<p align="center">
  <img src="docs/assets/rihmasto-banner.jpg" alt="Rihmasto: governed AI solution factory" width="760">
</p>

# Rihmasto

Rihmasto is a governed AI solution factory. It takes a need from a vague request to a tested,
running service or agent, and it records who decided what at every step.

> Models propose. The kernel decides. People own intent and policy.

*Rihmasto* is Finnish for a mycelium, the whole network of fungal threads. One thread is a
*rihma*: in Rihmasto, a single agent is **a Rihma agent**. The analyst, the builder, the verifier,
the holdout author and the cockpit's chat assistant ("Ask Rihma") are Rihma agents
([D-0013](decisions/D-0013-name-rihmasto.md)).

Rihmasto runs on [Gnomon](https://github.com/eljaplacido/gnomonharness), an open agent harness, and
depends on nothing else at runtime. Every model call goes through Gnomon, which enforces each
agent's tools, write scope and sandbox and keeps an audit trail. Rihmasto works with any
OpenAI-compatible model endpoint, local or hosted, set per role.

Rihmasto is free to adopt, under the [Apache License 2.0](LICENSE).

## Who it is for

| You are | Rihmasto gives you |
|---|---|
| A business owner | One Inbox for the decisions that are yours: approve the plan, accept a demo, validate a new concept, set how far the factory may go on its own. |
| A product owner | Needs that arrive as signals and become concepts you validate, with the panel's questions and assumptions in plain view. |
| A developer | A spec, a hashed contract and a gate that runs the tests itself. Work in your own terminal with your own agent; your changes meet the same gate. |
| IT and operations | Delivery only on paved roads you configured, your deploy gate before production, then probes, canary and rollback. |
| Compliance | A hash-chained ledger, evidence packs for reviewers, security findings with accepted risks that expire, and the autonomy cap. |

## What Rihmasto is, and is not

Rihmasto is **the middle layer** between where solutions are developed (your IDE, terminal and
coding agents, or Rihma's own builders) and everywhere they go (backends and clouds, test
environments, data systems, and the channels and platforms where they are published or used).

Rihmasto is the platform for an agentic capability's whole life:

1. an idea becomes a concept and a first mock-up;
2. the concept is productionised;
3. its integrations are worked out;
4. it reaches a first test deployment, then production;
5. it is maintained.

People decide at every step, and automations can hook onto each step and its transitions.

It is **not** another IDE: write code in the editor and agent you prefer, and Rihmasto captures that
work's specs, tests and conventions, aligns them with its contract, and hands context back. It does
not replace your CI, monitoring or ticketing either. It reads them, runs its own gate and checks, and
keeps the decisions and the evidence. See [D-0023](decisions/D-0023-what-rihmasto-is-and-is-not.md).

## Quick start

You need Python 3.11 or later and git. The demo needs no Gnomon, no model keys and no network.

```bash
git clone <repository URL> rihmasto && cd rihmasto
pip install -e .
rihmasto demo && rihmasto-cockpit --home var/demo
```

- Install into a virtual environment of its own (`python -m venv .venv`, then activate it).
  Rihmasto's `mcp` package would shadow the MCP Python SDK of the same name.
- `rihmasto demo` builds a demo factory home in `var/demo` in well under a minute.
- `rihmasto-cockpit` prints a one-use sign-in link on 127.0.0.1. Open it once and pick a persona.
- The command is `rihmasto`; `rihma` stays as an alias. Without installing, run
  `python -m kernel.cli demo` and `python -m cockpit.server --home var/demo` from the checkout.
- `rihmasto doctor` shows what this machine has: Python, Gnomon, git, docker, the lanes and the
  model keys. It exits 1 until Gnomon is installed; the demo does not need Gnomon.

For a first real project, read [docs/getting-started.md](docs/getting-started.md).

## Use only what you need

Rihmasto is a set of modules. Use one small part, such as *spec only* (a need becomes a confirmed spec
and a hashed contract, nothing is built) or *gate my code* (the gate judges changes in your own
repository, and you merge), or the whole factory, and change it later with `rihmasto modules set` or in
the cockpit's Settings. Every way records the same trail in the ledger.
[docs/guides/use-only-what-you-need.md](docs/guides/use-only-what-you-need.md) walks through each preset.

## What you see in the demo

The demo is the real kernel with a scripted model and a scripted builder standing in for Gnomon.
Every decision in it is made by a fake person named `demo-*`. It holds:

- **Equipment loans**, waiting on the panel's blocking questions;
- **Shipment webhook to the stock system**, built through the gate, escalated once, retried and
  released on the local preview road with a capability pack;
- **Access review check**, an ops agent whose escalation waits for a person, with the gate's
  objections;
- a **concept** that waits for a business owner.

[docs/demo.md](docs/demo.md) walks through it screen by screen.

## How it works

```text
a need: an idea, a written spec, a folder, or a signal
  |
  v
material map ........ any folder is scanned by rule: each file read, summarised, listed or skipped
  |                   with why (secrets never read); you see it before anything is sent, and a
  |                   confidential project stays on local models (docs/guides/inputs.md)
  v
intake panel ........ business, end user, IT and security, operations and delivery each ask
  |                   the questions that change what gets built; disagreements stay side by side
  v
spec ................ requirements with given / when / then criteria; the kernel sets ids and
  |                   provenance (who confirmed what)
  v
hashed contract ..... compiled from the spec with no model; its hash is its revision; every
  |                   criterion needs a test named by its id
  v
Gnomon builder cells  each task runs as a Rihma agent in a Gnomon cell, in a clean lane, inside
  |                   its write scope
  v
gate ................ the kernel runs the tests itself, traces each criterion to a test, checks
  |                   that the tests fail first, and asks an independent verifier from another
  |                   model family; holdout scenarios the builder never sees run against the
  |                   delivered service
  v
delivery ............ only on paved roads IT configured; production waits on IT's deploy gate,
  |                   then shadow, canary and rollback
  v
change loop ......... triage sends each change back to its stage; approvals that rest on a
                      changed requirement go stale; recurring lessons become checks a person
                      accepts
```

People decide in the cockpit's **Inbox**, and every decision names a person and a persona. Models
propose. The kernel, standard-library Python with no model in it, decides whether work is accepted,
and appends every transition to a hash-chained ledger.
[docs/how-it-works.md](docs/how-it-works.md) explains each step.

## The capability layer

Rihmasto's product is agentic capability: apps and services, integrations, agents and assistants,
model pipelines, tuned harnesses, and ops agents that do a job and prove it.

- **Capability packs.** One manifest per release, pinned by hash: the contract and product
  revisions, the artifacts, the models that built and judged it, and every criterion with its
  evidence. A changed hash means a new version. A pack is valid only while its acceptance holds,
  and it says what it lacks (no SBOM, not signed). Command: `rihmasto pack`.
- **Evidence packs.** A zip for a reviewer: the pack, contract, decisions, gates, holdout scores,
  Gnomon runs and the ledger with its chain check. Its verdict is *attestable*, *chain broken* or
  *insufficient evidence*, never "compliant". Command: `rihmasto evidence`.
- **The autonomy ladder.** 1 answer, 2 suggest, 3 prepare, 4 deliver. A business owner, IT or
  compliance sets the cap, with a reason; the kernel refuses any step above it. Command:
  `rihmasto autonomy set`.

Guides: [packs and evidence](docs/guides/packs-and-evidence.md), [autonomy](docs/guides/autonomy.md),
[the capability layer](docs/capability-layer.md).

## Work profiles

A work profile shapes the panel's questions, the spec guidance and the cockpit around the same
governance core ([docs/guides/profiles.md](docs/guides/profiles.md)).

| Profile | For | Status |
|---|---|---|
| `web_service` | a web app or HTTP service | ready |
| `integration` | moving data or events between systems | ready |
| `mobile_prototype` | a phone-first prototype | preview |
| `ml_pipeline` | training, evaluating or serving a model | preview |
| `agentic_workflow` | an agent, assistant or tool-using workflow | preview |
| `harness_engineering` | building or tuning an agent harness | preview |
| `ops_agent` | a job done and proven, such as an access review | preview |
| `automation` | a scheduled or triggered job with no screens, one workflow or one agentic capability | ready |

Every profile but `automation` builds on the one paved-road template today, a standard-library Python HTTP
service; `automation` has its own, one image with several faces ([small capabilities](docs/guides/small-capabilities.md)).
*Preview* means the intake, spec and checks are shaped for the work, and its own template is still
to come.

## Integrations

Rihmasto reaches outside systems through Gnomon, as governed tool calls
([D-0015](decisions/D-0015-integrations-through-gnomon.md)). Gnomon runs a system's MCP server or
API tools in an integration lane, checks each call against policy, asks before a write, and records
the call in its audit trail. Decisions stay in Rihmasto's Inbox. That design is in
[docs/integrations.md](docs/integrations.md); the connectors are not built yet.

What connects today:

- **Security scanners:** SARIF 2.1.0 from any scanner feeds the security gate
  (`rihmasto security ingest`). A person accepts a risk, with a reason and an expiry date.
- **Website chats:** an embed files end-user feedback as a change, or a need as a signal
  ([docs/guides/embeds.md](docs/guides/embeds.md)).
- **Your own coding agent:** an MCP server over stdio, with reads and proposals, never decisions
  ([docs/mcp.md](docs/mcp.md)).
- **Signals:** from the command line, the cockpit's JSON API or the MCP server.
- **Models:** any OpenAI-compatible endpoint, per role, in [kernel/routing.json](kernel/routing.json)
  or in your own `kernel/routing.local.json`, which is merged over it.

## Portability

Each release can carry a capability pack that pins it by hash. Today a release can be exported as
an offline bundle with `SHA256SUMS` and, when cosign is installed, a signature (from Python; no
command yet). The docker road builds an image, and the Azure Container Apps package is rendered
and validated.
The plan to run a release on any OCI runtime and expose its agents over open protocols is in
[docs/portability.md](docs/portability.md); it is a design, not built yet.

The factory's own cells are harness agnostic: Gnomon runs them by default and enforces the rules
during a run, and a team can run them with Claude Code, Codex, OpenCode or a command it names
instead, approved by IT with the version pinned. Every rule is then checked after the run, and the
evidence says which assurance applied (`rihmasto runners`,
[docs/guides/harnesses.md](docs/guides/harnesses.md)).

## Status

Version **1.0.0.dev0**, a development release. Commands, file formats and the cockpit's API may
still change before 1.0.0.

**Works today, covered by the test suite:**
- the chain from intake to delivery on the local preview road: the panel, the spec rules, the
  compiled contract, the gate, holdouts in custody, the change loop and the ledger;
- the command line, the demo, the cockpit and the MCP server;
- the `web_service`, `integration` and `automation` profiles; a small capability is reached over MCP,
  an OpenAI-compatible endpoint, a website chat or HTTP, behind its pack guard (`rihmasto capability serve`);
- the security gate for SARIF findings, capability packs, evidence packs, the autonomy ladder,
  signals, concepts and embeds;
- delegated decisions, an autopilot bound to a sandbox, and Track, which says whether a project stays
  on track against its approved plan, with human checkpoints
  ([docs/guides/autopilot-and-tracking.md](docs/guides/autopilot-and-tracking.md));
- automations per project or across them: a schedule, a ledger event, an inbound webhook or new commits
  trigger an allow-listed action with its owner's rights, with guards, limits and a circuit breaker
  (`rihmasto automations`, the cockpit's Automations page,
  [docs/guides/automations.md](docs/guides/automations.md));
- outputs per audience, chosen by a person and built from the records: a web app with sign-in, a
  container, an OpenAPI description, a delivery report, an evidence pack and the source
  (`rihmasto output`, the cockpit's Outputs view; the MCP server output is planned,
  [docs/guides/outputs.md](docs/guides/outputs.md));
- access control, phase A: in enforced mode a decision is signed by the identity your organisation's
  sign-in verified, through IT's identity-aware proxy, as a persona an IT-owned access file grants on
  that project ([docs/guides/access.md](docs/guides/access.md)).

**Preview:**
- five of the eight profiles, which run on the web-service template;
- the docker road, which the tests run against a fake docker CLI, not a daemon;
- the Azure Container Apps road, rendered and validated but never deployed;
- recipes, sandbox trials, measured fit and offline bundles, which have no command or screen yet
  ([docs/guides/recipes-and-fit.md](docs/guides/recipes-and-fit.md));
- the capability gateway, run as `python -m gateway.server` ([docs/guides/gateway.md](docs/guides/gateway.md)).

**Designed, not built:**
- integrations through Gnomon ([docs/integrations.md](docs/integrations.md));
- Rihmasto's own security scanning and red teaming ([D-0014](decisions/D-0014-security-is-native.md));
- the portability exports ([docs/portability.md](docs/portability.md));
- signed and anchored ledger heads, signed packs and SBOMs.

**Know before you rely on it:**
- Without an access file the cockpit is for one operator: it listens on 127.0.0.1 only, whoever
  holds the session can pick any persona, and it says so ("single operator: personas are
  self-declared"). For a team, IT puts an identity-aware proxy in front of it and enforces access
  ([docs/guides/access.md](docs/guides/access.md)). Provisioning through SCIM and separation of
  duties are not built yet.
- Builder cells have run on Linux. On Windows the kernel, the tests, the demo and the cockpit run;
  run cells in WSL2 or a container.
- The gate runs a Python unittest suite. An adopted repository's other suites (pytest, npm, Go
  and others) are characterised once at adoption when their tool is installed, but the gate does
  not run them, and no paved road runs an adopted repository yet.
- Cloud cost reads "not measured" until someone fills the per-token prices in
  [kernel/prices.json](kernel/prices.json).
- The shipped [kernel/routing.json](kernel/routing.json) points at a local OpenAI-compatible
  server on 127.0.0.1 and a hosted endpoint. Put your own machine's routing in
  `kernel/routing.local.json` (gitignored, merged over the shipped file); see
  [docs/guides/local-models.md](docs/guides/local-models.md).
- File-format ids such as `gnomonfactory.contract/1` keep the project's working name, so existing
  files stay valid.

## Documentation

[docs/README.md](docs/README.md) lists every guide, grouped by reader. To start:

- [docs/getting-started.md](docs/getting-started.md): install, the demo, models, a first real project.
- [docs/how-it-works.md](docs/how-it-works.md): the chain step by step, and who decides what.
- [docs/cockpit.md](docs/cockpit.md): the cockpit, its lenses and its API.
- [docs/brownfield.md](docs/brownfield.md): existing solutions, your own terminal, security findings.
- [docs/guides/ide-and-rihmasto.md](docs/guides/ide-and-rihmasto.md): your IDE and Rihmasto, where
  the line is; your CLAUDE.md, AGENTS.md, Cursor rules and skills read and followed; MCP for Cursor
  and Claude Code.
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
