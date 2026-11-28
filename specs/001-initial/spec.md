# Gnomon Factory — Functional Specification

**Cynefin Classification:** Complex (85% confidence)
**Version:** 1.0

## Executive Summary

Gnomon Factory is an antifragile solution factory designed to transform approved requirements into verified production software while growing stronger from every failure it understands. It operates as an independent system with Gnomon (version 0.6.5) as its sole runtime dependency, ensuring no code or runtime dependency on earlier factory projects. The system takes approved requirements in, develops solutions through testing and production, and loops back when end-user feedback arrives. It is built on a constitution of deterministic governance, evidence over claims, and artifact-based coordination, where models decide how work is done but deterministic code decides whether a result takes effect.

## Functional Requirements

### FR-A1. Closed Intake Contract
**Priority:** High

The factory accepts a closed intake contract defined as a manifest of files with hashes, roles, and exact record counts, plus a structured representation of requirements, glossary, roles, process, screens, decisions, and open questions. If a package's declared count differs from what is found, intake rejects it with the file, line, expected and got values, and writes nothing downstream.

### FR-A2. Vague Explanation to Contract
**Priority:** High

The factory accepts a vague explanation of what should be built and turns it into the same contract through classification and guided questions. Answers are signed, so each resulting requirement records who confirmed it. A brief too ambiguous to classify is refused with reasons.

### FR-A3. Requirement Provenance
**Priority:** Medium

Every requirement records its provenance tier: customer-confirmed, customer-endorsed, vendor-proposed, assumption or withdrawn. It also records who decided it and when.

### FR-A4. Change Request Amendment
**Priority:** Medium

A change request becomes a contract amendment. The factory computes exactly which tasks it reopens. An amendment touching 14 requirements reports the tasks that trace to them and reopens only those.

### FR-A5. Incomplete Intake Send-Back
**Priority:** Medium

When intake is incomplete, it produces a send-back list for the sender and tracks acknowledgement by content hash.

### FR-B1. Cynefin Domain Classification
**Priority:** High

Each work item gets a Cynefin domain, proposed by a classifier and confirmed by a person. Clear: one cell, standard gate. Complicated: scouts, one builder, an independent verifier. Complex: safe-to-fail probes behind flags, small canaries. Chaotic: reflexes first. Disorder: refuse.

### FR-B2. Shadow Classifier
**Priority:** Medium

The classifier runs in shadow until calibrated on the factory's own labelled work items. Its output never decides a gate.

### FR-B3. Routing Hypothesis
**Priority:** Low

Routing by domain is itself a pre-registered hypothesis. If routing does not change outcomes, the router is removed.

### FR-B4. Holdout Scenarios
**Priority:** High

Holdout acceptance scenarios are written outside the build and kept out of reach of building agents.

### FR-C1. Work Envelope Structure
**Priority:** High

Each unit of work is an envelope with these fields: goal, contract revision, base revision, requirement references, read and write scope, role, budget (tokens, wall time, steps), stop condition, required evidence and parent. Nested envelopes inherit limits and can never widen them.

### FR-C2. Gnomon Task Execution
**Priority:** High

An envelope runs as a Gnomon task in an isolated worktree, using the role's hashed surface. The factory records Gnomon's structured task record, audit chain head, surface hash and build identity.

### FR-C3. Six Gnomon Roles
**Priority:** High

Six roles, each a Gnomon surface: scout (read, map, reproduce); builder (writes inside a lease, tests that fail first); verifier (read-only, different model, holdouts); assembler (walks seams end to end); repairer (known failure classes, with a sweep); triager (clusters signals, drafts amendments).

### FR-C4. Live Progress Streaming
**Priority:** High

Live progress and permission requests stream from Gnomon's ACP interface to the factory, so approvals can be answered from the cockpit.

### FR-C5. Gnomon Exit Mapping
**Priority:** High

Gnomon exit buckets (result, refusal, apparatus failure), the verify outcome and the stop reason map to factory verdicts. The native values are stored beside the translation.

### FR-C6. Apparatus Failure Handling
**Priority:** Medium

Apparatus failures go to reflexes and are excluded from every success rate.

### FR-D1. Typed Workspace Artifacts
**Priority:** High

A typed workspace holds every hand-off between cells. Each artifact is pinned to a revision and supersedes or links other artifacts. Artifact types: finding, failure record, patch, open question, objection, decision, seam contract, signal and lesson.

