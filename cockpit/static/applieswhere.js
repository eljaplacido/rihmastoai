/* What applies where (kernel/scope_table.py, FR-TM3, FR-TM4; applieswhere.js): every setting or configuration surface with the
   scopes it may be set at (the shipped default, all teams, a team's own words, this project) and, for a project, where its
   value comes from right now, read from the store it is kept in ("this project's own", "set for all teams", "from the team",
   "shipped default", "nothing set here yet"), with a link to change it. One person's home says "all your projects" and keeps
   the long list closed. In Settings it reads for the home, or for a project chosen in the card; in a project's Vocabulary it
   reads for that project. Ask Rihma answers "where is this set?" from the same table. Nothing here changes a setting: a link
   says where. */

import { h, fill, icon, chip, api, enc, card, AuthError } from "./core.js";
import { pick, datum, emptyState } from "./words.js";

const SRC_TONE = { project: "accent", home: "info", team: "info", default: "neutral", none: "neutral", per_project: "neutral", personal: "neutral" };
const SRC_ICON = { project: "folder", home: "layers", team: "users", default: "layers", none: "minus", per_project: "folder", personal: "user" };
const ROW = { display: "flex", flexWrap: "wrap", alignItems: "center", gap: "4px 8px", margin: "6px 0" };

function rowOf(r, d) {
  const link = r.change_for_project || r.change_for_team;
  const forHome = r.change_for_project && r.change_for_team;
  const wider = r.scopes.length > 1;                  // a surface that only exists per project has nothing to differ from
  return h("li", { class: "sc-row", "data-surface": r.id, "data-source": r.source },
    h("div", { style: ROW }, h("b", { style: { flex: "1 1 220px", minWidth: "0" } }, datum(r.label)),
      chip(SRC_TONE[r.source] || "neutral", SRC_ICON[r.source] || "layers", r.id === "teams" && r.source === "project" ? datum(r.source_word) : r.source_word,
        { "data-scope": r.source })),
    h("p", { class: "small muted" }, pick("Can be set at: ", "Scopes: "), r.scope_words.join(", ").toLowerCase() + ".",
      r.set_per_project && wider ? pick(" A project may differ from the wider setting.", " A project's own setting wins.") : ""),
    h("div", { style: ROW }, link ? h("a", { class: "btn small", href: link.route, "data-key": "sc-change:" + r.id, "data-link-control": link.control },
      icon("arrow-right"), h("span", { class: "lbl" }, pick(r.change_for_project ? "Change it for this project" : "Change it", "Change")))
      : h("span", { class: "small muted" }, pick("Nothing to change here: it is shipped.", "Shipped.")),
    forHome ? h("a", { class: "btn small quiet", href: r.change_for_team.route, "data-key": "sc-team:" + r.id }, icon("layers"),
      h("span", { class: "lbl" }, pick(d.solo ? "Change it for all projects" : "Change it for all teams", d.solo ? "All projects" : "All teams"))) : null));
}

function body(d) {
  const shown = d.rows.filter((r) => !(d.solo && r.id === "teams"));      // one person has no team to move a project to
  const per = shown.filter((r) => r.set_per_project);
  const other = shown.filter((r) => !r.set_per_project);
  const everyone = d.solo ? "all your projects" : "all teams";
  return [h("p", { class: "small" }, d.project
    ? pick("Each setting, where its value comes from for this project, and where to change it. ", "Per setting: the value's source for this project. ")
    : pick("Each setting and the scopes it can be set at. Pick a project to see where its values come from. ", "Scopes per setting. "),
  d.team && !d.solo ? [pick("This project is in ", "Team: "), h("b", null, datum(d.team.name)), ". "] : null),
  per.length ? h("details", { class: "sc-part", open: true, "data-part": "per" }, h("summary", null, pick("Can differ per project (" + per.length + ")", "Per project (" + per.length + ")")),
    h("ul", { class: "plain sc-rows" }, per.map((r) => rowOf(r, d)))) : null,
  other.length ? h("details", { class: "sc-part", "data-part": "team" }, h("summary", null, pick("Set once for " + everyone + ", or shipped only (" + other.length + ")",
    "Home-wide or shipped (" + other.length + ")")), h("ul", { class: "plain sc-rows" }, other.map((r) => rowOf(r, d)))) : null];
}

/* The table for one project (a project's Vocabulary view). */
export function scopeCard(pid) {
  const holder = h("div", { class: "sc-holder", "data-control": "scope_view" }, h("p", { class: "muted small" }, "Reading what applies where…"));
  api("GET", "/api/scope?project=" + enc(pid)).then((d) => fill(holder, body(d)))
    .catch((e) => { if (!(e instanceof AuthError)) fill(holder, emptyState("scope", null, { what: e.message, how: "Open the project again." })); });
  return holder;
}

/* Settings: What applies where, for the home as a whole or for a project chosen in the card. One person's home keeps the
   long list in a closed disclosure, so Settings stays short (FR-TM7). */
export function scopeSettingsCard(projects) {
  const holder = h("div", { class: "sc-box" });
  const list = (projects || []).filter((p) => p.id !== "_factory");      // Rihmasto's own records are no project to read it for
  const sel = h("select", { "data-key": "sc-project", "aria-label": "Project", style: { flex: "0 1 260px", maxWidth: "100%", width: "auto" } },
    [h("option", { value: "" }, pick("All projects (no project chosen)", "All projects"))].concat(list.map((p) => h("option", { value: p.id }, p.title))));
  const draw = () => api("GET", "/api/scope" + (sel.value ? "?project=" + enc(sel.value) : "")).then((d) => fill(holder, body(d)))
    .catch((e) => { if (!(e instanceof AuthError)) fill(holder, h("p", { class: "note warning" }, icon("alert"), h("span", null, e.message))); });
  sel.addEventListener("change", draw);
  draw();
  const inner = h("div", { "data-control": "scope_view" }, list.length ? h("div", { style: { margin: "0 0 8px" } }, h("label", { class: "small", style: { marginRight: "8px" } }, pick("Read it for", "For")), sel) : null, holder);
  const shell = card({ title: pick("Where each setting applies", "Scope of every setting"), icon: "layers", id: "set-scope", dataId: "scope_view",
    info: "Every setting is set at the shipped default, for the whole home (every team shares it), for a team (only its words) or for one project. This lists each one with the scopes it can be set at and, for a project, "
      + "where its value comes from now." }, inner);
  api("GET", "/api/scope").then((d) => {
    if (!d.solo) return;
    const fold = h("details", { class: "as-more sc-fold", "data-key": "sc-fold" }, h("summary", null, pick("Which settings apply to everything and which to one project", "Scope of each setting")));
    inner.replaceWith(fold);
    fold.append(inner);
  }).catch(() => {});
  return shell;
}
