"""Autopilot in a sandbox (D-0017): a person lets Rihmasto run on its own, for a while, in a test sandbox.

    rihmasto autopilot start <pid> --until 8h --delegate question,approval,escalation --person Aino --persona developer
    rihmasto autopilot run <pid>        more passes of a running autopilot, after a person decided what it waited on
    rihmasto autopilot status [<pid>]
    rihmasto autopilot stop <pid> --person Aino --persona developer [--reason "..."]
    rihmasto autopilot relay SUB-001 --sandbox | --off --person Ilkka --persona it     IT marks a sandbox receiver

Starting a run delegates the named card kinds to the factory's rules until ``--until`` (kernel/delegation.py),
in the starting person's name, and records the run (``autopilot.json`` in the project, and the ledger). Then
the pipeline runs pass after pass until it needs a person, is done, fails, or the time is up. A run is bound
to a sandbox while it holds:

- it delivers only where the project lands in a sandbox: the built-in local preview, or a road IT marked
  ``"sandbox": true`` for a preview or demo environment (``kernel.roads.is_sandbox``). A delivery anywhere
  else (staging, production, a road not marked) waits for a person (``delivery_hold``, which the pipeline
  asks before it delivers);
- the relay sends none of the project's events to a subscription IT has not marked as a sandbox receiver:
  they wait, in order, and go once a person stops the run (``outbound_hold``, asked by kernel/relay.py);
- a write through a connector waits for a person; reads stay allowed (``write_hold``, for the connector
  path to ask before a write tool runs: connectors are modelled and not yet called, D-0015).

When ``--until`` passes the delegation ends and no pass runs; the sandbox still holds until a person stops
the run, because only a person releases what the run held back. Stopping revokes the delegation at once.
A pass the autopilot started stays bound to its sandbox to its end, even when a person stops the run while
it is under way: it delivers nothing, writes through no connector, and ends at its next safe point (between
pipeline steps or between tasks; a cell already working is not cut off mid-step, FR-J3), so the job that
runs it ends there too (``pass_stopped``). Only a pass a person runs afterwards may deliver.
Every start, pass, hold and stop is in the project's ledger with who asked, who delegated and the sandbox.
``posture_preset`` is the hook kernel/posture.py calls to offer an "autopilot sandbox" posture.
"""

from __future__ import annotations

import contextvars
import datetime as dt
from typing import Any

from kernel.canon import DecisionRefused
from kernel.delegation import (
    DEFAULT_RULE,
    MAX_DAYS,
    RULES,
    decided_under,
    declined_under,
    delegations,
    grant,
    revoke,
    stamp,
    when,
)
from kernel.people import PERSONAS, is_person
from kernel.safestop import MAY_PAUSE
from kernel.store import Project, updating_json

FILE = "autopilot.json"
MAY_RUN = MAY_PAUSE          # who may start or stop one: the personas who may pause and resume a project
MAX_PASSES = 20              # pipeline passes in one `start` or `run`
KEPT_PASSES = 30             # passes the run record keeps; the ledger keeps every one
SANDBOX_ROAD = "local-preview"
# The pass this process runs for an autopilot: (project id, run id), set by ``run`` around each pass. A
# person stopping the run in another process cannot end this process's pass; the pass reads this and holds.
_PASS: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar("autopilot_pass", default=None)


# -- where a run may deliver -----------------------------------------------------------------------

def sandbox_of(project: Project) -> dict[str, Any]:
    """Where the project lands and whether that is a sandbox: the environment its maturity lands in,
    the road named for it, and why it is (or is not) one."""
    from kernel.deliver import LANDING
    from kernel.roads import SANDBOX_ENVS, PavedRoads, is_sandbox

    env = LANDING.get(str(project.meta.get("maturity")), "production")
    roads = PavedRoads.load(project.factory)
    name = roads.name_for(project, env)
    ok = is_sandbox(roads.roads.get(name) if name else None, env)
    if ok:
        why = f"{env} on {name}, a road marked as a sandbox"
    elif env not in SANDBOX_ENVS:
        why = f"the project lands in {env}, which is never a sandbox"
    else:
        why = f"{env} on {name or 'no road yet'}, which IT has not marked as a sandbox"
    return {"env": env, "road": name, "sandbox": ok, "why": why}


