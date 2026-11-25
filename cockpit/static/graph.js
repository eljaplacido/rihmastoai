/* The Knowledge graph (FR-GRV1): a project's records, or every project's, as the ontology links them
   (kernel/graph_view.py). One filter panel scopes everything shown: kinds, relations, states, time, words and
   "only issues"; on a phone it is a sheet. The graph (graph_draw.js) and its accessible twin, the table of nodes
   and relations, show the same slice; the table is the default on a narrow screen. Click or press Enter on a
   node for its details, its links, its record, Focus here, and Ask Rihma. The filters live in the route
   (#/p/<pid>/graph?kinds=...), so Ask Rihma's Take me there opens a slice; a person saves slices as views, chooses
   the mode a view opens in, pins a slice to Home, and resets to the default. Nothing here writes a record. */

import { S, h, fill, icon, chip, api, say, button, empty, pageHead, enc, openModal, closeModal, openMenu, needPerson,
  signed, segmented, AuthError } from "./core.js";
import { drawGraph, severity, shapeOf } from "./graph_draw.js";
import { graphPanel, legend, sevChip, stateChip } from "./graph_panel.js";
import { WIDGET_DEFS, SOURCES } from "./widgets.js";

const LISTS = ["kinds", "rels", "states", "projects"];
const narrow = () => window.matchMedia("(max-width: 720px)").matches;

export function parseQuery(q) {
  const f = {};
  new URLSearchParams(q || "").forEach((v, k) => {
    if (LISTS.includes(k)) f[k] = v.split(",").filter(Boolean);
    else if (["window", "q", "focus", "hops", "issues", "limit", "audience"].includes(k)) f[k] = v;
  });
  return f;
}
export function toQuery(f) {
  const parts = [];
  LISTS.forEach((k) => { if (f[k] && f[k].length) parts.push(k + "=" + f[k].map(enc).join(",")); });
  [["window", "all"], ["q", ""], ["focus", ""], ["hops", "1"], ["limit", "300"], ["audience", "person"]].forEach(([k, d]) => {
    if (f[k] !== undefined && f[k] !== null && String(f[k]) !== d && String(f[k]) !== "") parts.push(k + "=" + enc(f[k]));
  });
  if (f.issues === true || f.issues === "1") parts.push("issues=1");
  return parts.join("&");
}
const routeBase = (pid) => (pid ? "#/p/" + enc(pid) + "/graph" : "#/graph");
function routeQuery() { const hs = location.hash || ""; const i = hs.indexOf("?"); return i < 0 ? "" : hs.slice(i + 1); }
const apiPath = (st) => (st.pid ? "/api/projects/" + enc(st.pid) + "/graph" : "/api/graph") + "?" + toQuery(st.f);
const kindLabel = (st) => (k) => ((st.model && st.model.kinds) || []).reduce((a, x) => (x.id === k ? x.label : a), k.replace("_", " "));

// -- loading and drawing ------------------------------------------------------------------------------------

async function load(st) {
  st.box.classList.add("gv-busy");
  const q = toQuery(st.f);
  if (st.box.isConnected && location.hash.split("?")[0] === routeBase(st.pid)) {
    history.replaceState(null, "", routeBase(st.pid) + (q ? "?" + q : ""));
  }
  try {
    st.model = await api("GET", apiPath(st));
    st.error = null;
  } catch (e) {
    if (e instanceof AuthError) throw e;
    st.model = null; st.error = e.message;
  }
  st.box.classList.remove("gv-busy");
  draw(st);
}
function setFilters(st, change) { st.f = Object.assign({}, st.f, change); st.selected = null; load(st).catch(() => {}); }

function summary(st) {
  const m = st.model;
  const c = m.counts || {};
  const focus = m.focus ? chip("info", "eye", "Focus: " + (m.nodes.find((n) => n.id === m.focus) || {}).short + " within " + st.f.hops + " link" + (String(st.f.hops) === "1" ? "" : "s"), { "data-control": "graph_focus" }) : null;
  const clear = m.focus ? button("Clear focus", { kind: "tiny quiet", icon: "x", onclick: () => setFilters(st, { focus: "", hops: "1" }) }) : null;
  return h("div", { class: "gv-sum" },
    h("p", { class: "muted small", "aria-live": "polite" }, c.nodes + " nodes · " + c.matching + " match · " + c.shown + " shown · " + c.edges + " links"
      + (m.scope === "factory" ? " · " + (m.projects || []).length + " projects" : "")),
    focus, clear, m.focus_missing ? chip("warning", "alert", "No node " + st.f.focus + " here: the focus is left out") : null,
    (m.issues || []).map((i) => h("button", { type: "button", class: "chip " + i.severity + " gv-iss", "aria-label": i.count + ": " + i.text + " Show only issues",
      onclick: () => setFilters(st, { issues: true }) }, icon(i.severity === "critical" ? "x-circle" : "alert"), h("span", null, i.count + " · " + i.text))));
}

