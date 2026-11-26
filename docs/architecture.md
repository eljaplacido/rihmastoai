# Architecture: how the parts relate

The picture in [assets/architecture.svg](assets/architecture.svg) and the Mermaid diagram below show
the same thing: who reaches Rihmasto, what decides, where things are kept, what reads them, which
agents and models do the work, and where the result goes. This page then walks through each layer and
names the code behind it.

![Rihmasto's layers: where people and agents meet it, the kernel, the knowledge and data layers, the agent layer and the destinations](assets/architecture.svg)

## The diagram as text

GitHub draws this diagram from the text. Every box names a part you can find in the repository.

```mermaid
flowchart TB
  subgraph meet["Where people and agents meet it"]
    cockpit["Cockpit (web UI)<br/>Inbox, views per persona"]
    ask["Ask Rihma<br/>chat in every view"]
    cli["Command line<br/>rihmasto"]
    mcp["MCP server<br/>your IDE agent"]
    bells["Doorbells<br/>webhooks, website chats, signals"]
  end

  subgraph kernel["Rihmasto kernel: standard-library Python, no model"]
    direction LR
    intake["Material and intake"] --> spec["Spec"] --> contract["Contract<br/>hashed"] --> plan["Plan"]
    plan --> cells["Builder cells"] --> gate["Gate"] --> deliver["Delivery"] --> operate["Operate"]
    operate -. "change loop" .-> spec
    inbox["Inbox: people decide"]
    access["Access: solo or team"]
    autonomy["Autonomy cap and posture"]
    health["Checks, automations, self-healing"]
    existing["Adopt, attach, assess, align"]
  end

  subgraph data["Data layer: files in the factory home"]
    ledger[("ledger.jsonl<br/>hash-chained")]
    canon[("canon, spec.json,<br/>contract.json")]
    repo[("repo.git and lanes")]
    custody[("holdout custody")]
  end

  subgraph knowledge["Knowledge layer: read models"]
    graph["Knowledge graph"]
    context["Context packs"]
    insights["Insights and Review"]
    structure["Structure map"]
  end

  subgraph agents["Agent layer"]
    gnomon["Gnomon harness<br/>roles, write scope, sandbox, audit"]
    others["Other harnesses (opt-in)<br/>Claude Code, Codex, OpenCode"]
    models["Models<br/>local or hosted, OpenAI-compatible"]
  end

  subgraph roads["Destinations"]
    preview["Local preview (real)"]
    standins["Docker, Cloud Run (stand-ins)"]
    azure["Azure (preview)"]
  end

  meet --> kernel
  kernel -- "appends every transition" --> data
  data --> knowledge
  knowledge -- "what each agent is given" --> agents
  kernel -- "every model call" --> gnomon
  gnomon --> models
  others --> models
  deliver --> roads
  roads -- "probes, feedback, incidents" --> operate
```

## The layers

### Where people and agents meet it

Five ways in, one set of rules behind them. Each feature works in the cockpit and through Ask Rihma,
and most through the command line too.

| Part | What it is | Code |
|---|---|---|
| Cockpit | The web UI: the Inbox, a project's views grouped into five capsules (Now, Build, Run, Govern, Agents), Settings. Binds to 127.0.0.1 only; a one-use sign-in link. | `cockpit/server.py`, `cockpit/*_routes.py`, `cockpit/static/` |
| Ask Rihma | The chat in every view. It answers from the records by rule where it can, proposes actions you confirm, and offers **Take me there**. It never writes on its own. | `kernel/assistant*.py`, `kernel/walkthrough*.py`, `kernel/journey*.py` |
| Command line | `rihmasto <command>`: every action, JSON out, each write signed with `--person` and `--persona`. | `kernel/cli.py`, `kernel/*_cli.py` |
| MCP server | Your own coding agent (Claude Code, Cursor, Codex, OpenCode) reads the contract and files proposals; it decides nothing. | `mcp/server.py`, [mcp.md](mcp.md) |
| Doorbells | Signed webhooks in, website chats, signals on the delivery square. A ring becomes a signal or a change proposal, never a decision. | `kernel/hooks.py`, `embed/`, `kernel/signals.py` |

### The Rihmasto kernel

The kernel is plain Python from the standard library, with no model in it. It decides by rule whether
work is accepted, writes every transition to the ledger, and stops at each decision that belongs to a
person.

- **The chain.** Material and intake (`kernel/material*.py`, `kernel/intake.py`), the spec
  (`kernel/spec.py`), the contract compiled with no model and pinned by its hash (`kernel/compile.py`),
  the plan and the holdouts (`kernel/plan.py`, `kernel/holdouts.py`, `kernel/custody.py`), builder
  cells (`kernel/dispatch.py`, `kernel/lanes.py`), the gate (`kernel/gate.py`), delivery on paved
  roads (`kernel/deliver.py`, `kernel/roads*.py`) and operation (`kernel/operate.py`). The change loop
  (`kernel/change.py`) sends feedback, incidents and drift back to the step they belong to.
- **People decide.** Inbox cards (`kernel/canon.py`) wait for a named person with a persona that may
  decide them. Access is solo by default (`kernel/solo.py`), a team when you need one
  (`kernel/team.py`), or IT's access file behind an identity-aware proxy (`kernel/access*.py`).
- **How far it goes alone.** The autonomy cap and delegation (`kernel/autonomy.py`,
  `kernel/delegation.py`), the autopilot in a sandbox (`kernel/autopilot.py`) and postures from
  prototype to regulated (`kernel/posture*.py`).
- **Keeping it healthy.** Checks (`kernel/checks/`), automations with guards and a circuit breaker
  (`kernel/automations*.py`), incidents and self-healing remedies (`kernel/incidents.py`,
  `kernel/heal_*.py`), Review (`kernel/review*.py`) and a recorded console (`kernel/console*.py`).
- **Existing repositories.** Adopt (`kernel/adopt*.py`) or attach (`kernel/attach.py`), assess
  (`kernel/assess*.py`), align the repository's own specs and tests (`kernel/alignment*.py`), and
  watch the upstream.

### The data layer

Plain files under the factory home (`--home`, else `$RIHMASTO_HOME`, else `var/` in the checkout).
There is no database and no service to run. Back the home up like any folder.

| Store | Where | What holds it together |
|---|---|---|
| The ledger | `projects/<id>/ledger.jsonl`, one per project, and the factory's own | One JSON record a line, each with the hash of the one before it (`kernel/ledger.py`, `kernel/ledgerstore.py`). Appended under a lock; a chain check finds an edit to part of it. |
| The canon | `projects/<id>/canon/` | The brief, questions, answers, assumptions with due dates, decisions and Inbox cards (`kernel/canon.py`). |
| Spec and contract | `projects/<id>/spec.json`, `contract.json`, `checkplan.json`, `tasks.json` | The contract's revision is the hash of its content (`tools/contract_check.py`). |
| The product | `projects/<id>/repo.git`, and lanes under `$GF_LANES` | Git. A cell works in a lane of its own and merges only after the gate. |
| Holdout custody | `holdouts/<id>/` | Outside every project folder and lane, so no builder ever reads its own exam. |
| Releases and operations | `projects/<id>/releases/`, `ops/` | Capability packs pinned by hash, probe results, incidents. |
| Secrets | never in the home | Keys stay in environment variables named in the routing; deploy packages carry references, never values. |

The Data and context page shows every store with its size, verifies every ledger's chain, says how
long each store is kept, and proposes a clean-up that a person signs
([context and data](guides/context-and-data.md)).

### The knowledge layer

Read models built from the records, never a second source of truth. Each can be rebuilt from the data
layer at any time.

- **The knowledge graph** (`kernel/graph*.py`, `kernel/ontology.json`): requirements, criteria, tests,
  tasks, decisions, changes, releases and agent runs as typed nodes and links. It answers "what does
  this rest on" and "what rests on this", finds what is missing, and powers the Knowledge graph view
  ([guide](guides/knowledge-graph.md), [design and ontology](knowledge-graph.md)).
- **Context packs** (`kernel/context_*.py`, `kernel/agent_context*.py`): what each Rihma agent is given
  right now, part by part, with what was compressed or left out and why, and the compression audit.
- **Insights and Review** (`kernel/insights/`, `kernel/review*.py`): health, security, QA, governance
  and usage counted from the records; anything with nothing behind it reads **not measured**, never zero.
- **The structure map** (`kernel/repo_structure.py`, `kernel/repo_specs.py`, `kernel/repo_suites.py`):
  an existing repository's own specs (spec-kit, Kiro, BMAD, Gherkin), ADRs, API contracts and tests,
  found by rule, which alignment then proposes for the contract.

### The agent layer

- **Gnomon is the glue.** By default every model call goes through [Gnomon](https://github.com/eljaplacido/gnomonharness),
  an open agent harness. Gnomon enforces each agent's tools, write scope and sandbox during the run
  and keeps an audit trail. The kernel reaches it only as a command (`kernel/model.py`,
  `kernel/lanes.py`, `.gnomon/`). Any model behind any OpenAI-compatible endpoint works under the same
  structure of specs, contracts, tests and verification.
- **The Rihma agents** are roles in [kernel/routing.json](../kernel/routing.json): the analyst (intake
  and spec), the holdout author, the builder, the verifier (always another model family than the
  builder) and the assistant (Ask Rihma).
- **Other harnesses** (Claude Code, Codex, OpenCode or a command IT approves) can run cells, opt-in,
  with their version pinned. Their rules are checked after the run, not enforced during it
  ([harnesses](guides/harnesses.md)).
- **Your coding agent as the model.** With no API key, Claude Code, Codex or OpenCode can answer the
  text roles on your own login. Each call is recorded in Rihmasto's ledger as run by that agent, with no
  Gnomon audit trail ([guide](guides/harness-models.md)).

### Destinations

Releases go only to paved roads IT configured (`kernel/roads*.py`), each with its deploy gate. The
local preview on your own machine runs for real; the docker and Google Cloud Run roads are tested only
against stand-ins; Azure Container Apps is rendered but never deployed
([deploying](guides/deploying.md), [destinations](guides/destinations.md)). Probes, incidents and
feedback come back through the change loop.

## How a decision travels

1. Something arrives: a sentence in Shape it in chat, a folder, a signal, a ring on a webhook, a
   proposal from your IDE agent over MCP.
2. The kernel records it in the project's ledger and works out the next step by rule.
3. Where a model is needed, the kernel builds the agent's context pack and calls Gnomon, which runs the
   role on the routed model inside its write scope and sandbox.
4. What the model produced is a proposal. The kernel checks it by rule (the gate runs the tests itself,
   checks that each criterion has a test that failed first, keeps the holdouts out of reach and asks a
   verifier from another family).
5. When a person must decide, an Inbox card waits for a person with a persona that may decide it. The
   decision is a ledger record that names them.
6. The knowledge layer picks the new records up the next time a view or a question reads them.

## Read next

- [How it works](how-it-works.md): each step of the chain in detail.
- [The scenarios](scenarios/README.md): what happens under the hood when you start blank, bring an
  existing project, fix one that lacks governance, or build automations.
- [Configure with your agents](guides/configure-your-agents.md): Claude Code, Cursor, Codex and
  OpenCode through MCP and hooks.
