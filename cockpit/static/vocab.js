/* Vocabulary: Rihmasto's own words, by team and by project (kernel/vocab.py, kernel/vocab_edit.py, FR-TM2). Every kind of
   record, relation and attribute has a shipped word and meaning; a team may say it differently for all its projects and a
   project differently again. Each row shows the shipped meaning, the team's, the project's and which one is in force, with
   its scope as a chip (this project, this team, the shipped default) and, for a redefined term, "as defined on <date>" with
   who and why. A change is previewed first (how many records, nodes and views read differently; nothing stored is
   rewritten), signed with a reason and undone to the earlier reading exactly. IT changes a team's words; IT or the project's
   owner a project's; working alone the person holds every role, so it applies at once. Ask Rihma does the same by rule. */

import { h, fill, icon, chip, api, enc, card, button, say, plural, signed, needPerson, act, ago, AuthError, mayAct, nav,
  PROPOSALS } from "./core.js";
import { pick, datum, emptyState, scopeWord, setVocabulary } from "./words.js";
import { twoStep, teamField } from "./teams.js";
import { scopeCard } from "./applieswhere.js";

const ROW = { display: "flex", flexWrap: "wrap", alignItems: "center", gap: "6px 8px", margin: "8px 0" };
const GROW = { flex: "1 1 200px", minWidth: "0", margin: "0" };
const SCOPE_TONE = { project: "accent", team: "info", shipped: "neutral" };
const SCOPE_ICON = { project: "folder", team: "users", shipped: "layers" };
const TYPE_WORD = { kind: ["Kind of record", "Record kind"], rel: ["Relation", "Relation"], attr: ["Attribute", "Attribute"], custom: ["Your own term", "Custom term"] };
const failed = (holder) => (e) => { if (!(e instanceof AuthError)) fill(holder, h("p", { class: "note warning" }, icon("alert"), h("span", null, e.message))); };

let loaded = null;
/* The words in force for the page: a project's own, else the one team all projects share, else the shipped words. */
export async function syncVocabulary(pid, force) {
  const key = pid || "*";
  if (!force && !nav.vocabDirty && loaded === key) return;
  nav.vocabDirty = false;       // a project moved to another team reads in that team's words now (teams.js)
  try {
    setVocabulary(await api("GET", "/api/vocabulary?compact=1" + (pid && pid !== "_factory" ? "&project=" + enc(pid) : "")));
    loaded = key;
  } catch (e) { loaded = null; }
}
const reread = async (pid) => { await syncVocabulary(pid, true); if (nav.rerender) nav.rerender(); };

export const scopeChip = (scope) => chip(SCOPE_TONE[scope] || "neutral", SCOPE_ICON[scope] || "layers", scopeWord(scope), { "data-scope": scope, tip: scope === "shipped"
  ? "Rihmasto's own word and meaning." : scope === "team" ? "The team's word, for all its projects." : "This project's own word." });

// What a term's layers say: one line each, for the shipped meaning, the team's and the project's.
function layerLine(label, scope, e) {
  if (!e) return null;
  const said = [e.label ? "called " + e.label : null, e.description ? "described: " + e.description : null,
    e.synonyms && e.synonyms.length ? "also " + e.synonyms.join(", ") : null, e.hidden ? "hidden" : null, e.means ? "means " + e.means.replace("kind:", "") : null]
    .filter(Boolean).join("; ");
  return h("p", { class: "small", "data-layer": scope }, scopeChip(scope), " ", h("b", null, label + " "), datum(said || "as shipped"));
}

