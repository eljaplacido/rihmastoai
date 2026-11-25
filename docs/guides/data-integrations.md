# Data integrations: databases, warehouses, cloud storage and ERPs

How a capability Rihmasto builds reaches a database, a data warehouse, cloud storage, an ERP or another
business system, who approves what, and where credentials live. Also how Rihmasto itself reads those
systems through Gnomon ([D-0015](../../decisions/D-0015-integrations-through-gnomon.md)).

**Status (2026-11-23).**

| Part | State |
|---|---|
| Declarations: what a product reaches, how, read or read-write, which data classes, credentials by name (`kernel/integration_decl.py`, `rihmasto integration ...`) | built |
| The spec, the plan, the contract: each declaration is listed and becomes an `INT-` requirement a test must name; a writing or sensitive one needs plan approval at any maturity | built |
| Bindings on the paved roads, a `road` card IT decides per binding and environment, wiring into the deploy package and the Compose file (`kernel/integration_bind.py`) | built |
| The gate's stand-ins and its `integrations` signal (`kernel/integration_standins.py`) | built |
| The Plan view's "Data integrations" block, and Ask Rihma's way there | built |
| Reference connectors for Rihmasto itself: `connectors/postgres`, `connectors/snowflake`, `connectors/s3`, `connectors/openapi`, each passing the contract suite against a local fake | built; nothing calls them until Gnomon's integration lane exists ([integrations.md](../integrations.md), section 3) |
| The PostgreSQL live check against a real database | built, not yet run: it waits for a PostgreSQL host |
| A docker product gets each `env:` credential by name (`docker run --env NAME`), its value only in the docker CLI's environment (FR-DS5) | built (2026-11-24), tested against a fake docker CLI; not yet run against a docker daemon |
| A template whose products carry a pinned database driver; stand-ins on a preview without a binding; a declaration changed through the change loop after compile; credentials whose reference is `os:`, `cmd:` or a vault URL resolved for a local or docker product; connectors for MySQL, SQL Server, BigQuery, Databricks, Azure Blob and GCS; decided writes to an ERP | planned |

## 1. Two ways to reach a system

- **A product reaches it at run time.** The capability Rihmasto builds (a service, an agent, a workflow)
  reads orders from a database or writes a file to a bucket. It **declares** the integration in its
  spec, IT **binds** it to a real endpoint on the paved road of each environment and **approves** the
  binding, and delivery hands the product the settings and secret references. The gate tests the data
  access against a **stand-in** first.
- **Rihmasto itself reads it.** To adopt a system, learn a schema, or take signals from an ERP, Rihmasto
  goes through Gnomon: a **connector** names the MCP server Gnomon runs in an integration lane, every
  call checked against policy and recorded in Gnomon's audit trail. Read-only first.

## 2. Who decides what

| Step | Who | Where it is recorded |
|---|---|---|
| Propose an integration from the need | the analyst (a model), in its spec draft | `spec.json` `integrations`, with a provenance by the spec's rules; `spec_written` in the ledger |
| Declare or withdraw one | a person with a plan editor's persona (business owner, product owner, developer), with a reason | `integration_declared`, `integration_withdrawn`; the declaration is theirs (customer-confirmed) |
| Approve the plan that lists it | as for any plan; at any maturity when the product writes to a system or touches confidential or restricted data there | the plan's approval card |
| Bind it to an endpoint, per environment | IT, in `paved_roads.json` | the road card's payload and pin |
| Approve each binding | IT only, on a `road` card | the card's decision; `integrations_waiting`, `integrations_bound` |
| Check the data access | the gate, with no model | the `integrations` signal in the task's gate record |
| Turn on a connector for Rihmasto itself | IT, on a `connector` card | `connector_enabled` in the factory's ledger |
| Trust a connector's server in Gnomon | the owner (`gnomon trust grant`), never Rihmasto | Gnomon's own audit |

## 3. Where credentials live

Never in the repository, the spec, the ledger, a package or a Compose file.

