---
id: D-0024
decided_by: owner
decided_on: 2026-11-24
kind: principle
amends: D-0017, D-0018, D-0023
---

# Self-healing by default, visible context, simple for one person and governed for many

The owner (2026-11-24): "remember we wanted to base this project on anti-fragility and resilience. How can
you have an anti-fragile system if every failure brings up an obstacle? Whether it's feeding in a new
project, an unexplained situation or an error, the system should be able to fix itself and learn from its
mistakes and from the feedback." Also: "I'm wondering how the data and context layer is working: there
is not much visibility." And: "we shouldn't overcomplicate things: there are many tabs. Capsule these
features. A single developer shouldn't spend time configuring each persona (they could even be
agent-based personas), but in an enterprise a persona is an authenticated user, from the platform's own
user management or Entra ID groups or another service." And: "the terms are not AI slop: they make sense
for each persona, and adapt to the user's feedback."

**What this means:**

1. **A failure is handled, then learned from.** Every error, refusal, failed job, empty view or unexplained
   situation becomes an incident with a fingerprint, its context attached (view, request, logs, record
   entries).
   - Known classes are handled by their learned remedy: retry, a different route, a fix already
     approved.
   - Unknown ones go to a Rihma agent, which investigates with a trace and proposes a fix. The fix is
     verified through the gate and, once a person approves it, sent as a pull request (to the project's
     repository, or to Rihmasto's own).
   - Each resolved incident teaches: its fingerprint and remedy become immune memory, so the same failure
     is handled next time.
   - Feedback a person gives ("this is unclear", "this was wrong") is recorded and changes prompts,
     wording and rules by the same reviewed path.
   - Nothing is fixed silently: every remedy is recorded. A remedy that changes code or policy is a
     proposal a person accepts.
2. **The data and context layer is visible.** A person can see what Rihmasto knows about a project:
   - its sources, records, ledger, graph and freshness;
   - what each Rihma agent is given in its context, and how large it is;
   - what was compressed, and what was left out and why.
3. **Capsules, not tabs.** A project's views are grouped into a few capsules by purpose, filterable and
   customisable, with defaults by persona.
4. **Simple for one, governed for many.**
   - A single person works in **solo mode**: one person acts in every persona they need, with no persona
     set-up and no switching friction. Personas may also be **agents**, acting by explicit delegation.
   - An organisation turns on **team mode**: personas become authenticated users and groups (the
     platform's own user management, or Entra ID, AWS, Google or any OIDC provider), with filters and
     access per role.
   - Moving from solo to team keeps every record.
5. **Words that fit the reader.** Every view's wording is reviewed per persona: plain business language for
   a business owner, precise technical terms for a developer. Wording a person flags as unclear is
   rewritten, and the change is recorded.
6. **Every transition is helped.** A Rihma agent can take a person through each move between stages:
   - idea to concept to demo, and demo to test to production;
   - production to maintenance;
   - hooking up an IDE, a system or an integration.

   It works by walkthrough, by plan, or by doing it once the person confirms.
