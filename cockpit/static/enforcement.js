/* Enforcement: how strictly Rihmasto holds development, testing and production (kernel/enforcement.py, FR-ENF1).
   A project's view in the Govern capsule and a card in Settings for every project. Each cell (an environment and a
   check family) has a level: off, advise (a note and a nudge), require review (a card for the named reviewer) or
   enforce (the work waits until they decide), and says where it comes from: this project, all projects, or
   Rihmasto's default. Preview says what a change would do before it is saved; every save is signed and recorded.
   The project's GitHub environments and branch protection are read on request, never written, and shown beside
   Rihmasto's levels: where the two agree, and where one is stricter. Ask Rihma proposes the same changes. */

import { S, h, fill, icon, chip, api, enc, card, button, say, plural, signed, needPerson, act, ago, AuthError, nav,
  mayAct, mayChoose, heldPersonas, personaLabel, PROPOSALS } from "./core.js";
import { placesCard, protectionLine, placedNote } from "./enforcement_places.js";
import { pick, datum, emptyState } from "./words.js";

const ENVS = ["dev", "test", "prod"];
const FAMILIES = ["quality", "security", "legal", "governance"];
const LEVELS = ["off", "advise", "require_review", "enforce"];
const ENV_WORD = { dev: "Development", test: "Testing", prod: "Production" };
const FAMILY_WORD = { quality: "Quality", security: "Security", legal: "Legal", governance: "Governance" };
const levelWord = (l) => pick({ off: "Off", advise: "Advise", require_review: "Ask for a review", enforce: "Hold until decided" }[l],
  { off: "Off", advise: "Advise", require_review: "Require review", enforce: "Enforce" }[l]) || l;
// A preset's short name on its button; its tooltip says it whole (kernel/enforcement.py PRESETS).
const PRESET_WORD = { advise: "Advise everywhere", split: "The split", strict: "Strict" };
const LEVEL_TONE = { off: "neutral", advise: "info", require_review: "warning", enforce: "critical" };
const LEVEL_ICON = { off: "pause", advise: "info", require_review: "eye", enforce: "shield" };
const OUTCOME = { passed: ["good", "check-circle", "Went on"], cleared: ["good", "check-circle", "Approved, went on"],
  noted: ["info", "info", "Noted"], review: ["warning", "eye", "Review asked"], refused: ["critical", "stop", "Held"] };
const scopeWord = (s) => pick({ project: "This project", platform: "All projects", default: "Rihmasto's default" }[s],
  { project: "Project", platform: "Platform", default: "Default" }[s]) || s;

async function ask(question) {
  const { openAssistant, send } = await import("./assistant.js");
  openAssistant();
  send(question);
}
function askButton(question, key) {
  return button("Ask Rihma why and how", { icon: "bot", kind: "small quiet", key: "enf-ask:" + key, "data-control": "enforcement_ask", onclick: () => ask(question) });
}
function levelChip(level) { return chip(LEVEL_TONE[level] || "neutral", LEVEL_ICON[level] || "info", levelWord(level)); }

// -- the levels editor: one for the platform, one per project ---------------------------------------------------

// One row per family: its name, its level, and where the level comes from; it wraps on a phone.
const ROW = { display: "flex", flexWrap: "wrap", alignItems: "center", gap: "6px 8px", margin: "6px 0" };
const LABEL = { flex: "0 0 92px", margin: "0" };
const SELECT = { flex: "1 1 150px", minWidth: "0", maxWidth: "100%", width: "auto" };
function selectFor(id, value, options, label) {
  return h("select", { id, "data-key": id, "aria-label": label, style: SELECT }, options.map(([v, text]) => h("option", { value: v, selected: v === value || null }, text)));
}

