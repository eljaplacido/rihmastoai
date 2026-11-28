"""Changing the words: a preview, a signed change with its reason, the record of what each term meant, and Undo
(D-0027, FR-TM2; the overlay itself is kernel/vocab.py).

Who may: a team's terms, IT (tech admins); a project's own, IT or the project's owner. A person working alone holds
every role, so there is no approval step: the change applies at once, after a preview, and an Undo gives the earlier
reading back exactly. Every change is in the ledger of the scope it is made in (the factory's for a team, the
project's for a project) with the term, what it was before, what it is, who, as which persona, why and since when.
Undo takes the newest change not yet undone off, in that scope, and puts its earlier entry back (the undone change
stays in the record).
Nothing here touches a stored record: a redefinition changes how records are read and labelled.
"""

from __future__ import annotations

from typing import Any

from kernel import teams, vocab
from kernel import teams_guard as guard
from kernel.canon import DecisionRefused
from kernel.enforcement import count
from kernel.learn import FACTORY_PID, factory_project
from kernel.people import is_person
from kernel.store import Factory, Project, slugify

SET_KIND, UNDONE_KIND = "vocab_set", "vocab_undone"
SETTERS = {"team": ("it",), "project": ("it", "business_owner", "product_owner")}
ALL_SETTERS = tuple(dict.fromkeys(p for v in SETTERS.values() for p in v))
MAX_LABEL, MAX_TEXT, MAX_SYNONYMS = 60, 400, 12
VIEWS = {"kind": ["the Knowledge graph's labels and legend", "the glossary's words",
                  "Ask Rihma's answers and map search"],
         "rel": ["the Knowledge graph's relation labels", "Ask Rihma's answers"],
         "attr": ["Ask Rihma's answers"], "custom": ["Ask Rihma's map search and answers"]}


def check_who(scope: str, person: str, persona: str) -> None:
    if scope not in vocab.SCOPES:
        raise ValueError("a vocabulary is a team's or a project's")
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a change of words is signed by a named person")
    guard.require_persona(persona, SETTERS[scope], f"change a {scope}'s words",
                          "IT" if scope == "team" else "IT or the project's owner")


def _store(factory: Factory, scope: str, owner: str) -> Any:
    return factory_project(factory) if scope == "team" else factory.project(owner)


def _key(scope: str, owner: str) -> str:
    return f"vocab:{scope}:{owner}"


# -- reading what was asked ----------------------------------------------------------------------------------

def _text(value: Any, limit: int, what: str) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if len(text) > limit or any(c in text for c in "<>"):
        raise ValueError(f"{what} is plain text of at most {limit} characters")
    return text


def _synonyms(raw: Any) -> list[str] | None:
    items = [] if raw is None else [raw] if isinstance(raw, str) else list(raw)
    syn = [_text(s, MAX_LABEL, "a synonym") for s in items]
    return list(dict.fromkeys(s for s in syn if s))[:MAX_SYNONYMS] or None


def _means(means: Any) -> Any:
    if means is not None and not (str(means).startswith("kind:") and str(means) in vocab.shipped()):
        raise ValueError("a custom term means one kind of record: kind:<id>, as the ontology names it")
    return means


def _fields(fields: dict[str, Any]) -> dict[str, Any]:
    """The change as asked: a value sets a field, None gives that field back to the layer below it."""
    unknown = set(fields) - set(vocab.FIELDS)
    if unknown:
        raise ValueError(f"a term has {', '.join(vocab.FIELDS)}; not {sorted(unknown)[0]}")
    out: dict[str, Any] = {}
    for name, limit in (("label", MAX_LABEL), ("description", MAX_TEXT)):
        if name in fields:
            out[name] = _text(fields[name], limit, name) or None
    if "synonyms" in fields:
        out["synonyms"] = _synonyms(fields["synonyms"])
    if "hidden" in fields:
        out["hidden"] = None if fields["hidden"] is None else bool(fields["hidden"])
    if "means" in fields:
        out["means"] = _means(fields["means"])
    return out


