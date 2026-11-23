# Taking Rihmasto's capabilities anywhere

Status: design, 2026-11-23, with phase 1 partly built the same day. Nothing here is built unless it
says "today" or **Built**; [section 4](#4-build-order) marks each phase 1 step built or planned.
UNVERIFIED marks claims not confirmed from a primary source.

## 1. The short answer

Every release becomes one portable unit with two identifiers: the OCI image digest and the
capability pack's `content_sha256`. Everything that leaves the factory names both. The image runs on
any OCI runtime: Docker, Podman, Kubernetes or a cloud container service. Its agents speak open
protocols (MCP, A2A, an OpenAI-compatible endpoint), so any host that speaks them can call the agent.
Neither Gnomon nor Rihmasto has to run at the destination.

What travels with it:

- **Pinning:** digest and pack hash, checked at start by a guard in the image, and by admission
  policy in clusters.
- **Evals:** signed acceptance scores and a public smoke set the site re-runs. Holdouts stay home.
- **Revocation:** a signed status document that expires.
- **Evidence:** checksums, signatures, the evidence pack and an SBOM, checkable offline.
- **Telemetry home:** outbound, content-free, only if the site agrees.

Governance is strongest where Rihmasto runs the agent and platforms call it by URL, and weakest where
a definition is copied into a platform. Each export says which guarantees it keeps.

## 2. Export targets by work profile

O = open, P = proprietary. Effort: S small, M medium, L large.

| Profile | Exports | Open-standard targets | Platform targets | Effort |
|---|---|---|---|---|
| Web app or service | image@digest, pack, Compose file, Kustomize base, Helm 4 chart, OpenAPI 3.1 | OCI runtimes, Compose, Podman Quadlet, Kubernetes, K3s (O) | Azure Container Apps (P; rendered today, never deployed), ECS Express Mode, Cloud Run (P) | S–M |
| Integration | as web, plus egress as NetworkPolicy, a CronJob, an MCP package if it declares tools | as web, plus MCP (O) | Copilot Studio connector, Foundry OpenAPI tool (P) | S–M |
| Mobile prototype | image serving a web app manifest and a service worker keyed to the release | W3C manifest (Working Draft), any HTTPS host (O) | the cloud hosts above (P); Play and Microsoft Store wrappers (UNVERIFIED) | S; stores M |
| ML or data pipeline | job image, weights as a signed OCI artifact, CycloneDX ML-BOM, eval report | Kubernetes Job, Compose, KServe, OpenSSF model signing (O) | ACA jobs, Cloud Run jobs (P) | M |
| Agent or assistant | agent image (HTTP, MCP, OpenAI-compatible model, embed), `server.json`, `.mcpb`, A2A card, Agent Skills folder | MCP 2026-07-28, A2A v1.0, Agent Skills (O) | by URL: Copilot Studio, ChatGPT plugins, Claude Managed Agents, Slackbot MCP, Gemini Enterprise A2A (preview); hosted: AgentCore, Foundry (P) | M |
| Harness engineering | `AGENTS.md`, Agent Skills, `.mcp.json`, the delivered Gnomon surface | AGENTS.md, Agent Skills, MCP (O) | coding agents reading those formats (P); instructions only | S |
| Ops agent | run-once job image; typed report (`report.json`, SARIF) with evidence pack | Kubernetes CronJob, Compose, report as OCI artifact (O) | ACA and Cloud Run jobs (P); scheduled AgentCore (UNVERIFIED) | M |

The factory's own apps (cockpit, gateway, embed, MCP control plane) export the same way. Its Gnomon
roles export as harness-engineering artifacts, labelled: Gnomon's enforcement does not carry over.

## 3. Architecture

### What travels

- **The image:** the stdlib product plus generated stdlib files (`pack_guard`, built today as
  `factory/pack_guard.py`, the image's entrypoint; for agents, the MCP, A2A and model endpoints,
  planned). The base is to be pinned by digest; today it is the tag `python:3.12-slim`. The image
  holds no Gnomon and no SDK.
- **The pack, beside the image, never inside it.** The pack pins the image digest, so baking the
  pack or its hash into the image would be circular. It travels as a mounted file, an OCI 1.1
  referrer or a bundle file. So the image can still check itself, the pack also pins
  `app_files_sha256` and `runtime_files_sha256`, tree hashes recomputed inside the container.
- **A signed status document** (`rihma.pack-status/1`): state (valid, suspended, superseded,
  withdrawn), reason, decided_by, expires_at, revoked key ids. Built today: the bundle carries one,
  signed when cosign can sign, and a withdrawal issues one; `superseded` and revoked key ids are
  still never set.
- **Integrity material:** SHA256SUMS, Sigstore bundles, `trusted_root.json`, in-toto statements
  (SLSA provenance, test results, a verification summary with `valid_until`), an SBOM. Built today:
  SHA256SUMS, the Sigstore bundles of SHA256SUMS and of the status, `trusted_root.json` and
  `cosign.pub`; statements and the SBOM are phase 2. `cosign.pub` is for reference only: whoever
  changes a bundle can sign it again and replace that file, so a site verifies against the key the
  factory published, handed over apart from any bundle.
- **A deploy kit** with images by digest and secrets by name only, the verifier, and instructions
  for use. Built today inside the offline bundle: `deploy-package.json`, `compose.yaml`,
  `rihmasto_verify.py` and the README.

Type names such as `application/vnd.rihmasto.capability-pack.v1+json` are proposals for the owner.
The published schemas use `urn:rihmasto:schema:...` ids, which name no domain.

### Verification at the destination

1. **By anyone, offline.** `rihmasto_verify.py`, one stdlib file importing nothing from `kernel/`,
   checks SHA256SUMS, the pack hash, the evidence manifest, the ledger chain and statement subjects.
   Signatures go to cosign; without it the result says "signature not verified: no verifier", never
   "passed". Good and tampered fixtures are published. Built today as
   [tools/rihmasto_verify.py](../tools/rihmasto_verify.py), with checks on the status, the app files
   against the source zip and the published [schemas](../schemas/); there are no statements yet, so
   that line reads "not applicable". Signatures are verified only against the key the factory
   published (`--key`), never the bundle's own `cosign.pub`. In a signed bundle the status must be
   signed too, and present where `BUNDLE.json` names it; with `--key` a bundle must be signed. The
   verdict reads "passed" (exit 0) only when every check passed and every signature was verified
   against `--key`; "failed" (exit 2) when a check failed; otherwise "not verified: no verifier",
   "not verified: no trusted key" or "not signed" (exit 3), never "passed". The good and tampered
   bundles are made by the tests at run time; publishing fixed fixtures is planned.
2. **At start, by the image.** `pack_guard` checks the pack hash, the tree hashes, the status
   document and its freshness, gateway drift (`gateway.packs.check`) and the smoke set. Until all
   pass, `/health` returns 503, so every orchestrator keeps traffic away. The site's IT decides
   whether a failure refuses, holds or defers (queue at L4). Built today, except gateway drift and
   the choice: a failure always holds (503). The guard reads the status from a file beside the pack.
   It is the image's entrypoint (the Dockerfile's CMD) and lives in `factory/`, a protected path, so
   a builder's change to `app/` cannot take it out; a pack built from a product whose image does
   not start through it says so in `pinned.trees_note`.
