"""Running a Gnomon audit, benchmark or eval on a project, and keeping what it found (FR-EVL1).

- **Who:** a named person as a persona that sets checks (developer, IT, operations, compliance, a product owner);
  one that runs the project's own code (``check``, ``eval``, ``claim_check``) by a persona the console allows.
- **Where:** in the project's workspace (kernel/console.py), through IT's isolation runner when access is enforced.
  An eval of the harness itself (``chaos``, ``context_cost``, ``degradation``) runs in a scratch folder.
- **Models:** an eval that calls the lane's model roles (``eval``) on a confidential project is refused unless every
  role it asks has a local or private endpoint (kernel/confidential.py): nothing is sent, and the refusal is recorded.
- **What is kept:** ``evals/results.json`` in the project (the last 50 results of each eval, with its scores and
  findings, each finding marked new when the run before did not have it), and the ledger's ``eval_ran`` (the
  verdict, a one-line summary, the scores and how many findings and new findings): never a prompt, never source.
- **From the cockpit** a run is a job with its log streamed on the Jobs page: the request is signed and recorded
  (``eval_requested``) and ``rihmasto evals carry <pid> <request>`` carries it out.
- **A finding can become a change proposal** (``make_change``): a change card with the finding and its evidence,
  recorded as ``eval_finding_changed``.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel import gnomon_evals as ge
from kernel.canon import DecisionRefused
from kernel.gnomon_evals_read import answer, read
from kernel.store import Factory, Project, updating_json

MAX_RESULTS = 50
ENABLERS = ("developer", "it", "operations", "compliance", "product_owner")
_RUNNING: set[tuple[str, str]] = set()
_LOCK = threading.Lock()
Emit = Callable[[str], None]


class EvalsRefused(DecisionRefused):
    """A run or a change the rules refuse (403, exit 2)."""


def _quiet(_: str) -> None:
    pass


def may(project: Project, ev: ge.Eval, person: str, persona: str) -> None:
    from kernel.people import PERSONAS, is_person

    if not is_person(person):
        raise EvalsRefused(f"{person!r} is not a person: an audit is run by a named person")
    if persona not in PERSONAS:
        raise EvalsRefused(f"persona must be one of {', '.join(PERSONAS)}, got {persona!r}")
    if ev.runs_code:
        from kernel.console import check_persona

        check_persona(project, person, persona)
    elif persona not in ENABLERS:
        raise EvalsRefused(f"Gnomon audits are run by {', '.join(ENABLERS)}, not a {persona}")


def _setting(key: str, value: Any) -> Any:
    """A setting as kept: true or false, a whole number, or a short word; None for anything else."""
    if isinstance(value, bool) or (isinstance(value, int) and 0 <= value < 10**9):
        return value
    if not isinstance(value, str) or len(value) > 300 or not value.strip():
        return None
    return int(value) if key == "max_bytes" and value.strip().isdigit() else value.strip()


def clean(ev: ge.Eval, config: Any) -> dict[str, Any]:
    config = dict(config or {})
    unknown = [k for k in config if k not in ev.options]
    if unknown:
        raise ValueError(f"the {ev.label} takes {', '.join(ev.options) or 'no settings'}, not {', '.join(unknown)}")
    out = {k: _setting(k, v) for k, v in config.items()}
    out = {k: v for k, v in out.items() if v is not None}
    missing = [k for k in ev.needs if not out.get(k)]
    if missing:
        raise ValueError(f"the {ev.label} needs {', '.join(missing)}")
    return out


# -- running -----------------------------------------------------------------------------------------------------

def _argv(ev: ge.Eval, ws: Path, cfg: dict[str, Any], out_file: Path) -> list[str]:
    import shutil

    words = ev.command(str(ws), cfg)
    if ev.kind == "cli":
        return [*ge.gnomon(), *words]
    subs = {"{python}": sys.executable, "{node}": shutil.which("node") or "node", "{out}": str(out_file)}
    source = str(ge.source_dir())
    return [subs.get(w, w.replace("{source}", source)) for w in words]


def _stream(argv: list[str], cwd: Path, env: dict[str, str], timeout: int, emit: Emit) -> tuple[int | None, str, str]:
    """Run ``argv``, each line of its output to ``emit`` as it comes; (exit code or None on timeout, out, err)."""
    proc = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    parts: dict[str, list[str]] = {"out": [], "err": []}

    def pump(stream: Any, key: str) -> None:
        for line in stream:
            parts[key].append(line)
            if sum(len(x) for x in parts[key]) < 4 * 1024 * 1024:
                emit(("  " if key == "out" else "! ") + line.rstrip()[:300])

    threads = [threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True),
               threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True)]
    for t in threads:
        t.start()
    try:
        code: int | None = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        code = None
    for t in threads:
        t.join(10)
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            stream.close()
    return code, "".join(parts["out"]), "".join(parts["err"])


def _where(project: Project, ev: ge.Eval, person: str) -> tuple[Path, str | None]:
    """The folder it runs in, and why it cannot run there (None: it can)."""
    if ev.scope == "harness":
        return Path(tempfile.mkdtemp(prefix=f"rihmasto-{ev.id}-")), None
    from kernel.console import ensure_workspace

    ws, _ = ensure_workspace(project, person or None)
    if not (ws / ".gnomon").is_dir():
        return ws, "the repository has no .gnomon/ surface (run `gnomon init` in it, or let Rihmasto build it)"
    return ws, None


def _ready(project: Project, ev: ge.Eval, cfg: dict[str, Any], person: str,
           emit: Emit) -> tuple[Path | None, dict[str, Any] | None]:
    """The folder ``ev`` runs in, or why it cannot run (a not measured result)."""
    from kernel.confidential import ConfidentialRefused, require_local

    if ev.models == "roles":
        try:
            require_local(project, ev.roles, where=f"the Gnomon {ev.label}")
        except ConfidentialRefused as exc:
            emit(f"refused: {exc}")
            return None, answer("not measured", str(exc), why="confidential") | {"refused": "confidential"}
    ok, missing = ge.availability(ev)
    if not ok:
        return None, answer("not measured", missing, why="not available")
    try:
        ws, why = _where(project, ev, person)
    except (OSError, ValueError, DecisionRefused) as exc:
        return None, answer("not measured", f"no workspace to run in: {exc}", why="no workspace")
    if why:
        return None, answer("not measured", why, why="no surface")
    report = (ws / str(cfg.get("report"))).resolve()
    if ev.id == "claim_check" and (ws.resolve() not in report.parents or not report.is_file()):
        return None, answer("not measured", f"no report {cfg.get('report')} in the repository", why="no report")
    return ws, None


def _written(path: Path) -> Any:
    """The JSON report a benchmark wrote to its --json file, or None."""
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return None


def measure(project: Project, ev: ge.Eval, cfg: dict[str, Any], *, person: str, emit: Emit) -> dict[str, Any]:
    """Run ``ev`` once and read its result; never raises for the apparatus: what failed is not measured, with why."""
    ws, refused = _ready(project, ev, cfg, person, emit)
    if ws is None:
        return refused or answer("not measured", "it could not run here", why="not run")
    out_file = Path(tempfile.mkdtemp(prefix="rihmasto-eval-out-")) / "report.json"
    argv = _argv(ev, ws, cfg, out_file)
    from kernel import console_run as crun
    from kernel.access_isolation import IsolationRequired
    from kernel.console import _env

    plan = crun.Plan(argv=argv, cwd=ws, env=_env(project, gnomon=ev.models != "none"), display=" ".join(argv[-4:]))
    try:
        plan = crun.isolate(plan)
    except IsolationRequired as exc:
        return answer("not measured", str(exc), why="isolation required")
    emit(f"$ gnomon {' '.join(ev.command('<workspace>', cfg))}" if ev.kind == "cli"
         else f"$ {Path(ev.marker).name} (Gnomon source checkout)")
    try:
        code, out, err = _stream(plan.argv, plan.cwd, plan.env, ev.timeout, emit)
    except OSError as exc:
        return answer("not measured", f"it could not start: {exc}", why="did not start")
    if code is None:
        return answer("not measured", f"it did not finish in {ev.timeout} s", why="timed out")
    doc = _written(out_file) if ev.out_file else None
    return read(ev.id, out, err, code, doc=doc, cfg=cfg) | {"exit": code}


def run(project: Project, eid: str, *, person: str, persona: str, config: Any = None, via: str = "person",
        emit: Emit = _quiet, request: str | None = None, identity: str | None = None) -> dict[str, Any]:
    """Run an eval now on the project and record it; returns the result as kept."""
    import time

    ev = ge.find(eid)
    may(project, ev, person, persona)
    cfg = clean(ev, config)
    with _LOCK:
        if (project.pid, ev.id) in _RUNNING:
            raise EvalsRefused(f"the {ev.label} is running on {project.pid} now")
        _RUNNING.add((project.pid, ev.id))
    started = time.monotonic()
    try:
        emit(f"Gnomon {ev.label} on {project.pid}, asked by {person} as {persona}")
        out = measure(project, ev, cfg, person=person, emit=emit)
    finally:
        with _LOCK:
            _RUNNING.discard((project.pid, ev.id))
    row = record(project, ev, out, person=person, persona=persona, via=via, seconds=time.monotonic() - started,
                 config=cfg, request=request, identity=identity)
    emit(f"{row['verdict']}: {row['summary']} ({len(row['findings'])} finding(s), {row['new_findings']} new)")
    return row


def running(project: Project, eid: str) -> bool:
    with _LOCK:
        return (project.pid, eid) in _RUNNING


# -- the records -------------------------------------------------------------------------------------------------

def results(project: Project, eid: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    kept = project.read("evals/results.json", {}) or {}
    rows = kept.get(eid, []) if eid else [r for v in kept.values() for r in v]
    return sorted(rows, key=lambda r: str(r.get("at")))[-limit:]


def record(project: Project, ev: ge.Eval, out: dict[str, Any], *, person: str, persona: str, via: str,
           seconds: float = 0.0, config: dict[str, Any] | None = None, request: str | None = None,
           identity: str | None = None) -> dict[str, Any]:
    findings, new, gone = _compared(project, ev, out.get("findings") or [])
    issues = sum(1 for f in findings if f["severity"] == "issue")
    row = {**out, "eval": ev.id, "label": ev.label, "findings": findings, "new_findings": new, "issues": issues,
           "resolved": gone, "at": project.factory.clock.stamp(), "seconds": round(seconds, 2),
           "config": config or {}, "by": {"person": person, "persona": persona}, "via": via,
           "gnomon": ge.detect()["version"] if ev.kind == "cli" else "source", "request": request}
    with updating_json(project.path("evals", "results.json"), {}) as kept:
        kept[ev.id] = (kept.get(ev.id) or [])[-(MAX_RESULTS - 1):] + [row]
    extra = {"request": request, "identity": identity, "refused": out.get("refused")}
    project.log("eval_ran", {"eval": ev.id, "label": ev.label, "verdict": row["verdict"],
                             "summary": row["summary"][:300], "scores": row["scores"], "findings": len(findings),
                             "issues": issues, "new_findings": new, "resolved": gone, "dimension": ev.dimension,
                             "person": person, "persona": persona, "via": via,
                             **{k: v for k, v in extra.items() if v}})
    from kernel.heal_evals import audit_failed  # a failed audit opens an incident with its findings (FR-HEAL1)

    opened = audit_failed(project, ev, row)
    return row | ({"incident": opened["id"]} if opened else {})


def _compared(project: Project, ev: ge.Eval, found: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    """The findings marked new against the run before, how many issues are new, and how many went away."""
    before = (results(project, ev.id, 1) or [{}])[-1]
    seen = {f["id"] for f in before.get("findings") or []}
    marked = [dict(f, new=f["id"] not in seen) for f in found]
    new = sum(1 for f in marked if f["new"] and f["severity"] == "issue")
    return marked, new, len(seen - {f["id"] for f in marked})


def latest(project: Project) -> dict[str, dict[str, Any]]:
    kept = project.read("evals/results.json", {}) or {}
    return {k: v[-1] for k, v in kept.items() if v}


def changes(project: Project) -> dict[str, str]:
    """Each finding already made a change proposal: finding id -> card id."""
    return dict(project.read("evals/changes.json", {}) or {})


def findings(project: Project) -> list[dict[str, Any]]:
    """The findings of each eval's latest run, issues first, each saying whether it became a change."""
    made = changes(project)
    out = [dict(f, eval=eid, label=row.get("label"), at=row.get("at"), card=made.get(f["id"]))
           for eid, row in latest(project).items() for f in row.get("findings") or []]
    return sorted(out, key=lambda f: (f["severity"] != "issue", not f.get("new"), f["eval"]))


