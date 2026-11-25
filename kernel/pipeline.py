"""The paved road as a state machine: advance a project as far as it can go without a person.

Each call looks at what the project has and does the next thing:
1. intake;
2. spec;
3. compile, and author the holdouts;
4. build, cell by cell;
5. deliver, by maturity;
6. operate.

It stops when a person is needed: a blocking question, an escalation, an acceptance, a user
validation, IT's deploy gate, an unconfigured road, or an open security finding that holds a
release. It says which card it waits on (an open finding has no card: it says which findings).
Calling it again after the person decides carries on from there.

A paused project runs nothing, not even its intake or its spec, until a person resumes it
(FR-J3). Building, a ruling's or a change's rebuild and delivery each ask the autonomy cap first
(FR-K4). A user validation decided `fix` or `change` hands the release to the change loop: one
change card in the decider's name and words; a fix is carried out at once, a change once a
business owner accepts its card (FR-R3-AC-2).

Each pass (of a project that is not paused) first carries out the decided update cards
(`kernel.observations.apply_updates`), so a trial a person approved is recorded before anything
moves (FR-V2-AC-2).

Before it waits on cards, the run asks the delegations in force (kernel/delegation.py): a card a
person delegated to one of the factory's rules is decided by that rule in their name, and the pass
goes on. A human checkpoint a person set to hold the run stops it once its stage is reached, until
a person has looked (kernel/track.py); while an autopilot run is bound to a sandbox, a delivery that
would leave it waits for a person (kernel/autopilot.py).

An adopted solution (`rihma adopt`) had no intake. Until a change is applied to it, it says what
it waits for by its intent (FR-B1-AC-3): to monitor, `monitoring` with the last probe result; to
maintain or improve, `waiting` for a change, a workspace submission or a person. Once a change
is applied, it goes round the normal loop: build, gate and delivery.

`tick(factory)` carries out the decided concept cards and advances nothing else, for the command
line and the cockpit: a validated concept becomes a project without any project being run.
"""

from __future__ import annotations

import json
from typing import Any

from kernel.attach import attached_state
from kernel.canon import Canon
from kernel.compile import author_holdouts, compile_project
from kernel.dispatch import build
from kernel.intake import SendBack, blocking_open
from kernel.modules import stop_before
from kernel.spec import make_spec
from kernel.store import Factory, Project

ADOPTED_WAITS_FOR = ("a change", "a workspace submission", "a person")
# What one part of a pass gives back: a result to return, AGAIN to start the next pass, or None to
# go on to the next part of this pass.
AGAIN = "again"


def _waiting(stage: int, cards, why: str) -> dict:
    return {"state": "waiting", "stage": stage, "waiting_on": list(cards), "why": why}


def tick(factory: Factory) -> dict:
    """Carry out the factory's decided concept cards once each (a validated concept becomes a
    project whose intake starts from its need), and advance nothing else."""
    from kernel.signals import apply_concepts

    applied = apply_concepts(factory)
    return {"concepts_applied": applied, "projects_created": [a["project"] for a in applied if a.get("project")]}


def advance(project, *, model, **kwargs) -> dict:
    """Move the project forward until a person is needed. A model endpoint that fails (an apparatus
    failure, for example during a network outage) stops the run cleanly: what was recorded stays,
    and running again resumes. A confidential project's skipped hosted fallback is recorded once per run."""
    from kernel.confidential import ConfidentialRefused, one_run
    from kernel.model import ModelError

    try:
        with one_run():
            return _advance(project, model=model, **kwargs)
    except ConfidentialRefused as exc:     # a confidential project's next step would leave for a hosted endpoint
        return {"state": "refused", "stage": project.meta.get("stage"), "confidential": True, "why": str(exc)}
    except ModelError as exc:
        project.log("apparatus_failure", {"where": "pipeline", "error": str(exc)[:300]})
        return {"state": "apparatus_failure", "stage": project.meta.get("stage"), "apparatus": True,
                "why": f"a model endpoint failed ({exc}); what was recorded stays, run again when it answers"}


