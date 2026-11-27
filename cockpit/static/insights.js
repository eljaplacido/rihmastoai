/* Insights (FR-INS1): health, compliance, governance, security, context drift, QA and usage, counted from the
   records (kernel/insights). One filter row above everything it scopes: the dimension, the window and the scope
   (the factory or one project). Stat tiles first, each with its one-line insight and a link to the records,
   then the charts, each with a table twin, then what is not measured here and how to get it measured. A figure
   that is not measured says so, never zero. The same view is a project's Insights tab, and any tile can be
   pinned to Home as a widget. Nothing here writes a record; Export saves a file and sends nothing anywhere. */

import {
  S, $, h, fill, icon, api, say, button, empty, pageHead, infoButton, enc, local, localJSON, openMenu, needPerson,
  AuthError,
} from "./core.js";
import { columns, bars, stack100, dataTable, SERIES, STATUS_MARK } from "./charts.js";
import { WIDGET_DEFS, SOURCES } from "./widgets.js";
import { technical, insightWord, insightTab, leadLine, measureHow, pick } from "./words.js";
import { workCard } from "./workbalance.js";   // where the work went, across projects (FR-STR1)

const STORE = "gf.insights";
const WINDOW_LABEL = { "24h": "24 h", "7d": "7 days", "30d": "30 days", all: "All" };
const DIMS = [["health", "Health"], ["compliance", "Compliance"], ["governance", "Governance"], ["security", "Security"],
  ["drift", "Context drift"], ["qa", "QA"], ["usage", "Usage"]];
const STATUS_WORD = { good: ["check-circle", "Good"], warning: ["alert", "Needs a look"], serious: ["alert", "Serious"],
  critical: ["x-circle", "Critical"] };
const FORMATS = [["json", "JSON (the read models)"], ["csv", "CSV (one row per figure)"],
  ["otlp-json", "OpenTelemetry JSON (metrics and GenAI spans)"]];

function prefs() {
  const p = localJSON(STORE, {}) || {};
  return { dimension: DIMS.some((d) => d[0] === p.dimension) ? p.dimension : "health",
    window: WINDOW_LABEL[p.window] ? p.window : "7d", project: typeof p.project === "string" ? p.project : "" };
}
function keep(p) { local.set(STORE, JSON.stringify(p)); }

// The colour of each series: a status colour where the series means good or bad, else the categorical slots
// in their fixed order (never cycled; the read models fold anything past six into fewer series).
function colored(series) {
  let slot = 0;
  return (series || []).map((s) => Object.assign({}, s, {
    color: s.status ? STATUS_MARK[s.status] : s.neutral ? STATUS_MARK.neutral : s.hatch ? null : SERIES(++slot),
    icon: s.status ? (STATUS_WORD[s.status] || [])[0] : null,
  }));
}

function chartBody(c) {
  const series = colored(c.series);
  if (c.kind === "columns") {
    return columns({ series, rows: c.rows.map((r) => ({ label: r.label, short: r.label, values: r.values })), height: 150 });
  }
  if (c.kind === "stack100") {
    return stack100({ series, rows: c.rows,
      summary: (r, total) => total.toLocaleString("en-US") + " " + (total === 1 ? c.unit.replace(/s$/, "") : c.unit) });
  }
  const suffix = { "%": "%", hours: " h", days: " d" }[c.unit] || "";
  return bars({ rows: c.rows.map((r) => Object.assign({}, r, { display: r.value === null || r.value === undefined ? null
    : Number(r.value).toLocaleString("en-US") + suffix })), unit: c.unit });
}

function chartTable(c) {
  if (c.kind === "bars") {
    return dataTable([{ label: "Item", key: "label" }, { label: c.unit ? "Value (" + c.unit + ")" : "Value", num: true,
      value: (r) => (r.value === null || r.value === undefined ? null : Number(r.value).toLocaleString("en-US")) }], c.rows, c.title);
  }
  return dataTable([{ label: c.kind === "columns" ? "When" : "Row", key: "label" }].concat((c.series || []).map((s) => ({
    label: s.label, num: true, value: (r) => Number((r.values || {})[s.key] || 0).toLocaleString("en-US") }))), c.rows, c.title);
}

