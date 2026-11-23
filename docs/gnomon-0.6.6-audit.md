# Rihma against Gnomon v0.6.6

Status: audit, 22 Nov 2026. **Rihma needs Gnomon 0.6.5 or later; 0.6.6 recommended.**

Gnomon v0.6.6 (tag `v0.6.6`, commit `d3c574a`, released 2026-11-22) was read from the tag's own
files with `git show v0.6.6:<path>`, `git diff v0.6.5 v0.6.6` and `git log v0.6.5..v0.6.6`.
`origin/master` is the tag itself: nothing was merged after it. Sections below are
CONTRACTS.md at v0.6.6 (`§n`) unless another file is named.

## The verdict

Rihma runs on 0.6.6 with the fixes in this change. Two things broke, and neither started in
0.6.6, but 0.6.6 makes both likelier:

1. **The audit chain check called intact Gnomon trails tampered.** Rihma re-hashed records with
   Python's `json.dumps`, and Gnomon hashes JavaScript's `JSON.stringify` output. The two write
   some numbers differently: 0.00005 is `5e-05` in Python and `0.00005` in JavaScript; 1.5e-7 is
   `1.5e-07` against `1.5e-7`. Any record holding such a number failed the check, so the run read
   *tampered* and *not measured*. 0.6.6 writes more fractional numbers than before, for example
   `proposal_decision.policy_evidence.token_delta` and a trim's `ratio`, which now applies against
   any known window.
2. **Exit codes 12 and 13 raised instead of mapping.** `adapters/gnomon_outcome.py` accepted only
   10 and 11 in the `apparatus_failure` bucket. §1 also puts 12 (`provider_unreachable`) and 13
   (`context_exhausted`) there, both with `stop_reason: "endpoint_error"`. 0.6.6 now reads context
   overflows in Anthropic, Gemini, LiteLLM and HTTP 413 wording as 13, where it used to return 10.
   An unknown code is never guessed (FR-C5-AC-2), so such a run was logged as
   `gnomon_run_not_ingested`.

One thing needed a change for 0.6.6 itself. Gnomon 0.6.6 has more machine-local directories,
and a bash flood now spills up to 64 MB to `.gnomon-out/`. A lane ignored none of these, so a
builder cell could commit them into the product repository.

## Versions in play

