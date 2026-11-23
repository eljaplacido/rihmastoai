"""The way back: changes and feedback from any persona re-enter the factory (FR-I1, FR-I3, FR-A4).

`submit` opens a change card. `triage` classifies the change and names the stage it returns
to:

| Class | Returns to | Needs a business decision first |
|---|---|---|
| defect | 5, build: a regression criterion and a repair task | no: the requirement stands |
| change_request | 4, spec: an amendment | yes (FR-P4) |
| new_requirement | 1 to 2: the panel reads it, then a spec amendment | yes |
| infra_change | 7, the paved road: IT's card, then a dry run before adoption | IT decides (FR-Q2) |
| incident | 7, operation: rollback reflex, then a defect | no |
| question | 2, the canon's questions | no |

Applying a change amends the spec and recompiles the contract. Every approval resting on a
changed requirement becomes stale (FR-P5). A defect closes only with a regression check added,
which is its lesson (FR-K2).

A change a person rejected or deferred is never applied, whatever its class. A submitter's class
hint never skips the business decision: a hint that differs from what the rules (or the analyst)
read needs one, unless the submitter is a persona who decides change cards anyway (a business
owner or product owner). A developer's or anyone else's label is only a label. The one other
defect hint that stands is a person's product-defect ruling on a failing holdout (FR-H3-AC-2):
the defect `kernel/rulings.py` files for a ruling not yet carried out, in the name and persona of
the person who decided it and in the ruling's own words (`ruling_defect_text`). The amended spec
is compiled before anything is written, so a change the compiler refuses leaves the spec, the
contract and the approvals as they were. Holdout scenarios for the criteria a change withdraws or
restates are retired in the holdout custody, so none of them runs again (a restated one is
written anew before the next delivery).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from kernel.canon import CARD_DECIDERS, Canon
from kernel.compile import check_plan, retire_holdouts, to_contract, update_repo_contract
from kernel.intake import _ask_json
from kernel.people import PERSONAS, is_person
from kernel.spec import KINDS, render_spec_md
from kernel.store import Project, write_text

CLASSES = ("defect", "change_request", "new_requirement", "infra_change", "incident", "question")
WAY_BACK = {"defect": 5, "change_request": 4, "new_requirement": 2, "infra_change": 7, "incident": 7, "question": 2}
NEEDS_DECISION = {"change_request", "new_requirement"}
# Whose class hint stands even where it differs from the rules' or the analyst's reading: only the
# personas who decide a change card anyway, so a label never skips their decision (FR-P4).
HINT_TRUSTED = CARD_DECIDERS["change"]
AMENDS = ("defect", "change_request", "new_requirement")

_DEFECT = re.compile(r"\b(error|errors|crash|crashes|broken|bug|fails?|failing|wrong|500|exception|does ?n[o']t work|"
                     r"lost|missing data|virhe|ei toimi|kaatuu)\b", re.I)
_NEW = re.compile(r"\b(new feature|also need|we also want|add a new|another (screen|report|page)|uusi)\b", re.I)
_CHANGE = re.compile(r"\b(change|should be|instead|rename|rather|move|make it|prefer|muuta|pitäisi)\b", re.I)


def submit(project: Project, *, persona: str, person: str, text: str,
           kind_hint: str | None = None) -> dict[str, Any]:
    """Anyone in the delivery square may file a change or feedback; it lands in the Inbox."""
    if persona not in PERSONAS:
        raise ValueError(f"persona must be one of {PERSONAS}, got {persona!r}")
    if not is_person(person):
        raise ValueError(f"{person!r} is not a person")
    if not text.strip():
        raise ValueError("the change is empty")
    card = Canon(project).card("change", text.strip().splitlines()[0][:90], body=text.strip(),
                               refs={"source": persona}, payload={"source": persona, "person": person,
                                                                  "text": text.strip(), "hint": kind_hint})
    project.log("change_submitted", {"card": card["id"], "persona": persona, "person": person})
    return card


def heuristic_class(persona: str, text: str, hint: str | None = None) -> str:
    if hint in CLASSES:
        return hint
    if persona == "it":
        return "infra_change"
    if _DEFECT.search(text):
        return "defect"
    if text.strip().endswith("?") and not _CHANGE.search(text):
        return "question"
    if _NEW.search(text):
        return "new_requirement"
    return "change_request"


def triage_prompt(spec: dict, text: str, persona: str) -> str:
    reqs = "\n".join(f"- {r['id']}: {r['statement']}" for r in spec["requirements"])
    return f"""Classify a piece of feedback about a running product, so the factory routes it back correctly.

