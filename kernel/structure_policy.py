"""Rihmasto's structure, per project: Off, Advise or Enforce for each of its own conventions (FR-STR1).

The owner (2026-11-26): "how much rihmasto is able / trying to ingest existing structures of project versus are
the tasks highlighted about enforcing rihmasto's own structure? ... Ofc I can enforce those where I should if
beneficial, but not blindsided".

Rihmasto keeps conventions of its own: tests trace to requirements, requirements have given/when/then criteria,
tasks link to criteria, decisions are recorded, API contracts are declared, commits are kept tidy, and the
repository has the layout its checks look for. A project brought in with a structure of its own (adopted or
attached) keeps that structure: Rihmasto takes it as given. For each convention a person chooses a **level**:

- ``off``: what the convention finds is hidden, with a count and why;
- ``advise`` (the default for a project with its own structure): shown folded as a suggestion, never counted
  against the project, no card;
- ``enforce`` (the default for a project Rihmasto builds): counted as a decision to make, one card per convention
  in the Inbox (kernel/structure_cards.py), and named at the repo gate.

The platform sets the default per kind of project (its own structure, or built by Rihmasto); a project may set its
own; every row says which scope its level comes from. Every change is previewed first, signed by a person with
the reason they give, and recorded in that scope's ledger (``structure_set``). Nothing is written to the
project's repository. The Alignment view (kernel/alignment_records.py) and the Assessment follow the levels here.
"""

from __future__ import annotations

from typing import Any

from kernel.canon import DecisionRefused
from kernel.enforcement import count as _n
from kernel.learn import factory_project
from kernel.people import is_person

LEVELS = ("off", "advise", "enforce")
LEVEL_MEANING = {"off": "hidden, with a count and why",
                 "advise": "shown folded as a suggestion; never counted against the project; no card",
                 "enforce": "counted as a decision to make, one card in the Inbox, named at the repo gate"}
LEVEL_WORD = {"off": "Off", "advise": "Advise", "enforce": "Enforce"}
INHERIT = "inherit"
KINDS = ("own", "built")
KIND_MEANING = {"own": "projects brought in with a structure of their own (adopted or attached)",
                "built": "projects Rihmasto builds itself"}
DEFAULT = {"own": "advise", "built": "enforce"}
SETTERS = ("business_owner", "product_owner", "developer", "it")
FILE = "structure.json"
EVENT = "structure_set"

# Each convention: its name, what it asks of a project, and what of the project follows its level here.
CONVENTION: dict[str, dict[str, str]] = {
    "test_trace": {"label": "Tests trace to requirements",
                   "asks": "every test names the requirement or criterion it checks (test_<criterion id>_...)",
                   "follows": "the Alignment's Tests trace links and its gaps: tests that trace to no requirement, "
                              "requirements no test traces to"},
    "criteria": {"label": "Requirements have given/when/then criteria",
                 "asks": "each requirement has acceptance criteria written as given, when, then, each observable",
                 "follows": "the Alignment's gaps: criteria not testable as written, requirements given no criterion"},
    "task_links": {"label": "Tasks link to criteria",
                   "asks": "each task names the criteria it serves",
                   "follows": "the tasks Rihmasto builds; an imported task list is taken as it is"},
    "decisions": {"label": "Decisions recorded",
                  "asks": "decisions are kept as records (ADRs or the decision ledger)",
                  "follows": "the Assessment's audit-trail finding"},
    "api_contracts": {"label": "API contracts declared",
                      "asks": "each API the project offers has a contract file (OpenAPI, GraphQL, protobuf)",
                      "follows": "the API contracts Rihmasto builds; contracts found in the repository are kept "
                                 "as references"},
    "commit_hygiene": {"label": "Commit hygiene",
                       "asks": "commits name their task or criterion and stay small",
                       "follows": "the commits Rihmasto's own lanes make"},
    "layout": {"label": "Repository layout checks",
               "asks": "a README, code owners and the files Rihmasto's checks look for",
               "follows": "the Assessment's README and code-owners findings"},
}
CONVENTIONS = tuple(CONVENTION)
GAP_CONVENTION = {"no_requirement": "test_trace", "no_test": "test_trace", "untestable": "criteria",
                  "no_criteria": "criteria"}
