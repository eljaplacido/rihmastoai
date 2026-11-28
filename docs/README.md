# Rihmasto documentation

Every guide and reference page that ships with Rihmasto, grouped by capability area, with the
paths for each scenario first. A page can sit in more than one group. Pages marked *design*
describe something planned; they say inside what is built and what is not.

## Start here

- [The README](../README.md): what Rihmasto is, which path to pick, the quick start, the scenarios
  step by step, the capability breakdown and the project's status (what is built, what is tested only
  against stand-ins, and what is landing next).
- [Getting started](getting-started.md): install, the demo, models and Gnomon (with checksum and
  provenance verification), a first real project, the cockpit, where things are kept.
- [Configure with your agents](guides/configure-your-agents.md): Claude Code, Cursor, Codex and
  OpenCode through MCP, your AGENTS.md or CLAUDE.md, and hooks; how your agent's work comes back.
- [Architecture](architecture.md): the picture and a Mermaid diagram of how the parts relate (the
  kernel, the data and knowledge layers, the agent layer with Gnomon, the destinations), with the code
  behind each part.
- [Scenarios](scenarios/README.md): pick where you start, and see what happens under the hood.
- [The demo](demo.md): what the demo home holds, and what each persona sees in it.
- [How it works](how-it-works.md): the chain step by step, the delivery square, personas and
  lenses, and what Gnomon does beside the kernel.
- [Walkthroughs in Ask Rihma](guides/walkthroughs.md): Rihma walks you through plugging in an existing
  project, starting from an idea or documents, setting up a model, or a tour, step by step in the chat.
- [Guided journeys](guides/guided-journeys.md): the larger paths through Rihmasto, measured from the records,
  with a next step, its real action and command, and a guide that stays with you.
- [Use only what you need](guides/use-only-what-you-need.md): the modules and the presets (spec only,
  gate my code, assess, security or evidence only, a capability, the full chain), and changing them.
- [The acceptance matrix](acceptance.md): every use case and mode, measured, and the live acid test.

## By scenario

**Before any scenario.** [Getting started](getting-started.md) to install and pick a model
([models setup](guides/models-setup.md), or [your coding agent as the model](guides/harness-models.md)),
then start the cockpit on your own home, not the demo, and
[connect your coding agent](guides/configure-your-agents.md).

Each scenario has a guide that walks through it and says what happens under the hood:

- [Start from a blank page](scenarios/start-blank.md): an idea, a sentence or a folder of notes to a
  first working version.
