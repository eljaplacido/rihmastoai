/* The data-flow diagram of a project (kernel/itdata_flow.py, FR-ITD1): where data comes from, Rihmasto, its agents
   and where data goes, drawn as an SVG. Wide, the four groups are columns read left to right; on a phone they are
   rows read top to bottom, so nothing scrolls sideways. An edge whose end is outside this machine and your network is
   dashed and marked; a node's border says where it is (a solid line here, a dotted one when not known, the warning
   colour outside), and its state is a word in its second line, never colour alone. Every node is a button: it
   opens the connection it stands for (onPick). The kernel's labels are its own words (data-ud). */

import { h, svg, fill } from "./core.js";

const NODE_H = 46;
const GAP_Y = 12;
const HEAD = 28;
const WIDE = 760;
const LOC_CLASS = { "this machine": "loc-here", "your network": "loc-net", outside: "loc-out", "not known": "loc-unk" };

function cut(text, width, px) {
  const room = Math.max(4, Math.floor(width / px));
  const s = String(text || "");
  return s.length > room ? s.slice(0, room - 1) + "…" : s;
}

/* Where each node goes: wide, one column per group; narrow, one row per group with two nodes a line. */
function layout(flow, width) {
  const wide = width >= WIDE;
  const cols = flow.columns.map((c) => flow.nodes.filter((n) => n.column === c.id));
  const pos = {};
  const heads = [];
  if (wide) {
    const nodeW = Math.min(200, Math.floor((width - 3 * 40) / 4));
    const step = (width - nodeW) / 3;
    const tallest = Math.max(...cols.map((c) => c.length));
    const height = HEAD + tallest * (NODE_H + GAP_Y);
    cols.forEach((list, i) => {
      const top = HEAD + (tallest - list.length) * (NODE_H + GAP_Y) / 2;
      heads.push({ x: i * step + nodeW / 2, y: 16, text: flow.columns[i].label, anchor: "middle" });
      list.forEach((n, j) => { pos[n.id] = { x: i * step, y: top + j * (NODE_H + GAP_Y), w: nodeW }; });
    });
    return { pos, heads, height, wide };
  }
  const per = 2;
  const nodeW = Math.floor((width - 12 * (per - 1)) / per);
  let y = 0;
  cols.forEach((list, i) => {
    heads.push({ x: 0, y: y + 16, text: flow.columns[i].label, anchor: "start" });
    y += HEAD;
    list.forEach((n, j) => {
      const col = list.length === 1 ? 0.5 : j % per;
      pos[n.id] = { x: col * (nodeW + 12), y: y + Math.floor(j / per) * (NODE_H + GAP_Y), w: nodeW };
    });
    y += Math.ceil(list.length / per) * (NODE_H + GAP_Y) + 10;
  });
  return { pos, heads, height: y, wide };
}

function edgePath(a, b, wide) {
  if (wide) {
    const fwd = b.x >= a.x;
    const x1 = fwd ? a.x + a.w : a.x;
    const x2 = fwd ? b.x : b.x + b.w;
    const y1 = a.y + NODE_H / 2;
    const y2 = b.y + NODE_H / 2;
    const mid = (x1 + x2) / 2;
    return `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`;
  }
  const down = b.y >= a.y;
  const x1 = a.x + a.w / 2;
  const x2 = b.x + b.w / 2;
  const y1 = down ? a.y + NODE_H : a.y;
  const y2 = down ? b.y : b.y + NODE_H;
  const mid = (y1 + y2) / 2;
  return `M${x1},${y1} C${x1},${mid} ${x2},${mid} ${x2},${y2}`;
}

function nodeEl(n, p, onPick) {
  const name = n.label + ": " + n.sub + (n.state ? ", " + n.state : "");
  const g = svg("g", { class: "itd-node " + (LOC_CLASS[n.locality] || "loc-unk") + (n.state === "failing" ? " failing" : ""),
    transform: `translate(${p.x},${p.y})`, role: "button", tabindex: "0", "aria-label": name, "data-node": n.id,
    "data-item": n.item || null, "data-agent": n.agent || null },
  svg("title", null, name),
  svg("rect", { width: p.w, height: NODE_H, rx: 8, ry: 8 }),
  svg("text", { x: 10, y: 19, class: "itd-n-t", "data-ud": "" }, cut(n.label, p.w - 16, 7)),
  svg("text", { x: 10, y: 36, class: "itd-n-s", "data-ud": "" }, cut(n.sub + (n.state && n.state !== "on" ? " · " + n.state : ""), p.w - 16, 6)));
  const pick = () => onPick(n);
  g.addEventListener("click", pick);
  g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
  return g;
}

function draw(box, flow, onPick) {
  const width = Math.max(280, Math.floor(box.clientWidth || 0));
  const L = layout(flow, width);
  const edges = flow.edges.filter((e) => L.pos[e.from] && L.pos[e.to]).map((e) => svg("path", {
    class: "itd-edge" + (e.leaves ? " leaves" : ""), d: edgePath(L.pos[e.from], L.pos[e.to], L.wide),
    "marker-end": e.leaves ? "url(#itd-arrow-out)" : "url(#itd-arrow)" }));
  const marker = (id) => svg("marker", { id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" },
    svg("path", { d: "M0,0 L10,5 L0,10 z" }));
  const picture = svg("svg", { class: "itd-svg", viewBox: `0 0 ${width} ${L.height}`, width, height: L.height,
    role: "group", "aria-label": "Data flow of " + flow.title + ": where data comes from, Rihmasto, the agents and where data goes" },
  svg("defs", null, marker("itd-arrow"), marker("itd-arrow-out")),
  L.heads.map((t) => svg("text", { x: t.x, y: t.y, "text-anchor": t.anchor, class: "itd-head" }, t.text)),
  svg("g", { class: "itd-edges" }, edges),
  flow.nodes.filter((n) => L.pos[n.id]).map((n) => nodeEl(n, L.pos[n.id], onPick)));
  fill(box, picture);
  box.dataset.wide = L.wide ? "1" : "0";
}

/* The diagram as an element. It draws itself once it has a width, and again when the width crosses into the other
   layout (a phone turned, a window resized). */
export function flowDiagram(flow, onPick) {
  const box = h("div", { class: "itd-flow-box" });
  let last = null;
  const redraw = () => {
    if (!box.isConnected || !box.clientWidth) return;
    const key = Math.floor(box.clientWidth / 40);
    if (key === last) return;
    last = key;
    draw(box, flow, onPick);
  };
  // drawn in the next frame, never inside the observer's own callback (a resize there is a "ResizeObserver loop")
  if (typeof ResizeObserver === "function") new ResizeObserver(() => requestAnimationFrame(redraw)).observe(box);
  requestAnimationFrame(redraw);
  return box;
}

export function legend() {
  const item = (cls, words) => h("li", null, h("span", { class: "itd-key " + cls, "aria-hidden": "true" }), h("span", null, words));
  return h("ul", { class: "itd-legend", "aria-label": "How to read the diagram" },
    item("k-here", "this machine or your network"), item("k-out", "outside"), item("k-unk", "address not known here"),
    item("k-leaves", "data may leave the machine"));
}
