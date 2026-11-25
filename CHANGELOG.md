# Changelog

Every notable change to Rihmasto is recorded here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[PEP 440](https://peps.python.org/pep-0440/): `1.0.0.dev0` is a development release before 1.0.0.

## [Unreleased]

### Added

- **The round-two features wired together**: an automation can run a check (`run_check`, registered when the
  automations load) and re-read a repository for alignment (`align_scan`), with the templates **Notify when a
  check fails** (FR-CHK1-AC-10) and **Re-read the repository for alignment when it changes** (FR-ALN1-AC-10);
  the section for the IDE agent carries the accepted alignment and its open gaps (FR-ALN1-AC-9); Insights
  measures the checks from their `check_ran` results and the repository drift from `alignment_scanned`,
  `alignment_accepted` and `alignment_rejected` (FR-INS1-AC-8); every role's model run (analyst, holdout author,
  verifier, assistant) is recorded in the project's ledger as `model_run` with its role, model, endpoint,
  tokens, priced cost and duration, never the prompt (`kernel/model_usage.py`), and a refused step above the
  autonomy cap as `autonomy_capped`, which Governance counts (FR-INS1-AC-9); Health and Insights sit in the
  sidebar once each and Home says a failing check once (FR-INS1-AC-10); Plug in an existing project offers Open
  Alignment and the AI tools card once adopted (FR-WLK1-AC-10); the distribution lists every package directory
  (FR-REL1-AC-5).
- **The Review, the Google Cloud road and the agent bridge wired into the merged streams**: the Review reads the
  record kinds the streams really write (failed automation runs, checks and console commands, refused runners,
  paused automations; FR-REV1-AC-8) and fills **From agents** from the agent channel (FR-REV1-AC-9); its
  **Morning review digest** runs as an automation too (FR-REV1-AC-10); a Cloud Run job fires the life-cycle
  events like any road, has a **Scheduled job executions** check, and its failed execution shows in the Review
  and in Insights' health (FR-GCP1-AC-8); goal help plans a Google Drive goal with the Drive integration and the
  Google Cloud road (FR-CPL1-AC-6); Insights counts agents' proposals and Rihma's channel answers
  (FR-INS1-AC-11); the hand-off's "Run it with" names the project's builder runner.
- **The coding agent you already have, wired in** (FR-HMD1-AC-9): the agent channel's Rihma answers and goal help
  go through the same guard as every model call, so a harness-backed role answers there too, each run recorded
  once as `model_run` in the project's ledger with its harness and task; Insights' usage shows the harness as the
  runner; goal help offers "Use the coding agent you already have" when no model answers.
- **Run Rihmasto with the coding agent you already have** (FR-HMD1): with no API key, Claude Code (your
  login), Codex or OpenCode can answer the text roles: the analyst (intake, the spec, Shape it in chat),
  the holdout author, the verifier and the assistant. Each one runs headless as a text completion with no
  tools, in an empty folder, never given the repository, the contract or the holdouts. The verifier is
  given the change's diff in its task. `rihmasto models use claude-code [--roles ...]` (signed and
  recorded), **Use Claude Code / Use Codex / Use OpenCode** in Models setup, and Home's "No API key?
  Claude Code found: use it" set it up. Models setup lists the harnesses on this machine with their
  versions, Test sends its tiny prompt through the harness, and `rihmasto doctor` suggests the one it
  finds. Each call is a `model_run` in the ledger with the harness, its version, the model, tokens and
  cost, and the honest assurance "not through Gnomon's lane: no Gnomon audit trail for this call". The
  verifier stays another model family than the builder, and a confidential project refuses a hosted
  harness (an OpenCode on a local model can be declared private). It is slower than an API endpoint and
  spends your subscription: the pages say so. The builder's harness stays a cell runner. A proposal for
  Gnomon to run and record such calls itself is in `docs/upstream/gnomon-harness-provider.md`.
- **Real projects of every shape** (FR-RPJ1), after the owner's five real projects were fed in through New
  project: housekeeping files (ignore lists, editor settings, checksums, `.env.example`, lockfiles) are
  listed, never read, and the root README is read first and in full; a `.zip` is read inside, never
  extracted, size-capped, zip bombs refused; a copy's text is read once; a git repository is scanned as its
  last commit, with "N uncommitted changes (and M untracked files) are not in the last commit" and **Adopt
  the working copy as it is now** (`--working-copy`); a folder adopted already says so, with **Open** and
  **Adopt it again as a new project**; a workspace of several repositories lists them, **Adopt each as its
  own project** or **the folder as one**; a long scan shows its progress with **Cancel**, and a refusal says
  what to do (**Allow C:\dev**, or "Ask IT to allow it"); **Settings > Folders the cockpit may read**
  allows a folder without a restart; a confidential adoption says "Adopting works (it calls no model)" with
  **Use my local model for these roles**; a folder of documents only offers **Track and evaluate this
  work** (`--documents`). Five new work profiles (game, ML experiment or model, knowledge or tooling,
  library or CLI, data pipeline), with their gates and recognised from files too; **Kind: not chosen yet**
  in the header. An adopted project shows its real state instead of the seven stages, its maturity is
  asked ("How is it used today"), a failed baseline is a health item, a stated test command runs as the
  baseline after a yes (`rihmasto baseline`), **Set up the watch** watches it through the automations, and
  its **Areas** (inventory and activity by area, design and lore documents) are a card, served to Insights
  and answered by Ask Rihma.

