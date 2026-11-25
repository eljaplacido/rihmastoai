/* The cockpit's core: state, DOM helpers, the API, formatting, tooltips, menus and modals.
   Every fact comes from the JSON API behind the session token; every write is signed with the
   person and persona chosen in the person chip, and the kernel decides whether it stands. */

export const BRAND = "Rihmasto.ai";   // the system; a single agent is "Rihma" (D-0013)
export const FACTORY_PID = "_factory";

// The page's routes. Every view in cockpit/ui_map.json has its route here, and the router is
// built from this table (tests/test_cockpit.py checks the two agree).
export const PAGE_ROUTES = {
  "home": "#/home", "square": "#/square", "catalogue": "#/catalogue", "projects": "#/projects",
  "inbox_all": "#/inbox", "floor": "#/floor", "jobs": "#/jobs", "settings": "#/settings",
  "shape": "#/shape", "models": "#/models", "runners": "#/runners", "automations_all": "#/automations",
  "insights_all": "#/insights", "insights": "#/p/{pid}/insights",
  "overview": "#/p/{pid}/overview", "inbox": "#/p/{pid}/inbox", "questions": "#/p/{pid}/questions",
  "assumptions": "#/p/{pid}/assumptions", "plan": "#/p/{pid}/plan", "spec": "#/p/{pid}/spec",
  "tasks": "#/p/{pid}/tasks", "cell": "#/p/{pid}/cell", "releases": "#/p/{pid}/releases",
  "try": "#/p/{pid}/try", "changes": "#/p/{pid}/changes", "ledger": "#/p/{pid}/ledger",
  "evidence": "#/p/{pid}/evidence", "track": "#/p/{pid}/track", "outputs": "#/p/{pid}/outputs",
  "assessment": "#/p/{pid}/assessment", "automations": "#/p/{pid}/automations",
  "console": "#/p/{pid}/console", "checks": "#/p/{pid}/checks", "health_all": "#/health", "align": "#/p/{pid}/align",
  "review_all": "#/review", "review": "#/p/{pid}/review", "agents": "#/p/{pid}/agents", "agents_all": "#/agents",
  "aitools": "#/p/{pid}/aitools"
};
export const TOP_PAGES = Object.keys(PAGE_ROUTES).filter((k) => !PAGE_ROUTES[k].includes("{pid}"));
export const PROJECT_VIEWS = Object.keys(PAGE_ROUTES).filter((k) => PAGE_ROUTES[k].includes("{pid}"));

