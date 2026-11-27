"""People in the loop in Ask Rihma (FR-HITL1): by rule, no model needed, each with Take me there.

- "who hasn't answered?": every open ask with who it waits on and for how long (this project, or every project);
- "send this question to the legal reviewer: <words>" (or "to IT: <words>", or an intake question, Q-3): a
  proposal to put it to the persona named or responsible for that family, which the person confirms, signed; it
  waits in People in the loop until someone sends it to their channels;
- "send HQ-002" (an ask named by its id): a proposal to send that ask to its persona's channels, never a copy;
- "nudge them": a proposal to send the reminders due now;
- "require legal sign-off" / "make security advise only" (or "... for all projects"): a proposal to set that
  family's level, for this project or every project;
- "give Maria Example a link for the legal questions": a proposal to make her a one-use link for the open asks put
  to that persona; on Confirm the link is shown once in the chat to copy (FR-HITL2).

Each proposal is an ``act`` operation (``OPS``, merged into kernel/assistant_ops.py): Confirm sends exactly the
cockpit request the table says, signed by the person who confirms it, and the route checks it all again.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import hitl

# op -> (label, method, path template, the arguments it needs, the arguments it sends, the map's control)
OPS: dict[str, tuple[str, str, str, tuple[str, ...], tuple[str, ...], str]] = {
    "hitl_ask": ("Put the question to the reviewer", "POST", "/api/projects/{pid}/hitl/asks", ("text",),
                 ("text", "kind", "family", "to_persona", "to_person", "options"), "hitl_ask"),
    "hitl_answer": ("Answer the ask", "POST", "/api/projects/{pid}/hitl/answer", ("ask", "answer"),
                    ("ask", "answer", "comment"), "hitl_answer"),
    "hitl_send": ("Send the ask to its channels", "POST", "/api/projects/{pid}/hitl/send", ("ask",), ("ask",),
                  "hitl_send"),
    "hitl_link": ("Give a person outside a one-use link", "POST", "/api/projects/{pid}/hitl/links", ("name", "asks"),
                  ("name", "asks", "role", "hours", "channel", "address", "context"), "hitl_link"),
    "hitl_revoke": ("Withdraw the link", "POST", "/api/projects/{pid}/hitl/revoke", ("link",), ("link",),
                    "hitl_link_revoke"),
    "hitl_nudge": ("Nudge who has not answered", "POST", "/api/projects/{pid}/hitl/nudge", (), (), "hitl_nudge"),
    "hitl_enforce": ("Set how strictly the check family is enforced", "PUT", "/api/projects/{pid}/hitl/enforcement",
                     ("family", "level"), ("family", "level", "scope"), "hitl_enforce"),
}
VIEW = "loop"
_WHO = re.compile(r"\b(who|whom)\b.{0,40}\b(has ?n[o']?t|have ?n[o']?t|not yet|hasn't|haven't|still)\b.{0,20}"
                  r"\b(answer|answered|replied|respond|responded|signed)|\bwaiting on whom\b|\boutstanding "
                  r"(sign-?offs?|answers|reviews)\b|\bkuka ei (ole )?vastannut\b", re.I)
_SEND = re.compile(r"\b(send|ask|forward|route|put)\b", re.I)
_REVIEWER = re.compile(r"\b(reviewer|review|team|sign-?off|owner|lawyer|counsel|compliance)\b", re.I)
_IT = re.compile(r"\bIT\b")                                    # IT, not "it": case counts here
_TO_PERSONA = (("product_owner", re.compile(r"\bproduct owner\b", re.I)),
               ("business_owner", re.compile(r"\bbusiness owner\b", re.I)),
               ("compliance", re.compile(r"\bcompliance\b", re.I)))
_ALL = re.compile(r"\b(all|every|each) projects?\b|\bplatform[- ]wide\b|\beverywhere\b|\bkaikki(in)? projekti", re.I)
_NUDGE = re.compile(r"\b(nudge|remind|chase)\b", re.I)
_LEVEL = re.compile(r"\b(require|required|enforce|force|mandatory|advise|advisory|optional)\b", re.I)
# a stage or environment named: the levels per environment are Enforcement's (kernel/enforcement_chat.py, FR-ENF1)
_STAGE = re.compile(r"\b(staging|stage|production|prod|dev|development|testing|test environment|environments?|"
                    r"deploys?|deployments?)\b", re.I)
_LINK = re.compile(r"\b(link|invite)\b.*\b(for|to)\b|\bgive\b.+\ba link\b", re.I)
_NAME = re.compile(r"\b(?i:give|send|invite)\s+(?i:a link to\s+)?([A-Z][\w'-]+(?:\s+[A-Z][\w'-]+){0,2})")
_ID = re.compile(r"\b(HQ-\d{1,5})\b")
_QID = re.compile(r"\b(Q-\d{1,5})\b")
_WORDS = {"legal": ("legal", "lawyer", "counsel", "gdpr"), "security": ("security", "secure"),
          "quality": ("quality", "qa"), "governance": ("governance", "compliance", "audit")}


def family_in(question: str) -> str | None:
    low = question.lower()
    return next((fam for fam, words in _WORDS.items() if any(re.search(rf"\b{w}\b", low) for w in words)), None)


def _out(answer: str, project: Any, *, control: str | None = None, propose: list[Any] | None = None) -> dict:
    route = f"#/p/{project.pid}/{VIEW}" if project is not None else "#/projects"
    return {"answer": answer, "navigate": {"route": route, "control": control}, "propose": propose or [],
            "dropped": [], "sources": [], "by": "map", "matches": [VIEW]}


def _proposal(factory: Any, op: str, args: dict[str, Any], persona: str, project: Any) -> dict[str, Any] | None:
    from kernel import assistant_ops

    return assistant_ops.proposal(factory, op, {"project": project.pid, **args}, persona=persona, project=project)


def _waiting_lines(project: Any) -> list[str]:
    rows = hitl.who_has_not_answered(project)
    return [f"{r['id']} ({hitl.FAMILY_LABEL[r['family']].lower()} {r['kind']}) waits on "
            f"{r['person'] or 'the ' + r['persona'].replace('_', ' ')}{' (outside)' if r['external'] else ''} for "
            f"{round(r['hours'] / 24, 1)} days{', required before delivery' if r['required'] else ''}" for r in rows]


def _who(factory: Any, project: Any, persona: str) -> dict:
    projects = [project] if project is not None else [p for p in factory.projects() if p.path(hitl.FILE).exists()]
    lines = [f"{p.meta.get('title') or p.pid}: {line}" if project is None else line
             for p in projects for line in _waiting_lines(p)]
    if not lines:
        where = project.meta.get("title") if project is not None else "any project"
        return _out(f"Nobody: no question waits on anyone in {where}. Put one to a reviewer with \"send to the legal "
                    "reviewer: <your question>\", or in People in the loop.", project, control="hitl_ask")
    nudge = _proposal(factory, "hitl_nudge", {}, persona, project) if project is not None else None
    return _out(f"{len(lines)} not answered yet: " + "; ".join(lines[:8]) + ("." if len(lines) <= 8 else "; and more.")
                + (" I can send the reminders due now." if nudge else ""), project, control="hitl_waiting",
                propose=[nudge] if nudge else [])


def _words(question: str) -> str | None:
    """The person's own words to ask: quoted, or after a colon."""
    quoted = re.search(r"[\"“']([^\"”']{5,})[\"”']", question)
    if quoted:
        return quoted.group(1).strip()
    if ":" in question and len(question.split(":", 1)[1].strip()) >= 5:
        return question.split(":", 1)[1].strip()
    return None


