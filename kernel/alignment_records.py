"""The alignment of a project with its repository, recorded (FR-ALN1, docs/guides/alignment.md).

- `scan` reads the project's repository (kernel/repo_structure.py) at its committed revision, proposes the
  items (kernel/alignment.py) and keeps the scan in the project (`alignment/scan.json`, the one before it in
  `alignment/previous.json`), signed by the person who asked, with `alignment_scanned` in the ledger. Nothing
  is written to the repository.
- `decide` records a person's Accept, Edit (an accept with changes) or Reject of items, signed: accepted
  requirements and criteria go into the project's contract (kernel/alignment_contract.py); tasks, decisions,
  trace links, API contract references and gaps are kept as the project's records (`alignment/decisions.json`,
  each with the item as accepted). The ledger holds `alignment_accepted` or `alignment_rejected` with the item
  ids. Accepting a criterion takes its requirement with it; accepting a requirement takes its criteria that
  were not rejected; rejecting a requirement rejects its open criteria.
- `view` is what the cockpit's Alignment tab and `rihmasto align <pid>` show: the items by group with their
  status (open, accepted, rejected, changed since accepted), the summary, the suggested changes for the
  repository (kernel/alignment_suggest.py) and the drift since the scan before: new items, changed ones and
  removed ones. A re-scan after the repository changed shows them for the same accept and reject.
"""

from __future__ import annotations

from typing import Any

from kernel import alignment as al
from kernel import alignment_suggest as sg
from kernel.attach import AttachRefused, check_signer
from kernel.store import Project, updating_json

DIR = "alignment"
SCAN, PREVIOUS, DECISIONS = "alignment/scan.json", "alignment/previous.json", "alignment/decisions.json"
VERDICTS = ("accept", "reject")
STATUSES = ("open", "accepted", "rejected", "changed")
KINDS = ("adopted", "attached")
EDITABLE = {"requirements": ("id", "statement", "priority"), "criteria": ("given", "when", "then"),
            "tasks": ("title", "done"), "decisions": ("title", "status"), "trace": ("criterion",),
            "contracts": (), "gaps": ()}


class AlignRefused(AttachRefused):
    """An alignment request the kernel will not take: the command line exits 2, the cockpit answers 400."""


def applies(project: Project) -> bool:
    return project.meta.get("source_kind") in KINDS


def decisions(project: Project) -> dict[str, dict[str, Any]]:
    return project.read(DECISIONS, {}) or {}


def _kept(decided: dict[str, dict[str, Any]]) -> dict[str, str]:
    """The Rihmasto id each accepted requirement was given, by its item's key: kept across re-scans."""
    return {d["key"]: d["item"]["proposal"]["id"] for d in decided.values()
            if d["verdict"] == "accept" and d.get("group") == "requirements"}


def _taken(project: Project, kept: dict[str, str]) -> set[str]:
    contract = project.read("contract.json") or {}
    return {r["id"] for r in contract.get("requirements", [])} - set(kept.values())


def scan(project: Project, *, person: str, persona: str) -> dict[str, Any]:
    """Read the repository, propose, and keep the scan: signed, recorded, nothing written to the repository."""
    from kernel import repo_structure

    check_signer(person, persona)
    if not applies(project):
        raise AlignRefused(f"{project.pid} has no repository of its own: alignment reads an adopted or attached "
                           "project's repository (`rihmasto adopt` or `rihmasto repo attach`)")
    try:
        structure = repo_structure.for_project(project)
    except (ValueError, KeyError, OSError) as exc:
        raise AlignRefused(f"the repository could not be read: {exc}") from None
    decided = decisions(project)
    kept = _kept(decided)
    proposal = al.propose(structure, kept=kept, taken=_taken(project, kept))
    old = project.read(SCAN)
    n = (old or {}).get("n", 0) + 1
    if old:
        project.write(PREVIOUS, old)
    at = project.factory.clock.stamp()
    project.write(SCAN, {"n": n, "at": at, "by": {"person": person, "persona": persona},
                         "revision": structure.get("revision"), "read_from": structure.get("read_from"),
                         "structure": structure, "proposal": proposal})
    out = view(project)
    project.log("alignment_scanned", {"scan": n, "revision": structure.get("revision"), "person": person,
                                      "persona": persona, "counts": proposal["counts"],
                                      "summary": proposal["summary"]["text"], "conventions": structure["conventions"],
                                      "drift": {k: len(v) for k, v in out["drift"].items() if isinstance(v, list)},
                                      "note": "read from the committed revision; nothing found was run, nothing "
                                              "was written to the repository"})
    return out


