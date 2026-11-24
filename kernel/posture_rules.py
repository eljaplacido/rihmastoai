"""Where a project's posture (kernel/posture.py) acts on the chain. Each function does nothing for a
project without a posture, so such a project runs exactly as before.

- intake: `question_budget` and `panel_note` (each perspective's number of questions and what it weighs);
- spec: `spec_guidance`, `extra_requirements` and `check_spec` (the topics the analyst must cover,
  checked by rule and recorded; a spec that misses one waits for a person to approve the plan). The
  check is made again from the spec as it stands whenever it is asked (`missing_topics`), so a person's
  edit to the plan counts at once;
- plan: `plan_required`, `plan_note`, `plan_deciders` and `on_plan_approved` (approving the plan
  confirms each requirement in the approver's name where the posture confirms, so only the customer's
  side, a business owner or product owner, approves it then; approving a plan that misses a required
  topic waives a check, so only a business owner may; any topic approved without cover is recorded);
- autonomy: `clear`, asked by `kernel.autonomy.cleared_to_build` and `cleared_to_deliver`: every
  assumption confirmed before a build where the posture confirms, the security gate before a preview
  or demo landing where the posture requires a scan, and a person's go-ahead card for a step above the
  posture's autonomy (one card per step and revision; a declined card asks again on the next run; under
  a confirming posture only the customer's side gives it). A revision already built is not asked about
  again (`kernel.autonomy.cleared_to_build`);
- security: `block_on` and `gate_requirements`, asked by `kernel.security.security_gate`: the levels
  that block, the scan and red-team layers required, and the evidence pack required before a release
  lands on staging (pilot) or production. A requirement of the posture is not a finding: it cannot be
  accepted as a risk (`not_a_risk`).
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping
from typing import Any

from kernel.autonomy import BUILD_LEVEL, LANDING_LEVEL, LEVELS, AutonomyCapped
from kernel.canon import CARD_DECIDERS, Canon
from kernel.posture import LOOSENERS, TOPICS, of
from kernel.redteam import TOOL_NAME as REDTEAM

GO_AHEAD = "go_ahead"                       # an approval card's refs.scope
POSTURE_TOOL = "Rihmasto posture"
HUMAN_PROVENANCE = ("customer-confirmed", "customer-endorsed")
CUSTOMER = ("business_owner", "product_owner")   # who confirms in the customer's name


class Held(AutonomyCapped):
    """A step waits on a person under the project's posture: a go-ahead card, a confirmation or a gate."""

    def __init__(self, needed: int, autonomy: int, why: str, card: str | None = None):
        PermissionError.__init__(self, why)
        self.needed, self.cap, self.card = needed, autonomy, card


# -- intake --------------------------------------------------------------------------------------------

def question_budget(project: Any, perspective: str, default: int) -> int:
    eff = of(project)
    return int(eff["intake"]["budget"].get(perspective, default)) if eff else default


def panel_note(project: Any, perspective: str) -> str:
    """The posture's line at the end of one perspective's prompt; empty without a posture."""
    eff = of(project)
    if eff is None:
        return ""
    weigh = eff["intake"]["emphasis"].get(perspective) or []
    return (f"\nThis project's posture is **{eff['posture']}**. From your perspective ask at most "
            f"{eff['intake']['budget'][perspective]} questions (this replaces the number above)."
            + ("".join(f"\n- Weigh {x}." for x in weigh)) + "\n")


# -- spec ------------------------------------------------------------------------------------------------

def spec_guidance(project: Any) -> str:
    eff = of(project)
    if eff is None or not eff["spec"]["guidance"]:
        return ""
    return (f"\nThis project's posture is **{eff['posture']}**. The spec must also cover:\n"
            + "\n".join(f"- {g}" for g in eff["spec"]["guidance"]) + "\n")


def questions_to_settle(project: Any) -> list[dict[str, Any]]:
    """Under a confirming posture every question the panel asked is settled by a person before the spec
    is written, not only the blocking ones: each requirement then rests on a person's word."""
    eff = of(project)
    return Canon(project).questions("open") if eff is not None and eff["confirm"] else []


def extra_requirements(project: Any) -> int:
    """One more requirement allowed per topic the posture requires."""
    eff = of(project)
    return len(eff["spec"]["topics"]) if eff else 0


