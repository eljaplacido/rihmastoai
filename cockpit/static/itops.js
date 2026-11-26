/* What IT checks (kernel/itops*.py, FR-ITO1). The owner: "IT maintenance view should include typical infrastructure
   checks done for apps, databases, networks, integrations ... think what they would be per project and solution type
   too". A project's IT checks view (#/p/<pid>/itops, the Run capsule): what the project is (its solution types, with
   why), its check set with why each check is there and whether the rule is the platform's or this project's, Enable
   the set and Run the IT checks now, a check added or taken away for this project, Run an assessment of any area, the
   eval sets (Gnomon's per project, Rihma's role evals platform-wide) with their trends, and the automations IT's
   context suggests. Small cards of the same go on Health, on Integrations and data, on the platform's Integrations
   and data page (the defaults per type) and on Agent operations (the eval sets' trends). What the kernel wrote (why,
   summaries, labels) is shown as its own words (data-ud). */

import { S, h, fill, icon, chip, api, act, say, signed, needPerson, button, ago, card, plural, enc, empty, link } from "./core.js";
import { datum, emptyState, pick } from "./words.js";
import { openAssistant, send as askRihma } from "./assistant.js";

const ASK_SET = "What should IT check for this project?";
const VERDICT = { passed: ["good", "check-circle", "Passed"], failed: ["critical", "x-circle", "Failed"],
  "not measured": ["nm", "dashed", "Not measured"], "not run yet": ["neutral", "clock", "Not run yet"],
  "not enabled": ["neutral", "dashed", "Not on yet"] };
const SCOPE = { "platform default": ["neutral", "layers", "Platform default"],
  "platform default (changed by IT)": ["info", "layers", "Platform default, changed by IT"],
  "project override": ["accent", "folder", "This project only"] };
const NAMED = ["gnomon", "evalset", "check", "family"];      // assessment targets that name which one
const base = (pid) => "/api/projects/" + enc(pid) + "/itops";

function verdict(state) { const [t, i, w] = VERDICT[state] || VERDICT["not measured"]; return chip(t, i, w, { "data-verdict": state }); }
function scopeChip(s) { const [t, i, w] = SCOPE[s] || SCOPE["platform default"]; return chip(t, i, w, { "data-scope": s }); }
function line(iconName, kids, cls) { return h("p", { class: "ito-line" + (cls ? " " + cls : "") }, icon(iconName), h("span", null, kids)); }
function ask(question) { openAssistant(); askRihma(question); }
function askButton(question, key) { return button(question, { icon: "bot", kind: "small quiet", key, onclick: () => ask(question) }); }

// A row of small squares, oldest first: one per run, its tone the result (the latest is the last).
function trend(rows, unit) {
  const tone = { passed: "ok", failed: "bad" };
  return h("span", { class: "hl-trend", role: "img", "aria-label": "Last results: " + (rows.map((t) => t.verdict).join(", ") || "none") },
    rows.map((t) => h("span", { class: "hl-sq " + (tone[t.verdict] || "nm"), tip: t.verdict + (t.value != null ? " · " + t.value + (unit || "") : "") + " · " + ago(t.at) })));
}

// -- what the project is, and its check set ----------------------------------------------------------------

function typesCard(pid, data, again) {
  const s = data.set;
  const pickBox = h("div", { class: "ito-types", role: "group", "aria-label": "Solution types" }, data.types.map((t) =>
    h("label", { class: "chk", for: "ito-t-" + t.id }, h("input", { type: "checkbox", id: "ito-t-" + t.id, value: t.id, class: "ito-t",
      checked: s.types.some((x) => x.id === t.id) || null }), " " + t.label)));
  const save = button("Save the types", { icon: "check", kind: "small", key: "ito-types-save", "data-control": "itops_types" });
  const reset = s.chosen ? button("Go back to what was found", { kind: "small quiet", key: "ito-types-reset", "data-control": "itops_types" }) : null;
  const send = (types) => act(save.parentElement, async () => {
    if (!needPerson()) return;
    await api("POST", base(pid) + "/types", Object.assign({ types }, signed()));
    say(types.length ? "Solution types saved for this project." : "Back to the types that were found.", "good");
    await again();
  });
  save.addEventListener("click", () => send([...pickBox.querySelectorAll(".ito-t")].filter((x) => x.checked).map((x) => x.value)));
  if (reset) reset.addEventListener("click", () => send([]));
  return card({ title: "What it runs", icon: "layers", id: "ito-types", info: "The solution types decide which checks IT typically runs. They come from the project's work profile and from what was found: where it runs, what it connects to, its scheduled jobs and evals." },
    h("ul", { class: "ito-list" }, s.types.map((t) => h("li", { class: "ito-type", "data-type": t.id },
      h("div", { class: "ito-top" }, h("b", null, t.label), s.chosen ? chip("accent", "folder", "Chosen for this project") : chip("neutral", "search", "Found")),
      line("info", datum(t.why.join("; ")), "muted")))),
    h("details", { class: "ito-more" }, h("summary", null, "Change the solution types"), pickBox, h("div", { class: "btns" }, save, reset)));
}