function notMeasured(why, how) {
  // "nothing failed in the window" is a count of none, not a missing measurement
  if (/^nothing to do/i.test(String(how || ""))) {
    return h("div", { class: "nm-box ins-nm" }, icon("check-circle"), h("div", null,
      h("b", null, pick("None in this period", "None in the window")), h("p", null, cap(String(why || "")) + ".")));
  }
  const way = measureHow(how);
  return h("div", { class: "nm-box ins-nm" }, icon("dashed"), h("div", null, h("b", null, "Not measured"),
    h("p", null, why + "."), way ? h("p", { class: "ins-how" }, "To measure it: " + way + ".") : null));
}
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);
// A tile's or chart's one line in the reader's words: no ranking sentence about a count, no "every project" on one.
function lineOf(line, model) {
  const t = model && model.project && line === "Every project is on track." ? "This project is on track." : String(line || "");
  return technical() ? t : leadLine(t);
}
// A tile's small line: "0 at error" beside a big 1 reads as 10, so a business reader gets words.
function subOf(t) {
  const s = String(t.sub || "");
  if (technical()) return s;
  const e = /^(\d+) at error$/.exec(s);
  if (e) return e[1] === "0" ? "none serious" : e[1] + " serious";
  const r = /^(\d+) refused in the window$/.exec(s);
  if (r) return r[1] === "0" ? "nothing held back" : r[1] + " held back from a cloud AI";
  return s;
}
// An accepted risk is a choice a person made, not good news: its count carries no Good or Critical word.
const NEUTRAL_TILES = new Set(["accepted_risks"]);

function chartCard(c, uid) {
  const id = "ic-" + uid + "-" + c.key;
  const body = h("div", { class: "ins-chart-body", "data-ud": "" });   // the figure's own labels, as kernel/insights computes them
  let view = "chart";
  const draw = () => fill(body, !c.measured ? notMeasured(c.why, c.how) : view === "table" ? chartTable(c) : chartBody(c));
  const toggle = c.measured ? h("span", { class: "view-toggle", role: "group", "aria-label": "View of " + c.title },
    ["chart", "table"].map((v) => {
      const b = h("button", { type: "button", class: "icon-btn tiny" + (v === view ? " on" : ""), "aria-pressed": String(v === view),
        "aria-label": (v === "chart" ? "Chart" : "Table") + " view of " + c.title, tip: v === "chart" ? "Chart view" : "Table view" },
      icon(v === "chart" ? "bar-chart" : "table"));
      b.addEventListener("click", () => {
        view = v;
        toggle.querySelectorAll("button").forEach((x) => { const on = x === b; x.classList.toggle("on", on); x.setAttribute("aria-pressed", String(on)); });
        draw();
      });
      return b;
    })) : null;
  draw();
  return h("section", { class: "card ins-chart", "aria-labelledby": id, "data-chart": c.key },
    h("header", { class: "card-head" }, h("h3", { class: "card-t", id }, insightWord(c.key, c.title)),
      infoButton(c.title, h("p", { class: "muted" }, "Where it comes from: " + c.basis + ".")), h("span", { class: "card-tools" }, toggle)),
    c.measured ? h("p", { class: "ins-line", "data-ud": "" }, lineOf(c.line, c.model)) : null, body);   // not measured: the box says why, once
}

function deltaLine(t) {
  const d = t.delta;
  // the line already says the change against the window before: the delta is not said twice
  if (!d || d.value === 0 || d.value === null || String(t.line || "").includes(" against " + d.vs)) return null;
  const up = d.value > 0;
  const amount = d.pct !== null && d.pct !== undefined ? Math.abs(d.pct) + "%" : Math.abs(d.value).toLocaleString("en-US");
  return h("span", { class: "ins-delta" }, h("span", { "aria-hidden": "true" }, up ? "↑ " : "↓ "),
    (up ? "up " : "down ") + amount + " against " + d.vs);
}

function tileCard(t, model, opts) {
  const st = t.status && !(NEUTRAL_TILES.has(t.key) && !technical()) && STATUS_WORD[t.status];
  const label = insightWord(t.key, t.label);
  const how = measureHow(t.how);
  const sub = subOf(t);
  const records = t.href ? h("a", { class: "ins-rec", href: t.href }, icon("arrow-right"), "Open the records") : null;
  const pin = opts && opts.pin ? button("Pin to Home", { kind: "small quiet", icon: "plus", "data-control": "insights_pin",
    aria: "Pin " + t.label + " to Home", onclick: () => pinTile(t, model) }) : null;
  return h("article", { class: "kpi ins-tile" + (t.measured ? "" : " nm"), "data-tile": t.key, "aria-label": label },
    h("div", { class: "kpi-h" }, h("span", null, label), infoButton(label, h("p", { class: "muted" }, "Where it comes from: " + t.basis + "."))),
    t.measured ? h("div", { class: "kpi-v" }, t.display, sub ? h("small", null, " " + sub) : null)
      : h("div", { class: "kpi-v nm-text" }, "— Not measured"),
    st ? h("span", { class: "ins-status " + t.status }, icon(st[0]), st[1]) : null,
    deltaLine(t),
    h("p", { class: "kpi-sub ins-line", "data-ud": "" }, lineOf(t.line, opts && opts.model)),
    !t.measured && how ? h("p", { class: "kpi-sub ins-how" }, "To measure it: " + how + ".") : null,
    records || pin ? h("div", { class: "ins-actions" }, records, pin) : null);
}

