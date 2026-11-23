# Rihma v1: the end-to-end chain

Status: design for v1, 2026-11-22 (D-0008). It turns the brief, the seven-stage model and the
delivery square into one working chain. Requirement ids are the brief's. The new ones are
FR-A6 to FR-A8 and FR-H7.

## What "finished" means

v1 is finished when the following holds for **three different inputs**:
- a vague idea in two sentences;
- an existing written spec (markdown);
- a factoryctl demo.

Each input passes through all of these steps:
1. **Intake.** In Socratic mode a perspectives panel asks questions, and a person answers each
   one or lets the factory assume. In assume mode every assumption is recorded with a due
   date.
2. **Spec.** Each requirement has a provenance tag and given/when/then criteria. The maturity
   level is chosen at intake.
3. **Contract** and check plan. The compiler has no model in it. Holdouts are kept in a
   separate custody.
4. **Cells.** Gnomon builder cells run in lanes. Every model call goes through Gnomon.
5. **Gates:**
   - the kernel runs the tests;
   - the criterion trace;
   - holdouts;
   - an independent verifier from another model family;
   - the bounded repair loop, then the Inbox.
6. **Delivery** on the paved road for the maturity: preview, demo, staging with user
   validation, or production behind IT's gate, with shadow, canary and rollback.
7. **Operation.** Probes and service levels. Incidents become Inbox cards.
8. **A change** from any persona (end user, product owner, business, IT, developer,
   operations) is triaged and sent back to the right stage. It marks later approvals as
   stale, ships through the same gates, and leaves a lesson.
9. **Visibility.** All of it can be seen and decided in the cockpit, by persona.

## Maturity levels: the paved ways (FR-A8)

The maturity is chosen at intake and can be raised later, which is a change. It decides which
stages run, which gates apply, and where the result lands.

| Maturity | Stages | Gates | Lands on | Human gates |
|---|---|---|---|---|
| `explore` | 1–4 and a walking skeleton | tests named by criterion | local preview (process) | none beyond intake |
| `demo` | 1–5 | + independent verifier | Docker on the GPU box, `demo` environment | owner accepts the demo |
| `pilot` | 1–6 | + holdouts on staging, + user validation | Docker on the GPU box, `staging` | business accepts after validation |
| `production` | 1–7 | + IT deploy gate, shadow, canary, rollback | paved road: `team-docker` prod, or `azure-containerapps` once IT has configured it | IT deploy gate, business go-live |

A paved road is configured in advance, by IT, in `paved_roads.json`. It records the target,
the endpoints, the identity to deploy as, and the rules (TLS, egress, regions). The factory
deploys only to a configured road. An unconfigured road becomes an Inbox card for IT; the
factory never guesses.

## Intake (FR-A2, A3, A5, A6, A7)

- **Inputs:** free text (an idea), a markdown spec, a Solution Factory output folder, or a
  factoryctl demo folder.
- **Modes (FR-A6):**
  - `socratic`: the panel's questions go to the Inbox, and the person answers.
  - `assume`: the factory answers each question itself, as an assumption with a due date.
  - `mixed` (the default): questions marked blocking go to the person, the rest are assumed.
  - On each Socratic question a person may press "let the factory assume".
- **Perspectives panel (FR-A7):** business, end_user, it_security, operations, delivery. Each
  perspective proposes questions and its own reading. Disagreements between perspectives are
  kept as *opinions* on the question. They are not averaged away.
- **Provenance (FR-A3):** every statement in the brief is tagged `[owner]` (said by a person),
  `[assumed]` (the factory assumed it; it has a due date) or `[proposed]` (the factory
  proposes it).
- **Send-back list (FR-A5):** if blocking questions stay open, the intake stops with the
  list. It does not invent answers.

## Architecture

All factory code is Python 3.11+, standard library only (D-0002).

**Where it runs:**
- **The GPU box:** the kernel, Gnomon, the lanes, Docker, and the cockpit server on loopback.
  You reach the cockpit from the workstation with `ssh -L 8787:127.0.0.1:8787 gpu-box`.
- **The workstation:** tests and development.

**Lanes (FR-C2, FR-F5):**
- Lanes are directories under `~/gf-lanes/`.
- A product's cell surface grants nothing beyond Gnomon's defaults (no verify command, no
  wider shell), so a lane runs **without anyone's trust grant**. It is clamped to the
  defaults, which this design wants.
- Verification is the kernel's job, in the gate. The verifier is pinned apart from the
  builder (FR-G6).
- If the owner trusts a lane once (`gnomon trust grant` in it), in-loop verify becomes an
  optional upgrade.

**Every model call goes through Gnomon:**
- `gnomon task --role <role> --json` runs in a lane whose surface names the role.
- The analyst role (intake and spec) has no write tools.
- The builder writes only inside the envelope's scope.
- The verifier is read-only, on a model family other than the builder's.
- The roles and models come from `kernel/routing.json`, so the factory has no model family
  of its own (D-0005).

### Modules (`kernel/`)