- **The owner's decisions of 2026-11-24** ("1. Yes 2. Skip 3. Agreed 4. Ask"), after a journey test walked
  their real flows:
  - **A new kind keeps only what a person chose** (FR-CHG1-AC-11): changing a project's kind of work and
    going back to the questions withdraws the assumptions the factory made on its own, "made for the old
    kind", and keeps the answers and assumptions a person chose; the settings preview counts what is kept
    and withdrawn, and the panel that runs again is told only the person-settled ones.
  - **Confidential work skips a hosted fallback** (FR-MAT1-AC-10): a role whose primary endpoint is local
    but whose fallback is hosted is no longer refused; the lanes a confidential project's calls run in are
    compiled without the hosted fallback, so Gnomon cannot reach it, and `confidential_fallback_skipped`
    records the skip once per run. A hosted primary is still refused.
  - **Look at the spec before building** (FR-CHG1-AC-12, AC-13): at explore and demo a project a person
    makes waits once, before its first build, for Go or Skip on its spec, in What's next and the Inbox;
    **Build without waiting for me** in New project and Project settings (`--build-without-waiting`) turns
    it off; a delegation may say Go (`go_ahead`, rule `go`); pilot and up keep the plan's approval; the
    scripted demo sets it off.
  - **Adopting asks the kind when it is not clear** (FR-X1-AC-4): an adopted project whose kind is not
    clear from its title, README and files gets the "Which kind of work is this?" question card with the
    candidate kinds, instead of a web app; one clear candidate is taken and said with why.
- **Models setup sees a key Gnomon holds** (FR-MDL1-AC-10): an endpoint whose key Gnomon keeps (`gnomon
  key set`) reads "key set by Gnomon", by `gnomon key list` (names only), not "no key"; when Gnomon cannot
  say but its credential store exists, "Gnomon may have its own key for this host". Rihmasto never opens
  the store. `rihmasto doctor` counts such a key as set.
- **Other harnesses as cell runners** (D-0019, FR-HRN1): the builder and the verifier can run with
  Claude Code, Codex, OpenCode or any command a team names instead of Gnomon, per role, for the
  factory or one project. Gnomon stays the default and the reference. Another runner is chosen on a
  **Cell runner** card only IT decides, with the version found on the machine pinned; a run with
  another version, a runner not found, or the docker sandbox where Docker does not answer does not
  happen (`runner_refused`). Each harness gets the task's envelope, its write scope and protected
  paths and the project's own conventions (AGENTS.md, CLAUDE.md, rules files), never the holdouts.
  After its run the gate checks the write scope and the holdout custody beside the suite, the trace,
  fail-first and the independent verifier (another model family, whichever runner); a change that
  fails any of them never merges. The optional docker sandbox mounts only the working copy, with no
  network but a proxy to the model endpoint. Every round's record, the ledger (`runner_ran`) and the
  evidence pack (`cell-runners.json`) name the runner, its version and its assurance: "in-run policy
  enforced by Gnomon" or "checked after the run", never the one shown as the other. Settings >
  Runners, a runner line in Project settings, and `rihmasto runners list|check|set`
  ([guide](docs/guides/harnesses.md)).
- **Your IDE and Rihmasto** (FR-AGC1): a project's AI tool configuration is recognised by rule and
  followed. The scan reads `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules`, Cursor rules (with
  their description, globs and alwaysApply), Copilot, Windsurf and Cline instructions right after
  the README, then Claude skills (with their bundled files listed), subagents and slash commands;
  hooks, permissions and MCP servers by name only; personal settings never. Nothing found is run.
  The material map shows them as **How AI tools here are set up**. Intake's and the assessment's
  panels are told the conventions; adoption's baseline runs the test command they state (shell
  syntax never); a builder cell on an adopted project gets the instructions that apply to the files
  it may write. An adopted or attached project's Overview shows **AI tools in this project** and
  **Work on it from your IDE** (MCP configuration for Claude Code, Cursor and Codex, how a change
  comes back, and a section to paste into your own AGENTS.md); `rihmasto ide <pid>` prints the same
  and writes nothing ([guide](docs/guides/ide-and-rihmasto.md)).
