# Code quality: the gate, the numbers, and what to fix

Status: 23 Nov 2026, task V-42, criterion FR-O8-AC-5. Code: `tools/quality.py`,
`tools/quality_baseline.json`, `tools/covered.py`, `tests/test_quality.py`.

This is a measurement, not a cleanup. Other work was in flight in `cockpit/**`, `kernel/cli.py`,
`kernel/dispatch.py`, `kernel/gate.py`, `kernel/spec.py`, `kernel/compile.py` and more, so
nothing outside the files above was changed. The fixes come later, in one pass. Every number
here was measured on this tree (base `b59f2f7` plus this change), on Windows, Python 3.14.7.

## 1. The gate

`tools/quality.py` is standard-library Python (`ast`, `tokenize`), with no model. It reads
`kernel/`, `adapters/`, `cockpit/server.py`, `embed/`, `mcp/`, `tools/` and `tests/` and reports,
per file and in total:

- unused imports, unused local variables (assignments, `except ... as`, loop variables), and
  names imported twice;
- annotation coverage: public functions and methods with every parameter and the return
  annotated;
- function length (over 60 lines is listed), cyclomatic complexity (over 15 is listed), and
  module size (over 500 lines is listed);
- duplicated function bodies: the same AST once the docstring is removed;
- bare `except:`, and `except Exception` with neither a comment nor a re-raise;
- `print()` in library code, mutable default arguments, TODO and FIXME markers;
- CR line endings and trailing whitespace;
- in `kernel/`, `adapters/`, `embed/` and `mcp/`: any import that leaves the standard library.

```bash
python tools/quality.py                    # the readable report (about 2 s)
python tools/quality.py --json             # everything, for tools
python tools/quality.py --gate             # exit 1 if a hard rule breaks or a count grows
python tools/quality.py --write-baseline   # record today's counts; review the diff
python tools/quality.py --prompts          # model-facing prompt sizes on a fake project
python tools/covered.py                    # line coverage without the coverage package
```

**Hard rules** fail the gate on any finding: a file that does not parse, a third-party import
in a runtime package, a bare `except:`, a mutable default, a CR line ending. All are at 0 today.

**The ratchet** holds every other count at or below its value in `tools/quality_baseline.json`.
A count that grows fails the gate. A count that falls is reported ("lower the baseline"), so the
fix and the lower baseline land in one commit. Unused imports were meant to be a hard rule, but
three exist in `tests/test_compile.py` and `tests/test_ledger.py`, which are outside this task's
write scope, so they are a ratchet at 3 until the fix pass. Length, complexity, size,
annotation and duplicate counts cover the code outside `tests/`, so a new test is never held to
them.

**ruff and mypy** are counted when the interpreter can import them, or when `RIHMA_QA_PYTHON`
names one that can (for example a throwaway venv). Their settings are fixed in the tool (ruff
`--isolated`, mypy with no config file), so a future `pyproject.toml` does not move the
baseline. They are held to the baseline only while the tool version matches the recorded one;
otherwise they read "not measured", and the stdlib rules still apply.

`tests/test_quality.py` runs the gate on this repository, and seeds each defect the gate exists
for (a third-party import, a bare except, a mutable default, a CRLF file, a count above its
baseline, a shadowed import, a duplicate helper) into a scratch tree to show the gate names it.

**After the parallel branches merge**, run `python tools/quality.py --gate`. New code from those
branches will raise some counts (new public functions without annotations, for example). Run
`--write-baseline` once, read the diff, and commit it with the merge. From then on the ratchet
only goes down.

## 2. Baseline

| Count | Today | Rule |
|---|---:|---|
| Files / lines | 92 / 19,636 (13,474 code, 6,162 tests) | |
| Functions | 1,121 | |
| Third-party imports in runtime packages | 0 | hard |
| Bare `except:` | 0 | hard |
| Mutable default arguments | 0 | hard |
| Files with CR line endings | 0 | hard |
| Unused imports | 3 (all in tests) | ratchet |
| Unused local variables | 1 (in a test) | ratchet |
| Names imported twice | 5 | ratchet |
| Broad excepts with no comment and no re-raise | 3 | ratchet |
| `print()` in library code | 0 | ratchet |
| TODO / FIXME | 0 | ratchet |
| Trailing whitespace lines | 0 | ratchet |
| Public functions not fully annotated (outside tests) | 256 of 530 | ratchet |
| Functions over 60 lines (outside tests) | 8 | ratchet |
| Functions over complexity 15 (outside tests) | 41 | ratchet |
| Modules over 500 lines (outside tests) | 4 | ratchet |
| Duplicated function bodies, extra copies (outside tests) | 6 | ratchet |
| ruff findings (E,F,W,B,I,UP,SIM; line 120) | 100 | ratchet, ruff 0.17.6 |
| mypy errors (non-strict, runtime packages) | 70 in 24 files | ratchet, mypy 2.4.1 |
| mypy `--strict` errors on `kernel/` | 836 in 41 files | ratchet when measured |

**Annotation coverage** (public functions and methods with full annotations):

