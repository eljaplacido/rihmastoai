# Automations

An automation is a **trigger**, an optional **guard**, an **action**, a **scope** and **limits**, owned
and signed by a person and a persona. It runs with its owner's rights and never beyond them, and every
change and every run is in the ledger. An automation never decides a card: deciding stays with people,
or with a person's delegation as before ([autopilot and delegation](autopilot-and-tracking.md)).

The owner asked for it (2026-11-24): "we should be able to set and run automations and hooks per
project, even across them." This page says how, in the cockpit and on the command line, with the
templates and the lines that run them without the cockpit. The code is `kernel/automations.py` (the
parts, signed), `kernel/automations_run.py` (the tick), `kernel/automations_actions.py` (the actions)
and `cockpit/automation_routes.py` (the page and the scheduler).

## The parts

**Trigger**, one of:

- a **schedule**: every N minutes, hours or days (`15m`, `2h`, `1d`; at least 5 minutes, at most 7
  days), daily at `HH:MM`, or weekly on a day at `HH:MM`. Times are UTC. A slot missed while nothing
  ran (the cockpit was down) fires once when the next tick comes, never once per slot missed;
- a **ledger event** in the scoped projects: any record kind (`release_done`, `question_added`,
  `material_added`, `adopted`, `change_submitted`, `incident_opened`, ...), and three names for what
  people mean: `gate_failed` and `gate_passed` (a `gate` record with that verdict) and `card_waiting`
  (a card opened). An automation never reacts to automations' own records (`automation_*`), nor to the
  records its own run wrote;
