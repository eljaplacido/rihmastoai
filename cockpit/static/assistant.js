/* The assistant drawer: it answers where something is and what a button does (and takes you there:
   it opens the page the control is on, then highlights it), answers about runs from the real read
   models, and proposes actions you confirm. A proposal is checked again when you confirm it, against
   your persona now and the record now, and then calls the same route a click would, signed with your
   name. A layout or theme proposal is shown as a live preview first, then you Keep or Undo it. It
   never acts on its own.

   The conversation is kept per persona and project in the tab. A question asked while another waits
   is queued, and an answer always goes to the conversation it was asked in, even after you moved on.
   A reload while one waits says that no answer came. While the drawer is open, the proposals it shows
   are checked again now and then, so one that another person or tab settled says so before anyone
   presses Confirm. */

import {
  S, $, $$, h, fill, icon, api, act, say, signed, needPerson, nav, enc, store, chip, button, personaLabel,
  VERDICT_LABEL, KIND_LABEL, FACTORY_PID, link,
} from "./core.js";
import { previewProposal, previewing, keepPreview, undoPreview } from "./dashboard.js";

const A = {
  convs: {}, key: null, queue: [], current: null, busy: false, tick: null, embedCheck: new WeakMap(),
  confirming: new WeakSet(), swept: {}, sweeping: false, sweepAgain: false, sweepTimer: null, unloadAt: 0, gone: false,
};
const SIZE_WORD = { S: "small", M: "medium", L: "wide", XL: "wide and tall" };
const PHONE = "(max-width: 760px)";
const FOCUSABLE = "button:not([disabled]), a[href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex='-1'])";
const LOST = "No answer came: the page was reloaded while it waited. Ask again.";
const SWEEP_EVERY = 15000;   // how often the open proposals are checked again while the drawer is open
const SWEEP_GAP = 5000;      // and never more often than this for one conversation, unless something was confirmed

// A reload, or a link away, aborts the answer on its way. The page is then going: the next one reads the question
// still pending and says no answer came, so nothing is written here in the meantime.
window.addEventListener("beforeunload", () => { A.unloadAt = Date.now(); });
window.addEventListener("pagehide", () => { A.gone = true; });
window.addEventListener("pageshow", () => { A.gone = false; A.unloadAt = 0; });
function leaving() { return A.gone || Date.now() - A.unloadAt < 10000; }
const delay = (ms) => new Promise((r) => setTimeout(r, ms));
async function stillHere() {
  await delay(300);   // the abort can come just before the page says it is going
  while (leaving()) await delay(250);   // a page that goes never gets past this; one that stays does
}

// -- conversations: one per persona and project, each saved under its own key ---------------------

function storeKey() { return "gf.assistant." + (S.persona || "-") + "." + ((S.route && S.route.pid) || "-"); }
function conv(key) {
  if (!A.convs[key]) {
    let log = [];
    try { log = JSON.parse(store.get(key) || "[]"); } catch (e) { log = []; }
    const out = [];
    (Array.isArray(log) ? log : []).forEach((it) => {
      if (!it || it.role === "thinking") return;
      out.push(it);
      if (it.role === "person" && it.pending) { it.pending = false; out.push({ role: "error", text: LOST }); }
    });
    A.convs[key] = out;
  }
  return A.convs[key];
}
function load() { A.key = storeKey(); return conv(A.key); }
function save(key) {
  const k = key || A.key;
  if (k) store.set(k, JSON.stringify(conv(k).filter((it) => it.role !== "thinking").slice(-40)));
}
function mapMode() { return !(S.meta && S.meta.assistant && S.meta.assistant !== "map"); }
function phone() { return window.matchMedia(PHONE).matches; }
function unique(list) { return Array.from(new Set(list)); }

// -- proposals in plain words ----------------------------------------------------------------------

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
    case "create_embed": return ["A " + a.kind + " chat for " + ((a.origins || []).length ? a.origins.join(", ") : "the websites you name on the form")];
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

// -- suggested questions: only what this mode can answer -----------------------------------------------