| Package | Annotated | Coverage |
|---|---:|---:|
| `kernel/` | 163 / 369 | 44% |
| `adapters/` | 5 / 7 | 71% |
| `mcp/` | 22 / 29 | 76% |
| `embed/` | 0 / 3 | 0% |
| `cockpit/server.py` | 9 / 45 | 20% |
| `tools/` | 75 / 77 | 97% |
| **runtime packages** (kernel, adapters, embed, mcp) | **190 / 408** | **47%** |
| tests | 11 / 366 | 3% (not a goal) |

The least annotated: `kernel/roads.py` 26/79, `kernel/operate.py` 2/13, `kernel/ledger.py` 0/7,
`kernel/signals.py` 0/7, `kernel/dispatch.py` 0/6, `kernel/status.py` 0/5,
`kernel/observations.py` 0/4.

**Functions over 60 lines** (outside tests): `tools/contract_check.py:121 check` (181 lines,
complexity 84), `kernel/cli.py:69 main` (162, 28), `kernel/pipeline.py:43 _advance` (120, 41),
`kernel/change.py:219 apply_change` (86, 48), `kernel/intake.py:140 intake` (79, 31),
`kernel/dispatch.py:138 build_task` (77, 21), `embed/server.py:40 make_handler` (69, 2: a class
defined inside a function), `kernel/roads.py:937 validate_containerapp` (63, 47).

**The most complex** beyond those: `kernel/spec.py:161 normalize` (42),
`kernel/assistant.py:196 check_proposal` (36), `kernel/status.py:42 evidence` (32),
`kernel/insight.py:88 alignment` (31), `kernel/compile.py:250 author_holdouts` (30),
`kernel/embeds.py:154 converse` (30), `kernel/status.py:88 now` and `:194 health` (30 each).

**Modules over 500 lines:** `cockpit/server.py` 1,251; `kernel/roads.py` 1,135; `tools/quality.py`
1,041 (this tool, with its prompt-size mode; it can split once `tools/` may hold more files);
`mcp/server.py` 704.

## 3. Test coverage

Measured with coverage.py 7.17.4 (`python -m coverage run --source=kernel,adapters,embed,mcp,cockpit
-m unittest discover -s tests`): 272 tests in 179 s. Code that runs in a child process (a product
service started by a road, a CLI run through `subprocess`) is not counted, which is why the
road and CLI numbers understate what the tests exercise.

| Module | Statements | Missed | Cover |
|---|---:|---:|---:|
| `kernel/model.py` | 116 | 56 | **52%** |
| `kernel/cli.py` | 149 | 61 | **59%** |
| `embed/server.py` | 104 | 29 | 72% |
| `kernel/observations.py` | 75 | 19 | 75% |
| `kernel/filelock.py` | 37 | 9 | 76% |
| `kernel/roads.py` | 786 | 182 | 77% |
| `kernel/profiles.py` | 35 | 6 | 83% |
| `kernel/pipeline.py` | 115 | 18 | 84% |
| `kernel/change.py` | 181 | 28 | 85% |
| `kernel/intake.py` | 143 | 22 | 85% |
| `kernel/signals.py` | 144 | 21 | 85% |
| `mcp/server.py` | 435 | 65 | 85% |
| `kernel/dispatch.py` | 175 | 24 | 86% |
| `kernel/insight.py` | 82 | 10 | 88% |
| `kernel/assistant.py` | 182 | 21 | 88% |
| `kernel/dashboard.py` | 148 | 17 | 89% |
| `adapters/gnomon_ingest.py` | 131 | 15 | 89% |
| `kernel/operate.py` | 319 | 34 | 89% |
| `kernel/packs.py` | 80 | 8 | 90% |
| `kernel/canon.py` | 270 | 25 | 91% |
| `kernel/gate.py` | 161 | 15 | 91% |
| `kernel/doctor.py` | 102 | 9 | 91% |
| `kernel/evidence_pack.py`, `store.py`, `ledgerstore.py`, `rulings.py`, `verdicts.py` | | | 92% |
| `kernel/spec.py`, `embeds.py`, `status.py` | | | 93% |
| `kernel/deliver.py` | 342 | 20 | 94% |
| `kernel/plan.py`, `autonomy.py` | | | 96% |
| `kernel/ledger.py`, `compile.py`, `pricing.py` | | | 97% |
| `kernel/lanes.py` | 191 | 4 | 98% |
| `kernel/learn.py` | 96 | 1 | 99% |
| `adapters/gnomon_outcome.py`, `kernel/lenses.py`, `metrics.py`, `people.py`, `projections.py`, `safestop.py`, `scaffold.py`, `design_road.py` | | | 100% |
| **runtime packages** (kernel, adapters, embed, mcp) | **5,944** | **789** | **86.7%** |
| `cockpit/server.py` (for reference) | 839 | 91 | 89% |

**Under 70%:** `kernel/model.py` (the real Gnomon call path: `GnomonModel.ask`,
`run_gnomon_task`, `gnomon_cmd`; tests use `FakeModel`) and `kernel/cli.py` (most subcommands
are only run by hand). `run_gnomon_task` is where an apparatus failure is told apart from a
result (timeout, not startable, no JSON record), so it deserves tests with a fake `gnomon`
script on PATH before anything else.

