/* Agent sessions: what the IDE agents did in a project's repository (kernel/agentobs, FR-OBS1).
   An opt-in module (Settings, Modules), a view for developers and IT. Everything is read through the cockpit's
   own API from the team's agent observability hub when the view opens; nothing is kept unless a person records
   a snapshot. Each section is measured, or says "not measured" with why and how, never a zero. Every link into
   the hub opens the hub's own page for the detail. Rihmasto installs nothing: the hub's command to instrument a
   repository is shown for the person to run in their own shell. */

import { S, h, fill, icon, chip, api, enc, card, button, say, plural, signed, needPerson, act, empty, num, pct, ago,
  AuthError, nav, mayAct, everything } from "./core.js";
import { columns, bars, segbar, dataTable, SERIES, legend } from "./charts.js";

export const AGENTOBS_SEES = ["developer", "it"];
// As the person's persona, or (viewing "everything", FR-PPL1) through a persona they hold: the solo person holds
// every persona, so the view, the mapping, the snapshot and the hub's address are theirs without switching.
export function agentSessionsFor() { return mayAct(AGENTOBS_SEES); }

const HARNESS = { "claude-code": "Claude Code", cursor: "Cursor", opencode: "OpenCode" };
const harness = (id) => HARNESS[id] || id || "unknown";
const KIND = { read: ["Read", SERIES(1)], edit: ["Edit", SERIES(2)], run: ["Run", SERIES(3)], fail: ["Failed", "var(--critical-mark)"],
  ask: ["Prompt", SERIES(5)], other: ["Other", "var(--neutral-mark)"] };

function hubLink(url, label, key) {
  if (!url) return null;
  return h("a", { class: "btn small quiet", href: url, target: "_blank", rel: "noopener noreferrer", "data-key": key },
    icon("external"), h("span", { class: "lbl" }, label || "Open in the hub"));
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); say("Copied.", "good"); } catch (e) { say("Copy it by hand from the box.", "warning"); }
}

function nmBlock(sec) {
  return h("div", { class: "obs-nm" }, h("p", null, chip("nm", "dashed", "Not measured"), " ", sec.why + "."),
    sec.how ? h("p", { class: "small muted" }, "How: " + sec.how + ".") : null);
}

function section(title, ic, id, sec, ui, draw, info) {
  return card({ title, icon: ic, id: "obs-" + id, cls: "obs-card", dataId: "obs_" + id, info,
    tools: [sec && sec.measured ? hubLink(ui, "Detail in the hub", "obs-hub:" + id) : null] },
  sec && sec.measured ? draw(sec) : nmBlock(sec || { why: "nothing was read", how: "" }));
}

// -- the sections ---------------------------------------------------------------------------------------

function sessionsBody(sec, rows) {
  const series = sec.harnesses.map((x, i) => ({ key: x, label: harness(x), color: SERIES(i + 1) }));
  const chart = columns({ series, rows: sec.rows.map((r) => ({ label: r.day, short: r.day.slice(5), values: r.values })), height: 140 });
  return [h("p", { class: "obs-lead" }, h("b", null, plural(sec.count, "session")), " · ",
    Object.entries(sec.totals).map(([k, n]) => harness(k) + " " + n).join(" · "),
    sec.with_failure ? " · " + plural(sec.with_failure, "session") + " with a failure" : ""),
  chart, h("p", { class: "small muted" }, "Days with sessions, newest " + sec.shown_days + " shown, by the day the session started (UTC)."),
  dataTable([{ label: "Session", value: (r) => h("code", null, String(r.session_id).slice(0, 18)) },
    { label: "Harness", value: (r) => harness(r.harness) }, { label: "Started", value: (r) => ago(r.started_at) },
    { label: "Steps", num: true, value: (r) => num(r.step_count) },
    { label: "Failures", num: true, value: (r) => r.failures.failures ? r.failures.failures + (r.failures.unrecovered ? " (" + r.failures.unrecovered + " stuck)" : "") : "none" },
    { label: "Contract first", value: (r) => r.contract_first === null ? null : r.contract_first ? "yes" : "no", none: "—" }],
  rows.slice(0, 20), "The sessions, newest first")];
}

