/* Home: the dashboard for the active lens. A layout is versioned JSON kept on the server per person,
   persona and lens ({v:1, lens, widgets:[{id,type,size,view,filter}], theme}); localStorage is only a
   cache. The lens presets are read-only: the first edit duplicates the preset into a personal layout,
   with "Reset to default". Customize mode: drag to reorder (or Alt+arrows), cycle the size, remove,
   add from the library, Ctrl+Z to undo, Esc to cancel, Done to save. */

import {
  S, $, $$, h, icon, fill, api, act, say, needPerson, nav, enc, local, localJSON, button, iconButton, infoButton,
  openMenu, pageHead, empty, skeleton, chip, personaLabel, AuthError, ACCENTS,
} from "./core.js";
import { WIDGET_DEFS, SOURCES, PROV_NOTE } from "./widgets.js";
import { widgetOn, offNote } from "./modules.js";
import { modelSetupCard } from "./models.js";
import { pausedCard } from "./automations.js";
import { healthCard } from "./health.js";
import { reviewCard } from "./review.js";

const SIZES = ["S", "M", "L", "XL"];
const SIZE_LABEL = { S: "Small", M: "Medium", L: "Wide", XL: "Wide and tall" };
const VIEW_LABEL = { chart: "Chart", table: "Table", list: "List" };
const VIEW_ICON = { chart: "bar-chart", table: "table", list: "list" };
export const THEME_DEFAULT = { accent: "amber", density: "comfortable", mode: "system", radius: "soft", font_scale: 1 };
const UNDO_LIMIT = 20;
// widgets whose figures carry the observed or derived word; their ⓘ says what the words mean
const WITH_PROVENANCE = ["kpi_strip", "spend", "gate_trend", "coverage"];

/* A Customize session edits one layout: one person, persona and lens (`key`). `snapshot` is that layout
   as it was saved, `working` the edits in progress and `undo` their history. Leaving Home keeps the
   session, so coming back resumes it; another lens, persona or person ends it, and says so when it had
   unsaved changes. `library` redraws the open widget library after an edit. */
const C = { snapshot: null, working: null, key: null, undo: [], preview: null, drag: null, library: null };

/* The dashboard's read model. GET /api/dashboard is the same for every lens, persona and person, and takes
   seconds on a busy home. A lens, persona or person switch on Home draws the one fetched moments ago at
   once, says how old it is, and fetches a fresh one behind it. Coming back to Home, Refresh and the redraw
   after a write fetch a fresh one first. `raw` is the server's answer and `at` when it came; `shown` is the
   lens, persona and person Home last drew (cleared when the page changes); `inbox` the persona's Inbox. */
const D = { raw: null, at: 0, shown: null, inbox: null, refreshing: false, error: null, ready: null };
const REUSE_MS = 120000;

function phone() { return window.matchMedia("(max-width: 760px)").matches; }
function clone(x) { return JSON.parse(JSON.stringify(x)); }
function widgetInfo(type) { return ((S.meta && S.meta.widgets) || {})[type] || { title: type, icon: "info", question: "" }; }
function cacheKey() { return "gf.layout." + (S.person.trim() || "-") + "." + S.persona + "." + S.lens; }
function sessionKey() { return S.person.trim() + "\n" + S.persona + "\n" + S.lens; }
function onHome() { return !!S.route && S.route.name === "home"; }

// -- the theme: accent, density, mode, radius and font scale, from fixed sets ---------------------