**Without coverage.py**, `python tools/covered.py` does the same with `sys.monitoring` (Python
3.12+; `sys.settrace` on 3.11). Each line reports once and is then switched off, so the suite
runs at almost full speed. Measured on the same tree: 272 tests in 168 s (plain runs on this
machine took 211 to 215 s, so the overhead is inside the noise of other load), runtime packages
87.7%, and the same two modules under 70%. Per module it agrees with coverage.py within 3
points. It counts about 2% fewer statements, because a `try:` line has no instruction of its
own since Python 3.11 and so is not a statement to it.

## 4. Test-suite speed

262 tests ran in 211 s before this change (`python -m unittest discover -s tests --durations 15`).
The 15 slowest take 78 s, 37% of the run:

| s | Test |
|---:|---|
| 9.9 | `test_operate.CanaryTest` a healthy candidate is promoted |
| 9.3 | `test_operate.CanaryTest` a canary with more errors is rolled back |
| 7.1 | `test_plan.PlanTest` at pilot nothing is built until a person approves the plan |
| 5.6 | `test_operate.IncidentTest` a failing probe opens one incident per release and environment |
| 5.2 | `test_deliver.DeployGateTest` a gate on an old revision is withdrawn when main moves |
| 4.9 | `test_live.LiveTest` a pause stops at the next safe point |
| 4.2 | `test_operate.ShadowTest` shadow reports every differing response |
| 4.2 | `test_deliver.DeployGateTest` approve at the deploy gate lets the next deliver continue |
| 4.1 | `test_learn.LearnTest` each builder model's reliability comes from the ledgers |
| 4.1 | `test_operate.ShadowTest` shadow reports nothing when candidate and current agree |
| 4.0 | `test_mcp.CustodyTest` holdout content never reaches the client |
| 4.0 | `test_pipeline.PipelineTest` an idea goes to a built product |
| 3.9 | `test_deliver.DemoDeliveryTest` demo runs holdouts and waits for the business owner |
| 3.9 | `test_capability.PackTest` a release has a capability pack pinned by hash |
| 3.8 | `test_capability.ApparatusTest` an unreachable model stops the pipeline cleanly |

The time goes to real work, not sleeps: each local-road deploy starts a Python process and
polls `/health` every 0.1 s (`kernel/roads.py:164 wait_healthy`), and every compiled project
makes a bare git repository and clones it per lane. Cheap wins, in order:

1. Build the compiled project once per test class (`setUpClass`) where the tests only read it.
   The same `compiled()` helper (intake, spec, compile, git) is copied into four test classes
   (`test_change`, `test_dispatch`, `test_gate_rules`, `test_live`) and runs per test.
2. Cache the scaffolded bare repository per process (a template copied with `shutil.copytree`
   instead of `git init` + commit + push each time).
3. Mark the process-starting tests (canary, shadow, incident, deploy gate) as a slow tier, for
   example skipped unless `RIHMA_SLOW=1`, and run that tier in CI and before a release.

## 5. Findings, ranked

Ranked by what they cost the next person who reads or changes the code.

1. **Two definitions of "a person" disagree.** `kernel/people.py:17 is_person` and
   `tools/contract_check.py:82 _is_person` have the same body, but their `NOT_A_PERSON` sets
   differ: the kernel also refuses `assistant`, `bot`, `system` and `kernel`. So a contract
   whose customer-confirmed requirement is `decided_by: "kernel"` passes `contract_check`, the
   judge of every contract, while the kernel would never have written it. The tool stays
   standalone on purpose (it judges contracts without the kernel), so keep the copy, but give
   both the same set and add a test that they agree.

2. **Record shapes are implicit dictionaries.** Canon cards and questions, `tasks.json` task
   state, gate rounds, ledger payloads, release records, specs and contracts are `dict`
   literals built in one module and read by key in five others. mypy shows the cost: 23 of its
   70 errors are empty containers it cannot type (`var-annotated`), and most of the rest
   (`operator`, `arg-type`, `assignment`, `index`, `union-attr`) come from one dict literal
   holding values of several types. `kernel/pipeline.py:47 history` even mixes strings and
   dicts in one list. `TypedDict` fits these best, because the records are JSON on disk and stay
   dicts at runtime: `Card`, `Question`, `Assumption`, `TaskState`, `GateRound`, `LedgerRecord`
   (`seq`, `event`, `prev`, `hash`), `Release`, `Spec`, `Requirement`, `Criterion`. Use
   frozen dataclasses only for values that never touch disk (`Signal`, `GateResult` already are).

3. **Oversized modules and functions.** `kernel/roads.py` (1,135 lines, 102 functions, local,
   Docker and Azure Container Apps roads plus validation) wants to be a package:
   `roads/local.py`, `roads/docker.py`, `roads/azure.py`, `roads/validate.py`.
   `cockpit/server.py` (1,251 lines) mixes the HTTP handler, sign-in and 45 API methods; split
   the API by view. Inside functions: `kernel/cli.py:69 main` (162 lines) wants a table from
   subcommand to function; `kernel/change.py:219 apply_change` (complexity 48) one handler per
   change class; `kernel/pipeline.py:43 _advance` (complexity 41) one step function per stage;
   `tools/contract_check.py:121 check` (complexity 84) one function per section (requirements,
   plan, tasks, bans).

