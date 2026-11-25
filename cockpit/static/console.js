/* The Console tab (kernel/console.py, FR-CON1): run the project's own commands, or ask Gnomon, in its
   workspace, and watch the output line by line. Every run is a job, signed with the person and persona and
   recorded in the project's ledger (console_ran); its output stays in the job's log. "Open a terminal here"
   opens the operating system's own terminal on the machine the cockpit runs on. Where the line is: your IDE
   stays where you develop; this console runs one command at a time; a full-screen program belongs in a real
   terminal. */

import { S, h, fill, icon, chip, api, act, say, signed, needPerson, enc, button, card, empty, ago, personaLabel,
  nav } from "./core.js";

const STATE = {
  running: ["info", "refresh", "Running"], done: ["good", "check-circle", "Done"], failed: ["critical", "x-circle", "Failed"],
  stopped: ["warning", "stop", "Stopped"], timed_out: ["warning", "clock", "Timed out"],
  not_started: ["critical", "alert", "Did not start"], unknown: ["nm", "dashed", "Unknown"],
};
const WORKSPACE = { attached: "Your attached repository", workspace: "Your workspace",
  working_copy: "The console's working copy" };
const EVERY = 400;
const CUR = { pid: null, jid: null };     // the run the output pane shows, kept across re-renders

export function stateChip(state) {
  const [tone, ic, word] = STATE[state] || STATE.unknown;
  return chip(tone, ic, word, { "data-state": state || "unknown" });
}

const base = (pid) => "/api/projects/" + enc(pid) + "/console";

export function viewConsole(p) {
  const pid = p.meta.id;
  const box = h("div", { class: "con-tab" }, head(), h("p", { class: "muted" }, "Loading…"));
  drawConsole(box, pid).catch((e) => { if (box.isConnected) fill(box, head(), empty("alert", e.message)); });
  return box;
}

function head() {
  return h("div", { class: "q" }, h("h2", { id: "view-title", tabindex: "-1" }, "Console"),
    h("p", null, "Run this project's commands, or ask Gnomon, in its workspace. Your IDE stays where you develop; this "
      + "console runs one command at a time with its output line by line; a full-screen program belongs in a real "
      + "terminal (Open a terminal here)."));
}

async function drawConsole(box, pid) {
  const data = await api("GET", base(pid) + "?person=" + enc(S.person.trim()));
  if (!box.isConnected) return;
  const out = h("pre", { id: "con-out", class: "con-out", role: "log", "aria-live": "polite", "aria-label": "Output of the run",
    tabindex: "0" });
  const stateBox = h("span", { id: "con-state", class: "con-state" });
  const what = h("span", { class: "mono small con-what" });
  const stop = button("Stop", { icon: "stop", kind: "small", key: "console-stop", "data-control": "console_stop", disabled: true });
  const pane = { pid, out, stateBox, what, stop, runs: h("div", { class: "con-runs" }) };
  stop.addEventListener("click", () => act(null, () => stopRun(pane)));
  const ws = data.workspace || {};
  const allowed = (data.settings || {}).personas || [];
  fill(box, head(),
    allowed.includes(S.persona) ? null : h("p", { class: "note warning" }, icon("alert"),
      h("span", null, "The console here is for " + allowed.map(personaLabel).join(", ") + ": choose one of those personas to run.")),
    h("div", { class: "ev-grid" },
      card({ title: "Workspace", icon: "folder", id: "con-ws" },
        h("p", null, h("b", null, WORKSPACE[ws.kind] || "No workspace yet")),
        ws.path ? h("p", { class: "mono small con-path" }, ws.path) : null,
        h("p", { class: "muted small" }, ws.note || ""),
        h("p", { class: "small" }, "Who may run: " + (allowed.map(personaLabel).join(", ") || "nobody")),
        terminalBlock(pid, data.terminal || {})),
      card({ title: "Run a command", icon: "terminal", id: "con-cmd" }, commandForm(pane), offers(pane, data.offers || []))),
    card({ title: "Ask Gnomon", icon: "bot", id: "con-gn", info: "gnomon task in the workspace, under its own surface and "
      + "policy. Without the box ticked, every gated tool call is refused, as in any run with nobody to ask." }, gnomonForm(pane)),
    card({ title: "Output", icon: "rows", id: "con-o", tools: [stateBox, stop] }, what, out),
    card({ title: "Recent runs", icon: "clock", id: "con-recent" }, pane.runs),
    S.persona === "it" ? settingsCard(pid, data.settings || {}) : null);
  drawRuns(pane, data.runs || []);
  const latest = (data.runs || [])[0];
  const jid = CUR.pid === pid && CUR.jid ? CUR.jid : latest && latest.id;
  if (jid) follow(pane, jid);
  else fill(out, "Nothing has run here yet.");
  if (nav.refreshShell) nav.refreshShell();
}