### FR-D2. Ledger of Paths
**Priority:** Medium

A ledger of paths tried keeps history out of each cell's context.

### FR-D3. Invariant Breach Detection
**Priority:** High

Any edge between two cells that bypasses the workspace is an invariant breach. It is detected and shown.

### FR-E1. Phase Machine
**Priority:** High

Each contract moves through these phases: 1. intake, 2. shape, 3. explore, 4. build, 5. challenge, 6. assemble, 7. gate, 8. release, 9. observe.

### FR-E2. Evidence-Based Transitions
**Priority:** High

Phase transitions fire on distinct kinds of evidence, never on a count of agreeing agents.

### FR-E3. Insufficient Evidence Outcome
**Priority:** Medium

"Insufficient evidence" is a valid outcome. It returns work to explore.

### FR-E4. Assemble Seam Ownership
**Priority:** High

Assemble owns every seam. Its exit is a path walked in a real browser and against real contracts.

### FR-F1. Capacity Following Progress
**Priority:** Medium

Capacity per lane (contract × phase × work class) follows verified progress per euro over a sliding window. It grows additively and shrinks multiplicatively.

### FR-F2. Exploration Floor
**Priority:** Medium

Every active lane keeps one scout and about 10% of its budget as an exploration floor.

### FR-F3. Overlapping Write Scope Cap
**Priority:** Medium

A lane with heavily overlapping write scopes is capped at one cell.

### FR-F4. Stalled Cell Recall
**Priority:** Medium

A cell with no verified progress inside its calibrated stall window is recalled and its budget returned. Elapsed time alone never kills a run.

### FR-F5. Write Leases and Quotas
**Priority:** Medium

Write leases give one writer per path scope. Quotas per model endpoint come from live GPU memory pressure and serving slots. Jobs outside the factory that use the same hardware must take leases too.

### FR-F6. Approval Inbox WIP Limit
**Priority:** Medium

The approval inbox has a work-in-progress limit. When its p90 age passes the target, lanes that generate approvals slow down.

### FR-F7. Cloud Escalation and Charging
**Priority:** Medium

A prompt that cannot fit the local model window goes to the cloud tier before it starts. Otherwise escalation happens only on stall, failed verification or deadline share. Each escalation is charged to its lane.

### FR-F8. Reliability Beliefs
**Priority:** Medium

Each role, model and work class carries a reliability belief. Below a minimum number of trials, it reads as "not measured".

### FR-G1. Two-Signal Gate
**Priority:** High

A change advances only with two independent signals bound to its exact revision hash: warranted (evidence) and permitted (a policy rule or a human approval).

### FR-G2. Acceptance Criterion Verification
**Priority:** High

An acceptance criterion counts as met only when: an executing test names it; the factory saw the test run; the test failed on the revision before the change.

### FR-G3. Named Verdicts with Precedence
**Priority:** High

Named verdicts with precedence: passed, failed, regressed, not applicable, not measured, violation, escalate. A failure outranks not measured. All-not-applicable means not measured. Nothing maps to passed by configuration.

### FR-G4. Seeded Defects in Gates
**Priority:** High

Every gate carries seeded defects it must catch on each run, and lists its known blind spots.

### FR-G5. Gate Decision Posture
**Priority:** Medium

Each gate decision records its posture: blocked before execution, or only recorded after.

### FR-G6. Verifier Build Pinning
**Priority:** High

The verifier runs from a build pinned separately from the build it judges.

### FR-G7. Shadow Gate Rules
**Priority:** Medium

New gate rules run in shadow. A rule moves to enforce only after replay over labelled past traffic shows a reviewed false-positive rate under a set limit.

### FR-G8. Objection Preservation
**Priority:** Medium

Objections are preserved with provenance. A blocked change records why it was blocked.

### FR-G9. Release Notes and Postmortem Checks
**Priority:** Medium

Agent-written release notes and postmortems are checked. A number that was not measured, or causal wording without a supported result, fails.

### FR-H1. CI Build Verification
**Priority:** High

CI builds only the revision the gate passed, and re-runs the evidence.

### FR-H2. Signed Provenance
**Priority:** High

Each release carries signed provenance linking requirement, evidence, policy and approval.

### FR-H3. Staging Holdouts
**Priority:** High

