/* Tasks you can open, and a list that moves (FR-LND1). The owner (2026-11-26): "Tasks view is maybe too static? ...
   shouldnt I be able to open the tasks somehow".

   - Every task opens a panel at #/p/<pid>/tasks/<id> (GET /api/projects/<pid>/task?id=, kernel/task_detail.py): its
     criteria, the tests that check it and how they last ended, the commits and agent sessions that touched it, its
     status history, and Hand it to a coding agent, Start it, Mark it done with evidence, Ask Rihma about it.
   - The board filters by status and by source (the factory's plan, the repository's own spec, the existing code at
     adoption), kept for this viewer in this browser only.
   - While the Tasks view is open and visible it asks every 5 s whether any task changed (a signature from
     GET /api/projects/<pid>/tasks) and draws the view again when one did, never while the person types. */

import { S, h, icon, api, enc, link, button, chip, signed, needPerson, act, say, nav, fmtAt, localJSON, openModal, fill } from "./core.js";
import { pick, datum, emptyState } from "./words.js";
import { openAssistant, send as askRihma } from "./assistant.js";

const EVERY = 5000;
const STATUS_TONE = { pending: "neutral", started: "info", building: "info", merged: "good", done: "good", escalated: "warning", stopped: "nm" };
const STATUS_SAID = { pending: ["not started", "pending"], started: ["started by a person", "started"], building: ["being built", "building"],
  merged: ["done and checked", "merged"], done: ["done, marked by a person", "marked done"], escalated: ["waits on a person", "escalated"], stopped: ["stopped", "stopped"] };
const SOURCE_SAID = { plan: ["from the plan", "plan"], repository: ["from its own files", "repository"], adopted: ["existing code", "adopted as-is"] };
const STATE_TONE = { verified: "good", claimed: "info", failed: "critical", not_measured: "nm" };
const AGENTS = [["claude-code", "Claude Code"], ["codex", "Codex"], ["opencode", "OpenCode"], ["cursor", "Cursor"], ["generic", "any coding agent"]];
const KEY = "gf.tasks.filter";

function said(table, k) { const w = table[k]; return w ? pick(w[0], w[1]) : String(k || ""); }
export function statusChip(s) { return chip(STATUS_TONE[s] || "neutral", null, said(STATUS_SAID, s)); }

// -- the filters (this viewer's, in this browser) ----------------------------------------------------------

// Kept per project (FR-LND2): one project's "marked done" never hides another project's tasks.
function keyOf(pid) { return KEY + ":" + pid; }
function statusOf(t) { return t.shown_status || t.status; }
function options(p) {
  return { status: Array.from(new Set(p.tasks.map(statusOf))), source: Array.from(new Set(p.tasks.map((t) => t.source || "plan"))) };
}
function filter(p) {
  const f = localJSON(keyOf(p.meta.id), {});
  const o = options(p);   // a value that is not one of this project's options filters nothing: the select would not say it
  return { status: o.status.includes(f.status) ? f.status : "", source: o.source.includes(f.source) ? f.source : "" };
}
function keep(pid, f) { try { localStorage.setItem(keyOf(pid), JSON.stringify(f)); } catch (e) { /* private window: kept for this page only */ } }
/* When the filters hide every task: say so, with the way to show them again (never an empty board). */
export function filteredOut(p) {
  if (!p.tasks.length || p.tasks.some(taskShown(p))) return null;
  return emptyState("tasks_filtered", button("Show every task", { icon: "filter", kind: "small", key: "tl-clear", "data-control": "task_filters",
    onclick: () => { keep(p.meta.id, {}); if (nav.rerender) nav.rerender(); } }));
}
export function taskShown(p) {
  const f = filter(p);
  return (t) => (!f.status || statusOf(t) === f.status) && (!f.source || (t.source || "plan") === f.source);
}

function select(id, label, value, options, onChange) {
  const el = h("select", { id, "data-key": id, "aria-label": label, "data-control": "task_filters" },
    options.map(([v, l]) => h("option", { value: v, selected: v === value || null }, l)));
  el.addEventListener("change", () => onChange(el.value));
  return h("label", { class: "tl-f", for: id }, h("span", { class: "small muted" }, label), el);
}

