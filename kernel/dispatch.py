"""Stage 5: each contract task becomes an envelope, a Gnomon cell in a lane, and a gate.

The loop for one task:
1. Lease a lane and check out a fresh branch from the product's main.
2. Write the envelope: the requirement, the visible criteria, the scope and the rules. Holdouts
   are never in it (FR-O3).
3. Run `gnomon task --role builder` in the lane. Gnomon enforces the scope and the shell
   rules.
4. Commit what the cell left, and judge it at that revision (gate.py).
5. If it is warranted and permitted, push it to main. Otherwise repair, for at most
   ``max_rounds`` rounds, with every objection carried into the next envelope. After that,
   an escalation card keeps the objections (FR-G8).

An apparatus failure, where the harness broke rather than the work, is retried once as a
reflex. It never counts as a verdict on the work (FR-C6).
"""

from __future__ import annotations

from typing import Any

from kernel.canon import Canon
from kernel.gate import judge, visible_criteria
from kernel.lanes import Lanes
from kernel.model import ModelError, run_gnomon_task

AUTONOMY = {
    # Who gives the "permitted" signal for merging a warranted task into the product's main
    # (FR-G1). At every maturity a task merge is permitted by policy. The human gates sit at
    # validation and deployment, where the maturity decides them.
    "explore": "policy:auto-merge-warranted",
    "demo": "policy:auto-merge-warranted",
    "pilot": "policy:auto-merge-warranted",
    "production": "policy:auto-merge-warranted",
}

STACK_NOTES = """The service is `app/server.py` (do not edit it). Register behaviour in `app/routes.py` or
modules it imports:

    from app.server import route, load_data, save_data

    @route("POST", "/items")
    def create_item(req):          # req.body (parsed JSON), req.params, req.query, req.headers
        items = load_data("items", [])
        items.append(req.body)
        save_data("items", items)
        return 201, req.body       # dict or list -> JSON; str -> HTML

Tests import `app.routes` and call `handle(method, path, body)` from `app.server`, which returns
(status, payload, content_type). Each test run gets its own DATA_DIR (tests/__init__.py).

Screens: read `factory/DESIGN.md` before building any page. Build every page with `page()` and the
classes in `app/static/product.css`, and pass every value through `esc()`. Every list needs an
empty state."""


def envelope(project, contract: dict, task_id: str, *, base: str, round_no: int = 0,
             objections=()) -> str:
    task = next(t for t in contract["tasks"] if t["id"] == task_id)
    crit = {c["id"]: c for r in contract["requirements"] for c in r["acceptance"]}
    req_ids = sorted({cid.rsplit("-AC-", 1)[0] for cid in task["criteria"]})
    reqs = {r["id"]: r for r in contract["requirements"]}
    visible = visible_criteria(contract, task_id)
    lines = [f"# Envelope {task_id}" + (f", repair round {round_no}" if round_no else ""), "",
             f"Product: {project.meta['title']} (maturity {project.meta['maturity']}). "
             f"Contract {contract['revision'][:19]}. Base revision {base[:12]}.", "",
             "Do this with your tools, now. Your answer is judged by the files you leave and by checks "
             "the factory runs itself after you finish.", "", "## Goal", ""]
    for rid in req_ids:
        lines.append(f"- **{rid}**: {reqs[rid]['statement']}")
    lines += ["", "## Acceptance criteria you must meet, each with a test named by its id", ""]
    for cid in visible:
        c = crit[cid]
        lines.append(f"- **{cid}**: given {c['given']}; when {c['when']}; then {c['then']}")
    hidden = [cid for cid in task["criteria"] if cid not in visible]
    if hidden:
        lines += ["", f"{len(hidden)} more criteria for this requirement are checked end to end against the running "
                  "service by the factory. Build the requirement as stated, not only the tests above."]
    from kernel.spec import render_interface

    lines += ["", "## The product's HTTP interface (fixed by the spec: use exactly these paths)", "",
              render_interface(project.read("spec.json") or {})]
    lines += ["", "## Scope", "", "Write only: " + ", ".join(task.get("scope", {}).get("write", [])) + ".",
              "", "## How the product is built", "", STACK_NOTES, "",
              "## Rules", "",
              "- Write each criterion's test first, named `test_<ID with hyphens as underscores>_...`, "
              "and run it: it must fail before your code exists.",
              "- Then make it pass. Run `python3 -m unittest discover -s tests` and keep every test passing.",
              "- Python 3 standard library only."]
    if objections:
        lines += ["", "## Objections from the last round: each must be fixed", ""]
        lines += [f"- {o}" for o in objections]
    lines += ["", "## Report", "", "What you changed, the tests for each criterion, the check you ran, and "
              "anything you could not check."]
    return "\n".join(lines) + "\n"


def _tasks_state(project) -> dict:
    return project.read("tasks.json", {}) or {}


def _set_task(project, task_id: str, **changes) -> dict:
    state = _tasks_state(project)
    state.setdefault(task_id, {"status": "pending", "rounds": []}).update(changes)
    project.write("tasks.json", state)
    return state[task_id]


