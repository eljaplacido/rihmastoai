/* Agent operations: the AI architect's view of how the agents perform and what they cost (kernel/agentops*.py,
   FR-AOP1). Across every project in the sidebar (#/agentops, Rihmasto's own work included) and per project in the
   Agents capsule (#/p/<pid>/agentops). One filter row (the period) above figures, charts and tables:

   - key figures: runs, tokens, cost, response time, tool calls and the share served from the prompt cache;
   - by role, harness and model (bars and their table), the trend (lines), role x project (a heatmap; one project:
     role x day), tools and their latency, the harness's overhead, the context packs against their budgets with
     Gnomon's own context evals, context drift and the agent observability hub's recorded figures;
   - the Optimise audit: proposals by rule, each with its expected saving, Take me there and File as a change, and
     Record the audit (signed, in the ledger).

   Any figure, bar, cell or tool opens the runs behind it. A figure with nothing behind it says "not measured" with
   how to measure it, never zero. Reading writes nothing; the two writes are signed. */

import { S, $, h, fill, icon, chip, api, enc, card, button, say, plural, signed, needPerson, act, num, ago, pageHead,
  segmented, openModal, local, fmtMoney, mayAct, nav, AuthError } from "./core.js";
import { bars, dataTable, sparkline, SERIES } from "./charts.js";
import { lines, heatmap } from "./agentops_charts.js";
import { pricesCard } from "./agentops_prices.js";
import { pick, term, tw, emptyState, datum } from "./words.js";
import { incidentPanel } from "./heal.js";

const WINDOWS = [["24h", "24 h"], ["7d", "7 days"], ["30d", "30 days"], ["all", "All"]];
const KEY = "gf.agentops.window";
const ROLE = { holdout_author: "holdout author", analyst: "analyst", builder: "builder", verifier: "verifier", assistant: "assistant" };
const ROLE_PLAIN = { analyst: "question asker and requirements writer", builder: "builder", verifier: "checker",
  holdout_author: "hidden-test writer", assistant: "Ask Rihma" };
const KIND = { context_cut: ["Cut context", "layers"], reorder: ["Reorder for the cache", "refresh"], cache_prefix: ["Cache a prefix", "layers"],
  cheaper_model: ["Cheaper model", "cpu"], slow_tool: ["Slow tool", "clock"], retries: ["Many attempts", "flag", "Many rounds"] };

const roleWord = (r) => (String(r).startsWith("handoff:") ? "hand-off to " + String(r).slice(8) : pick(ROLE_PLAIN[r] || ROLE[r] || r, ROLE[r] || r));
function windowNow() { const w = local.get(KEY); return WINDOWS.some((x) => x[0] === w) ? w : "30d"; }
const short = (n) => (n === null || n === undefined ? null : Math.abs(n) >= 1e6 ? (n / 1e6).toFixed(1) + "M" : Math.abs(n) >= 1e4 ? Math.round(n / 1000) + "K" : num(Math.round(n)));
const secs = (s) => (s === null || s === undefined ? null : s < 1 ? Math.round(s * 1000) + " ms" : (Math.round(s * 10) / 10) + " s");
const money = (v, cur) => (v === null || v === undefined ? null : fmtMoney(v, cur));
function nm(text, why) { return h("span", { class: "nm-text", tip: why || null }, text || "not measured"); }

function notMeasured(gap) {
  return h("div", { class: "nm-box" }, icon("dashed"), h("div", null, h("b", null, "Not measured"),
    h("p", null, datum(gap.why + ".")), gap.how ? h("p", { class: "small muted" }, "To measure it: ", datum(gap.how + ".")) : null));
}

// -- the drill-down: the runs behind a figure --------------------------------------------------------------

