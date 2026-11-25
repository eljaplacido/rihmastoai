# The Rihma cockpit

Rihmasto takes an idea or an existing repository, turns it into a spec and a tested contract, has
coding agents build against it behind a gate that runs the tests itself, ships it only to targets IT
configured, and keeps it healthy, with a person signing every decision
([D-0023](../decisions/D-0023-what-rihmasto-is-and-is-not.md)). Today the one target that has run for
real is the local preview; the cloud roads are tested against stand-ins. Gnomon is the harness
underneath it, and keeps its name. What it carries is agentic capability: web apps, integrations,
mobile prototypes, ML pipelines, agents and assistants, harness engineering, and ops agents that
deliver a report with an evidence pack. Each release is a hash-pinned capability pack whose evals travel with it.

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
**Open in another browser tab** in the person menu of a signed-in tab: it makes a new one-use link
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

The persona is chosen in the person chip. Without an access file it is not a login: whoever holds
the session can pick any persona, and the top bar and the person menu say so ("single operator:
personas are self-declared"). The persona decides what the Inbox offers, and the kernel checks it on
every decision.

## Enforced access

With an access file in mode `enforced` ([guides/access.md](guides/access.md)), the cockpit stays on
127.0.0.1 behind IT's identity-aware proxy, which runs beside it:

- The identity comes only from the identity provider's signed token the proxy forwards, verified with
  the provider's public keys from the access folder; the cockpit holds no shared secret. Any other
  request is a 401, and so is a request that repeats the token header; while the access file or the
  key file cannot be used, every request is a 403 that says why.
- The session travels in `X-Rihmasto-Session` (the token may use `Authorization`) and ends when the
  token it was opened with expires; the page then signs in again once through the proxy before it asks
  the person. A run or a new project starts only when the access file names an isolation runner.
- The page says the mode (`<meta name="rihmasto-access">`). An enforced page signs in with
  `POST /auth` and no bootstrap: the session is opened for the verified identity and answers only that
  identity. The printed one-use link is not needed, and **Open in another browser tab** is hidden. A single
  operator's page asks for nothing until a sign-in link is opened.
- The person menu shows the verified name, read-only, and offers only the personas granted on the
  open project (outside a project, those granted anywhere). The top bar says "enforced: signed in as
  <name>" (in either mode the note keeps its words: under 1520px of top bar the lenses show their
  icons, and the note shrinks to its shield, with the words as its tooltip, only when nothing else can
  give way).
- Every write route that takes a person or persona signs as the verified person (a `person` that
  differs is a 403) and needs the persona granted on its project; the factory's own writes need it on
  `_factory`. The decision, the ledger and `cockpit_write` record the identity beside the person.
- The proxy's public address (the access file's `origin`) is accepted as `Host` and `Origin` beside
  `127.0.0.1:<port>`. `GET /api/meta` carries the mode, and in enforced mode the identity, its
  grants, when the session ends and where untrusted code runs, under `access`; the person menu shows
  that line.

## The shell

The cockpit always says what a page is about: **all projects**, or **one project** (FR-UXO1).

- **Scope bar** (the strip at the top of the main area, `data-control="scope_switch"`): "All
  projects", or "Project: <title> ▾" followed by the capsule and the view. Its switcher lists the
  projects, the recent ones first, and "← All projects"; switching keeps the view you are on when
  the other project has it. Inside a project the whole frame takes the project's own accent (a
  coloured top edge, the switcher, the header's edge and the sidebar's project block), so a project
  page is unmistakable. Every page title states its scope: "Home and Horizon · Inbox" in a project,
  "Inbox · all projects" outside one.
- **Sidebar** (240px, collapsible to a 56px icon rail with tooltips, dimmer than the content). Outside
  a project: the hypha logo, **New project**, then **Review** (since you last looked), Home,
  **Square**, **Catalogue**, Projects, **Inbox** (with the count of cards this persona may decide
  across every project), **Insights**, Floor, Jobs, Automations, **Health**, **Agent activity**, **Data and context** (the factory's stores, ledgers and each agent role's context health) and the **Knowledge graph** across projects.
  The pages that exist per project too say so: "Inbox · all projects". A live badge on Projects
  counts the cells running now (`kernel.status.live`). Inside a project the sidebar is the
  project's: "← All projects", the project's name with what waits on you there, the recent projects
  to switch to, and a short way to Home, Projects, the Inbox and the Square. It never repeats the
  project's views: those are the capsules on the page. Settings sits at the bottom.
- **Top bar** (52px): the **lens switcher**, a segmented control with an icon and a label per lens
  (Business, Concept, Delivery, Operations, Compliance, Insight), starting in the persona's own lens;
  **Search or jump** (Ctrl+K); density; theme (dark, light or system, the accent and the corners);
  **Customize** on every page; and the **person chip** (initials, name and persona). The chip opens
  the person menu: your name, the persona, and **Open in another browser tab**.
- **Assistant**: the **Ask Rihma** button, or the `/` key, opens a 400px drawer on the right. On a
  wide screen it pushes the page aside rather than covering it.
