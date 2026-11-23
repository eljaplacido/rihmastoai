# Integrations

How Rihmasto connects to the tools people already use, as decided in
[D-0015](../decisions/D-0015-integrations-through-gnomon.md). Vendor facts were checked on 2026-11-23;
UNVERIFIED marks anything not confirmed from a primary source.

## 1. The short answer

Rihmasto reaches other systems through **Gnomon**. Each connector runs in its own integration lane:
Gnomon starts that system's MCP server (or a small Rihmasto tool server), checks every call against
policy, asks before writes, and records each call in its hash-chained audit, which Rihmasto ingests
like any other run. Rihmasto keeps only two thin native edges: **verified inbound webhooks** that
become proposals, and **outbound events** from its ledgers. The long tail comes through any MCP server
or the customer's own iPaaS.

- **Optional.** With no connectors, the factory runs exactly as today. Nothing connects until an `it`
  person decides a `connector` card.
- **No SDKs in the kernel.** Edge code is stdlib Python. Gnomon is the MCP client; vendor servers are
  the adopter's pinned choices, never dependencies.
- **Decisions stay in the Inbox.** Integrations only propose. Chat and mail carry a deep link.
- **Credentials never in the repository.** Configuration holds names and references only.
- **Every external call is governed and recorded**, in one audit trail the evidence pack cites.

## 2. Integration matrix

**Lane**: a Gnomon integration lane running a pinned stdio MCP server. **Bridge**: a lane plus
Rihmasto's stdio-to-HTTP bridge for a remote MCP server, until Gnomon speaks HTTP. **Hook**: a native
verified webhook, used only as a doorbell. **Relay**: a native outbound event, or a notice rendered
from one. **File**: a standard format. **Proxy**: IT's identity-aware proxy.

### Tier 1: adoption blockers, build first

| System | Personas | Direction | Mechanism | Maps to | Effort |
|---|---|---|---|---|---|
| iPaaS and event buses (n8n, Zapier, Make, Power Automate) | it, operations, business_owner | Two-way | Relay out; Hook in (Standard Webhooks v1) | All ledger events; signals, changes, observations | M |
| Email | every persona | Two-way | Relay to SMTP; Lane with a narrow IMAP server | Notices, digests; signals (channel `email`) | S |
| Teams, Slack | business_owner, stakeholder, developer, operations | Out | Relay to a Teams Workflows webhook or the adopter's own Slack app | Notices with one deep link, digests | S |
| Identity: OIDC, SCIM 2.0 (Entra ID, Okta; Google sign-in only) | all deciders, it, compliance | In | Proxy for sign-in; native `/scim/v2` | Signer bound to iss+sub; personas from groups; leavers lose rights | M |
| GitHub | developer, it, compliance | Two-way | Lane: `github-mcp-server --read-only`; narrow server for check runs and SARIF; Hook | Signals, changes (`gh:owner/repo#n`), check runs, security gate, `rihma sync` | M |
| Jira Cloud, JSM | product_owner, developer | Two-way | Bridge to Atlassian Rovo MCP (`/v1` or `/v2`: UNVERIFIED); Hook | Signals; linked issues mirror change cards; fix versions | L |
| Azure Boards | product_owner, developer | Two-way | Lane: local `azure-devops-mcp` | As Jira | M |
| PagerDuty | operations | Out | Relay to Events API v2 change events | Releases and rollbacks on the on-call timeline | S |
| Supply-chain and evidence files | compliance, it | Out | File: CycloneDX 1.7, SLSA v1.2, OSCAL, SARIF | Pack `sbom` and `signature` (null today); evidence pack | M |

### Tier 2: widens reach

