/* Chart primitives. The method (the dataviz skill): one axis only; thin marks (bars at most 24px,
   4px rounded data ends, square at the baseline); a 2px surface gap between touching segments; a
   legend for two or more series; a hover and keyboard-focus tooltip on every mark; a table twin for
   every chart; status colours only where a series means good or bad, always with an icon and a
   label; and "not measured" never drawn as zero. Charts are static: nothing animates on refresh. */

import { $$, h, svg, icon, attachTip, num, pct } from "./core.js";

// The validated categorical palette, by slot (tokens.css: --series-1 .. --series-8).
export const SERIES = (n) => "var(--series-" + n + ")";
export const STATUS_MARK = { good: "var(--good-mark)", warning: "var(--warning-mark)", serious: "var(--serious-mark)",
  critical: "var(--critical-mark)", neutral: "var(--neutral-mark)" };

// A tooltip: the value leads, the series name follows, keyed by a short stroke of its colour.
export function tipBox(title, rows, foot) {
  return h("div", { class: "tipbox" }, title ? h("div", { class: "tip-t" }, title) : null,
    (rows || []).map((r) => h("div", { class: "tip-r" },
      r.color ? h("span", { class: "tip-key", style: { background: r.color } }) : null,
      r.icon ? icon(r.icon) : null,
      h("b", null, r.value), h("span", null, r.label))),
    foot ? h("div", { class: "tip-f" }, foot) : null);
}

export function legend(series, opts) {
  const o = opts || {};
  return h("ul", { class: "legend" + (o.line ? " line" : ""), "aria-label": "Legend" }, series.map((s) =>
    h("li", null, h("span", { class: "sw" + (s.hatch ? " hatch" : ""), style: s.hatch ? null : { background: s.color } }),
      s.icon ? icon(s.icon) : null, h("span", null, s.label))));
}

