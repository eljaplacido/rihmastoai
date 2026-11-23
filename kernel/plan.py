"""Approve the plan before building (after Kiro's gated spec, Cursor's Plan Mode and Copilot Workspace).

At pilot and production maturity, or whenever the owner turns it on (`approve_plan` in
`project.json`), the pipeline stops after the spec. An "Approve the plan" card waits for a person:

- **approve:** the contract is compiled and the build starts;
- **reject with a reason:** the spec is drafted again with that reason in front of the analyst,
  and a new card follows;
- **edit before approving:** a person may change a requirement's statement or criteria. The
  requirement becomes customer-confirmed by them, and the card is reissued for the edited plan.

Once the plan is approved the contract exists, and a change goes through the change loop instead.
"""

from __future__ import annotations

from typing import Any

from kernel.canon import CARD_DECIDERS, Canon, DecisionRefused
from kernel.people import is_person

NEEDS_APPROVAL = {"explore": False, "demo": False, "pilot": True, "production": True}


def required(project) -> bool:
    """Whether a person approves the plan before building: the owner's setting, else the maturity's
    rule; and at any maturity when a requirement contradicts the paved road (FR-DF1-AC-3)."""
    meta = project.meta
    if "approve_plan" in meta:
        return bool(meta["approve_plan"])
    if NEEDS_APPROVAL.get(meta.get("maturity"), True):
        return True
    from kernel.roads import road_conflicts

    return bool(road_conflicts(project.read("spec.json") or {}))


def _version(project) -> int:
    return int(project.meta.get("spec_version", 1))


def _cards(project, state=None) -> list:
    return [c for c in Canon(project).cards(state=state, kind="approval") if c["refs"].get("scope") == "plan"]


def summary(spec: dict) -> str:
    lines = [f"{spec.get('title', '')}: {spec.get('summary', '')}", ""]
    for r in spec["requirements"]:
        lines.append(f"- {r['id']} ({r['provenance']}): {r['statement']}")
        for c in r["acceptance"]:
            lines.append(f"    - {c['id']} [{c['kind']}]: then {c['then']}")
    if spec.get("interface"):
        lines += ["", "Interface:"] + [f"- {e['method']} {e['path']}" for e in spec["interface"]]
    from kernel.roads import conflict_lines

    conflicts = conflict_lines(spec)  # for the person who approves: built as written, delivery would fail
    if conflicts:
        lines += ["", "Conflicts with the paved road (edit or reject these before approving):", *conflicts]
    return "\n".join(lines)


def open_card(project) -> dict:
    spec, version = project.read("spec.json"), _version(project)
    for c in _cards(project, state="open"):
        if c["refs"].get("spec_version") == version:
            return c
    n_crit = sum(len(r["acceptance"]) for r in spec["requirements"])
    from kernel.roads import road_conflicts

    conflicts = road_conflicts(spec)
    card = Canon(project).card(
        "approval", f"Approve the plan: {len(spec['requirements'])} requirements, {n_crit} criteria"
        + (f"; {len(conflicts)} {'conflict' if len(conflicts) == 1 else 'conflicts'} with the paved road"
           if conflicts else ""),
        body=summary(spec), blocking=True, payload={"road_conflicts": conflicts} if conflicts else None,
        refs={"scope": "plan", "spec_version": version, "requirements": [r["id"] for r in spec["requirements"]]})
    project.log("plan_card_opened", {"card": card["id"], "spec_version": version})
    return card


def gate(project, *, model) -> dict | None:
    """None when building may start; otherwise what the pipeline waits on."""
    if not required(project):
        return None
    version = _version(project)
    for c in _cards(project, state="decided"):
        if c["refs"].get("spec_version") != version:
            continue
        d = c["decision"]
        if d["verdict"] == "approve":
            if not project.meta.get("plan_approved"):
                project.update_meta(plan_approved={"card": c["id"], "by": d["person"], "spec_version": version})
                project.log("plan_approved", {"card": c["id"], "by": d["person"], "spec_version": version})
            return None
        if d["verdict"] == "reject" and not c["refs"].get("redone"):
            redo(project, c, model=model)
            break
    card = open_card(project)
    return {"waiting_on": [card["id"]], "why": "a person approves the plan before building"}


def redo(project, card: dict, *, model) -> dict:
    """Draft the spec again with the person's reason in front of the analyst."""
    from kernel.spec import make_spec
    from kernel.store import write_json

    version = _version(project)
    project.write(f"spec.v{version}.json", project.read("spec.json"))
    reason = card["decision"].get("reason") or "rejected without a reason"
    spec = make_spec(project, model=model, feedback=f"{card['decision']['person']} rejected the previous plan: {reason}")
    project.update_meta(spec_version=version + 1)
    card["refs"]["redone"] = True
    write_json(Canon(project).dir / "inbox" / f"{card['id']}.json", card)
    project.log("plan_redone", {"card": card["id"], "from_version": version, "reason": reason})
    return spec


def edit_requirement(project, rid: str, *, person: str, persona: str, statement: str | None = None,
                     acceptance: list | None = None) -> dict:
    """A person changes a requirement before the plan is approved."""
    from kernel.spec import KINDS, render_spec_md
    from kernel.store import write_text

    if project.path("contract.json").exists():
        raise DecisionRefused("the plan is approved and compiled: change it through the change loop")
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person")
    if persona not in CARD_DECIDERS["approval"]:
        raise DecisionRefused(f"a {persona} may not edit the plan (editors: {CARD_DECIDERS['approval']})")
    spec = project.read("spec.json")
    req = next((r for r in spec["requirements"] if r["id"] == rid), None)
    if req is None:
        raise KeyError(rid)
    version = _version(project)
    project.write(f"spec.v{version}.json", spec)
    if statement is not None and statement.strip():
        req["statement"] = statement.strip()
    if acceptance is not None:
        crits: list[dict[str, Any]] = []
        for ac in acceptance:
            if isinstance(ac, dict) and str(ac.get("then", "")).strip():
                crits.append({"id": f"{rid}-AC-{len(crits) + 1}", "given": str(ac.get("given") or "-").strip(),
                              "when": str(ac.get("when") or "-").strip(), "then": str(ac["then"]).strip(),
                              "kind": ac.get("kind") if ac.get("kind") in KINDS else "test"})
        if not crits:
            raise ValueError("a requirement needs at least one criterion with a 'then'")
        if not any(c["kind"] == "test" for c in crits):
            crits[0]["kind"] = "test"
        req["acceptance"] = crits
    req.update(provenance="customer-confirmed", decided_by=person, sources=sorted(set(req.get("sources", [])) | {f"edit:{person}"}))
    project.write("spec.json", spec)
    write_text(project.path("spec.md"), render_spec_md(spec))
    project.update_meta(spec_version=version + 1)
    canon = Canon(project)
    for c in _cards(project, state="open"):
        canon.close(c["id"], f"the plan was edited by {person}; a new card follows")
    project.log("plan_edited", {"requirement": rid, "by": person, "persona": persona, "spec_version": version + 1})
    return req
