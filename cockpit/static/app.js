/* The Rihma cockpit page: an ES module, no build step, no external assets.
   Rihma is the factory; Gnomon is the engine underneath it. This module signs the tab in, draws the
   shell (sidebar, top bar with the lens switcher, person chip, theme and Customize, the phone's
   bottom bar), and routes between pages. Every fact comes from the JSON API behind the session token;
   every write is signed with the person and persona chosen in the person chip. */

import {
  S, $, $$, h, fill, icon, api, say, store, local, localJSON, nav, enc, AuthError, setSignedOutHandler, wireTips,
  wireModal, closeMenu, openMenu, hideTip, personaLabel, PAGES, PAGE_ROUTES, TOP_PAGES, PROJECT_VIEWS, VIEWS, LENS_ICON,
  ACCENTS, FACTORY_PID, avatar, button, empty, pageHead, CREDENTIALS,
} from "./core.js";
import {
  renderHome, applyTheme, currentTheme, setTheme, loadLayout, previewing, toggleCustomize, customizeKeys, THEME_DEFAULT,
} from "./dashboard.js";
import { renderProject, renderFloor, renderJobs, stopLive, startLive, LIVE, cycleTasksMode } from "./project.js";
import { renderSquare, renderCatalogue, renderProjectsPage, renderInboxAll, renderSettings, newProjectModal, openEmbedForm } from "./screens.js";
import { openPalette, wirePalette } from "./palette.js";
import { wireAssistant, openAssistant, closeAssistant, assistantOpen, onRouteChange } from "./assistant.js";
import { loadModules, pageOn, firstRun, offPage, moduleShows } from "./modules.js";
import { renderShape } from "./shape.js";
import { renderModels } from "./models.js";
import { renderRunners } from "./runners.js";
import { renderAutomations } from "./automations.js";
import { resumeWalk } from "./walkthrough.js";
import { resumeGuide } from "./journey.js";   // guided journeys (FR-JRN1)
import { renderHealth } from "./health.js";
import { renderInsights } from "./insights.js";
import { renderGraphPage } from "./graph.js";   // the Knowledge graph (FR-GRV1)
import { renderReview } from "./review.js";
import { renderAgentActivity } from "./agents.js";
import { drawScope, projectSidebar, scopedLabel, ALL_SCOPE } from "./scope.js";
import { toggleViewCustomize, endViewCustomize, applyPageLayout } from "./viewcustom.js";
import { pick } from "./words.js";
import { ensureViewLayouts } from "./layoutstore.js";
import { renderData } from "./context.js";

applyTheme(Object.assign({}, THEME_DEFAULT, localJSON("gf.theme", {})));

// -- sign-in ----------------------------------------------------------------------------------------

function showSignIn(message) {
  clearTimeout(S.timer);
  document.documentElement.classList.add("signed-out");
  if (S.enforcedSignIn) {
    // Access is enforced: people sign in through the organisation's sign-in, at IT's proxy.
    fill($("#main"), h("div", { class: "signin" }, h("div", { class: "card signin-card" },
      h("span", { class: "card-ic big" }, icon("key")),
      h("h1", null, "Sign in"),
      message ? h("p", { class: "toast-inline warning" }, icon("alert"), message) : null,
      h("p", null, "This cockpit signs you in through your organisation's sign-in. Your name and the personas "
        + "you may act as come from it, as IT set them."),
      button("Sign in again", { icon: "key", kind: "primary", onclick: () => { location.reload(); } }))));
    return;
  }
  fill($("#main"), h("div", { class: "signin" }, h("div", { class: "card signin-card" },
    h("span", { class: "card-ic big" }, icon("key")),
    h("h1", null, "Sign in"),
    message ? h("p", { class: "toast-inline warning" }, icon("alert"), message) : null,
    h("p", null, "Open the one-use link that ", h("code", null, "python -m cockpit.server"),
      " printed when it started. It signs this tab in once; the session lives in this tab only."),
    h("p", { class: "muted small" }, "For a second tab, use “Open in another browser tab” in the person menu of a signed-in tab, "
      + "or restart the server for a new link. From another machine, open an SSH tunnel to the same port first: ",
    h("code", null, "ssh -L 8787:127.0.0.1:8787 <host>"), "."))));
}
setSignedOutHandler(showSignIn);