def _text_of(req: dict[str, Any]) -> str:
    crits = [f"{c.get('given', '')} {c.get('when', '')} {c.get('then', '')}" for c in req.get("acceptance", [])]
    return " ".join([str(req.get("statement", "")), *crits])


def coverage(spec: dict[str, Any], topics: list[str]) -> dict[str, Any]:
    """Which requirements cover each required topic, by the words their statements and criteria hold."""
    covered: dict[str, list[str]] = {}
    for t in topics:
        pat = re.compile(TOPICS[t][3], re.IGNORECASE)
        covered[t] = [r["id"] for r in spec.get("requirements", []) if pat.search(_text_of(r))]
    return {"topics": topics, "covered": covered, "missing": [t for t in topics if not covered[t]]}


def check_spec(project: Any, spec: dict[str, Any]) -> dict[str, Any] | None:
    """Check a new spec against the posture's topics, by rule, and record the result."""
    eff = of(project)
    if eff is None:
        return None
    result = coverage(spec, eff["spec"]["topics"]) | {"posture": eff["posture"]}
    project.log("posture_spec_checked", result)
    return result


def missing_topics(project: Any) -> list[str]:
    """The topics the posture requires that the spec as it stands does not cover (none without a spec)."""
    eff, spec = of(project), project.read("spec.json")
    if eff is None or not isinstance(spec, dict):
        return []
    return list(coverage(spec, eff["spec"]["topics"])["missing"])


# -- plan ------------------------------------------------------------------------------------------------

def plan_required(project: Any) -> bool:
    """The posture asks for plan approval at any maturity, or the spec misses a topic it requires."""
    eff = of(project)
    return bool(eff is not None and (eff["plan_approval"] or missing_topics(project)))


def plan_note(project: Any, spec: dict[str, Any]) -> str:
    """What approving the plan means under the posture, for the plan card's body."""
    eff = of(project)
    if eff is None:
        return ""
    lines = [f"Posture: {eff['posture']}."]
    check = coverage(spec, eff["spec"]["topics"])
    for t in check["topics"]:
        ids = check["covered"][t]
        lines.append(f"- {TOPICS[t][1]}: " + (f"covered by {', '.join(ids)}" if ids else "MISSING: no requirement "
                                              "covers it; edit or reject the plan, or a business owner approves "
                                              "it without"))
    if eff["confirm"]:
        loose = [r["id"] for r in spec.get("requirements", []) if r.get("provenance") not in HUMAN_PROVENANCE]
        lines.append("Approving confirms each requirement in your name"
                     + (f" ({', '.join(loose)} are not confirmed by anyone yet)." if loose else "."))
    who = plan_deciders(project, spec)
    if who:
        lines.append(f"Under the {eff['posture']} posture only a {' or '.join(x.replace('_', ' ') for x in who)} "
                     "approves this plan.")
    return "\n\n" + "\n".join(lines)


def plan_deciders(project: Any, spec: dict[str, Any]) -> tuple[str, ...] | None:
    """Who may approve the plan under the posture, when fewer than an approval card's own deciders: the
    customer's side where approving confirms each requirement in the approver's name, and one who may
    loosen the posture (of the approvers, a business owner) where a required topic is missing."""
    eff = of(project)
    if eff is None:
        return None
    who = [p for p in CARD_DECIDERS["approval"] if p in CUSTOMER or not eff["confirm"]]
    if coverage(spec, eff["spec"]["topics"])["missing"]:
        who = [p for p in who if p in LOOSENERS]
    return tuple(who) if tuple(who) != tuple(CARD_DECIDERS["approval"]) else None


def narrow(project: Any, card: dict[str, Any], who: tuple[str, ...] | None, why: str) -> dict[str, Any]:
    """Set who may decide ``card`` (kernel.canon refuses anyone else) and record it in the ledger;
    ``who`` None gives the card its kind's own deciders back."""
    want = list(who or CARD_DECIDERS[card["kind"]])
    if list(card.get("deciders") or []) == want:
        return card
    with Canon(project).edit_card(card["id"]) as c:
        c["deciders"] = want
    project.log("card_deciders_set", {"card": card["id"], "deciders": want, "why": why})
    return dict(card, deciders=want)


