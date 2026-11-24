# Paved roads: where a product runs, and how IT configures it

Status: v1, 22 Nov 2026; the delivery lifecycle (stage, security gate, holdout twin) 23 Nov 2026;
the road's platform facts and signed holdout steps 23 Nov 2026.
Code: `kernel/roads.py`, `kernel/deliver.py`, `kernel/operate.py`, `kernel/holdouts.py`.

The factory deploys a product only to a **paved road** that IT has configured in advance. A road
records the kind of target, the environments it serves, the identity it deploys as, and the
rules it keeps (region, TLS, egress). If a delivery needs a road that is missing or not
configured, the factory opens a `road` card for IT in the Inbox and deploys nothing. It never
guesses a target.

## Configuring a road

The roads live in one file, `paved_roads.json`, in the factory home (`var/paved_roads.json` by
default, or `$GNOMONFACTORY_HOME/paved_roads.json`). IT edits it, then decides the waiting
`road` card `configured` (or `declined`). The next `deliver` re-reads the file.

```json
{
  "schema": "gnomonfactory.paved_roads/1",
  "roads": {
    "team-docker": {
      "kind": "docker",
      "configured": true,
      "owner": "IT: Jaana",
      "environments": ["demo", "staging", "production"],
      "bind": "127.0.0.1",
      "ports": {"production": 18080},
      "rules": {"region": "on premises", "tls": "terminated by the host's reverse proxy",
                "egress": "none"},
      "canary": {"tolerance": 0.02, "min_sample": 20, "probe_rounds": 3}
    },
    "azure-prod": {
      "kind": "azure-containerapps",
      "configured": false,
      "environments": ["production"],
      "identity": "/subscriptions/<sub>/resourceGroups/rg-gf/providers/Microsoft.ManagedIdentity/userAssignedIdentities/gf-deployer",
      "subscription": "<sub>",
      "resource_group": "rg-gf",
      "environment": "cae-gf",
      "registry": "gfacr.azurecr.io",
      "storage": "gf-data",
      "rules": {"region": "swedencentral", "regions": ["swedencentral"], "tls": "required",
                "ingress": {"external": true, "transport": "auto"},
                "egress": {"default": "deny", "allow": []}},
      "secrets": [{"name": "API_TOKEN", "ref": "https://kv-gf.vault.azure.net/secrets/api-token"}]
    }
  },
  "maturity": {
    "demo": "team-docker",
    "pilot": "team-docker",
    "production": {"staging": "team-docker", "production": "azure-prod"}
  }
}
```

- **`maturity`** names the road for each maturity: one road for every environment, or a map
  from environment to road. A project can name its own road in `project.json` (`paved_road`).
  An explore preview needs nothing here: the built-in `local-preview` road runs it as a local
  process on the kernel's machine.