function suggestions() {
  const inProject = S.route && S.route.name === "project";
  const factory = inProject && S.route.pid === FACTORY_PID;
  const out = [];
  if (mapMode()) {   // the map answers where things are; it cannot answer about runs or change anything
    if (factory) out.push("Where is the inbox?", "Where is the ledger?");
    else if (inProject) out.push("Where do I approve the plan?", "Where is the ledger?", "How do I pause this?");
    else out.push("Where are all the decisions?", "Where do I log a signal?");
    const byLens = {
      business: "Where do I validate a concept?", concept: "Where are the assumptions?", delivery: "Where is the task board?",
      operations: "Where are the releases?", compliance: "Where do I export the evidence pack?", insight: "Where are the factory's metrics?",
    };
    if (byLens[S.lens]) out.push(byLens[S.lens]);
    out.push("Where do I make a chat for a website?");
    return unique(out).slice(0, 5);
  }
  if (inProject && !factory) out.push("Where do I approve the plan?", "How is the current run going?");
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
  if (!inProject) out.push("Use a compact teal theme");
  out.push("Make a feedback chat for our website");
  return unique(out).slice(0, 5);
}

// -- sources -------------------------------------------------------------------------------------------

function sourceChip(s, backed, pid) {
  let href = null;
  const id = (/\b([CTQ])-\d+\b/i.exec(s) || [])[0];
  const proj = (S.projects || []).find((p) => s === p.id || s.endsWith(" " + p.id) || s.endsWith(":" + p.id));
  if (proj) href = "#/p/" + enc(proj.id);
  else if (pid && id) href = link(pid, { C: "inbox", T: "tasks", Q: "questions" }[id[0].toUpperCase()], id.toUpperCase());
  if (!backed) return h("span", { class: "src unbacked", tip: "Not found in the records" }, icon("dashed"), h("span", { class: "mono" }, s), h("small", null, "not found in the records"));
  return href ? h("a", { class: "src", href }, icon("file-check"), h("span", { class: "mono" }, s)) : h("span", { class: "src" }, icon("file-check"), h("span", { class: "mono" }, s));
}

// -- Take me there: the control's page first, then the control -------------------------------------------

function controlLabel(id) {
  const c = ((S.uiMap && S.uiMap.controls) || []).find((x) => x.id === id);
  return c ? c.label : "That control";
}
// "Verdict buttons are", "Pause is": the verb agrees with the label, as the kernel's answers do.
function isAre(label) { return /[^s]s$/i.test(label) ? " are" : " is"; }
function visibleControl(id) {
  return $$('[data-control="' + CSS.escape(id) + '"]').find((x) => {
    const r = x.getBoundingClientRect();
    return x.getClientRects().length > 0 && !x.closest("[hidden]") && r.right > 0 && r.left < window.innerWidth;
  }) || null;
}
function underDrawer(el) {
  const a = el.getBoundingClientRect(), d = $("#assistant").getBoundingClientRect();
  return assistantOpen() && a.right > d.left && a.left < d.right && a.bottom > d.top && a.top < d.bottom;
}
function waitFor(fn, ms) {
  return new Promise((resolve) => {
    const until = Date.now() + ms;
    (function poll() {
      const v = fn();
      if (v || Date.now() > until) resolve(v || null); else setTimeout(poll, 80);
    })();
  });
}
function onPage(route) {
  const hash = location.hash || "";
  return hash === route || hash.startsWith(route + "/") || (/\/overview$/.test(route) && hash === route.replace(/\/overview$/, ""));
}
function focusPage() { const m = $("#main"); if (m) m.focus({ preventScroll: true }); }
export function highlight(el) {
  el.scrollIntoView({ block: "center" });
  el.classList.add("flash");
  setTimeout(() => el.classList.remove("flash"), 2000);
  const target = el.matches(FOCUSABLE) ? el : el.querySelector(FOCUSABLE);
  if (target) target.focus({ preventScroll: true });
}
async function takeThere(nv) {
  if (nv.control === "assistant" && assistantOpen()) { say("You are in it: ask here.", "info"); $("#as-q").focus(); return; }
  let el = nv.control ? visibleControl(nv.control) : null;   // already in sight: highlight it where it is
  const go = !el && nv.route && !onPage(nv.route);
  if (go) location.hash = nv.route;
  if (phone()) closeAssistant(true);   // the drawer covers the page
  if (!nv.control) {
    if (go) await waitFor(() => $("#main") && $("#main").dataset.loaded !== "0", 3000);
    focusPage();
    return;
  }
  if (!el) el = await waitFor(() => visibleControl(nv.control), go ? 3000 : 600);
  if (el && underDrawer(el)) closeAssistant(true);
  if (!el) {
    const there = $('[data-control="' + CSS.escape(nv.control) + '"]');
    const label = controlLabel(nv.control);
    say(label + isAre(label) + (there ? " not shown " + (phone() ? "at this width" : "here right now") : " not on this page right now")
      + ". The answer says where to find " + (isAre(label) === " are" ? "them" : "it") + ".", "info");
    if (!assistantOpen()) focusPage();
    return;
  }
  highlight(el);
}