async function signIn(bootstrap) {
  const res = await fetch("/auth", { method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store",
    credentials: CREDENTIALS, body: JSON.stringify(bootstrap ? { bootstrap } : {}) });
  let data = {};
  try { data = await res.json(); } catch (e) { data = {}; }
  if (data.access === "enforced") S.enforcedSignIn = true;
  if (!res.ok || !data.token) throw new Error(data.error || "the sign-in link was refused");
  return data.token;
}

/* The one-use link, #k=<bootstrap> in the address. It is read when the page opens and whenever the address
   changes, so a link pasted into a signed-out tab (or one whose session ended) signs it in at once, as the
   sign-in card says. Answers whether the address held a link. */
async function useLink() {
  const m = /^#k=([A-Za-z0-9_-]+)/.exec(location.hash || "");
  if (!m) return false;
  history.replaceState(null, "", location.pathname + "#/home");
  try {
    S.token = await signIn(m[1]);
    store.set("gf.token", S.token);
  } catch (e) {
    S.token = store.get("gf.token");
    if (!S.token) showSignIn(e.message);
  }
  return true;
}

// -- access: who signs (kernel/access.py) ------------------------------------------------------------

function enforced() { return !!(S.meta && S.meta.access && S.meta.access.mode === "enforced"); }

// The personas offered: every one for a single operator; with access enforced, those granted on the open
// project (outside a project, those granted anywhere). The server refuses any other.
function offeredPersonas() {
  if (!enforced()) return S.personas;
  const grants = S.meta.access.grants || [];
  const pid = S.route && S.route.name === "project" ? S.route.pid : null;
  return S.personas.filter((p) => grants.some((g) => g.persona === p.id
    && (!pid || g.scope === "*" || (Array.isArray(g.scope) && g.scope.includes(pid)))));
}

function drawAccess() {
  const a = (S.meta && S.meta.access) || {};
  // a single operator's note in the reader's words: who uses the cockpit and where the role is chosen
  const said = !enforced() && a.note ? pick("Only you use this cockpit", a.note) : a.note || "";
  $("#access-note-text").textContent = said;
  $("#access-note").dataset.tip = !enforced() && a.note
    ? pick("Only you use this cockpit: pick your role in the menu on the right. Each decision is signed with the name and role you pick.", a.note) : a.note || "";
  $("#access-pop").textContent = a.detail || a.note || "";   // enforced: the sign-in, its end, where untrusted code runs
  for (const id of ["#access-note", "#access-pop"]) $(id).hidden = !a.note;
  $("#access-note").classList.toggle("enforced", enforced());
  if (!enforced()) return;
  S.person = a.name || "";              // the verified name: not typed, not editable
  const input = $("#person");
  input.value = S.person;
  input.readOnly = true;
  $("#newlink").hidden = true;          // another tab signs in through the organisation's sign-in too
  drawPersonChip();
}