function niceMax(v) {
  if (!v || v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}
function tickLabel(v) {
  if (v >= 10000) return Math.round(v / 1000) + "K";
  return Number.isInteger(v) ? v.toLocaleString("en-US") : String(Math.round(v * 10) / 10);
}

/* Stacked columns on one axis. series: [{key, label, color, icon}]; rows: [{label, values: {key: n}}].
   Segments stack with a 2px gap; the top segment carries the 4px rounded data end. */
export function columns(opts) {
  const o = opts || {};
  const series = o.series || [];
  const rows = o.rows || [];
  const totals = rows.map((r) => series.reduce((a, s) => a + (Number(r.values[s.key]) || 0), 0));
  const max = niceMax(Math.max(0, ...totals));
  const ticks = [0, max / 2, max];
  const maxLabels = o.maxLabels || 8;
  const every = Math.max(1, Math.ceil(rows.length / maxLabels));
  // A narrow chart (a small widget) keeps every other label (k2); the CSS picks by the chart's width.
  const label = (r, i) => (i % every === 0 ? h("span", { class: "xl" + (i % (every * 2) === 0 ? " k2" : " k1") }, r.short || r.label)
    : h("span", { class: "xl" }));
  const plot = h("div", { class: "plot", style: { "--h": (o.height || 160) + "px" } },
    h("div", { class: "yaxis", "aria-hidden": "true" }, ticks.map((t) => h("span", { class: "tick", style: { bottom: (t / max * 100) + "%" } },
      h("span", { class: "tick-l" }, tickLabel(t))))),
    h("div", { class: "cols" }, rows.map((r, i) => {
      const total = totals[i];
      const segs = series.filter((s) => Number(r.values[s.key]) > 0);
      const col = h("div", { class: "col mark", tabindex: "0", role: "img",
        "aria-label": r.label + ": " + series.map((s) => (r.values[s.key] || 0) + " " + s.label).join(", ") },
      h("div", { class: "stack", style: { height: (total / max * 100) + "%" } }, segs.map((s) =>
        h("span", { class: "cseg", style: { background: s.color, flexGrow: String(r.values[s.key]) } }))));
      attachTip(col, () => tipBox(r.tipTitle || r.label, series.map((s) => ({ color: s.color, icon: s.icon,
        value: num(r.values[s.key] || 0), label: s.label })), r.tipFoot));
      return col;
    })));
  const axis = h("div", { class: "xaxis", "aria-hidden": "true" }, rows.map(label));
  return h("figure", { class: "viz columns" }, h("div", { class: "plot-wrap" }, plot, axis),
    series.length > 1 ? legend(series) : null);
}

/* Ranked horizontal bars, one hue (one series: no legend; the title names it).
   rows: [{label, value (null when not measured), display, sub, href, why}]; max: the scale's end. */
export function bars(opts) {
  const o = opts || {};
  const rows = o.rows || [];
  const max = o.max || niceMax(Math.max(0, ...rows.map((r) => r.value || 0)));
  return h("figure", { class: "viz bars" }, h("ul", { class: "bar-list" }, rows.map((r) => {
    const measured = r.value !== null && r.value !== undefined;
    const lab = r.href ? h("a", { href: r.href }, r.label) : h("span", null, r.label);
    const track = h("span", { class: "track" + (measured ? "" : " nm") },
      measured && r.value > 0 ? h("span", { class: "bar", style: { width: Math.max(0.8, r.value / max * 100) + "%",
        background: r.color || o.color || SERIES(1) } }) : null);
    const li = h("li", { class: "bar-row mark", tabindex: "0" },
      h("span", { class: "bar-l" }, r.icon ? icon(r.icon) : null, lab, r.sub ? h("small", null, r.sub) : null),
      track,
      h("span", { class: "bar-v" + (measured ? "" : " nm-text") }, measured ? (r.display || num(r.value)) : "not measured"));
    attachTip(li, () => tipBox(r.label, [{ color: measured ? (r.color || o.color || SERIES(1)) : null,
      value: measured ? (r.display || num(r.value)) : "not measured", label: o.unit || "" }], measured ? r.tip : (r.why || r.tip)));
    return li;
  })));
}

/* One whole per row, split into parts (a thin 100% bar). A part at zero draws nothing; a part that is
   not measured is hatched, never drawn as a measured share. */
export function stack100(opts) {
  const o = opts || {};
  const series = o.series || [];
  const rows = o.rows || [];
  return h("figure", { class: "viz stack100" }, h("ul", { class: "s100-list" }, rows.map((r) => {
    const total = series.reduce((a, s) => a + (Number(r.values[s.key]) || 0), 0);
    const bar = h("span", { class: "s100" + (total ? "" : " none") }, total ? series.filter((s) => Number(r.values[s.key]) > 0).map((s) => {
      const part = h("span", { class: "part mark" + (s.hatch ? " hatch" : ""), tabindex: "0",
        style: { flexGrow: String(r.values[s.key]), background: s.hatch ? null : s.color } });
      attachTip(part, () => tipBox(r.label, [{ color: s.hatch ? null : s.color, icon: s.icon,
        value: r.values[s.key] + " of " + total + " (" + pct(r.values[s.key] / total) + ")", label: s.label }]));
      return part;
    }) : null);
    return h("li", { class: "s100-row" }, h("span", { class: "s100-l" }, r.href ? h("a", { href: r.href }, r.label) : r.label,
      h("small", null, total ? (o.summary ? o.summary(r, total) : total + " in all") : (o.none || "nothing yet"))), bar);
  })), series.length > 1 ? legend(series) : null);
}

/* A tall segmented bar: one whole, at a glance; each part prints its share where it fits. */
export function segbar(opts) {
  const o = opts || {};
  const parts = (o.parts || []).filter((p) => p.value > 0);
  const total = parts.reduce((a, p) => a + p.value, 0);
  if (!total) return h("p", { class: "muted small viz-none" }, o.none || "Nothing to show yet.");
  return h("figure", { class: "viz segbar" }, h("div", { class: "seg-tall", role: "img",
    "aria-label": parts.map((p) => p.label + " " + p.value).join(", ") }, parts.map((p) => {
    const share = p.value / total;
    // a hatched part (not read, not measured) prints its count on a plate, so the hatching never crosses it
    const count = share < 0.14 ? null : p.hatch ? h("span", { class: "segn" }, String(p.value)) : String(p.value);
    const el = h("span", { class: "segp mark " + (p.ink || "ink-light") + (p.hatch ? " hatch" : ""), tabindex: "0",
      style: { flexGrow: String(p.value), background: p.hatch ? null : p.color } }, count);
    attachTip(el, () => tipBox(p.label, [{ color: p.color, icon: p.icon, value: p.value + " (" + pct(share) + ")", label: p.label }]));
    return el;
  })), legend(parts.map((p) => ({ label: p.label, color: p.color, icon: p.icon, hatch: p.hatch }))));
}

/* A 24px sparkline: a 2px line in the accent, with its end marked. values: numbers in [lo, hi]. */
export function sparkline(values, opts) {
  const o = opts || {};
  const vs = (values || []).filter((v) => v !== null && v !== undefined);
  if (vs.length < 2) return null;
  const lo = o.min !== undefined ? o.min : Math.min(...vs);
  const hi = o.max !== undefined ? o.max : Math.max(...vs);
  const span = hi - lo || 1;
  const pts = vs.map((v, i) => [i / (vs.length - 1) * 100, 22 - (v - lo) / span * 20]);
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(2) + " " + p[1].toFixed(2)).join(" ");
  const last = pts[pts.length - 1];
  return h("span", { class: "spark", "aria-hidden": "true" },
    svg("svg", { viewBox: "0 0 100 24", preserveAspectRatio: "none" },
      svg("path", { d: d + " L100 24 L0 24 Z", class: "spark-area" }),
      svg("path", { d, class: "spark-line", "vector-effect": "non-scaling-stroke" })),
    h("span", { class: "spark-dot", style: { left: last[0] + "%", top: (last[1] / 24 * 100) + "%" } }));
}

