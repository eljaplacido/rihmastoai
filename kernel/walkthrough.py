"""Walkthroughs in Ask Rihma (FR-WLK1, docs/guides/walkthroughs.md): Rihma takes a person through plugging in
an existing project, starting from an idea or from documents, setting up a model, or a tour of the cockpit,
step by step in the chat.

A walkthrough is a small state machine. Each step says what it asks (a question, with the options offered as
buttons), what it does with the reply (a folder is checked and scanned, nothing recorded), and what it shows
(the scan's counts, a job's progress, the result). It runs without a model: the prompts are fixed and a reply
is read by rule (a path, yes or no in English or Finnish, a pick from the options by its number, its id or its
words). With a model (``reader``), a free-text reply the rules cannot place is read by the model into one of
the offered options; the model never decides anything on its own, and what it read is said in the chat.

Every step that changes something is a proposal: the walkthrough stops with a Confirm button, and nothing
is written until the person presses it. Confirming calls ``run`` with the proposal, which is the same path
the cockpit's own routes take (adopt, new project, Models setup, Project settings, Shape it in chat), signed
with the person's name and persona and checked as those routes check. The walkthrough itself only keeps its
conversation.

Kept per person under the factory home's ``_walkthroughs/`` (one file a walkthrough, and the folders a person
typed before), resumable, one active per person (a Models setup detour pauses the one it came from), cancel
at any time. The factory's ledger records walkthrough_started, walkthrough_step and walkthrough_done with ids
and step names only: what a person typed stays in the walkthrough's own file.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel.canon import DecisionRefused
from kernel.people import PERSONAS, is_person
from kernel.store import Factory, read_json, records_lock, updating_json

SCHEMA = "rihmasto.walkthrough/1"
ID = re.compile(r"WT-\d{3,6}\Z")
MAX_REPLY = 2000
MAX_MESSAGES = 200
RECENT = 5
BACK = {"id": "back", "label": "Back"}
WAITING = ("adopting", "intake")         # steps that wait on a job
Reader = Callable[[str, list[dict[str, Any]]], str | None]
Runner = Callable[[dict[str, Any]], dict[str, Any]]


class WalkRefused(ValueError):
    """A step the walkthrough does not take, with the reason."""


# -- where it is kept -------------------------------------------------------------------------------------

def walk_dir(factory: Factory) -> Path:
    return factory.home / "_walkthroughs"


def _file(factory: Factory, wid: str) -> Path:
    if not ID.match(wid or ""):
        raise KeyError(f"no walkthrough {wid!r}")
    return walk_dir(factory) / f"{wid}.json"


def get(factory: Factory, wid: str) -> dict[str, Any]:
    w = read_json(_file(factory, wid), None)
    if not isinstance(w, dict):
        raise KeyError(f"no walkthrough {wid}")
    return w


def _all(factory: Factory) -> list[dict[str, Any]]:
    out = [read_json(p, None) for p in sorted(walk_dir(factory).glob("WT-*.json"))]
    return [w for w in out if isinstance(w, dict)]


def mine(factory: Factory, person: str) -> dict[str, Any] | None:
    """The person's active walkthrough, or None."""
    return next((w for w in reversed(_all(factory)) if w.get("person") == person and w.get("state") == "active"), None)


def recent(factory: Factory, person: str) -> list[str]:
    """The folders and addresses this person gave a walkthrough before, newest first."""
    kept = read_json(walk_dir(factory) / "recent.json", {}) or {}
    return [str(x) for x in kept.get(person) or []][:RECENT]


def remember(factory: Factory, person: str, source: str) -> None:
    with updating_json(walk_dir(factory) / "recent.json", {}) as kept:
        kept[person] = [source, *[x for x in kept.get(person) or [] if x != source]][:RECENT]


def _record(factory: Factory, events: list[tuple[str, dict[str, Any]]]) -> None:
    """Each event in the factory's ledger, in order: ids and step names, signed by the person."""
    from kernel.learn import factory_project

    if not events:
        return
    canon = factory_project(factory)
    for kind, payload in events:
        canon.log(kind, payload)