function reworkBody(sec) {
  return [h("p", { class: "obs-lead" }, h("b", null, plural(sec.files_above_threshold, "file")), " at or above " + sec.threshold
    + " edits, of " + plural(sec.total_files_edited, "file") + " edited (" + sec.total_edits + " edits)."),
  bars({ rows: sec.files.map((f) => ({ label: f.label || f.file, sub: f.directory, value: f.edits, display: plural(f.edits, "edit"),
    tip: f.file + ": " + plural(f.sessions, "session"), color: f.edits >= sec.threshold ? "var(--warning-mark)" : SERIES(1) })), unit: "edits" }),
  h("p", { class: "small muted" }, sec.basis + ".")];
}

function failuresBody(sec) {
  const stuck = sec.unrecovered_sessions || [];
  return [h("p", { class: "obs-lead" }, h("b", null, plural(sec.tool_failures || 0, "failure")), " in " + plural(sec.tool_events, "tool call")
    + ". Recovery rate " + (sec.recovery_rate === null ? "not measured" : pct(sec.recovery_rate)) + "."),
  segbar({ parts: [{ label: "Recovered", value: sec.recovered_failures || 0, color: "var(--good-mark)", icon: "check-circle" },
    { label: "Not recovered", value: sec.blocked_failures || 0, color: "var(--critical-mark)", icon: "x-circle" },
    { label: "Cannot be told", value: sec.undetermined_failures || 0, hatch: true, icon: "dashed" }], none: "No failure recorded." }),
  stuck.length ? h("ul", { class: "plain obs-stuck" }, stuck.map((r) => h("li", null, chip("critical", "x-circle", harness(r.harness)), " ",
    h("code", null, String(r.session_id).slice(0, 18)), " · ", r.failures.stuck.map((x) => x.tool + " on " + x.file).join("; ")))) :
    h("p", { class: "small" }, chip("good", "check-circle", "None stuck"), " Every determinable failure was recovered."),
  h("p", { class: "small muted" }, sec.basis + ".")];
}

function governanceBody(sec) {
  const per = sec.per_session || {};
  return [h("p", { class: "obs-big" }, h("b", null, pct(sec.contract_engagement_rate)), h("span", null, " of the sessions that touched code read the contract before their first edit ("
    + sec.sessions_contract_first + " of " + sec.sessions_touching_code + ").")),
  h("p", { class: "small" }, "Per session, from their steps: " + per.read_first + " read it first, " + per.edited_without + " edited without it, "
    + per.not_measured + " not measured (no edit, or the steps were cut)."),
  (sec.docs || []).length ? h("p", { class: "small muted" }, "Contract files: " + sec.docs.map((d) => d.file + " (" + plural(d.reads, "read") + ")").join(", ") + ".") : null,
  h("p", { class: "small muted" }, sec.basis + ".")];
}

function stripOf(s) {
  return h("li", { class: "obs-strip-row" }, h("span", { class: "obs-strip-l" }, harness(s.harness), h("small", null, String(s.session_id).slice(0, 14))),
    h("span", { class: "obs-strip", role: "img", "aria-label": s.strip.map((k) => KIND[k][0]).join(", ") },
      s.strip.map((k) => h("span", { class: "obs-step k-" + k, style: { background: KIND[k][1] } }))));
}

