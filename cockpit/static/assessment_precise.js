/* A precise assessment (FR-ASP1; kernel/assess_precise.py, kernel/assess_measure.py, kernel/assess_headline.py).
   The owner: "when I jump into [an adopted project] its not clear what should I do". So the Assessment view opens on two
   lines, what is worth acting on now and what is probably noise, each with why, and the next steps as buttons. Each
   finding can be marked not relevant to this project (with a reason; findings like it are offered the same), a secret
   confirmed real or marked a fixture (for its file), and the project's own test runner mapped. Every write is signed
   and the kernel decides whether it stands; the kernel's own lines are marked data-ud. */

import { pick, emptyState } from "./words.js";
import { S, h, icon, chip, api, say, signed, needPerson, enc, plural, cap, card, button, link } from "./core.js";
import { openAssistant, send as askRihma } from "./assistant.js";

const verdictUrl = (pid) => "/api/projects/" + enc(pid) + "/assessment/verdict";
const kernelText = (tag, cls, text) => h(tag, { class: cls, "data-ud": "" }, text);

function go(sel) {
  const el = document.querySelector(sel);
  if (!el) return;
  el.scrollIntoView({ block: "start" });
  const f = el.querySelector("button, input, summary, a[href]");
  if (f) f.focus();
}

// The two lines on top, and the next steps from the state (guide, don't describe).
export function headlineCard(pid, a, tick) {
  const hd = a.headline;
  if (!hd) return null;
  const steps = (hd.next || []).map((s) => {
    const attrs = { kind: "small", key: "asp-next:" + s.do };      // a step goes to its control, never stands for it
    if (s.do === "select_act") return button(s.label, Object.assign(attrs, { icon: "check", onclick: () => { tick(hd.act_ids.slice(0, 5)); go("#as-file-h"); } }));
    if (s.do === "map_runner" || s.do === "runner_results") return button(s.label, Object.assign(attrs, { icon: "play", "data-control": "assessment_runner_map", onclick: () => go('[aria-labelledby="asp-tests-h"]') }));
    if (s.do === "assess_again") return button(s.label, Object.assign(attrs, { icon: "refresh", "data-control": "run_assessment", onclick: () => go('[data-key="assess-now"]') }));
    if (s.do === "review_secrets") return button(s.label, Object.assign(attrs, { icon: "shield", onclick: () => go(".asp-likely") }));
    if (s.do === "review_similar") return button(s.label, Object.assign(attrs, { icon: "layers", onclick: () => go(".asp-like") }));
    if (s.do === "align") return h("a", { class: "btn small", href: link(pid, "align"), "data-key": "asp-next:align" }, icon("merge"), h("span", { class: "lbl" }, s.label));
    return null;
  });
  return card({ title: pick("What to do now", "Worth acting on, gaps, probably noise"), icon: "flag", id: "asp-head", cls: "asp-head" },
    h("div", { class: "asp-lines" },
      h("p", { class: "asp-act" }, icon(hd.act_ids.length ? "alert" : "check-circle"), kernelText("span", null, hd.act)),
      hd.gaps ? h("p", { class: "asp-gaps" }, icon("dashed"), kernelText("span", null, hd.gaps)) : null,   // FR-ASP2
      h("p", { class: "asp-noise muted" }, icon("info"), kernelText("span", null, hd.noise))),
    h("div", { class: "btns" }, steps,
      button("Ask Rihma what is noise", { icon: "bot", kind: "small ghost", key: "asp-ask", "data-control": "assessment_ask",
        onclick: () => { openAssistant(); askRihma("In the assessment, what is worth acting on and what is noise?"); } })));
}

async function sendVerdict(pid, body, btn, kit, where) {
  if (!needPerson()) return;
  await kit.run(btn, where, async () => {
    const out = await api("POST", verdictUrl(pid), Object.assign(body, signed()));
    const like = out.similar || [];
    const kind = out.family ? " (" + out.family + ")" : "";
    say(cap(String(out.findings.join(", "))) + ": " + String(out.verdict).replace("_", " ") + ", signed by " + S.person.trim() + "."
      + (out.verdict !== "not_relevant" ? "" : like.length ? " " + plural(like.length, "finding") + " of the same kind" + kind + ": settle them on their rows."
        : " No other open finding is of the same kind" + kind + "."), "good");
    await kit.settle(["#asp-head-h"]);
  });
}

