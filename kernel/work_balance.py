"""Where the work went: of the decisions and changes in a period, what moved development and what conformed to
Rihmasto's structure (FR-STR1).

The owner (2026-11-26): "Do I just spend accepting changes that forces project to rihmasto structure or actually
moving the needle with dev."

Counted from the records, never estimated:

- **moved development**: code merged through the gate (``merged``), commits seen in the repository that change
  code or tests (git's own log of the project's repository, read and never written), changes seen upstream
  (``watch_commits``), checks that passed on a change (``gate``), a build that passed, a release done, an accepted
  change as a feature or a fix (``change_applied``), findings filed as changes, and decisions that move the work
  on (a change accepted, a stuck task decided, a plan approved);
- **conformed to structure**: Alignment decisions on the traces and gaps of Rihmasto's conventions, a convention
  raised to Enforce, and Will fix on an enforced convention's Inbox card.
- **taken in** (FR-STR2): Alignment decisions on what the project's own files hold (requirements, criteria, tasks,
  decisions, API contracts, and facts about its files) and a contract imported. That is the project's own structure,
  kept as it is: counted beside the bars, in neither, as the Alignment view says (kernel/structure_sides.py).

Lowering a convention (to Advise or Off, or Advise instead on its card) is in neither bar: following Rihmasto's
advice to step back never counts as conformance work. Anything else (reading, scanning, questions, settings) is in
neither bar. Each bar keeps the items behind it. A warning says when conformance work dominates while development
stalls, with what to do about it.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from kernel.insights.base import stamp as _stamp
from kernel.insights.base import when as _when

WINDOWS = {"7d": 7, "30d": 30, "90d": 90, "all": None}
WINDOW_WORDS = {"7d": "the last 7 days", "30d": "the last 30 days", "90d": "the last 90 days", "all": "all records"}
DEV_WORDS = {"code": ("code change", "code changes"), "tests": ("test added or passing", "tests added or passing"),
             "feature": ("feature", "features"), "fix": ("fix", "fixes"), "release": ("release", "releases"),
             "decision": ("decision that moved the work on", "decisions that moved the work on")}
CONFORM_WORDS = {"traces": ("trace or gap of Rihmasto's conventions", "traces and gaps of Rihmasto's conventions"),
                 "conventions": ("convention set to Enforce", "conventions set to Enforce"),
                 "cards": ("enforced convention taken on", "enforced conventions taken on")}
TAKEN_WORDS = {"records": ("record taken in from the project's own files",
                           "records taken in from the project's own files"),
               "facts": ("fact about its own files kept", "facts about its own files kept")}
MOVING_CARDS = ("change", "escalation", "approval", "validation", "go_ahead", "incident")
DOMINATES, AT_LEAST = 2.0, 5
MAX_ITEMS = 200
TEST_HINT = ("test", "tests", "__tests__")
DOC_SUFFIX = (".md", ".rst", ".txt", ".adoc", ".feature")
DOC_FOLDERS = ("docs", "doc", "specs", ".kiro", "adr", "decisions")


def _item(side: str, what: str, title: str, at: Any, href: str, project: Any) -> dict[str, Any]:
    return {"side": side, "what": what, "title": str(title)[:200], "at": at if isinstance(at, str) else _stamp(at),
            "href": href, "project": project.pid}


def _decided(project: Any) -> dict[str, dict[str, Any]]:
    """Each decided Alignment item as decided, by its id (kernel/alignment_records.py keeps it)."""
    from kernel.alignment_records import decisions

    return {k: d.get("item") or {} for k, d in decisions(project).items()}


def _alignment(payload: dict[str, Any], at: Any, project: Any, kind: str) -> list[dict[str, Any]]:
    """Each decided item on the side the Alignment view gives it (kernel/structure_sides.py): the project's own
    records and facts are taken in; Rihmasto's conventions are conformance."""
    from kernel.structure_sides import side_of

    out = []
    verb = "accepted" if kind == "alignment_accepted" else "rejected"
    items = _decided(project)
    for iid in payload.get("items") or []:
        item = items.get(iid) or {"id": iid, "group": _GROUP_OF.get(str(iid).split("-", 1)[0], "gaps")}
        side = side_of(item)
        bar, what = {"take_in": ("take_in", "records"), "fact": ("take_in", "facts")}.get(side, ("conform", "traces"))
        out.append(_item(bar, what, f"{item.get('title') or iid}: {verb} by {payload.get('person') or 'a person'}",
                         at, f"#/p/{project.pid}/align", project))
    return out


