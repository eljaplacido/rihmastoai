// Writes the Gnomon 0.6.6-shaped fixtures beside this file. Run: node make_fixture.mjs
//
// No Gnomon 0.6.6 was installed anywhere when these were made (the GPU box ran 0.6.5+fb458ea5,
// the workstation 0.6.5), so the records are synthesised, field by field, from the v0.6.6
// tag's own files:
//   - conformance/audit_record_schema.json (gnomon.audit_record/1): every kind's fields;
//   - conformance/mediator_record.json: counters.model_calls, a trim's `basis` and `pre_call`;
//   - docs/CONTRACTS.md §1, §29, §52 to §59; prompt_loop.ts TaskRecord (verify_exit, ...).
// The chain is written the way Gnomon writes it: canonical() and recordHash() below are copied
// verbatim from packages/gnomon-core/src/audit.ts at v0.6.6, and each line is JSON.stringify of
// the record, as AuditTrail.write does. So the Python adapter is checked against JavaScript's
// own serialisation, not against itself.
//
// `external_context` is NOT a Gnomon 0.6.6 kind (it is in neither v0.6.6 nor master). It stands
// for a kind from a newer Gnomon, which the adapter must keep and count, never drop.
//
// Machine details are neutral: the local endpoint is `local` at 127.0.0.1:8080, and working
// directories are written under `~/`.

import { createHash } from "node:crypto";
import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

// --- verbatim from packages/gnomon-core/src/audit.ts @ v0.6.6 ---
function canonical(value) {
  if (value === undefined) return "null";
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  const obj = value;
  const keys = Object.keys(obj)
    .filter((k) => obj[k] !== undefined)
    .sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${canonical(obj[k])}`).join(",")}}`;
}

function recordHash(record) {
  const { hash: _omit, ...rest } = record;
  return createHash("sha256").update(canonical(rest)).digest("hex");
}
// --- end verbatim ---

function trail(name, records) {
  let prev = null;
  const lines = records.map(([kind, fields], seq) => {
    const ts = new Date(Date.UTC(2026, 10, 22, 20, 5, seq)).toISOString();
    const record = { seq, ts, kind, prev, ...fields };
    record.hash = recordHash(record);
    prev = record.hash;
    return JSON.stringify(record);
  });
  writeFileSync(join(here, name), lines.join("\n") + "\n", "utf-8");
}

const SURFACE = "4f1c0a5e2b7d9c3a8e6f1b2d4c7a9e0f3b5d8c1a2e4f6b8d0c3a5e7f9b1d2c4a";
const SURFACE_AFTER = "7a2e9c4f1b3d5a8c0e2f4b6d8a1c3e5f7b9d0a2c4e6f8b1d3a5c7e9f0b2d4a6c";
const HARNESS = "gnomon/0.6.6+v0.6.6-d3c574a";
const SESSION = "task-2026-11-22T20-05-00-000Z-4242";
const MODEL = "qwen3.6-35b";
const ENDPOINT = "local";
const ENDPOINT_URL = "http://127.0.0.1:8080/v1/chat/completions";
const WIRE = { stream: true, max_tokens: 0, max_context_tokens: 98304, max_context_tokens_source: "listing:llamacpp",
  tools_hash: "5230aa3b7d7f53f9863d9a75dadea4e9d15ffb3f2bbcc81d089a8c8081e4b286" };
const PRE_CALL = { why: "pre_call", dropped: 6, before: 70120, after: 38870, budget: 39321, ratio: 1.5, basis: "safety" };
const LEG = { why: "leg", dropped: 3, before: 61000, after: 52010, budget: 54918, ratio: 1.074, basis: "measured" };
const SENT = { v: 1, count: 2, window: 98304, budget: 58982, estimate: "chars4", est_max: 70120, replayed_calls: 0,
  steered_calls: { nudge: 0, converge: 0, other: 1 }, trims: { leg: 1, overflow: 0, dropped: 9, pre_call: 1 },
  calls: [{ i: 1, est: 70120, est_body: 70480, trim: PRE_CALL }, { i: 2, est: 61000, est_body: 61310, trim: LEG }] };