export const PAGES = {
  home: { label: "Home", icon: "home" },
  // a page whose own name is a metaphor (Square, Floor) is called by what it shows to a business reader (words.js)
  square: { get label() { return pageLabel("square", "Square"); }, icon: "square" },
  catalogue: { get label() { return pageLabel("catalogue", "Catalogue"); }, icon: "catalogue" },
  projects: { label: "Projects", icon: "folder" },
  inbox_all: { label: "Inbox", icon: "inbox" },
  floor: { get label() { return pageLabel("floor", "Floor"); }, icon: "factory" },
  insights_all: { label: "Insights", icon: "insight" },
  jobs: { get label() { return pageLabel("jobs", "Jobs"); }, icon: "terminal" },
  settings: { label: "Settings", icon: "settings" },
  shape: { label: "Describe a new idea in chat", icon: "message-square" },
  models: { label: "Models", icon: "cpu" },
  runners: { label: "Runners", icon: "layers" },
  automations_all: { label: "Automations", icon: "clock" },
  health_all: { label: "Health", icon: "pulse" },      // checks across every project (health.js, FR-CHK1)
  review_all: { label: "Review", icon: "eye" },   // since you last looked (review.js)
  agents_all: { label: "Agent activity", icon: "bot" },   // every project's agent channel (agents.js, FR-CHN1)
};
export const VIEWS = {
  overview: { label: "Overview", icon: "home" },
  plan: { label: "Plan", icon: "check-circle" },
  inbox: { label: "Inbox", icon: "inbox" },
  questions: { label: "Questions", icon: "comment" },
  assumptions: { label: "Assumptions", icon: "flag" },
  spec: { label: "Spec & contract", icon: "file-check" },
  tasks: { label: "Tasks", icon: "pipeline" },
  cell: { label: "Cell", icon: "cpu" },
  try: { label: "Try it", icon: "play" },
  releases: { label: "Releases", icon: "package" },
  changes: { label: "Changes", icon: "refresh" },
  ledger: { label: "Ledger", icon: "layers" },
  evidence: { label: "Evidence", icon: "shield" },
  track: { label: "Track", icon: "flag" },
  outputs: { label: "Outputs", icon: "send" },
  assessment: { label: "Assessment", icon: "gauge" },
  automations: { label: "Automations", icon: "clock" },
  console: { label: "Console", icon: "terminal" },     // run commands in the workspace (console.js, FR-CON1)
  checks: { label: "Health", icon: "pulse" },          // the project's checks (health.js, FR-CHK1)
  align: { label: "Alignment", icon: "merge" },
  insights: { label: "Insights", icon: "insight" },
  review: { label: "Review", icon: "eye" },
  agents: { label: "Channel", icon: "bot" },     // agents and people on this project (agents.js, FR-CHN1)
  aitools: { label: "AI tools", icon: "sparkles" },   // the repository's AI tools, in the Agents capsule (aitools.js)
};
export const FACTORY_VIEWS = ["overview", "inbox", "ledger"];
export const STAGE_ICON = { 1: "briefcase", 2: "lightbulb", 3: "code", 4: "file-check", 5: "hammer", 6: "users", 7: "server" };
export const STAGE_VIEW = { 1: "questions", 2: "questions", 3: "spec", 4: "spec", 5: "tasks", 6: "try", 7: "releases" };
const KIND_TECH = {
  question: "Question", approval: "Approval", validation: "Validation", deploy_gate: "Deploy gate",
  incident: "Incident", change: "Change", escalation: "Escalation", road: "Paved road", trust: "Trust",
  holdout_ruling: "Holdout ruling", concept: "Concept", update: "Update", go_ahead: "Go-ahead",
  runner: "Cell runner",
};
// A card kind in the reader's words (words.js sets wordHooks.kind): "Stuck task" to a business owner, "Escalation" to a developer.
export const KIND_LABEL = new Proxy(KIND_TECH, { get: (t, k) => (wordHooks.kind && wordHooks.kind(k)) || t[k] });
export const KIND_ICON = {
  question: "comment", approval: "check-circle", validation: "users", deploy_gate: "server", incident: "alert",
  change: "refresh", escalation: "flag", road: "arrow-right", trust: "key", holdout_ruling: "shield",
  concept: "lightbulb", update: "bell", go_ahead: "eye", runner: "layers",
};
export const VERDICT_LABEL = {
  answer: "Answer", assume: "Let Rihma assume", approve: "Approve", reject: "Reject", accept: "Accept",
  fix: "Fix", change: "Change", keep: "Keep", refuse: "Refuse", acknowledge: "Acknowledge",
  rollback: "Roll back", open_defect: "Open a defect", defer: "Defer", retry: "Retry",
  get accept_as_is() { return (wordHooks.verdict && wordHooks.verdict("accept_as_is")) || "Accept as is"; }, stop: "Stop", configured: "Configured", declined: "Declined", granted: "Granted",
  validate: "Validate", park: "Park", trial: "Start a trial", decline: "Decline", product_defect: "Product defect",
  scenario_defect: "Scenario defect", go: "Go: build it", skip: "Skip: build without my look",
};
export const CLASS_LABEL = {
  defect: "defect", change_request: "change request", new_requirement: "new requirement",
  infra_change: "infra change", incident: "incident", question: "question",
};
export const PERSPECTIVE_LABEL = {
  business: "business", end_user: "end user", it_security: "IT and security", operations: "operations",
  delivery: "delivery",
};
// A state always carries an icon and a word, never colour alone.
export const NOW_STATE = {
  working: { tone: "info", icon: "refresh", word: "Working" },
  // the project waits on a person, not always the reader: the Inbox says which cards are theirs
  waiting_on_you: { tone: "warning", icon: "user", word: "Waiting on a person" },
  done: { tone: "good", icon: "check-circle", word: "Done" },
  failed: { tone: "critical", icon: "x-circle", word: "Failed" },
  paused: { tone: "neutral", icon: "pause", word: "Paused" },
};
export const EVIDENCE = {
  verified: { tone: "good", icon: "check-circle", word: "Verified" },
  held_out: { tone: "good", icon: "shield", word: "Held out" },
  claimed: { tone: "warning", icon: "dashed", word: "Claimed" },
  failing: { tone: "critical", icon: "x-circle", word: "Failing" },
  not_measured: { tone: "nm", icon: "dashed", word: "Not measured" },
};
export const EVIDENCE_ORDER = ["verified", "held_out", "claimed", "failing", "not_measured"];
export const HEALTH = {
  on_track: { tone: "good", icon: "check-circle", word: "On track" },
  at_risk: { tone: "warning", icon: "alert", word: "At risk" },
  off_track: { tone: "critical", icon: "stop", word: "Off track" },
};
export const CATALOGUE_STATE = {
  in_use: { tone: "good", icon: "check-circle", word: "In use" },
  pilot: { tone: "info", icon: "flag", word: "Pilot" },
  trying: { tone: "info", icon: "users", word: "Trying" },
  building: { tone: "info", icon: "hammer", word: "Building" },
  shaping: { tone: "neutral", icon: "edit", word: "Shaping" },
  proposed: { tone: "warning", icon: "lightbulb", word: "Proposed" },
};
export const LENS_ICON = { business: "briefcase", concept: "lightbulb", delivery: "hammer", operations: "activity",
  compliance: "shield", insight: "sparkles" };
