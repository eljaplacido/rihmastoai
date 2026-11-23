/* The Rihma cockpit page: an ES module, no build step, no external assets.
   Rihma is the factory; Gnomon is the engine underneath it. This module signs the tab in, draws the
   shell (sidebar, top bar with the lens switcher, person chip, theme and Customize, the phone's
   bottom bar), and routes between pages. Every fact comes from the JSON API behind the session token;
   every write is signed with the person and persona chosen in the person chip. */

import {
  S, $, $$, h, fill, icon, api, say, store, local, localJSON, nav, enc, AuthError, setSignedOutHandler, wireTips,
  wireModal, closeMenu, openMenu, personaLabel, PAGES, PAGE_ROUTES, TOP_PAGES, PROJECT_VIEWS, VIEWS, LENS_ICON, ACCENTS,
  FACTORY_PID, avatar, button, empty, pageHead,
} from "./core.js";
import { renderHome, applyTheme, currentTheme, setTheme, toggleCustomize, customizeKeys, THEME_DEFAULT } from "./dashboard.js";
import { renderProject, renderFloor, renderJobs, stopLive, startLive, LIVE, cycleTasksMode } from "./project.js";
import { renderSquare, renderCatalogue, renderProjectsPage, renderInboxAll, renderSettings, newProjectModal, openEmbedForm } from "./screens.js";
import { openPalette, wirePalette } from "./palette.js";
import { wireAssistant, openAssistant, closeAssistant, assistantOpen, onRouteChange } from "./assistant.js";

applyTheme(Object.assign({}, THEME_DEFAULT, localJSON("gf.theme", {})));

// -- sign-in ----------------------------------------------------------------------------------------

function showSignIn(message) {
  clearTimeout(S.timer);
  document.documentElement.classList.add("signed-out");
  fill($("#main"), h("div", { class: "signin" }, h("div", { class: "card signin-card" },
    h("span", { class: "card-ic big" }, icon("key")),
    h("h1", null, "Sign in"),
    message ? h("p", { class: "toast-inline warning" }, icon("alert"), message) : null,
    h("p", null, "Open the one-use link that ", h("code", null, "python -m cockpit.server"),
      " printed when it started. It signs this tab in once; the session lives in this tab only."),
    h("p", { class: "muted small" }, "For a second tab, use “Link for another tab” in the person menu of a signed-in tab, "
      + "or restart the server for a new link. From another machine, open an SSH tunnel to the same port first: ",
    h("code", null, "ssh -L 8787:127.0.0.1:8787 <host>"), "."))));
}
setSignedOutHandler(showSignIn);

async function signIn(bootstrap) {
  const res = await fetch("/auth", { method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store",
    credentials: "omit", body: JSON.stringify({ bootstrap }) });
  let data = {};
  try { data = await res.json(); } catch (e) { data = {}; }
  if (!res.ok || !data.token) throw new Error(data.error || "the sign-in link was refused");
  return data.token;
}

// -- the person and the lens ------------------------------------------------------------------------

function lensFor(persona) {
  const saved = store.get("gf.lens." + persona);
  const lenses = (S.meta && S.meta.lenses) || {};
  if (saved && lenses[saved]) return saved;
  return ((S.meta && S.meta.persona_lens) || {})[persona] || "business";
}

function drawPersonChip() {
  const name = S.person.trim();
  fill($("#pc-avatar"), name ? name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase() : icon("user"));
  $("#pc-name").textContent = name || "Set your name";
  $("#pc-persona").textContent = personaLabel(S.persona);
  $("#person-chip").classList.toggle("unset", !name);
}

function drawPersonaList() {
  fill($("#persona-list"), S.personas.map((p) => {
    const id = "pp-" + p.id;
    const r = h("input", { type: "radio", name: "pp-persona", id, value: p.id, checked: p.id === S.persona });
    r.addEventListener("change", () => setPersona(p.id));
    return h("div", { class: "pp-opt" }, r, h("label", { for: id }, h("b", null, p.label),
      h("small", null, (((S.meta && S.meta.lenses) || {})[p.lens] || {}).label + " lens")));
  }));
  const p = S.personas.find((x) => x.id === S.persona);
  $("#persona-note").textContent = p ? p.label + " sees " + p.sees + ". Can " + p.can + "." : "";
}

function setPersona(id) {
  S.persona = id;
  store.set("gf.persona", id);
  S.lens = lensFor(id);
  drawPersonChip();
  drawPersonaList();
  drawLens();
  say("");
  route();
}

