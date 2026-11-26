"""Run any assessment on request or on a schedule: the ``run_assessment`` automation action (FR-ITO1 with FR-AUT1).

The owner (2026-11-25): "in regards to automations there should be able to run assessments of any area if
requested."

One action, one target (``TARGETS``), each run through its own feature's path with its own rules, signed by the
person (a click, Ask Rihma's confirmed proposal) or the automation's owner (``handle``), so the action never has
more rights than that person: the target's own check refuses a persona it does not allow.

| Target | What runs | Its own rules |
|---|---|---|
| ``code`` | the code assessment of the repository, rules only (kernel/assess.py) | the assessment's askers |
| ``gnomon:<eval>`` | one of Gnomon's audits, benchmarks or evals (kernel/gnomon_evals_run.py) | its enablers |
| ``evalset:<id>`` | an eval set: Gnomon's, or a role eval set for this project (kernel/role_evals.py) | its own |
| ``evalsets`` | every eval set turned on for the project, each as ``evalset:<id>`` | each one's |
| ``check:<key>`` | one enabled Health check (kernel/checks/store.py) | the check's |
| ``family:<kind>`` | every enabled check of one kind (``family:tls``) | each check's |
| ``alignment`` | the alignment scan of the repository (kernel/alignment_records.py) | alignment's signers |
| ``optimise`` | the AI architect's Optimise audit of the project's agents (kernel/agentops_actions.py) | its auditors |
| ``infra`` | the project's infrastructure check set (kernel/itops.py) | IT, operations, developers |

Each run is recorded where its feature records it, and ``assessment_ran`` in the project's ledger says which
target ran, its outcome and who asked. A target that does not apply here (no repository, no such check enabled)
does nothing and says why.
"""

from __future__ import annotations

from typing import Any

from kernel.canon import DecisionRefused

TARGETS: dict[str, str] = {
    "code": "Code assessment of the repository (rules only)",
    "gnomon": "A Gnomon audit, benchmark or eval",
    "evalset": "An eval set (Gnomon's, or a role eval set for this project)",
    "evalsets": "Every eval set turned on for this project",
    "check": "One Health check",
    "family": "Every enabled check of one kind",
    "alignment": "Alignment of the repository's specs and tests",
    "optimise": "The AI architect's Optimise audit of the agents",
    "infra": "The infrastructure check set",
}
PERSONAS = ("business_owner", "product_owner", "developer", "it", "operations", "compliance", "ai_architect")
OTHERS = ("ai_architect", "compliance", "product_owner", "business_owner")   # beyond IT's, for the targets they own


def parse(target: Any) -> tuple[str, str]:
    """``(kind, name)`` of a target, checked against the list; a name where its kind needs one."""
    kind, _, name = str(target or "").strip().partition(":")
    if kind not in TARGETS:
        raise ValueError(f"an assessment target is one of {', '.join(TARGETS)} (gnomon:<eval>, evalset:<id>, "
                         "check:<key> and family:<kind> name theirs)")
    if kind in ("gnomon", "evalset", "check", "family") and not name:
        raise ValueError(f"{kind} names what to run: {kind}:<name>")
    if kind == "gnomon":
        from kernel.gnomon_evals import find

        name = find(name).id
    if kind in ("check", "family"):
        from kernel.checks import store as cstore

        name = cstore.check_of(name)[1] if kind == "check" else cstore.check_of(name)[0].kind
    return kind, name


def _out(outcome: str, detail: str, verdict: str | None = None, **refs: Any) -> dict[str, Any]:
    return {"outcome": outcome, "verdict": verdict, "detail": str(detail)[:300], "refs": refs}


def _checks(project: Any, keys: list[str], person: str, persona: str, via: str) -> dict[str, Any]:
    from kernel.checks import store as cstore

    if not keys:
        return _out("nothing", "no such check is enabled here: enable it on Health first")
    rows = [cstore.run(project, k, person=person, persona=persona, via=via) for k in keys]
    failed = [r["check"] for r in rows if r["verdict"] == "failed"]
    verdict = "failed" if failed else "passed" if all(r["verdict"] == "passed" for r in rows) else "not measured"
    return _out("done", "; ".join(f"{r['check']}: {r['summary']}" for r in rows), verdict, checks=keys)