def _advance(project, *, model, lanes=None, cell_runner=None, verifier_runner=None, deliver_kwargs=None,
             max_steps: int = 12) -> dict:
    history: list = []
    for _ in range(max_steps):
        paused = _paused(project, history)
        if paused is not None:
            return paused
        _carry_out_decisions(project, history)     # a person's decision never waits behind another open question
        held = _checkpoint(project, history)
        if held is not None:
            return held
        _apply_updates(project, history)
        _apply_accepted(project, model, history)
        idle = adopted_state(project) or attached_state(project)
        if idle is not None:
            return idle | {"history": history}
        canon = Canon(project)
        step = _shape(project, model, history)
        if step is None:  # the edge of the project's modules (FR-MOD2): spec only stops before the build
            step = stop_before(project, "build", history) or _gatekeep(project, canon, history)
        if step is None:
            step = _build(project, canon, history, lanes=lanes, cell_runner=cell_runner,
                          verifier_runner=verifier_runner)
        if step is None:
            step = stop_before(project, "delivery", history) or _deliver(project, model, canon, history, deliver_kwargs)
        if isinstance(step, dict):
            if step.get("state") == "waiting" and _delegated(project, step, history):
                continue
            return step
    return {"state": "progress", "stage": project.meta["stage"], "history": history}


def _delegated(project: Project, step: dict[str, Any], history: list[Any]) -> bool:
    """Whether a delegation decided a card the run waits on (kernel/delegation.py): then it goes on."""
    from kernel.delegation import consult

    decided = consult(project, list(step.get("waiting_on") or []))
    if decided:
        history.append({"delegated": [{k: d[k] for k in ("card", "verdict", "delegation")} for d in decided]})
    return bool(decided)


def _checkpoint(project: Project, history: list[Any]) -> dict[str, Any] | None:
    """A human checkpoint that holds the run: its stage is reached and no person has looked yet; or an
    autopilot pass whose run a person stopped while it ran, which ends here (kernel/autopilot.py)."""
    from kernel.autopilot import pass_stopped
    from kernel.track import checkpoint_hold

    held = pass_stopped(project) or checkpoint_hold(project)
    return None if held is None else held | {"history": history}


def _paused(project: Project, history: list[Any]) -> dict[str, Any] | None:
    """A paused project runs nothing until a person resumes it: no intake, spec, compile, build or
    delivery, and no decided card is carried out (FR-J3). None when it is not paused."""
    from kernel.safestop import paused

    if not paused(project):
        return None
    pause = project.meta["pause"]
    why = f"paused by {pause.get('requested_by')}" + (f": {pause['reason']}" if pause.get("reason") else "")
    return {"state": "paused", "stage": project.meta.get("stage"), "history": history, "why": why,
            "stopped_at": pause.get("stopped_at")}


def _capped(project: Project, exc: Exception, history: list[Any]) -> dict[str, Any]:
    return {"state": "capped", "stage": project.meta["stage"], "why": str(exc), "history": history}


def _apply_updates(project, history: list) -> None:
    """Record the update cards people decided since the last pass (a trial, a decline, a deferral)."""
    from kernel.observations import apply_updates

    done = apply_updates(project)
    if done:
        history.append({"updates": [{"card": u["card"], "verdict": u["verdict"]} for u in done]})


def _intake_again(project, model, history: list) -> dict | str | None:
    """An intake sent back to its questions, or over material added later (FR-CHG1), runs first. Over a spec
    written before the material, a person looks before anything is built on the old spec."""
    meta = project.meta
    from kernel.project_material import pending_intake

    added_to_spec = bool(meta.get("reintake_pending")) and not meta.get("redo_intake") \
        and project.path("spec.json").exists()
    redone = pending_intake(project, model=model)
    if not redone:
        return None
    history.append(redone)
    if not added_to_spec:
        return AGAIN
    open_qs = [q for q in blocking_open(project) if q.get("card")]
    why = ("the panel read the added material; the spec was written before it: answer what it asks, then go "
           "back to the spec to write it again with it, or go on with the spec as it is")
    return _waiting(2 if open_qs else 4, [q["card"] for q in open_qs], why) | {"material_read": True,
                                                                           "history": history}


def _first_intake(project, model, history: list) -> dict | str:
    """A project with no intake yet: a concept a person validated starts from the need as it arrived."""
    need = project.read("need.json")
    if not need:
        return {"state": "failed", "stage": 1, "why": "no intake yet: run `factory intake` with a source",
                "history": history}
    from kernel.intake import intake

    # The need is text from outside (a signal): never a path to read (literal=True).
    intake(project, need["text"], model=model, requested_by=need.get("requested_by"), literal=True)
    history.append("intake from the validated need")
    return AGAIN