function gapsList(gaps) {
  if (!gaps.length) return null;
  return h("section", { class: "card ins-gaps", "aria-labelledby": "ins-gaps-h" }, h("h3", { class: "card-t", id: "ins-gaps-h" }, "Not measured here"),
    h("ul", { "data-ud": "" }, gaps.map((g) => h("li", null, h("b", null, g.what), h("span", null, ": " + g.why + ". "),
      measureHow(g.how) ? h("span", { class: "ins-how" }, "To measure it: " + measureHow(g.how) + ".") : null))));
}

function saveText(text, name, type) {
  const a = h("a", { href: URL.createObjectURL(new Blob([text], { type: type || "application/json" })), download: name });
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
}

async function exportAs(fmt, p, pid) {
  const q = "/api/insights/export?format=" + enc(fmt) + "&dimension=" + enc(p.dimension) + "&window=" + enc(p.window)
    + (pid ? "&project=" + enc(pid) : "");
  try {
    const out = await api("GET", q);
    saveText(out.text, out.filename, out.media_type);
    say("Saved " + out.filename + ". Nothing was sent anywhere: send it to your own tools.", "good");
  } catch (e) {
    if (!(e instanceof AuthError)) say("The export did not work: " + e.message, "warning");
  }
}

function exportButton(p, pid) {
  const b = button("Export", { icon: "download", "data-control": "insights_export", aria: "Export these insights" });
  b.setAttribute("aria-haspopup", "menu");
  b.addEventListener("click", () => openMenu(b, [{ group: "Save as a file" }].concat(FORMATS.map(([f, label]) => ({
    label, icon: "download", onclick: () => exportAs(f, p, pid) }))), "Export"));
  return b;
}

async function pinTile(t, model) {
  if (!needPerson()) return;
  const { loadLayout, saveLayout } = await import("./dashboard.js");
  try {
    const layout = JSON.parse(JSON.stringify(await loadLayout()));
    if ((layout.widgets || []).length >= 24) { say("A layout holds at most 24 widgets: remove one on Home first.", "warning"); return; }
    layout.widgets.push({ id: "insight-" + Math.random().toString(36).slice(2, 8), type: "insight", size: "S", view: "chart",
      filter: { dimension: model.dimension, key: t.key, window: model.window, project: model.project || "" } });
    await saveLayout(layout, { quiet: true });
    say(t.label + " is pinned to your Home layout for this lens.", "good");
  } catch (e) {
    if (!(e instanceof AuthError)) say("It could not be pinned: " + e.message, "warning");
  }
}

function segmented(label, attrs, items, current, onpick) {
  return h("div", Object.assign({ class: "ins-seg", role: "group", "aria-label": label }, attrs),
    items.map(([id, text]) => h("button", { type: "button", class: "seg-b" + (id === current ? " on" : ""), "aria-pressed": String(id === current),
      onclick: () => onpick(id) }, text)));
}

function filters(p, fixedPid, redraw) {
  const pick = (k) => (v) => { p[k] = v; keep(p); redraw(); };
  const scope = fixedPid ? null : h("label", { class: "ins-scope" }, h("span", null, "Scope"),
    h("select", { class: "w-select", "data-control": "insights_scope", "aria-label": "Scope: the factory or one project",
      onchange: (e) => pick("project")(e.target.value) },
    h("option", { value: "", selected: !p.project || null }, "All projects"),
    (S.projects || []).filter((x) => !x.factory).map((x) => h("option", { value: x.id, selected: x.id === p.project || null }, x.title))));
  return h("div", { class: "ins-filters" },
    segmented("Dimension", { "data-control": "insights_dimension" }, DIMS.map(([id, l]) => [id, insightTab(id, l)]), p.dimension, pick("dimension")),
    segmented("Window", { "data-control": "insights_window" }, Object.entries(WINDOW_LABEL), p.window, pick("window")), scope);
}