4. **Duplicated helpers.**
   - `_store(factory)` three times and `_factory(factory)` once, all `factory_project(factory)`:
     `kernel/autonomy.py:41`, `kernel/embeds.py:43`, `kernel/observations.py:31`,
     `kernel/signals.py:36`. One `Factory.store` property (or `kernel/learn.py`'s function,
     imported) replaces all four.
   - `_words` in `kernel/assistant.py:87` and `kernel/signals.py:76`: same body, but each reads
     its own `_WORD` and `_STOP`, so they behave differently. One `words(text, pattern, stop)`.
   - `_stamp` in `kernel/operate.py:38` and `stamp` in `kernel/roads.py:83`.
   - Criteria normalization twice: `kernel/spec.py:161 normalize` and `kernel/change.py:183
     _criteria` apply the same rules (ids from the requirement, `-` for an empty given or when,
     the kind fallback, at least one `test`). One `make_criteria(rid, items)`.
   - In tests: `compiled()` four times, and `setUp`/`tearDown` copies in `test_gnomon_066.py`
     and `test_doctor.py`; move them into `tests/factory_fakes.py`.

5. **Errors come in three families.** Refusals are `DecisionRefused(ValueError)` in the canon,
   `PermissionError` subclasses elsewhere (`AutonomyCapped`, `EmbedRefused`, and plain
   `PermissionError` in `kernel/change.py:228` and `kernel/compile.py:267`), and plain
   `ValueError` for "not a person" in `kernel/change.py:46`. "Not found" is a bare `KeyError`.
   The servers make up for it with catch-all tuples (`mcp/server.py:395` catches `OSError,
   ValueError, KeyError, TypeError, AttributeError`). The cockpit maps only `DecisionRefused` to
   403 (`cockpit/server.py:535`); a `PermissionError` refusal reaching a route becomes
   "internal error" 500. One `kernel/errors.py` with `RihmaError` and three children,
   `Refused` (403), `NotFound` (404) and `Invalid` (400), mapped once in each server, fixes it.

6. **Private names are used as module APIs.** `_ask_json` (from `kernel/intake.py`, used by
   `spec`, `change` and `compile`), `_git` (from `kernel/lanes.py`, used in four modules),
   `_ORIGIN` (`kernel/embeds.py`, used by `assistant`), `_main_test_names` (`kernel/insight.py`).
   `ask_json` belongs in `kernel/model.py` next to `extract_json`; `git` in a small
   `kernel/git.py`.

7. **Silent truncation of model context.** Intake cuts the request at 40,000 characters
   (`kernel/intake.py:49 MAX_SOURCE_CHARS`) and records nothing: the factory's own brief
   (42,910 characters) loses its last 2,910 without a trace. The assistant slices JSON text
   (`kernel/assistant.py:181`, `[:12000]` of the snapshot; `:149`, `[:3000]` of the layout), so the
   model can get a cut-off object. Record a "truncated" note on the canon, and trim lists
   before serializing.

8. **Coverage gaps on the apparatus.** `kernel/model.py` 52% and `kernel/cli.py` 59% (section 3).
   `kernel/filelock.py` 76% is the branch for the other operating system; that is expected and
   is better shown by running the suite on Linux too.

9. **Annotations are at 47% in the runtime packages**, and lowest where trust is decided:
   `kernel/ledger.py` 0/7 (the hash chain), `kernel/dispatch.py` 0/6, `kernel/status.py` 0/5.
   Section 6 has the staged plan.

10. **Three broad excepts carry no reason.** `kernel/deliver.py:345` (a step that raises becomes
    a failed outcome with its traceback), `kernel/ledger.py:147` (verification never raises; the
    docstring says so), `kernel/pipeline.py:134` (holdouts not authored are logged). Each is
    deliberate; each needs the one-line comment the other 17 carry.

11. **Kernel functions no code calls (in this tree).** Only tests call `autonomy.set_cap`,
    `dashboard.catalogue`, `embeds.revoke`, `embeds.snippet`, `lenses.project_context`,
    `observations.observe`, `observations.apply_updates`, `packs.render_yaml`,
    `roads.stop_started`, `roads.stop_all`, `signals.edit_concept` and `signals.apply_concepts`.
    The cockpit work in flight may wire them; check after the merge and remove what stays
    unwired. `FixedClock`, a test helper, lives in `kernel/store.py`.

12. **`Project.meta` reads `project.json` on every access** (`kernel/store.py:116`). Functions
    read `project.meta[...]` several times, so each is a disk read and the values can change
    between two reads in one function. Read it once per function (`meta = project.meta`), as
    most already do.

