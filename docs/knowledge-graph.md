# Knowledge graphs and ontologies in Rihmasto

Status: recommendation, 2026-11-23. Nothing here is built yet. Claims not confirmed from a primary source are marked UNVERIFIED.

## 1. The short answer

Rihmasto already holds a knowledge graph, though nothing calls it one. The kernel gives every record an id (Q-, A-, C-, D-, R-n, R-n-AC-n, T-, S-). Records point at each other through `refs` dicts, `requirement.sources`, `depends_on`, criterion-id prefixes and test names. The hash-chained ledgers hold the history. `insight.impact` and `Canon.mark_stale` follow these links in hand-written code, and some of that code is wrong: `releases_carrying` lists every release.

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
- Today the redaction code is split between `mcp/server.py` and `kernel/deliver.py`. It moves into one module, `kernel/custody.py`.
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
- The domain or email address used in IRIs.
- Whether person names are pseudonymised in exports.
- Confirming that `graph check` only reports and never blocks.
- Whether `ontology.json` is added to the protected files.
- A change card for an existing leak: the evidence pack ships `ledger.jsonl` unredacted, including `holdouts_authored.reauthored_because`. That field can quote a scenario, and the MCP server already redacts it.

**Phase 1: build now, with no change to any write path.** The custody module, the ontology file, `graph.py` for one project, and parity with today's hand-written walkers. That parity work reports the release-hop bug and the dead `refs.scope == 'release'` branch. Phase 1 also adds a read-only `rihma graph` CLI command and an assistant eval baseline. Its acceptance criteria are at the end of this page.

**Phase 2: use it.**
- The insight functions become adapters over the graph.
- The cockpit gets a lineage view and the blast radius on change cards.
- Read-only MCP tools.
- A release-scoped JSON-LD file in the evidence pack.
- `refs` keys checked when written, as a warning only.
- Assistant grounding, switched on only if the eval shows improvement.
- Recipe and Trial kinds, declared before the recipes work merges.

**Phase 3: widen, after measuring.**
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

1. Given holdout scenarios containing sentinel strings, when the graph is built and every query and export is rendered, then no sentinel appears and no graph module references `holdouts_dir`.
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
