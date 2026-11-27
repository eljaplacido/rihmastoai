"""A project's own sources (FR-SRC1): where an adopted or attached project keeps its requirements, criteria, tests,
test results, findings and tasks, said by the project, proposed by Rihmasto, and read as the truth.

The owner (2026-11-26): "Im still not happy with clarity, when I jump into [an adopted project] its not clear what
should I do and claude code in IDE didnt find most of insights relevant". A project's real requirements may be a
folder of rule files, its real tests a gate run on another machine, its real plan a round's README: guessing them
from old documents misleads. Here a person maps each source (kernel/native_detect.py proposes them by rule):

- ``native_sources.json``: the mapped sources: kind, adapter, the glob of files, the field mapping, how often it
  is read again (on a new commit, daily, weekly, or by hand), who mapped it; stopped ones are kept, stopped; and
  the planning documents a person said to use although they may be old plans;
- ``native_read.json``: the latest read of every mapped source: requirements, tasks, findings and committed results,
  each with its path and line, and per source the files, the records and what could not be read.

Mapping, changing, stopping, using an old plan anyway and reading are signed and in the ledger. Nothing is ever
written to the repository. The contract, tasks, findings and traceability then come from these records
(kernel/native_apply.py), each marked as from the project's own source.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from kernel import native_detect as nd
from kernel import native_readers as nr
from kernel import native_tests as nt

FILE = "native_sources.json"
READ = "native_read.json"
KINDS = {"requirements": "Requirements and criteria", "findings": "Findings", "tasks": "Tasks",
         "results": "Test results", "tests": "Test roots and commands"}
ADAPTERS = {"requirements": ("records",), "findings": ("jsonl", "records"), "tasks": ("markdown",),
            "results": ("results",), "tests": ("command",)}
FIELDS = ("id", "title", "statement", "criteria", "test", "status", "severity", "where")
EVERY = ("commit", "daily", "weekly", "manual")
EVERY_SAID = {"commit": "on every new commit", "daily": "daily", "weekly": "weekly", "manual": "when asked"}
MAPPERS = ("developer", "product_owner", "it", "operations")
MAX_FILES = 400
MAX_KEPT = 5000
_GLOB = re.compile(r"[A-Za-z0-9_.*?/@+ -]{1,200}\Z")
_KEY = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")
SCOPE = {"project": "Project-specific: which files are this project's requirements, findings, tasks and test results, "
                    "and how often they are read again",
         "platform": "Platform-wide: the adapters (JSON and YAML records, JSONL findings, markdown tables and "
                     "checklists, JUnit, TAP and JSON results) and the old-plan rule (a planning document "
                     f"{nd.STALE_DAYS} days older than the code's newest commit, with {nd.STALE_COMMITS} commits "
                     "since) are the same for every project"}


class SourcesRefused(PermissionError):
    """A mapping that may not be made, or not by this person."""


def applies(project: Any) -> bool:
    return project.meta.get("source_kind") in ("adopted", "attached")


def where(project: Any) -> tuple[Path, str]:
    """The repository and revision the sources are read from: an adopted project's upstream as last fetched (the
    baseline before any), an attached repository's branch."""
    from kernel.native_history import absolute, upstream_ref
    from kernel.repo_structure import _git

    if project.meta.get("source_kind") == "attached":
        info = project.meta.get("attached") or {}
        return absolute(info["repo"]), info.get("branch") or "HEAD"
    bare = absolute(project.path("repo.git"))
    adopted = project.read("adopted.json", {}) or {}
    upstream = upstream_ref(project)
    if _git(bare, "rev-parse", "--verify", "-q", upstream + "^{commit}").strip():
        return bare, upstream
    return bare, adopted.get("baseline") or "main"


def _src(project: Any) -> Any:
    from kernel import repo_structure

    return repo_structure.source_of(project)


def _book(project: Any) -> dict[str, Any]:
    return project.read(FILE, None) or {"n": 0, "sources": [], "use_anyway": []}


def active(project: Any) -> list[dict[str, Any]]:
    return [s for s in _book(project)["sources"] if s.get("state") == "mapped"]


def mapped_roots_of(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for s in sources if s.get("state") == "mapped" and s["kind"] == "tests" for r in s.get("roots") or []]


def mapped_roots(project: Any) -> list[dict[str, Any]]:
    return mapped_roots_of(_book(project)["sources"])


