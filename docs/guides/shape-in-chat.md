# Shape it in chat

Not every need starts as a written plan or a filled-in form. With **Shape it in chat** you open a
conversation with Rihma, start with nothing, a sentence or a file, and work out together what is
needed. When the draft is good enough, you create the project from it (D-0022, FR-SHP1).

## Start a conversation

In the cockpit:

- **Home**: the **Shape it in chat** button in the page header;
- **New project**: choose **Shape it in chat** under "Start from", then **Open the chat**;
- or ask Rihma: "I want to figure out the spec in a chat" takes you there.

Write a first message if you have one, and attach a file or a folder if you want to (both are
optional), then **Start the conversation**.

On the command line:

```bash
rihmasto shape --person "Aino Example" --persona business_owner                # interactive
rihmasto shape --person "Aino Example" --persona business_owner --attach notes.md
rihmasto shape --resume SH-001 --person "Aino Example" --persona business_owner
```

In the interactive chat, type to talk with Rihma. `/attach PATH` adds a file or a folder,
`/draft` shows the draft, `/edit FIELD TEXT` changes a field, `/create` makes the project and
`/quit` leaves (the conversation is kept, and `--resume` goes on with it).

For scripts, every step is its own command and prints JSON:

```bash
rihmasto shape start --text "Our team loses track of borrowed drills" --person ... --persona ...
rihmasto shape say SH-001 "The team members borrow them" --person ... --persona ...
rihmasto shape attach SH-001 notes/ --person ... --persona ...
rihmasto shape edit SH-001 scope_out "Billing; Repairs" --person ... --persona ...
rihmasto shape show SH-001 [--brief]          # show every conversation without an id
rihmasto shape create SH-001 --maturity demo --person ... --persona ...
```

## The conversation

Rihma is the **analyst** role, asked through the same model plumbing as intake (Gnomon in the
analyst lane; [Models setup](models-setup.md) says which model that is). Rihma asks one or two
questions at a time, the ones whose answers change most what gets built, and answers in your
language.

**Attachments.** A file or a folder, read by the same rules as the folder scanner
([inputs](inputs.md)): text and Markdown, Word, PowerPoint, Excel, OpenDocument, HTML, CSV, JSON,
YAML and PDF with a text layer. A folder is scanned as intake scans one: the most telling documents
first, code as an inventory, secret-looking files never read. A file it cannot read (a scanned PDF,
an image) is refused with why and a request to paste its text; nothing is skipped in silence. In the
cockpit a file is sent from your browser (up to about 900 KB); a larger file, or a folder, is given by
its path on the machine that runs the cockpit.

**No model yet.** If no model is set up, the chat says so and links to Models setup. Your messages
are kept; say it again once a model answers. A model that fails is said the same way, with its
error.

## The draft brief

Beside the chat, the draft takes shape:

| Field | What it holds |
|---|---|
| Title | the project's name |
| Who it is for | the users and roles |
| The problem | what goes wrong today |
| Outcomes | what it should bring, and how success is measured |
| In scope / Out of scope | the first version, and what it leaves out |
| Constraints | budgets, deadlines, technologies, rules |
| Data and systems | the data it holds, and the systems it talks to |
| Open questions | what is still to decide |

You can edit any field and **Save the draft**. A field you edited is yours: Rihma's later drafts
leave it as you wrote it, and if Rihma would change it, it says so in the chat. Rihma never puts
words in your mouth: what it only supposes goes under open questions.

The draft is **good enough** when it says who it is for, the problem, an outcome and what is in
scope. The panel under the draft says what is still needed, and Rihma says so in the chat too.

## Create the project

**Create the project from this** asks for the work profile, the mode and the maturity, with Rihma's
suggestion and why (the profile by rule over the draft's words when Rihma names none). Then:

- the project is created as **New project** creates one, signed by you, and its intake runs as a job;
- the draft becomes the project's **request**: a Markdown brief whose headings name the checklist's
  facets (users and roles, goals and success measures, scope, constraints, data and systems), so
  intake reads them as **given** and never asks them again ([Inputs](inputs.md)); open questions stay
  questions;
- the conversation is kept with the project (`shape.json`) and the project's ledger records
  `shaped_in_chat`.

A conversation that became a project takes no more messages.

## What is kept

- The conversation: `<home>/_shape/<id>/shape.json`, and each attachment's text in `files/`.
- The factory's ledger: `shape_started`, `shape_said`, `shape_attached`, `shape_draft_edited` and
  `shape_created`, each signed by the person and persona (with access enforced, the verified
  identity). A message's words stay in the conversation's file; the ledger has their length and
  sha256.

## The API

| Method and path | What it does |
|---|---|
| `GET /api/shape` | every conversation, newest first, and whether a model is set up |
| `GET /api/shape/<id>` | one conversation with its draft, what is still needed, Rihma's suggestion and the brief |
| `POST /api/shape` | `{text?, attach?, title?, person, persona}`: opens one; Rihma answers beside the request |
| `POST /api/shape/<id>/say` | `{text, person, persona}`; the answer comes in a moment (`pending` until then) |
| `POST /api/shape/<id>/attach` | `{attach: {path} or {name, text} or {name, data_base64}, person, persona}` |
| `PUT /api/shape/<id>/draft` | `{draft: {field: value}, person, persona}`: your own words in the draft |
| `POST /api/shape/<id>/create` | `{profile?, mode?, maturity?, person, persona}`: the project, its intake as a job |

## Not yet

D-0022 also asks that each answer given in the chat be signed as an Inbox answer is, and that a
website's need-chat hand over to a conversation here. Both are still to come: today the draft
becomes the project's request, and the panel's questions that remain go to the Inbox as usual.
