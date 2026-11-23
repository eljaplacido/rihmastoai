#!/usr/bin/env python3
"""contract_check: validate a Rihma contract.

No model, no network, standard library only. It judges a contract by fixed rules
and names every violation with its JSON path, what was expected and what it got.

Verdicts and exit codes (the named-verdict vocabulary in docs/spec-to-verify.md):
  0  passed        the contract holds every rule
  2  failed        the contract breaks at least one rule
  4  not measured  the contract could not be read, or its schema version is unknown
  1  internal error, a bug in this tool

Usage:
  python tools/contract_check.py contract/contract.json [--json]
  python tools/contract_check.py --revision contract/contract.json
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import posixpath
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Who counts as a person is the kernel's one definition (kernel/people.py, FR-O8-AC-7): a
# decision attributed to the factory, a model, an agent, the assistant or the kernel was not
# made by a human. The import loads only kernel/__init__.py, kernel/verdicts.py and
# kernel/people.py, all standard library, so this tool still runs without a factory home.
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from kernel.people import is_person  # noqa: E402

SCHEMA = "gnomonfactory.contract/1"
REPORT_SCHEMA = "gnomonfactory.contract_check/1"

PROVENANCE = ("customer-confirmed", "customer-endorsed", "vendor-proposed", "assumption", "withdrawn")
NEEDS_HUMAN = ("customer-confirmed", "customer-endorsed")
CHECK_KINDS = ("test", "holdout", "browser_walk", "probe", "signed_manual")
# Paths no task may claim write access to: the contract and the specs it was compiled from, and the
# ontology the knowledge graph is checked against (kernel/ontology.json), which only the owner amends.
# A write glob claims one when it can name it, a folder above it or (for a folder) anything inside it,
# however it is spelled (claims_protected).
PROTECTED_WRITE = ("contract/", "specs/", "intake/", "decisions/", "kernel/ontology.json")

REQ_ID = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$")
TASK_ID = re.compile(r"^[A-Z][A-Z0-9]*-?[0-9]+[A-Z0-9-]*$")
GLOB = re.compile(r"^[^\s]+$")

KEYS = {
    "top": ({"schema", "contract", "requirements", "tasks"},
            {"revision", "source", "bans", "verification_plan", "counts"}),
    "source": (set(), {"spec", "spec_sha256", "brief", "brief_sha256", "generated_by"}),
    "requirement": ({"id", "statement", "provenance", "acceptance"},
                    {"group", "decided_by", "decided_on", "notes"}),
    "criterion": ({"id", "then"}, {"given", "when", "check", "must_differ_on"}),
    "check": ({"kind"}, {"ref", "command"}),
    "task": ({"id", "title", "criteria"}, {"scope", "depends_on"}),
    "scope": (set(), {"write", "read"}),
    "ban": ({"form", "reason"}, {"scope"}),
    "plan": ({"criterion", "reason", "signed_by", "signed_on"}, set()),
    "counts": (set(), {"requirements", "criteria", "tasks"}),
}


class NotMeasured(Exception):
    """The contract could not be judged at all."""


@dataclass
class Report:
    violations: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    def fail(self, rule: str, path: str, expected: str, got) -> None:
        self.violations.append({"rule": rule, "path": path, "expected": expected, "got": got})

    def warn(self, rule: str, path: str, message: str) -> None:
        self.warnings.append({"rule": rule, "path": path, "message": message})


def canonical_revision(contract: dict) -> str:
    """sha256 over canonical JSON (sorted keys, no whitespace), the `revision` key excluded."""
    body = {k: v for k, v in contract.items() if k != "revision"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _keys(rep: Report, obj, kind: str, path: str) -> bool:
    """Check an object's keys. Returns False when `obj` is not an object at all."""
    if not isinstance(obj, dict):
        rep.fail("R-TYPE", path, "an object", type(obj).__name__)
        return False
    required, optional = KEYS[kind]
    for k in sorted(required - obj.keys()):
        rep.fail("R-KEYS", f"{path}/{k}", "a required key", "missing")
    for k in sorted(obj.keys() - required - optional):
        rep.fail("R-KEYS", f"{path}/{k}", "no unknown keys", k)
    return True


def _str(rep: Report, obj: dict, key: str, path: str, *, pattern=None, allow_none=False) -> str | None:
    if key not in obj:
        return None
    value = obj[key]
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip():
        rep.fail("R-TYPE", f"{path}/{key}", "a non-empty string", value)
        return None
    if pattern is not None and not pattern.match(value):
        rep.fail("R-ID", f"{path}/{key}", f"an id matching {pattern.pattern}", value)
    return value


def _str_list(rep: Report, obj: dict, key: str, path: str) -> list[str]:
    value = obj.get(key, [])
    if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
        rep.fail("R-TYPE", f"{path}/{key}", "a list of non-empty strings", value)
        return []
    return value


