"""Where a project keeps its own requirements, findings, tasks and test results, found by rule (FR-SRC1).

Read from the repository's committed revision (kernel/repo_structure.py ``source_of``), never run:

- **requirements**: a folder of JSON or YAML records (rule files, laws, invariants) whose records share an id, a
  title and a criterion, a statement or the test that checks each one; or one file holding a list of them;
- **findings**: a JSONL file (an issues or findings log), one finding per line;
- **tasks**: markdown tables with a status column and checklists, in a round's or a sprint's README, a handoff
  note, a to-do list or a roadmap; sibling folders that keep the same file (``rounds/*/README.md``) are one source;
- **test results**: JUnit XML, TAP or JSON results files committed by a run elsewhere;
- **test roots**: each Python package's own test root (kernel/native_tests.py ``roots``).

**Staleness.** A planning document (a spec, a task list, a plan) whose last commit is at least ``STALE_DAYS`` older
than the code's newest commit, with at least ``STALE_COMMITS`` commits to the code since, "may be an old plan": it is
not imported by default, and says so with Use it anyway. These two numbers are the platform's defaults.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from kernel import native_readers as nr
from kernel import native_tests as nt

STALE_DAYS = 14
STALE_COMMITS = 8
MAX_CANDIDATES = 300
MAX_PER_GROUP = 12
SKIP = {"node_modules", ".git", ".github", ".vscode", ".idea", "fixtures", "fixture", "testdata", "__snapshots__",
        "schemas", "schema", "vendor", "dist", "build", ".venv", "venv", "site-packages", "locales", "i18n"}
NOT_RECORDS = re.compile(r"(?i)(^|/)(package(-lock)?\.json|tsconfig[^/]*\.json|composer\.json|[^/]*\.lock"
                         r"|\.eslintrc[^/]*|renovate\.json|manifest\.json|\.?prettierrc[^/]*|app\.json"
                         r"|docker-compose[^/]*|\.pre-commit[^/]*|mkdocs\.yml|codecov\.yml|pnpm-workspace\.yaml"
                         r"|\.gitlab-ci\.yml|[^/]*openapi[^/]*|[^/]*swagger[^/]*)$")
TASK_NAMES = re.compile(r"(?i)(^|/)(handoff[^/]*|todo[^/]*|tasks?[^/]*|roadmap[^/]*|plan[^/]*|status[^/]*"
                        r"|progress[^/]*|next[^/]*|backlog[^/]*)\.md$")
TASK_DIRS = re.compile(r"(?i)(^|/)(rounds?|sprints?|milestones?|iterations?|phases?|handoffs?|plans?|notes|work)"
                       r"(/|[-_ ]?\d)")
RESULT_NAMES = re.compile(r"(?i)((^|/)TEST-[^/]*\.xml|junit[^/]*\.xml|\.tap|(^|/|[-_.])(test[-_]?)?results?"
                          r"[^/]*\.json|(^|/)[^/]*gates?[-_]?(results?|report|run)[^/]*\.json"
                          r"|(^|/)(test[-_]?)?(results?|reports?)/[^/]*\.(json|xml|tap)"
                          r"|(^|/)gates?/[^/]*(results?|reports?|runs?)[^/]*\.(json|xml|tap))$")
FINDING_HINT = re.compile(r"(?i)(issue|finding|bug|defect|evidence|incident|problem|risk)")
PREFER = re.compile(r"(?i)(^|/)(rules?|laws?|requirements?|invariants?|policies|policy|specs?|criteria|contracts?)"
                    r"(/|$)")


def _skipped(rel: str) -> bool:
    return bool(set(rel.split("/")[:-1]) & SKIP)


def prefetch(src: Any, rels: list[str]) -> None:
    """A committed revision's files are read from git in one batch first (kernel/repo_structure.py)."""
    fetch = getattr(src, "prefetch", None)
    if fetch is not None and rels:
        fetch(list(dict.fromkeys(rels)))


def _text(src: Any, rel: str) -> str | None:
    raw = src.read(rel)
    if raw is None or len(raw) > nr.MAX_TEXT:
        return None
    return raw.decode("utf-8", "replace")


def _parent(rel: str) -> str:
    return str(PurePosixPath(rel).parent) if "/" in rel else ""


def _glob_of(parent: str, ext: str) -> str:
    return f"{parent}/*{ext}" if parent else f"*{ext}"


# -- staleness -------------------------------------------------------------------------------------------

def code_commits(src: Any) -> list[int]:
    """The commit times that touched code, newest first: every commit at a git revision (kernel/native_history.py),
    else each code file's last commit (a lower bound)."""
    from kernel.native_history import code_commit_times
    from kernel.repo_structure import CODE_EXT

    real = code_commit_times(src)
    if real is not None:
        return real
    return sorted({d for r, d in src.dates.items() if r.endswith(CODE_EXT) and d}, reverse=True)


