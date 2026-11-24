"""A person's folder, scanned: the material map (docs/guides/inputs.md, The material map).

Intake no longer expects certain file names. `scan` walks any folder, deterministically and with no model,
and says for every file what happens to it:

- **read**: its text goes into the request in full;
- **summarised**: part of it goes in (a log's first and last lines, a table's header and first rows, a
  structured file's keys, or the first part of a long document when the budget is short);
- **listed**: it is named, not read (code, which becomes an inventory; binaries; housekeeping files; a
  document the budget had no room for; a PDF with no text layer);
- **skipped**, with the reason: excluded by the person, or it may hold secrets (never opened, or its text
  holds a credential). A secret is never read into the request and never shown.

The budget is the intake's limit (kernel.intake.MAX_SOURCE_CHARS). The most telling files are read
first: briefs and specs, then plans, reviews, handovers and the code inventory, then notes, slides and
other documents, then data and logs. Nothing is cut silently: the map's ``cut`` says what was cut and why.

`preview` is the same scan with nothing kept but the map: the person sees what would leave before
anything is sent (`rihmasto scan`, and the cockpit's "Scan the folder" step). `record` keeps the map in
the project (material.json) and a ledger record of its counts, never its contents. The formats are read
by kernel/material_read.py and the kinds, secrets and the inventory decided by kernel/material_kinds.py.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from kernel import material_kinds as mk
from kernel import material_read as mr

SCHEMA = "rihmasto.material-map/1"
MAX_FILES = 5000                 # files looked at; more are counted, never silently dropped
MAX_READ = 20 * 1024 * 1024      # a file larger than this is listed, not read
MAX_MANIFEST = 1024 * 1024
MIN_PART = 400                   # a part shorter than this is not worth sending: the file is listed instead
INVENTORY = "code inventory"
ACTIONS = ("read", "summarised", "listed", "skipped")
SECRET_WHY = "may hold secrets"


def _excluded(rel: str, patterns: Sequence[str]) -> str | None:
    """The person's pattern that drops ``rel``: an exact path, a glob on the path or the name, or a folder."""
    name = PurePosixPath(rel).name
    for pat in patterns:
        p = pat.replace("\\", "/").strip()
        p = p[2:] if p.startswith("./") else p
        if p and p != "." and (rel == p.rstrip("/") or fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(name, p)
                  or rel.startswith(p.rstrip("/") + "/")):
            return pat
    return None


def _walk(root: Path, patterns: Sequence[str]) -> tuple[list[str], list[dict[str, Any]], int]:
    """The folder's regular files (relative, POSIX, sorted), the folders not walked and why, and how many
    files were beyond MAX_FILES. A link is never followed."""
    files: list[str] = []
    dirs: list[dict[str, Any]] = []
    more = 0
    for here, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        base = Path(here)
        rel_here = base.relative_to(root).as_posix()
        keep = []
        for d in sorted(dirnames):
            rel = d if rel_here == "." else f"{rel_here}/{d}"
            why = ("a link: never followed" if (base / d).is_symlink() else
                   (f"excluded by you ({pat})" if (pat := _excluded(rel, patterns)) else
                    mk.skipped_dir(d, (base / d / "pyvenv.cfg").is_file())))
            if why:
                dirs.append({"path": rel + "/", "why": why})
            else:
                keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            rel = f if rel_here == "." else f"{rel_here}/{f}"
            if (base / f).is_symlink() or not (base / f).is_file():
                continue
            if len(files) >= MAX_FILES:
                more += 1
            else:
                files.append(rel)
    return sorted(files), dirs, more


def _row(rel: str, size: int, action: str, why: str, kind: str = "other", **more: Any) -> dict[str, Any]:
    ext = PurePosixPath(rel.lower()).suffix
    return {"path": rel, "size": size, "format": ext or "none", "kind": kind, "action": action, "why": why,
            "chars": 0, **more}


def _by_rule(rel: str, size: int, patterns: Sequence[str]) -> dict[str, Any] | None:
    """A file's row when its name or size decides it, before it is opened; None when it must be read."""
    name = PurePosixPath(rel).name
    ext = PurePosixPath(rel.lower()).suffix
    pat = _excluded(rel, patterns)
    if pat:
        return _row(rel, size, "skipped", f"excluded by you ({pat})")
    if mk.secret_by_name(rel):
        return _row(rel, size, "skipped", f"{SECRET_WHY}: never opened, by its name")
    if size > MAX_READ:
        return _row(rel, size, "listed", f"too large to read ({size / 1048576:.0f} MB)")
    if ext in (".doc", ".xls", ".ppt"):
        return _row(rel, size, "listed", "an older Office format the kernel does not read: save it as "
                                         f"{ext}x to have it read")
    if ext in mk.BINARY:
        return _row(rel, size, "listed", "binary: not read")
    if mk.HOUSEKEEPING.fullmatch(name):
        return _row(rel, size, "listed", "a housekeeping file: not the author's request")
    return None


