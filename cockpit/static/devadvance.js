/* The developer briefing when a developer presses Advance (FR-DEV2). The owner (2026-11-25): "when I click in that
   [developer] role that I want to advance the project, I want insights about the latest sessions ... and it would tell
   me, this would be the next step in development". Advance still starts the run; for a person acting as a developer
   it then opens the same briefing the Board shows (kernel/devbrief.py): the latest sessions since their last look,
   what changed, the next step with why, and only the decisions that block it, with Got it and a link to the Board. */

import { h, fill, api, enc, mayAct, openModal, closeModal, say } from "./core.js";
import { pick } from "./words.js";
import { briefingCard } from "./devboard.js";

export const asDeveloper = () => mayAct(["developer"]);

async function load(slot, pid, person) {
  const b = await api("GET", "/api/projects/" + enc(pid) + "/dev/briefing" + (person ? "?person=" + enc(person) : ""));
  if (!slot.isConnected) return;
  const again = () => load(slot, pid, person).catch((e) => say(e.message, "critical"));
  fill(slot, briefingCard(pid, b, again),
    h("p", { class: "small" }, h("a", { href: "#/p/" + enc(pid) + "/board", "data-key": "dev:adv-board" },
      pick("Open the building board", "Open the development board"))));
}

// After Advance started: the briefing in a dialog, for a developer only; nothing for anyone else.
export function briefAfterAdvance(pid, person) {
  if (!asDeveloper() || !pid || pid.startsWith("_")) return false;
  const slot = h("div", { class: "dv-adv", "data-id": "dev_advance_briefing" }, h("p", { class: "muted" }, "Reading the records…"));
  slot.addEventListener("click", (e) => { if (e.target.closest("a[href^='#']")) closeModal(); });   // a link goes there
  openModal(pick("While it moves on: your briefing", "Advance started: your developer briefing"), slot, { icon: "bell", wide: true });
  load(slot, pid, person).catch((e) => fill(slot, h("p", { class: "note small" }, "The briefing could not be read: " + e.message
    + ". It is on the project's Board too.")));
  return true;
}
