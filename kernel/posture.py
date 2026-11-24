"""Postures: one choice that sets how a project runs, tuned by priority weights (the owner, 2026-11-23).

A posture is chosen when a project is made (`rihmasto new --posture`, the cockpit's New project
dialog) and can be changed during the run (`rihmasto posture set`, the project's Posture dialog):

- prototype: assume mode, explore or demo, autonomy 3; light gates (nothing beyond the maturity's own).
- balanced: mixed mode, demo or pilot, autonomy 2; standard gates, and a person says go ahead before
  each build and delivery.
- production: mixed mode, pilot or production, autonomy 3; a security scan and the red team's static
  layer before any landing, holdouts on staging, IT's deploy gate, an evidence pack before production.
- regulated: socratic mode, any maturity, autonomy 1; every question settled by a person, plan approval
  at any maturity, every assumption and requirement confirmed by a named person, warnings block, the
  static and agentic red-team layers where they apply, an attestable evidence pack.

The posture's autonomy is a rung of the autonomy ladder (kernel/autonomy.py): the factory acts on its
own up to it, and a step above it waits for a person's go-ahead card. The autonomy cap still refuses
any step above the cap, whatever the posture.

Priority weights from 0 to 3 for ux, security, compliance, speed and cost tune a posture. They set
the panel's question budget per perspective and what each perspective weighs, the non-functional
topics the analyst must cover, which signals block, and how much waits for a person. A posture may
hold a floor under a weight (production: security and compliance at least 2; regulated: both 3);
a weight below it is raised and the preview says so. Every effect is a rule in `effects`, never a
model's choice, and `lines` says it in words before anyone chooses. The rules that act on the chain
are in kernel/posture_rules.py, a change during the run in kernel/posture_change.py and the command
line in kernel/posture_cli.py.

A project without a posture (`posture` absent from project.json) behaves exactly as before.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kernel.canon import PERSPECTIVES, DecisionRefused
from kernel.people import is_person
from kernel.store import MATURITIES, MODES

WEIGHTS = ("ux", "security", "compliance", "speed", "cost")
WEIGHT_MEANING = {
    "ux": "the people who use it: accessibility, the everyday task flow, plain language",
    "security": "threats and misuse, identity and access, secrets, input and data exposure",
    "compliance": "record-keeping, personal data and its protection, who approves",
    "speed": "how soon there is something to show",
    "cost": "what it costs to build and to run",
}
PERSPECTIVE_NAME = {"business": "business", "end_user": "end user", "it_security": "IT and security",
                    "operations": "operations", "delivery": "delivery"}
MODE_RANK = {"assume": 0, "mixed": 1, "socratic": 2}
MODE_MEANING = {"socratic": "every question goes to a person; nothing is assumed",
                "mixed": "blocking questions go to a person, the rest are assumed",
                "assume": "the factory assumes every answer, with a due date"}
SETTERS = ("business_owner", "product_owner", "it", "compliance")   # who chooses or tightens a posture
LOOSENERS = ("business_owner", "it", "compliance")                   # who may loosen one (as kernel/autonomy.py)
EVIDENCE_LEVELS = (None, "exported", "attestable")
# What a project without a posture does: the baseline a first posture is compared with (its own mode and
# maturity are added by `baseline`).
NO_POSTURE: dict[str, Any] = {
    "posture": None, "autonomy": 4, "plan_approval": False, "confirm": False, "spec": {"topics": []},
    "gate": {"block_on": ["error"], "scan": False, "redteam": [], "evidence": None}}

POSTURES: dict[str, dict[str, Any]] = {
    "prototype": {
        "label": "Prototype", "icon": "flask",
        "summary": "A fast, rough demo: the factory assumes the answers, builds and shows it, with light gates.",
        "mode": "assume", "maturities": ("explore", "demo"), "maturity": "demo", "autonomy": 3, "range": (2, 3),
        "weights": {"ux": 1, "security": 1, "compliance": 0, "speed": 3, "cost": 1}, "floors": {},
        "plan_approval": False, "confirm": False, "scan": False, "redteam": (), "evidence": None,
    },
    "balanced": {
        "label": "Balanced", "icon": "sliders",
        "summary": "Blocking questions to people, the rest assumed; standard gates; a person says go ahead "
                   "before each build and delivery.",
        "mode": "mixed", "maturities": ("demo", "pilot"), "maturity": "demo", "autonomy": 2, "range": (1, 3),
        "weights": {"ux": 1, "security": 1, "compliance": 1, "speed": 1, "cost": 1}, "floors": {},
        "plan_approval": False, "confirm": False, "scan": False, "redteam": (), "evidence": None,
    },
    "production": {
        "label": "Production", "icon": "gate",
        "summary": "As production-ready as possible: holdouts on staging, a security scan and the red team's "
                   "static layer before any landing, the deploy gate and an evidence pack before production.",
        "mode": "mixed", "maturities": ("pilot", "production"), "maturity": "production", "autonomy": 3,
        "range": (2, 3), "weights": {"ux": 2, "security": 2, "compliance": 2, "speed": 1, "cost": 1},
        "floors": {"security": 2, "compliance": 2},
        "plan_approval": False, "confirm": False, "scan": True, "redteam": ("static",), "evidence": "exported",
    },
    "regulated": {
        "label": "Regulated", "icon": "shield",
        "summary": "Conservative and secure: every question to a person, every assumption and requirement "
                   "confirmed by name, plan approval at any maturity, blocking security and compliance gates.",
        "mode": "socratic", "maturities": MATURITIES, "maturity": "pilot", "autonomy": 1, "range": (1, 1),
        "weights": {"ux": 1, "security": 3, "compliance": 3, "speed": 0, "cost": 1},
        "floors": {"security": 3, "compliance": 3},
        "plan_approval": True, "confirm": True, "scan": True, "redteam": ("static", "agentic"),
        "evidence": "attestable",
    },
}

# Which weights each perspective of the panel answers to (speed shortens every perspective).
TOUCHES = {"business": ("compliance", "cost"), "end_user": ("ux",), "it_security": ("security", "compliance"),
           "operations": ("cost",), "delivery": ()}
EMPHASIS = {
    "ux": "accessibility (keyboard use, screen readers, contrast), the everyday task flow and plain language",
    "security": "threats and misuse, authentication and authorisation, secrets, input validation and data exposure",
    "compliance": "record-keeping (who did what, and when), personal data (which, why, for how long) and who "
                  "must approve",
    "cost": "running cost, licences and the cheapest way to operate it",
    "speed": "the smallest version that can be shown soon; leave the rest for later",
}
# The non-functional topics the analyst must cover when their weight is 2 or more: the weight, the
# topic's name, the guidance, and the words a requirement or criterion covering it holds (checked by
# rule in kernel/posture_rules.py). Accessibility applies only to work with screens.
TOPICS: dict[str, tuple[str, str, str, str]] = {
    "accessibility": (
        "ux", "accessibility",
        "Accessibility: include a requirement that every screen can be used with the keyboard alone and every "
        "form control has a label, with a test that reads the HTML the service returns.",
        r"accessib|keyboard|screen reader|\baria\b|aria-|wcag|colou?r contrast|contrast ratio"),
    "security": (
        "security", "threat model and security",
        "Security: include a threat-model requirement: a request that changes data is refused without the "
        "caller's credential (401), malformed input is refused (400) without echoing it, and no response "
        "carries a secret. Its criteria are tests.",
        r"authenticat|authori[sz]|credential|\b401\b|\b403\b|threat|secret|malformed|invalid input|injection"
        r"|access control|forbidden|\b(?:api|bearer|access) token"),
    "record_keeping": (
        "compliance", "record-keeping",
        "Record-keeping: include a requirement that every change is recorded with who made it and when, "
        "readable through the API.",
        r"audit|who (?:made|changed|did)|change history|history of changes|record(?:s|ed)? (?:of )?who"),
    "data_protection": (
        "compliance", "data protection",
        "Data protection: include a requirement that names the personal data the product keeps, why and for "
        "how long, and how a person's data is deleted on request.",
        r"personal data|data protection|gdpr|retention|retain|erasure|right to be forgotten"
        r"|delet\w* on request|on request.{0,40}delet"),
}
GUIDES = {"cost": "Cost: no requirement may need a paid external service; prefer what the paved road runs.",
          "speed": "Speed: write the fewest requirements that show the goal, and put the rest out of scope."}


def posture(name: str) -> dict[str, Any]:
    if name not in POSTURES:
        raise ValueError(f"posture must be one of {', '.join(POSTURES)}, got {name!r}")
    return POSTURES[name]


def parse_weights(text: str | None) -> dict[str, int]:
    """'security=3,ux=1' as a dict; an unknown name or a value outside 0 to 3 is refused."""
    out: dict[str, int] = {}
    for part in (x.strip() for x in str(text or "").split(",")):
        if not part:
            continue
        name, sep, value = part.partition("=")
        if not sep or not value.strip().isdigit() or int(value) > 3:
            raise ValueError(f"a weight is name=0..3, got {part!r}")
        if name.strip() not in WEIGHTS:
            raise ValueError(f"a weight is one of {', '.join(WEIGHTS)}, got {name.strip()!r}")
        out[name.strip()] = int(value)
    return out


def weights_of(name: str, given: Mapping[str, Any] | None = None) -> tuple[dict[str, int], list[str]]:
    """The posture's weights with the person's over them, each raised to the posture's floor, and what
    was raised."""
    p = posture(name)
    w = dict(p["weights"])
    for k, v in (given or {}).items():
        if k not in WEIGHTS:
            raise ValueError(f"a weight is one of {', '.join(WEIGHTS)}, got {k!r}")
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 3:
            raise ValueError(f"the weight {k} is a whole number from 0 to 3, got {v!r}")
        w[k] = v
    raised = []
    for k, floor in p["floors"].items():
        if w[k] < floor:
            raised.append(f"{k} raised from {w[k]} to {floor}: the floor of the {name} posture")
            w[k] = floor
    return w, raised


def _maturity(name: str, maturity: str | None, strict: bool) -> str:
    p = posture(name)
    if maturity is None:
        return str(p["maturity"])
    if maturity not in MATURITIES or (strict and maturity not in p["maturities"]):
        raise ValueError(f"the {name} posture runs at {' or '.join(p['maturities'])}, not {maturity!r}")
    return maturity


def _mode(name: str, mode: str | None, strict: bool) -> str:
    p = posture(name)
    if mode is None:
        return str(p["mode"])
    if mode not in MODES or (strict and MODE_RANK[mode] < MODE_RANK[p["mode"]]):
        stricter = [m for m in MODES if MODE_RANK[m] >= MODE_RANK[p["mode"]]]
        raise ValueError(f"the {name} posture asks in mode {' or '.join(stricter)}, not {mode!r}")
    return mode


def _budget(maturity: str, w: Mapping[str, int]) -> dict[str, int]:
    """Questions per perspective: the maturity's number, one more per weight point above 1 that the
    perspective answers to (one fewer at 0), one fewer everywhere at speed 3; from 1 to 6."""
    from kernel.intake import QUESTIONS_PER_PERSPECTIVE

    base, quick = QUESTIONS_PER_PERSPECTIVE[maturity], 1 if w["speed"] == 3 else 0
    return {p: min(6, max(1, base + max((w[k] - 1 for k in TOUCHES[p]), default=0) - quick)) for p in PERSPECTIVES}


def _emphasis(w: Mapping[str, int]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in PERSPECTIVES:
        lines = [f"{k} ({w[k]} of 3): {EMPHASIS[k]}" for k in (*TOUCHES[p], "speed") if w[k] >= 2]
        lines += [f"{k} has no weight: ask about it only if building without it would build the wrong thing"
                  for k in TOUCHES[p] if w[k] == 0]
        out[p] = lines
    return out


def _evidence(floor: str | None, compliance: int) -> str | None:
    by_weight = "attestable" if compliance == 3 else "exported" if compliance == 2 else None
    return max(floor, by_weight, key=EVIDENCE_LEVELS.index)


def _topics(w: Mapping[str, int], screens: bool) -> list[str]:
    return [t for t, (weight, *_) in TOPICS.items() if w[weight] >= 2 and (screens or t != "accessibility")]


def effects(name: str, weights: Mapping[str, Any] | None = None, *, maturity: str | None = None,
            mode: str | None = None, strict: bool = True, screens: bool = True) -> dict[str, Any]:
    """Everything a posture and its weights do, by rule. ``strict`` refuses a maturity the posture does
    not run at and a mode looser than its own; a project's own record is read with ``strict=False``.
    ``screens`` is whether the work has screens (its profile's): accessibility is asked for only then."""
    p = posture(name)
    w, raised = weights_of(name, weights)
    maturity, mode = _maturity(name, maturity, strict), _mode(name, mode, strict)
    lo, hi = p["range"]
    autonomy = min(hi, max(lo, p["autonomy"] - int(w["security"] == 3 or w["compliance"] == 3)
                           + int(w["speed"] == 3)))
    topics = _topics(w, screens)
    return {
        "posture": name, "label": p["label"], "weights": w, "raised": raised, "mode": mode, "maturity": maturity,
        "maturities": list(p["maturities"]), "autonomy": autonomy, "screens": screens,
        "intake": {"budget": _budget(maturity, w), "emphasis": _emphasis(w)},
        "spec": {"topics": topics, "guidance": [TOPICS[t][2] for t in topics]
                 + [GUIDES[k] for k in GUIDES if w[k] >= (2 if k == "cost" else 3)]},
        "plan_approval": bool(p["plan_approval"] or w["compliance"] == 3),
        "confirm": bool(p["confirm"] or w["compliance"] == 3),
        "gate": {"block_on": ["error", "warning"] if w["security"] == 3 else ["error"],
                 "scan": bool(p["scan"] or w["security"] == 3),
                 "redteam": [x for x in ("static", "agentic") if x in p["redteam"] or w["security"] == 3],
                 "evidence": _evidence(p["evidence"], w["compliance"])},
    }


# -- in words: what a posture will do, said before anyone chooses ------------------------------------

def _waiting_steps(eff: Mapping[str, Any]) -> list[str]:
    from kernel.autonomy import BUILD_LEVEL, LANDING_LEVEL
    from kernel.deliver import LANDING

    landing = LANDING[eff["maturity"]]
    steps = [("building", BUILD_LEVEL), (f"delivering to {landing}", LANDING_LEVEL.get(landing, 4))]
    return [what for what, level in steps if level > eff["autonomy"]]


def _people_lines(eff: Mapping[str, Any]) -> list[str]:
    from kernel.autonomy import LEVELS
    from kernel.plan import NEEDS_APPROVAL

    waits = _waiting_steps(eff)
    out = [f"Autonomy {eff['autonomy']} ({LEVELS[eff['autonomy']]}): the factory acts alone up to it"
           + (f"; {' and '.join(waits)} {'wait' if len(waits) > 1 else 'waits'} for a person's go-ahead card."
              if waits else "; nothing waits for a "
              "go-ahead beyond the maturity's own cards.")]
    if eff["plan_approval"] or NEEDS_APPROVAL[eff["maturity"]]:
        out.append("A person approves the plan before anything is built"
                   + (" (at any maturity)." if eff["plan_approval"] else f" (as every {eff['maturity']} plan)."))
    if eff["confirm"]:
        out.append("Approving the plan confirms each requirement in the approver's name; every assumption is "
                   "confirmed or refuted by a person before a build.")
    gates = {"demo": "the business owner accepts the demo", "pilot": "end users validate it on staging",
             "production": "end users validate it on staging, then IT's deploy gate before production"}
    if eff["maturity"] in gates:
        out.append(f"The {eff['maturity']} plan's own card: {gates[eff['maturity']]}.")
    out.append("The autonomy cap a business owner, IT or compliance set still refuses any step above it.")
    return out


def _gate_lines(eff: Mapping[str, Any]) -> list[str]:
    g = eff["gate"]
    out = ["Every task meets the gate: the tests, the criterion trace, fail-first and an independent verifier."]
    levels = " or ".join(g["block_on"])
    out.append(f"An open security finding at {levels} holds a release before "
               + ("any landing." if g["scan"] else "staging and production."))
    if g["scan"]:
        layers = " and ".join(g["redteam"]) or "no"
        out.append(f"A security scan is required before any landing, with the red team's {layers} "
                   f"{'layer' if len(g['redteam']) == 1 else 'layers'}"
                   + (" (agentic where the project has an LLM-facing surface, such as an embed)."
                      if "agentic" in g["redteam"] else "."))
    if g["evidence"]:
        when = {"production": "Before production", "pilot": "Before a release lands on staging"}.get(
            eff["maturity"], f"At {eff['maturity']} nothing lands on staging or production; if the maturity is raised, "
                             "before a release lands there")
        out.append(f"{when}, an evidence pack exported for the release ({g['evidence']}: "
                   + ("its records intact and complete enough to judge, with the control table)."
                      if g["evidence"] == "attestable" else "its hash chains intact)."))
    return out


def _spec_lines(eff: Mapping[str, Any]) -> list[str]:
    from kernel.spec import MAX_REQUIREMENTS

    n = MAX_REQUIREMENTS[eff["maturity"]] + len(eff["spec"]["topics"])
    out = [f"At most {n} requirements at {eff['maturity']}."] + list(eff["spec"]["guidance"])
    if eff["weights"]["ux"] >= 2 and not eff.get("screens", True):
        out.append("ux: this kind of work has no screens, so no accessibility requirement is asked for.")
    if eff["spec"]["topics"]:
        out.append("A spec that misses one of these topics waits for a person to approve the plan.")
    return out


def lines(eff: Mapping[str, Any]) -> dict[str, list[str]]:
    """What the posture does, in four groups: the panel, the spec, the gates and the people."""
    b = eff["intake"]["budget"]
    more = sorted({k for p in PERSPECTIVES for k in TOUCHES[p] if eff["weights"][k] >= 2})
    intake = [f"Mode {eff['mode']}: {MODE_MEANING[eff['mode']]}.",
              f"The panel asks at most {sum(b.values())} questions: "
              + ", ".join(f"{PERSPECTIVE_NAME[p]} {b[p]}" for p in PERSPECTIVES) + "."]
    if more:
        intake.append("It asks more about " + ", ".join("UX" if k == "ux" else k for k in more) + ".")
    return {"intake": intake, "spec": _spec_lines(eff), "gates": _gate_lines(eff), "people": _people_lines(eff),
            "raised": list(eff["raised"])}


def screens_of(profile: str | None) -> bool:
    """Whether a work profile's product has screens (an unknown or unchosen one is assumed to)."""
    from kernel.profiles import PROFILES

    return bool((PROFILES.get(profile or "") or {}).get("screens", True))


def preview(name: str, weights: Mapping[str, Any] | None = None, *, maturity: str | None = None,
            mode: str | None = None, profile: str | None = None) -> dict[str, Any]:
    eff = effects(name, weights, maturity=maturity, mode=mode, screens=screens_of(profile))
    return {"effects": eff, "lines": lines(eff)}


def public() -> dict[str, Any]:
    """The postures as the cockpit and the command line list them."""
    rows = [{"id": k, "label": p["label"], "icon": p["icon"], "summary": p["summary"], "mode": p["mode"],
             "maturities": list(p["maturities"]), "maturity": p["maturity"], "autonomy": p["autonomy"],
             "weights": dict(p["weights"]), "floors": dict(p["floors"])} for k, p in POSTURES.items()]
    return {"postures": rows, "weights": dict(WEIGHT_MEANING), "modes": dict(MODE_MEANING),
            "setters": list(SETTERS), "looseners": list(LOOSENERS)}


# -- a project's posture ------------------------------------------------------------------------------

def record_of(project: Any) -> dict[str, Any] | None:
    rec = project.meta.get("posture")
    return rec if isinstance(rec, dict) and rec.get("name") in POSTURES else None


def of(project: Any) -> dict[str, Any] | None:
    """The effects of the project's posture, or None: a project without one runs as before."""
    from kernel.profiles import profile_of

    rec = record_of(project)
    if rec is None:
        return None
    meta = project.meta
    return effects(rec["name"], rec.get("weights"), maturity=meta.get("maturity"), mode=meta.get("mode"),
                   strict=False, screens=bool(profile_of(project).get("screens", True)))


def baseline(project: Any) -> dict[str, Any]:
    """What the project does now: its posture's effects, or, without one, how it runs as before (its own
    mode and maturity, the autonomy cap alone, the maturity's own gates)."""
    eff = of(project)
    if eff is not None:
        return eff
    return dict(NO_POSTURE, mode=project.meta.get("mode"), maturity=project.meta.get("maturity"))


def for_new_project(choice: Mapping[str, Any] | None, maturity: str | None,
                    mode: str | None) -> tuple[str, str, dict[str, Any] | None]:
    """The maturity, mode and posture record of a project made with ``choice`` (``name``, ``weights``,
    ``by``, ``persona``), or the defaults when there is none."""
    if not choice:
        return maturity or "demo", mode or "mixed", None
    if not is_person(choice.get("by")):
        raise DecisionRefused(f"{choice.get('by')!r} is not a person: a posture is a person's choice")
    eff = effects(str(choice.get("name")), choice.get("weights"), maturity=maturity, mode=mode)
    return eff["maturity"], eff["mode"], {"name": eff["posture"], "weights": eff["weights"],
                                          "chosen_by": choice["by"], "persona": choice.get("persona")}


def record_choice(project: Any, rec: Mapping[str, Any]) -> None:
    """Record the posture chosen at creation: who chose it, what it does, and the preview they were
    shown (the same rules over the same choice give the same lines)."""
    eff = of(project)
    if eff is not None:
        project.log("posture_chosen", {"posture": rec["name"], "weights": rec["weights"], "raised": eff["raised"],
                                       "by": rec["chosen_by"], "persona": rec.get("persona"),
                                       "mode": eff["mode"], "maturity": eff["maturity"],
                                       "autonomy": eff["autonomy"], "gate": eff["gate"],
                                       "plan_approval": eff["plan_approval"], "confirm": eff["confirm"],
                                       "topics": eff["spec"]["topics"], "shown": lines(eff)})


def track_posture(project: Any) -> dict[str, Any]:
    """Whether the run keeps the posture chosen for it, for Track (kernel/track.py asks this hook): its
    maturity one the posture runs at, and its mode at least as strict as the posture's. Without a posture
    nothing is measured, and the basis says so."""
    rec = record_of(project)
    if rec is None:
        return {"posture": None, "keeps": None, "drift": [],
                "basis": "no posture chosen: the project runs by its mode, maturity and autonomy cap"}
    p, meta = POSTURES[rec["name"]], project.meta
    drift = []
    if meta.get("maturity") not in p["maturities"]:
        drift.append(f"maturity {meta.get('maturity')} is not one {p['label']} runs at ({', '.join(p['maturities'])})")
    if MODE_RANK.get(meta.get("mode"), -1) < MODE_RANK[p["mode"]]:
        drift.append(f"mode {meta.get('mode')} is looser than {p['label']}'s {p['mode']}")
    return {"posture": rec["name"], "keeps": not drift, "drift": drift,
            "basis": f"the {p['label']} posture: " + ("; ".join(drift) if drift else
                                                    f"maturity {meta.get('maturity')} and mode {meta.get('mode')} keep it")}


def summary(project: Any) -> dict[str, Any] | None:
    """The posture in brief, for the MCP server and status: None when the project has none."""
    rec, eff = record_of(project), of(project)
    if rec is None or eff is None:
        return None
    return {"posture": eff["posture"], "label": eff["label"], "weights": eff["weights"], "mode": eff["mode"],
            "maturity": eff["maturity"], "autonomy": eff["autonomy"], "gate": eff["gate"],
            "plan_approval": eff["plan_approval"], "confirm": eff["confirm"], "topics": eff["spec"]["topics"],
            "chosen_by": rec.get("chosen_by"), "persona": rec.get("persona"), "at": rec.get("at"),
            "reason": rec.get("reason")}
