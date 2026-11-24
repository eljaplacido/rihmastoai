"""Running automations (FR-AUT1): one tick at a time, each firing taken once, each run recorded.

A **tick** looks at every active automation once:

1. **collect**: a schedule that is due fires once (a missed slot fires once, never once per slot missed); the
   ledgers of the scoped projects are read from where the automation stopped (each ledger's hash chain is
   checked first, so nothing after a break fires), and each record of a kind it reacts to fires; an inbound
   source's rings are ``hook_received`` records; a repository is polled at most every five minutes and new
   commits on its branch fire. Firings wait in the automation's queue, and the cursors move past them.
2. **take**: for each firing in order, the guard is read (a guard that does not hold drops the firing and
   records nothing), then the limits: quiet hours hold the whole queue until they end, and a firing over the
   runs per hour waits for the next tick. A firing is taken off the queue and saved **before** its action
   runs, so a crash never runs it twice: at most once, never twice.
3. **act**: the action runs with the owner's rights (kernel/automations_actions.py) and ``automation_ran``
   is recorded with its outcome, in the factory's ledger and in the project's. Failures in a row (a failed
   or refused action) open the circuit breaker, which pauses the automation and says why.

A dry run (the automation's ``dry_run`` limit) records what it would have done, as ``would``; ``dry_run``
here answers what the next tick would do and records nothing. Only one tick runs at a time: a second one,
in the cockpit's scheduler or `rihmasto automations tick` from cron, answers busy and changes nothing.
"""

from __future__ import annotations

import copy
import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kernel import automations as au
from kernel.automations_events import records_of, seconds_of
from kernel.events import heads
from kernel.filelock import LockHeld, locked
from kernel.store import Factory, Project, read_json, updating_json

STATE = "state.json"
REQUESTS = "requests.json"
MAX_QUEUE = 200
REPO_POLL = 300            # seconds between two looks at a repository
_ID_KEYS = ("id", "card", "kind", "verdict", "state", "release", "task", "signal", "source", "ref", "branch",
            "environment", "head", "upstream", "new_commits", "round", "stage")
FAILED = ("failed", "refused")


@dataclass
class Tools:
    """What a tick may use: a model when an action asks one (made only then), the environment for a relay's
    secrets, the relay's transports, the gate's verifier runner (tests), and a time limit for a suite."""

    model: Callable[[], Any] | None = None
    environ: Mapping[str, str] | None = None
    post: Any = None
    send: Any = None
    verifier_runner: Any = None
    suite_timeout: int = 900
    cache: dict[str, Any] = field(default_factory=dict)


def _path(factory: Factory, name: str) -> Path:
    return factory.home / "automations" / name


def _when(stamp: str) -> dt.datetime:
    return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _stamp(at: dt.datetime) -> str:
    return at.replace(microsecond=0).isoformat().replace("+00:00", "Z")


# -- schedules and quiet hours --------------------------------------------------------------------------

def next_slot(trigger: dict[str, Any], after: dt.datetime) -> dt.datetime:
    """The first time a schedule fires after ``after`` (UTC)."""
    if trigger.get("every"):
        return after + dt.timedelta(minutes=au.minutes_of(trigger["every"]))
    text = trigger.get("daily") or trigger["weekly"][4:]
    at = after.replace(hour=int(text[:2]), minute=int(text[3:5]), second=0, microsecond=0)
    if trigger.get("daily"):
        return at if at > after else at + dt.timedelta(days=1)
    at += dt.timedelta(days=(au.DAYS.index(trigger["weekly"][:3]) - after.weekday()) % 7)
    return at if at > after else at + dt.timedelta(days=7)


def quiet_now(limits: dict[str, Any], now: dt.datetime) -> bool:
    if not limits.get("quiet"):
        return False
    start, end = (int(t[:2]) * 60 + int(t[3:5]) for t in limits["quiet"].split("-"))
    m = now.hour * 60 + now.minute
    return start <= m < end if start <= end else (m >= start or m < end)


# -- the state each automation keeps ---------------------------------------------------------------------

def armed(factory: Factory, a: dict[str, Any], *, keep: bool = False) -> None:
    """Where a new or changed automation starts: its next slot, every ledger's head (it reacts to what happens
    next, never to the history) and an empty queue. ``keep``: its trigger and scope did not change, so it goes
    on from where it was, as its new version."""
    if keep:
        with updating_json(_path(factory, STATE), {}) as st:
            if a["id"] in st:
                st[a["id"]]["version"] = a["version"]
                return
    now = factory.clock.now()
    fresh = {"version": a["version"], "queue": [], "runs": [], "failures": 0, "heads": {},
             "cursors": heads(factory) if a["trigger"]["kind"] in ("event", "hook") else {},
             "next_at": _stamp(next_slot(a["trigger"], now)) if a["trigger"]["kind"] == "schedule" else None}
    with updating_json(_path(factory, STATE), {}) as st:
        st[a["id"]] = fresh