def _shape(project, model, history: list) -> dict | str | None:
    """Intake, spec and contract: whatever the project still lacks of them."""
    meta = project.meta
    again = _intake_again(project, model, history)
    if again is not None:
        return again
    if not project.path("source.json").exists() and meta.get("source_kind") != "adopted":
        return _first_intake(project, model, history)
    if not project.path("spec.json").exists():
        return _spec(project, model, history)
    late = [q["card"] for q in blocking_open(project) if q.get("card")] if not meta.get("built") else []
    if late:    # asked after the spec (material added later): nothing is built past a blocking question
        return _waiting(2, late, "blocking questions are open: answer them, then go back to the spec to write it "
                                 "again with the answers, or go on with the spec as it is") | {"history": history}
    if not project.path("contract.json").exists() or meta.get("contract_revision") is None:
        return _contract(project, model, history)
    return None


def _spec(project, model, history: list) -> dict | str:
    """The spec, once no blocking question is open (a send-back waits for the questions it names)."""
    open_blocking = blocking_open(project)
    if open_blocking:
        return _waiting(2, [q["card"] for q in open_blocking if q.get("card")],
                        "blocking questions are open") | {"history": history}
    try:
        make_spec(project, model=model)
    except SendBack as exc:
        return _waiting(2, [q["card"] for q in exc.questions], "send-back") | {"history": history}
    history.append("spec")
    return AGAIN


def _contract(project, model, history: list) -> dict | str:
    """The plan's approval, where it needs one, then the contract and its holdouts."""
    from kernel.go_ahead import gate as look_gate  # explore and demo: a person's go-ahead on the spec, once
    from kernel.plan import gate as plan_gate

    waiting = plan_gate(project, model=model) or look_gate(project)
    if waiting:
        return _waiting(4, waiting["waiting_on"], waiting["why"]) | {"history": history}
    compile_project(project)
    try:
        author_holdouts(project, model=model)
    except Exception as exc:  # holdouts are a separate custody; their absence is recorded, not hidden
        project.log("holdouts_not_authored", {"error": str(exc)})
    history.append("compile")
    return AGAIN


def _gatekeep(project, canon: Canon, history: list) -> dict | None:
    """Escalations a person decided are carried out; an open one or a stop holds the run."""
    from kernel.dispatch import resolve_escalations

    if resolve_escalations(project):
        history.append("escalations resolved")
    if project.meta.get("halted"):
        return {"state": "failed", "stage": 5, "why": "a person stopped the build", "history": history}
    escalations = canon.cards(kind="escalation")
    if escalations:
        return _waiting(5, [c["id"] for c in escalations], "a task did not pass its gate") | {"history": history}
    return None


def _build(project, canon: Canon, history: list, **runners) -> dict | str | None:
    """Build every task still to build, cell by cell, within the autonomy cap."""
    from kernel.autonomy import AutonomyCapped, cleared_to_build

    if project.meta.get("built"):
        return None
    try:
        cleared_to_build(project)
    except AutonomyCapped as exc:
        return _capped(project, exc, history)
    out = build(project, **runners)
    history.append({"build": out["results"]})
    if out["all_merged"]:
        return AGAIN
    escalations = canon.cards(kind="escalation")
    if escalations:
        return _waiting(5, [c["id"] for c in escalations], "a task did not pass its gate") | {"history": history}
    from kernel.autopilot import pass_stopped        # an autopilot pass a person stopped ended between tasks

    stopped = pass_stopped(project)
    if stopped is not None:
        return stopped | {"history": history}
    return {"state": "failed", "stage": 5, "why": "build stopped", "history": history}


def _deliver(project, model, canon: Canon, history: list, deliver_kwargs: dict | None) -> dict | str:
    """Within the cap: rulings first, then the holdouts nobody wrote yet, then the delivery the
    maturity decides. A ruling leads to a rebuild or a new delivery, so it waits below level 3 as
    building does; landing asks for the landing's own level."""
    from kernel.autonomy import AutonomyCapped, cleared_to_build, cleared_to_deliver
    from kernel.autopilot import delivery_hold

    try:
        from kernel.deliver import deliver
    except ImportError:
        return {"state": "done", "stage": project.meta["stage"], "why": "built; delivery module not installed",
                "history": history}
    try:
        cleared_to_build(project)
    except AutonomyCapped as exc:
        return _capped(project, exc, history)
    step = _rule(project, model, canon, history)
    if step is not None:
        return step
    try:
        cleared_to_deliver(project)
    except AutonomyCapped as exc:
        return _capped(project, exc, history)
    held = delivery_hold(project)     # an autopilot run bound to a sandbox never delivers outside it
    if held is not None:
        return held | {"history": history}
    kwargs = dict(deliver_kwargs or {})
    if project.meta.get("redeliver"):
        kwargs["new"] = True
        project.update_meta(redeliver=False)
    out = deliver(project, **kwargs)
    history.append({"deliver": out.get("state")})
    if out.get("state") == "failed" and out.get("handoff"):
        return _handoff(project, model, out, history)
    return _delivered(project, out, history)


