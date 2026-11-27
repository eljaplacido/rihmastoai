"""Each model run of every role recorded in the project's ledger as ``model_run`` (FR-INS1, Insights' usage).

The builder's cells are recorded by the ingest (``gnomon_run``, adapters/gnomon_ingest.py). The other roles ask a
model through ``kernel.model``: the analyst (intake, spec, shaping), the holdout author, the verifier (the gate's
review) and the assistant (Ask Rihma). Their calls do not know which project they serve, so the code that does
says it around them:

    with model_usage.for_project(project, task="intake"):
        ... model.ask(prompt, role="analyst") ...

or, for a function whose first argument is the project, ``@model_usage.recorded("spec")``. Each Gnomon call
(``kernel.model.run_gnomon_task``) and each scripted answer (``FakeModel``) inside it then appends one
``model_run``: the role, the model and endpoint, the tokens, the priced cost when the model is in the price table
(not measured otherwise, never zero), how long it took and whether it answered. Nothing of the prompt or the
answer is kept: a holdout author's run says only that it ran (its task and the session id), never the holdouts.
Outside such a block nothing is recorded.
"""

from __future__ import annotations

import contextlib
import functools
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from typing import Any

# The builder's cells have their own record, with the audit chain (gnomon_run): never a second one here.
OWN_RECORD = ("builder",)
_CURRENT: ContextVar[tuple[Any, str | None] | None] = ContextVar("rihmasto_model_usage", default=None)
_QUIET: ContextVar[bool] = ContextVar("rihmasto_model_usage_quiet", default=False)


@contextlib.contextmanager
def quiet() -> Iterator[None]:
    """Nothing inside is recorded, whatever a block within names: an evaluation that keeps nothing
    (kernel/graph_ask.py's eval_baseline) asks a model without it being the project's usage."""
    token = _QUIET.set(True)
    try:
        yield
    finally:
        _QUIET.reset(token)


@contextlib.contextmanager
def for_project(project: Any, *, task: str | None = None, factory: Any = None) -> Iterator[None]:
    """Model runs inside this block are recorded in ``project``'s ledger; with no project, in the factory's own
    (``factory`` given), else nowhere."""
    if project is None and factory is not None:
        from kernel.learn import factory_project

        project = factory_project(factory)
    token = _CURRENT.set((project, task) if project is not None else None)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def current() -> tuple[Any, str | None]:
    """The project and task the surrounding block names, (None, None) outside one or inside ``quiet``."""
    found = None if _QUIET.get() else _CURRENT.get()
    return found if found is not None else (None, None)


def recorded(task: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """A function whose first argument is the project records its model runs there, under ``task``."""
    def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def inner(project: Any, *args: Any, **kwargs: Any) -> Any:
            with for_project(project, task=task):
                return fn(project, *args, **kwargs)
        return inner
    return wrap


def timed(runner: Callable[..., Any] | None, role: str) -> Callable[..., Any] | None:
    """A runner given in place of a Gnomon call (a scripted verifier, another harness's review), recorded as a
    run of ``role`` when it answers or fails; None stays None. Its model is the one it names itself (a ``model``
    attribute), never the routing's: the routing says what Gnomon would have asked, not what this runner is."""
    if runner is None:
        return None

    @functools.wraps(runner)
    def run(*args: Any, **kwargs: Any) -> Any:
        import time

        started, ok = time.monotonic(), False
        try:
            out = runner(*args, **kwargs)
            ok = True
            return out
        finally:
            note(role, None, seconds=time.monotonic() - started, ok=ok, runner="scripted",
                 model=getattr(runner, "model", None))
    return run


def _routed(role: str) -> dict[str, Any]:
    """The model and endpoint the routing names for a role, when the run's own record names none."""
    try:
        from kernel.lanes import load_routing

        spec = (load_routing().get("roles") or {}).get(role) or {}
    except (OSError, ValueError):
        return {}
    return {"model": spec.get("model"), "endpoint": spec.get("endpoint")} if isinstance(spec, dict) else {}


def payload(role: str, record: dict[str, Any] | None, *, seconds: float, ok: bool, task: str | None,
            runner: str | None = None, model: str | None = None) -> dict[str, Any]:
    """One run's metadata: what Insights' usage reads (kernel/insights/gnomon_records.py)."""
    from adapters.gnomon_ingest import context, run_cost, tokens

    record = record if isinstance(record, dict) else {}
    routed = {} if record.get("model") or runner == "scripted" else _routed(role)
    model, endpoint = record.get("model") or model or routed.get("model"), record.get("endpoint") or routed.get(
        "endpoint")
    toks = tokens(record) if record.get("volatile") else {"in": None, "out": None, "cached": None, "calls": None}
    if toks["in"] is None or toks["out"] is None:
        cost = {"measured": False, "kind": None, "amount": None, "why": "the run recorded no token counts"}
    else:
        cost = run_cost(dict(record, model=model), toks)
    failed = not ok or record.get("bucket") == "apparatus_failure"
    return {"run": record.get("session"), "task": task, "role": role, "model": model, "endpoint": endpoint,
            "runner": runner or ("gnomon" if record else "scripted"), "tokens": toks, "cost": cost,
            "context": context(record) if record else {}, "seconds": round(max(seconds, 0.0), 3),
            "verdict": "failed" if failed else "passed"}


def note(role: str, record: dict[str, Any] | None, *, seconds: float, ok: bool, runner: str | None = None,
         model: str | None = None) -> None:
    """Record one run in the project the surrounding block names; nothing outside one, or for the builder."""
    current = _CURRENT.get()
    if current is None or role in OWN_RECORD or _QUIET.get():
        return
    if isinstance((record or {}).get("harness"), dict):
        return          # a harness answered: kernel/harness_model.py recorded the run, in this project (``current``)
    project, task = current
    try:
        project.log("model_run", payload(role, record, seconds=seconds, ok=ok, task=task, runner=runner,
                                         model=model))
    except (OSError, ValueError, TypeError):   # the usage record never breaks the work it describes
        return
