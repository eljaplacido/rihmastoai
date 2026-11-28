/* Work in progress (FR-WIP1): on a project's Overview, what its own working copy holds that is not committed yet,
   by area, the oldest change, and the branch against its remote (GET /api/projects/<pid>/wip, kernel/wip.py). Only
   metadata is read and nothing is written. Rihmasto reads committed work only, so a large or old pile is a nudge to
   commit (Start here says it too); an area that is almost all untracked files looks generated: add it to .gitignore.
   Ask Rihma's "what am I in the middle of?" answers the same, by rule. */

import { h, icon, api, enc, button, act } from "./core.js";
import { datum } from "./words.js";
import { reachButton } from "./asks.js";   // Test connection, and an ask to the machine that has it (FR-RCH1)

const SHOWN = 6;
const KINDS = ["modified", "added", "deleted", "renamed", "conflicted", "untracked"];

function areaRow(a, piled) {
  const kinds = KINDS.filter((k) => a[k]).map((k) => a[k] + " " + k).join(", ");
  return h("li", { class: "wip-area" }, h("code", null, a.area), " ", h("span", { class: "muted" }, kinds),
    piled ? h("span", { class: "chip neutral" }, h("span", null, "looks generated")) : null);
}

function render(pid, r, box) {
  if (!r.applies) return null;
  const piled = new Set((r.piles || []).map((p) => p.area));
  const areas = r.areas || [];
  return h("section", { class: "card wip-card", "aria-labelledby": "wip-h", "data-control": "wip_card" },
    h("header", { class: "card-head" }, h("span", { class: "card-ic" }, icon("edit")),
      h("h3", { class: "card-t", id: "wip-h" }, "Work in progress"),
      r.nudge ? h("span", { class: "chip warning" }, h("span", null, "commit what is ready")) : null,
      h("span", { class: "card-tools" }, button("Refresh", { icon: "refresh", kind: "tiny quiet", key: "wip-refresh",
        aria: "Read the working copy again", "data-control": "wip_card", onclick: () => act(box, () => draw(box, pid, true)) }))),
    h("p", { class: "wip-said" }, datum(r.said)),
    r.measured && areas.length ? h("ul", { class: "plain wip-areas small" }, areas.slice(0, SHOWN).map((a) => areaRow(a, piled.has(a.area)))) : null,
    r.measured && areas.length > SHOWN ? h("p", { class: "small muted" }, "and " + (areas.length - SHOWN) + " more area(s)") : null,
    h("p", { class: "small muted" }, r.measured
      ? "Read from " + r.path + " just now: file names and times only, never their contents; nothing is written there."
      : "Rihmasto reads a project's work in progress from its working copy on this machine."),
    r.measured ? null : reachButton(pid, [{ id: pid, title: pid }], "Test connection"));
}

async function draw(box, pid, fresh) {
  let r;
  try { r = await api("GET", "/api/projects/" + enc(pid) + "/wip" + (fresh ? "?fresh=1" : "")); } catch (e) {
    box.replaceChildren(h("p", { class: "small muted" }, "Work in progress could not be read: " + e.message));
    return;
  }
  const el = render(pid, r, box);
  box.replaceChildren(...(el ? [el] : []));
}

/* The card for a project's Overview: drawn when its reading arrives; nothing for a project with no repository. */
export function wipCard(p) {
  const box = h("div", { class: "wip-box", "data-panel": "wip" });
  draw(box, p.meta.id, false);
  return box;
}