function filterBar(p) {
  const f = filter(p);
  const { status: statuses, source: sources } = options(p);
  const set = (k) => (v) => { const g = filter(p); g[k] = v; keep(p.meta.id, g); if (nav.rerender) nav.rerender(); };
  const shown = p.tasks.filter(taskShown(p)).length;
  return h("div", { class: "tl-bar", role: "group", "aria-label": "Filter the tasks" }, icon("filter"),
    select("tl-status", "Status", f.status, [["", "every status"], ...statuses.map((s) => [s, said(STATUS_SAID, s)])], set("status")),
    select("tl-source", "Source", f.source, [["", "every source"], ...sources.map((s) => [s, said(SOURCE_SAID, s)])], set("source")),
    h("span", { class: "small muted tl-n", "aria-live": "polite" }, shown + " of " + p.tasks.length + " shown"),
    h("span", { class: "small muted tl-live" }, icon("refresh"), pick(" Updates by itself while work runs", " Live: checked every 5 s while visible")));
}

/* A task card's extra line on the board: its source, a person's mark, and Open. */
export function taskCardExtra(pid, t) {
  const m = t.mark || {};
  return h("p", { class: "tc-o small" },
    chip("neutral", null, said(SOURCE_SAID, t.source || "plan"), { title: t.source_said || null }),
    m.done ? chip("good", "check", "marked done by " + m.done.person, { title: "marked done by " + m.done.person })
      : m.started && t.status === "pending" ? chip("info", "play", "started by " + m.started.person, { title: "started by " + m.started.person }) : null,
    h("a", { href: link(pid, "tasks", t.id), class: "tc-open", "data-control": "task_open", "data-key": "tc-open:" + t.id }, icon("expand"), " Open"));
}

// -- the panel of one task -------------------------------------------------------------------------------------

function section(title, ...body) { return h("section", { class: "td-s" }, h("h4", { class: "label-h" }, title), ...body); }

function criteriaBlock(d) {
  if (!d.criteria.length) return emptyState("task_criteria");
  return h("ul", { class: "td-list" }, d.criteria.map((c) => h("li", null,
    h("div", null, h("b", { class: "mono" }, c.id), " ", chip(STATE_TONE[c.state] || "nm", null, c.state.replace(/_/g, " "))),
    c.statement ? h("p", { class: "small muted", "data-ud": "" }, c.statement) : null,
    h("p", { class: "small", "data-ud": "" }, "Given " + (c.given || "-") + ", when " + (c.when || "-") + ", then " + (c.then || "-")))));
}

function testsBlock(d) {
  if (!d.tests.length) return emptyState("task_tests");
  return h("ul", { class: "td-list" }, d.tests.map((t) => h("li", null, h("code", { "data-raw": "" }, t.name), " ",
    chip(/^(ok|pass)/.test(t.result) ? "good" : /fail|error/.test(t.result) ? "critical" : "nm", null, t.result),
    h("span", { class: "small muted" }, " · " + t.from), t.why ? h("p", { class: "small muted" }, t.why) : null)));
}

function workBlock(d) {
  const commits = d.commits || [];
  const agents = (d.agents || []).concat((d.sessions || []).map((s) => ({ name: s.person, harness: s.harness_label || s.harness, via: "session " + (s.event || "") })));
  return h("div", { class: "td-two" },
    section(pick("Changes to the code", "Commits"), commits.length ? h("ul", { class: "td-list small" }, commits.map((c) => h("li", null, h("code", null, c.short), " ", datum(c.subject),
      h("span", { class: "muted" }, " · " + (c.author || "") + (c.on_main ? " · on main" : ""))))) : emptyState("task_commits", null, { how: d.commits_why })),
    section("Agents and sessions", agents.length ? h("ul", { class: "td-list small" }, agents.map((a) => h("li", null, icon("bot"), " ", datum(a.name || "an agent"),
      h("span", { class: "muted" }, " · " + [a.harness, a.via].filter(Boolean).join(" · "))))) : emptyState("task_agents")));
}