3. **At admission, in clusters.** Rendered policy-controller and Kyverno policies require the
   factory's signature and an unexpired verification summary. IT owns the controller.

A container cannot prove its own digest. Inside it, `RIHMA_IMAGE_DIGEST` is the deployer's
assertion. Only admission or pull-by-digest proves it.

### Telemetry and feedback home

Outbound only; nothing calls into a site. Telemetry is content-free OTLP/HTTP JSON with the
OpenTelemetry GenAI conventions, pinned by commit because they are still Development status. Every
span carries the pack version and hash. Eval failures, drift and operator reports travel as
CloudEvents over Standard Webhooks (HMAC, stdlib), per
[D-0015](../decisions/D-0015-integrations-through-gnomon.md), and become update cards for people to
triage. A site with no channel shows "not measured", never "healthy".

### Revocation

Sigstore signatures cannot be revoked, so revocation runs through the expiring status document; an
expired one is not trusted (the TUF rule). Withdrawal is a named person's ledgered act
(`rihma pack withdraw`). The guard reads the status from the site's URL, the OCI referrer, or the
bundle copy (with a stated air-gap grace period). It keeps a last-known-good copy, so a Rihmasto
outage cannot silently stop a site. Endpoints Rihmasto hosts stop at once; installed skills,
`AGENTS.md` files and `.mcpb` bundles cannot be recalled.

