"""QA: how often the gate passes the work, in how many rounds, and whether its signals agree, from the ledger.

- the gate's verdicts (``gate`` events: each round's verdict and its signals' verdicts, kernel/gate.py);
- holdouts (``holdouts_run``: scenarios passed and failed against a running service, and a release's
  ``release_step`` holdout steps);
- flaky reruns (``reflex_retry``: the harness stopped for a transient reason and the round ran again).

A verdict the gate could not measure is counted beside a rate, never in it (kernel/metrics.py's rule).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from kernel.insights.base import (
    PREVIOUS_WORDS,
    Scope,
    answer,
    chart,
    delta,
    gap,
    level,
    median,
    obj,
    series_rows,
    share,
    tile,
    unit_of,
)
from kernel.insights.evals import tiles as gnomon_tiles
from kernel.insights.lines import change, count

SIGNALS = ("tests", "trace", "fail_first", "verifier")
SIGNAL_WORDS = {"tests": "Tests", "trace": "Trace", "fail_first": "Fail-first", "verifier": "Verifier"}
HOW_GATE = "build a task (rihmasto build <pid>), or gate your own change (rihmasto repo gate <pid>)"
NO_GATE = "no gate verdict in the window"
Row = dict[str, Any]


def _gates(scope: Scope, previous: bool = False) -> list[Row]:
    return [{"project": p, "at": t, "task": pl.get("task"), "round": pl.get("round"), "verdict": pl.get("verdict"),
             "signals": obj(pl.get("signals"))} for p, t, pl, _ in scope.events("gate", previous=previous)]


def _rate(gates: list[Row]) -> tuple[float | None, int, int]:
    measured = [g for g in gates if g["verdict"] and g["verdict"] != "not measured"]
    passed = sum(1 for g in measured if g["verdict"] == "passed")
    return share(passed, len(measured)), passed, len(measured)


def _rounds(gates: list[Row]) -> dict[tuple, int]:
    out: dict[tuple, int] = {}
    for g in gates:
        if g["task"] is not None and isinstance(g["round"], int):
            key = (g["project"].pid, g["task"])
            out[key] = max(out.get(key, 0), g["round"] + 1)
    return out


def _context(scope: Scope) -> dict[str, Any]:
    gates = _gates(scope)
    return {"scope": scope, "gates": gates, "before": _gates(scope, previous=True), "rounds": _rounds(gates),
            "period": PREVIOUS_WORDS.get(scope.window, "")}


def _t_rate(c: dict[str, Any]) -> Row:
    rate, passed, measured = _rate(c["gates"])
    brate = _rate(c["before"])[0]
    plain = f"The gate passed {passed} of {measured} rounds."
    return tile("pass_rate", "Gate pass rate", rate, unit="%", basis="ledger gate verdicts (not measured left out)",
                delta=delta(rate, brate, c["period"]), sub=f"{passed} of {measured} rounds",
                status=level(rate, 70, 40),
                line=change("The gate pass rate", rate, brate, c["scope"].window, "%") or plain,
                why=NO_GATE, how=HOW_GATE)


def _t_rounds(c: dict[str, Any]) -> Row:
    rounds = c["rounds"]
    per_task = median(list(rounds.values()))
    many = sorted(((v, k) for k, v in rounds.items() if v >= 3), reverse=True)
    line = f"Each task needed {per_task} rounds at the median."
    href = None
    if many:
        (most, (pid, task)) = many[0]
        line = f"{count(len(many), 'task')} needed 3 or more rounds; the most was {most} ({task})."
        href = f"#/p/{pid}/tasks/{task}"
    return tile("rounds_per_task", "Rounds per task", per_task, sub=count(len(rounds), "task"), href=href,
                basis="the highest round each gated task reached (median)", line=line, why=NO_GATE, how=HOW_GATE)


def _t_first(c: dict[str, Any]) -> Row:
    first = [g for g in c["gates"] if g["round"] == 0 and g["verdict"] and g["verdict"] != "not measured"]
    rate = share(sum(1 for g in first if g["verdict"] == "passed"), len(first))
    return tile("first_round", "First-round passes", rate, unit="%", basis="round 0 gate verdicts",
                line=f"{rate}% of the tasks passed their gate on the first round.",
                why="no first round was gated in the window", how=HOW_GATE)


def _t_fail_first(c: dict[str, Any]) -> Row:
    judged = [g["signals"].get("fail_first") for g in c["gates"]]
    judged = [v for v in judged if v in ("passed", "failed")]
    held = judged.count("passed")
    return tile("fail_first", "Fail-first held", share(held, len(judged)), unit="%",
                sub=f"{held} of {len(judged)} rounds", basis="the gate's fail_first signal (passed against failed)",
                line=f"The criteria's tests failed before the change in {held} of {len(judged)} rounds.",
                why="no round in the window was judged on fail-first (a task with no visible criteria is not "
                    "applicable)",
                how=HOW_GATE)


def _t_disagree(c: dict[str, Any]) -> Row:
    pair = ("passed", "failed")
    both = [g for g in c["gates"] if g["signals"].get("tests") in pair and g["signals"].get("verifier") in pair]
    n = sum(1 for g in both if g["signals"]["tests"] != g["signals"]["verifier"])
    return tile("verifier_disagreements", "Verifier disagreements", n if both else None,
                basis="rounds where the tests and the independent verifier gave different verdicts",
                line=f"The verifier and the tests disagreed in {n} of {len(both)} rounds.",
                status=level(n, 0, 1, higher_is_better=False),
                why="no round in the window has both a tests and a verifier verdict", how=HOW_GATE)


def _holdouts(scope: Scope) -> tuple[int, int, str]:
    passed = total = 0
    for _, _, pl, _ in scope.events("holdouts_run"):
        if isinstance(pl.get("passed"), int) and isinstance(pl.get("scenarios"), int):
            passed, total = passed + pl["passed"], total + pl["scenarios"]
    if total:
        return passed, total, "scenarios"
    steps = [pl.get("outcome") for _, _, pl, _ in scope.events("release_step")
             if str(pl.get("step") or "").startswith("holdout") and pl.get("outcome") in ("passed", "failed")]
    return steps.count("passed"), len(steps), "release holdout steps"


def _t_holdouts(c: dict[str, Any]) -> Row:
    passed, total, unit = _holdouts(c["scope"])
    return tile("holdout_rate", "Holdout pass rate", share(passed, total), unit="%", basis=f"holdouts_run ({unit})",
                sub=f"{passed} of {total} {unit}", line=f"{passed} of {total} holdout {unit} passed.",
                why="no holdout ran in the window",
                how="run the holdouts against a running service (rihmasto repo holdouts <pid> --base-url URL) or "
                    "deliver "
                    "a release whose road runs them")


def _t_reruns(c: dict[str, Any]) -> Row:
    n = sum(1 for _ in c["scope"].events("reflex_retry"))
    line = (f"The harness stopped for a transient reason and ran again {count(n, 'time')}." if n
            else "No round needed a rerun for a transient stop.")
    return tile("flaky_reruns", "Flaky reruns", n if c["gates"] or n else None, line=line,
                basis="ledger reflex_retry: a round run again after a transient stop",
                why="no round ran in the window", how=HOW_GATE)


def _signal_rows(gates: list[Row]) -> list[Row]:
    rows = []
    for name in SIGNALS:
        c = Counter(g["signals"].get(name) for g in gates if name in g["signals"])
        if c:
            rows.append({"label": SIGNAL_WORDS[name], "values": {k: c.get(k, 0) for k in ("passed", "failed",
                                                                                          "not measured")}})
    return rows


def _charts(c: dict[str, Any], tiles: list[Row]) -> list[Row]:
    scope, gates, rounds = c["scope"], c["gates"], c["rounds"]
    bins = Counter(min(v, 5) for v in rounds.values())
    dist = [{"label": f"{n} round{'s' if n > 1 else ''}" if n < 5 else "5 or more", "value": bins.get(n, 0)}
            for n in range(1, 6)] if rounds else []
    titles = {p.pid: scope.title(p) for p in scope.projects}
    worst = [{"label": task, "value": n, "sub": titles.get(pid) if scope.pid is None else None,
              "href": f"#/p/{pid}/tasks/{task}"}
             for (pid, task), n in sorted(rounds.items(), key=lambda kv: -kv[1])[:10]]
    points = [(g["at"], "passed" if g["verdict"] == "passed" else "not_passed", 1) for g in gates]
    return [
        chart("verdicts", "Gate verdicts over time", "columns", rows=series_rows(scope, points), unit="rounds",
              series=[{"key": "passed", "label": "Passed", "status": "good"},
                      {"key": "not_passed", "label": "Not passed", "status": "critical"}],
              basis="ledger gate verdicts per " + unit_of(scope.window), line=tiles[0]["line"], why=NO_GATE,
              how=HOW_GATE),
        chart("rounds", "Rounds each task needed", "bars", rows=dist, unit="tasks", line=tiles[1]["line"],
              basis="the highest round each gated task reached", why=NO_GATE, how=HOW_GATE),
        chart("signals", "The gate's signals", "stack100", rows=_signal_rows(gates), unit="rounds",
              series=[{"key": "passed", "label": "Passed", "status": "good"},
                      {"key": "failed", "label": "Failed", "status": "critical"},
                      {"key": "not measured", "label": "Not measured", "hatch": True}],
              basis="each round's signals: tests, trace, fail-first, verifier (kernel/gate.py)", line=tiles[3]["line"],
              why=NO_GATE, how=HOW_GATE),
        chart("most_rounds", "Tasks with the most rounds", "bars", unit="rounds", rows=worst, line=tiles[1]["line"],
              basis="the highest round each gated task reached", why=NO_GATE, how=HOW_GATE),
    ]


def read(scope: Scope) -> dict[str, Any]:
    c = _context(scope)
    tiles = [_t_rate(c), _t_rounds(c), _t_first(c), _t_fail_first(c), _t_disagree(c), _t_holdouts(c), _t_reruns(c)]
    tiles += gnomon_tiles(scope, "qa")          # Gnomon's audits and evals (kernel/insights/evals.py, FR-EVL1)
    gaps = [gap("Test counts over time", "the gate records each signal's verdict, not how many tests ran",
                "your CI's own test reports carry the counts; send them to your observability tools beside this "
                "export")]
    return answer(scope, "qa", tiles, _charts(c, tiles), gaps)
