"""What a project's own sources change in what Rihmasto shows of it (FR-SRC1).

- **The view** of the "Project's own sources" panel: what is mapped and when it was last read, what is detected and
  not mapped (each with Map), the planning documents that may be old plans (each with Use it anyway), the test
  roots, the latest runs and imports, the trace, and the next steps from that state, as buttons.
- **The trace**: each requirement of a mapped source, the tests its own record names, and their latest result
  (a run here, a results file imported or committed), with the run it came from.
- **Alignment** (kernel/alignment_records.py ``scan``): a planning document that may be an old plan is left out
  unless a person said to use it; with requirements or tasks mapped, those come from the mapped sources instead
  of documents, and the tests a requirement names trace to it "by the project's own source".
- **Understanding** (kernel/understanding.py): its tests from the project's own runs, its contract from its own
  requirements, its findings from its own file, and the misleading "not measured" gaps cleared.
"""

from __future__ import annotations

from typing import Any

from kernel import native_detect as nd
from kernel import native_sources as ns
from kernel import native_tests as nt

OWN = "project's own source"
RESULTS = ("passed", "failed", "not run", "no test named")
CLOSED = ("closed", "fixed", "resolved", "done", "wontfix")
RUN_KEYS = ("id", "from", "root", "name", "command", "verdict", "counts", "at", "produced_at", "machine", "reason")
ORDER = {"requirements": 0, "tasks": 1, "findings": 2, "results": 3, "tests": 4}