/* A waterfall of each task's rounds on one time axis, coloured by the gate's verdict (status colours,
   with icons in the legend), with merge and escalation markers. */
export function waterfall(opts) {
  const o = opts || {};
  const tasks = o.tasks || [];
  const times = [];
  tasks.forEach((t) => {
    t.rounds.forEach((r) => { if (r.start) times.push(Date.parse(r.start)); if (r.end) times.push(Date.parse(r.end)); });
    if (t.merged_at) times.push(Date.parse(t.merged_at));
    if (t.escalated_at) times.push(Date.parse(t.escalated_at));
  });
  const ok = times.filter((x) => !Number.isNaN(x));
  if (!tasks.length) return h("p", { class: "muted small viz-none" }, "No task has run yet.");
  const t0 = ok.length ? Math.min(...ok) : 0;
  const t1 = ok.length ? Math.max(...ok) : 1;
  const span = Math.max(1, t1 - t0);
  const pos = (at) => (at ? (Date.parse(at) - t0) / span * 100 : null);
  const VERD = {
    passed: { color: STATUS_MARK.good, icon: "check-circle", label: "Gate passed" },
    failed: { color: STATUS_MARK.critical, icon: "x-circle", label: "Gate failed" },
    open: { color: STATUS_MARK.neutral, icon: "clock", label: "In its gate" },
  };
  const vOf = (r) => (r.verdict === "passed" ? "passed" : r.verdict ? "failed" : "open");
  const fmt = (ms) => { const d = new Date(ms); return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"); };
  const rows = tasks.map((t) => {
    const track = h("div", { class: "wf-track" });
    t.rounds.forEach((r, i) => {
      const v = VERD[vOf(r)];
      let left = pos(r.start);
      let right = pos(r.end);
      if (left === null && right === null) { left = 0; right = 0; }
      if (left === null) left = right;
      if (right === null) right = left;
      const width = Math.max(1.2, right - left);
      const bar = h("span", { class: "wf-bar mark", tabindex: "0", style: { left: Math.min(left, 100 - width) + "%", width: width + "%",
        background: v.color } });
      attachTip(bar, () => tipBox(t.task + " · round " + r.round, [{ color: v.color, icon: v.icon, value: v.label, label: "" },
        { value: r.model || "model not recorded", label: "builder" }],
      (r.start ? "started " + String(r.start).replace("T", " ").replace("Z", " UTC") : "start not recorded")
        + (r.end ? " · ended " + String(r.end).slice(11, 16) + " UTC" : "")));
      track.append(bar);
      if (i === 0 && !t.rounds.length) track.append(h("span"));
    });
    if (t.merged_at) track.append(h("span", { class: "wf-mark good", style: { left: pos(t.merged_at) + "%" }, tip: t.task + " merged" }, icon("merge")));
    if (t.escalated_at) track.append(h("span", { class: "wf-mark warning", style: { left: pos(t.escalated_at) + "%" }, tip: t.task + " escalated to a person" }, icon("flag")));
    return h("div", { class: "wf-row" }, h("span", { class: "wf-l" }, o.href ? h("a", { href: o.href(t), class: "mono" }, t.task) : h("span", { class: "mono" }, t.task),
      h("small", null, t.title || "")), track);
  });
  // the two middle ticks give way on a narrow chart (CSS), so the times never collide
  const ticks = ok.length ? [0, 1 / 3, 2 / 3, 1].map((f) => h("span", { class: f > 0 && f < 1 ? "mid" : null, style: { left: (f * 100) + "%" } },
    fmt(t0 + f * span))) : [];
  return h("figure", { class: "viz waterfall" }, h("div", { class: "wf" }, rows,
    h("div", { class: "wf-row wf-axis", "aria-hidden": "true" }, h("span", { class: "wf-l" }, "Local time"), h("div", { class: "wf-track" }, ticks))),
  legend([{ label: VERD.passed.label, color: VERD.passed.color, icon: "check-circle" },
    { label: VERD.failed.label, color: VERD.failed.color, icon: "x-circle" },
    { label: VERD.open.label, color: VERD.open.color, icon: "clock" }]),
  h("p", { class: "viz-note" }, icon("merge"), " merged", h("span", { class: "sep" }, " · "), icon("flag"), " escalated"));
}

/* The table twin of a chart: the WCAG-clean equivalent, never gated behind hover. */
export function dataTable(columnsDef, rows, caption) {
  return h("div", { class: "tbl" }, h("table", null, caption ? h("caption", { class: "vh" }, caption) : null,
    h("thead", null, h("tr", null, columnsDef.map((c) => h("th", { scope: "col", class: c.num ? "num" : null }, c.label)))),
    h("tbody", null, rows.map((r) => h("tr", null, columnsDef.map((c, i) => {
      const v = typeof c.value === "function" ? c.value(r) : r[c.key];
      const cell = v === null || v === undefined ? h("span", { class: "nm-text" }, c.none || "not measured") : v;
      // each cell names its column, so a phone shows the table as stacked rows (shell.css)
      return i === 0 ? h("th", { scope: "row" }, cell) : h("td", { class: c.num ? "num" : null, "data-label": c.label }, cell);
    }))))));
}

/* A meter: one ratio against its whole, the track a lighter step of the same hue. */
export function meter(value, of, opts) {
  const o = opts || {};
  if (value === null || value === undefined || !of) {
    return h("span", { class: "meter nm", tip: o.why || "not measured" }, h("span", { class: "nm-text" }, "not measured"));
  }
  return h("span", { class: "meter", role: "img", "aria-label": value + " of " + of },
    h("span", { class: "meter-fill", style: { width: (value / of * 100) + "%", background: o.color || "var(--accent)" } }));
}

// Re-focus helper for charts that rebuild: nothing animates, so a re-render is instant.
export function marks(root) { return $$(".mark", root); }