Staging runs holdout scenarios and real integrations. "Validated" is claimed only when every integration marked real-required was exercised.

### FR-H4. Canary Releases
**Priority:** High

Canary releases are judged with an anytime-valid confidence sequence against a declared harm margin, and abort automatically on declared health checks.

### FR-H5. Production Reconciler
**Priority:** High

Production is kept in its approved state by a reconciler. Rolling back code never implies rolling back data.

### FR-H6. Kernel-Absent Replay
**Priority:** High

Every release can be rebuilt and rechecked from the ledger, artifacts and pinned revisions with the factory's kernel absent.

### FR-I1. End-User Feedback Loop
**Priority:** High

End-user feedback re-enters the factory.

### FR-I2. Production Signal Intake
**Priority:** High

Production telemetry, errors, service-level breaches and user reports enter as typed signal artifacts linked to the release that caused them. A signal is an input to weigh, never an instruction.

### FR-I3. Signal Triage
**Priority:** High

Triage clusters and reproduces signals and classifies each as one of: defect, change request, new requirement or noise.

### FR-I4. Four Healing Loops
**Priority:** High

Four loops with separate authority: operational healing (reflexes; must work with every model offline); engineering repair (gate, plus a person outside pre-approved classes); product adaptation (the product owner decides); factory learning (paired evaluation, then human promotion).

### FR-I5. Impact Estimation
**Priority:** Medium

The impact of a release on a user metric is estimated with staggered comparisons where the rollout allows it. A single incident's cause stays a hypothesis, never a verified fact.

### FR-J1. Self-Healing
**Priority:** High

The factory heals itself under change, error or disruption where it safely can.

### FR-J2. Reflexes
**Priority:** High

Reflexes need no model. They include: retry with backoff; switch to a fallback endpoint; recall stalled cells; release dead leases; abort the canary; revert to the last green release.

### FR-J3. Safe Stop State
**Priority:** Medium

Safe stop is a first-class state, shown in the cockpit with its reason.

### FR-J4. Weekly Fire Drills
**Priority:** Medium

Weekly fire drills inject faults and score the factory on held-out disruption scenarios. Faults include: endpoint down, flaky test, conflicting writes, malformed contract.

### FR-K1. Antifragility
**Priority:** High

The factory becomes stronger from failures (antifragile).

### FR-K2. Incident Closure Requirements
**Priority:** High

An incident closes only when it has left a sweep for its class, a regression test and an eval case.

### FR-K3. Factory Learning Proposals
**Priority:** Medium

Changes to skills, roles, topologies and models are proposed by the factory as versioned artifacts. They are pre-registered with what they would demote. They are judged by paired trials with an effect size and interval. They are decided on a ladder: act, act with approval, experiment with a sized trial, or refuse.

### FR-K4. Autonomy Levels
**Priority:** High

Autonomy levels per class of change: 0: observe; 1: propose, with a person approving each release; 2: act within pre-approved reversible classes; 3: self-tune skills and topologies, with promotion by a person. Irreversible actions and changes to gates, policy or permissions are never automatic.

### FR-L1. Hash-Chained Ledger
**Priority:** High

One insert-only, hash-chained ledger records: runs, artifacts and envelopes; gate decisions and approvals; signals, prices and phase transitions. Every view in the cockpit is a projection of it.

### FR-L2. Kernel State Writes
**Priority:** High

Only the kernel writes state, and only by appending a transition.

### FR-L3. Ledger Anchoring
**Priority:** Medium

Ledger heads can be signed and anchored externally.

### FR-L4. Model Pricing
**Priority:** Medium

The kernel prices every model call from a price table kept in the policy repository.

### FR-M1. Cockpit Visualization
**Priority:** High

Visualise how the factory and the agents inside it work, plus monitoring and observation views.

### FR-M2. Visual Grammar
**Priority:** High

One visual grammar across all views: shape and colour show who decides: agent (circle), deterministic code (diamond), person (hexagon); fill shows assurance: declared, evidenced, verified; an icon shows state: passed, running, insufficient, blocked, not measured; the line style shows the channel: artifact or control.

### FR-M3. Nine Cockpit Views
**Priority:** High