The product's requirements:
{reqs}

The feedback, from the {persona} persona:
<<<
{text}
>>>

Classes:
- defect: the product does not do what a requirement already says;
- change_request: a requirement should say something different;
- new_requirement: a need no requirement covers;
- infra_change: hosting, network, security or deployment rules;
- incident: the service is down or failing now;
- question: a question, not a change.

Feedback often mixes several requests. Give one part per distinct request, each with its own
class, so nothing in the feedback is lost. Answer with this JSON in a ```json block:
{{"parts": [{{"class": "defect", "requirements": ["R-2"], "text": "the part of the feedback this covers",
  "summary": "one sentence", "regression": "for a defect: the observable behaviour a regression test
  must check, as given / when / then"}}]}}
"""


def _part_result(part: dict, known: set, fallback_text: str) -> dict | None:
    if not isinstance(part, dict) or part.get("class") not in CLASSES:
        return None
    return {"class": part["class"], "requirements": [r for r in part.get("requirements") or [] if r in known],
            "summary": str(part.get("summary") or fallback_text[:200]), "regression": part.get("regression"),
            "text": str(part.get("text") or fallback_text).strip(), "by": "analyst"}


def _finish(result: dict[str, Any], hint: str | None, trusted: bool = False) -> dict[str, Any]:
    """Name the way back and whether a business decision comes first. A hint replaces the class the
    rules or the analyst read; where it differs, it needs a business decision unless it is
    ``trusted`` (see `_hint_trusted`), so a label never skips one (FR-P4)."""
    if hint in CLASSES and hint != result["class"]:
        result["hint_over"] = result["class"]
        result["class"] = hint
    result["way_back"] = WAY_BACK[result["class"]]
    result["needs_decision"] = result["class"] in NEEDS_DECISION or ("hint_over" in result and not trusted)
    return result


def ruling_defect_text(ruling: dict[str, Any]) -> str:
    """The words of the defect a product-defect ruling files (kernel/rulings.py apply_rulings): one
    definition, rulings.defect_regression, so the two can never drift apart. They name the release,
    the requirement and the held-out criteria, never the scenario itself (FR-B4-AC-2)."""
    from kernel.rulings import defect_regression

    return defect_regression(ruling)[0]


def _ruled_by_submitter(ruling: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Whether a holdout ruling was decided product_defect by the change's person, as its persona."""
    decision = ruling.get("decision") or {}
    return (decision.get("verdict") == "product_defect" and decision.get("person") == payload.get("person")
            and decision.get("persona") == payload.get("source"))


def _ruled_defect(project: Project, canon: Canon, card: dict[str, Any]) -> bool:
    """Whether a change card is the defect a person's product-defect ruling files (FR-H3-AC-2): a
    ruling not yet carried out, decided product_defect by the card's person as its persona, whose
    defect the card states word for word. That ruling is the decision the defect stands on: a
    person who may rule whether the product or the scenario is wrong ruled the product wrong,
    against a criterion the contract already holds. Nothing else a person files rides on it."""
    payload = card["payload"]
    carried_out = set(project.read("rulings_applied.json", []) or [])
    return any(r["id"] not in carried_out and _ruled_by_submitter(r, payload)
               and ruling_defect_text(r) == payload.get("text")
               for r in canon.cards(state="decided", kind="holdout_ruling"))


def _hint_trusted(project: Project, canon: Canon, card: dict[str, Any]) -> bool:
    """Whether a card's class hint stands without a business decision where it differs from the
    reading: it comes from a persona who decides change cards anyway, or it is the defect of a
    product-defect ruling the submitter decided. Any other persona's label, a developer's
    included, needs a business owner's or product owner's accept (FR-P4-AC-1)."""
    if card["payload"].get("source") in HINT_TRUSTED:
        return True
    return card["payload"].get("hint") == "defect" and _ruled_defect(project, canon, card)


def triage(project, card_id: str, *, model=None) -> dict:
    """Classify a change card. Feedback that mixes several requests is split: the card keeps the
    first part, and each further part becomes its own change card with the same person and
    persona (FR-I3-AC-2)."""
    from kernel.store import write_json

    canon = Canon(project)
    card = canon.get_card(card_id)
    text, persona = card["payload"]["text"], card["payload"]["source"]
    hint = card["payload"].get("hint")
    spec = project.read("spec.json") or {"requirements": []}
    result = {"class": heuristic_class(persona, text), "requirements": [],
              "summary": text[:200], "regression": None, "by": "rules"}
    parts = []
    if model is not None and spec["requirements"]:
        try:
            answer = _ask_json(model, triage_prompt(spec, text, persona))
            known = {r["id"] for r in spec["requirements"]}
            raw_parts = answer.get("parts") if isinstance(answer.get("parts"), list) else [answer]
            parts = [p for p in (_part_result(x, known, text) for x in raw_parts) if p]
            if parts:
                result.update(parts[0])
        except Exception as exc:  # the rules' classification stands
            result["model_error"] = str(exc)
    result = _finish(result, hint, _hint_trusted(project, canon, card))
    children = []
    if len(parts) > 1 and not card["payload"].get("split_from"):
        for part in parts[1:]:
            child = canon.card("change", part["text"].splitlines()[0][:90], body=part["text"],
                               refs={"source": persona, "split_from": card_id},
                               payload={"source": persona, "person": card["payload"].get("person"),
                                        "text": part["text"], "hint": None, "split_from": card_id,
                                        "triage": _finish(dict(part), None)})
            children.append(child["id"])
            project.log("change_triaged", {"card": child["id"], "class": child["payload"]["triage"]["class"],
                                           "way_back": child["payload"]["triage"]["way_back"],
                                           "requirements": child["payload"]["triage"]["requirements"],
                                           "split_from": card_id})
        result["split_into"] = children
    card = canon.get_card(card_id)
    card["payload"]["triage"] = result
    write_json(canon.dir / "inbox" / f"{card_id}.json", card)
    project.log("change_triaged", {"card": card_id, **{k: result[k] for k in ("class", "way_back", "requirements")},
                                   **({"split_into": children} if children else {})})
    return result


def amend_prompt(spec: dict, change: dict) -> str:
    reqs = "\n".join(f"- {r['id']} ({r['provenance']}): {r['statement']}\n" + "\n".join(
        f"    - {c['id']} [{c['kind']}]: given {c['given']}; when {c['when']}; then {c['then']}" for c in r["acceptance"])
        for r in spec["requirements"])
    return f"""Amend a software specification for an accepted change. Keep everything the change does not touch.

The current requirements:
{reqs}

The accepted change ({change['class']}), from the {change['source']} persona:
<<<
{change['text']}
>>>

Answer with this JSON in a ```json block. Use "modify" for an existing requirement (give its full new
statement and full new criteria), "add" for new ones, and "withdraw" for ids that no longer apply:
{{"modify": [{{"id": "R-2", "statement": "...", "acceptance": [{{"given": "...", "when": "...", "then": "...", "kind": "test"}}]}}],
  "add": [{{"statement": "...", "acceptance": [{{"given": "...", "when": "...", "then": "...", "kind": "test"}}]}}],
  "withdraw": []}}
