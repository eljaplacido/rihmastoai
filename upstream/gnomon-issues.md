# Gnomon upstream issues needed by Rihma

Each issue comes from the spec-to-verify chain (`docs/spec-to-verify.md`). Checked against
gnomonharness `master` at `fb458ea` (22 Nov 2026). Filed with the owner's consent on 22 Nov
2026:

| Draft | Status |
|---|---|
| 1. Per-run write scope | Filed: Gnomon #266 |
| 2. Holdout path family | Filed: #267 |
| 3. Per-test verify report and must-fail-first per test | Filed: #268 |
| 4. Per-rule governance levels | Filed: #269 |
| 5. Shell-effect classification for approvals | **Not filed: already in Gnomon** as `[approval] readonly_bash = "allow"` (CONTRACTS §10). Adopted in `.gnomon/policy.toml`. |
| 6. `could_not_measure` and `request_evidence` outcomes | Filed: #270 |
| 7. Audit export for an external ledger | Filed: #271 |
| 8. Doctor passes a surface that `gnomon task` refuses | Filed during M0 operations: #272 |
| 9. A builder turn with zero tool calls is accepted | Filed during M0 operations: #273 |
| 10. Roles silently offered no tools without `tools.toml` | Filed during M0 operations: #274 |
| 11. Two runs in one workspace stop each other as tamper | Filed during M0 operations: #279 |

The draft texts below are kept as written. The filed issues carry the final wording.

---

## 1. Per-run write scope that can only narrow the role's `write_allow`

**Use case.** A factory kernel runs one Gnomon task per work item, and each work item may
write only its own paths (for example `src/reports/**`). Today the only way to scope a run
is a separate role per work item. That moves the surface hash per task and makes the hash
useless as a run identity.

**Proposal.**
- Add `gnomon task --write-allow <glob>` (repeatable), or a `write_allow` key in a
  structured task file. Its effective scope is the intersection with the role's
  `write_allow`: it can only narrow, never widen.
- The task record carries `write_allow_run: [...]`.
- `gnomon check --write-allow <glob>` judges a change against the same narrowed scope.

**Acceptance.** A write inside the role's scope but outside the run's scope is refused and
recorded. A run glob outside the role's scope is a surface error. The surface hash does not
change between runs with different scopes.

## 2. A holdout path family: read-protected per role

**Use case.** Acceptance scenarios written outside the build (holdouts) must be readable by
the verifier role and unreadable by the builder role. Otherwise a builder can fit the code
to the test. Today read protection exists only for the `secrets` family, and only globally.

**Proposal.**
- Add `[governance.paths] holdout = ["holdouts/**"]` as a family that binds `read`, `grep`,
  `glob` and bash reads, the same way `secret_path` does.
- Allow a per-role override: `[roles.verifier.governance] holdout = "observe"` allows and
  records.

**Acceptance.** The builder role's read of `holdouts/x.feature` is refused, both by tool
and through bash `cat`. The verifier's read is allowed and recorded.

## 3. Per-test verify report in the task record

**Use case.** The factory accepts a criterion only when a test naming it passed at head and
failed at base. Today `[verify]` yields one verdict per command, so the factory has to parse
a junit file the cell itself could have written.

**Proposal.**
- Add `[verify] report = "junit:<path>"`. After the harness runs the check, it reads the
  report and records `verify_tests: [{id, outcome}]` plus the report's sha256 in the task
  record and the `verify` audit record.
- `test_must_fail_first` then applies per test id: each new test must fail at base.

**Acceptance.** A run whose junit reports `test_REQ_014_AC_2` passed at head, and failed on
the pre-turn tree, records both outcomes. A test that passed on the pre-turn tree is listed
as `fail_first: false`.

## 4. Per-rule governance levels

**Use case.** New gate rules must run in shadow (observe) and move to enforce one at a
time, after their false-positive rate is measured on replayed traffic. Today levels are per
family.

**Proposal.** `[governance.rules] outside_root = "enforce"`, `secret_path = "advise"`, and so
on, overriding the family level, with the effective level recorded per decision.

## 5. Shell-effect classification for approvals

**Use case.** In a 790-call replay, `[approval] gate = "on_write"` asked a person 355 times.
It treats every bash call as mutating, including `ls -la && cat CONTRIBUTING.md`. A
read/write classification of shell words (paths read, paths written, pushes, deletes, pipes
to an interpreter) asked 23 times with no catches lost.

**Proposal.** Classify bash calls by effect before the approval gate, and ask only for
mutations. Port the classification's fixtures as conformance cases.

## 6. `could_not_measure` and `request_evidence` outcomes in policy decisions

**Use case.** A rule that cannot evaluate a call, for example an unparseable shell word, has
to say so rather than allow or deny silently. A rule that needs evidence, for example "push
with no passing test since the last edit", should ask for it rather than refuse outright.

## 7. An event export the factory ledger can ingest

**Use case.** The factory keeps one hash-chained ledger and wants Gnomon's audit records in
it without re-parsing per version. The audit record schema (`gnomon.audit_record/1`,
§55) is the base.

**Proposal.** `gnomon audit export --since <seq> --format jsonl|otlp`, carrying the chain
head and the surface hash.

## 11. Refuse a second `gnomon task` in a workspace that already has a live run

**What happened.** On 22 Nov 2026 (master `fb458ea`), two `gnomon task` runs ended up
working in the same workspace at the same time. One was a run the operator believed was
dead: its SSH session had been killed, and `pgrep -f` could not find it because Gnomon
rewrites its process title to `gnomon task`. Within 19 seconds each run saw the other write to
`.gnomon-audit/`. Both recorded `record_tamper` (`when: between_calls`) and stopped with exit 3.
The 31-step run was lost as well as the new one, and two unresolved tamper events now
block skill acceptance until a person resolves them.

Gnomon was right that its records changed under it. But the cause was a second live Gnomon in
the same workspace, which Gnomon could have told apart from tampering at the start rather than
in the middle.

**Proposal.**
- At start, `gnomon task` takes a workspace run lock: `.gnomon-audit/run.lock` holding the
  pid, the start time and the trail name, with an OS advisory lock so a crashed run releases
  it.
- A second run in that workspace refuses to start, as an `apparatus_failure` with exit 10,
  with this message: "another gnomon task (pid N, trail T) is running in this workspace".
  Today it starts and both runs die as tamper later.
- A new record kind, `concurrent_run`, is distinct from `record_tamper`, so monitoring can
  tell operator error from tampering.
- Optional: `gnomon status` lists live runs per workspace by lock file, because the process
  title cannot.

**Workaround in Rihma.** Cells run through a wrapper holding `flock` on a workspace
lock file, with a pid file per cell (`ops/gf-cell-run.sh`).