function checkRow(pid, r, again) {
  const off = button("Take away here", { icon: "x", kind: "small quiet", key: "ito-off:" + r.check, "data-control": "itops_override",
    aria: "Take " + r.label + " away for this project" });
  off.addEventListener("click", () => act(off.parentElement, async () => {
    if (!needPerson()) return;
    await api("POST", base(pid) + "/override", Object.assign({ check: r.check, action: "remove" }, signed()));
    say(r.label + " is taken away for this project.", "good");
    await again();
  }));
  return h("li", { class: "ito-row", "data-check": r.check, "data-key": "ito:" + r.check },
    h("div", { class: "ito-top" }, h("b", { "data-ud": "" }, r.label), h("span", { class: "mono muted small" }, r.check),
      verdict(r.state), scopeChip(r.scope), r.every ? h("span", { class: "muted small" }, "every " + r.every) : null),
    r.why.map((w) => line("info", datum(w), "ito-why")),
    r.summary ? line("pulse", [datum(r.summary), r.at ? h("span", { class: "muted small" }, " · " + ago(r.at)) : null], r.state === "failed" ? "bad" : "muted") : null,
    h("div", { class: "btns" }, off));
}

function addForm(pid, catalogue, again) {
  const sel = h("select", { id: "ito-add-kind", "aria-label": "Check to add" }, catalogue.map((c) => h("option", { value: c.kind }, c.label)));
  const why = h("input", { type: "text", id: "ito-add-why", class: "input small", maxlength: "300", placeholder: "Why this project needs it",
    "aria-label": "Why this project needs it" });
  const add = button("Add for this project", { icon: "plus", kind: "small", key: "ito-add", "data-control": "itops_override" });
  add.addEventListener("click", () => act(add.parentElement, async () => {
    if (!needPerson()) return;
    await api("POST", base(pid) + "/override", Object.assign({ check: sel.value, action: "add", why: why.value }, signed()));
    say("Added for this project.", "good");
    await again();
  }));
  return h("div", { class: "ito-add" }, sel, why, add);
}