const RECEIVED = { metered: 2, reasoning_chars: 18608, over_window: 0,
  calls: [
    { i: 1, code: 0, ms: 48210, first_byte_ms: 912, prompt_tokens: 44310, cached_tokens: 0, completion_tokens: 812, reasoning_tokens: 640, reasoning_chars: 2560, finish: "tool_calls" },
    { i: 2, code: 0, ms: 39007, first_byte_ms: 655, prompt_tokens: 55841, cached_tokens: 40960, completion_tokens: 431, reasoning_tokens: 0, reasoning_chars: 16048, finish: "stop" },
  ],
  prompt_tokens: 100151, cached_tokens: 40960, completion_tokens: 1243, reasoning_tokens: 640, prompt_max: 55841, ratio: 1.074 };
const SKILLS = { v: 1, fired: [{ name: "unittest-first", tokens: 96 }], read: { "unittest-first": 1 },
  cited_in_reasoning: ["unittest-first"], proposed: [], stubbed: [{ name: "unittest-first", tokens_saved: 1210 }] };
const COUNTERS = { writes: 1, worktree_moves: 0, nudges: 0, final_step_was_write: false, per_tool: { bash: 1, write: 1 },
  model_calls: SENT, think_cap: { v: 1, cuts: 1, tokens_at_cut: [4012] }, skills: SKILLS,
  tree_delta: { files: 1, insertions: 12, deletions: 0, crlf_only: 0 } };
const TOOL_LOG = ["write app/routes.py (12 lines)", "bash python3 -m unittest discover -s tests -> exit 5: Ran 0 tests (päivitys ✓)"];

trail("builder-run.jsonl", [
  ["session_start", { surface_hash: SURFACE, harness: HARNESS, cwd: "~/gf-lanes/lane-1", mode: "task",
    role: "builder", resolved: { routes: { builder: { target: { endpoint: ENDPOINT, model: MODEL, local: true } } }, think_cap: 4000 },
    record: "metadata", approvals: "granted",
    deadline: { at: "2026-11-22T20:30:00.000Z", budget_ms: 1500000, margin_ms: 60000, source: "flag" } }],
  ["verify", { command: "true", role: "builder", phase: "setup", network: "none", exit: 0, ok: true }],
  ["model_call", { i: 1, role: "builder", model: MODEL, endpoint: ENDPOINT, estimate: "chars4", est: 70120, est_body: 70480,
    window: 98304, trim: PRE_CALL, code: 0, ms: 48210, first_byte_ms: 912, prompt_tokens: 44310, cached_tokens: 0,
    completion_tokens: 812, reasoning_tokens: 640, reasoning_chars: 2560, finish: "tool_calls" }],
  ["tool_call", { role: "builder", tool: "write", target: "app/routes.py", summary: "write app/routes.py (12 lines)",
    gated: false, code: 0, bucket: "result", duration_ms: 4, started_at: "2026-11-22T20:05:02.100Z" }],
  ["think_cap", { role: "builder", step: 2, cap: 4000, reasoning_tokens: 4012, reasoning_chars: 16048, consecutive: 1,
    rearmed: false, model: MODEL }],
  ["stall_signal", { role: "builder", signal: "novelty_cusum", step: 2, episode: 1, cusum: 1.5e-7 }],
  ["tool_call", { role: "builder", tool: "bash", target: "python3 -m unittest discover -s tests", summary: "exit 5",
    gated: false, code: 0, bucket: "result", duration_ms: 1840, started_at: "2026-11-22T20:05:04.300Z" }],
  ["model_call", { i: 2, role: "builder", model: MODEL, endpoint: ENDPOINT, estimate: "chars4", est: 61000, est_body: 61310,
    window: 98304, trim: LEG, ratio: 1.074, code: 0, ms: 39007, first_byte_ms: 655, prompt_tokens: 55841,
    cached_tokens: 40960, completion_tokens: 431, reasoning_tokens: 0, reasoning_chars: 16048, finish: "stop" }],
  ["checkpoint", { event: "checkpoint_skipped", role: "builder", step: 3, why: "deadline", left_ms: 75, share_left: 0.00005 }],
  ["verify", { command: "python3 -m unittest discover -s tests", role: "builder", round: 1, exit: 5, unrunnable: true,
    verdict: "unrunnable", reason: "exit 5 read as unrunnable" }],
  ["skill_use", { turn: 1, role: "builder", fired: SKILLS.fired, read: SKILLS.read,
    cited_in_reasoning: SKILLS.cited_in_reasoning, proposed: [], stubbed: SKILLS.stubbed }],
  ["external_context", { source: "inbox", items: 1, chars: 312 }],
  ["turn", { role: "builder", turn: 1, model: MODEL, endpoint: ENDPOINT, endpoint_url: ENDPOINT_URL,
    wire: WIRE, bucket: "result", code: 0, duration_ms: 92315, tool_steps: 2, tool_log: TOOL_LOG, stop_reason: "answered",
    counters: COUNTERS, tokens_in: 100151, tokens_out: 1243, skills: ["unittest-first"], context_turns: 0,
    context_dropped: 9, context_tokens: 52010, context_window: 98304, context_budget: 58982, context_estimate: "chars4",
    context_trims: 2, context_trimmed: 9, model_calls: RECEIVED, surface_hash: SURFACE }],
  ["session_end", { turns: 1, surface_hash: SURFACE }],
]);