function openPerson(focusName) {
  const pop = $("#person-pop");
  const chipEl = $("#person-chip");
  if (!pop.hidden && !focusName) { closePerson(); return; }
  pop.hidden = false;
  chipEl.setAttribute("aria-expanded", "true");
  const r = chipEl.getBoundingClientRect();
  pop.style.top = (r.bottom + 6) + "px";
  pop.style.right = Math.max(8, window.innerWidth - r.right) + "px";
  drawPersonaList();
  ($("#person").value ? $("#persona-list input:checked") || $("#person") : $("#person")).focus();
  if (focusName) $("#person").focus();
}
function closePerson() {
  const pop = $("#person-pop");
  if (pop.hidden) return;
  pop.hidden = true;
  $("#person-chip").setAttribute("aria-expanded", "false");
  $("#linkbox").hidden = true;
}
nav.openPerson = openPerson;

function wirePerson() {
  S.person = store.get("gf.person") || "";
  const input = $("#person");
  input.value = S.person;
  input.addEventListener("input", () => { S.person = input.value; store.set("gf.person", input.value); drawPersonChip(); });
  input.addEventListener("change", () => { if (S.route && S.route.name === "home") route(true); });
  $("#person-chip").addEventListener("click", () => openPerson(false));
  $("#pp-done").addEventListener("click", closePerson);
  $("#person-pop").addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closePerson(); $("#person-chip").focus(); } });
  document.addEventListener("pointerdown", (e) => {
    const pop = $("#person-pop");
    if (!pop.hidden && !pop.contains(e.target) && !$("#person-chip").contains(e.target)) closePerson();
  });
  $("#newlink").addEventListener("click", async () => {
    try {
      const out = await api("POST", "/api/links", {});
      $("#linkurl").value = out.url;
      $("#linkbox").hidden = false;
      $("#linkurl").focus();
      $("#linkurl").select();
    } catch (e) { if (!(e instanceof AuthError)) say(e.message, "critical"); }
  });
  $("#linkcopy").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("#linkurl").value); say("The link is copied. It works once.", "good"); }
    catch (e) { $("#linkurl").select(); say("Copy the selected link by hand.", "warning"); }
  });
}

function drawLens() {
  const lenses = (S.meta && S.meta.lenses) || {};
  const box = $("#lens-switch");
  fill(box, Object.entries(lenses).map(([k, v]) => {
    const b = h("button", { type: "button", role: "radio", "aria-checked": String(k === S.lens), class: "lens-b", "data-lens": k,
      tip: v.question }, icon(LENS_ICON[k] || "eye"), h("span", { class: "lbl" }, v.label));
    b.addEventListener("click", () => {
      S.lens = k;
      store.set("gf.lens." + S.persona, k);
      drawLens();
      route(true);
    });
    return b;
  }));
}

// -- the sidebar, the top bar and the bottom bar ----------------------------------------------------

const NAV_ORDER = ["home", "square", "catalogue", "projects", "inbox_all", "floor", "jobs"];
const PAGE_ROUTE = { home: "#/home", square: "#/square", catalogue: "#/catalogue", projects: "#/projects",
  inbox_all: "#/inbox", floor: "#/floor", jobs: "#/jobs", settings: "#/settings" };

function navItem(id, extra) {
  const pg = PAGES[id];
  const on = S.route && S.route.name === id;
  return h("a", { class: "nav-i rail-tip" + (on ? " on" : ""), href: PAGE_ROUTE[id], "aria-current": on ? "page" : null, "data-tip": pg.label },
    icon(pg.icon), h("span", { class: "lbl" }, pg.label), extra || null);
}

function refreshSidebar() {
  const running = (S.projects || []).filter((p) => p.running).length;   // a running cell, never a guess
  fill($("#sb-nav"), NAV_ORDER.map((id) => navItem(id,
    id === "inbox_all" && S.inboxCount ? h("span", { class: "count", "aria-label": S.inboxCount + " waiting on you" }, String(S.inboxCount))
      : id === "projects" && running ? h("span", { class: "live-badge", tip: running === 1 ? "1 cell running now" : running + " cells running now" }, h("span", { class: "live-dot pulse" }), String(running)) : null)));
  const pv = S.route && S.route.name === "project" ? S.projectViews : null;
  const sbp = $("#sb-project");
  if (pv && S.project) {
    sbp.hidden = false;
    fill(sbp, h("div", { class: "sb-sec rail-tip", "data-tip": S.project.meta.title }, h("span", { class: "lbl" }, S.project.meta.title)),
      pv.views.map((v) => h("a", { class: "nav-i sub rail-tip" + (v === pv.current ? " on" : ""), href: "#/p/" + enc(pv.pid) + "/" + v,
        "aria-current": v === pv.current ? "page" : null, "data-tip": VIEWS[v].label }, icon(VIEWS[v].icon), h("span", { class: "lbl" }, VIEWS[v].label),
      v === "inbox" && pv.inbox ? h("span", { class: "count" }, String(pv.inbox)) : null)));
  } else {
    sbp.hidden = true;
    fill(sbp);
  }
  fill($("#sb-foot"), navItem("settings"));
  fill($("#bottombar"), [["home", "Home"], ["square", "Square"], ["inbox_all", "Inbox"], ["projects", "Projects"]].map(([id, lbl]) => {
    const on = S.route && S.route.name === id;
    return h("a", { href: PAGE_ROUTE[id], class: on ? "on" : null, "aria-current": on ? "page" : null }, icon(PAGES[id].icon),
      h("span", null, lbl), id === "inbox_all" && S.inboxCount ? h("span", { class: "count" }, String(S.inboxCount)) : null);
  }).concat([h("button", { type: "button", onclick: () => (assistantOpen() ? closeAssistant() : openAssistant()) }, icon("bot"), h("span", null, "Ask"))]));
}