- [Bring in an existing project](scenarios/existing-project.md): adopt or attach a repository, capture
  its structure, and choose
  [how much of Rihmasto's structure to enforce](scenarios/existing-project.md#how-much-structure-to-take-on).
- [Improve and maintain](scenarios/improve-and-maintain.md): the weekly rhythm, one change loop.
- [Fix a project that lacks governance](scenarios/fix-ungoverned-project.md): capture, measure, write
  down, put agents under the contract, gate, trace.
- [Build workflows and automations](scenarios/workflows-and-automations.md): automations around your
  projects, and a workflow as the product.

The guides by topic, for each scenario:

**Start fresh from an idea.** [Shape it in chat](guides/shape-in-chat.md), then
[inputs](guides/inputs.md) and [how it works](how-it-works.md) for the questions, spec, contract,
build and gate, at explore maturity on the local preview; [postures](guides/postures.md) to choose how
strict; [deploying on paved roads](guides/deploying.md) for demo, pilot and production once IT has
configured a road (only the local preview has run for real; see [paved roads](paved-roads.md)).

**Integrate into an existing project.** [Existing solutions](brownfield.md) to scan, adopt and
assess; [alignment](guides/alignment.md); [your IDE and Rihmasto](guides/ide-and-rihmasto.md);
[checks](guides/console-and-checks.md) and [automations](guides/automations.md) to watch it. No paved
road delivers an adopted repository yet.

**Conceptualise.** [Shape it in chat](guides/shape-in-chat.md) or a folder of documents through
[inputs](guides/inputs.md); then either socratic mode to think it through
([how it works](how-it-works.md#1-intake)) or the prototype posture at explore for a quick mock-up
([postures](guides/postures.md)); [signals and concepts](guides/signals-and-concepts.md) for validating
a concept on the delivery square; [change anything](guides/change-anything.md) to firm it up later.

**Keep something running.** [Checks](guides/console-and-checks.md), probes and incidents in
[how it works](how-it-works.md#8-operation), [automations](guides/automations.md),
[Review](guides/review.md) each morning, and [Insights](guides/insights.md).

**Work from your IDE or terminal.** [Your IDE and Rihmasto](guides/ide-and-rihmasto.md),
[MCP](mcp.md), [hand-offs and the agent channel](guides/agentic-help.md),
[the console and a terminal](guides/console-and-checks.md),
[your coding agent as the model](guides/harness-models.md).

## Intake and shaping

- [Shape it in chat](guides/shape-in-chat.md): work out a need with Rihma in conversation, from
  nothing, a sentence or a file, with a draft brief you edit, then create the project from it.
- [Inputs: any input, from any author](guides/inputs.md): how a need, a specification, a plan or a
  folder is read, what is never asked again, how the gaps are asked, and the intake summary.
- [The autonomy ladder](guides/autonomy.md): how far the factory may go on its own, and who sets
  the cap.
- [Autopilot, delegation and staying on track](guides/autopilot-and-tracking.md): let Rihmasto run
  on its own in a sandbox, or keep a tight hold with checkpoints, and see whether a project stays on
  track against its approved plan.
- [Automations](guides/automations.md): a trigger, a guard, an action and a scope, per project or
  across them, run with their owner's rights; the templates, and the lines that run them from cron or
  Windows Task Scheduler; suggested from a project's shape, or described in your own words.
- [Set up a project, archive it, remove it](guides/project-setup.md): the checklist of everything that
  applies to a project with one click each, archiving duplicates, and how every click is also a request
  in Ask Rihma.
- [Postures and priority weights](guides/postures.md): prototype, balanced, production or
  regulated, tuned by weights; what each does, previewed before you choose, and changing it during
  the run.
- [Work profiles](guides/profiles.md): the kinds of work, and what each one asks.
- [Insights](guides/insights.md): health, compliance, governance, security, context drift, QA and
  token, skill and memory usage, per project and factory-wide, counted from the records; what is not
  measured and how to measure it; exporting to your own observability stack (JSON, CSV, OpenTelemetry).
- [The Knowledge graph view](guides/knowledge-graph.md): each project, or all of them, as a graph of its
  records (requirements, criteria, tests, tasks, decisions, changes, releases, agent runs), filtered and
  focused, with what is missing highlighted, a table on a phone, saved views, and Ask Rihma's Take me there.
- [Change anything, go back a step, never get stuck](guides/change-anything.md): change a project's
  kind of work, mode, maturity or title with a preview of what it means, send it back to its material,
  questions, spec or plan, add material later, and see what it waits for.
- [Self-healing: incidents, remedies, what Rihmasto learned](guides/self-healing.md): every error, failed
  job, broken view or refused step becomes an incident with what happened in plain words, the remedies Rihmasto
  knows (learned ones first), Investigate with Rihma, a fix through the gate sent as a pull request on your
  approval, and feedback that changes wording, rules and prompts.
- [Share your view: observer links](guides/observer-links.md): a time-limited, read-only link for a colleague
  to watch your work or define a project together; following, guest comments and suggestions, revoke at once.
- [Never lost: why it is empty, who acted, what blocks work](guides/never-lost.md): Why? Ask Rihma on every
  empty, unmeasured or failed thing, who acted on every answer and run, Harness and enforcement, and decision
  triage with assumption weights.
- [Start here, tasks you open, and the whole log of a run](guides/start-here.md): what Rihmasto understood a
  project to be and the one to three things to do there now, each task's panel with its criteria, tests, commits
  and history, and every run's log followed live.
- [Enforcement levels: how strict each stage is](guides/enforcement-levels.md): off, advise, require review or
  enforce per environment (development, testing, production) and check family, for all projects in Settings and
  per project in its Enforcement view, the project's own GitHub pipeline read beside them, a preview before a
  change, and the same by chat ([D-0026](../decisions/D-0026-enforcement-levels.md)).
- [Machines, asks between agents, and Test connection](guides/machines-and-asks.md): the computers your agents and
  working copies are on, a question put to the agent on another machine and its answer back in the agent channel
  (over MCP, a one-use reply link, or copy and paste), and why something is not reachable with the fix for its system.
- [Teams, Rihmasto's words and what applies where](guides/teams-and-words.md): a project in one team (a team of one
  made for a person working alone), the words a team or a project gives Rihmasto's own terms, read at read time and
  never rewriting a record, each change previewed, signed and undone, and every setting's scope and value source
  ([D-0027](../decisions/D-0027-teams-and-semantics.md)).
- [People in the loop, and reviewers outside the system](guides/people-in-the-loop.md): questions, decisions and
  feedback put to a persona or a named person, each check family advised or required before delivery, a one-use
  link for a reviewer outside Rihmasto, sending by Teams, Slack, email or WhatsApp, and nudges that escalate.
- [Agentic help: goals, hand-offs and the agent channel](guides/agentic-help.md): ask Rihma for a goal
  ("hook this to Google Drive") and get a plan you take one click at a time; hand a project off to
  Claude Code, Codex, OpenCode or Cursor; what agents read and write back; and the agent channel where
  people, Rihma's agents and coding agents talk, traced and watched.
- [Context and data](guides/context-and-data.md): what Rihmasto knows about a project and where it came
  from, what each of its agents is given right now (every part, its size, what was compressed or left out and
  why), the compression audit, and the factory's stores, ledger integrity, retention and a signed clean-up.
- [Outputs](guides/outputs.md): what each audience receives (a web app with sign-in, a container,
  an API description, a delivery report, an evidence pack, the source), chosen by a person and built
  from the records.
- [The capability layer](capability-layer.md): what Rihmasto delivers, besides software, and who
  sees what.
- [The whole delivery](factory-overview.md) (*design*): the seven stages, the delivery square and
  the canon, from a business need to measured benefit.

## Existing projects

- [Existing solutions, your own terminal, security findings](brownfield.md): adopting a folder or a git
  address, the assessment, workspaces for your own agent, SARIF findings, and what is not built yet
  (no paved road delivers an adopted repository).
- [Assessing an existing system, and watching it run](guides/assessment.md): the assessment's rules and
  panel, and the live progress every long job shows (each area as it runs, its findings as they land, an
  honest estimate, Cancel, and "how is the assessment going?" in Ask Rihma).
- [The console, a terminal, and checks](guides/console-and-checks.md): where the line is between your
  IDE, Rihmasto's console and a real terminal; running a project's commands or Gnomon in its workspace,
  recorded; opening a terminal there; and checks with a Health view for keeping a project healthy.
- [Audits and evals](guides/audits-and-evals.md): Gnomon's capability-based audits, benchmarks and evals
  (security posture, attack corpus, compliance mapping, data flow, agent metrics, audit trails, change check,
  eval, chaos, doctor, claim check, context cost, degradation) on a project's repository, what each measures
  and costs, as checks, in Insights and Review; and Rihma's own evals per role, comparing models.
- [Alignment: your repository's own specs and tests](guides/alignment.md): the specs, criteria, tests,
  tasks, ADRs and API contracts a team keeps in its repository (spec-kit, Kiro, BMAD, Gherkin, OpenAPI and
  more), proposed for the project's contract and accepted, edited or rejected, the gaps, suggested changes
  for the repository, the drift after it changes, and continuing in your IDE.
- [A project's own sources](guides/own-sources.md): where an adopted project keeps its own requirements,
  tests, test results, findings and tasks (rule files, an issues log, a round's README, each package's test
  root, a gate run on another machine), found by rule, mapped, read as the truth with path and line, plans
  that may be old left out, its own tests run or their results imported, and the trace.
- [Your IDE and Rihmasto](guides/ide-and-rihmasto.md): where the line is between the IDE and
  terminal (the inner loop) and Rihmasto (the outer loop); how Rihmasto reads a project's CLAUDE.md,
  AGENTS.md, Cursor rules, skills and MCP servers and follows them; MCP configuration for Claude Code,
  Cursor and Codex, and `rihmasto ide`.

## Build and verify

- [How it works](how-it-works.md): the panel, the spec, the hashed contract, the builder cells, the
  gate and the holdouts.
- [Agent observability](guides/agent-observability.md): an opt-in module and a per-project Agent
  sessions view for developers and IT: what the IDE agents (Claude Code, Cursor, OpenCode) did in the
  repository, read from your own agent observability hub; metadata only.
- [Gnomon posture](guides/gnomon-posture.md): how well Gnomon governs each project and what to tighten first,
  computed from its own Gnomon files; its suggestions become change cards you decide, never changes.
- [Agent operations](guides/agent-operations.md): the AI architect's view across projects and per
  project: what each agent role costs, how fast it answers and what it is given, the Optimise audit, and agent
  skills platform-wide and per project.
- [Development board and trace](guides/development-board.md): each project's work as lanes, the
  developer briefing with the next step, the trace of every person and agent, and session hooks for
  Claude Code and Cursor.
- [MCP](mcp.md): the MCP server for your own coding agent, with its tools, resources and safety
  boundary.
- [Small capabilities](guides/small-capabilities.md): an automation, a single workflow or one agentic
  capability, from a two-sentence need to a running capability reached over MCP, an OpenAI-compatible
  endpoint, a website chat or HTTP, behind its pack guard.
- [The cockpit](cockpit.md): every view, the lenses, the assistant and the JSON API.
- [Running fully local](guides/local-models.md): every role on your own hardware.
- [Recipes, sandbox trials, measured fit and offline bundles](guides/recipes-and-fit.md): reuse of
  proven capabilities, from Python.
- [Spec to verify](spec-to-verify.md) (*design*): how a requirement becomes something Gnomon
  enforces.
- [The v1 chain](v1-design.md) (*design*): the end-to-end chain as it was designed for v1.
- [Harnesses](guides/harnesses.md): who runs the cells. Gnomon by default (in-run policy enforced), or
  Claude Code, Codex, OpenCode or a command you name, approved by IT with its version pinned and
  checked after every run; the docker sandbox; adding a command runner.
- [Models setup](guides/models-setup.md): which model answers for each role (a local server or a
  hosted OpenAI-compatible provider), its key, and a Test, from the cockpit or `rihmasto models`.
- [Run Rihmasto with the coding agent you already have](guides/harness-models.md): no API key? Claude
  Code (your login), Codex or OpenCode answers the text roles (`rihmasto models use claude-code`), run
  headless with no tools, each call recorded as run by it.
- [A harness provider for Gnomon](upstream/gnomon-harness-provider.md) (*proposal*): how Gnomon itself
  could spawn a coding agent for a role and keep it in its own audit trail.
- [Access](guides/access.md): who may decide as which persona. Single-operator and enforced modes,
  the access file, and setting up an identity-aware proxy (oauth2-proxy with Entra ID, Okta, Google
  or Keycloak; Google IAP; an AWS load balancer) whose signed token the cockpit verifies, and the
  isolation runner untrusted code runs through.
- [Deploying on paved roads](guides/deploying.md): the short version of how a product lands.
- [Destinations](guides/destinations.md): every place a capability goes (where it runs, the data it
  reaches, the channels it is used through, where it is published), publishing to a registry test first
  and production through IT's gate, and the feedback a failing destination brings back.
- [Integrations and data](guides/integrations-and-data.md): IT's view of every connection (model
  endpoints, relay channels, webhooks, connectors, registries, roads and a project's data integrations),
  where each is, its health, credentials by name, what each agent may reach, the data-flow diagram, and
  Check now, Turn off and rotation reminders.
- [IT checks](guides/it-checks.md): what IT checks per project and solution type (app, certificates,
  names, database, integrations, jobs, models, agents), why each check is there and whether its rule is the
  platform's or the project's, running any assessment on request or on a schedule, the eval sets, and the
  incident a failing check opens.
- [Google Cloud and Google Drive](guides/gcp.md): a Cloud Run service or a scheduled Cloud Run job on
  IT's Google Cloud road, and a capability that reads new recordings from a Drive folder and writes
  transcripts back, with where the audio goes.
- [Outputs](guides/outputs.md): what each audience receives (a web app with sign-in, a container,
  an API description, a delivery report, an evidence pack, the source), chosen by a person and built
  from the records.
- [The capability gateway](guides/gateway.md): one OpenAI-compatible endpoint for a site's
  workloads, with fallbacks, quotas and an audit.
- [Data integrations](guides/data-integrations.md): how a capability reaches a database, a data
  warehouse, cloud storage or an ERP, who approves each binding, and where credentials live (connectors
  tested against local fakes; no road calls them yet).
- [Events, doorbells and connectors](guides/integrations.md): signed events and Teams, Slack and email
  notices out (tested against local receivers), verified webhooks in, and the connector model, as far
  as they are built.
- [Embeds](guides/embeds.md): a website chat that files feedback or a need, and how it is
  protected.
- [Integrations](integrations.md) (*design*): connecting other systems through Gnomon as governed
  tool calls.
- [Portability](portability.md) (*design, phase 1 built*): running a release anywhere, with its pins
  and evidence.

## Automate and keep healthy

- [Automations](guides/automations.md): a trigger, a guard, an action and a scope, per project or
  across them, run with their owner's rights; the templates, and the lines that run them from cron or
  Windows Task Scheduler.
- [The console, a terminal, and checks](guides/console-and-checks.md): where the line is between your
  IDE, Rihmasto's console and a real terminal; running a project's commands or Gnomon in its workspace,
  recorded; opening a terminal there; and checks with a Health view for keeping a project healthy.
- [Autopilot, delegation and staying on track](guides/autopilot-and-tracking.md): let Rihmasto run
  on its own in a sandbox, or keep a tight hold with checkpoints, and see whether a project stays on
  track against its approved plan.
- [The autonomy ladder](guides/autonomy.md): how far Rihmasto may go on its own, and who sets the cap.

## Agents

- [The cockpit](cockpit.md): every view, the lenses, Ask Rihma and the JSON API.
- [Walkthroughs in Ask Rihma](guides/walkthroughs.md): step-by-step help in the chat for each move.
- [Agentic help: goals, hand-offs and the agent channel](guides/agentic-help.md): ask Rihma for a goal
  ("hook this to Google Drive") and get a plan you take one click at a time; hand a project off to
  Claude Code, Codex, OpenCode or Cursor; what agents read and write back; and the agent channel where
  people, Rihma's agents and coding agents talk, traced and watched.
- [MCP](mcp.md): the MCP server for your own coding agent, with its tools, resources and safety
  boundary.

## See and govern

- [Review what agents shipped](guides/review.md): since you last looked, grouped by what needs you
  (waiting on you, went wrong, decided for you, shipped, from your IDE, cost), acted on in place, marked
  reviewed, and sent to you every morning.
- [Insights](guides/insights.md): health, compliance, governance, security, context drift, QA and
  token, skill and memory usage, per project and across them, counted from the records; what is not
  measured and how to measure it; exporting to your own observability stack (JSON, CSV, OpenTelemetry).
- [Knowledge graphs and ontologies](knowledge-graph.md) (*phase 1 built*): the read model over
  Rihmasto's own records, and the read-only `rihmasto graph` command.
- [Capability packs and evidence packs](guides/packs-and-evidence.md): what a release is, what a pack
  says it lacks (no SBOM, not signed), and the bundle a reviewer checks, whose verdict is *attestable*,
  *chain broken* or *insufficient evidence*, never "compliant".
- [The capability layer](capability-layer.md): what Rihmasto delivers besides software, and who sees
  what.
- [Access](guides/access.md): who may decide as which persona. Single-operator and enforced modes,
  IT's access file, setting up an identity-aware proxy that IT runs (oauth2-proxy with Entra ID, Okta,
  Google or Keycloak; Google IAP; an AWS load balancer) whose signed token the cockpit verifies (tested
  with test keys, not yet a real identity provider), and the isolation runner untrusted code runs
  through.
- [Security findings from any scanner](brownfield.md#security-findings-from-any-scanner): the
  security gate and accepted risks.
- [The whole delivery](factory-overview.md) (*design*): the seven stages, the delivery square and
  the canon, from a business need to measured benefit.
- [Decisions](../decisions/): every decision, who made it and why.

## Background and research

- [Knowledge graphs and ontologies](knowledge-graph.md) (*phase 1 built*): a read model over Rihmasto's
  own records, and the read-only `rihmasto graph` command; the cockpit's view of it is
  [the Knowledge graph view](guides/knowledge-graph.md).
- [Ideas for the road ahead](roadmap-ideas.md): ideas from research, and which are done.
- [Gnomon upstream issues](../upstream/gnomon-issues.md): what Rihmasto asked of Gnomon.
- [The first working spec](../specs/001-initial/spec.md): an early draft of Rihmasto's own spec,
  kept as history; the contract is the current one.

## The project

- [Contributing](../CONTRIBUTING.md), [code of conduct](../CODE_OF_CONDUCT.md),
  [governance](../GOVERNANCE.md) and [security](../SECURITY.md).
- [The changelog](../CHANGELOG.md): what changed in each release.
- [Maintainers: releases and the two-way sync](maintainers.md): how a snapshot of the maintainers'
  development repository reaches `main`, and how merged contributions are brought back.
- [Licence](../LICENSE) (Apache-2.0) and [notice](../NOTICE).
- [The contract](../contract/contract.json): Rihmasto's own requirements, criteria and tasks.
- [Decisions](../decisions/), [amendments](../decisions/amendments/) and
  [proposals](../decisions/proposed/).
- [Code quality](code-quality.md): the quality gate, its numbers, and what to fix.
- [Rihmasto against Gnomon v0.6.6](gnomon-0.6.6-audit.md): what changed in Gnomon 0.6.6 and how
  Rihmasto follows it.
- [Security: Rihmasto checks what it builds](guides/security.md): its own static scan, dynamic
  probes and agentic red team, the scope a person authorises, and what they do not catch.
