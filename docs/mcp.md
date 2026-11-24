# Rihma over MCP

The MCP server is the headless form of the cockpit (FR-N3). A developer reaches the factory from
their own coding agent (Claude Code, Cursor, Codex or any other MCP client) without opening the
cockpit. It wraps the same kernel read models as `cockpit/server.py`, and it carries proposals,
never decisions: people decide in the cockpit.

It is standard-library Python 3.11+ (`mcp/server.py`), and it speaks MCP over **stdio**: JSON-RPC
2.0, one JSON message per line. The client starts it as a child process.

## Start it

From the repository root:

```
python -m mcp.server --home <factory home> --person "<your name>" --persona developer
```

- `--home` is the factory home (default: `$RIHMA_HOME`, then `$GNOMONFACTORY_HOME`, then `var/`).
  It must exist.
- `--person` and `--persona` are fixed for the life of the server. They sign every write and
  decide what the reads show: the cards this persona may decide, and what waits on it. The server
  refuses to start (exit code 2, a line on stderr, nothing on stdout) when the name is not a person
  (`kernel.people.is_person`: "assistant", "claude", "model" and the like are refused) or the
  persona is not one of `business_owner`, `product_owner`, `concept_evaluator`, `end_user`, `it`,
  `developer`, `operations`, `stakeholder`.
- `--lanes` is where the product lanes are, for the live cell (default: `$GF_LANES`, then
  `~/gf-lanes`).
- With access enforced ([guides/access.md](guides/access.md)), the server signs as the operating
  system user that starts it, `local:<os user>`, which the access file must name. `--person` must be
  that user's name in the file and `--persona` must be granted to them; otherwise the server refuses
  to start. Each proposal needs the persona granted on its project, and its records name the
  identity beside the person.

The file can also be run directly, from any working directory: `python <path to rihma>/mcp/server.py
...`. That is the form the client examples below use, because they do not depend on the client's
working directory. The package is named `mcp`; inside this repository it shadows the MCP Python SDK
of the same name, which Rihma does not use.

