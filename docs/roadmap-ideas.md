# Ideas for the road ahead

These ideas come from research of agent-observability and factory tools, and from the owner's earlier
factory experiments. They are inspiration only: Rihma re-implements what it adopts natively and
depends on nothing but Gnomon. **Done** marks what Rihma has since built.

| # | Idea | Serves | Lands in | Effort | State |
|---|---|---|---|---|---|
| 1 | An evidence pack as an attestation (*attestable*, *chain broken* or *insufficient evidence*, never "compliant"), with a control table keyed by public control ids | compliance | evidence pack | M | **Done** (`kernel/evidence_pack.py`) |
| 2 | Coverage before absence: every export says what it cannot produce, and every event type says whether anything emits it yet | compliance, insight | read models | S | partly |
| 3 | Data placement and classification: which tier (local or hosted) saw which data; confidential data never routed to hosted models | compliance, IT | gate, pack | M | not yet |
| 4 | A security pre-check gate: negative auth sweep, dependency audit, secret scan of history, response headers; findings cite public control ids | IT, compliance | gate, evidence | M | not yet |
| 5 | SLOs and error budgets declared in the pack; a burn rate opens an incident card | operations | pack, widget | M | probes and canary only |
| 6 | Integration health per connector: last success, error rate, credential expiry, API drift | IT, operations | read model, widget | M | not yet |
| 7 | A restore-verification receipt for a pack: digests, a credential scan with reasons, explicit limits | IT, compliance | pack | S | partly |
| 8 | Tester environments as a paved road: SSO at the edge, invitable roles, tester data kept across updates, a real-data scan before teardown | end-user tester, IT | road, gate | M | Try it and embeds only |
| 9 | Push decisions to Teams, Slack or e-mail with a deep link; the decision is still signed in the cockpit | business, operations | integration | M | not yet |
| 10 | A GitHub and ticket bridge: namespaced external ids, a ticket becomes a signal | delivery, operations | integration | M–L | not yet |
| 11 | Business outcome KPIs in the pack: baseline, owner, source, review date; "not measured" until a feed exists | business | pack, widget | M | not yet |
| 12 | A customer's re-delivered requirements become a scoped change: new, restated, withdrawn, unchanged | business, concept | change loop | M | partly |
| 13 | Conservation of bans: a negative requirement dropped or inverted on its way from spec to tasks blocks the run | concept, delivery | gate | S–M | not yet |
| 14 | Guardrail-clause mutants: each policy clause needs a violating mutant that a check catches | compliance, developer | gate | M | fail-first per criterion only |
| 15 | The customer's own ops guide and runbook, filled in, with a recovery script tested from another directory | operations, IT | evidence, pack | M | not yet |
| 16 | Retention enforced, not merely intended: classes per record kind, a deletion job, a tombstone in the chain | compliance | kernel | M | not yet |
| 17 | OpenTelemetry GenAI ingest and export for deployed agents, feeding drift and eval monitoring | operations, insight | integration | M–L | not yet |
| 18 | A read-only brief and MCP surface for developers' own agents | developer | integration | S–M | **Done** (MCP server) |
| 19 | Metric provenance (observed, derived, proxy) with a denominator on every number, and a "this looks wrong" action that files a change | insight | cockpit | S | in the cockpit redesign |
| 20 | A Finnish cockpit through a translation pass, with run content left untranslated | business, testers | cockpit | S–M | the embed widget speaks Finnish |

## An event schema to adopt: `rihma.event/1`

Native to Rihma, with names aligned to OpenTelemetry's GenAI conventions where they fit. Pin the
semconv version when adopting.

- **Envelope:** `spec_version`, `event_id`, `event_type`, `occurred_at`, `observed_at`, `seq`, `payload_hash`, `prev_hash`.
  The chain is made at the single writer (the kernel), never at the edge.
- **stream:** `factory_id`, `project_id`, `pack_id`, `pack_version`, `pack_digest`.
- **actor:** `kind` (person, agent, kernel or external), `id`, `persona`, `role`, `model`.
- **correlation:** `run_id`, `task_id`, `card_id`, `release_id`, `incident_id`, `trace_id`, `span_id`, `external_refs[]`.
- **deployment:** `environment`, `road`, `slot`, `revision`, `artifact_digest`.
- **classification:** `sensitivity`, `content_capture`, `retention_class`, `data_placement`, `personal_data`.
- **measure:** `provenance` (observed, derived, proxy or not_measured), `value`, `unit`, `denominator`.
- **gen_ai:** `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`,
  `gen_ai.usage.output_tokens`, `gen_ai.agent.name`, `gen_ai.tool.name`, plus `rihma.cost.*`.

## Lessons to keep

- **A record that blocks nothing protects nothing.** Wire every check into a gate.
- **Gates must run the product, not read files about it.**
- **A file ledger that "verifies clean" after an edit proves little.** Say what a verification attests.
- **Numbers on event types nothing emits, or with mismatched denominators, mislead.**
  - "100% recovery" that is only co-occurrence is an example.
  - So is "governance 0%" that measures a missing file.
- **Keep customer material out of the reusable factory.**
- **One source of truth:** no branch sprawl, and no hand-maintained status tables that drift.
