"""Learning from feedback: "This is unclear" and "This is wrong" change wording, rules and prompts by a reviewed path
(FR-HEAL1, D-0024 items 1 and 5).

A person flags an answer, a view, a card or a chat reply: the **kind** (unclear or wrong), **where** (the view, the
control or the card, and the words shown there), their own **words**, and optionally the wording they would use.
It is recorded (``feedback_given``, in the project's ledger or the factory's) and kept in ``heal/feedback.json``.

Feedback about the same thing is **grouped** (its kind, view, target and the words shown, normalised). A group of
two or more, or one that carries a suggestion, becomes a **proposal**:

- a **wording** change (copy): the words shown in that view replaced by better ones;
- an **assistant rule**: a sentence Ask Rihma keeps to (feedback on an assistant answer);
- a **prompt** change: a sentence added to what a Rihma agent is told (feedback on an agent's answer).

A person approves a proposal (with the final text, when nobody suggested one). An approved change is applied
through data files Rihmasto reads, never by editing code at run time: ``heal/wording.json`` (the cockpit replaces
the words in that view), ``heal/assistant_rules.json`` (Ask Rihma reads its rules in its snapshot) and
``heal/prompt_rules.json``. Each approval and rejection is recorded.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import incidents as inc
from kernel.people import PERSONAS, is_person
from kernel.store import Factory, read_json, updating_json

KINDS = ("unclear", "wrong")
CHANGES = ("wording", "assistant_rule", "prompt")
APPROVERS = ("product_owner", "business_owner", "it", "developer")
GROUP_AT = 2
FILES = {"wording": "wording.json", "assistant_rule": "assistant_rules.json", "prompt": "prompt_rules.json"}


class FeedbackRefused(ValueError):
    """Feedback or an approval the kernel will not take."""


def _path(factory: Factory) -> Any:
    return inc.heal_dir(factory) / "feedback.json"


def read(factory: Factory) -> dict[str, Any]:
    doc = read_json(_path(factory), None) or {}
    return {"items": list(doc.get("items") or []), "proposals": list(doc.get("proposals") or [])}


def _signs(person: str, persona: str) -> None:
    if not is_person(person) or persona not in PERSONAS:
        raise FeedbackRefused(f"{person!r} is not a person with a persona: feedback is signed")


def key_of(kind: str, where: dict[str, Any]) -> str:
    shown = re.sub(r"\s+", " ", str(where.get("text") or "").strip().lower())[:120]
    return "|".join([kind, str(where.get("view") or "-"), str(where.get("target") or where.get("control") or "-"),
                     shown])


def _change_of(where: dict[str, Any]) -> str:
    view = str(where.get("view") or "")
    if view == "assistant":
        return "assistant_rule"
    if view in ("agents", "channel"):
        return "prompt"
    return "wording"


def _check_given(kind: str, where: Any, words: str, suggest: str, person: str, persona: str) -> None:
    _signs(person, persona)
    if kind not in KINDS:
        raise FeedbackRefused(f"feedback is one of {', '.join(KINDS)}")
    if not isinstance(where, dict) or not (where.get("view") or where.get("text")):
        raise FeedbackRefused("say where: the view, and the words shown there")
    if not str(words or "").strip() and not str(suggest or "").strip():
        raise FeedbackRefused("say what is unclear or wrong, in your own words")


def _grouped(doc: dict[str, Any], group: list[dict[str, Any]], key: str, place: dict[str, Any], now: str,
             pid: str | None) -> dict[str, Any] | None:
    """The proposal a group joins (an open one) or opens (two notes, or one with better words), or None."""
    open_ = next((p for p in doc["proposals"] if p["key"] == key and p["state"] == "proposed"), None)
    suggestion = next((i["suggest"] for i in reversed(group) if i.get("suggest")), None)
    if open_ is not None:
        open_["items"] = [i["id"] for i in group]
        open_["text"] = open_.get("text") or suggestion
        return dict(open_)
    if len(group) < GROUP_AT and not suggestion:
        return None
    proposal = {"id": f"FP-{len(doc['proposals']) + 1:04d}", "key": key, "change": _change_of(place),
                "where": place, "from": place.get("text"), "text": suggestion, "items": [i["id"] for i in group],
                "state": "proposed", "opened": now, "project": pid}
    doc["proposals"].append(proposal)
    return proposal


def give(factory: Factory, *, kind: str, where: dict[str, Any], words: str, person: str, persona: str,
         suggest: str = "", project: str | None = None) -> dict[str, Any]:
    """Record one piece of feedback; group it, and open a proposal when its group is ready. Returns the item, with
    the proposal it opened or joined (if any)."""
    _check_given(kind, where, words, suggest, person, persona)
    pid = project if project and project != "_factory" else None
    if pid:
        factory.project(pid)
    place = {k: inc.mask_text(where[k], 300) for k in ("view", "control", "target", "text") if where.get(k)}
    key = key_of(kind, place)
    now = factory.clock.stamp()
    with updating_json(_path(factory), {"items": [], "proposals": []}) as doc:
        item = {"id": f"FB-{len(doc['items']) + 1:04d}", "kind": kind, "where": place,
                "words": inc.mask_text(words, 1000), "suggest": inc.mask_text(suggest, 500) if suggest else None,
                "person": person, "persona": persona, "project": pid, "at": now, "key": key}
        doc["items"].append(item)
        group = [i for i in doc["items"] if i["key"] == key]
        proposal = _grouped(doc, group, key, place, now, pid)
    inc.ledger_of(factory, pid).log("feedback_given", {"id": item["id"], "kind": kind, "view": place.get("view"),
                                                       "grouped": len(group), "proposal": (proposal or {}).get("id"),
                                                       "person": person, "persona": persona})
    return item | {"proposal": proposal, "group": len(group)}


def groups(factory: Factory) -> list[dict[str, Any]]:
    """Feedback grouped by what it is about, the largest first, each with its proposal."""
    doc = read(factory)
    out: dict[str, dict[str, Any]] = {}
    for i in doc["items"]:
        g = out.setdefault(i["key"], {"key": i["key"], "kind": i["kind"], "where": i["where"], "count": 0,
                                      "words": [], "items": []})
        g["count"] += 1
        g["items"].append(i["id"])
        g["words"] = (g["words"] + [i["words"]])[-5:]
    for g in out.values():
        g["proposal"] = next((p for p in reversed(doc["proposals"]) if p["key"] == g["key"]), None)
    return sorted(out.values(), key=lambda g: -g["count"])


def settle(factory: Factory, fpid: str, *, verdict: str, person: str, persona: str, text: str = "") -> dict[str, Any]:
    """A person approves (with the final text) or rejects a proposal. An approved one is applied to its data file."""
    from kernel.heal_approval import approvers, may_approve

    _signs(person, persona)
    if not may_approve(factory, person, persona, APPROVERS):   # or the solo person (kernel/heal_approval.py)
        raise FeedbackRefused(f"a wording, rule or prompt change is approved by {approvers(APPROVERS)}, "
                              f"not {persona}")
    if verdict not in ("approve", "reject"):
        raise FeedbackRefused("a proposal is approved or rejected")
    with updating_json(_path(factory), {"items": [], "proposals": []}) as doc:
        p = next((x for x in doc["proposals"] if x["id"] == fpid), None)
        if p is None:
            raise KeyError(f"no proposal {fpid}")
        if p["state"] != "proposed":
            raise FeedbackRefused(f"{fpid} is already {p['state']}")
        final = inc.mask_text(text.strip() or p.get("text") or "", 500)
        if verdict == "approve" and not final:
            raise FeedbackRefused("say the new wording, rule or prompt text: nobody suggested one")
        p.update(state="approved" if verdict == "approve" else "rejected", text=final or p.get("text"),
                 settled={"person": person, "persona": persona, "at": factory.clock.stamp()})
        out = dict(p)
    if verdict == "approve":
        _apply(factory, out, person)
    inc.ledger_of(factory, out.get("project")).log(
        "feedback_change_applied" if verdict == "approve" else "feedback_change_rejected",
        {"proposal": fpid, "change": out["change"], "view": out["where"].get("view"), "person": person,
         "persona": persona})
    return out


def _apply(factory: Factory, out: dict[str, Any], person: str) -> None:
    """An approved change into its data file, replacing an earlier one for the same words in the same view."""
    entry = {"proposal": out["id"], "view": out["where"].get("view"), "from": out.get("from"), "to": out["text"],
             "approved_by": person, "at": factory.clock.stamp()}
    with updating_json(inc.heal_dir(factory) / FILES[out["change"]], {"changes": []}) as doc:
        kept = [c for c in doc["changes"] if (c.get("view"), c.get("from")) != (entry["view"], entry["from"])]
        doc["changes"] = [*kept, entry]


def applied(factory: Factory, change: str) -> list[dict[str, Any]]:
    """The approved changes of one kind, as their data file holds them."""
    return list((read_json(inc.heal_dir(factory) / FILES[change], {}) or {}).get("changes") or [])