"""


def _criteria(rid: str, items: Iterable[Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ac in items or []:
        if isinstance(ac, dict) and str(ac.get("then", "")).strip():
            out.append({"id": f"{rid}-AC-{len(out) + 1}", "given": str(ac.get("given", "")).strip() or "-",
                        "when": str(ac.get("when", "")).strip() or "-", "then": str(ac["then"]).strip(),
                        "kind": ac.get("kind") if ac.get("kind") in KINDS else "test"})
    if out and not any(c["kind"] == "test" for c in out):
        out[0]["kind"] = "test"
    return out


def _save_spec(project, spec: dict) -> None:
    version = project.meta.get("spec_version", 1)
    project.write(f"spec.v{version}.json", project.read("spec.json"))
    project.write("spec.json", spec)
    write_text(project.path("spec.md"), render_spec_md(spec))
    project.update_meta(spec_version=version + 1)


def _recompile(project: Project, contract: dict[str, Any], changed: set[str]) -> None:
    """Keep a compiled contract; tasks for changed requirements go back to pending."""
    project.write("contract.json", contract)
    project.write("checkplan.json", check_plan(contract))
    update_repo_contract(project, contract)
    state = project.read("tasks.json", {}) or {}
    for t in contract["tasks"]:
        rids = {c.rsplit("-AC-", 1)[0] for c in t["criteria"]}
        if rids & changed:
            state[t["id"]] = {"status": "pending", "rounds": [], "reopened_by": sorted(rids & changed)}
    project.write("tasks.json", state)
    project.update_meta(stage=5, contract_revision=contract["revision"], built=False)


def _decided_person(card: dict[str, Any], tri: dict[str, Any], person: str | None) -> str | None:
    """Who the change is applied for. A change a person rejected or deferred is never applied,
    whatever its class; one that needs a business decision is applied only once a person accepted
    it, and then for that person (FR-P4)."""
    decision = card.get("decision") or {}
    verdict = decision.get("verdict")
    if verdict is not None and verdict != "accept":
        raise PermissionError(f"{card['id']} was decided {verdict} by {decision.get('person')}: it is not applied")
    if tri["class"] in NEEDS_DECISION or tri.get("needs_decision"):
        if verdict != "accept":
            raise PermissionError(f"{card['id']} is a {tri['class']}: it needs a business decision (accept) first")
        return str(decision["person"])
    return person


def _regression(spec: dict[str, Any], tri: dict[str, Any], text: str) -> tuple[str, str]:
    """A defect's lesson: a regression criterion on the requirement it breaks (FR-K2). Returns the
    requirement's id and the new criterion's id."""
    rid = (tri.get("requirements") or [None])[0] or spec["requirements"][0]["id"]
    req = next(r for r in spec["requirements"] if r["id"] == rid)
    regression = tri.get("regression") or {}
    if isinstance(regression, str):
        regression = {"given": "-", "when": "-", "then": regression}
    then = str(regression.get("then") or f"the reported defect does not recur: {text[:160]}")
    cid = f"{rid}-AC-{len(req['acceptance']) + 1}"
    req["acceptance"].append({"id": cid, "given": str(regression.get("given") or "-"),
                              "when": str(regression.get("when") or "-"), "then": then, "kind": "test"})
    return str(rid), cid


def _keep_lesson(project: Project, canon: Canon, lesson: dict[str, Any]) -> None:
    """Record a defect's lesson and close its card: the repair is queued (FR-K2)."""
    lessons = project.read("lessons.json", []) or []
    lessons.append(lesson | {"at": project.factory.clock.stamp()})
    project.write("lessons.json", lessons)
    canon.close(lesson["card"], f"repair queued with regression criterion {lesson['regression_criterion']}",
                state="resolved")