13. **Small hygiene.** Unused imports `tests/test_compile.py:12 Canon`, `:13 check_plan`,
    `tests/test_ledger.py:4 math`; unused variable `tests/test_compile.py:161 check_plan_rows`;
    the same import twice in `kernel/cli.py:148` and `:180` (each branch of `main` imports
    again), `kernel/dashboard.py:195`, `tests/test_compile.py:238`, `tests/test_ledger.py:185`.
    From ruff: a duplicate `"an"` in the stopwords at `kernel/learn.py:27`; an unused loop
    variable at `cockpit/server.py:522`; `zip()` without `strict=` at `kernel/operate.py:253`;
    five `raise` inside `except` without `from` in `kernel/roads.py`.

14. **Naming.** The working name survives on purpose in file formats (`gnomonfactory.contract/1`)
    and `GNOMONFACTORY_HOME`, but the lane variables are `GF_LANES` and `GF_LANES_SIZE` and
    temporary directories start with `gf-`. Add `RIHMA_LANES` with `GF_LANES` as the fallback,
    the way `RIHMA_HOME` was done.

## 6. ruff and mypy

The owner allowed ruff 0.17.6, mypy 2.4.1 and coverage 7.17.4 in a throwaway venv, for
measurement only. Nothing was installed into the repository.

**ruff** (`E,F,W,B,I,UP,SIM`, line length 120, Python 3.11) finds 100: 67 `E501` long lines (13
in `kernel/design_road.py` and 10 in `kernel/profiles.py`, which hold prose), 5 each of
`SIM105`, `I001`, `UP037` and `B904`, 3 `UP031`, 3 `E741` (a variable named `l`), and single
`B007`, `B033`, `B905`, `SIM102`, `SIM201`, `UP034`, `UP017`. No `F` code in the runtime packages:
no unused import and no undefined name. On `tests/` ruff adds 56, 44 of them `E501`, and the
same unused imports `tools/quality.py` lists.

**mypy, non-strict** (runtime packages, Python 3.11): 70 errors in 24 files. Classified by
reading each one:

| Class | Errors | Examples |
|---|---:|---|
| Missing annotations | 24 | 23 empty containers such as `out = []` (`var-annotated`); `mcp/server.py:300`, an attribute first set to `None` |
| Heterogeneous dict literals (a `TypedDict` would type them) | 27 | `kernel/pipeline.py:107` appends a dict to a list of strings; `kernel/observations.py:74`, `kernel/lenses.py:66`, `kernel/signals.py:175`, `kernel/roads.py:308`, `kernel/gate.py:152`, `kernel/status.py:156`, `kernel/embeds.py:186`, `mcp/server.py:226` |
| Optional and union handling mypy cannot follow | 13 | `kernel/dispatch.py:182` (`record` is set because the loop runs at least once), `kernel/operate.py:336` (`cur` is set whenever `records` is), `kernel/embeds.py:176`, `mcp/server.py:617`, `adapters/gnomon_ingest.py:82` (NaN and infinity return earlier), `kernel/intake.py:137` (`raise last` with `last` still `None` only if `retries < 0`) |
| Platform branches | 6 | `kernel/filelock.py:12-20` (`fcntl` on Windows), `kernel/roads.py:459` (`signal.SIGKILL`, guarded by `os.name == "nt"`, which mypy does not read; `sys.platform` it does) |

**Real bugs: none found that crash today.** The closest are the person check that disagrees with
itself (finding 1) and `raise last` in `kernel/intake.py:137`, which raises `TypeError` instead
of `ModelError` if anyone ever passes `retries=-1`. `adapters/gnomon_ingest.py:82` looked like a
`str + int` crash, but NaN and infinity return before it.

**mypy `--strict` on `kernel/`**: 836 errors in 41 files: 319 `type-arg` (bare `dict` and `list`
in annotations), 288 `no-untyped-def`, 120 `no-untyped-call`, 40 `no-any-return`, and the 70
above. `kernel/roads.py` alone has 143. With `--check-untyped-defs` the non-strict count only
moves from 70 to 73, so checking the bodies of unannotated functions is cheap to turn on.

**What they add over `tools/quality.py`:** import sorting, line length, modern-syntax and
simplification rules, `raise ... from` (ruff); and actual type checking of calls, returns and
`None` handling (mypy). The stdlib tool keeps working where neither is installed, and owns the
Rihma-specific rules (stdlib-only runtime, duplicate bodies, ratchet).

### Recommended configuration

For the `pyproject.toml` another task creates. The gate keeps its own fixed flags, so adopting
this does not move the baseline.