function linksOf(st, n) {
  const byId = new Map(st.model.nodes.map((x) => [x.id, x]));
  return st.model.edges.filter((e) => e.from === n.id || e.to === n.id).map((e) => {
    const other = byId.get(e.from === n.id ? e.to : e.from);
    const rel = e.rel.replace(/_/g, " ");
    return h("li", null, e.from === n.id ? h("span", { class: "muted" }, rel + " ") : null,
      h("button", { type: "button", class: "linkish", onclick: () => select(st, other.id) }, other.short),
      e.to === n.id ? h("span", { class: "muted" }, " " + rel + " this") : null, e.proposed ? h("span", { class: "muted" }, " (a model's proposal)") : null);
  });
}

function focusRef(st, n) {
  const plain = n.kind === "requirement" && n.state === "open" ? n.detail.rid : n.kind === "criterion" ? n.detail.plain : n.node;
  return st.pid ? plain : n.pid + "/" + plain;
}

function details(st, n) {
  const hops = h("select", { class: "w-select", "aria-label": "Links away", "data-control": "graph_focus" },
    [1, 2, 3, 4].map((k) => h("option", { value: String(k), selected: String(k) === String(st.f.hops || 1) || null }, k + (k === 1 ? " link" : " links"))));
  const ask = button("Ask Rihma", { kind: "small quiet", icon: "message-square", onclick: async () => {
    const { openAssistant, send } = await import("./assistant.js");
    openAssistant();
    send("Explain " + (n.kind === "requirement" ? n.detail.rid : n.short) + " in the knowledge graph");
  } });
  return h("aside", { class: "gv-details card", "aria-labelledby": "gv-d-h" },
    h("header", { class: "card-head" }, h("span", { class: "gv-sw fam-" + n.family + " " + shapeOf(n.family), "aria-hidden": "true" }),
      h("h3", { class: "card-t", id: "gv-d-h", tabindex: "-1" }, n.short),
      h("span", { class: "card-tools" }, h("button", { type: "button", class: "icon-btn tiny", "aria-label": "Close the details", onclick: () => select(st, null) }, icon("x")))),
    h("p", { class: "gv-d-kind" }, kindLabel(st)(n.kind), " ", stateChip(n.state), n.issues.length ? sevChip(severity(n)) : null),
    n.issues.map((i) => h("p", { class: "gv-d-iss " + severity(n) }, icon("alert"), ((st.model.issue_kinds || []).find((x) => x.id === i) || {}).text || i)),
    h("p", { class: "gv-d-label" }, n.label),
    h("dl", { class: "kv" }, n.project && st.model.scope === "factory" ? h("div", null, h("dt", null, "Project"), h("dd", null, n.project)) : null,
      h("div", null, h("dt", null, "When"), h("dd", null, n.at ? n.at.replace("T", " ").replace("Z", " UTC") : "no time of its own")),
      h("div", null, h("dt", null, "Record"), h("dd", { class: "mono" }, n.record || "—"))),
    h("h4", { class: "gv-d-sub" }, "Links shown here"), h("ul", { class: "plain gv-links" }, linksOf(st, n)),
    h("div", { class: "btns" }, n.href ? h("a", { class: "btn small", href: n.href }, icon("arrow-right"), h("span", { class: "lbl" }, "Open the record")) : null,
      button("Focus here", { kind: "small", icon: "eye", "data-control": "graph_focus", onclick: () => setFilters(st, { focus: focusRef(st, n), hops: hops.value }) }),
      hops, ask));
}

function select(st, id) {
  st.selected = id;
  if (st.drawing) st.drawing.select(id);
  const n = id ? st.model.nodes.find((x) => x.id === id) : null;
  fill(st.side, n ? details(st, n) : null);
  st.box.classList.toggle("gv-has-details", !!n);
  if (n && st.mode === "table") { const t = st.side.querySelector("#gv-d-h"); if (t) t.focus(); }
}

