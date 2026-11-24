---
id: D-0018
decided_by: owner
decided_on: 2026-11-23
kind: principle
---

# Resilience and antifragility are tested, not claimed

The owner (2026-11-23): the factory must be "dogfed with unexpected situations and test reactions", and
"unexpected should test resilience and antifragility of the system".

**Resilience** is measured per injected fault, on four counts:
- **detected:** the fault is noticed, and how long that took is recorded;
- **contained:** no record is corrupted, nothing reads "passed" that was not, and the ledger chain
  still verifies;
- **honest:** the outcome is named (an apparatus failure, not measured, refused), never a quiet success;
- **recovered:** the run resumes from where it stopped, without repeating or losing work, or a person
  is asked with the evidence attached.

**Antifragility** is measured by a second exposure. After a fault is resolved it leaves something behind:
a lesson, a regression check, a sweep for its whole class, and an eval case where a model was involved.
The same class of fault, injected again, must then be caught earlier, more cheaply or without a person.
A lesson learned in one project, once a person accepts it as a default check, must protect the next
project. An incident does not close until that is true (the "immune memory" of the first design).

**The fault catalogue covers every layer:**
- **Models:** garbage, refusals, invented tool calls, timeouts, rate limits, and instructions planted
  in inputs or in an adopted repository.
- **The harness:** a Gnomon crash, a drifted or untrusted surface.
- **The kernel:** a kill mid-stage, a full disk, a partial write, a corrupted ledger line, clock skew,
  a lock left by a dead process.
- **The environment:** Docker down, a taken port, a network partition.
- **Integrations:** webhooks replayed or out of order, a connector whose tools change, an
  identity-provider outage, key rotation.
- **People:** a decision that never comes, conflicting decisions, a delegation that expires mid-run.
- **Data:** a huge, malformed or multilingual input.

Each fault has a scripted injection, an expected reaction and the measurements above, offline in CI
where it can be and live on the GPU box with real models where it cannot.
