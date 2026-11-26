# A harness provider for Gnomon (proposal)

*A design note and patch proposal for Gnomon. It is not built in Gnomon. Rihmasto works around the gap
today (FR-HMD1, [Run Rihmasto with the coding agent you already have](../guides/harness-models.md)),
and this note proposes closing it in Gnomon itself. It is written for the owner to take to the Gnomon
repository as a pull request.*

## The gap

Gnomon reaches a model through an endpoint, and an endpoint has two request shapes:
`EndpointKind = "ollama" | "openai"` (`packages/gnomon-core/src/config.ts`). The config check refuses
any other `kind` as fatal ("is not a request shape the harness knows"). A person whose only model
access is a coding agent's login cannot point a Gnomon role at it. That covers Claude Code with a
Claude subscription, Codex with a ChatGPT plan, and OpenCode with its own providers.

Rihmasto now runs such a role itself. It spawns the agent headless with no tools in an empty folder,
then records a `model_run` in its own ledger that says honestly: *run by Claude Code, not through
Gnomon's lane: no Gnomon audit trail for this call*. That is the gap this proposal closes. The call
happens, but Gnomon's hash-chained audit trail, its surface hash and its degradation records never
see it.

## The proposal

Two modes behind one new endpoint kind, `harness`.

### 1. `kind = "harness"`: a coding agent as a toolless request shape

```toml
[endpoints.claude]
kind = "harness"
harness = "claude-code"        # claude-code | codex | opencode | command
# command = ["my-agent", "--json", "{prompt_file}"]   # harness = "command" only
# model = "sonnet"            # optional: passed to the agent's own --model

[roles.analyst]
model = "claude-code-default"
endpoint = "claude"
tools = []                     # required: a harness endpoint serves toolless roles only
```

A role on a harness endpoint is a text completion. Gnomon writes the turn's messages to a task file,
spawns the agent in a fresh empty directory under `.gnomon-out/` (never the checkout), and reads the
final text and the usage from the agent's own output:

| harness | argv | read from |
|---|---|---|
| `claude-code` | `claude -p <instruction> --output-format json --tools "" --strict-mcp-config --mcp-config '{"mcpServers":{}}' --no-session-persistence --system-prompt <role system.md>`, the messages on stdin | `result`, `usage`, `total_cost_usd`, `modelUsage` |
| `codex` | `codex exec --json --sandbox read-only -c approval_policy="never" --skip-git-repo-check -C <empty dir> -`, on stdin | `item.completed` / `agent_message`, `turn.completed.usage` |
| `opencode` | `opencode run --format json --file <task>`, with `OPENCODE_CONFIG_CONTENT` switching every tool off | `text` parts, `step_finish` tokens and cost |
| `command` | the declared argv with `{prompt_file}` filled in, the task on stdin | the last JSON line's `output`, `usage`, `model` |

The config check refuses a harness endpoint on a role that declares tools. The agent's own tools
would run outside Gnomon's tool policy, so the toolless mode is the only one that keeps Gnomon's
guarantees intact.

### 2. `delegate` mode: a coding agent for a role with tools, checked after the run

```toml
[roles.builder]
endpoint = "claude"
delegate = true                # the agent runs its own tools in the checkout; Gnomon checks the result
write_allow = ["app/**", "tests/**"]
```

Gnomon spawns the agent in the checkout with the narrowest permission flags the agent offers. It
records the run, then applies the surface policy it would have enforced in-loop, now **after the
run**:

- the diff against `write_allow` and the protected paths (`.gnomon/`, the hashed surface);
- the declared `[verify]` command, run by Gnomon, not by the agent;
- `bash_deny` against the commands the agent's output shows it ran, where the agent reports them.

A violation fails the turn and the working tree is reset to the turn's start. This is the assurance
Rihmasto's cell runners give today (kernel/runners, "checked after the run"). In Gnomon it becomes part
of the trail.

## The audit trail

A new record kind joins `AuditKind` in `packages/gnomon-core/src/audit.ts`, hash-chained like every
other record:

```ts
// One per call answered by an external coding agent (kind = "harness"). The call ran
// outside Gnomon's own inference loop, so the record says what ran and how, never the content.
| "delegate_run"
```

```json
{"kind": "delegate_run", "role": "analyst", "endpoint": "claude", "harness": "claude-code",
 "harness_version": "2.1.331", "argv_sha256": "...", "cwd_policy": "empty", "tools": "none",
 "task_sha256": "...", "output_sha256": "...", "model": "claude-sonnet-4-5-20250929",
 "usage": {"input": 120, "output": 40, "cache_read": 7, "cache_write": 5}, "cost_usd": 0.0123,
 "exit": 0, "ms": 1834, "assurance": "toolless"}
```

For `delegate = true` the record adds `"assurance": "after_run"`, the changed paths, and the verdict of
each check made after the run. A `degradation` record follows when the agent could not be told
something the surface asked for. Examples: an agent version with no `--tools` flag, or a model family
the agent did not report.

`gnomon verify` (`verifyTrail`) covers these records like any other, so a trail that includes harness
calls stays checkable end to end.

## The patch, in outline

1. `config.ts`: `EndpointKind = "ollama" | "openai" | "harness"`. `EndpointConfig` gains `harness?`,
   `command?: string[]` and `model?`. `url` becomes optional for `kind = "harness"`. `ENDPOINT_KEYS`
   gains the new keys. The config check accepts `harness` and refuses a harness endpoint on a role with
   tools unless `delegate = true`, and refuses `delegate` on a role with no `write_allow`.
2. A new `packages/gnomon-core/src/harness_endpoint.ts`: `runHarness(target, messages, opts) ->
   InferenceResult` (spawn, parse, usage). Detection reads `<binary> --version` and is cached per
   session, so the version lands in `session_start` and in each `delegate_run`.
3. `prompt_loop.ts`: `callEndpoint` branches on `target.endpoint.kind === "harness"` before building an
   HTTP request. The retry and fallback logic stays as it is. A harness that is not installed is a
   transport failure (retryable once), so a declared fallback still applies.
4. `audit.ts`: the `delegate_run` kind and its writer. `explain.ts` names it in `gnomon explain`.
5. `gnomon endpoints test <name>` sends the same tiny prompt through the harness and shows the latency.
6. Tests use fake agent executables written by the tests, as Rihmasto's do (`tests/harness_fakes.py`).
   Every test runs them, and none runs the real CLIs.

## What changes in Rihmasto when this lands

- `kernel/lanes.py` compiles a harness endpoint as `kind = "harness"` into the lane's `config.toml`
  instead of the placeholder it writes now (`kernel/harness_model.py` `gnomon_endpoint`).
- `kernel/model.py` stops intercepting harness roles. `gnomon task` answers them, and the guard
  becomes a version check: a Gnomon that knows `kind = "harness"` (a minimum version in
  `kernel/doctor.py`) takes them over.
- The ledger's `model_run` assurance changes from *no Gnomon audit trail for this call* to *recorded
  in Gnomon's audit trail (delegate_run)*. The evidence pack can then count those calls as
  Gnomon-level for the text roles.
- The verifier's diff-in-task stays: a toolless verifier still needs the change in its task.
