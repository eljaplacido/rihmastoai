"""Accepted alignment items written into the project's contract (FR-ALN1, docs/guides/alignment.md).

A person accepts requirements and criteria proposed from their repository (kernel/alignment.py). This module
writes them into the **project's** spec and contract, never into the repository:

- each requirement is **customer-endorsed** by the person who accepted it (`decided_by`), with the note
  "imported from the repository (<file>:<line>, their <ref>), accepted by <person> on <date>", and each criterion
  is a visible test;
- a project whose contract is compiled from its spec (an adopted project, an attached one given a spec file)
  gets the requirements in its spec, and the contract is compiled again with no model: every other task keeps
  its id (kernel/compile.py). An attached project whose contract came as a file gets them appended to it, with
  a task per requirement, checked and hashed again. One with no contract yet gets a spec and a contract;
- on an adopted project the task of an imported requirement is the existing work, as an as-is task is: nothing
  is built until a person reopens it through the change loop or a workspace;
- an item accepted again after its source changed restates the requirement or criterion in place.

The contract is checked by tools/contract_check.py before anything is written; a refusal writes nothing.
"""

from __future__ import annotations

from typing import Any

from kernel.store import Project, write_text

SOURCE = "repository"
PROVENANCE = "customer-endorsed"
IMPORTED_NOTE = "imported from the repository's own spec: the existing work, not built by the factory; reopen it " \
                "through the change loop to build it"


def note_of(req: dict[str, Any], person: str, today: str) -> str:
    src = req["source"]
    their = f", their {src['ref']}" if src.get("ref") else ""
    return (f"imported from the repository ({src['path']}:{src['lines'][0]}{their}, {src.get('convention')}), "
            f"accepted by {person} on {today}")


def _criterion(c: dict[str, Any]) -> dict[str, Any]:
    p = c["proposal"]
    return {"id": p["id"], "given": p.get("given") or "-", "when": p.get("when") or "-", "then": p["then"],
            "kind": p.get("kind") or "test"}


def spec_requirement(req: dict[str, Any], crits: list[dict[str, Any]], person: str, today: str) -> dict[str, Any]:
    """An accepted requirement as the project's spec holds it."""
    p = req["proposal"]
    return {"id": p["id"], "statement": p["statement"], "sources": [SOURCE], "priority": p.get("priority", "must"),
            "provenance": PROVENANCE, "decided_by": person, "acceptance": [_criterion(c) for c in crits],
            "notes": note_of(req, person, today), "imported": {"path": req["source"]["path"],
                                                               "ref": req["source"].get("ref"), "item": req["id"]}}


def _merge(reqs: list[dict[str, Any]], new: dict[str, Any]) -> list[str]:
    """Put an accepted requirement into a list of requirements: added, or restated in place with its criteria
    merged by id. Returns the criterion ids it changed."""
    old = next((r for r in reqs if r["id"] == new["id"]), None)
    if old is None:
        reqs.append(new)
        return [c["id"] for c in new["acceptance"]]
    old.update({k: new[k] for k in ("statement", "notes", "decided_by", "decided_on", "provenance") if k in new})
    changed = [c["id"] for c in new["acceptance"] if _put_criterion(old["acceptance"], c)]
    old["acceptance"].sort(key=lambda c: int(c["id"].rsplit("-", 1)[1]))
    return changed


def _put_criterion(have: list[dict[str, Any]], c: dict[str, Any]) -> bool:
    """Add a criterion, or restate the one with its id; whether anything changed."""
    old = next((x for x in have if x["id"] == c["id"]), None)
    if old is None:
        have.append(c)
        return True
    if all(old.get(k) == c.get(k) for k in ("given", "when", "then")):
        return False
    old.update({k: c[k] for k in ("given", "when", "then")})
    return True


def _as_contract(r: dict[str, Any], today: str) -> dict[str, Any]:
    from kernel.compile import _contract_requirement

    return _contract_requirement(r, today)


def _put_task(tasks: list[dict[str, Any]], req: dict[str, Any]) -> None:
    """The task that serves a requirement appended to a contract file: one per requirement, AL-n."""
    crits = [c["id"] for c in req["acceptance"]]
    task = next((t for t in tasks if t.get("criteria") and t["criteria"][0].rsplit("-AC-", 1)[0] == req["id"]), None)
    if task is not None:
        task["criteria"] = crits
        return
    n = 1 + sum(1 for t in tasks if str(t.get("id", "")).startswith("AL-"))
    tasks.append({"id": f"AL-{n}", "title": req["statement"][:100], "criteria": crits})


