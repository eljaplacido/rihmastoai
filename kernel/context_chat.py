"""Ask Rihma about the data and context layer (FR-CTX1, chat parity with the Context view).

Two kinds of question are answered from the context packs themselves (kernel/context_packs.py), with no model:

- **what an agent sees**: "what does the verifier get for T-003?", "what is the builder given?", "show me the
  spec's context": the pack's size against its budget, its largest parts, what was cut and what was left out and
  why, with Take me there to the project's Context view;
- **why Rihma did not know something**: "why didn't Rihma know about the night shift?": whether the words are in
  any agent's pack, in the project's records but in no pack (and why: a cut, an exclusion), or nowhere in the
  records, so no agent could know them.

Anything else returns None, and Ask Rihma answers as before (kernel/assistant.py, through kernel/copilot.py's hook).
"""

from __future__ import annotations

import re
from typing import Any

from kernel import context_packs as packs

ROLE_WORDS = (("verifier", "verifier"), ("builder", "builder"), ("envelope", "builder"), ("holdout", "holdout_author"),
              ("spec", "spec"), ("panel", "intake"), ("intake", "intake"), ("perspective", "intake"),
              ("ask rihma", "assistant"), ("assistant", "assistant"), ("goal", "goal"), ("channel", "channel"),
              ("hand-off", "handoff"), ("handoff", "handoff"), ("mcp", "mcp"), ("tool", "mcp"))
SEES = re.compile(r"\b(gets?|sees?|given|receives?|reads?|context|prompt|pack|sent|knows?)\b")
ASKS = re.compile(r"^\s*(what|which|how much|how big|show|explain|mitä|näytä)\b|\?\s*$")
WHY_NOT = re.compile(r"\bwhy (?:didn'?t|did not|doesn'?t|does not|don'?t|wasn'?t|isn'?t)\s+(?:rihma|it|the \w+|you)\s+"
                     r"(?:know|see|get|have|read|mention|use)\s+(?:about\s+|of\s+)?(?P<x>.+?)\s*[?.!]*\s*$", re.I)
WHERE = re.compile(r"^\s*(where|missä|mistä)\b")    # "where do I see ..." is the map's: a way to a view
TASK = re.compile(r"\bT-\d{3,4}\b")
ROUTE = "#/p/{pid}/context"


def asks_pack(question: str) -> str | None:
    """The pack a question asks about ("what does the verifier get"), or None."""
    low = question.lower()
    if WHERE.match(low) or WHY_NOT.search(question) or not SEES.search(low) or not ASKS.search(low):
        return None
    return next((pack for word, pack in ROLE_WORDS if re.search(rf"\b{re.escape(word)}", low)), None)


def _parts_line(p: dict[str, Any]) -> str:
    big = sorted(p["parts"], key=lambda x: -x["chars"])[:3]
    return ", ".join(f"{x['name'].lower()} ({x['chars']:,})" for x in big)


def pack_answer(factory: Any, project: Any, pack_id: str, question: str, persona: str | None) -> dict[str, Any]:
    target = (TASK.search(question) or [None])[0] if pack_id in ("builder", "verifier") else None
    nav = {"route": ROUTE.format(pid=project.pid), "control": "context_pack"}
    try:
        p = packs.build(factory, project, pack_id, target=target, persona=persona)
    except packs.Unavailable as exc:
        return _shaped(f"The {packs.LABELS[pack_id]} has no context pack here yet: {exc}.", nav, project, pack_id)
    within = "over" if p["over_budget"] else "within"
    task = f" for {p['target']}" if p.get("target") and pack_id in ("builder", "verifier") else ""
    head = (f"The {p['label']}{task} "
            f"gets {p['chars']:,} characters, about {p['with_system']['tokens']:,} tokens with its system prompt, "
            f"{within} its {p['budget']['tokens']:,}-token budget. Its largest parts: {_parts_line(p)}.")
    cut = " Compressed: " + "; ".join(f"{c['what']} ({c['how']})" for c in p["compressed"][:2]) + "." \
        if p["compressed"] else ""
    left = " Left out: " + "; ".join(f"{e['what']} ({e['why']})" for e in p["excluded"][:3]) + "." \
        if p["excluded"] else ""
    cache = f" {round(p['prefix']['ratio'] * 100)}% of it is a prefix a prompt cache can reuse between calls."
    out = _shaped(head + cut + left + cache, nav, project, pack_id)
    out["context"] = {k: p[k] for k in ("id", "label", "target", "chars", "tokens", "over_budget", "prefix")}
    return out


def _records_text(project: Any) -> dict[str, str]:
    """The project's records an agent's context is built from, as text, by where they are."""
    import json

    from kernel.canon import Canon

    canon = Canon(project)
    return {"the request (source.json)": str((project.read("source.json", None) or {}).get("text") or ""),
            "the brief": canon.brief,
            "the questions and assumptions": json.dumps([canon.questions(), canon.assumptions()], ensure_ascii=False),
            "the spec": json.dumps(project.read("spec.json", None) or {}, ensure_ascii=False),
            "the contract": json.dumps(project.read("contract.json", None) or {}, ensure_ascii=False),
            "the material map": json.dumps(project.read("material.json", None) or {}, ensure_ascii=False)}


def why_not_answer(factory: Any, project: Any, term: str, persona: str | None) -> dict[str, Any]:
    term = term.strip().strip("\"'“”").removeprefix("the ").strip()
    nav = {"route": ROUTE.format(pid=project.pid), "control": "context_pack"}
    built = [p for p in packs.every(factory, project, persona=persona) if "unavailable" not in p]
    needle = term.lower()
    carry = [p["label"] for p in built if needle in p["text"].lower()]
    held = [where for where, text in _records_text(project).items() if needle in text.lower()]
    if carry:
        rest = [p["label"] for p in built if p["label"] not in carry]
        said = (f"“{term}” is in what Rihma's agents are given: {', '.join(carry)}."
                + (f" It is not in {', '.join(rest)}." if rest else ""))
    elif held:
        cuts = [f"{c['what']}: {c['how']}" for p in built for c in p["compressed"]][:2]
        said = (f"“{term}” is in {', '.join(held)}, but in no agent's context pack."
                + (f" What was compressed: {'; '.join(cuts)}." if cuts else "")
                + " The Context view shows each pack's parts and what it leaves out.")
    else:
        said = (f"“{term}” is not in this project's records: no request, brief, question, spec, contract or material "
                "mentions it, so no agent could know it. Add it as material, or say it in a change or an answer.")
    out = _shaped(said, nav, project, None)
    out["context"] = {"term": term, "in_packs": carry, "in_records": held}
    return out


def _shaped(answer: str, nav: dict[str, Any], project: Any, pack_id: str | None) -> dict[str, Any]:
    return {"answer": answer, "navigate": nav, "propose": [], "dropped": [], "sources": [project.pid],
            "by": "context", "matches": [m for m in ("context", pack_id) if m]}


def answer(factory: Any, project: Any, question: str, persona: str | None = None) -> dict[str, Any] | None:
    """Ask Rihma's answer to a question about what an agent sees or did not know; None for anything else."""
    if project is None or project.pid.startswith("_"):
        return None
    why = WHY_NOT.search(question)
    if why:
        return why_not_answer(factory, project, why.group("x"), persona)
    pack_id = asks_pack(question)
    return pack_answer(factory, project, pack_id, question, persona) if pack_id else None
