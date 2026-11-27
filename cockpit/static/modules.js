/* Modules: the cockpit shows only what is enabled (kernel/modules.py, FR-MOD1, FR-MOD4).
   A person may use a small part of Rihmasto or the whole of it. The factory's set of modules (and a
   project's own, where one overrides it) decides which pages, project views, widgets, controls and
   assistant suggestions the page shows. Nothing is deleted when a module is off: its records stay, its
   writes are refused by the kernel, and Settings, Modules says what it would add and turns it on again.
   A new factory home offers the choice once, on the first visit (firstRun). */

import {
  S, $, $$, h, fill, icon, chip, api, say, button, card, openModal, closeModal, nav, personaLabel, store, AuthError,
  pageHead, FACTORY_PID, PAGES, mayAct,
} from "./core.js";
import { technical, pick } from "./words.js";
import { whoWorksHere } from "./people.js";

// -- reading the set -----------------------------------------------------------------------------------

/* GET /api/modules: the catalogue, the presets, the factory's set and the projects' own sets. Until it is
   read (or when it cannot be), everything is shown, as for a factory where nobody chose. */
export async function loadModules() {
  try {
    S.modules = await api("GET", "/api/modules");
  } catch (e) {
    if (e instanceof AuthError) throw e;
    S.modules = null;
  }
  return S.modules;
}

function setOf(pid) {
  const m = S.modules;
  if (!m) return null;
  const own = pid && pid !== FACTORY_PID && m.projects ? m.projects[pid] : null;
  return (own || m.factory).modules;
}
function ownersOf(kind, id) {
  const m = S.modules;
  if (!m || (m.core[kind] || []).includes(id)) return [];
  return m.catalogue.filter((x) => (x[kind] || []).includes(id)).map((x) => x.id);
}
function moduleOf(id) { return ((S.modules && S.modules.catalogue) || []).find((x) => x.id === id) || null; }

// Whether a page, view, widget or control is shown: core, or a module that names it is on (for ``pid``,
// the project's own set when it has one). Named so that no page's own `shown` list can hide it.
export function moduleShows(kind, id, pid) {
  const on = setOf(pid);
  if (!on) return true;
  const found = ownersOf(kind, id);
  return !found.length || found.some((x) => on.includes(x));
}
// A page the signed-in person's personas do not see in team mode (Settings, People and access; FR-PPL1) is off too.
export function pageOn(id) {
  return moduleShows("pages", id) && !(((S.meta && S.meta.people) || {}).hidden_pages || []).includes(id);
}
export function viewOn(id, pid) { return moduleShows("views", id, pid); }
export function widgetOn(type) { return moduleShows("widgets", type); }
// The key figures that belong to a module: shown only while it is on.
const TILE_MODULE = { "First-round gate pass": "build", "Criteria proven": "plan", "Capabilities in use": "capabilities" };
export function tileOn(label) {
  const on = setOf(null);
  return !on || !TILE_MODULE[label] || on.includes(TILE_MODULE[label]);
}
// The module that would show it, for a note that says so.
export function offeredBy(kind, id) { const o = ownersOf(kind, id)[0]; return o ? moduleOf(o) : null; }