| Where | Build | What it has from 0.6.6 |
|---|---|---|
| GPU box (cells) | `gnomon/0.6.5+fb458ea5`, the source build in `~/src/gnomonharness-master` (D-0003) | Everything merged before `fb458ea` (#259): the `[verify]` contract keys (§53), `[defaults] max_context_tokens` as the fallback, `think_cap` (§52), `skill_use` (§54), the audit record schema (§55), the `pre_call` trim, `secrets_in_root` (#227) and the bounded bash flood. **Not** the trim `basis` or the realistic estimate (`31c3188`), the background window lookup (`da13d65`), the catalog and the Anthropic listing, the inbox, proposals, memory, `improve`, `skill export` or dashboard v2. |
| This workstation | `gnomon/0.6.5+v0.6.5-53f83bd`, the release | Nothing from 0.6.6. Cells do not run here: `exec = "os"` refuses shell on Windows. |

Which commits are in the GPU box's build was checked with `git log fb458ea5` against the commits in
`git log v0.6.5..v0.6.6`.

## Changes that touch Rihma

Effect: **breaks** (wrong today), **needs change** (to stay correct), **opportunity**, or
**no effect**.

### Records and the audit trail

| # | Change | Source | Effect | Done |
|---|---|---|---|---|
| 1 | Four new audit kinds: `skill_use` (§54), `think_cap` (§52), `inbox_item` (§57, the 35th) and `proposal_decision` (§58, the 36th). `audit_kind` now has 36 entries. | `packages/gnomon-core/src/audit.ts`@v0.6.6 (`AUDIT_KINDS`), `conformance/enumerations_golden.json`@v0.6.6, CHANGELOG | **No effect** on the chain: the `audit.ts` diff adds kinds only, and hashing is unchanged. **Needs change** to report them: Rihma had no list of kinds. | `AUDIT_KINDS` (all 36) in `adapters/gnomon_ingest.py`. `verify_audit()` counts every record by kind, before and after a break, and lists `unknown_kinds`; the ledger's `chain` carries both. FR-C2-AC-5. |
| 2 | `external_context` audit kind | `git grep external_context` at v0.6.5, v0.6.6 and `origin/master` finds nothing | **UNVERIFIED: not a Gnomon 0.6.6 kind.** It exists in no tagged or merged Gnomon code. | It is used as the stand-in for "a kind from a newer Gnomon" in the fixture. Such a record is kept and counted; per §55 only its kind name and count leave the adapter, never its fields. |
| 3 | A trim's `basis`: `measured` (the provider's own prompt counts for this endpoint and model) or `safety` (the 1.5x factor before any usage was seen), beside `ratio`. It appears on `counters.model_calls.calls[].trim` and on the `model_call` audit record's `trim`. | CHANGELOG "Fixed — a known window is checked against a realistic estimate"; `conformance/mediator_record.json`@v0.6.6 (`trim.optional: ["ratio", "basis"]`); `mediators.ts`@v0.6.6 lines 73 and 393-398; §29 | **Opportunity** | `context()` in `gnomon_ingest.py`: the `gnomon_run` event now carries `context: {window, source, trims {leg, overflow, pre_call, dropped}, basis {measured, safety, unstated}, ratio}`. FR-C2-AC-6. |
| 4 | The `pre_call` trim reason and `counters.model_calls.trims.pre_call`. It is present once there has been one. | `conformance/mediator_record.json`@v0.6.6 (`trim_why`, `trims_optional`); §29 | **Opportunity**. The GPU box's build already writes it. | Counted in `context.trims.pre_call`, 0 when absent. |
| 5 | Canonical JSON for the hash chain: unchanged in 0.6.6, but 0.6.6 writes more fractional numbers. | `audit.ts`@v0.6.6 `canonical()`/`recordHash()` | **Breaks** (see the verdict). | `canonical_json()` in `gnomon_ingest.py` writes as JavaScript does. Numbers follow ECMA-262 `Number::toString`; keys sort by UTF-16 code unit; a lone surrogate is escaped as `\udxxx`. It was checked against Node 24's `JSON.stringify` on 25,008 doubles (random bit patterns, ±1e-12 to 1e25, edge cases), with 0 mismatches. The 0.6.6 fixture is chained by Gnomon's `canonical()`, copied verbatim into `tests/fixtures/gnomon-0.6.6/make_fixture.mjs`. On it, the old hash breaks at the `stall_signal` (`cusum` 1.5e-7), `checkpoint` (`share_left` 0.00005) and `proposal_decision` (`token_delta` -0.00004) records. FR-C2-AC-5. |
| 6 | The audit record schema `gnomon.audit_record/1` and `gnomon audit schema --json`. A reader treats a kind or field the schema does not list as `content`. | §55; `conformance/audit_record_schema.json`@v0.6.6 | **Opportunity** (already in the GPU box's build) | Followed: unknown kinds are reported by name and count only. A record with no `hash` (`[audit] chain = false`) is reported as unchained and not intact. |
| 7 | Sealed trails of their own: inbox items (`inbox-<time>-<pid>-<hex>.jsonl`, `session_start.mode: "inbox"`), proposal decisions (`skill-<time>-<pid>-<hex>.jsonl`, mode `proposal`) and dashboard chat sends (`chat-<time>-<pid>.jsonl`, mode `dashboard_chat`) | `inbox.ts:239`, `skills.ts:605`, `dashboard_chat.ts:431`@v0.6.6 | **No effect**: `kernel/status.py` `live()` and `kernel/dispatch.py` read `task-*.jsonl` and `task-*.record.json` only. | None |

### The `gnomon task --json` record

| # | Change | Source | Effect | Done |
|---|---|---|---|---|
| 8 | New fields `verify_exit`, `verify_rounds`, `verify_reason` and `verify_tail`, present only with `--require-verify`, `[verify] exit_on_fail` or `[verify] record_detail` | `TaskRecord` in `prompt_loop.ts`@v0.6.6 (the only diff to the interface); §53 "The exit, the record detail and the probe" | **Needs change**: only `verify_exit` travelled. Product lanes declare no `[verify]`, so these fields are absent there. The factory's own surface declares `exit_on_fail` and `record_detail`. | `verify_rounds` and `verify_reason` now travel in `native`. `verify_tail` does not: it is the check's own output (content), and the record keeps it. FR-C5-AC-3. |
| 9 | The exit under `--require-verify` or `exit_on_fail`. Where the bucket says 0, a failed, regressed or passed_unverified check exits 1 and an unrunnable one exits 4. The record's `bucket` stays `result` and its `code` 0 ("A deviation, stated"). | §1; `taskExitCode()` in `prompt_loop.ts:10842`@v0.6.6 | **No effect** on the verdict: Rihma reads the record, never the process exit. | The process exit (`_exit` from `kernel/model.py`) now travels as `native.exit`. FR-C5-AC-3. |
| 10 | Exit codes 12 `provider_unreachable` and 13 `context_exhausted` on `apparatus_failure`, with stop reason `endpoint_error`. 13 now covers more overflow wordings. | §1 table and the `stop_reason` table; `classifyFailure()` in `prompt_loop.ts`@v0.6.6; CHANGELOG ("Context overflows in Anthropic, Gemini, LiteLLM and HTTP 413 wordings are recognised (code 13...)") | **Breaks** (see the verdict) | `APPARATUS_CODES = (10, 11, 12, 13)`. FR-C5-AC-3. |
| 11 | `verify` values: `passed`, `passed_unverified`, `failed`, `unrunnable`, `regressed`, `declined`, `skipped` | `TurnResult.verify` in `prompt_loop.ts:4488`@v0.6.6; §1 | **No effect**: all seven were mapped already. | None |
| 12 | Stop reasons: the same 13 values in 0.6.5 and 0.6.6 (`answered`, `empty`, `stall`, `step_wall`, `cancelled`, `truncated`, `tamper`, `apparatus`, `malformed`, `endpoint_error`, `in_progress`, `killed`, `deadline`) | the `StopReason` type in `prompt_loop.ts`, diffed between the tags | **No effect** | `STOP_REASONS` in `gnomon_outcome.py`. A test maps each value on a bucket and code a record can carry. FR-C5-AC-3. |
| 13 | Buckets: still `result`, `refusal`, `apparatus_failure` | `session.ts`@v0.6.6 `Bucket` | **No effect** | None |
| 14 | `wire.max_context_tokens_source` gains `listing:anthropic` and `catalog` | §24 | **No effect** (read as a string) | It is shown in `context.source`. |
| 15 | New counters: `counters.think_cap`, `counters.skills` (and `stubbed`), `counters.memory`, `counters.compaction` | §52, §54, §56, §58 | **No effect**: each is absent unless its key is declared, and Rihma declares none. | None |
| 16 | `harness` is `gnomon/<version>+<build>`: a stamp, `npm`, a short sha, `-dirty`, or `unknown` | `build.ts` `resolveHarnessBuild()`@v0.6.6 | **No effect** | `kernel/doctor.py` parses it. |

### Surface keys

| # | Change | Source | Effect | Done |
|---|---|---|---|---|
| 17 | `[defaults] max_context_tokens` is now **the fallback, not the window**. An endpoint that declares no number is asked through its listing, then Gnomon's catalog; the fallback applies only when both find nothing. A number on `[endpoints.<name>]` wins and asks nothing. | §24 "Semantics change (2026-11-22)"; CHANGELOG "Behaviour change"; `init.ts`@v0.6.6 comment | **Needs change** to keep a cap. The GPU box's build already behaves this way; the Windows 0.6.5 release does not. Lanes compile `[defaults] max_context_tokens = 98304` from `routing.json`. Under 0.6.6, `go` (OpenCode Go) reports its own window: the existing fixture shows 1,000,000 for `deepseek-v4-pro`, `listing:opencode`. `local` reports llama.cpp's `/props` `n_ctx`, measured at 98,304. Cloud roles are therefore no longer held to 98,304. | `kernel/lanes.py` now compiles an optional per-endpoint `max_context_tokens` (a whole number or `"auto"`) from `routing.json` onto `[endpoints.<name>]`. With none declared, the output is unchanged. `routing.json` is unchanged: 0.6.6 does not require a cap. FR-C2-AC-7. |
| 18 | `[verify]` gains `timeout_seconds`, `setup`, `setup_network`, `setup_timeout_seconds`, `contract`, `exit_map`, `regressed_hand_back`, `protects`, `exit_on_fail` and `record_detail` | `BLOCK_KEYS` in `config.ts`, v0.6.5 against v0.6.6 | **Opportunity**. The factory's own `.gnomon/policy.toml` declares `protects`, `exit_on_fail`, `record_detail`, `timeout_seconds` and `[verify.exit_map]`. The 0.6.5 release warns that they "do nothing"; 0.6.6 reads them. That meets D-0003's exit condition: "Move back to a released version when one includes these keys." | `.gnomon/` is unchanged. Moving back is the owner's decision (see the upgrade steps). Product lanes declare no `[verify]`. |
| 19 | `[governance] secrets_in_root` (#227). Under `exec = "os"` with the secrets family at `prevent` or above, a session refuses to start while a declared secret file is inside the root. | CHANGELOG "Fixed" (#227); §10 `secret_path` | **No effect observed**: the GPU box's build already has it, and cells start there. The factory's own surface is exactly this case: `exec = "os"`, `level = "prevent"`, `secrets = "enforce"`. | None. Before upgrading, check that no `.env` or key file sits inside `~/gnomonfactory` on the GPU box. |
| 20 | `[turn] max_reasoning_tokens_without_action` (the think cap) | §52 | **Opportunity** (opt-in, unmeasured) | None |
| 21 | `[skills] inline_max_tokens`, `[context] summary_style`, `[memory] propose`, `[proposals] harness_paths`, `[improve] *`, `[dashboard] chat_role`, and `[ui] style`, `spinner` and `think = "wrap"` | §54, §56, §58, §59, §17; CHANGELOG | **No effect**: Rihma declares none. The changelog says a surface with none of them gives the same hash, prompt, tool schemas and first request body as 0.6.5. | None |
| 22 | `[resilience]` and `[sandbox]` keys, role keys (`ROLE_KEYS`), `tools.toml` entries (`ToolConfig`, `ToolDef`) and the `gnomon init` system prompt and tools template: all unchanged. A sandbox refusal now names `[sandbox] extra_roots` for file tools too. | `config.ts` diffed between the tags; the `init.ts` diff hunks | **No effect**: the lanes' `system.md` and `tools.toml` stay in step. | None |
| 23 | Machine-local directories: `.gnomon-inbox` and `.gnomon-proposals` join `MACHINE_LOCAL_DIRS`. A bash flood spills to `.gnomon-out/<session>/`, up to 64 MB a file. | `init.ts`@v0.6.6 `MACHINE_LOCAL_DIRS`; `check.ts`@v0.6.6 `OWN_STATE`; `tools.ts`@v0.6.6 `FLOOD_SPILL_CAP_BYTES`, `OVERFLOW_DIR`; `.gitignore` diff | **Needs change**. Lanes ignored only `.gnomon-audit/` and `.gnomon-sessions/`, and `commit_all()` runs `git add -A`. | `kernel/lanes.py` `GNOMON_MACHINE_LOCAL` (all ten) goes into every lane's `.git/info/exclude` and the analyst lane's `.gitignore`. FR-C2-AC-7. |

### Commands

| # | Change | Source | Effect | Done |
|---|---|---|---|---|
| 24 | `gnomon task` flags Rihma uses (`--task-file`, `--role`, `--json`, `--yes`, `--deadline`): unchanged. `--require-verify` is added. | the usage text in `packages/gnomon-cli/src/index.ts`@v0.6.6 | **No effect** | None |
| 25 | `gnomon --version` prints `harnessBuild()` | `index.ts:3583`@v0.6.6 | **Opportunity** | `kernel/doctor.py` `gnomon_version()`. |
| 26 | `gnomon check`: `setup` in its temporary worktree, `protects` makes a green check `fail` (`passed_unverified`), `verdict` appears when an exit map is declared, and `OWN_STATE` adds the inbox and proposals directories | §53; the `check.ts` diff | **No effect**: the kernel's gate does not call `gnomon check` (only `blueprint/` and docs name it). | None |
| 27 | `gnomon doctor verify` runs the declared check once and flags `no_tests`, `ambiguous_exit` and `red_baseline` | §53 | **Opportunity**: worth running once on the factory's own repository on the GPU box after the upgrade (an owner's act). | None |
| 28 | `gnomon skill export [--to <dir>] [--format skill-md] [--write]` | CHANGELOG "Added — Cursor hooks v2 and skill export"; `skill_export.ts`@v0.6.6 | **Opportunity, none today**: the factory's `.gnomon/` has no `skills/`. | None (see Opportunities) |
| 29 | `gnomon proposals`, `gnomon memory` (§58) and `gnomon improve` (§59) | CHANGELOG; §58, §59 | **Opportunity** | None (see Opportunities) |
| 30 | `gnomon inbox` and the dashboard's "Flag for fix" | §57 | **Opportunity** | None (see Opportunities) |
| 31 | Dashboard v2: onboarding, the per-project Lens, the inbox, a read-only chat | §17; CHANGELOG | **Opportunity** | None (see Opportunities) |
| 32 | The window lookup runs in the background and is cached per machine in `window-cache.json`: 7 days for a window, 1 day for none. `GNOMON_WINDOW_LOOKUP=off` disables it. | §24; CHANGELOG "Fixed — the window lookup no longer holds the first request" | **No effect** on code. If llama-server's `-c` on the GPU box changes, Gnomon may use the cached window for up to 7 days. Declare the number on the endpoint (row 17) if it must follow at once. | None |
| 33 | The realistic estimate: before each call against a known window, the estimate is scaled by 1.5 until usage has been seen, then by the measured ratio (never below 1). This fixes R66: on a local Qwen3.6 behind llama.cpp with a 98,304 window, 9 prompts were refused while the pre-call trim fired 0 times. | CHANGELOG; §29 | **Opportunity**: it is the GPU box lane's failure. Expect fewer `endpoint_error`/13 endings and earlier trims on `local`. | None |
| 34 | Terminal themes, the boxed UI, piped output, Cursor hooks v2, guard adapters for Codex, Qwen Code and Copilot, the `gnomon init` starter trial spec | CHANGELOG | **No effect**: "No wire, record, `--json` or `gnomon task` output changes", and all are opt-in. | None |

### Observations not caused by 0.6.6 (left as they are)

- **The refusal floor reads as "violation".** FR-C5-AC-1 maps exit 2 to *violation*. A record
  lands on exit 2 for `stall`, `step_wall`, `malformed`, `deadline`, `cancelled` and cut tool
  calls (`truncated`), where no rule was broken. It is the approved criterion, so it is
  unchanged. The owner may want "not measured" for those stop reasons.
- **On Windows, a bare `gnomon` does not start from Python.** `subprocess.run(["gnomon", ...])`
  raises `FileNotFoundError`, because npm installs `gnomon.cmd`. `kernel/model.py` now resolves
  the command with `shutil.which()`, and a command that cannot start raises `ModelError`, which
  dispatch treats as an apparatus failure (FR-C6-AC-2).
- **Two ignore lists are outside this change's write scope.** The product template's
  `kernel/scaffold.py` `GITIGNORE` and the repository's own `.gitignore` list only some of
  Gnomon's machine-local directories. Lanes are covered (row 23). Recommended: add
  `.gnomon-out/`, `.gnomon-jobs/`, `.gnomon-loops/`, `.gnomon-shadow/`, `.gnomon-skills/`,
  `.gnomon-trials/`, `.gnomon-inbox/` and `.gnomon-proposals/` to both.
- **History keeps the version it was written against.** `docs/m0-log.md` (the operations log),
  `decisions/`, `blueprint/`, and the dated design pages `docs/gnomon-factory.html` and
  `docs/gnomon-factory-vision.html` name 0.6.5, `faba3a4` or `fb458ea`. That is when they were
  written, so they are unchanged. The README and `docs/spec-to-verify.md` now say "Rihma needs
  Gnomon 0.6.5 or later; 0.6.6 recommended".
- **One comment now describes a fallback.** `.gnomon/config.toml` says
  `max_context_tokens = 98304  # the GPU box's llama-server window`; under 0.6.6 that is the
  fallback. It was not edited then, because any byte in `.gnomon/` moves the surface hash the
  owner trusted. The release scrub, which moved the hash anyway, now calls it the fallback window.

## Fixes, criteria and tests

The new criteria sit under existing requirements in `contract/contract.json`, with task
**V-29**.

| Criterion | What it holds | Tests |
|---|---|---|
| FR-C2-AC-5 | A 0.6.6-shaped trail re-verifies intact with JavaScript's canonical JSON; a rewritten record still breaks it; every kind is counted, an unknown kind is never dropped | `tests/test_gnomon_ingest.py`: `test_FR_C2_AC_5_a_0_6_6_trail_reverifies_intact_and_every_kind_is_kept`, `test_FR_C2_AC_5_canonical_json_is_written_as_javascript_writes_it`, `test_FR_C2_AC_5_a_rewritten_0_6_6_record_still_breaks_the_chain` |
| FR-C2-AC-6 | The run's event carries the window, its source, trims by reason (`pre_call` included) and their `basis` | `test_FR_C2_AC_6_the_run_event_carries_the_window_its_source_the_trims_and_their_basis` |
| FR-C2-AC-7 | Lanes keep Gnomon's machine-local directories out of commits; an endpoint's own window compiles to its block | `tests/test_gnomon_066.py`: `test_FR_C2_AC_7_a_lane_keeps_gnomons_machine_local_directories_out_of_the_products_commits`, `test_FR_C2_AC_7_an_endpoints_own_window_compiles_to_its_block_and_defaults_stays_the_fallback` |
| FR-C5-AC-3 | Codes 12 and 13 are apparatus failures; every stop reason maps; the exit and the verify detail travel as native values | `tests/test_gnomon_outcome.py`: `test_FR_C5_AC_3_exit_12_and_13_are_apparatus_failures_and_verify_detail_travels_as_native`, `test_FR_C5_AC_3_every_0_6_6_stop_reason_on_its_documented_bucket_maps_without_guessing` |
| FR-C6-AC-2 | `gnomon` is found as the shell finds it; one that cannot start is a `ModelError` | `tests/test_gnomon_066.py`: `test_FR_C6_AC_2_gnomon_is_found_as_the_shell_finds_it_and_one_that_cannot_start_is_an_apparatus_failure` |
| FR-N2-AC-2 | `doctor` reports and exits 1 on a hard failure | `tests/test_doctor.py`: `test_FR_N2_AC_2_doctor_reports_gnomons_version_and_support_and_never_a_keys_value`, `test_FR_N2_AC_2_the_doctor_subcommand_prints_json_and_exits_1_on_a_hard_failure`, `test_FR_N2_AC_2_gnomon_version_parses_every_build_form` |

**About the fixtures.** No Gnomon 0.6.6 was installed anywhere, and the owner installs it. So
`tests/fixtures/gnomon-0.6.6/` is synthesised from the tag's own files. Each record's fields
come from `conformance/audit_record_schema.json`, `conformance/mediator_record.json` and
CONTRACTS §1, §29 and §52 to §59. The chain is written by `make_fixture.mjs`, which runs
Gnomon's `canonical()` and `recordHash()` copied verbatim from `audit.ts`@v0.6.6, and
`JSON.stringify` for each line. **UNVERIFIED** until a real 0.6.6 run is ingested: that a live
0.6.6 record carries exactly these fields together. Every field name and type is from the
schema files; the combination and the values are illustrative.

**The doctor.** `python -m kernel.cli doctor` prints `rihma.doctor/1` JSON with:

- Python;
- Gnomon: the command found, the raw `--version` line, version, build, `supported` (≥ 0.6.5)
  and `is_recommended` (≥ 0.6.6; a pre-release sorts below its release);
- git, and docker (optional);
- the lanes root and whether it is writable (probed with a temporary file that is removed);
- for each `routing.json` endpoint with an `api_key_env`, whether that variable is set, never
  its value (with a machine's `routing.local.json` merged over it, which the report names);
- the factory home.

It exits 1 when Gnomon is missing, its version cannot be read, or it is older than 0.6.5.

## Opportunities, with a recommendation each

1. **The `basis` and the window in the Cell view.** *Recommended; the data is in place.* Each
   `gnomon_run` event now carries `context`. The Cell row in `kernel/projections.py` `cell()` is
   outside this change's scope; adding `"context": p.get("context")` there shows the window,
   its source and the trims per run. A cockpit badge could mark a run whose trims rested on
   `safety`: those are first-request estimates, not measurements.
2. **`external_context` records in the Cell view.** *Recommendation: none until Gnomon defines
   it.* No such kind exists in v0.6.6 or on `master`. If a later Gnomon adds it, the adapter
   already lists it under `chain.unknown_kinds`. The Cell view should show that list (kind names
   only, as §55 requires for unknown kinds) and nothing of the record. Once Gnomon's schema
   classes its fields (`gnomon audit schema --json`), show its `metadata` fields only.
3. **The cockpit and Gnomon dashboard v2, per lane.** *Recommended: show a command, not a link.*
   The dashboard lists the project it was started in plus the roots in the trust store (§17).
   Product lanes run untrusted, so they are never in the trust store. Sign-in is a one-time
   bootstrap printed in the terminal, and every API call needs its bearer token, so a link from
   the cockpit cannot open a signed-in Lens. For each lane, the cockpit can show
   `gnomon dashboard --dir <lane>` and the Lens route `#/lens/<id>`, where `<id>` is the first
   12 hex characters of the sha256 of the resolved lane root (`idOf()` in
   `dashboard_data.ts:73`@v0.6.6). `cockpit/**` is outside this change's scope.
4. **`gnomon skill export` for the factory's own skills.** *Not now.* The factory's `.gnomon/`
   has no `skills/` directory, so there is nothing to export. If skills are added and accepted
   later, `gnomon skill export --write` puts them in `.claude/skills/<name>/SKILL.md` for the
   operator's Claude Code session. That is a dry run without `--write`, never writes into
   `.gnomon/`, and never overwrites a `SKILL.md` it did not write. The repository's
   `.gitignore` ignores `.claude/`, so the exports stay on the machine that made them.
5. **Rihma's default checks against Gnomon's proposal store.** *Keep them separate.* They govern
   different things:
   - `kernel/learn.py` turns a lesson that recurs across products into a default check for
     every future product's contract. It is decided in the `_factory` canon by a person with a
     persona, and stored in the factory home.
   - A Gnomon proposal changes one project's `.gnomon/` surface: a skill, a memory entry or
     `system.md`. It is machine-local (`.gnomon-proposals/` is gitignored), decided per machine,
     and refused for policy, roles, tools and config unless a person lists them.

   Rihma also recompiles lanes' `.gnomon/` from the routing and rewrites `system.md`, so an
   accepted Gnomon proposal in a lane would be overwritten by the next compile. Mapping one
   onto the other would let a surface edit pose as a contract check, or the reverse. The one
   useful link is evidence: a default check's card can cite the `proposal_decision` record of a
   related surface change by trail and `seq`.
6. **`gnomon improve` as the engine of the `harness_engineering` profile.** *Recommended, read
   only first.* A harness-engineering product *is* a `.gnomon/` surface with trial specs, and
   §59 already mines trails, drafts, lints, probes on `.gnomon/trials/` and composes. Steps:
   1. The profile runs `gnomon improve --dry-run --json` in the product lane. It calls no
      model, writes nothing, and its `gnomon.improve/1` report lists candidates with their
      evidence. Each candidate becomes a card in the project's canon.
   2. Acceptance stays a person's, with `gnomon proposals accept <id>` at a terminal. It is
      refused in an agent session (exit 3), and `improve --run` refuses without a confined
      sandbox and, for billed roles, without `--max-requests`.
   3. The profile's "delta against a named baseline on a fixed trial set" is the probe's
      `pass_delta`, `token_delta` and `regressed`, read from the cited `eval_run` record.

   `[improve] auto_accept` should stay undeclared on product surfaces until a person decides
   otherwise. `kernel/profiles.py` is outside this change's scope.
7. **The inbox for the factory's own development.** *Optional; the owner's act.* After
   `gnomon guard install claude-code --write` in this repository, an item flagged in the
   dashboard reaches the next Claude Code session, as information and not instructions.
   Rihma's kernel should not write inbox items: the agent side has no add on purpose.
8. **`gnomon doctor verify` and `[turn] max_reasoning_tokens_without_action`.** *Worth one
   owner-run measurement each.* Run `doctor verify` once on `~/gnomonfactory` after the
   upgrade. The think cap could address long silent reasoning on `qwen3.6-35b` builder
   fallbacks, but it is unmeasured; trial it on the GPU box lane before declaring it on a surface.

## Upgrade steps (the owner's)

Nothing here was run. Gnomon is installed and upgraded by the owner. The commands are from
Gnomon's README@v0.6.6 ("Install", "Updating", "From source") and `package.json`@v0.6.6.
Gnomon's repository, and so its README, is linked from this repository's
[README](../README.md); `npm repo gnomon-harness` opens it too (the package's `repository`
field). `gnomon update` needs no URL. The two installer lines, `install.sh` for Linux and macOS
and `install.ps1` for Windows, are written out with their full URLs in
[Getting started](getting-started.md#install-gnomon), under "Install Gnomon"; the pinned
commands below name that line rather than repeat it.

**Windows workstation** (`gnomon/0.6.5+v0.6.5-53f83bd`, an installer or npm install):

```powershell
gnomon update                      # shows this version, the latest and its changelog, then re-runs the installer
# or, pinned: set the version, then run the Windows installer line from docs/getting-started.md, "Install Gnomon"
$env:GNOMON_VERSION = '0.6.6'
irm <install.ps1 URL, as in docs/getting-started.md> | iex
gnomon --version                   # gnomon/0.6.6+...
python -m kernel.cli doctor        # "is_recommended": true
```

`npm i -g gnomon-harness@0.6.6` also works once `npm view gnomon-harness version` prints 0.6.6.
Until then the registry has 0.6.5.

**GPU box** (`gnomon/0.6.5+fb458ea5`, the source build that `kernel/model.py` and
`ops/gf-cell-run.sh` call by path). Two ways; the second is the move back to a release that
D-0003 anticipated, and it is the owner's decision.

*A. Keep the pinned source path and build it at the release tag:*

```bash
cd ~/src/gnomonharness-master
git status --porcelain              # must print nothing, or the build is stamped -dirty
git fetch --tags origin
git checkout --detach v0.6.6
source ~/.nvm/nvm.sh && nvm use 22
pnpm install && pnpm run build:native && pnpm run build   # `pnpm run setup` without link:global (pnpm 9 and Rust, as the first build)
node packages/gnomon-cli/gnomon.js --version              # gnomon/0.6.6+d3c574a2 (git's short sha; the GPU box printed 8 digits for fb458ea5)
```

*B. Use the released 0.6.6 and stop calling the source build:*

```bash
source ~/.nvm/nvm.sh && nvm use 22
gnomon update                       # or, pinned: curl -fsSL <install.sh URL, as in docs/getting-started.md> | GNOMON_VERSION=0.6.6 sh
gnomon --version                    # gnomon/0.6.6+...
export GNOMON_CMD=gnomon            # kernel/model.py and ops/gf-cell-run.sh both honour it
```

Then, on either path:

```bash
cd ~/gnomonfactory && python3 -m kernel.cli doctor   # exit 0, "is_recommended": true
gnomon security --json                               # read-only (§45); no `surface_fatal` or `secrets_in_tree` finding (row 19)
```

Finally, run one preflight smoke task (FR-O8-AC-3). The engine should report no declared key
it does not read, and the record's `harness` should name 0.6.6. Its `surface_hash` should
equal the one the owner trusted. The changelog says a surface that sets no new key hashes as
it did under 0.6.5, so the trust grant should stand. **UNVERIFIED** until that smoke task runs.