_GROUP_OF = {"req": "requirements", "crit": "criteria", "task": "tasks", "adr": "decisions", "api": "contracts",
             "trace": "trace"}


Said = tuple[str, str, str, str]                 # the bar, what it was, its title, the project view it opens
P = dict[str, Any]


def _labels(pl: P) -> str:
    return ", ".join(str(c.get("label", "")) for c in pl.get("changes") or [])


# What each kind of ledger record adds to a bar, when it always adds the same.
PLAIN: dict[str, Any] = {
    "merged": lambda pl: ("dev", "code", f"{pl.get('task') or 'A change'} merged", "tasks"),
    "watch_commits": lambda pl: ("dev", "code", f"{pl.get('new_commits') or 'New'} commit(s) seen upstream",
                                 "overview"),
    "first_build_passed": lambda pl: ("dev", "tests", "The first build passed", "checks"),
    "release_done": lambda pl: ("dev", "release", f"Release {pl.get('version') or pl.get('release') or ''} done",
                                "releases"),
    "change_applied": lambda pl: ("dev", "fix" if pl.get("class") == "defect" else "feature",
                                  f"{pl.get('card') or 'A change'} applied as a "
                                  + str(pl.get("class") or "change").replace("_", " "), "changes"),
    "assessment_change_opened": lambda pl: ("dev", "fix", f"Finding {pl.get('finding') or ''} filed as a change",
                                            "changes"),
    "contract_imported": lambda pl: ("take_in", "records", "A contract imported", "spec"),
}


def _raised(pl: P) -> Said | None:
    """A structure change counts only for the conventions it raises to Enforce: lowering one is not conformance."""
    up = [c for c in pl.get("changes") or [] if c.get("to") == "enforce" and c.get("from") != "enforce"]
    if not up:
        return None
    return ("conform", "conventions", f"Rihmasto's structure: {_labels({'changes': up})} set to Enforce by "
            f"{pl.get('person') or 'a person'}", "align")


def _judged(kind: str, pl: P) -> Said | None:
    """A record that adds to a bar only by what it says: a passed check, a decision on a card."""
    if kind == "gate":
        return ("dev", "tests", f"Checks passed on {pl.get('task') or 'a change'}", "checks") \
            if str(pl.get("verdict")) == "passed" else None
    if kind == "structure_set":
        return _raised(pl)
    if kind != "decision":
        return None
    said = f"{pl.get('card')}: {pl.get('kind')} decided ({pl.get('verdict')})"
    if pl.get("kind") in MOVING_CARDS:
        return "dev", "decision", said, "inbox"
    # Will fix takes the convention on; Advise instead steps back from it and is in neither bar
    return ("conform", "cards", said, "inbox") if (pl.get("kind"), pl.get("verdict")) == ("structure", "will_fix") \
        else None


def _event(kind: str, pl: P, at: Any, project: Any) -> list[dict[str, Any]]:
    """The items one ledger record adds to a bar: none for what moves neither."""
    if kind in ("alignment_accepted", "alignment_rejected"):
        return _alignment(pl, at, project, kind)
    said = PLAIN[kind](pl) if kind in PLAIN else _judged(kind, pl)
    if said is None:
        return []
    side, what, title, view = said
    return [_item(side, what, " ".join(title.split()), at, f"#/p/{project.pid}/{view}", project)]


# -- the project's repository, read and never written --------------------------------------------------------

def _repo(project: Any) -> tuple[Path, str] | None:
    kind = project.meta.get("source_kind")
    if kind == "attached":
        info = project.meta.get("attached") or {}
        return (Path(info["repo"]), info.get("branch") or "HEAD") if info.get("repo") else None
    if kind == "adopted" and project.path("repo.git").exists():
        adopted = project.read("adopted.json", {}) or {}
        return project.path("repo.git"), f"refs/remotes/upstream/{adopted.get('branch') or 'main'}"
    return None