ASSESS_CONVENTION = {"maintenance.docs": "layout", "maintenance.ownership": "layout",
                     "compliance.audit_trail": "decisions"}
TAKE_IN = ("requirements", "criteria", "tasks", "decisions", "contracts")


def kind_of(project: Any) -> str:
    return "own" if (project.meta.get("source_kind") in ("adopted", "attached")) else "built"


def _doc(store: Any) -> dict[str, Any]:
    doc = store.read(FILE, {}) if store is not None else {}
    return doc if isinstance(doc, dict) else {}


def platform_doc(factory: Any) -> dict[str, Any]:
    return _doc(factory_project(factory, create=False))      # a reader never creates the factory's own records


def project_doc(project: Any) -> dict[str, Any]:
    return _doc(project)


def _valid(value: Any) -> str | None:
    return value if value in LEVELS else None


def row(factory: Any, project: Any, conv: str, *, kind: str | None = None) -> dict[str, Any]:
    """One convention's level in force for a project (or the platform's for a kind), with where it comes from:
    the project's own, the platform's or Rihmasto's default, and the platform's level beside it."""
    kind = kind or (kind_of(project) if project is not None else "own")
    plat = platform_doc(factory)
    p_level = _valid(((plat.get("levels") or {}).get(kind) or {}).get(conv))
    platform = {"level": p_level or DEFAULT[kind], "scope": "platform" if p_level else "default",
                "why": ((plat.get("reasons") or {}).get(kind) or {}).get(conv)}
    own = project_doc(project) if project is not None else {}
    o_level = _valid((own.get("levels") or {}).get(conv))
    level, scope, why = ((o_level, "project", (own.get("reasons") or {}).get(conv)) if o_level
                         else (platform["level"], platform["scope"], platform["why"]))
    c = CONVENTION[conv]
    return {"id": conv, "label": c["label"], "asks": c["asks"], "follows": c["follows"], "level": level,
            "scope": scope, "why": why, "platform": platform, "own": o_level, "kind": kind}


def levels(factory: Any, project: Any) -> dict[str, str]:
    return {conv: row(factory, project, conv)["level"] for conv in CONVENTIONS}


# -- what follows the levels ------------------------------------------------------------------------------

def convention_of(item: dict[str, Any]) -> str | None:
    """The convention an Alignment item is about: a trace link or a gap of a convention; None for what Rihmasto
    takes in from the project's own files (requirements, criteria, tasks, decisions, API contracts) and for facts
    about them (a spec older than its code, CI that does not run the tests)."""
    if item.get("group") == "trace":
        return "test_trace"
    if item.get("group") == "gaps":
        return GAP_CONVENTION.get(item.get("kind") or "")
    return None


def _alignment_items(project: Any) -> list[dict[str, Any]]:
    from kernel import alignment_records as ar

    found = project.read(ar.SCAN) or {}
    decided = ar.decisions(project)
    items = (found.get("proposal") or {}).get("items", [])
    return [dict(i, status=ar.status_of(i, decided.get(i["id"]))) for i in items]


def _assessment_failed(project: Any) -> list[dict[str, Any]]:
    from kernel import assess

    if not assess.history(project):
        return []
    try:
        latest = assess.load(project)
    except LookupError:
        return []
    return [c for c in latest.get("checks") or [] if c.get("verdict") == "failed"]


