# Small capabilities: an automation, a workflow or one agentic capability

Not every need is an app. Many are a job with no screens: count last night's failed deliveries, check
a folder every hour, answer one kind of question for people's own AI assistants. Rihmasto builds these
as **small capabilities**: the same governed chain (intake, spec, hashed contract, gate, delivery,
ledger), with a product template made for them and one image that can be reached several ways.

This guide takes a two-sentence need for an automation to a running capability you can reach over
MCP, an OpenAI-compatible endpoint, a website chat or HTTP. [What is built and what is
planned](#what-is-built-and-what-is-planned) is at the end.

## The pieces

| Piece | What it does | Where |
|---|---|---|
| **The automation profile** | A scheduled or triggered job with no screens, a single workflow or one agentic capability. Its panel asks what starts a run and where it must be reachable; its deliverable is a capability pack. | `kernel/profiles.py` (`automation`) |
| **The capability template** | The paved-road product (the server, `/health`, `pack_guard`, the road's checks) plus `app/runtime.json`, `app/job.py`, and the faces in `factory/`, which no builder cell may change. | `kernel/capability_template.py` |
| **The runtime declaration** | `app/runtime.json` (`rihma.runtime/1`): what starts a run, its tools, model roles, integrations, secrets by name, and its faces. Judged with no model, at the gate, in the pack and in the image. | `kernel/runtime_decl.py` |
| **The faces** | One image, several ways in: MCP over stdio and Streamable HTTP, an OpenAI-compatible chat whose model is the capability's name, a website embed, and HTTP. Each answers only after the pack guard has checked the pack. | `factory/faces.py`, `factory/faces_http.py` (from `kernel/faces_image.py`, `kernel/faces_http_image.py`) |
| **The trigger path** | A webhook from another system, or an event from Rihmasto's relay, verified with Standard Webhooks, runs the capability once per delivery. With the schedule on, a scheduled capability runs itself. Each run's result can go out as a signed CloudEvent. | `factory/faces_http.py` |
| **`rihmasto capability`** | `check` judges the declaration at a release; `serve` runs a delivered release on this machine, behind its pack guard, and records who served it. | `kernel/faces.py` |
| **Compose** | The bundle's `compose.yaml` carries the faces in its one service, with every secret by name. | `kernel/roads.py` (`render_compose`) |
| **The gateway route** | The capability as a model: a gateway workload named after it, routed to its own OpenAI-compatible face. | `gateway/packs.py` (`agent_workloads`) |

## Tutorial

The need, in two sentences:

> Every night, count yesterday's failed shipment deliveries the stock system reports, as a scheduled
> job with no screens. Make it reachable over MCP.

### 1. Start the project

```bash
rihmasto new "Shipment failure digest" --source "Every night, count yesterday's failed shipment deliveries the stock system reports, as a scheduled job with no screens. Make it reachable over MCP." --maturity explore --requested-by Aino
```

The rule proposes the **automation** profile for this text (its words: every night, scheduled, MCP).
When a request names two kinds of work about equally ("an agent that runs every night"), the proposal
is uncertain and the panel asks you which kind it is. To choose it yourself, add
`--profile automation`, or pick **Automation or small capability** under **New project** in the cockpit.

### 2. Answer the panel

Besides the usual perspectives, the automation profile asks two questions:

- **What starts a run?** a schedule, a webhook from another system (verified by its signature), an
  event from Rihmasto itself through the relay, or a person.
- **Where must it be reachable?** MCP for people's own AI assistants, the gateway as a model, a chat
  on your website, or HTTP.

Answer them (`rihmasto answer <pid> <Q-id> "a schedule, every night" --person Aino --persona
business_owner`) or let the factory assume them in `mixed` or `assume` mode. Each answer is in the
ledger with your name, and the spec's provenance says which requirement rests on it.

### 3. Let the chain run

```bash
rihmasto run <pid>
```

The spec is written with the profile's guidance (criteria against a run, every system it calls
simulated in tests), the contract is compiled, and the product starts from the capability template:

```text
app/runtime.json      what it needs where it runs: the builder fills it in
app/job.py            run(trigger) and one function per declared tool: the builder writes it
app/routes.py         imports the faces
factory/faces.py      the faces: not the builder's to change (factory/ is protected)
factory/faces_http.py the HTTP faces and the trigger path
factory/runtime_decl.py  the same check the factory runs
tests/test_road_contract.py  the road's checks, the capability's included: never edited by a cell
```

A builder cell writes the job and the declaration. For this need, the declaration might read:

```json
{
  "format": "rihma.runtime/1",
  "name": "shipment-digest",
  "kind": "automation",
  "summary": "Counts failed shipment deliveries for operations.",
  "trigger": {"kind": "schedule", "every_minutes": 1440},
  "faces": ["mcp", "http"],
  "tools": [{"name": "count_failures", "description": "How many of the given shipments failed.",
             "effect": "read", "input": {"type": "object", "properties": {"shipments": {"type": "array"}},
                                         "required": ["shipments"]}}],
  "integrations": [{"system": "stock-system", "via": "api", "purpose": "reads yesterday's deliveries",
                    "writes": false, "secrets": ["STOCK_API_TOKEN"]}],
  "secrets": [{"name": "STOCK_API_TOKEN", "ref": "env:STOCK_API_TOKEN"}]
}
```

The gate runs the product's suite as for any product. The road's checks fail a capability whose
declaration is not valid, whose job lacks `run` or a declared tool's function, or that no longer serves
its declared faces (or serves one it did not declare).

### 4. Deliver it

At `explore` maturity `rihmasto run` delivers it on the built-in local preview road. Then:

```bash
rihmasto capability check <pid>          # the declaration at the release, as the pack judges it
rihmasto pack <pid>                      # the capability pack: its "runtime" section is the declaration
```

The pack's `runtime` says `declared: true` with the trigger, the faces, the tools, the gateway
workloads its model roles call, the integrations and the **names** of its secrets: never a value and
never where a value is kept. The declaration is part of the pack's hash, so changing it is a new pack
version, and the pack is valid only while its acceptance holds.

### 5. Reach it

Over MCP from your own AI assistant, as a server it starts:

```json
{"mcpServers": {"shipment-digest": {"command": "rihmasto",
  "args": ["--home", "/path/to/factory-home", "capability", "serve", "<pid>", "--face", "mcp"]}}}
```

Its tools are two reads, `capability_describe` and `capability_runs`, and the capability's own
declared tools, in that order, with the pack's version in `_meta`. Nothing in it decides or approves.

Over HTTP on this machine:

```bash
rihmasto capability serve <pid> --face http --port 8090          # POST /capability/run, GET /capability/runs
rihmasto capability serve <pid> --face mcp --port 8090           # Streamable HTTP at POST /mcp
rihmasto capability serve <pid> --face openai --port 8090        # POST /v1/chat/completions
```

`serve` takes the latest delivered release (or `--release N`), checks out its revision, writes its pack
and a fresh status document beside it, and serves only on 127.0.0.1. Before any face answers, the pack
guard checks the pack's hash, the app and runtime files, the status and the smoke set: a pack whose
acceptance does not hold, or a withdrawn version, keeps every face at 503 (an error on MCP's stdio).
Each serve is recorded in the project's ledger as `capability_served`.

With `--schedule`, a scheduled capability also runs on its schedule while it is served. Only the flag
starts it: a `RIHMA_SCHEDULE` or `RIHMA_FACES` set in your shell is not passed on, and the ledger's
`capability_served` says whether the schedule runs.

### 6. Trigger it from another system

Declare a webhook trigger and the secret that verifies it:

```json
"trigger": {"kind": "webhook", "source": "stock", "secret": "DIGEST_HOOK_SECRET"},
"secrets": [{"name": "DIGEST_HOOK_SECRET", "ref": "env:DIGEST_HOOK_SECRET"}]
```

The other system posts to `POST /capability/trigger`, signed with
[Standard Webhooks](https://www.standardwebhooks.com/) (`webhook-id`, `webhook-timestamp`,
`webhook-signature`), the same scheme Rihmasto's own doorbell verifies. A delivery runs the capability
once; a replayed id is answered and not run again; a wrong signature, an old timestamp or a body over
64 KiB is refused, and a missing secret answers 503. The body reaches `run(trigger)` as
`trigger["input"]`: data from outside, never an instruction.

To run it on an event from Rihmasto itself, declare an event trigger
(`{"kind": "event", "types": ["rihma.signal.received"], "secret": "DIGEST_HOOK_SECRET"}`) and let IT
subscribe the capability to the relay:

```bash
rihmasto relay subscribe --sink webhook --url https://digest.example.org/capability/trigger \
  --secret-env DIGEST_HOOK_SECRET --type 'rihma.signal.*' --person Ilkka --persona it
```

An event of another type is taken and runs nothing.

### 7. Send its results home

Set `RIHMA_RESULT_URL` and `RIHMA_RESULT_SECRET` where it runs, and each run goes out as a CloudEvent
(`rihma.capability.ran`, its subject the run's id) signed with Standard Webhooks. Pointed at the
factory's own doorbell, a result becomes a signal in the delivery square:

```bash
rihmasto hooks add capability-results --scheme standard --secret-env CAP_RESULTS_SECRET --person Ilkka --persona it
python -m embed.webhooks --port 8791     # RIHMA_RESULT_URL=http://127.0.0.1:8791/hooks/capability-results
```

The run's result itself stays with the capability (`GET /capability/runs`, `capability_runs`); the
event carries its id, state and the result's sha256.

### 8. Offer it as a model through the gateway

A capability that declares the `openai` face is itself a model. Generate its gateway workload from the
pack and route a site's clients to it by name:

```python
from gateway.packs import agent_workloads, workloads_from_pack
workloads = {**workloads_from_pack(pack, "digest"), **agent_workloads(pack, "digest")}
# upstreams: {"digest": {"url": "http://127.0.0.1:8090/v1", "api_key_env": "DIGEST_FACES_TOKEN"}}
```

`python -m gateway.server --config gateway.json --check-pack capability-pack.json` then passes, and
names the drift when the gateway's workload routes elsewhere. The capability's guard still answers
first: while its pack does not check out, the gateway says no upstream answered.

### 9. Ship it to a site

An offline bundle (`kernel.bundle.export_bundle`) carries `compose.yaml` once the image is pinned by
digest. For a small capability it also sets, in its one service:

- `RIHMA_FACES` (the declared faces) and `RIHMA_SCHEDULE=on` for a scheduled capability;
- every declared secret, `RIHMA_FACES_TOKEN` (the bearer token the mcp, openai and http faces ask) and,
  for model roles, `RIHMA_GATEWAY_URL`, each as `${NAME:?...}`: Compose takes the value from the
  deployer's environment and refuses to start without it;
- `RIHMA_RESULT_URL` and `RIHMA_RESULT_SECRET`, optional;
- header lines that say how each face is reached, including MCP over stdio:
  `docker compose run --rm -T app python3 factory/faces.py --face mcp --stdio`.

### 10. Find it in the cockpit

Open the project's **Releases** tab. The capability pack shows **Runtime and faces**: what starts it,
its tools, model roles, integrations, secrets by name, each face and the command that serves it. Ask
Rihma "How is this capability reached?" and press **Take me there**.

## The runtime declaration

| Key | Required | What it says |
|---|---|---|
| `format` | yes | `rihma.runtime/1` |
| `name` | yes | lower-case letters, digits and hyphens: its MCP server name and its model name |
| `kind` | yes | `automation`, `workflow` or `agent` |
| `summary` | yes | one sentence, at most 300 characters |
| `trigger` | yes | `{"kind": "schedule", "every_minutes": 1..10080}`, `{"kind": "webhook", "secret": NAME, "source": id}`, `{"kind": "event", "types": ["rihma...."], "secret": NAME}` or `{"kind": "manual"}` |
| `faces` | yes | distinct, from `mcp`, `openai`, `http`, `embed` |
| `tools` | no | `name`, `description`, `effect` (`read` or `write`), `input` (a JSON Schema object). No tool is named for approve, decide, delete, deploy, merge, push, grant or trust: deciding stays with people |
| `model_roles` | no | `role`, `workload` (the gateway workload it calls), `class` (interactive, batch, specialist), `data_class`, `model` (the model it was accepted with) |
| `integrations` | no | `system`, `via` (mcp, api, webhook, relay, database, file, queue), `purpose`, `writes`, `secrets` (declared names) |
| `secrets` | no | `name` (an environment variable's name) and `ref`: `env:NAME`, `os:NAME` or `gnomon:NAME`. Never a value: a string shaped like a live token anywhere in the file is a problem (a token's prefix counts where a word starts, so `desk-assistant` is a name) |
| `embed` | with the embed face | `{"origins": ["https://..."]}` (http only for localhost) |
| `timeout_seconds` | no | 1 to 600, default 60: a run that takes longer is recorded as timed out |
| `data_class` | no | public, internal (the default), confidential, restricted |

Every problem names its JSON path, for example `/trigger/secret: expected the name of a secret
declared under /secrets`.

## The faces

| Face | Paths | Who may call it |
|---|---|---|
| `mcp` | stdio (`python3 factory/faces.py --face mcp --stdio`); `POST /mcp` | anyone who can reach it; with `RIHMA_FACES_TOKEN` set, a bearer token |
| `openai` | `GET /v1/models`, `POST /v1/chat/completions` (model: the capability's name; no streaming) | as above |
| `http` | `POST /capability/run`, `GET /capability/runs` | as above |
| `embed` | `GET /embed/widget.js`, `POST /embed/messages` | the declared origins only |
| trigger | `POST /capability/trigger` | a delivery signed with the trigger's secret |

A request with an `Origin` that is not declared is refused on every face. A face the declaration does
not name, or that `RIHMA_FACES` or `--face` narrows away (each narrows; neither widens the other),
answers 404, and MCP over stdio answers every request with JSON-RPC error -32001 and lists no tool.
The openai face counts no tokens: its answers carry `"usage": null` and `"rihmasto": {"usage": "not
measured"}`, and the gateway records them as not measured, never as zeros.
`app.job.chat(messages)` answers the chat faces when the product has it;
otherwise a chat turn is a run with the last user message as its input. A model role is reached with
`factory.faces.model(role, messages)`, which asks the gateway workload the declaration names at
`RIHMA_GATEWAY_URL`.

## What is recorded

D-0017 asks every path to leave the same trace. For a small capability:

- **Who asked, what was assumed, who decided:** the intake, the panel's questions and the answers or
  assumptions, the spec's provenance, the gate's verdicts and any person's decisions, in the project's
  ledger, as for every project.
- **What proves it:** the capability pack pins the declaration's hash with the contract, the product,
  the faces' files and the acceptance.
- **Each serve:** `capability_served` records the local user who served it, the face, whether its schedule runs, the pack's status
  and on whose word it holds (the acceptance, or the person who withdrew it), what was assumed (who can
  reach it, which declared secrets this environment lacks) and the pack's and declaration's hashes.
- **Each run** is kept by the capability itself (`DATA_DIR/capability-runs.jsonl`) and, when a receiver
  is set, goes out as a signed event; the factory's doorbell records `hook_received`. Rihmasto is not
  the system of record for operational telemetry (D-0017): runs stay with the capability.

## What is built and what is planned

**Built** (FR-SC1 to FR-SC6, proven by [tests/test_small_capabilities.py](../../tests/test_small_capabilities.py)):

- the automation profile and the capability template, built through the gate and delivered on the
  local preview road;
- the runtime declaration, judged deterministically at the gate, in the pack and in the image;
- MCP over stdio and Streamable HTTP (initialize, ping, tools/list, tools/call; protocol revisions
  2025-11-25, 2025-06-18 and 2025-03-26; `server/discover` answers "method not found"), the
  OpenAI-compatible chat, the website embed and HTTP, each behind the pack guard, which the image and
  every face share;
- the trigger path: verified webhooks and relay events, a schedule, and results out as signed events
  the factory's own doorbell accepts;
- `rihmasto capability check` and `rihmasto capability serve`, with the `capability_served` trace;
- the faces in `compose.yaml`, and the gateway workload that routes to the capability as a model, with
  `--check-pack` covering it;
- the **Runtime and faces** section of the Releases tab, and its place in the assistant's map.

**Planned:**

- MCP 2026-07-28 (stateless `server/discover`), an A2A card, and publishing (`server.json`, `.mcpb`);
- streaming answers on the chat faces, and a token per client instead of one shared token;
- the schedule on the factory's own local road (today it runs where the capability is served with
  `--schedule`, or in Compose);
- the builder's envelope naming the capability's files (today the template's README and `app/job.py`
  say how to fill them in);
- rate limits on the faces, and a site's choice to refuse, hold or defer when the guard fails;
- dedicated templates for the agent and ops-agent profiles, which still build on the web-service
  template.