const MATCH = { role: "role", harness: "harness", model: "model", project: "project", day: "day", task: "task" };
function runsOf(d, f) {
  const ids = f.tool ? new Set(((d.tools.tools || []).find((t) => t.tool === f.tool) || {}).run_ids || []) : null;
  return d.runs.filter((r) => Object.keys(MATCH).every((k) => f[k] === undefined || (k === "day" ? (r.at || "").slice(0, 10) === f.day : r[MATCH[k]] === f[k]))
    && (!ids || ids.has(r.id)));
}
function drill(d, f, title) {
  const rows = runsOf(d, f);
  const capped = d.runs_total > d.runs.length ? h("p", { class: "small muted" }, "The newest " + d.runs.length + " of " + d.runs_total + " runs in the period are read here.") : null;
  openModal(title, h("div", { class: "aop-drill" }, h("p", { class: "small" }, plural(rows.length, "run") + " behind this figure, newest first."), capped,
    rows.length ? dataTable([
      { label: "When", value: (r) => ago(r.at) },
      { label: "Project", value: (r) => h("a", { href: "#/p/" + enc(r.project) + "/" + (r.role === "builder" ? "cell" : "ledger") }, datum(r.title)) },
      { label: pick("Helper", "Role"), value: (r) => roleWord(r.role) },
      { label: pick("Coding agent", "Harness"), value: (r) => datum(r.harness) },
      { label: "Model", value: (r) => h("span", { class: "mono" }, r.model) },
      { label: tw("token", 2, { cap: true }), num: true, value: (r) => short(r.tokens) },
      { label: "Cost", num: true, value: (r) => money(r.cost, r.currency), none: "not priced" },
      { label: tw("latency", 1, { cap: true }), num: true, value: (r) => secs(r.seconds) },
      { label: pick("Result", "Verdict"), value: (r) => r.verdict || "" }], rows.slice(0, 200), title)
      : h("p", { class: "muted" }, "No run in this period matches.")), { icon: "list", wide: true });
}
function drillable(el, d, f, title) {
  el.setAttribute("data-control", "agent_ops_drill");
  el.addEventListener("click", (e) => { if (e.target.closest("a")) return; drill(d, f, title); });
  el.addEventListener("keydown", (e) => { if (e.key === "Enter") drill(d, f, title); });
  return el;
}

// -- the key figures ----------------------------------------------------------------------------------------

function tile(label, value, sub, why, spark, onOpen) {
  const measured = value !== null && value !== undefined;
  const el = h("article", { class: "kpi aop-tile" + (measured ? "" : " nm"), tabindex: "0", role: "button", "aria-label": label + ": " + (measured ? value : "not measured") },
    h("div", { class: "kpi-h" }, h("span", null, label)),
    h("div", { class: "kpi-v" + (measured ? "" : " nm-text") }, measured ? value : "— Not measured"),
    spark || null, h("p", { class: "kpi-sub small" }, measured ? sub || "" : why || ""));
  if (onOpen) { el.setAttribute("data-control", "agent_ops_drill"); el.addEventListener("click", onOpen); el.addEventListener("keydown", (e) => { if (e.key === "Enter") onOpen(); }); }
  return el;
}
function figures(d) {
  const t = d.totals;
  const pts = d.trend.points;
  const tokSpark = sparkline(pts.map((p) => Object.values(p.tokens || {}).reduce((a, b) => a + b, 0) || null));
  const costSpark = sparkline(pts.map((p) => p.cost));
  const gap = (what) => (d.gaps.find((g) => g.what === what) || {}).why;
  const all = () => drill(d, {}, "Every run in the period");
  const cost = t.cost !== null ? money(t.cost, t.currency) : null;
  return h("div", { class: "kpi-strip aop-tiles" },
    tile(pick("Times an AI helper worked", "Runs"), t.runs ? num(t.runs) : null, plural(t.failed, "failed run"), "no agent ran in this period", null, all),
    tile(tw("token", 2, { cap: true }), short(t.tokens), short(t.in) + " in · " + short(t.out) + " out", gap("tokens"), tokSpark, all),
    tile("Cost", cost, t.unpriced ? plural(t.unpriced, "run") + " not priced" : "every run priced",
      t.cost_priced !== null ? money(t.cost_priced, t.currency) + " priced; " + plural(t.unpriced, "run") + " without a price" : gap("cost"), costSpark, all),
    tile(pick("Typical response time", "Median latency"), secs(t.seconds_median), "90th percentile " + (secs(t.seconds_p90) || "not measured"), gap("latency"), null, all),
    tile(pick("Tool uses", "Tool calls"), t.tool_calls !== null ? num(t.tool_calls) : null, d.tools.timed ? "latency measured" : "latency not measured", "the runs recorded no tool calls", null, all),
    tile(pick("Repeated text reused", "Prompt cache share"), t.cached_share !== null ? t.cached_share + "%" : null, short(t.cached) + " cached input tokens", "no run recorded cached tokens", null, null));
}

