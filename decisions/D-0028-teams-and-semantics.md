---
id: D-0028
decided_by: owner
decided_on: 2026-11-27
kind: principle
status: proposed
amends: D-0027
---

# Teams and words, made true: what applies where reads the real source, a team is not broken, a word is used everywhere

The owner (2026-11-27): "Maybe at this point we just talk about teams and them being tied to projects." D-0027 built it. An
independent check of that build found eleven places where it said something its stores did not hold. This decision
records each and what was done; the requirements are FR-TM4 to FR-TM7.

1. **A setting is called a team's only when it is kept per team.** The structure policy, the enforcement levels, the
   modules, the IT-check defaults, the runners and the roads are each one document per home with no team in it. They now say
   **all teams** (a home of one person says **all projects**), never "this team": with two teams, changing one of them
   changes both, and the table no longer claims otherwise. Only the words (and who is in a team) are a team's. The scope
   table's `team` scope remains for those; a new `home` scope is the shared one.
2. **Each surface reads its value source from its own store** (`kernel/scope_sources.py`): runners from the runner
   choices, roads from the project's road and the configured ones, Gnomon's enforcement from its ledger records, embeds,
   observer links, automations and evals from what was made for the project, models from the machine's routing, people from
   the access mode. Where nothing was made the row says **nothing set here yet**; without a project, a per-project surface
   says it is made on each project; a project in a team is told which team.
3. **A team is not undone out from under its projects or its words.** Undoing a creation is refused while the team holds
   projects or has words, naming them and saying what to do first. A new team's id is never an old team's, an old team's
   leftover words file or a team a project still names, so a re-created team no longer recaptures projects or words.
4. **Names and members are checked.** A team name is unique whatever the case or spacing, holds a letter or a digit and is not
   another team's id; an id folds accents and uses a short code when a name has no plain letters. Members are a list of names;
   a number is refused (400, not 500). A team does not remove a person of the home (People does); the automatic team reads
   "Our team" once there is a team, until a person renames it.
5. **Rihmasto's own records are in no team**: reading says so and a move is refused.
6. **A preview asks for the same role as its change.** A refusal says "an end_user may not define a team; only IT may", or
   asks which role is acted as. A move's preview names the words that would read differently and how many records and nodes.
   Ask Rihma answers "who is in the Ops team?" for the named team. *By design and left as it is:* in team mode a business
   owner who owns a project may set that project's words and move it (D-0027 item 4): the owner's wording "team terms by IT
   only" is kept for a **team's** terms, which a business owner cannot set.
7. **The word in force is used wherever a kind is named.** The kernel says its own text (graph issues, Ask Rihma's answers
   from the map) in the words in force (`kernel/vocab_say.py`), and the browser does the same over what a view draws
   (`cockpit/static/wordsapply.js`), leaving what people wrote and the Vocabulary views alone. Both read names in one pass, so
   two kinds renamed across each other are not read twice. *Known limit:* the browser reads each text node once, but a word
   a script itself produced from the word in force (a label made from the Vocabulary) is read again, so a chain of renames
   (a requirement called a task while a task is called a story) can read twice in a label the page builds from the word;
   the kernel's text does not.
8. **Hiding a kind leaves the Knowledge graph whole.** The kind leaves before anything is counted, so the counts, the
   issues and a focus agree with what is drawn; the warnings that still hold on the hidden records are counted and said, the
   preview of hiding says how many, and a focus on a hidden record says it is hidden. The graph across projects says which
   words it reads in and which projects say some differently (and no longer counts Rihmasto's own records as a team of its
   own, which had made it fall back to the shipped words whenever they existed).
9. **A person working alone meets no word about teams** on Settings or in their project: the Words card is theirs with its
   long list closed, What applies where is a closed list in plain words with no team row, Rihmasto itself is not offered to
   read it for, and a project's settings have no Team line.

**Requirements.** FR-TM4 (the scope table tells the truth), FR-TM5 (teams stay whole), FR-TM6 (the word in force everywhere;
a hidden kind leaves the graph whole), FR-TM7 (one person meets no team words), in `contract/contract.json`.