def _signed(person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"refused: {person!r} is not a person; a walkthrough is signed by a named person")
    if persona not in PERSONAS:
        raise DecisionRefused(f"refused: persona must be one of {', '.join(PERSONAS)}")


def _new_id(factory: Factory) -> str:
    root = walk_dir(factory)
    root.mkdir(parents=True, exist_ok=True)
    with records_lock(root / "ids.lock"):
        taken = [int(p.stem[3:]) for p in root.glob("WT-*.json") if p.stem[3:].isdigit()]
        wid = f"WT-{max(taken, default=0) + 1:03d}"
        (root / f"{wid}.json").write_text("{}\n", encoding="utf-8")
    return wid


# -- the steps' context ---------------------------------------------------------------------------------------

class Ctx:
    """What a step works with: the walkthrough, the factory, who replies, the model reader if any, and the
    messages and ledger events the step adds."""

    def __init__(self, factory: Factory, w: dict[str, Any], person: str, persona: str, reader: Reader | None) -> None:
        self.factory, self.w, self.person, self.persona, self.reader = factory, w, person, persona, reader
        self.events: list[tuple[str, dict[str, Any]]] = []

    @property
    def data(self) -> dict[str, Any]:
        return self.w.setdefault("data", {})

    def say(self, text: str, **extra: Any) -> dict[str, Any]:
        msg = {"from": "rihma", "step": self.w.get("step"), "text": text, "at": self.factory.clock.stamp(),
               **{k: v for k, v in extra.items() if v not in (None, [], {})}}
        self.w.setdefault("messages", []).append(msg)
        return msg


def _flows() -> dict[str, Any]:
    from kernel import walkthrough_adopt, walkthrough_more

    return {**walkthrough_adopt.FLOWS, **walkthrough_more.FLOWS}


def flow(name: str) -> Any:
    flows = _flows()
    if name not in flows:
        raise WalkRefused(f"no walkthrough {name!r}: one of {', '.join(flows)}")
    return flows[name]


def catalogue() -> list[dict[str, Any]]:
    """The walkthroughs Ask Rihma offers, in order."""
    return [{"name": n, "label": f.label, "about": f.about, "control": f.control} for n, f in _flows().items()]


def _ask(ctx: Ctx) -> None:
    """The current step's question, said in the chat, with Back where there is a step to go back to."""
    f = flow(ctx.w["name"])
    msg = getattr(f, "ask_" + ctx.w["step"])(ctx)
    if msg is not None:
        msg["ask"] = True
    if msg is not None and ctx.w.get("trail") and ctx.w["step"] not in WAITING and ctx.w["step"] != "done" \
            and not msg.get("final"):
        msg.setdefault("options", []).append(dict(BACK))


def _carry(w: dict[str, Any]) -> None:
    """What a step said without moving on (why a folder may not be read) carries the step's buttons and input,
    so the person answers right there."""
    last = w["messages"][-1]
    asked = next((m for m in reversed(w["messages"][:-1]) if m.get("from") == "rihma" and m.get("ask")
                  and m.get("step") == w["step"]), None)
    if asked is None or last.get("from") != "rihma" or last.get("options") or last.get("proposal"):
        return
    for key in ("options", "input", "proposal"):
        if asked.get(key):
            last[key] = asked[key]


def _go(ctx: Ctx, step: str) -> None:
    w = ctx.w
    if step != w["step"]:
        w.setdefault("trail", []).append(w["step"])
        w["step"] = step
        ctx.events.append(("walkthrough_step", {"walkthrough": w["id"], "name": w["name"], "step": step,
                                                "person": ctx.person, "persona": ctx.persona}))
    _ask(ctx)
    if step == "done":
        _end(ctx, w.get("outcome") or "done")


def _end(ctx: Ctx, outcome: str) -> None:
    w = ctx.w
    w["state"], w["outcome"], w["ended"] = ("cancelled" if outcome in ("cancelled", "replaced") else "done"), outcome, \
        ctx.factory.clock.stamp()
    made = ctx.data.get("project")
    ctx.events.append(("walkthrough_done", {"walkthrough": w["id"], "name": w["name"], "outcome": outcome,
                                            "person": ctx.person, "persona": ctx.persona,
                                            **({"project": made} if isinstance(made, str) else {})}))


