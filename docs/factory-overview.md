# Rihma: the whole delivery, from business need to measured benefit

Status: design, 22 Nov 2026. Takes in the owner's seven-stage model and the "Toimitusneliö"
(delivery square) operating model. Everything here follows decisions D-0001 to D-0005: the
factory is independent, Gnomon is its only runtime dependency, and no model family is
assumed.

## The principle that frames the rest

**The factory's technical implementation does not define how a customer turns needs from
daily operations into concepts and requirements.** Those stages belong to the business. The
factory gives each stage:
- a contract at its boundary (what goes in, what comes out);
- agents that do the heavy work;
- a named human who decides;
- a check that keeps the gate shut until it is proven.

It also gives every stage a way back. Tools are views, not the process: a stage may live in
Teams, Jira, Azure Boards or the cockpit, and it reads and writes the same canon.

Three rules hold everywhere (the owner's wording, and they match the factory's rules of
evidence):

1. **A requirement is a unit, not a task.** It has a state, a source, an owner and an
   executable test, through the whole chain.
2. **A gate reads evidence, not a report.** An empty gate is not a pass ("not measured").
   A rejection returns work to the right stage and **invalidates every later approval**
   that depended on it.
3. **Feedback never goes straight to implementation.** The business decides whether a
   requirement, a priority or the UI changes. The change then travels the same route as
   everything else.

## Seven stages

| # | Stage | In | Agents do | Out | Human decides | Gate check | Today in the design |
|---|---|---|---|---|---|---|---|
| 1 | **Need and decision** | business need, current state, a measurable baseline | transcribe walkthroughs and interviews, assemble the baseline, estimate benefit and ROI, draft the decision material | decision material: need, benefit, cost, recommendation, owner, acceptance criteria, scope | business: continue, investigate further, or concept; names owner and criteria | why now, for whom, what changes, how value shows, who owns it; every assumption written down | **Gap**: added as P-group requirements |
| 2 | **Concept factory** | work instructions, spreadsheets, process descriptions, recordings | discover: question list; build: UI concept and requirements; iterate on recordings; package the concept with open questions | functional requirements with state (confirmed, proposed, assumed), UI concept, open questions | SME and end users test the concept; the PM approves the package for the factory | every requirement has state and source; the user flow is understood without guidance; content comes from the business, not a consultant | **Gap**: the factory treated the concept as input; now a stage with its own gate |
| 3 | **Technical translation** | concept package | translate into a build brief; report what carried and what was dropped; separate confirmed from assumed | build brief, translation report, list of open requirements to decide | the open requirements: the process owner decides before building; the factory makes no business decisions | confirmed requirements carried into the brief; dropped items visible; no open requirement left for the factory to decide | **Covered**: closed intake contract, send-back, provenance tiers (FR-A1, A3, A5) |
| 4 | **Spec and architecture** | build brief, NFRs, integrations, data, performance, security | technical spec, architecture, an executable test per acceptance criterion, ADRs | technical spec, architecture, test plan where every criterion has a test | architect approves; spec, architecture and test plan reviewed as a diff | a criterion without an executable test keeps the gate shut; ADRs per decision; NFRs measurable | **Covered**: the spec-to-verify chain (contract, check plan, holdouts) |
| 5 | **Build and verify** | approved spec, test plan, a branch per work item | roled agents code, test and document phase by phase; a failed gate starts a bounded repair | runnable app, test and quality reports, PR, immutable audit log | developers review PRs; agents escalate what they cannot resolve | the gate reads test results, not reports; an empty gate is no pass; repairs bounded, otherwise escalate | **Covered**: Gnomon cells, gates, `gnomon check`, criterion trace (running now) |
| 6 | **User validation** | test-ready version: complete user journey, real users, real tasks, realistic data | prepare test tasks and data, transcribe sessions, structure observations (UI gap, requirement, data, defect), link them to requirements | test report, observation log with owners and severities, updated concept, acceptance decision | end users test, a facilitator observes, the business decides: accept, fix, change or keep | understandable, correct, timely; every finding is linked to a requirement and an owner | **Gap**: holdouts covered automated checks only; now a stage with testers |
| 7 | **Deploy and measure** | approved version, deploy package (agent, instructions, environment as code), baseline metrics | the deploy agent dry-runs and logs for IT; release and onboarding docs; benefit measured against the baseline | production deployment by customer IT, release docs, benefit report: planned vs realised | **customer IT** runs it with its own identity, one environment at a time; the **business owner** accepts the benefit | dry run and log approved; no deploy without IT's go; benefit measured with the same metric as the baseline | **Partly**: canary, health, signals covered; IT ownership and benefit-vs-baseline added |

