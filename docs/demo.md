# The demo

One command builds a demo factory home, with no model keys, no network and no Gnomon:

```text
rihmasto demo
rihmasto-cockpit --home var/demo
```

The cockpit prints a one-use sign-in link on 127.0.0.1. Open it in your browser.

A scripted model stands in for the analyst and the holdout author, and a scripted builder cell and
verifier stand in for Gnomon's cells. Everything else is the real kernel: the intake panel and the
brief, the spec and its provenance rules, the compiled contract, holdout custody, git lanes, the
gate, escalation, the local preview road, the capability pack, signals, concepts and the updates
inbox. Every decision is made by a fake person named `demo-*`. Nothing the scripted model produces
measures a real model; what was not measured says "not measured".

## What is in it

- **Equipment loans** (web service): the panel's blocking questions wait for a person, and a demo
  business owner has confirmed one assumption. Open it from Home, then **Questions**.
- **Shipment webhook to the stock system** (integration): built through the gate. One task
  escalated after three rounds, a demo developer chose retry, and it passed. Release 1 runs on the
  local preview road and has a capability pack. A chat signal became a change on it, and an
  observation (a new model) opened an update card. See **Tasks**, **Releases** and **Evidence**.
- **Access review check** (ops agent): built through the gate until a task escalated. The
  escalation waits in the **Inbox** with the gate's objections, and its holdout scenario sits in
  holdout custody.
- **Rihmasto itself**: a need raised in a meeting became a concept that waits for a business
  owner on the **Square**.

## A short tour by role

- **Business owner:** Home in the business lens, then the Inbox and the Square: what waits on you,
  and the concept to validate.
- **Product owner:** Equipment loans > Questions and Spec: answer or let Rihma assume, then see the
  criteria and where each came from.
- **Developer:** Shipment webhook > Tasks and the gate timeline: rounds, objections, the retry.
- **Operations:** Releases and the local preview; the update card the new model opened.
- **Compliance:** Evidence: the attestation, the control table and the evidence pack export.
- **Anyone:** press **Ask Rihma** and ask "what waits on me?" or "where do I change the theme?".

The same facts from the command line:

```text
rihmasto --home var/demo status
rihmasto --home var/demo waiting
```