// -- by role, trend, heatmap --------------------------------------------------------------------------------

// A bar's label names records (a harness, a model, a pack, a tool): the record's own words, never reworded.
function asData(el) { el.querySelectorAll(".bar-l > span, .bar-l > a").forEach((x) => x.setAttribute("data-ud", "")); return el; }

function byRole(d) {
  const rows = d.by_role;
  const label = (r) => roleWord(r.role) + " · " + r.harness + " · " + r.model;
  const body = rows.length ? [
    asData(bars({ rows: rows.slice(0, 12).map((r) => ({ label: label(r), value: r.tokens, display: short(r.tokens) + " tokens", sub: plural(r.runs, "run"),
      why: "its runs recorded no token counts" })), unit: "tokens" })),
    dataTable([{ label: pick("Helper", "Role"), value: (r) => roleWord(r.role) }, { label: pick("Coding agent", "Harness"), value: (r) => datum(r.harness) },
      { label: "Model", value: (r) => h("span", { class: "mono" }, r.model) }, { label: "Runs", num: true, value: (r) => num(r.runs) },
      { label: "In", num: true, value: (r) => short(r.in) }, { label: "Out", num: true, value: (r) => short(r.out) },
      { label: "Cost", num: true, value: (r) => money(r.cost, r.currency) || (r.cost_priced !== null ? nm("part priced", money(r.cost_priced, r.currency) + " priced") : null) },
      { label: "Median", num: true, value: (r) => secs(r.seconds_median) }, { label: "p90", num: true, value: (r) => secs(r.seconds_p90) },
      { label: pick("Tool uses", "Tool calls"), num: true, value: (r) => (r.tool_calls === null ? null : num(r.tool_calls)) },
      { label: "Failed", num: true, value: (r) => num(r.failed) }], rows, "Runs by role, harness and model")] : [emptyState(d.project ? "agentops" : "agentops_all", null, { icon: "bot" })];
  const c = card({ title: pick("Each AI helper", "By role, harness and model"), icon: "bot", id: "aop-roles",
    info: pick("Each kind of AI helper with the coding agent and model it ran on: how often, how much text, what it cost and how fast. Select a row to see its runs.",
      "Runs grouped by role, harness and model: tokens in/out, priced cost, latency (median, p90), tool calls and failures. Select a bar or row for its runs.") }, body);
  c.querySelectorAll(".bar-row").forEach((el, i) => drillable(el, d, { role: rows[i].role, harness: rows[i].harness, model: rows[i].model }, label(rows[i])));
  c.querySelectorAll("tbody tr").forEach((el, i) => { el.tabIndex = 0; drillable(el, d, { role: rows[i].role, harness: rows[i].harness, model: rows[i].model }, label(rows[i])); });
  return c;
}

function trend(d) {
  const t = d.trend;
  const series = t.roles.slice(0, 6).map((r, i) => ({ key: r, label: roleWord(r), color: SERIES(i + 1) }));
  const body = t.measured ? [lines({ series, points: t.points.map((p) => ({ label: p.label, values: Object.fromEntries(t.roles.map((r) => [r, (p.tokens || {})[r] ?? null])) })), unit: "tokens" }),
    dataTable([{ label: "When", key: "label" }].concat(series.map((s) => ({ label: s.label, num: true, none: "no run",
      value: (p) => short((p.tokens || {})[s.key] ?? null) }))),
      t.points.filter((p) => Object.keys(p.tokens || {}).length), "Tokens per period by role")]
    : [notMeasured({ why: "no run in the period recorded token counts", how: d.how_runs })];
  return card({ title: pick("AI usage over time", "Tokens over time, by role"), icon: "activity", id: "aop-trend",
    info: "Tokens per " + (d.window === "24h" ? "hour" : "day") + " for each role. A period with no run leaves a gap, never a zero." }, body);
}

