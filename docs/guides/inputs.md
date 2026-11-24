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
| Reading PDF, Word or spreadsheet files | Planned; today a folder's `.md` and `.txt` files are read |

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
- `intake_done` carries the input's kind.

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
- A folder is read as intake reads it: its README, spec and brief files, then up to 12 other `.md` and
  `.txt` files at its top level, then up to six files in `docs/`. A repository's housekeeping files
  are left out at the top level: changelogs and release notes, licence and notice files, security,
  contributing, code of conduct, authors, support, governance and funding files, and `requirements*.txt`
  or `constraints*.txt` dependency lists. They are not the author's request, and a security policy
  would otherwise count as a stated security need. Rename such a file, or put it in `docs/`, if it
  really is part of the request.
- The panel reads at most 40,000 characters of the request; the reading reads all of it, and the
  facts beyond the cut are still given.