Built today: `rihmasto pack withdraw <pid> "why"` (it, compliance or product owner), the
`pack_withdrawn` ledger record, the withdrawn status document under `pack-status/<version>.json`,
and a guard that reads a status file (`RIHMA_PACK_STATUS`, with `RIHMA_STATUS_GRACE` for air-gapped
sites) and keeps the newest status it has seen for each pack in `DATA_DIR`. It takes no status
issued before that one (a replay), keeps a withdrawal as final, and falls back to the newest seen
when the file is missing, corrupt or half written, so none of these, nor a restart, undoes a
withdrawal. Compose mounts the folder holding the status, not the file, so a fresh copy written
by a rename reaches the guard. Reading the site's URL or an OCI referrer, delivering the new status
to sites, and stopping the factory's own slots on a withdrawal are planned.

### Site modes

| | Connected | Restricted | Air-gapped |
|---|---|---|---|
| Telemetry | pushed | hourly aggregates | file on media |
| Status | polled every 15 minutes | polled if egress allows, else the bundle copy | bundle copy with grace |
| Delivery | registry or cloud | per data class | OCI image layout on media |

Today the gateway knows only air-gapped and connected, and defaults to air-gapped. Packs know all
three and default to connected. Align them first.

### Evidence

The evidence pack and SBOM are referrers of the exact digest. The operator keeps their own site
evidence export (site ledger, start-time checks, smoke results, status versions applied) for six
months or more (EU AI Act Art. 26(6)). Every gate card and evidence pack carries a governance map
marking each guarantee held, partial or lost; one resting on an UNVERIFIED platform feature is never
"held". Built today for every gate card (the demo's acceptance, staging's validation and
production's deploy gate, each for the road its environment runs on), the evidence pack
(`governance-map.json`) and the offline bundle (`BUNDLE.json`, `README.md`); the site evidence
export is phase 2.

### Who acts

The kernel renders text and runs local tools found on PATH (docker, cosign, helm), saying "not
included: X not installed" when one is missing. Every act on an external system (pushing, applying,
publishing) goes through Gnomon's integration lane per D-0015: policy-checked, approved when it
writes, and audit-chained. Until that lane exists Rihmasto pushes nothing: for step 1 it tags the
image for the registry IT named on its paved road, on the deploying host only, and IT pushes the
tag with its own tools. A person with the it persona then pins the release by the digest the
registry gave it (`rihmasto pack pin`), which the deploying host's docker records: a local read,
recorded in the ledger with the person. The push moves into the integration lane with that lane.
The Azure road, rendered and validated but never deployed, builds with `az acr build`, which
writes to the registry; it predates D-0015 and moves into the lane before it is used.

## 4. Build order

### Phase 1: build now

Steps 1 to 5 and 7 are **built** (2026-11-23), as the contract's FR-PT1 to FR-PT6, proven by
[tests/test_portability.py](../tests/test_portability.py), and repaired the same day after an
independent check (task PT-07). Step 6 is planned.

1. **Pin by digest.** `kernel/packs.py:213` pins the mutable tag `gf-<pid>:<rev12>`.
   - Given a docker release, when its pack is built, then `pinned.artifacts` holds digests and no
     tags, and `deploy_package/2` names the same digest and the pack hash.
   - **Built** (FR-PT1). A docker road whose configuration names a `registry` tags the image for it
     at build, on the deploying host only (`image_tagged`): Rihmasto pushes nothing (D-0015). IT
     pushes the tag with its own tools, and a person with the it persona pins the release by the
     digest the registry gave it (`rihmasto pack pin <pid>`, `kernel.deliver.pin_image`), read from
     the deploying host's docker (`RepoDigests`), recorded as `image_pinned` with the person; the
     release runs it by digest from then on. The pack pins that digest (`pin_of`); an image not
     pushed and pinned is pinned by its local image id, never its tag, and `pinned.not_by_digest`
     says a site cannot pull it. The Azure road still reports a tag: its pin is marked as one.
     `kernel.bundle.deploy_package` makes `deploy_package/2` with the image as the release pins it
     now.