Nine views, each answering one question: Inbox (who must decide what now); Floor (where work piles up); Colony (who works on this contract through which artifacts); Cell (what one run did and what can be proved); Evidence (may this revision advance); Thread (why this code is in production); Pulse (is the factory healthy and getting cheaper); Immune (is it learning); Reef (are factories competing for compute, quota or files).

### FR-M4. Number Provenance
**Priority:** High

Every number opens its method and the ledger records it was counted from. Numbers carry provenance: observed, derived or proxy.

### FR-M5. View Replay
**Priority:** Medium

Any view can be replayed to a past moment.

### FR-M6. Inbox Write Path
**Priority:** High

The Inbox is the only write path. Every decision is signed with a name and appended to the ledger.

### FR-M7. Alerts
**Priority:** High

Alerts include: a stalled cell; the approval queue over its target; budget burn over forecast; gate flapping; an invariant breach; quota contention; a canary abort; the recurrence of a closed failure class.

### FR-N1. Factory API
**Priority:** High

A factory API with read models and a server-sent event stream. Its only write path is a signed decision.

### FR-N2. Command-Line Tool
**Priority:** High

A factory command-line tool for operators.

### FR-N3. MCP Server
**Priority:** High

An MCP server where other agents can read state and file proposals, never approvals.

### FR-N4. Event Schema
**Priority:** Medium

Events use one documented schema that can be exported to OpenTelemetry.

### FR-O1. Spec Compilation
**Priority:** High

A requirements spec is compiled into a machine-readable, content-hashed contract. The contract holds requirements with provenance, acceptance criteria (given/when/then), the check that proves each criterion, banned terms with their scope, and non-functional probes. A customer-confirmed criterion with no check, and no signed verification plan entry, fails compilation with file, line, expected and got.

### FR-O2. Compiler Constraints
**Priority:** High

The compiler has no model inside. It recomputes counts and rejects unknown keys. Every criterion traces to a task, and every task to a criterion.

### FR-O3. Check Custodies
**Priority:** High

Checks come in two custodies: visible tests in the product repository, which name their criterion id; holdout scenarios stored outside it, given only to the verifier role and staging.

### FR-O4. Gnomon Surface Compilation
**Priority:** High

From the contract, check plan and envelope, the kernel compiles each cell's Gnomon surface (.gnomon/policy.toml, .gnomon/roles.toml): write scope from the envelope; the contract, specs and CI write-protected through [governance.paths]; [verify] with a contract preset, test_must_fail_first, protects, exit_on_fail, record_detail and the finish gate.

### FR-O5. Post-Run Check
**Priority:** High

After each run, gnomon check --base <rev> judges the change by the base revision's rules. The kernel then traces each criterion through test reports at the head and base revisions.

### FR-O6. Criterion Verification Conditions
**Priority:** High

A criterion is verified only when all of these hold: a test naming it passed at head and failed at base; Gnomon's verify is passed, not passed_unverified; gnomon check exits 0; any holdout passed; any declared input pair produced different results. Otherwise the criterion reads as evidenced, declared, not measured or failed.

### FR-O7. Contract Amendment Process
**Priority:** High

The contract changes only through an amendment signed in the Inbox. The kernel then recompiles surfaces and reopens exactly the tasks whose criteria changed.

### FR-O8. Self-Application
**Priority:** High

The chain applies to Gnomon Factory itself. Its own specs are compiled into its own contract and .gnomon/ surface, and its development runs under them from the first milestone.


## Non-Functional Requirements

- **NFR-1 Determinism** (Reliability): The kernel contains no model. An import-graph check enforces this. Given the same ledger, the same phase transitions result.
- **NFR-2 Reproducibility** (Reliability): Runs are pinned by revision, Gnomon surface hash and Gnomon build identity. Pins must be reachable on the remote. Custody is checked before hashing.
- **NFR-3 Security** (Security): Agents hold no production credentials. Cells run sandboxed with no network unless their role allows it. The policy repository accepts human writes only. Secrets never enter prompts or logs.
- **NFR-4 Privacy** (Privacy): Event metadata is captured without prompt content by default. Customer documents go to cloud models only where policy allows.
- **NFR-5 Availability** (Availability): Reflexes and the ledger keep working with every model offline.
- **NFR-6 Cost** (Cost): Every token is priced, with local and cloud spend shown separately. Daily cloud spend has a cap, proposed at €20.
- **NFR-7 Performance** (Performance): Cockpit views update within 5 seconds of a ledger event. Kernel overhead per dispatch stays small next to model time.
- **NFR-8 Portability** (Portability): Gnomon's operating-system sandbox refuses shell commands on Windows. Cells therefore run on Linux: a GPU box, WSL2 or containers.
- **NFR-9 Accessibility** (Accessibility): The cockpit works in light and dark themes, at phone width, and never shows state by colour alone.
- **NFR-10 Language** (Localization): Finnish and English inputs are first class. The cockpit's language is an open question.
- **NFR-11 Honesty** (Integrity): Published counts are regenerated by their producer. The cockpit never averages an unmeasured dimension into a score.