def _rule(project: Project, model: Any, canon: Canon, history: list[Any]) -> dict[str, Any] | str | None:
    """Carry out the rulings people decided, wait on an open one, and write the holdouts the author
    never managed to write before delivery."""
    from kernel.rulings import apply_rulings

    ruled = apply_rulings(project, model=model)
    if ruled:
        history.append({"rulings": [r["verdict"] for r in ruled]})
        return AGAIN  # a product defect reopened tasks; a scenario defect asks for a new delivery
    open_rulings = canon.cards(kind="holdout_ruling")
    if open_rulings:
        return _waiting(project.meta["stage"], [c["id"] for c in open_rulings],
                        "a holdout failed: a person rules product or scenario") | {"history": history}
    try:  # a holdout the author never managed to write is written now, before delivery
        missing = author_holdouts(project, model=model, only="missing")
        if missing:
            history.append({"holdouts_authored_late": missing})
    except Exception as exc:  # the delivery records the holdouts as not measured; the error is kept
        project.log("holdouts_not_authored", {"error": str(exc), "when": "before delivery"})
    return None


def _handoff(project: Project, model: Any, out: dict[str, Any], history: list[Any]) -> dict[str, Any] | str:
    """A user validation decided fix or change: the release goes to the change loop (FR-R3-AC-2).
    Its change card (see `_handoff_card`) is carried out at once for a fix, a defect that needs no
    decision, and for a change once a business owner or product owner accepted it. A card rejected
    or deferred, or one already carried out, leaves the release failed and says why."""
    from kernel.change import apply_change

    card, handoff = _handoff_card(project, model, out)
    stage, extra = project.meta["stage"], {"history": history, "release": out.get("release")}
    decision = card.get("decision") or {}
    said = f"user validation decided {handoff['verdict']}"
    if handoff.get("applied") or decision.get("verdict") not in (None, "accept"):
        why = (f"the change loop carried it out as {card['id']}" if handoff.get("applied") else
               f"its change card {card['id']} was decided {decision['verdict']} by {decision.get('person')}")
        return {"state": "failed", "stage": stage, "why": f"{said}: {why}", **extra}
    if card["payload"]["triage"].get("needs_decision") and decision.get("verdict") != "accept":
        return _waiting(stage, [card["id"]], f"{said}: a business owner or product owner accepts its change "
                                             "card before the spec is amended") | extra
    try:
        applied = apply_change(project, card["id"], model=model)
    except ValueError as exc:  # the amendment changed nothing, or the compiler refused it
        return {"state": "failed", "stage": stage, "why": f"{said}: {card['id']} was not applied: {exc}", **extra}
    _save_handoff(project, out["release"], handoff | {"applied": True})
    history.append({"handoff": {"card": card["id"], "class": applied["class"], "changed": applied["changed"]}})
    return AGAIN