function edit(r, scope, owner, may, pid, again) {
  const mine = (scope === "project" ? r.project : r.team) || {};
  const id = "vc-" + r.id.replace(/[^a-z0-9]/g, "-");
  const label = h("input", { id: id + "-l", "data-key": id + "-label", value: mine.label || "", maxlength: "60", autocomplete: "off", placeholder: (r.shipped || {}).label || r.label,
    "aria-label": "Word for " + r.id });
  const desc = h("input", { id: id + "-d", "data-key": id + "-desc", value: mine.description || "", maxlength: "400", autocomplete: "off",
    placeholder: "What it means here", "aria-label": "Description of " + r.id });
  const syn = h("input", { id: id + "-s", "data-key": id + "-syn", value: (mine.synonyms || []).join(", "), autocomplete: "off",
    placeholder: pick("Other words Ask Rihma should find it by", "Synonyms (comma separated)"), "aria-label": "Synonyms of " + r.id });
  const hide = h("input", { type: "checkbox", id: id + "-h", "data-key": id + "-hide", checked: !!mine.hidden || null });
  const reason = h("input", { id: id + "-r", "data-key": id + "-reason", autocomplete: "off", maxlength: "300", "aria-required": "true",
    placeholder: pick("Why, in a few words (kept with the change)", "Reason (recorded)") , "aria-label": "Reason" });
  const owned = { [scope]: owner };
  const body = () => {
    const f = {};
    if (label.value.trim() !== (mine.label || "")) f.label = label.value.trim() || null;
    if (desc.value.trim() !== (mine.description || "")) f.description = desc.value.trim() || null;
    const list = syn.value.split(",").map((x) => x.trim()).filter(Boolean);
    if (list.join(",") !== (mine.synonyms || []).join(",")) f.synonyms = list.length ? list : null;
    if (hide.checked !== !!mine.hidden) f.hidden = hide.checked ? true : null;
    return Object.assign({ term: r.id }, owned, f);
  };
  const step = twoStep({ label: pick("Save", "Save"), key: id + "-save", control: scope === "project" ? "vocab_project" : "vocab_team",
    disabled: !may || null, previewPath: "/api/vocabulary/preview", previewKind: "vocab", preview: () => body(),
    method: "PUT", path: () => scope === "project" ? "/api/projects/" + enc(owner) + "/vocabulary" : "/api/teams/" + enc(owner) + "/vocabulary",
    body: () => Object.assign(body(), { reason: reason.value.trim() }), after: again });
  [label, desc, syn, hide, reason].forEach((el) => el.addEventListener("input", step.stale));
  const back = Object.keys(mine).some((k) => ["label", "description", "synonyms", "hidden", "means"].includes(k))
    ? button(pick("Give it back to the word below", "Reset"), { icon: "undo", kind: "small quiet", key: id + "-reset", disabled: !may || null,
      onclick: () => act(back.parentNode, async () => {
        if (!needPerson()) return;
        const res = await api("PUT", scope === "project" ? "/api/projects/" + enc(owner) + "/vocabulary" : "/api/teams/" + enc(owner) + "/vocabulary",
          Object.assign({ term: r.id, reset: true, reason: reason.value.trim() || "back to the word below" }, signed()));
        say((res.lines || ["Done."]).join(" "), "good");
        await again();
      }) }) : null;
  return h("div", { class: "vc-edit" },
    h("div", { style: ROW }, h("label", { for: label.id, style: { flex: "0 0 auto" } }, pick("Word", "Label")), label, h("label", { for: desc.id, class: "vh" }, "Description"), desc),
    h("div", { style: ROW }, syn, h("label", null, hide, " ", pick("Hide it from the views", "Hide"))),
    h("div", { style: ROW }, reason, step.go, back), step.out);
}

function termRow(r, scope, owner, may, pid, again) {
  const changed = r.scope !== "shipped";
  const word = TYPE_WORD[r.type] || ["Term", "Term"];
  const defined = r.since ? h("p", { class: "small muted", "data-key": "vc-since" }, pick("As defined on ", "Defined on ") + String(r.since).slice(0, 10)
    + (r.by ? " by " : ""), r.by ? datum(r.by) : null, r.why ? [": ", datum(r.why)] : null) : null;
  return h("li", { class: "vc-row" + (changed ? " changed" : ""), "data-term": r.id, "data-scope": r.scope },
    h("div", { style: ROW }, h("b", { style: GROW }, datum(r.label), " ", h("span", { class: "small muted" }, pick(word[0], word[1]))),
      scopeChip(r.scope), r.hidden ? chip("warning", "eye", pick("hidden", "hidden")) : null),
    r.description ? h("p", { class: "small" }, datum(r.description)) : null, defined,
    h("details", { class: "as-more" }, h("summary", null, pick("Meanings and change", "Layers and edit")),
      layerLine("Shipped:", "shipped", r.shipped && { label: r.shipped.label, description: r.shipped.description, synonyms: r.shipped.synonyms }),
      layerLine("Team's:", "team", r.team), layerLine("Project's:", "project", r.project),
      h("p", { class: "small" }, pick("In force: ", "In force: "), scopeChip(r.scope)),
      edit(r, scope, owner, may, pid, again)));
}

