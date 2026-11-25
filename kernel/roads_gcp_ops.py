"""A Cloud Run job's life after it is rendered: its delivery steps, its executions and its rollback (FR-GCP1).

A job has no HTTP face, so delivery runs it differently from a service (kernel/deliver.py asks the road
first, `delivery_step`):

- **smoke** (in the test environment, or wherever the plan smokes): the job is executed once with
  `gcloud run jobs execute --wait`, and the execution's outcome is the check;
- **holdouts**, the production **candidate**, **shadow** and **canary**: not applicable, and the record says
  why. The deploy gate before production still holds, and IT still approves exactly the package that runs;
- **promote**: the production job gets the release's image, and its Cloud Scheduler job its schedule. The
  previous image is kept (`envs/production/previous.json`) for rollback.

`executions` reads the last executions (`gcloud run jobs executions list --format=json`); `job_probe` turns
them into a probe the operation round keeps (kernel/operate.py `probe`, and `tick`, which opens an incident
when the latest execution failed, so the relay notifies whoever subscribed to incidents). `rollback`, signed
by IT or operations, sends a service's traffic back to its previous revision, or gives a job its previous
image. Nothing reads or keeps an execution's logs.
"""

from __future__ import annotations

from typing import Any

from kernel.canon import DecisionRefused
from kernel.people import is_person
from kernel.roads import PavedRoads, RoadError, _save_slot, road_for_slot, slot_path, slot_state
from kernel.store import write_json

NOT_FOR_A_JOB = ("a scheduled job has no HTTP face: its check is the execution in the test environment, and it is "
                 "promoted by giving the production job the release's image (the previous image is kept for rollback)")
ROLLBACK_PERSONAS = ("it", "operations")


def summary(execution: Any) -> dict[str, Any]:
    """One execution as the record keeps it: its name, state, times and task counts, never its logs."""
    e = execution if isinstance(execution, dict) else {}
    status, meta = e.get("status") or {}, e.get("metadata") or {}
    done = next((c for c in status.get("conditions") or [] if isinstance(c, dict) and c.get("type") == "Completed"), {})
    state = {"True": "succeeded", "False": "failed"}.get(str(done.get("status")), "running")
    return {"name": meta.get("name"), "state": state, "started": status.get("startTime"),
            "completed": status.get("completionTime"), "succeeded": status.get("succeededCount") or 0,
            "failed": status.get("failedCount") or 0, "reason": str(done.get("message") or "")[:300] or None}


def executions(road: Any, state: dict[str, Any]) -> list[dict[str, Any]]:
    """The job's last executions, newest first, as `summary` keeps them."""
    listed = road.gcloud.json(state["package"]["rendered"]["commands"]["executions"], timeout=120) or []
    rows = [summary(e) for e in listed if isinstance(e, dict)] if isinstance(listed, list) else []
    return sorted(rows, key=lambda r: str(r.get("started") or ""), reverse=True)


def job_probe(project: Any, env: str, state: dict[str, Any], record: bool = True) -> dict[str, Any]:
    """A probe of a scheduled job: its latest finished execution passed or failed; not measured while none
    has finished or gcloud cannot be asked here. Shaped as kernel.operate.probe's, so `tick` reads it."""
    from kernel.operate import _append, _stamp

    base = {"environment": env, "slot": "current", "release": state["release"], "revision": state["revision"],
            "base_url": None, "at": _stamp(project), "scenarios": [], "workload": "job", "job": state.get("job")}
    try:
        rows = executions(road_for_slot(state, project.factory), state)
    except RoadError as exc:
        rows, why = [], f"not measured: {exc}"
    else:
        why = "not measured: no execution has finished yet"
    finished = [r for r in rows if r["state"] != "running"]
    failed = sum(1 for r in finished if r["state"] == "failed")
    latest = finished[0] if finished else None
    verdict = "not measured" if latest is None else "failed" if latest["state"] == "failed" else "passed"
    if latest is not None:
        why = (f"the latest execution {latest['name']} {latest['state']}"
               + (f": {latest['reason']}" if latest["state"] == "failed" and latest.get("reason") else ""))
    result = base | {"executions": rows[:5], "checks": len(finished), "failed": failed, "verdict": verdict,
                     "ok": verdict != "failed",
                     "health": {"ok": verdict == "passed", "url": None, "status": None,
                                "reason": None if verdict == "passed" else why}}
    if record:
        _append(project.path("ops", "probes.jsonl"), result)
    return result


# -- delivery steps ------------------------------------------------------------------------------------

