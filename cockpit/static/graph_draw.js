/* The Knowledge graph drawn by hand in SVG (FR-GRV1), no library. Layered by kind, left to right along the trace:
   what was asked, the requirements, their criteria, the tasks and tests, then the runs and releases. Within a
   column, nodes are ordered to keep links short (barycentre sweeps); a crowded column wraps into more columns.

   The method (the dataviz skill): colour carries a node's family only, from the first three categorical slots,
   which pass the validator for every pair in both modes; its kind is carried by its shape (circle, square,
   diamond) and its text label, so identity is never colour alone. Every mark has a 2px surface ring. Issues wear
   the reserved status colours as a ring, and say so in words in the details, the tooltip and the table. Links are
   thin and recessive; a model's proposal is dashed. Pan by dragging, zoom with the buttons or Ctrl and the wheel,
   and move between nodes with the arrow keys (one tab stop: the current node). Nothing animates. */

import { h, svg, icon, attachTip } from "./core.js";
import { tipBox } from "./charts.js";

const COLUMN = { request: 0, question: 0, assumption: 0, signal: 0, observation: 0, requirement: 1, card: 1, comment: 1,
  criterion: 2, decision: 2, person: 2, task: 3, test: 3, holdout_ref: 3, round: 4, release: 4, pack: 5, model: 5, revision: 5 };
const KIND_RANK = ["request", "question", "assumption", "signal", "observation", "requirement", "card", "comment", "criterion",
  "decision", "person", "task", "test", "holdout_ref", "round", "release", "pack", "model", "revision"];
const COLW = 230;
const ROWH = 32;
const WRAP = 36;            // nodes per column before it wraps
const SHAPE = { asked: "circle", decided: "square", built: "diamond" };
let uid = 0;

export const shapeOf = (family) => SHAPE[family] || "circle";
export function severity(n) {
  return n.issues && n.issues.length ? (n.issues.some((i) => ["overturned", "refuted_basis", "broken_link", "ambiguous"].includes(i)) ? "critical" : "warning") : null;
}

// Columns of node ids, left to right, each ordered to keep links short.
export function layout(nodes, edges, colw) {
  const cw = colw || COLW;
  const byCol = new Map();
  nodes.forEach((n) => {
    const c = COLUMN[n.kind] === undefined ? 6 : COLUMN[n.kind];
    if (!byCol.has(c)) byCol.set(c, []);
    byCol.get(c).push(n);
  });
  const rank = (n) => (KIND_RANK.indexOf(n.kind) + 1 || 99);
  let cols = [...byCol.keys()].sort((a, b) => a - b).map((c) => byCol.get(c).sort((a, b) => rank(a) - rank(b) || a.id.localeCompare(b.id)));
  const near = new Map(nodes.map((n) => [n.id, []]));
  edges.forEach((e) => { if (near.has(e.from) && near.has(e.to)) { near.get(e.from).push(e.to); near.get(e.to).push(e.from); } });
  const place = new Map();
  const index = () => cols.forEach((col, ci) => col.forEach((n, i) => place.set(n.id, { ci, t: col.length > 1 ? i / (col.length - 1) : 0.5 })));
  index();
  for (let sweep = 0; sweep < 4; sweep++) {
    const order = sweep % 2 ? cols.map((_, i) => cols.length - 1 - i) : cols.map((_, i) => i);
    order.forEach((ci) => {
      const bary = (n) => {
        const others = near.get(n.id).map((id) => place.get(id)).filter((p) => p && p.ci !== ci);
        return others.length ? others.reduce((a, p) => a + p.t, 0) / others.length : place.get(n.id).t;
      };
      const scored = cols[ci].map((n) => [bary(n), rank(n), n]);
      cols[ci] = scored.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2].id.localeCompare(b[2].id)).map((x) => x[2]);
      index();
    });
  }
  cols = cols.flatMap((col) => {                       // a crowded column wraps
    const parts = [];
    for (let i = 0; i < col.length; i += WRAP) parts.push(col.slice(i, i + WRAP));
    return parts;
  });
  const tallest = Math.max(1, ...cols.map((c) => c.length));
  const pos = new Map();
  cols.forEach((col, ci) => {
    const top = ((tallest - col.length) * ROWH) / 2;
    col.forEach((n, i) => pos.set(n.id, { x: 40 + ci * cw, y: 30 + top + i * ROWH, ci, i, w: 0 }));
  });
  return { pos, cols, width: 40 + cols.length * cw, height: 60 + tallest * ROWH };
}

function mark(family) {
  const s = shapeOf(family);
  if (s === "square") return svg("rect", { class: "gv-mark", x: -8, y: -8, width: 16, height: 16, rx: 3 });
  if (s === "diamond") return svg("polygon", { class: "gv-mark", points: "0,-10 10,0 0,10 -10,0" });
  return svg("circle", { class: "gv-mark", r: 9 });
}

