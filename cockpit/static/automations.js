/* Automations (kernel/automations.py, FR-AUT1): a trigger, an optional guard, an action, a scope and limits,
   owned and signed by a person. The factory-wide page lists every one with scope filters and templates; each
   project has an Automations tab with its own and its tags. The builder shows, before it saves, the summary
   the kernel writes from the parts ("Every night at 02:00 UTC, for every attached project, run the gate ...").
   Nothing here decides anything: an automation never decides a card. */

import { pick, emptyState, technical } from "./words.js";
import { S, $, h, fill, icon, chip, api, act, say, signed, needPerson, enc, button, card, pageHead, skeleton, empty,
  openModal, closeModal, segmented, ago, nav, personaLabel } from "./core.js";
import { pathField } from "./picker.js";

const STATE = { active: ["good", "play", "Active"], paused: ["warning", "pause", "Paused"] };
const OUTCOME = { done: ["good", "check-circle"], nothing: ["neutral", "dashed"], would: ["info", "eye"],
  failed: ["critical", "x-circle"], refused: ["warning", "alert"] };
const F = { state: "all", scope: "all", project: "" };
let OFFERS = null;

function outcomeChip(o, verdict) {
  const [tone, ic] = OUTCOME[o] || ["nm", "dashed"];
  return chip(tone, ic, o + (verdict ? " (" + verdict + ")" : ""));
}

// -- one automation ------------------------------------------------------------------------------------

function history(a) {
  const runs = (a.history || []).filter((r) => r.kind === "automation_ran").slice(-5).reverse();
  if (!runs.length) return h("p", { class: "muted small" }, "No run yet.");
  return h("ul", { class: "plain small amn-hist" }, runs.map((r) => h("li", null, outcomeChip(r.outcome, r.verdict), " ",
    h("span", { class: "muted" }, ago(r.at) + (r.project ? " · " + r.project : "") + (r.requested_by ? " · asked by " + r.requested_by : "")),
    r.detail ? h("span", null, " · " + r.detail) : null)));
}

async function post(a, path, body, done) {
  if (!needPerson()) return;
  const out = await api("POST", "/api/automations/" + enc(a.id) + path, Object.assign({}, body || {}, signed()));
  if (done) await done(out);
}

function row(a, again) {
  const st = STATE[a.state] || STATE.active;
  const tools = h("div", { class: "mdl-tools" });
  const result = h("p", { class: "mdl-result muted small", "aria-live": "polite" });
  const btn = (label, ic, attrs, fn) => {
    const control = attrs["data-control"];
    const b = button(label, { icon: ic, kind: "small", "data-control": control, key: control + ":" + a.id, aria: label + " " + a.id });
    b.addEventListener("click", () => act(tools, fn));
    tools.append(b);
  };
  btn("Run now", "play", { "data-control": "automations_run" }, () => post(a, "/run", {}, (out) => {
    say(a.id + (out.scheduler ? " runs now." : " runs on the next tick (the scheduler runs while the cockpit runs, or `rihmasto automations tick`)."), "good");
    setTimeout(again, 1500);
    setTimeout(again, 6000);      // a run that takes longer shows under What ran here without a reload
  }));
  btn("Dry run", "eye", { "data-control": "automations_dry_run" }, () => post(a, "/dry-run", {}, (out) => {
    const d = out.dry_run;
    fill(result, d.firings.length ? d.firings.map((f) => h("span", { class: "amn-would" }, (f.project || "the factory") + ": " + f.would
      + (f.guard === "holds" ? "" : " (guard " + f.guard + ")"))) : "Nothing would run on the next tick" + (d.next_at ? "; next at " + d.next_at : "") + ".");
  }));
  if (a.state === "paused") btn("Resume", "play", { "data-control": "automations_resume" }, () => post(a, "/resume", {}, again));
  else btn("Pause", "pause", { "data-control": "automations_pause" }, () => post(a, "/pause", { reason: "paused in the cockpit" }, again));
  btn("Edit", "edit", { "data-control": "automations_edit" }, () => openBuilder(a, again));
  btn("Remove", "x", { "data-control": "automations_remove" }, () => post(a, "/remove", {}, async () => { say(a.id + " removed.", "good"); await again(); }));
  return h("li", { class: "mdl-row", "data-key": "auto:" + a.id, "data-id": a.id },
    h("div", { class: "mdl-main" },
      h("b", null, a.name), h("span", { class: "mono muted small" }, " " + a.id),
      h("p", { class: "amn-sum" }, a.summary),
      h("div", { class: "mdl-chips" }, chip(st[0], st[1], st[2]), chip("neutral", "user", a.owner.person + " as " + personaLabel(a.owner.persona)),
        a.limits.dry_run ? chip("info", "eye", "Dry run") : null, a.last ? outcomeChip(a.last.outcome) : null,
        a.queue ? chip("info", "clock", a.queue + " waiting") : null),
      a.paused_why ? h("p", { class: "note warning amn-why" }, icon("alert"), h("span", null, a.paused_why)) : null,
      h("details", { class: "amn-det" }, h("summary", null, "Runs"), history(a)), result),
    tools);
}

