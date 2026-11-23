# Knowledge graphs and ontologies in Rihmasto

Status: phase 1 built, 2026-11-23 (requirement FR-KG1, task KG-1); phases 2 and 3 are designed, not built.
[Built in phase 1](#built-in-phase-1) says what exists and how to use it, and where it differs from the
design that follows. Claims not confirmed from a primary source are marked UNVERIFIED.

## Built in phase 1

The kernel modules are standard-library Python, like the rest of the kernel. Nothing is stored and no write
path changed.

| Module | What it does |
|---|---|
| `kernel/custody.py` | The one redaction module: `custody_safe`, `held_strings`, `redact`, `ledger_record`. The MCP server and delivery import it; their own copies are gone. |
| `kernel/ontology.json` | The ontology, version 1.0.0: 19 kinds, 29 relations, the 24 `refs` keys the kernel writes and the ledger fields the graph reads, with each kind's audiences. Write-protected. |
| `kernel/ontology.py` | Loads and validates it: ids, labels, descriptions, aliases, consumers and enum references that resolve, relations between declared kinds with declared origins. |
| `kernel/graph.py` | The `Graph` read model, its stamp and its queries: `trace`, `impact`, `path`, `as_of`, `check`, `show` and `view`. |
| `kernel/graph_build.py`, `kernel/graph_records.py` | The build: the ledger (its chain checked first), the spec snapshots, the contract, the tests on main, then the canon, releases, packs, builder rounds and the signals routed to the project. |
| `kernel/graph_ask.py` | The questions people ask, parity with `insight.impact`, the assistant eval baseline, and `rihmasto graph`. |

**The command.** Every subcommand only reads, prints JSON and exits 0; an unknown project is refused with
exit 2.

```bash
rihmasto graph trace <pid> R-2              # what R-2 rests on, back to the person who answered
rihmasto graph impact <pid> R-1 R-2         # what rests on them: criteria, tests, tasks, approvals, releases
rihmasto graph path <pid> R-2 person:Aino   # the shortest chain of links between two records
rihmasto graph check <pid>                  # closed-world rules: it reports and never blocks
rihmasto graph show <pid> --audience builder
rihmasto graph refuted <pid>                # releases that rest on a refuted assumption
rihmasto graph answers <pid> Aino           # criteria that trace back to Aino's answers
rihmasto graph approvals <pid>              # who approved each production release; does it still hold?
rihmasto graph parity <pid> R-1             # graph impact against insight.impact on the same ids
rihmasto graph eval <pid> --with-model      # the assistant baseline; not measured without a model
```

`trace`, `impact`, `path`, `check`, `refuted`, `answers` and `approvals` take `--as-of <ledger seq>`: the
links valid then, between the records that existed then.

**Ids.** A requirement version is `R-2@v1`, and a plain `R-2` names the version in force. A criterion is
`R-2-AC-1@<12 hex digits of its given, when and then>`; a plain criterion id is `ambiguous` once an amendment
restated it, and its content key names one version. Other nodes: `Q-001`, `A-001`, `C-0004`, `D-003`, `T-001`,
`S-001`, `CM-001`, `person:<name>`, `test:<name>`, `release-<n>`, `pack-<version>`, `H-<criterion>`,
`round:<task>/<n>@<seq>`, `model:<id>`, `rev:<sha>`. A `by` pointer names the record that holds a link:
`spec.v1.json#R-2`, `canon/decisions.json#D-003`, `canon/inbox/C-0004.json`, `ledger.jsonl#17`, `repo.git#main`.

**An answer** carries the `query`, the `stamp`, its findings (`steps`, `proposed`, `cites`, and per query
`result`, `rows` or `findings`) and, last, its `outcome`. `impact`'s `result` has the same fields as
`kernel.insight.impact`, so a change card's blast radius can move onto the graph in phase 2.

**Not measured, and why.** A graph checks its stamp before it answers. It answers `not_measured`, naming the
cause, when the ledger's hash chain is broken; when the ontology does not validate; when the canon holds what
the ledger does not record; and when a source file, the ledger, main or the ontology changed after the graph
was built ("canon/questions.json changed since the graph was built, with no ledger event"). The canon is
compared with the ledger field by field, so a hand edit made before a fresh build is caught too:

| Canon record | Must match |
|---|---|
| A question | a `question_added` event; if answered, its `question_answered` event's `by` and `persona`; if assumed, its `question_assumed` event's `assumption` and `chosen_by`; if open, no such event |
| An assumption | an `assumption_added` event; its status (`open`, `confirmed`, `refuted`) is the one its `assumption_settled` event records, or `open` when there is none |
| A decision | its `decision` event's `card`, `kind`, `verdict`, `person`, `persona` and `refs`; its `approving` flag is the kernel's rule for that kind and verdict (`kernel.canon.APPROVING`) |
| A stale flag | an `approvals_stale` event that names the decision, both ways: a flag with no mark, or a mark with no flag, is caught |

Whether an approval went stale is read from the ledger's mark, never from the flag in `decisions.json`. Cards
and comments are not compared: a card's `refs` change legitimately after it opens (a plan redone, a ruling
applied), with no event that records the new value. The spec snapshots, the contract, `tasks.json` and the
release files have no copy in the ledger to compare against either: the stamp catches an edit made after a
build, but not one made by hand before a fresh build. Recording their hashes in the ledger would change a
write path, so it is left to phase 3 (write-path fixes through the change loop).