export const ACCENTS = ["amber", "teal", "violet", "blue", "green", "rose"];

export const S = {
  token: null, persona: "business_owner", person: "", personas: [], meta: null, route: null,
  lens: null, lensPinned: false, project: null, context: null, inbox: null, projects: null, inboxCount: 0,
  allViews: false, showSettled: false, onlyMine: false, onlyWaiting: false, oneAtATime: false,
  alignOpen: {}, skipped: {}, focusNext: null, jumped: false, timer: null, seq: 0, dashboard: null,
  layout: null, layoutPreset: true, theme: null, customizing: false, uiMap: null, running: [],
  enforcedSignIn: false,
};

// The router and the shell register themselves here, so modules can call them without import cycles.
export const nav = { route: null, rerender: null, openPerson: null, refreshShell: null, applyTheme: null };

// -- storage: sessionStorage for the tab, localStorage only as a cache and for conveniences ---------

function wrap(get) {
  return {
    get(k) { try { return get().getItem(k); } catch (e) { return null; } },
    set(k, v) { try { get().setItem(k, v); } catch (e) { /* storage may be off */ } },
    del(k) { try { get().removeItem(k); } catch (e) { /* storage may be off */ } },
  };
}
export const store = wrap(() => window.sessionStorage);
export const local = wrap(() => window.localStorage);
export function localJSON(key, fallback) {
  const raw = local.get(key);
  if (!raw) return fallback;
  try { return JSON.parse(raw); } catch (e) { return fallback; }
}

// -- DOM ----------------------------------------------------------------------------------------

export const $ = (sel, root) => (root || document).querySelector(sel);
export const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
export const enc = encodeURIComponent;
const SVG_NS = "http://www.w3.org/2000/svg";

/* h(tag, attrs, ...kids): attributes, on* listeners, and `style` as an object applied through the
   CSSOM (never a style attribute: the policy forbids inline styles). */
export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  setAttrs(el, attrs);
  append(el, kids);
  return el;
}
export function svg(tag, attrs, ...kids) {
  const el = document.createElementNS(SVG_NS, tag);
  setAttrs(el, attrs);
  append(el, kids);
  return el;
}
function setAttrs(el, attrs) {
  if (!attrs) return;
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.setAttribute("class", v);
    else if (k === "style" && typeof v === "object") {
      for (const [p, x] of Object.entries(v)) {
        if (x === null || x === undefined) continue;
        if (p.startsWith("--")) el.style.setProperty(p, String(x)); else el.style[p] = x;
      }
    } else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "tip") attachTip(el, v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, String(v));
  }
}
function append(el, kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
}
export function fill(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false)
    .map((k) => (k instanceof Node ? k : document.createTextNode(String(k)))));
}
export function icon(name, cls) {
  const s = svg("svg", { class: "ic" + (cls ? " " + cls : ""), "aria-hidden": "true", focusable: "false" });
  s.append(svg("use", { href: "#i-" + name }));
  return s;
}
// A chip: an icon and a word, with a tone (good, warning, serious, critical, info, neutral, nm, accent).
export function chip(tone, iconName, text, attrs) {
  return h("span", Object.assign({ class: "chip " + (tone || "neutral") }, attrs || {}),
    iconName ? icon(iconName) : null, h("span", null, text));
}
export function button(label, opts) {
  const o = opts || {};
  const b = h("button", {
    type: o.type || "button", class: "btn" + (o.kind ? " " + o.kind : "") + (o.cls ? " " + o.cls : ""),
    "data-key": o.key || null, "data-control": o["data-control"] || o.control || null, disabled: o.disabled || null,
    "aria-label": o.aria || null, title: null, tip: o.tip || null, "aria-expanded": o.expanded,
    "aria-controls": o.controls || null,
  }, o.icon ? icon(o.icon) : null, label ? h("span", { class: "lbl" }, label) : null);
  if (o.onclick) b.addEventListener("click", o.onclick);
  return b;
}
export function iconButton(iconName, label, onclick, extra) {
  const b = h("button", Object.assign({ type: "button", class: "icon-btn", "aria-label": label, tip: label }, extra || {}),
    icon(iconName));
  if (onclick) b.addEventListener("click", onclick);
  return b;
}
export function avatar(name, kind) {
  const initials = String(name || "?").trim().split(/\s+/).map((w) => w[0] || "").join("").slice(0, 2).toUpperCase() || "?";
  if (kind === "agent") return h("span", { class: "avatar agent", "aria-hidden": "true" }, icon("bot"));
  if (kind === "kernel") return h("span", { class: "avatar kernel", "aria-hidden": "true" }, icon("diamond"));
  return h("span", { class: "avatar person", "aria-hidden": "true" }, initials);
}
export function sepList(nodes, sep) {
  const out = [];
  nodes.forEach((n, i) => { if (i) out.push(h("span", { class: "sep", "aria-hidden": "true" }, sep || " · ")); out.push(n); });
  return out;
}
export function empty(iconName, line, action) {
  return h("div", { class: "empty" }, h("span", { class: "empty-ic" }, icon(iconName || "info")),
    h("p", null, line), action || null);
}
// A static placeholder, shown only if loading takes more than a second (never a shimmer). Only the latest
// load draws one, and never over what a finished render or an error has put there (the router marks main
// loaded when it is done either way).
let loads = 0;
export function skeleton(main, what) {
  const mine = String(++loads);
  const t = setTimeout(() => {
    if (!main.isConnected || main.dataset.loaded === "1" || main.dataset.load !== mine) return;
    fill(main, h("div", { class: "skeleton", "aria-label": "Loading " + what }, h("div", { class: "sk-h" }),
      h("div", { class: "sk-row" }, h("div", { class: "sk-b" }), h("div", { class: "sk-b" })), h("div", { class: "sk-b tall" })));
  }, 1000);
  main.dataset.load = mine;
  main.dataset.loaded = "0";
  return () => { clearTimeout(t); if (main.dataset.load === mine) main.dataset.loaded = "1"; };
}