function terminalBlock(pid, t) {
  const b = button("Open a terminal here", { icon: "terminal", key: "console-terminal", "data-control": "console_terminal",
    disabled: !t.available, tip: t.available ? "Your operating system's own terminal, in this workspace, with the "
      + "project's routing and Gnomon on PATH" : "Not here: " + t.why });
  b.addEventListener("click", () => act(b.parentNode, async () => {
    if (!needPerson()) return;
    const out = await api("POST", base(pid) + "/terminal", signed());
    say("A terminal opened in " + out.path + ". " + out.note + ".", "good");
  }));
  return h("div", { class: "btns" }, b, t.available ? null : h("span", { class: "muted small" }, "Not here: " + t.why));
}

function commandForm(pane) {
  const line = h("input", { id: "con-line", autocomplete: "off", spellcheck: "false", placeholder: "npm test",
    "aria-label": "Command line" });
  const shell = h("input", { type: "checkbox", id: "con-shell" });
  const run = button("Run", { icon: "play", kind: "primary", key: "console-run", "data-control": "console_run" });
  const go = () => act(run.parentNode, () => start(pane, { line: line.value.trim(), shell: shell.checked }));
  run.addEventListener("click", go);
  line.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } });
  return h("div", null, h("div", { class: "field" }, h("label", { for: "con-line" }, "Command line"), line),
    h("label", { class: "chk", for: "con-shell" }, shell, " Run through the shell (pipes, &&, redirects)"),
    h("div", { class: "btns" }, run));
}

function offers(pane, list) {
  if (!list.length) return h("p", { class: "muted small" }, "No command is known here yet: type one, or state the "
    + "project's commands (IT and developers, in the console's settings).");
  return h("div", null, h("p", { class: "small muted" }, "Known for this project:"),
    h("div", { class: "btns con-offers" }, list.map((o, n) => {
      const b = button(o.label, { kind: "small", icon: o.shell ? "terminal" : "play", key: "console-offer:" + n,
        "data-control": "console_run", tip: o.source + (o.shell ? " · runs through the shell" : "") + " · " + o.line });
      b.addEventListener("click", () => act(b.parentNode, () => start(pane, { line: o.line, shell: !!o.shell })));
      return b;
    })));
}

function gnomonForm(pane) {
  const text = h("textarea", { id: "con-gnomon", rows: "3", spellcheck: "true", placeholder: "Add a /health endpoint and its test" });
  const role = h("input", { id: "con-role", autocomplete: "off", spellcheck: "false", placeholder: "builder" });
  const yes = h("input", { type: "checkbox", id: "con-yes" });
  const ask = button("Ask Gnomon", { icon: "bot", key: "console-gnomon", "data-control": "console_gnomon" });
  ask.addEventListener("click", () => act(ask.parentNode, () => start(pane,
    { gnomon: text.value.trim(), role: role.value.trim() || null, yes: yes.checked })));
  return h("div", null, h("div", { class: "field" }, h("label", { for: "con-gnomon" }, "What should Gnomon do here?"), text),
    h("div", { class: "field" }, h("label", { for: "con-role" }, "Role (optional)"), role),
    h("label", { class: "chk", for: "con-yes" }, yes, " Let Gnomon apply gated changes without asking"),
    h("div", { class: "btns" }, ask));
}

async function start(pane, request) {
  if (!needPerson()) return;
  if (!request.line && !request.gnomon) { say("Type a command line, or what Gnomon should do.", "warning"); return; }
  const out = await api("POST", base(pane.pid) + "/run", Object.assign(request, signed()));
  say("Started " + out.job.id + (out.isolated ? ", isolated (" + out.isolated + ")" : "") + ".", "info");
  follow(pane, out.job.id);
}

async function stopRun(pane) {
  if (!needPerson() || !CUR.jid) return;
  const out = await api("POST", base(pane.pid) + "/runs/" + enc(CUR.jid) + "/stop", signed());
  say(out.stopped ? CUR.jid + " stopped." : CUR.jid + " was not running.", out.stopped ? "good" : "info");
}

