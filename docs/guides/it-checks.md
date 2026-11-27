# IT checks

What IT keeps an eye on for each project, and why: the typical infrastructure checks for apps, databases,
networks, integrations, scheduled jobs, models and agents, proposed per project from what it runs. It is FR-ITO1;
the code is `kernel/checks/infra.py`, `kernel/checks/infra_data.py`, `kernel/checks/infra_ai.py`,
`kernel/checks/infra_targets.py`, `kernel/itops.py` (check sets), `kernel/itops_evals.py` (eval sets),
`kernel/itops_assess.py` (any assessment), `kernel/itops_suggest.py`, `kernel/itops_heal.py`,
`kernel/itops_chat.py` and `kernel/itops_cli.py`, with `cockpit/itops_routes.py` and `cockpit/static/itops.js`.

## Where to find it

- **A project**: the *Run* capsule, *IT checks* (`#/p/<project>/itops`). What the project runs, its check set with
  why each check is there, Run an assessment, the eval sets and the automations IT would set up.
- **Health** and **Integrations and data** of a project show the set in a card; the platform's *Integrations and
  data* page shows what IT checks by solution type, and lets IT change a platform default.
- **Agent operations** shows the eval sets over time.
- **Ask Rihma**, by rule and without a model: "What should IT check for this project?", "Run the IT checks",
  "Run the optimise audit", "Run an assessment of the code", "Which eval sets can I run?", "Enable the chaos eval
  set". Each write is a proposal: nothing happens until you confirm it.
- **The command line**: `rihmasto itops show [<project>]`, `rihmasto itops apply <project> --person P --persona it`
  and `rihmasto itops assess <project> --target infra --person P --persona it`.

## The check families

Each check is passed, failed, or not measured with why, never passed when nothing was measured. Its history is
kept on Health like any check's. A check finds its target in the project's own records when you give it none:
where the project runs, and the endpoints IT bound for its declared data integrations.

| Check | What it measures | Settings |
| --- | --- | --- |
| `app` | the health endpoint's status code, its latency against a budget, the version it reports | `url`, `path`, `expect_status`, `max_ms` |
| `tls` | days until each https certificate expires: a warning under `warn_days`, failed under `fail_days` | `targets`, `warn_days`, `fail_days` |
| `dns` | each host resolves and something answers on its port, within a timeout | `hosts`, `timeout_ms` |
| `database` | a declared database answers within budget; a SQLite file opens read-only and its growth is bounded; the newest backup is recent | `binding`, `endpoint`, `environment`, `max_ms`, `backup_dir`, `backup_max_hours`, `growth_pct` |
| `integration` | each declared integration's endpoint answers; credential expiry from IT's rotation reminders and `expires`; quota headroom when the endpoint reports it | `integrations`, `environment`, `expires`, `quota_min_pct` |
| `job` | each scheduled automation ran on time and without failures in a row; the scheduled checks' duration trend; the output is fresh | `output`, `max_age_hours` |
| `ml` | the latest result of each Gnomon eval set that ran, and its drift against the runs before | `evals`, `drift_pct` |
| `agent` | the agents' tool-error rate, cost per run and refusals, from their run records | `window`, `max_tool_error_pct`, `max_refusal_pct`, `max_cost_per_run` |

What a check never does: it sends no credential and signs in nowhere. A PostgreSQL or MySQL database is asked its
protocol's first round trip (PostgreSQL's SSL request, MySQL's greeting), so a query and the storage size there are
not measured, and the check says so. The reference connector of the kind is named, never called.

## Check sets per solution type

| Solution type | Its checks |
| --- | --- |
| Web service | app, tls, dns, destinations, dependencies |
| Scheduled job or pipeline | job, executions, dependencies |
| Integration | integration, dns, tls |
| Database-backed | database, dns |
| ML pipeline | ml, job |
| Agent or assistant | agent, ml, gnomon_security |
| Game or content | tests, dependencies |
| Mobile app | app, tls, dependencies |
| Library or command-line tool | tests, dependencies, licences |
| Documents only | none: it runs nothing, so there is no infrastructure to check |

A project's types come from its work profile and from what was found: an address where it runs, a declared
database or other integration, a scheduled automation, Gnomon eval results. You can choose them by hand.

Each check of a set says where its rule comes from:

- **Platform default**: Rihmasto's default for the type, or **changed by IT** for every project of that type
  (the platform's *Integrations and data* page, *Change a platform default*, IT only);
- **This project only**: a check added here with why, or taken away here (the IT checks view; IT, operations or
  a developer).

**Turn on** enables each check of the set not on yet, with its schedule; **Run the IT checks now** runs the
infrastructure checks of the set. Both are signed and recorded.

## Run an assessment of any area

The `run_assessment` action runs one target, now from the IT checks view or Ask Rihma, or on a schedule from an
automation, always with the rights of the person (or the automation's owner): the target's own rule refuses a
persona it does not allow.

| Target | What runs |
| --- | --- |
| `code` | the code assessment of the repository, rules only |
| `gnomon:<eval>` | one of Gnomon's audits, benchmarks or evals |
| `evalset:<id>` | an eval set: `evalset:gnomon:chaos`, or a role eval set for this project such as `evalset:role:ask_answers` |
| `evalsets` | every eval set turned on for the project, each as its own `evalset:<id>` |
| `check:<key>` | one enabled Health check |
| `family:<kind>` | every enabled check of one kind, such as `family:tls` |
| `alignment` | the alignment scan of the repository |
| `optimise` | the AI architect's Optimise audit of the project's agents |
| `infra` | the project's IT check set |

Each run is recorded as `assessment_ran`, beside what its own feature records.

## Eval sets

- **Gnomon's** audits, benchmarks and evals run on one project's repository, so each is turned on per project: it
  then runs on its schedule as a Health check (`gnomon_<id>`).
- **Rihma's role evals** judge the models behind Rihma's own roles, so their results are platform-wide; a project
  turns one on to run it with its own rules (a confidential project compares local models only) and see its trend.

Each set shows its trend in the IT checks view, and the eval sets over time are on Agent operations.

## Suggested automations

From what the project runs, the Automations tab and the IT checks view suggest: a weekly certificate check when it
serves or reaches https, a nightly database probe when it declares a database, an alert when an integration
fails its check, a weekly round of the IT checks, a weekly run of the eval sets turned on for an ML pipeline or an
agent, and a daily check of an agent's limits. A suggestion that runs a check is shown *not available here* until
that check is on (and the weekly eval sets until an eval set is on), saying what to turn on first: set up before,
it would run nothing. Two templates join the automations' own: *Run an assessment on a schedule* and *TLS expiry
weekly*.

## When a check fails

A failing infrastructure check opens an incident at once, with the check's evidence and the remedy where one is
known (renew the certificate, check DNS and the firewall, run the backup job, rotate a credential, retrain or roll
back a model, open the Optimise audit). It is opened once per change to failed, never once per run, and
`infra_check_failed` is recorded with the kind as its source, so an automation can react to one kind failing.

A result that says *not measured* opens no incident for an infrastructure check: the project runs nowhere yet,
declares no database, or a setting needs changing. Turning a check set on for a project that runs nowhere leaves
Incidents empty. Only a check whose own code broke is an incident then, because that is Rihmasto's fault.

## What the checks hold up under

- **A port that is not HTTP.** An app or integration endpoint that answers with something else (an SSH or
  database port) fails its check: *it answered, but not with HTTP*. A check that breaks is recorded as not measured
  with what broke, and every other check due in the same round still runs.
- **The wrong port for a database.** Only a server that answers PostgreSQL's SSL request with its one byte, and
  says nothing else, passes as PostgreSQL. A closed port says the connection was refused; a port that never answers
  says no answer came in time.
- **Bad settings.** A credential expiry that is not `NAME=YYYY-MM-DD`, a host that is not `host:port`, or an address
  with no host is refused when the check is turned on. A setting kept from before runs as *not measured*, naming
  the setting to change.
- **Certificates.** An expired certificate is said expired (renew it). One from a private CA, self-signed, or for
  another name is said *not trusted*, with what to install instead.
- **What counts as a job.** A project is a *scheduled job or pipeline* when an active scheduled automation of its
  own does its work. An automation that only runs its checks, evals or assessments, or one for every project, does
  not count. A paused automation is listed as paused, never as late.
- **Assessments.** A code assessment fails only on a critical or high finding; the others are counted by severity.
  The Optimise audit of a project with no agent run says so. A refused assessment replaces the last result on the
  view instead of standing beside it.
- **Who acts.** Turning the set on and running it are for IT, operations or a developer. Another persona sees those
  buttons disabled with whose they are. Ask Rihma tells them whose it is instead of offering a Confirm that would be
  refused. Ask Rihma understands *run the TLS checks*, *run the database check*, a phone's lowercase *run the it
  checks* and *what should it check for this project?*