- an **inbound webhook** source ringing (see [hooks per project](#hooks-per-project));
- a **repository change**: new commits on a branch of an attached repository (`rihmasto repo attach`)
  or an adopted project's upstream, found by polling at most every five minutes. The first look only
  notes where the branch is.

**Guard** (optional), a cheap check before acting, so a tick costs nothing when there is nothing to do:
`count` (an event at least N times within some hours: "only when the gate failed twice today"),
`branch` (the event's branch: "only on main"), `field` (a field of the event equals a value), or
`open_cards` (the project has at least N open cards, of a kind or any). A guard that does not hold
drops the firing and records nothing; the automation's page says why it last skipped.

**Action**, from an allow-list, each through the kernel's own path:

| Action | What it does | Personas whose rights it may run with |
|---|---|---|
| `advance` | runs the project's pipeline until a person is needed (the autonomy cap, posture and pause apply) | business owner, product owner, developer, operations, IT |
| `gate` | gates the commits since the last gate this automation ran, on an attached repository | developer, IT, operations, product owner |
| `rescan` | re-scans a folder and adds it as material when it changed | business owner, product owner, developer |
| `notify` | sends a notice (Teams, Slack, mail) or a signed CloudEvent through one of IT's relay subscriptions | any |
| `change` | opens a change proposal on the project, or on another one (cross-project) | any |
| `signal` | logs a signal in the delivery square | any |
| `output` | rebuilds the project's chosen outputs | business owner, product owner, developer, IT, compliance |
| `command` | runs the project's own test suite, found by rule, in a temporary clone | developer, IT, operations |
| `ask` | asks a model (the assistant role) with the project's context, and posts the answer as a comment | any |
| `probe` | runs the probe check (`/health` and every probe scenario) where the release runs: the environment the event names, or the one given, else production; on production it is an operations round, so a failing probe opens the incident card. With `every` (15m to 1d) it keeps probing production from then on: the probe check is enabled on the project (`probe_check_enabled`) | business owner, product owner, developer, IT, operations |
| `run_check` | runs one check enabled on the project's Health tab (`check`, such as `dependencies` or `custom:smoke`) through the checks' own path; its result is a `check_ran` like any other run. A check not enabled there does nothing and says so ([console and checks](console-and-checks.md)) | business owner, product owner, developer, IT, operations |
| `align_scan` | reads the project's repository again for alignment (an attached or adopted project), signed by the owner; `alignment_scanned` records the drift since the scan before, shown on the Alignment tab to accept or reject ([alignment](alignment.md)) | business owner, product owner, developer, IT |

`decide`, `approve`, `accept`, `deploy`, `merge`, `grant`, `trust`, `delegate` and the like are refused
whatever an action is called, and so are `go`, `skip` and `go_ahead` (the look at the spec before the
first build) and `runner` (a cell runner IT approves). An `advance` waits on cards exactly as a person's
Advance does: the go-ahead card and a runner card stay open for people, or a person's delegation. A text may
carry `{project}`, `{event}`, `{automation}`, `{ref}`, `{verdict}` and `{branch}`, filled from ids only,
never from a record's free text. A run may also **notify** a subscription of its outcome: if it fails
(the action failed or was refused, or the gate's verdict is failed), or every run.

**Scope**: one project, a list of projects, every project with a **tag**, a **profile** or a **source**
(attached, adopted, idea, folder), or every project in the factory. A project is tagged on its
Automations tab or with `rihmasto automations tag <pid> --tag ops`. An action on one project runs once
per project in scope; `notify` and `signal` run once.

**Limits**: at most N runs an hour (a firing over it waits for the next tick), a **circuit breaker**
after N failed runs in a row (it pauses the automation, and Home and the project's What's next say why
and offer Resume), **quiet hours** (`22:00-06:00`, UTC: nothing runs, and what came in meanwhile runs
when they end) and a **dry run** (it records `would ...` and does nothing).

## Who owns it, and with which rights

A named person sets an automation as a persona the action allows; with access enforced
([access](access.md)) the persona must be granted on every project in scope (on the factory for a
factory-wide one), and the verified identity is recorded. **Before every run** the rights are checked
again, as they are now: the persona must still be allowed, and with access enforced the owner's identity
must still hold the persona on the project in IT's access file. A grant IT removes stops the next run
(it is recorded as refused). The run is signed as that identity, so its records name it, and untrusted
code (a gate, the project's tests) goes through IT's isolation runner as anywhere else. A module that is
not enabled where an action acts refuses it ([use only what you need](use-only-what-you-need.md)).

Anyone may **pause** an automation (stopping is always safe). Its owner or IT resumes, changes or
removes it; the person who changes it owns it from then on, signed again. Run now acts at once with the
owner's rights, passing over the trigger and the guard; the runs per hour still hold.

## Running them

A **tick** takes every active automation once: it collects what fired since the last tick, reads the
guard, holds to the limits, takes a firing off the queue and saves that **before** the action runs, then
records the run (`automation_ran` with its outcome, in the factory's ledger and the project's). A record
fires an automation at most once: a run that dies part way is never run again. Only one tick runs at a
time; a second one answers busy and changes nothing.

- **In the cockpit**: `python -m cockpit.server` starts a scheduler thread that ticks every minute while
  the cockpit runs, and at once when someone presses Run now.
- **Without the cockpit**: run `rihmasto automations tick` every minute from the system's scheduler.
  `rihmasto automations install-help` prints the exact lines for this machine, with its Python, this
  checkout and the factory home:

```
# cron (Linux, macOS)
* * * * * cd "/path/to/rihmasto" && "/path/to/python" -m kernel.cli --home "/path/to/factory-home" automations tick >> "/path/to/factory-home/automations/tick.log" 2>&1

# Windows Task Scheduler
schtasks /Create /TN "Rihmasto automations" /SC MINUTE /MO 1 /F /TR "cmd /c cd /d \"C:\path\to\rihmasto\" && \"C:\path\to\python.exe\" -m kernel.cli --home \"C:\path\to\factory-home\" automations tick"
```

Both may run together: the cockpit's tick and the scheduled one never overlap.

### Why not Gnomon loops

Gnomon's loops (`gnomon loops`) are a schedule, a shell guard and a shell act with a circuit breaker and
no daemon, declared in a repository's `.gnomon/loops/*.toml`. They fit a schedule with a guard, but an
automation here is governed by Rihmasto: it is signed by a person, checked against the access file before
every run, runs only allow-listed kernel actions, reacts to ledger events and inbound webhooks, and
records every run in the hash-chained ledger. A loop's act is a shell command in a content-hashed surface,
its state lives beside the repository, and on Windows a loop can run but not install. So the automations
stay Rihmasto's own, and a Gnomon loop may still be the scheduler that runs the tick: its `[act] run` is
the line above, and nothing about what runs changes.

## Templates

The builder starts from these (`rihmasto automations templates`):

| Template | Trigger | Action | Scope | Fill in |
|---|---|---|---|---|
| Nightly re-gate | daily 02:00 | gate, notify a channel if it fails | every attached repository | the subscription |
| Notify on release | `release_done` | notify a channel | every project | the subscription |
| Re-scan a folder weekly | weekly mon 06:00 | rescan a folder | one project | the project and the folder |
| Cross-project dependency | `release_done` on A | open a change proposal on B | project A | both projects |
| Ask after two failed gates | `gate_failed`, guard: twice in 24 h | ask a model, post the answer | one project | the project |
| When a release reaches test, run its checks and notify | `release_reached_test` | probe the test road, notify of every run | every project | the subscription |
| When promoted to production, enable the probe check and notify | `promoted` | probe production now and every hour, notify of every run | every project | the subscription |
| When a concept is validated, notify the product owner | `concept_validated` | notify the product owner's channel | every project | the subscription |
| When the gate fails twice, open a change proposal | `gate_failed`, guard: twice in 24 h | open a change proposal | one project | the project |
| Notify when a check fails | `check_ran`, guard: verdict = failed | notify a channel with the project | every project | the subscription |
| Morning review digest | daily 07:30 | `review_digest`: the owner's [Review](review.md) to a channel, held back when nothing happened | the factory | the subscription |
| Re-read the repository for alignment when it changes | a new commit on the repository | `align_scan`: the drift shows on the Alignment tab | one project | the project |

## Suggested for a project

The owner (2026-11-24): "for automations you should be able to scan a project for suggestions of them."
A scan reads what a project is and how it stands (`kernel/automation_suggest.py`) and suggests the
automations it asks for, each with a one-line reason. Scanning writes nothing.

| Suggestion | When it is offered | What it sets up |
|---|---|---|
| Nightly gate on new commits; notify if it fails | an attached repository | daily 02:00, the gate; a notice when it fails (if a channel is set up) |
| Run its tests on every new commit | a repository with a stated or found test command | new commits, the project's own tests in a sandbox |
| Probe production every 5 minutes | a release runs in production | every 5 minutes, the probe check on production |
| Tell me when a check fails | checks are enabled on it | `check_ran` with verdict failed, a notice |
| Alert if a role would leave the local model | it is confidential | `confidential_fallback_skipped` or `confidential_refused`, a notice |
| Re-read its specs and tests when the repository changes | it aligns with a repository of its own | new commits, `align_scan` |
| When a release reaches test, probe it there | it has releases on a paved road | `release_reached_test`, the probe |
| When the gate fails twice in a day, open a change proposal | agents work on it from an IDE, or people push to it | `gate_failed` twice in 24 h, a change proposal |
| Build and test it every night; run its evaluations every week; re-scan its folder every week | a game; an ML pipeline; a knowledge base with its folder | the project's own tests; its folder re-scanned |
| Weekly activity summary by area into Review | it has history | Mondays 07:00, a summary asked of the assistant model (a local one when confidential) |
| Tell me when the first build passes the gate | Rihmasto builds it | `first_build_passed`, a notice |

A notice goes to the project's own relay subscription, else one for every project; with none set up it is a
signal on the delivery square, which needs no channel. **Set it up** sets the automation in your name, signed
and checked as any automation (`automation_set`, and `automation_suggestion_accepted` in the project's
ledger); **Not now** dismisses it, remembered and recorded (`automation_suggestion_dismissed`). One already
set up (an automation of the same action and trigger reaches the project) shows as set up.

## Describe it

The owner: "ask an agent to generate an automation based on your description." Write what should happen,
in English or Finnish, and Rihmasto drafts it (`kernel/automation_compose.py`):

> every night run the tests and tell me on Teams if they fail
> öisin aja testit ja ilmoita Teamsiin jos ne epäonnistuvat

Both read as: every night at 02:00 UTC, for this project, run the project's own tests in a sandbox; notify
the Teams subscription if it fails. The draft comes with its plain-language summary and a dry run (the
projects it reaches, what one firing would do on each, when it would first run). Nothing is set until you
press **Set it up**, or **Open in the builder** to change a part first.

- **The rules** read the common phrasings without a model: a schedule ("every night", "every 5 minutes", "on
  Mondays at 9", "öisin", "joka aamu"), an event ("when a release is done", "when the gate fails", "when a
  check fails", "on new commits", "kun julkaisu valmistuu"), an action ("run the tests", "run the gate",
  "probe production", "summarise", "re-read the repository", "aja testit") and whom to tell ("tell me on
  Teams if they fail", "ilmoita Slackiin"). What they cannot read is said plainly.
- **A model for the rest**: when you name an automation the rules cannot read, the assistant model drafts it
  from the allow-list and the schema; its draft is checked as any automation is, so an action off the
  allow-list, or one an automation may never take (decide, approve, deploy, merge...), is refused with the
  reason. A confidential project whose assistant model is hosted is read by the rules only, and told so.

Ask Rihma does the same: "suggest automations for this project" lists the suggestions, each a proposal to
set up; "probe production every 5 minutes" is a draft to confirm.

## The life-cycle steps and their transitions

D-0023: every transition is visible, recorded, and can trigger an automation. An event trigger names
each by the name on the left; the record behind it is in the project's ledger
(`kernel/automations_events.py`):

| Event | The record |
|---|---|
| `concept_validated` | `created_from_concept`, in the project the validated concept made |
| `plan_approved` | `plan_approved`, or at explore and demo `go_ahead_given` with Go (Skip is no approval) |
| `first_build_passed` | `first_build_passed`: every task merged through the gate, the first time |
| `release_reached_test` | `release_reached_test`: a release deployed to a test road (preview, demo, staging) and its smoke check passed |
| `promoted` | `promoted`: a release promoted to production |
| `rolled_back` | `rolled_back` |
| `check_failed` | `probe_failed` (a probe on production) or `release_failed` (a release's step failed) |

## In the cockpit

**Automations** in the sidebar lists every automation with its plain-language summary, owner, state and
last run, filtered by state, scope kind or the project it reaches. **New automation** opens the builder:
trigger, guard, action, scope and limits, with the summary the kernel writes from them shown before you
save ("Every night at 02:00 UTC, for every attached project, run the gate on the attached repository;
notify SUB-001 if it fails."). Each automation has Run now, Dry run (what the next tick would do; it
records nothing), Pause or Resume, Edit, Remove, and its runs. Each project has an **Automations** tab
with the automations that reach it, its tags and what ran on it. Ask Rihma knows where all of this is.

## On the command line

```
rihmasto automations list [--project PID] [--state active|paused] | templates | show AU-001 | history [AU-001]
rihmasto automations add --name "Nightly re-gate" --daily 02:00 --action gate --source attached \
                         --notify SUB-001 --person Aino --persona developer
rihmasto automations add --template notify_on_release --subscription SUB-001 --person Ilkka --persona it
rihmasto automations add --name "When Loans releases" --on release_done --project loans-1a2b3c \
                         --action change --target-project bookings-4d5e6f --text "{project} released: check" \
                         --person Aino --persona product_owner
rihmasto automations edit AU-001 --guard-count gate_failed:2:24 --person ... --persona ...
rihmasto automations pause|resume|remove AU-001 --person ... --persona ... [--reason "..."]
rihmasto automations run-now AU-001 [--project PID] --person ... --persona ...
rihmasto automations dry-run AU-001
rihmasto automations tick
rihmasto automations install-help
rihmasto automations tag PID --tag ops --person ... --persona ...
rihmasto automations suggest PID
rihmasto automations accept|dismiss PID nightly_gate --person ... --persona ...
rihmasto automations describe "every night run the tests and tell me on Teams if they fail" --project PID \
                              [--save --person ... --persona ...] [--with-model]
```

## Hooks per project

IT binds an inbound source to projects: `rihmasto hooks add ci --scheme standard --secret-env HOOK_CI
--bind <pid>` (or later `rihmasto hooks bind ci --project <pid>`). Each ring is then recorded in those
projects' ledgers too, so their automations react to it; a push names its branch, so a `branch` guard
holds only for `main`. A factory-wide automation hears every ring of a source in the factory's ledger.
A ring stays a doorbell: it carries ids, never the sender's text ([integrations](integrations.md)).

Outbound, IT gives a project a channel of its own: `rihmasto relay subscribe ... --project <pid>` sends
that subscription only the project's events. An automation's `notify` goes through any of IT's
subscriptions, and a project an autopilot binds to its sandbox sends nothing to a receiver that is not a
sandbox one.
