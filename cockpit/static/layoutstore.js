/* A person's view layouts, kept on the server (FR-UXO1). Customize on any view but Home arranges its sections
   (order, hidden, compact or wide) and, in a project, hides or pins capsule tabs. These follow the person to any
   computer and browser: they live in the factory home's _cockpit/view-layouts/ (GET and PUT /api/view-layouts),
   outside every ledger, beside Home's own layouts. This browser keeps only a copy to draw from while offline.

   The first load for a person moves what an earlier version kept in this browser ("gf.vlayout.<person>.<view>"
   and "gf.tabs.<person>") to the server in one save, then forgets the browser's copy. */

import { S, api, enc, local, say, AuthError } from "./core.js";

const VL = { person: null, views: {}, tabs: { hidden: [], pinned: [] }, loading: null };
let warned = false;

function who() { return (S.person || "").trim(); }
function cacheKey(person) { return "gf.vl.cache." + (person || "-"); }
function blank(lay) { return !lay || (!(lay.order || []).length && !(lay.hidden || []).length && !Object.keys(lay.size || {}).length); }

// What an earlier version of the page kept in this browser for the person, if anything.
function fromBrowser(person) {
  const views = {};
  let tabs = null;
  const keys = [];
  const prefix = "gf.vlayout." + (person || "-") + ".";
  try {
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const k = window.localStorage.key(i);
      if (k && k.startsWith(prefix)) keys.push(k);
    }
  } catch (e) { return null; }
  keys.forEach((k) => {
    try { const v = JSON.parse(local.get(k) || "null"); if (!blank(v)) views[k.slice(prefix.length)] = v; } catch (e) { /* unreadable: left out */ }
  });
  try {
    const t = JSON.parse(local.get("gf.tabs." + (person || "-")) || "null");
    if (t && ((t.hidden || []).length || (t.pinned || []).length)) tabs = { hidden: t.hidden || [], pinned: t.pinned || [] };
  } catch (e) { tabs = null; }
  if (!Object.keys(views).length && !tabs) return keys.length ? { views, tabs, keys } : null;
  return { views, tabs, keys };
}
function forgetBrowser(person, keys) {
  keys.forEach((k) => local.del(k));
  local.del("gf.tabs." + (person || "-"));
}

function take(person, out) {
  VL.person = person;
  VL.views = (out && out.views) || {};
  VL.tabs = { hidden: ((out && out.tabs) || {}).hidden || [], pinned: ((out && out.tabs) || {}).pinned || [] };
  local.set(cacheKey(person), JSON.stringify({ views: VL.views, tabs: VL.tabs }));
}

/* Read the person's layouts once per person (again after a change of name). Never throws: offline, the copy
   this browser keeps is drawn from. */
export function ensureViewLayouts() {
  const person = who();
  if (VL.person === person && !VL.loading) return Promise.resolve();
  if (VL.loading && VL.loading.person === person) return VL.loading.p;
  const p = (async () => {
    try {
      const read = () => api("GET", "/api/view-layouts?person=" + enc(person));
      const out = await read().catch((e) => {
        if (e instanceof AuthError) throw e;
        return new Promise((ok) => { setTimeout(ok, 600); }).then(read);
      });
      const old = person ? fromBrowser(person) : null;
      if (person && !out.saved && old && (Object.keys(old.views).length || old.tabs)) {
        const moved = await api("PUT", "/api/view-layouts", { person, persona: S.persona, views: old.views, tabs: old.tabs || undefined });
        take(person, moved);
        forgetBrowser(person, old.keys);
        say("Your view layouts from this browser now follow you to any computer.", "good");
      } else {
        take(person, out);
        if (old && out.saved) forgetBrowser(person, old.keys);
      }
    } catch (e) {
      if (e instanceof AuthError) { VL.person = null; return; }
      let cached = null;
      try { cached = JSON.parse(local.get(cacheKey(person)) || "null"); } catch (x) { cached = null; }
      VL.person = person;
      VL.views = (cached && cached.views) || {};
      VL.tabs = (cached && cached.tabs) || { hidden: [], pinned: [] };
    } finally {
      VL.loading = null;
    }
  })();
  VL.loading = { person, p };
  return p;
}

export function viewLayout(key) { return VL.views[key] || null; }
export function tabChoices() { return { hidden: VL.tabs.hidden.slice(), pinned: VL.tabs.pinned.slice() }; }

/* Save on the server: shown at once, kept in the background. Without a name the change shows here only. */
async function put(body) {
  const person = who();
  local.set(cacheKey(person), JSON.stringify({ views: VL.views, tabs: VL.tabs }));
  if (!person) {
    if (!warned) { warned = true; say("Shown here only: say who you are (the person chip) to keep your layout on every computer.", "warning"); }
    return;
  }
  try {
    // What is on screen stays as it is: two quick changes may be answered out of order, and the server merges each.
    await api("PUT", "/api/view-layouts", Object.assign({ person, persona: S.persona }, body));
  } catch (e) {
    if (!(e instanceof AuthError)) say("The layout is shown here but was not saved: " + e.message, "warning");
  }
}
/* opts.only_here: shown on this page and not yet saved (Ask Rihma's preview, saved when the person keeps it). */
export function saveViewLayoutFor(key, lay, opts) {
  if (blank(lay)) delete VL.views[key]; else VL.views[key] = lay;
  if (opts && opts.only_here) return Promise.resolve();
  return put({ views: { [key]: blank(lay) ? null : lay } });
}
export function saveTabChoices(tabs) {
  VL.tabs = { hidden: (tabs.hidden || []).slice(), pinned: (tabs.pinned || []).slice() };
  return put({ tabs: VL.tabs });
}
