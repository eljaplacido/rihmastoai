"""Governance: who decides, how fast, what waits, what the factory may do alone, and whether the record holds.

- **Decisions** are the canon's decision record (``canon/decisions.json``): each one by a named person and
  persona, by a person's delegation (``delegation``: DL-n, kernel/delegation.py), or by an automation a later
  build records (``automation``). Time to decide runs from the card's creation to its decision.
- **Waiting** are the open cards a person decides (kernel/dashboard.py's queue rules), with their age.
- **Autonomy holds** are the ledger's ``go_ahead_asked``: a step above the posture's autonomy waited for a
  person. **Autonomy cap hits** are the ledger's ``autonomy_capped``: a step above the cap was refused
  (kernel/autonomy.py). **Delegations** are the project's ``delegations.json``, in force now.
- **Integrity** is each project's ledger chain verified (kernel/ledger.py), against the head the cockpit
  keeps outside the project's folder when it keeps one.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from kernel.insights.base import (
    PREVIOUS_WORDS,
    Scope,
    answer,
    chart,
    delta,
    first,
    gap,
    hours,
    median,
    series_rows,
    share,
    tile,
    unit_of,
    when,
)
from kernel.insights.lines import change, count, top

HOW_DECIDE = "decide a card in the Inbox (or rihmasto decide <pid> <card> <verdict> --person ... --persona ...)"
NO_DECISION = "no decision was recorded in the window"
AGE_BINS = (("under an hour", 1), ("1 to 4 hours", 4), ("4 to 24 hours", 24), ("1 to 3 days", 72),
            ("over 3 days", None))
ACTORS = {"person": "By a person", "delegation": "By delegation", "automation": "By automation"}
Row = dict[str, Any]


def _actor(d: Row) -> str:
    return "automation" if d.get("automation") else "delegation" if d.get("delegation") else "person"


def _decisions(scope: Scope, previous: bool = False) -> list[Row]:
    from kernel.canon import Canon

    test = scope.before if previous else scope.inside
    out = []
    for p in scope.projects:
        canon = Canon(p)
        created = {c["id"]: when(c.get("created")) for c in canon.cards(state=None)}
        for d in canon.decisions():
            t = when(d.get("at"))
            if test(t):
                out.append({"project": p, "id": d.get("id"), "at": t, "card": d.get("card"), "kind": d.get("kind"),
                            "persona": d.get("persona"), "actor": _actor(d),
                            "hours": hours(created.get(d.get("card")), t)})
    return out


def _counts(c: Row) -> bool:
    if c["kind"] == "question":
        return bool(c.get("blocking"))
    if c["kind"] == "change":
        return bool(((c.get("payload") or {}).get("triage") or {}).get("needs_decision"))
    return True


def _waiting(scope: Scope) -> list[Row]:
    from kernel.canon import Canon
    from kernel.dashboard import DECISION_KINDS

    out = [{"project": p, "card": c["id"], "kind": c["kind"], "title": c["title"],
            "age": hours(when(c.get("created")), scope.now)}
           for p in scope.projects for c in Canon(p).cards() if c["kind"] in DECISION_KINDS and _counts(c)]
    return sorted(out, key=lambda c: -(c["age"] or 0))


def _integrity(scope: Scope) -> tuple[int, list[str]]:
    from kernel.evidence_pack import _kept_head
    from kernel.ledger import verify

    intact, broken = 0, []
    for p in scope.projects:
        recs = p.ledger().records()
        if not recs:
            continue
        if verify(recs, head=_kept_head(p) or None).intact:
            intact += 1
        else:
            broken.append(scope.title(p))
    return intact, broken


def _context(scope: Scope) -> Row:
    from kernel.delegation import delegations

    ds = _decisions(scope)
    return {"scope": scope, "ds": ds, "before": _decisions(scope, previous=True), "waiting": _waiting(scope),
            "actors": Counter(d["actor"] for d in ds), "period": PREVIOUS_WORDS.get(scope.window, ""),
            "active": [d for p in scope.projects for d in delegations(p) if d["state"] == "active"],
            "holds": sum(1 for _ in scope.events("go_ahead_asked")),
            "capped": [(p, pl) for p, _, pl, _ in scope.events("autonomy_capped")]}


def _t_decisions(c: Row) -> Row:
    n, b = len(c["ds"]), len(c["before"])
    plain = f"{count(n, 'decision')}, {c['actors'].get('person', 0)} by a person in their own name."
    return tile("decisions", "Decisions", n or None, basis="canon decisions.json, in the window",
                delta=delta(n, b or None, c["period"]),
                line=change("Decisions", n, b or None, c["scope"].window) or plain, why=NO_DECISION, how=HOW_DECIDE)


def _t_delegated(c: Row) -> Row:
    n = len(c["ds"])
    by = c["actors"].get("delegation", 0) + c["actors"].get("automation", 0)
    return tile("delegated_share", "Decided by delegation", share(by, n), unit="%",
                basis="decisions that carry a delegation (DL-n) or an automation",
                line=f"{by} of {n} decisions were taken by a person's delegation or an automation.",
                why=NO_DECISION, how=HOW_DECIDE)


def _times(ds: list[Row]) -> list[float]:
    return [d["hours"] for d in ds if d["hours"] is not None]


def _t_time(c: Row) -> Row:
    mid, bmid = median(_times(c["ds"])), median(_times(c["before"]))
    plain = f"Half the cards were decided within {mid} hours."
    return tile("time_to_decide", "Time to decide", mid, unit="h", basis="median hours from a card's creation to its "
                "decision", delta=delta(mid, bmid, c["period"]),
                line=change("The median time to decide", mid, bmid, c["scope"].window, "h") or plain,
                why="no card was decided in the window", how=HOW_DECIDE)


def _t_waiting(c: Row) -> Row:
    w = c["waiting"]
    oldest = first(w, "age")
    verb = "waits" if len(w) == 1 else "wait"
    line = (f"{count(len(w), 'card')} {verb} on a person; the oldest, {first(w, 'card')}, has waited {oldest} hours."
            if w else "Nothing waits on a person.")
    href = f"#/p/{w[0]['project'].pid}/inbox/{w[0]['card']}" if w else None
    status = "good" if not w else "warning" if (oldest or 0) < 72 else "critical"
    return tile("waiting", "Cards waiting", len(w), sub=f"oldest {oldest} h" if oldest is not None else None,
                basis="open cards a person decides (the Decisions waiting rules)", status=status, href=href, line=line)


def _t_holds(c: Row) -> Row:
    n = c["holds"]
    line = f"{count(n, 'step')} waited for a person's go-ahead." if n else "No step waited for a go-ahead."
    return tile("autonomy_holds", "Autonomy holds", n if n or c["ds"] else None, line=line,
                basis="ledger go_ahead_asked: a step above the posture's autonomy waited for a person",
                why="no decision or hold was recorded in the window",
                how="choose a posture (rihmasto posture set): a step above its autonomy waits for a go-ahead card")


def _t_capped(c: Row) -> Row:
    hits = c["capped"]
    line = (f"The autonomy cap stopped {count(len(hits), 'step')}; the latest was {hits[-1][1].get('what', 'a step')} "
            f"on {c['scope'].title(hits[-1][0])}." if hits else "The autonomy cap stopped no step.")
    return tile("autonomy_capped", "Autonomy cap hits", len(hits) if hits or c["ds"] else None, line=line,
                basis="ledger autonomy_capped: a step above the autonomy cap was refused (kernel/autonomy.py)",
                status="warning" if hits else "good", why="no decision or cap hit was recorded in the window",
                how="set an autonomy cap (rihmasto autonomy set): a step above it is refused and counted here")


def _proposals(scope: Scope) -> list[Row]:
    """Agents' proposals in the agent channels of the scope, in the window (kernel/agent_channel.py)."""
    try:
        from kernel import agent_channel as ch
    except ImportError:
        return []
    return [m for p in scope.projects for m in ch.read(p)["messages"]
            if m.get("kind") == "proposal" and scope.inside(when(m.get("at")))]


