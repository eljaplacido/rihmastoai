/* The observer's page (kernel/observe_page.py, FR-SHR1): a guest watches what someone shared, read only.

   The link's token sits after "#", so no server, log or link preview receives it; it is exchanged for a session
   kept in this tab only, and the address is cleaned at once. The page asks for the shared view every few seconds:
   the views in scope (overview, plan, decisions waiting, activity, the agent channel), and following: the view the
   person who shared is on and their latest actions, with a pause. A guest may comment (signed with their name,
   marked as a guest's) and, on a link for defining a project together, suggest answers to the intake questions;
   never decide, run or change anything. Everything shown is text from the server, set as text. */

import { h, fill } from "./core.js";
import { datum, emptyState, eventWord, localDateTime } from "./words.js";

const KEY = "rihma.observer.session";
const EVERY = 4000;
const TABS = [["overview", "Overview"], ["plan", "Plan"], ["decisions", "Decisions waiting"], ["activity", "Activity"], ["channel", "Agent channel"]];
// a cockpit view, as the closest view a guest has
const FOLLOWS = { overview: "overview", plan: "plan", spec: "plan", tasks: "plan", questions: "plan", requirements: "plan",
  track: "plan", board: "plan", inbox: "decisions", inbox_all: "decisions", decide: "decisions", triage: "decisions",
  ledger: "activity", review: "activity", review_all: "activity", who: "activity", trace: "activity",
  agents: "channel", agents_all: "channel" };
const O = { session: null, data: null, pid: null, tab: "overview", follow: true, timer: null, busy: false, said: "" };
const main = document.getElementById("main");

function store(v) { try { if (v) sessionStorage.setItem(KEY, v); else sessionStorage.removeItem(KEY); } catch (e) { /* private mode */ } }
function stored() { try { return sessionStorage.getItem(KEY); } catch (e) { return null; } }

async function call(path, body) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store",
    credentials: "omit", referrerPolicy: "no-referrer", body: JSON.stringify(body) });
  let data = {};
  try { data = await res.json(); } catch (e) { data = {}; }
  if (!res.ok) { const err = new Error(data.error || "Something went wrong. Try again in a moment."); err.status = res.status; throw err; }
  return data;
}

function refused(message) {
  store(null);
  clearInterval(O.timer);
  fill(main, h("h1", null, "Watching"), h("p", { class: "ob-err", role: "alert", "data-ud": "" }, message));
}

function head(d) {
  const scope = d.scope === "platform" ? "Platform-wide: every project shared" : "One project";
  return h("header", { class: "ob-head" },
    h("h1", null, "Watching ", datum(d.scope_title)),
    h("p", { class: "ob-meta" }, h("span", { class: "chip info" }, "Read only"), " ", h("span", { class: "chip neutral", "data-scope": d.scope }, scope),
      " Shared by ", datum(d.from), " with ", datum(d.guest), " · until " + localDateTime(d.expires)),
    h("p", { class: "small muted" }, "You can watch and comment. You cannot decide, run or change anything here."));
}

function followBox(d) {
  const f = d.following || { state: "away", actions: [] };
  // the kernel's words for the view (FR-SHR2), never its route id
  const where = { here: () => [datum(f.sharer), " is on ", h("b", { "data-ud": "" }, f.view_words || "a view"), f.project_title ? [" of ", datum(f.project_title)] : null],
    paused: () => [datum(f.sharer), " paused showing where they are. The shared views stay."],
    elsewhere: () => [datum(f.sharer), " is on something not shared with you."],
    away: () => [datum(f.sharer), " is not in Rihmasto right now."] }[f.state] || (() => "");
  const toggle = h("button", { type: "button", class: "btn small", "aria-pressed": String(O.follow), "data-key": "ob:follow" },
    O.follow ? "Pause following" : "Follow " + f.sharer);
  toggle.addEventListener("click", () => { O.follow = !O.follow; draw(); });
  const acts = (f.actions || []).map((a) => h("li", null, h("span", { class: "small muted" }, localDateTime(a.at) + " · "),
    eventWord(a.kind), " ", h("span", { class: "small muted" }, "in "), datum(a.project)));
  return h("section", { class: "card ob-follow", "aria-labelledby": "ob-f-h" },
    h("h2", { class: "card-t", id: "ob-f-h" }, "Following"), h("p", { "data-state": f.state }, where()),
    h("div", { class: "btns" }, toggle),
    acts.length ? [h("h3", { class: "ob-sub" }, "Latest actions"), h("ul", { class: "ob-list" }, acts)]
      : h("p", { class: "small muted" }, "Their latest actions appear here as they work."));
}

