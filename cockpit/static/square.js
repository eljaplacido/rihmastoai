/* The Delivery square made understandable (FR-UXO1). The owner: "Delivery Square view is unclear: how are you
   even supposed to view it? By project? On the whole platform level?"

   The square says in one line what it is ("How needs move from arriving to production"), switches between all
   projects and one project, and opens with its five lanes in order: needs arrive, concepts to validate, being
   built, end users test, in production. Each lane's count is a link to its items below, and an empty lane says
   what would appear there and how it gets there. */

import { S, h, icon, store, enc, plural } from "./core.js";
import { technical } from "./words.js";

const KEY = "gf.square.scope";
export function squarePid() { return store.get(KEY) || ""; }
export function setSquarePid(pid) { if (pid) store.set(KEY, pid); else store.del(KEY); }

// The square seen for one project (or all): the signals routed to it, its place in the pipeline, its feedback
// and production. Concepts are not a project yet, so a project's square has none.
export function squareScope(sq, pid) {
  if (!pid) return { sq, pid: "" };
  const bands = ((sq.pipeline || {}).bands || []).map((b) => Object.assign({}, b, {
    stages: b.stages.map((s) => Object.assign({}, s, { projects: s.projects.filter((p) => p.id === pid) })) }));
  const total = bands.reduce((n, b) => n + b.stages.reduce((m, s) => m + s.projects.length, 0), 0);
  const signals = (sq.signals_list || []).filter((s) => (s.routed_to || {}).project === pid);
  const feedback = (sq.feedback || []).filter((f) => f.project === pid);
  return { pid, sq: Object.assign({}, sq, {
    signals_list: signals, signals: { new: signals.filter((s) => s.state === "new").length, total: signals.length }, signals_all: true,
    concepts: [], pipeline: Object.assign({}, sq.pipeline, { bands, total }), feedback,
    production: (sq.production || []).filter((p) => p.project === pid),
    end_user_feedback_open: feedback.filter((f) => f.state === "open").length, end_user_feedback_untriaged: null }) };
}

export function scopeSwitch(pid, onChange) {
  const products = (S.projects || []).filter((p) => !p.factory);
  const sel = h("select", { id: "sq-scope", "data-control": "square_scope", "data-key": "sq:scope", "aria-label": "Show the square for" },
    h("option", { value: "", selected: !pid }, "All projects"),
    products.map((p) => h("option", { value: p.id, selected: p.id === pid }, p.title)));
  sel.addEventListener("change", () => onChange(sel.value));
  return h("label", { class: "sq-scope" }, h("span", null, "Show"), sel);
}

function inBuild(sq) {
  return ((sq.pipeline || {}).bands || []).reduce((n, b) => n + b.stages.filter((s) => s.stage < 7)
    .reduce((m, s) => m + s.projects.length, 0), 0);
}
/* The five lanes, in the order a need moves. A count is a link to the lane's items; an empty lane says what
   would appear there. */
export function squareLanes(sc) {
  const sq = sc.sq;
  const one = !!sc.pid;
  const tech = technical();
  const lanes = [
    ["needs", "signal", "Needs arrive", (sq.signals_list || []).length,
      one ? "A need about this project that someone logs here is routed to it as a change." : "A need someone logs here, or one a feed or the website chat sends."],
    ["concepts", "lightbulb", "Concepts to validate", (sq.concepts || []).length,
      one ? "Concepts are not a project yet: switch to All projects to see them." : "A new need that fits no project becomes a concept for a business or product owner."],
    ["factory", "factory", tech ? "In the pipeline" : "Being built", inBuild(sq),
      one ? "This project is in production, or not started." : "A validated concept or a new project, at its stage."],
    ["testing", "users", "End users test", (sq.feedback || []).filter((f) => f.state === "open").length,
      "What testers report on a release they try (the Try it checklist or a feedback embed)."],
    ["production", "server", "In production", (sq.production || []).length, "A release that reached stage 7 runs here."],
  ];
  return h("ol", { class: "sq-lanes", "aria-label": "The square's lanes, from a need to production" }, lanes.map(([id, ic, label, n, none]) =>
    h("li", { class: "sq-lane" + (n ? "" : " zero") },
      h("a", { href: "#/square", "data-lane": id, "data-key": "lane:" + id, "aria-describedby": n ? null : "lane-" + id + "-none",
        onclick: (e) => { e.preventDefault(); goLane(id); } },
      h("span", { class: "sq-lane-n" }, String(n)), h("span", { class: "sq-lane-l" }, icon(ic), label)),
      n ? null : h("p", { class: "sq-lane-none muted small", id: "lane-" + id + "-none" }, none))));
}
function goLane(id) {
  const target = document.getElementById(id + "-h") || document.querySelector('[data-lane-card="' + id + '"]');
  if (!target) return;
  const box = target.closest(".card") || target;
  box.scrollIntoView({ block: "start" });
  if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
  target.focus({ preventScroll: true });
}

export function scopeLine(sc) {
  if (!sc.pid) return null;
  const p = (S.projects || []).find((x) => x.id === sc.pid);
  return h("p", { class: "callout sq-one" }, icon("folder"), h("span", null, "Showing one project: ", h("b", null, p ? p.title : sc.pid),
    ". " + plural((sc.sq.signals_list || []).length, "signal") + " routed to it."),
  h("a", { class: "callout-go", href: "#/p/" + enc(sc.pid) }, "Open the project"));
}