```toml
[tool.ruff]
target-version = "py311"
line-length = 120
extend-exclude = ["blueprint", "specs", "upstream", "envelopes", "evidence", "var", "tests/fixtures"]

[tool.ruff.lint]
select = ["E", "F", "W", "B", "I", "UP", "SIM", "C90"]

[tool.ruff.lint.mccabe]
max-complexity = 15                  # the same threshold as tools/quality.py

[tool.ruff.lint.isort]
known-first-party = ["kernel", "adapters", "cockpit", "embed", "mcp", "tools"]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["E402"]                 # tests put tests/ on sys.path before importing the fakes
"kernel/design_road.py" = ["E501"]   # prose: the paved road's design text
"kernel/profiles.py" = ["E501"]

[tool.mypy]
python_version = "3.11"
files = ["kernel", "adapters", "embed", "mcp", "tools"]
ignore_missing_imports = true        # nothing third-party; this silences the tests' sys.path helpers
check_untyped_defs = true
warn_unused_ignores = true
warn_redundant_casts = true
show_error_codes = true

# Stage 2 onward: strict, module by module. `strict` itself is global-only in mypy, so the
# flags it sets are listed. Add a module here when it reaches zero errors.
[[tool.mypy.overrides]]
module = ["kernel.verdicts", "kernel.ledger", "kernel.ledgerstore", "kernel.canon", "kernel.store", "kernel.people"]
disallow_untyped_defs = true
disallow_incomplete_defs = true
disallow_untyped_calls = true
disallow_any_generics = true
warn_return_any = true
strict_equality = true
```

### A staged plan for typing

1. **Non-strict at zero.** Annotate the 24, write `TypedDict`s for the records in finding 2
   (the 27), narrow the 13 Optional cases with an early return or an `assert`, and use
   `sys.platform` for the 6 platform branches. That clears the 70 (73 with
   `check_untyped_defs`). Then lower `mypy_errors` in the baseline to 0, which makes it a hard
   line.
2. **Strict on the trust core:** `kernel/verdicts.py` (already clean), `kernel/ledger.py` (9
   errors), `kernel/ledgerstore.py` (9), `kernel/store.py` (16), `kernel/canon.py` (44, mostly
   bare `dict`). 79 errors in all, about a day. These decide what is recorded and who decided.
3. **Strict on the deciders:** `gate`, `verdicts`, `compile`, `spec`, `change`, `plan`,
   `rulings`: the modules that turn evidence into verdicts.
4. **Strict on the rest of `kernel/`**, then `adapters/`, `mcp/`, `embed/`; `kernel/roads.py`
   last, after it is split (finding 3).

Each stage ends with its count at 0 in the baseline, so it cannot come back.

## 7. Prompts and context

Measured with `python tools/quality.py --prompts`, which builds the "Equipment loans" project
with `tests/factory_fakes.py` (demo maturity, assume mode, a one-sentence request) and renders
every model-facing text. Tokens are approximated as characters / 4. "Before" is commit `fc5bbe8`;
"after" is task V-53 (FR-Z1), which applied P1, P2, P3, P5 and P7 below.

| Prompt | Where | Before | After | ~Tokens after |
|---|---|---:|---:|---:|
| Gnomon `init` system prompt (prefix of the product lane) | `.gnomon/system.md` | 2,832 | 2,832 | 708 |
| Analyst lane `system.md` | `kernel/lanes.py` `analyst_system_md()` | 3,140 | 594¹ | 148 |
| Product lane `system.md` (init + `PRODUCT_RULES`) | `kernel/lanes.py` `product_system_md()` | 3,669 | 3,324 | 831 |
| The factory's own `system.md` | `.gnomon/system.md` | 4,307 | 4,307 | 1,077 |
| Tool descriptions, all declared | `.gnomon/tools.toml` | 1,628 | 1,628 | 407 |
| `[turn] continue_message` | `.gnomon/config.toml` | 362 | 362 | 90 |
| Intake perspective (each of five) | `kernel/intake.py` | 1,292–1,404 | 1,223–1,335 | 306–334 |
| … the prefix the five share, word for word | `kernel/intake.py` `_panel_prefix` | 14 | 987 | 247 |
| Intake opinions | `kernel/intake.py` | 1,048 | 1,048 | 262 |
| Spec | `kernel/spec.py` | 3,623 | 3,623 | 906 |
| Spec, redrafted after a rejected plan | `kernel/spec.py` | 4,027 | 4,027 | 1,007 |
| Holdout scenarios | `kernel/compile.py` | 2,200 | 2,200 | 550 |
| Builder envelope, T-001 | `kernel/dispatch.py` | 2,277 | 2,277 | 569 |
| Builder envelope, a repair round | `kernel/dispatch.py` | 2,404 | 2,404 | 601 |
| Verifier | `kernel/gate.py` | 914 | 914 | 228 |
| Triage | `kernel/change.py` | 1,192 | 1,192 | 298 |
| Amend | `kernel/change.py` | 1,461 | 1,461 | 365 |
| Cockpit assistant | `kernel/assistant.py` | 6,727 | 6,799 | 1,700 |
| Cockpit assistant, with a layout | `kernel/assistant.py` | 7,594 | 7,667 | 1,917 |
| … the prefix two assistant calls share² | `kernel/assistant.py` `_catalogue` | 542 | 5,673 | 1,418 |
| Embed reply | `kernel/embeds.py` | 1,027 | 1,027 | 257 |
| Signal concept | `kernel/signals.py` | 513 | 513 | 128 |

