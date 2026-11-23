---
id: A-0003
kind: contract-amendment (approved under delegation, see D-0007)
proposed_by: operator session (Claude Code), from the T-006 gate (evidence/T-006/gate.md)
proposed_on: 2026-11-22
amends: contract r2 (or r3 if A-0002 is approved first)
---

# Proposed: the ledger's head is recorded outside the chain, and verify checks against it

**Why.** A hash chain is consistent with itself after events are cut from its end, and
after it is emptied. FR-L1-AC-2 says "changing any stored event" is reported, which a reader
takes to include deleting the last ones, but no chain can see that alone. The blind verifier
on T-006 called the claim over-claimed, and it is. The design already has the remedy in
reserve: FR-C2-AC-1 records a chain head, and Gnomon offers signed and anchored heads
(`[audit.attest]`, `[audit.anchor]`).

**Change.**
- **Add FR-L1-AC-4:** "`append` returns the new head (sequence number and hash). `verify`
  given an expected head reports a ledger that is shorter than it, or whose last hash differs,
  as broken at the first missing sequence number. `verify` without a head says that
  truncation at the end cannot be checked."
- **Where the head is kept:** in the kernel's run record and at each gate, outside the
  ledger's own store. Signing or anchoring the head stays with FR-L3.
- **Task:** fold into T-006 if the owner chooses option 3 at the T-006 gate. Otherwise add it
  as T-012, serving FR-L1-AC-4, with write scope `kernel/ledger.py` and
  `tests/test_ledger.py`, depending on T-006.
