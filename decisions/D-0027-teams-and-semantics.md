---
id: D-0027
decided_by: owner
decided_on: 2026-11-27
kind: principle
status: proposed
amends: D-0023, D-0024
---

# Teams, tied to projects: Rihmasto's own words by team and by project, and what applies where

The owner (2026-11-27), after a long discussion of "two-level semantics where the platform's own semantics are
user-redefinable, and the full platform vs unit scope": "I believe not all but defined it/tech admins (note; not over
complicating things for a single developer) and I believe old records included? ... Maybe at this point we just talk
about teams and them being tied to projects."

**The decision.**

1. **The unit is the team, tied to projects.** A project belongs to exactly one team; a team has many projects. A team
   has a name and members (people, as `kernel/people.py` names them). A person working alone is a team of one, made
   automatically and named after them, with nothing for them to configure or see. When a second person is added (the
   existing solo to team switch) the same team simply gets members: no migration, no lock-in. A project made before
   teams, and every new one, is in the automatic team until a person moves it. Teams are kept in the factory home
   (`home/_teams/`), a project's team in its `project.json`.
2. **Meaning resolves in three steps: the shipped default, then the team's terms, then a per-project override.** The
   shipped default is `kernel/ontology.json`, which only the owner's contract amends. A team, or a project, may rename or
   describe a kind of record, a relation or an attribute, add synonyms (they feed Ask Rihma's map search), hide a term,
   and add a custom term that means an existing record kind. The word in force is used by the Knowledge graph's labels and
   legend, the glossary words, Ask Rihma's answers and map synonyms, and the epic and requirement wording.
3. **There is no individual level and no enterprise level.** An empty optional `unit` field on the team record is allowed
   so that business units added later migrate nothing; it is neither built nor shown.
4. **Who may change what.** A team's terms are changed by IT or tech admins only. A project's own override by IT or the
   project's owner. A team is defined by IT; IT or the project's owner moves a project. A person working alone holds every
   role, so there is no approval step: a change applies at once, after a preview, with an Undo.
5. **Old records are included.** A redefinition changes how records are **read and labelled**, never the stored records.
   Old records read through the overlay as new ones do. The ledger keeps what each term meant and since when: each
   definition is recorded with who, why and the date ("as defined on ..." is in the term's detail). An Undo puts the
   previous reading back exactly, and the undone change stays in the record. Before a change is saved a preview says how
   many records, nodes and views would read differently.
6. **Every setting and term shows its scope: this project, this team, or the shipped default.** One table
   (`kernel/scope_table.py`) says for every setting or configuration surface whether it is set per project, per team or
   is the shipped default, and a "What applies where" view renders it with each setting's current value source ("this
   project overrides the team", "from the team", "shipped default") and a link to change it. A test iterates the map's
   controls on Settings and fails when one has no scope entry. The earlier "platform" scope reads as the team.

**What was left out on purpose.** An enterprise or business-unit level, and an individual's own words: the owner chose to
stop at teams and projects. A team that holds projects cannot be removed; a team may be renamed and its members changed.

**How the standing rules hold.** Solo first, solo to team without lock-in (a second person joins the same team). Guide,
don't describe: Ask Rihma answers "which team is this project in?", "who is in my team?", "where is this set?" from the real
state, proposes "move this project to the platform team" and "call a requirement a story", and the person confirms them
signed. Never lost: a change of words or of a team is a ledger record, and an Undo adds a record rather than removing one. UI
and chat parity: each control has its chat path in `kernel/parity.py`, and the command line has `teams`, `vocab` and `scope`.

**Requirements.** FR-TM1 (teams), FR-TM2 (words), FR-TM3 (what applies where), in `contract/contract.json`.