// The assistant's suggested questions, each with what it is about: one about something that is off is
// not suggested (kernel/assistant.py leaves the same things out of its map).
const SUGGESTION_NEEDS = {
  "Where do I log a signal?": ["controls", "log_signal"], "Where do I validate a concept?": ["controls", "validate_concept"],
  "Where are the assumptions?": ["views", "assumptions"], "Where is the task board?": ["views", "tasks"],
  "Where are the releases?": ["views", "releases"], "Where do I export the evidence pack?": ["controls", "export_evidence"],
  "Where are the factory's metrics?": ["pages", "floor"], "Where do I make a chat for a website?": ["controls", "create_embed"],
  "Make a feedback chat for our website": ["controls", "create_embed"], "Where do I approve the plan?": ["views", "plan"],
  "Which capabilities are in use?": ["pages", "catalogue"], "What does the plan assume?": ["views", "plan"],
  "Show coverage as a table": ["widgets", "coverage"], "Make the gate trend bigger and show it as a table": ["widgets", "gate_trend"],
  "What runs in production?": ["views", "releases"], "Which models do the work well?": ["widgets", "models"],
  "How is the current run going?": ["views", "tasks"],
  // the AI architect's own (askscope.js personaAsks, FR-AOP3)
  "What do my agents cost?": ["pages", "agentops_all"], "Optimise my agents": ["pages", "agentops_all"],
  "How are my agents performing?": ["pages", "agentops_all"], "Where is the token use highest?": ["pages", "agentops_all"],
  "Is there context drift?": ["pages", "agentops_all"], "Who acted on the last run?": ["views", "who"],
};
export function suggestionOn(q) {
  const need = SUGGESTION_NEEDS[q];
  const pid = S.route && S.route.name === "project" ? S.route.pid : null;
  return !need || moduleShows(need[0], need[1], pid);
}

/* A page whose module is off, opened by its address: it says which module adds it and what that module
   would add, with a way to Settings, Modules. Reading the records is never refused; the page is only hidden. */
export function offPage(name) {
  const mod = offeredBy("pages", name);
  const label = (PAGES[name] || { label: name }).label;
  document.title = label + " · off · Rihmasto";
  fill($("#main"), pageHead(label, null, { icon: (PAGES[name] || {}).icon }),
    h("div", { class: "empty mod-off" }, h("span", { class: "empty-ic" }, icon("layers")),
      h("p", null, label + " is part of " + (mod ? mod.label : "a module") + ", which is not enabled here."),
      mod ? h("p", { class: "muted" }, "Turning it on adds " + mod.adds + ".") : null,
      h("a", { class: "btn primary", href: "#/settings", "data-key": "off:settings" }, icon("settings"), h("span", { class: "lbl" }, "Open Settings, Modules"))));
}
export function offNote(count, what) {
  return h("p", { class: "w-note page mod-note", role: "note" }, icon("layers"),
    h("span", null, count + " " + what + (count === 1 ? " is" : " are") + " hidden: " + (count === 1 ? "its module is" : "their modules are")
      + " off. ", h("a", { href: "#/settings" }, "Settings, Modules"), " turns " + (count === 1 ? "it" : "them") + " on."));
}

// -- choosing a set --------------------------------------------------------------------------------------

function closure(ids) {
  const out = new Set();
  const want = ids.slice();
  while (want.length) {
    const id = want.pop();
    const m = moduleOf(id);
    if (m && !out.has(id)) { out.add(id); want.push(...m.depends); }
  }
  return S.modules.catalogue.map((x) => x.id).filter((x) => out.has(x));
}
function presetFor(ids) {
  const want = ids.slice().sort().join(" ");
  const p = S.modules.presets.find((x) => x.modules.slice().sort().join(" ") === want);
  return p ? p.id : null;
}
function setLabel(ids) {
  const p = S.modules.presets.find((x) => x.id === presetFor(ids));
  return p ? p.label : "a set of its own";
}
function maySet() { return mayAct((S.modules && S.modules.setters) || []); }

async function save(pid, body) {
  const path = pid ? "/api/projects/" + encodeURIComponent(pid) + "/modules" : "/api/modules";
  const out = await api("PUT", path, Object.assign({ person: S.person.trim(), persona: S.persona }, body));
  S.modules = out.view;
  if (nav.refreshShell) nav.refreshShell();
  return out;
}

function changeLine(out) {
  if (!out.changed) return "Nothing changed: that set is already in use.";
  const names = (ids) => ids.map((id) => (moduleOf(id) || { label: id }).label).join(", ");
  return "Saved, signed and recorded: " + setLabel(out.modules) + "."
    + (out.turned_on.length ? " On: " + names(out.turned_on) + "." : "")
    + (out.turned_off.length ? " Off: " + names(out.turned_off) + "." : "")
    + (out.added_for_dependencies.length ? " Turned on because something needs it: " + names(out.added_for_dependencies) + "." : "");
}

