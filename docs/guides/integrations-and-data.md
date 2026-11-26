# Integrations and data

IT's view of everything Rihmasto and its projects connect to, and of the data side: where each connection is,
whether it works, which credentials it needs (by name only), what each agent may reach, and which data may leave
the machine. It is FR-ITD1; the code is `kernel/itdata.py`, `kernel/itdata_project.py`, `kernel/itdata_flow.py`,
`kernel/itdata_actions.py` and `kernel/itdata_chat.py`, with `cockpit/itdata_routes.py` and
`cockpit/static/itdata.js`.

## Where to find it

- **The platform**: *Integrations and data* in the sidebar (`#/connections`). Every connection of the platform,
  each project's data integrations with their access and data classes, every credential by name, what each agent
  may reach, and the factory home's data stores with their size, retention and ledger integrity.
- **A project**: the *Run* capsule, *Integrations and data* (`#/p/<project>/itdata`). What this project connects
  to, its data-flow diagram, what each agent may reach, and its credentials.
- **Ask Rihma**, by rule and without a model: "What does this project connect to?", "Which data leaves the
  machine?", "Where are the credentials?", "Check the integrations", "Turn off relay:SUB-001", "Remind me to
  rotate ORDERS_API_TOKEN in 30 days". The last three are proposals: nothing happens until you confirm.

## What a connection shows

| Kind | What it is | Turned off here |
| --- | --- | --- |
| Model endpoints | where each Rihma role sends its prompts (Models setup) | no: change it in Models setup |
| Relay channels | Teams, Slack, email and signed webhooks the relay sends events to | yes (IT) |
| Inbound webhooks | sources that ring Rihmasto | yes (IT) |
| Connectors | systems Gnomon reaches, read only | yes (IT) |
| Registries | where release images go | no: registries.json |
| Where it runs | paved roads and a project's environments | no: Destinations and the road settings |
| Website chats | chats on a website | no: Settings > Website chats |
| Data integrations | what a product declares in its spec, bound per environment by IT | no: a change, or IT's road card |

Each one says:

- **where it is**: *this machine*, *your network* (a private address, the rule confidential work uses), *outside*,
  or *address not known* (the address is in a variable that is not set where Rihmasto runs);
- **which way data goes**: in, out or both, and the **data classes** it touches;
- **health**: the last check (passed or failed, how long the connection took, failures in a row), or the relay's
  own last delivery;
- **credentials, by name**: where each lives (an environment variable, the stored key file, Gnomon's key store,
  the computer's keychain, a command, a vault) and whether it is set here. A value is never read or shown;
- **what to do** when something is missing, in one sentence.

A confidential project never calls a hosted model endpoint: the view marks it *never called for this project*,
and it does not count as data leaving. A role whose own model is hosted is therefore **blocked** there, not
working locally: its card says *Blocked: needs a local model* until a model on this machine or your network is set
for it in Models setup (FR-ITD2).

**Each project's own truth** (FR-ITD2): every project has its own *road:demo* or *integration:orders*, so a check
of one is kept for that project only; another project with the same id still says *not checked yet*. A connection
that serves other projects too says so (*Platform-wide*, or *Shared with other projects*).

## The data-flow diagram

Four groups: where data comes from (you and your team, webhooks, website chats, connectors, data integrations),
Rihmasto, the agents (Rihma's roles, coding agents through the AI tool connection, the delivered product) and
where data goes (model endpoints, where it runs, relay channels, registries). A dashed edge may leave this machine
and your network; a website chat's answers to its visitors are one. The line above the diagram counts the places a
dashed line ends, so the words and the picture agree. Each node is a button: it shows what the node is and opens its connection. On a phone the groups
are rows.

## Check now, Turn off, rotation reminders

Each is signed with your name and persona and recorded in the ledger (the project's, or Rihma's own for the
platform's connections).

- **Check now** (IT, operations or a developer): what stands between each connection and working, and, where it
  has an address, whether something answers on its port and how fast. Only a TCP connection is opened: no data,
  no credential and no request is sent. Results are kept in `itdata/` in the factory home. A check of where a
  project runs measures nothing itself (Destinations probes it), so what that probe said stays the health.
- **Turn off** (IT): ends a relay subscription, stops a webhook source or disables a connector through its own
  rule, with your reason. Anything else says where it is changed. One that serves other projects too is warned
  about before you confirm, and is signed with your IT access on the platform, not on the project you opened it
  from: IT on one project cannot stop every project's channel.

Ask Rihma's connection list answers "what does this connect to?"; a how-to question ("How do I connect to
Teams?") gets the map's answer instead.
- **Rotation reminder** (IT or operations): the date by which a credential is to be rotated. An overdue one is
  shown, and nothing nudges you for it: it does not block work.
