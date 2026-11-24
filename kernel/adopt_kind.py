"""Which kind of work an adopted project is (FR-X1-AC-4; the owner's decision of 2026-11-24, "Ask").

Adoption proposes the work profile by rule from the project's title and its README (kernel/adopt.py
``_propose``, kernel/profiles.py ``propose_profile``). With one clear candidate it takes it, as before, and
says which and why (the brief's line, `rihmasto adopt`'s ``profile_basis``). When the files and words do not
make it clear, it no longer falls back to a web app: it asks a person which kind it is, with a question card
listing the candidate kinds, the same "Which kind of work is this?" question an intake asks. The project's
kind stays unset until a person answers; the answer chooses the profile it names (``profile_chosen``) and the
adopted brief says so. The as-is spec of an adopted project is observed behaviour, not shaped for a kind of
work, so an answer given after adoption still chooses (an intake's spec does not: kernel/profiles.py).
"""

from __future__ import annotations

import re
from typing import Any

from kernel.canon import Canon
from kernel.profiles import PROFILE_QUESTION, PROFILES, _named_profile, add_profile_question, choose
from kernel.store import Project

LINE = re.compile(r"^- Work profile: .*$", re.MULTILINE)


def unclear(profile: dict[str, Any]) -> bool:
    """Whether the rule's proposal leaves the kind to a person: proposed by rule, and not clear."""
    return profile.get("by") == "rule" and profile.get("confidence") != "clear"


def ask(project: Project, profile: dict[str, Any]) -> dict[str, Any] | None:
    """Put "Which kind of work is this?" to a person, with the candidate kinds as its options, when the rule is
    not sure; the question card is in the Inbox and What's next. Returns the question, or None when it is clear."""
    if not unclear(profile):
        return None
    canon = Canon(project)
    q = add_profile_question(canon, {"profile": profile["profile"], "confidence": "uncertain",
                                     "candidates": profile["candidates"], "uncertain_because": profile["why"]})
    if q is None:
        return None
    card = canon.ask(q["id"])
    project.log("adopt_kind_asked", {"question": q["id"], "card": card["id"], "candidates": profile["candidates"],
                                     "why": profile["why"]})
    return {**q, "card": card["id"]}


def line(profile: dict[str, Any]) -> str:
    """The adopted brief's line on the work profile: which and why, or that a person is asked."""
    label = PROFILES[profile["profile"]]["label"] if profile.get("profile") in PROFILES else None
    if profile.get("by") != "rule":
        who = "a person" if profile.get("by") in (None, "person at creation") else profile["by"]
        return f"- Work profile: {label}, chosen by {who}."
    if not unclear(profile):
        return f"- Work profile: {label}, proposed by rule ({', '.join(profile.get('keywords') or [])})."
    names = ", ".join(PROFILES[c]["label"] for c in profile.get("candidates") or [])
    return (f"- Work profile: not clear from its files and words ({profile.get('why')}): a person is asked which "
            f"kind of work it is, among {names}.")


def settle(project: Project) -> str | None:
    """A person's answer to the adopted project's kind question chooses the profile it names, once. Returns the
    profile chosen, or None."""
    meta = project.meta
    if meta.get("source_kind") != "adopted":
        return None
    for q in Canon(project).questions("answered"):
        if q["text"] != PROFILE_QUESTION or meta.get("profile_answered") == q["id"]:
            continue
        named = _named_profile(str(q["answer"].get("text", "")))
        if named is None:
            continue
        project.update_meta(profile_answered=q["id"])
        choose(project, named, basis={"by": q["answer"]["by"], "question": q["id"]})
        adopted = project.read("adopted.json") or {}
        adopted["profile"] = {"profile": named, "by": q["answer"]["by"], "question": q["id"]}
        project.write("adopted.json", adopted)
        return named
    return None


def brief(project: Project) -> str:
    """The adopted project's brief as it stands: its own (kernel/adopt.py), with the work profile's line as
    the records say now and the answers people gave. A kind answered is taken first (``settle``)."""
    settle(project)
    canon = Canon(project)
    text = canon.brief
    profile = (project.read("adopted.json") or {}).get("profile") or {}
    if unclear(profile) and project.meta.get("profile"):     # chosen since, in Project settings
        profile = {"profile": project.meta["profile"], "by": "a person"}
    if profile:
        text = LINE.sub(lambda _: line(profile), text, count=1)
    text = text.split("\n## Answers [owner]\n", 1)[0].rstrip() + "\n"
    answered = canon.questions("answered")
    if answered:
        text += "\n## Answers [owner]\n\n" + "".join(
            f"- {q['id']} ({q['perspective']}): {q['text']}: **{q['answer']['text']}** [owner: {q['answer']['by']}]\n"
            for q in answered)
    canon.write_brief(text)
    return text