/* The Settings card: the set in force for the factory or one project, the presets, every module with what
   it adds and what it needs, and Save (signed with the person and persona; a setter persona only). A module
   that is off stays listed, with what turning it on would add. */
export function modulesCard(projects) {
  const box = h("div", { class: "mod-box" });
  const m = S.modules;
  if (!m) return card({ title: "Modules", icon: "layers", id: "modules" }, h("p", { class: "muted" }, "The modules could not be read."));
  const scope = h("select", { id: "mod-scope", "data-key": "mod:scope" },
    h("option", { value: "" }, "This factory"),
    (projects || []).filter((p) => p.id !== FACTORY_PID).map((p) => h("option", { value: p.id }, "Project: " + p.title)));
  const draw = () => drawChooser(box, scope.value || null);
  scope.addEventListener("change", draw);
  draw();
  return card({ title: "Modules: the parts of Rihmasto in use", icon: "layers", id: "modules", cls: "mod-card",
    info: "Use a small part of Rihmasto or all of it, and change it later. A module that is off is not shown, and the kernel "
      + "refuses its commands and writes; its records stay. Each change is signed with your name and recorded in the ledger." },
  h("div", { class: "set-row" }, h("label", { for: "mod-scope" }, "Choose the modules for"), scope), box);
}

function drawChooser(box, pid) {
  const m = S.modules;
  const own = pid ? m.projects[pid] : null;
  const current = pid ? (own || m.factory).modules : m.factory.modules;
  let chosen = current.slice();
  let inherit = !!pid && !own;
  const status = h("p", { class: "mod-status", role: "status", "aria-live": "polite" });
  const who = !pid && m.factory.chosen ? " Chosen by " + m.factory.set_by + " (" + personaLabel(m.factory.persona) + ")"
    + (m.factory.reason ? ": " + m.factory.reason : "") + "." : !pid ? pick(" Everything is switched on (no one has chosen yet).",
    " Nobody has chosen yet, so the whole factory is on.") : "";
  const lead = h("p", { class: "mod-now" }, (pid ? (own ? "This project has its own set: " : pick("This project follows the platform-wide set: ", "This project follows the factory: "))
    : pick("In use here: ", "This factory uses: ")) + setLabel(current) + "." + who);
  const preset = h("select", { "data-key": "mod:preset", id: "mod-preset", "aria-describedby": "mod-preset-d" },
    m.presets.map((p) => h("option", { value: p.id }, p.label)), h("option", { value: "" }, "A set of my own"));
  const gets = h("p", { class: "small muted mod-gets", id: "mod-preset-d" });
  const rows = h("ul", { class: "mod-list", "aria-label": "Modules" });
  const inheritBox = h("input", { type: "checkbox", id: "mod-inherit", "data-key": "mod:inherit", checked: inherit });
  const reason = h("input", { maxlength: "300", id: "mod-reason", placeholder: "Why, in a few words (optional)", "data-key": "mod:reason" });
  const sync = () => {
    preset.value = presetFor(chosen) || "";
    const p = m.presets.find((x) => x.id === preset.value);
    gets.textContent = p ? "You bring " + p.brings + "; you get " + p.gets + "." : "A set of your own: the modules ticked below.";
    fill(rows, m.catalogue.map((mod) => moduleRow(mod, chosen.includes(mod.id), inherit, (on) => {
      chosen = on ? closure(chosen.concat([mod.id])) : chosen.filter((x) => x !== mod.id && !closure([x]).includes(mod.id));
      sync();
      const back = box.querySelector('[data-key="mod:m:' + mod.id + '"]');
      if (back) back.focus();
    })));
    preset.disabled = inherit;
  };
  preset.addEventListener("change", () => {
    const p = m.presets.find((x) => x.id === preset.value);
    if (p) { chosen = p.modules.slice(); sync(); }
  });
  inheritBox.addEventListener("change", () => { inherit = inheritBox.checked; if (inherit) chosen = m.factory.modules.slice(); sync(); });
  const saveB = button("Save the modules", { icon: "check", kind: "primary", key: "mod:save", "data-control": "modules",
    disabled: !maySet() || null, onclick: async () => {
      if (!S.person.trim()) { say("Set your name first: the change is signed with a person and a persona.", "warning"); if (nav.openPerson) nav.openPerson(true); return; }
      saveB.disabled = true;
      try {
        const p = presetFor(chosen);
        const body = inherit ? { inherit: true } : p ? { preset: p } : { modules: chosen };
        const out = await save(pid, Object.assign(body, { reason: reason.value.trim() }));
        say(changeLine(out), "good");
        drawChooser(box, pid);
        const again = box.querySelector('[data-key="mod:save"]');
        if (again) again.focus();
      } catch (e) {
        if (!(e instanceof AuthError)) { fill(status, icon("alert"), " " + e.message); say(e.message, "critical"); }
        saveB.disabled = !maySet();
      }
    } });
  fill(box, lead,
    pid ? h("div", { class: "set-row" }, h("label", { class: "chk-l", for: "mod-inherit" }, inheritBox, " Use the factory's set")) : null,
    h("div", { class: "set-row" }, h("label", { for: "mod-preset" }, "Preset"), preset), gets, rows,
    h("div", { class: "field" }, h("label", { for: "mod-reason" }, "Why are you changing this? (saved with your name)"), reason),
    h("div", { class: "btns" }, saveB, maySet() ? null : h("span", { class: "muted small" }, icon("user"),
      " A " + m.setters.map(personaLabel).join(", ") + " chooses the modules.")), status);
  sync();
}

