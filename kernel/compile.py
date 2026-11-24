"""Stage 4 to 5: the spec becomes a contract, a check plan and a product repository.

There is no model in this module (FR-O2). The same spec always compiles to the same contract
revision. The contract is judged by the same `tools/contract_check.py` that judges the factory's
own contract.

Checks come in two custodies (FR-O3):
- visible tests, which the builder sees in its envelope;
- holdout scenarios, which a different role writes. They are kept outside the project folder
  and are never shown to a builder. A scenario whose criterion a change withdrew or restated is
  retired: kept in the custody, it never runs again (`retire_holdouts`).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from kernel import scaffold
from kernel.confidential import routing_for
from kernel.intake import _ask_json
from kernel.lanes import GIT_ID, _git, load_routing, write_product_surface
from kernel.outputs import wants_sign_in
from kernel.profiles import profile_of
from kernel.spec import render_interface
from kernel.store import REPO_ROOT, Project, read_json, write_json, write_text

WRITE_SCOPE = ["app/**", "tests/**"]
OBSERVED = "observed"  # the spec tier of an adopted solution's as-is requirements
_CC = None
_TASK_NO = re.compile(r"T-(\d+)")
RETIRED = ".retired.json"  # where a criterion's scenarios go once no criterion stands behind them
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


class CompileError(ValueError):
    def __init__(self, failures):
        self.failures = failures
        super().__init__("; ".join(f"{f['rule']} {f['path']}" for f in failures[:5]))


def contract_check():
    """`tools/contract_check.py`, loaded as a module (tools/ is not a package)."""
    global _CC
    if _CC is None:
        import sys

        name = "gnomonfactory_contract_check"
        spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "tools" / "contract_check.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # dataclasses look their module up here
        spec.loader.exec_module(module)
        _CC = module
    return _CC


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _default_requirements(project: Project) -> list[dict[str, Any]]:
    """Checks the factory learned from earlier products and a person accepted (FR-K3): every new
    contract carries them as factory-default requirements."""
    from kernel.learn import default_checks

    reqs: list[dict[str, Any]] = []
    for n, d in enumerate(default_checks(project.factory), 1):
        rid = f"FD-{n}"
        reqs.append({"id": rid, "statement": f"Factory default check (learned from {', '.join(d['from_projects'])}): "
                                             f"{d['then']}",
                     "provenance": "vendor-proposed", "group": "factory-default",
                     "acceptance": [{"id": f"{rid}-AC-1", "given": d.get("given") or "-", "when": d.get("when") or "-",
                                     "then": d["then"], "check": {"kind": "test"}}]})
    return reqs


def _task_numbers(project: Project, rids: list[str], withdrawn: set[str]) -> dict[str, int]:
    """Each live requirement's task number. A first compile numbers the requirements in order (a
    withdrawn one keeps its place and gets no task). A recompile keeps the number each
    requirement's task had in the project's current contract and gives a new requirement the next
    free number, so adding one never renumbers another task, a factory default check's included,
    and withdrawing one leaves every other task its id (FR-A4)."""
    had: dict[str, int] = {}
    for t in (project.read("contract.json") or {}).get("tasks") or []:
        found = _TASK_NO.fullmatch(str(t.get("id", "")))
        if found and t.get("criteria"):
            had[str(t["criteria"][0]).rsplit("-AC-", 1)[0]] = int(found.group(1))
    if not had:
        return {rid: n for n, rid in enumerate(rids, 1) if rid not in withdrawn}
    top = max(had.values())
    numbers: dict[str, int] = {}
    for rid in rids:
        if rid in withdrawn:
            continue
        if rid not in had:
            top += 1
            had[rid] = top
        numbers[rid] = had[rid]
    return numbers


def _tasks(task_reqs: list[dict[str, Any]], numbers: dict[str, int]) -> list[dict[str, Any]]:
    """One task per live requirement, in the order of their numbers, each after the one before it:
    one writer on the shared scope at a time (FR-F3). A withdrawn requirement has no task."""
    by_id = {r["id"]: r for r in task_reqs}
    tasks: list[dict[str, Any]] = []
    for rid, n in sorted(numbers.items(), key=lambda item: item[1]):
        r = by_id[rid]
        task: dict[str, Any] = {"id": f"T-{n:03d}", "title": r["statement"][:100],
                                "criteria": [c["id"] for c in r["acceptance"]], "scope": {"write": list(WRITE_SCOPE)}}
        if tasks:
            task["depends_on"] = [tasks[-1]["id"]]
        tasks.append(task)
    return tasks


def _contract_requirement(r: dict[str, Any], today: str) -> dict[str, Any]:
    """One spec requirement as the contract states it, each criterion with its check."""
    acceptance = []
    for c in r["acceptance"]:
        check = {"kind": c["kind"]}
        if c["kind"] == "holdout":
            check["ref"] = f"H-{c['id']}"
        elif c["kind"] == "probe":
            check["command"] = f"probe {c['id']}"
        acceptance.append({"id": c["id"], "given": c.get("given") or "-", "when": c.get("when") or "-",
                           "then": c["then"], "check": check})
    req = {"id": r["id"], "statement": r["statement"], "provenance": r["provenance"],
           "group": r.get("priority", "must"), "acceptance": acceptance}
    if r["provenance"] == OBSERVED:
        # An adopted solution's as-is requirement (kernel/adopt.py). The contract's vocabulary has
        # no observed tier: no person stood behind it, so it enters as vendor-proposed and says so.
        req["provenance"] = "vendor-proposed"
        req["notes"] = "observed: existing behaviour at adoption, not a spec"
    if r.get("decided_by"):
        req["decided_by"], req["decided_on"] = r["decided_by"], today
    return req


def to_contract(project, spec: dict) -> dict:
    """The contract a spec compiles to, with no model. A withdrawn requirement stays in it, marked
    withdrawn, with no task; every other task keeps the id it had (FR-A4)."""
    cc = contract_check()
    today = project.factory.clock.today().isoformat()
    reqs = [_contract_requirement(r, today) for r in spec["requirements"]]
    reqs += _default_requirements(project)
    task_reqs = list(spec["requirements"]) + [r for r in reqs if r["id"].startswith("FD-")]
    withdrawn = {r["id"] for r in task_reqs if r.get("provenance") == "withdrawn"}
    tasks = _tasks(task_reqs, _task_numbers(project, [r["id"] for r in task_reqs], withdrawn))
    spec_text = json.dumps(spec, sort_keys=True, ensure_ascii=False)
    brief = project.path("canon", "brief.md")
    contract = {
        "schema": cc.SCHEMA, "contract": project.pid,
        "source": {"spec": "spec.json", "spec_sha256": _sha(spec_text), "brief": "canon/brief.md",
                   "brief_sha256": _sha(brief.read_text(encoding="utf-8")) if brief.exists() else "",
                   "generated_by": "kernel/compile.py (no model)"},
        "requirements": reqs, "tasks": tasks,
        "counts": {"requirements": len(reqs), "criteria": sum(len(r["acceptance"]) for r in reqs),
                   "tasks": len(tasks)},
    }
    contract["revision"] = cc.canonical_revision(contract)
    report, _ = cc.check(contract)
    if report.violations:
        raise CompileError(report.violations)
    return contract


def check_plan(contract: dict) -> dict:
    rows = []
    for r in contract["requirements"]:
        if r.get("provenance") == "withdrawn":  # no work on a withdrawn requirement: no check, no holdout
            continue
        for c in r["acceptance"]:
            kind = c["check"]["kind"]
            rows.append({"criterion": c["id"], "requirement": r["id"], "kind": kind,
                         "custody": "holdout" if kind == "holdout" else "visible",
                         "test_token": c["id"].replace("-", "_"), "then": c["then"]})
    return {"contract_revision": contract["revision"], "checks": rows}


def init_repo(project, contract: dict, routing: dict | None = None) -> Path:
    """Create the product's bare repository with the paved-road template, the contract and
    the cell surface, as one commit on main."""
    bare = project.path("repo.git")
    if bare.exists():
        return bare
    routing = routing or load_routing()
    meta = project.meta
    with tempfile.TemporaryDirectory(prefix="gf-scaffold-") as tmp:
        work = Path(tmp) / "w"
        work.mkdir()
        _git(work, "init", "-q", "-b", "main")
        look = (project.read("spec.json") or {}).get("look", "neutral")
        sign_in = wants_sign_in(project)  # a person chose a web app people sign in to (kernel/outputs.py)
        template = profile_of(project).get("template", "web-service")   # a small capability's, or the web service's
        made = scaffold.files(meta["title"], project.pid, meta["maturity"], look=look, template=template,
                              sign_in=sign_in)
        for rel, text in made.items():
            write_text(work / rel, text)
        write_json(work / "contract.json", contract)
        write_product_surface(work, routing_for(project, routing), WRITE_SCOPE)   # confidential: no hosted fallback
        _git(work, "add", "-A")
        _git(work, *GIT_ID, "commit", "-q", "-m", f"Scaffold from the paved road; contract {contract['revision'][:19]}")
        bare.parent.mkdir(parents=True, exist_ok=True)
        _git(bare.parent, "init", "-q", "--bare", "-b", "main", bare.name)
        _git(work, "push", "-q", str(bare), "main")
    project.log("repo_created", {"repo": "repo.git", "contract": contract["revision"]})
    return bare


def update_repo_contract(project, contract: dict) -> str:
    """Commit a new contract revision to the product's main (after an amendment)."""
    with tempfile.TemporaryDirectory(prefix="gf-amend-") as tmp:
        work = Path(tmp) / "w"
        _git(Path(tmp), "clone", "-q", str(project.path("repo.git")), "w")
        write_json(work / "contract.json", contract)
        _git(work, "add", "contract.json")
        _git(work, *GIT_ID, "commit", "-q", "-m", f"Contract amended to {contract['revision'][:19]}")
        _git(work, "push", "-q", "origin", "main")
        return _git(work, "rev-parse", "HEAD")


