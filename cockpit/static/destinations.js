/* Destinations (kernel/destinations.py, FR-DST1): every place a project's capability goes, as a map grouped by
   kind (deployed, data, channels, published). Each card says its environment, its state, its last delivery and
   its health, and offers what a person can do there: deliver to test, promote to production (IT's deploy gate
   decides), publish, open, investigate, check now. Every write is signed with the person chip. The overview's
   "Where this goes" is whereCard. A state always carries an icon and a word, never colour alone. */

import { h, fill, icon, chip, api, act, say, signed, needPerson, enc, button, empty, ago, link, nav } from "./core.js";

// The interface overhaul's capsules: this view belongs in "Run". A capsule registry, when one is loaded, takes it
// from nav.capsuleViews; until then it is a project view (core.js VIEWS, project.js VIEW_FN).
export const CAPSULE_ENTRY = { capsule: "run", view: "destinations", label: "Destinations", icon: "globe", order: 20 };
(nav.capsuleViews = nav.capsuleViews || []).push(CAPSULE_ENTRY);

const STATE = {
  planned: ["neutral", "dashed", "Planned"], configured: ["info", "settings", "Configured"],
  delivered: ["accent", "send", "Delivered"], healthy: ["good", "check-circle", "Healthy"],
  failing: ["critical", "x-circle", "Failing"], "not measured": ["nm", "dashed", "Not measured"],
};
const GROUP_ICON = { deployed: "server", data: "plug", channels: "message-square", published: "package" };
const GROUP_WHAT = {
  deployed: "Where it runs: each environment of its plan, on its paved road.",
  data: "The data systems and integrations it reads or writes, and the sources that feed it.",
  channels: "Where it is used: website chats, Teams, Slack and email through the relay, its MCP and API faces.",
  published: "Registries it is published to, and the outputs built for its audiences.",
};
// The control each action is (cockpit/ui_map.json), written out so the map's check finds every one.
const ACTION_CONTROL = {
  deliver: { "data-control": "destinations_deliver" }, promote: { "data-control": "destinations_promote" },
  publish: { "data-control": "destinations_publish" }, investigate: { "data-control": "destinations_investigate" },
  check: { "data-control": "destinations_check" }, open: { "data-control": null },
};
const ACTION_ICON = { deliver: "play", promote: "arrow-right", publish: "upload", open: "external", investigate: "search",
  check: "refresh" };
const base = (pid) => "/api/projects/" + enc(pid);

export function stateChip(state) {
  const [tone, ic, word] = STATE[state] || STATE["not measured"];
  return chip(tone, ic, word, { "data-state": state });
}

function tierChip(d) {
  if (!d.environment && !d.tier) return null;
  const words = d.environment && d.tier && d.environment !== d.tier ? d.environment + " · " + d.tier : (d.environment || d.tier);
  return chip(d.tier === "production" ? "warning" : "neutral", d.tier === "production" ? "flag" : "flask", words);
}

function resultSay(out, what) {
  if (out.state === "published") return say(what + " published as " + out.image + (out.digest ? " (" + out.digest.slice(0, 19) + "…)" : "") + ".", "good");
  if (out.state === "written") return say("The MCP registry entry is written to " + out.file + ". Submit it yourself: Rihmasto never submits it.", "good");
  if (out.state === "waiting") return say("It waits on IT's deploy gate " + out.waiting_on + " in the Inbox: production is IT's decision.", "info");
  if (out.state === "refused") return say("Not published. " + (out.missing || [out.why]).join(" "), "warning");
  return say("Publishing failed: " + (out.why || out.state), "critical");
}

function actionControl(pid, d, a, again) {
  const key = "dst-act:" + a.id + ":" + d.id;
  const control = (ACTION_CONTROL[a.id] || {})["data-control"] || null;
  if (a.href) {
    const outside = /^https?:/.test(a.href);
    return h("a", { href: a.href, class: "btn small" + (a.id === "investigate" ? " warn" : ""), "data-key": key,
      "data-control": control, target: outside ? "_blank" : null, rel: outside ? "noopener noreferrer" : null,
      "aria-label": a.label + ": " + d.label }, icon(ACTION_ICON[a.id] || "arrow-right"), h("span", { class: "lbl" }, a.label));
  }
  const b = button(a.label, { icon: ACTION_ICON[a.id] || "play", kind: "small" + (a.id === "deliver" || a.id === "publish" ? " primary" : ""),
    key, "data-control": control, disabled: !!a.disabled, aria: a.label + ": " + d.label, tip: a.disabled || null });
  b.addEventListener("click", (e) => act(e.currentTarget.parentElement, async () => {
    if (!needPerson()) return;
    if (a.id === "deliver" || a.id === "promote") {
      const out = await api("POST", base(pid) + "/destinations/deliver", Object.assign({ to: a.to }, signed()));
      say((a.id === "promote" ? "Delivery toward production started" : "Delivery to test started") + " (job " + out.job.id + ")."
        + (a.id === "promote" ? " It stops at IT's deploy gate." : ""), "good");
    } else if (a.id === "publish") {
      resultSay(await api("POST", base(pid) + "/publish", Object.assign({ registry: a.registry }, signed())), d.label);
    } else if (a.id === "check") {
      const out = await api("POST", base(pid) + "/destinations/check", signed());
      say(out.said, out.tone);
    }
    await again();
  }));
  return b;
}

