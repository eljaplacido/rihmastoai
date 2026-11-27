/* Audits & evals (kernel/gnomon_evals*.py, kernel/role_evals.py; FR-EVL1): Gnomon's audits, benchmarks and evals
   on a project's repository, each with its last result, trend and findings, Run now as a job whose log streams on
   the Jobs page, and Make it a change on a finding; the same across projects on the Health page; and Rihma's own
   role evals in Models setup, comparing models per eval set. A result is passed, failed or not measured with why:
   not measured is never shown as passed. */

import { h, fill, icon, chip, api, act, say, signed, needPerson, enc, button, card, empty, ago, link } from "./core.js";
import { emptyState } from "./words.js";
import { openHandoff } from "./goal.js";

const VERDICT = {
  passed: ["good", "check-circle", "Passed"], failed: ["critical", "x-circle", "Failed"],
  "not measured": ["nm", "dashed", "Not measured"], "not run yet": ["neutral", "clock", "Not run yet"],
};
const SQ = { passed: "ok", failed: "bad", "not measured": "nm" };
const MODELS = { none: "calls no model", listing: "asks each endpoint for its model list", roles: "calls the lane's models" };

function verdict(state) {
  const [tone, ic, word] = VERDICT[state] || VERDICT["not measured"];
  return chip(tone, ic, word, { "data-verdict": state });
}

function trend(rows) {
  return h("span", { class: "hl-trend", role: "img", "aria-label": "Last runs: " + (rows.map((t) => t.verdict).join(", ") || "none") },
    rows.map((t) => h("span", { class: "hl-sq " + (SQ[t.verdict] || "nm"), tip: t.verdict + (t.score != null ? " · " + t.score : "") + " · " + ago(t.at) })));
}

const base = (pid) => "/api/projects/" + enc(pid) + "/evals";
export const EVALS_POLL_MS = 3000;

function evalRow(pid, e, again) {
  const last = e.last;
  const tools = h("div", { class: "mdl-tools" });
  const run = button(e.running ? "Running" : "Run now", { icon: "play", kind: "small", key: "eval-run:" + e.id,
    "data-control": "evals_run", disabled: e.running || !e.available, aria: "Run the Gnomon " + e.label + " now" });
  run.addEventListener("click", () => act(tools, async () => {
    if (!needPerson()) return;
    const out = await api("POST", base(pid) + "/" + enc(e.id) + "/run", signed());
    say("The " + e.label + " is running as job " + out.job.id + ": its log streams on the Jobs page.", "info");
    await again();
  }));
  const hist = h("details", { class: "hl-ev", "data-control": "evals_history" }, h("summary", null, "History"),
    e.trend.length ? h("ul", { class: "plain small" }, e.trend.slice().reverse().map((t) => h("li", null, verdict(t.verdict),
      " " + ago(t.at) + (t.score != null ? " · " + e.score + ": " + t.score + (e.unit === "%" ? "%" : "") : ""))))
      : h("p", { class: "muted small" }, "No run yet."));
  tools.append(run);
  return h("li", { class: "mdl-row", "data-key": "eval:" + e.id },
    h("div", { class: "mdl-main", "data-ud": "" },      // the audit's name and description are Gnomon's catalogue
      h("b", null, e.label), h("span", { class: "mono muted small" }, " " + e.id),
      h("div", { class: "mdl-chips" }, verdict(e.state), last ? h("span", { class: "muted small" }, "ran " + ago(last.at)
        + (last.via ? " · " + last.via : "")) : null, trend(e.trend || []),
      e.scheduled ? chip("info", "clock", "Check, every " + (e.every || "?")) : null,
      last && last.new_findings ? chip("warning", "alert", last.new_findings + " new issue" + (last.new_findings === 1 ? "" : "s")) : null),
      last ? h("p", { class: "hl-sum" }, last.summary) : h("p", { class: "muted small" }, e.measures + "."),
      h("p", { class: "muted small" }, "Takes " + e.duration + "; " + (MODELS[e.models] || e.models)
        + (e.runs_code ? "; runs the project's own check" : "") + (e.scope === "harness" ? "; measures Gnomon on this machine" : "")),
      e.available ? null : h("p", { class: "note warning small" }, icon("alert"), h("span", null, e.why_not)),
      hist),
    tools);
}

