# Alignment: your repository's own specs and tests, the Rihmasto way

You have been working in Claude Code, Cursor, VS Code or another IDE. Your repository already has its own
structure: specs, user stories and acceptance criteria, decisions, API contracts, tests, task lists, a CI
pipeline, linters, instructions for your AI tools. **Alignment** reads all of that, proposes how it maps
onto a Rihmasto project, and lets you accept, edit or reject each proposal. What you accept becomes the
project's contract and records, signed with your name. Your repository is never written: what it could change
to align is suggested as text to copy or a patch to download, and you keep working in your IDE.

It works on a project with a repository of its own: one you **adopted** (`rihmasto adopt`,
[brownfield.md](../brownfield.md)) or **attached** (`rihmasto repo attach`,
[use only what you need](use-only-what-you-need.md)). FR-ALN1 in the contract.

## In the cockpit

Right after you adopt or attach a repository, its Overview offers the next step: **Open Alignment**. The
**Alignment** tab:

1. **Read the repository** reads the committed revision by rule (an attached repository's branch; an adopted
   project's upstream as last fetched). No model, nothing found is run, nothing is written to the repository.
   Signed with your name, recorded as `alignment_scanned` in the ledger.
2. The **summary** says, for example, "5 of 6 tests trace to a criterion; 3 of 7 requirements have no test;
   1 criterion is not testable as written".
3. The proposals come in groups, each item with what it would **add** to the project, **why**, and the file
   and line it came from:
   - **Requirements**, keeping your ids and titles as their source. A Rihmasto id is proposed: yours when it
     is a valid one (`FR-001`), one built from it (`User Story 2` as `US-2`, Kiro's `Requirement 1` as
     `REQ-1`, `F002-FR-001` when two spec-kit features both have an `FR-001`), else `IMP-n`.
   - **Criteria**, as given / when / then: spec-kit's acceptance scenarios, Kiro's EARS lines (`WHEN ... THEN
     the system SHALL ...`), Gherkin scenarios, items under an "Acceptance criteria" heading. A requirement
     your repository gives no criterion gets one derived from its statement, and says so.
   - **Tests trace**: each of your tests linked to the criterion it most likely checks, with its **basis**
     and a **confidence**: *by name* (the test's name carries the id, 90 to 95%), *by file* (its file or
     suite names the feature, up to 85%), *by text* (similar words, at most 70%). A link under 50% is weak.
   - **Tasks** from your task lists (`tasks.md`, `TODO.md`, checkboxes), done or open, with the requirements
     they name.
   - **Decisions** from your ADRs, with their status, and **API contracts** (OpenAPI, AsyncAPI, GraphQL,
     protobuf, JSON Schema) kept as references, never copies.
   - **Gaps**: requirements with no test, tests with no requirement, criteria not testable as written
     ("user-friendly", "fast"), a spec older than the code it describes (by commit dates), CI that does not
     run the tests.
4. **Accept**, **Edit** (change the statement, the given / when / then, the id; then accept) or **Reject**
   each one, or **Accept all open** in a group. Accepting a criterion takes its requirement with it;
   accepting a requirement takes its criteria you did not reject.
5. **Suggested changes for your repository**: criterion ids in your test names (a patch, `git apply`), a
   task list entry for each requirement no task serves, a CI job that runs the tests, the tests to write,
   the criteria to restate, the specs to bring up to date. Copy or download them; Rihmasto never writes them.
6. **Continue in your IDE**: the accepted contract and the open gaps as text for your `AGENTS.md` or
   `CLAUDE.md` (you paste it yourself).

## What accepting writes

- A requirement and its criteria go into the **project's contract**, `customer-endorsed` by you, with the note
  "imported from the repository (specs/001-loan-items/spec.md:7, their User Story 1, spec-kit), accepted by
  Aino Virtanen on 2026-11-24". Each criterion is a visible test. The contract is checked by
  `tools/contract_check.py` before anything is written.
  - A project whose contract is compiled from its spec (an adopted one, an attached one given a spec file)
    gets them in its spec, and the contract is compiled again with no model: every other task keeps its id.
    On an adopted project the new contract is committed to the mirror's main, as an amendment's is, and the
    imported requirement's task is held as the **existing work**: nothing is built until you reopen it through
    the change loop or a workspace.
  - An attached project whose contract came as a file gets them appended to it, with a task each.
- Tasks, decisions, trace links, API contract references and gaps are kept as the project's **records**
  (`alignment/decisions.json`), each with the item as you accepted it.
- The ledger holds `alignment_accepted` or `alignment_rejected` with the item ids, your name and persona.
- A requirement already in the contract is never rejected here: it leaves the contract through the change
  loop. An id another requirement has is refused.

## Where each item comes from, and what to do with many

Rihmasto takes your project's structure as it is; its own conventions are yours to enforce where they help. So
every item says which it is:

- **From your project**: a requirement, criterion, task, decision, API contract or test trace read from a file,
  with the file, the line and the file's last commit. A planning file (a spec, a task list) committed 21 or more
  days before the code's latest change is marked **may be an old plan**.
- **Rihmasto's convention**: a gap, a criterion Rihmasto derived, a suggested change for your repository or an
  assessment finding, each naming its rule ("every test traces to a requirement").

Filter the view by origin; each group's header counts its items by origin. Before Accept, each item says what
accepting does: what the contract and the records gain, what the gate then measures, that your repository is
never written, how the measured state moves and how to undo it. Accept all shows the same for the whole group
first and asks once; a suggested change says which files and areas it touches, the checks it must pass and how
to undo it.

**What to do with these**, at the top of the view, counts the items to decide by origin, names the ones that may
be from an old plan and recommends what to do: leave Rihmasto's convention items (a test that traces to no
requirement stops being a gap once your tests are mapped), reject the stale ones or wait for the current plan,
and accept what your project's current sources say. **Reject stale**, **Defer convention items** and **Accept
from current sources** each show their impact and are signed with your name; a deferred item is set aside, not
decided, and **Bring back** returns it. Weak test traces are never accepted unseen. Ask Rihma "what should I do
with these?" for the same, with each action to confirm, or:

```
rihmasto align-triage <pid> [--json]
rihmasto align-triage <pid> --impact <item>... [--verdict accept|reject|defer]
rihmasto align-triage <pid> --do reject_stale|defer_convention|accept_current|restore --person ... --persona ...
```

### What the triage keeps true

- **Your tests decide what is current.** A requirement, criterion or task that a current test of your project
  checks (a trace that is not weak, to it, its requirement or what the task serves) is never "may be an old plan",
  however old its file; its origin says which tests check it. Reject stale never takes it.
- **A test counts once its criterion is in the contract.** The impact says which tests become counted, which wait
  for their criterion ("not counted until US-1-AC-1 is in the contract") and which trace to a criterion you
  rejected. Accept from current sources leaves those out and the head names them.
- **A gap about what you rejected is closed.** It shows as Closed, out of the count to decide, exactly as the
  measured state counts it; accept the item again and the gap opens again.
- **One number to decide.** The summary counts what is open and not deferred, with deferred and closed apart; each
  filter counts the rows it shows.
- **Nothing is decided silently.** The impact names the items that come with the ones you asked (a requirement's
  criteria, a criterion's requirement), those of them you had deferred, and for a bulk accept how many may be from
  an old plan and how many are Rihmasto's convention.
- **Risks are not bookkeeping.** "The CI does not run the tests" and a criterion no test can observe are named
  apart as possible real risks and never deferred with the convention items. The head says plainly that none of
  these decisions is development work: development moves in Tasks and Changes.
- **Suggestions follow your decisions**: none asks for work on what you rejected; a stale-spec suggestion names the
  specs it edits. An assessment finding about something present in your project (a committed secret, failing
  tests) is **Found in your project**, not a convention.
- **Ask Rihma in your own words**: "am I moving the needle with dev?", "which of these are stale?", "which should I
  accept?", "what happens if I accept all gaps?" (the impact of exactly that). A proposal carries the items its
  impact was said for; confirmed after another one changed the list, it takes only what is left and says what it
  skipped.

## When your repository changes

Read it again (the button, or `rihmasto align <pid> --scan`): the **drift** says what is new since the scan
before, what changed and what was removed. An item you accepted whose source changed reads **changed since
accepted**: accept it again to restate it in the contract, or **Keep as accepted**. Items that did not change
keep their ids and your decisions. An adopted project's upstream moves with `rihmasto sync`; an automation that
runs on a repository change can call the same scan.

## Continuing in your IDE

Alignment is how the work comes back from the IDE, not a reason to leave it:

- the text for your IDE agent lists what was accepted from your repository and the gaps still open
  (the "Work on it from your IDE" section of an adopted or attached project adds it when it is present);
- `rihmasto repo gate <pid> --head <revision> [--task <id>]` judges a commit against the contract, which now
  holds the accepted criteria; its answer names the accepted criteria whose traced tests the change edits
  (`aligned`). A test named `test_<criterion id>_...` is traced by the gate exactly: the suggested patch
  renames yours.

## On the command line

```
rihmasto structure <folder> [--json]          the structure map of any folder; nothing is run
rihmasto align <pid> [--json]                 what is proposed and decided
rihmasto align <pid> --scan --person "Aino Virtanen" --persona developer
rihmasto align <pid> --drift [--json]
rihmasto align <pid> accept|reject <item>... --person ... --persona ... [--reason ...]
rihmasto align <pid> edit <item> --set then="the loan is marked overdue" --person ... --persona ...
```

Reading needs no signature; a scan and a decision do, and a refusal exits 2.

## What is recognised

| What | Where and how |
| --- | --- |
| Specs and requirements | spec-kit `specs/<n>-<name>/spec.md` (user stories with priorities, `**FR-001**:` lines); Kiro `.kiro/specs/<name>/requirements.md`; BMAD (`docs/prd.md`, `docs/stories/`); agent-os (`.agent-os/specs/`); PRD, RFC, requirements, user stories and feature documents; a line or heading starting with an id (`REQ-12`, `US-3`, `FR1`); "As a ..., I want ..., so that ..." |
| Acceptance criteria | given / when / then lines and spec-kit's acceptance scenarios; EARS (`WHEN`, `IF`, `WHILE`, `WHERE` ... `SHALL`); Gherkin `.feature` files with their tags; lists under "Acceptance criteria" |
| Decisions | ADRs under `adr/`, `docs/adr/`, `docs/decisions/` and the like: number, title, status, date |
| API contracts | OpenAPI and Swagger (YAML or JSON), AsyncAPI, GraphQL schemas, `.proto`, JSON Schema |
| Tests | pytest and unittest, jest, vitest, mocha, Playwright, Cypress, go test, JUnit, xUnit and NUnit, RSpec: each test's name; how they run (`package.json` scripts, pytest configuration, Makefile, tox, go, cargo, Maven, Gradle), never run; coverage configuration |
| Tasks | checkbox lines in `tasks.md`, `TODO.md`, backlogs and checklists, with Kiro's `_Requirements: 1.1_` |
| CI/CD | GitHub Actions, GitLab CI, Azure Pipelines, CircleCI, Bitbucket, Jenkins: each job and the commands it runs, and whether one runs tests |
| Quality | ruff, flake8, pylint, mypy, pyright, black, isort, eslint, prettier, TypeScript, biome, golangci-lint, rubocop, pre-commit and husky hooks, EditorConfig, SonarQube and more |
| Architecture | architecture and design documents, spec-kit plans, Kiro steering, PlantUML, Mermaid and C4 files |
| AI tools | `CLAUDE.md`, `AGENTS.md`, Cursor, Copilot, Windsurf and Cline rules, skills, MCP configuration: read by `kernel/agent_context.py` when it is present, otherwise named only |

A file whose name or text may hold a credential is never read and never shown; a link is never followed; a
file over 1 MB is listed, not read. The modules: `kernel/repo_structure.py`, `kernel/repo_specs.py`,
`kernel/repo_suites.py` (capture), `kernel/alignment.py` and `kernel/alignment_suggest.py` (proposals),
`kernel/alignment_records.py` and `kernel/alignment_contract.py` (decisions), `kernel/alignment_cli.py`,
`cockpit/align_routes.py` and `cockpit/static/alignment.js`.

## Not built yet

- The trace reads test names, not what a test asserts; a test whose name says nothing about what it checks
  is a gap until you rename it or accept a weak link.
- Requirements are recognised by the conventions above; free prose with no id, story or heading is not.
- A requirement removed from your repository is shown as removed; it leaves the contract only through the
  change loop.