def _term_id(term: Any, fields: dict[str, Any], layer: dict[str, Any]) -> str:
    """The term changed: a shipped one, one this layer made, or a new custom one named by its label."""
    tid = str(term or "")
    if not tid:
        label = fields.get("label")
        if not label or not fields.get("means"):
            raise ValueError("name the term to change, or give a custom term a label and the kind it means")
        tid = f"custom:{slugify(label, 40).replace('-', '_')}"
        if tid in vocab.shipped():
            raise ValueError("that custom term is already named")
    elif not (tid in vocab.shipped() or tid in layer):
        raise ValueError(f"{tid!r} is not a term: kind:<id>, rel:<id>, attr:<key>, or a custom term made here")
    if tid.startswith("custom:") and not (fields.get("means") or (layer.get(tid) or {}).get("means")):
        raise ValueError("a custom term means one kind of record: say which")
    return tid


def _after(before: dict[str, Any] | None, change: dict[str, Any], reset: bool) -> dict[str, Any] | None:
    if reset:
        return None
    entry = dict(before or {})
    for name, value in change.items():
        if value is None:
            entry.pop(name, None)
        else:
            entry[name] = value
    return entry if any(f in entry for f in vocab.FIELDS) else None


def _owner_ok(factory: Factory, scope: str, owner: str) -> None:
    if scope == "team":
        teams.read(factory, owner)           # a team that exists
    elif owner == FACTORY_PID:
        raise ValueError("Rihmasto's own records use its own words: a project's or a team's words are set for those")
    else:
        factory.project(owner)


# -- preview -------------------------------------------------------------------------------------------------

def _reach(factory: Factory, scope: str, owner: str, tid: str) -> tuple[list[Project], list[Project]]:
    """The projects whose reading changes, and those that keep their own word for this term."""
    if scope == "project":
        return [factory.project(owner)], []
    mine = teams.projects_of(factory, owner)
    keeps = [p for p in mine if tid in vocab.read_layer(factory, "project", p.pid)]
    return [p for p in mine if p not in keeps], keeps


def _count_in(g: Any, pid: str, tid: str, kind: str | None) -> tuple[set[str], int]:
    """The records and nodes of one project's graph that a term names."""
    if tid.startswith("rel:") and not kind:
        edges = [e for e in g.edges if e.get("rel") == tid[4:]]
        return ({f"{pid}:{e['from']}>{e['to']}" for e in edges},
                len({x for e in edges for x in (e["from"], e["to"])}))
    held = [n for n in g.nodes.values() if (n.get("kind") == kind[5:] if kind else tid[5:] in n)]
    return {f"{pid}:{n.get('record') or n['id']}" for n in held}, len(held)


def _counts(projects: list[Project], tid: str, means: str | None) -> tuple[int, int]:
    """(records, nodes) the term names in these projects: the records behind its nodes, and the nodes."""
    from kernel import graph

    kind = (means or tid) if (means or tid).startswith("kind:") else None
    records: set[str] = set()
    nodes = 0
    for p in projects:
        try:
            found, n = _count_in(graph.build(p), p.pid, tid, kind)
        except (OSError, ValueError, KeyError):
            continue
        records |= found
        nodes += n
    return len(records), nodes


def preview(factory: Factory, scope: str, owner: str, *, term: Any = None, fields: dict[str, Any] | None = None,
            reset: bool = False) -> dict[str, Any]:
    """How the change would read, and how many records, nodes and views read differently. It records nothing."""
    _owner_ok(factory, scope, owner)
    layer = vocab.read_layer(factory, scope, owner)
    change = _fields(fields or {})
    tid = _term_id(term, change, layer)
    before = layer.get(tid)
    after = _after(before, change, reset)
    sim = {**layer, tid: after} if after else {k: v for k, v in layer.items() if k != tid}
    now, then = _said(factory, scope, owner, tid, layer), _said(factory, scope, owner, tid, sim)
    reach, keeps = _reach(factory, scope, owner, tid)
    records, nodes = _counts(reach, tid, (after or before or {}).get("means"))
    row_type = tid.split(":")[0]
    diffs = [f for f in ("label", "description", "synonyms", "hidden") if now[f] != then[f]]
    warned, more = _warnings(reach, tid, diffs, then)
    lines = _lines(now, then, diffs) + _reach_lines(diffs, (records, nodes, len(VIEWS[row_type])), keeps) + more
    return {"term": tid, "warnings": warned, "scope": scope, "owner": owner, "before": now, "after": then,
            "lines": lines, "records": records if diffs else 0, "nodes": nodes if diffs else 0,
            "views": list(VIEWS[row_type]) if diffs else [], "keeps": [p.pid for p in keeps],
            "changes": [{"term": tid, "field": f, "from": now[f], "to": then[f]} for f in diffs]}


