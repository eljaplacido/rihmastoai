/* Rihmasto's structure (kernel/structure_policy.py, FR-STR1): for each of Rihmasto's own conventions, Off, Advise or
   Enforce, on an adopted or attached project's Alignment view and, for every project, in Settings. Advise is the
   default for a project that came with its own structure: Rihmasto takes that structure as given, shows what its
   conventions would add as folded suggestions and never counts them. Enforce makes them decisions to make, with an
   Inbox card; Off hides them with a count and why. Each row says where its level comes from (this project, all
   projects or Rihmasto's default), with the level for all projects beside it and the reason recorded. Preview says
   what moves before Save; every Save is signed with the person's reason. Ask Rihma proposes the same change. */

import { h, fill, icon, chip, api, enc, card, button, say, plural, signed, needPerson, act, ago, AuthError,
  mayAct, PROPOSALS } from "./core.js";
import { pick, datum, scopeWord as baseScopeWord } from "./words.js";

const LEVELS = ["off", "advise", "enforce"];
const levelWord = (l) => pick({ off: "Off: hide it", advise: "Advise: a suggestion", enforce: "Enforce: a decision" }[l],
  { off: "Off", advise: "Advise", enforce: "Enforce" }[l]) || l;
const LEVEL_TONE = { off: "neutral", advise: "info", enforce: "warning" };
const LEVEL_ICON = { off: "pause", advise: "info", enforce: "shield" };
// The scope wording is the scope table's (words.js scopeWord, kernel/scope_table.py): this project, this team, the shipped default.
const scopeWord = (s) => baseScopeWord(s);
const KIND_WORD = { own: ["Projects with their own structure", "Adopted or attached projects"],
  built: ["Projects Rihmasto builds", "Built by Rihmasto"] };
// Each convention in a business reader's words; a developer reads the kernel's own name.
const PLAIN = { test_trace: "Each test says which requirement it checks", criteria: "Each requirement has checks written as given, when, then",
  task_links: "Each task names the checks it serves", decisions: "Decisions are written down", api_contracts: "Each interface the product offers is described in a file",
  commit_hygiene: "Each change to the code is small and says what it is for", layout: "The code folder has a README and named owners" };
export const conventionWord = (r) => (pick(PLAIN[r.id] || null, null) || datum(r.label));
const ROW = { display: "flex", flexWrap: "wrap", alignItems: "center", gap: "6px 8px", margin: "8px 0" };
const LABEL = { flex: "1 1 220px", minWidth: "0", margin: "0" };
const SELECT = { flex: "0 1 230px", minWidth: "0", maxWidth: "100%", width: "auto" };

export function levelChip(level) { return chip(LEVEL_TONE[level] || "neutral", LEVEL_ICON[level] || "info", levelWord(level)); }

async function ask(question) {
  const { openAssistant, send } = await import("./assistant.js");
  openAssistant();
  send(question);
}

function said(why) {
  if (!why || (!why.reason && !why.person)) return null;
  return h("p", { class: "small muted st-why" }, "Set by " + (why.person || "a person") + (why.at ? " " + ago(why.at) : "") + ": ",
    datum(why.reason || "no reason given"));
}

// One convention: its name (what it asks in the tip), the level chosen, where the level comes from, what it finds.
function rowOf(r, project, state) {
  const id = "st-" + (project ? "p" : "f-" + r.kind) + "-" + r.id;
  const orig = project && r.scope !== "project" ? "inherit" : project ? r.level : (r.scope === "platform" ? r.level : "inherit");
  const inherit = project ? pick("As for all projects: ", "Platform: ") + levelWord(r.platform.level)
    : pick("Rihmasto's default: ", "Default: ") + levelWord(r.kind === "built" ? "enforce" : "advise");
  const sel = h("select", { id, "data-key": id, "aria-label": pick(PLAIN[r.id] || r.label, r.label), style: SELECT },
    [["inherit", inherit]].concat(LEVELS.map((l) => [l, levelWord(l)])).map(([v, t]) => h("option", { value: v, selected: v === orig || null }, t)));
  state.push({ sel, id: r.id, orig });
  return h("li", { class: "st-row", "data-convention": r.id, "data-level": r.level },
    h("div", { style: ROW },
      h("label", { for: id, style: LABEL }, h("b", null, conventionWord(r)), h("span", { class: "small muted" }, " " + pick("asks that ", "asks: "), datum(r.asks))),
      sel,
      chip(r.scope === "project" ? "accent" : "neutral", r.scope === "project" ? "folder" : "layers", scopeWord(r.scope), { "data-scope": r.scope }),
      r.found !== undefined ? chip(r.found ? "info" : "good", r.found ? "list" : "check-circle", plural(r.found, "finding") + " now") : null),
    h("p", { class: "small muted" }, pick("What follows it here: ", "Follows: "), datum(r.follows)),
    project && r.scope === "project" ? h("p", { class: "small muted" }, pick("All projects: ", "Platform: ") + levelWord(r.platform.level)) : null,
    said(r.why));
}

