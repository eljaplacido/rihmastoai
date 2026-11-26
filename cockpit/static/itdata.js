/* Integrations and data, IT's view (kernel/itdata*.py, FR-ITD1). The owner: "from IT perspective, you would want to
   view for integrations and the data side of things as well".

   A project's view (#/p/<pid>/itdata, the Run capsule): its data flow as a diagram whose nodes open each connection,
   every connection with where it is, its health, access, data classes and credentials by name, what each agent may
   reach, and its credentials. The platform's page (#/connections): every connection, each project's integrations,
   the credentials and the factory home's data stores with retention. Check now, Turn off and a rotation reminder are
   signed with the person chip; Ask Rihma answers "what does this project connect to?" and "which data leaves the
   machine?" by rule. What the kernel wrote (labels, notes, what is missing) is shown as its own words (data-ud). */

import { S, h, fill, icon, chip, api, act, say, signed, needPerson, button, ago, card, pageHead, plural, enc, empty } from "./core.js";
import { datum, emptyState, pick } from "./words.js";
import { openAssistant, send as askRihma } from "./assistant.js";
import { flowDiagram, legend } from "./itdata_flow.js";
import { itopsCard, itopsPlatformCard } from "./itops.js";   // what IT checks (FR-ITO1)

const KIND_ICON = { model: "cpu", relay: "send", hook: "link", connector: "plug", registry: "package", road: "server",
  chat: "message-square", integration: "layers" };
const STATE = { on: ["good", "check-circle", "On"], off: ["neutral", "dashed", "Off"], waiting: ["info", "clock", "Waiting"],
  failing: ["critical", "x-circle", "Failing"], "not set up": ["warning", "alert", "Not set up"] };
const PLACE = { "this machine": ["neutral", "monitor", "This machine"], "your network": ["neutral", "server", "Your network"],
  outside: ["warning", "globe", "Outside"], "not known": ["nm", "dashed", "Address not known"] };
const DIR = { in: "Data comes in", out: "Data goes out", both: "In and out" };
const ASK_CONNECT = "What does this project connect to?";
const ASK_LEAVES = "Which data leaves the machine?";

// One line of a card: an icon and its words, which wrap beside the icon, never under it.
function line(iconName, kids, cls) { return h("p", { class: "itd-line" + (cls ? " " + cls : "") }, icon(iconName), h("span", null, kids)); }
function stateChip(s) { const [t, i, w] = STATE[s] || STATE["not set up"]; return chip(t, i, w, { "data-state": s }); }
function placeChip(p) { const [t, i, w] = PLACE[p] || PLACE["not known"]; return chip(t, i, w); }
function ask(question) { openAssistant(); askRihma(question); }
function askButton(question, key) {
  return button(question, { icon: "bot", kind: "small quiet", key, onclick: () => ask(question) });
}

// -- one connection -----------------------------------------------------------------------------------------

function healthLine(x) {
  const hh = x.health;
  if (!hh) return line("pulse", "Not checked yet: press Check now.", "muted");
  const parts = [hh.ok === true ? "Passed" : hh.ok === false ? "Failed" : "Nothing to measure",
    hh.latency_ms != null ? hh.latency_ms + " ms" : null, hh.failures ? plural(hh.failures, "failure") + " in a row" : null,
    hh.at ? ago(hh.at) : null].filter(Boolean);
  return line("pulse", [parts.join(" · ") + (hh.why ? ": " : ""), hh.why ? datum(hh.why) : null], hh.ok === false ? "bad" : null);
}

function credList(x) {
  if (!x.credentials.length) return null;
  return line("key", ["Credentials: ", x.credentials.map((c, i) => h("span", { class: "itd-cred" }, i ? ", " : "", h("code", null, c.name),
    c.set === false ? h("span", { class: "itd-unset" }, " (not set here)") : null))]);
}

