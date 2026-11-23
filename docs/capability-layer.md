# Rihma as an agentic capability factory

Rihma started as a software factory: a request goes in, verified software comes out, and feedback from
production loops back. Its product is wider than software. It is **agentic capability**:

- a web app, service or integration;
- an agent or assistant, embedded in an app or standalone for a process;
- a model or data pipeline with its evals;
- a developer capability, such as a tuned harness or a coding-agent setup;
- an **ops agent** that does a job and proves it: a compliance check, a security scan, a log analysis,
  a maintenance report.

Every one goes through the same governed chain: intake, then spec, then the hashed contract, then
Gnomon cells in lanes, then the gate, then delivery, then the change loop. This page explains the
pieces that make the chain work for capabilities rather than only for software.

## The pieces

| Piece | What it is | Where |
|---|---|---|
| **Work profile** | The kind of work: web service, integration, mobile prototype, ML or data pipeline, agent or assistant, harness engineering, ops agent. It shapes the panel's questions, the spec guidance, the roads and the cockpit, around the same governance core. Each profile names its **deliverable**: a product, a capability pack, or a report. | `kernel/profiles.py` |
| **Delivery square** | Needs arrive as **signals** from the operation: chats, data feeds, monitoring, meetings, a website chat. A signal about an existing project becomes a change there. A new need becomes a **concept** that a business owner or product owner validates into a project. | `kernel/signals.py` |
| **Capability pack** | One manifest per release, pinned by hash. It holds the contract and product revisions, the artifacts, the models and harness surfaces that built and judged it, and its acceptance: criteria with evidence, holdout scores but never the scenarios. *Pack version = behaviour version*: if any hash changes, the version changes. It is valid only while its acceptance holds, and it never claims a signature or SBOM it does not have. | `kernel/packs.py` |
| **Evidence pack** | An exportable bundle for review: the pack, contract, decisions, gates, holdout scores, Gnomon runs, and the ledger with its chain check. Its attestation is *attestable*, *chain broken* or *insufficient evidence*, never "compliant", with a control table that also says what it cannot evidence. | `kernel/evidence_pack.py` |
| **Autonomy ladder** | 1 answer, 2 suggest, 3 prepare (build and trial in a sandbox lane), 4 deliver (staging and production, with a named approver). A person's policy caps it for the factory and may lower it per project. The kernel enforces it. | `kernel/autonomy.py` |
| **Insight engine and updates inbox** | An observation from outside (a model release, a CVE, eval drift, a compliance deadline, low use) is rendered three ways: JSON for a developer, a sentence for an expert, a proposal for a business reader. Within the cap it opens an `update` card: trial, decline or defer, by a named person. Nothing updates itself. | `kernel/observations.py` |
| **Capability catalogue** | Every capability with its state (in use, pilot, trying, building, shaping, proposed), its profile, deliverable and pack validity. | `kernel/dashboard.py` (`catalogue`) |
| **Embeds** | A chat a website includes with one script tag. It has one capability: end-user feedback becomes a change card, or a business need becomes a signal. It works only from its allowed origins with its key, is rate limited, and sees nothing of the project's records. | `kernel/embeds.py`, `embed/` |
| **Headless access** | The same logic without the cockpit: the CLI, the JSON API, and an MCP server for developers' own coding agents. They allow reads and proposals; decisions stay with people. | `kernel/cli.py`, `cockpit/server.py`, `mcp/` |
| **Assistant** | It answers "where is", explains, and answers about runs from the records. It proposes actions, including reshaping the cockpit within fixed boundaries (layout operations, theme tokens) and making a website chat. A person confirms each one. | `kernel/assistant.py` |

## The change loop, for capabilities

Something changes (a new model, a CVE, a new task, eval drift). The factory re-measures and proposes
the change with its eval delta. A named approver decides. A new pack version results.

Rihma's existing loop already carries most of this: change cards, stale approvals, rebuild and
redeliver, lessons that become default checks. The insight engine adds the outside triggers. A
capability pinned by hash does not change behaviour unless someone changes it through this loop.

## Who sees what

| Viewpoint | Their question | In the cockpit |
|---|---|---|
| Business | Which capabilities do we have, what is coming, what needs me? | The catalogue, the square, decisions |
| Concept | What do we assume, and what does the plan say? | Questions, assumptions, plan |
| Delivery | How is the run going, and why did something fail? | The live cell, timeline, gate trend |
| Operations and IT | What runs, is it healthy, and what changed outside? | Health, releases, updates |
| Compliance | What ran, which versions, who approved, and was it checked? | The evidence pack, autonomy, ledger |
| Insight | How does the factory itself perform? | Gate trend, models, coverage |

## Not built yet (honest list)

- **Runtime declaration.** Product templates do not yet declare the runtime models an agentic product
  uses. A pack says so ("runtime: not declared").
- **Signing and SBOM.** Packs are not signed and no SBOM is generated. A pack says so.
- **Trials.** A trial approved on an update card is recorded. The re-measure with the new model is an
  operator step in v1.
- **Templates.** Dedicated templates for mobile, ML, agent, harness and ops-agent profiles. Today they
  run on the web-service template, and each profile says so (`status: preview`).
- **Fit measurement.** Measured fit across hardware, runtime, model and task (throughput, latency,
  memory and quality per workload class) is a natural extension of the per-model reliability Rihma
  already computes from its ledgers.