// -- confirming: checked again first, then the route a click would call -----------------------------------

// The checks Confirm runs, and the sweep runs on every open proposal: `get` reads each record once per pass.
async function recheck(p, item, get = (path) => api("GET", path)) {
  const a = p.args || {};
  const meta = S.meta || {};
  const who = personaLabel(S.persona);
  if (p.persona && p.persona !== S.persona) return "it was checked for " + personaLabel(p.persona) + ", and you are now " + who + ". Ask again.";
  if (p.action === "create_embed") return (meta.embed_creators || []).includes(S.persona) ? null : "as " + who + " you may not create an embed.";
  const pid = p.project || item.project;
  if (!pid || ["layout_edit", "theme", "open", "report_change", "comment"].includes(p.action)) return null;
  const base = "/api/projects/" + enc(pid);
  if (p.action === "pause" || p.action === "resume") {
    if (!(meta.may_pause || []).includes(S.persona)) return "as " + who + " you may not pause or resume a project.";
    const held = (await get(base)).meta.pause;
    if (p.action === "pause" && held) return "it is already paused by " + held.requested_by + ".";
    return p.action === "resume" && !held ? "it is not paused any more." : null;
  }
  if (p.action === "decide") {
    const id = String(a.card).toUpperCase();
    const kindWord = (kind) => { const w = (KIND_LABEL[kind] || kind).toLowerCase(); return (/^[aeiou]/.test(w) ? "an " : "a ") + w; };
    const mine = ((await get(base + "/inbox?persona=" + enc(S.persona))).cards || []).find((c) => c.id === id);
    if (mine) return (mine.verdicts || []).includes(a.verdict) ? null : kindWord(mine.kind) + " card takes " + mine.verdicts.join(", ") + ".";
    const open = ((await get(base)).open_cards || []).find((c) => c.id === id);
    return open ? "as " + who + " you may not decide " + kindWord(open.kind) + " card." : id + " is no longer open: it was decided.";
  }
  if (p.action === "answer_question" || p.action === "let_rihma_assume") {
    const q = ((await get(base)).questions || []).find((x) => x.id === String(a.question).toUpperCase());
    if (!q) return "there is no question " + a.question + ".";
    return q.status === "open" ? null : q.id + " is " + q.status + ".";
  }
  return null;
}

