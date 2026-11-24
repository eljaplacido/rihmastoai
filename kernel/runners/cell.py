"""A builder or verifier cell run by the runner chosen for its project (D-0019, FR-HRN1), for kernel/dispatch.py.

With Gnomon chosen for both roles (the default), nothing here runs and the build is exactly as before. With another
runner for the builder, its rounds run through that harness, each round's record names the runner, its version and
its assurance, and the gate judges the round with the glue's checks beside its own signals. With another runner for
the verifier, the review runs through that harness in a throwaway copy of the lane, read-only as far as the harness
lets a caller say so, and whatever it wrote there is dropped. Before any round runs, a runner that is missing, not the
version IT pinned, asked to sandbox where Docker is not, or of the builder's model family, refuses the task.
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Any

from kernel.gate import GateResult, visible_criteria
from kernel.model import ModelError
from kernel.runners import DEFAULT, assurance_of, label_of
from kernel.runners.base import Envelope, conventions
from kernel.runners.choice import effective, family_clash
from kernel.runners.glue import judge_after_run
from kernel.runners.harnesses import runner_for


def gnomon_info(record: dict[str, Any]) -> dict[str, Any]:
    """The runner line of a round Gnomon ran: its build from the record, in-run policy enforced by Gnomon."""
    return {"name": DEFAULT, "label": label_of(DEFAULT), "version": record.get("harness"), **assurance_of(DEFAULT)}


def runner_line(record: dict[str, Any]) -> dict[str, Any]:
    given = record.get("runner")
    return dict(given) if isinstance(given, dict) else gnomon_info(record)


def chosen(project: Any, role: str) -> dict[str, Any]:
    return effective(project.factory, project.pid, role)


def refusal(project: Any, *, builder: bool = True, verifier: bool = True) -> str | None:
    """Why this project's runners may not run now, or None. Gnomon is the kernel's own (`rihmasto doctor`)."""
    from kernel.runners.detect import detect
    from kernel.runners.sandbox import docker_status

    pair = {"builder": chosen(project, "builder"), "verifier": chosen(project, "verifier")}
    if pair["builder"]["runner"] == DEFAULT and pair["verifier"]["runner"] == DEFAULT:
        return None
    clash = family_clash(pair["builder"], pair["verifier"])
    if clash:
        return clash
    for role, use in (("builder", builder), ("verifier", verifier)):
        c = pair[role]
        if not use or c["runner"] == DEFAULT:
            continue
        why = runner_for(c["runner"], c).refusal(detect(c["runner"], c))
        if why:
            return f"the {role}'s runner: {why}"
        if c.get("sandbox") == "docker" and not (status := docker_status())["available"]:
            return f"the {role}'s runner asks for the docker sandbox and {status['why']}: nothing ran"
    return None


def gnomon_roles(project: Any) -> tuple[str, ...]:
    """The roles Gnomon runs for this project: their model is the routing's (kernel/confidential.py checks it)."""
    return tuple(r for r in ("builder", "verifier") if chosen(project, r)["runner"] == DEFAULT)


def hosted(project: Any, roles: tuple[str, ...] = ("builder", "verifier")) -> list[dict[str, Any]]:
    """The roles another runner would run on a model that cannot be shown to be local: a harness reaches the
    endpoints its docker sandbox lets it reach (its own, such as api.anthropic.com for Claude Code, unless the
    choice names others), and outside the sandbox nothing holds it to any endpoint."""
    from kernel.confidential import is_local
    from kernel.runners.sandbox import ENDPOINTS

    out = []
    for role in roles:
        c = chosen(project, role)
        if c["runner"] == DEFAULT:
            continue
        named = [str(e) for e in (c.get("endpoints") or ENDPOINTS.get(c["runner"], []))]
        far = [e for e in named if not is_local(e)]
        if c.get("sandbox") != "docker":
            far = far or ["any host: outside the docker sandbox nothing holds it to a local endpoint"]
        elif not named:
            far = ["no endpoint named"]
        if far:
            out.append({"role": role, "which": "runner", "endpoint": c["runner"], "host": ", ".join(far)})
    return out