function heat(d) {
  const hm = d.heatmap;
  const byProject = hm.by === "project";
  const title = byProject ? pick("Which helper works where", "Role × project") : pick("Which helper worked when", "Role × day");
  if (!hm.cells.length) return card({ title, icon: "table", id: "aop-heat" }, emptyState(d.project ? "agentops" : "agentops_all", null, { icon: "table" }));
  const colLabel = Object.fromEntries(hm.cols.map((c) => [c.key, c.label]));
  return card({ title, icon: "table", id: "aop-heat", info: tw("token", 2, { cap: true }) + " per role and " + (byProject ? "project" : "day") + "; darker is more. A hatched cell had runs that recorded no tokens. Select a cell for its runs." },
    heatmap({ rows: hm.rows, rowLabel: roleWord, cols: hm.cols, title,
      cells: hm.cells.map((c) => Object.assign({ row: c.role }, c)), value: (c) => c.tokens,
      display: (c) => (c.tokens === null ? "not measured" : short(c.tokens) + " tokens") + " · " + plural(c.runs, "run") + (c.cost !== null ? " · " + money(c.cost) : ""),
      onCell: (c) => drill(d, Object.assign({ role: c.role }, byProject ? { project: c.col } : { day: c.col }), roleWord(c.role) + " · " + (colLabel[c.col] || c.col)) }),
    dataTable([{ label: pick("Helper", "Role"), value: (c) => roleWord(c.role) }, { label: byProject ? "Project" : "Day", value: (c) => datum(colLabel[c.col] || c.col) },
      { label: "Runs", num: true, value: (c) => num(c.runs) }, { label: "Tokens", num: true, value: (c) => short(c.tokens) }], hm.cells, title));
}

// -- tools, overhead, context, drift, hub -------------------------------------------------------------------

function tools(d) {
  const t = d.tools;
  const gap = d.gaps.find((g) => g.what === "tools" || g.what === "tool latency");
  const rows = t.tools || [];
  const body = !t.measured ? [notMeasured(gap || { why: "no tool call was recorded", how: "" })] : [
    t.timed ? asData(bars({ rows: rows.filter((x) => x.median_ms !== null).slice(0, 10).map((x) => ({ label: x.tool, value: x.median_ms, display: secs(x.median_ms / 1000),
      sub: plural(x.calls, "call"), color: x.median_ms >= 2000 ? "var(--warning-mark)" : SERIES(1), tip: "90th percentile " + secs((x.p90_ms || 0) / 1000) })), unit: "median ms" })) : (gap ? notMeasured(gap) : null),
    dataTable([{ label: "Tool", value: (x) => h("span", { class: "mono" }, x.tool) }, { label: "Calls", num: true, value: (x) => num(x.calls) },
      { label: "Failed", num: true, value: (x) => num(x.failed) }, { label: "Median", num: true, value: (x) => (x.median_ms === null ? null : secs(x.median_ms / 1000)) },
      { label: "p90", num: true, value: (x) => (x.p90_ms === null ? null : secs(x.p90_ms / 1000)) }, { label: "Runs", num: true, value: (x) => num(x.runs) }], rows, "Tools the agents called")];
  const c = card({ title: pick("Tools the AI helpers used", "Tools and their " + "latency"), icon: "clock", id: "aop-tools",
    info: "From Gnomon's own audit trails of each run: which tools were called, how often, how many failed and how long they took. Select a tool for its runs." }, body);
  c.querySelectorAll(".bar-row").forEach((el, i) => drillable(el, d, { tool: rows[i].tool }, rows[i].tool));
  return c;
}

