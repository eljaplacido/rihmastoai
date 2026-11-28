/* Asks between agents and machines, the machines, and Test connection (FR-XAG1, FR-RCH1; kernel/asks.py,
   kernel/machines.py, kernel/reach.py). The back-and-forth a person used to carry by copy and paste between agents on
   different computers happens here: put a question to a named agent (on a named machine), copy it for the other agent
   or give it a reply link, paste the answer back, and see it answered in the agent channel. Where something is not
   reachable, Test connection says why, how to fix it, and drafts the ask to the agent there; nothing is sent without
   the person's Confirm. */

import { h, icon, api, enc, button, act, fill, card, chip, say, signed, needPerson, PROPOSALS } from "./core.js";
import { datum, scopeWord, emptyState } from "./words.js";

const TONE = { open: "info", delivered: "info", answered: "good", expired: "neutral", withdrawn: "neutral" };
const STATE_WORD = { open: "waiting", delivered: "delivered", answered: "answered", expired: "expired", withdrawn: "withdrawn" };

async function copyOut(text, what) {
  try { await navigator.clipboard.writeText(text); say(what + " copied: paste it to the other agent.", "good"); }
  catch (e) { say("Copy it by hand from the box.", "warning"); }
}

function field(id, label, el) {
  return h("label", { class: "ak-field", for: id }, h("span", { class: "small" }, label), el);
}

// -- one ask --------------------------------------------------------------------------------------------------

function askRow(pid, a, again) {
  const open = a.state === "open" || a.state === "delivered";
  const out = h("div", { class: "ak-out", role: "status", "aria-live": "polite" });
  let stateChip = chip(TONE[a.state] || "neutral", null, STATE_WORD[a.state] || a.state);
  const paste = h("textarea", { id: "ak-paste-" + a.id, rows: "3", maxlength: "8000", class: "ak-paste", "aria-label": "The answer that came back for " + a.id });
  const tools = open ? h("div", { class: "btns" },
    button("Copy for the other agent", { icon: "copy", kind: "small", key: "ak-copy:" + a.id, "data-control": "ask_copy",
      onclick: () => act(tools, async () => {
        if (!needPerson()) return;
        const r = await api("POST", "/api/projects/" + enc(pid) + "/asks/" + enc(a.id) + "/copy", signed());
        fill(out, h("pre", { class: "ak-text", "data-ud": "" }, r.text));
        const now = chip(TONE.delivered, null, STATE_WORD.delivered);   // delivered by copy, shown in place
        stateChip.replaceWith(now);
        stateChip = now;
        await copyOut(r.text, a.id);
      }) }),
    button("Reply link", { icon: "link", kind: "small quiet", key: "ak-link:" + a.id, "data-control": "ask_link",
      onclick: () => act(tools, async () => {
        if (!needPerson()) return;
        const r = await api("POST", "/api/projects/" + enc(pid) + "/asks/" + enc(a.id) + "/link", signed());
        fill(out, h("p", { class: "small" }, datum(r.said)), h("pre", { class: "ak-text", "data-ud": "" }, r.how));
        await copyOut(r.how, "The reply link");
      }) }),
    button("Withdraw", { icon: "x", kind: "small quiet", key: "ak-withdraw:" + a.id, "data-control": "ask_withdraw",
      onclick: () => act(tools, async () => {
        if (!needPerson()) return;
        await api("POST", "/api/projects/" + enc(pid) + "/asks/" + enc(a.id) + "/withdraw", signed());
        say(a.id + " withdrawn.", "good");
        again();
      }) })) : null;
  const pasteBox = open ? h("div", { class: "ak-answer" }, field("ak-paste-" + a.id, "Paste the answer that came back", paste),
    button("File the answer", { icon: "check", kind: "small primary", key: "ak-answer:" + a.id, "data-control": "ask_answer",
      onclick: () => act(pasteBox, async () => {
        if (!paste.value.trim() || !needPerson()) return;
        await api("POST", "/api/projects/" + enc(pid) + "/asks/" + enc(a.id) + "/answer", Object.assign({ text: paste.value.trim() }, signed()));
        say(a.id + " answered: it is in the agent channel.", "good");
        again();
      }) })) : null;
  return h("li", { class: "ak-row", "data-key": "ask:" + a.id },
    h("div", { class: "ak-head" }, h("code", null, a.id), " ", stateChip,
      " ", h("span", { class: "small" }, "to ", h("strong", { "data-ud": "" }, a.to), a.machine ? [" on ", h("strong", { "data-ud": "" }, a.machine)] : null),
      h("span", { class: "small muted" }, " · " + (a.by || "") + ", " + String(a.at || "").slice(0, 16).replace("T", " "))),
    h("p", { class: "ak-q" }, datum(a.text)),
    a.why ? h("p", { class: "small muted" }, "Why: ", datum(a.why)) : null,
    a.answer ? h("blockquote", { class: "ak-a" }, h("span", { class: "small muted" }, "Answer (" + a.answer.via + "): "), datum(a.answer.text)) : null,
    tools, pasteBox, out);
}

