"""Ask Rihma about agent operations (FR-AOP1), by rule and without a model, as the project status is.

"How much do my agents cost?", "where can I cut tokens?", "which tool is slow?", "is the agents' context out of
date?" and "what is the harness overhead?" are answered from the same read model as the Agent operations view
(kernel/agentops.py), for the open project or across the platform, with Take me there to the view. A question
about cutting tokens or costs answers with the Optimise audit's top proposals and offers, for a person to confirm,
to file the largest one as a change and to record the audit (kernel/assistant_ops.py operations). Every figure that
is not measured says so, with how to measure it. The assistant itself writes nothing.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import agentops_actions as ops
from kernel.insights.base import compact

# Narrow on purpose (FR-AOP2): these are answered before the model sees the question, so each pattern names the
# agents' tokens, costs or context together; "save the context of this project" or "what does the AI architect
# persona do" reach the model.
AI = r"(?:agents?'?|ai|models?'?|llms?)"
COST = re.compile(r"\b(?:how much|what) (?:do|does|did|are|is)\b.{0,30}\b(?:agents?|ai|models?)\b.{0,20}\b(?:cost|spend"
                  r"|costing)|\bagents?'? (?:cost|costs|spend|spending|token usage|tokens)\b|"
                  r"\btoken (?:usage|use|spend|cost)\b|\bagent operations (?:figures|numbers|costs?|summary)\b|"
                  r"\bpaljonko agentit maksa")
VERB = r"\b(?:cut|reduce|save|lower|trim|optimi[sz]e|shrink)\b"
CUT = re.compile(VERB + r".{0,40}(?:\btokens\b|\btoken (?:usage|use|spend|cost|count)s?\b)|"
                 + VERB + r".{0,40}\b" + AI + r"(?:\W+\w+)?\W+(?:costs?|spend|spending|bills?|context|usage)\b|"
                 + VERB + r".{0,30}\b(?:costs?|spend|spending)\b (?:of|for|on) (?:my |our |the )?" + AI + r"(?!\w)|"
                 + VERB + r".{0,30}\bcontext (?:packs?|tokens|size|windows?)\b|"
                 r"\boptimi[sz]e (?:my |our |the )?agents?\b")
SLOW = re.compile(r"\b(?:which|what) tools?\b.{0,30}\b(?:slow|slowest|latency|lag)|\btool latency\b|"
                  r"\bslow(?:est)? tools?\b|\btools? (?:is|are) slow\b")
DRIFT = re.compile(r"\bcontext drift\b|\b(?:stale|out of date|outdated) context\b|\bharness overhead\b|"
                   r"\bwhat (?:are|were) (?:my |the )?agents given\b")
VIEW = "agentops"


def asks(question: str) -> str | None:
    """Which question about agent operations this is (cut, slow, drift, cost), or None."""
    low = " ".join(question.lower().split())
    for name, rx in (("cut", CUT), ("slow", SLOW), ("drift", DRIFT), ("cost", COST)):
        if rx.search(low):
            return name
    return None


def _out(answer: str, route: str, *, control: str | None = None, propose: list | None = None) -> dict:
    return {"answer": answer, "navigate": {"route": route, "control": control}, "propose": propose or [],
            "dropped": [], "sources": [], "by": "map", "matches": [VIEW]}


def _money(v: float | None, currency: str = "USD") -> str:
    return "not measured" if v is None else f"{v:,.4f} {currency}".replace(".0000 ", " ")


def _where(view: dict[str, Any]) -> str:
    return (f"for {view['projects'][0]['title']}" if view["project"] else "across your projects") + \
        f" over {view['window_words']}"


def _cost(view: dict[str, Any]) -> str:
    t = view["totals"]
    if not t["runs"]:
        return f"No agent run was recorded {_where(view)}: not measured. How: {view['how_runs']}."
    roles = "; ".join(f"{r['role']} ({r['harness']}, {r['model']}): {r['runs']} runs, "
                      f"{compact(r['tokens'])} tokens, cost {_money(r['cost'], r['currency'])}"
                      for r in view["by_role"][:4])
    cost = _money(t["cost"], t["currency"])
    if t["cost"] is None and t["cost_priced"] is not None:
        cost += f" ({_money(t['cost_priced'], t['currency'])} priced; {t['unpriced']} runs have no price)"
    gaps = " ".join(f"Not measured: {g['what']}: {g['why']}. How: {g['how']}." for g in view["gaps"][:2])
    return (f"Your agents {_where(view)}: {t['runs']} runs, {compact(t['tokens'])} tokens "
            f"({compact(t['in'])} in, {compact(t['out'])} out), cost {cost}. By role: {roles}. {gaps}").strip()


def _saving(s: dict[str, Any]) -> str:
    parts = [f"{compact(s['tokens'])} tokens" if s.get("tokens") is not None else None,
             _money(s["cost"], s.get("currency") or "USD") if s.get("cost") is not None else None,
             f"{s['seconds']:g} s" if s.get("seconds") is not None else None,
             f"{s['per_call']:,} tokens per call" if s.get("tokens") is None and s.get("per_call") else None]
    return ", ".join(x for x in parts if x) or "not measured"


def _cut(view: dict[str, Any]) -> str:
    found = view["proposals"]
    if not found:
        return (f"The Optimise audit {_where(view)} proposes nothing: no pack over its budget or said twice, no "
                "prefix to cache, no cheaper model the role evals allow, no slow tool and no task with many rounds.")
    s = view["savings"]
    top = "; ".join(f"{i + 1}. {p['title']} (saves {_saving(p['saving'])})" for i, p in enumerate(found[:3]))
    return (f"The Optimise audit {_where(view)} finds {len(found)} ways to save: {top}. Together: "
            f"{compact(s['tokens'])} tokens, cost {_money(s['cost'])}.")


def _slow(view: dict[str, Any]) -> str:
    t = view["tools"]
    if not t["measured"] or not t["timed"]:
        gap = next((g for g in view["gaps"] if g["what"] in ("tools", "tool latency")), None)
        why = f"{gap['why']}. How: {gap['how']}" if gap else "nothing recorded"
        return f"Tool latency {_where(view)}: not measured: {why}."
    timed = [x for x in t["tools"] if x["median_ms"] is not None][:3]
    said = "; ".join(f"{x['tool']}: median {x['median_ms'] / 1000:.1f} s, 90th percentile "
                     f"{(x['p90_ms'] or 0) / 1000:.1f} s over {x['timed']} calls" for x in timed)
    return f"The slowest tools {_where(view)}: {said}."


def _drift(view: dict[str, Any]) -> str:
    behind = [d for d in view["drift"] if d["state"] == "behind"]
    over = [o for o in view["overhead"]["roles"] if o["system_share"] is not None][:3]
    first = (f"Context drift {_where(view)}: {len(behind)} of {len(view['drift'])} agent roles last ran before "
             "records they were not given" if view["drift"] else
             f"Context drift {_where(view)}: not measured: no agent ran yet. How: {view['how_runs']}")
    if behind:
        first += ": " + "; ".join(f"{d['role']} in {d['title']} ({d['changes_since']} since)" for d in behind[:3])
    lines = [first]
    if over:
        lines.append("Harness overhead (the system prompt's share of what a role is given): "
                     + "; ".join(f"{o['role']} {o['system_share']:g}%" for o in over))
    else:
        ctx = view.get("context") or {}
        why = ctx.get("why") or "no context pack was read"
        lines.append(f"Harness overhead: not measured: {why}. How: {ctx.get('how') or view['how_runs']}")
    return ". ".join(lines) + "."


ANSWER = {"cost": _cost, "cut": _cut, "slow": _slow, "drift": _drift}


def _proposals(factory: Any, view: dict[str, Any], persona: str, project: Any) -> list[dict[str, Any]]:
    from kernel import assistant_ops

    out = []
    top = next((p for p in view["proposals"] if p["project"] and not p.get("card")), None)
    if top is not None and persona in ops.opt.AUDITORS:
        out.append(assistant_ops.proposal(factory, "file_agent_optimisation", {"project": top["project"],
                                          "proposal": top["id"]}, persona=persona, project=project,
                                          summary=f"File as a change: {top['title']}"))
    if persona in ops.opt.AUDITORS:
        out.append(assistant_ops.proposal(factory, "record_agent_ops_audit",
                                          {"project": view["project"]} if view["project"] else {}, persona=persona,
                                          project=project, summary="Record the Optimise audit in the ledger"))
    return [p for p in out if p]


def answer(factory: Any, question: str, project: Any, persona: str,
           holding: tuple[str, ...] | None = None) -> dict | None:
    """The answer by rule, or None when the question is not about agent operations."""
    from kernel import agentops_price_chat

    if persona not in ops.opt.AUDITORS and holding:
        persona = next((p for p in ops.opt.AUDITORS if p in holding), persona)
    priced = agentops_price_chat.answer(factory, question, project, persona)     # pricing a model (FR-AOP2)
    kind = asks(question) if priced is None else None
    if kind is None:
        return priced
    pid = project.pid if project is not None and not project.pid.startswith("_") else None
    view = ops.read(factory, pid=pid, window="30d", context=kind in ("cut", "drift"))   # packs: the overhead
    route = f"#/p/{pid}/{VIEW}" if pid else "#/agentops"
    control = {"cut": "agent_ops_audit", "slow": "agent_ops_drill"}.get(kind, "agent_ops_window")
    propose = _proposals(factory, view, persona, project) if kind == "cut" else []
    return _out(ANSWER[kind](view), route, control=control, propose=propose)