// With access enforced, a persona not granted where the person now is gives way to the first that is.
function keepGrantedPersona() {
  if (!enforced()) return;
  const offered = offeredPersonas();
  if (!offered.length || offered.some((p) => p.id === S.persona)) return;
  S.persona = offered[0].id;
  S.lens = lensFor(S.persona);
  drawPersonChip();
  drawLens();
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

// The persona radios are drawn once and afterwards only checked: drawing them again would take the focus
// from the radio an arrow key has just chosen, and the next arrow would do nothing.
function drawPersonaList() {
  const list = $("#persona-list");
  const offered = offeredPersonas();
  if (!offered.length) {
    fill(list, h("p", { class: "muted small" }, "No persona is granted to you here. IT grants personas in the access file."));
    $("#persona-note").textContent = "";
    return;
  }
  const radios = $$("input[type=radio]", list);
  if (radios.length !== offered.length || radios.some((r, i) => r.value !== offered[i].id)) {
    fill(list, offered.map((p) => {
      const id = "pp-" + p.id;
      const r = h("input", { type: "radio", name: "pp-persona", id, value: p.id, checked: p.id === S.persona });
      r.addEventListener("change", () => setPersona(p.id));
      return h("div", { class: "pp-opt" }, r, h("label", { for: id }, h("b", null, p.label),
        h("small", null, "sees the " + String((((S.meta && S.meta.lenses) || {})[p.lens] || {}).label || "").toLowerCase() + " view")));
    }));
  } else {
    radios.forEach((r) => { r.checked = r.value === S.persona; });
  }
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
  drawAccess();                         // the access note is said in the new role's words
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
// Closing by Done or Esc gives the focus back to the chip that opened the menu; a click elsewhere leaves it
// where the click put it.
function closePerson(refocus) {
  const pop = $("#person-pop");
  if (pop.hidden) return;
  pop.hidden = true;
  $("#person-chip").setAttribute("aria-expanded", "false");
  $("#linkbox").hidden = true;
  if (refocus) $("#person-chip").focus();
}
nav.openPerson = openPerson;
// A name and a persona set elsewhere (the first-run choice) show in the person menu at once.
nav.personChanged = () => { $("#person").value = S.person; S.lens = lensFor(S.persona); drawPersonChip(); drawLens(); };

function wirePerson() {
  S.person = store.get("gf.person") || "";
  const input = $("#person");
  input.value = S.person;
  input.addEventListener("input", () => { S.person = input.value; store.set("gf.person", input.value); drawPersonChip(); });
  input.addEventListener("change", () => { if (S.route && S.route.name === "home") route(true); });
  $("#person-chip").addEventListener("click", () => openPerson(false));
  $("#pp-done").addEventListener("click", () => closePerson(true));
  $("#person-pop").addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); closePerson(true); } });
  document.addEventListener("pointerdown", (e) => {
    const pop = $("#person-pop");
    if (!pop.hidden && !pop.contains(e.target) && !$("#person-chip").contains(e.target)) closePerson(false);
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

/* The lens switcher is an ARIA radiogroup: one tab stop (the chosen lens), the arrow keys (and Home, End)
   move and choose within it, and choosing keeps the focus on the lens. The buttons are drawn once and then
   only marked, so the focused one is never replaced. */
function drawLens() {
  const lenses = (S.meta && S.meta.lenses) || {};
  const box = $("#lens-switch");
  const keys = Object.keys(lenses);
  if ($$(".lens-b", box).map((b) => b.dataset.lens).join(" ") !== keys.join(" ")) {
    fill(box, keys.map((k) => {
      // what a lens changes, on hover and focus: the view of Home and the order of a project's views
      const b = h("button", { type: "button", role: "radio", class: "lens-b", "data-lens": k,
        tip: "View as " + lenses[k].label + ": " + lenses[k].question + " Home and each project show what this view needs first." },
        icon(LENS_ICON[k] || "eye"), h("span", { class: "lbl" }, lenses[k].label));
      b.addEventListener("click", () => chooseLens(k));
      return b;
    }));
  }
  $$(".lens-b", box).forEach((b) => {
    const on = b.dataset.lens === S.lens;
    b.setAttribute("aria-checked", String(on));
    b.tabIndex = on ? 0 : -1;
  });
}
function chooseLens(k) {
  if (k === S.lens) return;
  S.lens = k;
  store.set("gf.lens." + S.persona, k);
  drawLens();
  route(true);
}
function wireLens() {
  const box = $("#lens-switch");
  box.addEventListener("keydown", (e) => {
    const all = $$(".lens-b", box);
    const i = all.indexOf(document.activeElement);
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (i < 0 || (!step && e.key !== "Home" && e.key !== "End")) return;
    e.preventDefault();
    const j = e.key === "Home" ? 0 : e.key === "End" ? all.length - 1 : (i + step + all.length) % all.length;
    all[j].focus();
    chooseLens(all[j].dataset.lens);
  });
}

// -- the sidebar, the top bar and the bottom bar ----------------------------------------------------

// Review first (since you last looked, FR-REV1); Health is the checks, Insights the dimensions: each once.
const NAV_ORDER = ["review_all", "home", "square", "catalogue", "projects", "inbox_all", "insights_all", "floor",
  "jobs", "automations_all"];
NAV_ORDER.push("health_all");                       // Health across every project (health.js, FR-CHK1)
const PAGE_ROUTE = { home: "#/home", square: "#/square", catalogue: "#/catalogue", projects: "#/projects",
  inbox_all: "#/inbox", insights_all: "#/insights", floor: "#/floor", jobs: "#/jobs", settings: "#/settings",
  automations_all: "#/automations", review_all: "#/review" };
PAGE_ROUTE.health_all = "#/health";
NAV_ORDER.push("agents_all");                       // Agent activity across every project (agents.js, FR-CHN1)
PAGE_ROUTE.agents_all = "#/agents";
NAV_ORDER.push("data_all");                         // Data and context, factory-wide (context.js, FR-CTX1)
PAGE_ROUTE.data_all = "#/data";
NAV_ORDER.push("graph_all");                        // the Knowledge graph across projects (graph.js, FR-GRV1)
PAGE_ROUTE.graph_all = "#/graph";
const IN_PROJECT_PAGES = NAV_ORDER;   // the factory's pages stay reachable from inside a project, under "Factory"

/* A page in the sidebar. Its label is hidden in the icon rail, where the tooltip carries it and what its
   badge counts. A note the badge alone shows (the cells running now) is a tooltip at every width, on
   keyboard focus as on hover, and its words are in the link's name. */
function navItem(id, extra, note, everyWidth) {
  const pg = PAGES[id];
  const on = S.route && S.route.name === id;
  const label = scopedLabel(id);   // "Inbox · all projects": a page that exists per project too says it is about all
  return h("a", { class: "nav-i" + (everyWidth ? "" : " rail-tip") + (on ? " on" : ""), href: PAGE_ROUTE[id], "aria-current": on ? "page" : null,
    "data-tip": note ? label + ": " + note : label }, icon(pg.icon), h("span", { class: "lbl" }, pg.label,
    ALL_SCOPE.has(id) ? h("small", { class: "lbl-scope" }, " · all projects") : null), extra || null);
}

// The sidebar and the bottom bar are drawn again after every route and count: a focused link or button in
// them is found again by its address (or id) in the same list it was in (the pages, the project's views,
// the foot or the bottom bar), so the focus stays where the person left it. Only within that list is an
// address unique: the brand at the top of the sidebar goes to Home as the Home page link does.
function keepFocus(roots, draw) {
  const a = document.activeElement;
  const root = a ? roots.find((r) => r.contains(a)) : null;
  const box = root && a.parentElement ? a.parentElement.closest("[id]") : null;
  const href = root ? a.getAttribute("href") : null;
  const id = root ? a.id : null;
  draw();
  if (!root || a.isConnected) return;
  const within = box && box.isConnected && root.contains(box) ? box : root;
  const again = $$("a, button", within).find((el) => (id && el.id === id) || (href && el.getAttribute("href") === href));
  if (again) again.focus({ preventScroll: true });
}

function refreshSidebar() {
  keepFocus([$("#sidebar"), $("#bottombar")], drawSidebar);
}
function drawSidebar() {
  const running = (S.projects || []).filter((p) => p.running).length;   // a running cell, never a guess
  const waiting = S.inboxCount ? S.inboxCount + " waiting on you" : "";
  const live = running === 1 ? "1 cell running now" : running + " cells running now";
  const inProject = S.route && S.route.name === "project";
  // In a project the sidebar is the project's: its name, back to all projects, the recent ones to switch to, and
  // a short way to the factory's pages. Its views are the capsules on the page, never a second copy here.
  const pages = inProject ? IN_PROJECT_PAGES : NAV_ORDER;
  const items = pages.filter(pageOn).map((id) => {   // only the pages of modules that are on
    if (id === "inbox_all" && S.inboxCount) {
      return navItem(id, h("span", { class: "count", "aria-label": waiting }, String(S.inboxCount)), waiting);
    }
    if (id === "projects" && running) {
      return navItem(id, h("span", { class: "live-badge" }, h("span", { class: "live-dot pulse" }),
        h("span", { class: "live-n", "aria-hidden": "true" }, String(running)), h("span", { class: "vh" }, live)), live, true);
    }
    return navItem(id);
  });
  const pv = inProject ? S.projectViews : null;
  fill($("#sb-nav"), inProject ? [projectSidebar(S.route.pid, pv ? pv.inbox : 0),
    h("div", { class: "sb-sec" }, h("span", { class: "lbl" }, "Factory")), items] : items);
  const sbp = $("#sb-project");
  sbp.hidden = true;
  fill(sbp);
  fill($("#sb-foot"), navItem("settings"));
  $("#sb-new").hidden = !moduleShows("controls", "new_project");   // a new project starts with the intake module
  fill($("#bottombar"), [["home", "Home"], ["square", PAGES.square.label], ["inbox_all", "Inbox"], ["projects", "Projects"]].filter(([id]) => pageOn(id)).map(([id, lbl]) => {
    const on = S.route && S.route.name === id;
    return h("a", { href: PAGE_ROUTE[id], class: on ? "on" : null, "aria-current": on ? "page" : null }, icon(PAGES[id].icon),
      h("span", null, lbl), id === "inbox_all" && S.inboxCount ? h("span", { class: "count", "aria-label": waiting }, String(S.inboxCount)) : null);
  }).concat([h("button", { type: "button", id: "bb-ask", "aria-controls": "assistant", "aria-expanded": String(assistantOpen()),
    onclick: () => (assistantOpen() ? closeAssistant() : openAssistant()) }, icon("bot"), h("span", null, "Ask"))]));
}

// The scope bar replaces the breadcrumb: all projects or one project, its capsule and view (scope.js).
function crumbs() { drawScope(); }

nav.refreshShell = () => { refreshSidebar(); crumbs(); };

async function refreshCounts() {
  try {
    const [projects, inbox] = await Promise.all([api("GET", "/api/projects"), api("GET", "/api/inbox?persona=" + enc(S.persona))]);
    S.projects = projects;
    S.inboxCount = inbox.count;
    refreshSidebar();
  } catch (e) { /* the shell keeps what it had */ }
}

// The icon rail: the collapse button says what it will do, in its name and its tooltip, also after a reload.
function drawRail(on) {
  document.documentElement.classList.toggle("rail", on);
  const b = $("#sb-collapse");
  const label = on ? "Expand the sidebar" : "Collapse the sidebar";
  b.setAttribute("aria-expanded", String(!on));
  b.setAttribute("aria-label", label);
  b.setAttribute("data-tip", label);
}

/* Below 901px the sidebar is a navigation overlay opened from the menu button. While it is closed it is
   hidden (so its links are not in the tab order); open, it takes the focus, and a click outside it, its
   close button, Esc or tabbing out of it closes it. Closing by the close button, Esc or the backdrop gives
   the focus back to the menu button; following a link gives it to the new page's heading. */
function navOpen() { return document.documentElement.classList.contains("nav-open"); }
function setNav(open, refocus) {
  const was = navOpen();
  document.documentElement.classList.toggle("nav-open", open);
  $("#tb-menu").setAttribute("aria-expanded", String(open));
  if (open && !was) {
    const first = $("#sidebar .nav-i[aria-current]") || $("#sidebar .nav-i");
    if (first) first.focus();
  } else if (!open && was && refocus) {
    $("#tb-menu").focus();
  }
}
function wireNav() {
  $("#tb-menu").addEventListener("click", () => setNav(!navOpen(), false));
  $("#sb-close").addEventListener("click", () => setNav(false, true));
  $("#sidebar").addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (!a || !navOpen()) return;
    const same = a.getAttribute("href") === location.hash;
    if (!same) S.jumped = true;
    setNav(false, same);
  });
  document.addEventListener("click", (e) => {
    if (!navOpen() || $("#sidebar").contains(e.target) || $("#tb-menu").contains(e.target)) return;
    if (e.target.closest && e.target.closest("dialog, .popover, .toasts")) return;
    setNav(false, e.target === $("#shell"));   // the backdrop
  });
  // Tabbing out of the overlay either way (forward into the page, back to the skip link) closes it; a dialog,
  // menu or toast opened from it keeps it open, as a click there does.
  document.addEventListener("focusin", (e) => {
    const t = e.target;
    if (!navOpen() || !(t instanceof Element) || $("#sidebar").contains(t) || t.closest("dialog, .popover, .toasts")) return;
    setNav(false, false);
  });
}