function nodeTable(st) {
  const kl = kindLabel(st);
  return h("div", { class: "tbl gv-tbl" }, h("table", null, h("caption", null, "Nodes (" + st.model.nodes.length + ")"),
    h("thead", null, h("tr", null, ["Node", "Kind", "State", "Label", "Issues", "Record"].map((t) => h("th", { scope: "col" }, t)))),
    h("tbody", null, st.model.nodes.map((n) => h("tr", { "data-id": n.id, class: n.id === st.selected ? "on" : null },
      h("th", { scope: "row" }, h("button", { type: "button", class: "linkish", "aria-label": "Details of " + n.short, onclick: () => select(st, n.id) }, n.short),
        st.model.scope === "factory" ? h("div", { class: "muted small" }, n.project) : null),
      h("td", null, h("span", { class: "gv-sw fam-" + n.family + " " + shapeOf(n.family), "aria-hidden": "true" }), " " + kl(n.kind)),
      h("td", null, stateChip(n.state)), h("td", { class: "gv-lbl" }, n.label),
      h("td", null, n.issues.length ? sevChip(severity(n), n.issues.join(", ")) : h("span", { class: "muted" }, "none")),
      h("td", null, n.href ? h("a", { href: n.href, "aria-label": "Open the record of " + n.short }, "Open") : h("span", { class: "muted" }, "—")))))));
}
function edgeTable(st) {
  const byId = new Map(st.model.nodes.map((x) => [x.id, x.short]));
  return h("div", { class: "tbl gv-tbl" }, h("table", null, h("caption", null, "Relations (" + st.model.edges.length + ")"),
    h("thead", null, h("tr", null, ["From", "Relation", "To", "Known by"].map((t) => h("th", { scope: "col" }, t)))),
    h("tbody", null, st.model.edges.map((e) => h("tr", null, h("th", { scope: "row" }, byId.get(e.from)), h("td", null, e.rel.replace(/_/g, " ")),
      h("td", null, byId.get(e.to)), h("td", { class: "muted" }, e.proposed ? "a model's proposal" : e.origin.replace(/_/g, " ") + (e.ended ? ", ended" : "")))))));
}

function draw(st) {
  const m = st.model;
  st.drawing = null;
  if (!m) { fill(st.main, empty("alert", "The graph could not be read: " + (st.error || "no answer"))); fill(st.top); return; }
  if (m.outcome !== "answered") {
    fill(st.top); fill(st.main, h("div", { class: "nm-box" }, icon("dashed"), h("div", null, h("b", null, "Not measured now"),
      m.causes.map((c) => h("p", null, c)), h("p", null, "The graph is rebuilt from the records on every read; it is never shown wrong."))));
    return;
  }
  fill(st.top, summary(st));
  const a = document.activeElement;     // a filter that was used keeps the focus when the panel is drawn again
  const where = a && a.dataset && a.dataset.key ? [st.sheetBody, st.panel].find((p) => p && p.contains(a)) : null;
  if (st.sheetBody) fill(st.sheetBody, graphPanel(st, setFilters));
  fill(st.panel, graphPanel(st, setFilters));
  if (where) { const again = where.querySelector('[data-key="' + CSS.escape(a.dataset.key) + '"]'); if (again) again.focus(); }
  const search = st.bar.querySelector(".gv-search");
  if (search && document.activeElement !== search) search.value = st.f.q || "";
  const body = !m.nodes.length ? empty("filter", "Nothing matches these filters.", button("Reset filters", { kind: "small", onclick: () => setFilters(st, resetF(st)) }))
    : st.mode === "table" ? h("div", { class: "gv-tables" }, nodeTable(st), edgeTable(st))
      : (st.drawing = drawGraph(m, { kindLabel: kindLabel(st), onSelect: (id) => select(st, id), selected: st.selected })).el;
  fill(st.main, body, m.more ? h("p", { class: "viz-note gv-more" }, icon("info"), m.more.note) : null,
    (m.unmeasured || []).map((u) => h("p", { class: "viz-note" }, icon("dashed"), u.project + " is not measured now: " + u.causes.join("; "))),
    st.mode === "graph" && m.nodes.length ? legend(m) : null);
  select(st, st.selected && m.nodes.some((n) => n.id === st.selected) ? st.selected : null);
  st.box.dataset.scope = m.scope;                 // drawn: what the page and its tests wait for
  st.box.dataset.drawn = String(Number(st.box.dataset.drawn || 0) + 1);
}
// Back to no filters (across projects, the projects chosen stay): the filters are replaced, not merged.
function resetF(st) { st.f = Object.assign({ hops: "1" }, st.pid ? {} : { projects: st.f.projects || [] }); return {}; }

// -- saved views, the default mode, pinning -------------------------------------------------------------------