def findings(project: Any) -> dict[str, list[dict[str, Any]]]:
    """What each convention finds open on a project now: Alignment items not decided, the Assessment's findings."""
    out: dict[str, list[dict[str, Any]]] = {c: [] for c in CONVENTIONS}
    for i in _alignment_items(project):
        conv = convention_of(i)
        if conv and i["status"] in ("open", "changed"):
            out[conv].append({"source": "alignment", "id": i["id"], "title": i["title"], "group": i["group"]})
    for c in _assessment_failed(project):
        conv = ASSESS_CONVENTION.get(c.get("key") or "")
        if conv:
            out[conv].append({"source": "assessment", "id": c.get("id"), "title": c.get("title"),
                              "group": "assessment"})
    return out


def _hidden_why(r: dict[str, Any]) -> str:
    by = (r.get("why") or {}) if isinstance(r.get("why"), dict) else {}
    who = f" by {by['person']}" if by.get("person") else ""
    reason = f": {by['reason']}" if by.get("reason") else ""
    plat = {"own": "for all projects with their own structure", "built": "for all projects Rihmasto builds"}
    where = {"project": "for this project", "platform": plat[r.get("kind") or "own"],
             "default": "by Rihmasto's default"}
    return f"{r['label']} is Off {where[r['scope']]}{who}{reason}"


def follow_alignment(factory: Any, project: Any, view: dict[str, Any]) -> dict[str, Any]:
    """The Alignment as the levels have it: an item of an Off convention leaves its group (a count stays, with
    why); an Advise one is folded as a suggestion and not counted; an Enforce one counts as a decision to make.
    ``policy`` says how many items take in the project's own structure, how many are Rihmasto's conventions, and
    how many are left to decide."""
    from kernel import alignment_triage as kalign_triage
    from kernel import structure_sides  # what each item counts as, how old its source (FR-STR2)

    if not view.get("applies") or not view.get("scanned"):
        return view
    rows = {c: row(factory, project, c) for c in CONVENTIONS}
    older = structure_sides.annotate(project, view)
    found = sum(len(g["items"]) for g in view["groups"])          # everything the scan found, decided or not
    split = {"take_in": 0, "conform": 0, "own": 0}
    by_level = {lvl: 0 for lvl in LEVELS}
    for g in view["groups"]:
        _follow_group(g, rows, split, by_level)
    structure_sides.headline(view, rows["test_trace"]["level"])
    shown = [i for g in view["groups"] for i in g["items"] if not i.get("folded")]
    view["status"] = dict(view.get("status") or {}, **{s: sum(1 for i in shown if i["status"] == s)
                                                       for s in ("open", "changed")})   # what is left to decide
    kalign_triage.recount(project, view)    # the head says the same number (FR-ORG2)
    to_decide = split["take_in"] + split["own"] + by_level["enforce"]
    view["policy"] = {"split": split, "by_level": by_level, "to_decide": to_decide, "found": found,
                      "open": sum(split.values()), "older": older, "rows": list(rows.values()),
                      "kind": kind_of(project),
                      "line": policy_line(split, by_level, to_decide, found=found, older=older)}
    return view


def _live(i: dict[str, Any]) -> bool:
    return i["status"] in ("open", "changed")


def _follow_group(g: dict[str, Any], rows: dict[str, dict[str, Any]], split: dict[str, int],
                  by_level: dict[str, int]) -> None:
    """One group as the levels have it, counting each open item where it belongs."""
    kept, hidden = [], []
    for i in g["items"]:
        conv = convention_of(i)
        if conv is None:
            split["take_in" if g["id"] in TAKE_IN else "own"] += _live(i)
            kept.append(i)
            continue
        lvl = rows[conv]["level"]
        split["conform"] += _live(i)
        by_level[lvl] += _live(i)
        if lvl == "off":
            hidden.append(conv)
        else:
            kept.append(dict(i, convention=conv, level=lvl, folded=lvl == "advise"))
    g["items"] = kept
    g["open"] = sum(1 for i in kept if _live(i) and not i.get("folded"))
    g["suggested"] = sum(1 for i in kept if _live(i) and i.get("folded"))
    g["hidden"] = ({"n": len(hidden), "why": "; ".join(_hidden_why(rows[c]) for c in dict.fromkeys(hidden))}
                   if hidden else None)


