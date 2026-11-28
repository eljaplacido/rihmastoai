# Agentic help: goals, hand-offs and the agent channel

Rihmasto should never leave you in the dark about what to do next with a project, and the coding agents
that develop it (Claude Code, Codex, OpenCode, Cursor, a script in a terminal) should see what Rihmasto
holds and report back to it. This guide covers three parts that work together:

- **Goal help**: say what you want in your own words, and Rihma answers with a plan you take one click at
  a time (FR-CPL1).
- **The agent bridge**: a hand-off brief for a coding agent, the MCP tools it reads Rihmasto with, and the
  writes it sends back, signed for you (FR-BRG1).
- **The agent channel**: one conversation per project between you, Rihma's own agents and the coding
  agents, which you watch and step into (FR-CHN1).

None of them decides anything for you. A plan only opens the place where you act; an agent's writes are
proposals and posts; a proposed answer becomes an answer only when a person confirms it.

## Ask Rihma for a goal

Open a project and ask Ask Rihma what you want, for example:

- "I want to hook this solution to Google Drive" (or "Haluan kytkeä tämän Google Driveen")
- "Run it every night in our cloud"
- "Deploy it to test", "Add sign-in", "Monitor it"
- "Give this to my coding agent"

Rihma recognises the goal and answers with a **plan** built from two things only:

1. **The project's records**: its stage, whether its contract is compiled, what it waits for, its posture,
   whether it is confidential, adopted or attached, the integrations it declared.
2. **What this Rihmasto can do, read from its code when you ask**: the paved roads IT configured and their
   environments, the connectors and whether IT enabled each, the data integration kinds, the outputs, and
   the checks, automation templates, cell runners and walkthroughs when this installation has them.

What it lacks is said plainly. For Google Drive the plan says there is no Google Drive connector yet and
lists the options: a REST integration against Drive's API, an MCP integration to a server your IT runs,
copying the files to storage Rihmasto reaches (Google Cloud Storage or S3), or asking for a connector.

Each step is one click:

| Step | What the click does |
| --- | --- |
| Draft a change request | Opens the change form prefilled with your goal and the questions it raises; you edit it and file it, signed with your name |
| Open, or open the settings | Takes you to the view or the settings where you do it (the Plan's integrations, Outputs, Health) |
| Add an automation | Opens Automations with a template, when this installation has automations |
| Start a walkthrough | Starts the matching walkthrough, when this installation has walkthroughs |
| Copy the command | Copies a plain `rihmasto ...` command, for example the one IT runs to enable a connector |
| Hand off | Opens the hand-off dialog for a coding agent (below) |

A step whose feature is not in this installation says "Not available yet" and why.

**Without a model** the goal is read by rule (English and Finnish), and the plan comes from the rules.
**With a model** for the assistant role, the model writes the plan from the same records and catalogue,
and every step it proposes is checked: an unknown kind, a route the cockpit does not have, a check or
template this installation lacks, or a command that is not one plain `rihmasto` command is not shown, and
the answer says why. A **confidential** project whose assistant model is hosted gets the rule-based plan,
and nothing about it is sent; set the assistant role to a local or private endpoint in Models setup
(Settings, Models) to let a model plan it.

From a terminal: `rihmasto goal <project> "hook this to Google Drive"` prints the same plan.

## Hand off to a coding agent

**Hand off to an agent** in a project's header gives a coding agent a brief with:

- the goal, or the change card you name, and the accepted contract's criteria relevant to it;
- the open questions and assumptions (people answer them; the agent may only propose);
- the plan and its tasks, the assessment's findings, review feedback, the gates that failed and the checks
  that fail, the alignment gaps and the insights that matter, when this installation has them;
- the project's conventions (its AGENTS.md and the commands it states), how to run the tests, and how to
  report back.

Choose the agent and the dialog shows how it takes the brief:

| Agent | How it runs | Rihma's tools |
| --- | --- | --- |
| Claude Code | `claude -p "$(cat .rihmasto/handoff-<project>.md)" --mcp-config .mcp.json` | `.mcp.json` |
| Codex | `codex exec "$(cat .rihmasto/handoff-<project>.md)"` | `~/.codex/config.toml` |
| OpenCode | `opencode run "$(cat .rihmasto/handoff-<project>.md)"` | `.mcp.json` |
| Cursor | attach the brief in Cursor's chat | `.cursor/mcp.json` |
| Any other | give it the brief as its task | `.mcp.json` |

**Copy** or **Download** records that you gave the hand-off (who, to which agent, and the brief's sha256,
never its text) on the project's timeline and in its agent channel. Rihmasto never writes into your
folder: save the brief and the MCP file yourself. When cell runners are in this installation and IT chose
one for the project, **Run it with <runner>** files the brief as a change; when a product owner accepts it,
the factory's own builder cell runs it with that runner, every rule checked after the run (D-0019).

From a terminal: `rihmasto handoff <project> [--change C-0004] [--to claude-code|codex|opencode|cursor|generic]`
prints the brief and the agent's way to use it.

## What agents read and write back

Rihma's MCP server ([docs/mcp.md](../mcp.md)) gives the agent these tools besides the existing ones:

| Reads | What they answer |
| --- | --- |
| `rihma_next` | what the project waits for, who can act, and the actions |
| `rihma_plan` | the spec in short, the contract's requirements with each criterion, the tasks |
| `rihma_questions` | the open questions and assumptions |
| `rihma_handoff` | the hand-off brief and how this agent takes it |
| `rihma_feedback` | review feedback, failed gates and checks, change cards, settled proposals and people's messages since a time |
| `rihma_insights`, `rihma_alignment`, `rihma_health` | key figures, alignment gaps and checks, when this installation has them |
| `rihma_channel_read` | the agent channel, since a message or a time, per thread |

| Writes | What they do |
| --- | --- |
| `rihma_progress` | posts what the agent did, the files it touched, the criteria it believes it addressed, a commit |
| `rihma_propose_answer` | suggests an answer to an open question: a proposal a person confirms or rejects |
| `rihma_request_gate` | asks the gate to check a commit of an attached repository (or an enabled check to run); the result posts itself into the channel. An adopted project's gate runs on `rihmasto workspace submit` |
| `rihma_channel_post` | posts in the agent channel; a question naming `@analyst` or `@verifier` is answered by a Rihma agent |
| `rihma_ask_rihma` | asks a Rihma agent: what a criterion means, why the gate failed, what is next |
| `rihma_report_change` | (as before) files a change card |

Every write is signed as the agent (its name, such as `claude-code`, and its harness) **for the server's
named operator**, recorded in the ledger, shown on the timeline, in the channel and in the **Agents working
on this** strip on the project's overview as "claude-code for Aino". None decides a card.

An agent without MCP posts from a terminal:
`rihmasto channel <project> post --as claude-code --kind progress --text "..." --person "<operator>" --persona developer`.

## The agent channel

Each project has an **Agent channel** tab: one threaded conversation (thread `main` unless named) where
every message has its author and kind:

- authors: a **person**, a **Rihma agent** in its role (analyst, verifier, assistant; the holdout author
  never posts), an **external agent** with its harness and operator, an **automation**, or the **system**
  (gate and check results it was asked for);
- kinds: question, answer, progress, feedback, plan, handoff, gate result, check result, proposal, note.

Every post is in the ledger as `channel_posted` with its ids, author and kind, never its text.

**Rihma's agents answer** a question addressed to them (`rihma_ask_rihma`, or `@analyst`, `@verifier`,
`@rihma` in a question):

- **from the records, by rule, where they can**: a criterion's given, when and then; the last gate's
  verdict, its failing signals and objections; what the project waits for and the tasks not yet merged;
  an open question's or assumption's status; the contract's requirements. The answer names its sources;
- **else through Gnomon** in the matching role: the verifier when the question points at a commit, the
  analyst otherwise. In the MCP server this is on with `RIHMA_AGENT_MODEL=gnomon`; in the cockpit, with the
  assistant's model. A confidential project uses only a local or private model; with a hosted one Rihma
  answers by rule or says it cannot, and how to fix it in Models setup.

**Loops are stopped.** Rihma answers at most six questions per thread an hour, and a question asked again
in a thread within the hour gets one pointer to the first answer, then silence. A note says each limit
once.

