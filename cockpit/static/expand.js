/* Compact boxes open for review (FR-CMP1). The owner (2026-11-26): "When I change size of something to compact I
   guess I should be able to roll those compacted boxes for review?"

   Wherever a box can be made compact, it carries Expand (and a click on its head does the same; Enter or Space on
   Expand, as on any button), which shows its whole content, and Collapse, which folds it back. The size the person
   chose is never changed: Expand only shows, for now, what the compact size leaves out.

     inPlace(box, o)      the box grows in place: a view's compact section, the agent channel beside the view, the
                          last-action box of the live view, the Agents strip's list
     sheetButton(o)       a side panel where growing in place would break the grid (Home's small and medium
                          widgets); at phone width always a sheet from the bottom
     expandIntent(q)      Ask Rihma, map or chat: "expand the decisions" opens the compact box on screen by its name
     expandBlock(x)       that answer's button in the conversation

   Every Expand is a real button with aria-expanded and aria-controls; the focus stays on it in place, and goes back
   to it when the side panel closes. The words are words.js's ("expand.*").

   FR-CMP2 (an independent check of FR-CMP1): a box keeps one state, kept by the box itself, not by its button. A box
   whose content arrives after it is drawn (Set up this project) gets its Expand back and its name from its new head;
   applying the layout again keeps the same Expand; a head click always toggles the Expand that is there, and does
   nothing once the box is no longer compact; one box made compact twice over (the Agents strip) has one Expand; a
   compact section's Expand comes first in the tab order and is the cut line, over none of its controls, and a
   control the cut hides opens the section when it takes the focus. The side panel follows a redraw of its widget:
   what was decided in it is gone, the new Expand says it is open, and the focus comes back to it. */

import { $, $$, h, icon, fill, fmtAt } from "./core.js";
import { word } from "./words.js";
import { liftToasts, dropToasts } from "./expandkeep.js";

const OPEN = new Set();   // boxes opened in place, by key: a redraw of the same box keeps it open
const STATE = new WeakMap();   // box -> its one Expand state (FR-CMP2)
const WIRED = new WeakSet();   // boxes whose head click and focus are listened to
const HANDLED = new WeakSet(); // a click toggles one box only
// what a click on a box's head leaves alone: its own controls
const OWN_CONTROL = "a, button, input, select, textarea, summary, label, [role=button], [role=menu], [role=menuitem], [tabindex]:not([tabindex='-1'])";
const HEADS = "h2, h3, .card-head, .label-h";   // a compact section's head: the first of these, found when clicked
let seq = 0;

function slug(s) { return String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48); }
function said(open) { return word(open ? "expand.close" : "expand.open"); }

function control(o, onclick) {
  const b = h("button", { type: "button", class: "btn tiny quiet xp-btn", "data-control": "expand_box", "data-key": "xp:" + o.key,
    "data-xp-name": o.name, "aria-expanded": "false" }, icon("expand"), h("span", { class: "lbl" }, said(false)));
  b.addEventListener("click", onclick);
  return b;
}
function mark(b, open, name) {
  b.setAttribute("aria-expanded", String(open));
  b.setAttribute("aria-label", said(open) + " " + name);
  b.setAttribute("tip", open ? word("expand.close_tip") : word("expand.open_tip"));
  const lbl = b.querySelector(".lbl");
  if (lbl.textContent !== said(open)) lbl.textContent = said(open);
  const use = b.querySelector("use");
  if (use.getAttribute("href") !== "#i-" + (open ? "rows-compact" : "expand")) use.setAttribute("href", "#i-" + (open ? "rows-compact" : "expand"));
}
// A click on the head (its title, its empty space) does what Expand does; the head's own links and buttons keep theirs.
// For the side panel's widgets, drawn anew with their Expand each time.
export function headToggles(head, b) { wireHead(head, () => b.click()); }
function wireHead(head, go) {
  if (!head || head.dataset.xpHead) return;
  head.dataset.xpHead = "1";
  head.classList.add("xp-head");
  head.addEventListener("click", (e) => {
    if (e.target.closest(OWN_CONTROL) && e.target.closest(OWN_CONTROL) !== head) return;
    go();
  });
}

// -- in place: one state per box ----------------------------------------------------------------------------

function headOf(s) {
  if (s.head) return s.head.isConnected || !s.box.isConnected ? s.head : null;
  return s.headSel ? s.box.querySelector(s.headSel) : null;
}
function apply(s, open) {
  const box = s.box;
  box.classList.toggle("xp-open", open);
  mark(s.b, open, s.name);
  if (open) OPEN.add(s.key); else OPEN.delete(s.key);
  // folded back, a box that clips shows its top again (the focused Collapse had scrolled it)
  if (!open) requestAnimationFrame(() => { box.scrollTop = 0; });
  if (s.onToggle) s.onToggle(open);
  if (s.cut) s.cut();
}
/* The box's Expand is where it belongs, its head shows the hand, and its name follows the head: a box filled after it
   was drawn (its content replaced, the button with it) gets them back. */
