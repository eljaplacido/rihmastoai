# Audits and evals: Gnomon's audits on your projects, and Rihma's evals of its own agents

Rihmasto sits over the projects you already have. Besides the checks and automations, it can run **Gnomon's own
capability-based audits, benchmarks and evals** on a project's repository and keep what they found. It does not
write audits of its own: it runs what Gnomon already has, headless, in the project's workspace, reads Gnomon's report
and records the result (FR-EVL1).

It can also **evaluate its own agents**: an eval set per Rihma role, run against the models you configured (or
others), so you can compare models and endpoints for each role.

## Where you find it

- **A project's Health tab, Audits & evals.** Each audit has its last result (passed, failed, or not measured with
  why), its trend over the last runs, and **Run now**. A run is a job: its log streams on the Jobs page. Below the
  list are the latest **findings**. Each one is an issue or advice, new ones are marked, and each issue has **Make it
  a change**, which files it with its evidence as a change proposal in the Inbox.
- **The Health page** lists every project's latest audits and their new issues.
- **Checks.** Every audit is also a check kind (`gnomon_security`, `gnomon_check`, ...). Enable one with a schedule
  (`every: 7d` is a weekly Gnomon audit of the repository) and Health runs it on time. An automation can run one too:
  the action `run_eval`, or the template **Weekly Gnomon audit of this repository**.
- **Insights.** Each audit has a tile in the dimension it measures (QA, Governance or Context drift). The tile shows
  its main score, its change against the window before and its last verdicts.
- **Review.** An audit that found issues its run before did not have shows under *Went wrong*: "An audit found 3 new
  issue(s): Gnomon Security posture, ...". It links to Audits & evals and can be made a change.
- **Goal help and Ask Rihma.** Say "audit this project" or "benchmark the context cost" and the plan offers to run
  the audit, schedule it as a check, or run it from a terminal. Ask Rihma may propose `run_eval`, which you confirm.
- **Models setup, On our evals.** This shows the role evals' results and offers **Compare models**.

## What each audit measures and costs

Whether each one runs here is read from this machine's Gnomon (`gnomon --help`). Gnomon 0.6.5 or later has every
command below. The three benchmarks at the end need a Gnomon source checkout (`GNOMON_SOURCE`, else
`~/src/gnomonharness-master`), and node for the two `.mjs` scripts.