def _role_set(project: Any, name: str, person: str, persona: str) -> dict[str, Any]:
    from kernel import role_evals

    if name not in role_evals.SETS:
        raise ValueError(f"no eval set {name}")
    got = role_evals.run(project.factory, person=person, persona=persona, sets=[name], for_project=project.pid)
    scored = [r["score_pct"] for r in got["runs"] if r.get("score_pct") is not None]
    verdict = "not measured" if not scored else "passed" if min(scored) >= 80 else "failed"
    return _out("done", "; ".join(got["lines"]) or "no candidate answered", verdict, evalset=name)


Who = tuple[Any, str, str, str, str]          # (project, name, person, persona, via)


def _code(w: Who) -> dict[str, Any]:
    from kernel import assess

    project, _, person, persona, _ = w
    if not project.path("repo.git").is_dir():
        return _out("nothing", f"{project.pid} has no repository mirror to assess: attach or adopt one first")
    rec = assess.assess(project, person=person, persona=persona)
    return _out("done", *code_verdict(rec), assessment=rec["id"])


BLOCKING = ("critical", "high")         # a code assessment fails on these; medium, low and info are said, not failed


def code_verdict(rec: dict[str, Any]) -> tuple[str, str]:
    """(detail, verdict) of a code assessment: failed only on a critical or high finding (FR-ITO2)."""
    counts = rec.get("counts") or {}
    by = {k: int(v) for k, v in (counts.get("by_severity") or {}).items() if v}
    found = int(counts.get("findings") or 0)
    said = ", ".join(f"{n} {s}" for s, n in by.items())
    blocking = sum(by.get(s, 0) for s in BLOCKING)
    detail = f"{rec['id']}: {found} finding(s)" + (f" ({said})" if said else "")
    if blocking:
        return detail + f"; {blocking} critical or high", "failed"
    return detail + ("; none critical or high" if found else ""), "passed"


def _gnomon(w: Who) -> dict[str, Any]:
    from kernel import gnomon_evals_run as gr

    project, name, person, persona, via = w
    row = gr.run(project, name.removeprefix("gnomon:"), person=person, persona=persona, via=via)
    return _out("done", f"{row['label']}: {row['summary']}", row["verdict"], eval=row["eval"])


def _evalset(w: Who) -> dict[str, Any]:
    return _gnomon(w) if w[1].startswith("gnomon:") else _role_set(w[0], w[1].removeprefix("role:"), w[2], w[3])


def _evalsets(w: Who) -> dict[str, Any]:
    """Every eval set turned on for the project, each through its own path (FR-ITO2: "Weekly eval sets" runs the
    sets themselves, not a drift check)."""
    from kernel import itops_evals

    project, _, person, persona, via = w
    on = [r["id"] for r in itops_evals.sets(project) if r["enabled"]]
    if not on:
        return _out("nothing", "no eval set is turned on for this project: turn one on under Eval sets first")
    rows = [_evalset((project, sid, person, persona, via)) for sid in on]
    verdicts = [r["verdict"] for r in rows]
    verdict = "failed" if "failed" in verdicts else "passed" if all(v == "passed" for v in verdicts) else \
        "not measured"
    return _out("done", "; ".join(f"{sid}: {r['detail']}" for sid, r in zip(on, rows, strict=True)), verdict,
                evalsets=on)


def _check(w: Who) -> dict[str, Any]:
    from kernel.checks import store as cstore

    project, name, person, persona, via = w
    return _checks(project, [name] if name in cstore.enabled(project) else [], person, persona, via)


def _family(w: Who) -> dict[str, Any]:
    from kernel.checks import store as cstore

    project, name, person, persona, via = w
    keys = [k for k, e in sorted(cstore.enabled(project).items()) if e.get("kind") == name]
    return _checks(project, keys, person, persona, via)


