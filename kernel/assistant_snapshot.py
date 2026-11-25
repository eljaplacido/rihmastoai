"""What the cockpit assistant may talk about, and what its sources rest on (kernel/assistant.py).

- **The snapshot** is a picture of the real read models: each project's now line, pause and latest
  release, what runs in production, the cards waiting on a person (as the Decisions waiting widget and
  the Inbox count them, the panel's open questions included) and whose they are, the gates, the
  builder models and the catalogue; with a project open, its health, evidence, tasks, cards (open and
  decided), questions, assumptions and releases, with their counts. A holdout ruling's body and reason
  stay in custody. Nothing outside it is known.
- **The budget**: `fit_snapshot` keeps it within a character budget by whole items, least needed first,
  and names what it left out; the items the question names go last (`relevant_first`).
- **Sources**: a source is backed when the records hold it (`known`, `backed`), not only when the
  fitted snapshot happened to show it.
"""

from __future__ import annotations

import copy
import json
import re
from collections import Counter
from typing import Any

from kernel.assistant_rules import FACTORY_PID, words
from kernel.canon import CARD_DECIDERS, CUSTODY_KINDS, Canon, deciders_of
from kernel.people import PERSONAS

ID = re.compile(r"\b(?:[A-Z]{1,2}-\d+(?:-AC-\d+)?)\b", re.I)


def _release(rel: dict) -> dict:
    from kernel.deliver import custody_safe  # what a holdout expected stays out (FR-T1-AC-4)

    steps = [s for s in rel.get("steps", []) if isinstance(s, dict)]
    return {"number": rel.get("release"), "state": rel.get("state"), "environments": rel.get("environments"),
            "deployed_to": [s["step"].split(":", 1)[1] for s in steps
                            if str(s.get("step", "")).startswith("deploy:") and s.get("outcome") == "passed"],
            "failed_step": rel.get("failed_step"), "reason": (custody_safe(rel.get("reason")) or None)}


def _pause(project: Any) -> dict | bool:
    pz = project.meta.get("pause")
    return {k: pz.get(k) for k in ("requested_by", "persona", "reason", "at", "stopped_at")} if pz else False


def _card(c: dict, persona: str | None) -> dict:
    """A card as the snapshot shows it. A holdout ruling's body stays in custody, and no decision's reason is
    sent to the model: the verdict and who decided are enough to name the card (the red team's canaries)."""
    from kernel.deliver import custody_safe

    held = c["kind"] in CUSTODY_KINDS
    out = {"id": c["id"], "kind": c["kind"], "title": c["title"][:120]}
    if c["state"] == "open":
        out.update(verdicts=c["verdicts"], deciders=c["deciders"], yours=persona in c["deciders"],
                   summary=None if held else (custody_safe(c.get("body") or "")[:240] or None))
    else:
        d = c.get("decision") or {}
        out.update(state=c["state"], verdict=d.get("verdict"), by=d.get("person"), persona=d.get("persona"))
    return out


def _evidence_counts(project: Any) -> dict:
    from kernel.status import evidence

    counts: dict[str, int] = {}
    for e in evidence(project) if project.path("contract.json").exists() else []:
        counts[e["state"]] = counts.get(e["state"], 0) + 1
    return counts


def _project_part(project: Any, persona: str | None) -> dict:
    from kernel.deliver import releases
    from kernel.plan import required
    from kernel.status import health, live, now

    canon = Canon(project)
    counts = _evidence_counts(project)
    tasks, cards = project.read("tasks.json", {}) or {}, canon.cards(state=None)
    open_cards, questions = [c for c in cards if c["state"] == "open"], canon.questions()
    open_q, assumed = [q for q in questions if q["status"] == "open"], canon.assumptions("open")
    return {
        "id": project.pid, "title": project.meta.get("title"), "maturity": project.meta.get("maturity"),
        "stage": project.meta.get("stage"), "plan_held_for_approval": required(project), "now": now(project),
        "paused": _pause(project), "health": health(project), "evidence": counts, "live": live(project),
        "counts": {"open_cards": len(open_cards), "open_questions": len(open_q), "assumptions_open": len(assumed),
                   "questions_settled": len(questions) - len(open_q)},
        "tasks": {t: {"status": s.get("status"), "rounds": len(s.get("rounds", []))} for t, s in tasks.items()},
        "open_cards": [_card(c, persona) for c in open_cards],
        "open_questions": [{"id": q["id"], "text": q["text"][:160], "options": q.get("options", []),
                            "blocking": q["blocking"]} for q in open_q],
        "assumptions": [{"id": a["id"], "text": a["text"][:160], "due": a.get("due")} for a in assumed],
        "decided_cards": [_card(c, persona) for c in reversed([c for c in cards if c["state"] != "open"][-8:])],
        "releases": [_release(r) for r in releases(project)], "agents": _agents(project)}


