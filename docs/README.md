# Rihmasto documentation

Every guide and reference page that ships with Rihmasto, grouped by who reads it. A page can sit
in more than one group. Pages marked *design* describe something planned; they say inside what is
built and what is not.

## Start here

- [The README](../README.md): what Rihmasto is, the quick start, and the project's status.
- [Getting started](getting-started.md): install, the demo, models and Gnomon, a first real
  project, the cockpit, where things are kept.
- [The demo](demo.md): what the demo factory holds, and what each persona sees in it.
- [How it works](how-it-works.md): the chain step by step, the delivery square, personas and
  lenses, and what Gnomon does beside the kernel.
- [The acceptance matrix](acceptance.md): every use case and mode, measured, and the live acid test.
- [Walkthroughs in Ask Rihma](guides/walkthroughs.md): Rihma walks you through plugging in an existing
  project, starting from an idea or documents, setting up a model, or a tour, step by step in the chat.
- [Review what agents shipped](guides/review.md): since you last looked, grouped by what needs you
  (waiting on you, went wrong, decided for you, shipped, from your IDE, cost), acted on in place, marked
  reviewed, and sent to you every morning.
- [Use only what you need](guides/use-only-what-you-need.md): the modules and the presets (spec only,
  gate my code, assess, security or evidence only, a capability, the full factory), and changing them.

## Business owners and product owners

- [Signals, concepts and updates](guides/signals-and-concepts.md): how needs and outside events
  arrive, and how a person decides what becomes work.
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
  Windows Task Scheduler.
- [Postures and priority weights](guides/postures.md): prototype, balanced, production or
  regulated, tuned by weights; what each does, previewed before you choose, and changing it during
  the run.
- [Work profiles](guides/profiles.md): the kinds of work, and what each one asks.
- [Insights](guides/insights.md): health, compliance, governance, security, context drift, QA and
  token, skill and memory usage, per project and factory-wide, counted from the records; what is not
  measured and how to measure it; exporting to your own observability stack (JSON, CSV, OpenTelemetry).
- [Change anything, go back a step, never get stuck](guides/change-anything.md): change a project's
  kind of work, mode, maturity or title with a preview of what it means, send it back to its material,
  questions, spec or plan, add material later, and see what it waits for.
- [Agentic help: goals, hand-offs and the agent channel](guides/agentic-help.md): ask Rihma for a goal
  ("hook this to Google Drive") and get a plan you take one click at a time; hand a project off to
  Claude Code, Codex, OpenCode or Cursor; what agents read and write back; and the agent channel where
  people, Rihma's agents and coding agents talk, traced and watched.
- [Outputs](guides/outputs.md): what each audience receives (a web app with sign-in, a container,
  an API description, a delivery report, an evidence pack, the source), chosen by a person and built
  from the records.
- [The capability layer](capability-layer.md): what Rihmasto delivers, besides software, and who
  sees what.
- [The whole delivery](factory-overview.md) (*design*): the seven stages, the delivery square and
  the canon, from a business need to measured benefit.

## Developers

- [Existing solutions, your own terminal, security findings](brownfield.md): adopting a
  repository, workspaces for your own agent, and SARIF findings.
- [The console, a terminal, and checks](guides/console-and-checks.md): where the line is between your
  IDE, Rihmasto's console and a real terminal; running a project's commands or Gnomon in its workspace,
  recorded; opening a terminal there; and checks with a Health view for keeping a project healthy.