function crumbs() {
  const r = S.route || {};
  const parts = [];
  if (r.name === "project" && S.project) {
    parts.push(h("a", { href: "#/p/" + enc(r.pid), class: "crumb-p" }, S.project.meta.title));
    const v = (S.projectViews || {}).current;
    if (v) parts.push(h("span", { "aria-current": "page" }, VIEWS[v].label));
  } else if (PAGES[r.name]) {
    parts.push(h("span", { "aria-current": "page" }, PAGES[r.name].label));
  }
  fill($("#crumbs"), parts.map((p, i) => [i ? icon("chevron-right", "crumb-sep") : null, p]));
}

nav.refreshShell = () => { refreshSidebar(); crumbs(); };

async function refreshCounts() {
  try {
    const [projects, inbox] = await Promise.all([api("GET", "/api/projects"), api("GET", "/api/inbox?persona=" + enc(S.persona))]);
    S.projects = projects;
    S.inboxCount = inbox.count;
    refreshSidebar();
  } catch (e) { /* the shell keeps what it had */ }
}

function wireShell() {
  const rail = local.get("gf.rail") === "1";
  document.documentElement.classList.toggle("rail", rail);
  $("#sb-collapse").setAttribute("aria-expanded", String(!rail));
  $("#sb-collapse").addEventListener("click", () => {
    const on = !document.documentElement.classList.contains("rail");
    document.documentElement.classList.toggle("rail", on);
    local.set("gf.rail", on ? "1" : "");
    $("#sb-collapse").setAttribute("aria-expanded", String(!on));
    $("#sb-collapse").setAttribute("aria-label", on ? "Expand the sidebar" : "Collapse the sidebar");
  });
  $("#tb-menu").addEventListener("click", () => document.documentElement.classList.toggle("nav-open"));
  $("#sidebar").addEventListener("click", (e) => { if (e.target.closest("a")) document.documentElement.classList.remove("nav-open"); });
  $("#sb-new").addEventListener("click", () => newProjectModal());
  $("#skip").addEventListener("click", (e) => { e.preventDefault(); $("#main").focus(); });
  $("#customize").addEventListener("click", toggleCustomize);
  $("#density").addEventListener("click", () => setTheme({ density: currentTheme().density === "compact" ? "comfortable" : "compact" }));
  $("#theme").addEventListener("click", () => {
    const t = currentTheme();
    openMenu($("#theme"), [{ group: "Mode" }].concat([["dark", "Dark", "moon"], ["light", "Light", "sun"], ["system", "System", "monitor"]].map(([v, l, ic]) =>
      ({ label: l, icon: ic, checked: t.mode === v, onclick: () => setTheme({ mode: v }) })),
    [{ sep: true }, { group: "Accent" }], ACCENTS.map((a) => ({ label: a.charAt(0).toUpperCase() + a.slice(1), checked: t.accent === a,
      onclick: () => setTheme({ accent: a }) })),
    [{ sep: true }, { group: "Corners" }], [["soft", "Soft"], ["crisp", "Crisp"]].map(([v, l]) => ({ label: l, checked: t.radius === v, onclick: () => setTheme({ radius: v }) }))), "Theme");
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyTheme(currentTheme()));
}

// -- routing ----------------------------------------------------------------------------------------

function parseRoute() {
  const parts = (location.hash || "").replace(/^#\/?/, "").split("/").filter(Boolean).map((x) => {
    try { return decodeURIComponent(x); } catch (e) { return x; }
  });
  if (parts[0] === "p" && parts[1]) {
    const view = parts[2] && PROJECT_VIEWS.includes(parts[2]) ? parts[2] : null;
    return { name: "project", pid: parts[1], view, focus: parts[3] || null };
  }
  const name = parts[0] === "inbox" ? "inbox_all" : parts[0];
  if (TOP_PAGES.includes(name)) return { name };
  return { name: "home" };
}

const RENDER = {
  home: renderHome, square: renderSquare, catalogue: renderCatalogue, projects: renderProjectsPage, inbox_all: renderInboxAll,
  floor: renderFloor, jobs: renderJobs, settings: renderSettings,
};
void PAGE_ROUTES;

