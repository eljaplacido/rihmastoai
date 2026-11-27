# Run Rihmasto with the coding agent you already have

Rihmasto's text roles need a model: the **analyst** (intake, the spec, Shape it in chat), the
**holdout author**, the **verifier** and the **assistant** (Ask Rihma). Gnomon reaches models through an
API endpoint (an OpenAI-compatible server or Ollama). If you have no API key but you do have **Claude
Code** (your own login), **Codex** or **OpenCode** on this machine, Rihmasto can ask that coding agent
instead (FR-HMD1).

```bash
rihmasto models use claude-code --person "Your Name" --persona it
```

That one signed command answers every text role with the Claude Code on this machine. It is written to
this machine's `kernel/routing.local.json` and recorded in the factory's ledger. In the cockpit, the
same is **Use Claude Code (your login)** on Home's **Set up a model** card, or in **Models setup > Use
the coding agent you already have**, where you can pick the roles and the model.

## What it costs you

- **It is slower.** A coding agent starts once per call, so each answer takes seconds longer than an
  API endpoint. Intake asks several questions in a row, so expect intake to take a few minutes.
- **It spends your subscription.** Each call uses your own Claude, ChatGPT or OpenCode plan, as if you
  had typed the prompt yourself.
- **It is recorded honestly.** Each call is a `model_run` in the ledger (the project's when the call is
  for a project, else the factory's) with the role, the harness and its version, the model, the tokens
  and cost when the harness reports them, how long it took, and: *run by Claude Code, not through
  Gnomon's lane: no Gnomon audit trail for this call*. Gnomon's hash-chained audit trail covers the
  calls it makes itself; [a proposal for Gnomon](../upstream/gnomon-harness-provider.md) would let it
  cover these too.

## How each one is run

Every call starts in an **empty temporary folder**, never in the repository, a lane or the factory's
home. Its environment leaves out where the factory keeps its home, lanes and stored keys. The harness
gets the task as text and nothing else, and has no tools.

| Harness | How it is started |
|---|---|
| `claude-code` | `claude -p --output-format json --tools ""` with MCP servers off (`--strict-mcp-config`), no saved session, the role's rules as the whole system prompt (`--system-prompt`); the task on standard input |
| `codex` | `codex exec --json --sandbox read-only` with approvals `never`, in the empty folder; the task on standard input |
| `opencode` | `opencode run --format json --file <task>` with every tool switched off and edit, bash and web fetch denied (`OPENCODE_CONFIG_CONTENT`) |
| `command` | the command line you name (`--command`), with `{prompt_file}` and `{role}` filled in; the task also on standard input. If its last JSON line has `output` (and `usage`, `model`, `cost_usd`), that is read |

Codex's read-only sandbox lets its shell read files outside the empty folder. Its task says it has no
tools, but Rihmasto cannot switch Codex's shell off. If that matters to you, use Claude Code or OpenCode
for the text roles.

What each role is given:

- **The analyst, the assistant**: their task, as through Gnomon. A task for any role but the holdout
  author that quotes one of the project's holdout scenarios is refused before anything runs.
- **The holdout author**: the spec's criteria. It writes the scenarios, so it is the one role that may
  see them.
- **The verifier**: its review task and the change's diff (`git diff <base> -- app tests`), because it
  has no tools to read the repository. It never gets the repository, the contract or the holdouts.
- **The builder** never runs here. It writes code, so its harness is a **cell runner**, chosen by IT
  with its version pinned: `rihmasto runners set builder claude-code` ([Harnesses](harnesses.md)).

## Model families

The verifier must be another model family than the builder (FR-G6). Claude Code counts as `claude`
and Codex as `gpt`. OpenCode and a command run whatever model you set, so name it (`--model
anthropic/claude-sonnet-4`, which gives the family) or its family (`--family qwen`). If a harness's
output names a model, that model's family is recorded. A verifier that answers with the builder's
family gives no verdict: its signal is *not measured*.

A change that breaks the rule is refused when you make it. One example is Claude Code as the verifier
while the builder is a Claude model, or while the builder runs with the Claude Code runner.

## Confidential projects

A confidential project keeps its material on local models. Claude Code's and Codex's models are
hosted by their providers, so a confidential project refuses them like any hosted endpoint: nothing is
sent, and the refusal is in the ledger. Declaring them private is refused. An OpenCode (or a command)
that runs a model on this machine or your own network can be declared private:

```bash
rihmasto models use opencode --roles analyst --model ollama/qwen3:32b --private --person "Your Name" --persona it
```

## Checking it

- `rihmasto models list` and **Models setup** show each harness this machine has, with its version, and
  for each role the harness that answers it.
- **Test** on a role sends a tiny prompt through the harness and shows how long it took or the error,
  for example "not logged in". Test records nothing.
- `rihmasto doctor` lists the harnesses it finds. When a key is missing (or Gnomon is) and no role uses
  a harness yet, it suggests: *No API key? Claude Code found: use it.*
- **Back to shipped** on a role, or `rihmasto models remove <role>`, puts the role back on the routing
  it shipped with.

## Choosing roles

```bash
rihmasto models use claude-code --roles analyst,assistant --person "Your Name" --persona it
rihmasto models use codex --roles verifier --person "Your Name" --persona it
```

`--roles all`, the default, means the four text roles. `--model` passes a model to the harness (for
example `--model sonnet` for Claude Code). Without it, the harness uses the model it is set to use.