**Holdout custody.** No graph module reads the custody or names its folder. A release's holdout verdicts are
read in a closed shape (a criterion id and a named verdict) and its reason through `custody_safe`. Card titles,
bodies and payloads (except a triage's class and requirements), decision reasons, and the text of comments,
signals and requests never enter the graph. A comment's target links only when it has the shape of the id it
names (a requirement, criterion, task, card or release id); any other target is outside text, reported as a
`dangling_ref` without its words. Each kind declares its audiences: builders never see held-out checks,
cards, decisions, comments or signals. An audience's view (`graph show --audience`, `Graph.view`) keeps only
the findings whose records and nodes that audience may see: a builder sees no pointer into the canon's cards,
decisions, comments, questions or assumptions, the ledger or the signals. An audience that may not see every
kind (verifier, builder) is told only that the records cannot be measured, not which ones disagree. A canary
test plants sentinel strings, one of them in a comment's target, and renders every query.

**Owner decisions applied.** `graph check` only reports and never blocks. `kernel/ontology.json` joined the
protected files: no contract task may claim it (`tools/contract_check.py`), and the builder surface
write-protects it for every role (`.gnomon/policy.toml`, `[governance.paths]`). The contract check refuses a
write scope that names a protected path or covers it in any spelling: a glob (`kernel/**`, `kernel/*.json`,
`kernel/onto*`, `**/ontology.json`), a folder above it (`kernel`, `kernel/`), `./`, `//` or `..` in the path,
a `{a,b}` group, or another case. It errs on the side of refusing: `*` and `?` may cross a `/`. The same holds
for `contract/`, `specs/`, `intake/` and `decisions/`. The surface change takes effect only once the owner
runs `gnomon trust` on it; until then Gnomon's policy does not protect the file, only the contract check does.
Still open from phase 0: the domain or email address for IRIs, whether exports pseudonymise names, and the
change card for the evidence pack's ledger.

**What parity found.** `insight.impact` listed every release as carrying the ids; it now lists only the
releases whose `requirements` include them, and `graph impact` agrees with it field for field on the test
fixtures. The `refs.scope == "release"` branch in `Canon._rests_on` and `insight.impact` is dead: nothing in
`kernel/` writes that scope. `graph parity` reports it; removing the branch is left to a change of
`kernel/canon.py`.

**Where phase 1 differs from the design below.**
- Only kinds a phase 1 read model uses are declared. Contract, Persona, Lesson, Incident, Finding, Control,
  Recipe and Trial are not: an incident is a card, a persona is a qualifier on `answered_by` and `signed_by`,
  and `refs.trial` is declared an attribute until the Trial kind comes (phase 2).
- A requirement's `sources` are `kernel` links: the kernel accepted them into the spec by rule. A triage's
  requirements are the `model_proposed` links, as section 2 says. Two sources name no record and link
  nothing: `proposed` (the analyst proposed it) and `observed` (an adopted project's as-is requirement,
  observed in its code); the requirement's provenance says which.
- The scan test covers every `refs` key written in `kernel/`, and checks that each ledger field the graph
  reads is one the kernel writes. A scan of every id-bearing ledger field is planned with phase 2's
  write-time warning on `refs` keys.
- `rihmasto graph show` renders the graph to stdout. It is not an export: exports (JSON-LD, each logged as
  `graph_exported`) are phase 2.
- `as_of` filters links and records by sequence number; the tests on main are read as main is now.
- The graph is four modules, not one, to keep each under the quality gate's 500 lines.

## 1. The short answer

Rihmasto already holds a knowledge graph, though nothing calls it one. The kernel gives every record an id (Q-, A-, C-, D-, R-n, R-n-AC-n, T-, S-). Records point at each other through `refs` dicts, `requirement.sources`, `depends_on`, criterion-id prefixes and test names. The hash-chained ledgers hold the history. `insight.impact` and `Canon.mark_stale` follow these links in hand-written code, and some of that code was wrong: `releases_carrying` listed every release (fixed in phase 1).

- **The ontology** is the declared schema of Rihmasto's own records. It says which kinds of record exist, which links between them are allowed, how each link is known, and who may create or decide each one. It is small and closed, and the kernel owns it.
- **The knowledge graph** is a read model rebuilt from the ledgers and canon. It is never a store and never a second source of truth.
- **Standard formats** are exports for auditors' tools. They are never dependencies.

What they should not be:
- a graph database inside the kernel;
- RDF as the storage format;
- OWL reasoning, because the kernel's rules are closed-world checks;
- a graph that a model extracts from text, which would add guesses where the kernel already has certainty.

Later, each product can add a **domain glossary**: business terms linked to the requirements that use them, approved by the business owner. That glossary is where business and technical requirements meet.

## 2. The ontology

**Format.** The ontology lives in `kernel/ontology.json` and is read with the standard library's `json` module. Its shape borrows three ideas from the Neo4j Ontology Graph Spec: stable ids kept separate from labels, plus a description and aliases on every kind and relation.

Enums are referenced, not copied. For example, `"verdicts": "canon.CARD_VERDICTS"` resolves to the constant in the code, so there is only one source for each list. Each relation names the read model that uses it; a relation that no read model uses is removed.

| Node kind | Key | Standard term |
|---|---|---|
| Signal, Concept, Question, Assumption | S-, concept card, Q-, A- | prov:Entity |
| Person, Persona | a name (not an identity); 9 personas | prov:Person, prov:Role |
| Requirement@v | R-n, customer id or FD-n, per spec version | oslc_rm:Requirement |
| Criterion | `<rid>-AC-n@<sha of given/when/then>` | — |
| Contract, Task | revision hash, T- | prov:Plan |
| Round, Model, Revision, Test | (task, round); model id; git sha; test name | prov:Activity, prov:SoftwareAgent |
| HoldoutRef | H-<cid>: id, criterion, kind, verdicts only | — |
| Card, Decision | C- (12 kinds), D- | prov:Entity, prov:Activity |
| Release, Pack, Incident, Observation, Finding, Lesson, Comment | key per file | prov:Entity |
| Control | ai-act:art12 … nis2:art21 | ELI, DPV (phase 3) |

| Relation | From → to | Carried today by | Standard term |
|---|---|---|---|
| derived_from | Requirement@v → Question, request, change card | `sources` in each spec version | prov:wasDerivedFrom |
| revision_of | Requirement@v, Contract → previous | spec snapshots, ledger order | prov:wasRevisionOf |
| answered_by, assumed_as | Question → Person (persona), Assumption | `answer` | prov:qualifiedAssociation + hadRole |
| has_criterion, checked_by | Requirement@v → Criterion → Test, HoldoutRef | id prefix, test name, `check.ref` | oslc_rm:decomposedBy, validatedBy |
| serves, depends_on | Task → Criterion, Task | contract | oslc_rm:implementedBy |
| ran_on, produced | Round → Model, Revision | `cell_ran`, `gnomon_run`, `merged` | prov:wasAssociatedWith, prov:generated |
| carries, versions | Release → Requirement@v; Pack → Release | release file, `packs.json` | prov:wasDerivedFrom |
| signed_by, approves | Decision → Person (persona), Release | `decisions.json`, card refs | prov:qualifiedAssociation |
| invalidated_by | Decision → change card | `approvals_stale` | prov:wasInvalidatedBy |
| touches | change card → Requirement | triage payload | oslc_rm:affectedBy |
| raised_from, about | Card → Signal; Comment, Incident → any node | `routed_to`, `target` | — |
| evidences | record → Control | new; compliance persona only | NIST IR 8477 relationship |

**Every edge carries three things:**
- an origin: `kernel`, `convention`, `model_proposed` or `person_confirmed`. This applies the verified-versus-claimed rule to links.
- a validity window measured in ledger sequence numbers, so an "as of" question becomes a simple filter.
- a `by` pointer to the record that holds the link.

The list of requirements a triage names stays `model_proposed` until a person decides the card.

**Versioning.** The ontology has a semver version and an `ontology_sha256` hash, both stamped on every graph and export. Changes go through the factory's own contract, which only the owner amends.

**Validation.** `kernel/ontology.py` checks the file itself. A scan test fails if any `refs` key or id-bearing ledger field in `kernel/` has no declared relation. `graph.check` validates a built graph against closed-world rules; it is the native counterpart of SHACL 1.0.

## 3. Architecture

**Source of truth: unchanged.** `kernel/graph.py` rebuilds the graph from the ledgers and record files each time it is read. It reads the `spec.v<n>.json` snapshots, which no code reads today. That recovers the provenance an amendment overwrites when it replaces `requirement.sources`.

**Stamp.** Each graph is stamped with four things: the ontology hash, the ledger heads, the main git sha, and a hash of every source file read. The file hashes are needed because `questions.json` and `tasks.json` change without a ledger event. If the stamp is stale or a ledger chain is broken, answers come back as `not_measured`, never silently wrong.

**Storage and query.**
- Phase 1 stores nothing. A cache that can be deleted at any time (JSON, or SQLite with `WITH RECURSIVE` queries) comes only if build time is measured as a problem.
- Queries: `trace` (upstream), `impact` (downstream), `path`, `as_of` and `check`.
- Every step in an answer cites record ids. Each answer ends in one of four outcomes: `answered`, `ambiguous`, `not_found` or `not_measured`.
- Edges a model proposed come back separately and never feed write paths.

**Exports.**
- Exports are one-way and written with the standard library. Each is stamped and logged as a `graph_exported` event by a person whose persona may export evidence.
- The first format is JSON-LD 1.1 using PROV-O and OSLC terms, on RDF 1.1 only, because RDF 1.2 is still a Candidate Recommendation.
- A Cypher script or a Neo4j-spec document is made only on request. Compatibility is claimed only for tools the export has actually been loaded into in a test.
- Ids are RFC 4151 tag URIs under a domain name or email address the operator owns.

**Independence.** The kernel stays standard-library only, and Gnomon stays its single runtime dependency. Optional adapters, such as graph-database loaders and pySHACL cross-checks, live in `tools/`. That folder is outside the folders the quality gate keeps standard-library only.

**Holdout custody.**
- The redaction code, once split between `mcp/server.py` and `kernel/deliver.py`, is one module, `kernel/custody.py` (built in phase 1).
- Graph code never references `holdouts_dir`.
- HoldoutRef reads release verdicts through `custody_safe`, because the reasons stored with a release can quote a scenario.
- Each kind declares which audiences may see it. Builders and verifiers never see holdout or probe text. Builders never see outside text (signals, comments, embeds), and outside text can never create an edge.
- Graph context is never written to the analyst lane, because `holdout_author` shares that lane.
- A canary test fails if a planted scenario string appears anywhere.

## 4. What it enables, ranked

1. **Cockpit questions.**
   - A correct blast radius on change cards.
   - Who approved what runs in production, and does that approval still hold?
   - Which releases rest on a refuted assumption?
   - Which criteria trace back to a named person's answer?
2. **Compliance mapping.** Each row of the evidence pack's control table becomes a path query, written by the compliance persona. It returns one release's records, or "no evidence". It never says "compliant".
3. **Assistant grounding.** Today's flat snapshot cannot answer "why" questions that need several hops. The graph neighbourhood of the ids in view can. The gain is not measured until an eval runs.
4. **Builder and workspace context.** A code map built with the standard library's `ast` module: symbols, calls, routes, and tests mapped to criteria.
   - People get it first: a structural diff on an adopted repository's "Upstream changed" card, and a code map in the workspace's `context.md`.
   - Builder envelopes get it only after the ledgers show it helps.
5. **Recipes.** Which projects descend from a recipe whose source pack is no longer valid?
6. **Fit.** What depends on model M if it is retired? One question stays out of reach: which capability uses a component with a CVE. Packs must first declare their runtime components.

## 5. Phased plan

**Phase 0: decisions for the owner.**
- The domain or email address used in IRIs. *Open.*
- Whether person names are pseudonymised in exports. *Open.*
- Confirming that `graph check` only reports and never blocks. *Decided: it only reports.*
- Whether `ontology.json` is added to the protected files. *Decided: it is; the surface change waits for the
  owner's `gnomon trust`.*
- A change card for an existing leak: the evidence pack ships `ledger.jsonl` unredacted, including `holdouts_authored.reauthored_because`. That field can quote a scenario, and the MCP server already redacts it. *Open.*

**Phase 1: build now, with no change to any write path.** *Built (FR-KG1).* The custody module, the ontology file, `graph.py` for one project, and parity with today's hand-written walkers. That parity work reports the release-hop bug and the dead `refs.scope == 'release'` branch. Phase 1 also adds a read-only `rihmasto graph` CLI command and an assistant eval baseline. Its acceptance criteria are at the end of this page.

**Phase 2: use it.** *Planned.*
- The insight functions become adapters over the graph.
- The cockpit gets a lineage view and the blast radius on change cards.
- Read-only MCP tools.
- A release-scoped JSON-LD file in the evidence pack.
- `refs` keys checked when written, as a warning only.
- Assistant grounding, switched on only if the eval shows improvement.
- Recipe and Trial kinds, declared before the recipes work merges.

**Phase 3: widen, after measuring.** *Planned.*
- Control mappings using ELI and DPV terms.
- SHACL shapes for auditors.
- SPDX 3.0.1 or CycloneDX 1.7 documents for packs.
- The code map.
- Write-path fixes, made through the change loop.
- Domain glossaries.

## 6. The tools from the list

| Tool | Licence | Where it fits |
|---|---|---|
| NVIDIA Auto Ontology | Apache-2.0 | Inspiration: experts certify generated terms, and answers carry provenance. Needs Postgres and model endpoints. Offline use UNVERIFIED. |
| AWS Context Ontology Accelerator | Apache-2.0 | Not for us (Bedrock, Neptune). Lesson: models draft, people approve every element. |
| OpenBKN Foundry | OpenBKN License (Apache-2.0 plus restrictions; not OSI) | Not for us (Kubernetes, licence). Idea: permissions in the ontology, as `CARD_DECIDERS` already does. |
| Open Ontologies | MIT | Inspiration: plan, apply and roll back a change, with its blast radius shown first. |
| Neo4j Ontology Graph Spec | Apache-2.0 | Template for the file's shape; optional export. A few weeks old, run by one vendor, not RDF. |
| Relate by Neo4j | Apache-2.0 | Optional export target. "Alpha" status and conformance claims UNVERIFIED. |
| cognee | Apache-2.0 | Not for the kernel. Offline GLiNER2 extraction UNVERIFIED (sources disagree). |
| Semantica | MIT | Inspiration: PROV-O provenance on every fact. Too broad to adopt. Accuracy figures UNVERIFIED. |
| Ontology Atlas | MIT | Inspiration: plain files in the repository, and "unknown" instead of a guess. Its own benchmark showed no gain. |
| Graphify | Apache-2.0 (an MIT file is also present) | Inspiration: edges labelled EXTRACTED or INFERRED. Optional input for repositories not written in Python. Benchmarks self-reported. |

LadybugDB (MIT) and Oxigraph (MIT or Apache-2.0) are also possible export targets. Kuzu was archived in October 2025, which shows why any graph store must stay optional.

## 7. Risks

| Risk | Avoided by |
|---|---|
| Stale graph | Rebuild on read; stamp includes a hash of every source file. |
| Model guesses shown as fact | Origin on every edge; impact, evidence and the gate ignore `model_proposed` edges. |
| Holdout leak | One redaction module, a closed HoldoutRef shape, declared audiences, a canary test. |
| Schema drifting from code | Enums referenced, not copied; the scan test fails hard. |
| Criterion ids reused after an amendment | Criteria keyed by a hash of their content; old links flagged "ambiguous after amendment". |
| Over-engineering | Every relation names the read model that uses it; nothing added before a measured need. |
| Unproven gains for agents | Eval baseline first; agent features off until measured. |
| Personal data | Names appear only where `decisions.json` already has them; pseudonymising is the owner's call. |
| Regulatory drift | Regulation (EU) 2026/1744 amended the AI Act after DPV 2.3 and AIRO were published. Its new deadlines are UNVERIFIED against the Official Journal. |

## Phase 1 acceptance criteria

All built. Each is criterion FR-KG1-AC-n of the factory's contract, with the same number, proved by the tests
named after it in `tests/test_graph.py` and `tests/test_graph_custody.py`. Criteria 12 and 13 carry the owner's
phase 0 decisions. Criteria 14 to 16, and the glob part of 12, came from an independent check of the first
build, which forged canon records by hand, claimed the ontology with globs, planted text in a comment's target
and checked an adopted project.

1. Given holdout scenarios containing sentinel strings (and outside text, a comment's target among it), when the graph is built and every query and export is rendered, then no sentinel appears and no graph module references `holdouts_dir`.
2. Given the redaction code moved into `kernel/custody.py`, when the test suite runs, then the MCP and deliver tests pass unchanged.
3. Given `kernel/ontology.json`, when it is loaded, then every kind and relation has an id, a description and a consumer, and every enum reference resolves.
4. Given every `refs` key written in `kernel/`, when the scan test runs, then each maps to a declared relation; and given an unknown key in a project, when the graph is built, then it reports an `unmapped_ref` finding.
5. Given a built graph, when its edges are listed, then each has an origin, a validity start and a `by` pointer, and edges from a triage stay `model_proposed` until their card is decided.
6. Given the test fixtures, when `graph.impact` and `insight.impact` run on the same ids, then they agree except that releases are limited to those that carry the ids, and the approvals found are the same ones `Canon.mark_stale` would mark.
7. Given a requirement whose `sources` an amendment replaced, when `trace` runs, then it reaches the original question and its answer or assumption.
8. Given hand-written expected answers, when the graph is asked which releases rest on a refuted assumption, which criteria trace to a person's answer, and who approved a production release and whether that approval still holds, then each answer matches.
9. Given `questions.json` changed without a ledger event, or a broken ledger chain, when the graph is queried, then the outcome is `not_measured` and names the cause; and given an unknown or duplicated id, when it is queried, then the outcome is `not_found` or `ambiguous`.
10. Given the quality gate, when it runs, then the new kernel modules import only the standard library.
11. Given the assistant eval, when it runs, then it reports cited-id recall and the rate of citations not backed by a record, or `not_measured` when no model endpoint answers.
12. Given `kernel/ontology.json`, when the contract is checked and the builder surface is read, then a task that claims write access to it fails (by name, or by any glob, folder or spelling that covers it), no task claims it, and the surface write-protects it for every role.
13. Given a project whose graph has findings, when every `rihmasto graph` subcommand runs, then each answer ends in one of the four outcomes, `check` reports its findings and never blocks, and no file in the factory home changes.
14. Given canon records edited by hand so that they disagree with the ledger (an assumption's status, a decision's refs, persona, kind or approving flag, a removed stale flag, a question's answer or status), when the graph is built afresh and asked, then the answer is `not_measured` and names the record, and an approval the ledger marked stale counts as stale whatever `decisions.json` says.
15. Given findings about cards, decisions and comments, and a comment's target that names no record, when the graph is shown to each audience, then the target's words appear nowhere, each audience's findings name only records it may see, and an audience that may not see every kind is not told which records disagree.
16. Given an adopted project whose requirements were observed in its code, when its graph is checked, then no requirement reports a dangling source.