def _cell_summary(record: dict) -> dict:
    esc = record.get("escalation") or {}
    return {k: record.get(k) for k in ("code", "bucket", "stop_reason", "tool_steps", "model", "verify")} | {
        "escalated": bool(esc), "final_model": esc.get("final_model") or record.get("model"),
        "surface_hash": (record.get("trust") or {}).get("surface_hash") or record.get("surface_hash")}


def ingest_latest_run(project, lane_path, started: float, *, task: str, round_no: int):
    """Ingest the Gnomon run that just finished in a lane: its record and its re-verified audit
    trail become one `gnomon_run` ledger event (FR-C2)."""
    import json as _json
    from pathlib import Path as _Path

    from adapters.gnomon_ingest import find_trail, ingest

    audit = _Path(lane_path) / ".gnomon-audit"
    if not audit.exists():
        return None
    recent = [p for p in audit.glob("task-*.record.json") if p.stat().st_mtime >= started - 1]
    if not recent:
        return None
    path = max(recent, key=lambda p: p.stat().st_mtime)
    try:
        record = _json.loads(path.read_text(encoding="utf-8"))
        return ingest(project, record, find_trail(audit, record), task=task, round_no=round_no)
    except Exception as exc:  # an unknown native value is reported, never guessed (FR-C5-AC-2)
        project.log("gnomon_run_not_ingested", {"task": task, "round": round_no, "record": path.name,
                                                 "error": f"{type(exc).__name__}: {exc}"})
        return None


def gate_record(task: str, round_no: int, result, *, author: dict | None = None, **extra) -> dict:
    """The ledger payload of one gate verdict. A builder cell's and a person's workspace share it;
    a person's names them as its author."""
    record = {"task": task, "round": round_no, "head": result.head, "verdict": result.verdict,
              "signals": {s.name: s.verdict for s in result.signals}, "objections": result.objections}
    if author is not None:
        record["author"] = author
    return record | extra


def build_task(project, task_id: str, *, lanes: Lanes | None = None, max_rounds: int = 2,
               cell_runner=None, verifier_runner=None, deadline: int = 1500, lane_wait: float = 3600,
               reflex_backoff: tuple = (30, 120)) -> dict:
    """Build one task. ``cell_runner(lane_path, prompt) -> record`` replaces gnomon in tests."""
    contract = project.read("contract.json")
    lanes = lanes or Lanes()
    canon = Canon(project)
    repo = project.path("repo.git")
    run_cell = cell_runner or (lambda path, prompt: run_gnomon_task(
        path, prompt, role="builder", timeout=deadline + 600, deadline=deadline))
    _set_task(project, task_id, status="building")
    with lanes.lease(f"{project.pid}:{task_id}", wait=lane_wait) as lane:
        base = lane.checkout(repo, branch=f"cell/{task_id}")
        objections: list[str] = []
        rounds: list[dict[str, Any]] = []
        result = None
        for round_no in range(max_rounds + 1):
            from kernel.safestop import paused, stop_here

            if round_no and paused(project):  # a safe point: between repair rounds (FR-J3)
                stop_here(project, where=f"{task_id} before round {round_no}")
                _set_task(project, task_id, status="pending", rounds=rounds)
                return {"status": "paused", "rounds": rounds}
            prompt = envelope(project, contract, task_id, base=base, round_no=round_no, objections=objections)
            record: dict[str, Any] = {}  # the loop below runs at least once and sets it
            attempts = 0
            # Reflex (FR-J2, FR-C6): an apparatus failure, such as an endpoint error, is the harness or
            # the provider failing, not the work. Retry it with growing pauses before asking anyone.
            while attempts < 1 + len(reflex_backoff):
                attempts += 1
                started = __import__("time").time()
                try:
                    record = run_cell(lane.path, prompt)
                except ModelError as exc:
                    record = {"bucket": "apparatus_failure", "stop_reason": str(exc)}
                if cell_runner is None:
                    ingest_latest_run(project, lane.path, started, task=task_id, round_no=round_no)
                if record.get("bucket") != "apparatus_failure":
                    break
                if attempts > len(reflex_backoff):
                    break
                pause = reflex_backoff[attempts - 1]
                project.log("reflex_retry", {"task": task_id, "round": round_no, "why": record.get("stop_reason"),
                                             "attempt": attempts, "pause_seconds": pause})
                __import__("time").sleep(pause)
            head = lane.commit_all(f"{task_id} round {round_no}: cell work\n\nEnvelope for {task_id}, "
                                   f"contract {contract['revision'][:19]}, base {base[:12]}.")
            cell = _cell_summary(record)
            project.log("cell_ran", {"task": task_id, "round": round_no, "head": head, **cell})
            if record.get("bucket") == "apparatus_failure":
                rounds.append({"round": round_no, "cell": cell, "gate": None})
                objections = [f"the harness failed {attempts} times (an apparatus failure, not the work): {record.get('stop_reason')}"]
                break
            result = judge(lane.path, contract, task_id, base, head, verifier_runner=verifier_runner)
            project.log("gate", gate_record(task_id, round_no, result))
            rounds.append({"round": round_no, "cell": cell, "gate": result.to_dict()})
            if result.warranted:
                break
            objections = result.objections
        if result is not None and result.warranted:
            permitted_by = AUTONOMY[project.meta["maturity"]]
            lane.push(f"cell/{task_id}", "main")
            project.log("merged", {"task": task_id, "revision": result.head, "warranted": result.verdict,
                                   "permitted_by": permitted_by})
            return _set_task(project, task_id, status="merged", revision=result.head, rounds=rounds,
                             permitted_by=permitted_by)
        try:  # keep the cell's work in the product repository, so a person can accept it as it is
            lane.push(f"cell/{task_id}")
        except RuntimeError as exc:
            project.log("escalated_branch_not_kept", {"task": task_id, "error": str(exc)})
        card = canon.card("escalation", f"{task_id} did not pass its gate after {len(rounds)} round(s)",
                          body="\n".join(f"- {o}" for o in objections),
                          refs={"task": task_id, "requirements": sorted({c.rsplit('-AC-', 1)[0]
                                                                          for c in next(t for t in contract['tasks']
                                                                                        if t['id'] == task_id)['criteria']})},
                          payload={"objections": objections, "branch": f"cell/{task_id}"}, blocking=True)
        project.log("escalated", {"task": task_id, "card": card["id"], "objections": objections})
        return _set_task(project, task_id, status="escalated", card=card["id"], rounds=rounds)


