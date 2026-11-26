# Review what agents shipped: since you last looked

> "You're not supposed to watch Claude Code work. You're supposed to wake up and review what it shipped."
> (quoted by the owner, 2026-11-24)

Agents and automations work while you are away: builder cells merge tasks through the gate, releases go to
a test environment, an autopilot decides cards in your name by a delegation, the factory assumes answers,
a developer gates a commit from their IDE, a job fails. The **Review** is the one place to look at all of it
afterwards: what happened since you last looked, grouped by what needs you, each item linked to its record
and saying who or what did it. You act on it in place, mark what you looked at, and mark the whole review
done. It is a read of the records (the canon and the ledgers); reading it records nothing.

## The morning habit

1. Open **Review** (the first item in the sidebar), or Home's first card, **Since you last looked**:
   "Since you last looked: 3 shipped, 2 waiting on you, 1 failed".
2. Decide what waits on you. Look at what went wrong. Overturn what was decided in your name that you
   would not have decided.
3. Open each shipped change's preview: its diff file by file, the gate's verdict and signals, its rounds.
   Press **Reviewed** on what you looked at, or **Report a change** on what you dislike.
4. Press **Mark all reviewed**. Your next review starts there.

On a phone the page is one column and the preview is a full-screen sheet.

## What each group means

| Group | What is in it | What you can do in place |
|---|---|---|
| **Waiting on you** | The open Inbox cards your persona may decide, on every project and the factory's own canon, with how long each has waited: questions, approvals and go-ahead cards, escalations, deploy gates. A card that came since you last looked says **new**. | Approve or decline (the card's own verdicts, signed); answer a question or let Rihma assume; open the card. |
| **Went wrong** | Gate failures, escalations, failed releases, probes and incidents (a Cloud Run job's failed execution opens one), rollbacks, model endpoint failures, refusals (a confidential step that would have left for a hosted endpoint, a task a cell runner would not run, a paved road refused), automations paused (by a person or their breaker) and automation runs that failed or were refused, failed checks (`check_ran`), console commands that failed, ran out of time or did not start, and the cockpit's failed jobs. | Mark it seen; report a change; open the record. |
| **Decided for you** | The decisions a delegation or an autopilot run made in your name (each with its rule and why), and the assumptions the factory made, with their due dates. An overdue assumption stays here until it is settled. | Confirm or **Overturn** an assumption (refuted with your correction: a change card opens); overturn another decision by reporting a change about it; **Stop the delegation**. |
| **Shipped** | Tasks merged, with the gate's verdict, the rounds it took and the diff stats; releases to test and to production; outputs built. | **Reviewed** (a signed `review_marked` record: the record now shows a human looked; it approves nothing); report a change; open the task or release. |
| **From your IDE** | Commits gated on an attached or adopted repository ("gate my code", or a workspace submission): the verdict, who asked, the criteria the task touches and the diff. | Reviewed; report a change. |
| **From agents** | The project's agent channel ([agentic help](agentic-help.md)): coding agents' progress posts, their proposals still waiting on a person (first, however old), and the gate and check results agents asked for. | Open the channel; settle a proposal there. |
| **Cost and usage** | The period's model runs by project and role: runs, tokens in and out, and the priced cost. With no run recorded, it says **not measured**, never zero. | |

Every row says who or what did it: a person (with the persona), a Rihma agent's role (with its model and
the runner or harness that ran it), the kernel's rule, an automation, a delegation, or an autopilot run in a
person's name. Every row links to its record: the card, the task, the release, the assumption, the
decision in the ledger, and the diff in the preview.

## Since when

Your first review covers the last 24 hours. **Mark all reviewed** records `review_done` (in the factory's
ledger, or in a project's for that project's **Review** tab) with the period and how many items each group
held, and keeps each ledger's last record beside the time, so your next review starts exactly there and
never shows a record twice. The marker is yours: another person's review starts at theirs. **24 h** and
**7 days** look back further without moving the marker.

## Keys

| Key | Does |
|---|---|
| `j` / `k` | the next / the previous row |
| `Enter` | opens the preview drawer (`Esc` closes it) |
| `a` | approve: the card's approving verdict, or confirm an assumption |
| `d` | decline: the card's declining verdict, or overturn |
| `r` | reviewed (or seen) |
| `o` | opens the record |

A key that needs words (an answer, a reason, a correction) opens a short dialog first. Nothing happens
while you type in a field.

## The morning digest

**Morning digest** on the Review page sends you the same review as a message: the headline, each group's
count with its first items, and one link back to the Review. You choose the time (`07:30`), the days
(weekdays, or every day), your time zone (`Europe/Helsinki` where the machine has the zone database, or an
offset such as `+02:00`) and the receiver: one of the Teams, Slack or mail subscriptions IT configured for
your persona ([the integrations guide](integrations.md)). The setting is signed and kept in the factory's
ledger (`review_digest_set`).

The relay sends it: each round (`rihmasto relay run`, which IT schedules every few minutes) sends a digest
that is due, once on each of your local days. Its period starts at the later of your last review and your
last digest, so a morning never repeats yesterday's. When nothing happened in it, the digest is held back,
and the delivery log says so (`review_digest`, `held back`). A project an autopilot binds to its sandbox is
left out for a receiver that is not a sandbox receiver; the message says how many were left out. Nothing in
the message decides anything: you decide in the cockpit.

The automations run the same digest from the template "Morning review digest" (an automation with the
`review_digest` action and a relay subscription, [automations](automations.md)): every morning it sends its
owner's review, and holds it back when nothing happened. The relay round above stays the other way.

## The command line

```
rihmasto review [<pid>] [--since 24h] [--json] [--person P --persona X]
rihmasto review mark <item>... --person P --persona X [--note "..."]
rihmasto review done [--project <pid>] --person P --persona X
rihmasto review digest SUB-001 --at 07:30 --days weekdays --tz +02:00 --person P --persona X
rihmasto review digest off --person P --persona X
```

An item is `<project>/task/T-001`, `<project>/release/1`, `<project>/gate/<record>`,
`<project>/ledger/<record>` or `<project>/assumption/A-001`, as `rihmasto review` prints it. A card is
decided, not marked. While access is enforced, the command signs as the local user the access file names,
with a persona granted on the factory.

## The API

| Method and path | What it does |
|---|---|
| `GET /api/review?person=&persona=&since=&project=` | the review: `headline`, `since`, `until`, `basis`, `counts`, `groups` with their items, `cost`. Records nothing |
| `GET /api/projects/<pid>/review?person=&persona=&since=` | one project's review |
| `GET /api/projects/<pid>/review/detail?item=task/T-001` | one item's preview: the diff (file by file, cut at a readable size), the gate's signals and objections, the record's facts |
| `POST /api/review/mark` | `{items, person, persona, note?}`: `review_marked` per item in its project's ledger, and a `cockpit_write`; a card, an unknown item or a non-person records nothing |
| `POST /api/review/done` | `{person, persona, project?, since?}`: `review_done` with the counts; the marker moves |
| `GET /api/review/digest?person=&persona=` · `PUT /api/review/digest` | your digest and the receivers you may choose · `{subscription, at, days, tz, person, persona}` or `{off: true, ...}` |