// Read the run's output by offset until it ends: whole lines while it runs, then the rest.
function follow(pane, jid) {
  CUR.pid = pane.pid;
  CUR.jid = jid;
  fill(pane.out);
  fill(pane.stateBox, stateChip("running"));
  pane.stop.disabled = true;
  let offset = 0;
  const tick = async () => {
    if (!pane.out.isConnected || CUR.jid !== jid) return;
    let got;
    try {
      got = await api("GET", base(pane.pid) + "/output?job=" + enc(jid) + "&offset=" + offset);
    } catch (e) {
      if (pane.out.isConnected) fill(pane.stateBox, chip("critical", "alert", e.message));
      return;
    }
    if (!pane.out.isConnected || CUR.jid !== jid) return;
    if (got.text) {
      const end = pane.out.scrollTop + pane.out.clientHeight >= pane.out.scrollHeight - 8;
      pane.out.append(document.createTextNode(got.text));
      if (end) pane.out.scrollTop = pane.out.scrollHeight;
    }
    offset = got.offset;
    const job = got.job || {};
    fill(pane.what, (job.args || []).join(" ") + (job.by ? " · " + job.by.person : "") + (job.started ? " · " + ago(job.started) : ""));
    fill(pane.stateBox, stateChip(got.ended ? job.state : "running"));
    pane.stop.disabled = !!got.ended;
    if (got.ended) { refreshRuns(pane); return; }
    setTimeout(tick, EVERY);
  };
  tick();
}

async function refreshRuns(pane) {
  try {
    const data = await api("GET", base(pane.pid));
    if (pane.runs.isConnected) drawRuns(pane, data.runs || []);
  } catch (e) { /* the list stays as it was */ }
}

function drawRuns(pane, runs) {
  if (!runs.length) { fill(pane.runs, h("p", { class: "muted" }, "No run yet.")); return; }
  fill(pane.runs, h("ul", { class: "plain small con-list" }, runs.map((j) => {
    const b = h("button", { type: "button", class: "btn quiet small", "data-key": "console-open:" + j.id,
      "aria-label": "Show the output of " + j.id }, icon("eye"), h("span", { class: "lbl" }, "Show"));
    b.addEventListener("click", () => follow(pane, j.id));
    return h("li", { class: "con-li" }, stateChip(j.state), " ", h("span", { class: "mono" }, (j.args || []).join(" ")),
      h("span", { class: "muted" }, " · " + (j.what === "gnomon" ? "Gnomon · " : "") + ((j.by || {}).person || "") + " · " + ago(j.started)), " ", b);
  })));
}

function settingsCard(pid, st) {
  const picks = (S.personas || []).map((p) => h("label", { class: "chk", for: "con-p-" + p.id },
    h("input", { type: "checkbox", id: "con-p-" + p.id, value: p.id, class: "con-pick", checked: (st.personas || []).includes(p.id) ? true : null }),
    " " + p.label));
  const cmds = h("textarea", { id: "con-cmds", rows: "4", spellcheck: "false",
    placeholder: "test=python -m unittest -v" }, Object.entries(st.commands || {}).map(([k, v]) => k + "=" + v).join("\n"));
  const save = button("Save console settings", { icon: "check", kind: "small", key: "console-settings", "data-control": "console_settings" });
  save.addEventListener("click", () => act(save.parentNode, async () => {
    if (!needPerson()) return;
    const personas = [...document.querySelectorAll(".con-pick")].filter((x) => x.checked).map((x) => x.value);
    const commands = {};
    cmds.value.split("\n").map((l) => l.trim()).filter(Boolean).forEach((l) => {
      const i = l.indexOf("=");
      if (i > 0) commands[l.slice(0, i).trim()] = l.slice(i + 1).trim();
    });
    await api("PUT", base(pid) + "/settings", Object.assign({ personas, commands }, signed()));
    say("Console settings saved.", "good");
    if (nav.rerender) nav.rerender();
  }));
  return card({ title: "Console settings", icon: "settings", id: "con-set", info: "IT chooses which personas may run "
    + "commands here; developers, IT and product owners state the project's own commands." },
  h("fieldset", { class: "con-fs" }, h("legend", null, "Personas that may run commands"), h("div", { class: "con-picks" }, picks)),
  h("div", { class: "field" }, h("label", { for: "con-cmds" }, "The project's commands, one name=command line a row"), cmds),
  h("div", { class: "btns" }, save));
}