// Not relevant here: a reason, then Save. The answer offers the findings like it.
function notRelevant(pid, f, kit) {
  const id = "asp-why-" + f.id;
  const box = h("div", { class: "asp-why", hidden: true },
    h("label", { for: id, class: "small" }, "Why is " + f.id + " not relevant to this project?"),
    h("input", { id, type: "text", maxlength: 400, "data-key": "asp-why:" + f.id }));
  const save = button("Save", { kind: "small primary", key: "asp-save:" + f.id, "data-control": "assessment_not_relevant" });
  box.append(save);
  save.addEventListener("click", () => {
    const reason = box.querySelector("input").value.trim();
    if (reason.length < 3) { say("Say why in a few words: the reason is kept with it.", "warn"); return; }
    sendVerdict(pid, { finding: f.id, verdict: "not_relevant", reason }, save, kit, box);
  });
  const open = button("Not relevant here", { icon: "x", kind: "small ghost", key: "asp-nr:" + f.id, "data-control": "assessment_not_relevant",
    aria: "Mark " + f.id + " not relevant to this project", expanded: "false",
    onclick: () => { box.hidden = !box.hidden; open.setAttribute("aria-expanded", String(!box.hidden)); if (!box.hidden) box.querySelector("input").focus(); } });
  return [open, box];
}

// What people said of a finding, and the buttons to say it: shown on each finding's row.
export function findingExtras(pid, f, kit) {
  const out = [];
  const lk = f.likely;
  if (lk) {
    const tone = lk.verdict === "likely not a secret" ? "neutral" : lk.verdict === "confirmed real" ? "critical" : "warning";
    out.push(h("p", { class: "small asp-likely" }, chip(tone, tone === "neutral" ? "info" : "alert", cap(lk.verdict)),
      kernelText("span", "muted", " " + cap(lk.reason) + (f.severity_was ? " (the rule said " + f.severity_was + ")" : "") + ".")));
  }
  if (f.dismissed) {
    const d = f.dismissed;
    const undo = button("Relevant after all", { kind: "small ghost", key: "asp-undo:" + f.id, "data-control": "assessment_not_relevant" });
    undo.addEventListener("click", () => sendVerdict(pid, { finding: f.id, verdict: "relevant" }, undo, kit, undo.parentNode));
    out.push(h("p", { class: "small note asp-dismissed" }, icon("x-circle"), h("span", null, "Not relevant here, said by " + d.person + ": "),
      kernelText("span", null, d.reason), " ", undo));
    return out;
  }
  if (f.later) {          // a local project's finding for later, by rule (FR-ASP2): a person may bring it back
    const now = button("Relevant now", { kind: "small ghost", key: "asp-now:" + f.id, "data-control": "assessment_not_relevant",
      aria: "Bring " + f.id + " back: it matters for this project now" });
    now.addEventListener("click", () => sendVerdict(pid, { finding: f.id, verdict: "relevant" }, now, kit, now.parentNode));
    out.push(h("p", { class: "small note asp-later" }, icon("clock"), kernelText("span", null, cap(f.later.reason) + "."), " ", now));
  }
  if (f.propose_dismiss) {
    const p = f.propose_dismiss;
    const same = button("Not relevant too", { kind: "small", key: "asp-same:" + f.id, "data-control": "assessment_not_relevant" });
    same.addEventListener("click", () => sendVerdict(pid, { finding: f.id, verdict: "not_relevant", reason: "like " + p.like + ": " + p.reason },
      same, kit, same.parentNode));
    out.push(h("p", { class: "small note asp-like" }, icon("layers"), h("span", null, "Of the same kind as " + p.like + ", which " + p.person + " marked not relevant: "),
      kernelText("span", null, p.reason), " ", same));
  }
  const acts = notRelevant(pid, f, kit);
  if (lk && f.id && f.id.startsWith("F-")) {
    const real = button("Confirm real", { icon: "alert", kind: "small ghost", key: "asp-real:" + f.id, "data-control": "assessment_secret_mark" });
    real.addEventListener("click", () => sendVerdict(pid, { finding: f.id, verdict: "real" }, real, kit, real.parentNode));
    const fix = button("Mark as fixture", { icon: "check", kind: "small ghost", key: "asp-fix:" + f.id, "data-control": "assessment_secret_mark" });
    fix.addEventListener("click", () => sendVerdict(pid, { finding: f.id, verdict: "fixture" }, fix, kit, fix.parentNode));
    acts.unshift(real, fix);
  }
  out.push(h("div", { class: "btns asp-acts" }, acts));
  return out;
}