async function savePrefs(st, change, done) {
  if (!needPerson()) return;
  try {
    const out = await api("PUT", "/api/graph/prefs", Object.assign({ scope: st.pid || "*" }, change, signed()));
    st.prefs = out.prefs;
    say(done, "good");
  } catch (e) { if (!(e instanceof AuthError)) say("It was not saved: " + e.message, "warning"); }
}
function saveAs(st) {
  const name = h("input", { type: "text", maxlength: "60", "aria-label": "Name of the view", placeholder: "Only open requirements and their tests" });
  const go = button("Save view", { kind: "primary", icon: "check", onclick: async () => {
    const n = name.value.trim();
    if (!n) { name.focus(); return; }
    const presets = (st.prefs.presets || []).filter((p) => p.name !== n).concat([{ name: n, query: toQuery(st.f) }]);
    closeModal();
    await savePrefs(st, { presets }, "Saved “" + n + "” for you.");
  } });
  openModal("Save this graph view", h("div", { class: "gv-save" }, h("label", null, h("span", null, "Name"), name),
    h("p", { class: "muted small" }, "It keeps these filters: " + (toQuery(st.f) || "everything") + ". Saved for you only."), h("div", { class: "btns" }, go)), { icon: "filter" });
}
function presetsMenu(st, anchor) {
  const now = toQuery(st.f);
  const presets = st.prefs.presets || [];
  const mine = presets.find((p) => p.query === now);
  openMenu(anchor, [{ group: "Saved views" }].concat(presets.length ? presets.map((p) => ({ label: p.name, icon: "filter", checked: p === mine,
    onclick: () => setFilters(st, Object.assign({ hops: "1" }, parseQuery(p.query))) })) : [{ label: "None saved yet", disabled: true, onclick: () => {} }],
  [{ sep: true }, { label: "Save this view…", icon: "plus", onclick: () => saveAs(st) }],
  mine ? [{ label: "Open “" + mine.name + "” by default", icon: "check", onclick: () => savePrefs(st, { default_preset: mine.name }, "“" + mine.name + "” opens first from now on.") },
    { label: "Delete “" + mine.name + "”", icon: "x", onclick: () => savePrefs(st, { presets: presets.filter((p) => p !== mine), default_preset: st.prefs.default_preset === mine.name ? null : st.prefs.default_preset }, "Deleted.") }] : [],
  [{ sep: true }, { group: "Opens as" }], [["auto", "Table on a phone, graph elsewhere"], ["graph", "Graph"], ["table", "Table"]].map(([v, l]) => ({ label: l, checked: (st.prefs.mode || "auto") === v,
    onclick: () => savePrefs(st, { mode: v }, "The graph opens as " + l.toLowerCase() + " from now on.") })),
  [{ sep: true }, { label: "Reset to default", icon: "undo", onclick: async () => { await savePrefs(st, { reset: true }, "Back to the default view."); st.mode = narrow() ? "table" : "graph"; setFilters(st, resetF(st)); bar(st); } }]), "Saved graph views");
}
async function pin(st) {
  if (!needPerson()) return;
  const { loadLayout, saveLayout } = await import("./dashboard.js");
  try {
    const layout = JSON.parse(JSON.stringify(await loadLayout()));
    if ((layout.widgets || []).length >= 24) { say("A layout holds at most 24 widgets: remove one on Home first.", "warning"); return; }
    const mine = (st.prefs.presets || []).find((p) => p.query === toQuery(st.f));
    layout.widgets.push({ id: "graph-" + Math.random().toString(36).slice(2, 8), type: "graph", size: "M", view: "chart",
      filter: { project: st.pid || "", query: toQuery(st.f).slice(0, 280), name: mine ? mine.name.slice(0, 60) : "" } });
    await saveLayout(layout, { quiet: true });
    say("This slice of the graph is pinned to your Home layout for this lens.", "good");
  } catch (e) { if (!(e instanceof AuthError)) say("It could not be pinned: " + e.message, "warning"); }
}

function bar(st) {
  const search = h("input", { type: "search", class: "gv-search", value: st.f.q || "", placeholder: "Find in the graph", "aria-label": "Find words in the graph" });
  let t = null;
  search.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => setFilters(st, { q: search.value.trim() }), 350); });
  const filtersBtn = button("Filters", { kind: "small", icon: "filter", cls: "gv-sheet-btn", "data-control": "graph_filters", onclick: () => {
    st.sheetBody = h("div", { class: "gv-sheet" }, graphPanel(st, setFilters));
    openModal("Graph filters", st.sheetBody, { icon: "filter", onClose: () => { st.sheetBody = null; } });
  } });
  const presets = button("Saved views", { kind: "small", icon: "layers", "data-control": "graph_presets" });
  presets.setAttribute("aria-haspopup", "menu");
  presets.addEventListener("click", () => presetsMenu(st, presets));
  fill(st.bar, h("span", { class: "gv-mode", "data-control": "graph_mode" }, segmented("gv-mode", [["graph", "Graph", "graph"], ["table", "Table", "table"]],
    st.mode, (v) => { st.mode = v; draw(st); }, { label: "Show as a graph or a table" })), search, filtersBtn, presets,
  button("Pin to Home", { kind: "small quiet", icon: "plus", "data-control": "graph_pin", aria: "Pin this slice of the graph to Home", onclick: () => pin(st) }));
}

