# Improve and maintain

A project runs in Rihmasto: started from a blank page, adopted, or attached. This guide is the weekly
rhythm that keeps it healthy and moves it forward, for one person working alone, and what Rihmasto
does underneath.

## The rhythm in one table

| When | What you do | Where | Command |
|---|---|---|---|
| Each morning | Read what shipped, what went wrong, what was decided in your name, what waits on you | **Review** | `rihmasto review` |
| When a card waits | Decide it: approve, accept, retry, stop | **Inbox** | `rihmasto decide <pid> <card> <verdict> --person ... --persona ...` |
| Once per project | Turn on what applies: checks, an automation, alignment | **Set up this project** on the Overview | `rihmasto setup <pid>` |
| On a schedule | Tests, CI status, dependencies, secrets, licences, an SBOM, a probe | **Health** | `rihmasto checks enable <pid> tests --every 1d ...` |
| Now and then | Assess again; read the trends | **Assessment**, **Insights** | `rihmasto assess <pid> ...`, `rihmasto insights <pid>` |
| When you want a change | Report it, or hand it to your coding agent | **Report a change**, **Hand off to an agent** | `rihmasto change ...`, `rihmasto handoff <pid> --to claude-code` |

## Improve: a change, end to end

1. **Say what should change.** **Report a change** on the project, Ask Rihma ("the loans list should
   show overdue items first"), or from your IDE agent over MCP (`rihma_report_change`). The kernel
   classifies it by rule: a fix inside an existing criterion, or a new promise that needs a business
   decision.
2. **Decide what needs deciding.** A change that alters what is promised waits on a product or business
   owner in the Inbox. In solo mode that is you, signed with the persona it needs.
3. **Build it.** **Advance** builds it in a cell and gates it, or **Hand off to an agent** gives your
   coding agent a brief with the goal, the contract's criteria, the project's conventions and how to
   report back ([agentic help](../guides/agentic-help.md)). Your agent's work comes back through a
   workspace (`rihmasto workspace submit`) or, on an attached repository, `rihmasto repo gate`.
4. **See it land.** Review shows it as shipped; the Knowledge graph view links the change to its
   criterion, its test and its release.

Not sure how? "What next?" in Ask Rihma, or **What's next** on the Overview, names the next step with
its button and its command ([guided journeys](../guides/guided-journeys.md)).

## Maintain: stay ahead of breakage

- **Checks on a schedule.** Each check answers passed, failed or not measured, with why. A failure can
  log a signal or open a change proposal once, when the verdict turns
  ([console and checks](../guides/console-and-checks.md)).
- **Probes and incidents.** On a delivered release, `rihmasto operate <pid>` probes `/health` and the
  probe scenarios; a failing probe opens an incident card. On a road with a canary, a worse canary is
  rolled back.
- **Self-healing.** A failed job, a broken view or a refused step becomes an incident in plain words,
  with the remedies Rihmasto knows (learned ones first), **Investigate with Rihma**, and a fix through
  the gate offered as a pull request on your approval ([self-healing](../guides/self-healing.md)).
- **Upstream drift.** `rihmasto sync <pid>` records what changed upstream of an adopted project; an
  automation can do it on every new commit ([workflows and automations](workflows-and-automations.md)).
- **Gnomon's audits and evals** run as checks: security posture, compliance mapping, data flow, agent
  metrics and more, each saying what it costs ([audits and evals](../guides/audits-and-evals.md)).

## How strict, and how much alone

- **Posture** sets how strict the chain is: prototype, balanced, production or regulated. `rihmasto
  posture preview <posture>` shows what would change before you choose ([postures](../guides/postures.md)).
- **Maturity** sets where it lands: explore < demo < pilot < production.
- **Autonomy** caps how far Rihmasto goes on its own; **delegation** gives chosen kinds of decision to
  an agent until a date you set; the **autopilot** runs a project in a sandbox
  ([autopilot and tracking](../guides/autopilot-and-tracking.md), [autonomy](../guides/autonomy.md)).

Change any of these during the run, with a preview of what it means
([change anything](../guides/change-anything.md)).

## What happens under the hood

- **One loop for every change.** Feedback, an incident, a failed check, a drift card and a request from
  your IDE all become change cards (`kernel/change.py`). Triage sends each to the step it belongs to: a
  question, the spec, a task. An approval that a change makes stale is marked stale, so nothing ships on
  an approval that no longer holds.
- **Checks and automations act with their owner's rights**, checked again before every run; a guard
  keeps a quiet tick free; a circuit breaker pauses an automation after repeated failures and says why.
- **Review is counted from the ledger**, not from a model: what shipped, what failed, what was decided
  for you (`kernel/review*.py`). Insights counts health, security, QA, governance and usage the same
  way, and exports JSON, CSV or OpenTelemetry for your own stack.
- **Lessons.** `rihmasto learn` reads across projects for repeated failures and model reliability and
  proposes changes; a person accepts them.

## Next

- [Build workflows and automations](workflows-and-automations.md) to put the rhythm on a schedule.
- [Review](../guides/review.md) and [Insights](../guides/insights.md) in depth.