function tabBody(p) {
  if (!p) return emptyState("observer", null, {});
  if (O.tab === "overview") {
    return h("div", { class: "ob-pane" }, h("p", { class: "ob-now", "data-ud": "" }, p.now.line || "No news."),
      h("p", { class: "small muted" }, "Stage " + (p.stage || "?") + (p.stage_name ? ": " + p.stage_name : "")),
      h("p", { class: "small" }, p.plan.requirements.length + " requirements · " + p.plan.tasks.length + " tasks · "
        + p.decisions.length + " decisions waiting"));
  }
  if (O.tab === "plan") {
    const reqs = p.plan.requirements.map((r) => h("li", null, h("b", null, r.id + " "), datum(r.statement)));
    const tasks = p.plan.tasks.map((t) => h("li", null, h("b", null, t.id + " "), datum(t.title), h("span", { class: "small muted" }, " · " + t.status)));
    return reqs.length || tasks.length ? h("div", { class: "ob-pane" }, reqs.length ? [h("h3", { class: "ob-sub" }, "Requirements"), h("ul", { class: "ob-list" }, reqs)] : null,
      tasks.length ? [h("h3", { class: "ob-sub" }, "Tasks"), h("ul", { class: "ob-list" }, tasks)] : null)
      : emptyState("observer", null, { what: "No plan yet.", how: "Requirements and tasks appear here once the project's plan is written." });
  }
  if (O.tab === "decisions") {
    return p.decisions.length ? h("ul", { class: "ob-list" }, p.decisions.map((c) => h("li", null, h("b", null, c.id + " "), datum(c.title),
      c.blocking ? h("span", { class: "chip warning" }, "holds work") : null)))
      : emptyState("observer", null, { what: "No decision waits.", how: "Decisions waiting for a person appear here; only the people on the project decide them." });
  }
  if (O.tab === "activity") {
    return p.activity.length ? h("ul", { class: "ob-list" }, p.activity.map((e) => h("li", null, h("span", { class: "small muted" }, localDateTime(e.at) + " · "),
      eventWord(e.kind), " · ", datum(e.who)))) : emptyState("observer", null, {});
  }
  return p.channel.length ? h("ul", { class: "ob-list" }, p.channel.map((m) => h("li", null, h("b", null, datum(m.who)),
    h("span", { class: "small muted" }, " · " + (m.kind || "") + " · " + localDateTime(m.at)), h("p", { "data-ud": "" }, m.text))))
    : emptyState("observer_channel", null, {});
}

function tabs() {
  return h("div", { class: "seg ob-tabs", role: "tablist", "aria-label": "Views" }, TABS.map(([id, label]) =>
    h("button", { type: "button", role: "tab", class: "seg-b", "aria-selected": String(O.tab === id), "aria-checked": String(O.tab === id),
      "data-key": "ob-tab:" + id, onclick: () => { O.tab = id; draw(); } }, h("span", { class: "lbl" }, label))));
}

function commentBox(d, p) {
  const text = h("textarea", { id: "ob-comment", rows: "3", maxlength: "2000", "aria-label": "Your comment",
    placeholder: "Write a comment for " + d.from + "…" });
  const send = h("button", { type: "button", class: "btn primary", "data-key": "ob:comment" }, "Comment");
  const said = h("p", { class: "small", role: "status" }, O.said);
  send.addEventListener("click", async () => {
    if (!text.value.trim() || !p) return;
    send.disabled = true;
    try {
      await call("/o/api/comment", { session: O.session, project: p.pid, text: text.value, about: O.tab });
      text.value = "";
      O.said = said.textContent = "Sent, signed as " + d.guest + " (guest).";
      await refresh();
    } catch (e) { said.textContent = e.message; } finally { send.disabled = false; }
  });
  const mine = (d.comments || []).slice().reverse().map((c) => h("li", null, h("b", null, datum(c.guest)), " ",
    h("span", { class: "chip accent" }, "Guest"), h("span", { class: "small muted" }, " · " + localDateTime(c.at)), h("p", { "data-ud": "" }, c.text)));
  return h("section", { class: "card", "aria-labelledby": "ob-c-h" }, h("h2", { class: "card-t", id: "ob-c-h" }, "Comments"),
    h("div", { class: "ob-form" }, text, h("div", { class: "btns" }, send), said),
    mine.length ? h("ul", { class: "ob-list" }, mine) : emptyState("observer_comments", null, {}));
}