def policy_line(split: dict[str, int], by_level: dict[str, int], to_decide: int, *, found: int | None = None,
                older: int = 0) -> str:
    live = sum(split.values())
    found = live if found is None else found
    parts = [f"{split['take_in']} take{'s' if split['take_in'] == 1 else ''} in the project's own specs, tasks, "
             "decisions and contracts"]
    if split["own"]:
        parts.append(f"{split['own']} {'is a fact' if split['own'] == 1 else 'are facts'} about its own files")
    conv = [f"{by_level[lvl]} {LEVEL_WORD[lvl].lower()}" + {"advise": "d (suggestions, not counted)",
                                                           "off": " (hidden)", "enforce": "d"}[lvl]
            for lvl in ("enforce", "advise", "off") if by_level[lvl]]
    parts.append(f"{split['conform']} {'is' if split['conform'] == 1 else 'are'} Rihmasto's own conventions"
                 + (f": {', '.join(conv)}" if conv else ""))
    verb = "is" if to_decide == 1 else "are"
    state = "all open" if live == found else f"{found - live} decided and {live} open"
    aged = (f" {older} of the project's own {'comes' if older == 1 else 'come'} from files older than the newest "
            "code: check they still hold." if older else "")
    return (f"Of {_n(found, 'item')} found, {state}: " + "; ".join(parts) + f". {to_decide} {verb} yours to decide."
            + aged)


def _reordered(priority: list[dict[str, Any]], level_of: dict[str, str]) -> list[dict[str, Any]]:
    """The suggested order without an Off convention's findings, and with an Advise one's at its end, marked."""
    def lvl(p: dict[str, Any]) -> str:
        return level_of.get(str(p.get("id")), "enforce")
    return ([p for p in priority if lvl(p) == "enforce"]
            + [dict(p, advised=True) for p in priority if lvl(p) == "advise"])


