# The demo: a guided tour

One command builds a demo factory home that shows what Rihmasto does, with no model keys, no
network and no Gnomon. This page walks you through it in about 15 minutes, one lens at a time.
Each stop names the persona to pick, what to look at on each page of the cockpit, and the commands
that show the same thing.

## What is real, and what is scripted

- **Real: the kernel.** The panel and the brief, the spec and its provenance, the hashed contract,
  the gate (the product's own tests, the criterion trace, fail-first, the verifier's findings),
  escalation, git lanes, the holdout custody, the local-preview road, the capability pack, the
  SARIF reader and the security gate, risk acceptance, the evidence pack, the autonomy cap, the
  website chat's key, origin check and filing, comments, the adoption of an existing repository,
  signals, concepts, updates and the hash-chained ledger.
- **Scripted.** A scripted model (`demo-model`) answers the analyst's, the holdout author's and the
  website chat's prompts. A scripted builder cell and verifier (`demo-builder`) stand in for
  Gnomon's cells. The security scan is an example the demo writes over its own release, by a tool
  called "Example Scanner": its two findings describe the demo's code as it is, but no real scanner
  produced them.
- **Fake people.** Every decision is signed by a `demo-*` person: `demo-owner` (business owner),
  `demo-product` (product owner), `demo-dev` (developer), `demo-ops` (operations),
  `demo-compliance` (compliance) and `demo-stakeholder` (stakeholder).
- **Not measured, and said so.** There are no Gnomon runs: the Cell view says none is recorded,
  and the harness figures are not measured. Spend reads "Not measured" with its reason (no Gnomon
  run yet, so nothing is priced): no model was paid for, and nothing shows as a zero. The local preview was started, checked and stopped again, so the
  release link in **Try it** does not answer.

## Build it and open it (2 minutes)

```bash
rihmasto demo                                # builds var/demo in well under a minute
rihmasto-cockpit --home var/demo             # the cockpit on the demo home
```

Without installing, the two lines are `python -m kernel.cli demo` and
`python -m cockpit.server --home var/demo`. Running the demo again replaces an earlier demo home,
and it refuses any other folder that is not empty.

The cockpit listens on 127.0.0.1 only and prints a link you open once. Then press the **person
chip** at the top right, type your name, pick the persona the stop below names, and press **Done**.
Each persona starts in its own lens; the **lens switcher** in the top bar changes it at any time.
**Ask Rihma** (or the `/` key) opens the assistant at every stop: try "Where are the releases?" and
press **Take me there**.

For the command line, point it at the demo home once:

```bash
export RIHMASTO_HOME=var/demo       # PowerShell: $env:RIHMASTO_HOME = "var/demo"
rihmasto status                     # every project, its stage, its open cards with their ids
```

`rihma` stays as an alias of `rihmasto`, `RIHMA_HOME` is honoured too, and `python -m kernel.cli`
works without installing. Project ids end in a random suffix: below, `<webhook>`, `<access>`,
`<loans>` and `<stock>` stand for them, as `rihmasto status` lists them. A command that writes is
signed with `--person` and `--persona`. The commands below need no model, so they also run offline.

## What is in the demo home

| Project | Profile, maturity | Where it stands |
|---|---|---|
| Equipment loans | web service, demo | Stage 2: two blocking questions from the panel wait for a person; a business owner confirmed one assumption. |
| Shipment webhook to the stock system | integration, explore | Stage 6: built through the gate (one task escalated and was retried), release 1 ran on the local preview, capability pack v1.0.0. Then a security scan with one accepted risk, a stakeholder's comment, a website feedback chat with one triaged message, a change from a chat signal, an update card, and an exported evidence pack. |
| Access review check | ops agent, demo | Stage 5: a task escalated after three gate rounds and waits for a person. Its autonomy is capped at 3 (prepare). |
| Stock levels service | adopted, web service, production | Stage 5: an existing service adopted to maintain it. Its own tests pass at the baseline (3 of 3); nothing is built until a change arrives. |
| Rihmasto itself | the factory's own canon | A need raised in a meeting became a concept that waits for a business owner. |

