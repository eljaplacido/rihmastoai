"""Ask Rihma about what IT checks, by rule and without a model, with Take me there (FR-ITO1).

- "What should IT check for this project?" (and "which infrastructure checks", "IT checks"): the check set with why
  each one is there and its state; a proposal to enable what is not enabled yet. Outside a project, every solution
  type's platform default;
- "Run the IT checks" (and "run the infrastructure checks"): a proposal to run the set now;
- "Run an assessment of the code" ("run the Optimise audit", "assess alignment", "run the TLS checks", "run the
  security eval"): a proposal of ``run_assessment`` with the target read from the words;
- "Which eval sets?" ("what evals can I run"): Gnomon's sets and the role evals with their scope and state; "enable
  the chaos eval set" proposes enabling it.

Each proposal is the same signed write the buttons make (kernel/assistant_ops.py), run only when the person
confirms it, and offered only to a persona that write allows (``allowed``): any other is told whose it is (FR-ITO2).
"""

from __future__ import annotations

import re
from typing import Any

# "IT" is the team, never the pronoun: "what does it check?" asks about something else.
# Lowercase "it" is read as the team only where the pronoun cannot stand: "the it checks", "what should it check for
# this project", as a phone types them (FR-ITO2).
ASK_SET = re.compile(r"\b(?:what|which)\b[^?.!]{0,40}\b(?:(?-i:IT)|infra(?:structure)?)\b[^?.!]{0,20}\bchecks?\b|"
                     r"\b(?:(?-i:IT)|infrastructure) checks?\b[^?.!]{0,30}\b(?:for|on)\b|\bcheck set\b|"
                     r"\bwhat should (?-i:IT) check\b|\bmitä (?-i:IT):n pitäisi tarkistaa\b|"
                     r"\bwhat should it check (?:for|on) (?:this|the|my|our) (?:project|service|app)\b|"
                     r"\b(?:what|which) are the it checks\b", re.IGNORECASE)
RUN_SET = re.compile(r"\b(?:run|start|do)\b[^?.!]{0,20}\b(?:(?-i:IT)|the it|infra(?:structure)?) checks?\b",
                     re.IGNORECASE)
# "run the TLS checks", "run the database check": one family of checks, run as an assessment of that family.
RUN_FAMILY = re.compile(r"\b(?:run|start|do)\b[^?.!]{0,20}\b(?:tls|certificate|dns|database|db|integration|job|"
                        r"scheduled job|ml|drift|agent|app|health endpoint)s? checks?\b", re.IGNORECASE)
ASSESS = re.compile(r"\b(?:run|start|do|make)\b[^?.!]{0,30}\b(?:assessment|audit|eval(?:uation)?s?)\b",
                    re.IGNORECASE)
EVALSETS = re.compile(r"\beval(?:uation)? sets?\b|\bwhich evals\b|\bwhat evals\b|\bevals can i run\b", re.IGNORECASE)
ENABLE_SET = re.compile(r"\b(enable|turn on|disable|turn off)\b[^?.!]{0,20}\b(?:the\s+)?"
                        r"([\w ]{2,40}?)\s+eval(?:uation)? set\b", re.IGNORECASE)
# The words an assessment's target is read from, first match wins.
TARGET_WORDS: tuple[tuple[str, str], ...] = (
    (r"optimi[sz]", "optimise"), (r"align", "alignment"), (r"\bcode\b|repository|repo\b", "code"),
    (r"\btls\b|certificate", "family:tls"), (r"\bdns\b|reachab", "family:dns"), (r"database|\bdb\b", "family:database"),
    (r"integration", "family:integration"), (r"\bjobs?\b|schedul", "family:job"), (r"drift|\bml\b|model eval",
                                                                                   "family:ml"),
    (r"\bagents?\b", "family:agent"), (r"\bapp\b|health endpoint", "family:app"),
    (r"security", "gnomon:security"), (r"compliance", "gnomon:compliance"), (r"chaos", "gnomon:chaos"),
    (r"infra|\bit checks?\b", "infra"))