// -- the project's asks, on the agent channel's view --------------------------------------------------------------

function newAskForm(pid, machines, again) {
  const to = h("input", { id: "ak-to", maxlength: "41", autocomplete: "off", placeholder: "claude-code", "aria-label": "The agent asked" });
  const where = h("select", { id: "ak-machine", "aria-label": "On which machine" }, h("option", { value: "" }, "this machine"),
    machines.map((m) => h("option", { value: m }, m)));
  const text = h("textarea", { id: "ak-text", rows: "3", maxlength: "4000", "aria-label": "What to ask", placeholder: "What the agent should do or answer" });
  const why = h("input", { id: "ak-why", maxlength: "300", autocomplete: "off", "aria-label": "Why it is asked" });
  const form = h("div", { class: "ak-new" },
    h("div", { class: "ak-fields" }, field("ak-to", "To the agent", to), field("ak-machine", "On", where), field("ak-why", "Why (optional)", why)),
    field("ak-text", "The ask", text),
    button("Put the ask", { icon: "send", kind: "small primary", key: "ak-put", "data-control": "ask_put",
      onclick: () => act(form, async () => {
        if (!to.value.trim() || !text.value.trim() || !needPerson()) return;
        const r = await api("POST", "/api/projects/" + enc(pid) + "/asks", Object.assign({ to: to.value.trim(), machine: where.value, text: text.value.trim(),
          why: why.value.trim() }, signed()));
        say(r.said, "good");
        text.value = "";
        again();
      }) }));
  return form;
}

export function asksPanel(pid) {
  const holder = h("section", { class: "card ak-card", "aria-labelledby": "ak-h", "data-control": "asks_list" });
  const again = () => api("GET", "/api/projects/" + enc(pid) + "/asks").then((d) => fill(holder,
    h("header", { class: "card-head" }, h("span", { class: "card-ic" }, icon("bot")), h("h3", { class: "card-t", id: "ak-h" }, "Asks to agents"),
      h("span", { class: "small muted" }, " to agents here or on your other machines; each answer comes back into this channel")),
    d.asks.length ? h("ul", { class: "plain ak-list" }, d.asks.map((a) => askRow(pid, a, again)))
      : emptyState("asks", null, { icon: "bot" }),
    newAskForm(pid, d.machines || [], again))).catch((e) => fill(holder, h("p", { class: "small muted" }, "Asks could not be read: " + e.message)));
  again();
  return holder;
}

// -- Home: what waits on other agents ---------------------------------------------------------------------------------

export function homeAsksCard(el) {
  if (!el) return;
  api("GET", "/api/asks").then((d) => {
    if (!d.asks.length) { fill(el); return; }
    fill(el, card({ title: "Waiting on other agents", icon: "clock", id: "home-asks" },
      h("div", { "data-control": "asks_waiting" }, h("p", { class: "small" }, datum(d.said)),
        h("ul", { class: "plain ak-list" }, d.asks.slice(0, 6).map((a) => h("li", null,
          h("a", { href: "#/p/" + enc(a.project) + "/agents", "data-key": "home-ask:" + a.id }, h("code", null, a.id)), " ",
          chip(TONE[a.state], null, STATE_WORD[a.state]), " ", h("span", { "data-ud": "" }, a.title + ": " + a.to + (a.machine ? " on " + a.machine : ""))))))));
  }).catch(() => fill(el));
}

