"""Guided journeys (FR-JRN1, docs/guides/guided-journeys.md): the real ways through Rihmasto, step by step.

A journey is a named, ordered list of steps. Each step says what it is in plain words (a business persona's
words where they differ), why it matters, how to tell it is done (``check``: a rule over the records, in
kernel/journey_state.py), the action that does it (a control of cockpit/ui_map.json, the chat walkthrough that
does it, or a proposal Rihma makes in the chat that the person confirms), the command line, what it needs
first and what to do when it fails. Because every step is measured from the records, a journey resumes where
the person is, whoever did the step and wherever (the cockpit, Ask Rihma, the command line).

The journeys are the playbooks the docs describe (docs/brownfield.md, docs/guides): feed in an existing project
(in depth), start from a new idea, start from documents, set up a model, connect your IDE or coding agent,
first deploy, and set up automations. Nothing here reads or writes a record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The personas whose words are the business words; the others read the technical ones.
BUSINESS = frozenset({"business_owner", "product_owner", "stakeholder", "concept_evaluator", "end_user"})
SIGN = "--person {you} --persona {persona}"


@dataclass(frozen=True)
class Step:
    """One step of a journey (see the module's docstring)."""

    id: str
    title: str
    why: str
    done_when: str
    check: str
    button: str
    control: str | None = None
    view: str | None = None
    page: str | None = None
    walkthrough: str | None = None
    do: str | None = None
    command: str = ""
    needs: tuple[str, ...] = ()
    if_fails: str = ""
    optional: bool = False
    business: str = ""
    not_yet: str = ""                   # what the records say while it is not done ("the assessment has not run")
    prefer: tuple[str, ...] = ()        # controls to point at instead, when this build's map has them
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Journey:
    """A named, ordered list of steps; ``scope`` says whether it is about one project or the whole factory."""

    name: str
    label: str
    about: str
    scope: str
    steps: tuple[Step, ...]
    walkthrough: str | None = None
    business_label: str = ""
    anchor: str = ""                    # the step whose record says where the project came from ("adopted 2 h ago")


def _s(sid: str, title: str, why: str, done_when: str, check: str, button: str, **kw: Any) -> Step:
    return Step(sid, title, why, done_when, check, button, **kw)


BROWNFIELD = Journey("brownfield", "Feed in an existing project", (
    "a project you already have, from its folder or git address, adopted, measured, assessed and aligned, then "
    "changed through the gate"), "project", walkthrough="plug_in",
    business_label="Bring in a system we already have", anchor="adopt", steps=(
        _s("folder", "Choose the folder or git address", "Rihmasto reads only what you point it at.",
           "a folder or address was given, or the project is adopted", "folder_given", "Walk me through it",
           control="adopt_project", page="projects", walkthrough="plug_in", prefer=("pick_folder",),
           command="rihmasto scan <folder>",
           if_fails="A folder outside the allowed ones is refused: Allow the folder (a single operator), or ask IT "
                    "to add it in Settings, Folders.", business="Say where the system's files are"),
        _s("scan", "Scan it and choose what is sent", (
            "You see what would be read, summarised, listed or skipped before anything is sent or kept; untick what "
            "should stay out. Secret-looking files are never opened."),
           "the folder was scanned, or the project is adopted", "scanned", "Scan the folder",
           control="scan_source", page="projects", walkthrough="plug_in", needs=("folder",),
           command="rihmasto scan <folder> [--exclude GLOB]",
           if_fails="A long scan shows its progress and Cancel the scan stops it. A folder with documents only is "
                    "offered as material for a new project instead.", business="See what Rihmasto would read"),
        _s("adopt", "Adopt it", (
            "The project gets a mirror of the code, an inventory, a test baseline and an as-is spec. Your folder is "
            "never changed."), "the project is adopted (the ledger's adopted record)", "adopted", "Adopt",
           control="adopt_project", page="projects", walkthrough="plug_in", needs=("scan",),
           command="rihmasto adopt \"<title>\" --source <folder> --intent maintain " + SIGN,
           if_fails="The adoption job's page says why; nothing is half-adopted. Fix the cause (a folder that is not "
                    "allowed, a git address that needs credentials: clone it yourself and adopt the folder) and "
                    "adopt again.", business="Bring it in"),
        _s("baseline", "Baseline tests", (
            "The existing tests run once, so every later change is measured against how the code behaves today."),
           "the baseline is passed or failed, or a stated test command was run", "baseline", "Run the stated command",
           control="baseline_stated", view="overview", needs=("adopt",), optional=True,
           command="rihmasto baseline {pid} --command \"<the stated command>\" --yes " + SIGN,
           if_fails="Failing tests are recorded, not judged. \"Not measured\" means no runner the kernel knows ran "
                    "them: run the test command your instructions state as the baseline.",
           business="Record how it behaves today"),
        _s("spec", "As-is spec and contract", (
            "R-1 says the existing tests keep passing; the contract is what every later change is checked against."),
           "the as-is spec is compiled into the project's contract", "contract", "Open the spec",
           view="spec", needs=("adopt",), command="rihmasto status {pid}",
           if_fails="No contract: the adoption did not finish. Open the adoption job, or adopt again.",
           business="See what it promises today"),
        _s("assess", "Run the assessment", (
            "It reads the repository from five perspectives (CI/CD, maintenance, security, compliance, architecture "
            "and operations) and lists what to fix, each with its evidence. By rule it takes seconds and runs "
            "nothing of the repository."), "an assessment version (AS-1 or later) is recorded", "assessed",
           "Run the assessment", control="run_assessment", view="assessment", do="assess", needs=("adopt",),
           command="rihmasto assess {pid} " + SIGN,
           if_fails="\"No repository\" means it is not adopted yet. If one is still running, wait for it. A check that "
                    "cannot know says not measured, with why.", business="Have it checked for what to fix",
           not_yet="the assessment has not run yet"),
        _s("review", "Review the gaps and the alignment", (
            "The findings that matter become changes, and the repository's own specs, criteria and tests come into "
            "the contract (you accept, edit or reject each)."),
           "the repository was read for alignment, or findings were filed as changes", "reviewed",
           "Read the repository", control="align_scan", view="align", do="align", needs=("assess",),
           command="rihmasto align {pid} --scan " + SIGN + "   (findings: rihmasto assessment change {pid} F-1 ...)",
           if_fails="Nothing proposed means the repository holds no specs or tests the rules recognise: that is a "
                    "gap, and the assessment says so.", business="Choose what to fix first",
           not_yet="the gaps and the alignment are not reviewed yet"),
        _s("tools", "AI tools and conventions for your IDE agents", (
            "Your CLAUDE.md, AGENTS.md, skills and MCP servers stay the agent's context; the IDE section tells the "
            "agent the contract and how a change comes back."),
           "a hand-off, a workspace or your word that the section is in place", "tools", "Work on it from your IDE",
           control="ide_setup", view="overview", needs=("adopt",), optional=True,
           command="rihmasto ide {pid} --section",
           if_fails="No AI tools found is fine: the IDE section and the MCP configuration work without them.",
           business="Let the team's coding assistants work with it"),
        _s("checks", "Checks and automations", (
            "A check on a schedule and a watch on new commits catch drift without anyone looking."),
           "a check is enabled, the watch is set, or an automation reaches it", "watched", "Set up the watch",
           control="watch_setup", view="overview", do="watch", needs=("adopt",),
           command="rihmasto checks enable {pid} secrets " + SIGN,
           if_fails="A watch that cannot set an automation falls back to `rihmasto sync` and says so.",
           business="Get told when something changes or breaks", not_yet="nothing watches it yet"),
        _s("change", "First change through the gate", (
            "Every change is tested, traced and verified before it merges into what the factory holds."),
           "a change was applied or merged (filed or submitted counts as under way)", "changed", "Report a change",
           control="report", view="changes", needs=("adopt",),
           command="rihmasto change {pid} \"<what to change>\" " + SIGN
                   + "   (or rihmasto workspace open {pid} ... then workspace submit)",
           if_fails="A gate that fails names the check; fix it and submit again. The escalation lists each "
                    "objection.", business="Ask for the first improvement",
                    not_yet="no change has gone through the gate yet"),
        _s("deploy", "Where it deploys", (
            "IT chooses the paved road for each environment. An adopted repository has no delivery road yet: "
            "Rihmasto monitors and gates it while it runs where it runs today."),
           "a road is chosen, or a release is recorded", "deployed", "Where it deploys",
           control="choose_road", view="releases", needs=("adopt",), optional=True,
           command="rihmasto road choose {pid} <road> --person {you} --persona it",
           if_fails="Paved roads (Settings) says exactly what a road is missing.",
           business="Decide where it runs"),
    ))

NEW_IDEA = Journey("new_idea", "Start from a new idea", (
    "a need in a few sentences, shaped in a chat and made a project, its questions answered, a plan approved, "
    "then built and delivered"), "project", walkthrough="new_idea", business_label="Start from a new idea",
    anchor="idea", steps=(
        _s("idea", "Say the need", "Rihma asks only what the need does not say.",
           "the project exists", "made", "Walk me through it", control="shape_open", page="shape",
           walkthrough="new_idea", command="rihmasto shape start --text \"<the need>\" " + SIGN,
           if_fails="No model answers: Set up a model first, or start from the form in New project."),
        _s("questions", "Answer the questions", "The panel asks what it needs to write the spec.",
           "the intake is done and no blocking question is open", "answered", "Answer the questions",
           control="answer", view="questions", needs=("idea",),
           command="rihmasto answer {pid} Q-001 \"<answer>\" " + SIGN,
           if_fails="A question that does not fit: change the kind of work in Project settings.",
           business="Answer what it asks"),
        _s("plan", "Approve the plan", "Nothing is built before a person approves what will be built.",
           "the plan is approved, or the contract is compiled", "planned", "Open the plan", view="plan",
           needs=("questions",), command="rihmasto run {pid}",
           if_fails="Send it back with a reason, or go back a step."),
        _s("build", "Build it", "Each task is built and gated: tested, traced and verified.",
           "a build passed or merged", "built", "Advance the project", control="next_step", view="overview",
           needs=("plan",), command="rihmasto run {pid}",
           if_fails="What's next says what it waits for: a decision, a model, the autonomy cap."),
        _s("deliver", "Deliver it", "The paved road for its maturity runs it where it should run.",
           "a release is done", "delivered", "Releases", view="releases", needs=("build",),
           command="rihmasto deliver {pid}", if_fails="A failed release says which step; retry or change it."),
    ))

DOCUMENTS = Journey("documents", "Start from documents", (
    "a spec or a folder of material, scanned and made a project, then its questions, plan, build and delivery"),
    "project", walkthrough="documents", business_label="Start from our documents", anchor="create", steps=(
        _s("docs", "Choose the documents", "A folder of material or one file; secret-looking files are never opened.",
           "a folder or file was given, or the project exists", "docs_given", "Walk me through it",
           control="scan_source", page="projects", walkthrough="documents",
           command="rihmasto scan <folder>", if_fails="A folder outside the allowed ones: ask IT to allow it."),
        _s("create", "Create the project", "Its intake reads the material and asks only what it does not say.",
           "the project exists", "made", "Create", control="new_project", page="projects", walkthrough="documents",
           needs=("docs",), command="rihmasto new \"<title>\" --source <folder> --requested-by {you}"),
        *NEW_IDEA.steps[1:],
    ))

MODEL = Journey("model", "Set up a model", (
    "who answers each role, a local model, a hosted one or the coding agent you already have"), "factory",
    walkthrough="model", steps=(
        _s("open", "Open Models setup", "Each role (analyst, assistant, builder, verifier) has its own model.",
           "a role is set, or you said you looked", "models_seen", "Open Models setup", control=None,
           page="models", command="rihmasto models list"),
        _s("set", "Set who answers", (
            "A local server, a hosted endpoint with its key, or Claude Code, Codex or OpenCode you already have."),
           "a role is set here (models_set or models_use in the factory's ledger)", "models_set", "Set a role",
           control="models_set", page="models", walkthrough="model", needs=("open",),
           command="rihmasto models set assistant --base-url <url> --model <model> " + SIGN
                   + "   (or rihmasto models use claude-code)",
           if_fails="Test says what failed: the port, the key or the model name."),
        _s("test", "Test it", "One short prompt shows the role answers before work depends on it.",
           "you said it answered", "mark", "Test", control="models_test", page="models", needs=("set",),
           command="rihmasto doctor"),
        _s("local", "Keep confidential work local", "A confidential project is refused on a hosted model.",
           "you said so, or nothing here is confidential", "mark", "Use a local model", control="use_local_model",
           page="models", needs=("set",), optional=True),
    ))

IDE = Journey("ide", "Connect your IDE or coding agent", (
    "Claude Code, Cursor, Codex or OpenCode on a project, with its AI tools, the MCP configuration, the contract "
    "for the agent, and its changes coming back through the gate"), "project", steps=(
        _s("tools", "See the AI tools it uses", "Rihmasto reads the conventions; it runs none of them.",
           "you looked, or a hand-off was given", "tools", "AI tools in this project", control="ai_tools",
           view="overview", command="rihmasto ide {pid}"),
        _s("config", "Connect the IDE", "Ready-to-paste MCP configuration, signed with your name and persona.",
           "you said it is connected, or a hand-off was given", "tools", "Work on it from your IDE",
           control="ide_setup", view="overview", needs=("tools",), command="rihmasto ide {pid}"),
        _s("section", "Give the agent the contract", (
            "You paste the section into AGENTS.md or CLAUDE.md yourself; Rihmasto never writes into your folder."),
           "you said it is pasted", "mark", "Copy the section", control="ide_section", view="overview",
           needs=("config",), command="rihmasto ide {pid} --section"),
        _s("handoff", "Hand off a piece of work", "The brief carries the goal, the criteria and how to report back.",
           "a hand-off is recorded", "handed_off", "Hand off to an agent", control="handoff", view="overview",
           needs=("config",), command="rihmasto handoff {pid} --to claude-code"),
        _s("back", "Bring the change back through the gate", "The gate decides what merges, not the agent.",
           "a change was submitted or merged", "changed", "Report a change", control="report", view="changes",
           needs=("handoff",), command="rihmasto workspace submit {pid} <path> " + SIGN),
    ))

DEPLOY = Journey("deploy", "First deploy", (
    "a paved road that is ready, the project's road, the build and the release, and its probes"), "project", steps=(
        _s("roads", "See which roads are ready", "Each road says exactly what it is missing.",
           "you looked, or a road is chosen", "roads_seen", "Paved roads", control="paved_roads", page="settings",
           command="rihmasto road list"),
        _s("choose", "Choose the project's road", "IT chooses where each environment lands.",
           "a road is chosen", "road_chosen", "Choose the road", control="choose_road", view="releases",
           needs=("roads",), command="rihmasto road choose {pid} <road> --person {you} --persona it"),
        _s("build", "Build it", "A release is only made from a build that passed the gate.",
           "a build passed or merged", "built", "Advance the project", control="next_step", view="overview",
           needs=("choose",), command="rihmasto run {pid}"),
        _s("release", "Deliver it", "The road runs it, environment by environment.",
           "a release is done", "delivered", "Releases", view="releases", needs=("build",),
           command="rihmasto deliver {pid}"),
        _s("probe", "Watch it run", "Its probes say whether it answers; a failure opens an incident card.",
           "a probe ran", "probed", "Releases", view="releases", needs=("release",), optional=True,
           command="rihmasto operate {pid}"),
    ))

AUTOMATIONS = Journey("automations", "Set up automations", (
    "a schedule or an event that runs something for you, started from a template, tried as a dry run, saved and "
    "seen running"), "project", steps=(
        _s("open", "Open Automations", "Automations run with your rights, within their limits.",
           "you looked, or an automation reaches the project", "automation_seen", "New automation",
           control="automations_new", view="automations", command="rihmasto automations list"),
        _s("template", "Start from a template", "Nightly re-gate, notify on release, weekly re-scan and more.",
           "an automation reaches the project", "automated", "Start from a template", control="automations_template",
           view="automations", needs=("open",),
           command="rihmasto automations add --name <name> --every 1d ... " + SIGN),
        _s("dry_run", "Try it as a dry run", "It says what it would do, and does nothing.",
           "you said you tried it, or it ran", "automation_ran", "Dry run", control="automations_dry_run",
           view="automations", needs=("template",), optional=True),
        _s("ran", "See it run", "Each run is in the ledger; three failures in a row pause it.",
           "it ran at least once", "automation_ran", "Run now", control="automations_run", view="automations",
           needs=("template",), command="rihmasto automations run-now <AU-id> " + SIGN),
    ))

JOURNEYS: dict[str, Journey] = {j.name: j for j in (BROWNFIELD, NEW_IDEA, DOCUMENTS, MODEL, IDE, DEPLOY, AUTOMATIONS)}
# The three a new person is offered on an empty Home or Projects page.
STARTERS = ("brownfield", "new_idea", "documents")


def journey(name: str) -> Journey:
    if name not in JOURNEYS:
        raise KeyError(f"no journey {name!r}: one of {', '.join(JOURNEYS)}")
    return JOURNEYS[name]


def label(j: Journey, persona: str | None = None) -> str:
    return j.business_label if persona in BUSINESS and j.business_label else j.label


def title(step: Step, persona: str | None = None) -> str:
    """The step in the persona's words: a business persona reads what it achieves, the others what it is."""
    return step.business if persona in BUSINESS and step.business else step.title


def control(step: Step) -> str | None:
    """The control the step points at: one it prefers when this build's map has it (Browse for the folder, where
    the folder picker is in), else its own."""
    if step.prefer:
        from kernel.assistant_rules import ui_map

        ids = {c["id"] for c in ui_map()["controls"]}
        return next((c for c in step.prefer if c in ids), step.control)
    return step.control


def command(step: Step, *, pid: str | None = None, person: str | None = None, persona: str | None = None) -> str:
    """The step's command line with what is known filled in; what is not stays a <placeholder>."""
    you = f'"{person}"' if person and " " in person else (person or "<you>")
    return step.command.replace("{pid}", pid or "<project>").replace("{you}", you).replace(
        "{persona}", persona or "<persona>")


def catalogue(persona: str | None = None) -> list[dict[str, Any]]:
    """The journeys, in order, with their steps' titles."""
    return [{"name": j.name, "label": label(j, persona), "about": j.about, "scope": j.scope,
             "walkthrough": j.walkthrough, "starter": j.name in STARTERS,
             "steps": [{"id": s.id, "title": title(s, persona), "optional": s.optional} for s in j.steps]}
            for j in JOURNEYS.values()]