def _t_proposals(c: Row) -> Row:
    rows = _proposals(c["scope"])
    states = Counter(m.get("state") or "open" for m in rows)
    line = (f"Agents proposed {count(len(rows), 'answer')}: {states['confirmed']} confirmed, {states['rejected']} "
            f"rejected and {states['open']} waiting on a person." if rows else "No agent proposed an answer.")
    return tile("agent_proposals", "Agents' proposals", len(rows) if rows or c["ds"] else None, line=line,
                sub=f"{states['open']} waiting" if rows else None, status="warning" if states["open"] else None,
                basis="agent channel proposals and how a person settled them (confirmed, rejected or open)",
                why="no agent proposal or decision was recorded in the window",
                how="let a coding agent work over the agent bridge (rihmasto handoff): its proposals wait for a person")


def _t_delegations(c: Row) -> Row:
    active = c["active"]
    line = (f"{count(len(active), 'delegation')} in force; the next ends {min(d['until'] for d in active)}."
            if active else "No delegation is in force: every card waits for a person.")
    return tile("delegations", "Delegations in force", len(active), basis="delegations.json, active now", line=line)


def _t_integrity(c: Row) -> Row:
    intact, broken = _integrity(c["scope"])
    chains = intact + len(broken)
    line = (f"{count(len(broken), 'ledger')} did not verify: {', '.join(broken[:3])}." if broken
            else f"Every ledger's chain verified ({intact} of {chains}).")
    return tile("ledger_integrity", "Verified ledgers", intact if chains else None, sub=f"of {chains}",
                basis="each project's hash chain verified now, against the cockpit's kept head where it keeps one",
                status="critical" if broken else "good", line=line, why="no project has a ledger yet",
                how="create a project: every step it takes is appended to its ledger")


