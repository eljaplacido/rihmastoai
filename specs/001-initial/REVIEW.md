# Review of specs/001-initial (working draft)

This is Solution Factory's output from run A2, reviewed against its input.

- **Generator:** Solution Factory, branch `agentic-operating-model` with the worktree
  patches listed in `intake/solution-factory-findings.md`.
- **Model:** `qwen3.6-35b` on the GPU box, temperature 0, auto mode, a 32,000-token output
  budget.
- **Input:** `intake/gnomon-factory-brief.md`, sha256 `59ab509e174263c8…`.
- **Spec:** `spec.md`, sha256 `16b470a533e5e5ce…`.
- **Status:** a working draft. It is not owner-approved. The governing document for work is
  `contract/contract.json`, whose provenance comes from the brief, not from this spec.

## What carried over

- **Requirement IDs:** all 92 IDs in the brief (FR-A1 … FR-O8, NFR-1 … NFR-11) are in
  `spec.md`. No ID was invented.
- **Traceability:** `traceability.md` traces 84 of 92 requirements to 18 tasks, with 0
  orphan citations and 0 untraced tasks.
- **Constitution:** `constitution.md` states the owner's principles faithfully.

## What was lost or changed (read before relying on this spec)

| Issue | Effect | Where the truth is |
|---|---|---|
| Every provenance tag was stripped (`[owner]`, `[proposed]`, `[evidence]`) | The owner's decisions and the design session's proposals read the same | The brief, and `contract/contract.json` (`provenance`, `decided_by`) |
| `plan.md` picks TypeScript and SQLite for the kernel. Run A had picked Rust. | An open owner question (brief §16, Q1) was answered silently, and differently from run to run | Open: owner decision pending |
| NFR-10 and NFR-11 are missing from the formal NFR list (flagged by Solution Factory's own validator) | Language support and the honesty rules can fall out of planning | The brief §8 |
| Milestones (§12) and success measures (§13) are not in the spec | The M0–M4 exits and the targets are absent from planning | The brief §12–13; the contract covers M0 |
| 8 requirements are not covered by any task, including FR-A4 (change-request amendments) | The plan does not implement the whole spec | `traceability.md` |
| Model names appear as decided choices (flagged by the validator) | Proposals and measured candidates read as final | The brief §9 |

## Not used from the blueprint

- `infra/` and `azure-pipelines.yml`: Azure templates for a self-hosted system (findings
  F-1 and F-10).
- Harness-neutral agent rules (`.agent/policy.json`, `CLAUDE.md`, `.cursorrules`): Gnomon
  Factory compiles its rules into `.gnomon/` instead. The wave plan and branching protocol
  in `blueprint/run-a2-local-qwen/docs/agentic/` stay as reference.
