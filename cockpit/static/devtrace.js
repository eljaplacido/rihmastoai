/* A project's trace (FR-DEV1, kernel/devtrace.py): every interaction of people and agents with its development as
   one timeline, newest first: people's decisions and answers, Rihma's roles asking a model, the builder cell's
   rounds, gate rounds and merges, workspaces, MCP writes, outside sessions captured by hooks, the agent channel's
   posts and hand-offs. Each line says who (a person and their role, Rihma in a role, an agent with its harness and
   operator), what, and the task; Details opens the record itself. Filters: the time window, who, the harness, the
   task. Below, the session hooks for Claude Code and Cursor a project installs (metadata only), to copy or
   download, and the sessions they recorded. Ask Rihma answers "what did the agents do since yesterday?" the same
   way, by rule. */

import { S, h, fill, icon, chip, api, enc, button, say, segmented, personaLabel } from "./core.js";
import { pick, emptyState, datum, localDateTime, plurals } from "./words.js";
import { askButton, harnessWord } from "./devboard.js";

const WHO_WORDS = { person: "People", rihma: "Rihma", agent: "Agents", automation: "Automations", system: "Rihmasto itself" };
const WHO_ICON = { person: "user", rihma: "sparkles", agent: "bot", automation: "clock", system: "diamond" };
const F = { window: "7d", who: "", harness: "", task: "" };

function whoEl(w) {
  const kind = w.kind || "system";
  const extra = kind === "person" ? personaLabel(w.persona) : kind === "rihma" ? (w.role || "") :
    kind === "agent" ? harnessWord(w.harness) + (w.operator ? " for " + w.operator : "") : "";
  return h("span", { class: "dv-who dv-" + kind }, icon(WHO_ICON[kind] || "info"),
    h("span", { class: "who-n", "data-ud": "" }, w.name || WHO_WORDS[kind]),
    extra ? h("span", { class: "who-r", "data-ud": "" }, extra) : null);
}

function itemEl(pid, i) {
  return h("li", { class: "dv-item", "data-ref": i.id, "data-who": (i.who || {}).kind || "" },
    h("div", { class: "dv-row" }, h("span", { class: "dv-at" }, localDateTime(i.at)), whoEl(i.who || {}),
      i.task ? h("a", { class: "chip neutral dv-task", href: "#/p/" + enc(pid) + "/tasks/" + enc(i.task) }, i.task) : null),
    h("p", { class: "dv-what", "data-ud": "" }, plurals(i.what)),
    h("details", { class: "tc-d" }, h("summary", null, pick("Details", "Record ") + (pick("", i.id))),
      h("pre", { class: "dv-rec mono" }, JSON.stringify(i.record, null, 2))));
}

function opt(name, label, values, word) {
  const s = h("select", { "aria-label": label, "data-key": "trace:f:" + name },
    h("option", { value: "" }, label + ": all"), values.map((v) => h("option", { value: v, selected: F[name] === v || null }, word ? word(v) : v)));
  s.addEventListener("change", () => { F[name] = s.value; s.dispatchEvent(new CustomEvent("dv-filter", { bubbles: true })); });
  return s;
}

function filterBar(t) {
  const win = segmented("trace-window", [["24h", "24 hours"], ["7d", "7 days"], ["30d", "30 days"], ["all", "All"]], F.window,
    (v) => { F.window = v; win.dispatchEvent(new CustomEvent("dv-filter", { bubbles: true })); }, { label: "Time window" });
  return h("div", { class: "dv-filters", "data-control": "dev_filters", role: "group", "aria-label": "Filter the trace" },
    win, opt("who", "Who", t.filters.who, (k) => WHO_WORDS[k] || k),
    opt("harness", pick("Tool or role", "Harness or role"), t.filters.harnesses, harnessWord), opt("task", "Task", t.filters.tasks));
}

function counts(t) {
  return h("div", { class: "chips" }, Object.entries(t.counts).filter(([, n]) => n).map(([k, n]) => chip("neutral", WHO_ICON[k], WHO_WORDS[k] + " " + n)),
    h("span", { class: "muted small" }, t.shown < t.total ? "newest " + t.shown + " of " + t.total : ""));
}

// -- the session hooks ------------------------------------------------------------------------------------

function saveFile(name, text) {
  const a = h("a", { href: URL.createObjectURL(new Blob([text], { type: "text/plain" })), download: name.split("/").pop() });
  document.body.append(a);
  a.click();
  a.remove();
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); say("Copied.", "good"); } catch (e) { say("Copy it by hand from the box.", "warning"); }
}

function fileEl(f) {
  const where = { both: "both tools", "claude-code": "Claude Code", cursor: "Cursor" }[f.for] || f.for;
  return h("div", { class: "dv-file", "data-file": f.path },
    h("div", { class: "dv-file-h" }, h("code", null, f.path), chip("neutral", "bot", where),
      f.merge ? h("span", { class: "muted small" }, pick("add to the file if it is there", "merge into an existing file")) : null,
      button("Copy", { icon: "copy", kind: "small quiet", key: "hooks:copy:" + f.path, onclick: () => copy(f.content) }),
      button("Download", { icon: "download", kind: "small quiet", key: "hooks:dl:" + f.path, onclick: () => saveFile(f.path, f.content) })),
    h("details", { class: "tc-d" }, h("summary", null, "Show it"), h("pre", { class: "dv-rec mono" }, f.content)));
}

