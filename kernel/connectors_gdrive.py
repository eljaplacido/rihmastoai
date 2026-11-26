"""Google Drive for a capability Rihmasto builds: new files in a folder, a download, an upload (FR-GDR1).

Standard library only, and nothing imported from Rihmasto: a product that declares a `gdrive` integration
gets this file as `app/gdrive.py` (kernel/compile.py), and imports it there:

    from app.gdrive import Drive
    drive = Drive.from_env("recordings")              # RECORDINGS_URL, RECORDINGS_ACCESS, a credential by name
    cursor = drive.load_cursor(transcripts_folder)    # where the last run stopped, kept in Drive itself
    batch = drive.list_new(recordings_folder, cursor, mime_prefixes=("audio/", "video/"))
    for f in batch.files:
        audio = drive.download(f["id"])
        drive.upload(transcripts_folder, f["name"] + ".txt", transcribe(audio), "text/plain")
    drive.save_cursor(transcripts_folder, batch.cursor)

It speaks the Drive v3 REST API at `<NAME>_URL` (https://www.googleapis.com; a stand-in at the gate). Each
run picks up only what is new: `list_new` reads every page of the folder's files modified at or after the
cursor's time, skips the ones the cursor saw at that very time, and returns the cursor to keep.

**Credentials, by name only** (the declaration names them; IT says where each lives on the paved road):
1. `<NAME>_TOKEN`: an OAuth access token, for a local run (`gcloud auth print-access-token` with the scope);
2. `<NAME>_KEY_FILE`: the path of a service account's JSON key: a JWT signed with its key (RS256) is
   exchanged at the key's token_uri;
3. neither: the metadata server of the Google Cloud runtime, asked for the Drive scopes: on Cloud Run, the
   road's runtime service account (workload identity), with no key anywhere. Share the folder with it.

**Scopes:** read: `drive.readonly`; read-write: `drive.readonly` and `drive.file` (it may create files and
change the files it created). An integration declared read never uploads: `upload` refuses.

Nothing is logged or printed. An error names the call, Drive's status and its message: never a token, a
key or a file's content.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any

SCOPES = {"read": ("https://www.googleapis.com/auth/drive.readonly",),
          "read-write": ("https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/drive.file")}
DEFAULT_URL = "https://www.googleapis.com"
TOKEN_URI = "https://oauth2.googleapis.com/token"
FIELDS = "nextPageToken,files(id,name,mimeType,modifiedTime,size,md5Checksum)"
FOLDER_MIME = "application/vnd.google-apps.folder"
CURSOR_FILE = ".rihmasto-cursor.json"
FILE_ID = re.compile(r"[A-Za-z0-9_-]{1,200}\Z")
STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?Z\Z")
SHA256_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


class DriveError(RuntimeError):
    """A Drive call that did not succeed: the call, the status and Drive's message, never a token."""

    def __init__(self, call: str, status: int | None, message: str) -> None:
        super().__init__(f"Drive {call}: {status if status is not None else 'no answer'}: {message}"[:500])
        self.call, self.status = call, status


@dataclass
class Batch:
    """What `list_new` found: the new files, oldest first, and the cursor to keep for the next run."""

    files: list[dict[str, Any]] = field(default_factory=list)
    cursor: dict[str, Any] = field(default_factory=dict)
    pages: int = 0


# -- RS256 for a service account's key, in the standard library ----------------------------------------

def _der(data: bytes, i: int) -> tuple[int, bytes, int]:
    """One DER element at ``i``: its tag, its content and the index after it."""
    tag, length, i = data[i], data[i + 1], i + 2
    if length & 0x80:
        n = length & 0x7F
        length, i = int.from_bytes(data[i:i + n], "big"), i + n
    return tag, data[i:i + length], i + length


def _seq(content: bytes) -> list[tuple[int, bytes]]:
    out, i = [], 0
    while i < len(content):
        tag, value, i = _der(content, i)
        out.append((tag, value))
    return out