def _agents(project: Any) -> dict:
    """What coding agents and Rihma's agents did here (the Agents strip, kernel/agent_writes.py), in short."""
    from kernel.agent_writes import activity

    a = activity(project, limit=5)
    return {k: a[k] for k in ("agents", "handoffs", "gates", "proposals_waiting")} | {
        "paused": bool(a["paused"]), "recent": [{k: i[k] for k in ("id", "who", "kind")} for i in a["items"]]}


def _waiting_cards(factory: Any, products: list, persona: str | None) -> list:
    """Every card that waits on a person, as the Decisions waiting widget and the Inbox count them: each
    product's open cards (the panel's questions, blocking or not, and every open change), and the concepts,
    approvals and questions of Rihma's own canon. "yours" is whether the persona may decide it. The
    persona's own come first, then what holds work up, then the oldest (as the widget orders them)."""
    from kernel.dashboard import _when

    now_t, out = factory.clock.now(), []
    own = [p for p in factory.projects() if p.pid == FACTORY_PID]
    for p, kinds in [(p, None) for p in products] + [(p, ("concept", "approval", "question")) for p in own]:
        for c in Canon(p).cards(state="open"):
            if kinds is not None and c["kind"] not in kinds:
                continue
            try:
                age = round((now_t - _when(c["created"])).total_seconds() / 3600, 1) if c.get("created") else None
            except (TypeError, ValueError):
                age = None
            who = list(deciders_of(c)) if c["kind"] in CARD_DECIDERS else []   # a card may narrow them
            out.append({"project": p.pid, "card": c["id"], "kind": c["kind"], "title": c["title"][:100],
                        "deciders": "any persona" if set(who) >= set(PERSONAS) else who,
                        "yours": persona in who, "blocking": bool(c.get("blocking")), "age_hours": age})
    out.sort(key=lambda i: (not i["yours"], i["kind"] == "question" and not i["blocking"], -(i["age_hours"] or 0)))
    return out


def _waiting(cards: list) -> dict:
    """What waits, in counts: the whole factory, the persona's own, by kind, and the persona's per project."""
    mine: dict[str, int] = {}
    for i in cards:
        if i["yours"]:
            mine[i["project"]] = mine.get(i["project"], 0) + 1
    return {"total": len(cards), "yours": sum(mine.values()), "by_kind": dict(Counter(i["kind"] for i in cards)),
            "yours_by_project": mine,
            "basis": "every open card a person decides, across the projects and Rihma itself, the panel's open "
                     "questions included: what the Decisions waiting widget and the Inbox count"}


def snapshot(factory: Any, *, project: Any = None, persona: str | None = None) -> dict:
    """A picture of what the assistant may talk about. Nothing outside it is known. The prompt
    carries it through `fit_snapshot`, which keeps it within its budget by whole items."""
    from kernel.dashboard import catalogue
    from kernel.deliver import in_production, latest_release
    from kernel.learn import model_reliability
    from kernel.projections import floor
    from kernel.status import now

    products = [p for p in factory.projects() if not p.pid.startswith("_")]
    cat, waiting = catalogue(factory), _waiting_cards(factory, products, persona)
    snap: dict[str, Any] = {"factory": {
        "projects": [{"id": p.pid, "title": p.meta.get("title"), "stage": p.meta.get("stage"),
                      "maturity": p.meta.get("maturity"), "now": now(p), "paused": _pause(p),
                      "latest_release": _release(r) if (r := latest_release(p)) else None} for p in products],
        "in_production": [p.pid for p in products if in_production(p)],
        "gates": floor(factory)["gates"],
        "waiting": _waiting(waiting),
        # With a project open, another product's cards are counts only: its titles never reach the model.
        "waiting_cards": waiting if project is None else [i for i in waiting
                                                          if i["project"] in (project.pid, FACTORY_PID)],
        "capabilities": {"counts": cat["counts"],
                         "in_use": [i["title"] for i in cat["items"] if i["state"] == "in_use"]},
        "models": model_reliability(factory)}}
    if project is not None:
        snap["project"] = _project_part(project, persona)
    _insights(factory, project, snap)
    return snap


