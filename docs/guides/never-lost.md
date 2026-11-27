# Never lost: why it is empty, who acted, what blocks work

Rihmasto is meant to be used every day on real projects, by one person or a team. This guide covers four things
that keep you on track (FR-NVL1):

1. **Why? Ask Rihma** on everything that is empty, not measured or failed.
2. **Who acted** on every Ask Rihma answer and every run.
3. **Harness and enforcement**: what changing the AI tool does to Gnomon's rules.
4. **Decide what matters**: of many open decisions, the few that block work, and the rest assumed for you.

## Why? Ask Rihma

Every empty state, every value that says *not measured*, every error box and every failed action's message has a
small **Why? Ask Rihma** button. Press it and Ask Rihma opens with the context: the view, the field, the project and
the words on the screen. Rihma answers **by rule**, without asking an AI model, from:

- a catalogue of reasons per view (`kernel/neverlost.py`, `VIEW_RULES`), checked against the project's own state:
  for example, Releases is empty because no work has passed its quality check yet, or because work is accepted but
  nothing has been released;
- a catalogue per field (`FIELD_RULES`): cost and tokens, tests, evals, releases, quality checks, agent sessions,
  findings, times;
- the record's own words, quoted back (for example "the run recorded no token counts");
- for an error, its kind (`ERROR_RULES`): a persona that may not do it, no model set up, a paused project, a step
  someone already settled, a confidential project, a folder the cockpit may not read, a cockpit that did not
  answer, or a bug (with Investigate with Rihma).

The answer ends with **the step that fills it**, as a button that takes you there and highlights the control.

Rihma checks the question's premise first (FR-NVL2). When a view's own records have data (Releases with a release,
Insights with recorded runs), it says the view is **not empty here** and what it shows, instead of inventing a
reason; a view no rule knows never takes the premise. A value that is *not measured* is named by its own label
(never its buttons), and the answer follows the value's own *To measure it* hint: a check not measured opens
Health, a time to resolve opens Incidents.

You can also type it: *Why is Insights empty?*, *Why is cost not measured?*, *Why is the page blank?* (the page you
are on), *Why is the Track view not measured?* Rihma reads the subject: a view named exactly, a figure it knows
(cost, tokens, tests, checks), or the page you are on; never a view that only shares a word with the question.

A failure asked in general, *Why did it fail?*, *Why is it broken?*, *Why did my last action fail?*, is answered by
the error rules from the last failure the page showed in the last ten minutes. With none, Rihma says so and opens
Incidents, where every failed action is kept with its message.

## Who acted

Under every Ask Rihma answer a line says who answered: Ask Rihma by rule (no model), or which model through which
harness (Gnomon's lane, or a harness such as Claude Code), on this machine or hosted, and that each proposal is
checked against the Inbox rules.

A project's **Who acted** view (Agents) lists every run: each build attempt with its runner (Gnomon enforces the
rules during the run; another harness is checked after the run), its model, the task's contract criteria and the
gate's verdict; and each model call with its role, model, where it ran, and whether it went through Gnomon's lane.
Each run keeps the enforcement that was in force **when it ran** (FR-NVL2): opting out later changes no past run,
and a run made during an opt-out says *Gnomon ran it without its in-run policy* and who opted out.
Ask Rihma: *who acted here?*, or *who acted on T-002?* for one task's runs.

## Harness and enforcement

In **Settings** (the platform) and in a project's **Who acted** view (that project): for each role (the builder,
the analyst, the holdout author, the verifier, the assistant), the harness and model it runs on now, what Gnomon
enforces on it, and what changing to each other harness would do.

- **Gnomon's enforcement is on by default.** Every run is held to the project's contract: the write scope, the
  criteria, and the gate (tests, fail-first, trace, the verifier) before anything merges.
- **Changing the harness** changes who does the work, never whether the gate decides. Gnomon as the runner
  enforces the rules while it works; Claude Code, Codex, OpenCode or a command you name are checked after the run
  by the same gate.
- **An opt-out is explicit.** IT or compliance may opt the platform out; IT, compliance, a developer or a product
  owner may opt one project out. It needs a reason, is signed and recorded in the ledger, and never skips the gate:
  it only records that runs without Gnomon's in-run rules are accepted, and every run then says so.

Ask Rihma: *if I change harness, does Gnomon still enforce?*

## Decide what matters

A project's **Decide what matters** view (Now) triages its open decisions by rule (`kernel/triage.py`):