/* A theme change from the top bar is shown at once and kept with the layout of the person, persona and lens
   in view. The layout in memory may be the one Home loaded for another persona, lens or person (the switch
   was made on another page, or Home is still drawing the new one), so it is read again first, and the theme
   is never saved under the wrong lens or for the wrong persona. Only a Customize session or an assistant's
   preview shown on Home keeps its own layout. What is kept is the theme on screen with the change. The
   changes are kept one after another, so a second choice made before the first is saved builds on it. */
let themeQueue = Promise.resolve();
function changeTheme(changes) {
  const free = !S.customizing && !previewing();
  if (free) applyTheme(Object.assign({}, S.theme || currentTheme(), changes));
  themeQueue = themeQueue.then(() => keepTheme(changes, free))
    .catch((e) => { if (!(e instanceof AuthError)) say("The theme is shown here but was not saved: " + e.message, "warning"); });
  return themeQueue;
}
async function keepTheme(changes, free) {
  const home = !!S.route && S.route.name === "home";
  if (!S.customizing && S.person.trim() && !(home && previewing())) {
    try {
      await loadLayout();
    } catch (e) {
      if (e instanceof AuthError) return;
      await setTheme(Object.assign({}, S.theme, changes), { save: false });
      say("The theme is shown here but was not saved with your layout: " + e.message, "warning");
      return;
    }
  }
  await setTheme(free ? Object.assign({}, S.theme, changes) : changes);
}
function shownTheme() { return S.theme || currentTheme(); }

