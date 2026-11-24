# The OpenAPI business-API connector (read-only)

How Rihmasto itself reads an ERP or another business system through Gnomon (D-0015), when the system
publishes an OpenAPI document: SAP (its OData services publish OpenAPI), Dynamics 365, NetSuite's REST
API, or any business API. It ships its own narrow server, `server.py` (standard library only), which
calls only the document's GET operations. For a product that reaches an ERP at run time, see
[docs/guides/data-integrations.md](../../docs/guides/data-integrations.md).

| File | What it is |
|---|---|
| `connector.json` | The connector: `python server.py --document openapi.json`, pinned by its sha256, two read tools, the write tools never allowed, and the base URL and token by reference. |
| `openapi.json` | The OpenAPI document the server reads. The example describes orders and customers; replace it with your system's. The connector card pins it with every other file here. |
| `server.py` | The narrow MCP server over stdio: `list_operations` (the GET operations) and `call_operation` (one GET operation, with only the parameters the document declares). |
| `mapping.py` | Pure functions: each record becomes an observation (`api:listOrders/1001`), each operation a note, every text quoted as untrusted data. |
| `fake.py` | A business API on 127.0.0.1 for the contract suite: it answers only the test bearer token, and refuses and records any write. |
| `fixtures/` | The pinned tools/list, a rug pull that would post and delete, injection samples and the fake's records. |

## Setup, one folder per system

1. Copy this folder to `connectors/<system>/` (for example `connectors/netsuite/`), set `system`, `title`
   and `namespace` in `connector.json`, and replace `openapi.json` with the system's own document.
2. Give the base URL and the token by reference. A system whose token comes from a sign-in flow gets a
   token command IT declares (`cmd:<command>`), which prints a short-lived token.
3. `rihmasto connector validate <system>`, then `python -m unittest tests.test_connectors_contract`.
4. IT enables it and decides its card. Writes to an ERP (a posting, an order) are decided writes, each
   approved in the Inbox: planned, they wait on Gnomon's model-free governed tool call
   ([docs/integrations.md](../../docs/integrations.md), section 3).

UNVERIFIED offline: how each named system signs a client in, and whether its published document lists
every operation it serves.