// -- the doctor's result ---------------------------------------------------------------------------------------------

export function reachResult(r, projects, box) {
  const draft = r.draft;
  const pick = draft && projects && projects.length ? h("select", { id: "rc-project", "aria-label": "The project the ask is about" },
    projects.map((p) => h("option", { value: p.id }, p.title || p.id))) : null;
  const canSend = !!(pick || (draft && draft.project));
  const send = draft ? (canSend ? button("Send to the agent on " + draft.machine, { icon: "send", kind: "small primary", key: "rc-send", "data-control": "ask_put",
    onclick: () => act(box, async () => {
      const pid = pick ? pick.value : (draft.project || "");
      if (!pid || !needPerson()) return;
      const out = await api("POST", "/api/projects/" + enc(pid) + "/asks", Object.assign({ to: draft.to, machine: draft.machine, text: draft.text,
        why: draft.why, expects: draft.expects, source: draft.source }, signed()));
      say(out.said, "good");
    }) }) : h("p", { class: "small muted" }, "Create or adopt a project first to send this ask, or copy the steps above for the agent there.")) : null;
  return h("div", { class: "rc-result", "data-key": "reach:" + r.target },
    h("p", null, chip(r.ok ? "good" : "warning", r.ok ? "check" : "alert", r.ok ? "reachable" : "not reachable"), " ", datum(r.said)),
    r.fix && r.fix.length ? h("ol", { class: "rc-fix small" }, r.fix.map((s) => h("li", { "data-ud": "" }, s))) : null,
    draft ? h("div", { class: "rc-draft" }, h("p", { class: "small" }, "Ask the agent on " + draft.machine + " to do it:"),
      h("pre", { class: "ak-text", "data-ud": "" }, draft.text), pick ? field("rc-project", "About the project", pick) : null, send) : null);
}

export function reachButton(target, projects, label) {
  const box = h("div", { class: "rc-box" });
  const b = button(label || "Test connection", { icon: "plug", kind: "small", key: "reach:" + target, "data-control": "reach_test",
    onclick: () => act(box, async () => {
      const r = await api("POST", "/api/reach", { target });
      fill(out, reachResult(r, projects, out));
    }) });
  const out = h("div", { class: "rc-out", role: "status", "aria-live": "polite" });
  fill(box, b, out);
  return box;
}

// -- Settings: the machines ------------------------------------------------------------------------------------------

function machineRow(m, projects, again) {
  return h("li", { class: "mc-row", "data-key": "machine:" + m.name },
    h("div", { class: "mc-head" }, h("strong", { "data-ud": "" }, m.name), " ", chip("neutral", null, m.reach + (m.address ? " " + m.address : "")),
      " ", h("span", { class: "small muted" }, (m.os || "unknown") + (m.agents && m.agents.length ? " · agents " + m.agents.join(", ") : ""))),
    h("div", { class: "btns" }, reachButton(m.name, projects),
      button("Remove", { icon: "x", kind: "small quiet", key: "mc-remove:" + m.name, "data-control": "machine_remove",
        onclick: (e) => act(e.currentTarget.parentElement, async () => {
          if (!needPerson()) return;
          await api("POST", "/api/machines/remove", Object.assign({ name: m.name }, signed()));
          say("Machine " + m.name + " removed.", "good");
          again();
        }) })));
}

