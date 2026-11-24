---
id: D-0019
decided_by: owner
decided_on: 2026-11-23
kind: architecture
amends: D-0003, D-0015
---

# Other harnesses may run the factory's cells, opt-in, with the evidence saying so

The owner (2026-11-23) agreed: keep Gnomon as the default harness, and let a team that has standardised
on another harness run the factory's own cells with it.

**What this means:**
- **Gnomon stays the default and the reference.** It enforces the rules during a run: the task's write
  scope, the protected paths (the contract, the specs, the holdouts), fail-first and the hash-chained
  record of every tool call. It also stays the single runtime dependency of the kernel itself.
- **Other harnesses are opt-in.** A project or a factory may choose another cell runner, for example a
  coding agent run headless (Claude Code, OpenCode, Codex). IT approves the choice on a card, with the
  runner's version pinned.
- **Every rule is checked after the run.** The diff stays inside the task's write scope, no protected
  path is touched, the criterion's tests fail first, and the independent verifier and the holdouts pass.
  A change that breaks any of these never merges, whatever the harness said.
- **The evidence says which assurance applied.** A round run by another harness is recorded as "in-run
  policy not enforced by this harness; checked after the run", and its record carries the harness and
  its version. Evidence packs and the cockpit never present it as Gnomon-level assurance.
- **Holdouts stay in custody.** No harness, Gnomon included, ever gets the holdout scenarios.
