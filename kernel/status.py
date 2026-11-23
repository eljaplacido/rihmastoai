"""Read models that tell people where a project stands (after Codex, Kiro and Linear's agent guidelines).

- **evidence:** every criterion's evidence state, so a claim is never shown as a fact.
  - *verified*: a passing gate at the merged revision, and a test on main names it.
  - *claimed*: a test names it, but no gate proved it.
  - *held_out*: it passed against a running release.
  - *failing*, or *not_measured*.
- **now:** one line on what the project is doing, and its state: working, waiting_on_you, done
  or failed.
- **health:** on track, at risk or off track. Each reason names a record. The forecast comes
  from the project's own history, and says "not measured" until there is some.
"""

from __future__ import annotations

import datetime as dt
import json
from statistics import median
from typing import Any

from kernel.canon import Canon
from kernel.insight import _main_test_names, alignment

DECISION_KINDS = ("question", "approval", "validation", "deploy_gate", "escalation", "holdout_ruling", "road",
                  "trust", "incident", "change")


def _releases(project) -> list:
    d = project.path("releases")
    if not d.exists():
        return []
    out = []
    for path in sorted((p for p in d.glob("*.json") if p.stem.isdigit()), key=lambda p: int(p.stem)):
        try:
            rel = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        rel.setdefault("number", int(path.stem))
        out.append(rel)
    return out


def evidence(project) -> list:
    from kernel.gate import tests_naming

    contract = project.read("contract.json") or {"requirements": [], "tasks": []}
    names = _main_test_names(project)
    task_of = {cid: t["id"] for t in contract["tasks"] for cid in t["criteria"]}
    ledger = project.ledger()
    passed_gates = {r["event"]["payload"]["task"]: r["event"]["payload"] for r in ledger.of_kind("gate")
                    if r["event"]["payload"].get("verdict") == "passed"}
    merged = {r["event"]["payload"]["task"]: r["event"]["payload"] for r in ledger.of_kind("merged")}
    held = {}
    for rel in _releases(project):
        for step in rel.get("steps", []):
            if not isinstance(step, dict) or not str(step.get("step", "")).startswith("holdouts:"):
                continue
            native = step.get("native") or {}
            failing = {f["criterion"] for f in native.get("failing", [])}
            ran = set(native.get("ran") or [])
            if step.get("outcome") == "passed" and not ran:
                ran = {c["id"] for r in contract["requirements"] for c in r["acceptance"]
                       if (c.get("check") or {}).get("kind") in ("holdout", "probe")}
            for cid in ran | failing:
                held[cid] = ("failing" if cid in failing else "held_out", rel["number"])
    out = []
    for r in contract["requirements"]:
        for c in r["acceptance"]:
            cid, kind = c["id"], (c.get("check") or {}).get("kind", "test")
            row = {"criterion": cid, "requirement": r["id"], "kind": kind, "state": "not_measured", "evidence": []}
            if kind in ("holdout", "probe"):
                if cid in held:
                    state, rel_no = held[cid]
                    row.update(state=state, evidence=[{"kind": "holdout", "release": rel_no}])
            else:
                tests = tests_naming(names, cid)
                task = task_of.get(cid)
                gate, merge = passed_gates.get(task), merged.get(task)
                if tests and gate and merge and merge.get("warranted") == "passed":
                    row.update(state="verified", evidence=[{"kind": "gate", "task": task, "round": gate.get("round"),
                                                            "revision": merge.get("revision"), "tests": tests}])
                elif tests:
                    row.update(state="claimed", evidence=[{"kind": "test_named", "tests": tests,
                                                           "why": "no passing gate proved it"}])
            out.append(row)
    return out


def now(project) -> dict:
    canon, meta = Canon(project), project.meta
    waiting = [c for c in canon.cards() if c["kind"] in DECISION_KINDS
               and (c["kind"] != "question" or c.get("blocking"))
               and (c["kind"] != "change" or (c["payload"].get("triage") or {}).get("needs_decision"))]
    tasks = project.read("tasks.json", {}) or {}
    building = [t for t, s in tasks.items() if s.get("status") == "building"]
    records = project.ledger().records()
    last = records[-1] if records and isinstance(records[-1], dict) else {}
    since = (last.get("event") or {}).get("at")
    if meta.get("halted"):
        return {"state": "failed", "line": "A person stopped the build.", "since": since}
    if meta.get("pause"):
        pz = meta["pause"]
        where = f" at {pz['stopped_at']}" if pz.get("stopped_at") else " (stopping at the next safe point)"
        return {"state": "paused", "line": f"Paused by {pz.get('requested_by')}{where}.", "since": since}
    if building:
        contract = project.read("contract.json") or {"tasks": []}
        title = next((t["title"] for t in contract["tasks"] if t["id"] == building[0]), "")
        rounds = len(tasks[building[0]].get("rounds", []))
        line = f"Building {building[0]}: {title[:70]}" + (f" (repair round {rounds})" if rounds else "")
        return {"state": "working", "line": line, "since": since}
    if waiting:
        kinds = sorted({c["kind"].replace("_", " ") for c in waiting})
        return {"state": "waiting_on_you", "line": f"{len(waiting)} decision(s) waiting: " + ", ".join(kinds),
                "since": since, "cards": [c["id"] for c in waiting]}
    rels = _releases(project)
    if rels and rels[-1].get("state") == "done":
        return {"state": "done", "line": f"Release {rels[-1]['number']} is live ({meta['maturity']}).", "since": since}
    if rels and rels[-1].get("state") == "failed":
        from kernel.deliver import custody_safe  # what a holdout expected stays out of the one line

        return {"state": "failed", "since": since,
                "line": f"Release {rels[-1]['number']} stopped: "
                        f"{custody_safe(rels[-1].get('reason')) or rels[-1].get('failed_step')}"}
    return {"state": "working", "line": f"Stage {meta['stage']}: ready for the next step.", "since": since}