// The theme as it is kept: the lens's saved layout over the browser's cache. While customizing, that is the
// session's snapshot, never its unsaved edits (an imported theme is only a preview on Home until Done).
export function currentTheme() {
  const saved = S.customizing && C.snapshot ? C.snapshot : S.layout;
  return Object.assign({}, THEME_DEFAULT, localJSON("gf.theme", {}), (saved && !S.layoutPreset && saved.theme) || {});
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
  // while customizing, the change also goes into the session's working layout, over an imported theme's
  // other values; Home shows that working theme, every other page the kept one
  const editing = S.customizing && C.snapshot ? C.working || S.layout : null;
  if (editing) editing.theme = Object.assign({}, editing.theme || {}, changes);
  applyTheme(editing && onHome() ? Object.assign({}, t, editing.theme) : t);
  local.set("gf.theme", JSON.stringify(t));
  if (opts && opts.save === false) return;
  if (S.layout && S.person.trim()) {
    // while customizing, the theme is saved with the layout as it was saved, never with unsaved edits
    const layout = clone(editing ? C.snapshot : S.layout);
    layout.theme = t;
    try {
      await saveLayout(layout, { quiet: true });
    } catch (e) {
      if (!(e instanceof AuthError)) say("The theme is shown here but was not saved with your layout: " + e.message, "warning");
      return;
    }
    if (editing) {
      C.snapshot = clone(S.layout);
      S.layout = editing;
      C.working = editing;
      drawLayoutKind();
    }
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
// `focus` says where the keyboard focus goes after the grid is drawn again (see renderGrid).
async function editLayout(fn, focus) {
  const layout = clone(S.layout);
  fn(layout);
  const keep = focus || focusMark(document.activeElement);
  if (!S.person.trim()) {
    S.layout = layout;
    renderGrid(keep);
    say("Shown for now. Set your name to keep it: a layout is saved per person.", "warning");
    return;
  }
  await act(null, async () => { await saveLayout(layout, { quiet: true }); });
  renderGrid(keep);
}
nav.setWidgetFilter = (id, filter) => editLayout((l) => { const w = l.widgets.find((x) => x.id === id); if (w) w.filter = filter; },
  { wid: id, fk: "filter" });

// -- keeping the focus: every control in a widget carries data-fk; after a redraw the focus goes back
// to the same control of the same widget, or to the widget, or to a named fallback ------------------

function focusMark(el) {
  const grid = $("#grid");
  if (!el || !grid || !grid.contains(el)) return null;
  const card = el.closest("[data-wid]");
  const fkEl = el.closest("[data-fk]");
  return card ? { wid: card.dataset.wid, fk: fkEl && card.contains(fkEl) ? fkEl.dataset.fk : null } : null;
}
function restoreFocus(mark) {
  if (!mark) return;
  const card = mark.wid ? document.querySelector('#grid [data-wid="' + CSS.escape(mark.wid) + '"]') : null;
  let el = card && mark.fk ? card.querySelector('[data-fk="' + CSS.escape(mark.fk) + '"]') : null;
  if (!el && card) el = card.matches('[tabindex="0"]') ? card : card.querySelector('[data-fk="menu"], .card-head button');
  if (!el && mark.fallback) el = document.querySelector(mark.fallback);
  if (el) el.focus();
}
// After a widget is removed, the focus goes to the widget that takes its place, else the one before it.
function neighbourOf(id, fk, fallback) {
  const ws = (S.layout && S.layout.widgets) || [];
  const i = ws.findIndex((w) => w.id === id);
  const next = ws[i + 1] || ws[i - 1];
  return { wid: next ? next.id : null, fk, fallback };
}

// -- rendering ------------------------------------------------------------------------------------

export async function renderHome(seq) {
  const main = $("#main");
  const last = D.shown;
  const quick = !!D.raw && !!last && Date.now() - D.at < REUSE_MS
    && (last.lens !== S.lens || last.persona !== S.persona || last.person !== S.person.trim());
  const done = skeleton(main, "the dashboard");
  let raw;
  let inbox;
  try {
    [raw, inbox] = await Promise.all([quick ? D.raw : fetchDashboard(), readInbox(), loadLayout()]);
  } finally {
    done();   // a failed read is shown by the router and stays: the placeholder never replaces it
  }
  if (seq !== S.seq) return;
  D.inbox = inbox;
  D.error = null;
  D.ready = null;
  S.dashboard = withQuestions(raw, inbox);
  D.shown = { lens: S.lens, persona: S.persona, person: S.person.trim() };
  const resumed = resumeSession();
  restorePreview();
  applyTheme(C.preview && C.preview.shown ? C.preview.shown.theme : editTheme());
  const lens = ((S.meta && S.meta.lenses) || {})[S.lens] || {};
  document.title = lens.label + " · Home · Rihmasto.ai";
  fill(main,
    pageHead(lens.label ? lens.label + " view" : "Home", lens.question || "", {
      icon: null,
      actions: [h("span", { class: "fresh-note muted small", id: "fresh-note" }),
        h("a", { href: "#/shape", class: "btn quiet", "data-control": "shape_open", "data-key": "home:shape" }, icon("message-square"),
          h("span", { class: "lbl" }, "Shape it in chat")),
        nav.walk ? nav.walk.homeButton() : null,   // walkthroughs in Ask Rihma (walkthrough.js)
        button("Refresh", { icon: "refresh", kind: "quiet", key: "home:refresh", onclick: () => nav.route && nav.route(true) })],
    }),
    h("div", { class: "home-review", id: "home-review" }),
    h("div", { class: "home-setup", id: "home-setup" }),
    h("div", { class: "home-setup", id: "home-auto" }),
    h("div", { class: "home-walk", id: "home-walk" }),
    h("div", { class: "home-setup", id: "home-health" }),
    h("div", { class: "dash-notes", id: "dash-notes" }),
    h("div", { class: "cz-bar", id: "cz-bar", hidden: true }),
    h("div", { class: "preview-bar", id: "preview-bar", hidden: true }),
    h("div", { class: "grid", id: "grid", role: "list", "aria-label": "Dashboard widgets" }));
  D.refreshing = quick;   // this render owns the flag; a read of an earlier render that comes late leaves it be
  drawFresh();
  drawNotes();
  reviewCard($("#home-review"));       // "Since you last looked": the first card (review.js)
  modelSetupCard($("#home-setup"));    // "Set up a model" while no model Rihma talks with answers
  pausedCard($("#home-auto"));         // an automation the circuit breaker paused, and why (automations.js)
  if (nav.walk) nav.walk.homeCard($("#home-walk"));   // no project yet: a walkthrough is offered (FR-WLK1)
  healthCard($("#home-health"));       // checks failing or not measured (health.js, FR-CHK1)
  renderGrid();
  if (S.customizing) startCustomize(resumed);
  if (C.preview) showPreviewBar();
  if (quick) refreshBehind(seq);
}
function layoutKind() { return S.customizing && C.snapshot && C.undo.length ? "Unsaved changes" : S.layoutPreset ? "Default layout" : "Your layout"; }
function drawLayoutKind() { const kind = $(".layout-kind"); if (kind) kind.textContent = layoutKind(); }

// The header's note: which layout this is, how old the figures are, and whether fresh ones are on the way.
function drawFresh() {
  const el = $("#fresh-note");
  if (!el) return;
  fill(el, h("span", { class: "layout-kind" }, layoutKind()),
    " · updated " + String((S.dashboard || {}).generated_at || "").slice(11, 16) + " UTC",
    D.refreshing ? h("span", { class: "dash-refreshing" }, " · refreshing") : null);
  const grid = $("#grid");
  if (grid) grid.setAttribute("aria-busy", D.refreshing ? "true" : "false");
}

// The page's notes above the grid: read models the server could not read, a fresh read that failed (the
// figures shown are the older ones, and say so), and newer figures held back while the person works in a widget.
function drawNotes() {
  const box = $("#dash-notes");
  if (!box) return;
  const d = S.dashboard || {};
  const off = ((S.layout && S.layout.widgets) || []).filter((w) => !widgetOn(w.type)).length;
  fill(box, off ? offNote(off, off === 1 ? "widget of this layout" : "widgets of this layout") : null,
    (d.problems || []).length ? h("p", { class: "w-warn page", role: "note" }, icon("alert"),
      h("span", null, "Some read models could not be read: " + d.problems.join(", ") + ". The widgets built on them say so.")) : null,
    D.error ? h("p", { class: "w-warn page", role: "alert" }, icon("alert"),
      h("span", null, "The figures could not be read again (" + D.error + "), so these are the ones from "
        + String(d.generated_at || "").slice(11, 16) + " UTC. Refresh tries again.")) : null,
    D.ready ? h("div", { class: "w-note page", role: "status" }, icon("refresh"),
      h("span", null, "Newer figures came in while you were working in a widget; they are not shown yet."),
      button("Show them", { kind: "small", key: "home:newer", onclick: showNewer })) : null);
}

// Home is drawn again (another page and back, Refresh, a lens, persona or person): a Customize session for
// the same layout goes on with its edits; one for another layout ends, and says why if it had changes.
function resumeSession() {
  if (!S.customizing || !C.snapshot) return false;
  if (C.key === sessionKey()) {
    if (C.working) S.layout = C.working;
    return true;
  }
  if (C.working && JSON.stringify(C.working) !== JSON.stringify(C.snapshot)) say(notKept(C.key), "warning");
  C.snapshot = null;
  C.working = null;
  C.undo = [];
  return false;
}
function lensName(id) { return (((S.meta && S.meta.lenses) || {})[id] || {}).label || id; }
// Why a Customize session's edits were not kept, naming what changed: the person, the persona or the lens.
function notKept(key) {
  const [person, persona, lens] = String(key).split("\n");
  const me = S.person.trim();
  let was = "the " + lensName(lens) + " layout";
  let why = "you switched to the " + lensName(S.lens) + " lens";
  let now = "the " + lensName(S.lens) + " layout";
  if (person !== me) {
    was = (person ? person + "'s " : "the ") + lensName(lens) + " layout";
    why = me ? "the person chip now names " + me : "the person chip names nobody now";
    now = (me ? me + "'s " : "the ") + lensName(S.lens) + " layout";
  } else if (persona !== S.persona) {
    was = "the " + personaLabel(persona) + "'s " + lensName(lens) + " layout";
    why = "you switched to the " + personaLabel(S.persona) + " persona";
    now = "the " + personaLabel(S.persona) + "'s " + lensName(S.lens) + " layout";
  }
  return "The unsaved changes to " + was + " were not kept: " + why + ", and Customize edits one layout at a time "
    + "(one person, persona and lens). You are now customizing " + now + "; Done saves it.";
}

// -- the read model: fetched, merged with the persona's Inbox, and refreshed behind a quick redraw ---------

async function fetchDashboard() {
  const raw = await api("GET", "/api/dashboard");
  D.raw = raw;
  D.at = Date.now();
  return raw;
}
// The persona's Inbox; one that cannot be read is named among the problems, never shown as empty.
async function readInbox() {
  try {
    return await api("GET", "/api/inbox?persona=" + enc(S.persona));
  } catch (e) {
    if (e instanceof AuthError) throw e;
    return { error: e.message || String(e) };
  }
}
function ageHours(now, at) {
  const t = Date.parse(at || "");
  return Number.isNaN(now) || Number.isNaN(t) ? null : Math.round((now - t) / 360000) / 10;
}
/* The dashboard's decisions with the open question cards put back. A question card is a question put to a
   person (kernel.canon.ask): it waits on one, blocking or not, and in a socratic project every question is
   one. The server's decisions keep only blocking questions, so the persona's Inbox (question cards go to
   every persona) adds the others, a card already listed is not counted twice, and the key figure counts
   them too. An Inbox that could not be read is a problem the decisions widget and its figure name. */
export function withQuestions(raw, inbox) {
  const d = Object.assign({}, raw);
  if (!inbox || inbox.error) {
    d.problems = (raw.problems || []).concat(["inbox: " + ((inbox && inbox.error) || "not read")]);
    return d;
  }
  const cards = (inbox.cards || []).filter((c) => c.kind === "question" && c.state === "open");
  const byKey = new Map(cards.map((c) => [c.project + "\n" + c.id, c]));
  const listed = (raw.decisions || []).map((x) => {
    const c = x.kind === "question" ? byKey.get(x.project + "\n" + x.card) : null;
    byKey.delete(x.project + "\n" + x.card);
    return c && !x.refs ? Object.assign({}, x, { refs: c.refs || {} }) : x;
  });
  const now = Date.parse(raw.generated_at || "");
  const extra = Array.from(byKey.values()).map((c) => ({ project: c.project, project_title: c.project_title, card: c.id,
    kind: "question", title: c.title, deciders: c.deciders || [], verdicts: c.verdicts || [], refs: c.refs || {},
    blocking: !!c.blocking, payload: {}, age_hours: ageHours(now, c.created) }));
  d.decisions = listed.concat(extra).sort((a, b) => (b.age_hours || 0) - (a.age_hours || 0));
  if (!extra.length) return d;
  const k = raw.kpis || {};
  const ages = d.decisions.map((x) => x.age_hours).filter((x) => x !== null && x !== undefined);
  d.kpis = Object.assign({}, k, { decisions: Object.assign({}, k.decisions || {}, { value: d.decisions.length,
    oldest_hours: ages.length ? Math.max(...ages) : null,
    basis: "open cards waiting on a person across projects, the panel's open questions included" }) });
  return d;
}
// Whether the person is at work in the grid, which a redraw would undo: text typed into a widget (a reason,
// a filter) or a widget being dragged.
function busyInGrid() {
  const grid = $("#grid");
  return !!grid && (C.drag !== null || $$("input, textarea", grid).some((x) => x.value !== x.defaultValue));
}
function refreshBehind(seq) {
  fetchDashboard().then((raw) => {
    if (seq !== S.seq || !onHome()) return;
    D.refreshing = false;
    const next = withQuestions(raw, D.inbox);
    if (busyInGrid()) {
      D.ready = next;
      drawFresh();
      drawNotes();
      return;
    }
    showDashboard(next);
  }, (e) => {
    if (e instanceof AuthError || seq !== S.seq || !onHome()) return;
    D.refreshing = false;
    D.error = e.message || String(e);
    drawFresh();
    drawNotes();
  });
}
function showDashboard(d) {
  S.dashboard = d;
  D.ready = null;
  D.error = null;
  drawFresh();
  drawNotes();
  renderGrid();
}
// "Show them": the newer figures replace the held ones; the button is gone, so the focus goes to the grid.
function showNewer() {
  if (!D.ready) return;
  showDashboard(D.ready);
  const first = (S.layout && S.layout.widgets || [])[0];
  restoreFocus(first ? { wid: first.id } : { fallback: '[data-key="home:refresh"]' });
}

/* Draw every widget. The keyboard focus stays where it was: on the same control of the same widget
   (data-fk), or where `focus` says ({wid, fk, fallback}), never on <body>. */
export function renderGrid(focus) {
  const grid = $("#grid");
  if (!grid || !S.layout) return;
  const keep = focus === undefined ? focusMark(document.activeElement) : focus;
  const d = S.dashboard || {};
  const widgets = S.layout.widgets || [];
  if (!widgets.some((w) => widgetOn(w.type))) {   // a widget whose module is off stays in the layout, not drawn
    fill(grid, h("div", { class: "grid-empty" }, empty("sliders", "This layout has no widgets.",
      button("Add a widget", { icon: "plus", kind: "primary", key: "grid:add", onclick: () => { if (!S.customizing) toggleCustomize(); openLibrary(); } }))));
  } else {
    fill(grid, widgets.map((w, i) => (widgetOn(w.type) ? widgetCard(w, i, d) : null)));
  }
  restoreFocus(keep && !widgets.length ? { fallback: '#grid [data-key="grid:add"]' } : keep);
  drawLayoutKind();
  if (C.library) C.library();
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
  const setView = (v) => (l) => { const x = l.widgets.find((y) => y.id === w.id); if (x) x.view = v; };
  if (views.length > 1 && !custom) {
    tools.push(h("span", { class: "view-toggle", role: "group", "aria-label": "View" }, views.map((v) =>
      h("button", { type: "button", class: "icon-btn tiny" + (v === view ? " on" : ""), "aria-pressed": String(v === view),
        "aria-label": VIEW_LABEL[v] + " view", tip: VIEW_LABEL[v] + " view", "data-fk": "view-" + v,
        onclick: () => editLayout(setView(v), { wid: w.id, fk: "view-" + v }) }, icon(VIEW_ICON[v])))));
  }
  if (!phone() && !custom) {
    const more = h("button", { type: "button", class: "icon-btn tiny", "aria-label": "Widget menu: " + info.title, "aria-haspopup": "menu",
      "aria-expanded": "false", "data-fk": "menu" }, icon("more"));
    const back = { wid: w.id, fk: "menu" };
    more.addEventListener("click", () => openMenu(more, [{ group: "View" }].concat(views.map((v) => ({ label: VIEW_LABEL[v], icon: VIEW_ICON[v], checked: v === view,
      onclick: () => editLayout(setView(v), back) })),
    [{ sep: true }, { group: "Size" }], SIZES.map((s) => ({ label: SIZE_LABEL[s] + " (" + s + ")", checked: s === w.size,
      onclick: () => editLayout((l) => { const x = l.widgets.find((y) => y.id === w.id); if (x) x.size = s; }, back) })),
    [{ sep: true }, { label: "Remove from this layout", icon: "x", danger: true,
      onclick: () => editLayout((l) => { l.widgets = l.widgets.filter((y) => y.id !== w.id); },
        neighbourOf(w.id, "menu", '#grid [data-key="grid:add"]')) }]), "Widget menu"));
    tools.push(more);
  }
  if (custom) {
    tools.push(h("button", { type: "button", class: "btn tiny", "aria-label": "Size " + w.size + ": change", tip: "Cycle the size: S, M, L, XL",
      "data-fk": "size", onclick: () => czEdit((l) => { const x = l.widgets[index]; x.size = SIZES[(SIZES.indexOf(x.size) + 1) % SIZES.length]; },
        { wid: w.id, fk: "size" }) }, icon("expand"), w.size),
    h("button", { type: "button", class: "icon-btn tiny", "aria-label": "Remove " + info.title, tip: "Remove", "data-fk": "remove",
      onclick: () => czEdit((l) => { l.widgets.splice(index, 1); }, neighbourOf(w.id, null, '#grid [data-key="grid:add"]')) }, icon("x")));
  }
  const about = infoButton(info.title, h("div", null, h("p", null, h("b", null, info.question)), h("p", { class: "muted" }, SOURCES[w.type] || ""),
    WITH_PROVENANCE.includes(w.type) ? h("p", { class: "muted" }, PROV_NOTE.observed + ". " + PROV_NOTE.derived + ".") : null));
  about.dataset.fk = "about";
  // while customizing, the body is inert: nothing in it can be clicked, focused or decided
  const el = h("section", { class: "widget card size-" + w.size + (custom ? " cz" : ""), role: "listitem", "data-wid": w.id, "data-type": w.type,
    "aria-labelledby": "wt-" + w.id, tabindex: custom ? "0" : null, draggable: custom ? "true" : null },
  h("header", { class: "card-head" },
    custom ? h("span", { class: "grip", "aria-hidden": "true" }, icon("grip")) : null,
    h("span", { class: "card-ic" }, icon(info.icon)),
    h("h3", { class: "card-t", id: "wt-" + w.id }, info.title),
    about,
    h("span", { class: "card-tools" }, tools)),
  h("div", { class: "card-body" + (custom ? " inert" : ""), inert: custom || null }, body));
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
  if (!resume || !C.snapshot) {
    C.snapshot = clone(S.layout);
    C.working = S.layout;
    C.key = sessionKey();
    C.undo = [];
  }
  document.documentElement.classList.add("customizing");
  const btn = $("#customize");
  if (btn) btn.setAttribute("aria-pressed", "true");
  const bar = $("#cz-bar");
  if (bar) {
    bar.hidden = false;
    fill(bar, h("span", { class: "cz-t" }, icon("sliders"), h("b", null, "Customizing your " + lensLabel() + " layout"),
      h("span", { class: "muted small" }, S.layoutPreset ? "The default stays as it is; Done saves your own copy." : "Drag to reorder, or Alt+arrows on a focused widget.")),
    h("span", { class: "cz-a" },
      button("Add widget", { icon: "plus", kind: "small", key: "cz:add", onclick: openLibrary }),
      button("Undo", { icon: "undo", kind: "small quiet", aria: "Undo (Ctrl+Z)", key: "cz:undo", onclick: undo }),
      button("Reset to default", { kind: "small quiet", key: "cz:reset", onclick: () => czEdit((l) => { l.widgets = clone((S.layoutDefault || l).widgets); }) }),
      button("Export", { icon: "download", kind: "small quiet", key: "cz:export", onclick: exportLayout }),
      button("Import", { icon: "upload", kind: "small quiet", key: "cz:import", onclick: importLayout }),
      button("Cancel", { kind: "small quiet", key: "cz:cancel", onclick: () => finishCustomize(false) }),
      button("Done", { icon: "check", kind: "small primary", key: "cz:done", onclick: () => finishCustomize(true) })));
  }
  renderGrid();
}

async function finishCustomize(save) {
  const opener = $("#customize");
  const from = document.activeElement;
  if (save) {
    const ok = await act($("#cz-bar"), async () => saveLayout(S.layout));
    if (!ok) return;
    local.set("gf.theme", JSON.stringify(currentTheme()));
  } else if (C.snapshot) {
    S.layout = C.snapshot;
  }
  S.customizing = false;
  C.snapshot = null;
  C.working = null;
  C.key = null;
  C.undo = [];
  document.documentElement.classList.remove("customizing");
  if (opener) opener.setAttribute("aria-pressed", "false");
  const bar = $("#cz-bar");
  if (bar) bar.hidden = true;
  closeLibrary();
  applyTheme(currentTheme());   // an imported theme was only a preview until Done
  renderGrid();
  // the bar's buttons are gone: the focus goes back to Customize, which opened it
  if (opener && (!from || from === document.body || (bar && bar.contains(from)) || !from.isConnected || (from.closest && from.closest("#library")))) opener.focus();
}

// An edit in Customize: undoable, kept as the session's working layout, focus per `focus` (renderGrid).
function czEdit(fn, focus) {
  C.undo.push(clone(S.layout));
  if (C.undo.length > UNDO_LIMIT) C.undo.shift();
  const layout = clone(S.layout);
  fn(layout);
  S.layout = layout;
  C.working = layout;
  renderGrid(typeof focus === "string" ? { wid: focus } : focus);
}
function undo() {
  if (!C.undo.length) { say("Nothing to undo.", "info"); return; }
  S.layout = C.undo.pop();
  C.working = S.layout;
  applyTheme(editTheme());
  renderGrid();
}
// The theme shown while customizing: the working layout's own, which an import may have changed.
function editTheme() { return Object.assign({}, currentTheme(), (S.customizing && S.layout && S.layout.theme) || {}); }

function wireDrag(el, index) {
  el.addEventListener("dragstart", (e) => { C.drag = index; el.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(index)); });
  el.addEventListener("dragend", () => { C.drag = null; el.classList.remove("dragging"); $$(".widget.drop").forEach((x) => x.classList.remove("drop")); });
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
  if (!S.customizing || !onHome()) return false;   // away from Home the session waits, untouched
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
  // drawn again after every edit (and undo), so "On this layout" is always true; the focused Add stays focused
  const draw = () => {
    const was = document.activeElement && list.contains(document.activeElement) ? document.activeElement.dataset.key : null;
    const term = q.value.trim().toLowerCase();
    const all = Object.entries((S.meta && S.meta.widgets) || {}).filter(([k]) => widgetOn(k));   // the modules that are on
    const offLib = Object.keys((S.meta && S.meta.widgets) || {}).filter((k) => !widgetOn(k)).length;
    if (!list.nextSibling && offLib) list.after(offNote(offLib, "more widgets"));
    fill(list, all.filter(([k, v]) => !term || (k + " " + v.title + " " + v.question).toLowerCase().includes(term)).map(([k, v]) => {
      const n = (S.layout.widgets || []).filter((w) => w.type === k).length;
      const add = button("Add", { icon: "plus", kind: "small", key: "lib:" + k, aria: "Add " + v.title, onclick: () => {
        if ((S.layout.widgets || []).length >= ((S.meta.layout || {}).max_widgets || 24)) { say("A layout holds at most 24 widgets.", "warning"); return; }
        const id = k + "-" + Math.random().toString(36).slice(2, 7);
        czEdit((l) => { l.widgets.push({ id, type: k, size: k === "kpi_strip" || k === "timeline" || k === "evidence_packs" ? "L" : "M", view: WIDGET_DEFS[k].views[0], filter: {} }); }, id);
        say(v.title + " is added at the end of the layout.", "info");
      } });
      return h("li", { class: "lib-item" }, h("span", { class: "card-ic" }, icon(v.icon)),
        h("div", null, h("b", null, v.title), h("p", null, v.question), n ? h("small", { class: "muted" }, "On this layout " + (n > 1 ? n + " times" : "already")) : null), add);
    }));
    const again = was ? list.querySelector('[data-key="' + CSS.escape(was) + '"]') : null;
    if (again) again.focus();
  };
  q.addEventListener("input", draw);
  fill(lib, h("div", { class: "lib-head" }, h("h2", { id: "lib-h" }, "Widget library"), iconButton("x", "Close the library", () => closeLibrary(true))),
    h("p", { class: "muted small" }, "Each widget answers one question. Add it, then drag it into place."), q, list);
  C.library = draw;
  draw();
  lib.hidden = false;
  document.documentElement.classList.add("library-open");
  q.focus();
}
function closeLibrary(refocus) {
  const lib = $("#library");
  const had = lib && !lib.hidden && lib.contains(document.activeElement);
  if (lib) lib.hidden = true;
  C.library = null;
  document.documentElement.classList.remove("library-open");
  if (refocus || had) {
    const back = [$('#cz-bar [data-key="cz:add"]'), $("#customize")].find((b) => b && b.offsetParent !== null);
    if (back) back.focus();
  }
}
/* The library is part of Home: it closes when the page changes. A Customize session and the assistant's
   preview wait on Home too: every other page shows the kept theme, nothing is marked as customizing, and
   unsaved changes are said to be waiting there. */
window.addEventListener("hashchange", () => setTimeout(() => {
  if (onHome()) return;
  const wasHome = !!D.shown;
  closeLibrary();
  D.shown = null;
  D.ready = null;
  if (!S.customizing && !C.preview) return;
  document.documentElement.classList.remove("customizing");
  applyTheme(currentTheme());
  if (wasHome && S.customizing && C.working && JSON.stringify(C.working) !== JSON.stringify(C.snapshot)) {
    say("Your unsaved changes to the " + lensName(String(C.key).split("\n")[2]) + " layout wait on Home: Done there saves them, "
      + "Cancel drops them.", "info");
  }
}, 0));

function exportLayout() {
  const blob = new Blob([JSON.stringify(Object.assign({}, S.layout, { theme: editTheme() }), null, 2) + "\n"], { type: "application/json" });
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
      const out = readLayoutFile(JSON.parse(await f.text()));
      czEdit((l) => {
        l.widgets = out.widgets;
        if (out.theme) l.theme = Object.assign({}, l.theme || {}, out.theme);
      });
      if (out.theme) applyTheme(editTheme());
      say("Imported " + out.widgets.length + (out.widgets.length === 1 ? " widget" : " widgets") + (out.theme ? " and the theme" : "")
        + (out.notes.length ? ". " + out.notes.join(" ") : ".") + " Done saves it; Cancel or Ctrl+Z goes back.", out.notes.length ? "warning" : "info");
    } catch (e) {
      say("That file could not be imported, and the layout is as it was: " + e.message, "critical");
    }
    input.remove();
    const back = $('#cz-bar [data-key="cz:import"]');
    if (back) back.focus();
  });
  document.body.append(input);
  input.click();
}

