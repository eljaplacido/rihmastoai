# Development board, trace and briefing: advancing a project as a developer

When you open a project as a developer, Rihmasto shows where the building work is, who worked on it, and
what to do next. Everything is read from the project's own records (its contract, tasks, ledger, agent
channel and repository); nothing here asks a model, and reading changes nothing.

The owner (2026-11-25): "when I click in that [developer] role that I want to advance the project, I want
insights about the latest sessions, whether inside Rihmasto with Gnomon or in Claude Code ... and it would
tell me, this would be the next step in development".

## The Board (Build)

A developer's project opens on **Build, Board**. On top is the **developer briefing**:

- **Next development step**, with why and a button that does it. It is chosen in a fixed order: a decision
  that blocks a task, an outside session still open or work in progress, a gate round that failed, the
  first task ready to start, then what is left when every task is merged.
- **Only the decisions that block that step.** Nothing else nudges you (solo by default).
- **Latest sessions in any harness** since your last look: builder cells (Gnomon or another runner),
  Claude Code and Cursor sessions the hooks recorded, agents posting in the channel, MCP writes.
- **What changed**: gate rounds passed and failed, tasks merged, the newest round's tests, and whether the
  requirements were compiled again.

**Got it** records your look (signed, in the ledger as `dev_looked`); the next briefing counts from there.

Below, the lanes: **Planned** (not started, or a change waiting for its decision), **In progress** (a cell
running it, an open workspace, a hand-off, an outside session), **In review** (gate rounds without a
merge), **Blocked** (waits on a person: which card, who may decide it) and **Done** (on main). Each task
card lists its requirements, its criteria with given, when and then, the tests that name them, its commits
(read from the project's repository, marked whether main holds them), its gate rounds and the agents and
harnesses that worked on it. Filter by lane, harness, requirement, words, or only what waits on you.

## The Trace (Agents)

Every interaction as one timeline, newest first: people's decisions, Rihma's roles asking a model, builder
cells, gate rounds and merges, workspaces, MCP writes, the agent channel and hand-offs, outside sessions.
Each line says who (a person with their persona, Rihma in a role, an agent with its harness and operator),
what, and the task; **Details** opens the record itself (a ledger record without holdout details). Filter
by 24 hours, 7 or 30 days, who, harness or role, and task.

## Session hooks for Claude Code and Cursor

Below the timeline, the Trace gives three files to copy or download into the repository you work in:

| File | For | What it does |
|---|---|---|
| `.rihmasto/session_hook.py` | both | records a session's start and end in this project |
| `.claude/settings.json` | Claude Code | `SessionStart` and `SessionEnd` run the script (merge into an existing file) |
| `.cursor/hooks.json` | Cursor | `beforeSubmitPrompt` (the first prompt starts the session) and `stop` run it |

The hook records **metadata only**: the session id, the tool, the branch, the head commit and, at the end,
the commits and changed files since the start and the task ids the commits name. Never a prompt, a file's
content or the transcript. Each record is signed by the named person who operates the agent and is in the
ledger as `dev_session_recorded`. A hook that fails says so on its error output and never stops the agent.
Add `.rihmasto/` to the repository's `.gitignore`: the script names this computer's Rihmasto folder.
Rihmasto writes nothing into your repository itself.

## Ask Rihma and the command line

Ask Rihma answers, by rule, on a project's page:

- "What's next in development?": the next step and why, what blocks it, the latest sessions; Take me there
  opens the Board.
- "What did the agents do since yesterday?" (or today, this week, since my last look): the trace of that
  window counted by harness, with the newest; Take me there opens the Trace.

In a terminal: `rihmasto dev board <pid>`, `rihmasto dev brief <pid> --for "<your name>"`,
`rihmasto dev trace <pid> --window 24h --who agent`, `rihmasto dev hooks <pid> --operator "<your name>"`,
`rihmasto dev seen <pid> --person ... --persona developer`, and `rihmasto dev session` (what a hook records).
