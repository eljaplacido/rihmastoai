/* Capsules: a project's views grouped by purpose (D-0024, FR-UXO1). Five capsules (Now, Build, Run, Govern,
   Agents) are the top row of tabs; each opens its own short row of views. A view takes part by REGISTERING:

     registerView({ id: "sessions", capsule: "agents", label: "Sessions", icon: "bot",
                    personas: ["developer", "it"], order: 20, render: (p, inbox, ctx) => node,
                    when: (p, ctx) => true, wait: (p, inbox) => 0 });

   `id` is the view's address (#/p/<pid>/<id>; add it to core.js PAGE_ROUTES and cockpit/ui_map.json), `render`
   draws it (or `module` names a module under /static/ whose `render` export does, imported when first opened),
   `when` says whether it applies to this project, `wait` how many things in it wait on the person (the capsule's
   badge). `personas` brings the view forward for them (it comes first in its capsule); every view stays
   reachable for every persona. A view that is not registered simply does not appear.

   The person may hide views they never use and pin a favourite to the top row (Customize, per person); a view
   that holds a decision waiting on them is never hidden. Addresses stay #/p/<pid>/<view>, so every old link
   still opens the right capsule and view. */

import { S, h, icon, local, VIEWS, PAGE_ROUTES, PROJECT_VIEWS, FACTORY_VIEWS, enc, plural } from "./core.js";
import { word, viewWord } from "./words.js";
import { tabChoices, saveTabChoices } from "./layoutstore.js";

export const CAPSULES = [
  { id: "now", label: "Now", icon: "bell" },
  { id: "build", label: "Build", icon: "hammer" },
  { id: "run", label: "Run", icon: "server" },
  { id: "govern", label: "Govern", icon: "shield" },
  { id: "agents", label: "Agents", icon: "bot" },
];
// The capsule each persona opens a project in.
export const PERSONA_CAPSULE = {
  business_owner: "now", product_owner: "now", stakeholder: "now", concept_evaluator: "now", end_user: "now",
  developer: "build", it: "run", operations: "run", compliance: "govern",
};

const REG = new Map();

/* Register a view into a capsule. Calling it again for the same id replaces the entry (a module may refine the
   built-in one). The view's label and icon are added to VIEWS and its address to the routes when missing. */
export function registerView(v) {
  if (!v || !v.id || !CAPSULES.some((c) => c.id === v.capsule)) throw new Error("registerView: an id and a known capsule are needed");
  const prev = REG.get(v.id) || {};
  const entry = Object.assign({ order: 50, personas: [] }, prev, v);
  REG.set(v.id, entry);
  if (!VIEWS[v.id]) VIEWS[v.id] = { label: entry.label || v.id, icon: entry.icon || "layers" };
  if (!PAGE_ROUTES[v.id]) PAGE_ROUTES[v.id] = "#/p/{pid}/" + v.id;
  if (!PROJECT_VIEWS.includes(v.id)) PROJECT_VIEWS.push(v.id);
  return entry;
}
export function registered(id) { return REG.get(id) || null; }
export function capsuleOf(id) { const r = REG.get(id); return r ? r.capsule : "now"; }
// A view's label in the reader's words (words.js): "Decision record" for a business owner, "Ledger" for a developer.
export function labelOf(id) { const r = REG.get(id); return viewWord(id, (r && r.label) || (VIEWS[id] || {}).label || id); }