function setCard(pid, data, catalogue, again) {
  const s = data.set;
  const tools = h("span", { class: "btns" });
  const apply = button(s.missing.length ? "Turn on " + plural(s.missing.length, "check") : "All on", { icon: "check", kind: "small primary",
    key: "ito-apply", "data-control": "itops_apply", disabled: !s.missing.length || null });
  apply.addEventListener("click", () => act(tools, async () => {
    if (!needPerson()) return;
    const out = await api("POST", base(pid) + "/apply", signed());
    say(plural(out.enabled.length, "check") + " turned on" + (out.skipped.length ? "; " + out.skipped.length + " not: " + out.skipped.map((x) => x.why).join("; ") : "."),
      out.skipped.length ? "warning" : "good");
    await again();
  }));
  const run = button("Run the IT checks now", { icon: "play", kind: "small", key: "ito-run", "data-control": "itops_run" });
  run.addEventListener("click", () => act(tools, async () => {
    if (!needPerson()) return;
    say("Running the IT checks…", "info");
    const out = await api("POST", base(pid) + "/run", signed());
    const failed = out.ran.filter((x) => x.verdict === "failed");
    say(out.ran.length ? plural(out.ran.length, "check") + " ran" + (failed.length ? "; failing: " + failed.map((x) => x.check).join(", ") : ".")
      : "No IT check is on yet: turn the set on first.", failed.length ? "warning" : "good");
    await again();
  }));
  tools.append(apply, run);
  // Turning the set on and running it are IT's, operations' or a developer's: another persona sees whose, never a refusal.
  const mine = !data.setters || data.setters.includes(S.persona);
  if (!mine) for (const b of [apply, run]) { b.disabled = true; b.setAttribute("aria-disabled", "true"); }
  const whose = mine ? null : line("key", "Turning these on and running them is for IT, operations or a developer: switch persona in the person chip, or ask them.", "muted ito-whose");
  const removed = s.removed.length ? h("ul", { class: "ito-list" }, s.removed.map((r) => {
    const back = button("Put back", { kind: "small quiet", key: "ito-back:" + r.check, "data-control": "itops_override" });
    back.addEventListener("click", () => act(back.parentElement, async () => {
      if (!needPerson()) return;
      await api("POST", base(pid) + "/override", Object.assign({ check: r.check, action: "reset" }, signed()));
      await again();
    }));
    return h("li", { class: "ito-row muted", "data-removed": r.check }, h("span", { class: "mono" }, r.check), " ", scopeChip(r.scope), " ", back);
  })) : null;
  const body = s.checks.length ? h("ul", { class: "ito-list", id: "ito-checks" }, s.checks.map((r) => checkRow(pid, r, again)))
    : emptyState("itops", askButton(ASK_SET, "ito-ask-empty"), { icon: "pulse", what: "No IT check for this project.",
      how: s.none || "Checks appear here once the project runs somewhere, declares a database or an integration, or runs a scheduled job; you can add one below." });
  return card({ title: "IT checks", icon: "pulse", id: "ito-set", tools, info: "Each check says why it is there and where the rule comes from: the platform default for its solution type, or this project's own change. A check that is on runs on its schedule on Health." },
    h("div", { "data-control": "itops_set" }, h("p", { class: "ito-sum", "data-ud": "", "data-key": "ito-line" }, s.line), whose, body),
    removed ? [h("h4", { class: "small" }, "Taken away for this project"), removed] : null,
    h("details", { class: "ito-more" }, h("summary", null, "Add a check for this project"), addForm(pid, catalogue, again)));
}

// -- any assessment ---------------------------------------------------------------------------------------------

function assessCard(pid, data) {
  const target = h("select", { id: "ito-target", "aria-label": "What to assess" }, data.targets.map((t) => h("option", { value: t.id }, t.label)));
  const name = h("input", { type: "text", id: "ito-target-name", class: "input small", placeholder: "security, tls, check key…",
    "aria-label": "Which one (for a Gnomon eval, an eval set, a check or a family)" });
  const out = h("p", { class: "small", id: "ito-assess-out", "aria-live": "polite" });
  const run = button("Run the assessment", { icon: "play", kind: "small primary", key: "ito-assess", "data-control": "itops_assess" });
  run.addEventListener("click", () => act(run.parentElement, async () => {
    if (!needPerson()) return;
    fill(out);                                   // the last result never stays beside a new request's error
    if (NAMED.includes(target.value) && !name.value.trim()) {
      fill(out, line("alert", "Say which one in the box beside it (for example security, tls or a check key).", "bad"));
      name.focus();
      return;
    }
    const t = target.value + (name.value.trim() ? ":" + name.value.trim() : "");
    say("Running " + t + "…", "info");
    try {
      const got = await api("POST", base(pid) + "/assess", Object.assign({ target: t }, signed()));
      fill(out, verdict(got.verdict || "not measured"), " ", datum(got.target + ": " + got.detail));
      say(got.detail, got.verdict === "failed" ? "warning" : "good");
    } catch (e) {
      fill(out, line("alert", [t + ": ", datum(e.message)], "bad"));
      throw e;
    }
  }));
  return card({ title: "Run an assessment", icon: "shield", id: "ito-assess-card", info: "Any area, now: the code assessment, a Gnomon audit or eval set, one check or a family of checks, alignment, the Optimise audit of the agents, or the IT checks. It runs with your rights, and its result is kept where that area keeps it. An automation can run the same on a schedule (Run an assessment)." },
    h("div", { class: "ito-add" }, target, name, run), out);
}