// -- the builder ---------------------------------------------------------------------------------------

function sel(id, options, value, label) {
  return h("div", { class: "field" }, h("label", { for: id }, label),
    h("select", { id }, options.map(([v, l]) => h("option", { value: v, selected: v === value ? true : null }, l))));
}
function inp(id, value, label, extra) {
  return h("div", { class: "field" }, h("label", { for: id }, label), h("input", Object.assign({ id, value: value == null ? "" : String(value),
    autocomplete: "off", spellcheck: "false" }, extra || {})));
}
// A folder on the cockpit's machine: typed, or chosen by browsing (picker.js, FR-PICK1).
function folderInp(id, value, label) {
  const input = h("input", { id, value: value == null ? "" : String(value), autocomplete: "off", spellcheck: "false" });
  return h("div", { class: "field" }, h("label", { for: id }, label), pathField(input, { kind: "folder", name: "the folder to scan again", title: "Choose the folder to scan again" }));
}
const val = (id) => { const el = document.getElementById(id); return el ? el.value.trim() : ""; };
const num = (id) => parseInt(val(id), 10);

function schedOf(t) {
  if (t.every) return ["every", t.every];
  if (t.daily) return ["daily", t.daily];
  if (t.weekly) return ["weekly", t.weekly];
  return ["daily", "02:00"];
}

