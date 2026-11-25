"""Read models for the cockpit's dashboard widgets. Each one answers one question across projects.

Every number comes from the canon or the ledger, and none is estimated. A widget with nothing to
show says "not measured", never zero.

| Widget | Question | Read model |
|---|---|---|
| Pipeline flow | Where is the work? | `pipeline(factory)`: projects per stage, by band |
| Decision queue | What waits on people, and for how long? | `queue(factory)`: open decision cards by kind, with age |
| Gate trend | Is the factory getting the work right? | `gate_trend(factory)`: rounds passed and failed per hour |
| Task timeline | How did each task go? | `timeline(project)`: per task, its rounds with start, end and verdict |
| Activity | What just happened, and who did it? | `activity(factory)`: recent events, person or agent |
| Evidence coverage | How much is proven rather than claimed? | `coverage(factory)`: evidence states per project |
| Staying on track | Is each project on track against its plan? | `tracking(factory)`: kernel/track.py per project |
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from typing import Any

from kernel.canon import Canon
from kernel.store import STAGES, Project

BANDS = (("Decide", (1, 2)), ("Shape", (3, 4)), ("Deliver", (5, 6)), ("Run", (7,)))
DECISION_KINDS = ("question", "approval", "validation", "deploy_gate", "escalation", "holdout_ruling", "road",
                  "trust", "incident", "change", "go_ahead")
AGENT_KINDS = {"cell_ran": "builder", "gate": "kernel", "merged": "kernel", "escalated": "kernel",
               "gnomon_run": "agent", "intake_done": "analyst", "spec_written": "analyst",
               "holdouts_authored": "holdout author", "contract_compiled": "kernel", "release_step": "kernel",
               "change_triaged": "analyst", "reflex_retry": "kernel", "surface_updated": "kernel"}
PERSON_KINDS = ("decision", "change_submitted", "pause_requested", "resumed", "plan_edited", "question_answered")


def _projects(factory):
    return [p for p in factory.projects() if not p.pid.startswith("_")]


def _when(at: str | None):
    return dt.datetime.fromisoformat(at.replace("Z", "+00:00")) if at else None


def pipeline(factory) -> dict:
    stages = {n: [] for n in STAGES}
    for p in _projects(factory):
        stages[p.meta.get("stage", 1)].append({"id": p.pid, "title": p.meta.get("title"),
                                               "maturity": p.meta.get("maturity")})
    bands = [{"band": name, "stages": [{"stage": n, "name": STAGES[n], "projects": stages[n]} for n in nums],
              "count": sum(len(stages[n]) for n in nums)} for name, nums in BANDS]
    return {"bands": bands, "total": sum(b["count"] for b in bands)}


def queue(factory) -> dict:
    now = factory.clock.now()
    items, by_kind = [], Counter()
    for p in _projects(factory):
        for c in Canon(p).cards():
            if c["kind"] not in DECISION_KINDS:
                continue
            if c["kind"] == "question" and not c.get("blocking"):
                continue
            if c["kind"] == "change" and not ((c["payload"].get("triage") or {}).get("needs_decision")):
                continue
            created = _when(c.get("created"))
            age_h = round((now - created).total_seconds() / 3600, 1) if created else None
            items.append({"project": p.pid, "card": c["id"], "kind": c["kind"], "title": c["title"],
                          "deciders": c.get("deciders", []), "age_hours": age_h})
            by_kind[c["kind"]] += 1
    items.sort(key=lambda i: -(i["age_hours"] or 0))
    ages = sorted(i["age_hours"] for i in items if i["age_hours"] is not None)
    return {"items": items, "by_kind": dict(by_kind), "count": len(items),
            "oldest_hours": ages[-1] if ages else None,
            "median_hours": ages[len(ages) // 2] if ages else None}


def gate_trend(factory, *, bucket_minutes: int = 60) -> dict:
    buckets = defaultdict(Counter)
    for p in _projects(factory):
        for rec in p.ledger().of_kind("gate"):
            t = _when(rec["event"].get("at"))
            if t is None:
                continue
            key = t.replace(minute=(t.minute // bucket_minutes) * bucket_minutes if bucket_minutes < 60 else 0,
                            second=0, microsecond=0)
            buckets[key]["passed" if rec["event"]["payload"].get("verdict") == "passed" else "not_passed"] += 1
    series = [{"at": k.isoformat().replace("+00:00", "Z"), "passed": v["passed"], "not_passed": v["not_passed"]}
              for k, v in sorted(buckets.items())]
    total = sum(s["passed"] + s["not_passed"] for s in series)
    return {"series": series, "bucket_minutes": bucket_minutes, "rounds": total,
            "pass_rate": (sum(s["passed"] for s in series) / total) if total else None}


def timeline(project) -> dict:
    tasks = defaultdict(lambda: {"rounds": []})
    open_round = {}
    for rec in project.ledger().records():
        if not isinstance(rec, dict):
            continue
        ev = rec.get("event") or {}
        pl, kind, at = ev.get("payload") or {}, ev.get("kind"), ev.get("at")
        if kind == "cell_ran":
            open_round[(pl["task"], pl["round"])] = {"round": pl["round"], "start": at, "model": pl.get("final_model"),
                                                     "escalated": pl.get("escalated")}
        elif kind == "gate":
            r = open_round.pop((pl["task"], pl["round"]), {"round": pl["round"], "start": None})
            r.update(end=at, verdict=pl.get("verdict"), signals=pl.get("signals"))
            tasks[pl["task"]]["rounds"].append(r)
        elif kind == "merged":
            tasks[pl["task"]]["merged_at"] = at
        elif kind == "escalated":
            tasks[pl["task"]]["escalated_at"] = at
    for (task, _), r in open_round.items():  # a round still in its gate, or cut off
        tasks[task]["rounds"].append(dict(r, end=None, verdict=None))
    contract = project.read("contract.json") or {"tasks": []}
    titles = {t["id"]: t["title"] for t in contract["tasks"]}
    out = [{"task": t, "title": titles.get(t, ""), **v} for t, v in sorted(tasks.items())]
    starts = [r["start"] for t in out for r in t["rounds"] if r.get("start")]
    ends = [r["end"] for t in out for r in t["rounds"] if r.get("end")]
    return {"tasks": out, "start": min(starts) if starts else None, "end": max(ends) if ends else None}


def activity(factory, *, limit: int = 40) -> list:
    events = []
    for p in _projects(factory):
        for rec in p.ledger().records()[-200:]:
            if not isinstance(rec, dict):
                continue
            ev = rec.get("event") or {}
            kind, pl = ev.get("kind"), ev.get("payload") or {}
            if kind in PERSON_KINDS:
                actor = {"type": "person", "name": pl.get("person") or pl.get("by"),
                         "persona": pl.get("persona")}
            elif kind in AGENT_KINDS:
                actor = {"type": "agent", "name": AGENT_KINDS[kind], "model": pl.get("final_model") or pl.get("model")}
            else:
                continue
            events.append({"project": p.pid, "at": ev.get("at"), "kind": kind, "actor": actor,
                           "summary": summarise(kind, pl)})
    events.sort(key=lambda e: e["at"] or "", reverse=True)
    return events[:limit]


def summarise(kind: str, pl: dict) -> str:
    if kind == "cell_ran":
        return f"{pl.get('task')} round {pl.get('round')}: cell finished ({pl.get('bucket')})"
    if kind == "gate":
        return f"{pl.get('task')} round {pl.get('round')}: gate {pl.get('verdict')}"
    if kind == "merged":
        return f"{pl.get('task')} merged"
    if kind == "escalated":
        return f"{pl.get('task')} escalated to a person"
    if kind == "decision":
        return f"{pl.get('verdict')} on {pl.get('card') or pl.get('kind')}"
    if kind == "change_submitted":
        return f"reported a change ({pl.get('card')})"
    if kind == "release_step":
        return f"release {pl.get('release')}: {pl.get('step')} {pl.get('outcome')}"
    return kind.replace("_", " ")


def coverage(factory) -> dict:
    from kernel.status import evidence

    rows, total = [], Counter()
    for p in _projects(factory):
        if not p.path("contract.json").exists():
            continue
        c = Counter(e["state"] for e in evidence(p))
        total.update(c)
        rows.append({"project": p.pid, "title": p.meta.get("title"), **{k: c.get(k, 0) for k in
                     ("verified", "held_out", "claimed", "failing", "not_measured")}})
    n = sum(total.values())
    return {"projects": rows, "total": dict(total),
            "proven_share": ((total["verified"] + total["held_out"]) / n) if n else None}


CATALOGUE_STATES = ("in_use", "pilot", "trying", "building", "shaping", "proposed")


def catalogue_state(project: Project) -> str:
    """A capability's state from what was delivered (FR-Q7): `in_use` while production runs it;
    `pilot` once a release is validated, or being validated, on staging; `trying` once a demo is
    accepted or waits for its acceptance, or a preview is done; else `building` from stage 5 and
    `shaping` before. The furthest any release got counts: a later release that failed does not
    undo a validation people gave."""
    from kernel.deliver import in_production, release_reach, releases

    if in_production(project):
        return "in_use"
    reached = {release_reach(rel) for rel in releases(project)}
    for state in ("pilot", "trying"):
        if state in reached:
            return state
    return "building" if project.meta.get("stage", 1) >= 5 else "shaping"


def catalogue(factory) -> dict:
    """Every capability the factory holds or was asked for: what it is, what it delivers, how far it
    is, and whether its capability pack is valid. Concepts waiting for validation are 'proposed'."""
    from kernel.canon import Canon
    from kernel.learn import factory_project
    from kernel.profiles import profile_of

    items = []
    for p in _projects(factory):
        prof = profile_of(p)
        spec = p.read("spec.json") or {}
        packs = p.read("packs.json", []) or []
        latest = None
        if packs:
            rel = packs[-1]["release"]
            latest = p.read(f"releases/{rel}/capability-pack.json")
        items.append({"project": p.pid, "title": p.meta.get("title"), "state": catalogue_state(p),
                      "summary": spec.get("summary") or p.meta.get("title"), "profile": prof["id"],
                      "profile_label": prof["label"], "deliverable": prof.get("deliverable", "product"),
                      "maturity": p.meta.get("maturity"), "stage": p.meta.get("stage"),
                      "adopted": p.meta.get("source_kind") == "adopted",   # an existing system kept, not built
                      "pack":{"version": latest.get("version"), "valid": latest["acceptance"]["valid"]}
                      if latest else None})
    fp = factory_project(factory, create=False)     # a read never creates the factory's canon
    for c in Canon(fp).cards(kind="concept") if fp is not None else []:
        items.append({"project": None, "title": c["payload"]["title"], "state": "proposed", "summary": c["body"][:200],
                      "profile": c["payload"]["profile"], "card": c["id"], "pack": None})
    counts = {s: sum(1 for i in items if i["state"] == s) for s in CATALOGUE_STATES}
    return {"items": items, "counts": counts}


def tracking(factory: Any) -> dict[str, Any]:
    """Each project against its approved plan (kernel/track.py), worst first: its answer, first reasons,
    checkpoints due and autopilot; and how many projects give each answer."""
    from kernel.track import STATES, summary

    worst = {"off_track": 0, "at_risk": 1, "on_track": 2, "not_measured": 3}
    rows = sorted((summary(p) for p in _projects(factory)), key=lambda r: (worst[r["state"]], r["title"] or ""))
    return {"projects": rows, "counts": {s: sum(1 for r in rows if r["state"] == s) for s in STATES},
            "autopilots": sum(1 for r in rows if r["autopilot"].get("holding"))}