def _flush(factory: Factory, ctx: Ctx) -> None:
    _record(factory, ctx.events)
    ctx.events.clear()


def _trim(w: dict[str, Any]) -> None:
    w["messages"] = (w.get("messages") or [])[-MAX_MESSAGES:]


# -- starting, replying, confirming, cancelling ---------------------------------------------------------------

def start(factory: Factory, name: str, *, person: str, persona: str, said: str = "", replace: bool = False,
          parent: str | None = None, reader: Reader | None = None) -> dict[str, Any]:
    """Start a walkthrough for a person, or resume the one of that name they have going. Another one going is
    refused unless ``replace`` (it is then ended as replaced). ``said`` carries what the person said first
    (a sentence, a folder) into the first step."""
    _signed(person, persona)
    f = flow(name)
    going = mine(factory, person)
    if going is not None and going["name"] == name and not said and parent is None:
        return going
    if going is not None and going["id"] != parent:
        if not replace:
            raise WalkRefused(f"{going['id']} ({flow(going['name']).label}) is going: resume it or cancel it first")
        cancel(factory, going["id"], person=person, persona=persona, outcome="replaced")
    wid = _new_id(factory)
    w = {"schema": SCHEMA, "id": wid, "name": name, "label": f.label, "state": "active", "person": person,
         "persona": persona, "started": factory.clock.stamp(), "step": f.first, "trail": [], "data": {},
         "messages": [], "parent": parent}
    ctx = Ctx(factory, w, person, persona, reader)
    ctx.events.append(("walkthrough_started", {"walkthrough": wid, "name": name, "person": person, "persona": persona,
                                               **({"parent": parent} if parent else {})}))
    ctx.say(f.intro)
    if said.strip():
        w["messages"].append({"from": "person", "text": said.strip()[:MAX_REPLY], "at": factory.clock.stamp()})
        nxt = getattr(f, "take_" + f.first)(ctx, {"text": said.strip()[:MAX_REPLY], "choice": None})
        if nxt:
            _go(ctx, nxt)
        else:
            _ask(ctx)
    else:
        _ask(ctx)
    with updating_json(_file(factory, wid), {}) as stored:
        stored.clear()
        stored.update(w)
    _flush(factory, ctx)
    return w


def _active(w: dict[str, Any]) -> None:
    if w.get("state") != "active":
        raise WalkRefused(f"{w.get('id')} is {w.get('state')}: start it again from Walkthroughs")


def _owned(factory: Factory, w: dict[str, Any], person: str, enforced: bool) -> None:
    """With access enforced the name is verified: a walkthrough answers the person who started it only."""
    if enforced and w.get("person") != person:
        raise DecisionRefused(f"refused: {w['id']} is {w.get('person')}'s walkthrough")


def _label_of(w: dict[str, Any], choice: str | None) -> str | None:
    last = next((m for m in reversed(w.get("messages") or []) if m.get("from") == "rihma" and m.get("options")), None)
    return next((o["label"] for o in (last or {}).get("options") or [] if o["id"] == choice), None)


def offered(w: dict[str, Any]) -> list[dict[str, Any]]:
    """The options the current step offers (its last question's buttons)."""
    last = next((m for m in reversed(w.get("messages") or []) if m.get("from") == "rihma"
                 and m.get("step") == w.get("step")), None)
    return list((last or {}).get("options") or [])