def _insights(factory: Any, project: Any, snap: dict) -> None:
    """A few key figures from Insights (kernel/insights): the open project's, else the factory's. Figures only."""
    from kernel.insights import summary

    try:
        if project is not None and not project.pid.startswith("_"):
            snap["project"]["insights"] = summary(factory, pid=project.pid)
        elif project is None:
            snap["factory"]["insights"] = summary(factory)
    except Exception:  # noqa: BLE001 - the assistant answers without them rather than not at all
        return


# The snapshot as the model reads it: at most this many characters of JSON (FR-Z1-AC-4).
SNAPSHOT_BUDGET = 12_000
LAYOUT_BUDGET = 3_000
# What the snapshot sheds, least needed first: whole items from the end of these lists, at most
# `most` kept in any case: (section, key, how "not_shown" names them, most). The prompt puts the
# items the question names first (relevant_first), so they are the last to go.
SHED_ITEMS: tuple[tuple[str, str, str, int | None], ...] = (
    ("factory", "projects", "projects in the factory list", None), ("factory", "models", "builder models", None),
    ("factory", "waiting_cards", "decision cards waiting in the factory", None),
    ("project", "decided_cards", "decided cards", None), ("project", "releases", "releases", None),
    ("project", "assumptions", "open assumptions", None), ("project", "tasks", "tasks", None),
    ("project", "open_questions", "open questions", 6), ("project", "open_cards", "open cards", 10))
# Then whole sections, if the lists were not enough.
_SHED_SECTIONS = (("factory", "insights", "the factory's insights"), ("project", "insights", "the project's insights"),
                  ("project", "live", "the project's live run"), ("factory", "capabilities", "the catalogue"),
                  ("factory", "gates", "the factory's gates"), ("factory", "waiting", "what waits in the factory"),
                  ("project", "health", "the project's health"))


def _size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def _over(snap: dict, not_shown: list[str], budget: int) -> int:
    """How many characters the snapshot is over its budget, with room for its "not_shown" key."""
    return _size(snap) + (_size(not_shown) + 15 if not_shown else 0) - budget


def _shed(items: list | dict, excess: int) -> None:
    """Drop whole items from the end of ``items`` until about ``excess`` characters are gone."""
    gone = 0
    while items and gone < excess:
        if isinstance(items, dict):
            key, value = items.popitem()
            gone += _size(key) + _size(value) + 4
        else:
            gone += _size(items.pop()) + 2


def _fit_list(out: dict, items: list | dict, label: str, total: int, not_shown: list[str], budget: int) -> None:
    """Shed whole items while the snapshot, with the note that says so, is over budget; then add
    that note to ``not_shown`` if any of the ``total`` items are gone."""
    note = [f"{total} of {total} {label}"]  # as long as its note can be
    while items and _over(out, not_shown + (note if len(items) < total else []), budget) > 0:
        _shed(items, _over(out, not_shown + note, budget))
    if len(items) < total:
        not_shown.append(f"{total - len(items)} of {total} {label}")


def fit_snapshot(snap: dict, budget: int = SNAPSHOT_BUDGET) -> dict:
    """The snapshot within ``budget`` characters of JSON. Whole items go, least needed first, never a
    slice of one, and the snapshot's "not_shown" says what went (FR-Z1-AC-4)."""
    out: dict = copy.deepcopy(snap)
    not_shown: list[str] = []
    lists = [(items, label, len(items), most) for section, key, label, most in SHED_ITEMS
             if (items := (out.get(section) or {}).get(key))]
    for items, _label, _total, most in lists:  # the caps first, so the budget sheds only what it must
        if most is not None and isinstance(items, list):
            del items[most:]
    for items, label, total, _most in lists:
        _fit_list(out, items, label, total, not_shown, budget)
    for section, key, label in _SHED_SECTIONS:
        if _over(out, not_shown, budget) > 0 and key in (out.get(section) or {}):
            del out[section][key]
            not_shown.append(label)
    if _over(out, not_shown, budget) > 0:  # one record is too large by itself: say so rather than cut it
        out, not_shown = {}, [f"the whole snapshot: it is over {budget:,} characters even without its lists"]
    if not_shown:
        out["not_shown"] = not_shown
    return out


