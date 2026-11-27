/* Decisions that hold work and wait on another role the person also holds (cockpit/inbox_elsewhere.py, FR-ENF2).
   Seen through one role, the Inbox lists that role's cards only; a person working alone holds every role, so a card
   that holds work for IT, say, would wait unseen while they look as business owner. This note says it waits, links
   to where it is decided, and offers to show every role at once ("View as everything"). */

import { h, icon, button, plural, personaLabel, mayChoose, nav, link, enc } from "./core.js";
import { pick, datum } from "./words.js";

// Where a card is decided outside the Inbox: an enforcement card on the project's Enforcement view.
function where(c) {
  return c.kind === "enforcement" ? "#/p/" + enc(c.project) + "/enforcement" : link(c.project, "inbox");
}

export function elsewhereNote(list) {
  if (!list || !list.length) return null;
  const roles = Array.from(new Set(list.map((c) => c.decide_as))).map(personaLabel);
  const all = mayChoose() && nav.viewAll
    ? button(pick("Show every role's decisions here", "View as everything"), { icon: "users", kind: "small", key: "ib-view-all", "data-control": "inbox_view_all", onclick: () => nav.viewAll() })
    : h("p", { class: "small muted" }, "Switch role in the person menu to decide them.");
  return h("div", { class: "note warning ib-elsewhere", "data-key": "ib-elsewhere", role: "status" }, icon("user"),
    h("div", null,
      h("p", null, plural(list.length, "decision") + (list.length === 1 ? " holds" : " hold") + " work and " + (list.length === 1 ? "waits" : "wait")
        + " on " + roles.join(" or ") + ", a role you also hold."),
      h("ul", { class: "plain" }, list.map((c) => h("li", null, h("a", { href: where(c), class: "mono", "data-key": "ib-elsewhere:" + c.id }, c.id), " ",
        datum(c.title), h("span", { class: "small muted" }, " · " + personaLabel(c.decide_as) + (c.project_title ? " · " : ""), c.project_title ? datum(c.project_title) : null)))),
      all));
}
