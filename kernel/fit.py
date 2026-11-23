"""Measured fit: how each model and endpoint fits each workload class, from the records only (FR-F9).

A **workload class** is how the work is used:
- **interactive:** a person waits for the answer (the cockpit assistant, a website chat);
- **batch:** nobody waits on each call (the analyst, the builder, the verifier, the holdout author);
- **specialist:** a narrow job a person names as such (a classifier, an extractor). No factory role
  is specialist by rule; a person maps a role or a use case to it.

The **registry** has one row per role, model, endpoint and workload class, built from:
- the `gnomon_run` events in every project ledger: runs, the pass rate over measured runs (apparatus
  failures and not-measured runs counted beside it, never in it), tokens, and latency and throughput
  when a run carries Gnomon's `duration_ms`;
- the gate's first-round verdicts on each builder model's cells (`cell_ran` and `gate` events): the
  factory's own judgement of the work, since a builder cell in a grant-free lane has no verify of its
  own;
- `gnomon eval` reports, imported read-only (schema `gnomon.eval/3`, Gnomon's CONTRACTS section 47):
  each arm's passes over valid cells, its output tokens and its wall-clock time.

Nothing is estimated. A value with no record behind it is None and the row says why. Rihma's Gnomon
ingest (`adapters/gnomon_ingest.py`) does not keep the run's duration today, so ledger rows say
latency is not measured.

The **report** maps use cases to workload classes by rule, lists the measured candidates, recommends
one per workload class by a fixed rule, and says what was not measured and what would change each
recommendation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

from kernel.metrics import pass_rate

WORKLOADS = ("interactive", "batch", "specialist")
WORKLOAD_BY_ROLE = {"builder": "batch", "verifier": "batch", "analyst": "batch", "holdout_author": "batch",
                    "assistant": "interactive", "embed": "interactive"}
EVAL_SCHEMA = "gnomon.eval/3"
MIN_RUNS = 5
NEAR = 0.05  # interactive: pass rates within this of the best are level, and latency decides
NO_DURATION = ("latency: not measured: Rihma's Gnomon ingest does not keep the run's duration "
               "(Gnomon records it as volatile.duration_ms)")
USE_CASE_WORDS = {
    "interactive": ("chat", "assistant", "answer", "embed", "website", "real time", "real-time", "interactive",
                    "conversation", "help desk", "helpdesk", "customer support", "copilot", "live"),
    "batch": ("batch", "nightly", "overnight", "build", "report", "backfill", "pipeline", "review", "verify",
              "spec", "bulk", "scheduled", "weekly", "daily"),
    "specialist": ("classif", "extract", "ocr", "vision", "image", "speech", "transcri", "translat", "embedding",
                   "rerank", "fine-tun", "domain model"),
}
RULES = {
    "interactive": f"the best pass rate decides, but among candidates within {NEAR} of it the lowest measured "
                   "mean latency wins; at least the minimum of measured runs",
    "batch": "the best pass rate wins; then more measured runs; then fewer output tokens per run; "
             "at least the minimum of measured runs",
    "specialist": "the best pass rate wins; then more measured runs; then fewer output tokens per run; "
                  "at least the minimum of measured runs",
}


def workload_of(role: str | None, roles: dict | None = None) -> str | None:
    """A role's workload class: a person's mapping first, then the factory's rule. None when neither
    names it: an unmapped role is said, never guessed."""
    if role is None:
        return None
    named = (roles or {}).get(role)
    if named in WORKLOADS:
        return str(named)
    return WORKLOAD_BY_ROLE.get(role)


# -- rows from the ledgers ----------------------------------------------------------------------------

def _latency(timed: list) -> dict | None:
    if not timed:
        return None
    ms = [float(r["duration_ms"]) for r in timed]
    return {"mean_ms": round(mean(ms), 1), "median_ms": round(median(ms), 1), "runs_timed": len(ms)}


def _throughput(timed: list) -> float | None:
    """Output tokens per second over the runs that recorded both."""
    both = [r for r in timed if (r.get("tokens") or {}).get("out") is not None and r["duration_ms"]]
    if not both:
        return None
    return round(sum(r["tokens"]["out"] for r in both) / (sum(float(r["duration_ms"]) for r in both) / 1000), 2)


def _tokens(runs: list) -> dict:
    counted = [r["tokens"] for r in runs if (r.get("tokens") or {}).get("out") is not None]
    ins = [t["in"] for t in counted if t.get("in") is not None]
    return {"in": sum(ins) if ins else None, "out": sum(t["out"] for t in counted) if counted else None,
            "runs_counted": len(counted),
            "mean_out_per_run": round(sum(t["out"] for t in counted) / len(counted), 1) if counted else None}


def _gaps(row: dict) -> list:
    gaps = []
    if row["pass_rate"] is None:
        gaps.append(f"pass rate: no measured run ({row.get('not_measured_runs', 0)} not measured, "
                    f"{row.get('apparatus_failures', 0)} apparatus failures)")
    if row["tokens"]["out"] is None:
        gaps.append("tokens: no run reported token counts")
    if row["latency"] is None:
        gaps.append(NO_DURATION if row["source"].startswith("ledger") else "latency: not in the record")
    if row["endpoint"] is None:
        gaps.append("endpoint: the record does not name it")
    if row["workload"] is None:
        gaps.append(f"workload class: no rule maps the role {row['role']!r}; name its class")
    return gaps


def _run_row(key: tuple, runs: list, roles: dict | None) -> dict:
    role, model, endpoint = key
    rate = pass_rate(runs)
    timed = [r for r in runs if _number(r.get("duration_ms")) is not None]
    row = {"source": "ledger: gnomon_run", "role": role, "model": model, "endpoint": endpoint,
           "workload": workload_of(role, roles), "runs": len(runs), "measured": rate["measured"],
           "passed": rate["passed"], "pass_rate": rate["rate"], "not_measured_runs": rate["not_measured"],
           "apparatus_failures": rate["apparatus_failures"], "tokens": _tokens(runs), "latency": _latency(timed),
           "throughput_tokens_per_s": _throughput(timed), "projects": sorted({r["_project"] for r in runs})}
    row["not_measured"] = _gaps(row)
    return row


def _first_rounds(project: Any) -> list:
    """(model, passed) for every builder cell's first-round gate in one project. A person's own
    workspace submission (a gate record with an author) is not a model's work and is left out. Events
    are read in ledger order, so a task built again later is judged against the cell just before it."""
    cells: dict = {}
    out = []
    for rec in project.ledger().of_kind("cell_ran", "gate"):
        pl, kind = rec["event"]["payload"], rec["event"]["kind"]
        key = (pl.get("task"), pl.get("round"))
        if kind == "cell_ran":
            cells[key] = pl.get("final_model") or pl.get("model")
        elif pl.get("round") == 0 and not pl.get("author") and cells.get(key):
            out.append((str(cells[key]), pl.get("verdict") == "passed"))
    return out


def _gate_rows(factory: Any, roles: dict | None) -> list:
    by_model: dict = defaultdict(lambda: {"n": 0, "passed": 0, "projects": set()})
    for project in factory.projects():
        for model, passed in _first_rounds(project):
            by_model[model]["n"] += 1
            by_model[model]["passed"] += int(passed)
            by_model[model]["projects"].add(project.pid)
    rows = []
    for model, s in sorted(by_model.items()):
        row = {"source": "ledger: gate, first round", "role": "builder", "model": model, "endpoint": None,
               "workload": workload_of("builder", roles), "runs": s["n"], "measured": s["n"], "passed": s["passed"],
               "pass_rate": s["passed"] / s["n"], "tokens": _tokens([]), "latency": None,
               "throughput_tokens_per_s": None, "projects": sorted(s["projects"])}
        row["not_measured"] = _gaps(row)
        rows.append(row)
    return rows


# -- rows from a Gnomon eval report --------------------------------------------------------------------

def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _arm_figures(report: dict, name: str) -> dict:
    """One arm's figures as the report holds them (`endpoints`: pass, output_tokens, wall_ms). Valid
    cells are the arm's measured runs; `wall_ms` is the sum of their durations."""
    ep = report.get("endpoints") or {}
    score = (ep.get("pass") or {}).get(name) or {}
    n, passes = score.get("n"), score.get("passes")
    ok = isinstance(n, int) and isinstance(passes, int) and n > 0
    return {"n": n if ok else 0, "passes": passes if ok else 0,
            "out": _number((ep.get("output_tokens") or {}).get(name)),
            "wall": _number((ep.get("wall_ms") or {}).get(name))}