function keep(s) {
  if (!s.owners.size) return;
  const at = s.place || s.box;
  if (s.b.parentNode !== at) { if (s.first) at.prepend(s.b); else at.append(s.b); }
  const head = headOf(s);
  if (head !== s.lastHead) {
    if (s.lastHead) s.lastHead.classList.remove("xp-head");
    if (head) head.classList.add("xp-head");
    s.lastHead = head;
  }
  const name = (s.nameOf && s.nameOf()) || s.name;
  if (name && name !== s.b.dataset.xpName) {
    s.name = name;
    s.b.dataset.xpName = name;
    mark(s.b, s.box.classList.contains("xp-open"), name);
  }
  if (s.cut) s.cut();
}
function wireBox(box) {
  if (WIRED.has(box)) return;
  WIRED.add(box);
  box.addEventListener("click", (e) => {
    const s = STATE.get(box);
    if (!s || !s.owners.size || HANDLED.has(e)) return;
    const head = headOf(s);
    if (!head || !head.contains(e.target) || s.b.contains(e.target)) return;
    const own = e.target.closest(OWN_CONTROL);
    if (own && own !== head && head.contains(own)) return;
    HANDLED.add(e);
    apply(s, !box.classList.contains("xp-open"));
  });
  // a control the cut hides, reached by the keyboard: the section opens so the focused control is seen
  box.addEventListener("focusin", (e) => {
    const s = STATE.get(box);
    if (!s || !s.owners.has("section") || box.classList.contains("xp-open") || s.b.hidden || s.b.contains(e.target)) return;
    if (e.target.getBoundingClientRect().bottom > s.b.getBoundingClientRect().top + 1) apply(s, true);
  });
}

/* In place: the box gets .xp-box, and .xp-open while it is expanded (its CSS shows what compact cut). o: key (what
   keeps it open across a redraw), name (said on the button and matched by Ask Rihma), nameOf() (the name again once
   the box is filled), head (a click on it toggles) or headSel (the head found in the box when clicked), place (where
   the button goes, the box by default), first (the button first in the box), owner (who made it compact: one Expand
   per box however many ask), onToggle(open). Called again on the same box, it keeps the same Expand. */
export function inPlace(box, o) {
  const owner = o.owner || "own";
  const was = document.activeElement;
  const opts = { name: o.name, nameOf: o.nameOf || null, head: o.head || null, headSel: o.headSel || null, place: o.place || null,
    first: !!o.first, onToggle: o.onToggle || null };
  let s = STATE.get(box);
  if (s && s.owners.size) {
    s.owners.add(owner);
    s.by.set(owner, opts);
    if (s.owner === owner) Object.assign(s, opts);
    keep(s);
    apply(s, OPEN.has(s.key));
    return s.b;
  }
  const hadFocus = !!(was && was.dataset && was.dataset.key === "xp:" + o.key);
  [box, o.place].forEach((at) => { if (at) $$(":scope > .xp-btn", at).forEach((x) => x.remove()); });
  if (!box.id) box.id = "xp-" + slug(o.key) + "-" + (++seq);
  box.classList.add("xp-box");
  s = Object.assign({ box, owner, owners: new Set([owner]), by: new Map([[owner, opts]]), key: o.key, lastHead: null }, opts);
  s.b = control(o, () => apply(s, !box.classList.contains("xp-open")));
  s.b.setAttribute("aria-controls", box.id);
  STATE.set(box, s);
  wireBox(box);
  if (typeof MutationObserver === "function") {
    s.mo = new MutationObserver(() => keep(s));
    s.mo.observe(box, { childList: true, subtree: true });
  }
  keep(s);
  apply(s, OPEN.has(o.key));
  if (hadFocus) queueMicrotask(() => { if (s.b.isConnected) s.b.focus(); });   // a redraw keeps the focus on Expand
  return s.b;
}
/* A box no longer compact (for ``owner``, a view's section by default): once nobody keeps it compact its Expand goes,
   its head is plain again, and it shows as it is. */
export function dropInPlace(box, owner = "section") {
  const s = STATE.get(box);
  if (!s) return;
  s.owners.delete(owner);
  s.by.delete(owner);
  if (owner === "section" && s.ro) { s.ro.disconnect(); s.ro = null; s.cut = null; s.b.hidden = false; box.classList.remove("xp-cut"); }
  if (s.owners.size) {
    if (s.owner === owner) { s.owner = [...s.owners][0]; Object.assign(s, s.by.get(s.owner)); }   // the other's place and head
    keep(s);
    return;
  }
  if (s.mo) s.mo.disconnect();
  if (s.lastHead) s.lastHead.classList.remove("xp-head");
  s.b.remove();
  box.classList.remove("xp-box", "xp-open", "xp-cut");
  OPEN.delete(s.key);
  STATE.delete(box);
}