¹ `tools/quality.py --prompts` still prints 3,426 for this row: it measures
`scaffold_system_md() + ANALYST_RULES`, and `ANALYST_RULES` is now the whole file. 594 is
`lanes.analyst_system_md()`, which is what `ensure_analyst_lane` writes. The tool needs a one-line
change (measure `lanes.analyst_system_md()` and `lanes.product_system_md()`); `tools/` was outside
task V-53's scope.
² Two calls on the same project, by a product owner and a developer, with different questions.
Before, they parted at the persona line; now everything up to it is the same.

The assistant grew by 72 characters: one rule line says what `not_shown` means. Its snapshot is
now fitted to 12,000 characters by dropping whole items (P5), so on a large factory it can
be shorter than before, and it is always valid JSON.

**With a real document.** The same intake on the factory's own brief
(`intake/gnomon-factory-brief.md`, 42,902 characters in 42,910 bytes) sends five perspective
prompts of 41,238–41,377 characters: 206,576 in all, about 51,600 tokens. They used to share 14
characters; now they share 41,001, 99% of each prompt, so an endpoint that caches prompt prefixes
(llama-server's prompt cache, cloud prompt caching) can reuse about 10,250 tokens of prefill in
four of the five calls, roughly 41,000 tokens per intake. The brief is longer than
`MAX_SOURCE_CHARS`, and the cut is no longer silent: each prompt says "(The request was cut at
40,000 of 42,902 characters: the rest is not shown.)", the ledger records `request_cut`
(`{"kind", "kept", "of"}`), `source.json` keeps `cut_from`, and the brief's source line says how
much the panel read.

**Per project.** From the one-sentence request to holdouts, the analyst lane makes 8 calls
(5 perspectives, opinions, spec, holdouts). Their system prompts drop from 25,120 to 4,752
characters and their prompts from 13,557 to 13,212: the analyst lane's input falls from 38,677 to
17,964 characters, 54% less. The system prompt was two thirds of what the analyst read; it is now
a quarter. Every assistant call reads 2,546 fewer characters of system prompt, and every builder
and verifier call 345 fewer.

### What the review found

- **Fixed (P1): the analyst lane's system prompt contradicted its role.** It was Gnomon's `init`
  prompt verbatim, then "you do not need tools". The `init` part says to use the declared tools,
  to do arithmetic through `compute`, that a reply with no tool call ends the turn, and to run
  what you produced before ending. The analyst, holdout-author and assistant roles have
  `tools = []`. They now read a short prompt of their own.
- **Fixed (P3): the verifier read builder rules.** The product lane has one `system.md` for both
  roles, and `PRODUCT_RULES` told every reader to write a failing test first and to run
  `python3 -m unittest` with bash; the verifier has neither write nor bash, and its own prompt
  says "run nothing else". `PRODUCT_RULES` is now role-neutral: the read-only paths, writing only
  inside the task's paths (none for a task that names none), and LF line endings.
- **Fixed (P3): the builder read its rules twice.** `PRODUCT_RULES` and the envelope's "Rules" and
  "Report" sections repeated the test-first naming rule, the unittest command, "standard library
  only" and the report. Each is now said once, in the envelope.
- **Fixed (P2): the five perspective prompts shared no prefix.** Each started "You are the
  **business** perspective…", so the identical request sat after a different first line in every
  call.
- **Open (P4): the holdout prompt explains `{{prev.<key>}}` three times.**
- **Fixed (P5): the assistant prompt put the persona line before its static catalogue** of views,
  controls and actions, which broke the same prefix reuse, and sliced the snapshot JSON
  mid-object. It also sliced the person's layout at 3,000 characters; a layout that large is now
  named as not shown. With P7 this closes finding 7 in section 5 (silent truncation of model
  context), whose text predates the fix.
- **Open (P6): triage asks for the regression as prose** ("as given / when / then" inside a
  string), but `kernel/change.py:237` wants an object with `given`, `when` and `then`; a string
  lands whole in `then` with `-` for the others.
- **Open, found while fixing P3: the verifier prompt asks for `git diff`,** "Compare it with the
  base revision (`git diff <base> -- app tests`)", but the verifier role has `read`, `glob` and
  `grep` only, and the same prompt says "run nothing else". It should say which files changed
  (the gate knows) instead of naming a command the role cannot run. `kernel/gate.py`.
