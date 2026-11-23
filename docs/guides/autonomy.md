# The autonomy ladder

One backend, four degrees of freedom. A person sets how far the factory may go on its own, and
the kernel enforces it ([kernel/autonomy.py](../../kernel/autonomy.py)).

| Level | Name | The factory may |
|---|---|---|
| 1 | answer | answer questions and analyse; it changes nothing |
| 2 | suggest | propose; a person decides each proposal |
| 3 | prepare | build and trial candidates in a sandbox lane, judged by their evals; nothing goes beyond a local preview or a demo |
| 4 | deliver | deliver approved candidates to staging and production, with a named approver for each release |

## How it is enforced

The kernel checks the cap at each step that needs more freedom. Above the cap, it stops with the
state `capped` and the reason, for example "building needs autonomy level 3 (prepare); the cap
is 2 (suggest)".

| Step | Needs |
|---|---|
| building a task in a cell | 3 |
| delivering to `preview` or `demo` | 3 |
| delivering to `staging` or `production` | 4 |
| opening an update card for an observation | 2; at level 1 the observation only informs |

The cap never replaces a person's decision. At level 4, production still waits on IT's deploy
gate, and every card still needs its decider.

## Who sets it

- The **factory's cap** applies to every project. The default is 4.
- A **project's cap** can be lower than the factory's, never higher. The effective cap is the
  lower of the two.
- Only a named person with the **business owner**, **IT** or **compliance** persona may set a cap,
  and only with a reason. Every change is in the ledger (`autonomy_cap_set`), with who, why, and
  the level before and after.

A policy might read: a defence customer at 3, industry at 4, internal development at 4.

## Set it

From the command line:

```bash
rihma autonomy set 3 --reason "build and trial only, until the pilot is approved" \
    --person "<your name>" --persona compliance
rihma autonomy set 2 --project <project id> --reason "suggest only for this one" \
    --person "<your name>" --persona it
rihma autonomy show <project id>      # the cap, its meaning, and which levels are allowed
rihma autonomy show                   # the factory's cap
```

In the cockpit, the **Autonomy** widget shows the ladder, and a business owner, IT or compliance
sets the cap there, with a reason. From Python, `kernel.autonomy.set_cap` and `describe` do the
same.

A refused change is not recorded: a persona that may not set caps, a reason left empty, or a
project cap above the factory's. The command prints why and exits 2; in Python it raises
`DecisionRefused` (or `ValueError` for an empty reason). The capability pack of each release
records the cap the project had ([packs-and-evidence.md](packs-and-evidence.md)).