def reply(factory: Factory, wid: str, *, person: str, persona: str, text: str | None = None,
          choice: str | None = None, exclude: list[str] | None = None, job: dict[str, Any] | None = None,
          reader: Reader | None = None, enforced: bool = False) -> dict[str, Any]:
    """The person's reply to the current step: typed ``text``, a ``choice`` among the offered options, the
    files unticked in the full map (``exclude``), or a waited-for ``job`` that ended. Nothing outside the
    walkthrough's own file and its ledger records is written here."""
    _signed(person, persona)
    text = (text or "").strip()
    if len(text) > MAX_REPLY:
        raise WalkRefused(f"a reply is at most {MAX_REPLY} characters")
    if not text and not choice and exclude is None and job is None:
        raise WalkRefused("say something, or press one of the buttons")
    with updating_json(_file(factory, wid), {}) as w:
        _open_to(factory, w, wid, person, enforced)
        _check_choice(w, choice, job)
        _heard(factory, w, _label_of(w, choice) if choice else text, choice)
        if choice and choice.startswith("walk:"):          # a detour: this one waits while the other runs
            ctx = None
        else:
            ctx = Ctx(factory, w, person, persona, reader)
            _answer(ctx, text, choice, exclude, job)
            _trim(w)
        out = dict(w)
    if ctx is None:
        return detour(factory, wid, str(choice)[5:], person=person, persona=persona, reader=reader)
    _flush(factory, ctx)
    switch = out.get("switch")
    if isinstance(switch, dict) and out.get("state") == "done":     # a folder with no code: documents instead
        return start(factory, switch["name"], person=person, persona=persona, said=str(switch.get("said") or ""),
                     reader=reader) | {"switched_from": out["id"]}
    return _back_to_parent(factory, out, person, persona)


def _open_to(factory: Factory, w: dict[str, Any], wid: str, person: str, enforced: bool) -> None:
    if not w:
        raise KeyError(f"no walkthrough {wid}")
    _active(w)
    _owned(factory, w, person, enforced)


def _check_choice(w: dict[str, Any], choice: str | None, job: dict[str, Any] | None) -> None:
    if choice and job is None and choice not in {o["id"] for o in offered(w)}:
        raise WalkRefused(f"{choice!r} is not one of the options offered now")


def _heard(factory: Factory, w: dict[str, Any], shown: str | None, choice: str | None) -> None:
    """What the person said or pressed, in the conversation (never in the ledger)."""
    if shown:
        w["messages"].append({"from": "person", "text": shown[:MAX_REPLY], "at": factory.clock.stamp(),
                              **({"choice": choice} if choice else {})})


def _answer(ctx: Ctx, text: str, choice: str | None, exclude: list[str] | None, job: dict[str, Any] | None) -> None:
    """The step reads the reply: Back, the unticked files, or its own take, which moves on or says why not."""
    w, f = ctx.w, flow(ctx.w["name"])
    if choice == "back" and w.get("trail"):
        w["step"] = w["trail"].pop()
        ctx.events.append(("walkthrough_step", {"walkthrough": w["id"], "name": w["name"], "step": w["step"],
                                                "person": ctx.person, "persona": ctx.persona, "back": True}))
        _ask(ctx)
        return
    if exclude is not None:
        f.untick(ctx, exclude)
        return
    before = len(w["messages"])
    nxt = getattr(f, "take_" + w["step"])(ctx, {"text": text or None, "choice": choice, "job": job})
    if nxt:
        _go(ctx, nxt)
    elif len(w["messages"]) == before:
        ctx.say("I could not place that. Pick one of the buttons, or type it again.")
        _ask(ctx)
    else:
        _carry(w)


def _back_to_parent(factory: Factory, out: dict[str, Any], person: str, persona: str) -> dict[str, Any]:
    """A detour that ended takes the walkthrough it came from up again; the answer says which."""
    if out.get("state") in ("done", "cancelled") and out.get("parent") and out.get("outcome") != "replaced":
        parent = resume(factory, out["parent"], person=person, persona=persona)
        return out | {"resumed": parent["id"]}
    return out


def proposal(w: dict[str, Any]) -> dict[str, Any] | None:
    """The proposal the current step waits on, or None."""
    last = next((m for m in reversed(w.get("messages") or []) if m.get("from") == "rihma"
                 and m.get("step") == w.get("step")), None)
    return (last or {}).get("proposal")