def _owned(req: dict[str, Any], card_id: str, person: str | None) -> dict[str, Any]:
    """An amended or added requirement rests on the change: confirmed by the person who accepted it."""
    req.update(sources=[f"change:{card_id}"],
               provenance="customer-confirmed" if person and is_person(person) else "vendor-proposed")
    if person and is_person(person):
        req["decided_by"] = person
    return req


def _modify(spec: dict[str, Any], items: list[Any], card_id: str, person: str | None) -> set[str]:
    """Requirements the amendment restates, each with its full new statement and criteria."""
    changed: set[str] = set()
    by_id = {r["id"]: r for r in spec["requirements"]}
    for m in items:
        r = by_id.get(m.get("id")) if isinstance(m, dict) else None
        crits = _criteria(r["id"], m.get("acceptance")) if r else []
        if r and str(m.get("statement", "")).strip() and crits:
            _owned(r, card_id, person).update(statement=str(m["statement"]).strip(), acceptance=crits)
            changed.add(r["id"])
    return changed


def _add(spec: dict[str, Any], items: list[Any], card_id: str, person: str | None) -> set[str]:
    """Requirements the amendment adds, numbered after the spec's last one."""
    changed: set[str] = set()
    for a in items:
        rid = f"R-{len(spec['requirements']) + 1}"
        crits = _criteria(rid, a.get("acceptance")) if isinstance(a, dict) else []
        if crits and str(a.get("statement", "")).strip():
            spec["requirements"].append(_owned({"id": rid, "statement": str(a["statement"]).strip(),
                                                "priority": "must", "acceptance": crits}, card_id, person))
            changed.add(rid)
    return changed


