"""What accepting, rejecting or deferring alignment items would do, before anyone does it (FR-ORG1).

The owner (2026-11-26): "I would also want to understand the impact of changes, not just accept them blindly." For
an item, a bulk selection or a triage action, the kernel works out, writing nothing:

- what Rihmasto's records gain or change: requirements and criteria in the project's contract (and how many of the
  criteria Rihmasto derived), tasks, decisions, API references, test traces and gaps kept as records;
- what the gate then measures: the criteria it checks, how many have a test of the project traced to them and how
  many would show untested, how many tests become counted, how many still trace to no requirement;
- that the repository is never written;
- how the project's measured state shifts (requirements and criteria in the contract, tests counted, open gaps);
- how it is undone.

A suggested change for the repository (kernel/alignment_suggest.py) gets its own impact: the files and areas it
touches, the checks it must pass, that Rihmasto never writes it, and how to undo it.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import alignment as al
from kernel import alignment_evidence as ev
from kernel import alignment_records as ar

REPO_NEVER = "Your repository is never written: nothing in it changes."


def _plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else (many or word + 's')}"


class Context:
    """The latest scan, the decisions and the contract, read once for many impacts."""

    def __init__(self, project: Any, found: dict[str, Any] | None = None) -> None:
        self.project = project
        self.found = found or ar._current(project)
        self.items = self.found["proposal"]["items"]
        self.index = {i["id"]: i for i in self.items}
        self.decided = ar.decisions(project)
        contract = project.read("contract.json") or {}
        reqs = contract.get("requirements", [])
        self.contract = {"requirements": len(reqs), "criteria": sum(len(r.get("acceptance", [])) for r in reqs)}
        self.traced = {i["proposal"]["criterion"] for i in self.items if i["group"] == "trace"}
        self.loose_tests = sum(len(i["proposal"]["refs"]) for i in self.items if i.get("kind") == "no_requirement")
        self.acc = ev.accepted(self.decided)                                  # FR-ORG2: what the contract holds
        self.deferred = set(project.read("alignment/deferred.json", {}) or {})
        self._origins: dict[str, dict[str, Any]] | None = None

    def origin(self, iid: str) -> dict[str, Any]:
        """An item's origin, with the evidence of the current tests (kernel/alignment_evidence.py)."""
        if self._origins is None:
            self._origins = ev.origins(self.items, self.found["structure"], self.decided)
        return self._origins[iid]

    def status(self, iid: str) -> str:
        return ar.status_of(self.index[iid], self.decided.get(iid))

    def accepted(self, group: str) -> set[str]:
        return {k for k, d in self.decided.items() if d["verdict"] == "accept" and d.get("group") == group}

    def rejected(self) -> set[str]:
        return {k for k, d in self.decided.items() if d["verdict"] == "reject"}

    def open_gaps(self, rejected: set[str]) -> int:
        return sum(1 for i in self.items if i["group"] == "gaps" and i["id"] not in rejected
                   and not set(i["proposal"]["refs"]) & rejected)

    def measured(self, add: dict[str, int] | None = None, rejected: set[str] | None = None,
                 accepting: list[str] | tuple[str, ...] = ()) -> dict[str, int]:
        """The measured state; a test is counted only when its trace and its criterion are both accepted."""
        add = add or {}
        no = rejected if rejected is not None else self.rejected()
        return {"requirements": self.contract["requirements"] + add.get("requirements", 0),
                "criteria": self.contract["criteria"] + add.get("criteria", 0),
                "tests_counted": ev.counted(self.items, self.acc | set(accepting)),
                "open_gaps": self.open_gaps(no)}


def _shift(before: dict[str, int], after: dict[str, int]) -> str:
    names = {"requirements": "requirements in the contract", "criteria": "criteria the gate measures",
             "tests_counted": "tests counted against a criterion", "open_gaps": "open gaps"}
    moved = [f"{names[k]} {before[k]} -> {after[k]}" for k in names if before[k] != after[k]]
    return "; ".join(moved) if moved else "the measured state does not move"


Groups = dict[str, list[dict[str, Any]]]


def _contract_line(by: Groups, fresh: Groups) -> str | None:
    if not (by["requirements"] or by["criteria"]):
        return None
    derived = sum(1 for c in by["criteria"] if c.get("derived"))
    changed = len(by["requirements"]) - len(fresh["requirements"])
    return (f"the contract gains {_plural(len(fresh['requirements']), 'requirement')} and "
            f"{_plural(len(fresh['criteria']), 'criterion', 'criteria')}"
            + (f" ({derived} derived by Rihmasto: a requirement in the contract needs one)" if derived else "")
            + (f"; {changed} changed since accepted are updated" if changed else ""))