async function mount(box, pid) {
  let prefs = { mode: "auto", presets: [], default_preset: null };
  try {
    prefs = (await api("GET", "/api/graph/prefs?scope=" + enc(pid || "*") + "&person=" + enc((S.person || "").trim()))).prefs;
  } catch (e) { if (e instanceof AuthError) throw e; }
  const q = routeQuery();
  const preset = (prefs.presets || []).find((p) => p.name === prefs.default_preset);
  const st = { pid, box, prefs, f: Object.assign({ hops: "1" }, parseQuery(q || (preset ? preset.query : ""))), selected: null,
    mode: prefs.mode === "graph" || prefs.mode === "table" ? prefs.mode : (narrow() ? "table" : "graph") };
  st.bar = h("div", { class: "gv-bar" }); st.top = h("div"); st.panel = h("aside", { class: "gv-panel card", "aria-label": "Graph filters", "data-control": "graph_filters" });
  st.main = h("div", { class: "gv-main" }); st.side = h("div", { class: "gv-side" });
  fill(box, st.bar, st.top, h("div", { class: "gv-body" }, st.panel, st.main, st.side));
  bar(st);
  await load(st);
  return st;
}

export async function renderGraphPage(seq) {
  const main = document.querySelector("#main");
  if (!S.projects) { try { S.projects = await api("GET", "/api/projects"); } catch (e) { if (e instanceof AuthError) throw e; } }
  if (seq !== S.seq) return;
  document.title = "Knowledge graph · Rihmasto.ai";
  const box = h("div", { class: "gv", id: "graph" });
  fill(main, pageHead("Knowledge graph", "Every project's records as the ontology links them: what each requirement rests on, what checks it, and what is missing.",
    { icon: "graph", info: "Rebuilt from the records on every read; nothing here writes a record. Filters live in the address, so a view can be shared or saved." }), box);
  await mount(box, null);
}

// A project's Knowledge graph tab.
export function graphView(pid) {
  const box = h("div", { class: "gv", id: "graph" }, h("p", { class: "muted" }, "Reading the records…"));
  mount(box, pid).catch(() => {});
  return box;
}

// -- the Knowledge graph widget on Home: a slice, pinned from the view ------------------------------------

function widgetBody(w) {
  const f = w.filter || {};
  const box = h("div", { class: "gv-widget" });
  const href = routeBase(f.project || null) + (f.query ? "?" + f.query : "");
  fill(box, h("p", { class: "muted small" }, "Reading the records…"));
  const path = (f.project ? "/api/projects/" + enc(f.project) + "/graph" : "/api/graph") + "?" + (f.query ? f.query + "&" : "") + "limit=8";
  api("GET", path).then((m) => {
    if (m.outcome !== "answered") { fill(box, h("p", { class: "muted" }, "Not measured now: " + m.causes.join("; "))); return; }
    fill(box, h("p", { class: "gv-w-sum" }, h("b", null, (f.name || m.title || "Every project")), " · " + m.counts.matching + " nodes match"),
      (m.issues || []).map((i) => h("p", { class: "small" }, sevChip(i.severity, i.count + " · " + i.text))),
      h("ul", { class: "plain gv-w-list" }, m.nodes.map((n) => h("li", null, h("span", { class: "gv-sw fam-" + n.family + " " + shapeOf(n.family), "aria-hidden": "true" }),
        " ", h("span", { class: "mono" }, n.short), " ", h("span", { class: "muted" }, n.label.slice(0, 60))))),
      m.more ? h("p", { class: "muted small" }, m.more.count + " more") : null,
      h("p", { class: "viz-note" }, icon("graph"), h("a", { href }, "Open in the Knowledge graph")));
  }).catch((e) => {
    if (!(e instanceof AuthError)) fill(box, h("div", { class: "nm-box err", role: "note" }, icon("alert"), h("div", null, h("b", null, "Could not be read"), h("p", null, e.message))));
  });
  return box;
}
WIDGET_DEFS.graph = { views: ["chart"], render: (d, w) => widgetBody(w), table: (d, w) => widgetBody(w) };
SOURCES.graph = "kernel.graph_view: a slice of the knowledge graph, rebuilt from the records on every read.";