def reset_failures(factory: Factory, aid: str) -> None:
    with updating_json(_path(factory, STATE), {}) as st:
        if aid in st:
            st[aid]["failures"] = 0


def state_of(factory: Factory, aid: str) -> dict[str, Any]:
    return dict((read_json(_path(factory, STATE), {}) or {}).get(aid) or {})


def _save(factory: Factory, aid: str, s: dict[str, Any]) -> None:
    """Keep a tick's state of one automation, unless the automation was changed meanwhile (it was armed
    again: what the tick saw belongs to the old version)."""
    with updating_json(_path(factory, STATE), {}) as st:
        if (st.get(aid) or {}).get("version") == s.get("version"):
            st[aid] = s


def request_run(factory: Factory, aid: str, *, person: str, persona: str, project: str | None = None) -> dict:
    """A person asks for a run now: the next tick takes it (the cockpit's scheduler wakes for it). It acts with
    the owner's rights; the trigger and the guard are passed over, the runs per hour still hold."""
    a = au.get(factory, aid)
    if a["state"] != "active":
        raise au.AutomationRefused(f"{aid} is {a['state']}: resume it first")
    au.check_persona(a["action"]["kind"], person, persona)
    if project is not None and not au.in_scope(factory.project(project), a["scope"]):
        raise ValueError(f"{project} is not in {aid}'s scope")
    req = {"person": person, "persona": persona, "project": project, "at": factory.clock.stamp()}
    with updating_json(_path(factory, REQUESTS), {}) as reqs:
        reqs.setdefault(aid, []).append(req)
    au._log(factory, "automation_run_requested", {"id": aid, "person": person, "persona": persona,
                                                  "project": project})
    return req


def _requests(factory: Factory, aid: str, take: bool) -> list[dict[str, Any]]:
    if not take:
        return list((read_json(_path(factory, REQUESTS), {}) or {}).get(aid) or [])
    with updating_json(_path(factory, REQUESTS), {}) as reqs:
        return list(reqs.pop(aid, None) or [])


# -- collecting firings ----------------------------------------------------------------------------------

def event_of(project: Project, record: dict[str, Any]) -> dict[str, Any]:
    """A record as an automation sees it: its kind, place and id-like values; never its free text."""
    from kernel.events import _ID

    payload = (record.get("event") or {}).get("payload") or {}
    out: dict[str, Any] = {"kind": record["event"].get("kind"), "seq": record["seq"], "at": record["event"].get("at"),
                           "project": None if project.pid.startswith("_") else project.pid}
    for key in _ID_KEYS:
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            continue
        if isinstance(value, int) or _ID.match(value):
            out.setdefault(key, value)
    return out


def matches(trigger: dict[str, Any], ev: dict[str, Any]) -> bool:
    kind = str(ev.get("kind") or "")
    if kind.startswith("automation_"):
        return False                      # never its own records, nor another automation's
    if trigger["kind"] == "hook":
        return kind == "hook_received" and ev.get("source") == trigger["source"]
    return any(kind == base and (verdict is None or ev.get("verdict") == verdict)
               for wanted in trigger.get("types", []) for base, verdict in records_of(wanted))


def _records(project: Project, cache: dict[str, Any]) -> list[dict[str, Any]]:
    from kernel.events import tail

    key = "ledger:" + project.pid
    if key not in cache:
        cache[key] = tail(project)[0]
    return list(cache[key])


def _ledgers(factory: Factory, a: dict[str, Any]) -> list[Project]:
    from kernel.learn import factory_project

    scope, kind = a["scope"], a["trigger"]["kind"]
    if scope["kind"] == "factory":
        home = factory_project(factory, create=False)
        if kind == "hook":                 # a ring is in the factory's ledger, and again in each bound project's
            return [home] if home else []
        return ([home] if home else []) + au.projects_in(factory, scope)
    return au.projects_in(factory, scope)


def _own(s: dict[str, Any], pid: str, seq: int) -> bool:
    """Whether a record was written by this automation's own run: it never reacts to what it did itself."""
    return any(lo <= seq <= hi for lo, hi in (s.get("own") or {}).get(pid, []))