async function confirm(p, item, key) {
  const a = p.args || {};
  const pid = p.project || item.project || (S.route && S.route.pid);
  const base = "/api/projects/" + enc(pid || "");
  const why = await recheck(p, item);
  if (why) { p.state = "stale"; p.stale = why; return; }
  if (p.action === "layout_edit" || p.action === "theme") {
    p.state = "preview";   // set on the proposal itself: the drawer may show Home's conversation once Home opens
    save(key);
    await previewProposal(p);
    if (phone()) {   // the drawer covers the page: the preview, and its Keep and Undo, are in sight instead
      closeAssistant(true);
      const keep = $('[data-key="preview:keep"]');
      if (keep) keep.focus(); else focusPage();
    }
    return;
  }
  if (p.action === "open") { p.state = "done"; save(key); if (phone()) closeAssistant(true); location.hash = a.route; return; }
  if (p.action === "create_embed") {
    const before = ((await api("GET", "/api/embeds")).embeds || []).map((e) => e.id);
    p.state = "opened";
    p.before = before;
    save(key);
    if (nav.openEmbedForm) nav.openEmbedForm({ kind: a.kind, origins: (a.origins || []).join("\n"), project: a.project || pid || "", label: a.label || "", brief: a.brief || "" });
    return;
  }
  if (!needPerson()) return;
  const calls = {
    decide: () => api("POST", base + "/cards/" + enc(String(a.card).toUpperCase()) + "/decide", Object.assign({ verdict: a.verdict, reason: a.reason || "" }, signed())),
    answer_question: () => api("POST", base + "/questions/" + enc(String(a.question).toUpperCase()) + "/answer", Object.assign({ text: a.text }, signed())),
    let_rihma_assume: () => api("POST", base + "/questions/" + enc(String(a.question).toUpperCase()) + "/assume", signed()),
    pause: () => api("POST", base + "/pause", Object.assign({ reason: a.reason || "" }, signed())),
    resume: () => api("POST", base + "/resume", signed()),
    report_change: () => api("POST", base + "/changes", Object.assign({ text: a.text }, signed())),
    comment: () => api("POST", base + "/comments", Object.assign({ target: { kind: a.target_kind, id: a.target_id }, text: a.text }, signed())),
  };
  if (!calls[p.action]) return;
  const out = await calls[p.action]();
  p.state = "done";
  save(key);
  const made = p.action === "decide" && out && out.project;   // a validated concept became a project: open it, as a click does
  if (made) p.made = out.project;
  say("Done, signed by " + S.person.trim() + " as " + personaLabel(S.persona) + "." + (made ? " The new project opens." : ""), "good");
  if (made) location.hash = "#/p/" + enc(out.project) + "/overview";
  else if (nav.rerender) nav.rerender();
}

// An embed form opened from a proposal: the proposal says "made" only once an embed was created.
function checkEmbed(p, key) {
  const last = A.embedCheck.get(p) || 0;
  if (Date.now() - last < 4000) return;
  A.embedCheck.set(p, Date.now());
  api("GET", "/api/embeds").then((r) => {
    const made = (r.embeds || []).find((e) => !(p.before || []).includes(e.id) && (!e.kind || e.kind === (p.args || {}).kind));
    if (!made || p.state !== "opened") return;
    p.state = "made";
    p.madeEmbed = made.id;
    save(key);
    if (assistantOpen() && !$("#modal").open) render();
  }).catch(() => { /* the next look tries again */ });
}

/* The open proposals in the conversation shown, checked again while the drawer is open: when it renders, every
   SWEEP_EVERY ms, and at once after a confirm. One that another person, tab or confirm settled turns to "No
   longer offered" with its reason, so its Confirm is gone before anyone presses it. A record that cannot be read
   now leaves the proposal as it is: Confirm checks again anyway. */
async function sweep(force) {
  if (A.sweeping) { A.sweepAgain = A.sweepAgain || !!force; return; }
  const key = A.key;
  if (!key || !assistantOpen() || document.hidden || mapMode()) return;
  if (!force && Date.now() - (A.swept[key] || 0) < SWEEP_GAP) return;
  A.swept[key] = Date.now();
  const open = [];
  conv(key).forEach((item, idx) => ((item.out || {}).propose || []).forEach((p, i) => {
    if (!p.state && !A.confirming.has(p)) open.push({ p, item, k: "prop:" + idx + ":" + i });
  }));
  if (!open.length) return;
  A.sweeping = true;
  const reads = new Map();
  const get = (path) => { if (!reads.has(path)) reads.set(path, api("GET", path)); return reads.get(path); };
  const settled = [];
  try {
    for (const o of open) {
      let why = null;
      try { why = await recheck(o.p, o.item, get); } catch (e) { why = null; }
      if (why && !o.p.state && !A.confirming.has(o.p)) { o.p.state = "stale"; o.p.stale = why; settled.push(o); }
    }
  } finally {
    A.sweeping = false;
  }
  if (settled.length) {
    save(key);
    if (assistantOpen() && key === A.key) {
      const was = document.activeElement && document.activeElement.getAttribute && document.activeElement.getAttribute("data-key");
      const box = $("#as-log");
      const top = box.scrollTop, atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 8;
      render();
      if (!atEnd) box.scrollTop = top;   // someone reading further up stays where they were
      const mine = settled.find((o) => was && was.startsWith(o.k + ":"));
      if (mine) settle(mine.k + ":st");   // its Confirm or Dismiss had the focus: the line that says why takes it
    }
  }
  if (A.sweepAgain) { A.sweepAgain = false; sweep(true); }
}