async function runCheck(base, id, again) {
  if (!needPerson()) return;
  const out = await api("POST", "/api/it-data/check", Object.assign({}, base, id ? { item: id } : {}, signed()));
  say(out.summary, out.failing.length ? "warning" : "good");
  await again();
}

function offForm(base, x, again) {
  const reason = h("input", { type: "text", class: "input small", maxlength: "300", "aria-label": "Why turn " + x.label + " off",
    placeholder: "Why (saved with the record)" });
  const wide = x.disable && x.disable.wide;
  const ok = button(wide ? "Turn off for all of them" : "Turn off", { icon: "stop", kind: "small danger", key: "itd-off-ok:" + x.id, "data-control": "itdata_disable" });
  // one that serves other projects too: said before confirming, and signed with your IT access on the platform
  const warn = wide ? line("alert", ["Before you turn it off: ", datum(wide), ". It is signed with your IT access on the platform."], "itd-wide") : null;
  const box = h("div", { class: "itd-off" }, warn, reason, ok,
    button("Cancel", { kind: "small quiet", onclick: () => box.remove() }));
  ok.addEventListener("click", () => act(box, async () => {
    if (!needPerson()) return;
    const out = await api("POST", "/api/it-data/disable", Object.assign({}, base, { item: x.id, reason: reason.value }, signed()));
    say(out.label + " is off" + (out.wide ? " for every project it served." : ".") + (out.note ? " " + out.note + "." : ""), "good");
    await again();
  }));
  return box;
}

function actions(base, x, again) {
  const check = button("Check now", { icon: "refresh", kind: "small", key: "itd-check:" + x.id, "data-control": "itdata_check",
    aria: "Check now: " + x.label });
  check.addEventListener("click", () => act(row, () => runCheck(base, x.id, again)));
  const off = x.disable && x.disable.how ? button("Turn off", { icon: "stop", kind: "small", key: "itd-off:" + x.id,
    "data-control": "itdata_disable", aria: "Turn off: " + x.label }) : null;
  if (off) off.addEventListener("click", () => { if (!row.querySelector(".itd-off")) row.after(offForm(base, x, again)); });
  const open = x.open ? h("a", { class: "btn small quiet", href: x.open, "aria-label": "Open where " + x.label + " is set" },
    icon("arrow-right"), h("span", { class: "lbl" }, "Open")) : null;
  const row = h("div", { class: "itd-acts" }, check, off, open);
  return row;
}

function connCard(base, x, again) {
  const notes = [x.note ? line("info", datum(x.note), "muted") : null];
  const missing = x.missing.length ? h("ul", { class: "itd-missing", "aria-label": "What to do" },
    x.missing.map((m) => h("li", null, datum(m)))) : null;
  const classes = x.data_classes.map((d) => chip("neutral", "file-check", d));
  return h("li", { class: "itd-card", "data-id": x.id, "data-state": x.state, "data-key": "itd:" + x.id, tabindex: "-1" },
    h("div", { class: "itd-top" }, h("b", { class: "itd-label", "data-ud": "" }, x.label), stateChip(x.state)),
    h("div", { class: "itd-chips" }, placeChip(x.locality), chip("neutral", x.direction === "in" ? "download" : "upload", DIR[x.direction]),
      x.access ? chip("neutral", "key", x.access + " access") : null, x.scope === "project" ? null : chip("neutral", "layers", x.scope === "shared" ? "Shared with other projects" : "Platform-wide"),
      x.refused ? chip("good", "shield", "Never called for this project") : null),
    classes.length ? h("div", { class: "itd-chips", "aria-label": "Data it touches" }, classes) : null,
    healthLine(x), credList(x), notes, missing, actions(base, x, again));
}