# -- runs ------------------------------------------------------------------------------------------

def _runs(project: Project) -> list[dict[str, Any]]:
    return list((project.read(FILE, {}) or {}).get("runs") or [])


def state_of(run: dict[str, Any], now: dt.datetime) -> str:
    """running (its delegation in force), expired (its time is up; the sandbox holds until a person
    stops it) or stopped."""
    if run.get("stopped"):
        return "stopped"
    return "expired" if when(run["until"]) <= now else "running"


def holding(project: Project) -> dict[str, Any] | None:
    """The run that binds the project to its sandbox now (running or expired, not stopped), or None."""
    runs = _runs(project)
    return runs[-1] if runs and not runs[-1].get("stopped") else None


def _signer(person: str, persona: str, verb: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a named person {verb}s an autopilot")
    if persona not in PERSONAS or persona not in MAY_RUN:
        raise DecisionRefused(f"a {persona} may not {verb} an autopilot (may: {', '.join(MAY_RUN)})")


def start(project: Project, *, until: object, kinds: list[str], person: str, persona: str,
          rules: dict[str, str] | None = None, reason: str = "") -> dict[str, Any]:
    """Arm an autopilot run: delegate ``kinds`` until ``until`` and bind the project to its sandbox."""
    from kernel.safestop import paused

    _signer(person, persona, "start")
    if project.pid.startswith("_"):
        raise DecisionRefused("the factory's own canon has no pipeline to run")
    if paused(project):
        raise DecisionRefused(f"{project.pid} is paused: a person resumes it before an autopilot starts")
    held = holding(project)
    if held is not None:
        raise DecisionRefused(f"{held['id']} still holds {project.pid}: stop it before a new run starts")
    rid = f"AP-{len(_runs(project)) + 1:03d}"
    d = grant(project, kinds, person=person, persona=persona, until=until, rules=rules,
              reason=reason or f"autopilot {rid}", run=rid)
    run = {"id": rid, "person": person, "persona": persona, "at": d["at"], "until": d["until"],
           "delegation": d["id"], "kinds": d["kinds"], "rules": d["rules"], "reason": d["reason"],
           "sandbox": sandbox_of(project), "passes": [], "stopped": None,
           **({"identity": d["identity"]} if d.get("identity") else {})}
    with updating_json(project.path(FILE), {}) as doc:
        doc.setdefault("runs", []).append(run)
    project.log("autopilot_started", {k: run[k] for k in ("id", "delegation", "person", "persona", "until", "kinds",
                                                          "rules", "sandbox", "reason")})
    return view(project, run)


def stop(project: Project, *, person: str, persona: str, reason: str = "") -> dict[str, Any]:
    """A person stops the run: its delegation is revoked at once and what it held back is released."""
    from kernel.access import require

    _signer(person, persona, "stop")
    held = holding(project)
    if held is None:
        raise DecisionRefused(f"no autopilot holds {project.pid}")
    require(project, person, persona)
    now = project.factory.clock.now()
    live = next((d for d in delegations(project) if d["id"] == held["delegation"]), {})
    if live.get("state") == "active":
        revoke(project, held["delegation"], person=person, persona=persona, any_persona=True,
               reason=f"autopilot {held['id']} stopped" + (f": {reason}" if reason else ""))
    with updating_json(project.path(FILE), {}) as doc:
        run = doc["runs"][-1]
        run["stopped"] = {"by": person, "persona": persona, "at": stamp(now),
                          "reason": str(reason or "").strip()[:2000], "was": state_of(run, now)}
    project.log("autopilot_stopped", {"id": run["id"], "delegation": run["delegation"], "by": person,
                                      "persona": persona, "reason": run["stopped"]["reason"],
                                      "was": run["stopped"]["was"]})
    return view(project, run)


def view(project: Project, run: dict[str, Any]) -> dict[str, Any]:
    now = project.factory.clock.now()
    return {**run, "state": state_of(run, now), "decided": decided_under(project, run["delegation"]),
            "declined": declined_under(project, run["delegation"]),
            "rule_text": {k: RULES[k].get(r, "") for k, r in run.get("rules", {}).items()}}


def status(project: Project) -> dict[str, Any]:
    """The run that holds the project (or its last one), its sandbox, and every delegation."""
    runs = _runs(project)
    return {"project": project.pid, "run": view(project, runs[-1]) if runs else None,
            "holding": holding(project) is not None, "sandbox": sandbox_of(project),
            "delegations": delegations(project), "runs": len(runs)}


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    delegated = [d for h in result.get("history") or [] if isinstance(h, dict) for d in h.get("delegated", [])]
    return {"state": result.get("state"), "stage": result.get("stage"), "why": result.get("why"),
            "waiting_on": result.get("waiting_on"), "delegated": delegated}


def run(project: Project, *, model: Any, passes: int = MAX_PASSES, **advance_kwargs: Any) -> dict[str, Any]:
    """Run pipeline passes while the autopilot is running, until a pass stops short of progress: the
    project waits for a person, is done, fails, is capped or paused, or the time is up."""
    from kernel.pipeline import advance

    done: list[dict[str, Any]] = []
    ended = "the passes this call may run were used"
    for _ in range(max(1, int(passes))):
        held = holding(project)
        state = state_of(held, project.factory.clock.now()) if held is not None else None
        if held is None or state != "running":
            ended = "no autopilot runs" if held is None else f"{held['id']} is {state}"
            break
        token = _PASS.set((project.pid, held["id"]))
        try:
            result = advance(project, model=model, **advance_kwargs)
        finally:
            _PASS.reset(token)
        summary = _summary(result) | {"at": project.factory.clock.stamp()}
        done.append(summary)
        project.log("autopilot_pass", {"run": held["id"], **summary})
        if summary["state"] != "progress":
            ended = summary["why"] or summary["state"]
            break
    if done:
        with updating_json(project.path(FILE), {}) as doc:
            last = doc["runs"][-1]
            last["passes"] = (last.get("passes") or []) + done
            del last["passes"][:-KEPT_PASSES]
    return {"project": project.pid, "passes": done, "ended": ended,
            "state": done[-1]["state"] if done else None, "run": status(project)["run"]}


# -- what a run holds back ---------------------------------------------------------------------------

def _held_once(project: Project, held: dict[str, Any], what: str, why: str) -> None:
    seen = any(r["event"]["payload"].get("run") == held["id"] and r["event"]["payload"].get("what") == what
               for r in project.ledger().of_kind("autopilot_held"))
    if not seen:
        project.log("autopilot_held", {"run": held["id"], "what": what, "why": why})


def _this_pass(project: Project) -> dict[str, Any] | None:
    """The run whose pass this process is running on ``project`` (stopped or not), or None."""
    mine = _PASS.get()
    if mine is None or mine[0] != project.pid:
        return None
    return next((r for r in _runs(project) if r["id"] == mine[1]), None)


def _bound(project: Project) -> dict[str, Any] | None:
    """The run that binds what happens now: this process's autopilot pass (even after a person stopped
    its run: a pass the autopilot started never leaves the sandbox), else the run that holds the project."""
    return _this_pass(project) or holding(project)


def pass_stopped(project: Project) -> dict[str, Any] | None:
    """The state an autopilot pass ends in at a safe point once a person stopped its run (the pipeline
    asks between steps, kernel/dispatch.py between tasks), on record once; None to go on, and always None
    for a pass a person runs."""
    run_ = _this_pass(project)
    if run_ is None or not run_.get("stopped"):
        return None
    by = run_["stopped"]
    why = (f"autopilot {run_['id']} was stopped by {by['by']} ({by['persona']}) while this pass ran: the pass ends "
           "here, at a safe point, and a person runs the project from now on")
    _held_once(project, run_, "pass:stopped", why)
    return {"state": "stopped", "stage": project.meta.get("stage"), "waiting_on": [], "why": why,
            "sandbox": sandbox_of(project) | {"run": run_["id"]}}


def delivery_hold(project: Project) -> dict[str, Any] | None:
    """What the pipeline returns instead of delivering outside the sandbox while a run holds the project
    (a waiting state with no card: a person stops the run and delivers); None when it may deliver. A pass
    the autopilot started whose run a person stopped meanwhile delivers nowhere: that person delivers."""
    held = _bound(project)
    if held is None:
        return None
    if held.get("stopped"):
        why = (f"autopilot {held['id']} was stopped by {held['stopped']['by']} while this pass ran, and a pass an "
               "autopilot started never delivers once it is stopped: a person runs the project to deliver")
        _held_once(project, held, "delivery:after_stop", why)
        return {"state": "stopped", "stage": project.meta.get("stage"), "waiting_on": [], "why": why,
                "sandbox": sandbox_of(project) | {"run": held["id"]}}
    box = sandbox_of(project)
    if box["sandbox"]:
        return None
    why = (f"autopilot {held['id']} is bound to a sandbox, and delivering would leave it ({box['why']}): "
           "a person stops the autopilot and delivers")
    _held_once(project, held, f"delivery:{box['env']}", why)
    return {"state": "waiting", "stage": project.meta.get("stage"), "waiting_on": [], "why": why,
            "sandbox": box | {"run": held["id"]}}


def outbound_hold(project: Project, subscription: dict[str, Any]) -> str | None:
    """Why the relay holds this project's events from ``subscription`` (kernel/relay.py), or None: while a
    run holds the project, only a subscription IT marked ``"sandbox": true`` receives them."""
    held = _bound(project)
    if held is None or subscription.get("sandbox") is True:
        return None
    return (f"autopilot {held['id']} binds {project.pid} to a sandbox: {subscription.get('id')} is not a sandbox "
            "receiver, so its events wait until a person stops the run")


def write_hold(project: Project, system: str, tool: str) -> str | None:
    """The hook a connector's write asks first (D-0015: Gnomon's integration lane, planned): while a run
    holds the project (or this is a pass it started, stopped or not), a write through any connector waits
    for a person; a read goes on. None: go on."""
    held = _bound(project)
    if held is None:
        return None
    why = f"autopilot {held['id']} keeps connectors read-only: {tool} on {system} writes, so it waits for a person"
    _held_once(project, held, f"connector:{system}:{tool}", why)
    return why


def posture_preset() -> dict[str, Any]:
    """The "autopilot sandbox" posture for kernel/posture.py to offer beside its presets: what a run binds,
    in plain words and as values a posture can apply. Nothing here applies it."""
    return {"id": "autopilot_sandbox", "label": "Autopilot in a sandbox",
            "summary": "Rihmasto runs on its own for a while, decides only the card kinds a person delegated, "
                       "delivers only to a sandbox, sends events only to sandbox receivers and writes through no "
                       "connector; a person stops it and releases what it held back.",
            "autonomy_cap": 3, "delivers_to": ["preview on the local preview road", "a preview or demo road marked "
                                               "\"sandbox\": true"],
            "delegable": {k: sorted(r) for k, r in RULES.items()}, "default_rules": dict(DEFAULT_RULE),
            "max_days": MAX_DAYS, "relay": "sandbox receivers only", "connectors": "read only",
            "start": "rihmasto autopilot start <pid> --until <time> --delegate <kinds> --person <name> --persona <p>"}
