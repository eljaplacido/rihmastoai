# Agent operations

The AI architect's view (FR-AOP1): how the agents perform, what they cost and what they are given, across every
project and per project, with an audit that proposes where to save.

Choose **AI architect** in the person menu. Agent operations is in the sidebar (all projects, Rihmasto's own work
included) and first in a project's **Agents** capsule. Every figure comes from the records; a figure with nothing
behind it says **not measured** and how to measure it, never zero.

## What it shows

| Part | From |
|---|---|
| Key figures: runs, tokens, cost, response time, tool calls, prompt cache share | every agent run in the ledgers: Gnomon's builder cells (`gnomon_run`), Rihma's roles (`model_run`), a coding agent through its harness |
| By role, harness and model (bars and table) | the same runs, grouped |
| Tokens over time (lines) | the runs per day (per hour over 24 hours); a period with no run is a gap |
| Role × project heatmap (one project: role × day) | the runs; a hatched cell had runs without token counts |
| Tools and their latency | Gnomon's audit trails in the lanes (`.gnomon-audit/<session>.jsonl`): calls, failures, duration when recorded |
| Harness overhead | each role's context pack: the system prompt's share; model calls per run, cached share and Gnomon's trims from the runs |
| Context packs against their budgets | the compression audit (`rihmasto context audit`), without running commands; Gnomon's `context_cost` and `metrics` evals when they ran |
| Context drift | when each role last ran, and the records written since (decisions, answers, the spec, merges, changes) |
| Agent observability hub | the figures a person recorded from the hub (Agent sessions) |

Select any figure, bar, heatmap cell or tool to see the runs behind it. The period is chosen above the figures.

Across the platform, context packs are read for the projects whose agents ran in the period (the busiest twelve).
A project's packs are kept while nothing they are built from changed (its records, the home's settings, its main):
switching the period or asking Rihma where to cut reads them again only after something changed (FR-AOP2).

## Model prices

The **Model prices** card lists every model the runs name with its price per million tokens in and out, and how
many of its runs are not priced. **Price a model** gives a model its price (or marks it as running on your own
machine: no API money); the price is kept in your home, signed and recorded (`model_price_set`), and a run
recorded without a price is priced from its tokens when it is read. Ask Rihma does the same: "set the price of
`example-large` to 3 and 15 per million tokens" or "mark `example-local` as local", for you to confirm.

## The Optimise audit

Fixed rules, no model. Each proposal says its expected saving and its basis:

- **Cut context**: a pack over its budget, a long line said twice, or the project's conventions sent to a role
  that does not need them; tokens per call times the role's runs (at most).
- **Reorder for the cache**: a part that changes often placed before parts that change less.
- **Cache a prefix**: a role that ran 3 or more times with under 20% of its input from the prompt cache while
  half or more of what it is given is a stable prefix.
- **Cheaper model**: a model the role evals score within 2 points of the role's current one, at a lower price
  (Model prices).
- **Slow tool**: a median of 2 seconds or more over 3 or more timed calls.
- **Many rounds**: a builder task that needed 3 or more rounds.

**Take me there** opens the place to make the change (the Context view, Models, the task). **File as a change**
puts it in the Inbox as a change card with its saving, signed. **Record the audit** keeps the proposals and their
savings in the ledger (`agent_ops_audited`), the project's or Rihmasto's own.

A cost saving needs priced runs: price each model on the Model prices card.

## Ask Rihma

"How much do my agents cost?", "Where can I cut tokens?", "Which tool is slow?", "Is there context drift?" are
answered by rule from the same records, with Take me there. Asked where to cut, Rihma offers to file the largest
proposal as a change and to record the audit; you confirm each. The drift answer says the harness overhead too, or
that it is not measured and how. Only questions about the agents' tokens, costs or context are answered by these
rules: "save the context of this project" or "what does the AI architect persona do" go to the model.

## API

- `GET /api/agent-ops?window=24h|7d|30d|all` and `GET /api/projects/<pid>/agent-ops` (`&context=0` skips the packs)
- `POST /api/agent-ops/audit` (`project`, `window`, signed)
- `POST /api/projects/<pid>/agent-ops/proposals/<id>/change` (signed; `_factory` for a platform-wide proposal)
- `POST /api/agent-ops/prices` (`model`, `input`, `output`, optional `cached`, or `local`; signed)

Who records, files and prices: AI architect, developer, IT, operations, compliance, product owner or business owner.