def _touches(files: list[str]) -> str | None:
    """A commit's side: code or tests changed; None for one that changes only documents."""
    def test(f: str) -> bool:
        parts = f.lower().replace("\\", "/").split("/")
        return any(p in TEST_HINT for p in parts[:-1]) or parts[-1].startswith("test_") or ".test." in parts[-1] \
            or parts[-1].endswith("_test.py") or ".spec." in parts[-1]
    def doc(f: str) -> bool:
        low = f.lower().replace("\\", "/")
        return low.endswith(DOC_SUFFIX) or any(p in DOC_FOLDERS for p in low.split("/")[:-1])
    tests = [f for f in files if test(f)]
    code = [f for f in files if f not in tests and not doc(f)]
    return "tests" if tests and not code else "code" if code else None


def _commits(project: Any, since: dt.datetime | None) -> list[dict[str, Any]]:
    from kernel.repo_structure import _git

    found = _repo(project)
    if found is None:
        return []
    repo, rev = found
    if not _git(repo, "rev-parse", "--verify", "-q", rev + "^{commit}").strip():
        rev = "HEAD" if project.meta.get("source_kind") == "attached" else "main"
    args = ["log", "--no-merges", "-n", "500", "--format=%x1e%H%x1f%cI%x1f%s", "--name-only"]
    if since is not None:
        args.append(f"--since={_stamp(since)}")
    out = []
    for block in _git(repo, *args, rev, "--").decode("utf-8", "replace").split("\x1e")[1:]:
        head, _, files = block.partition("\n")
        parts = head.split("\x1f")
        if len(parts) != 3:
            continue
        side = _touches([f for f in files.splitlines() if f.strip()])
        if side:
            out.append(_item("dev", side, f"{parts[0][:8]} {parts[2]}", _stamp(_when(parts[1])),
                             f"#/p/{project.pid}/overview", project))
    return out


# -- the read -------------------------------------------------------------------------------------------------

def _projects(factory: Any, pid: str | None) -> list[Any]:
    from kernel.learn import FACTORY_PID

    if pid is not None:
        p = factory.project(pid)
        if not p.path("project.json").exists():
            raise KeyError(f"no project {pid!r}")
        return [p]
    return [p for p in factory.projects() if p.pid != FACTORY_PID and not p.pid.startswith("_")]


def _items_of(project: Any, since: dt.datetime | None, now: dt.datetime) -> list[dict[str, Any]]:
    out = []
    for rec in project.ledger().records():
        if not isinstance(rec, dict) or not isinstance(rec.get("event"), dict):
            continue
        ev = rec["event"]
        t = _when(ev.get("at"))
        if since is not None and (t is None or not since <= t <= now):
            continue
        out += _event(str(ev.get("kind")), ev.get("payload") or {}, ev.get("at"), project)
    seen_commits = any(i["what"] == "code" and "upstream" in i["title"] for i in out)
    if not seen_commits:              # an adopted project's watch already counts the same commits
        out += _commits(project, since)
    return out


def _count(items: list[dict[str, Any]], words: dict[str, Any]) -> dict[str, int]:
    return {k: n for k in words if (n := sum(1 for i in items if i["what"] == k))}


def _said(by: dict[str, int], words: dict[str, tuple[str, str]]) -> str:
    return ", ".join(f"{n} {words[k][0 if n == 1 else 1]}" for k, n in by.items())


def _side(items: list[dict[str, Any]], side: str, words: dict[str, Any]) -> dict[str, Any]:
    mine = sorted((i for i in items if i["side"] == side), key=lambda i: i["at"] or "", reverse=True)
    by = _count(mine, words)
    return {"n": len(mine), "by": by, "said": _said(by, words), "items": mine[:MAX_ITEMS],
            "more": max(0, len(mine) - MAX_ITEMS)}


def _warning(dev: int, conform: int) -> bool:
    return conform >= AT_LEAST and conform >= DOMINATES * max(dev, 1)