- **Phone width** (390 px and up): one column, a bottom bar of five icons with labels (Home, Square,
  Inbox, Projects, Ask), the lens switcher as icons, Customize as an icon, the scope switcher full
  width. A project's five capsules fit one row and a capsule's views scroll as chips; outside its
  Overview a project's header is compact (title and actions), so the capsules are in the first
  screen. Dialogs open as sheets from the bottom, tables become stacked rows (each value with its
  column's name), and every touch target is at least 40 px. No page scrolls sideways.

### Capsules: a project's views by purpose

A project's views are grouped into five **capsules** (D-0024 point 3, `data-control="capsules"`). The
top row has the five; each opens its own short row of views:

| Capsule | Views |
|---|---|
| **Now** | Overview, Inbox, Review, Questions (and the Plan while it waits on approval) |
| **Build** | Spec & contract, Tasks, Changes, Alignment, Console, Assumptions, Assessment, Cell |
| **Run** | Releases, Outputs, Health, Automations, Try it |
| **Govern** | Evidence, Track, Insights, Knowledge graph, Ledger |
| **Agents** | Channel, Sessions, AI tools, Context |

Sessions, Context and Knowledge graph show once the views that draw them register (below); until
then their capsule simply lists the views it has.

A project opens in its persona's capsule: a business owner, product owner or stakeholder in Now, a
developer in Build, IT and operations in Run, compliance in Govern (each capsule opens on the view
last used there). A capsule counts what waits on you in it (Now: the Inbox's cards; Build: changes and
escalations; Run: gates, incidents, roads and updates; Govern: holdout rulings). Addresses are
unchanged (`#/p/<pid>/<view>`), so every old link, the palette and Ask Rihma's **Take me there** open
the right capsule and view. Alignment and AI tools appear for an adopted or attached project,
Assessment for an adopted one, the Plan while it waits; a view of a module that is off does not appear.

Views take part by **registering** (`cockpit/static/capsules.js`):

```js
import { registerView } from "./capsules.js";
registerView({ id: "sessions", capsule: "agents", label: "Sessions", icon: "bot", order: 20,
  personas: ["developer", "it"],              // brought forward for them in the capsule
  render: (p, inbox, ctx) => node,            // or module: "sessions.js" (its render export, loaded on first open)
  when: (p, ctx) => true,                     // whether it applies to this project
  wait: (p, inbox) => 0 });                   // how many things in it wait on the person
```

A registered view gets its address (`#/p/<pid>/<id>`; add it to `PAGE_ROUTES` in `core.js` and to
`cockpit/ui_map.json` too, so Ask Rihma and the route test know it). A view that is not registered
simply does not appear. There is no horizontal row of every view and no "Show all views".

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

## Review: since you last looked

**Review** (`#/review`, first in the sidebar) is the morning check of what agents and automations did
since you last looked, across your projects; each project has a **Review** tab for its own. Home's first
card says it in one line ("Since you last looked: 3 shipped, 2 waiting on you, 1 failed") and opens it.
Compact rows in six groups (waiting on you, went wrong, decided for you, shipped, from your IDE, cost and
usage) say who or what did each thing and link to its record; a drawer previews the diff and the gate's
signals. Approve, decline, overturn, report a change or mark reviewed in place, by mouse or keys (`j` `k`
`a` `d` `r` `o`, Enter and Esc), then **Mark all reviewed**; **Morning digest** sends the same review to
your Teams, Slack or mail receiver at the time you set. See [the review guide](guides/review.md).

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
| Staying on track | Is each project on track against its approved plan? | `kernel.track` per project, worst first: on track, at risk, off track or not measured, the first reasons, a checkpoint due and an autopilot holding ([autopilot and tracking](guides/autopilot-and-tracking.md)) |
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

**Customize** is in the top bar on every page.

On any page but Home it customizes **the view you are on** (`customize_view`): each section gets
**Up**, **Down**, **Size** (normal, compact or wide) and **Hide** or **Show**. In a project the
capsule row gets them too (`customize_tabs`): hide a tab you never use, or pin a favourite to the
top row beside the capsules. A section or tab that holds a decision waiting on you is never hidden
("Waits on you: stays shown"), and a page with hidden sections says how many, with **Show them**.
**Reset** brings the view and the tabs back; **Done** ends it. These choices are kept **on the server,
per person and view** (`GET` and `PUT /api/view-layouts`, in the factory home's
`_cockpit/view-layouts/`, outside every ledger, beside Home's layouts), so they follow you to another
computer or browser; the browser keeps only a copy to draw from while the server cannot be reached.
The first time a person opens the cockpit after this change, the layouts an earlier version kept in
that browser move to the server in one save and the browser's copy is forgotten. Ask Rihma makes the
same changes from words ("hide the brief", "move Needs attention to the top", "show all sections"):
the change is shown as a preview on the view with **Keep** or **Undo**, and only **Keep** saves it.

On Home, Customize turns the grid into a layout editor: drag a widget to reorder it
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
compact teal theme", "Make a feedback chat for our website").

**What it talks about** (`assistant_scope`): a line at the top of the chat says "Talking about:
Home and Horizon · Inbox" (or "all projects") and follows the page; its choice switches between
**This view**, **This project** and **Whole platform**. Each answer begins with what it was about.
A question that names another project by its title ("How is Equipment loans doing?") is answered
about that project, and Rihma says it switched. A proposal names its target (the project, or your
layout). The conversation is kept per project, and one for the whole platform, in the tab.

**How-to answers are practical** (`kernel/assistant_howto.py`): "How do I export the evidence?"
answers with numbered steps for this project: the path to click ("Open Home and Horizon › Govern ›
Evidence", with **Take me there**), what to press there, and the command with the project's id, your
name and persona filled in, each with **Copy**. A command whose value is not known is left out
rather than shown with a placeholder ("<pid>" never appears), a missing name is asked for, and "the
snapshot does not show" becomes where to look instead.

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

### Walkthroughs

**Walkthroughs** (Home's header, the flag in the chat's header, and a card on Home while there is no
project) runs a walkthrough in the chat: plug in an existing project, start from a new idea or from
documents, set up a model, or a five-stop tour. Rihma asks one thing at a time with the answers as
buttons, shows a folder's scan in the chat (**See the full map** opens New project's map), and each
change waits on a Confirm button signed with your name, carried out by the cockpit's own route. An
adoption or an intake is waited on in the chat, with its progress and then What's next. An answer
whose words ask for a walkthrough ("I have an existing project", "uusi idea") carries a **Walk me
through it** button. See [Walkthroughs in Ask Rihma](guides/walkthroughs.md).

## The delivery square

**Square** shows how needs move from arriving to production, across all projects, and says so in
its first line: needs arrive from the operation, a concept is validated, the factory builds, end
users test and feedback flows back, and production runs with DevOps, maintenance, security and
compliance around it.

Its **scope switch** (`square_scope`, "Show: All projects" or one project) shows the square for one
project: the signals routed to it, its place in the pipeline, its end-user feedback and production
(a concept is not a project yet, so a project's square has none, and says so). Five **lanes** come
first, in the order a need moves: Needs arrive, Concepts to validate, Being built, End users test,
In production. Each lane's count is a link to its items below; an empty lane says what would
appear there and how it gets there.

With all projects in scope, a map shows the loop with the counts and the
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
what is. The first card, **Let Rihma choose**, is chosen until a person picks another: nothing is assumed,
and the intake proposes the profile by rule from the need or the folder, asking which kind it is when the
words point to more than one; **Project settings** changes it later. The cards are a radiogroup: one tab
stop, and the arrow keys move and choose. **Let Rihma propose**
picks the profile by rule from the words of the need (`propose_profile`) and says which words; a
keyword the rule found inside a longer word is shown with the person's own word ("train" in
"trainees") and the proposal is marked uncertain. The button keeps the focus once Rihma has read the
need. Then maturity, mode and who asks. Creating it starts the intake as a job, and the new project's
heading takes the focus. The third way to start, **Shape it in chat**, opens a conversation instead of
the form.

**Choosing a folder or a file by browsing** (FR-PICK1). Every field that takes a path on the cockpit's
machine has **Browse…** and **Browse here** beside it: An existing project's folder and a folder given as
the need, Add material, Shape it in chat's attach, Settings > Folders the cockpit may read, an automation's
rescan folder, a Google Cloud road's workload identity file, and a walkthrough's folder step in Ask Rihma.
Typing or pasting a path still works. **Browse…** opens the computer's own folder dialog when the browser
runs on the cockpit's machine for a single operator (the page at 127.0.0.1, no `--public-origin` in the
way, access not enforced); from another computer, a phone or under enforced access it opens the folder
browser instead. **Browse here** is the folder browser in the page, always: the places to start from (the
folders you chose before, the allowed roots, the home folder, the drives), a breadcrumb, each folder with a
**git** badge, the project here that already holds it (adopted or attached) and whether the cockpit may
read it, a filter as you type, the arrow keys, Enter and Backspace, and **Choose this folder**. At phone
width it is a full-screen sheet. A folder outside the allowed ones offers **Allow …** (a single operator,
after a yes; signed and in the factory's ledger). Choosing a project's folder starts its scan at once. A
dropped folder fills only its name, since browsers do not give the full path. Ask Rihma's "adopt the project
in C:\dev\x" or "open the folder picker" offers **Plug in an existing project**, started from the folder
named. The rules are those of [the inputs guide](guides/inputs.md#choose-a-folder-or-a-file).

## Shape it in chat

**Shape it in chat** (`#/shape`, from Home's header or New project) is a conversation with Rihma, the
analyst role, beside a draft brief you can edit: who it is for, the problem, outcomes, scope in and
out, constraints, data and systems, open questions. Start with nothing, a sentence, a file or a folder.
Rihma asks one or two questions at a time and its answer arrives a moment after yours (the page reads
the conversation again until it is in). A field you edited stays yours. The panel under the draft says
what is still needed; **Create the project from this** asks for the work profile, mode and maturity
with Rihma's suggestion, creates the project as New project does and starts its intake. With no model
set up, the chat says so and links to Models setup. Conversations are listed at `#/shape` and resume
where they were ([guide](guides/shape-in-chat.md)).

## Models setup

**Models setup** (`#/models`, from Settings, or Home's **Set up a model** card while no model answers)
shows each role (analyst, holdout author, builder, verifier, assistant) with its model, endpoint host,
local or hosted, its key variable and whether it is set (never the key), and whether it answers.
**Change** points a role at an OpenAI-compatible endpoint, with presets; **Test** sends a tiny prompt
and says the latency or the error; **Back to shipped** removes the role from this machine's
`kernel/routing.local.json` ([guide](guides/models-setup.md)).

## Runners

**Runners** (`#/runners`, from Settings; `#/runners/<pid>` from a project's **Project settings**) says
which harness runs each role's cells, for the factory and for each project with its own choice: the
runner, its pinned version, and its assurance, **In-run policy enforced by Gnomon** or **Checked after
the run**. **Check** looks for Gnomon, Claude Code, Codex, OpenCode and a named command on this machine
and asks each its version, and says whether Docker can run the sandbox. **Choose a runner** sets a
role's runner: Gnomon at once, any other on a **Cell runner** card in the factory's Inbox, which an IT
persona approves or declines from the page's Choices. Project settings shows the project's builder and
verifier with their assurance, and a task's rounds name the runner that ran each one
([guide](guides/harnesses.md)).

## Automations

**Automations** (`#/automations`, in the sidebar) lists every automation with its plain-language summary,
owner, state and last run, filtered by state, scope kind or the project it reaches, with templates and a
builder that shows the kernel's summary before saving. Each has Run now, Dry run, Pause or Resume, Edit,
Remove and its runs. Each project has an **Automations** tab with the ones that reach it, its tags and
what ran on it; Home shows an automation the circuit breaker paused. The cockpit's scheduler ticks every
minute while it runs ([guide](guides/automations.md)).

## Projects and the Inbox

**Projects** shows every project as cards or a table: its work profile, its state with an icon and
a word (Working only while a cell runs), its now line, a stage bar, maturity and mode, and the
cards waiting for you. **Rihma itself** (`_factory`) comes first: the factory's proposals to change
itself.

**Inbox · all projects** gathers every card the persona may decide across every project and Rihma
itself, grouped **by project** (each project a heading with its colour and its count), by kind
(decisions that hold work up first: escalations, holdout rulings, approvals, validations, deploy
gates, incidents, paved roads and trust; then changes, updates and concepts; the panel's questions
last; a blocking card first within its group) or by age.

Every card, here and in a project's Inbox, **says what it wants** (FR-UXO1):

- it leads with one plain line, "Decide: <what in plain words>: <its choices>", for example "Decide:
  The task 'Show overdue loans first' failed its checks 3 times: retry it, accept it as it is or stop
  it" (`kernel/card_words.py`, the card's `plain`);
- its choices are clear options, each with a one-line meaning in the persona's words; nothing is
  chosen for you;
- once you pick one, **Why? (optional, saved with your decision)** opens with **Confirm**; parking or
  rejecting a need, or rejecting an approval, asks for the reason;
- **Add a comment** is a separate, secondary row at the card's foot: a comment decides nothing;
- the card's id, kind, the record's own wording, refs and who may decide are folded under **Details**
  (what a failed task's checks said is shown to a developer, folded for a business owner);
- a question shows "Rihma suggests: X" above its options and pre-selects none.

Each card decides in place through the same route as the project's Inbox. Card ids repeat across
projects, so each card's reason, verdicts and status line are named by its project and id; a
reason typed on one card survives a decision on another, and the focus moves to the next card. A
card that accepts a release carries the release link and checklist, as in the project's Inbox. A
question opens its options, the plan opens the plan, a concept opens it on the square.

## A project

The header carries the work profile, the title, the maturity and mode, health, the **autonomy
cap** ("Autonomy 3 · prepare"), the **Posture** chip (what the project's posture does, what holds
the project now, and changing it with a reason: [guides/postures.md](guides/postures.md)), the
ledger's state, the now line (with the real state: a running
cell, apparatus failure, ready), a compact stepper of the seven stages with their icons and counts,
and **Project settings**, **Pause** or **Resume** and **Advance**. Below it are the five capsules (Now,
Build, Run, Govern, Agents; see [Capsules](#capsules-a-projects-views-by-purpose)), each with its own
short row of views; each view's heading names the project ("Home and Horizon · Overview"). The
Overview has the alignment panel and the stage counts beside it.

**Words per persona** (`cockpit/static/words.js`, D-0024 point 5): where wording differs, a business
owner, product owner, stakeholder, concept evaluator or end user reads plain words about outcomes,
and a developer, IT, operations or compliance person reads the precise technical term, with the same
meaning (an escalation's Retry is "Let Rihma try again, with what the checks said" or "Run another
cell round with the objections as input"). Ids and records never change: only the words around them.

- **One word per concept.** A glossary in `words.js` gives each concept its business word, its
  technical word and a one-line explanation, and every view says it through `term()` (an element
  whose tooltip explains it and names the other reader's word) or `tw()`:

  | Concept | Business word | Technical word |
  |---|---|---|
  | ledger | decision record | ledger |
  | canon | project record | canon |
  | spec · contract · criterion | requirements · agreed checks · acceptance check | spec · contract · acceptance criterion |
  | gate · round · cell | quality check · attempt · AI build team | gate · round · cell |
  | merged · escalation | accepted (Done) · stuck task | merged · escalation |
  | holdout · fail-first | hidden test · test that fails before the fix | holdout scenario · fail-first test |
  | evidence pack · capability pack · attestation | proof package · release package · signed proof | evidence pack · capability pack · attestation |
  | maturity · mode · autonomy · posture | ambition · who answers · AI independence · working rules | maturity · mode · autonomy cap · posture |
  | signal · triage · stale | incoming need · sorting · out of date | signal · triage · stale |
  | hash · commit · repository · SBOM · CI · MCP | fingerprint · saved version · code · parts list · automatic checks · AI tool connection | the same |
  | stage, a task's status, a card's kind, a view's label | "Design and checks", "Done", "Stuck task", "Decision record" | "Spec and architecture", "Merged", "Escalation", "Ledger" |

- **No filler.** `SLOP` lists inflated, vague or self-referential words ("seamlessly", "leverage",
  "robust", "it's important to note", "Rihmasto has", "your journey"); no view uses them.
- **Records stay as written.** A record's own text (card titles, briefs, findings, the kernel's
  lines) is marked `data-ud` and shown as written; code and ids are monospace.
- **Every empty state says what would appear and how it gets there** (`emptyState(view)`: a "what"
  line and a "how" line, in each reader's words).

Wording a person flags as unclear is changed in `words.js`, in one place. `tests/test_ui_words.py`
reads every page and project view as a business owner and as a developer and fails on a filler
word, or on a technical word a business owner meets unexplained (`JARGON`).

- **Project settings** (`data-control="project_settings"`) changes the title, kind of work, mode and
  maturity with a preview of what the change means for the work done, signed with a reason; from it,
  **Go back a step** (`rewind_project`) sends the project back to its material, questions, spec or plan,
  and **Add material** (`add_material`) adds more of the request. The Overview's **What's next**
  (`next_step`) says what the project waits for, who can act, and has the buttons that move it on
  ([change anything](guides/change-anything.md)).
- An adopted or attached project's Overview has **AI tools in this project** (`ai_tools`): how the
  team's AI coding tools are set up in its repository (CLAUDE.md, AGENTS.md, Cursor rules, skills,
  subagents, slash commands, hooks, MCP servers), each with where it is, read from the committed
  revision and never run; and **Work on it from your IDE** (`ide_setup`): MCP configuration for
  Claude Code, Cursor and Codex pointing at Rihmasto's MCP server, how a change comes back, and
  **Copy the section** (`ide_section`) for your own AGENTS.md
  ([your IDE and Rihmasto](guides/ide-and-rihmasto.md)). `GET /api/projects/<pid>/ai-tools` reads it.

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
- **Track** (also the header's **Track** pill) shows whether the project stays on track against its
  approved plan, with every figure's basis; the human checkpoints, with **I looked** and, for a plan
  owner, **Set checkpoints and a budget**; the autopilot in a sandbox, with **Start the autopilot**
  and **Stop the autopilot**; and the delegations, with **Revoke**
  ([autopilot and tracking](guides/autopilot-and-tracking.md)).
- **Outputs** shows what each audience receives: a web app with sign-in, a container, an API
  description, an MCP server (planned), a delivery report, an evidence pack and the source, each with
  what it holds and whether it is ready. **Save the choice** (`data-control="choose_outputs"`) records
  which outputs the project delivers, signed and with a reason; **Build and download**
  (`build_output`) and **Build every chosen output** (`build_outputs`) build them from the records
  and the release, each file through a link that works once ([guides/outputs.md](guides/outputs.md)).
- **Assessment** (an adopted project brings it forward, after the first view) judges the system's
  repository from five perspectives: **Assess now** (`data-control="run_assessment"`) records a new
  version by rule at once, and with **Ask the panel too** (when the cockpit has a model) in the
  background; each
  perspective lists its findings with evidence, severity and suggested change, then what was not
  measured and why; the panel's proposals stay apart as opinions; **Suggested order** ranks what to fix
  first and offers quick selections, and each finding has its own suggested change kind with why; ticked
  findings are filed with **File the ticked findings as changes** (`data-control="assessment_changes"`). See
  [brownfield.md](brownfield.md#assessing-an-adopted-system).
- **Alignment** (an adopted or attached project brings it forward; its Overview offers it until the first
  scan) shows what the team's repository already holds and how the project would take it: **Read the
  repository** (`data-control="align_scan"`) proposes requirements, criteria, a tests trace with its basis and
  confidence, tasks, decisions, API contracts and gaps; each item has **Accept**, **Edit** and **Reject**
  (`align_decide`), each group **Accept all open** (`align_bulk`); suggested changes for the repository are
  copied or downloaded (`align_suggestions`), never written there. See
  [guides/alignment.md](guides/alignment.md).
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
- The **Intake summary** heads the Questions view: how the input was read (a need, a specification,
  a plan or a folder), then **From your input** (each fact, decision and requirement with its
  document and lines), **Asked** and **Assumed** side by side, the questions not asked because the
  input already says it, and the facet checklist with each facet's state
  ([guides/inputs.md](guides/inputs.md)).
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
- **Insights** (FR-INS1, [guide](guides/insights.md)): health, compliance, governance, security,
  context drift, QA and usage, for the factory or one project (and as each project's **Insights**
  tab), over 24 hours, 7 or 30 days or all records. One filter row (dimension, window, scope), stat
  tiles with a one-line insight computed by rule and a link to the records, charts with a table view,
  and **Not measured here** with why and how. **Pin to Home** adds a tile as an *Insight* widget;
  **Export** saves JSON, CSV or OpenTelemetry JSON and sends nothing anywhere. Routes:
  `GET /api/insights`, `/api/insights/tile`, `/api/insights/export` (cockpit/insights_routes.py).
- **Knowledge graph** (FR-GRV1, [guide](guides/knowledge-graph.md)): every project's records as the ontology
  links them (the sidebar page) and each project's own (its **Knowledge graph** view): a graph drawn by hand
  with pan, zoom and keyboard navigation, and its table twin (the default on a phone). One filter panel (a sheet
  on a phone) scopes both: kinds, relations, states, time window, words, only issues, projects; **Focus here**
  keeps a node and what lies within one to four links. Issues ring the node and say so in words: requirements no
  test checks, tests without a requirement, decisions overturned, requirements on a refuted assumption, broken
  links. The filters live in the route (`#/p/<pid>/graph?kinds=...`), which Ask Rihma's Take me there opens.
  **Saved views** (per person, outside every ledger), **Opens as**, **Pin to Home** (a *Knowledge graph*
  widget) and **Reset to default**. Routes: `GET /api/projects/<pid>/graph`, `GET /api/graph`,
  `GET`/`PUT /api/graph/prefs` (cockpit/graph_routes.py).
- **Floor** (Floor in the sidebar). Its first row is the gate's judgement of the work
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

## Console, terminal and Health

Each project has a **Console** tab: the workspace (an attached repository's folder, your own workspace,
or the console's working copy), who may run, and the commands it offers (stated, detected by rule,
`package.json` scripts, Makefile targets, CI steps), a command line, a Gnomon box (`gnomon task` under the
workspace's own surface) and the output streaming line by line, with Stop. Each run is a job (a console
run never holds up Advance) and `console_ran` in the ledger, for developers and IT unless IT changes it,
through IT's isolation runner when access is enforced. **Open a terminal here** opens the operating
system's terminal in the workspace, only from the cockpit's own loopback address; only a cockpit started
with `python -m cockpit.server` opens one. Each project's **Health** tab lists its enabled checks (the
test suite, CI/CD status, a dependency audit, the secret scan, licences, an SBOM, an HTTP probe, the
repo gate, the security gate, a custom command) with the last result, the trend, the last run and Run
now; the **Health** page shows every project's, Home and What's next say when checks fail, and the
cockpit runs checks on their schedule once a minute while it runs. Where the line is between your IDE,
the console and a real terminal: [the console and checks](guides/console-and-checks.md).

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
| `PUT /api/projects/<pid>/settings` · `POST /api/projects/<pid>/settings/preview` | `{title, kind, mode, maturity, reason, redo, person, persona}` → `kernel.project_settings.change`: a business owner, product owner or developer; recorded as `project_changed` with before, after and the impact; `redo` goes back to the step the change no longer fits. The preview takes the same body, is checked the same way and writes nothing ([change anything](guides/change-anything.md)) |
| `POST /api/projects/<pid>/rewind` | `{to: material \| questions \| spec \| plan, reason, person, persona}` → `kernel.rewind.rewind`; what it sets aside is kept under `superseded/`; a project with a release, or one a job runs for, is a 409 |
| `POST /api/projects/<pid>/material` | `{text \| path, note, reintake, person, persona}` → `kernel.project_material.add_material`; with `reintake` a run starts and the panel reads the new material first; with access enforced a path is refused (text only). `GET /api/projects/<pid>` carries `next` (`kernel.next_step`) and `change` (the settings, each step and what it would set aside, the material added) |
| `POST /api/projects/<pid>/pause` | `{person, persona, reason}` → `kernel.safestop.request_pause`; a persona that may not pause is a 403, a project already paused a 409 |
| `POST /api/projects/<pid>/resume` | `{person, persona}` → `kernel.safestop.resume`; a persona that may not resume is a 403, a project that is not paused a 409 |
| `POST /api/projects` | `{title, source, profile, mode, maturity, requested_by}`; creates the project with its work profile and starts the intake job. An optional `outputs` list is chosen at intake by the requester (`kernel/outputs.py`); a persona that may not choose outputs is refused before the project is made |
| `POST /api/projects/<pid>/advance` | starts `kernel.cli run` |
| `GET /api/jobs` | jobs with their state and the last lines of their logs; a finished run carries its `outcome` (the state and reason of the result it printed last), and one the autonomy cap stopped has the state `capped` |
| `GET /api/projects/<pid>/console` · `GET /api/projects/<pid>/console/output?job=&offset=` | the workspace, the console's settings, the offered commands, the recent runs and whether a terminal can open here; reads only · a run's output from `offset` (whole lines while it runs), its state, and the next offset ([console](guides/console-and-checks.md)) |
| `POST /api/projects/<pid>/console/run` · `POST /api/projects/<pid>/console/runs/<job>/stop` | `{line, shell?} \| {gnomon, role?, yes?}, timeout?, person, persona`: a job (201), `console_ran` in the ledger at its end · stop it and everything it started, answered once it ended |
| `POST /api/projects/<pid>/console/terminal` · `PUT /api/projects/<pid>/console/settings` | `{person, persona}`: the operating system's terminal in the workspace, from the loopback address only (a public origin is a 403, a cockpit not started from the command line a 409) · `{personas? (IT), commands?, person, persona}` |
| `GET /api/checks` · `GET /api/projects/<pid>/checks` | every project's checks, what fails and the catalogue · a project's checks with each last result, trend and last run; reads only |
| `POST /api/projects/<pid>/checks/<check>/enable` · `/disable` · `/run` · `POST /api/checks/enable` | `{config?, every?, on_fail?, person, persona}`, recorded as `check_enabled` · `check_disabled` · Run now, answered with the result (`check_ran`) · one check on several `projects`, signed on each |
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
| `GET /api/view-layouts?person=` | the person's Customize choices on every view but Home: `views` (`{"p:<view>" or "g:<page>": {order, hidden, size}}`), the capsule `tabs` (`{hidden, pinned}`) and `saved` (false until their first save); empty for no one. With access enforced, the verified person's own |
| `PUT /api/view-layouts` | `{person, persona, views?, tabs?, reset?}`: each view in `views` replaces that view's layout (`null` removes it), `tabs` replaces the tab choices, `reset` names views to remove (`"*"`: all, with the tabs). Saved under `<home>/_cockpit/view-layouts/`, outside every ledger. A bad view key, a size outside normal, compact and wide, more than 80 sections or 120 views, or a non-person is refused (`cockpit/viewlayout_routes.py`) |
| `GET /api/projects/<pid>/timeline` | each task's rounds with start, end and verdict (`kernel.dashboard.timeline`) |
| `GET /api/projects/<pid>/context?persona=&lens=` | the lens (the persona's own, or the one asked for), `default_lens`, the stage-ordered `views`, the work profile and widgets (`kernel.lenses.project_context`) |
| `GET /api/projects/<pid>/comments?kind=&id=` · `POST` | the comments, by target · `{target: {kind, id}, text, person, persona}`; a bad target or empty text is a 400, a non-person a 403 |
| `POST /api/projects/<pid>/comments/<cmid>/promote` | `{person, persona}`: a product owner or business owner turns it into a triaged change; anyone else is a 403 |
| `GET /api/autonomy` · `PUT /api/autonomy` · `PUT /api/projects/<pid>/autonomy` | the ladder, caps and history · `{level, reason, person, persona}` for the factory, or to lower one project's cap; only a business owner, IT or compliance, always with a reason |
| `GET /api/projects/<pid>/pack` | the capability pack as last written (`kernel.packs.latest_pack` where the kernel has it, else the latest release's `capability-pack.json`), with its YAML, `history`, `latest_release`, `current` and the `builders`; `pack: null` with a `note` while the latest release has none. It never builds a pack and records nothing; 404 without a release |
| `POST /api/projects/<pid>/pack/build` | `{person, persona}` → `kernel.packs.build_pack` for the latest release: a new version in `packs.json` and the ledger only when the content changed, and a `cockpit_write`. A persona that does not export evidence, or a non-person, is a 403 |
| `GET /api/projects/<pid>/attestation` | what an export would attest, computed read-only |
| `GET /api/projects/<pid>/assessment` | the system's assessment (`kernel.assess_cards.view`): the latest version, every version with its sha256 checked against the ledger's `assessment_recorded` (`intact`), what each finding was `filed` as and that card's state, `has_repo`, `run` (the background assessment's state, or null) and `panel_available` (whether the cockpit has a model). Records nothing |
| `POST /api/projects/<pid>/assessment` · `POST .../assessment/changes` | `{person, persona, panel}` → `kernel.assess.assess`, signed by that person, outside the write lock (its records keep their own file locks): by rule it is recorded before the answer (201, with the record in short); with `panel: true` the cockpit's model reviews it in the background (202). `panel: true` without a model is a 409, a project with no repository a 400, a second while one runs a 409 · `{findings: ["F-3", "P-1"], version, as, person, persona}` → `kernel.assess_cards.to_changes`: change cards with `refs.origin: "assessment"`, triaged by rule; an unknown version is a 404. Each is a `cockpit_write` too ([brownfield.md](brownfield.md#assessing-an-adopted-system)) |
| `POST /api/projects/<pid>/evidence` | `{person, persona}` → `kernel.evidence_pack.export` into `<home>/_cockpit/exports/`; returns the file and a one-time `download` path |
| `GET /api/exports/<token>` | that export, once, as an attachment, only from the exports folder |
| `GET /api/projects/<pid>/outputs` · `PUT /api/projects/<pid>/outputs` | the output targets, what each holds, the choice and who made it, the last builds · `{targets, reason, person, persona}` → `kernel.outputs.choose`; a persona that may not choose is a 403 |
| `POST /api/projects/<pid>/outputs/build` | `{targets, person, persona}` → `kernel.outputs.build` into `<home>/_cockpit/exports/`; each built file with a one-time `download` path; a target nobody chose is a 403 |
| `GET /api/embeds` · `POST /api/embeds` · `POST /api/embeds/<eid>/revoke` | the embeds, never a key or its hash, with `embed_base` (null when unset) and `embed_base_local`; reading creates nothing · `{kind, origins, project, label, brief, person, persona}` → the embed, its `key` (in this answer only) and the `snippet`, which points at the embed server; a feedback embed on `_factory` is a 400 · revoke; an embed already revoked is a 409 and nothing is recorded |
| `POST /api/assistant` | `{question, persona, project, view, person, lens}` → `kernel.assistant.ask` with the widget library and the person's layout; records nothing |
| `GET /api/projects/<pid>/track` · `PUT /api/projects/<pid>/tracking` | the project against its approved plan (`kernel.track.track`), its autopilot and delegations, and its tracking settings; records nothing · `{checkpoints, hold, due, budget, currency, person, persona}`: a plan owner sets them |
| `POST /api/projects/<pid>/checkpoints/<stage>/look` | `{note, person, persona}`: a person records a look at a checkpoint; a stage not reached is a 403 |
| `POST /api/projects/<pid>/autopilot` · `POST /api/projects/<pid>/autopilot/stop` | `{kinds, until, rules?, reason, person, persona}` → `kernel.autopilot.start` and a job running `autopilot run`; a kind never delegated or one the persona may not decide is a 403 · `{reason, person, persona}` → `kernel.autopilot.stop` |
| `POST /api/projects/<pid>/delegations/<DL-n>/revoke` | `{reason, person, persona}` → `kernel.delegation.revoke`; a persona that may not revoke it is a 403 |
| `GET /api/shape` · `GET /api/shape/<id>` · `POST /api/shape` | the conversations · one with its draft, what is still needed, Rihma's suggestion and the brief · `{text?, attach?, title?, person, persona}` opens one ([Shape it in chat](guides/shape-in-chat.md)) |
| `POST /api/shape/<id>/say` · `POST /api/shape/<id>/attach` · `PUT /api/shape/<id>/draft` | `{text, person, persona}` · `{attach: {path} or {name, text or data_base64}, person, persona}` · `{draft, person, persona}`; Rihma answers beside the request (`pending` until then); signed, in the factory's ledger |
| `POST /api/shape/<id>/create` | `{profile?, mode?, maturity?, person, persona}`: the project from the draft, as `POST /api/projects` makes one, its intake a job; `shape_created` in the factory's ledger |
| `GET /api/models` · `PUT /api/models/<role>` · `POST /api/models/<role>/test` · `POST /api/models/<role>/remove` | each role's model, endpoint, key state and readiness, the presets, `ready` · `{base_url, model, family?, key_env? or key?, keep_fallback?, person, persona}` into `kernel/routing.local.json` (a key never echoed) · a tiny prompt, records nothing · back to the shipped routing ([Models setup](guides/models-setup.md)) |
| `GET /api/runners[?project=<pid>][&check=1]` · `PUT /api/runners/<role>` | what runs each role for the factory and each project with its own choice, every choice and its state; `check=1` also looks for each runner here and for Docker; reading writes nothing · `{runner, project?, version?, model?, family?, command?, sandbox?, image?, endpoints?, reason?, person, persona}`: Gnomon at once, another runner on a `runner` card IT decides through the factory's own decide route ([Harnesses](guides/harnesses.md)) |
| `GET /api/modules` · `PUT /api/modules` · `PUT /api/projects/<pid>/modules` | the catalogue, the presets, the factory's set, the projects' own sets and `new_home`; reading creates nothing · `{preset | modules | inherit, reason, person, persona}` for the factory, or a project's own set; a business owner, product owner, IT, a developer or compliance; recorded in that ledger ([use only what you need](guides/use-only-what-you-need.md)). Any write of a module that is off is a 403 |
| `GET /api/automations` · `GET /api/projects/<pid>/automations` · `PUT /api/projects/<pid>/tags` | every automation (`?state=`, `?project=`) with its summary and runs, and what the builder offers; reading writes nothing · those reaching a project, its tags and what ran on it · `{tags, person, persona}` ([automations](guides/automations.md)) |
| `POST /api/automations` · `PUT /api/automations/<AU-n>` · `POST /api/automations/<AU-n>/pause` · `/resume` · `/remove` · `/run` | `{automation, person, persona}` signed where it acts, the kernel checking every scoped project · pause by anyone, the rest by its owner or IT · Run now recorded, carried out by the scheduler's next tick |
| `POST /api/automations/preview` · `POST /api/automations/<AU-n>/dry-run` | a draft's summary and the projects it reaches · what the next tick would do; both signed, both record nothing |

Every GET is a read: none of them records a decision, marks an approval stale, appends
to a ledger or creates Rihma's own canon on a home without one. `<pid>` may also be `_factory`,
Rihma's own canon.

The cockpit keeps the last ledger head it verified for each project in
`<home>/cockpit/heads.json`. If the ledger is cut or its tail rewritten after that, the
project shows "ledger broken".
