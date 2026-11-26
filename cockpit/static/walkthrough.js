/* Walkthroughs in Ask Rihma (FR-WLK1, kernel/walkthrough.py): Rihma takes you through plugging in an existing
   project, starting from an idea or documents, setting up a model, or a tour, step by step in the chat.

   The walkthrough is kept on the server per person, so it resumes after a reload. Its messages show here with
   their options as buttons, a scan's counts, a Confirm button for each proposal (nothing is written before you
   press it, and it is signed with your name and persona), a job's progress while the chat waits on it, and
   links that take you there. Typing in the box answers the step. Walkthroughs are offered from Home's header,
   the panel's header and empty state, a first-run card on Home, and by Ask Rihma when your words ask for one. */

import { S, $, h, fill, icon, chip, api, act, say, signed, needPerson, nav, store, local, button, card, openModal, closeModal, AuthError } from "./core.js";
import { openAssistant, rerenderAssistant, takeThere, highlight } from "./assistant.js";
import { scanStep } from "./scan.js";
import { strip } from "./progress.js";
import { browseButtons } from "./picker.js";

const W = { open: false, picker: false, view: null, list: null, timer: 0, polling: false, seen: 0, focus: null, note: null };
const POLL_MS = 1200;
const KEY = "gf.walk.id";
const HOME_KEY = "gf.walk.home";
const ICON = { plug_in: "plug", documents: "file-check", new_idea: "lightbulb", model: "cpu", tour: "flag" };
// Each walkthrough's button in the panel, by its control in the cockpit's map (cockpit/ui_map.json).
const CONTROL = {
  plug_in: { "data-control": "walk_plug_in" }, new_idea: { "data-control": "walk_new_idea" },
  documents: { "data-control": "walk_documents" }, model: { "data-control": "walk_model" }, tour: { "data-control": "walk_tour" },
};
const n = (x) => Number(x || 0).toLocaleString("en");

function shown() { return W.open; }
function active() { return !!(W.view && W.view.state === "active"); }
function busy() { return !!(W.view && W.view.awaiting && W.view.awaiting.kind === "job"); }

async function loadList() {
  try { W.list = await api("GET", "/api/walkthroughs?person=" + encodeURIComponent(S.person.trim())); } catch (e) { W.list = W.list || null; }
  if (W.list && W.list.yours && !W.view) { W.view = W.list.yours; store.set(KEY, W.view.id); }
  return W.list;
}

// -- starting, answering, confirming --------------------------------------------------------------------

async function take(out) {
  const was = W.view && W.view.id;
  W.view = out.walkthrough;
  store.set(KEY, W.view.id);
  if (out.resumed && out.resumed !== W.view.id) {    // a detour ended: back to the walkthrough it came from
    W.view = (await api("GET", "/api/walkthroughs/" + out.resumed)).walkthrough;
    store.set(KEY, W.view.id);
  }
  if (was !== W.view.id) W.seen = 0;
  W.picker = false;
  W.open = true;
  draw();
  follow();
  poll();
}

export async function startWalk(name, said) {
  if (!needPerson()) return;
  openAssistant();
  const replace = !!(W.view && W.view.state === "active" && W.view.name !== name);
  await act($("#as-log"), async () => take(await api("POST", "/api/walkthroughs", Object.assign({ name, said: said || "", replace }, signed()))));
}
async function send(body, block) {
  if (!W.view || !needPerson()) return;
  await act(block || $("#as-log"), async () => take(await api("POST", "/api/walkthroughs/" + W.view.id + "/reply", Object.assign(body, signed()))));
}
async function confirmIt(block) {
  if (!needPerson()) return;
  await act(block, async () => {
    const out = await api("POST", "/api/walkthroughs/" + W.view.id + "/confirm", signed());
    if (out.refused) say("Refused: " + out.refused, "critical");
    else say("Confirmed, signed by " + S.person.trim() + ".", "good");
    await take(out);
  });
}
async function cancelIt() {
  if (!W.view || !needPerson()) return;
  await act($("#as-log"), async () => take(await api("POST", "/api/walkthroughs/" + W.view.id + "/cancel", signed())));
}