def _arm_row(report: dict, name: str, source: str, roles: dict | None) -> dict | None:
    arm = (report.get("arms") or {}).get(name)
    if not isinstance(arm, dict):
        return None
    f = _arm_figures(report, name)
    n, out, wall = f["n"], f["out"], f["wall"]
    per_run = round(out / n, 1) if out is not None and n else None
    row = {"source": source, "role": report.get("role"), "model": arm.get("model") or arm.get("label"),
           "endpoint": arm.get("endpoint"), "workload": workload_of(report.get("role"), roles), "runs": n,
           "measured": n, "passed": f["passes"], "pass_rate": f["passes"] / n if n else None,
           "tokens": {"in": None, "out": out, "runs_counted": n if out is not None else 0, "mean_out_per_run": per_run},
           "latency": {"mean_ms": round(wall / n, 1), "median_ms": None, "runs_timed": n} if wall and n else None,
           "throughput_tokens_per_s": round(out / (wall / 1000), 2) if out is not None and wall else None,
           "projects": [], "status": report.get("status")}
    row["not_measured"] = _gaps(row)
    if arm.get("kind") == "command":
        row["not_measured"].append("tokens: Gnomon does not meter a command arm")
    return row


def import_eval_report(path: str | Path, roles: dict | None = None) -> dict:
    """Rows from one `gnomon eval` report file, read only. A file in any other format is not imported,
    and the result says so: its rows are not measured."""
    path = Path(path)
    try:
        raw = path.read_bytes()
        report = json.loads(raw)
    except (OSError, ValueError) as exc:
        return {"file": path.name, "rows": [], "not_imported": f"{path.name}: could not be read ({exc})"}
    if not isinstance(report, dict) or report.get("schema") != EVAL_SCHEMA:
        got = report.get("schema") if isinstance(report, dict) else type(report).__name__
        return {"file": path.name, "rows": [],
                "not_imported": f"{path.name}: schema {got!r} is not {EVAL_SCHEMA}, the documented report format"}
    sha = hashlib.sha256(raw).hexdigest()
    spec = (report.get("spec") or {}).get("name") or "?"
    source = f"gnomon eval: {path.name}, spec {spec}, sha256 {sha[:12]}"
    rows = [r for r in (_arm_row(report, name, source, roles) for name in ("base", "candidate")) if r]
    return {"file": path.name, "sha256": sha, "rows": rows, "not_imported": None}