| System | Personas | Direction | Mechanism | Maps to | Effort |
|---|---|---|---|---|---|
| Model cost (Anthropic, OpenAI, OpenRouter) | business_owner, operations | In | Gateway keeps returned cost; Lane for admin cost endpoints | Cost labelled estimated or invoiced | S |
| FOCUS export | business_owner, it | Out | File: FOCUS 1.3 CSV | Cost per capability and model | M |
| Azure Cost Management, AWS Data Exports, budgets | business_owner, it | In | Lane (read-only) or export-file drop | Run cost per release; budget breach as a signal | M |
| OpenTelemetry | operations, it | Two-way | Relay as OTLP/HTTP JSON; ingest keeps aggregates | Spans out; drift and errors as observations | M |
| Sentry, Grafana, Azure Monitor, Datadog | operations, developer | In | Hook for alerts; Lane for context | Observations, incident cards | M |
| ServiceNow ITSM, JSM change | it, operations, compliance | Two-way | Bridge or narrow server (MCP path UNVERIFIED) | Release links a change; CAB approval as evidence | M |
| SIEM (Sentinel, Splunk, Elastic) | it, compliance | Out | Relay JSONL file, shipped by the SOC's agent | Audit stream | S |
| GitLab, Azure Repos and Pipelines | developer, it | Two-way | Bridge; Lane | As GitHub | M |
| Confluence, SharePoint, Work IQ, Google Workspace | compliance, concept_evaluator | Two-way | Bridge, read-only first | Decision logs out; evaluation context in | M |
| Rihmasto remote MCP, OpenAPI | product_owner, business_owner, it | In | Native HTTP resource server; OpenAPI 3.1 plus Swagger 2.0 | Reads and proposals from hosted assistants and Power Platform | M |

### Tier 3: long tail through any MCP server or iPaaS

| Systems | Mechanism | Maps to |
|---|---|---|
| Linear, Asana, monday.com, Notion, Miro, Planner, Productboard, Aha! | `generic-mcp` (read-only) or an iPaaS recipe | Signals, concepts, tasks |
| Bitbucket, Jenkins, any CI | SARIF or JUnit files to the ingress | Evidence, security gate |
| Dynamics 365, NetSuite, SAP; Tempo, Clockify, Harvest | Lane, read first; postings only as decided writes | Cost centres, labour cost |
| Vanta, Drata, OneTrust, Archer | OSCAL first, then narrow servers | Control records |
| Backstage, A2A clients | Catalog file (UNVERIFIED); Agent Card | Catalog entries; signals |

Model endpoints are gateway routes, and clouds are paved roads. Neither is a connector.

## 3. Architecture

**Connector model.** `connectors/<system>/` holds `connector.json` (pinned server, tools hash, read and
write tools with deciders and argument templates, forbidden tools, data classes, credential names, id
namespace), pure `mapping.py` functions, fixtures with injection and rug-pull samples, an optional
narrow `server.py`, and a setup README. IT enables it in `projects/_factory/connectors.json`. The
`connector` card pins the sha256 of that entry; any change stops the connector and reopens the card.
One contract test suite runs over every connector.

**Gnomon as the governed client.** One lane per connector and one server per lane, so a tool never
acts on data another system returned. Roles allow only declared tools, with no shell or web fetch.
Gnomon pins each server's tools/list and clamps the session on change until the owner runs `gnomon
trust grant`; Rihmasto opens a `trust` card and prints the command, never runs it. Three call kinds:
**pulls** (cursor sync), **reads** (context, output only as JSON proposals), and **decided writes**:
checked against the allowlist, the argument template and a target already linked to the source
record, then approved in the Inbox bound to the sha256 of the canonical arguments. Time-boxed
`integration_policy` grants (90 days at most) cover low-impact mirror writes.

**What Gnomon must add upstream** (filed with the owner's consent; read in
`packages/gnomon-core/src/mcp.ts` at v0.6.6):

1. A model-free governed tool call (`--expect-args-sha256`, `--authorised-by`). Interim: a templated
   task on a local model, its trail checked by the kernel.
2. `args_sha256` on tool-call records in metadata audit mode. Interim: write roles record in full.
3. Declared read tools per server, so reads need no blanket `--yes`.
4. Streamable HTTP and an OAuth client (client ID metadata documents, RFC 8707, iss validation). The
   client is stdio-only today. Interim: the bridge.
5. MCP 2026-07-28. The client sends `2024-11-05` and knows up to `2025-06-18`; whether current
   servers accept that is UNVERIFIED, so each is tested at configure time.
6. Re-pinning on `tools/list_changed`, which v0.6.6 does not handle.
7. Releasing the `external_context` audit records (commit `2dd1c55`, on an unreleased branch).

**Inbound.** Webhooks are doorbells: verify the HMAC signature, drop repeated delivery ids, keep only
external ids, answer 202, then fetch the item through the lane. Content never comes from a webhook
body. Each item becomes one call: `signals.receive`, `change.submit`, `observations.observe`, SARIF
ingest, or a note on a linked card. End-user feedback keeps using the embed server.

**Outbound.** The relay tails each ledger by seq and checks the hash chain (a break halts that
stream). It wraps `rihma.event/1` in CloudEvents and posts it signed with Standard Webhooks v1, or
serves it as SSE or a JSONL file. Events are thin by default: ids, kind, redacted title, waiting
personas, deep link. A notice has one action, `#/p/<pid>/inbox/<card>`; a follow-up says who decided,
as which persona. Each persona gets a daily digest.