- **Automations** (FR-AUT1): a trigger (a schedule, a ledger event, an inbound webhook ringing, or new
  commits on an attached or adopted repository), an optional guard, an action from an allow-list
  (advance, gate, re-scan a folder, notify, open a change proposal or a signal, rebuild an output, run the
  project's own tests in a sandbox, ask a model and post a comment), a scope (one project, a list, a tag,
  a profile, a source, or the factory) and limits (runs per hour, a circuit breaker, quiet hours, a dry
  run), owned and signed by a person and run with their rights, checked again before every run. Never a
  decision. Recorded as `automation_set`, `automation_ran`, `automation_paused` and the like. The
  cockpit ticks every minute while it runs; `rihmasto automations tick` runs from cron or Windows Task
  Scheduler (`install-help` prints the line). The Automations page with scope filters, templates and a
  builder that shows the kernel's plain-language summary before saving, and an Automations tab on each
  project with its tags. Inbound sources bind to projects (`hooks add --bind`, `hooks bind`), and a relay
  subscription can be one project's own (`relay subscribe --project`)
  ([guide](docs/guides/automations.md)).
- **The four together** (FR-HRN1-AC-11 to AC-13, FR-AUT1-AC-16): a harness other than Gnomon is given
  the project's conventions recognised and matched as a Gnomon builder's envelope matches them, for
  the files its task may write (and not twice on an adopted project, whose envelope already holds
  them); a confidential project's role run by another harness on a hosted model, or outside the docker
  sandbox, is refused as a hosted role is (`confidential_refused`); a runner card waiting on IT shows
  in the project's What's next (opening Settings > Runners for it) and in the Inbox beside the trust
  and road cards, as the go-ahead card does; an automation never says Go or Skip on the look at the
  spec, nor approves or declines a runner.
- **Automations on the life-cycle steps and their transitions** (FR-AUT1-AC-17, D-0023): a concept
  validated, the spec or plan approved, the first build through the gate, a release on a test road, a
  promotion to production, a rollback and a failed check are each a clear record an event trigger names
  (`concept_validated`, `plan_approved`, `first_build_passed`, `release_reached_test`, `promoted`,
  `rolled_back`, `check_failed`); `first_build_passed` and `release_reached_test` are new records. A
  `probe` action runs the probe check where the release runs and, with `every`, keeps probing
  production. Four templates: when a release reaches test, run its checks and notify; when promoted to
  production, enable the probe check and notify; when a concept is validated, notify the product owner;
  when the gate fails twice, open a change proposal.
