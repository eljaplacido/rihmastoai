<p align="center">
  <img src="docs/assets/rihmasto-banner.jpg" alt="Rihmasto: from an idea or a repository to a spec, a tested contract and a gated build, with a person signing every decision" width="760">
</p>

# Rihmasto

Rihmasto takes an idea or an existing repository, turns it into a spec and a tested contract, has
coding agents build against it behind a gate that runs the tests itself, ships it only to targets you
configured, and keeps it healthy, with a person signing every decision.

It sits between where software is developed (your IDE, a terminal, Claude Code, Codex, OpenCode or
Cursor, or Rihmasto's own builders) and where it goes, and records every step in a hash-chained
ledger. Today the one delivery target that has run for real is the local preview on your own machine;
the docker and Google Cloud Run roads are tested only against stand-ins ([Status](#status)). Rihmasto
is alpha software with one maintainer.

> Models propose. The kernel (plain code, with no model in it) decides. People own intent and policy.

Rihmasto is free to adopt, under the [Apache License 2.0](LICENSE).

## Pick your path

| You want to | Go to |
|---|---|
| Try it in two minutes, with no keys and no network | [Quick start](#quick-start) |
| Start from an idea, a sentence or a written spec | [Start fresh from an idea](#1-start-fresh-from-an-idea) |
| Bring in a repository you already have | [Integrate into an existing project](#2-integrate-into-an-existing-project) |
| Think a concept through, or mock it up quickly | [Conceptualise](#3-conceptualise) |
| Keep something running and know when it breaks | [Keep something running](#4-keep-something-running) |
| Work from your own IDE or coding agent | [Work from your IDE or terminal](#5-work-from-your-ide-or-terminal) |
| See everything it can do | [Capabilities](#capabilities) |

## Who it is for

- **One developer.** Start a project from an idea, or point Rihmasto at a repository, and keep using
  your own editor and agent. With no access file, Rihmasto runs in single-operator mode: you pick any
  persona from the person chip, nothing to set up, and each decision records which persona you used.
- **A team.** Personas become people. IT runs an identity-aware proxy in front of the cockpit
  ([access](docs/guides/access.md)) and an access file says who may decide as which persona.
- **By role:**

| You are | Rihmasto gives you |
|---|---|
| A business owner | One Inbox for your decisions: approve the plan, accept a demo, validate a concept, set how far it may go alone. |
| A product owner | Needs that arrive as signals and become concepts, with the panel's questions and assumptions in plain view. |
| A developer | Your own IDE and agent, a spec and a hashed contract, and a gate that runs the tests itself. |
| IT and operations | Delivery only on roads you configured, your deploy gate, checks, probes and incidents. |
| Compliance | A hash-chained ledger, evidence packs that say *insufficient evidence* rather than "compliant", expiring accepted risks, and the autonomy cap. |

## Quick start

You need Python 3.11 or later and git. The demo needs no Gnomon, no model keys and no network.

```bash
git clone https://github.com/eljaplacido/rihmastoai rihmasto && cd rihmasto
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
rihmasto demo && rihmasto-cockpit --home var/demo
```

- Use a virtual environment of its own: Rihmasto's `mcp` package would shadow the MCP Python SDK.
- `rihmasto demo` builds a demo home in `var/demo` in well under a minute: the real kernel, with a
  scripted model and builder standing in for Gnomon, and fake people named `demo-*`
  ([what it holds](docs/demo.md)).
- `rihmasto-cockpit` prints a one-use sign-in link on 127.0.0.1. Open it once.
- `rihmasto doctor` shows what this machine has: Python, Gnomon, git, docker and the model keys.
- Without installing, run `python -m kernel.cli demo` and `python -m cockpit.server --home var/demo`.

The demo is a sandbox with a scripted model. Real work starts on your own home, with a real model:
see [Before any scenario](#before-any-scenario).

## Scenarios

Each step names the click in the cockpit (the web UI) and the command that does the same.

### Before any scenario

1. **Install** as in the [Quick start](#quick-start).
2. **Choose a model.** Intake, Shape it in chat, alignment and Ask Rihma need one. Either:
   - an OpenAI-compatible endpoint, local or hosted: the cockpit's **Models setup**, or
     `rihmasto models set analyst --base-url <url> --model <name> --key-env <VARIABLE> --person "Ada Example" --persona it`
     ([models setup](docs/guides/models-setup.md)). Endpoints are called through Gnomon, so
     [install Gnomon](docs/getting-started.md#5-install-gnomon-and-configure-models) first;
   - or the coding agent you already have, with no API key:
     `rihmasto models use claude-code --person "Ada Example" --persona it` (or `codex`, `opencode`;
     [guide](docs/guides/harness-models.md)). It runs on that person's own account and its terms.

   `rihmasto models test analyst` sends a tiny prompt to check it. Building (step 4 below) also needs
   Gnomon, or another harness IT approved ([harnesses](docs/guides/harnesses.md)).
3. **Start the cockpit on your own home:** `rihmasto-cockpit`, with no `--home`. It uses
   `$RIHMASTO_HOME`, else `var/` in the checkout, the same home as the command line; the demo in
   `var/demo` stays separate. Open the sign-in link it prints.
4. **Sign as yourself.** In the cockpit, pick a persona from the person chip, top right. On the
   command line, every command that records a decision takes `--person "Your Name" --persona <id>`.
   The persona ids are `business_owner`, `product_owner`, `concept_evaluator`, `end_user`, `it`,
   `developer`, `operations`, `stakeholder` and `compliance`. Single-operator mode still needs both.
5. **Find the project id** (`<pid>` below, such as `equipment-loans-3f9a1c`). `rihmasto new` and
   `rihmasto adopt` print it, `rihmasto status` lists every project, and the cockpit shows it in the
   address bar (`#/p/<pid>/overview`).

In the commands, `<...>` is a value you fill in, and "Ada Example" stands for your name.

### Words used here

- **Kernel**: Rihmasto's rule engine, standard-library Python with no model in it. It decides what is
  accepted and writes the ledger.
- **Harness**: the program that runs an agent with its tools and limits. Gnomon is the default.
- **Contract**: the requirements and their given / when / then criteria, compiled with no model and
  pinned by a hash.
- **Gate**: the kernel runs the tests itself, checks each criterion has a test, and asks a verifier
  from another model family. Nothing passes on a model's word.
- **Cell**: one builder run for one task, in a sandbox with its own write scope.
- **Holdouts**: test scenarios the builder never sees, run against the delivered service.
- **Decision**: a card in the Inbox that waits for a person: approve a plan, accept a demo, pass a
  deploy gate. Every decision names a person and a persona.
- **Persona**: the role you decide as (business owner, developer, IT and so on).
- **Maturity**: how far a project goes: explore < demo < pilot < production. Explore lands on a local
  preview; the others need a paved road.
- **Paved road**: a delivery target IT configured, with its own deploy gate.
- **Posture**: how strict the chain is: prototype, balanced, production or regulated.
- **Delivery square**: where needs (signals) become concepts a business owner validates.

### 1. Start fresh from an idea

This path stays at explore maturity, which lands on a local preview and needs nothing configured.

1. **Shape it.** Home > **Shape it in chat**: say the idea, answer Rihma's questions, edit the draft
   brief beside the chat and press **Create the project from this**. Or **New project > A need or a
   spec** and **Create and start the intake**. The command:
   `rihmasto new "Equipment loans" --source "Our team keeps losing track of who borrowed the drills." --maturity explore --mode mixed --requested-by "Ada Example"`
2. **Answer the questions.** The intake panel's questions wait in the project's **Questions** tab.
   Answer each, or press **Let Rihma assume** to make it an assumption with a due date.
   `rihmasto answer <pid> Q-001 "the team lead approves" --person "Ada Example" --persona business_owner`
   or `rihmasto assume <pid> Q-002 --person "Ada Example" --persona business_owner`.
3. **Read the spec.** **Spec & contract** shows the requirements, their criteria and who confirmed
   what.
4. **Build.** **Advance** (or `rihmasto run <pid>`) compiles the contract, writes the holdouts, builds
   each task in a cell and judges it at the gate. It stops at each decision a person must make:
   decide it in the **Inbox**, or `rihmasto status <pid>` lists them and
   `rihmasto decide <pid> <decision id> <verdict> --person "Ada Example" --persona developer` decides
   one (the persona must be one that may make that decision).
5. **Try it.** The release lands on the local preview. Open **Try it**. **Report a change**, or
   `rihmasto change <pid> "An empty name crashes" --person "Ada Example" --persona end_user`, sends
   feedback back through the same chain.

**Going further: demo, pilot, production.** These need a paved road, and today no road to a target
outside this machine has run for real: docker and Google Cloud Run are tested only against stand-ins,
and Azure Container Apps is rendered but never deployed ([Status](#status)).

1. IT configures a road first: **Settings > Paved roads** ([deploying](docs/guides/deploying.md)).
2. Raise the maturity in **Project settings**, which previews what changes, or
   `rihmasto settings <pid> --maturity pilot --preview` and then without `--preview`.
3. At pilot and production a person approves the plan before anything is built. At demo the business
   owner accepts the demo; at production IT's deploy gate decides, with shadow, canary and rollback.
   `rihmasto deliver <pid>` delivers on the road for the project's maturity.

### 2. Integrate into an existing project

Rihmasto adopts, aligns, gates and watches a repository you already have. It does not deploy it: no
paved road delivers an adopted repository yet.

1. **Point at it.** **New project > An existing project**: a folder on this machine or a git address.
2. **Scan.** **Scan the folder** shows what would be read, listed and skipped, the AI-tool setup it
   found (CLAUDE.md, AGENTS.md, Cursor rules, MCP servers), and the files it never reads because they
   look secret. Untick what to leave out. `rihmasto scan <folder>`
3. **Confidential?** Tick it (`--confidential`), and every model call for the project stays on local
   models.
4. **Adopt.** Choose Monitor, Maintain or Improve. Adoption reads the project and runs its tests once
   for a baseline; a folder that is not a git repository is snapshotted, and your folder is never
   changed.
   `rihmasto adopt "Billing service" --source <folder or git URL> --intent maintain --person "Ada Example" --persona developer`
5. **Assess** (optional). **Assessment > Assess now**, or
   `rihmasto assess <pid> --person "Ada Example" --persona developer`, gives findings you can file as
   changes.
6. **Align.** **Alignment > Read the repository** proposes the repository's own specs, criteria and
   tests for the contract; accept, edit or reject each. `rihmasto align <pid> --scan`, then
   `rihmasto align <pid> accept <item ids> --person "Ada Example" --persona developer`.
7. **Keep working in your IDE.** **Work on it from your IDE** on the Overview, or `rihmasto ide <pid>`,
   gives the MCP configuration and a conventions section for AGENTS.md or CLAUDE.md.
8. **Watch it.** **Health > Enable a check** runs tests, CI status, dependency audit, secrets and more
   on a schedule:
   `rihmasto checks enable <pid> tests --every 1d --person "Ada Example" --persona developer`.
   `rihmasto sync <pid>` fetches upstream and records the drift, and an automation can run on new
   commits. The gate itself runs only a Python unittest suite; other suites are characterised at
   adoption.

### 3. Conceptualise

1. **Start loose.** Home > **Shape it in chat**, starting with a sentence or nothing, or attach a
   folder of documents. From the command line, `rihmasto new "Title" --source <folder> --requested-by "Ada Example"`
   shows the scan of the folder first and asks for `--yes`.
2. **Choose how to work it out:**
   - **Think it through.** Socratic mode sends every question to a person and assumes nothing:
     choose it as the project's **Mode**, or `--mode socratic`.
   - **Get a quick mock-up.** The prototype posture assumes answers and builds fast; at explore it
     lands on the local preview. `--posture prototype --maturity explore`, then open **Try it**.
3. **Validate it as a concept** (when the need came from the business). The **Delivery square** is
   where needs arrive as signals and become concepts. **Log a signal**, then a business owner or
   product owner validates, parks or rejects the concept there.
   `rihmasto signal log --text "Drivers want a picking list" --channel chat --source "team chat" --person "Ada Example" --persona product_owner`,
   `rihmasto signal triage S-001`, then
   `rihmasto decide _factory C-0001 validate --person "Ada Example" --persona business_owner`.
   `_factory` is the factory-level project that holds signals and concepts. `rihmasto tick` turns a
   validated concept into a project.
4. **Firm it up.** When it holds, change the posture, mode or maturity in **Project settings**
   (`rihmasto posture preview balanced` shows what a posture would do) and it carries on through the same
   chain.

### 4. Keep something running

1. **Check it.** **Health**: tests, CI status, dependencies, secrets, licences, an SBOM and an HTTP
   probe, each on a schedule. `rihmasto checks list <pid>`
2. **Probe it.** `rihmasto operate <pid>` runs one operations round: it checks `/health` and the probe
   scenarios where the release runs, and a failing probe opens an incident decision in the Inbox. On a
   road with a canary, a canary worse than the current release is rolled back and opens an incident.
3. **Automate it.** **Automations**: start from a template ("Notify when a check fails") or build
   one: a trigger, a guard and an allow-listed action. Without the cockpit running,
   `rihmasto automations install-help` prints the cron or Task Scheduler line.
4. **Review each morning.** **Review** lists what shipped, what went wrong, what was decided in your
   name and what waits on you. Mark it reviewed, or have it sent each morning. `rihmasto review`
5. **Read the trends.** **Insights**: health, security, QA and usage, counted from the records, and
   "not measured" when they are not. `rihmasto insights`

### 5. Work from your IDE or terminal

1. **Connect your agent.** `rihmasto ide <pid>` prints the MCP configuration for Claude Code, Cursor
   or Codex. The server (`rihmasto-mcp`) gives your agent reads and proposals, never decisions.
2. **Hand off.** **Hand off to an agent** in the project's header, or
   `rihmasto handoff <pid> --to claude-code`, gives a brief with the goal or change, the contract's
   criteria, the project's conventions and how to report back.
3. **Talk in the agent channel.** Your agent posts progress and Rihma's agents answer:
   `rihmasto channel <pid> post --as claude-code --kind progress --text "AC-1 passes" --person "Ada Example" --persona developer`.
   Watch it in **Agent channel**, or `rihmasto channel <pid> --follow`.
4. **Bring work back.**
   `rihmasto workspace open <pid> --agent claude --person "Ada Example" --persona developer` gives a
   workspace;
   `rihmasto workspace submit <pid> <path> --person "Ada Example" --persona developer` sends the
   change to the same gate.
5. **Use the console.** **Console** runs the project's commands on record:
   `rihmasto console <pid> --person "Ada Example" --persona developer -- python -m unittest`.
   **Open a terminal here**, or `rihmasto shell <pid>`, for anything interactive.

## Capabilities

Each capability works from the cockpit, and most from Ask Rihma and the command line too. Items marked
*(preview)* are partly built; *(stand-ins)* means tested only against fakes, never a real system.

| Area | What you can do | Guides |
|---|---|---|
| **Intake and shaping** | Shape a need in chat or from a spec, plan or folder; a panel asks the questions that change what gets built; pick one of 13 kinds of work (3 ready, 10 *preview*) and a posture; change any of it later. | [shape it in chat](docs/guides/shape-in-chat.md), [inputs](docs/guides/inputs.md), [profiles](docs/guides/profiles.md), [postures](docs/guides/postures.md), [change anything](docs/guides/change-anything.md) |
| **Existing projects** | Adopt a folder or git address with a test baseline, assess it, align its own specs and tests with the contract, follow its AI-tool setup, record upstream drift. Not delivered by a road yet. | [existing solutions](docs/brownfield.md), [alignment](docs/guides/alignment.md), [your IDE and Rihmasto](docs/guides/ide-and-rihmasto.md) |
| **Build and verify** | A hashed contract, builder cells in Gnomon (or another harness, checked after the run), a gate that runs the tests itself, holdouts, a security gate with Rihmasto's own scans and SARIF from any scanner. | [how it works](docs/how-it-works.md), [harnesses](docs/guides/harnesses.md), [models](docs/guides/models-setup.md), [security](docs/guides/security.md) |
| **Run and deliver** | The local preview road (real); docker and Google Cloud Run roads *(stand-ins)*; Azure Container Apps *(preview)*; outputs per audience; small capabilities over MCP, an OpenAI-compatible endpoint, a website chat or HTTP. | [deploying](docs/guides/deploying.md), [outputs](docs/guides/outputs.md), [small capabilities](docs/guides/small-capabilities.md) |
| **Integrations** | Website chats that file feedback or needs; signed events out and verified webhooks in; Teams, Slack and email notices *(stand-ins)*; data bindings and a Google Drive connector *(stand-ins)*. | [embeds](docs/guides/embeds.md), [events](docs/guides/integrations.md), [data](docs/guides/data-integrations.md), [Google Cloud](docs/guides/gcp.md) |
| **Keep it healthy** | Scheduled checks with a Health view, probes that open incidents, automations with guards and a circuit breaker, a recorded console, an autopilot capped by the autonomy ladder. | [checks](docs/guides/console-and-checks.md), [automations](docs/guides/automations.md), [autopilot](docs/guides/autopilot-and-tracking.md), [autonomy](docs/guides/autonomy.md) |
| **Agents and help** | Ask Rihma in every view (proposals you confirm, never writes on its own), walkthroughs, goal help, hand-offs, the agent channel, an MCP server for your IDE agent. | [cockpit](docs/cockpit.md), [walkthroughs](docs/guides/walkthroughs.md), [agentic help](docs/guides/agentic-help.md), [MCP](docs/mcp.md) |
| **See and govern** | Review since you last looked, Insights, a read-only graph of the records, capability and evidence packs, single-operator or enforced access. | [review](docs/guides/review.md), [insights](docs/guides/insights.md), [graph](docs/knowledge-graph.md), [packs](docs/guides/packs-and-evidence.md), [access](docs/guides/access.md) |

<details>
<summary>More detail per area</summary>

- **Intake.** A material map shows what of a folder is read, summarised or skipped before anything is
  sent. The panel (business, end user, IT and security, operations, delivery) works in socratic,
  assume or mixed mode. Ready kinds of work: `web_service`, `integration`, `automation`. The other ten
  build on the web-service template.
- **Existing projects.** A folder of documents only is offered as material for a new project instead.
  Alignment reads spec-kit, Kiro, BMAD, Gherkin, OpenAPI and more, and shows the gaps and the drift.
- **Build.** Requirements carry given / when / then criteria; the kernel sets ids and records who
  confirmed what. The gate checks that tests fail first. Models: any OpenAI-compatible endpoint per
  role, fully local if you like, or your coding agent answering the text roles.
  [Use only what you need](docs/guides/use-only-what-you-need.md): spec only, gate my code, a small
  capability, or the whole chain.
- **Delivery.** Outputs: a web app with sign-in, a container, an OpenAPI description, a delivery
  report, an evidence pack, the source. The [capability gateway](docs/guides/gateway.md) *(preview)*
  gives one OpenAI-compatible endpoint for a site's workloads.
- **Packs.** A capability pack pins a release by hash and says what it lacks (no SBOM, not signed).
  An evidence pack's verdict is *attestable*, *chain broken* or *insufficient evidence*, never
  "compliant".
- **Access.** Delegation gives chosen kinds of decision to an agent until a date you set
  (`rihmasto delegation`). Some kinds are never delegated.

</details>

## What it is, and what it is not

**It is** the platform around your IDE for a capability's whole life
([D-0023](decisions/D-0023-what-rihmasto-is-and-is-not.md)): it takes in what development produced,
holds the intent, the contract and the decisions, verifies and packages the result, sends it to the
targets IT configured with people deciding, watches it, and brings feedback back to development.

**It is not:**

- **an IDE or a code editor.** Write code in the editor and agent you prefer. Rihmasto reads that
  work's specs, tests and conventions, aligns them with its contract through proposals a person
  accepts, and hands context back;
- **a replacement for your CI, monitoring or ticketing.** It reads CI status, runs its own gate and
  checks, and exports to your observability tools. It is the system of record for decisions and
  evidence, not for telemetry or tickets;
- **tied to one harness or one model.** Gnomon is the default; other harnesses run cells opt-in, with
  the rules checked after the run ([D-0019](decisions/D-0019-other-harnesses-as-opt-in-cell-runners.md));
- **an autopilot without people.** Autonomy is capped, delegated, sandboxed and recorded. No
  automation makes a decision that waits for a person;
- **a framework for writing agents in code.** It builds, verifies and governs services, agents,
  workflows and automations. Agent code written by hand comes in through adoption;
- **a place where a step can skip the record.** A light posture asks less and gates less. It never
  drops provenance ([D-0017](decisions/D-0017-governance-everywhere.md)).

## How it works

```text
a need or an existing project: an idea, a spec, a folder, a signal, a repository
  |
  v
material map ..... each file read, summarised, listed or skipped, with why; secrets never read
intake panel ..... the questions that change what gets built; people answer or let Rihma assume
spec ............. given / when / then criteria; the kernel sets ids and who confirmed what
hashed contract .. compiled with no model; every criterion needs a test named by its id
builder cells .... each task in a Gnomon cell (or another harness, checked after), in its write scope
gate ............. tests run by the kernel, fail-first, an independent verifier, holdouts
delivery ......... paved roads only; IT's deploy gate; shadow, canary, rollback
keep healthy ..... checks, probes, incidents, automations, the change loop
```

The kernel is standard-library Python with no model in it. It decides by rule whether work is
accepted and appends every transition to a hash-chained ledger. People decide in the Inbox, and each
decision names a person and a persona. [docs/how-it-works.md](docs/how-it-works.md) explains each
step.

Rihmasto runs on [Gnomon](https://github.com/eljaplacido/gnomonharness), an open agent harness, and
depends on nothing else at runtime. By default every model call goes through Gnomon, which enforces
each agent's tools, write scope and sandbox during the run and keeps an audit trail. Two exceptions:
when your coding agent answers the text roles, each call is recorded in Rihmasto's ledger as run by
that agent, not through Gnomon, with no Gnomon audit trail; and when another harness runs the cells,
the rules are checked after the run, not enforced during it.

*Rihmasto* is Finnish for a mycelium, the whole network of fungal threads. One thread is a *rihma*:
a single agent in Rihmasto is **a Rihma agent**. The analyst, the builder, the verifier, the holdout
author and the chat assistant ("Ask Rihma") are Rihma agents
([D-0013](decisions/D-0013-name-rihmasto.md)).

## Status

Version **1.0.0.dev0**, alpha, with one maintainer ([governance](GOVERNANCE.md)). There has been no
independent security review or penetration test; it is installed from source, with no release on a
package registry. It is not yet recommended for production company use. Commands, file formats and
the cockpit's API may still change before 1.0.0. [SECURITY.md](SECURITY.md) has the threat model.

**Built and covered by the offline test suite (scripted models, no network):**

- the chain from intake to delivery on the local preview road: panel, spec rules, contract, gate,
  holdouts in custody, change loop and ledger;
- the command line, the demo, the cockpit and the MCP server;
- Shape it in chat, walkthroughs, goal help, hand-offs, the agent channel and Ask Rihma's proposals;
- adoption of folders and git addresses, assessment, alignment, drift after a sync;
- the `web_service`, `integration` and `automation` profiles, and small capabilities, which answer
  only while their capability pack checks out;
- automations, checks, the console, probes and incidents, Review, Insights, the read-only
  `rihmasto graph`, capability and evidence packs, the autonomy ladder, delegation, autopilot and
  tracking;
- single-operator mode and enforced access through an identity-aware proxy (with test keys; see below);
- Rihmasto's own static scan, dynamic probes and agentic red team, and SARIF from any scanner.

The live end-to-end acceptance run with real models has not happened yet
([acceptance](docs/acceptance.md)).

**Built, tested only against stand-ins:**

- the docker road: a fake docker CLI, never a daemon or a registry;
- the Google Cloud Run road and the Google Drive connector: a fake gcloud and a Drive stand-in, never a
  real Google Cloud project ([what a first real run needs](docs/guides/gcp.md));
- proxy sign-in: tokens signed with test keys, never a real Entra ID, Okta, Google IAP or AWS load
  balancer;
- data bindings: the reference connectors pass against local fakes and no road calls them yet; the
  PostgreSQL live check has not run; `os:`, `cmd:` and vault references are not resolved
  ([data integrations](docs/guides/data-integrations.md));
- Teams, Slack and email notices, and signed events out: local receivers only;
- the coding agent you already have as a model, and other harnesses as cell runners: fake Claude Code,
  Codex and OpenCode commands; a real run spends that person's own subscription.

**Preview:**

- ten of the thirteen profiles, which build on the web-service template;
- the Azure Container Apps road, rendered and validated but never deployed;
- recipes, sandbox trials, measured fit and offline bundles, with no command or screen yet
  ([guide](docs/guides/recipes-and-fit.md));
- the capability gateway, run as `python -m gateway.server` ([guide](docs/guides/gateway.md)).

**Landing next** (on development branches, not on `main`, and not yet tested together): solo and team
modes with personas given to agents, self-healing with remedies and Investigate with Rihma
([D-0024](decisions/D-0024-self-healing-simple-for-one-governed-for-many.md)), a Set up this project
checklist, a destinations map per project, projects on other machines over SSH, Gnomon audits and
evals as checks, a knowledge graph view and a context and data view in the cockpit, an agent sessions
view (it reads one specific observability hub, which is not public yet). They are added here when they reach `main`.

**Designed, not built:**

- integrations through Gnomon as governed tool calls ([docs/integrations.md](docs/integrations.md));
- the portability exports ([docs/portability.md](docs/portability.md));
- publishing to a container or package registry and submitting an MCP registry entry;
- signed and anchored ledger heads, signed packs and SBOMs; SCIM provisioning and separation of
  duties.

**Know before you rely on it:**

- **No paved road delivers an adopted repository yet.** Rihmasto adopts, aligns, gates its Python
  unittest suite, checks and watches it, but does not deploy it. An adopted repository's other suites
  are characterised at adoption, and a stated test command can be its baseline, but the gate does not
  run them.
- **What leaves the machine.** Project material goes to whichever endpoint each role routes to. Mark a
  project confidential to keep its calls on local or private endpoints. Your coding agent as the model
  uses that person's own account and its terms, which may not match your company's AI policy.
- **Secrets** are held by name in the host's environment, or in a key file outside the repository
  ([models setup](docs/guides/models-setup.md)). There is no vault integration yet.
- **The audit trail.** With your coding agent as the model, or another harness running cells, a call
  is recorded in Rihmasto's ledger but not in Gnomon's audit trail, and the rules are checked after the
  run ([harnesses](docs/guides/harnesses.md)).
- **The ledger** shows an edit to part of its chain, but someone with file access who rewrites the
  whole chain consistently is not detected until ledger heads are signed and anchored (designed).
  Rihmasto makes no compliance certification; a compliance mapping is a mapping, not an attestation.
- **Running it for a team.** Rihmasto is one process on one machine. The cockpit binds only to
  127.0.0.1; people reach it through IT's HTTPS front or identity-aware proxy (`--public-origin`), or
  an SSH tunnel. State is files under the factory home, with no database and no high availability:
  back the home up yourself. There is no container image or Helm chart for Rihmasto itself
  ([access](docs/guides/access.md)).
- Without an access file, personas are self-declared and the cockpit says so. When code a model wrote
  must not run as the operator, use IT's access file and its isolation runner.
- Builder cells have run on Linux. On Windows the kernel, the tests, the demo and the cockpit run; run
  cells in WSL2 or a container.
- Cloud cost reads "not measured" until someone fills the per-token prices in
  [kernel/prices.json](kernel/prices.json).
- The shipped [kernel/routing.json](kernel/routing.json) points at a local OpenAI-compatible server on
  127.0.0.1 and a hosted endpoint. Put your own routing in `kernel/routing.local.json` (gitignored,
  merged over it); see [docs/guides/local-models.md](docs/guides/local-models.md).
- File-format ids such as `gnomonfactory.contract/1` keep the project's working name, so existing
  files stay valid.

## Documentation

[docs/README.md](docs/README.md) lists every guide by capability area and by scenario. To start:

- [docs/getting-started.md](docs/getting-started.md): install, the demo, models, a first real project.
- [docs/how-it-works.md](docs/how-it-works.md): the chain step by step, and who decides what.
- [docs/cockpit.md](docs/cockpit.md): the cockpit, its views, lenses and API.
- [docs/brownfield.md](docs/brownfield.md): existing projects, your own terminal, security findings.
- [docs/guides/ide-and-rihmasto.md](docs/guides/ide-and-rihmasto.md): where the line is between your
  IDE and Rihmasto.
- [CHANGELOG.md](CHANGELOG.md): what changed in each release.
- [decisions/](decisions/): every decision, who made it and why.

## Contributing, security and licence

- **Contributing:** read [CONTRIBUTING.md](CONTRIBUTING.md). Work is spec-first: a criterion, a
  test named after it that fails first, then the change. Sign off each commit (`git commit -s`)
  under the Developer Certificate of Origin. Changes reach `main` through pull requests only.
- **Questions:** ask in [GitHub Discussions](https://github.com/eljaplacido/rihmastoai/discussions).
- **Changes:** [CHANGELOG.md](CHANGELOG.md) lists what changed in each release.
- **Conduct:** the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md).
- **Governance:** maintainers and how decisions are made, in [GOVERNANCE.md](GOVERNANCE.md).
- **Security:** report a vulnerability privately, as [SECURITY.md](SECURITY.md) explains. Do not
  open a public issue for it.
- **Licence:** [Apache License 2.0](LICENSE). Copyright 2026 The Rihmasto authors; see
  [NOTICE](NOTICE).