function previewList(out) {
  return h("ul", { class: "plain st-lines", "data-key": "st-preview" }, out.lines.map((l) => h("li", null, icon("arrow-right"), " ", datum(l))));
}

/* The editor for ``project`` (null: the platform, for one ``kind`` of project). ``again`` redraws after a save. */
function editor(rows, setters, project, kind, again) {
  const state = [];
  const may = mayAct(setters);
  const key = project ? "p" : "f-" + kind;
  const reason = h("input", { id: "st-reason-" + key, "data-key": "st-reason-" + key, autocomplete: "off", "aria-required": "true",
    placeholder: pick("Why, in a few words (kept with the change)", "Reason (recorded with the change)") });
  const out = h("div", { class: "st-out", role: "status", "aria-live": "polite" });
  const levels = () => Object.fromEntries(state.filter((x) => x.sel.value !== x.orig).map((x) => [x.id, x.sel.value]));
  const body = () => Object.assign({ levels: levels(), reason: reason.value.trim() }, project ? { project } : { kind });
  // The preview shown is for one choice of levels: a Save writes only that choice, once its impact was on screen (FR-STR2).
  let previewed = null;
  const SAVE_WORD = "Save";
  const CONFIRM_WORD = pick("Save this change", "Confirm and save");
  const label = (t) => { save.querySelector(".lbl").textContent = t; };
  const showPreview = async () => {
    if (!Object.keys(levels()).length) { fill(out, h("p", { class: "small muted" }, "Nothing changed yet: choose a level first.")); return null; }
    const res = await api("POST", "/api/structure/preview", Object.assign(body(), signed()));
    fill(out, previewList(res));
    previewed = JSON.stringify(levels());
    label(CONFIRM_WORD);
    return res;
  };
  const prev = button("Preview", { icon: "eye", kind: "small", key: "st-preview-" + key, "data-control": "structure_preview",
    onclick: () => act(prev.parentNode, showPreview) });
  const save = button(SAVE_WORD, { icon: "check", kind: "small primary", key: "st-save-" + key, disabled: !may || null,
    "data-control": "structure_policy",
    onclick: () => act(save.parentNode, async () => {
      if (!needPerson()) return;
      if (!Object.keys(levels()).length) { say("Nothing changed yet: choose a level first.", "warning"); return; }
      if (!reason.value.trim()) {
        say(pick("Say why first, in a few words: it is kept with the change.", "Give a reason first: it is recorded with the change."), "warning");
        reason.focus();
        return;
      }
      if (previewed !== JSON.stringify(levels())) {          // the impact first; the next click saves it
        await showPreview();
        say(pick("Here is what changes. Save again to make it.", "Preview shown: confirm to save."), "info");
        return;
      }
      const b = body();
      const res = await api("PUT", project ? "/api/projects/" + enc(project) + "/structure" : "/api/structure", Object.assign(b, signed()));
      say(plural(res.changes.length, "convention") + " changed, signed and recorded.", "good");
      await again();
    }) });
  // A changed choice needs its own preview before it is saved.
  const stale = () => { if (previewed !== null && previewed !== JSON.stringify(levels())) { previewed = null; fill(out); label(SAVE_WORD); } };
  const node = h("div", { class: "st-editor" },
    h("ul", { class: "plain st-rows" }, rows.map((r) => rowOf(r, project, state))),
    h("div", { class: "field" }, h("label", { for: reason.id }, pick("Why", "Reason")), reason),
    h("div", { class: "btns" }, prev, save, may ? null : h("span", { class: "muted small" }, icon("user"),
      " A business owner, product owner, developer or IT sets these.")), out);
  state.forEach((x) => x.sel.addEventListener("change", stale));
  return node;
}