def resolve_escalations(project) -> list:
    """Carry out what a person decided on each escalation card:
    - **retry** reopens the task for new rounds;
    - **accept as is** merges the cell's branch with the person as the permitted signal, the
      gate's verdict kept beside it, unwarranted;
    - **stop** halts the task and the project's build."""
    import tempfile
    from pathlib import Path as _Path

    from kernel.lanes import GIT_ID, _git

    canon, state, done = Canon(project), _tasks_state(project), []
    for card in canon.cards(state="decided", kind="escalation"):
        task = card["refs"].get("task")
        if not task or state.get(task, {}).get("escalation_resolved") == card["id"]:
            continue
        d = card["decision"]
        if d["verdict"] == "retry":
            _set_task(project, task, status="pending", rounds=[], escalation_resolved=card["id"])
        elif d["verdict"] == "accept_as_is":
            with tempfile.TemporaryDirectory(prefix="gf-accept-") as tmp:
                _git(_Path(tmp), "clone", "-q", str(project.path("repo.git")), "w")
                work = _Path(tmp) / "w"
                _git(work, *GIT_ID, "merge", "--no-ff", "-q", f"origin/{card['payload']['branch']}",
                     "-m", f"Accept {task} as it is: {d['person']} ({d['persona']}) on {card['id']}")
                _git(work, "push", "-q", "origin", "main")
                revision = _git(work, "rev-parse", "HEAD")
            project.log("merged", {"task": task, "revision": revision, "warranted": "not warranted",
                                   "permitted_by": f"person:{d['person']} ({d['persona']}) on {card['id']}",
                                   "objections": card["payload"].get("objections", [])})
            _set_task(project, task, status="merged", revision=revision, accepted_as_is_by=d["person"],
                      escalation_resolved=card["id"])
        elif d["verdict"] == "stop":
            _set_task(project, task, status="stopped", escalation_resolved=card["id"], stopped_by=d["person"])
            project.update_meta(halted=True)
        project.log("escalation_resolved", {"card": card["id"], "task": task, "verdict": d["verdict"],
                                            "person": d["person"]})
        done.append(card["id"])
    return done


def ready_tasks(project) -> list:
    contract, state = project.read("contract.json"), _tasks_state(project)
    done = {t for t, s in state.items() if s.get("status") == "merged"}
    out = []
    for t in contract["tasks"]:
        if t["id"] in done or state.get(t["id"], {}).get("status") in ("escalated", "stopped"):
            continue
        if all(d in done for d in t.get("depends_on", [])):
            out.append(t["id"])
    return out


def build(project, **kwargs) -> dict:
    """Build every task in dependency order. Stop at the first escalation: later tasks build on it."""
    from kernel.safestop import paused, stop_here

    results = {}
    while True:
        ready = ready_tasks(project)
        if not ready:
            break
        if paused(project):  # a safe point: between tasks (FR-J3)
            stop_here(project, where=f"before {ready[0]}")
            break
        outcome = build_task(project, ready[0], **kwargs)
        results[ready[0]] = outcome["status"]
        if outcome["status"] != "merged":
            break
    state = _tasks_state(project)
    contract = project.read("contract.json")
    all_merged = all(state.get(t["id"], {}).get("status") == "merged" for t in contract["tasks"])
    if all_merged:
        project.update_meta(stage=6 if project.meta["maturity"] in ("pilot", "production") else 5, built=True)
    project.log("build_round", {"results": results, "all_merged": all_merged})
    return {"results": results, "all_merged": all_merged}
