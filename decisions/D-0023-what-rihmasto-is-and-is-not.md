---
id: D-0023
decided_by: owner
decided_on: 2026-11-24
kind: scope
amends: D-0017, D-0019, D-0021
---

# What Rihmasto is, and what it is not: the platform around the IDE, not another IDE

The owner (2026-11-24): "we would have to think about the anti-patterns of what this wouldn't be. We
wouldn't want to compete with the developer tooling, so that goes to the IDE side. But we want to make
anything visible there possible, starting from turning the idea into a concept or first mock-up, and then
productionizing that, taking it to deployment, figuring out integration, figuring out where the first test
deployment will be, and hooking it to production ... like the name indicates, it's about creating agentic
capabilities. Rihmasto is the platform: take ideas in, package them, take them to testing, to deployment,
keep the human in the loop, help with the maintenance, and hook up the automations related to these steps
and their transitions."

**What Rihmasto is: the platform for an agentic capability's whole life.**

1. **Idea to concept.** A need in any form (a sentence, a chat, a folder of material, a written spec, an
   existing repository) becomes a concept with its questions, assumptions and decisions in plain view.
2. **Concept to first mock-up.** A prototype posture and demo maturity give something to look at and try
   early, without the gates of production.
3. **Productionising.** The spec, the hashed contract, the independent gate, the posture's floors.
4. **Integration.** Data systems, identity, APIs and MCP faces, through connectors and Gnomon.
5. **First test deployment, then production.** Paved roads chosen by IT, a test environment first, the
   deploy gate, then production with probes, canary and rollback.
6. **Maintenance and evolution.** Checks, monitoring hooks, the change loop and stage 8 (D-0021).
7. **People in the loop at every step.** Decisions are signed by the person whose decision it is. Models
   propose; the kernel decides by rule; delegation is explicit and expires.
8. **Automations on the steps and their transitions.** For example: when a concept is validated, when a
   release reaches test, when it is promoted to production, or when a check fails. Scheduled or
   event-driven, owned and recorded, never deciding a card.

**What Rihmasto is not (the anti-patterns):**

- **Not an IDE or a code editor.** People write code in the IDE and agent they prefer (Cursor, Claude
  Code, VS Code, Antigravity, a terminal). Rihmasto captures what that work produced (specs, tests,
  conventions, AI-tool setup), aligns it with its contract by proposals a person accepts, and hands
  context back to the IDE (the MCP server, a pasteable conventions section). Its console runs commands
  and checks; it does not grow into an editor.
- **Not a replacement for the team's CI, monitoring or ticketing.** It reads CI status, runs its own
  gate and checks, and hooks into the customer's observability and notification tools (D-0017). It is
  the system of record for decisions and evidence, not for telemetry or tickets.
- **Not tied to one agent harness or one model.** Gnomon is the default and the governance glue. Other
  harnesses run cells opt-in, with the rules checked after the run and the evidence saying which
  assurance applied (D-0019). Any OpenAI-compatible endpoint, local or hosted, per role.
- **Not an autopilot without people.** Autonomy is capped, delegated, sandboxed and recorded. No
  automation decides a card.
- **Not a framework for writing agents in code.** It produces and governs agentic capabilities: services,
  agents, workflows, automations and MCP or API faces, built and verified by its cells. Teams who write
  agent code by hand do so in their IDE and bring it in through adoption.
- **Not a place where a step can skip the record.** A light posture asks less and gates less. It never
  drops provenance (D-0017).

**How to apply:**
- A feature that helps a person write or edit code belongs to the IDE side. Rihmasto offers context to
  the IDE instead.
- A feature that moves a capability between the life stages above, or keeps it governed afterwards,
  belongs in Rihmasto. Every transition is visible, recorded, and can trigger an automation.
