# Task Breakdown


## Phase: Foundation: Ledger, Kernel & Intake

### T-001 — Implement Hash-Chained Ledger Storage
**Complexity:** medium

Create the SQLite schema and append-only logic for the ledger. Implement hash chaining for runs, artifacts, envelopes, gate decisions, approvals, signals, prices, and phase transitions. Ensure every view is a projection of this ledger.

**Acceptance Criteria:**
- [ ] Ledger table supports append-only inserts.
- [ ] Each entry contains a hash of the previous entry.
- [ ] Schema includes fields for all specified event types.
- [ ] Import-graph check script exists and enforces no model imports in kernel code.

### T-002 — Implement Closed Intake Contract Parser
**Complexity:** medium
**Depends on:** T-001

Build the parser for closed intake contracts. Validate file hashes, roles, and exact record counts. Reject packages with mismatched counts, providing file, line, expected, and got values, and write nothing downstream.

**Acceptance Criteria:**
- [ ] Parser accepts manifest with hashes, roles, and counts.
- [ ] Mismatched counts trigger rejection with specific error details (file, line, expected, got).
- [ ] Rejection results in no downstream writes.
- [ ] Incomplete intake produces a send-back list tracked by content hash.

### T-003 — Implement Vague Explanation to Contract Compiler
**Complexity:** complex
**Depends on:** T-002

Implement the logic to accept vague explanations, classify them, and ask guided questions. Sign answers to record provenance. Refuse briefs that are too ambiguous with reasons.

**Acceptance Criteria:**
- [ ] System accepts vague text input.
- [ ] Classifier proposes domain/structure.
- [ ] Guided questions are generated for ambiguities.
- [ ] Answers are signed with user identity.
- [ ] Too ambiguous briefs are refused with reasons.
- [ ] Output is a machine-readable contract with provenance.

### T-004 — Implement Spec Compilation & Contract Hashing
**Complexity:** complex
**Depends on:** T-003

Compile requirements spec into a content-hashed contract. Include acceptance criteria (given/when/then), checks, banned terms, and non-functional probes. Ensure every criterion traces to a task and every task to a criterion.

**Acceptance Criteria:**
- [ ] Contract is content-hashed.
- [ ] Acceptance criteria include given/when/then.
- [ ] Checks are linked to criteria.
- [ ] Banned terms and scopes are defined.
- [ ] Compilation fails if customer-confirmed criterion has no check.
- [ ] Traceability matrix exists: criterion <-> task.


## Phase: Core: Envelopes, Roles & Gnomon Integration

### T-005 — Implement Work Envelope Structure
**Complexity:** simple
**Depends on:** T-001

Define and implement the Work Envelope data structure with all required fields (goal, contract revision, base revision, requirement references, read/write scope, role, budget, stop condition, required evidence, parent). Enforce inheritance of limits for nested envelopes.

**Acceptance Criteria:**
- [ ] Envelope schema includes all specified fields.
- [ ] Nested envelopes inherit limits and cannot widen them.
- [ ] Validation ensures all required fields are present.

### T-006 — Implement Gnomon Surface Compilation
**Complexity:** medium
**Depends on:** T-004, T-005

Compile Gnomon surfaces (.gnomon/policy.toml, .gnomon/roles.toml) from the contract, check plan, and envelope. Define write scopes, governance paths, and verify settings (test_must_fail_first, etc.).

**Acceptance Criteria:**
- [ ] Generates policy.toml with governance.paths.
- [ ] Generates roles.toml with six roles: scout, builder, verifier, assembler, repairer, triager.
- [ ] Verify section includes test_must_fail_first, protects, exit_on_fail, record_detail, finish gate.
- [ ] Write scopes are correctly derived from envelopes.

### T-007 — Implement Gnomon Task Execution & Streaming
**Complexity:** complex
**Depends on:** T-005, T-006

Execute envelopes as Gnomon tasks in isolated worktrees. Stream live progress and permission requests via Gnomon's ACP interface. Record task records, audit chain head, surface hash, and build identity.

