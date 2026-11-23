/* The assistant drawer: it answers where something is and what a button does (and takes you there),
   answers about runs from the real read models, and proposes actions you confirm. A confirmed
   proposal calls the same route a click would, signed with your name. A layout or theme proposal is
   shown as a live preview first, then you Keep or Undo it. It never acts on its own. */

import {
  S, $, $$, h, fill, icon, api, act, say, signed, needPerson, nav, enc, store, chip, button, personaLabel,
  VERDICT_LABEL, link,
} from "./core.js";
import { previewProposal, previewing, keepPreview, undoPreview } from "./dashboard.js";

const A = { log: [], busy: false, key: null };
const SIZE_WORD = { S: "small", M: "medium", L: "wide", XL: "wide and tall" };

function storeKey() { return "gf.assistant." + ((S.route && S.route.pid) || "-"); }
function load() {
  const key = storeKey();
  if (A.key === key) return;
  A.key = key;
  try { A.log = JSON.parse(store.get(key) || "[]"); } catch (e) { A.log = []; }
}
function save() { store.set(A.key || storeKey(), JSON.stringify(A.log.slice(-40))); }

function widgetTitle(type) { return (((S.meta && S.meta.widgets) || {})[type] || {}).title || type; }
function describeOps(ops) {
  return (ops || []).map((o) => {
    const t = widgetTitle(o.widget);
    if (o.op === "resize") return "Make " + t + " " + (SIZE_WORD[o.size] || o.size);
    if (o.op === "set_view") return "Show " + t + " as a " + o.view;
    if (o.op === "add") return "Add " + t;
    if (o.op === "remove") return "Remove " + t;
    if (o.op === "move") return "Move " + t + " to place " + (Number(o.to) + 1);
    if (o.op === "set_filter") return "Filter " + t + " by " + Object.entries(o.filter || {}).map(([k, v]) => k + " " + v).join(", ");
    return o.op + " " + t;
  });
}
function describeTheme(s) {
  const out = [];
  if (s.accent) out.push(s.accent + " accent");
  if (s.density) out.push(s.density + " density");
  if (s.mode) out.push(s.mode + " mode");
  if (s.radius) out.push(s.radius + " corners");
  if (s.font_scale) out.push("text at " + Math.round(s.font_scale * 100) + "%");
  return out.join(", ");
}
const ACTION_WORDS = {
  layout_edit: ["Change the layout", "sliders"], theme: ["Change the theme", "sun"], create_embed: ["Make a chat for a website", "message-square"],
  decide: ["Decide a card", "check-circle"], answer_question: ["Answer a question", "comment"], let_rihma_assume: ["Let Rihma assume", "bot"],
  pause: ["Pause the project", "pause"], resume: ["Resume the project", "play"], report_change: ["Report a change", "refresh"],
  comment: ["Add a comment", "comment"], open: ["Open a view", "arrow-right"],
};
function describe(p) {
  const a = p.args || {};
  switch (p.action) {
    case "layout_edit": return describeOps(a.ops);
    case "theme": return [describeTheme(a.settings || {})];
    case "create_embed": return ["A " + a.kind + " chat for " + (a.origins || []).join(", ")];
    case "decide": return [(VERDICT_LABEL[a.verdict] || a.verdict) + " on " + a.card + (a.reason ? ": “" + a.reason + "”" : "")];
    case "answer_question": return ["Answer " + a.question + ": “" + a.text + "”"];
    case "let_rihma_assume": return ["Take the panel's proposal for " + a.question + " as an assumption"];
    case "pause": return ["Stop at the next safe point" + (a.reason ? ": " + a.reason : "")];
    case "resume": return ["Let the paused project continue"];
    case "report_change": return ["“" + a.text + "”"];
    case "comment": return ["On " + a.target_kind + " " + a.target_id + ": “" + a.text + "”"];
    case "open": return [a.route];
    default: return [JSON.stringify(a)];
  }
}