# -- write globs against the protected paths ---------------------------------------------------------
# The check errs on the side of refusing: * and ? may cross a /, **/ may also match no folder at all, a
# {a,b} group is read as *, and case is ignored (a case-insensitive file system claims the file whatever
# its case).

def _normal_glob(glob: str) -> str:
    """A write glob as the paths it may claim are compared: forward slashes; ./, // and .. resolved; no
    leading slash; every {a,b} group widened to * (whatever an alternative matches, * matches too)."""
    g, n = glob.replace("\\", "/"), 1
    while n:
        g, n = re.subn(r"\{[^{}]*\}", "*", g)
    return posixpath.normpath(g).lstrip("/").lower()


def _glob_tokens(glob: str) -> list[str]:
    """A glob as tokens: *, ?, a character class [...] as fnmatch reads one, or one literal character."""
    out: list[str] = []
    i = 0
    while i < len(glob):
        j = i + 1
        if glob[i] == "[":
            first = j + 1 if glob[j:j + 1] == "!" else j
            first = first + 1 if glob[first:first + 1] == "]" else first
            close = glob.find("]", first)
            j = close + 1 if close >= 0 else j        # no closing ] makes the [ a literal
        out.append(glob[i:j])
        i = j
    return out


def _glob_takes(token: str, c: str) -> bool:
    """Whether one token reads the character ``c``."""
    if token in ("*", "?"):
        return True
    return fnmatch.fnmatchcase(c, token) if len(token) > 1 else token == c


def _glob_closure(tokens: list[str], states: set[int]) -> set[int]:
    """The states reachable without reading a character: past a *, and past a whole **/."""
    out: set[int] = set()
    todo = list(states)
    while todo:
        s = todo.pop()
        if s in out:
            continue
        out.add(s)
        if s < len(tokens) and tokens[s] == "*":
            todo.append(s + 1)
            if tokens[s + 1:s + 3] == ["*", "/"]:
                todo.append(s + 3)
    return out


def _glob_reach(tokens: list[str], text: str) -> set[int]:
    """The glob's states after reading ``text``: empty when no path that starts with it can match."""
    states = _glob_closure(tokens, {0})
    for c in text:
        moved = {s if tokens[s] == "*" else s + 1 for s in states if s < len(tokens) and _glob_takes(tokens[s], c)}
        states = _glob_closure(tokens, moved)
    return states


def claims_protected(glob: str) -> bool:
    """Whether a write glob claims a protected path: the path itself, a folder above it, or anything
    inside a protected folder, however the glob is spelled."""
    g = _normal_glob(glob)
    if g in ("", "."):
        return True                                    # the whole tree
    tokens = _glob_tokens(g)
    for path in PROTECTED_WRITE:
        parts = path.rstrip("/").split("/")
        if any(len(tokens) in _glob_reach(tokens, "/".join(parts[:k])) for k in range(1, len(parts) + 1)):
            return True
        if path.endswith("/") and _glob_reach(tokens, path):
            return True
    return False