def confirmers(eff: Mapping[str, Any] | None) -> tuple[str, ...] | None:
    """Who speaks for the customer under a confirming posture: a go-ahead, an edit to the plan (which
    confirms the requirement) and the plan's approval are theirs, not the vendor's (a developer's)."""
    return CUSTOMER if eff is not None and eff["confirm"] else None


def _confirm(project: Any, spec: dict[str, Any], card: dict[str, Any]) -> list[str]:
    """Each requirement no named person confirmed becomes customer-confirmed by the approver."""
    from kernel.spec import render_spec_md
    from kernel.store import write_text

    d, done = card["decision"], []
    for r in spec.get("requirements", []):
        if r.get("provenance") not in HUMAN_PROVENANCE:
            r["confirmed"] = {"by": d["person"], "persona": d["persona"], "card": card["id"],
                              "was": r.get("provenance")}
            r.update(provenance="customer-confirmed", decided_by=d["person"])
            done.append(r["id"])
    if done:
        project.write("spec.json", spec)
        write_text(project.path("spec.md"), render_spec_md(spec))
    return done


def on_plan_approved(project: Any, card: dict[str, Any]) -> dict[str, Any] | None:
    """Under a posture, record what approving the plan meant: the requirements it confirmed in the
    approver's name (a confirming posture) and any required topic the person approved without cover."""
    eff, d = of(project), card["decision"]
    if eff is None:
        return None
    spec = project.read("spec.json") or {}
    done = _confirm(project, spec, card) if eff["confirm"] else []
    out = {"card": card["id"], "by": d["person"], "persona": d["persona"], "posture": eff["posture"],
           "confirmed": done, "approved_without": coverage(spec, eff["spec"]["topics"])["missing"]}
    project.log("posture_plan_approved", out)
    if done:
        project.log("requirements_confirmed", {"requirements": done, "by": d["person"], "persona": d["persona"],
                                               "card": card["id"], "posture": eff["posture"]})
    return out


# -- before a build or a delivery --------------------------------------------------------------------------

def _main(project: Any) -> str:
    repo = project.path("repo.git")
    if not repo.exists():
        return str(project.meta.get("contract_revision") or "none")
    out = subprocess.run(["git", "rev-parse", "main"], cwd=repo, capture_output=True, text=True, check=False)
    return out.stdout.strip()[:12] or "none"


def go_ahead_cards(project: Any, state: str | None = "open") -> list[dict[str, Any]]:
    return [c for c in Canon(project).cards(state=state, kind="approval") if c["refs"].get("scope") == GO_AHEAD]


def _go_ahead(project: Any, eff: dict[str, Any], needed: int, key: str, what: str) -> None:
    """Pass when a person approved this step's go-ahead; otherwise wait on its card (opened once)."""
    cards = [c for c in go_ahead_cards(project, None) if (c.get("payload") or {}).get("key") == key]
    if any(c["state"] == "decided" and c["decision"]["verdict"] == "approve" for c in cards):
        return
    why = (f"{what} needs level {needed} ({LEVELS[needed]}); the {eff['posture']} posture lets the factory act "
           f"alone up to level {eff['autonomy']} ({LEVELS[eff['autonomy']]}): it waits for a person's go-ahead")
    open_card = next((c for c in cards if c["state"] == "open"), None)
    if open_card is None:
        declined = [c["decision"] for c in cards if c["state"] == "decided" and c.get("decision")]
        body = f"The factory proposes {what}. {why}." + (
            f"\n\nDeclined before by {declined[-1]['person']}: {declined[-1].get('reason') or 'no reason'}."
            if declined else "")
        # refs keep to the ontology's keys (kernel/ontology.json); the step's key and level ride in the payload
        open_card = Canon(project).card("approval", f"Go ahead: {what}", body=body, blocking=True,
                                        refs={"scope": GO_AHEAD},
                                        payload={"key": key, "needed": needed, "posture": eff["posture"]})
        open_card = narrow(project, open_card, confirmers(eff), f"the {eff['posture']} posture")
        project.log("go_ahead_asked", {"card": open_card["id"], "key": key, "needed": needed,
                                       "autonomy": eff["autonomy"], "posture": eff["posture"],
                                       "deciders": open_card["deciders"]})
    raise Held(needed, eff["autonomy"], f"{why}: card {open_card['id']}", open_card["id"])