function builderForm(a) {
  const o = OFFERS;
  const t = a.trigger || {}, g = a.guard || {}, x = a.action || {}, sc = a.scope || {}, lim = a.limits || {}, n = a.notify || {};
  const [sk, sv] = schedOf(t);
  const projects = o.projects.map((p) => [p.id, p.title + " (" + p.id + ")"]);
  const subs = [["", "None"]].concat(o.subscriptions.map((s) => [s.id, s.id + " (" + s.sink + ")"]));
  const picked = new Set(sc.projects || []);
  const parts = [
    inp("amn-name", a.name || "", "Name"),
    h("fieldset", { class: "amn-part" }, h("legend", null, "When"),
      sel("amn-trigger", [["schedule", "On a schedule"], ["event", "When something is recorded"], ["hook", "When an inbound webhook rings"], ["repo", "When new commits land"]], t.kind || "schedule", "Trigger"),
      h("div", { class: "row2", "data-show": "trigger:schedule" }, sel("amn-sched", [["every", "Every"], ["daily", "Daily at (UTC)"], ["weekly", "Weekly on (UTC)"]], sk, "How often"),
        inp("amn-sched-v", sv, "15m, 2h, 1d · 02:00 · mon 02:00")),
      h("div", { "data-show": "trigger:event" }, inp("amn-events", (t.types || ["release_done"]).join(", "), "Record kinds (comma between), for example " + o.events.slice(0, 4).join(", "))),
      h("div", { "data-show": "trigger:hook" }, sel("amn-hook", [["", "Choose a source"]].concat(o.sources.map((s) => [s.id, s.id + (s.projects.length ? " (bound to " + s.projects.join(", ") + ")" : "")])), t.source || "", "Inbound source")),
      h("div", { "data-show": "trigger:repo" }, inp("amn-branch", t.branch || "", "Branch (empty: the tracked one)"))),
    h("fieldset", { class: "amn-part" }, h("legend", null, "Only when (a guard, optional)"),
      sel("amn-guard", [["", "Always"], ["count", "It happened at least N times"], ["branch", "On a branch"], ["field", "A field equals"], ["open_cards", "Cards are open"]], g.kind || "", "Guard"),
      h("div", { class: "row2", "data-show": "guard:count" }, inp("amn-g-event", g.event || "gate_failed", "Event"), inp("amn-g-n", g.at_least || 2, "At least", { type: "number", min: "1" })),
      h("div", { "data-show": "guard:count" }, inp("amn-g-hours", g.within_hours || 24, "Within hours", { type: "number", min: "1" })),
      h("div", { "data-show": "guard:branch" }, inp("amn-g-branch", g.is || "main", "Branch")),
      h("div", { class: "row2", "data-show": "guard:field" }, inp("amn-g-key", g.key || "verdict", "Field"), inp("amn-g-value", g.equals || "failed", "Equals")),
      h("div", { "data-show": "guard:open_cards" }, inp("amn-g-cards", g.at_least || 3, "Open cards, at least", { type: "number", min: "1" }))),
    h("fieldset", { class: "amn-part" }, h("legend", null, "Do"),
      sel("amn-action", o.actions.map((y) => [y.id, y.label]), x.kind || "notify", "Action"),
      h("div", { "data-show": "action:change action:signal action:ask action:notify" }, inp("amn-a-text", x.text || "", "Words ({project}, {event}, {ref} are filled in)")),
      h("div", { "data-show": "action:rescan" }, folderInp("amn-a-folder", x.folder || "", "Folder on this machine")),
      h("div", { "data-show": "action:notify" }, sel("amn-a-sub", subs.slice(1), x.subscription || "", "Relay subscription (IT sets these up)")),
      h("div", { "data-show": "action:change" }, sel("amn-a-target", [["", "The project it reacts to"]].concat(projects), x.project || "", "On project")),
      h("div", { "data-show": "action:output" }, inp("amn-a-targets", (x.targets || []).join(", "), "Outputs (empty: the chosen ones)")),
      h("div", { "data-show": "action:probe" }, sel("amn-a-env", [["", "Where the event says (else production)"], ["preview", "Preview"], ["demo", "Demo"], ["staging", "Staging"], ["production", "Production"]], x.environment || "", "Probe where"),
        inp("amn-a-every", x.every || "", "Keep probing production every (15m to 1d; empty: once)")),
      h("div", { "data-show": "action:gate" }, h("label", { class: "chk", for: "amn-a-nover" }, h("input", { type: "checkbox", id: "amn-a-nover", checked: x.verifier === false ? true : null }), " Without the verifier"))),
    h("fieldset", { class: "amn-part" }, h("legend", null, "For"),
      sel("amn-scope", [["project", "One project"], ["projects", "Some projects"], ["tag", "Projects with a tag"], ["profile", "Projects of a profile"], ["source", "Projects of a source"], ["factory", "Every project"]], sc.kind || "project", "Scope"),
      h("div", { class: "amn-picks", "data-show": "scope:project scope:projects", role: "group", "aria-label": "Projects" }, o.projects.map((p) =>
        h("label", { class: "chk", for: "amn-p-" + p.id }, h("input", { type: "checkbox", id: "amn-p-" + p.id, value: p.id, class: "amn-pick", checked: picked.has(p.id) ? true : null }), " " + p.title))),
      h("div", { "data-show": "scope:tag" }, inp("amn-s-tag", sc.tag || "", "Tag")),
      h("div", { "data-show": "scope:profile" }, inp("amn-s-profile", sc.profile || "", "Profile")),
      h("div", { "data-show": "scope:source" }, sel("amn-s-source", [["attached", "Attached repositories"], ["adopted", "Adopted systems"], ["idea", "From an idea"], ["folder", "From a folder"]], sc.source || "attached", "Source"))),
    h("fieldset", { class: "amn-part" }, h("legend", null, "Limits"),
      h("div", { class: "row2" }, inp("amn-l-max", lim.max_per_hour || 12, "Runs an hour, at most", { type: "number", min: "1" }),
        inp("amn-l-breaker", lim.breaker || 3, "Pause after failures in a row", { type: "number", min: "1" })),
      inp("amn-l-quiet", lim.quiet || "", "Quiet hours, UTC (22:00-06:00), optional"),
      h("label", { class: "chk", for: "amn-l-dry" }, h("input", { type: "checkbox", id: "amn-l-dry", checked: lim.dry_run ? true : null }), " Dry run: record what it would do, do nothing"),
      h("div", { class: "row2" }, sel("amn-n-sub", subs, n.subscription || "", "Notify of the outcome"), sel("amn-n-when", [["failed", "If it fails"], ["always", "Every run"]], n.when || "failed", "When"))),
  ];
  return parts;
}

function showParts(form) {
  const on = { trigger: val("amn-trigger"), guard: val("amn-guard"), action: val("amn-action"), scope: val("amn-scope") };
  form.querySelectorAll("[data-show]").forEach((el) => {
    el.hidden = !el.dataset.show.split(" ").some((s) => { const [k, v] = s.split(":"); return on[k] === v; });
  });
}