| Id | What it measures | Runs | Takes | Models | Result |
|---|---|---|---|---|---|
| `security` | the surface's trust, where each role's commands run, network, allow-lists, guard hooks, audit trail health | `gnomon security --json` | seconds | none | `gnomon.security/1`: risks and advice; exit 0 no risk, 2 a risk |
| `security_test` | a model-free attack corpus through Gnomon's guard on a scratch copy (OWASP LLM Top 10) | `gnomon security test --json` | minutes | none | `gnomon.security_test/2`: cases held |
| `compliance` | which controls (EU AI Act, GDPR, OWASP LLM, ISO 42001, NIST AI RMF, ISO 27001, SOC 2, CRA, DORA) have Gnomon evidence. A mapping, never an assessment | `gnomon compliance --json` | seconds | none | `gnomon.compliance/1`: evidence, partial, gap |
| `dataflow` | every endpoint a role can reach, with host, locality and region, against the residency rule | `gnomon compliance dataflow --json` | seconds | none | `gnomon.dataflow/2` |
| `metrics` | how the agent worked: turns, tokens, tool calls, whether a check passed after the last write | `gnomon audit metrics --json` | seconds | none | `gnomon.metrics/2` |
| `audit_verify` | every audit trail re-hashed: chains intact and sealed | `gnomon audit verify` | seconds | none | text per trail; exit 1 broken or nothing to verify |
| `check` | the latest change judged by the surface: write scope, `.gnomon/` untouched, `[verify]` passes, a new test fails first | `gnomon check --base HEAD~1 --json` | minutes | none (runs the project's check) | `gnomon.check/1` |
| `eval` | the surface's pass rate on the project's own tasks (`.gnomon/trials/<spec>.toml`), or another profile, surface or harness against it | `gnomon eval --spec default --yes --json` | minutes to hours | the lane's roles (builder) | `gnomon.eval/3`: pass rate and whether it meets the spec |
| `chaos` | fault disclosure: a scripted model on 127.0.0.1 injects faults; is each announced or silent? | `gnomon chaos --json` | minutes | none | `gnomon.chaos/1` |
| `doctor` | whether this machine still runs what the surface says (each role's model listing, memory, servers) | `gnomon doctor --json` | seconds | model listings only | `gnomon.doctor/1` |
| `claim_check` | the claims in an agent's report: citations resolve, diff size and test counts match | `benchmarks/claim-check/check_claims.py` | seconds | none | claims verified, refuted or unverifiable |
| `context_cost` | the bytes on the wire for one prompt, against a local canary | `benchmarks/context-cost/measure.mjs` | minutes | none | requests and bytes |
| `degradation` | every degradation Gnomon can fall into is announced and recorded | `benchmarks/degradation-contract/contract.mjs` | seconds | none | rows complete |

The `chaos`, `context_cost` and `degradation` benchmarks measure Gnomon itself on this machine, not the project:
they run in a scratch folder. Gnomon's audit-existing and greenfield benchmarks are not offered for a project,
because they run only on their own planted corpus against a fixed local endpoint.

## Rules

- **Who.** Audits are run by a developer, IT, operations, compliance or a product owner. An audit that runs the
  project's own code (`check`, `eval`, `claim_check`) is run by a persona the console allows on the project. Every
  run is signed.
- **Confidential projects.** An audit that calls models (`eval`) on a confidential project is refused while any role
  it asks has a hosted endpoint. Nothing is sent, and the refusal is recorded.
- **What is kept.** Each run is recorded as `eval_ran`, with the verdict, a one-line summary, the scores and how many
  findings were new or resolved. It never holds a prompt or source code. The last 50 results of each audit, with
  their findings, are in the project (`evals/results.json`). A finding made a change is recorded as
  `eval_finding_changed`.
- **Not measured is never passed.** Gnomon missing, an older Gnomon, no `.gnomon/` surface, a void run or an
  undetermined eval all show as not measured, with why.

## The command line

    rihmasto evals list [<pid>]
    rihmasto evals run <pid> --eval security [--set base=HEAD~3] --person P --persona developer
    rihmasto evals history <pid> [--eval security]
    rihmasto evals findings <pid>
    rihmasto evals change <pid> <finding> --person P --persona developer
    rihmasto evals roles [--role assistant] [--model configured --model glm-5.3@go] [--for <pid>] --person P --persona it
    rihmasto evals history                      # the role evals' latest results

## Rihma's own evals of its agents

| Set | Role | A good answer |
|---|---|---|
| Intake panel questions | analyst | a few real questions on a need, distinct, each with a proposed answer and options, touching what matters |
| Spec criteria testability | analyst | criteria with given, when and then, an observable outcome, no vague words |
| Ask Rihma answers | assistant | the right place for a where-is question, the snapshot's figure for a status question, the right control for a how-to |
| Goal help plans | assistant | steps of known kinds, routes and controls the cockpit has, plain `rihmasto` commands |

The fixtures are neutral, made up for the evals (`kernel/role_evals_fixtures.py`). Each answer is judged by rule, not
by another model. A **candidate** is a role's configured model, its fallback, or `<model>@<endpoint>` from the
routing (a coding-agent harness endpoint too). Each candidate is asked through its own Gnomon lane, so the comparison
uses the same path a real call does. The results, recorded as `role_eval_ran` (scores only, never a prompt or an
answer), show in Models setup: "On our evals, ask rihma answers: qwen3.6-35b (local) 100% vs glm-5.3 (go) 71%."
Compared for a confidential project (`--for <pid>`), a hosted candidate is refused and never asked.

## What a live run needs

Gnomon 0.6.5 or later on PATH (or `GNOMON_CMD`). For a project audit, the repository needs a `.gnomon/` surface (a
project Rihmasto built has one; elsewhere run `gnomon init`). `eval` also needs a trials spec in the repository and
the lane's model roles answering. The three benchmarks need a Gnomon source checkout and node. The role evals need
the roles' endpoints answering. Each run spends what its models cost; the role evals ask 3 to 7 short prompts per set
and candidate.
