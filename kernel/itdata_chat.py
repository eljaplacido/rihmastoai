"""Ask Rihma about integrations and data (FR-ITD1), by rule and without a model, with Take me there.

- "What does this project connect to?" (and "which systems", "what integrations"): every connection by kind, with
  its state and where it is, from the project's view (kernel/itdata_project.py), or the platform's outside a project;
- "Which data leaves the machine?" (and "what is sent outside", "egress"): each connection data may leave this
  machine and your network through, what goes there and why, a confidential project's refused endpoints said;
- "Where are the credentials?": each credential by name, where it lives and whether it is set here, never a value;
- "Check the integrations", "turn off relay SUB-001", "remind me to rotate ORDERS_TOKEN in 30 days": a proposal of
  the same signed write the buttons make (kernel/assistant_ops.py), which runs only when the person confirms it.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import itdata as it

CONNECT = ("what integrations", "which integrations", "which systems", "what systems", "integrations and data",
           "data connections", "what connections", "which connections", "on yhteydessä", "integraatiot")
# "What does this project connect to?": the words end the question. "How do I connect to Teams?" is a how-to (the
# map answers it), never this list.
CONNECT_Q = re.compile(r"\b(?:what|which)\b[^?.!]{0,60}\bconnect(?:s|ed)?\s+(?:to|with)\s*(?:[?.!]|$)", re.IGNORECASE)
HOW_TO = re.compile(r"^\s*(?:how\b|can (?:i|we)\b|where do (?:i|we)\b|miten\b|kuinka\b)", re.IGNORECASE)
LEAVE = ("leaves the machine", "leave the machine", "leaving the machine", "leaves this machine", "leave this machine",
         "data leave", "data leaves", "sent outside", "send outside", "goes outside", "go outside",
         "leaves our network", "leave our network", "egress", "lähtee koneelta", "lähtee ulos")
CREDS = ("where are the credentials", "which credentials", "what credentials", "where are the secrets",
         "where are the keys", "which secrets", "credentials does", "tunnukset")
CHECK = re.compile(r"\bcheck\b[^?.!]{0,30}\b(integrations?|connections?|data connections?)\b", re.IGNORECASE)
# "stop SUB-001 from failing" asks for a fix, not to turn it off: an id followed by "from" is not this
OFF = re.compile(r"\b(?:disable|turn off|switch off|stop)\b[^?.!]{0,40}?\b((?:relay|hook|connector):[\w.-]+|SUB-\d+)"
                 r"(?![\w.-])(?!\s+(?:from|failing)\b)", re.IGNORECASE)
ROTATE = re.compile(r"\brotat\w*\b[^?.!]*?\b([A-Z][A-Z0-9_]{2,80})\b(?:[^?.!]*?\bin\s+(\d{1,3})\s+days?)?")
_WORD = re.compile(r"\s+")
VIEW_CONTROL = "itdata_map"


def _has(question: str, phrases: tuple[str, ...]) -> bool:
    low = _WORD.sub(" ", question.lower())
    return any(p in low for p in phrases)


def _route(project: Any) -> str:
    return f"#/p/{project.pid}/itdata" if project is not None else "#/connections"


def _view(factory: Any, project: Any) -> dict[str, Any]:
    from kernel import itdata_project as ip

    return ip.project_view(project) if project is not None else ip.platform_view(factory, stores=False)


def _out(answer: str, project: Any, control: str = VIEW_CONTROL, propose: list | None = None) -> dict[str, Any]:
    route = _route(project)
    open_it = {"action": "open", "args": {"route": route}, "why": "See every connection, check it, turn it off or set "
               "a rotation reminder from there", "project": project.pid if project is not None else None}
    return {"answer": answer, "navigate": {"route": route, "control": control}, "propose": [open_it, *(propose or [])],
            "dropped": [], "sources": [], "by": "map", "matches": ["itdata"]}


def _scope(project: Any) -> str:
    return str(project.meta.get("title") or project.pid) if project is not None else "The platform"


def _line(x: dict[str, Any]) -> str:
    return f"{x['label']} ({x['state']}, {x['locality']})"


def connects(view: dict[str, Any], project: Any) -> str:
    items = view["items"]
    if not items:
        return f"{_scope(project)} connects to nothing yet."
    parts = []
    for kind, label in it.KIND_LABEL.items():
        mine = [x for x in items if x["kind"] == kind]
        if mine:
            parts.append(f"{label}: " + "; ".join(_line(x) for x in mine))
    return f"{_scope(project)}: {view['summary']['line']} " + ". ".join(parts) + "."


def _why_leaves(x: dict[str, Any]) -> str:
    what = ", ".join(x["data_classes"]) or "data"
    where = f"to {x['host']}" if x.get("host") else ("to an address not known here" if x["locality"] == it.UNKNOWN
                                                     else "outside")
    roles = f" for the {it.role_words(x['roles'])}" if x.get("roles") else ""
    return f"{x['label']}: {what} {where}{roles}"


def _blocked(view: dict[str, Any]) -> str:
    """A confidential project's roles whose own model is hosted: blocked, never working locally (FR-ITD2)."""
    blocked = [a["label"] for a in view.get("agents") or [] if a.get("blocked")]
    if not blocked:
        return ""
    return (f" So {', '.join(blocked)} {'is' if len(blocked) == 1 else 'are'} blocked here, not working locally: "
            "each needs a model on this machine or your network, set in Models setup.")


