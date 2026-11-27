"""Alignment: a repository's own structure mapped onto Rihmasto's model, proposed and never applied (FR-ALN1,
docs/guides/alignment.md).

kernel/repo_structure.py captures what a team keeps in its repository. `propose` turns that structure map into
items a person accepts, edits or rejects (kernel/alignment_records.py records the decision):

- **requirements** from the repository's specs, stories and PRDs, keeping their ids and titles as source refs
  (a Rihmasto id is proposed: their own when it is a valid, unused id, else one built from it, else IMP-n);
- **criteria** from their acceptance lists, Gherkin scenarios and EARS lines, as given / when / then; a
  requirement the repository gives no criterion gets one derived from its statement, and says so;
- **tests trace**: each existing test linked to the criterion it most likely checks, by name (the test's name
  carries the id), by file (its file or suite names the feature) or by text similarity, each link with its
  basis and a confidence;
- **tasks** from their task lists, done or open, with the requirements they name;
- **decisions** from their ADRs, and **API contracts** kept as references;
- **gaps**: requirements with no test, tests with no requirement, criteria not testable as written, a spec
  older than the code it describes (by commit dates), and CI that does not run the tests.

Each item says what it would add or change in the Rihmasto project (never in the repository), why, and the
lines it came from. Item ids are stable for the same source, so a re-scan finds the same items again, and a
fingerprint of what each says shows when it changed (drift).
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

GROUPS = ("requirements", "criteria", "trace", "tasks", "decisions", "contracts", "gaps")
GROUP_LABEL = {"requirements": "Requirements", "criteria": "Criteria", "trace": "Tests trace", "tasks": "Tasks",
               "decisions": "Decisions", "contracts": "API contracts", "gaps": "Gaps"}
PREFIX = {"requirements": "req", "criteria": "crit", "trace": "trace", "tasks": "task", "decisions": "adr",
          "contracts": "api", "gaps": "gap"}
_REQ_ID = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$")
VAGUE = re.compile(r"(?i)\b(user[- ]friendly|intuitive(ly)?|easy|easily|simple|fast|quick(ly)?|efficient(ly)?|robust"
                   r"|seamless(ly)?|appropriate(ly)?|as needed|flexible|modern|nice|reasonable|adequate(ly)?|scalable"
                   r"|performant|clean|etc)\b")
STOP = frozenset(("a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are", "be", "by", "as",
                  "at", "it", "its", "this", "that", "when", "then", "given", "shall", "must", "should", "system",
                  "user", "can", "will", "from", "into", "not", "no", "their", "they", "them", "we", "our", "you",
                  "your", "has", "have", "was", "were", "any", "all", "each", "every", "test", "tests", "spec", "do",
                  "does"))
WEAK = 0.5                         # a link below this confidence is shown as weak


def _sha(*parts: Any) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def item_id(group: str, key: str) -> str:
    return f"{PREFIX[group]}-{_sha(key)[:10]}"


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> set[str]:
    """A text's content words, lower case and roughly stemmed: snake_case and camelCase split."""
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", str(text).replace("_", " "))
    return {_stem(w.lower()) for w in words if w.lower() not in STOP and (len(w) >= 3 or (w.isdigit() and len(w) >= 2))}


def similarity(a: set[str], b: set[str]) -> float:
    return len(a & b) / math.sqrt(len(a) * len(b)) if a and b else 0.0


def _ref_pattern(ref: str) -> re.Pattern | None:
    """How a test name carries an id: FR-001 as fr_001, fr001 or FR-1; None for an id with no letter and digit."""
    m = re.fullmatch(r"([A-Za-z]+)[-_ ]?0*(\d+)((?:[-_.]\w+)*)", ref.strip())
    if not m:
        m2 = re.fullmatch(r"([A-Za-z]+)-([A-Za-z]+)", ref.strip())
        word = rf"(?<![a-z0-9]){m2.group(1).lower()}[_\-\s]?{m2.group(2).lower()}(?![a-z0-9])" if m2 else None
        return re.compile(word) if word else None
    rest = "".join(rf"[_\-\s.]?0*{re.escape(p)}" for p in re.split(r"[-_.]", m.group(3)) if p)
    return re.compile(rf"(?<![a-z0-9]){m.group(1).lower()}[_\-\s]?0*{m.group(2)}{rest.lower()}(?![0-9])")


