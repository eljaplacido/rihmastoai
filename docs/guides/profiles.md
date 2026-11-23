# Work profiles

A work profile says what kind of work a project is. The governance core stays the same for every
profile: the canon, the Inbox, the contract, the gate, holdouts and the ledger. A profile changes
only what sits around that core:

- **intake:** what each panel perspective should also weigh, and a few questions it always asks;
- **spec:** guidance on criteria and checks;
- **cockpit:** extra widgets, and the words people in that field use;
- **deliverable:** a product, a capability pack, or a report.

The profiles live in [kernel/profiles.py](../../kernel/profiles.py).

## The seven profiles

| Profile | For | Deliverable | Asks once | Status |
|---|---|---|---|---|
| `web_service` | a web app or HTTP service with screens and an API | product | the look and feel | ready |
| `integration` | moving data or events between systems: webhooks, polling, mapping, retries | product | which systems can be called in tests; what happens to a message that cannot be delivered | ready |
| `mobile_prototype` | a fast phone-first prototype to show or test an idea | product | who sees it first, on what device | preview |
| `ml_pipeline` | training, evaluating or serving a model, or transforming data | capability pack | the metric and its threshold; which data may be used | preview |
| `agentic_workflow` | an agent, assistant or multi-step workflow that uses tools | capability pack | which actions need a person's approval | preview |
| `harness_engineering` | building or tuning an agent harness, policy or evaluation suite | capability pack | the baseline, and how much regression is acceptable | preview |
| `ops_agent` | an agent that does a job and proves it: a compliance check, a security scan, a log analysis | report | the framework and who signs off; what the agent may read | preview |

**Status** is honest about the template. Every profile builds on the paved-road web-service
template today. `preview` means the intake, spec and checks are shaped for the work, and its own
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

## Choosing a profile

By default, Rihma proposes a profile from the request, by rule and with no model: the profile
whose keywords the request names most. Nothing standing out means `web_service`.

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
