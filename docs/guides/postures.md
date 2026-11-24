# Postures and priority weights

A posture is one choice that sets how a project runs: how many questions the panel asks and who
answers them, what the spec must cover, which signals block a release, and how much waits for a
person. Priority weights from 0 to 3 tune it. Every effect is a rule in the kernel, never a model's
choice. You see what a posture will do before you choose it, the ledger records who chose it, and a
change during the run says what it changes now and what it changes later
([kernel/posture.py](../../kernel/posture.py)).

A project without a posture runs exactly as before: its own mode and maturity, the autonomy cap
alone, and the maturity's own gates.

## The four postures

| Posture | Mode | Maturity | Autonomy | What it adds |
|---|---|---|---|---|
| **prototype**: a fast, rough demo | assume | explore or demo | 3 | nothing beyond the maturity's own gates |
| **balanced** | mixed | demo or pilot | 2 | a person says go ahead before each build and each delivery |
| **production**: as production-ready as possible | mixed | pilot or production | 3 | a security scan and the red team's static layer before any landing; holdouts on staging; IT's deploy gate; an evidence pack before production |
| **regulated**: conservative and secure | socratic | any | 1 | every question settled by a person before the spec; plan approval at any maturity, by the customer's side only; every requirement confirmed by a named person; no assumption stands without a confirmation before a build; warnings block; the red team's static and agentic layers; an attestable evidence pack, with its control table, before a release lands on staging (pilot) or production |

The mode and maturity are the posture's unless you name them. A maturity the posture does not run
at, or a mode looser than its own, is refused.

**Autonomy** here is the posture's rung of the [autonomy ladder](autonomy.md): the factory goes on
alone up to it, and a step above it waits for a person's **go-ahead card** (an approval card in the
Inbox, one per step and revision). Building needs level 3; delivering to a preview or a demo needs
3, to staging or production 4. So under *balanced* a person approves "Go ahead: building contract
revision ..." and then "Go ahead: delivering revision ... to demo". A declined card asks again on
the next run, with the decline in its body. A revision already built is not asked about again: a
posture tightened after the build asks only for the go-ahead to deliver it, and holds the next build.
The **autonomy cap** still refuses any step above it, whatever the posture: the cap is what the
kernel refuses outright, the posture is what waits for a person.

**Who decides.** Under a confirming posture (*regulated*, or compliance 3) approving the plan confirms
each requirement in the approver's name, so only the customer's side, a business owner or a product
owner, approves the plan, edits it, or gives a go-ahead; a developer is refused. Approving a plan that
misses a required topic waives a check, so only a business owner may. The card names who decides,
the kernel refuses anyone else, and the ledger records it (`card_deciders_set`). In the cockpit a
developer opening such a plan sees "Waits on a decision by Business owner" in place of the Approve and
Edit buttons. Every list of what a persona may decide reads the card's own deciders the same way: the
Inbox and its API (`GET /api/projects/<pid>/inbox`, `GET /api/inbox`), the dashboard's decisions, the
MCP server's `rihma_project` (`cards_you_may_decide`) and `rihma_waiting`, and Rihma's snapshot and
the decisions it offers to make. A developer does not see such a card as theirs anywhere.

Every posture keeps the gate's four signals (the tests, the criterion trace, fail-first and an
independent verifier) and the whole record. A lighter posture asks fewer questions and waits for
fewer people; it never drops provenance ([D-0017](../../decisions/D-0017-governance-everywhere.md)).

## Priority weights

Five weights, each from 0 to 3: **ux**, **security**, **compliance**, **speed** and **cost**. Each
posture has its own defaults. *production* holds security and compliance at 2 or more, *regulated*
at 3; a weight below the floor is raised, and the preview says so.

| Weight | The panel | The spec | The gates and the people |
|---|---|---|---|
| ux | the end-user perspective asks one more question per point above 1 | at 2 or more: an accessibility requirement (keyboard, labels), for work with screens only | |
| security | IT and security asks more | at 2 or more: a threat-model requirement (credentials, malformed input, no secret in a response) | at 3: warnings block, a scan and both red-team layers are required, and one step more waits for a person |
| compliance | business and IT and security ask more | at 2 or more: a record-keeping requirement and a data-protection requirement | at 2: an evidence pack before production; at 3: attestable, plan approval at any maturity, every requirement confirmed, one step more waits for a person |
| speed | at 3, every perspective asks one fewer | at 3: the fewest requirements that show the goal | at 3: one step less waits for a person |
| cost | business and operations ask more | at 2 or more: no requirement may need a paid external service | |

"One step more waits" lowers the posture's autonomy by one and "one step less" raises it, within the
posture's own range: prototype 2 to 3, balanced 1 to 3, production 2 to 3, regulated always 1. A
weight of 0 tells its perspectives to ask about it only if building without it would build the wrong
thing.

