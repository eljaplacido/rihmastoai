# Guided journeys

A guided journey is a checklist measured from Rihmasto's real records. It tells you where you are, what is next,
why that step matters, which button does it and the equivalent command. You can ask Rihma to stay with you while
you do it (FR-JRN1).

Journeys and [walkthroughs](walkthroughs.md) work together but are not the same thing. A **walkthrough** is a
conversation that gathers input and waits for your Confirm. A **journey** is the larger path before, during and
after that conversation. It does not duplicate the records: a step done in the cockpit, in a walkthrough or on the
command line is done in the journey too.

## The journeys

| Journey | Scope | Steps |
| --- | --- | --- |
| Feed in an existing project | one adopted project | folder or git address, scan, adopt, baseline, as-is contract, assessment, gaps and alignment, IDE tools, checks and automations, first gated change, deployment road |
| Start from a new idea | one project | need, questions, approved plan, build, delivery |
| Start from documents | one project | documents, create, questions, approved plan, build, delivery |
| Set up a model | the factory | open Models setup, set a role, test it, optionally keep confidential work local |
| Connect your IDE or coding agent | one project | inspect its AI tools, connect the IDE, give the agent the contract, hand off work, bring the change through the gate |
| First deploy | one project | ready roads, choose the project's road, build, release, probes |
| Set up automations | one project | open Automations, start from a template, optional dry run, see it run |

Some steps are optional. The next-step rule chooses an unfinished required step whose prerequisites are settled
before an optional one. A submitted change is **under way**, not done; it remains the current step until the records
show it applied or merged. A business persona sees business wording for the journey and its steps.

## Ask Rihma, or start from a project

Ask, for example:

- “How should I get started with a brownfield project?” or “Minulla on olemassa oleva projekti”;
- “What should I do next?” or “Mitä seuraavaksi?”;
- “How do I get started?” for the three ways in: an existing project, a new idea or documents;
- “Walk me through it” for the open project's next step, or the ways in when no project is open.

These requests are answered **by rule from the journeys and records, without calling a model**. The answer shows
the current position, the next step and its button and command, the remaining steps, and **Guide me step by step**.
A “where is” question still goes to the cockpit map, and a status question still goes to the status answer. Other
how-to questions that do go to a model include the matching journey's steps in the model's prompt, so its answer can
name real buttons and commands.

A project's **Overview** has a **Next step** card with the same measured position and actions. Home and the empty
Projects page offer the three ways in. After an adoption, Plug in offers the journey's next action and **Guide me
through the rest**.

## The guided panel

**Guide me step by step** opens the panel at the top of Ask Rihma. The current step shows why it matters, what the
records say, its action and command, and **If it fails** where there is specific recovery advice. **All steps**
shows every state and result.

- The step's main button starts its walkthrough (for example Plug in), opens its view and highlights its control,
  or performs it through that control's own signed route. **Run the assessment**, **Read the repository** and
  **Set up the watch** use their existing cockpit API routes; the journey does not invent a second implementation.
- **I did it** records your word for the current step when the records cannot prove it, such as pasting the IDE
  section. **Skip** records that this guide skips it. If a real record later proves a step done, that record takes
  precedence over either mark.
- **Stop** ends the panel's active guide. It neither undoes completed work nor performs the remaining steps.

The active guide follows you across cockpit views and is restored after a reload. Starting a guide again starts a
fresh set of marks, but its position still comes from the records, so work already done is not repeated. One guide
is kept per person; another person's guide is separate.

A newly completed step's measured result appears in the panel while it refreshes. Reading or refreshing a journey
never completes a step by itself and writes nothing.

## On the command line

The command line exposes the same catalogue and measured progress. It is read-only: each step's own command is
shown for you to run separately, with the project, person and persona filled in when known.

```bash
rihmasto journey list [--persona business_owner] [--json]
rihmasto journey next [--project PROJECT] [--persona developer] [--json]
rihmasto journey brownfield --project PROJECT --person "Aino Example" --persona developer
rihmasto journey new_idea --project PROJECT --json
```

In the text checklist, `[x]` means done, `[~]` under way, `[-]` skipped and `[ ]` to do; `>` marks the next step.
`next` without a project reports which projects need what, or the three ways in when the factory has none.

## The API

| Method and path | What it does |
| --- | --- |
| `GET /api/journeys?persona=` | the catalogue and the three starters |
| `GET /api/journeys/next?project=&persona=` | one project's next answer, or the factory's projects and ways in without `project` |
| `GET /api/journeys/guide?person=&persona=` | the asking person's guide and its progress, or `{"guide": null}` |
| `POST /api/journeys/guide` | `start`, `did`, `skip`, `project` (attach a project) or `stop` |

A start body is `{action: "start", journey: "brownfield", project: "", person, persona}`. A mark also names
`step`; attach names `project`. Every write needs a named person and a persona granted on the factory, just as a
walkthrough does, and requires the normal cockpit session and Origin. Unknown journeys, projects, steps and actions
are refused without changing the guide.

The POST response and the GET guide response wrap the result in `guide`; inside it, `guide` is the saved state,
`progress` is the measured journey and `walk` is the associated walkthrough when one exists.

## What is kept

The saved guide is under the factory home's `_journeys/guides.json`: the journey, project when known, start and end
state, persona and marks. The factory ledger records `journey_started`, `journey_step` and `journey_ended`, signed
with the person and persona and containing journey, step and project ids, not the question you typed. A guide that
started before its project existed can find the project and the folder/scan through the same person's matching
walkthrough.

See [Walkthroughs](walkthroughs.md), [Existing solutions](../brownfield.md), [Inputs](inputs.md),
[Models setup](models-setup.md), [Your IDE and Rihmasto](ide-and-rihmasto.md) and
[Deploying on paved roads](deploying.md) for the individual steps.
