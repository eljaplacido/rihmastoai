# The Rihma cockpit

Rihma is the factory: one living thread from a business need to the running service
(D-0010). Gnomon is the engine underneath it, and keeps its name. Rihma's product is agentic
capability: web apps, integrations, mobile prototypes, ML pipelines, agents and assistants,
harness engineering, and ops agents that deliver a report with an evidence pack. Each release
is a hash-pinned capability pack whose evals travel with it.

The cockpit is one web page over Rihma, seen through a lens (FR-T1, FR-M3). It shows the
delivery square, the capability catalogue, a dashboard per lens that each person can reshape,
every project's stages, Inbox, plan, questions, assumptions, spec and contract, tasks with what
the running cell does, Gnomon runs, what to try, releases with their capability pack, evidence,
changes and ledger, and the factory's Floor. It is also the Inbox's write path (FR-M6): every
decision made in it carries a person and a persona, and the kernel accepts or refuses it. The
server never decides anything itself, and what it shows before a decision (impact, alignment,
the Cell, the Floor, the dashboard) changes nothing.

It is standard-library Python and plain HTML, CSS and JavaScript (ES modules), with no build
step and no external assets: `cockpit/server.py` and `cockpit/static/`.

## Start it

On the machine that runs the kernel (for example a GPU box), from the repository root:

```
python -m cockpit.server --home var --port 8787
```

`--home` is the factory home (default: `$GNOMONFACTORY_HOME`, else `var/`). The server
binds to `127.0.0.1` only and refuses any other address. It prints one link:

```
Open this link once to sign in: http://127.0.0.1:8787/#k=<one-use bootstrap>
```

The page sends the bootstrap to `/auth` once and gets a session token, which it keeps in
that tab's sessionStorage. The link does not work a second time. To open a second tab, press
**Link for another tab** in the person menu of a signed-in tab: it makes a new one-use link
that is valid for 10 minutes. If every tab is closed, restart the server for a new link.

`--assistant gnomon` (the default when `kernel.model.gnomon_cmd()` finds Gnomon) asks Gnomon in
the analyst lane, as the `assistant` role, for the cockpit assistant (`kernel.lanes.ensure_analyst_lane`).
`--assistant map` answers from the cockpit's map only; the server says in one line which it uses.
A slow model call never holds up other requests: the assistant's route runs outside the write lock.

`--embed-base https://feedback.example` (or `RIHMA_EMBED_BASE`) is the public address of the
embed server (`python -m embed.server`, see [the embeds guide](guides/embeds.md)). Every embed
snippet points there, never at the cockpit, which serves no widget. It must be
`https://host[:port][/path]`, or loopback `http` for testing; anything else, or the cockpit's own
address, is refused at start. Without it, snippets point at the local embed server
(`http://127.0.0.1:8790`) and say so; the server prints one line about which it uses.

## Reach it from another machine

Open an SSH tunnel to the same port, then open the printed link on the workstation:

```
ssh -L 8787:127.0.0.1:8787 gpu-box
```

Use the same local port as the server's port. The server accepts a request only when its
`Host` is `127.0.0.1:<port>`, and a POST or PUT only when its `Origin` is
`http://127.0.0.1:<port>`. A tunnel on another local port, or `localhost` in the address,
is refused.

## What the server enforces

- Every `/api/*` request needs `Authorization: Bearer <session token>`. Otherwise the answer
  is 401.
- Every POST and PUT also needs the server's own `Origin`. Otherwise the answer is 403.
- There are no cookies and no CORS headers. A Content-Security-Policy allows only the
  page's own scripts (ES modules) and stylesheets, with no inline script or style: sizes and
  colours that data decides are set through the CSSOM, never a `style` attribute.
- The static files hold no data. Every fact comes from the API, behind the token. Only flat
  `.html`, `.js` and `.css` files in `cockpit/static/` are served.
- A refused decision (wrong persona, wrong verdict, not a person, card not open) is a 403
  with the kernel's reason, and nothing is recorded.
- Each write is also noted in the ledger as `cockpit_write`, with the person and persona: the
  project's own ledger, or the factory canon's (`_factory`) for signals, concepts, embeds and
  the factory's autonomy cap.
- Layouts are the cockpit's own files under `<home>/_cockpit/layouts/`, never in a project
  ledger. Evidence exports go to `<home>/_cockpit/exports/` and are downloaded once.

The persona is chosen in the person chip. It is not a login: whoever holds the session can pick
any persona. The persona decides what the Inbox offers, and the kernel checks it on every
decision.

## The shell

- **Sidebar** (240px, collapsible to a 56px icon rail with tooltips, dimmer than the content):
  the hypha logo, **New project**, then Home, **Square**, **Catalogue**, Projects, **Inbox** (with
  the count of cards this persona may decide across every project, updates and concepts
  included), Insight (the Floor) and Jobs. A live badge on Projects counts the cells running now
  (`kernel.status.live`). With a project open, its views follow in `project_context` order, each
  with an icon. Settings sits at the bottom.