function historyBlock(d) {
  if (!d.history.length) return emptyState("task_history");
  return h("ol", { class: "td-hist small" }, d.history.slice(-20).reverse().map((e) => h("li", null,
    h("span", { class: "muted" }, fmtAt(e.at)), " ", datum(e.said), e.who ? h("span", { class: "muted" }, " · " + e.who) : null)));
}

async function write(pid, path, body, box, done) {
  if (!needPerson()) return;
  await act(box, async () => {
    const out = await api("POST", path, Object.assign(body || {}, signed()));
    if (done) done(out);
    if (nav.rerender) nav.rerender();
  });
}

function doneForm(pid, d, a, box) {
  const area = h("textarea", { id: "td-ev", "data-key": "td-ev", rows: "3", maxlength: "2000", placeholder: "The suite passed at abc1234; or a link to the run" });
  const form = h("div", { class: "td-done" }, h("label", { for: "td-ev", class: "small" }, "What shows it is done"), area,
    h("div", { class: "btns" }, button("Mark it done", { icon: "check", kind: "small primary", key: "td-done-go", "data-control": "task_done",
      onclick: () => {
        if (!area.value.trim()) { say("Say what shows it is done: a test run, a commit or a link.", "warning"); area.focus(); return; }
        write(pid, a.path, { evidence: area.value.trim() }, box, () => say(d.id + " is marked done, with your evidence.", "good"));
      } })));
  return form;
}

function handoffDialog(pid, d, a) {
  const to = h("select", { id: "tdh-to", "data-key": "tdh-to", "aria-label": "Which agent" }, AGENTS.map(([v, l]) => h("option", { value: v }, l)));
  const pre = h("pre", { class: "ho-brief", tabindex: "0", "aria-label": "The brief" }, pick("Press Hand it off: the brief for this task shows here, copied for you.", "Hand it off writes the task's brief here and copies it."));
  const acts = h("div", { class: "btns" });
  acts.append(button("Hand it off", { icon: "send", kind: "primary small", key: "tdh-go", "data-control": "task_handoff", onclick: () => act(acts, async () => {
    if (!needPerson()) return;
    const out = await api("POST", a.path, Object.assign({ to: to.value, via: "copy" }, signed()));
    pre.textContent = out.markdown;
    try { await navigator.clipboard.writeText(out.markdown); say("The brief for " + d.id + " is copied, and the hand-off is in the agent channel.", "good"); }
    catch (e) { say("The hand-off is recorded; select the brief and copy it by hand.", "warning"); }
  }) }));
  openModal("Hand " + d.id + " to a coding agent", h("div", { class: "ho" },
    h("p", { class: "muted small" }, "The brief names this task, its criteria and tests, how to run them and how to report back. The channel shows the hand-off, so the board and the trace see who works on it."),
    h("div", { class: "ho-row" }, h("label", { for: "tdh-to" }, "Agent"), to), pre, acts), { icon: "send", wide: true });
}

function actionsBlock(pid, d, box) {
  const slot = h("div", { class: "td-slot" });
  const btns = h("div", { class: "btns td-acts" }, d.actions.map((a) => {
    if (a.id === "handoff") return button(a.label, { icon: "send", kind: "small primary", key: "td-handoff", "data-control": "task_handoff", onclick: () => handoffDialog(pid, d, a) });
    if (a.id === "start") return button(a.label, { icon: "play", kind: "small", key: "td-start", "data-control": "task_start",
      onclick: () => write(pid, a.path, {}, box, () => say(d.id + " is started, signed with your name.", "good")) });
    if (a.id === "done") return button(a.label, { icon: "check", kind: "small", key: "td-done", "data-control": "task_done", onclick: () => slot.replaceChildren(doneForm(pid, d, a, box)) });
    return button(a.label, { icon: "bot", kind: "small quiet", key: "td-ask", "data-control": "task_ask", onclick: () => { openAssistant(); askRihma(a.question); } });
  }));
  return h("div", null, btns, slot);
}

