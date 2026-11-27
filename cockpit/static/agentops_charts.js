/* Agent operations' own chart forms (FR-AOP1), drawn as charts.js draws its own: one axis, thin marks, a legend
   for two or more series, a hover and keyboard tooltip on every mark, a table twin beside, and "not measured" never
   drawn as zero.

     lines(opts)     a line per series over time (2px lines, 8px markers on the hovered point); a period with no
                     value leaves a gap in its line, never a drop to zero; a value alone on its line is a dot
     heatmap(opts)   rows x columns, one hue from light to dark by magnitude (sequential); a cell with runs but no
                     measured value is hatched, a cell with no run is empty */

import { h, svg, attachTip } from "./core.js";
import { tipBox, legend } from "./charts.js";

function niceMax(v) {
  if (!v || v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}
function short(v) {
  const a = Math.abs(v);
  if (a >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (a >= 1e4) return Math.round(v / 1000) + "K";
  return Number.isInteger(v) ? v.toLocaleString("en-US") : String(Math.round(v * 100) / 100);
}

/* opts: { series: [{key, label, color}], points: [{label, values: {key: n | null}}], height, fmt(v), unit } */
export function lines(opts) {
  const o = opts || {};
  const series = o.series || [];
  const pts = o.points || [];
  const fmt = o.fmt || short;
  const all = [];
  pts.forEach((p) => series.forEach((s) => { const v = p.values[s.key]; if (v !== null && v !== undefined) all.push(v); }));
  const max = niceMax(Math.max(0, ...all));
  const W = 100, H = 100;
  const x = (i) => (pts.length < 2 ? W / 2 : i / (pts.length - 1) * W);
  const y = (v) => H - v / max * H;
  const paths = series.map((s) => {
    let d = "", open = false;
    pts.forEach((p, i) => {
      const v = p.values[s.key];
      if (v === null || v === undefined) { open = false; return; }
      d += (open ? " L" : " M") + x(i).toFixed(2) + " " + y(v).toFixed(2);
      open = true;
    });
    return svg("path", { d: d.trim() || "M0 0", class: "aol-line", stroke: s.color, "vector-effect": "non-scaling-stroke" });
  });
  // A value with no value beside it on its line (one day, or days apart) is a bare "M x y": a path that draws
  // nothing. Each such value is a dot, so the largest figure of a chart is never invisible (FR-AOP2).
  const has = (s, i) => i >= 0 && i < pts.length && pts[i].values[s.key] !== null && pts[i].values[s.key] !== undefined;
  const lone = h("div", { class: "aol-pts", "aria-hidden": "true" }, series.flatMap((s) => pts.map((p, i) => (has(s, i) && !has(s, i - 1) && !has(s, i + 1)
    ? h("span", { class: "aol-pt", "data-series": s.key, style: { left: x(i) + "%", top: y(p.values[s.key]) + "%", background: s.color } }) : null)).filter(Boolean)));
  const grid = [0, 0.5, 1].map((f) => svg("line", { x1: 0, x2: W, y1: H - f * H, y2: H - f * H, class: "aol-grid", "vector-effect": "non-scaling-stroke" }));
  const plot = svg("svg", { viewBox: "0 0 " + W + " " + H, preserveAspectRatio: "none", class: "aol-svg", "aria-hidden": "true" }, grid, paths);
  const dots = h("div", { class: "aol-dots", "aria-hidden": "true" });
  const hits = h("div", { class: "aol-hits" }, pts.map((p, i) => {
    const vals = series.filter((s) => p.values[s.key] !== null && p.values[s.key] !== undefined);
    const hit = h("span", { class: "aol-hit mark", tabindex: "0", role: "img", style: { left: x(i) + "%" },
      "aria-label": p.label + ": " + (vals.length ? vals.map((s) => fmt(p.values[s.key]) + " " + s.label).join(", ") : "nothing recorded") });
    const show = () => {
      dots.replaceChildren(...vals.map((s) => h("span", { class: "aol-dot", style: { left: x(i) + "%", top: y(p.values[s.key]) + "%", background: s.color } })));
      dots.style.setProperty("--x", x(i) + "%");
      dots.classList.add("on");
    };
    const hide = () => dots.classList.remove("on");
    hit.addEventListener("mouseenter", show); hit.addEventListener("focus", show);
    hit.addEventListener("mouseleave", hide); hit.addEventListener("blur", hide);
    attachTip(hit, () => tipBox(p.label, vals.length ? vals.map((s) => ({ color: s.color, value: fmt(p.values[s.key]), label: s.label }))
      : [{ value: "nothing recorded", label: "" }], o.unit || null));
    return hit;
  }));
  const every = Math.max(1, Math.ceil(pts.length / (o.maxLabels || 6)));
  const axis = h("div", { class: "aol-x", "aria-hidden": "true" }, pts.map((p, i) => (i % every === 0 || i === pts.length - 1
    ? h("span", { style: { left: x(i) + "%" }, class: i === 0 ? "first" : i === pts.length - 1 ? "last" : null }, p.label) : null)));
  const yaxis = h("div", { class: "aol-y", "aria-hidden": "true" }, [0, 0.5, 1].map((f) => h("span", { style: { bottom: (f * 100) + "%" } }, short(f * max))));
  return h("figure", { class: "viz aol" }, h("div", { class: "aol-wrap", style: { "--h": (o.height || 160) + "px" } },
    yaxis, h("div", { class: "aol-plot" }, plot, lone, dots, hits)), axis,
  series.length > 1 ? legend(series.map((s) => ({ label: s.label, color: s.color })), { line: true }) : null);
}

const STEPS = [14, 30, 48, 68, 90];   // the share of the hue mixed into the surface, light to dark

/* opts: { rows: [key], rowLabel(key), cols: [{key, label}], cells: [{row, col, ...}], value(cell) -> n | null,
           display(cell) -> text, onCell(cell), title } */
export function heatmap(opts) {
  const o = opts || {};
  const at = {};
  (o.cells || []).forEach((c) => { at[c.row + "\u0000" + c.col] = c; });
  const vals = (o.cells || []).map(o.value).filter((v) => v !== null && v !== undefined && v > 0);
  const max = Math.max(0, ...vals);
  const step = (v) => (max ? Math.min(STEPS.length - 1, Math.floor(v / max * STEPS.length - 1e-9)) : 0);
  const cols = o.cols || [];
  const grid = h("div", { class: "aoh-grid", role: "grid", "aria-label": o.title || "Heatmap",
    style: { gridTemplateColumns: "minmax(88px, max-content) repeat(" + cols.length + ", minmax(44px, 1fr))" } },
  h("span", { class: "aoh-corner" }), cols.map((c) => h("span", { class: "aoh-col", role: "columnheader", tip: c.label }, c.label)),
  (o.rows || []).map((r) => [h("span", { class: "aoh-row", role: "rowheader" }, o.rowLabel ? o.rowLabel(r) : r), cols.map((c) => {
    const cell = at[r + "\u0000" + c.key];
    if (!cell) return h("span", { class: "aoh-cell none", role: "gridcell", "aria-label": "no run" });
    const v = o.value(cell);
    const measured = v !== null && v !== undefined;
    const el = h("button", { type: "button", class: "aoh-cell mark" + (measured ? "" : " hatch"), role: "gridcell",
      "data-control": "agent_ops_drill", "aria-label": (o.rowLabel ? o.rowLabel(r) : r) + ", " + c.label + ": " + o.display(cell),
      style: measured && v > 0 ? { background: "color-mix(in oklab, var(--series-1) " + STEPS[step(v)] + "%, var(--surface))",
        color: step(v) >= 3 ? "#fff" : null } : null, onclick: () => o.onCell && o.onCell(cell) },
    measured ? short(v) : "");
    attachTip(el, () => tipBox((o.rowLabel ? o.rowLabel(r) : r) + " · " + c.label, [{ color: measured ? "var(--series-1)" : null,
      value: o.display(cell), label: "" }], "Select to see the runs"));
    return el;
  })]));
  const key = h("div", { class: "aoh-key", "aria-hidden": "true" }, h("span", null, "less"),
    STEPS.map((s) => h("span", { class: "aoh-sw", style: { background: "color-mix(in oklab, var(--series-1) " + s + "%, var(--surface))" } })),
    h("span", null, "more"), h("span", { class: "aoh-sw hatch" }), h("span", null, "not measured"));
  return h("figure", { class: "viz aoh" }, h("div", { class: "aoh-scroll" }, grid), key);
}
