"""Start here (FR-LND1): what Rihmasto understood a project to be, the one to three things to do there now, and what
Rihmasto does on its own meanwhile, by rule from the project's records.

The owner (2026-11-26), after adopting a project of their own: "when I jump into the game project its not clear what
should I do". Every project's first view opens on this panel. It says, in one line, what Rihmasto took the project to
be and where that came from (with Correct it), then at most three steps read from the real state, each with the place
that does it (``route``) and the control of the cockpit's map that does it there (``control``):

- an adopted or attached project: confirm its kind of work when Rihmasto only guessed it; review an upstream change
  that waits for a decision; read its repository with Alignment when nothing of it was aligned yet, saying what
  Alignment reads and what it cannot (kernel/source_reach.py), or review what that left open and name the sources
  it left unread (FR-LND2); look at the top findings of
  its latest assessment (or assess it); connect a coding agent when none has worked on it yet;
- any project: what kernel/next_step.py says it waits for (a decision, a question, a run that failed, Advance).

``meanwhile`` lists what runs without a person: a cell building a task, a background job, the upstream watch, the
automations that reach the project and its scheduled health checks; or, when nothing does, says so with the step that
would. A person may hide the panel (``hide``); it is recorded in the ledger with the steps it showed, and it comes
back by itself when a step it did not show appears. Reading changes nothing. kernel/start_here_chat.py answers
"what should I do here?" with the same steps.
"""

from __future__ import annotations

import re
from typing import Any

from kernel.people import PERSONAS, is_person

MAX_STEPS = 3
HIDDEN, SHOWN = "start_here_hidden", "start_here_shown"
UPSTREAM = "upstream sync"           # the name an upstream sync signs its change card with (kernel/adopt.py)
SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
# Where a card came from, as the kernel writes it into a title ("[embed E-001] ..."): the page says it apart.
SOURCE_TAG = re.compile(r"\[(?:embed|signal) [A-Z]+-\d+(?: via [\w-]+)?\]\s*")


class StartHereRefused(ValueError):
    """A hide or show the kernel does not take: not a named person, or not a persona."""


def _route(pid: str, view: str, focus: str | None = None) -> str:
    return f"#/p/{pid}/{view}" + (f"/{focus}" if focus else "")


def _step(sid: str, label: str, why: str, route: str, control: str | None, **extra: Any) -> dict[str, Any]:
    return {"id": sid, "label": label, "why": why, "route": route, "control": control, **extra}


def _n(n: int, one: str) -> str:
    return f"{n} {one}" + ("" if n == 1 else "s")


def _clip(text: str, limit: int = 160) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"


def _first_sentence(text: str) -> str:
    text = " ".join(str(text or "").split())
    for end in (". ", "! ", "? "):
        if end in text:
            return text.split(end, 1)[0] + end.strip()
    return text


# -- what Rihmasto understood -------------------------------------------------------------------------------

def _kind_of_work(project: Any) -> tuple[str | None, bool]:
    """The kind of work chosen or guessed, and whether a person still has to confirm it."""
    prof = (project.read("adopted.json", None) or {}).get("profile")
    named = project.meta.get("profile")
    if isinstance(prof, dict) and prof.get("profile"):
        return str(prof["profile"]).replace("_", " "), prof.get("confidence") == "uncertain"
    return (str(named).replace("_", " ") if named else None), not named


def _adopted_line(project: Any, u: dict[str, Any]) -> dict[str, Any]:
    """An adopted or attached project's line, from what adoption read (kernel/understanding.py)."""
    meta, pid = project.meta, project.pid
    kind, guessed = _kind_of_work(project)
    bits = [f"adopted to {u['intent'] or 'improve'}" if meta.get("source_kind") == "adopted" else "attached"]
    bits.append(f"{kind} (a guess: confirm it)" if kind and guessed else kind or "kind of work not chosen yet")
    langs = next((s.split(": ", 1)[1] for s in u["shape"] if s.startswith("Languages: ")), "")
    if langs and langs != "none recognised":
        bits.append(langs.split(" (")[0])
    what = _first_sentence(u["what"]) if u["what"] else "no description found in it yet"
    return {"line": _clip(f"{meta.get('title') or pid}: {what}", 220) + " (" + ", ".join(bits) + ")",
            "basis": u["said_by"], "correct": {"route": _route(pid, "overview"), "control": "understood_correct"},
            "by": "rule"}