def _rid(ref: str | None, feature: str | None, used: set[str], counter: list[int]) -> str:
    """The Rihmasto id proposed for a requirement: their own id when it is a valid, unused one; else one built
    from it (User Story 2 as US-2, Requirement 1 as REQ-1, F001-FR-001 for a spec-kit feature's FR-001 taken by
    another feature); else the next IMP-n."""
    cands: list[str] = []
    if ref:
        r = ref.strip()
        r = re.sub(r"(?i)^user\s+story\s+", "US-", r)
        r = re.sub(r"(?i)^requirement\s+", "REQ-", r)
        r = re.sub(r"(?i)^story\s+", "STORY-", r)
        r = re.sub(r"[.\s_]+", "-", r.upper())
        r = re.sub(r"^([A-Z]+)(\d)", r"\1-\2", r)
        cands.append(r)
        num = re.match(r"^(\d{3,4})-", feature or "")
        if num:
            cands.append(f"F{num.group(1)}-{r}")
    for c in cands:
        if _REQ_ID.fullmatch(c) and c not in used and not re.fullmatch(r"R-\d+|FD-\d+", c):
            return c
    while True:
        counter[0] += 1
        if f"IMP-{counter[0]}" not in used:
            return f"IMP-{counter[0]}"


def _then_of_statement(statement: str) -> str:
    return re.sub(r"(?i)^(the\s+)?system\b", "the system", statement.strip()).rstrip(".")


def untestable(c: dict[str, Any]) -> str | None:
    """Why a criterion cannot be tested as written, or None."""
    words = sorted({m.group(0).lower() for m in VAGUE.finditer(c["then"])})
    if words:
        return f"its then says {', '.join(repr(w) for w in words)}, which no test can observe as written"
    if len(tokens(c["then"])) < 2:
        return "its then names nothing a test can observe"
    return None


# -- requirements and criteria ---------------------------------------------------------------------------

def _requirements(structure: dict[str, Any], kept: dict[str, str], taken: set[str]) -> list[dict[str, Any]]:
    used = set(taken) | set(kept.values())
    counter = [0]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for spec in sorted(structure.get("specs", []), key=lambda s: s["path"]):
        for r in spec["requirements"]:
            base = f"req|{spec['path']}|{r['ref'] or ' '.join(r['title'].lower().split())[:80]}"
            key, n = base, 1
            while key in seen:
                n += 1
                key = f"{base}#{n}"
            seen.add(key)
            rid = kept.get(key) or _rid(r["ref"], spec.get("feature"), used, counter)
            used.add(rid)
            iid = item_id("requirements", key)
            where = f"{spec['path']}:{r['lines'][0]}"
            req = {"id": iid, "group": "requirements", "key": key, "title": (f"{r['ref']}: " if r["ref"] else "")
                   + r["title"], "source": {"path": spec["path"], "lines": r["lines"], "ref": r["ref"],
                                            "convention": spec["convention"], "feature": spec.get("feature")},
                   "proposal": {"id": rid, "statement": r["statement"], "priority": "must"},
                   "adds": f"Requirement {rid} in the project's contract: \"{r['statement']}\", imported from {where}",
                   "why": f"the {spec['convention']} {spec['kind']} states it" + (f" as {r['ref']}" if r["ref"] else "")
                   + (" (a user story)" if r.get("story") else ""),
                   "fingerprint": _sha(r["statement"])[:16], "children": []}
            out.append(req)
            crits = r["criteria"] or [{"given": "-", "when": "-", "then": _then_of_statement(r["statement"]),
                                       "form": "derived", "line": r["lines"][0], "derived": True}]
            for k, c in enumerate(crits, 1):
                ckey = f"{key}|ac{k}"
                cid = f"{rid}-AC-{k}"
                crit = {"id": item_id("criteria", ckey), "group": "criteria", "key": ckey, "parent": iid,
                        "title": f"{cid}: then {c['then']}",
                        "source": {"path": spec["path"], "lines": [c["line"], c["line"]], "ref": r["ref"],
                                   "form": c["form"], "convention": spec["convention"]},
                        "proposal": {"id": cid, "given": c["given"], "when": c["when"], "then": c["then"],
                                     "kind": "test"},
                        "adds": f"Acceptance criterion {cid} under {rid}: given {c['given']}; when {c['when']}; "
                                f"then {c['then']}",
                        "why": ("the repository gives no acceptance criterion for it: derived from its statement"
                                if c.get("derived") else f"the {spec['convention']} spec writes it as {c['form']}"),
                        "derived": bool(c.get("derived")), "untestable": untestable(c),
                        "fingerprint": _sha(c["given"], c["when"], c["then"])[:16]}
                req["children"].append(crit["id"])
                out.append(crit)
    return out