function findingRow(pid, f, again) {
  const tools = h("div", { class: "mdl-tools" });
  if (f.card) tools.append(h("a", { href: link(pid, "inbox") + "/" + enc(f.card), class: "btn small quiet", "data-key": "ef-card:" + f.id }, "Change " + f.card));
  else if (f.severity === "issue") {
    const make = button("Make it a change", { icon: "edit", kind: "small", key: "ef-change:" + f.id, "data-control": "evals_make_change",
      aria: "Make the finding a change proposal: " + f.title });
    make.addEventListener("click", () => act(tools, async () => {
      if (!needPerson()) return;
      const out = await api("POST", base(pid) + "/findings/" + enc(f.id) + "/change", signed());
      say("Change " + out.card + " filed from the finding: it waits in the Inbox.", "good");
      await again();
    }));
    const hand = button("Hand off to Claude Code", { icon: "send", kind: "small quiet", key: "ef-handoff:" + f.id,
      "data-control": "handoff", aria: "Hand this finding off to Claude Code (or another coding agent)" });
    hand.addEventListener("click", () => openHandoff(pid, { to: "claude-code" }));
    tools.append(make, hand);
  }
  const required = f.severity === "issue";
  const fixes = (f.evidence || []).filter((x) => /^fix:/i.test(x));
  const evidence = (f.evidence || []).filter((x) => !/^fix:/i.test(x));
  return h("li", { class: "mdl-row", "data-key": "finding:" + f.id, "data-actionability": required ? "required" : "review" },
    h("div", { class: "mdl-main", "data-ud": "" },      // a finding is the audit's own words
      h("div", { class: "mdl-chips" }, chip(required ? "warning" : "neutral", required ? "alert" : "info",
        required ? "Action needed" : "For review"), f.new ? chip("info", "sparkles", "New") : null,
      h("span", { class: "muted small" }, f.label)),
      h("p", { class: "hl-sum" }, f.title),
      fixes.length ? h("p", { class: "hl-sum" }, h("b", null, "Suggested action: "),
        fixes.map((x) => x.replace(/^fix:\s*/i, "")).join("; ")) : null,
      evidence.length ? h("details", { class: "hl-ev" }, h("summary", null, "Evidence"), h("pre", { class: "code" }, evidence.join("\n"))) : null),
    tools);
}

// The open findings of the project's own findings file (kernel/native_guide.py, FR-SRC2), each at its place in the code.
const SEV_TONE = { critical: "critical", high: "critical", major: "warning", medium: "warning" };
function ownFindings(pid, own) {
  if (!own || !own.applies) return null;
  const head = h("h4", { class: "small" }, "From the project's own findings file");
  if (!own.sources.length) {
    return h("div", { "data-control": "evals_own_findings" }, head, emptyState("checks", null, { icon: "info",
      what: "The project's own findings file is not mapped: its issues do not show here yet.",
      how: "Map it in What Rihmasto understood on the Overview (Project's own sources), or tell Rihma: use the issues file as findings." }));
  }
  return h("div", { "data-control": "evals_own_findings" }, head,
    h("p", { class: "muted small" }, own.open + " open, read " + ago(own.read_at) + " from " + own.sources.map((s) => s.glob).join(", ")),
    own.findings.length ? h("ul", { class: "emb-list", id: "ev-own-findings" }, own.findings.map((f) => h("li", { class: "mdl-row", "data-key": "own-finding:" + f.id },
      h("div", { class: "mdl-main", "data-ud": "" },     // the project's own words
        h("div", { class: "mdl-chips" }, chip(SEV_TONE[f.severity] || "neutral", "alert", f.severity), h("span", { class: "mono muted small" }, " " + f.id),
          h("span", { class: "muted small" }, " " + f.status)),
        h("p", { class: "hl-sum" }, f.title),
        h("p", { class: "muted small" }, h("code", null, f.where))))))
      : emptyState("checks", null, { icon: "check-circle", what: "No open finding in the project's own file.",
        how: "A new line in it shows here once the sources are read again (Read again, or the watch on a new commit)." }));
}

// A project's Audits & evals, under its Health tab.
export function evalsCard(pid) {
  const box = h("div", { id: "ev-box" }, card({ title: "Audits & evals", icon: "shield", id: "ev-card" }, h("p", { class: "muted" }, "Loading…")));
  const again = async () => {
    const data = await api("GET", base(pid));
    if (!box.isConnected && box.dataset.drawn) return;
    box.dataset.drawn = "1";
    const g = data.gnomon || {};
    const issues = (data.findings || []).filter((f) => f.severity === "issue");
    fill(box, card({ title: "Audits & evals", icon: "shield", id: "ev-card", info: "Gnomon's capability-based audits, benchmarks "
      + "and evals, run headless on this project's repository. A model-calling eval on a confidential project only uses local or private endpoints." },
    h("p", { class: "hl-line", id: "ev-line" }, icon(g.found ? "shield" : "alert"), h("span", null, (g.found ? "Gnomon " + g.version : "Gnomon is not on this machine")
      + " · " + data.line + ".")),
    h("ul", { class: "emb-list", id: "ev-list" }, data.evals.map((e) => evalRow(pid, e, again))),
    h("h4", { class: "small" }, "Findings"),
    h("p", { class: "muted small" }, "Action-needed findings affect the audit result and can be made a change. "
      + "For-review items are information, not failures."),
    issues.length || (data.findings || []).length ? h("ul", { class: "emb-list", id: "ev-findings" },
      data.findings.slice(0, 30).map((f) => findingRow(pid, f, again))) : emptyState("checks", null, { icon: "check-circle", what: "No finding in the latest runs: each issue an audit finds appears here, with its evidence.",
        how: "Run one of the audits above; a finding can then be made a change with one click." }),
    ownFindings(pid, data.own_findings)));
    // A run is a job: while one runs its row says Running, and its result and findings show here when it ends.
    if (data.evals.some((e) => e.running)) setTimeout(() => { if (box.isConnected) again().catch(() => null); }, EVALS_POLL_MS);
  };
  again().catch((e) => fill(box, card({ title: "Audits & evals", icon: "shield", id: "ev-card" }, empty("alert", e.message))));
  return box;
}

