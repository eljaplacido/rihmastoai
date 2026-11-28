/* Scope: is the person looking at one project or at all of them (FR-UXO1)? The owner: "it's not clear when you
   view a single project and when not; transitions are not clear and which views are about what project."

   The scope bar at the top of the main area says it: "All projects", or "Project: <title> ▾" with a switcher that
   lists the projects (the recent ones first) and "← All projects". Inside a project the whole frame takes the
   project's accent (a coloured top edge, the project's name in the bar), so a project page is unmistakable, and
   every page title states its scope ("Webshop · Inbox", "Inbox · all projects"). */

import { S, $, h, fill, icon, enc, local, openMenu, PAGES, VIEWS, FACTORY_PID, ALL_SCOPE_PAGES, plural } from "./core.js";
import { CAPSULES, capsuleOf, labelOf } from "./capsules.js";
import { word, factoryWord } from "./words.js";

const RECENT = "gf.recent";
const RECENT_MAX = 8;
// The pages that exist per project too: outside a project they are about every project, and say so.
export const ALL_SCOPE = new Set(ALL_SCOPE_PAGES);

export function recentProjects() {
  try { const r = JSON.parse(local.get(RECENT) || "[]"); return Array.isArray(r) ? r : []; } catch (e) { return []; }
}
export function rememberProject(pid) {
  if (!pid || pid === FACTORY_PID) return;
  local.set(RECENT, JSON.stringify([pid].concat(recentProjects().filter((x) => x !== pid)).slice(0, RECENT_MAX)));
}

// A project's accent hue, the same every time for the same project.
export function projectHue(pid) {
  let n = 0;
  for (const ch of String(pid || "")) n = (n * 31 + ch.charCodeAt(0)) % 360;
  return n;
}

// The page's label with its scope: "Inbox · all projects" for a page that exists per project too.
export function scopedLabel(name) {
  const pg = PAGES[name];
  if (!pg) return name;
  return ALL_SCOPE.has(name) ? pg.label + " · all projects" : pg.label;
}
export function projectTitle(pid) {
  if (pid === FACTORY_PID) return factoryWord();
  const p = (S.projects || []).find((x) => x.id === pid);
  return (S.project && S.project.meta && S.project.meta.id === pid && S.project.meta.title) || (p && p.title) || pid;
}

// The projects, recent first, then the rest by title.
function projectsByRecent() {
  const all = (S.projects || []).filter((p) => !p.factory);
  const recent = recentProjects();
  const rank = (p) => { const i = recent.indexOf(p.id); return i < 0 ? 99 : i; };
  return all.slice().sort((a, b) => rank(a) - rank(b) || String(a.title).localeCompare(String(b.title)));
}

export function openSwitcher(anchor) {
  const r = S.route || {};
  const inProject = r.name === "project";
  const recent = recentProjects();
  const list = projectsByRecent();
  const items = [];
  if (inProject) items.push({ label: "← All projects", icon: "chevron-left", onclick: () => { location.hash = "#/projects"; } }, { sep: true });
  const shown = list.filter((p) => recent.includes(p.id));
  if (shown.length) items.push({ group: "Recent" }, ...shown.map((p) => item(p)));
  const rest = list.filter((p) => !recent.includes(p.id));
  if (rest.length) items.push({ group: shown.length ? "Other projects" : "Projects" }, ...rest.map((p) => item(p)));
  if (!list.length) items.push({ label: "No project yet: start one", icon: "plus", onclick: () => { location.hash = "#/projects"; } });
  openMenu(anchor, items, "Switch project");
  function item(p) {
    // switching keeps the view the person is on, when the other project has it
    const view = inProject && r.view ? r.view : "";
    return { label: p.title, icon: "folder", checked: inProject && r.pid === p.id,
      onclick: () => { location.hash = "#/p/" + enc(p.id) + (view ? "/" + view : ""); } };
  }
}

/* The scope bar: drawn after every route. In a project: the project, its capsule and its view; else All projects
   and the page. The frame's accent follows. */
export function drawScope() {
  const bar = $("#scopebar");
  if (!bar) return;
  const r = S.route || {};
  const root = document.documentElement;
  const inProject = r.name === "project";
  root.dataset.scope = inProject ? "project" : "all";
  if (inProject) root.style.setProperty("--proj-h", String(projectHue(r.pid)));
  else root.style.removeProperty("--proj-h");
  const pv = S.projectViews || {};
  const view = inProject ? (pv.current || r.view) : null;
  const switcher = h("button", { type: "button", class: "scope-sw", id: "scope-switch", "data-control": "scope_switch",
    "aria-haspopup": "menu", "aria-expanded": "false", tip: inProject ? "Switch project, or go back to all projects" : "Open one project" },
  inProject ? [h("span", { class: "scope-k" }, "Project:"), h("b", { class: "scope-t" }, projectTitle(r.pid))]
    : [icon("layers"), h("b", { class: "scope-t" }, word("scope.all"))],
  icon("chevron-down", "chev"));
  switcher.addEventListener("click", () => openSwitcher(switcher));
  const trail = [];
  if (inProject && view) {
    const cap = CAPSULES.find((c) => c.id === capsuleOf(view));
    if (cap && r.pid !== FACTORY_PID) trail.push(h("span", { class: "scope-cap" }, cap.label));
    trail.push(h("span", { class: "scope-v", "aria-current": "page" }, labelOf(view) || (VIEWS[view] || {}).label || view));
  } else if (!inProject && PAGES[r.name]) {
    trail.push(h("span", { class: "scope-v", "aria-current": "page" }, scopedLabel(r.name)));
  }
  const back = inProject ? h("a", { class: "scope-back", href: "#/projects", "data-key": "scope:back" }, icon("chevron-left"),
    h("span", { class: "lbl" }, "All projects")) : null;
  fill(bar, back, switcher, trail.map((t) => [icon("chevron-right", "crumb-sep"), t]));
  bar.setAttribute("aria-label", inProject ? "Scope: project " + projectTitle(r.pid) : "Scope: all projects");
}

/* The sidebar inside a project: the project's name, "← All projects", and the recent projects to switch to.
   Not a second copy of the project's views: those are the capsules on the page. */
export function projectSidebar(pid, waiting) {
  const recent = recentProjects().filter((x) => x !== pid).slice(0, 5);
  const others = recent.map((id) => (S.projects || []).find((p) => p.id === id)).filter(Boolean);
  return [
    h("a", { class: "nav-i sb-back rail-tip", href: "#/projects", "data-tip": "All projects", "data-key": "sb:back" },
      icon("chevron-left"), h("span", { class: "lbl" }, "All projects")),
    h("div", { class: "sb-proj rail-tip", "data-tip": projectTitle(pid) },
      h("span", { class: "sb-proj-dot", "aria-hidden": "true" }),
      h("span", { class: "lbl" }, h("small", null, "Project"), h("b", null, projectTitle(pid)),
        waiting ? h("small", { class: "sb-wait" }, plural(waiting, "decision") + (waiting === 1 ? " waits" : " wait") + " for you") : null)),
    others.length ? h("div", { class: "sb-sec" }, h("span", { class: "lbl" }, "Switch to")) : null,
    others.map((p) => h("a", { class: "nav-i sub rail-tip", href: "#/p/" + enc(p.id), "data-tip": p.title },
      icon("folder"), h("span", { class: "lbl" }, p.title))),
  ];
}