def _amend(spec: dict[str, Any], answer: dict[str, Any], card_id: str, person: str | None) -> set[str]:
    """Apply the analyst's amendment to ``spec``: modified, added and withdrawn requirements. A
    withdrawn requirement stays in the spec, marked withdrawn; the compiler gives it no task."""
    by_id = {r["id"]: r for r in spec["requirements"]}  # what the spec held before: an addition is not withdrawn
    changed = _modify(spec, answer.get("modify") or [], card_id, person)
    changed |= _add(spec, answer.get("add") or [], card_id, person)
    for wid in answer.get("withdraw") or []:
        if wid in by_id:
            by_id[wid]["provenance"] = "withdrawn"
            by_id[wid].pop("decided_by", None)
            changed.add(wid)
    if not changed:
        raise ValueError(f"the amendment for {card_id} changed nothing")
    return changed


def _live_criteria(spec: dict[str, Any]) -> dict[str, tuple[Any, ...]]:
    """Each criterion a spec still stands behind, by id, with its wording: a withdrawn requirement's
    criteria are not among them."""
    return {str(c["id"]): tuple(c.get(k) for k in ("given", "when", "then", "kind"))
            for r in spec["requirements"] if r.get("provenance") != "withdrawn" for c in r["acceptance"]}


def _gone(before: dict[str, tuple[Any, ...]], spec: dict[str, Any]) -> list[str]:
    """The criteria the amended ``spec`` withdrew or restated: no scenario written for them stands."""
    after = _live_criteria(spec)
    return sorted(cid for cid, wording in before.items() if after.get(cid) != wording)


def _route(project: Project, canon: Canon, card_id: str, tri: dict[str, Any], text: str) -> dict[str, Any]:
    """A class that amends nothing: IT's change to the paved road appears on the board as a road card
    that only IT decides (FR-Q2), and delivery uses the road as IT leaves it in paved_roads.json,
    after a dry run; an incident or a question is routed to its stage."""
    cls, out = tri["class"], {"class": tri["class"], "way_back": tri["way_back"], "changed": []}
    if cls == "infra_change":
        road = canon.card("road", f"Infrastructure change: {text[:70]}", body=text,
                          refs={"change": card_id, "source": "it"},
                          payload={"source": "it", "text": text, "from_card": card_id})
        canon.close(card_id, f"routed to IT as road card {road['id']}", state="resolved")
        out["road_card"] = road["id"]
    project.log("change_routed", {"card": card_id, "class": cls, "way_back": tri["way_back"],
                                  **({"road": out["road_card"]} if "road_card" in out else {})})
    return out


def apply_change(project: Project, card_id: str, *, model: Any = None, person: str | None = None) -> dict[str, Any]:
    """Carry a triaged change back into the spec and contract. The amended spec is compiled before
    anything is written: a change the compiler refuses raises and leaves the spec, the contract,
    the lessons, the approvals and the card as they were, so the spec and the contract never
    diverge. Once applied, the holdout scenarios of the criteria it withdrew or restated are
    retired, so no holdout runs for a criterion the contract no longer holds as written."""
    canon = Canon(project)
    card = canon.get_card(card_id)
    tri = card["payload"].get("triage") or triage(project, card_id, model=model)
    cls = tri["class"]
    person = _decided_person(card, tri, person)
    text = str(tri.get("text") or card["payload"]["text"])
    if cls not in AMENDS:
        return _route(project, canon, card_id, tri, text)
    spec = project.read("spec.json")
    before = _live_criteria(spec)
    lesson: dict[str, Any] | None = None
    if cls == "defect":
        rid, cid = _regression(spec, tri, text)
        changed = {rid}
        lesson = {"card": card_id, "class": cls, "requirement": rid, "regression_criterion": cid, "text": text}
    else:
        change = {"class": cls, "source": card["payload"]["source"], "text": text}
        changed = _amend(spec, _ask_json(model, amend_prompt(spec, change)) if model is not None else {},
                         card_id, person)
    contract = to_contract(project, spec)  # a CompileError here leaves everything as it was
    _save_spec(project, spec)
    if lesson is not None:
        _keep_lesson(project, canon, lesson)
    stale = canon.mark_stale(changed, reason=f"{cls} {card_id}")
    _recompile(project, contract, changed)
    retired = retire_holdouts(project, _gone(before, spec), because=card_id)
    project.log("change_applied", {"card": card_id, "class": cls, "changed": sorted(changed),
                                   "stale": [d["id"] for d in stale], "contract": contract["revision"],
                                   "holdouts_retired": retired})
    return {"class": cls, "way_back": tri["way_back"], "changed": sorted(changed),
            "stale": [d["id"] for d in stale], "contract": contract["revision"], "holdouts_retired": retired}


