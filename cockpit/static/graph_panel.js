/* The Knowledge graph's filter panel and legend (graph.js, FR-GRV1). One panel scopes the graph and the table
   alike: kinds by family (each with how many there are), relations, states, the time window, only issues and,
   across projects, the projects. On a wide screen it sits beside the graph; on a phone it opens as a sheet. Each
   change applies at once and is kept in the route. A state and an issue always carry an icon and a word. */

import { S, h, icon, chip, button } from "./core.js";
import { shapeOf } from "./graph_draw.js";

const STATE = { open: ["info", "clock", "Open"], closed: ["neutral", "check", "Closed"], superseded: ["nm", "dashed", "Superseded"] };
const WINDOW = { all: "All records", "24h": "Last 24 hours", "7d": "Last 7 days", "30d": "Last 30 days", "90d": "Last 90 days" };

export function stateChip(state) {
  const s = STATE[state];
  return s ? chip(s[0], s[1], s[2]) : chip("neutral", null, "No lifecycle", { tip: "A test, a person or a model has no state of its own" });
}
export function sevChip(sev, text) {
  return sev === "critical" ? chip("critical", "x-circle", text || "Contradiction") : chip("warning", "alert", text || "Needs a look");
}
export function swatch(family) {
  return h("span", { class: "gv-sw fam-" + family + " " + shapeOf(family), "aria-hidden": "true" });
}

function box(label, checked, key, onchange, count) {
  const input = h("input", { type: "checkbox", checked: checked || null, "data-key": key });
  input.addEventListener("change", onchange);
  return h("label", { class: "gv-check" }, input, h("span", null, label), count === undefined ? null : h("span", { class: "muted small" }, String(count)));
}

// A list filter from its checkboxes: every one ticked is no filter at all.
function picked(root, prefix) {
  const all = [...root.querySelectorAll('input[data-key^="' + prefix + '"]')];
  const on = all.filter((x) => x.checked).map((x) => x.dataset.key.slice(prefix.length));
  return on.length === all.length ? [] : on;
}

// No kind ticked is read as every kind, as no filter is.
function kindsSet(st, root, set) { set(st, { kinds: picked(root, "gvk:") }); }

export function graphPanel(st, set) {
  const m = st.model;
  if (!m || m.outcome !== "answered") return null;
  const f = st.f;
  const root = h("div", { class: "gv-filters" });
  const has = (list, id) => !(list || []).length || list.includes(id);
  const present = m.kinds.filter((k) => k.total > 0);
  const families = m.families.map((fam) => {
    const mine = present.filter((k) => fam.kinds.includes(k.id));
    return mine.length ? h("div", { class: "gv-fam" }, h("p", { class: "gv-fam-h" }, swatch(fam.id), h("span", null, fam.label)),
      mine.map((k) => box(k.label, has(f.kinds, k.id), "gvk:" + k.id, () => kindsSet(st, root, set), k.matching + " of " + k.total))) : null;
  });
  const rels = h("details", { class: "gv-rels" }, h("summary", null, "Relations" + ((f.rels || []).length ? " (" + f.rels.length + " chosen)" : "")),
    m.relations.map((r) => box(r.label, has(f.rels, r.id), "gvr:" + r.id, () => set(st, { rels: picked(root, "gvr:") }))));
  const states = h("fieldset", { class: "gv-fs" }, h("legend", null, "State"),
    m.states.map((s) => box(STATE[s][2], has(f.states, s), "gvs:" + s, () => set(st, { states: picked(root, "gvs:") }))),
    h("p", { class: "muted small" }, "A test, a person or a model has no state: it always shows."));
  const win = h("select", { class: "w-select", "aria-label": "Time window", "data-key": "gvw" },
    Object.entries(WINDOW).map(([v, l]) => h("option", { value: v, selected: (f.window || "all") === v || null }, l)));
  win.addEventListener("change", () => set(st, { window: win.value }));
  const issues = box("Only nodes with an issue", f.issues === true || f.issues === "1", "gvi", (e) => set(st, { issues: e.target.checked }));
  const projects = m.scope === "factory" ? h("fieldset", { class: "gv-fs" }, h("legend", null, "Projects"),
    (S.projects || []).map((p) => box(p.title, has(f.projects, p.id), "gvp:" + p.id, () => set(st, { projects: picked(root, "gvp:") })))) : null;
  root.append(...[h("fieldset", { class: "gv-fs" }, h("legend", null, "Kinds"), families), rels, states,
    h("label", { class: "gv-win" }, h("span", null, "Time"), win), issues, projects,
    button("Reset filters", { kind: "small quiet", icon: "undo", onclick: () => { st.f = { hops: "1" }; set(st, {}); } })]
    .filter(Boolean));            // a filter that does not apply here (Projects, inside one project) adds nothing
  return root;
}

export function legend(m) {
  const present = new Set(m.nodes.map((n) => n.kind));
  const label = (id) => (m.kinds.find((k) => k.id === id) || {}).label || id;
  return h("figure", { class: "gv-legend", "aria-label": "Legend" },
    h("ul", { class: "legend" }, m.families.filter((fam) => fam.kinds.some((k) => present.has(k))).map((fam) => h("li", null, swatch(fam.id),
      h("span", null, h("b", null, fam.label), ": " + fam.kinds.filter((k) => present.has(k)).map(label).join(", "))))),
    h("ul", { class: "legend" }, h("li", null, h("span", { class: "gv-ring-sw warning", "aria-hidden": "true" }), icon("alert"), h("span", null, "Ring: needs a look (no test, a test without a requirement)")),
      h("li", null, h("span", { class: "gv-ring-sw critical", "aria-hidden": "true" }), icon("x-circle"), h("span", null, "Ring: a contradiction (overturned, refuted, broken)")),
      h("li", null, h("span", { class: "gv-dash-sw", "aria-hidden": "true" }), h("span", null, "Dashed link: a model's proposal no person decided"))),
    h("figcaption", { class: "muted small" }, "Drag to pan; Ctrl and the wheel, or the buttons, zoom; the arrow keys move between nodes and Enter opens one."));
}
