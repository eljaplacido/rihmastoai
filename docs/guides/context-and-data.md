# Context and data: what Rihmasto knows, and what each agent reads

Rihmasto's agents (the intake panel, the analyst who writes the spec, the holdout author, the builder, the
verifier, Ask Rihma) each read a prompt the kernel builds from the project's records. This guide shows where to
see that: what Rihmasto knows about a project, what every agent is given right now, how large it is, what was
compressed or left out and why, and what the factory keeps on disk (FR-CTX1, decision D-0024 item 2).

Nothing on these pages asks a model or writes a record, except a clean-up a person proposes and applies.

## The Context view of a project

Open a project and choose **Context** (`#/p/<project>/context`). It has three parts.

**What Rihmasto knows**, the context map (`kernel/context_map.py`):

- **Sources**: the request (its kind, its length, whether it was cut), the folder's material map (how many files
  were read, summarised, listed or skipped, and how many may hold secrets and were never read), the adopted or
  attached repository and its main revision, the project's own conventions for its AI tools (CLAUDE.md,
  AGENTS.md, Cursor rules, skills), and the alignment with the repository's own specs and tests. Each says when
  it was last updated, from the ledger.
- **Records**: the questions and assumptions by status, overdue assumptions, decisions and stale decisions, open
  cards, the ledger's records and bytes with its hash chain verified now, the knowledge graph's nodes, edges and
  contradictions, the spec with its superseded versions, the contract's revision and tasks, and the model runs per
  role.
- **Freshness**: a record written before something it rests on changed is **stale**, with why. The spec is
  stale when a question or assumption was settled after it; the contract when the spec changed after it was
  compiled; a folder's material or conventions when they were not read again for 30 days.
- **Kept on disk**: the project's stores in bytes, and the holdout custody's size (never its content).

**What each agent is given**: one row per context pack, with its size in estimated tokens against its budget,
and how much of each call a prompt cache can reuse. **Open** shows the pack part by part:

| Pack | Who reads it | Built by |
|---|---|---|
| Intake panel | the analyst, as one perspective (`--target business` and so on) | `kernel/intake.py perspective_prompt` |
| Spec | the analyst | `kernel/spec.py spec_prompt` |
| Holdout author | the holdout author | `kernel/compile.py holdout_prompt` |
| Builder envelope | the builder, for one task (`--target T-002`) | `kernel/dispatch.py envelope` |
| Verifier | the verifier, for one task | `kernel/gate.py verifier_prompt` |
| Ask Rihma | the assistant, for your persona and a question | `kernel/assistant.py prompt` |
| Goal help | the assistant, for a goal | `kernel/copilot.py prompt` |
| Agent channel answer | a Rihma agent answering a coding agent | `kernel/channel_rihma.py` |
| Hand-off brief | a coding agent you hand the project to | `kernel/agent_bridge.py render` |
| MCP tools | a coding agent connected over MCP: the tool list and each tool's answer | `mcp/server.py` |

Each pack is the prompt the real code path sends next, built by the same function: the tests capture what the
code sends with a scripted model and compare (tests/test_context.py). Each part names its source, its size in
characters and estimated tokens (characters / 4), and how stable it is: **static** (the same in every call of
the role), **project** (the same for this project until its records change) or **call** (different each call).
The lane's system prompt is shown first, as the model reads it.

Every pack lists what it **leaves out, and why**: the holdout scenarios (in their custody), secret values (a
prompt names a secret's setting, never its value), other projects' cards, decision reasons, and what each role
does not need. What was **compressed** is named too: a request cut at the panel's budget, a folder's files
summarised, a snapshot fitted to its budget by whole items.

**Who sees the content.** Every persona sees a pack's parts, sources and sizes. The content of the holdout
author's pack (the criteria a holdout checks, judged out of the builder's sight) is shown to compliance and IT
only. Anything of the holdout custody is replaced wherever content is shown.

**Compression findings**: what the audit below found in this project's packs, each with a proposed compression.

## The compression audit