def registry(factory: Any, *, eval_reports: tuple | list = (), roles: dict | None = None) -> dict:
    """Every measured row: Gnomon runs and gate rounds from the ledgers, and imported eval reports."""
    groups: dict = defaultdict(list)
    for project in factory.projects():
        for rec in project.ledger().of_kind("gnomon_run"):
            pl = rec["event"]["payload"]
            key = (pl.get("role") or "unknown", pl.get("model") or "unknown", pl.get("endpoint"))
            groups[key].append({**pl, "_project": project.pid})
    rows = [_run_row(k, v, roles) for k, v in sorted(groups.items(), key=lambda kv: tuple(map(str, kv[0])))]
    rows += _gate_rows(factory, roles)
    imports = [import_eval_report(p, roles) for p in eval_reports]
    for imp in imports:
        rows += imp["rows"]
    return {"rows": rows, "imports": [{k: v for k, v in imp.items() if k != "rows"} for imp in imports]}


# -- use cases and the rule --------------------------------------------------------------------------

def map_use_case(use_case: Any, roles: dict | None = None) -> dict:
    """A use case's workload class: as a person named it, by its role, or by keywords. When no rule
    matches, or two classes match equally, it is not mapped and says why."""
    if isinstance(use_case, dict):
        name, named, role = str(use_case.get("name") or "?"), use_case.get("workload"), use_case.get("role")
    else:
        name, named, role = str(use_case), None, None
    if named in WORKLOADS:
        return {"use_case": name, "workload": named, "basis": "named by a person"}
    if role and workload_of(role, roles):
        return {"use_case": name, "workload": workload_of(role, roles), "basis": f"its role, {role}"}
    low = name.lower()
    hits = {w: [k for k in USE_CASE_WORDS[w] if re.search(r"\b" + re.escape(k), low)] for w in WORKLOADS}
    best = max(len(h) for h in hits.values())
    winners = [w for w in WORKLOADS if best and len(hits[w]) == best]
    if not winners:
        return {"use_case": name, "workload": None, "basis": "not mapped: no rule matched; name its workload class"}
    if len(winners) > 1:
        return {"use_case": name, "workload": None,
                "basis": f"not mapped: it matches {' and '.join(winners)} equally; name its workload class"}
    return {"use_case": name, "workload": winners[0], "basis": "keywords: " + ", ".join(hits[winners[0]])}


