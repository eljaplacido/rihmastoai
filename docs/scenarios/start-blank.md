# Start from a blank page

You have an idea, a sentence, a document or a folder of notes, and no code yet. This guide takes it to
a first working version on your own machine, with a spec, a contract and tests you can trust, and then
says what Rihmasto did underneath.

This path stays at **explore** maturity, which lands on the local preview and needs nothing
configured beyond a model. Before you start: [getting started](../getting-started.md) (install, sign
in, a model, Gnomon).

## 1. Shape the need

**In the cockpit.** Home > **Shape it in chat**. Say the idea in your own words, or attach a file or a
folder. Rihma asks one or two questions at a time and keeps a draft brief beside the chat (who it is
for, the problem, the outcomes, what is in and out of scope, constraints, data and systems). Edit any
field yourself: a field you edited stays yours. When the draft holds, press **Create the project from
this**, and choose the kind of work, the mode and the maturity, with Rihma's suggestion and why.

Already know what you want? **New project > A need or a spec** takes the text or a file directly.

**In Ask Rihma.** "I have a new idea" offers **Walk me through it**: the same steps, one question at a
time, each proposal confirmed by you ([walkthroughs](../guides/walkthroughs.md)).

**On the command line.**

```bash
rihmasto new "Equipment loans" --profile auto --mode mixed --maturity explore \
    --requested-by "Ada Example" \
    --source "Our team keeps losing track of who borrowed the drills and laptops."
```

`--source` also takes a Markdown file or a folder; with a folder, `rihmasto scan <folder>` shows first
what would be read, summarised or skipped, and `new` asks for `--yes`.

## 2. Answer what matters

The intake panel asks only the questions that change what gets built. They wait in the project's
**Questions** tab. Answer each, or press **Let Rihma assume** to turn the panel's proposal into an
assumption with a due date.

```bash
rihmasto status <pid>
rihmasto answer <pid> Q-001 "the team lead approves a loan" --person "Ada Example" --persona business_owner
rihmasto assume <pid> Q-002 --person "Ada Example" --persona business_owner
```

The **mode** decides how many questions reach you: `socratic` sends every one to a person, `assume`
assumes every answer (with a due date), `mixed` asks only the blocking ones.

## 3. Look at the spec, then build

**Spec and contract** shows the requirements, each with given / when / then criteria and who confirmed
what. Before the first build a card asks once: **Go** (I looked, build it) or **Skip**. Then
**Advance** (or `rihmasto run <pid>`) builds until a person is needed, and says what it waits for.

## 4. Try it, and send feedback back

The release lands on the local preview: open **Try it**. **Report a change** (or
`rihmasto change <pid> "An empty name crashes" --person "Ada Example" --persona end_user`) sends it
back through the same chain.

## What happens under the hood

| Step | What Rihmasto does | Who or what does it | What is recorded |
|---|---|---|---|
| Material | Each file of a folder is read, summarised, listed or skipped, with why. Files that look secret are never read. | the kernel, by rule (`kernel/material*.py`) | the material map |
| Intake | The panel (business, end user, IT and security, operations, delivery) reads the need and asks what is missing. Facts already in your brief are never asked again. | the **analyst** agent, through Gnomon in the analyst lane | `question_added`, answers, assumptions with due dates |
| Kind of work | A profile (web service, integration, automation, and more) is proposed by rule from the words of the need; an uncertain match asks you. | the kernel (`kernel/profiles.py`) | the profile and why |
| Spec | Requirements with given / when / then criteria; the kernel sets the ids and records who confirmed each one. | the analyst proposes, the kernel checks | `spec.json`, its provenance |
| Contract | The spec compiled into a contract with **no model**, its revision the hash of its content. Every criterion must have a check. | the kernel (`kernel/compile.py`) | `contract.json` and its hash |
| Plan and holdouts | Tasks, each with the criteria it serves and the files it may write. Test scenarios the builder never sees are written and kept in custody, outside every project folder and lane. | the kernel; the **holdout author** agent | `tasks.json`, the custody |
| Build | Each task runs in a cell: a git work tree of its own, with Gnomon enforcing the agent's tools, write scope and sandbox. | the **builder** agent, through Gnomon | each round, its model and its cost |
| Gate | The kernel runs the tests itself, checks that each criterion's test failed before the change and passes after, and asks a **verifier** from another model family. Two failed repair rounds escalate to you. | the kernel and the verifier | the `gate` verdict; a merge or an escalation card |
| Delivery | The release goes to the local preview; the holdouts run against it; a capability pack pins it by hash. | the kernel (`kernel/deliver.py`) | the release, its pack |
| Change loop | Feedback is classified and sent back to the step it belongs to: a question, the spec, a task. | the kernel (`kernel/change.py`) | the change card and what it led to |

Every row appends to the project's `ledger.jsonl`, each record carrying the hash of the one before it.
The Knowledge graph view then shows the whole chain, from your answer to the test that proves it.

## When you only want to think it through

Not every idea should be built yet.

- **Think it through:** choose the `socratic` mode. Every question goes to a person and nothing is
  assumed.
- **Get a quick mock-up:** `--posture prototype --maturity explore` assumes answers and builds fast,
  onto the local preview.
- **Validate it as a concept first:** log it as a signal on the **Delivery square**, and a business or
  product owner validates, parks or rejects the concept there
  ([signals and concepts](../guides/signals-and-concepts.md)).
- **Spec only:** the `spec_only` preset stops at a confirmed spec and a hashed contract, exported as
  files, with nothing built ([use only what you need](../guides/use-only-what-you-need.md)).

## Going further than your own machine

Demo, pilot and production need a paved road IT configured ([deploying](../guides/deploying.md)).
Today only the local preview has run for real; the docker and Google Cloud Run roads are tested
against stand-ins, and Azure Container Apps is rendered but never deployed. At pilot and production a
person approves the plan before anything is built.

## Next

- [Improve and maintain](improve-and-maintain.md) once it runs.
- [Build workflows and automations](workflows-and-automations.md) when the need is a job with no
  screens.
- [How it works](../how-it-works.md) for each step in detail.
