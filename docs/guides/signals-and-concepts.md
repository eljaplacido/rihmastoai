# Signals, concepts and updates

Work does not always start as a project. Needs come from the operation, and events come from
outside. Rihma records each as it arrives, and a person decides what becomes work.

- A **signal** is a need or a remark from the operation: a chat, a data feed, a form, an email, a
  monitoring alert, a meeting note, a website chat, or a manual entry.
- A **concept** is a new need, waiting for a business owner or product owner to validate it into
  a project.
- An **observation** is an event from outside: a new model, a CVE, eval drift, a compliance
  deadline, low use. Within the autonomy cap it opens an **update** card.

The code is [kernel/signals.py](../../kernel/signals.py) and
[kernel/observations.py](../../kernel/observations.py).

## Signals

Record a signal as it arrived, then triage it:

```bash
rihma signal log --text "The shipment webhook should tell the stock system when a delivery is split." \
    --channel chat --source "warehouse chat" --person "<your name>" --persona operations
rihma signal triage S-001
rihma signal list --state new         # the signals still waiting for triage
```

In the cockpit, **Square** has **Log a signal** and **Triage** ([cockpit.md](../cockpit.md#the-delivery-square)).
From Python, `kernel.signals.receive` and `triage` do the same.

Triage needs no model. It routes by rule:

- **About an existing project:** the signal names the project's id, or at least two words of its
  title. It becomes a **change card** on that project, and enters the change loop like any other
  feedback.
- **A new need:** it becomes a **concept** card in Rihma's own Inbox (the project shown as
  *Rihma itself*). The profile is proposed by rule from the text.

With `rihma signal triage S-001 --with-model`, the analyst's model (through Gnomon) may summarise
the need into a title, the problem, who has it and its value. It may also name an existing
project, which counts only if that project exists. The rule still decides.

`--channel` is one of `chat`, `feed`, `form`, `email`, `monitoring`, `meeting`, `embed` or
`manual`. `--person` and `--persona` are optional: a feed has none.

Two other ways in:
- the MCP server's `rihma_signal` tool, signed with the server's person ([mcp.md](../mcp.md));
- a website chat of kind `need` ([embeds.md](embeds.md)).

## Concepts

A business owner or product owner decides a concept card: **validate**, **park** or **reject**.
Before deciding, they may set its title, profile, maturity (demo by default) or mode (mixed by
default):

```bash
rihma concept edit C-0001 --title "Offline maintenance visits" --profile mobile_prototype \
    --maturity explore --person "<your name>" --persona business_owner
rihma decide _factory C-0001 validate --person "<your name>" --persona business_owner
rihma concept apply                   # carry out each decided concept once
```

Concept cards live in Rihma's own canon, whose project id is `_factory`. Nothing becomes a
project without the decision. A validated concept becomes a project whose intake starts from the
need as it arrived; `rihma run <project>` then runs the panel. The cockpit's **Square** edits and
decides concepts too, and carries a decided one out at once; after a decision on the command
line, `rihma concept apply` does it.

`rihma square` shows the square at a glance: signals waiting, concepts to validate, projects per
stage band, end-user feedback waiting for triage, and what runs in production. The MCP server's
`rihma_square` tool returns the same. `rihma catalogue` lists every capability with its state,
profile, deliverable and capability pack, and each concept waiting as `proposed`.

## Observations and the updates inbox

```bash
rihma observe cve --facts '{"id": "<the CVE id>", "severity": "high", "component": "the HTTP layer"}' \
    --source "the security team's feed"
```

The trigger is one of `model_release`, `cve`, `eval_drift`, `compliance_deadline` or `usage_low`;
`--facts` is a JSON object. Rihma works out which projects it touches. A model release touches the
projects built by the model it `replaces`; a CVE or a compliance deadline touches what is
delivered or about to be; `"projects": [...]` in the facts names them outright. Recording an
observation has no cockpit screen; from Python, it is `kernel.observations.observe`.

Each observation is rendered three ways:
- **developer:** JSON, for the API, MCP or a script;
- **expert:** a short report sentence with the facts;
- **business:** a proposal in plain words that ends with the decision it asks for.

At autonomy level 2 or higher it opens an **update** card on each touched project: **trial**,
**decline** or **defer**, decided by a named product owner, business owner, IT, developer or
compliance officer. At level 1 it only informs. Each decided card is recorded once; a trial is
approved for the operator to re-measure. Nothing updates itself. The cockpit records an update
card as soon as it is decided; after a decision on the command line, record it yourself:

```bash
rihma decide <project> <card> trial --person "<your name>" --persona developer
rihma updates apply <project>
```

In the demo, the shipment webhook has both: a change card routed from a chat signal, and an
update card for a new model. *Rihma itself* has a concept from a meeting.