function intakeBox(d) {
  if (!d.intake) return null;
  const rows = (d.questions || []).map((q) => {
    const input = h("input", { type: "text", maxlength: "2000", "aria-label": "Your suggestion for " + q.id, placeholder: "Your suggested answer" });
    const go = h("button", { type: "button", class: "btn small", "data-key": "ob:suggest:" + q.id }, "Suggest");
    go.addEventListener("click", async () => {
      if (!input.value.trim()) return;
      go.disabled = true;
      try { await call("/o/api/suggest", { session: O.session, question: q.id, text: input.value }); input.value = ""; await refresh(); }
      catch (e) { input.setCustomValidity(e.message); input.reportValidity(); } finally { go.disabled = false; }
    });
    return h("li", null, h("b", null, q.id + " "), datum(q.text), h("div", { class: "ob-suggest" }, input, go));
  });
  const offered = (d.suggestions || []).map((s) => h("li", null, h("b", null, s.question + " "), datum(s.text), h("span", { class: "small muted" }, " · " + s.state)));
  return h("section", { class: "card", "aria-labelledby": "ob-i-h" }, h("h2", { class: "card-t", id: "ob-i-h" }, "Define the project together"),
    h("p", { class: "small muted" }, "Your suggestions wait for " + d.from + " to confirm. They are not answers until then."),
    rows.length ? h("ul", { class: "ob-list" }, rows) : h("p", { class: "small" }, "No question is open."),
    offered.length ? [h("h3", { class: "ob-sub" }, "Your suggestions"), h("ul", { class: "ob-list" }, offered)] : null);
}

function draw() {
  const d = O.data;
  if (!d) return;
  const f = d.following || {};
  if (O.follow && f.state === "here" && f.view && FOLLOWS[f.view]) O.tab = FOLLOWS[f.view];
  const p = d.project;
  const picker = d.projects.length > 1 ? h("label", { class: "ob-pick" }, h("span", { class: "small" }, "Project "),
    h("select", { id: "ob-project", "aria-label": "Project", onchange: (e) => { O.pid = e.target.value; O.follow = false; refresh(); } },
      d.projects.map((x) => h("option", { value: x.pid, selected: p && x.pid === p.pid ? true : null }, x.title)))) : null;
  const focused = document.activeElement && document.activeElement.closest && document.activeElement.closest(".ob-form, .ob-suggest");
  if (focused) {   // never redraw under someone typing: only the parts they are not in
    const view = main.querySelector(".ob-view");
    if (view) fill(view, h("h2", { class: "ob-title" }, p ? datum(p.title) : "Nothing shared"), tabs(), tabBody(p));
    return;
  }
  fill(main, head(d), h("div", { class: "ob-cols" },
    h("div", { class: "ob-main" }, picker, h("section", { class: "card ob-view" }, h("h2", { class: "ob-title" }, p ? datum(p.title) : "Nothing shared"), tabs(), tabBody(p)),
      commentBox(d, p), intakeBox(d)),
    h("div", { class: "ob-side" }, followBox(d))));
}

async function refresh() {
  if (O.busy || !O.session) return;
  O.busy = true;
  const asked = O.session;
  try {
    const f = O.data && O.data.following;
    const pid = O.follow && f && f.state === "here" && f.project ? f.project : O.pid;
    const got = await call("/o/api/view", { session: asked, project: pid || "" });
    if (asked !== O.session) return;              // a new link was opened meanwhile
    O.data = got;
    O.pid = O.data.project ? O.data.project.pid : null;
    draw();
  } catch (e) {
    if (e.status === 403 && asked === O.session) refused(e.message);
  } finally { O.busy = false; }
}

async function start() {
  const token = (location.hash || "").replace(/^#/, "");
  if (token) {
    history.replaceState(null, "", location.pathname);   // the token leaves the address bar at once
    clearInterval(O.timer);
    Object.assign(O, { session: null, data: null, pid: null, tab: "overview", follow: true, said: "", busy: false });
    try { O.session = (await call("/o/api/open", { link: token })).session; store(O.session); } catch (e) { refused(e.message); return; }
  } else if (!O.session) {
    O.session = stored();
  }
  if (!O.session) { refused("Open the link you were given: it has everything this page needs."); return; }
  await refresh();
  clearInterval(O.timer);
  O.timer = setInterval(() => { if (!document.hidden) refresh(); }, EVERY);
}

// A new link pasted into this tab changes only the hash: open it as a fresh load would (FR-SHR2).
window.addEventListener("hashchange", () => { if ((location.hash || "").length > 1) start(); });
start();
