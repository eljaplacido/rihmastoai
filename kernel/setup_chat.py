"""Ask Rihma for FR-SET1: set up a project, suggest or describe automations, archive, restore and remove projects.

Chat parity with the cockpit's clicks (the owner, 2026-11-24): what the Set up checklist, the suggestions, "Describe
it" and the archive buttons do, a person can ask for in Ask Rihma, in English or Finnish, with or without a model:

- "set up this project" / "aseta projekti": the checklist, and a proposal per offered item;
- "suggest automations for this project" / "what should I automate": the suggestions, each one to accept;
- "every night run the tests and tell me on Teams if they fail": the draft, its summary and dry run, to set up;
- "archive the duplicate projects", "archive Loans", "restore Loans", "remove Loans for good": the proposals.

Each proposal is an ``act`` of kernel/assistant_ops.py, checked before it is shown and carried out only when the
person confirms it in the cockpit, signed with their name. Kernel/copilot.py ``routed`` asks this module first.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import assistant_ops as ops
from kernel.alignment_suggest import plural

_SETUP = re.compile(r"\b(?:set ?up (?:this|the|my) project|set (?:this|it) up|setup checklist|populate (?:it|this)|"
                    r"what is not set up|aseta (?:projekti|tämä)|ota käyttöön kaikki|all (?:the )?features)")
_SUGGEST = re.compile(r"\b(?:suggest (?:\w+ )?automations?|automation (?:ideas|suggestions)|what (?:should|could|can) "
                      r"i automate|scan (?:\w+ )?for automations?|ehdota automaatio\w*)")
_AUTOMATION = re.compile(r"\b(?:automat(?:e|ion|ically)|automaatio\w*|every (?:night|morning|day|week|hour|\d)|"
                         r"nightly|hourly|öisin|aamuisin|joka (?:yö|aamu|päivä|viikko))")
_QUESTION = re.compile(r"(?:where|how|what is|what are|which|why|can i|could i|is |are |do i|missä|miten|mikä|"
                       r"voiko|kuinka)")
_NAMED = re.compile(r"\b(?:automat(?:e|ion)\w*|automaatio\w*)")
_DUPLICATES = re.compile(r"\b(?:duplicates?|duplicate projects?|copies|kaksoiskappale\w*|tuplat?)\b")
_ARCHIVE = re.compile(r"\b(?:archive|arkistoi\w*|hide)\b")
_RESTORE = re.compile(r"\b(?:restore|unarchive|palauta)\b")
_REMOVE = re.compile(r"\b(?:remove|delete|poista|clean up|siivoa)\b")
_FOR_GOOD = re.compile(r"\b(?:for good|permanently|pysyvästi|lopullisesti)\b")


def _said(question: str) -> str:
    return re.sub(r"\s+", " ", question.lower()).strip()


def _answer(text: str, offered: list[dict[str, Any] | None], *, matches: list[str],
            nav: dict[str, Any] | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    proposals = [p for p in offered if p]
    tail = " Nothing is done yet: what I propose below runs only when you confirm it." if proposals else ""
    return {"answer": text + tail, "navigate": nav, "propose": proposals, "dropped": [],
            "sources": [], "by": "setup", "matches": matches, **(extra or {})}


def _named(factory: Any, said: str, *, archived: bool = False) -> Any:
    """The project the words name, by its id or its title (the longest title found wins)."""
    from kernel.project_archive import is_archived

    pool = [p for p in factory.projects(archived=True) if not p.pid.startswith("_") and is_archived(p) == archived]
    def names(p: Any) -> bool:
        title = str(p.meta.get("title") or "").lower()
        return p.pid in said or (len(title) >= 3 and re.search(rf"\b{re.escape(title)}\b", said) is not None)

    hits = [p for p in pool if names(p)]
    hits.sort(key=lambda p: -len(str(p.meta.get("title") or "")))
    return hits[0] if hits else None


# -- set up, suggest, describe ------------------------------------------------------------------------------

def _named_suggestion(item: dict[str, Any]) -> dict[str, Any]:
    """The suggestion an item's one click names, sent with it so Confirm sets up that one or is refused."""
    named = (item["action"] or {}).get("suggestion")
    return {"suggestion": named} if named else {}