function panelBody(pid, d, box) {
  const mark = d.mark || {};
  return [
    h("header", { class: "card-head" }, h("span", { class: "card-ic" }, icon("list")),
      h("h3", { class: "card-t", id: "td-h" }, h("span", { class: "mono" }, d.id), " ", h("span", { "data-ud": "" }, d.title)),
      h("span", { class: "card-tools" }, h("a", { href: link(pid, "tasks"), class: "btn tiny quiet", "data-key": "td-close", "aria-label": "Close the task" }, icon("x")))),
    h("p", { class: "td-st" }, statusChip(d.status), " ", chip("neutral", null, said(SOURCE_SAID, d.source)), " ",
      h("span", { class: "small muted", "data-ud": "" }, d.source_said),
      d.why ? h("span", { class: "small muted", "data-ud": "" }, " · " + d.why) : null),
    // one line of text beside its icon, never three narrow columns (FR-LND2)
    mark.done ? h("p", { class: "note small td-mark" }, icon("check"), h("span", null, "Marked done by " + mark.done.person + " on " + fmtAt(mark.done.at) + ": ", datum(mark.done.evidence || ""),
      pick(". The quality check has not checked it.", ". The gate's merge is not claimed."))) : null,
    // what it waits for first: the tasks it depends on, or the decision it is escalated to (kernel/task_rules.py)
    d.waits ? h("p", { class: "note warning small td-wait" }, icon("clock"), h("span", null, h("span", { "data-ud": "" }, d.waits.said + ". "),
      h("a", { href: d.waits.route, "data-key": "td-wait" }, d.waits.card ? "Decide " + d.waits.card : "Open " + d.waits.tasks[0]))) : null,
    d.gate_status === "building" ? h("p", { class: "small" }, icon("activity"), " Being built now. ",
      h("a", { href: "#/jobs/cell:" + enc(pid), "data-control": "run_log_open" }, "Open the whole log")) : null,
    actionsBlock(pid, d, box),
    section(pick("Acceptance checks", "Criteria"), criteriaBlock(d)),
    section("Tests that check it", testsBlock(d)),
    workBlock(d),
    section(pick("What happened to it", "Status history"), historyBlock(d)),
  ];
}

/* The panel of one task, above the board: drawn as soon as its record is read. */
export function taskPanel(pid, tid) {
  const box = h("section", { class: "card task-panel", "data-id": tid, "aria-labelledby": "td-h", "data-control": "task_open" },
    h("p", { class: "small muted" }, "Opening " + tid + "…"));
  api("GET", "/api/projects/" + enc(pid) + "/task?id=" + enc(tid)).then((d) => {
    if (!d.found) { box.replaceChildren(emptyState("task_missing", h("a", { href: link(pid, "tasks"), class: "btn small" }, "Show every task"), { what: tid + " is not one of this project's tasks.", how: d.why })); return; }
    fill(box, panelBody(pid, d, box));
  }).catch((e) => box.replaceChildren(h("p", { class: "small muted" }, tid + " could not be read: " + e.message)));
  return box;
}

/* What the Tasks view puts above its board: the filters, and the open task's panel. */
export function tasksTop(p, ctx) {
  const pid = p.meta.id;
  watchTasks(pid);
  return [p.tasks.length ? filterBar(p) : null, filteredOut(p), ctx && ctx.focus ? taskPanel(pid, ctx.focus) : null];
}

// -- live: the list moves while work runs ------------------------------------------------------------------

const W = { pid: null, sig: null, timer: null, seq: 0 };
function typing() { const a = document.activeElement; return !!a && (/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) || a.isContentEditable) || !!document.querySelector("#modal[open]"); }

function watchTasks(pid) {
  clearTimeout(W.timer);
  W.pid = pid;
  W.sig = null;
  const seq = S.seq;
  W.seq = seq;
  const tick = async () => {
    const here = S.route && S.route.name === "project" && S.route.pid === pid && S.route.view === "tasks";
    if (W.seq !== seq || !here) return;
    if (!document.hidden) {
      try {
        const r = await api("GET", "/api/projects/" + enc(pid) + "/tasks");
        if (W.seq !== seq) return;
        if (W.sig === null) W.sig = r.signature;
        else if (r.signature !== W.sig && !typing()) { W.seq = -1; if (nav.rerender) nav.rerender(); return; }
      } catch (e) { /* the next tick tries again; the page says nothing about one missed check */ }
    }
    W.timer = setTimeout(tick, EVERY);
  };
  W.timer = setTimeout(tick, 50);
}
