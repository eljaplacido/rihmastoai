---
id: D-0008
decided_by: operator session, under the owner's delegation ("finish it end to end")
decided_on: 2026-11-22
kind: delivery approach
---

# v1 of the factory is built by the operator under the factory's own gates; products go through the factory

**Context.** The owner asked for the whole chain, end to end. That means intake (Socratic or
assumed, with a perspectives panel), spec at a chosen maturity, contract, Gnomon cells,
gates, a paved-road deploy up to production, operation with shadow and canary releases, and
changes from any persona looping back. It also means a cockpit for every persona.

M0 alone, built cell by cell on the local lane, took one to three repair rounds per task.
At that rate v1 would take weeks.

**Decision.**
- **The factory's own v1 code** (kernel, cockpit, delivery) is written by the operator
  session, as the bootstrap tier (T-001 to T-003, T-010) already was. It is held to the same
  rules:
  - every behaviour has a criterion in the contract and a test named by that criterion;
  - the repository's checks stay green;
  - an independent verifier reviews each module.
- **In-flight cells continue.** These are T-006 round 3 and T-011.
- **Products go through the factory.** Spec, contract, Gnomon cells in lanes, gates,
  deployment and operation: this is where the factory is proven. That includes the test
  inputs: a vague idea, an existing spec, and an existing demo product.

**Why it is acceptable.** The invariant "every dispatch goes through Gnomon" governs the
factory's dispatches, that is, the products. Building the builder by hand is the bootstrap
problem every compiler has. The gates, not the author, decide whether code is accepted.
