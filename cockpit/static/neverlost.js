/* Never lost, who acted and decision triage in the shell (FR-NVL1, docs/guides/never-lost.md).

   - "Why? Ask Rihma" on every empty state, every "not measured" value, every error box and every failed action:
     it opens Ask Rihma with the context (the view, the field, the project, the words on screen), and Rihma answers
     by rule why it is empty or failing and offers the step that fills it as a button (kernel/neverlost.py).
     Added by watching the page, so every view gets it, the ones other modules draw included.
   - Under every Ask Rihma answer: who acted (which Rihma agent and role, which harness and model, on this machine
     or hosted, and whether Gnomon's structure applied), the step that fills an empty thing, and a decision
     triage's blocking few with its proposal to confirm. */

import { S, $, $$, h, icon, button, api, enc, say, needPerson, signed, nav, plural } from "./core.js";
import { pick, datum } from "./words.js";
import { openAssistant, send, takeThere } from "./assistant.js";

const SCOPES = ["#main", "#modal", "#status", "#as-log"];
const NOT_MEASURED = /not measured/i;
const N = { seq: 0, timer: null };

function currentView() { return (S.route && (S.route.view || S.route.name)) || "home"; }
function fieldOf(el) {
  const box = el.closest(".card, .widget, section, article, .tile, li, tr");
  const head = box && box.querySelector("h2, h3, h4, .card-t, .w-title, .tile-t, th, b");
  return head && !el.contains(head) ? head.textContent.trim().slice(0, 120) : "";
}
function basisOf(el) { return el.textContent.replace(/Why\? Ask Rihma/g, "").replace(/\s+/g, " ").trim().slice(0, 380); }

/* Ask Rihma why: the drawer opens and the question goes with its context, answered by rule. */
export function askWhy(ctx) {
  const what = ctx.kind === "error" ? "Why did this fail" : ctx.kind === "not_measured" ? "Why is " + (ctx.field || "this") + " not measured"
    : "Why is " + (ctx.field || "this") + " empty";
  openAssistant();
  send(what + " here?", { why: ctx });
}

function whyButton(ctx) {
  N.seq += 1;
  return h("button", { type: "button", class: "nvl-why", "data-control": "why_ask", "data-key": "why:" + ctx.kind + ":" + N.seq,
    "aria-label": "Why? Ask Rihma" + (ctx.field ? " about " + ctx.field : ""), onclick: (e) => { e.preventDefault(); e.stopPropagation(); askWhy(ctx); } },
  icon("sparkles"), h("span", null, "Why? Ask Rihma"));
}

function context(el, kind) {
  return { view: el.getAttribute("data-empty") || currentView(), field: fieldOf(el), kind, basis: basisOf(el),
    project: (S.route && S.route.pid) || "" };
}

// An empty state: the button after it, so the explanation stays the empty state's own words.
function onEmpty(el) {
  if (el.dataset.nvl || el.closest(".nvl-why, #as-log, .as-hello")) return;
  el.dataset.nvl = "1";
  el.after(h("div", { class: "nvl-row" }, whyButton(context(el, "empty"))));
}
// A value's own label inside its tile ("Checks failing"), and its words without buttons, icons or tips.
const LABEL = ".kpi-h > span, .tile-t, .label, dt, th";
const EDGE = /^[\s:·—-]+|[\s:·—-]+$/g;
function plainText(el) {
  const c = el.cloneNode(true);
  c.querySelectorAll("button, .nvl-why, .ins-actions, .btns, svg, .tip, [aria-hidden='true']").forEach((x) => x.remove());
  const parts = [];      // each text on its own: "…run yet." and "To measure it…" never run together
  const walk = document.createTreeWalker(c, NodeFilter.SHOW_TEXT);
  while (walk.nextNode()) parts.push(walk.currentNode.nodeValue);
  return parts.join(" ").replace(/\s+/g, " ").trim();
}
/* A value said as "not measured": the field is its label (never the tile's whole text with its buttons), the basis
   the words after it (its reason and its "To measure it: ..." hint), so the answer follows the tile's own hint. */