def setup_answer(factory: Any, project: Any, persona: str) -> dict[str, Any]:
    from kernel.project_setup import checklist

    c = checklist(factory, project.pid)
    offered = [i for i in c["items"] if i["state"] == "offered"]
    proposals = [ops.proposal(factory, "setup_step", {"item": i["id"], **_named_suggestion(i)}, persona=persona,
                              project=project, summary=i["action"]["label"])
                 for i in offered if (i["action"] or {}).get("kind") == "do"]
    by_hand = [i["label"] + ": " + i["action"]["label"] for i in offered if (i["action"] or {}).get("kind") == "open"]
    text = f"{c['title']}: {c['line']}"
    if by_hand:
        text += " Chosen by hand, in their own place: " + "; ".join(by_hand) + "."
    return _answer(text, proposals, matches=["setup_checklist"],
                   nav={"route": f"#/p/{project.pid}/overview", "control": "setup_checklist"}, extra={"setup": c})


def suggest_answer(factory: Any, project: Any, persona: str) -> dict[str, Any]:
    from kernel.automation_suggest import scan

    s = scan(factory, project.pid)
    offered = [x for x in s["suggestions"] if x["state"] == "offered"]
    proposals = [ops.proposal(factory, "accept_suggestion", {"suggestion": x["id"]}, persona=persona, project=project,
                              summary=f"{x['label']}: {x['reason']}") for x in offered[:6]]
    text = (f"For {s['title']} I suggest {plural(len(offered), 'automation')} from its shape and state: "
            + "; ".join(f"{x['label']} ({x['reason']})" for x in offered[:6]) + "." if offered
            else f"Nothing more to suggest for {s['title']}: what its shape asks for is set up or was dismissed.")
    return _answer(text, proposals, matches=["automations_suggest"],
                   nav={"route": f"#/p/{project.pid}/automations", "control": "automations_suggest"},
                   extra={"suggestions": s["suggestions"]})


def describe_answer(factory: Any, project: Any, question: str, persona: str, model: Any) -> dict[str, Any] | None:
    """A described automation: when the rules read both its trigger and its action, or the person names an
    automation and a model reads the rest. Anything else is not an automation: None."""
    from kernel.automation_compose import by_rules, compose

    read = by_rules(factory, question, project=project)
    if read["missing"] and (model is None or not _NAMED.search(_said(question))):
        return None
    out = compose(factory, question, project=project, model=model)
    if not out["ok"]:
        return _answer(f"I read it as an automation, but it does not check out: {out['why']}", [],
                       matches=["automations_describe"], extra={"compose": out})
    p = ops.proposal(factory, "add_automation", {"automation": out["draft"]}, persona=persona, project=project,
                     summary=out["summary"])
    text = f"Here is the draft: {out['summary']}"
    if out["dry_run"] and out["dry_run"].get("first_at"):
        text += f" It would first run at {out['dry_run']['first_at']}."
    if out.get("note"):
        text += f" Note: {out['note']}."
    return _answer(text, [p] if p else [], matches=["automations_describe"], extra={"compose": out})


# -- archive, restore, remove ------------------------------------------------------------------------------

def duplicates_answer(factory: Any, persona: str) -> dict[str, Any]:
    from kernel.project_archive import duplicates

    groups = duplicates(factory)
    proposals = [ops.proposal(factory, "archive_project", {"project": c["id"], "reason": f"a copy of {keep}"},
                              persona=persona, summary=f"Archive {c['title']} ({c['id']}), a copy of {keep}")
                 for g in groups for keep in [g["keep"]["id"]] for c in g["copies"]][:12]
    if not groups:
        return _answer("No two projects share a title here: there is no duplicate to archive.", [],
                       matches=["archived_projects"], nav={"route": "#/projects", "control": "archived_projects"})
    lines = "; ".join(f"{g['title']}: keep {g['keep']['id']}, archive {', '.join(c['id'] for c in g['copies'])}"
                      for g in groups)
    text = (f"{len(groups)} title(s) have copies ({lines}). Archiving hides a copy and makes it read-only; it can be "
            "restored, and an archived project can then be removed for good from Projects, Archived.")
    return _answer(text, proposals, matches=["archived_projects"],
                   nav={"route": "#/projects", "control": "archived_projects"}, extra={"duplicates": groups})