function trajectoryBody(sec) {
  const figs = [["Productive", sec.productive], ["Exploratory", sec.exploratory], ["Execution", sec.execution], ["Corrective", sec.corrective]];
  return [h("ul", { class: "obs-figs" }, figs.map(([l, v]) => h("li", null, h("b", null, num(v)), h("span", null, l)))),
    h("p", { class: "small" }, "Corrective share " + pct(sec.corrective_share) + " · median " + num(sec.median_steps_to_first_edit) + " steps to the first edit."),
    (sec.loops || []).length ? h("p", { class: "small muted" }, "Loops: " + sec.loops.map((x) => x.label + " ×" + x.occurrences).join("; ") + ".") : null,
    h("ul", { class: "plain obs-strips", "aria-label": "Session trajectories" }, sec.strips.map(stripOf)),
    legend(Object.values(KIND).map(([label, color]) => ({ label, color })))];
}

function chainBody(sec) {
  return [h("p", { class: "obs-lead" }, sec.valid ? chip("good", "check-circle", "Chain intact") : chip("critical", "x-circle", "Chain broken"),
    " " + num(sec.checked) + " events checked, " + num(sec.reachable) + " reachable" + (sec.breaks ? ", " + plural(sec.breaks, "break") : "") + "."),
  h("p", { class: "small" }, h("b", null, "What it attests: "), (sec.attests || "not said") + ". " + sec.meaning + ".")];
}

// -- mapping, instrumentation and the hub ----------------------------------------------------------------

function mapCard(pid, d, again) {
  const m = d.mapping || {};
  const cur = m.current;
  const list = m.hub_projects || [];
  const pick = h("select", { id: "obs-map", "data-key": "obs:map" }, h("option", { value: "" }, "Choose a hub project"),
    list.map((x) => h("option", { value: x.project_id, selected: (m.suggested && m.suggested.id === x.project_id && !cur) || (cur && cur.hub_project === x.project_id) || null },
      x.project_id + (x.last_harness ? " · " + harness(x.last_harness) : "") + (x.event_count !== undefined ? " · " + num(x.event_count) + " events" : ""))));
  const save = button(cur ? "Map to this one" : "Map the project", { icon: "link", kind: "small primary", key: "obs:map-save", "data-control": "agent_sessions_map",
    onclick: () => act(save.parentNode, async () => {
      if (!needPerson()) return;
      if (!pick.value) { say("Choose a hub project first.", "warning"); return; }
      const how = m.suggested && m.suggested.id === pick.value ? "suggested" : "chosen";
      await api("POST", "/api/projects/" + enc(pid) + "/agent-sessions/map", Object.assign({ hub_project: pick.value, how }, signed()));
      say("Mapped to " + pick.value + ", signed and recorded.", "good");
      await again();
    }) });
  const may = mayAct(d.mappers);
  const mapRow = h("div", { class: "set-row obs-map-row" }, h("label", { for: "obs-map" }, "Hub project"), pick, may ? save : null);
  return card({ title: "Hub project", icon: "link", id: "obs-mapping", cls: "obs-card",
    info: "The hub names a project by its repository: a catalog annotation, the git remote, or the folder's name. Rihmasto suggests the one that matches; a developer or IT confirms it." },
  h("p", null, cur ? ["Mapped to ", h("b", null, cur.hub_project), " by " + cur.by + " (" + cur.how + ")."] : "Not mapped yet."),
  m.suggested && !cur ? h("p", { class: "small" }, "Suggested: ", h("b", null, m.suggested.id), ", matched by " + m.suggested.from + ".") : null,
  (m.candidates || []).length ? h("p", { class: "small muted" }, "This repository's ids: " + m.candidates.map((c) => c.id).join(", ") + ".") : null,
  !list.length ? h("p", { class: "small muted" }, "The hub lists no project yet.") : cur
    ? h("details", { class: "obs-change" }, h("summary", null, "Change the hub project"), mapRow)
    : mapRow,
  may ? null : h("p", { class: "small muted" }, icon("user"), " A developer or IT maps the project."));
}