def staleness(src: Any, rel: str, commits: list[int] | None = None) -> dict[str, Any] | None:
    """Why a planning document may be an old plan, or None when it is not (or its dates are not known)."""
    date = src.dates.get(rel)
    commits = code_commits(src) if commits is None else commits
    if not date or not commits:
        return None
    after = [c for c in commits if c > date]
    days = (commits[0] - date) // 86400
    if days < STALE_DAYS or len(after) < STALE_COMMITS:
        return None
    return {"path": rel, "days": int(days), "commits_since": len(after),
            "why": f"may be an old plan: its last change is {days} days older than the code's newest, and the code "
                   f"changed in {len(after)} commits since"}


def stale_docs(src: Any, paths: list[str], use_anyway: list[str]) -> list[dict[str, Any]]:
    commits = code_commits(src)
    return [s for p in dict.fromkeys(paths) if p not in use_anyway and (s := staleness(src, p, commits))]


# -- each kind -------------------------------------------------------------------------------------------

RECORD_EXT = (".json", ".yaml", ".yml")


def _requirement_groups(files: list[str]) -> dict[tuple[str, str], list[str]]:
    """Record files by folder: ``*.json`` (or ``*.yaml``) when the folder holds one kind, ``*`` when both."""
    groups: dict[str, list[str]] = {}
    for rel in files:
        if rel.lower().endswith(RECORD_EXT) and not _skipped(rel) and not NOT_RECORDS.search(rel):
            groups.setdefault(_parent(rel), []).append(rel)
    out = {}
    for parent, rels in groups.items():
        exts = {PurePosixPath(r).suffix.lower() for r in rels}
        out[(parent, exts.pop() if len(exts) == 1 else "")] = rels
    return out


def _objects(src: Any, rel: str) -> list[dict[str, Any]]:
    text = _text(src, rel)
    try:
        return nr.objects(text, rel) if text else []
    except nr.SourceUnreadable:
        return []


def _take(budget: list[int], rels: list[str]) -> list[str]:
    """As many of ``rels`` as the reading budget still allows, counted off it."""
    n = max(0, min(len(rels), budget[0]))
    budget[0] -= n
    return rels[:n]


def _records_like(m: dict[str, str]) -> bool:
    """An id, a title, and a criterion, a test or a statement apart from the title."""
    extra = [k for k in ("criteria", "test", "statement") if k in m and m[k] != m.get("title")]
    return bool(m.get("id") and m.get("title") and extra)