def make_change(project: Project, fid: str, *, person: str, persona: str) -> dict[str, Any]:
    """A change proposal from a finding: its title and evidence, in the Inbox for the person who decides changes."""
    from kernel.change import submit
    from kernel.people import is_person

    if not is_person(person):
        raise EvalsRefused(f"{person!r} is not a person: a change is filed by a named person")
    found = next((f for f in findings(project) if f["id"] == fid), None)
    if found is None:
        raise KeyError(f"no finding {fid} in {project.pid}'s latest audits")
    if found.get("card"):
        raise ValueError(f"{fid} is already change {found['card']}")
    text = (f"Gnomon {found['label']} found: {found['title']}\n\nEvidence ({found['at']}):\n"
            + "\n".join(f"- {e}" for e in found["evidence"] or ["(no more evidence)"])
            + f"\n\nFinding {fid}, from `rihmasto evals history {project.pid} --eval {found['eval']}`.")
    card = submit(project, persona=persona, person=person, text=text)
    with updating_json(project.path("evals", "changes.json"), {}) as kept:
        kept[fid] = card["id"]
    project.log("eval_finding_changed", {"finding": fid, "eval": found["eval"], "card": card["id"], "person": person,
                                         "persona": persona})
    return {"finding": fid, "card": card["id"], "title": card.get("title")}