// While the chat waits on a job, its progress is read again; once the job ended, the walkthrough is told (it reads
// the job's end from the cockpit's own jobs, never from the page).
function poll() {
  clearTimeout(W.timer);
  if (!busy()) { W.polling = false; return; }
  W.polling = true;
  W.timer = setTimeout(async () => {
    if (!busy()) return;
    try {
      const out = await api("GET", "/api/walkthroughs/" + W.view.id);
      W.view = out.walkthrough;
      const job = W.view.job_view;
      if (job && !["running", "unknown"].includes(job.state)) {
        await take(await api("POST", "/api/walkthroughs/" + W.view.id + "/reply", Object.assign({ job: true }, signed())));
        return;
      }
      if (shown()) redrawProgress();
    } catch (e) {
      if (e instanceof AuthError) return;
    }
    poll();
  }, POLL_MS);
}

// A new message that takes you somewhere (a tour's stop, a conversation that opened) does so at once.
function follow() {
  const msgs = (W.view && W.view.messages) || [];
  const fresh = msgs.slice(W.seen).filter((m) => m.from === "rihma");
  W.seen = msgs.length;
  const goTo = fresh.find((m) => m.go);
  if (goTo) { location.hash = goTo.go; return; }
  const there = fresh.reverse().find((m) => m.navigate);
  if (there) setTimeout(() => takeThere(there.navigate), 50);
}

// -- the full map: the same map as New project's scan step, where files are unticked ---------------------

function openMap(folder) {
  const step = scanStep({ adopting: W.view && W.view.name === "plug_in", exclude: lastScan().exclude || [] });
  const use = button("Use this selection", { icon: "check", kind: "primary", key: "wk-map:use", onclick: () => {
    const exclude = step.exclude();
    closeModal();
    send({ exclude });
  } });
  openModal("What Rihmasto would read", h("div", { class: "wk-map" }, step.el, h("div", { class: "btns" }, use)), { wide: true, icon: "search" });
  step.scan(folder).catch((e) => { if (!(e instanceof AuthError)) say(e.message, "critical"); });
}
function lastScan() {
  const m = [...((W.view && W.view.messages) || [])].reverse().find((x) => x.scan);
  return (m && m.scan) || {};
}

// -- drawing --------------------------------------------------------------------------------------------------

