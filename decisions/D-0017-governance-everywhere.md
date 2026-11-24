---
id: D-0017
decided_by: owner
decided_on: 2026-11-23
kind: principle
---

# Governance everywhere, agility without gaps, monitoring that respects the customer's own tools

The owner (2026-11-23): "everywhere we want to follow the principles of governance, traceability,
auditability ... while providing the agility to just spit out something, a simple feature". On
monitoring: "Rihmasto could have some self-monitoring capabilities of its solution, while knowing that
many of the companies, users, people would want to use their own ways." And: "for everything create
onboardings, tutorial, agentic navigation from chat across the platform, possibility to hook in checks,
validations and steps with human in the loop principles", tested end to end across the backend,
integrations and the front end.

**What this means:**

1. **No path skips the record.** Every way of using Rihmasto (the full factory, a quick feature, spec
   only, gate my code, a small capability, autopilot in a sandbox) writes the same kind of trace: who
   asked, what was decided and by whom (or by whose delegation), what was assumed, what was built, what
   proves it, in the hash-chained ledger. A lighter posture asks fewer questions and runs lighter gates.
   It does not drop provenance. One command exports a project's audit trail in standard formats.
2. **Rihmasto is the system of record for decisions and evidence, not for operational telemetry.** It
   monitors what it needs to keep its own promises: that a release runs as delivered, health and probes
   against the release's criteria, drift from the approved plan, autonomy used, and gate evidence.
   Everything else is exported in open standards, so a company keeps its own tools: OpenTelemetry,
   CloudEvents, an audit stream for a SIEM, SARIF and OSCAL. Their tools' alerts come back in as
   verified signals that become observations or incidents. Per project, monitoring is "Rihmasto",
   "ours" or both.
3. **Checks and steps are pluggable, people stay in the loop.** A team can add its own checks to the
   gate (a command run in isolation, an external CI status, a policy rule), its own validation steps
   and its own human checkpoints at any stage. Each is recorded, deterministic where it decides, and
   shown to the person before it applies.
4. **Every feature is learnable and reachable.** Each feature has onboarding, a tutorial, and a place
   in the assistant's map, so "Ask Rihma" can explain it and take the person there. Each is tested end
   to end in a real browser and through its integrations before it is called built.