def update_repo_surface(project, routing: dict | None = None, *, reason: str = "routing changed") -> str | None:
    """Recompile the product's `.gnomon/` surface from the current routing and commit it to main,
    so the next cell runs under it (for example after fallbacks were added). Returns the new
    revision, or None when nothing changed."""
    routing = routing or load_routing()
    with tempfile.TemporaryDirectory(prefix="gf-surface-") as tmp:
        _git(Path(tmp), "clone", "-q", str(project.path("repo.git")), "w")
        work = Path(tmp) / "w"
        write_product_surface(work, routing_for(project, routing), WRITE_SCOPE)
        _git(work, "add", "-A", ".gnomon")
        if not _git(work, "diff", "--cached", "--name-only"):  # what is staged decides, not line-ending noise
            return None
        _git(work, *GIT_ID, "commit", "-q", "-m", f"Surface recompiled by the kernel: {reason}")
        _git(work, "push", "-q", "origin", "main")
        revision = _git(work, "rev-parse", "HEAD")
    project.log("surface_updated", {"revision": revision, "reason": reason})
    return revision


def compile_project(project) -> dict:
    spec = project.read("spec.json")
    if not spec:
        raise FileNotFoundError("no spec.json: run the spec stage first")
    contract = to_contract(project, spec)
    project.write("contract.json", contract)
    project.write("checkplan.json", check_plan(contract))
    init_repo(project, contract)
    project.update_meta(stage=5, contract_revision=contract["revision"])
    project.log("contract_compiled", {"revision": contract["revision"], **contract["counts"]})
    return contract