function instrumentCard(inst) {
  if (!inst || !inst.applies) return null;
  const rows = inst.commands.map((c, i) => h("li", { class: "obs-cmd" }, h("span", { class: "small" }, c.label),
    h("div", { class: "obs-cmd-row" }, h("code", { class: "obs-cmd-t" }, c.command),
      button("Copy", { icon: "copy", kind: "small quiet", key: "obs-copy:" + i, aria: "Copy: " + c.label, onclick: () => copyText(c.command) }))));
  return card({ title: "Instrument the repository", icon: "terminal", id: "obs-instrument", cls: "obs-card",
    info: "The hub's own command writes its hooks into the repository, from your shell. Rihmasto installs nothing and never writes into your repository." },
  h("p", null, inst.instrumented ? [chip("good", "check-circle", "Hooks found"), " for " + inst.harnesses.map(harness).join(", ") + " (" + inst.files.join(", ") + ")."]
    : [chip("nm", "dashed", "No hooks found"), " in " + inst.read_from + "."]),
  h("p", { class: "small muted" }, "Looked at by " + inst.by + ". Run these in the hub's checkout:"), h("ol", { class: "plain obs-cmds" }, rows));
}

function hubChip(hub) {
  if (!hub || !hub.configured) return chip("nm", "dashed", "No hub set");
  if (hub.reachable === false) return chip("warning", "alert", "Hub not answering");
  return chip("good", "check-circle", "Hub answers · " + (hub.where || "local"));
}

// -- the view --------------------------------------------------------------------------------------------

export function viewAgentSessions(p) {
  const pid = p.meta.id;
  const box = h("div", { class: "obs-view" }, h("div", { class: "q" }, h("h2", { id: "view-title", tabindex: "-1" }, "Agent sessions"),
    h("p", null, "What the IDE agents did in this project's repository, read from your agent observability hub.")), h("p", { class: "muted" }, "Reading the hub…"));
  const again = () => draw(box, pid).catch((e) => { if (!(e instanceof AuthError)) fill(box, empty("alert", e.message)); });
  again();
  return box;
}

async function draw(box, pid) {
  const d = await api("GET", "/api/projects/" + enc(pid) + "/agent-sessions?persona=" + enc(S.persona) + (everything() ? "&as_needed=1" : ""));
  if (!box.isConnected) return;
  const again = () => draw(box, pid);
  const head = h("div", { class: "q" }, h("h2", { id: "view-title", tabindex: "-1" }, "Agent sessions"),
    h("p", null, "What the IDE agents (Claude Code, Cursor, OpenCode) did in this project's repository: metadata only, never a prompt, a response or a line of source."));
  if (!d.applies) { fill(box, head, empty("user", "The Agent sessions view is for developers and IT: switch persona in the person menu to see it.")); return; }
  if (!d.module_on) { fill(box, head, empty("layers", "Agent observability is not turned on for this project.", h("a", { class: "btn primary", href: "#/settings" }, icon("settings"), h("span", { class: "lbl" }, "Settings, Modules")))); return; }
  const hub = d.hub || {};
  const sec = d.sections || {};
  const ui = hub.ui || null;
  const snap = button("Record what the hub shows", { icon: "check", kind: "small", key: "obs:snapshot", "data-control": "agent_sessions_snapshot",
    disabled: !mayAct(d.mappers) || !(sec.sessions && sec.sessions.measured) || null,
    onclick: () => act(snap.parentNode, async () => {
      if (!needPerson()) return;
      const out = await api("POST", "/api/projects/" + enc(pid) + "/agent-sessions/snapshot", signed());
      say("Recorded in the project's ledger" + (out.snapshot.new.length ? ": new " + out.snapshot.new.join(", ").replace(/_/g, " ") : "") + ".", "good");
    }) });
  const bar = h("div", { class: "btns obs-bar" }, hubChip(hub), hub.chain_attests ? chip("neutral", "shield", "Chain: " + hub.chain_attests) : null,
    hubLink(ui, "Open the project in the hub", "obs-hub:project"), snap,
    hub.configured ? null : h("a", { class: "btn small", href: "#/settings", "data-key": "obs:settings" }, icon("settings"), h("span", { class: "lbl" }, "Set the hub's address")));
  fill(box, head, bar, hub.error ? h("p", { class: "note warning" }, icon("alert"), h("span", null, hub.error)) : null,
    hub.configured && hub.reachable ? mapCard(pid, d, again) : null,
    h("div", { class: "obs-grid" },
      section("Sessions by harness", "activity", "sessions", sec.sessions, ui, (s) => sessionsBody(s, d.sessions || []),
        "Each session the hub recorded, by the harness that ran it and the day it started."),
      section("Rework hotspots", "refresh", "rework", sec.rework, ui, reworkBody, "The files the IDE agents edited most; reads are not rework."),
      section("Failures and recovery", "alert", "failures", sec.failures, ui, failuresBody,
        "A failure is recovered when the same tool later succeeds on the same file in that session."),
      section("Contract read before edit", "file-check", "governance", sec.governance, ui, governanceBody,
        "Governance coherence: sessions that read the project's contract or AGENTS.md before they edited code."),
      section("Session trajectories", "timeline", "trajectory", sec.trajectory, ui, trajectoryBody,
        "How the sessions moved: reading, editing, running, failing. The hub classifies the steps; the strips show the most recent ones."),
      section("The hub's hash chain", "shield", "chain", sec.chain, ui, chainBody,
        "Whether the hub's ledger still hashes to what it claimed, and what that verdict attests.")),
    instrumentCard(d.instrumentation));
  if (nav.refreshShell) nav.refreshShell();
}

