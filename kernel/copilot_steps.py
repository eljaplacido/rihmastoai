"""The steps of a goal plan, by rule (kernel/copilot.py, FR-CPL1): what each recognised goal asks of Rihmasto.

Every step names one action a person takes with one click (``STEP_KINDS``), and whether this build and this
factory have what it needs (``available``, and ``why_not`` when they do not). A step that changes something
only opens the place where a person does it, prefilled: drafting a change opens the change form for the
person to edit and file, configuring opens the settings, a command is shown to copy. Nothing here writes.
"""

from __future__ import annotations

import re
from typing import Any

from kernel.copilot_catalog import system_support

STEP_KINDS = ("draft_change", "walkthrough", "open", "configure", "enable_check", "automation", "command", "handoff")
AGENTS = ("claude-code", "codex", "opencode", "cursor", "generic")
QUESTIONS = {
    "connect": ["Which {label} folder, drive or data, and who owns it?",
                "Read only, or does the product also write back?",
                "Which data classes does it hold: public, internal, confidential or restricted?",
                "Whose account signs in: a service account IT manages?"],
    "schedule": ["What should happen on each run, and what if a run fails?", "At what time, in which time zone?"],
    "cloud": ["Which cloud and region? Is there a rule on where the data may live?",
              "Who operates it, and who is called when it fails?"],
    "test_env": ["Who tries it in the test environment, and with what data?"],
    "sign_in": ["Which identity provider: Entra ID, Okta, Google or another?",
                "Who may sign in, and with which roles?"],
    "monitor": ["What must be watched (up, response time, a business figure), and who gets the alert?",
                "Monitoring in Rihmasto, in your own tools (OpenTelemetry), or both?"],
    "evaluate": ["Which figures decide it (accuracy, loss, an eval set's score), and what counts as better?",
                 "Where does a new run's result land: a folder, an archive, a report?",
                 "Which command produces the figures, and may Rihmasto run it?"],
    "develop": ["How will you know it works: which test or check shows it (a time, a test, a figure)?",
                "Which part of the code does it touch, and what must keep working as it does today?"],
}
ASKS = {"connect": "The product reaches {label}.", "schedule": "It runs on a schedule.",
        "cloud": "It runs in the organisation's cloud.", "test_env": "It is deployed to a test environment first.",
        "sign_in": "People sign in through the organisation's identity provider.",
        "monitor": "Its health is watched, and someone is alerted when it fails.",
        "evaluate": "Each new run is evaluated against the baseline, and its figures are kept as evidence.",
        "develop": "The work itself changes (its code, content or pipeline, kept to its own conventions), with a test "
                   "that checks it, and what works today keeps working."}


def step(title: str, action: dict[str, Any], detail: str = "", *, available: bool = True, why_not: str = "",
         doc: str | None = None, who: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"title": title, "detail": detail, "action": action, "available": available}
    if not available:
        out["why_not"] = why_not
    if doc:
        out["doc"] = doc
    if who:
        out["who"] = who
    return out


def change_step(goal: str, intents: list[str], facts: dict[str, Any], label: str) -> dict[str, Any]:
    """Draft a change request with the goal in the person's words, what it asks and the questions it raises."""
    asks = [ASKS[i].format(label=label) for i in intents if i in ASKS]
    qs = [q.format(label=label) for i in intents for q in QUESTIONS.get(i, [])]
    text = (goal.strip().rstrip(".") + ".\n\nWhat this asks of the product:\n" + "\n".join(f"- {a}" for a in asks)
            + "\n\nQuestions it raises:\n" + "\n".join(f"- {q}" for q in qs)).strip()
    how = ("A person decides it in the Inbox, and the change loop carries it into the plan."
           if facts.get("contract") else "It goes into the plan before the contract is compiled.")
    # Filed as what it is: its questions end the text, and a text ending in "?" would be triaged as a question.
    hint = "change_request" if set(intents) <= {"develop", "handoff"} else "new_requirement"
    return step("Draft a change request", {"kind": "draft_change", "text": text, "hint": hint},
                f"Prefilled with your goal and the {len(qs)} question(s) it raises; edit it and file it. {how}")


