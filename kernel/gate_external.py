"""The gate for a repository of your own ("gate my code", FR-MOD3): the same gate a builder cell meets,
without the factory's builder cells, and holdouts against your running service.

`gate` judges a change in an attached repository (kernel/attach.py): the commits from ``base`` to
``head``, checked out in a temporary clone. It is `kernel.gate`'s own judge, signal for signal:

- **tests:** the repository's whole unittest suite (`tests/`), run by the kernel on this machine, through
  IT's isolation runner while access is enforced and refused without one (`attach.outside_code`);
- **trace** and **fail-first**, when the change names the contract task it serves (`--task`): every
  visible criterion of the task is named by a test that ran, and those tests fail at ``base``;
- **verifier:** a read-only reviewer from another model family, through Gnomon, in the clone under the
  kernel's own `.gnomon/` surface. Without Gnomon it is not measured; `--no-verifier` leaves it out, and
  then it says not measured too, so a gate without its verifier is never passed;
- **protected:** a change to the contract file or a `.gnomon/` surface is a violation, as for a cell.

Rihmasto never merges: the verdict is recorded in the project's ledger (who asked, as which persona,
which revisions, every signal and objection) and you merge, or not. Each run is a new round of the task.

`holdouts` keeps the holdout custody for an attached repository. Scenarios are imported from a folder
outside the repository (a person who writes them hands them in; they are never in the repository the
builders work in), or written by the holdout author through Gnomon from the project's spec. They run
against the base URL of the service you started, and the ledger keeps each criterion's verdict, never a
scenario's steps.
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from typing import Any

from kernel.attach import AttachRefused, check_signer, checkout, commit_of, git, outside_code, repository, uncommitted
from kernel.gate import GateResult, Signal, _conclude, judge, judge_change, signal_protected, signal_tests
from kernel.store import Project, write_json

# The command's exit code by verdict: passed 0, a verdict against the change 1, not measured 4.
EXIT = {"passed": 0, "failed": 1, "regressed": 1, "violation": 1}
NOT_MEASURED_EXIT = 4
HELD_EXIT = 3                  # passed, but an enforce level holds it until its reviewer decides (FR-ENF2)
HOLDOUT_KINDS = ("holdout", "probe")


def _surface(work: Path) -> None:
    """The kernel's own `.gnomon/` surface in the clone, so the verifier runs under it and never under one
    the repository carries. A routing that cannot be read leaves the verifier not measured."""
    import contextlib
    import shutil

    from kernel.compile import WRITE_SCOPE
    from kernel.lanes import load_routing, write_product_surface

    shutil.rmtree(work / ".gnomon", ignore_errors=True)
    with contextlib.suppress(OSError, ValueError, KeyError):   # then the verifier finds no surface: not measured
        write_product_surface(work, load_routing(), WRITE_SCOPE)


def _judge(work: Path, contract: dict, *, task: str | None, base: str, head: str, label: str, author: str,
           verifier: bool, runner: Any) -> GateResult:
    if task is not None:
        result = judge(work, contract, task, base, head, verifier=verifier, verifier_runner=runner)
    elif verifier:
        result = judge_change(work, contract, base, head, label=label, author=author, verifier_runner=runner)
    else:
        guard = signal_protected(work, base, head)
        result = GateResult(task=label, base=base, head=head, signals=[
            signal_tests(work), Signal("trace", "not applicable", {"criteria": []}, "the change names no criterion"),
            Signal("fail_first", "not applicable", {}, "the change names no criterion"), *([guard] if guard else [])])
    if not verifier and not any(s.name in ("verifier", "protected") for s in result.signals):
        result.signals.append(Signal("verifier", "not measured", {}, "not asked (--no-verifier): a gate without "
                                                                     "its independent verifier is never passed"))
    result.objections = []
    return _conclude(result)


def _base_of(project: Project, head: str, base: str | None) -> str:
    if base is not None:
        return commit_of(project, base)
    branch = (project.meta.get("attached") or {}).get("branch") or "main"
    found = git(repository(project), "merge-base", head, branch, check=False)
    if not found or found == head:
        raise AttachRefused(f"nothing to judge: {head[:12]} is on {branch} itself; name the change's base with --base")
    return found


def gate(project: Project, *, person: str, persona: str, head: str | None = None, base: str | None = None,
         task: str | None = None, verifier: bool = True, verifier_runner: Any = None) -> dict[str, Any]:
    """Judge the change ``base``..``head`` of the attached repository with the gate, and record it."""
    from kernel.dispatch import gate_record

    check_signer(person, persona)
    contract = project.read("contract.json")
    if not contract:
        raise AttachRefused(f"{project.pid} has no contract to judge against: `rihmasto repo contract {project.pid} "
                            "--contract FILE` (or --spec FILE) gives it one")
    if task is not None and task not in {t["id"] for t in contract["tasks"]}:
        raise AttachRefused(f"{task} is not a task of the contract")
    head_sha = commit_of(project, head)
    base_sha = _base_of(project, head_sha, base)
    label = task or f"repo:{head_sha[:12]}"
    round_no = len([r for r in project.ledger().of_kind("gate") if r["event"]["payload"].get("task") == label])
    left_out = uncommitted(project) if head is None else False
    with outside_code(project), checkout(project, head_sha) as work:   # isolated, or refused, under access
        if verifier and verifier_runner is None:
            _surface(work)
        result = _judge(work, contract, task=task, base=base_sha, head=head_sha, label=label,
                        author=f"{person} ({persona})", verifier=verifier, runner=verifier_runner)
    record = gate_record(label, round_no, result, repository=str(repository(project)), base=base_sha,
                         person=person, persona=persona, asked_as="gate my code", uncommitted_left_out=left_out)
    project.log("gate", record)
    aligned = _aligned(project, base_sha, head_sha)
    from kernel.enforcement_guard import at_gate, gate_parts  # the levels of the stage it enters (FR-ENF2)

    enforced = gate_parts(at_gate(project, result.verdict, label, head_sha))
    return {**({"aligned": aligned} if aligned else {}), **enforced,
            "project": project.pid, "repository": str(repository(project)), "task": label, "round": round_no,
            "base": base_sha, "head": head_sha, "verdict": result.verdict, "warranted": result.warranted,
            "signals": [{"name": s.name, "verdict": s.verdict, "detail": s.detail} for s in result.signals],
            "objections": result.objections, "uncommitted_left_out": left_out,
            "merge": "yours: Rihmasto never merges into, writes to or pushes to an attached repository"}


def _aligned(project: Project, base: str, head: str) -> dict[str, Any] | None:
    """What the change touches of the criteria accepted from the repository (kernel/alignment_records.py)."""
    from kernel.alignment_records import gate_note

    changed = git(repository(project), "diff", "--name-only", base, head, check=False).splitlines()
    return gate_note(project, changed)


def exit_code(verdict: str, held: Any = None) -> int:
    """The verdict's exit code; a change an enforce level holds until its reviewer decides never exits 0."""
    code = EXIT.get(verdict, NOT_MEASURED_EXIT)
    return HELD_EXIT if held and code == 0 else code