def relevant_first(snap: dict, question: str) -> dict:
    """The snapshot with the items the question names, by id or by its words, first in each list, so
    the budget sheds the others (the order is kept among the rest)."""
    out, q = copy.deepcopy(snap), words(question)
    ids = {i.upper() for i in ID.findall(question)} | set(re.findall(r"[a-z0-9_-]+", question.lower()))

    def rank(it: Any) -> int:
        named = isinstance(it, dict) and str(it.get("id")) in ids
        return -(10 * named + len(q & words(json.dumps(it, ensure_ascii=False, default=str))))

    for section, key, _label, _most in SHED_ITEMS:
        items = (out.get(section) or {}).get(key)
        if isinstance(items, list):
            items.sort(key=rank)
    return _grounded(out, question)


def _grounded(out: dict, question: str) -> dict:
    """A how-to question gets the matching journey's steps first (FR-JRN1), so the answer names steps and their
    buttons and never describes a view instead."""
    from kernel.journey_chat import grounding

    how = grounding(question)
    return {"how_to": how, **out} if how else out


# -- sources -----------------------------------------------------------------------------------------

def _spec_ids(project: Any) -> set:
    """The requirements, criteria and tasks of the project's spec and contract."""
    out: set = set()
    for doc in (project.read("spec.json") or {}, project.read("contract.json") or {}):
        for r in doc.get("requirements") or []:
            out |= {r.get("id")} | {c.get("id") for c in r.get("acceptance") or []}
        out |= {t.get("id") for t in doc.get("tasks") or [] if isinstance(t, dict)}
    return out


def _record_ids(project: Any) -> set:
    """Every card, question and assumption, the tasks, the spec's ids and the releases of a project."""
    from kernel.deliver import releases

    canon = Canon(project)
    return ({c["id"] for c in canon.cards(state=None)} | {q["id"] for q in canon.questions()}
            | {a["id"] for a in canon.assumptions()} | set(project.read("tasks.json", {}) or {})
            | _spec_ids(project) | {f"RELEASE {r.get('release')}" for r in releases(project)})


def known(factory: Any, project: Any, snap: dict) -> set:
    """Every id the records hold for the question's scope: the projects, what the snapshot names, and,
    with a project open, its cards, questions, assumptions, requirements, criteria, tasks and releases."""
    out = {p.pid for p in factory.projects()} | {i.upper() for i in ID.findall(json.dumps(snap, default=str))}
    return out | _record_ids(project) if project is not None else out


def _in_snapshot(snap: Any, path: str) -> bool:
    for part in [x for x in re.split(r"[./\[\]]+", path) if x]:
        if isinstance(snap, dict) and part in snap:
            snap = snap[part]
        elif isinstance(snap, list) and part.isdigit() and int(part) < len(snap):
            snap = snap[int(part)]
        else:
            return False
    return True


def backed(source: str, ids_held: set, snap: dict) -> bool:
    """A source the records hold: an id they hold, "card: C-0013", a snapshot path such as
    factory.gates.first_round_rate, or a phrase whose every id they hold."""
    body = re.sub(r"^\s*[A-Za-z_ ]{2,20}:\s*", "", source).strip()
    if any(s in ids_held or s.upper() in ids_held for s in (source.strip(), body)):
        return True
    if " " not in body and "." in body and _in_snapshot(snap, body):
        return True
    named = [i.upper() for i in ID.findall(source)] + re.findall(r"(?i)release \d+", source) \
        + [w for w in re.findall(r"[a-z0-9_][a-z0-9_-]+", source) if w in ids_held]
    return bool(named) and all(i in ids_held or i.upper() in ids_held for i in named)
