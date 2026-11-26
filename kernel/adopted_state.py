"""An adopted project's real state, instead of the factory's seven stages (FR-RPJ1; docs/brownfield.md).

A project the factory builds moves through need, concept, spec, build, validation and run. An adopted one did
not: it arrived built (or as a body of work), and the factory monitors, maintains or improves it. Its page
shows that, from its records: what it is doing (monitoring, maintaining, improving), what was taken (the last
commit, the working copy, a snapshot, documents), its baseline and the command that produced it, what was
left out, its last look upstream, its watch (kernel/adopt_watch.py), its activity by area (kernel/areas.py),
the stated commands it could run as a baseline (kernel/adopt_stated.py) and how it is used today.
"""

from __future__ import annotations

from typing import Any

STATES = {"monitor": "monitoring", "maintain": "maintaining", "improve": "improving"}
USAGE = {"explore": "an experiment", "demo": "a prototype", "pilot": "in use by a few", "production": "in production"}
TOOK = {"commit": "its last commit", "working copy": "its working copy (a snapshot)",
        "snapshot": "a snapshot of the folder", "documents": "its documents, to track and evaluate"}


def _baseline(project: Any) -> dict[str, Any]:
    b = project.read("baseline.json") or {}
    runs = b.get("runs") or []
    command = b.get("command") or (" ".join(runs[0].get("command") or []) if runs else None)
    return {"verdict": b.get("verdict") or "not measured", "reason": b.get("reason"), "command": command,
            "stated": bool(b.get("stated")), "revision": (b.get("revision") or "")[:12],
            "failed": b.get("verdict") == "failed"}


def _activity(areas: dict[str, Any] | None) -> dict[str, Any]:
    if not areas or not areas.get("measured"):
        return {"measured": False, "line": "activity not measured yet"}
    act = areas.get("activity") or {}
    if not act.get("measured"):
        return {"measured": False, "line": str(act.get("basis") or "activity not measured")}
    month = act["windows"].get("30") or []
    commits = max((a["commits"] for a in month), default=0)
    line = (f"active in {len(month)} area(s) over 30 days (up to {commits} commits in one), most recently "
            + ", ".join(act.get("recent", [])[:3])) if month else "no commits in the last 30 days"
    return {"measured": True, "line": line, "recent": act.get("recent", [])[:3]}


def state(project: Any) -> dict[str, Any] | None:
    """The adopted project's state for its page, or None when it was not adopted."""
    from kernel import adopt_stated, adopt_watch
    from kernel.adopt import is_adopted

    if not is_adopted(project):
        return None
    adopted = project.read("adopted.json") or {}
    meta = project.meta
    intent = adopted.get("intent") or meta.get("intent") or "improve"
    base = _baseline(project)
    areas = project.read("areas.json", None)
    took = adopted.get("took") or ("snapshot" if adopted.get("snapshot") else "commit")
    sync = adopted.get("last_sync") or {}
    words = [f"Adopted, {STATES.get(intent, intent)}", f"baseline {base['revision'] or '?'}: {base['verdict']}"
             + (f" ({base['command']})" if base["command"] else "")]
    if sync.get("at"):
        words.append(f"last look upstream {sync['at'][:10]}: {sync.get('new_commits', 0)} new commit(s)")
    return {"intent": intent, "state": STATES.get(intent, intent), "took": took, "took_said": TOOK.get(took, took),
            "source": adopted.get("source"), "origin": adopted.get("origin"), "left_out": adopted.get("left_out"),
            "baseline": base, "last_sync": sync or None, "watch": adopt_watch.view(project),
            "activity": _activity(areas), "has_areas": bool(areas and areas.get("measured")),
            "usage": {"maturity": meta.get("maturity"), "said": USAGE.get(meta.get("maturity") or "", "not said")},
            "stated": adopt_stated.offers(project), "line": " · ".join(words)}