function customForm(d, scope, owner, may, pid, again) {
  const label = h("input", { id: "vc-new-l", "data-key": "vc-new-label", maxlength: "60", autocomplete: "off", placeholder: pick("Your word, e.g. Brief", "Label"), "aria-label": "Your own word" });
  const kinds = d.order.filter((t) => t.startsWith("kind:")).map((t) => d.terms[t]);
  const means = h("select", { id: "vc-new-m", "data-key": "vc-new-means", "aria-label": "The kind of record it means", style: { flex: "0 1 220px", maxWidth: "100%", width: "auto" } },
    kinds.map((k) => h("option", { value: k.id }, k.label)));
  const reason = h("input", { id: "vc-new-r", "data-key": "vc-new-reason", autocomplete: "off", maxlength: "300", placeholder: pick("Why", "Reason"), "aria-label": "Reason" });
  const owned = { [scope]: owner };
  const body = () => Object.assign({ label: label.value.trim(), means: means.value }, owned);
  const step = twoStep({ label: pick("Add the term", "Add"), key: "vc-new-save", control: scope === "project" ? "vocab_project" : "vocab_team", disabled: !may || null,
    previewPath: "/api/vocabulary/preview", previewKind: "vocab", preview: () => body(), method: "PUT",
    path: () => scope === "project" ? "/api/projects/" + enc(owner) + "/vocabulary" : "/api/teams/" + enc(owner) + "/vocabulary",
    body: () => Object.assign(body(), { reason: reason.value.trim() }), after: again });
  [label, means, reason].forEach((el) => el.addEventListener("input", step.stale));
  return h("details", { class: "as-more vc-custom" }, h("summary", null, pick("Add your own word for a kind of record", "Add a custom term")),
    h("p", { class: "small muted" }, "Another word that means an existing kind of record: Ask Rihma finds the kind by it."),
    h("div", { style: ROW }, label, h("span", { class: "small" }, "means"), means, reason, step.go), step.out);
}

function undoButton(scope, owner, may, pid, again) {
  const undo = button(pick("Undo the last change of words", "Undo"), { icon: "undo", kind: "small quiet", key: "vc-undo", "data-control": "vocab_undo", disabled: !may || null,
    onclick: () => act(undo.parentNode, async () => {
      if (!needPerson()) return;
      const r = await api("POST", "/api/vocabulary/undo", Object.assign({ [scope]: owner }, signed()));
      say(r.lines.join(" "), "good");
      await again();
    }) });
  return undo;
}

function filterBar(list, state, redraw) {
  const q = h("input", { type: "search", "data-key": "vc-find", placeholder: pick("Find a term", "Filter"), "aria-label": "Find a term", autocomplete: "off", style: { flex: "1 1 160px", minWidth: "0" } });
  const only = h("input", { type: "checkbox", "data-key": "vc-changed" });
  q.addEventListener("input", () => { state.q = q.value.trim().toLowerCase(); redraw(); });
  only.addEventListener("change", () => { state.only = only.checked; redraw(); });
  return h("div", { style: ROW }, q, h("label", { class: "small" }, only, " ", pick("Only the words that differ", "Changed only")), h("span", { class: "small muted", "data-key": "vc-count" },
    plural(list.filter((r) => r.scope !== "shipped").length, "term") + " differ"));
}

