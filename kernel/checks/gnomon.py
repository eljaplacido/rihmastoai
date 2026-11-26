"""Gnomon's audits, benchmarks and evals as checks (FR-EVL1 with FR-CHK1): one check kind per eval of
kernel/gnomon_evals.py (``gnomon_security``, ``gnomon_check``, ``gnomon_eval`` ...), so Health shows each one's last
result and trend, a schedule runs it (``every``: "7d" is a weekly Gnomon audit of the repository), and an
automation's ``run_check`` action runs it. A run as a check is recorded twice, by design: ``eval_ran`` with its
scores and findings (kernel/gnomon_evals_run.py), and ``check_ran`` with the verdict (kernel/checks/store.py)."""

from __future__ import annotations

from typing import Any

from kernel import gnomon_evals as ge
from kernel.checks import Check, Ctx, not_measured, result


def _runner(ev: ge.Eval) -> Any:
    def run(ctx: Ctx) -> dict[str, Any]:
        from kernel import gnomon_evals_run as gr

        row = gr.run(ctx.project, ev.id, person=ctx.person, persona=ctx.persona, config=ctx.config, via="check")
        evidence = [f"{'new ' if f.get('new') else ''}{f['severity']}: {f['title']}" for f in row["findings"]]
        data = {"eval": ev.id, "scores": row["scores"], "new_findings": row["new_findings"]}
        if row["verdict"] == "not measured":
            return not_measured(row["summary"], evidence, **data)
        return result(row["verdict"], f"Gnomon {ev.label}: {row['summary']}", evidence, **data)
    return run


CHECKS = tuple(Check(ev.check_kind, f"Gnomon: {ev.label}", ev.measures, _runner(ev), options=ev.options,
                     needs=ev.needs, runs_code=ev.runs_code, every=ev.every) for ev in ge.CATALOGUE)