def _tail(factory: Factory, a: dict[str, Any], s: dict[str, Any], cache: dict[str, Any]) -> list[dict[str, Any]]:
    cursors = s.setdefault("cursors", {})
    out = []
    for project in _ledgers(factory, a):
        for record in _records(project, cache)[int(cursors.get(project.pid, -1)) + 1:]:
            ev = event_of(project, record)
            if matches(a["trigger"], ev) and not _own(s, project.pid, record["seq"]):
                out.append({"trigger": a["trigger"]["kind"], "project": ev["project"], "event": ev})
            cursors[project.pid] = record["seq"]
    return out


def _lengths(factory: Factory, a: dict[str, Any]) -> dict[str, int]:
    if a["trigger"]["kind"] not in ("event", "hook"):
        return {}
    return {p.pid: len(p.ledger().records()) for p in _ledgers(factory, a)}


def _mark_own(factory: Factory, a: dict[str, Any], s: dict[str, Any], before: dict[str, int]) -> None:
    own = s.setdefault("own", {})
    for pid, n in _lengths(factory, a).items():
        if n > before.get(pid, n):
            own[pid] = (own.get(pid, []) + [[before[pid], n - 1]])[-20:]


def _repo(factory: Factory, a: dict[str, Any], s: dict[str, Any], now: dt.datetime, fetch: bool) -> list[dict]:
    from kernel import automations_actions as acts

    if s.get("polled_at") and (now - _when(s["polled_at"])).total_seconds() < REPO_POLL:
        return []
    s["polled_at"] = _stamp(now)
    heads, out = s.setdefault("heads", {}), []
    for project in au.projects_in(factory, a["scope"]):
        try:
            branch, head = acts.repo_head(project, a["trigger"].get("branch"), fetch=fetch)
        except (ValueError, LookupError, OSError):
            continue                       # not a repository, or the branch is not there: nothing to poll
        before = heads.get(project.pid)
        heads[project.pid] = head
        if before is not None and before != head:
            ev = {"kind": "repo_changed", "project": project.pid, "branch": branch, "head": head, "before": before,
                  "at": _stamp(now)}
            out.append({"trigger": "repo", "project": project.pid, "event": ev})
    return out


def scope_firings(factory: Factory, a: dict[str, Any], trigger: str, event: dict | None = None) -> list[dict]:
    """One firing per project in scope for an action on a project; one for the factory otherwise."""
    if au.ACTIONS[a["action"]["kind"]]["per_project"] or a["scope"].get("projects"):
        return [{"trigger": trigger, "project": p.pid, "event": event} for p in au.projects_in(factory, a["scope"])]
    return [{"trigger": trigger, "project": None, "event": event}]


def collect(factory: Factory, a: dict[str, Any], s: dict[str, Any], now: dt.datetime, *, cache: dict[str, Any],
            take: bool = True) -> list[dict[str, Any]]:
    """The firings since the last tick; moves the cursors (on ``s``) past them."""
    out: list[dict[str, Any]] = []
    for req in _requests(factory, a["id"], take):
        firings = scope_firings(factory, a, "run_now")
        out += [dict(f, requested_by=req["person"]) for f in firings
                if req.get("project") in (None, f["project"])]
    kind = a["trigger"]["kind"]
    if kind == "schedule" and s.get("next_at") and now >= _when(s["next_at"]):
        s["next_at"] = _stamp(next_slot(a["trigger"], now))
        out += scope_firings(factory, a, "schedule")
    elif kind in ("event", "hook"):
        out += _tail(factory, a, s, cache)
    elif kind == "repo":
        out += _repo(factory, a, s, now, fetch=take)
    return out + _probes_due(a, s, now)


def _probes_due(a: dict[str, Any], s: dict[str, Any], now: dt.datetime) -> list[dict[str, Any]]:
    """The probe check a probe action enabled on a project (its ``every``): a firing whenever the next is due."""
    every = seconds_of(str(a["action"].get("every") or ""))
    due = [pid for pid, at in sorted((s.get("probing") or {}).items()) if every and now >= _when(at)]
    for pid in due:
        s["probing"][pid] = _stamp(now + dt.timedelta(seconds=every))
    return [{"trigger": "probe_check", "project": pid, "event": None} for pid in due]