// -- a view's compact section (viewcustom.js): Expand first, the cut line, shown only when compact cuts something ---

export function compactSection(el, key, name, nameOf) {
  const b = inPlace(el, { key, name, nameOf, headSel: HEADS, first: true, owner: "section" });
  const s = STATE.get(el);
  if (s && !s.ro && typeof ResizeObserver === "function") {
    s.cut = () => {
      if (!s.owners.has("section")) return;
      const filled = [...el.childNodes].some((n) => n !== s.b && String(n.textContent || "").trim());
      const open = el.classList.contains("xp-open");
      const cut = el.scrollHeight > el.clientHeight + 2;
      // nothing cut (or nothing in it): no Expand, unless another owner keeps it (the Agents strip's own)
      s.b.hidden = s.owners.size === 1 && (!filled || (!cut && !open));
      el.classList.toggle("xp-cut", !s.b.hidden);
    };
    s.ro = new ResizeObserver(() => { if (!s.b.isConnected && !el.isConnected) { s.ro.disconnect(); return; } s.cut(); });
    s.ro.observe(el);
  }
  return b;
}

// -- the live view's last-action box: Expand shows the steps before it, newest first --------------------------------

export function lastActionBox(lastEl, recent, key) {
  const rows = (recent || []).slice(1);   // the first is the last action itself
  if (!rows.length) return lastEl;
  const box = h("div", { class: "live-lastbox" }, lastEl,
    h("p", { class: "muted small xp-more" }, word("expand.recent")),
    h("ol", { class: "live-recent xp-more" }, rows.map((s) => h("li", null, h("span", { class: "mono" }, s.tool || "?"),
      s.target ? h("code", null, s.target) : null, s.at ? h("span", { class: "muted small" }, fmtAt(s.at)) : null))));
  inPlace(box, { key, name: word("expand.last_action"), head: lastEl.querySelector(".label") });
  return box;
}

// -- the side panel (a sheet at phone width) ----------------------------------------------------------------

let sheet = null;
let opener = null;
let shown = null;   // the o of the box the panel shows: its key, name, render()
function sheetEl() {
  if (sheet && sheet.isConnected) return sheet;
  sheet = h("dialog", { id: "xp-sheet", class: "xp-sheet", "aria-labelledby": "xp-h" });
  sheet.addEventListener("close", () => {
    if (sheet.open) return;   // reopened for another box before this event came: that box's content stays
    const was = shown;
    let b = opener;
    opener = null;
    shown = null;
    dropToasts();
    fill(sheet);
    // the grid drew the box again while it was open: the focus goes back to its Expand as it is now
    if ((!b || !b.isConnected) && was) b = $$("[data-control=\"expand_box\"]").find((x) => x.dataset.key === "xp:" + was.key) || null;
    if (b && b.isConnected) { mark(b, false, b.dataset.xpName); b.focus(); }
  });
  sheet.addEventListener("click", (e) => { if (e.target === sheet) sheet.close(); });
  document.body.append(sheet);
  return sheet;
}
/* Expand for a box that opens in the side panel. o: key, name, icon, render() (the whole content, drawn when it
   opens, and again when the box is drawn again while it is open), head (a click on it opens). */
export function sheetButton(o) {
  const b = control(o, () => (opener === b && sheet && sheet.open ? sheet.close() : openSheet(b, o)));
  b.setAttribute("aria-controls", "xp-sheet");
  mark(b, false, o.name);
  wireHead(o.head, () => b.click());
  if (sheet && sheet.open && shown && shown.key === o.key && opener !== b) follow(b, o);
  return b;
}
function body(o) {
  try { return o.render(); } catch (e) { return h("p", { class: "muted" }, word("expand.failed") + " " + e.message); }
}
/* The box was drawn again while its panel is open (an action taken in the panel redrew the grid): the panel shows it
   as it is now, the new Expand says it is open, and the focus stays in the panel. */