function modelView(model, opts) {
  const uid = (model.project || "factory").replace(/[^a-z0-9-]/g, "") + "-" + model.dimension;
  const where = model.project_title ? model.project_title : "the whole factory (" + model.projects + " project" + (model.projects === 1 ? "" : "s") + ")";
  // a business reader of Usage wants one answer first: what the AI cost in this period
  const cost = model.dimension === "usage" && !technical() ? (model.tiles || []).find((t) => t.key === "cost") : null;
  return h("div", { class: "ins-model", "data-dimension": model.dimension },
    h("p", { class: "ins-sum muted" }, h("b", null, insightTab(model.dimension, model.label)), " · " + where + " · " + model.window_words),
    cost ? h("p", { class: "ins-lead" }, h("b", null, "AI cost this period: "),
      cost.measured ? String(cost.display || cost.value) : "not known (prices not set by IT)") : null,
    h("div", { class: "kpi-strip ins-tiles" }, model.tiles.map((t) => tileCard(t, model, Object.assign({ model }, opts)))),
    h("div", { class: "ins-charts" }, model.charts.map((c) => chartCard(Object.assign({ model }, c), uid))),
    // how the cockpit keeps its background work is a developer's concern
    gapsList(technical() ? model.gaps : model.gaps.filter((g) => !/cockpit's memory/.test(g.why || ""))));
}

// The insights of one scope, drawn into `box`, with the filter row above them. `fixedPid` is a project's own tab.
async function drawInto(box, fixedPid) {
  const p = prefs();
  const pid = fixedPid || p.project || null;
  const redraw = () => drawInto(box, fixedPid);
  const q = "/api/insights?dimension=" + enc(p.dimension) + "&window=" + enc(p.window) + (pid ? "&project=" + enc(pid) : "");
  box.classList.add("ins-busy");
  let model;
  try {
    model = await api("GET", q);
  } catch (e) {
    if (e instanceof AuthError) throw e;
    if (pid && !fixedPid) { p.project = ""; keep(p); return redraw(); }   // a project that is gone: back to the factory
    fill(box, filters(p, fixedPid, redraw), empty("alert", "The insights could not be read: " + e.message));
    box.classList.remove("ins-busy");
    return null;
  }
  fill(box, h("div", { class: "ins-bar" }, filters(p, fixedPid, redraw), exportButton(p, pid)), modelView(model, { pin: true }));
  box.classList.remove("ins-busy");
  return model;
}

export async function renderInsights(seq) {
  const main = $("#main");
  if (!S.projects) { try { S.projects = await api("GET", "/api/projects"); } catch (e) { if (e instanceof AuthError) throw e; } }
  if (seq !== S.seq) return;
  document.title = "Insights · Rihmasto";
  const box = h("div", { class: "ins", id: "insights" });
  fill(main, pageHead("Insights", "Health, compliance, governance, security, context drift, QA and usage, counted from the "
    + "records. Nothing is estimated: what has no record says not measured, and how to measure it.", { icon: "insight",
    info: "Rihmasto is the system of record for decisions and evidence, not for telemetry (D-0017). Export saves these "
      + "figures as JSON, CSV or OpenTelemetry JSON for your own observability tools; nothing is sent anywhere." }), workCard(null), box);
  await drawInto(box, null);
}

// A project's Insights tab: the same view, its scope fixed to the project.
export function insightsView(pid) {
  const box = h("div", { class: "ins", id: "insights" }, h("p", { class: "muted" }, "Reading the records…"));
  drawInto(box, pid).catch(() => {});
  return box;
}

// -- the Insight widget on Home: one tile, pinned from here ------------------------------------------------

function widgetBody(w) {
  const f = w.filter || {};
  const box = h("div", { class: "ins-widget" });
  if (!f.dimension || !f.key) {
    fill(box, empty("insight", "Pin a figure from Insights to show it here.", h("a", { href: "#/insights", class: "more-link" }, "Open Insights")));
    return box;
  }
  const q = "/api/insights/tile?dimension=" + enc(f.dimension) + "&key=" + enc(f.key) + "&window=" + enc(f.window || "7d")
    + (f.project ? "&project=" + enc(f.project) : "");
  fill(box, h("p", { class: "muted small" }, "Reading the records…"));
  api("GET", q).then((out) => {
    const where = (out.project_title || "the factory") + " · " + (WINDOW_LABEL[out.window] || out.window);
    fill(box, tileCard(out.tile, { dimension: out.dimension }, { pin: false }), h("p", { class: "viz-note" }, icon("insight"),
      h("a", { href: out.project ? "#/p/" + enc(out.project) + "/insights" : "#/insights" }, out.label + " · " + where)));
  }).catch((e) => {
    if (!(e instanceof AuthError)) fill(box, h("div", { class: "nm-box err", role: "note" }, icon("alert"),
      h("div", null, h("b", null, "Could not be read"), h("p", null, e.message + ". Nothing here means zero."))));
  });
  return box;
}

WIDGET_DEFS.insight = { views: ["chart"], render: (d, w) => widgetBody(w), table: (d, w) => widgetBody(w) };
SOURCES.insight = "kernel.insights: one figure from Insights, counted from the records; not measured is never zero.";