def _records(by: Groups, fresh: Groups) -> list[str]:
    """What the contract and the project's records gain."""
    done = sum(1 for t in by["tasks"] if t["proposal"]["done"])
    said = {"tasks": lambda n: f"{_plural(n, 'task')} kept in the project's records ({done} done, {n - done} open)",
            "trace": lambda n: f"{_plural(n, 'test')} traced to the criteria they check",
            "decisions": lambda n: f"{_plural(n, 'decision record')} kept",
            "contracts": lambda n: f"{_plural(n, 'API contract reference')} kept, never copied or changed",
            "gaps": lambda n: f"{_plural(n, 'gap')} kept open in the project's records and the IDE notes"}
    lines = [_contract_line(by, fresh)] + [f(len(by[g])) for g, f in said.items() if by[g]]
    return [x for x in lines if x]


def _counted_lines(ctx: Context, traces: list[dict[str, Any]], chosen: list[str]) -> list[str]:
    """Which of the tests traced become counted: only those whose criterion is, or goes, into the contract."""
    take = ctx.acc | set(chosen)
    part: dict[str, list[dict[str, Any]]] = {"now": [], "wait": [], "no": []}
    for t in traces:
        crit = t["proposal"]["criterion"]
        part["now" if crit in take else "no" if ctx.status(crit) == "rejected" else "wait"].append(t)
    return [_said_counted(k, ts) for k, ts in part.items() if ts]


def _said_counted(kind: str, ts: list[dict[str, Any]]) -> str:
    ids = list(dict.fromkeys(t["proposal"]["criterion_id"] for t in ts))
    n, one = len(ts), len(ids) == 1
    named = ", ".join(ids[:4]) + (" ..." if len(ids) > 4 else "")
    if kind == "now":
        return (f"{_plural(n, 'test')} become{'s' if n == 1 else ''} counted when the gate runs "
                f"{'it' if n == 1 else 'them'}")
    if kind == "wait":
        return f"{_plural(n, 'test')} not counted until {named} {'is' if one else 'are'} in the contract"
    return (f"{_plural(n, 'test')} trace{'s' if n == 1 else ''} to {'a criterion' if one else 'criteria'} you "
            f"rejected ({named}): never counted unless {'it is' if one else 'they are'} accepted")


def _gate(ctx: Context, by: Groups, chosen: list[str] | None = None) -> list[str]:
    """What the gate then measures: the criteria and their tests, the tests counted, the tests still loose."""
    crits = by["criteria"]
    untested = [c["proposal"]["id"] for c in crits if c["id"] not in ctx.traced]
    loose = sum(len(g["proposal"]["refs"]) for g in by["gaps"] if g.get("kind") == "no_requirement")
    named = f" ({', '.join(untested[:4])}{' ...' if len(untested) > 4 else ''}) that would show untested"
    out = [f"the gate then measures {_plural(len(crits), 'more criterion', 'more criteria')}: "
           f"{len(crits) - len(untested)} with a test of your project traced to {'it' if len(crits) == 1 else 'them'}, "
           f"{len(untested)} without one yet" + (named if untested else "")] if crits else []
    out += _counted_lines(ctx, by["trace"], chosen or [])
    out += [f"{_plural(loose, 'test')} still trace{'s' if loose == 1 else ''} to no requirement until mapped"] \
        if loose else []
    return out


FIRM_UNDO = ("a requirement or criterion accepted into the contract leaves it only through the change loop (Changes); "
             "the other records can be rejected here later")
SOFT_UNDO = "reject it here later: the record says it was accepted, then rejected"


def _accept(ctx: Context, chosen: list[str]) -> dict[str, Any]:
    by = {g: [ctx.index[i] for i in chosen if ctx.index[i]["group"] == g] for g in al.GROUPS}
    fresh = {g: [i for i in v if ctx.status(i["id"]) == "open"] for g, v in by.items()}
    add = {g: len(fresh[g]) for g in ("requirements", "criteria", "trace")}
    return {"records": _records(by, fresh), "gate": _gate(ctx, by, chosen), "add": add,
            "undo": FIRM_UNDO if by["requirements"] or by["criteria"] else SOFT_UNDO}


