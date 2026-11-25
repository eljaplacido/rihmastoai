/* The Assessment view: an existing system judged from every perspective (kernel/assess.py). The rules'
   findings come first, each with its evidence, severity and suggested change; the panel's proposals stay
   apart, as opinions; what was not measured says why; each version says what changed since the one before.
   Assess now and File as changes are signed writes, and the kernel decides whether they stand. */

import { pick, viewWord } from "./words.js";
import {
  S, h, fill, icon, chip, api, say, signed, needPerson, enc, plural, cap, short, ago, card, button, empty, link,
  personBadge, agentBadge,
} from "./core.js";
import { openAssistant, send as askRihma } from "./assistant.js";
import { watch as pwatch, progressUrl } from "./progress.js";

const VERDICT = { failed: ["critical", "x-circle", "Finding"], "not measured": ["nm", "dashed", "Not measured"],
  passed: ["good", "check-circle", "Passed"], "not applicable": ["neutral", "info", "Not applicable"] };
const SEVERITY = { critical: "critical", high: "critical", medium: "warning", low: "info", info: "neutral" };
const CLASSES = [["new_requirement", "New requirement: a business decision first"], ["change_request", "Change request"],
  ["defect", "Defect"], ["infra_change", "Infra change: IT decides"]];
let onPick = () => {};
let suggested = new Map();     // finding id -> its suggested kind and why (kernel/assess_priority.py)
let handed = false;              // the progress view just handed over: the result comes in softly

function verdictChip(v) { const t = VERDICT[v] || ["neutral", "info", v]; return chip(t[0], t[1], t[2]); }
function severityChip(s, n) {
  if (!s) return null;
  const tone = SEVERITY[s] || "neutral";
  return chip(tone, null, n ? n + " " + s : cap(s), { class: "chip " + tone + " as-sev" });
}
function where(e) {
  if (e.line) return h("span", null, h("span", { class: "mono" }, e.file + ":" + e.line), " ", h("code", null, e.text || ""));
  if (e.file) return h("span", null, h("span", { class: "mono" }, e.file), " ", e.fact || "");
  return h("span", null, e.fact || "");
}

// While an assessment runs, its live progress (cockpit/static/progress.js) shows each area as it runs and
// ends; when it ends, the view hands over to the result.
function finished(m) {
  const r = m.result || {};
  return "Finished: " + (r.id || "the assessment") + " recorded, " + plural(r.findings || 0, "finding") + " by rule"
    + (r.proposed ? " and " + plural(r.proposed, "proposal") + " from the panel" : "") + ". Opening the result…";
}

function liveCard(pid, a, kit, fresh) {
  return pwatch({ url: progressUrl(pid, "assessment"), cancelUrl: "/api/projects/" + enc(pid) + "/assessment/cancel",
    cancelAttrs: { "data-control": "cancel_assessment" }, attrs: { "data-control": "assessment_progress" }, id: "as-prg",
    icon: "gauge", fresh,
    title: "Assessing", seed: fresh ? null : a.progress, doneWords: finished,
    onEnd: () => { handed = true; kit.settle(["#as-sum-h", '[data-key="assess-now"]']); } });
}

function actions(pid, a, kit, slot) {
  const running = a.run && a.run.state === "running";
  const panel = h("input", { type: "checkbox", id: "as-panel", "data-key": "as-panel", disabled: !a.panel_available || running || null });
  const assess = button(running ? "Assessing…" : "Assess now", { icon: "gauge", kind: "small primary", key: "assess-now",
    "data-control": "run_assessment", disabled: running || !a.has_repo || null });
  assess.addEventListener("click", () => {
    if (!needPerson()) return;
    const w = liveCard(pid, a, kit, true);          // the progress shows at once, while the request is on its way
    fill(slot, w.el);
    kit.run(assess, assess.parentNode, async () => {
      try {
        const out = await api("POST", "/api/projects/" + enc(pid) + "/assessment", Object.assign({ panel: panel.checked }, signed()));
        w.release();
        say(out.run.state === "done" ? out.run.id + " recorded by rule, signed by " + S.person.trim() + "."
          : "Assessing" + (out.run.panel ? " by rule, then with the panel" : "") + ", signed by " + S.person.trim()
            + ". Each area shows here as it ends.", "good");
      } catch (e) {
        w.stop();
        fill(slot);
        throw e;
      }
    }).then(() => {                                  // while it runs, a second one cannot be asked for
      if (w.stopped || w.ended) return;
      assess.disabled = true;
      panel.disabled = true;
      assess.querySelector(".lbl").textContent = "Assessing…";
    });
  });
  const r = a.run;
  const state = !r ? null : r.state === "failed"
    ? h("p", { class: "note warning", role: "status" }, icon("alert"), h("span", null, "The last assessment failed: " + r.error))
    : r.state === "cancelled" ? h("p", { class: "note", role: "status" }, icon("info"), h("span", null, "The last assessment was "
      + (r.error || "cancelled") + ", between two steps: nothing was recorded."))
      : null;
  return card({ title: pick("Assess the code", "Assess the repository"), icon: "gauge", id: "as-run",
    info: "Reads what the factory holds on main, from git's objects and never a checkout, and judges it by rule from five "
      + "perspectives. Each finding names its evidence; what the files cannot show reads \"not measured\". With the panel, its "
      + "perspectives propose more through a model, kept apart as opinions. Every assessment is a new version in the ledger." },
  h("div", { class: "btns" }, assess,
    h("label", { class: "as-check" }, panel, "Ask the panel too"),
    a.panel_available ? null : h("span", { class: "muted small" }, "The panel needs the cockpit's model; on the command line: rihmasto assess "
      + pid + " --with-model")),
  state);
}