function wireShell() {
  drawRail(local.get("gf.rail") === "1");
  $("#sb-collapse").addEventListener("click", () => {
    const on = !document.documentElement.classList.contains("rail");
    drawRail(on);
    local.set("gf.rail", on ? "1" : "");
    hideTip();   // the pointer is still on the button: its next move shows the new tooltip
  });
  wireNav();
  wireLens();
  $("#sb-new").addEventListener("click", () => newProjectModal());
  // The top bar is sticky: main's top goes just below it, so the page's heading is never hidden under the bar.
  $("#skip").addEventListener("click", (e) => {
    e.preventDefault();
    const main = $("#main");
    main.focus({ preventScroll: true });
    const top = main.getBoundingClientRect().top + window.scrollY - $("#topbar").offsetHeight;
    if (window.scrollY > top) window.scrollTo(0, Math.max(0, top));
  });
  // Customize on every page: Home's widget grid, or the sections (and a project's tabs) of the view shown.
  $("#customize").addEventListener("click", () => (S.route && S.route.name === "home" ? toggleCustomize() : toggleViewCustomize()));
  $("#density").addEventListener("click", () => changeTheme({ density: shownTheme().density === "compact" ? "comfortable" : "compact" }));
  $("#theme").addEventListener("click", () => {
    const t = shownTheme();
    openMenu($("#theme"), [{ group: "Mode" }].concat([["dark", "Dark", "moon"], ["light", "Light", "sun"], ["system", "System", "monitor"]].map(([v, l, ic]) =>
      ({ label: l, icon: ic, checked: t.mode === v, onclick: () => changeTheme({ mode: v }) })),
    [{ sep: true }, { group: "Accent" }], ACCENTS.map((a) => ({ label: a.charAt(0).toUpperCase() + a.slice(1), checked: t.accent === a,
      onclick: () => changeTheme({ accent: a }) })),
    [{ sep: true }, { group: "Corners" }], [["soft", "Soft"], ["crisp", "Crisp"]].map(([v, l]) => ({ label: l, checked: t.radius === v, onclick: () => changeTheme({ radius: v }) }))), "Theme");
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => applyTheme(shownTheme()));
  // The phone's Ask says whether the assistant is open, as Ask Rihma does; closing it there gives the focus
  // back to Ask (Ask Rihma is hidden at that width).
  new MutationObserver(() => {
    const bb = $("#bb-ask");
    if (!bb) return;
    const open = assistantOpen();
    bb.setAttribute("aria-expanded", String(open));
    const a = document.activeElement;
    if (!open && bb.offsetParent !== null && (!a || a === document.body || $("#assistant").contains(a))) bb.focus();
  }).observe($("#assistant"), { attributes: true, attributeFilter: ["hidden"] });
}

// -- routing ----------------------------------------------------------------------------------------

function parseRoute() {
  // a query after the route is a view's own (the Knowledge graph's filters, FR-GRV1): it names no page
  const parts = (location.hash || "").split("?")[0].replace(/^#\/?/, "").split("/").filter(Boolean).map((x) => {
    try { return decodeURIComponent(x); } catch (e) { return x; }
  });
  if (parts[0] === "p" && parts[1]) {
    const view = parts[2] && PROJECT_VIEWS.includes(parts[2]) ? parts[2] : null;
    return { name: "project", pid: parts[1], view, focus: parts[3] || null };
  }
  const name = { inbox: "inbox_all", insights: "insights_all", automations: "automations_all",
    health: "health_all", review: "review_all", agents: "agents_all", data: "data_all",
    graph: "graph_all" }[parts[0]] || parts[0];
  if (name === "shape") return { name, id: parts[1] || null };   // a conversation: #/shape/SH-001
  if (name === "runners") return { name, id: parts[1] || null }; // a project's runners: #/runners/<pid>
  if (TOP_PAGES.includes(name)) return { name };
  return { name: "home" };
}

