# Brownfield: existing solutions, a terminal beside the chat, and security findings

Rihma started greenfield: a need becomes a spec, a contract and a product. This page covers the
pieces that let it hold solutions that already exist, assess what they should fix from every
perspective, let a person work on them by hand, and take security findings from any scanner. They follow the same rules of evidence: named verdicts, "not
measured" as a state, everything in the ledger, and people decide.

## Adopting an existing solution

```
python -m kernel.cli adopt "Legacy loans" --source <folder or URL> --intent monitor|maintain|improve \
    --person Aino --persona developer [--base-url https://loans.example] [--exclude GLOB] [--confidential]
python -m kernel.cli sync <pid>
```

### Any folder

The source may be **any folder** on this machine, not only a git repository
([kernel/material_adopt.py](../kernel/material_adopt.py), FR-MAT1):

- **A git repository** is adopted as below. Its documents are also scanned
  ([kernel/material.py](../kernel/material.py), see [the material map](guides/inputs.md#any-folder-the-material-map))
  as context for the panel and the coming assessment: the project keeps the map (`material.json`) and
  the text built from it (`material.md`), and the ledger's `material_scanned` holds the counts. Nothing
  is sent to a model at adoption.
- **A folder that is not a git repository** is first **snapshotted**: the files that pass the scan's
  rules (no dependency, build or cache folders, nothing that may hold secrets, nothing you excluded) are
  copied into a new git repository under the factory home (`snapshots/`) and committed as the baseline
  ("Baseline snapshot of <folder>"). Your folder is never changed: no `.git` is created in it. That
  repository is then adopted like any other, and `adopted.json` and the ledger's `snapshot_taken` say
  what was copied, skipped and excluded. A later `sync` reads the snapshot, which does not follow your
  folder: adopt it again to take a new baseline.
- **A folder with no code at all** (only documents) is refused: there is nothing to adopt. The message
  offers to start a new project from it as material instead (`rihmasto new "Title" --source <folder>`).

**The team's AI tools.** A repository the team works on in Cursor, Claude Code or another IDE agent
holds its conventions: `CLAUDE.md`, `AGENTS.md`, Cursor rules, skills, slash commands, hooks and MCP
servers. Adoption recognises them by rule and runs none of them: the baseline runs the test command
they state (when the kernel runs it), the assessment's panel and a builder cell's envelope carry
them, and the project's Overview shows them beside **Work on it from your IDE**. See
[guides/ide-and-rihmasto.md](guides/ide-and-rihmasto.md) for where the IDE ends and Rihmasto begins.

In the cockpit, **New project → An existing project** takes the folder and shows the same scan first
(**Scan the folder**): what would be read, listed and skipped, and whether it is a git repository. Untick
files to leave them out of the snapshot and the scanned documents; a folder of documents only gets a
**Start a new project from it** button. `--confidential` (or the box) records the project as
confidential, so every later model call for it stays on local models
([inputs.md](guides/inputs.md#confidential-material-keep-it-on-local-models)).

`kernel/adopt.py` makes the repository a project (`source_kind: adopted`):

- **The mirror.** The code is fetched into the project's `repo.git`. The upstream's default branch
  at adoption is the **baseline**; `main` is the baseline plus one kernel commit that holds the
  kernel's own compiled `.gnomon/` surface (`surface_compiled` in the ledger). In that commit the
  kernel removes what the upstream keeps under a name the kernel holds on `main`: an upstream's own
  `.gnomon/` (its endpoints, key variables, roles and prompts), Gnomon's machine-local directories
  (`.gnomon-inbox/`, `.gnomon-skills/`, `.gnomon-audit/` and the rest) and `.lfsconfig`. A name
  counts under every spelling a file system opens it by: another case (`.GNOMON/` is `.gnomon/` on
  NTFS and APFS), the 8.3 short name Windows gives it (`GNOMON~1/`), trailing dots or spaces, an
  NTFS stream suffix, or characters HFS+ ignores. So every later checkout of `main` (a builder
  cell, the gate's verifier, a workspace) runs under the kernel's surface, never one the upstream
  wrote. `surface_compiled` lists what was removed (`removed_upstream_surface`); the baseline keeps
  it in the history. The upstream is a fetch-only remote: its push URL is not a transport, and the
  kernel never pushes there.
- **No credentials.** A URL is adopted only when `git clone` reads it without any: credential
  helpers, prompts and Git LFS downloads are switched off for every git call that adoption and
  `sync` make (the fetch, the checkout of the baseline, the surface commit), and a URL with a user,
  a password, a token, a query, an ssh address or a transport helper is refused. So is a
  `base_url` with a user, a password, a query or a fragment: it would land in the hash-chained
  ledger, the spec and the brief. A later checkout of `main` (a lane, a workspace) is an ordinary
  git call under the owner's configuration, so git-lfs runs there if the owner installed it; but
  `main` carries no `.lfsconfig` of the upstream's, so the only address git-lfs knows there is the
  clone's own origin, the local `repo.git`: never an address the upstream chose, and the owner's
  credential helper is not asked for one. Clone a private repository yourself and adopt the local
  path. A git call that reaches the upstream has a timeout that stops git and every helper it
  started, and gives up on a transfer that stalls.
- **The inventory, by rule.** Languages by file extension; the test command (pytest or unittest,
  `npm test`, `go test`, `cargo test`, Maven or Gradle), detected or not, never guessed; the
  README's first paragraph; the HTTP routes the source declares (Flask, FastAPI, Express, Go,
  Spring, Django and Rihma's own `@route`), listed only when a `base_url` is given (their number,
  `http_routes`, always, for the work profile); whether there
  is a Dockerfile. Only regular files inside the checkout are read: a symlink is never followed,
  and a file name that is not UTF-8 is counted, not fatal. It is kept in `inventory.json`.
- **The work profile.** Proposed by rule from the title, the README and its files (HTTP routes the code
  declares count as an API), unless a person chose one. With one clear candidate it is taken, and the
  brief and `rihmasto adopt`'s `profile_basis` say which and why. When the rule is not sure (one keyword,
  none, or two profiles close), adoption does not fall back to a web app: it **asks** a person which kind
  of work it is, with the "Which kind of work is this?" question card intake uses and the candidate kinds
  as its options (`adopt_kind_asked`; the owner's decision of 2026-11-24). The kind stays unset until the
  answer, which chooses it (`profile_chosen`, `adopted.json`, the brief); What's next and the Inbox show the
  question, and Project settings can choose the kind too ([kernel/adopt_kind.py](../kernel/adopt_kind.py)).
- **The characterisation baseline.** A detected Python suite runs once in a temporary checkout,
  with a per-suite timeout of its own, apart from git's (`SUITE_TIMEOUT`, 300 s; from Python,
  `adopt(..., suite_timeout=...)`, with no command-line flag yet). A suite still running then is
  stopped and recorded as "not measured: timed out", with the limit, and adoption goes on. Its
  counts are **existing behaviour, not a spec**: a suite that already fails is
  recorded as failing, not judged. Other toolchains run only when the tool is on PATH, offline
  (nothing is installed or downloaded); otherwise the baseline says "not measured: toolchain not
  run by the kernel". It is "passed" only when at least one test passed: no tests, every test
  skipped, or output the kernel cannot read is "not measured", never "passed", and so is a suite
  that could not import a dependency the kernel does not install. Running the suite runs the
  adopted code on this machine: adopt only code you would run. Its stdin is closed, its output goes
  to files, and the timeout, like the end of the run, stops every process it started (a process
  group on POSIX, a job object on Windows).
- **Nothing half-adopted.** Everything that reads the upstream (the fetch, the checkout, the
  inventory and the characterisation) runs before the project exists, and a failure after it
  exists removes it again.
- **The as-is spec.** Requirement R-1, of `observed` provenance: "the existing test suite keeps
  passing", one criterion per detected suite. With a `base_url`, R-2: "GET <base_url> answers", a
  probe whose scenario is written by rule into the holdout custody. The spec compiles to a
  contract and a check plan; the contract's provenance vocabulary has no observed tier, so the
  compiler enters these requirements as `vendor-proposed` with the note "observed: existing
  behaviour at adoption, not a spec" (`as_is_spec_written` in the ledger says so).
- **The stage.** `monitor` goes to stage 7 and probes `base_url` (a failing probe opens an incident
  card; a server error, 5xx, is a failing probe, not a healthy answer). `maintain` and `improve`
  wait at stage 5: the as-is tasks hold the existing code, so nothing is built until a change
  arrives through the change loop or a person's workspace.

`sync` fetches the upstream again and records the drift since the baseline: new commits, rewritten
history and the files that differ (`upstream_synced`). When the upstream moved since the last look,
it opens a change card, "Upstream changed: review", filed by "upstream sync" as a developer. It
never moves `main`: what the factory holds changes only when a person decides. Commit messages and
file names that are not UTF-8 are read with the bytes replaced. When the tracked branch is gone
upstream after a fetch that worked (a default branch renamed from `master` to `main`), sync says so
("not measured: the tracked branch ... is no longer upstream", `upstream_branch_gone`) and opens
one change card naming the new default branch; the project keeps tracking the old name until a
person decides. For a monitored project, `rihma sync` also runs a probe round.

## Assessing an adopted system

```
rihmasto assess <pid> --person Aino --persona developer [--with-model] [--ref main]
rihmasto assessment list <pid>
rihmasto assessment show <pid> [--version AS-2] [--full]
rihmasto assessment compare <pid> [--from AS-1] [--to AS-2]
rihmasto assessment change <pid> F-3 P-1 --person Aino --persona developer [--as new_requirement]
```

In the cockpit, an adopted project has an **Assessment** tab beside its Overview. An assessment
tells you what the system should fix, from five perspectives, and lets you turn what matters into
changes that go round the factory's change loop (`kernel/assess.py`, `kernel/assess_cards.py`).

**What it reads.** One revision of the project's own mirror: `main`, what the factory holds, unless
`--ref` names another (`upstream/main` reads the upstream's head after a `sync`). The files are read
from git's objects, never checked out: no filter, hook or LFS helper runs, nothing reaches the
upstream, and nothing of the repository is executed. A link is not followed, a submodule is not
fetched, a name this machine cannot hold or a file over 2 MB is not written; each is said in the
record's notes. The kernel's own `.gnomon/` surface on main is the factory's, not the system's, and
is left out.

**The perspectives, by rule first.**

| Perspective | The rules look at |
|---|---|
| CI/CD governance | a pipeline (GitHub Actions, GitLab CI, Azure Pipelines, Jenkins and others), whether it runs the tests, whether it runs on pull requests, actions pinned to a commit, a workflow's token permissions, a release process |
| Maintenance | a test suite found by rule, the adoption's characterisation baseline, coverage configured, dependencies pinned (or a lock file), when the dependencies last changed, an update bot, the README, code owners |
| Security | the red team's static layer over the revision (Python, JavaScript, HTML, Dockerfiles, Actions and secrets, D-0014) and what it could read, a SECURITY.md, environment files kept out of git |
| Compliance | a licence, a NOTICE for vendored code, fields named like personal data and whether a document says how they are handled, an audit trail in the code, the factory's own records of the system (the ledger's chain, decisions, the controls an evidence pack covers) and whether a security scan is on record |
| Architecture and operations | entry points, a health endpoint, configuration from the environment, logging through a library, a container and its `.dockerignore` |

Each check is passed, failed, not applicable or not measured. A failed check is a **finding**
(`F-1`, `F-2`, ...): its perspective, a severity (critical, high, medium, low), its evidence (a file
and a line with the line itself, masked as the red team masks a secret, or a measured fact) and a
suggested change. A check that cannot know says **not measured** and why, never passed: whether
`main` is protected and which checks a merge requires are set in the hosting service, not in the
files, so they always read "not measured" until someone records the answer; a route the kernel's
simple patterns miss makes the health check "not measured", not "no health endpoint"; coverage is
"configured", its value not measured, because the kernel does not instrument the suite; the age of
each package is not measured, because no registry is read offline; the characterisation baseline
reads passed or failed only at the revision its suite ran at (the adoption's upstream revision), and
"not measured" at any other, `main` included (it adds the kernel's surface commit), with the result at
adoption in the reason: assess `--ref <that revision>` to read the run itself. Dates are the mirror's
commit dates, never this machine's clock.

A rule passes only on what shows its claim, never on a word in passing. A match inside a comment
does not count. Configuration "comes from the environment" only where the code reads it (`os.environ`,
`getenv`, `process.env` and their kind), and a `config.get(...)` on a dict does not. An audit trail
counts when the code names one (`audit_log`, `AuditTrail`, `@Audited`, a history library), not the
bare word "audit"; what it records is not checked. How personal data is handled counts as written
down when a document is named for it (`PRIVACY.md`, `data-protection.md`, a DPIA) or a Markdown
document has a section headed for it ("## Personal data", "## Privacy", "## Retention"); a README
that only mentions privacy does not, and what such a section says is not checked by rule.

**The panel second.** With `--with-model` (in the cockpit, **Ask the panel too**, which uses the
cockpit's own model), each perspective of the intake panel (business, end user, IT and security,
operations, delivery) reads the inventory and the rules' results and proposes up to three findings
the rules cannot see (`P-1`, `P-2`, ...; `kernel/assess_panel.py`). A proposal is **model_proposed**:
an opinion, never a fact, never counted with the rules' findings. What it says it rests on is
checked (a finding id or a file of the repository is "found"; anything else is "not found in the
repository"). The repository's own words reach the model as quoted data it cannot close. A
perspective whose model call fails is "not measured" in the record, and the assessment is still
recorded. The record and its trace name the model that answered each perspective where the harness
says which (a Gnomon run does), and "not recorded" where it does not.

**A record, comparable over time.** Each assessment is a version, `AS-<n>`, in the project's
`assessments/` folder, with the red team's SARIF beside it (`AS-<n>.sarif`, ready for
`rihmasto security ingest`). Its sha256 is in `assessments/index.json` and in the ledger
(`assessment_recorded`), with the trace every path writes (D-0017): who asked, what decided (the
rules, no model), what was delegated to whom (the panel's model, by the person who asked, kept as
model_proposed), what was assumed (each check that could not know, with its reason) and what proves
it (the revision and the SARIF's sha256). A record is checked against the sha256 in the ledger,
whose hash chain protects it, not only against the index, a plain file beside it: a record that no
longer hashes to the ledger's sha256 (even with its index entry edited to match) shows as "changed
since recorded". Each version says what changed since the one before: findings new,
resolved, still open and no longer measured; `rihmasto assessment compare` takes any two.

**Into the change loop.** Tick findings and file them (or `rihmasto assessment change`): each becomes
a change card signed by you, its first line the finding's title with the assessment and finding id,
its text the perspective, severity, who found it (the rules, or the panel as an opinion), the
evidence and the suggested change. The card carries its origin (`refs.origin: "assessment"`, and
the assessment, the finding and its key in `payload.origin`) and is triaged by rule like any change,
as a **new requirement** unless you choose another class, so a business owner or product owner
decides it before anything is built. A finding whose card is still open is not filed twice
(`assessments/filed.json`); once that card is decided it may be filed again. Each card is
`assessment_change_opened` in the ledger.

**Where else it shows.** The evidence pack carries `assessment.json` (the latest version in short,
every version with its sha256 checked against the ledger) and a line in its README. The MCP server reads it with
`rihma_assessment` ([mcp.md](mcp.md)); it files nothing.

### Tutorial: assess, read, file, assess again

1. **Adopt the system** (above), or open the demo's *Stock levels service*, an adopted project.
2. **Assess it.** Open the project's **Assessment** tab and press **Assess now** (signed with the
   name and persona in your person chip), or run `rihmasto assess <pid> --person Aino --persona
   developer`. The rules take seconds, and the record is there when the button is ready again. With
   **Ask the panel too** the panel's model reviews it in the background: the tab says "Assessing"
   until the record is written.
3. **Read it by perspective.** The summary says how many findings by severity, and what changed
   since the version before. Each perspective lists its findings with their evidence and suggested
   change, then what was not measured and why; what passed is folded away.
4. **Choose what matters.** Tick the findings to fix, choose how to file them (a new requirement by
   default) and press **File the ticked findings as changes**. Each finding shows the card it became.
5. **Decide.** A business owner or product owner finds the cards in the Inbox and accepts, rejects or
   defers each; an accepted one goes back to its stage, and the work is built and gated like any
   change.
6. **Assess again.** After the change merged, or after `rihmasto sync` when the upstream moved
   (`--ref upstream/main`), assess again: the summary says what was resolved, what is new and what is
   still open. `rihmasto assessment compare <pid> --from AS-1 --to AS-3` compares any two.
7. **Ask Rihma.** "Where do I assess an existing system?" and **Take me there** open the tab; "How
   do I file findings as changes?" points at the button.

### Built, and planned

Built and covered by tests (`tests/test_assess.py`, `tests/test_ui_assess.py`): the rules of the five
perspectives over a revision read from git's objects, the red team's static layer and its SARIF, the
panel's proposals kept apart, the versioned record with its sha256 in the ledger (each version
checked against it) and its trace, the comparison of versions, findings filed as change cards with
their origin, the command line, the
cockpit's Assessment tab, the MCP read, the evidence pack's `assessment.json`, and the assistant's
map entries.

Planned, not built:
- reading branch protection and required checks from the hosting service through Gnomon's
  integration lane (D-0015), so they are measured rather than "not measured";
- coverage measured by running the suite under coverage in a sandbox, and each package's age read
  from an offline mirror of its registry;
- rules for more ecosystems' pipelines and manifests (Gradle and Maven versions, Go and Rust
  workspaces) and for infrastructure as code;
- an assessment after each `sync` on its own, and a cockpit view that compares any two versions (the
  command line does today; the tab shows what changed since the version before);
- ingesting the assessment's SARIF from the cockpit (today: `rihmasto security ingest`).

## Workspaces: a terminal beside the chat

```
python -m kernel.cli workspace open <pid> --person Aino --persona developer --agent gnomon|claude|opencode|shell
python -m kernel.cli workspace submit <pid> <path> --person Aino --persona developer [--task T-003]
python -m kernel.cli workspace list <pid>
```

`kernel/workspace.py` clones the product's repository onto a branch of the person's own,
`work/<person>/<n>`, in `<lanes root>/workspaces/<pid>/<person>-<n>`, and writes two files there,
kept out of every commit:

- `RIHMA_CONTEXT.md`: the brief, the spec, the tasks, the open cards and questions, the `now` line,
  the evidence counts and the rules;
- `.mcp.json`: Rihma's MCP server ([mcp.md](mcp.md)) for this factory home, signed with the person
  and persona. The agent in the terminal can read the factory and file proposals; it has no tool
  that decides.

`open` returns the command that opens the person's own terminal there (`wt.exe -d`, `cmd /c start`,
`x-terminal-emulator`, `gnome-terminal`, `open -a Terminal`, or the agent command alone). The kernel
never runs it; `launch` is a separate call for a cockpit on the person's own machine.

`submit` makes the person a cell. The branch's commits meet the gate a builder cell meets: the
kernel runs the tests itself, traces the criteria and checks fail-first for the task named with
`--task`, and the independent verifier reviews the change. Without a task, the suite and the
verifier judge it, and trace and fail-first are not applicable. Warranted, it merges into `main`
under the same policy; otherwise it escalates with every objection, and a later passing submission
closes that escalation. The gate record names the person (`author: {"type": "person", ...}`). A
submission with no commits is refused, and so is one that touches what a cell may not:
`.gnomon/`, `contract.json` and `factory/`.

## Security findings from any scanner

`adapters/sarif.py` reads a SARIF 2.1.0 file from any tool (bandit, semgrep, trivy, ZAP, or
Rihmasto's own scanner). Each result is a finding with its rule, level, message, location, CWE
tags and the tool's name and version, kept in `security/<n>.json`; `security_scan` in the ledger
holds the counts by level, the tool and the file's sha256.

`kernel/security.py` holds the **security gate**. Each tool's latest scan counts; an open finding at
a blocking level (`error` by default) blocks. A person with the `it` or `compliance` persona may
accept a finding as a risk, with a reason and an expiry date; the acceptance follows the finding
into later scans and lets the gate pass until the date, when the finding opens again. With no scan
the gate says "not measured: no security scan", never "passed". The capability pack and the
evidence pack name the latest scan, its counts and the accepted risks.

## Not built yet (honest list)

- **A snapshot that follows its folder.** A folder that is not a git repository is adopted from a
  snapshot taken once; changes in the folder afterwards are not seen by `sync`. Adopt it again, or make
  the folder a git repository.

- **Delivering adopted code.** There is no paved road that knows how to run an adopted repository,
  so `run` stops before delivery. The kernel's surface on an adopted `main` gives a builder cell
  the paved road's write scope (`app/**`, `tests/**`); code the upstream keeps elsewhere is changed
  in a person's workspace.
- **Git LFS content.** The factory never downloads LFS objects, so an adopted repository that
  keeps files in Git LFS has only their pointer files in `repo.git`. Where the owner has git-lfs
  installed (with `filter.lfs.required`, its default), a lane or a workspace checkout of such a
  `main` stops at the smudge filter ("smudge filter lfs failed"): a builder cell or a workspace
  cannot work on it yet.
- **Other test runners in the gate.** The gate runs `python -m unittest discover -s tests`. An
  adopted pytest, npm, Go, Rust or Java suite is characterised at adoption, but a workspace
  submission on such a project is judged by the unittest runner only.
- **Ingesting and accepting from the CLI or cockpit.** SARIF ingestion and risk acceptance are
  kernel calls; the security gate is not yet consulted by delivery.