// A proposal decided by the one declared policy (§58, §59), in its own sealed trail.
trail("proposal-decision.jsonl", [
  ["session_start", { surface_hash: SURFACE, harness: HARNESS, cwd: "~/gnomonfactory", mode: "proposal" }],
  ["proposal_decision", { id: "20261122T201500123Z-a1b2", proposal_kind: "memory", decision: "accept",
    decided_by: "policy:improve.auto_accept", paths: ["memory/test-command.md"], surface_hash_before: SURFACE,
    surface_hash_after: SURFACE_AFTER, by: "improve", authorised_by: "policy", interactive: false,
    agent_session_marker: "none", policy_rule: "improve.auto_accept",
    policy_evidence: { kind: "memory", probe_pairs: 3, pass_delta: 0, token_delta: -0.00004,
      report: ".gnomon-trials/_eval/2026-11-22T20-10-00Z/report.json",
      report_sha256: "9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d9c8b7a6f5e4d3c2b1a0f9e8d",
      spec_sha256: "0a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f9",
      min_probe_runs: 3, min_pass_delta: 0, max_token_increase: 0.1 } }],
  ["session_end", { applied: true, surface_hash_after: SURFACE_AFTER }],
]);

// An operator's work item (§57), in its own sealed trail. Never the item's text.
trail("inbox-item.jsonl", [
  ["session_start", { surface_hash: SURFACE, harness: HARNESS, cwd: "~/gnomonfactory", mode: "inbox" }],
  ["inbox_item", { op: "add", id: "20261122T201600456Z-c3d4", target: "claude-code" }],
  ["session_end", {}],
]);

// The task record `gnomon task --json` printed for the same run, under `[verify] exit_on_fail`
// (so the process exited 4 for an unrunnable check while the record's bucket stays result, §1).
const record = {
  surface_hash: SURFACE, harness: HARNESS, role: "builder", model: MODEL, endpoint: ENDPOINT,
  input: "Envelope T-001", output: "Wrote app/routes.py; the check ran no tests.",
  code: 0, bucket: "result", tool_steps: 2, tool_log: TOOL_LOG, skills: ["unittest-first"], stop_reason: "answered",
  verify: "unrunnable", verify_exit: 5, verify_rounds: 1, verify_reason: "exit 5 read as unrunnable",
  verify_tail: "Ran 0 tests in 0.000s\n\nNO TESTS RAN", counters: COUNTERS,
  volatile: { duration_ms: 92315, tokens_in: 100151, tokens_out: 1243, requests: 2, model_calls: RECEIVED,
    deadline: { at: "2026-11-22T20:30:00.000Z", budget_ms: 1500000, margin_ms: 60000, source: "flag" } },
  record_state: "final", session: SESSION, turn: 1,
  endpoint_url: ENDPOINT_URL, wire: WIRE,
};
writeFileSync(join(here, "builder-run.record.json"), JSON.stringify(record) + "\n", "utf-8");

// Values on which JavaScript and Python serialise differently, with JavaScript's canonical text.
const cases = [
  { share_left: 0.00005, cusum: 1.5e-7, token_delta: -0.00004, big: 1e21, mid: 123456789012345680000, ratio: 1.074 },
  { "ﬁles": 1, "\u{1F600}docs": 2, z: 3, "é": 4 },
  { text: "lone \uD800 surrogate", ctl: "\u0001\u001f\u007f", quote: "\"\\/" },
  [0.1, 100, 1e-6, 1e-7, 5e-324, -0],
];
writeFileSync(join(here, "canonical-cases.json"),
  JSON.stringify(cases.map((value) => ({ value, canonical: canonical(value) })), null, 1) + "\n", "utf-8");
