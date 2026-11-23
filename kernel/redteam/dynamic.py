"""The dynamic layer: probe a running deployment the factory runs, inside a scope a person authorised.

    python -m kernel.redteam dynamic <project> --env staging [--slot current] [--budget N]

What a run does, in order:

1. **The scope.** The target is checked before anything is sent (`kernel/redteam/scope.py`): a
   loopback `base_url` the factory deployed (a running slot of the environment) or a surface it
   runs, named in an unexpired scope that a person with the `it` or `compliance` persona
   authorised. A refusal is recorded in the ledger and raised: not one connection is made. After
   that, every single request is checked again (`kernel/redteam/client.py`), so a scope revoked
   or expired mid-run stops the run at its next request; what was not probed is not measured.
2. **The probes**, one layer each, on the routes of the project's fixed interface
   (`kernel/spec.py` `interface_of`): security headers, error pages that leak, path traversal
   (plain and encoded), reflected injection, method tampering, malformed and oversized bodies,
   CORS, and rate limiting on a write route (at most 12 requests).
3. **The budget.** A run sends at most its budget of requests (300 by default, 1000 at most); the
   layers the budget did not reach are partial or not measured, with the reason.
4. **The report**, as for the static layer (`kernel/redteam/report.py`): findings with CWE and
   OWASP ids and a fix, coverage per layer that never reads unmeasured as passed, SARIF under its
   own tool name (`Rihmasto red team (dynamic)`), and a `redteam_dynamic_run` record in the
   project's ledger naming the scope, the target and the number of requests sent.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from kernel.redteam import contentprobes, protocolprobes
from kernel.redteam.client import DEFAULT_BUDGET, TIMEOUT, BudgetSpent, Client
from kernel.redteam.probing import Run, Tally, routes_of
from kernel.redteam.report import Coverage, Report
from kernel.redteam.scope import ScopeRefused
from kernel.redteam.started import Started
from kernel.roads import ENVIRONMENTS, SLOTS, slot_state
from kernel.spec import interface_of

RUN_RECORD = "redteam_dynamic_run"
Probe = Callable[[Run, Tally], str]
PROBES: dict[str, Probe] = {
    "headers": contentprobes.headers,
    "errors": contentprobes.errors,
    "traversal": contentprobes.traversal,
    "injection": contentprobes.injection,
    "methods": protocolprobes.methods,
    "bodies": protocolprobes.bodies,
    "cors": protocolprobes.cors,
    "ratelimit": protocolprobes.ratelimit,
}


def _probe(run: Run) -> list[tuple[Tally, str]]:
    """Run every layer's probe; the budget ends a layer, a scope refusal ends the run."""
    out = []
    for layer, probe in PROBES.items():
        tally, reason = Tally(layer), ""
        if run.halted:
            tally.stopped = run.halted
        else:
            try:
                reason = probe(run, tally)
            except BudgetSpent as exc:
                tally.stopped = str(exc)
            except ScopeRefused as exc:
                run.halted = tally.stopped = f"the scope refused a request mid-run, so the run stopped: {exc}"
        out.append((tally, reason))
    return out


def _coverage(run: Run, tallies: list[tuple[Tally, str]]) -> list[Coverage]:
    inspected = contentprobes.inspect_errors(run)
    out = []
    for tally, reason in tallies:
        if tally.layer == "errors" and reason:
            reason += f"; every error answer of the run read for leaks ({inspected})"
        out.append(tally.coverage(reason))
    return out


def _target(run: Run) -> str:
    p = run.client.permit
    where = f"{p.environment}/{p.slot}" if p.environment else p.label
    return f"{where} ({p.base_url})"


def _record(project: Any, run: Run, report: Report) -> None:
    p = run.client.permit
    project.log(RUN_RECORD, {
        "scope": p.scope, "label": p.label, "environment": p.environment, "slot": p.slot, "release": p.release,
        "base_url": p.base_url, "requests": run.client.sent, "budget": run.client.budget,
        "verdict": report.verdict, "counts": report.counts(),
        "layers": {c.layer: c.state for c in report.coverage}, "halted": run.halted or None})


def scan(project: Any, target: str, *, running: Mapping[str, Started] | None = None, budget: int = DEFAULT_BUDGET,
         interface: list[Any] | None = None, timeout: float = TIMEOUT) -> Report:
    """Probe ``target`` (a deployment the factory runs) and report. Raises ScopeRefused, with nothing
    sent, for a target the scope does not allow now; ``interface`` defaults to the project's spec."""
    client = Client(project, target, running=running, budget=budget, timeout=timeout)
    rows = interface if interface is not None else interface_of(project.read("spec.json") or {})
    run = Run(client, routes_of(rows))
    tallies = _probe(run)
    coverage = _coverage(run, tallies)
    p = client.permit
    notes = [f"Scope {p.scope}: authorised by {p.person} ({p.persona}) until {p.expires}, as {p.label}.",
             f"{client.sent} of a budget of {client.budget} requests sent, each checked against the scope first.",
             f"{len(run.routes)} route(s) from the project's interface."]
    if run.halted:
        notes.append(run.halted)
    report = Report(_target(run), run.findings, coverage, notes=notes, kind="dynamic")
    _record(project, run, report)
    return report


def scan_environment(project: Any, environment: str, slot: str = "current", **kw: Any) -> Report:
    """Probe the slot of ``environment`` the factory runs (its `base_url` in the slot state)."""
    if environment not in ENVIRONMENTS or slot not in SLOTS:
        raise ValueError(f"an environment is one of {', '.join(ENVIRONMENTS)} and a slot one of {', '.join(SLOTS)}")
    state = slot_state(project, environment, slot)
    if not state or not state.get("base_url"):
        raise LookupError(f"nothing the factory deployed runs in {environment}/{slot}")
    return scan(project, str(state["base_url"]), **kw)