def leaving(view: dict[str, Any], project: Any) -> str:
    out = [x for x in view["items"] if it.leaves(x)]
    refused = [x["label"] for x in view["items"] if x.get("refused")]
    head = f"{_scope(project)}: "
    text = (head + "data may leave this machine and your network through " + str(len(out)) + " connection"
            + ("s" if len(out) != 1 else "") + ": " + "; ".join(_why_leaves(x) for x in out) + "."
            if out else head + "nothing sends data outside this machine and your network.")
    if refused:
        text += f" This project is confidential, so these are never called for it: {', '.join(refused)}."
    text += _blocked(view)
    unknown = [x["label"] for x in out if x["locality"] == it.UNKNOWN]
    if unknown:
        text += (f" Where {', '.join(unknown)} send is not known here: its address is in a variable not set where "
                 "Rihmasto runs.")
    return text


def creds(view: dict[str, Any], project: Any) -> str:
    rows = view["credentials"]
    if not rows:
        return f"{_scope(project)} names no credential: nothing it connects to needs one."
    said = {True: "set here", False: "NOT set here", None: "not readable from here"}
    parts = [f"{c['name']} ({c['where']}, {said[c['set']]})" for c in rows]
    return (f"{_scope(project)} names {len(rows)} credential" + ("s" if len(rows) != 1 else "")
            + ", by name only (a value is never read or shown): " + "; ".join(parts) + ".")


def _act(factory: Any, op: str, args: dict[str, Any], persona: str, project: Any, summary: str) -> list:
    from kernel import assistant_ops

    full = {**args, **({"project": project.pid} if project is not None else {})}
    found = assistant_ops.proposal(factory, op, full, persona=persona, summary=summary)
    return [found | {"why": summary}] if found else []


def _item_id(view: dict[str, Any], said: str) -> str | None:
    said = said if ":" in said else "relay:" + said.upper()
    return next((x["id"] for x in view["items"] if x["id"].lower() == said.lower()), None)


def _doing(factory: Any, question: str, project: Any, persona: str) -> dict[str, Any] | None:
    """A proposal for check, turn off or a rotation reminder, when the words ask for one."""
    if CHECK.search(question):
        return _out("I can check every connection here now: what is missing, and whether each address answers and "
                    "how fast. You confirm it, signed with your name.", project, "itdata_check",
                    _act(factory, "check_integrations", {}, persona, project, "Check the integrations now"))
    off, rot = OFF.search(question), ROTATE.search(question)
    if off:
        view = _view(factory, project)
        iid = _item_id(view, off.group(1))
        if iid is None:
            return _out(f"I found no connection {off.group(1)} here. The view lists each one's id.", project)
        wide = (next(x for x in view["items"] if x["id"] == iid).get("disable") or {}).get("wide")
        warn = f" Before you confirm: {wide}, and it is signed with your IT access on the platform." if wide else ""
        return _out(f"I can turn {iid} off; IT confirms it, signed, and it is recorded.{warn}", project,
                    "itdata_disable", _act(factory, "disable_connection", {"item": iid}, persona, project,
                                           f"Turn {iid} off" + (" for every project it serves" if wide else "")))
    if rot and ("remind" in question.lower() or "rotation" in question.lower()):
        days = int(rot.group(2) or 90)
        return _out(f"I can set a reminder to rotate {rot.group(1)} in {days} days; you confirm it, signed.", project,
                    "itdata_rotate", _act(factory, "remind_rotation", {"credential": rot.group(1), "days": days},
                                          persona, project, f"Remind to rotate {rot.group(1)}"))
    return None


IT_READERS = ("it", "operations", "ai_architect")   # whose view Integrations and data is (cockpit/static/capsules.js)


def answer(factory: Any, question: str, project: Any, persona: str) -> dict[str, Any] | None:
    """The answer by rule, or None when the question is about something else."""
    if project is not None and str(project.pid).startswith("_"):
        project = None
    doing = _doing(factory, question, project, persona)
    if doing is not None:
        return doing
    if persona not in IT_READERS:                   # IT's view: another persona asking is answered by its own view
        return None
    how_to = bool(HOW_TO.match(question))          # "how do I connect to GitHub?": the map's how-to answers it
    for asked, say, control in ((_has(question, LEAVE), leaving, "itdata_flow"),
                                (_has(question, CREDS), creds, "itdata_rotate"),
                                (not how_to and (_has(question, CONNECT) or bool(CONNECT_Q.search(question))),
                                 connects, VIEW_CONTROL)):
        if asked:
            return _out(say(_view(factory, project), project), project, control)
    return None
