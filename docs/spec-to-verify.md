# Spec to verify: how a requirement becomes something Gnomon enforces

Status: design proposal, 22 Nov 2026.
Grounded in Gnomon `master` at `fb458ea` (22 Nov 2026), whose `[verify]` keys v0.6.6 released
the same day. Rihma needs Gnomon 0.6.5 or later; 0.6.6 recommended
([gnomon-0.6.6-audit.md](gnomon-0.6.6-audit.md)).

A specification in prose cannot stop anything. Rihma turns it into a chain of
artifacts, and each link is enforced by code, not by a model's good intentions:

```
vague idea ─▶ requirements spec ─▶ contract ─▶ check plan ─▶ envelopes ─▶ Gnomon surface
                (intake)          (compiled)  (+ holdouts)  (per task)    (compiled)
                                                                              │
     gate ◀── kernel trace ◀── gnomon check ◀── end-of-turn verify ◀── pre-tool rules
 (warranted +   (per criterion)  (independent,   (inside the run)       (inside the run)
  permitted)                      base rules)
```

Solution Factory produces the first link. Every link after it is native to Rihma
and enforced by Gnomon or by the kernel.

## The links, one by one

### 1. Intake: from a vague explanation to a requirements spec

| | |
|---|---|
| Input | Meeting notes, a brief, a concept package, a change request |
| Output | `spec.md`, `constitution.md`, `tasks.md`, `traceability.md` (Spec Kit layout) |
| Today | Solution Factory: Cynefin triage, Socratic questions whose answers become requirements, refusing Disorder |
| Later | The factory's own intake, modelled on Solution Factory and xlat, with answers signed in the Inbox so each requirement records who confirmed it |
| Enforced by | Nothing yet. Prose is a proposal until the next link compiles it. |

Solution Factory's traceability maps requirements to tasks. It has no criterion-to-test
link, and that link is what enforcement needs.

### 2. Contract: the spec compiled into something checkable

A deterministic compiler, with no model inside, reads the spec and the decisions log and
writes `contract/contract.json`. The contract is content-hashed, and the hash is its
revision.

```yaml
# contract/contract.json, shown as YAML for reading
contract: energy-reports
revision: sha256:4be1…            # hash of the canonical contract
requirements:
  - id: REQ-014
    statement: Daily totals are grouped by local calendar day.
    provenance: customer-confirmed      # customer-confirmed | customer-endorsed | vendor-proposed | assumption | withdrawn
    decided_by: product-owner
    decided_on: 2026-10-02
    acceptance:
      - id: REQ-014-AC-2
        given: a meter in Europe/Helsinki with readings across 27 Oct 2026
        when:  the daily report runs
        then:  27 Oct has 25 hourly buckets and its total equals the sum of those buckets
        check: { kind: test }                       # test | holdout | browser_walk | probe | signed_manual
        must_differ_on: [{tz: Europe/Helsinki, day: 2026-10-27}, {tz: UTC, day: 2026-10-27}]
      - id: REQ-014-AC-4
        then:  exported totals equal report totals for every day of the month
        check: { kind: holdout, scenario: H-11 }
bans:
  - form: "approximately"
    scope: report-totals
    reason: totals are exact by contract
nfr:
  - id: NFR-7
    statement: the report renders within 2 s for 10,000 meters
    check: { kind: probe, command: "k6 run perf/report.js", threshold: "p95<2000" }
```

Compiler rules. Each one fails loudly, with file, line, expected and got:

- Every customer-confirmed or customer-endorsed criterion has at least one check. A
  criterion that cannot be tested needs a signed entry in `verification_plan.json`.
- Every criterion traces to at least one task, and every task traces to a criterion.
- `must_differ_on` gives an input pair whose outputs must differ. A test that passes on
  both inputs does not prove the criterion.
- Counts are recomputed, never copied. Unknown keys are rejected.
- The contract changes only through an amendment approved in the Inbox. It is never
  edited by a cell (see link 6).

### 3. Check plan and holdouts

The check plan says which check proves which criterion. Checks come in two kinds, kept in
different custody:

- **Visible checks.** These are tests in the product repository. Builders write them,
  and the kernel verifies that they ran and failed first. Each test names its criterion,
  for example `test_REQ_014_AC_2_fall_back_day_has_25_buckets` or a marker such as
  `@pytest.mark.ac("REQ-014-AC-2")`.
- **Holdout checks.** These are scenarios written outside the build by the requirement
  owner or a verifier. They are stored outside the product repository, so they never
  enter a builder's worktree. Only the verifier role and staging receive them.

### 4. Envelopes: one per unit of work

The kernel writes one envelope per task. The envelope is the Gnomon task file.