function scanChips(s) {
  return h("div", { class: "wk-scan", "data-key": "wk-scan" },
    chip("good", "check-circle", n(s.read) + " read"), chip("info", "layers", n(s.summarised) + " summarised"),
    chip("neutral", "list", n(s.listed) + " listed"), chip(s.skipped ? "warning" : "neutral", "shield", n(s.skipped) + " skipped"),
    (s.languages || []).length ? chip("accent", "code", s.languages.join(", ")) : null,
    (s.ai_setup || []).length ? chip("info", "bot", "AI-tool setup: " + s.ai_setup.join(", ")) : null);
}
function linkButton(l, i, k) {
  if (l.map) return button(l.label, { icon: "search", kind: "small", key: k + ":map", onclick: () => openMap(l.map) });
  if ((l.guide || l.do) && nav.journey) {     // a journey's next step, or Guide me through the rest (FR-JRN1)
    return button(l.label, { icon: l.guide ? "flag" : "play", kind: "small" + (l.do ? " primary" : ""), key: k + ":jr:" + i,
      onclick: () => nav.journey.runLink(l) });
  }
  const go = { route: l.route || null, control: l.control || null };
  return button(l.label, { icon: "arrow-right", kind: "small", key: k + ":link:" + i, onclick: () => takeThere(go) });
}
function optionButtons(m, k, live) {
  return h("div", { class: "btns wk-opts", role: "group", "aria-label": "Options" }, m.options.map((o) => {
    const b = button(o.label, { kind: "small" + (o.id === "back" ? " quiet" : ""), key: k + ":opt:" + o.id, icon: o.id === "back" ? "chevron-left" : null,
      onclick: () => send({ choice: o.id }, b.parentNode) });
    if (!live) b.disabled = true;
    if (o.hint) { b.setAttribute("title", o.hint); b.append(h("small", { class: "wk-hint" }, o.hint)); }
    return b;
  }));
}
// A step that asks for a folder (or a file): Browse… and Browse here beside the answer box (picker.js, FR-PICK1);
// the chosen path is the answer, as if typed.
function pathButtons(m) {
  const either = /file/.test(m.input.placeholder || "");
  return browseButtons({ kind: either ? "either" : "folder", name: either ? "a file or a folder to give Rihma" : "the folder to give Rihma",
    title: either ? "Choose a file or a folder" : "Choose the project's folder", onPick: (p) => send({ text: p }) });
}
function proposalCard(m, k, live) {
  const p = m.proposal;
  const ok = button(p.label, { icon: "check", kind: "small primary", key: k + ":confirm" });
  ok.addEventListener("click", () => confirmIt(card));
  const card = h("div", { class: "prop wk-prop" + (live ? "" : " settled") }, h("div", { class: "prop-h" }, icon("check-circle"), h("b", null, p.label)),
    h("ul", { class: "prop-args" }, (p.lines || []).map((l) => h("li", null, l))),
    live ? h("div", { class: "btns" }, ok, h("span", { class: "muted small" }, "Signed with your name as you confirm."))
      : h("p", { class: "prop-st muted" }, icon("info"), h("span", null, "Not waiting on a confirm any more.")));
  return card;
}
function progress(m) {
  const job = (W.view && W.view.job_view) || {};
  const steps = job.progress || [];
  const live = busy() && m === lastRihma();
  return h("div", { class: "wk-progress", role: "status", "aria-live": "polite" },
    live && !job.live ? h("p", { class: "wk-run" }, h("span", { class: "dots", "aria-hidden": "true" }, h("i"), h("i"), h("i")),
      h("span", null, steps.length ? "Now: " + steps[steps.length - 1] : "Starting the job…")) : null,
    job.live ? strip(job.live, { title: "Adopting", icon: "download" })        // the job's plan, live (FR-PRG1)
      : steps.length ? h("ol", { class: "wk-steps small muted" }, steps.map((s) => h("li", null, s))) : null);
}
// While a job runs only its progress is drawn again, so a screen reader hears the new step, not the whole chat.
function redrawProgress() {
  const shownNow = [...document.querySelectorAll("#as-log .wk-progress")].pop();
  const m = [...((W.view && W.view.messages) || [])].reverse().find((x) => x.progress);
  if (shownNow && m) shownNow.replaceWith(progress(m)); else draw();
}
function lastRihma() { return [...((W.view && W.view.messages) || [])].reverse().find((m) => m.from === "rihma"); }

function message(m, i) {
  if (m.from === "person") return h("div", { class: "msg me" }, h("div", { class: "bub" }, m.text));
  const k = "wk:" + i;
  const live = active() && m === lastRihma();
  const test = m.test ? (m.test.ok ? chip("good", "check-circle", "Answered in " + m.test.latency_ms + " ms") : chip("critical", "x-circle", "Failed")) : null;
  return h("div", { class: "msg bot" }, h("span", { class: "bot-av" }, icon("bot")),
    h("div", { class: "bub wk-bub" + (m.refused ? " err" : "") },
      String(m.text).split("\n").map((line) => h("p", null, line)),
      test, m.scan ? scanChips(m.scan) : null,
      m.progress ? progress(m) : null,
      m.proposal ? proposalCard(m, k, live) : null,
      (m.options || []).length ? optionButtons(m, k, live) : null,
      live && m.input && m.input.kind === "path" ? pathButtons(m) : null,
      m.navigate ? h("div", { class: "btns" }, button("Take me there", { icon: "arrow-right", kind: "small", key: k + ":go", onclick: () => takeThere(m.navigate) })) : null,
      (m.links || []).length ? h("div", { class: "btns wk-links" }, m.links.map((l, j) => linkButton(l, j, k))) : null,
      m.read_by ? h("small", { class: "muted" }, "Read by the model; the rules could not place it.") : null));
}