2. **Fix signing.** `kernel/bundle.py:138` signs without `--bundle`. cosign v3.1.1 requires bundle
   output or a registry upload (PR #4785), and the latest release is v3.1.4.
   - Given cosign 3.1.4 and a key reference, when a bundle is exported, then it holds
     `SHA256SUMS.sigstore.json` and `trusted_root.json`, and `cosign verify-blob` passes offline.
   - Given no cosign, when a bundle is exported, then it says "not signed: cosign not installed".
   - **Built** (FR-PT2). `cosign sign-blob --bundle SHA256SUMS.sigstore.json --use-signing-config=false
     --tlog-upload=false`, then `cosign public-key` and `cosign trusted-root create` for `cosign.pub` and
     `trusted_root.json`. cosign is not installed where this was built and was not downloaded: the
     tests run a stand-in cosign on PATH that refuses a blob without `--bundle` and a verify without
     a trusted root. The exact flags against a real cosign 3.1.4 are UNVERIFIED. The factory
     publishes its key apart from any bundle (`cosign public-key --key "$RIHMA_COSIGN_KEY"`); the
     bundle's `cosign.pub` is for reference only.
3. **Compose renderer.**
   - Given a valid deploy package, when it is rendered, then `compose.yaml` uses image@digest, a
     named `/data` volume and secrets by name only, `secret_leaks()` finds nothing, and
     `docker compose config` accepts the file.
   - **Built** (FR-PT3). `kernel.roads.render_compose` mounts the folder beside `compose.yaml` (the
     bundle's, holding the pack and its status) read-only at `/pack`: a folder, never a single file,
     since a file bind-mounted keeps the file it first saw and a status replaced by a rename would
     never reach the guard. Each secret reaches the product as the environment variable of its name,
     as on the factory's roads, its value taken from the deployer's environment
     (`${NAME:?...}`, so Compose refuses to start without it); never a Compose secret, which is a
     file under `/run/secrets` the product does not read. It binds 127.0.0.1 unless the road says
     otherwise, and renders nothing for an image not pinned by digest. The offline bundle carries
     `compose.yaml` when it can. `compose_config` runs `docker compose config --quiet
     --no-interpolate` when docker is installed (no secret's value is needed), and says "not
     measured" otherwise.
4. **Schemas and verifier.** Schemas for the pack, status document and deploy package name the
   unhashed fields and the canonical-JSON rule (no floats: `canonical_json` is not RFC 8785).
   - Given a good bundle, when the verifier runs offline, then every check passes, and the signature
     line reads "verified" (with cosign) or "not verified: no verifier".
   - Given one changed byte, when the verifier runs, then it fails and names the file.
   - **Built** (FR-PT4). [schemas/](../schemas/) holds JSON Schema 2020-12 files for the pack, the
     status document, the deploy package/2 and `BUNDLE.json`;
     [tools/rihmasto_verify.py](../tools/rihmasto_verify.py) checks a bundle folder or zip, or an
     evidence pack, and judges the status's expiry at `--at` (default: now). It verifies signatures
     only against `--key`, the key the factory published; a bundle changed and signed again with
     another key reads "not verified: no trusted key" without it and fails with it. A signed
     bundle's status must be signed and present; with `--key` the bundle must be signed. Only a
     bundle verified against `--key` reads "passed" and exits 0; an unverified one exits 3.
5. **pack_guard and withdrawal.** The personas it, compliance and product_owner can withdraw.
   - Given a withdrawn version, when the guard next reads the status, then `/health` returns 503
     with the reason, and the ledger names the person.
   - Given an edited app file, when the container starts, then it never becomes ready.
   - **Built** (FR-PT5). The template writes `factory/pack_guard.py` (from
     `kernel/scaffold_guard.py`); the Dockerfile copies it and starts the image through it, so the
     guard does not rest on `app/server.py`, which a builder may change. With `RIHMA_PACK` set,
     `/health` answers 503 with the reasons until the pack hash (`RIHMA_PACK_SHA256`), the app and
     runtime tree hashes (CRLF read as LF, so a Windows checkout hashes alike), the status and the
     pack's read-only smoke set pass, checked again every `RIHMA_PACK_STATUS_EVERY` seconds. The
     guard keeps the newest status seen per pack in `DATA_DIR`: no older status is taken and a
     withdrawal is final, through a missing or corrupt file and a restart. Without `RIHMA_PACK` the
     guard hands over to the product's server, as on the factory's own roads (which start the
     product directly). Planned: gateway drift, reading the status from a URL or referrer, and
     refuse or defer modes.
6. **Runtime declaration and agent endpoints.** The template declares workloads, tools and
   refusals; `build_pack` fills `runtime` (packs.py:217); build roles leave
   `declared.workload_classes`; the gateway is packaged and gains `restricted`. Agents serve
   stateless MCP 2026-07-28 (with a 2025-11-25 fallback) and an OpenAI-compatible model.
   - Given an agent release, when its pack is built, then `runtime.declared` is true and
     `gateway --check-pack` passes.
   - Given a 2026-07-28 client, when it calls `server/discover` and `tools/list`, then the tools
     arrive in a fixed order, with the pack version in `_meta`.
   - **Planned.** Nothing of this step is built.
7. **Governance map.**
   - Given any export or gate card, when it is shown, then it marks each of the five guarantees held,
     partial or lost, and the evidence pack holds the same map.
   - **Built** (FR-PT6). `kernel.evidence_pack.governance_map` marks pinning, evals, revocation,
     evidence and telemetry for a road the factory runs, or an export a site runs (`compose`,
     `offline-bundle`). Every gate card (the demo's acceptance, staging's validation, production's
     deploy gate, each for its environment's road), the evidence pack and `BUNDLE.json` carry it; on
     the Azure road (never deployed) nothing is held, and a tag loses pinning. `compose.yaml` and
     `deploy-package.json` travel inside the bundle, whose map covers them.

### Phase 2

- OCI referrers and attestations (SLSA Build L1, test results, verification summary, CycloneDX
  1.7); an OCI image layout in the offline bundle.
- Kubernetes with Kustomize, then Helm 4, plus admission policies (one replica, RWO volume, Gateway
  API route, NetworkPolicy).
- Publishing by URL: one MCP URL per pack version, an A2A v1.0 card, a publish gate card.
- Telemetry ingest, the site evidence export, a smoke scenario kind outside holdout custody, and
  approval parking at the site.
- A real ACA deployment through Gnomon, with a twin; the mobile manifest and service worker;
  multi-arch images; renaming the `mcp` package, which shadows the official SDK.

### Phase 3, on demand

ECS Express Mode and Cloud Run; AgentCore Runtime (ARM64, named endpoints, never DEFAULT; its
`/ping` probe is UNVERIFIED); the Foundry hosted agent; Teams and Slack apps; Zarf and Hauler;
KServe; store wrappers; SCITT receipts; edge runtimes.

## 5. What Rihmasto deliberately does not do

- No runtime dependency beyond Gnomon, and no cloud, MCP, A2A or Helm SDK in the kernel.
- No secrets in the repository, image, pack or bundle.
- No holdout scenarios outside custody: not in attestations, not to platform evaluators, not run
  against endpoints another organisation operates.
- No self-written cryptography, and no "verified" without a verifier.
- No DRM. The guard cooperates with the operator; anyone with root can run the product without it.
- No pulling telemetry from sites, and no prompt content in telemetry by default.
- No movable pins: no tags without digests, AgentCore DEFAULT, Cloud Run `--to-latest`,
  Ingress-NGINX, or Helm 3 (security fixes end 10 Feb 2027).
- No copying agent definitions into platforms as the main route.
- No auto-applied feedback or optimizer output.
- No App Runner adapter (closed to new customers), and no platform adapter before a customer asks.
- No acting for the owner. Type names, the MCP Registry namespace,
  public registries, stores and tenant consent belong to the owner or to the customer's admin.

## Sources and what is unverified

Checked 2026-11-23: cosign's GitHub releases (v3.1.4 latest; v3.1.1 PRs #4785 and #4804, the latter
deprecating OCI-referrer flags for v4), helm.sh "Helm 3 End of Life" (2 Jun 2026), and kubernetes.io
(image volumes stable since v1.36). MCP 2026-07-28, A2A v1.0, App Runner's closure and AgentCore
versioning come from the research streams' primary sources.

UNVERIFIED: whether bundle.py's earlier call failed outright on cosign 3.1.x; key-based signing
without a transparency log, and the flags `--use-signing-config=false` and `trusted-root create`
with no services that the built signing uses; `oras cp -r` with OCI layouts; Kyverno referrers and offline admission; MCPB
signing; Foundry's hosted-agent protocol from stdlib; a persistent `/data` on ECS Express and Cloud
Run; the App Runner closure date; the EU Digital Omnibus dates.