- **Top bar** (52px): the breadcrumb; the **lens switcher**, a segmented control with an icon and a
  label per lens (Business, Concept, Delivery, Operations, Compliance, Insight), starting in the
  persona's own lens; **Search or jump** (Ctrl+K); density; theme (dark, light or system, the
  accent and the corners); **Customize** on Home; and the **person chip** (initials, name and
  persona). The chip opens the person menu: your name, the persona, and **Link for another tab**.
- **Assistant**: the **Ask Rihma** button, or the `/` key, opens a 400px drawer on the right. On a
  wide screen it pushes the page aside rather than covering it.
- **Phone width**: one column, a bottom bar of five icons with labels (Home, Square, Inbox,
  Projects, Ask), the lens switcher as icons, and no customizing.

The look comes from `cockpit/static/tokens.css`: a warm neutral scale in 12 steps for both
themes, one brand accent (Rihma amber, or teal, violet, blue, green or rose), status colours
(good, warning, serious, critical) that always come with an icon and a word, the validated
categorical chart palette, a radius scale (soft, or crisp at half), elevation (a tinted layered
shadow in light; a lighter surface, a border and a 1px top highlight in dark), a 4px spacing base
and type on a 14px base that `font_scale` (0.9 to 1.25) scales. Icons are one inline `<symbol>`
sprite in `index.html`, drawn for Rihma: 24×24, stroke 1.75, round caps, `currentColor`, always
with a label or a tooltip. Motion is short (hover 120-150ms, enter about 200ms); nothing loops
except a running cell's dot, and `prefers-reduced-motion` turns motion off.

## Lenses

A lens is the same work seen for a purpose (`kernel.lenses`):

| Lens | Question | Home starts with |
|---|---|---|
| Business | What is coming, when, and what does it need from me? | key figures, decisions, capabilities, the square, health, activity |
| Concept | What do we assume, and what does the plan say? | decisions, the square, evidence coverage, the pipeline |
| Delivery | How is the run going, and why did something fail? | live agents, gate trend, task timeline, decisions, activity |
| Operations | What runs in production, and is it healthy? | health, updates, decisions, activity, spend |
| Compliance | Can we show what ran, which versions, who approved, and that it was checked? | evidence packs, autonomy, evidence coverage, activity, updates |
| Insight | How does the factory itself perform, and what has it learned? | key figures, gate trend, builder models, evidence coverage, spend, the pipeline |

Each persona starts in its own lens and may switch; the choice is kept per persona in the tab. In
a project, the lens and the project's stage order its views (`project_context`): the first tab is
what that order puts first.

## Home: the dashboard

Home is a 12-column grid (max 1600px) of widgets for the lens. Each widget is a card with an icon,
a title, an ⓘ holding the question it answers and where its numbers come from, and a menu: chart,
list or table view, size (S is 3 columns, M is 6, L is 12, XL is 12 and taller) and remove. Every
widget offers its data as a table too, so a value is never only in a chart or a tooltip.

