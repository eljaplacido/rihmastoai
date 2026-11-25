"""A failed Gnomon audit or role eval opens an incident, with its findings as context (FR-HEAL1 with FR-EVL1).

- A **Gnomon audit** whose verdict is failed (kernel/gnomon_evals_run.py ``record``) opens an ``eval_failed``
  incident on its project: where is the audit, the message its summary, the context the audit's label, scores
  and findings (each finding's id, severity, title and evidence, already cut by kernel/gnomon_evals_read.py), and
  which of them are new. Not measured is not failed: it opens nothing.
- A **role eval** (kernel/role_evals.py ``_keep``) a candidate model answered wrongly in any case opens one on
  the factory: where is the eval set, the context the role, the candidate and each wrong case with what was
  wrong. A refused candidate (a confidential project, a hosted model) was never asked: it opens nothing.

The same audit or set failing again while its incident is open is counted on it (kernel/incidents.py), so a weekly
audit that keeps failing is one incident with its count, not one a week.
"""

from __future__ import annotations

from typing import Any

from kernel import incidents as inc

MAX_FINDINGS = 20


def audit_failed(project: Any, ev: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    """The incident a failed audit opens (or counts one more on); None when it did not fail."""
    if row.get("verdict") != "failed":
        return None
    findings = [{k: f.get(k) for k in ("id", "severity", "title", "evidence", "new")}
                for f in (row.get("findings") or [])[:MAX_FINDINGS] if isinstance(f, dict)]
    return inc.open_incident(project.factory, kind="eval_failed", where=f"eval:{ev.id}",
                             message=f"failed: {row.get('summary') or ''}", project=project.pid,
                             by="Gnomon's audit", context={
                                 "eval": ev.id, "label": ev.label, "scores": row.get("scores") or {},
                                 "issues": row.get("issues"), "new_findings": row.get("new_findings"),
                                 "findings": findings, "persona": (row.get("by") or {}).get("persona")})


def role_eval_failed(factory: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    """The incident a role eval with wrong answers opens (or counts on); None when every case was right."""
    if row.get("refused") or not row.get("cases") or row.get("correct") == row.get("cases"):
        return None
    wrong = [{"case": r.get("case"), "failed": r.get("failed")} for r in row.get("rows") or [] if not r.get("passed")]
    return inc.open_incident(factory, kind="eval_failed", where=f"role_eval:{row['set']}",
                             message=f"{row['candidate']} answered wrongly on the {row['set']} set",
                             by="Rihma's role evals", context={
                                 "set": row["set"], "role": row.get("role"), "candidate": row.get("candidate"),
                                 "score_pct": row.get("score_pct"), "cases": row.get("cases"),
                                 "correct": row.get("correct"), "findings": wrong[:MAX_FINDINGS],
                                 "persona": (row.get("by") or {}).get("persona")})
