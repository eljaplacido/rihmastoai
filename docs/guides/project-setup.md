# Set up a project, archive it, remove it

The owner (2026-11-24): "For all projects I want to see them populated with the entire features of
Rihmasto, and make sure that when you know how it happens I can also do it on a UIX level or by agent
request on chat." And: "Delete so many duplicate projects."

## Set up this project

Every project's **Overview** opens with **Set up this project**: each feature of Rihmasto that applies
to it, with its state (`kernel/project_setup.py`).

| Item | Set up when | One click |
|---|---|---|
| Checks and Health | a check is enabled on it | enables the test suite check (a stated test command), else the secret scan, daily |
| Watching and automations | a suggested automation is set up | sets up the first [suggested automation](automations.md#suggested-for-a-project) |
| Alignment with its own specs and tests | its repository was read | reads the repository for [alignment](alignment.md) |
| Insights and Review | the modules that show them are on | opens [Review](review.md), or Settings, Modules |
| AI tools, IDE hand-off and the agent channel | agents worked on it (a workspace, a hand-off, a channel post) | opens Work on it from your IDE |
| Posture | a posture is chosen | opens the Posture dialog, with its preview |
| Outputs | outputs are chosen | opens Outputs |
| Destinations, agent observability, Gnomon audits | the build has them | opens the project |

Each item is **set up**, **offered** (with its one click), or **not applicable** with why: a project made
from an idea has no repository to align and no code for an IDE yet, and a part this build does not have
says so. A one click goes through the feature's own signed path (`check_enabled`, `automation_set`,
`alignment_scanned`), so the records are the same as by hand; an item that is chosen with judgement (the
posture, the outputs) opens its own dialog instead. The card stays on top of the Overview while anything
is offered, which is right after a project is fed in.

On the command line:

```
rihmasto setup <pid>
rihmasto setup <pid> --do checks|automations|alignment --person Aino --persona developer
```

In Ask Rihma: "set up this project" (or "aseta projekti") answers with the checklist and a proposal for
each offered item, which runs only when you confirm it.

## Archive, restore, remove

**Archive** (Project settings, at the bottom; or **Archive this copy** under Projects, Duplicates) hides a
project from every list and makes it read-only: every write to it is refused, in the cockpit, on the
command line and by the kernel itself, until a person restores it. It is recorded with who archived it and
why, in the project's ledger and in the factory's (`project_archived`).

**Projects, Archived and duplicates** lists the archived projects with **Restore** (back in the lists,
writable; `project_restored`) and **Remove**, and the projects that share a title with the copies to
archive (the one with the most records is kept).

**Remove** takes only an archived project, and only after you type its id: removing it cannot be undone.
Its records are kept first as an export file, a zip of the project's folder and its holdout custody, in
`exports/removed/` in the factory home; the factory's ledger records the removal with the file and its
sha256 (`project_removed`). Then the project's folder is gone.

Who may: a business owner, product owner, developer, IT or operations, signed with their name.

```
rihmasto project duplicates
rihmasto project archive <pid> [--reason "a duplicate"] --person Aino --persona product_owner
rihmasto project archived
rihmasto project restore <pid> --person Aino --persona product_owner
rihmasto project remove <pid> --confirm <pid> --person Aino --persona product_owner
```

In Ask Rihma: "archive the duplicate projects" proposes archiving each copy; "remove <name> for good"
proposes the removal of an archived one (and archiving first, when it is not archived); "restore <name>"
brings one back. Each runs only when you confirm it.

## Every click is also a request in chat

Ask Rihma proposes any change the cockpit makes by a click, by the operation behind it
(`kernel/assistant_ops.py`): the request a proposal sends is filled from the kernel's table, never from a
model's words, and checked before it is shown. `kernel/parity.py` keeps the tables that say, for every
control of the cockpit, how Ask Rihma does the same (or why it only takes you there: a file to download, a
judgement made beside what it judges, a secret on IT's machine), and for every signed command its cockpit
route. `tests/test_parity.py` fails when something is added without its other half.