Beside the projects, in `var/demo`:

- `exports/`: the webhook's evidence pack, a zip as a reviewer receives it;
- `scans/example-scanner.sarif`: the example scan, in SARIF 2.1.0;
- `existing/stock-levels/`: the existing service's own git repository, the adopted upstream.

## 1. Business lens: what is coming, and what does it need from me? (3 minutes)

**Persona: business owner.**

- **Home.** Key figures (projects in flight, decisions waiting and the oldest one's age, first-round
  gate pass, criteria proven), Decisions waiting, Capabilities, the Delivery square, Project health
  and Activity. Every figure carries its denominator; a figure that was not measured has a dashed
  border and its reason, never a 0.
- **Square** (sidebar). Two signals arrived. The warehouse chat's (S-001) named the webhook, so
  triage routed it there as a change. The monthly operations review's need (S-002) became the
  concept **Offline maintenance visits**. Edit its title, work profile or maturity, then
  **Validate**, **Park** or **Reject** it with a reason: a validated concept becomes a project at
  once.
- **Catalogue.** Every capability by its state (trying, building, shaping, proposed), with its work
  profile, deliverable and capability pack.
- **Projects → Equipment loans → Questions.** Q-001 ("Who approves a loan?") and Q-003 ("Must every
  loan have a return date?") block the build. Each offers the panel's proposal first, then the
  asking perspective's reasoning and the other perspectives' opinions side by side: IT and security
  wants approvals logged, the end user wants any team member to approve. **Answer** records your own
  words; the secondary action turns the proposal into an assumption with a due date.
  **Assumptions** shows A-001, the benefit baseline, confirmed by `demo-owner`.

The same from the command line:

```bash
rihmasto square                     # signals, concepts waiting, the pipeline, feedback waiting, production
rihmasto catalogue                  # every capability and its state
rihmasto signal list                # S-001 routed to the webhook, S-002 a concept
rihmasto answer <loans> Q-001 "the team lead approves" --person You --persona business_owner
```

## 2. Concept lens: what do we assume, and what does the plan say? (3 minutes)

**Persona: product owner.**

- **Home.** Decisions waiting (the cards a product owner may decide, with inline verdicts), the
  Delivery square, Evidence coverage (how much of each project is proven rather than claimed) and
  the Pipeline.
- **Projects → Shipment webhook → Spec & contract.** Three requirements. Each has a **Sources**
  line (the request, or Q-007, the integration profile's question about undeliverable messages) and
  its provenance; each criterion has an **evidence** chip. Verified means a gate passed at the
  merged revision and a test on main names the criterion: press the chip to see which gate.
  **Impact if changed** shows what a change to the requirement would touch.
- **Comments.** Requirement R-2 ("The same event sent twice counts once") carries a comment from
  `demo-stakeholder` (CM-001): the carrier sometimes sends a relabelled parcel again under a new
  event id. A comment decides nothing. As a product owner you may **Promote to change**, which files
  it as a change card and triages it.
- **Changes** and **Inbox.** Two change cards wait for you:
  - **C-0002** came from the website feedback chat. One end user wrote on the warehouse's site;
    the chat (its assistant scripted) thanked them and filed the message through the embed. The
    rules triaged it as a *new requirement*, so it needs a decision.
  - **C-0003** came from the warehouse chat signal: a change request on R-1, about deliveries split
    into parcels.

  Each card shows **Impact if changed** before **Accept**, **Reject** or **Defer**.
- **Settings → Embeds.** **Warehouse feedback** (E-001) is a feedback chat for the webhook, allowed
  only on `https://warehouse.example`, with one message so far. Its key was shown once when it was
  made, and only its hash is kept. Make an embed of your own here to see a key and the snippet a
  website includes; **Revoke** stops one at once.
- **The end user's side.** Switch to the **end-user tester** persona: **Try it** lists one plain
  check per criterion, and **Report what you saw** on a check files a change on the project, which
  the rules triage as they triaged the website chat's message.

```bash
rihmasto embed list                 # E-001: its origins, its state and its message count; never its key
rihmasto decide <webhook> C-0002 defer --person You --persona product_owner --reason "After the carrier's own release"
```

## 3. Delivery lens: how is the run going, and why did something fail? (3 minutes)

**Persona: developer.**

- **Home.** Live agents shows each project's real state (waiting on a person, ready, done): no cell
  is running, so nothing pulses. Gate trend counts the rounds that passed and did not pass; the Task
  timeline puts every round on one time axis, coloured by its gate's verdict.
- **Access review check → Tasks.** T-001 merged. T-002 is in the Escalated lane: the scripted cell
  wrote a test that asserts True and calls nothing, three rounds in a row. **Details** shows each
  round's four signals: the tests and the trace passed, but fail-first failed (the test passes
  without the behaviour, on the bare template) and the verifier found a test that cannot fail.
- **Access review check → Inbox.** The escalation card keeps the gate's objections. **Retry**,
  **Accept as is** or **Stop**; your decision is recorded, and **Advance** would then run the real
  pipeline, which needs Gnomon and a model.
- **Shipment webhook → Tasks.** The same story with its ending: T-002 escalated, `demo-dev` chose
  **Retry** ("the test cannot fail"), and it merged. **Ledger** shows every transition, hash-chained.
- **Stock levels service.** An existing service, adopted to maintain it. **Spec & contract** holds
  one requirement whose source is *observed*: its own test suite keeps passing (existing behaviour,
  not a spec). **Tasks** shows T-001 as the existing code, not built or gated by the factory.
  **Ledger** shows the adoption, the inventory by rule and the characterisation baseline: 3 tests
  ran, 3 passed. Its upstream is fetch-only: nothing in the kernel pushes there.

```bash
rihmasto status <access>            # T-001 merged, T-002 escalated, the escalation card
rihmasto sync <stock>               # fetches the upstream again and records any drift
```

To see drift, commit a change in `var/demo/existing/stock-levels` (it is an ordinary git
repository) and run `rihmasto sync <stock>` again: the drift is recorded and a change card
"Upstream changed: review" opens. The project's main never moves on its own.

## 4. Operations lens: what runs, and is it healthy? (2 minutes)

**Persona: IT** (IT may decide update cards; the operations persona acknowledges incidents and
rolls back).

- **Home.** Project health (on track, at risk or off track, each with its reasons), Updates,
  Decisions waiting, Activity and Spend. Spend reads "Not measured", because the demo starts no
  Gnomon run and nothing is priced. With real runs, a run whose model has no price in `kernel/prices.json` makes cloud
  spend "not measured", never zero.
- **Updates.** A new model, `demo-model-2`, is available for what built the webhook (observation
  O-001). The card **C-0004** offers **Start a trial**, **Decline** or **Defer**; a decided card is
  recorded once by `rihmasto updates apply`.
- **Shipment webhook → Releases.** Release 1 at explore maturity on the local-preview road. The
  capability pack comes first: version 1.0.0, valid, every criterion verified, the pinned hashes
  (contract, product revision, artifacts, the models that built and judged it), "not signed" and
  "no SBOM" said plainly, and a YAML view whose `security` section names the example scan and the
  accepted risk. Showing the pack never builds it. Nothing runs in production in the demo.

```bash
rihmasto pack <webhook> --yaml      # the capability pack; the same content keeps version 1.0.0
rihmasto updates apply <webhook>    # records each decided update card once
```

## 5. Compliance lens: can we show what ran, who approved, and that it was checked? (2 minutes)

**Persona: compliance.**

- **Home.** Evidence packs, Autonomy, Evidence coverage, Activity and Updates.
  - **Evidence packs** shows each project's attestation: the webhook is *attestable* (its records
    are intact and complete enough for a reviewer to judge; never "compliant"), with pack v1.0.0,
    valid. The table view counts its exports: one, by the demo. **Export** makes another, with a
    one-time download link.
  - **Autonomy** shows the ladder (1 answer, 2 suggest, 3 prepare, 4 deliver), the factory's cap
    and the lower caps: the access review at 3, *prepare*, so nothing it builds reaches staging or
    production. Its project header says "Autonomy 3 · prepare", and its **Ledger** holds the
    change, signed by `demo-compliance` with the reason given.
