# Inputs: any input, from any author

A need can arrive as one vague sentence from a business user, as an expert's precise specification,
as a complete plan with a few gaps, or as a folder of documents, in English or Finnish. Rihmasto reads
each for what it is ([kernel/input_kind.py](../../kernel/input_kind.py)). What the input states is
recorded as given by its author, with its lines, and never asked again. A facet checklist finds what it
does not state, and the project's mode settles those gaps. The intake summary shows **from your input**,
**asked** and **assumed** side by side.

| | Status |
|---|---|
| Reading the kind, language and facts by rule; the facet checklist; the screening of questions | Built |
| The checklist's own questions for the gaps of a specification, a plan or a folder | Built |
| An expert's requirement ids and wording kept through the spec; a plan's decisions kept as given | Built |
| A model's refinement, kept as a proposal (`rihmasto inputs refine`) | Built |
| The intake summary: `rihmasto inputs summary`, the cockpit's Questions view, Ask Rihma | Built |
| Posture presets that change which gaps are asked | Hook built; the presets come with the posture work |
| A person confirming a model's proposal so it counts as given | Planned |
| Facts as nodes of the knowledge graph | Planned (an ontology change is the owner's) |
| Any folder, scanned: Word, PowerPoint, Excel, OpenDocument, HTML, CSV, JSON, YAML, TOML, PDF, logs and code | Built (FR-MAT1) |
| The preview before anything is sent: `rihmasto scan`, `new --yes`, the cockpit's "Scan the folder" step | Built |
| Confidential material kept on local models | Built |
| Text from scanned PDFs (OCR), legacy `.doc`/`.xls`/`.ppt`, PDF fonts with their own encodings | Not built: listed, with why |

## Any folder: the material map

Give intake a folder, any folder: a project's working folder with its notes, slides, sheets, PDFs and
code. Rihmasto does not expect certain file names. It walks the folder by rule, with no model
([kernel/material.py](../../kernel/material.py)), and says for **every** file what happens to it:

| What happens | When |
|---|---|
| **read** | its text goes into the request in full |
| **summarised** | part of it goes in: a log's first and last 15 lines, a sheet's or a CSV's header and first rows, a JSON, YAML or TOML file's keys and a short sample, or the first part of a long document when the budget is short |
| **listed** | it is named, not read: code (it becomes the code inventory), pictures and other binaries, housekeeping files (changelog, licence, security policy, contributing), a PDF with no text layer, a document the budget had no room for |
| **skipped** | excluded by you, or it **may hold secrets**: `.env` files (not `.env.example`), keys (`*.pem`, `*.key`, `id_rsa*`), `credentials*`, `*secret*`, key stores and Terraform state are never opened; any other file whose text holds a credential (a known key format, a private key, a random value assigned to a password or token name; [kernel/redteam/secretscan.py](../../kernel/redteam/secretscan.py)) is not read |

Dependency, build, cache, virtual-environment and version-control folders (`node_modules/`, `.venv/`,
`__pycache__/`, `build/`, `dist/`, `target/`, `.git/` and the like) are not walked, and a link is
never followed. A scan looks at the first 5,000 files and counts the rest.

**The formats** ([kernel/material_read.py](../../kernel/material_read.py), standard library only):
Markdown, reStructuredText and text as they are; HTML with its scripts and styles dropped, its entities
decoded and its headings kept as `#` lines; Word (`.docx`) paragraphs with their headings; PowerPoint
(`.pptx`) slides in the deck's own order, each under "Slide N"; Excel (`.xlsx`) sheets by name with
their header and first rows; OpenDocument text, slides and sheets (`.odt`, `.odp`, `.ods`) the same way;
CSV and TSV; JSON, YAML and TOML by their structure. A **PDF** is read from the strings of its text
operators, in uncompressed or Flate streams: it is always marked **partly read**, because layout,
tables and fonts with their own encodings may be lost. A scanned PDF has no text layer: it is listed as
"not read: no text layer".

**The kinds.** Each file is classified by its format, its name and then its words
([kernel/material_kinds.py](../../kernel/material_kinds.py)): brief or spec, plan, review or comments,
handover, notes, deploy or run log, data, slides, code, other. **Code is never read as text.** It becomes
an inventory: its languages by extension with file counts, entry points, test folders, dependency
manifests with the packages they name, CI workflows and Dockerfiles.

**The budget** is the intake's limit, 40,000 characters. The most telling files are read first: the
README, then briefs and specs, then plans, reviews, handovers and the code inventory, then notes,
slides and other documents, then data and logs. A long file is summarised to its first part; when no
room is left, a file is listed. **Nothing is cut silently**: the map's `cut` names every file that was
summarised or listed for the budget, and why.

The request the panel reads is built from the map, each part headed with its file and its kind
(`## docs/requirements.md (brief or spec)`), and each part is then read as its own document by the
rules below. A single file given as the source is read by its format the same way, and refused when it
may hold secrets.

## See what leaves before it leaves

Whatever is read is sent to the analyst's model endpoint, which may be a hosted provider. So the person
sees the map first, and nothing is sent until they confirm.

```bash
rihmasto scan ~/work/lobby-register                      # the map: read, summarised, listed, skipped, and why
rihmasto scan ~/work/lobby-register --exclude "drafts/" --exclude "*.xlsx" --json
rihmasto new "Visitor register" --source ~/work/lobby-register --requested-by Aino     # shows the map, then asks
rihmasto new "Visitor register" --source ~/work/lobby-register --requested-by Aino --yes --exclude "drafts/"
```

`scan` sends nothing. It ends with the characters the request comes to and where they would go: the
analyst role's endpoint, local or hosted. `new` and `intake` with a folder print the same map on stderr
and need `--yes`, or "y" at the prompt when a terminal is attached; without either, nothing is created
and nothing is sent (exit 2). `--exclude` takes a path, a glob (on the path or the name) or a folder,
and is repeatable.

In the cockpit, **New project** takes a folder on both paths: in **An existing project**, or as the
path of a folder in the need field. The button then reads **Scan the folder**: it shows the map grouped
by what happens to each file (read, summarised, unticked by you, listed, skipped with its reason), and
what it comes to. Untick a file to leave it out: the step scans again without it, so what you see is
what is sent. Only then does the button create the project or adopt it. The cockpit reads a folder
only for a persona that may create or adopt a project (business owner, product owner, developer, IT),
signed like any write, and only under your home folder or a root the operator named in
`RIHMASTO_SOURCE_ROOTS`; never a system folder or a folder of keys (`.ssh`, `.gnupg`, `.aws`).

What is recorded: the project keeps the map you confirmed (`material.json`, with your exclusions), and
the ledger's `material_scanned` record holds its counts, the request's sha256, who confirmed it and how
(`--yes`, at the terminal, or in the cockpit's scan step). Never a file's contents.

## Confidential material: keep it on local models

Mark a project **confidential** when its material must not leave for a hosted model:
`rihmasto new ... --confidential`, `rihmasto adopt ... --confidential`, or the **Confidential: keep on
local models** box in New project ([kernel/confidential.py](../../kernel/confidential.py)). The setting
is recorded (`confidential_set`, with who set it and the routes it holds to). While it is set, intake,
the spec, the holdouts, a build and its verifier, a refinement and a run may only call a model whose
endpoint is on this machine (loopback) or a private network address: the routes in
`kernel/routing.json` with this machine's `kernel/routing.local.json` over them, fallbacks included. A
role that would go to a hosted endpoint is **refused**, never sent: the message names the role and its
endpoint and points at [local-models.md](local-models.md), and `confidential_refused` records where. A
run stops in a `refused` state; the command line and the cockpit refuse before a project is created. A
change on a confidential project is triaged by rule instead, and Ask Rihma answers from the cockpit
map. An endpoint counts as local by its address (`localhost`, `127.0.0.1`, `10.x`, `192.168.x`,
`172.16-31.x`, `::1`, a tailnet's `100.64-127.x`) or a name reserved for private networks (`.local`,
`.lan`, `.internal`, `.home.arpa`). Any other host name is taken as hosted, since Rihmasto does not
resolve names. A model server on your own network that you reach by name (a GPU box on a tailnet or a
VPN) is local once you say so: tick **On my own network** in Models setup, or
`rihmasto models set <role> --base-url http://<name>:<port>/v1 --model <name> --private`, which writes
`"private": true` on its endpoint in `kernel/routing.local.json`.

## The kinds of input

The kind is decided by fixed rules, in this order. The reading names the rule that fired (its *basis*),
and says *certain* or *uncertain*.

| Kind | Read so when |
|---|---|
| specification | two or more requirements carry the author's own ids (`TLR-001`, `FR-KRIT-7`) and there are acceptance criteria or requirement-like sentences |
| plan | two or more decisions, or four or more headings that state five or more facets |
| reference | mostly table rows (a data inventory in a folder) |
| need | at most 150 words and at most one heading |
| folder | a folder with two or more documents: each document is read as its own kind |

Anything else falls back to an uncertain reading: many *must* and *should* sentences read as a
specification, several headings as a plan, the rest as a need told at length. The language is English,
Finnish, or mixed when a folder holds both.

## What your input states: the facet checklist

The checklist has thirteen facets. A fact states one of them when:

- a heading names it (`## Users and roles`, `## Tietoturva`), for the lines of its section;
- a label names it (`Users: ...`, `Out of scope: ...`, `Käyttäjät: ...`), on that line;
- a sentence carries one of its cues (`single sign-on`, `GDPR`, `within five seconds`, `käyttäjinä`);
- a requirement has given / when / then criteria (the acceptance facet);
- a decision names it (`D1: ...`, `Decision 2: ...`, `Päätös 3: ...`, or an item under a "Decisions"
  heading).

A section that only says `TBD`, `open` or `avoin` leaves its facet open, and the reading records the
lines that do so. Every fact keeps its document and its lines, and quotes the author's own words.

| Facet | Asked from | Blocking in mixed mode |
|---|---|---|
| users and roles | explore | yes |
| outcomes and success measures | explore | yes |
| scope and out of scope | explore | yes |
| data and its sensitivity | demo | yes |
| acceptance criteria | demo | no |
| integrations, security, privacy, accessibility and languages, deployment and environments, constraints | pilot | no |
| availability, performance | production | no |

## Never asked again

The panel is told, in the prefix every perspective shares, what the input states and what its gaps are.
A panel question is not asked only when it **restates** the input. Two things must both hold:

- every facet it asks about is one the input states;
- every word of its own appears in what the input states for those facets, or in the input's titles.
  Words that name the facet, and asking words such as *who*, *should* or *the*, are not counted.
  A word with another ending counts as the same word (*register*, *registers*).

Such a question is kept under "not asked", with the facts it rests on, and the ledger records it. Any
other question is asked. That covers a question that touches a gap as well (authentication of a webhook
the input names, when security is a gap). It also covers a question about a detail the input never
mentions, even when it names a stated facet: "Can users delete a tool from the register?" is asked,
although the specification names its users.

**A blocking question always reaches the mode**, so in mixed or socratic mode a person sees it. When it
restates the input, its rationale quotes the facts and their lines ("Your input already states: ..."),
so the person can confirm the fact instead of writing the answer again. The reading keeps it under
`restated_blocking`, and the ledger's `input_screened` record lists it too.

For a need, one sentence rarely settles a work profile's standing questions, so those are asked anyway.
For a specification, a plan or a folder, a profile question the input already answers is not asked.

## The gaps, and the mode

For a **specification, plan or folder**, the checklist asks its own question for each gap that no other
question covers, from the maturity that needs it (the table above). Each question carries a proposal,
first among its options, so the mode can settle it:

- `socratic`: every question goes to a person, as an Inbox card;
- `assume`: each is assumed, with a due date 14 days on;
- `mixed`: a blocking gap goes to a person, the rest are assumed.

For a **need**, every facet is a gap, so the gaps are the panel's to ask within its budget for the
maturity. The checklist adds no question of its own, and the summary shows each facet nobody asked about
as "not stated, not asked".

A posture preset can change which gaps are asked. `GAP_POSTURES` in
[kernel/input_intake.py](../../kernel/input_intake.py) is the hook: `prototype` asks only users,
outcomes and scope; `regulated` also asks data, security, privacy, constraints and acceptance at any
maturity. A project's posture is read from its `posture` setting once the posture work sets it.

## An expert's specification

The author's requirements keep their ids and wording. When the analyst's draft names a requirement by
the author's id, the spec keeps the author's statement and given / when / then criteria word for word,
with the draft's criterion kinds by place (at least one stays a visible test). A requirement the draft
left out is kept as the author wrote it and marked *restored*. Provenance follows the kernel's rule: each
is *customer-endorsed* by whoever asked, or *customer-confirmed* when it also rests on a person's answer.
Beyond the maturity's limit the analyst's own requirements are dropped
first, and every drop is listed in the spec with its reason.

## A plan's decisions

A plan's decisions arrive as given. They stand in the brief as `[owner: decided in the input]`, with
their lines. They are never turned into assumptions, questions or decisions in the canon: a decision in
the canon always names a person and a persona who made it in Rihmasto.

## A model may refine the reading

`rihmasto inputs refine <pid> --person <you> --persona <persona>` asks the analyst's model, through
Gnomon, whether the rule missed anything. Its answer is kept beside the rule's reading as
`model_proposed`:

- only facets of the checklist, on lines that exist in the request, are kept, and the kernel quotes
  those lines itself; everything else is listed with why it was left out;
- it changes no kind, no question and no decision; the rule's reading stands;
- a named person asks for it; a model is never the one who asks;
- when no model answers, it is *not measured* and nothing is written.

## The intake summary

The cockpit's **Questions** view of a project starts with the intake summary: how the input was read,
then three columns, **From your input** (facts, decisions and requirements, each with its document and
lines), **Asked** (with the answer and who gave it) and **Assumed** (with the assumption and its due
date). Below them: the questions not asked because the input already says it, and the facet checklist
with every facet's state (given, answered, asked, assumed, left open, or not stated and not asked).

On the command line:

```bash
rihmasto inputs read tests/fixtures/inputs/plan-full.md --maturity production   # how it would be read; writes nothing
rihmasto inputs summary <pid> --text                                           # the summary, readable
rihmasto inputs summary <pid>                                                  # the same, as JSON
```

## What is recorded

Every intake writes the same trace (D-0017), whatever the kind of input:

- `inputs.json` in the project's folder: the reading, the questions not asked, the checklist's
  questions and any model proposal;
- `input_read` in the ledger: who asked, the kind and how it was decided, every fact with its facet,
  document and lines, the author's requirement and decision ids, and the request's sha256;
- `input_screened`: each question not asked with the facts it rests on, each blocking question that
  restated the input (asked all the same), the checklist's questions, and the gaps;
- `input_refined`: who asked for a refinement, the rule's kind and the model's, and the lines it cited;
- `intake_done` carries the input's kind;
- for a folder: `material.json` (the map: every file, what happened to it and why, never a file's
  contents) and `material_scanned` in the ledger (the counts, the request's sha256, who confirmed it and
  how); for a confidential project, `confidential_set` and every `confidential_refused`.

## Tutorial: a folder of material (5 minutes)

1. **Scan it.** Run `rihmasto scan <a folder of yours>`: a project's working folder with slides, sheets,
   PDFs and notes is fine. Read the four groups. Secret-looking files are under **Skipped**, unopened;
   code is one line, counted in the code inventory.
2. **Leave something out.** Run it again with `--exclude "drafts/"` or a file's path: that file moves
   to Skipped, "excluded by you", and the total drops.
3. **In the cockpit.** Press **New project**, paste the folder's path into the need, and press **Scan the
   folder**. Untick a file: the step scans again without it. Press **Create and start the intake**.
4. **Keep it local.** Tick **Confidential: keep on local models** before you scan. If a role is routed
   to a hosted model, the step says so and creating is refused; route the roles to a local model
   ([local-models.md](local-models.md)) and try again.
5. **Ask Rihma** "what will be sent from my folder?": it explains the scan step and takes you there.

## Tutorial: from a plan to the summary (10 minutes)

1. **See how a plan is read.** Run
   `rihmasto inputs read tests/fixtures/inputs/plan-full.md --maturity production`. It reads as a plan
   (3 decisions, 13 headings, 10 facets stated), and `checklist_would_ask` names its three deliberate
   gaps: data and its sensitivity, availability, acceptance criteria.
2. **Try the other kinds.** Read `need-one-line.txt` (a need: every facet a gap), `need-finnish.txt`
   (a need in Finnish: its users stated on line 2), `spec-expert.md` (a specification: four requirements
   with their criteria) and the `folder` (each document its own kind).
3. **Take the plan in.** In the cockpit, press **New project**, paste the plan, choose maturity
   *production* and mode *mixed*, and press **Create and start the intake** (this needs Gnomon and a
   model). From the command line:
   `rihmasto new "Visitor registration" --source-file tests/fixtures/inputs/plan-full.md --maturity production --requested-by <you>`.
4. **Open the summary.** The project opens at **Questions**. The intake summary lists what the plan
   stated, with its lines; the blocking gap (data) waits under **Asked**; availability and acceptance
   are under **Assumed** with their due dates. Open **The facet checklist** to see every facet's state.
5. **Answer the gap.** Answer the data question on its card. The summary shows it answered, by you.
6. **Ask Rihma.** Press **Ask Rihma** (or `/`) and ask "Where is the intake summary?". **Take me there**
   opens the Questions view on it.
7. **Check what was not asked.** Under the three columns, the questions not asked each name the facts
   they rest on. Each one only restates your input. A question about a detail your input never mentions
   is asked, even when it names a facet your input states. A blocking question that restates your input
   is asked as well, and its card quotes the lines it rests on, so you confirm it rather than answer it
   again.

## Know before you rely on it

- The rules read English and Finnish words. Another language reads as "no language read", and its
  facts are found only through headings and labels the rules know.
- Screening compares words, not meaning. A question that restates the input in other words (a
  synonym the input does not use) is asked, which errs toward asking. A question whose words all
  happen to appear in the stated facts is not asked, unless it is blocking. Every question not asked
  is listed under "not asked" with the facts it rests on, so a person can see it and raise it.
- A folder is read through its material map (above). A repository's housekeeping files are listed, not
  read: changelogs and release notes, licence and notice files, security, contributing, code of
  conduct, authors, support, governance and funding files; dependency lists such as `requirements*.txt`
  count in the code inventory. They are not the author's request, and a security policy would otherwise
  count as a stated security need. Rename such a file if it really is part of the request.
- The scan's kinds and the secret check are rules, not understanding: a file named oddly may get the
  kind "other" and be read later, and a credential in a format the rules do not know is not caught.
  Look at the map before you confirm, and untick what should not leave.
- A PDF is only partly read; a scanned PDF, an image of text or a legacy `.doc`, `.xls` or `.ppt` file is
  listed, not read: save it as text or in a newer format to have it read.
- The panel reads at most 40,000 characters of the request; the reading reads all of it, and the
  facts beyond the cut are still given.