const RENDER = {
  home: renderHome, square: renderSquare, catalogue: renderCatalogue, projects: renderProjectsPage, inbox_all: renderInboxAll,
  floor: renderFloor, jobs: renderJobs, settings: renderSettings, shape: renderShape, models: renderModels, runners: renderRunners,
  automations_all: renderAutomations, insights_all: renderInsights, review_all: renderReview,
};
RENDER.health_all = renderHealth;
RENDER.agents_all = renderAgentActivity;
RENDER.data_all = renderData;
RENDER.graph_all = renderGraphPage;
void PAGE_ROUTES;

async function route(keep) {
  if (!S.token) return;
  clearTimeout(S.timer);
  stopLive();
  LIVE.el = null;
  closeMenu();
  const r = parseRoute();
  const same = S.route && S.route.name === r.name && S.route.pid === r.pid && S.route.view === r.view && S.route.focus === r.focus
    && S.route.id === r.id;
  if (!same) endViewCustomize();   // each view is customized on its own
  S.route = r;
  keepGrantedPersona();
  const seq = ++S.seq;
  if (r.name !== "project") { S.project = null; S.projectViews = null; }
  document.documentElement.classList.toggle("on-home", r.name === "home");
  if (!keep && !same) window.scrollTo(0, 0);   // a new page opens at its top; a re-render keeps the place
  refreshSidebar();
  crumbs();
  onRouteChange();
  const main = $("#main");
  try {
    await ensureViewLayouts();             // the person's own layouts, from the server (layoutstore.js); never throws
    if (seq !== S.seq) return;
    if (r.name === "project") {
      const shown = await renderProject(r, keep || same, seq);
      if (shown && !keep && !same) showFocus(r.focus);
    } else if (!pageOn(r.name)) {
      offPage(r.name);                       // a page whose module is off says so, and where to turn it on
    } else {
      await RENDER[r.name](seq);
      if (seq === S.seq && r.name !== "home") applyPageLayout(r.name);   // the person's layout of this page
    }
    if (seq === S.seq) { main.dataset.loaded = "1"; crumbs(); refreshSidebar(); }   // what is shown now stays
    if (S.jumped && seq === S.seq) {
      S.jumped = false;
      if (!r.focus) { const t = $("#view-title"); if (t) t.focus(); }
    }
  } catch (e) {
    if (e instanceof AuthError || seq !== S.seq) return;
    // an error stays on screen: a loading placeholder still waiting to be drawn never replaces it
    main.dataset.loaded = "1";
    fill(main, pageHead("Something went wrong", null), empty("alert", e.message,
      button("Back to Home", { icon: "home", onclick: () => { location.hash = "#/home"; } })));
    if (S.jumped) { S.jumped = false; $("#view-title").focus(); }   // a jump lands on the error's heading
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
nav.newProject = (opts) => newProjectModal(opts);
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
    if (e.key === "Escape" && navOpen() && !$("#modal").open && !$("#palette").open) {
      const a = document.activeElement;
      setNav(false, !a || a === document.body || $("#sidebar").contains(a));
    }
  });
}

