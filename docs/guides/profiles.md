# Work profiles

A work profile says what kind of work a project is. The governance core stays the same for every
profile: the canon, the Inbox, the contract, the gate, holdouts and the ledger. A profile changes
only what sits around that core:

- **intake:** what each panel perspective should also weigh, and a few questions it always asks;
- **spec:** guidance on criteria and checks;
- **cockpit:** extra widgets, and the words people in that field use;
- **deliverable:** a product, a capability pack, or a report.

The profiles live in [kernel/profiles.py](../../kernel/profiles.py).

## The thirteen profiles

| Profile | For | Deliverable | Asks once | Status |
|---|---|---|---|---|
| `web_service` | a web app or HTTP service with screens and an API | product | the look and feel | ready |
| `integration` | moving data or events between systems: webhooks, polling, mapping, retries | product | which systems can be called in tests; what happens to a message that cannot be delivered | ready |
| `mobile_prototype` | a fast phone-first prototype to show or test an idea | product | who sees it first, on what device | preview |
| `ml_pipeline` | training, evaluating or serving a model, or transforming data | capability pack | the metric and its threshold; which data may be used | preview |
| `agentic_workflow` | an agent, assistant or multi-step workflow that uses tools | capability pack | which actions need a person's approval | preview |
| `harness_engineering` | building or tuning an agent harness, policy or evaluation suite | capability pack | the baseline, and how much regression is acceptable | preview |
| `ops_agent` | an agent that does a job and proves it: a compliance check, a security scan, a log analysis | report | the framework and who signs off; what the agent may read | preview |
| `automation` | a scheduled or triggered job with no screens, a single workflow or one agentic capability, reached over MCP, an OpenAI-compatible endpoint, a website chat or HTTP ([small capabilities](small-capabilities.md)) | capability pack | what starts a run; where it must be reachable | ready |

| `game` | a game: its code, assets, levels, world and lore, builds and playtests | product | the next build or milestone; how a build is checked | preview |
| `ml_experiment` | a training or fine-tuning experiment, or a model: datasets, runs, metrics, evaluations, a model card | report | what the experiment must show, on which metric | preview |
| `knowledge_tooling` | notes, scripts and local services for one's own work: a second brain, a dev toolbox | product | what you rely on it for every day | preview; [second-brain scope approved](../../decisions/D-0025-second-brains-and-agent-context.md) |
| `library_cli` | a package other code imports, or a command-line tool | product | what counts as a breaking change | preview |
| `data_pipeline` | ingestion, transformations and quality checks on a schedule | product | how fresh its outputs must be, and who is told of a failed run | preview |

**Status** is honest about the template. The `automation` profile has its own, the capability
template; every other profile builds on the paved-road web-service template today. `preview` means the intake, spec and checks are shaped for the work, and its own
template is still to come. A mobile prototype ships as a phone-first web app, for example.

## What a profile changes in practice

- **Integration:** the spec asks for a contract test per upstream system against a recorded or
  simulated message, an idempotency test (the same message twice is processed once), the
  dead-letter path, and the end-to-end flow through a simulator as a holdout.
- **ML pipeline:** the metric and its threshold become a criterion, checked as a test on a fixed
  evaluation set. The hidden test set is a holdout: the builder never sees it.
- **Agent or assistant:** scenarios are trials. Refusals are criteria (it must refuse a forbidden
  action), and the cost per run is a probe.
- **Harness engineering:** every claim is a delta against a named baseline on a fixed trial set,
  with seeded defects the checks must catch.
- **Ops agent:** each finding cites the evidence it rests on, and what was not checked is
  reported as not measured, never as passed.
- **Automation:** the product declares what it needs where it runs (`app/runtime.json`), each
  criterion is checked against a run, every system it calls is simulated in tests, and the road's
  checks fail a capability whose declaration, job or faces break.

## Real project shapes

The last five profiles are for the shapes real projects people feed in come in (FR-RPJ1,
[kernel/profiles_shapes.py](../../kernel/profiles_shapes.py)): a game, an ML experiment or model (tied to
D-0020: a run, a metric and a model card are evidence), a knowledge or tooling project, a library or
command-line tool, and a data pipeline. Each has its panel focus, its questions and its **gates**, what
must hold before a release of that kind counts:

| Profile | Its gates |
|---|---|
| `game` | it builds headless; every scene in the build loads; a smoke playtest reaches the first goal; no asset is missing |
| `ml_experiment` | each reported metric names its run and evaluation set; the evaluation set is fixed and versioned; a model card states its limits |
| `knowledge_tooling` | its scripts' own checks pass; its local services answer |
| `library_cli` | its test suite passes; the package builds and installs; the changelog names breaking changes |
| `data_pipeline` | data-quality checks pass on the sample; a run finishes within its window |

**Recognised by their files too.** For an existing folder, adoption reads its files as well as its title and
README (`kernel.profiles_shapes.file_hints`): a Godot, Unity or Unreal project file, or assets, levels and lore
folders, point to a game; training or evaluation scripts, datasets, runs, metrics and results archives to an
ML experiment; a notes vault (`.obsidian/`, many notes) to knowledge or tooling; DAGs or a dbt project to a
data pipeline; a package manifest with a `bin/` or `cli/` folder to a library or CLI. A strong sign counts as
three of the profile's words, and when the words leave two kinds close, the files settle it. "Which kind of
work is this?" offers these profiles among its candidates, and the project header says **Kind: not chosen
yet** until a kind is chosen.

## Choosing a profile

By default, Rihma proposes a profile from the request, by rule and with no model: the profile
whose keywords the request names most. Nothing standing out means `web_service`.

Keywords are matched on word boundaries (`kernel.profiles.keyword_pattern`): the word or phrase
itself, or its plural (`model` finds "models"), and for a stem marked `*`, every word it begins
(the Finnish `palvelu*` finds "palvelun"). A keyword is never found inside another word: `train`
does not find "trainees", and `ml` does not find "html". Before 23 Nov 2026 a long keyword matched
anywhere in the text, which proposed `ml_pipeline` for Rihmasto's own README.

**When the rule is not sure.** A best score under two keywords, or within one keyword of the
runner-up, makes the proposal **uncertain**: it names its top candidates (at most four) and says
why. What happens then (built):

- **Intake** records the confidence and the candidates in the `profile_chosen` basis and, when the
  request's keywords point to more than one profile, adds the question "Which kind of work is
  this?" with the candidates as options. It has no proposed answer, so it goes to a person in every
  mode, `assume` included. A request whose keywords point to one profile, or to none, keeps that
  profile (or `web_service`), recorded as uncertain, without a question: there is nothing to choose
  between.
- **The spec waits for it.** The question is **blocking**, in every mode: the spec is shaped for a
  profile, so the run stops at stage 2 and waits on the question's card ("blocking questions are
  open"); no spec is written on the rule's guess while the question is open. Before the fix of
  23 Nov 2026 it was not blocking, so in `assume` mode the spec was written straight after intake
  and the answer came too late.
- **The answer decides.** When a person answers that question naming a profile (its label or its
  id), the profile is chosen in their name before the spec is written (`profile_chosen` with
  `{"by": <person>, "question": <id>}`), so the spec's guidance is for the kind of work a person
  said.
- **A late answer changes nothing silently.** An answer recorded after a spec exists (only a
  question an earlier version left open, not blocking, can get one) never changes the profile at a
  later spec, a plan redo included: the plan in review was shaped for the profile it has. The
  ledger records it once, as `profile_answer_late`, with the profile it named and the profile
  kept.
- **Adoption** records the uncertainty in `adopted.json`, the ledger and the brief
  ([../brownfield.md](../brownfield.md)).
- **The cockpit's** new-project dialog says when the proposal is unsure and asks the person to pick
  ("Let Rihma propose"); `POST /api/profiles/propose` returns the `confidence`, the
  `uncertain_because` and the `candidates`. Showing every candidate in the dialog, not only the
  runner-up, is still to come.

```bash
rihma new "Shipment webhook" --profile auto --maturity explore --requested-by "<your name>" \
    --source "When the carrier posts a shipment event to our webhook, update the stock system."
# proposed: integration (it names: carrier, event, webhook)
```

The choice and its basis go to the ledger as `profile_chosen`. To choose yourself, name it:

```bash
rihma new "Phone demo" --profile mobile_prototype --maturity explore --requested-by "<your name>" \
    --source "A phone page where field staff log a visit in three taps."
```

A person's choice stands; the rule never overrides it. A concept from the delivery square can have
its profile changed by its business owner or product owner before they validate it, in the
cockpit's Square or with `rihma concept edit <card> --profile <profile>`
([signals-and-concepts.md](signals-and-concepts.md)).

In the demo, the three projects got their profiles by rule: Equipment loans is a `web_service`,
the shipment webhook an `integration`, and the access review an `ops_agent`.