function teach(a) {
  return h("div", { class: "empty teach", "data-empty": "assessment" }, h("p", { class: "empty-t" }, a.has_repo ? "Not assessed yet."
    : pick("There is no existing code to assess.", "No repository to assess.")),
    h("p", { class: "empty-how" }, a.has_repo
      ? pick("Assess now reads this system's code by fixed rules and lists what to fix: how changes are checked and released, upkeep, "
        + "security, compliance, and how it is built and run. Each finding points to where it was found, with how serious it is and a suggested change.",
      "Assess now reads this system's repository by rule and tells you what to fix: CI/CD governance, maintenance, "
        + "security (the red team's static layer), compliance, and architecture and operations. Each finding names a file and a "
        + "line, or a measured fact, with a severity and a suggested change.")
      : pick("Bring in an existing system first (New project, adopt), then assess it here.", "Adopt an existing system first (rihmasto adopt), then assess it here.")),
    h("p", { class: "muted small" }, pick("Then tick the findings you want fixed and send them as changes: each is decided like any change, "
      + "and a business decision comes first.", "Then tick the findings you want fixed and file them as changes: each goes round the "
      + "change loop, and a business decision comes first.")));
}

function summaryCard(a) {
  const r = a.latest;
  const c = r.counts || {};
  const sev = (a.severities || []).filter((s) => (c.by_severity || {})[s]).map((s) => severityChip(s, c.by_severity[s]));
  const since = r.since;
  const arrive = handed;
  handed = false;
  return card({ title: r.id + " of revision " + short(r.revision), icon: "file-check", id: "as-sum", cls: arrive ? "prg-arrive" : null },
    h("p", null, "Recorded ", ago(r.at), " by ", personBadge(r.asked_by.person, r.asked_by.persona), " on ",
      h("span", { class: "mono" }, r.ref), ". ", plural(c.findings || 0, "finding"), " by rule", sev.length ? ": " : ".", sev,
      c.proposed ? h("span", null, " · " + plural(c.proposed, "proposal") + " from the panel, kept apart") : null),
    since ? h("p", { class: "small" }, "Since " + since.previous + ": " + since.new.length + " new, " + since.resolved.length
      + " resolved, " + since.still.length + " still open" + (since.unmeasured.length ? ", " + since.unmeasured.length + " no longer measured" : "") + ".")
      : h("p", { class: "muted small" }, "The first version: the next one says what changed since."),
    h("p", { class: "muted small" }, "Red team (static): " + (r.scan || {}).verdict + ". "
      + ((r.scan || {}).sarif ? "Its SARIF is " + r.scan.sarif + " in the project's folder; ingest it into the security gate with rihmasto security ingest."
        : (r.scan || {}).note || "")));
}

function findingRow(pid, f, filed, picked) {
  const id = "as-pick-" + f.id;
  const box = h("input", { type: "checkbox", id, "data-key": "pick:" + f.id });
  box.checked = picked.has(f.id);
  box.addEventListener("change", () => { if (box.checked) picked.add(f.id); else picked.delete(f.id); });
  const x = filed[f.key];
  return h("li", { class: "as-row", "data-id": f.id },
    h("div", { class: "as-h" }, box, h("label", { for: id }, h("b", { class: "mono" }, f.id), " " + f.title), severityChip(f.severity),
      f.by === "model_proposed" ? agentBadge("panel: " + String(f.panel || "").replace("_", " "), null) : null,
      x ? h("a", { class: "small", href: link(pid, "changes", x.card) }, "Filed as " + x.card + (x.state ? " (" + x.state + ")" : "")) : null),
    f.summary ? h("p", { class: "small" }, cap(f.summary) + ".") : null,
    f.why ? h("p", { class: "small" }, f.why) : null,
    (f.evidence || []).length ? h("ul", { class: "plain as-ev" }, f.evidence.map((e) => h("li", null, where(e)))) : null,
    (f.rests_on || []).length ? h("p", { class: "small" }, "Rests on: ", f.rests_on.map((x2) => chip(x2.found ? "good" : "warning",
      x2.found ? "check" : "alert", x2.ref + (x2.found ? "" : ": not found in the repository")))) : null,
    f.suggestion ? h("p", { class: "small as-fix" }, h("b", null, "Suggested change: "), f.suggestion) : null,
    x && x.state === "open" ? null : kindField(f));
}