class _Scan:
    """One walk of a folder: the rows, the documents with their text, the code and the manifests."""

    def __init__(self, root: Path, patterns: Sequence[str]) -> None:
        self.root = root
        self.patterns = list(patterns)
        self.rows: list[dict[str, Any]] = []
        self.docs: list[tuple[dict[str, Any], str]] = []
        self.code: list[str] = []
        self.manifests: dict[str, str] = {}
        self.ci: list[str] = []
        files, self.dirs, self.more = _walk(root, self.patterns)
        for rel in files:
            self.rows.append(self._look(rel))

    def _text(self, rel: str) -> str:
        return mr.decode((self.root / rel).read_bytes())

    def _code(self, rel: str, size: int, manifest: bool) -> dict[str, Any]:
        """Code is never read as text; it is checked for secrets, and a manifest's packages are named."""
        text = self._text(rel) if size <= MAX_MANIFEST else ""
        if text and mk.secret_in_text(rel, text):
            return _row(rel, size, "skipped", f"{SECRET_WHY}: its text holds a credential", kind="code")
        if manifest:
            self.manifests[rel] = text
            return _row(rel, size, "listed", "a dependency manifest: in the code inventory", kind="code")
        if mk.CI.search(rel):
            self.ci.append(rel)
            return _row(rel, size, "listed", "a CI workflow: in the code inventory", kind="code")
        self.code.append(rel)
        return _row(rel, size, "listed", "code: counted in the code inventory, not read", kind="code")

    def _look(self, rel: str) -> dict[str, Any]:
        path = self.root / rel
        try:
            size = path.stat().st_size
            decided = _by_rule(rel, size, self.patterns)
            if decided is not None:
                return decided
            name = PurePosixPath(rel).name
            if mk.MANIFESTS.fullmatch(name) or mk.CI.search(rel) or mk.language(rel):
                return self._code(rel, size, bool(mk.MANIFESTS.fullmatch(name)))
            return self._document(rel, size, path.read_bytes())
        except Exception as exc:  # one odd file never stops the scan: it is listed as not read, with the reason
            return _row(rel, 0, "listed", f"could not be read ({type(exc).__name__})")

    def _document(self, rel: str, size: int, data: bytes) -> dict[str, Any]:
        ext = PurePosixPath(rel.lower()).suffix
        if ext not in mr.READABLE and b"\0" in data[:8192]:
            return _row(rel, size, "listed", "binary: not read")
        got = mr.extract(data, ext)
        kind = mk.kind_of(rel, ext, got.text)
        if kind == "log" and ext != ".log":
            got = mr.extract(data, ext, log=True)
        raw = "" if ext in (*mr.OFFICE, ".pdf") else mr.decode(data[:1048576])   # what the format hides, too
        if mk.secret_in_text(rel, got.text) or (raw and mk.secret_in_text(rel, raw)):
            return _row(rel, size, "skipped", f"{SECRET_WHY}: its text holds a credential", kind=kind)
        if got.state == "not read" or not got.text.strip():
            return _row(rel, size, "listed", f"not read: {got.note or 'no text'}", kind=kind)
        row = _row(rel, size, "pending", "", kind=kind, state=got.state, **({"note": got.note} if got.note else {}))
        self.docs.append((row, got.text))
        return row


def heading(rel: str, kind: str) -> str:
    """The line a part of the request starts with: its file and its kind."""
    if rel == INVENTORY:
        return f"## {INVENTORY}"
    shown = "".join(ch if ch.isprintable() else "?" for ch in rel)
    return f"## {shown} ({mk.KIND_LABEL.get(kind, kind)})"


def _cut_at(text: str, n: int) -> str:
    """The first ``n`` characters, ending at a line break when there is one in the last fifth."""
    part = text[:n]
    nl = part.rfind("\n")
    return part[:nl] if nl > n * 4 // 5 else part


def _readme(rel: str) -> bool:
    """A README at the top of the folder: what the folder says about itself, read first."""
    return "/" not in rel and rel.lower().startswith("readme")