// -- formatting ---------------------------------------------------------------------------------

export function fmtAt(s) { return s ? String(s).replace("T", " ").replace(/:\d\dZ$/, " UTC").replace(/Z$/, " UTC") : ""; }
export function short(hash) { return hash ? String(hash).slice(0, 12) + "…" : "none"; }
export function cap(s) { s = String(s || ""); return s.charAt(0).toUpperCase() + s.slice(1); }
export function plural(n, one, many) { return n + " " + (n === 1 ? one : (many || one + "s")); }
export function num(n) { return n === null || n === undefined ? "not measured" : Number(n).toLocaleString("en-US"); }
export function pct(r, digits) {
  if (r === null || r === undefined) return null;
  const d = digits === undefined ? 0 : digits;
  return (Math.round(r * 100 * 10 ** d) / 10 ** d) + "%";
}
export function link(pid, view, focus) { return "#/p/" + enc(pid) + "/" + view + (focus ? "/" + enc(focus) : ""); }
export function fmtMoney(amount, currency) {
  if (amount === null || amount === undefined) return "not measured";
  const digits = Math.abs(amount) >= 1 ? 2 : 4;
  return Number(amount).toFixed(digits) + " " + (currency || "USD");
}
export function fmtCost(cost) {
  if (!cost || !cost.measured) return h("span", { class: "nm-text", tip: (cost && cost.why) || "not measured" }, "not measured");
  if (cost.kind === "local") return "local · " + num(cost.local_tokens) + " tokens";
  return fmtMoney(cost.amount, cost.currency);
}
export function fmtMinutes(m) {
  if (m === null || m === undefined) return null;
  if (m < 1) return "under a minute";
  if (m < 120) return Math.round(m) + " min";
  const hours = Math.floor(m / 60);
  return hours + " h " + Math.round(m - hours * 60) + " min";
}
export function fmtAge(hours) {
  if (hours === null || hours === undefined) return "age not known";
  if (hours < 1) return Math.max(1, Math.round(hours * 60)) + " min";
  if (hours < 48) return Math.round(hours) + " h";
  return Math.round(hours / 24) + " d";
}
export function ago(at) {
  if (!at) return "";
  const t = Date.parse(at);
  if (Number.isNaN(t)) return fmtAt(at);
  const m = (Date.now() - t) / 60000;
  if (m < 1) return "just now";
  if (m < 60) return Math.round(m) + " min ago";
  if (m < 48 * 60) return Math.round(m / 60) + " h ago";
  return Math.round(m / 1440) + " d ago";
}

// -- people -------------------------------------------------------------------------------------