def _text_of(question: str, project: Any) -> str | None:
    """The words to ask: the person's own, or an intake question's (Q-3)."""
    words = _words(question)
    if words:
        return words
    qid = _QID.search(question)
    return _canon_question(project, qid.group(1)) if qid else None


def _named_to(question: str) -> str | None:
    """The persona a person names: "to IT", "to compliance", "to the product owner"."""
    if _IT.search(question):
        return "it"
    return next((p for p, rx in _TO_PERSONA if rx.search(question)), None)


def _is_send(question: str) -> bool:
    if not _SEND.search(question):
        return False
    if _ID.search(question):
        return True
    named = _REVIEWER.search(question) or _IT.search(question)
    return bool(named) and bool(family_in(question) or "reviewer" in question.lower() or _named_to(question))


def _canon_question(project: Any, qid: str) -> str | None:
    from kernel.canon import Canon

    try:
        q = Canon(project).question(qid)
    except (KeyError, OSError, ValueError):
        return None
    return str(q.get("text") or q.get("question") or "").strip() or None


def _send_existing(factory: Any, project: Any, persona: str, question: str, ask_id: str) -> dict:
    """An ask named by its id is sent as it is, to the persona it is put to: never a copy (FR-HITL2)."""
    try:
        item = hitl.get(project, ask_id)
    except KeyError:
        return _out(f"There is no {ask_id} in {project.meta.get('title') or project.pid}. Who hasn't answered lists "
                    "the open ones.", project, control="hitl_waiting")
    if item["state"] != "open":
        return _out(f"{ask_id} is already answered: nothing to send.", project, control="hitl_waiting")
    to = item["to"]["persona"]
    fam = family_in(question)
    named = _named_to(question) or (hitl.FAMILY_PERSONA[fam] if fam else None)
    other = (f" You named {hitl.persona_word(named)}, but {ask_id} is put to {hitl.persona_word(to)}, so it goes to "
             f"their channels. To ask {hitl.persona_word(named)} too, say \"send to {hitl.persona_word(named)}: <your "
             "question>\", or give a person outside a link." if named and named != to else "")
    p = _proposal(factory, "hitl_send", {"ask": ask_id}, persona, project)
    return _out(f"I can send {ask_id} ({hitl.FAMILY_LABEL[item['family']].lower()} {item['kind']}: "
                f"\"{item['text'][:160]}\") to {hitl.persona_word(to)} through the Teams, Slack or email channels IT "
                f"set up for them, with a link back to answer.{other}", project, control="hitl_send",
                propose=[p] if p else [])