def label(row: dict) -> str:
    return f"{row['model']}@{row['endpoint'] or '?'} as {row['role']}"


def _rank(workload: str, rows: list) -> list:
    inf = float("inf")
    if workload == "interactive":
        top = max(r["pass_rate"] for r in rows)
        return sorted(rows, key=lambda r: (r["pass_rate"] < top - NEAR, (r["latency"] or {}).get("mean_ms") or inf,
                                           -r["pass_rate"], -r["measured"], label(r)))
    return sorted(rows, key=lambda r: (-r["pass_rate"], -r["measured"], r["tokens"]["mean_out_per_run"] or inf,
                                       label(r)))


def _next_in_line(workload: str, ranked: list) -> str:
    best, nxt = ranked[0], ranked[1]
    it = f"(it is {nxt['pass_rate']:.2f} over {nxt['measured']} measured runs)"
    if workload != "interactive":
        return f"{label(nxt)} would lead if its pass rate rose above {best['pass_rate']:.2f} {it}"
    floor = max(r["pass_rate"] for r in ranked) - NEAR
    if nxt["pass_rate"] < floor:
        return f"{label(nxt)} would be weighed on latency if its pass rate rose to {floor:.2f} or more {it}"
    mine, theirs = (best["latency"] or {}).get("mean_ms"), (nxt["latency"] or {}).get("mean_ms")
    if mine is not None and theirs is not None:
        return f"{label(nxt)} would lead if its mean latency fell below {mine} ms (it is {theirs} ms)"
    return f"{label(nxt)} is level on pass rate {it}, and a latency is not measured"


def _would_change(workload: str, ranked: list, under: list, min_runs: int) -> list:
    out = [_next_in_line(workload, ranked)] if len(ranked) > 1 else []
    out += [f"{label(r)} has {r['measured']} of the {min_runs} measured runs the rule needs; with more it is ranked"
            for r in under]
    unmeasured = [label(r) for r in ranked if r["latency"] is None]
    if workload == "interactive" and unmeasured:
        out.append("latency is not measured for " + ", ".join(unmeasured) + "; measured latency could change "
                   "the choice")
    return out or ["a new candidate with a better measured pass rate"]


def recommend(workload: str, rows: list, min_runs: int = MIN_RUNS) -> dict:
    """One recommendation for a workload class by its fixed rule, with what would change it."""
    rated = [r for r in rows if r["workload"] == workload and r["pass_rate"] is not None]
    qualified = [r for r in rated if r["measured"] >= min_runs]
    under = [r for r in rated if r["measured"] < min_runs]
    out: dict = {"workload": workload, "rule": RULES[workload], "min_runs": min_runs, "choice": None}
    if not qualified:
        why = "no record for this workload class" if not rated else f"no candidate has {min_runs} measured runs"
        changes = [f"{label(r)} reaching {min_runs} measured runs (it has {r['measured']})" for r in under]
        return out | {"why": why,
                      "would_change": changes or [f"{min_runs} measured runs of any model on {workload} work"]}
    ranked = _rank(workload, qualified)
    best = ranked[0]
    lat = (best["latency"] or {}).get("mean_ms")
    why = (f"pass rate {best['pass_rate']:.2f} over {best['measured']} measured runs"
           + (f", mean latency {lat} ms" if lat is not None else "") + f" ({best['source']})")
    return out | {"choice": label(best), "model": best["model"], "endpoint": best["endpoint"], "role": best["role"],
                  "why": why, "would_change": _would_change(workload, ranked, under, min_runs)}