export function personaLabel(id) { const p = S.personas.find((x) => x.id === id); return p ? p.label : (id || ""); }
// ``who``: a card's own deciders, when it names fewer than its kind's (a posture may narrow them).
export function decides(kind, who) {
  const p = S.personas.find((x) => x.id === S.persona);
  return !!p && p.decides.includes(kind) && (!who || !who.length || who.includes(S.persona));
}
export function orList(ids) {
  const words = ids.map(personaLabel);
  return words.length > 1 ? words.slice(0, -1).join(", ") + " or " + words[words.length - 1] : words.join("");
}
export function stageName(n) { return (S.meta && S.meta.stages[String(n)]) || "?"; }
export function bandOf(n) {
  const b = ((S.meta && S.meta.bands) || []).find((x) => x.stages.includes(Number(n)));
  return b ? b.label : "";
}
export function profileOf(id) {
  return ((S.meta && S.meta.profiles) || []).find((p) => p.id === id) || { id, label: id || "Web app or service", icon: "globe" };
}
export function signed() { return { person: S.person.trim(), persona: S.persona }; }
export function needPerson() {
  if (S.person.trim()) return true;
  say("Set your name first: every decision is signed with a person and a persona.", "warning");
  if (nav.openPerson) nav.openPerson(true);
  return false;
}
export function personBadge(name, persona) {
  return h("span", { class: "who person", tip: "A person" + (persona ? ", as " + personaLabel(persona) : "") },
    avatar(name), h("span", { class: "vh" }, "person: "), h("span", { class: "who-n" }, name || "?"),
    persona ? h("span", { class: "who-r" }, personaLabel(persona)) : null);
}
// Words per persona set from words.js (which imports this module): the kernel is "an automatic rule" to a business reader.
export const wordHooks = { kernel: () => "the kernel" };
function pageLabel(id, fallback) { return (wordHooks.page && wordHooks.page(id)) || fallback; }
export function agentBadge(name, model) {
  const kernel = name === "the kernel" || name === "kernel";
  // the legend says a rule is never a model: a kernel row is labelled a rule, not an agent
  return h("span", { class: "who agent", tip: kernel ? "An automatic rule (the kernel): it decides by fixed rules, never by a model" : "An agent: a model in a role" },
    avatar(name, kernel ? "kernel" : "agent"), h("span", { class: "vh" }, kernel ? "rule: " : "agent: "), h("span", { class: "who-n", "data-ud": kernel ? null : "" }, kernel ? wordHooks.kernel() : name),   // an agent's role as recorded
    model ? h("span", { class: "who-r mono" }, model) : null);
}
export function actorBadge(a) {
  if (!a) return h("span", { class: "muted" }, "-");
  return a.type === "person" ? personBadge(a.name, a.persona) : agentBadge(a.name, a.model);
}

// -- the API ------------------------------------------------------------------------------------

export class AuthError extends Error {}
let onSignedOut = () => {};
export function setSignedOutHandler(fn) { onSignedOut = fn; }

// "same-origin": with access enforced, IT's sign-in proxy in front of the cockpit keeps its own session
// cookie and needs it on every request. The cockpit itself sets and reads no cookie.
export const CREDENTIALS = "same-origin";

// The session: a single operator's as a Bearer token; with access enforced, in X-Rihmasto-Session, since
// IT's proxy may put the organisation's signed token in Authorization (kernel/access_tokens.py).
function sessionHeaders() { return { Authorization: "Bearer " + S.token, "X-Rihmasto-Session": S.token || "" }; }

// With access enforced a session ends with the sign-in token it was opened with. The proxy forwards a
// fresh token on every request, so the page signs in again once, quietly, before it shows the sign-in card.
async function signInAgain() {
  try {
    const res = await fetch("/auth", { method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store",
      credentials: CREDENTIALS, body: "{}" });
    const data = await res.json();
    if (!res.ok || !data.token) return false;
    S.token = data.token;
    store.set("gf.token", S.token);
    return true;
  } catch (e) { return false; }
}

export async function api(method, path, body, again = true) {
  const opts = { method, headers: sessionHeaders(), cache: "no-store", credentials: CREDENTIALS };
  if (method !== "GET") {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body || {});
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new Error("The cockpit server did not answer. Is it still running?");
  }
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (res.status === 401) {
    if (again && data && data.access === "enforced" && S.token && await signInAgain()) return api(method, path, body, false);
    S.token = null;
    store.del("gf.token");
    if (data && data.access === "enforced") S.enforcedSignIn = true;   // sign in again through the proxy
    onSignedOut((data && data.error) || "Your session ended.");
    throw new AuthError("signed out");
  }
  if (!res.ok) {
    const err = new Error((data && data.error) || res.status + " " + res.statusText);
    err.status = res.status;
    throw err;
  }
  return data;
}