**Watching agents.** In the tab, or as a panel beside any view (**Agent channel** in the project's header),
the channel refreshes by itself every few seconds. Each message has a **Trace**: for a Rihma answer, the
rule and its sources, or the Gnomon run behind it (model, tokens, tool calls, how long it took); for an
agent's post, its commit, files and criteria; for a gate result, its signals and objections. Filter by
author or kind.

**Stepping in.** Post a message (name `@analyst` or `@verifier` to ask Rihma). **Confirm the answer** on an
agent's proposal answers its question with that text, signed with your name, through the Questions view's
own route; **Reject** keeps the question open. **Pause the channel** holds the agents: their posts wait,
hidden from other agents and unanswered, until a person resumes it.

**Across the factory**, **Agent activity** in the sidebar lists every project's channel: who is talking,
the last message, the posts held and the proposals waiting on a person.

From a terminal: `rihmasto channel <project> [--thread T] [--since M-0007] [--follow]` prints the channel
line by line; `--follow` keeps showing new messages until Ctrl+C.

### Asking a coding agent through Rihma

The channel's head says what to expect and who is connected (the coding agents that posted in it). With none,
**Connect a coding agent** opens an adopted project's IDE setup (or the hand-off) and the head lists the steps:
give the agent Rihmasto's MCP server (`rihmasto ide <project>` prints the configuration), add the session-start
hook `rihmasto ide <project> --section`, and tell it to read the channel.

Write "ask Claude Code ..." (or Cursor, Codex, "the agent"), or press **Ask a coding agent**. Rihma posts the
question addressed to that agent and answers you with what it did, how the agent sees it, and what the records
say now. The agent reads it in `rihma_channel_read` (under `asked_agents`) and in the section the hook prints
(under "Questions for you"), and answers with `rihma_channel_post` (kind `answer`, `reply_to` the question's id)
or `rihmasto channel <project> post --kind answer --reply-to M-0012`. Only a person's message makes Rihma ask
an agent. Ask Rihma does the same: its **Ask a coding agent in the agent channel** proposal posts your words.

Rihma's answers end with the next steps from the project's state as buttons: the card waiting on a decision,
the assessment not run yet, the watch not set up, the project's own sources to add as material. Asked how to
keep a project in step with Rihmasto and what to monitor, it answers by rule: upstream change cards follow
commits once the watch is set up, the project's own sources fed in as material, its checks, and the
automations to schedule. Records are quoted whole; when they do not all fit, fewer are quoted and the rest
are counted by id.

### Asking an agent on another machine

An agent the channel cannot reach (on a laptop, a build server) gets an **ask**: the same question in the channel,
with its state, delivered over MCP when the agent is here, through a one-use reply link, or copied for you to paste
there, and answered back into the same thread. Where a machine is not reachable, Test connection says why and drafts
the ask to its agent. See [Machines, asks between agents, and Test connection](machines-and-asks.md).

### How the channel holds up

- **Only a request asks an agent.** "Ask Claude Code ...", "Rihma, consult Cursor on ...", "Can you check with
  the agent whether ..." put the question to the agent. "What should I ask the agent?" or "Can I ask my agent
  to ...?" are questions to Rihma, answered as such. "Ask Claude Code" with nothing after it gets "What should
  I ask Claude Code?" and nothing is posted to the agent.
- **Long questions.** You may paste up to 8,000 characters (a log, a stack trace). Rihma's question to the
  agent quotes it shortened at a sentence and names your message, which holds it whole. If the channel ever
  refuses one of Rihma's posts, a short note says why, and the channel goes on.
- **Answered once.** The panel reads the channel every few seconds; a message is answered once even when that
  read comes while Rihma is still answering it.
- **The hourly cap is for agents.** At most 6 of Rihma's replies an hour answer agents in a thread, so two
  agents cannot keep each other going. Your own questions, and Rihma's questions to agents for you, never use
  it up. The same question twice within an hour gets a pointer to the first; Ask Rihma's Confirm says so.
- **Answering an agent's question.** Only a post with `reply_to` answers it; naming its id in a progress note
  does not. The question carries a reply command that runs as written, with the connected agent's operator
  already in it (for a question to any agent, the operator fills in their own name):
  `rihmasto channel <project> post --as <agent> --person "<operator>" --persona developer --kind answer
  --reply-to M-0012 --text "..."`.
- **Buttons that land.** Only the latest of Rihma's answers in a thread shows its buttons, one per decision,
  none for a card no longer open; the first is the step Ask Rihma's "what should I do next" gives. A button
  naming a control lands on it highlighted (Set up the watch), one about a question or a card opens it.
- **Syncing, briefly.** The sync answer is a few lines: the watch, the baseline (a command that measured
  nothing reads as tried, with **State the test command** opening Console settings), the project's own
  sources, its checks and the automations to schedule.

## What is recorded

| Event | Recorded as |
| --- | --- |
| A post in the channel | `channel_posted`: id, thread, kind, author kind, author, operator or person, persona |
| An agent's progress, proposal or gate request | `agent_progress`, `agent_proposed_answer`, `agent_gate_requested`, with the agent and its operator, plus `mcp_write` when it came over MCP |
| A hand-off a person gave | `agent_handoff`: to which agent, how, the change, the brief's sha256 |
| A proposal confirmed or rejected | `channel_settled`, and the answer as the Questions view records it |
| A pause or a resume | `channel_paused`, `channel_resumed` with the posts let through |
