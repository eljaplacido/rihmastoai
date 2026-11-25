"""Ask Rihma about people and access (D-0024 item 4, FR-PPL1): the same moves Settings > People and access offers.

Read from the words alone (no model is needed, so it works in map mode too), each a proposal the person
confirms, carried out by the route its button would call:

- "switch to team mode" / "go back to just me": ``people_mode``;
- "add a user Bea Example as developer": ``people_add_user``;
- "map group 0b8e5c1a to operations": ``people_map_group``;
- "delegate operations to the ops agent" (in a project): ``people_delegate_agent``, for the kinds of card that
  persona decides and a delegation may cover, for a week at most;
- "who may decide C-3?": an answer, from kernel/team_access.py ``who_decides``.

None writes anything here; the words that do not ask for one of these go on to the assistant as before.
"""

from __future__ import annotations

import re
from typing import Any

from kernel.canon import CARD_DECIDERS
from kernel.delegation import NEVER

SETTINGS = {"route": "#/settings", "control": "people_access"}
_LABELS = {"business owner": "business_owner", "product owner": "product_owner", "concept evaluator":
           "concept_evaluator", "end user": "end_user", "developer": "developer", "operations": "operations",
           "ops": "operations", "stakeholder": "stakeholder", "compliance": "compliance"}
_TEAM = re.compile(r"\b(?:switch|turn|move|go|change|enable|start)\b.{0,40}\b(?:team mode|a team|organi[sz]ation)\b")
_SOLO = re.compile(r"\b(?:switch|turn|move|go|change|back)\b.{0,40}\b(?:solo|just me|on my own|single developer)\b")
_ADD = re.compile(r"\b(?:add|invite|create)\b(?: a| an| the)? (?:new )?(?:user|person|team ?member|teammate)\b(.*)")
_GROUP = re.compile(r"\bmap\b(?: the)? group\s+[\"']?([^\s\"']{1,256})[\"']?")
_AGENT = re.compile(r"\b(?:delegate|give|assign|hand)\b.{0,60}\bagent\b")
_WHO = re.compile(r"\bwho\b.{0,30}\b(?:decides?|decide|may|can|approves?)\b")
_CARD = re.compile(r"\bC-\d{1,9}\b", re.I)


def _persona(question: str) -> str | None:
    """The persona the words name: "IT" only in capitals, since "it" is a word."""
    if re.search(r"\bIT\b", question):
        return "it"
    low = question.lower()
    found = [(low.find(w), p) for w, p in _LABELS.items() if re.search(rf"\b{w}\b", low)]
    return min(found)[1] if found else None


def _name(rest: str) -> str | None:
    quoted = re.search(r"[\"“]([^\"”]{2,200})[\"”]", rest)
    if quoted:
        return quoted.group(1).strip()
    words = re.match(r"\s*(?:called|named)?\s*((?:[A-ZÀ-Þ][\w'-]+)(?:\s+[A-ZÀ-Þ][\w'-]+){0,3})", rest)
    return words.group(1).strip() if words else None


def _proposal(action: str, args: dict[str, Any], why: str, persona: str, pid: str | None) -> dict[str, Any]:
    return {"action": action, "args": args, "why": why, "persona": persona, "project": pid}


def _out(answer: str, propose: list[dict[str, Any]], match: str, navigate: dict | None = None) -> dict[str, Any]:
    return {"answer": answer, "navigate": navigate or SETTINGS, "propose": propose, "dropped": [], "sources": [],
            "by": "people", "matches": [match]}


def _mode(low: str, persona: str) -> dict[str, Any] | None:
    to = "team" if _TEAM.search(low) else "solo" if _SOLO.search(low) else None
    if to is None:
        return None
    words = ("Team mode turns personas into people and groups: you become the first user, with every persona, "
             "and every record stays. Then add users or map your identity provider's groups."
             if to == "team" else "Solo mode: one person acts in every persona again; every record stays.")
    return _out(words, [_proposal("people_mode", {"mode": to}, words, persona, None)], "people_mode")


def _add_user(question: str, persona: str) -> dict[str, Any] | None:
    m = _ADD.search(question.lower())
    if m is None:
        return None
    rest = question[len(question) - len(m.group(1)):]
    name, role = _name(rest), _persona(rest) or "stakeholder"
    if not name:
        return _out("Name the person, as in “add a user Bea Example as developer”, or add them in Settings, "
                    "People and access.", [], "people_add_user")
    words = f"Add {name} as a user with the {role.replace('_', ' ')} persona on every project, then send an invite."
    return _out(words, [_proposal("people_add_user", {"name": name, "personas": [role]}, words, persona, None)],
                "people_add_user")


def _group(question: str, persona: str) -> dict[str, Any] | None:
    m = _GROUP.search(question) or _GROUP.search(question.lower())
    if m is None:
        return None
    to = _persona(question[m.end():]) or _persona(question)
    if to is None:
        return _out("Say which persona the group maps to, as in “map group <id> to operations”.", [],
                    "people_map_group")
    words = f"Map the provider's group {m.group(1)} to {to.replace('_', ' ')} on every project."
    return _out(words, [_proposal("people_map_group", {"group": m.group(1), "to": to}, words, persona, None)],
                "people_map_group")


def _agent(question: str, persona: str, pid: str | None) -> dict[str, Any] | None:
    low = question.lower()
    if not _AGENT.search(low):
        return None
    given = _persona(question)
    name = re.search(r"\bto (?:the |our |an? )?([a-z0-9][a-z0-9._-]{0,30})(?: agent)?\b", low)
    agent = (name.group(1) if name else "agent").removesuffix("-agent") + "-agent"
    if given is None or pid is None:
        return _out("Open the project, then say which persona and which agent, as in “delegate operations to the "
                    "ops agent”. It decides only the kinds of card you give it, until the date you set.", [],
                    "people_delegate_agent")
    kinds = [k for k, who in CARD_DECIDERS.items() if given in who and k not in NEVER and k != "question"]
    if not kinds:
        return _out(f"A {given.replace('_', ' ')} decides no kind of card a delegation may cover.", [],
                    "people_delegate_agent")
    words = (f"{given.replace('_', ' ')}: delegated to {agent} for a week, deciding {', '.join(kinds)} cards on "
             "this project and nothing else.")
    args = {"persona": given, "agent": agent, "agent_kind": "bridge", "kinds": kinds, "until": "7d"}
    return _out(words, [_proposal("people_delegate_agent", args, words, given, pid)], "people_delegate_agent")


def _who(factory: Any, question: str, pid: str | None) -> dict[str, Any] | None:
    card = _CARD.search(question)
    if not _WHO.search(question.lower()) or card is None or pid is None:
        return None
    from kernel.team_access import who_decides

    try:
        said = who_decides(factory, pid, card.group(0).upper())
    except KeyError:
        return None
    return _out(said["text"], [], "people_who", {"route": f"#/p/{pid}/inbox", "control": None})


def answer(factory: Any, project: Any, question: str, *, persona: str) -> dict[str, Any] | None:
    """Ask Rihma's answer to words about people and access, or None for words about something else."""
    pid = project.pid if project is not None else None
    if re.match(r"\s*(?:where|how)\b", question.lower()):     # where a control is: the map answers that
        return _who(factory, question, pid)
    return (_who(factory, question, pid) or _agent(question, persona, pid) or _mode(question.lower(), persona)
            or _add_user(question, persona) or _group(question, persona))
