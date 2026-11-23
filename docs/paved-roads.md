# Paved roads: where a product runs, and how IT configures it

Status: v1, 22 Nov 2026; the delivery lifecycle (stage, security gate, holdout twin) 23 Nov 2026.
Code: `kernel/roads.py`, `kernel/deliver.py`, `kernel/operate.py`.

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
  the package fails validation, which stops the deployment.
- **Shadow** (optional): `"shadow_target": "live"` replays traffic against the live production
  slot instead of a fresh twin of the current release (the default); then
  `"shadow_safe": ["production"]` says the live slot may also take replayed writes. A live slot
  records the reads replayed to it in its own traffic log, which is why `twin` is the default.
- **`volatile`** (optional) lists the JSON keys shadow ignores; the default is `id`, `created`,
  `updated`, `at`, `version`.

### Road kinds

| Kind | What it does | Ready when |
|---|---|---|
| `local-process` | Runs the product from a checkout of the product repository at the release's revision, on a free loopback port. Data and the traffic log live under `envs/<env>/` in the project folder (a twin's under `envs/<env>/twin/`, removed when the twin stops). | configured |
| `docker` | `docker build` per revision (`gf-<pid>:<rev12>`), `docker run -d` per environment and slot (`gf-<pid>-<env>-<slot>`), a port published on `bind`, a named volume for `/data` (`gf-<pid>-<env>-data`; a twin or candidate gets its own, removed when it stops), `APP_VERSION` and `TRAFFIC_LOG=/data/traffic.jsonl` set. Uses the docker CLI on the kernel's host. | configured, and `docker` is on PATH |
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
  observed status and body are kept in the release record.
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
  holdouts in a twin, the security gate holding a release, shadow, canary, promotion and
  rollback), the docker command construction (against a fake CLI, including a twin's own
  container and volume), and the Azure package rendering and validation.
- **Real, not exercised by the tests**: the `docker` road against a docker daemon (a holdout
  twin on docker included), and the `azure-containerapps` deployment. Azure needs IT to
  configure the road with an identity, and the `az` CLI on the deploying host; neither exists
  today. Its YAML is checked by reading it
  back with the factory's own reader, not by Azure.
- **Not in v1**: injecting secret values into local or docker products (packages carry the
  references only), traffic splitting by weight, and reading an Azure product's traffic log
  (shadow reports `not measured` there, and the canary uses probes alone).
