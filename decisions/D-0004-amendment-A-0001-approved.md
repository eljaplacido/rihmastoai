---
id: D-0004
decided_by: owner
decided_on: 2026-11-22
kind: contract-approval
subject: contract/contract.json
supersedes: D-0001 (r1, sha256:2cfffb04…ba6ea)
revision: sha256:814654179e093d347a3d245035b1446cd6a848101e9685a2be9a6ec628afb67e
---

# Contract r2 approved: amendment A-0001 applied

The owner accepted amendment A-0001 ("I accept those proposals", given remotely while away
from the workstation). The amendment adds:
- criterion **FR-O8-AC-3**, which requires the engine to enforce every rule the surface
  declares. It is checked by `tools/preflight.py` against the Gnomon build pinned in D-0003.
- task **T-010 Preflight**.

r2 has 11 requirements, 25 criteria and 10 tasks.

T-010 was built by the operator session, outside Gnomon, in the same commit as this
record. That kept `main` green: FR-O8-AC-3 is customer-confirmed, so leaving it unnamed
would have failed the repository's own trace test (FR-O8-AC-2) for every cell. Its evidence
tier is *evidenced* (12 tests). The probe itself is run on the GPU box next.
