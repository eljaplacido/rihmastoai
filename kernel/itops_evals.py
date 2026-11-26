"""Eval sets: every eval Gnomon offers and Rihma's role evals, enabled per project and trended (FR-ITO1, FR-EVL1).

The owner (2026-11-25): "Don't forget the eval sets enabled by Gnomon."

Two kinds of set, each shown with its **scope**:

- **Gnomon's** audits, benchmarks and evals (kernel/gnomon_evals.py ``CATALOGUE``): they run on one project's
  repository, so each is enabled **per project**. Enabled means it runs on its schedule as a Health check
  (``gnomon_<id>``, kernel/checks/gnomon.py), and it runs on demand from Health, Ask Rihma and the
  ``run_assessment`` automation action;
- **Rihma's role evals** (kernel/role_evals.py ``SETS``): they judge the models behind Rihma's own roles, so their
  results are **platform-wide**. A project enables a set to have it run with the project's rules (a confidential
  project compares local models only) and to see its trend on the project's views; kept in the project's
  ``itops.json`` (``evalsets``).

``view`` gives each set with whether it runs here, whether it is enabled on the project, its latest result and
its trend (the last ten verdicts with their main figure), for Health, the IT checks view and Agent operations.
Enabling and disabling are signed and recorded (``evalset_enabled``, ``evalset_disabled``).
"""

from __future__ import annotations

from typing import Any

from kernel import gnomon_evals as ge
from kernel.itops import FILE, signed
from kernel.store import updating_json

ENABLERS = ("developer", "it", "operations", "compliance", "product_owner", "ai_architect")
TREND = 10


def _enablers() -> tuple[str, ...]:
    from kernel.people import PERSONAS

    return tuple(p for p in ENABLERS if p in PERSONAS)


def _gnomon_trend(project: Any, ev: ge.Eval) -> list[dict[str, Any]]:
    from kernel import gnomon_evals_run as gr

    return [{"verdict": r.get("verdict"), "at": r.get("at"), "value": (r.get("scores") or {}).get(ev.score)}
            for r in gr.results(project, ev.id, TREND)]


def _role_runs(factory: Any) -> list[dict[str, Any]]:
    from kernel.learn import factory_project

    fp = factory_project(factory, create=False)
    return list(((fp.read("evals/roles.json", {}) or {}).get("runs") or []) if fp is not None else [])


def _role_trend(runs: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    mine = [r for r in runs if r.get("set") == name][-TREND:]
    return [{"verdict": "not measured" if r.get("score_pct") is None else "passed" if r["score_pct"] >= 80
             else "failed", "at": r.get("at"), "value": r.get("score_pct"), "candidate": r.get("candidate")}
            for r in mine]


def sets(project: Any = None) -> list[dict[str, Any]]:
    """Every eval set, with its scope and, for a project, whether it is enabled there and its trend."""
    from kernel import role_evals as re_
    from kernel.checks import store as cstore

    enabled = cstore.enabled(project) if project is not None else {}
    chosen = set((project.read(FILE, {}) or {}).get("evalsets") or []) if project is not None else set()
    out = []
    for g in ge.public(project):
        ev = ge.BY_ID[g["id"]]
        trend = _gnomon_trend(project, ev) if project is not None else []
        out.append({"id": f"gnomon:{g['id']}", "source": "gnomon", "label": g["label"], "what": g["measures"],
                    "scope": "per project", "available": g["available"], "why_not": g["why_not"],
                    "duration": g["duration"], "models": g["models"], "every": g["every"], "check": g["check"],
                    "enabled": g["check"] in enabled, "score": g["score"], "unit": g["unit"],
                    "trend": trend, "latest": trend[-1] if trend else None,
                    "run": {"method": "POST", "path": f"/api/projects/{project.pid}/evals/{g['id']}/run"}
                    if project is not None else None})
    runs = _role_runs(project.factory) if project is not None else []
    for name, s in re_.SETS.items():
        trend = _role_trend(runs, name)
        out.append({"id": f"role:{name}", "source": "rihma", "label": s["label"], "what": s["what"],
                    "scope": "platform (Rihma's own roles)", "available": True, "why_not": None,
                    "duration": "minutes", "models": "roles", "every": None, "check": None, "role": s["role"],
                    "enabled": name in chosen, "score": "Right answers", "unit": "%", "trend": trend,
                    "latest": trend[-1] if trend else None,
                    "run": {"method": "POST", "path": "/api/evals/roles/run",
                            "body": {"role": s["role"], **({"for_project": project.pid} if project else {})}}})
    return out


def view(project: Any = None) -> dict[str, Any]:
    rows = sets(project)
    on = [r for r in rows if r["enabled"]]
    failing = [r["label"] for r in on if (r["latest"] or {}).get("verdict") == "failed"]
    line = (f"{len(on)} of {len(rows)} eval sets enabled" + (f"; failing: {', '.join(failing)}" if failing else "")
            if project is not None else f"{len(rows)} eval sets: Gnomon's per project, Rihma's role evals "
                                         "platform-wide")
    return {"project": project.pid if project is not None else None, "sets": rows, "line": line,
            "gnomon": ge.summary_line()}


def toggle(project: Any, set_id: str, on: bool, *, person: str, persona: str, every: str | None = None) -> dict:
    """Enable or disable an eval set on a project, signed and recorded."""
    from kernel import role_evals as re_
    from kernel.checks import store as cstore

    signed(person, persona, _enablers(), "enabling an eval set")
    source, _, name = str(set_id).partition(":")
    if source == "gnomon":
        ev = ge.find(name)
        if on:
            cstore.enable(project, ev.check_kind, person=person, persona=persona, every=every or ev.every)
        elif ev.check_kind in cstore.enabled(project):
            cstore.disable(project, ev.check_kind, person=person, persona=persona)
    elif source == "role" and name in re_.SETS:
        cstore.sign_on(project, person, persona)
        with updating_json(project.path(FILE), {}) as kept:
            chosen = [s for s in kept.get("evalsets") or [] if s != name]
            kept["evalsets"] = chosen + ([name] if on else [])
    else:
        raise ValueError("an eval set is gnomon:<eval> or role:<set>, as the Eval sets list names it")
    project.log("evalset_enabled" if on else "evalset_disabled", {"set": set_id, "person": person,
                                                                  "persona": persona})
    return view(project)


def trends(factory: Any, pid: str | None = None) -> list[dict[str, Any]]:
    """The enabled sets' trends, for Agent operations: one project's, or every project's with a latest result."""
    projects = [factory.project(pid)] if pid else [p for p in factory.projects() if not p.pid.startswith("_")]
    out = []
    for p in projects:
        for r in sets(p):
            if r["enabled"] or (r["source"] == "gnomon" and r["trend"]):
                out.append({"project": p.pid, "title": p.meta.get("title") or p.pid, "set": r["id"],
                            "label": r["label"], "scope": r["scope"], "enabled": r["enabled"], "trend": r["trend"],
                            "latest": r["latest"], "unit": r["unit"]})
    return out