- **Walkthroughs in Ask Rihma** (FR-WLK1): Rihma walks a person through **Plug in an existing project**
  (the folder or git address checked and scanned in the chat, with the counts, the AI-tool setup found,
  the languages and what was skipped as secret-looking; confidential, with a hosted role named and Set
  up a model as a detour; the intent and the posture; then Adopt, with the chat waiting on the job's
  progress and showing the baseline, the kind of work and What's next), **Start from a new idea**
  (handed to Shape it in chat, or a quick start), **Start from documents**, **Set up a model** (with
  Test) and a five-stop **Get started** tour. Without a model by rule (replies read as paths, yes or no
  in English and Finnish, or the options offered as buttons); with one, a free-text reply is read into
  an option and the chat says so. Each change waits on a Confirm signed with the person's name and is
  carried out by the cockpit's own route. Kept per person under `_walkthroughs/`, resumable, one at a
  time, cancel any time; the factory's ledger records `walkthrough_started`, `walkthrough_step` and
  `walkthrough_done` with ids and step names only. Started from Home's header, the chat's header, a
  first-run card on Home, or plain words ("I have an existing project", "uusi idea"); `rihmasto
  walkthrough <name>` in a terminal; the API under `/api/walkthroughs` ([guide](docs/guides/walkthroughs.md)).
  An adoption now prints its steps as it goes (`adopt: ...` on stderr).
- **The console and Open a terminal here** (FR-CON1): each project's Console tab, and `rihmasto console
  <pid> -- <command>`, run a command in the project's workspace (an attached repository's folder, your own
  workspace, or the console's working copy, which cannot push) with the output streaming line by line, a
  time limit and Stop that end every process it started; the commands it knows are offered as buttons
  (stated ones, the test command found by rule, `package.json` scripts, Makefile targets, CI steps). The
  Gnomon box runs `gnomon task` in the workspace under its own surface. Every run is a job and
  `console_ran` in the ledger (who, persona, command line, exit, duration; never an environment value or
  the output), for developers and IT unless IT changes it, through IT's isolation runner when access is
  enforced. **Open a terminal here** and `rihmasto shell <pid>` open the operating system's terminal in
  the workspace with the routing environment, refused through a public origin
  ([guide](docs/guides/console-and-checks.md), with where the line is between your IDE, the console and a
  real terminal).
- **Checks and Health** (FR-CHK1): checks a person enables per project or across projects (the test
  suite, CI/CD status through the GitHub API or `gh`, a dependency audit with pip-audit, npm audit, cargo
  audit or osv-scanner, the secret scan, a licence check against a copyleft policy list, a CycloneDX SBOM,
  an HTTP probe with TLS expiry, the repo gate, the security gate, a custom command), each giving passed,
  failed or not measured with evidence, never not measured shown as passed; run on demand, on a schedule
  with the rights of the person who enabled it, or from an automation (`run_check`,
  `kernel/checks/automation_hook.py`); a failure logs a signal or opens a change once per change of
  verdict. The Health tab and page show each check's last result, trend and last run; What's next and
  Home say what fails. `rihmasto checks list|enable|disable|run|history|tick`.
- **Alignment with your repository's own structure** (FR-ALN1): an adopted or attached project reads the
  development structure its team keeps in the repository, by rule and running nothing: specs and user
  stories (spec-kit, Kiro, BMAD, agent-os, PRDs, RFCs), acceptance criteria (given / when / then, EARS,
  Gherkin), ADRs, API contracts (OpenAPI, AsyncAPI, GraphQL, protobuf, JSON Schema), test suites and their
  test names, task lists, CI/CD jobs, quality tools and AI tool files (`rihmasto structure <folder>`). It
  proposes requirements (keeping the repository's ids as their source), criteria, a trace from the existing
  tests with its basis and confidence, tasks, decisions, API contract references and the gaps (requirements
  with no test, tests with no requirement, untestable criteria, specs older than the code, CI that runs no
  test). A person accepts, edits or rejects each, or a group at once: accepted requirements and criteria go
  into the project's contract, customer-endorsed and noted as imported from the repository
  (`alignment_accepted`, `alignment_rejected` in the ledger). Suggested changes for the repository (criterion
  ids in test names as a patch, task list entries, a CI job that runs the tests) are copied or downloaded,
  never written there; a re-scan shows the drift; the accepted contract and the open gaps go to the IDE.
  `rihmasto align <pid>`, the cockpit's Alignment tab ([guide](docs/guides/alignment.md)).
- **Insights** (FR-INS1): health, compliance, governance, security, context drift, QA and token, skill
  and memory usage of the projects and their agentic work, per project and factory-wide, over 24 hours,
  7 days, 30 days or all records. Every figure is counted from the records (the ledgers, the canons and
  Gnomon's own audit trails in the lanes) and none is estimated; a figure with no record says "not
  measured", why and how to measure it, never zero. Tokens and cost per project, task, role, model,
  endpoint, runner and local or hosted; tool calls by tool; skills used and compactions; gate pass rate,
  rounds per task, fail-first and verifier disagreements; decisions by person, delegation or automation,
  time to decide and verified ledgers; findings, secrets and the red team; spec age, untested
  requirements, contradictions and context trims. Each tile and chart has a one-line insight computed by
  rule. The cockpit's **Insights** page (sidebar) and each project's Insights tab, with a table view of
  every chart; any tile can be pinned to Home as an *Insight* widget. `rihmasto insights` and
  `rihmasto insights export --format json|csv|otlp-json` (OpenTelemetry GenAI conventions for model
  runs), which writes a file or prints and sends nothing anywhere (D-0017)
  ([guide](docs/guides/insights.md)). The sidebar's former "Insight" page is now named Floor.
- **Review what agents shipped: since you last looked** (FR-REV1): one place to review what agents and
  automations did while you were away, across your projects or one project, from the records alone:
  waiting on you (cards your persona may decide, with their age), went wrong (gate failures, escalations,
  failed releases, jobs and checks, refusals, automations paused by their breaker), decided for you
  (decisions a delegation or an autopilot made in your name, and the factory's assumptions with due
  dates), shipped (merged tasks with the gate's verdict, rounds and diff stats; releases to test and
  production; outputs), from your IDE (commits gated on attached repositories) and the period's cost by
  project and role. Every item links to its record and says who or what did it. Approve, decline,
  overturn, stop a delegation or report a change in place through the existing signed routes; mark a
  change reviewed (`review_marked`) and the whole review done (`review_done`, your next review starts
  there). The cockpit's **Review** page (first in the sidebar, Home's first card, a tab per project) is
  keyboard first and works on a phone; a **morning digest** goes to your Teams, Slack or mail receiver at
  the time you set, held back when nothing happened; `rihmasto review`, `review mark`, `review done` and
  `review digest` ([guide](docs/guides/review.md)).

- **A Google Cloud road and a Google Drive connector** (FR-GCP1, FR-GDR1): IT configures a `gcp-cloudrun`
  paved road (projects per environment, a region, an Artifact Registry repository, the identity Rihmasto
  deploys as and the one the product runs as, VPC egress, Secret Manager secrets by name), checked whole
  before it is written, in Settings > Paved roads or with `rihmasto road configure`. A product runs there as
  a Cloud Run service or as a Cloud Run job that Cloud Scheduler runs on a cron schedule with retries; the
  road renders and validates the exact YAML, scheduler job and gcloud commands (`rihmasto road render`),
  builds with Cloud Build, runs a job once in the test project as its smoke check, stops at IT's deploy gate,
  then promotes a service's candidate revision by traffic or gives a job its image and schedule, and rolls
  back to the previous revision or image (`rihmasto road rollback`, IT or operations). A job's last
  executions feed its probe, and a failed one opens an incident card. gcloud runs only when it is on PATH
  and signed in and the road is configured; otherwise the road card says exactly what is missing. A
  capability declares a Drive folder as a `gdrive` integration and imports the paved road's client
  (`app/gdrive.py`): the files that arrived since its cursor across every page, downloads, uploads, its
  scopes stated and its credentials by name (a token or key file for a local run, the runtime service
  account on Google Cloud), never logging a token or content; the gate runs its tests against a Drive v3
  stand-in. A project's Releases view shows where each environment deploys and lets IT choose the road and
  schedule; Settings lists the integration kinds with the Drive connector. Tested end to end against a fake
  gcloud on PATH and a Drive stand-in on loopback; **not yet run against a real Google Cloud project**
  ([guide](docs/guides/gcp.md): a scheduled agent that reads recordings from Drive and writes transcripts
  back, and where the audio goes).
- **Goal help, the agent bridge and the agent channel** (FR-CPL1, FR-BRG1, FR-CHN1): ask Rihma a goal
  in a project in your own words, in English or Finnish ("hook this to Google Drive", "run it every night
  in our cloud", "deploy to test", "add sign-in", "monitor it", "give this to my coding agent") and get a
  plan from the project's records and what this Rihmasto can do, read from its code (roads, connectors,
  integration kinds, outputs, and checks, automations, runners and walkthroughs when present), with gaps
  said plainly and each step one click: a drafted change you edit and file, the right settings, a
  walkthrough, a command, or a hand-off; a model's plan is checked step by step, and a confidential
  project never asks a hosted model. **Hand off to an agent** gives a coding agent its brief (the goal or a
  change, criteria, open questions, the plan, findings, failed gates and checks, conventions, tests, how
  to report back) and the way Claude Code, Codex, OpenCode or Cursor takes it. New MCP tools read what
  Rihmasto holds (`rihma_next`, `rihma_plan`, `rihma_questions`, `rihma_handoff`, `rihma_feedback`,
  `rihma_insights`, `rihma_alignment`, `rihma_health`, `rihma_channel_read`) and write back, signed as the
  agent for its operator and never deciding (`rihma_progress`, `rihma_propose_answer`,
  `rihma_request_gate`, `rihma_channel_post`, `rihma_ask_rihma`). Each project has an **agent channel**
  where people, Rihma's agents and coding agents talk: Rihma answers from the records by rule, else
  through Gnomon with a trace, within per-thread limits; a person confirms or rejects an agent's proposed
  answer, pauses the channel, and watches it live, as a tab or beside any view; **Agent activity** lists
  every live channel. The overview's **Agents working on this** strip shows what agents did. Commands
  `rihmasto goal`, `rihmasto handoff` and `rihmasto channel` ([guide](docs/guides/agentic-help.md)).

- **Change anything, go back a step, never get stuck** (FR-CHG1): a project's kind of work, mode,
  maturity and title change after it was made, with a preview of what the change means for the
  questions, spec and plan already done (`project_changed` in the ledger, before and after); a project
  goes back to its material, questions, spec or plan so that step runs again, with what it sets aside
  kept under `superseded/` and open questions withdrawn with the reason (never past a release); material
  is added later, and re-intake asks only about what is new; What's next on the overview, and
  `rihmasto next`, say what a project waits for, who can act, and the actions that move it on. Commands
  `rihmasto settings`, `rewind`, `material add` and `next`; the cockpit's Project settings dialog
  ([guide](docs/guides/change-anything.md)). An intake run again never asks a settled question again.
- **Shape it in chat** (D-0022, FR-SHP1): open a conversation with Rihma (the analyst role) with
  nothing, a sentence, a file (text, Markdown or Word) or a folder, and work out the need: Rihma asks
  one or two questions at a time and keeps a draft brief beside the chat that you can edit (a field you
  edited stays yours), and says when it is good enough. **Create the project from this** asks for the
  work profile, mode and maturity with Rihma's suggestion; the draft becomes the project's request, so
  intake never asks again what it says. Conversations are kept under `_shape/`, signed in the factory's
  ledger, and resume later. With no model set up, the chat says so and links to Models setup. In the
  cockpit from Home and New project, and as `rihmasto shape` (interactive, or
  `start|say|attach|edit|show|create`) ([guide](docs/guides/shape-in-chat.md)).
- **Models setup** (FR-MDL1): Settings > Models and `rihmasto models list|presets|test|set|remove`
  show each role's model, endpoint host, local or hosted, key state and readiness, and set a role to
  any OpenAI-compatible endpoint (presets for llama.cpp, Ollama, vLLM, OpenCode Go and hosted
  providers) in this machine's `kernel/routing.local.json`. A key is given as an environment
  variable's name or stored outside the repository, handed to Gnomon in its variable, and never shown,
  logged or put in the ledger. **Test** sends a tiny prompt and says the latency or the error. Home
  shows a **Set up a model** card while no model answers ([guide](docs/guides/models-setup.md)).
- **Releases** (FR-REL1): pushing a version tag such as `v1.0.0` runs the suite and the contract again,
  then builds the source archives, a CycloneDX SBOM and `SHA256SUMS`, signs a build provenance
  attestation and publishes a GitHub Release whose notes are the version's changelog section. A tag
  that is not `pyproject.toml`'s version, or a version with no changelog section, publishes nothing.
  "Run workflow" rehearses without publishing ([docs/maintainers.md](docs/maintainers.md)). CI uses
  `actions/checkout` and `actions/setup-python` v7.
- **Any folder as material** (FR-MAT1): intake scans whatever a folder holds instead of expecting
  certain file names. Word, PowerPoint, Excel, OpenDocument, HTML, CSV, JSON, YAML, TOML, PDF (partly
  read), logs (first and last lines) and code (an inventory, never its text) are read by rule; every file
  is read, summarised, listed or skipped with why, secret-looking files are never read, and a budget
  reads the most telling first and says what it cut. `rihmasto scan <folder>` and the cockpit's **Scan
  the folder** step show the map before anything is sent; `new` with a folder needs `--yes`. A
  **confidential** project keeps every model call on loopback or private endpoints and refuses a hosted
  one, naming the role. **An existing project** may be any folder: one that is not a git repository is
  snapshotted into a baseline repository (the folder is never changed), and one with no code is offered
  as material for a new project ([inputs](docs/guides/inputs.md), [brownfield](docs/brownfield.md)).

- **Autopilot, delegation and staying on track** (D-0017): a person delegates named card kinds on a
  project, for at most seven days, to the factory's deterministic rules, and the pipeline decides those
  cards in their name with "by delegation" on record; an autopilot run lets Rihmasto run on its own,
  bound to a sandbox (local preview or roads marked sandbox, sandbox relay receivers, no connector
  writes), until a person stops it; Track says whether a project stays on track against its approved
  plan, with every figure's basis, human checkpoints that can hold the run, and a daily digest through
  the relay. Commands `rihmasto autopilot`, `delegation`, `track` and `tracking`; the cockpit's Track
  view, pill and Home widget; the MCP reads `rihma_track` and `rihma_autopilot`
  ([guide](docs/guides/autopilot-and-tracking.md)). A pass under way when a person stops the autopilot
  stays in the sandbox (it delivers nothing and ends at its next safe point), the daily digest leaves a
  held project out for receivers outside the sandbox, and a project header shows one on-track answer.
- **Outputs per audience** ([docs/guides/outputs.md](docs/guides/outputs.md)): a person chooses what
  a project delivers, at intake or later, and the kernel builds each output from the records and the
  release, the same records giving the same bytes: a web app with the paved road's sign-in, a
  container with compose, an OpenAPI 3.1 description, a plain delivery report, the evidence pack and
  the source as a git bundle. `rihmasto output`, and the cockpit's **Outputs** view. The MCP server
  output is planned, through a hook to the small-capability faces. Outputs chosen with the request
  are told to intake and never asked again; the source's README runs as written outside any
  repository; the sign-in's checks catch session fixation; a sign-in added later runs unprivileged;
  and a factory check the sign-in turns away is recorded as not measured, never failed or passed.
- **Use only what you need.** Rihmasto is a catalogue of modules with presets (spec only, gate my code,
  assess only, security only, evidence only, capability only, the full factory), chosen per factory
  and per project by a named person and recorded in the ledger: `rihmasto modules show|set|presets`,
  Settings, Modules in the cockpit, and a first-run choice on a new factory home. A module that is off
  is refused where it acts, on the command line, in the cockpit, in the MCP server's write tools, in
  a website's chat and at the webhook server, is hidden where it shows and is not proposed by the
  assistant; a safety switch (revoking a chat, removing a webhook source, ending a subscription,
  disabling a connector) stays open whatever is on. An attached repository's tests run only through IT's isolation runner while
  access is enforced. A repository of your own is attached with
  `rihmasto repo attach` and judged by the gate (`repo gate`), scanned (`repo scan`) and its releases
  recorded for evidence (`repo releases`); `rihmasto contract export` ends spec only in files
  ([docs/guides/use-only-what-you-need.md](docs/guides/use-only-what-you-need.md)).

- **Small capabilities** ([docs/guides/small-capabilities.md](docs/guides/small-capabilities.md)): the
  `automation` profile and its capability template, a runtime declaration (`app/runtime.json`) judged
  at the gate and carried in the pack with secrets by name, one image whose faces (MCP over stdio and
  Streamable HTTP, an OpenAI-compatible chat also routed by the gateway, a website embed, HTTP) answer
  only after the pack guard has checked the pack, verified webhook and relay triggers, a schedule,
  results out as signed events, `rihmasto capability check` and `serve`, and the faces in
  `compose.yaml`. A face the declaration does not name stays shut on every transport, MCP's stdio
  included, and the openai face reports its token usage as not measured (the gateway's audit too),
  never as zeros.
- **Postures and priority weights** ([docs/guides/postures.md](docs/guides/postures.md)): prototype,
  balanced, production or regulated, tuned by ux, security, compliance, speed and cost, previewed
  before anyone chooses, recorded with who chose it, and changed during the run with what it changes
  now and later (`rihmasto posture`, New project's **How it runs**, where *No posture* is chosen
  until a person picks one, for a need and for an adopted project, and the **Posture** chip in the
  header and in Project settings, whose maturity and mode changes keep to the posture).
- **Brownfield assessment** ([docs/brownfield.md](docs/brownfield.md#assessing-an-adopted-system)):
  `rihmasto assess` and the cockpit's **Assessment** view judge an adopted system from every
  perspective by rule, versioned, with the panel's review apart, and file chosen findings as changes.
- **Access with the identity provider's signed token** ([docs/guides/access.md](docs/guides/access.md)):
  the cockpit verifies the provider's token (RS256 or ES256) and holds no shared secret; with access
  enforced, untrusted code (a suite, an adopted suite, a product, a Gnomon cell) runs only through
  IT's isolation runner, and the cockpit refuses to start a job that would need one it lacks.
- **Data integrations** ([docs/guides/data-integrations.md](docs/guides/data-integrations.md)): a
  product declares the databases, warehouses, cloud storage and business APIs it reaches, IT approves
  each binding, delivery wires it in by name, and the gate tests it on stand-ins.
- **The acceptance matrix** ([docs/acceptance.md](docs/acceptance.md)): every need, mode, maturity and
  access column with its offline cells in `tests/acceptance`, and the live acid-test plan.
- **Pull requests only.** `main` changes only through pull requests that pass the four CI jobs and
  the new DCO sign-off check, with a code owner's review, squash-merged
  ([CONTRIBUTING.md](CONTRIBUTING.md#how-changes-reach-main)).
- **The DCO sign-off check:** [tools/dco_check.py](tools/dco_check.py), run on every pull request by
  [.github/workflows/dco.yml](.github/workflows/dco.yml). It lists each commit without its author's
  sign-off and says how to fix it from the commit the branch starts from. The owner's and
  Dependabot's exemptions hold only in pull requests their own accounts opened, and a commit whose
  text holds a control character is still checked.
- **CODEOWNERS** and **Dependabot** for the GitHub Actions the workflows use (Rihmasto has no package
  dependencies).
- **The two-way sync:** [tools/release_sync.py](tools/release_sync.py) sends each snapshot of the
  maintainers' development repository here as a pull request, and brings merged contributions back
  with their authors and merged messages. A contribution comes in as the three-way merge of its
  change, so a change that is there already is never applied twice. The import refuses a path the
  release leaves out (in any case), a path that differs only in case, a merge commit, and a change
  to the exclude list, the release tools or a `.gitignore` that a maintainer has not read, or that
  would let a private or ignored file out. A copied export trailer never skips an import, and an
  export never reverts one. [docs/maintainers.md](docs/maintainers.md) gives the procedure and the
  repository's settings.
- This changelog.

### Changed

- Questions go to GitHub Discussions; security reports go to private vulnerability reporting, at
  the repository's security advisories ([SECURITY.md](SECURITY.md)).
- The release export's exclude list matches paths in any case, so a left-out folder spelled
  otherwise on a disk that ignores case stays out too.

### Fixed

Found by walking the owner's journeys in a real cockpit with a local model:

- New project no longer assumes a web app: **Let Rihma choose** is the default, and the intake proposes
  the kind of work by rule from the need or the folder.
- A project made from a folder, or adopted, opens its Project settings again (they read "unreadable"), and
  material added to it is kept beside the folder's map instead of failing.
- Material read with re-intake no longer goes on to build on the spec written before it; nothing is built
  past an open blocking question (FR-CHG1-AC-10).
- What's next drops a run's result from before a person went back a step, changed a setting or added
  material; says when the autonomy cap stops the build, on the command line too; opens Models setup for
  any persona when a model did not answer; names the command for every action; and offers an improved
  adopted project's next steps.
- The Jobs page opens the project an adoption made; the first-run name shows at once in the person menu;
  Ask Rihma no longer flags a cockpit view or control it cites as "not found"; a confidential refusal and
  Models setup say how to drop a hosted fallback; `rihmasto settings` and `rewind` previews need no signer.

## [1.0.0.dev0] - 2026-11-23

The first public release: a development snapshot. Commands, file formats and the cockpit's API may
still change before 1.0.0. It covers the first public snapshot and what was published the same day:
the fixes below and Rihmasto's own red team.

### Added

- **The chain from a need to a running service:** an intake panel whose perspectives ask the
  questions that change what gets built; specs with given / when / then criteria and their
  provenance; a contract compiled with no model and pinned by its hash; Gnomon builder cells; a gate
  that runs the tests itself, checks that they fail first, keeps holdout scenarios in custody and
  asks an independent verifier; delivery on paved roads; and a change loop.
- **The cockpit:** one Inbox for the decisions that are people's, lenses per persona, and Rihma
  agents ("Ask Rihma"), behind a one-use sign-in on 127.0.0.1.
- **The capability layer:** capability packs, evidence packs with a chain check, and the autonomy
  ladder with its cap.
- **Signals and concepts, website chats (embeds), the security gate** for SARIF findings with
  accepted risks that expire, and **the MCP server** for a developer's own coding agent (reads and
  proposals, never decisions).
- **Seven work profiles:** `web_service` and `integration` ready, five in preview.
- **`rihmasto demo`**, a demo factory with no keys, no network and no Gnomon, and a 15-minute tour
  by role ([docs/demo.md](docs/demo.md)): a website feedback chat, a stakeholder comment, a
  security scan with an accepted risk, an exported evidence pack, an autonomy cap and an adopted
  existing service.
- **Rihmasto's own red team** (`python -m kernel.redteam`, [docs/guides/security.md](docs/guides/security.md)):
  static checks of Python, JavaScript and HTML, Dockerfiles, GitHub Actions and secrets, each rule
  with a CWE and an OWASP Top 10 2025 id, a seeded example it must catch and a clean twin it must
  stay silent on, and SARIF into the security gate; dynamic probes only of a service the factory
  deployed itself, on loopback, under a written scope an IT or compliance person grants for at most
  31 days; and agentic checks of Rihma agents and website chats against injection and leaks, scored
  by canaries. A layer that could not run is not measured, never passed. The bypasses independent
  attacks found are seeded cases it now catches, or limits the guide documents.
- **The Rihmasto logo:** the README banner, the cockpit's corner mark and its tab icon.
- **The project's rules:** the contributing guide, the code of conduct (Contributor Covenant 2.1),
  governance, the security policy, issue and pull request templates, and CI on Ubuntu and Windows
  with Python 3.11 and 3.12. Apache License 2.0.

### Fixed

- The tests hold on Python 3.11 and 3.12: deep JSON is refused at parsing, and a run with no test
  exits 0.
- A decision made before a workspace merged a task never undoes the merge.
- A capability pack keeps the criteria its release had; a malformed ledger line no longer stops an
  evidence export.
- A developer's label on a change, on an adopted solution too, waits for the business decision it
  needs; withdrawn holdouts never run.
- Cockpit Home: Customize keeps one lens and the keyboard focus, the pipeline reads at every size,
  nothing unmeasured shows as zero, and a read error shows as an error. The square, the catalogue,
  the Inbox and the settings have the fixes from a UI audit, each checked in a real browser.
- The routing overlay, the home variables, the install docs and the release export's checks; the
  release scan reads a private key as a header with key material after it.
- The browser driver waits through a page that is still navigating, so a slow machine is not a
  failure.
- The Gnomon surface's comments and the contract's prose say Rihmasto, not the project's working
  name.