def _handoff_card(project: Project, model: Any, out: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The change card a validation's hand-off goes to, opened once: in the name, persona and words
    of the person who decided the validation, a fix as a defect and a change as a change request,
    and recorded on the release (``handoff.change``)."""
    from kernel.change import submit, triage

    canon, n = Canon(project), out["release"]
    handoff = dict((project.read(f"releases/{n}.json") or {}).get("handoff") or out["handoff"])
    if not handoff.get("change"):
        d = canon.get_card(handoff["card"])["decision"]
        text = str(d.get("reason") or "").strip() or f"Release {n} needs a {handoff['verdict']} after user validation"
        card = submit(project, persona=d["persona"], person=d["person"], text=text,
                      kind_hint="defect" if handoff["verdict"] == "fix" else "change_request")
        handoff["change"] = card["id"]
        _save_handoff(project, n, handoff)
        project.log("handoff_opened", {"release": n, "validation": handoff["card"], "card": card["id"],
                                       "verdict": handoff["verdict"], "person": d["person"]})
    card = canon.get_card(handoff["change"])
    if not card["payload"].get("triage"):
        triage(project, card["id"], model=model)
        card = canon.get_card(card["id"])
    return card, handoff


def _save_handoff(project: Project, n: int, handoff: dict[str, Any]) -> None:
    """Keep the hand-off's progress on its release record, under the delivery's lock."""
    from kernel.filelock import locked

    with locked(project.path("releases", ".deliver.lock")):
        rel = project.read(f"releases/{n}.json") or {}
        rel["handoff"] = handoff
        project.write(f"releases/{n}.json", rel)


def _delivered(project, out: dict, history: list) -> dict:
    """What the pipeline says about one delivery: done, waiting (on a card, or on open findings),
    or failed (a failing holdout opens a ruling card first)."""
    from kernel.rulings import open_ruling

    stage, extra = project.meta["stage"], {"history": history, "release": out.get("release")}
    if out.get("state") == "waiting" and out.get("blocked"):
        return _waiting(stage, [], out["waiting_on"]) | extra | {"blocked": out["blocked"]}
    if out.get("state") == "waiting":
        return _waiting(stage, [out.get("waiting_on")], "a person or IT must decide") | extra
    if out.get("state") == "failed":
        release = project.read(f"releases/{out.get('release')}.json", {}) or {}
        card = open_ruling(project, out.get("release"), release)
        if card is not None:
            return _waiting(stage, [card["id"]], "a holdout failed: a person rules product or scenario") | extra
        return {"state": "failed", "stage": stage, "why": out.get("reason") or out.get("why", "delivery failed"),
                **extra}
    return {"state": "done", "stage": stage, "env": out.get("env"), **extra}


def _carry_out_decisions(project: Project, history: list[Any]) -> None:
    """Escalations a person decided (retry, accept as it is, stop) are carried out at once."""
    from kernel.dispatch import resolve_escalations

    if resolve_escalations(project):
        history.append("escalations resolved")


def _apply_accepted(project: Project, model: Any, history: list[Any]) -> None:
    """Every change card a person accepted and nothing has carried out yet (an assessment's finding, a change filed
    in the cockpit or by an agent) goes into the spec and the contract now: accepting it is the decision, so the
    person never needs a further step to put it under way. One the compiler refuses stays open, with why."""
    from kernel.change import apply_change

    done = {r["event"]["payload"].get("card") for r in project.ledger().of_kind("change_applied")}
    for card in Canon(project).cards(state=None, kind="change"):
        if (card.get("decision") or {}).get("verdict") != "accept" or card["id"] in done:
            continue
        try:
            applied = apply_change(project, card["id"], model=model)
        except ValueError as exc:      # it changed nothing, or the compiler refused it: said, not dropped
            history.append({"change_not_applied": {"card": card["id"], "why": str(exc)}})
            continue
        history.append({"change_applied": {"card": card["id"], "class": applied["class"], "changed": applied["changed"]}})


# -- adopted solutions ------------------------------------------------------------------------------

def adopted_state(project: Project) -> dict | None:
    """What an adopted solution waits for while no change is under way, by its intent. None for a
    project that was not adopted, and for an adopted one once a change was applied to it: from
    then on it goes round the normal loop."""
    meta = project.meta
    if meta.get("source_kind") != "adopted" or project.ledger().of_kind("change_applied"):
        return None
    intent = meta.get("intent") or "maintain"
    if intent == "monitor":
        probe = last_probe(project)
        return {"state": "monitoring", "stage": meta.get("stage"), "intent": intent, "probe": probe,
                "waiting_on": [c["id"] for c in Canon(project).cards(kind="incident")],
                "why": "adopted to monitor: the factory probes the running service and watches the upstream; "
                       f"the last probe: {probe['verdict']}" + (f" ({probe['reason']})" if probe.get("reason") else "")}
    return {"state": "waiting", "stage": meta.get("stage"), "intent": intent, "waiting_for": list(ADOPTED_WAITS_FOR),
            "waiting_on": [c["id"] for c in Canon(project).cards()],
            "why": f"adopted to {intent}: no change is under way. It waits for a change (filed, triaged and applied "
                   "through the change loop), a workspace submission judged by the same gate, or a person's "
                   "decision on an open card"}


def last_probe(project: Project) -> dict:
    """The last probe of an adopted service as `ops/probes.jsonl` keeps it, or why there is none."""
    adopted = project.read("adopted.json") or {}
    path = project.path("ops", "probes.jsonl")
    lines = [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []
    if not lines:
        why = "no probe has run yet" if adopted.get("base_url") else \
            "no base_url was given at adoption: only the upstream is watched"
        return {"verdict": "not measured", "reason": why, "base_url": adopted.get("base_url")}
    last = json.loads(lines[-1])
    out = {k: last.get(k) for k in ("verdict", "at", "base_url", "checks", "failed")}
    if out["verdict"] == "failed":  # the probe's incident card is kept beside the log, per release and environment
        out["incident"] = ((project.read("ops/incidents.json") or {}).get("adopted:production") or {}).get("card")
    return out