/* The Vocabulary of a scope: ``scope`` "project" (owner the project id) or "team" (owner the team id). */
export function vocabBody(d, scope, owner, pid, again, calm) {
  const may = mayAct(d.setters[scope]);
  const rows = d.order.map((t) => d.terms[t]);
  const state = { q: "", only: false };
  const lists = h("div", { class: "vc-lists" });
  const draw = () => {
    const keep = (r) => (!state.q || (r.label + " " + (r.shipped || {}).label + " " + r.synonyms.join(" ")).toLowerCase().includes(state.q)) && (!state.only || r.scope !== "shipped");
    const part = (types, title, open) => {
      const mine = rows.filter((r) => types.includes(r.type) && keep(r));
      if (!mine.length) return null;
      return h("details", { class: "vc-part", open: open || state.q || state.only || null, "data-part": types[0] }, h("summary", null, title + " (" + mine.length + ")"),
        h("ul", { class: "plain vc-rows" }, mine.map((r) => termRow(r, scope, owner, may, pid, again))));
    };
    const shown = [part(["kind", "custom"], pick("Kinds of record and your own words", "Kinds of record and custom terms"), !calm),
      part(["rel"], pick("How records link", "Relations"), false), part(["attr"], pick("Details a record carries", "Attributes"), false)].filter(Boolean);
    fill(lists, shown.length ? shown : emptyState("vocabulary", null, { what: pick("No term matches.", "No match."), how: pick("Clear the search, or untick “only the words that differ”.", "Clear the filter.") }));
  };
  draw();
  const history = (d.history || []).length ? h("details", { class: "as-more" }, h("summary", null, plural(d.history.length, "change") + " recorded"),
    h("ul", { class: "plain small" }, d.history.map((x) => h("li", null, ago(x.at) + ", " + (x.by || "a person") + ": ", datum(x.term + " "
      + ((x.after || {}).label ? "now " + x.after.label : x.after ? "changed" : "back to the word below") + (x.reason ? " (" + x.reason + ")" : "")))))) : null;
  return [h("p", { class: "small" }, pick("Rihmasto's own words, in yours. A word set here changes how records are read and labelled in the Knowledge graph, the glossary and Ask Rihma; "
    + "no record is rewritten, and old ones read the same way.", calm ? "Overlay on the shipped ontology: terms resolve shipped, then yours. Records are read through it, never rewritten."
      : "Overlay on the shipped ontology: terms resolve shipped, then team, then project. Records are read through it, never rewritten.")),
  filterBar(rows, state, draw), lists, customForm(d, scope, owner, may, pid, again),
  h("div", { class: "btns" }, undoButton(scope, owner, may, pid, again),
    may ? null : h("span", { class: "muted small" }, icon("user"), scope === "project" ? " IT or the project's owner changes a project's words." : " IT changes a team's words.")),
  history];
}

// -- the project's Vocabulary view -----------------------------------------------------------------------------------

function head() {
  return h("div", { class: "q" }, h("h2", { id: "view-title", tabindex: "-1" }, pick("Words for this project", "Vocabulary")),
    h("p", null, pick("What this project calls things, the team's words beneath, and Rihmasto's own beneath those. Where a setting comes from is listed at the end.",
      "Terms by scope: shipped, team, project. Where each setting comes from is listed below.")));
}

export function render(p) {
  const pid = p.meta.id;
  const box = h("div", { class: "vc-view", "data-said": "" }, head(), h("p", { class: "muted" }, "Reading…"));
  const again = () => draw().then(() => reread(pid));
  const draw = async () => {
    const d = await api("GET", "/api/vocabulary?project=" + enc(pid));
    if (!box.isConnected) return;
    fill(box, head(), card({ title: pick("Team of this project", "Team"), icon: "users", id: "vc-team", dataId: "teams_move" }, teamField(pid)),
      card({ title: pick("Words for this project", "Vocabulary: project"), icon: "book", id: "vc-project", dataId: "vocab_project",
        info: "Each term with Rihmasto's meaning, the team's and this project's, and which one is in force. A change is previewed, signed and can be undone; "
          + "records are only read in the new word." }, h("div", { "data-control": "vocab_project" }, vocabBody(d, "project", pid, pid, again))),
      card({ title: pick("What applies here", "Scope"), icon: "layers", id: "vc-scope", dataId: "scope_view" }, scopeCard(pid)));
  };
  draw().catch((e) => { if (!(e instanceof AuthError)) fill(box, head(), emptyState("vocabulary", null, { what: e.message, how: "Open the project again." })); });
  return box;
}

