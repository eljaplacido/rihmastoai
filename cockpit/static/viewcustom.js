/* Customize any view (FR-UXO1). The owner: "I see the UIX customization button only on Home; it should work
   across any view." Home keeps its widget grid (dashboard.js); every other page and every project view has
   sections, which a person may show or hide, move up or down, and make compact or wide, per person and view,
   with Reset. In a project, Customize also edits the capsule tabs: hide a tab you never use, pin a favourite to
   the top row (capsules.js). A section that holds a decision waiting on the person is never hidden.

   The layout is kept on the server per person (layoutstore.js, /api/view-layouts), so it follows the person to any
   computer; this browser keeps only a copy. Ask Rihma proposes the same changes in words ("hide the brief", "move
   Needs attention to the top"), shown as a preview first and saved on the server only when kept. */

import { S, $, $$, h, icon, button, say, plural } from "./core.js";
import { resetTabs } from "./capsules.js";
import { viewLayout, saveViewLayoutFor } from "./layoutstore.js";

const SIZES = ["normal", "compact", "wide"];
const SIZE_WORD = { normal: "Normal", compact: "Compact", wide: "Wide" };
const WAITING = ".card.decision, [data-control=\"decide\"], [data-control=\"answer\"], .concept";
const SKIP = ".page-head, .proj-head, .caps, .vcz-bar, .vcz-hidden-note, .q, script, template";
let current = { root: null, key: null };
let preview = null;   // { key, before } while Ask Rihma's proposal is shown

export function loadViewLayout(key) {
  const v = viewLayout(key);
  return { order: Array.isArray(v && v.order) ? v.order.slice() : [], hidden: Array.isArray(v && v.hidden) ? v.hidden.slice() : [],
    size: Object.assign({}, (v && typeof v.size === "object" && v.size) || {}) };
}
// Shown at once; saved on the server unless Ask Rihma's preview is on screen (kept only when the person keeps it).
function saveViewLayout(key, lay, opts) { saveViewLayoutFor(key, lay, opts); }

function slug(s) { return String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40); }
export function sectionLabel(el) {
  const head = el.querySelector("h2, h3, .card-t, .label-h, summary, legend, b");
  const t = ((head && head.textContent) || el.getAttribute("aria-label") || el.textContent || "").replace(/\s+/g, " ").trim();
  return t.slice(0, 60) || "Section";
}
function sectionKey(el, i) {
  return el.dataset.cz || el.dataset.id || el.dataset.type || el.id || slug(sectionLabel(el)) || "s" + i;
}

// The parents whose children are the view's sections: the first element with more than one child.
function parents(root) {
  const kids = (el) => [...el.children].filter((c) => !c.matches(".vcz-hidden-note, .vcz-bar"));   // the shell's own notes
  let box = root;
  while (box && kids(box).length === 1 && !box.matches(".card, section, article")) box = kids(box)[0];
  if (!box) return [];
  if (box.matches(".with-side")) return [...box.children];
  return [box];
}
export function sections(root) {
  const out = [];
  parents(root).forEach((p) => [...p.children].forEach((el, i) => {
    if (el.matches(SKIP) || el.hidden && !el.classList.contains("cz-off")) return;
    if (!el.dataset.czKey) el.dataset.czKey = sectionKey(el, i);
    out.push(el);
  }));
  return out;
}

/* Apply the person's layout to a view that was just drawn: order, sizes, hidden sections (never one that holds a
   decision waiting on them), and a note saying how many are hidden. */
export function applyViewLayout(root, key) {
  current = { root, key };
  if (!root) return;
  const lay = loadViewLayout(key);
  const all = sections(root);
  if (lay.order.length) {
    const rank = (el) => { const i = lay.order.indexOf(el.dataset.czKey); return i < 0 ? 1000 : i; };
    parents(root).forEach((p) => {
      const kids = all.filter((el) => el.parentElement === p);
      const sorted = kids.slice().sort((a, b) => rank(a) - rank(b) || kids.indexOf(a) - kids.indexOf(b));
      const anchor = kids.length ? kids[kids.length - 1].nextSibling : null;
      sorted.forEach((el) => p.insertBefore(el, anchor));
    });
  }
  let hidden = 0;
  all.forEach((el) => {
    const k = el.dataset.czKey;
    SIZES.forEach((s) => el.classList.remove("cz-" + s));
    if (lay.size[k] && lay.size[k] !== "normal") el.classList.add("cz-" + lay.size[k]);
    const wantHidden = lay.hidden.includes(k);
    const waits = wantHidden && el.querySelector(WAITING);
    el.classList.toggle("cz-off", !!wantHidden && !waits);
    el.classList.toggle("cz-kept", !!waits);
    if (wantHidden && !waits) hidden += 1;
  });
  const old = $(".vcz-hidden-note", root);
  if (old) old.remove();
  if (hidden && !S.customizingView) {
    root.append(h("p", { class: "vcz-hidden-note muted small" }, icon("eye"), " " + plural(hidden, "section") + " hidden here. ",
      button("Show them", { kind: "tiny quiet", onclick: () => { toggleViewCustomize(true); } })));
  }
  if (S.customizingView) decorate(root, key);
}

