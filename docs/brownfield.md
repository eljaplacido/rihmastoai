# Brownfield: existing solutions, a terminal beside the chat, and security findings

Rihma started greenfield: a need becomes a spec, a contract and a product. This page covers three
pieces that let it hold solutions that already exist, let a person work on them by hand, and take
security findings from any scanner. They follow the same rules of evidence: named verdicts, "not
measured" as a state, everything in the ledger, and people decide.

## Adopting an existing solution

```
python -m kernel.cli adopt "Legacy loans" --source <path or URL> --intent monitor|maintain|improve \
    --person Aino --persona developer [--base-url https://loans.example]
python -m kernel.cli sync <pid>
```

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
  Spring, Django and Rihma's own `@route`), scanned only when a `base_url` is given; whether there
  is a Dockerfile. Only regular files inside the checkout are read: a symlink is never followed,
  and a file name that is not UTF-8 is counted, not fatal. It is kept in `inventory.json`.
- **The work profile.** Proposed by rule from the title and the README, unless a person chose one.
  When the rule is not sure (one keyword, none, or two profiles close), the proposal is recorded as
  **uncertain**, with the candidates a person should choose from, in `profile_chosen`, in
  `adopted.json` and in the brief.
- **The characterisation baseline.** A detected Python suite runs once in a temporary checkout,
  with a timeout. Its counts are **existing behaviour, not a spec**: a suite that already fails is
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

- **Delivering adopted code.** There is no paved road that knows how to run an adopted repository,
  so `run` stops before delivery. The kernel's surface on an adopted `main` gives a builder cell
  the paved road's write scope (`app/**`, `tests/**`); code the upstream keeps elsewhere is changed
  in a person's workspace.
- **Git LFS content.** The factory never downloads LFS objects, so an adopted repository that
  keeps files in Git LFS has only their pointer files in `repo.git`. Where the owner has git-lfs
  installed (with `filter.lfs.required`, its default), a lane or a workspace checkout of such a
  `main` stops at the smudge filter ("smudge filter lfs failed"): a builder cell or a workspace
  cannot work on it yet.
- **Asking for the profile at intake.** An uncertain profile proposal is recorded at adoption and
  `kernel/profiles.py` holds the question for a person (`add_profile_question`), but intake does
  not ask it yet.
- **Other test runners in the gate.** The gate runs `python -m unittest discover -s tests`. An
  adopted pytest, npm, Go, Rust or Java suite is characterised at adoption, but a workspace
  submission on such a project is judged by the unittest runner only.
- **Ingesting and accepting from the CLI or cockpit.** SARIF ingestion and risk acceptance are
  kernel calls; the security gate is not yet consulted by delivery.
