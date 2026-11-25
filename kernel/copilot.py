"""Goal help in a project (FR-CPL1, docs/guides/agentic-help.md): a person states a goal, Rihma answers with a plan.

"Hook this to Google Drive", "run it every night in our cloud", "deploy to test", "add sign-in", "monitor it",
"give this to my coding agent", in English or Finnish. The plan rests on two things only:

- **the project's records** (``facts``): its stage, whether a contract is compiled, what it waits for, its posture,
  whether it is confidential, adopted or attached, its declared integrations and its runner;
- **what this Rihmasto can do** (kernel/copilot_catalog.py), read from the code at run time, with honest gaps:
  "there is no Google Drive connector yet: options are ...".

Each step is one action a person takes with one click (kernel/copilot_steps.py ``STEP_KINDS``): draft a change
request (the change form opens prefilled, the person edits and files it, signed, through the existing route),
start a walkthrough, open or configure a view, enable a check, add an automation from a template, run a command,
or hand off to a coding agent (kernel/agent_bridge.py). Nothing is written by planning.

**Without a model** a rule-based recogniser (``intents``) reads the goal and the steps come from the rules.
**With one** (the ``assistant`` role, through Gnomon), the model writes the plan from the facts and the catalogue,
and every step it proposes is checked (``check_step``): an unknown kind, a route the cockpit does not have, a
walkthrough, check or template this build lacks, or a command that is not a plain `rihmasto` command is dropped
with the reason. A confidential project whose assistant model is hosted gets the rule-based plan, and is told so
with how to fix it in Models setup; nothing about it is sent.
"""

from __future__ import annotations

import json
import re
from typing import Any

from kernel import copilot_steps as cs
from kernel import model_usage
from kernel.copilot_catalog import catalogue, system_named
from kernel.copilot_steps import AGENTS, STEP_KINDS

# What each goal sounds like, in English and Finnish (lower case, matched as word starts).
INTENTS: dict[str, re.Pattern[str]] = {
    "test_env": re.compile(r"\b(test environment|deploy (?:it )?to test|to test\b|staging|qa\b|try it out|"
                           r"testiympärist|testiin|testattavaksi|kokeiluun)"),
    "cloud": re.compile(r"\b(deploy|in (?:our|the) cloud|cloud\b|production|azure|gcp|google cloud|aws\b|"
                        r"kubernetes|cloud run|go live|host it|pilve|pilvi|tuotanto|julkai)"),
    "connect": re.compile(r"\b(hook|connect|integrat|link it|plug|sync|read (?:from|the files)|write to|pull from|"
                          r"push to|kytke|yhdist|integroi|liitä|liittä|synkro)"),
    "schedule": re.compile(r"\b(every (?:night|day|hour|morning|week|monday|\d+ ?(?:min|minute|hour))|nightly|daily|"
                           r"hourly|weekly|on a schedule|schedul|cron\b|joka (?:yö|päivä|aamu|tunti|viikko)|öisin|"
                           r"päivittäin|viikoittain|ajasta)"),
    "monitor": re.compile(r"\b(monitor|alert|observab|uptime|watch it|opentelemetry|valvo|monitoroi|hälyt)"),
    "sign_in": re.compile(r"\b(sign[- ]?in|log[- ]?in|sso\b|single sign|authenticat|access control|identity provider|"
                          r"kirjautu|tunnistau|käyttöoikeu)"),
    "handoff": re.compile(r"\b(coding agent|hand (?:it |this )?(?:off|over)|handoff|give (?:this|it) to|claude|codex|"
                          r"opencode|cursor|my agent|my ide|the ide\b|terminal agent|koodausagent|agentille|"
                          r"anna (?:tämä|se))"),
}
GOAL = re.compile(r"\b(i want|we want|i'?d like|we'?d like|i would like|we need|i need|need to|want to|"
                  r"how (?:do|can|would|should) (?:i|we)|help me|help us|can (?:you|we|it)|could (?:you|we)|let'?s|"
                  r"make it|get it|haluan|haluamme|tarvitsen|tarvitsemme|pitäisi|miten (?:saan|voin|saamme|voimme)|"
                  r"auta|voisitko|voitko)")
