# Scenarios: where you start, and what happens under the hood

Each guide here starts from a situation you are in, walks through it in the cockpit, in Ask Rihma and
on the command line, and then says what Rihmasto does underneath: what it reads, what it records,
which agent runs, where a person decides. Pick the one closest to you.

| You have | You want | Guide |
|---|---|---|
| Nothing yet, or a sentence, a document, a folder of notes | A first working version, with a spec and tests you can trust | [Start from a blank page](start-blank.md) |
| A repository that already works | Rihmasto beside it: its structure captured, a contract, a gate, checks | [Bring in an existing project](existing-project.md) |
| A repository, and a choice to make | To decide how much of Rihmasto's structure it takes on, from "only watch it" to "the full chain" | [Enforce Rihmasto's structure, or not](existing-project.md#how-much-structure-to-take-on) |
| A project in Rihmasto | To improve it and keep it healthy week after week | [Improve and maintain](improve-and-maintain.md) |
| Agentic work that drifted: no specs, flaky tests, nobody knows who decided what | Governance, reliability and traceability back, step by step | [Fix a project that lacks governance](fix-ungoverned-project.md) |
| Repeated work: nightly checks, a weekly rescan, a notice when something breaks, a small agentic job | Workflows and automations that run on their own, with guards | [Build workflows and automations](workflows-and-automations.md) |

Before any of them: install Rihmasto and pick a model ([getting started](../getting-started.md)), and
connect your own coding agent if you use one ([configure with your agents](../guides/configure-your-agents.md)).

## The same rules in every scenario

Whatever you start from, and however much of Rihmasto you use
([use only what you need](../guides/use-only-what-you-need.md)):

- **Models propose; the kernel decides by rule; people decide what is theirs.** The kernel is plain
  Python with no model in it. A model's output is a proposal until the kernel's checks or a person
  accept it.
- **Every step is recorded** in the project's hash-chained ledger, with who did it and as which
  persona.
- **Solo by default.** On a new home you are the one person and hold every persona. Only what blocks
  work waits for you; the rest goes on. Team mode and IT's access file come later, when you need them
  ([access](../guides/access.md)).
- **Never stuck.** Every refusal says why and what to do next, every empty view says what would appear
  there and how, and Ask Rihma answers "why is this empty?" and "what next?" for the view you are on
  ([change anything](../guides/change-anything.md), [self-healing](../guides/self-healing.md)).
- **Honest states.** Something that could not be checked reads **not measured**, never passed and never
  zero.

## The words used in these guides

- **Factory home**: the folder where Rihmasto keeps everything (`--home`, else `$RIHMASTO_HOME`, else
  `var/` in the checkout).
- **`<pid>`**: a project's id, such as `equipment-loans-3f9a1c`. `rihmasto status` lists them; the
  cockpit shows it in the address bar (`#/p/<pid>/overview`).
- **Persona**: the role you decide as: `business_owner`, `product_owner`, `concept_evaluator`,
  `end_user`, `it`, `developer`, `operations`, `stakeholder` or `compliance`.
- **"Ada Example"** stands for your name. Every command that records a decision takes
  `--person "<your name>" --persona <persona>`.