function draftOf() {
  const tk = val("amn-trigger");
  const trigger = tk === "schedule" ? { kind: tk, [val("amn-sched")]: val("amn-sched-v") } : tk === "event"
    ? { kind: tk, types: val("amn-events").split(",").map((s) => s.trim()).filter(Boolean) } : tk === "hook" ? { kind: tk, source: val("amn-hook") }
    : { kind: tk, branch: val("amn-branch") || null };
  const gk = val("amn-guard");
  const guard = !gk ? null : gk === "count" ? { kind: gk, event: val("amn-g-event"), at_least: num("amn-g-n"), within_hours: num("amn-g-hours") }
    : gk === "branch" ? { kind: gk, is: val("amn-g-branch") } : gk === "field" ? { kind: gk, key: val("amn-g-key"), equals: val("amn-g-value") }
    : { kind: gk, at_least: num("amn-g-cards") };
  const ak = val("amn-action");
  const action = { kind: ak, text: val("amn-a-text"), folder: val("amn-a-folder"), subscription: val("amn-a-sub"),
    project: ak === "change" ? val("amn-a-target") || null : null, verifier: !$("#amn-a-nover").checked,
    targets: val("amn-a-targets").split(",").map((s) => s.trim()).filter(Boolean),
    environment: ak === "probe" ? val("amn-a-env") || null : null, every: ak === "probe" ? val("amn-a-every") || null : null };
  const sk = val("amn-scope");
  const picks = [...document.querySelectorAll(".amn-pick:checked")].map((c) => c.value);
  const scope = sk === "project" || sk === "projects" ? { kind: picks.length > 1 ? "projects" : "project", projects: picks }
    : sk === "factory" ? { kind: sk } : { kind: sk, [sk]: val("amn-s-" + sk) };
  const limits = { max_per_hour: num("amn-l-max"), breaker: num("amn-l-breaker"), quiet: val("amn-l-quiet") || null, dry_run: $("#amn-l-dry").checked };
  const notify = val("amn-n-sub") ? { subscription: val("amn-n-sub"), when: val("amn-n-when") } : null;
  return { name: val("amn-name"), trigger, guard, action, scope, limits, notify };
}

function openBuilder(a, again) {
  const editing = !!a.id;
  const summary = h("p", { class: "note amn-summary", id: "amn-summary", "aria-live": "polite" }, icon("info"), h("span", null, "…"));
  const save = h("button", { type: "submit", class: "btn primary", "data-control": "automations_save", "data-key": "amn-save" }, icon("check"), editing ? "Save the changes" : "Set it up");
  const form = h("form", { class: "np-form amn-form", novalidate: true }, builderForm(a), summary, h("div", { class: "btns" }, save));
  let timer = null;
  const preview = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      if (!S.person.trim()) { fill(summary, icon("user"), h("span", null, "Set your name to see the summary.")); return; }
      try {
        const out = await api("POST", "/api/automations/preview", Object.assign({ automation: draftOf() }, signed()));
        fill(summary, icon(out.ok ? "info" : "alert"), h("span", null, out.ok ? out.summary + (out.projects.length ? " Now: " + out.projects.join(", ") + "." : "") : "Not yet: " + out.why));
        summary.classList.toggle("warning", !out.ok);
      } catch (e) { fill(summary, icon("alert"), h("span", null, e.message)); }
    }, 250);
  };
  form.addEventListener("change", () => { showParts(form); preview(); });
  form.addEventListener("input", preview);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!needPerson()) return;
    act(form, async () => {
      const body = Object.assign({ automation: draftOf() }, signed());
      const out = editing ? await api("PUT", "/api/automations/" + enc(a.id), body) : await api("POST", "/api/automations", body);
      closeModal();
      say(out.automation.id + " is set: " + out.automation.summary, "good");
      if (again) await again();
    });
  });
  openModal(editing ? "Edit " + a.id : "New automation", form, { icon: "clock", wide: true });
  showParts(form);
  preview();
}

// The templates a business reader knows by what they do for them; a developer keeps the kernel's own names.
const TPL_PLAIN = { nightly_regate: "Re-check all work every night", gate_twice: "Ask me when a task fails twice",
  production_probe: "Start watching a service once it is live", align_on_change: "Check the code against the plan when it changes" };