function envBlock(d, project, env, state) {
  const rows = FAMILIES.map((fam) => {
    const c = d.cells.find((x) => x.env === env && x.family === fam);
    const inherited = project ? (d.platform_levels || {})[env] || {} : {};
    const orig = project && c.scope !== "project" ? "inherit" : c.level;
    const opts = (project ? [["inherit", pick("As for all projects: ", "Platform: ") + levelWord(inherited[fam] || "advise")]] : [])
      .concat(LEVELS.map((l) => [l, levelWord(l)]));
    const sel = selectFor("enf-" + (project ? "p" : "f") + "-" + env + "-" + fam, orig, opts, ENV_WORD[env] + ", " + FAMILY_WORD[fam]);
    state.selects.push({ sel, env, fam, orig });
    return h("div", { class: "enf-row", style: ROW }, h("label", { for: sel.id, style: LABEL }, FAMILY_WORD[fam]), sel,
      chip(c.scope === "project" ? "accent" : "neutral", c.scope === "project" ? "folder" : "layers", scopeWord(c.scope), { "data-scope": c.scope }));
  });
  const strict = d.strictest[env];
  return h("div", { class: "enf-env", "data-env": env }, h("h4", null, ENV_WORD[env], " ", levelChip(strict)), rows);
}

function reviewerRow(d, project, state) {
  return h("div", { class: "enf-reviewers" }, h("h4", null, pick("Who reviews", "Reviewer per family")),
    FAMILIES.map((fam) => {
      const c = d.cells.find((x) => x.family === fam);
      const orig = project && c.reviewer_scope !== "project" ? "inherit" : c.reviewer;
      const opts = (project ? [["inherit", pick("As for all projects: ", "Platform: ") + personaLabel(c.reviewer)]] : [])
        .concat(d.meta.reviewers.map((r) => [r, personaLabel(r)]));
      const sel = selectFor("enf-r-" + (project ? "p" : "f") + "-" + fam, orig, opts, pick("Who reviews ", "Reviewer for ") + FAMILY_WORD[fam]);
      state.reviewers.push({ sel, fam, orig });
      return h("div", { class: "enf-row", style: ROW }, h("label", { for: sel.id, style: LABEL }, FAMILY_WORD[fam]), sel);
    }));
}

function changesOf(state) {
  const levels = {};
  const reviewers = {};
  state.selects.filter((x) => x.sel.value !== x.orig).forEach((x) => { (levels[x.env] = levels[x.env] || {})[x.fam] = x.sel.value; });
  state.reviewers.filter((x) => x.sel.value !== x.orig).forEach((x) => { reviewers[x.fam] = x.sel.value; });
  return { levels, reviewers };
}

function previewLines(out) {
  return [h("ul", { class: "plain enf-lines", "data-key": "enf-preview" }, out.lines.map((l) => h("li", null, datum(l)))),
    out.changes.length ? h("ul", { class: "plain enf-changes" }, out.changes.map((c) => h("li", null,
      h("b", null, ENV_WORD[c.env] + ", " + FAMILY_WORD[c.family] + ": "), levelWord(c.from) + " → " + levelWord(c.to) + ". ", datum(c.next)))) : null];
}

/* The editor for ``project`` (null: the platform). ``again`` redraws after a save. Returns the card and set(levels). */
function editor(d, project, again) {
  const state = { selects: [], reviewers: [] };
  const may = mayAct(d.setters);
  const reason = h("input", { id: "enf-reason-" + (project || "f"), "data-key": "enf-reason", placeholder: pick("Why (needed when you loosen a level)", "Reason (required when loosening)"), autocomplete: "off" });
  const out = h("div", { class: "enf-out", role: "status", "aria-live": "polite" });
  const body = () => Object.assign(changesOf(state), project ? { project } : {}, { reason: reason.value.trim() });
  const showPreview = async () => {
    const res = await api("POST", "/api/enforcement/preview", Object.assign(body(), signed()));
    fill(out, previewLines(res));
    return res;
  };
  const prev = button("Preview", { icon: "eye", kind: "small", key: "enf-preview-btn", "data-control": "enforcement_preview", onclick: () => act(prev.parentNode, showPreview) });
  const save = button("Save", { icon: "check", kind: "small primary", key: "enf-save", "data-control": project ? "enforcement_levels" : "enforcement_platform", disabled: !may || null,
    onclick: () => act(save.parentNode, async () => {
      if (!needPerson()) return;
      const b = body();
      if (!Object.keys(b.levels).length && !Object.keys(b.reviewers).length) { say("Nothing changed yet: choose a level first.", "warning"); return; }
      const res = await api("PUT", project ? "/api/projects/" + enc(project) + "/enforcement" : "/api/enforcement", Object.assign(b, signed()));
      say(plural(res.changes.length, "setting") + " changed, signed and recorded.", "good");
      await again();
    }) });
  const presets = h("div", { class: "btns enf-presets" }, h("span", { class: "small muted" }, pick("Start from:", "Preset:")),
    d.meta.presets.map((p) => button(PRESET_WORD[p.id] || p.label, { kind: "small quiet", tip: p.label, key: "enf-preset:" + p.id, onclick: () => act(presets, async () => {
      const lv = { advise: { dev: "advise", test: "advise", prod: "advise" }, split: { dev: "advise", test: "require_review", prod: "enforce" },
        strict: { dev: "require_review", test: "enforce", prod: "enforce" } }[p.id];
      state.selects.forEach((x) => { x.sel.value = lv[x.env]; });
      await showPreview();
    }) })));
  const node = h("div", { class: "enf-editor" }, presets,
    h("div", { class: "enf-grid", style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "12px" } },
      ENVS.map((e) => envBlock(d, project, e, state))),
    reviewerRow(d, project, state),
    h("div", { class: "field" }, h("label", { for: reason.id }, pick("Why", "Reason")), reason),
    h("div", { class: "btns" }, prev, save, may ? null : h("span", { class: "muted small" }, icon("user"), " A business owner, IT, compliance or a developer sets these.")), out);
  const set = async (levels) => {
    state.selects.forEach((x) => { const v = ((levels || {})[x.env] || {})[x.fam]; if (v) x.sel.value = v; });
    await showPreview();
  };
  return { node, set };
}