The server reads the factory home directly, so it runs on the machine that holds the home. To use a
home on another machine, run the server there through SSH (the client's command is `ssh` and the
server's command line is its argument); stdio carries over the connection unchanged.

## Connect a client

### Claude Code

A project-scoped `.mcp.json` in your repository:

```json
{
  "mcpServers": {
    "rihma": {
      "type": "stdio",
      "command": "python",
      "args": [
        "<path to rihma>/mcp/server.py",
        "--home", "<factory home>",
        "--person", "<your name>",
        "--persona", "developer"
      ]
    }
  }
}
```

Or add it from the command line:

```
claude mcp add rihma -- python <path to rihma>/mcp/server.py --home <factory home> --person "<your name>" --persona developer
```

### Any stdio client

Most clients (Cursor's `mcp.json` among them) take the same shape: a command, its arguments and an
optional environment.

```json
{
  "mcpServers": {
    "rihma": {
      "command": "python",
      "args": ["<path to rihma>/mcp/server.py", "--home", "<factory home>",
               "--person", "<your name>", "--persona", "<persona>"],
      "env": {"GF_LANES": "<lanes root, optional>"}
    }
  }
}
```

Codex reads the same three things from `config.toml`:

```toml
[mcp_servers.rihma]
command = "python"
args = ["<path to rihma>/mcp/server.py", "--home", "<factory home>", "--person", "<your name>", "--persona", "<persona>"]
```

## Tools

Every tool answers with JSON as text (`content: [{type: "text", text}]`) and the same object as
`structuredContent`. Read tools are marked `readOnlyHint`.

| Tool | Arguments | What it does |
|---|---|---|
| `rihma_projects` | none | Every project: id, title, work profile, maturity, stage, `now` (state and one line) and `health` (on track, at risk or off track, with reasons and the forecast). |
| `rihma_project` | `pid` | One project: now, health, evidence counts per state, open questions, the open cards this persona may decide (ids and titles only), the live cell, and the persona's lens. |
| `rihma_waiting` | none | What waits on this persona across projects (`kernel.dashboard.queue`, kept to the card kinds `CARD_DECIDERS` lets it decide), oldest first, with age in hours. |
| `rihma_floor` | none | The gate's judgement (first-round pass rate, merged, escalated, rounds), the harness outcomes of each Gnomon run with the harness note, runs by phase, and spend. |
| `rihma_timeline` | `pid` | Each task's rounds: start, end, model and gate verdict, and when it merged or escalated. |
| `rihma_evidence` | `pid` | Each criterion with its evidence state (verified, claimed, held out, failing, not measured), what the state rests on, and the criterion's text. |
| `rihma_square` | none | The delivery square: signals waiting, concepts to validate, projects per stage band, end-user feedback waiting for triage, what runs in production. |
| `rihma_track` | `pid` (optional) | How a project is doing against its approved plan: on track, at risk, off track or not measured, with each reason and every figure's basis, and the checkpoints due; without `pid`, every project's line ([autopilot and tracking](guides/autopilot-and-tracking.md)). |
| `rihma_autopilot` | `pid` | The project's autopilot run, the sandbox it is bound to, its delegations, the cards they decided and the ones they left to a person. Starting or stopping one is a person's act, in the cockpit or the command line. |
| `rihma_ask` | `question`, `pid` (optional) | "Where is…" and "how is it going" answers from the cockpit's own map (`kernel.assistant.ask` with no model). It proposes nothing; the answer notes that decisions are made in the cockpit. |
| `rihma_report_change` | `pid`, `text` | Opens a change card (`kernel.change.submit`), classified by rule as the cockpit does. A change that needs a business decision waits on a product or business owner. |
| `rihma_comment` | `pid`, `target_kind`, `target_id`, `text` | A comment on a requirement, criterion, task, release, card or the project (`Canon.comment`). It decides nothing; an owner may promote it into a change. |
| `rihma_signal` | `text`, `source` | A business need into the delivery square (`kernel.signals.receive`, channel `manual`). A person triages it into a change or a concept. |

Each write is signed with the server's person and persona, and also noted in the ledger as
`mcp_write` (`action`, `target`, `person`, `persona`): in the project's ledger, or the factory's
own for a signal. A signal keeps the persona in its record and its `signal_received` event, and
triage routes it by that persona: IT's need becomes an infrastructure change, not a stakeholder's
change request.

A write answers with the ids it made and with what the client sent, as it sent it: the change
card's title (the first line of `text`), the comment's target and the signal's source.

## Resources

| URI | What it is |
|---|---|
| `rihma://projects/<pid>/spec` | the project's `spec.md` (`text/markdown`) |
| `rihma://projects/<pid>/contract` | the project's `contract.json` |
| `rihma://projects/<pid>/ledger` | the last 100 ledger records, as JSON: seq, kind, time, payload, hash |
| `rihma://cockpit/map` | `cockpit/ui_map.json`, the cockpit's map of views and controls |

`resources/list` lists them for every project that has them, and `resources/templates/list` gives
the three project templates.

## The safety boundary

- **Reads and proposals, never decisions.** There is no tool that decides a card, answers a
  question, lets the factory assume, settles an assumption, approves, pauses, resumes, advances or
  deploys. The server's `instructions` say so to the client. A test checks that the tool list holds
  no such tool.
- **One signer.** The person and persona are set when the server starts, not per call, so a model
  cannot sign as someone else. A name that is not a person cannot start it.
- **No holdouts.** The holdout custody (`<home>/holdouts/`) is never served: no resource or tool
  reads from it. The kernel's own records can quote a holdout, so every output is also guarded:
  - the ledger's holdout fields (`failing`, `expected`, `observed`, `steps`, a re-authoring
    reason) are dropped, and the reason of a failed holdout step is replaced. The record says which
    fields it lost, and a redacted record no longer matches its hash;
  - the kernel's phrase for a failed holdout ("holdout R-1-AC-2 failed at step 2: …") keeps its
    first part and loses the rest, wherever it appears (a project's `now` line, for example);
  - the string values of every scenario in the custody that its project's spec and contract do not
    already show are replaced by `[held out]` in any output. The custody is read for this only.
  - what the client itself sent is never redacted. A refusal names the argument names or the
    project id it was given, and a write answers with its own title, target or source, each as
    the client sent it. Redacting the client's own words would make every read tool an oracle:
    send candidate strings, see which come back as `[held out]`. What a write stored is the
    factory's record, and a later read of it is guarded like any other.
- **Nothing outside the home.** Project ids are checked by pattern, a project folder that leads out
  of the home (a link) is not a project, and every served file must resolve inside the home and
  outside the holdout custody. The one exception is the cockpit's map, which is part of the code.
  Paved roads, credentials and environment variables are never served. A live cell's last target
  names no folder of the machine, wherever it stands in a command: the factory home, the lanes and
  the user's home become `...` (also when the kernel's 120-character cut ends inside one), and every
  other absolute path, quoted or not, keeps only its last part (`pytest .../repo -k x`). Relative
  paths and web addresses stay as they are.
- **Clean stdout.** stdout carries only protocol messages. Logs and tracebacks go to stderr.
- **No line ends the server.** A line nested deeper than the JSON parser goes is refused with
  `-32700`, a line that breaks the server gets `-32603` with a null id and its traceback on stderr,
  and the next line is read as usual.

## Errors

- An unknown tool, or `arguments` that are not an object: JSON-RPC error `-32602`.
- Bad arguments (missing, not text, too long, an unknown name, a value outside its list) and an
  unknown project: a tool result with `isError: true` and a plain message, so the model can correct
  itself.
- An unknown resource, or one a project does not have yet: `-32002`. An unknown method: `-32601`.
  A line that is not JSON, or is nested too deeply to parse: `-32700`. A bug: `-32603` with the
  exception's type only.
- A message that is not a JSON-RPC 2.0 request: `-32600`. Its id is echoed only when it is a
  string or a number; any other id is answered with `null`.

## Protocol

The server implements MCP's handshake revisions: `initialize` (answering with `protocolVersion`,
`serverInfo` `{name: "rihma", title, version}`, `capabilities` `{tools: {}, resources: {}}` and
`instructions`), `notifications/initialized`, `tools/list`, `tools/call`, `resources/list`,
`resources/templates/list`, `resources/read` and `ping`. The field names were checked against the
2025-06-18 and 2025-11-25 specifications. It accepts `2025-11-25`, `2025-06-18`, `2025-03-26` and
`2024-11-05`, and answers any other requested version with `2025-11-25`. A batch (a JSON array) is
answered as an array.

The current MCP revision, 2026-07-28, drops the handshake for per-request metadata. This server
does not implement that revision. A client that supports both probes with `server/discover`, gets
"method not found" and falls back to `initialize`, as that revision's compatibility rules describe.
