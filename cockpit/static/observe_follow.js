/* Following (FR-SHR1): while one of your observer links is active, the page tells the cockpit which view you are on,
   so a guest can follow it, and shows who is watching now in a chip in the top bar that opens Share. Paused, it says
   only that you paused: guests keep the shared views, not where you are. Kept in memory on the server, recorded
   nowhere. Nothing is posted while you share nothing.

   A pause is the server's (FR-SHR2): the heartbeat says only where you are, and the server answers whether you are
   paused, which this page mirrors. Only an explicit pause or resume (Share's button, or Ask Rihma's Confirm) changes
   it, so a pause from the chat is never undone by the next heartbeat. The page's own last word is sent as a hint the
   server takes only when it remembers nothing (after a restart). */

import { S, h, icon, api, local, signed } from "./core.js";

const F = { active: 0, checked: 0, timer: null, watching: [], last: "" };
const CHECK_EVERY = 30000;
const BEAT_EVERY = 8000;     // who is watching shows within seconds of a guest opening the link (FR-SHR2)

export function followPaused() { return local.get("gf.share.paused") === "1"; }
export function setFollowPaused(on) { local.set("gf.share.paused", on ? "1" : "0"); F.last = ""; beat(true, on); }

function where() {
  const r = S.route || {};
  return { project: r.pid || "", view: r.name === "project" ? (r.view || "overview") : (r.name || "home") };
}

function chip() {
  let el = document.getElementById("obs-chip");
  if (!F.active) { if (el) el.remove(); return; }
  const said = (F.watching.length ? F.watching.join(", ") + " watching" : "Sharing: nobody watching now")
    + (followPaused() ? " (paused)" : "");
  if (!el) {
    el = h("a", { id: "obs-chip", class: "obs-chip", href: "#/share", "data-control": "observe_watching", "aria-live": "polite" });
    const bar = document.querySelector("#topbar .tb-right");
    const person = bar && bar.querySelector("#person-chip");
    if (bar) bar.insertBefore(el, person || null); else document.body.append(el);   // in the top bar: over nothing
  }
  el.setAttribute("aria-label", said);
  el.title = said;
  el.dataset.watching = String(F.watching.length);
  el.replaceChildren(icon("eye"), h("span", { class: "obs-n", "aria-hidden": "true" }, String(F.watching.length)),
    h("span", { class: "lbl" }, said));
}

async function check() {
  F.checked = Date.now();
  const me = (S.person || "").trim();
  if (!me || !S.token) { F.active = 0; chip(); return; }
  try {
    const d = await api("GET", "/api/observe");
    const mine = (d.links || []).filter((l) => l.state === "active" && l.created_by === me);
    F.active = mine.length;
    F.watching = Array.from(new Set(mine.flatMap((l) => l.watching || [])));
  } catch (e) { F.active = 0; }
  chip();
}

// paused: true or false when the person paused or resumed; undefined for a heartbeat
async function beat(force, paused) {
  if (Date.now() - F.checked > CHECK_EVERY) await check();
  if (!F.active || !(S.person || "").trim()) return;
  const w = where();
  const key = JSON.stringify([w, paused]);
  if (!force && key === F.last) return;
  F.last = key;
  const said = typeof paused === "boolean" ? { paused } : { was_paused: followPaused() };
  try {
    const out = await api("POST", "/api/observe/presence", Object.assign({}, w, said, signed()));
    if (out.presence && typeof out.presence.paused === "boolean") local.set("gf.share.paused", out.presence.paused ? "1" : "0");
    F.watching = out.watching || [];
    F.active = out.sharing || 0;
    chip();
  } catch (e) { /* following is a courtesy: a failure never stops the page */ }
}

// The route changed: say where you are now (only while sharing).
export function followRoute() {
  beat(false);
  if (!F.timer) F.timer = setInterval(() => { F.last = ""; beat(true); }, BEAT_EVERY);
}

// A link was just made, or Ask Rihma's Confirm changed the pause: check at once.
export function followNow() { F.checked = 0; F.last = ""; beat(true); }