// -- the conversation on the page -----------------------------------------------------------------------

function status(text, ic, key, muted) {
  return h("p", { class: "prop-st" + (muted ? " muted" : ""), tabindex: "-1", "data-key": key }, icon(ic), h("span", null, text));
}
function settle(...keys) {
  // after a confirm, a dismiss or a preview the focus stays in the card: its next button, or its status line
  const el = keys.map((k) => $('#as-log [data-key="' + CSS.escape(k) + '"]')).find((x) => x && !x.disabled);
  if (el) el.focus(); else $("#as-q").focus();
}
function proposalCard(p, item, i, key, idx) {
  const [title, ic] = ACTION_WORDS[p.action] || [p.action, "info"];
  const k = "prop:" + idx + ":" + i;
  const st = k + ":st";
  const open = !p.state;
  const el = h("div", { class: "prop" + (open || (p.state === "preview" && previewing()) ? "" : " settled") },
    h("div", { class: "prop-h" }, icon(ic), h("b", null, title)),
    h("ul", { class: "prop-args" }, describe(p).map((l) => h("li", null, l))),
    p.why ? h("p", { class: "prop-why" }, h("span", { class: "muted" }, "Why: "), p.why) : null);
  const again = (label) => button(label, { icon: "eye", kind: "small", key: k + ":again", onclick: () => { p.state = undefined; save(key); render(); settle(k + ":ok", st); } });
  if (p.state === "preview" && previewing()) {
    el.append(status("Shown as a preview on Home. Keep it, or undo it.", "eye", st),
      h("div", { class: "btns" }, button("Keep", { icon: "check", kind: "small primary", key: k + ":keep", onclick: () => keepPreview() }),
        button("Undo", { icon: "undo", kind: "small quiet", key: k + ":undo", onclick: () => undoPreview() })));
  } else if (p.state === "preview") {
    el.append(status("The preview ended without Keep or Undo: nothing was kept.", "info", st, true), h("div", { class: "btns" }, again("Preview again")));
  } else if (p.state === "kept") {
    el.append(status(p.action === "theme" ? "Kept: your theme is saved." : "Kept: your layout is saved.", "check", st));
  } else if (p.state === "undone") {
    el.append(status("Previewed, then undone: nothing was kept.", "undo", st, true));
  } else if (p.state === "opened") {
    checkEmbed(p, key);
    el.append(status("The form opened, filled in. Nothing is made until you press Create the chat there.", "info", st),
      h("div", { class: "btns" }, button("Open the form again", { icon: "message-square", kind: "small", key: k + ":form",
        onclick: () => { p.state = undefined; act(el, async () => { await confirm(p, item, key); render(); }); } })));
  } else if (p.state === "made") {
    el.append(status("Chat " + p.madeEmbed + " is made.", "check", st));
  } else if (p.state === "done") {
    el.append(status(p.made ? "Confirmed: the new project " + p.made + " was made." : "Confirmed, signed with your name.", "check", st));
  } else if (p.state === "stale") {
    el.append(status("No longer offered: " + p.stale, "x-circle", st, true));
  } else if (p.state === "dismissed") {
    el.append(status("Dismissed", "x", st, true));
  } else {
    const ok = button(p.action === "layout_edit" || p.action === "theme" ? "Preview" : "Confirm", { icon: "check", kind: "small primary", key: k + ":ok" });
    const no = button("Dismiss", { kind: "small quiet", key: k + ":no" });
    ok.addEventListener("click", () => act(el, async () => {
      A.confirming.add(p);   // the sweep leaves a proposal being confirmed alone
      try {
        await confirm(p, item, key);
      } finally {   // refused or not, the focus stays in the card
        A.confirming.delete(p);
        save(key);
        const lost = !document.activeElement || document.activeElement === document.body;
        if (assistantOpen()) render();   // also when a preview moved to Home: its Keep and Undo show there
        if (assistantOpen() && key === A.key) settle(k + ":keep", st, k + ":ok");
        else if (lost) (assistantOpen() ? $("#as-q") : $("#main")).focus();
        if (p.state === "done") sweep(true);   // what was just decided may settle another proposal
      }
    }));
    no.addEventListener("click", () => { p.state = "dismissed"; save(key); render(); settle(st); });
    el.append(h("div", { class: "btns" }, ok, no));
  }
  return el;
}