`rihmasto context audit [<project>]`, and the findings in the Context view (`kernel/context_audit.py`), measure
every pack, every MCP tool's answer and the JSON of the commands an agent may read against the prompt economy:

- **over budget**: a pack over its role's budget, which is the prompt economy's for the role (for example 8,000
  tokens for Ask Rihma: the snapshot's 3,000 and the catalogue) or a quarter of the role's context window
  (`max_context_tokens` in the routing), whichever is smaller;
- **said twice**: a line of 80 characters or more carried twice in one pack;
- **stable prefix**: a part that changes more often placed before parts that change less, which defeats prompt
  caching for everything after it;
- **oversized output**: an MCP answer or command output over 2,000 tokens;
- **conventions sent where they are not needed**: the project's own conventions in a pack other than the
  panel's, the builder's or a coding agent's brief.

Each finding proposes a compression: a summary, a reference instead of the full text, or a shared prefix.

### What was compressed (FR-CTX1)

Measured on the same built project before and after; "shared" is the share of a call, with the lane's system
prompt, that is the same in every project, which a prompt cache reuses:

| What | Before | After |
|---|---:|---:|
| Ask Rihma's prompt (the catalogue names each control by id and label; the entries that match the question carry where they are and what they do) | 43,008 characters | 18,652 characters |
| MCP tools' read answers, all together (compact JSON, the hand-off brief once) | 25,798 characters | 15,569 characters |
| The hand-off tool's answer | 9,463 characters | 4,338 characters |
| The spec's prompt, shared (instructions first, the brief last) | 12% | 75% |
| The holdout author's prompt, shared | 20% | 62% |
| The verifier's prompt, shared | 80% | 92% |
| Goal help's prompt, shared (and its rule-based steps fitted by whole steps, never sliced) | 25% | 62% |

Still open, and flagged by the audit: the builder's envelope starts with the task and its base revision, so the
static rules after them are not a shared prefix. The envelope's first line is read by other runners, so moving
it is a change for the owner's review.

## The Data and context page

**Data and context** in the sidebar (`#/data`, `rihmasto data`, `kernel/data_stores.py`) is factory-wide:

- **Context health**: per agent role, the average and largest pack, the budget, how many are over it, and the
  share a prompt cache reuses; what was compressed; the findings across every project.
- **Stores**: every folder and file of the factory home, named, with bytes and files and how long it is kept,
  and the lanes folder outside the home.
- **Ledgers**: every project's ledger, Rihma's own and the relay's, each hash chain verified now; a broken one is
  named.
- **Clean-up**: what can go safely, by rule: job logs and snapshots of adopted folders no project names, older
  than 30 days. Ledgers, the canon, specs, contracts, releases and the holdout custody are never cleaned.

A clean-up is two signed steps, for the IT or operations persona:

```
rihmasto data cleanup --person "Ilkka" --persona it
rihmasto data apply CU-0001 --person "Ilkka" --persona it
```

The proposal lists each item with its size and time and is recorded in Rihma's own ledger
(`data_cleanup_proposed`). Applying it removes only the items unchanged since, keeps the rest with why, and
records what was removed (`data_cleanup_applied`). In the cockpit: **Propose a clean-up** and **Apply**.

## Ask Rihma

Ask in a project, in your words:

- "What does the verifier get for T-003?", "What is the builder given?", "What context does Ask Rihma have?":
  the pack's size against its budget, its largest parts, what was compressed and left out, and Take me there to
  the Context view;
- "Why didn't Rihma know about the night shift?": whether those words are in an agent's pack, only in the
  project's records (and what was cut), or nowhere in the records, so no agent could know them.

## On the command line

```
rihmasto context map <project>
rihmasto context packs <project> [--persona developer]
rihmasto context pack <project> verifier --target T-002 [--persona compliance]
rihmasto context pack <project> assistant --question "What waits on me?"
rihmasto context audit [<project>] [--no-commands]
rihmasto data
```

Each prints JSON from the same kernel functions the cockpit reads.
