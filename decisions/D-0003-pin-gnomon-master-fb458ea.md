---
id: D-0003
kind: engine pin
proposed_by: operator session (Claude Code), under the owner's standing rule
proposed_on: 2026-11-22
decided_by: owner
decided_on: 2026-11-22
status: approved (owner: "I accept those proposals", given remotely)
---

# Proposed: cells run Gnomon `master` at `fb458ea` until a release includes it

**The owner's rule.** Use Gnomon's latest version, and fix it if something is missing.

**Facts.**
- The latest release, v0.6.5 (`v0.6.5-53f83bd`), does not read `[verify] protects`,
  `exit_on_fail`, `record_detail`, `timeout_seconds` or `exit_map`.
- `master` at `fb458ea` reads them all. A smoke task shows 0 warnings.
- The approved contract (FR-O8-AC-1) names `protects` and `exit_on_fail`.

**Proposal.** Cells on the GPU box run
`node ~/src/gnomonharness-master/packages/gnomon-cli/gnomon.js` (build
`gnomon/0.6.5+fb458ea5`). Every run records that build identity. Move back to a released
version when one includes these keys.

**Alternative.** Stay on v0.6.5 and amend FR-O8-AC-1 to drop the two keys. This was
rejected, because it would weaken an approved criterion to fit the engine.
