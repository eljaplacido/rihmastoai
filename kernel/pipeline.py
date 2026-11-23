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

Each pass first carries out the decided update cards (`kernel.observations.apply_updates`), so a
trial a person approved is recorded before anything moves (FR-V2-AC-2).

An adopted solution (`rihma adopt`) had no intake. Until a change is applied to it, it says what
it waits for by its intent (FR-B1-AC-3): to monitor, `monitoring` with the last probe result; to
maintain or improve, `waiting` for a change, a workspace submission or a person. Once a change
is applied, it goes round the normal loop: build, gate and delivery.

`tick(factory)` carries out the decided concept cards and advances nothing else, for the command
line and the cockpit: a validated concept becomes a project without any project being run.
"""

from __future__ import annotations

import json

from kernel.canon import Canon
from kernel.compile import author_holdouts, compile_project
from kernel.dispatch import build
from kernel.intake import SendBack, blocking_open
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
    and running again resumes."""
    from kernel.model import ModelError

    try:
        return _advance(project, model=model, **kwargs)
    except ModelError as exc:
        project.log("apparatus_failure", {"where": "pipeline", "error": str(exc)[:300]})
        return {"state": "apparatus_failure", "stage": project.meta.get("stage"), "apparatus": True,
                "why": f"a model endpoint failed ({exc}); what was recorded stays, run again when it answers"}


def _advance(project, *, model, lanes=None, cell_runner=None, verifier_runner=None, deliver_kwargs=None,
             max_steps: int = 12) -> dict:
    history: list = []
    for _ in range(max_steps):
        _apply_updates(project, history)
        idle = adopted_state(project)
        if idle is not None:
            return idle | {"history": history}
        canon = Canon(project)
        step = _shape(project, model, history)
        if step is None:
            step = _gatekeep(project, canon, history)
        if step is None:
            step = _build(project, canon, history, lanes=lanes, cell_runner=cell_runner,
                          verifier_runner=verifier_runner)
        if step is None:
            step = _deliver(project, model, canon, history, deliver_kwargs)
        if isinstance(step, dict):
            return step
    return {"state": "progress", "stage": project.meta["stage"], "history": history}


def _apply_updates(project, history: list) -> None:
    """Record the update cards people decided since the last pass (a trial, a decline, a deferral)."""
    from kernel.observations import apply_updates

    done = apply_updates(project)
    if done:
        history.append({"updates": [{"card": u["card"], "verdict": u["verdict"]} for u in done]})


def _shape(project, model, history: list) -> dict | str | None:
    """Intake, spec and contract: whatever the project still lacks of them."""
    meta = project.meta
    if not project.path("source.json").exists() and meta.get("source_kind") != "adopted":
        need = project.read("need.json")
        if need:  # a concept a person validated: intake starts from the need as it arrived
            from kernel.intake import intake

            intake(project, need["text"], model=model, requested_by=need.get("requested_by"))
            history.append("intake from the validated need")
            return AGAIN
        return {"state": "failed", "stage": 1, "why": "no intake yet: run `factory intake` with a source",
                "history": history}
    if not project.path("spec.json").exists():
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
    if not project.path("contract.json").exists() or meta.get("contract_revision") is None:
        from kernel.plan import gate as plan_gate

        waiting = plan_gate(project, model=model)
        if waiting:
            return _waiting(4, waiting["waiting_on"], waiting["why"]) | {"history": history}
        compile_project(project)
        try:
            author_holdouts(project, model=model)
        except Exception as exc:  # holdouts are a separate custody; their absence is recorded, not hidden
            project.log("holdouts_not_authored", {"error": str(exc)})
        history.append("compile")
        return AGAIN
    return None


def _gatekeep(project, canon: Canon, history: list) -> dict | None:
    """Escalations a person decided are carried out; an open one, a stop or a pause holds the run."""
    from kernel.dispatch import resolve_escalations
    from kernel.safestop import paused

    if resolve_escalations(project):
        history.append("escalations resolved")
    if project.meta.get("halted"):
        return {"state": "failed", "stage": 5, "why": "a person stopped the build", "history": history}
    escalations = canon.cards(kind="escalation")
    if escalations:
        return _waiting(5, [c["id"] for c in escalations], "a task did not pass its gate") | {"history": history}
    if paused(project):
        pause = project.meta["pause"]
        why = f"paused by {pause.get('requested_by')}" + (f": {pause['reason']}" if pause.get("reason") else "")
        return {"state": "paused", "stage": project.meta["stage"], "history": history, "why": why,
                "stopped_at": pause.get("stopped_at")}
    return None


def _build(project, canon: Canon, history: list, **runners) -> dict | str | None:
    """Build every task still to build, cell by cell, within the autonomy cap."""
    from kernel.autonomy import AutonomyCapped, require

    if project.meta.get("built"):
        return None
    try:
        require(project, 3, "building")
    except AutonomyCapped as exc:
        return {"state": "capped", "stage": project.meta["stage"], "why": str(exc), "history": history}
    out = build(project, **runners)
    history.append({"build": out["results"]})
    if out["all_merged"]:
        return AGAIN
    escalations = canon.cards(kind="escalation")
    if escalations:
        return _waiting(5, [c["id"] for c in escalations], "a task did not pass its gate") | {"history": history}
    return {"state": "failed", "stage": 5, "why": "build stopped", "history": history}


def _deliver(project, model, canon: Canon, history: list, deliver_kwargs: dict | None) -> dict | str:
    """Rulings first, then the holdouts nobody wrote yet, then the delivery the maturity decides."""
    from kernel.autonomy import LANDING_LEVEL, AutonomyCapped, require

    try:
        from kernel.deliver import LANDING, deliver
    except ImportError:
        return {"state": "done", "stage": project.meta["stage"], "why": "built; delivery module not installed",
                "history": history}
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
    landing = LANDING[project.meta["maturity"]]
    try:
        require(project, LANDING_LEVEL.get(landing, 4), f"delivering to {landing}")
    except AutonomyCapped as exc:
        return {"state": "capped", "stage": project.meta["stage"], "why": str(exc), "history": history}
    kwargs = dict(deliver_kwargs or {})
    if project.meta.get("redeliver"):
        kwargs["new"] = True
        project.update_meta(redeliver=False)
    out = deliver(project, **kwargs)
    history.append({"deliver": out.get("state")})
    return _delivered(project, out, history)


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