// A binary download behind the bearer token: fetched, then handed to the browser as a file.
export async function download(path, fallbackName) {
  const res = await fetch(path, { headers: sessionHeaders(), cache: "no-store", credentials: CREDENTIALS });
  if (!res.ok) {
    let msg = res.status + " " + res.statusText;
    try { msg = (await res.json()).error || msg; } catch (e) { /* not JSON */ }
    throw new Error(msg);
  }
  const blob = await res.blob();
  const disp = res.headers.get("Content-Disposition") || "";
  const m = /filename="([^"]+)"/.exec(disp);
  const a = h("a", { href: URL.createObjectURL(blob), download: (m && m[1]) || fallbackName || "download" });
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  return (m && m[1]) || fallbackName;
}

// Run a write; keep the buttons of its block disabled while it is in flight.
export async function act(container, fn) {
  const buttons = container ? $$("button", container) : [];
  const before = buttons.map((b) => b.disabled);
  buttons.forEach((b) => { b.disabled = true; });
  try {
    return await fn();
  } catch (e) {
    if (!(e instanceof AuthError)) say(e.message, "critical");
    return undefined;
  } finally {
    buttons.forEach((b, i) => { if (b.isConnected) b.disabled = before[i]; });
  }
}

// -- toasts -------------------------------------------------------------------------------------

const TOAST_ICON = { good: "check-circle", warning: "alert", critical: "x-circle", info: "info" };
const LEGACY_TONE = { ok: "good", warn: "warning", crit: "critical" };
export function say(text, toneIn) {
  const tone = LEGACY_TONE[toneIn] || toneIn;
  const region = $("#status");
  if (!region) return;
  region.replaceChildren();
  if (!text) return;
  const t = h("div", { class: "toast " + (tone || "info") }, icon(TOAST_ICON[tone] || "info"), h("span", null, text),
    h("button", { type: "button", class: "icon-btn", "aria-label": "Dismiss", onclick: () => t.remove() }, icon("x")));
  region.append(t);
  if (tone === "good" || tone === "info" || !tone) setTimeout(() => { if (t.isConnected) t.remove(); }, 7000);
}

// -- tooltips: one element for every tooltip; the same text on hover and keyboard focus ---------

const TIPS = new WeakMap();
let tipFor = null;
export function attachTip(el, content) {
  TIPS.set(el, content);
  el.classList.add("has-tip");
}
function tipContent(el) {
  const c = TIPS.get(el);
  if (c === undefined) return el.getAttribute("data-tip");
  return typeof c === "function" ? c() : c;
}
function showTip(el, x, y) {
  const content = tipContent(el);
  const tip = $("#tip");
  if (!tip || content === null || content === undefined || content === "") return;
  if (tipFor !== el) {
    fill(tip, content instanceof Node ? content : h("span", null, String(content)));
    tipFor = el;
  }
  tip.hidden = false;
  const r = el.getBoundingClientRect();
  const tw = tip.offsetWidth;
  const th = tip.offsetHeight;
  let left = x === undefined ? r.left + r.width / 2 - tw / 2 : x + 14;
  let top = y === undefined ? r.top - th - 8 : y + 16;
  if (y === undefined && top < 8) top = r.bottom + 8;
  if (left + tw > window.innerWidth - 8) left = (x === undefined ? window.innerWidth - tw - 8 : x - tw - 14);
  if (top + th > window.innerHeight - 8) top = (y === undefined ? r.top - th - 8 : y - th - 12);
  tip.style.left = Math.max(8, left) + "px";
  tip.style.top = Math.max(8, top) + "px";
}
export function hideTip() {
  const tip = $("#tip");
  if (tip) tip.hidden = true;
  tipFor = null;
}
export function wireTips() {
  const find = (t) => {
    const el = t && t.closest ? t.closest(".has-tip,[data-tip]") : null;
    // a navigation item carries its label; its tooltip is only for the collapsed icon rail
    if (el && el.classList.contains("rail-tip") && !document.documentElement.classList.contains("rail")) return null;
    return el;
  };
  document.addEventListener("pointermove", (e) => {
    const el = find(e.target);
    if (!el) { if (tipFor) hideTip(); return; }
    if (el.classList.contains("mark")) showTip(el, e.clientX, e.clientY);
    else showTip(el);
  });
  document.addEventListener("focusin", (e) => { const el = find(e.target); if (el) showTip(el); else hideTip(); });
  document.addEventListener("focusout", hideTip);
  document.addEventListener("scroll", hideTip, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideTip(); });
}

// -- menus and popovers ---------------------------------------------------------------------------

