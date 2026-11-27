"""Observer links in Ask Rihma (FR-SHR1): by rule, no model needed, each with Take me there (the Share page).

- "share my screen with a colleague for an hour" (or "let Maria Example watch for a day", "define this project
  together with Maria"): a proposal to make an observer link, for the open project or every project, for an hour,
  a day or a week, which the person confirms, signed; on Confirm the link is shown once in the chat to copy and
  pass on. A confidential project is never offered here: sharing one needs the explicit tick on the Share page;
- "who is watching?": the guests watching now, per link;
- "stop sharing": a proposal to revoke each active link of the person's;
- "pause sharing my view" / "resume sharing my view": a proposal to pause (or resume) following.

Each proposal is an ``act`` operation (``OPS``, merged into kernel/assistant_ops.py): Confirm sends exactly the
cockpit request the table says, signed by the person who confirms it, and the route checks it all again.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import observe
from kernel.confidential import confidential

# op -> (label, method, path template, the arguments it needs, the arguments it sends, the map's control)
OPS: dict[str, tuple[str, str, str, tuple[str, ...], tuple[str, ...], str]] = {
    "observe_link": ("Make an observer link (read only)", "POST", "/api/observe/links", ("scope", "hours"),
                     ("scope", "project", "hours", "guest", "intake"), "observe_link"),
    "observe_revoke": ("Stop sharing: revoke the observer link", "POST", "/api/observe/revoke", ("link",), ("link",),
                       "observe_revoke"),
    "observe_presence": ("Pause or resume showing guests the view you are on", "POST", "/api/observe/presence", (),
                         ("paused", "view"), "observe_presence"),
    "observe_suggestion": ("Confirm or decline a guest's suggested answer", "POST",
                           "/api/projects/{pid}/observe/suggestions", ("suggestion", "verdict"),
                           ("suggestion", "verdict"), "observe_suggestion"),
}
ROUTE = "#/share"
# Only questions about observer links (FR-SHR2): "share my screen", not "share work items"; "let Maria watch", not
# "let the agents watch the repository"; "who is watching?", not "who is following the plan?".
_SHARE = re.compile(r"\bshare\s+(?:my|our)\s+(?:\w+\s+)?(?:screen|view|work|doings|cockpit)\b(?!\s+items?\b)|"
                    r"\bshare\s+(?:the\s+|this\s+)?screen\b|\bshare\s+what i'?m (?:doing|working on)\b|"
                    r"\bshow\b.{0,20}\b(my screen|my work|what i'?m doing)\b.{0,30}\b(to|with)\b|"
                    r"\bobserver link\b|"
                    r"\b(?:let|invite)\s+(?!me\b|us\b|(?:the\s+|our\s+|an?\s+|my\s+)?(?:agents?|bots?|ci|pipelines?|"
                    r"automations?|scripts?|system|rihma|team|model)\b)[^.?!]{0,50}?\b(?:watch|observe|follow along|"
                    r"look over)\b(?!\s+(?:the\s+|our\s+|for\s+|my\s+)?(?:repo|repository|files?|folders?|"
                    r"branch(?:es)?|changes|logs?|builds?|ci|commits?)\b)|"
                    r"\b(define|shape|plan)\b.{0,30}\bproject\b.{0,20}\btogether\b|\bjaa (minun )?näkymä", re.I)
_WATCHING = re.compile(r"\bwho(?:'?s| is| are)?\s+(?:\w+\s+)?(?:watching|observing|following)"
                       r"(?:\s+(?:me|us|along|my\s+(?:work|screen|view|links?)))?(?:\s+(?:right\s+)?now)?\s*[?.!]*\s*$|"
                       r"\bkuka katsoo\b", re.I)
_STOP = re.compile(r"\b(stop|end|revoke|withdraw)\b.{0,20}\b(sharing|observer links?)\b", re.I)
_PAUSE = re.compile(r"\b(pause|resume|hide|unpause)\b.{0,30}\b(sharing|following|my view|what i'?m on)\b", re.I)
_NAME = re.compile(r"\b(?i:with|let|invite)\s+([A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)?)")
_ALL = re.compile(r"\b(all|every) projects?\b|\bplatform\b|\beverything\b|\bwhole (cockpit|rihmasto)\b", re.I)
_TOGETHER = re.compile(r"\btogether\b|\bintake\b|\banswer (the )?questions\b", re.I)


def _out(answer: str, *, control: str | None = None, propose: list[Any] | None = None) -> dict:
    return {"answer": answer, "navigate": {"route": ROUTE, "control": control}, "propose": propose or [],
            "dropped": [], "sources": [], "by": "map", "matches": ["share"]}


def _proposal(factory: Any, op: str, args: dict[str, Any], persona: str, project: Any) -> dict[str, Any] | None:
    from kernel import assistant_ops

    return assistant_ops.proposal(factory, op, args, persona=persona, project=project)


def hours_in(question: str) -> int:
    low = question.lower()
    if re.search(r"\bweek\b|\b7 days\b|\bviikko", low):
        return 168
    if re.search(r"\b(day|today|24 hours|tomorrow)\b|\bpäivä", low):
        return 24
    return 1


def _guest(question: str) -> str:
    found = _NAME.search(question)
    return found.group(1) if found and found.group(1).lower() not in ("me", "my", "a", "the") else ""


def _link_args(project: Any, question: str) -> dict[str, Any]:
    """The observer link the words ask for: every project, or the open one; how long; the guest; together."""
    if project is None or _ALL.search(question):
        args: dict[str, Any] = {"scope": "platform"}
    else:
        args = {"scope": "project", "project": project.pid}
        if _TOGETHER.search(question):
            args["intake"] = True
    guest = _guest(question)
    return {**args, "hours": hours_in(question), **({"guest": guest} if guest else {})}


def _share(factory: Any, project: Any, persona: str, question: str) -> dict:
    args = _link_args(project, question)
    every = args["scope"] == "platform"
    if not every and confidential(project):
        return _out(f"{project.meta.get('title') or project.pid} is confidential: sharing it needs the explicit tick "
                    "\"Include confidential projects\" on the Share page, so I do not offer it here. Take me there "
                    "to share it with that tick, or share another project.", control="observe_link")
    p = _proposal(factory, "observe_link", args, persona, None if every else project)
    what = "every project (confidential ones left out)" if every else (project.meta.get("title") or project.pid)
    who, lasts = args.get("guest") or "your colleague", observe.DURATIONS[args["hours"]]
    extra = (" They may also suggest answers to the open intake questions; each waits for you to confirm it."
             if args.get("intake") else "")
    return _out(f"I can make a read-only observer link for {who} to {what}, for {lasts}. They see the views in scope, "
                "the agent channel, the view you are on and your latest actions, and may comment; they never decide, "
                f"run or change anything.{extra} When you confirm, the link is shown here once with Copy: you pass "
                "it on yourself, Rihmasto sends nothing. They open it on this machine; a tunnel to it is "
                "an ssh login on this machine, far more than read only, so only from a restricted account (Share's "
                "guide says how).",
                control="observe_link", propose=[p] if p else [])


def _mine(factory: Any, person: str | None) -> list[dict[str, Any]]:
    rows = [observe.public(factory, r) | {"scope_title": observe.scope_title(factory, r)}
            for r in observe.links(factory)]
    return [r for r in rows if r["state"] == "active" and (not person or r["created_by"] == person)]


def _watching(factory: Any, person: str | None) -> dict:
    active = _mine(factory, person)
    if not active:
        return _out("Nobody: you have no active observer link. Say \"share my screen with a colleague for an hour\", "
                    "or make one on the Share page.", control="observe_watching")
    lines = [f"{r['id']} ({r['scope_title']}): " + (", ".join(r["watching"]) + " watching now" if r["watching"]
                                                     else "nobody watching now") for r in active]
    return _out("; ".join(lines) + ".", control="observe_watching")


def _stop(factory: Any, project: Any, persona: str, person: str | None) -> dict:
    active = _mine(factory, person)
    if not active:
        return _out("You share nothing now: no observer link is active.", control="observe_revoke")
    props = [p for r in active[:5] if (p := _proposal(factory, "observe_revoke", {"link": r["id"]}, persona, None))]
    return _out(f"I can revoke {', '.join(r['id'] for r in active[:5])}: each ends at once, and every guest's page "
                "says sharing stopped.", control="observe_revoke", propose=props)


def answer(factory: Any, question: str, project: Any, persona: str, person: str | None = None) -> dict | None:
    """The rule's answer, or None when the question is not about observer links. Only the latest turn is read."""
    question = question.rsplit("\n\nNow: ", 1)[-1]
    if _WATCHING.search(question):
        return _watching(factory, person)
    if _STOP.search(question):
        return _stop(factory, project, persona, person)
    if _PAUSE.search(question):
        paused = not re.search(r"\b(resume|unpause)\b", question, re.I)
        p = _proposal(factory, "observe_presence", {"paused": paused, "view": "paused" if paused else ""}, persona,
                      None)
        return _out("I can " + ("pause showing your guests the view you are on: they keep the shared views, not where "
                                "you are." if paused else "resume showing your guests the view you are on."),
                    control="observe_presence", propose=[p] if p else [])
    if _SHARE.search(question):
        return _share(factory, project, persona, question)
    said = _SUGGESTION.search(question)
    return _settle(factory, persona, said.group(1).lower(), said.group(2)) if said else None


_SUGGESTION = re.compile(r"\b(accept|confirm|decline|reject)\b.{0,30}\b(GS-\d{1,5})\b", re.I)


def _settle(factory: Any, persona: str, word: str, sid: str) -> dict:
    """A guest's suggestion confirmed or declined by its id (GS-001)."""
    try:
        row = observe.suggestion(factory, sid.upper())
        project = factory.project(row["project"])
    except KeyError:
        return _out(f"There is no suggestion {sid}. The Share page lists your guests' suggestions.",
                    control="observe_suggestion")
    verdict = "accept" if word in ("accept", "confirm") else "decline"
    p = _proposal(factory, "observe_suggestion", {"project": project.pid, "suggestion": row["id"],
                                                  "verdict": verdict}, persona, project)
    then = (f"{row['question']} is answered with their words, signed by you" if verdict == "accept"
            else f"{row['question']} stays open")
    return _out(f"{row['guest']} suggested for {row['question']}: \"{row['text'][:200]}\". "
                f"If you {verdict} it, {then}.",
                control="observe_suggestion", propose=[p] if p else [])
