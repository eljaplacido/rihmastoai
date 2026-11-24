# The PostgreSQL connector (read-only)

How Rihmasto itself reads a PostgreSQL database through Gnomon (D-0015): the schemas and tables of a
system it adopts, and the rows a read-only query returns, as notes and observations a person reads. It
names a pinned MCP server that Gnomon runs in an integration lane, read-only first. Nothing here writes.
For a product that reaches a database at run time, see
[docs/guides/data-integrations.md](../../docs/guides/data-integrations.md).

| File | What it is |
|---|---|
| `connector.json` | The connector (schema `rihma.connector/1`): the pinned server `postgres-mcp --access-mode=restricted`, the sha256 of its tools/list, four read tools, the tools never allowed, the data classes it reads and the one credential it needs, by reference. |
| `mapping.py` | Pure functions from a read tool's result to proposals: a schema or object becomes a note (`pg:public.orders`), a row an observation (`pg:result/1`), every text quoted as untrusted data. |
| `fake.py` | An in-process fake of the pinned server for the contract suite: the same tools/list, results from `fixtures/database.json`, and `execute_sql` that refuses anything but one read statement, as restricted mode does. |
| `fixtures/tools.json` | The tools/list the connector pins. UNVERIFIED: written from the server's documentation, offline. |
| `fixtures/rugpull-tools.json` | The same tools with an instruction hidden in `execute_sql`'s description: its hash differs, so it is caught. |
| `fixtures/injection.json` | Objects whose comments try to instruct a model or hide text; each must map to clean, quoted data. |
| `fixtures/database.json` | What the fake serves. |

## What is verified and what is not

UNVERIFIED offline (2026-11-23): the server's name and version (`postgres-mcp` 0.3.0), its
`--access-mode=restricted` flag, the `DATABASE_URI` variable it reads, its tools/list and the shape of its
results. The live check below settles all of them against a real server and database. Until it has run,
treat the pin as a draft: a server whose tools/list differs from the pin is stopped
(`kernel.connectors.check_tools`), never called.

`explain_query` is forbidden because `analyze: true` runs the statement it explains. The index and health
tools are forbidden because nothing here needs them: least privilege.

## Setup

1. On the host that runs the lane, install the pinned server version (IT's step; Rihmasto installs nothing).
2. Create a PostgreSQL role that can only read: `CREATE ROLE rihma_reader LOGIN; GRANT CONNECT ON DATABASE
   ...; GRANT USAGE ON SCHEMA public TO rihma_reader; GRANT SELECT ON ALL TABLES IN SCHEMA public TO
   rihma_reader; ALTER ROLE rihma_reader SET default_transaction_read_only = on;`. The server's restricted
   mode is the second wall, not the first.
3. Put the role's connection string in the variable `RIHMA_POSTGRES_DSN` on that host (or change the
   credential's `ref` to `os:` or `cmd:`). The value never enters this folder.
4. Check the folder and run the contract suite: `rihmasto connector validate postgres`, then
   `python -m unittest tests.test_connectors_contract`.
5. Run the live check on the host that runs PostgreSQL (below). If the real tools/list differs from the
   pin, review the difference, update `fixtures/tools.json` and `tools_sha256`, and run it again.
6. IT enables it: `rihmasto connector enable postgres --person <name> --persona it`, then decides the
   `connector` card in the factory's Inbox. A later change to any file here stops the connector until IT
   decides a new card.

## The live check

`tests/test_connectors_live.py` runs only when asked, against a database you name, on loopback only:

```bash
RIHMA_LIVE_POSTGRES=1 RIHMA_POSTGRES_DSN=postgresql://rihma_reader:...@127.0.0.1:5432/orders \
  python -m unittest tests.test_connectors_live -v
```

It starts the pinned server with that DSN as `DATABASE_URI`, speaks MCP to it over stdio as Gnomon does,
and checks that its tools/list is the pinned one, that `list_schemas`, `list_objects` and a `SELECT` map
to valid proposals, and that a statement that writes is refused and leaves nothing behind. Without the
flag, or when the server is not installed, it is skipped and says why. A DSN whose host is not loopback is
refused: run it on the database's own host.