// -- the pipeline: read, never written ----------------------------------------------------------------------------

const STATE = { agree: ["good", "check-circle", "Agree"], pipeline_stricter: ["warning", "alert", "The pipeline is stricter"],
  rihmasto_stricter: ["warning", "alert", "Rihmasto is stricter"], unknown: ["nm", "dashed", "Nothing to compare"] };

function pipelineBody(pid, d, ed) {
  const pipe = d.pipeline;
  if (!pipe.read) {
    return [h("p", { class: "note warning" }, icon("alert"), h("span", null, "Not read: ", datum(pipe.why || "unknown"), ". ", datum(pipe.how + "."))),
      askButton("Why can Rihmasto not read the GitHub settings of this project, and how do I fix it?", "pipe")];
  }
  const cmp = d.compare || { rows: [] };
  const take = cmp.suggested ? button(pick("Take the pipeline's split", "Mirror the pipeline's split"), { icon: "merge", kind: "small", key: "enf-take", "data-control": "enforcement_take_pipeline",
    onclick: () => act(take.parentNode, async () => { await ed.set(cmp.suggested); say("The editor now holds the pipeline's split: check the preview, then Save.", "good"); }) }) : null;
  return [h("p", { class: "small" }, "Read from ", datum(pipe.repo), " (", datum(pipe.from), "), main line ", datum(pipe.branch), ", read only."),
    h("ul", { class: "plain enf-cmp" }, cmp.rows.map((r) => h("li", { "data-env": r.env, "data-state": r.state },
      h("b", null, ENV_WORD[r.env] + ": "), chip(...STATE[r.state]), " ", levelChip(r.rihmasto), " ",
      h("span", { class: "small" }, datum(r.pipeline_says)), h("p", { class: "small muted", "data-ud": "" }, r.todo)))),
    h("p", { class: "small" }, pick("Places it deploys to: ", "GitHub environments: "),
      pipe.environments.length ? datum(pipe.environments.map((e) => e.name + (e.required_reviewers ? " (" + plural(e.required_reviewers, "reviewer") + ")" : "")).join(", ")) : "none named"),
    placedNote(pipe.environments), protectionLine(pipe.protection || {}),
    h("div", { class: "btns" }, take, h("a", { class: "btn small quiet", href: pipe.url, target: "_blank", rel: "noopener noreferrer", "data-key": "enf-github" }, icon("external"), h("span", { class: "lbl" }, "Open the settings on GitHub")))];
}