```yaml
envelope: WI-88
contract_revision: sha256:4be1…
base_revision: 3e9a1c0
role: builder
goal: Group daily totals by local calendar day across clock changes.
criteria: [REQ-014-AC-1, REQ-014-AC-2, REQ-014-AC-3]
scope:
  write: ["src/reports/**", "tests/reports/**"]
  read:  ["src/**", "tests/**", "contract/contract.json"]
budget: { tokens_in: 400000, wall_seconds: 900, steps: 60 }
stop: all listed criteria have a passing test that failed on base_revision
evidence_required: [junit, worktree_diff, verify_record]
parent: null
```

Nested envelopes inherit every limit and may only narrow them.

### 5. Gnomon surface: compiled from contract, check plan and envelope

The kernel compiles the rules into `.gnomon/` in the cell's worktree. Gnomon hashes the
surface, and the hash is stamped on every record, so the rules a change was built under
are provable afterwards.

```toml
# .gnomon/policy.toml (compiled; content-hashed by Gnomon)
[verify]
command = "pytest -q --junitxml=.verify/junit.xml"
contract = "pytest"                  # exit 2, 4, 5 are unrunnable: nothing measured is not a failure
after = "change"
max_rounds = 2
test_must_fail_first = true          # a new test must fail on the code as it was
protects = ["@detected"]             # a green check over an edited conftest/pyproject is passed_unverified
exit_on_fail = true                  # failed, regressed or passed_unverified exits 1; unrunnable exits 4
record_detail = true                 # verify_exit, verify_rounds, verify_reason, verify_tail on the record
timeout_seconds = 900
setup = "uv sync --frozen"           # runs before the model's first call; the model cannot change it
finish_gate = "v2"

[governance]
level = "prevent"
secrets = "enforce"
ci = "enforce"

[governance.paths]                   # each list replaces its default, so the defaults are repeated
ci = [".github/workflows/**", ".github/actions/**", ".gitlab-ci.yml",
      "contract/**", "specs/**", "verification_plan.json"]   # write-protected; reads stay allowed
```

```toml
# .gnomon/roles.toml (compiled)
[roles.builder]
tools = ["read", "grep", "glob", "write", "edit", "bash"]
write_allow = ["src/reports/**", "tests/reports/**"]       # from the envelope's scope
model = "qwen3.6-35b"
escalate = "deepseek-v4-pro"

[roles.verifier]
tools = ["read", "grep", "glob", "bash"]                   # no write, no edit
bash_allow = ["^pytest\\b", "^npx playwright test\\b"]
model = "glm-5.3"                                          # a different model from the builder
```

### 6. Enforcement points

| When | Mechanism | What it stops | Gnomon `fb458ea` |
|---|---|---|---|
| Every tool call | `write_allow`, sandbox, `[governance]` families | Writing outside the envelope's scope, editing the contract, specs or CI, reading secrets | Exists |
| Every tool call | `[governance.paths] ci` list extended with `contract/**`, `specs/**` | A cell weakening the spec it is judged against | Exists (custom list) |
| End of turn | `[verify]` with a `contract` preset and `exit_map` | Calling "nothing measured" a failure, or a failure a pass. Only exit 0 passes. | Exists |
| End of turn | `test_must_fail_first` | A test that already passed before the change counted as proof | Exists |
| End of turn | `protects` → `passed_unverified` | A green check produced by editing the check's own configuration | Exists |
| End of turn | `finish_gate = "v2"`, or a read-only reviewer | Declaring done while the answer itself names an open defect | Exists |
| Exit | `exit_on_fail` / `--require-verify` | A failed check hiding behind exit 0 | Exists (opt-in) |
| After the run | `gnomon check --base <rev> --role builder --json` | A change judged by rules it widened. The rules come from the base revision, and a head cannot widen or empty them. | Exists |
| After the run | Kernel criterion trace: junit at head and at base | A criterion with no executed test, or a test that did not fail first, per criterion | Kernel, new |
| Staging | Verifier runs holdouts | Code that passes its own tests but not the requirement owner's scenarios | Kernel, new; custody, not Gnomon |
| Gate | Two signals bound to revision hash and surface hash | Anything without both evidence and permission | Kernel, new |

### 7. Criterion-level evidence: what turns a criterion green

A criterion is **verified** only when all of these hold. No model's statement can satisfy
any of them:

1. A test that names the criterion appears in the junit report at the head revision, and
   it passed.
2. The same test failed at `base_revision`, or the criterion is new and the test did not
   exist there. The kernel re-runs this itself.
3. Gnomon's `verify` for the run is `passed`, not `passed_unverified`.
4. `gnomon check` exits 0 for the change.
5. For a `holdout` criterion, the verifier's run of the scenario passed on the same
   revision.
6. For a `must_differ_on` criterion, the test was observed to produce different results
   on the two inputs.

Anything less is reported honestly:

- **evidenced:** the test exists but was not observed running here;
- **declared:** a cell says so;
- **not measured:** the check could not run;
- **failed.**

These states feed the Evidence view directly.

### 8. Contract change control

- `contract/**` and `specs/**` are write-protected for every role through
  `[governance.paths]`. Gnomon refuses the edit before it happens.