function overhead(d) {
  const o = d.overhead;
  return card({ title: [term("overhead", { cap: true })], icon: "gauge", id: "aop-overhead",
    info: pick("The fixed part every call carries: the coding agent's standing instructions before the work's own context, how many calls one run makes, and how much repeated text was reused.",
      "Per role: the lane's system prompt as a share of the context pack sent (the harness's own part), model calls per run, the prompt cache's share of input, and Gnomon's trims (context that did not fit the window).") },
  o.measured ? dataTable([{ label: pick("Helper", "Role"), value: (r) => roleWord(r.role) },
    { label: pick("Fixed instructions", "System prompt"), num: true, value: (r) => (r.system_tokens === null ? null : short(r.system_tokens) + " tokens") },
    { label: "Share", num: true, value: (r) => (r.system_share === null ? null : r.system_share + "%") },
    { label: pick("Calls per run", "Model calls / run"), num: true, value: (r) => (r.calls_per_run === null ? null : String(r.calls_per_run)) },
    { label: pick("Reused", "Cached"), num: true, value: (r) => (r.cached_share === null ? null : r.cached_share + "%") },
    { label: pick("Cut to fit", "Trims"), num: true, value: (r) => (r.trims === null ? null : num(r.trims)) }], o.roles, "Harness overhead per role")
    : notMeasured(o));
}

function context(d) {
  const c = d.context;
  const packs = (c.packs || []).slice().sort((a, b) => b.with_system - a.with_system);
  const evals = c.evals || [];
  const read = c.platform && c.read ? h("p", { class: "small muted" }, "Packs read for the " + plural(c.read.length, "project") + " whose agents ran in the period.") : null;
  return card({ title: pick("What each AI helper is given", "Context packs against their budgets"), icon: "layers", id: "aop-context",
    info: "Each role's context pack as it would be sent now, with the system prompt, against its budget; the compression audit's findings; and Gnomon's own context cost and metrics evals when they ran." },
  c.measured ? [read, asData(bars({ rows: packs.slice(0, 10).map((p) => ({ label: p.label + (d.project ? "" : " · " + p.title), value: p.with_system, display: short(p.with_system) + " / " + short(p.budget),
    color: p.over_budget ? "var(--warning-mark)" : SERIES(1), sub: p.over_budget ? "over budget" : Math.round(p.prefix_ratio * 100) + "% stable prefix",
    href: "#/p/" + enc(p.project) + "/context" })), unit: "tokens" })),
  h("p", { class: "small" }, Object.keys(c.counts || {}).length ? "Audit findings: " + Object.entries(c.counts).map(([k, n]) => k.replace(/_/g, " ") + " " + n).join(" · ") + "." : "The compression audit finds nothing to cut.")]
    : notMeasured(c),
  evals.length ? dataTable([{ label: "Gnomon eval", value: (e) => datum(e.label || e.eval) }, { label: "Project", value: (e) => datum(e.title) },
    { label: pick("Result", "Verdict"), value: (e) => e.verdict }, { label: "Summary", value: (e) => datum(e.summary || "") }, { label: "When", value: (e) => ago(e.at) }], evals, "Gnomon's context evals")
    : h("p", { class: "small muted" }, "Gnomon's context cost and metrics evals have not run here: run them from Health (Gnomon's audits) to measure the bytes per prompt."));
}

function drift(d) {
  const rows = d.drift;
  return card({ title: [term("context_drift", { cap: true })], icon: "refresh", id: "aop-drift",
    info: "When each role last ran in each project, and how many records it was not given were written since (a decision, an answer, the spec, a merge, a change). Fresh: nothing new since." },
  rows.length ? dataTable([{ label: "Project", value: (r) => datum(r.title) }, { label: pick("Helper", "Role"), value: (r) => roleWord(r.role) },
    { label: "Last ran", value: (r) => ago(r.last_run) }, { label: pick("New records since", "Records since"), num: true, value: (r) => num(r.changes_since) },
    { label: "State", value: (r) => (r.state === "fresh" ? chip("good", "check-circle", "Fresh") : chip("warning", "alert", "Behind")) }], rows.slice(0, 30), "Context drift per role")
    : notMeasured({ why: "no agent ran yet", how: d.how_runs }));
}

