"""Signals: the delivery square's front corner, where business needs arrive before any project exists.

Needs come from the operation: a business chat, a data feed, a monitoring alert, a form, a meeting
note, an end user's message through an embedded chat. Each one is a **signal**. The factory triages
it:

- a signal about an existing project becomes a **change** on that project, so it enters the change
  loop like any other feedback;
- a new need becomes a **concept** card in the factory's own Inbox. A business owner or product
  owner validates it (it becomes a project, with intake started from the need), parks it, or
  rejects it. Nothing becomes a project without that person's decision.

The triage needs no model. A model, if given, only summarises the need into a concept (title,
problem, who, value) and may name an existing project it is about; the kernel checks that project
exists before routing anything there.

The signals live in the factory's own canon (`_factory/signals.json`) and change only under its
lock (kernel.store.updating_json): a signal received while another arrives, or while a triage
waits on its model, is never lost and never shares an id. Reading never creates the factory's canon.
"""

from __future__ import annotations

import re
from contextlib import AbstractContextManager

from kernel.canon import Canon
from kernel.model import ModelError, extract_json
from kernel.people import is_person
from kernel.profiles import PROFILES, propose_profile
from kernel.store import MATURITIES, MODES, lock_path, records_lock, updating_json

CHANNELS = ("chat", "feed", "form", "email", "monitoring", "meeting", "embed", "manual")
STATES = ("new", "routed", "concept", "validated", "parked", "rejected")
MAX_TEXT = 8000
_WORD = re.compile(r"[a-zåäö0-9]{4,}")
_STOP = {"that", "this", "with", "from", "have", "they", "their", "there", "would", "should", "could", "about",
         "which", "when", "what", "where", "into", "more", "some", "only", "also", "need", "want", "team"}


def _factory(factory, create: bool = True):
    from kernel.learn import factory_project

    return factory_project(factory, create)


def signals(factory, state: str | None = None) -> list:
    fp = _factory(factory, create=False)            # a read never creates the factory's canon
    items = (fp.read("signals.json", []) or []) if fp is not None else []
    return [s for s in items if state is None or s["state"] == state]


def _editing(fp) -> AbstractContextManager[list]:
    """The signals, read and written back under their lock (kernel.store.updating_json)."""
    return updating_json(fp.path("signals.json"), [])


def receive(factory, text: str, *, channel: str, source: str, person: str | None = None,
            persona: str | None = None, ref: str | None = None) -> dict:
    """Record a signal as it arrived. ``source`` names where it came from (a chat channel, a feed);
    ``person`` is who raised it, when a person did."""
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {CHANNELS}, got {channel!r}")
    if not str(text).strip():
        raise ValueError("the signal is empty")
    if person is not None and not is_person(person):
        raise ValueError(f"{person!r} is not a person")
    from kernel.people import PERSONAS

    if persona is not None and persona not in PERSONAS:
        raise ValueError(f"persona must be one of {PERSONAS}")
    fp = _factory(factory)
    with _editing(fp) as items:
        s = {"id": f"S-{len(items) + 1:03d}", "text": str(text).strip()[:MAX_TEXT], "channel": channel,
             "source": str(source)[:200], "person": person, "persona": persona, "ref": ref, "state": "new",
             "at": factory.clock.stamp(), "routed_to": None}
        items.append(s)
    fp.log("signal_received", {"id": s["id"], "channel": channel, "source": s["source"],
                               "person": person, "persona": persona})
    return s


def _words(text: str) -> set:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def match_project(factory, text: str):
    """An existing project the signal names: its id verbatim, or at least two of its title's words."""
    low, words = text.lower(), _words(text)
    best, best_n = None, 1
    for p in factory.projects():
        if p.pid.startswith("_"):
            continue
        if p.pid in low:
            return p
        n = len(words & _words(p.meta.get("title", "")))
        if n > best_n:
            best, best_n = p, n
    return best