**Sync.** Records carry namespaced refs (`jira:acme/PROJ-123`). Creates are two-step: a pending link
carrying the event id, then that id stamped on the external object, so a crash is reconciled by
searching for the stamp. Rihmasto's own writes are not read back as changes. Rihmasto owns key, title
and state of what it created; the external tool owns its workflow fields. Inbound edits become notes or
proposals. Outside approvals (CAB, JSM, PR reviews) are evidence, never the decision.

**Identity.** Today a signer is a typed name, and any session holder can sign as any persona. The
cockpit moves behind IT's OIDC proxy, people bind to iss+sub, an IT-owned map turns groups into
personas, and SCIM ends a leaver's rights and re-routes their cards. The stdlib cannot verify RS256,
so verification stays at the proxy or uses token introspection.

**Credentials.** References only: `env:`, `os:` (the operating system's store) or `cmd:` (a token
command IT declares, such as `az account get-access-token`). Lane secrets live in `gnomon key`, and
Gnomon passes each server only the names it declares. Bot or App identities only.

**Security.**
- *Prompt injection:* inbound text is quoted data with provenance, stripped of hidden Unicode and HTML;
  its URLs are never fetched. The session that reads it has no write tool, and writes run without a
  model, so injected text can at most produce a proposal a person sees.
- *Confused deputy:* writes touch only linked targets; no token passthrough; the bridge pins one host
  and refuses redirects and private addresses.
- *Least privilege:* vendor read-only modes, bridge filtering, role allowlists, Gnomon policy and an
  Inbox decision each hold if another fails. Decide, merge, approve, delete and deploy tools are never
  allowed.
- *Data classification:* each project gets a class from public to restricted. Lanes reading
  confidential data use local models only. Above a sink's cap, only a content-free notice goes out.

## 4. Standards Rihmasto speaks natively

| Standard | Used for |
|---|---|
| CloudEvents 1.0.2 | Envelope for `rihma.event/1` |
| Standard Webhooks v1.0.0 | HMAC signing in and out (ed25519 only as an optional adapter) |
| OpenTelemetry OTLP/HTTP JSON, GenAI conventions | Runs and model calls out, telemetry in. Conventions are still Development, so names sit behind a pinned mapping |
| SARIF 2.1.0 | Security findings in (done) and out |
| OSCAL 1.2.x | Assessment results and a POA&M from the control table |
| CycloneDX 1.7 (SPDX 3.0.1 AI profile later) | SBOM, with models as ML-BOM components |
| SLSA v1.2 with in-toto | Provenance: contract hash, Gnomon runs, models |
| FOCUS 1.3 | Cost export (token columns expected in 1.5) |
| OIDC Core 1.0, SCIM 2.0 | Sign-in, people and personas |
| OSV 1.9.x | CVE observations matched to SBOM components |
| MCP | stdio server today; 2026-07-28 and a remote server next |
| A2A 1.0 | Later: tasks from enterprise agents (release date UNVERIFIED) |