function hubCard(d) {
  const x = d.hub;
  return card({ title: "Agent observability hub", icon: "activity", id: "aop-hub",
    info: "The figures a person recorded from the team's agent observability hub (Agent sessions): sessions per coding agent, failures not recovered and heavily reworked files." },
  x.measured ? [h("p", { class: "small" }, plural(x.sessions, "session") + " · " + Object.entries(x.by_harness).map(([k, n]) => k + " " + n).join(" · ") + " · " +
    plural(x.unrecovered, "unrecovered failure") + " · " + plural(x.rework_files, "heavily reworked file")),
  dataTable([{ label: "Project", value: (r) => h("a", { href: "#/p/" + enc(r.project) + "/agent_sessions" }, datum(r.title)) }, { label: "Recorded", value: (r) => ago(r.at) },
    { label: "Sessions", num: true, value: (r) => num(r.sessions) }, { label: "Unrecovered", num: true, value: (r) => num(r.unrecovered) },
    { label: "Reworked files", num: true, value: (r) => num(r.rework_files) }], x.projects, "Hub figures per project")] : notMeasured(x));
}

// -- the Optimise audit -------------------------------------------------------------------------------------

function savingLine(s) {
  const parts = [s.tokens !== null && s.tokens !== undefined ? short(s.tokens) + " tokens" + (s.cacheable ? " cacheable" : "") : null,
    s.cost !== null && s.cost !== undefined ? money(s.cost, s.currency) : null, s.seconds !== null && s.seconds !== undefined ? s.seconds + " s" : null,
    (s.tokens === null || s.tokens === undefined) && s.per_call ? short(s.per_call) + " tokens per call" : null].filter(Boolean);
  return parts.length ? parts.join(" · ") : "not measured";
}
function proposalItem(p, d, redraw) {
  const k0 = KIND[p.kind] || [p.kind, "sparkles"];
  const k = [pick(k0[0], k0[2] || k0[0]), k0[1]];
  const may = mayAct(d.auditors);
  const file = p.card ? chip("good", "check-circle", "Filed as " + p.card) : button("File as a change", { icon: "send", kind: "small", key: "aop-change:" + p.id,
    "data-control": "agent_ops_change", disabled: !may || null, onclick: (e) => act(e.currentTarget.parentNode, async () => {
      if (!needPerson()) return;
      const out = await api("POST", "/api/projects/" + enc(p.project || "_factory") + "/agent-ops/proposals/" + p.id + "/change", Object.assign({ window: d.window }, signed()));
      say((out.already ? "Already filed as " : "Filed as change ") + out.card.id + ", signed and recorded. It waits in the Inbox.", "good");
      redraw();
    }) });
  const go = p.act && p.act.route ? h("a", { class: "btn small quiet", href: p.act.route, "data-key": "aop-go:" + p.id }, icon("arrow-right"), h("span", { class: "lbl" }, "Take me there"))
    : button("See the runs", { icon: "list", kind: "small quiet", key: "aop-runs:" + p.id, onclick: () => drill(d, p.drill || {}, p.title) });
  return h("li", { class: "aop-prop", "data-proposal": p.id }, h("div", { class: "aop-prop-h" }, chip("neutral", k[1], k[0]),
    h("b", { "data-ud": "" }, p.title)),
  h("p", { class: "small", "data-ud": "" }, p.detail),
  h("p", { class: "small aop-save" }, icon("coins"), h("b", null, "Expected saving: " + savingLine(p.saving)), h("span", { class: "muted", "data-ud": "" }, " · " + p.saving.basis),
    p.saving.cost_why ? h("span", { class: "muted" }, " · cost not measured: " + p.saving.cost_why) : null),
  h("div", { class: "btns" }, go, file, p.project_title && !d.project ? h("span", { class: "small muted", "data-ud": "" }, p.project_title) : null));
}
function optimise(d, pid, redraw) {
  const s = d.savings;
  const may = mayAct(d.auditors);
  const rec = button("Record the audit", { icon: "check", kind: "small primary", key: "aop-audit", "data-control": "agent_ops_audit", disabled: !may || null,
    onclick: (e) => act(e.currentTarget.parentNode, async () => {
      if (!needPerson()) return;
      const out = await api("POST", "/api/agent-ops/audit", Object.assign({ window: d.window }, pid ? { project: pid } : {}, signed()));
      say("The Optimise audit is recorded: " + plural(out.proposals.length, "proposal") + ", signed in the " + (pid ? "project's" : "platform's") + " ledger.", "good");
    }) });
  return card({ title: "Optimise", icon: "sparkles", id: "aop-optimise", cls: "aop-opt",
    info: "Concrete changes the records support, found by fixed rules (no AI): cut or reorder a context pack, cache a stable prefix, a cheaper model the role evals allow, a slow tool, a task that needed many rounds. Each says what it would save and on what basis." },
  h("p", { class: "small" }, s.proposals ? plural(s.proposals, "proposal") + " · together " + savingLine({ tokens: s.tokens, cost: s.cost, seconds: s.seconds }) + "." :
    pick("Nothing to optimise in this period by the rules.", "No rule fires on the records in this window.")),
  d.proposals.length ? h("ol", { class: "aop-props plain" }, d.proposals.slice(0, 4).map((p) => proposalItem(p, d, redraw))) : null,
  d.proposals.length > 4 ? h("details", { class: "aop-more" }, h("summary", null, plural(d.proposals.length - 4, "more proposal") + " with smaller savings"),
    h("ol", { class: "aop-props plain", start: "5" }, d.proposals.slice(4, 40).map((p) => proposalItem(p, d, redraw)))) : null,
  h("div", { class: "btns" }, rec, may ? null : h("span", { class: "small muted" }, icon("user"), " An AI architect, developer, IT or operations records it.")));
}