function follow(b, o) {
  opener = b;
  shown = o;
  mark(b, true, o.name);
  queueMicrotask(() => {
    if (!sheet || !sheet.open || shown !== o) return;
    const at = $(".xp-sheet-body", sheet);
    if (!at) return;
    const was = document.activeElement;
    const key = was && at.contains(was) && was.dataset ? was.dataset.key : null;
    const lost = !was || was === document.body || !sheet.contains(was) || at.contains(was);
    fill(at, body(o));
    if (!lost) return;
    const again = key ? $$("[data-key]", at).find((x) => x.dataset.key === key && !x.disabled) : null;
    (again || $(".xp-close", sheet)).focus();
  });
}
function openSheet(b, o) {
  const dlg = sheetEl();
  if (dlg.open) {
    const before = opener;
    opener = null;
    shown = null;
    dlg.close();
    if (before && before.isConnected) mark(before, false, before.dataset.xpName);
  }
  dropToasts();   // before the panel is emptied: the toasts belong to the page
  const close = h("button", { type: "button", class: "btn small xp-close", "data-key": "xp-close", "data-control": "expand_box",
    "aria-label": word("expand.close") + " " + o.name, "aria-controls": "xp-sheet", "aria-expanded": "true" },
  icon("rows-compact"), h("span", { class: "lbl" }, word("expand.close")));
  close.addEventListener("click", () => dlg.close());
  fill(dlg, h("div", { class: "xp-sheet-in" },
    h("div", { class: "xp-sheet-head" }, o.icon ? h("span", { class: "card-ic" }, icon(o.icon)) : null,
      h("h2", { id: "xp-h" }, o.name), close),
    h("p", { class: "xp-sheet-note muted small" }, word("expand.kept")),
    h("div", { class: "xp-sheet-body" }, body(o))));
  opener = b;
  shown = o;
  mark(b, true, o.name);
  dlg.showModal();
  liftToasts(dlg);   // what the person does in the panel says so above its backdrop
  close.focus();
}

// -- Ask Rihma: open a compact box on screen by its name ----------------------------------------------------

const OPENS = /^(expand|unfold|unroll|roll open|roll out|open up|open in full|show in full|show all of|show the whole|show the full|show everything in|open the compact(?:ed)?|open compact(?:ed)?)\b/;
const CLOSES = /^(collapse|fold|roll up|fold up|fold back|close the expanded)\b/;
const FILLER = /\b(the|a|my|this|that|box|boxes|card|widget|section|panel|compact|compacted|small|medium|for review|in full|fully|full|whole|all of|again|please|up|back|open|expanded)\b/g;

function boxes() {
  return $$("[data-xp-name]").filter((b) => b.getClientRects().length || b.closest(".xp-box"));
}
function find(name) {
  const said = String(name || "").toLowerCase();
  const all = boxes();
  const label = (b) => String(b.dataset.xpName || "").toLowerCase();
  return all.find((b) => label(b) === said) || all.find((b) => label(b).includes(said))
    || all.find((b) => said.split(" ").every((w) => label(b).includes(w)));
}
/* A request to expand (or collapse) a compact box on screen, read from the words, or null when the words do not ask
   it or name no compact box here. */
export function expandIntent(question) {
  const q = String(question || "").toLowerCase().trim().replace(/[?.!]+$/, "").replace(/^(please|rihma,?|can you|could you)\s+/g, "");
  const verb = OPENS.test(q) ? "open" : CLOSES.test(q) ? "close" : null;
  if (!verb) return null;
  const rest = q.replace(verb === "open" ? OPENS : CLOSES, " ").replace(FILLER, " ").replace(/\s+/g, " ").trim();
  if (!rest) return null;
  const b = find(rest);
  return b ? { verb, name: b.dataset.xpName, key: b.dataset.key } : null;
}
/* Carries the request out: the box opens (or folds back) and comes into view. True when it was there to do. */
export function applyExpand(it) {
  const b = $$("[data-xp-name]").find((x) => x.dataset.key === it.key) || find(it.name);
  if (!b) return false;
  const open = b.getAttribute("aria-expanded") === "true";
  if ((it.verb === "open") !== open) b.click();
  const box = b.closest(".xp-box");
  if (box && it.verb === "open") box.scrollIntoView({ block: "nearest" });
  return true;
}
export function expandAnswer(it) {
  return (it.verb === "open" ? word("expand.chat_open") : word("expand.chat_close")).replace("{name}", it.name);
}
export function expandBlock(it, idx) {
  const again = h("button", { type: "button", class: "btn small", "data-key": "xp-chat:" + idx, "data-control": "expand_box" },
    icon(it.verb === "open" ? "expand" : "rows-compact"), h("span", { class: "lbl" }, (it.verb === "open" ? said(false) : said(true)) + " “" + it.name + "”"));
  again.addEventListener("click", () => {
    const b = $$("[data-xp-name]").find((x) => x.dataset.key === it.key);
    const shut = $("#as-close");
    // on a phone the drawer covers a box that opens in place: it steps aside first
    if (shut && b && b.closest(".xp-box") && window.matchMedia("(max-width: 760px)").matches) shut.click();
    applyExpand(it);
  });
  return h("div", { class: "btns" }, again);
}
