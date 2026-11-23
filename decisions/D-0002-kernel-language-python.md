---
id: D-0002
decided_by: owner
decided_on: 2026-11-22
kind: architecture
answers: intake/gnomon-factory-brief.md §16 Q1
---

# The kernel is written in Python, standard library only

**Decision.** The Gnomon Factory kernel and its tools are Python, using the standard library
only (Python 3.11 or later, for `tomllib`).

**Why.**
- It matches the deterministic tools already built (`tools/contract_check.py`,
  `tools/contract_trace.py`).
- It keeps zero runtime dependencies besides Gnomon.
- It is the fastest route to M0.
- The kernel talks to Gnomon only through its CLI and JSON, so Gnomon's own language does
  not matter.

**Alternatives considered.**
- TypeScript was proposed by Solution Factory run A2's plan.
- Rust was proposed by run A's plan.

Both were model choices made without the owner (findings F-9, F-12), and both are recorded
here as rejected.

**Consequence.** `specs/001-initial/plan.md` (TypeScript) is superseded on this point. The
envelopes `envelopes/T-004.md` … `T-009.md` already target Python with the standard library
only.
