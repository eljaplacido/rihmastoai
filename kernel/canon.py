"""The canon: one shared truth per project (FR-S1).

It holds the goal, the brief, open questions, assumptions with due dates (FR-S4), decisions,
the Inbox (proposals waiting for a person) and the exchange (notes between agents) (FR-S3).

The Inbox is the only write path for human decisions (FR-M6). A decision on a card needs a
named person and a persona allowed to decide that kind of card, with a verdict that kind
allows. Every change to the canon is also appended to the project's ledger. A question card is
settled through its question: deciding it answers the question, or assumes it. Every change holds
the canon's lock (kernel.store.updating_json), so writers at once, in threads or processes, never
lose a card, a decision or a stale mark, and never take the same id. A card the decision record
says is decided stays decided, with that decision, even when a stale copy is written back over it.

A reason given on a holdout ruling may describe the holdout scenario, so it is kept in the holdout
custody (kernel/rulings.py); the canon and the ledger record only its sha256, its length and a
pointer to it (FR-O3-AC-3).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

from kernel.people import PERSONAS, is_person
from kernel.store import read_json, records_lock, updating_json, write_json, write_text

PERSPECTIVES = ("business", "end_user", "it_security", "operations", "delivery")

# What a person may say on each kind of card.
CARD_VERDICTS = {
    "question": ("answer", "assume"),
    "approval": ("approve", "reject"),
    "validation": ("accept", "fix", "change", "keep"),          # FR-R3
    "deploy_gate": ("approve", "refuse"),                        # FR-Q5
    "incident": ("acknowledge", "rollback", "open_defect"),
    "change": ("accept", "reject", "defer"),
    "escalation": ("retry", "accept_as_is", "stop"),
    "road": ("configured", "declined"),
    "trust": ("granted", "declined"),
    "holdout_ruling": ("product_defect", "scenario_defect"),
    "concept": ("validate", "park", "reject"),                   # the delivery square's concept check
    "update": ("trial", "decline", "defer"),                     # the updates inbox: a model, a CVE, drift
}

# Who may decide each kind of card. Questions are open to everyone.
CARD_DECIDERS = {
    "question": PERSONAS,
    "approval": ("business_owner", "product_owner", "developer"),
    "validation": ("business_owner", "product_owner"),
    "deploy_gate": ("it",),
    "incident": ("operations", "it", "developer"),
    "change": ("business_owner", "product_owner"),
    "escalation": ("developer", "business_owner", "product_owner"),
    "road": ("it",),
    "trust": ("it", "developer"),
    "holdout_ruling": ("developer", "product_owner", "business_owner"),
    "concept": ("business_owner", "product_owner"),
    "update": ("product_owner", "business_owner", "it", "developer", "compliance"),
}

APPROVING = {("approval", "approve"), ("validation", "accept"), ("deploy_gate", "approve"),
             ("change", "accept"), ("escalation", "accept_as_is")}

# Cards whose reasons may describe a holdout scenario: those reasons live in the holdout custody.
CUSTODY_KINDS = ("holdout_ruling",)
DECISION_ON_CARD = ("id", "verdict", "person", "persona", "reason", "at", "reason_custody")   # a card's copy


class DecisionRefused(ValueError):
    """A decision the Inbox does not accept: not a person, wrong persona, wrong verdict, or closed card."""


def _rests_on(decision: dict, req_ids: set) -> bool:
    """Whether an approval rests on one of the requirements, or on the release as a whole."""
    refs = decision.get("refs") or {}
    touched = set(refs.get("requirements", [])) | ({refs["requirement"]} if refs.get("requirement") else set())
    return bool(touched & req_ids) or refs.get("scope") == "release"


class Canon:
    def __init__(self, project):
        self.project = project
        self.dir = project.path("canon")
        self.clock = project.factory.clock
        self.lock = self.dir / ".canon.lock"     # every change to the canon holds it

    # -- files ------------------------------------------------------------------------------

    def init(self, goal: str = "") -> None:
        with self._locked():
            (self.dir / "inbox").mkdir(parents=True, exist_ok=True)
            (self.dir / "exchange").mkdir(parents=True, exist_ok=True)
            if not (self.dir / "goal.md").exists():
                write_text(self.dir / "goal.md", (goal.strip() + "\n") if goal else "")
            if not (self.dir / "brief.md").exists():
                write_text(self.dir / "brief.md", "")
            for name in ("questions.json", "assumptions.json", "decisions.json"):
                if not (self.dir / name).exists():
                    write_json(self.dir / name, [])

    def _locked(self) -> AbstractContextManager[None]:
        return records_lock(self.lock)

    def _edit(self, name: str) -> AbstractContextManager[list]:
        """Change one of the canon's lists under the canon's lock (kernel.store.updating_json)."""
        return updating_json(self.dir / name, [], lock=self.lock)

    def _load(self, name: str) -> list:
        return read_json(self.dir / name, [])

    def _log(self, kind: str, payload: dict) -> None:
        self.project.log(kind, payload)

    @staticmethod
    def _next_id(prefix: str, items: list, width: int = 3) -> str:
        return f"{prefix}-{len(items) + 1:0{width}d}"

    @staticmethod
    def _next_file(folder: Path, prefix: str) -> str:
        """The next id in a folder of numbered files: one past the highest taken, so none is written over."""
        numbers = [int(p.stem[len(prefix) + 1:]) for p in folder.glob(f"{prefix}-*.json")
                   if p.stem[len(prefix) + 1:].isdigit()]
        return f"{prefix}-{max(numbers, default=0) + 1:04d}"

    @staticmethod
    def _one(items: list, item_id: str) -> dict:
        found = next((x for x in items if x["id"] == item_id), None)
        if found is None:
            raise KeyError(item_id)
        return found

    @property
    def goal(self) -> str:
        return (self.dir / "goal.md").read_text(encoding="utf-8").strip()

    @property
    def brief(self) -> str:
        return (self.dir / "brief.md").read_text(encoding="utf-8")

    def write_brief(self, text: str) -> None:
        write_text(self.dir / "brief.md", text if text.endswith("\n") else text + "\n")
        self._log("brief_written", {"chars": len(text)})

    # -- questions ----------------------------------------------------------------------------

    def questions(self, status: str | None = None) -> list:
        qs = self._load("questions.json")
        return [q for q in qs if status is None or q["status"] == status]

    def question(self, qid: str) -> dict:
        return self._one(self._load("questions.json"), qid)

    def add_question(self, text: str, perspective: str, *, blocking: bool = False,
                     opinions: dict | None = None, rationale: str = "", options=None) -> dict:
        if perspective not in PERSPECTIVES:
            raise ValueError(f"perspective must be one of {PERSPECTIVES}, got {perspective!r}")
        with self._edit("questions.json") as qs:
            q = {"id": self._next_id("Q", qs), "text": text, "perspective": perspective,
                 "blocking": bool(blocking), "rationale": rationale, "opinions": dict(opinions or {}),
                 "options": [str(o).strip() for o in (options or []) if str(o).strip()][:4],
                 "status": "open", "answer": None, "card": None, "created": self.clock.stamp()}
            qs.append(q)
        self._log("question_added", {"id": q["id"], "perspective": perspective, "blocking": q["blocking"]})
        return q

    def add_opinion(self, qid: str, perspective: str, opinion: str) -> dict:
        """Keep each perspective's reading of a question side by side (FR-A7): never merged."""
        if perspective not in PERSPECTIVES:
            raise ValueError(f"perspective must be one of {PERSPECTIVES}, got {perspective!r}")
        with self._edit("questions.json") as qs:
            q = self._one(qs, qid)
            q["opinions"][perspective] = opinion
        self._log("opinion_added", {"question": qid, "perspective": perspective})
        return q

    def ask(self, qid: str) -> dict:
        """Put an open question to a person: it becomes an Inbox card."""
        with self._locked():
            q = self.question(qid)
            card = self.card("question", q["text"], body=q.get("rationale", ""),
                             refs={"question": qid, "perspective": q["perspective"]},
                             blocking=q["blocking"], payload={"opinions": q["opinions"]})
            self._update_question(qid, card=card["id"])
        return card

    def _card_to_decide(self, q: dict, verdict: str) -> str | None:
        """The question's card, decided with the question; None when it has none, or when its card was
        already decided with this verdict while the question stayed open (as decide once left it)."""
        c = self.get_card(q["card"]) if q.get("card") else None
        settled = c is not None and c["state"] == "decided" and (c.get("decision") or {}).get("verdict") == verdict
        return None if c is None or settled else c["id"]

    def _update_question(self, qid: str, **changes) -> dict:
        with self._edit("questions.json") as qs:
            q = self._one(qs, qid)
            q.update(changes)
        return q

    def answer(self, qid: str, text: str, *, person: str, persona: str) -> dict:
        """A person answers: the answer is the owner's word (provenance customer-confirmed)."""
        with self._locked():
            q = self.question(qid)
            if q["status"] != "open":
                raise DecisionRefused(f"{qid} is {q['status']}, not open")
            card = self._card_to_decide(q, "answer")
            if card:
                self._decide_card(card, "answer", person=person, persona=persona, reason=text)
            else:
                self._check_decider("question", "answer", person, persona)
                self._record_decision(None, "question", "answer", person, persona, text, {"question": qid})
            q = self._update_question(qid, status="answered", answer={"text": text, "by": person, "persona": persona,
                                                                      "at": self.clock.stamp()})
            self._log("question_answered", {"id": qid, "by": person, "persona": persona})
        return q

    def assume(self, qid: str, text: str, *, due_days: int = 14, chosen_by: str | None = None,
               persona: str | None = None) -> dict:
        """The factory answers for itself. The answer is an assumption with a due date (FR-S4).
        ``chosen_by`` names the person who pressed "let the factory assume", if anyone did."""
        with self._locked():
            q = self.question(qid)
            if q["status"] != "open":
                raise DecisionRefused(f"{qid} is {q['status']}, not open")
            if q.get("card") and chosen_by is None:
                raise DecisionRefused(f"{qid} was put to a person; only a person can let the factory assume")
            card = self._card_to_decide(q, "assume")
            if card and chosen_by is not None:
                self._decide_card(card, "assume", person=chosen_by, persona=persona or "concept_evaluator",
                                  reason="let the factory assume")
            elif chosen_by is not None:
                # A person chose to let the factory assume (the question has no card to decide): their decision.
                self._check_decider("question", "assume", chosen_by, persona or "concept_evaluator")
                self._record_decision(None, "question", "assume", chosen_by, persona or "concept_evaluator",
                                      "let the factory assume", {"question": qid})
            assumption = self.add_assumption(text, q["perspective"], due_days=due_days, question=qid)
            self._update_question(qid, status="assumed", answer={"text": text, "by": "factory",
                                                                  "assumption": assumption["id"],
                                                                  "chosen_by": chosen_by, "at": self.clock.stamp()})
            self._log("question_assumed", {"id": qid, "assumption": assumption["id"], "chosen_by": chosen_by})
        return assumption

    # -- assumptions --------------------------------------------------------------------------

    def assumptions(self, status: str | None = None) -> list:
        items = self._load("assumptions.json")
        return [a for a in items if status is None or a["status"] == status]

    def add_assumption(self, text: str, perspective: str, *, due_days: int = 14,
                       question: str | None = None) -> dict:
        if due_days < 0:
            raise ValueError("due_days must be zero or more")
        due = (self.clock.today() + dt.timedelta(days=due_days)).isoformat()
        with self._edit("assumptions.json") as items:
            a = {"id": self._next_id("A", items), "text": text, "perspective": perspective,
                 "question": question, "due": due, "status": "open", "created": self.clock.stamp()}
            items.append(a)
        self._log("assumption_added", {"id": a["id"], "due": due, "question": question})
        return a

    def overdue(self, today: dt.date | None = None) -> list:
        today = today or self.clock.today()
        return [a for a in self.assumptions("open") if dt.date.fromisoformat(a["due"]) < today]

    def settle_assumption(self, aid: str, *, confirmed: bool, person: str, persona: str,
                          correction: str = "") -> dict:
        """A person confirms an assumption, or refutes it. A refuted assumption opens a change card,
        because something built on it may now be wrong."""
        self._check_decider("question", "answer", person, persona)
        with self._locked():
            with self._edit("assumptions.json") as items:
                a = self._one(items, aid)
                if a["status"] != "open":
                    raise DecisionRefused(f"{aid} is {a['status']}")
                a["status"] = "confirmed" if confirmed else "refuted"
                a["settled"] = {"by": person, "persona": persona, "correction": correction, "at": self.clock.stamp()}
            self._record_decision(None, "question", "answer", person, persona,
                                  ("confirmed" if confirmed else "refuted: " + correction),
                                  {"assumption": aid, "question": a.get("question")})
            self._log("assumption_settled", {"id": aid, "status": a["status"], "by": person, "persona": persona})
            if not confirmed:
                self.card("change", f"Assumption {aid} was refuted",
                          body=f"Assumed: {a['text']}\nCorrection: {correction}",
                          refs={"assumption": aid}, payload={"source": persona, "text": correction})
        return a

    # -- the Inbox ----------------------------------------------------------------------------

    def cards(self, *, state: str | None = "open", kind: str | None = None,
              persona: str | None = None) -> list:
        """The Inbox's cards as the decision record has them, by state, kind and who may decide them."""
        inbox, decided = self.dir / "inbox", self._decided()
        paths = sorted(inbox.glob("C-*.json")) if inbox.exists() else []
        every = [self._as_recorded(read_json(p), decided) for p in paths]
        return [c for c in every if (state is None or c["state"] == state) and (kind is None or c["kind"] == kind)
                and (persona is None or persona in CARD_DECIDERS[c["kind"]])]

    def get_card(self, card_id: str) -> dict:
        c = read_json(self.dir / "inbox" / f"{card_id}.json")
        if c is None:
            raise KeyError(card_id)
        return self._as_recorded(c, self._decided())

    def _decided(self) -> dict[str, dict]:
        """Each decided card's decision, from the decision record: the first on it (a card takes one)."""
        return {d["card"]: d for d in reversed(self._load("decisions.json")) if d.get("card")}

    @staticmethod
    def _as_recorded(c: dict, decided: dict[str, dict]) -> dict:
        """A card as the decision record has it, with its copy of its decision. A card written back from a
        copy read before its decision (outside the canon's lock) is still decided, with that decision."""
        d = decided.get(c["id"]) if c["state"] == "open" else None
        if d is not None:
            c["state"], c["decision"] = "decided", {k: d[k] for k in DECISION_ON_CARD if k in d}
        return c

    def card(self, kind: str, title: str, *, body: str = "", refs: dict | None = None,
             payload: dict | None = None, blocking: bool = False) -> dict:
        if kind not in CARD_VERDICTS:
            raise ValueError(f"card kind must be one of {tuple(CARD_VERDICTS)}, got {kind!r}")
        inbox = self.dir / "inbox"
        with self._locked():
            inbox.mkdir(parents=True, exist_ok=True)
            c = {"id": self._next_file(inbox, "C"), "kind": kind, "title": title, "body": body,
                 "refs": dict(refs or {}), "payload": dict(payload or {}), "blocking": bool(blocking),
                 "state": "open", "deciders": list(CARD_DECIDERS[kind]), "verdicts": list(CARD_VERDICTS[kind]),
                 "created": self.clock.stamp(), "decision": None}
            write_json(inbox / f"{c['id']}.json", c)
            self._log("card_opened", {"id": c["id"], "kind": kind, "refs": c["refs"]})
        return c

    @contextmanager
    def edit_card(self, card_id: str) -> Iterator[dict]:
        """Every rewrite of a card, under the canon's lock: read as the decision record has it, changed in
        the block, written back. A block that raises changes nothing; a card that does not exist is a KeyError."""
        with updating_json(self.dir / "inbox" / f"{card_id}.json", None, lock=self.lock) as c:
            if c is None:
                raise KeyError(card_id)
            yield self._as_recorded(c, self._decided())

    def _check_decider(self, kind: str, verdict: str, person: str, persona: str) -> None:
        if not is_person(person):
            raise DecisionRefused(f"{person!r} is not a person; a decision needs a named person")
        if persona not in PERSONAS:
            raise DecisionRefused(f"persona must be one of {PERSONAS}, got {persona!r}")
        if verdict not in CARD_VERDICTS[kind]:
            raise DecisionRefused(f"a {kind} card takes {CARD_VERDICTS[kind]}, not {verdict!r}")
        if persona not in CARD_DECIDERS[kind]:
            raise DecisionRefused(f"a {persona} may not decide a {kind} card (deciders: {CARD_DECIDERS[kind]})")

    def _record_decision(self, card_id, kind, verdict, person, persona, reason, refs,
                         held: dict | None = None) -> dict:
        with self._edit("decisions.json") as items:
            d = {"id": self._next_id("D", items), "card": card_id, "kind": kind, "verdict": verdict,
                 "person": person, "persona": persona, "reason": reason, "refs": dict(refs or {}),
                 "approving": (kind, verdict) in APPROVING, "stale": False, "at": self.clock.stamp()}
            if held is not None:
                d["reason_custody"] = held
            items.append(d)
        keys = ("id", "card", "kind", "verdict", "person", "persona", "refs", "reason_custody")
        self._log("decision", {k: d[k] for k in keys if k in d})
        return d

    def _custody(self, card: dict, reason: str) -> tuple[str, dict | None]:
        """A reason on a holdout ruling may describe the scenario. It goes to the holdout custody;
        the canon and the ledger keep its sha256, its length and a pointer (FR-O3-AC-3)."""
        if card["kind"] not in CUSTODY_KINDS or not reason:
            return reason, None
        from kernel.rulings import HELD_REASON, hold_reason

        return HELD_REASON, hold_reason(self.project, reason, ref=card["id"])

    def decide(self, card_id: str, verdict: str, *, person: str, persona: str, reason: str = "") -> dict:
        """A person decides a card. An open question card is settled through its question, so it never
        stays open: `answer` answers it with the reason; `assume` assumes its perspective's proposal."""
        with self._locked():
            qid = self._open_question(self.get_card(card_id))
            if qid is None or verdict not in CARD_VERDICTS["question"]:
                return self._decide_card(card_id, verdict, person=person, persona=persona, reason=reason)
            self._settle(qid, verdict, person=person, persona=persona, reason=reason)
            return next(d for d in reversed(self._load("decisions.json")) if d["card"] == card_id)

    def _open_question(self, card: dict) -> str | None:
        """The question an open question card puts to a person, while that question is open on it."""
        qid = (card.get("refs") or {}).get("question") if card["kind"] == "question" else None
        q = next((x for x in self._load("questions.json") if x["id"] == qid), None) if qid else None
        return qid if q and card["state"] == "open" and q["status"] == "open" and q.get("card") == card["id"] else None

    def _settle(self, qid: str, verdict: str, *, person: str, persona: str, reason: str) -> None:
        self._check_decider("question", verdict, person, persona)
        if verdict == "answer":
            if not reason.strip():
                raise DecisionRefused(f"an answer to {qid} needs its text: give it as the reason")
            self.answer(qid, reason, person=person, persona=persona)
            return
        q = self.question(qid)
        proposed = str((q.get("opinions") or {}).get(q["perspective"]) or "").strip()
        if not proposed:
            raise DecisionRefused(f"the {q['perspective']} perspective proposed no answer to {qid}: answer it instead")
        self.assume(qid, proposed, chosen_by=person, persona=persona)

    def _decide_card(self, card_id: str, verdict: str, *, person: str, persona: str, reason: str = "") -> dict:
        with self._locked():
            c = self.get_card(card_id)
            if c["state"] != "open":
                raise DecisionRefused(f"{card_id} is {c['state']}")
            self._check_decider(c["kind"], verdict, person, persona)
            reason, held = self._custody(c, reason)
            d = self._record_decision(card_id, c["kind"], verdict, person, persona, reason, c["refs"], held)
            write_json(self.dir / "inbox" / f"{card_id}.json", self._as_recorded(c, {card_id: d}))
        return d

    def close(self, card_id: str, why: str, *, state: str = "withdrawn") -> dict:
        """The factory closes a card without a human decision: it was withdrawn (no longer needed),
        or resolved by the factory's own loop (for example a defect it repaired)."""
        if state not in ("withdrawn", "resolved"):
            raise ValueError("a card the factory closes is withdrawn or resolved")
        with self.edit_card(card_id) as c:
            c["state"] = state
            c["closed"] = {"why": why, "at": self.clock.stamp()}
        self._log("card_closed", {"id": card_id, "state": state, "why": why})
        return c

    # -- decisions and invalidation (FR-P5) -----------------------------------------------------

    def decisions(self, *, stale: bool | None = None) -> list:
        items = self._load("decisions.json")
        return [d for d in items if stale is None or d["stale"] == stale]

    def mark_stale(self, requirement_ids, *, reason: str) -> list:
        """An amendment or a rejection makes every approval resting on the changed requirements
        stale. A stale approval must be given again."""
        req_ids = set(requirement_ids)
        with self._edit("decisions.json") as items:
            hit = [d for d in items if d["approving"] and not d["stale"] and _rests_on(d, req_ids)]
            for d in hit:
                d.update(stale=True, stale_reason=reason, stale_at=self.clock.stamp())
        if hit:
            self._log("approvals_stale", {"decisions": [d["id"] for d in hit], "requirements": sorted(req_ids),
                                          "reason": reason})
        return hit

    # -- comments: people talk about the work without deciding anything ----------------------------

    COMMENT_TARGETS = ("requirement", "criterion", "task", "release", "card", "project")

    def comments(self, target: dict | None = None) -> list:
        items = self._load("comments.json")
        return items if target is None else [c for c in items if c["target"] == target]

    def comment(self, target: dict, text: str, *, person: str, persona: str) -> dict:
        """A remark on a requirement, task, release or card. It decides nothing; a product owner
        or business owner may later promote it into a change card."""
        if not is_person(person):
            raise DecisionRefused(f"{person!r} is not a person")
        if persona not in PERSONAS:
            raise DecisionRefused(f"persona must be one of {PERSONAS}, got {persona!r}")
        if not isinstance(target, dict) or target.get("kind") not in self.COMMENT_TARGETS or not target.get("id"):
            raise ValueError(f"a comment's target is one of {self.COMMENT_TARGETS} with an id")
        if not text.strip():
            raise ValueError("the comment is empty")
        with self._edit("comments.json") as items:
            c = {"id": self._next_id("CM", items), "target": {"kind": target["kind"], "id": str(target["id"])},
                 "text": text.strip(), "person": person, "persona": persona, "at": self.clock.stamp(),
                 "promoted_to": None}
            items.append(c)
        self._log("comment", {"id": c["id"], "target": c["target"], "person": person, "persona": persona})
        return c

    def promote_comment(self, comment_id: str, *, person: str, persona: str) -> dict:
        """Turn a comment into a change card, so it enters the change loop."""
        if persona not in ("product_owner", "business_owner"):
            raise DecisionRefused("only a product owner or business owner promotes a comment into a change")
        from kernel.change import submit

        with self._locked():
            c = next((x for x in self.comments() if x["id"] == comment_id), None)
            if c is None:
                raise KeyError(comment_id)
            if c["promoted_to"]:
                raise DecisionRefused(f"{comment_id} is already {c['promoted_to']}")
            card = submit(self.project, persona=persona, person=person,
                          text=f"[{c['target']['kind']} {c['target']['id']}] {c['text']} (comment by {c['person']})")
            with self._edit("comments.json") as items:
                self._one(items, comment_id)["promoted_to"] = card["id"]
            self._log("comment_promoted", {"id": comment_id, "card": card["id"], "by": person})
        return card

    # -- the exchange (agent to agent) ---------------------------------------------------------

    def note(self, author: str, text: str, refs: dict | None = None) -> dict:
        ex = self.dir / "exchange"
        with self._locked():
            ex.mkdir(parents=True, exist_ok=True)
            note = {"id": self._next_file(ex, "N"), "author": author, "text": text, "refs": dict(refs or {}),
                    "at": self.clock.stamp()}
            write_json(ex / f"{note['id']}.json", note)
        return note