def _remove(factory: Any, said: str, project: Any, persona: str) -> dict[str, Any] | None:
    target = _named(factory, said, archived=True)
    if target is not None:
        from kernel.project_archive import confirmation

        p = ops.proposal(factory, "remove_project", {"project": target.pid, "confirm": target.pid}, persona=persona,
                         summary=confirmation(target))
        return _answer(confirmation(target), [p] if p else [], matches=["remove_project"])
    live = _named(factory, said) or project
    if live is None:
        return None
    p = ops.proposal(factory, "archive_project", {"project": live.pid, "reason": "asked to remove it"},
                     persona=persona, summary=f"Archive {live.meta.get('title')} ({live.pid})")
    return _answer(f"A project is removed only once it is archived. I propose archiving {live.meta.get('title')} "
                   f"({live.pid}) first: it leaves every list and turns read-only; then Remove in Projects, Archived "
                   "deletes it for good after its records are exported.", [p] if p else [],
                   matches=["archive_project", "remove_project"])


def archive_answer(factory: Any, said: str, project: Any, persona: str) -> dict[str, Any] | None:
    if _DUPLICATES.search(said):
        return duplicates_answer(factory, persona)
    if _RESTORE.search(said):
        target = _named(factory, said, archived=True)
        if target is None:
            return None
        p = ops.proposal(factory, "restore_project", {"project": target.pid}, persona=persona,
                         summary=f"Restore {target.meta.get('title')} ({target.pid})")
        return _answer(f"I propose restoring {target.meta.get('title')}: it is back in the lists and writable.",
                       [p] if p else [], matches=["restore_project"])
    if _FOR_GOOD.search(said) or (_REMOVE.search(said) and not _ARCHIVE.search(said)):
        return _remove(factory, said, project, persona)
    target = _named(factory, said) or project
    if target is None:
        return None
    p = ops.proposal(factory, "archive_project", {"project": target.pid}, persona=persona,
                     summary=f"Archive {target.meta.get('title')} ({target.pid})")
    return _answer(f"I propose archiving {target.meta.get('title')} ({target.pid}): it leaves every list and turns "
                   "read-only, and Projects, Archived restores it.", [p] if p else [], matches=["archive_project"])


def _is_about_projects(factory: Any, said: str) -> bool:
    if re.search(r"\b(?:projects?|projekti\w*)\b", said) or _DUPLICATES.search(said):
        return True
    return _named(factory, said) is not None or _named(factory, said, archived=True) is not None


def routed(factory: Any, project: Any, question: str, *, persona: str, model: Any = None) -> dict[str, Any] | None:
    """Ask Rihma's answer when the question is one of these; None otherwise (the other helpers answer)."""
    said = _said(question)
    act = not _QUESTION.match(said)          # "where do I archive a project?" is answered from the map
    if project is not None and project.pid.startswith("_"):
        project = None
    found = _archiving(factory, said, project, persona) if act else None
    if found is not None:
        return found
    if project is not None:
        found = _in_project(factory, said, project, persona)
        if found is not None:
            return found
    if act and (_AUTOMATION.search(said) or re.search(r"\b(?:when|kun|on new|if)\b", said)):
        return describe_answer(factory, project, question, persona, model)
    return None


def _archiving(factory: Any, said: str, project: Any, persona: str) -> dict[str, Any] | None:
    asks = _ARCHIVE.search(said) or _RESTORE.search(said) or _REMOVE.search(said)
    return archive_answer(factory, said, project, persona) if asks and _is_about_projects(factory, said) else None


def _in_project(factory: Any, said: str, project: Any, persona: str) -> dict[str, Any] | None:
    if _SUGGEST.search(said):
        return suggest_answer(factory, project, persona)
    if _SETUP.search(said) and not _AUTOMATION.search(said):
        return setup_answer(factory, project, persona)
    return None
