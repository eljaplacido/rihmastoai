"""Rihmasto's own words, by team and by project (D-0027, FR-TM2): an overlay read at read time.

The ontology (kernel/ontology.json) gives every kind of record, every relation and every attribute a label, a
description and synonyms. That is the **shipped default**. A **team** may say it differently for all its projects, and a
**project** may say it differently again; the word in force is the project's, else the team's, else the shipped one.
Per term a layer may:

- give a new ``label`` or ``description`` (a team that says "story" for "requirement"),
- add ``synonyms`` (they feed Ask Rihma's map search and its answers),
- ``hide`` the term (it leaves the Knowledge graph's legend and its views),
- add a **custom term** (``custom:<slug>``) that ``means`` an existing record kind: another word for it.

A redefinition changes how records are **read and labelled**, never the records: nothing stored is rewritten. Old
records read through the same overlay as new ones. Each definition is kept with who made it, why and since when (the
ledger, kernel/vocab_edit.py), shows its scope (this project, this team, the shipped default) and is undone to the
earlier reading exactly. There is no level above a team and none below a project (no individual's words).

Files: a team's in ``home/_teams/<team>.vocab.json``, a project's in its own ``vocabulary.json``
(``rihmasto.vocabulary/1``): ``{"terms": {<term id>: {label, description, synonyms, hidden, means, by, persona, why,
since}}}``. Term ids are ``kind:<id>``, ``rel:<id>``, ``attr:<key>`` and ``custom:<slug>``.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any

from kernel.learn import FACTORY_PID
from kernel.store import Factory, read_json, write_json

SCHEMA = "rihmasto.vocabulary/1"
SCOPES = ("team", "project")
FIELDS = ("label", "description", "synonyms", "hidden", "means")
TYPE_WORD = {"kind": "kind of record", "rel": "relation", "attr": "attribute", "custom": "custom term"}
SCOPE_WORD = {"project": "this project", "team": "this team", "shipped": "the shipped default"}
# The ontology's own code names, said as the cockpit says them (kernel/graph_view.py LABELS).
CODE_NAMES = {"kind:holdout_ref": "Held-out check", "kind:round": "Agent run"}
_ID = re.compile(r"(?:kind|rel|attr|custom):[a-z0-9_]{1,60}(?:-[a-z0-9_]{1,60})*")
_OWNER = re.compile(r"[a-z0-9][a-z0-9-]{0,80}\Z")


def norm(text: Any) -> str:
    """A word for comparing: lower case, single spaces, a plural "s" dropped."""
    low = " ".join(str(text or "").lower().split())
    if low.endswith("ies") and len(low) > 4:
        return low[:-3] + "y"
    return low[:-1] if low.endswith("s") and len(low) > 3 and not low.endswith("ss") else low


@functools.lru_cache(maxsize=1)
def _shipped() -> dict[str, dict[str, Any]]:
    from kernel.ontology import load

    onto = load()
    out: dict[str, dict[str, Any]] = {}
    for key, k in onto.kinds.items():
        tid = f"kind:{key}"
        out[tid] = {"label": CODE_NAMES.get(tid) or str(k.get("label", key)).split("@")[0],
                    "description": str(k.get("description", "")), "synonyms": list(k.get("aliases") or [])}
    for key, r in onto.relations.items():
        out[f"rel:{key}"] = {"label": str(r.get("label", key)), "description": str(r.get("description", "")),
                             "synonyms": list(r.get("aliases") or [])}
    for key, a in onto.refs.items():
        if "attribute" in a:
            out[f"attr:{key}"] = {"label": key.replace("_", " "), "description": str(a["attribute"]), "synonyms": []}
    return out


def shipped() -> dict[str, dict[str, Any]]:
    return {k: {**v, "synonyms": list(v["synonyms"])} for k, v in _shipped().items()}


def valid_id(term: str) -> bool:
    return bool(_ID.fullmatch(str(term)))


# -- the layers on disk ---------------------------------------------------------------------------------------

def path_of(factory: Factory, scope: str, owner: str) -> Path:
    if not _OWNER.match(str(owner or "")):
        raise ValueError(f"invalid {scope} id: {str(owner)[:60]!r}")
    if scope == "team":
        from kernel.teams import folder

        return folder(factory) / f"{owner}.vocab.json"
    return factory.projects_dir / owner / "vocabulary.json"


def read_layer(factory: Factory, scope: str, owner: str | None) -> dict[str, dict[str, Any]]:
    """The terms a team or a project redefined (an unreadable file reads as none: the shipped words stand)."""
    if not owner:
        return {}
    try:
        doc = read_json(path_of(factory, scope, owner), None)
    except (OSError, ValueError):
        return {}
    terms = doc.get("terms") if isinstance(doc, dict) else None
    return {k: v for k, v in (terms or {}).items() if isinstance(v, dict) and valid_id(k)}


def write_layer(factory: Factory, scope: str, owner: str, terms: dict[str, dict[str, Any]]) -> None:
    path = path_of(factory, scope, owner)
    if terms:
        write_json(path, {"schema": SCHEMA, "terms": terms})
    else:
        path.unlink(missing_ok=True)


# -- the word in force ----------------------------------------------------------------------------------------

def _pick(field: str, project: dict[str, Any], team: dict[str, Any], ship: dict[str, Any] | None) -> Any:
    for layer in (project, team):
        if layer.get(field) not in (None, ""):
            return layer[field]
    return (ship or {}).get(field)


def _hidden(project: dict[str, Any], team: dict[str, Any]) -> bool:
    return bool(project["hidden"] if "hidden" in project else team.get("hidden", False))


def _public(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    return {k: entry[k] for k in (*FIELDS, "by", "persona", "why", "since") if k in entry} if entry else None


def _row(tid: str, ship: dict[str, Any] | None, team: dict[str, Any], proj: dict[str, Any]) -> dict[str, Any]:
    forced = proj or team
    held = "project" if proj else "team" if team else "shipped"
    syn = list(dict.fromkeys([*((ship or {}).get("synonyms") or []), *(team.get("synonyms") or []),
                              *(proj.get("synonyms") or [])]))
    return {"id": tid, "type": tid.split(":")[0], "shipped": ship, "team": _public(team), "project": _public(proj),
            "scope": held, "label": _pick("label", proj, team, ship) or tid.split(":", 1)[1],
            "description": _pick("description", proj, team, ship) or "", "synonyms": syn,
            "hidden": _hidden(proj, team), "means": _pick("means", proj, team, None),
            "since": forced.get("since") if forced else None, "by": forced.get("by") if forced else None,
            "why": forced.get("why") if forced else None}


def effective(factory: Factory, project: Any = None, team_id: str | None = None) -> dict[str, Any]:
    """Every term as it reads here: the shipped meaning, the team's, the project's and which one is in force.
    ``project`` gives its team; else ``team_id`` names one; with neither, the shipped words alone."""
    from kernel import teams

    tid = team_id or (teams.team_of(factory, project) if project is not None else None)
    team = read_layer(factory, "team", tid)
    proj = read_layer(factory, "project", project.pid if project is not None else None)
    ship = _shipped()
    ids = [*ship, *sorted(k for k in {*team, *proj} if k not in ship)]
    rows = {t: _row(t, ship.get(t), team.get(t) or {}, proj.get(t) or {}) for t in ids}
    for row in rows.values():       # another word for a kind is a synonym of that kind
        target = rows.get(str(row["means"] or ""))
        if row["type"] == "custom" and target is not None and not row["hidden"]:
            target["synonyms"] = list(dict.fromkeys([*target["synonyms"], row["label"], *row["synonyms"]]))
    return {"team": tid, "project": project.pid if project is not None else None, "terms": rows, "order": ids}


def context(factory: Factory, project: Any = None, projects: list[Any] | None = None) -> dict[str, Any]:
    """The overlay for a page: a project's own; across projects, the team they all share, else the shipped words."""
    from kernel import teams

    if project is not None:
        return effective(factory, project)
    shared = {teams.team_of(factory, p) for p in projects or [] if p.pid != FACTORY_PID}     # its own are in no team
    return effective(factory, None, next(iter(shared)) if len(shared) == 1 else None)


