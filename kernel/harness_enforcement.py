"""Harness and enforcement (FR-NVL1): which harness and model act for each role, and whether Gnomon's structure (the
contract, its criteria and the gate) applies to what they do.

The owner (2026-11-25): "how it's running inside Gnomon and if I change a harness, can I ensure Gnomon is
reconfiguring or enforcing its structures?"

- **On by default.** Gnomon's enforcement is on for the platform and every project until a person turns it off,
  with a reason, signed and recorded in the ledger (the factory's own for the platform, the project's for one
  project). Turning it on again is recorded the same way. A project follows the platform unless it has its own.
- **What it is.** With enforcement on, every run is held to the project's contract: the builder works inside the
  task's write scope on its criteria, and nothing merges before the gate (tests, fail-first, trace, the verifier)
  passes. Gnomon as the cell runner enforces the scope and shell rules *during* the run; another harness (Claude
  Code, Codex, OpenCode, a command) is checked *after* the run by the same rules. A text role answered by a harness
  is outside Gnomon's lane: no Gnomon audit trail for that call.
- **What an opt-out changes.** The gate is never skipped: an opt-out only records that the person accepts a
  harness's runs without Gnomon's in-run policy, so every run row and Ask Rihma answer says "not enforced: opted out
  by <person>" instead of nudging to bring the harness back under Gnomon.

``effects`` says, for the roles and harnesses here, what changing harness does to enforcement.
"""

from __future__ import annotations

from typing import Any

PLATFORM = "_factory"
KIND = "enforcement_set"
# Who may turn Gnomon's enforcement off or on: the platform by IT or compliance; a project also by its developer.
PLATFORM_SETTERS = ("it", "compliance")
PROJECT_SETTERS = ("it", "compliance", "developer", "product_owner")
REASON_MIN = 3

IN_RUN = ("Gnomon runs the work: the write scope, protected paths and shell rules are enforced during the run, "
          "every tool call is in a hash-chained record, and the gate decides before anything merges")
AFTER_RUN = ("{label} runs the work: Gnomon's in-run policy does not apply, so every rule is checked after the run "
             "by the same gate (tests, fail-first, trace, the verifier); a change that breaks one never merges")
TEXT_GNOMON = "answered through Gnomon's lane: the call is in Gnomon's audit trail"
TEXT_HARNESS = "answered by {label}: not through Gnomon's lane, so no Gnomon audit trail for that call"


class EnforcementRefused(ValueError):
    """A change to enforcement Rihmasto does not take, with the reason."""


def _factory_project(factory: Any, create: bool) -> Any:
    from kernel.learn import factory_project

    return factory_project(factory, create)


def _rows(project: Any) -> list[dict[str, Any]]:
    """The opt-out records only: a levels change once kept under this kind (no ``on``) is not an opt-out."""
    return [r for r in project.ledger().of_kind(KIND) if "on" in r["event"]["payload"]]


def _latest(project: Any) -> dict[str, Any] | None:
    if project is None:
        return None
    rows = _rows(project)
    return dict(rows[-1]["event"]["payload"], at=rows[-1]["event"].get("at")) if rows else None


def _said(rec: dict[str, Any] | None, where: str) -> str:
    if rec is None:
        return f"on for {where} (the default)"
    if rec.get("on"):
        return f"on for {where}, turned on by {rec.get('person')} on {str(rec.get('at') or '')[:10]}"
    return (f"off for {where}: opted out by {rec.get('person')} on {str(rec.get('at') or '')[:10]}, "
            f"because \"{rec.get('reason')}\"")


def state(factory: Any, project: Any = None) -> dict[str, Any]:
    """The platform's setting, the project's own (when it has one) and the one in force there, each with who set it."""
    plat = _latest(_factory_project(factory, False))
    own = _latest(project) if project is not None and project.pid != PLATFORM else None
    rec, scope = (own, "project") if own is not None else (plat, "platform")
    on = True if rec is None else bool(rec.get("on"))
    where = "this project" if scope == "project" else "the platform"
    return {"on": on, "from": scope if rec is not None else "default",
            "platform": {"on": True if plat is None else bool(plat.get("on")), "record": plat,
                         "said": _said(plat, "the platform")},
            "project": ({"on": bool(own.get("on")), "record": own, "said": _said(own, "this project")}
                        if own is not None else None),
            "said": _said(rec, where), "gate": "the gate always runs before anything merges: an opt-out never skips it"}


def _payload(rec: dict[str, Any] | None) -> dict[str, Any] | None:
    return dict(rec["event"]["payload"], at=rec["event"].get("at")) if rec else None