def _as_requirements(parent: str, ext: str, rels: list[str], objs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A folder's records as a requirements proposal, when they share an id, a title and a criterion, a statement
    or a test, and there are two files or three records at least."""
    m = nr.guess_mapping(objs)
    if not _records_like(m) or (len(rels) < 2 and len(objs) < 3):
        return None
    said = ", ".join(f"{f} ({m[f]})" for f in ("criteria", "test") if f in m)
    return {"kind": "requirements", "adapter": "records", "glob": _glob_of(parent, ext) if len(rels) > 1 else rels[0],
            "mapping": {k: v for k, v in m.items() if k in ("id", "title", "statement", "criteria", "test", "status")},
            "files": len(rels), "sample": str(objs[0].get(m["title"]) or "")[:120],
            "why": f"{len(rels)} file(s) in {parent or 'the root'}/ hold records with an id ({m['id']}) and a "
                   f"title ({m['title']})" + (f", and {said}" if said else "")}


def _requirements(src: Any, files: list[str], budget: list[int]) -> list[dict[str, Any]]:
    out = []
    groups = sorted(_requirement_groups(files).items(), key=lambda kv: (not PREFER.search(kv[0][0] + "/"), kv[0]))
    for (parent, ext), rels in groups:
        objs = [o for rel in _take(budget, sorted(rels)[:MAX_PER_GROUP]) for o in _objects(src, rel)]
        found = _as_requirements(parent, ext, rels, objs) if objs else None
        if found:
            out.append(found)
    return out


def _findings(src: Any, files: list[str], budget: list[int]) -> list[dict[str, Any]]:
    out = []
    for rel in sorted(f for f in files if f.lower().endswith((".jsonl", ".ndjson")) and not _skipped(f)):
        if budget[0] <= 0:
            break
        budget[0] -= 1
        text = _text(src, rel)
        try:
            got = nr.jsonl(text, rel) if text else []
        except nr.SourceUnreadable:
            got = []
        if got and (FINDING_HINT.search(rel) or any(g["severity"] != "not said" for g in got)):
            out.append({"kind": "findings", "adapter": "jsonl", "glob": rel, "mapping": {}, "files": 1,
                        "sample": got[0]["title"][:120],
                        "why": f"{rel} keeps {len(got)} finding(s), one per line, with a title"
                               + (" and a severity" if any(g["severity"] != "not said" for g in got) else "")})
    return out


PLANNING = re.compile(r"(?i)(^|/)(spec|plan|tasks|requirements|design|prd|roadmap|stories|backlog)[^/]*\.md$")


def planning_docs(files: list[str]) -> list[str]:
    """The planning documents by name: specs, plans, task lists, requirement documents, roadmaps, backlogs."""
    return sorted(f for f in files if PLANNING.search(f) and not _skipped(f))


def _task_files(files: list[str]) -> list[str]:
    return sorted(f for f in files if f.lower().endswith(".md") and not _skipped(f)
                  and (TASK_NAMES.search(f) or ("/" in f and TASK_DIRS.search(f))))


def _rows(src: Any, rel: str) -> int:
    text = _text(src, rel)
    return len(nr.markdown_tasks(text, rel)) if text else 0


def _sibling_glob(rel: str, found: dict[str, int]) -> str:
    """``rounds/*/README.md`` when sibling folders keep the same file, else the file itself."""
    p = PurePosixPath(rel)
    if len(p.parts) < 3:
        return rel
    grand = str(p.parent.parent)
    sibs = [r for r in found if PurePosixPath(r).name == p.name and str(PurePosixPath(r).parent.parent) == grand]
    return f"{grand}/*/{p.name}" if len(sibs) >= 2 else rel


def _tasks(src: Any, files: list[str], budget: list[int], stale: set[str]) -> list[dict[str, Any]]:
    found = {rel: n for rel in _take(budget, _task_files(files)) if (n := _rows(src, rel)) >= 2}
    by_glob: dict[str, list[str]] = {}
    for rel in found:
        by_glob.setdefault(_sibling_glob(rel, found), []).append(rel)
    out = []
    for glob, rels in sorted(by_glob.items()):
        fresh = [r for r in rels if r not in stale]
        if not fresh:
            continue
        n = sum(found[r] for r in fresh)
        out.append({"kind": "tasks", "adapter": "markdown", "glob": glob, "mapping": {}, "files": len(fresh),
                    "sample": fresh[-1],
                    "why": f"{len(fresh)} markdown file(s) ({glob}) keep {n} task row(s) with a status"})
    return out


def _results(src: Any, files: list[str], budget: list[int]) -> list[dict[str, Any]]:
    out = []
    for rel in sorted(f for f in files if RESULT_NAMES.search(f) and "node_modules" not in f):
        if budget[0] <= 0:
            break
        budget[0] -= 1
        text = _text(src, rel)
        try:
            got = nr.results(text) if text else None
        except nr.SourceUnreadable:
            got = None
        if got:
            c = got["counts"]
            out.append({"kind": "results", "adapter": "results", "glob": rel, "mapping": {}, "files": 1,
                        "sample": f"{c.get('passed', 0)} passed, {c.get('failed', 0)} failed",
                        "why": f"{rel} holds the results of a test run ({got['format']}), committed with its date"})
    return out


def _tests(files: list[str]) -> list[dict[str, Any]]:
    found = nt.roots(files)
    if not found:
        return []
    note = nt.root_note(found)
    return [{"kind": "tests", "adapter": "command", "glob": "", "mapping": {}, "files": sum(r["test_files"]
                                                                                       for r in found),
             "roots": found, "sample": ", ".join(r["root"] or "(root)" for r in found[:6]),
             "why": note or f"its Python tests run with pytest from the repository's root ({found[0]['test_files']} "
                            "test files)"}]


def key_of(p: dict[str, Any]) -> str:
    return f"{p['kind']}:{p['glob'] or 'roots'}"


def detect(src: Any, use_anyway: list[str] | None = None, planning: list[str] | None = None) -> dict[str, Any]:
    """What this repository keeps of its own, proposed with a mapping each; and its planning documents that may be
    old plans. ``planning``: the paths of the specs and task lists the structure scan found."""
    files = [r for r, _ in src.files]
    budget = [MAX_CANDIDATES]
    wanted = [r for rels in _requirement_groups(files).values() for r in sorted(rels)[:MAX_PER_GROUP]]
    wanted += [f for f in files if f.lower().endswith((".jsonl", ".ndjson")) or RESULT_NAMES.search(f)]
    prefetch(src, wanted[:MAX_CANDIDATES * 2] + _task_files(files)[:MAX_CANDIDATES])
    use = list(use_anyway or [])
    stale = stale_docs(src, list(planning or []) + _task_files(files), use)
    stale_paths = {s["path"] for s in stale}
    proposals = (_requirements(src, files, budget) + _findings(src, files, budget)
                 + _tasks(src, files, budget, stale_paths) + _results(src, files, budget) + _tests(files))
    for p in proposals:
        p["key"] = key_of(p)
    return {"proposals": proposals, "stale": stale, "revision": src.revision,
            "rule": {"stale_days": STALE_DAYS, "stale_commits": STALE_COMMITS}}