function pipelineCard(pid, d, ed, again) {
  const holder = h("div", { class: "enf-pipe" }, d.pipeline ? pipelineBody(pid, d, ed)
    : h("p", { class: "small muted" }, pick("Rihmasto can read how your pipeline on GitHub holds each stage, and show where it agrees with the levels here. It reads only; it never changes them.",
      "Reads the GitHub environments and branch protection with gh (GET only) and compares them with these levels. Nothing is written to GitHub.")));
  const repo = h("input", { id: "enf-repo", "data-key": "enf-repo", value: d.repo || "", placeholder: "owner/name (read from the git remote when empty)", autocomplete: "off", spellcheck: "false" });
  const read = button("Read from GitHub", { icon: "refresh", kind: "small primary", key: "enf-read", "data-control": "enforcement_pipeline",
    onclick: () => act(read.parentNode, async () => {
      const out = await api("GET", "/api/projects/" + enc(pid) + "/enforcement?pipeline=1");
      fill(holder, pipelineBody(pid, out, ed));
    }) });
  const saveRepo = button(pick("Use this one", "Save the repository"), { icon: "check", kind: "small quiet", key: "enf-repo-save", "data-control": "enforcement_repo", disabled: !mayAct(d.setters) || null,
    onclick: () => act(saveRepo.parentNode, async () => {
      if (!needPerson()) return;
      await api("PUT", "/api/projects/" + enc(pid) + "/enforcement", Object.assign({ repo: repo.value.trim() }, signed()));
      say("Saved, signed and recorded.", "good");
      await again();
    }) });
  return card({ title: pick("Your pipeline on GitHub", "The project's pipeline"), icon: "merge", id: "enf-pipeline",
    info: "Rihmasto is a middle layer: your pipeline is taken as given. It reads the deployment environments and the main line's protection with your own GitHub sign-in and never writes them." },
  h("div", { class: "field" }, h("label", { for: "enf-repo" }, "GitHub"), repo), h("div", { class: "btns" }, read, saveRepo), holder);
}

// -- what happened ---------------------------------------------------------------------------------------------

/* Decide a review here, signed with the role it needs among those the person holds (working alone: every role), so
   a card for IT never waits unseen while the person looks as business owner (FR-ENF2). Approving one that holds
   work is an override: its reason is needed and recorded. */
function decideRow(pid, c, again) {
  const who = c.deciders || [];
  if (!(mayAct(who) || (mayChoose() && heldPersonas().some((p) => who.includes(p))))) {
    return h("p", { class: "small muted" }, "Waits on " + who.map(personaLabel).join(" or ") + ".");
  }
  const as = who.includes(S.persona) ? S.persona : who.find((p) => heldPersonas().includes(p));
  const why = h("input", { id: "enf-why-" + c.id, "data-key": "enf-why:" + c.id, autocomplete: "off", maxlength: "300",
    "aria-label": "Why, for " + c.id, placeholder: c.blocking ? pick("Why you let it go on (needed to approve)", "Reason (required to approve: an override)") : pick("Why (optional)", "Reason (optional)") });
  const row = h("div", { class: "enf-decide", style: ROW });
  const go = (verdict) => act(row, async () => {
    if (!needPerson()) return;
    if (verdict === "approve" && c.blocking && !why.value.trim()) {
      why.setAttribute("aria-invalid", "true");
      why.focus();
      say("Say why you let it go on: approving is an override, recorded with your reason.", "warning");
      return;
    }
    await api("POST", "/api/projects/" + enc(pid) + "/cards/" + enc(c.id) + "/decide",
      Object.assign(signed(), mayChoose() ? { as_needed: true } : {}, { persona: as, verdict, reason: why.value.trim() }));
    say(c.id + " decided as " + personaLabel(as) + ", signed with your name.", "good");
    await again();
  });
  fill(row, h("span", { class: "small" }, pick("You decide it as ", "Signed as ") + personaLabel(as) + ":"), why,
    button(pick("Let it go on", "Approve"), { icon: "check", kind: "small primary", key: "enf-approve:" + c.id, "data-control": "enforcement_decide", onclick: () => go("approve") }),
    button(pick("Keep it held", "Refuse"), { icon: "stop", kind: "small quiet", key: "enf-refuse:" + c.id, "data-control": "enforcement_decide", onclick: () => go("refuse") }));
  return row;
}