function connections(base, view, again, emptyHow) {
  const groups = Object.keys(view.kinds).map((k) => [k, view.items.filter((x) => x.kind === k)]).filter(([, l]) => l.length);
  const body = groups.length ? groups.map(([k, list]) => h("section", { class: "itd-group", "data-kind": k },
    h("h4", { class: "itd-gh" }, icon(KIND_ICON[k] || "plug"), h("span", null, view.kinds[k]), h("span", { class: "count" }, String(list.length))),
    h("ul", { class: "itd-grid" }, list.map((x) => connCard(base, x, again)))))
    : emptyState("itdata", askButton(ASK_CONNECT, "itd-ask-empty"), { icon: "plug", what: "No connection yet.", how: emptyHow });
  return card({ title: "Connections", icon: "plug", id: "itd-conns" }, h("div", { "data-control": "itdata_map" }, body));
}

// -- credentials, agents, the flow --------------------------------------------------------------------------

function rotateForm(base, c, again) {
  const days = h("input", { type: "number", class: "input small itd-days", min: "1", max: "730", value: "90",
    "aria-label": "Days until " + c.name + " is rotated" });
  const ok = button("Set reminder", { icon: "clock", kind: "small", key: "itd-rot:" + c.name, "data-control": "itdata_rotate" });
  ok.addEventListener("click", () => act(ok.parentElement, async () => {
    if (!needPerson()) return;
    const out = await api("POST", "/api/it-data/rotate-reminder", Object.assign({}, base,
      { credential: c.name, days: Number(days.value) || 90 }, signed()));
    say("Rotate " + out.credential + " by " + out.due + ".", "good");
    await again();
  }));
  return h("span", { class: "itd-rot" }, days, h("span", { class: "small muted" }, "days"), ok);
}

function credentials(base, view, again) {
  const rows = view.credentials;
  const said = { true: ["good", "check", "Set here"], false: ["warning", "alert", "Not set here"], null: ["nm", "dashed", "Not readable here"] };
  const body = rows.length ? h("ul", { class: "itd-creds" }, rows.map((c) => {
    const [t, i, w] = said[String(c.set)] || said.null;
    const due = c.rotation ? chip(c.rotation.overdue ? "warning" : "neutral", "clock", (c.rotation.overdue ? "Rotate now: was due " : "Rotate by ") + c.rotation.due) : null;
    return h("li", { class: "itd-credrow", "data-cred": c.name },
      h("div", { class: "itd-top" }, h("code", null, c.name), chip(t, i, w)),
      line("key", datum(c.where), "muted"),
      line("link", ["Used by ", datum(c.used_by.map((u) => u.label).join(", "))], "muted"),
      h("div", { class: "itd-acts" }, due, rotateForm(base, c, again)));
  })) : emptyState("itdata", askButton("Which credentials does this use?", "itd-ask-creds"),
    { icon: "key", what: "No credential named.", how: "A credential appears here, by name only, when a connection needs one: a model's key, a relay channel's address, a binding's secret." });
  return card({ title: "Credentials (names only)", icon: "key", id: "itd-creds" },
    h("p", { class: "small muted" }, "A value is never read or shown here: only where each one lives, and whether it is set where Rihmasto runs."), body);
}

function agents(view) {
  return card({ title: "What each agent may reach", icon: "bot", id: "itd-agents" },
    h("ul", { class: "itd-agents" }, view.agents.map((a) => h("li", { class: "itd-agent", "data-agent": a.id },
      h("div", { class: "itd-top" }, h("b", { "data-ud": "" }, a.label),
        a.blocked ? chip("warning", "alert", "Blocked: needs a local model", { "data-blocked": "1" })
          : a.leaves ? chip("warning", "globe", "Sends data outside") : chip("good", "shield", "Stays here")),
      a.blocked ? line("alert", [datum(a.blocked), " ", h("a", { href: "#/models", "data-key": "itd-models:" + a.id }, "Open Models setup")], "itd-blocked") : null,
      line("check", ["Reaches: ", datum(a.reaches)]),
      line("x", ["Never: ", datum(a.never)], "muted"),
      a.model_labels.length ? line("cpu", ["Models: ", datum(a.model_labels.join(", "))], "muted") : null))));
}