def require_local(project: Any, *, builder: bool = True, verifier: bool = True) -> None:
    """A confidential project's role run by another harness on a hosted model is refused as a hosted role is
    (kernel/confidential.py): recorded as ``confidential_refused``, nothing run, nothing sent."""
    from kernel.confidential import GUIDE, ConfidentialRefused, confidential

    if not confidential(project):
        return
    far = hosted(project, tuple(r for r, use in (("builder", builder), ("verifier", verifier)) if use))
    if not far:
        return
    named = "; ".join(f"the {h['role']} role would run with {label_of(h['endpoint'])} on {h['host']}" for h in far)
    project.log("confidential_refused", {"where": "build", "hosted": far, "guide": GUIDE})
    raise ConfidentialRefused(
        f"refused: this project is confidential (keep on local models), and {named}. Nothing was sent. Choose "
        "Gnomon on a local model for that role in Settings > Runners, or run the harness in the docker sandbox "
        f"with only a local endpoint (--endpoint HOST:PORT) ({GUIDE}), then run it again.")


def refuse(project: Any, task_id: str, why: str, set_task: Any) -> dict[str, Any]:
    """The task does not run: the ledger says why, and it waits as pending for IT or the machine to change."""
    project.log("runner_refused", {"task": task_id, "why": why})
    set_task(project, task_id, status="pending", runner_refused=why)
    return {"status": "runner_refused", "why": why, "rounds": []}


class BuilderCell:
    """The builder's rounds for one task, through the harness chosen for the project."""

    def __init__(self, project: Any, contract: dict[str, Any], task_id: str, choice: dict[str, Any], *,
                 deadline: int = 1500):
        self.project, self.contract, self.task_id, self.choice = project, contract, task_id, choice
        self.runner = runner_for(choice["runner"], choice)
        self.deadline = deadline
        self.rounds = 0
        task = next(t for t in contract["tasks"] if t["id"] == task_id)
        self.scope = list((task.get("scope") or {}).get("write") or [])

    def run(self, lane_path: Path, prompt: str) -> dict[str, Any]:
        from kernel.lanes import PROTECTED

        env = Envelope(task=self.task_id, prompt=prompt, write_scope=self.scope, protected=list(PROTECTED),
                       conventions=conventions(Path(lane_path), self.scope, prompt=prompt),   # as Gnomon's envelope
                       tests=visible_criteria(self.contract, self.task_id))
        result = self.runner.run(env, Path(lane_path), timeout=self.deadline + 600)
        record = result.record
        self.project.log("runner_ran", {
            "task": self.task_id, "round": self.rounds, "role": "builder", "runner": record["runner"],
            **{k: record.get(k) for k in ("code", "bucket", "stop_reason", "seconds", "tool_steps", "model")},
            "tool_calls": record.get("tool_calls", [])[:50], "changed": result.changed[:50],
            "diff_sha256": hashlib.sha256(result.diff.encode("utf-8")).hexdigest(), "diff_bytes": len(result.diff)})
        self.rounds += 1
        return record

    def judge(self, lane_path: Path, base: str, head: str, verifier_runner: Any) -> GateResult:
        return judge_after_run(lane_path, self.contract, self.task_id, base, head,
                               custody=self.project.factory.holdouts_dir / self.project.pid,
                               verifier_runner=verifier_runner)


def builder(project: Any, contract: dict[str, Any], task_id: str, deadline: int) -> BuilderCell | None:
    """The builder cell of another runner, or None when Gnomon builds (the reference path)."""
    c = chosen(project, "builder")
    return None if c["runner"] == DEFAULT else BuilderCell(project, contract, task_id, c, deadline=deadline)


def verifier(project: Any, lane_path: Path) -> Any:
    """The verifier through another runner, as the gate calls it (prompt in, answer out), or None for Gnomon."""
    c = chosen(project, "verifier")
    if c["runner"] == DEFAULT:
        return None
    harness = runner_for(c["runner"], c)

    def review(prompt: str) -> str:
        with tempfile.TemporaryDirectory(prefix="rihmasto-verify-") as tmp:
            copy = Path(tmp) / "repo"
            shutil.copytree(lane_path, copy, symlinks=True, ignore=shutil.ignore_patterns(".factory-tasks"))
            env = Envelope(task="review", prompt=prompt, role="verifier", conventions=conventions(copy, prompt=prompt))
            record = harness.run(env, copy, timeout=1200).record
        project.log("runner_ran", {"role": "verifier", "runner": record["runner"],
                                   **{k: record.get(k) for k in ("code", "bucket", "stop_reason", "seconds",
                                                                 "tool_steps", "model")}})
        if record.get("bucket") == "apparatus_failure":
            raise ModelError(f"the verifier's runner failed: {record.get('stop_reason')}")
        return str(record.get("output") or "")

    return review