def assess(factory: Any, use_cases: list, *, eval_reports: tuple | list = (), roles: dict | None = None,
           min_runs: int = MIN_RUNS) -> dict:
    """The fit as data: use cases mapped, the rows, a recommendation per workload class, and what was
    not measured."""
    reg = registry(factory, eval_reports=eval_reports, roles=roles)
    mapped = [map_use_case(u, roles) for u in use_cases]
    recs = {w: recommend(w, reg["rows"], min_runs) for w in WORKLOADS}
    missing = [f"{label(r)} ({r['source']}): {g}" for r in reg["rows"] for g in r["not_measured"]]
    missing += [f"{w}: no measured row" for w in WORKLOADS if not any(r["workload"] == w for r in reg["rows"])]
    missing += [f"use case {m['use_case']!r}: {m['basis']}" for m in mapped if m["workload"] is None]
    missing += [i["not_imported"] for i in reg["imports"] if i.get("not_imported")]
    if not eval_reports:
        missing.append("benchmarks: no Gnomon eval report was imported, so no benchmark row is measured")
    return {"use_cases": mapped, "rows": reg["rows"], "imports": reg["imports"], "recommendations": recs,
            "not_measured": missing, "min_runs": min_runs}


# -- the markdown report -----------------------------------------------------------------------------

def _cell(value: Any, unit: str = "") -> str:
    return "not measured" if value is None else f"{value}{unit}"


def _rows_table(rows: list) -> list:
    lines = ["| Role | Model | Endpoint | Source | Runs | Measured | Pass rate | Tokens out per run | Mean latency "
             "| Throughput |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        rate = f"{r['pass_rate']:.2f} ({r['passed']}/{r['measured']})" if r["pass_rate"] is not None else "not measured"
        lines.append(f"| {r['role']} | {r['model']} | {r['endpoint'] or 'not recorded'} | {r['source']} | {r['runs']} "
                     f"| {r['measured']} | {rate} | {_cell(r['tokens']['mean_out_per_run'])} "
                     f"| {_cell((r['latency'] or {}).get('mean_ms'), ' ms')} "
                     f"| {_cell(r['throughput_tokens_per_s'], ' tokens/s')} |")
    return lines


def _candidates(rows: list) -> list:
    lines = ["## Measured candidates", ""]
    for w in WORKLOADS:
        mine = [r for r in rows if r["workload"] == w]
        lines += [f"### {w}", ""] + (_rows_table(mine) if mine else ["No record."]) + [""]
    unmapped = [r for r in rows if r["workload"] is None]
    if unmapped:
        lines += ["### not mapped to a workload class", ""] + _rows_table(unmapped) + [""]
    return lines


def _recommendation(rec: dict, users: list) -> list:
    head = (f"**Recommended: {rec['choice']}**: {rec['why']}." if rec["choice"]
            else f"**No recommendation**: {rec['why']}.")
    return ([f"### {rec['workload']}", "", f"Use cases: {', '.join(users) or 'none'}.", "", head, "",
             f"Rule: {rec['rule']} (minimum {rec['min_runs']}).", "", "What would change it:"]
            + [f"- {c}" for c in rec["would_change"]] + [""])


def render(fit: dict) -> str:
    """The fit as a markdown report."""
    lines = ["# Measured fit", "", "Every row comes from a record: Gnomon runs and gate rounds in the project ledgers, "
             "and imported Gnomon eval reports. Nothing is estimated; what has no record says not measured.", "",
             "## Use cases", "", "| Use case | Workload class | Basis |", "|---|---|---|"]
    lines += [f"| {m['use_case']} | {m['workload'] or 'not mapped'} | {m['basis']} |" for m in fit["use_cases"]]
    lines += [""] + _candidates(fit["rows"]) + ["## Recommendations", ""]
    for w in WORKLOADS:
        users = [m["use_case"] for m in fit["use_cases"] if m["workload"] == w]
        lines += _recommendation(fit["recommendations"][w], users)
    lines += ["## Not measured", ""] + ([f"- {m}" for m in fit["not_measured"]] or ["- nothing"])
    return "\n".join(lines).rstrip() + "\n"


def fit_report(factory: Any, use_cases: list, *, eval_reports: tuple | list = (), roles: dict | None = None,
               min_runs: int = MIN_RUNS) -> str:
    """A markdown report: use cases mapped to workload classes, the measured candidates, a rule-based
    recommendation per workload class, what was not measured, and what would change each choice."""
    return render(assess(factory, use_cases, eval_reports=eval_reports, roles=roles, min_runs=min_runs))