def live(project, *, lanes_root=None) -> dict:
    """What the running cell is doing right now, read from Gnomon's own audit trail in the lane
    the project holds: the task, the model, tool steps so far and the last action. Nothing is
    guessed: without a held lane or a trail, it says so."""
    from pathlib import Path

    from kernel.lanes import lanes_root as default_root

    root = Path(lanes_root or default_root())
    for lease in sorted(root.glob(".lane-*.lease.json")) if root.exists() else []:
        try:
            holder = json.loads(lease.read_text(encoding="utf-8")).get("holder") or ""
        except ValueError:
            continue
        if not holder.startswith(project.pid + ":"):
            continue
        lane = root / lease.name[1:-len(".lease.json")]
        trails = sorted((lane / ".gnomon-audit").glob("task-*.jsonl"), key=lambda p: p.stat().st_mtime) \
            if (lane / ".gnomon-audit").exists() else []
        out: dict[str, Any] = {"running": True, "task": holder.split(":", 1)[1], "lane": lane.name, "steps": 0,
                               "model": None, "role": None, "last": None, "ended": False}
        if trails:
            for line in trails[-1].read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                kind = rec.get("kind")
                if kind == "session_start":
                    out["role"] = rec.get("role")
                elif kind == "model_call":
                    out["model"] = rec.get("model") or out["model"]
                elif kind == "tool_call":
                    out["steps"] += 1
                    out["last"] = {"tool": rec.get("tool"), "target": str(rec.get("target") or "")[:120],
                                   "at": rec.get("ts"), "bucket": rec.get("bucket")}
                elif kind == "session_end":
                    out["ended"] = True
        return out
    return {"running": False, "why": "no lane is held for this project"}


def try_it(project) -> dict:
    """The acceptance checklist for people who try the product: each criterion as a check against
    the running release, with its evidence state beside it."""
    rels = _releases(project)
    base, env, number = None, None, None
    for rel in reversed(rels):
        for step in reversed(rel.get("steps", [])):
            if not isinstance(step, dict):
                continue
            url = (step.get("native") or {}).get("base_url")
            if str(step.get("step", "")).startswith("deploy") and url:
                base, env, number = url, step["step"].split(":", 1)[-1], rel["number"]
                break
        if base:
            break
    contract = project.read("contract.json") or {"requirements": []}
    states = {e["criterion"]: e["state"] for e in evidence(project)}
    items = []
    for r in contract["requirements"]:
        for c in r["acceptance"]:
            given = c.get("given") if c.get("given") not in (None, "", "-") else None
            when = c.get("when") if c.get("when") not in (None, "", "-") else None
            text = " ".join(x for x in (f"Given {given}," if given else "", f"when {when}," if when else "",
                                        f"check that {c['then']}.") if x)
            items.append({"criterion": c["id"], "requirement": r["id"], "statement": r["statement"],
                          "text": text[0].upper() + text[1:], "evidence": states.get(c["id"], "not_measured")})
    return {"release": number, "env": env, "url": base, "items": items}


def health(project) -> dict:
    canon = Canon(project)
    tasks = project.read("tasks.json", {}) or {}
    reasons, status = [], "on_track"
    if project.meta.get("halted") or any(s.get("status") == "stopped" for s in tasks.values()):
        status = "off_track"
        reasons.append("a person stopped the build")
    reasons += [f"{c['id']}: {c['title']}" for c in canon.cards(kind="escalation")]
    reasons += [f"{c['id']}: {c['title']}" for c in canon.cards(kind="holdout_ruling")]
    reasons += [f"assumption {a['id']} is overdue (due {a['due']})" for a in canon.overdue()]
    reasons += [f["text"] for f in alignment(project) if f["kind"] == "stale_approval"]
    rels = _releases(project)
    if rels and rels[-1].get("state") == "failed":
        reasons.append(f"release {rels[-1]['number']} stopped")
    if reasons and status == "on_track":
        status = "at_risk"
    started, durations = {}, []
    for rec in project.ledger().records():
        if not isinstance(rec, dict):
            continue
        ev = rec.get("event") or {}
        pl, at = ev.get("payload") or {}, ev.get("at")
        if not at:
            continue
        t = dt.datetime.fromisoformat(at.replace("Z", "+00:00"))
        if ev.get("kind") == "cell_ran" and pl.get("round") == 0 and pl.get("task") not in started:
            started[pl["task"]] = t
        if ev.get("kind") == "merged" and pl.get("task") in started:
            durations.append((t - started.pop(pl["task"])).total_seconds() / 60)
    contract = project.read("contract.json") or {"tasks": []}
    left = sum(1 for t in contract["tasks"] if tasks.get(t["id"], {}).get("status") != "merged")
    per = round(median(durations), 1) if durations else None
    forecast = {"tasks_left": left, "median_task_minutes": per,
                "eta_minutes": round(left * per) if per is not None else None,
                "basis": f"{len(durations)} merged task(s) in this project" if durations
                else "not measured: no task merged yet"}
    return {"status": status, "reasons": reasons, "forecast": forecast}
