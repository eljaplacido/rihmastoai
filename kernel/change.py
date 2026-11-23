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
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from kernel.canon import Canon
from kernel.compile import check_plan, to_contract, update_repo_contract
from kernel.intake import _ask_json
from kernel.people import PERSONAS, is_person
from kernel.spec import KINDS, render_spec_md
from kernel.store import write_text

CLASSES = ("defect", "change_request", "new_requirement", "infra_change", "incident", "question")
WAY_BACK = {"defect": 5, "change_request": 4, "new_requirement": 2, "infra_change": 7, "incident": 7, "question": 2}
NEEDS_DECISION = {"change_request", "new_requirement"}

_DEFECT = re.compile(r"\b(error|errors|crash|crashes|broken|bug|fails?|failing|wrong|500|exception|does ?n[o']t work|"
                     r"lost|missing data|virhe|ei toimi|kaatuu)\b", re.I)
_NEW = re.compile(r"\b(new feature|also need|we also want|add a new|another (screen|report|page)|uusi)\b", re.I)
_CHANGE = re.compile(r"\b(change|should be|instead|rename|rather|move|make it|prefer|muuta|pitäisi)\b", re.I)


def submit(project, *, persona: str, person: str, text: str, kind_hint: str | None = None) -> dict:
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


def _finish(result: dict, hint) -> dict:
    if hint in CLASSES:
        result["class"] = hint
    result["way_back"] = WAY_BACK[result["class"]]
    result["needs_decision"] = result["class"] in NEEDS_DECISION
    return result


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
    result = {"class": heuristic_class(persona, text, hint), "requirements": [],
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
    result = _finish(result, hint)
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


def _recompile(project, spec: dict, changed: set) -> dict:
    """Recompile the contract; tasks for changed requirements go back to pending."""
    contract = to_contract(project, spec)
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
    return contract


def apply_change(project, card_id: str, *, model=None, person: str | None = None) -> dict:
    """Carry a triaged change back into the spec and contract."""
    canon = Canon(project)
    card = canon.get_card(card_id)
    tri = card["payload"].get("triage") or triage(project, card_id, model=model)
    cls = tri["class"]
    if cls in NEEDS_DECISION:
        decision = card.get("decision") or {}
        if decision.get("verdict") != "accept":
            raise PermissionError(f"{card_id} is a {cls}: it needs a business decision (accept) first")
        person = decision["person"]
    spec = project.read("spec.json")
    change = {"class": cls, "source": card["payload"]["source"], "text": tri.get("text") or card["payload"]["text"]}
    changed: set = set()

    if cls == "defect":
        rid = (tri.get("requirements") or [None])[0] or spec["requirements"][0]["id"]
        req = next(r for r in spec["requirements"] if r["id"] == rid)
        regression = tri.get("regression") or {}
        if isinstance(regression, str):
            regression = {"given": "-", "when": "-", "then": regression}
        then = str(regression.get("then") or f"the reported defect does not recur: {change['text'][:160]}")
        cid = f"{rid}-AC-{len(req['acceptance']) + 1}"
        req["acceptance"].append({"id": cid, "given": str(regression.get("given") or "-"),
                                  "when": str(regression.get("when") or "-"), "then": then, "kind": "test"})
        changed.add(rid)
        lessons = project.read("lessons.json", []) or []
        lessons.append({"card": card_id, "class": cls, "requirement": rid, "regression_criterion": cid,
                        "text": change["text"], "at": project.factory.clock.stamp()})
        project.write("lessons.json", lessons)
    elif cls in ("change_request", "new_requirement"):
        answer = _ask_json(model, amend_prompt(spec, change)) if model is not None else {}
        by_id = {r["id"]: r for r in spec["requirements"]}
        for m in answer.get("modify") or []:
            r = by_id.get(m.get("id")) if isinstance(m, dict) else None
            crits = _criteria(r["id"], m.get("acceptance")) if r else []
            if r and str(m.get("statement", "")).strip() and crits:
                r.update(statement=str(m["statement"]).strip(), acceptance=crits,
                         provenance="customer-confirmed" if person and is_person(person) else "vendor-proposed",
                         sources=[f"change:{card_id}"])
                if person and is_person(person):
                    r["decided_by"] = person
                changed.add(r["id"])
        for a in answer.get("add") or []:
            if not isinstance(a, dict) or not str(a.get("statement", "")).strip():
                continue
            rid = f"R-{len(spec['requirements']) + 1}"
            crits = _criteria(rid, a.get("acceptance"))
            if not crits:
                continue
            new = {"id": rid, "statement": str(a["statement"]).strip(), "sources": [f"change:{card_id}"],
                   "priority": "must", "acceptance": crits,
                   "provenance": "customer-confirmed" if person and is_person(person) else "vendor-proposed"}
            if person and is_person(person):
                new["decided_by"] = person
            spec["requirements"].append(new)
            changed.add(rid)
        for wid in answer.get("withdraw") or []:
            if wid in by_id:
                by_id[wid]["provenance"] = "withdrawn"
                by_id[wid].pop("decided_by", None)
                changed.add(wid)
        if not changed:
            raise ValueError(f"the amendment for {card_id} changed nothing")
    elif cls == "infra_change":
        # IT's change to the paved road appears on the board as a road card that only IT decides
        # (FR-Q2). Delivery uses the road as IT leaves it in paved_roads.json, after a dry run.
        road = canon.card("road", f"Infrastructure change: {change['text'][:70]}", body=change["text"],
                          refs={"change": card_id, "source": "it"},
                          payload={"source": "it", "text": change["text"], "from_card": card_id})
        canon.close(card_id, f"routed to IT as road card {road['id']}", state="resolved")
        project.log("change_routed", {"card": card_id, "class": cls, "way_back": tri["way_back"], "road": road["id"]})
        return {"class": cls, "way_back": tri["way_back"], "changed": [], "road_card": road["id"]}
    else:
        project.log("change_routed", {"card": card_id, "class": cls, "way_back": tri["way_back"]})
        return {"class": cls, "way_back": tri["way_back"], "changed": []}

    _save_spec(project, spec)
    if cls == "defect":
        canon.close(card_id, f"repair queued with regression criterion {cid}", state="resolved")
    stale = canon.mark_stale(changed, reason=f"{cls} {card_id}")
    contract = _recompile(project, spec, changed)
    project.log("change_applied", {"card": card_id, "class": cls, "changed": sorted(changed),
                                   "stale": [d["id"] for d in stale], "contract": contract["revision"]})
    return {"class": cls, "way_back": tri["way_back"], "changed": sorted(changed),
            "stale": [d["id"] for d in stale], "contract": contract["revision"]}
