"""The destinations check (FR-DST1, FR-CHK1): one feedback round over every place the capability goes
(kernel/destinations_feedback.py), as a check Health shows and runs on a schedule. Failed when a destination is
failing, passed when every delivered destination answered healthy, not measured while nothing delivered was
measured."""

from __future__ import annotations

from typing import Any

from kernel.checks import Check, Ctx, not_measured, result


def _line(d: dict[str, Any]) -> str:
    why = (d.get("health") or {}).get("why") if d["state"] == "failing" else None
    return f"{d['label']}: {d['state']}" + (f" ({why})" if why else "")


def run(ctx: Ctx) -> dict[str, Any]:
    from kernel.destinations_feedback import check

    out = check(ctx.project, person=ctx.person or None, persona=ctx.persona or None, via="check")
    rows = [d for g in out["view"]["groups"].values() for d in g]
    lines = [_line(d) for d in rows if d["state"] != "planned"]
    if out["failing"]:
        return result("failed", f"{len(out['failing'])} destination(s) failing: {', '.join(out['failing'][:3])}",
                      lines, failing=out["failing"])
    measured = [d for d in rows if d["state"] in ("healthy", "not measured")]
    if any(d["state"] == "healthy" for d in measured):
        return result("passed", f"{sum(1 for d in measured if d['state'] == 'healthy')} destination(s) healthy",
                      lines)
    return not_measured("no destination has been measured yet: nothing delivered answered a probe", lines)


CHECKS = (Check("destinations", "Destinations", "every place the capability goes: where it runs, the channels it "
                "is used through and where it is published, failing or healthy", run, every="15m"),)