function edit(fn, opts) {
  const lay = loadViewLayout(current.key);
  fn(lay);
  saveViewLayout(current.key, lay, opts);
  applyViewLayout(current.root, current.key);
}
function move(k, dir) {
  edit((lay) => {
    const keys = sections(current.root).map((el) => el.dataset.czKey);
    const i = keys.indexOf(k);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= keys.length) return;
    [keys[i], keys[j]] = [keys[j], keys[i]];
    lay.order = keys;
  });
  const b = $('[data-key="vcz:' + CSS.escape(k) + (dir < 0 ? ':up"]' : ':down"]'));
  if (b) b.focus();
}

// Customize mode: each section carries Up, Down, Size and Hide (or Show).
function decorate(root, key) {
  $$(".vcz-tools", root).forEach((t) => t.remove());
  const lay = loadViewLayout(key);
  sections(root).forEach((el) => {
    const k = el.dataset.czKey;
    const name = sectionLabel(el);
    const size = lay.size[k] || "normal";
    const off = lay.hidden.includes(k);
    const kept = el.classList.contains("cz-kept");
    el.classList.add("vcz-sec");
    el.prepend(h("div", { class: "vcz-tools", role: "group", "aria-label": "Customize " + name },
      h("span", { class: "vcz-name" }, name),
      button(null, { icon: "chevron-left", kind: "tiny quiet up", aria: "Move " + name + " up", key: "vcz:" + k + ":up", onclick: () => move(k, -1) }),
      button(null, { icon: "chevron-right", kind: "tiny quiet down", aria: "Move " + name + " down", key: "vcz:" + k + ":down", onclick: () => move(k, 1) }),
      button("Size: " + SIZE_WORD[size], { icon: "expand", kind: "tiny quiet", key: "vcz:" + k + ":size",
        onclick: () => { edit((l) => { l.size[k] = SIZES[(SIZES.indexOf(size) + 1) % SIZES.length]; }); refocus("vcz:" + k + ":size"); } }),
      kept ? h("span", { class: "muted small" }, "Waits on you: stays shown")
        : button(off ? "Show" : "Hide", { icon: off ? "eye" : "x", kind: "tiny quiet", key: "vcz:" + k + ":hide", "data-control": "customize_view",
          onclick: () => { edit((l) => { l.hidden = off ? l.hidden.filter((x) => x !== k) : l.hidden.concat([k]); }); refocus("vcz:" + k + ":hide"); } })));
  });
}
function refocus(dataKey) { const b = $('[data-key="' + CSS.escape(dataKey) + '"]'); if (b) b.focus(); }

function bar() {
  const inProject = S.route && S.route.name === "project";
  return h("div", { class: "vcz-bar", id: "vcz-bar", role: "region", "aria-label": "Customize this view" },
    icon("sliders"), h("p", null, h("b", null, "Customize this view. "),
      "Hide, move or resize its sections" + (inProject ? "; above, hide tabs you never use or pin one to the top row" : "") + ". Kept for you on every computer you sign in from."),
    h("span", { class: "btns" },
      button("Reset", { icon: "undo", kind: "small quiet", key: "vcz:reset", onclick: () => {
        saveViewLayout(current.key, { order: [], hidden: [], size: {} });
        if (inProject) resetTabs();
        say("This view is back to its default layout.", "good");
        rerender();
      } }),
      button("Done", { icon: "check", kind: "small primary", key: "vcz:done", onclick: () => toggleViewCustomize(false) })));
}
function rerender() {
  if (S.redrawTabs && S.route && S.route.name === "project") S.redrawTabs();
  applyViewLayout(current.root, current.key);
  const old = $("#vcz-bar");
  if (S.customizingView && !old) $("#main").prepend(bar());
  if (!S.customizingView && old) old.remove();
}

