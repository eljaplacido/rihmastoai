# Start here, tasks you open, and the whole log of a run

When you open a project, its first view starts with **Start here**: what Rihmasto understood the project to be,
the one to three things to do there now, and what Rihmasto does on its own meanwhile. Tasks open into a panel of
their own, and the small "last action" and job boxes open the whole log.

## Start here

- **What Rihmasto understood**, in one line, and where that came from (an adopted project's README paragraph, or a
  new project's goal). If it is wrong, press **Correct it** and add a description or material: every later step
  uses it.
- **Do now**: at most three steps, the most pressing first, read from the project's records by rule, each a button
  that opens the place that does it. For an adopted or attached project:
  - **Confirm what kind of work it is** when Rihmasto only guessed it;
  - **Review the upstream change** when its repository moved on and a change card waits for a decision;
  - **Commit your work in progress** when its working copy holds a lot uncommitted (50 files or more) or a change
    older than two days (see [Work in progress](#work-in-progress) below);
  - **Read its repository's spec and tests** when nothing of its repository was aligned yet (Alignment's Read the
    repository). The step says what Alignment reads (requirement lines in specs and requirement documents, JSON rule
    files, task lists, a README's status table, ADRs, API contracts and test names) and what it does not read yet
    (other rule or data files such as YAML, issue or evidence logs, task rows in other documents). After the read it
    names the document its items came from and the sources it left unread, such as `rules/*.yaml (2 files)` or
    `docs/evidence/issues.jsonl`: if those hold the project's real
    work, the items may be out of date, so reject what is stale;
  - **Assess it**, or **look at the top findings** of its latest assessment (check that each is real first);
  - **Connect your coding agent** when no coding agent has worked on it here yet.

  For any project, the steps also come from what it waits for: a decision, a question, a failed run, or Advance.
- **Meanwhile**: the cell building a task now, a job running in the background (each with its log), the upstream
  watch, the automations that reach the project and its scheduled health checks; or that nothing runs on its own
  yet, with the step that would.

## Work in progress

Rihmasto reads a project's commits. An adopted project whose upstream is a folder on this machine, or an attached
repository, also shows its **work in progress** on its Overview: what the working copy holds that is not committed
yet. The **Work in progress** card says how many files are modified, added, deleted, renamed, conflicted or untracked
(what `.gitignore` hides is left out), grouped by top-level folder, when the oldest of those changes was made, which
branch you are on and how far it is ahead of or behind its remote branch, and when the last commit was made.

- It reads file names and times with git, never a file's contents, and writes nothing to the repository or the
  project's records. **Refresh** reads it again; otherwise a reading is reused for a minute.
- A folder that is almost all untracked files (build output, generated assets, caches) **looks generated**: it is
  not counted as work, and the card suggests adding it to `.gitignore`.
- When the work to commit is large or old, Start here nudges you to commit what is ready, so Rihmasto reads it. It
  never blocks anything.
- A project adopted from a remote address, or whose folder is gone or is not a git working copy, says "not
  measured" and why.

Ask Rihma **"what am I in the middle of?"** or **"what's uncommitted?"** for the same reading, with Take me there.
From a terminal: `rihmasto wip <project>` (`--json` for the reading as data).

**Hide** hides the panel for you only, recorded with the steps it showed. It comes back by itself when a step it
did not show appears, marked "new since you hid it"; **Show Start here** brings it back at any time.

Ask Rihma **"what should I do here?"** for the same answer, with each step as its own button; in a project,
**"where do I start?"** and **"what now?"** ask the same. From a terminal: `rihmasto start-here <project>`.

**Correct it** and every step that points at an Overview control take you to Overview, whichever view the project
opened on. The Board's **Next development step** is Start here's first step when the board has nothing of its own
to build, so the screen gives one next step. On a phone, entering a project starts the page at Start here; the
project's header is one scroll up.

Ask Rihma to **sync a coding agent** ("how do I keep Claude Code in sync with this project and what should I
monitor?") for a sync plan: give the agent the project's brief and Rihma's tools, hand it the first open task that
waits for nothing, and what to monitor; each step is a button, and nothing is handed off until you press it.

## Tasks you open

Every task on the **Tasks** board has **Open**, which opens its panel (the address is `#/p/<project>/tasks/<id>`):

- its status and where it came from: the factory's plan, the repository's own spec accepted in Alignment (with the
  file), or the existing code at adoption;
- its acceptance criteria, each with its evidence state;
- the tests that check it and how they last ended: from its last gate round, a test named for its criterion, or a
  repository test traced to it in Alignment (not measured here, and why);
- the commits that carry its id, the agents and coding sessions that worked on it, and its history from the ledger;
- **Hand it to a coding agent** (the brief narrowed to this task, posted in the agent channel with the task named),
  **Start it**, **Mark it done** with what shows it is done (a test run, a commit, a link), and **Ask Rihma about it**.

A done you mark is yours, signed and kept apart from the gate: the task reads "done, marked by you", never merged,
and sits in the board's **Marked done** lane. A task waits for the tasks it depends on (until each is merged or
marked done) and for the decision it is escalated to: until then its panel says what it waits for, with the way
there, and offers no **Start it** (nor **Mark it done** while the decision is open). The board filters by status and
by source, each project keeping its own filters, and draws itself again while work runs or a person marks a task. Ask Rihma "what about T-003?",
"start T-003", "hand T-003 to Claude Code" or "mark T-003 done: the suite passed at abc1234"; each write is proposed
for you to confirm. From a terminal: `rihmasto task list|show|start|done|handoff <project> [<task>]`.

## The whole log of a run

**Open the whole log** on a job (Jobs, a project's Overview), on the live panel's last action, or in **Agent
activity**'s runs opens the log at `#/jobs/<id>`, or `#/jobs/cell:<project>` for the cell building a task: all of it
(a very long one from its last 256 KiB, saying so), following new output while the run goes on (**Follow new
output**), with **Copy**. A finished job lists what the project's records gained from its start to its end, each
with its place; an adoption lists what the project it made gained. Once the cell stops, `#/jobs/cell:<project>`
keeps the whole log of the cell that ran last, marked finished, with what its round changed for its task.
