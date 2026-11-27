# Integrations: events out, doorbells in, connectors

How IT connects Rihmasto to the systems a team already uses, as decided in
[D-0015](../../decisions/D-0015-integrations-through-gnomon.md). The design, with every system and
standard, is [integrations.md](../integrations.md). This guide covers what is built.

**Built (phase 1, the native edges and the connector model):**
- **Events out.** The ledgers go out as CloudEvents 1.0, signed with Standard Webhooks v1, retried
  with backoff and logged (`kernel/events.py`, `kernel/relay.py`).
- **Notices.** Each has one deep link to the card, for Teams workflow webhooks, Slack incoming
  webhooks and email (`kernel/notices.py`).
- **Doorbells in.** Verified inbound webhooks become signals or change proposals, never decisions
  (`kernel/hooks.py`, `python -m embed.webhooks`).
- **The connector model.** It has a schema, the `connector` card only IT decides, pins that stop a
  changed connector, a contract suite and an example connector (`kernel/connectors.py`,
  `connectors/`).

**Not built yet:** Gnomon integration lanes that call a connector's server. Until they exist, a
connector is modelled, validated and decided, and nothing calls it. Fetching a doorbell's item
through its connector, decided writes, identity at the edge and the named connectors (GitHub, Jira,
Azure Boards and others) are also still to come. [Section 6](#6-what-is-planned) lists what is
planned and what Gnomon must add first.

Nothing connects until IT configures it. With no subscription, no source and no connector, the
factory runs exactly as before.

**How a capability reaches outside systems** at run time is a different path: it declares each one in its
plan and IT binds it on the paved road ([data-integrations.md](data-integrations.md)). One of those is a
**Google Drive folder**: the product imports the paved road's Drive client, lists the files that arrived
since its last run, downloads them and uploads results, with credentials by name only. On Google Cloud it
runs as the road's runtime service account, so no key is needed ([gcp.md](gcp.md), a scheduled agent that
reads recordings from Drive and writes transcripts back). A failing scheduled job opens an incident card,
which the relay below sends on.

## 1. Who does what

| Step | Who | How |
|---|---|---|
| Configure subscriptions, sources and connectors | `it` | `rihmasto relay`, `rihmasto hooks`, `rihmasto connector`, each signed `--person <name> --persona it` |
| Decide a `connector` card | `it` | in the factory's own Inbox ("Rihmasto itself"), or `rihmasto decide _factory <card> enable` |
| Decide every other card | the card's deciders | in the Inbox; a notice only links there |
| Hold the secrets | the host's environment | each secret is the name of an environment variable; Rihmasto never stores a value |

A command signed by anyone but IT is refused with exit 2, and nothing is written.

## 2. Events out: the relay

### Subscribe a receiver

```bash
rihmasto relay subscribe --sink webhook --url https://hooks.example.org/rihmasto \
    --secret-env RIHMASTO_RELAY_SECRET --type 'rihma.card.*' --type 'rihma.release.*' \
    --person Ilkka --persona it
rihmasto relay cockpit https://rihmasto.example.org --person Ilkka --persona it
```

- **The receiver** is an `https` URL. Plain `http` is accepted only on 127.0.0.1, for testing. A
  URL with a user name or a fragment is refused, and so is a redirect when the relay sends.
- **The secret** is named, never given. Set `RIHMASTO_RELAY_SECRET` in the relay's environment to
  a Standard Webhooks secret (`whsec_` and base64) or a plain shared secret, which is used as its
  bytes. A value given where a name belongs is refused.
- **`--type`** takes patterns over event types, such as `rihma.card.*`. The default is `rihma.*`,
  every event.
- **`relay cockpit`** sets the cockpit's address as people reach it, behind IT's proxy. Every deep
  link starts there. Without it, links point at `http://127.0.0.1:8787`.
- **A new subscription starts at each ledger's head.** It receives what happens next, not the
  history. A project created later is sent from its first record.

### What a receiver gets