WHERE = re.compile(r"^\s*(?:where|missä|mistä)\b")
DECIDING = re.compile(r"\b(approve|declin|decide|decision|accept|reject|hyväksy|hylkää|päätä)")
IMPERATIVE = {"run", "add", "give", "make", "put", "set", "get", "deploy", "hook", "connect", "integrate", "sync",
              "monitor", "schedule", "host", "ship", "lisää", "anna", "aja", "julkaise", "kytke", "yhdistä", "ajasta",
              "valvo", "vie", "siirrä"}
TO_AGENT = (("claude", "claude-code"), ("codex", "codex"), ("opencode", "opencode"), ("cursor", "cursor"))
MAX_STEPS = 9
CONFIDENTIAL_NOTE = ("This project is confidential and the assistant's model is hosted, so nothing was sent: the plan "
                     "comes from the rules. To let a model plan it, set the assistant role to a local or private "
                     "endpoint in Models setup (Settings, Models), or `rihmasto models set assistant ... --private`.")


def intents(goal: str) -> list[str]:
    """The goals a sentence states, in a fixed order. "Deploy to test" is a test environment, not production."""
    said = goal.lower()
    found = [name for name, pattern in INTENTS.items() if pattern.search(said)]
    if "test_env" in found and "cloud" in found and not re.search(r"\b(production|tuotanto|cloud|pilv)", said):
        found.remove("cloud")
    if "connect" not in found and system_named(said) and re.search(r"\b(to|into|from|with|-?(?:een|aan|sta|lle))\b",
                                                                    said) and not found:
        found.append("connect")
    return found


def agent_named(goal: str) -> str:
    said = goal.lower()
    return next((to for word, to in TO_AGENT if word in said), "generic")


def asks_goal(question: str) -> bool:
    """Whether a question states a goal to reach rather than asks where something is or how things stand."""
    from kernel.assistant_rules import asks_for_action

    said = question.lower()
    found = intents(said)
    if not found or WHERE.match(said) or DECIDING.search(said):
        return False             # a decision on a card ("approve the deploy gate") is the assistant's, by its rules
    first = (re.findall(r"[a-zåäö']+", said) or [""])[0]
    imperative = any(p.match(first) for p in INTENTS.values()) or first in IMPERATIVE
    return bool(GOAL.search(said)) or imperative or asks_for_action(question)


# -- the records ----------------------------------------------------------------------------------------------

def facts(project: Any) -> dict[str, Any]:
    """What the plan may say about the project, from its records."""
    from kernel.confidential import confidential
    from kernel.next_step import next_step
    from kernel.store import STAGES

    meta = project.meta
    try:
        nxt = next_step(project)
    except (OSError, ValueError, KeyError):
        nxt = {"waits_for": None, "actions": []}
    spec = project.read("spec.json", {}) or {}
    return {"pid": project.pid, "title": meta.get("title"), "stage": meta.get("stage"),
            "stage_name": STAGES.get(meta.get("stage") or 1), "profile": meta.get("profile"),
            "maturity": meta.get("maturity"), "posture": meta.get("posture"), "confidential": confidential(project),
            "source_kind": meta.get("source_kind"), "contract": project.path("contract.json").exists(),
            "waits_for": nxt.get("waits_for"), "next": [a.get("label") for a in nxt.get("actions") or []][:3],
            "integrations": [i.get("name") for i in spec.get("integrations") or [] if isinstance(i, dict)],
            "paved_road": meta.get("paved_road")}


def _views() -> set[str]:
    from kernel.assistant_rules import ui_map

    return {v["id"] for v in ui_map()["views"]}