// The kind this finding is filed as: Rihma's suggestion, with its reason, which the person may change.
function kindField(f) {
  const s = suggested.get(f.id);
  if (!s) return null;
  const id = "as-kind-" + f.id;
  const why = id + "-why";
  const sel = h("select", { id, "data-key": "cls:" + f.id, class: "as-kind", "aria-describedby": why },
    CLASSES.map(([v, t]) => h("option", { value: v, selected: v === s.suggested || null }, t.split(":")[0])));
  return h("p", { class: "small as-kind-row" }, h("label", { for: id }, "File " + f.id + " as "), sel,
    h("span", { id: why, class: "muted" }, " Suggested: " + s.suggested_why + "."));
}

function otherRow(c) {
  return h("li", { class: "as-row" }, h("div", { class: "as-h" }, verdictChip(c.verdict), h("span", null, c.title)),
    c.reason || c.summary ? h("p", { class: "small muted" }, cap(c.reason || c.summary) + ".") : null);
}

function perspectiveCard(pid, a, key, label, picked) {
  const checks = a.latest.checks.filter((c) => c.perspective === key);
  const failed = checks.filter((c) => c.verdict === "failed");
  const unmeasured = checks.filter((c) => c.verdict === "not measured");
  const rest = checks.filter((c) => c.verdict === "passed" || c.verdict === "not applicable");
  return card({ title: label, icon: "shield", id: "as-p-" + key, cls: "as-persp",
    tools: chip(failed.length ? "warning" : "good", failed.length ? "alert" : "check-circle", plural(failed.length, "finding")) },
  failed.length ? h("ul", { class: "plain as-list" }, failed.map((f) => findingRow(pid, f, a.filed || {}, picked)))
    : h("p", { class: "muted small" }, "No finding by rule."),
  unmeasured.length ? h("ul", { class: "plain as-list" }, unmeasured.map(otherRow)) : null,
  rest.length ? h("details", { class: "as-more" }, h("summary", null, plural(rest.length, "check") + " passed or not applicable"),
    h("ul", { class: "plain as-list" }, rest.map(otherRow))) : null);
}

function proposalsCard(pid, a, picked) {
  const ps = a.latest.proposals || [];
  const panel = a.latest.panel || {};
  return card({ title: "The panel's proposals", icon: "bot", id: "as-props",
    info: "Each perspective of the intake panel read the inventory and the rules' results through a model and proposed what the "
      + "rules cannot see. A proposal is an opinion, never a fact: it is not counted with the findings, and what it rests on is "
      + "checked against the repository." },
  !panel.used ? h("p", { class: "muted small" }, "Not asked: " + (panel.reason || "no model was given") + ".")
    : ps.length ? h("ul", { class: "plain as-list" }, ps.map((f) => findingRow(pid, f, a.filed || {}, picked)))
      : h("p", { class: "muted small" }, "The panel proposed nothing further."),
  (panel.errors || []).length ? h("p", { class: "note warning" }, icon("alert"), h("span", null, panel.errors.map((e) => e.perspective
    + ": " + e.error).join("; "))) : null);
}

// Tick or untick findings by id, in the set and on the page at once.
function tick(picked, ids, on) {
  ids.forEach((id) => {
    if (on) picked.add(id); else picked.delete(id);
    const box = document.querySelector('input[data-key="pick:' + CSS.escape(id) + '"]');
    if (box) box.checked = on;
  });
}