// Every project's latest audits, on the Health page.
export function evalsFactoryCard() {
  const box = h("div", { id: "ev-all", "data-control": "evals_all" }, card({ title: "Audits & evals", icon: "shield", id: "ev-all-card" }, h("p", { class: "muted" }, "Loading…")));
  api("GET", "/api/evals").then((data) => {
    const g = data.gnomon || {};
    const rows = (data.projects || []).filter((p) => p.results.length);
    const cell = (r) => h("span", { class: "hl-cell" }, verdict(r.verdict),
      h("span", { class: "small" }, " " + r.label + (r.new_findings ? " (" + r.new_findings + " new)" : "")));
    const row = (p) => h("tr", { "data-key": "ev-p:" + p.project },
      h("th", null, h("a", { href: link(p.project, "checks") }, p.title || p.project)),
      h("td", null, h("div", { class: "mdl-chips" }, p.results.map(cell))));
    const table = h("div", { class: "tbl" }, h("table", null,
      h("thead", null, h("tr", null, h("th", null, "Project"), h("th", null, "Latest audits"))),
      h("tbody", null, rows.map(row))));
    fill(box, card({ title: "Audits & evals", icon: "shield", id: "ev-all-card" },
      h("p", { class: "muted small" }, g.found ? "Gnomon " + g.version + " on this machine: "
        + data.catalogue.filter((c) => c.available).length + " of " + data.catalogue.length + " audits run here." : "Gnomon is not on this machine."),
      rows.length ? table : empty("shield", "No Gnomon audit has run yet: open a project's Health tab to run one.")));
  }).catch((e) => fill(box, card({ title: "Audits & evals", icon: "shield", id: "ev-all-card" }, empty("alert", e.message))));
  return box;
}

// Models setup: Rihma's own evals per role, comparing models.
export function roleEvalsCard() {
  const box = h("div", { id: "re-box" }, card({ title: "On our evals", icon: "flask", id: "re-card" }, h("p", { class: "muted" }, "Loading…")));
  const draw = async () => {
    const data = await api("GET", "/api/evals/roles");
    const role = h("select", { id: "re-role", "aria-label": "Role to evaluate" }, h("option", { value: "" }, "Both roles"),
      data.roles.map((r) => h("option", { value: r }, r)));
    const models = h("input", { id: "re-models", autocomplete: "off", spellcheck: "false", placeholder: "configured, fallback, model@endpoint",
      "aria-label": "Models to compare (comma between)" });
    const tools = h("div", { class: "btns" });
    const run = button("Compare models", { icon: "play", kind: "primary", key: "re-run", "data-control": "evals_roles_run" });
    run.addEventListener("click", () => act(tools, async () => {
      if (!needPerson()) return;
      const picked = models.value.split(",").map((s) => s.trim()).filter(Boolean);
      const out = await api("POST", "/api/evals/roles/run", Object.assign({ role: role.value || null, models: picked.length ? picked : null }, signed()));
      say("The role evals are running as job " + out.job.id + ": the log streams on the Jobs page.", "info");
    }));
    tools.append(run);
    const bySet = data.sets.map((s) => ({ s, rows: data.results.filter((r) => r.set === s.id) })).filter((x) => x.rows.length);
    fill(box, card({ title: "On our evals", icon: "flask", id: "re-card", info: "Each role's eval set, on neutral fixtures, judged by rule: "
      + "intake questions and spec testability for the analyst, Ask Rihma answers and goal plans for the assistant. Nothing of a project is sent." },
    data.lines.length ? h("ul", { class: "plain small", id: "re-lines" }, data.lines.map((l) => h("li", null, l)))
      : h("p", { class: "muted small", id: "re-lines" }, "No role eval has run yet."),
    bySet.length ? h("div", { class: "tbl" }, h("table", null, h("thead", null, h("tr", null, h("th", null, "Eval set"), h("th", null, "Model"), h("th", null, "Right"))),
      h("tbody", null, bySet.flatMap(({ s, rows }) => rows.map((r) => h("tr", { "data-key": "re:" + s.id + ":" + r.candidate },
        h("th", null, s.label), h("td", null, r.candidate + (r.local ? " (local)" : "")),
        h("td", null, r.refused ? chip("nm", "dashed", "Refused: " + r.refused) : r.correct + " of " + r.cases + " (" + r.score_pct + "%)"))))))) : null,
    h("div", { class: "row2" }, h("div", { class: "field" }, h("label", { for: "re-role" }, "Role"), role),
      h("div", { class: "field" }, h("label", { for: "re-models" }, "Models (comma between; empty: configured and fallback)"), models)),
    tools));
  };
  draw().catch((e) => fill(box, card({ title: "On our evals", icon: "flask", id: "re-card" }, empty("alert", e.message))));
  return box;
}
