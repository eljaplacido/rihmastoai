# Build workflows and automations

Two different things go by this name, and Rihmasto does both:

- **Automations around your projects**: Rihmasto itself re-gates, re-scans, probes, aligns, notifies
  and advances on a schedule or when something happens. You set them up in minutes.
- **A workflow as the product**: a job with no screens (a nightly count, a folder watcher, one agentic
  capability) that Rihmasto builds through the same governed chain and delivers as a capability you
  reach over MCP, an OpenAI-compatible endpoint, a website chat or HTTP.

## Automations around your projects

An automation is a **trigger**, an optional **guard**, an **action** from an allow-list, a **scope**
and **limits**, owned and signed by a person. It runs with its owner's rights, re-checked before every
run, and never decides a card.

### Start from a suggestion or a template

**In the cockpit.** A project's **Automations** tab suggests automations from the project's shape and
state ("this project has an upstream: re-align on new commits"). **Accept** sets one up in your name.
Or start from a template, or describe it in your own words and read the draft, its summary and its dry
run before you keep it.

**In Ask Rihma.** "Suggest automations for this project" lists the suggestions, each a proposal to set
up; "probe production every 5 minutes" or "every night run the tests and tell me on Teams if they fail"
is a draft you confirm. Common phrasings are read by rule, with no model.

**On the command line.**

```bash
rihmasto automations templates
rihmasto automations suggest <pid>
rihmasto automations add --template nightly_regate --project <pid> --person "Ada Example" --persona developer
rihmasto automations describe "every night at 02:00 run the tests and tell me if they fail" --project <pid>
rihmasto automations dry-run <automation id>
```

Some templates: `nightly_regate`, `check_failed_notify`, `align_on_change`, `production_probe`,
`weekly_rescan`, `morning_review_digest`, `weekly_gnomon_audit`, `gate_twice_change`.

### The parts

| Part | Choices |
|---|---|
| Trigger | a schedule (every 15m to 7d, daily or weekly at a time, in UTC), a ledger event (`gate_failed`, `release_done`, `card_waiting`, ...), an inbound webhook, new commits on a repository |
| Guard | an event at least N times within some hours, a branch, a field's value, at least N open cards |
| Action | `advance`, `gate`, `rescan`, `notify`, `change`, `signal`, `output`, `command`, `ask`, `probe`, `run_check`, `align_scan`, and more; never `decide`, `approve`, `deploy`, `merge` or `trust` |
| Scope | one project, a list, every project with a tag, a profile or a source, or the whole factory |
| Limits | runs per hour, a circuit breaker after repeated failures, quiet hours, a dry run |

The full reference is [automations](../guides/automations.md).

### Without the cockpit running

The cockpit runs what is due once a minute while it runs. Otherwise `rihmasto automations install-help`
prints the cron line or the Windows Task Scheduler command that runs `rihmasto automations tick`.

## A workflow as the product

When the need itself is a job, start it like any project, with the **automation** kind of work:

```bash
rihmasto new "Nightly failed deliveries" --profile automation --maturity explore \
    --requested-by "Ada Example" \
    --source "Every night, count yesterday's failed shipment deliveries the stock system reports. Make it reachable over MCP."
```

The panel asks what starts a run and where it must be reachable. The builder works inside a capability
template whose server, health check and pack guard no cell may change. The release is a capability pack;
`rihmasto capability serve` runs it on this machine behind that guard
([small capabilities](../guides/small-capabilities.md)).

## Workflows across tools: goals, hand-offs and hooks

- **A goal in your words.** `rihmasto goal <pid> "hook this to Google Drive"` (or the same in Ask Rihma)
  gives a plan of steps you take one click at a time ([agentic help](../guides/agentic-help.md)).
- **Doorbells in.** IT names a webhook source (`rihmasto hooks add`), bound to projects; a verified ring
  becomes a signal or a change proposal, and automations can react to it.
- **Events out.** A relay subscription sends signed CloudEvents or Teams, Slack and email notices
  (tested against local receivers only) ([integrations](../guides/integrations.md)).

## What happens under the hood

- **A tick.** Once a minute (the cockpit, or `automations tick` from cron), each active automation's
  trigger is checked; a guard that does not hold drops the firing and records nothing, so an idle tick
  costs nothing (`kernel/automations_run.py`).
- **A run.** The owner's rights are checked again as they are now. The action goes through the kernel's
  own path, exactly as if the owner had pressed the button: an `advance` stops at the same cards, a `gate`
  is the same gate. The run is recorded as `automation_ran` with its outcome, and its own records never
  trigger automations again.
- **Failures.** A failed or refused run counts towards the circuit breaker; at the limit the automation
  pauses itself, and Home and What's next say why and offer **Resume**.
- **A capability.** Its runtime declaration (`app/runtime.json`) is judged with no model at the gate, in
  the pack and in the image; each way in (MCP, OpenAI-compatible, embed, HTTP) answers only after the
  pack guard checks the pack.

## Next

- [Improve and maintain](improve-and-maintain.md): the rhythm these automations keep.
- [Configure with your agents](../guides/configure-your-agents.md): hooks in your own coding agent.
