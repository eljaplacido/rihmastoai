"""Changing a project's posture during the run (kernel/posture.py), never silently.

`consequences` compares the effects before and after and says, for each change, whether it acts now
(on the next step of this run, or on records that exist: open assumptions, a spec not yet approved, a
release on its way) or later (the next intake reading, the next plan, the next release). `change`
checks who may make it (a person with a setter persona; loosening it needs a business owner, IT or
compliance), applies the mode and maturity, records `posture_changed` with who, why and both lists,
re-checks a spec still waiting for approval, and withdraws go-ahead cards the new posture no longer
needs. A project without a posture may take one the same way: its "before" is how it runs today (its
own mode and maturity, the autonomy cap alone, the maturity's own gates).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kernel.canon import CARD_DECIDERS, Canon, DecisionRefused
from kernel.people import is_person
from kernel.posture import (
    EVIDENCE_LEVELS,
    LOOSENERS,
    MODE_MEANING,
    MODE_RANK,
    PERSPECTIVE_NAME,
    POSTURES,
    SETTERS,
    TOPICS,
    baseline,
    effects,
    lines,
    record_of,
)
from kernel.store import MATURITIES

FACTORY_PID = "_factory"      # kernel.learn.FACTORY_PID: the factory's own canon takes no posture


def _looser_rungs(b: Mapping[str, Any], a: Mapping[str, Any]) -> list[str]:
    """A higher autonomy, a looser mode, a lower maturity (fewer of the maturity's own gates)."""
    out = [f"autonomy {b['autonomy']} to {a['autonomy']}"] if a["autonomy"] > b["autonomy"] else []
    if b.get("mode") in MODE_RANK and MODE_RANK[a["mode"]] < MODE_RANK[b["mode"]]:
        out.append(f"mode {b['mode']} to {a['mode']}")
    if b.get("maturity") in MATURITIES and MATURITIES.index(a["maturity"]) < MATURITIES.index(b["maturity"]):
        out.append(f"maturity {b['maturity']} to {a['maturity']}")
    return out


def _dropped_checks(b: Mapping[str, Any], a: Mapping[str, Any]) -> list[str]:
    """Plan approval, confirmation, a scan, a red-team layer, a blocking level, evidence or a spec topic."""
    out = [f"no {said}" for key, said in (("plan_approval", "plan approval at any maturity"),
                                          ("confirm", "confirmation by name")) if b[key] and not a[key]]
    bg, ag = b["gate"], a["gate"]
    out += ["no security scan required"] if bg["scan"] and not ag["scan"] else []
    out += [f"no red team {x} layer" for x in bg["redteam"] if x not in ag["redteam"]]
    out += [f"{x} findings no longer block" for x in bg["block_on"] if x not in ag["block_on"]]
    if EVIDENCE_LEVELS.index(ag["evidence"]) < EVIDENCE_LEVELS.index(bg["evidence"]):
        out.append(f"evidence {bg['evidence']} to {ag['evidence'] or 'none'}")
    dropped = [TOPICS[t][1] for t in b["spec"]["topics"] if t not in a["spec"]["topics"]]
    return out + (["the spec no longer has to cover " + ", ".join(dropped)] if dropped else [])


def loosens(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    """What the change makes less strict: a higher autonomy, a looser mode, a lower maturity (fewer of
    the maturity's own gates), or a check it drops."""
    return _looser_rungs(before, after) + _dropped_checks(before, after)


def _state(project: Any) -> dict[str, Any]:
    from kernel.posture_rules import _latest_release

    rel = _latest_release(project)
    return {"intake": project.path("source.json").exists(), "spec": project.path("spec.json").exists(),
            "compiled": project.path("contract.json").exists() and project.meta.get("contract_revision") is not None,
            "release": rel if rel and rel.get("state") in ("running", "waiting") else None,
            "assumptions": [a["id"] for a in Canon(project).assumptions("open")]}


def _intake_lines(b: Mapping[str, Any], a: Mapping[str, Any], st: Mapping[str, Any], out: dict) -> None:
    when = "later" if st["intake"] else "now"
    if a["mode"] != b["mode"]:
        out[when].append(f"mode {b['mode']} to {a['mode']}: {MODE_MEANING[a['mode']]}"
                         + ("; questions already settled stay as they are, the next reading (a new requirement or "
                            "a change) follows the new mode" if st["intake"] else ""))
    if a.get("intake") != b.get("intake"):
        out[when].append("the panel's question budget and emphasis: " + ", ".join(
            f"{PERSPECTIVE_NAME[p]} {n}" for p, n in a["intake"]["budget"].items())
            + (" (from the next reading)" if st["intake"] else ""))


def _topic_lines(b: Mapping[str, Any], a: Mapping[str, Any], st: Mapping[str, Any], out: dict) -> None:
    if a["spec"]["topics"] == b["spec"]["topics"]:
        return
    said = ", ".join(TOPICS[t][1] for t in a["spec"]["topics"]) or "nothing beyond the maturity's own (no extra topic)"
    if st["compiled"]:
        out["later"].append(f"the next spec (after a change) must cover: {said}")
    elif st["spec"]:
        out["now"].append(f"the spec waiting for approval is checked again for: {said}")
    else:
        out["now"].append(f"the analyst must cover: {said}")


def _spec_lines(b: Mapping[str, Any], a: Mapping[str, Any], st: Mapping[str, Any], out: dict) -> None:
    _topic_lines(b, a, st, out)
    plan_now = a["plan_approval"] and not b["plan_approval"]
    if plan_now or (b["plan_approval"] and not a["plan_approval"]):
        said = "a person approves the plan at any maturity" if plan_now else "plan approval follows the maturity again"
        out["later" if st["compiled"] else "now"].append(said + (" (the next plan)" if st["compiled"] else ""))
    if a["confirm"] and not b["confirm"]:
        stands = "; the current contract stands as it was approved, the next plan is confirmed"
        out["later" if st["compiled"] else "now"].append(
            "approving the plan confirms each requirement by name" + (stands if st["compiled"] else ""))
        if st["assumptions"]:
            out["now"].append(f"confirmation reopened: {', '.join(st['assumptions'])} must be confirmed or refuted by "
                              "a person before the next build")
        else:
            out["later"].append("every assumption made from now on is confirmed by a person before a build")


def _run_lines(b: Mapping[str, Any], a: Mapping[str, Any], st: Mapping[str, Any], out: dict) -> None:
    from kernel.autonomy import LEVELS

    if a["autonomy"] != b["autonomy"]:
        out["now"].append(f"from the next step the factory acts alone up to level {a['autonomy']} "
                          f"({LEVELS[a['autonomy']]}); a step above it waits for a person's go-ahead card")
    rel = st["release"]
    if a["maturity"] != b.get("maturity"):
        if rel is not None:
            out["now"].append(f"release {rel['release']}, on its way at {rel.get('maturity')}, is superseded at the "
                              "next delivery: its approvals were for the earlier plan")
        out["later"].append(f"the next release follows the {a['maturity']} plan")
    if a["gate"] != b["gate"]:
        gl = lines(a)["gates"][1:]
        if rel is not None:
            out["now"].append(f"release {rel['release']} meets the new gate at its next step: " + " ".join(gl))
        else:
            out["later"].append("every release from now on: " + " ".join(gl))


def consequences(project: Any, before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, list[str]]:
    """What a change of posture does now and what it does later, by rule. ``before`` is the project's
    `baseline` (its posture's effects, or how it runs without one)."""
    st, out = _state(project), {"now": list[str](), "later": list[str]()}
    _intake_lines(before, after, st, out)
    _spec_lines(before, after, st, out)
    _run_lines(before, after, st, out)
    return out


def proposed(project: Any, name: str, weights: Mapping[str, Any] | None = None, *, maturity: str | None = None,
             mode: str | None = None) -> dict[str, Any]:
    """The effects ``name`` would have on this project: its maturity kept where the posture runs at it,
    else the posture's own; its profile's screens."""
    from kernel.posture import screens_of

    if project.pid == FACTORY_PID:
        raise DecisionRefused("the factory's own canon takes no posture: a posture is for a project")
    if name not in POSTURES:
        raise ValueError(f"posture must be one of {', '.join(POSTURES)}, got {name!r}")
    meta = project.meta
    keep = meta.get("maturity") if meta.get("maturity") in POSTURES[name]["maturities"] else None
    return effects(name, weights, maturity=maturity or keep, mode=mode, screens=screens_of(meta.get("profile")))


def what_changes(project: Any, after: Mapping[str, Any]) -> dict[str, Any]:
    """Before anyone changes it: what loosens, and what the change does now and later."""
    before = baseline(project)
    return {"loosens": loosens(before, after), **consequences(project, before, after)}


def _settle_plan(project: Any, spec: dict[str, Any], person: str) -> list[str]:
    """An open plan card the new posture no longer needs is withdrawn; one whose text or deciders the
    posture changes is withdrawn too, and the next run opens it again as the new posture says."""
    from kernel.plan import _cards, required, summary
    from kernel.posture_rules import plan_deciders, plan_note

    done, needed = [], required(project)
    want = (summary(spec) + plan_note(project, spec), list(plan_deciders(project, spec) or CARD_DECIDERS["approval"]))
    for card in _cards(project, state="open"):
        if needed and (card.get("body"), list(card.get("deciders") or [])) == want:
            continue
        Canon(project).close(card["id"], f"the posture changed by {person}: " + (
            "the plan card is opened again as the new posture says" if needed else "no person needs to approve the plan"))
        done.append(f"{card['id']} withdrawn" + ("" if needed else ": the plan needs no approval now"))
    return done


def _settle_now(project: Any, after: Mapping[str, Any], person: str) -> list[str]:
    """Apply what acts on existing records at once: re-check a spec still waiting for approval (and its
    plan card), withdraw go-ahead cards for steps the new autonomy lets the factory take alone, and set
    who decides the go-ahead cards still open."""
    from kernel.posture_rules import check_spec, confirmers, go_ahead_cards, narrow

    done = []
    spec = project.read("spec.json")
    if isinstance(spec, dict) and not project.path("contract.json").exists():
        missing = (check_spec(project, spec) or {}).get("missing") or []
        done.append("spec checked: " + (f"missing {', '.join(TOPICS[t][1] for t in missing)}" if missing
                                        else "every required topic covered"))
        done += _settle_plan(project, spec, person)
    for card in go_ahead_cards(project):
        if int((card.get("payload") or {}).get("needed", 4)) <= after["autonomy"]:
            Canon(project).close(card["id"], f"the posture changed by {person}: the factory goes ahead alone")
            done.append(f"{card['id']} withdrawn")
        elif narrow(project, card, confirmers(after), f"the posture changed by {person}") is not card:
            done.append(f"{card['id']} decided by {' or '.join(confirmers(after) or CARD_DECIDERS['approval'])}")
    return done


def change(project: Any, name: str, weights: Mapping[str, Any] | None = None, *, person: str, persona: str,
           reason: str, maturity: str | None = None, mode: str | None = None) -> dict[str, Any]:
    """A person changes the project's posture during the run, with a reason. Returns what it does now
    and later, as the ledger records it."""
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a posture is a person's choice")
    if persona not in SETTERS:
        raise DecisionRefused(f"a {persona} may not choose a posture; {', '.join(SETTERS)} may")
    if not str(reason or "").strip():
        raise ValueError("a posture change needs a reason")
    after = proposed(project, name, weights, maturity=maturity, mode=mode)
    said = what_changes(project, after)
    if said["loosens"] and persona not in LOOSENERS:
        raise DecisionRefused(f"the change loosens the posture ({'; '.join(said['loosens'])}): a "
                              f"{', '.join(LOOSENERS[:-1])} or {LOOSENERS[-1]} may, not a {persona}")
    old = record_of(project)
    rec = {"name": name, "weights": after["weights"], "chosen_by": person, "persona": persona,
           "at": project.factory.clock.stamp(), "reason": str(reason).strip()}
    project.update_meta(posture=rec, mode=after["mode"], maturity=after["maturity"])
    applied = _settle_now(project, after, person)
    project.log("posture_changed", {"from": old["name"] if old else None, "to": name, "weights": after["weights"],
                                    "raised": after["raised"], "by": person, "persona": persona,
                                    "reason": rec["reason"], "loosens": said["loosens"], "now": said["now"],
                                    "later": said["later"], "applied": applied, "shown": lines(after)})
    return {"project": project.pid, "posture": name, "weights": after["weights"], "mode": after["mode"],
            "maturity": after["maturity"], "loosens": said["loosens"], "now": said["now"], "later": said["later"],
            "applied": applied, "lines": lines(after)}
