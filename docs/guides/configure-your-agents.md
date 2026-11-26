# Configure Rihmasto with your agents

You keep working in your own IDE with your own coding agent: Claude Code, Cursor, Codex, OpenCode or
another. Rihmasto sits beside it as the outer loop: the contract, the decisions, the gate and the
record. This guide connects the two, agent by agent, through MCP, your conventions file and, if you
like, your agent's hooks.

Rihmasto never writes into your folder or repository. Every snippet below is something you paste
yourself, so you can read it first and take it out again.

## The six ways an agent works with Rihmasto

| Way | What your agent gets | What it may do | Set up with |
|---|---|---|---|
| **MCP server** | the contract, what waits on a decision, health, evidence, the assessment | read, and file proposals (a change, a comment, a signal); never decide | `rihmasto ide <pid>`, below |
| **Conventions file** | a section in AGENTS.md or CLAUDE.md: the contract, open questions, how a change comes back | follow it | `rihmasto ide <pid> --section` |
| **Hooks** (optional) | the same section at the start of each session; a note in the agent channel when it ends | nothing beyond the commands you name | [Hooks](#hooks-optional) |
| **Hand-off** | a brief: the goal or change, the criteria, the conventions, how to report back | work on it, report in the agent channel | `rihmasto handoff <pid> --to claude-code` |
| **Your agent as Rihmasto's model** | Rihma's text roles (analyst, holdout author, verifier, assistant), headless, with no tools | answer prompts on your own login | `rihmasto models use claude-code ...` ([guide](harness-models.md)) |
| **Your agent as a cell runner** | a builder task in a cell, approved by IT, its version pinned | build; the rules are checked after the run | [harnesses](harnesses.md) |

The first three are for your day-to-day work. The last two make your agent part of Rihmasto's own
chain and are set up once.

## Before you start

1. Install Rihmasto and know your factory home ([getting started](../getting-started.md)). The MCP
   server reads the home directly, so it runs on the machine that holds it.
2. Have a project: adopted, attached or started in Rihmasto ([scenarios](../scenarios/README.md)).
3. Print your configuration, filled in for this machine:

   ```bash
   rihmasto ide <pid> --name "Ada Example"
   ```

   It shows the project's AI-tool setup as committed, ready-to-paste MCP configuration for Claude Code,
   Cursor and Codex, and how your change comes back. The cockpit's **Work on it from your IDE** card on
   the project's Overview shows the same.

The server signs every proposal with the person and persona it was started with. A name such as
"claude" or "assistant" is refused: an agent acts for a named person, never as one.

## Claude Code

**MCP.** A project-scoped `.mcp.json` at the root of your repository:

```json
{
  "mcpServers": {
    "rihma": {
      "type": "stdio",
      "command": "python",
      "args": ["<path to rihmasto>/mcp/server.py", "--home", "<factory home>",
               "--person", "<your name>", "--persona", "developer"]
    }
  }
}
```

Or from the command line: `claude mcp add rihma -- python <path to rihmasto>/mcp/server.py --home
<factory home> --person "<your name>" --persona developer`.

**Conventions.** Paste the output of `rihmasto ide <pid> --section` into CLAUDE.md, between its
`<!-- rihmasto:begin <pid> -->` and `<!-- rihmasto:end <pid> -->` markers, so you can replace it later.

**Hooks.** See [Hooks](#hooks-optional) for a `.claude/settings.json` that loads the section at the
start of each session and notes the end of a session in the agent channel.

## Cursor

**MCP.** `.cursor/mcp.json` in the repository takes the same shape without `"type"`:

```json
{
  "mcpServers": {
    "rihma": {
      "command": "python",
      "args": ["<path to rihmasto>/mcp/server.py", "--home", "<factory home>",
               "--person", "<your name>", "--persona", "developer"]
    }
  }
}
```

**Conventions.** Paste the section into AGENTS.md, or into a project rule under `.cursor/rules/`.

## Codex

**MCP.** Codex reads MCP servers from `~/.codex/config.toml`:

```toml
[mcp_servers.rihma]
command = "python"
args = ["<path to rihmasto>/mcp/server.py", "--home", "<factory home>", "--person", "<your name>", "--persona", "developer"]
```

**Conventions.** Codex reads AGENTS.md: paste the section there.

## OpenCode

**MCP.** OpenCode reads local MCP servers from `opencode.json` in the repository:

```json
{
  "mcp": {
    "rihma": {
      "type": "local",
      "command": ["python", "<path to rihmasto>/mcp/server.py", "--home", "<factory home>",
                  "--person", "<your name>", "--persona", "developer"],
      "enabled": true
    }
  }
}
```

**Conventions.** OpenCode reads AGENTS.md: paste the section there.

Check the shape against your tool's current documentation if it does not load: these tools change their
configuration formats from time to time. The command and arguments stay the same.

## Hooks (optional)

Hooks let your agent run a command at points in its own life-cycle. Two are useful with Rihmasto:

- **At session start**, print the project's current section, so the agent starts from the contract as it
  is now, not as it was when you pasted it.
- **At session end**, post a note to the project's agent channel, so the record shows the session.

For Claude Code, in `.claude/settings.json` (Claude Code adds what a session-start hook prints to the
session's context):

```json
{
  "hooks": {
    "SessionStart": [
      {"hooks": [{"type": "command", "command": "rihmasto ide <pid> --section"}]}
    ],
    "SessionEnd": [
      {"hooks": [{"type": "command",
                  "command": "rihmasto channel <pid> post --as claude-code --kind note --text \"Session ended\" --person \"<your name>\" --persona developer"}]}
    ]
  }
}
```

- The hook runs in your shell, so `rihmasto` must be on its PATH and `RIHMASTO_HOME` set (or add
  `--home <factory home>` after `rihmasto`).
- Cursor and OpenCode have hook or plugin mechanisms of their own; the same two commands work from them.
- **Agent observability** is a separate, optional module: an observability hub your team runs itself
  installs its own hooks into a repository and records session metadata (never prompts or code), which
  Rihmasto's **Agent sessions** view reads ([agent observability](agent-observability.md)).

## How your agent's work comes back

| The project is | Your agent works in | The change comes back by |
|---|---|---|
| **adopted** | a workspace: `rihmasto workspace open <pid> --agent claude --person "<your name>" --persona developer` clones main onto your own branch, with the MCP server already set up | `rihmasto workspace submit <pid> <folder> --person ... --persona developer [--task T-003]`: the same gate a builder cell meets; warranted, it merges |
| **attached** | your own repository, as always | you commit; `rihmasto repo gate <pid> --head <commit> ...` judges it; you merge |
| **started in Rihmasto** | a workspace, as for adopted | the same submit and gate |

A new requirement is a decision: your agent files it as a change (`rihma_report_change`) before it is
built, and a person decides it in the Inbox.

## What happens under the hood

- The MCP server (`mcp/server.py`) speaks JSON-RPC over stdio, started by your agent as a child process.
  It wraps the same read models as the cockpit; each write is a proposal, signed with the server's
  person and persona and noted in the ledger as `mcp_write`.
- `rihmasto ide` reads the project's AI-tool setup from its committed revision (CLAUDE.md, AGENTS.md,
  Cursor rules, skills, MCP servers, hooks and permission rules) and records what it found; it writes
  nothing.
- A hand-off brief and the agent channel are records too: the channel's messages are kept per project,
  traced to the criteria and commits they name.
- With access enforced, the MCP server signs as the operating-system user that starts it, which IT's
  access file must name ([access](access.md)).

## When it does not work

| You see | Do this |
|---|---|
| The server exits at once with code 2 | the name is not a person ("claude" is refused) or the persona is unknown; the line on stderr says which |
| "refused: the factory home ... does not exist" | pass `--home` with the full path of the home the cockpit and `rihmasto status` use; the server never creates one |
| The tools list is empty | the agent did not start the server: check the command and path in its MCP log; run the same command in a terminal to see its error |
| A proposal is refused | read the refusal: it names the persona needed or the rule; with access enforced, the persona must be granted on that project |
| The section is out of date | run `rihmasto ide <pid> --section` again, or use the session-start hook |

## Read next

- [MCP](../mcp.md): every tool and resource, and the safety boundary.
- [Your IDE and Rihmasto](ide-and-rihmasto.md): where the line is between the inner and outer loop.
- [Agentic help](agentic-help.md): goals, hand-offs and the agent channel.
