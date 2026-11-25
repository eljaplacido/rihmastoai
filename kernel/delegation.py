"""Delegated decisions (D-0007, D-0017): a person lets the factory's rules decide named card kinds.

A person whose persona may decide a kind of card can delegate that kind, on one project, until a time
at most a week away, to one of the factory's own rules. The pipeline asks ``consult`` before it waits
on a card (kernel/pipeline.py): a card of a delegated kind that the delegation's rule settles is decided
by the rule, in the delegating person's name and persona. The decision records ``"delegation": "DL-n"``
beside them (``kernel.people.DELEGATION``), and its reason says "by delegation DL-n". The ledger also
keeps a ``delegated_decision`` record with the rule and its basis: who delegated, what was assumed and
what proves it. A card the rule does not settle waits for a person, and the ledger says why, once.

The rules (``RULES``), one per kind, each deterministic:

- ``question``: **assume** every open question with the proposal of the perspective that asked it; a
  question with no proposal waits;
- ``approval``: **plan_when_tested** approves the plan (only the plan's card) when every requirement has
  a test the gate runs, every criterion names a check the factory runs (a test, a holdout scenario or a
  probe), the spec compiles to a contract with no violation, and nothing in it contradicts the paved road;
- ``escalation``: **retry_once** retries an escalated builder task once; when it escalates again, the
  rule stops and the card waits for a person. It never accepts work as it is, and never stops a build;
- ``go_ahead``: **go** says Go to the look at the spec before a first build at explore or demo maturity
  (kernel/go_ahead.py): the delegating person lets the spec be built as written.

Some kinds are never delegated, whatever the persona (``NEVER``): the deploy gate (it opens production),
trust (the owner's own act), a holdout ruling (the product or its scenario may be wrong, and only a person
can tell which), a connector (IT's act), a paved road (IT configures it) and a concept (the factory's own
card). A kind with no rule (validation, change, incident, update) stays with a person too. Revoking a
delegation stops it at once: the next card waits for a person. With access enforced (D-0016) a delegated
decision is checked again as the delegating identity, so a grant IT removes stops it too.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import re
from collections import Counter
from collections.abc import Callable, Iterator
from typing import Any

from kernel.canon import CARD_DECIDERS, CARD_VERDICTS, Canon, DecisionRefused
from kernel.people import DELEGATION, PERSONAS, SIGNER, Identity, is_person
from kernel.store import Project, updating_json

FILE = "delegations.json"
MAX_DAYS = 7
RULES: dict[str, dict[str, str]] = {
    "question": {"assume": "assume every open question: the asking perspective's proposal becomes an assumption "
                           "with a due date; a question with no proposal waits for a person"},
    "approval": {"plan_when_tested": "approve the plan when every requirement has a test the gate runs, every "
                                     "criterion names a check the factory runs, the spec compiles to a contract "
                                     "and nothing in it contradicts the paved road"},
    "escalation": {"retry_once": "retry an escalated task once; when it escalates again, stop and wait for a "
                                 "person (never accept as is, never stop the build)"},
    "go_ahead": {"go": "say Go to the look at the spec before the first build (explore and demo): the delegating "
                       "person lets the spec be built as written"},
}
DEFAULT_RULE = {kind: next(iter(rules)) for kind, rules in RULES.items()}
NEVER = {
    "deploy_gate": "the deploy gate opens production: IT decides it, every time",
    "trust": "trust grants a Gnomon surface: it stays the owner's own act (D-0007)",
    "holdout_ruling": "a failed holdout means the product or its scenario is wrong, and only a person can tell "
                      "which; the scenario stays in its custody",
    "connector": "turning a connector on lets Rihmasto reach an outside system: IT decides it, every time (D-0015)",
    "road": "a paved road is configured by IT on its own infrastructure, and the record names who did it",
    "runner": "a cell runner decides whether the rules are enforced during a run or checked after it: IT decides it, "
              "every time (D-0019)",
    "concept": "a concept is the factory's own card, not one project's",
}
_RELATIVE = re.compile(r"\+?(\d{1,4})\s*([mhd])\Z")
_UNIT = {"m": "minutes", "h": "hours", "d": "days"}
Verdict = tuple[str | None, str, dict[str, Any]]      # (a verdict, or None to wait; why; the basis)


# -- time ------------------------------------------------------------------------------------------

def stamp(at: dt.datetime) -> str:
    return at.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def when(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))


def until_of(text: object, now: dt.datetime) -> dt.datetime:
    """When a delegation ends: ``8h``, ``90m`` or ``2d`` from now, or a date and time (UTC unless it says
    otherwise). It is in the future and at most ``MAX_DAYS`` away."""
    raw = str(text or "").strip()
    rel = _RELATIVE.match(raw.lower())
    if rel:
        at = now + dt.timedelta(**{_UNIT[rel.group(2)]: int(rel.group(1))})
    else:
        try:
            at = when(raw)
        except ValueError:
            raise ValueError(f"--until is a time such as 8h, 2d or 2026-11-24T08:00Z, not {raw!r}") from None
        at = at.replace(tzinfo=dt.UTC) if at.tzinfo is None else at
    if at <= now:
        raise ValueError(f"a delegation ends in the future; {stamp(at)} has passed")
    if at - now > dt.timedelta(days=MAX_DAYS):
        raise ValueError(f"a delegation lasts at most {MAX_DAYS} days: delegate again to go on")
    return at.astimezone(dt.UTC).replace(microsecond=0)


# -- granting and revoking -------------------------------------------------------------------------

def refusal(kind: str, persona: str) -> str | None:
    """Why ``persona`` may not delegate ``kind`` (None when it may)."""
    if kind not in CARD_VERDICTS:
        return f"{kind!r} is not a kind of card (kinds: {', '.join(CARD_VERDICTS)})"
    if kind in NEVER:
        return f"a {kind} card is never delegated: {NEVER[kind]}"
    if kind not in RULES:
        return f"no rule decides a {kind} card yet: it stays with a person"
    if persona not in CARD_DECIDERS[kind]:
        return (f"a {persona} may not decide a {kind} card, so may not delegate it "
                f"(it may: {', '.join(CARD_DECIDERS[kind])})")
    return None


def _rules_for(kinds: list[str], rules: dict[str, str] | None) -> dict[str, str]:
    chosen = dict(rules or {})
    for kind in chosen:
        if kind not in kinds:
            raise ValueError(f"a rule for {kind} needs {kind} among the delegated kinds")
    for kind in kinds:
        rule = chosen.setdefault(kind, DEFAULT_RULE[kind])
        if rule not in RULES[kind]:
            raise ValueError(f"a {kind} card's rule is one of {', '.join(RULES[kind])}, not {rule!r}")
    return chosen


def _signer(person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a delegation names the person who delegates")
    if persona not in PERSONAS:
        raise DecisionRefused(f"persona must be one of {', '.join(PERSONAS)}, got {persona!r}")


def grant(project: Project, kinds: list[str], *, person: str, persona: str, until: object,
          rules: dict[str, str] | None = None, reason: str = "", run: str | None = None) -> dict[str, Any]:
    """A person delegates card kinds on this project to the factory's rules until a time. Refused,
    with the reason, for a kind that is never delegated, has no rule, or the persona may not decide."""
    from kernel.access import require

    _signer(person, persona)
    kinds = list(dict.fromkeys(k.strip() for k in kinds if k and k.strip()))
    if not kinds:
        raise ValueError(f"name the card kinds to delegate: {', '.join(RULES)}")
    refused = [why for why in (refusal(k, persona) for k in kinds) if why]
    if refused:
        raise DecisionRefused("; ".join(refused))
    chosen = _rules_for(kinds, rules)
    now = project.factory.clock.now()
    end = until_of(until, now)
    require(project, person, persona)   # with access enforced: the verified identity, granted here
    signer = SIGNER.get()
    with updating_json(project.path(FILE), []) as items:
        d: dict[str, Any] = {"id": f"DL-{len(items) + 1:03d}", "kinds": kinds, "rules": chosen, "person": person,
                             "persona": persona, "reason": str(reason or "").strip()[:2000], "at": stamp(now),
                             "until": stamp(end), "run": run, "revoked": None}
        if signer is not None and signer.name == person:
            d.update(identity=signer.id, groups=list(signer.groups))
        items.append(d)
    project.log("delegation_granted", {k: d[k] for k in ("id", "kinds", "rules", "person", "persona", "until",
                                                         "reason", "run")})
    return view(d, now)


def may_revoke(d: dict[str, Any], person: str, persona: str) -> bool:
    """The delegating person, or anyone whose persona may decide one of the delegated kinds."""
    return person == d["person"] or any(persona in CARD_DECIDERS.get(k, ()) for k in d["kinds"])


def revoke(project: Project, did: str, *, person: str, persona: str, reason: str = "",
           any_persona: bool = False) -> dict[str, Any]:
    """Stop a delegation at once: from now on its cards wait for a person. ``any_persona`` is the
    autopilot's stop (kernel/autopilot.py), which its own rule allows."""
    from kernel.access import require

    _signer(person, persona)
    now = project.factory.clock.now()
    with updating_json(project.path(FILE), []) as items:
        d = next((x for x in items if x["id"] == did), None)
        if d is None:
            raise KeyError(f"no delegation {did} on {project.pid}")
        if not any_persona and not may_revoke(d, person, persona):
            raise DecisionRefused(f"a {persona} may not revoke {did}: {d['person']} or a persona that decides "
                                  f"{', '.join(d['kinds'])} may")
        if d["revoked"]:
            raise DecisionRefused(f"{did} was already revoked by {d['revoked']['by']}")
        require(project, person, persona)
        d["revoked"] = {"by": person, "persona": persona, "at": stamp(now), "reason": str(reason or "").strip()[:2000]}
    project.log("delegation_revoked", {"id": did, "by": person, "persona": persona, "reason": d["revoked"]["reason"]})
    return view(d, now)