// -- Settings: the hub's address (IT) ---------------------------------------------------------------------

export function agentObsSettingsCard() {
  const holder = h("div", { class: "obs-settings-holder" });
  api("GET", "/api/agent-observability").then((s) => { if (s.on_anywhere) fill(holder, settingsCard(s, holder)); })
    .catch((e) => { if (!(e instanceof AuthError)) fill(holder); });
  return holder;
}

function settingsCard(s, holder) {
  const cur = s.settings || {};
  const url = h("input", { id: "obs-url", value: cur.url || "", placeholder: s.default_url, autocomplete: "off", spellcheck: "false", "data-key": "obs:url" });
  const tokenEnv = h("input", { id: "obs-token", value: cur.token_env || "", placeholder: "COCKPIT_HUB_TOKEN (only if your hub needs one)", autocomplete: "off", spellcheck: "false", "data-key": "obs:token" });
  const priv = h("input", { type: "checkbox", id: "obs-private", checked: !!cur.private, "data-key": "obs:private" });
  const hosted = h("input", { type: "checkbox", id: "obs-hosted", checked: !!cur.hosted_consent, "data-key": "obs:hosted" });
  const may = mayAct(s.setters);
  const status = h("p", { class: "small", role: "status", "aria-live": "polite" });
  const save = button("Save the hub's address", { icon: "check", kind: "small primary", key: "obs:save", "data-control": "agent_observability_settings", disabled: !may || null,
    onclick: () => act(save.parentNode, async () => {
      if (!needPerson()) return;
      const out = await api("PUT", "/api/agent-observability", Object.assign({ url: url.value.trim(), token_env: tokenEnv.value.trim(), private: priv.checked, hosted: hosted.checked }, signed()));
      say(out.settings.url ? "The hub is set: " + out.settings.url + " (" + out.settings.where + "), signed and recorded." : "The hub's address is removed.", "good");
      fill(holder, settingsCard(out, holder));
    }) });
  const test = button("Does it answer?", { icon: "pulse", kind: "small quiet", key: "obs:test", onclick: () => act(test.parentNode, async () => {
    const out = await api("GET", "/api/agent-observability?check=1");
    fill(status, out.hub ? (out.hub.reachable ? [chip("good", "check-circle", "Answers"), " chain: " + (out.hub.chain_attests || "not said")] : [chip("warning", "alert", "No answer"), " " + out.hub.error]) : "Save an address first.");
  }) });
  return card({ title: "Agent observability", icon: "bot", id: "obs-settings", cls: "obs-card",
    info: "The address of your agent observability hub, the one your IDE agents' hooks report to. A loopback or private address is read at once; a hosted one only with your explicit consent. A token is named by its environment variable, never typed here." },
  h("p", { class: "small" }, cur.url ? "Reading " + cur.url + " (" + cur.where + "), set by " + cur.set_by + "." : "No address yet. The hub serves " + s.default_url + " by default."),
  h("div", { class: "field" }, h("label", { for: "obs-url" }, "Hub address"), url),
  h("div", { class: "field" }, h("label", { for: "obs-token" }, "Token's environment variable"), tokenEnv),
  h("div", { class: "set-row" }, h("label", { class: "chk-l", for: "obs-private" }, priv, " It is on our own network")),
  h("div", { class: "set-row" }, h("label", { class: "chk-l", for: "obs-hosted" }, hosted, " I consent to a hosted hub (https): its records leave our network")),
  h("div", { class: "btns" }, save, test, may ? null : h("span", { class: "muted small" }, icon("user"), " IT sets the hub's address.")), status);
}

