"""Reading the canon, the releases and the ledger's rounds into the knowledge graph (kernel/graph.py).

The builder (kernel/graph_build.py) reads the spec versions, the contract and the tests on main; these
readers add the rest of a project's records, each link with its origin, its validity start and the
record that holds it:

- questions and their answers or assumptions; assumptions with their status;
- Inbox cards, as the ontology maps each `refs` key (a key it does not map is an `unmapped_ref`
  finding), and a triage's requirements, `model_proposed` until a person decides the card;
- decisions: who signed them, the card they decide, what they rest on, and when an approval went stale
  and because of which change;
- comments (what they are about, never their text, and never a target that is not a record id: a
  person typed it) and the signals routed to the project (never their text);
- releases (the requirements they carry, how far they got, their holdout verdicts in a closed shape and
  their reason through kernel.custody.custody_safe), capability packs, and the builder rounds.

Last, the canon is checked against the ledger (consistency). The graph is not measured, and the problem
names the record, when the canon holds:
- a question no question_added event records; a question answered, assumed or open other than the
  ledger's question_answered (by, persona) or question_assumed (assumption, chosen_by) event records it;
- an assumption no assumption_added event records, or whose status (open, confirmed, refuted) is not
  the one its assumption_settled event records (open when there is none);
- a decision no decision event records, or whose card, kind, verdict, person, persona or refs differ
  from that event, or whose approving flag is not the one the kernel gives its kind and verdict
  (kernel.canon.APPROVING);
- a stale flag no approvals_stale event records, or no stale flag where one does. Whether an approval
  went stale is read from the ledger's mark, never from the flag.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from kernel.canon import APPROVING
from kernel.custody import custody_safe
from kernel.verdicts import VERDICTS

if TYPE_CHECKING:
    from kernel.graph_build import Builder

FACTORY_PID = "_factory"          # kernel.learn.FACTORY_PID: the factory's own canon
RID = re.compile(r"[A-Z][A-Z0-9]*(-[A-Z0-9]+)+\Z")
CID = re.compile(r"[A-Z][A-Z0-9]*(-[A-Z0-9]+)*-AC-\d+\Z")
CARD = re.compile(r"\bC-\d+\b")
# The shape of the id a comment's target holds, by the kind of record it is about (Canon.COMMENT_TARGETS;
# a comment on the project links nothing). A target of any other shape is outside text and never repeated.
TARGET_IDS = {"requirement": RID, "criterion": CID, "task": re.compile(r"[A-Z][A-Z0-9]*-?[0-9]+[A-Z0-9-]*\Z"),
              "card": re.compile(r"C-\d+\Z"), "release": re.compile(r"\d+\Z")}
DECISION_LOGGED = ("card", "kind", "verdict", "person", "persona", "refs")
SETTLED = {"answered": ("question_answered", ("by", "persona")),
           "assumed": ("question_assumed", ("assumption", "chosen_by"))}


class At(NamedTuple):
    """A link to a plain id (R-1, R-1-AC-2) as it stood at a ledger sequence number: resolved, once
    every node exists, to the version in force then."""

    plain: str
    seq: int | None


def ids_of(value: Any) -> list[str]:
    """The ids a field holds: each item of a list, or the one value; nothing for an object or null."""
    items = value if isinstance(value, list) else [value]
    return [str(v) for v in items if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v)]


def records_of(value: Any) -> list[dict[str, Any]]:
    """The objects in a list of records; nothing when it is not a list."""
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def object_of(value: Any) -> dict[str, Any]:
    """An object, or an empty one when the value is not an object."""
    return value if isinstance(value, dict) else {}


def signals_name(project: Any) -> str:
    return "signals.json" if project.pid == FACTORY_PID else f"{FACTORY_PID}/signals.json"


# -- the canon -------------------------------------------------------------------------------------

def canon(b: Builder) -> None:
    b.assumed = records_of(b.load("canon/assumptions.json", []))
    for a in b.assumed:
        aid = str(a.get("id"))
        b.node(aid, "assumption", f"canon/assumptions.json#{aid}", since=b.seq("assumption_added", "id", aid),
               label=str(a.get("text", ""))[:160], status=a.get("status"), due=a.get("due"),
               perspective=a.get("perspective"), question=a.get("question"))
    b.questions = records_of(b.load("canon/questions.json", []))
    for pos, q in enumerate(b.questions):
        _question(b, q, pos)


def _question(b: Builder, q: dict[str, Any], pos: int) -> None:
    qid = str(q.get("id"))
    by = f"canon/questions.json#{qid}"
    b.node(qid, "question", by, n=pos, since=b.seq("question_added", "id", qid), label=str(q.get("text", ""))[:160],
           status=q.get("status"), perspective=q.get("perspective"), blocking=q.get("blocking"))
    answer = object_of(q.get("answer"))
    if q.get("status") == "answered" and answer.get("by"):
        b.link("answered_by", qid, b.person(str(answer["by"])), "person_confirmed",
               b.seq("question_answered", "id", qid), by, persona=answer.get("persona"))
    elif q.get("status") == "assumed" and answer.get("assumption"):
        origin = "person_confirmed" if answer.get("chosen_by") else "kernel"
        b.link("assumed_as", qid, str(answer["assumption"]), origin, b.seq("question_assumed", "id", qid), by)


def signals(b: Builder) -> None:
    """The signals routed to this project (or, for the factory's own canon, every signal)."""
    name, mine = signals_name(b.p), b.p.pid == FACTORY_PID
    for s in records_of(b.load(name, [])):
        routed = object_of(s.get("routed_to"))
        if not isinstance(s.get("id"), str) or (not mine and routed.get("project") != b.p.pid):
            continue
        by = f"{name}#{s['id']}"
        b.node(s["id"], "signal", by, since=b.seq("signal_received", "id", s["id"]) if mine else None,
               channel=s.get("channel"), state=s.get("state"))
        if not mine and isinstance(routed.get("card"), str):
            submitted = b.seq("change_submitted", "card", routed["card"])
            b.link("raised_from", routed["card"], s["id"], "kernel", submitted, by)


def link_refs(b: Builder, src: str, refs: dict[str, Any], since: int | None, by: str, *, approving: bool) -> None:
    """The links a card's or a decision's refs carry, as the ontology maps each key. A key it does
    not map is reported (unmapped_ref) and links nothing."""
    for key, value in refs.items():
        entry = b.onto.refs.get(key)
        if entry is None:
            b.finding("unmapped_ref", key=key, record=by, text=f"refs key {key!r} maps to no declared relation")
            continue
        rel = entry.get("relation")
        if rel is None:
            continue
        rel = "approves" if rel == "concerns" and approving else rel
        origin = "person_confirmed" if rel == "approves" else "kernel"
        for v in ids_of(value):
            b.link(rel, src, _ref_target(b, key, rel, v, since), origin, since, by)


def _ref_target(b: Builder, key: str, rel: str, value: str, since: int | None) -> str | At:
    if rel in ("rests_on", "about_criterion"):
        return At(value, since)
    if rel in ("concerns", "approves"):
        return f"release-{value}"
    if rel == "raised_from":
        b.node(value, "signal" if key == "signal" else "observation", f"refs.{key}")
    return value


def refs_attrs(refs: dict[str, Any]) -> dict[str, Any]:
    """What a card or decision rests on by plain id, and its scope: an approval goes stale by these."""
    rids = set(ids_of(refs.get("requirements"))) | set(ids_of(refs.get("requirement")))
    return {"rids": sorted(rids), "scope": refs.get("scope") if isinstance(refs.get("scope"), str) else None}


def cards(b: Builder) -> None:
    for name in sorted(n for n in b.paths if n.startswith("canon/inbox/")):
        c = b.load(name, None)
        if not isinstance(c, dict) or not isinstance(c.get("id"), str):
            b.finding("unreadable_record", record=name)
            continue
        refs, tri = object_of(c.get("refs")), object_of(object_of(c.get("payload")).get("triage"))
        since = b.seq("card_opened", "id", c["id"])
        b.node(c["id"], "card", name, since=since, card_kind=c.get("kind"), state=c.get("state"),
               triage_class=tri.get("class"), **refs_attrs(refs))
        link_refs(b, c["id"], refs, since, name, approving=False)
        # A model's list stays its proposal until a person decides the card; a ruling's is the kernel's.
        origin = ("kernel" if tri.get("by") == "ruling" else
                  "person_confirmed" if c.get("state") == "decided" else "model_proposed")
        at = b.seq("change_triaged", "card", c["id"])
        for rid in ids_of(tri.get("requirements")):
            b.link("touches", c["id"], At(rid, at), origin, at, f"{name}#triage")


def decisions(b: Builder) -> None:
    for seq, p in b.events.get("approvals_stale", []):
        for did in ids_of(p.get("decisions")):
            b.marks.setdefault(did, (seq, p))
    b.decided = records_of(b.load("canon/decisions.json", []))
    for pos, d in enumerate(b.decided):
        _decision(b, d, pos, b.marks.get(str(d.get("id"))))


def _decision(b: Builder, d: dict[str, Any], pos: int, mark: tuple[int, dict[str, Any]] | None) -> None:
    did = str(d.get("id"))
    by, since, refs = f"canon/decisions.json#{did}", b.seq("decision", "id", did), object_of(d.get("refs"))
    b.node(did, "decision", by, n=pos, since=since, card=d.get("card"), card_kind=d.get("kind"),
           verdict=d.get("verdict"), approving=bool(d.get("approving")), stale=mark is not None,
           stale_seq=mark[0] if mark else None, person=d.get("person"), persona=d.get("persona"), **refs_attrs(refs))
    if d.get("person"):
        b.link("signed_by", did, b.person(str(d["person"])), "person_confirmed", since, by, persona=d.get("persona"))
    if d.get("card"):
        b.link("decides", did, str(d["card"]), "person_confirmed", since, by)
    first = len(b.pending)
    link_refs(b, did, refs, since, by, approving=bool(d.get("approving")))
    if mark is None:
        return
    for e in b.pending[first:]:          # the approval no longer holds: what it rested on ends here
        if e["rel"] in ("rests_on", "approves"):
            e["valid_to"] = mark[0]
    changed: list[str | At] = list(CARD.findall(str(mark[1].get("reason") or "")))
    for target in changed or [At(r, mark[0]) for r in ids_of(mark[1].get("requirements"))]:
        b.link("invalidated_by", did, target, "kernel", mark[0], f"ledger.jsonl#{mark[0]}")


def comments(b: Builder) -> None:
    for pos, c in enumerate(records_of(b.load("canon/comments.json", []))):
        cmid = str(c.get("id"))
        by, since, target = f"canon/comments.json#{cmid}", b.seq("comment", "id", cmid), object_of(c.get("target"))
        kind, tid = str(target.get("kind")), str(target.get("id", ""))
        known = kind in TARGET_IDS or kind == "project"
        b.node(cmid, "comment", by, n=pos, since=since, target_kind=kind if known else None)
        if kind == "project":           # a comment on the project as a whole links nothing
            continue
        if not known or not TARGET_IDS[kind].match(tid):
            b.finding("dangling_ref", record=by, rel="about", source=cmid, target=None,
                      text="the comment's target is not a record id; what it says is not repeated")
            continue
        targets: dict[str, str | At] = {"requirement": At(tid, since), "criterion": At(tid, since),
                                        "release": f"release-{tid}"}
        b.link("about", cmid, targets.get(kind, tid), "person_confirmed", since, by)


# -- releases, packs and rounds ------------------------------------------------------------------

def releases(b: Builder) -> None:
    promoted: dict[str, set[str]] = defaultdict(set)
    for _, p in b.events.get("promoted", []):
        promoted[str(p.get("release"))].add(str(p.get("environment")))
    for name in sorted((n for n in b.paths if n.startswith("releases/")), key=lambda n: int(Path(n).stem)):
        rel = b.load(name, None)
        if isinstance(rel, dict) and isinstance(rel.get("release"), int):
            _release(b, rel, name, promoted.get(str(rel["release"]), set()))
        else:
            b.finding("unreadable_record", record=name)


def _release(b: Builder, rel: dict[str, Any], name: str, promoted: set[str]) -> None:
    n = rel["release"]
    nid, since = f"release-{n}", b.seq("release_started", "release", n)
    outcomes = {s.get("step"): s.get("outcome") for s in records_of(rel.get("steps"))}
    reached = promoted | ({"production"} if outcomes.get("promote:production") == "passed" else set())
    rids = ids_of(rel.get("requirements"))
    b.node(nid, "release", name, n=n, number=n, since=since, revision=rel.get("revision"), state=rel.get("state"),
           maturity=rel.get("maturity"), contract_revision=rel.get("contract_revision"),
           reason=custody_safe(rel.get("reason")), reached=sorted(reached), rids=rids)
    for rid in rids:
        b.link("carries", nid, At(rid, since), "kernel", since, name)
    for r in records_of(object_of(rel.get("holdouts")).get("results")):   # closed: a criterion id, a named verdict
        cid, verdict = r.get("criterion"), r.get("verdict")
        if isinstance(cid, str) and CID.match(cid) and verdict in VERDICTS:
            ref = b.node(f"H-{cid}", "holdout_ref", name, criterion=cid)
            ref.setdefault("verdicts", {})[str(n)] = verdict


def packs(b: Builder) -> None:
    for pos, h in enumerate(records_of(b.load("packs.json", []))):
        if not h.get("version"):
            continue
        v = str(h["version"])
        by, since = f"packs.json#{v}", b.seq("pack_versioned", "version", v)
        b.node(f"pack-{v}", "pack", by, n=pos, since=since, version=v, content_sha256=h.get("content_sha256"))
        if isinstance(h.get("release"), int):
            b.link("versions", f"pack-{v}", f"release-{h['release']}", "kernel", since, by)


def rounds(b: Builder) -> None:
    for seq, p in b.events.get("cell_ran", []):
        if not isinstance(p.get("task"), str):
            continue
        nid, by = f"round:{p['task']}/{p.get('round')}@{seq}", f"ledger.jsonl#{seq}"
        b.node(nid, "round", by, since=seq, task=p["task"], round=p.get("round"))
        b.link("round_of", nid, p["task"], "kernel", seq, by)
        for m in dict.fromkeys(str(x) for x in (p.get("model"), p.get("final_model")) if x):
            b.node(f"model:{m}", "model", by, name=m, label=m)
            b.link("ran_on", nid, f"model:{m}", "kernel", seq, by)
        if isinstance(p.get("head"), str):
            b.node(f"rev:{p['head']}", "revision", by, since=seq, sha=p["head"])
            b.link("produced", nid, f"rev:{p['head']}", "kernel", seq, by)
    for seq, p in b.events.get("merged", []):
        rev = b.parts.nodes.get(f"rev:{p.get('revision')}")
        if rev is not None:
            rev["merged"] = f"ledger.jsonl#{seq}"


# -- the canon against the ledger ---------------------------------------------------------------------

def consistency(b: Builder) -> None:
    """A record the ledger does not record as it stands makes the graph not measured (the module's
    docstring lists what is compared)."""
    b.parts.problems.extend(_questions_unrecorded(b) + _assumptions_unrecorded(b) + _decisions_unrecorded(b))


def _questions_unrecorded(b: Builder) -> list[str]:
    out: list[str] = []
    for q in b.questions:
        qid, answer, status = str(q.get("id")), object_of(q.get("answer")), str(q.get("status"))
        if b.seq("question_added", "id", qid) is None:
            out.append(f"canon/questions.json holds {qid}, which no question_added event in the ledger records")
        withdrawn = status == "withdrawn" and b.by_id.get(("question_withdrawn", qid)) is not None
        for settled, (event, keys) in SETTLED.items():
            logged = b.by_id.get((event, qid))
            if withdrawn and settled == object_of(q.get("withdrawn")).get("was"):
                continue        # settled once, then withdrawn (an assumption made for an old kind of work)
            if settled != status:
                if logged is not None:
                    out.append(f"canon/questions.json says {qid} is {status}, but a {event} event in the ledger "
                               f"records it {settled}")
                continue
            differ = [k for k in keys if logged is None or logged.get(k) != answer.get(k)]
            if differ:
                said = ", ".join(f"{k} {answer.get(k)}" for k in differ)
                out.append(f"canon/questions.json says {qid} is {status} ({said}), which no {event} event in the "
                           f"ledger records")
    return out


def _assumptions_unrecorded(b: Builder) -> list[str]:
    out: list[str] = []
    for a in b.assumed:
        aid, status = str(a.get("id")), a.get("status")
        if b.seq("assumption_added", "id", aid) is None:
            out.append(f"canon/assumptions.json holds {aid}, which no assumption_added event in the ledger records")
        settled = b.by_id.get(("assumption_settled", aid))
        logged = settled.get("status") if settled is not None else "open"
        if status != logged:
            out.append(f"canon/assumptions.json says {aid} is {status}, but the ledger records it {logged}"
                       + ("" if settled is not None else " (no assumption_settled event settles it)"))
    return out


def _decisions_unrecorded(b: Builder) -> list[str]:
    out: list[str] = []
    for d in b.decided:
        did, mark = str(d.get("id")), b.marks.get(str(d.get("id")))
        logged = b.by_id.get(("decision", did))
        if logged is None:
            out.append(f"canon/decisions.json holds {did}, which no decision event in the ledger records")
        else:
            differ = [k for k in DECISION_LOGGED if logged.get(k) != d.get(k)]
            if bool(d.get("approving")) != ((logged.get("kind"), logged.get("verdict")) in APPROVING):
                differ.append("approving")
            if differ:
                out.append(f"canon/decisions.json holds {did} with fields its decision event in the ledger does "
                           f"not record ({', '.join(differ)})")
        if d.get("stale") and mark is None:
            out.append(f"canon/decisions.json marks {did} stale, which no approvals_stale event records")
        elif mark is not None and not d.get("stale"):
            out.append(f"canon/decisions.json does not mark {did} stale, which the approvals_stale event at "
                       f"ledger seq {mark[0]} records")
    return out


READERS = (canon, signals, cards, decisions, comments, releases, packs, rounds)