- An amendment is proposed as an artifact, by a triager or by a person. It becomes a new
  contract revision only after a signed Inbox decision. The kernel then recompiles the
  surfaces and reopens exactly the tasks whose criteria changed.
- `.gnomon/` itself is protected by Gnomon's surface rule. `gnomon check` always judges by
  the base revision's surface.

### 9. Fixes from the live runs (23 Nov 2026)

Live runs found four places where the chain let a wrong thing through. Each is now closed by a
mechanism, not a prompt alone (FR-DF1 to FR-DF4); all of it is built and covered by
`tests/test_dogfood_fix.py`.

| Link | What went wrong | What enforces it now |
|---|---|---|
| Spec | The analyst wrote "localhost-only", which contradicts the paved road | The spec prompt states the road's platform facts ([paved-roads.md](paved-roads.md#the-roads-platform-facts)); the plan review names every requirement that contradicts them, by rule and clause by clause, in their common phrasings ("only accessible from localhost", "Set HOST to 127.0.0.1", "/health must not disclose the version"), and the plan then waits for a person at any maturity |
| Spec | The profile was proposed from words inside other words, and the spec was written on the rule's guess while the profile question was open | Keywords match on word boundaries; the profile question blocks the spec in every mode, and an answer that arrives after a spec never changes the profile silently ([guides/profiles.md](guides/profiles.md)) |
| Build | The builder bound 127.0.0.1 and replaced `/health`; every test passed | The envelope states the facts; the template's `tests/test_road_contract.py` checks them in the product's own suite, and it is a protected path the gate refuses a change to |
| Delivery | The failed health check left `"logs": ""` | The release record keeps the container's log tail from both streams, its listening sockets and a diagnosis |
| Holdouts | A scenario could not sign a request the spec requires signed | A step's `sign` names a secret of the environment's settings; the runner signs the exact body with HMAC-SHA256; no scenario holds a value, and custody is unchanged. A `sign` with a transport header (`Host`, `Content-Length`) or a prefix holding a line break is refused before anything is sent, and a scenario the runner cannot send is not measured while the others still run |
| Change loop | A defect whose triage named no requirement got its regression criterion on R-1 | No default: a question card asks which requirement it breaks; until a person says, the change is not applied; an answer naming none, or an accept naming none, files a new requirement through the business decision; a product-defect ruling's requirement is taken as it is |

Still to come: the docker road passing a secret's value to the product's container, and the
pipeline showing the defect's question as what a hand-off waits on (today it reports the change
as not applied, naming the question).

## What Gnomon needs upstream for this chain

Several gaps listed earlier are already closed on `master`, and released in v0.6.6:

- A failed check can now set the exit, through `--require-verify` / `exit_on_fail`.
- Nothing-measured outcomes no longer count as failures (verify `contract` / `exit_map`).
- A cell can no longer weaken its own check unnoticed (`protects`).
- `gnomon doctor verify` detects suites that ran no tests.

Still needed:

1. **Per-run write scope.** A `--write-allow <glob>` flag, or envelope front matter, that
   can only narrow the role's scope. Gnomon would record it in the task record, and
   `gnomon check` would enforce it. Until then, the kernel compiles one role per envelope,
   which changes the surface hash per task.
2. **A holdout path family.** A path family that is read-protected per role: the builder
   is refused and the verifier is allowed. Until then, custody does the job: holdouts
   never enter a builder's worktree.
3. **A per-test verify report.** `[verify] report = "junit:<path>"` would put the report's
   hash and per-test outcomes in the task record. The evidence would then be observed by
   the harness rather than parsed from a file the cell could have written.
4. **Must-fail-first per test id,** not only per command. That gives fail-first per
   criterion. The kernel can do this meanwhile.
5. **Could-not-measure and request-evidence outcomes** in policy decisions, following the
   rules of evidence.
6. **Shell-effect classification,** so approvals are not asked for read-only commands.
7. **Per-rule governance levels,** so new gate rules move from shadow to enforce one at a
   time.
8. **An event export** the factory ledger can ingest directly, with OpenTelemetry as an
   option.

## Where Solution Factory fits

Solution Factory produces link 1 for this project now. For the factory as a product, it
is the model for the factory's own intake: turning a vague explanation into a spec through
classification and guided questions.

The contract compiler, the check plan and the surface compiler are native to Gnomon
Factory. Solution Factory's agentic branch already emits harness-neutral rules
(`.agent/policy.json`, protected paths, a wave plan). Rihma compiles the
equivalent into `.gnomon/`, where Gnomon enforces them.

## Applying the chain to Rihma itself

Once Solution Factory has produced `specs/001-initial/` from the brief:

1. Compile those specs into `contract/contract.json` for Rihma. A hand-run
   compiler is enough at first.
2. Compile the contract into the gnomonfactory repository's own `.gnomon/`.
3. Build M0 under it. Every task is an envelope, every criterion needs a test that failed
   first, and Gnomon refuses edits to the factory's own contract.

The factory is then governed by the chain it exists to provide, from its first commit.
