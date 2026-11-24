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

import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel.canon import Canon
from kernel.gate import judge, visible_criteria
from kernel.lanes import GIT_ID, Lane, Lanes, _git, protected_paths
from kernel.model import ModelError, run_gnomon_task
from kernel.store import Project

# The ref that keeps the head a person is asked to accept as it is, in the product repository:
# accept as is merges exactly that commit, whatever its branch holds by then.
JUDGED_REF = "refs/rihma/judged/"
# What an earlier outcome left on a task's state, and a merge makes stale.
CLEARED_ON_MERGE = ("reopened_by", "accepted_as_is_by", "stopped_by", "author")

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
    from kernel.outputs import builder_notes
    from kernel.roads import road_facts_for_builder
    from kernel.spec import render_interface

    lines += ["", "## The product's HTTP interface (fixed by the spec: use exactly these paths)", "",
              render_interface(project.read("spec.json") or {})] + builder_notes(project, base)  # req.user, CSRF
    lines += ["", "## Scope", "", "Write only: " + ", ".join(task.get("scope", {}).get("write", [])) + ".",
              "", "## How the product is built", "", STACK_NOTES, "",
              "## The paved road's platform facts (the road owns them)", "", road_facts_for_builder(), "",
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


def _contract(project: Project) -> dict:
    """The contract a build works from. A project not compiled yet has none: say so."""
    contract = project.read("contract.json")
    if not contract:
        raise FileNotFoundError(f"{project.pid} has no contract: compile the project before building it")
    return contract


def _set_task(project: Project, task_id: str, **changes: Any) -> dict:
    state = _tasks_state(project)
    entry = state.setdefault(task_id, {"status": "pending", "rounds": []})
    if changes.get("status") == "merged":  # this merge is the task's news; an earlier one's notes go
        for key in CLEARED_ON_MERGE:
            entry.pop(key, None)
    entry.update(changes)
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

    from adapters.gnomon_ingest import find_trail, ingest

    audit = Path(lane_path) / ".gnomon-audit"
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


def _run_cell(project: Project, lane: Lane, prompt: str, run_cell: Callable[[Path, str], dict], *, task_id: str,
              round_no: int, ingest: bool, reflex_backoff: tuple) -> tuple[dict, int]:
    """Run the cell once. Reflex (FR-J2, FR-C6): an apparatus failure, such as an endpoint error,
    is the harness or the provider failing, not the work. It is retried with growing pauses before
    anyone is asked. Returns the cell's record and the attempts it took."""
    record: dict[str, Any] = {}
    attempts = 0
    while attempts < 1 + len(reflex_backoff):
        attempts += 1
        started = time.time()
        try:
            record = run_cell(lane.path, prompt)
        except ModelError as exc:
            record = {"bucket": "apparatus_failure", "stop_reason": str(exc)}
        if ingest:
            ingest_latest_run(project, lane.path, started, task=task_id, round_no=round_no)
        if record.get("bucket") != "apparatus_failure" or attempts > len(reflex_backoff):
            break
        pause = reflex_backoff[attempts - 1]
        project.log("reflex_retry", {"task": task_id, "round": round_no, "why": record.get("stop_reason"),
                                     "attempt": attempts, "pause_seconds": pause})
        time.sleep(pause)
    return record, attempts


def build_task(project, task_id: str, *, lanes: Lanes | None = None, max_rounds: int = 2,
               cell_runner=None, verifier_runner=None, deadline: int = 1500, lane_wait: float = 3600,
               reflex_backoff: tuple = (30, 120)) -> dict:
    """Build one task. ``cell_runner(lane_path, prompt) -> record`` replaces gnomon in tests."""
    from kernel.safestop import paused, stop_here

    contract = _contract(project)
    lanes = lanes or Lanes()
    run_cell = cell_runner or (lambda path, prompt: run_gnomon_task(
        path, prompt, role="builder", timeout=deadline + 600, deadline=deadline))
    _set_task(project, task_id, status="building")
    with lanes.lease(f"{project.pid}:{task_id}", wait=lane_wait) as lane:
        base = lane.checkout(project.path("repo.git"), branch=f"cell/{task_id}")
        objections: list[str] = []
        rounds: list[dict[str, Any]] = []
        result = None
        for round_no in range(max_rounds + 1):
            if round_no and paused(project):  # a safe point: between repair rounds (FR-J3)
                stop_here(project, where=f"{task_id} before round {round_no}")
                _set_task(project, task_id, status="pending", rounds=rounds)
                return {"status": "paused", "rounds": rounds}
            prompt = envelope(project, contract, task_id, base=base, round_no=round_no, objections=objections)
            record, attempts = _run_cell(project, lane, prompt, run_cell, task_id=task_id, round_no=round_no,
                                         ingest=cell_runner is None, reflex_backoff=reflex_backoff)
            head = lane.commit_all(f"{task_id} round {round_no}: cell work\n\nEnvelope for {task_id}, "
                                   f"contract {contract['revision'][:19]}, base {base[:12]}.")
            cell = _cell_summary(record)
            project.log("cell_ran", {"task": task_id, "round": round_no, "head": head, **cell})
            if record.get("bucket") == "apparatus_failure":
                rounds.append({"round": round_no, "cell": cell, "gate": None})
                objections = [f"the harness failed {attempts} times (an apparatus failure, not the work): "
                              f"{record.get('stop_reason')}"]
                break
            result = judge(lane.path, contract, task_id, base, head, verifier_runner=verifier_runner)
            project.log("gate", gate_record(task_id, round_no, result))
            rounds.append({"round": round_no, "cell": cell, "gate": result.to_dict()})
            if result.warranted:
                return _merge_cell(project, lane, task_id, result.head, result.verdict, rounds)
            objections = result.objections
        judged = result.head if result is not None else lane.head()
        return _escalate_cell(project, lane, contract, task_id, judged, objections, rounds)


def _merge_cell(project: Project, lane: Lane, task_id: str, head: str, verdict: str, rounds: list) -> dict:
    """Push a warranted head to main, permitted by the maturity's policy (FR-G1). When main moved
    while the gate ran, the push is refused: the ledger says so beside the passed gate, and the task
    goes back to pending, to be built again on the new main ("stale_main")."""
    permitted_by = AUTONOMY[project.meta["maturity"]]
    try:
        lane.push(f"cell/{task_id}", "main")
    except RuntimeError as exc:
        project.log("merge_rejected", {"task": task_id, "revision": head, "why": "main moved during the gate",
                                       "error": str(exc)})
        return _set_task(project, task_id, status="pending", rounds=rounds) | {
            "status": "stale_main", "why": "main moved during the gate"}
    project.log("merged", {"task": task_id, "revision": head, "warranted": verdict, "permitted_by": permitted_by})
    return _set_task(project, task_id, status="merged", revision=head, rounds=rounds, permitted_by=permitted_by)


def _escalate_cell(project: Project, lane: Lane, contract: dict, task_id: str, judged: str, objections: list,
                   rounds: list) -> dict:
    """Keep the cell's work in the product repository, with the head the gate judged under a ref
    of its own, so a person can accept exactly that as it is; then open the escalation card with
    every objection (FR-G8)."""
    try:
        lane.git("push", "-q", "-f", "origin", f"cell/{task_id}:refs/heads/cell/{task_id}",
                 f"{judged}:{JUDGED_REF}{judged}")
    except RuntimeError as exc:
        project.log("escalated_branch_not_kept", {"task": task_id, "error": str(exc)})
    reqs = sorted({c.rsplit("-AC-", 1)[0] for t in contract["tasks"] if t["id"] == task_id for c in t["criteria"]})
    card = Canon(project).card("escalation", f"{task_id} did not pass its gate after {len(rounds)} round(s)",
                               body="\n".join(f"- {o}" for o in objections),
                               refs={"task": task_id, "requirements": reqs},
                               payload={"objections": objections, "branch": f"cell/{task_id}", "head": judged},
                               blocking=True)
    project.log("escalated", {"task": task_id, "card": card["id"], "objections": objections})
    return _set_task(project, task_id, status="escalated", card=card["id"], rounds=rounds)


class AcceptRefused(RuntimeError):
    """Accept as is cannot be carried out: the judged head is missing, touches a protected path,
    or no longer merges into main."""


def resolve_escalations(project: Project) -> list:
    """Carry out, once, what a person decided on each escalation card (the ledger's
    `escalation_resolved` records say which were carried out):
    - **retry** reopens a builder task for new rounds; on a workspace's card it is recorded, and the
      person submits again from the workspace;
    - **accept as is** merges the head the gate judged, never what its branch holds by then, with
      the person as the permitted signal and the gate's verdict kept beside it, unwarranted. A head
      that touches a protected path, is gone, or no longer merges is not merged: a new card asks
      the person again;
    - **stop** halts the project's build (and a builder task).
    A builder card whose task merged by another path (a workspace) after the decision and before it
    was carried out is not carried out, whatever its verdict: the task keeps its merge, and a stop
    neither marks it stopped nor halts the build over a task that is done."""
    canon, done = Canon(project), []
    carried = {r["event"]["payload"].get("card") for r in project.ledger().of_kind("escalation_resolved")}
    for card in canon.cards(state="decided", kind="escalation"):
        if card["id"] in carried:
            continue
        outcome = _carry_out(project, card)
        d = card["decision"]
        project.log("escalation_resolved", {"card": card["id"], "task": card["refs"].get("task"),
                                            "verdict": d["verdict"], "person": d["person"], **outcome})
        done.append(card["id"])
    return done


def _carry_out(project: Project, card: dict) -> dict:
    """One decided escalation card, carried out; what the ledger records beside it."""
    verdict, refs = card["decision"]["verdict"], card["refs"]
    task, workspace = refs.get("task"), refs.get("workspace")
    where: dict[str, Any] = {"workspace": workspace} if workspace else {}
    if task and not workspace and _tasks_state(project).get(task, {}).get("status") == "merged":
        return {"carried_out": False, "why": f"{task} merged by another path before this decision was carried out"}
    if verdict == "stop":
        if task and not workspace:
            _set_task(project, task, status="stopped", escalation_resolved=card["id"],
                      stopped_by=card["decision"]["person"])
        project.update_meta(halted=True)
        return where
    if not workspace and not task:
        return {"carried_out": False, "why": "the card names neither a task nor a workspace"}
    if verdict == "retry":
        if workspace:
            return where | {"note": "recorded: the person submits again from the workspace"}
        _set_task(project, task, status="pending", rounds=[], escalation_resolved=card["id"])
        return where
    return where | _accept_as_is(project, card)


def _accept_as_is(project: Project, card: dict) -> dict:
    """Merge the card's judged head into main with the person as the permission (FR-G8-AC-2)."""
    d, refs, payload = card["decision"], card["refs"], card["payload"]
    task, workspace = refs.get("task"), refs.get("workspace")
    label = task or f"workspace:{workspace}"
    try:
        revision = _merge_judged(project, payload.get("head"),
                                 f"Accept {label} as it is: {d['person']} ({d['persona']}) on {card['id']}")
    except AcceptRefused as exc:
        return _ask_again(project, card, str(exc))
    record = {"task": label, "revision": revision, "warranted": "not warranted", "head": payload.get("head"),
              "permitted_by": f"person:{d['person']} ({d['persona']}) on {card['id']}",
              "objections": payload.get("objections", [])}
    if workspace:
        record |= {"workspace": workspace, "author": payload.get("author")}
    project.log("merged", record)
    if task:
        _set_task(project, task, status="merged", revision=revision, accepted_as_is_by=d["person"],
                  escalation_resolved=card["id"])
    return {"revision": revision}


def _merge_judged(project: Project, head: str | None, message: str) -> str:
    """Merge ``head`` into the product's main in a fresh clone and push it; the new main."""
    if not isinstance(head, str) or len(head) < 40 or any(c not in "0123456789abcdef" for c in head):
        raise AcceptRefused("the card names no judged head to accept")
    with tempfile.TemporaryDirectory(prefix="gf-accept-") as tmp:
        _git(Path(tmp), "clone", "-q", str(project.path("repo.git")), "w")
        work = Path(tmp) / "w"
        _git(work, "fetch", "-q", "origin", f"{JUDGED_REF}{head}", check=False)
        if _git(work, "cat-file", "-t", head, check=False) != "commit":
            raise AcceptRefused(f"the judged head {head[:12]} is not in the product repository")
        touched = protected_paths(work, "HEAD", head)
        if touched:
            raise AcceptRefused("the change touches what a cell may not: " + ", ".join(touched[:10]))
        try:
            _git(work, *GIT_ID, "merge", "--no-ff", "-q", head, "-m", message)
            _git(work, "push", "-q", "origin", "main")
        except RuntimeError as exc:
            raise AcceptRefused(f"{head[:12]} could not be merged into main: {exc}") from exc
        return _git(work, "rev-parse", "HEAD")


def _ask_again(project: Project, card: dict, why: str) -> dict:
    """Accept as is could not be carried out. Nothing merges; a new card puts the case to a
    person again, with the reason first."""
    d, refs = card["decision"], card["refs"]
    again = Canon(project).card(
        "escalation", f"{card['title']}: accept as is was not carried out",
        body=f"- accept as is by {d['person']} on {card['id']} was not carried out: {why}\n{card.get('body', '')}",
        refs=refs, payload=card["payload"] | {"accept_refused": why, "after": card["id"]}, blocking=True)
    if refs.get("task") and not refs.get("workspace"):
        _set_task(project, refs["task"], status="escalated", card=again["id"], escalation_resolved=card["id"])
    project.log("accept_refused", {"card": card["id"], "again": again["id"], "why": why})
    return {"carried_out": False, "why": why, "asked_again": again["id"]}


def ready_tasks(project: Project) -> list:
    contract, state = _contract(project), _tasks_state(project)
    done = {t for t, s in state.items() if s.get("status") == "merged"}
    out = []
    for t in contract["tasks"]:
        if t["id"] in done or state.get(t["id"], {}).get("status") in ("escalated", "stopped"):
            continue
        if all(d in done for d in t.get("depends_on", [])):
            out.append(t["id"])
    return out


def build(project: Project, **kwargs: Any) -> dict:
    """Build every task in dependency order. Stop at the first escalation: later tasks build on it.
    A task whose merge found main moved during its gate is built once more, on the new main."""
    from kernel.autopilot import pass_stopped
    from kernel.confidential import require_local
    from kernel.safestop import paused, stop_here

    require_local(project, ("builder", "verifier"), where="build")   # the cells and the verifier read the code
    contract = _contract(project)
    results: dict[str, str] = {}
    again: set[str] = set()
    while True:
        ready = ready_tasks(project)
        if not ready:
            break
        if paused(project):  # a safe point: between tasks (FR-J3)
            stop_here(project, where=f"before {ready[0]}")
            break
        if pass_stopped(project):  # an autopilot pass a person stopped ends here too (kernel/autopilot.py)
            break
        outcome = build_task(project, ready[0], **kwargs)
        results[ready[0]] = outcome["status"]
        if outcome["status"] == "stale_main" and ready[0] not in again:
            again.add(ready[0])
            continue
        if outcome["status"] != "merged":
            break
    state = _tasks_state(project)
    all_merged = all(state.get(t["id"], {}).get("status") == "merged" for t in contract["tasks"])
    if all_merged:
        project.update_meta(stage=6 if project.meta["maturity"] in ("pilot", "production") else 5, built=True)
    project.log("build_round", {"results": results, "all_merged": all_merged})
    return {"results": results, "all_merged": all_merged}
