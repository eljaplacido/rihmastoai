"""Ask Rihma proposes a plain request by rule, with no model (FR-SET1, UI and chat parity).

On a home with no model (the demo, ``--assistant map``) a request to act used to get "I can only point the way".
A request that names one control unambiguously is read by rule instead, into the same confirm-to-run proposal a
model would make: the control's chat path in kernel/parity.py ``CHAT`` (an assistant action or an ``act``
operation) with arguments read from the words and the project's own records:

- pause (the reason after "because"), resume; a theme (dark, light or system, an accent, the density, corners);
- let Rihma assume (a Q-id or C-id named, else the open questions), answer a question ("answer Q-001: text");
  decide a card ("approve C-0003"), report a change ("report a change: text");
- an operation that needs nothing (build the capability pack, assess, check the destinations...); run or disable a
  check (each enabled check, or the one named); enable a check named; log a signal ("log a signal: text"); accept
  or dismiss the suggested automations.

Each proposal is checked as a model's is (kernel/assistant_rules.py ``check_proposal``) before a person sees it,
and it runs only when that person confirms it, signed. Anything not read here keeps pointing the way.
"""

from __future__ import annotations

import re
from typing import Any

LIMIT = 4
_REASON = re.compile(r"\b(?:because|since|reason:?)\s+(.{3,200})", re.I)
_AFTER_COLON = re.compile(r"[:—-]\s*(.{3,})$")
_QID, _CID = re.compile(r"\bQ-\d+\b", re.I), re.compile(r"\bC-\d+\b", re.I)
_THEME_WORDS = {"mode": ("dark", "light", "system"), "density": ("compact", "comfortable"),
                "radius": ("soft", "crisp"), "accent": ("amber", "teal", "violet", "blue", "green", "rose")}
_VERDICT_WORDS = {"approve": "approve", "approved": "approve", "accept": "accept", "reject": "reject",
                  "refuse": "refuse", "defer": "defer", "decline": "decline", "validate": "validate",
                  "park": "park", "acknowledge": "acknowledge", "retry": "retry", "stop": "stop", "keep": "keep"}
# Operations that take nothing but the project: proposed as asked. A watch needs its parts chosen beside it.
_BARE_OPS_SKIP = {"set_watch"}


def _said(question: str) -> str:
    return " ".join(question.rsplit("\n\nNow: ", 1)[-1].split())


def _text_after(question: str) -> str | None:
    m = _AFTER_COLON.search(_said(question))
    return m.group(1).strip() if m else None


def _theme(question: str) -> dict[str, Any] | None:
    said = set(re.findall(r"[a-z]+", question.lower()))
    settings = {k: next(v for v in values if v in said) for k, values in _THEME_WORDS.items() if said & set(values)}
    return {"settings": settings} if settings else None


def _questions(project: Any, question: str) -> list[str]:
    from kernel.canon import Canon

    canon = Canon(project)
    named = [q.upper() for q in _QID.findall(question)]
    for cid in (c.upper() for c in _CID.findall(question)):
        try:
            qid = (canon.get_card(cid).get("refs") or {}).get("question")
        except (KeyError, OSError):
            qid = None
        named += [qid] if qid else []
    return named or [q["id"] for q in canon.questions("open")]


def _decide(project: Any, question: str) -> list[dict[str, Any]]:
    from kernel.canon import Canon

    said = re.findall(r"[a-z_]+", question.lower())
    verdict = next((_VERDICT_WORDS[w] for w in said if w in _VERDICT_WORDS), None)
    out = []
    for cid in {c.upper() for c in _CID.findall(question)}:
        try:
            card = Canon(project).get_card(cid)
        except (KeyError, OSError):
            continue
        if verdict in card.get("verdicts", ()):
            out.append({"card": cid, "verdict": verdict, "reason": (_REASON.search(question) or [None, ""])[1]})
    return out


def action_args(name: str, project: Any, question: str) -> list[dict[str, Any]]:
    """The arguments of an assistant action read from the words, one set per proposal; [] when not read."""
    if name == "theme":
        return [theme] if (theme := _theme(question)) else []
    if project is None:
        return []
    if name == "pause":
        m = _REASON.search(question)
        return [{"reason": m.group(1).strip() if m else "asked in Ask Rihma"}]
    if name == "resume":
        return [{}]
    if name == "let_rihma_assume":
        return [{"question": q} for q in _questions(project, question)]
    if name == "answer_question":
        m = re.search(r"\b(Q-\d+)\b\s*[:,—-]\s*(.{2,})$", _said(question), re.I)
        return [{"question": m.group(1).upper(), "text": m.group(2).strip()}] if m else []
    if name == "decide":
        return _decide(project, question)
    if name == "report_change":
        return [{"text": t}] if (t := _text_after(question)) else []
    return []


def _checks(project: Any, question: str, *, catalogue: bool = False) -> list[str]:
    from kernel.checks import catalogue as kinds
    from kernel.checks.store import enabled

    keys = list(kinds()) if catalogue else list(enabled(project))
    said = question.lower()
    named = [k for k in keys if k.split(":")[0].replace("_", " ") in said or k in said]
    return named if named or catalogue else keys


def _enabled_checks(factory: Any, project: Any, question: str) -> list[dict[str, Any]]:
    found = [{"check": k} for k in _checks(project, question)]
    if not found:
        raise LookupError(f"no check is enabled on {project.meta.get('title') or project.pid} yet: Enable a check "
                          "on its Health tab first")
    return found