// -- eval sets --------------------------------------------------------------------------------------------------

function evalRow(pid, r, again) {
  const tools = h("span", { class: "btns" });
  const toggle = button(r.enabled ? "Turn off" : "Turn on", { icon: r.enabled ? "x" : "check", kind: "small" + (r.enabled ? " quiet" : ""),
    key: "ito-ev:" + r.id, "data-control": "itops_evalset", disabled: (!r.available && !r.enabled) || null, aria: (r.enabled ? "Turn off " : "Turn on ") + r.label });
  toggle.addEventListener("click", () => act(tools, async () => {
    if (!needPerson()) return;
    await api("POST", base(pid) + "/evalsets", Object.assign({ set: r.id, on: !r.enabled }, signed()));
    say(r.label + (r.enabled ? " turned off." : " turned on."), "good");
    await again();
  }));
  const run = r.run && r.available ? button("Run now", { icon: "play", kind: "small quiet", key: "ito-evrun:" + r.id,
    "data-control": r.source === "gnomon" ? "evals_run" : "evals_roles_run", aria: "Run " + r.label + " now" }) : null;
  if (run) run.addEventListener("click", () => act(tools, async () => {
    if (!needPerson()) return;
    await api(r.run.method, r.run.path, Object.assign({}, r.run.body || {}, signed()));
    say(r.label + " started: its result shows here and on Health when it is done.", "info");
  }));
  tools.append(...[toggle, run].filter(Boolean));
  return h("li", { class: "ito-row", "data-set": r.id },
    h("div", { class: "ito-top" }, h("b", { "data-ud": "" }, r.label), chip(r.source === "gnomon" ? "neutral" : "info", r.source === "gnomon" ? "folder" : "layers",
      r.source === "gnomon" ? "Per project" : "Platform-wide"), r.enabled ? chip("good", "check", "On here") : null,
      r.available ? null : chip("nm", "dashed", "Cannot run here"), trend(r.trend || [], r.unit)),
    line("info", datum(r.what), "muted"),
    r.available ? null : line("alert", datum(r.why_not || ""), "muted"),
    tools);
}

function evalsCard(pid, data, again) {
  const v = data.evalsets;
  const rows = v.sets;
  return card({ title: "Eval sets", icon: "flask", id: "ito-evals", info: "Gnomon's audits, benchmarks and evals run on one project, so each is turned on per project and runs on its schedule on Health. Rihma's role evals judge the models behind Rihma's own roles, so their results are platform-wide; a project turns one on to run it with its own rules and see its trend here." },
    h("div", { "data-control": "itops_evalsets" }, h("p", { class: "small", "data-ud": "" }, v.line + ". " + (v.gnomon.gnomon ? "Gnomon " + (v.gnomon.version || "") + " is on this machine." : "Gnomon is not on this machine: its sets say so.")),
      rows.length ? h("ul", { class: "ito-list" }, rows.map((r) => evalRow(pid, r, again)))
        : emptyState("itops", null, { icon: "flask", what: "No eval set.", how: "Gnomon's sets appear once Gnomon is installed; Rihma's role evals are always listed." })));
}

// -- suggested automations ----------------------------------------------------------------------------------------