const adoptedOrAttached = (p) => ["adopted", "attached"].includes(p.meta.source_kind);
// The views Rihmasto has today. Other streams register theirs (Sessions, Context, Knowledge graph) the same way.
[
  ["overview", "now", 10, ["business_owner", "product_owner", "stakeholder"]],
  ["inbox", "now", 20],
  ["review", "now", 30],
  ["questions", "now", 40, ["concept_evaluator", "business_owner"]],
  ["plan", "now", 15, [], (p, ctx) => !!(ctx && (ctx.planOpen || ctx.current === "plan"))],
  ["spec", "build", 10],
  ["graph", "build", 15],          // how the spec, contract, tests, decisions and agents connect (graph.js, FR-GRV1)
  ["tasks", "build", 20, ["developer"]],
  ["changes", "build", 30],
  ["align", "build", 40, [], adoptedOrAttached],
  ["console", "build", 50],
  ["assumptions", "build", 60],
  ["assessment", "build", 70, [], (p) => p.meta.source_kind === "adopted"],
  ["cell", "build", 80],
  ["destinations", "run", 5],      // where the capability goes, and publishing (destinations.js, FR-DST1)
  ["releases", "run", 10, ["it"]],
  ["outputs", "run", 20],
  ["checks", "run", 30, ["operations"]],
  ["automations", "run", 40],
  ["try", "run", 50, ["end_user"]],
  ["evidence", "govern", 10, ["compliance"]],
  ["track", "govern", 20],
  ["insights", "govern", 30],
  ["ledger", "govern", 50],
  ["agents", "agents", 10],
  ["context", "agents", 20],       // what each agent is given, and the context's health (context.js, FR-CTX1)
  ["aitools", "agents", 30, [], adoptedOrAttached],
].forEach(([id, capsule, order, personas, when]) => registerView({ id, capsule, order, personas: personas || [], when: when || null }));
REG.get("agents").label = "Channel";
REG.get("checks").label = "Health";
REG.get("aitools").label = "AI tools";
REG.get("aitools").icon = "sparkles";

// -- the person's choices: hidden views and pinned ones, per person ----------------------------------------

// Kept on the server per person with the view layouts (layoutstore.js), so they follow the person to any computer.
export function tabPrefs() { return tabChoices(); }
export function setTabPrefs(prefs) { saveTabChoices({ hidden: prefs.hidden || [], pinned: prefs.pinned || [] }); }
export function toggleTab(kind, id) {
  const p = tabPrefs();
  const list = p[kind];
  const i = list.indexOf(id);
  if (i >= 0) list.splice(i, 1); else list.push(id);
  setTabPrefs(p);
  return p;
}
export function resetTabs() { setTabPrefs({ hidden: [], pinned: [] }); }

// -- which views a project has, by capsule -----------------------------------------------------------------

/* The registered views that apply to this project and whose module is on (``viewOn``), in their capsule's order,
   the persona's own views first. The factory's own canon has only its three views. */
export function availableViews(p, ctx, viewOn) {
  if (p.meta.factory) return FACTORY_VIEWS.slice();
  return [...REG.values()].filter((r) => (!r.when || r.when(p, ctx)) && viewOn(r.id, p.meta.id) && (r.render || r.module || ctx.builtIn(r.id)))
    .map((r) => r.id);
}
export function inCapsule(cap, views) {
  const forMe = (id) => ((REG.get(id) || {}).personas || []).includes(S.persona);
  return views.filter((v) => capsuleOf(v) === cap)
    .sort((a, b) => Number(forMe(b)) - Number(forMe(a)) || (REG.get(a) || {}).order - (REG.get(b) || {}).order);
}
function lastKey(pid, cap) { return "gf.cap." + pid + "." + cap; }
export function rememberView(pid, view) { local.set(lastKey(pid, capsuleOf(view)), view); }
/* The view a capsule opens on: the one last opened there, else its first view the person has not hidden. */
export function capsuleHome(pid, cap, views) {
  const list = inCapsule(cap, views);
  const last = local.get(lastKey(pid, cap));
  if (last && list.includes(last)) return last;
  const hidden = tabPrefs().hidden;
  return list.find((v) => !hidden.includes(v)) || list[0] || null;
}
export function defaultView(pid, views) {
  const cap = PERSONA_CAPSULE[S.persona] || "now";
  return capsuleHome(pid, cap, views) || capsuleHome(pid, "now", views) || views[0];
}

// What waits on the person in each capsule: the Inbox's cards (Now) and what a registered view counts.
const CARD_CAPSULE = { change: "build", escalation: "build", deploy_gate: "run", incident: "run", road: "run", trust: "run",
  runner: "run", update: "run", holdout_ruling: "govern" };
export function capsuleWaits(p, inbox, views) {
  const out = { now: 0, build: 0, run: 0, govern: 0, agents: 0 };
  const cards = (inbox && inbox.cards) || [];
  out.now = cards.length;
  cards.forEach((c) => { const cap = CARD_CAPSULE[c.kind]; if (cap) out[cap] += 1; });
  views.forEach((v) => { const r = REG.get(v); if (r && r.wait) { try { out[r.capsule] += Number(r.wait(p, inbox)) || 0; } catch (e) { /* a count it cannot read */ } } });
  return out;
}