**Acceptance Criteria:**
- [ ] Tasks run in isolated worktrees.
- [ ] Live progress streams to factory via ACP.
- [ ] Task records include audit head, surface hash, build identity.
- [ ] Exit buckets (result, refusal, apparatus failure) map to factory verdicts.
- [ ] Native values are stored beside translations.
- [ ] Apparatus failures are excluded from success rates.

### T-008 — Implement Post-Run Check & Criterion Verification
**Complexity:** complex
**Depends on:** T-007

Implement 'gnomon check --base <rev>' logic. Trace each criterion through test reports at head and base revisions. Verify criteria based on conditions: test passed at head/failed at base, verify passed, check exits 0, holdouts passed.

**Acceptance Criteria:**
- [ ] Runs gnomon check with base revision.
- [ ] Traces criteria to test reports.
- [ ] Verifies 'test must fail first' condition.
- [ ] Checks Gnomon verify outcome.
- [ ] Checks holdout results.
- [ ] Assigns verdicts: passed, failed, regressed, not applicable, not measured, violation, escalate.


## Phase: Integration: Phase Machine, Gates & Workspace

### T-009 — Implement Phase Machine & Evidence-Based Transitions
**Complexity:** medium
**Depends on:** T-001, T-008

Implement the phase machine with 9 phases (intake to observe). Define evidence-based transitions. Handle 'insufficient evidence' outcome returning work to explore.

**Acceptance Criteria:**
- [ ] Phase machine supports 9 phases.
- [ ] Transitions fire on evidence, not agent count.
- [ ] 'Insufficient evidence' returns work to explore.
- [ ] Phase transitions are recorded in the ledger.

### T-010 — Implement Two-Signal Gate & Verifier Logic
**Complexity:** complex
**Depends on:** T-008, T-009

Implement the two-signal gate (warranted evidence + permitted policy/approval). Implement verifier build pinning, shadow gate rules, and objection preservation.

**Acceptance Criteria:**
- [ ] Gate requires two independent signals bound to revision hash.
- [ ] Verifier runs from a separately pinned build.
- [ ] Shadow gate rules run in shadow until calibrated.
- [ ] Objections are preserved with provenance.
- [ ] Seeded defects are checked in gates.
- [ ] Gate decision posture is recorded.

### T-011 — Implement Typed Workspace & Invariant Breach Detection
**Complexity:** medium
**Depends on:** T-001

Implement the typed workspace for hand-offs between cells. Define artifact types. Detect invariant breaches (edges bypassing workspace).

**Acceptance Criteria:**
- [ ] Workspace holds typed artifacts (finding, failure, patch, etc.).
- [ ] Artifacts are pinned to revisions.
- [ ] Invariant breaches (bypassing workspace) are detected and shown.
- [ ] Ledger of paths is maintained.

### T-012 — Implement Cynefin Classification & Routing
**Complexity:** medium
**Depends on:** T-003

Implement Cynefin domain classification (proposed by classifier, confirmed by person). Implement shadow classifier calibration and routing hypothesis management.

**Acceptance Criteria:**
- [ ] Classifier proposes Cynefin domain.
- [ ] Person confirms domain.
- [ ] Shadow classifier runs without deciding gates.
- [ ] Routing hypothesis is pre-registered.
- [ ] Holdout scenarios are kept out of reach of building agents.


## Phase: Polish: Cockpit, API, Reflexes & Release

### T-013 — Implement Cockpit Visualization & Visual Grammar
**Complexity:** complex
**Depends on:** T-001, T-009, T-010

Build the Cockpit UI with React and D3.js. Implement the visual grammar (shapes, colors, icons, line styles). Implement the nine views (Inbox, Floor, Colony, Cell, Evidence, Thread, Pulse, Immune, Reef).