function suggestCard(pid, data, again) {
  const rows = data.suggestions;
  const body = rows.length ? h("ul", { class: "ito-list" }, rows.map((s) => {
    const accept = s.state === "offered" ? button("Set it up", { icon: "check", kind: "small", key: "ito-sg:" + s.id,
      "data-control": "automations_suggest_accept", aria: "Set up: " + s.label }) : null;
    if (accept) accept.addEventListener("click", () => act(accept.parentElement, async () => {
      if (!needPerson()) return;
      const out = await api("POST", "/api/projects/" + enc(pid) + "/automation-suggestions/" + enc(s.id) + "/accept", signed());
      say("Automation " + out.automation.id + " set up.", "good");
      await again();
    }));
    return h("li", { class: "ito-row", "data-suggestion": s.id },
      h("div", { class: "ito-top" }, h("b", { "data-ud": "" }, s.label),
        s.state === "set_up" ? chip("good", "check", "Set up") : s.state === "dismissed" ? chip("neutral", "x", "Dismissed")
          : s.state === "unavailable" ? chip("nm", "dashed", "Not available here") : chip("info", "sparkles", "Suggested")),
      line("info", datum(s.reason), "muted"), s.why ? line("alert", datum(s.why), "muted") : null,
      h("div", { class: "btns" }, accept));
  })) : emptyState("itops", null, { icon: "sparkles", what: "No automation to suggest from IT's side yet.",
    how: "Suggestions appear when the project serves https, declares a database or an integration, has IT checks, or is an ML pipeline or an agent." });
  return card({ title: "Automations IT would set up", icon: "sparkles", id: "ito-suggest", info: "From what this project runs: a weekly certificate check, a nightly database probe, an alert when an integration fails, a weekly round of the IT checks, eval sets for drift. Each is set up in your name; all of a project's suggestions are on its Automations tab." },
    body, h("p", { class: "small" }, h("a", { href: link(pid, "automations"), "data-key": "ito-autos" }, "Open Automations")));
}

// -- the project's view --------------------------------------------------------------------------------------------

async function draw(box, pid) {
  const [data, health] = await Promise.all([api("GET", base(pid)), api("GET", "/api/projects/" + enc(pid) + "/checks")]);
  if (!box.isConnected && box.dataset.drawn) return;
  box.dataset.drawn = "1";
  const again = () => draw(box, pid).catch((e) => say(e.message, "critical"));
  fill(box, h("div", { class: "q" }, h("h2", { id: "view-title", tabindex: "-1" }, "IT checks"),
    h("p", null, pick("What IT keeps an eye on for this project, and why: whether it answers, its certificates, its database, the systems it connects, its scheduled jobs, its models and its AI helpers.",
      "Infrastructure checks for what this project runs (app, TLS, DNS, database, integrations, jobs, ML, agents), proposed by its solution type, with eval sets and any assessment on demand.")),
    h("div", { class: "btns" }, askButton(ASK_SET, "ito-ask"))),
  typesCard(pid, data, again), setCard(pid, data, health.catalogue || [], again), assessCard(pid, data),
  evalsCard(pid, data, again), suggestCard(pid, data, again));
}

export function render(p) {
  const pid = p.meta.id;
  const box = h("div", { class: "ito-view" }, h("p", { class: "muted" }, "Reading what IT checks here…"));
  draw(box, pid).catch((e) => { if (box.isConnected) fill(box, empty("alert", e.message, askButton(ASK_SET, "ito-ask-err"))); });
  return box;
}

// -- small cards elsewhere ---------------------------------------------------------------------------------------

// Health and Integrations and data: the set in a line, with a link to the IT checks view.
export function itopsCard(pid) {
  const box = h("div", { class: "ito-mini", "data-key": "ito-mini" });
  api("GET", base(pid)).then((data) => {
    if (!box.isConnected && box.dataset.drawn) return;
    box.dataset.drawn = "1";
    const s = data.set;
    fill(box, card({ title: "IT checks", icon: "pulse", id: "ito-mini-card" },
      h("p", { class: "small", "data-ud": "" }, s.line + "."),
      s.types.length ? h("p", { class: "small muted" }, "For: " + s.types.map((t) => t.label).join(", ")) : null,
      h("div", { class: "btns" }, h("a", { class: "btn small", href: link(pid, "itops"), "data-key": "ito-open" }, icon("arrow-right"),
        h("span", { class: "lbl" }, s.missing.length ? "Turn on " + plural(s.missing.length, "IT check") : "Open IT checks")))));
  }).catch(() => fill(box));
  return box;
}