## User Stories

### Operator Factory Management
As a **Operator / product owner**, I want **to run the factory, own intent, policy, budgets and approvals**, so that **I can control the solution factory's direction and resources**.

**Acceptance Criteria:**
- [ ] The operator has access to the cockpit to view all factory states.
- [ ] The operator can approve or reject decisions via the Inbox.
- [ ] The operator can set budgets and policies in the policy repository.

### Requirement Confirmation
As a **Requirement owner (customer)**, I want **to confirm requirements and supply or approve holdout scenarios**, so that **the factory builds the correct solution verified by independent tests**.

**Acceptance Criteria:**
- [ ] The requirement owner can sign requirements during intake.
- [ ] The requirement owner can provide holdout scenarios stored outside the build.
- [ ] The factory refuses vague briefs with reasons.

### Release Signing
As a **Approver**, I want **to sign releases and decisions**, so that **only verified and warranted changes reach production**.

**Acceptance Criteria:**
- [ ] The approver receives signed decisions in the Inbox.
- [ ] The approver can sign decisions which are appended to the ledger.
- [ ] Irreversible actions require human approval.

### Audit Access
As a **Auditor**, I want **to read evidence packs and the ledger**, so that **I can verify the factory's compliance and integrity**.

**Acceptance Criteria:**
- [ ] The auditor has read-only access to the ledger.
- [ ] The auditor can view evidence packs linked to releases.
- [ ] The ledger is insert-only and hash-chained.

### Agent State Reading
As a **Other agents and tools**, I want **to read factory state and file proposals through an MCP server**, so that **I can interact with the factory without approving anything**.

**Acceptance Criteria:**
- [ ] The MCP server allows reading factory state.
- [ ] The MCP server allows filing proposals.
- [ ] The MCP server does not allow approvals.

### Closed Intake
As a **Factory System**, I want **to accept a closed intake contract with file hashes, roles, and record counts**, so that **I can ensure the integrity of the input requirements**.

**Acceptance Criteria:**
- [ ] The factory rejects packages with mismatched counts, showing file, line, expected and got.
- [ ] The factory writes nothing downstream on rejection.

### Vague Explanation Processing
As a **Factory System**, I want **to turn vague explanations into structured contracts through classification and guided questions**, so that **I can accept informal requirements and formalize them**.

**Acceptance Criteria:**
- [ ] The factory classifies vague briefs.
- [ ] The factory asks guided questions to clarify.
- [ ] The factory refuses briefs too ambiguous to classify with reasons.

### Cockpit Visualization
As a **Operator / product owner**, I want **to visualize how the factory and the agents inside it work, plus monitoring and observation views**, so that **I can see the factory's health and progress**.

**Acceptance Criteria:**
- [ ] The cockpit displays nine views: Inbox, Floor, Colony, Cell, Evidence, Thread, Pulse, Immune, Reef.
- [ ] The cockpit uses a consistent visual grammar for shapes, colors, and icons.
- [ ] Every number in the cockpit opens its method and shows provenance.

### Gnomon Integration
As a **Factory System**, I want **to integrate with Gnomon via gnomon task, gnomon acp, gnomon check, gnomon eval, gnomon skill trial, gnomon chaos, and gnomon guard**, so that **I can leverage Gnomon's agent harness and safety features**.

**Acceptance Criteria:**
- [ ] The factory uses gnomon task to run envelopes.
- [ ] The factory streams live progress via gnomon acp.
- [ ] The factory uses gnomon check for post-run verification.
- [ ] The factory uses gnomon eval and gnomon skill trial for paired trials.
- [ ] The factory uses gnomon chaos for fault injection.
- [ ] The factory uses gnomon guard for per-action gating.

