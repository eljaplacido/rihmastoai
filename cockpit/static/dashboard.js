/* Home: the dashboard for the active lens. A layout is versioned JSON kept on the server per person,
   persona and lens ({v:1, lens, widgets:[{id,type,size,view,filter}], theme}); localStorage is only a
   cache. The lens presets are read-only: the first edit duplicates the preset into a personal layout,
   with "Reset to default". Customize mode: drag to reorder (or Alt+arrows), cycle the size, remove,
   add from the library, Ctrl+Z to undo, Esc to cancel, Done to save. */

import {
  S, $, $$, h, icon, fill, api, act, say, needPerson, nav, enc, local, localJSON, button, iconButton, infoButton,
  openMenu, pageHead, empty, skeleton, chip, ACCENTS,
} from "./core.js";
import { WIDGET_DEFS, SOURCES } from "./widgets.js";

const SIZES = ["S", "M", "L", "XL"];
const SIZE_LABEL = { S: "Small", M: "Medium", L: "Wide", XL: "Wide and tall" };
const VIEW_LABEL = { chart: "Chart", table: "Table", list: "List" };
const VIEW_ICON = { chart: "bar-chart", table: "table", list: "list" };
export const THEME_DEFAULT = { accent: "amber", density: "comfortable", mode: "system", radius: "soft", font_scale: 1 };
const UNDO_LIMIT = 20;

const C = { snapshot: null, undo: [], preview: null, drag: null };

function phone() { return window.matchMedia("(max-width: 760px)").matches; }
function clone(x) { return JSON.parse(JSON.stringify(x)); }
function widgetInfo(type) { return ((S.meta && S.meta.widgets) || {})[type] || { title: type, icon: "info", question: "" }; }
function cacheKey() { return "gf.layout." + (S.person.trim() || "-") + "." + S.persona + "." + S.lens; }

// -- the theme: accent, density, mode, radius and font scale, from fixed sets ---------------------

