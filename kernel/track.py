"""Staying on track (D-0017): how a project is doing against its approved plan, with every figure's basis.

``track(project)`` is deterministic and reads only the project's own records. Each figure says its value,
whether it was measured and what it rests on; a figure with nothing to rest on is "not measured", never
passed and never zero:

- **baseline:** the plan a person approved (or, at a maturity that approves none, the first compiled
  contract), with when and by whom;
- **tasks:** contract tasks done and left; **gate first round:** tasks that passed their gate on the first
  round, and the trend from the earlier half of the gated tasks to the later half;
- **assumption debt:** open assumptions, and those past their due date (each one past due: at risk);
- **scope:** changes applied since the baseline; **blocking:** open cards that hold the run, with their age;
- **time** and **cost** against the project's optional budget (a due date; an amount in the price table's
  currency): not measured with no budget, no run or no price;
- **posture:** whether the run keeps the posture chosen for it, asked of ``kernel.posture.track_posture``
  when that module defines it (not measured until it does);
- **autopilot:** the run that binds the project to a sandbox, if any (kernel/autopilot.py).

The answer is ``on_track``, ``at_risk`` or ``off_track``, with each reason and the figure it rests on;
``not_measured`` when nothing is wrong but no plan is approved yet to be on track with. Off track: a person
stopped the build, a card has held the run for 7 days, the due date passed with work left, or spend is over
the budget. At risk: an open escalation, holdout ruling or incident; a card that has held the run for 3 days;
an assumption past due; first-round passes falling by 25 points or more (from 4 gated tasks); 3 or more
changes since the baseline; 80% of the time used with less of the work done, or 80% of the budget spent; a
posture not kept; a checkpoint due; an autopilot whose time is up and still holds its sandbox (``THRESHOLDS``);
an approval gone stale or a last release that stopped (**health**: what kernel/status.py's health reads beside
these, so the one answer the cockpit's project header shows is never better than the health).

**Human checkpoints** are stage boundaries a person must look at, set per project (``tracking.json``): a
checkpoint is due once the project reaches its stage (from stage 5 on, at each contract revision) and no
person has recorded a look. With ``hold`` the pipeline stops at a due checkpoint until a person looks
(``checkpoint_hold``). ``digest_notice`` is the daily digest a relay subscription can ask for.
"""

from __future__ import annotations

import datetime as dt
import importlib
from collections import Counter
from typing import Any

from kernel.canon import CARD_DECIDERS, Canon, DecisionRefused
from kernel.people import PERSONAS, is_person
from kernel.store import STAGES, Project, updating_json

FILE = "tracking.json"
STATES = ("on_track", "at_risk", "off_track", "not_measured")
THRESHOLDS = {"blocking_risk_hours": 72, "blocking_off_hours": 168, "scope_changes_risk": 3, "trend_drop": 0.25,
              "trend_min_tasks": 4, "budget_risk_share": 0.8}
# Cards that hold the run whether or not they are marked blocking.
HOLDING_KINDS = ("approval", "go_ahead", "validation", "deploy_gate", "escalation", "holdout_ruling", "road", "trust",
                 "incident")
# Open cards that say the work fell short of its plan: at risk whatever their age.
FAILING_KINDS = ("escalation", "holdout_ruling", "incident")
SETTERS = CARD_DECIDERS["approval"]                     # who sets checkpoints and the budget: the plan's owners
LOOKERS = (*SETTERS, "it", "operations", "compliance")  # who records that they looked at a checkpoint
CHECKPOINT_STAGES = tuple(s for s in STAGES if s > 1)


