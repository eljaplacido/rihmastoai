"""Ask Rihma about a project's own sources (FR-SRC1), by rule and without a model, with Take me there.

- "Where does this project keep its requirements?" (its tests, findings, tasks; "what are its own sources", "how
  do I sync this project with Rihmasto"): what is mapped and when it was read, what is found and not mapped (each a
  proposal to map it), the planning documents that may be old plans, its test roots, and the next steps;
- "Use the rule files as requirements", "use rounds/*/README.md as tasks", "treat evidence/issues.jsonl as
  findings": a proposal to map the detected source the words name best (or the glob they give), which the person
  confirms, signed;
- "Read the sources again", "stop reading SRC-2", "use docs/plan.md anyway": a proposal of the same signed write
  the panel's buttons make (kernel/assistant_ops.py). Running the project's own tests stays a click beside its yes.
"""

from __future__ import annotations

import re
from typing import Any

# op -> (label, method, path template, the arguments it needs, the arguments it sends, the map's control)
OPS: dict[str, tuple[str, str, str, tuple[str, ...], tuple[str, ...], str]] = {
    "map_source": ("Use it as the project's own source", "POST", "/api/projects/{pid}/sources/map", (),
                   ("key", "spec", "every", "source"), "sources_map"),
    "stop_source": ("Stop reading a source", "POST", "/api/projects/{pid}/sources/{source}/stop", ("source",),
                    ("reason",), "sources_stop"),
    "read_sources": ("Read the project's own sources again", "POST", "/api/projects/{pid}/sources/read", (), (),
                     "sources_read"),
    "use_old_plan": ("Use a planning document anyway", "POST", "/api/projects/{pid}/sources/use-anyway", ("path",),
                     ("path",), "sources_use_anyway"),
}
KIND_WORDS = {"requirement": "requirements", "rule": "requirements", "law": "requirements", "criteria": "requirements",
              "task": "tasks", "plan": "tasks", "finding": "findings", "issue": "findings", "bug": "findings",
              "result": "results", "gate": "results", "test": "tests"}
WHERE = re.compile(r"\bwhere\b[^?.!]{0,50}\b(?:keep|keeps|kept|live|lives|store|stores|are|is)\b[^?.!]{0,30}"
                   r"\b(requirements?|rules|laws|criteria|tests?|test results|results|findings|issues|tasks|plan)\b"
                   r"|\b(?:own|native) sources\b|\bsync\b[^?.!]{0,40}\bwith rihmasto\b|\bfeed rihmasto\b"
                   r"|\bwhat should rihmasto read\b", re.IGNORECASE)
USE = re.compile(r"\b(?:use|map|read|take|treat)\s+(?:the\s+)?(?P<what>[^?!]{2,80}?)\s+as\s+(?:the\s+)?(?:project'?s\s+"
                 r"|its\s+|our\s+)?(?:own\s+)?(?P<kind>requirements?|rules|criteria|tasks?|findings?|issues"
                 r"|test results?|gate results?|results|test runs?|runs|tests?|test roots)\b", re.IGNORECASE)
STOP = re.compile(r"\bstop\s+(?:reading|using)\b[^?!]{0,40}?\b(SRC-\d{1,6})\b", re.IGNORECASE)
RESUME = re.compile(r"\b(?:resume|restart|start\s+reading|read)\b[^?!]{0,30}?\b(SRC-\d{1,6})\b", re.IGNORECASE)
READ = re.compile(r"\b(?:read|re-?read|refresh|reload)\b[^?!]{0,30}\bsources?\b(?![^?!]*\bas\b)", re.IGNORECASE)
OLD = re.compile(r"\buse\s+(?P<path>[\w./-]+\.md)\s+anyway\b", re.IGNORECASE)
CONTROL = "sources_panel"


