# Your IDE and Rihmasto: where the line is

Many teams already work with an AI agent at their side, in Cursor, Claude Code, Copilot, Windsurf,
Cline, Gemini or Codex. Their repositories hold the conventions those agents follow: a `CLAUDE.md`
or `AGENTS.md` with the build and test commands, Cursor rules, skills, slash commands, hooks and MCP
servers. Rihmasto reads all of it, follows the same conventions, and gives the IDE a way back in
(FR-AGC1).

| | Status |
|---|---|
| Recognising every AI tool file by rule, with its frontmatter, in a folder or a commit | Built |
| The conventions read right after the README, in a group of their own in the material map | Built |
| Intake's and the assessment's panels told the conventions | Built |
| Adoption's baseline running the test command the team states | Built |
| A builder cell's envelope carrying the rules that apply to the files it may write | Built |
| The project page's **AI tools in this project** and **Work on it from your IDE** cards | Built |
| `rihmasto ide <pid>`: MCP configuration, how a change comes back, the section for AGENTS.md | Built |
| Offering a team's skill or MCP server to Rihmasto's own cells, after a person approves | Not built: listed as candidates only |

## Where the line is

**The IDE and the terminal are the inner loop.** One developer, hands on, fast: write, run, debug,
with an agent at their side. Nothing about that changes.

**Rihmasto is the outer loop.** What is built and why, who decided it, the contract, independent
verification, delivery and evidence, the change loop, and the many parties a real system has: a
business owner, IT, operations, compliance, end users.

They meet in three places:

1. **The repository.** Rihmasto reads the team's conventions from it, and gates the team's changes
   to it: a workspace's submission on an adopted project, `rihmasto repo gate` on an attached one
   ([brownfield.md](../brownfield.md)).
2. **The MCP server.** The IDE's agent reaches Rihmasto's own MCP server ([mcp.md](../mcp.md)): it
   sees the contract, the evidence and what waits on a decision, and can file a change or a comment.
   It decides nothing: people decide in the cockpit.
3. **The conventions file.** Rihmasto gives you a section, "Rihmasto's contract and open questions
   for your IDE agent", that you paste into your project's `AGENTS.md` or `CLAUDE.md` yourself.

Rihmasto never writes into your folder or your repository. It prints; you paste.

## What Rihmasto reads

[kernel/agent_context.py](../../kernel/agent_context.py) recognises these by their paths, with no
model, at any level of the folder:

| Kind | Files | What it keeps |
|---|---|---|
| Project instructions | `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules`, `.cursor/rules/*.mdc`, `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`, `.windsurfrules`, `.windsurf/rules/*.md`, `.clinerules` | the text; a rule's description, globs and alwaysApply (Copilot's applyTo); where it applies: the whole project, a folder (`web/CLAUDE.md` speaks for `web/`), the files its globs match, or when relevant |
| Skills | `.claude/skills/<name>/SKILL.md` | its name and description, and the files bundled with it, listed, never read or run |
| Subagents | `.claude/agents/*.md` | name, description, tools |
| Slash commands | `.claude/commands/**`, `.cursor/commands/**` | `/name` and its description |
| Hooks and permissions | `.claude/settings.json` | the hook events and matchers, the allow, ask and deny rule names; never a hook's command, an environment value, or a rule that looks like it holds a secret |
| MCP servers | `.mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json` | each server's name, transport, and its command's name or its URL's host; never its arguments, environment values or headers |
| Personal settings | `.claude/settings.local.json`, `CLAUDE.local.md` | listed, never read: they are one person's, not the project's |

From the instructions it also takes the **commands they state**: a line of a code block or a code
span that starts like a command (`pytest`, `npm run build`, `ruff check .`), as test, lint, build or
run, with its file and line.