def _enable_probing(factory: Factory, a: dict[str, Any], s: dict[str, Any], f: dict[str, Any],
                    result: dict[str, Any]) -> None:
    """A probe action with ``every`` that probed production keeps probing it from then on: the probe check is
    enabled on the project, once, and recorded there (``probe_check_enabled``)."""
    every, pid = str(a["action"].get("every") or ""), f.get("project")
    production = (result.get("refs") or {}).get("environment") == "production"
    if a["action"]["kind"] != "probe" or not every or not pid or result["outcome"] in FAILED or not production \
            or pid in s.get("probing", {}):
        return
    s.setdefault("probing", {})[pid] = _stamp(factory.clock.now() + dt.timedelta(seconds=seconds_of(every)))
    factory.project(pid).log("probe_check_enabled", {"automation": a["id"], "every": every,
                                                     "environment": "production"})


# -- the guard and the limits ------------------------------------------------------------------------------

def guard_holds(factory: Factory, g: dict[str, Any] | None, f: dict[str, Any], now: dt.datetime) -> tuple[bool, str]:
    """Whether a firing's guard holds, and why not. A run a person asked for passes over it."""
    if g is None or f.get("requested_by"):
        return True, ""
    ev = f.get("event") or {}
    if g["kind"] == "branch":
        return ev.get("branch") == g["is"], f"the branch is {ev.get('branch') or 'not named'}, not {g['is']}"
    if g["kind"] == "field":
        got = ev.get(g["key"])
        return str(got) == g["equals"], f"{g['key']} is {got!r}, not {g['equals']!r}"
    if not f.get("project"):
        return False, "the guard reads a project, and this firing names none"
    return _project_guard(factory.project(f["project"]), g, now)


def _project_guard(project: Project, g: dict[str, Any], now: dt.datetime) -> tuple[bool, str]:
    """A guard over the project's state: its open cards, or how often an event was recorded lately."""
    if g["kind"] == "open_cards":
        from kernel.canon import Canon

        n = len([c for c in Canon(project).cards() if not g.get("card_kind") or c["kind"] == g["card_kind"]])
        return n >= g["at_least"], f"{n} open cards, fewer than {g['at_least']}"
    since = _stamp(now - dt.timedelta(hours=g["within_hours"]))
    n = len([r for r in project.ledger().records() if isinstance(r, dict) and str(r["event"].get("at") or "") >= since
             and matches({"kind": "event", "types": [g["event"]]}, event_of(project, r))])
    return n >= g["at_least"], f"{g['event']} {n} times in {g['within_hours']} h, fewer than {g['at_least']}"


def over_limit(a: dict[str, Any], s: dict[str, Any], now: float) -> bool:
    s["runs"] = [t for t in s.get("runs", []) if now - float(t) < 3600]
    return len(s["runs"]) >= int(a["limits"]["max_per_hour"])


# -- one automation in one tick ------------------------------------------------------------------------------

def _record(factory: Factory, a: dict[str, Any], f: dict[str, Any], result: dict[str, Any]) -> None:
    ev = f.get("event") or {}
    payload = {"id": a["id"], "trigger": f["trigger"], "project": f.get("project"), "event": ev.get("kind"),
               "event_seq": ev.get("seq"), "action": a["action"]["kind"], "outcome": result["outcome"],
               "verdict": result.get("verdict"), "detail": str(result.get("detail") or "")[:300],
               "refs": result.get("refs") or {}, "person": a["owner"]["person"], "persona": a["owner"]["persona"],
               "requested_by": f.get("requested_by"), "dry_run": result["outcome"] == "would"}
    au._log(factory, "automation_ran", payload)
    if f.get("project"):
        factory.project(f["project"]).log("automation_ran", payload)


def _after(factory: Factory, a: dict[str, Any], s: dict[str, Any], f: dict[str, Any], result: dict[str, Any],
           tools: Tools) -> bool:
    """Record a run, notify when asked, and count failures in a row; True when the breaker paused it."""
    from kernel import automations_actions as acts

    _record(factory, a, f, result)
    _enable_probing(factory, a, s, f, result)
    s["last"] = {"at": factory.clock.stamp(), "outcome": result["outcome"], "project": f.get("project"),
                 "detail": str(result.get("detail") or "")[:300]}
    failed = result["outcome"] in FAILED or result.get("verdict") == "failed"
    notify = a.get("notify")
    if notify and result["outcome"] != "would" and (notify["when"] == "always" or failed):
        acts.notify_result(factory, a, f, result, tools)
    if result["outcome"] not in FAILED:
        s["failures"] = 0
        return False
    s["failures"] = int(s.get("failures", 0)) + 1
    if s["failures"] < int(a["limits"]["breaker"]):
        return False
    runs = "1 failed run" if s["failures"] == 1 else f"{s['failures']} failed runs"
    why = (f"the circuit breaker: {runs} in a row; the last: "
           f"{str(result.get('detail') or result['outcome'])[:200]}")
    au.breaker_pause(factory, a["id"], why)
    return True