function thinkingText(item) {
  const s = Math.max(0, Math.round((Date.now() - (item.started || Date.now())) / 1000));
  return s < 3 ? "" : s + " s" + (s >= 15 ? ", the model can take up to a minute" : "");
}
function bubble(item, idx, key) {
  const av = () => h("span", { class: "bot-av" }, icon("bot"));
  if (item.role === "person") {
    const queued = A.queue.some((j) => j.item === item && j !== A.current);
    return h("div", { class: "msg me" }, h("div", { class: "bub" }, item.text,
      queued ? h("small", { class: "queued muted" }, icon("clock"), "Queued: asked when the answer before it comes") : null));
  }
  if (item.role === "thinking") {
    return h("div", { class: "msg bot" }, av(), h("div", { class: "bub thinking" },
      h("span", { class: "dots", "aria-hidden": "true" }, h("i"), h("i"), h("i")), "Thinking",
      h("small", { class: "th-s muted", "aria-hidden": "true" }, thinkingText(item))));
  }
  if (item.role === "error") return h("div", { class: "msg bot" }, av(), h("div", { class: "bub err" }, icon("alert"), h("span", null, item.text)));
  const out = item.out || {};
  const unbacked = new Set(out.unbacked_sources || []);
  const go = out.navigate && (out.navigate.route || out.navigate.control);
  return h("div", { class: "msg bot" }, av(),
    h("div", { class: "bub" },
      h("p", null, out.answer || "I have no answer to that."),
      out.note ? h("p", { class: "muted small" }, out.note) : null,
      (out.sources || []).length ? h("div", { class: "srcs" }, out.sources.map((s) => sourceChip(s, !unbacked.has(s), item.project))) : null,
      go ? h("div", { class: "btns" }, button("Take me there", { icon: "arrow-right", kind: "small", key: "go:" + idx, onclick: () => takeThere(out.navigate) })) : null,
      (out.propose || []).map((p, i) => proposalCard(p, item, i, key, idx)),
      (out.dropped || []).map((p) => h("div", { class: "prop dropped" }, h("div", { class: "prop-h" }, icon("x-circle"),
        h("b", null, (ACTION_WORDS[p.action] || [p.action])[0])), h("p", { class: "small" }, "Not offered: " + (p.refused || "outside the rules")))),
      out.unasked ? h("p", { class: "muted small" }, (out.unasked === 1 ? "An action was" : out.unasked + " actions were")
        + " suggested that you did not ask for, so none is offered. Ask for it if you want it.") : null,
      h("p", { class: "by muted small" }, out.by === "map" ? "From the cockpit map" : (S.meta && S.meta.assistant === "gnomon" ? "From Gnomon" : "From the model")
        + ", checked against the Inbox rules")));
}

