"""Decision triage (FR-NVL1): of many open decisions, the few that block work, ranked with why, and one proposal that
assumes the rest, which the person confirms once and each is recorded as their delegated choice.

The owner (2026-11-25): "I got 50 decisions. Can you prioritize those that block work? And assume me the answers."

By rule, never by a model:

- **Blocking** are the cards the next step waits on (the same kinds the Inbox leads with: an incident, a stuck
  task, a plan to approve, a go-ahead, a blocking question, a validation, a hidden-test ruling, a go-live), ranked by
  how much work stands still behind each, plus any assumption that grew in importance and now blocks the next task
  (kernel/assumption_weight.py).
- **The rest** is assumed in one proposal: an open question goes on with the answer its perspective suggested (an
  assumption with a due date, open to a real answer later), a change or an update is deferred until it matters. A
  card with nothing to assume (no suggestion, or a kind only a person decides) stays with the person, said plainly.
- **Confirming** decides each through the canon's own rules, signed by the person (who may decide each kind is
  checked as in the Inbox), and records one ``triage_assumed`` entry naming what was assumed, deferred and left.
"""

from __future__ import annotations

from typing import Any

from kernel.canon import Canon, DecisionRefused, deciders_of

# What blocks work, most work standing still first; with why, in the reader's words.
BLOCKS = {
    "incident": (0, "production has an incident: it waits for someone to acknowledge it, roll back or open a defect"),
    "escalation": (1, "a task stopped after its quality check kept failing: the build waits until you retry, accept "
                      "or stop it"),
    "approval": (2, "nothing is built until the plan is approved"),
    "go_ahead": (3, "the first build waits for your go-ahead on the spec"),
    "question": (4, "the requirements cannot be written until this is answered"),
    "validation": (5, "the next step waits for your acceptance of what was built"),
    "holdout_ruling": (6, "a hidden test failed: decide whether the product or the test is wrong before the release"),
    "deploy_gate": (7, "the go-live waits for this approval"),
}
DEFER = ("change", "update")
REASON = "decision triage: assumed for now, as {person} delegated; reopen it when it matters"


class TriageRefused(ValueError):
    """A confirm Rihmasto does not take: the persona may decide none of the proposal, said with who may."""


def _word(persona: str) -> str:
    return persona.replace("_", " ")


def _for(persona: str | None, row: dict[str, Any]) -> dict[str, Any]:
    """A row the persona may not decide stays with those who may: it is never in that persona's proposal."""
    if persona is None or not row["assume"]["verdict"] or persona in row["deciders"]:
        return row
    who = " or ".join(_word(d) for d in row["deciders"]) or "a person"
    a = "an" if persona[:1] in "aeiou" else "a"
    return row | {"assume": {"verdict": None, "refused": True,
                             "said": f"{a} {_word(persona)} may not decide this: {who} decides it"}}


def _blocking(card: dict[str, Any]) -> bool:
    return card.get("blocking") is True or (card["kind"] in BLOCKS and card["kind"] != "question")


def _proposal_of(canon: Canon, card: dict[str, Any]) -> str:
    qid = (card.get("refs") or {}).get("question")
    if not qid:
        return ""
    try:
        q = canon.question(qid)
    except KeyError:
        return ""
    return str((q.get("opinions") or {}).get(q.get("perspective")) or "").strip() if q.get("status") == "open" else ""


def _assume_of(canon: Canon, card: dict[str, Any]) -> dict[str, Any]:
    """What assuming a non-blocking card means, or why it stays with a person."""
    kind = card["kind"]
    if kind == "question":
        said = _proposal_of(canon, card)
        if said:
            return {"verdict": "assume", "said": f"go on with the suggested answer: \"{said[:160]}\""}
        return {"verdict": None, "said": "no suggested answer to assume: answer it when it matters"}
    if kind in DEFER:
        return {"verdict": "defer", "said": "deferred until it matters; reopen it from Changes"}
    return {"verdict": None, "said": "only a person decides this kind: it stays with you, not blocking"}


def _row(card: dict[str, Any]) -> dict[str, Any]:
    return {"card": card["id"], "kind": card["kind"], "title": card.get("title") or card["id"],
            "deciders": list(deciders_of(card)), "refs": card.get("refs") or {}}