function hooksCard(d) {
  const rec = d.recorded || [];
  return h("section", { class: "card dv-hooks", "aria-labelledby": "dv-hooks-h", "data-id": "dev_hooks", "data-control": "dev_hooks" },
    h("header", { class: "card-head" }, h("span", { class: "card-ic" }, icon("plug")),
      h("h3", { class: "card-t", id: "dv-hooks-h" }, pick("Capture work done in Claude Code and Cursor", "Session hooks for Claude Code and Cursor"))),
    h("p", { class: "small" }, pick("Save these files in the project's folder. Each time an AI helper session starts or ends there, Rihmasto notes it here: ",
      "Save these in the repository. On each session start and end the hook records "), datum(d.records + "."),
    " ", pick("Never what was said or the code itself.", "Never a prompt, a file's content or the transcript.")),
    h("p", { class: "small muted" }, datum("Add " + d.ignore + ".")),
    d.files.map(fileEl),
    h("h4", { class: "dv-sub" }, "Sessions recorded"),
    rec.length ? h("ul", { class: "plain dv-sess" }, rec.map((s) => h("li", null, h("span", { class: "dv-at" }, localDateTime(s.at)), " ",
      chip("neutral", "bot", s.harness_label), " ", datum((s.event === "start" ? "started" : "ended") + " by " + s.person
        + (s.branch ? " on " + s.branch : "") + (s.commits != null ? ", " + s.commits + " commits" : "")))))
      : emptyState("dev_hooks", askButton("How do I capture my Claude Code and Cursor sessions in this project?", "Ask Rihma how", "hooks:ask"),
        { icon: "plug", what: "No outside session is recorded yet.", how: pick("Save the files above in the project's folder; the next session there appears here.",
          "Save the files above in the repository; the next session there appears here and on the board.") }));
}

// -- drawing ----------------------------------------------------------------------------------------------

function query() {
  const q = new URLSearchParams({ window: F.window });
  ["who", "harness", "task"].forEach((k) => { if (F[k]) q.set(k, F[k]); });
  return q.toString();
}

async function drawList(holder, pid) {
  const t = await api("GET", "/api/projects/" + enc(pid) + "/dev/trace?" + query());
  if (!holder.isConnected) return null;
  const list = t.items.length ? h("ol", { class: "plain dv-timeline", "aria-label": "Trace, newest first" }, t.items.map((i) => itemEl(pid, i)))
    : emptyState("dev_trace", askButton("Why is there nothing in this project's trace, and what would appear there?", "Ask Rihma why", "trace:ask-empty"),
      { icon: "timeline", what: "Nothing happened in this window" + (F.who || F.harness || F.task ? " with these filters" : "") + ".",
        how: pick("Decisions, AI helpers' work and checks appear here as they happen; choose a longer window or clear the filters.",
          "Decisions, cells, gate rounds, channel posts and outside sessions appear as they are recorded; widen the window or clear the filters.") });
  fill(holder, filterBar(t), counts(t), list);
  return t;
}

function head() {
  return h("div", { class: "q" }, h("h2", { class: "view-h", id: "view-title", tabindex: "-1" }, pick("Who did what", "Trace")),
    h("p", null, pick("Every step people and AI helpers took on this project, newest first.",
      "Every interaction of people, Rihma's roles and agents in any harness, newest first, each expandable to its record.")));
}

export function render(p) {
  const pid = p.meta.id;
  const holder = h("div", { class: "dv-trace" }, h("p", { class: "muted" }, "Reading the records…"));
  const hooks = h("div", { class: "dv-hooks-holder" });
  const box = h("div", { class: "dv-view", "aria-busy": "true" }, head(),
    h("div", { class: "btns" }, askButton("What did the agents do since yesterday?", "What did the agents do since yesterday?", "trace:ask")), holder, hooks);
  const fail = (e) => { box.removeAttribute("aria-busy"); if (box.isConnected) fill(holder, emptyState("dev_trace", askButton("Why can the trace not be read?", "Ask Rihma why", "trace:ask-error"), { icon: "alert", what: "The trace could not be read: " + e.message, how: "Try again in a moment; if it stays, Ask Rihma what is wrong." })); };
  holder.addEventListener("dv-filter", () => drawList(holder, pid).catch(fail));
  const person = S.person.trim();
  Promise.all([drawList(holder, pid),
    api("GET", "/api/projects/" + enc(pid) + "/dev/hooks?persona=" + enc(S.persona) + (person ? "&person=" + enc(person) : ""))
      .then((d) => { if (hooks.isConnected && d.files) fill(hooks, hooksCard(d)); })])
    .then(() => box.removeAttribute("aria-busy")).catch(fail);
  return box;
}