def _warnings(reach: list[Project], tid: str, diffs: list[str], then: dict[str, Any]) -> tuple[int, list[str]]:
    """The warnings on the records a hidden kind would leave out of the graph, in the projects it reaches, and the
    line that says so (nothing for a change that hides no kind)."""
    from kernel import graph_hide

    if "hidden" not in diffs or not then["hidden"] or not tid.startswith("kind:"):
        return 0, []
    held = graph_hide.warnings_on(reach, {tid[5:]})
    return held, ([f"{count(held, 'warning')} still hold on {then['label']} records: they are left out of the graph, "
                   "which says how many, so none is lost."] if held else [])


def _reach_lines(diffs: list[str], counts: tuple[int, int, int], keeps: list[Project]) -> list[str]:
    out = []
    if diffs:
        records, nodes, views = counts
        out.append(f"{count(records, 'record')}, {count(nodes, 'node')} and {count(views, 'view')} read "
                   "differently; nothing stored is rewritten.")
    if keeps:
        out.append("Projects that keep their own word for it: "
                   + ", ".join(p.meta.get("title") or p.pid for p in keeps) + ".")
    return out


def _lines(now: dict[str, Any], then: dict[str, Any], diffs: list[str]) -> list[str]:
    if not diffs:
        return [f"{now['label']}: nothing changes."]
    out = []
    if "label" in diffs:
        out.append(f"{now['label']} is read as {then['label']}.")
    if "description" in diffs:
        out.append(f"{then['label']} gets a new description.")
    if "synonyms" in diffs:
        new = [s for s in then["synonyms"] if s not in now["synonyms"]]
        out.append(f"Ask Rihma also finds {then['label']} as " + (", ".join(new) if new else "fewer words") + ".")
    if "hidden" in diffs:
        out.append(f"{then['label']} is " + ("hidden from the views." if then["hidden"] else "shown again."))
    return out


def _said(factory: Factory, scope: str, owner: str, tid: str, layer: dict[str, Any]) -> dict[str, Any]:
    """The term as it would read in the scope, with this layer standing as given."""
    ship = vocab.shipped().get(tid)
    team = layer if scope == "team" else vocab.read_layer(factory, "team", owner if scope == "team" else
                                                           teams.team_of(factory, factory.project(owner)))
    proj = layer if scope == "project" else {}
    row = vocab._row(tid, ship, team.get(tid) or {}, proj.get(tid) or {})
    return {"label": row["label"], "description": row["description"], "hidden": row["hidden"], "scope": row["scope"],
            "synonyms": row["synonyms"]}


# -- the change, the record and Undo --------------------------------------------------------------------------