def _ranked(blocking: list[dict[str, Any]], grown: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The blocking cards, then the assumptions that now block the next step, numbered."""
    rows = [_row(c) | {"why": BLOCKS.get(c["kind"], (9, "the next step waits on it"))[1]} for c in blocking]
    rows += [{"card": None, "assumption": w["id"], "kind": "assumption", "title": w["text"], "deciders": [],
              "why": f"grew in importance and now blocks the next step: {w['blocks']} ({w['trigger']})"}
             for w in grown if w["blocking"]]
    return [r | {"rank": i} for i, r in enumerate(rows, 1)]


def triage(project: Any, persona: str | None = None) -> dict[str, Any]:
    """The project's open decisions: the blocking few ranked with why, and the one proposal that assumes the rest.
    With a ``persona``, the proposal holds only what that persona may decide; the rest says who decides it."""
    from kernel.assumption_weight import weights

    canon = Canon(project)
    cards = canon.cards(state="open")
    blocking = sorted((c for c in cards if _blocking(c)), key=lambda c: (BLOCKS.get(c["kind"], (9, ""))[0], c["id"]))
    grown = weights(project)
    rows = _ranked(blocking, grown)
    rest = [_for(persona, _row(c) | {"assume": _assume_of(canon, c)}) for c in cards if c not in blocking]
    take = [r for r in rest if r["assume"]["verdict"]]
    proposal = _proposal(rest, take)
    return {"project": project.pid, "title": project.meta.get("title") or project.pid, "persona": persona,
            "total": len(cards), "blocking": rows, "rest": rest, "proposal": proposal,
            "grew": [w for w in grown if w["grew"]],
            "said": said(len(cards), rows, take, proposal["stays"] - proposal["refused"])
            + _refused_said(proposal["refused"], persona)}


def _proposal(rest: list[dict[str, Any]], take: list[dict[str, Any]]) -> dict[str, Any]:
    verdicts = [r["assume"]["verdict"] for r in take]
    return {"cards": [r["card"] for r in take], "count": len(take), "assumed": verdicts.count("assume"),
            "deferred": verdicts.count("defer"), "stays": len(rest) - len(take),
            "refused": len([r for r in rest if r["assume"].get("refused")])}


def _refused_said(refused: int, persona: str | None) -> str:
    if not refused:
        return ""
    return (f" {refused} wait{'s' if refused == 1 else ''} on someone else: as {_word(persona or '')} you may not "
            "decide them.")


def said(total: int, blocking: list[dict[str, Any]], take: list[dict[str, Any]], stays: int) -> str:
    if not total and not blocking:
        return "Nothing waits on a decision here: no card is open."
    many = "s" if total != 1 else ""
    if blocking:
        lead = blocking[0]["card"] or blocking[0].get("assumption")
        head = (f"Of {total} open decision{many}, {len(blocking)} block{'s' if len(blocking) == 1 else ''} work: "
                f"first {lead}, because {blocking[0]['why']}.")
    else:
        head = f"None of the {total} open decision{many} blocks work."
    rest = (f" I propose to assume the other {len(take)}: each is recorded as your delegated choice and stays open to "
            "a real answer later." if take else "")
    left = f" {stays} stay{'s' if stays == 1 else ''} with you: nothing can be assumed for them." if stays else ""
    return head + rest + left


def _refuse_if_none(now: dict[str, Any], persona: str) -> None:
    refused = [r for r in now["rest"] if r["assume"].get("refused")]
    if refused and not now["proposal"]["cards"]:
        many = f"these {len(refused)} decisions" if len(refused) != 1 else "this decision"
        raise TriageRefused(f"as {_word(persona)} you may not decide {many}, so nothing was assumed: "
                            + "; ".join(f"{r['card']}: {r['assume']['said']}" for r in refused[:5]))


def _not_offered(row: dict[str, Any] | None) -> str:
    if row is not None and row["assume"].get("refused"):
        return str(row["assume"]["said"])
    return "not in the proposal now: it blocks work, is decided, or has nothing to assume"


def confirm(project: Any, *, person: str, persona: str, cards: list[str] | None = None) -> dict[str, Any]:
    """Assume the proposal's cards (all of them, or the ``cards`` named), each through the canon's own rules and signed;
    one ``triage_assumed`` record names the person, what was assumed, deferred and left, and why. A persona that may
    decide none of what would be assumed is refused with who may, and nothing is recorded."""
    now = triage(project, persona)
    _refuse_if_none(now, persona)
    offered = set(now["proposal"]["cards"])
    wanted = [c for c in (cards if cards is not None else now["proposal"]["cards"])]
    canon = Canon(project)
    assumed: list[str] = []
    deferred: list[str] = []
    left: list[dict[str, Any]] = []
    by_id = {r["card"]: r for r in now["rest"]}
    for cid in wanted:
        if cid not in offered:
            left.append({"card": cid, "why": _not_offered(by_id.get(cid))})
            continue
        try:
            _apply(canon, by_id[cid], person, persona)
        except (DecisionRefused, KeyError, ValueError) as exc:
            left.append({"card": cid, "why": str(exc)})
            continue
        (assumed if by_id[cid]["assume"]["verdict"] == "assume" else deferred).append(cid)
    record = {"person": person, "persona": persona, "assumed": assumed, "deferred": deferred, "left": left,
              "blocking": [r["card"] or r.get("assumption") for r in now["blocking"]],
              "basis": "decision triage by rule: blocking kinds first, the rest assumed as the person delegated"}
    project.log("triage_assumed", record)
    return record | {"triage": triage(project, persona)}


def _apply(canon: Canon, row: dict[str, Any], person: str, persona: str) -> None:
    verdict = row["assume"]["verdict"]
    reason = REASON.format(person=person)
    if verdict == "assume":
        qid = row["refs"].get("question")
        q = canon.question(qid)
        proposed = str((q.get("opinions") or {}).get(q.get("perspective")) or "").strip()
        canon.assume(qid, proposed, chosen_by=person, persona=persona)
    else:
        canon.decide(row["card"], "defer", person=person, persona=persona, reason=reason)