def check(contract) -> tuple[Report, dict]:
    """Judge a parsed contract. Raises NotMeasured when it cannot be judged."""
    if not isinstance(contract, dict):
        raise NotMeasured(f"the contract is not a JSON object (got {type(contract).__name__})")
    if contract.get("schema") != SCHEMA:
        raise NotMeasured(f"schema is {contract.get('schema')!r}; this tool judges {SCHEMA!r} only")

    rep = Report()
    _keys(rep, contract, "top", "")
    _str(rep, contract, "contract", "")
    if "source" in contract:
        _keys(rep, contract["source"], "source", "/source")

    reqs = contract.get("requirements", [])
    tasks = contract.get("tasks", [])
    if not isinstance(reqs, list) or not reqs:
        rep.fail("R-TYPE", "/requirements", "a non-empty list", reqs)
        reqs = []
    if not isinstance(tasks, list):
        rep.fail("R-TYPE", "/tasks", "a list", tasks)
        tasks = []

    seen: dict[str, str] = {}

    def unique(id_: str | None, path: str) -> None:
        if id_ is None:
            return
        if id_ in seen:
            rep.fail("R-UNIQUE", path, "an id used once", f"{id_} (also at {seen[id_]})")
        else:
            seen[id_] = path

    criteria: dict[str, dict] = {}        # criterion id -> {"req": provenance, "path": ..., "check": ...}
    withdrawn: set[str] = set()

    for i, req in enumerate(reqs):
        p = f"/requirements/{i}"
        if not _keys(rep, req, "requirement", p):
            continue
        rid = _str(rep, req, "id", p, pattern=REQ_ID)
        unique(rid, f"{p}/id")
        _str(rep, req, "statement", p)
        prov = req.get("provenance")
        if prov not in PROVENANCE:
            rep.fail("R-ENUM", f"{p}/provenance", "one of " + ", ".join(PROVENANCE), prov)
        decided_by = req.get("decided_by")
        if prov in NEEDS_HUMAN and not is_person(decided_by):
            rep.fail("R-HUMAN", f"{p}/decided_by", f"a named person for a {prov} requirement", decided_by)
        acceptance = req.get("acceptance", [])
        if not isinstance(acceptance, list):
            rep.fail("R-TYPE", f"{p}/acceptance", "a list", acceptance)
            acceptance = []
        if prov != "withdrawn" and not acceptance:
            rep.fail("R-CRITERIA", f"{p}/acceptance", "at least one acceptance criterion", "none")
        for j, ac in enumerate(acceptance):
            q = f"{p}/acceptance/{j}"
            if not _keys(rep, ac, "criterion", q):
                continue
            cid = _str(rep, ac, "id", q)
            if cid and rid and not re.fullmatch(re.escape(rid) + r"-AC-[0-9]+", cid):
                rep.fail("R-ID", f"{q}/id", f"{rid}-AC-<n>", cid)
            unique(cid, f"{q}/id")
            _str(rep, ac, "then", q)
            for k in ("given", "when"):
                _str(rep, ac, k, q)
            chk = ac.get("check")
            if chk is not None and _keys(rep, chk, "check", f"{q}/check"):
                kind = chk.get("kind")
                if kind not in CHECK_KINDS:
                    rep.fail("R-ENUM", f"{q}/check/kind", "one of " + ", ".join(CHECK_KINDS), kind)
                if kind == "holdout" and not chk.get("ref"):
                    rep.fail("R-CHECK", f"{q}/check/ref", "a holdout scenario id", "missing")
                if kind == "probe" and not chk.get("command"):
                    rep.fail("R-CHECK", f"{q}/check/command", "the probe command", "missing")
            if "must_differ_on" in ac:
                pair = ac["must_differ_on"]
                if (not isinstance(pair, list) or len(pair) != 2
                        or not all(isinstance(x, dict) and x for x in pair) or pair[0] == pair[1]):
                    rep.fail("R-DIFFER", f"{q}/must_differ_on", "two different, non-empty input objects", pair)
            if cid:
                criteria[cid] = {"prov": prov, "path": q, "check": chk if isinstance(chk, dict) else None}
                if prov == "withdrawn":
                    withdrawn.add(cid)

    # verification plan: signed exceptions for criteria that cannot be tested
    plan = contract.get("verification_plan", [])
    signed: set[str] = set()
    if not isinstance(plan, list):
        rep.fail("R-TYPE", "/verification_plan", "a list", plan)
        plan = []
    for i, entry in enumerate(plan):
        p = f"/verification_plan/{i}"
        if not _keys(rep, entry, "plan", p):
            continue
        cid = entry.get("criterion")
        if cid not in criteria:
            rep.fail("R-REF", f"{p}/criterion", "an existing criterion id", cid)
        if not is_person(entry.get("signed_by")):
            rep.fail("R-HUMAN", f"{p}/signed_by", "a named person", entry.get("signed_by"))
        else:
            signed.add(cid)

    # every criterion the customer stands behind needs a check (or a signed exception)
    for cid, info in criteria.items():
        chk = info["check"]
        if info["prov"] in NEEDS_HUMAN:
            if chk is None and cid not in signed:
                rep.fail("R-CHECK", info["path"] + "/check",
                         "a check, or a signed verification_plan entry", "none")
            elif chk is not None and chk.get("kind") == "signed_manual" and cid not in signed:
                rep.fail("R-CHECK", info["path"] + "/check",
                         "a signed verification_plan entry for a signed_manual check", "none")
        elif chk is None and info["prov"] != "withdrawn":
            rep.warn("W-UNCHECKED", info["path"], f"{info['prov']} criterion has no check yet")

    # tasks: ids, criteria, scope, dependencies
    task_ids: dict[str, int] = {}
    traced: set[str] = set()
    deps: dict[str, list[str]] = {}
    for i, task in enumerate(tasks):
        p = f"/tasks/{i}"
        if not _keys(rep, task, "task", p):
            continue
        tid = _str(rep, task, "id", p, pattern=TASK_ID)
        unique(tid, f"{p}/id")
        _str(rep, task, "title", p)
        crit = _str_list(rep, task, "criteria", p)
        if not crit:
            rep.fail("R-TRACE", f"{p}/criteria", "at least one criterion this task serves", "none")
        for j, cid in enumerate(crit):
            if cid not in criteria:
                rep.fail("R-REF", f"{p}/criteria/{j}", "an existing criterion id", cid)
            elif cid in withdrawn:
                rep.fail("R-TRACE", f"{p}/criteria/{j}", "no work on a withdrawn requirement", cid)
            else:
                traced.add(cid)
        if "scope" in task and _keys(rep, task["scope"], "scope", f"{p}/scope"):
            for k in ("write", "read"):
                for j, g in enumerate(_str_list(rep, task["scope"], k, f"{p}/scope")):
                    if not GLOB.match(g):
                        rep.fail("R-SCOPE", f"{p}/scope/{k}/{j}", "a glob without spaces", g)
                    if k == "write" and claims_protected(g):
                        rep.fail("R-SCOPE", f"{p}/scope/write/{j}",
                                 "no write access to contract/, specs/, intake/, decisions/ or kernel/ontology.json, "
                                 "by name or by a glob that covers them", g)
        if tid:
            task_ids[tid] = i
            deps[tid] = _str_list(rep, task, "depends_on", p)

    for cid, info in criteria.items():
        if cid not in withdrawn and cid not in traced:
            rep.fail("R-TRACE", info["path"], "a task that serves this criterion", "none")

    for tid, ds in deps.items():
        for d in ds:
            if d == tid:
                rep.fail("R-DEPS", f"/tasks/{task_ids[tid]}/depends_on", "no self-dependency", d)
            elif d not in task_ids:
                rep.fail("R-REF", f"/tasks/{task_ids[tid]}/depends_on", "an existing task id", d)
    for cycle in _cycles(deps):
        rep.fail("R-DEPS", "/tasks", "an acyclic dependency graph", " -> ".join(cycle))

    # bans
    bans = contract.get("bans", [])
    if not isinstance(bans, list):
        rep.fail("R-TYPE", "/bans", "a list", bans)
        bans = []
    for i, ban in enumerate(bans):
        if _keys(rep, ban, "ban", f"/bans/{i}"):
            _str(rep, ban, "form", f"/bans/{i}")
            _str(rep, ban, "reason", f"/bans/{i}")

    counts = {"requirements": len(reqs), "criteria": len(criteria), "tasks": len(tasks)}
    if "counts" in contract and _keys(rep, contract["counts"], "counts", "/counts"):
        for k, v in contract["counts"].items():
            if k in counts and v != counts[k]:
                rep.fail("R-COUNTS", f"/counts/{k}", f"{counts[k]} (recomputed)", v)

    revision = canonical_revision(contract)
    if "revision" in contract and contract["revision"] != revision:
        rep.fail("R-REVISION", "/revision", revision, contract["revision"])
    return rep, {"revision": revision, "counts": counts}