// The platform's Integrations and data page: what IT checks by solution type, and changing a default.
export function itopsPlatformCard() {
  const box = h("div", { class: "ito-platform", "data-control": "itops_defaults" }, card({ title: "What IT checks, by solution type", icon: "pulse", id: "ito-defaults" }, h("p", { class: "muted" }, "Loading…")));
  const draw2 = async () => {
    const data = await api("GET", "/api/itops");
    const d = data.defaults;
    const type = h("select", { id: "ito-def-type", "aria-label": "Solution type" }, d.types.map((t) => h("option", { value: t.id }, t.label)));
    const check = h("input", { type: "text", id: "ito-def-check", class: "input small", placeholder: "a check, such as tls", "aria-label": "Check" });
    const action = h("select", { id: "ito-def-action", "aria-label": "Change" }, [["add", "Add for every project of the type"], ["remove", "Take away for every project of the type"], ["reset", "Back to Rihmasto's default"]].map(([v, l]) => h("option", { value: v }, l)));
    const save = button("Change the default", { icon: "check", kind: "small", key: "ito-def-save", "data-control": "itops_default_change" });
    save.addEventListener("click", () => act(save.parentElement, async () => {
      if (!needPerson()) return;
      await api("POST", "/api/itops/defaults", Object.assign({ type: type.value, check: check.value.trim(), action: action.value }, signed()));
      say("The platform default changed: every project of the type follows it, unless it has its own change.", "good");
      await draw2();
    }));
    fill(box, card({ title: "What IT checks, by solution type", icon: "pulse", id: "ito-defaults", info: "The platform default for each solution type: Rihmasto's, or IT's change to it, which every project of that type follows unless the project has its own change." },
      h("ul", { class: "ito-list" }, d.types.map((t) => h("li", { class: "ito-row", "data-type": t.id },
        h("div", { class: "ito-top" }, h("b", null, t.label), scopeChip(t.scope)),
        t.checks.length ? h("p", { class: "small" }, t.checks.map((c, i) => [i ? ", " : "", h("span", { class: "mono" }, c.check), c.added_by_it ? " (IT)" : ""]))
          : line("info", datum(t.none || "No check."), "muted"),
        t.removed.length ? h("p", { class: "small muted" }, "Taken away by IT: " + t.removed.join(", ")) : null))),
      d.projects.length ? h("details", { class: "ito-more" }, h("summary", null, "Each project's IT checks"),
        h("ul", { class: "ito-list" }, d.projects.map((p) => h("li", { class: "ito-row", "data-pid": p.project },
          h("a", { href: link(p.project, "itops"), "data-ud": "" }, p.title || p.project), " ",
          p.overridden ? scopeChip("project override") : null, h("p", { class: "small muted", "data-ud": "" }, p.line))))) : null,
      h("details", { class: "ito-more" }, h("summary", null, "Change a platform default"), h("div", { class: "ito-add" }, type, check, action, save))));
  };
  draw2().catch((e) => fill(box, card({ title: "What IT checks, by solution type", icon: "pulse", id: "ito-defaults" }, empty("alert", e.message))));
  return box;
}

// Agent operations: the eval sets' trends, for one project or every project.
export function evalTrendsCard(pid) {
  const box = h("div", { class: "ito-trends", "data-control": "itops_evalsets" });
  api("GET", pid ? base(pid) + "/evalsets" : "/api/itops/evalsets").then((data) => {
    if (!box.isConnected && box.dataset.drawn) return;
    box.dataset.drawn = "1";
    const rows = data.trends;
    fill(box, card({ title: "Eval sets over time", icon: "flask", id: "ito-trends", info: "Each eval set turned on (or that ran) and its last results, oldest first: Gnomon's per project, Rihma's role evals platform-wide." },
      rows.length ? h("ul", { class: "ito-list" }, rows.map((r) => h("li", { class: "ito-row", "data-set": r.set },
        h("div", { class: "ito-top" }, h("b", { "data-ud": "" }, r.label), pid ? null : h("a", { href: link(r.project, "itops"), "data-ud": "", class: "small" }, r.title),
          chip("neutral", "layers", r.scope === "per project" ? "Per project" : "Platform-wide"), trend(r.trend, r.unit),
          r.latest ? verdict(r.latest.verdict || "not measured") : null))))
        : emptyState("agentops", null, { icon: "flask", what: "No eval set has run yet.",
          how: "Turn an eval set on in a project's IT checks, or run one from Health: its results show here over time." })));
  }).catch(() => fill(box));
  return box;
}

void S;