**Acceptance Criteria:**
- [ ] Cockpit displays nine distinct views.
- [ ] Visual grammar is consistent: agent (circle), code (diamond), person (hexagon).
- [ ] Fill shows assurance: declared, evidenced, verified.
- [ ] Icons show state: passed, running, insufficient, blocked, not measured.
- [ ] Line style shows channel: artifact or control.
- [ ] Numbers show provenance and method.
- [ ] Views update within 5 seconds of ledger event.
- [ ] Works in light/dark themes and at phone width.
- [ ] State is never shown by color alone.

### T-014 — Implement Factory API, CLI & MCP Server
**Complexity:** medium
**Depends on:** T-001, T-013

Implement the Factory API with read models and SSE stream. Implement the Command-Line Tool for operators. Implement the MCP Server for agent state reading and proposal filing.

**Acceptance Criteria:**
- [ ] API provides read models and SSE stream.
- [ ] Only write path is signed decision via Inbox.
- [ ] CLI tool allows operator actions.
- [ ] MCP server allows reading state and filing proposals.
- [ ] MCP server does not allow approvals.
- [ ] Events use documented schema exportable to OpenTelemetry.

### T-015 — Implement Reflexes & Self-Healing
**Complexity:** medium
**Depends on:** T-007, T-009

Implement reflexes (retry, fallback, recall, release leases, abort canary, revert). Implement safe stop state. Implement weekly fire drills.

**Acceptance Criteria:**
- [ ] Reflexes work without models.
- [ ] Reflexes include: retry, fallback, recall, release leases, abort canary, revert.
- [ ] Safe stop state is first-class and shown in cockpit.
- [ ] Fire drills inject faults and score factory.
- [ ] Apparatus failures trigger reflexes.

### T-016 — Implement Release, Canary & Reconciler
**Complexity:** complex
**Depends on:** T-010, T-015

Implement release mechanisms: CI build verification, signed provenance, staging holdouts, canary releases with anytime-valid confidence sequences, production reconciler, and kernel-absent replay.

**Acceptance Criteria:**
- [ ] CI builds only the revision the gate passed.
- [ ] Releases carry signed provenance.
- [ ] Staging runs holdout scenarios and real integrations.
- [ ] Canary releases use anytime-valid confidence sequences.
- [ ] Canary aborts on health check failure.
- [ ] Production reconciler keeps approved state.
- [ ] Rolling back code does not roll back data.
- [ ] Releases can be rebuilt with kernel absent.
- [ ] Release notes and postmortems are checked for honesty.

### T-017 — Implement Feedback Loop & Signal Triage
**Complexity:** medium
**Depends on:** T-016, T-015

Implement end-user feedback loop, production signal intake, signal triage, and four healing loops. Implement impact estimation.

**Acceptance Criteria:**
- [ ] End-user feedback re-enters factory.
- [ ] Production signals are typed artifacts.
- [ ] Signals are triaged (defect, change, requirement, noise).
- [ ] Four healing loops are implemented with separate authority.
- [ ] Impact estimation uses staggered comparisons.
- [ ] Incidents close with sweep, regression test, and eval case.
- [ ] Factory learning proposals are versioned and judged by paired trials.
- [ ] Autonomy levels are enforced.

### T-018 — Implement Cost, Capacity & Non-Functional Checks
**Complexity:** complex
**Depends on:** T-007, T-014

Implement model pricing, capacity following progress, exploration floor, overlapping write scope cap, stalled cell recall, write leases, approval inbox WIP limit, cloud escalation, reliability beliefs, and language support.

**Acceptance Criteria:**
- [ ] Every token is priced from price table.
- [ ] Local and cloud spend shown separately.
- [ ] Daily cloud spend cap is €20.
- [ ] Capacity follows verified progress per euro.
- [ ] Exploration floor keeps 10% budget and one scout.
- [ ] Overlapping write scopes cap at one cell.
- [ ] Stalled cells are recalled.
- [ ] Write leases give one writer per path.
- [ ] Approval inbox has WIP limit.
- [ ] Cloud escalation charges to lane.
- [ ] Reliability beliefs are tracked.
- [ ] Finnish and English inputs are first class.
- [ ] Cockpit updates within 5 seconds.
- [ ] Kernel overhead is small.