def _concept_prompt(text: str, projects: list) -> str:
    listing = "\n".join(f"- {p.pid}: {p.meta.get('title')}" for p in projects) or "- (none)"
    return f"""A business need arrived at a solution factory. Summarise it as a concept a business owner can
validate, and say whether it is about one of the existing projects instead.

Existing projects:
{listing}

The need, verbatim:
<<<
{text[:MAX_TEXT]}
>>>

Answer with this JSON in a ```json block:
{{"title": "a short name", "problem": "one sentence", "who": "who has the problem",
  "value": "what it is worth if solved", "existing_project": "<project id or null>"}}
"""


def _summary(model, text: str, projects: list) -> dict:
    """The analyst's concept summary: empty with no model, when it fails, or when it answers anything
    but a JSON object (a list, a string), so the rules' title and body apply."""
    if model is None:
        return {}
    try:
        summary = extract_json(model.ask(_concept_prompt(text, projects), role="analyst"))
    except ModelError:
        return {}
    return summary if isinstance(summary, dict) else {}


def _new_signal(items: list, signal_id: str) -> dict:
    s = next((x for x in items if x["id"] == signal_id), None)
    if s is None:
        raise KeyError(signal_id)
    if s["state"] != "new":
        raise ValueError(f"{signal_id} is already {s['state']}")
    return s


def triage(factory, signal_id: str, *, model=None) -> dict:
    """Route a new signal to a change on the project it is about, or to a concept card. The model is
    asked with no lock held; the signal is then read again under the lock and routed once, so a
    signal that arrived meanwhile is kept and one another triage took is refused."""
    s = _new_signal(signals(factory), signal_id)
    projects = [p for p in factory.projects() if not p.pid.startswith("_")]
    summary = _summary(model, s["text"], projects)
    fp = _factory(factory)
    with _editing(fp) as items:
        s = _new_signal(items, signal_id)
        s.update(_route(factory, fp, s, summary, projects))
    fp.log("signal_triaged", {"id": s["id"], "state": s["state"], "routed_to": s["routed_to"]})
    return s


def _route(factory, fp, s: dict, summary: dict, projects: list) -> dict:
    """Open the card the signal becomes; return the signal's new state and where it went."""
    named = summary.get("existing_project")        # a model's guess counts only for a project that exists
    target = factory.project(named) if named and any(p.pid == named for p in projects) else None
    target = target or match_project(factory, s["text"])
    raised_by = s["person"] or f"{s['channel']} signal from {s['source']}"
    if target is not None:
        from kernel.change import submit

        # The change keeps the persona the signal carried: triage routes by it (IT's need is an
        # infrastructure change). A signal nobody's persona raised is a stakeholder's.
        card = submit(target, persona=s.get("persona") or "stakeholder", person=raised_by,
                      text=f"[signal {s['id']} via {s['channel']}] {s['text']}")
        return {"state": "routed", "routed_to": {"project": target.pid, "card": card["id"]}}
    proposal = propose_profile(s["text"])
    title = str(summary.get("title") or s["text"].splitlines()[0])[:80]
    body = "\n".join(f"{k.capitalize()}: {summary[k]}" for k in ("problem", "who", "value") if summary.get(k)) \
        or s["text"][:600]
    card = Canon(fp).card(
        "concept", f"Validate as a concept? {title}", body=body,
        refs={"signal": s["id"]},
        payload={"signal": s["id"], "title": title, "text": s["text"], "profile": proposal["profile"],
                 "profile_basis": proposal["basis"], "maturity": "demo", "mode": "mixed",
                 "raised_by": raised_by, "summary": summary or None})
    return {"state": "concept", "routed_to": {"project": None, "card": card["id"]}}