let menuClose = null;
export function closeMenu() { if (menuClose) menuClose(); }
/* items: [{label, icon, onclick, checked, disabled, sep, group}] */
export function openMenu(anchor, items, label) {
  closeMenu();
  const pop = $("#menu-pop");
  const btns = [];
  fill(pop, items.map((it) => {
    if (it.sep) return h("div", { class: "menu-sep", role: "separator" });
    if (it.group) return h("div", { class: "menu-group" }, it.group);
    const b = h("button", {
      type: "button", role: it.checked === undefined ? "menuitem" : "menuitemradio",
      "aria-checked": it.checked === undefined ? null : String(!!it.checked), class: "menu-item" + (it.danger ? " danger" : ""),
      disabled: it.disabled || null,
    }, it.icon ? icon(it.icon) : h("span", { class: "ic-space" }), h("span", null, it.label),
    it.checked ? icon("check", "menu-check") : null);
    b.addEventListener("click", () => {
      closeMenu();
      it.onclick();
      // the item that had the focus is gone with the menu: unless the choice moved the focus (to a dialog or
      // a field), it goes back to the button that opened the menu, as Esc does
      const a = document.activeElement;
      if ((!a || a === document.body || (pop.hidden && pop.contains(a))) && anchor.isConnected) anchor.focus();
    });
    btns.push(b);
    return b;
  }));
  pop.setAttribute("aria-label", label || "Menu");
  pop.hidden = false;
  const r = anchor.getBoundingClientRect();
  const w = pop.offsetWidth;
  pop.style.left = Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8)) + "px";
  const below = r.bottom + 6;
  pop.style.top = (below + pop.offsetHeight > window.innerHeight - 8 ? Math.max(8, r.top - pop.offsetHeight - 6) : below) + "px";
  anchor.setAttribute("aria-expanded", "true");
  if (btns[0]) btns[0].focus();
  const onKey = (e) => {
    const i = btns.indexOf(document.activeElement);
    if (e.key === "Escape") { e.preventDefault(); closeMenu(); anchor.focus(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); (btns[(i + 1) % btns.length] || btns[0]).focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); (btns[(i - 1 + btns.length) % btns.length] || btns[0]).focus(); }
    else if (e.key === "Tab") { closeMenu(); anchor.focus(); }   // Tab goes on from the menu's button
  };
  const onDown = (e) => { if (!pop.contains(e.target) && e.target !== anchor && !anchor.contains(e.target)) closeMenu(); };
  pop.addEventListener("keydown", onKey);
  setTimeout(() => document.addEventListener("pointerdown", onDown), 0);
  menuClose = () => {
    pop.hidden = true;
    pop.removeEventListener("keydown", onKey);
    document.removeEventListener("pointerdown", onDown);
    anchor.setAttribute("aria-expanded", "false");
    menuClose = null;
  };
}

// An ⓘ button: the long explanation lives here, not on the page.
export function infoButton(title, body) {
  const b = h("button", { type: "button", class: "icon-btn info-btn", "aria-label": "About " + title, "aria-expanded": "false" }, icon("info"));
  b.addEventListener("click", () => {
    openMenu(b, [], title);
    const pop = $("#menu-pop");
    fill(pop, h("div", { class: "info-pop" }, h("b", null, title), typeof body === "string" ? h("p", null, body) : body));
    pop.setAttribute("role", "dialog");
  });
  return b;
}

// -- the modal dialog ---------------------------------------------------------------------------

let modalOnClose = null;
export function openModal(title, body, opts) {
  const o = opts || {};
  const dlg = $("#modal");
  const opener = document.activeElement;
  fill(dlg, h("div", { class: "modal-in" + (o.wide ? " wide" : "") },
    h("div", { class: "modal-head" }, o.icon ? h("span", { class: "modal-ic" }, icon(o.icon)) : null,
      h("h2", { id: "modal-h" }, title),
      iconButton("x", "Close", () => closeModal())),
    h("div", { class: "modal-body" }, body)));
  modalOnClose = () => {
    if (o.onClose) o.onClose();
    if (opener && opener.isConnected && typeof opener.focus === "function") opener.focus();
  };
  if (!dlg.open) dlg.showModal();
  const first = dlg.querySelector("input,textarea,select,button.primary");
  if (first) first.focus();
}
export function closeModal() {
  const dlg = $("#modal");
  if (dlg.open) dlg.close();
}
export function wireModal() {
  const dlg = $("#modal");
  dlg.addEventListener("close", () => { const f = modalOnClose; modalOnClose = null; if (f) f(); fill(dlg); });
  dlg.addEventListener("click", (e) => { if (e.target === dlg) closeModal(); });
}

// -- shared small blocks ------------------------------------------------------------------------