- **`configured: true`** is IT's word that the road is ready. Without it the road is refused.
- **`environments`** limits what a road serves (`preview`, `demo`, `staging`, `production`).
- **Secrets** are references only: a name and where the value lives (`ref`). A package never
  holds a secret value. If a road carries a `value`, the value is dropped from every package and
  the package fails validation, which stops the deployment. A `ref` of the form
  `env:<VARIABLE>` names a variable in the kernel host's environment; the holdout runner reads
  such a secret to sign a request (see [Signed holdout steps](#signed-holdout-steps)), and reads
  no other kind of reference.
- **Shadow** (optional): `"shadow_target": "live"` replays traffic against the live production
  slot instead of a fresh twin of the current release (the default); then
  `"shadow_safe": ["production"]` says the live slot may also take replayed writes. A live slot
  records the reads replayed to it in its own traffic log, which is why `twin` is the default.
- **`volatile`** (optional) lists the JSON keys shadow ignores; the default is `id`, `created`,
  `updated`, `at`, `version`.
- **`integrations`** (optional) binds the data systems a product declares (a database, a warehouse,
  cloud storage, an ERP) to an endpoint and secret references, for every environment or per
  environment. IT approves each binding on a `road` card before delivery, and the deploy package and
  the Compose file carry its settings and secret references: see
  [guides/data-integrations.md](guides/data-integrations.md).
- **`sandbox: true`** (optional) is IT's word that a road for `preview` or `demo` is a test sandbox:
  an autopilot run may deliver there on its own. The built-in `local-preview` road is one; staging
  and production never are, whatever a road says
  ([autopilot and tracking](guides/autopilot-and-tracking.md)).

### Road kinds

| Kind | What it does | Ready when |
|---|---|---|
| `local-process` | Runs the product from a checkout of the product repository at the release's revision, on a free loopback port. Data and the traffic log live under `envs/<env>/` in the project folder (a twin's under `envs/<env>/twin/`, removed when the twin stops). | configured |
| `docker` | `docker build` per revision (`gf-<pid>:<rev12>`), `docker run -d` per environment and slot (`gf-<pid>-<env>-<slot>`), a port published on `bind`, a named volume for `/data` (`gf-<pid>-<env>-data`; a twin or candidate gets its own, removed when it stops), `APP_VERSION` and `TRAFFIC_LOG=/data/traffic.jsonl` set, with each approved integration's settings, and its `env:` credentials by name only (`--env NAME`, the value in the docker CLI's environment). Uses the docker CLI on the kernel's host. | configured, and `docker` is on PATH |
| `azure-containerapps` | Renders an Azure Container Apps YAML (one replica, TLS-only ingress, the image tagged with the revision, Key Vault secret references, a user-assigned identity, an Azure Files volume) and the `az` command plan, and validates both. It hosts no twin for the holdouts. | configured, an `identity`, subscription, resource group, environment, registry and `rules.region`, and `az` on PATH |

A **slot** is one running copy in an environment: `current` is what people use, `candidate` is a
new release beside it in production, and `twin` is a disposable copy on its own empty data. The
shadow replays traffic against a twin of the current release, and the holdouts run against a twin
of the release being delivered (see below).

Every deployment goes through a **deploy package** (`releases/<n>/package-<env>-<slot>.json`):
the artifact (image or process reference), the environment settings, the secret references,
the road's rules and the target. It is validated before anything runs; the deploy gate card
shows it to IT.

Both runnable roads start the product with `python -c "from app.server import main; main()"`.
The template's own `python -m app.server` (and its Dockerfile `CMD`) loads `app/server.py`
twice, so the product's routes register on a copy that does not serve: every route but
`/health` answers 404. A road may set its own `command`.

## The road's platform facts

Built 23 Nov 2026 (FR-DF1), after a live run in which the analyst wrote a "localhost-only"
requirement, the builder bound 127.0.0.1 inside the container and replaced `/health`, every test
passed, and delivery failed its health check with an empty `logs`. The road owns three facts,
whatever a spec says (`kernel.roads.ROAD_FACTS`):

| Fact | What it means |
|---|---|
| bind | The service listens on all interfaces inside its container: it binds the address in `HOST` (default `0.0.0.0`) and the port in `PORT`. Bound to 127.0.0.1 inside a container, nothing outside it can reach the service. |
| exposure | Who can reach the service is the road's job: a loopback publish (`bind`), a reverse proxy or an ingress, with the road's TLS and egress rules. "Localhost-only" is met by the road, not by the code. |
| health | `GET /health` answers 200 with `{"status": "ok", "version": <APP_VERSION>}`, and delivery checks that version before anyone uses the release. |

Where each fact is said and checked:

- **The analyst's spec prompt** states them, and says that a wish for less exposure goes to
  `out_of_scope` as the road's job, never into a requirement (`kernel/spec.py`).
- **The builder's envelope** states them with what they mean for the code: never set `HOST` or
  bind loopback (not in `app/__init__.py` either), never register, replace or change
  `GET /health` (`kernel/dispatch.py`).