# -- holdouts: a separate custody (FR-O3, FR-B4) ------------------------------------------------

def _ruling_section(ruling: dict | None) -> str:
    """What a person said when they ruled earlier scenarios defective, and what those scenarios
    met on the running service. The holdout author sees the service's answers, never the code."""
    if not ruling:
        return ""
    lines = [f"- {f.get('criterion')}: the scenario sent {json.dumps(f.get('request'))[:300]}, expected "
             f"{json.dumps(f.get('expected'))[:300]}, and the service answered {json.dumps(f.get('observed'))[:400]}"
             for f in ruling.get("evidence", [])]
    return ("\nA person ruled the earlier scenarios for these criteria defective, so you are rewriting them.\n"
            f"Their reason: {ruling['reason']}\nWhat the earlier scenarios met on the running service:\n"
            + ("\n".join(lines) or "- (not recorded)") + "\nDo not repeat what made them wrong.\n")


def holdout_prompt(spec: dict, rows: list, ruling: dict | None = None, secret_names: list | None = None) -> str:
    """The holdout author's prompt. Its interface section says how a step signs a request, with the
    names (never the values) of the secrets the environment's settings give (FR-DF2-AC-2)."""
    from kernel.holdouts import signing_rules

    listing = "\n".join(f"- {r['criterion']} ({r['kind']}): {r['then']}" for r in rows)
    return f"""You write acceptance scenarios that a factory runs against a deployed HTTP service. The
builder never sees them.

The product: {spec['title']}: {spec.get('summary', '')}
Its requirements:
{chr(10).join(f"- {r['id']}: {r['statement']}" for r in spec['requirements'])}

The product's HTTP interface, fixed by the spec. Use exactly these methods and paths:
{render_interface(spec)}

{signing_rules(list(secret_names or []))}

Write one scenario for each of these criteria:
{listing}
{_ruling_section(ruling)}
All scenarios run one after another against ONE deployment, which may already hold data from
other scenarios or earlier use. So never assume an empty store. Create your own data with values
unique to the scenario (for example a name containing the criterion id), and check for the
presence or absence of *that* data, not for an empty list. When a criterion speaks of seeded
or existing data, never guess its ids: list it first with a GET step and reuse an id from that
answer.

Each step has a method, a path, an optional JSON body, and the expectations:
- expect_status: an integer;
- expect_json: an optional object whose keys must appear with these values in the JSON
  response;
- expect_contains: an optional text the response must contain;
- expect_not_contains: an optional text the response must not contain (for example your own
  item's unique name after it was removed);
- max_ms: an optional latency limit, for probes.

Reusing a value: "{{{{prev.<key>}}}}" in a step's path or body becomes that key's value in the
previous step's JSON response. That is how a value in braces in the interface, such as {{id}},
is filled: "{{{{prev.id}}}}" after a step that answered with an object, "{{{{prev.0.id}}}}" after
one that answered with a list.

Answer with this JSON in a ```json block:
{{"scenarios": [{{"criterion": "R-1-AC-2", "steps": [{{"method": "POST", "path": "/items", "body": {{}},
  "expect_status": 201, "expect_json": {{}}}}]}}]}}
"""


