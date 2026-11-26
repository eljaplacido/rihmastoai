# The acceptance matrix

Before Rihmasto is used on company projects, every use case and every mode must work end to end
(the owner, 2026-11-23). This page is that test, cell by cell: the exact input, what each person
does, what must happen, what proves it, and its state as measured.

**Built:** the matrix on this page and its offline cells in [tests/acceptance/](../tests/acceptance/),
which CI runs with the rest of the suite. **Planned:** the live acid test on the GPU box (its plan
is [at the end](#the-live-acid-test); no live run has happened yet), and the cells of features other
streams are building (postures, the multi-perspective assessment, verified tokens at the cockpit).

## How to read it

- **Rows** are use cases, each with one exact input. **Columns** are the modes, the maturities,
  the postures and the access modes. A **cell** is one row in one setting, with its id in the first
  column (`G1.demo`).
- **State**, measured on 2026-11-24 by running the cells on main with this page merged in (Python
  3.14, Windows 11; the whole package takes five to nine minutes, most of it the production cells):
  - **passes**: its offline test passes today;
  - **fails**: its offline test fails today, for the reason given. The test is marked as an expected
    failure, so the suite stays green; the day the gap closes, the suite reports an "unexpected
    success" and this page must change with it;
  - **pending**: it cannot run today. The cell says why and what it must meet.
- **Offline** means the real kernel (the panel, the spec's provenance rules, the hashed contract, the
  gate with its tests, trace, fail-first and verifier signals, the holdout custody, the paved road on
  127.0.0.1, the capability pack, the change loop, access and the ledger), with a scripted model, a
  scripted builder cell, no Gnomon, no model keys and no network beyond loopback. A guard fails a
  cell that calls Gnomon or reaches past loopback. Offline cells prove the chain's rules, not a
  model's judgement: the live acid test measures the models.
- **Personas.** Test personas decide everything: Aino (business owner), Pekka (product owner),
  Jaana (IT), Olli (developer) and Sanna (compliance). "Says yes" means each card's owner approves it.
- **Proof** names the offline test (in `tests/acceptance/`) and the live run (`L1` to `L9`) that
  will measure the cell with real models.

## Tutorial: run the matrix yourself

From the checkout, with Python 3.11 or later and git (nothing else, no network):

```bash
python -m unittest discover -s tests/acceptance -t tests            # every cell, five to nine minutes
python -m unittest discover -s tests/acceptance -t tests -k FR_AM2  # one family: the greenfield row
python -m unittest discover -s tests/acceptance -t tests -k FR_AM6_AC_3   # one cell: the assistant
```

A cell's test builds a fresh factory home in a temporary folder, runs the persona actions in its
own words (look for `self.need`, `self.answer_blocking`, `self.ship`), and checks what must happen.
`ship` runs the chain and, each time it waits, decides the waiting card the way its owner says yes.
`trace` reads what the ledger says (who decided, what was assumed, what proves it).

To add a cell: put the need and what the scripted model answers in `tests/acceptance/needs.py`,
write the test named after the criterion it proves (`test_FR_AM<n>_AC_<m>_...`, with the criterion
at the end of [contract/contract.json](../contract/contract.json)), and add its row here.
`tests/acceptance/test_matrix_doc.py` fails until this page names every acceptance test, every row
and column has a cell, a passing cell names a test that exists, and a failing cell names one marked
as an expected failure.

To run a cell with your own models instead of the scripted one, file the same input on a factory
home with Gnomon set up ([getting-started.md](getting-started.md)), then open it in the cockpit:

```bash
rihmasto new "Room booking" --source "We need room booking for the office." --requested-by Aino \
    --mode mixed --maturity demo                   # G1.demo: the panel asks, the Inbox shows the cards
rihmasto run <project id>                          # after the answers: spec, contract, build, delivery
```

## The rows

| Row | Use case | The exact input | Proposed by rule |
|---|---|---|---|
| G1 | Greenfield from one line | "We need room booking for the office." | web service, uncertain (one keyword) |
| G2 | Greenfield from two vague lines | "Our customer service team drowns in email and requests get lost. / We want something better, maybe with AI." | web service, uncertain (one keyword) |
| G3 | Greenfield from a written spec | the markdown file `visitor-sign-in.md`: a goal, requirements VIS-001 to VIS-004, users, out of scope (`WRITTEN` in `tests/acceptance/needs.py`) | web service, clear |
| G4 | Greenfield in Finnish | "Tarvitsemme palvelun, jossa taloyhtiön asukkaat jättävät vikailmoituksen lomakkeella ja näkevät, missä vaiheessa sen käsittely on." | web service, clear |
| B | Brownfield: adopt, assess, develop | the stock levels service, a git repository with its own three unittest tests (`kernel/demo.py`); then the change "We also need a low-stock list: every item whose level is below the threshold." | adopted: its spec is what it does |
| W | A single workflow | "A workflow that routes each purchase request to its budget owner for approval and reminds the owner after two working days." | agentic workflow, uncertain (one keyword) |
| A | An automation | "Automate the monthly invoice summary: on the first working day of each month, collect the open invoices from the finance export and send the finance team a summary." | automation (a small capability), uncertain (one keyword: automate) |
| C1 | An agentic capability: an assistant | "An assistant that answers employees' questions about the travel policy and cites the paragraph each answer rests on." | uncertain between agent and harness: a person chooses |
| C2 | An agentic capability: an ops agent | the demo's access review request ("Each quarter, check the exported access list of our ticketing system ...") | ops agent, clear |
| I | An integration | the demo's shipment webhook request ("When the carrier posts a shipment event to our webhook ...") | integration, clear |

**Faces: how people and systems reach what was delivered.** Today every row's release is an HTTP
service on the paved road, reached at its address (and through the cockpit's **Try it** list at
pilot), with a capability pack that pins it. An MCP tool, an A2A card, an OpenAI-compatible endpoint
or a chat for the product itself are planned ([portability.md](portability.md)); reaching the
systems a workflow must touch goes through Gnomon's integration lane, which is not built yet
([D-0015](../decisions/D-0015-integrations-through-gnomon.md)). The cells below say so where it matters.

## The columns

- **Modes** (what happens to each of the panel's questions): `socratic`, every question goes to a
  person; `assume`, the factory takes each proposal as an assumption with a due date; `mixed`, the
  blocking ones go to a person and the rest are assumed. A question nobody proposed an answer to
  ("Which kind of work is this?") goes to a person in every mode.
- **Maturities** (today's lever from a rough demo to production): `explore` lands on a preview with
  nobody after intake; `demo` on the demo environment after holdouts, with the business owner's
  acceptance; `pilot` on staging after the plan approval, holdouts and end users' validation;
  `production` after the pilot's steps, IT's deploy gate, a candidate, shadow and canary.
- **Postures** (prototype, balanced, production, regulated): presets with priority weights, being
  built in another stream. Their cells are pending, with the criteria they must meet.
- **Access modes:** a single operator (no access file; personas are self-declared and the factory
  says so), and enforced (every decision signed by a verified identity granted that persona on that
  project, by person, group or project).

## The cells

### G1: greenfield from one line

In every G1 cell the panel asks seven questions: Q-001 "Who may book a room, and whose booking stands
when two people want the same slot?" and Q-005 "Which rooms are there, and who keeps the list up to
date?" are blocking. The spec has four requirements: R-1 rests on the request, R-2 on Q-001, R-3 on
Q-005, R-4 is proposed. R-1-AC-2 is a holdout the builder never sees.

| Cell | Setting | Persona actions | What must happen | Proof | State |
|---|---|---|---|---|---|
| `G1.demo` | mixed, demo, single operator | Aino types the line; answers Q-001 and Q-005; accepts the demo | 2 question cards, 5 assumed with due dates; the run waits at stage 2 and writes no spec until both are answered; R-1 customer-endorsed by Aino, R-2 and R-3 customer-confirmed by Aino, R-4 vendor-proposed; 4 tasks merge through the gate; the demo runs the holdout on its twin (passed); one acceptance card; pack valid, "not signed" said plainly | `test_FR_AM2_AC_1_a_one_line_need_is_asked_shaped_built_and_accepted_as_a_demo`; live L1 | **passes** |
| `G1.explore` | mixed, explore | Aino answers Q-001 and Q-005 | preview, nobody after the answers; 3 requirements kept, the fourth recorded as dropped; the pack says R-1-AC-2 is not measured (no holdouts at explore), so it is not valid | `test_FR_AM4_AC_1_one_need_at_each_maturity_lands_where_the_maturity_says_after_the_people_it_names` | **passes** |
| `G1.pilot` | mixed, pilot | answers; Aino approves the plan and accepts the validation | a plan approval card before anything is built; staging; holdouts on staging; a user validation card; stage 6 | `test_FR_AM4_AC_1_one_need_at_each_maturity_lands_where_the_maturity_says_after_the_people_it_names` | **passes** |
| `G1.production` | mixed, production | as pilot; Jaana approves the deploy gate | the pilot's cards, then IT's deploy gate (only `it` may decide it), a candidate, shadow (not applicable: nothing runs yet), canary decides promote; stage 7; pack valid | `test_FR_AM4_AC_2_the_one_line_need_reaches_production`; live L3 | **passes** |
| `G1.socratic` | socratic, demo | Aino lets Rihma assume the look question, answers every other card, accepts the demo | 7 question cards, nothing assumed by the factory; the run waits only for the 2 blocking ones (see [gaps](#what-measuring-found)); every requirement resting on a question is customer-confirmed by Aino; the one assumption names her as the person who chose it | `test_FR_AM3_AC_2_socratic_mode_asks_every_question_and_the_spec_rests_on_the_persons_answers` | **passes** |
| `G1.assume` | assume, demo | Aino only accepts the demo | no question card; 7 assumptions due in 14 days; R-2 and R-3 are assumptions; the acceptance is the only decision | `test_FR_AM3_AC_3_assume_mode_runs_to_the_demo_with_one_decision_and_every_guess_on_record` | **passes** |

### G2: greenfield from two vague lines

| Cell | Setting | Persona actions | What must happen | Proof | State |
|---|---|---|---|---|---|
| `G2.demo` | mixed, demo | Aino types the two lines; answers the three blocking questions; accepts the demo | the panel asks what changes first (nothing lost, faster answers, fewer emails), where requests arrive and whether an AI may read customers' emails, all blocking; nothing is built before the answers; the AI requirement ("a suggested reply waits for a person's approval") is customer-confirmed by Aino; "sending replies without a person" is out of scope; holdout passed; pack valid | `test_FR_AM2_AC_2_a_two_line_vague_need_asks_what_to_build_first_before_anything_is_built`; live L2 | **passes** |
| `G2.production` | mixed, production | answers; Aino approves the plan, accepts the validation; Jaana approves the deploy gate | plan approval, staging, holdouts, validation, deploy gate, canary, promote; stage 7 | `test_FR_AM4_AC_2_the_two_line_vague_need_reaches_production` | **passes** |

### G3: greenfield from a written spec

| Cell | Setting | Persona actions | What must happen | Proof | State |
|---|---|---|---|---|---|
| `G3.demo` | mixed, demo | Aino hands in `visitor-sign-in.md`; answers Q-006 ("What data will it hold, and how sensitive is it?") with "personal or confidential data"; accepts the demo | read as markdown; the spec never says what data it holds, so the facet checklist asks it as Q-006, blocking at demo and the only card; the other 6 (the panel's 4, the profile's look-and-feel question and the checklist's "How will you accept it?") are assumed; the run waits at stage 2 and writes no spec until Q-006 is answered; the spec keeps VIS-001 to VIS-004 and adds R-1 (records deleted after 30 days) as an assumption; 5 tasks, each through a passed gate; the holdout VIS-001-AC-2 passes; pack valid | `test_FR_AM2_AC_3_a_written_spec_keeps_its_own_ids_and_is_asked_only_the_blocking_facet_it_leaves_out`; live L3 | **passes** |
| `G3.production` | mixed, production | Aino approves the plan, accepts the validation; Jaana approves the deploy gate | as G2.production, with the customer's own ids in the contract and the tests | `test_FR_AM4_AC_2_the_written_spec_reaches_production` | **passes** |

### G4: greenfield in Finnish

| Cell | Setting | Persona actions | What must happen | Proof | State |
|---|---|---|---|---|---|
| `G4.explore` | mixed, explore | Aino types the Finnish need; answers Q-001 ("Kuka käsittelee vikailmoitukset ...?") with the panel's proposal | the profile is clear (palvelu, lomake); the brief keeps the request in Finnish; the panel asks and the spec answers in Finnish; R-3 is customer-confirmed by Aino; preview; no holdout, so the pack is valid | `test_FR_AM2_AC_4_a_need_in_finnish_is_read_asked_and_specified_in_finnish`; live L4 | **passes** |
| `G4.production` | mixed, production | as G2.production | as G2.production | `test_FR_AM4_AC_2_the_finnish_need_reaches_production` | **passes** |

### B: brownfield, adopt, assess, develop

| Cell | Setting | Persona actions | What must happen | Proof | State |
|---|---|---|---|---|---|
| `B.develop` | adopted to maintain, explore | Olli adopts the repository; scans it with Rihmasto's own static layer and hands the SARIF in; Pekka files the change; Aino accepts it; Olli runs `rihmasto apply` | inventory and characterisation baseline (3 of 3 passed); the as-is spec is "observed"; the security gate says "not measured" before the scan and "passed" after it; the run waits, adopted to maintain; the rules triage the change as a new requirement that needs a decision; R-2 is added; T-002 merges with tests, trace and fail-first passed | `test_FR_AM5_AC_1_an_existing_service_is_adopted_assessed_and_developed_further_through_the_gate`; live L6 | **passes** |
| `B.deliver` | as B.develop | Olli runs the chain after the merge | the developed service lands on the preview. Today it fails: "the product has no app/server.py at this revision"; no paved road runs an adopted repository yet | `test_FR_AM5_AC_2_an_adopted_service_developed_further_is_delivered_on_a_paved_road` | **fails** |
| `B.apply` | as B.develop, in the cockpit | Aino accepts the change card; someone presses **Advance** | the run carries out the accepted change: each step of the pipeline applies accepted change cards not yet applied (kernel/pipeline.py), for any project, not only an adopted one | `test_FR_AM5_AC_3_the_run_carries_out_an_accepted_change_as_the_cockpits_advance_would` | **passes** |
| `B.rootsuite` | adopted to improve, explore | Olli adopts a small job scheduler whose unittest suite sits at its root, beside its one module, as the `schedule` candidate's does | no pytest marker, so the runner is unittest discovery from the root: the baseline runs the root suite and measures it (2 of 2 passed). The development gate discovers only under `tests/`, so on the same repository it says "not measured: no tests ran", and on a change it would run only the change's own tests, not the root suite (see [gaps](#what-measuring-found)) | `test_FR_AM5_AC_4_a_suite_at_the_repository_root_is_measured_at_adoption_and_the_gate_runs_only_tests` | **passes** |
| `B.perspectives` | adopted to improve | Olli asks for an assessment | pending: the multi-perspective assessment is being built in another stream. It must give findings per perspective (CI/CD governance, maintenance, security, compliance, architecture), each citing the evidence it rests on, say "not measured" where a tool is missing, and turn each proposed fix into a change card a person accepts | live L6 | **pending** |

### W: a single workflow

| Cell | Setting | Persona actions | What must happen | Proof | State |
|---|---|---|---|---|---|
| `W.explore` | mixed, explore | Aino types the workflow; answers Q-001 (which purchases need approval) | proposed as an agentic workflow on the keyword "workflow"; its own question ("Which of the agent's actions need a person's approval?") is assumed; preview; the pack's deliverable is a capability pack and says the holdout was not measured | `test_FR_AM6_AC_1_a_single_workflow_is_proposed_as_an_agentic_workflow_and_delivered_with_its_pack`; live L5 | **passes** |
| `W.production` | mixed, production | as G2.production | as G2.production | `test_FR_AM4_AC_2_the_workflow_reaches_production` | **passes** |
| `W.mcp` | any | a team calls the workflow from its own tools | pending: a release reached as an MCP tool, or from the customer's own platform, is planned in [portability.md](portability.md). It must pin the release it serves, refuse a call when the pack is no longer valid, and record each call against the release | none yet | **pending** |

### A: an automation

| Cell | Setting | Persona actions | What must happen | Proof | State |
|---|---|---|---|---|---|
| `A.explore` | assume, explore | Aino types the automation; nobody else acts | one keyword (automate) names the automation profile, so a small capability is proposed and the basis says it is uncertain; no question card; every answer assumed (6); a preview release with no person, its pack saying it is an automation; no requirement is customer-confirmed | `test_FR_AM6_AC_2_an_automation_in_assume_mode_runs_to_a_release_with_no_person_and_says_what_it_assumed`; live L5 | **passes** |
| `A.production` | assume, production | Aino approves the plan, accepts the validation; Jaana approves the deploy gate | even in assume mode, production waits for the plan approval, the validation and the deploy gate | `test_FR_AM4_AC_2_the_automation_reaches_production` | **passes** |
| `A.schedule` | any | none: the first working day of the month arrives | pending: nothing runs a release on a schedule. A schedule (planned as a CronJob in the portability exports) must call the release, record each run, and say "not measured" when the export is missing, never an empty summary | none yet | **pending** |

### C1: an agentic capability, an assistant

| Cell | Setting | Persona actions | What must happen | Proof | State |
|---|---|---|---|---|---|
| `C1.demo` | mixed, demo | Aino types the need; answers "Which kind of work is this?" with "Agent or assistant"; accepts the demo | the keywords point to two profiles, so a blocking question with the top candidates waits in every mode; the answer chooses the profile, recorded as Aino's; the spec holds a refusal (422 for a question the policy does not answer); holdout passed; the pack is a capability pack | `test_FR_AM6_AC_3_an_assistant_waits_for_a_person_to_say_which_kind_of_work_it_is_then_ships_as_a_capability`; live L5 | **passes** |
| `C1.production` | mixed, production | as G2.production, plus the profile answer | as G2.production | `test_FR_AM4_AC_2_the_assistant_reaches_production` | **passes** |
| `C1.chat` | any | employees ask on the intranet's travel page | pending: the product's own chat face (not the factory's feedback embed) is planned. It must answer only through the release, cite its source, and be inside the red team's agentic scope before any end user sees it | none yet | **pending** |

### C2: an agentic capability, an ops agent

| Cell | Setting | Persona actions | What must happen | Proof | State |
|---|---|---|---|---|---|
| `C2.demo` | assume, demo | Sanna types the request; Aino accepts the demo | ops agent, clear; its two questions (the framework and its sign-off, what the agent may read) are assumed; the holdout R-1-AC-2 passes against the demo; the pack's deliverable is a report | `test_FR_AM6_AC_4_an_ops_agent_delivers_a_report_with_a_holdout_the_builder_never_saw`; live L5 | **passes** |
| `C2.production` | assume, production | as G2.production | as G2.production | `test_FR_AM4_AC_2_the_ops_agent_reaches_production` | **passes** |

### I: an integration

| Cell | Setting | Persona actions | What must happen | Proof | State |
|---|---|---|---|---|---|
| `I.explore` | assume, explore | Pekka types the request | integration, clear; its two questions assumed, and R-3 (the dead-letter list) rests on one as an assumption; built by the demo's own webhook code and tests, every gate signal passed; preview; pack valid | `test_FR_AM6_AC_5_an_integration_is_built_by_its_own_code_and_tests_and_lands_on_the_preview`; live L5 | **passes** |
| `I.production` | assume, production | as G2.production | as G2.production | `test_FR_AM4_AC_2_the_integration_reaches_production` | **passes** |
| `I.systems` | any | IT enables a connector | pending: calling a real system (the stock system, the carrier) goes through Gnomon's integration lane, which is not built. Reads must become signals, a write must wait for a person's approval, and every call must reach Gnomon's audit trail | none yet | **pending** |
| `I.postgres` | any | IT models and enables a PostgreSQL connector | pending: the connector model is built, the lane that calls it is not. Live L8 checks what can be checked now | live L8 | **pending** |
| `I.warehouse` | any | IT connects an ERP, a cloud or a data warehouse such as Snowflake | pending: none is named or built. Each must come through an MCP server or the customer's own integration platform, modelled and pinned like the PostgreSQL connector, read-only until a person approves a write | none yet | **pending** |

### The mode sweep

Every need of the rows above (all but B, which has no panel) in each mode, through intake and one
step of the run. Measured counts: G1 7 questions (2 blocking), G2 6 (3), G3 7 (1: what data it holds),
G4 6 (1), W 6 (1), A 6 (2), C1 7 (1: the profile question), C2 7 (0), I 7 (0). A test holds this page
to the counts intake gives today (`tests/acceptance/test_matrix_doc.py`).

| Cell | Setting | Persona actions | What must happen | Proof | State |
|---|---|---|---|---|---|
| `M.socratic` | socratic, every need | none | every question is a card; nothing is assumed; no spec while a blocking question is open (a need with none, such as C2 or I, gets its spec at once while its cards stay open: see [gaps](#what-measuring-found)) | `test_FR_AM3_AC_1_each_mode_puts_to_a_person_exactly_what_it_says_for_every_need` | **passes** |
| `M.assume` | assume, every need | none | every question with a proposal is assumed with a due date; only the profile question (C1) goes to a person, and the spec waits for it | `test_FR_AM3_AC_1_each_mode_puts_to_a_person_exactly_what_it_says_for_every_need` | **passes** |
| `M.mixed` | mixed, every need | none | exactly the blocking questions go to a person; the rest are assumed | `test_FR_AM3_AC_1_each_mode_puts_to_a_person_exactly_what_it_says_for_every_need` | **passes** |

### Postures

Being built in another stream: a preset chosen when a project is made and changeable during the
run, tuned by priority weights (ux, security, compliance, speed, cost), deterministic, previewed in
words before anyone chooses, and recorded with who chose it. Each preset must meet the criteria
below on the input named, with the persona actions of the matching G cell.

| Cell | Setting | Persona actions | What must happen | Proof | State |
|---|---|---|---|---|---|
| `P.prototype` | G1, prototype | Aino chooses the posture and accepts the demo | pending: the posture is built in another stream. It must run in assume mode at explore or demo with light gates, ask nothing beyond what blocks, reach the demo with one decision, and record the posture, its weights and who chose it in the ledger | live L9 | **pending** |
| `P.balanced` | G2, balanced | as G2.demo, plus a go-ahead before the build and before the delivery | pending: the posture is built in another stream. It must run in mixed mode at demo or pilot, put a go-ahead card before each build and each delivery, and keep the standard gates | live L9 | **pending** |
| `P.production` | G3, production | as G3.production, plus Sanna exports the evidence pack | pending: the posture is built in another stream. It must scan with the red team's static layer before any landing, hold a release on an open error, and export an evidence pack before production | live L9 | **pending** |
| `P.regulated` | G1, regulated | Aino answers every card; the plan is approved by name | pending: the posture is built in another stream. It must run in socratic mode with plan approval at any maturity, have every assumption and requirement confirmed by a named person before the spec is used (so the spec waits for every question, not only the blocking ones), block on warnings, run the static and agentic red team where they apply, and end with an attestable evidence pack | live L9 | **pending** |

### Access

| Cell | Setting | Persona actions | What must happen | Proof | State |
|---|---|---|---|---|---|
| `X.single` | G1, no access file | Aino and a visitor answer, each typing a name and a persona | the factory says "single operator: personas are self-declared"; both decisions are recorded with the typed names and no identity | `test_FR_AM7_AC_1_without_an_access_file_one_operator_decides_and_the_factory_says_so` | **passes** |
| `X.enforced` | G1, mixed, production, enforced | IT binds the group "owners" to business owner everywhere, Jaana to IT everywhere, Pekka to product owner on this project only; Aino answers, Pekka approves the plan, Aino accepts the validation, Jaana approves the deploy gate | a decision with no verified identity, a typed name that is not the identity, a persona not granted and a project outside the scope are each refused, and nothing is recorded; then every decision of the run is recorded with its identity; release in production | `test_FR_AM7_AC_2_with_access_enforced_every_decision_of_a_production_run_is_signed_by_a_granted_identity`; live L7 | **passes** |
| `X.idp` | the cockpit behind oauth2-proxy and Keycloak | test users sign in through the browser | pending: the live identity test (L7) runs the real provider and proxy in front of the cockpit; offline, the kernel's check is proven by X.enforced and by `tests/test_access.py` | live L7 | **pending** |
| `X.lifecycle` | enforced | a joiner arrives, a leaver goes | pending: SCIM provisioning and separation of duties are D-0016's next phases. A leaver must lose every persona at once and their open cards be re-routed; the person who asked for a change must not accept it | none yet | **pending** |

### The trace (D-0017)

| Cell | Setting | Persona actions | What must happen | Proof | State |
|---|---|---|---|---|---|
| `T.paths` | A in assume at explore, and G1 in socratic at production | as A.explore; as G1.socratic, then the production cards; Sanna exports the evidence pack | both ledgers are intact and hold what proves the work (every gate passed, the release, the pack); the quick path holds every assumption and no decision, the strict one every decision by name and no assumption; the evidence pack is attestable | `test_FR_AM8_AC_1_the_quickest_and_the_strictest_paths_both_record_decisions_assumptions_and_proof` | **passes** |
| `T.asked` | G1 from the command line or the kernel | Aino files the need | the ledger records who asked and who chose the mode. Today only the cockpit does (its `cockpit_write` record); `rihmasto new` and `intake` keep them in `source.json` and `project.json`, outside the hash chain | `test_FR_AM8_AC_2_who_asked_and_who_chose_the_mode_are_in_the_ledger_on_every_path` | **fails** |
| `T.formats` | any | compliance exports the audit trail | pending: D-0017 asks for one command that exports a project's audit trail in standard formats (OpenTelemetry, an audit stream for a SIEM, OSCAL). Today the evidence pack and the CloudEvents relay exist; the rest is planned | none yet | **pending** |

## What measuring found

Each is a gap or a question for the owner, found by running the cells. None was changed here: the
fixes belong to the streams that own the code.

1. **No paved road runs an adopted repository** (`B.deliver`, fails). Developing an adopted service
   works through the gate, but delivery stops at "the product has no app/server.py at this
   revision". The README says it; the fix is a road (or a start command recorded at adoption) for an
   adopted service.
2. **An accepted change is carried out by the run** (`B.apply`, passes now). It was a gap: only the
   command line's `rihmasto apply` carried a change out. The pipeline now applies accepted change
   cards at each step, as it does a validation's hand-off, and the cockpit starts a run on acceptance.
3. **Who asked, and who chose the mode, are not in the ledger on the command line's path**
   (`T.asked`, fails). The cockpit records them; intake does not. One key in `intake_done`
   (`requested_by`, which the ledger then signs with the identity) and the mode's chooser would close it.
4. **Socratic mode waits only for blocking questions** (a question for the owner). Every question
   becomes a card, but the spec is written as soon as no blocking one is open; a non-blocking card
   answered later does not change the spec. For C2 and I (no blocking question) the spec is
   written at once with every card still open. If socratic mode should "fill the gaps" before
   anything is specified, the run must wait for every card; the regulated posture asks exactly that.
5. **"Automate" does not suggest the agentic profile** (A). The rule matches "automation", not
   "automate", so the automation is proposed as a web service, said to be a guess. A person can
   choose the profile when filing it; a stem keyword (`automat*`) would catch it.
6. **At explore, a pack with a holdout criterion is not valid** (W.explore, G1.explore). By design: no
   holdout runs on the preview, so the criterion is not measured and the pack says so.
7. **The gate runs only the suite under `tests/`** (`B.rootsuite`). Adoption finds a unittest suite
   wherever it sits and measures it as the baseline, but the development gate discovers only under
   `tests/`. On a repository whose tests sit at its root, a change's gate runs the change's own tests
   and none of the existing ones, so it cannot see a regression. The fix belongs to the gate: run the
   test command adoption recorded, or say "not measured" for the suite it cannot find.
8. **A written spec is asked what it leaves out** (G3). Since the facet checklist (FR-IK2), a written
   spec that never says what data it holds gets one blocking question at demo and above. The matrix
   keeps the spec as people usually write it. Measured on the side, not as a cell: the same spec with
   a "Data" section ("Visitors' names, companies and hosts: personal data.") is not asked about its
   data, but its words then point to a second profile, so "Which kind of work is this?" waits instead.

## The live acid test

The same rows with real models, on the GPU box ([D-0012](../decisions/D-0012-test-paved-road-gpu-box.md)),
by test personas only (`test-owner`, `test-product`, `test-it`, `test-dev`, `test-compliance`),
never in the owner's name. Hosted models take the public inputs (every row here, and the public
brownfield project); the local model takes anything from the owner's own code. Keycloak,
oauth2-proxy and PostgreSQL run as disposable containers published on 127.0.0.1 only, pulled by
digest and removed after the run. Nothing on this page has run live yet.

### Before the first run (L0)

1. On the box: `rihmasto doctor` passes (Python, git, Gnomon, docker, the lanes, the model keys).
2. `kernel/routing.local.json` routes every role, with the verifier and the holdout author on a
   different model family from the builder ([guides/local-models.md](guides/local-models.md)).
3. `paved_roads.json` holds the test road: Docker on loopback for demo, staging and production.
4. The offline matrix passes on the box: `python -m unittest discover -s tests/acceptance -t tests`.
5. Record: the Rihmasto commit, the Gnomon version, the routing (model and family per role), the
   road, the image digests.

### The run order

| Run | Cells | Input and setting | What it adds to the offline cell |
|---|---|---|---|
| L1 | G1.demo | the one line, mixed, demo | what a real panel asks of one line, and whether the blocking ones are the right ones |
| L2 | G2.demo, then G2 in socratic at pilot | the two lines | how far the questions narrow a vague need; whether the AI requirement lands where the answers put it |
| L3 | G3.demo, G3.production, G1.production | the written spec; the one line | the customer's ids through a real build; plan approval, staging, the deploy gate, shadow and canary on the Docker road |
| L4 | G4.explore | the Finnish need | the language held from the questions to the spec and the tests |
| L5 | W, A, C1, C2, I at demo | each row's input | each profile's questions and guidance with a real analyst; the ops agent's report and evidence |
| L6 | B.develop, then B.perspectives when built | the public project below | a real adoption, a real suite as the baseline, the own static scan, one change through the gate |
| L7 | X.idp, X.enforced | G1 at pilot, with the cockpit in enforced mode | the real provider, proxy and browser: see the identity test |
| L8 | I.postgres | the connector test below | the connector model against a real server |
| L9 | P.* | G1, G2 and G3 under each posture | when the postures are built |

### The brownfield project (L6)

The target is a public open-source project, not the owner's own code. The gate runs a Python
`unittest` suite discovered under `tests/` from the repository root, with nothing installed, so the
candidates are judged on that. Every fact below is to be checked at the commit the run pins (the
licence file, the size, that the suite runs and how many tests pass) and recorded with the run.

| Candidate | Licence | Size (approximate) | Tests and runner | Fit |
|---|---|---|---|---|
| [Python-Markdown](https://github.com/Python-Markdown/markdown) | BSD-3-Clause | about 10,000 lines of Python in the package and its built-in extensions | `unittest` suite in `tests/` (`python -m unittest discover tests`) | **Recommended.** No runtime dependency on current Python; the gate's shape of suite; a real security surface (raw HTML in Markdown) for the assessment; extension points for a realistic change, such as an extension that marks external links `rel="nofollow"` |
| [idna](https://github.com/kjd/idna) | BSD-3-Clause | a few hundred lines of logic beside large generated Unicode tables | `unittest` test cases in `tests/` | Small and very widely installed, but its domain (IDNA and UTS #46) leaves little room for a realistic feature, and its tables weigh on a model's context |
| [schedule](https://github.com/dbader/schedule) | MIT | about a thousand lines in one module | `unittest` test cases in `test_schedule.py` at the root; its CI runs pytest, but no `pytest.ini`, `conftest.py` or pytest section in `setup.cfg`, `tox.ini` or `pyproject.toml` marks it | The smallest, with clear features to add. Its suite sits at the root with no pytest marker, so the adoption baseline runs and measures it (unittest discovery from the root, as `B.rootsuite` shows). But the gate discovers only under `tests/`: a change's gate would run the change's own tests and not `test_schedule.py`, so moving the suite into `tests/` comes first, which is itself a realistic brownfield fix |

The run: Olli adopts the pinned tag to improve it; the baseline runs; Rihmasto's own static layer
scans it and the SARIF goes to the security gate; the multi-perspective assessment runs once it is
built; Pekka files the change; Aino accepts it; Olli applies it; the gate judges the cell's work. No
pull request is opened upstream: the upstream stays fetch-only.

### The identity test (L7)

1. **Keycloak** (container, `start-dev`, 127.0.0.1 only, TLS in front of it so the issuer is
   `https://`, as the access file requires): a realm `rihmasto-test`; groups `owners`, `it`,
   `developers`; users `test-owner` (owners), `test-it` (it), `test-dev` (developers),
   `test-outsider` (no group); a confidential client `rihmasto-cockpit` with the audience mapper and
   the `groups` client scope as Default ([guides/access.md](guides/access.md#oauth2-proxy)).
2. **oauth2-proxy** (container, 127.0.0.1): the alpha configuration in the access guide with
   `provider: keycloak-oidc`, the realm's issuer, the cockpit at `http://127.0.0.1:8787` upstream,
   passing the provider's signed token on (`--pass-authorization-header`); the cockpit verifies it with
   the realm's public keys and holds no shared secret ([guides/access.md](guides/access.md)).
3. **The cockpit** in enforced mode: an access file binding the group `owners` to business owner on
   every project, `test-it` to IT on every project, `test-dev` to developer on the G1 project only.
4. **The checks, in a real browser** (headless Chrome over the DevTools protocol, dark and light,
   1440 and 390 px):
   - each user signs in and the header says "enforced: signed in as" their name;
   - `test-owner` answers a question and approves the plan; `test-it` approves the deploy gate;
   - `test-dev` deciding the deploy gate is refused (403), and so is `test-outsider` everywhere;
   - a request straight to 127.0.0.1:8787 with forged identity headers and no signed token is refused (401);
   - `test-owner` is removed from `owners` in Keycloak; at the next sign-in the decision is refused;
   - the access file is changed, and the factory ledger records its new sha256 and who changed it.
5. When the stream verifying the provider's signed token at the cockpit lands, the same steps run
   with it on, and a forged token is refused too.

### The PostgreSQL connector test (L8)

What runs today is the connector model, not a call: Gnomon's integration lane is not built.

1. **PostgreSQL** (container, 127.0.0.1, a throwaway password from the environment): a schema
   `stock` with one table of item levels, and a role that may only read it.
2. **The connector**, as `connectors/postgres/` on the box (not committed), made from the example
   ([connectors/example/README.md](../connectors/example/README.md)): a read-only PostgreSQL MCP server
   the run picks and pins in `server.pin`, its read tools (list tables, a read-only query) mapped to
   signals in `mapping.py`, every tool that writes or changes the schema under `forbidden_tools`, the
   credential by name only (`env:...`), the sha256 of its tools/list, and the example's fixtures
   (`tools.json`, `rugpull-tools.json`, `injection.json`) written for it.
3. **The checks:** `rihmasto connector validate postgres` passes; `python -m unittest
   tests.test_connectors_contract`, which runs over every folder under `connectors/`, holds it to the
   contract (its pinned tools/list, its rug-pull fixture caught, every injection sample mapped to
   quoted data); `test-it` enables it and decides the `connector` card in the factory's Inbox; a
   changed tools/list stops the connector and `rihmasto connector check` opens a new card; nothing
   calls the server.
4. **Pending until the lane exists:** a read through Gnomon that becomes a signal, a write that
   waits for `test-it`'s approval, and both calls in Gnomon's audit trail, ingested by the factory.

### What each run records

One run sheet per live cell, kept beside the run's factory home and never in the repository when it
names anything private:

- the date, the box, the Rihmasto commit, the Gnomon version, the routing (model and family per
  role), the road, the image digests;
- the exact input and every persona action with its time;
- what the panel asked (per perspective, which were blocking), what was assumed, what the spec says
  and each requirement's provenance;
- per task: the gate rounds and each signal's verdict, escalations and how they were decided;
- holdout results, the release's environment and steps, the pack's version and validity, the
  evidence pack and its attestation;
- the Gnomon runs, their tokens, and the cost, or "not measured" with the reason;
- the cell's state (passes, fails or not measured) and what differed from the offline cell. The
  state on this page changes only with a run sheet behind it.