function suggestions() {
  const view = S.route && S.route.name === "project" ? (S.projectViews || {}).current : S.route && S.route.name;
  const inProject = S.route && S.route.name === "project";
  const out = [];
  if (inProject) out.push("Where do I approve the plan?", "How is the current run going?");
  else out.push("What is waiting on me?");
  const byLens = {
    business: ["Which capabilities are in use?", "Make the decisions widget wide"],
    concept: ["What does the plan assume?", "Show coverage as a table"],
    delivery: ["How is the current run going?", "Make the gate trend bigger and show it as a table"],
    operations: ["What runs in production?", "Use a compact teal theme"],
    compliance: ["Where do I export the evidence pack?", "Who may change the autonomy cap?"],
    insight: ["Which models do the work well?", "Make the gate trend bigger and show it as a table"],
  };
  (byLens[S.lens] || []).forEach((q) => out.push(q));
  if (view === "home" || !inProject) out.push("Use a compact teal theme");
  out.push("Make a feedback chat for our website");
  return Array.from(new Set(out)).slice(0, 5);
}

function sourceChip(s, backed) {
  let href = null;
  const pid = S.route && S.route.pid;
  if ((S.projects || []).some((p) => p.id === s)) href = "#/p/" + enc(s);
  else if (pid && /^C-\d+$/.test(s)) href = link(pid, "inbox", s);
  else if (pid && /^T-\d+$/.test(s)) href = link(pid, "tasks", s);
  else if (pid && /^Q-\d+$/.test(s)) href = link(pid, "questions", s);
  if (!backed) return h("span", { class: "src unbacked", tip: "Not found in the records" }, icon("dashed"), h("span", { class: "mono" }, s), h("small", null, "not found in the records"));
  return href ? h("a", { class: "src", href }, icon("file-check"), h("span", { class: "mono" }, s)) : h("span", { class: "src" }, icon("file-check"), h("span", { class: "mono" }, s));
}

export function highlight(control) {
  const el = $$('[data-control="' + CSS.escape(control) + '"]').find((x) => x.offsetParent !== null) || $('[data-control="' + CSS.escape(control) + '"]');
  if (!el) { say("That control is not on this page.", "info"); return; }
  el.scrollIntoView({ block: "center" });
  el.classList.add("flash");
  setTimeout(() => el.classList.remove("flash"), 2000);
}
async function takeThere(nv) {
  if (nv.route && location.hash !== nv.route) {
    location.hash = nv.route;
    await new Promise((r) => setTimeout(r, 400));
  }
  if (nv.control) setTimeout(() => highlight(nv.control), nv.route ? 600 : 0);
}

async function confirm(p, item) {
  const a = p.args || {};
  const pid = (item.project) || (S.route && S.route.pid);
  const base = "/api/projects/" + enc(pid || "");
  if (p.action === "layout_edit" || p.action === "theme") {
    await previewProposal(p);
    p.state = "preview";
    return;
  }
  if (p.action === "open") { location.hash = a.route; p.state = "done"; return; }
  if (p.action === "create_embed") {
    if (nav.openEmbedForm) nav.openEmbedForm({ kind: a.kind, origins: (a.origins || []).join("\n"), project: a.project || pid || "", label: a.label || "", brief: a.brief || "" });
    p.state = "done";
    return;
  }
  if (!needPerson()) return;
  const calls = {
    decide: () => api("POST", base + "/cards/" + enc(a.card) + "/decide", Object.assign({ verdict: a.verdict, reason: a.reason || "" }, signed())),
    answer_question: () => api("POST", base + "/questions/" + enc(a.question) + "/answer", Object.assign({ text: a.text }, signed())),
    let_rihma_assume: () => api("POST", base + "/questions/" + enc(a.question) + "/assume", signed()),
    pause: () => api("POST", base + "/pause", Object.assign({ reason: a.reason || "" }, signed())),
    resume: () => api("POST", base + "/resume", signed()),
    report_change: () => api("POST", base + "/changes", Object.assign({ text: a.text }, signed())),
    comment: () => api("POST", base + "/comments", Object.assign({ target: { kind: a.target_kind, id: a.target_id }, text: a.text }, signed())),
  };
  if (!calls[p.action]) return;
  await calls[p.action]();
  p.state = "done";
  say("Done, signed by " + S.person.trim() + " as " + personaLabel(S.persona) + ".", "good");
  if (nav.rerender) nav.rerender();
}