// A preview waits on Home while the drawer shows another conversation: Keep and Undo are here too.
function previewStrip(log) {
  const shown = log.some((it) => ((it.out || {}).propose || []).some((p) => p.state === "preview"));
  if (!previewing() || shown) return null;
  const home = S.route && S.route.name === "home";
  return h("div", { class: "as-preview", role: "status" }, icon("eye"),
    h("span", null, home ? "The assistant's change is shown as a preview." : "A preview of the assistant's change waits on Home."),
    h("span", { class: "btns" }, home
      ? [button("Keep", { icon: "check", kind: "small primary", key: "strip:keep", onclick: () => keepPreview() }),
        button("Undo", { icon: "undo", kind: "small quiet", key: "strip:undo", onclick: () => undoPreview() })]
      : button("Go to Home", { icon: "home", kind: "small", key: "strip:home", onclick: () => { location.hash = "#/home"; } })));
}

function render() {
  const log = load();
  const box = $("#as-log");
  if (!box) return;
  const active = document.activeElement;
  const lost = !!active && (box.contains(active) || $("#as-suggest").contains(active));
  const had = lost ? active.getAttribute("data-key") : null;
  A.shown = renderSign();
  const strip = previewStrip(log);
  if (!log.length) {
    fill(box, strip, h("div", { class: "as-hello" }, h("span", { class: "bot-av big" }, icon("bot")),
      h("p", null, h("b", null, "Ask about the cockpit or your projects.")),
      h("p", { class: "muted small" }, mapMode()
        ? "I can take you to a view or a control and tell you what a button does. No model is set up here, so I cannot answer about runs or propose actions."
        : "I can take you to a view, tell you what a button does, answer from the records, and propose actions or a new layout that you confirm.")));
  } else {
    fill(box, strip, log.map((it, i) => bubble(it, i, A.key)));
  }
  box.scrollTop = box.scrollHeight;
  fill($("#as-suggest"), suggestions().map((q, i) => h("button", { type: "button", class: "sugg", "data-key": "sugg:" + i + ":" + q, onclick: () => send(q) }, q)));
  $("#as-q").placeholder = mapMode() ? "Ask where something is, or what a button does" : "Ask where something is, how a run goes, or to change the layout";
  const again = had && $('#assistant [data-key="' + CSS.escape(had) + '"]');
  if (again) again.focus();
  else if (lost) $("#as-q").focus();   // the focus never drops to the page behind
  setTimeout(() => sweep(false), 0);
}
// What the drawer shows depends on these; a re-render of the same page with the same conversation is skipped.
function renderSign() {
  return [storeKey(), S.lens, S.route && S.route.name, previewing(), mapMode()].join("|");
}

// -- asking: one question at a time, the rest queued -------------------------------------------------------

export function send(question) {
  const q = String(question || "").trim();
  if (!q) return false;
  const key = storeKey();
  const route = S.route || {};
  const job = {
    key, q, project: route.name === "project" ? route.pid : null,
    view: route.name === "project" ? (S.projectViews || {}).current : route.name,
    persona: S.persona, lens: S.lens, person: S.person.trim(),
    item: { role: "person", text: q, pending: true },
  };
  conv(key).push(job.item);
  save(key);
  A.queue.push(job);
  if (assistantOpen()) render();
  if (!A.busy) drain();
  return true;
}
async function drain() {
  A.busy = true;
  A.tick = setInterval(() => $$("#as-log .th-s").forEach((el) => {
    const it = conv(A.key).find((x) => x.role === "thinking");
    if (it) el.textContent = thinkingText(it);
  }), 1000);
  while (A.queue.length) {
    const job = A.queue[0];
    A.current = job;
    const log = conv(job.key);
    const thinking = { role: "thinking", started: Date.now() };
    const at = log.indexOf(job.item);
    if (at >= 0) log.splice(at + 1, 0, thinking);
    if (assistantOpen()) render();
    let reply;
    try {
      const out = await api("POST", "/api/assistant", { question: job.q, persona: job.persona, project: job.project, view: job.view, person: job.person, lens: job.lens });
      reply = { role: "assistant", out, project: job.project, persona: job.persona };
    } catch (e) {
      await stillHere();   // a reload aborted it: the next page says no answer came, never that the server did not answer
      reply = { role: "error", text: e.message || "The assistant did not answer." };
    }
    A.queue.shift();
    A.current = null;
    job.item.pending = false;
    const t = log.indexOf(thinking);
    if (t >= 0) log.splice(t, 1, reply);
    else if (log.includes(job.item)) log.push(reply);   // a cleared conversation takes no late answer
    save(job.key);
    if (assistantOpen()) render();
  }
  clearInterval(A.tick);
  A.busy = false;
}