export function unmeasuredContext(box) {
  const text = plainText(box);
  const m = text.match(NOT_MEASURED);
  const at = m ? m.index : text.length;
  const before = text.slice(0, at).replace(EDGE, "");
  const after = text.slice(at + (m ? m[0].length : 0)).replace(/^(?:[\s:·—-]|not measured)+/i, "").trim();
  const own = box.querySelector(LABEL);
  const field = (own ? plainText(own).replace(EDGE, "") : "") || before || fieldOf(box);
  return Object.assign(context(box, "not_measured"), { field: field.slice(0, 120), basis: after.slice(0, 380) });
}
// A value said as "not measured": one button for its tile, row or card.
function onUnmeasured(node) {
  const el = node.parentElement;
  if (!el || el.closest(".nvl-why, #assistant, [data-nvl-m], code, pre, option, select, button, label, .tip")) return;
  // the value's own chip, tile or cell, never the whole row or card around it
  const box = el.closest(".chip, .pill, .tile, .kpi, .stat, td, li, dd") || el;
  if (box.dataset.nvlM) return;
  box.dataset.nvlM = "1";
  const ctx = unmeasuredContext(box);
  if (box.matches(".chip, .pill")) box.after(" ", whyButton(ctx)); else box.append(" ", whyButton(ctx));
}
// An error box, a failed action's toast, an error answer: the button beside its own.
function onError(el) {
  if (el.dataset.nvl) return;
  el.dataset.nvl = "1";
  N.last = { message: basisOf(el), view: currentView(), at: Date.now() };   // for a typed "why did it fail?"
  const where = el.querySelector(".btns") || el;
  const close = el.classList.contains("toast") ? el.querySelector(".icon-btn") : null;
  const b = whyButton(Object.assign(context(el, "error"), { field: "" }));
  if (close) close.before(b); else where.append(b);
}

function sweep() {
  N.timer = null;
  SCOPES.forEach((sel) => {
    const root = $(sel);
    if (!root) return;
    $$(".empty, [data-empty]", root).forEach(onEmpty);
    $$(".heal-panel, .toast.critical, .toast.danger, .note.critical, .bub.err", root).forEach(onError);
    if (sel === "#main" || sel === "#modal") {
      const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: (t) => (NOT_MEASURED.test(t.nodeValue) ? 1 : 3) });
      const found = [];
      while (walk.nextNode()) found.push(walk.currentNode);
      found.forEach(onUnmeasured);
    }
  });
}
function later() { if (!N.timer) N.timer = setTimeout(sweep, 60); }

export function wireNeverLost() {
  const watch = new MutationObserver(later);
  ["#main", "#modal", "#status", "#assistant"].forEach((sel) => { const el = $(sel); if (el) watch.observe(el, { childList: true, subtree: true }); });
  later();
  nav.neverlost = { block: answerBlock, lastError };
}
// The last failure the page showed in the last ten minutes: a typed "why did it fail?" is answered from it.
const RECENT_MS = 10 * 60 * 1000;
export function lastError() {
  return N.last && Date.now() - N.last.at < RECENT_MS && N.last.message ? { message: N.last.message, view: N.last.view } : undefined;
}

// -- under each Ask Rihma answer ---------------------------------------------------------------------------------

function whoLine(w) {
  if (!w) return null;
  const said = pick(
    (w.how === "by rule" ? "Answered by Ask Rihma from the records, by rule: no AI model was asked."
      : "Answered by Ask Rihma with " + w.model + " through " + w.harness + ", " + w.where + ".")
      + " Rihmasto's checks: " + (w.how === "by rule" ? "nothing to enforce on an answer; any action waits for your yes." : "each proposal is checked against the Inbox rules."),
    "Who acted: " + w.agent + " (" + w.role + ") · " + w.harness + " · " + (w.model === "no model" ? w.model : "model " + w.model) + " · " + w.where + " · Gnomon: " + w.gnomon
      + " · enforcement " + w.enforcement);
  return h("p", { class: "nvl-who muted small", "data-control": "who_acted" }, icon("bot"), " ", datum(said));
}

// Across projects (FR-NVL2): the blocking ones ranked over every project, and one confirm for every project's part.
function triageAllBlock(t) {
  const rows = (t.blocking || []).slice(0, 8).map((b) => h("li", null, h("b", null, b.rank + ". "), datum(b.project_title + " "),
    h("b", null, (b.card || b.assumption) + " "), datum(b.title || ""), h("small", { class: "muted" }, " · ", datum(b.why))));
  const p = t.proposal || { count: 0, projects: [] };
  const go = p.count ? button("Assume the other " + p.count + " across " + plural(p.projects.length, "project"), { kind: "small primary", icon: "check",
    key: "triage-chat:all", "data-control": "triage_assume", onclick: (e) => confirmTriageAll(p.projects, e.currentTarget) }) : null;
  return h("div", { class: "nvl-triage" },
    rows.length ? [h("p", { class: "small" }, h("b", null, "Blocking work, most first, in every project")), h("ol", { class: "nvl-list" }, rows)] : null,
    go ? h("div", { class: "btns" }, go) : null);
}