def _route(views: set[str], view: str, pid: str) -> str | None:
    return f"#/p/{pid}/{view}" if view in views else None


def road_step(cat: dict[str, Any], facts: dict[str, Any], env: str, prefer: str | None = None) -> dict[str, Any]:
    """Where it runs: the roads IT configured that serve ``env``, or the gap and the kinds there are. ``prefer``
    is the road kind the goal names (a Google Cloud goal: ``gcp-cloudrun``), said first."""
    roads = [r for r in cat["roads"]["roads"] if r["configured"] and not r["builtin"] and env in r["environments"]]
    kinds = ", ".join(k for k in cat["roads"]["kinds"] if k != "local-process")
    pid = facts["pid"]
    named = (f"The goal names Google Cloud: a {prefer} road (a Cloud Run service, or a Cloud Run job on a schedule, "
             "in your Google Cloud project) is the kind for it (docs/guides/gcp.md). ") if prefer else ""
    if roads:
        names = ", ".join(f"{r['name']} ({r['kind']})" for r in roads)
        chosen = facts.get("paved_road")
        missing = named if prefer and not any(r["kind"] == prefer for r in roads) else ""
        picks = f" This project names {chosen}." if chosen else " The project's maturity picks the road."
        return step(f"Choose where it runs in {env}", {"kind": "open", "route": f"#/p/{pid}/releases"},
                    missing + f"Roads IT configured for {env}: {names}." + picks, doc="docs/guides/deploying.md")
    # No road to choose yet: IT configures one; copying `rihmasto deliver` here would only stop on a road card.
    return step(f"Choose where it runs in {env}", {"kind": "open", "route": f"#/p/{pid}/releases"},
                named + f"Kinds of road this build has: {kinds}.", available=False,
                why_not=f"no paved road is configured for {env}: IT adds one to paved_roads.json and marks it "
                        "configured (docs/guides/deploying.md); until then a delivery stops on a road card for IT",
                doc="docs/guides/deploying.md", who="it")


def automation_step(cat: dict[str, Any], facts: dict[str, Any], views: set[str], title: str,
                    template: str | None, draft: dict[str, Any]) -> dict[str, Any]:
    au = cat["automations"]
    pid = facts["pid"]
    if not au["available"]:
        return step(title, {"kind": "automation", "template": template, "draft": draft}, available=False,
                    why_not="automations are not in this Rihmasto yet: a scheduler line (cron or Task Scheduler) that "
                            f"runs `rihmasto run {pid}` does it meanwhile")
    known = {t["id"] for t in au["templates"]}
    action = {"kind": "automation", "template": template if template in known else None, "draft": draft,
              "route": _route(views, "automations", pid) or ("#/automations" if "automations_all" in views else None)}
    # A command only when it is a whole one (a template, for this project); otherwise the button opens the
    # automation builder with the draft filled in.
    cmd = ({"command": f"rihmasto automations add --template {template} --project {pid} --person ... "
                       "--persona developer"} if template in known else {})
    return step(title, action | cmd,
                "Runs with your rights and never decides a card; you see its summary before you save it.",
                doc="docs/guides/automations.md")


def handoff_step(facts: dict[str, Any], to: str = "generic") -> dict[str, Any]:
    pid = facts["pid"]
    secret = (" This project is confidential: give it only to an agent on a local model; a coding agent on a hosted "
              "model (Claude Code, Codex, OpenCode or Cursor as they come) sends the repository to that host. The "
              "brief says so too.") if facts.get("confidential") else ""
    return step("Hand it to a coding agent", {"kind": "handoff", "to": to,
                                              "command": f"rihmasto handoff {pid} --to {to}"},
                "A brief with the goal, the contract's criteria, the open questions, the plan, the findings and how "
                "to report back; the agent posts its progress to the project's agent channel." + secret,
                doc="docs/guides/agentic-help.md")


USE_CONTROL = {"claude-code": "models_use_claude", "codex": "models_use_codex", "opencode": "models_use_opencode"}


