# The console, a terminal, and checks

Rihmasto does not replace your editor. You keep developing in the IDE you chose, on your own branch or
your own repository. What Rihmasto adds is the part that comes after: running a project's commands where
the factory can see and record them, asking Gnomon to do a piece of work under its own governance, and
keeping a set of checks running so that a project stays healthy after it is deployed (FR-CON1, FR-CHK1).

## Where the line is

| You want to | Use | Why |
|---|---|---|
| write and change code, debug, refactor, review a diff | **your IDE** | it is your tool; Rihmasto never writes into your repository |
| run the tests, a build, a lint, a CI step, a one-off script, and have it on record | **the console** (a project's Console tab, `rihmasto console`) | one command at a time, its output line by line, a time limit and a Stop, recorded in the project's ledger |
| ask Gnomon to do something in the workspace | **the console's Gnomon box** (`rihmasto console <pid> --gnomon "..."`) | `gnomon task` under the workspace's own `.gnomon/` surface, policy and audit trail |
| run an editor, `top`, a REPL, Gnomon's interactive loop, anything that draws the screen or waits for keys | **a real terminal** (Open a terminal here, `rihmasto shell`) | the console has no pseudo-terminal: its input is closed and its output is lines |
| keep checking a project after it is deployed | **checks** and **Health** | each check gives passed, failed or not measured with its evidence, on demand, on a schedule or from an automation |

## The workspace

Every console run, Gnomon run and terminal opens in the project's workspace:

- an **attached repository** (`rihmasto repo attach`): its own folder, your working tree as it is;
- else **your own workspace** on the project, when you opened one (`rihmasto workspace open`);
- else the **console's working copy**: a clone of the project's repository (a built or adopted project)
  under the lanes root, `<lanes root>/workspaces/<pid>/console`, made at the first run and moved forward
  to the repository's tip while it holds no change of its own. Its `origin` has no push URL: work reaches
  main only through a workspace's submission and the gate.

A project with no code yet has no workspace, and the console says so.

## The console

Open a project and choose **Console**. It shows the workspace, who may run commands, and what it offers:

- the commands stated for the project (test, build, lint and any other name; set in the console's
  settings or with `rihmasto console <pid> --state test="python -m pytest -q"`);
- the test command found by rule (the same rules adoption uses);
- `package.json` scripts, Makefile targets and the `run:` steps of the GitHub Actions workflows (and
  `.gitlab-ci.yml` scripts).

Press one, or type a command line and press **Run**. The output streams into the tab line by line until
it ends, with its exit code and how long it took. **Stop** ends it and every process it started; a run
that reaches its time limit (600 seconds unless you ask, at most an hour) is stopped the same way.

A command line runs as one program with its arguments, never through a shell. A line with a pipe, `&&`,
`;` or a redirect is refused unless you tick **Run through the shell** (`--shell`); a CI step of several
lines is offered as a shell step. Input is closed: a program that asks a question reads end of input.

**Who may run.** Developers and IT, unless IT changes the list for the project (the console's settings,
or `rihmasto console <pid> --allow developer,it,operations`). With access enforced, the persona must also
be granted on the project in IT's access file.

**What is recorded.** Each run is a job (it is on the Jobs page too) and a `console_ran` record in the
project's ledger: who, which persona, the command line (known secret shapes masked), the workspace, how it
ended, its exit code and how long it took. Never an environment value, and never what it printed: the
output stays in the job's log under `<home>/jobs/`.

**Access enforced.** A run goes through IT's isolation runner, as the gate's tests do: in a container with
no network and the workspace mounted at `/work`, or as the separate account through sudo. Without a usable
runner it does not start ([access](access.md#isolation)).

From the command line:

```
rihmasto console <pid> --person "Dana" --persona developer -- python -m pytest -q
rihmasto console <pid> --person "Dana" --persona developer --shell -- "npm ci && npm test"
rihmasto console <pid> --offers
```

It streams the output as it comes and exits with the command's own exit code.

## Gnomon

In the workspace, the console's Gnomon box runs `gnomon task "<what to do>"` with the role you name. Gnomon
governs the run: its `.gnomon/` surface says what each role may read, write and run, its policy gates writes,
and its audit trail records the run. Without **Let Gnomon apply gated changes** (`--yes`) every gated tool
call is refused, as in any run with nobody to ask.

- A workspace that has a `.gnomon/` surface (a built product's repository has one) runs under it.
- The console's own working copy without one gets the factory's routing compiled into it, kept out of
  commits.
- Your repository without one is refused, and never written to: run `gnomon init` there, or open a
  terminal here.
- A confidential project's run must route to local models (inputs guide, Confidential material).

The run is recorded as `console_ran` with kind `gnomon`; Gnomon's own records stay in the workspace.

## Open a terminal here

The cockpit runs on your own machine, so it can open your operating system's terminal in the workspace:
Windows Terminal (else PowerShell) on Windows, the default terminal on Linux, Terminal on macOS. It opens
with the project's routing environment: the model keys stored in Models setup in the variables the routing
names, Gnomon's folder first on PATH, and `RIHMASTO_HOME` and `RIHMASTO_PROJECT`. No value is shown or
recorded; the opening is recorded as `console_opened`.

`rihmasto shell <pid>` does the same from the command line: an interactive subshell in the workspace.

What you run in a terminal is your own work on your own machine: it is not isolated and not recorded
command by command. So the cockpit opens one only for a request from its own loopback address. Behind a
public origin (`--public-origin`, IT's proxy) the button is refused with why: open a terminal on that
machine yourself.

## Checks

A check is one question about a project, answered with a recorded result: **passed**, **failed** or **not
measured** with why. Not measured is never shown as passed.

| Check | What it asks | Not measured when |
|---|---|---|
| `tests` | the project's own test suite: the stated test command, else the one found by rule | no test command is known, or none ran |
| `custom` | a command of your own; exit 0 passes | the command cannot start |
| `ci` | the latest CI/CD runs on the default branch: the GitHub API with a token, else `gh run list` | neither a token nor the GitHub CLI is there, or no run finished |
| `dependencies` | known vulnerabilities: pip-audit, npm audit, cargo audit or osv-scanner | an ecosystem's tool is not installed; Rihmasto installs nothing |
| `secrets` | Rihmasto's own secret scan of the workspace (evidence masked) | the scan could not read the workspace |
| `licences` | dependency licences from `package-lock.json`, copyleft flagged against a policy list (`deny`) | no lockfile records licences, or one is unknown |
| `sbom` | a CycloneDX SBOM from the lockfiles, kept with the project | no lockfile pins components |
| `probe` | a deployed URL's status, latency and TLS expiry (`url`, `expect_status`, `max_ms`, `tls_days`) | no URL is set |
| `executions` | a scheduled job's latest finished execution where it runs, on the gcp-cloudrun road (`environment`, production by default), with the last executions as evidence | no scheduled job runs there, or none has finished yet |
| `repo_gate` | the gate on an attached repository's latest commits | the project is not attached, or has no contract |
| `security_gate` | Rihmasto's own security gate over the project's scans | there is no scan |

Several of one kind take a name: `probe:prod`, `custom:lint`.

**CI/CD status.** With a token, the check asks the GitHub API (or a GitHub Enterprise address in `api`).
The token is read from the environment variable `token_env` names (default `GITHUB_TOKEN`), the same
`env:` reference a connector's credentials use; it is sent only as the request's bearer token and never
shown, recorded or put on a command line. Without a token it uses `gh run list`, which signs in itself.

**Enabling.** Open a project's **Health** tab and **Enable a check**, or across projects from the Health
page; or `rihmasto checks enable <pid> <check> [--set key=value] [--every 1d] [--on-fail signal,change]
[--all-projects]`. A check that runs the project's own code (tests, custom, the repo gate) is enabled by a
persona the console allows; any other by a developer, IT, operations, compliance or a product owner. Each
change is recorded (`check_enabled`, `check_disabled`) with who.

**Running.** **Run now** on Health, `rihmasto checks run <pid> <check>`, on its schedule (`every`: the
cockpit runs what is due once a minute while it runs; `rihmasto checks tick` does it from cron or Windows
Task Scheduler), or from an automation with the `run_check` action. A scheduled run acts with the rights of
the person who enabled the check, checked again against the access file before every run: a grant IT
removed stops it, and the result says so. Every result is `check_ran` in the ledger (the verdict and a
one-line summary) and kept with its evidence under the project's `checks/`.

**When a check fails.** `on_fail` logs a signal in the delivery square or opens a change proposal, once
each time the verdict turns to failed, never once per run. An automation that reacts to `check_ran` with
a guard on `verdict` equal to `failed` can notify through IT's relay subscriptions.

## Health

Each project's **Health** tab lists its enabled checks: the last result with its evidence, a trend of the
last ten, when it last ran, its schedule, and Run now. The **Health** page in the sidebar shows every
project's checks and what fails across the factory. A project's What's next says when checks fail
("2 checks failing: Dependency audit, CI/CD status") with Run now, and Home shows the same line.

`rihmasto checks list [<pid>]` and `rihmasto checks history <pid> [<check>]` read the same records.

## Tutorial: your repository, its tests and its CI, kept in view

1. Attach the repository you work on: `rihmasto repo attach "Orders" --repo ~/src/orders --person "Dana"
   --persona developer`. You keep editing it in your IDE.
2. Start the cockpit (`python -m cockpit.server`), open the link, choose the developer persona and open the
   project's **Console**. Press the test command it offers (or type `python -m pytest -q`) and watch the
   output arrive. Start something long and press **Stop**.
3. Press **Open a terminal here**: your terminal opens in the repository, with Gnomon on PATH. Run `gnomon`
   there for its interactive loop.
4. Open **Health**, **Enable a check**: `tests` every day, `ci` with `repo` set to `owner/name` (and
   `GITHUB_TOKEN` set where the cockpit runs, or `gh` signed in), `dependencies` and `secrets`. Press **Run
   now** on each. A tool that is not installed shows not measured, and says which.
5. Break a test and run the `tests` check again: Health, the project's What's next and Home say "1 check
   failing". With **Open a change proposal** ticked when you enabled it, a change proposal waits in the Inbox, once.
6. The same from the command line: `rihmasto console orders-1a2b3c --person "Dana" --persona developer --
   python -m pytest -q`, `rihmasto checks run orders-1a2b3c tests --person "Dana" --persona developer`, and
   `rihmasto checks tick` from cron or Windows Task Scheduler for the schedules while the cockpit is closed.