def _goal(project: Any) -> str:
    from kernel.canon import Canon

    try:
        return Canon(project).goal
    except (OSError, ValueError):
        return ""


def understood(project: Any) -> dict[str, Any]:
    """One line: what Rihmasto took the project to be, where that came from, and how to correct it."""
    from kernel import understanding
    from kernel.store import STAGES

    u = understanding.take(project)
    if u is not None:
        return _adopted_line(project, u)
    meta, pid = project.meta, project.pid
    title, goal, stage = meta.get("title") or pid, _goal(project), meta.get("stage")
    said = _first_sentence(goal) if goal.strip() else "no goal written yet: its request is still being shaped"
    if said.rstrip(".").strip().lower() == str(title).strip().lower():
        said = "its goal says no more than its title yet"
    return {"line": _clip(f"{title}: {said}", 220) + f" (a new project, stage {stage}: {STAGES.get(stage, '?')})",
            "basis": "the project's goal" if goal.strip() else "its request: no goal yet",
            "correct": {"route": _route(pid, "overview"), "control": "add_material"}, "by": "rule"}


# -- the steps ----------------------------------------------------------------------------------------------

def _canon(project: Any) -> Any:
    from kernel.canon import Canon

    return Canon(project)


def _kind_step(project: Any, canon: Any) -> dict[str, Any] | None:
    from kernel.profiles import PROFILE_QUESTION

    q = next((q for q in canon.questions("open") if q.get("text") == PROFILE_QUESTION), None)
    if q is not None:
        return _step("confirm_kind", "Confirm what kind of work it is",
                     "Rihmasto could not tell from its files; the answer picks the checks and words that fit",
                     _route(project.pid, "questions", q["id"]), "answer", question=q["id"])
    kind, guessed = _kind_of_work(project)
    if kind and guessed:
        return _step("confirm_kind", "Confirm what kind of work it is",
                     f"Rihmasto guessed {kind}; confirm or change it in the project's settings",
                     _route(project.pid, "overview"), "project_settings")
    return None


def _upstream_step(project: Any, canon: Any) -> dict[str, Any] | None:
    waiting = [c for c in canon.cards(kind="change") if (c.get("payload") or {}).get("person") == UPSTREAM]
    if not waiting:
        return None
    c = waiting[-1]
    more = f" ({len(waiting)} waiting)" if len(waiting) > 1 else ""
    return _step("upstream_change", f"Review the upstream change {c['id']}{more}",
                 "its repository moved on; decide whether the change is taken into the project's work",
                 _route(project.pid, "inbox", c["id"]), "decide", card=c["id"])


Rows = list[dict[str, Any]]


def _scanned(project: Any, scan: dict[str, Any]) -> tuple[Rows, list[str], Rows]:
    """From Alignment's last read: the sources it left unread, the documents it read, and the items still open."""
    from kernel import alignment_records

    got = scan.get("structure")
    structure: dict[str, Any] = got if isinstance(got, dict) else {}
    unread = [u for u in structure.get("unread") or [] if isinstance(u, dict) and u.get("path")]
    docs = [str(s.get("path")) for s in structure.get("specs") or [] if isinstance(s, dict) and s.get("path")]
    decided = alignment_records.decisions(project)
    items = (scan.get("proposal") or {}).get("items") or []
    return unread, docs, [i for i in items if i.get("group") != "gaps" and i.get("id") not in decided]


def _old_plans(project: Any) -> int:
    """How many open items Alignment read from a file much older than the code's latest change (they may be an
    old plan, kernel/alignment_origin.py): what the Alignment view marks, counted for the first step."""
    from kernel import alignment_records

    try:
        groups = alignment_records.view(project).get("groups") or []
    except (OSError, ValueError, KeyError):
        return 0
    return sum(1 for g in groups for i in g.get("items") or []
               if i.get("status") == "open" and (i.get("origin") or {}).get("old"))