def _cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """Dependency cycles, each reported once, starting from its smallest id."""
    found, state, stack = [], {}, []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in graph.get(node, []):
            if nxt not in graph:
                continue
            if state.get(nxt) == 1:
                cyc = stack[stack.index(nxt):]
                k = cyc.index(min(cyc))
                cyc = cyc[k:] + cyc[:k]
                if cyc + [cyc[0]] not in found:
                    found.append(cyc + [cyc[0]])
            elif state.get(nxt) is None:
                visit(nxt)
        stack.pop()
        state[node] = 2

    for n in sorted(graph):
        if state.get(n) is None:
            visit(n)
    return found


def run(path: str) -> tuple[int, dict]:
    """Judge the contract at `path`. Returns (exit code, report)."""
    report: dict[str, Any] = {"schema": REPORT_SCHEMA, "contract": path}
    try:
        with open(path, encoding="utf-8") as fh:
            contract = json.load(fh)
        rep, facts = check(contract)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, NotMeasured) as exc:
        report.update(verdict="not measured", exit=4, reason=str(exc))
        return 4, report
    code = 2 if rep.violations else 0
    report.update(verdict="failed" if code else "passed", exit=code, **facts,
                  violations=rep.violations, warnings=rep.warnings)
    return code, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a Rihma contract.")
    parser.add_argument("contract")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--revision", action="store_true", help="print the canonical revision only")
    args = parser.parse_args(argv)
    try:
        if args.revision:
            with open(args.contract, encoding="utf-8") as fh:
                print(canonical_revision(json.load(fh)))
            return 0
        code, report = run(args.contract)
    except Exception as exc:  # a bug in this tool, never a verdict on the contract
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return code
    if code == 4:
        print(f"NOT MEASURED  {report['reason']}")
        return code
    for v in report["violations"]:
        print(f"FAIL {v['rule']:<11} {v['path'] or '/'}: expected {v['expected']}, got {v['got']!r}")
    for w in report["warnings"]:
        print(f"warn {w['rule']:<11} {w['path']}: {w['message']}")
    c = report["counts"]
    print(f"{report['verdict'].upper()}  {c['requirements']} requirements, {c['criteria']} criteria, "
          f"{c['tasks']} tasks, {len(report['violations'])} violations, {len(report['warnings'])} warnings")
    print(f"revision {report['revision']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