function proposalCard(p, item, i) {
  const [title, ic] = ACTION_WORDS[p.action] || [p.action, "info"];
  const lines = describe(p);
  const done = p.state === "done" || p.state === "dismissed";
  const el = h("div", { class: "prop" + (done ? " settled" : "") },
    h("div", { class: "prop-h" }, icon(ic), h("b", null, title)),
    h("ul", { class: "prop-args" }, lines.map((l) => h("li", null, l))),
    p.why ? h("p", { class: "prop-why" }, h("span", { class: "muted" }, "Why: "), p.why) : null);
  if (p.state === "preview" && previewing()) {
    el.append(h("p", { class: "prop-st" }, icon("eye"), "Shown as a preview on the dashboard. Keep it, or undo it."),
      h("div", { class: "btns" }, button("Keep", { icon: "check", kind: "small primary", onclick: () => keepPreview() }),
        button("Undo", { icon: "undo", kind: "small quiet", onclick: () => undoPreview() })));
  } else if (p.state === "preview" || p.state === "kept" || p.state === "undone") {
    el.append(h("p", { class: "prop-st" }, icon(p.state === "undone" ? "undo" : "check"),
      p.state === "undone" ? "Previewed, then undone: nothing was kept." : "Kept: your layout is saved."));
  } else if (p.state === "done") {
    el.append(h("p", { class: "prop-st" }, icon("check"), "Confirmed"));
  } else if (p.state === "dismissed") {
    el.append(h("p", { class: "prop-st muted" }, icon("x"), "Dismissed"));
  } else {
    const ok = button(p.action === "layout_edit" || p.action === "theme" ? "Preview" : "Confirm", { icon: "check", kind: "small primary", key: "prop:" + i + ":ok" });
    const no = button("Dismiss", { kind: "small quiet", key: "prop:" + i + ":no" });
    ok.addEventListener("click", () => act(el, async () => { await confirm(p, item); save(); render(); }));
    no.addEventListener("click", () => { p.state = "dismissed"; save(); render(); });
    el.append(h("div", { class: "btns" }, ok, no));
  }
  return el;
}

function bubble(item) {
  if (item.role === "person") {
    return h("div", { class: "msg me" }, h("div", { class: "bub" }, item.text));
  }
  if (item.role === "thinking") {
    return h("div", { class: "msg bot" }, h("span", { class: "bot-av" }, icon("bot")), h("div", { class: "bub thinking" },
      h("span", { class: "dots", "aria-label": "Thinking" }, h("i"), h("i"), h("i")), "Thinking"));
  }
  if (item.role === "error") {
    return h("div", { class: "msg bot" }, h("span", { class: "bot-av" }, icon("bot")), h("div", { class: "bub err" }, item.text));
  }
  const out = item.out || {};
  const unbacked = new Set(out.unbacked_sources || []);
  const props = out.propose || [];
  return h("div", { class: "msg bot" }, h("span", { class: "bot-av" }, icon("bot")),
    h("div", { class: "bub" },
      h("p", null, out.answer || "I have no answer to that."),
      out.note ? h("p", { class: "muted small" }, out.note) : null,
      (out.sources || []).length ? h("div", { class: "srcs" }, out.sources.map((s) => sourceChip(s, !unbacked.has(s)))) : null,
      out.navigate && (out.navigate.route || out.navigate.control) ? h("div", { class: "btns" },
        button("Take me there", { icon: "arrow-right", kind: "small", onclick: () => takeThere(out.navigate) })) : null,
      props.map((p, i) => proposalCard(p, item, i)),
      (out.dropped || []).map((p) => h("div", { class: "prop dropped" }, h("div", { class: "prop-h" }, icon("x-circle"),
        h("b", null, (ACTION_WORDS[p.action] || [p.action])[0])), h("p", { class: "small" }, "Not offered: " + (p.refused || "outside the rules")))),
      h("p", { class: "by muted small" }, out.by === "map" ? "From the cockpit map" : (S.meta && S.meta.assistant === "gnomon" ? "From Gnomon" : "From the model")
        + ", checked against the Inbox rules")));
}