// -- the drawer --------------------------------------------------------------------------------------------

export function openAssistant(prefill) {
  const dr = $("#assistant");
  dr.hidden = false;
  document.documentElement.classList.add("drawer-open");
  $("#assistant-fab").setAttribute("aria-expanded", "true");
  $("#as-mode").textContent = modeLine();
  const note = $("#assistant .dr-note");
  if (note) note.textContent = mapMode() ? "It points the way and changes nothing." : "It proposes; you confirm. Every action is signed with your name.";
  if (!S.uiMap) api("GET", "/api/ui-map").then((m) => { S.uiMap = m; }).catch(() => { /* labels fall back to a plain word */ });
  render();
  if (!A.sweepTimer) A.sweepTimer = setInterval(() => sweep(false), SWEEP_EVERY);
  const q = $("#as-q");
  if (prefill) q.value = prefill;
  q.focus();
}
export function closeAssistant(toPage) {
  const dr = $("#assistant");
  if (dr.hidden) return;
  dr.hidden = true;
  clearInterval(A.sweepTimer);
  A.sweepTimer = null;
  document.documentElement.classList.remove("drawer-open");
  $("#assistant-fab").setAttribute("aria-expanded", "false");
  if (toPage === true) return;   // Take me there moves the focus to what it opened
  const back = [$("#assistant-fab"), $("#bottombar button")].find((b) => b && b.getClientRects().length > 0);
  if (back) back.focus(); else $("#main").focus();
}
export function assistantOpen() { return !$("#assistant").hidden; }
export function onRouteChange() { if (assistantOpen() && renderSign() !== A.shown) render(); }

// When a preview is kept or undone on the dashboard, the proposal says so, in whichever conversation it is.
nav.previewSettled = (how) => {
  Object.keys(A.convs).forEach((key) => {
    let changed = false;
    A.convs[key].forEach((item) => ((item.out || {}).propose || []).forEach((p) => { if (p.state === "preview") { p.state = how; changed = true; } }));
    if (changed) save(key);
  });
  if (assistantOpen()) render();
};

function modeLine() {
  const m = S.meta && S.meta.assistant;
  if (m === "gnomon") return "Answers through Gnomon in the assistant's own lane, from the records";
  if (m === "model") return "Answers through an injected model, from the records";
  return "Answers from the cockpit map: where things are and what they do";
}

// At phone width the drawer covers the page: the focus stays in it.
function trapFocus(e) {
  if (e.key !== "Tab" || !phone()) return;
  const items = $$(FOCUSABLE, $("#assistant")).filter((x) => x.getClientRects().length > 0);
  if (!items.length) return;
  const first = items[0], last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

export function wireAssistant() {
  $("#assistant-fab").addEventListener("click", () => (assistantOpen() ? closeAssistant() : openAssistant()));
  $("#as-close").addEventListener("click", () => closeAssistant());
  $("#as-clear").addEventListener("click", () => {
    const log = load();
    log.length = 0;   // in place: an answer still on its way is not added back
    A.queue = A.queue.filter((j) => j.key !== A.key || j === A.current);
    save();
    render();
    $("#as-q").focus();
  });
  const form = $("#as-form");
  const q = $("#as-q");
  form.addEventListener("submit", (e) => { e.preventDefault(); if (send(q.value)) q.value = ""; q.focus(); });
  q.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
    if (e.key === "Escape") { e.preventDefault(); closeAssistant(); }
  });
  $("#assistant").addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); closeAssistant(); return; }
    trapFocus(e);
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) sweep(true); });   // back from another tab
}
export { chip };