- **Shipment webhook → Evidence** (under **Show all views**). The attestation, what the pack holds,
  and the control table: evidenced, partial or not evidenced, per control. A reviewer judges
  conformity, not the factory.
- **The exported pack.** Open the zip in `var/demo/exports/`: `README.md` says what it shows and
  what it does not; `MANIFEST.json` holds the sha256 of every file and who exported it
  (`demo-compliance`); `security.json` names the example scan and the accepted risk; `ledger.jsonl`
  is the whole project ledger, verified at export. Holdout scenarios never leave their custody;
  only scores do.
- **Security findings** are on the command line. The example scan found two things in the
  webhook's `app/routes.py`: SEC-1-1, an error (CWE-306: `POST /webhooks/shipments` accepts a
  request with no authentication), and SEC-1-2, a warning (CWE-20: `qty` is never range-checked).
  `demo-compliance` accepted SEC-1-1 as a risk until a date, with a reason: release 1 runs only on
  the local preview, and the carrier's shared secret is an IT rule for the next maturity. The
  security gate blocks on open errors, so it passed; the warning stays open. Before the scan the
  gate said "not measured", never "passed".

```bash
rihmasto security status <webhook>  # each finding, its state, and the accepted risk with its expiry
rihmasto security accept <webhook> SEC-1-2 --reason "Quantities come only from recorded sample events" --expires 2027-06-30 --person You --persona compliance
rihmasto evidence <webhook> --out var/demo/exports --person You --persona compliance
rihmasto autonomy show <access>
rihmasto autonomy set 2 --project <access> --reason "Until the escalation is decided" --person You --persona compliance
```

