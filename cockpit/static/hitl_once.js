/* New one-use links shown once (FR-HITL2): a link made in People in the loop, a fresh one a Nudge made for a
   person outside, or either confirmed in Ask Rihma. Only a hash of a link is kept, so this is the one place its
   address is seen: each with Copy, and a warning when it points at this computer only. Never stored in the
   browser: it is drawn once, then gone. */

import { h, icon, say, button } from "./core.js";

function copyButton(url, id, reusable) {
  const b = button("Copy the link", { icon: "copy", kind: "small", "data-control": "hitl_link_copy", aria: "Copy the link " + id });
  b.addEventListener("click", () => {
    const done = () => say(reusable ? "Copied. Pass it on yourself." : "Copied. It opens once.", "good");   // an observer link (FR-SHR1) opens until it ends
    const manual = () => say("Select the address and copy it.", "warning");
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(done, manual);
    else manual();
  });
  return b;
}

/* `once`: [{ link, name, url, said }] as the routes give them; `warning`: the kernel's words when the links point at
   this computer only. */
export function onceLinks(once, warning) {
  return h("div", { class: "hl-once", role: "status", "data-once": "" },
    h("p", null, h("b", null, "Shown once: "), once.length === 1 ? "pass this link on now. It is not shown again."
      : "pass these links on now. They are not shown again."),
    once.map((o) => h("div", { class: "hl-once-1", "data-link": o.link },
      h("p", { class: "small" }, h("b", null, o.name), " · " + o.link + (o.said ? " · " : ""), o.said ? h("span", { "data-ud": "" }, o.said) : null),
      h("p", { class: "mono small hl-url", "data-ud": "" }, o.url), copyButton(o.url, o.link, o.reusable))),
    warning ? h("p", { class: "small hl-local", role: "note" }, icon("alert"), " ", h("span", { "data-ud": "" }, warning)) : null);
}