def edit_concept(factory, card_id: str, *, person: str, persona: str, **fields) -> dict:
    """Before deciding, a business owner or product owner may set the concept's title, profile,
    maturity or mode. The edit is recorded with their name."""
    from kernel.canon import CARD_DECIDERS, DecisionRefused

    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person")
    if persona not in CARD_DECIDERS["concept"]:
        raise DecisionRefused(f"a {persona} may not edit a concept")
    fp = _factory(factory, create=False)
    if fp is None:                                   # no factory canon: no concept card either
        raise KeyError(card_id)
    allowed = {"title": None, "profile": PROFILES, "maturity": MATURITIES, "mode": MODES}
    with Canon(fp).edit_card(card_id) as card:      # under the canon's lock; a refusal writes nothing
        if card["kind"] != "concept" or card["state"] != "open":
            raise DecisionRefused(f"{card_id} is not an open concept")
        for k, v in fields.items():
            if k not in allowed:
                raise ValueError(f"a concept has no field {k!r}")
            if allowed[k] is not None and v not in allowed[k]:
                raise ValueError(f"{k} must be one of {', '.join(allowed[k])}")
            card["payload"][k] = str(v)[:80] if k == "title" else v
    fp.log("concept_edited", {"card": card_id, "fields": sorted(fields), "by": person, "persona": persona})
    return card


def apply_concepts(factory) -> list:
    """Carry out decided concept cards once: a validated concept becomes a project whose intake
    starts from the need; a parked or rejected one closes its signal. Appliers at once (the pipeline
    job and the cockpit) take turns under the signals' lock, so a concept never becomes two projects."""
    fp = _factory(factory, create=False)
    if fp is None:                                   # no factory canon: no concept was ever decided
        return []
    done: list = []
    with records_lock(lock_path(fp.path("signals.json"))):
        applied = set(fp.read("concepts_applied.json", []) or [])
        for card in Canon(fp).cards(state="decided", kind="concept"):
            if card["id"] in applied:
                continue
            with _editing(fp) as items:
                out = _apply_concept(factory, card, items)
            done.append(out)
            applied.add(card["id"])
            fp.write("concepts_applied.json", sorted(applied))
            fp.log("concept_applied", out | {"person": card["decision"]["person"]})
    return done


def _apply_concept(factory, card: dict, items: list) -> dict:
    """Carry out one decided concept card, and move its signal along with it."""
    d, pl = card["decision"], card["payload"]
    s = next((x for x in items if x["id"] == pl["signal"]), None)
    if d["verdict"] != "validate":
        if s:
            s["state"] = "parked" if d["verdict"] == "park" else "rejected"
        return {"card": card["id"], "verdict": d["verdict"]}
    p = factory.new_project(pl["title"], maturity=pl["maturity"], mode=pl["mode"], profile=pl["profile"])
    p.write("need.json", {"text": pl["text"], "requested_by": d["person"], "signal": pl["signal"],
                          "concept": card["id"], "raised_by": pl.get("raised_by")})
    p.log("created_from_concept", {"concept": card["id"], "signal": pl["signal"], "validated_by": d["person"]})
    if s:
        s.update(state="validated", routed_to={"project": p.pid, "card": card["id"]})
    return {"card": card["id"], "verdict": "validate", "project": p.pid}


def square(factory) -> dict:
    """The delivery square at a glance: signals waiting, concepts to validate, projects per stage band,
    end-user feedback waiting for triage, and what runs in production: a project whose production
    slot holds a current release, or an adopted solution monitored where it runs (FR-Q7)."""
    from kernel.dashboard import pipeline
    from kernel.deliver import in_production

    sigs = signals(factory)
    fp = _factory(factory, create=False)            # a read never creates the factory's canon
    concepts = Canon(fp).cards(kind="concept") if fp is not None else []
    feedback, live = 0, 0
    for p in factory.projects():
        if p.pid.startswith("_"):
            continue
        feedback += sum(1 for c in Canon(p).cards(kind="change")
                        if c["payload"].get("source") == "end_user" and not c["payload"].get("triage"))
        if in_production(p):
            live += 1
    return {"signals": {"new": sum(1 for s in sigs if s["state"] == "new"), "total": len(sigs)},
            "concepts_waiting": [{"card": c["id"], "title": c["payload"]["title"], "profile": c["payload"]["profile"]}
                                 for c in concepts],
            "pipeline": pipeline(factory), "end_user_feedback_waiting": feedback, "in_production": live}