def _walkthrough_steps(cat: dict[str, Any], found: list[str]) -> list[dict[str, Any]]:
    words = {"connect": ("integrat", "connect"), "cloud": ("deploy",), "test_env": ("deploy", "test"),
             "monitor": ("monitor", "health"), "schedule": ("automat", "schedul")}
    out = []
    for flow in cat["walkthroughs"]["flows"]:
        text = f"{flow.get('name')} {flow.get('label')} {flow.get('about')}".lower()
        if any(w in text for i in found for w in words.get(i, ())):
            out.append(cs.step(f"Walk through it: {flow.get('label')}", {"kind": "walkthrough", "name": flow["name"]},
                               str(flow.get("about") or "")))
    return out[:1]


def rule_plan(factory: Any, project: Any, goal: str, *, cat: dict[str, Any] | None = None) -> dict[str, Any]:
    """The plan from the rules and the catalogue: never a map answer for a goal."""
    cat = cat if cat is not None else catalogue(factory, project)
    f, views, found = facts(project), _views(), intents(goal) or ["connect"]
    system = system_named(goal)
    label = system[1] if system else "the system"
    gaps: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    if set(found) - {"handoff", "monitor"}:
        steps.append(cs.change_step(goal, found, f, label))
    steps += _walkthrough_steps(cat, found)
    builders = {"connect": lambda: cs.connect(cat, f, views, system, gaps),
                "cloud": lambda: cs.cloud(cat, f, views, goal.lower(), gaps),
                "test_env": lambda: cs.test_env(cat, f, views), "schedule": lambda: cs.schedule(cat, f, views),
                "monitor": lambda: cs.monitor(cat, f, views), "sign_in": lambda: cs.sign_in(cat, f, views)}
    for name in found:
        if name in builders:
            steps += builders[name]()
    steps.append(cs.handoff_step(f, agent_named(goal)))
    steps += cs.harness_step(cat)       # no model answers: the coding agent you already have (FR-HMD1)
    return _shaped(goal, found, _unique(steps), gaps, f, by="rules")