def _kind(word: str) -> str:
    """The kind the words name: results and runs before tests, so "test results" are results (FR-SRC2)."""
    low = word.lower()
    if "result" in low or re.search(r"\bruns?\b", low):
        return "results"
    return next((k for w, k in KIND_WORDS.items() if low.startswith(w)), "requirements")


def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3} - {"the", "file", "folder",
                                                                                              "json", "yaml", "jsonl"}


def _out(project: Any, answer: str, propose: list | None = None, control: str = CONTROL) -> dict[str, Any]:
    route = f"#/p/{project.pid}/overview" if project is not None else "#/projects"
    open_it = {"action": "open", "args": {"route": route}, "why": "See the project's own sources: Map, Change, Stop, "
               "Read again, run its tests or import their results", "project": project.pid if project else None}
    return {"answer": answer, "navigate": {"route": route, "control": control}, "propose": [open_it, *(propose or [])],
            "dropped": [], "sources": [], "by": "rule", "matches": ["sources"]}


def _act(factory: Any, op: str, args: dict[str, Any], persona: str, project: Any, summary: str) -> list:
    from kernel import assistant_ops

    found = assistant_ops.proposal(factory, op, {**args, "project": project.pid}, persona=persona, project=project,
                                   summary=summary)
    return [found | {"why": summary}] if found else []


def _mapped_line(s: dict[str, Any], v: dict[str, Any] | None = None) -> str:
    last = s.get("last") or {}
    if s["kind"] == "tests":           # test roots are run, not read: their latest runs say them (FR-SRC2)
        ran = {r.get("root"): r for r in reversed((v or {}).get("runs") or []) if r.get("from") == "run here"}
        roots = "; ".join(f"{r['root'] or '.'} `{r['command']}`: "
                          + (ran[r["root"]]["verdict"] if r["root"] in ran else "not run yet")
                          for r in s.get("roots") or [])
        return f"{s['kind_label']}: {roots or 'none'} ({s['id']})"
    read = (f"{last.get('records', 0)} record(s) from {last.get('files', 0)} file(s), read {last.get('read_at')}"
            if last else "not read yet")
    return f"{s['kind_label']}: {s['glob'] or 'its test roots'} ({s['id']}, {read}, read again {s['every_said']})"


def where(factory: Any, project: Any, persona: str) -> dict[str, Any]:
    from kernel.native_apply import view

    v = view(project)
    title = project.meta.get("title") or project.pid
    if not v["applies"]:
        return _out(project, f"{title}: {v['why']}.")
    propose = [x for p in v["detected"][:3] for x in _act(factory, "map_source", {"key": p["key"]}, persona, project,
                                                         f"Use {p['sample']} as its test roots" if p["kind"] == "tests"
                                                         else f"Use {p['glob']} as {v['kinds'][p['kind']].lower()}")]
    return _out(project, "\n".join(_where_lines(v, title)), propose)


def _listed(head: str, items: list[str]) -> list[str]:
    return [head, *(f"- {x}" for x in items)] if items else []


def _held_lines(v: dict[str, Any], title: str, mapped: list[dict[str, Any]]) -> list[str]:
    """What is mapped, what is stopped, and the latest runs (FR-SRC2)."""
    lines = [f"{title} keeps its own:" if mapped else f"{title}: nothing is mapped as its own source yet."]
    lines += [f"- {_mapped_line(s, v)}" for s in mapped]
    lines += _listed("Stopped (say \"resume SRC-n\" to read one again):",
                     [f"{s['kind_label']}: {s['glob'] or 'its test roots'} ({s['id']}, "
                      f"{s['stopped'].get('reason') or 'no reason given'})" for s in v.get("stopped") or []])
    return lines + _listed("Its latest runs:", [r["line"] for r in (v.get("runs") or [])[:4]])


