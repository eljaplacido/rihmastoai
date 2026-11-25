/* Jump to (Ctrl/Cmd+K): a modal dialog, labelled, with a combobox over a listbox. It jumps to any
   page, project, view of the open project, or open card. The focus stays inside while it is open
   and goes back where it was when it closes. */

import { S, $, h, fill, api, plural, link, closeModal, PAGES, VIEWS, FACTORY_VIEWS, KIND_LABEL, icon } from "./core.js";
import { pageOn, viewOn } from "./modules.js";

const PAL = { items: [], shown: [], active: 0, opener: null };

function isPlanCard(c) { return !!c && c.kind === "approval" && (c.refs || {}).scope === "plan"; }
function cardHref(pid, c) {
  const refs = c.refs || {};
  if (isPlanCard(c)) return link(pid, "plan");
  if (c.kind === "question" && refs.question) return link(pid, "questions", refs.question);
  if (c.kind === "change") return link(pid, "changes", c.id);
  return link(pid, "inbox", c.id);
}
const PAGE_HREF = { home: "#/home", square: "#/square", catalogue: "#/catalogue", projects: "#/projects", inbox_all: "#/inbox",
  floor: "#/floor", jobs: "#/jobs", settings: "#/settings", insights_all: "#/insights" };

// Every view of the open project: first the ones its stage and the lens bring forward (its tabs), then the
// rest, so a view the tabs leave out (the ledger, the cell) is still one jump away, at every width. The plan
// is a view only while its approval is open, as in the tabs.
function projectViews(pv) {
  const first = (pv && pv.views) || [];
  return first.concat(Object.keys(VIEWS).filter((v) => !first.includes(v) && (v !== "plan" || (pv && pv.planOpen))));
}

function items() {
  const out = Object.entries(PAGES).filter(([k]) => pageOn(k)).map(([k, v]) => ({ group: "Page", label: v.label, icon: v.icon, href: PAGE_HREF[k],
    sub: { home: "the dashboard for your lens", square: "the delivery square", catalogue: "every capability",
      projects: "every project and what it is doing", inbox_all: "what waits on you across projects",
      floor: "how the factory performs", insights_all: "health to token usage, from the records", jobs: "background runs started here", settings: "embeds, appearance, sign-in links" }[k] }));
  (S.projects || []).forEach((p) => out.push({ group: "Project", icon: p.factory ? "sparkles" : "folder", label: p.title,
    sub: p.factory ? "the factory's own proposals" : (p.now ? p.now.line : p.id), href: p.factory ? link(p.id, "inbox") : "#/p/" + encodeURIComponent(p.id) }));
  const cur = S.route && S.route.name === "project" ? S.project : null;
  if (cur) {
    const pid = cur.meta.id;
    const views = cur.meta.factory ? FACTORY_VIEWS : projectViews(S.projectViews).filter((v) => viewOn(v, pid));
    views.forEach((v) => out.push({ group: "View", icon: VIEWS[v].icon, label: VIEWS[v].label, sub: cur.meta.title, href: link(pid, v) }));
    (cur.open_cards || []).forEach((c) => out.push({ group: "Open card", icon: "inbox",
      label: c.id + " · " + (KIND_LABEL[c.kind] || c.kind) + ": " + c.title, sub: cur.meta.title, href: cardHref(pid, c) }));
  }
  return out;
}

function setActive(i, scroll) {
  PAL.active = i;
  const input = $("#pal-q");
  $("#pal-list").querySelectorAll("[role=option]").forEach((el, n) => {
    el.setAttribute("aria-selected", n === i ? "true" : "false");
    if (n === i && scroll) el.scrollIntoView({ block: "nearest" });
  });
  if (PAL.shown.length) input.setAttribute("aria-activedescendant", "pal-o-" + i);
  else input.removeAttribute("aria-activedescendant");
}