def _act(factory: Factory, a: dict[str, Any], s: dict[str, Any], f: dict[str, Any], tools: Tools) -> dict:
    from kernel import automations_actions as acts

    if a["limits"]["dry_run"]:
        return acts.plan(factory, a, f)
    before = _lengths(factory, a)
    result = acts.run(factory, a, f, tools)
    _mark_own(factory, a, s, before)
    return result


def _one(factory: Factory, a: dict[str, Any], tools: Tools, now: dt.datetime) -> dict[str, Any]:
    s = state_of(factory, a["id"])
    if s.get("version") != a["version"]:
        return {"id": a["id"], "state": "not armed"}
    queue = s.setdefault("queue", [])
    queue += collect(factory, a, s, now, cache=tools.cache)
    dropped = max(0, len(queue) - MAX_QUEUE)
    s["queue"], s["dropped"] = queue[dropped:], int(s.get("dropped", 0)) + dropped
    out: dict[str, Any] = {"id": a["id"], "ran": [], "skipped": 0}
    paused = False
    while s["queue"] and not paused:
        f = s["queue"][0]
        if quiet_now(a["limits"], now) and not f.get("requested_by"):
            out["state"] = "quiet hours"
            break
        ok, why = guard_holds(factory, a["guard"], f, now)
        if not ok:
            s["queue"].pop(0)
            out["skipped"] += 1
            s["last_skip"] = {"at": factory.clock.stamp(), "why": why}
            continue
        if over_limit(a, s, now.timestamp()):
            out["state"] = "at its runs per hour"
            break
        s["queue"].pop(0)
        s["runs"].append(now.timestamp())
        _save(factory, a["id"], s)                 # taken before it runs: never twice
        result = _act(factory, a, s, f, tools)
        paused = _after(factory, a, s, f, result, tools)
        out["ran"].append({"project": f.get("project"), "outcome": result["outcome"], "detail": result.get("detail")})
    _save(factory, a["id"], s)
    out.setdefault("state", "paused by the circuit breaker" if paused else "up to date")
    return out


def tick(factory: Factory, tools: Tools | None = None, *, only: str | None = None) -> dict[str, Any]:
    """One round over every active automation (or ``only`` one). A round already running answers busy."""
    tools = tools or Tools()
    autos = [a for a in au.automations(factory) if a["state"] == "active" and only in (None, a["id"])]
    if not autos:
        return {"automations": 0, "results": []}
    try:
        with locked(_path(factory, "tick.lock"), blocking=False):
            now = factory.clock.now()
            tools.cache.clear()
            results = [_one(factory, a, tools, now) for a in autos]
    except LockHeld:
        return {"automations": len(autos), "busy": "another tick is running: what was asked runs on the next one"}
    return {"automations": len(autos), "results": results}


def dry_run(factory: Factory, aid: str) -> dict[str, Any]:
    """What the next tick would do for one automation, from its state now. Records nothing, changes nothing."""
    from kernel import automations_actions as acts

    a = au.get(factory, aid)
    s = copy.deepcopy(state_of(factory, aid))
    now = factory.clock.now()
    firings = list(s.get("queue") or []) + collect(factory, a, s, now, cache={}, take=False)
    rows = []
    for f in firings:
        ok, why = guard_holds(factory, a["guard"], f, now)
        rows.append({"project": f.get("project"), "trigger": f["trigger"], "event": (f.get("event") or {}).get("kind"),
                     "guard": "holds" if ok else f"does not hold: {why}",
                     "would": acts.plan(factory, a, f)["detail"] if ok else "nothing"})
    return {"id": aid, "state": a["state"], "now": _stamp(now), "next_at": s.get("next_at"),
            "quiet_now": quiet_now(a["limits"], now), "firings": rows}


def history(factory: Factory, aid: str | None = None, *, project: str | None = None,
            limit: int = 50) -> list[dict[str, Any]]:
    """Runs and changes of automations, newest last: from the factory's ledger (a project's own, when named)."""
    from kernel.learn import factory_project

    where = factory.project(project) if project else factory_project(factory, create=False)
    if where is None:
        return []
    kinds = ("automation_set", "automation_ran", "automation_paused", "automation_resumed", "automation_removed",
             "automation_run_requested")
    rows = [dict(r["event"]["payload"], kind=r["event"]["kind"], at=r["event"].get("at"))
            for r in where.ledger().of_kind(*kinds)]
    rows = [r for r in rows if aid is None or r.get("id") == aid]
    return rows[-limit:] if limit > 0 else rows
