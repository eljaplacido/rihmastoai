# Use only what you need: modules and presets

Rihmasto is a set of modules. You can use one small part of it, a few parts, or the whole factory,
and change that later. Whatever you use, the same rules hold: models propose and people decide, every
decision names a person and a persona, "not measured" is never shown as passed, holdout scenarios
never reach a builder, and every step is recorded in the hash-chained ledger
([D-0017](../../decisions/D-0017-governance-everywhere.md)).

This page says what is **built** and what is **planned**, then walks through each starting point.

## The modules

**Core** is always on: projects, the Inbox where people decide, the ledger, personas and access, the
autonomy cap, the knowledge graph (its page and each project's Graph tab), the data and context of every
agent (the Data and context page and each project's Context tab), settings, jobs, and attaching a repository of
your own.

| Module | Adds | Needs |
|---|---|---|
| Intake and spec | the panel's questions and assumptions, then a spec with provenance | |
| Plan and contract | the plan a person approves, the hashed contract, the check plan, the holdout custody | |
| Build and gate | builder cells and the gate; the same gate for your own repository, and holdouts against your service | Plan |
| Delivery | paved roads, releases, holdouts against the release, user validation, IT's deploy gate | Build |
| Operations | probes, incidents, shadow and canary with rollback, the updates inbox | Delivery |
| Change loop | feedback and changes triaged back to their stage, stale approvals, lessons | Plan |
| Delivery square and signals | needs arriving as signals, concepts a business owner validates | Intake |
| Capability catalogue and packs | every capability by its state, a capability pack per release | Delivery |
| Security and red team | Rihmasto's own static scan of any repository, SARIF from any scanner, the security gate | |
| Compliance and evidence | evidence packs, with a repository's own releases | |
| Assessment | adopting an existing system: tests characterised, an inventory, its upstream watched | |
| Integrations | website chats, events and notices out, verified webhooks in, connectors | |
| Assistant | Ask Rihma answering from a model through Gnomon; without it the assistant points the way from the cockpit's map | |
| Agent observability (opt-in) | an Agent sessions view per project for developers and IT, read from your own agent observability hub ([guide](agent-observability.md)); off until a person turns it on, in no preset | |

`rihmasto modules show` prints the same table for your factory, with what is on.

## The presets

| Preset | You bring | You get |
|---|---|---|
| Spec only | a need, vague or precise | a confirmed spec and a hashed contract, exported as files with a report; nothing is built |
| Gate my code | your own git repository, and a contract or a spec file | a gate verdict on each change: tests by criterion, fail-first, the independent verifier, holdouts; you merge |
| Assess only | an existing system's repository | the system adopted: its tests characterised, an inventory, its upstream watched |
| Security only | any git repository, or another scanner's SARIF | findings in SARIF, the security gate's verdict, risks accepted until a date |
| Evidence only | a repository and its existing releases | evidence packs a reviewer can judge |
| Capability only | a need for one small capability | a running capability with its capability pack |
| Full factory | any of the above | everything, from need to production, and the loop after |

## Built and planned

**Built**, covered by the tests named after FR-MOD1 to FR-MOD5 in the contract:

- the catalogue, the presets and the sets: the factory's, and a project's own that overrides it; a set is
  chosen by a named person as a business owner, product owner, IT, developer or compliance, and every
  change is recorded in the ledger with who, as which persona, from what, to what and why;
- nothing chosen means the full factory, so a factory home made before modules works as it always did;
- the command line refuses a command of a module that is off, with exit 2 and the command that turns it
  on; the pipeline stops at the edge of the set and says why; the cockpit refuses a write of a module
  that is off (403), never a read;
- the cockpit shows only what is on: the sidebar, the phone's bar, Home's widgets and key figures, the
  widget library, the palette, a project's views and the assistant's suggestions and map; a page of a
  module that is off says which module adds it, and Settings, Modules turns it on;
- a first-run choice on a new factory home, and Settings, Modules for the factory and for one project;
- the other surfaces ask the same set: a website's chat, an inbound webhook, the MCP server's write tools
  and the assistant's model proposals (FR-MOD5); a safety switch (revoking a chat, removing a webhook
  source, ending a subscription, disabling a connector) is never refused;
- an attached repository's tests run through IT's isolation runner while access is enforced, and are
  refused without one; until the access stream's runner (`kernel/access_isolation.py`) is merged here,
  every such run under enforced access is refused (see "Wiring" below);
- each standalone preset from the command line, below.

**Planned:**

- posture presets (prototype, balanced, production, regulated) that follow a preset: each preset already
  names the posture it suggests (`kernel.modules.suggested_posture`), and nothing enforces it yet;
- the gate for repositories whose suites are not Python unittest: the gate runs a Python unittest suite
  under `tests/`, as it does for the factory's own products; other suites are not measured;
- a person's sign-off on a repository's release, so an evidence pack of an attached repository can read
  *attestable*: today it lists each release with what the kernel saw there, and reads *insufficient
  evidence* until a release went through the factory or a person decided something there;
- the brownfield assessment report and a capability's faces (MCP, OpenAI-compatible, embed), which plug
  into the Assessment and Capability modules when they land (see "Wiring" below).

## Tutorial: choose a set

**In the cockpit.** On a new factory home the cockpit asks once where to start. Pick a preset with the
mouse or the arrow keys, write your name, choose the persona you choose as, and press *Start with
this*. *Decide later* keeps everything on and records nothing. Later, open **Settings**, then
**Modules**: choose *This factory* or a project, a preset or the modules you tick, give a reason, and
press *Save the modules*. Ticking a module ticks what it needs; unticking one unticks what needs it.
A project ticks *Use the factory's set* to follow the factory again.

**On the command line.**

```bash
rihmasto modules presets
rihmasto modules set --preset spec_only --person Aino --persona business_owner --reason "the spec first"
rihmasto modules set --enable security --person Aino --persona developer
rihmasto modules set --project <pid> --modules intake,plan,change --person Aino --persona product_owner
rihmasto modules set --project <pid> --inherit --person Aino --persona product_owner
rihmasto modules show --project <pid>
```

**Ask Rihma.** "Which modules are on?" or "Where do I turn on the square?" opens Settings, Modules. A
question about something that is off says which module adds it.

## Tutorial: spec only

A need becomes a confirmed spec and a hashed contract, and nothing is built.

```bash
rihmasto modules set --preset spec_only --person Aino --persona business_owner
rihmasto new "Equipment loans" --source "Our team keeps losing track of who borrowed what" --requested-by Aino
rihmasto run <pid>        # questions go to people; once answered, the spec and the contract are compiled
rihmasto contract export <pid> --out exports --person Aino --persona product_owner
```

`run` stops once the contract is compiled and says so. The export folder holds `spec.json`, `spec.md`,
`contract.json`, `checkplan.json`, `brief.md`, `REPORT.md` (who answered what, what was assumed and until
when, every decision with its person and persona) and `MANIFEST.json` with the sha256 of every file.
Holdout scenarios stay in their custody: the check plan only names which criteria they hold. The export
is recorded in the project's ledger, and a second export never replaces the first.

## Tutorial: gate my code

Bring your own repository. Rihmasto judges each change with the gate its builder cells meet, and never
merges, pushes or writes to your repository: every check runs in a temporary clone of a committed
revision.

```bash
rihmasto modules set --preset gate_my_code --person Aino --persona developer
rihmasto repo attach "Calculator" --repo ../calculator --contract ../contract.json --person Aino --persona developer
rihmasto repo gate <pid> --head my-branch --task T-001 --person Aino --persona developer
```

- **The contract.** `--contract` takes a contract file; its revision is recomputed from its content, and
  a stated revision that does not match is refused. `--spec` takes a spec file (JSON), which the
  compiler turns into a contract with no model, each requirement endorsed by you. Without either, the
  repository's own `contract.json` on its branch is used if it is one. `rihmasto repo contract` gives a
  contract later.
- **The gate.** The repository's whole unittest suite runs; with `--task`, every visible criterion of the
  task must be named by a test that ran (`test_R_1_AC_1_...`) and those tests must fail at the base; the
  independent verifier reviews the change through Gnomon; a change to the contract file or a `.gnomon/`
  surface is a violation. `--no-verifier` leaves the verifier out, and the gate then reads not measured,
  never passed. The command exits 0 when the gate passed, 1 when it failed and 4 when it is not measured.
  Each run is recorded in the project's ledger with who asked, as which persona, and the revisions.
- **Holdouts.** Keep scenarios outside the repository, so the people and agents who build there never
  see them, and hand them in: `rihmasto repo holdouts <pid> --import ../holdouts --person Kaisa
  --persona it`. Each file is one criterion's scenario, `{"criterion": "R-1-AC-2", "steps": [...]}`, in
  the shape the holdout author writes. With a spec, `--author` has the holdout author write the missing
  ones through Gnomon. Start your service, then `rihmasto repo holdouts <pid> --base-url
  http://127.0.0.1:8000 --person Kaisa --persona it` runs them; the ledger keeps each criterion's
  verdict, never a scenario's steps.

The gate runs your repository's tests on this machine, as adoption does. With a single operator they run
as your own account, so attach only code you would run. With access enforced
([the access guide](access.md)), they run only through the isolation runner IT names in the access file;
without one, `repo gate` and `repo releases --check` are refused (exit 2) before anything is cloned.

## Tutorial: assess only

```bash
rihmasto modules set --preset assess_only --person Aino --persona it
rihmasto adopt "Loans" --source ../loans --intent monitor --base-url http://127.0.0.1:8080 --person Aino --persona it
rihmasto sync <pid>
```

Adoption is described in [the brownfield guide](../brownfield.md).

## Tutorial: security only

```bash
rihmasto modules set --preset security_only --person Ilkka --persona it
rihmasto repo attach "Billing" --repo ../billing --person Ilkka --persona it
rihmasto repo scan <pid> --person Ilkka --persona it
rihmasto security status <pid>
rihmasto security accept <pid> SEC-1-1 --reason "only called with literals" --expires 2027-01-31 --person Ilkka --persona it
```

`repo scan` runs Rihmasto's own static layer ([the security guide](security.md)) over a committed
revision (`--revision`, default HEAD) and hands its SARIF to the security gate, as `security ingest`
does for another scanner's file. A scan that measured nothing is recorded as not measured.

## Tutorial: evidence only

```bash
rihmasto modules set --preset evidence_only --person Kaisa --persona compliance
rihmasto repo attach "Billing" --repo ../billing --contract ../contract.json --person Kaisa --persona compliance
rihmasto repo releases <pid> --check --person Kaisa --persona compliance
rihmasto evidence <pid> --out evidence --person Kaisa --persona compliance
```

`repo releases` records the repository's tags: each tag, the commit it names and its date, marked as
git's claims, signed by you. With `--check` the kernel also runs the suite and, with a contract, the
trace of each criterion at each release's commit. A tag that moved is recorded again with the commit
it moved from. The evidence pack carries them as `repository-releases.json`, with a line in its README.

## Tutorial: capability only and the full factory

Capability only is the chain from a need to a running capability with its capability pack, without the
change loop, operations, the square, security, compliance, assessment, integrations or the model
assistant. The full factory is everything; [How it works](../how-it-works.md) walks through it.

## What a module that is off does

- **Its records stay.** Turning a module off deletes nothing; turning it on shows everything again.
- **Its commands are refused** where it is off: `rihmasto signal list` in a spec-only factory says which
  module it belongs to and the command that turns it on, and exits 2.
- **Its writes are refused** in the cockpit (403); reading is never refused. The MCP server's write
  tools are refused the same way: `rihma_signal` while the square is off, `rihma_report_change` while
  the change loop is off where the project is. A comment is core.
- **Its website chats take no message.** A chat made while Integrations was on answers the website
  "this chat is turned off" while Integrations, or what the chat files into, is off: the square for a
  chat for needs, the change loop of its project for a feedback chat. Nothing is filed.
- **Its webhooks store nothing.** A ring from a source IT added while Integrations was on, with a
  signature that holds, is answered 403 "this source is turned off" while Integrations, or what the
  source files into (the square for a signal, the change loop of its project for a change), is off.
- **A safety switch is never refused.** What stops something still live is core, with the list it is
  found in: `embed list` and `embed revoke`, `hooks list` and `hooks remove`, `relay list` and `relay
  unsubscribe`, `connector status` and `connector disable`, and the cockpit's *Revoke*. Settings keeps
  listing the chats made before, says Integrations is off and offers *Revoke*; only *Create a chat* is
  gone.
- **The assistant does not propose it.** A model's proposal that acts through something of a module that
  is off (a change report, a page, a widget to add) is not offered; it is listed as dropped, with the
  module and that Settings, Modules turns it on.
- **The pipeline stops** at its edge: spec only stops once the contract is compiled, a set without
  delivery stops once the work is built and gated. The stop is recorded once.
- **The cockpit hides it** and says where it went: a note on Home names the widgets it hides, the widget
  library says how many more there are, and a page opened by its address names its module.

## Tutorial: turn Integrations off without leaving a chat running

1. Open **Settings**. Under **Modules**, untick *Integrations* (or choose a preset without it), give a
   reason and press *Save the modules*.
2. The **Embeds** card stays while there are chats made before. It says *Integrations is off*: those
   chats now answer a website "this chat is turned off" and file nothing.
3. To stop one for good, press its *Revoke* (or Tab to it and press Enter). The row says *Revoked*, and
   the ledger records who revoked it, as which persona. From the command line: `rihmasto embed list`,
   then `rihmasto embed revoke E-001 --person Aino --persona business_owner`.
4. Webhooks are the same: a ring answers 403 while Integrations is off, and `rihmasto hooks list` and
   `rihmasto hooks remove <source> --person Ilkka --persona it` stop a source for good.
5. Turning Integrations on again brings back the chats that were not revoked. Ask Rihma "How do I revoke a
   chat?" and *Take me there* opens Settings at the Revoke button.

## Wiring for the parallel work

The modules are a catalogue in `kernel/modules.py`. Work that lands beside it plugs in with two hooks:

- **`modules.extend(module, commands=..., outputs=..., pages=..., views=..., widgets=..., controls=...,
  routes=..., planned=...)`** adds names to a module. A capability's faces add their command and their
  output to `capabilities`, for example `extend("capabilities", commands=("faces",), outputs=("an MCP
  face",))`; the brownfield assessment adds its report to `assessment` (its `assess` command is
  already listed there). A name two modules list is shown while either is on.
- **`modules.suggested_posture(factory)`** returns the posture a preset suggests: `balanced` for gate my
  code and the full factory, `regulated` for evidence only, `prototype` for capability only, none
  for the others. The posture presets read it as a default; nothing here enforces a posture.

- **`attach.outside_code(project)`** wraps every run of an attached repository's own tests (`repo gate`,
  `repo releases --check`). When the access stream's `kernel/access_isolation.py` is merged, it calls
  `access_isolation.require(factory, access_isolation.SUITE)` before anything is cloned and runs the
  tests inside `access_isolation.serving(factory)`, so `kernel.gate.run_suite` takes IT's runner. Until
  then, with access enforced it refuses (`attach.IsolationNeeded`, exit 2). Nothing to wire at the merge
  but keeping those two names.

The command line refuses a command of a module that is off through `modules.allowed`, the cockpit a
write route through `modules.require_route`, and the MCP server a write tool through
`mcp/server.py` `WRITE_ROUTES` (each tool that writes names the cockpit route whose module it asks): a new
command or route is core until a module names it. A safety switch stays core, as `embed revoke` and
`post_embed_revoke` are. A surface that runs on its own asks `modules.first_off(factory, needed, pid)`:
a website's chat through `embeds.turned_off`, a webhook through `hooks.turned_off`. The data systems
work (`kernel/integration_decl.py`, `connectors/`) wires a connector that acts on its own the same way,
and keeps its stop command core.
