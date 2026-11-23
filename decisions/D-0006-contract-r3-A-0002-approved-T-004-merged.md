---
id: D-0006
decided_by: owner
decided_on: 2026-11-22
kind: contract-approval and merge
subject: contract/contract.json, cell/T-004
supersedes: D-0004 (r2, sha256:8146541…afb67e)
revision: sha256:58cf5a4b73ab17ffc8c76ace3ba23427a9a9f7d2c4a34a278ca918668de49d56
---

# Contract r3 approved (A-0002, A-0003), and T-004 merged

The owner said: "merge T4, approve A2, and conclude the rest as you see best, and keep on
finishing."

- **T-004 merged** into `main` (`adbd8e3`). Objection O-1 from its gate is answered by A-0002.
- **A-0002 approved by the owner.**
  - FR-G3-AC-1 now says violation, regressed and escalate never combine into passed.
  - New criterion FR-G3-AC-3: a translation table may hold named verdicts only.
  - New task T-011 tightens `kernel/verdicts.py`.
- **A-0003 approved under the owner's delegation** (D-0007). New criterion FR-L1-AC-4
  covers the ledger head, and it is folded into T-006.

r3 has 11 requirements, 27 criteria and 11 tasks.