**Nothing found is ever run**: not a hook, a slash command, a skill's script or an MCP server. A
file whose text holds a credential is not read, by the same rules as every scanned file
([inputs.md](inputs.md#any-folder-the-material-map)).

## What Rihmasto does with it

- **The material map** reads the README first, then the project's instructions (`CLAUDE.md` and
  `AGENTS.md` before the rest), then its skills, subagents, commands, hooks and MCP servers, then
  briefs, plans and the rest. A big folder keeps its conventions within the budget. The map shows
  them in a group of their own, **How AI tools here are set up**; `rihmasto scan` prints the same.
- **Intake's panel** is told the project's own conventions and the commands they state, so it does
  not ask what they settle. So is **the assessment's panel**, which also does not propose a
  convention as a finding unless the code breaks it.
- **The baseline.** Adoption runs the test command the team states when it is one the kernel runs as
  it runs a detected suite (pytest, unittest, `npm test`, `go test`, `cargo test`, Maven, Gradle,
  `make test`, `dotnet test`) and its words are plain arguments; otherwise the command found by rule.
  Shell syntax (`&&`, `|`, `;`, `$`, redirection) is never run. The inventory says which command was
  used and why another was not; the brief names where it came from.
- **The builder.** A builder cell on an adopted project gets, in its envelope, the instructions that
  apply to the files its task may write: the whole project's, a folder's for that folder, a rule's
  whose globs match (a Cursor rule for `web/**/*.ts` reaches a task on the web pages, not one on the
  Python service). Rules that apply "when relevant" are named with their description. Where a
  convention differs from the envelope's scope or rules, the envelope wins.
- **Candidates, not more.** Skills and MCP servers found are listed as candidates for Rihmasto's own
  catalogue: they can be offered to Rihmasto's cells after a person approves. Nothing is enabled.

## In the cockpit

An adopted or attached project's **Overview** has two cards:

- **AI tools in this project**: every file above, grouped, each with where it is, for which tool and
  what it applies to, and the commands the instructions state. It is read from the committed
  revision (an adopted project's `main`, an attached repository's branch), never a working tree.
- **Work on it from your IDE**: ready-to-paste configuration for Claude Code (`.mcp.json`, or the
  `claude mcp add` line), Cursor (`.cursor/mcp.json`) and Codex, pointing at Rihmasto's MCP server on
  this machine with your name and persona; how your change comes back; and the section for your
  `AGENTS.md` or `CLAUDE.md`, with **Copy the section** and **Download it**.

Ask Rihma "how do I use this from Cursor" or "where are my Claude skills" to be taken there.

## From the terminal

```bash
rihmasto ide <pid> --name "Aino Virtanen"          # its AI tools, MCP config, how a change comes back
rihmasto ide <pid> --json                           # the same as JSON
rihmasto ide <pid> --section > rihmasto-section.md  # the section, to paste into AGENTS.md yourself
```

`rihmasto ide` prints and records nothing. The section sits between
`<!-- rihmasto:begin <pid> -->` and `<!-- rihmasto:end <pid> -->`, so a newer copy replaces it.

## How your change comes back

- **An adopted project.** `rihmasto workspace open <pid> --agent claude` clones `main` onto your
  own branch with Rihmasto's MCP server set up in its `.mcp.json`; open that folder in your IDE.
  `rihmasto workspace submit <pid> <folder>` sends your commits through the gate a builder cell
  meets. A change pushed to the upstream instead is seen by `rihmasto sync <pid>`, which opens an
  "Upstream changed: review" card.
- **An attached repository.** Commit as you always do. `rihmasto repo gate <pid> --head <revision>`
  judges the commit against the contract in a temporary clone; uncommitted changes are never judged.
- **A new requirement** is a decision: file it with `rihma_report_change` from your IDE, or in the
  cockpit, before you build it.

To hand a goal to your coding agent with a brief, let it post progress and proposals back over MCP,
and follow it in the project's agent channel, see [Agentic help](agentic-help.md) (`rihmasto goal`,
`rihmasto handoff`, `rihmasto channel`). When the repository was aligned, the section above also carries
the requirements accepted from it and the open gaps.

## Tutorial: an attached repository, from Cursor (10 minutes)

1. `rihmasto repo attach "Loan desk" --repo ~/work/loan-desk --person "Aino Virtanen" --persona developer`.
2. Open the project's Overview: **AI tools in this project** lists your `CLAUDE.md`, Cursor rules
   and skills. Check what applies where.
3. In **Work on it from your IDE**, open **Cursor** and copy the configuration into
   `.cursor/mcp.json` of your clone. Restart Cursor's MCP servers; ask its agent "what waits on a
   decision in this project?".
4. **Copy the section** and paste it at the end of your `AGENTS.md`. Commit it if the team wants it.
5. Make a change, commit it, then `rihmasto repo gate <pid> --head HEAD --person "Aino Virtanen"
   --persona developer`.

## Know before you rely on it

- Recognition is by path and a small frontmatter reader: a rule format a tool adds later is not
  recognised until the kernel names it.
- A stated command is found only in a code block or a code span; one written as plain prose is not.
- The builder's envelope carries the instructions of an adopted project only: an attached repository
  has no builder cells.
- Personal settings that were committed by mistake are listed and still never read.