def _cases(project: Any, last: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    """Each case's latest status: committed results files first, then the runs and imports (newest wins)."""
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for res in last.get("results") or []:
        run = {"name": res["path"], "from": "committed", "path": res["path"], "date": res.get("date")}
        for c in res.get("cases") or []:
            out[str(c["name"])] = (c["status"], run)
    out.update(nt.case_status(project))
    return out


def _said(run: dict[str, Any] | None) -> str | None:
    if run is None:
        return None
    if run.get("from") == "committed":
        return f"committed in {run['path']}"
    return nt.line(run)


def _result(states: list[str]) -> str:
    if not states:
        return "no test named"
    if "failed" in states:
        return "failed"
    return "passed" if all(s == "passed" for s in states) else "not run"


def _trace_row(q: dict[str, Any], cases: dict[str, tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    got = [(t, *nt.status_of(t, cases)) for t in q.get("tests") or []]
    run = next((r for _, _, r in got if r is not None), None)
    return {"ref": q.get("ref"), "title": q["title"], "path": q["path"], "line": q["line"],
            "tests": [{"name": t, "status": s} for t, s, _ in got], "result": _result([s for _, s, _ in got]),
            "from": _said(run), "criteria": len(q.get("criteria") or [])}


def trace(project: Any) -> dict[str, Any]:
    last = ns.latest_read(project)
    cases = _cases(project, last)
    rows = [_trace_row(q, cases) for q in last.get("requirements") or []]
    counts = {k: sum(1 for r in rows if r["result"] == k) for k in RESULTS}
    n = len(rows)
    line = (f"{n} requirement(s) from the project's own source: {counts['passed']} passed, {counts['failed']} failed, "
            f"{counts['not run']} with a test not run yet, {counts['no test named']} naming no test") if n else None
    return {"rows": rows[:500], "counts": {"requirements": n, **counts}, "line": line}


# -- the panel -------------------------------------------------------------------------------------------

def _map_steps(v: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for p in sorted(v["detected"], key=lambda p: ORDER[p["kind"]])[:4]:
        said = (f"Use {p['sample']} as its test roots" if p["kind"] == "tests"
                else f"Use {p['glob']} as {ns.KINDS[p['kind']].lower()}")
        out.append({"label": said, "why": p["why"], "do": {"kind": "map", "key": p["key"]}})
    return out


def _run_steps(v: dict[str, Any]) -> list[dict[str, Any]]:
    roots = ns.mapped_roots_of(v["mapped"])
    ran = {r.get("root") for r in v["runs"]}
    out = [{"label": f"Run the tests of {r['root'] or 'the repository root'}", "do": {"kind": "run", "root": r["root"]},
            "why": f"`{r['command']}` has not run here yet; it runs the project's own code after you say yes"}
           for r in roots if r["root"] not in ran]
    if roots and not any(r.get("from") == "imported" for r in v["runs"]):
        out.append({"label": "Import results of a run elsewhere", "do": {"kind": "import"},
                    "why": "a gate run on another machine: its results file, with the time it was produced"})
    return out


def _next(v: dict[str, Any], align: list[dict[str, Any]] | None = None,
          watch: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The next steps from this state, each a button (guide, don't describe)."""
    steps = [{"label": "Read the sources again", "do": {"kind": "read"},
              "why": "the repository has a newer commit than the one last read"}] if v.get("newer") else []
    steps += _map_steps(v) + list(align or []) + _run_steps(v) + list(watch or [])
    steps += [{"label": f"Use {s['path']} anyway", "why": s["why"], "do": {"kind": "use_anyway", "path": s["path"]}}
              for s in v["stale"][:2]]
    if not steps and not v["mapped"]:
        steps.append({"label": "Tell Rihma where they are", "do": {"kind": "ask",
                      "question": "Where does this project keep its requirements?"},
                      "why": "nothing was found by rule: say which files hold the requirements, tasks, findings "
                             "or test results, and Rihma proposes the mapping"})
    return steps


def _detected(project: Any) -> tuple[dict[str, Any], str | None]:
    try:
        return ns.proposals(project), None
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        return {"proposals": [], "stale": [], "rule": {}}, f"the repository could not be read: {exc}"


def _mapped(book: dict[str, Any], last: dict[str, Any]) -> list[dict[str, Any]]:
    read = last.get("sources") or {}
    return [{**s, "kind_label": ns.KINDS[s["kind"]], "every_said": ns.EVERY_SAID.get(s.get("every"), "when asked"),
             "last": read.get(s["id"])} for s in book["sources"]]


def _read_said(last: dict[str, Any]) -> dict[str, Any] | None:
    if not last:
        return None
    return {"at": last.get("at"), "revision": last.get("revision"),
            "counts": {k: len(last.get(k) or []) for k in ("requirements", "tasks", "findings", "results")}}


def _newer(last: dict[str, Any], det: dict[str, Any], mapped: list[dict[str, Any]]) -> bool:
    """Whether the repository moved since the sources were read, while any is mapped."""
    read, now = last.get("revision"), det.get("revision")
    return bool(read and now and read != now and any(s["state"] == "mapped" for s in mapped))


def view(project: Any) -> dict[str, Any]:
    """The "Project's own sources" panel. Reads the repository to detect; records nothing."""
    if not ns.applies(project):
        return {"applies": False, "scope": ns.SCOPE,
                "why": "this project has no repository of its own: its own sources are read from an adopted or "
                       "attached project's repository"}
    from kernel import native_guide as ng  # said truly: the watch, the review, stopped sources (FR-SRC2)

    book, last = ns._book(project), ns.latest_read(project)
    det, unreadable = _detected(project)
    mapped = _mapped(book, last)
    w = ng.every_said(project, mapped)
    taken = {(s["kind"], s["glob"]) for s in mapped if s["state"] == "mapped"}
    roots = next((p.get("roots") or [] for p in det["proposals"] if p["kind"] == "tests"), [])
    v = {"applies": True, "scope": ns.SCOPE, "mapped": mapped, "stale": det["stale"], "unreadable": unreadable,
         "stopped": ng.stopped(book), "watched": w, "fetch": last.get("fetch"),
         "detected": [p for p in ng.not_stopped(det["proposals"], book) if (p["kind"], p["glob"]) not in taken],
         "use_anyway": book.get("use_anyway") or [], "roots": roots, "root_note": nt.root_note(roots),
         "runs": [{k: r.get(k) for k in RUN_KEYS} | {"line": nt.line(r)} for r in reversed(nt.runs(project))][:10],
         "read": _read_said(last), "trace": trace(project),
         "rule": det.get("rule") or {"stale_days": nd.STALE_DAYS, "stale_commits": nd.STALE_COMMITS},
         "kinds": ns.KINDS, "every": ns.EVERY_SAID, "mappers": ns.MAPPERS, "schedule": book.get("schedule") or {},
         "newer": _newer(last, det, mapped)}
    v["next"] = _next(v, ng.align_step(project), ng.watch_step(w, mapped))
    return v


# -- alignment -------------------------------------------------------------------------------------------

def _specs(reqs: list[dict[str, Any]], dates: dict[str, int]) -> list[dict[str, Any]]:
    by_path: dict[str, list[dict[str, Any]]] = {}
    for q in reqs:
        by_path.setdefault(q["path"], []).append(q)
    return [{"path": p, "convention": OWN, "kind": "file", "feature": None, "title": p, "date": dates.get(p),
             "mentions": [], "requirements": [{"ref": q.get("ref"), "title": q["title"], "statement": q["statement"],
                                               "criteria": q.get("criteria") or [], "lines": q["lines"],
                                               "story": False} for q in rs]} for p, rs in sorted(by_path.items())]


def _with_tests(structure: dict[str, Any], reqs: list[dict[str, Any]]) -> dict[str, Any]:
    """The structure's tests plus each test a requirement's own record names, as the project's own."""
    tests = dict(structure.get("tests") or {"files": [], "count": 0, "frameworks": [], "run": [], "coverage": []})
    named = [{"path": q["path"], "framework": OWN, "date": None,
              "tests": [{"name": t, "line": q["line"], "suite": None, "doc": q.get("ref") or ""} for t in q["tests"]]}
             for q in reqs if q.get("tests")]
    tests["files"] = list(tests.get("files") or []) + named
    tests["count"] = int(tests.get("count") or 0) + sum(len(f["tests"]) for f in named)
    return tests


def _own_tasks(last: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"path": t["path"], "line": t["line"], "ref": t.get("ref"), "title": t["title"], "done": bool(t["done"]),
             "requirements": t.get("requirements") or []} for t in last.get("tasks") or []]


def _without_old_plans(project: Any, src: Any, out: dict[str, Any]) -> None:
    paths = [s["path"] for s in out.get("specs", [])] + [t["path"] for t in out.get("tasks", [])]
    old = {s["path"] for s in nd.stale_docs(src, paths, ns.use_anyway_paths(project))}
    out["specs"] = [s for s in out.get("specs", []) if s["path"] not in old]
    out["tasks"] = [t for t in out.get("tasks", []) if t["path"] not in old]
    out["old_plans"] = sorted(old)


def prepare(project: Any, structure: dict[str, Any]) -> dict[str, Any]:
    """The structure alignment proposes from: old plans left out, the project's own sources in."""
    if not ns.applies(project):
        return structure
    try:
        src = ns._src(project)
    except (ValueError, KeyError, OSError):
        return structure
    out = dict(structure)
    _without_old_plans(project, src, out)
    kinds = {s["kind"] for s in ns.active(project)}
    last = ns.latest_read(project) if kinds else {}
    if "requirements" in kinds:
        reqs = last.get("requirements") or []
        out["specs"], out["tests"] = _specs(reqs, src.dates), _with_tests(out, reqs)
    if "tasks" in kinds:
        out["tasks"] = _own_tasks(last)
    return out


def mark(proposal: dict[str, Any]) -> dict[str, Any]:
    """Items from the project's own sources say so; a test a requirement's own record names traces to it surely."""
    for i in proposal.get("items", []):
        src = i.get("source") or {}
        if src.get("convention") == OWN or src.get("framework") == OWN:
            i["native"] = {"path": src.get("path"), "line": (src.get("lines") or [None])[0]}
        if i.get("group") == "trace" and src.get("framework") == OWN:
            i.update(why=f"by the project's own source: {src['path']}:{src['lines'][0]} names this test",
                     basis="by the project's own source", confidence=1.0, weak=False)
    return proposal


# -- understanding and health ----------------------------------------------------------------------------

def _run_line(project: Any) -> str | None:
    latest = nt.latest(project)
    return "; ".join(nt.line(r) for r in list(latest.values())[-4:]) or None


def _native(mapped: list[dict[str, Any]], last: dict[str, Any], tr: dict[str, Any]) -> dict[str, Any]:
    from kernel.native_guide import finding_place
    findings = [f for f in last.get("findings") or [] if f.get("status") not in CLOSED]
    tasks = last.get("tasks") or []
    done = sum(1 for t in tasks if t["done"])
    return {"mapped": len(mapped), "read_at": last.get("at"), "trace": tr["line"],
            "findings": [f"{f['id']} {f['title']} ({f['severity']}, {f['status']}) at {finding_place(f)}"
                         for f in findings[:8]], "open_findings": len(findings),
            "tasks": {"open": len(tasks) - done, "done": done},
            "line": f"{len(mapped)} of its own source(s) mapped"
                    + (f", read {last['at']}" if last.get("at") else ", not read yet")}


def amend(project: Any, u: dict[str, Any]) -> dict[str, Any]:
    """The understanding with the project's own sources, when any is mapped or any run kept."""
    mapped = ns.active(project) if ns.applies(project) else []
    ran = _run_line(project)
    if not mapped and not ran:
        return u
    last, tr = ns.latest_read(project), trace(project)
    if ran:
        u["tests"] = f"from the project's own runs: {ran}"
        u["not_understood"] = [g for g in u.get("not_understood") or [] if not g.startswith("how to run its tests")]
    globs = [s["glob"] for s in mapped if s["kind"] == "requirements"]
    if globs:
        n = tr["counts"]["requirements"]
        u["contract"] = f"{n} requirement(s) in the project's own source ({', '.join(globs)})"
    u["native"] = _native(mapped, last, tr)
    return u


def baseline_passes_by_root(project: Any) -> bool:
    """Whether every mapped test root of the project's own ran here and its latest run passed: a root-level baseline
    that could not run then says nothing about it. A mapped root that never ran keeps the baseline counting."""
    roots = [r["root"] for r in ns.mapped_roots(project)] if ns.applies(project) else []
    latest = {k: r for k, r in nt.latest(project).items() if r.get("from") == "run here"}
    return bool(roots) and all(latest.get(r, {}).get("verdict") == "passed" for r in roots)