## 5. Build plan

### Phase 1: build now

1. **Kernel groundwork.** Lock id allocation (`signals.py:74` uses `len+1` unlocked; cards, notes and
   observations too). Stop `model.py:104` passing connector secrets to Gnomon. Pass `ref` and persona
   through `POST /api/signals`. Add `kernel/redact.py`, `kernel/events.py`, external refs, project
   data classes and the cards `connector`, `integration_write` and `integration_policy`. Add the new
   packages to `RUNTIME` in `tools/quality.py`.
   - *Given* two processes logging signals at once, *when* both finish, *then* ids are unique and none
     is lost.
   - *Given* any ledger kind, *when* the catalog test runs, *then* it has an event mapping.
2. **Relay and notices**, with deep links that survive sign-in.
   - *Given* a card opens for `it`, *when* the relay runs, *then* the IT channel gets one notice whose
     only link opens that card after sign-in, and no holdout canary appears in any payload.
   - *Given* a receiver was down, *when* it recovers, *then* each event arrives once per `webhook-id`.
3. **Doorbell ingress.**
   - *Given* a bad signature or a replayed id, *when* it arrives, *then* nothing is stored.
   - *Given* a valid doorbell, *when* processed, *then* the item is fetched through the lane and
     becomes one signal with its ref; a repeat creates nothing.
4. **Identity at the edge.**
   - *Given* the proxy is bypassed, *when* identity headers arrive, *then* they are refused.
   - *Given* SCIM deactivates a person, *when* they try to decide, *then* it is refused and their cards
     re-route.
5. **Integration lane and registry.**
   - *Given* a server's tools/list changed, *when* sync runs, *then* nothing is called and a `trust`
     card shows both hashes.
   - *Given* an approved write, *when* the executed arguments differ from the approved hash, *then* an
     `incident` card opens.
6. **GitHub.** *Given* a gate verdict, *when* a `developer` approves the write, *then* one check run
   appears on that commit, and no merge tool is offered.
7. **Jira and Azure Boards mirror.** *Given* a change card linked to `jira:acme/PROJ-1`, *when* it is
   applied, *then* the issue state updates under a standing policy, and the next pull creates no
   signal from that write.
8. **Red-team gate and health.** *Given* seeded injection, rug-pull, unlinked-target, data-class and
   replay cases, *when* the gate runs, *then* each is caught and reported as SARIF before any
   connector may write. An expiring credential opens an `update` card for `it`.

### Phase 2

Finish Tier 1 (supply-chain and evidence files, email intake), then Tier 2: cost capture and FOCUS
(the owner decides on a `finance_owner` persona), cloud budgets, OpenTelemetry, alerting, ServiceNow
and JSM change, SIEM, GitLab and Azure Repos, Confluence and SharePoint, the remote MCP server and
OpenAPI.

### Phase 3

Tier 3 through `generic-mcp` and iPaaS recipes, ERP and time tracking, GRC tools through OSCAL,
Backstage, A2A, and retiring the bridge once Gnomon speaks HTTP.

## 6. What Rihmasto deliberately does not do

- **No decisions outside the Inbox.** No approve buttons in chat and no reply-to-approve, at least
  until decisions are bound to IdP identities, and never for deploy or compliance gates.
- **No second MCP stack**, and no vendor SDK, JWT or crypto library in the kernel.
- **No secrets** in the repository, ledger, events or packs, and no lane runs a server that returns
  secret values (Vault MCP, Azure MCP `keyvault`).
- **No long-lived cloud credentials.** Roads use managed or workload identity.
- **No pushes, merges or deploy approvals** in any allowlist.
- **No trust grants.** The owner runs `gnomon trust grant`, never Rihmasto.
- **No "compliant" claim.** Regulator reports, such as CRA notifications, are drafts a person submits.
- **No dead platforms:** Opsgenie (support ends 2027-04-05), App Runner (closed to new customers
  2026-04-30), Office 365 Connectors (retired May 2026).
- **No replacing the customer's tools.** The tracker, SIEM and iPaaS stay theirs.
