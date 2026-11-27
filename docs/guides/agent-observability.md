# Agent observability: what the IDE agents did, per project

Your developers work in their IDE and terminal with coding agents: Claude Code, Cursor, OpenCode. An
agent observability hub that your team runs itself records the metadata of
each of those sessions: what ran, where, how long, what failed and what it touched. **Agent
observability** brings that into Rihmasto, per project, for developers and IT: the **Agent sessions**
view.

The owner (2026-11-24): "this should be a per-project view for the developer and maybe the IT persona;
maybe not on by default but a module to plug in, but still something embedded inside the platform."

Rihmasto stays the system of record for decisions and evidence, not for telemetry
([D-0017](../../decisions/D-0017-governance-everywhere.md),
[D-0023](../../decisions/D-0023-what-rihmasto-is-and-is-not.md)): it reads the hub when you open the
view and keeps nothing, unless a person records a snapshot. It installs nothing either: putting the
hub's hooks into a repository is the hub's own command, run by you in your shell.

## What the view shows

| Section | What it says | Where it comes from |
|---|---|---|
| Sessions by harness | the sessions per day, by Claude Code, Cursor and OpenCode, and each session with its steps, failures and whether it read the contract first | the hub's sessions |
| Rework hotspots | the files the agents edited most, and how many are at or above the hub's rework threshold (reads are not rework) | the hub's insight |
| Failures and recovery | recovered, not recovered and cannot be told (a shell command has no file), and the sessions that left a failure stuck | the hub's intelligence, and each session's steps |
| Contract read before edit | governance coherence: of the sessions that touched code, the share that read the contract (AGENTS.md, CLAUDE.md, a contract file) before the first edit | the hub's intelligence, and each session's steps |
| Session trajectories | productive, exploratory, execution and corrective steps, the loops, and each session as a strip of read, edit, run, fail and prompt | the hub's intelligence, and each session's steps |
| The hub's hash chain | intact or broken, how many events were checked, and what the verdict attests: `persisted` (a database the hub cannot rewrite: tamper evidence) or `derived-on-load` (a file ledger rebuilt at start: only self-consistent) | the hub's chain check and its health |

Every section links into the hub's own page for the detail. A section the hub has nothing for says
**not measured**, why, and how to get it measured; it is never shown as a zero.

**Privacy: metadata only.** The hub records event types, times, harness, session ids, tool names, file
paths, status and durations; never a prompt, a response, a diff, a command line or a line of source. It
enforces that twice, before an event leaves the machine and at ingest. Rihmasto reads only what the hub
serves, and its snapshot keeps counts and ids (session ids, file paths and edit counts), never a step.

## Turn it on

The module is **off by default** and in no preset. A developer, IT, a product owner, a business owner
or compliance turns it on for one project (or the factory) in **Settings, Modules**, or:

```bash
rihmasto modules set --project <pid> --enable agentobs --person "Dana Example" --persona developer
```

On a project with the module on, developers and IT see the **Agent sessions** tab. Other personas do
not; opened by its address, the view says who it is for.

## Run the hub

In your checkout of the hub (it is a separate project; follow its own README):

```bash
npm install
npm run build
npm run hub:dev          # the hub on http://127.0.0.1:8787
```

Then IT sets the hub's address in **Settings, Agent observability** (shown once the module is on
somewhere), or:

```bash
rihmasto agentobs settings --url http://127.0.0.1:8787 --person "Ilkka Example" --persona it
rihmasto agentobs status
```

- **Loopback or a private address** (or a private name such as `.lan` or `.internal`) is read at once.
- **One on your own network under a public-looking name** (a tailnet name, say): tick *It is on our own
  network* (`--private`).
- **A hosted hub** is refused unless IT consents explicitly (`--hosted`, *I consent to a hosted hub*),
  and then only over https: its records (file paths, session shapes) would cross the internet.
- **A token.** The hub's reads need none by default; its token guards writes, which Rihmasto never
  makes. If your hub sits behind something that wants one, name the environment variable that holds
  it (`--token-env COCKPIT_HUB_TOKEN`). The value is read when a request is made and never kept,
  recorded or shown.