function reviewsCard(pid, d, again) {
  const rows = d.open_cards || [];
  return card({ title: pick("Reviews waiting", "Open review cards"), icon: "eye", id: "enf-reviews" },
    rows.length ? h("ul", { class: "plain enf-cards" }, rows.map((c) => h("li", { "data-card": c.id }, chip(c.blocking ? "critical" : "warning", c.blocking ? "stop" : "eye", c.blocking ? "Holds work" : "Review"), " ",
      h("span", { class: "mono" }, c.id), " ", datum(c.title), h("span", { class: "small muted" }, " · " + (c.deciders || []).map(personaLabel).join(", ")),
      decideRow(pid, c, again))))
      : emptyState("enforcement_reviews", askButton("When does Rihmasto ask for a review in this project?", "reviews"), { icon: "eye",
        what: pick("No review waits.", "No open review card."),
        how: pick("A review appears here when a stage is set to ask for one or to hold until decided, and something enters that stage.",
          "A card opens when a cell is require review or enforce and the guard finds something to say there.") }));
}

function outcomesCard(d) {
  const rows = d.recent || [];
  return card({ title: pick("What Rihmasto noticed", "Latest outcomes"), icon: "activity", id: "enf-outcomes" },
    rows.length ? h("ul", { class: "plain enf-recent" }, rows.slice(0, 15).map((r) => h("li", { "data-outcome": r.outcome },
      chip(...(OUTCOME[r.outcome] || OUTCOME.noted)), " ", h("b", null, ENV_WORD[r.env] + ", " + FAMILY_WORD[r.family]), " · ", datum(r.subject),
      h("span", { class: "small muted" }, " · " + levelWord(r.level) + " · " + ago(r.at) + (r.card ? " · " + r.card : "")),
      r.override ? h("p", { class: "small" }, "Approved by ", datum(r.override.by || "?"), r.override.reason ? [": ", datum(r.override.reason)] : null) : null)))
      : emptyState("enforcement_recent", askButton("What will Rihmasto note here, and when?", "recent"), { icon: "activity",
        what: pick("Nothing has entered a stage yet.", "No outcome recorded yet."),
        how: pick("Each time a change is checked, a release goes to testing or production, or an automation changes something, what the level said is noted here.",
          "The repo gate, the deploy step and changing automations ask the guard; each outcome lands in the project's ledger and here.") }));
}

function findingsCard(d) {
  const items = FAMILIES.flatMap((f) => (d.findings[f] || []).map((x) => [f, x]));
  return card({ title: pick("Open findings", "Open findings by family"), icon: "alert", id: "enf-findings" },
    items.length ? h("ul", { class: "plain" }, items.map(([f, x]) => h("li", null, h("b", null, FAMILY_WORD[f] + ": "), datum(x))))
      : emptyState("enforcement_findings", h("a", { class: "btn small", href: "#/p/" + enc(d.project) + "/checks", "data-key": "enf-checks" }, icon("pulse"), h("span", { class: "lbl" }, "Open Health")), { icon: "check-circle",
        what: "No open finding.", how: pick("A failed check in Health (tests, security, licences and more) shows here and counts for its family.",
          "A failed check's latest result is a finding of its family (tests, ci, probe: quality; secrets, dependencies: security; licences, sbom: legal).") }));
}

function historyCard(d) {
  const rows = d.history || [];
  if (!rows.length) return null;
  return card({ title: pick("Changes to these levels", "Level changes"), icon: "clock", id: "enf-history" },
    h("ul", { class: "plain" }, rows.map((r) => h("li", { class: "small" }, datum(r.person), " · " + ago(r.at) + " · " + plural(r.changes.length, "change") + (r.preset ? " · " + r.preset : ""),
      r.reason ? [" · ", datum(r.reason)] : null))));
}

// -- the project's view --------------------------------------------------------------------------------------

function head() {
  return h("div", { class: "q" }, h("h2", { id: "view-title", tabindex: "-1" }, pick("How strict each stage is", "Enforcement")),
    h("p", null, pick("How Rihmasto holds development, testing and production for this project. It advises by default; it holds work only where you turn that on.",
      "Levels per environment and check family: off, advise, require review, enforce. Advise is the default; nothing is enforced until a person sets it.")));
}

export function render(p) {
  const pid = p.meta.id;
  const box = h("div", { class: "enf-view" }, head(), h("p", { class: "muted" }, "Reading…"));
  const again = () => draw(box, pid).catch((e) => { if (!(e instanceof AuthError)) fill(box, head(), h("p", { class: "note warning" }, icon("alert"), h("span", null, e.message)), askButton("Why does the Enforcement view not open, and what do I do?", "err")); });
  again();
  return box;
}