def _current(project: Project) -> dict[str, Any]:
    found = project.read(SCAN)
    if not found:
        raise AlignRefused(f"{project.pid} has not been aligned yet: `rihmasto align {project.pid} --scan` (or Read "
                           "the repository in the Alignment tab) reads it first")
    return found


def status_of(item: dict[str, Any], d: dict[str, Any] | None) -> str:
    if d is None:
        return "open"
    if d["verdict"] == "reject":
        return "rejected"
    return "accepted" if item["fingerprint"] in (d.get("fingerprint"), d.get("seen")) else "changed"


Book = dict[str, dict[str, Any]]


def _removed(before: Book, now: Book, decided: Book) -> list[dict[str, Any]]:
    """Items of the scan before, or decided earlier, that the latest scan no longer finds."""
    gone = [{"id": k, "group": i["group"], "title": i["title"], "decided": (decided.get(k) or {}).get("verdict")}
            for k, i in before.items() if k not in now]
    return gone + [{"id": k, "group": d.get("group"), "title": d["item"]["title"], "decided": d["verdict"]}
                   for k, d in decided.items() if k not in now and k not in before]


def _drift(project: Project, items: list[dict[str, Any]], decided: Book) -> dict[str, Any]:
    prev = project.read(PREVIOUS) or {}
    now = {i["id"]: i for i in items}
    before = {i["id"]: i for i in (prev.get("proposal") or {}).get("items", [])}
    moved = {k for k, i in now.items() if k in before and before[k]["fingerprint"] != i["fingerprint"]}
    return {"since": prev.get("n"), "new": [k for k in now if prev and k not in before],
            "changed": [k for k, i in now.items() if k in moved or i["status"] == "changed"],
            "removed": _removed(before, now, decided)}


def _structure_view(structure: dict[str, Any]) -> dict[str, Any]:
    """What the view shows of the structure map: its conventions and counts, how tests run, CI and quality."""
    ci = [{"path": c["path"], "system": c["system"],
           "jobs": [{"name": j["name"], "runs_tests": j["runs_tests"]} for j in c["jobs"]]} for c in structure["ci"]]
    return {**{k: structure.get(k) for k in ("conventions", "counts", "ai_tools", "read_from", "dated")},
            "tests": {k: structure["tests"].get(k) for k in ("frameworks", "run", "coverage", "count")}, "ci": ci,
            "quality": structure.get("quality", []), "skipped": structure.get("skipped", [])}


def _shown(item: dict[str, Any], d: dict[str, Any] | None) -> dict[str, Any]:
    return dict(item, status=status_of(item, d), decision={k: v for k, v in d.items() if k != "item"} if d else None)


def view(project: Project) -> dict[str, Any]:
    """The alignment as a person reads it: items by group with their status, the summary, suggested changes for
    the repository and the drift since the scan before."""
    if not applies(project):
        return {"applies": False, "why": "a project whose code Rihmasto builds itself: there is no team repository "
                                         "to align with"}
    found = project.read(SCAN)
    if not found:
        return {"applies": True, "scanned": False, "kind": project.meta.get("source_kind")}
    decided = decisions(project)
    items = [_shown(i, decided.get(i["id"])) for i in found["proposal"]["items"]]
    groups: list[dict[str, Any]] = []
    for g in al.GROUPS:
        mine = [i for i in items if i["group"] == g]
        groups.append({"id": g, "label": al.GROUP_LABEL[g], "items": mine,
                       "open": sum(1 for i in mine if i["status"] in ("open", "changed"))})
    return {"applies": True, "scanned": True, "kind": project.meta.get("source_kind"),
            "scan": {k: found.get(k) for k in ("n", "at", "by", "revision", "read_from")},
            "summary": found["proposal"]["summary"], "groups": groups,
            "status": {s: sum(1 for i in items if i["status"] == s) for s in STATUSES},
            "suggestions": sg.suggestions(found["proposal"], found["structure"]),
            "structure": _structure_view(found["structure"]), "drift": _drift(project, items, decided),
            "contract": project.meta.get("contract_revision"), "ide": ide_lines(project)}