/* Customize on any page but Home (Home has its own widget grid): turns the mode on or off for the view shown. */
export function toggleViewCustomize(on) {
  S.customizingView = on === undefined ? !S.customizingView : !!on;
  document.documentElement.classList.toggle("vcz", S.customizingView);
  const btn = $("#customize");
  if (btn) btn.setAttribute("aria-pressed", String(S.customizingView));
  if (!S.customizingView) { $$(".vcz-tools").forEach((t) => t.remove()); $$(".vcz-sec").forEach((el) => el.classList.remove("vcz-sec")); }
  rerender();
  if (S.customizingView) { const f = $("#vcz-bar button"); if (f) f.focus(); } else if (btn) btn.focus();
}
// A new page: the mode ends there (each view is customized on its own).
export function endViewCustomize() {
  if (!S.customizingView) return;
  S.customizingView = false;
  document.documentElement.classList.remove("vcz");
  const btn = $("#customize");
  if (btn) btn.setAttribute("aria-pressed", "false");
}
// A global page drawn in #main: its sections are the page's own blocks.
export function applyPageLayout(name) { applyViewLayout($("#main"), "g:" + name); }

// -- Ask Rihma: the same changes in words, previewed first ----------------------------------------------

const VERB = [[/^(hide|remove|drop)\b/, "hide"], [/^(show|unhide|bring back)\b/, "show"],
  [/^(move|put)\b.*\b(top|first|up)\b/, "top"], [/^(move|put)\b.*\b(bottom|last|down)\b/, "bottom"],
  [/^(make|set)\b.*\b(compact|smaller|small|shorter)\b/, "compact"], [/^(make|set)\b.*\b(wide|wider|bigger|full)\b/, "wide"]];
/* A layout change for the view on screen, read from the person's words, or null when the words do not ask one
   or name no section here. Home is left to the assistant's own layout proposals. */
export function viewLayoutIntent(question) {
  if (!current.root || !current.root.isConnected || (S.route && S.route.name === "home")) return null;
  const q = String(question || "").toLowerCase().trim().replace(/^(please|rihma,?|can you|could you)\s+/g, "");
  const verb = (VERB.find(([re]) => re.test(q)) || [])[1];
  if (!verb) return null;
  if (verb === "show" && /\b(all|every|everything)\b/.test(q)) return { verb: "show_all", key: null, name: "every section" };
  const all = sections(current.root);
  const said = q.replace(/\b(the|section|card|panel|to|at|of|this|view|page|top|bottom|first|last|up|down|compact|wide|wider|smaller|bigger|make|set|move|put|hide|show|remove)\b/g, " ")
    .replace(/\s+/g, " ").trim();
  if (!said) return null;
  const hit = all.find((el) => sectionLabel(el).toLowerCase().includes(said)) || all.find((el) => said.split(" ").every((w) => sectionLabel(el).toLowerCase().includes(w)));
  return hit ? { verb, key: hit.dataset.czKey, name: sectionLabel(hit) } : null;
}
export function describeIntent(it) {
  return { hide: "Hide “" + it.name + "”", show: "Show “" + it.name + "”", top: "Move “" + it.name + "” to the top",
    bottom: "Move “" + it.name + "” to the bottom", compact: "Make “" + it.name + "” compact", wide: "Make “" + it.name + "” wide",
    show_all: "Show every hidden section" }[it.verb];
}
function applyIntent(lay, it, keys) {
  if (it.verb === "hide") lay.hidden = lay.hidden.filter((x) => x !== it.key).concat([it.key]);
  if (it.verb === "show") lay.hidden = lay.hidden.filter((x) => x !== it.key);
  if (it.verb === "show_all") lay.hidden = [];
  if (it.verb === "compact" || it.verb === "wide") lay.size[it.key] = it.verb;
  if (it.verb === "top" || it.verb === "bottom") {
    const rest = keys.filter((k) => k !== it.key);
    lay.order = it.verb === "top" ? [it.key].concat(rest) : rest.concat([it.key]);
  }
}
export function previewIntent(it) {
  if (!current.key) return false;
  preview = { key: current.key, before: loadViewLayout(current.key) };
  edit((lay) => applyIntent(lay, it, sections(current.root).map((el) => el.dataset.czKey)), { only_here: true });
  return true;
}
export function keepIntent() {
  if (preview) saveViewLayout(preview.key, loadViewLayout(preview.key));   // saved on the server only now
  preview = null;
  say("Kept: this view's layout is saved for you on every computer.", "good");
}
export function undoIntent() {
  if (!preview) return;
  saveViewLayout(preview.key, preview.before, { only_here: true });   // nothing was saved: the view goes back
  preview = null;
  applyViewLayout(current.root, current.key);
}
export function previewingView() { return !!preview; }