## The ways back

| Trigger | Goes back to | Who decides | Mechanism |
|---|---|---|---|
| The package did not carry (translation report shows dropped or unclear content) | 2 Concept | PM and concept owner | send-back with a fix list, acknowledged by hash |
| A user cannot use it; a UI gap | 2 Concept | business, after the SME looks | observation from stage 6 or production, classified as "UI/concept" |
| A requirement changes | 1, as a business decision, then 3 (translation again), **never straight to code** | business owner | amendment signed in the Inbox → re-translation → recompiled contract → only the affected tasks reopen |
| A gate fails | 5, a bounded repair loop | none while in bounds; escalate past them | repairer cell, round limit, then the Inbox |
| IT finds something in deploy (network, security, resources) | 5, as a PR or card for development | IT raises it, development fixes it | `source:it` card or infra PR, with the command and its output as evidence |
| Measured benefit falls short of the target | 1, a new need and decision round | business owner | benefit report → new decision material |

**Invalidation rule.** When a stage's approval is withdrawn (a rejection, or an amendment
upstream), every later approval that depended on it becomes *stale*. The cockpit shows it as
stale, and it must be given again. The kernel computes this from the ledger's dependency
links, not by hand.

## Four corners around one canon (the delivery square)

| Corner | Who | Writes into the canon (always as a proposal, then the gate) | Owns which gate | Sees |
|---|---|---|---|---|
| Customer business | project owner, SMEs, end users | wishes, feedback, meeting notes, acceptance of criteria | business acceptance (named on the board) | the shared view: epics, status, "waiting for you" |
| **Customer IT or IT partner** | the customer's IT, or its service partner | **environments as code** (network, security, cloud resources) as PRs to the shared repo; resource answers; deploy observations | the **deployment gate**, per environment | environments, technical decisions, the infra lane, "waiting for IT". Not commercial data or estimates. |
| Supplier business | project manager | epics, decisions, open questions, the status digest | the canon's gate (what becomes true) | everything internal |
| Supplier technology | developers, architect | features, code, PRs, hand-overs | PR review and merge | everything technical |

**What flows in from customer IT.** Infrastructure, cloud deployment, network rules and
security requirements arrive as:
- **PRs to environments-as-code** in the shared repo (`environments/`, reviewed by IT);
- **requirements** with provenance `it-confirmed`, for example "egress only through the
  proxy" or "TLS 1.3". These enter the contract like any other requirement, and the check
  plan proves them (a probe, or a dry run against the environment);
- **cards with `source:it`** on the development board, for every merged infra change, so
  nobody has to ask what changed in the cloud.

Drift is checked on a fixed schedule: environment code is dry-run against the live
environment, and a change made in a portal shows up as drift, not as a surprise.

**Two approvals that look alike, and never substitute for each other:**
- **business acceptance**, a named person on the board;
- **the deployment gate**, an environment setting owned by IT, often approved by someone
  other than the person who reads the board.

The card always says which environment, and who can approve.

## The canon (project memory, one truth)

The factory's ledger and contract hold the technical truth. Around them, the canon adds the
owner's six items, each with one place, one writer and one cadence:

| Item | Where | Writer | Read as |
|---|---|---|---|
| Goal: why the project exists | `canon/goal.md` | business owner, through the gate | every epic links to it |
| **Epics**: the customer's wishes, each with goal, owner and criterion in the owner's words | `canon/epics/` | a human creates them; agents draft into `canon/inbox/` | the customer's board, "what did we ask" |
| Decisions, with reasons and evidence links | `decisions/` (exists) | owner, architect, PM | everyone |
| **Assumptions, each with a due date** | `canon/assumptions/` | PM; the Watch raises overdue ones | the Watch's daily query |
| Open questions: who answers, by when | `canon/questions.md` | agents propose, the PM approves | "waiting for you" and "waiting for IT" columns |
| Status digest | `canon/status/` | Status agent drafts, PM approves in 15 minutes a week | internal and shared channels |

Two folders the owner's model separates and the factory keeps:
- `canon/inbox/` holds **proposals for a human** (nothing there is true yet; empty is good);
- `canon/exchange/` holds **notes between agents**, deleted once the conclusion is in the
  canon. A memory that empties is not a memory, and an inbox that never empties stops being
  read.

**An epic qualifies only with three things:** a named business owner, an acceptance
criterion in the owner's words, and its blocking questions linked. An epic written as a
solution has skipped the point where someone could have said no.

## Agents across the stages

