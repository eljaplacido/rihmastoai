# People in the loop, and reviewers outside the system

Questions, decisions and feedback put to a named person or persona, answered and signed, with each check family
advised or required (FR-HITL1, FR-HITL2). A person outside the system answers through a one-use link, with no
account. The owner (2026-11-25): "the human in the loop aspect is something that can be enforced when needed, and
the personas who would be on the place of each could be the ones nudged for feedback."

## Asks

An **ask** is a question (free answer), a decision (one of its options) or feedback (free words), put to a persona
and, when named, a person. It belongs to a check family: quality, governance, legal, security or general. When
nobody is named it goes to the persona responsible for its family (quality: product owner; governance and legal:
compliance; security: IT). Every answer is recorded with the person, the persona, whether they were outside the
system and the link they used.

Open a project's **People in the loop** view (Govern capsule): what waits on whom, Ask someone, the answers, and
each family's level. Ask Rihma does the same by chat: "what are we waiting on?", "ask compliance whether the
retention period is acceptable", "give our legal counsel a link"; each write is a proposal you confirm, signed.

## Advise or require

Each check family is **advised** (an open ask is shown and nudged; nothing waits on it, the default) or
**required**: delivery waits until every open ask of that family is answered, and the project's What's next and
the gate say which asks hold it. The level is set per project in People in the loop (**How strictly each check is
enforced**, for each family) by a business owner, product owner, compliance or IT, signed and in the project's
ledger; a project without its own level follows the platform-wide one. When [enforcement levels](enforcement-levels.md)
are set for a family, they are read first.

## A reviewer outside the system

**Give someone outside a link** for some of a project's open asks, naming the person, the persona their answers are
recorded as (a compliance reviewer, say) and their role in words ("External legal counsel"). The link:

- is shown once: only its sha256 is kept, with an expiry (72 hours unless you say, at most 30 days);
- is **one use**: opening it starts a session in that browser tab until the expiry; opened again it is refused,
  and the page says to ask for a new one;
- carries its token after `#`, which a browser never sends to a server, a log or a link preview;
- opens a page on the embed server (`/r/`) showing only those asks: their words, options and the asker's name,
  and nothing of any other ask, project or record;
- records every answer signed with the person's name and the recorded persona, marked as from outside;
- is withdrawn with one click (**Withdraw**), which ends its session at once.

Product owners, business owners, IT and compliance make links. The embed server must be reachable by the reviewer
(`rihmasto-embed`, behind IT's TLS proxy for people outside the network; see [embeds](embeds.md)).

## Sending and nudges

- **To a persona inside:** a notice through each Teams, Slack or email subscription IT made for that persona, with
  a link back to the People in the loop view. A webhook subscription receives every ask and answer as an event.
- **To a person outside:** their link, sent when it is made: by WhatsApp, by email, into a Teams or Slack channel,
  or not at all (Copy the link and pass it on).
- **WhatsApp** goes through the provider IT names in **People in the loop, Channels**: Twilio's Messages API or
  Meta's WhatsApp Cloud API, with the provider's URL and the *name* of the environment variable holding its key.
  Rihmasto never stores a key.
- **Nudges** escalate as an ask ages: a nudge after a day, an escalation to the business owner after three days,
  overdue after a week. Each counts as sent only once it reached someone; a step with no channel stays due and says
  which subscription IT adds. In solo mode only what blocks work nudges you. **Nudge now** sends the next one; to a
  person outside it sends a new link and ends the old one.

Nothing sent decides anything: an answer is given on the page or in the cockpit, signed.

## The API

`GET /api/projects/<pid>/hitl`, and `POST` to `.../hitl/asks`, `.../hitl/answer`, `.../hitl/send`,
`.../hitl/links`, `.../hitl/revoke` (withdraw a link) and `.../hitl/nudge`; `PUT .../hitl/enforcement` (a family's level) and
`PUT /api/hitl/channels` (IT's channels). The kernel is `kernel/hitl.py`, `kernel/hitl_links.py`,
`kernel/hitl_page.py`, `kernel/hitl_send.py`, `kernel/hitl_nudge.py` and `kernel/hitl_chat.py`.

Related: [enforcement levels](enforcement-levels.md), [embeds](embeds.md), [integrations](integrations.md) (the
relay's subscriptions), [access](access.md).
