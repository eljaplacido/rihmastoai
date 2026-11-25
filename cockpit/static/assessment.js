/* The Assessment view: an existing system judged from every perspective (kernel/assess.py). The rules'
   findings come first, each with its evidence, severity and suggested change; the panel's proposals stay
   apart, as opinions; what was not measured says why; each version says what changed since the one before.
   Assess now and File as changes are signed writes, and the kernel decides whether they stand. */

import {
  S, h, icon, chip, api, say, signed, needPerson, enc, nav, plural, cap, short, ago, card, button, empty, link,
  personBadge, agentBadge,
} from "./core.js";

const VERDICT = { failed: ["critical", "x-circle", "Finding"], "not measured": ["nm", "dashed", "Not measured"],
  passed: ["good", "check-circle", "Passed"], "not applicable": ["neutral", "info", "Not applicable"] };
const SEVERITY = { critical: "critical", high: "critical", medium: "warning", low: "info", info: "neutral" };
const CLASSES = [["new_requirement", "New requirement: a business decision first"], ["change_request", "Change request"],
  ["defect", "Defect"], ["infra_change", "Infra change: IT decides"]];
const POLL_MS = 2000;
let poll = null;

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

// While an assessment runs in the background, the view looks again every two seconds (later while the
// person types); it stops once the run ended or the person left the view.
function watch(running) {
  clearTimeout(poll);
  if (!running) return;
  poll = setTimeout(() => {
    if (!/\/assessment(\/|$)/.test(location.hash)) return;
    const a = document.activeElement;
    const typing = a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) && a.type !== "checkbox";
    if (typing) watch(true); else nav.rerender();
  }, POLL_MS);
}

function actions(pid, a, kit) {
  const running = a.run && a.run.state === "running";
  const panel = h("input", { type: "checkbox", id: "as-panel", "data-key": "as-panel", disabled: !a.panel_available || running || null });
  const assess = button(running ? "Assessing…" : "Assess now", { icon: "gauge", kind: "small primary", key: "assess-now",
    "data-control": "run_assessment", disabled: running || !a.has_repo || null });
  assess.addEventListener("click", () => {
    if (!needPerson()) return;
    kit.run(assess, assess.parentNode, async () => {
      const out = await api("POST", "/api/projects/" + enc(pid) + "/assessment", Object.assign({ panel: panel.checked }, signed()));
      say(out.run.state === "done" ? out.run.id + " recorded by rule, signed by " + S.person.trim() + "."
        : "Assessing by rule, then with the panel, signed by " + S.person.trim() + ". This view shows it when it ends.", "good");
      await kit.settle(['[data-key="assess-now"]']);
    });
  });
  const r = a.run;
  const state = !r ? null : r.state === "running"
    ? h("p", { class: "note", role: "status" }, icon("refresh"), h("span", null, "Assessing since " + ago(r.started) + ", asked by " + r.person
      + (r.panel ? "; the panel's model reviews it after the rules." : ".")))
    : r.state === "failed" ? h("p", { class: "note warning", role: "status" }, icon("alert"), h("span", null, "The last assessment failed: " + r.error))
      : null;
  return card({ title: "Assess the repository", icon: "gauge", id: "as-run",
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
  return h("div", { class: "empty teach" }, h("p", { class: "empty-t" }, a.has_repo ? "Not assessed yet." : "No repository to assess."),
    h("p", null, a.has_repo
      ? "Assess now reads this system's repository by rule and tells you what to fix: CI/CD governance, maintenance, "
        + "security (the red team's static layer), compliance, and architecture and operations. Each finding names a file and a "
        + "line, or a measured fact, with a severity and a suggested change."
      : "Adopt an existing system first (rihmasto adopt), then assess it here."),
    h("p", { class: "muted small" }, "Then tick the findings you want fixed and file them as changes: each goes round the "
      + "change loop, and a business decision comes first."));
}

function summaryCard(a) {
  const r = a.latest;
  const c = r.counts || {};
  const sev = (a.severities || []).filter((s) => (c.by_severity || {})[s]).map((s) => severityChip(s, c.by_severity[s]));
  const since = r.since;
  return card({ title: r.id + " of revision " + short(r.revision), icon: "file-check", id: "as-sum" },
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
    f.suggestion ? h("p", { class: "small as-fix" }, h("b", null, "Suggested change: "), f.suggestion) : null);
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

/** Findings per call to /assessment/changes: the kernel's MAX_IDS (kernel/assess_cards.py). */
export const FILE_BATCH = 50;

function fileForm(pid, a, picked, kit) {
  const sel = h("select", { id: "as-class", name: "as" }, CLASSES.map(([v, t]) => h("option", { value: v }, t)));
  const send = button("File the ticked findings as changes", { icon: "send", kind: "primary", key: "as-file", type: "submit",
    "data-control": "assessment_changes" });
  const form = h("form", { class: "form panel", "aria-labelledby": "as-file-h", novalidate: true },
    h("h3", { id: "as-file-h" }, "Fix what matters"),
    h("p", { class: "small muted" }, "Tick findings above, then file them: each becomes a change card from " + a.latest.id
      + ", signed with your name. A finding whose card is still open is not filed twice."),
    h("div", { class: "field" }, h("label", { for: "as-class" }, "File them as"), sel),
    h("div", { class: "btns" }, send));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!picked.size) { say("Tick at least one finding first.", "warn"); return; }
    if (!needPerson()) return;
    kit.run(send, form, async () => {
      // The kernel files at most FILE_BATCH findings per call (kernel/assess_cards.py MAX_IDS); ticking
      // every finding of a large assessment is normal, so the ticks go in batches and the results add up
      const ids = Array.from(picked), out = { opened: [], skipped: [] };
      for (let i = 0; i < ids.length; i += FILE_BATCH) {
        const part = await api("POST", "/api/projects/" + enc(pid) + "/assessment/changes",
          Object.assign({ findings: ids.slice(i, i + FILE_BATCH), version: a.latest.id, as: sel.value }, signed()));
        out.opened.push(...part.opened);
        out.skipped.push(...part.skipped);
      }
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
  const head = kit.viewHead("Assessment", "What should this system fix, from CI/CD, maintenance, security, compliance and operations?");
  if (!a || a.error) return h("div", null, head, empty("gauge", (a && a.error) || "The assessment could not be read."));
  watch(!!a.run && a.run.state === "running");
  const out = h("div", { class: "assess" }, head, actions(pid, a, kit));
  if (!a.latest) {
    out.append(a.problem ? h("p", { class: "note warning" }, icon("alert"), h("span", null, a.problem)) : teach(a));
    return out;
  }
  const picked = new Set();
  out.append(summaryCard(a));
  Object.entries(a.perspectives || {}).forEach(([key, label]) => out.append(perspectiveCard(pid, a, key, label, picked)));
  out.append(proposalsCard(pid, a, picked), fileForm(pid, a, picked, kit), historyCard(a));
  return out;
}
