# Walkthroughs in Ask Rihma

Tell Rihma what you have, and it walks you through it in the chat, step by step: "I have an existing
project", "I have a new idea", "how do I get started". Rihma asks one thing at a time, offers the
answers it expects as buttons, shows what it finds, and waits. Nothing changes until you press the
Confirm button of a proposal, and that click is signed with your name and persona, exactly like
Ask Rihma's other proposals (FR-WLK1).

## Start one

In the cockpit:

- **Home**: the **Walkthroughs** button in the page header. While the factory has no project yet,
  Home also shows a card, "New here? Let Rihma walk you through it", with every walkthrough.
- **Ask Rihma** (the chat, `/`): the flag button in its header, and the list in its empty state.
- **In plain words**: ask Rihma "I have an existing project", "minulla on olemassa oleva
  projekti", "new idea", "uusi idea", "how do I get started", "miten pääsen alkuun?" or "set up a
  model", and the answer carries a **Walk me through it** button. Without a model this is by rule,
  in English and Finnish; with a model, the model may suggest one too. Nothing starts until you
  press the button.

On the command line, the same walkthrough runs in the terminal:

```bash
rihmasto walkthrough plug_in --person "Aino Example" --persona developer
rihmasto walkthrough tour --person "Aino Example" --persona developer --resume WT-001
rihmasto walkthrough list
```

Type the number of an option or your answer; `yes` confirms a proposal, `back` goes back a step,
`/map` shows a scanned folder's full map, `/cancel` ends the walkthrough and `/quit` leaves it to
resume later. There a confirm runs the command line's own commands (`rihmasto adopt`, `rihmasto new`,
`rihmasto models set`, `rihmasto settings`, `rihmasto shape`), and an adoption or an intake runs while
you wait, with its progress on the terminal.

## The walkthroughs

### Plug in an existing project

1. **Which project?** Type the folder's path on this machine, or a git address. Folders you gave
   before are offered as buttons. The folder is checked first: the cockpit reads folders under your
   home folder and the roots the operator lists in `RIHMASTO_SOURCE_ROOTS`, never a system folder
   or a folder of keys. If it may not read yours, Rihma says so and how the operator allows it.
2. **The scan**, in the chat: how many files would be read, summarised, listed and skipped, the
   code's languages, the AI-tool setup it found (an `AGENTS.md`, a `CLAUDE.md`, Cursor or Copilot
   rules, an `.mcp.json` and the like), and the files it skipped as secret-looking, which are never
   opened or sent. **See the full map** opens the same map as New project's scan step, where you
   untick files; Rihma scans again without them. Nothing is sent or recorded by the scan. A
   folder with no code is offered as documents for a new project instead.
3. **What should it be called?** The folder's name is offered.
4. **Is it confidential?** Then every model call for the project stays on a model on this machine
   or your own network. If a role it needs goes to a hosted model now, Rihma names the role and
   the host and offers **Set up a model now**: that walkthrough runs, and this one waits and comes
   back where it was.
5. **What should Rihmasto do with it?** Monitor, Maintain or Improve.
6. **Which posture?** No posture is the default; each posture says in one line what it does.
7. **Adopt <title>**: the proposal, with what it will do. Press it to start the adoption, the
   same as New project's Adopt. The chat waits on the job and shows its progress (fetching the
   code, reading it, running its own tests once for a baseline, recording), then the result: the
   baseline, the kind of work proposed (or, when the README leaves it unclear, the kinds as
   buttons, and Set the kind as a proposal), What's next with its buttons, and **Open the project**.

### Start from a new idea

Say the idea in a sentence or two. Then **Shape it in chat** opens a conversation with Rihma with
your sentence carried over (when you press **Open Shape it in chat**), or **Quick start** asks for a
title, one paragraph and the maturity, proposes **Create the project**, waits for the intake and
shows its first questions as buttons that open them.

### Start from documents

A folder of material (a spec, notes, slides) or one file: scanned in the chat as in Plug in, then a
title, confidential and the posture, and **Create <title>**, the same as New project with a folder.
The chat waits for the intake and shows its first questions. A confidential project is refused
while the analyst's model is hosted: Rihma says so before, and offers Set up a model.

### Set up a model

Each role with its model, host and readiness, then which role, where the model runs (a server on
this machine, a hosted OpenAI-compatible provider, or a host on your own network, which confidential
projects may use), the base URL (presets as buttons), the model and the NAME of the environment
variable that holds the key. Never type a key into the chat: one that looks like a key is not kept,
and Rihma says to change it at the provider. To store a key, use the form in Models setup.
**Set the <role>** writes this machine's routing overlay, as Models setup does, and **Run Test**
sends a tiny prompt and says how fast it answered, or the error.

### Get started

A five-stop tour: Home, the Inbox, a project's overview with What's next, Project settings and Ask
Rihma itself. Each stop takes you there and highlights the place; Next and Back move on.

## What is kept, and what is recorded

- A walkthrough is kept per person under the factory home's `_walkthroughs/` (one file each, with
  the conversation), and resumes after a reload or on the command line with `--resume`. A person
  has one going at a time: starting another ends it, and **Cancel** ends it at any step. What you
  confirmed stays; nothing else is done or undone.
- The factory's ledger records `walkthrough_started`, `walkthrough_step` and `walkthrough_done`,
  signed, with ids and step names only. A path or an answer you typed stays in the walkthrough's
  own file.
- Each Confirm goes through the cockpit's own route for it (adopt, New project, Models setup,
  Project settings, Shape it in chat), with the same module check, signing, access and isolation
  checks. A refusal is said in the chat, and nothing changed.
- With a model (the assistant's role), a typed answer the rules cannot place is read into one of
  the offered options, and the chat says it was the model's reading. The model never decides for
  you, and a confidential walkthrough is not sent to a hosted model.

## The API

| Route | What it does |
| --- | --- |
| `GET /api/walkthroughs?person=` | the walkthroughs on offer, and yours if one is going |
| `GET /api/walkthroughs/<id>` | a walkthrough, with the job it waits on and its progress; writes nothing |
| `POST /api/walkthroughs` | start one (`name`, `said`, `replace`), or resume yours of that name |
| `POST /api/walkthroughs/<id>/reply` | `text`, a `choice`, the `exclude` list from the full map, or `job: true` once the job ended |
| `POST /api/walkthroughs/<id>/confirm` | carry out the proposal it waits on, through the cockpit's own route |
| `POST /api/walkthroughs/<id>/cancel` | end it |

Every write is signed with `person` and `persona`; with access enforced, the verified person, and a
walkthrough answers only the person who started it. See also [The cockpit](../cockpit.md),
[Inputs](inputs.md), [Shape it in chat](shape-in-chat.md), [Models setup](models-setup.md),
[Postures](postures.md) and [Change anything](change-anything.md).
