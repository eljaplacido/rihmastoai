# Enforcement levels: how strict each stage is

How strictly Rihmasto holds work in development, testing and production, per check family, for all projects and
for one ([D-0026](../../decisions/D-0026-enforcement-levels.md), FR-ENF1, FR-ENF2). By default Rihmasto observes
and advises everywhere: nothing waits on you until you turn enforcement on.

## The levels

For each **environment** and each **check family** one level applies:

| Level | What Rihmasto does | Does the work wait? |
|---|---|---|
| off | does not look; the project's own pipeline still does what it does | no |
| advise | a note in the project's record and a nudge in its view and in Ask Rihma (the default) | no |
| require review | a card for the named reviewer; the review is owed | no |
| enforce | a card for the named reviewer | yes, until that reviewer decides; an approval is the override, recorded with its person and reason |

- **Environments:** development, testing and production. Rihmasto's own preview and demo count as development,
  staging as testing. A pipeline's environment is placed by its whole name (dev, local, preview: development; test,
  staging, qa, uat: testing; prod, live: production); a name Rihmasto does not know counts as production until a
  person places it ("treat eu-west as production").
- **Check families:** quality (tests, the pipeline's runs, probes, the gate's verdict), security (findings,
  secrets, dependency audits), legal (licences, the bill of materials) and governance (a change entering the
  environment, its approvals and audits). Governance has a say on every change entering testing or production; in
  development only once you set it above advise.
- **Presets:** advise everywhere (the default), the split (advise in development, require review in testing,
  enforce in production) and strict.

## Platform-wide and per project

| Where | Who sets it | Recorded in |
|---|---|---|
| **Settings > How strict each stage is** (all projects): the levels every project starts from, presets, the reviewer per family, and the projects that set their own | business owner, IT, compliance or developer, signed | the factory's ledger |
| **A project's Enforcement view** (Govern capsule): its own level for any cell (or *As for all projects*), its reviewer per family, and Give back to the platform | the same personas, signed | the project's ledger |

Every cell says where its level comes from: this project, all projects, or Rihmasto's default. Loosening a level
needs a reason. **Preview** says what a change would do before anyone makes it: the cells, what would happen
next there, how the recorded outcomes would have differed, and which projects keep their own setting.

In solo mode you hold every reviewer persona: advise everywhere means nothing waits on you, and only what you set
to enforce blocks work. In team mode the named reviewer decides, under team mode's access rules.

## The project's own pipeline, taken as given

The Enforcement view reads the repository's GitHub environments (required reviewers, wait timers, which branches
may deploy) and its default branch's protection with your own `gh` sign-in, GET requests only, and never writes
there. Per environment it says whether the two **agree**, **the pipeline is stricter** (Take the pipeline's split
makes it Rihmasto's levels too), **Rihmasto is stricter** (it says where in GitHub a person could add reviewers),
or there is **nothing to compare**, with why and how to fix it.

## Where the levels apply

Rihmasto's own checkpoints apply them: its gate on a change of an attached repository (development), the deploy
step of a release (each environment it enters, after the security gate) and an automation that changes something.
The deploy gate card (IT, before production) and the security gate stay as they are: the levels add to them and
never loosen them. Every outcome (noted, review, held, cleared) is in the project's ledger with the environment,
family, level, subject and card; a cleared one carries its override. A review is decided in the Inbox or on the
Enforcement view, by the named reviewer.

## In Ask Rihma

Ask "how is production enforced here?", "require review in test", "use the split", "treat eu-west as production"
or "the gate's changes go to testing". Rihma answers by rule, with no model, and proposes the change with the
preview's lines; it runs only when you confirm it, signed, through the same route as the view.

## The API

`GET` and `PUT /api/enforcement` (all projects), `POST /api/enforcement/preview`, and `GET` and
`PUT /api/projects/<pid>/enforcement` (one project). The kernel is `kernel/enforcement.py` (levels and scopes),
`kernel/enforcement_guard.py` (the runtime decision), `kernel/enforcement_pipeline.py` (the pipeline, read only),
`kernel/enforcement_places.py` (placing environments) and `kernel/enforcement_chat.py` (Ask Rihma).

Related: [people in the loop](people-in-the-loop.md) (each check family's asks, advised or required),
[never lost](never-lost.md) (Harness and enforcement: Gnomon's own enforcement), [access](access.md).
