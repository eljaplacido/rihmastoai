# Insights: health to token usage, from the records

Insights shows how the projects and their agentic work are doing, in seven dimensions: **health,
compliance, governance, security, context drift, QA and usage**. Open **Insights** in the sidebar for the
whole factory or one project, or a project's **Insights** tab. The same figures are on the command line
(`rihmasto insights`) and can be exported to your own observability tools. The page, the tab and the
Insight widget come with the **Build and gate** module ([use only what you need](use-only-what-you-need.md));
the command works whatever modules are on.

Three rules hold everywhere:

- **Every number is counted from the records** (the project ledgers, the canons, the projects' own files and
  Gnomon's own audit trails). Nothing is estimated, sampled or modelled.
- **"Not measured" is never zero.** A figure with no record behind it says *not measured*, why, and how to get
  it measured. An export leaves its value empty and gives it no data point.
- **Every tile and chart has one plain line**, computed by a rule from its own figures: a change against the
  window before ("Builder prompt tokens doubled against the week before (24,000 against 12,000): 3 tasks
  needed 5 or more rounds"), the largest item of a list with its share, the oldest card waiting. No model
  writes these lines (`kernel/insights/lines.py`).

## Using the page

One row above everything it scopes:

- **Dimension**: health, compliance, governance, security, context drift, QA or usage.
- **Window**: the last 24 hours (hourly columns), 7 days or 30 days (daily), or all records. A tile compares
  with the window of the same length before it; "all" has nothing before it.
- **Scope**: the whole factory or one project (a project's own tab is fixed to it).

Then the stat tiles (value, the comparison, a status with its icon and word where the figure means good or
bad, the line, and **Open the records** where there is one place to look), the charts (each with a table
view: the button beside its title), and **Not measured here**: what this dimension cannot count in this
factory, why, and how to get it counted.

**Pin to Home** on any tile adds it to your Home layout for the lens you are in, as an *Insight* widget.
It is saved with your layout and can be resized, moved or removed like any widget.

## What each dimension counts, and where from

| Dimension | Figures | Records |
|---|---|---|
| Health | projects at risk or off track; the longest time without a recorded step; failures in the window; each enabled check's last result (failed, passed, not measured); probes of what runs | `kernel.status.health`; each ledger's last record; `apparatus_failure`, `release_failed`, `probe_failed`, `gnomon_run_not_ingested`, `security_scan_refused`, `upstream_sync_failed`, `embed_triage_failed`, `merge_rejected`; each enabled check's last `check_ran` (`kernel.checks.last_results`); `ops/tick.json` and `probed` |
| Compliance | posture kept; what a posture requires that is missing (a scan, a red-team layer, an evidence pack); criteria proven; required scans present; accepted risks in force and their days left; overdue assumptions | `kernel.posture.track_posture`, `kernel.posture_rules`; `kernel.status.evidence`; `security/*.json`, `security/acceptances.json`, `risk_acceptance_expired`; the canon's assumptions |
| Governance | decisions, by a person, by delegation (DL-n) or by an automation; share decided by delegation; time to decide (card created to decided, median); cards waiting and their age; autonomy holds; autonomy cap hits; delegations in force; ledgers whose hash chain verifies | `canon/decisions.json` and the cards; `go_ahead_asked`; `autonomy_capped`; `delegations.json`; `kernel.ledger.verify` against the cockpit's kept head |
| Security | open findings and those at error; gate blocks; open findings that name a secret, credential, password, key or token; red-team findings; confidential projects, refused hosted calls and roles worked by rule | each tool's latest SARIF scan per scope (`kernel.security.findings`); `security_gate`; `security_scan` counts over time; the red team's own tool name; `confidential_refused`, `confidential_by_rule` |
| Context drift | merges since the spec was written; requirements without a verified or held-out criterion; contract revisions since the last release; repository drift; canon contradictions; assumptions settled; runs that trimmed their context, and the largest prompt against the window | `spec_written`, `merged`; `kernel.status.evidence`; `contract_compiled` after `release_started`; the drift of each project's latest `alignment_scanned`, with `alignment_accepted` and `alignment_rejected`; `kernel.insight.alignment`; each `gnomon_run`'s context window and trims, and the `model_call` prompt sizes in its trail |
| QA | gate pass rate; rounds per task; first-round passes; fail-first held; verifier disagreements (the tests and the independent verifier differ); holdout pass rate; flaky reruns | `gate` verdicts and signals; `holdouts_run` and release holdout steps; `reflex_retry` |
| Usage | tokens (prompt and completion) and cloud cost, per project or task, role, model, endpoint and runner, local against hosted, over time; model runs; tool calls, and by tool; skills used; compactions; accepted skills; capability faces started | `gnomon_run` for builder cells, `model_run` for the analyst, holdout author, verifier and assistant (`kernel/model_usage.py`), and a `runner_run` another harness records; each run's own Gnomon trail `<lane>/.gnomon-audit/<session>.jsonl`; the audit kinds `tool_call`, `skill_use`, `context_mask`, `checkpoint`; `.gnomon/skills/*.md` on the product's main; `capability_served` |

Cost is priced from `kernel/prices.json` when the run is ingested. A local model costs no API money and its
tokens count as local. A run whose model has no price makes the cloud cost *not measured*, and the tile says
the priced part beside it.

## What is not measured, and how to measure it

| Not measured | Why | How |
|---|---|---|
| Tokens of a role with no run in the window | each role's run is recorded in the project's ledger when it happens (`gnomon_run` for builders, `model_run` for the others); a run outside a project (a factory-wide question to Ask Rihma) goes to the factory's own ledger | run the intake, the spec, the holdouts, a gate or Ask Rihma on the project |
| Which tools a run called | its trail is no longer in the lane (lanes keep trails across leases, not forever) | keep the lanes' `.gnomon-audit` folders, or export each trail with `gnomon audit show` |
| Proposed skills (`skills/proposed`) | a proposal waits in the lane that wrote it, and a lane names no project | review with `gnomon skill list` in the lane; an accepted skill is counted on the product's main |
| Calls to a running capability's MCP or API face | a face answers outside the ledger; the ledger records that it started, with its proof | your gateway's or the face's own metrics, in your observability tools; the capability gateway's audit counts what it routed |
| Test counts over time | the gate records each signal's verdict, not how many tests ran | your CI's own test reports |
| Which criteria changed since a release | a contract record names its revision and counts, not the criteria it changed | compare `rihmasto contract export` at each release |
| Checks, repository drift | not measured before a check enabled on Health ran, or before the repository was read on the Alignment tab | enable a check (`rihmasto checks enable`), or read the repository (`rihmasto align <pid> --scan`) |
| Background jobs started in the cockpit | they live in the cockpit's memory while it runs | the Jobs page |

## On the command line

```
rihmasto insights                              # every dimension, the whole factory, the last 7 days
rihmasto insights <pid> --dimension usage --window 30d
rihmasto insights --dimension qa --json        # the read model as JSON
```

## Exporting to your own stack

Rihmasto is the system of record for decisions and evidence, not for telemetry (D-0017). It keeps the figures
it needs to keep its own promises and hands the rest to the tools your team already runs.

```
rihmasto insights export --format json      --out insights.json
rihmasto insights export --format csv       --out insights.csv   --window 30d
rihmasto insights export <pid> --format otlp-json --out insights.otlp.json
```

In the cockpit, **Export** beside the filter row saves the same file for what is on screen. Nothing is sent
anywhere: you send the file on with your own collector or tools.

- **json**: the read models as the cockpit reads them.
- **csv**: one row per figure (each tile, and each chart's rows and series) with its unit, basis and, when it
  is not measured, why. A figure not measured has an empty value.
- **otlp-json**: the OTLP/JSON encoding. `resourceMetrics` holds one gauge per measured tile, named
  `rihmasto.insights.<dimension>.<key>`, with the scope, project and window as attributes. `resourceSpans`
  holds one span per model run in the window, named and attributed by the OpenTelemetry GenAI semantic
  conventions: `gen_ai.operation.name` (`invoke_agent`), `gen_ai.agent.name` (the role),
  `gen_ai.request.model`, `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens`, with the project,
  task, round, endpoint, runner and priced cost as `rihmasto.*` attributes. A run's record gives the time it
  was ingested, not its duration, so its span starts and ends there. A collector's `otlpjsonfile` receiver,
  or an HTTP POST of the file to your collector's `/v1/metrics` and `/v1/traces`, takes it from there.

## Asking Rihma

Ask "where do I see token usage?" or "show me the context drift" and Rihma takes you to Insights. Its picture
of the factory carries a few key figures per dimension (figures only: no project title, no insight line and
no decision's reason; with a project open, only that project's).