- **The road-contract tests.** Every product starts with `tests/test_road_contract.py`
  (`kernel/scaffold.py`): `/health` with the release version, the bind from `HOST` with `0.0.0.0`
  as the default (the service is started as the roads start it, with the server class replaced,
  so nothing is bound), the `HOST` and `PORT` the road gives, and no loopback `HOST` in the
  Dockerfile. The road owns the file: it is a protected path (`kernel/lanes.py PROTECTED`), so a
  cell's change that edits or removes it is a `protected` violation at the gate and never merges,
  and a workspace submission that touches it is refused. Gnomon's `write_allow` has no exclusions,
  so the builder's `tests/**` scope lets the write tool reach the file; the gate's check is what
  refuses the change. The product surface's `system.md` says the file is read-only. No change to
  Rihmasto's own `.gnomon/` is needed, so nobody runs `gnomon trust` for this; a product lane an
  owner had trusted for in-loop verify needs that trust again after its surface is recompiled.
- **The plan review** names, by rule and with no model, every requirement or criterion that
  wants the service bound to loopback, a port of its own, or `/health` without the release
  version (`kernel.roads.road_conflicts`). The plan card's title counts them, its body and payload
  list each with the fact it contradicts, `spec.md` lists them, the ledger records
  `spec_road_conflicts`, and the plan waits for a person **at any maturity** while one stands. A
  probe that names `/health`'s latency is no conflict.

  The rules read each clause (a sentence, or its part before a `;`) on its own, so "only" in one
  sentence never pairs with `localhost` in another (FR-DF1-AC-5). They find:

  | Fact | Found | Not a conflict |
  |---|---|---|
  | bind | a loopback address (127.0.0.1, `localhost`, `loopback`, `::1`) with a word that restricts the service to it: "localhost-only", "binds 127.0.0.1", "Set HOST to 127.0.0.1", "only be accessible from localhost", "restrict (or limit) access to localhost", "not exposed beyond localhost", "serve the app from 127.0.0.1" | a loopback address the service calls out to ("calls the model server at localhost:11434"): egress, the road's egress rule |
  | port | the service on a port other than the road's 8080: "listens on port 5000", "listens on 0.0.0.0:5000", "Set PORT to 5000" | another component's port ("the database runs on port 5432", "Redis listens on port 6379"), or a port the service connects to |
  | health | `/health` (or the health endpoint) without the release version: "must not disclose (expose, reveal, show) the version", "without the version", `{"status": "ok"}` alone, an empty body, 204, plain text | `/health`'s latency; an answer that names the version |

  The rules are fixed words, not a model, so a new phrasing can still pass them. The
  road-contract tests catch such a product at build; the plan review is the earlier, cheaper
  check.
- **The local-process road** starts the product with `HOST=127.0.0.1`, so a preview listens on
  loopback only, whatever the kernel's own environment holds.

**A failed health check says why.** When a deploy's health check fails, the release record's
deploy step keeps, beside the last answer (`last`):

| Road | `logs` / `log_tail` | `listening` | `diagnosis` |
|---|---|---|---|
| docker | the container's last 50 lines from both of its streams (`docker logs` gives the container's stderr on its own stderr, where a Python service writes) | the TCP sockets listening inside the container, read from `/proc/net/tcp` and `tcp6` with `docker exec` (the image needs no tool); "not measured" when the container cannot be read | "listens on loopback inside the container only", "nothing listens on port 8080", or "/health answered ... not the release version" |
| local-process | the process log's tail | whether the loopback port accepted a connection | a `/health` without the release version |

## What each maturity does

| Maturity | Delivery plan | Lands on | A person decides |
|---|---|---|---|
| `explore` | build_image, deploy:preview, smoke:preview | a local preview process | nobody |
| `demo` | build_image, deploy:demo, smoke:demo, holdouts:demo, owner_acceptance | the `demo` environment | the business owner accepts the demo (`approval`) |
| `pilot` | build_image, deploy:staging, smoke:staging, holdouts:staging, user_validation | `staging` | the users' validation (`validation`: accept, fix, change or keep) |
| `production` | the pilot plan, then deploy_gate, deploy_candidate:production, shadow:production, canary:production, promote:production | `production` | IT at the deploy gate (`deploy_gate`) |