def _hidden_in(rows: dict[str, dict[str, Any]], checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per convention set Off, how many findings it hides, and who set it, why and for whom (FR-STR2)."""
    def n(conv: str) -> int:
        return sum(1 for x in checks if (x.get("structure") or {}).get("convention") == conv)
    return [{"convention": c, "label": rows[c]["label"], "n": n(c), "why": _hidden_why(rows[c])} for c in CONVENTIONS
            if rows[c]["level"] == "off" and n(c)]


def follow_assessment(factory: Any, project: Any, view: dict[str, Any]) -> dict[str, Any]:
    """The Assessment as the levels have it: a finding of one of Rihmasto's conventions says its level; an Off
    one leaves the suggested order, an Advise one goes to its end, marked as a suggestion."""
    latest = view.get("latest")
    if not isinstance(latest, dict):
        return view
    rows = {c: row(factory, project, c) for c in CONVENTIONS}
    level_of: dict[str, str] = {}
    counts = {lvl: 0 for lvl in LEVELS}
    for c in latest.get("checks") or []:
        conv = ASSESS_CONVENTION.get(c.get("key") or "")
        if conv and c.get("verdict") == "failed":
            r = rows[conv]
            c["structure"] = {"convention": conv, "label": r["label"], "level": r["level"], "scope": r["scope"]}
            counts[r["level"]] += 1
            level_of[str(c.get("id"))] = r["level"]
    view["priority"] = _reordered(view.get("priority") or [], level_of)
    view["structure"] = {"counts": counts, "hidden": _hidden_in(rows, latest.get("checks") or []),
                         "why": "findings about Rihmasto's own conventions follow this project's structure levels "
                                "(Alignment > Rihmasto's structure)"}
    return view


def gate_part(factory: Any, project: Any) -> dict[str, Any] | None:
    """What the repo gate names of Rihmasto's structure: the enforced conventions with something open."""
    found = findings(project)
    rows = [{"convention": c, "label": CONVENTION[c]["label"], "open": len(found[c])}
            for c, lvl in levels(factory, project).items() if lvl == "enforce" and found[c]]
    if not rows:
        return None
    return {"enforced": rows, "note": "Rihmasto's structure, enforced for this project: "
            + "; ".join(f"{r['label']} ({r['open']} open)" for r in rows)}


# -- the preview and the change ---------------------------------------------------------------------------

def check_setter(person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person; Rihmasto's structure is set by a named person")
    if persona not in SETTERS:
        raise DecisionRefused(f"a {persona} may not set Rihmasto's structure; {', '.join(SETTERS)} may")


def checked(wanted: Any) -> dict[str, str]:
    if not isinstance(wanted, dict) or not wanted:
        raise ValueError("levels is an object: {convention: off, advise, enforce or inherit}")
    for conv, lvl in wanted.items():
        if conv not in CONVENTION:
            raise ValueError(f"a convention is one of {', '.join(CONVENTIONS)}, got {conv!r}")
        if lvl not in (*LEVELS, INHERIT):
            raise ValueError(f"a level is one of {', '.join((*LEVELS, INHERIT))}, got {lvl!r}")
    return dict(wanted)


def _effect(before: str, after: str, n: int) -> str:
    things = _n(n, "finding")
    if n == 0:
        return "nothing on it now follows this convention"
    if after == "off":
        return f"{things} leave the views; a count stays, with why"
    if after == "advise":
        return f"{things} {'is' if n == 1 else 'are'} shown as suggestions, not counted" + (
            "; the Inbox card is withdrawn" if before == "enforce" else "")
    return f"{things} become decisions to make, with one card in the Inbox, named at the repo gate"


def _following(factory: Any, kind: str, conv: str) -> list[Any]:
    from kernel.learn import FACTORY_PID

    return [p for p in factory.projects() if p.pid != FACTORY_PID and kind_of(p) == kind
            and not _valid((project_doc(p).get("levels") or {}).get(conv))]


def preview(factory: Any, project: Any, levels_: Any, *, kind: str | None = None) -> dict[str, Any]:
    """What a change would do, before it is made: each convention's level from and to, and what moves on the
    project (or, for the platform, on every project of that kind that follows it). It records nothing."""
    wanted = checked(levels_)
    kind = kind_of(project) if project is not None else (kind or "own")
    if kind not in KINDS:
        raise ValueError(f"a kind of project is one of {', '.join(KINDS)}")
    plat = (platform_doc(factory).get("levels") or {}).get(kind) or {}
    seen = [x for conv, lvl in wanted.items() if (x := _one(factory, project, kind, plat, conv, lvl))]
    lines = [line for _, line in seen] or ["Nothing changes: that is how it is set now."]
    return {"scope": "project" if project is not None else "platform", "kind": kind,
            "changes": [c for c, _ in seen], "lines": lines,
            "repository": "nothing is written to the project's repository"}


def _one(factory: Any, project: Any, kind: str, plat: dict[str, Any], conv: str, lvl: str
         ) -> tuple[dict[str, Any], str] | None:
    """One convention's change and its line, or None when the level is set so already in that scope."""
    now = row(factory, project, conv, kind=None if project is not None else kind)
    after_set = None if lvl == INHERIT else lvl
    if (now["own"] if project is not None else _valid(plat.get(conv))) == after_set:
        return None
    if project is not None:
        to, n, who = after_set or now["platform"]["level"], len(findings(project)[conv]), "this project"
    else:
        projects = _following(factory, kind, conv)
        to, n = after_set or DEFAULT[kind], sum(len(findings(p)[conv]) for p in projects)
        who = f"{_n(len(projects), 'project')} that follow{'s' if len(projects) == 1 else ''} all projects"
    change = {"convention": conv, "label": now["label"], "from": now["level"], "to": to, "from_scope": now["scope"],
              "findings": n}
    if to == now["level"]:
        return change, (f"{now['label']}: stays {LEVEL_WORD[to]} for {who}, " + (
            "now as for all projects." if lvl == INHERIT else "now set as its own: it no longer follows a change "
                                                              "for all projects."))
    return change, (f"{now['label']}: {LEVEL_WORD[now['level']]} to {LEVEL_WORD[to]} for {who}"
                    + (" (back to all projects' level)" if lvl == INHERIT else "")
                    + f": {_effect(now['level'], to, n)}.")


def set_levels(factory: Any, project: Any, levels_: Any, *, person: str, persona: str, reason: str = "",
               kind: str | None = None) -> dict[str, Any]:
    """Set a project's own levels (``project``) or the platform's for a kind of project, signed with the person's
    reason and recorded in that scope's ledger; for a project, its Inbox cards follow (kernel/structure_cards.py)."""
    check_setter(person, persona)
    seen = preview(factory, project, levels_, kind=kind)
    said = " ".join(str(reason or "").split())[:300]
    if not seen["changes"]:
        return seen | {"changed": False, **describe(factory, project)}
    if not said:
        raise ValueError("give a reason: it is recorded with the change, for whoever reads it later")
    target = project if project is not None else factory_project(factory, create=True)
    doc = _doc(target)
    lv = doc.setdefault("levels", {})
    rs = doc.setdefault("reasons", {})
    if project is None:
        lv, rs = lv.setdefault(seen["kind"], {}), rs.setdefault(seen["kind"], {})
    at = factory.clock.stamp()
    for conv, lvl in checked(levels_).items():
        if lvl == INHERIT:
            lv.pop(conv, None)
            rs.pop(conv, None)
        else:
            lv[conv] = lvl
            rs[conv] = {"reason": said, "person": person, "persona": persona, "at": at}
    target.write(FILE, doc)
    target.log(EVENT, {"scope": seen["scope"], "kind": seen["kind"], "changes": seen["changes"],
                       "person": person, "persona": persona, "reason": said,
                       "note": "Rihmasto's structure levels; nothing written to the repository"})
    cards: dict[str, Any] = {}
    if project is not None:
        from kernel import structure_cards

        cards = structure_cards.sync(factory, project)
    return seen | {"changed": True, "cards": cards, **describe(factory, project)}


def history(factory: Any, project: Any = None, limit: int = 20) -> list[dict[str, Any]]:
    store = project if project is not None else factory_project(factory, create=False)
    if store is None:
        return []
    rows = [{"at": r["event"].get("at"), **r["event"]["payload"]} for r in store.ledger().of_kind(EVENT)]
    return rows[-limit:][::-1]


def describe(factory: Any, project: Any = None) -> dict[str, Any]:
    """The levels as a person reads them: each convention with its level, scope, the platform's level beside a
    project's own, the reason recorded, and what of the project it finds now."""
    meta = {"levels": [{"id": lvl, "word": LEVEL_WORD[lvl], "meaning": LEVEL_MEANING[lvl]} for lvl in LEVELS],
            "kinds": [{"id": k, "meaning": KIND_MEANING[k], "default": DEFAULT[k]} for k in KINDS],
            "setters": list(SETTERS)}
    if project is None:
        return {"scope": "platform", "project": None, "meta": meta, "history": history(factory),
                "kinds": {k: [row(factory, None, c, kind=k) for c in CONVENTIONS] for k in KINDS}}
    found = findings(project)
    rows = [row(factory, project, c) | {"found": len(found[c])} for c in CONVENTIONS]
    return {"scope": "project", "project": project.pid, "title": project.meta.get("title") or project.pid,
            "kind": kind_of(project), "kind_meaning": KIND_MEANING[kind_of(project)], "rows": rows, "meta": meta,
            "history": history(factory, project)}