### Cloud Model Escalation
As a **Factory System**, I want **to integrate with cloud models as an escalation tier, with DeepSeek-v4-pro as the default partner**, so that **I can handle capacity or evidence needs beyond local models**.

**Acceptance Criteria:**
- [ ] The factory escalates prompts that cannot fit the local model window to the cloud tier.
- [ ] The factory charges cloud model usage to the lane that needed them.
- [ ] DeepSeek-v4-pro is used as the default cloud partner.

### Local Model Usage
As a **Factory System**, I want **to integrate with a local Qwen3.6-35B model resident on the GPU box**, so that **I can perform most work locally with low latency and cost**.

**Acceptance Criteria:**
- [ ] The factory uses the local Qwen3.6-35B model for most tasks.
- [ ] The local model window is 65,536 tokens.

## Technical Constraints

- The system must have no runtime or code dependency on earlier projects, maintaining independence.
- The only runtime dependency is Gnomon (the agent harness) at its latest release (0.6.5).
- Gnomon gaps must be fixed upstream in Gnomon, not worked around in the factory.
- The system must run on Linux (a GPU box, WSL2, or containers) due to OS sandbox constraints.
- The system must be self-hosted on the owner's hardware (a local NVIDIA GPU box, RTX 5090) with no cloud hosting for the factory itself.
- The kernel must contain no model; an import-graph check enforces this to ensure determinism.
- The local model window is 65,536 tokens.
- Four parallel streams on the GPU box give about 157 tokens per second in total, about 42 each.
- Gnomon is TypeScript on Node 22, with Rust crates for the surface manifest, edits and the sandbox.

## Integration Points

- **Gnomon** (Agent Harness): The factory's only runtime dependency. Integrates via gnomon task, gnomon acp, gnomon check, gnomon eval, gnomon skill trial, gnomon chaos, and gnomon guard.
- **MCP Server** (Agent Communication): Allows other agents and tools to read factory state and file proposals, but never approve anything.
- **OpenTelemetry** (Observability): Events use one documented schema that can be exported to OpenTelemetry.
- **Cloud Models** (Compute Escalation): Used as an escalation tier for capacity or evidence. DeepSeek-v4-pro is the proposed default partner.
- **Local Model** (Compute): A resident Qwen3.6-35B model on the GPU box for most work.

## Data Requirements

### Contract
Revision and hash of the requirements contract.
  - Contains Requirements
  - Linked to Envelopes

### Requirement
Provenance tier (customer-confirmed, customer-endorsed, vendor-proposed, assumption, withdrawn), acceptance criteria, and decision history.
  - Part of Contract
  - Linked to Tasks

### Holdout Scenario
Scenarios stored outside the build, given only to the verifier role and staging.
  - Linked to Requirements

### Decision
Who decided, when, and requirements touched.
  - Linked to Contract Amendments

### Envelope
Unit of work with goal, contract revision, base revision, requirement references, read and write scope, role, budget, stop condition, required evidence and parent.
  - Runs as Gnomon Task
  - Contains Tasks

### Run
Task record, audit head, surface hash and build identity.
  - Linked to Envelope

### Evidence Bundle
Inspected, changed, checks, uncertain, cost.
  - Linked to Runs

### Artifact
Typed, revision-pinned. Types: finding, failure record, patch, open question, objection, decision, seam contract, signal and lesson.
  - Part of Workspace

### Gate Decision
Subject hash, warranted refs, permitted refs, verdict, posture, reason, native values.
  - Linked to Envelopes

### Release
Digest and signed provenance linking requirement, evidence, policy and approval.
  - Linked to Gate Decisions

### Signal
Production telemetry, errors, service-level breaches and user reports linked to the release that caused them.
  - Linked to Releases

### Lesson
Learned from incidents, includes sweep for class, regression test and eval case.
  - Linked to Incidents

### Hypothesis
Pre-registered, with demotion, budget and power.
  - Linked to Factory Learning

### Lease
Write leases give one writer per path scope.
  - Linked to Envelopes

### Price Table
Kept in the policy repository, used to price every model call.
  - Linked to Runs

### Policy Version
Human-written policies for the factory.
  - Linked to Decisions

### Ledger
One insert-only, hash-chained ledger recording runs, artifacts and envelopes; gate decisions and approvals; signals, prices and phase transitions.
  - Source for all Cockpit Views