def author_holdouts(project, *, model, only=None, reason: str | None = None, person: str | None = None,
                    evidence: list | None = None) -> list:
    """The holdout author writes executable scenarios for holdout and probe criteria. They are
    stored in the holdout custody, outside the project folder and the product repository.

    ``only`` re-authors named criteria. That is allowed only when a person ruled a failing
    scenario defective. The person is recorded; the reason, which may describe the scenario, is
    kept in the holdout custody and the ledger holds a pointer to it. The builder never writes
    or sees them."""
    from kernel.confidential import guard
    from kernel.people import is_person

    model = guard(project, model, ("holdout_author",), where="holdouts")
    spec, plan = project.read("spec.json"), project.read("checkplan.json")
    rows = [r for r in plan["checks"] if r["kind"] in ("holdout", "probe")]
    if only == "missing":  # criteria with no scenario yet: nothing exists to overturn, no ruling needed
        rows = [r for r in rows if not (project.holdouts_dir / f"{r['criterion']}.json").exists()]
        only = None
    if only is not None:
        if not (reason and is_person(person or "")):
            raise PermissionError("re-authoring a holdout needs a person's ruling and a reason")
        rows = [r for r in rows if r["criterion"] in set(only)]
    if not rows:
        return []
    names = {r["criterion"] for r in rows}
    ruling = {"reason": reason, "evidence": [f for f in (evidence or []) if f.get("criterion") in names]} \
        if only is not None else None
    from kernel.holdouts import clean_step, secret_names

    answer = _ask_json(model, holdout_prompt(spec, rows, ruling, secret_names(project)), role="holdout_author")
    wanted = {r["criterion"]: r for r in rows}
    saved = []
    for sc in answer.get("scenarios") or []:
        cid = sc.get("criterion") if isinstance(sc, dict) else None
        steps = [clean_step(s) for s in (sc.get("steps") or []) if isinstance(s, dict) and s.get("method")
                 and s.get("path")] if cid in wanted else []
        if not steps:
            continue
        doc = {"criterion": cid, "kind": wanted[cid]["kind"], "steps": steps, "author_role": "holdout_author"}
        write_json(project.holdouts_dir / f"{cid}.json", doc)
        saved.append(cid)
    record: dict = {"criteria": saved, "missing": sorted(set(wanted) - set(saved))}
    if only is not None:
        # The reason may describe the scenario: the ledger keeps a pointer to it in the custody (FR-O3-AC-3).
        from kernel.rulings import hold_reason

        record |= {"reauthored_because": hold_reason(project, str(reason), ref="holdouts_authored"),
                   "ruled_by": person}
    project.log("holdouts_authored", record)
    return saved


def _retire_one(custody: Path, cid: str, because: str) -> bool:
    """Move one criterion's scenario out of the runs, into ``<cid>.retired.json`` beside it: its
    steps under the card that retired it, after any retired before. That file is not a scenario
    (it has no steps of its own), so no holdout run loads it (kernel/operate.py load_scenarios),
    while it stays custody content that output is redacted against (mcp/server.py)."""
    source = custody / f"{cid}.json"
    if not _SAFE_NAME.fullmatch(cid) or not source.is_file():
        return False
    try:
        doc = read_json(source)
    except ValueError:  # an unreadable scenario never ran; it leaves all the same
        doc = None
    archive = custody / f"{cid}{RETIRED}"
    kept = read_json(archive) or {"criterion": cid, "retired": {}}
    kept["retired"][because] = doc.get("steps") if isinstance(doc, dict) else None
    write_json(archive, kept)
    source.unlink()
    return True


def retire_holdouts(project: Project, criteria: Iterable[str], *, because: str) -> list[str]:
    """Take the scenarios of criteria a change withdrew or restated out of the holdout runs, and
    keep them in the custody, never shown to the builder (see `_retire_one`). A restated criterion
    then has no scenario, so the holdout author writes it anew before the next delivery
    (``author_holdouts(only="missing")``); a withdrawn one is in no check plan, so it gets none.
    Returns the criteria whose scenario was retired."""
    if not _SAFE_NAME.fullmatch(because):
        raise ValueError(f"a retirement names the card behind it, got {because!r}")
    moved = [cid for cid in sorted(set(criteria)) if _retire_one(project.holdouts_dir, cid, because)]
    if moved:
        project.log("holdouts_retired", {"criteria": moved, "because": because})
    return moved