def _send(factory: Any, project: Any, persona: str, question: str) -> dict:
    found = _ID.search(question)
    if found and not _words(question):
        return _send_existing(factory, project, persona, question, found.group(1))
    fam = family_in(question) or ("security" if _IT.search(question) else "general")
    to = _named_to(question) or hitl.FAMILY_PERSONA[fam]
    text = _text_of(question, project)
    if not text:
        return _out(f"Which question? Say it after a colon, for example \"send to the {fam} reviewer: Can we keep the "
                    "customers' emails for two years?\", or name an ask (HQ-001). Or write it in People in the "
                    "loop, Ask.", project, control="hitl_ask")
    p = _proposal(factory, "hitl_ask", {"text": text, "family": fam, "kind": "question", "to_persona": to},
                  persona, project)
    return _out(f"I can put this to {hitl.persona_word(to)} as a {fam} question: \"{text[:200]}\". It waits for "
                "them in People in the loop; nothing is sent until you press Send to their channels there (or say "
                f"\"send\" and its id here). {_level_words(project, fam)}", project, control="hitl_ask",
                propose=[p] if p else [])


def _level_words(project: Any, fam: str) -> str:
    if fam not in hitl.CHECK_FAMILIES:
        return "Nothing waits on it."
    lvl, where = hitl.level(project, fam)
    return ("Delivery waits until it is answered (required, " if lvl == "require" else
            "Nothing waits on it (advised, ") + f"set {where})."


def _enforce(factory: Any, project: Any, persona: str, question: str) -> dict | None:
    fam = family_in(question)
    if fam is None:
        return None
    lvl = "advise" if re.search(r"\b(advise|advisory|optional|only advise)\b", question, re.I) else "require"
    scope = "platform" if _ALL.search(question) else "project"    # "for all projects": every project (FR-HITL2)
    p = _proposal(factory, "hitl_enforce", {"family": fam, "level": lvl, "scope": scope}, persona, project)
    said = (f"delivery waits on every open {fam} ask" if lvl == "require"
            else f"{fam} asks are shown and nudged, nothing waits")
    where = ("all projects (every project without its own setting; signed on the factory's record)"
             if scope == "platform" else project.meta.get("title") or project.pid)
    return _out(f"I can set {fam} checks to {lvl} for {where}: {said}. Now it is "
                f"{hitl.level(project, fam)[0]} ({hitl.level(project, fam)[1]}).", project, control="hitl_enforce",
                propose=[p] if p else [])


def _link(factory: Any, project: Any, persona: str, question: str) -> dict:
    name = _NAME.search(question)
    fam = family_in(question)
    to = hitl.FAMILY_PERSONA[fam] if fam else None
    open_ids = [a["id"] for a in hitl.asks(project, state="open") if to is None or a["to"]["persona"] == to]
    if name is None or not open_ids:
        why = "Name the person" if name is None else "No open ask is put to that persona yet"
        return _out(f"{why}: for example \"give Maria Example a link for the legal questions\". The link opens once, "
                    "shows only those questions, and her answers are signed with her name.", project,
                    control="hitl_link")
    if to is None:
        first = hitl.get(project, open_ids[0])["to"]["persona"]
        open_ids = [i for i in open_ids if hitl.get(project, i)["to"]["persona"] == first]
    p = _proposal(factory, "hitl_link", {"name": name.group(1), "asks": open_ids, "channel": "copy"}, persona, project)
    return _out(f"I can make {name.group(1)} a one-use link for {', '.join(open_ids)}. When you confirm, the link is "
                "shown here once, with Copy, for you to pass on; it opens a page with only those questions."
                + _base_words(factory), project, control="hitl_link", propose=[p] if p else [])


def _base_words(factory: Any) -> str:
    """A warning when links would point at this computer only (FR-HITL2)."""
    from kernel import hitl_links, hitl_send

    base = hitl_send.channels(factory)["link_base"]
    if base and not hitl_links.local_only(base):
        return ""
    return (" IT has not set where outside links point, so the link may point at this computer only and nobody "
            "outside can open it: IT sets it in People in the loop, Channels (Where outside links point).")


def answer(factory: Any, question: str, project: Any, persona: str) -> dict | None:
    """The rule's answer, or None when the question is not about people in the loop. Only the latest turn is
    read: the conversation before it is history, never a request (kernel/copilot.py does the same)."""
    question = question.rsplit("\n\nNow: ", 1)[-1]
    if _WHO.search(question):
        return _who(factory, project, persona)
    if project is None:
        return None
    if _NUDGE.search(question) and re.search(r"\b(review|answer|them|who|sign)", question, re.I):
        p = _proposal(factory, "hitl_nudge", {}, persona, project)
        return _out("I can send the reminders due now to whoever has not answered.", project, control="hitl_nudge",
                    propose=[p] if p else [])
    if _LINK.search(question) and _NAME.search(question):
        return _link(factory, project, persona, question)
    if _LEVEL.search(question) and family_in(question) and not _STAGE.search(question) \
            and re.search(r"\b(check|checks|sign-?off|review)", question, re.I):
        return _enforce(factory, project, persona, question)
    if _is_send(question):
        return _send(factory, project, persona, question)
    return None