function runnerForm(pid, a, kit) {
  const r = a.runner || {};
  const field = (k, label, val, help) => h("p", { class: "small" }, h("label", { for: "asp-run-" + k }, label),
    h("input", { id: "asp-run-" + k, type: "text", value: val || "", "data-key": "asp-run:" + k, maxlength: 300, "aria-describedby": help ? "asp-run-" + k + "-h" : null }),
    help ? h("span", { id: "asp-run-" + k + "-h", class: "muted" }, " " + help) : null);
  const save = button("Map its test runner", { icon: "play", kind: "small primary", key: "asp-run-save", type: "submit", "data-control": "assessment_runner_map" });
  const form = h("form", { class: "form asp-run", novalidate: true },
    field("command", pick("The command the team runs its tests with", "The project's own test command"), r.command),
    field("results", pick("Where the results are saved", "Its results file in the repository"), r.results,
      pick("for example build/test-results.xml", "JUnit XML or JSON counts, read at the assessed revision")),
    field("note", "Where it runs", r.note), h("div", { class: "btns" }, save));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!needPerson()) return;
    const v = (k) => form.querySelector("#asp-run-" + k).value.trim();
    if (v("command").length < 2) { say("Name the command first.", "warn"); return; }
    kit.run(save, form, async () => {
      await api("POST", "/api/projects/" + enc(pid) + "/assessment/runner",
        Object.assign({ command: v("command"), results: v("results"), note: v("note") }, signed()));
      say("Mapped, signed by " + S.person.trim() + ". Assess again: the next assessment reads its results.", "good");
      await kit.settle(['[data-key="assess-now"]']);
    });
  });
  return form;
}

// The landing's word on the assessment (the developer briefing on the Board, FR-ASP2): what is worth acting on now,
// the gaps to close, and the way there; or that it was never assessed.
export function briefingLine(b) {
  const a = b && b.assessment;
  if (!a) return null;
  const led = b.next && b.next.action && b.next.action.route === a.route;     // the next step already says it and leads there
  if (led && !a.gaps) return null;
  return h("div", { class: "dv-assess small", "data-id": "dev_assessment" },
    led ? null : h("p", null, icon(a.assessed ? (a.act_ids.length ? "alert" : "check-circle") : "dashed"),
      h("b", null, pick("From the assessment: ", "Assessment" + (a.assessment ? " " + a.assessment : "") + ": ")), kernelText("span", null, a.act)),
    a.gaps ? h("p", { class: "muted" }, icon("dashed"), kernelText("span", null, a.gaps)) : null,
    led ? null : h("div", { class: "btns" }, h("a", { class: "btn small", href: a.route, "data-key": "dev:assessment" },
      icon("arrow-right"), h("span", { class: "lbl" }, a.label))));
}

// Tests: what they are measured against, the project's own runner, and the plans imported from documents.
export function testsCard(pid, a, kit) {
  const latest = a.latest || {};
  const pr = latest.precise || {};
  const m = (latest.checks || []).find((c) => c.key === "maintenance.tests_measured");
  const plans = (pr.plans || {}).items || [];
  const roots = (pr.test_roots || []).filter(Boolean);
  return card({ title: pick("Tests and plans: what this is measured against", "Tests and plans: measured against what"), icon: "flask", id: "asp-tests" },
    pr.measured_against ? kernelText("p", "small muted", cap(pr.measured_against) + ".") : null,
    roots.length ? kernelText("p", "small", "Each package's own test root, run on its own: " + roots.join(", ") + ".") : null,
    m && m.verdict === "not measured" ? emptyState("assess_runner", null, { icon: "flask" }) : null,
    m && m.verdict === "not measured" ? kernelText("p", "small muted", cap(m.reason || "") + ".") : null,
    m && m.verdict !== "not measured" ? h("p", { class: "small" }, chip(m.verdict === "passed" ? "good" : m.verdict === "failed" ? "critical" : "nm",
      m.verdict === "passed" ? "check-circle" : "dashed", cap(m.verdict)), kernelText("span", null, " " + cap(m.reason || m.summary || "") + ".")) : null,
    h("p", { class: "small" }, h("a", { href: link(pid, "align") }, pick("Open the team's own plans and tests", "Open the project's own sources (Alignment)"))),
    runnerForm(pid, a, kit),
    h("h3", { class: "small asp-plans-h" }, pick("Plans taken from the team's documents", "Requirements and tasks imported from documents")),
    plans.length ? h("ul", { class: "plain as-list" }, plans.map((p) => h("li", { class: "as-row" + (p.stale ? " asp-stale" : "") },
      h("div", { class: "as-h" }, h("b", { class: "mono" }, p.id), kernelText("span", null, " " + p.title),
        chip(p.status === "open" ? "info" : "good", null, p.status === "open" ? "To decide" : "Accepted")),
      kernelText("p", "small muted", p.path + (p.committed ? ", last changed " + String(p.committed).slice(0, 10) : "")),
      p.stale ? h("p", { class: "small note warning" }, icon("alert"), kernelText("span", null, cap(p.said) + ".")) : null)))
      : emptyState("assess_plans", null, { icon: "list" }));
}