One POST per event, in ledger order, with the body as a CloudEvents 1.0 structured JSON
(`Content-Type: application/cloudevents+json`):

```json
{"specversion": "1.0", "id": "msg_3f2a...", "source": "/rihmasto/projects/equipment-loans-ab12cd",
 "type": "rihma.card.opened", "subject": "C-0007", "time": "2026-11-23T09:30:00Z",
 "datacontenttype": "application/json",
 "data": {"spec_version": "rihma.event/1", "event_id": "msg_3f2a...", "event_type": "card.opened",
          "ledger_kind": "card_opened", "seq": 41, "prev_hash": "...", "record_hash": "...",
          "stream": {"project_id": "equipment-loans-ab12cd"}, "actor": {"kind": "kernel"},
          "correlation": {"id": "C-0007", "kind": "deploy_gate"},
          "card": {"id": "C-0007", "kind": "deploy_gate", "title": "Release 3 to production",
                   "state": "open", "waiting": ["it"],
                   "link": "https://rihmasto.example.org/#/p/equipment-loans-ab12cd/inbox/C-0007"}}}
```

- **Every ledger kind has a type.** The kinds people act on have their own: `rihma.card.opened`,
  `rihma.card.decided`, `rihma.release.done`, `rihma.incident.opened` and others (`CATALOG` in
  `kernel/events.py`). Every other kind is `rihma.ledger.<kind>`.
- **Events are thin.** They carry ids, the ledger position and hashes, and only id-like payload
  values. A card adds its kind, its title, the personas it waits on and its link.
- **Nothing private leaves.** A card's body and a payload's free text never leave. A title is
  redacted against every holdout scenario, cleaned of HTML and hidden characters, redacted again
  against each held string as cleaned, and only then cut to 160 characters: a held-out string reads
  `[held out]`, even when it carries tags or runs of spaces, or crosses the cut.
- **A decision says who decided.** `actor` names the person and their persona, and `correlation`
  holds the verdict.

### Verifying a delivery

Each request carries `webhook-id`, `webhook-timestamp` (Unix seconds) and `webhook-signature`
(`v1,` and the base64 HMAC-SHA256 of `<id>.<timestamp>.<body>`). The `id` is the CloudEvent's id
and stays the same on every retry, so a receiver drops an id it has seen. Any Standard Webhooks
library verifies it. In Python's standard library:

```python
import base64, hashlib, hmac

def verify(headers, body: bytes, secret: str, now: int, tolerance: int = 300) -> bool:
    key = base64.b64decode(secret.removeprefix("whsec_")) if secret.startswith("whsec_") else secret.encode()
    msg_id, stamp = headers["webhook-id"], int(headers["webhook-timestamp"])
    mac = hmac.new(key, f"{msg_id}.{stamp}.".encode() + body, hashlib.sha256).digest()
    expected = "v1," + base64.b64encode(mac).decode()
    return abs(now - stamp) <= tolerance and any(
        hmac.compare_digest(s, expected) for s in headers["webhook-signature"].split())
```

### Running it, retries and the log

```bash
rihmasto relay run                                      # one round, for every subscription
rihmasto relay log [--subscription SUB-001] [--limit 50]
rihmasto relay list                                     # subscriptions; secrets are names only
rihmasto relay unsubscribe SUB-001 --person Ilkka --persona it
```

- **A round** reads each ledger from where the subscription stopped. It checks the hash chain
  first: a break halts that stream at the break, and the log says so once.
- **No daemon yet.** Run `rihmasto relay run` on a schedule, such as cron, a systemd timer or Task
  Scheduler. A round already running answers `busy`.
- **A failed delivery** (no connection, or an answer outside 2xx) is tried again on a later round,
  after 5 s, 5 min, 30 min, 2 h, 5 h, 10 h and 10 h. The subscription waits on it, so events stay
  in order.
- **After the eighth attempt** the event is logged `failed` and the stream moves on.
- **A delivery that cannot be sent** counts as a failed attempt like any other: a URL variable
  with a port that is not a number, or with a space in it, is retried and logged. The round goes on
  to the other subscriptions.