function render() {
  const query = $("#pal-q").value.trim().toLowerCase();
  const terms = query.split(/\s+/).filter(Boolean);
  const scored = [];
  PAL.items.forEach((it, i) => {
    const hay = (it.label + " " + (it.sub || "") + " " + it.group).toLowerCase();
    if (!terms.every((t) => hay.includes(t))) return;
    const lab = it.label.toLowerCase();
    const score = !terms.length ? 0 : lab.startsWith(terms[0]) ? 0 : lab.includes(terms[0]) ? 1 : 2;
    scored.push([score, i, it]);
  });
  scored.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  PAL.shown = scored.slice(0, 60).map((x) => x[2]);
  fill($("#pal-list"), PAL.shown.map((it, i) => h("li", {
    id: "pal-o-" + i, role: "option", "aria-selected": "false", class: "pal-o",
    onclick: () => go(i), onmousemove: () => { if (PAL.active !== i) setActive(i, false); },
  }, h("span", { class: "pal-ic" }, icon(it.icon || "arrow-right")), h("span", { class: "pal-l" }, it.label),
  it.sub ? h("span", { class: "pal-s" }, it.sub) : null, h("span", { class: "pal-g" }, it.group))));
  const emptyEl = $("#pal-empty");
  emptyEl.hidden = PAL.shown.length > 0;
  emptyEl.textContent = PAL.shown.length ? "" : "Nothing matches “" + query + "”.";
  $("#pal-count").textContent = PAL.shown.length ? plural(PAL.shown.length, "match", "matches") : "No matches";
  setActive(Math.min(PAL.active, Math.max(0, PAL.shown.length - 1)), true);
}

export function openPalette() {
  const dlg = $("#palette");
  if (!S.token || !S.meta || dlg.open) return;
  PAL.opener = document.activeElement;
  PAL.items = items();
  PAL.active = 0;
  $("#pal-q").value = "";
  dlg.showModal();
  $("#pal-q").focus();
  render();
  api("GET", "/api/projects").then((projects) => {
    S.projects = projects;
    if (dlg.open) { PAL.items = items(); render(); }
  }).catch(() => { /* the list keeps what it had */ });
}

function close(restore) {
  const dlg = $("#palette");
  const back = PAL.opener;
  PAL.opener = null;
  if (dlg.open) dlg.close();
  if (restore === false) return;
  if (back && back.isConnected && back !== document.body && typeof back.focus === "function") back.focus();
  else $("#main").focus();
}

function go(i) {
  const it = PAL.shown[i];
  if (!it) return;
  const overModal = $("#modal").open;
  if (location.hash === it.href && !overModal) { close(); return; }
  close(false);
  // a jump leaves the page: a dialog open under the palette (New project) closes with it
  if (overModal) closeModal();
  if (location.hash === it.href) return;   // the dialog gives the focus back to the control that opened it
  S.jumped = true;
  location.hash = it.href;
}

export function wirePalette() {
  const dlg = $("#palette");
  const input = $("#pal-q");
  if (/Mac|iPhone|iPad/.test(navigator.platform || "")) $("#jump-key").textContent = "⌘ K";
  $("#jump").addEventListener("click", openPalette);
  $("#pal-close").addEventListener("click", () => close());
  input.addEventListener("input", () => { PAL.active = 0; render(); });
  input.addEventListener("keydown", (e) => {
    const n = PAL.shown.length;
    if (e.key === "ArrowDown" && n) { e.preventDefault(); setActive((PAL.active + 1) % n, true); }
    else if (e.key === "ArrowUp" && n) { e.preventDefault(); setActive((PAL.active - 1 + n) % n, true); }
    else if (e.key === "Enter") { e.preventDefault(); go(PAL.active); }
  });
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  dlg.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); close(); return; }
    if (e.key !== "Tab") return;
    const stops = Array.from(dlg.querySelectorAll("input,button")).filter((el) => !el.disabled);
    const at = stops.indexOf(document.activeElement);
    e.preventDefault();
    stops[(at + (e.shiftKey ? -1 : 1) + stops.length) % stops.length].focus();
  });
  dlg.addEventListener("click", (e) => { if (e.target === dlg) close(); });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      if (dlg.open) close(); else openPalette();
    }
  });
}
