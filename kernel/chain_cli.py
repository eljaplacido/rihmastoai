"""The chain's commands that read or settle a project's questions, and what a mistyped id is told (kernel/cli.py).

`rihmasto status` names each open question's Q-id beside its card's C-id, and `answer` and `assume` take either id:
the C-id that status shows for a question card is read as its question. A mistyped project id, question id, card id
or verdict is one line on stderr that says what was wrong and which ids there are, and exit 2, as the CLI's help
promises for the capability layer; never a traceback.
"""

from __future__ import annotations

import re
from typing import Any

from kernel.canon import Canon
from kernel.learn import FACTORY_PID, FACTORY_TITLE
from kernel.store import STAGES, Factory

CARD_ID = re.compile(r"C-\d+\Z", re.I)
QUESTION_ID = re.compile(r"Q-\d+\Z", re.I)
SHOWN = 8      # ids named in one refusal, the rest counted


def _card_row(c: dict) -> dict:
    row = {"id": c["id"], "kind": c["kind"], "title": c["title"][:80]}
    qid = (c.get("refs") or {}).get("question") if c["kind"] == "question" else None
    return row | ({"question": qid} if qid else {})


def status(factory: Factory, pid: str | None) -> dict:
    """Each project's stage, open cards (a question card with its question's Q-id, which `answer` takes), questions,
    overdue assumptions, tasks and whether its ledger is intact."""
    projects = [factory.project(pid)] if pid else factory.projects()
    out = []
    for p in projects:
        meta, canon = p.meta, Canon(p)
        tasks = p.read("tasks.json", {}) or {}
        title = FACTORY_TITLE if p.pid == FACTORY_PID else meta["title"]   # one name, a home made before it too
        out.append({"id": p.pid, "title": title, "maturity": meta["maturity"], "mode": meta["mode"],
                    "stage": f"{meta['stage']} {STAGES[meta['stage']]}",
                    "open_cards": [_card_row(c) for c in canon.cards()],
                    "open_questions": [{"id": q["id"], "card": q.get("card"), "text": str(q.get("text") or "")[:80]}
                                       for q in canon.questions("open")],
                    "questions": {s: len(canon.questions(s)) for s in ("open", "answered", "assumed")},
                    "overdue_assumptions": [a["id"] for a in canon.overdue()],
                    "tasks": {t: s.get("status") for t, s in tasks.items()},
                    "ledger_intact": p.ledger().verify().intact})
    return {"projects": out}


def question_id(canon: Canon, given: str) -> str:
    """The Q-id a person named, or the question a question card's C-id puts to a person."""
    if not CARD_ID.match(given):
        return given
    card = canon.get_card(given.upper())
    qid = (card.get("refs") or {}).get("question") if card["kind"] == "question" else None
    if not qid:
        raise LookupError(f"{card['id']} is a {card['kind']} card, not a question: {_open_questions(canon)}")
    return str(qid)


def answer(factory: Factory, args: Any, out: Any) -> None:
    p = factory.project(args.pid)
    canon = Canon(p)
    out(canon.answer(question_id(canon, args.qid), args.text, person=args.person, persona=args.persona))
    _render(p)


def assume(factory: Factory, args: Any, out: Any) -> None:
    p = factory.project(args.pid)
    canon = Canon(p)
    qid = question_id(canon, args.qid)
    q = canon.question(qid)
    out(canon.assume(qid, q["opinions"].get(q["perspective"], "") or "as the panel proposed",
                     chosen_by=args.person, persona=args.persona))
    _render(p)


def _render(p: Any) -> None:
    from kernel.intake import render_brief

    render_brief(p)


def _ids(ids: list[str]) -> str:
    more = len(ids) - SHOWN
    return ", ".join(ids[:SHOWN]) + (f" and {more} more" if more > 0 else "")


def _open_questions(canon: Canon) -> str:
    open_ = [f"{q['id']} (card {q['card']})" if q.get("card") else q["id"] for q in canon.questions("open")]
    return (f"its open questions are {_ids(open_)}; `answer` takes a Q-id or the question card's C-id" if open_
            else "it has no open question (`rihmasto status <pid>` shows its cards)")


def _project_ids(factory: Factory) -> str:
    ids = [p.pid for p in factory.projects()]
    return f"the projects are {_ids(ids)} (`rihmasto status` lists them)" if ids else "this home has no project yet"


def explain(factory: Factory, args: Any, exc: BaseException) -> str:
    """One line for a refused chain command: what was wrong and what to use instead."""
    said = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
    if not isinstance(exc, KeyError):
        return said
    if said.startswith("no project"):
        return f"{said.split(' in ', 1)[0]}: {_project_ids(factory)}"
    pid = getattr(args, "pid", None)
    try:
        canon = Canon(factory.project(pid)) if pid else None
    except (KeyError, OSError):
        canon = None
    if canon is None:
        return said
    if QUESTION_ID.match(said):
        return f"no question {said} in {pid}: {_open_questions(canon)}"
    if CARD_ID.match(said):
        cards = [c["id"] for c in canon.cards()]
        return f"no card {said} in {pid}: " + (f"its open cards are {_ids(cards)}" if cards else "it has no open card")
    return said
