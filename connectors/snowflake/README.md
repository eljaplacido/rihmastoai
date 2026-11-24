# The Snowflake connector (read-only)

How Rihmasto itself reads a Snowflake warehouse through Gnomon (D-0015): the tables and views it holds
and the rows a SELECT returns, as notes and observations a person reads. It names the Snowflake Labs MCP
server, pinned, which Gnomon runs in an integration lane with a service configuration that only reads.
For a product that queries a warehouse at run time, see
[docs/guides/data-integrations.md](../../docs/guides/data-integrations.md).

| File | What it is |
|---|---|
| `connector.json` | The connector: the pinned server `snowflake-labs-mcp --service-config-file tools_config.yaml`, the sha256 of its tools/list, three read tools, the object tools that create, drop or alter (forbidden), and its credentials by reference. `server.pin.sha256` pins `tools_config.yaml`. |
| `tools_config.yaml` | The server's service configuration: object listing and SELECT, SHOW and DESCRIBE only; every statement that writes off; no Cortex service. |
| `mapping.py` | Pure functions from a read tool's result to proposals: an object becomes a note (`snowflake:ANALYTICS.PUBLIC.SALES`), a row an observation (`snowflake:result/1`). |
| `fake.py` | An in-process fake of the pinned server for the contract suite, refusing every statement but a read, as the configuration does. |
| `fixtures/` | The pinned tools/list, a rug pull of it, injection samples and the fake's warehouse. |

## What is verified and what is not

UNVERIFIED offline (2026-11-23): the package name `snowflake-labs-mcp` and version 1.3.3, the
`--service-config-file` flag, the keys of `tools_config.yaml`, the `SNOWFLAKE_*` variables the server
reads, its tools/list and its result shape. Snowflake also offers a managed MCP server inside Snowflake;
it is remote (HTTP), so it waits for Gnomon's HTTP client (docs/integrations.md, item 4). There is no
live check for Snowflake yet: when one is run, it is the same as PostgreSQL's (the pinned tools/list,
the reads, a refused write).

## Setup

1. On the host that runs the lane, install the pinned server version (IT's step).
2. In Snowflake, create a role that can only read the schemas Rihmasto may see, a user for it with a
   programmatic access token, and a small warehouse it may use.
3. Name the account, user, role and warehouse in the variables the credentials reference, and keep the
   token in the operating system's store (`os:RIHMA_SNOWFLAKE_PAT`). No value enters this folder.
4. `rihmasto connector validate snowflake`, then `python -m unittest tests.test_connectors_contract`.
5. IT enables it (`rihmasto connector enable snowflake --person <name> --persona it`) and decides its
   card. A change to `tools_config.yaml` or any other file here stops it until IT decides a new card.
