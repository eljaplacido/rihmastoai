# Fix a project that lacks governance

A project grew fast with coding agents. It works, mostly. But nobody wrote down what it must do, tests
are thin or flaky, agents edited whatever they touched, and when something breaks nobody can say which
change, which agent or which decision led there. This guide brings governance, reliability and
traceability back step by step, without stopping the work, and says what Rihmasto does underneath.

Do it in this order. Each step is useful on its own, and you can stop at any of them.

## 1. Capture what is there, changing nothing

Bring the project in at **Watch only** ([existing project](existing-project.md)): adopt it with
`--intent monitor`, or attach it if you want to keep merging yourself.

```bash
rihmasto structure ../orders-service
rihmasto adopt "Orders service" --source ../orders-service --intent monitor \
    --person "Ada Example" --persona developer
```

You now have, on the record:

- **the structure map**: which specs, decisions (ADRs), API contracts, tests, CI jobs and quality tools
  exist, where, in which convention, and how old each is next to the code it describes;
- **the AI tools' setup**: CLAUDE.md, AGENTS.md, Cursor rules, skills, MCP servers, hooks and permission
  rules, as committed;
- **a test baseline**: what the suite does today, failing tests included, recorded as behaviour, not as
  a spec.

## 2. Measure how bad it is

- **Assess.** **Assessment > Assess now** gives findings per perspective (CI/CD governance,
  maintenance, security, compliance, architecture and operations) with evidence and a suggested change for each
  ([assessment](../guides/assessment.md)).
- **Scan for security.** `rihmasto repo scan <pid> --person ... --persona ...` (an attached repository) runs Rihmasto's own static scan
  into the security gate; SARIF from any other scanner goes in with `rihmasto security ingest`
  ([security](../guides/security.md)).
- **See what the agents did.** With the optional agent observability module and your own hub, the
  **Agent sessions** view shows rework hotspots, failures that were never recovered, and the share of
  sessions that read the contract before their first edit ([agent observability](../guides/agent-observability.md)).
- **Run Gnomon's audits** as checks: claim check, degradation, audit trails and more
  ([audits and evals](../guides/audits-and-evals.md)).

Everything that could not be measured says **not measured** and why: that list is your to-do list, not
a pass.

## 3. Write down what it must do

- **Align what exists.** **Alignment > Read the repository** turns the project's own specs, Gherkin
  features, OpenAPI documents and tests into proposed requirements and criteria. Accept, edit or reject
  each ([alignment](../guides/alignment.md)).
- **Fill the gaps.** Each criterion with no test, and each test with no criterion, is listed as a gap.
  File a change for each one that matters ("add a criterion for refunds over the limit"), from the gap
  itself, Ask Rihma or your IDE agent.
- **Decide what was never decided.** Behaviour that nobody chose becomes a question or an assumption
  with a due date, so the record shows it was looked at.

The result is a contract pinned by a hash: every requirement with its criteria, and every criterion with
the test that proves it, or "not measured".

## 4. Put the agents under the contract

- **Tell them.** `rihmasto ide <pid> --section` prints a section for AGENTS.md or CLAUDE.md: the contract,
  what waits on a decision and how a change comes back. Paste it yourself; Rihmasto never writes into
  your repository.
- **Connect them.** The MCP server lets Claude Code, Cursor, Codex or OpenCode read the contract and file
  changes and comments, never decide ([configure with your agents](../guides/configure-your-agents.md)).
- **Brief them.** **Hand off to an agent** (`rihmasto handoff <pid> --to claude-code`) gives the goal, the
  criteria and the conventions in one brief, and the agent channel keeps their progress on the record.

## 5. Gate every change

Move the project up to **Gated**: every change is judged before it merges.

```bash
rihmasto repo gate <pid> --head HEAD --task T-003 --person "Ada Example" --persona developer
```

The kernel runs the tests itself in a temporary clone, checks that the task's criteria have tests that
failed before the change and pass after, and asks a verifier from another model family. A verdict
without the verifier is "not measured", never passed. Holdout scenarios, which no builder ever sees, can
run against your service (`rihmasto repo holdouts`).

## 6. Make it traceable, and keep it so

- **The Knowledge graph view** shows each requirement, its criteria, tests, tasks, decisions, changes and
  releases, with what is missing highlighted. `rihmasto graph trace` and `rihmasto graph impact` answer
  "what does this rest on" and "what breaks if this changes".
- **An evidence pack** (`rihmasto evidence <pid> --out exports ...`) bundles the chain for a reviewer. Its
  verdict is *attestable*, *chain broken* or *insufficient evidence*, never "compliant".
- **Automations keep it up**: re-gate nightly, re-align on each new commit, notify when a check fails
  ([workflows and automations](workflows-and-automations.md)).

## What happens under the hood

| You see | Underneath |
|---|---|
| A structure map | `kernel/repo_structure.py` walks the committed revision by rule; nothing is run, credentials are never read |
| Proposed requirements | `kernel/alignment.py` maps what it found onto the contract's shape; nothing joins the contract until a person accepts it, and each acceptance is a signed ledger record |
| A contract revision | `tools/contract_check.py` recomputes the hash from the content; a stated revision that does not match is refused |
| A gate verdict | `kernel/gate.py` runs the tests in a temporary clone, traces criteria to test names, checks fail-first, then asks the verifier through Gnomon |
| A gap | the knowledge graph's closed-world rules (`rihmasto graph check`): a criterion with no test, a release resting on a refuted assumption; it reports and never blocks |
| Who did what | every record in `ledger.jsonl` names a person and a persona (and the agent, when one acted under a delegation), chained by hash |

## Honest limits

- The gate runs a Python unittest suite; other suites are characterised and can run as checks.
- No paved road delivers an adopted repository yet: you deploy it as before.
- The ledger shows an edit to part of its chain; a consistent rewrite of the whole chain by someone with
  file access is not detected until ledger heads are signed and anchored (designed, not built).