# -- the trace -------------------------------------------------------------------------------------------

def _flat_tests(structure: dict[str, Any]) -> list[dict[str, Any]]:
    return [{**t, "file": f["path"], "framework": f["framework"], "file_date": f.get("date")}
            for f in structure.get("tests", {}).get("files", []) for t in f["tests"]]


def _best(cands: list[dict[str, Any]], words: set[str]) -> tuple[dict[str, Any] | None, float]:
    scored = sorted(((similarity(words, c["_words"]), c["id"], c) for c in cands), key=lambda x: (-x[0], x[1]))
    return (scored[0][2], scored[0][0]) if scored else (None, 0.0)


Link = tuple[dict[str, Any], float, str]          # the criterion, the confidence, the basis


def _feature(req: dict[str, Any]) -> str | None:
    """The feature a requirement belongs to: its spec's feature folder, or a Gherkin feature's own title."""
    return req["source"].get("feature") or (req["title"] if req["source"]["convention"] == "Gherkin" else None)


class _Tracer:
    """The criteria a test may check, indexed for the four rules, tried in order: the criterion's id in the test's
    name, the requirement's id in it, the feature in its file or suite, and the words alone."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        reqs = {i["id"]: i for i in items if i["group"] == "requirements"}
        self.crits = [dict(c, _words=tokens(" ".join([c["proposal"][k] for k in ("given", "when", "then")]
                                                     + [reqs[c["parent"]]["title"]])))
                      for c in items if c["group"] == "criteria"]
        self.by_req: dict[str, list[dict[str, Any]]] = {}
        for c in self.crits:
            self.by_req.setdefault(c["parent"], []).append(c)
        self.own = [(p, c) for c in self.crits if (p := _ref_pattern(c["proposal"]["id"]))]
        self.refs = [(p, r) for r in reqs.values() for ref in sorted({r["source"]["ref"], r["proposal"]["id"]} - {None})
                     if (p := _ref_pattern(ref))]
        self.features = {r["id"]: tokens(re.sub(r"^\d+-", "", name)) for r in reqs.values() if (name := _feature(r))}

    def by_id(self, hay: str, words: set[str]) -> Link | None:
        c = next((c for p, c in self.own if p.search(hay)), None)
        if c is not None:
            return c, 0.95, f"by name: the test's name carries {c['proposal']['id']}"
        r = next((r for p, r in self.refs if p.search(hay)), None)
        best, sim = _best(self.by_req.get(r["id"], []), words) if r else (None, 0.0)
        if r is None or best is None:
            return None
        return best, 0.9, f"by name: the test's name carries {r['source']['ref'] or r['proposal']['id']}; its " \
                          f"criterion by text ({sim:.2f})"

    def by_file(self, t: dict[str, Any], words: set[str]) -> Link | None:
        where = tokens(t["file"]) | tokens(t.get("suite") or "")
        near = [c for rid, fw in self.features.items() if fw and fw <= where for c in self.by_req.get(rid, [])]
        best, sim = _best(near, words)
        if best is None or sim < 0.2:
            return None
        return best, round(min(0.85, 0.55 + 0.3 * sim), 2), f"by file: {t['file']} names the feature; by text: " \
                                                              f"similarity {sim:.2f}"

    def by_text(self, words: set[str]) -> Link | None:
        best, sim = _best(self.crits, words)
        return (best, round(min(0.7, sim), 2), f"by text: similarity {sim:.2f} with the criterion") \
            if best is not None and sim >= 0.34 else None

    def link(self, t: dict[str, Any]) -> Link | None:
        said = " ".join(x for x in (t["name"], t.get("suite") or "", t.get("doc") or "") if x)
        words = tokens(said)
        return self.by_id(said.lower(), words) or self.by_file(t, words) or self.by_text(words)


def _trace_item(t: dict[str, Any], link: Link) -> dict[str, Any]:
    crit, conf, basis = link
    key, cid = f"trace|{t['file']}|{t['name']}", crit["proposal"]["id"]
    return {"id": item_id("trace", key), "group": "trace", "key": key, "title": f"{t['name']} -> {cid}",
            "source": {"path": t["file"], "lines": [t["line"], t["line"]], "framework": t["framework"]},
            "proposal": {"test": t["name"], "file": t["file"], "line": t["line"], "criterion": crit["id"],
                         "criterion_id": cid},
            "adds": f"A trace in the project's records: {t['file']}::{t['name']} checks {cid}",
            "why": basis, "basis": basis.split(":")[0], "confidence": conf, "weak": conf < WEAK,
            "fingerprint": _sha(crit["key"], t["name"])[:16]}


def trace(items: list[dict[str, Any]], structure: dict[str, Any]) -> list[dict[str, Any]]:
    """A link from each test to the criterion it most likely checks, with its basis and confidence. A test no
    rule links to gets no item: it is a gap."""
    tracer = _Tracer(items)
    return [_trace_item(t, link) for t in _flat_tests(structure) if (link := tracer.link(t))]


# -- tasks, decisions, contracts -------------------------------------------------------------------------

def _folder(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _task_targets(task: dict[str, Any], reqs: list[dict[str, Any]], items: dict[str, dict[str, Any]]) -> list[str]:
    near = [r for r in reqs if _folder(r["source"]["path"]) == _folder(task["path"])] or reqs
    out = []
    for ref in task["requirements"]:
        m = re.fullmatch(r"(\d+)\.(\d+)", ref)
        us = re.fullmatch(r"(?i)US(\d+)", ref)
        want = f"Requirement {m.group(1)}" if m else f"User Story {us.group(1)}" if us else ref
        for r in near:
            if (r["source"]["ref"] or "").lower() == want.lower():
                kids = r["children"]
                target = kids[int(m.group(2)) - 1] if m and int(m.group(2)) <= len(kids) else r["id"]
                out.append(target)
    return [x for x in dict.fromkeys(out) if x in items]


def _tasks(structure: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reqs = [i for i in items if i["group"] == "requirements"]
    index = {i["id"]: i for i in items}
    out = []
    for t in structure.get("tasks", []):
        key = f"task|{t['path']}|{t['ref'] or t['title'].lower()[:80]}"
        targets = _task_targets(t, reqs, index)
        names = [index[x]["proposal"]["id"] for x in targets]
        out.append({"id": item_id("tasks", key), "group": "tasks", "key": key,
                    "title": (f"{t['ref']} " if t["ref"] else "") + t["title"],
                    "source": {"path": t["path"], "lines": [t["line"], t["line"]], "ref": t["ref"]},
                    "proposal": {"title": t["title"], "done": t["done"], "targets": targets, "serves": names},
                    "adds": f"A task in the project's records, {'done' if t['done'] else 'open'}: {t['title']}"
                            + (f" (serves {', '.join(names)})" if names else ""),
                    "why": t.get("why") or f"a checkbox of the repository's task list, "     # a table row's (FR-ASP2)
                                           f"{'ticked' if t['done'] else 'not ticked'}",
                    "fingerprint": _sha(t["title"], t["done"])[:16]})
    return out


def _decisions(structure: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for d in structure.get("decisions", []):
        key = f"adr|{d['path']}"
        out.append({"id": item_id("decisions", key), "group": "decisions", "key": key,
                    "title": f"{d['ref'] or 'ADR'}: {d['title']}",
                    "source": {"path": d["path"], "lines": [d["line"]] * 2, "ref": d["ref"]},
                    "proposal": {"ref": d["ref"], "title": d["title"], "status": d["status"], "date": d.get("date")},
                    "adds": f"A decision record in the project ({d['status']}): {d['title']}",
                    "why": f"an architecture decision record, its status {d['status']}",
                    "fingerprint": _sha(d["title"], d["status"])[:16]})
    return out


def _contracts(structure: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for c in structure.get("contracts", []):
        key = f"api|{c['path']}"
        ops = c.get("operations", [])
        out.append({"id": item_id("contracts", key), "group": "contracts", "key": key,
                    "title": f"{c['kind']}: {c.get('title') or c['path']}",
                    "source": {"path": c["path"], "lines": [1, 1]},
                    "proposal": {"kind": c["kind"], "title": c.get("title"), "version": c.get("version"),
                                 "operations": [f"{o['method']} {o['path']}" for o in ops][:50]},
                    "adds": f"A reference to the {c['kind']} contract {c['path']} ({len(ops)} operations), kept as "
                            "it is",
                    "why": "an API contract in the repository: Rihmasto keeps it as a reference, never a copy",
                    "fingerprint": _sha(c.get("version"), len(ops), *[o["path"] for o in ops])[:16]})
    return out


# -- gaps ------------------------------------------------------------------------------------------------

def _gap(kind: str, key: str, title: str, detail: str, path: str | None, refs: list[str],
         lines: list[int] | None = None) -> dict[str, Any]:
    full = f"gap|{kind}|{key}"
    return {"id": item_id("gaps", full), "group": "gaps", "key": full, "title": title, "kind": kind,
            "source": {"path": path, "lines": lines or [1, 1]},
            "proposal": {"kind": kind, "refs": refs, "detail": detail},
            "adds": f"An open gap kept with the project: {title}", "why": detail, "fingerprint": _sha(detail)[:16]}


Items = list[dict[str, Any]]


def _untested(items: Items, links: Items) -> Items:
    traced = {lk["proposal"]["criterion"] for lk in links}
    return [_gap("no_test", r["key"], f"{r['proposal']['id']} has no test", f"no test of the repository traces to "
                 f"{r['title']}", r["source"]["path"], [r["id"]], r["source"]["lines"])
            for r in items if r["group"] == "requirements" and not set(r["children"]) & traced]


def _weak_criteria(items: Items) -> Items:
    out = []
    for c in (i for i in items if i["group"] == "criteria" and (i["untestable"] or i["derived"])):
        kind, title, why = (("untestable", "is not testable as written", c["untestable"]) if c["untestable"] else
                            ("no_criteria", "was derived: the repository gives none", c["why"]))
        out.append(_gap(kind, c["key"], f"{c['proposal']['id']} {title}", why, c["source"]["path"], [c["id"]],
                        c["source"]["lines"]))
    return out


def _loose_tests(links: Items, structure: dict[str, Any]) -> Items:
    linked = {(lk["proposal"]["file"], lk["proposal"]["test"]) for lk in links}
    out = []
    for f in structure.get("tests", {}).get("files", []):
        loose = [t["name"] for t in f["tests"] if (f["path"], t["name"]) not in linked]
        many = len(loose) > 1
        if loose:
            out.append(_gap("no_requirement", f["path"], f"{len(loose)} test{'s' if many else ''} in {f['path']} "
                            f"trace{'' if many else 's'} to no requirement", "no rule links them: "
                            + ", ".join(loose[:12]) + (" and more" if len(loose) > 12 else ""), f["path"], loose[:50]))
    return out


def gaps(items: Items, links: Items, structure: dict[str, Any]) -> Items:
    return (_untested(items, links) + _weak_criteria(items) + _loose_tests(links, structure)
            + _stale(items, links, structure) + _ci(structure))


def _newer(spec: dict[str, Any], items: Items, links: Items, dates: dict[str, Any]) -> list[tuple[str, int]]:
    """The code a spec names, and the test files tracing to its criteria, committed after it."""
    reqs = {i["id"] for i in items if i["group"] == "requirements" and i["source"]["path"] == spec["path"]}
    crits = {i["id"] for i in items if i["group"] == "criteria" and i["parent"] in reqs}
    found = [(m["path"], m.get("date") or 0) for m in spec.get("mentioned", [])]
    found += [(lk["proposal"]["file"], dates.get(lk["proposal"]["file"]) or 0) for lk in links
              if lk["proposal"]["criterion"] in crits]
    return sorted({(p, d) for p, d in found if d > spec["date"]})


def _stale(items: Items, links: Items, structure: dict[str, Any]) -> Items:
    if not structure.get("dated"):
        return []
    out = []
    dates = {f["path"]: f.get("date") for f in structure.get("tests", {}).get("files", [])}
    for spec in (s for s in structure.get("specs", []) if s.get("date")):
        newer = _newer(spec, items, links, dates)
        if newer:
            detail = (f"{spec['path']} was last committed before " + ", ".join(p for p, _ in newer[:6])
                      + ": the code it describes changed after it")
            gap = _gap("stale_spec", spec["path"], f"{spec['path']} is older than the code it describes", detail,
                       spec["path"], [p for p, _ in newer], [1, 1])
            out.append(gap | {"dates": {"spec": spec["date"], "code": max(d for _, d in newer)}})
    return out


def _ci(structure: dict[str, Any]) -> list[dict[str, Any]]:
    tests = structure.get("tests", {})
    if not tests.get("count"):
        return []
    ci = structure.get("ci", [])
    if not ci:
        return [_gap("ci_no_tests", "none", "No CI runs the tests", "the repository has tests and no CI file "
                     "(GitHub Actions, GitLab CI, Azure Pipelines, CircleCI, Jenkins) that runs them", None, [])]
    if any(j["runs_tests"] for f in ci for j in f["jobs"]):
        return []
    jobs = [f"{f['path']}: {j['name']}" for f in ci for j in f["jobs"]]
    return [_gap("ci_no_tests", "jobs", "The CI does not run the tests", "no job runs a test command: "
                 + "; ".join(jobs[:10]), ci[0]["path"], jobs)]


# -- the proposal ----------------------------------------------------------------------------------------

def summary(items: list[dict[str, Any]], structure: dict[str, Any]) -> dict[str, Any]:
    total = structure.get("tests", {}).get("count", 0)
    traced = sum(1 for i in items if i["group"] == "trace")
    reqs = sum(1 for i in items if i["group"] == "requirements")
    no_test = sum(1 for i in items if i.get("kind") == "no_test")
    bad = sum(1 for i in items if i.get("kind") == "untestable")
    text = (f"{traced} of {total} tests trace to a criterion; {no_test} of {reqs} requirement"
            f"{'s' if reqs != 1 else ''} {'has' if no_test == 1 else 'have'} no test"
            + (f"; {bad} {'criterion is' if bad == 1 else 'criteria are'} not testable as written" if bad else ""))
    return {"tests": total, "traced": traced, "requirements": reqs, "no_test": no_test, "untestable": bad,
            "text": text, "against": _against(reqs, structure)}


def _against(reqs: int, structure: dict[str, Any]) -> str:
    """What the trace counts are measured against, and what they leave out (FR-ASP1)."""
    specs = sorted({s.get("path") for s in structure.get("specs", []) if s.get("path")})
    read = ", ".join(specs[:3]) or "no document"
    frameworks = ", ".join(structure.get("tests", {}).get("frameworks") or []) or "no framework"
    return (f"measured against the {reqs} requirement{'s' if reqs != 1 else ''} read from {read}"
            f"{' and more' if len(specs) > 3 else ''}, and the test files found by rule (written for {frameworks}): a "
            "runner of the project's own is not counted here")


def propose(structure: dict[str, Any], *, kept: dict[str, str] | None = None,
            taken: set[str] | None = None) -> dict[str, Any]:
    """Every item the structure map proposes, by group, with a summary. ``kept`` maps the key of an item
    already accepted to the Rihmasto id it was given; ``taken`` holds ids the project's contract uses."""
    items = _requirements(structure, kept or {}, taken or set())
    links = trace(items, structure)
    items += links + _tasks(structure, items) + _decisions(structure) + _contracts(structure)
    items += gaps(items, links, structure)
    return {"items": items, "summary": summary(items, structure),
            "counts": {g: sum(1 for i in items if i["group"] == g) for g in GROUPS}}