// A link leaves its node after the node's label and arrives at the node's mark, so no line crosses a label.
function edgePath(a, b) {
  if (a.ci === b.ci) {
    const bend = Math.min(90, 30 + Math.abs(a.y - b.y) / 4);
    return "M" + (a.x - 10) + " " + a.y + " C" + (a.x - bend) + " " + a.y + " " + (b.x - bend) + " " + b.y + " " + (b.x - 12) + " " + b.y;
  }
  const fwd = a.x < b.x;
  const x1 = fwd ? a.x + 18 + a.w : a.x - 11;
  const x2 = fwd ? b.x - 13 : b.x + 20 + b.w;
  const mid = (x1 + x2) / 2;
  return "M" + x1 + " " + a.y + " C" + mid + " " + a.y + " " + mid + " " + b.y + " " + x2 + " " + b.y;
}

function clip(text, n) { const s = String(text || ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
// A node's label: across projects it names its project too.
const labelOf = (n, scoped) => (scoped ? clip(n.short, 16) + " · " + clip(n.project, 14) : clip(n.short, 26));

/* The drawing. model: the read model; o: {kindLabel(id), onSelect(id), selected}. Returns {el, select, fit}. */
export function drawGraph(model, o) {
  const id = "gv" + (++uid);
  const nodes = model.nodes || [];
  const edges = model.edges || [];
  const scoped = model.scope === "factory";
  const L = layout(nodes, edges, scoped ? 270 : COLW);
  nodes.forEach((n) => { L.pos.get(n.id).w = labelOf(n, scoped).length * 6.6; });
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const vp = svg("g", { class: "gv-vp" });
  const root = svg("svg", { class: "gv-svg", role: "group", "aria-roledescription": "graph", id,
    "aria-label": "Knowledge graph: " + nodes.length + " nodes and " + edges.length + " links. Arrow keys move between nodes, Enter shows a node's details, plus and minus zoom." },
  svg("defs", null, svg("marker", { id: id + "-arrow", viewBox: "0 0 8 8", refX: 7, refY: 4, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" },
    svg("path", { class: "gv-arrow", d: "M0 0 L8 4 L0 8 z" }))), vp);
  const edgeEls = edges.map((e) => {
    const a = L.pos.get(e.from); const b = L.pos.get(e.to);
    const p = svg("path", { class: "gv-e" + (e.proposed ? " proposed" : "") + (e.ended ? " ended" : ""), d: edgePath(a, b),
      "marker-end": "url(#" + id + "-arrow)", "data-from": e.from, "data-to": e.to });
    return p;
  });
  const nodeEls = new Map();
  nodes.forEach((n) => {
    const p = L.pos.get(n.id);
    const sev = severity(n);
    const words = [n.short, o.kindLabel(n.kind), n.state || "", sev ? (sev === "critical" ? "contradiction" : "needs a look") + ": " + n.issues.join(", ") : ""].filter(Boolean).join(", ");
    const g = svg("g", { class: "gv-n fam-" + n.family + (sev ? " iss-" + sev : ""), transform: "translate(" + p.x + " " + p.y + ")",
      role: "button", tabindex: "-1", "aria-label": words, "data-id": n.id, "data-kind": n.kind },
    sev ? svg("circle", { class: "gv-ring " + sev, r: 14 }) : null, svg("circle", { class: "gv-hit", r: 15 }), mark(n.family),
    svg("text", { class: "gv-t", x: 15, y: 4 }, labelOf(n, scoped)));
    attachTip(g, () => tipBox(n.short, [{ value: o.kindLabel(n.kind), label: n.state || "" }].concat(sev ? [{ icon: "alert", value: sev === "critical" ? "Contradiction" : "Needs a look", label: n.issues.join(", ") }] : []), clip(n.label, 140)));
    g.addEventListener("click", () => select(n.id, true));
    nodeEls.set(n.id, g);
  });
  vp.append(svg("g", { class: "gv-edges" }, edgeEls), svg("g", { class: "gv-nodes" }, [...nodeEls.values()]));

  // -- pan and zoom: a transform attribute, never an inline style -----------------------------------
  const view = { k: 1, x: 0, y: 0 };
  const apply = () => vp.setAttribute("transform", "translate(" + view.x + " " + view.y + ") scale(" + view.k + ")");
  const size = () => { const r = root.getBoundingClientRect(); return { w: r.width || 800, h: r.height || 520 }; };
  function zoom(f, cx, cy) {
    const s = size();
    const px = cx === undefined ? s.w / 2 : cx; const py = cy === undefined ? s.h / 2 : cy;
    const k = Math.max(0.15, Math.min(3, view.k * f));
    view.x = px - (px - view.x) * (k / view.k); view.y = py - (py - view.y) * (k / view.k); view.k = k;
    apply();
  }
  function fit() {
    const s = size();
    // readable first: never below 0.85 (a larger graph pans from its top left), never above 1.2
    const k = Math.max(0.85, Math.min(1.2, (s.w - 40) / L.width, (s.h - 20) / L.height));
    view.k = k;
    view.x = L.width * k < s.w ? (s.w - L.width * k) / 2 : 0;
    view.y = L.height * k < s.h ? (s.h - L.height * k) / 2 : 0;
    apply();
  }
  function reveal(nid) {
    const p = L.pos.get(nid); const s = size();
    const sx = view.x + p.x * view.k; const sy = view.y + p.y * view.k;
    if (sx < 30 || sx > s.w - 160 || sy < 20 || sy > s.h - 20) { view.x = s.w / 2 - p.x * view.k; view.y = s.h / 2 - p.y * view.k; apply(); }
  }
  let drag = null;
  root.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".gv-n")) return;
    drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
    root.setPointerCapture(e.pointerId);
    root.classList.add("dragging");
  });
  root.addEventListener("pointermove", (e) => { if (drag) { view.x = drag.vx + e.clientX - drag.x; view.y = drag.vy + e.clientY - drag.y; apply(); } });
  const stop = () => { drag = null; root.classList.remove("dragging"); };
  root.addEventListener("pointerup", stop);
  root.addEventListener("pointercancel", stop);
  root.addEventListener("wheel", (e) => {
    if (!e.ctrlKey && !e.metaKey) return;            // a plain wheel scrolls the page; Ctrl and the wheel (or a pinch) zooms
    e.preventDefault();
    const r = root.getBoundingClientRect();
    zoom(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });

  // -- selection, the neighbourhood and the keyboard ------------------------------------------------
  let current = null;
  function select(nid, tell) {
    current = byId.has(nid) ? nid : null;
    const near = new Set(current ? [current] : []);
    edgeEls.forEach((p, i) => {
      const e = edges[i]; const on = current && (e.from === current || e.to === current);
      p.classList.toggle("on", !!on);
      if (on) { near.add(e.from); near.add(e.to); }
    });
    root.classList.toggle("has-sel", !!current);
    nodeEls.forEach((g, k) => {
      g.classList.toggle("on", k === current); g.classList.toggle("near", near.has(k) && k !== current);
      g.setAttribute("tabindex", k === (current || (nodes[0] || {}).id) ? "0" : "-1");
      g.setAttribute("aria-pressed", String(k === current));
    });
    if (current) { reveal(current); if (tell) nodeEls.get(current).focus({ preventScroll: true }); }
    if (tell && o.onSelect) o.onSelect(current);
  }
  function step(nid, key) {
    const p = L.pos.get(nid); const col = L.cols[p.ci];
    if (key === "ArrowUp" || key === "ArrowDown") return (col[p.i + (key === "ArrowUp" ? -1 : 1)] || {}).id;
    if (key === "Home" || key === "End") return (key === "Home" ? col[0] : col[col.length - 1]).id;
    const next = L.cols[p.ci + (key === "ArrowLeft" ? -1 : 1)];
    if (!next) return null;
    return next.reduce((best, n) => (Math.abs(L.pos.get(n.id).y - p.y) < Math.abs(L.pos.get(best.id).y - p.y) ? n : best), next[0]).id;
  }
  root.addEventListener("keydown", (e) => {
    const g = e.target.closest ? e.target.closest(".gv-n") : null;
    if (e.key === "+" || e.key === "=") { zoom(1.2); e.preventDefault(); return; }
    if (e.key === "-") { zoom(1 / 1.2); e.preventDefault(); return; }
    if (e.key === "0") { fit(); e.preventDefault(); return; }
    if (!g) return;
    const nid = g.dataset.id;
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(nid, true); return; }
    if (e.key === "Escape") { select(null, true); g.focus(); return; }
    if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const to = step(nid, e.key);
    if (!to) return;
    nodeEls.forEach((x, k) => x.setAttribute("tabindex", k === to ? "0" : "-1"));
    reveal(to);
    nodeEls.get(to).focus({ preventScroll: true });
  });
  if (nodes.length) nodeEls.get(nodes[0].id).setAttribute("tabindex", "0");

  const tools = h("div", { class: "gv-zoom", role: "group", "aria-label": "Zoom the graph" },
    h("button", { type: "button", class: "icon-btn tiny", "aria-label": "Zoom in", tip: "Zoom in (+)", onclick: () => zoom(1.25) }, icon("plus")),
    h("button", { type: "button", class: "icon-btn tiny", "aria-label": "Zoom out", tip: "Zoom out (−)", onclick: () => zoom(0.8) }, h("span", { class: "gv-minus", "aria-hidden": "true" }, "−")),
    h("button", { type: "button", class: "icon-btn tiny", "aria-label": "Fit the graph", tip: "Fit (0)", onclick: fit }, icon("expand")));
  const el = h("div", { class: "gv-canvas" }, tools, root);
  requestAnimationFrame(() => { fit(); if (o.selected) select(o.selected, false); });
  return { el, select: (nid) => select(nid, false), fit, focus: () => { const g = root.querySelector('.gv-n[tabindex="0"]'); if (g) g.focus(); } };
}
