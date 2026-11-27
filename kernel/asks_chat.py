"""Ask Rihma about machines, asks between agents and machines, and reachability, by rule (FR-XAG1, FR-RCH1).

- "what am I waiting on from other agents?", "open asks": the asks open or delivered across projects;
- "which machines do I have?", "list machines": the machines, how each is reached and its agents;
- "is the laptop reachable?", "test the connection to build-server", "can you reach github?": the doctor's verdict, its
  fix and, when not reachable, the drafted ask offered to send (kernel/reach.py; one read-only test, nothing kept);
- "ask the agent on laptop to run git status", "ask codex on build-server whether the tests pass": a proposal
  (``ask_put``) the person confirms, signed; the answer comes back into the agent channel;
- "the answer to AK-0002 is …": a proposal (``ask_answer``) to file it; "withdraw AK-0002": ``ask_withdraw``;
- "add the machine laptop, reached by ssh laptop, windows": ``machine_add``; "remove the machine laptop":
  ``machine_remove``.

Copying an ask for the other agent and making a reply link stay clicks beside the ask (the clipboard is the person's,
and a reply link is shown once): Ask Rihma takes the person there. It writes nothing itself.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import asks, machines, reach
from kernel.learn import FACTORY_PID

WAITING = re.compile(r"\b(?:what|which)\b.*\bwait\w*\b.*\b(?:other |another |remote )?agents?\b"
                     r"|\bopen asks?\b|\basks? (?:waiting|open)\b|\bwaiting on (?:other |the )?agents?\b", re.I)
# About the list itself ("which machines?", "list my machines"), never a question that only mentions a machine
# ("which data leaves the machine?" is about integrations).
LIST_MACHINES = re.compile(r"\b(?:which|what|list|show)\s+(?:are\s+)?(?:my\s+|our\s+|the\s+)?machines\b"
                           r"|\bmy machines\b|\bmachines\s+(?:do|have|are)\s+(?:i|we|there)\b", re.I)
REACH = re.compile(r"\b(?:is|are)\s+(?:the\s+|my\s+)?(?P<a>[\w.-]+)\s+(?:reachable|up|online|connected)\b"
                   r"|\b(?:test|check)\s+(?:the\s+)?(?:connection|ssh|reach)\s+(?:to|with|of)\s+(?:the\s+)?(?P<b>[\w.:/-]+)"
                   r"|\bcan (?:you|rihmasto|it) (?:reach|connect to)\s+(?:the\s+)?(?P<c>[\w.:/-]+)", re.I)
ASK = re.compile(r"\bask\s+(?:the\s+)?(?P<agent>[\w.-]+?)?\s*(?:agent\s+)?on\s+(?:the\s+)?(?P<machine>[\w.-]+)\s+"
                 r"(?:to\s+|whether\s+|if\s+|about\s+|:\s*)?(?P<text>.+)$", re.I | re.S)
ANSWER = re.compile(r"\b(?:the\s+)?answer\s+(?:to|for)\s+(?P<aid>AK-\d{4,6})\s*(?:is|was|:)\s*(?P<text>.+)$",
                    re.I | re.S)
WITHDRAW = re.compile(r"\b(?:withdraw|cancel|drop)\s+(?:the\s+ask\s+)?(?P<aid>AK-\d{4,6})\b", re.I)
ADD = re.compile(r"\badd\s+(?:a\s+|the\s+)?machine\s+(?:called\s+|named\s+)?(?P<name>[a-z0-9][\w.-]*)"
                 r"(?:.*?\b(?:ssh|alias)\s+(?P<address>[\w.@\\-]+))?(?:.*?\b(?P<os>windows|linux|macos|mac)\b)?", re.I)
REMOVE = re.compile(r"\b(?:remove|delete)\s+(?:the\s+)?machine\s+(?P<name>[a-z0-9][\w.-]*)", re.I)
GENERIC_AGENT = {"the", "an", "a", "my", "agent", "coding"}


def _out(answer: str, *, propose: list[dict[str, Any]] | None = None, nav: dict[str, Any] | None = None,
         steps: list[str] | None = None) -> dict[str, Any]:
    return {"answer": answer, "steps": [{"text": s, "action": "navigate"} for s in steps or []], "navigate": nav,
            "propose": propose or [], "dropped": [], "sources": [], "by": "rule", "matches": ["asks"]}


def _project_of(project: Any) -> Any:
    return project if project is not None and project.pid != FACTORY_PID else None


def _waiting(factory: Any) -> dict[str, Any]:
    s = asks.summary(factory)
    return _out(s["said"], nav={"route": "#/home", "control": "asks_waiting"})


def _machines(factory: Any) -> dict[str, Any]:
    rows = machines.listed(factory)
    if not rows:
        return _out(machines.describe(factory)["said"], nav={"route": "#/settings", "control": "machines_page"})
    lines = [f"{m['name']}: by {m['reach']}{' (' + m['address'] + ')' if m.get('address') else ''}, "
             f"{m.get('os', 'unknown')}{', agents ' + ', '.join(m['agents']) if m.get('agents') else ''}"
             for m in rows]
    return _out("Your machines (all projects share them): " + "; ".join(lines) + ".",
                nav={"route": "#/settings", "control": "machines_page"})


def _reach(factory: Any, project: Any, target: str, persona: str) -> dict[str, Any] | None:
    name = target.strip(" ?.!").lower()
    known = machines.get(factory, name) is not None or name == "github" or name.startswith("https://") or (
        name in {p.pid for p in factory.projects()})
    if not known:
        return None
    r = reach.doctor(factory, name)
    text = r["said"] + ("" if r.get("ok") else " To fix it: " + " ".join(f"({i}) {s}" for i, s in
                                                                           enumerate(r.get("fix") or [], 1)))
    props = []
    draft, here = r.get("draft"), _project_of(project)
    if draft and here is not None:
        props.append(_ask_prop(here, draft, persona))
        text += f" I drafted an ask to {draft['to']} on {draft['machine']} with these steps: confirm it to send."
    return _out(text, propose=props, nav={"route": "#/settings", "control": "reach_test"})


def _ask_prop(project: Any, d: dict[str, Any], persona: str) -> dict[str, Any]:
    return {"action": "ask_put", "why": f"Ask {d['to']}{' on ' + d['machine'] if d.get('machine') else ''}.",
            "persona": persona, "project": project.pid,
            "args": {"to": d["to"], "machine": d.get("machine"), "text": d["text"], "why": d.get("why") or "",
                     "expects": d.get("expects") or "", "source": d.get("source")}}


def _ask(factory: Any, project: Any, m: re.Match[str], persona: str) -> dict[str, Any] | None:
    machine = machines.get(factory, m.group("machine"))
    if machine is None:
        return None
    here = _project_of(project)
    if here is None:
        return _out(f"Open the project the ask is about, then ask again: an ask to the agent on {machine['name']} "
                    "lives in that project's agent channel.", nav={"route": "#/projects"})
    word = (m.group("agent") or "").lower()
    agent = word if word and word not in GENERIC_AGENT else (machine.get("agents") or ["coding-agent"])[0]
    text = " ".join(m.group("text").split()).rstrip("?")
    d = {"to": agent, "machine": machine["name"], "text": text, "why": "asked in Ask Rihma", "expects": ""}
    return _out(f"I'll put this to {agent} on {machine['name']}: \"{text}\". Confirm it, signed with your name; the "
                f"answer comes back into the agent channel. If nothing connects to {machine['name']}, copy it for the "
                "agent there from the ask.", propose=[_ask_prop(here, d, persona)],
                nav={"route": f"#/p/{here.pid}/agents", "control": "asks_list"})


def _answer(project: Any, m: re.Match[str], persona: str) -> dict[str, Any] | None:
    here = _project_of(project)
    if here is None:
        return None
    aid = m.group("aid").upper()
    text = m.group("text").strip()
    prop = {"action": "ask_answer", "why": f"File the answer to {aid}.", "persona": persona, "project": here.pid,
            "args": {"aid": aid, "text": text}}
    return _out(f"I'll file this as the answer to {aid}. Confirm it, signed with your name.", propose=[prop])


def _withdraw(project: Any, m: re.Match[str], persona: str) -> dict[str, Any] | None:
    here = _project_of(project)
    if here is None:
        return None
    aid = m.group("aid").upper()
    prop = {"action": "ask_withdraw", "why": f"Withdraw {aid}.", "persona": persona, "project": here.pid,
            "args": {"aid": aid}}
    return _out(f"I'll withdraw {aid}. Confirm it, signed with your name.", propose=[prop])


def _machine_add(factory: Any, m: re.Match[str], persona: str) -> dict[str, Any]:
    name = m.group("name").lower()
    address, said_os = m.group("address"), (m.group("os") or "").lower()
    system = {"mac": "macos"}.get(said_os, said_os)
    args = {"name": name, "reach": "ssh" if address else "hand", "address": address, "os": system or None}
    prop = {"action": "machine_add", "why": f"Add the machine {name}.", "persona": persona, "project": None,
            "args": {k: v for k, v in args.items() if v}}
    who = " or ".join(machines.editors(factory))
    return _out(f"I'll add the machine {name}" + (f", reached by ssh {address}" if address else ", reached by hand")
                + f". The machine list is kept by {who}; confirm it, signed with your name.", propose=[prop],
                nav={"route": "#/settings", "control": "machines_page"})


def _machine_remove(factory: Any, m: re.Match[str], persona: str) -> dict[str, Any] | None:
    name = m.group("name").lower()
    if machines.get(factory, name) is None:
        return None
    prop = {"action": "machine_remove", "why": f"Remove the machine {name}.", "persona": persona, "project": None,
            "args": {"name": name}}
    return _out(f"I'll remove the machine {name}; asks already sent there keep their record. Confirm it.",
                propose=[prop], nav={"route": "#/settings", "control": "machines_page"})


def _reach_q(factory: Any, project: Any, m: re.Match[str], persona: str) -> dict[str, Any] | None:
    return _reach(factory, project, m.group("a") or m.group("b") or m.group("c") or "", persona)


# In this order: the first pattern that matches and gets an answer wins.
RULES: tuple[tuple[re.Pattern[str], Any], ...] = (
    (ANSWER, lambda f, p, m, who: _answer(p, m, who)),
    (WITHDRAW, lambda f, p, m, who: _withdraw(p, m, who)),
    (ASK, _ask),
    (REMOVE, lambda f, p, m, who: _machine_remove(f, m, who)),
    (ADD, lambda f, p, m, who: _machine_add(f, m, who)),
    (WAITING, lambda f, p, m, who: _waiting(f)),
    (REACH, _reach_q),
    (LIST_MACHINES, lambda f, p, m, who: _machines(f)),
)


def answer(factory: Any, question: str, project: Any, persona: str) -> dict[str, Any] | None:
    q = " ".join(str(question or "").split())
    for pattern, handle in RULES if q else ():
        m = pattern.search(q)
        out = handle(factory, project, m, persona) if m else None
        if out:
            return out
    return None