The six build roles (scout, builder, verifier, assembler, repairer, triager) cover stages 4
and 5. The stages around them need narrow roles too. All run in Gnomon. Each has a one-page
card that is both its instruction and its limit, and writes only to `canon/inbox/`, a
branch, or `canon/exchange/`:

| Role | Stages | Does | Never |
|---|---|---|---|
| Scribe | 1, 2, 6 | turns meetings and sessions into notes: decisions, tasks, risks, questions | interprets unclear speech as a decision |
| Concept | 2 | question lists, UI concept, packaging with open questions | invents business content |
| Translator | 3 | build brief, plus the carried and dropped report | decides an open requirement |
| Status | all | weekly digest draft, internal and shared versions | publishes the customer version itself |
| Watch | all | raises drift: scope creep, overdue assumptions, orphan features and epics, stuck gates | writes anywhere; alerts daily on the same thing |
| Board keeper | all | keeps the canon and the boards consistent, generates views | opens or closes customer cards without approval |
| Onboarder | all | answers "where is this going" with sources | answers without a source, or shows internal content to the customer |
| Environment watch | 7 | reads infra-code changes and drift, proposes cards | changes an environment, even to fix drift |
| Deploy agent | 7 | runbook, environment requirements, dry run, feedback channel; runs in the customer's environment with the **customer's identity** | deploys without IT's approval, or uses the supplier's credentials |

## The cockpit, by who is looking

The nine technical views stay: Floor, Colony, Cell, Evidence, Thread, Pulse, Immune, Reef
and Inbox. Around them, each persona gets an entry view and its own write path. Every
write is a signed proposal or decision. Visibility follows the square: customer views never
show internal or commercial data.

| Persona | Opens on | Sees | Can do |
|---|---|---|---|
| Business owner | **Decisions and benefit** | epics and their state, decisions waiting, **benefit vs baseline**, stale approvals | decide, accept criteria, reprioritise, reject an epic with a reason |
| Concept owner or SME | **Concept and fidelity** | requirement state (confirmed, proposed, assumed), what carried from the package, open questions, the concept validation results | answer questions, confirm or change a requirement, approve the package |
| **End-user tester** | **Test and feedback** | assigned test tasks with realistic data; their own observations and what happened to each | report an observation (screenshot, steps, severity), linked to a requirement automatically where possible |
| **Customer IT or IT partner** | **Environments and deploy** | environments as code, drift, the infra lane, deploy queue per environment with approvers, "waiting for IT", deploy-agent logs | approve or refuse a deployment per environment, raise an IT observation as a PR or card |
| Project manager | **Canon and health** | inbox, status digest, orphan queries, gate health, assumptions due | approve proposals into the canon, publish the digest |
| Developer or architect | **Floor, Colony, Cell, Evidence, Thread** | technical state | review PRs, handle escalations |
| **Maintainer (production)** | **Operate** | service health and SLOs, incidents, recurrence, dependency and security updates, drift, runbooks | open a repair, accept a pre-approved repair class |
| Auditor | **Thread and evidence** | the signed thread from need to production | read only |

**Health queries the Watch runs on a cadence.** Each has an owner; an empty answer is
good:
- Is anything waiting for me?
- What are we waiting for from the customer, and from IT?
- Is a hand-over older than the last commit?
- Is a deployment waiting for approval, and who can approve it?
- Are there features without an epic, or epics without a feature?
- Did a meeting leave no decision, question or epic change within two days?
- Has a gate been shut longer than five days, or opened by a non-human?
- Does each environment match its code?
- Were any epics rejected or frozen, and why?

## Integrations and the tool-is-a-view rule

Views are generated from the canon into wherever each party already works (Teams, Jira,
Azure Boards, Planner, or the cockpit). A customer tool that must stay becomes where that
party's view lives, with key, title and state mirrored back. An integration is built only
after the agreement has worked by hand for a week. Otherwise it automates the mess. Every
sync ends in a proposal, never directly in the canon.

## Where this lands in the roadmap

| Item | Milestone |
|---|---|
| Canon folders, epic level with the three qualification conditions, inbox vs exchange, the "waiting for you" and "waiting for IT" columns | M1 |
| Stage gates 1–3 as Inbox decisions; the translation report; send-back | M1 |
| User-validation stage: tester view, observation log, routing back | M2 |
| IT axis: environments as code in the shared repo, `source:it` cards, drift dry-run, deploy package and deploy agent, the deployment gate owned by IT | M2 (delivery) |
| Approval invalidation (stale approvals) computed from the ledger | M2 |
| Persona entry views and visibility rules | M2–M3 |
| Benefit vs baseline (stage 1 metric re-measured at stage 7) | M3 |
| Generated views into Teams, Jira and Azure Boards; ITSM adapter | M4 |