// An adopted project's material is its repository: re-scanning a folder into it is refused, so it is not offered.
const NOT_FOR_ADOPTED = new Set(["weekly_rescan"]);
function templates(again, preset) {
  const meta = (preset && S.project && S.project.meta) || {};
  const offered = OFFERS.templates.filter((t) => !(meta.source_kind === "adopted" && NOT_FOR_ADOPTED.has(t.id)));
  return card({ title: "Start from a template", icon: "sparkles", id: "amn-tpl" },
    h("div", { class: "btns amn-tpls" }, offered.map((t) => {
      const b = button((!technical() && TPL_PLAIN[t.id]) || t.label, { icon: "plus", kind: "small", "data-control": "automations_template", key: "amn-tpl:" + t.id, tip: t.about });
      b.setAttribute("data-ud", "");   // the template's own name, as the kernel offers it (kernel/automations_text.py)
      b.addEventListener("click", () => openBuilder(Object.assign(JSON.parse(JSON.stringify(t.draft)), preset ? { scope: preset } : {}), again));
      return b;
    })));
}

// -- the factory-wide page -----------------------------------------------------------------------------

function shownRows(rows) {
  return rows.filter((a) => (F.state === "all" || a.state === F.state) && (F.scope === "all" || a.scope.kind === F.scope)
    && (!F.project || (a.projects_now || []).includes(F.project)));
}

export async function renderAutomations(seq) {
  const main = $("#main");
  const done = skeleton(main, "the automations");
  let data;
  try { data = await api("GET", "/api/automations"); } finally { done(); }
  if (seq !== S.seq) return;
  OFFERS = data;
  document.title = "Automations · Rihmasto.ai";
  const again = () => renderAutomations(S.seq);
  const list = h("ul", { class: "emb-list amn-list", id: "amn-list" });
  const draw = () => {
    const rows = shownRows(data.automations);
    fill(list, rows.length ? rows.map((a) => row(a, again)) : h("li", null, data.automations.length ? empty("clock", "None matches these filters.")
      : emptyState("automations", null, { icon: "clock" })));
  };
  const filters = h("div", { class: "btns amn-filters" },
    segmented("amn-f-state", [["all", "All"], ["active", "Active"], ["paused", "Paused"]], F.state, (v) => { F.state = v; draw(); }, { label: "State" }),
    h("label", { class: "vh", for: "amn-f-scope" }, "Scope"),
    h("select", { id: "amn-f-scope", "aria-label": "Scope", onchange: (e) => { F.scope = e.target.value; draw(); } },
      // what each automation is set to cover: "all automations" first, never two options that read alike
      [["all", "Show: all automations"], ["factory", "Set for all projects"], ["project", "Set for one project"], ["projects", "Set for several projects"],
        ["tag", "Set for a tag"], ["profile", "Set for a type of project"], ["source", "Set for a source"]]
        .map(([v, l]) => h("option", { value: v, selected: v === F.scope ? true : null }, l))),
    h("select", { id: "amn-f-project", "aria-label": "Runs for project", onchange: (e) => { F.project = e.target.value; draw(); } },
      [["", "For whichever project"]].concat(data.projects.map((p) => [p.id, p.title])).map(([v, l]) => h("option", { value: v, selected: v === F.project ? true : null }, l))));
  const sched = data.scheduler || {};
  fill(main,
    pageHead("Automations", pick("Rules that run by themselves, like “tell me when a release is ready”. They never decide for you.",
      "A trigger, an optional guard, an action and a scope, run with your rights. An automation never decides a card."), {
      icon: "clock", actions: [button("New automation", { icon: "plus", kind: "primary", "data-control": "automations_new", key: "amn-new",
        onclick: () => openBuilder({ scope: { kind: "factory" } }, again) })] }),
    h("p", { class: "note" + (sched.running ? "" : " warning") }, icon(sched.running ? "check-circle" : "info"), h("span", null, sched.running
      ? pick("The cockpit checks them every minute" + (sched.last ? "; last checked " + ago(sched.last.at) : "") + ".",
        "The cockpit runs them every minute" + (sched.last ? "; last tick " + ago(sched.last.at) : "") + ".")
      : "The cockpit's scheduler is not running here. Without it, run `rihmasto automations tick` every minute: `rihmasto automations install-help` prints the line for cron or Windows Task Scheduler.")),
    templates(again, null), filters, card({ title: "Automations", icon: "clock", id: "amn-all" }, list));
  draw();
}

// -- a project's tab ----------------------------------------------------------------------------------

