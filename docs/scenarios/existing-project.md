# Bring in an existing project

You have a repository that already works, built in your own IDE, perhaps with coding agents. You want
Rihmasto beside it: its structure captured, a contract, a gate on changes, checks that keep it
healthy, without giving up your editor or your workflow. This guide shows the two ways in, how much of
Rihmasto's structure to take on, and what happens underneath.

**What Rihmasto does not do here (yet):** no paved road delivers an adopted repository. Rihmasto
adopts, aligns, gates, checks and watches it; you deploy it as you do today. The gate itself runs a
Python unittest suite; other suites are characterised at adoption and can run as checks.

## Two ways in: adopt or attach

| | **Adopt** | **Attach** |
|---|---|---|
| What Rihmasto holds | its own copy of the repository (`repo.git` in the factory home); a folder that is not a git repository is snapshotted | nothing: a pointer to your repository on this machine |
| Your folder | never changed | never written, pushed to or merged into |
| How a change comes back | a workspace (`rihmasto workspace open`, then `submit`) goes through the gate and merges into Rihmasto's main; `rihmasto sync` sees what you pushed upstream | you commit as always; `rihmasto repo gate <pid> --head <commit>` judges it in a temporary clone, and **you** merge |
| Good for | Monitor, Maintain or Improve a system as a whole | "gate my code", "security only", "evidence only" |
| Command | `rihmasto adopt` | `rihmasto repo attach` |

## 1. Point at it and scan

**In the cockpit.** **New project > An existing project**: a folder on this machine (press
**Browse…** or **Browse here**) or a git address. **Scan the folder** shows what would be read, listed
and skipped, the AI-tool setup it found (CLAUDE.md, AGENTS.md, Cursor rules, MCP servers, skills) and
the files it never reads because they look secret. Untick what to leave out. Tick **Confidential** to
keep every model call for this project on local models.

**In Ask Rihma.** "I have an existing project" (or "adopt the project in C:\dev\x") offers **Walk me
through it**.

**On the command line.**

```bash
rihmasto scan ../billing-service                      # what would be read, and why
rihmasto structure ../billing-service                 # its own specs, ADRs, API contracts, tests, CI
rihmasto adopt "Billing service" --source ../billing-service --intent maintain \
    --person "Ada Example" --persona developer
```

`--intent` is `monitor` (probe where it runs: add `--base-url`), `maintain` or `improve`. A private
repository: clone it yourself and adopt the local path.

To attach instead, with a contract or a spec file you have:

```bash
rihmasto repo attach "Billing service" --repo ../billing-service --spec spec.json \
    --person "Ada Example" --persona developer
rihmasto repo gate <pid> --head HEAD --person "Ada Example" --persona developer
```

## 2. See what it is

- **Assessment > Assess now** (or `rihmasto assess <pid> --person "Ada Example" --persona developer`)
  gives findings per area, with live progress, that you can file as changes
  ([assessment](../guides/assessment.md)).
- **Set up this project** on the Overview lists every feature that applies, each with one click:
  checks, a suggested automation, alignment, posture, outputs (`rihmasto setup <pid>`).

## 3. Align its own specs and tests with a contract

**Alignment > Read the repository** proposes the repository's own specs, criteria and tests for the
contract (spec-kit, Kiro, BMAD, Gherkin, OpenAPI and more). Accept, edit or reject each; the gaps and
the drift show beside them ([alignment](../guides/alignment.md)).

```bash
rihmasto align <pid> --scan --person "Ada Example" --persona developer
rihmasto align <pid>                                  # the proposals, with their ids
rihmasto align <pid> accept <item ids> --person "Ada Example" --persona developer
```

## 4. Keep working in your IDE

**Work on it from your IDE** on the Overview (or `rihmasto ide <pid>`) gives the MCP configuration for
Claude Code, Cursor and Codex, and a section to paste into your AGENTS.md or CLAUDE.md: the contract,
what waits on a decision and how a change comes back. Rihmasto never writes it there itself
([configure with your agents](../guides/configure-your-agents.md)).

## How much structure to take on

You choose how far Rihmasto's structure reaches into the project, and you can change it later
(Settings, Modules, or `rihmasto modules set --project <pid> ...`). Nothing below rewrites your
repository.

| Level | What you get | What it asks of you | How |
|---|---|---|---|
| **Watch only** | an inventory, a test baseline, checks, upstream drift, findings | nothing changes in how you work | adopt with `--intent monitor`, or the `assess_only` preset |
| **Captured** | the structure map: where its specs, decisions, API contracts and tests are, and in which convention | nothing; it only reads | `rihmasto structure <folder>`; the Alignment tab |
| **Aligned** | a contract made of your own specs and tests, gaps listed, drift seen after each change | accept or reject proposals | Alignment, `rihmasto align` |
| **Gated** | a verdict on each change: tests by criterion, fail-first, an independent verifier | commit, ask the gate, then merge yourself | attach and `rihmasto repo gate`, or the `gate_my_code` preset |
| **Full chain** | changes built in cells and merged only through the gate; the change loop, packs, evidence | changes come back through a workspace or a builder cell | adopt with `--intent improve`, the `full` preset |

**Not enforcing is a real choice.** A project at "Watch only" still has every step on the record and
"not measured" where nothing was checked; it simply asks nothing of the people working on it. Move up
when the project earns it: when changes break things, when more people or agents touch it, or when
someone needs evidence.

## What happens under the hood

- **Reading, never running.** The scan and the structure map walk the folder by rule, skip dependency,
  build and cache folders, follow no link and never read a file that may hold a credential. Nothing
  found is run, apart from the test baseline below. An adopted repository is read from git's objects at
  a committed revision, never from your working tree.
- **The baseline is behaviour, not a spec.** Adoption runs a detected Python suite once and records the
  result as it is: a suite that already fails is recorded as failing. A toolchain the kernel does not run
  reads "not measured".
- **The AI tools' setup is followed, not overwritten.** CLAUDE.md, AGENTS.md, Cursor rules, skills and MCP
  servers are recorded (`kernel/agent_context.py`) and given to Rihma's own agents as the project's
  conventions.
- **The upstream is fetch-only.** `rihmasto sync <pid>` fetches it and records the drift; when it moved,
  an "Upstream changed: review" card waits for a person. Main never moves by itself.
- **Every proposal is signed.** An alignment scan, an accepted item and a gate verdict are each a ledger
  record that names the person and persona; an attached project's record names the repository, its
  branch and head, and where its contract came from.
- **Confidential stays local.** With Confidential ticked, a call that would go to a hosted model is
  refused and says how to route it locally.

## Next

- [Fix a project that lacks governance](fix-ungoverned-project.md) if the project grew without specs or
  tests.
- [Improve and maintain](improve-and-maintain.md) for the weekly rhythm.
- [Existing solutions, in depth](../brownfield.md): workspaces, SARIF findings and the honest list of
  what is not built.
