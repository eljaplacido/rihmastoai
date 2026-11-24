# Autopilot, delegation and staying on track

Two ends of the same rope ([D-0017](../../decisions/D-0017-governance-everywhere.md), building on
[D-0007](../../decisions/D-0007-delegated-conclusions.md)):

- **Let it run.** A person delegates named kinds of cards to the factory's own rules, for a while, and
  lets Rihmasto run on its own in a test sandbox: an **autopilot run**.
- **Keep a tight hold.** A person sets **human checkpoints** at stage boundaries, and the run stops at
  each until they have looked.

Either way, **Track** shows whether a project stays on track against its approved plan, with every
figure's basis, and nothing skips the record: each decision names the person who made it or delegated
it, the rule, what was assumed and what proves it.

## What is built and what is planned

| Part | Status |
|---|---|
| Delegated decisions: grant, revoke, three rules, kinds never delegated, the pipeline asks before it waits (`kernel/delegation.py`) | built |
| Autopilot runs: start, passes, status, stop, expiry (`kernel/autopilot.py`) | built |
| The sandbox: delivery only to the local preview or a road marked `"sandbox": true` | built |
| The sandbox: relay events held from receivers not marked as sandbox receivers | built |
| The sandbox: a pass under way when a person stops the run delivers nothing and ends at its next safe point | built |
| The sandbox: the daily digest leaves a held project out for receivers outside the sandbox | built |
| Cutting off a cell mid-step when a person stops the run | not built, on purpose: a cell finishes its step, as with a pause (FR-J3) |
| The sandbox: a connector write waits for a person (`write_hold`) | hook built; connectors are not called yet (D-0015), so nothing asks it today |
| Track: figures, answers, checkpoints, budget (`kernel/track.py`) | built |
| Track: the posture figure | hook built; not measured until `kernel/posture.py` defines `track_posture` |
| The daily digest through a relay notice subscription | built |
| Cockpit: the Track view, the header's Track pill (the project's one on-track answer), the Home widget, start and stop, revoke, checkpoints | built |
| MCP reads `rihma_track` and `rihma_autopilot` | built |
| An "autopilot sandbox" posture preset | hook built (`posture_preset`); kernel/posture.py offers it once wired |
| Rules for more card kinds (validation, change, incident, update) | planned |
| A scheduler that runs an autopilot's passes on its own clock | planned: today `rihmasto autopilot run` or the cockpit's job runs them |

## Delegated decisions

A person whose persona may decide a kind of card delegates that kind, on one project, until a time at
most seven days away. Before the pipeline waits on a card, it asks the delegations in force: a card of a
delegated kind that the delegation's rule settles is decided by the rule, in the delegating person's
name and persona. Nothing outside the delegation is decided.

| Card kind | Rule | What the rule decides |
|---|---|---|
| question | `assume` | every open question is assumed with the proposal of the perspective that asked it, as an assumption with a due date; a question with no proposal waits |
| approval | `plan_when_tested` | the plan (and only the plan) is approved when every requirement has a test the gate runs, every criterion names a check the factory runs (a test, a holdout scenario or a probe), the spec compiles to a contract with no violation, and nothing contradicts the paved road |
| escalation | `retry_once` | an escalated builder task is retried once; when it escalates again, the rule stops and the card waits for a person. It never accepts work as it is and never stops a build |

Never delegated, whatever the persona, and refused with the reason:

| Kind | Why |
|---|---|
| deploy_gate | it opens production: IT decides it, every time |
| trust | trust grants a Gnomon surface: the owner's own act (D-0007) |
| holdout_ruling | a failed holdout means the product or its scenario is wrong, and only a person can tell which |
| connector | turning a connector on reaches an outside system: IT decides it (D-0015) |
| road | IT configures a paved road on its own infrastructure |
| concept | the factory's own card, not one project's |

A kind with no rule yet (validation, change, incident, update) stays with a person, and so does a kind
the persona may not decide itself.

