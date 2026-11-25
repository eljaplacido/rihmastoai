/* The agent channel (FR-CHN1): people, Rihma's agents and the coding agents working on a project, in one
   threaded conversation a person watches and steps into. The Agents strip on a project's overview, the
   Agent channel view (and the same channel as a panel beside any view), and the factory-wide Agent
   activity monitor. Every post and every confirm is signed with the person chip's name and persona; an
   agent's proposed answer is answered only when a person confirms it here. */

import {
  S, $, h, fill, icon, chip, button, api, enc, link, say, act, needPerson, signed, empty, fmtAt, pageHead, card,
  personaLabel,
} from "./core.js";

const POLL_MS = 3000;
const KIND_TONE = { question: "accent", answer: "good", progress: "info", feedback: "warning", plan: "neutral",
  handoff: "accent", gate_result: "neutral", check_result: "neutral", proposal: "warning", note: "neutral" };
const AUTHOR_ICON = { person: "user", rihma: "sparkles", agent: "bot", automation: "refresh", system: "gate" };
const F = { agent: "", kind: "" };      // the filters, kept while the page is open

function whoLabel(a) {
  if (a.kind === "agent") return a.name + " for " + a.operator;
  if (a.kind === "rihma") return "Rihma (" + a.role + ")";
  if (a.kind === "automation") return a.name + " for " + a.operator;
  return a.name;
}
export function authorBadge(a) {
  const sub = a.kind === "agent" ? (a.harness || "agent") : a.kind === "person" ? personaLabel(a.persona)
    : a.kind === "rihma" ? "Rihma agent" : a.kind;
  return h("span", { class: "ab ab-" + a.kind }, icon(AUTHOR_ICON[a.kind] || "info"),
    h("b", null, whoLabel(a)), h("span", { class: "ab-sub muted" }, sub));
}
function kindChip(m) {
  const word = m.kind.replace("_", " ") + (m.state ? ": " + m.state : "");
  return chip(KIND_TONE[m.kind] || "neutral", null, word, { "data-kind": m.kind });
}
function refChips(refs) {
  const out = [];
  Object.entries(refs || {}).forEach(([k, v]) => (Array.isArray(v) ? v : [v]).slice(0, 6).forEach((x) =>
    out.push(h("span", { class: "ref mono small", title: k }, k === "message" ? "re " + x : x))));
  return out.length ? h("div", { class: "ch-refs" }, out) : null;
}

// -- the trace drawer: what a message rests on ---------------------------------------------------------

function traceRows(m) {
  const t = m.trace || {};
  const rows = [];
  if (m.author.kind === "agent") {
    const r = m.refs || {};
    rows.push(["agent", m.author.name], ["harness", m.author.harness], ["operator", m.author.operator + " (" + personaLabel(m.author.persona) + ")"],
      ["commits", (r.commits || []).join(", ")], ["files", (r.files || []).join(", ")], ["criteria", (r.criteria || []).join(", ")]);
  }
  if (t.basis === "model") {
    rows.push(["answered by", "a model, through Gnomon"], ["role", t.role], ["model", t.model], ["tokens", t.tokens],
      ["tool calls", t.tool_calls], ["run", t.run], ["took", t.duration_ms != null ? t.duration_ms + " ms" : null]);
  } else if (t.basis === "rule") {
    rows.push(["answered by", "the records, by rule"], ["rests on", t.rests_on], ["sources", (t.sources || []).join(", ")]);
  } else if (t.basis === "gate" || t.basis === "check") {
    rows.push(["result of", t.basis], ["task", t.task], ["round", t.round], ["head", t.head], ["check", t.check], ["verdict", t.verdict],
      ["signals", (t.signals || []).map((s) => s.name + ": " + s.verdict).join("; ")],
      ["objections", (t.objections || []).join(" | ")], ["refused", t.refused]);
  } else if (t.basis === "none") {
    rows.push(["answered by", "nothing: no rule matched and no model is set up for Rihma's agents"]);
  }
  rows.push(["posted", fmtAt(m.at)], ["thread", m.thread]);
  return rows.filter(([, v]) => v !== null && v !== undefined && v !== "");
}
function traceDrawer(m) {
  return h("dl", { class: "kv ch-trace" }, traceRows(m).map(([k, v]) => h("div", null, h("dt", null, k), h("dd", null, String(v)))));
}

