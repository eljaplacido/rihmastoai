# Embeds: a website chat that feeds the factory

An embed is a small chat a website includes with one script tag. It has exactly one capability:

- **feedback:** the end users of a product say what they saw. Each conversation becomes a change
  card on that project (source: end user), triaged when it is filed, like feedback typed in the
  cockpit. A change request or a new requirement then waits in the decision queue (the Inbox,
  "what waits on you");
- **need:** people in the business describe a need. It becomes a signal in the delivery square,
  and from there a concept a business owner validates.

An embed can never read the canon, decide anything, see another project or reach the cockpit.

A website talks to the **embed server** only. The cockpit stays on 127.0.0.1 behind its one-use
sign-in and serves no widget, so a snippet never points at it.

## 1. Run the embed server

The embed server is separate from the cockpit. It answers two things only: the widget script
(`GET /e/<id>/widget.js`) and one chat turn (`POST /e/<id>/messages`).

```bash
rihmasto-embed --home var --port 8790        # or: python -m embed.server --home var --port 8790
```

It listens on 127.0.0.1 by default. To serve websites, put it behind IT's TLS reverse proxy:

- **The proxy on the same host:** keep the default. The proxy terminates TLS for
  `https://feedback.example` and forwards to `http://127.0.0.1:8790`.
- **The proxy on another host:** bind to the address the proxy reaches, and say that TLS is in
  front: `rihmasto-embed --home var --host 192.0.2.10 --behind-proxy`. Without `--behind-proxy`, a
  non-loopback address is refused.