| Module | Owns | Key interface |
|---|---|---|
| `store.py` | the factory home and project folders; atomic JSON; ids; clock | `Factory(home)`, `.project(pid)`, `Project.read(name)`, `Project.write(name, obj)` |
| `canon.py` | goal, brief, questions, assumptions (with due dates), decisions, Inbox cards, exchange notes | `Canon(project)`, `.add_question()`, `.answer()`, `.assume()`, `.card()`, `.decide(card, person, persona, verdict, reason)` |
| `ledgerstore.py` | an insert-only JSONL ledger per project and for the factory, over `ledger.py` | `LedgerStore(path).append(kind, payload) -> record`, `.verify()` |
| `model.py` | model calls through Gnomon; a fake for tests | `GnomonModel(lane_dir, role)`, `FakeModel(script)`, `.ask(prompt) -> text`, `extract_json(text)` |
| `intake.py` | stage 1 to 2: modes, panel, brief, questions, assumptions | `intake(project, source, mode, maturity, model)` |
| `spec.py` | brief and answers to `spec.json`; importers | `make_spec(project, model)`, `import_markdown()`, `import_solution_factory()` |
| `compile.py` | spec to contract and check plan; holdouts to a separate custody; no model | `compile_contract(project) -> contract` |
| `lanes.py` | lane pool: prepare, lease, sync the product repo, compile the surface | `Lanes(root)`, `.lease(project, task)`, `.release()` |
| `gate.py` | tests, trace, holdouts, verifier, verdicts, two signals | `judge(project, task, lane) -> GateResult` |
| `dispatch.py` | envelope to cell to gate, the bounded repair loop, merge or escalate | `build(project, model_routing)` |
| `roads.py` + `deliver.py` | paved roads (local process, Docker, Azure Container Apps); the plan by maturity; environments; IT gate; shadow and canary | `delivery_plan(maturity)`, `deliver(project, *, roads, docker, az, new)`; see `docs/paved-roads.md` |
| `operate.py` | probes, holdouts, shadow compare, canary decision, rollback, incidents | `probe(project, env)`, `tick(project)`, `shadow(project, env)`, `canary(project, env)`, `rollback(...)` |
| `change.py` | change and feedback intake from any persona: triage, ways back, invalidation, amendment | `submit(project, persona, text)`, `triage()`, `route()` |
| `pipeline.py` | advance a project until a person is needed | `advance(project, *, model)` |
| `learn.py` | the factory learning from its products: default checks, model reliability | `propose(factory)`, `apply_accepted(factory)`, `model_reliability(factory)` |
| `cli.py` | the `factory` command | `factory new / answer / spec / compile / build / deliver / operate / change / status / serve` |

`cockpit/` holds `server.py` (`http.server` on 127.0.0.1, with a one-use sign-in link
exchanged for a token) and the views. **The Inbox is the only write path** (FR-M6). Every
decision is signed with a person and a persona.

### A project on disk

The home is `var/` by default, and it is not committed.

```
var/projects/<pid>/
  project.json        id, title, maturity, mode, stage, paved_road, created
  canon/
    brief.md          provenance-tagged
    questions.json    id, perspective, text, blocking, opinions[], status: open|answered|assumed
    assumptions.json  id, text, perspective, due, status: open|confirmed|refuted
    decisions.json    id, card, person, persona, verdict, reason, at
    inbox/<card>.json kind: question|approval|validation|deploy_gate|incident|change|escalation|road
    exchange/         agent notes (agent to agent)
  spec.json
  contract.json       gnomonfactory.contract/1, checked by tools/contract_check.py
  checkplan.json      visible checks per criterion (the holdouts live in var/holdouts/<pid>/)
  envelopes/<task>.md
  repo.git            the product repository (bare); lanes clone from it
  ledger.jsonl        every transition, hash-chained
  releases/<n>.json   revision, image, gates, provenance, environment
  ops/                probe results, shadow comparisons, incidents
```

### The change loop (FR-A4, FR-I1, FR-I3, FR-P4, FR-P5, FR-Q2)

`submit(persona, text)` produces a change card, and triage classifies it. Each class goes back
to its own stage, the "way back":

| Class | Typical source | Way back to |
|---|---|---|
| `defect` | end user, operations | stage 5: a repair envelope plus a regression test (the lesson) |
| `change_request` | product owner, business | stage 4: a contract amendment, which goes to the business decision first |
| `new_requirement` | business, stakeholder | stage 1 to 2: an intake round for the new need |
| `infra_change` | IT | stage 7 paved road: a `source:it` card on the board, with a dry run before it is adopted |
| `incident` | probes, operations | stage 7: rollback reflex, then a defect |
| `question` | anyone | the canon's questions |

**Invalidation (FR-P5):** an amendment marks every later approval that rests on the changed
requirement as **stale**. A stale approval must be given again. The cockpit shows what went
stale.

### Cockpit by persona (FR-T1, FR-M3)

| Persona | Sees | Can do |
|---|---|---|
| Business owner | goal, benefit against the baseline, decisions waiting, stale approvals | decide, accept, change priority, request a change |
| Concept evaluator | brief, opinions, assumptions due, spec | answer, let the factory assume, challenge an assumption |
| End-user tester | what to try, the validation build, their own reports | report an observation (UI gap, requirement, data, defect) |
| IT / partner | paved roads, deploy gates, environment drift, IT rules | configure a road, approve or refuse a deploy, file an infra change |
| Developer / PM | Floor (cells by stage), Evidence (gate signals), escalations | answer escalations, approve gates within the autonomy rules |
| Operations | Pulse (probes, service levels, shadow and canary), incidents | acknowledge, roll back, open a defect |

## What v1 does not do (honest)

- Signed provenance and external anchoring (FR-H2, FR-L3).
- Cynefin routing (FR-B1 to B3).
- A causal layer.
- Multi-factory scheduling (M4).
- MCP server (FR-N3).
- **A real Azure deployment.** The road renders and validates. It deploys once IT has
  configured `azure-containerapps` in `paved_roads.json` with an identity, and the Azure CLI
  exists on the deploying host. Neither is true today.