def _bins(values: list[float]) -> list[Row]:
    rows, lo = [], 0.0
    for label, hi in AGE_BINS:
        rows.append({"label": label, "value": sum(1 for v in values if v >= lo and (hi is None or v < hi))})
        lo = float(hi or lo)
    return rows


def _waiting_rows(c: Row) -> list[Row]:
    scope = c["scope"]
    titles = {p.pid: scope.title(p) for p in scope.projects}
    return [{"label": f"{w['card']} · {w['kind'].replace('_', ' ')}", "value": w["age"],
             "sub": titles.get(w["project"].pid) if scope.pid is None else w["title"][:60],
             "href": f"#/p/{w['project'].pid}/inbox/{w['card']}"} for w in c["waiting"][:10]]


def _charts(c: Row, tiles: list[Row]) -> list[Row]:
    scope, ds = c["scope"], c["ds"]
    personas = Counter(d["persona"] or "not recorded" for d in ds)
    persona_rows = [{"label": k.replace("_", " "), "value": v} for k, v in personas.most_common()]
    times = _times(ds)
    return [
        chart("over_time", "Decisions over time", "columns", unit="decisions",
              rows=series_rows(scope, [(d["at"], d["actor"], 1) for d in ds]),
              series=[{"key": k, "label": v} for k, v in ACTORS.items() if c["actors"].get(k)],
              basis="canon decisions.json per " + unit_of(scope.window), line=tiles[0]["line"], why=NO_DECISION,
              how=HOW_DECIDE),
        chart("by_persona", "Decisions by persona", "bars", rows=persona_rows, unit="decisions",
              basis="the persona each decision was signed as", line=top("the decisions", persona_rows), why=NO_DECISION,
              how=HOW_DECIDE),
        chart("time_to_decide", "Time to decide", "bars", rows=_bins(times) if times else [], unit="cards",
              basis="hours from a card's creation to its decision", line=tiles[2]["line"],
              why="no card was decided in the window", how=HOW_DECIDE),
        chart("waiting", "Oldest cards waiting", "bars", unit="hours", rows=_waiting_rows(c),
              basis="open decision cards by age", line=tiles[3]["line"], why="nothing waits on a person",
              how="cards open as the work needs a person: a question, an approval, an escalation"),
    ]


def read(scope: Scope) -> dict[str, Any]:
    c = _context(scope)
    tiles = [_t_decisions(c), _t_delegated(c), _t_time(c), _t_waiting(c), _t_holds(c), _t_capped(c),
             _t_delegations(c), _t_integrity(c), _t_proposals(c)]
    from kernel.insights.evals import tiles as gnomon_tiles  # Gnomon's audits (FR-EVL1)

    tiles += gnomon_tiles(scope, "governance")
    gaps = [gap("Why a cap was set where it is", "a cap change records who set it and the reason, not the risk it "
                "weighed", "read the autonomy_cap_set records in the project's ledger (rihmasto autonomy show)")]
    return answer(scope, "governance", tiles, _charts(c, tiles), gaps)