- [Alignment: your repository's own specs and tests](guides/alignment.md): the specs, criteria, tests,
  tasks, ADRs and API contracts a team keeps in its repository (spec-kit, Kiro, BMAD, Gherkin, OpenAPI and
  more), proposed for the project's contract and accepted, edited or rejected, the gaps, suggested changes
  for the repository, the drift after it changes, and continuing in your IDE.
- [Security: Rihmasto checks what it builds](guides/security.md): its own static scan, dynamic
  probes and agentic red team, the scope a person authorises, and what they do not catch.
- [Your IDE and Rihmasto](guides/ide-and-rihmasto.md): where the line is between the IDE and
  terminal (the inner loop) and Rihmasto (the outer loop); how Rihmasto reads a project's CLAUDE.md,
  AGENTS.md, Cursor rules, skills and MCP servers and follows them; MCP configuration for Claude Code,
  Cursor and Codex, and `rihmasto ide`.
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
- [Code quality](code-quality.md): the quality gate, its numbers, and what to fix.
- [Rihmasto against Gnomon v0.6.6](gnomon-0.6.6-audit.md): what changed in Gnomon 0.6.6 and how
  Rihmasto follows it.
- [Contributing](../CONTRIBUTING.md): set up, run the checks, and the spec-first way of working.

## IT and operations

- [Models setup](guides/models-setup.md): which model answers for each role (a local server or a
  hosted OpenAI-compatible provider), its key, and a Test, from the cockpit or `rihmasto models`.
- [Run Rihmasto with the coding agent you already have](guides/harness-models.md): no API key? Claude
  Code (your login), Codex or OpenCode answers the text roles (`rihmasto models use claude-code`), run
  headless with no tools, each call recorded as run by it.
- [A harness provider for Gnomon](upstream/gnomon-harness-provider.md) (*proposal*): how Gnomon itself
  could spawn a coding agent for a role and keep it in its own audit trail.
- [Harnesses](guides/harnesses.md): who runs the factory's cells. Gnomon by default (in-run policy
  enforced), or Claude Code, Codex, OpenCode or a command you name, approved by IT with its version
  pinned and checked after every run; the docker sandbox; adding a command runner.
- [Access](guides/access.md): who may decide as which persona. Single-operator and enforced modes,
  the access file, and setting up an identity-aware proxy (oauth2-proxy with Entra ID, Okta, Google
  or Keycloak; Google IAP; an AWS load balancer) whose signed token the cockpit verifies, and the
  isolation runner untrusted code runs through.
- [Deploying on paved roads](guides/deploying.md): the short version of how a product lands.
- [Google Cloud and Google Drive](guides/gcp.md): a Cloud Run service or a scheduled Cloud Run job on
  IT's Google Cloud road, and a capability that reads new recordings from a Drive folder and writes
  transcripts back, with where the audio goes.
- [Paved roads](paved-roads.md): the full reference: configuring a road, what each maturity does,
  and what is real and what is not.
- [The capability gateway](guides/gateway.md): one OpenAI-compatible endpoint for a site's
  workloads, with fallbacks, quotas and an audit.
- [Embeds](guides/embeds.md): a website chat that files feedback or a need, and how it is
  protected.
- [Integrations](integrations.md) (*design*): connecting other systems through Gnomon as governed
  tool calls.
- [Events, doorbells and connectors](guides/integrations.md): signed events and notices out,
  verified webhooks in, and the connector model, as far as they are built.
- [Data integrations](guides/data-integrations.md): how a capability reaches a database, a data
  warehouse, cloud storage or an ERP, who approves each binding, and where credentials live.
- [Portability](portability.md) (*design, phase 1 built*): running a release anywhere, with its pins
  and evidence.
- [Security](../SECURITY.md): how to report a vulnerability, and the threat model in short.

## Compliance

- [Capability packs and evidence packs](guides/packs-and-evidence.md): what a release is, and the
  bundle a reviewer checks.
- [The autonomy ladder](guides/autonomy.md): the cap, who may set it, and how it is recorded.
- [Access](guides/access.md): how a decision is bound to a verified identity, and how each change
  to who may decide is recorded.
- [Security findings from any scanner](brownfield.md#security-findings-from-any-scanner): the
  security gate and accepted risks.
- [Decisions](../decisions/): every decision, who made it and why.

## Background and research

- [Knowledge graphs and ontologies](knowledge-graph.md) (*phase 1 built*): a read model over Rihmasto's
  own records, and the read-only `rihmasto graph` command.
- [Ideas for the road ahead](roadmap-ideas.md): ideas from research, and which are done.
- [Gnomon upstream issues](../upstream/gnomon-issues.md): what Rihmasto asked of Gnomon.
- [The first working spec](../specs/001-initial/spec.md): an early draft of the factory's own
  spec, kept as history; the contract is the current one.

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