def _confirmed(project: Any, eff: dict[str, Any]) -> None:
    """Under a confirming posture no assumption stands without a person's confirmation before a build."""
    if not eff["confirm"]:
        return
    open_ones = [a["id"] for a in Canon(project).assumptions("open")]
    if open_ones:
        raise Held(BUILD_LEVEL, eff["autonomy"],
                   f"the {eff['posture']} posture confirms every assumption before a build: "
                   f"{', '.join(open_ones)} wait for a person to confirm or refute them")


def _landing_gate(project: Any, eff: dict[str, Any], landing: str) -> None:
    """A posture that requires a scan holds a preview or demo landing too (staging and production are
    held by the delivery's own security step)."""
    from kernel.security import security_gate

    if not eff["gate"]["scan"] or landing not in ("preview", "demo"):
        return
    gate = security_gate(project, record=False)
    if gate["blocked"]:
        raise Held(LANDING_LEVEL.get(landing, 3), eff["autonomy"],
                   f"the security gate holds delivery to {landing} under the {eff['posture']} posture: "
                   f"{gate['reason']}")


def clear(project: Any, step: str, landing: str | None = None) -> None:
    """Raise Held while the project's posture holds ``step`` ("build" or "deliver" to ``landing``)."""
    eff = of(project)
    if eff is None:
        return
    if step == "build":
        _confirmed(project, eff)
        needed, key = BUILD_LEVEL, f"build:{project.meta.get('contract_revision') or 'none'}"
        what = f"building contract revision {str(project.meta.get('contract_revision') or '')[:19]}".rstrip()
    else:
        landing = landing or "production"
        _landing_gate(project, eff, landing)
        needed, head = LANDING_LEVEL.get(landing, 4), _main(project)
        key, what = f"deliver:{landing}:{head}", f"delivering revision {head} to {landing}"
    if needed > eff["autonomy"]:
        _go_ahead(project, eff, needed, key, what)


# -- the security gate --------------------------------------------------------------------------------------

def block_on(project: Any) -> tuple[str, ...] | None:
    eff = of(project)
    return tuple(eff["gate"]["block_on"]) if eff else None


def agentic_applies(project: Any) -> bool:
    """The agentic layer applies where the project has an LLM-facing surface the red team can reach:
    an active embed."""
    from kernel.embeds import embeds

    return any(e.get("project") == project.pid and e.get("state") == "active" for e in embeds(project.factory))


def _latest_release(project: Any) -> dict[str, Any] | None:
    from kernel.deliver import latest_release

    rel = latest_release(project)
    return rel if isinstance(rel, dict) else None


def evidence_due(rel: dict[str, Any] | None) -> str | None:
    """Where a release on its way still lands with its evidence pack: staging at pilot (before it lands
    there), production at production (once IT's deploy gate passed). None otherwise."""
    if rel is None or rel.get("state") not in ("running", "waiting"):
        return None
    passed = {s.get("step") for s in rel.get("steps", []) if s.get("outcome") == "passed"}
    if rel.get("maturity") == "pilot":
        return None if "deploy:staging" in passed else "staging"
    return "production" if rel.get("maturity") == "production" and "deploy_gate" in passed else None


def evidence_missing(project: Any, level: str | None) -> str | None:
    """Before a release lands on staging (pilot) or production: an evidence pack exported for it since
    it started, its chains intact (and attestable, with its control table, where the posture asks it).
    None when nothing is missing or nothing is due yet."""
    rel = _latest_release(project)
    where = evidence_due(rel)
    if level is None or rel is None or where is None:
        return None
    ledger = project.ledger()
    started = max((r["seq"] for r in ledger.of_kind("release_started")
                   if r["event"]["payload"].get("release") == rel["release"]), default=-1)
    good = ("attestable",) if level == "attestable" else ("attestable", "insufficient evidence")
    if any(r["seq"] > started and r["event"]["payload"].get("verdict") in good for r in ledger.of_kind(
            "evidence_exported")):
        return None
    return (f"an evidence pack for release {rel['release']}" + (", attestable," if level == "attestable" else "")
            + f" exported before {where} (rihmasto evidence {project.pid} --out DIR)")