def set_term(factory: Factory, scope: str, owner: str, *, term: Any = None, fields: dict[str, Any] | None = None,
             reset: bool = False, person: str, persona: str, reason: str = "") -> dict[str, Any]:
    """Give a term another word here, signed, recorded with the earlier entry. A project's override of a team term
    leaves the team's alone."""
    check_who(scope, person, persona)
    seen = preview(factory, scope, owner, term=term, fields=fields, reset=reset)
    if not seen["changes"]:
        return seen | {"saved": False}
    layer = vocab.read_layer(factory, scope, owner)
    tid, before = seen["term"], layer.get(seen["term"])
    after = _after(before, _fields(fields or {}), reset)
    if after is not None:
        after = {**after, "by": person, "persona": persona, "why": str(reason or "")[:300],
                 "since": factory.clock.stamp()}
    layer = {k: v for k, v in layer.items() if k != tid} | ({tid: after} if after else {})
    vocab.write_layer(factory, scope, owner, layer)
    _store(factory, scope, owner).log(SET_KIND, {"key": _key(scope, owner), "scope": scope, "owner": owner,
                                                 "term": tid, "before": before, "after": after, "by": person,
                                                 "persona": persona, "reason": str(reason or "")[:300]})
    return seen | {"saved": True}


def _stack(factory: Factory, scope: str, owner: str) -> list[dict[str, Any]]:
    key = _key(scope, owner)
    stack: list[dict[str, Any]] = []
    for r in _store(factory, scope, owner).ledger().of_kind(SET_KIND, UNDONE_KIND):
        e = r["event"]
        p = e.get("payload") or {}
        if p.get("key") != key:
            continue
        if e["kind"] == UNDONE_KIND:
            if stack:
                stack.pop()
        else:
            stack.append({**p, "at": e.get("at")})
    return stack


def undo(factory: Factory, scope: str, owner: str, *, person: str, persona: str) -> dict[str, Any]:
    """Put back the reading the newest change here replaced, exactly (its earlier entry, with who and since when)."""
    check_who(scope, person, persona)
    _owner_ok(factory, scope, owner)
    stack = _stack(factory, scope, owner)
    if not stack:
        raise ValueError("there is nothing to undo here: no change of words was made, or all were undone")
    last = stack[-1]
    layer = {k: v for k, v in vocab.read_layer(factory, scope, owner).items() if k != last["term"]}
    if last["before"] is not None:
        layer[last["term"]] = last["before"]
    vocab.write_layer(factory, scope, owner, layer)
    _store(factory, scope, owner).log(UNDONE_KIND, {"key": _key(scope, owner), "scope": scope, "owner": owner,
                                                    "term": last["term"], "by": person, "persona": persona})
    return {"undone": last["term"], "scope": scope, "owner": owner,
            "lines": [f"{last['term']} reads as it did before; the change stays in the record."]}


def definitions(factory: Factory, project: Project | None, term: str,
                team_id: str | None = None) -> list[dict[str, Any]]:
    """What the term meant and since when, newest first: every definition in the team's record and the project's,
    each with who, why and whether it was undone."""
    out: list[dict[str, Any]] = []
    scopes = [("team", team_id or (teams.team_of(factory, project) if project else None)),
              ("project", project.pid if project else None)]
    for scope, owner in scopes:
        if not owner:
            continue
        open_: list[dict[str, Any]] = []
        for r in _store(factory, scope, owner).ledger().of_kind(SET_KIND, UNDONE_KIND):
            e, p = r["event"], r["event"].get("payload") or {}
            if p.get("key") != _key(scope, owner):
                continue
            if e["kind"] == UNDONE_KIND:
                if open_:
                    open_.pop()["undone"] = True
            elif p.get("term") == term:
                open_.append(row := {"scope": scope, "owner": owner, "since": e.get("at"), "by": p.get("by"),
                                     "why": p.get("reason"), "label": (p.get("after") or {}).get("label"),
                                     "description": (p.get("after") or {}).get("description"), "undone": False})
                out.append(row)
            else:
                open_.append({})                  # another term's change: undo takes it, not this term's
    return sorted(out[::-1], key=lambda x: str(x["since"]), reverse=True)    # newest first; ledger order within a time


def history(factory: Factory, scope: str, owner: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = [{"at": e["at"], **e["payload"], "undone": False} for e in
            ({"at": r["event"].get("at"), "payload": r["event"].get("payload") or {}}
             for r in _store(factory, scope, owner).ledger().of_kind(SET_KIND))
            if e["payload"].get("key") == _key(scope, owner)]
    return rows[-limit:][::-1]
