"""The cockpit assistant's own lane (kernel/assistant.py, D-0005): Gnomon's `assistant` role in a lane beside
the factory's analyst lane, so a question never waits behind intake or holdout authoring there.
"""

from __future__ import annotations

import time
from contextlib import ExitStack
from pathlib import Path

from kernel.filelock import LockHeld
from kernel.model import Model, ModelError, run_gnomon_task

LANE_WAIT, MODEL_TIMEOUT, DEADLINE_GRACE = 10.0, 60, 15   # as the website chat's (embed/server.py ChatModel)


class AssistantModel(Model):
    """Gnomon's `assistant` role in a lane of its own (`<lanes root>/assistant/analyst`), never the factory's
    analyst lane, where intake, spec and holdout authoring run for many minutes. A question waits at most
    ``lane_wait`` seconds for the lane (LockHeld after that), and Gnomon gets at most ``timeout`` seconds."""

    def __init__(self, lane_dir: str | Path, *, timeout: int = MODEL_TIMEOUT, lane_wait: float = LANE_WAIT) -> None:
        self.lane_dir, self.timeout, self.lane_wait = Path(lane_dir), timeout, lane_wait

    def ask(self, prompt: str, *, role: str) -> str:
        from kernel.lanes import lane_lock

        give_up = time.monotonic() + self.lane_wait
        with ExitStack() as held:
            while True:
                try:
                    held.enter_context(lane_lock(self.lane_dir, blocking=False))
                    break
                except LockHeld:
                    if time.monotonic() >= give_up:
                        raise
                    time.sleep(0.2)
            record = run_gnomon_task(self.lane_dir, prompt, role=role, timeout=self.timeout,
                                     deadline=max(1, self.timeout - DEADLINE_GRACE))
        self.last_record, output = record, record.get("output")
        if record.get("bucket") == "apparatus_failure" or not isinstance(output, str) or not output.strip():
            raise ModelError(f"gnomon task --role {role} gave no answer (stop: {record.get('stop_reason')})")
        return output


def assistant_model(root: str | Path | None = None, *, local: bool = False) -> AssistantModel:
    """The assistant's model, in ``<lanes root>/assistant/analyst``: a toolless analyst lane of its own. With
    ``local`` (a confidential project), in ``assistant-local``, compiled without a hosted fallback."""
    from kernel.confidential import without_hosted_fallbacks
    from kernel.lanes import ensure_analyst_lane, lanes_root, load_routing

    routing = without_hosted_fallbacks(load_routing()) if local else load_routing()
    where = Path(root or lanes_root()) / ("assistant-local" if local else "assistant")
    return AssistantModel(ensure_analyst_lane(routing, root=where))


_OWN_LANES: dict[str, Model] = {}


def lane_busy(model: Model) -> bool:
    """Whether the model's lane is held by another question now (a where-is question then never waits, FR-NVL3)."""
    from kernel.lanes import lane_lock

    lane = getattr(model, "lane_dir", None)
    if lane is None:
        return False
    try:
        with lane_lock(Path(lane), blocking=False):
            return False
    except LockHeld:
        return True


def _own_lane(model: Model, local: bool = False) -> Model:
    """A GnomonModel for the factory's analyst lane is asked through the assistant's own lane beside it (never
    waiting on that lane's lock behind a long run); a confidential project's through one with no hosted fallback."""
    from kernel.model import GnomonModel

    if not isinstance(model, GnomonModel):
        return model
    key = f"{model.lane_dir}|{'local' if local else 'any'}"
    if key not in _OWN_LANES:
        _OWN_LANES[key] = assistant_model(Path(model.lane_dir).parent, local=local)
    return _OWN_LANES[key]
