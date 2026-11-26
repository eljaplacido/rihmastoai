# The Knowledge graph view

Look at a project's records, or every project's at once, as the knowledge graph links them: what each
requirement rests on, which criteria and tests check it, which tasks serve it, who decided what, and what
shipped. Filter it, focus on one record, see what is missing, and keep the views you use. (FR-GRV1; the graph
itself is described in [Knowledge graphs and ontologies](../knowledge-graph.md).)

## Where it is

- **Knowledge graph** in the sidebar: every project you may see, in one view.
- **Knowledge graph** among a project's views: that project only.
- **Ask Rihma**: "Show me how requirements trace to tests in Equipment loans" (or in two projects: "... in
  Equipment loans and Room bookings") answers with what the slice holds, and **Take me there** opens the view
  with those filters. "Explain R-2 in the knowledge graph" explains one record: what it is, its state, what it
  links to and any issue, and Take me there focuses the graph on it.
- The command line: `rihmasto graph view <project> [--kinds requirement,criterion,test] [--states open]
  [--focus R-1 --hops 2] [--json]`, or `rihmasto graph view --all` for every project.

## What it shows

Every record the ontology (`kernel/ontology.json`) knows, as a node: the request, questions and assumptions,
requirements (each version), acceptance criteria, held-out checks, tasks, tests on main, cards (changes,
incidents, approvals) and decisions, comments, signals and observations, releases and packs, agent runs, the
models they ran on and the revisions they produced, and the people who answered or decided. Each node has its
kind, a label, a state (open, closed or superseded; a test, a person or a model has none), when its record
began, and the record that holds it. Each link has its relation (has criterion, checked by, serves, derived
from, rests on, decides...) and how it is known; a link a model proposed and no person decided is dashed.

**Issues** are found from the records and shown on the node, in words beside the colour:

| Issue | Means |
|---|---|
| Needs a look (amber ring) | a requirement in force that no test checks; a criterion no test names yet; a test that checks no criterion |
| Contradiction (red ring) | a decision a later change overturned; a requirement resting on an assumption a person refuted; a link to a record that does not exist; an id an amendment restated |

Click an issue above the graph to show only the nodes with an issue.

## Filters

One panel scopes the graph and the table alike (on a phone it is a sheet, behind **Filters**):

- **Kinds**, grouped by family, each with how many match and how many there are;
- **Relations**: only these links;
- **State**: open, closed, superseded;
- **Time**: the last 24 hours, 7, 30 or 90 days, or all records;
- **Find in the graph**: words in the id or the label;
- **Only nodes with an issue**;
- across projects, **Projects**.

The filters live in the address (`#/p/<project>/graph?kinds=requirement,criterion,test&states=open`), so a
view can be bookmarked or sent, and Ask Rihma's Take me there opens exactly that slice.

**Focus**: open a node (click it, or press Enter on it) and choose **Focus here**: the graph keeps that node and
what lies within one to four links of it, in either direction.

A large project stays fast: at most 300 nodes are drawn by default, the focus first, then the nodes with an
issue, then requirements, criteria and tests, newest first, and a note says how many more are not shown, by
kind. Narrow the filters or focus to see them.

## Graph and table

The graph is drawn in columns along the trace: what was asked, the requirements, their criteria, the tasks and
tests, then the runs and releases. Colour says a node's family (what was asked and agreed; who decided and what
changed; what was built and checked) and its shape says it again (circle, square, diamond), with its label
beside it. Drag to pan; **+** and **-** (or Ctrl and the mouse wheel, or a trackpad pinch) zoom; **Fit** shows it whole.
With the keyboard, Tab reaches the graph, the arrow keys move between nodes, Enter opens one, Escape closes it.

**Table** shows the same slice as two tables, the nodes and the relations, each node with its state, issues and
a link to its record. On a phone the table is what opens first; the graph is one tap away.

## Make it yours

- **Saved views**: **Save this view...** names the current filters ("Only open requirements and their tests").
  Open a saved view from the same menu, make one open first (**Open ... by default**), or delete it.
- **Opens as**: the table on a phone and the graph elsewhere (the default), always the graph, or always the
  table.
- **Pin to Home** adds the current slice to your Home layout as a *Knowledge graph* widget: what matches, its
  issues, and a link back.
- **Reset to default** forgets your views for this project and goes back to the automatic mode.

Views are kept per person in the cockpit's own folder (`_cockpit/graph_views/`), as a Home layout is, and never
in a project's ledger: they are your preference, not a record. Saving one is signed with your name.

## What it never shows

- **Holdout content.** The graph never reads the holdout custody: a held-out check is a node with its verdicts,
  never its scenario.
- **Credentials.** A label that looks like a key or a password is replaced by "[hidden: it looks like a
  credential]".
- **What you may not see.** With access enforced, a project's graph is shown only to someone who holds a
  persona on it, and the view across projects leaves the others out. `--audience` on the command line shows the
  graph as the ontology's other audiences (assistant, verifier, builder) may see it.

Nothing in the view writes a record; the graph is rebuilt from the records on every read. When the records
disagree with the ledger, the view says **Not measured now** and why, and shows nothing rather than something
wrong.

## For developers

- Read model: `kernel/graph_view.py` (filters, the slice, the limits) and `kernel/graph_view_nodes.py` (nodes,
  states, issues, routes). Command: `kernel/graph_view_cli.py`. Ask Rihma: `kernel/graph_assist.py`.
- Routes: `GET /api/projects/<pid>/graph`, `GET /api/graph`, `GET` and `PUT /api/graph/prefs`
  (`cockpit/graph_routes.py`).
- Page: `cockpit/static/graph.js`, `graph_draw.js` (the SVG, no library), `graph_panel.js`, `graph.css`.
- Tests: `tests/test_graph_view.py`, `tests/test_ui_graph.py`.