export function currentTheme() {
  const t = Object.assign({}, THEME_DEFAULT, localJSON("gf.theme", {}), (S.layout && !S.layoutPreset && S.layout.theme) || {});
  return t;
}
export function applyTheme(theme) {
  const t = Object.assign({}, THEME_DEFAULT, theme || {});
  const root = document.documentElement;
  const dark = t.mode === "dark" || (t.mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  root.setAttribute("data-theme", dark ? "dark" : "light");
  root.setAttribute("data-accent", ACCENTS.includes(t.accent) ? t.accent : "amber");
  root.setAttribute("data-density", t.density === "compact" ? "compact" : "comfortable");
  root.setAttribute("data-radius", t.radius === "crisp" ? "crisp" : "soft");
  const fs = Math.min(1.25, Math.max(0.9, Number(t.font_scale) || 1));
  root.style.setProperty("--fs-scale", String(fs));
  root.style.fontSize = (14 * fs) + "px";
  S.theme = t;
  const themeBtn = $("#theme");
  if (themeBtn) {
    themeBtn.querySelector("use").setAttribute("href", "#i-" + (t.mode === "dark" ? "moon" : t.mode === "light" ? "sun" : "monitor"));
    themeBtn.setAttribute("aria-label", "Theme: " + t.mode);
  }
  const dens = $("#density");
  if (dens) {
    dens.querySelector("use").setAttribute("href", "#i-" + (t.density === "compact" ? "rows-compact" : "rows"));
    dens.setAttribute("aria-label", "Density: " + t.density);
  }
}
// A theme change the person makes: applied, cached, and saved with the lens's layout when there is a person.
export async function setTheme(changes, opts) {
  const t = Object.assign({}, currentTheme(), changes);
  applyTheme(t);
  local.set("gf.theme", JSON.stringify(t));
  if (opts && opts.save === false) return;
  if (S.layout && S.person.trim()) {
    const layout = clone(S.layout);
    layout.theme = t;
    await saveLayout(layout, { quiet: true });
  }
}

// -- loading and saving layouts -------------------------------------------------------------------

export async function loadLayout() {
  const q = "/api/layout?persona=" + enc(S.persona) + "&lens=" + enc(S.lens) + "&person=" + enc(S.person.trim());
  try {
    const out = await api("GET", q);
    S.layout = out.layout;
    S.layoutPreset = out.preset;
    S.layoutDefault = out.default;
    local.set(cacheKey(), JSON.stringify(out));
  } catch (e) {
    const cached = localJSON(cacheKey(), null);
    if (!cached) throw e;
    S.layout = cached.layout;
    S.layoutPreset = cached.preset;
    S.layoutDefault = cached.default;
  }
  return S.layout;
}

export async function saveLayout(layout, opts) {
  const o = opts || {};
  if (!S.person.trim()) {
    if (!o.quiet) needPerson();
    return false;
  }
  const out = await api("PUT", "/api/layout?persona=" + enc(S.persona) + "&lens=" + enc(S.lens),
    { person: S.person.trim(), layout });
  S.layout = out.layout;
  S.layoutPreset = false;
  const kind = $(".layout-kind");
  if (kind) kind.textContent = "Your layout";
  local.set(cacheKey(), JSON.stringify({ layout: out.layout, preset: false, default: S.layoutDefault }));
  if (!o.quiet) say("Your " + lensLabel() + " layout is saved for " + S.person.trim() + ".", "good");
  return true;
}
function lensLabel() { return (((S.meta && S.meta.lenses) || {})[S.lens] || {}).label || S.lens; }

// An edit outside Customize (a widget's menu): saved at once; the first edit makes the layout personal.
async function editLayout(fn) {
  const layout = clone(S.layout);
  fn(layout);
  if (!S.person.trim()) {
    S.layout = layout;
    renderGrid();
    say("Shown for now. Set your name to keep it: a layout is saved per person.", "warning");
    return;
  }
  await act(null, async () => { await saveLayout(layout, { quiet: true }); });
  renderGrid();
}
nav.setWidgetFilter = (id, filter) => editLayout((l) => { const w = l.widgets.find((x) => x.id === id); if (w) w.filter = filter; });

// -- rendering ------------------------------------------------------------------------------------

export async function renderHome(seq) {
  const main = $("#main");
  const done = skeleton(main, "the dashboard");
  const [d] = await Promise.all([api("GET", "/api/dashboard"), loadLayout()]);
  done();
  if (seq !== S.seq) return;
  S.dashboard = d;
  applyTheme(currentTheme());
  const lens = ((S.meta && S.meta.lenses) || {})[S.lens] || {};
  document.title = lens.label + " · Home · Rihmasto.ai";
  fill(main,
    pageHead(lens.label ? lens.label + " view" : "Home", lens.question || "", {
      icon: null,
      actions: [h("span", { class: "fresh-note muted small" }, h("span", { class: "layout-kind" }, S.layoutPreset ? "Default layout" : "Your layout"),
        " · updated " + String(d.generated_at || "").slice(11, 16) + " UTC"),
        button("Refresh", { icon: "refresh", kind: "quiet", onclick: () => nav.route && nav.route(true) })],
    }),
    h("div", { class: "cz-bar", id: "cz-bar", hidden: true }),
    h("div", { class: "preview-bar", id: "preview-bar", hidden: true }),
    h("div", { class: "grid", id: "grid", role: "list", "aria-label": "Dashboard widgets" }),
    d.problems && d.problems.length ? h("p", { class: "muted small" }, "Some read models could not be read: " + d.problems.join(", ")) : null);
  renderGrid();
  if (S.customizing) startCustomize(true);
  if (C.preview) showPreviewBar();
}

export function renderGrid() {
  const grid = $("#grid");
  if (!grid || !S.layout) return;
  const d = S.dashboard || {};
  const widgets = S.layout.widgets || [];
  if (!widgets.length) {
    fill(grid, h("div", { class: "grid-empty" }, empty("sliders", "This layout has no widgets.",
      button("Add a widget", { icon: "plus", kind: "primary", onclick: () => { if (!S.customizing) toggleCustomize(); openLibrary(); } }))));
    return;
  }
  fill(grid, widgets.map((w, i) => widgetCard(w, i, d)));
}

function widgetCard(w, index, d) {
  const def = WIDGET_DEFS[w.type];
  const info = widgetInfo(w.type);
  const views = def ? def.views : ["chart", "table"];
  const view = views.includes(w.view) ? w.view : views[0];
  const wv = Object.assign({}, w, { view });
  let body;
  try {
    body = !def ? empty("info", "This widget is not in the library.")
      : view === "table" ? def.table(d, wv) : def.render(d, wv);
  } catch (e) {
    body = empty("alert", "This widget could not be drawn: " + e.message);
  }
  const custom = S.customizing && !phone();
  const tools = [];
  if (views.length > 1 && !custom) {
    const other = views.filter((v) => v !== view);
    tools.push(h("span", { class: "view-toggle", role: "group", "aria-label": "View" }, views.map((v) =>
      h("button", { type: "button", class: "icon-btn tiny" + (v === view ? " on" : ""), "aria-pressed": String(v === view),
        "aria-label": VIEW_LABEL[v] + " view", tip: VIEW_LABEL[v] + " view",
        onclick: () => editLayout((l) => { const x = l.widgets.find((y) => y.id === w.id); if (x) x.view = v; }) }, icon(VIEW_ICON[v])))));
    void other;
  }
  if (!phone() && !custom) {
    const more = h("button", { type: "button", class: "icon-btn tiny", "aria-label": "Widget menu: " + info.title, "aria-haspopup": "menu", "aria-expanded": "false" }, icon("more"));
    more.addEventListener("click", () => openMenu(more, [{ group: "View" }].concat(views.map((v) => ({ label: VIEW_LABEL[v], icon: VIEW_ICON[v], checked: v === view,
      onclick: () => editLayout((l) => { const x = l.widgets.find((y) => y.id === w.id); if (x) x.view = v; }) })),
    [{ sep: true }, { group: "Size" }], SIZES.map((s) => ({ label: SIZE_LABEL[s] + " (" + s + ")", checked: s === w.size,
      onclick: () => editLayout((l) => { const x = l.widgets.find((y) => y.id === w.id); if (x) x.size = s; }) })),
    [{ sep: true }, { label: "Remove from this layout", icon: "x", danger: true,
      onclick: () => editLayout((l) => { l.widgets = l.widgets.filter((y) => y.id !== w.id); }) }]), "Widget menu"));
    tools.push(more);
  }
  if (custom) {
    tools.push(h("button", { type: "button", class: "btn tiny", "aria-label": "Size " + w.size + ": change", tip: "Cycle the size: S, M, L, XL",
      onclick: () => czEdit((l) => { const x = l.widgets[index]; x.size = SIZES[(SIZES.indexOf(x.size) + 1) % SIZES.length]; }) }, icon("expand"), w.size),
    h("button", { type: "button", class: "icon-btn tiny", "aria-label": "Remove " + info.title, tip: "Remove",
      onclick: () => czEdit((l) => { l.widgets.splice(index, 1); }) }, icon("x")));
  }
  const el = h("section", { class: "widget card size-" + w.size + (custom ? " cz" : ""), role: "listitem", "data-wid": w.id, "data-type": w.type,
    "aria-labelledby": "wt-" + w.id, tabindex: custom ? "0" : null, draggable: custom ? "true" : null },
  h("header", { class: "card-head" },
    custom ? h("span", { class: "grip", "aria-hidden": "true" }, icon("grip")) : null,
    h("span", { class: "card-ic" }, icon(info.icon)),
    h("h3", { class: "card-t", id: "wt-" + w.id }, info.title),
    infoButton(info.title, h("div", null, h("p", null, h("b", null, info.question)), h("p", { class: "muted" }, SOURCES[w.type] || ""))),
    h("span", { class: "card-tools" }, tools)),
  h("div", { class: "card-body" + (custom ? " inert" : "") }, body));
  if (custom) wireDrag(el, index);
  return el;
}

// -- customize ------------------------------------------------------------------------------------

export function toggleCustomize() {
  if (phone()) { say("Customizing is for wider screens.", "info"); return; }
  if (S.customizing) { finishCustomize(false); return; }
  if (!S.route || S.route.name !== "home") { location.hash = "#/home"; S.customizing = true; return; }
  startCustomize(false);
}

function startCustomize(resume) {
  S.customizing = true;
  if (!resume || !C.snapshot) { C.snapshot = clone(S.layout); C.undo = []; }
  document.documentElement.classList.add("customizing");
  const btn = $("#customize");
  if (btn) btn.setAttribute("aria-pressed", "true");
  const bar = $("#cz-bar");
  if (bar) {
    bar.hidden = false;
    fill(bar, h("span", { class: "cz-t" }, icon("sliders"), h("b", null, "Customizing your " + lensLabel() + " layout"),
      h("span", { class: "muted small" }, S.layoutPreset ? "The default stays as it is; Done saves your own copy." : "Drag to reorder, or Alt+arrows on a focused widget.")),
    h("span", { class: "cz-a" },
      button("Add widget", { icon: "plus", kind: "small", onclick: openLibrary }),
      button("Undo", { icon: "undo", kind: "small quiet", aria: "Undo (Ctrl+Z)", onclick: undo }),
      button("Reset to default", { kind: "small quiet", onclick: () => czEdit((l) => { l.widgets = clone((S.layoutDefault || l).widgets); }) }),
      button("Export", { icon: "download", kind: "small quiet", onclick: exportLayout }),
      button("Import", { icon: "upload", kind: "small quiet", onclick: importLayout }),
      button("Cancel", { kind: "small quiet", onclick: () => finishCustomize(false) }),
      button("Done", { icon: "check", kind: "small primary", onclick: () => finishCustomize(true) })));
  }
  renderGrid();
}

async function finishCustomize(save) {
  if (save) {
    const ok = await act($("#cz-bar"), async () => saveLayout(S.layout));
    if (!ok) return;
  } else if (C.snapshot) {
    S.layout = C.snapshot;
  }
  S.customizing = false;
  C.snapshot = null;
  C.undo = [];
  document.documentElement.classList.remove("customizing");
  const btn = $("#customize");
  if (btn) btn.setAttribute("aria-pressed", "false");
  const bar = $("#cz-bar");
  if (bar) bar.hidden = true;
  closeLibrary();
  renderGrid();
}

function czEdit(fn, focusId) {
  C.undo.push(clone(S.layout));
  if (C.undo.length > UNDO_LIMIT) C.undo.shift();
  const layout = clone(S.layout);
  fn(layout);
  S.layout = layout;
  renderGrid();
  if (focusId) { const el = document.querySelector('[data-wid="' + CSS.escape(focusId) + '"]'); if (el) el.focus(); }
}
function undo() {
  if (!C.undo.length) { say("Nothing to undo.", "info"); return; }
  S.layout = C.undo.pop();
  renderGrid();
}

function wireDrag(el, index) {
  el.addEventListener("dragstart", (e) => { C.drag = index; el.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(index)); });
  el.addEventListener("dragend", () => { el.classList.remove("dragging"); $$(".widget.drop").forEach((x) => x.classList.remove("drop")); });
  el.addEventListener("dragover", (e) => { e.preventDefault(); el.classList.add("drop"); });
  el.addEventListener("dragleave", () => el.classList.remove("drop"));
  el.addEventListener("drop", (e) => {
    e.preventDefault();
    const from = C.drag;
    C.drag = null;
    if (from === null || from === index) return;
    czEdit((l) => { const [w] = l.widgets.splice(from, 1); l.widgets.splice(index, 0, w); });
  });
  el.addEventListener("keydown", (e) => {
    if (!e.altKey || e.target !== el) return;
    const dir = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 }[e.key];
    if (!dir) return;
    e.preventDefault();
    const to = index + dir;
    if (to < 0 || to >= S.layout.widgets.length) return;
    const id = S.layout.widgets[index].id;
    czEdit((l) => { const [w] = l.widgets.splice(index, 1); l.widgets.splice(to, 0, w); }, id);
  });
}

