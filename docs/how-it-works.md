# How Rihma works

Rihma carries a need through one chain: intake, spec, contract, build, gate, holdouts, delivery,
operation, and back through the change loop. Models propose at each step. The kernel, which has
no model in it, decides whether the work is accepted. People decide what matters, and every
decision names a person.

## The chain, step by step

### 1. Intake

A request comes in as a vague idea, a markdown spec, a folder of documents, or a signal from the
[delivery square](#the-delivery-square). A **panel of perspectives** reads it: business, end user,
IT and security, operations, and delivery. Each asks the questions whose answers change what
gets built, with the answer it would assume. Where perspectives disagree, the opinions stay side
by side on the question. They are not averaged.

The **mode** decides what happens to each question:
- `socratic`: every question goes to a person, as an Inbox card;
- `assume`: the factory takes each proposed answer as an assumption with a due date;
- `mixed` (the default): blocking questions go to a person, the rest are assumed.

A person can answer any open question, or let the factory assume. The **work profile** adds the
questions its kind of work always needs ([guides/profiles.md](guides/profiles.md)). The brief is
generated from the canon, with every statement tagged `[owner]`, `[assumed]` or `[proposed]`.

### 2. Spec

The analyst drafts requirements, each with given / when / then criteria and a fixed HTTP
interface. The kernel, not the model, decides ids and **provenance**:
- a requirement resting on an answer is *customer-confirmed* by whoever answered;
- one resting on the request is *customer-endorsed* by whoever asked;
- one resting on an assumption is an *assumption*;
- anything else is *vendor-proposed*.

A spec is not written while blocking questions are open: the intake sends back the list. The
**maturity** (explore, demo, pilot, production) sets how many requirements and which stages run.
At pilot and production, a person approves the plan before anything is built.

### 3. Contract

A compiler with no model turns the spec into a contract and a check plan. The same spec always
compiles to the same contract, and its hash is its revision. The compiler fails loudly if a
criterion has no check or no task, or a task serves no criterion. The product's repository starts from the
paved-road template with the contract inside, and a Gnomon surface that grants nothing beyond
Gnomon's defaults.

### 4. Build

Each task becomes an **envelope**: the requirement, its visible criteria, the scope it may write,
and the rules. A Gnomon **cell** runs the envelope as the builder role, in a **lane** (a clean
clone of the product repository, one run at a time). Gnomon enforces the write scope, the
sandbox and the shell rules while the cell works.

### 5. Gate

The kernel judges the cell's work itself, apart from the builder. Four signals:

| Signal | Passed when |
|---|---|
| tests | the product's whole suite, run by the kernel, exits 0 |
| trace | every visible criterion of the task is named by a test (`test_R_1_AC_2_...`) |
| fail-first | each criterion's tests fail at the base revision (or, where an earlier task already met the criterion, on the bare template) |
| verifier | a read-only reviewer from another model family finds nothing high and in scope |

A task merges only when it is *warranted* (the combined verdict is passed) and *permitted* (a
policy or a named person). Otherwise its objections go into the next round. After two repair
rounds it **escalates**: a person decides retry, accept as is, or stop, with every objection on
the card.

### 6. Holdouts

A different role, the holdout author, writes end-to-end scenarios for the criteria marked
`holdout` or `probe`. They live in a **separate custody** (`<home>/holdouts/<id>/`), outside the
project folder and every lane, so a builder never sees them. They run against the deployed
service over HTTP. When one fails, a person rules whether the product or the scenario is wrong.

### 7. Delivery

The maturity picks the plan and the [paved road](guides/deploying.md):

| Maturity | Lands on | A person decides |
|---|---|---|
| explore | a local preview process | nobody |
| demo | the `demo` environment, after holdouts | the business owner accepts the demo |
| pilot | `staging`, after holdouts | end users validate: accept, fix, change or keep |
| production | `production`, after IT's deploy gate, shadow and canary | IT at the deploy gate |

A road missing or not configured is a card for IT; the factory never guesses a target. Each
release can carry a [capability pack](guides/packs-and-evidence.md) that pins every hash.

### 8. Operation

Probes check `/health` and every `probe` scenario. A failing probe opens one incident card per
release and environment. A canary worse than the current release is rolled back with no person
needed, and the rollback opens an incident.

### 9. The change loop

Feedback and changes come from any persona. Triage classifies each and sends it back to its
stage:

| Class | Goes back to | Needs a decision first |
|---|---|---|
| defect | 5, build: a regression criterion and a repair task | no |
| change request | 4, spec: an amendment | yes, a business decision |
| new requirement | 1 to 2: the panel reads it | yes |
| infra change | 7, the paved road | IT decides |
| incident | 7, operation: rollback, then a defect | no |
| question | 2, the canon's questions | no |

An amendment marks every later approval that rests on the changed requirement **stale**. It must
be given again. Every defect leaves a regression check, its lesson.

### 10. Learning

When lessons recur across products, Rihma proposes a **default check** for every future product.
A person accepts it before it applies (`rihma learn`). The ledgers also give each builder model's
record: cells run, first-round pass rate, escalations, rounds to pass. That is the evidence a
routing change rests on; Rihma never re-routes on its own.

## The seven stages

The chain maps onto seven stages, grouped in four bands for people who do not think in stages:

| Band | Stage | What happens | Who decides |
|---|---|---|---|
| Decide | 1 Need and decision | the request, the panel's reading, the baseline | the business |
| Decide | 2 Concept | questions, assumptions, opinions | the people who answer |
| Shape | 3 Technical translation | the brief becomes requirements with provenance | rules |
| Shape | 4 Spec and architecture | criteria, the contract, the plan | rules; a person approves the plan at pilot and production |
| Deliver | 5 Build and verify | cells, gates, repairs, escalations | the gate, then people on escalation |
| Deliver | 6 User validation | staging, holdouts, end users testing | the business |
| Run | 7 Deploy and measure | paved roads, IT's gate, shadow, canary, probes | IT, then the canary rule |

[factory-overview.md](factory-overview.md) has the full table: inputs, outputs and the gate check
of each stage.

## The delivery square

Four corners work around one **canon**, the project's single truth: its goal, brief, questions,
assumptions, decisions and Inbox.

| Corner | Who | Owns which gate |
|---|---|---|
| Customer business | owner, experts, end users | business acceptance |
| Customer IT or partner | IT, or its service partner | the deploy gate, per environment |
| Supplier business | project manager | what becomes true in the canon |
| Supplier technology | developers, architect | review and merge |

Business acceptance and the deploy gate look alike, and never stand in for each other.

Needs reach the square as **signals**: a chat, a data feed, a monitoring alert, a meeting, a
website chat. A signal about an existing project becomes a change there. A new need becomes a
**concept** that a business owner or product owner validates into a project. See
[guides/signals-and-concepts.md](guides/signals-and-concepts.md).

## Personas and lenses

Every decision is signed with a person and a **persona**. The persona decides which cards a
person may decide. Who may decide each card kind is fixed in the kernel (`CARD_DECIDERS` in
`kernel/canon.py`):

| Persona | Starts in the lens | Decides, for example |
|---|---|---|
| business owner | business | approvals and the plan, validations, changes, escalations, holdout rulings, concepts, updates; sets the autonomy cap |
| product owner | concept | the same cards as the business owner |
| concept evaluator | concept | answers questions, settles assumptions |
| end user | business | reports what they saw; answers questions |
| IT | operations | the deploy gate, paved roads, incidents, trust, updates; sets the autonomy cap |
| developer | delivery | approvals and the plan, escalations, incidents, holdout rulings, trust, updates |
| operations | operations | incidents |
| stakeholder | business | answers questions, requests changes |
| compliance | compliance | updates; exports evidence packs; sets the autonomy cap |

A **lens** is the same project seen for one purpose. Each answers one question:
- **business:** what is coming, when, and what does it need from me?
- **concept:** what do we assume, and what does the plan say?
- **delivery:** how is the run going, and why did something fail?
- **operations:** what runs in production, and is it healthy?
- **compliance:** what ran, which versions, who approved, and was it checked?
- **insight:** how does the factory itself perform?

Anyone can switch lens. The project's current stage brings its own views forward: questions at
stage 2, the plan at 4, the live cell at 5, the try-it list at 6, releases at 7. The cockpit's
views are described in [cockpit.md](cockpit.md).

## The rules of evidence

- **Named verdicts.** The factory speaks in passed, failed, regressed, not applicable, not
  measured, violation and escalate; never a bare exit code. Combining them follows a fixed
  precedence: failed or regressed wins, then violation, then escalate, then not measured. Only
  passed and not applicable combine into passed.
- **"Not measured" is a state.** A check that could not run is not a failure and not a pass. A
  pass rate counts measured runs only; apparatus failures are counted beside it. A rate with
  nothing measured has no value, never zero. An unpriced cost is not zero.
- **Evidence per criterion.** Each criterion is *verified* (a gate passed at the merged revision
  and a test on main names it), *claimed* (a test names it, no gate proved it), *held out*
  (passed against a release), *failing*, or *not measured*. A claim is never shown as a fact.
- **A hash-chained ledger.** Every transition is appended to the project's ledger. Each record
  hashes the one before, so a rewritten or removed record breaks the chain. Gnomon's own audit
  trails are re-verified independently; a broken trail makes a run *tampered* and *not measured*.
- **People decide.** A decision needs a named person and a persona allowed to make it. "factory",
  "model", "assistant" and the like are never people. Models propose, the kernel decides, people
  own intent and policy.
- **The autonomy ladder.** Answer, suggest, prepare, deliver. A person sets the cap, and the
  kernel refuses anything above it ([guides/autonomy.md](guides/autonomy.md)).

## What Gnomon does, and what the kernel does

| Gnomon (the harness) | The kernel (Rihma) |
|---|---|
| Runs every model call: `gnomon task --role <role> --json` in a lane | Never calls a model API itself |
| Enforces a role's tools, write scope, sandbox and shell rules during a run | Compiles those rules into each lane's `.gnomon/` surface from the contract and the routing |
| Hashes the surface and stamps it on every record | Keeps the contract, its hash and every envelope |
| Writes a hash-chained audit trail per run | Re-verifies that trail itself and ingests the run into its own ledger |
| Reports an outcome: a bucket, an exit code, a stop reason | Maps it onto a named verdict; an unknown code is reported, never guessed |
| Falls back to another endpoint when one fails | Keeps the verifier in another family, with no fallback |
| | Runs the tests, the trace, fail-first and the verifier review at the gate |
| | Keeps holdouts in custody, delivers on paved roads, runs the change loop |
| | Records every decision with its person and persona |

The kernel's code is standard-library Python 3.11. It depends on nothing but Gnomon at runtime.
[spec-to-verify.md](spec-to-verify.md) traces each link of the chain to the mechanism that
enforces it.
