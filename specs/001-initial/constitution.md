# Gnomon Factory — Constitution

## Vision

To be the best-in-class, antifragile solution factory that transforms approved requirements into verified production software while growing stronger from every failure it understands.

## Mission

To coordinate autonomous agents through deterministic governance and biological metaphors, ensuring every line of code is traceable to evidence, every decision is auditable, and every change is safe.

## Principles

- **Deterministic Governance** — Models decide how work is done; deterministic code decides whether a result takes effect. The kernel contains no model, ensuring that given the same ledger, phase transitions are identical.
- **Evidence Over Claims** — Nothing turns green from a claim. Every mark must be declared, evidenced, or verified. A check that cannot measure must report 'not measured' rather than passing or failing.
- **Artifact-Based Coordination** — Agents never message each other directly. They coordinate only through typed artifacts pinned to a revision. An artifact is an input, never an instruction, preventing silent coordination failures.
- **Human-in-the-Loop Sovereignty** — People own intent, policy, and irreversible decisions. Agents propose changes, but humans approve them. The factory can propose changes to its own gates but cannot apply them.
- **Antifragile Healing** — The factory heals itself under change, error, or disruption via reflexes (no model) and pre-approved repairs. It stops safely and asks a person when it cannot heal, ensuring missing health signals are never read as healthy.
- **Radical Independence** — Gnomon Factory is its own independent system with no runtime dependency on earlier projects. Gnomon is its only runtime dependency, and gaps are fixed upstream, not worked around.

## Quality standards

- **Criterion Verification** — An acceptance criterion is met only when an executing test names it, the factory saw the test run, and the test failed on the revision before the change. _(target: 100% of customer-confirmed criteria must be proved by an executing test that failed first.)_
- **Dispatch Integrity** — Every unit of work must run inside Gnomon. No dispatches are allowed outside the harness to ensure auditability and sandboxing. _(target: 0% of dispatches outside Gnomon.)_
- **Failure Class Elimination** — Every incident must leave a regression test, a sweep for its class, and an eval case before it closes. The factory must not allow a closed failure class to recur. _(target: 0% recurrence of closed failure classes.)_
- **Holdout Fidelity** — Holdout scenarios are written outside the build and kept out of reach of building agents. They must pass on first delivery before 'validated' is claimed. _(target: 100% fidelity on holdouts at first delivery.)_
- **Operator Intervention Reduction** — The factory must minimize human intervention by automating reflexes and pre-approved repairs, reserving human time for policy and intent. _(target: ≤ 3 operator interventions per contract, with none at component seams.)_

## Technology constraints

- The kernel must contain no model; an import-graph check enforces this.
- The system must run on Linux (a GPU box, WSL2, or containers) due to OS sandbox constraints.
- The system must be self-hosted on the owner's hardware with no cloud hosting for the factory itself.
- Gnomon is the only runtime dependency; gaps must be fixed upstream in Gnomon.
- Agents hold no production credentials; cells run sandboxed with no network unless their role allows it.
- The ledger is insert-only and hash-chained; only the kernel writes state by appending a transition.

## Decision guidelines

- When in the Complex domain, use safe-to-fail probes and small canaries; in the Clear domain, use one cell and standard gates. Refuse work in the Disorder domain.
- Autonomy is earned per class of change based on evidence and withdrawn after an escaped defect. Changes to skills, roles, or topologies require paired evaluations and human promotion.
- Local models are used by default; cloud models are an escalation tier used only on capacity or evidence, and are charged to the work that needed them.
- Fan-out, extra roles, or a planning stage must win a paired evaluation for that class of work; the default is one cell to prevent sprawl and cost overruns.