- **Security gate**: before a release enters staging (`deploy:staging`) or production
  (`deploy_candidate:production`), delivery asks the security gate (`kernel/security.py`). An
  open finding at a blocking level holds the release: it waits, with `waiting_on` naming the
  findings (`SEC-1-1 (B602, Bandit, app/routes.py:14)`) and `blocked` saying it is the security
  gate, and nothing is deployed. There is no card for it: the release goes on at the next
  `deliver` once a scan no longer reports the finding, or a person with the `it` or
  `compliance` persona accepts the risk until a date (`kernel.security.accept_risk`). In demo and
  preview the verdict is only recorded in the deploy step. "Not measured: no security scan"
  never holds a release; it is recorded in the step too.
- **Smoke**: `/health` answers 200 from the release's own version.
- **Holdouts**: every scenario in the holdout custody runs over HTTP against a **twin** of the
  environment: the same revision, deployed as the `twin` slot on its own empty data, and stopped
  with its data when the scenarios are done. Scenarios write their own data, and the slot end
  users try never receives it. A road that cannot host a twin (Azure Container Apps today) runs
  them against the shared slot, and the release says so: "holdouts ran in the shared slot: this
  road has no twin". One failing scenario stops the release; its first failing step and the
  observed status and body are kept in the release record. A step that signs its request uses
  the secrets the environment's road names (below).
- **Validation**: `fix` or `change` stops the release and hands the card to the change loop.
- **Deploy gate**: only the `it` persona decides it. `refuse` stops the release.
- **Candidate**: the release starts beside the current one, with its own empty data.
- **Shadow**: the production traffic log is replayed against the current release and the
  candidate. Every response that differs is reported (`ops/shadow/<n>.json`); a difference is
  not by itself a stop.
- **Canary**: the error rate (5xx answers and failed probes over the replayed and probe sample)
  of the candidate against the current. Above the current's rate plus the tolerance, the
  candidate is rolled back: stopped, the current kept, the rollback recorded
  (`ops/rollbacks.jsonl`) and an `incident` card opened. No person is needed for it.
- **Promotion**: the current slot is replaced by the release, on production's data.

### Signed holdout steps

Built 23 Nov 2026 (FR-DF2), after a live run whose spec required signed carrier webhooks: the
holdouts reached the right route and got 401 "missing HMAC signature", because a scenario had no
way to sign. A step may now carry `sign` (`kernel/holdouts.py`):

```json
{"method": "POST", "path": "/carriers/a/events", "body": {"event": "delivered"},
 "sign": {"header": "X-Carrier-Signature", "secret": "CARRIER_WEBHOOK_SECRET", "prefix": "sha256="},
 "expect_status": 202}
```

- The runner sends the body as exact JSON bytes and puts the hex HMAC-SHA256 of those bytes,
  keyed by the secret, in that header (after `prefix`, if given).
- `secret` is the **name** of a setting of the environment: a secret the environment's road names
  in `paved_roads.json`, for example `{"name": "CARRIER_WEBHOOK_SECRET", "ref": "env:CARRIER_TEST_SECRET"}`.
  Delivery reads the value from that `env:` reference when the holdouts run, and keeps it in
  memory only. A scenario never holds a value: one the holdout author wrote in `secret` is dropped
  before the scenario enters the custody.
- A name the environment does not give, a reference the runner cannot read (a vault URL, an unset
  variable), or a malformed `sign` makes the scenario **not measured**, never failed, and its
  reason says which. The release record and the ledger name the header and the secret's name,
  never the value or the signature.