function pickNode(box, view) {
  return (n) => {
    const detail = box.querySelector(".itd-detail");
    const x = view.items.find((i) => i.id === n.item);
    const a = view.agents.find((i) => i.id === n.agent);
    fill(detail, h("b", { "data-ud": "" }, n.label), " ", placeChip(n.locality),
      x ? [h("p", { class: "itd-line" }, datum((x.data_classes.join(", ") || "") + (x.note ? " · " + x.note : ""))),
        h("button", { type: "button", class: "btn small", "data-key": "itd-goto:" + x.id, onclick: () => {
          const el = document.querySelector('.itd-card[data-id="' + CSS.escape(x.id) + '"]');
          if (el) { el.scrollIntoView({ block: "center" }); el.focus({ preventScroll: true }); el.classList.add("focused"); }
        } }, icon("arrow-right"), h("span", { class: "lbl" }, "Show the connection"))] : null,
      a ? h("p", { class: "itd-line" }, datum("Reaches " + a.reaches + ". Never " + a.never + ".")) : null);
    detail.hidden = false;
  };
}

function flowCard(view) {
  const box = h("div", { class: "itd-flow", "data-control": "itdata_flow" });
  const detail = h("div", { class: "itd-detail", hidden: true, "aria-live": "polite" });
  box.append(flowDiagram(view.flow, pickNode(box, view)), detail);
  // counted from the diagram itself: each place a dashed line ends, so the words and the picture always agree
  const leaving = view.flow.leaving.length;
  return card({ title: "Data flow", icon: "graph", id: "itd-flow", tools: askButton(ASK_LEAVES, "itd-ask-leaves") },
    h("p", { class: "small", "data-key": "itd-flow-caption" }, leaving ? pick(plural(leaving, "connection") + " may send data outside this machine and your network: each is drawn with a dashed line.",
      plural(leaving, "egress target") + " outside this machine and your network (dashed).") : "Nothing here sends data outside this machine and your network."),
    legend(), box);
}

function head(view, base, again, title, sub) {
  const check = button("Check now", { icon: "refresh", kind: "small primary", key: "itd-check-all", "data-control": "itdata_check",
    aria: "Check every connection now" });
  check.addEventListener("click", () => act(check.parentElement, () => runCheck(base, null, again)));
  const counts = Object.entries(view.summary.by_locality).filter(([, n]) => n).map(([p, n]) => {
    const [t, i, w] = PLACE[p] || PLACE["not known"]; return chip(t, i, n + " · " + w.toLowerCase());
  });
  return [h("p", { class: "itd-sum", "data-key": "itd-summary", "data-ud": "" }, view.summary.line),
    h("div", { class: "itd-bar" }, h("div", { class: "itd-counts" }, counts),
      h("span", { class: "itd-bar-r" }, h("span", { class: "muted small" }, view.checked ? "Checked " + ago(view.checked) : "Not checked yet"),
        check, askButton(title === "project" ? ASK_CONNECT : "What does the platform connect to?", "itd-ask-connect")))];
}

// -- the project's view --------------------------------------------------------------------------------------

async function drawProject(box, pid) {
  const view = await api("GET", "/api/projects/" + enc(pid) + "/it-data");
  if (!box.isConnected && box.dataset.drawn) return;
  box.dataset.drawn = "1";
  const again = () => drawProject(box, pid).catch((e) => say(e.message, "critical"));
  const base = { project: pid };
  fill(box, h("div", { class: "q itd-head" }, h("h2", { id: "view-title", tabindex: "-1" }, "Integrations and data"),
    h("p", null, "What this project connects to, where each connection is, what each agent may reach, and which data may leave this machine."),
    view.confidential ? h("p", null, chip("good", "shield", "Confidential: hosted models are never called for it")) : null,
    view.confidential && view.agents.some((a) => a.blocked) ? line("alert", ["Blocked until a local model is set: ",
      datum(view.agents.filter((a) => a.blocked).map((a) => a.label).join(", ")), ". ", h("a", { href: "#/models" }, "Open Models setup")]) : null,
    head(view, base, again, "project")),
  flowCard(view), connections(base, view, again, "Connections appear here when the project declares a data integration, runs somewhere, or a channel carries its events: declare one in the Plan's Data integrations."),
  h("div", { class: "itd-two" }, agents(view), credentials(base, view, again)), itopsCard(pid));
}