- **A redirect is an answer, never followed.** A receiver that answers 3xx has failed that attempt,
  and the address it names is never called.
- **A missing variable** leaves the subscription waiting (`not configured`) without losing an
  attempt.
- **The delivery log** (`<home>/relay/deliveries.jsonl`) is hash-chained. It holds every attempt
  with its outcome, status and next try, and never a URL or a secret. An error that quotes one is
  masked first: a variable's value reads `<$NAME>`, a receiver's URL `<url>`.

## 3. Notices: Teams, Slack and email

A notice tells a channel that a card waits for one of its personas, and follows up when the card
is decided.

```bash
rihmasto relay subscribe --sink teams --url-env RIHMASTO_TEAMS_IT --notify it --person Ilkka --persona it
rihmasto relay subscribe --sink slack --url-env RIHMASTO_SLACK_DELIVERY --notify developer --notify operations \
    --person Ilkka --persona it
rihmasto relay subscribe --sink email --smtp-host mail.example.org --smtp-port 587 --starttls \
    --mail-from rihmasto@example.org --mail-to it-team@example.org --notify it \
    --smtp-user-env RIHMASTO_SMTP_USER --smtp-password-env RIHMASTO_SMTP_PASSWORD --person Ilkka --persona it
```

- **Teams and Slack URLs are named by a variable.** A Teams workflow webhook ("when a Teams
  webhook request is received") or a Slack incoming webhook URL is itself a secret, so `--url` is
  refused for them.
- **Teams** gets a message with one Adaptive Card 1.4 and one `Action.OpenUrl`. **Slack** gets a
  fallback `text`, one section and one link button. **Email** gets plain text, marked
  `Auto-Submitted: auto-generated`.
- **The mail relay** is reached with STARTTLS unless it is on this machine.
- **`--notify`** names the personas whose cards the channel hears of. A card is announced when one
  of its deciders is among them. Question cards are open to everyone, so they come only when
  `--kind question` names them. `--kind` limits a channel to the card kinds it names.
- **A notice has exactly one link**, the card in its project's Inbox
  (`<cockpit>/#/p/<project>/inbox/<card>`). It has no approve button and no reply-to-approve. The
  follow-up says the verdict, who decided and as which persona, and carries the same link.
- **A title cannot add a link.** A title can come from outside: an end user's feedback names its
  change card.
  - An address with a scheme (`https://`, `mailto:`, `tel:` and the like), one that starts `www.`
    and one that starts `//` read `(link removed)`.
  - A bare domain, a dotted address and a mail address keep their words, with their dots and @
    written so that no client links them: `evil[.]com/login`, `boss[at]evil[.]com`.
  - A Markdown link is broken apart.
  - In Slack, `&`, `<` and `>` are escaped, so a title cannot make a Slack link or mention.
- **Planned:** keeping that link through the cockpit's one-use sign-in. Today it opens the card in
  a tab that is already signed in.

## 4. Doorbells in: verified inbound webhooks

A webhook from another system is a doorbell. It says that something changed, and the factory keeps
only its ids.

```bash
rihmasto hooks add ipaas --scheme standard --secret-env RIHMASTO_HOOK_IPAAS --person Ilkka --persona it
rihmasto hooks add github --scheme github --secret-env RIHMASTO_HOOK_GITHUB --person Ilkka --persona it
rihmasto hooks add tracker --scheme standard --secret-env RIHMASTO_HOOK_TRACKER --becomes change \
    --project equipment-loans-ab12cd --person Ilkka --persona it
python -m embed.webhooks --home var --port 8791         # the senders POST to /hooks/<source>
```

**The server** listens on 127.0.0.1. Put it behind IT's TLS reverse proxy, which forwards
`https://hooks.example.org/hooks/<source>` to it. For a proxy on another host, use `--host <address>
--behind-proxy`. It reads each source's secret from its own environment. `GET /health` answers 200.

**A delivery is accepted only when all of these hold:**
- **its size:** at most 64 KiB, refused with 413 before it is read; a request with no length is
  refused with 411;
- **its signature:**
  - Standard Webhooks v1: `webhook-id`, a `webhook-timestamp` within the source's tolerance
    (300 s by default) and a valid `webhook-signature`;
  - GitHub: `X-Hub-Signature-256` over the body with the shared secret, keyed by
    `X-GitHub-Delivery`;
- **its id:** never seen before. A replay is answered 200, not accepted, and stores nothing.

A refused delivery stores nothing. The answers are 202 accepted, 200 already received, 401 bad
signature or timestamp, 404 no such source, 400 or 422 a body that names no item, and 503 a source
whose secret is not set.

**What a ring becomes.** The factory keeps external ids only: an event name, an action, a
repository, a number and a `ref`. It never keeps text from the body.
- **GitHub:** `issues` `opened` on `acme/shop#12` becomes ref `gh:acme/shop#12`.
- **A Standard Webhooks sender:** the body's `ref`, else its `subject`, else its `id`. A value
  without a namespace is prefixed with the source's id, such as `tracker:PROJ-7`. The CloudEvent
  `type`, or an `event` field, names what happened.

Each accepted ring becomes **one signal** in the delivery square (channel `feed`), or, for a
`--becomes change` source, **one change card** on its project. Either way, it carries the ref.
- **A second ring for the same item** adds nothing while the signal is new or the change card is
  open.
- **Nothing an outside system sends decides a card.** A person triages the signal, and a person
  decides the change.
- **Every accepted ring** is recorded in the factory's ledger as `hook_received`, with the pushed
  branch when the body names one (`ref: refs/heads/main`).
- **A source bound to projects** (`hooks add ... --bind <pid>`, or later `hooks bind <source> --project
  <pid>`) also records each ring in those projects' ledgers, so their automations react to it
  ([automations](automations.md)). A relay subscription made with `--project <pid>` is that project's
  own receiver: no other project's events go to it.

## 5. Connectors

A connector is how one system is reached through Gnomon: `connectors/<system>/` holds
`connector.json`, a pure `mapping.py`, `fixtures/` (the pinned tools/list, a rug-pull tools/list
and injection samples), optionally a narrow `server.py`, and a setup README.
[connectors/example](../../connectors/example/README.md) is the template.

### connector.json (`rihma.connector/1`)

| Key | What it holds |
|---|---|
| `system`, `title`, `namespace` | the folder's name, a title, and the prefix of its refs (`jira:`) |
| `server` | `transport` (`stdio`; a remote server waits for Gnomon's HTTP client), the `command` Gnomon starts, and a `pin`: the version, and the sha256 of a local server |
| `tools_sha256` | the sha256 of the server's tools/list (`kernel.connectors.tools_sha256`) |
| `read_tools` | each tool's name and what it maps to: `signal`, `change`, `observation` or `note` |
| `write_tools` | each tool's name, the personas who decide it and the argument template it must match (decided writes are planned) |
| `forbidden_tools` | tools the server has that are never allowed |
| `data_classes` | `public`, `internal`, `confidential` or `restricted` |
| `credentials` | each credential's name and a reference: `env:NAME`, `os:NAME` or `cmd:<command>`, never a value |

**`rihmasto connector validate <system>` names every break by its JSON path.** Among the rules:
- no read or write tool may decide, merge, approve, delete, deploy or push; list such tools under
  `forbidden_tools`;
- a tool is named once;
- a string shaped like a live token is refused anywhere in the file.

### Turning one on

```bash
rihmasto connector enable example --person Ilkka --persona it     # writes the entry, opens a connector card
rihmasto decide _factory C-0003 enable --person Ilkka --persona it
rihmasto connector status                                         # off, waiting, enabled, declined or stopped
rihmasto connector check                                          # stop changed connectors, reopen their cards
rihmasto connector disable example --person Ilkka --persona it
```

**The entry.** Enabling writes the connector's entry to `projects/_factory/connectors.json`. The
entry holds the folder, the lane, the namespace, the data classes, the read tools, `writes: false`,
who enabled it and when.

**The card.** A `connector` card opens in the factory's own Inbox. It pins the sha256 of the entry
together with the sha256 of `connector.json` and of every file in the connector's folder: its
server, its mapping and its fixtures. Only IT decides it: `enable` or `decline`.

**When it may run.** Only while that card was decided `enable`, nothing it pins has changed and
IT has not disabled it since (`kernel.connectors.require_enabled`, checked before any call).
- **A change stops it at once.** That covers an edited `connector.json`, `server.py`, `mapping.py`
  or any other file of its folder, an entry changed by hand, an entry written back by hand after
  `connector disable`, and a connector enabled again.
- **A local server must be the one pinned.** When the command names a file in the folder, such as
  `server.py`, its sha256 must be `server.pin.sha256`. A server that is not may not run, whatever
  is decided, and `connector validate` names `/server/pin/sha256`.
- **`connector check`** records `connector_stopped`, withdraws a card left open, and opens one new
  card that pins what is there now.
- **A schema break.** A `connector.json` that breaks the schema may not run, whatever is decided.

### The contract suite

```bash
python -m unittest tests.test_connectors_contract
```

**It runs over every folder under `connectors/`**, so a new connector is held to it when it is
added. Each connector must:
- validate under its own name, with its fixtures, mapping and setup page;
- pin a tools/list that matches its fixture, and catch its rug-pull fixture;
- map every injection sample to a proposal whose text is quoted untrusted data
  (`[untrusted text from <ref>] ...`), with no HTML and no hidden characters, without opening a
  socket.

**A connector with a narrow `server.py`** must also:
- pin that file's sha256;
- answer the pinned tools/list over MCP stdio, run as a local child process;
- map what each read tool returns to valid proposals;
- be caught when it serves its rug pull (`--rug-pull`).

## 6. What is planned

| Planned | Waits on |
|---|---|
| A Gnomon integration lane per connector that runs its pinned server and checks each call against policy | Gnomon: declared read tools per server, a model-free governed tool call, `args_sha256` on tool-call records |
| A `trust` card with both hashes when a server's tools/list changes, and re-pinning on `tools/list_changed` | Gnomon: re-pinning on `tools/list_changed` |
| Fetching a doorbell's item through its connector (today a ring keeps its ids only) | the integration lane |
| Decided writes (`integration_write`, `integration_policy` cards), bound to the sha256 of the arguments | Gnomon: a model-free governed tool call |
| Remote MCP servers over Streamable HTTP with OAuth | Gnomon: an HTTP client (until then, a stdio bridge) |
| The GitHub, Jira, Azure Boards, PagerDuty and other connectors | the integration lane |
| Identity at the edge (OIDC behind IT's proxy, SCIM) and deep links that survive sign-in | the cockpit |
| A relay daemon, SSE and JSONL sinks, daily digests, data classes per project | Rihmasto |

Gnomon's side is listed in [integrations.md](../integrations.md#3-architecture), under "What Gnomon
must add upstream". The owner files those upstream.

## 7. What it keeps

| File | What | Written by |
|---|---|---|
| `<home>/relay/subscriptions.json` | subscriptions and the cockpit's address; variable names, never secrets | `rihmasto relay` (IT) |
| `<home>/relay/cursors.json` | where each subscription stopped, its attempts and next try | the relay |
| `<home>/relay/deliveries.jsonl` | the delivery log, hash-chained | the relay |
| `<home>/hooks/sources.json` | inbound sources; variable names, never secrets | `rihmasto hooks` (IT) |
| `<home>/hooks/seen.json` | delivery ids seen per source, for replay protection | the webhook server |
| `<home>/projects/_factory/connectors.json` | the connectors IT enabled | `rihmasto connector` (IT) |

Configuration changes are also recorded in the factory's own ledger: `relay_subscribed`,
`hook_source_added`, `connector_enabled`, `connector_stopped` and the others. They go out as
events like any other record.