export function customizeKeys(e) {
  if (!S.customizing) return false;
  if ((e.ctrlKey || e.metaKey) && (e.key === "z" || e.key === "Z")) { e.preventDefault(); undo(); return true; }
  if (e.key === "Escape" && !$("#modal").open) {
    if ($("#library") && !$("#library").hidden) { closeLibrary(); return true; }
    e.preventDefault();
    finishCustomize(false);
    return true;
  }
  return false;
}

// The library drawer: every widget with its question, searchable.
function openLibrary() {
  let lib = $("#library");
  if (!lib) {
    lib = h("aside", { class: "library", id: "library", "aria-labelledby": "lib-h" });
    document.body.append(lib);
  }
  const q = h("input", { type: "search", placeholder: "Search widgets", "aria-label": "Search widgets", class: "lib-q" });
  const list = h("ul", { class: "lib-list" });
  const draw = () => {
    const term = q.value.trim().toLowerCase();
    const all = Object.entries((S.meta && S.meta.widgets) || {});
    fill(list, all.filter(([k, v]) => !term || (k + " " + v.title + " " + v.question).toLowerCase().includes(term)).map(([k, v]) => {
      const n = (S.layout.widgets || []).filter((w) => w.type === k).length;
      const add = button("Add", { icon: "plus", kind: "small", onclick: () => {
        if ((S.layout.widgets || []).length >= ((S.meta.layout || {}).max_widgets || 24)) { say("A layout holds at most 24 widgets.", "warning"); return; }
        const id = k + "-" + Math.random().toString(36).slice(2, 7);
        czEdit((l) => { l.widgets.push({ id, type: k, size: k === "kpi_strip" || k === "timeline" || k === "evidence_packs" ? "L" : "M", view: WIDGET_DEFS[k].views[0], filter: {} }); }, id);
        draw();
      } });
      return h("li", { class: "lib-item" }, h("span", { class: "card-ic" }, icon(v.icon)),
        h("div", null, h("b", null, v.title), h("p", null, v.question), n ? h("small", { class: "muted" }, "On this layout " + (n > 1 ? n + " times" : "already")) : null), add);
    }));
  };
  q.addEventListener("input", draw);
  fill(lib, h("div", { class: "lib-head" }, h("h2", { id: "lib-h" }, "Widget library"), iconButton("x", "Close the library", closeLibrary)),
    h("p", { class: "muted small" }, "Each widget answers one question. Add it, then drag it into place."), q, list);
  draw();
  lib.hidden = false;
  document.documentElement.classList.add("library-open");
  q.focus();
}
function closeLibrary() {
  const lib = $("#library");
  if (lib) lib.hidden = true;
  document.documentElement.classList.remove("library-open");
}