// -- one message -------------------------------------------------------------------------------------

function settleButtons(pid, m, refresh) {
  if (m.kind !== "proposal" || m.state !== "open") return null;
  const box = h("div", { class: "btns", "data-control": "channel_settle" });
  const go = (verdict) => act(box, async () => {
    if (!needPerson()) return;
    await api("POST", "/api/projects/" + enc(pid) + "/channel/" + m.id + "/settle", Object.assign({ verdict }, signed()));
    say(verdict === "confirm" ? "Confirmed: the question is answered, signed by " + S.person.trim() + "." : "Rejected: the question stays open.", "good");
    refresh();
  });
  box.append(button("Confirm the answer", { icon: "check", kind: "small primary", key: "ch-confirm:" + m.id, onclick: () => go("confirm") }),
    button("Reject", { icon: "x", kind: "small quiet", key: "ch-reject:" + m.id, onclick: () => go("reject") }));
  return box;
}
function messageEl(pid, m, refresh, opened) {
  const open = opened.has(m.id);
  const drawer = h("div", { class: "ch-drawer", hidden: !open }, traceDrawer(m));
  const tr = button("Trace", { icon: "layers", kind: "small quiet", key: "ch-trace:" + m.id, "data-control": "channel_trace", expanded: String(open) });
  tr.addEventListener("click", () => {
    drawer.hidden = !drawer.hidden;
    tr.setAttribute("aria-expanded", String(!drawer.hidden));
    if (drawer.hidden) opened.delete(m.id); else opened.add(m.id);   // a new message keeps the drawers open
  });
  return h("article", { class: "ch-msg ch-" + m.author.kind + (m.held ? " held" : ""), "data-id": m.id },
    h("div", { class: "ch-top" }, authorBadge(m.author), kindChip(m), m.held ? chip("warning", "pause", "waiting: paused") : null,
      h("span", { class: "muted small ch-at" }, m.id + " · " + fmtAt(m.at))),
    h("p", { class: "ch-text" }, m.text), refChips(m.refs), settleButtons(pid, m, refresh),
    h("div", { class: "ch-foot" }, tr), drawer);
}

// -- the channel: a view, and the same as a panel beside any view -------------------------------------

