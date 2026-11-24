"""The pack guard of the paved-road product template (docs/portability.md, FR-PT5).

kernel/scaffold.py writes PACK_GUARD_PY into every product as `factory/pack_guard.py`, a protected
path, and the template's Dockerfile starts the image through it, so the guard does not rest on
app/server.py, which a builder may change. The text is a standard-library Python module for the
product's image; it is kept here, apart from the rest of the template.
"""

from __future__ import annotations

PACK_GUARD_PY = r'''"""pack_guard: the product checks the capability pack it came with before it says it is ready.

Written by Rihmasto into every paved-road product (docs/portability.md); not the builder's to change.
It is the image's entrypoint (the Dockerfile's CMD) and lives in factory/, a protected path, so it does
not rest on app/server.py, which a builder may change. Without RIHMA_PACK it hands over to the
product's server unchanged: the guard is off, as on the factory's roads. The site mounts the pack
beside the image, never in it (the pack pins the image's digest), and sets RIHMA_PACK,
RIHMA_PACK_SHA256, RIHMA_PACK_STATUS (rihma.pack-status/1, read again every RIHMA_PACK_STATUS_EVERY
seconds, 900 by default) and RIHMA_STATUS_GRACE (seconds an expired status still counts, for
air-gapped sites). The guard then serves the product itself, and until the pack's hash, the app and
runtime file trees, the status (valid, unexpired, this pack) and the smoke set pass, /health answers
503 with the reasons.

It keeps the newest status it has seen for each pack in DATA_DIR. A status issued before that one is
a replay and is not taken, a withdrawal is final, and a status that cannot be read (missing,
corrupt, half written) falls back to the newest seen, so none of these undoes a withdrawal, also
after a restart. It cooperates with the operator, it is not DRM; the verifier checks signatures.
"""

import datetime
import hashlib
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

UNHASHED = ("acceptance", "provenance", "security", "version", "content_sha256")
STATUS = "rihma.pack-status/1"
SEEN = ".pack-status-seen.json"  # in DATA_DIR: the newest status seen, by the pack's content_sha256


def pack_hash(pack):
    """The pack's content_sha256, as the factory computes it (kernel/packs.py)."""
    body = {k: v for k, v in pack.items() if k not in UNHASHED}
    body["provenance"] = {k: v for k, v in (pack.get("provenance") or {}).items() if k != "ledger_head"}
    acc = pack.get("acceptance") or {}
    body["acceptance"] = {"criteria": acc.get("criteria"), "holdout_scores": acc.get("holdout_scores")}
    declared = body.get("declared")
    if isinstance(declared, dict) and isinstance(declared.get("site_mode"), dict):
        body["declared"] = dict(declared, site_mode={k: v for k, v in declared["site_mode"].items() if k != "source"})
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tree_hash(root, names):
    """sha256 over '<sha256 of the file, CRLF read as LF>  <path>' lines, sorted by path."""
    lines = []
    for name in sorted(names):
        with open(os.path.join(root, name), "rb") as fh:
            lines.append(hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest() + "  " + name + "\n")
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def app_files(root):
    found = []
    for folder, dirs, names in os.walk(os.path.join(root, "app")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        found += [os.path.relpath(os.path.join(folder, n), root).replace(os.sep, "/")
                  for n in names if not n.endswith(".pyc")]
    return found


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def issued(doc):
    """When a status document was issued (aware, UTC when it names no zone), or None when unreadable."""
    try:
        moment = datetime.datetime.fromisoformat(str(doc.get("issued_at")).replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=datetime.timezone.utc)


class Guard:
    def __init__(self, handle, root, env=None):
        self.handle, self.root, self.env = handle, root, dict(os.environ if env is None else env)
        self.ready, self.reasons, self.version = False, ["starting: the pack is being checked"], None
        self.kept = os.path.join(self.env.get("DATA_DIR", "data"), SEEN)
        seen = load(self.kept)
        self.seen = seen if isinstance(seen, dict) else {}

    def check(self):
        """One round of every check; /health follows it."""
        try:
            pack = load(self.env["RIHMA_PACK"])
            if not isinstance(pack, dict):
                raise ValueError("RIHMA_PACK names no readable pack")
            reasons = self._pack(pack)
            reasons += self._status(pack) + ([] if reasons else self._smoke(pack))
            version = pack.get("version")
        except Exception as exc:  # a guard that cannot check is not ready
            reasons, version = [f"the pack cannot be checked: {type(exc).__name__}: {exc}"], None
        self.version, self.reasons, self.ready = version, reasons, not reasons
        return reasons

    def _pack(self, pack):
        out, digest, pinned = [], pack_hash(pack), pack.get("pinned") or {}
        if digest != pack.get("content_sha256"):
            out.append("the pack's content does not hash to its content_sha256")
        if (self.env.get("RIHMA_PACK_SHA256") or digest) != digest:
            out.append("the pack is not the one the deploy package names (RIHMA_PACK_SHA256)")
        if tree_hash(self.root, app_files(self.root)) != pinned.get("app_files_sha256"):
            out.append("the app files differ from those the pack pins")
        runtime = pinned.get("runtime_files") or []
        if any(not os.path.isfile(os.path.join(self.root, n)) for n in runtime) \
                or tree_hash(self.root, runtime) != pinned.get("runtime_files_sha256"):
            out.append("the runtime files differ from those the pack pins")
        return out

    def _status(self, pack):
        """Judge the newest status seen for this pack: the file's, unless it is older than one seen
        before (a replay) or a withdrawal was seen (it is final); the newest seen when the file cannot
        be read."""
        digest = pack_hash(pack)
        newest = self.seen.get(digest)
        doc = load(self.env["RIHMA_PACK_STATUS"]) if self.env.get("RIHMA_PACK_STATUS") else None
        if doc is not None:
            if not isinstance(doc, dict) or doc.get("format") != STATUS:
                return ["the status document is not " + STATUS]
            if [doc.get(k) for k in ("pack", "version", "content_sha256")] != [pack.get("pack"), pack.get("version"),
                                                                                 digest]:
                return ["the status document names another pack"]
            if newest is None or self._replaces(doc, newest):
                newest = self._remember(digest, doc)
        if newest is None:
            return ["no status document can be read (RIHMA_PACK_STATUS), and none was seen before"]
        return self._judge(newest)

    @staticmethod
    def _replaces(doc, newest):
        """A status replaces the newest seen unless that one withdrew the pack, or it was issued before it."""
        if newest.get("state") == "withdrawn":
            return False
        when, before = issued(doc), issued(newest)
        return when is not None and (before is None or when >= before)

    def _remember(self, digest, doc):
        """Keep the newest status seen in DATA_DIR, written whole (a temporary file, then a rename)."""
        if self.seen.get(digest) != doc:
            self.seen[digest] = doc
            try:
                with open(self.kept + ".tmp", "w", encoding="utf-8") as fh:
                    json.dump(self.seen, fh)
                os.replace(self.kept + ".tmp", self.kept)
            except OSError:  # a read-only DATA_DIR: kept in memory until the process ends
                pass
        return doc

    def _judge(self, doc):
        if doc.get("state") != "valid":
            who = (doc.get("decided_by") or {}).get("person")
            return [f"the pack is {doc.get('state')}: {doc.get('reason')}" + (f" (decided by {who})" if who else "")]
        try:
            expires = datetime.datetime.fromisoformat(str(doc.get("expires_at")).replace("Z", "+00:00"))
            grace = datetime.timedelta(seconds=float(self.env.get("RIHMA_STATUS_GRACE") or 0))
            expired = datetime.datetime.now(datetime.timezone.utc) > expires + grace
        except (ValueError, TypeError):
            return ["the status document has no readable expires_at"]
        return [f"the status document expired at {doc.get('expires_at')}"] if expired else []

    def _smoke(self, pack):
        out = []
        for check in (pack.get("smoke") or {}).get("checks") or []:
            path, want = check.get("path", "/"), check.get("expect_status", 200)
            got = self.handle("GET", path)[0] if check.get("method", "GET") == "GET" else "not run (not a GET)"
            if got != want:
                out.append(f"smoke {check.get('method', 'GET')} {path}: {got}, expected {want}")
        return out

    def start(self):
        def rounds():
            while True:
                self.check()
                time.sleep(max(float(self.env.get("RIHMA_PACK_STATUS_EVERY") or 900), 0.05))
        threading.Thread(target=rounds, name="pack_guard", daemon=True).start()
        return self


GUARDS = {}  # the one guard of this process, by the product's root: /health and a capability's faces ask it
_GUARDS_LOCK = threading.Lock()


def shared(handle, root):
    """The process's guard for ``root``, checked once before it is handed out and then every round, so
    /health and every face judge alike from their first request."""
    key = os.path.normcase(os.path.abspath(root))
    with _GUARDS_LOCK:
        if key not in GUARDS:
            guard = Guard(handle, root)
            guard.check()
            GUARDS[key] = guard.start()
        return GUARDS[key]


class Failed:
    """A pack is mounted but the guard cannot run: never ready."""

    ready, version = False, None

    def __init__(self, why):
        self.reasons = [why]


def _reply(handler, status, body):
    data = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def guarded(base, guard, handle):
    """The product's request handler with /health answered by the guard: 503 with the reasons until
    every check passes, then the product's own /health with the pack's version."""
    serve_app = getattr(base, "do_GET", None)

    class Guarded(base):
        def do_GET(self):
            if urlsplit(self.path).path != "/health" and serve_app is not None:
                return serve_app(self)
            version = os.environ.get("APP_VERSION", "dev")
            if not guard.ready:
                return _reply(self, 503, {"status": "not ready", "version": version, "guard": list(guard.reasons)})
            try:
                status, body = handle("GET", "/health")[:2]
            except Exception as exc:  # the product's own /health broke: not ready
                why = f"the product's /health failed: {type(exc).__name__}"
                return _reply(self, 503, {"status": "not ready", "version": version, "guard": [why]})
            return _reply(self, status, dict(body, pack=guard.version) if isinstance(body, dict) else body)

        def log_message(self, fmt, *args):
            return

    return Guarded


def serve(root=None):
    """The image's entrypoint (the Dockerfile's CMD): the product, guarded when a pack is beside it."""
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    if not os.environ.get("RIHMA_PACK"):  # no pack beside the image: the product's server, unguarded
        from app.server import main

        return main()
    try:
        from app import server
        import app.routes  # noqa: F401  (registers the product's routes)

        guard, base, handle = shared(server.handle, root), server.Handler, server.handle
    except Exception as exc:  # a pack is mounted but no guard runs: never ready
        guard = Failed(f"pack_guard cannot start: {type(exc).__name__}: {exc}")
        base, handle = BaseHTTPRequestHandler, None
    host, port = os.environ.get("HOST", "0.0.0.0"), int(os.environ.get("PORT", "8080"))
    ThreadingHTTPServer((host, port), guarded(base, guard, handle)).serve_forever()


if __name__ == "__main__":  # run as a file: serve from the importable copy, whose guard the faces share
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from factory.pack_guard import serve as _serve

    _serve()
'''