export function nowChip(n, pid) {
  const st = NOW_STATE[(n || {}).state] || { tone: "nm", icon: "dashed", word: "Not known" };
  if (n && n.state === "waiting_on_you" && pid) {
    return h("a", { class: "chip " + st.tone, href: link(pid, "inbox"), tip: "Open the Inbox" }, icon(st.icon), h("span", null, st.word));
  }
  return chip(st.tone, st.icon, st.word);
}
export function healthChip(hl) {
  if (!hl) return chip("nm", "dashed", "Health not read");
  const st = HEALTH[hl.status] || { tone: "nm", icon: "dashed", word: hl.status };
  return chip(st.tone, st.icon, st.word, { tip: hl.reasons && hl.reasons.length ? hl.reasons.slice(0, 3).join("; ") : "Nothing holds it back" });
}
export function evChip(state) {
  const st = EVIDENCE[state] || EVIDENCE.not_measured;
  return chip(st.tone, st.icon, st.word, { tip: "Evidence: " + st.word.toLowerCase() });
}
export function profileChip(id, opts) {
  const p = profileOf(id);
  return h("span", { class: "chip profile", tip: p.summary || p.label }, icon(p.icon || "globe"),
    h("span", null, (opts && opts.short) ? p.label.split(/[:(]/)[0].trim() : p.label),
    p.status === "preview" && !(opts && opts.noPreview) ? h("span", { class: "pv" }, "preview") : null);
}
export function linkIds(pid, text) {
  const ID_VIEW = [[/^C-\d+$/, "inbox"], [/^A-\d+$/, "assumptions"], [/^D-\d+$/, "ledger"], [/^Q-\d+$/, "questions"],
    [/^T-\d+$/, "tasks"], [/^R-\d+$/, "spec"]];
  const out = [];
  const re = /\b([CADQT]-\d+|R-\d+)\b/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    const hit = ID_VIEW.find(([pat]) => pat.test(m[1]));
    if (!hit) continue;
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(h("a", { href: link(pid, hit[1], m[1]), class: "mono" }, m[1]));
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
// A card: radius 12, 1px border; header with icon, title and an ⓘ holding its question.
export function card(opts, ...body) {
  const o = opts || {};
  return h("section", { class: "card" + (o.cls ? " " + o.cls : ""), "aria-labelledby": o.id ? o.id + "-h" : null, "data-id": o.dataId || null },
    o.title ? h("header", { class: "card-head" }, o.icon ? h("span", { class: "card-ic" }, icon(o.icon)) : null,
      h("h3", { class: "card-t", id: o.id ? o.id + "-h" : null }, o.title),
      o.info ? infoButton(o.title, o.info) : null,
      h("span", { class: "card-tools" }, o.tools || null)) : null,
    body);
}
export function segmented(name, options, value, onChange, opts) {
  const o = opts || {};
  const wrapEl = h("div", { class: "seg" + (o.cls ? " " + o.cls : ""), role: "radiogroup", "aria-label": o.label || name,
    "data-control": o.control || null });
  options.forEach(([v, label, iconName]) => {
    const b = h("button", { type: "button", role: "radio", "aria-checked": String(v === value), class: "seg-b",
      "data-key": name + ":" + v, tip: o.iconOnly ? label : null, "aria-label": o.iconOnly ? label : null },
    iconName ? icon(iconName) : null, o.iconOnly ? null : h("span", { class: "lbl" }, label));
    b.addEventListener("click", () => {
      $$(".seg-b", wrapEl).forEach((x) => x.setAttribute("aria-checked", String(x === b)));
      onChange(v);
    });
    wrapEl.append(b);
  });
  wrapEl.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const all = $$(".seg-b", wrapEl);
    const i = all.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    const next = all[(i + (e.key === "ArrowRight" ? 1 : -1) + all.length) % all.length];
    next.focus();
    next.click();
  });
  return wrapEl;
}
// The pages that exist per project too: outside a project they are about every project, and their title says so.
export const ALL_SCOPE_PAGES = ["inbox_all", "insights_all", "automations_all", "health_all", "review_all", "agents_all"];
export function pageHead(title, sub, opts) {
  const o = opts || {};
  const all = !!S.route && ALL_SCOPE_PAGES.includes(S.route.name) && !o.noScope;
  return h("div", { class: "page-head" },
    h("div", { class: "ph-main" }, o.icon ? h("span", { class: "ph-ic" }, icon(o.icon)) : null,
      h("div", null, h("h1", { id: "view-title", tabindex: "-1" }, title, all ? h("span", { class: "h-scope" }, " · all projects") : null),
        sub ? h("p", { class: "lede" }, sub) : null),
      o.info ? infoButton(title, o.info) : null),
    o.actions ? h("div", { class: "ph-actions" }, o.actions) : null);
}
// The view choice a person made (cards or table, board or timeline), kept per view in this browser.
export function viewChoice(key, fallback) { return local.get("gf.view." + key) || fallback; }
export function setViewChoice(key, value) { local.set("gf.view." + key, value); }