// What each module does, in one plain line for a business reader; a technical reader keeps the kernel's own line.
const MODULE_PLAIN = {
  intake: "Questions and requirements: Rihma asks what it needs to know and writes down what will be built.",
  plan: "Plan and agreed checks: you approve the plan before anything is built.",
  build: "Building and checking: the AI builds each piece, and an automatic quality check reviews it.",
  delivery: "Delivery: releases you can try, and your approval before anything goes live.",
  operations: "Running it: live services are watched, problems open incidents, and updates are offered.",
  change: "Changes: feedback and change requests go back to the right step.",
  square: "Incoming requests: requests from chats and other places become changes or new ideas you approve.",
  capabilities: "What we have built: every product and agent, and a release package for each release.",
  security: "Security: scans of the code, and risks a person accepts for a limited time.",
  compliance: "Compliance: a proof package for auditors, with every decision and check.",
  assessment: "Existing systems: bring in a system you already have and see how it stands.",
  integrations: "Connections: website chats, notices and links to other tools.",
  assistant: "Ask Rihma: answers about your projects from an AI model. Without it, Ask Rihma only shows the way around the cockpit.",
};
function moduleRow(mod, on, locked, onToggle) {
  const id = "mod-m-" + mod.id;
  const box = h("input", { type: "checkbox", id, checked: on, disabled: locked || null, "data-key": "mod:m:" + mod.id,
    "aria-describedby": id + "-d" });
  box.addEventListener("change", () => onToggle(box.checked));
  const needs = mod.depends.length ? "Needs " + mod.depends.map((d) => (moduleOf(d) || { label: d }).label).join(", ") + ". " : "";
  return h("li", { class: "mod-row" + (on ? " on" : "") }, box,
    // the module's name and what it adds are the kernel's own words (kernel/modules.py), shown as written
    h("div", { class: "mod-b" }, h("label", { for: id, "data-ud": "" }, mod.label), " ",
      on ? chip("good", "check", "On") : chip("nm", "dashed", "Off"),
      h("p", { class: "small muted", id: id + "-d", "data-ud": "" }, !technical() && MODULE_PLAIN[mod.id] ? (on ? "" : "Off. ") + MODULE_PLAIN[mod.id] + " " + needs
        : (on ? "Adds " : "Off. Turning it on adds ") + mod.adds + ". " + needs
        + (mod.planned.length ? "Planned: " + mod.planned.join("; ") + "." : ""))));
}