def _view(project: Any) -> dict[str, Any]:
    from kernel.native_apply import view

    return view(project)


def use_anyway_paths(project: Any) -> list[str]:
    return list(_book(project).get("use_anyway") or [])


def glob_re(glob: str) -> re.Pattern:
    """A glob as a pattern over repository paths: ``**/`` any folders, ``*`` within one, ``?`` one character."""
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif glob.startswith("**", i):
            out, i = out + ".*", i + 2
        elif glob[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif glob[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(glob[i]), i + 1
    return re.compile(out + r"\Z")


def matching(files: list[str], glob: str) -> list[str]:
    rx = glob_re(glob)
    return sorted(f for f in files if rx.match(f))[:MAX_FILES]


# -- what a person maps ----------------------------------------------------------------------------------

def _signer(project: Any, person: str, persona: str) -> None:
    from kernel.access import require
    from kernel.people import is_person

    if not is_person(person):
        raise SourcesRefused(f"{person!r} is not a person: a project's own sources are mapped by a named person")
    if persona not in MAPPERS:
        raise SourcesRefused(f"refused: a {', '.join(MAPPERS)} maps a project's own sources")
    require(project, person, persona)
    if not applies(project):
        raise ValueError(f"{project.pid} has no repository of its own: its own sources are read from an adopted or "
                         "attached project's repository")


def _inside(path: str) -> bool:
    """A path or glob that names files inside the repository."""
    return bool(_GLOB.match(path)) and ".." not in path and not path.startswith("/")


def _mapping(spec: dict[str, Any]) -> dict[str, str]:
    mapping = spec.get("mapping") or {}
    if not isinstance(mapping, dict) or any(k not in FIELDS or not _KEY.match(str(v)) for k, v in mapping.items()):
        raise ValueError(f"mapping maps fields ({', '.join(FIELDS)}) to the keys the files use")
    return {k: str(v) for k, v in mapping.items()}


def _root(r: Any) -> dict[str, str]:
    """One test root: its folder, the command that runs it there, and the results file it writes, if any."""
    r = r if isinstance(r, dict) else {}
    root, res = str(r.get("root") or "").strip("/"), str(r.get("results") or "")
    if root and (not _inside(root) or "*" in root):
        raise ValueError(f"{root!r} is not a folder of the repository")
    if res and not _inside(res):
        raise ValueError("results names a file the command writes, inside its root")
    command = str(r.get("command") or "")
    nt.argv(command)
    return {"root": root, "command": command[:300], **({"results": res} if res else {})}


def _roots(spec: dict[str, Any]) -> list[dict[str, str]]:
    roots = spec.get("roots") or []
    if not isinstance(roots, list) or not roots or len(roots) > 50:
        raise ValueError("a tests source names its test roots, each with the command that runs it there")
    return [_root(r) for r in roots]


def _clean(spec: dict[str, Any]) -> dict[str, Any]:
    """A source's settings, checked: a kind, its adapter, a glob of repository paths, a field mapping, test roots."""
    kind = spec.get("kind")
    if kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(KINDS)}")
    adapter = spec.get("adapter") or ADAPTERS[kind][0]
    if adapter not in ADAPTERS[kind]:
        raise ValueError(f"{kind} is read with {' or '.join(ADAPTERS[kind])}")
    glob = str(spec.get("glob") or "")
    if kind != "tests" and not _inside(glob):
        raise ValueError("glob names files inside the repository, such as rules/*.json or rounds/*/README.md")
    every = spec.get("every") or "commit"
    if every not in EVERY:
        raise ValueError(f"every is one of {', '.join(EVERY)}")
    out = {"kind": kind, "adapter": adapter, "glob": glob, "mapping": _mapping(spec), "every": every,
           "label": str(spec.get("label") or KINDS[kind])[:120]}
    return out | ({"roots": _roots(spec)} if kind == "tests" else {})


def proposals(project: Any) -> dict[str, Any]:
    """What detection proposes now (from the repository; nothing recorded)."""
    src = _src(project)
    return nd.detect(src, use_anyway_paths(project), nd.planning_docs([r for r, _ in src.files]))


def _schedule(project: Any, every: str, person: str, persona: str) -> dict[str, Any]:
    """An automation that reads the sources again daily or weekly, in the person's name; or why there is none."""
    from kernel import automations as au

    when = {"daily": "05:00"} if every == "daily" else {"weekly": "mon 05:00"}
    raw = {"name": f"Read {project.meta.get('title') or project.pid}'s own sources {every}",
           "trigger": {"kind": "schedule", **when}, "action": {"kind": "watch", "what": "sources"},
           "scope": {"kind": "project", "project": project.pid}}
    try:
        return {"automation": au.add(project.factory, raw, person=person, persona=persona)["id"]}
    except (au.AutomationRefused, ValueError, LookupError, PermissionError) as exc:
        return {"automation": None, "why": f"not scheduled ({str(exc)[:200]}): read again by hand or on a new commit"}


def _changed(book: dict[str, Any], sid: str, spec: dict[str, Any], signed: dict[str, Any]) -> dict[str, Any]:
    have = next((s for s in book["sources"] if s["id"] == sid), None)
    if have is None:
        raise ValueError(f"no source {sid}")
    have.update(_clean({**have, **spec}), state="mapped", changed=signed)
    return have


def _added(book: dict[str, Any], spec: dict[str, Any], signed: dict[str, Any]) -> dict[str, Any]:
    clean = _clean(spec)
    dup = next((s for s in book["sources"] if s["state"] == "mapped" and s["kind"] == clean["kind"]
                and s["glob"] == clean["glob"]), None)
    if dup is not None:
        raise ValueError(f"{dup['id']} already reads {clean['glob'] or 'these test roots'} as {clean['kind']}: "
                         "change it instead")
    book["n"] = book.get("n", 0) + 1
    entry = {"id": f"SRC-{book['n']}", **clean, "state": "mapped",
             "by": {k: signed[k] for k in ("person", "persona")}, "at": signed["at"]}
    book["sources"].append(entry)
    return entry


def map_source(project: Any, *, person: str, persona: str, key: str | None = None,
               spec: dict[str, Any] | None = None, sid: str | None = None, every: str | None = None) -> dict[str, Any]:
    """Map a source: a detected proposal by its key, or settings given; with ``sid``, change that source."""
    _signer(project, person, persona)
    if key:
        found = next((p for p in proposals(project)["proposals"] if p["key"] == key), None)
        if found is None:
            raise ValueError(f"nothing is detected as {key!r} now: read the sources again, or give the glob")
        spec = dict(found, every=(spec or {}).get("every"))
    spec = dict(spec or {}, **({"every": every} if every else {}))
    book = _book(project)
    signed = {"person": person, "persona": persona, "at": project.factory.clock.stamp()}
    kind, entry = (("native_source_changed", _changed(book, sid, spec, signed)) if sid
                   else ("native_source_mapped", _added(book, spec, signed)))
    if entry["every"] in ("daily", "weekly") and not (book.get("schedule") or {}).get(entry["every"]):
        book.setdefault("schedule", {})[entry["every"]] = _schedule(project, entry["every"], person, persona)
    project.write(FILE, book)
    project.log(kind, {"source": entry["id"], "kind": entry["kind"], "glob": entry["glob"],
                       "mapping": entry["mapping"], "every": entry["every"], "person": person, "persona": persona})
    read(project, person=person, persona=persona, why=f"{entry['id']} mapped")
    return {"source": entry, **_view(project)}


def stop(project: Any, sid: str, *, person: str, persona: str, reason: str = "") -> dict[str, Any]:
    _signer(project, person, persona)
    book = _book(project)
    have = next((s for s in book["sources"] if s["id"] == sid and s["state"] == "mapped"), None)
    if have is None:
        raise ValueError(f"no mapped source {sid}")
    have.update(state="stopped", stopped={"person": person, "persona": persona, "reason": reason[:500],
                                          "at": project.factory.clock.stamp()})
    project.write(FILE, book)
    project.log("native_source_stopped", {"source": sid, "kind": have["kind"], "glob": have["glob"],
                                          "reason": reason[:500], "person": person, "persona": persona})
    read(project, person=person, persona=persona, why=f"{sid} stopped")
    return _view(project)


def use_anyway(project: Any, path: str, *, person: str, persona: str) -> dict[str, Any]:
    """Use a planning document that may be an old plan, as a person said."""
    _signer(project, person, persona)
    if not _GLOB.match(path or "") or ".." in path or "*" in path:
        raise ValueError("path names one file of the repository")
    book = _book(project)
    if path not in book.setdefault("use_anyway", []):
        book["use_anyway"].append(path)
    project.write(FILE, book)
    project.log("native_old_plan_used", {"path": path, "person": person, "persona": persona,
                                         "note": "the person said to use it although it may be an old plan"})
    return _view(project)


# -- reading ---------------------------------------------------------------------------------------------

def _parse(s: dict[str, Any], text: str, rel: str, date: int | None) -> list[dict[str, Any]]:
    """One file of a source, read by its adapter."""
    if s["kind"] == "requirements":
        return nr.records(text, rel, s["mapping"] or nr.guess_mapping(nr.objects(text, rel)))
    if s["kind"] == "findings" and s["adapter"] == "jsonl":
        return nr.jsonl(text, rel, s["mapping"])
    if s["kind"] == "findings":
        return [{"id": r["ref"], "title": r["title"], "severity": "not said", "status": r["status"] or "open",
                 "where": None, "path": rel, "line": r["line"]} for r in nr.records(text, rel, s["mapping"])]
    if s["kind"] == "tasks":
        return nr.markdown_tasks(text, rel)
    res = nr.results(text)
    return [{"path": rel, "format": res["format"], "counts": res["counts"], "cases": res["cases"][:MAX_KEPT],
             "date": date}]


def _read_one(src: Any, s: dict[str, Any], files: list[str], out: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rels = matching(files, s["glob"])
    if s["adapter"] == "records":                      # a folder's README beside its rule files is not a record
        rels = [r for r in rels if r.lower().endswith(nd.RECORD_EXT)]
    nd.prefetch(src, rels)
    errors, n = [], 0
    for rel in rels:
        raw = src.read(rel)
        try:
            if raw is None:
                raise nr.SourceUnreadable(f"{rel}: not read (larger than the read limit, or gone)")
            got = _parse(s, raw.decode("utf-8", "replace"), rel, src.dates.get(rel))
        except nr.SourceUnreadable as exc:
            errors.append(str(exc)[:300])
            continue
        out[s["kind"]] += [dict(g, source=s["id"]) for g in got]
        n += len(got)
        if s["adapter"] == "jsonl" and (skipped := nr.jsonl_unread(raw.decode("utf-8", "replace"))):   # never lost
            errors.append(f"{rel}: {len(skipped)} line(s) are not JSON objects and were not read (lines "
                          f"{', '.join(map(str, skipped[:20]))}{', ...' if len(skipped) > 20 else ''})")
    if not rels:
        errors.append(f"no file of the repository matches {s['glob']}")
    return {"files": len(rels), "records": n, "errors": errors[:20]}


def read(project: Any, *, person: str | None, persona: str | None, why: str = "asked",
         fetch: bool = False) -> dict[str, Any]:
    """Read every mapped source again from the repository's committed revision; keep it, and record it. With
    ``fetch``, an adopted project's upstream is fetched first (kernel/native_history.py, FR-SRC2)."""
    from kernel.native_history import fetch as fetch_upstream

    fetched = fetch_upstream(project) if fetch else None
    src = _src(project)
    files = [r for r, _ in src.files]
    out: dict[str, list[dict[str, Any]]] = {"requirements": [], "findings": [], "tasks": [], "results": []}
    per = {s["id"]: _read_one(src, s, files, out) for s in active(project) if s["kind"] != "tests"}
    at = project.factory.clock.stamp()
    for v in per.values():
        v["read_at"] = at
    record = {"at": at, "revision": src.revision, "why": why[:200], "sources": per,
              **{k: v[:MAX_KEPT] for k, v in out.items()},
              "by": {"person": person, "persona": persona} if person else {"note": "a schedule or a new commit"},
              **({"fetch": fetched} if fetched else {})}
    project.write(READ, record)
    project.log("native_sources_read", {"revision": src.revision, "why": why[:200], "person": person,
                                        "persona": persona, "counts": {k: len(v) for k, v in out.items()},
                                        "errors": sum(len(v["errors"]) for v in per.values())})
    return record


def latest_read(project: Any) -> dict[str, Any]:
    return project.read(READ, None) or {}


def reread(project: Any, reason: str) -> dict[str, Any] | None:
    """Read again for a schedule or a new commit, when a mapped source asks for it; None when none does."""
    want = "commit" if "commit" in reason else reason
    if not any(s.get("every") == want for s in active(project)):
        return None
    return read(project, person=None, persona=None, why=reason)
