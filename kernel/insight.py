"""Two read models for people deciding: what a change would touch, and where the canon disagrees
with itself.

- **Impact if changed (FR-P5-AC-2).** Before a person decides a change, they see what it would
  touch: the requirements and their criteria, the tests that name those criteria (on the
  product's main), the tasks that would reopen, the approvals that would go stale, and the
  releases that carry them. Invalidation is shown before the decision, not discovered after it.
- **Alignment (FR-S6).** The canon's contradictions, listed rather than resolved silently:
  - an assumption taken over a recorded dissent from another perspective;
  - a requirement resting on an assumption that was refuted;
  - an open assumption past its due date;
  - a stale approval that nobody has given again;
  - an answer that differs from what was assumed for the same question earlier.
"""

from __future__ import annotations

import re
import subprocess

from kernel.canon import Canon

_TEST_DEF = re.compile(r"^\s*def (test\w+)\s*\(", re.MULTILINE)


def _main_test_names(project) -> list:
    repo = project.path("repo.git")
    if not repo.exists():
        return []
    try:
        files = subprocess.run(["git", "ls-tree", "-r", "--name-only", "main", "tests"], cwd=repo,
                               capture_output=True, text=True, check=True).stdout.split()
        names = []
        for f in files:
            if f.endswith(".py"):
                text = subprocess.run(["git", "show", f"main:{f}"], cwd=repo, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace").stdout
                names += _TEST_DEF.findall(text)
        return names
    except subprocess.CalledProcessError:
        return []


def _releases(project) -> list:
    """Every release record, in release order. Only a release that carries a requirement is shown as
    carrying it: this walker once listed every release (FR-KG1-AC-6; kernel/graph_ask.py parity)."""
    import json

    folder = project.path("releases")
    found = []
    paths = [p for p in folder.glob("*.json") if p.stem.isdigit()] if folder.exists() else []
    for path in sorted(paths, key=lambda p: int(p.stem)):
        try:
            rel = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rel, dict) and isinstance(rel.get("release"), int):
            found.append(rel)
    return found


def impact(project, requirement_ids) -> dict:
    from kernel.gate import tests_naming

    rids = sorted(set(requirement_ids))
    contract = project.read("contract.json") or {"requirements": [], "tasks": []}
    reqs = {r["id"]: r for r in contract["requirements"]}
    criteria = [c["id"] for rid in rids if rid in reqs for c in reqs[rid]["acceptance"]]
    kinds = {c["id"]: (c.get("check") or {}).get("kind", "test") for rid in rids if rid in reqs
             for c in reqs[rid]["acceptance"]}
    names = _main_test_names(project)
    tests = {cid: tests_naming(names, cid) for cid in criteria}
    tasks = [t["id"] for t in contract["tasks"]
             if {c.rsplit("-AC-", 1)[0] for c in t["criteria"]} & set(rids)]
    approvals = []
    for d in Canon(project).decisions(stale=False):
        refs = d.get("refs") or {}
        touched = set(refs.get("requirements", [])) | ({refs["requirement"]} if refs.get("requirement") else set())
        if d["approving"] and (touched & set(rids) or refs.get("scope") == "release"):
            approvals.append({"id": d["id"], "card": d["card"], "kind": d["kind"], "person": d["person"]})
    releases = [{"release": rel.get("release"), "revision": rel.get("revision"), "state": rel.get("state")}
                for rel in _releases(project) if set(rel.get("requirements") or []) & set(rids)]
    unknown = [r for r in rids if r not in reqs]
    return {"requirements": [r for r in rids if r in reqs], "unknown_requirements": unknown,
            "criteria": criteria, "kinds": kinds, "tests": tests, "tasks_reopened": tasks,
            "approvals_going_stale": approvals, "releases_carrying": releases}


def change_impact(project, card_id: str) -> dict | None:
    """The impact of a triaged change card; None until triage names its requirements."""
    card = Canon(project).get_card(card_id)
    tri = (card.get("payload") or {}).get("triage") or {}
    if not tri.get("requirements"):
        return None
    return impact(project, tri["requirements"])


def _gives_again(later: dict, stale: dict) -> bool:
    """The same approval given again, or the same kind of approval given for a later release: a
    release's acceptance that went stale is answered by accepting the release that replaced it."""
    if later["refs"] == stale["refs"]:
        return True
    old, new = (stale.get("refs") or {}).get("release"), (later.get("refs") or {}).get("release")
    return isinstance(old, int) and isinstance(new, int) and new > old


def alignment(project) -> list:
    canon = Canon(project)
    findings = []
    questions = {q["id"]: q for q in canon.questions()}
    for q in questions.values():
        if q["status"] != "assumed":
            continue
        mine = q["opinions"].get(q["perspective"], "").strip()
        others = {p: o for p, o in q["opinions"].items() if p != q["perspective"] and o.strip() and o.strip() != mine}
        if others:
            findings.append({"kind": "assumed_over_dissent", "question": q["id"],
                             "text": f"{q['id']} was assumed (the {q['perspective']} perspective's answer) although "
                                     + ", ".join(sorted(others)) + " disagreed",
                             "refs": {"question": q["id"], "dissent": sorted(others)}})
    refuted = {a["id"]: a for a in canon.assumptions("refuted")}
    spec = project.read("spec.json") or {"requirements": []}
    for r in spec["requirements"]:
        for s in r.get("sources", []):
            q = questions.get(s)
            aid = (q or {}).get("answer", {}) or {}
            aid = aid.get("assumption") if isinstance(aid, dict) else None
            if aid and aid in refuted:
                findings.append({"kind": "rests_on_refuted_assumption", "requirement": r["id"],
                                 "text": f"{r['id']} rests on {s}, whose assumption {aid} was refuted",
                                 "refs": {"requirement": r["id"], "assumption": aid}})
    for a in canon.overdue():
        findings.append({"kind": "assumption_overdue", "assumption": a["id"],
                         "text": f"{a['id']} was due {a['due']} and is still open: {a['text'][:90]}",
                         "refs": {"assumption": a["id"]}})
    for d in canon.decisions(stale=True):
        regiven = [x for x in canon.decisions(stale=False)
                   if x["kind"] == d["kind"] and _gives_again(x, d) and x["approving"] and x["at"] >= d.get("stale_at", "")]
        if not regiven:
            findings.append({"kind": "stale_approval", "decision": d["id"],
                             "text": f"{d['id']} ({d['kind']} by {d['person']}) went stale: {d.get('stale_reason', '')}",
                             "refs": {"decision": d["id"]}})
    for a in canon.assumptions():
        q = questions.get(a.get("question") or "")
        if q and q["status"] == "answered" and q["answer"]["text"].strip() != a["text"].strip():
            findings.append({"kind": "answer_differs_from_assumption", "question": q["id"],
                             "text": f"{q['id']} was answered differently from assumption {a['id']}",
                             "refs": {"question": q["id"], "assumption": a["id"]}})
    return findings
