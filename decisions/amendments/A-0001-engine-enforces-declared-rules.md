---
id: A-0001
kind: contract-amendment
status: approved by the owner on 2026-11-22 ("I accept those proposals", given remotely); applied as contract r2, see D-0004
proposed_by: operator session (Claude Code)
proposed_on: 2026-11-22
amends: contract/contract.json r1 (sha256:2cfffb04…ba6ea)
---

# Proposed: the engine must enforce every rule the surface declares

**Why.** Under the Gnomon v0.6.5 release, five `[verify]` keys this repository declares
were silently ignored, and the FR-O8-AC-1 test still passed, because it reads declarations
(see `docs/m0-log.md`). A criterion that checks only what is written down cannot catch an
engine that does not read it.

**Proposed change.** Add a criterion to FR-O8:

```json
{"id": "FR-O8-AC-3",
 "given": "this repository's surface and the Gnomon build pinned for cells",
 "when": "preflight runs a smoke task under that build",
 "then": "the engine reports no declared key it does not read and no surface problem; any such warning fails preflight",
 "check": {"kind": "probe", "command": "tools/preflight (to be written; runs the smoke task and reads its warnings)"}}
```

Also add a task `T-010 Preflight` serving FR-O8-AC-3, with write scope
`tools/preflight.py` and `tests/test_preflight.py`.

**Effect if approved.** The contract moves to r2. The kernel will not dispatch a cell while
preflight fails.
