"""The impact of a change to the enforcement levels, before anyone makes it (D-0026 enforcement levels, FR-ENF1).

``preview`` takes the same body as setting the levels (levels, a preset, reviewers) and says, writing nothing:

- each cell that would change, from what to what, with the scope it would come from and what happens there next;
- what the recorded outcomes of the guard (kernel/enforcement_guard.py) would have been under the new levels:
  how many notes would now be reviews or refusals, and the other way round;
- for the platform, which projects the change reaches and which keep their own setting for a changed cell.
"""

from __future__ import annotations

import copy
from typing import Any

from kernel import enforcement as ke
from kernel import enforcement_places as kplaces
from kernel.enforcement_guard import LEVEL_OUTCOME, recent
from kernel.hitl import persona_word
from kernel.learn import FACTORY_PID

NEXT = {"off": "Rihmasto will not look here; the project's own pipeline still does what it does.",
        "advise": "Rihmasto will note it and nudge; the work goes on.",
        "require_review": "A card will ask {who} to review it; the work goes on.",
        "enforce": "The work will wait until {who} decides its card."}


def _after(factory: Any, project: Any, wanted: dict, reviewers: dict) -> dict[tuple[str, str], dict[str, Any]]:
    """Every cell as it would be: the scope's own value replaced, else what it inherits."""
    out = {}
    for c in ke.grid(factory, project):
        to = (wanted.get(c["env"]) or {}).get(c["family"])
        new = dict(c)
        if to == ke.INHERIT:
            inherited = ke.cell(factory, None, c["env"], c["family"]) if project is not None else None
            new.update(level=inherited["level"] if inherited else ke.DEFAULT_LEVEL,
                       scope=inherited["scope"] if inherited else "default")
        elif to is not None:
            new.update(level=to, scope="project" if project is not None else "platform")
        who = reviewers.get(c["family"])
        if who and who != ke.INHERIT:
            new.update(reviewer=who, reviewer_scope="project" if project is not None else "platform")
        out[(c["env"], c["family"])] = new
    return out


def _would(project: Any, after: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    """The recorded outcomes on ``project`` as they would have been under ``after``."""
    moved: dict[str, int] = {}
    seen = 0
    for row in recent(project, limit=200):
        cell = after.get((str(row.get("env")), str(row.get("family"))))
        if cell is None or row.get("outcome") == "cleared":
            continue
        seen += 1
        now = LEVEL_OUTCOME[cell["level"]]
        if now != row.get("outcome"):
            key = f"{row.get('outcome')} -> {now}"
            moved[key] = moved.get(key, 0) + 1
    return {"looked_at": seen, "moved": moved}


def _changes(before: list[dict[str, Any]], after: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in before:
        new = after[(c["env"], c["family"])]
        if (new["level"], new["reviewer"]) == (c["level"], c["reviewer"]):
            continue
        who = persona_word(new["reviewer"])             # "IT / partner", never the raw id
        out.append({"env": c["env"], "family": c["family"], "from": c["level"], "to": new["level"],
                    "from_scope": c["scope"], "to_scope": new["scope"], "reviewer": new["reviewer"],
                    "next": NEXT[new["level"]].format(who=who)})
    return out


def _lines(changes: list[dict[str, Any]], would: dict[str, Any], reached: list[str], kept: list[dict]) -> list[str]:
    lines = [f"{ke.count(len(changes), 'setting')} would change." if changes else "Nothing would change."]
    if would["looked_at"]:
        moved = ", ".join(f"{n} {k.replace('->', 'would become')}" for k, n in sorted(would["moved"].items()))
        lines.append(f"Of the last {would['looked_at']} outcomes Rihmasto recorded, "
                     + (moved + "." if moved else "none would have been different."))
    else:
        lines.append("Rihmasto has recorded no outcome here yet, so there is nothing to compare with.")
    if reached:
        lines.append(f"It reaches {ke.count(len(reached), 'project')}.")
    if kept:
        lines.append(f"{ke.count(len(kept), 'project')} keep their own setting for a changed cell: "
                     + ", ".join(k["title"] for k in kept[:5]) + ".")
    return lines


def _reach(factory: Any, after: dict, changed: set) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    """A platform change: the projects it reaches (with what their records would have been) and those that keep
    their own setting for a changed cell."""
    reached: list[str] = []
    kept: list[dict[str, Any]] = []
    total: dict[str, Any] = {"looked_at": 0, "moved": {}}
    for p in factory.projects():
        if p.pid == FACTORY_PID:
            continue
        own = ke.project_settings(p)
        mine = {(e, f) for e, row in (own.get("levels") or {}).items() for f in row}
        if mine & changed:
            kept.append({"project": p.pid, "title": p.meta.get("title") or p.pid})
            continue
        reached.append(p.pid)
        w = _would(p, _after(factory, p, {}, {}) | {k: v for k, v in after.items() if k not in mine})
        total["looked_at"] += w["looked_at"]
        for k, n in w["moved"].items():
            total["moved"][k] = total["moved"].get(k, 0) + n
    return reached, kept, total


def _placing(factory: Any, project: Any, names: Any, gate_env: Any) -> list[dict[str, Any]]:
    """What placing names or the gate's stage would change (FR-ENF2), on a copy: nothing is written."""
    doc = copy.deepcopy(ke.project_settings(project) if project is not None else ke.platform_settings(factory))
    return kplaces.names_change(doc, names) + kplaces.gate_change(doc, gate_env)


def _placing_lines(placing: list[dict[str, Any]]) -> list[str]:
    out = []
    for c in placing:
        to = kplaces.WHERE.get(c["to"] or "", "where its words place it")
        what = f"'{c['name']}' would count as {to}" if "name" in c else f"A change the gate checks would enter {to}"
        out.append(what + (" (less strict than now: say why)." if c["looser"] else "."))
    return out


def preview(factory: Any, project: Any = None, *, levels: Any = None, preset: str | None = None,
            reviewers: Any = None, names: Any = None, gate_env: Any = None) -> dict[str, Any]:
    wanted, who = ke.wanted_levels(levels, preset), ke._checked_reviewers(reviewers)
    before = ke.grid(factory, project)
    after = _after(factory, project, wanted, who)
    changes = _changes(before, after)
    reached, kept, total = (([], [], _would(project, after)) if project is not None
                            else _reach(factory, after, {(c["env"], c["family"]) for c in changes}))
    placing = _placing(factory, project, names, gate_env)
    lines = _lines(changes, total, reached, kept)
    # What a save counts: every setting written in this scope, also one already in force from where it inherits.
    doc = copy.deepcopy(ke.project_settings(project) if project is not None else ke.platform_settings(factory))
    written = len(ke._apply(doc, wanted, who))
    if written + len(placing):
        lines[0] = f"{ke.count(written + len(placing), 'setting')} would change."
    if written > len(changes):
        lines.insert(1, f"{written - len(changes)} of them already have that level here, inherited; they become "
                        f"this {'project' if project is not None else 'platform'}'s own.")
    return {"scope": "project" if project is not None else "platform", "changes": changes, "would": total,
            "reached": reached, "kept": kept, "placing": placing, "lines": lines + _placing_lines(placing)}