def timeline(factory: Any, project: Any) -> Any:
    """``then(at, seq)``: the enforcement in force when a run recorded at ``at`` (seq ``seq`` in the project's ledger)
    ran, so a run keeps the state it ran under after a later opt-out. The project's own setting counts when recorded
    before the run (by ledger order), else the platform's recorded before it (by time). None when the run's time is
    not recorded."""
    plat = _factory_project(factory, False)
    plat_rows = _rows(plat) if plat is not None else []
    own_rows = _rows(project) if project is not None and project.pid != PLATFORM else []

    def then(at: str | None, seq: int | None) -> dict[str, Any] | None:
        if not at and seq is None:
            return None
        own = [r for r in own_rows if (r["seq"] < seq if seq is not None else str(r["event"].get("at")) < str(at))]
        before = [r for r in plat_rows if at and str(r["event"].get("at") or "") < str(at)]
        rec, where = (own[-1], "this project") if own else ((before[-1], "the platform") if before else (None, ""))
        payload = _payload(rec)
        return {"on": True if payload is None else bool(payload.get("on")), "record": payload,
                "said": _said(payload, where or "the platform")}

    return then


def set_enforcement(factory: Any, project: Any, *, on: bool, reason: str, person: str, persona: str) -> dict[str, Any]:
    """Turn Gnomon's enforcement on or off for the platform (``project`` None) or one project: signed and recorded.
    Turning it off needs a reason, and only a persona that may set it."""
    setters = PLATFORM_SETTERS if project is None else PROJECT_SETTERS
    if persona not in setters:
        raise EnforcementRefused(f"as {persona} you may not change Gnomon's enforcement here: "
                                 f"{' or '.join(setters)} may")
    reason = str(reason or "").strip()
    if not on and len(reason) < REASON_MIN:
        raise EnforcementRefused("say why you opt out of Gnomon's enforcement: the reason is recorded with it")
    target = project if project is not None else _factory_project(factory, True)
    before = state(factory, project)
    target.log(KIND, {"on": bool(on), "reason": reason, "person": person, "persona": persona,
                      "scope": "platform" if project is None else "project", "was": before["on"]})
    return state(factory, project)


# -- what changing harness does --------------------------------------------------------------------------------------

def routing_now() -> dict[str, Any]:
    """The routing in force (an unreadable overlay reads as none: Models setup says why in its own words)."""
    from kernel.lanes import read_routing

    try:
        return read_routing() or {}
    except (OSError, ValueError):
        return {}


def _builder(factory: Any, project: Any) -> dict[str, Any]:
    from kernel.runners import RUNNERS, label_of
    from kernel.runners.choice import effective

    pid = project.pid if project is not None else None
    try:
        choice = effective(factory, pid, "builder")
    except (OSError, ValueError, KeyError):
        choice = {"runner": "gnomon", "from": "default"}
    name = str(choice.get("runner") or "gnomon")
    return {"role": "builder", "harness": name, "label": label_of(name), "from": choice.get("from", "default"),
            "enforced": IN_RUN if name == "gnomon" else AFTER_RUN.format(label=label_of(name)),
            "in_run": name == "gnomon", "others": [
                {"harness": k, "label": v["label"],
                 "then": IN_RUN if k == "gnomon" else AFTER_RUN.format(label=v["label"])}
                for k, v in RUNNERS.items() if k != name]}


def _text_role(routing: dict[str, Any], role: str) -> dict[str, Any]:
    from kernel import harness_model as hm

    route = hm.route_of(routing, role)
    if route is not None:
        return {"role": role, "harness": route["harness"], "label": route["label"], "model": route.get("model") or "",
                "enforced": TEXT_HARNESS.format(label=route["label"]), "in_run": False,
                "others": [{"harness": "gnomon", "label": "Gnomon", "then": TEXT_GNOMON}]}
    spec = (routing.get("roles") or {}).get(role) or {}
    return {"role": role, "harness": "gnomon", "label": "Gnomon", "model": str(spec.get("model") or ""),
            "enforced": TEXT_GNOMON, "in_run": True,
            "others": [{"harness": k, "label": v["label"], "then": TEXT_HARNESS.format(label=v["label"])}
                       for k, v in hm.HARNESSES.items()]}


def effects(factory: Any, project: Any = None) -> dict[str, Any]:
    """Per role: the harness acting now, what Gnomon enforces on it, and what switching to each other harness does."""
    from kernel import harness_model as hm

    routing = routing_now()
    roles = [_builder(factory, project)] + [_text_role(routing, r) for r in hm.TEXT_ROLES]
    st = state(factory, project)
    return {"state": st, "roles": roles,
            "summary": ("Gnomon's structure (the contract, its criteria and the gate) applies to every run here. "
                        if st["on"] else "Gnomon's enforcement is opted out here; the gate still runs. ")
                       + "Changing a harness changes who runs the work, never whether the gate decides."}