def _where_lines(v: dict[str, Any], title: str) -> list[str]:
    mapped = [s for s in v["mapped"] if s["state"] == "mapped"]
    lines = _held_lines(v, title, mapped)
    lines += _listed("Found by rule, not mapped yet:", [f"{v['kinds'][p['kind']]}: {p['glob'] or 'its test roots'}: "
                                                         f"{p['why']}" for p in v["detected"]])
    lines += _listed("Left out as they may be old plans (say \"use <path> anyway\" to keep one):",
                     [f"{s['path']}: {s['why']}" for s in v["stale"][:5]])
    lines += [f"{label}: {said}." for label, said in (("Its tests", v["root_note"]), ("Trace", v["trace"]["line"]),
                                                       ("Not measured", v["unreadable"])) if said]
    if not mapped and not v["detected"]:
        lines.append("Nothing was found by rule. Tell me the files, for example \"use rules/*.json as requirements\" "
                     "or \"use docs/rounds/*/README.md as tasks\", and I propose the mapping for you to confirm.")
    steps = [s["label"] for s in v["next"]]
    return lines + (["Next: " + "; ".join(steps[:4]) + "."] if steps else [])


def _best(cands: list[dict[str, Any]], what: str, glob: str | None) -> dict[str, Any] | None:
    """The detected source the words name best: the glob they give, else the most words in common (or the only one)."""
    want = _words(what)
    scored = sorted(((len(want & _words(f"{p['glob']} {p['why']} {p.get('sample') or ''}")), p["key"], p)
                     for p in cands if glob is None or p["glob"] == glob), key=lambda x: (-x[0], x[1]))
    return scored[0][2] if scored and (scored[0][0] or len(scored) == 1) else None


def _old(factory: Any, project: Any, persona: str, path: str) -> dict[str, Any]:
    """Use a planning document anyway: only one marked as an old plan; any other is said to be in use already."""
    from kernel.native_apply import view

    v = view(project)
    if path in v["use_anyway"]:
        return _out(project, f"{path} is used already: you said to use it although it may be an old plan.")
    if path not in [s["path"] for s in v["stale"]]:
        return _out(project, f"{path} is not marked as an old plan, so nothing is left out: alignment reads it as "
                             "it is. Old plans: " + (", ".join(s["path"] for s in v["stale"]) or "none") + ".")
    return _out(project, f"I can use {path} although it may be an old plan; you confirm it, signed.",
                _act(factory, "use_old_plan", {"path": path}, persona, project, f"Use {path} anyway"),
                "sources_use_anyway")


def _resume(factory: Any, project: Any, persona: str, sid: str) -> dict[str, Any]:
    from kernel import native_sources as ns

    have = next((s for s in ns._book(project)["sources"] if s["id"] == sid), None)
    if have is None:
        return _out(project, f"There is no source {sid}.")
    what = f"{ns.KINDS[have['kind']]}: {have['glob'] or 'its test roots'}"
    if have.get("state") == "mapped":
        return _out(project, f"{sid} is read already ({what}).")
    return _out(project, f"I can read {sid} again ({what}), as it was mapped before it was stopped; you confirm it, "
                         "signed.",
                _act(factory, "map_source", {"source": sid, "spec": {}}, persona, project, f"Resume {sid}"),
                "sources_map")


def _already(v: dict[str, Any], kind: str, what: str, glob: str | None) -> dict[str, Any] | None:
    """The mapped source of this kind the words name: its glob, or the most words in common."""
    mine = [dict(s, key=s["id"], why=s.get("label") or s["kind_label"]) for s in v["mapped"]
            if s["state"] == "mapped" and s["kind"] == kind]
    return _best(mine, what, glob) if mine else None


def _mapped_already(project: Any, v: dict[str, Any], kind: str, what: str, glob: str,
                    named: str | None) -> dict[str, Any] | None:
    """When the words name a source mapped already (and no better one found), the answer says which (FR-SRC2)."""
    have = _already(v, kind, what, named)
    cands = [p for p in v["detected"] if p["kind"] == kind]
    if have is None or (_best(cands, what, named) and have.get("glob") != glob):
        return None
    return _out(project, f"{have['glob'] or 'Its test roots'} is already mapped as {have['id']} "
                         f"({v['kinds'][kind].lower()}, read again {have['every_said']}). Change or Stop it in the "
                         "project's own sources.", control="sources_change")