export function render(p) {
  const pid = p.meta.id;
  const box = h("div", { class: "itd-view" }, h("p", { class: "muted" }, "Reading what this project connects to…"));
  drawProject(box, pid).catch((e) => { if (box.isConnected) fill(box, empty("alert", e.message, askButton(ASK_CONNECT, "itd-ask-err"))); });
  return box;
}

// -- the platform's page -----------------------------------------------------------------------------------

function projectsCard(view) {
  const rows = view.projects;
  const body = rows.length ? h("ul", { class: "itd-projects" }, rows.map((p) => h("li", { class: "itd-proj", "data-pid": p.pid },
    h("div", { class: "itd-top" }, h("a", { href: "#/p/" + enc(p.pid) + "/itdata", "data-ud": "" }, p.title || p.pid),
      p.confidential ? chip("good", "shield", "Confidential") : null),
    p.integrations.length ? h("ul", { class: "itd-chips" }, p.integrations.map((i) => h("li", null,
      chip("neutral", "layers", i.name + " · " + i.kind + " · " + i.access + (i.data_classes.length ? " · " + i.data_classes.join(", ") : "")))))
      : h("p", { class: "small muted" }, "No data integration declared.")))) : emptyState("itdata", null,
    { icon: "folder", what: "No project yet.", how: "Each project's data integrations appear here once it has a spec." });
  return card({ title: "Projects and their data integrations", icon: "folder", id: "itd-projects" }, body);
}

function kb(b) { return b >= 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB"; }

function storesCard(view) {
  const s = view.stores;
  const broken = s.integrity.broken.length;
  return card({ title: "Data stores and retention", icon: "server", id: "itd-stores" }, h("div", { "data-control": "itdata_stores" },
    h("p", { class: "small" }, kb(s.bytes) + " in the factory home · ",
      chip(broken ? "critical" : "good", broken ? "x-circle" : "check-circle", broken ? broken + " ledger(s) broken" : s.integrity.intact + " of " + s.integrity.ledgers + " ledgers intact")),
    h("ul", { class: "itd-stores" }, s.stores.map((r) => h("li", { class: "itd-store" },
      h("div", { class: "itd-top" }, h("b", { "data-ud": "" }, r.label), h("span", { class: "small muted" }, kb(r.bytes) + " · " + plural(r.files, "file"))),
      line("clock", datum(r.retention), "muted")))),
    h("p", { class: "small muted" }, "Never cleaned: ", datum(s.never_cleaned), ". ",
      h("a", { href: "#/data" }, "Clean up on Data and context"))));
}

export async function renderConnections(seq) {
  const main = document.getElementById("main");
  let view;
  try { view = await api("GET", "/api/it-data"); } catch (e) { fill(main, empty("alert", e.message)); return; }
  if (seq !== S.seq) return;
  document.title = "Integrations and data · Rihmasto.ai";
  const again = () => renderConnections(S.seq);
  fill(main, pageHead("Integrations and data", "Every connection the platform has, where each one is, what each agent may reach, the credentials by name and the data the home keeps.",
    { icon: "plug", actions: [button("Refresh", { icon: "refresh", kind: "quiet", key: "itd-refresh", onclick: again })] }),
  h("div", { class: "itd-view" }, head(view, {}, again, "platform"),
    connections({}, view, again, "Connections appear here once a model is set, IT adds a relay channel or a webhook source, or a connector or registry is named."),
    h("div", { class: "itd-two" }, projectsCard(view), storesCard(view)),
    h("div", { class: "itd-two" }, agents(view), credentials({}, view, again)), itopsPlatformCard()));
}