async function draw(box, pid) {
  const d = await api("GET", "/api/projects/" + enc(pid) + "/enforcement");
  if (!box.isConnected) return;
  const again = () => draw(box, pid);
  if (!d.applies) { fill(box, head(), emptyState("enforcement", null, { what: d.why, how: "Open a project to set its own levels, or Settings for all projects." })); return; }
  const ed = editor(d, pid, again);
  fill(box, head(), h("div", { class: "btns enf-summary" }, ENVS.map((e) => h("span", { "data-env": e }, ENV_WORD[e] + " ", levelChip(d.strictest[e])))),
    card({ title: pick("Levels for this project", "Levels"), icon: "shield", id: "enf-levels", dataId: "enforcement_levels",
      info: "Each cell says where it comes from: this project, all projects, or Rihmasto's default. Advise notes and nudges; ask for a review opens a card for the named role; hold until decided keeps the work waiting until they decide." },
    h("div", { "data-control": "enforcement_levels" }, ed.node)), reviewsCard(pid, d, again), pipelineCard(pid, d, ed, again), placesCard(pid, d, again),
    outcomesCard(d), findingsCard(d), historyCard(d));
  if (nav.refreshShell) nav.refreshShell();
}

// -- Settings: all projects ------------------------------------------------------------------------------------

export function enforcementSettingsCard() {
  const holder = h("div", { class: "enf-settings-holder" });
  const again = () => api("GET", "/api/enforcement").then((d) => fill(holder, settingsCard(d, again)))
    .catch((e) => { if (!(e instanceof AuthError)) fill(holder, h("p", { class: "note warning" }, icon("alert"), h("span", null, e.message))); });
  again();
  return holder;
}

function settingsCard(d, again) {
  const ed = editor(d, null, again);
  const own = d.overriding || [];
  return card({ title: pick("How strict each stage is: all projects", "Enforcement levels: platform"), icon: "shield", id: "enf-platform", dataId: "enforcement_platform",
    info: "The levels every project starts from. A project may set its own for any cell; its view says which cells are its own." },
  h("p", { class: "small" }, pick("Development, testing and production, for every project that has not set its own. Rihmasto advises by default.",
    "Per environment and check family, for every project without its own cell. Default: advise.")),
  h("div", { "data-control": "enforcement_platform" }, ed.node), own.length ? h("p", { class: "small", "data-key": "enf-own" }, plural(own.length, "project") + " set their own: ",
    own.map((o, i) => [i ? ", " : "", h("a", { href: "#/p/" + enc(o.project) + "/enforcement" }, datum(o.title)), " (" + o.cells.join(", ") + ")"])) : null,
  historyCard(d));
}

// -- Ask Rihma's proposal: the same signed route a Save calls --------------------------------------------------

Object.assign(PROPOSALS, {
  enforcement_levels_set: { words: ["Change how strict a stage is", "shield"],
    describe: (a) => [(a.project ? "For project " + a.project : "For all projects") + ": " + (a.preset ? "the " + a.preset + " preset"
      : Object.entries(a.levels || {}).map(([e, row]) => ENV_WORD[e] + " " + Object.entries(row).map(([f, l]) => f + " " + levelWord(l)).join(", ")).join("; "))
      + Object.entries(a.names || {}).map(([n, e]) => "; " + n + " counts as " + (ENV_WORD[e] || e)).join("")
      + (a.gate_env ? "; the gate's changes enter " + (ENV_WORD[a.gate_env] || a.gate_env) : "")
      + (a.reason ? ". Your reason: " + a.reason : "")],
    // The person's own reason, from their words (kernel/enforcement_chat.py); loosening without one is refused (FR-ENF2).
    call: (a) => api("PUT", a.project ? "/api/projects/" + enc(a.project) + "/enforcement" : "/api/enforcement",
      Object.assign({ levels: a.levels || {}, preset: a.preset || null, reason: a.reason || "" },
        a.names ? { names: a.names } : {}, a.gate_env ? { gate_env: a.gate_env } : {}, signed())) },
});