Never expose the embed server without TLS. Without `--model`, every message is filed as it is.
With `--model gnomon`, the chat may ask one clarifying question first (see
[The chat's model](#the-chats-model)).

## 2. Tell the cockpit where the embed server is

Each snippet names the embed server's public address. Give it to the cockpit once:

```bash
rihmasto-cockpit --home var --embed-base https://feedback.example
# or set it for the cockpit's environment:
RIHMA_EMBED_BASE=https://feedback.example rihmasto-cockpit --home var
```

- The address is `https://host[:port][/path]`. Plain `http` is accepted only for `localhost` and
  `127.0.0.1`, for testing. Anything else (another scheme, a query, a user name) is refused when the
  cockpit starts, and so is the cockpit's own address.
- `--embed-base` wins over `RIHMA_EMBED_BASE`. The cockpit prints which address snippets use.
- **Without either**, snippets point at the local embed server, `http://127.0.0.1:8790`, which only
  a browser on the same machine reaches. The snippet then starts with a comment that says so, and
  Settings and the key box show the same warning. This is for testing: for a website, set the
  address and replace `http://127.0.0.1:8790` in an earlier snippet with it.

## 3. Create an embed

A product owner, business owner or IT creates it, with the websites (origins) allowed to use it.

**In the cockpit:** Settings → Embeds → **Create a chat**. Choose feedback (and its project) or a
business need, list the allowed websites, add a label and a short public brief, and create it. The
key and the snippet are shown once ([cockpit.md](../cockpit.md)). For a need chat, add
`data-kind="need"` to that snippet before you paste it (step 4).

**From the command line:**

```bash
rihmasto embed create --kind feedback --project <project id> --origin https://intranet.example \
    --label "Loans page" --brief "Equipment loans: lend and return the team's tools." \
    --endpoint https://feedback.example --person "<your name>" --persona product_owner
```

It prints the embed with its `key` and, with `--endpoint`, the `snippet` for the website.
`rihmasto embed list` shows every embed and its state, never a key.

**From Python**, at the repository root:

```python
from kernel.embeds import create, snippet
from kernel.store import Factory

factory = Factory("var")
e = create(factory, kind="feedback", project_id="<project id>",
           origins=["https://intranet.example"], label="Loans page",
           brief="Equipment loans: lend and return the team's tools.",
           person="<your name>", persona="product_owner")
print(snippet(e, "https://feedback.example", key=e["key"]))   # the embed server's public address
```

`snippet(e, None, key=...)` gives the testing snippet of step 2.

- `kind` is `feedback` (it needs a project) or `need` (it does not).
- An origin is `https://host[:port]`; give one for each website. Plain `http` is allowed only for
  `localhost` and `127.0.0.1`, for testing.
- `brief` is all the chat knows about the product. It never sees the project's records.
- **The key is shown once.** Rihma stores only its sha256 hash. Copy the snippet now.

## 4. Put the snippet on the website

```html
<script src="https://feedback.example/e/E-001/widget.js" data-rihma-embed="E-001"
        data-key="rk_..." data-endpoint="https://feedback.example" defer></script>
```

`src` and `data-endpoint` are the embed server's address from step 2. Two more attributes set what
the visitor reads:

- **`data-kind="need"`** gives a need chat its own words: "Share a need", "Tell us what you need".
  Without it the widget uses the feedback words ("Give feedback", "Tell us what you saw"). The
  snippet the cockpit and `rihmasto embed create` print does not carry it yet, so add it to a need
  chat's tag yourself.
- **`data-lang`** is `en` or `fi` and defaults to the browser's language. It sets all the widget's
  own words, the fixed thank-you included. With `--model gnomon`, the model is asked to answer in
  the language the person writes in.

What the visitor sees:

- **A filed message:** the thank-you and "Sent to the team". Never the card's or signal's number:
  that is the project's own.
- **A refused message:** it stays in the box, and the chat says why. Too many messages this minute
  (wait a minute), the chat is not set up for this website (a wrong key), the chat is busy, or the
  chat could not be reached. A revoked embed, or a website it does not allow, looks the same to the
  visitor's browser as a connection that is down, so the chat says it may be closed.

## The chat's model

With `--model gnomon`, a vague message gets one clarifying question before it is filed, through
Gnomon's `assistant` role. A website's visitor must never wait on the factory's own work, so:

- **A lane of its own.** The chat runs in `<lanes root>/embed/analyst` (by default
  `~/gf-lanes/embed/analyst`), a toolless analyst lane with its own lock. Intake, spec, holdout
  authoring and the cockpit's assistant use `~/gf-lanes/analyst`; a chat turn never waits on that
  lock, and never holds it.
- **A short wait and a short timeout.** Turns of one embed server share the chat's lane. A turn
  waits at most 10 seconds for it, and gives Gnomon at most 60 seconds
  (`--model-timeout <seconds>` changes that).
- **Filing without a reply.** When the lane stays busy, the model times out or fails, or its answer
  is not the JSON asked for, the message is filed as it is and the visitor reads "Thank you. It has
  been passed on to the team." (in Finnish with `data-lang="fi"`).
- **No kept records.** The server keeps no Gnomon task record in memory, however long it runs.

After at most 4 of the person's messages, the conversation is filed even if the model still has a
question, and the visitor reads the same thank-you rather than a question the next conversation
would not carry.

## The safety model

| Protection | What it does |
|---|---|
| One capability | A feedback embed only files change cards on its own project; a need embed only files signals. |
| A separate server | Websites reach the embed server only. The cockpit stays on loopback and serves no widget or chat route. |
| Origins | A message is accepted only with an `Origin` the embed allows. CORS answers allowed origins only. |
| The key | Required on every message, compared by its hash. It is publishable, like a site key: the origin list, the rate limit and the single capability are what protect it. |
| Rate limit | At most 20 chat turns a minute per embed, per server process. Past it, the answer is 429. |
| Size | A message is at most 2,000 characters, a request body at most 32 KB, and a conversation is filed after at most 4 turns. |
| Stalled connections | A connection that stops sending for 15 seconds is closed, so idle sockets do not hold the server's threads. |
| No records | The chat answers from the public brief only. It never reads the canon, the ledger, holdouts or another project, and the widget never shows the visitor a card's or signal's number. The embed server's answer to the browser still names that number, so a visitor who opens the browser's developer tools can read it. |
| Errors | A website sees a refusal, a turn it sent wrong, or a fixed line ("the chat is busy", "the chat is not available just now"). An internal error's text, such as a path or a project id, goes to the server's log only. |
| Headers | `nosniff` and `no-referrer` on every answer; `no-store` on every answer but the widget script, which browsers may cache for five minutes. |
| Revocation | **Revoke** in the cockpit's Settings, or one command: `rihmasto embed revoke E-001 --person "<your name>" --persona product_owner`. A message the chat was still answering when the embed was revoked is not filed. A page that still carries the snippet keeps showing the chat's button: what a visitor sends there is refused and stays in the box, and the chat says it may be closed. Take the snippet off the website as well. |
| Parallel messages | Messages the embed server receives at the same moment are filed one at a time: each gets its own card or signal, and none undoes a revoke. |

Each filed change card says it came from the embed, and keeps the conversation. It is triaged by
the rules when it is filed, exactly as the cockpit triages feedback typed there: a defect,
incident or question gets its way back, and a change request or new requirement waits for a
person's decision in the cockpit. If that triage cannot be written, the card is still filed, and
waits untriaged in the delivery square's **End-user testing** count; the visitor still reads the
thank-you. Reading the list of embeds writes nothing: it does not even create the factory's own
canon.