VIEW = "itops_set"
# Ask Rihma's operations (kernel/assistant_ops.py): op -> (label, method, path, needs, sends, the map's control).
OPS: dict[str, tuple[str, str, str, tuple[str, ...], tuple[str, ...], str]] = {
    "apply_it_checks": ("Turn on the IT checks", "POST", "/api/projects/{pid}/itops/apply", (), ("only",),
                        "itops_apply"),
    "run_it_checks": ("Run the IT checks now", "POST", "/api/projects/{pid}/itops/run", (), (), "itops_run"),
    "change_it_check": ("Change this project's IT checks", "POST", "/api/projects/{pid}/itops/override",
                        ("check", "action"), ("check", "action", "why"), "itops_override"),
    "set_it_types": ("Choose the solution types", "POST", "/api/projects/{pid}/itops/types", (), ("types",),
                     "itops_types"),
    "change_it_default": ("Change a platform default check set", "POST", "/api/itops/defaults",
                          ("type", "action"), ("type", "check", "action", "why"), "itops_default_change"),
    "run_assessment_now": ("Run an assessment", "POST", "/api/projects/{pid}/itops/assess", ("target",), ("target",),
                           "itops_assess"),
    "toggle_evalset": ("Turn an eval set on or off", "POST", "/api/projects/{pid}/itops/evalsets", ("set",),
                       ("set", "on"), "itops_evalset"),
}


def _route(project: Any) -> str:
    return f"#/p/{project.pid}/itops" if project is not None else "#/connections"


def _out(answer: str, project: Any, control: str = VIEW, propose: list | None = None) -> dict[str, Any]:
    route = _route(project)
    open_it = {"action": "open", "args": {"route": route}, "why": "See the IT checks, why each is there, and enable, "
               "change or run them from there", "project": project.pid if project is not None else None}
    return {"answer": answer, "navigate": {"route": route, "control": control}, "propose": [open_it, *(propose or [])],
            "dropped": [], "sources": [], "by": "map", "matches": ["itops"]}


def allowed(op: str, args: dict[str, Any]) -> tuple[str, ...]:
    """The personas whose write this proposal is: a proposal another persona would see refused is never offered."""
    from kernel import itops, itops_assess, itops_evals
    from kernel.checks import ENABLERS

    if op == "change_it_default":
        return itops.DEFAULTERS
    if op == "toggle_evalset":
        return itops_evals._enablers()
    if op != "run_assessment_now":
        return itops.SETTERS
    kind = str(args.get("target") or "").split(":")[0]
    if kind == "infra":
        return itops.SETTERS
    if kind in ("check", "family"):
        return ENABLERS
    if kind == "optimise":
        from kernel import agentops_optimise as opt

        return tuple(opt.AUDITORS)
    return itops_assess.PERSONAS


def whose(op: str, args: dict[str, Any]) -> str:
    """Who to ask, in words, when the person's persona may not make this write."""
    names = ["IT" if p == "it" else p.replace("_", " ") for p in allowed(op, args)]
    return ", ".join(names[:3]) + (" and others" if len(names) > 3 else "")


def _act(factory: Any, op: str, args: dict[str, Any], persona: str, project: Any, summary: str) -> list:
    from kernel import assistant_ops

    if persona not in allowed(op, args):
        return []
    found = assistant_ops.proposal(factory, op, {**args, "project": project.pid}, persona=persona, project=project,
                                   summary=summary)
    return [found | {"why": summary}] if found else []


def set_answer(factory: Any, project: Any, persona: str) -> dict[str, Any]:
    from kernel import itops

    if project is None:
        p = itops.platform(factory)
        parts = [f"{t['label']}: " + (", ".join(c["check"] for c in t["checks"]) or "none (" + (t["none"] or "") + ")")
                 + (" (changed by IT)" if t["scope"] != "platform default" else "") for t in p["types"]]
        return _out("What IT checks, by solution type (platform defaults): " + "; ".join(parts) + ". Open a project "
                    "to see its own set and why each check is there.", None, "itops_defaults")
    s = itops.check_set(project)
    title = s["title"] or project.pid
    if not s["checks"]:
        return _out(f"{title}: {s['line']}.", project)
    types = ", ".join(f"{t['label']} ({'; '.join(t['why'])})" for t in s["types"])
    rows = "; ".join(f"{r['label']} ({r['state']}, {r['scope']}): {r['why'][0]}" for r in s["checks"])
    propose = _act(factory, "apply_it_checks", {}, persona, project, f"Enable {len(s['missing'])} IT check(s) on "
                   f"{title}") if s["missing"] else []
    mine = persona in allowed("apply_it_checks", {})
    tail = (f" {len(s['missing'])} are not enabled yet: " + ("I can enable them, signed with your name." if mine else
            f"turning them on is for {whose('apply_it_checks', {})}.")) if s["missing"] else " All are enabled."
    return _out(f"For {title} IT checks what it is: {types}. {rows}.{tail}", project, VIEW, propose)