def impact(project: Any, ids: list[str], verdict: str, ctx: Context | None = None) -> dict[str, Any]:
    """What deciding these items would do; nothing is written. ``verdict``: accept, reject or defer."""
    ctx = ctx or Context(project)
    unknown = [i for i in ids if i not in ctx.index]
    if unknown or not ids:
        raise ar.AlignRefused(f"no item {', '.join(unknown)} in scan {ctx.found['n']}" if unknown else "name the items")
    if verdict not in ("accept", "reject", "defer"):
        raise ar.AlignRefused(f"the verdict is accept, reject or defer, got {verdict!r}")
    before = ctx.measured()
    out: dict[str, Any]
    if verdict == "defer":
        chosen = list(dict.fromkeys(ids))
        out = {"records": [f"{_plural(len(chosen), 'item')} set aside as deferred: nothing goes into the contract "
                           "or the records"], "gate": ["the gate measures nothing new"], "add": {},
               "undo": "Bring back puts them in the list to decide again"}
        after = before
    else:
        chosen = ar._expand(ids, verdict, ctx.index, ctx.decided)
        if verdict == "accept":
            out = _accept(ctx, chosen)
            after = ctx.measured(out["add"], accepting=chosen)
        else:
            no = ctx.rejected() | set(chosen)
            closes = ctx.open_gaps(ctx.rejected()) - ctx.open_gaps(no)
            out = {"records": [f"{_plural(len(chosen), 'item')} marked rejected: nothing is added"
                               + (f"; {_plural(closes, 'gap')} about them close" if closes else "")],
                   "gate": ["the gate measures nothing new"], "add": {},
                   "undo": f"accept it again later (rihmasto align {project.pid} accept <item>)"}
            after = ctx.measured(rejected=no)
    extra = [i for i in chosen if i not in ids]
    mind, held = _mind(ctx, ids, chosen, verdict)
    said = ("; ".join(out["records"] + out["gate"] + mind) + f". {REPO_NEVER} Measured: {_shift(before, after)}. "
            f"Undo: {out['undo']}.")
    return {"verdict": verdict, "asked": list(dict.fromkeys(ids)), "items": chosen, "taken_with": extra,
            "deferred_taken": held, "mind": mind,
            "records": out["records"], "gate": out["gate"], "repository": REPO_NEVER,
            "measured": {"before": before, "after": after, "said": _shift(before, after)}, "undo": out["undo"],
            "said": said[0].upper() + said[1:]}


def _mind(ctx: Context, ids: list[str], chosen: list[str], verdict: str) -> tuple[list[str], list[str]]:
    """What a person should know before deciding (FR-ORG2): the items taken with the ones asked, those of them they
    had deferred, and for a bulk accept the origin mix (how many may be from an old plan, how many are Rihmasto's
    convention)."""
    if verdict == "defer":
        return [], []
    extra = [i for i in chosen if i not in ids]
    held = [i for i in chosen if i in ctx.deferred and ctx.status(i) == "open"]
    out = [f"{_plural(len(extra), 'more item')} {'comes' if len(extra) == 1 else 'come'} with them "
           f"({ev.names(ctx.index, extra)}): a requirement goes with its open criteria, a criterion with its "
           "requirement"] if extra else []
    out += [f"{len(held)} of these you had deferred ({ev.names(ctx.index, held)}): deciding now decides "
            f"{'it' if len(held) == 1 else 'them'} too"] if held else []
    return out + (_mix(ctx, chosen) if verdict == "accept" and len(chosen) > 1 else []), held


def _mix(ctx: Context, chosen: list[str]) -> list[str]:
    """A bulk accept's origin mix: how many may be from an old plan, how many are Rihmasto's convention."""
    old = [i for i in chosen if ctx.origin(i).get("old")]
    files = sorted({ctx.origin(i)["path"] for i in old})
    conv = sum(1 for i in chosen if ctx.origin(i)["kind"] == "convention")
    more = " and more" if len(files) > 3 else ""
    out = [f"{len(old)} of them may be from an old plan ({', '.join(files[:3])}{more}): accepting records a plan "
           "the code may have left behind"] if old else []
    return out + ([f"{conv} of them {'is' if conv == 1 else 'are'} Rihmasto's convention, not your project's own"]
                  if conv else [])


def _trace_line(ctx: Context, item: dict[str, Any]) -> str:
    """A test counts only when its criterion is in the contract (FR-ORG2)."""
    test, cid, crit = item["proposal"]["test"], item["proposal"]["criterion_id"], item["proposal"]["criterion"]
    if ctx.status(crit) == "rejected":
        return (f"Accept records {test} as the test of {cid}, which you rejected: it is not counted unless {cid} is "
                "accepted.")
    if crit in ctx.acc:
        return f"Accept counts {test} as the test of {cid} when the gate runs it."
    return (f"Accept records {test} as the test of {cid}; it is counted once {cid} is in the contract (accept {cid} "
            "too).")