- The spec, embed, signal, verifier and amend prompts are otherwise compact. `.gnomon/system.md`
  (the factory's own) repeats the report rule of the `init` part once; that is all.

### Applied in task V-53 (FR-Z1)

**P1. The analyst lane has its own short system prompt** (`kernel/lanes.py` `ANALYST_RULES`,
written whole by `ensure_analyst_lane`): what the lane does, answer only from the task, say what
is missing rather than invent it, one JSON value in a fenced block when asked, no tools. The
product lanes keep Gnomon's `init` prompt. FR-Z1-AC-1.

**P2. One shared prefix for the five perspectives** (`kernel/intake.py` `_panel_prefix`): the
request verbatim, the maturity, the instructions and the answer's shape come first, word for
word; "You are the **{perspective}** perspective on a panel…" and the profile's focus come last,
next to the answer. FR-Z1-AC-3.

**P3. A role-neutral product `system.md`** (`kernel/lanes.py` `PRODUCT_RULES`). Every safety rule
stays; the builder's rules are in its envelope only. The proposal's other half, the example test
name in the envelope, is not applied: the envelope already gives the pattern
`test_<ID with hyphens as underscores>_...`, and `kernel/dispatch.py` was outside the task's
scope. FR-Z1-AC-2.

**P5. The assistant's static catalogue first, the snapshot last** (`kernel/assistant.py`):
the rules, views, controls, actions and the answer's shape (`_catalogue`), then the widget
library when the cockpit may be reshaped, then who is asking, their layout, the map hints and the
question, and the snapshot as the last block. `fit_snapshot` keeps it within `SNAPSHOT_BUDGET`
(12,000 characters of JSON): at most 10 open cards and 6 open questions as before, then whole
items from the end of the factory's project list, the tasks, the questions and the cards, then
whole sections (live, gates, waiting, health), and a single record too large on its own replaces
the snapshot with a note. Its `not_shown` names each cut, such as "20 of 30 open cards".
FR-Z1-AC-4.

**P7. A cut request says so,** in the prompt, the ledger, `source.json` and the brief (above).
FR-Z1-AC-3.

**When the new system prompts take effect.** The analyst lane's `system.md` is rewritten every
time `ensure_analyst_lane` runs, so the next intake, spec, holdout or assistant call reads it. A
product compiled before V-53 keeps its committed `.gnomon/system.md` until its surface is
recompiled (`kernel/compile.py` `update_repo_surface`, which commits it and records
`surface_updated`). Either change alters that lane's Gnomon surface hash; the lanes run without a
trust grant by design, so nothing breaks, but an owner who had trusted a lane would have to trust
it again.

### Still proposed (prompt changes go through the owner's review)

**P4. The holdout prompt says `{{prev.<key>}}` once.** Saves about 150 characters.

```diff
--- a/kernel/compile.py
+++ b/kernel/compile.py
@@ def holdout_prompt
 The product's HTTP interface, fixed by the spec. Use exactly these methods and paths; a value
-in braces, such as {{id}}, comes from an earlier step's response through {{{{prev.<key>}}}}:
+in braces, such as {{id}}, comes from the previous step's JSON response as {{{{prev.<key>}}}},
+in a path or a body:
@@
 - max_ms: an optional latency limit, for probes.
-
-A step may use "{{{{prev.<key>}}}}" in its path or body to reuse a value from the previous
-step's JSON response, for example an id.
```

**P6. Triage asks for the regression as an object** (a behaviour change; the owner decides):

```diff
--- a/kernel/change.py
+++ b/kernel/change.py
@@ def triage_prompt
-  "summary": "one sentence", "regression": "for a defect: the observable behaviour a regression test
-  must check, as given / when / then"}}]}}
+  "summary": "one sentence", "regression": {{"given": "...", "when": "...", "then": "..."}}}}]}}
+For a defect, "regression" is the observable behaviour a regression test must check; otherwise null.
```

**P8. The verifier is told which files changed,** instead of a `git diff` it cannot run
(`kernel/gate.py` `verifier_prompt`; the finding above).

**P9. `tools/quality.py --prompts` measures the files the lanes write:** `lanes.analyst_system_md()`
and `lanes.product_system_md()` in place of `init + ANALYST_RULES` and `init + PRODUCT_RULES`, and
a row for the prefix the five perspectives share.

## 8. Language choices

**Standard-library Python for the kernel fits, and should stay.** The kernel's job is to be the
part that can be trusted: it decides verdicts, keeps the hash chain and judges contracts. With no
dependencies there is no supply chain to audit, nothing to pin, and nothing that changes under a
release; the product scaffold makes the same promise to every product. It runs unchanged on
Linux, WSL2 and Windows (the `gitattributes` LF rule and `kernel/filelock.py` show the cost is
small). Python 3.11 is the documented floor; keep it, and run the suite on 3.11 now and then:
this machine runs 3.14, and a 3.12-only API would otherwise go unnoticed (mypy with
`python_version = "3.11"` catches most of them).

What to add, all optional and outside the runtime: ruff and mypy as development tools (section 6),
and `TypedDict` for the records (finding 2), which costs nothing at runtime. What not to add:
a web framework for the cockpit, an ORM over the JSON files, or pydantic for validation. Each
would make the factory depend on what it is meant to judge.

**Vanilla JavaScript for the cockpit fits an open-source project of this kind**, with one
condition. No build step means anyone can read and change the page the server sends, the
cockpit ships in the same repository with no `node_modules`, and the loopback-only, one-use
sign-in design stays simple to audit. The condition is structure: the cockpit is large enough
that it needs modules (`<script type="module">`, one file per view), JSDoc types checked by
`tsc --checkJs --noEmit` if the owner allows that one development tool, and the same
`ui_map.json` contract the assistant already reads. Keep no framework and no bundler.

**Keep:** the stdlib-only runtime, `unittest` (pytest can still run the suite unchanged), JSON
files written atomically with LF, named verdicts, "not measured" as an honest result, and tests
named by criterion id. **Change:** typed records, a shared error hierarchy, smaller modules, and
the gate in this document as the line no change crosses.