def _layer_ran(layer: str, tools: set[str]) -> bool:
    """Whether a red-team layer's SARIF was ingested: the static layer's own tool, or any agentic surface's
    (`Rihmasto red team (agentic embed)`, kernel/redteam/agentic_report.py)."""
    prefix = f"{REDTEAM} ({layer}"
    return any(t == f"{prefix})" or t.startswith(prefix + " ") for t in tools)


def _missing(project: Any, eff: dict[str, Any], scans: list[dict[str, Any]]) -> list[tuple[str, str]]:
    g, tools = eff["gate"], {str(s["tool"]) for s in scans}
    out = []
    if g["scan"] and not scans:
        out.append(("SCAN", "a security scan (SARIF 2.1.0 from any scanner, or the red team's static layer)"))
    for layer in g["redteam"]:
        if not _layer_ran(layer, tools) and (layer != "agentic" or agentic_applies(project)):
            how = ("python -m kernel.redteam static <the product's source> --sarif OUT" if layer == "static" else
                   f"python -m kernel.redteam agentic {project.pid} --surface embed --sarif OUT")
            out.append((f"REDTEAM-{layer.upper()}", f"the red team's {layer} layer ({how}, then "
                                                    f"rihmasto security ingest {project.pid} OUT)"))
    ev = evidence_missing(project, g["evidence"])
    if ev:
        out.append(("EVIDENCE", ev))
    return out


def gate_requirements(project: Any, result: dict[str, Any]) -> dict[str, Any]:
    """The security gate's result with what the posture requires and is missing: each one blocks."""
    eff = of(project)
    if eff is None:
        return result
    missing = _missing(project, eff, result.get("scans") or [])
    result = dict(result, posture={"posture": eff["posture"], "missing": [why for _, why in missing]})
    if not missing:
        return result
    result["posture"]["then"] = THEN
    rows: list[dict[str, Any]] = [{"id": f"POSTURE-{key}", "rule": f"posture {eff['posture']}", "level": "required",
                                   "tool": POSTURE_TOOL, "where": None, "cwe": [], "why": why} for key, why in missing]
    reason = f"the {eff['posture']} posture requires " + "; ".join(why for _, why in missing)
    return dict(result, blocked=True, blocking=list(result["blocking"]) + rows,
                verdict="failed" if result["verdict"] == "failed" else "not measured",
                reason=f"{result['reason']}; {reason}")


THEN = ("What the posture requires is not a finding and cannot be accepted as a risk: the release goes on once "
        "each one is there, or once a business owner, IT or compliance changes the posture (rihmasto posture set).")


def not_a_risk(finding: str) -> str | None:
    """Why ``finding`` cannot be accepted as a risk, when it names what a posture requires."""
    if not str(finding).startswith("POSTURE-"):
        return None
    return f"{finding} is what the project's posture requires, not a security finding. {THEN}"


# -- what a project's posture does, and what holds it now -------------------------------------------------

def holds(project: Any) -> list[str]:
    """What the posture holds now: go-ahead cards, assumptions to confirm, a spec topic missing, and
    what the security gate requires before a landing."""
    from kernel.security import security_gate

    eff = of(project)
    if eff is None:
        return []
    out = [f"{c['id']}: {c['title']}" for c in go_ahead_cards(project)]
    if eff["confirm"]:
        open_ones = [a["id"] for a in Canon(project).assumptions("open")]
        out += [f"assumptions to confirm before a build: {', '.join(open_ones)}"] if open_ones else []
    if not project.path("contract.json").exists():
        out += [f"the spec misses {TOPICS[t][1]}: the plan waits for a person" for t in missing_topics(project)]
    gate = security_gate(project, record=False)
    return out + [f"required before a landing: {m}" for m in (gate.get("posture") or {}).get("missing", [])]


def view(project: Any) -> dict[str, Any]:
    """The project's posture as the cockpit, the command line and the MCP server show it."""
    from kernel.autonomy import cap_of
    from kernel.posture import lines, summary

    eff = of(project)
    if eff is None:
        return {"posture": None, "cap": cap_of(project),
                "note": "no posture: the project runs by its own mode, maturity and autonomy cap, as before; "
                        "`rihmasto posture set` chooses one"}
    return {"posture": summary(project), "cap": cap_of(project), "lines": lines(eff), "holds": holds(project),
            "effects": eff}
