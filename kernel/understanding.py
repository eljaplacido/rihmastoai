"""What Rihmasto understood about a project, in one place, so a person can judge it and correct it (the owner,
2026-11-25: "How can I even judge that the platform understands a given project if there's not any overview or
description of it?").

By rule, with no model, from what adoption and the later steps recorded in the project's folder: what it says it
is (its README's first paragraph or the spec's summary), its shape (languages, kind of work, a Dockerfile, HTTP
routes), its areas, its tests (the command and the baseline's verdict), what was read of it, its contract, its
latest assessment, and the AI-tool setup found. What could not be worked out is listed as such, never guessed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read(project: Any, name: str) -> Any:
    path = Path(project.path(name))
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def _latest_assessment(project: Any) -> dict[str, Any] | None:
    folder = Path(project.path("assessments"))
    runs = sorted(folder.glob("AS-*.json"), key=lambda p: int(p.stem.split("-")[1]) if p.stem.split("-")[1].isdigit()
                  else 0) if folder.is_dir() else []
    if not runs:
        return None
    got = json.loads(runs[-1].read_text(encoding="utf-8"))
    return {"id": runs[-1].stem, "counts": got.get("counts") or {}}


def _what(inv: dict[str, Any], spec: dict[str, Any], meta: dict[str, Any]) -> tuple[str, str]:
    first = ((inv.get("readme") or {}).get("first_paragraph") or "").strip()
    if first:
        return first, f"the first paragraph of its {inv['readme'].get('file') or 'README'}"
    if (spec.get("summary") or "").strip():
        return spec["summary"].strip(), "the spec's summary"
    return "", "nothing: it has no README paragraph and no summary yet"


def _tests(inv: dict[str, Any], base: dict[str, Any]) -> tuple[str, bool]:
    cmd = inv.get("test_command") or {}
    if cmd.get("detected"):
        run = cmd.get("command")
        run = " ".join(run) if isinstance(run, list) else str(run)
        return f"`{run}`; at adoption: {base.get('verdict') or 'not run'}", True
    return "no test command found by rule, so nothing about its behaviour is measured yet", False


def _shape(inv: dict[str, Any], adopted: dict[str, Any]) -> list[str]:
    langs = ", ".join(f"{x['language']} ({x['files']} files)" for x in (inv.get("languages") or [])[:6])
    out = [f"Languages: {langs or 'none recognised'}"]
    prof = adopted.get("profile")
    if isinstance(prof, dict) and prof.get("profile"):
        guess = prof.get("confidence") == "uncertain"
        out.append(f"Kind of work: {prof['profile'].replace('_', ' ')}"
                   + (f" (a guess: {prof.get('why') or 'nothing stood out'})" if guess else ""))
    elif isinstance(prof, str):
        out.append(f"Kind of work: {prof.replace('_', ' ')}")
    out.append("A Dockerfile: " + ("yes" if (inv.get("dockerfile") or {}).get("present") else "no"))
    if inv.get("http_routes"):
        out.append(f"HTTP routes found in the code: {inv['http_routes']}")
    return out


def take(project: Any) -> dict[str, Any] | None:
    """The understanding, or None for a project that was not adopted (it has no inventory)."""
    inv = _read(project, "inventory.json")
    if not isinstance(inv, dict):
        return None
    spec, adopted = _read(project, "spec.json") or {}, _read(project, "adopted.json") or {}
    base, material = _read(project, "baseline.json") or {}, _read(project, "material.json") or {}
    areas, contract = _read(project, "areas.json") or {}, _read(project, "contract.json") or {}
    what, said_by = _what(inv, spec, project.meta)
    tests, measured = _tests(inv, base)
    ctx = material.get("agent_context") or {}
    listed = areas.get("areas")
    return {
        "what": what, "said_by": said_by, "source": adopted.get("source") or project.meta.get("upstream"),
        "intent": project.meta.get("intent"), "shape": _shape(inv, adopted),
        "areas": [a.get("area") for a in listed][:8] if isinstance(listed, list) else [],
        "tests": tests, "read": _read_line(material.get("totals") or {}),
        "ai_tools": [k for k in ("instructions", "skills", "agents", "commands", "settings", "mcp") if ctx.get(k)],
        "contract": f"{len(contract.get('requirements') or [])} requirement(s) as it is (observed, not yet specified)",
        "assessment": _latest_assessment(project), "not_understood": _gaps(what, measured, inv, areas, adopted),
        "by": "rule (kernel/understanding.py), no model",
    }


def _read_line(totals: dict[str, Any]) -> str | None:
    if not totals:
        return None
    return (f"{totals.get('read', 0)} files read, {totals.get('summarised', 0)} summarised, "
            f"{totals.get('listed', 0)} listed by name, {totals.get('skipped', 0)} skipped")


def _gaps(what: str, measured: bool, inv: dict[str, Any], areas: dict[str, Any], adopted: dict[str, Any]) -> list[str]:
    """What could not be worked out by rule, each with how to fill it in."""
    prof = adopted.get("profile")
    guessed = isinstance(prof, dict) and prof.get("confidence") == "uncertain"
    gaps = [
        (not what, "what the project is for: add a README paragraph, or describe it (Correct or add to it)"),
        (not measured, "how to run its tests: name the command (Overview, Run its tests) so behaviour is measured"),
        (not (inv.get("endpoints") or {}).get("scanned"), "its running endpoints: no address was given to probe"),
        (not areas.get("measured"), "its areas over time: not measured yet"),
        (guessed, "what kind of work it is: Rihmasto guessed; confirm or change it in the project's settings"),
    ]
    return [text for missing, text in gaps if missing]


def _commits(project: Any, n: int = 8) -> list[dict[str, str]]:
    """The newest commits on the project's main, by rule from its mirror: what is being worked on."""
    import subprocess

    bare = Path(project.path("repo.git"))
    if not bare.is_dir():
        return []
    try:
        out = subprocess.run(["git", "--git-dir", str(bare), "log", "main", f"-n{n}", "--format=%h%x09%as%x09%s"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows = [ln.split("\t", 2) for ln in out.splitlines() if ln.count("\t") >= 2]
    return [{"commit": c, "date": d, "subject": s[:140]} for c, d, s in rows]


PRIVACY = ("privacy", "personal", "gdpr", "pii", "secret", "credential", "consent", "retention")


def _findings(assessment_path: Path | None) -> list[dict[str, Any]]:
    if assessment_path is None:
        return []
    got = json.loads(assessment_path.read_text(encoding="utf-8"))
    return [c for c in got.get("checks") or [] if c.get("verdict") == "failed"]


def lenses(project: Any, u: dict[str, Any]) -> dict[str, Any]:
    """The same understanding for each reader: a developer (what was built, what is next), compliance and IT
    (security, compliance and privacy findings), and a business owner (the goal, what is agreed, the risks)."""
    folder = Path(project.path("assessments"))
    latest = folder / f"{u['assessment']['id']}.json" if u.get("assessment") else None
    failed = _findings(latest if latest and latest.is_file() else None)
    return {"developer": _developer(project), "compliance": _risk(project, failed, bool(latest)),
            "business": _business(project, u, failed)}


def _line(f: dict[str, Any]) -> str:
    return f"{f.get('id')} {f.get('title')} ({f.get('severity')})"


def _developer(project: Any) -> dict[str, Any]:
    from kernel.next_step import next_step

    nxt = next_step(project)
    snapshot = (_read(project, "adopted.json") or {}).get("source_kind") == "folder"
    history = ("adopted from a folder, not a git repository: its history before adoption is not known; changes "
               "from now on are") if snapshot else None
    return {"recent": [] if snapshot else _commits(project), "history": history,
            "next": [a.get("label") for a in (nxt.get("actions") or []) if a.get("label")][:4],
            "waits_for": nxt.get("waits_for")}


def _risk(project: Any, failed: list[dict[str, Any]], assessed: bool) -> dict[str, Any]:
    private = [f for f in failed if any(w in (str(f.get("title")) + str(f.get("summary"))).lower() for w in PRIVACY)]
    return {"security": [_line(f) for f in failed if f.get("perspective") == "security"],
            "compliance": [_line(f) for f in failed if f.get("perspective") == "compliance"],
            "privacy": [_line(f) for f in private], "confidential": bool(project.meta.get("confidential")),
            "assessed": assessed}


def _goal(project: Any) -> str:
    from kernel.canon import Canon

    try:
        goal = Canon(project).goal or ""
    except Exception:  # noqa: BLE001  (no canon goal yet)
        return ""
    same = goal.strip().lower() == str(project.meta.get("title") or "").strip().lower()
    return "" if same else goal               # the title repeated is not a goal


def _business(project: Any, u: dict[str, Any], failed: list[dict[str, Any]]) -> dict[str, Any]:
    goal = _goal(project)
    severe = [f for f in failed if f.get("severity") in ("critical", "high")]
    return {"goal": goal, "intent": project.meta.get("intent"), "agreed": u.get("contract"),
            "risks": [f"{f.get('title')} ({f.get('severity')})" for f in severe][:5],
            "impact": None if goal else ("no business goal or impact is stated yet: set the goal so progress and "
                                         "findings can be judged against it")}


ASKS = ("what is this project", "what's this project", "what is the project", "describe this project",
        "what do you know about", "what did you understand", "do you understand", "mikä tämä projekti",
        "what does this project do", "overview of this project", "summarise this project", "summarize this project")


def asks(question: str) -> bool:
    """Whether a question asks what the project is, or what Rihmasto knows about it."""
    q = (question or "").lower()
    return any(k in q for k in ASKS)


def answer(project: Any) -> dict[str, Any] | None:
    """Ask Rihma's answer, by rule."""
    u = take(project)
    if u is None:
        return None
    lines = [f"{project.meta.get('title')}: {u['what'] or '(no description found)'}  [from {u['said_by']}]",
             "Shape: " + "; ".join(u["shape"]) + ".", f"Tests: {u['tests']}."]
    if u["read"]:
        lines.append(f"Read at adoption: {u['read']}.")
    if u["assessment"]:
        c = u["assessment"]["counts"]
        lines.append(f"Assessment {u['assessment']['id']}: {c.get('findings', 0)} findings of "
                     f"{c.get('checks', 0)} checks.")
    if u["not_understood"]:
        lines.append("Not understood yet: " + "; ".join(u["not_understood"]) + ".")
    return {"answer": "\n".join(lines), "navigate": {"route": f"#/p/{project.pid}/overview", "control": "add_material"},
            "propose": [], "dropped": [], "sources": [], "by": "rule", "matches": []}