def _sources_step(project: Any) -> dict[str, Any] | None:
    """Read the project's repository with Alignment, saying what it reads and what it cannot (FR-LND2): the sources
    it left unread are named, so an old document is not taken for the project's current plan."""
    if project.meta.get("source_kind") not in ("adopted", "attached"):
        return None
    from kernel import source_reach as reach

    scan = project.read("alignment/scan.json", None)
    if not isinstance(scan, dict):
        return _step("map_sources", "Read its repository's spec and tests",
                     f"Alignment reads {reach.READS}; it does not read {reach.CANNOT} yet, and names those it "
                     "finds, so you can tell whether what it proposes is current", _route(project.pid, "align"),
                     "align_scan")
    unread, docs, open_items = _scanned(project, scan)
    left = (f"; it did not read {reach.named(unread)}: if those hold its real requirements, findings or tasks, "
            "these items may be out of date, so reject what is stale" if unread else "")
    if open_items:
        where = f" from {', '.join(docs[:3])}" + (" and more" if len(docs) > 3 else "") if docs else ""
        old = _old_plans(project)
        stale = (f"; {_n(old, 'item')} may be from an old plan (the file is much older than the code): check they "
                 "still hold, and reject the ones the project has moved past") if old else ""
        return _step("map_sources", f"Review {_n(len(open_items), 'item')} read{where}",
                     f"accept, edit or reject what Alignment read{where} so its plan and tests are its own"
                     + stale + left, _route(project.pid, "align"), "align_decide", unread=unread)
    if unread:
        return _step("map_sources", "Its real sources were not read",
                     f"Alignment read {', '.join(docs[:3]) or 'no spec document'} and did not read "
                     f"{reach.named(unread)}; it reads {reach.READS}: write what holds its requirements and tasks "
                     "into one of those (a requirements document or a tasks list) and read it again",
                     _route(project.pid, "align"), "align_scan", unread=unread)
    return None