def _direct(project: Project, contract: dict[str, Any], accepted: list[dict[str, Any]], today: str) -> dict[str, Any]:
    """Append to a contract that came as a file: each requirement with its task, checked and hashed again."""
    from kernel.compile import CompileError, contract_check

    cc = contract_check()
    doc = {k: v for k, v in contract.items() if k != "revision"}
    reqs = [dict(r, acceptance=[dict(c) for c in r["acceptance"]]) for r in doc["requirements"]]
    tasks = [dict(t) for t in doc.get("tasks", [])]
    for spec_req in accepted:
        new = _as_contract(spec_req, today)
        _merge(reqs, new)
        _put_task(tasks, next(r for r in reqs if r["id"] == new["id"]))
    doc.update(requirements=reqs, tasks=tasks)
    if "counts" in doc:
        doc["counts"] = {"requirements": len(reqs), "criteria": sum(len(r["acceptance"]) for r in reqs),
                         "tasks": len(tasks)}
    doc["revision"] = cc.canonical_revision(doc)
    report, _ = cc.check(doc)
    if report.violations:
        raise CompileError(report.violations)
    return doc


Groups = list[tuple[dict[str, Any], list[dict[str, Any]]]]


def apply(project: Project, groups: Groups, *, person: str) -> dict[str, Any]:
    """Write accepted requirements (each with its accepted criteria) into the project's spec and contract.
    Returns the new contract revision and the requirement and criterion ids written."""
    from kernel.compile import check_plan

    if not groups:
        return {"revision": project.meta.get("contract_revision"), "requirements": [], "criteria": []}
    today = project.factory.clock.today().isoformat()
    accepted = [spec_requirement(r, cs, person, today) for r, cs in groups]
    contract = project.read("contract.json")
    from_spec = project.read("spec.json") is not None and (
        contract is None or (contract.get("source") or {}).get("spec") == "spec.json")
    if contract is not None and not from_spec:
        doc = _direct(project, contract, accepted, today)
        changed = [c["id"] for r in accepted for c in r["acceptance"]]
        how = "appended to the contract file it was given"
    else:
        doc, changed = _via_spec(project, accepted)
        how = "added to the project's spec, and the contract compiled again"
    project.write("contract.json", doc)
    project.write("checkplan.json", check_plan(doc))
    if project.meta.get("source_kind") == "adopted" and project.path("repo.git").exists():
        _adopted_tasks(project, doc, {r["id"] for r in accepted})
    project.update_meta(contract_revision=doc["revision"], stage=max(5, int(project.meta.get("stage") or 5)))
    return {"revision": doc["revision"], "requirements": [r["id"] for r in accepted], "criteria": changed, "how": how}


def _via_spec(project: Project, accepted: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """The requirements in the project's spec (one is made when there is none), the contract compiled from it;
    the spec before is kept as a version. A CompileError leaves everything as it was."""
    from kernel.compile import to_contract
    from kernel.spec import render_spec_md

    before = project.read("spec.json")
    spec = before or {"title": project.meta.get("title"), "summary": "", "users": [], "stack": "existing repository",
                      "maturity": project.meta.get("maturity") or "production", "requirements": []}
    spec = dict(spec, requirements=[dict(r, acceptance=[dict(c) for c in r["acceptance"]])
                                    for r in spec.get("requirements", [])])
    changed = [cid for r in accepted for cid in _merge(spec["requirements"], r)]
    doc = to_contract(project, spec)
    if before is not None:
        version = project.meta.get("spec_version", 1)
        project.write(f"spec.v{version}.json", before)
        project.update_meta(spec_version=version + 1)
    project.write("spec.json", spec)
    write_text(project.path("spec.md"), render_spec_md(spec))
    return doc, changed


def _adopted_tasks(project: Project, contract: dict[str, Any], rids: set[str]) -> None:
    """On an adopted project: the new contract in its mirror's main, as an amendment's is, and the tasks of the
    imported requirements held as the existing work."""
    from kernel.compile import update_repo_contract

    update_repo_contract(project, contract)
    adopted = project.read("adopted.json", {}) or {}
    state = project.read("tasks.json", {}) or {}
    for t in contract["tasks"]:
        if {c.rsplit("-AC-", 1)[0] for c in t["criteria"]} <= rids and t["id"] not in state:
            state[t["id"]] = {"status": "merged", "revision": adopted.get("baseline"), "rounds": [], "adopted": True,
                              "imported": True, "note": IMPORTED_NOTE}
    project.write("tasks.json", state)