## Map the project to the hub's project

The hub names a project by its repository: a `cockpit.io/project-id` annotation in `catalog-info.yaml`,
else `owner/repo` from the git remote `origin`, else `local/<folder name>`. For an adopted or attached
project Rihmasto works out the same ids and suggests the one the hub knows. A developer or IT confirms
it (or chooses another) on the view; it is recorded in the project's ledger (`agentobs_mapped`).

```bash
rihmasto agentobs map <pid> --suggested --person "Dana Example" --persona developer
rihmasto agentobs map <pid> --hub-project acme/checkout --person "Dana Example" --persona developer
rihmasto agentobs show <pid>
```

## Instrument a repository

When the hub has no session for the project, the view shows the hub's own commands, with your
repository's folder filled in, to run in the hub's checkout:

```bash
npm run cockpit -- install --project /path/to/your-repo --dry-run   # preview first
npm run cockpit -- install --project /path/to/your-repo
npm run cockpit -- doctor --project /path/to/your-repo              # after restarting the IDE or agent
```

When a repository is adopted or attached, Rihmasto looks for the hub's hooks **by file name only**
(`.claude/hooks/cockpit-hook.*`, `.cursor/hooks/cockpit-hook.*`, `.opencode/plugins/cockpit.js`): it
opens and runs none of them. What it finds is on the project's **AI tools in this project** card, which
offers to turn the module on for a project worked on in IDEs, and in the ledger
(`agentobs_instrumentation_seen`).

## Record what the hub shows

**Record what the hub shows** on the view (or `rihmasto agentobs snapshot <pid>`) puts the figures that
matter for decisions into the project's ledger (`agent_sessions_observed`): sessions per harness, the
sessions that left a failure unrecovered, the files at or above the rework threshold, the share that
read the contract first, and the chain's verdict. When something new appears since the last record,
`agent_failure_unrecovered` or `agent_rework_heavy` follows, so an automation can react.

Automations (see [Automations](automations.md)) add the action **record what the agent observability hub
shows** (`agent_snapshot`) and three templates: *Record what the IDE agents did, every morning*,
*Notify on heavy rework by IDE agents* and *Notify on unrecovered agent failures*.

## Ask Rihma

"Show me the agent sessions", "Which rework hotspots do the IDE agents have?" or "How are the agent
sessions going?" is answered from the hub, with Take me there to the view. With the module off, Ask
Rihma proposes turning it on for the project; with the project not mapped, it proposes the hub project
that matches. Each proposal runs only when you confirm it, signed with your name.

## Where else it shows

`kernel/agentobs/feeds.py` holds the hooks the other views call when they are in the build:

- **Insights**: QA (files the IDE agents reworked, unrecovered failures), Governance (contract read
  before edit), Usage (sessions by harness), as insight tiles;
- **Review**: "From your IDE agents", the sessions that left a failure unrecovered and the files
  reworked heavily since you last looked;
- **The agent channel**: a coding agent's post whose trace names a session id the hub observed is linked
  to that session;
- **The copilot's catalogue**: the view, and a suggestion to turn it on for a project worked on in IDEs;
- **The checks**: *Unrecovered agent failures*, passed, failed or not measured.

## Know before you rely on it

- The hub's figures are its own: Rihmasto shows them with the hub's denominators and does not recount
  them. Per-session figures come from each session's most recent 200 steps; a session cut before its
  first edit reads "not measured" for contract-first.
- A failure with no file (a shell command) cannot be told recovered or not; the recovery rate leaves it
  out, as the hub does.
- An intact chain from a hub on its file ledger (`derived-on-load`) is not tamper evidence; set the
  hub's database for that.
- Nothing is read until someone opens the view, asks Ask Rihma, or an automation records a snapshot;
  Rihmasto does not poll the hub.

See also [Your IDE and Rihmasto](ide-and-rihmasto.md) and
[Use only what you need](use-only-what-you-need.md).