- A **declaration** names each credential the product needs (`ORDERS_DB_PASSWORD`): a name only.
- A **binding** says where each value lives: `env:NAME` (the host's environment), `os:NAME` (the operating
  system's store), `cmd:<command>` (a token command IT declares) or a vault URL. A binding that holds a
  value, or an endpoint that carries a password or a token, is refused.
- The **deploy package** carries the reference. **Compose** gives the product each secret as the variable
  of its name, taken from the deployer's environment at `up` (`${ORDERS_DB_PASSWORD:?...}`), and refuses
  to start without it. A **local process** gets an `env:` secret's value from the kernel host's
  environment, in memory only. A **docker** product gets each `env:` secret by name only: the container
  is started with `--env ORDERS_DB_PASSWORD` and no value, and the docker CLI reads the value from its own
  environment for that one command, so no argument (visible to anyone listing processes), package, slot
  record or ledger entry holds it. A credential the deploying host does not hold is not given, and the
  product's own health check and the release's probes show what it cannot reach. A reference of another
  kind (`os:`, `cmd:`, a vault URL) is not resolved for a local or docker product yet (planned).
- **No credential steers the deploy tools.** The docker CLI gets a credential's value in its own
  environment, so a credential named like a variable the CLI or the host reads (`DOCKER_HOST`,
  `DOCKER_CONFIG`, `HTTP_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`, `LD_PRELOAD` ...) would change which daemon,
  proxy, certificates or preloaded library the tool itself uses. Such a name is refused four times: at the
  declaration, on the binding (no card can approve it), when the package is validated (one approved before
  this rule is not delivered), and by the docker CLI wrapper before it runs (FR-DS5-AC-2). Built
  (2026-11-24) and tested.
- A **connector**'s credentials are references too, and Gnomon passes its server only the names it
  declares.

## 4. Kinds, ways and stand-ins

| Kind | Family | Ways (default first) | Stand-in at the gate | Connector for Rihmasto itself |
|---|---|---|---|---|
| postgres, mysql, sqlserver | database | mcp, http, sql | MCP or HTTP server; SQLite file via sql | `connectors/postgres` (mysql, sqlserver planned) |
| sqlite | database | sql | SQLite file | none needed |
| snowflake, bigquery, databricks | warehouse | http, sql, mcp | HTTP server; SQLite file via sql | `connectors/snowflake` (others planned) |
| s3, azure_blob, gcs | cloud storage | http | an object store in S3's path style | `connectors/s3` (Azure Blob, GCS planned) |
| gdrive | a Google Drive folder | http | the Drive v3 API on loopback, with the metadata server's token | none; the product imports `app/gdrive.py` ([gcp.md](gcp.md)) |
| openapi (sap, dynamics, netsuite, generic) | ERP or business API | http | HTTP server answering from the product's fixture | `connectors/openapi` |
| mcp | MCP server | mcp | MCP over HTTP from the product's fixture | any connector |
| rest | REST API | http | HTTP server answering from the product's fixture | none |

**Ways.** `mcp` reaches the system through an MCP server over HTTP (a database's MCP server that IT runs
read-only), `http` through its own HTTP API (Snowflake's SQL API, BigQuery's REST API, an ERP's OpenAPI),
`sql` through a database connection. The paved road's template is standard-library Python, so `sql` opens
only a SQLite file today: a PostgreSQL, MySQL or SQL Server endpoint via `sql` needs a driver the template
does not carry, and the plan says so. That is why databases default to `mcp`.

## 5. How a capability reaches each

- **A database.** Declare `{"name": "orders_db", "kind": "postgres", "access": "read", ...}`. The product
  reads `ORDERS_DB_URL` and calls the database's MCP server there (`tools/call` with a read-only query).
  IT runs that server beside the database, read-only, and binds its https endpoint.
- **A data warehouse.** Declare `{"kind": "snowflake", "via": "http", ...}`. The product posts a
  statement to the warehouse's SQL API at `<NAME>_URL`, signed with the credential it declared. A POST
  whose `statement` (or `query`, or `q`) is a SELECT counts as a read at the gate.
- **Cloud storage.** Declare `{"kind": "s3", "access": "read-write", ...}`. The product reads and writes
  `/<bucket>/<key>` at `<NAME>_URL`; on a real store it signs with the keys it declared.
- **An ERP.** Declare `{"kind": "openapi", "system": "netsuite", ...}`. The product calls the operations
  the system's OpenAPI document describes, at `<NAME>_URL`, with a bearer token it declared.

## 6. The declaration

```json
{"name": "orders_db", "kind": "postgres", "via": "mcp", "access": "read",
 "data_classes": ["internal"], "credentials": ["ORDERS_DB_PASSWORD"],
 "purpose": "reads open orders for the picking list"}
```

- `name` gives the settings the product reads: `ORDERS_DB_URL` (the endpoint), `ORDERS_DB_ACCESS` (read or
  read-write) and `ORDERS_DB_KIND`. A name whose settings would look like a secret (`api_token`), like a
  setting the road sets (`port_db`) or like a variable the deploy tools read (`docker`, `http`, `https`,
  `no`, `ssl`, `ld` and the rest of `TOOLING` in `kernel/integration_decl.py`: `DOCKER_HOST`, `HTTP_PROXY`,
  `NO_PROXY`, `SSL_CERT_FILE`, `LD_PRELOAD`) is refused.
- Each credential starts with the prefix (`ORDERS_DB_...`) and is never one of the three settings.
- The kernel writes requirement `INT-ORDERS-DB` with criterion `INT-ORDERS-DB-AC-1`: a test named by it
  reads `orders_db` only through `ORDERS_DB_URL`, and nothing writes to it when it is declared read. The
  criterion's `given` names the declaration in a fixed form, and the gate reads it back from the contract.

## 7. The binding

```json
"roads": {
  "team-docker": {"kind": "docker", "configured": true, "environments": ["staging", "production"],
    "integrations": {
      "orders_db": {
        "staging": {"endpoint": "https://orders-db-mcp.test.internal/mcp",
                    "secrets": [{"name": "ORDERS_DB_PASSWORD", "ref": "env:ORDERS_TEST_PASSWORD"}]},
        "production": {"endpoint": "https://orders-db-mcp.internal/mcp",
                       "secrets": [{"name": "ORDERS_DB_PASSWORD", "ref": "https://kv.vault.azure.net/secrets/orders-db"}]}}}}}
```

One binding serves every environment the road serves, or each environment has its own. Via `sql` the
endpoint is the database's URL (`postgresql://reader@db:5432/orders`, a user and no password); via `http`
or `mcp` it is https, plain http only on loopback. `rihmasto integration check <pid>` names what is wrong
with each binding without opening a card. A preview runs on the built-in `local-preview` road: to bind
there, IT names a road `local-preview` in `paved_roads.json` (`"kind": "local-process"`, `"configured":
true`, `"environments": ["preview"]`) with its own `integrations`, which replaces the built-in one.

## 8. The road card

Before anything is built, delivery checks each declared integration in each environment of its plan. A
missing or wrong binding, or a valid one no card approved, opens a `road` card that only IT decides:
what the product reaches, the access in capitals, the endpoint, the data classes, each credential's name
and where it lives, and what is wrong with the binding if anything is. `configured` lets the release go
on; `declined` stops it. The card pins the road, the environment, the declaration and the binding: change
any of them and the open card is withdrawn and a new one opens. An approved binding is not asked again
for a later release while nothing it pins changed.

## 9. The gate's stand-ins

The gate runs the product's own tests with each declared integration pointed at a stand-in on 127.0.0.1:

- **via sql**: a SQLite file, seeded from `tests/standins/<name>.sql` when the product has one;
  `<NAME>_URL` is `sqlite:///` and the file's absolute path.
- **via http**: an HTTP server answering from `tests/standins/<name>.json`:
  `{"responses": [{"method": "GET", "path": "/orders", "status": 200, "json": [...]}]}`. For cloud storage
  it is an object store instead (`PUT`, `GET`, `HEAD`, `DELETE` on `/<bucket>/<key>`, and a list as S3's XML).
- **via mcp**: MCP's JSON-RPC over HTTP POST, `tools/list` and `tools/call` answered from the same file's
  `tools` and `results`.

Credentials get a placeholder that is no secret. The `integrations` signal is **failed** when a read
integration was written (the SQLite file changed; a PUT, PATCH or DELETE; a POST that is not a read query;
an MCP tool whose name writes) or a seed did not load; **not measured** when the task's `INT-` test never
reached its HTTP stand-in, or the criterion was edited so that it no longer names its integration; and
**passed** otherwise. A product with no integration starts no stand-in and gets no signal.

## 10. What delivery hands the product

The deploy package gets an `integrations` list (each one's kind, way, access, data classes, endpoint, the
card that approved it, and who), the three settings, and each credential as a secret reference. Then:

| Road | The product gets |
|---|---|
| local-process | the settings, and each `env:` secret's value from the kernel host |
| docker | the settings as `--env NAME=value`, and each `env:` secret as `--env NAME`, its value given to the docker CLI's environment only |
| azure-containerapps | the settings as environment variables, secrets as Key Vault references |
| a site's Compose file | the settings, and each secret by its name from the deployer's environment |

## 11. Connectors for Rihmasto itself

| Folder | Server | What it reads | Verified |
|---|---|---|---|
| `connectors/postgres` | `postgres-mcp --access-mode=restricted`, pinned | schemas, objects, a read-only query | contract suite against an in-process fake; the live check is ready, not yet run; the server's version and tools/list are UNVERIFIED |
| `connectors/snowflake` | the Snowflake Labs MCP server with a read-only `tools_config.yaml`, pinned | objects, a SELECT | contract suite against an in-process fake; version, flags and configuration keys UNVERIFIED |
| `connectors/s3` | Rihmasto's narrow server, SigV4, GET and HEAD only, one bucket | keys, metadata, text | contract suite against a signed fake store |
| `connectors/openapi` | Rihmasto's narrow server over a pinned OpenAPI document, GET operations only | records from an ERP or business API | contract suite against a fake API |

Each is enabled like any connector ([integrations guide](integrations.md)). The PostgreSQL live check
runs on the database's own host:

```bash
RIHMA_LIVE_POSTGRES=1 RIHMA_POSTGRES_DSN=postgresql://reader:...@127.0.0.1:5432/orders \
  python -m unittest tests.test_connectors_live -v
```

## 12. Tutorial: a picking list that reads open orders

1. **Declare.** After intake and the spec, the product owner declares the database:
   `rihmasto integration declare P-001 --name orders_db --kind postgres --access read --data-class internal
   --credential ORDERS_DB_PASSWORD --purpose "reads open orders" --person Aino --persona product_owner
   --reason "the picking team's source of truth"`. The plan's version moves on and a new approval card
   follows.
2. **See it in the plan.** Open the project's **Plan** tab: the **Data integrations** block lists
   `orders_db`, via mcp, reads only, internal data. Ask Rihma "where are the data integrations?" and press
   *Take me there*. Approve the plan.
3. **Build.** The builder reads `INT-ORDERS-DB-AC-1` in its envelope and writes `tests/standins/orders_db.json`
   and a test named by the criterion. The gate runs it against the stand-in; the `integrations` signal says
   passed, or names the write it saw.
4. **Bind.** IT adds the binding to the road in `paved_roads.json`, then runs
   `rihmasto integration check P-001` until nothing is wrong.
5. **Approve.** Delivery opens one `road` card per environment. IT reads what the product reaches, with
   which access and which credentials, and decides `configured`.
6. **Run it.** The release deploys with `ORDERS_DB_URL` set. A site's export bundle (`kernel/bundle.py`)
   carries a `compose.yaml` that sets it too and takes `ORDERS_DB_PASSWORD` from the deployer's
   environment.
7. **On the docker road.** If the binding says `{"name": "ORDERS_DB_PASSWORD", "ref":
   "env:ORDERS_TEST_PASSWORD"}`, set `ORDERS_TEST_PASSWORD` in the environment of the host that runs
   `rihmasto deliver`, not in any file. The container starts with `--env ORDERS_DB_PASSWORD` and reads
   the value there; `docker inspect` on that host shows it, as for any container environment, so the
   host is IT's to guard. Leave the variable unset and the product starts without it: its own checks
   say what it cannot reach.

## 13. Limits

- The stand-ins check the access path and the access mode, not the system's dialect: SQLite is not
  PostgreSQL, and a fixture is not the ERP.
- A read query is recognised by its first word (SELECT, WITH, SHOW, DESCRIBE, EXPLAIN, VALUES) and a single
  statement; an MCP write by its tool's name. Fixed rules can miss a new shape; the system's own read-only
  role is the wall that holds.
- What Gnomon must add before a connector runs is listed in [integrations.md](../integrations.md), section 3.