def label(eff: dict[str, Any], term: str) -> str:
    row = eff["terms"].get(term)
    return str(row["label"]) if row else term.split(":", 1)[-1].replace("_", " ")


def differs(eff: dict[str, Any]) -> list[dict[str, Any]]:
    """The terms that do not read as shipped."""
    return [r for r in eff["terms"].values() if r["scope"] != "shipped"]


def compact(eff: dict[str, Any]) -> dict[str, Any]:
    """What the page needs of the overlay: each term's word, its meaning, where it comes from and since when."""
    return {"team": eff["team"], "project": eff["project"], "terms": {
        t: {"label": r["label"], "description": r["description"], "scope": r["scope"], "hidden": r["hidden"],
            "synonyms": r["synonyms"], "means": r["means"], "since": r["since"],
            "shipped": (r["shipped"] or {}).get("label")}
        for t, r in eff["terms"].items() if r["type"] == "custom" or r["scope"] != "shipped"
        or r["type"] == "kind"}}


# -- reading through the overlay ------------------------------------------------------------------------------

def relabel(view: dict[str, Any], eff: dict[str, Any]) -> dict[str, Any]:
    """The Knowledge graph's legend and relations in the words in force, a hidden kind left out of the legend, its
    nodes and the edges that touch them. The stored records are not changed: only how the view says them."""
    hidden = {t[5:] for t, r in eff["terms"].items() if t.startswith("kind:") and r["hidden"]}
    for prefix, key in (("kind", "kinds"), ("rel", "relations")):
        for item in view.get(key) or []:
            row = eff["terms"].get(f"{prefix}:{item['id']}")
            if row:
                item.update(label=row["label"], scope=row["scope"], term=row["id"])
    if hidden:
        _drop(view, hidden)
    view["vocabulary"] = {"team": eff["team"], "project": eff["project"], "changed": len(differs(eff)),
                          "hidden_kinds": sorted(hidden)}
    return view


def _drop(view: dict[str, Any], hidden: set[str]) -> None:
    """Take hidden kinds out of the legend, and their nodes and the edges that touch them out of the view."""
    gone = {n["id"] for n in view.get("nodes") or [] if n.get("kind") in hidden}
    view["kinds"] = [k for k in view.get("kinds") or [] if k["id"] not in hidden]
    view["nodes"] = [n for n in view.get("nodes") or [] if n["id"] not in gone]
    view["edges"] = [e for e in view.get("edges") or [] if e["from"] not in gone and e["to"] not in gone]


def match(eff: dict[str, Any], text: str) -> list[str]:
    """The terms a question names, by their word in force, their shipped word or a synonym (whole words)."""
    said = f" {_words(text)} "
    found = []
    for t, r in eff["terms"].items():
        names = {_words(r["label"]), _words((r["shipped"] or {}).get("label")), *(_words(s) for s in r["synonyms"])}
        if any(n and f" {n} " in said for n in names):
            found.append(t)
    return found


def _words(text: Any) -> str:
    return " ".join(norm(w) for w in re.findall(r"[a-z0-9][a-z0-9'-]*", str(text or "").lower()))