- **Blocking work, most first**: an incident, a stuck task, a plan to approve, a go-ahead, a blocking question,
  a validation, a hidden-test ruling, a go-live; each with why.
- **The rest, assumed for you**: an open question goes on with the answer its perspective suggested (an assumption
  with a due date, open to a real answer later); a change or update is deferred until it matters; a card with
  nothing to assume stays with you. **Assume the other N for me** decides each through the Inbox's own rules,
  signed with your name, and records it as your delegated choice.
- **Assumptions that grew in importance**: an assumption's weight grows as work touches the requirement it is
  about (`kernel/assumption_weight.py`): a task (+1, +1 more once accepted), a test (+1), a change (+2), a release
  (+2), an overdue review (+2), a failed gate (+3). From weight 4 it comes back here as *grew in importance:
  reconsider*, with what triggered it. It moves into Blocking only when the next task to build rests on it.

The proposal holds only what **your persona may decide** (FR-NVL2). A card you may not decide says who decides it
and stays with them; when you may decide none, the button says *Nothing you may assume here*, and a confirm is
refused with that reason, recording nothing.

**Decide what matters across projects** (`#/decide`, in the sidebar) does the same for every project at once: the
blocking decisions ranked across projects by what stops most work, each with its project, and one proposal for the
rest. **Assume the other N across K projects** confirms each project's part through that project's own confirm,
signed and recorded there (`kernel/triage_all.py`).

Ask Rihma: *I have 50 decisions: what blocks work? Assume the rest* (inside a project, that project; from Home,
every project), or *which assumptions grew in importance?*

## When something breaks (FR-NVL3)

- **A project whose `project.json` cannot be read** is kept out of every list, so the others keep working. Home and
  Projects name it (*Stress project 07 cannot be read (project.json is not valid: line 1)*) with how to restore it;
  its page and Ask Rihma name the file (`kernel/store.py` `ProjectUnreadable`, `GET /api/unreadable`). Any record
  file that is not valid JSON is named with its line, never the parser's words (`RecordUnreadable`).
- **A write the disk refuses** (full, read-only, held by another program) records nothing: every file the request
  changed is put back and the ledger cut back to where it was (`kernel/journal.py`). The message names the file and
  says what to do; a retry works.
- **A cockpit restart mid-run**: every job is written down beside its log (`jobs/jobs.json`, `kernel/job_registry.py`).
  After a restart a run whose process is gone reads *Interrupted by a cockpit restart* with Run it again; one whose
  process still runs reads *still running from before the restart*, and Stop ends its whole tree. Job ids go on.
- **A removed project's old link** says who removed it, when, and where its records are kept, with Open Projects;
  Ask Rihma answers the removal by rule, or goes on at the platform scope (`kernel/recovery.py`).
- **A run ended from outside** (exit 4294967295 on Windows is -1) says so, and *Ask Rihma what went wrong* sends that
  job's own failure, so the answer is about it.
- **A panel the model answered nothing usable for** is not a done stage: the project says to check Models setup, and
  Advance runs the panel again.
- **Lanes**: a demo home (or one with a `.lanes-here` file) keeps its lanes in `<home>/lanes`; a home that shares
  `~/gf-lanes` with another is warned at start, with how to keep them apart (`kernel/lanes_home.py`). `--home` is
  made absolute at start.
- **Quick under load**: Data and context opens at once and measures Context health on its own (a project whose
  records did not change is not measured again); Home asked in many tabs at once is built once (`kernel/shared_read.py`).

## Routes

| Route | What it does |
|---|---|
| `GET /api/unreadable` | the projects whose project.json cannot be read, each with how to restore it (FR-NVL3) |
| `GET /api/why?view=&field=&kind=&basis=&project=` | why it is empty, not measured or failed, and the step that fills it |
| `GET /api/projects/<pid>/triage?persona=` | the blocking few, the proposal (what that persona may decide), the assumptions that grew |
| `GET /api/triage?persona=` | the same across every project: blocking ranked across projects, one proposal per project |
| `POST /api/projects/<pid>/triage/assume` | confirm the proposal (signed; `cards` narrows it) |
| `GET /api/projects/<pid>/who` | every run with who acted, and the project's harness and enforcement |
| `GET /api/harness-enforcement`, `PUT /api/harness-enforcement` | the platform's harness and enforcement; turn it off with a reason, or on |
| `PUT /api/projects/<pid>/harness-enforcement` | the same for one project |