// -- the first visit to a new factory home -----------------------------------------------------------------

/* A factory home with no project and no set chosen: the person is offered the usual starting points once
   (this tab), each saying what you bring and what you get. "Decide later" keeps the whole factory and
   records nothing; the choice is in Settings, Modules at any time. */
export function firstRun() {
  const m = S.modules;
  if (!m || !m.new_home || store.get("gf.firstrun") === "later") return;
  let chosen = "full";
  const grid = h("div", { class: "prof-grid mod-presets", role: "radiogroup", "aria-label": "Where to start" });
  const mark = () => $$(".prof-card", grid).forEach((b) => {
    const on = b.dataset.key === "preset:" + chosen;
    b.setAttribute("aria-checked", String(on));
    b.tabIndex = on ? 0 : -1;
  });
  fill(grid, m.presets.map((p) => {
    const b = h("button", { type: "button", role: "radio", "aria-checked": "false", class: "prof-card", "data-key": "preset:" + p.id },
      h("b", null, p.label), h("span", { class: "prof-s" }, "You bring " + p.brings + "."), h("small", null, "You get " + p.gets + "."));
    b.addEventListener("click", () => { chosen = p.id; mark(); });
    return b;
  }));
  grid.addEventListener("keydown", (e) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    const all = $$(".prof-card", grid);
    const i = all.indexOf(document.activeElement);
    if (i < 0 || (!step && e.key !== "Home" && e.key !== "End")) return;
    e.preventDefault();
    const next = all[e.key === "Home" ? 0 : e.key === "End" ? all.length - 1 : (i + step + all.length) % all.length];
    chosen = next.dataset.key.split(":")[1];
    mark();
    next.focus();
  });
  mark();
  const name = h("input", { id: "fr-name", maxlength: "200", value: S.person, autocomplete: "name" });
  const persona = h("select", { id: "fr-persona" }, m.setters.map((p) => h("option", { value: p, selected: p === S.persona || null }, personaLabel(p))));
  const status = h("p", { class: "mod-status", role: "status", "aria-live": "polite" });
  const as = h("div", { class: "field" }, h("label", { for: "fr-persona" }, "As"), persona);
  const who = whoWorksHere((mode) => { as.hidden = mode === "solo"; });   // Just me, or a team (FR-PPL1)
  as.hidden = true;
  const use = button("Start with this", { icon: "check", kind: "primary", key: "fr:use", "data-control": "modules", onclick: async () => {
    if (!name.value.trim()) { fill(status, icon("alert"), " Write your name: the choice is signed and recorded."); name.focus(); return; }
    S.person = name.value;
    store.set("gf.person", S.person);
    S.persona = persona.value;
    store.set("gf.persona", S.persona);
    if (nav.personChanged) nav.personChanged();
    use.disabled = true;
    try {
      const out = await save(null, { preset: chosen, reason: "the first-run choice" });
      const team = await who.apply(S.person.trim());
      store.set("gf.firstrun", "chosen");
      closeModal();
      say(changeLine(out) + " Settings, Modules changes it. " + team, "good");
      if (nav.route) nav.route(true);
    } catch (e) {
      use.disabled = false;
      if (!(e instanceof AuthError)) fill(status, icon("alert"), " " + e.message);
    }
  } });
  const later = button("Decide later: everything on", { kind: "quiet", key: "fr:later", onclick: () => {
    store.set("gf.firstrun", "later");
    closeModal();
  } });
  openModal("Start with what you need", h("div", { class: "fr" },
    h("p", null, "Rihmasto is a set of modules. Use one small part, or the whole factory, and change it later in Settings. "
      + "Whatever you choose, every decision names a person and everything is recorded in the ledger."),
    grid,
    h("div", { class: "fr-who" }, h("div", { class: "field" }, h("label", { for: "fr-name" }, "Your name"), name), as),
    who.el, status, h("div", { class: "btns" }, use, later)), { wide: true, icon: "layers" });
}