def _unique(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each step once, and only the controls the cockpit's map has (a stream not merged has none of its own)."""
    from kernel.assistant_rules import ui_map

    controls = {c["id"] for c in ui_map()["controls"]}
    seen, out = set(), []
    for s in steps:
        if s["action"].get("control") not in (None, *controls):
            s["action"] = {k: v for k, v in s["action"].items() if k != "control"}
        key = (s["title"], s["action"].get("kind"))
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out[:MAX_STEPS]


def _shaped(goal: str, found: list[str], steps: list[dict[str, Any]], gaps: list[dict[str, Any]],
            f: dict[str, Any], *, by: str, answer: str | None = None) -> dict[str, Any]:
    for n, s in enumerate(steps, 1):
        s["id"] = f"S-{n}"
    if answer is None:
        own = {"adopted": " It is an adopted project: a change goes through the change loop.",
               "attached": " Its repository is attached: Rihmasto gates commits and never writes to it."}
        gap = " " + " ".join(g["what"] for g in gaps) if gaps else ""
        answer = (f"A plan for \"{goal.strip()}\" on {f['title']}, from its records and what this Rihmasto has: "
                  f"{len(steps)} step(s).{own.get(str(f.get('source_kind')), '')}{gap} Nothing is done until you take "
                  "a step: each one that changes something is yours to confirm, signed with your name.")
    return {"goal": goal.strip(), "intents": found, "steps": steps, "gaps": gaps, "facts": f, "by": by,
            "answer": answer}


# -- the model ----------------------------------------------------------------------------------------------

def _compact(cat: dict[str, Any]) -> dict[str, Any]:
    return {"roads": cat["roads"]["roads"], "road_kinds": cat["roads"]["kinds"],
            "connectors": cat["connectors"], "integration_kinds": [k["kind"] for k in cat["integration_kinds"]],
            "outputs": [o["id"] for o in cat["outputs"]], "checks": cat["checks"],
            "automation_templates": [t["id"] for t in cat["automations"]["templates"]],
            "automations": cat["automations"]["available"], "walkthroughs": [w.get("name") for w in
                                                                            cat["walkthroughs"]["flows"]],
            "runners": cat["runners"]}


def prompt(goal: str, f: dict[str, Any], cat: dict[str, Any], rules: dict[str, Any]) -> str:
    kinds = ", ".join(STEP_KINDS)
    return (
        "You are Rihma, helping a person reach a goal in one of their projects. Write a short plan.\n"
        "Rules: only what the catalogue below has; say plainly what it lacks (a gap) and the options. Each step is "
        f"one action of kind {kinds}. You never act and never write that you did: the person takes each step.\n"
        "Step args: draft_change {text}; walkthrough {name}; open {route, control}; configure {route, control, "
        "command}; enable_check {check, route}; automation {template, draft}; command {command: a plain `rihmasto ...` "
        f"command line}}; handoff {{to: one of {', '.join(AGENTS)}}}.\n"
        'Answer with this JSON in a ```json block: {"answer": "two to four sentences", "steps": [{"title": "...", '
        '"detail": "...", "action": {"kind": "...", ...}}], "gaps": [{"what": "...", "options": ["..."]}]}\n\n'
        f"The goal:\n<<<\n{goal}\n>>>\n\nThe project's records (JSON):\n{json.dumps(f, default=str)}\n\n"
        f"What this Rihmasto has (JSON):\n{json.dumps(_compact(cat), default=str)}\n\n"
        f"The rule-based plan, to improve on (JSON):\n{json.dumps(rules['steps'], default=str)[:6000]}\n")


def _automation_ok(a: dict[str, Any], cat: dict[str, Any]) -> str | None:
    if not cat["automations"]["available"]:
        return "automations are not in this Rihmasto yet"
    known = (None, *(t["id"] for t in cat["automations"]["templates"]))
    return None if a.get("template") in known else f"no automation template {a.get('template')!r}"


# What each kind of step must name to be shown: None when it may, else why not.
_KIND_CHECKS = {
    "draft_change": lambda a, cat: None if str(a.get("text") or "").strip() else "a drafted change needs its text",
    "walkthrough": lambda a, cat: None if a.get("name") in {w.get("name") for w in cat["walkthroughs"]["flows"]}
    else f"no walkthrough {a.get('name')!r} in this Rihmasto",
    "enable_check": lambda a, cat: None if a.get("check") in {c["kind"] for c in cat["checks"]["kinds"]}
    else f"no check {a.get('check')!r} in this Rihmasto",
    "automation": _automation_ok,
    "handoff": lambda a, cat: None if a.get("to", "generic") in AGENTS else f"hand off to one of {', '.join(AGENTS)}",
}


def _nav_ok(factory: Any, a: dict[str, Any]) -> str | None:
    """A route the cockpit has, a control of its map, and a command that is one plain `rihmasto` command."""
    from kernel.assistant_rules import route_ok, ui_map

    if a.get("route") is not None and not route_ok(a["route"], factory):
        return f"{a['route']} is not a cockpit route"
    if a.get("control") is not None and a["control"] not in {c["id"] for c in ui_map()["controls"]}:
        return f"{a['control']} is not a control of the cockpit"
    cmd = str(a.get("command") or "")
    plain = cmd.startswith("rihmasto ") and not re.search(r"[;&|`$<>\n]", cmd)
    if plain or (not cmd and a.get("kind") != "command"):
        return None
    return "a command is one plain `rihmasto ...` command line"


def check_step(factory: Any, project: Any, s: Any, cat: dict[str, Any]) -> str | None:
    """None when a step the model proposed may be shown; otherwise why not."""
    if not isinstance(s, dict) or not isinstance(s.get("action"), dict) or not str(s.get("title") or "").strip():
        return "a step is {title, detail, action}"
    a = s["action"]
    if a.get("kind") not in STEP_KINDS:
        return f"unknown step kind {a.get('kind')!r}"
    own = _KIND_CHECKS.get(a["kind"])
    return (own(a, cat) if own else None) or _nav_ok(factory, a)


def model_plan(factory: Any, project: Any, goal: str, model: Any) -> dict[str, Any]:
    """The model's plan with every step checked; the rule-based plan, with a note, when it gives none usable."""
    from kernel.assistant_rules import honest
    from kernel.model import ModelError, extract_json

    cat = catalogue(factory, project)
    rules = rule_plan(factory, project, goal, cat=cat)
    try:
        # through run_gnomon_task's guard (a harness-backed role answers too), its run as model_run in the project
        with model_usage.for_project(project, task="goal", factory=factory):
            raw = extract_json(model.ask(prompt(goal, rules["facts"], cat, rules), role="assistant"))
        if not isinstance(raw, dict):
            raise ModelError("the answer is not a JSON object")
    except (ModelError, OSError, RuntimeError, ValueError) as exc:
        return rules | {"note": f"the assistant model gave no usable plan ({exc}); this plan comes from the rules"}
    kept, dropped = [], []
    for s in raw.get("steps") if isinstance(raw.get("steps"), list) else []:
        why = check_step(factory, project, s, cat)
        if why:
            dropped.append({"step": s, "refused": why})
        else:
            kept.append(cs.step(str(s["title"])[:200], dict(s["action"]), str(s.get("detail") or "")[:600]))
    if not kept:
        return rules | {"dropped": dropped, "note": "none of the model's steps passed the checks; this plan comes "
                                                    "from the rules"}
    gaps = [g for g in raw.get("gaps") or [] if isinstance(g, dict) and g.get("what")] or rules["gaps"]
    answer, _ = honest(str(raw.get("answer") or "").strip(), kept, dropped)
    out = _shaped(goal, rules["intents"], _unique(kept), gaps, rules["facts"], by="model", answer=answer or None)
    return out | {"dropped": dropped}


def plan(factory: Any, project: Any, goal: str, *, model: Any = None) -> dict[str, Any]:
    """The plan for a goal: the model's, checked, when there is one and the project allows it; else the rules'."""
    from kernel.confidential import confidential, refusal

    if not goal.strip():
        raise ValueError("the goal is empty")
    if model is not None and confidential(project) and refusal(["assistant"]):
        return rule_plan(factory, project, goal) | {"note": CONFIDENTIAL_NOTE, "confidential": True}
    if model is None:
        return rule_plan(factory, project, goal)
    from kernel.assistant import _own_lane  # a question never waits behind the factory's analyst lane

    return model_plan(factory, project, goal, _own_lane(model))


def routed(factory: Any, project: Any, question: str, about: dict[str, Any] | None, *, persona: str,
           model: Any = None) -> dict[str, Any] | None:
    """Ask Rihma's hook (kernel/assistant.py): an answer already found stays; a goal in a project gets its plan."""
    if about is not None or project is None or not asks_goal(question):
        return about
    return goal_answer(factory, project, question, persona=persona, model=model)


def goal_answer(factory: Any, project: Any, question: str, *, persona: str, model: Any = None) -> dict[str, Any]:
    """Ask Rihma's answer to a goal in a project: the plan, in the assistant's answer shape."""
    p = plan(factory, project, question, model=model)
    first = next((s["action"] for s in p["steps"] if s["action"].get("route")), None)
    out = {"answer": p["answer"], "plan": {k: p[k] for k in ("goal", "intents", "steps", "gaps")},
           "navigate": {"route": first["route"], "control": first.get("control")} if first else None,
           "propose": [], "dropped": [], "sources": [project.pid], "by": "goal" if p["by"] == "rules" else "goal_model",
           "matches": p["intents"], "persona": persona}
    for key in ("note", "confidential"):
        if key in p:
            out[key] = p[key]
    if p.get("dropped"):
        out["plan"]["dropped"] = p["dropped"]
    return out