function exportLayout() {
  const blob = new Blob([JSON.stringify(Object.assign({}, S.layout, { theme: currentTheme() }), null, 2) + "\n"], { type: "application/json" });
  const a = h("a", { href: URL.createObjectURL(blob), download: "rihma-layout-" + S.persona + "-" + S.lens + ".json" });
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
function importLayout() {
  const input = h("input", { type: "file", accept: "application/json,.json", class: "vh" });
  input.addEventListener("change", async () => {
    const f = input.files && input.files[0];
    if (!f) return;
    try {
      const data = JSON.parse(await f.text());
      if (!data || data.v !== 1 || !Array.isArray(data.widgets)) throw new Error("not a cockpit layout (v: 1 with widgets)");
      const known = Object.keys((S.meta && S.meta.widgets) || {});
      const widgets = data.widgets.filter((w) => w && known.includes(w.type)).slice(0, 24);
      czEdit((l) => { l.widgets = widgets.map((w, i) => ({ id: String(w.id || w.type + "-" + i).replace(/[^A-Za-z0-9_-]/g, "").slice(0, 64) || "w" + i,
        type: w.type, size: SIZES.includes(w.size) ? w.size : "M", view: ["chart", "table", "list"].includes(w.view) ? w.view : "chart", filter: {} })); });
      say("Imported " + widgets.length + " widgets. Done saves them; the server checks them again.", "info");
    } catch (e) {
      say("That file could not be imported: " + e.message, "critical");
    }
    input.remove();
  });
  document.body.append(input);
  input.click();
}

// -- previews: the assistant's layout and theme proposals are shown before anything is kept ---------

function applyOps(layout, ops) {
  const lib = Object.keys((S.meta && S.meta.widgets) || {});
  const out = clone(layout);
  for (const o of ops || []) {
    let idx = out.widgets.findIndex((w) => w.type === o.widget);
    if (o.op === "add" && lib.includes(o.widget)) {
      out.widgets.push({ id: o.widget + "-" + Math.random().toString(36).slice(2, 7), type: o.widget, size: o.size || "M",
        view: o.view || WIDGET_DEFS[o.widget].views[0], filter: {} });
      continue;
    }
    if (idx < 0) continue;
    const w = out.widgets[idx];
    if (o.op === "remove") out.widgets.splice(idx, 1);
    else if (o.op === "resize") w.size = o.size;
    else if (o.op === "set_view") w.view = WIDGET_DEFS[w.type].views.includes(o.view) ? o.view : (o.view === "list" ? WIDGET_DEFS[w.type].views[0] : o.view);
    else if (o.op === "set_filter") w.filter = o.filter || {};
    else if (o.op === "move") {
      out.widgets.splice(idx, 1);
      out.widgets.splice(Math.max(0, Math.min(out.widgets.length, o.to)), 0, w);
      idx = o.to;
    }
  }
  return out;
}

export async function previewProposal(p) {
  if (!S.route || S.route.name !== "home") {
    location.hash = "#/home";
    await new Promise((r) => setTimeout(r, 50));
    if (nav.route) await nav.route();
  }
  if (!C.preview) C.preview = { layout: clone(S.layout), theme: Object.assign({}, currentTheme()) };
  if (p.action === "layout_edit") S.layout = applyOps(S.layout, p.args.ops);
  if (p.action === "theme") applyTheme(Object.assign({}, currentTheme(), p.args.settings));
  renderGrid();
  showPreviewBar();
  const first = p.action === "layout_edit" && p.args.ops[0] ? document.querySelector('[data-type="' + CSS.escape(p.args.ops[0].widget) + '"]') : null;
  if (first) { first.scrollIntoView({ block: "center" }); first.classList.add("flash"); setTimeout(() => first.classList.remove("flash"), 2000); }
}
function showPreviewBar() {
  const bar = $("#preview-bar");
  if (!bar) return;
  bar.hidden = false;
  fill(bar, icon("eye"), h("span", null, h("b", null, "Preview"), " · the assistant's change is shown, not kept yet."),
    h("span", { class: "pv-a" }, button("Undo", { icon: "undo", kind: "small quiet", key: "preview:undo", onclick: undoPreview }),
      button("Keep", { icon: "check", kind: "small primary", key: "preview:keep", onclick: keepPreview })));
}
export async function keepPreview() {
  if (!C.preview) return;
  const layout = clone(S.layout);
  layout.theme = Object.assign({}, S.theme);
  const saved = await act($("#preview-bar"), async () => saveLayout(layout));
  if (!saved) return false;
  local.set("gf.theme", JSON.stringify(S.theme));
  C.preview = null;
  const bar = $("#preview-bar");
  if (bar) bar.hidden = true;
  renderGrid();
  if (nav.previewSettled) nav.previewSettled("kept");
  return true;
}
export function undoPreview() {
  if (!C.preview) return;
  S.layout = C.preview.layout;
  applyTheme(C.preview.theme);
  C.preview = null;
  const bar = $("#preview-bar");
  if (bar) bar.hidden = true;
  renderGrid();
  say("The preview is undone; nothing was kept.", "info");
  if (nav.previewSettled) nav.previewSettled("undone");
}
export function previewing() { return !!C.preview; }
export { chip };