def _use(factory: Any, project: Any, persona: str, what: str, kind: str) -> dict[str, Any]:
    from kernel.native_apply import view

    v = view(project)
    cands = [p for p in v["detected"] if p["kind"] == kind]
    glob = what.strip().strip("`'\"")
    pathlike = bool(re.search(r"[/*]|\.\w{2,5}$", glob))
    label = v["kinds"][kind].lower()
    said = _mapped_already(project, v, kind, what, glob, glob if pathlike else None)
    if said is not None:
        return said
    p = _best(cands, what, glob if pathlike else None)
    if p is not None:
        return _out(project, f"I can use {p['glob'] or 'its test roots'} as {label}: {p['why']}. With its mapping "
                             f"{p['mapping'] or 'by its format'}. You confirm it, signed; then it is read, and the "
                             "contract, tasks, findings and trace come from it, marked as the project's own source.",
                    _act(factory, "map_source", {"key": p["key"]}, persona, project,
                         f"Use {p['glob'] or 'its test roots'} as {label}"), "sources_map")
    if pathlike and re.fullmatch(r"[\w.*?/@+ -]{2,200}", glob):
        spec = {"kind": kind, "glob": glob}
        return _out(project, f"I found no {label} by rule matching \"{what}\", but I can read {glob} as {label}, with "
                             "the field mapping guessed from the files. You confirm it, signed.",
                    _act(factory, "map_source", {"spec": spec}, persona, project, f"Use {glob} as {label}"),
                    "sources_map")
    found = ", ".join(p["glob"] for p in cands) or "none"
    return _out(project, f"I found no {label} matching \"{what}\" (found as {label}: {found}). Name the files, for "
                         f"example \"use rules/*.json as {label}\".")


def answer(factory: Any, question: str, project: Any, persona: str) -> dict[str, Any] | None:
    """Ask Rihma's answer about a project's own sources, by rule; None when the words ask something else."""
    q = question or ""
    if not any(rx.search(q) for rx in (WHERE, USE, STOP, OLD, READ, RESUME)):
        return None
    if project is None or project.pid.startswith("_"):
        return _out(None, "A project's own sources are read from its repository: open an adopted or attached "
                          "project and ask there.") if WHERE.search(q) else None
    from kernel import native_sources as ns

    if not ns.applies(project):
        return _out(project, f"{project.meta.get('title') or project.pid} has no repository of its own: its own "
                             "sources are read from an adopted or attached project's repository.")
    return _doing(factory, q, project, persona, bool(ns.active(project)))


def _doing(factory: Any, q: str, project: Any, persona: str, mapped: bool) -> dict[str, Any] | None:
    """A proposal for the write the words ask for, else where the project keeps its own."""
    m_use, m_stop, m_old, m_resume = USE.search(q), STOP.search(q), OLD.search(q), RESUME.search(q)
    if m_old:
        return _old(factory, project, persona, m_old.group("path"))
    if m_stop:
        sid = m_stop.group(1).upper()
        return _out(project, f"I can stop reading {sid}; it is kept, stopped, and you confirm it, signed.",
                    _act(factory, "stop_source", {"source": sid}, persona, project, f"Stop reading {sid}"),
                    "sources_stop")
    if m_resume:
        return _resume(factory, project, persona, m_resume.group(1).upper())
    if m_use:
        return _use(factory, project, persona, m_use.group("what"), _kind(m_use.group("kind")))
    if READ.search(q) and not WHERE.search(q) and mapped:
        return _out(project, "I can read every mapped source again from the repository's latest committed revision; "
                             "you confirm it, signed.",
                    _act(factory, "read_sources", {}, persona, project, "Read the sources again"), "sources_read")
    return where(factory, project, persona) if WHERE.search(q) else None