def _alignment(w: Who) -> dict[str, Any]:
    from kernel import alignment_records as ar

    project, _, person, persona, _ = w
    if not ar.applies(project):
        return _out("nothing", f"{project.pid} has no repository of its own to align with")
    view = ar.scan(project, person=person, persona=persona)
    moved = sum(len(v) for v in (view.get("drift") or {}).values() if isinstance(v, list))
    return _out("done", f"{moved} item(s) drifted since the scan before", "failed" if moved else "passed")


def _optimise(w: Who) -> dict[str, Any]:
    from kernel import agentops_actions

    project, _, person, persona, _ = w
    got = agentops_actions.record(project.factory, pid=project.pid, window="30d", person=person, persona=persona)
    found, runs = len(got.get("proposals") or []), int(got["totals"]["runs"] or 0)
    detail = (f"{found} optimisation proposal(s) over {runs} agent run(s) in the last 30 days" if runs else
              f"no agent run in the last 30 days, so nothing measured from runs; {found} proposal(s) from how the "
              "agents are set up")
    return _out("done", detail, None if runs else "not measured", audit=(got.get("audit") or {}).get("seq"))


def _infra(w: Who) -> dict[str, Any]:
    from kernel import itops

    project, _, person, persona, via = w
    ran = itops.run(project, person=person, persona=persona, via=via)["ran"]
    if not ran:
        return _out("nothing", "no infrastructure check is enabled: enable the check set first")
    failed = [r["check"] for r in ran if r["verdict"] == "failed"]
    return _out("done", f"{len(ran)} IT check(s) ran" + (f"; failing: {', '.join(failed)}" if failed else ""),
                "failed" if failed else "passed", checks=[r["check"] for r in ran])


RUNS = {"code": _code, "gnomon": _gnomon, "evalset": _evalset, "evalsets": _evalsets, "check": _check,
        "family": _family,
        "alignment": _alignment, "optimise": _optimise, "infra": _infra}


def run(project: Any, target: Any, *, person: str, persona: str, via: str = "person") -> dict[str, Any]:
    """Run one assessment on the project with this person's rights; its outcome for the history."""
    from kernel import itops

    itops.signed(person, persona, PERSONAS, "an assessment")    # the target's own rule narrows it further
    kind, name = parse(target)
    out = RUNS[kind]((project, name, person, persona, via))
    said = f"{kind}:{name}" if name else kind
    project.log("assessment_ran", {"target": said, "outcome": out["outcome"], "verdict": out["verdict"],
                                   "detail": out["detail"], "person": person, "persona": persona, "via": via})
    return out | {"target": said}


# -- the automation action ------------------------------------------------------------------------------------------

ACTION = {"run_assessment": {"label": "run an assessment of any area (code, Gnomon, an eval set, checks, alignment, "
                                      "Optimise, the IT check set)", "personas": PERSONAS, "per_project": True}}


def fields(factory: Any, a: dict[str, Any]) -> dict[str, Any]:
    kind, name = parse(a.get("target") or "infra")
    return {"target": f"{kind}:{name}" if name else kind}


def handle(factory: Any, a: dict[str, Any], f: dict[str, Any], tools: Any) -> dict[str, Any]:
    """Run the target on the firing's project with the owner's rights; its outcome for the automation's history."""
    if not f.get("project"):
        raise ValueError("run_assessment acts on a project, and the firing names none")
    project = factory.project(f["project"])
    owner = a["owner"]
    try:
        got = run(project, a["action"]["target"], person=owner["person"], persona=owner["persona"],
                  via=f"automation {a['id']}")
    except DecisionRefused as exc:
        return _out("refused", str(exc))
    return {k: got[k] for k in ("outcome", "verdict", "detail", "refs")}


def register(automations: Any, actions: Any) -> None:
    """Add run_assessment to the allow-list, its field and its handler (idempotent)."""
    automations.ACTIONS.update(ACTION)
    automations._ACTION_FIELDS["run_assessment"] = fields
    if hasattr(actions, "HANDLERS"):
        actions.HANDLERS["run_assessment"] = handle


def public() -> list[dict[str, str]]:
    """The targets as the cockpit offers them."""
    return [{"id": k, "label": v} for k, v in TARGETS.items()]