The spec's topics are checked by rule: the words of each requirement's statement and criteria. A
spec that misses a topic sends the plan to a person, at any maturity, and the plan card says which
topic is missing. If you edit the plan to cover it, the check counts the edit at once. A business
owner may also approve the plan without the topic; the ledger then records what was approved
without (`posture_plan_approved`). The analyst may write one more requirement per topic.

## Before you choose: the preview

The preview is the kernel's own words for what a posture and its weights will do, in four groups:
the panel, the spec, the gates and the people. The same choice always gives the same preview, and
showing it records nothing.

```bash
rihmasto posture list                                     # the postures, their defaults and floors
rihmasto posture preview production --weights ux=3        # what it would do
rihmasto posture preview balanced --profile integration   # an integration has no screens: no accessibility topic
rihmasto posture preview prototype --project <pid>        # also what changing this project would change, now and later
```

In the cockpit the preview sits under the posture you pick in **New project** and in a project's
**Posture** dialog, and it changes as you move a weight.

## Choose a posture for a new project

```bash
rihmasto new "Equipment loans" --source "Our team keeps losing track of who borrowed the drills." \
    --requested-by Aino --posture regulated --weights ux=2
```

The person who asks for the project chooses its posture (with access enforced, the identity that
signs the request). The ledger records `posture_chosen` with who chose it, the persona, the weights,
the mode, maturity, autonomy and gates, and the preview they were shown. Without `--posture`, `new`
is exactly as before.

In the cockpit, **New project** has a **How it runs** section: four posture cards and *No posture*,
the five weights, the maturity and mode the posture allows, and the preview. *No posture* is chosen
first, so nothing waits for a person by surprise: it gives the maturity and mode controls as before,
and *Balanced* and the others are one click away. The section is there when you start from a need or
a spec and from an existing project (`rihmasto adopt ... --posture production` does the same), and
not for *Shape it in chat*, which asks the mode and maturity when it creates the project.

## Change it during the run

```bash
rihmasto posture show <pid>       # the posture, what it does, and what holds the project now
rihmasto posture set <pid> regulated --reason "the pilot runs on customer data" \
    --person Aino --persona business_owner
rihmasto posture confirm <pid> A-002 --person Aino --persona business_owner
rihmasto posture confirm <pid> A-003 --refute "the laptops are not tagged yet" --person Aino --persona business_owner
```

- A business owner, product owner, IT or compliance chooses or tightens a posture, always with a
  reason.
- **Loosening** needs a business owner, IT or compliance: a higher autonomy, a looser mode, a lower
  maturity, or a check dropped (plan approval, confirmation, a scan, a red-team layer, blocking
  warnings, the evidence pack, a spec topic). The preview names each one before you change.
- The change says what it does **now** and what it does **later**, and the ledger records both with
  who, the persona and the reason (`posture_changed`). For example, *prototype* to *regulated* after
  intake reopens confirmation: every open assumption must be confirmed or refuted by a person before
  the next build. A spec still waiting for approval is checked again at once. Questions already
  settled stay as they are; the next reading follows the new mode. A release on its way meets the new
  gate at its next step, and one at another maturity is superseded at the next delivery.
- Go-ahead cards the new posture no longer needs are withdrawn, and the change says which; those
  still open are given the deciders the new posture names.
- A plan card the new posture no longer needs is withdrawn (for example security lowered to 1 when
  the missing threat model was the only reason the plan waited). One whose text or deciders the new
  posture changes is withdrawn too, and the next run opens it again as the new posture says.
- The factory's own canon takes no posture.

In the cockpit, the **Posture** chip in the project header opens the same: what the posture does,
what holds the project now, the autonomy cap, and, for a persona that may, the form to change it
with the preview of what changes now and later. The same chip sits in **Project settings**, and
opens the Posture dialog in its place.

**Project settings** keeps to the posture too ([change anything](change-anything.md)): a new maturity
or mode says in its impact when it also loosens or tightens the posture, by the same rules; a maturity
or mode the posture does not take is refused (change the posture first), and loosening it there needs
a business owner, IT or compliance, as here.

## What it holds, and where