- What counts as malformed, refused before anything is sent and before the scenario enters the
  custody (FR-DF2-AC-3): a `header` that is not a plain name (a letter, then letters, digits and
  `-`), or one HTTP itself sends or the runner sets (`Host`, `Content-Length`, `Content-Type`,
  `Transfer-Encoding`, `Connection`, any `Proxy-*` and the like), which would replace what frames
  or routes the request; a `prefix` that is not at most 32 visible ASCII characters, since a line
  break in it would start a header of its own; an algorithm other than `hmac-sha256`.
- Each scenario runs guarded (`kernel.holdouts.run_guarded`): one the runner cannot send (a step
  `http.client` refuses, a step that is not an object) is **not measured**, named by the error's
  kind only (its text may quote what the step sent), and the other scenarios still run. Before
  the fix of 23 Nov 2026 such a scenario stopped the holdouts step with a traceback, and the
  scenarios after it never ran.
- The holdout author learns the option in the interface section of its prompt, with the names
  (never the values, never where they live) of the secrets the project's roads give.
- Custody is unchanged: scenarios stay in `<home>/holdouts/<project>/`, and the builder's envelope
  names no scenario, header or secret.
- Still to come: the docker road does not pass a road secret's value to the product's container yet
  (packages carry references only; a declared integration's `env:` credential is passed by name since
  FR-DS5, see the [data integrations guide](guides/data-integrations.md)), so a docker product reads its test secret from its own
  configuration; a local-process product inherits the kernel's environment. Probes (`operate.tick`)
  do not sign.

`deliver` stops at each card and returns `waiting`. Call it again after the person decided: it
goes on from there. If main moves while a release waits, that release is superseded and its
open cards are withdrawn, because an approval is for one revision.

## What delivery tells the rest of the factory

The project's stage follows what was delivered, and each move is a `stage_changed` record in
the ledger:

- a release that lands in preview, demo or staging puts the project at stage 6, user
  validation;
- a release promoted to production puts it at stage 7 and sets `released`.

The capability catalogue reads its state from the releases and from what runs, never from the
stage alone:

| State | When |
|---|---|
| `in_use` | production's current slot runs a release (or an adopted solution is monitored where it runs) |
| `pilot` | a release is validated, or waits for its validation, on staging |
| `trying` | a demo is accepted or waits for its acceptance, or a preview is done |
| `building` | stage 5 or later, with no release that got that far |
| `shaping` | before stage 5 |

The furthest any release got counts: a later release that failed does not undo a validation.
The delivery square's `in_production` counts the same projects as `in_use`: those whose
production slot is current, and adopted solutions monitored where they already run.

## Operation

`operate.tick(project)` probes production: `/health` and its latency, and every holdout
scenario of kind `probe`. Results go to `ops/probes.jsonl`. A failing probe opens one
`incident` card per release and environment; later failures add occurrences to it
(`ops/incidents.json`) rather than new cards.

## What is real and what is not

- **Real and tested**: the `local-process` road end to end (real processes, real HTTP, real
  holdouts in a twin, signed holdout steps, the security gate holding a release, shadow, canary,
  promotion and rollback), the docker command construction (against a fake CLI, including a twin's
  own container and volume, and the log tail, listening sockets and diagnosis of a failed health
  check), the road-contract tests and the plan review's road conflicts, and the Azure package
  rendering and validation.
- **Real, not exercised by the tests**: the `docker` road against a docker daemon (a holdout
  twin on docker included), and the `azure-containerapps` deployment. Azure needs IT to
  configure the road with an identity, and the `az` CLI on the deploying host; neither exists
  today. Its YAML is checked by reading it
  back with the factory's own reader, not by Azure.
- **Not in v1**: injecting a road secret's value into local or docker products (packages carry the
  references only; a declared integration's `env:` credential is the exception, FR-DS2 and FR-DS5), traffic splitting by weight, and reading an Azure product's traffic log
  (shadow reports `not measured` there, and the canary uses probes alone).