def _req_line(ctx: Context, item: dict[str, Any]) -> str:
    kids = [ctx.index[c] for c in item["children"] if c in ctx.index]
    derived = sum(1 for c in kids if c.get("derived"))
    traced = sum(1 for c in kids if c["id"] in ctx.traced)
    return (f"Accept adds {item['proposal']['id']} with {_plural(len(kids), 'criterion', 'criteria')} to the contract"
            + (f" ({derived} derived by Rihmasto)" if derived else "")
            + f"; the gate then measures {'it' if len(kids) == 1 else 'them'}: {traced} with a traced test, "
              f"{len(kids) - traced} without.")


def _crit_line(ctx: Context, item: dict[str, Any]) -> str:
    return (f"Accept adds {item['proposal']['id']} to the contract (with its requirement if not there yet); the gate "
            "then " + ("measures it with the test traced to it." if item["id"] in ctx.traced else
                       "measures it, and no test traces to it yet: it would show untested."))


def _gap_line(ctx: Context, item: dict[str, Any]) -> str:
    if item.get("kind") == "no_requirement":
        return (f"Accept keeps this open gap: {_plural(len(item['proposal']['refs']), 'test')} counted as tracing to "
                "no requirement until mapped. No test or file changes.")
    return "Accept keeps this gap open in the project's records and the IDE notes; nothing else changes."


LINES = {
    "requirements": _req_line, "criteria": _crit_line, "gaps": _gap_line,
    "trace": _trace_line,
    "tasks": lambda ctx, i: f"Accept keeps this {'done' if i['proposal']['done'] else 'open'} task in the project's "
                            "records; the contract does not change.",
    "decisions": lambda ctx, i: f"Accept keeps this decision record ({i['proposal']['status']}); the contract does not "
                                "change.",
    "contracts": lambda ctx, i: f"Accept keeps a reference to {i['source']['path']}; Rihmasto never copies or changes "
                                "it.",
}


def line(ctx: Context, item: dict[str, Any]) -> str:
    """One short line: what Accept on this item does, by rule."""
    return LINES[item["group"]](ctx, item)


def of_finding(project: Any, f: dict[str, Any]) -> dict[str, Any]:
    """An assessment finding filed as a change card: what a run building it would touch, check and how to undo."""
    from kernel.alignment_origin import finding_files

    files = finding_files(f)
    areas = sorted({x.split("/", 1)[0] if "/" in x else "(top level)" for x in files})
    touch = ", ".join(files) if files else "the files the change names once triaged"
    checks = "the gate: a failing test first, the project's suite, the verifier"
    undo = "reject the card before it is built; after, the release is rolled back through the change loop"
    return {"files": files, "areas": areas, "checks": checks, "undo": undo,
            "said": f"Filing it opens a change card: nothing is built until a person accepts it. A run would touch "
                    f"{touch}" + (f" (areas: {', '.join(areas)})" if areas else "") + f"; it must pass {checks}. "
                    f"Undo: {undo}."}


def _files(s: dict[str, Any]) -> list[str]:
    found = re.findall(r"^\+\+\+ b/(\S+)", s.get("patch") or "", re.M)
    return list(dict.fromkeys(found or s.get("files") or ([s["path"]] if s.get("path") else [])))


def of_suggestion(project: Any, s: dict[str, Any]) -> dict[str, Any]:
    """A suggested change for the repository: what a person applying it would touch, check and undo."""
    files = _files(s)
    areas = sorted({f.split("/", 1)[0] if "/" in f else "(top level)" for f in files})
    undo = (f"before you commit it, git apply -R {s['file_name']}; after, git revert the commit" if s.get("patch")
            else "remove what you added, or git revert the commit")
    checks = f"your own tests and CI, and the repo gate on the commit (rihmasto repo gate {project.pid})"
    touch = ", ".join(files) if files else "new files of your choosing"
    return {"files": files, "areas": areas, "checks": checks, "undo": undo, "rihmasto_writes": False,
            "said": f"Touches {touch}" + (f" (areas: {', '.join(areas)})" if areas else "")
                    + f". Rihmasto never writes it: you apply it in your IDE. It must pass {checks}. Undo: {undo}."}