def harness_step(cat: dict[str, Any], facts: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """When no model Rihmasto talks with answers and a coding agent is on this machine: let it answer the text
    roles (kernel/harness_setup.py, FR-HMD1). Nothing otherwise, and never for a confidential project: a
    coding agent's subscription is a hosted model, which such a project's roles may not call."""
    m = cat.get("models") or {}
    if m.get("ready", True) or not m.get("harnesses") or (facts or {}).get("confidential"):
        return []
    h = m["harnesses"][0]
    others = ", ".join(x["label"] for x in m["harnesses"][1:])
    return [step(f"Use the coding agent you already have: {h['label']}",
                 {"kind": "configure", "route": "#/models", "control": USE_CONTROL.get(h["id"]),
                  "command": f"rihmasto models use {h['id']} --roles all --person ... --persona it"},
                 "No model Rihmasto talks with answers yet; " + h["label"] + " on this machine can answer the analyst, "
                 "the holdout author, the verifier and the assistant, headless and toolless, with your own "
                 "subscription" + (f" ({others} too)" if others else "") + ".", who="it",
                 doc="docs/guides/harness-models.md")]


# -- per goal ---------------------------------------------------------------------------------------------

def connect(cat: dict[str, Any], facts: dict[str, Any], views: set[str], system: tuple[str, str] | None,
            gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pid = facts["pid"]
    key, label = system or ("api", "the system")
    sup = system_support(cat, key, label)
    out = []
    compiled = facts.get("contract")
    via_change = ("its plan is compiled already, so the integration is not declared here: file the drafted change "
                  "(the first step), and the change loop adds it")
    name = key.replace("google_", "")[:24] + "_data"
    data_class = "confidential" if facts.get("confidential") else "internal"
    own_code = facts.get("source_kind") in ("adopted", "attached")
    if sup["how"] == "connector" and not sup["enabled"]:
        c = sup["connector"]
        out.append(step(f"IT turns on the {c['title']} connector", {"kind": "command", "command":
                        f"rihmasto connector enable {c['system']} --person ... --persona it"},
                        f"It is {c['state']} now; a connector card pins it and only IT decides it.", who="it",
                        doc="docs/guides/integrations.md"))
    if sup["how"] in ("connector", "kind"):
        kind = sup["kind"] or sup["connector"]["system"]
        cmd = (f"rihmasto integration declare {pid} --name {name} --kind {kind} --access read --data-class "
               f"{data_class} --person ... --persona product_owner")
        client = next((k["client"] for k in cat["integration_kinds"] if k["kind"] == kind and k.get("client")),
                      None)
        road = f" through the paved road's own client ({client})" if client else ""
        reach = ((" The product reaches it with its own code, as it does today" + (f", or{road} if it adopts it"
                                                                                  if road else "") + ".")
                 if own_code else (f" The product reaches it{road}." if road else ""))
        out.append(step(f"Declare the {label} integration", {"kind": "configure", "route": _route(views, "plan", pid),
                                                              "control": "integrations", "command": cmd},
                        "The product names what it needs; IT binds where the credential lives on the road." + reach,
                        available=not compiled, why_not=via_change, doc="docs/guides/data-integrations.md"))
    else:
        gaps.append({"what": sup["gap"], "options": sup["options"]})
        cmd = (f"rihmasto integration declare {pid} --name {name} --kind rest --access read --data-class "
               f"{data_class} --person ... --persona product_owner")
        out.append(step(f"Reach {label} through its API, declared as a REST integration",
                        {"kind": "configure", "route": _route(views, "plan", pid), "control": "integrations",
                         "command": cmd}, "One of the options while there is no connector.",
                        available=not compiled, why_not=via_change, doc="docs/guides/data-integrations.md"))
        out.append(step(f"Ask for a {label} connector", {"kind": "command", "command":
                        f"rihmasto signal log --text \"A {label} connector\" --channel chat --source \"goal help\" "
                        "--person ... --persona ..."}, "A signal in the delivery square; a person triages it."))
    out.append(road_step(cat, facts, "production"))
    out.append(automation_step(cat, facts, views, f"Keep {label} in sync on a schedule", None,
                               {"trigger": {"kind": "schedule", "daily": "02:00"},
                                "scope": {"kind": "project", "projects": [pid]}}))
    return out


def cloud(cat: dict[str, Any], facts: dict[str, Any], views: set[str], said: str,
          gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    google = any(w in said for w in ("gcp", "google cloud", "cloud run"))
    if google and not cat["roads"]["gcp"]:
        gaps.append({"what": "There is no Google Cloud road in this Rihmasto yet.",
                     "options": ["the docker road on a virtual machine in your Google Cloud project",
                                 "Azure Container Apps, if the organisation has Azure",
                                 "the Compose file of a delivered release, run by your own platform team"]})
    prefer = next((k for k in cat["roads"]["kinds"] if k.startswith("gcp")), None) if google else None
    pid = facts["pid"]
    return [road_step(cat, facts, "staging", prefer), road_step(cat, facts, "production", prefer),
            step("Deliver through the deploy gate", {"kind": "command", "command": f"rihmasto deliver {pid}"},
                 "Staging first; production waits on a deploy-gate card a person decides.",
                 doc="docs/guides/deploying.md")]


def test_env(cat: dict[str, Any], facts: dict[str, Any], views: set[str]) -> list[dict[str, Any]]:
    pid = facts["pid"]
    return [road_step(cat, facts, "staging"),
            step("Try it", {"kind": "open", "route": _route(views, "try", pid) or f"#/p/{pid}/overview"},
                 "The checklist people try a release with, criterion by criterion.")]


def schedule(cat: dict[str, Any], facts: dict[str, Any], views: set[str], goal: str = "") -> list[dict[str, Any]]:
    """The automation itself, with the person's own words carried into Describe it (``describe``), read there into
    a draft ready to set up; a re-gate goal on a repository Rihmasto gates picks the Nightly re-gate template."""
    regate = facts.get("source_kind") in ("attached", "adopted") or re.search(r"\b(tests?|gate)\b", goal.lower())
    out = automation_step(cat, facts, views, "Set up the automation", "nightly_regate" if regate else None,
                          {"trigger": {"kind": "schedule", "daily": "02:00"},
                           "scope": {"kind": "project", "projects": [facts["pid"]]}})
    if goal.strip():
        out["action"]["describe"] = goal.strip()[:2000]
        out["detail"] = ("Opens Automations with your words in Describe it, read into a draft with its summary and a "
                         "dry run: Set it up saves it, signed. " + str(out.get("detail") or ""))
    return [out]


def monitor(cat: dict[str, Any], facts: dict[str, Any], views: set[str]) -> list[dict[str, Any]]:
    pid = facts["pid"]
    kinds = {c["kind"] for c in cat["checks"]["kinds"]}
    out = []
    for kind, title in (("probe", "Enable an HTTP probe"), ("ci", "Enable the CI status check")):
        out.append(step(title, {"kind": "enable_check", "check": kind, "route": _route(views, "checks", pid),
                                "control": "health_enable"}, "Passed, failed or not measured, with its evidence.",
                        available=kind in kinds, why_not="checks are not in this Rihmasto yet: the Track view and "
                        "the release probes show what Rihmasto watches today", doc="docs/guides/console-and-checks.md"))
    out.append(step("Send events to your own tools", {"kind": "command", "command":
                    "rihmasto relay subscribe --sink webhook --url https://... --person ... --persona it"},
                    "OpenTelemetry, CloudEvents or a webhook: your monitoring keeps its tools (D-0017).", who="it"))
    return out


def evaluate(cat: dict[str, Any], facts: dict[str, Any], views: set[str]) -> list[dict[str, Any]]:
    """Evaluate each new run against the baseline: the evaluation command as a check, and, adopted, the watch."""
    pid = facts["pid"]
    kinds = {c["kind"] for c in cat["checks"]["kinds"]}
    out = [step("Run your evaluation as a check", {"kind": "enable_check", "check": "custom",
                                                   "route": _route(views, "checks", pid), "control": "health_enable",
                                                   "command": f"rihmasto checks enable {pid} custom --set command=..."},
                "A custom check runs the command that produces the figures, on demand or on a schedule: passed, "
                "failed or not measured, each run kept with its output. Rihmasto runs only the command you give it.",
                available="custom" in kinds, why_not="checks are not in this Rihmasto yet: the Console runs the "
                "command once, recorded in the ledger", doc="docs/guides/console-and-checks.md")]
    if facts.get("source_kind") == "adopted":
        out.append(step("Watch it for new results", {"kind": "open", "route": f"#/p/{pid}/overview",
                                                      "control": "watch_setup"},
                        "New commits become a summary in Review, and a failed check notifies a channel."))
    return out


def sign_in(cat: dict[str, Any], facts: dict[str, Any], views: set[str]) -> list[dict[str, Any]]:
    pid = facts["pid"]
    has = any(o["id"] == "login_web_app" for o in cat["outputs"])
    return [step("Choose the web app with sign-in as an output", {"kind": "configure", "route":
                 _route(views, "outputs", pid), "control": "choose_outputs", "prefill": {"target": "login_web_app"}},
                 "The paved road's sign-in, and the organisation's own sign-in through a proxy (SIGN-IN.md).",
                 available=has, why_not="this build has no sign-in output")]


def develop(cat: dict[str, Any], facts: dict[str, Any], views: set[str], said: str = "") -> list[dict[str, Any]]:
    """Developing an existing product further: what its repository already says, the work in a branch of one's
    own (an attached repository is worked on in place and its commits judged by the gate), its tests as a Health
    check when the goal names one, the commits sent through the gate, and its tests in the Console. A project with
    no code of its own gets the change request and the hand-off only."""
    pid, kind = facts["pid"], facts.get("source_kind")
    if kind not in ("adopted", "attached"):
        return []
    who = facts.get("who") or '--person "<your name>" --persona developer'
    out = [step("See what its repository already says", {"kind": "open", "route": _route(views, "align", pid),
                                                          "control": "align_scan"},
                "Its own specs, criteria, tests and tasks, read by rule: accept what is the product's own, so the "
                "change is checked against them.", doc="docs/guides/alignment.md")]
    if kind == "attached":
        out.append(step("Build it in your repository; the gate judges the commit",
                        {"kind": "command", "command": f"rihmasto repo gate {pid} --head <commit>"},
                        "Rihmasto never writes to your repository: commit as you always do.", who="developer"))
    else:
        out.append(step("Build it in a branch of your own",
                        {"kind": "command", "command": f"rihmasto workspace open {pid} {who} --agent shell"},
                        "Clones main onto a branch of your own and prints the folder; or open Console, Open a "
                        "terminal here in the cockpit.", who="developer", doc="docs/guides/ide-and-rihmasto.md"))
    if any(w in said for w in ("test", "check", "testi")):
        kinds = {c["kind"] for c in cat["checks"]["kinds"]}
        out.append(step("Run its tests as a Health check", {"kind": "enable_check", "check": "tests",
                                                            "route": _route(views, "checks", pid),
                                                            "control": "health_enable"},
                        "Name the test command once; it runs on demand or on a schedule, passed, failed or not "
                        "measured with its evidence.", available="tests" in kinds,
                        why_not="checks are not in this Rihmasto yet", doc="docs/guides/console-and-checks.md"))
    if kind != "attached":
        out.append(step("Send your commits through the gate", {"kind": "command", "command":
                        f"rihmasto workspace submit {pid} . {who}"},
                        "Run in the workspace folder: the tests, the criteria traced and the independent verifier; "
                        "warranted, it merges into main.", doc="docs/guides/ide-and-rihmasto.md", who="developer"))
    out.append(step("Run its tests in the Console", {"kind": "open", "route": _route(views, "console", pid),
                                                     "control": "console_run"},
                    "The project's own commands as buttons, the output line by line, recorded in the ledger."))
    return out