# -- deciding --------------------------------------------------------------------------------------------

def _edited(item: dict[str, Any], edit: dict[str, Any] | None, index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not edit:
        return item
    allowed = EDITABLE[item["group"]]
    bad = sorted(set(edit) - set(allowed))
    if bad:
        raise AlignRefused(f"{item['id']}: {', '.join(bad)} cannot be edited on a {item['group']} item"
                           + (f"; {', '.join(allowed)} can" if allowed else ""))
    p = dict(item["proposal"])
    for k, v in edit.items():
        if k == "done":
            p[k] = bool(v)
            continue
        text = " ".join(str(v).split())[:2000]
        if not text:
            raise AlignRefused(f"{item['id']}: {k} cannot be empty")
        if k == "id" and not al._REQ_ID.fullmatch(text):
            raise AlignRefused(f"{item['id']}: {text!r} is not a requirement id (letters and digits joined by "
                               "hyphens, such as FR-12)")
        if k == "priority" and text not in ("must", "should", "could"):
            raise AlignRefused(f"{item['id']}: priority is must, should or could")
        if k == "criterion" and (text not in index or index[text]["group"] != "criteria"):
            raise AlignRefused(f"{item['id']}: {text} is not a criterion item of this alignment")
        p[k] = text
    return dict(item, proposal=p, edited=sorted(edit))


def _expand(ids: list[str], verdict: str, index: dict[str, dict[str, Any]], decided: dict[str, dict[str, Any]]
            ) -> list[str]:
    out = list(dict.fromkeys(ids))
    for i in list(out):
        item = index[i]
        if verdict == "accept" and item["group"] == "criteria":
            parent = item["parent"]
            if status_of(index[parent], decided.get(parent)) in ("open", "changed", "rejected") and parent not in out:
                out.insert(0, parent)
        if item["group"] == "requirements":
            for c in item["children"]:
                st = status_of(index[c], decided.get(c))
                if c not in out and ((verdict == "accept" and st in ("open", "changed"))
                                     or (verdict == "reject" and st == "open")):
                    out.append(c)
    return out


def _rid_renamed(item: dict[str, Any], index: dict[str, dict[str, Any]], edits: dict[str, Any]) -> dict[str, Any]:
    """A criterion whose requirement's id was edited takes the new id."""
    parent = index.get(item.get("parent") or "")
    new = (edits.get(parent["id"]) or {}).get("id") if parent else None
    if not new:
        return item
    n = item["proposal"]["id"].rsplit("-AC-", 1)[1]
    return dict(item, proposal=dict(item["proposal"], id=f"{new}-AC-{n}"))


def _groups(chosen: list[str], items: dict[str, dict[str, Any]], index: dict[str, dict[str, Any]],
            decided: dict[str, dict[str, Any]]) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Each requirement to write with its accepted criteria: those accepted now, and those accepted before. A
    criterion takes its requirement's id as accepted (an edited id included)."""
    out: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    for i in chosen:
        rid = i if items[i]["group"] == "requirements" else items[i].get("parent")
        req = (items.get(rid) or (decided.get(rid) or {}).get("item")) if rid and rid not in out else None
        if rid and req is not None:
            out[rid] = (req, _criteria_of(rid, req, items, index, decided))
    return list(out.values())


def _criteria_of(rid: str, req: dict[str, Any], items: dict[str, dict[str, Any]], index: Book, decided: Book
                 ) -> list[dict[str, Any]]:
    """A requirement's criteria to write: those accepted now and those accepted before, under its id."""
    taken = [items.get(c) or (decided[c]["item"] if (decided.get(c) or {}).get("verdict") == "accept" else None)
             for c in index[rid]["children"]]
    crits = [dict(c, proposal=dict(c["proposal"], id=f"{req['proposal']['id']}-AC-"
                                   f"{c['proposal']['id'].rsplit('-AC-', 1)[1]}")) for c in taken if c is not None]
    if not crits:
        raise AlignRefused(f"{rid} has no criterion left to accept: a requirement in the contract needs one")
    return crits


def _asked(project: Project, ids: list[str], verdict: str, edits: dict[str, Any]) -> tuple[dict[str, Any], Book]:
    """The scan the items are of, and its items by id; a request the kernel will not take is refused."""
    if verdict not in VERDICTS:
        raise AlignRefused(f"the verdict is accept or reject, got {verdict!r}")
    if edits and verdict != "accept":
        raise AlignRefused("an edit is accepted with its changes: edit with accept")
    found = _current(project)
    index = {i["id"]: i for i in found["proposal"]["items"]}
    unknown = [i for i in list(ids) + list(edits) if i not in index]
    if unknown or not ids:
        raise AlignRefused(f"no item {', '.join(unknown)} in scan {found['n']}" if unknown else "name the items")
    return found, index


def _refusals(project: Project, chosen: list[str], verdict: str, items: Book, index: Book, decided: Book) -> None:
    """A rejection of what the contract holds, and an id another requirement of the project has, are refused."""
    firm = [i for i in chosen if verdict == "reject" and status_of(index[i], decided.get(i)) == "accepted"
            and index[i]["group"] in ("requirements", "criteria")]
    if firm:
        raise AlignRefused(f"{', '.join(firm)} {'is' if len(firm) == 1 else 'are'} in the contract already: a "
                           "requirement leaves the contract through the change loop, never here")
    kept = _kept(decided)
    taken = _taken(project, kept)
    clash = [items[i]["proposal"]["id"] for i in chosen if items[i]["group"] == "requirements"
             and items[i]["proposal"]["id"] in taken | (set(kept.values()) - {kept.get(index[i]["key"])})]
    if clash:
        raise AlignRefused(f"{', '.join(clash)} is already a requirement of the project: give it another id")


def _entry(verdict: str, old: dict[str, Any], item: dict[str, Any], asked: dict[str, Any]) -> dict[str, Any]:
    """A decision as the book keeps it. Keeping an accepted item whose source changed marks the change seen."""
    if verdict == "reject" and old.get("verdict") == "accept":
        return dict(old, seen=asked["fingerprint"], seen_by=asked["person"], seen_at=asked["at"])
    extra = {"reason": asked["reason"]} if asked["reason"] else {}
    extra |= {"edited": item["edited"]} if item.get("edited") else {}
    return {"verdict": verdict, "person": asked["person"], "persona": asked["persona"], "at": asked["at"],
            "scan": asked["scan"], "key": asked["key"], "group": asked["group"], "fingerprint": asked["fingerprint"],
            "item": item, **extra}


def _write_contract(project: Project, groups: list[tuple[dict[str, Any], list[dict[str, Any]]]], person: str
                    ) -> dict[str, Any]:
    from kernel import alignment_contract
    from kernel.compile import CompileError

    if not groups:
        return {}
    try:
        return alignment_contract.apply(project, groups, person=person)
    except CompileError as exc:
        raise AlignRefused(f"the contract would not pass tools/contract_check.py: {exc}") from None


def decide(project: Project, ids: list[str], verdict: str, *, person: str, persona: str,
           edits: dict[str, dict[str, Any]] | None = None, reason: str = "") -> dict[str, Any]:
    """Accept or reject alignment items, signed by a person; accepted requirements and criteria go into the
    project's contract. Nothing is written to the repository."""
    check_signer(person, persona)
    edits = edits or {}
    found, index = _asked(project, ids, verdict, edits)
    decided = decisions(project)
    chosen = _expand(ids, verdict, index, decided)
    items = {i: _rid_renamed(_edited(index[i], edits.get(i), index), index, edits) for i in chosen}
    _refusals(project, chosen, verdict, items, index, decided)
    groups = _groups(chosen, items, index, decided) if verdict == "accept" else []
    items.update({c["id"]: c for _, crits in groups for c in crits if c["id"] in items})   # as the contract has them
    contract = _write_contract(project, groups, person)
    at = project.factory.clock.stamp()
    with updating_json(project.path(DECISIONS), {}) as book:
        for i in chosen:
            asked = {"person": person, "persona": persona, "at": at, "scan": found["n"], "reason": reason,
                     **{k: index[i][k] for k in ("key", "group", "fingerprint")}}
            book[i] = _entry(verdict, book.get(i) or {}, items[i], asked)
    written = {k: contract.get(k) for k in ("requirements", "criteria")} | {"contract": contract.get("revision")}
    project.log("alignment_accepted" if verdict == "accept" else "alignment_rejected",
                {"items": chosen, "asked": list(dict.fromkeys(ids)), "person": person, "persona": persona,
                 "scan": found["n"], "edited": sorted(edits), **({"reason": reason} if reason else {}),
                 **(written if contract else {}),
                 "provenance": f"imported from the repository, {verdict}ed by {person}"})
    return {"project": project.pid, "verdict": verdict, "items": chosen, "contract": contract.get("revision"),
            "requirements": contract.get("requirements", []), "how": contract.get("how")}


# -- what the rest of Rihmasto reads ----------------------------------------------------------------------

def accepted(project: Project, group: str | None = None) -> list[dict[str, Any]]:
    """The items accepted, as accepted (with their edits), optionally of one group."""
    return [dict(d["item"], decided_by=d["person"], decided_at=d["at"]) for d in decisions(project).values()
            if d["verdict"] == "accept" and (group is None or d.get("group") == group)]


def open_gaps(project: Project) -> list[dict[str, Any]]:
    """The gaps of the latest scan that nobody rejected, about nothing a person rejected: what is still open."""
    found = project.read(SCAN) or {}
    decided = decisions(project)
    no = {k for k, d in decided.items() if d["verdict"] == "reject"}
    return [i for i in (found.get("proposal") or {}).get("items", [])
            if i["group"] == "gaps" and i["id"] not in no and not set(i["proposal"]["refs"]) & no]


def ide_lines(project: Project) -> list[str]:
    """For the section a person pastes into their AGENTS.md or CLAUDE.md ("Work on it from your IDE"): what was
    aligned from the repository and the gaps still open. [] when nothing was aligned."""
    if not applies(project) or not project.read(SCAN):
        return []
    reqs = accepted(project, "requirements")
    lines = ["### Aligned from your repository", ""]
    lines += [f"- **{r['proposal']['id']}** ({r['source']['path']}" + (f", your {r['source']['ref']}"
              if r["source"].get("ref") else "") + f"): {r['proposal']['statement']}" for r in reqs[:30]]
    if not reqs:
        lines.append("- Nothing accepted into the contract yet: the Alignment tab proposes it.")
    traces = accepted(project, "trace")
    if traces:
        lines.append(f"- {len(traces)} of your tests are traced to criteria; name new tests test_<criterion id>_...")
    gaps = open_gaps(project)
    lines += ["", "### Open gaps", ""] + ([f"- {g['title']}: {g['why']}" for g in gaps[:20]] or ["- None."])
    return lines


def gate_note(project: Project, changed: list[str]) -> dict[str, Any] | None:
    """What a change touches of the accepted alignment, for `repo gate`: the accepted criteria whose traced tests
    the change edits, and the criteria in the contract that came from the repository. None when nothing was
    accepted."""
    traces = accepted(project, "trace")
    reqs = accepted(project, "requirements")
    if not traces and not reqs:
        return None
    touched = sorted({t["proposal"]["criterion_id"] for t in traces if t["proposal"]["file"] in set(changed)})
    return {"accepted_requirements": [r["proposal"]["id"] for r in reqs], "criteria_touched": touched,
            "note": "the contract holds the criteria accepted from the repository; a test named test_<criterion id>_ "
                    "is traced by the gate"}