// -- the AI tools card, and Ask Rihma's proposals ---------------------------------------------------------

export async function enableAgentObs(pid) {
  const m = await api("GET", "/api/modules");
  const cur = ((m.projects && m.projects[pid]) || m.factory).modules;
  if (cur.includes("agentobs")) return null;
  const out = await api("PUT", "/api/projects/" + enc(pid) + "/modules", Object.assign({ modules: cur.concat(["agentobs"]), reason: "turn on Agent observability" }, signed()));
  S.modules = out.view;
  if (nav.refreshShell) nav.refreshShell();
  return out;
}

export function obsToolsGroup(pid, obs) {
  if (!obs || !(obs.instrumentation.instrumented || obs.on || obs.suggest)) return null;
  const inst = obs.instrumentation;
  const offer = obs.suggest ? button("Turn on Agent sessions", { icon: "plus", kind: "small", key: "obs:enable", "data-control": "agent_sessions_enable",
    onclick: () => act(offer.parentNode, async () => {
      if (!needPerson()) return;
      await enableAgentObs(pid);
      say("Agent observability is on for this project, signed and recorded.", "good");
      if (nav.rerender) await nav.rerender();
    }) }) : null;
  return h("div", { class: "ait-group", "data-control": "agent_observability_hooks" }, h("h4", null, icon("activity"), "Agent observability hub"),
    h("p", { class: "small" }, inst.instrumented ? "Its hooks are in the repository for " + inst.harnesses.map(harness).join(", ") + ": " + inst.files.join(", ") + "."
      : "No hooks of the agent observability hub in the repository."),
    obs.suggest ? h("p", { class: "small muted" }, "Agent sessions would show what the IDE agents do here: " + obs.why + ".") : null,
    obs.on ? h("a", { href: "#/p/" + enc(pid) + "/agent_sessions", class: "small" }, "Open Agent sessions") : offer);
}

export const OBS_WORDS = { agentobs_enable: ["Turn on Agent observability", "activity"], agentobs_map: ["Map to the hub's project", "link"] };
export const OBS_DESCRIBE = {
  agentobs_enable: (a) => ["For project " + a.project + ": the Agent sessions view for developers and IT"],
  agentobs_map: (a) => ["Project " + a.project + " to hub project " + a.hub_project],
};
export function obsCalls(a, pid) {
  return {
    agentobs_enable: () => enableAgentObs(a.project || pid),
    agentobs_map: () => api("POST", "/api/projects/" + enc(a.project || pid) + "/agent-sessions/map", Object.assign({ hub_project: a.hub_project, how: "suggested" }, signed())),
  };
}