# -- holdouts for an attached repository ---------------------------------------------------------------

def _holdout_criteria(project: Project) -> dict[str, str]:
    plan = project.read("checkplan.json") or {}
    return {r["criterion"]: r["kind"] for r in plan.get("checks", []) if r.get("kind") in HOLDOUT_KINDS}


def _scenario(project: Project, path: Path, wanted: dict[str, str]) -> dict[str, Any]:
    """One scenario file as the custody keeps it, or AttachRefused saying what is wrong with it."""
    from kernel.holdouts import clean_step

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError, RecursionError):
        raise AttachRefused(f"{path.name} is not a JSON scenario") from None
    cid = str(doc.get("criterion")) if isinstance(doc, dict) else ""
    steps = [clean_step(s) for s in (doc.get("steps") or []) if isinstance(s, dict) and s.get("method")
             and s.get("path")] if cid in wanted else []
    if not steps:
        raise AttachRefused(f"{path.name}: a scenario names a holdout or probe criterion of the contract "
                            f"({', '.join(sorted(wanted)) or 'it has none'}) and has steps")
    if (project.holdouts_dir / f"{cid}.json").exists():
        raise AttachRefused(f"{cid} already has a scenario in custody: a person's ruling replaces it")
    return {"criterion": cid, "kind": wanted[cid], "steps": steps, "author_role": "person"}


