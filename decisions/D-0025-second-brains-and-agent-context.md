---
id: D-0025
decided_by: owner
decided_on: 2026-11-25
kind: principle
---

# Rihmasto builds second brains and their agent context layer

The owner approved the second-brain feature and its proposed scope on 2026-11-25, from a Finnish voice note about
a "knowledge factory": Rihmasto should generate purpose-specific second brains rather than become another
note-taking application. One knowledge source serves both the person's workspace and the agent's context, so a
new conversation does not start from zero.

## Approved product scope

A person specifies the knowledge's purpose, sources, note and folder structure, synchronization and freshness
rules, what agents may read, and what needs approval. Rihmasto generates, tests and maintains that workspace
through the existing contract, gate, evidence and integration machinery. The `knowledge_tooling` profile and
Obsidian-vault recognition are the starting point; their dedicated product template is the missing piece.

The first vertical slice is deliberately small:

- portable Markdown is the canonical knowledge, with source links and provenance;
- an Obsidian-compatible vault is the person's interface;
- a local SQLite full-text index is disposable and rebuildable, not a second source of truth;
- read-only MCP tools search notes and assemble context packs;
- synchronization is incremental, notices changed and deleted sources, and never indexes secrets;
- acceptance includes opening a fresh chat and answering earlier questions with citations and freshness.

PostgreSQL, Qdrant, embeddings and alternative storage backends follow only after that journey works. Build the
knowledge source and its context layer together; do not start by building a configurable database platform.