async function route(keep) {
  if (!S.token) return;
  clearTimeout(S.timer);
  stopLive();
  LIVE.el = null;
  closeMenu();
  const r = parseRoute();
  const same = S.route && S.route.name === r.name && S.route.pid === r.pid && S.route.view === r.view && S.route.focus === r.focus;
  S.route = r;
  const seq = ++S.seq;
  if (r.name !== "project") { S.project = null; S.projectViews = null; }
  document.documentElement.classList.toggle("on-home", r.name === "home");
  if (!keep && !same) window.scrollTo(0, 0);   // a new page opens at its top; a re-render keeps the place
  refreshSidebar();
  crumbs();
  onRouteChange();
  try {
    if (r.name === "project") {
      const shown = await renderProject(r, keep || same, seq);
      if (shown && !keep && !same) showFocus(r.focus);
    } else {
      await RENDER[r.name](seq);
    }
    if (seq === S.seq) { crumbs(); refreshSidebar(); }
    if (S.jumped && seq === S.seq) {
      S.jumped = false;
      if (!r.focus) { const t = $("#view-title"); if (t) t.focus(); }
    }
  } catch (e) {
    if (e instanceof AuthError || seq !== S.seq) return;
    fill($("#main"), pageHead("Something went wrong", null), empty("alert", e.message,
      button("Back to Home", { icon: "home", onclick: () => { location.hash = "#/home"; } })));
  }
  refreshCounts();
}
nav.route = route;

function showFocus(id) {
  if (!id) return;
  const el = document.querySelector('[data-id="' + CSS.escape(id) + '"]');
  if (!el) { say(id + " is not shown in this view.", "warning"); return; }
  el.classList.add("focused");
  if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
  el.scrollIntoView({ block: "center" });
  el.focus({ preventScroll: true });
}

// Re-render after a write, keeping the place: the scroll position and the focused control.
async function rerender() {
  const active = document.activeElement;
  const key = active && active.dataset ? active.dataset.key : null;
  const y = window.scrollY;
  await route(true);
  window.scrollTo(0, y);
  const next = S.focusNext ? $(S.focusNext) : null;
  S.focusNext = null;
  const again = next || (key ? document.querySelector('[data-key="' + CSS.escape(key) + '"]') : null);
  if (again) again.focus();
}
nav.rerender = rerender;
nav.newProject = () => newProjectModal();
nav.openEmbedForm = openEmbedForm;

// -- keys -------------------------------------------------------------------------------------------

function typing(e) {
  const t = e.target;
  return t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
}
function wireKeys() {
  document.addEventListener("keydown", (e) => {
    if (customizeKeys(e)) return;
    if (e.key === "/" && !typing(e) && !e.ctrlKey && !e.metaKey && !$("#palette").open && !$("#modal").open) {
      e.preventDefault();
      openAssistant();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === "b" || e.key === "B") && !e.shiftKey && !e.altKey) {
      if (cycleTasksMode()) e.preventDefault();
      return;
    }
    if (e.key === "Escape") {
      if (document.documentElement.classList.contains("nav-open")) document.documentElement.classList.remove("nav-open");
    }
  });
}

// -- start ------------------------------------------------------------------------------------------

async function boot() {
  wireTips();
  wireModal();
  wirePerson();
  wireShell();
  wirePalette();
  wireAssistant();
  wireKeys();
  const m = /^#k=([A-Za-z0-9_-]+)/.exec(location.hash || "");
  if (m) {
    history.replaceState(null, "", location.pathname + "#/home");
    try {
      S.token = await signIn(m[1]);
      store.set("gf.token", S.token);
    } catch (e) {
      S.token = store.get("gf.token");
      if (!S.token) { showSignIn(e.message); return; }
    }
  } else {
    S.token = store.get("gf.token");
  }
  if (!S.token) { showSignIn(); return; }
  try {
    const [personas, meta] = await Promise.all([api("GET", "/api/personas"), api("GET", "/api/meta")]);
    S.personas = personas;
    S.meta = meta;
  } catch (e) {
    if (!(e instanceof AuthError)) say(e.message, "critical");
    return;
  }
  document.documentElement.classList.remove("signed-out");
  const saved = store.get("gf.persona");
  if (saved && S.personas.some((p) => p.id === saved)) S.persona = saved;
  S.lens = lensFor(S.persona);
  S.oneAtATime = store.get("gf.oneatatime") === "1";
  drawPersonChip();
  drawLens();
  window.addEventListener("hashchange", () => { route(); });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopLive();
    else if (LIVE.el && LIVE.el.isConnected) startLive();
  });
  route();
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
void $$; void avatar; void FACTORY_PID;