# -- requests the cockpit files, carried out as a job ---------------------------------------------------------------

def request(project: Project, eid: str, *, person: str, persona: str, config: Any = None) -> dict[str, Any]:
    """A signed request to run ``eid``, recorded; ``carry`` runs it (the cockpit's job)."""
    from kernel.people import SIGNER

    ev = ge.find(eid)
    may(project, ev, person, persona)
    cfg = clean(ev, config)
    signer = SIGNER.get()
    ident = signer.id if signer is not None and signer.name == person else None
    with updating_json(project.path("evals", "requests.json"), {}) as kept:
        rid = f"ER-{len(kept) + 1:04d}"
        kept[rid] = {"eval": ev.id, "config": cfg, "person": person, "persona": persona, "identity": ident,
                     "at": project.factory.clock.stamp(), "state": "requested"}
    project.log("eval_requested", {"request": rid, "eval": ev.id, "person": person, "persona": persona})
    return {"request": rid, "eval": ev.id, "label": ev.label}


def carry(factory: Factory, pid: str, rid: str, emit: Emit = _quiet) -> dict[str, Any]:
    """Carry out a recorded request once, as the person who signed it."""
    project = factory.project(pid)
    with updating_json(project.path("evals", "requests.json"), {}) as kept:
        req = kept.get(rid)
        if req is None:
            raise KeyError(f"no eval request {rid} in {pid}")
        if req.get("state") != "requested":
            raise ValueError(f"{rid} was already carried out ({req.get('state')})")
        req["state"] = "running"
    try:
        row = run(project, req["eval"], person=req["person"], persona=req["persona"], config=req.get("config"),
                  via="cockpit", emit=emit, request=rid, identity=req.get("identity"))
    finally:
        with updating_json(project.path("evals", "requests.json"), {}) as kept:
            kept[rid]["state"] = "done"
            kept[rid]["ended"] = dt.datetime.now(dt.UTC).isoformat()
    return row