// -- start ------------------------------------------------------------------------------------------

let started = false;
// After a sign-in: the personas and the meta are read once, then the shell is drawn and the page routed.
async function start() {
  if (!S.token) { showSignIn(); return; }
  if (started) {
    document.documentElement.classList.remove("signed-out");
    route();
    return;
  }
  try {
    const [personas, meta] = await Promise.all([api("GET", "/api/personas"), api("GET", "/api/meta")]);
    S.personas = personas;
    S.meta = meta;
  } catch (e) {
    if (!(e instanceof AuthError)) say(e.message, "critical");
    return;
  }
  await loadModules().catch(() => null);   // the parts of Rihmasto in use; everything shows until read
  started = true;
  document.documentElement.classList.remove("signed-out");
  const saved = store.get("gf.persona");
  if (saved && S.personas.some((p) => p.id === saved)) S.persona = saved;
  S.lens = lensFor(S.persona);
  S.oneAtATime = store.get("gf.oneatatime") === "1";
  drawAccess();
  drawPersonChip();
  drawLens();
  await route();
  firstRun();                              // a new factory home: where to start (kernel/modules.py presets)
  resumeWalk();                            // a walkthrough that was going (walkthrough.js, FR-WLK1)
  resumeGuide();                           // a guide that was going (journey.js, FR-JRN1)
}

async function boot() {
  wireTips();
  wireModal();
  wirePerson();
  wireShell();
  wirePalette();
  wireAssistant();
  wireKeys();
  window.addEventListener("hashchange", async () => {
    if (await useLink()) { if (S.token) start(); return; }
    if (started) route();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopLive();
    else if (LIVE.el && LIVE.el.isConnected) startLive();
  });
  if (!(await useLink())) {
    S.token = store.get("gf.token");
    // No link and no session: with access enforced (the page says so), the organisation's sign-in at IT's
    // proxy opens one. A single operator's page asks for nothing until a sign-in link is opened.
    const mode = document.querySelector('meta[name="rihmasto-access"]');
    if (mode && mode.content === "enforced") S.enforcedSignIn = true;
    if (!S.token && S.enforcedSignIn) {
      try { S.token = await signIn(null); store.set("gf.token", S.token); }
      catch (e) { S.token = null; showSignIn(e.message); return; }
    }
  }
  start();
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
void avatar; void FACTORY_PID;