| Where | What the posture does there |
|---|---|
| Intake | each perspective's question budget and what it weighs, at the end of its prompt |
| Spec | the topics' guidance in the analyst's prompt; a confirming posture holds the spec until every question is settled |
| Plan | approval at any maturity (regulated, compliance 3) or when a topic is missing; approving confirms each requirement in the approver's name under a confirming posture (`requirements_confirmed`) |
| Build | open assumptions under a confirming posture; a go-ahead above the posture's autonomy |
| Delivery | a go-ahead above its autonomy; with a required scan, the security gate holds a preview or demo landing too |
| Security gate | the posture's blocking levels; a scan, the red team's static layer and, where the project has an active embed, its agentic layer, each named with the command that provides it (`POSTURE-SCAN`, `POSTURE-REDTEAM-STATIC`, `POSTURE-REDTEAM-AGENTIC`) |
| Before staging (pilot) | before the release lands on staging, an evidence pack exported for it (`POSTURE-EVIDENCE`) |
| Before production | after IT's deploy gate, an evidence pack exported for the release (`POSTURE-EVIDENCE`): intact for *production*, attestable for *regulated* |

At explore or demo nothing lands on staging or production, so no pack is due; the preview says so.

A capability pack's and an evidence pack's security summary report the findings alone; what the
posture requires is the gate's, at the step it holds. What the posture requires is not a finding and
cannot be accepted as a risk: `rihmasto security accept <pid> POSTURE-SCAN ...` is refused with the
reason, and the hold says the release goes on once each one is there, or once a business owner, IT or
compliance changes the posture.

### Tutorial: a regulated pilot to staging

1. `rihmasto new "Equipment loans" --source "..." --requested-by Aino --posture regulated` (pilot).
2. `rihmasto run <pid>`, answer every question (`rihmasto answer <pid> <Q-id> "text" --person Aino
   --persona business_owner`) and run again: the plan waits. The plan card names who decides; as a
   developer, `rihmasto decide` is refused, and the MCP server started with `--persona developer`
   does not list the card in `rihma_waiting`.
3. As the business owner, approve the plan, then each go-ahead the run stops at.
4. Ingest a scan of the red team's static layer (`rihmasto security ingest`). When the release is on
   its way, `rihmasto posture show <pid>` lists "required before a landing: an evidence pack for
   release 1, attestable, exported before staging".
5. `rihmasto evidence <pid> --out DIR --person Kaisa --persona compliance` exports it; the next run
   goes on to staging (once IT's paved road for staging is configured).

The MCP server's `rihma_project` read carries the project's posture: what it does and what holds it
now ([mcp.md](../mcp.md)). The cockpit's API: `GET /api/postures`, `POST /api/postures/preview`
(records nothing), `GET` and `PUT /api/projects/<pid>/posture`, and `posture` and `weights` on
`POST /api/projects`.

## Tutorial: a balanced project from an idea to its first delivery

1. Open the cockpit, set your name and the business owner persona, and press **New project**.
2. Write a title and the need. Under **How it runs**, choose *Balanced*. Read the preview: the
   panel asks blocking questions of people, and building and delivering each wait for your go-ahead.
3. Move to *Production* with the arrow keys and watch the preview add the security scan and the red
   team's static layer. Raise **Security** to 3: warnings now block, and one step more waits. Go back
   to *Balanced* and press **Create and start the intake**.
4. When the intake is done, answer the blocking question in **Questions**, then press **Advance**.
5. The run stops at "Go ahead: building contract revision ...". Approve it in the **Inbox** and press
   **Advance** again: the cells build. The next stop is the go-ahead to deliver.
6. Open the **Posture** chip in the header. *What holds the project now* lists the open go-ahead.
   Choose *Prototype*: the preview says it loosens the autonomy from 2 to 3, and what changes now.
   With a reason, **Set the posture**: the go-ahead card is withdrawn, and the ledger has the change.

Ask Rihma "where do I change the posture?" and press **Take me there**: it opens the project's
overview at the Posture chip.

## Built and planned

**Built:** the four postures and five weights; the preview (command line, cockpit, the API); the
choice at creation (`rihmasto new`, the cockpit, the API) and during the run (`rihmasto posture set`,
the Posture dialog, the API); the effects on intake, spec, plan, build, delivery, the security gate,
before staging and before production; go-ahead cards; who decides the plan and go-ahead cards under
a confirming posture, and every read of what a persona may decide following them; plan cards that
follow a change; the ledger records; the MCP read; the assistant's map entry.

**Planned, not built:**
- a posture on a concept (the delivery square) and on `rihmasto adopt`: today a validated concept or
  an adopted solution starts without one, and `rihmasto posture set` gives it one;
- a factory-wide default posture or floor set by policy;
- tying a required scan to the revision it scanned: today the latest scan of each required tool
  counts, whatever revision it read;
- the run's state for a go-ahead: the pipeline reports `capped` with the card in its reason, as the
  autonomy cap does, rather than `waiting`;
- pluggable checks and human checkpoints per posture ([D-0017](../../decisions/D-0017-governance-everywhere.md),
  item 3);
- removing a posture: a project may take another posture, never none again;
- an evidence pack at explore or demo: nothing lands on staging or production there, so none is due;
- narrowing who decides a card decided before a posture change: a decision already made stands.