| Widget | Question | From |
|---|---|---|
| Key figures | How is the factory doing at a glance? | projects in flight, decisions waiting with the oldest age, first-round gate pass, criteria proven, capabilities in use |
| Delivery square | Where is everything in the delivery square? | `signals.square`: a four-corner loop, or a step flow when small |
| Pipeline | Where is the work? | stage columns with project chips (profile icon, title, maturity) |
| Decisions waiting | What waits on me? | `queue` plus concepts and updates, and every open change as the Inbox lists it (also one whose class needs no business decision before it is applied, such as IT's infra change), with inline verdicts for cards this persona may decide |
| Capabilities | Which capabilities do we have? | `catalogue`: state, profile, deliverable, pack version and validity |
| Live agents | What are agents doing now? | Working, with a pulsing dot, only while `status.live` reports a running cell; otherwise the project's real state: waiting on a person, paused, apparatus failure, ready or done |
| Task timeline | Where did the time go? | each round on one time axis, coloured by its gate's verdict, with merge and escalation marks |
| Gate trend | Is the factory getting the work right? | rounds passed and not passed per hour, one axis, the rate as headline |
| Evidence coverage | How much is proven rather than claimed? | a 100% bar per project; not measured is hatched, never drawn as zero |
| Activity | What just happened, and who did it? | a feed with person and agent avatars, or people against agents per hour |
| Builder models | Which models do the work well? | first-round warranted rate per builder model, with n |
| Project health | Which projects are on track? | health, forecast and now line per project |
| Updates | What changed outside, and what should we try? | update cards, rendered for the lens: the business proposal, the expert sentence, or the developer JSON in Delivery and Insight; Start a trial, Decline or Defer |
| Autonomy | How far may the factory act alone? | the ladder 1-4 with the cap; a business owner, IT or compliance sets it with a reason |
| Evidence packs | Can we show it was checked? | each project's attestation and an Export button |
| Spend | What does the work cost? | cloud spend (not measured until prices exist) and local tokens |
| Feed health, Eval trend, Try it | (by work profile) | "Not measured yet" with the reason when there is no data |

Every number says whether it is observed or derived, carries its denominator ("10 of 13 tasks
gated") and how fresh it is. A figure that was not measured is shown with a dashed border and the
reason, never as 0. A delta appears only against a named baseline. Charts follow one method: one
axis, thin marks with 4px rounded data ends, a 2px gap between stacked segments, a legend for two
or more series, a tooltip on hover and keyboard focus, status colours only where a series means
good or bad (with an icon and a label), and the categorical palette validated for both themes with
the data-viz skill's `validate_palette.js` (no failures; light slots 3 to 5 sit below 3:1 on the
surface, so every chart has its table view). Charts never animate on refresh.

## Customize

**Customize** (top bar, on Home) turns the grid into a layout editor: drag a widget to reorder it
(or Alt+arrow keys on a focused widget), cycle its size S, M, L, XL, remove it, or **Add widget**
from the searchable library drawer. Ctrl+Z undoes (20 steps), Esc cancels, **Done** saves.
**Reset to default** goes back to the lens preset; **Export** and **Import** move a layout as JSON.

A layout is versioned JSON, `{v: 1, lens, widgets: [{id, type, size, view, filter}], theme:
{accent, density, mode, radius, font_scale}}`, kept on the server per person, persona and lens
(`GET` and `PUT /api/layout`). The lens presets are read-only: the first edit saves a personal
copy. The server refuses unknown widget types, more than 24 widgets, theme values outside the
fixed sets, and a non-person. localStorage only caches the layout. Changing the theme or density
in the top bar keeps it with the lens's layout and in the browser.

## The assistant

The drawer is a chat: your messages on the right, the assistant's on the left with a bot avatar,
a thinking state, and suggested questions for the lens and view ("Where do I approve the plan?",
"How is the current run going?", "Make the gate trend bigger and show it as a table", "Use a
compact teal theme", "Make a feedback chat for our website"). The conversation is kept per
project in the tab.

`POST /api/assistant {question, persona, project, view, person, lens}` calls `kernel.assistant.ask`;
the server adds `ui = {widgets: the library, layout: your current layout}`. The answer shows:

- **sources** as chips that link to their records; a source the records do not hold is marked
  "not found in the records";
- **Take me there**, which opens the view and highlights the control (`data-control`) for two
  seconds. Every control in `cockpit/ui_map.json` exists on the page as `data-control`;
- **proposals** as cards (the action in plain words, its arguments and why), each with Confirm
  and Dismiss. Confirm calls the same route a click would, signed with your name. A
  **layout_edit** or **theme** proposal is shown first as a live preview on Home, with **Keep**
  (saves the layout) or **Undo**, in the page and in the chat. **create_embed** opens the embed
  form, filled in. A proposal the kernel dropped is shown greyed, with its reason.

The assistant writes nothing itself.

## The delivery square

**Square** is the home of the flow: needs arrive from the operation, a concept is validated, the
factory builds, end users test and feedback flows back, and production runs with DevOps,
maintenance, security and compliance around it. A map shows the loop with the counts and the
people in each corner, each with the persona they signed with: each corner's link names its count
and its people in words and shows them on keyboard focus as on hover, and each card below has one
keyboard stop that names them all; below it:

- **Needs arrive**: **Log a signal** (the need, its channel and source, signed; the signal keeps the
  signer's persona), and the signals with their state: every signal still new and the newest
  others, with **Show every signal** for the rest, so a new signal can always be triaged.
  **Triage** routes a signal about an existing project to that project as a change, triaged at
  once like every change filed in the cockpit (its class, by the signal's persona, its way back and
  its impact), or makes a new need a concept (`kernel.signals.triage`, no model). A signal triaged
  on the page stays listed though it is no longer new, and its link to what it became takes the
  focus.
- **Concepts to validate**: a business owner or product owner edits the title, work profile,
  maturity and mode (**Save the edit** records only the fields that changed), then **Validate**, or
  **Park** or **Reject** with the reason why (without one the decide route refuses it with a 400,
  from any page, and records nothing). Deciding goes through the Inbox's decide route on the
  factory's own canon (`_factory`); a validated concept becomes a project at once, and its intake
  runs from the need on the project's first **Advance** (`apply_concepts`). The project shows who
  asked for it. An edited title is the one every Inbox and the decisions widget show.
- **The factory**: the pipeline per stage.
- **End-user testing**: feedback from end users, with how many are open and how many are not
  triaged yet. Every open report waits (a triaged one on a decision, one not triaged yet for its
  class), and the map's corner counts them all as "feedback waiting".
- **Production**: what runs at stage 7.

A link can name one concept, `#/square/<card>` (a signal's concept, the Inbox, the catalogue): the
square brings it into view and gives it the focus.

## The capability catalogue

**Catalogue** lists every capability: in use, pilot, trying, building, shaping or proposed (a
concept waiting). A lifecycle strip counts each state and filters by it; profile, deliverable and
a search narrow it further; cards or a table show the same items, and a filter keeps the focus on
the control that was used. A card shows the profile icon, the state, what it does, the deliverable
(a proposed concept's is its work profile's: an agent is a capability pack), and the capability
pack's version and validity; a release whose pack is not built yet says so, never "no release". It
opens its project, or the concept on the square.

## New project

**New project** (sidebar, Projects, Catalogue) opens a form: a title, the need or a written spec,
the **work profile** as seven cards (web app or service, integration, mobile prototype, ML or data
pipeline, agent or assistant, harness engineering, ops agent), each with its icon, summary,
deliverable and a **Preview** badge where its template is still to come, with the profile's note on
what is. The cards are a radiogroup: one tab stop, and the arrow keys move and choose. **Let Rihma propose**
picks the profile by rule from the words of the need (`propose_profile`) and says which words; a
keyword the rule found inside a longer word is shown with the person's own word ("train" in
"trainees") and the proposal is marked uncertain. The button keeps the focus once Rihma has read the
need. Then maturity, mode and who asks. Creating it starts the intake as a job, and the new project's
heading takes the focus.

## Projects and the Inbox

**Projects** shows every project as cards or a table: its work profile, its state with an icon and
a word (Working only while a cell runs), its now line, a stage bar, maturity and mode, and the
cards waiting for you. **Rihma itself** (`_factory`) comes first: the factory's proposals to change
itself.

**Inbox** gathers every card the persona may decide across every project and Rihma itself,
grouped by kind (decisions that hold work up first: escalations, holdout rulings, approvals,
validations, deploy gates, incidents, paved roads and trust; then changes, updates and concepts;
the panel's questions last; a blocking card first within its group), by project or by age. Each
card decides in place through the same route as the project's Inbox. Card ids repeat across
projects, so each card's reason, verdicts and status line are named by its project and id; a
reason typed on one card survives a decision on another, and the focus moves to the next card. A
card that accepts a release carries the release link and checklist, as in the project's Inbox. A
question opens its options, the plan opens the plan, a concept opens it on the square.

## A project

The header carries the work profile, the title, the maturity and mode, health, the **autonomy
cap** ("Autonomy 3 · prepare"), the ledger's state, the now line (with the real state: a running
cell, apparatus failure, ready), a compact stepper of the seven stages with their icons and counts,
and **Pause** or **Resume** and **Advance**. The views are tabs with icons, in the order the stage
and the lens bring forward; **Show all views** shows every view. The Overview has the alignment
panel and the stage counts beside it.

- **Tasks** is a board, a timeline (each round on one time axis, coloured by its gate's verdict)
  or a table. Ctrl+B cycles them; the choice is kept per view.
- **Releases** shows the capability pack first, as it was last written: its version, valid or why
  not, the pinned hashes (contract, product revision, artifacts, the models that built and judged
  it), the signature and SBOM notes, and a YAML view (`render_yaml`). Showing it never builds it,
  so a visit records no version. While the latest release has no pack, the card says "Not built
  yet"; **Build the capability pack** (or **Build again**, `data-control="build_pack"`) builds it,
  signed by a compliance, IT, business owner, product owner or developer persona, and the version
  changes only when what the pack names changed. Then each release as its steps, its holdout
  results (scores, never scenarios) and the rest of its record.
- **Evidence** shows the attestation (attestable, chain broken or insufficient evidence; never
  "compliant"), what the pack holds, the control table (evidenced, partial or not evidenced) and
  **Export evidence pack**.
- **Comments**: requirements, criteria, tasks, releases and cards have a **Comment** button that
  opens a small thread. A comment decides nothing; a product owner or business owner may
  **Promote to change**, which files and triages a change card.

The views as before:

- **Overview** has a **Health** card (`kernel.status.health`): on track, at risk or off track,
  each with an icon and a word. Its reasons are listed, and each
  id in a reason links to its card, assumption, decision or task. The forecast shows the tasks
  left, the median minutes per task and the ETA, with its basis verbatim. Until a task has
  merged, the median and the ETA say "not measured", never a number. The card comes first for
  the business owner, the product owner and the stakeholder. While a plan waits on approval, a
  callout above it links to the **Plan**. While a cell runs, a **live panel** shows
  what it does (see Tasks).
- **Plan** (offered as a tab, marked with a person icon, while a plan card is open): at
  pilot and production maturity nothing is built until a person approves the plan
  (`kernel.plan`, FR-P7). The view shows the plan's state (waiting on approval, approved by whom,
  or rejected with the reason the next Advance redraws it with), then every requirement with its
  sources, provenance and criteria. One line says that an edit makes its editor the requirement's
  owner. For the business owner, product owner and developer, each requirement has an **Edit**
  form: the statement, then criteria rows (given, when, then, and the kind of check) that can be
  added or removed. Saving makes the person the owner (customer-confirmed by them); the card is
  withdrawn and the kernel reissues it for the edited plan at once. Then **Approve the plan**, or
  **Reject and redraw** with a required reason. Earlier plan cards are listed with what became
  of them. In the **Inbox**, the plan card is rendered the same way, not as its raw text. Other
  personas see the plan read-only, with who may decide it.
- **Try it** (first for the end-user tester; FR-R1): the release link, which opens the running
  environment's url in a new tab, and one plain check per criterion ("Given …, when …, check
  that …") with its evidence chip. Each check has a checkbox: the ticks are only the person's own
  aid, kept per person in that tab's sessionStorage and never sent as a decision. **Report what
  you saw** on a check files a change through the changes route, its text starting with
  "[<criterion id>] ", so the change names the criterion. Every Inbox card that accepts a
  release (an approval titled "Accept the demo …", and every validation card) carries the same
  link and checklist above its decision buttons.
- **Spec & contract**: under every requirement a **Sources** line lists where it came
  from (question ids, which link to the question, "request", or a change card) and its
  provenance: customer-confirmed or customer-endorsed by a named person, assumption, or
  vendor-proposed. Every criterion has an **evidence** chip (`kernel.status.evidence`):
  - **verified**: a gate passed at the merged revision and a test on main names it. Press the
    chip to see the gate's task, round and tests;
  - **claimed**: a test names it, but no gate proved it;
  - **held out**: it passed against a release;
  - **failing**: it failed against a release;
  - **not measured**.

  Each requirement shows its count per state. **Impact if changed** under each requirement
  shows what changing it would touch.
- **Questions** (in the Questions view and as Inbox cards) offer their options as radio
  buttons. The first option is the panel's proposal, marked **Recommended (the panel's
  proposal)**, and is selected by default. **Other: write your own** takes free text. Below
  them come the asking perspective's reasoning and the other perspectives' opinions side by
  side. **Answer** posts the chosen text to the answer route, so it is recorded as the person's
  own word. **Let Rihma assume** is a separate, secondary action: it turns the proposal into an
  assumption with a due date. **One at a time** (a toggle in the Questions view, kept in the tab)
  shows only the first open question, with Answer, Let Rihma assume or **Skip for now**, then the
  next: the conversational intake pattern. A skipped question comes back after the others.
- **Inbox** and **Changes**: every change card shows **Impact if changed** before the decision
  buttons (FR-P5): the requirements, the criteria with the tests on the product's main that
  name them, the tasks that would reopen, the approvals that would go stale and who gave
  them, and the releases that carry them. Until triage names requirements, the impact is not
  known yet, and the card says so. An empty Inbox says "Nothing needs you right now" with the
  project's one line. An empty Changes view explains how to report feedback.
- **Tasks** is a board with five lanes: Pending, Building, Merged, Escalated and Stopped. Each
  card shows the task id, its title, its rounds and the last gate's four signals as small
  chips (tests, trace, fail-first, verifier). An escalated card links to its Inbox card.
  **Details** on a card shows every round and what each gate saw. On a phone the lanes stack.
  The Building lane carries the **live panel** (`kernel.status.live`, FR-T1): the task, the role
  and model, "n tool steps so far" and the last action (tool and target), read from Gnomon's own
  audit trail in the lane the project holds (`$GF_LANES`, else `~/gf-lanes`). It polls every 5 s
  while the page is visible and stops while it is hidden (Page Visibility API). When nothing runs,
  it says "No cell is running for this project."
- **People and agents**: a person is an owner, and an agent is a delegate. Wherever the
  Ledger or a decision shows who acted, a person has a person badge (their initials, with
  the persona). An agent has an agent badge: a model role such as builder, verifier, analyst or
  holdout author (a bot, with its model where the ledger records one), or the kernel (a
  diamond). Every decision row names its accountable person.
- **Cell**: every Gnomon run of the project (FR-M3): role, model, verdict with Gnomon's
  native bucket and exit code, whether the audit chain re-verified, tokens and cost. A cost
  that was not measured is shown as "not measured", never as zero.
- **Floor** (Insight in the sidebar). Its first row is the gate's judgement of the work
  (`floor.gates`, FR-M3): the first-round pass rate ("n of m tasks passed their gate on the first
  round"), tasks merged, tasks escalated and rounds judged. Below it, under **Harness outcomes
  (each Gnomon run)** and the `harness_note` verbatim, come the per-run figures: runs, the harness
  pass rate over measured runs only, and not-measured runs and apparatus failures counted beside
  it. A run that was not measured is shown in a neutral style, never as a failure. Then each run
  by phase and verdict; each project with its gate figures and its harness figures; cloud spend
  apart from local spend; and each builder model's record (cells run, first round warranted,
  escalations, rounds to pass).

A link can name one item in a view, `#/p/<pid>/<view>/<id>` (for example a question or a
decision): the page brings it into view and marks it.

**Jump to** (Ctrl+K, or Cmd+K on a Mac) opens a palette that jumps to any project, any view
of the open project, or any of its open cards. It filters as you type. The arrow keys move
through the matches, Enter opens one and Esc closes the palette. It is a modal dialog labelled
"Jump to". The focus stays inside it while it is open. After a jump, the view's heading takes
the focus; on Esc, the focus goes back where it was.

## Embeds: a chat window for a website

**Settings → Embeds** (product owner, business owner and IT; anyone else is told who creates one)
creates a chat for a website with exactly one capability: **feedback** on a product (filed as a
change on that project; never on Rihma itself, which is refused) or a business **need** (filed as
a signal in the square). The form takes the project, the allowed websites, a label and a short
public brief; a proposed project the list does not hold is said, and none is chosen in its place.
The embed sees nothing of the project's records. The
key is shown **once**, masked until you choose Show, with the snippet from `kernel.embeds.snippet`
and copy buttons; only its hash is kept. The snippet points at the embed server named by
`--embed-base` (or `RIHMA_EMBED_BASE`), never at the cockpit; Settings and the key box say which
address that is, or warn that none is set and the snippet points at the local embed server for
testing. The list shows each embed's state and message count, and **Revoke** stops it at once;
revoking it again is a 409 and records nothing. The assistant's "make a feedback chat for our
website" opens this form, filled in.

**Settings → Appearance** reads the layout of the lens in view first, so it shows the person's own
theme, and a change made there (mode, accent, density, corners, text size) is saved with that
lens's layout; a save that fails says so. The accent swatches are a radiogroup with the arrow keys.

## Driven in a browser

`tests/test_ui_drive.py` (FR-T1-AC-17) builds a demo home, starts the cockpit on 127.0.0.1 and
drives it in headless Chrome over the DevTools protocol (a standard-library WebSocket client),
with real mouse clicks and typing: sign in and name the person, switch the lens, validate a concept
on the square as a business owner, decide a card in a project, Customize (resize a widget, Done),
ask the assistant "Where are the releases?" and press **Take me there**, then open Settings. After
every step there must be no console error, uncaught exception, failed request or CSP violation; a
probe at the end shows the watch sees one. It is skipped when Chrome is not installed
(`RIHMA_CHROME` names another binary). `RIHMA_UI_SHOTS=<folder>` keeps a screenshot per step.

## Compliance and autonomy

The Compliance lens starts with every project's evidence pack (its attestation, pack and an
Export button), the autonomy ladder, evidence coverage, activity and updates. **Export** writes the
zip into `<home>/_cockpit/exports/` (`kernel.evidence_pack.export`, recorded in the project's
ledger) and hands back a one-time download link, served only from that folder, as an attachment.
The **autonomy cap** (1 answer, 2 suggest, 3 prepare, 4 deliver) is set for the factory, or lowered
for a project, by a business owner, IT or compliance, always with a reason; the ladder lists the
history.

## Personas

| Persona | Lens | Can do in the cockpit |
|---|---|---|
| Business owner | Business | approve, accept a validation, decide a change or an escalation, validate a concept, set the autonomy cap, create an embed, request a change |
| Product owner | Concept | approve, accept a validation, decide a change or an escalation, validate a concept, answer questions, create an embed, promote a comment |
| Concept evaluator | Concept | answer, let the factory assume, confirm or refute an assumption |
| End-user tester | Business | report an observation: defect, UI gap, missing requirement, data; report on one check |
| IT / partner | Operations | approve or refuse a deploy, mark a road configured, file an infra change, set the autonomy cap, create an embed |
| Developer | Delivery | answer escalations, approve gates, record trust, decide incidents, decide updates |
| Operations | Operations | acknowledge, roll back, open a defect |
| Stakeholder | Business | answer questions, request a change, comment |
| Compliance | Compliance | export evidence, set the autonomy cap, decide updates |

Who may decide each card kind comes from `kernel/canon.py` (`CARD_DECIDERS`, `CARD_VERDICTS`).
The plan's editors are its approval card's deciders (business owner, product owner,
developer); who may pause and resume comes from `kernel/safestop.py` (`MAY_PAUSE`: business
owner, product owner, developer, operations, IT). Questions and assumptions are open to every
persona. Anyone may comment; a product owner or business owner promotes. The Floor is open to
every persona.

## Projects and jobs

**New project** creates the project and starts its intake in the background. **Advance** on a
project starts `python -m kernel.cli run <pid>`, which runs until the next gate a person must
decide. Only one job runs per project at a time. A job is a child process with an argument
list, never a shell string, started from the repository root with `GNOMONFACTORY_HOME` set. Its
log is in `<home>/jobs/`. The **Jobs** page shows each job's state and the last lines of its log;
a run the autonomy cap stopped shows as capped, not done, with the kernel's reason.

## API

| Method and path | What it does |
|---|---|
| `POST /auth` `{bootstrap}` | exchanges the one-use bootstrap for a session token |
| `GET /api/meta` | stages and their four bands, modes, maturities (and the last stage each runs), change classes, card kinds, who may pause (`may_pause`), the plan's editors and the criterion kinds; the lenses and each persona's lens, the widget library and the lens presets, the layout's fixed sets, the work profiles and deliverables, signal channels, who edits concepts, creates embeds, promotes comments, exports evidence, builds a capability pack and sets the autonomy cap, where embed snippets point (`embed_base`, null when unset, and `embed_base_local`), and whether the assistant uses a model |
| `GET /api/personas` | personas with labels and the card kinds each may decide |
| `GET /api/projects` | id, title, maturity, mode, stage, profile, open cards, `now` (state and line), `running` (a cell runs now) and the last cell's outcome; `_factory` first, as "Rihma itself" |
| `GET /api/projects/<pid>` | the whole project view: `meta` (with `requested_by` from the need for a project a validated concept made), `now`, `health`, `evidence` (every criterion) and `evidence_summary` (counts per state, for the project and per requirement), `stage_summary` (a count per stage, the four bands; stage 5 also has verified and claimed), each requirement's sources, each question's `options` with the proposal first and `recommended`, change cards with their `impact`, ledger status against the kept head with who acted on each recent event (`actor`: a person with the persona, or an agent with its model) |
| `GET /api/projects/<pid>/evidence` | each criterion's evidence state: verified, claimed, held out, failing or not measured (`kernel.status.evidence`) |
| `GET /api/projects/<pid>/now` | the project's state (working, waiting on you, done, failed) and one line (`kernel.status.now`) |
| `GET /api/projects/<pid>/health` | on track, at risk or off track, the reasons, and the forecast with its basis (`kernel.status.health`) |
| `GET /api/projects/<pid>/inbox?persona=<p>` | open cards that persona may decide, with their verdicts; a change card carries its `impact` (null until triage names requirements) |
| `GET /api/projects/<pid>/impact?requirements=R-1,R-2` | impact if changed, for any requirements (`kernel.insight.impact`) |
| `GET /api/projects/<pid>/alignment` | the canon's alignment findings, an empty list when there are none (`kernel.insight.alignment`) |
| `GET /api/projects/<pid>/cell` | every Gnomon run of the project (`kernel.projections.cell`) |
| `GET /api/projects/<pid>/plan` | `required` (does this project hold its plan for approval), the open plan `card` or null, `approved` (`plan_approved`: card, by, spec version), `compiled`, `editors`, the `spec` (requirements with their criteria, provenance and owner) and the `history` of earlier plan cards (`kernel.plan`). Opens no card |
| `GET /api/projects/<pid>/live` | what the running cell is doing: task, lane, role, model, tool steps, last action, ended; or `running: false` with why (`kernel.status.live`, lanes root `$GF_LANES` or `~/gf-lanes`) |
| `GET /api/projects/<pid>/try` | the release, environment and url to try, and one item per criterion with its text and evidence state (`kernel.status.try_it`) |
| `GET /api/floor` | the gate's judgement `gates` (tasks gated, first round passed and rate, merged, escalated, rounds), runs by phase and verdict, the harness outcomes `overall` with `harness_note`, spend (`kernel.projections.floor`), plus `model_reliability` and `immune_memory` (`kernel.learn`) |
| `POST /api/projects/<pid>/cards/<cid>/decide` | `{verdict, person, persona, reason}`; parking or rejecting a concept without the reason is a 400, and nothing is recorded |
| `POST /api/projects/<pid>/questions/<qid>/answer` | `{text, person, persona}`; regenerates the brief. When the text is one of the options, the `cockpit_write` note keeps which (`option`, 0 is the proposal) |
| `POST /api/projects/<pid>/questions/<qid>/assume` | `{person, persona}`; regenerates the brief |
| `POST /api/projects/<pid>/assumptions/<aid>/settle` | `{confirmed, person, persona, correction}` |
| `POST /api/projects/<pid>/changes` | `{persona, person, text, hint?}`; returns the triage. A report on one Try it check starts its text with `[<criterion id>] ` |
| `POST /api/projects/<pid>/plan/requirements/<rid>` | `{statement, acceptance: [{given, when, then, kind}], person, persona}` → `kernel.plan.edit_requirement`: the person becomes the requirement's owner, and the plan card is reissued (`kernel.plan.open_card`) where the maturity needs one. A non-person, a persona that may not edit the plan, or a plan already compiled is a 403 and nothing is recorded |
| `POST /api/projects/<pid>/pause` | `{person, persona, reason}` → `kernel.safestop.request_pause`; a persona that may not pause is a 403, a project already paused a 409 |
| `POST /api/projects/<pid>/resume` | `{person, persona}` → `kernel.safestop.resume`; a persona that may not resume is a 403, a project that is not paused a 409 |
| `POST /api/projects` | `{title, source, profile, mode, maturity, requested_by}`; creates the project with its work profile and starts the intake job |
| `POST /api/projects/<pid>/advance` | starts `kernel.cli run` |
| `GET /api/jobs` | jobs with their state and the last lines of their logs; a finished run carries its `outcome` (the state and reason of the result it printed last), and one the autonomy cap stopped has the state `capped` |
| `POST /api/links` | a new one-use sign-in link for another tab |
| `GET /api/dashboard` | every widget's read model in one answer: `kpis` (each with provenance and denominator), `pipeline` (chips with profile), `queue`, `decisions` (queue kinds plus concepts and updates, and every open change as the Inbox lists it, with its class and `needs_decision`; with age), `gate_trend`, `gates`, `timelines` per project, `activity`, `coverage`, `catalogue`, `square`, `projects` (now, health, live and the last cell's outcome), `models`, `updates`, `autonomy`, `evidence_packs` (each attestation, read-only), `spend`, `try_it`, `feed_health`, `eval_trend`. Records nothing |
| `GET /api/catalogue` | `kernel.dashboard.catalogue` with the states, profiles and deliverables; a proposed concept carries its work profile's `deliverable`, and a project its `releases` and `latest_release` |
| `GET /api/square?signals=&show=` | `kernel.signals.square` with the signals, concepts (their editable fields), end-user feedback, production and the people per corner with the persona they signed with. `end_user_feedback_waiting` (and `end_user_feedback_open`) counts every open end-user report, triaged or not; the kernel's not-triaged count is `end_user_feedback_untriaged` (the dashboard's `square` says the same). `signals_list` holds every signal still new and the newest others, newest first; `?signals=all` lists every one, and `signals_all` says whether the list is whole; `?show=S-8,...` also lists the signals named (up to 20, such as one just triaged), and `signals_shown` names those listed only for that |
| `GET /api/signals?state=` | the signals, the channels and states |
| `POST /api/signals` | `{text, channel, source, person, persona}` → `kernel.signals.receive`, which keeps the persona; 201 |
| `POST /api/signals/<sid>/triage` | `{person, persona}` → `kernel.signals.triage` (no model): a change on a project, triaged at once (`triage`), or a concept; 409 when already triaged |
| `POST /api/concepts/<cid>/edit` | `{title?, profile?, maturity?, mode?, person, persona}` → `edit_concept` with only the fields that differ from the card (`changed`); when none differs, nothing is written or recorded. Another persona is a 403, a bad value a 400. A concept is then decided through `POST /api/projects/_factory/cards/<cid>/decide`, which applies it (`apply_concepts`); an update card's decision applies it too (`apply_updates`), and both answer with `applied` |
| `GET /api/profiles` · `POST /api/profiles/propose` | the work profiles and deliverables · `{text}` → `propose_profile` (records nothing) |
| `GET /api/inbox?persona=` | every open card that persona may decide, across projects and `_factory`, with `count`; a concept's title follows its edit, here and in the dashboard's `decisions` |
| `GET /api/ui-map` | `cockpit/ui_map.json` |
| `GET /api/layout?persona=&lens=&person=` | the person's layout for that persona and lens, or the lens preset (`preset: true`), and the `default` |
| `PUT /api/layout?persona=&lens=` | `{person, layout}`; saved under `<home>/_cockpit/layouts/`. Unknown widget types, more than 24 widgets, a theme value outside its set or a non-person are refused |
| `GET /api/projects/<pid>/timeline` | each task's rounds with start, end and verdict (`kernel.dashboard.timeline`) |
| `GET /api/projects/<pid>/context?persona=&lens=` | the lens (the persona's own, or the one asked for), `default_lens`, the stage-ordered `views`, the work profile and widgets (`kernel.lenses.project_context`) |
| `GET /api/projects/<pid>/comments?kind=&id=` · `POST` | the comments, by target · `{target: {kind, id}, text, person, persona}`; a bad target or empty text is a 400, a non-person a 403 |
| `POST /api/projects/<pid>/comments/<cmid>/promote` | `{person, persona}`: a product owner or business owner turns it into a triaged change; anyone else is a 403 |
| `GET /api/autonomy` · `PUT /api/autonomy` · `PUT /api/projects/<pid>/autonomy` | the ladder, caps and history · `{level, reason, person, persona}` for the factory, or to lower one project's cap; only a business owner, IT or compliance, always with a reason |
| `GET /api/projects/<pid>/pack` | the capability pack as last written (`kernel.packs.latest_pack` where the kernel has it, else the latest release's `capability-pack.json`), with its YAML, `history`, `latest_release`, `current` and the `builders`; `pack: null` with a `note` while the latest release has none. It never builds a pack and records nothing; 404 without a release |
| `POST /api/projects/<pid>/pack/build` | `{person, persona}` → `kernel.packs.build_pack` for the latest release: a new version in `packs.json` and the ledger only when the content changed, and a `cockpit_write`. A persona that does not export evidence, or a non-person, is a 403 |
| `GET /api/projects/<pid>/attestation` | what an export would attest, computed read-only |
| `POST /api/projects/<pid>/evidence` | `{person, persona}` → `kernel.evidence_pack.export` into `<home>/_cockpit/exports/`; returns the file and a one-time `download` path |
| `GET /api/exports/<token>` | that export, once, as an attachment, only from the exports folder |
| `GET /api/embeds` · `POST /api/embeds` · `POST /api/embeds/<eid>/revoke` | the embeds, never a key or its hash, with `embed_base` (null when unset) and `embed_base_local`; reading creates nothing · `{kind, origins, project, label, brief, person, persona}` → the embed, its `key` (in this answer only) and the `snippet`, which points at the embed server; a feedback embed on `_factory` is a 400 · revoke; an embed already revoked is a 409 and nothing is recorded |
| `POST /api/assistant` | `{question, persona, project, view, person, lens}` → `kernel.assistant.ask` with the widget library and the person's layout; records nothing |

Every GET is a read: none of them records a decision, marks an approval stale, appends
to a ledger or creates Rihma's own canon on a home without one. `<pid>` may also be `_factory`,
Rihma's own canon.

The cockpit keeps the last ledger head it verified for each project in
`<home>/cockpit/heads.json`. If the ledger is cut or its tail rewritten after that, the
project shows "ledger broken".