An acceptance must end in the future, so pick an expiry date after today. To feed a real
scanner's SARIF, `rihmasto security ingest <webhook> <file.sarif>` reads any SARIF 2.1.0 file
([brownfield.md](brownfield.md#security-findings-from-any-scanner)).

## 6. Insight lens: how does the factory itself perform? (2 minutes)

**Any persona.**

- **Home.** Key figures, Gate trend, Builder models (the first-round warranted rate per builder
  model, with its n: here only the scripted `demo-builder`), Evidence coverage per project (a 100%
  bar; not measured is hatched, never drawn as zero), Spend and the Pipeline.
- **Insight** (sidebar), the Floor. First the gate's judgement of the work: how many tasks passed
  their gate in the first round, tasks merged and escalated, rounds judged. Then the harness
  outcomes of each Gnomon run: there are none in the demo, so they are not measured, and a run that
  was not measured is never counted as a failure.
- **Projects → Rihmasto itself.** The factory's own proposals to change itself, decided like any
  card, and the concept waiting from the square.

```bash
rihmasto learn                      # lessons across projects, proposals, each builder model's record
```

## What next

- Log a need yourself and watch triage route it by rule:
  `rihmasto signal log --text "The access review should also flag shared accounts" --channel chat --source "compliance chat" --person You --persona compliance`,
  then `rihmasto signal triage S-003`. It names two words of the access review's title, so it
  becomes a change there.
- [getting-started.md](getting-started.md) takes you from the demo to a first real project, with
  Gnomon and your own models.
- [how-it-works.md](how-it-works.md) explains the chain step by step, and who decides what.
- [cockpit.md](cockpit.md) describes every page of the cockpit; [mcp.md](mcp.md) the MCP server
  for your own coding agent.
- The guides cover [embeds](guides/embeds.md), [packs and evidence](guides/packs-and-evidence.md),
  [autonomy](guides/autonomy.md) and [signals and concepts](guides/signals-and-concepts.md);
  [brownfield.md](brownfield.md) covers adopting existing solutions, workspaces and security
  findings from any scanner.