function addForm(again) {
  const name = h("input", { id: "mc-name", maxlength: "41", autocomplete: "off", placeholder: "laptop", "aria-label": "Machine name" });
  const reach = h("select", { id: "mc-reach", "aria-label": "How it is reached" }, ["ssh", "https", "hand"].map((r) => h("option", { value: r }, r === "hand" ? "by hand" : r)));
  const address = h("input", { id: "mc-address", maxlength: "200", autocomplete: "off", placeholder: "an ssh alias, user@host or https://…", "aria-label": "Address" });
  const os = h("select", { id: "mc-os", "aria-label": "Its system" }, ["unknown", "windows", "linux", "macos"].map((s) => h("option", { value: s }, s)));
  const agents = h("input", { id: "mc-agents", maxlength: "200", autocomplete: "off", placeholder: "claude-code, codex", "aria-label": "Agents there" });
  const form = h("div", { class: "mc-new" },
    h("div", { class: "ak-fields" }, field("mc-name", "Name", name), field("mc-reach", "Reached by", reach), field("mc-address", "Address", address),
      field("mc-os", "System", os), field("mc-agents", "Agents there", agents)),
    button("Add the machine", { icon: "plus", kind: "small primary", key: "mc-add", "data-control": "machine_add",
      onclick: () => act(form, async () => {
        if (!name.value.trim() || !needPerson()) return;
        const r = await api("POST", "/api/machines", Object.assign({ name: name.value.trim(), reach: reach.value, address: address.value.trim(),
          os: os.value, agents: agents.value }, signed()));
        say(r.said, "good");
        name.value = ""; address.value = ""; agents.value = "";
        again();
      }) }));
  return form;
}

export function machinesSettingsCard(projects) {
  const list = (projects || []).filter((p) => !p.factory).map((p) => ({ id: p.id, title: p.title }));
  const holder = h("div", { class: "mc-holder", "data-control": "machines_page" });
  const again = () => api("GET", "/api/machines").then((d) => fill(holder, card({ title: "Machines", icon: "server", id: "set-machines",
    tools: [chip("neutral", "globe", scopeWord(d.scope))],
    info: "The computers your agents and working copies are on, and how each is reached. Test connection says why one is not reachable and how to fix it, "
      + "and drafts the ask to the agent there. Asks to agents on another machine are carried from here: by its agent over MCP, a reply link, or copy and paste." },
  h("p", { class: "small" }, datum(d.said)),
  d.machines.length ? h("ul", { class: "plain mc-list" }, d.machines.map((m) => machineRow(m, list, again))) : null,
  h("div", { class: "btns" }, reachButton("github", list, "Test GitHub")),
  addForm(again)))).catch((e) => fill(holder, h("p", { class: "small muted" }, "Machines could not be read: " + e.message)));
  again();
  return holder;
}

// -- Ask Rihma's proposals: the same signed routes a click calls ---------------------------------------------------

Object.assign(PROPOSALS, {
  ask_put: { words: ["Put the ask", "send"],
    describe: (a) => ["Ask " + a.to + (a.machine ? " on " + a.machine : "") + ": " + a.text],
    call: (a, pid) => api("POST", "/api/projects/" + enc(pid || a.project) + "/asks", Object.assign({ to: a.to, machine: a.machine || "", text: a.text,
      why: a.why || "", expects: a.expects || "", source: a.source || null }, signed())) },
  ask_answer: { words: ["File the answer", "check"],
    describe: (a) => ["File as the answer to " + a.aid + ": " + a.text],
    call: (a, pid) => api("POST", "/api/projects/" + enc(pid || a.project) + "/asks/" + enc(a.aid) + "/answer", Object.assign({ text: a.text }, signed())) },
  ask_withdraw: { words: ["Withdraw the ask", "x"],
    describe: (a) => ["Withdraw " + a.aid],
    call: (a, pid) => api("POST", "/api/projects/" + enc(pid || a.project) + "/asks/" + enc(a.aid) + "/withdraw", signed()) },
  machine_add: { words: ["Add the machine", "server"],
    describe: (a) => ["Add the machine " + a.name + " (" + (a.reach || "hand") + (a.address ? " " + a.address : "") + ")"],
    call: (a) => api("POST", "/api/machines", Object.assign({ name: a.name, reach: a.reach || "hand", address: a.address || "", os: a.os || "unknown" }, signed())) },
  machine_remove: { words: ["Remove the machine", "x"],
    describe: (a) => ["Remove the machine " + a.name],
    call: (a) => api("POST", "/api/machines/remove", Object.assign({ name: a.name }, signed())) },
});
