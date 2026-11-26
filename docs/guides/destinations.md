# Destinations: where a capability goes

Rihmasto is the middle layer between development and destinations (D-0023). The owner (2026-11-24):
"Rihmasto is the middle layer of development and all backend work and any external platform / channel or
similar where the solutions are pushed and published or taken to testing."

A project's **Destinations** tab shows every place its capability goes, read from what exists, never
typed in twice. `rihmasto destinations <pid>` prints the same map in a terminal, and the project's
**Overview** says it in one line under **Where this goes**. When the interface's capsules arrive, the
view sits in the **Run** capsule.

## The four groups

| Group | What is in it | Read from |
|---|---|---|
| **Deployed** | each environment of the delivery plan on its paved road: the release that runs there, its URL, its health | `paved_roads.json`, `envs/<env>/current.json`, the releases, the probes (`ops/probes.jsonl`), the HTTP probe checks, open incidents |
| **Data and integrations** | the data systems it reads or writes (databases, APIs, a Google Drive folder), per environment, and the webhook sources bound to it | the spec's integrations and their bindings on the roads ([data-integrations.md](data-integrations.md)), Rihmasto's connectors, `hooks` |
| **Channels** | where it is used: website chats (embeds), Teams, Slack, email and signed webhooks through the relay, its MCP, HTTP and OpenAI faces and who served them | `embeds.json`, the relay's subscriptions and delivery log ([integrations.md](integrations.md)), `app/runtime.json` at the release, `capability_served` |
| **Published** | the registries IT named, and the outputs built for its audiences | `registries.json`, `publishes.json`, `output_built` ([outputs.md](outputs.md)) |

Each destination has its **environment** (test or production), its **state**, its **last delivery**,
its **health** and what you can do there.

| State | Means |
|---|---|
| Planned | named, but not ready: what is missing is said exactly (a road not configured, gcloud not signed in, a binding IT has not approved, a variable not set) |
| Configured | ready, and nothing delivered there yet |
| Delivered | something is there; its health is not measured yet |
| Healthy | the last probe or check passed |
| Failing | the last probe or check failed, a delivery there failed, or an incident is open |
| Not measured | a probe ran and could not measure (a sign-in turned it away) |

## What you can do there

- **Deliver to test** (a test environment's card): starts `rihmasto deliver` as a job, signed with your
  name. The plan's test steps run as always: build, deploy, smoke, holdouts.
- **Promote to production** (the production card): goes on with the delivery toward production. It stops
  at IT's deploy gate, which decides. A project whose maturity is not `production` says to raise it first.
- **Publish** (a registry's card): see below.
- **Open**: the environment's URL. **Investigate**: the incident in the Inbox.
- **Check now**: one feedback round (below).

In Ask Rihma, "where is this running?" (or "missä tämä pyörii?") is answered from the same map, with
**Take me there**. Asked to deliver or publish, Rihma proposes opening Destinations, where you press the
button: it never does it itself.

## Publishing to a registry

IT names the registries in `<home>/registries.json`, as it names the roads:

```json
{
  "schema": "rihmasto.registries/1",
  "registries": {
    "ghcr-test": {"kind": "ghcr", "environment": "test", "configured": true, "owner": "IT: the platform team",
                  "namespace": "example-org/test",
                  "login": {"username_env": "GHCR_USER", "password_env": "GHCR_TOKEN"}},
    "ghcr": {"kind": "ghcr", "environment": "production", "configured": true, "namespace": "example-org",
             "login": "existing"},
    "mcp-listing": {"kind": "mcp-registry", "environment": "production", "configured": true,
                    "namespace": "io.github.example-org"}
  }
}
```

| Kind | What it is | Needs |
|---|---|---|
| `ghcr`, `dockerhub` | GitHub's or Docker's container registry | a namespace, a login, `docker` on PATH |
| `artifact-registry`, `acr`, `container` | Google's, Azure's or any other container registry | a `host` too (`europe-north1-docker.pkg.dev`, `example.azurecr.io`) |
| `mcp-registry` | an MCP registry listing | the reverse-DNS namespace the server is listed under |
| `package` | a package registry | shown as a planned destination; publishing to it is not built |

**Credentials by name only.** `login` is `"existing"` (IT signed the deploying host's docker in with its
own credential helper: `gcloud auth configure-docker`, `az acr login`, `docker login`) or the names of the
two variables that hold the user name and the token. The token goes to `docker login --password-stdin` on
its input; it is never in an argument, a file, a record or an answer. A value that looks like a token in
the file makes the registry not ready.

```bash
rihmasto publish <pid> --to ghcr-test --person Pekka --persona developer
rihmasto publish <pid> --to ghcr --release 3 --person Ilkka --persona it
```

- The image is the release's own when its road built one (pulled first when it lives in a registry), else
  built now from a clean checkout at the release's revision. It is tagged
  `<host>/<namespace>/rihmasto-<pid>:r<release>-<revision>`, pushed, and the digest the registry gave back
  is recorded.
- **Test first, then production.** A production registry takes a release only after the same release was
  published to a test registry, and only through IT's **deploy gate**: the first publish opens a
  `deploy_gate` card in the Inbox, and the next one, after IT approved it, pushes. IT's refusal stops it.
- A registry that is not ready refuses and says exactly what is missing; the refusal is recorded
  (`publish_refused`) with who asked. Every publish is in `publishes.json` and the ledger (`published`,
  `publish_waiting`, `publish_failed`).
- **An MCP registry entry** (`mcp-registry`) is a file: the server manifest of the capability's MCP face,
  written to `publish/<release>/mcp-server.json` in the project, naming the published image when there is
  one. You submit it with the registry's own publisher tool. Rihmasto never submits anything to a public
  registry.

D-0015 said IT pushes images with its own tools. The owner's word above amends it: a person asks for each
publish, signed, and production keeps IT's gate.

## Feedback from destinations

One **round** (Check now, `rihmasto destinations <pid> --check --person P --persona X`, or the
**Destinations** check on its schedule in Health):

1. every environment where a release runs is probed (`/health` and the probe scenarios, or a scheduled
   job's executions), kept in `ops/probes.jsonl` like any probe;
2. every destination is read again and compared with the last round;
3. a destination that **became failing** opens an incident card (the Inbox, Home and the Review show it),
   posts in the project's **agent channel** (thread `destinations`, so a coding agent working on the
   project sees it with the card), and records `destination_failing`, which the **Review** lists under what
   went wrong and an **automation** reacts to. One that recovers records `destination_recovered`.

Life-cycle events for automations: `delivered` (a release reached where its maturity delivers it),
`published`, `destination_failing` and `destination_recovered` ([automations.md](automations.md)).

## What is real today

- **Real and tested:** the model over a project with a local-process and a gcp-cloudrun road, a data
  integration, a website chat, a relay subscription and an MCP face; the feedback round with real HTTP
  probes on 127.0.0.1; the view in headless Chrome.
- **Tested against a fake docker and a fake gcloud on PATH, never a real registry or cloud:** publishing,
  test first and production through the gate. A real publish needs IT to write `registries.json`, the
  docker CLI on the deploying host, and either the host signed in to the registry (`"login": "existing"`)
  or the two login variables set where the cockpit or the command runs.
- **Not built:** publishing to a package registry, submitting an MCP registry entry, and measuring the
  health of a data system or a registry beyond the digest a push returns.