// The walkthroughs as buttons. In the panel each carries its map control (cockpit/ui_map.json), so Take me there
// highlights it; elsewhere (Home's card, the panel's empty state) the same buttons carry none.
function pickerList(compact, where) {
  const list = (W.list && W.list.walkthroughs) || [];
  const going = W.view && W.view.state === "active" ? W.view : null;
  const tag = where || "panel";
  return h("ul", { class: "wk-picker" + (compact ? " compact" : ""), "aria-label": "Walkthroughs" },
    going ? h("li", { class: "wk-going" }, icon("clock"), h("span", null, "Going: " + going.label),
      button("Resume", { kind: "small primary", key: "wk-resume:" + tag, onclick: () => { openAssistant(); W.open = true; W.picker = false; draw(); poll(); } })) : null,
    list.map((w) => h("li", null, h("button", Object.assign({ type: "button", class: "wk-card",
      "data-key": "wk-start:" + tag + ":" + w.name, onclick: () => startWalk(w.name) }, tag === "panel" ? CONTROL[w.name] : null),
    icon(ICON[w.name] || "flag"), h("span", null, h("b", null, w.label), h("small", null, w.about))))));
}

function head() {
  const v = W.view;
  const steps = (v && v.steps) || [];
  const at = v ? Math.max(0, steps.indexOf(v.step)) + 1 : 0;
  return h("div", { class: "wk-head" }, icon(v && !W.picker ? ICON[v.name] || "flag" : "flag"),
    h("div", { class: "wk-title" }, h("b", null, W.picker || !v ? "Walkthroughs" : v.label),
      v && !W.picker ? h("small", { class: "muted" }, v.state === "active" ? "Step " + at + " of " + steps.length : v.state === "done" ? "Done" : "Cancelled") : null),
    h("div", { class: "btns" },
      !W.picker ? button("All", { kind: "small quiet", key: "wk-all", icon: "list", aria: "All walkthroughs", onclick: () => openPicker() }) : null,
      active() && !W.picker ? button("Cancel", { kind: "small quiet", key: "wk-cancel", icon: "x", onclick: () => cancelIt() }) : null,
      button("Questions", { kind: "small quiet", key: "wk-leave", icon: "message-square", aria: "Back to questions", onclick: () => leave() })));
}

function draw() {
  const box = $("#as-log");
  if (!box || $("#assistant").hidden) return;
  if (!W.open) { rerenderAssistant(); return; }
  const had = document.activeElement && box.contains(document.activeElement) ? document.activeElement.getAttribute("data-key") : null;
  const atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  fill(box, h("div", { class: "wk" }, head(), W.picker || !W.view
    ? [h("p", { class: "muted small" }, "Rihma takes you through it step by step, here in the chat. Nothing changes until you press Confirm."), pickerList(false)]
    : W.view.messages.map(message)));
  fill($("#as-suggest"));
  const note = $("#assistant .dr-note");
  if (note && W.note === null) W.note = note.textContent;
  if (note) note.textContent = "Each change waits on your Confirm, signed with your name.";
  const q = $("#as-q");
  const wait = W.view && W.view.awaiting;
  const input = wait && wait.input;
  q.placeholder = W.picker || !W.view ? "Or tell Rihma what you want to do" : !active() ? "This walkthrough has ended" : busy() ? "Rihma is waiting on the job" : (input && input.placeholder) || "Type your answer, or press a button";
  q.disabled = !!(W.view && !W.picker && (!active() || busy()));
  if (atEnd || W.focus) box.scrollTop = box.scrollHeight;
  const back = had && box.querySelector('[data-key="' + CSS.escape(had) + '"]');
  if (back && !back.disabled) back.focus();
  else if (W.focus === "next") focusNext(box);
  W.focus = null;
}
function focusNext(box) {
  const last = box.querySelector(".msg.bot:last-of-type") || box;
  const target = last.querySelector('[data-key$=":confirm"]') || last.querySelector(".wk-opts button:not([disabled])");
  if (target) target.focus(); else if (!$("#as-q").disabled) $("#as-q").focus();
}