function destCard(pid, d, again) {
  const last = d.last_delivery;
  const health = d.health;
  const lines = [];
  if (last) lines.push(h("p", { class: "dst-line" }, icon("clock"), h("span", null, "Last: " + (last.what || ("release " + last.release))
    + (last.at ? " · " + ago(last.at) : ""))));
  if (health && health.why) lines.push(h("p", { class: "dst-line" + (d.state === "failing" ? " bad" : "") }, icon("pulse"),
    h("span", null, (health.by ? health.by + ": " : "") + health.why + (health.at ? " · " + ago(health.at) : ""))));
  if (d.url) lines.push(h("p", { class: "dst-line mono small" }, icon("link"), h("span", { class: "dst-url" }, d.url)));
  if (d.note) lines.push(h("p", { class: "dst-line muted small" }, icon("info"), h("span", null, d.note)));
  const missing = (d.missing || []).length ? h("ul", { class: "dst-missing", "aria-label": "What is missing" },
    d.missing.map((m) => h("li", null, m))) : null;
  const acts = (d.actions || []).filter((a) => a.id !== "check");
  return h("li", { class: "dst-card", "data-id": d.id, "data-state": d.state, "data-key": "dst:" + d.id },
    h("div", { class: "dst-top" }, h("b", { class: "dst-label" }, d.label), stateChip(d.state)),
    h("div", { class: "dst-chips" }, tierChip(d), d.details && d.details.road_kind ? chip("neutral", "server", d.details.road_kind) : null,
      d.details && d.details.consumers && d.details.consumers.length ? chip("neutral", "users", "Used by " + d.details.consumers.join(", ")) : null),
    lines, missing,
    acts.length ? h("div", { class: "dst-acts" }, acts.map((a) => actionControl(pid, d, a, again))) : null);
}

function groupSection(pid, view, g, again) {
  const rows = view.groups[g] || [];
  return h("section", { class: "dst-group", "data-group": g, "aria-labelledby": "dst-h-" + g },
    h("h3", { class: "dst-gh", id: "dst-h-" + g }, icon(GROUP_ICON[g]), h("span", null, view.labels[g]),
      h("span", { class: "count" + (rows.length ? "" : " zero") }, String(rows.length))),
    h("p", { class: "muted small dst-what" }, GROUP_WHAT[g]),
    rows.length ? h("ul", { class: "dst-grid" }, rows.map((d) => destCard(pid, d, again)))
      : h("p", { class: "muted small" }, "Nothing here yet."));
}

function counts(summary) {
  return h("div", { class: "dst-counts", "aria-label": "Destinations by state" }, Object.keys(STATE)
    .filter((s) => summary.counts[s]).map((s) => { const [tone, ic, word] = STATE[s]; return chip(tone, ic, summary.counts[s] + " " + word.toLowerCase()); }));
}

function head(view, pid, again) {
  const check = button("Check now", { icon: "refresh", kind: "small", key: "dst-check", "data-control": "destinations_check",
    aria: "Check every destination now" });
  check.addEventListener("click", () => act(check.parentElement, async () => {
    if (!needPerson()) return;
    const out = await api("POST", base(pid) + "/destinations/check", signed());
    say(out.said, out.tone);
    await again();
  }));
  return h("div", { class: "q dst-head" },
    h("h2", { id: "view-title", tabindex: "-1" }, "Destinations"),
    h("p", null, "Every place this goes: where it runs, the data it reaches, the channels it is used through, and where it is published."),
    view ? h("p", { class: "dst-sum", "data-key": "dst-summary" }, view.summary.line) : null,
    view ? h("div", { class: "dst-bar" }, counts(view.summary), h("span", { class: "dst-bar-r" },
      view.checked ? h("span", { class: "muted small" }, "Checked " + ago(view.checked)) : h("span", { class: "muted small" }, "Not checked yet"),
      check)) : null);
}

async function draw(box, pid) {
  const view = await api("GET", base(pid) + "/destinations");
  if (!box.isConnected && box.dataset.drawn) return;
  const again = () => draw(box, pid).catch((e) => say(e.message, "critical"));
  box.dataset.drawn = "1";
  fill(box, head(view, pid, again), h("div", { class: "dst-map", "data-control": "destinations_map" },
    ["deployed", "data", "channels", "published"].map((g) => groupSection(pid, view, g, again))));
}

export function viewDestinations(p) {
  const pid = p.meta.id;
  const box = h("div", { class: "dst-view" }, head(null, pid, () => {}), h("p", { class: "muted" }, "Reading where this goes…"));
  draw(box, pid).catch((e) => { if (box.isConnected) fill(box, head(null, pid, () => {}), empty("alert", e.message)); });
  return box;
}

// "Where this goes" on the overview: the summary line and where it runs, with the way to the map.
export function whereCard(pid) {
  const body = h("div", { class: "dst-where-b" }, h("p", { class: "muted small" }, "Reading where this goes…"));
  const box = h("section", { class: "section panel dst-where", "data-control": "destinations_where", "aria-labelledby": "dst-where-h" },
    h("div", { class: "next-top" }, h("h3", { id: "dst-where-h", class: "label-h" }, icon("globe"), " Where this goes"),
      h("a", { href: link(pid, "destinations"), class: "small", "data-key": "dst-where-open" }, "Open Destinations")), body);
  api("GET", base(pid) + "/destinations/where").then((w) => {
    fill(body, h("p", { class: "small" }, w.summary.line),
      w.deployed.length ? h("ul", { class: "plain dst-where-l" }, w.deployed.map((d) => h("li", null, stateChip(d.state), " ",
        h("span", { class: "small" }, d.label + (d.last_delivery ? " · " + d.last_delivery.what : ""))))) : null);
  }).catch(() => fill(body, h("p", { class: "muted small" }, "Where this goes could not be read.")));
  return box;
}