def _latest_assessment(project: Any) -> dict[str, Any] | None:
    folder = project.path("assessments")
    runs = [p for p in folder.glob("AS-*.json") if p.stem.split("-")[-1].isdigit()] if folder.is_dir() else []
    if not runs:
        return None
    import json

    try:
        return json.loads(max(runs, key=lambda p: int(p.stem.split("-")[-1])).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def top_findings(project: Any, n: int = 3) -> list[dict[str, Any]]:
    """The latest assessment's failed checks, most severe first."""
    got = _latest_assessment(project) or {}
    failed = [c for c in got.get("checks") or [] if isinstance(c, dict) and c.get("verdict") == "failed"]
    failed.sort(key=lambda c: SEVERITY.get(str(c.get("severity") or "").lower(), 5))
    return [{"id": c.get("id") or c.get("key"), "title": _clip(c.get("title") or c.get("key") or "a finding", 120),
             "severity": c.get("severity"), "perspective": c.get("perspective")} for c in failed[:n]]


def _findings_step(project: Any) -> dict[str, Any] | None:
    if project.meta.get("source_kind") != "adopted":
        return None
    if _latest_assessment(project) is None:
        return _step("assess", "Assess it", "no assessment yet: its risks and gaps are not known",
                     _route(project.pid, "assessment"), "run_assessment")
    top = top_findings(project)
    if not top:
        return None
    first = top[0]
    sev = f"{first['severity']}: " if first.get("severity") else ""
    return _step("findings", f"Look at the top {_n(len(top), 'finding')}",
                 f"the most severe is {sev}{first['title']}; check each is real before acting on it",
                 _route(project.pid, "assessment"), None, findings=top)


def _agent_step(project: Any) -> dict[str, Any] | None:
    if project.meta.get("source_kind") not in ("adopted", "attached"):
        return None
    from kernel import agent_channel as ch
    from kernel.devsessions import sessions

    worked = sessions(project) or any((m.get("author") or {}).get("kind") == "agent" or m.get("kind") == "handoff"
                                      for m in ch.read(project)["messages"])
    if worked:
        return None
    return _step("connect_agent", "Connect your coding agent",
                 "no coding agent has worked on it here yet; give Claude Code, Codex or Cursor the project's brief "
                 "and Rihma's tools, so what it does comes back here", _route(project.pid, "overview"), "handoff")


def _route_of(project: Any, a: dict[str, Any]) -> str:
    pid = project.pid
    if a.get("card"):
        return _route(pid, "inbox", a["card"])
    if a.get("question"):
        return _route(pid, "questions", a["question"])
    if a.get("page"):
        return f"#/{a['page']}"
    return _route(pid, a.get("view") or "overview")


def _waits(project: Any) -> tuple[list[dict[str, Any]], str | None]:
    """What kernel/next_step.py says the project waits for, as steps."""
    from kernel.next_step import next_step

    try:
        nx = next_step(project)
    except (OSError, ValueError, KeyError):
        return [], None
    why = "it waits for " + (nx.get("waits_for") or "a person")
    steps = [_step(a["id"], SOURCE_TAG.sub("", a["label"]), why, _route_of(project, a), a.get("control"),
                   personas=a.get("personas") or [], **({"card": a["card"]} if a.get("card") else {}))
             for a in nx.get("actions") or [] if a.get("id") not in ("watch",)]
    return steps, nx.get("waits_for")


def steps(project: Any) -> tuple[list[dict[str, Any]], str | None]:
    """At most three things to do now, the most pressing first, and what the project waits for."""
    canon = _canon(project)
    own = [s for s in (_kind_step(project, canon), _upstream_step(project, canon), _sources_step(project),
                       _findings_step(project), _agent_step(project)) if s is not None]
    waits, waits_for = _waits(project)
    adopted = project.meta.get("source_kind") in ("adopted", "attached")
    picked: list[dict[str, Any]] = []
    for s in (own + waits if adopted else waits + own):
        if len(picked) == MAX_STEPS:
            break
        if any(s["id"] == p["id"] or (s.get("card") and s.get("card") == p.get("card")) for p in picked):
            continue
        picked.append(s)
    return picked, waits_for


# -- what runs on its own meanwhile ---------------------------------------------------------------------------

def _running(project: Any, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The cell building a task now and the project's jobs running in the background, each with its log."""
    from kernel import status as kstatus

    pid, rows = project.pid, []
    try:
        lv = kstatus.live(project)
    except (OSError, ValueError):
        lv = {}
    if lv.get("running") and not lv.get("ended"):
        rows.append({"what": f"Building {lv.get('task')} now", "route": _route(pid, "tasks", lv.get("task")),
                     "log": {"project": pid}})
    rows += [{"what": f"Running {j.get('title') or j.get('kind')} in the background", "route": f"#/jobs/{j['id']}",
              "log": {"job": j["id"]}} for j in jobs if j.get("state") == "running"]
    return rows


def _scheduled(project: Any) -> list[dict[str, Any]]:
    """The automations that reach the project and its health checks on a schedule."""
    from kernel import automations as au
    from kernel.checks.store import enabled

    pid, rows = project.pid, []
    active = [a for a in au.automations(project.factory)
              if a.get("state") == "active" and au.in_scope(project, a.get("scope") or {"kind": "none"})]
    if active:
        names = ", ".join(str(a.get("name") or a.get("id")) for a in active[:3])
        rows.append({"what": f"{_n(len(active), 'automation')} run on their triggers: {names}"
                             + (" and more" if len(active) > 3 else ""), "route": _route(pid, "automations")})
    checks = sorted(enabled(project))
    if checks:
        rows.append({"what": f"{_n(len(checks), 'health check')} run on their schedule: {', '.join(checks[:4])}",
                     "route": _route(pid, "checks")})
    return rows


def meanwhile(project: Any, jobs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """What Rihmasto does on its own for the project, each with where to see it; or that nothing does, and how."""
    from kernel import adopt_watch

    pid, w = project.pid, adopt_watch.view(project)
    watched = [{"what": w["line"], "route": _route(pid, "automations")}] if w.get("watching") else []
    rows = _running(project, jobs or []) + watched + _scheduled(project)
    if rows:
        return {"rows": rows, "none": None}
    offer = (_step("watch", "Set up a watch", "nothing runs here on its own yet: a watch looks for new commits, "
                   "activity by area and failed checks", _route(pid, "overview"), "watch_setup")
             if w.get("offered") else
             _step("automate", "Set up an automation", "nothing runs here on its own yet: an automation runs a check, "
                   "a sync or a report on a schedule or an event", _route(pid, "automations"), "automations_new"))
    return {"rows": [], "none": offer}


# -- hidden for a person ---------------------------------------------------------------------------------------

def _last_choice(project: Any, person: str | None) -> dict[str, Any] | None:
    if not person:
        return None
    rows = [r["event"] for r in project.ledger().records()
            if (r.get("event") or {}).get("kind") in (HIDDEN, SHOWN)
            and ((r["event"].get("payload") or {}).get("person") == person)]
    return rows[-1] if rows else None


def hidden_for(project: Any, person: str | None, shown_ids: list[str]) -> dict[str, Any]:
    """Whether ``person`` hid the panel and it stays hidden: a step it did not show when hidden brings it back."""
    last = _last_choice(project, person)
    if last is None or last.get("kind") != HIDDEN:
        return {"hidden": False, "new": []}
    seen = set((last.get("payload") or {}).get("steps") or [])
    new = [s for s in shown_ids if s not in seen]
    return {"hidden": not new, "new": new, "at": last.get("at")}


def choose(project: Any, *, person: str, persona: str, hide: bool) -> dict[str, Any]:
    """Record that ``person`` hid (``hide``) or showed the panel again, with the steps it shows now."""
    if not is_person(person) or persona not in PERSONAS:
        raise StartHereRefused("hiding or showing Start here is signed by a named person with their persona")
    ids = [s["id"] for s in steps(project)[0]]
    rec = project.log(HIDDEN if hide else SHOWN, {"person": person, "persona": persona, "steps": ids})
    return {"hidden": hide, "at": rec["event"].get("at"), "steps": ids}


# -- the panel ----------------------------------------------------------------------------------------------

def said(u: dict[str, Any], picked: list[dict[str, Any]], mw: dict[str, Any]) -> str:
    """The panel in words: what Ask Rihma says to "what should I do here?"."""
    lines = [f"What I understood: {u['line']} (from {u['basis']}; Correct it if it is wrong)."]
    if picked:
        lines.append("Do now: " + " ".join(f"{i}. {s['label']}: {s['why']}." for i, s in enumerate(picked, 1)))
    else:
        lines.append("Nothing waits on you here now.")
    if mw["rows"]:
        lines.append("Meanwhile, on its own: " + "; ".join(r["what"] for r in mw["rows"]) + ".")
    elif mw["none"]:
        lines.append(f"Meanwhile: {mw['none']['why']}. {mw['none']['label']} does that.")
    return " ".join(lines)


def panel(project: Any, *, person: str | None = None, jobs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The Start here panel of ``project`` for ``person`` (whether they hid it), by rule."""
    if project.pid.startswith("_"):
        return {"project": project.pid, "applies": False,
                "why": "Start here is a project's: open a project, or ask Rihma what to do across them"}
    u = understood(project)
    picked, waits_for = steps(project)
    mw = meanwhile(project, jobs)
    return {"project": project.pid, "applies": True, "understood": u, "steps": picked, "waits_for": waits_for,
            "meanwhile": mw, "said": said(u, picked, mw), "by": "rule", **hidden_for(project, person,
                                                                                    [s["id"] for s in picked])}


__all__ = ["MAX_STEPS", "StartHereRefused", "choose", "hidden_for", "meanwhile", "panel", "said", "steps",
           "top_findings", "understood"]
