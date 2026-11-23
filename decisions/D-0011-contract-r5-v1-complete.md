---
id: D-0011
decided_by: operator session, under the owner's delegation ("finish it end to end")
decided_on: 2026-11-22
kind: contract-approval
subject: contract/contract.json
supersedes: D-0009 (r4)
revision: sha256:206480918bd75c12d200e60159b09be045fe6fb9335c65745b212b29f998e711
---

# Contract r5: the rest of v1

r5 adds the criteria for the parts of v1 built after r4:
- the cockpit: FR-T1, FR-M6-AC-3, FR-A6-AC-4, FR-I1;
- delivery and operation: FR-A8, FR-Q4, FR-H3, FR-Q5, FR-H7, FR-H4, FR-I2;
- the factory learning from its products: FR-K3, FR-F8;
- IT's road cards: FR-Q2;
- customer ids: FR-A3-AC-2;
- the CLI and pipeline: FR-N2.

They are served by tasks V-06 to V-09.

The cockpit and delivery were built by delegated agents in isolated worktrees, reviewed by the
operator and merged. Their findings were fixed in the operator's modules:
- letting the factory assume, and settling an assumption, are now signed decisions;
- the product template served no routes when started as a module. That was a real bug,
  confirmed on Docker. The new FR-O2-AC-5 test fails on the old template.

r5 has 38 requirements, 67 criteria and 20 tasks. 58 are named by tests; 169 tests pass. The 9
not measured are M0's adapter, pricing and views tasks (T-005, T-007 to T-009).