def rsa_private_key(pem: str) -> tuple[int, int]:
    """(n, d) of a PKCS#8 ("BEGIN PRIVATE KEY") RSA key, as a service account's JSON key holds it."""
    body = "".join(line for line in pem.strip().splitlines() if not line.startswith("-----"))
    _, info, _ = _der(base64.b64decode(body), 0)
    parts = _seq(info)
    if len(parts) < 3 or parts[2][0] != 0x04:
        raise ValueError("not a PKCS#8 private key")
    _, rsa, _ = _der(parts[2][1], 0)
    ints = [int.from_bytes(v, "big") for t, v in _seq(rsa) if t == 0x02]
    if len(ints) < 4:
        raise ValueError("not an RSA private key")
    return ints[1], ints[3]


def _b64(data: bytes) -> str:
    """Base64url without padding, as a JWT writes it (this file imports nothing from Rihmasto)."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def sign_rs256(message: bytes, key: tuple[int, int]) -> bytes:
    """RSASSA-PKCS1-v1_5 with SHA-256 (RFC 8017, 8.2.1)."""
    n, d = key
    size = (n.bit_length() + 7) // 8
    info = SHA256_INFO + hashlib.sha256(message).digest()
    em = b"\x00\x01" + b"\xff" * (size - 3 - len(info)) + b"\x00" + info
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(size, "big")


def assertion(key_doc: dict[str, Any], scopes: tuple[str, ...], now: int) -> str:
    """The signed JWT a service account exchanges for an access token (the JWT bearer grant)."""
    claims = {"iss": key_doc["client_email"], "scope": " ".join(scopes), "aud": key_doc.get("token_uri") or TOKEN_URI,
              "iat": now, "exp": now + 3600}
    head = {"alg": "RS256", "typ": "JWT"}
    if key_doc.get("private_key_id"):
        head["kid"] = key_doc["private_key_id"]
    signing = f"{_b64(json.dumps(head).encode())}.{_b64(json.dumps(claims).encode())}".encode("ascii")
    return signing.decode("ascii") + "." + _b64(sign_rs256(signing, rsa_private_key(key_doc["private_key"])))


# -- the client --------------------------------------------------------------------------------------

class Drive:
    """A Drive v3 client for one declared integration."""

    def __init__(self, url: str = DEFAULT_URL, *, access: str = "read", token: str | None = None,
                 key_file: str | None = None, metadata_host: str | None = None, timeout: float = 60.0,
                 retries: int = 2, backoff: float = 0.5) -> None:
        if access not in SCOPES:
            raise ValueError(f"access must be one of {tuple(SCOPES)}")
        self.url, self.access, self.timeout = url.rstrip("/"), access, timeout
        self.retries, self.backoff = retries, backoff
        self._token, self._key_file = token, key_file
        self._metadata = metadata_host or os.environ.get("GCE_METADATA_HOST") or "metadata.google.internal"
        self._expires = float("inf") if token else 0.0

    @classmethod
    def from_env(cls, name: str, environ: dict[str, str] | None = None, **kwargs: Any) -> Drive:
        """The client for the integration ``name``, from the settings and credentials the road gives by name."""
        env, prefix = environ if environ is not None else os.environ, name.upper()
        return cls(env.get(f"{prefix}_URL") or DEFAULT_URL, access=env.get(f"{prefix}_ACCESS") or "read",
                   token=env.get(f"{prefix}_TOKEN") or None, key_file=env.get(f"{prefix}_KEY_FILE") or None, **kwargs)

    @property
    def scopes(self) -> tuple[str, ...]:
        return SCOPES[self.access]

    # -- the access token, never kept anywhere but this object ---------------------------------------

    def _post_form(self, url: str, form: dict[str, str], call: str) -> dict[str, Any]:
        body = urllib.parse.urlencode(form).encode("ascii")
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        return json.loads(self._send(req, call) or b"{}")

    def token(self) -> str:
        """An access token for the Drive scopes, renewed a minute before it expires."""
        if self._token and time.time() < self._expires - 60:
            return self._token
        if self._key_file:
            with open(self._key_file, encoding="utf-8") as fh:
                key_doc = json.load(fh)
            got = self._post_form(key_doc.get("token_uri") or TOKEN_URI, {
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion(key_doc, self.scopes, int(time.time()))}, "token exchange")
        else:
            url = (f"http://{self._metadata}/computeMetadata/v1/instance/service-accounts/default/token?"
                   + urllib.parse.urlencode({"scopes": ",".join(self.scopes)}))
            req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
            got = json.loads(self._send(req, "metadata token", authorize=False) or b"{}")
        if not got.get("access_token"):
            raise DriveError("token", None, "no access token in the answer")
        self._token, self._expires = str(got["access_token"]), time.time() + float(got.get("expires_in") or 3600)
        return self._token

    # -- HTTP --------------------------------------------------------------------------------------------

    def _send(self, req: urllib.request.Request, call: str, *, authorize: bool = False) -> bytes:
        for attempt in range(self.retries + 1):
            if authorize:
                req.add_header("Authorization", "Bearer " + self.token())
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                status, raw = exc.code, exc.read()
                exc.close()
                if (status == 429 or status >= 500) and attempt < self.retries:
                    time.sleep(self.backoff * (2 ** attempt))
                    continue
                if status == 401 and authorize and attempt < self.retries and self._expires != float("inf"):
                    self._expires = 0.0      # a token from a key or the metadata server is fetched once more
                    continue
                raise DriveError(call, status, _message(raw)) from None
            except (urllib.error.URLError, OSError) as exc:
                if attempt < self.retries:
                    time.sleep(self.backoff * (2 ** attempt))
                    continue
                raise DriveError(call, None, type(exc).__name__) from None
        raise DriveError(call, None, "no attempt left")  # pragma: no cover - the loop returns or raises

    def _call(self, method: str, path: str, query: dict[str, Any] | None = None, body: bytes | None = None,
              ctype: str | None = None, call: str = "") -> bytes:
        url = self.url + path + ("?" + urllib.parse.urlencode(query) if query else "")
        req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": ctype} if ctype else {})
        return self._send(req, call or f"{method} {path}", authorize=True)

    # -- what a capability does ------------------------------------------------------------------------

    def list_new(self, folder_id: str, cursor: dict[str, Any] | None = None, *, page_size: int = 100,
                 mime_prefixes: tuple[str, ...] = ()) -> Batch:
        """Every file in the folder that arrived since ``cursor`` (all of them with no cursor), oldest first,
        across every page, and the cursor for the next run."""
        after, seen = _cursor(cursor)
        q = f"'{_file_id(folder_id)}' in parents and trashed = false and mimeType != '{FOLDER_MIME}'"
        q += f" and modifiedTime >= '{after}'" if after else ""
        batch, token = Batch(), None
        while True:
            query = {"q": q, "orderBy": "modifiedTime", "pageSize": page_size, "fields": FIELDS,
                     "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
            if token:
                query["pageToken"] = token
            page = json.loads(self._call("GET", "/drive/v3/files", query, call="list files") or b"{}")
            batch.pages += 1
            batch.files += [f for f in page.get("files") or []
                            if not (f.get("modifiedTime") == after and f.get("id") in seen)
                            and (not mime_prefixes or str(f.get("mimeType", "")).startswith(mime_prefixes))]
            token = page.get("nextPageToken")
            if not token:
                break
        batch.files.sort(key=lambda f: (str(f.get("modifiedTime", "")), str(f.get("id", ""))))
        batch.cursor = _next_cursor(after, seen, batch.files)
        return batch

    def download(self, file_id: str) -> bytes:
        """A file's bytes (`alt=media`). They are handed back, never kept or logged here."""
        return self._call("GET", f"/drive/v3/files/{_file_id(file_id)}", {"alt": "media", "supportsAllDrives": "true"},
                          call="download")

    def upload(self, folder_id: str, name: str, data: bytes, mime_type: str = "text/plain") -> dict[str, Any]:
        """A new file in the folder (a multipart upload); its id and name. Refused when declared read."""
        self._writable()
        meta = {"name": name, "parents": [_file_id(folder_id)], "mimeType": mime_type}
        boundary = "rihmasto-" + uuid.uuid4().hex
        head = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
                f"--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n")
        body = head.encode() + data + f"\r\n--{boundary}--\r\n".encode()
        out = self._call("POST", "/upload/drive/v3/files", {"uploadType": "multipart", "supportsAllDrives": "true",
                                                            "fields": "id,name"}, body,
                         f"multipart/related; boundary={boundary}", call="upload")
        return json.loads(out or b"{}")

    def update(self, file_id: str, data: bytes, mime_type: str = "application/json") -> dict[str, Any]:
        """New content for a file this integration created (`drive.file`)."""
        self._writable()
        out = self._call("PATCH", f"/upload/drive/v3/files/{_file_id(file_id)}",
                         {"uploadType": "media", "supportsAllDrives": "true", "fields": "id,name"}, data, mime_type,
                         call="update")
        return json.loads(out or b"{}")

    def find(self, folder_id: str, name: str) -> list[dict[str, Any]]:
        """The files of that name in the folder: a run asks before it writes, so a rerun writes nothing twice."""
        escaped = name.replace("\\", "\\\\").replace("'", "\\'")
        q = f"'{_file_id(folder_id)}' in parents and trashed = false and name = '{escaped}'"
        page = json.loads(self._call("GET", "/drive/v3/files", {"q": q, "fields": FIELDS, "supportsAllDrives": "true",
                                                                 "includeItemsFromAllDrives": "true"},
                                     call="find") or b"{}")
        return list(page.get("files") or [])

    def load_cursor(self, folder_id: str, name: str = CURSOR_FILE) -> dict[str, Any] | None:
        """The cursor a previous run kept in the folder, or None before the first run."""
        found = self.find(folder_id, name)
        return json.loads(self.download(found[0]["id"]) or b"null") if found else None

    def save_cursor(self, folder_id: str, cursor: dict[str, Any], name: str = CURSOR_FILE) -> dict[str, Any]:
        data = json.dumps(cursor, sort_keys=True).encode("utf-8")
        found = self.find(folder_id, name)
        return self.update(found[0]["id"], data) if found else self.upload(folder_id, name, data, "application/json")

    def _writable(self) -> None:
        if self.access != "read-write":
            raise PermissionError("this Drive integration is declared read: it never writes")


