/* What holds delivery for a person's answer (FR-HITL2): the open asks of a required check family, from a project's
   Now (kernel/status.py `now.hitl`, kernel/hitl.py `holds`). Shown where the owner looks for what blocks work: the
   project's Inbox, the all-projects Inbox and the project's Now line, each with the way to People in the loop.
   Only what blocks work appears here; advised asks wait in People in the loop. Record text is data-ud. */

import { h, icon, link, plural } from "./core.js";
import { pick, datum } from "./words.js";

const FAMILY = { quality: "Quality", governance: "Governance", legal: "Legal", security: "Security", general: "General" };

function row(pid, a, title) {
  return h("li", { "data-held-ask": a.id },
    title ? h("b", null, title + ": ") : null,
    h("a", { href: link(pid, "loop") }, a.id), " · " + (FAMILY[a.family] || a.family) + ", waits on ",
    h("span", { "data-ud": "" }, a.to + (a.external ? " (outside)" : "")), " · ", datum(a.text));
}

function box(key, rows, n, href) {
  return h("section", { class: "hl-held", "data-held": key, "aria-label": "Delivery waits on an answer" },
    h("h2", { class: "label-h" }, icon("user"), " ", pick("Delivery waits on " + plural(n, "answer") + " from a person",
      plural(n, "required answer") + " hold delivery")),
    h("p", { class: "small" }, pick("These checks must be answered before delivery. Whoever they are put to answers them in People in the loop; nudge them, or set that check to advise only.",
      "Open asks of a required check family (People in the loop): delivery is held until each is answered, or the family is set to advise.")),
    h("ul", null, rows),
    h("p", null, h("a", { href }, "Open People in the loop", icon("arrow-right"))));
}

// One project's: from its `now` (null when nothing holds it).
export function heldBox(pid, now) {
  const asks = (now && now.hitl) || [];
  if (!asks.length) return null;
  return box(pid, asks.map((a) => row(pid, a)), asks.length, link(pid, "loop"));
}

// Every project's, from the projects list (each with its `now`): for the all-projects Inbox.
export function heldAll(projects) {
  const rows = [];
  let first = null;
  (projects || []).forEach((p) => ((p.now || {}).hitl || []).forEach((a) => {
    first = first || p.id;
    rows.push(row(p.id, a, p.title || p.id));
  }));
  return rows.length ? box("all", rows, rows.length, link(first, "loop")) : null;
}

// The Now line's way on: People in the loop when only required answers hold the project, else the Inbox.
export function nowGo(n) {
  const cards = (n && n.cards) || [];
  return n && !cards.length && (n.hitl || []).length ? ["loop", "Open People in the loop"] : ["inbox", "Open the Inbox"];
}