export function viewAutomations(p) {
  const pid = p.meta.id;
  const box = h("div", { class: "amn-tab" }, h("div", { class: "q" }, h("h2", { id: "view-title", tabindex: "-1" }, "Automations"),
    h("p", null, "What runs on its own for this project, and in whose name.")), h("p", { class: "muted" }, "Loading…"));
  drawTab(box, pid).catch((e) => fill(box, empty("alert", e.message)));
  return box;
}

async function drawTab(box, pid) {
  const [mine, all] = await Promise.all([api("GET", "/api/projects/" + enc(pid) + "/automations"), api("GET", "/api/automations")]);
  if (!box.isConnected) return;
  OFFERS = all;
  const again = () => drawTab(box, pid);
  const tags = h("input", { id: "amn-tags", value: mine.tags.join(", "), autocomplete: "off", spellcheck: "false", "aria-label": "Tags (separate with commas)" });
  const saveTags = button("Save tags", { icon: "check", kind: "small", "data-control": "automations_tags", key: "amn-tags-save" });
  saveTags.addEventListener("click", () => act(saveTags.parentNode, async () => {
    if (!needPerson()) return;
    const out = await api("PUT", "/api/projects/" + enc(pid) + "/tags", Object.assign({ tags: tags.value.split(",").map((s) => s.trim()).filter(Boolean) }, signed()));
    say("Tags: " + (out.tags.join(", ") || "none") + ".", "good");
  }));
  const preset = { kind: "project", projects: [pid] };
  fill(box, h("div", { class: "q" }, h("h2", { id: "view-title", tabindex: "-1" }, "Automations"),
    h("p", null, "What runs on its own for this project, and in whose name. An automation never decides a card.")),
  h("div", { class: "btns" }, button("New automation", { icon: "plus", kind: "primary", "data-control": "automations_new", key: "amn-new:" + pid,
    onclick: () => openBuilder({ scope: preset }, again) }), h("a", { class: "btn quiet", href: "#/automations", "data-control": "automations_open", "data-key": "amn-all:" + pid }, icon("clock"), h("span", { class: "lbl" }, "Every automation"))),
  card({ title: "Tags", icon: "flag", id: "amn-tags-card", info: "An automation scoped to a tag reaches every project that carries it." },
    h("div", { class: "field" }, h("label", { for: "amn-tags" }, "Tags (separate with commas)"), tags), h("div", { class: "btns" }, saveTags)),
  templates(again, preset),
  card({ title: "On this project", icon: "clock", id: "amn-mine" }, h("ul", { class: "emb-list amn-list" },
    mine.automations.length ? mine.automations.map((a) => row(a, again)) : h("li", null, emptyState("automations", null, { icon: "clock",
      what: "No automation runs for this project yet.", how: pick("Start from a template above, or ask Rihma to set one up; it appears here with when it runs.",
        "Start from a template above or create one with New automation; it appears here with its trigger and last run.") })))),
  card({ title: "What ran here", icon: "layers", id: "amn-ran" }, mine.history.length ? h("ul", { class: "plain small amn-hist" },
    mine.history.slice().reverse().slice(0, 15).map((r) => h("li", null, r.kind === "automation_ran" ? outcomeChip(r.outcome, r.verdict) : chip("neutral", "info", r.kind.replace("automation_", "")),
      " " + r.id + " · " + ago(r.at) + (r.detail ? " · " + r.detail : "")))) : h("p", { class: "muted" }, "Nothing yet.")));
  if (nav.refreshShell) nav.refreshShell();
}

// -- Home: an automation the circuit breaker paused -------------------------------------------------------

export async function pausedCard(box) {
  if (!box) return;
  let data;
  try { data = await api("GET", "/api/automations?state=paused"); } catch (e) { return; }
  const paused = (data.automations || []).filter((a) => a.paused_by === "breaker");
  if (!box.isConnected || !paused.length) { if (box.isConnected) fill(box); return; }
  fill(box, card({ title: paused.length === 1 ? "An automation was paused" : paused.length + " automations were paused", icon: "alert", id: "home-auto-card", cls: "setup-card" },
    h("ul", { class: "plain small" }, paused.slice(0, 3).map((a) => h("li", null, h("b", null, a.id + " " + a.name + ": "), a.paused_why))),
    h("div", { class: "btns" }, h("a", { href: "#/automations", class: "btn primary", "data-control": "automations_open", "data-key": "home:automations" }, icon("clock"),
      h("span", { class: "lbl" }, "Open Automations")))));
}