def _target(question: str) -> str | None:
    low = question.lower()
    return next((t for pattern, t in TARGET_WORDS if re.search(pattern, low)), None)


def evalsets_answer(factory: Any, project: Any, persona: str, question: str) -> dict[str, Any]:
    from kernel import itops_evals

    view = itops_evals.view(project)
    asked = ENABLE_SET.search(question)
    if asked and project is not None:
        on, words = asked.group(1).lower() in ("enable", "turn on"), asked.group(2).strip().lower()
        found = next((r for r in view["sets"] if words in r["label"].lower() or words == r["id"].split(":")[-1]
                      .replace("_", " ")), None)
        if found is None:
            return _out(f"I found no eval set {words!r}. The Eval sets list names each one.", project, "itops_evalset")
        verb = "enable" if on else "disable"
        return _out(f"I can {verb} {found['label']} on this project ({found['scope']}); you confirm it, signed.",
                    project, "itops_evalset", _act(factory, "toggle_evalset", {"set": found["id"], "on": on}, persona,
                                                   project, f"{verb.capitalize()} the {found['label']} eval set"))
    rows = "; ".join(f"{r['label']} ({r['scope']}" + (", enabled" if r["enabled"] else "")
                     + (f", latest {r['latest']['verdict']}" if r.get("latest") else "")
                     + ("" if r["available"] else ", not on this machine") + ")" for r in view["sets"])
    return _out(f"{view['line']}: {rows}.", project, "itops_evalset")


def answer(factory: Any, question: str, project: Any, persona: str) -> dict[str, Any] | None:
    """The answer by rule, or None when the question is about something else."""
    if project is not None and str(project.pid).startswith("_"):
        project = None
    if RUN_SET.search(question) and project is not None:
        if persona not in allowed("run_it_checks", {}):
            return _out(f"Running the IT checks is for {whose('run_it_checks', {})}, not your persona: switch "
                        "persona in the person chip if you hold one of those, or ask them. You can read every check "
                        "and its last result on the IT checks view.", project, VIEW)
        return _out("I can run the IT checks of this project now; each result is recorded on Health. You confirm "
                    "it, signed.", project, "itops_run",
                    _act(factory, "run_it_checks", {}, persona, project, "Run the IT checks now"))
    if RUN_FAMILY.search(question) and project is not None and _target(question):
        return assess_answer(factory, project, persona, str(_target(question)))
    if EVALSETS.search(question) or ENABLE_SET.search(question):
        return evalsets_answer(factory, project, persona, question)
    if ASK_SET.search(question):
        return set_answer(factory, project, persona)
    if ASSESS.search(question) and project is not None:
        target = _target(question)
        if target is None:
            return None
        return assess_answer(factory, project, persona, target)
    return None


def assess_answer(factory: Any, project: Any, persona: str, target: str) -> dict[str, Any]:
    """A proposal to run one assessment, or who runs it when this persona may not."""
    args = {"target": target}
    if persona not in allowed("run_assessment_now", args):
        return _out(f"That assessment ({target}) is run by {whose('run_assessment_now', args)}, not your persona: "
                    "switch persona in the person chip if you hold one of those, or ask them.", project, "itops_assess")
    return _out(f"I can run that assessment ({target}) on this project now, with your rights; its result is "
                "recorded where it belongs. You confirm it.", project, "itops_assess",
                _act(factory, "run_assessment_now", args, persona, project, f"Run an assessment: {target}"))