def _suggestions(factory: Any, projects: list[Any], warn: bool) -> list[dict[str, Any]]:
    from kernel import structure_policy as sp

    if not warn:
        return []
    out = []
    for p in projects:
        enforced = [r["label"] for c in sp.CONVENTIONS if (r := sp.row(factory, p, c))["level"] == "enforce"]
        if enforced and sp.kind_of(p) == "own":
            out.append({"text": f"Switch {', '.join(enforced)} to Advise for {p.meta.get('title') or p.pid}: its "
                                "findings become suggestions, not counted, and stop taking your time",
                        "route": f"#/p/{p.pid}/align", "control": "structure_policy", "project": p.pid})
        if sp.kind_of(p) == "own":
            scanned = bool(p.read("alignment/scan.json"))
            out.append({"text": ("Map the project's own sources: read its code again on Alignment so its own specs, "
                                 "tests and tasks are taken as they are" if scanned else
                                 "Map the project's own sources first: read its code on Alignment so Rihmasto "
                                 "takes its own specs, tests and tasks as given"),
                        "route": f"#/p/{p.pid}/align", "control": "align_scan", "project": p.pid})
    return out[:6]


def _rows(projects: list[Any], since: dt.datetime | None, now: dt.datetime
          ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Each project's two counts, and every item behind them."""
    rows, every = [], []
    for p in projects:
        items = _items_of(p, since, now)
        every += items
        d, c = sum(1 for i in items if i["side"] == "dev"), sum(1 for i in items if i["side"] == "conform")
        t = sum(1 for i in items if i["side"] == "take_in")
        rows.append({"project": p.pid, "title": p.meta.get("title") or p.pid, "development": d, "conformance": c,
                     "taken_in": t, "warning": _warning(d, c), "href": f"#/p/{p.pid}/overview"})
    return rows, every


def _line(dev: dict[str, Any], conform: dict[str, Any], where: str, taken: dict[str, Any] | None = None) -> str:
    taken = taken or {"n": 0, "said": ""}
    also = (f" Besides, {taken['said']}: its own structure, counted in neither bar." if taken["n"] else "")
    if not dev["n"] and not conform["n"]:
        return f"Nothing moved development or conformed to Rihmasto's structure in {where}." + also
    return (f"In {where}, {dev['n']} moved development" + (f" ({dev['said']})" if dev["said"] else "")
            + f" and {conform['n']} conformed to Rihmasto's structure"
            + (f" ({conform['said']})" if conform["said"] else "") + "." + also)


def read(factory: Any, *, pid: str | None = None, window: str = "30d") -> dict[str, Any]:
    """Where the work went in a window, for one project or every project, with the items behind each bar."""
    if window not in WINDOWS:
        raise ValueError(f"the window is one of {', '.join(WINDOWS)}, got {window!r}")
    now = factory.clock.now()
    days = WINDOWS[window]
    since = now - dt.timedelta(days=days) if days else None
    projects = _projects(factory, pid)
    rows, every = _rows(projects, since, now)
    dev, conform = _side(every, "dev", DEV_WORDS), _side(every, "conform", CONFORM_WORDS)
    taken = _side(every, "take_in", TAKEN_WORDS)
    warn = _warning(dev["n"], conform["n"])
    where = WINDOW_WORDS[window]
    warning = (f"Conformance work dominates: {conform['n']} items conformed to Rihmasto's structure against "
               f"{dev['n']} that moved development. Rihmasto's conventions can be suggestions instead of work."
               if warn else None)
    flagged = [p for p, r in zip(projects, rows, strict=True) if r["warning"]] or (projects if warn else [])
    return {"scope": "project" if pid else "factory", "project": pid, "window": window, "window_words": where,
            "since": _stamp(since), "until": _stamp(now), "development": dev, "conformance": conform,
            "taken_in": taken,
            "projects": sorted(rows, key=lambda r: -(r["development"] + r["conformance"] + r["taken_in"])),
            "line": _line(dev, conform, where, taken),
            "warning": warning, "suggestions": _suggestions(factory, flagged, bool(warning)),
            "measured": bool(dev["n"] or conform["n"] or taken["n"]),
            "how": "Development is counted from merges, passing checks, releases, applied changes and the "
                   "repository's own commits; conformance from Alignment decisions on Rihmasto's conventions, a "
                   "convention raised to Enforce and Will fix on its card. What is taken in from the project's own "
                   "files is its own structure, counted beside, in neither. Lowering a convention, reading, "
                   "scanning and settings count in neither."}