/* An exported layout, checked as the server checks it before it replaces anything: known widget types,
   at most the layout's maximum, unique ids of letters, digits, - or _, sizes and views from their sets,
   a small filter of plain values, and a theme from the fixed sets. What is left out is said; a file with
   no usable widget is refused. */
function readLayoutFile(data) {
  if (!data || typeof data !== "object" || data.v !== 1 || !Array.isArray(data.widgets)) throw new Error("it is not a cockpit layout (v: 1 with widgets).");
  const lib = (S.meta && S.meta.widgets) || {};
  const sets = (S.meta && S.meta.layout) || {};
  const max = sets.max_widgets || 24;
  const unknown = [];
  const ids = new Set();
  let renamed = 0;
  const widgets = [];
  data.widgets.forEach((w, i) => {
    if (!w || typeof w !== "object" || !Object.prototype.hasOwnProperty.call(lib, w.type)) { unknown.push(String((w && w.type) || "?").slice(0, 40)); return; }
    let id = String(w.id || w.type + "-" + i).replace(/[^A-Za-z0-9_-]/g, "").slice(0, 64) || w.type + "-" + i;
    if (ids.has(id)) { renamed += 1; let n = 2; while (ids.has(id.slice(0, 58) + "-" + n)) n += 1; id = id.slice(0, 58) + "-" + n; }
    ids.add(id);
    const views = (WIDGET_DEFS[w.type] || {}).views || ["chart", "table"];
    const plain = (v) => v === null || ["string", "number", "boolean"].includes(typeof v);
    const filter = w.filter && typeof w.filter === "object" && !Array.isArray(w.filter) && Object.values(w.filter).every(plain)
      && JSON.stringify(w.filter).length <= 400 ? w.filter : {};
    widgets.push({ id, type: w.type, size: SIZES.includes(w.size) ? w.size : "M", view: views.includes(w.view) ? w.view : views[0], filter });
  });
  if (!widgets.length) throw new Error(unknown.length ? "none of its widgets is in the library (" + unknown.join(", ") + ")." : "it holds no widget.");
  const notes = [];
  if (unknown.length) notes.push(unknown.length + " left out, not in the library: " + unknown.join(", ") + ".");
  if (widgets.length > max) notes.push((widgets.length - max) + " left out: a layout holds at most " + max + " widgets.");
  if (renamed) notes.push(renamed + " repeated widget id" + (renamed > 1 ? "s were" : " was") + " made unique.");
  let theme = null;
  if (data.theme && typeof data.theme === "object") {
    const fixed = sets.theme || {};
    const fs = sets.font_scale || [0.9, 1.25];
    theme = {};
    Object.entries(data.theme).forEach(([k, v]) => {
      if (k === "font_scale" ? typeof v === "number" && v >= fs[0] && v <= fs[1] : (fixed[k] || []).includes(v)) theme[k] = v;
    });
    if (Object.keys(theme).length < Object.keys(data.theme).length) notes.push("Theme values outside the fixed sets were left out.");
    if (!Object.keys(theme).length) theme = null;
  }
  return { widgets: widgets.slice(0, max), theme, notes };
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
  if (!C.preview) C.preview = { layout: clone(S.layout), theme: Object.assign({}, currentTheme()), key: sessionKey(), shown: null };
  if (p.action === "layout_edit") S.layout = applyOps(S.layout, p.args.ops);
  if (p.action === "theme") applyTheme(Object.assign({}, currentTheme(), p.args.settings));
  C.preview.shown = { layout: clone(S.layout), theme: Object.assign({}, S.theme) };
  renderGrid();
  showPreviewBar();
  const first = p.action === "layout_edit" && p.args.ops[0] ? document.querySelector('[data-type="' + CSS.escape(p.args.ops[0].widget) + '"]') : null;
  if (first) { first.scrollIntoView({ block: "center" }); first.classList.add("flash"); setTimeout(() => first.classList.remove("flash"), 2000); }
}
// Coming back to Home: the preview is shown again on the layout it was made for; for another layout (the
// lens, persona or person changed) it is undone, and nothing was kept.
function restorePreview() {
  if (!C.preview) return;
  if (C.preview.key === sessionKey() && C.preview.shown) {
    S.layout = clone(C.preview.shown.layout);
    return;
  }
  C.preview = null;
  say("The assistant's preview was for another layout, so it is undone; nothing was kept.", "info");
  if (nav.previewSettled) nav.previewSettled("undone");
}
function showPreviewBar() {
  const bar = $("#preview-bar");
  if (!bar) return;
  bar.hidden = false;
  fill(bar, icon("eye"), h("span", null, h("b", null, "Preview"), " · the assistant's change is shown, not kept yet."),
    h("span", { class: "pv-a" }, button("Undo", { icon: "undo", kind: "small quiet", key: "preview:undo", onclick: undoPreview }),
      button("Keep", { icon: "check", kind: "small primary", key: "preview:keep", onclick: keepPreview })));
}
// The preview bar closes after Keep or Undo: a focus that was on its buttons goes to the first widget.
function closePreviewBar(from) {
  const bar = $("#preview-bar");
  const had = !!bar && !!from && (bar.contains(from) || from === document.body);
  if (bar) bar.hidden = true;
  const first = ((S.layout && S.layout.widgets) || [])[0];
  renderGrid(had ? (first ? { wid: first.id } : { fallback: '[data-key="home:refresh"]' }) : undefined);
}
export async function keepPreview() {
  if (!C.preview) return;
  const from = document.activeElement;
  const layout = clone(S.layout);
  layout.theme = Object.assign({}, S.theme);
  const saved = await act($("#preview-bar"), async () => saveLayout(layout));
  if (!saved) return false;
  local.set("gf.theme", JSON.stringify(S.theme));
  C.preview = null;
  closePreviewBar(from);
  if (nav.previewSettled) nav.previewSettled("kept");
  return true;
}
export function undoPreview() {
  if (!C.preview) return;
  const from = document.activeElement;
  S.layout = C.preview.layout;
  applyTheme(C.preview.theme);
  C.preview = null;
  closePreviewBar(from);
  say("The preview is undone; nothing was kept.", "info");
  if (nav.previewSettled) nav.previewSettled("undone");
}
export function previewing() { return !!C.preview; }
export { chip };
