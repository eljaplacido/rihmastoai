# Change anything, go back a step, never get stuck

Nothing you set when you made a project is final. If you picked the wrong kind of work (the template),
the wrong maturity or mode, or a spec was written from the wrong material, you change it, and Rihmasto
says what the change means for the work already done before anything is saved. Nothing is deleted: what
a change sets aside is kept as a superseded version, and the ledger records who changed what, when and
why (requirement FR-CHG1).

## Project settings

Open a project and press **Project settings** in its header. You can change:

| Setting | What follows it |
|---|---|
| Title | the brief and every heading; the ledger keeps the old one |
| Kind of work | the panel's questions, the checks and the template ([work profiles](profiles.md)) |
| Mode | who answers the panel's questions: people (`socratic`), the factory (`assume`), or both (`mixed`) |
| Maturity | which stages and gates run, how big the spec may be, and whether a person approves the plan |

Change a value, give a reason, and press **Preview the impact**. The preview writes nothing. It lists
what the change means, for example:

- *The questions were asked for "Web app or service": 1 open question no longer fits and is withdrawn
  when the questions run again for "Integration or connector"; 6 settled answers are kept.*
- *The spec was written for demo maturity (up to 5 requirements; pilot allows 7): write it again.*
- *At pilot maturity a person approves the plan before anything is built.*

Where the work no longer fits, the preview offers to go back to the right step at once: the questions
for a new kind of work, the spec for a new maturity. Under a new mode it offers to let the factory
assume the open questions the new mode would assume, in your name. **Save the settings** is on only
once the preview shows the values you are saving.

A business owner, product owner or developer persona changes settings. The posture (prototype,
balanced, production, regulated) is changed in its own flow: its chip in the dialog opens the Posture
dialog, with its preview of what changes now and later ([postures](postures.md)). A project with a
posture keeps to it here: the impact says when a new maturity or mode also loosens or tightens the
posture, a maturity or mode it does not take is refused, and loosening it needs a business owner, IT
or compliance.

From the command line:

```
rihmasto settings <pid> --kind integration --reason "it connects two systems" --preview --person Aino --persona product_owner
rihmasto settings <pid> --kind integration --reason "it connects two systems" --redo --person Aino --persona product_owner
```

## Go back a step

**Go back a step** (in Project settings, or on What's next) sends a project back so a step runs again:

| Back to | What it undoes |
|---|---|
| the material | the request itself: the material, the panel's readings, every open question, the spec and the plan are set aside; you add the material again and the intake runs from it |
| the questions | open questions are withdrawn (their cards decided as withdrawn, with your reason) and the intake runs again over the same material at the next Advance; answers people gave are kept and never asked again |
| the spec | the spec is kept as a superseded version and written again from the brief; the plan is set aside with it |
| the plan | the contract is kept as a superseded version and compiled again from the spec; where a person approves the plan, they approve it again |

What a step sets aside moves to `superseded/<n>-<step>/` in the project folder, listed in
`superseded/index.json`, and the ledger records `rewound` with the person, persona and reason. Holdout
scenarios of a contract set aside stay in their custody, out of the runs.

A project with a release is never sent back: a released project changes through the change loop (the
**Changes** view, or `rihmasto change <pid> "..."`), and going back says so.

```
rihmasto rewind <pid> --to questions --reason "the questions missed the desks" --person Aino --persona product_owner
```

## Add material

**Add material** takes text, or the path of a file or folder on the cockpit's machine (with access
enforced, the cockpit takes text only). The original request is kept; the material is added after it
under its own heading and kept on its own in `material.json`, and the ledger records `material_added`
with its sha256.

With **Let the panel read it now** (re-intake), the panel reads only the new material, told what was
asked before: it asks about what is new, never a question already on record, and every answer stands.
From the cockpit the panel reads it in a run the cockpit starts; from the command line, at once. A
project with no request yet (or one sent back to its material) takes the material as its request.

When the spec is already written, the run that reads the material stops there: nothing is built on a spec
written before the material. Answer what the panel asks; then **Go back to the spec** to write it again
with the material, or **Go on with the spec as it is**. Nothing is built past an open blocking question,
whenever it was asked (FR-CHG1-AC-10).

A project made from a folder keeps the folder's material map in `material.json`; material added later is
kept in the same file beside the map, which stays as it was.

```
rihmasto material add <pid> --path notes/desks.md --note "the desk rules" --reintake --person Aino --persona product_owner
```

## What's next: never stuck

The overview's **What's next** strip says what the project waits for, who can act, and gives the
buttons that move it forward:

- a decision card to decide, or a blocking question to answer or let the factory assume;
- a run that stopped, with **Retry**, and the step to go back to;
- a step whose input is missing, with **Add material** or **Change the project settings**;
- a model endpoint that did not answer, or a confidential project whose role would go to a hosted model,
  with **Open Models setup** for any persona (`rihmasto models list`; [Models setup](models-setup.md),
  [running fully local](local-models.md));
- a paused project with **Resume**, a checkpoint to look at, an autonomy cap to raise, a module to turn on.

Every state the pipeline can stop in maps to at least one action, and each action names its command
line. `rihmasto next <pid>` prints the same answer; it reads the autonomy cap from the records, so it says
when the cap stops the build without a run to show it. A run's result from before you went back a step,
changed a setting or added material no longer counts: What's next reads the records again.
`rihmasto settings ... --preview` and `rihmasto rewind ... --preview` write nothing and need no signer.

See also: [the cockpit](../cockpit.md), [inputs](inputs.md), [work profiles](profiles.md).
