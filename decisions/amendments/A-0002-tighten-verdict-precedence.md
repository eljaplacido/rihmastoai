---
id: A-0002
kind: contract-amendment (approved, see D-0006)
proposed_by: operator session (Claude Code), from objection O-1 on T-004
proposed_on: 2026-11-22
amends: contract r2
---

# Proposed: no verdict other than "passed" or "not applicable" may combine into "passed"

**Why.** T-004 met FR-G3-AC-1 as written, yet `combine_verdicts(["passed", "violation"])`
returns `"passed"` (evidence/T-004/gate.md, O-1). The criterion did not say what
`violation`, `regressed` and `escalate` do, so a cell could leave them neutral.

**Change.**
- **Replace FR-G3-AC-1's `then` with:** "combining verdicts gives failed if any is failed or
  regressed; else violation if any is violation; else escalate if any is escalate; else not
  measured if any is not measured or all are not applicable (an empty set included); else
  passed. Only passed and not applicable can combine into passed."
- **Add FR-G3-AC-3:** "a translation table whose values are not all named verdicts is
  rejected."
- **Add task T-011:** "Verdict precedence, tightened", serving FR-G3-AC-1 and FR-G3-AC-3, with
  write scope `kernel/verdicts.py` and `tests/test_verdicts.py`, depending on T-004.