def _suggestions(factory: Any, project: Any, question: str) -> list[dict[str, Any]]:
    from kernel.automation_suggest import scan

    offered = [x for x in scan(factory, project.pid)["suggestions"] if x["state"] == "offered"]
    if not offered:
        raise LookupError("no automation is suggested for this project now: what its shape asks for is set up or "
                          "was dismissed")
    return [{"suggestion": x["id"], "summary": f"{x['label']}: {x['reason']}"} for x in offered]


# The operations whose arguments are read from the project's records: (reader, whether it needs a project).
_ON_PROJECT = {"run_check": _enabled_checks, "disable_check": _enabled_checks,
               "enable_check": lambda f, p, q: [{"check": k} for k in _checks(p, q, catalogue=True)],
               "accept_suggestion": _suggestions, "dismiss_suggestion": _suggestions}


def op_args(factory: Any, op: str, project: Any, question: str) -> list[dict[str, Any]]:
    """The arguments of an operation read from the words and the records, one set per proposal."""
    from kernel import assistant_ops as ops

    if not ops.OPS[op][3]:
        return [] if op in _BARE_OPS_SKIP else [{}]
    if op == "log_signal":
        return [{"text": t, "channel": "chat"}] if (t := _text_after(question)) else []
    reader = _ON_PROJECT.get(op)
    return reader(factory, project, question) if reader is not None and project is not None else []


def _summary(p: dict[str, Any], label: str, project: Any) -> str:
    args = p.get("args") or {}
    if p["action"] == "act":
        return str(args.get("summary") or label)
    detail = {"theme": lambda: ", ".join(f"{k} {v}" for k, v in (args.get("settings") or {}).items()),
              "let_rihma_assume": lambda: args.get("question"), "answer_question": lambda: args.get("question"),
              "decide": lambda: f"{args.get('card')}: {args.get('verdict')}"}.get(p["action"], lambda: "")()
    where = f" on {project.meta.get('title') or project.pid}" if project is not None and p["action"] != "theme" else ""
    return f"{label}{f' ({detail})' if detail else ''}{where}"


def _checked(factory: Any, project: Any, persona: str, p: dict[str, Any], label: str) -> tuple[dict | None, str]:
    from kernel.assistant_rules import check_proposal, normalize

    p = normalize(p)
    why = check_proposal(factory, project, persona, p)
    if why:
        return None, why
    p.setdefault("summary", _summary(p, label, project))
    return {**p, "persona": persona, "project": project.pid if project is not None else None}, ""


def for_control(factory: Any, project: Any, persona: str, question: str, control: dict[str, Any]
                ) -> tuple[list[dict[str, Any]], str | None]:
    """The proposals a request names through one control of the map, each checked, and why none could be offered
    when the words were read but the rules refuse it ("it is not paused"); ([], None) when nothing was read."""
    from kernel.parity import CHAT

    kind, name = CHAT.get(control["id"], ("", ""))
    try:
        if kind == "action":
            raw = [{"action": name, "args": a, "why": "you asked for it"} for a in action_args(name, project, question)]
        elif kind == "op":
            raw = [{"action": "act", "args": {"op": name, **a}} for a in op_args(factory, name, project, question)]
        else:
            return [], None
    except LookupError as exc:
        return [], str(exc)
    checked = [_checked(factory, project, persona, p, control.get("label") or name) for p in raw]
    made = [p for p, _ in checked if p][:LIMIT]
    return made, (None if made or not checked else checked[0][1])


def offered(factory: Any, project: Any, persona: str | None, question: str, hits: list[dict[str, Any]]
            ) -> tuple[list[dict[str, Any]], str | None]:
    """The proposals of the control the request names, by rule, and why not when the rules refuse them. The best
    match decides; a match that only shows something (suggested automations) lets the next one, its act, answer."""
    from kernel.parity import CHAT, READS

    if factory is None or not persona:
        return [], None
    controls = [h for h in hits if h.get("kind") == "control"]
    for hit in controls:
        made, why = for_control(factory, project, persona, question, hit)
        if made or why or CHAT.get(hit["id"], ("",))[0] in ("action", "op"):
            return made, why
    top = hits[0]["id"] if hits and hits[0].get("kind") == "control" else None
    own = top is not None and (top in READS or CHAT.get(top, ("",))[0] in ("walk", "open", "goal"))
    return [], ("" if own else None)     # "": a control that shows, or whose act is its own place: no note


def lead(proposals: list[dict[str, Any]], why: str | None = None) -> str:
    """What the answer says first: the proposals by rule, why the rules refuse it, or that the map only points."""
    if why == "":
        return ""
    if why:
        return f"I could not propose it: {why}. "
    if not proposals:
        return "I can only point the way here: no model is set up to propose actions. "
    names = "; ".join(str(p.get("summary") or (p.get("args") or {}).get("summary") or p["action"]) for p in proposals)
    return (f"I propose, by rule (no model is needed for this): {names}. Nothing is done until you confirm it "
            "below, signed with your name. ")


def _phrase(text: str) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9]+", text.lower())) + " "


def names_control(question: str) -> str | None:
    """The control a question names by its whole label of three words or more ("How do I ask Gnomon in the
    workspace?", "how do I use data-flow diagram?"): that control answers, not a goal's generic plan. A control whose
    own chat path is a goal plan (kernel/parity.py) is left to the plan."""
    from kernel.assistant_rules import ui_map
    from kernel.parity import CHAT

    said = _phrase(_said(question))
    named = [(len(_phrase(c["label"])), c["id"]) for c in ui_map()["controls"]
             if len(_phrase(c["label"]).split()) >= 3 and _phrase(c["label"]) in said
             and CHAT.get(c["id"], ("",))[0] != "goal"]
    return max(named)[1] if named else None