export function channelPanel(pid, opts) {
  const o = opts || {};
  const log = h("div", { class: "ch-log", id: o.compact ? "chp-log" : "ch-log", role: "log", "aria-live": "polite", "aria-label": "Agent channel messages" });
  const agentSel = h("select", { id: o.compact ? "chp-agent" : "ch-agent", "aria-label": "Filter by agent" }, h("option", { value: "" }, "Every author"));
  const kindSel = h("select", { id: o.compact ? "chp-kind" : "ch-kind", "aria-label": "Filter by kind" }, h("option", { value: "" }, "Every kind"));
  const pauseBox = h("span", { class: "ch-pause" });
  const text = h("textarea", { id: o.compact ? "chp-text" : "ch-text", rows: "2", maxlength: "8000", "aria-label": "Your message",
    placeholder: "Write to the agents; @analyst or @verifier asks Rihma" });
  const send = button("Send", { icon: "send", kind: "small primary", key: o.compact ? "chp-send" : "ch-send", "data-control": "channel_post" });
  let data = { messages: [], paused: null, kinds: [] };
  let timer = null;
  let seen = null;                       // what was drawn last: the log is drawn again only when it changed
  const opened = new Set();
  const draw = () => {
    const keepAtEnd = log.scrollHeight - log.scrollTop - log.clientHeight < 12;
    const authors = Array.from(new Set(data.messages.map((m) => m.author.name)));
    if (agentSel.options.length !== authors.length + 1) {
      fill(agentSel, h("option", { value: "" }, "Every author"), authors.map((a) => h("option", { value: a }, a)));
      agentSel.value = authors.includes(F.agent) ? F.agent : "";
    }
    if (kindSel.options.length === 1) data.kinds.forEach((k) => kindSel.append(h("option", { value: k }, k.replace("_", " "))));
    kindSel.value = F.kind;
    const shown = data.messages.filter((m) => (!F.agent || m.author.name === F.agent) && (!F.kind || m.kind === F.kind));
    fill(log, shown.length ? shown.map((m) => messageEl(pid, m, load, opened))
      : empty("message-square", data.messages.length ? "Nothing matches the filters." : "No message yet. A coding agent posts here over MCP (rihma_progress, rihma_ask_rihma), and so can you."));
    fill(pauseBox, data.paused
      ? [chip("warning", "pause", "Paused by " + data.paused.person), button("Resume", { icon: "play", kind: "small", key: "ch-resume", "data-control": "channel_pause", onclick: () => pause(false) })]
      : button("Pause the channel", { icon: "pause", kind: "small quiet", key: "ch-pause", "data-control": "channel_pause", onclick: () => pause(true) }));
    if (keepAtEnd) log.scrollTop = log.scrollHeight;
  };
  async function load() {
    try { data = await api("GET", "/api/projects/" + enc(pid) + "/channel"); } catch (e) { return; }
    const sig = JSON.stringify([data.messages, data.paused]);
    if (sig !== seen && (log.isConnected || !timer)) { seen = sig; draw(); }
  }
  async function pause(on) {
    if (!needPerson()) return;
    await act(pauseBox, async () => {
      await api("POST", "/api/projects/" + enc(pid) + "/channel/" + (on ? "pause" : "resume"), Object.assign({ reason: "" }, signed()));
      say(on ? "Paused: agents' posts wait until you resume." : "Resumed: what waited is let through.", "good");
      await load();
    });
  }
  send.addEventListener("click", () => act(send.parentElement, async () => {
    if (!text.value.trim() || !needPerson()) return;
    await api("POST", "/api/projects/" + enc(pid) + "/channel", Object.assign({ text: text.value.trim() }, signed()));
    text.value = "";
    await load();
  }));
  agentSel.addEventListener("change", () => { F.agent = agentSel.value; draw(); });
  kindSel.addEventListener("change", () => { F.kind = kindSel.value; draw(); });
  const poll = () => {
    if (!log.isConnected && timer) return;          // the page moved on: the polling ends with it
    load().finally(() => { timer = setTimeout(poll, POLL_MS); });
  };
  timer = setTimeout(poll, 0);
  return h("div", { class: "ch-panel" + (o.compact ? " compact" : "") },
    h("div", { class: "ch-tools" }, agentSel, kindSel, pauseBox),
    log, h("div", { class: "ch-compose" }, text, send));
}

export function viewAgents(p) {
  const pid = p.meta.id;
  return h("div", { class: "ch-view" },
    h("div", { class: "q" }, h("h2", { id: "view-title", tabindex: "-1" }, "Agent channel"),
      h("p", null, "Who is working on this project with an agent, what they said, and what waits on a person.")),
    channelPanel(pid));
}

// The same channel beside whatever view is open, from the project's header.
export function channelPanelButton(p) {
  const pid = p.meta.id;
  return button("Agent channel", { icon: "message-square", kind: "small", key: "channel-panel", "data-control": "channel_panel",
    onclick: () => {
      let aside = $("#agent-aside");
      if (aside) { aside.remove(); return; }
      aside = h("aside", { id: "agent-aside", class: "agent-aside", "aria-label": "Agent channel beside the view" },
        h("div", { class: "aa-head" }, h("b", null, "Agent channel"),
          button("Close", { icon: "x", kind: "small quiet", key: "agent-aside-close", onclick: () => aside.remove() })),
        channelPanel(pid, { compact: true }));
      document.body.append(aside);
    } });
}