**Revoking** stops a delegation at once: the next card waits for a person. The delegating person, or
anyone whose persona may decide one of the delegated kinds, may revoke it. When its time passes it
expires the same way.

**What is recorded.** The decision itself names the delegating person and persona, with
`"delegation": "DL-001"` beside them on the decision record, on the card's copy and in the ledger's
`decision` record; a decision with a reason of its own says "by delegation DL-001 (rule): why". The
ledger also keeps a `delegated_decision` record with the rule and its basis (the assumed answer, the
plan's counts, the retried task), and a `delegation_declined` record, once per card, when the rule
left a card to a person and why. Outbound events carry the delegation id, and a decided card's notice
says "by delegation DL-001".

**With access enforced** ([access](access.md)), only a verified identity granted the persona may
delegate, and the delegation keeps that identity. Each delegated decision is checked again as that
identity against the access file: a grant IT removes stops the delegation's decisions at once, and the
card waits.

## Autopilot in a sandbox

Starting an autopilot delegates the kinds you name until the time you name, records the run in the
project (`autopilot.json`) and the ledger, and runs the pipeline pass after pass until a person is
needed, it is done or fails, or the time is up. While a run holds the project, it is bound to a sandbox:

- **Delivery** goes only where the project lands in a sandbox: the built-in local preview (explore
  maturity), or a preview or demo road IT marked `"sandbox": true` in `paved_roads.json`. Staging and
  production are never a sandbox, whatever a road says. Any other delivery waits for a person, with the
  reason, and nothing is deployed or asked of IT.
- **Events** go only to relay subscriptions IT marked as sandbox receivers. The others get none of the
  project's events while the run holds: they wait, in order, and go once a person stops the run.
- **Connectors** stay read-only: a write waits for a person (the hook `write_hold`, for the connector
  path to ask; connectors are not called yet).

When the time is up the delegation ends and no pass runs, but the sandbox still holds until a person
stops the run, because only a person releases what the run held back. Track says so. Stopping revokes
the delegation at once. Who may start or stop one: the personas who may pause a project (business owner,
product owner, developer, operations, IT); a starting persona must also be one that decides each
delegated kind. One run holds a project at a time.

**A stopped pass stays in the sandbox (built).** A person may stop the autopilot while one of its passes
is under way (in the cockpit, the job is then still running). That pass stays bound to the sandbox to
its end: it delivers nothing, anywhere, and writes through no connector, even though the run no longer
holds the project. It ends at its next safe point, between pipeline steps or between tasks, in the state
`stopped`, and the job that runs it ends there too; the stop is on record once (`autopilot_held`, what
`pass:stopped` or `delivery:after_stop`). A cell already working is not cut off mid-step, as with a
pause (FR-J3): it finishes its step, and its work stays in the sandbox's lanes. The cockpit's Stop says
so beside the job. Only a pass a person runs afterwards (`rihmasto run <pid>`, or Advance) delivers, in
that person's name.

A sandbox road, as IT writes it in `paved_roads.json`:

```json
{"schema": "gnomonfactory.paved_roads/1",
 "maturity": {"demo": "test-demo"},
 "roads": {"test-demo": {"kind": "local-process", "configured": true, "environments": ["demo"], "sandbox": true}}}
```

## Staying on track

`rihmasto track <pid>`, the cockpit's Track view and the MCP read `rihma_track` all answer the same,
deterministically, from the project's own records:

| Figure | Its basis |
|---|---|
| Approved plan | the plan a person approved, or at a maturity that approves none, the first compiled contract |
| Tasks | contract tasks merged and left |
| Gate, first round | tasks that passed their gate on the first round; the trend from the earlier half of the gated tasks to the later half (from four gated tasks) |
| Assumption debt | open assumptions, and those past their due date |
| Scope changes | changes applied since the baseline |
| Holding the run | open cards that hold the run, with their age |
| Time | time used from the baseline to the due date, beside the share of tasks done |
| Cost | cloud spend of the priced runs against the budget, in the price table's currency |
| Posture | whether the run keeps the posture chosen for it, from `kernel.posture.track_posture` |
| Health | what the project's health reads besides these: approvals gone stale, and a last release that stopped |

A figure with nothing to rest on is **not measured**, with the reason: never zero and never passed.
The answer:

- **off track:** a person stopped the build; a card has held the run for 7 days; the due date passed
  with work left; spend is over the budget;
- **at risk:** an open escalation, holdout ruling or incident; a card that has held the run for 3 days;
  an assumption past due; first-round passes falling by 25 points or more; 3 or more changes since the
  baseline; 80% of the time used with less of the work done, or 80% of the budget spent; a posture not
  kept; a checkpoint due; an autopilot whose time is up and still holds its sandbox; an approval gone
  stale; a last release that stopped;
- **on track:** none of those, against an approved plan;
- **not measured:** none of those, and no plan approved yet to be on track with.

Each reason names the figure it rests on.

**One answer per project.** The cockpit's project header shows one on-track answer: the Track pill. It
replaces the health chip there (the track carries every reason the health reads, so the pill is never
better than the health), and the overview's Health card shows the same answer with the track's reasons
(then any health reason the track does not already name, such as a second open escalation) and the
forecast. Before a plan is approved the pill says "Track: Not measured", never "On track".

**Human checkpoints** are stage boundaries a person must look at, set per project by a plan owner
(business owner, product owner or developer). A checkpoint is due once the project reaches its stage,
and from stage 5 on, again at each new contract revision, until a person records a look. With **hold**
on, the pipeline stops at a due checkpoint and goes on at its next pass after the look.

**The daily digest.** IT has a Teams, Slack or email notice subscription ask for it, and once a UTC day
the relay sends one notice: how many projects are on track, at risk, off track or not measured, a line
per project, and one link, to the cockpit's Home. Titles are defanged as every notice's are; nothing in
it decides anything. A failed digest is tried again on the next round; every attempt is in the relay's
delivery log. While an autopilot holds a project, the digest to a subscription IT has not marked as a
sandbox receiver leaves that project out (no title, no reason), says only how many projects it left
out, and the delivery log names them (`sandbox_held`); a sandbox receiver's digest lists it.

## Tutorial: let it run overnight in a sandbox

1. See where it would land: `rihmasto autopilot status <pid>` shows the sandbox. An explore project
   lands on the local preview, a sandbox. A demo project needs a demo road IT marked `"sandbox": true`.
2. Start it, delegating what you are willing to let the rules decide:

   ```bash
   rihmasto autopilot start <pid> --until 12h --delegate question,approval,escalation \
     --person Aino --persona developer --reason "try it overnight"
   ```

   In the cockpit: open the project, the **Track** tab (or the **Track** pill in the header), **Start an
   autopilot**, tick the kinds, pick how long, and press **Start the autopilot**. It runs as a job.
3. In the morning, read **Track**: the answer and its reasons, the cards decided by the delegation, and
   the cards it left to you with why. `rihmasto autopilot status <pid>` says the same.
4. Decide what it left you in the Inbox, then `rihmasto autopilot run <pid>` for more passes, or stop it:
   `rihmasto autopilot stop <pid> --person Aino --persona developer`, or **Stop the autopilot** in Track.
   Stopping revokes the delegation and releases the events it held back. If a pass is still under way,
   it delivers nothing more and ends at its next safe point; then run or advance the project yourself
   to deliver.

## Tutorial: keep a tight hold

1. As a plan owner, set the stages you want to look at, and have them hold the run:
   `rihmasto tracking set <pid> --checkpoints 4,6 --hold --person Ida --persona product_owner`, or in
   the cockpit, **Track**, **Set checkpoints and a budget**.
2. Add a due date and a budget if you have them: `--due 2026-12-31 --budget 400`.
3. When the project reaches stage 4 the run stops, the Track pill says "checkpoint due", and Home's
   **Staying on track** widget lists it. Look at the spec, then record it:
   `rihmasto tracking look <pid> 4 --person Ida --persona product_owner --note "the spec reads right"`,
   or **I looked** in Track. The next pass goes on.

## Tutorial: watch it from your own tools

1. IT has an existing notice subscription take the digest:
   `rihmasto tracking digest SUB-002 daily --person Ilkka --persona it` (`off` to stop it).
2. Each relay round (`rihmasto relay run`) sends it once a day; `rihmasto relay log` shows each attempt.
3. Your own coding agent reads the same through the MCP server: `rihma_track` and `rihma_autopilot`.

## Commands

```text
rihmasto autopilot start <pid> --until 8h --delegate question,approval,escalation --person ... --persona ...
                       [--rule question=assume] [--reason ...] [--passes 20] [--arm-only]
rihmasto autopilot run <pid> [--passes 20]
rihmasto autopilot status [<pid>]
rihmasto autopilot stop <pid> --person ... --persona ... [--reason ...]
rihmasto autopilot relay SUB-001 [--off] --person ... --persona it      a sandbox receiver, or not
rihmasto delegation grant <pid> --kinds question --until 2d [--rule KIND=RULE] --person ... --persona ...
rihmasto delegation revoke <pid> DL-001 --person ... --persona ... [--reason ...]
rihmasto delegation list <pid> | delegation rules
rihmasto track [<pid>]
rihmasto tracking set <pid> [--checkpoints 5,6] [--hold | --no-hold] [--due YYYY-MM-DD] [--budget N]
                      [--currency EUR] --person ... --persona ...
rihmasto tracking look <pid> <stage> --person ... --persona ... [--note ...]
rihmasto tracking digest SUB-001 daily|off --person ... --persona it
```

The cockpit's JSON API: `GET /api/projects/<pid>/track`, `PUT /api/projects/<pid>/tracking`,
`POST /api/projects/<pid>/checkpoints/<stage>/look`, `POST /api/projects/<pid>/autopilot`,
`POST /api/projects/<pid>/autopilot/stop` and `POST /api/projects/<pid>/delegations/<DL-n>/revoke`,
each write signed with `person` and `persona`; `GET /api/dashboard` carries `track`.

## The record

| Ledger kind | When |
|---|---|
| `delegation_granted`, `delegation_revoked` | a delegation starts or is revoked, with who and until when |
| `decision` with `delegation` | a card decided under a delegation |
| `delegated_decision` | the same decision's rule and basis |
| `delegation_declined` | a rule left a card to a person, and why (once per card) |
| `autopilot_started`, `autopilot_pass`, `autopilot_held`, `autopilot_stopped` | a run, each pass, a hold at the sandbox's edge, the stop |
| `checkpoint_reached`, `checkpoint_looked`, `tracking_set` | checkpoints and the budget |
| `relay_marked` (factory ledger); `sandbox_held`, `digest` (relay's delivery log) | IT's marks; the relay's holds and digests |

## Hooks for other parts

- `kernel.autopilot.posture_preset()`: the "autopilot sandbox" preset for kernel/posture.py to offer.
- `kernel.posture.track_posture(project)`, when defined, answers Track's posture figure:
  `{"posture": <name>, "keeps": true | false | null, "basis": <why>, "drift": [<what differs>]}`.
- `kernel.autopilot.write_hold(project, system, tool)`: a connector's write asks it first; not None means
  wait for a person.
- `kernel.autopilot.outbound_hold(project, subscription)`: the relay asks it for each project's stream.
- `kernel.autopilot.delivery_hold(project)` and `kernel.track.checkpoint_hold(project)`: the pipeline
  asks them; `kernel.delegation.consult(project, waiting_on)` before it waits.