def _file_id(value: str) -> str:
    if not FILE_ID.match(str(value)):
        raise ValueError("a Drive file or folder id is letters, digits, _ and -")
    return str(value)


def _cursor(cursor: dict[str, Any] | None) -> tuple[str | None, set[str]]:
    if not cursor:
        return None, set()
    after = cursor.get("modified_after")
    if after is not None and not STAMP.match(str(after)):
        raise ValueError("the cursor's modified_after is not an RFC 3339 time in UTC")
    return after, {str(x) for x in cursor.get("seen") or []}


def _next_cursor(after: str | None, seen: set[str], files: list[dict[str, Any]]) -> dict[str, Any]:
    if not files:
        return {"modified_after": after, "seen": sorted(seen)}
    last = max(str(f.get("modifiedTime", "")) for f in files)
    at_last = {str(f["id"]) for f in files if f.get("modifiedTime") == last}
    return {"modified_after": last, "seen": sorted(at_last | (seen if last == after else set()))}


def _message(raw: bytes) -> str:
    try:
        doc = json.loads(raw or b"{}")
    except ValueError:
        return "the answer was not JSON"
    err = doc.get("error") if isinstance(doc, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or err.get("status") or "an error")[:300]
    return str(doc.get("error_description") or err or "an error")[:300] if isinstance(doc, dict) else "an error"