function triageBlock(out, item) {
  if (out.triage_all) return triageAllBlock(out.triage_all);
  const t = out.triage;
  if (!t) return null;
  const pid = t.project || item.project || (S.route && S.route.pid);
  const rows = (t.blocking || []).slice(0, 8).map((b) => h("li", null, h("b", null, b.rank + ". " + (b.card || b.assumption) + " "),
    datum(b.title || ""), h("small", { class: "muted" }, " · ", datum(b.why))));
  const grew = (t.grew || []).slice(0, 5).map((g) => h("li", null, h("b", null, g.id + " "), datum(g.text || ""),
    h("small", { class: "muted" }, " · grew in importance: reconsider (", datum(g.trigger || ""), ")")));
  const p = t.proposal;
  const go = p && p.count && pid ? button("Assume the other " + p.count + " for me", { kind: "small primary", icon: "check",
    key: "triage-chat:" + pid, "data-control": "triage_assume", onclick: (e) => confirmTriage(pid, e.currentTarget) }) : null;
  return h("div", { class: "nvl-triage" },
    rows.length ? [h("p", { class: "small" }, h("b", null, "Blocking work, most first")), h("ol", { class: "nvl-list" }, rows)] : null,
    grew.length ? [h("p", { class: "small" }, h("b", null, "Grew in importance")), h("ul", { class: "nvl-list" }, grew)] : null,
    go ? h("div", { class: "btns" }, go) : null);
}

function doneWords(assumed, deferred) {
  return [assumed ? plural(assumed, "question") + " go on with the suggested answer" : "",
    deferred ? plural(deferred, "change") + " wait until they matter" : ""].filter(Boolean).join(" and ");
}
function leftWords(left) { return left.map((l) => l.card + ": " + l.why).join("; "); }
// Nothing assumed is never a success: a warning that gives each reason, with "Why? Ask Rihma" beside it.
function warnNothing(left) {
  say("Nothing was assumed" + (left.length ? ": " + leftWords(left) + "." : "."), "warning");
  const t = $("#status .toast");
  if (t) onError(t);
}
function settled(btn, done, left) {
  if (!done) { warnNothing(left); if (btn) btn.disabled = false; return; }
  if (btn) { const label = btn.querySelector(".lbl") || btn; label.textContent = "Done: recorded as your choice"; }
  if (nav.rerender && S.route && ["project", "triage_all"].includes(S.route.name)) nav.rerender();
}
function failed(btn, e) {
  if (btn) btn.disabled = false;
  if (nav.actionError) nav.actionError(e); else say(e.message, "critical");
  return null;
}

export async function confirmTriage(pid, btn, cards) {
  if (!needPerson()) return null;
  if (btn) btn.disabled = true;
  try {
    const out = await api("POST", "/api/projects/" + enc(pid) + "/triage/assume", Object.assign(signed(), cards ? { cards } : {}));
    const done = out.assumed.length + out.deferred.length;
    if (done) {
      say(doneWords(out.assumed.length, out.deferred.length) + ", each recorded as your delegated choice."
        + (out.left.length ? " " + out.left.length + " stay with you: " + leftWords(out.left) + "." : ""), "good");
    }
    settled(btn, done, out.left);
    return out;
  } catch (e) { return failed(btn, e); }
}

/* One proposal across projects (FR-NVL2): each project's part confirmed through that project's own route, signed
   and recorded there; what one project refuses is said with its reason and the rest still goes on. */
export async function confirmTriageAll(parts, btn) {
  if (!needPerson()) return null;
  if (btn) btn.disabled = true;
  const sum = { assumed: 0, deferred: 0, left: [], projects: 0 };
  for (const part of parts) {
    try {
      const out = await api("POST", "/api/projects/" + enc(part.project) + "/triage/assume", Object.assign(signed(), { cards: part.cards }));
      sum.assumed += out.assumed.length; sum.deferred += out.deferred.length;
      sum.left.push(...out.left.map((l) => Object.assign({}, l, { card: part.title + " " + l.card })));
      if (out.assumed.length + out.deferred.length) sum.projects += 1;
    } catch (e) { sum.left.push({ card: part.title, why: e.message }); }
  }
  const done = sum.assumed + sum.deferred;
  if (done) {
    say(doneWords(sum.assumed, sum.deferred) + " in " + plural(sum.projects, "project") + ", each recorded as your delegated choice there."
      + (sum.left.length ? " Not assumed: " + leftWords(sum.left) + "." : ""), "good");
  }
  settled(btn, done, sum.left);
  return sum;
}

function answerBlock(out, item, idx) {
  if (!out) return null;
  const fillStep = out.fill && out.fill.route ? button(out.fill.label, { kind: "small primary", icon: "arrow-right", key: "fill:" + idx,
    "data-control": "why_ask", onclick: () => takeThere({ route: out.fill.route, control: out.fill.control }) }) : null;
  return h("div", { class: "nvl-block" }, fillStep ? h("div", { class: "btns" }, fillStep) : null, triageBlock(out, item), whoLine(out.who));
}