def _allocate(docs: list[tuple[dict[str, Any], str]], budget: int) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Read the most telling first, within the budget: each document in full, summarised, or listed.
    Returns the parts (path, heading, text) in order and the notes of what was cut and why."""
    order = sorted(docs, key=lambda d: (mk.PRIORITY.get(d[0]["kind"], 2), not _readme(d[0]["path"]),
                                        d[0]["path"].count("/"), d[0]["path"].lower()))
    parts: list[tuple[str, str, str]] = []
    cut: list[str] = []
    room = budget
    for i, (row, text) in enumerate(order):
        head = heading(row["path"], row["kind"])
        cost = len(head) + 4
        waiting = len(order) - i - 1
        cap = room - min(MIN_PART * waiting, room // 2)
        summary = row["state"] == "summarised"
        if len(text) + cost <= cap:
            take, action = text, "summarised" if summary else "read"
            why = row.get("note") or ("" if summary else "read in full")
        elif cap - cost >= MIN_PART:
            take, action = _cut_at(text, cap - cost), "summarised"
            why = f"the budget: its first {len(_cut_at(text, cap - cost)):,} of {len(text):,} characters"
            cut.append(f"{row['path']}: {why}")
        else:
            row.update(action="listed", why=f"the budget of {budget:,} characters went to more telling files")
            cut.append(f"{row['path']}: listed only, {len(text):,} characters not read (the budget)")
            continue
        row.update(action=action, why=why, chars=len(take) + cost, of=len(text))
        room -= len(take) + cost + 2
        parts.append((row["path"], head, take))
    return parts, cut


def _digest(text: str) -> str:
    """The request's sha256 as kernel.access reads a request (LF line endings, ends trimmed), so a request
    filed in the cockpit carries the same digest in its map and in its signed record."""
    from kernel.access import request_digest

    return request_digest(text)


def _totals(rows: list[dict[str, Any]], chars: int, budget: int) -> dict[str, Any]:
    out: dict[str, Any] = {a: sum(1 for r in rows if r["action"] == a) for a in ACTIONS}
    out.update(files=len(rows), secrets=sum(1 for r in rows if r["why"].startswith(SECRET_WHY)),
               excluded=sum(1 for r in rows if r["why"].startswith("excluded by you")),
               code=sum(1 for r in rows if r["kind"] == "code" and r["action"] == "listed"),
               chars=chars, budget=budget)
    return out


def gather(folder: str | Path, exclude: Iterable[str] = (), budget: int | None = None
           ) -> tuple[dict[str, Any], str, list[tuple[str, str]]]:
    """Scan ``folder``: the map, the request text built from it, and its documents (name, text) in order."""
    from kernel.intake import MAX_SOURCE_CHARS

    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"{root} is not a folder")
    budget = budget or MAX_SOURCE_CHARS
    scan = _Scan(root, [p for p in exclude if str(p).strip()])
    inv = mk.inventory(scan.code, scan.manifests, scan.ci) if scan.code else None
    docs = list(scan.docs)
    if inv:
        note = "the code by rule: languages, entry points, tests, manifests, CI"
        docs.append(({"path": INVENTORY, "kind": "code", "state": "summarised", "note": note}, mk.inventory_text(inv)))
    parts, cut = _allocate(docs, budget)
    if scan.more:
        cut.append(f"{scan.more:,} files were not looked at: a scan looks at the first {MAX_FILES:,} files")
    text = "\n\n".join(f"{head}\n\n{body}" for _, head, body in parts)
    rows = sorted(scan.rows, key=lambda r: r["path"].lower())
    mp = {"schema": SCHEMA, "folder": str(root), "budget": budget, "exclude": list(scan.patterns),
          "files": rows, "order": [{"path": p, "heading": h} for p, h, _ in parts], "inventory": inv,
          "skipped_dirs": scan.dirs[:200], "not_looked_at": scan.more, "cut": cut,
          "totals": _totals(rows, len(text), budget), "request_sha256": _digest(text)}
    return mp, text, [(p, body) for p, _, body in parts]


def scan(folder: str | Path, exclude: Iterable[str] = (), budget: int | None = None) -> dict[str, Any]:
    """The material map of ``folder``: every file with what happens to it and why. Its contents are not kept."""
    return gather(folder, exclude, budget)[0]


def preview(folder: str | Path, exclude: Iterable[str] = ()) -> dict[str, Any]:
    """What would leave, before anything is sent: the map, with secret-looking files skipped unread."""
    return scan(folder, exclude)


def has_code(mp: dict[str, Any]) -> bool:
    return bool(mp.get("inventory")) or any(r["kind"] == "code" for r in mp["files"])


def documents_of(mp: dict[str, Any], text: str) -> list[tuple[str, str]] | None:
    """The documents of a request built from ``mp`` (``text`` as kept, its digest matching), or None."""
    if mp.get("schema") != SCHEMA or mp.get("request_sha256") != _digest(text):
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    heads = [o["heading"] for o in mp["order"]]
    starts, at = [], 0
    for head in heads:
        at = text.find(head, at)
        if at < 0:
            return None
        starts.append(at)
        at += len(head)
    ends = starts[1:] + [len(text) + 2]
    return [(o["path"], text[s + len(o["heading"]):e - 2].strip("\n"))
            for o, s, e in zip(mp["order"], starts, ends, strict=True)]


def recorded(project: Any, text: str) -> list[tuple[str, str]] | None:
    """The documents of a request a person confirmed from a scan (the project's material.json), or None."""
    mp = project.read("material.json", None)
    return documents_of(mp, text) if isinstance(mp, dict) else None


def record(project: Any, mp: dict[str, Any], *, person: str | None, persona: str | None = None,
           confirmed: str = "") -> None:
    """Keep the map in the project and record its counts in the ledger: never a file's contents."""
    project.write("material.json", mp)
    t = mp["totals"]
    project.log("material_scanned", {
        "folder": mp["folder"], **{k: t[k] for k in ("files", *ACTIONS, "secrets", "excluded", "code", "chars",
                                                       "budget")},
        "cut": len(mp["cut"]), "not_looked_at": mp["not_looked_at"], "request_sha256": mp["request_sha256"],
        "person": person, "persona": persona, "confirmed": confirmed or "not asked: called by the kernel"})