// -- Settings: the team's Vocabulary ---------------------------------------------------------------------------------

export function vocabSettingsCard() {
  const holder = h("div", { class: "vc-holder", "data-control": "vocab_team", "data-said": "" });
  let team = null;
  const again = () => draw().then(() => reread(null));
  const draw = async () => {
    const t = await api("GET", "/api/teams");
    team = team && t.teams.some((x) => x.id === team) ? team : t.teams[0].id;
    const d = await api("GET", "/api/vocabulary?team=" + enc(team));
    const pickTeam = t.teams.length > 1 ? h("select", { "data-key": "vc-team-sel", "aria-label": "Team", style: { flex: "0 1 240px", maxWidth: "100%", width: "auto" } },
      t.teams.map((x) => h("option", { value: x.id, selected: x.id === team || null }, x.name))) : null;
    if (pickTeam) pickTeam.addEventListener("change", () => { team = pickTeam.value; draw().catch(failed(holder)); });
    const mine = t.teams.find((x) => x.id === team);
    const alone = !!t.solo;      // one person: their own words, with no team to speak of, and the long list closed (FR-TM7)
    fill(holder, card({ title: alone ? "Your words for Rihmasto's terms" : pick("Words: Rihmasto's terms in your team's language", "Vocabulary: team"), icon: "book",
      id: "set-vocab", dataId: "vocab_team",
      info: alone ? "Say a kind of record in your own word: \"story\" where Rihmasto says \"requirement\". It is used in the Knowledge graph, the glossary and Ask Rihma for all your projects; "
        + "no record is rewritten."
        : "The team's words for Rihmasto's own terms, used in the Knowledge graph, the glossary and Ask Rihma for all the team's projects. A project may differ; "
        + "its own Vocabulary says so. IT changes a team's words." },
    alone ? null : h("p", { class: "small" }, scopeChip("team"), " ", pick("For ", "Team: "), h("b", null, datum(mine.name)), " · " + plural(mine.projects.length, "project")),
    pickTeam, vocabBody(d, "team", team, null, again, true)));
  };
  draw().catch(failed(holder));
  return holder;
}

// -- Ask Rihma's proposals: the same signed routes a click calls -----------------------------------------------------

const target = (a) => (a.project ? "/api/projects/" + enc(a.project) + "/vocabulary" : "/api/teams/" + enc(a.team) + "/vocabulary");
Object.assign(PROPOSALS, {
  vocab_set: { words: ["Change the word", "book"],
    describe: (a) => [(a.project ? "In project " + a.project : "For the team") + ": " + (a.term || "a custom term")
      + [a.label ? " is called " + a.label : "", a.description ? " is described" : "", a.synonyms ? " gets synonyms " + a.synonyms.join(", ") : "",
        a.hidden === true ? " is hidden" : a.hidden === null ? " is shown again" : ""].join("") + (a.reason ? ". Reason: " + a.reason : "")],
    call: (a) => api("PUT", target(a), Object.assign({ term: a.term, label: a.label, description: a.description, synonyms: a.synonyms, hidden: a.hidden, means: a.means,
      reason: a.reason || "" }, signed())).then((r) => { reread(a.project || null); return r; }) },
  vocab_undo: { words: ["Undo the change of words", "undo"],
    describe: (a) => ["Undo the last change of words " + (a.project ? "in project " + a.project : "for the team")],
    call: (a) => api("POST", "/api/vocabulary/undo", Object.assign(a.project ? { project: a.project } : { team: a.team }, signed())).then((r) => { reread(a.project || null); return r; }) },
});
