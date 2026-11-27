# Deploying on paved roads

Rihma deploys a product only to a **paved road**: a target IT configured in advance. A road
records its kind, the environments it serves, the identity it deploys as, and the rules it keeps
(region, TLS, egress). When a delivery needs a road that is missing or not configured, Rihma opens
a `road` card for IT and deploys nothing. It never guesses a target.

The full reference is [paved-roads.md](../paved-roads.md). This page is the short version.

## The maturity decides the plan

| Maturity | Plan | Lands on | Who decides |
|---|---|---|---|
| `explore` | build, deploy, smoke | a local preview process | nobody |
| `demo` | build, deploy, smoke, holdouts, the owner's acceptance | `demo` | the business owner accepts the demo |
| `pilot` | build, deploy, smoke, holdouts, user validation | `staging` | end users validate: accept, fix, change or keep |
| `production` | the pilot plan, then IT's deploy gate, a candidate, shadow, canary, promotion | `production` | IT at the deploy gate |

`explore` needs no configuration: the built-in `local-preview` road runs the product as a local
process on a free loopback port. Every other maturity needs a road in `paved_roads.json`.

## IT configures a road

The roads live in one file in the factory home: `<home>/paved_roads.json`. IT edits it, then
decides the waiting `road` card **configured** (or **declined**). The next delivery re-reads the
file.

```json
{
  "schema": "gnomonfactory.paved_roads/1",
  "roads": {
    "team-docker": {
      "kind": "docker",
      "configured": true,
      "owner": "IT: the platform team",
      "environments": ["demo", "staging", "production"],
      "bind": "127.0.0.1",
      "rules": {"region": "on premises", "tls": "terminated by the host's reverse proxy", "egress": "none"},
      "canary": {"tolerance": 0.02, "min_sample": 20, "probe_rounds": 3}
    }
  },
  "maturity": {"demo": "team-docker", "pilot": "team-docker", "production": "team-docker"}
}
```

| Road kind | What it does | Ready when |
|---|---|---|
| `local-process` | Runs the product from a checkout at the release's revision, on loopback. | configured |
| `docker` | An image per revision, a container per environment and slot, a named volume for data. | configured, and `docker` is on PATH |
| `azure-containerapps` | Renders an Azure Container Apps YAML and an `az` command plan, and validates both. | configured, with an identity, subscription, resource group, environment, registry and region, and `az` on PATH |
| `gcp-cloudrun` | A Cloud Run service, or a Cloud Run job Cloud Scheduler runs on a schedule: the YAML, the scheduler job and the exact gcloud commands, rendered, validated and run ([gcp.md](gcp.md)). | configured, with projects, a region, an Artifact Registry repository, a deploying and a runtime identity, and `gcloud` on PATH and signed in |

IT configures a Google Cloud road in the cockpit (**Settings > Paved roads**) or with `rihmasto road
configure`; every other kind is edited in the file. Settings and `rihmasto road list` show each road, ready
or exactly what is missing, and a project's **Releases** view shows where each environment of its plan
deploys. [gcp.md](gcp.md) walks through a scheduled agent on Cloud Run Jobs that reads recordings from a
Google Drive folder and writes transcripts back.

`maturity` maps each maturity to a road, or to a map from environment to road. A project may
name its own road in `project.json` (`paved_road`).

**Secrets are references only:** a name and where the value lives. A deploy package never holds a
secret value. A road that carries one has it dropped, and the package fails validation, which
stops the deployment.

## IT's deploy gate

At `production`, the release first runs the whole pilot plan on `staging`. Then it stops at a
`deploy_gate` card. Only the **IT** persona decides it: **approve** or **refuse**. The card shows
the deploy package (the artifact, the environment settings, the secret references, the road's
rules and the target), so IT approves exactly what will run.

Business acceptance and the deploy gate never stand in for each other. A business owner who
accepted a demo has not approved a production deployment.

After approval:
1. **Candidate:** the release starts beside the current one, with its own empty data.
2. **Shadow:** the production traffic log is replayed against both. Every response that differs
   is reported; a difference alone is not a stop.
3. **Canary:** the candidate's error rate (5xx answers and failed probes) is compared with the
   current one. Above the current rate plus the tolerance, the candidate is rolled back with no
   person needed, and an incident card opens.
4. **Promotion:** the release replaces the current one, on production's data.

## Run it

```bash
rihma run <project>               # builds, then delivers by maturity, stopping at each card
rihma deliver <project>           # delivery only; run again after a person decides
rihma deliver <project> --new     # a new release even if this revision was delivered
rihma operate <project>           # one operations round: probes, incidents
```

`deliver` stops at each card and returns `waiting`. If main moves while a release waits, that
release is superseded and its open cards are withdrawn, because an approval is for one revision.

A project's **Destinations** tab (`rihmasto destinations <pid>`) shows every environment it is delivered
to, with the release that runs there, its URL and its health, beside the data, channels and registries it
goes to; **Deliver to test** and **Promote to production** start the delivery from there, and
`rihmasto publish` pushes a release's image to a registry, test first and production through IT's gate
([destinations.md](destinations.md)).

## What is real today

- **Real and tested end to end:** the `local-process` road, with real processes, HTTP, holdouts,
  shadow, canary, promotion and rollback.
- **Real, tested against a fake CLI:** the `docker` road's commands.
- **Rendered and validated, never deployed:** `azure-containerapps`. It needs IT to configure the
  road with an identity, and the `az` CLI on the deploying host.
- **Rendered, validated and tested end to end against a fake gcloud on PATH; not yet run against a real
  Google Cloud project:** `gcp-cloudrun`, a service or a scheduled job: Cloud Build, the test project
  first, the deploy gate, a candidate revision promoted by traffic or a job's image and schedule, rollback,
  and a job's executions read into its probe. It needs IT to set up the projects and service accounts,
  configure the road, and sign `gcloud` in on the deploying host ([gcp.md](gcp.md)).
- **Not built:** injecting secret values into local or docker products, traffic splitting by
  weight, and reading an Azure or Cloud Run product's traffic log (shadow reports "not measured" there).
