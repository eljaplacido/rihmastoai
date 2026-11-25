"""The scans Rihmasto already has, as checks (FR-CHK1): its secret scan, the repo gate on an attached
repository's latest commits, and its own security gate over the project's scans."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kernel.checks import Check, Ctx, not_measured, result

SKIP = ("node_modules/**", ".venv/**", "venv/**", "dist/**", "build/**", ".gnomon*/**")


def secrets(ctx: Ctx) -> dict[str, Any]:
    """Rihmasto's secret rules (kernel/redteam/secretscan.py) over the workspace; evidence is masked."""
    from kernel.redteam import static

    root, _ = ctx.workspace()
    report = static.scan([Path(root)], root=Path(root), exclude=[*SKIP, *(ctx.config.get("exclude") or [])])
    found = [f for f in report.findings if f.layer == "secrets"]
    cover = next((c for c in report.coverage if c.layer == "secrets"), None)
    lines = [f"{f.location}: {f.rule} {f.title} ({f.evidence})" for f in found]
    if found:
        return result("failed", f"{len(found)} secret finding(s) in the workspace", lines, findings=len(found))
    if cover is None or not cover.applicable or cover.state != "measured":
        return not_measured(f"the secret scan did not measure the workspace ({cover.reason if cover else 'no layer'})")
    return result("passed", "no committed secret, credential of a known shape or secret-looking value",
                  [f"secret rules over the workspace: {cover.reason}"] if cover.reason else [])


def repo_gate(ctx: Ctx) -> dict[str, Any]:
    """The gate (kernel/gate_external.py) on the commits since the last gate, without the model verifier
    unless ``verifier`` is true; recorded as the gate records itself."""
    from kernel import gate_external
    from kernel.attach import AttachRefused

    if not ctx.project.meta.get("attached"):
        return not_measured("the repo gate judges an attached repository; a built project's changes meet the gate "
                            "on every merge already")
    try:
        out = gate_external.gate(ctx.project, person=ctx.person, persona=ctx.persona,
                                 verifier=ctx.config.get("verifier") is True)
    except AttachRefused as exc:
        return not_measured(str(exc))
    lines = [f"{s['name']}: {s['verdict']}" + (f" ({s['detail']})" if s.get("detail") else "") for s in out["signals"]]
    lines += [f"objection: {o}" for o in out["objections"][:5]]
    verdict = out["verdict"] if out["verdict"] in ("passed", "failed") else (
        "failed" if out["verdict"] in ("regressed", "violation") else "not measured")
    summary = f"the gate on {out['base'][:12]}..{out['head'][:12]}: {out['verdict']}"
    return result(verdict, summary if verdict != "not measured" else f"not measured: {summary}", lines,
                  head=out["head"])


def security_gate(ctx: Ctx) -> dict[str, Any]:
    from kernel import security

    out = security.security_gate(ctx.project)
    lines = [f"{b.get('id')}: {b.get('rule') or b.get('title') or ''} ({b.get('level')})" for b in out["blocking"]]
    lines += [f"scan: {s.get('tool')} {s.get('scope') or ''}".strip() for s in out["scans"]][:5]
    verdict = out["verdict"] if out["verdict"] in ("passed", "failed") else "not measured"
    if verdict == "not measured":
        return not_measured(out.get("reason") or "no security scan", lines)
    return result(verdict, out.get("reason") or verdict, lines)


CHECKS = (
    Check("secrets", "Secret scan", "Rihmasto's own secret scan of the workspace: committed secret files, credentials "
          "of a known shape and secret-looking values", secrets, options=("exclude",), every="1d"),
    Check("repo_gate", "Repo gate", "the gate on the latest commits of an attached repository (tests, criteria, "
          "fail-first; the verifier when asked)", repo_gate, options=("verifier",), runs_code=True),
    Check("security_gate", "Security gate", "Rihmasto's own security gate over the project's scans and the risks "
          "people accepted", security_gate, every="1d"),
)