function render() {
  load();
  const log = $("#as-log");
  if (!log) return;
  if (!A.log.length) {
    fill(log, h("div", { class: "as-hello" }, h("span", { class: "bot-av big" }, icon("bot")),
      h("p", null, h("b", null, "Ask about the cockpit or your projects.")),
      h("p", { class: "muted small" }, "I can take you to a view, tell you what a button does, answer from the records, and propose actions or a new layout that you confirm.")));
  } else {
    fill(log, A.log.map(bubble));
  }
  log.scrollTop = log.scrollHeight;
  fill($("#as-suggest"), suggestions().map((q) => h("button", { type: "button", class: "sugg", onclick: () => send(q) }, q)));
}

export async function send(question) {
  const q = String(question || "").trim();
  if (!q || A.busy) return;
  load();
  A.busy = true;
  A.log.push({ role: "person", text: q });
  A.log.push({ role: "thinking" });
  render();
  const project = S.route && S.route.name === "project" ? S.route.pid : null;
  const view = S.route && S.route.name === "project" ? (S.projectViews || {}).current : S.route && S.route.name;
  try {
    const out = await api("POST", "/api/assistant", { question: q, persona: S.persona, project, view, person: S.person.trim(), lens: S.lens });
    A.log.pop();
    A.log.push({ role: "assistant", out, project });
  } catch (e) {
    A.log.pop();
    A.log.push({ role: "error", text: e.message });
  } finally {
    A.busy = false;
    save();
    render();
  }
}

export function openAssistant(prefill) {
  const dr = $("#assistant");
  dr.hidden = false;
  document.documentElement.classList.add("drawer-open");
  $("#assistant-fab").setAttribute("aria-expanded", "true");
  $("#as-mode").textContent = modeLine();
  render();
  const q = $("#as-q");
  if (prefill) q.value = prefill;
  q.focus();
}
export function closeAssistant() {
  const dr = $("#assistant");
  if (dr.hidden) return;
  dr.hidden = true;
  document.documentElement.classList.remove("drawer-open");
  $("#assistant-fab").setAttribute("aria-expanded", "false");
  $("#assistant-fab").focus();
}
export function assistantOpen() { return !$("#assistant").hidden; }
export function onRouteChange() { if (assistantOpen()) render(); else A.key = null; }

// When a preview is kept or undone on the dashboard, the proposal says so.
nav.previewSettled = (how) => {
  load();
  A.log.forEach((item) => ((item.out || {}).propose || []).forEach((p) => { if (p.state === "preview") p.state = how; }));
  save();
  if (assistantOpen()) render();
};

function modeLine() {
  const m = S.meta && S.meta.assistant;
  if (m === "gnomon") return "Answers through Gnomon in the analyst lane, from the records";
  if (m === "model") return "Answers through an injected model, from the records";
  return "Answers from the cockpit map and the records";
}

export function wireAssistant() {
  $("#assistant-fab").addEventListener("click", () => (assistantOpen() ? closeAssistant() : openAssistant()));
  $("#as-close").addEventListener("click", closeAssistant);
  $("#as-clear").addEventListener("click", () => { load(); A.log = []; save(); render(); });
  const form = $("#as-form");
  const q = $("#as-q");
  form.addEventListener("submit", (e) => { e.preventDefault(); const v = q.value; q.value = ""; send(v); });
  q.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
    if (e.key === "Escape") { e.preventDefault(); closeAssistant(); }
  });
  $("#assistant").addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closeAssistant(); } });
}
export { chip };