def import_holdouts(project: Project, folder: str | Path, *, person: str, persona: str) -> list[str]:
    """Take a person's scenarios into the holdout custody: one JSON file per criterion, ``{"criterion",
    "steps": [...]}``. A folder inside the attached repository is refused (the builders would see it), and
    so is a criterion that is not a holdout or probe of the contract, or one already in custody."""
    check_signer(person, persona)
    source = Path(folder).resolve()
    if source == repository(project) or repository(project) in source.parents:
        raise AttachRefused("holdout scenarios inside the repository reach its builders: keep them in a folder "
                            "outside it")
    wanted = _holdout_criteria(project)
    docs = [_scenario(project, path, wanted) | {"imported_by": person} for path in sorted(source.glob("*.json"))]
    if not docs:
        raise AttachRefused(f"no scenario (*.json) in {source}")
    for doc in docs:
        write_json(project.holdouts_dir / f"{doc['criterion']}.json", doc)
    saved = [d["criterion"] for d in docs]
    project.log("holdouts_imported", {"criteria": saved, "person": person, "persona": persona,
                                      "missing": sorted(set(wanted) - set(saved) - _in_custody(project))})
    return saved


def _in_custody(project: Project) -> set[str]:
    folder = project.holdouts_dir
    return {p.stem for p in folder.glob("*.json") if not p.name.endswith(".retired.json")} if folder.exists() else set()


def _base_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise AttachRefused("the base URL is http:// or https:// with a host")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise AttachRefused("the base URL carries no user, password, query or fragment")
    return url.rstrip("/")


def run_holdouts(project: Project, base_url: str, *, person: str, persona: str) -> dict[str, Any]:
    """Run the custody's scenarios against the service at ``base_url``; record each criterion's verdict."""
    from kernel.operate import run_holdouts as run

    check_signer(person, persona)
    if not project.read("checkplan.json"):
        raise AttachRefused(f"{project.pid} has no contract, so no holdout criteria")
    out = run(project, _base_url(base_url))
    rows = [{"criterion": r.get("criterion"), "verdict": r.get("verdict"), **({"reason": r["reason"]}
            if r.get("reason") else {})} for r in out["results"]]
    project.log("holdouts_run", {"base_url": out["base_url"], "verdict": out["verdict"], "scenarios": out["scenarios"],
                                 "passed": out["passed"], "failed": out["failed"], "missing": out["missing"],
                                 "results": rows, "person": person, "persona": persona, "asked_as": "gate my code"})
    return {"project": project.pid, "base_url": out["base_url"], "verdict": out["verdict"], "results": rows,
            "missing": out["missing"], "scenarios": out["scenarios"], "passed": out["passed"], "failed": out["failed"]}


def holdouts(project: Project, *, person: str, persona: str, import_dir: str | None = None, author: bool = False,
             base_url: str | None = None, model: Any = None) -> dict[str, Any]:
    """`rihmasto repo holdouts`: import scenarios, let the holdout author write the missing ones, run them."""
    out: dict[str, Any] = {"project": project.pid}
    if not (import_dir or author or base_url):
        raise AttachRefused("name what to do: --import DIR, --author, or --base-url URL to run them")
    if import_dir:
        out["imported"] = import_holdouts(project, import_dir, person=person, persona=persona)
    if author:
        from kernel.compile import author_holdouts

        check_signer(person, persona)
        if not project.read("spec.json"):
            raise AttachRefused("the holdout author writes from a spec: attach with --spec, or import scenarios")
        out["authored"] = author_holdouts(project, model=model() if callable(model) else model, only="missing")
    if base_url:
        out["run"] = run_holdouts(project, base_url, person=person, persona=persona)
    out["in_custody"] = sorted(_in_custody(project))
    return out