def _when(text: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def figure(value: Any, basis: str, *, measured: bool = True, **extra: Any) -> dict[str, Any]:
    return {"value": value if measured else None, "measured": measured, "basis": basis, **extra}


def settings(project: Project) -> dict[str, Any]:
    return dict(project.read(FILE, {}) or {})


# -- the figures -----------------------------------------------------------------------------------

def baseline(project: Project) -> dict[str, Any]:
    meta, ledger = project.meta, project.ledger()
    approved = meta.get("plan_approved")
    if approved:
        recs = ledger.of_kind("plan_approved")
        at = recs[-1]["event"].get("at") if recs else meta.get("created")
        return figure(meta.get("contract_revision"), f"the plan {approved['card']} that {approved['by']} approved "
                      f"(spec version {approved.get('spec_version')})", at=at, by=approved["by"], card=approved["card"])
    compiled = ledger.of_kind("contract_compiled")
    if compiled:
        ev = compiled[0]["event"]
        return figure(ev["payload"].get("revision"), "no plan approval at this maturity: the first compiled contract "
                      "is the baseline", at=ev.get("at"), by=None, card=None)
    return figure(None, "no plan is approved and no contract compiled yet", measured=False, at=None)


def tasks(project: Project) -> dict[str, Any]:
    contract = project.read("contract.json")
    if not contract:
        return figure(None, "no contract yet: tasks come with it", measured=False)
    state = project.read("tasks.json", {}) or {}
    ids = [t["id"] for t in contract.get("tasks") or []]
    by = Counter((state.get(t) or {}).get("status") or "pending" for t in ids)
    return figure(by["merged"], f"{by['merged']} of {len(ids)} contract tasks merged", done=by["merged"],
                  left=len(ids) - by["merged"], total=len(ids), escalated=by["escalated"], stopped=by["stopped"])


def _rate(verdicts: list[str]) -> float:
    return sum(1 for v in verdicts if v == "passed") / len(verdicts)


def gate_first_round(project: Project) -> dict[str, Any]:
    first: dict[str, str] = {}
    for rec in project.ledger().of_kind("gate"):
        pl = rec["event"]["payload"]
        if pl.get("round") == 0 and pl.get("task") not in first:
            first[pl["task"]] = pl.get("verdict") or "not measured"
    measured = [v for v in first.values() if v != "not measured"]
    if not measured:
        return figure(None, "no task has been through its gate yet", measured=False, trend=None)
    n, least = len(measured), THRESHOLDS["trend_min_tasks"]
    out = figure(round(_rate(measured), 3), f"{sum(v == 'passed' for v in measured)} of {n} gated tasks passed "
                 "their gate on the first round", of=n, trend=None, trend_basis=f"not measured: a trend needs "
                 f"{least} gated tasks, {n} so far")
    if n >= least:
        earlier, later = _rate(measured[:n // 2]), _rate(measured[n // 2:])
        drop = THRESHOLDS["trend_drop"]
        trend = "falling" if later < earlier - drop else "rising" if later > earlier + drop else "steady"
        out.update(trend=trend, earlier=round(earlier, 3), later=round(later, 3),
                   trend_basis=f"the first {n // 2} gated tasks against the last {n - n // 2}")
    return out


def assumption_debt(project: Project) -> dict[str, Any]:
    canon = Canon(project)
    open_, overdue = canon.assumptions("open"), canon.overdue()
    return figure(len(overdue), f"{len(overdue)} of {len(open_)} open assumptions are past their due date",
                  open=len(open_), past_due=[{"id": a["id"], "due": a["due"]} for a in overdue])


def scope_changes(project: Project, base: dict[str, Any]) -> dict[str, Any]:
    if not base["measured"]:
        return figure(None, "no baseline to count changes from", measured=False, items=[])
    since = _when(base.get("at"))
    items = [{"card": r["event"]["payload"].get("card"), "class": r["event"]["payload"].get("class"),
              "at": r["event"].get("at")} for r in project.ledger().of_kind("change_applied")
             if since is None or (_when(r["event"].get("at")) or since) >= since]
    return figure(len(items), f"changes applied since the baseline ({base.get('at')})", items=items)


def blocking(project: Project) -> dict[str, Any]:
    now = project.factory.clock.now()
    rows = []
    for c in Canon(project).cards():
        if c.get("blocking") or c["kind"] in HOLDING_KINDS:
            made = _when(c.get("created"))
            rows.append({"card": c["id"], "kind": c["kind"], "title": str(c.get("title", ""))[:100],
                         "age_hours": round((now - made).total_seconds() / 3600, 1) if made else None})
    rows.sort(key=lambda r: -(r["age_hours"] or 0))
    return figure(len(rows), "open cards that hold the run (blocking, or of a kind the run waits on), oldest first",
                  oldest_hours=rows[0]["age_hours"] if rows else None, cards=rows)


def time_budget(project: Project, base: dict[str, Any], done: dict[str, Any]) -> dict[str, Any]:
    due = (settings(project).get("budget") or {}).get("due")
    if not due:
        return figure(None, "no due date is set (rihmasto tracking set --due)", measured=False)
    start = _when(base.get("at")) or _when(project.meta.get("created"))
    end = dt.datetime.combine(dt.date.fromisoformat(due), dt.time(23, 59, 59), tzinfo=dt.UTC)
    now = project.factory.clock.now()
    if start is None or end <= start:
        return figure(None, f"the due date {due} is not after the baseline", measured=False, due=due)
    share = max(0.0, (now - start) / (end - start))
    done_share = done["done"] / done["total"] if done["measured"] and done.get("total") else None
    return figure(round(share, 3), f"time used from the baseline to the end of {due}", due=due,
                  days_left=round((end - now).total_seconds() / 86400, 1), done_share=done_share)


def cost_budget(project: Project) -> dict[str, Any]:
    from kernel.pricing import load_prices, spend
    from kernel.projections import cell

    budget = settings(project).get("budget") or {}
    if budget.get("amount") is None:
        return figure(None, "no cost budget is set (rihmasto tracking set --budget)", measured=False)
    amount, currency = float(budget["amount"]), budget.get("currency")
    priced = load_prices().get("currency", "USD")
    if currency and currency != priced:
        return figure(None, f"the budget is in {currency}, the price table in {priced}", measured=False)
    rows = cell(project)
    if not rows:
        return figure(None, "no Gnomon run yet, so nothing is priced", measured=False, budget=amount)
    s = spend([r["cost"] for r in rows])
    if s["cloud"] is None:
        return figure(None, f"{s['unmeasured_runs']} of {len(rows)} runs have no price (kernel/prices.json); the "
                      f"priced part is {s['cloud_measured_part']} {priced}", measured=False, budget=amount)
    return figure(s["cloud"], f"cloud spend over {len(rows)} priced runs, against {amount} {priced}",
                  budget=amount, currency=priced, share=round(s["cloud"] / amount, 3) if amount else None)


def health(project: Project) -> dict[str, Any]:
    """What the project's health (kernel/status.py) reads besides the figures above: approvals gone stale
    and a last release that stopped. Track carries them, so the one answer the cockpit's header shows is
    never better than the health."""
    from kernel.insight import alignment
    from kernel.status import _releases

    stale = [f["text"] for f in alignment(project) if f["kind"] == "stale_approval"]
    rels = _releases(project)
    failed = rels[-1].get("number") if rels and rels[-1].get("state") == "failed" else None
    return figure(len(stale) + (failed is not None), "approvals gone stale, and whether the last release stopped",
                  stale=stale, release_failed=failed)


def posture(project: Project) -> dict[str, Any]:
    """Asked of ``kernel.posture.track_posture(project)``, the hook the posture module defines: it answers
    ``{"posture": <name>, "keeps": True | False | None, "basis": <why>, "drift": [<what differs>]}``."""
    try:
        hook = getattr(importlib.import_module("kernel.posture"), "track_posture", None)
    except ImportError:
        return figure(None, "no posture module yet (kernel/posture.py)", measured=False)
    if not callable(hook):
        return figure(None, "kernel/posture.py defines no track_posture(project) yet", measured=False)
    try:
        out = hook(project)
    except Exception as exc:  # noqa: BLE001 - a hook that fails is reported as not measured, never as kept
        return figure(None, f"the posture hook failed: {type(exc).__name__}", measured=False)
    out = out if isinstance(out, dict) else {}
    keeps = out.get("keeps")
    return figure(bool(keeps) if keeps is not None else None, str(out.get("basis") or "kernel.posture"),
                  measured=keeps is not None, posture=out.get("posture"), drift=list(out.get("drift") or []))


# -- human checkpoints -----------------------------------------------------------------------------

def checkpoints(project: Project) -> dict[str, Any]:
    cfg = settings(project)
    stage, rev = int(project.meta.get("stage", 1)), project.meta.get("contract_revision")
    looks = [r["event"] for r in project.ledger().of_kind("checkpoint_looked")]
    rows = []
    for s in sorted(int(x) for x in cfg.get("checkpoints") or []):
        key = rev if s >= 5 else None
        seen = [e for e in looks if e["payload"].get("stage") == s and e["payload"].get("revision") == key]
        last = seen[-1] if seen else None
        rows.append({"stage": s, "name": STAGES.get(s), "reached": stage >= s, "due": stage >= s and last is None,
                     "looked": {"by": last["payload"].get("person"), "persona": last["payload"].get("persona"),
                                "at": last.get("at"), "note": last["payload"].get("note")} if last else None})
    return {"stages": rows, "hold": bool(cfg.get("hold")), "due": [r["stage"] for r in rows if r["due"]]}


def checkpoint_hold(project: Project) -> dict[str, Any] | None:
    """The waiting state the pipeline returns at a due checkpoint that holds the run; None to go on."""
    cp = checkpoints(project)
    if not cp["hold"] or not cp["due"]:
        return None
    s, rev = cp["due"][0], project.meta.get("contract_revision")
    if not any(r["event"]["payload"].get("stage") == s and r["event"]["payload"].get("revision") == rev
               for r in project.ledger().of_kind("checkpoint_reached")):
        project.log("checkpoint_reached", {"stage": s, "revision": rev})
    return {"state": "waiting", "stage": project.meta.get("stage"), "waiting_on": [], "checkpoint": s,
            "why": f"checkpoint: stage {s} ({STAGES.get(s)}) is reached, and a person looks before the run goes on "
                   f"(the Track view, or rihmasto tracking look {project.pid} {s})"}


def _signs(project: Project, person: str, persona: str, allowed: tuple[str, ...], what: str) -> None:
    from kernel.access import require

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: {what} is signed by a named person")
    if persona not in PERSONAS or persona not in allowed:
        raise DecisionRefused(f"a {persona} may not {what} (may: {', '.join(allowed)})")
    require(project, person, persona)


def _budget(due: str | None, amount: float | None, currency: str | None, old: dict[str, Any]) -> dict[str, Any]:
    out = dict(old)
    if due is not None:
        out["due"] = dt.date.fromisoformat(due).isoformat() if due else None
    if amount is not None:
        if amount <= 0:
            raise ValueError("a cost budget is more than zero")
        out["amount"] = float(amount)
    if currency is not None:
        out["currency"] = currency.strip().upper() or None
    return {k: v for k, v in out.items() if v is not None}


def set_tracking(project: Project, *, person: str, persona: str, stages: list[int] | None = None,
                 hold: bool | None = None, due: str | None = None, amount: float | None = None,
                 currency: str | None = None) -> dict[str, Any]:
    """A plan owner sets the project's checkpoints (and whether they hold the run) and its budget."""
    _signs(project, person, persona, SETTERS, "set checkpoints and a budget")
    if stages is not None and any(s not in CHECKPOINT_STAGES for s in stages):
        raise ValueError(f"a checkpoint is a stage boundary: one of {', '.join(map(str, CHECKPOINT_STAGES))}")
    with updating_json(project.path(FILE), {}) as cfg:
        if stages is not None:
            cfg["checkpoints"] = sorted(set(stages))
        if hold is not None:
            cfg["hold"] = bool(hold)
        cfg["budget"] = _budget(due, amount, currency, cfg.get("budget") or {})
        cfg["set_by"] = {"person": person, "persona": persona, "at": project.factory.clock.stamp()}
        out = dict(cfg)
    project.log("tracking_set", {"checkpoints": out.get("checkpoints", []), "hold": bool(out.get("hold")),
                                 "budget": out["budget"], "person": person, "persona": persona})
    return out


def look(project: Project, stage: int, *, person: str, persona: str, note: str = "") -> dict[str, Any]:
    """A person records that they looked at a checkpoint: a held run goes on at its next pass."""
    _signs(project, person, persona, LOOKERS, "record a checkpoint")
    row = next((r for r in checkpoints(project)["stages"] if r["stage"] == int(stage)), None)
    if row is None:
        raise ValueError(f"stage {stage} has no checkpoint on {project.pid}")
    if not row["reached"]:
        raise DecisionRefused(f"stage {stage} is not reached yet: there is nothing to look at")
    rev = project.meta.get("contract_revision") if int(stage) >= 5 else None
    project.log("checkpoint_looked", {"stage": int(stage), "revision": rev, "person": person, "persona": persona,
                                      "note": str(note or "").strip()[:2000]})
    return checkpoints(project)


# -- the answer ------------------------------------------------------------------------------------

def _reason(level: str, key: str, why: str) -> dict[str, str]:
    return {"level": level, "figure": key, "why": why}


def _work_reasons(f: dict[str, Any]) -> list[dict[str, str]]:
    """What the work's own figures say: a stopped build, old blocking cards, assumption debt, the gate's
    trend and scope that grew."""
    t, out = THRESHOLDS, []
    if f["tasks"].get("stopped") or f["tasks"].get("halted"):
        out.append(_reason("off_track", "tasks", "a person stopped the build"))
    failing = [c for c in f["blocking"]["cards"] if c["kind"] in FAILING_KINDS]
    if failing:
        out.append(_reason("at_risk", "blocking", f"{failing[0]['card']}: {failing[0]['title']} (it waits for a "
                                                  "person)"))
    age = f["blocking"].get("oldest_hours")
    if age is not None and age >= t["blocking_risk_hours"]:
        card = f["blocking"]["cards"][0]
        out.append(_reason("off_track" if age >= t["blocking_off_hours"] else "at_risk", "blocking",
                           f"{card['card']} ({card['kind']}) has waited {round(age / 24, 1)} days for a person"))
    if f["assumption_debt"]["value"]:
        out.append(_reason("at_risk", "assumption_debt",
                           f"{f['assumption_debt']['value']} assumptions are past their due date"))
    g = f["gate_first_round"]
    if g.get("trend") == "falling":
        out.append(_reason("at_risk", "gate_first_round",
                           f"first-round passes fell from {g['earlier']:.0%} to {g['later']:.0%}"))
    if f["scope"]["measured"] and f["scope"]["value"] >= t["scope_changes_risk"]:
        out.append(_reason("at_risk", "scope", f"{f['scope']['value']} changes were applied since the baseline"))
    out += [_reason("at_risk", "health", text) for text in f["health"]["stale"]]
    if f["health"]["release_failed"] is not None:
        out.append(_reason("at_risk", "health", f"release {f['health']['release_failed']} stopped"))
    return out


def _watch_reasons(f: dict[str, Any], cps: dict[str, Any], held: dict[str, Any] | None) -> list[dict[str, str]]:
    """What the watch says: the budget, the posture, checkpoints due and an autopilot whose time is up."""
    out = _budget_reasons(f["time"], f["cost"])
    if f["posture"]["value"] is False:
        out.append(_reason("at_risk", "posture", f"the run does not keep its posture: {f['posture']['basis']}"))
    out += [_reason("at_risk", "checkpoints", f"checkpoint {s} ({STAGES.get(s)}) is due: a person looks")
            for s in cps["due"]]
    if held is not None and held.get("state") == "expired":
        out.append(_reason("at_risk", "autopilot",
                           f"{held['id']}'s time is up and it still holds the sandbox: a person stops it"))
    return out


def _budget_reasons(time_: dict[str, Any], cost: dict[str, Any]) -> list[dict[str, str]]:
    out, share = [], THRESHOLDS["budget_risk_share"]
    if time_["measured"]:
        used, done = time_["value"], time_.get("done_share")
        if used >= 1 and (done is None or done < 1):
            out.append(_reason("off_track", "time", f"the due date {time_['due']} has passed with work left"))
        elif used >= share and done is not None and done < used:
            out.append(_reason("at_risk", "time", f"{used:.0%} of the time is used and {done:.0%} of the tasks "
                               "are done"))
    if cost["measured"] and cost.get("share") is not None:
        if cost["share"] > 1:
            out.append(_reason("off_track", "cost", f"spend is {cost['share']:.0%} of the budget"))
        elif cost["share"] >= share:
            out.append(_reason("at_risk", "cost", f"spend is {cost['share']:.0%} of the budget"))
    return out


def track(project: Project) -> dict[str, Any]:
    """How the project is doing against its approved plan: the answer, its reasons and every figure."""
    from kernel.autopilot import status as autopilot_status

    base = baseline(project)
    done = tasks(project) | {"halted": bool(project.meta.get("halted"))}
    figures = {"baseline": base, "tasks": done, "gate_first_round": gate_first_round(project),
               "assumption_debt": assumption_debt(project), "scope": scope_changes(project, base),
               "blocking": blocking(project), "time": time_budget(project, base, done), "cost": cost_budget(project),
               "posture": posture(project), "health": health(project)}
    cps = checkpoints(project)
    ap = autopilot_status(project)
    run = ap["run"] if ap["holding"] else None
    reasons = _work_reasons(figures) + _watch_reasons(figures, cps, run)
    levels = {r["level"] for r in reasons}
    state = "off_track" if "off_track" in levels else "at_risk" if levels else \
        "on_track" if base["measured"] else "not_measured"
    return {"project": project.pid, "title": project.meta.get("title"), "stage": project.meta.get("stage"),
            "state": state, "reasons": reasons, "figures": figures, "checkpoints": cps, "thresholds": THRESHOLDS,
            "autopilot": {"holding": ap["holding"], "sandbox": ap["sandbox"],
                          **({k: run[k] for k in ("id", "state", "until", "delegation", "person", "persona")}
                             | {"decided": len(run["decided"]), "declined": len(run["declined"])} if run else {})},
            "basis": "not measured: no approved plan to be on track with yet" if state == "not_measured" else
            "the project's own records against its baseline; each reason names the figure it rests on",
            "at": project.factory.clock.stamp()}


def summary(project: Project) -> dict[str, Any]:
    """One project's line for a list: its answer, its first reasons and what waits on a person."""
    t = track(project)
    return {k: t[k] for k in ("project", "title", "stage", "state", "basis")} | {
        "reasons": t["reasons"][:3], "due": t["checkpoints"]["due"], "autopilot": t["autopilot"],
        "tasks": {k: t["figures"]["tasks"].get(k) for k in ("done", "left", "total")}}


def digest_notice(factory: Any, *, cockpit: str, sub_id: str, day: str,
                  subscription: dict[str, Any] | None = None) -> dict[str, Any]:
    """The daily Track digest (kernel/notices.py renders it, kernel/relay.py sends it): one line per
    project and one link, to the cockpit's Home. Titles are defanged; nothing in it decides anything.
    A project an autopilot binds to its sandbox is left out for a ``subscription`` that is not a sandbox
    receiver (``kernel.autopilot.outbound_hold``): only how many were left out is said, never what."""
    from kernel.autopilot import outbound_hold
    from kernel.notices import NOT_HERE, defang

    shown, held = [], []
    for p in factory.projects():
        if p.pid.startswith("_"):
            continue
        (held if subscription is not None and outbound_hold(p, subscription) else shown).append(p)
    rows = [summary(p) for p in shown]
    counts = Counter(r["state"] for r in rows)
    head = "Rihmasto daily track: " + (", ".join(f"{counts[s]} {s.replace('_', ' ')}" for s in STATES if counts[s])
                                        or "no project listed")
    lines = [f"- {defang(r['title'] or r['project'])}: {r['state'].replace('_', ' ')}"
             + (f" ({defang(r['reasons'][0]['why'])})" if r["reasons"] else "") for r in rows[:30]]
    if held:
        lines.append(f"- {len(held)} more {'project is' if len(held) == 1 else 'projects are'} bound to an "
                     "autopilot's sandbox and not listed here until a person stops the run")
    return {"digest": True, "event_id": f"digest-{sub_id}-{day}", "card_kind": None, "headline": head,
            "detail": "\n".join(lines + [NOT_HERE]), "link": cockpit.rstrip("/") + "/#/home", "day": day,
            "counts": dict(counts), "held": [p.pid for p in held]}