// -- the Agents strip on the overview ------------------------------------------------------------------

export function agentsStrip(p) {
  const pid = p.meta.id;
  const body = h("div", { class: "as-body" }, h("p", { class: "muted small" }, "Reading what agents did here…"));
  const box = h("section", { class: "section panel agents-strip", "data-control": "agents_strip", "aria-labelledby": "agents-h" },
    h("div", { class: "next-top" }, h("h3", { id: "agents-h", class: "label-h" }, icon("bot"), " Agents working on this"),
      h("a", { href: link(pid, "agents"), class: "small", "data-key": "agents-open" }, "Open the agent channel")), body);
  api("GET", "/api/projects/" + enc(pid) + "/agents").then((a) => {
    if (!a.items.length) {
      fill(body, h("p", { class: "muted small" }, "No agent has worked on this yet. Hand it off to a coding agent, or connect one over MCP: what it does shows here."));
      return;
    }
    fill(body, h("div", { class: "chips" },
      a.agents.map((n) => chip("info", "bot", n)),
      chip("neutral", "send", a.handoffs + " hand-off" + (a.handoffs === 1 ? "" : "s")),
      chip("neutral", "gate", a.gates + " gate result" + (a.gates === 1 ? "" : "s")),
      a.proposals_waiting.length ? chip("warning", "user", a.proposals_waiting.length + " proposal(s) wait on a person") : null,
      a.paused ? chip("warning", "pause", "Channel paused") : null),
    h("ul", { class: "plain as-list" }, a.items.slice(0, 5).map((it) => h("li", null,
      h("span", { class: "ab ab-" + it.author_kind }, icon(AUTHOR_ICON[it.author_kind] || "info"), h("b", null, it.who)),
      " ", chip(KIND_TONE[it.kind] || "neutral", null, it.kind.replace("_", " ")), " ",
      h("span", { class: "small" }, it.text), h("span", { class: "muted small" }, " · " + fmtAt(it.at))))));
  }).catch(() => fill(body, h("p", { class: "muted small" }, "What agents did here could not be read.")));
  return box;
}

// -- Agent activity: every live channel across the factory ---------------------------------------------

export async function renderAgentActivity(seq) {
  const main = $("#main");
  let data;
  try { data = await api("GET", "/api/agents"); } catch (e) { fill(main, empty("alert", e.message)); return; }
  if (seq !== S.seq) return;
  document.title = "Agent activity · Rihmasto.ai";
  const rows = data.channels.map((c) => h("li", { class: "aa-row", "data-id": c.project },
    h("div", { class: "aa-t" }, h("a", { href: link(c.project, "agents"), "data-key": "aa-open:" + c.project }, c.title || c.project),
      c.paused ? chip("warning", "pause", "Paused") : null,
      c.proposals_waiting.length ? chip("warning", "user", c.proposals_waiting.length + " waiting on a person") : null,
      c.held ? chip("warning", "clock", c.held + " held") : null),
    h("p", { class: "small" }, h("b", null, c.last.who + ": "), c.last.text),
    h("p", { class: "muted small" }, "Talking: " + (c.talking.join(", ") || "nobody yet") + " · " + c.messages + " message(s) · last " + fmtAt(c.last.at))));
  fill(main, pageHead("Agent activity", "Every project's agent channel: who is talking, the last message, and any proposal waiting on a person.",
    { icon: "bot", actions: [button("Refresh", { icon: "refresh", kind: "quiet", key: "aa-refresh", onclick: () => renderAgentActivity(S.seq) })] }),
  card({ title: "Live channels", icon: "message-square", id: "aa-list" },
    rows.length ? h("ul", { class: "plain aa-list", "data-control": "agent_activity" }, rows)
      : h("div", { "data-control": "agent_activity" }, empty("bot", "No agent has posted in any project yet. Hand a project off to a coding agent to start."))));
}
