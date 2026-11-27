# Teams, Rihmasto's words and what applies where

A project belongs to a team, and a team's words reach its projects
([D-0027](../../decisions/D-0027-teams-and-semantics.md) and
[D-0028](../../decisions/D-0028-teams-and-semantics.md), FR-TM1 to FR-TM7). Working alone, you meet none of it:
Rihmasto made a team of one for you, named after you, and there is nothing to set up.

## Teams

- A **team** has a name and members (people, as the rest of Rihmasto names them). A project is in exactly one team;
  a team has many projects.
- **Working alone** you are a team of one, made automatically. Settings > Teams says so in a line. When a second
  person is added (Settings > People and access, or `rihmasto access team`), the same team simply has more members:
  nothing moves, nothing is rewritten, nothing is locked in.
- **Every project** made before teams, and every new one, is in the automatic team until a person moves it.
- **IT defines a team** (Settings > Teams: name, members). **IT or the project's owner moves a project** to another
  team, from Settings > Teams or from the project's settings (the Team field). Each change shows a **preview** first,
  is **signed**, goes in the **ledger**, and an **Undo** puts the earlier record back exactly (the undone change stays
  in the record).
- A team's **name** is unique (whatever the case or the spacing), holds a letter or a digit and is not another team's id.
  Members are a list of names, and a team does not take a person out of the home: you remove someone in Settings >
  People and access (deactivate), not in a team. Once there is a second person the automatic team reads "Our team"
  until someone renames it.
- A **preview** asks for the same role as the change it previews, and a refusal says in plain words who may. A move's
  preview names each word that would read differently in the team the project joins, and how many records read differently.
- **Undoing a team's creation** is refused while it holds projects or has words of its own: the message names them and says
  what to do first (move the projects, give the words back), so nothing is silently moved or lost. Rihmasto's own records
  (Rihmasto itself) are in no team.
- A team record may carry an empty optional `unit` field, so that business units added later migrate nothing. It is
  neither built nor shown. There is no enterprise or business-unit level, and none for an individual.

Ask Rihma does the same by rule: "which team is this project in?", "who is in my team?", "create a team called
Platform", "move this project to the platform team". A creation and a move are proposed; you confirm them, signed.
On the command line:

```text
rihmasto teams list
rihmasto teams which <project>
rihmasto teams create Platform --member "Cleo Example" --person "Aino Example" --persona it
rihmasto teams set <team> --add "Dee Example" --person ... --persona it
rihmasto teams move <project> <team> --reason "they run it" --person ... --persona it
rihmasto teams undo --project <project> --person ... --persona it
```

## Rihmasto's own words

Rihmasto has words of its own for what it keeps: a *Request*, a *Requirement*, a *Criterion*, a *Task*, the links
between them (*has criterion*) and the details a record carries. They are the **shipped default**
(`kernel/ontology.json`). A team may say them differently for all its projects, and a project differently again. The
word in force is the project's, else the team's, else the shipped one.

For each term a team or a project can:

- **rename or describe** it (a team that says *story* for *requirement*);
- add **synonyms**: Ask Rihma then finds the term by them, so "where are the stories?" reaches the requirements;
- **hide** it (it leaves the Knowledge graph's legend and views);
- add a **custom term** that means an existing kind of record: another word for it.

The word in force is used wherever the kind is named: the Knowledge graph's labels, legend and issue lines, the glossary
words, Ask Rihma's answers from the map, the epic and requirement wording, and, in the browser, over what a view draws (a
capsule's count, a spec page's heading, the board's filter). What people wrote (a title, a brief) and the Vocabulary views,
which show both words side by side, are left as they are. A kind you **hide** leaves the Knowledge graph before anything is
counted, so the counts, the issues and a focus agree with what is drawn; the warnings that still hold on the hidden records
are said and counted, not lost, and the preview of hiding says how many. The graph across projects says which words it reads
in and which projects say some differently.

**Old records are included.** A redefinition changes how records are **read and labelled**, never the records:
nothing stored is rewritten, and old records read through the same words as new ones. The ledger keeps what each term
meant and since when; a term's detail says "as defined on <date>" with who and why.

- **Before saving**, a preview says how many records, nodes and views would read differently.
- **Who may change it:** a team's words, IT; a project's own, IT or the project's owner. Working alone you hold every
  role, so there is no approval step: it applies at once, after the preview, and **Undo** gives the earlier reading
  back exactly.
- **Where:** Settings > Vocabulary for the team, and a project's **Vocabulary** view (Govern) for the project. Each term shows
  the shipped meaning, the team's, the project's and which is in force, with its scope as a chip: this project, this
  team or the shipped default.

```text
rihmasto vocab show --project <project>
rihmasto vocab preview --project <project> --term kind:requirement --label Story
rihmasto vocab set --team <team> --term kind:requirement --label Story --reason "we write stories" --person ... --persona it
rihmasto vocab undo --team <team> --person ... --persona it
```

Ask Rihma: "call a requirement a story", "say check instead of criterion in this project", "hide the comment term",
"add the synonym brief for request", "add a term brief that means request", "undo the last change of words". The team's
words by default; "in this project" keeps it to the project.

## What applies where

Every setting says its scope: **this project**, **all teams** (one setting the whole home shares: structure policy,
enforcement levels, IT checks, modules, runners, roads, models, people), **this team** (only its words, and who is in it)
or the **shipped default**. A home of one person says **all projects** and **your words**, and keeps the list closed. One
table (`kernel/scope_table.py`) lists every setting surface with the scopes it may be set at, and each reads its current
value source from the store it is kept in (`kernel/scope_sources.py`): **this project's own**, **set for all teams**, **from
the team**, **shipped default**, or **nothing set here yet** for what exists only where somebody made it (an embed, an
observer link, an automation, an eval). Without a project chosen, a surface made on each project says so. Settings > Where each
setting applies, and the end of a project's Vocabulary view, render it with a link to change it. A test fails if a control on
Settings has no entry in the table.

Ask Rihma answers "where is this set?" ("where is the enforcement level set?") by rule, and `rihmasto scope show
[--project <project>]` prints the table.