// On an adopted or attached project's Alignment view: the levels for this project, and what each finds now.
export function structureCard(pid, onSaved) {
  const holder = h("div", { class: "st-holder", "data-control": "structure_policy" }, h("p", { class: "muted small" }, "Reading Rihmasto's structure…"));
  const again = async () => { if (onSaved) await onSaved(); else await draw(); };
  const draw = () => api("GET", "/api/projects/" + enc(pid) + "/structure").then((d) => {
    if (!d.applies) { fill(holder); return; }
    const own = d.kind === "own";
    fill(holder, card({ title: pick("How much of Rihmasto's own way to ask for", "Rihmasto's structure"), icon: "layers", id: "st-card",
      info: "Rihmasto has conventions of its own. A project that came with its own structure keeps it: by default each convention "
        + "only advises (a suggestion, never counted, no card). Enforce makes it a decision with an Inbox card; Off hides what it finds.",
      tools: h("span", { class: "btns" }, button(pick("Am I just following Rihmasto's way?", "Am I just conforming?"), { icon: "bot", kind: "small quiet",
        key: "st-ask", onclick: () => ask("Am I just conforming to Rihmasto or moving development?") })) },
    h("p", { class: "small" }, own
      ? pick("This project came with its own structure, and Rihmasto takes it as given. Choose where Rihmasto's own conventions should only "
        + "suggest, where they should be enforced, and where they should stay out of the way.",
      "Adopted or attached: the project's own structure is taken as given. Per convention: Off (hidden), Advise (a suggestion, not "
        + "counted) or Enforce (counted, an Inbox card, named at the repo gate).")
      : pick("Rihmasto builds this project, so its conventions are this project's own structure.",
        "Built by Rihmasto: its conventions are enforced by default.")),
    editor(d.rows, d.meta.setters, pid, d.kind, again),
    (d.history || []).length ? h("details", { class: "as-more" }, h("summary", null, plural(d.history.length, "change") + " recorded"),
      h("ul", { class: "plain small" }, d.history.map((x) => h("li", null, ago(x.at) + ", " + (x.person || "a person") + ": ",
        datum((x.changes || []).map((c) => c.label + " " + c.from + " to " + c.to).join("; ") + (x.reason ? " (" + x.reason + ")" : "")))))) : null));
  }).catch((e) => { if (!(e instanceof AuthError)) fill(holder, h("p", { class: "note warning" }, icon("alert"), h("span", null, e.message))); });
  draw();
  return holder;
}

// In Settings: the levels for every project, one block per kind of project.
export function structureSettingsCard() {
  const holder = h("div", { class: "st-holder", id: "st-platform", "data-control": "structure_policy" });
  const again = () => api("GET", "/api/structure").then((d) => fill(holder, card({ title: pick("Rihmasto's own way: all projects", "Rihmasto's structure: platform"),
    icon: "layers", id: "st-plat", info: "The level each of Rihmasto's conventions starts at. A project may set its own on its Alignment view; its row then says so." },
  h("p", { class: "small" }, pick("Projects that came with their own structure keep it: Rihmasto only advises there unless you choose otherwise.",
    "Defaults: Advise for adopted or attached projects, Enforce for projects Rihmasto builds.")),
  ["own", "built"].map((k) => h("div", { class: "st-kind", "data-kind": k }, h("h4", null, pick(KIND_WORD[k][0], KIND_WORD[k][1])),
    editor(d.kinds[k], d.meta.setters, null, k, again))))))
    .catch((e) => { if (!(e instanceof AuthError)) fill(holder, h("p", { class: "note warning" }, icon("alert"), h("span", null, e.message))); });
  again();
  return holder;
}

/* The Alignment's summary of what the items are: Rihmasto taking in the project's own structure, facts about its own
   files, and Rihmasto's own conventions at their levels; and how many are left to decide. */
export function alignSplit(a) {
  const p = a.policy;
  if (!p) return null;
  const s = p.split;
  const b = p.by_level;
  const part = (n, label, tone, ic, key) => h("li", { class: "st-part", "data-part": key }, chip(tone, ic, String(n)), " ", label);
  return h("div", { class: "st-split", "data-key": "st-split" },
    h("p", { class: "small", "data-key": "st-line" }, datum(p.line)),
    h("ul", { class: "plain st-parts", style: { display: "flex", flexWrap: "wrap", gap: "6px 16px" } },
      part(s.take_in, pick("taken in from the project's own files", "taking in your structure"), "accent", "download", "take_in"),
      s.own ? part(s.own, pick("about the project's own files", "facts about your files"), "neutral", "info", "own") : null,
      part(s.conform, pick("Rihmasto's own conventions", "Rihmasto's conventions") + " (" + [b.enforce ? b.enforce + " enforced" : null,
        b.advise ? b.advise + " suggestions" : null, b.off ? b.off + " hidden" : null].filter(Boolean).join(", ") + ")", "info", "layers", "conform"),
      part(p.to_decide, pick("yours to decide", "to decide"), p.to_decide ? "warning" : "good", "dashed", "to_decide"),
      p.older ? part(p.older, pick("of the project's own from files older than the code", "sources older than the newest code"),
        "warning", "alert", "older") : null));
}

// -- Ask Rihma's proposal: the same signed route a Save calls --------------------------------------------------

Object.assign(PROPOSALS, {
  structure_set: { words: ["Change Rihmasto's structure", "layers"],
    describe: (a) => [(a.project ? "For project " + a.project : "For all projects with their own structure") + ": "
      + Object.entries(a.levels || {}).map(([c, l]) => c.replace(/_/g, " ") + " " + (l === "inherit" ? "as for all projects" : l)).join(", ")
      + (a.reason ? ". Reason: " + a.reason : "")],
    call: (a) => api("PUT", a.project ? "/api/projects/" + enc(a.project) + "/structure" : "/api/structure",
      Object.assign({ levels: a.levels || {}, reason: a.reason || "" }, a.project ? {} : { kind: a.kind || "own" }, signed())) },
});
