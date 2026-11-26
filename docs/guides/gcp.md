# Google Cloud: Cloud Run services, scheduled jobs and Google Drive

How a capability Rihmasto builds runs in an organisation's own Google Cloud, as a Cloud Run service or as a
Cloud Run job that Cloud Scheduler runs on a schedule, and how it reads from and writes to a Google Drive
folder. The worked pattern is the one a team asked for: **a scheduled agent on Cloud Run Jobs that reads new
recordings from a Drive folder and writes transcripts back.**

| Part | State |
|---|---|
| The `gcp-cloudrun` paved road: IT's configuration, checked whole; the service and job YAML, the Cloud Scheduler job and the exact gcloud commands, rendered and validated | built, tested |
| Delivery: Cloud Build, the test project first, the deploy gate, then production; a service's candidate revision, promotion and rollback by traffic; a job's single execution as its smoke check, its schedule, its previous image kept for rollback | built, **tested against a fake gcloud on PATH** |
| A job's last executions read into its probe; a failed execution opens an incident card | built, tested against a fake gcloud |
| The Google Drive connector (`app/gdrive.py`): new files since a cursor, download, upload, credentials by name | built, tested against a Drive v3 stand-in on 127.0.0.1 |
| Settings > Paved roads and Integrations, a project's "Where it deploys" card | built, tested in a browser |
| A run against a real Google Cloud project and a real Drive folder | **not yet**: see [What a first real run needs](#what-a-first-real-run-needs) |

Rihmasto runs `gcloud` only on the deploying host, only when IT marked the road configured, the road's entry
is whole, and `gcloud` is on PATH and signed in. Otherwise the road says exactly what is missing and
nothing is built or deployed. It never creates a Google Cloud project, a service account or a role: IT does
that with its own tools, and the owner grants any trust.

## The pattern

```
Cloud Scheduler (cron, time zone, retries)
   |  calls the Run API as the scheduler's service account
   v
Cloud Run job  (the capability's image, from IT's Artifact Registry repository)
   |  runs as the road's runtime service account (no key anywhere)
   |-- lists new recordings in Drive folder A   (shared with the runtime service account: Viewer)
   |-- transcribes each one                     (a model: see "Where the audio goes")
   |-- uploads a transcript to Drive folder B   (shared with the runtime service account: Editor)
   '-- keeps its cursor in folder B, so the next run picks up only what is new

Rihmasto: builds it, gates it, runs it once in the test project, stops at IT's deploy gate, deploys
it to production with its schedule, reads its executions, and opens an incident when one fails.
```

## 1. IT prepares Google Cloud (once, with its own tools)

Rihmasto does none of this. IT, with the people who own the projects:

1. **Projects.** A test project and a production project (they may be one project; the job's name carries
   the environment either way). In each, enable the Cloud Run, Cloud Build, Artifact Registry, Cloud
   Scheduler, Secret Manager and Google Drive APIs.
2. **An Artifact Registry repository** for images, such as `europe-north1-docker.pkg.dev/<build-project>/rihmasto`.
3. **Three service accounts:**
   - the **deployer**, which Rihmasto impersonates on every gcloud call: Cloud Run Admin, Service Account
     User on the runtime account, Cloud Build Editor, Artifact Registry Writer and Cloud Scheduler Admin;
   - the **runtime** account the job runs as: Secret Manager Secret Accessor on the secrets it needs. It
     needs no Drive role: Drive access is given by sharing the folders with it;
   - the **scheduler** account Cloud Scheduler calls the job as: Cloud Run Invoker on the job.
4. **The deploying host** (where Rihmasto runs): `gcloud` installed and signed in as a person or account
   allowed to impersonate the deployer (Service Account Token Creator), or a workload identity federation
   credential file, which holds no secret.
5. **The network:** a Serverless VPC Access connector (or a VPC network and subnet) when the job's egress
   must go through IT's VPC.

## 2. IT configures the road

In the cockpit: **Settings > Paved roads > Configure a Google Cloud road**, signed as IT. Or from a file:

```bash
rihmasto road configure company-gcp --file road.json --maturity pilot --maturity production \
    --person "Ilkka" --persona it
```

`road.json`, the entry Rihmasto writes into `paved_roads.json` once it is whole:

```json
{
  "kind": "gcp-cloudrun",
  "configured": true,
  "owner": "IT: the platform team",
  "environments": ["staging", "production"],
  "projects": {"staging": "example-test-123", "production": "example-prod-123"},
  "region": "europe-north1",
  "repository": "europe-north1-docker.pkg.dev/example-build-123/rihmasto",
  "deployer": {"service_account": "deployer@example-ops-123.iam.gserviceaccount.com"},
  "runtime_service_account": "transcriber@example-prod-123.iam.gserviceaccount.com",
  "workload": "job",
  "schedule": {"cron": "0 6 * * 1-5", "time_zone": "Europe/Helsinki", "retries": 2,
               "service_account": "scheduler@example-prod-123.iam.gserviceaccount.com",
               "environments": ["production"]},
  "job": {"max_retries": 1, "timeout_seconds": 3600},
  "network": {"egress": "all-traffic", "vpc_connector": "rihmasto-connector"},
  "resources": {"cpu": "2", "memory": "4Gi"},
  "env": {"RECORDINGS_FOLDER": {"staging": "<test folder id>", "production": "<folder id>"},
          "TRANSCRIPTS_FOLDER": {"staging": "<test folder id>", "production": "<folder id>"}},
  "secrets": [{"name": "MODEL_API_KEY", "ref": "sm:model-api-key:latest"}],
  "rules": {"region": "europe-north1", "regions": ["europe-north1"],
            "tls": "required: Cloud Run serves HTTPS", "egress": "none: all traffic through IT's VPC"}
}
```

| Field | What it is |
|---|---|
| `project_id` or `projects` | one project, or one per environment |
| `region`, `rules.regions` | where it runs, and the regions IT allows |
| `repository` | the Artifact Registry repository Cloud Build pushes to |
| `deployer` | `{"service_account": ...}` (impersonated), `{"credential_file": ...}` (workload identity federation) or `{"ambient": true}` (the host's own login) |
| `runtime_service_account` | the identity the product runs as |
| `workload` | `service` (HTTP, the default) or `job` |
| `schedule` | a job's five-field cron in numbers, its time zone, Cloud Scheduler's retries, its service account, and the environments it is scheduled in (production by default: the test project runs it on demand) |
| `job` | `max_retries`, `timeout_seconds` and `command` (default: `app.job`'s `run({"kind": "schedule"})`, the small-capability template) |
| `network` | a service's `ingress` (`internal` by default), `egress` and the VPC connector or network |
| `env` | plain settings by name: one value, or one per environment |
| `secrets` | Secret Manager references by name: `sm:<secret>[:<version>]` or `projects/<p>/secrets/<s>[/versions/<v>]` |

**Checked whole first.** A missing identity, a project id or region Cloud Run does not take, a cron or time
zone Cloud Scheduler does not take, a secret with a value or outside Secret Manager, a secret-like name in
`env`, a variable Cloud Run sets itself (`PORT`), or `rules.egress` none without all traffic through a VPC:
each is named, and nothing is written. The factory's ledger records `road_configured` with who configured
it and the sha256 of the entry. Other kinds of road are edited in `paved_roads.json`
([deploying.md](deploying.md)).

`rihmasto road list` (and Settings) shows every road, ready or what is missing: "the gcloud CLI is not on
PATH on the deploying host", "gcloud is not signed in", or a gap in the entry.

## 3. The project: its road, workload and schedule

IT chooses where a project deploys, in the project's **Releases > Where it deploys > Choose the road**, or:

```bash
rihmasto road choose <pid> company-gcp --workload job --cron "0 6 * * 1-5" --time-zone Europe/Helsinki \
    --retries 2 --scheduler-account scheduler@example-prod-123.iam.gserviceaccount.com --person "Ilkka" --persona it
```

The project's choice (`cloudrun` in project.json) overrides the road's workload and schedule for this
project only, and is checked as the road's own. `rihmasto road render <pid> --env production` shows exactly
what would run: the job's YAML, the Cloud Scheduler job, and every gcloud command, without running any.

## 4. The Drive connector

The product declares the folder as an integration, in its plan:

```bash
rihmasto integration declare <pid> --name recordings --kind gdrive --access read-write \
    --data-class confidential --purpose "reads new recordings and writes their transcripts" \
    --person "Aino" --persona product_owner
```

On Cloud Run the job needs **no credential**: it asks the metadata server for a token as the runtime
service account. For a run on a laptop, declare a credential by name too (`--credential RECORDINGS_TOKEN`,
an OAuth access token, or `RECORDINGS_KEY_FILE`, the path of a service account's JSON key); IT binds where
each lives. A gdrive declaration writes the requirement `INT-RECORDINGS`, and the product gets the paved
road's client as `app/gdrive.py`:

```python
import os
from app.gdrive import Drive

def run(trigger):
    drive = Drive.from_env("recordings")             # RECORDINGS_URL and RECORDINGS_ACCESS, set by the road
    source, target = os.environ["RECORDINGS_FOLDER"], os.environ["TRANSCRIPTS_FOLDER"]
    batch = drive.list_new(source, drive.load_cursor(target), mime_prefixes=("audio/", "video/"))
    done = 0
    for f in batch.files:
        name = f["name"].rsplit(".", 1)[0] + ".txt"
        if drive.find(target, name):                 # a rerun writes nothing twice
            continue
        drive.upload(target, name, transcribe(drive.download(f["id"])), "text/plain")
        done += 1
    drive.save_cursor(target, batch.cursor)
    return {"transcribed": done, "seen": len(batch.files)}
```

- **New files only.** `list_new` reads every page of the folder's files modified at or after the cursor's
  time, skips those the cursor saw at that very time, and returns the cursor to keep. The cursor is kept as
  a small file in the target folder, so a Cloud Run job, which has no disk of its own, picks up where it
  stopped.
- **Scopes.** Read: `drive.readonly`. Read-write: `drive.readonly` and `drive.file` (it may create files and
  change the files it created). An integration declared read never uploads.
- **Sharing.** In Drive, share the recordings folder with the runtime service account's email as a Viewer
  and the transcripts folder as an Editor (in a shared drive, add the account as a member).
- **Nothing is logged.** An error names the call and Drive's status, never a token or a file's content.
- **The binding.** On the road, IT binds the integration for each environment to `https://www.googleapis.com`
  and approves it on a `road` card ([data-integrations.md](data-integrations.md)). The test environment's
  folder ids are its own (`env` per environment above), so the test run never touches the real recordings.
- **At the gate** the product's tests run against a Drive v3 stand-in on loopback, seeded from
  `tests/standins/recordings.json` (`{"files": [{"name": ..., "parents": [...], "content": ...}]}`); a write
  to an integration declared read fails the gate.

## 5. Secrets: Secret Manager, by name

A model key lives in Secret Manager in the production project. IT creates it there; the road names it
(`{"name": "MODEL_API_KEY", "ref": "sm:model-api-key:latest"}`), the job gets it as the environment variable
`MODEL_API_KEY` through `valueFrom.secretKeyRef`, and the runtime service account needs Secret Accessor on
it. Rihmasto's records, the deploy package, the YAML and the ledger hold the name only.

## 6. Delivering: the test project first, then production through the gate

```bash
rihmasto deliver <pid>
```

1. **Build:** Cloud Build builds the image from the release's revision into the repository; the release is
   pinned by the digest Cloud Build reports.
2. **Test project:** the job is created or replaced there (no schedule), and **executed once**
   (`gcloud run jobs execute --wait`) against the test folders. A failed execution stops the release before
   anyone is asked. A service is deployed as a revision named for its release and checked on `/health`.
3. **User validation**, then **IT's deploy gate**. The gate card shows the package IT approves: the image,
   the job or service, the schedule, the egress rule and the secret references.
4. **Production:** a job gets the release's image and its Cloud Scheduler job (created, or updated when it
   exists). A service runs first as a candidate revision with no traffic and the `candidate` tag; the canary
   probes it beside the current one, and promotion sends it all the traffic.

**Rollback**, signed by IT or operations, with a reason:

```bash
rihmasto road rollback <pid> --env production --reason "the transcripts are empty" --person "Jaana" --persona operations
```

A service's traffic goes back to the previous revision; a job gets its previous image back. A second
rollback goes forward again. Delivery rolls back a failing service candidate on its own, as on every road.

## 7. Watching it

`rihmasto operate <pid>` (run it on a schedule on the factory host, as cron or a timer) reads the job's last
executions with `gcloud run jobs executions list --format=json`. The probe passes when the latest finished
execution succeeded, is not measured while none has finished, and fails when it failed: that opens an
incident card for the release, which the relay sends on as `rihma.incident.opened` to a webhook and as a
notice to the channels IT subscribed ([integrations.md](integrations.md)):

```bash
rihmasto relay subscribe --sink teams --url-env RIHMASTO_TEAMS_OPS --notify operations --notify it \
    --person "Ilkka" --persona it
```

`rihmasto road executions <pid>` reads the executions now; the project's Releases view shows the last ones
read. Rihmasto never reads an execution's logs: Cloud Logging stays the place for them.

## 8. Where the audio goes: confidentiality

Transcription sends audio to whatever model transcribes it. Choose where:

| Option | Where the audio goes | What to set |
|---|---|---|
| **A hosted speech API outside the organisation's cloud** | to that provider, under its terms | declare it as an integration (`--kind rest` or `openapi`, `--data-class confidential`), which needs plan approval at any maturity; its key in Secret Manager; the egress rule must allow that host |
| **A model in the organisation's own Google Cloud project** (Speech-to-Text or a model served on Vertex AI in its project and region) | stays in Google Cloud, in the organisation's project and region | the runtime service account gets the model's role; with `rules.egress` none and all traffic through the VPC, reach Google APIs through Private Google Access or Private Service Connect |
| **An open model, such as Whisper, inside the container** | nowhere: it stays in the job | the model in the image, `resources` sized for it (CPU and memory) and a longer `job.timeout_seconds` |

**A project marked confidential** ([inputs.md](inputs.md)) keeps Rihmasto's own model calls (the analyst,
the builder, the verifier) on a local or private endpoint. A model endpoint in the organisation's own Google
Cloud project counts as private when it is reached at a private address (Private Service Connect gives one)
or when its owner declares it private in Models setup ("On my own network", [models-setup.md](models-setup.md)).
The confidential setting governs Rihmasto's calls, not the product's: what the product sends at run time is
decided in its plan, by the integrations it declares and their data classes, and by the road's egress rule.

## What is real today

- **Rendered, validated, and tested end to end against a fake gcloud on PATH:** the road's configuration,
  the YAML and commands, delivery through the deploy gate, promotion and rollback, executions and incidents.
  The fake answers as gcloud does; the services' URLs it hands out are a server on 127.0.0.1.
- **Tested against a Drive v3 stand-in on 127.0.0.1:** the Drive client, its cursor, its credentials (a
  token, a service account key's signed JWT, the metadata server) and its errors.
- **Not yet run against a real Google Cloud project or a real Drive folder.**

## What a first real run needs

1. The projects, APIs, repository, three service accounts and their roles (section 1), set up by IT, and
   the Drive folders shared with the runtime service account.
2. `gcloud` installed and signed in on the deploying host, allowed to impersonate the deployer.
3. The road configured and a project's road chosen (sections 2 and 3); `rihmasto road render` reviewed.
4. The model key, if any, in Secret Manager, and the scheduler's service account given Run Invoker on the job
   once it exists.
5. A first `rihmasto deliver` watched end to end: the Cloud Build output, the test execution, the gate card,
   the production job and its Cloud Scheduler job. Expect to adjust: the fake gcloud answers as the
   documentation says gcloud does, and only a real run shows where the two differ.

## Commands

| Command | What it does |
|---|---|
| `rihmasto road list` | every paved road, ready or what is missing |
| `rihmasto road configure NAME --file F --person P --persona it` | IT writes a gcp-cloudrun road, checked whole |
| `rihmasto road choose PID ROAD [--workload job --cron ... --time-zone ... --retries N --scheduler-account ...] --person P --persona it` | a project's road, workload and schedule |
| `rihmasto road render PID [--env staging]` | the YAML and gcloud commands it would run, run nothing |
| `rihmasto road rollback PID [--env production] --reason R --person P --persona it` | back to the previous revision or image |
| `rihmasto road executions PID [--env production]` | a scheduled job's last executions, read now |
| `rihmasto integration declare PID --name N --kind gdrive ...` | the product reads or writes a Drive folder |