// -- the page and the view ----------------------------------------------------------------------------------

function body(d, pid, redraw) {
  if (!d.totals.runs && !d.context.measured) {
    return [emptyState(pid ? "agentops" : "agentops_all", null, { icon: "bot" }), optimise(d, pid, redraw), pricesCard(d, redraw)];
  }
  return [figures(d), h("div", { class: "aop-grid" }, optimise(d, pid, redraw), byRole(d), trend(d), heat(d), tools(d), overhead(d), context(d), drift(d), hubCard(d), pricesCard(d, redraw))];
}
function filters(pid, redraw) {
  return h("div", { class: "aop-bar", "data-control": "agent_ops_window" }, h("span", { class: "small muted" }, "Period"),
    segmented("aop-window", WINDOWS.map(([v, l]) => [v, l]), windowNow(), (v) => { local.set(KEY, v); redraw(); }, { label: "Period" }));
}
async function load(holder, pid) {
  const redraw = () => load(holder, pid);
  holder.setAttribute("aria-busy", "true");
  const url = (pid ? "/api/projects/" + enc(pid) + "/agent-ops" : "/api/agent-ops") + "?window=" + windowNow();
  try {
    const d = await api("GET", url);
    fill(holder, filters(pid, redraw), body(d, pid, redraw));
  } catch (e) {
    if (e instanceof AuthError) return;
    fill(holder, incidentPanel(e, "Agent operations", { retry: async () => { await redraw(); return true; } }));
  } finally { holder.removeAttribute("aria-busy"); }
}

const LEDE = () => pick("What the AI helpers cost, how fast they answer, what they are given, and where to save.",
  "Runs, tokens, cost, latency, tools, harness overhead, context and drift per role, harness and model, with the Optimise audit.");
const INFO = "Read from the records only: each agent run in the ledgers (Gnomon's cells, Rihma's roles, coding agents through their harness), Gnomon's audit trails, the context packs and the hub's recorded figures. A figure with nothing behind it says not measured and how to measure it.";

export async function renderAgentOps(seq) {
  const main = $("#main");
  const holder = h("div", { class: "aop", "aria-live": "polite" });
  fill(main, pageHead("Agent operations", LEDE(), { icon: "gauge", info: INFO }), holder);
  document.title = "Agent operations · Rihmasto.ai";
  if (seq !== undefined && seq !== S.seq) return;
  await load(holder, null);
  if (nav.refreshShell) nav.refreshShell();
}

// The project's view (capsules.js registers it in the Agents capsule).
export function render(p) {
  const holder = h("div", { class: "aop", "aria-live": "polite" });
  const head = h("div", { class: "q" }, h("h2", { class: "view-h", tabindex: "-1" }, h("span", { class: "vh-scope", "data-ud": "" }, p.meta.title + " · "), "Agent operations"),
    h("p", null, LEDE()));
  load(holder, p.meta.id);
  return h("div", null, head, holder);
}