// The suggested order (kernel/assess_priority.py, by rule) with its why, quick selections, and Ask Rihma.
function priorityBlock(a, picked) {
  const order = a.priority || [];
  const all = order.map((r) => r.id);
  const severe = order.filter((r) => r.severity === "critical" || r.severity === "high").map((r) => r.id);
  const top = all.slice(0, Math.min(5, all.length));
  const count = h("span", { class: "muted small", role: "status", "aria-live": "polite" });
  const shown = () => { count.textContent = plural(picked.size, "finding") + " ticked"; };
  const pick = (label, ids, key, on = true) => button(label, { kind: "small", key, type: "button", disabled: !ids.length || null,
    onclick: () => { tick(picked, on ? ids : Array.from(picked), on); shown(); } });
  document.removeEventListener("change", onPick);      // one listener, for the view drawn last
  onPick = (e) => { if (e.target && String(e.target.dataset.key || "").startsWith("pick:")) shown(); };
  document.addEventListener("change", onPick);
  shown();
  return h("div", { class: "as-prio" },
    order.length ? h("details", { class: "as-more", open: true }, h("summary", null, "Suggested order: fix these first"),
      h("ol", { class: "small" }, order.slice(0, 5).map((r) => h("li", null, h("b", { class: "mono" }, r.id), " " + r.title,
        h("span", { class: "muted" }, ": " + r.why + "."))))) : h("p", { class: "muted small" }, "Nothing open to prioritise."),
    h("div", { class: "btns" },
      pick("Select the top " + top.length, top, "as-top"),
      pick("Select critical and high (" + severe.length + ")", severe, "as-severe"),
      pick("Select all open (" + all.length + ")", all, "as-all"),
      pick("Clear", all, "as-clear", false),
      button("Ask Rihma what to fix first", { icon: "bot", kind: "small", key: "as-ask", type: "button", "data-control": "assessment_ask",
        onclick: () => { openAssistant(); askRihma("Which findings should I fix first, and why?"); } })),
    count);
}

// The kind chosen on each ticked finding's row.
function kindsOf(picked) {
  const out = {};
  picked.forEach((id) => {
    const sel = document.querySelector('select[data-key="cls:' + CSS.escape(id) + '"]');
    if (sel) out[id] = sel.value;
  });
  return out;
}

function fileForm(pid, a, picked, kit) {
  const send = button("File the ticked findings as changes", { icon: "send", kind: "primary", key: "as-file", type: "submit",
    "data-control": "assessment_changes" });
  const form = h("form", { class: "form panel", "aria-labelledby": "as-file-h", novalidate: true },
    h("h3", { id: "as-file-h" }, "Fix what matters"),
    h("p", { class: "small muted" }, "Tick findings above, or choose them here, then file them: each becomes a change card from "
      + a.latest.id + " as the kind shown on it (Rihma suggests one for each, with why; change any), signed with your name. "
      + "A finding whose card is still open is not filed twice."),
    priorityBlock(a, picked),
    h("div", { class: "btns" }, send));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!picked.size) { say("Tick at least one finding first.", "warn"); return; }
    if (!needPerson()) return;
    kit.run(send, form, async () => {
      const out = await api("POST", "/api/projects/" + enc(pid) + "/assessment/changes",
        Object.assign({ findings: Array.from(picked), version: a.latest.id, classes: kindsOf(picked) }, signed()));
      const opened = out.opened.map((c) => c.card + " (" + c.finding + ")").join(", ");
      say((opened ? "Filed " + opened + "." : "Nothing new filed.")
        + (out.skipped.length ? " Skipped " + out.skipped.map((s) => s.finding + ": " + s.why).join("; ") + "." : ""), "good");
      await kit.settle(['[data-key="as-file"]']);
    });
  });
  return form;
}

function historyCard(a) {
  return card({ title: "Versions", icon: "layers", id: "as-hist" },
    h("ul", { class: "plain as-list" }, a.history.slice().reverse().map((e) => h("li", { class: "as-row" },
      h("div", { class: "as-h" }, h("b", { class: "mono" }, e.id), h("span", { class: "mono muted" }, short(e.revision)),
        h("span", null, ago(e.at) + " · " + plural((e.counts || {}).findings || 0, "finding") + (e.panel ? " · with the panel" : "")),
        e.intact ? chip("good", "check-circle", "sha256 matches") : chip("critical", "x-circle", "changed since recorded"))))));
}

export function viewAssessment(p, ctx, kit) {
  const pid = p.meta.id;
  const a = ctx.assessment;
  const head = kit.viewHead(viewWord("assessment", "Assessment"), pick("What should this system fix: how it is released, kept up, secured, kept compliant and run?",
    "What should this system fix, from CI/CD, maintenance, security, compliance and operations?"));
  if (!a || a.error) return h("div", null, head, empty("gauge", (a && a.error) || "The assessment could not be read."));
  const slot = h("div", { class: "as-live" });
  if (a.run && a.run.state === "running") fill(slot, liveCard(pid, a, kit, false).el);
  const out = h("div", { class: "assess" }, head, actions(pid, a, kit, slot), slot);
  if (!a.latest) {
    out.append(a.problem ? h("p", { class: "note warning" }, icon("alert"), h("span", null, a.problem)) : teach(a));
    return out;
  }
  const picked = new Set();
  suggested = new Map((a.priority || []).map((r) => [r.id, r]));
  out.append(summaryCard(a));
  Object.entries(a.perspectives || {}).forEach(([key, label]) => out.append(perspectiveCard(pid, a, key, label, picked)));
  out.append(proposalsCard(pid, a, picked), fileForm(pid, a, picked, kit), historyCard(a));
  return out;
}