export async function openPicker(control) {
  openAssistant();
  W.open = true;
  W.picker = true;
  await loadList();
  draw();
  if (control && control !== "walkthroughs") {
    const el = $('#as-log [data-control="' + CSS.escape(control) + '"]');
    if (el) highlight(el);
  }
}
function leave() {
  W.open = false;
  W.picker = false;
  const note = $("#assistant .dr-note");
  if (note && W.note !== null) note.textContent = W.note;
  W.note = null;
  $("#as-q").disabled = false;
  rerenderAssistant();
  $("#as-q").focus();
}

// -- the offers: in an answer, on Home, and the first-run card ---------------------------------------------------

function offerButton(o) {
  return h("div", { class: "btns wk-offer" }, button("Walk me through it: " + o.label + (o.said ? " (" + o.said + ")" : ""), { icon: ICON[o.name] || "flag", kind: "small primary", key: "wk-offer:" + o.name,
    onclick: () => startWalk(o.name, o.said) }), h("small", { class: "muted" }, o.about));
}
function homeButton() {
  return button("Walkthroughs", { icon: "flag", kind: "quiet", key: "home:walk", "data-control": "walkthroughs", onclick: () => openPicker() });
}
async function homeCard(box) {
  if (!box || local.get(HOME_KEY) === "later") return;
  let projects = [];
  try { projects = await api("GET", "/api/projects"); } catch (e) { return; }
  if (!box.isConnected || (projects || []).some((p) => p.id !== "_factory")) { fill(box); return; }
  await loadList();
  if (!box.isConnected) return;
  fill(box, card({ title: "New here? Let Rihma walk you through it", icon: "flag", id: "wk-home", cls: "wk-home" },
    h("div", { class: "card-body" }, h("p", null, "Plug in a project you have, start from an idea or documents, or take the five-stop tour. Rihma asks, shows what it finds, and changes nothing until you confirm."),
      nav.journey ? nav.journey.starters("home") : null,   // the three ways in, each guided step by step (FR-JRN1)
      pickerList(true, "home"),
      h("div", { class: "btns" }, button("Not now", { kind: "quiet small", key: "wk-home:later", onclick: () => { local.set(HOME_KEY, "later"); fill(box); } })))));
}

// Typed into the box: an answer to the walkthrough, or with the picker open, a walkthrough the words ask for.
function sendText(text) {
  const t = String(text || "").trim();
  if (!t || !W.view && !W.picker) return false;
  if (W.picker || !active()) { leave(); return false; }
  // A step that waits on its buttons, not on typed words: a question typed then is for Ask Rihma, not an answer
  // to the walkthrough (which stays where it is, to come back to).
  const wait = (W.view && W.view.awaiting) || {};
  if (wait.kind === "reply" && !wait.input && /\?\s*$|^(how|what|where|why|when|which|who|can|could|is|are|do|does|miten|mikä|missä|miksi|voinko)\b/i.test(t)) {
    leave();
    return false;
  }
  send({ text: t });
  W.focus = "next";
  return true;
}

nav.walk = {
  shown, render: draw, send: sendText, offerButton, homeButton, homeCard, openPicker, pickerList: () => pickerList(true, "hello"),
  start: startWalk,
};

// After a reload: the walkthrough that was going is read again, and its job polled.
export async function resumeWalk() {
  const opener = $("#as-walk");
  if (opener && !opener.dataset.wired) { opener.dataset.wired = "1"; opener.addEventListener("click", () => openPicker()); }
  const id = store.get(KEY);
  if (!id) { loadList(); return; }
  try { W.view = (await api("GET", "/api/walkthroughs/" + encodeURIComponent(id))).walkthrough; W.seen = W.view.messages.length; } catch (e) { store.del(KEY); }
  loadList();
  poll();
}
