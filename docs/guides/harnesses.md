# Harnesses: who runs the factory's cells

Rihmasto builds every task in a **cell**: a builder writes the change and its tests in a working copy,
and an independent verifier on another model family tries to break it. By default both run in
[Gnomon](https://github.com/eljaplacido/gnomonharness), the factory's own harness. A team that has
standardised on another coding agent can run the cells with it instead (D-0019). Gnomon is then the
governance glue around that harness rather than the harness itself: the same rules apply, and the
evidence says how they were applied.

This guide says what each assurance level means, how to choose a runner, and how to add one of your
own.

## The runners

| Runner | How it is started | Assurance |
|---|---|---|
| `gnomon` (default) | `gnomon task --role <role> --json` in the lane | in-run policy enforced by Gnomon |
| `claude-code` | `claude -p --output-format stream-json --verbose --permission-mode dontAsk`, tools Read, Glob, Grep, Edit, Write and Bash for a builder (read tools and `git diff/log/show` for a verifier), web tools disallowed; the task on standard input | checked after the run |
| `codex` | `codex exec --json --sandbox workspace-write` (`read-only` for a verifier), approvals `never`; the task on standard input | checked after the run |
| `opencode` | `opencode run --format json --auto --file <task>`, edits denied to a verifier and the web to both through `OPENCODE_CONFIG_CONTENT` | checked after the run |
| `command` | the command line you name, with `{prompt_file}`, `{workdir}` and `{role}` filled in; the task also on standard input | checked after the run |

Every harness runs in the working copy, never through a shell. Its task is the factory's envelope
for the task, then what is checked after the run (the write scope, the protected paths, the criteria
whose tests must fail first), then the project's own conventions when the working copy has them
(`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `CONVENTIONS.md`, `.rules`, `.cursorrules`, Copilot, Windsurf
and Cline instructions, Cursor rules and the Markdown files in `.claude/rules/`). They are recognised
and matched as a Gnomon builder's envelope matches them (`kernel/agent_context_use.py`,
[your IDE and Rihmasto](ide-and-rihmasto.md)): the instructions that apply to the files the task may
write, in full, a rule that applies when relevant by its description, and never a rule whose globs
match only other files. A verifier, which writes nothing, gets those that apply anywhere. An adopted
project's envelope already holds that section, so it is not given twice.
Its environment leaves out where the factory keeps its home, its lanes and its stored keys.

## What each assurance level means

**In-run policy enforced by Gnomon.** Gnomon holds the cell to its task while it runs: a write
outside the task's write scope is refused when it is attempted, the protected paths (the contract,
the specs, `.gnomon/`, the paved road's own files) cannot be written, the shell's deny-list applies,
and every tool call is in a hash-chained audit trail that Rihmasto checks and keeps (`gnomon_run` in
the ledger). The gate then checks the result as well.

**Checked after the run.** Another harness has its own permission model, but Rihmasto does not
enforce anything inside it. What it did is read from its own output (its tool calls, when it shows
them), and every rule is checked after it finishes, at the revision the gate judges:

- **write scope**: every path the change touches is inside the task's write scope;
- **protected**: no protected path is touched (the verifier does not run when one is);
- **custody**: the working copy holds nothing from the holdout custody;
- **tests, trace and fail-first**: the whole suite passes, each criterion is named by a test that ran,
  and each criterion's tests fail at the base revision;
- **verifier**: an independent reviewer on another model family finds nothing high and in scope;
- **holdouts**: the scenarios no runner ever sees run at acceptance, as for every change.

A change that fails any of them never merges, whatever the harness reported. After its repair
rounds it escalates to a person like any other task.

The difference matters for an auditor: with Gnomon, a forbidden write never happened; after the run,
a forbidden write happened in a working copy and was refused before it reached main. The ledger, the
evidence pack (`cell-runners.json` and its README line) and the cockpit say which applied to every
round, and a round another harness ran is never shown as Gnomon-level assurance.

### Holdouts

No runner, Gnomon included, ever gets the holdout scenarios: they stay in their custody under the
factory home, outside every working copy, and nothing in the task or the environment points at it.
On the host, a harness with a shell can read whatever the account that runs it can read, as Gnomon's
own shell can. To make the custody unreachable, run cells with access enforced (IT's isolation
account cannot read the factory home; see [access](access.md)) or in the docker sandbox below.

## Choosing a runner

A runner is chosen per role (the builder and the verifier may differ) for the factory, or for one
project, which then wins over the factory's choice. The verifier must stay another model family than
the builder, whichever runners they use: a choice that breaks this is refused.

From the cockpit, open **Settings > Runners**:

1. **Check** looks for each runner on this machine and asks its version, and says whether Docker
   answers.
2. **Choose a runner** names the role, the runner, the factory or a project, the version to pin (by
   default the one found here), the model and its family, and the sandbox.
3. Going back to Gnomon applies at once. Any other runner opens a **Cell runner** card in the
   factory's Inbox that only IT decides; it applies from IT's approval, with that version pinned.

A project's **Project settings** shows what runs its builder and verifier, with their assurance, and
links to the page.

From the command line:

```bash
rihmasto runners check                     # each runner here, its version, and Docker
rihmasto runners set builder claude-code --reason "our standard harness" --person "Dana" --persona developer
rihmasto decide _factory C-0001 approve --person "Ilkka" --persona it
rihmasto runners set verifier codex --project equipment-loans --person "Ilkka" --persona it
rihmasto runners list                      # what runs each role, and every choice
```

A runner's command is found as `$RIHMASTO_RUNNER_<NAME>` (for example `RIHMASTO_RUNNER_CLAUDE_CODE`,
as a JSON list of words or a line split as a POSIX shell would), else on `PATH`. A runner that is
not found says so and what to do.

### When a run does not happen

Before any round, a task does not run, and the ledger says why (`runner_refused`), when:

- the runner is not found on this machine;
- its version is not the one IT pinned (IT approves the new version with a new choice);
- the choice asks for the docker sandbox and Docker does not answer here;
- the builder and the verifier are of the same model family.

The task stays pending until IT or the machine changes.

## The docker sandbox

With `--sandbox docker --image <image>`, a harness other than Gnomon runs in a container of an image
that holds it. Only the working copy is mounted, every capability is dropped and no new privileges
are taken. Its key variables are passed by name, never written on the command line. When the harness
needs its model endpoint (by default `api.anthropic.com:443` for Claude Code and `api.openai.com:443`
for Codex; name others with `--endpoint HOST:PORT`), the container joins an internal network whose
one way out is a small proxy that opens a tunnel only to that endpoint and refuses everything else;
otherwise it has no network. When Docker does not answer, the run does not happen: it never falls
back to the host. Gnomon's own `[sandbox] exec` governs Gnomon's shell only, so it does not apply to
another harness.

**Confidential projects.** A confidential project's roles stay on local models, whichever runner
runs them ([local models](local-models.md)). A role Gnomon runs is checked by its routing, as before.
A role another harness runs is refused like a role routed to a hosted model (`confidential_refused`,
nothing run, nothing sent) unless it runs in the docker sandbox and every endpoint it may reach is on
this machine or a private network (`--endpoint localhost:11434`, for example): outside the sandbox
nothing holds a harness to the endpoint it was told, and Claude Code and Codex reach their own hosted
endpoints by default.

## Adding a command runner

Any coding agent that can run headless can be a runner. Name its command line with `{prompt_file}`
where the task file goes:

```bash
rihmasto runners set builder command \
  --command "my-agent run --task {prompt_file} --cwd {workdir} --as {role}" \
  --family mistral --reason "the platform team's agent" --person "Dana" --persona developer
```

- `{prompt_file}` is the task file (under `.factory-tasks/` in the working copy, never committed),
  `{workdir}` the working copy, `{role}` `builder` or `verifier`. The task is also on standard input.
- The agent works in the working copy and exits 0 when it is done; another exit is a failure of the
  harness, not a verdict on the work, and is retried as Gnomon's would be.
- A line of its output that is a JSON object with a `tool` (and a `target`) is read as a tool call;
  the rest is its answer. A verifier answers with the findings JSON its task asks for.
- Its version is its first word's `--version`, with the digest of the whole line: a changed line is
  a new version, which IT approves again.

## Where it is recorded

- `runners.json` in the factory's own project: every choice, who made it and why.
- The factory's ledger: `runner_proposed`, `runner_chosen`, and IT's `decision` on the card.
- A project's ledger: each round's `cell_ran` names its runner, version and assurance; `runner_ran`
  keeps a harness's tool calls, what it changed, the diff's digest and its timings; `runner_refused`
  says why a task did not run.
- The evidence pack: `cell-runners.json`, and a line in its README.