def state_of(d: dict[str, Any], now: dt.datetime) -> str:
    return "revoked" if d.get("revoked") else "expired" if when(d["until"]) <= now else "active"


def view(d: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
    """A delegation as people read it: its state now, and each rule in words."""
    return {**d, "state": state_of(d, now), "rule_text": {k: RULES[k][r] for k, r in d["rules"].items()}}


def delegations(project: Project) -> list[dict[str, Any]]:
    now = project.factory.clock.now()
    return [view(d, now) for d in project.read(FILE, []) or []]


def active(project: Project, kind: str) -> dict[str, Any] | None:
    """The newest delegation in force on this project that covers ``kind``, or None."""
    now = project.factory.clock.now()
    live = [d for d in project.read(FILE, []) or [] if kind in d["kinds"] and state_of(d, now) == "active"
            and (d.get("agent") or {}).get("kind") != "bridge"]    # a named agent decides itself (agent_personas)
    return live[-1] if live else None


# -- the rules -------------------------------------------------------------------------------------

def _assume(project: Project, card: dict[str, Any], d: dict[str, Any]) -> Verdict:
    canon = Canon(project)
    qid = (card.get("refs") or {}).get("question")
    q = next((x for x in canon.questions("open") if x["id"] == qid and x.get("card") == card["id"]), None)
    if q is None:
        return None, f"{card['id']} puts no open question", {}
    proposal = str((q.get("opinions") or {}).get(q["perspective"]) or "").strip()
    if not proposal:
        return None, f"the {q['perspective']} perspective proposed no answer to {qid}: a person answers it", {}
    return "assume", f"{qid} assumed as its {q['perspective']} perspective proposed", \
        {"question": qid, "perspective": q["perspective"], "assumed": proposal[:300], "blocking": q["blocking"]}


def _plan_counts(reqs: list[dict[str, Any]]) -> dict[str, int]:
    """The plan's requirements and criteria, and its criteria by the kind of check that proves them."""
    from kernel.spec import KINDS

    kinds = Counter(c.get("kind") for r in reqs for c in r.get("acceptance") or [])
    return {"requirements": len(reqs), "criteria": sum(kinds.values()), **{k: kinds[k] for k in KINDS}}


def _plan_gaps(project: Project, spec: dict[str, Any]) -> tuple[list[str], dict[str, int]]:
    """What stops the rule from approving the plan (none: it may), and the plan's counts."""
    from kernel.compile import CompileError, to_contract
    from kernel.roads import road_conflicts
    from kernel.spec import KINDS

    reqs = [r for r in spec.get("requirements") or [] if r.get("provenance") != "withdrawn"]
    gaps = []
    for r in reqs:
        checks = [c.get("kind") for c in r.get("acceptance") or []]
        if "test" not in checks:
            gaps.append(f"{r['id']} has no test the gate runs")
        gaps += [f"{r['id']} has a criterion that names no check the factory runs" for k in checks if k not in KINDS]
    gaps += [f"contradicts the paved road: {c}" for c in road_conflicts(spec)]
    if not gaps:
        try:
            to_contract(project, spec)
        except CompileError as exc:
            gaps.append(f"the spec does not compile to a contract: {exc}")
    return gaps, _plan_counts(reqs)


def _plan_when_tested(project: Project, card: dict[str, Any], d: dict[str, Any]) -> Verdict:
    refs = card.get("refs") or {}
    if refs.get("scope") != "plan":
        return None, f"{card['id']} is not the plan's approval: only the plan is delegated", {}
    version = int(project.meta.get("spec_version", 1))
    spec = project.read("spec.json") or {}
    if refs.get("spec_version") != version or not spec.get("requirements"):
        return None, f"{card['id']} is for spec version {refs.get('spec_version')}, not the current {version}", {}
    gaps, counts = _plan_gaps(project, spec)
    basis = {"spec_version": version, **counts}
    if gaps:
        return None, "the plan waits for a person: " + "; ".join(gaps[:5]), basis | {"gaps": gaps[:20]}
    return "approve", (f"every one of {counts['requirements']} requirements has a test, every one of "
                       f"{counts['criteria']} criteria names a check, and the spec compiles"), basis


def _retry_once(project: Project, card: dict[str, Any], d: dict[str, Any]) -> Verdict:
    refs = card.get("refs") or {}
    task = refs.get("task")
    if refs.get("workspace") or not task:
        return None, f"{card['id']} is a person's own workspace submission: they decide it", {}
    earlier = [r for r in project.ledger().of_kind("delegated_decision")
               if r["event"]["payload"].get("delegation") == d["id"] and r["event"]["payload"].get("task") == task]
    if earlier:
        return None, f"{task} escalated again after the delegated retry: the rule stops, a person decides", \
            {"task": task, "retried_on": earlier[0]["event"]["payload"].get("card")}
    objections = (card.get("payload") or {}).get("objections") or []
    return "retry", f"{task} is retried once under the rule", {"task": task, "objections": len(objections)}


def _go(project: Project, card: dict[str, Any], d: dict[str, Any]) -> Verdict:
    spec = project.read("spec.json") or {}
    return "go", f"the spec is built as written ({len(spec.get('requirements') or [])} requirements)", \
        {"spec_version": (card.get("refs") or {}).get("spec_version")}


RULE_FN: dict[str, Callable[[Project, dict[str, Any], dict[str, Any]], Verdict]] = {
    "assume": _assume, "plan_when_tested": _plan_when_tested, "retry_once": _retry_once, "go": _go}


# -- the pipeline asks before it waits -------------------------------------------------------------

@contextlib.contextmanager
def acting_for(d: dict[str, Any]) -> Iterator[None]:
    """Carry out a decision under delegation ``d``: its records name the delegation, and with access
    enforced the delegating identity is checked again, as it was when it delegated (none: refused)."""
    from kernel.access import signing

    ident = Identity(d["identity"], d["person"], tuple(d.get("groups") or ())) if d.get("identity") else None
    token = DELEGATION.set((d["id"], d["person"]))
    try:
        with signing(ident):
            yield
    finally:
        DELEGATION.reset(token)


def _declined(project: Project, d: dict[str, Any], card: dict[str, Any], rule: str, why: str,
              basis: dict[str, Any]) -> None:
    """Say once, per delegation and card, why the rule left a card to a person."""
    seen = any(r["event"]["payload"].get("delegation") == d["id"] and r["event"]["payload"].get("card") == card["id"]
               for r in project.ledger().of_kind("delegation_declined"))
    if not seen:
        project.log("delegation_declined", {"delegation": d["id"], "card": card["id"], "kind": card["kind"],
                                            "rule": rule, "why": why[:500], "basis": basis})


def _candidates(project: Project, waiting: list[Any]) -> list[dict[str, Any]]:
    """The open cards the run waits on; with questions among them, every open question card too."""
    canon = Canon(project)
    cards = []
    for cid in dict.fromkeys(w for w in waiting if isinstance(w, str)):
        with contextlib.suppress(KeyError):
            cards.append(canon.get_card(cid))
    if any(c["kind"] == "question" for c in cards):
        cards += [c for c in canon.cards(kind="question") if c["id"] not in {x["id"] for x in cards}]
    return [c for c in cards if c["state"] == "open"]


def _decide(project: Project, card: dict[str, Any], d: dict[str, Any]) -> dict[str, Any] | None:
    rule = d["rules"].get(card["kind"]) or DEFAULT_RULE[card["kind"]]
    verdict, why, basis = RULE_FN[rule](project, card, d)
    if verdict is None:
        _declined(project, d, card, rule, why, basis)
        return None
    try:
        with acting_for(d):
            dec = Canon(project).decide(card["id"], verdict, person=d["person"], persona=d["persona"],
                                        reason=f"by delegation {d['id']} ({rule}): {why}")
    except DecisionRefused as exc:
        _declined(project, d, card, rule, f"refused: {exc}", basis)
        return None
    out = {"card": card["id"], "kind": card["kind"], "verdict": verdict, "delegation": d["id"], "rule": rule,
           "decision": dec.get("id"), "person": d["person"], "persona": d["persona"], "why": why,
           **({"task": basis["task"]} if basis.get("task") else {}),
           **({"agent": d["agent"]["name"]} if d.get("agent") else {})}     # a persona given to an agent
    project.log("delegated_decision", out | {"basis": basis})
    return out


def consult(project: Project, waiting: list[Any]) -> list[dict[str, Any]]:
    """Decide what the delegations in force on this project settle among the cards the run waits on;
    the decisions made (none: the run waits for a person)."""
    done = []
    for card in _candidates(project, waiting):
        d = active(project, card["kind"])
        if d is None:
            continue
        out = _decide(project, card, d)
        if out is not None:
            done.append(out)
    if any(o["kind"] == "question" for o in done):
        from kernel.intake import render_brief

        render_brief(project)
    return done


def _records(project: Project, kind: str, did: str | None) -> list[dict[str, Any]]:
    rows = [dict(r["event"]["payload"], at=r["event"].get("at")) for r in project.ledger().of_kind(kind)]
    return [r for r in rows if did is None or r.get("delegation") == did]


def decided_under(project: Project, did: str | None = None) -> list[dict[str, Any]]:
    """The decisions delegations made on this project (one delegation's, when named), oldest first."""
    return _records(project, "delegated_decision", did)


def declined_under(project: Project, did: str | None = None) -> list[dict[str, Any]]:
    """The cards a delegation's rule left to a person, and why."""
    return _records(project, "delegation_declined", did)