def confirm(factory: Factory, wid: str, *, person: str, persona: str, run: Runner,
            enforced: bool = False) -> dict[str, Any]:
    """Carry out the proposal the current step waits on, through ``run`` (the cockpit's own route, or the
    kernel's own call on the command line), signed by the person. A refusal is said in the chat; nothing
    changed then."""
    _signed(person, persona)
    w = get(factory, wid)
    _active(w)
    _owned(factory, w, person, enforced)
    prop = proposal(w)
    if prop is None:
        raise WalkRefused("nothing waits on a confirm now")
    step = w["step"]
    try:
        result, refused = run(prop), None
    except (WalkRefused, DecisionRefused, PermissionError, ValueError, KeyError, OSError) as exc:
        result, refused = None, str(exc.args[0] if isinstance(exc, KeyError) and exc.args else exc)
    with updating_json(_file(factory, wid), {}) as w:
        ctx = Ctx(factory, w, person, persona, None)
        if refused is not None:
            ctx.say(f"That was refused, and nothing was changed: {refused}", refused=True)
            _ask(ctx)
        elif w.get("step") == step:
            w["messages"].append({"from": "person", "text": prop["label"], "at": factory.clock.stamp(),
                                  "confirmed": prop["action"]})
            _go(ctx, getattr(flow(w["name"]), "done_" + step)(ctx, prop, result or {}))
        _trim(w)
        out = dict(w)
    _flush(factory, ctx)
    return _back_to_parent(factory, out, person, persona) | ({"refused": refused} if refused else {})


def cancel(factory: Factory, wid: str, *, person: str, persona: str, outcome: str = "cancelled",
           enforced: bool = False) -> dict[str, Any]:
    """End a walkthrough at any step. What it already confirmed stays; nothing else is undone or done."""
    _signed(person, persona)
    with updating_json(_file(factory, wid), {}) as w:
        if not w:
            raise KeyError(f"no walkthrough {wid}")
        _owned(factory, w, person, enforced)
        ctx = Ctx(factory, w, person, persona, None)
        if w.get("state") in ("active", "paused"):
            ctx.say("Cancelled. Nothing more is done; what you confirmed before stays."
                    if outcome == "cancelled" else "Ended: another walkthrough took its place.")
            _end(ctx, outcome)
        out = dict(w)
    _flush(factory, ctx)
    return _back_to_parent(factory, out, person, persona)


def detour(factory: Factory, wid: str, name: str, *, person: str, persona: str,
           reader: Reader | None = None) -> dict[str, Any]:
    """Pause this walkthrough and start ``name`` (Models setup from a confidential project's question); the
    paused one is offered again when that one ends."""
    with updating_json(_file(factory, wid), {}) as w:
        _active(w)
        w["state"] = "paused"
    _record(factory, [("walkthrough_step", {"walkthrough": wid, "name": w["name"], "step": "paused", "person": person,
                                            "persona": persona})])
    return start(factory, name, person=person, persona=persona, parent=wid, reader=reader)


def resume(factory: Factory, wid: str, *, person: str, persona: str) -> dict[str, Any]:
    """Take a paused walkthrough up again where it was."""
    _signed(person, persona)
    with updating_json(_file(factory, wid), {}) as w:
        if w.get("state") != "paused":
            return dict(w)
        w["state"] = "active"
        ctx = Ctx(factory, w, person, persona, None)
        ctx.say("Back to " + w["label"] + ", where we were.")
        _ask(ctx)
        out = dict(w)
    _record(factory, [("walkthrough_step", {"walkthrough": wid, "name": out["name"], "step": out["step"],
                                            "person": person, "persona": persona, "resumed": True})])
    return out


# -- what the chat shows -----------------------------------------------------------------------------------

def awaiting(w: dict[str, Any]) -> dict[str, Any]:
    """What the walkthrough waits on now: a confirm, a job, a reply (typed or a button), or nothing."""
    if w.get("state") != "active":
        return {"kind": w.get("state")}
    if w.get("step") in WAITING:
        return {"kind": "job", "job": (w.get("data") or {}).get("job")}
    prop = proposal(w)
    if prop is not None:
        return {"kind": "confirm", "label": prop["label"], "action": prop["action"]}
    last = next((m for m in reversed(w.get("messages") or []) if m.get("from") == "rihma"), {}) or {}
    return {"kind": "reply", "input": last.get("input"), "options": len(last.get("options") or [])}


def view(w: dict[str, Any]) -> dict[str, Any]:
    data = w.get("data") or {}
    return {k: w.get(k) for k in ("id", "name", "label", "state", "step", "person", "persona", "started", "ended",
                                   "outcome", "parent", "messages")} | {
        "awaiting": awaiting(w), "project": data.get("project"), "job": data.get("job"),
        "steps": flow(w["name"]).steps}