// -- drawing ---------------------------------------------------------------------------------------------

/* The capsule row and the current capsule's views. While the person customizes (S.customizingView), each view
   carries Hide and Pin. A hidden view that holds a decision waiting on them stays, marked. */
export function capsuleNav(pid, views, current, waits, opts) {
  const o = opts || {};
  const prefs = tabPrefs();
  const curCap = capsuleOf(current);
  const href = (v) => "#/p/" + enc(pid) + "/" + v;
  const waitsIn = (v) => (v === "inbox" ? (waits.now || 0) : 0);
  const top = CAPSULES.filter((c) => inCapsule(c.id, views).length).map((c) => {
    const on = c.id === curCap;
    const n = waits[c.id] || 0;
    const tip = word("capsule." + c.id) + (n ? " · " + plural(n, "thing") + " waiting on you" : "");
    return h("li", null, h("a", { class: "cap-t" + (on ? " on" : ""), href: href(capsuleHome(pid, c.id, views)), "data-capsule": c.id,
      "aria-current": on ? "true" : null, tip, "data-control": "capsules" },
    icon(c.icon), h("span", { class: "lbl" }, c.label),
    n ? h("span", { class: "count", "aria-label": plural(n, "thing") + " waiting on you" }, String(n)) : null));
  });
  const pins = prefs.pinned.filter((v) => views.includes(v) && capsuleOf(v) !== curCap).map((v) => h("li", null,
    h("a", { class: "cap-t pin", href: href(v), "data-pin": v, tip: "Pinned: " + labelOf(v) }, icon((VIEWS[v] || {}).icon || "layers"),
      h("span", { class: "lbl" }, labelOf(v)))));
  const sub = inCapsule(curCap, views).filter((v) => o.customizing || v === current || !prefs.hidden.includes(v) || waitsIn(v));
  const hiddenCount = inCapsule(curCap, views).filter((v) => prefs.hidden.includes(v) && v !== current && !waitsIn(v)).length;
  const capLabel = (CAPSULES.find((c) => c.id === curCap) || {}).label || "";
  return h("nav", { class: "caps" + (o.customizing ? " cz-tabs" : ""), "aria-label": "Project areas" },
    h("ul", { class: "caps-top", role: "list" }, top, pins),
    h("ul", { class: "tabs caps-sub", role: "list", "aria-label": capLabel + " views" }, sub.map((v) => {
      const on = v === current;
      const hidden = prefs.hidden.includes(v);
      const pinned = prefs.pinned.includes(v);
      return h("li", { class: hidden ? "is-hidden" : null },
        h("a", { href: href(v), "aria-current": on ? "page" : null, class: on ? "on" : null, "data-view": v },
          icon((VIEWS[v] || {}).icon || "layers"), h("span", null, labelOf(v)),
          waitsIn(v) ? h("span", { class: "count", "aria-label": plural(waitsIn(v), "card") + " waiting on you" }, String(waitsIn(v))) : null,
          v === "plan" && o.planOpen ? h("span", { class: "tab-wait", tip: "Waits on approval" }, icon("user")) : null),
        o.customizing ? h("span", { class: "tab-cz" },
          h("button", { type: "button", class: "icon-btn tiny", "data-control": "customize_tabs", "data-key": "tabhide:" + v,
            "aria-pressed": String(hidden), "aria-label": (hidden ? "Show " : "Hide ") + labelOf(v), tip: hidden ? "Show this tab" : "Hide this tab",
            disabled: (waitsIn(v) && !hidden) || null, onclick: () => { toggleTab("hidden", v); if (o.onChange) o.onChange(); } }, icon(hidden ? "eye" : "x")),
          h("button", { type: "button", class: "icon-btn tiny", "data-key": "tabpin:" + v, "aria-pressed": String(pinned),
            "aria-label": (pinned ? "Unpin " : "Pin ") + labelOf(v) + " to the top row", tip: pinned ? "Unpin from the top row" : "Pin to the top row",
            onclick: () => { toggleTab("pinned", v); if (o.onChange) o.onChange(); } }, icon(pinned ? "check" : "flag"))) : null);
    }),
    hiddenCount && !o.customizing ? h("li", { class: "tabs-hidden muted small" }, plural(hiddenCount, "tab") + " hidden") : null));
}
