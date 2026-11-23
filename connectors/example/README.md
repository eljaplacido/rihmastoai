# The example connector

A read-only connector for a fake tracker. It is the template for a new connector and the one the
connector contract suite runs against its own narrow server (`server.py`), on this machine only.
Nothing here reaches a real system.

| File | What it is |
|---|---|
| `connector.json` | The connector (schema `rihma.connector/1`): the pinned server, the sha256 of its tools/list, two read tools that map to signals, one forbidden tool, the data class it reads and the one credential it would need, by name. |
| `mapping.py` | Pure functions from a read tool's result to proposals: one signal per item, its title quoted as untrusted data. |
| `server.py` | A narrow MCP server over stdio that serves `fixtures/items.json`. With `--rug-pull` it serves a changed tools/list. |
| `fixtures/tools.json` | The tools/list the connector pins. |
| `fixtures/rugpull-tools.json` | The same tools with an instruction hidden in one description: its hash differs, so it is caught. |
| `fixtures/injection.json` | Items that try to instruct a model or hide text; each must map to clean, quoted data. |
| `fixtures/items.json` | What the fake tracker holds. |

## Setup

1. Check the folder: `rihmasto connector validate example`.
2. Run the contract suite: `python -m unittest tests.test_connectors_contract`.
3. IT enables it: `rihmasto connector enable example --person <name> --persona it`. A `connector`
   card opens in the factory's own Inbox and pins this entry and every file in this folder.
4. IT decides that card (`enable` or `decline`) in the Inbox. Any later change to the entry or to
   any file in this folder (`connector.json`, `server.py`, `mapping.py`, a fixture) stops the
   connector; `rihmasto connector check` opens a new card. After `server.py` changes, `server.pin`
   must pin its new sha256 too, or it may not run.

Gnomon runs the server's `command` in an integration lane, from this folder, and passes it only the
credential names declared here (`EXAMPLE_TRACKER_TOKEN`; the fake server needs none). That lane is
planned: see [docs/integrations.md](../../docs/integrations.md) for what Gnomon must add first.

## Making your own

Copy this folder to `connectors/<system>/`, then:

- name the vendor's MCP server and its version in `server.pin` (drop `server.py`, or keep a narrow
  server of your own and pin its sha256);
- list the read tools and what each maps to, and put every tool that decides, merges, approves,
  deletes, deploys or pushes under `forbidden_tools`;
- record the sha256 of the server's tools/list in `tools_sha256` (`kernel.connectors.tools_sha256`);
- name each credential by reference only: `env:NAME`, `os:NAME` or `cmd:<command>`;
- write `mapping.py` as pure functions, and add your own injection and rug-pull samples.