def job_step(road: Any, delivery: Any, name: str, env: str) -> dict[str, Any] | None:
    """The outcome of a job's delivery step ``name`` in ``env``; None for a step delivery runs as for any road."""
    if name == "smoke":
        return _smoke(road, delivery, env)
    if name in ("holdouts", "deploy_candidate", "shadow", "canary"):
        return {"outcome": "not applicable", "native": {"why": NOT_FOR_A_JOB, "workload": "job"}}
    if name == "promote":
        return _promote(road, delivery, env)
    return None


def _smoke(road: Any, delivery: Any, env: str) -> dict[str, Any]:
    state = slot_state(delivery.project, env, "current")
    if not state:
        return {"outcome": "failed", "native": {"why": f"nothing runs in {env}"}}
    try:
        run = summary(road.gcloud.json(state["package"]["rendered"]["commands"]["execute"], timeout=7200))
    except RoadError as exc:     # gcloud exits non-zero when the execution fails: read what it recorded
        rows = executions(road, state)
        run = rows[0] if rows else summary({}) | {"state": "failed", "reason": str(exc)}
    native = {"workload": "job", "job": state.get("job"), "execution": run}
    if run["state"] != "succeeded":
        native["why"] = (f"the job's execution {run['name']} in {env} {run['state']}"
                         + (f": {run['reason']}" if run.get("reason") else ""))
        return {"outcome": "failed", "native": native}
    state["last_execution"] = run
    _save_slot(delivery.project, state)
    return {"outcome": "passed", "native": native}


def _promote(road: Any, delivery: Any, env: str) -> dict[str, Any]:
    from kernel.roads import validate_package

    previous = slot_state(delivery.project, env, "current")
    _, pkg = delivery.package(env, "current")
    problems = validate_package(pkg)
    if problems:
        return {"outcome": "failed", "native": {"problems": problems, "why": "the production package is not valid"}}
    state = road.deploy(delivery.project, pkg)
    before = {"release": previous["release"], "revision": previous["revision"],
              "image": previous.get("image")} if previous else None
    rel = delivery.rel
    rel["promoted"] = {"environment": env, "previous": before, "image": state["image"], "schedule": state["schedule"],
                       "at": delivery.now()}
    delivery.log("promoted", environment=env, previous=before, revision=rel["revision"])
    delivery.stage_to(7, f"release {rel['release']} was promoted to {env}", released=True)
    return {"outcome": "passed", "native": {"previous": before, "image": state["image"], "schedule": state["schedule"],
                                            "workload": "job"}}


# -- rollback ------------------------------------------------------------------------------------------

def rollback(project: Any, env: str, *, person: str, persona: str, reason: str, roads: Any = None) -> dict[str, Any]:
    """Go back to what ran before in ``env`` on a gcp-cloudrun road: a service's traffic to its previous
    revision, a job's previous image. Signed by IT or operations, with a reason; the release that was
    replaced becomes the previous one, so a second rollback goes forward again."""
    from kernel.operate import _append, _stamp

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a rollback is signed by a named person")
    if persona not in ROLLBACK_PERSONAS:
        raise DecisionRefused(f"a {persona} may not roll back a release: {' or '.join(ROLLBACK_PERSONAS)} may")
    cur = slot_state(project, env, "current")
    road: Any = road_for_slot(cur, PavedRoads.load(roads if roads is not None else project.factory)) if cur else None
    if cur is None or getattr(road, "kind", None) != "gcp-cloudrun":
        raise DecisionRefused(f"nothing runs in {env} on a Google Cloud road")
    prev = road.previous(project, env)
    if not prev:
        raise DecisionRefused(f"no earlier release ran in {env}: there is nothing to go back to")
    cmds = cur["package"]["rendered"]["commands"]
    if cur.get("workload") == "job":
        road.gcloud.run([prev["image"] if a == "<previous image>" else a for a in cmds["rollback_image"]], timeout=600)
    else:
        road.gcloud.run([f"{prev['revision_name']}=100" if a == "<revision>=100" else a for a in cmds["traffic_to"]],
                        timeout=600)
    write_json(slot_path(project, env, "previous"), cur)
    restored = dict(prev, started=_stamp(project), rolled_back_from=cur["release"])
    _save_slot(project, restored)
    record = {"environment": env, "from": {"release": cur["release"], "revision": cur["revision"]},
              "to": {"release": prev["release"], "revision": prev["revision"]},
              "how": "the job's previous image" if cur.get("workload") == "job" else "the previous revision's traffic",
              "person": person, "persona": persona, "reason": reason, "at": _stamp(project)}
    _append(project.path("ops", "rollbacks.jsonl"), record)
    project.log("rolled_back", {"release": cur["release"], "environment": env, "reason": reason, "person": person,
                                "persona": persona, "restored": record["to"], "how": record["how"]})
    return record
