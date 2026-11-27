/* Teams, each tied to projects (kernel/teams.py, FR-TM1). A person working alone is a team of one made for them,
   named after them: there is nothing to set up, and the page says so in a line. When a second person joins, the same
   team simply has more members. In Settings, Teams lists each team with its members and projects and lets IT make a
   team, rename it and change its members; a project is moved to another team (by IT or its owner) with a preview first,
   signed, and an Undo after. A project's settings carry the same Team field. Ask Rihma does the same by rule. */

import { h, fill, icon, chip, api, enc, card, button, say, plural, signed, needPerson, act, ago, AuthError, mayAct, nav,
  PROPOSALS } from "./core.js";
import { pick, datum, emptyState } from "./words.js";

const ROW = { display: "flex", flexWrap: "wrap", alignItems: "center", gap: "6px 8px", margin: "8px 0" };
const GROW = { flex: "1 1 200px", minWidth: "0", margin: "0" };
const SELECT = { flex: "0 1 240px", minWidth: "0", maxWidth: "100%", width: "auto" };

const failed = (holder) => (e) => { if (!(e instanceof AuthError)) fill(holder, h("p", { class: "note warning" }, icon("alert"), h("span", null, e.message))); };

/* A move or a change with its preview first: the first press shows what changes, the next makes it, signed. */
const PREVIEWS = { teams: { "data-control": "teams_preview" }, vocab: { "data-control": "vocab_preview" } };

export function twoStep(opts) {
  let shown = null;
  const out = h("div", Object.assign({ class: "tm-out", role: "status", "aria-live": "polite" }, PREVIEWS[opts.previewKind || "teams"]));
  const lines = (r) => h("ul", { class: "plain tm-lines", "data-key": "tm-preview" }, r.lines.map((l) => h("li", null, icon("arrow-right"), " ", datum(l))));
  const go = button(opts.label, { icon: "check", kind: "small primary", key: opts.key, "data-control": opts.control, disabled: opts.disabled || null,
    onclick: () => act(go.parentNode, async () => {
      if (!needPerson()) return;
      const asked = JSON.stringify(opts.preview());
      if (shown !== asked) {
        const r = await api("POST", opts.previewPath || "/api/teams/preview", Object.assign(opts.preview(), signed()));
        fill(out, lines(r));
        if (!r.changes.length) { shown = null; return; }
        shown = asked;
        go.querySelector(".lbl").textContent = pick("Make this change", "Confirm");
        say(pick("Here is what changes. Press again to make it.", "Preview shown: confirm to save."), "info");
        return;
      }
      const res = await api(opts.method, opts.path(), Object.assign(opts.body(), signed()));
      shown = null;
      go.querySelector(".lbl").textContent = opts.label;
      say(((res.saved === false ? ["Nothing changed."] : res.lines) || ["Done."]).join(" ") + " Signed and recorded; Undo puts it back.", "good");
      await opts.after();
    }) });
  const stale = () => { shown = null; if (go.isConnected) go.querySelector(".lbl").textContent = opts.label; };
  return { go, out, stale };
}

// -- the team of a project ----------------------------------------------------------------------------------------

/* The Team field of Project settings: the project's team, and a move to another with a preview first. In a home with
   one person and one team it is one calm line. */
export function teamField(pid) {
  const holder = h("div", { class: "tm-field", "data-control": "teams_move", "data-key": "ps-team" }, h("span", { class: "muted small" }, "Reading the team…"));
  const draw = () => api("GET", "/api/projects/" + enc(pid) + "/team").then((d) => {
    if (!d.applies) { fill(holder); return; }
    const solo = d.solo && d.choices.length === 1;
    const name = h("b", null, datum(d.team.name));
    if (solo) {      // one person, one team made for them: nothing to say here, so the field and its label go (FR-TM7)
      const wrap = holder.closest(".chg-team, .card");
      if (wrap) wrap.style.display = "none";
      fill(holder);
      return;
    }
    const sel = h("select", { id: "tm-sel-" + pid, "data-key": "tm-sel", "aria-label": pick("Move this project to a team", "Team"), style: SELECT },
      d.choices.map((c) => h("option", { value: c.id, selected: c.id === d.team.id || null }, c.name)));
    const may = mayAct(d.movers);
    const step = twoStep({ label: pick("Move", "Move"), key: "tm-move", control: "teams_move", disabled: !may || null,
      preview: () => ({ project: pid, to: sel.value }), method: "POST", path: () => "/api/projects/" + enc(pid) + "/team",
      body: () => ({ team: sel.value }), after: async () => { nav.vocabDirty = true; await draw(); } });
    sel.addEventListener("change", step.stale);
    const undo = button("Undo", { icon: "undo", kind: "small quiet", key: "tm-undo", "data-control": "teams_undo", disabled: !may || null,
      onclick: () => act(undo.parentNode, async () => {
        if (!needPerson()) return;
        const r = await api("POST", "/api/teams/undo", Object.assign({ project: pid }, signed()));
        say(r.lines.join(" "), "good");
        nav.vocabDirty = true;
        await draw();
      }) });
    fill(holder, h("label", { for: sel.id, class: "vh" }, pick("Team of this project", "Team")),
      h("div", { style: ROW }, h("span", { style: GROW }, icon("users"), " ", pick("In ", "In "), name,
        h("span", { class: "small muted" }, " · " + plural(d.team.members.length, "member"))), sel, step.go, undo),
      step.out, may ? null : h("p", { class: "muted small" }, icon("user"), " IT or the project's owner moves a project to another team."));
  }).catch(failed(holder));
  draw();
  return holder;
}

// -- Settings: Teams ----------------------------------------------------------------------------------------------

function memberChips(t) {
  return t.members.length ? h("span", { class: "tm-members" }, t.members.map((m) => chip("neutral", "user", m, { "data-ud": "" })))
    : h("span", { class: "muted small" }, pick("nobody yet", "no members"));
}

function projectRow(p, t, d, again) {
  const sel = h("select", { "aria-label": pick("Move " + p.title + " to a team", "Team of " + p.title), "data-key": "tm-proj-sel:" + p.id, style: SELECT },
    d.teams.map((x) => h("option", { value: x.id, selected: x.id === t.id || null }, x.name)));
  const step = twoStep({ label: "Move", key: "tm-proj-move:" + p.id, control: "teams_move", disabled: !mayAct(d.movers) || null,
    preview: () => ({ project: p.id, to: sel.value }), method: "POST", path: () => "/api/projects/" + enc(p.id) + "/team",
    body: () => ({ team: sel.value }), after: async () => { nav.vocabDirty = true; await again(); } });
  sel.addEventListener("change", step.stale);
  return h("li", { class: "tm-proj", "data-project": p.id }, h("div", { style: ROW }, h("span", { style: GROW }, icon("folder"), " ", datum(p.title)),
    sel, step.go), step.out);
}

function changeForm(t, d, again) {
  const name = h("input", { id: "tm-name-" + t.id, "data-key": "tm-name:" + t.id, value: t.name, maxlength: "80", autocomplete: "off",
    "aria-label": pick("Team name", "Name") });
  const add = h("input", { id: "tm-add-" + t.id, "data-key": "tm-add:" + t.id, autocomplete: "off", placeholder: pick("Add a person by name", "Add member"),
    "aria-label": "Add a member" });
  const may = mayAct(d.admins);
  const step = twoStep({ label: pick("Save the team", "Save"), key: "tm-save:" + t.id, control: "teams_set", disabled: !may || null,
    preview: () => ({ team: t.id, name: name.value.trim(), add: add.value.trim() ? [add.value.trim()] : [] }), method: "PUT",
    path: () => "/api/teams/" + enc(t.id), body: () => ({ name: name.value.trim(), add: add.value.trim() ? [add.value.trim()] : [] }), after: again });
  [name, add].forEach((el) => el.addEventListener("input", step.stale));
  const gone = h("select", { "aria-label": "Remove a member", "data-key": "tm-rm:" + t.id, style: SELECT },
    [h("option", { value: "" }, pick("Remove a member…", "Remove member"))].concat(t.members.map((m) => h("option", { value: m }, m))));
  const rm = button("Remove", { icon: "x", kind: "small quiet", key: "tm-remove:" + t.id, disabled: !may || null,
    onclick: () => act(rm.parentNode, async () => {
      if (!needPerson() || !gone.value) return;
      const r = await api("PUT", "/api/teams/" + enc(t.id), Object.assign({ remove: [gone.value] }, signed()));
      say(r.lines.join(" "), "good");
      await again();
    }) });
  return h("div", { class: "tm-edit" }, h("div", { style: ROW }, name, add, step.go), step.out,
    t.auto && !(t.members.length > 1) ? null : h("div", { style: ROW }, gone, rm),
    may ? null : h("p", { class: "muted small" }, icon("user"), " IT defines a team and who is in it."));
}

function teamBlock(t, d, again) {
  return h("section", { class: "tm-team", "data-team": t.id }, h("h4", null, icon("users"), " ", datum(t.name), " ",
    t.auto ? chip("info", "user", pick("made for you", "automatic"), { tip: "Made automatically for the person working alone; a second person joins this same team." }) : null),
  h("p", { class: "small" }, pick("People: ", "Members: "), memberChips(t)),
  t.projects.length ? h("ul", { class: "plain tm-projects" }, t.projects.map((p) => projectRow(p, t, d, again)))
    : emptyState("teams", null, { what: pick("No project in this team yet.", "No projects in this team."),
      how: pick("Move one in from the list of another team here, or from the project's settings.", "Move a project in from its settings or from another team's list.") }),
  changeForm(t, d, again));
}

function makeForm(d, again) {
  const name = h("input", { id: "tm-new", "data-key": "tm-new", autocomplete: "off", maxlength: "80", placeholder: pick("Name of the new team", "New team name"),
    "aria-label": "Name of the new team" });
  const may = mayAct(d.admins);
  const make = button(pick("Make the team", "Create"), { icon: "plus", kind: "small primary", key: "tm-create", "data-control": "teams_set", disabled: !may || null,
    onclick: () => act(make.parentNode, async () => {
      if (!needPerson()) return;
      if (!name.value.trim()) { say("Name the team first.", "warning"); name.focus(); return; }
      const r = await api("POST", "/api/teams", Object.assign({ name: name.value.trim() }, signed()));
      say(r.lines.join(" ") + " Signed and recorded; Undo puts it back.", "good");
      await again();
    }) });
  return h("div", { style: ROW, class: "tm-make" }, name, make);
}

function historyList(d, again) {
  const rows = (d.history || []).filter((x) => x.kind !== "team_undone").slice(0, 5);
  const undo = button("Undo the last team change", { icon: "undo", kind: "small quiet", key: "tm-undo-last", "data-control": "teams_undo", disabled: !mayAct(d.admins) || null,
    onclick: () => act(undo.parentNode, async () => {
      if (!needPerson()) return;
      const last = (d.history || []).find((x) => x.kind === "team_set");
      if (!last) { say("There is no team change to undo.", "warning"); return; }
      const r = await api("POST", "/api/teams/undo", Object.assign({ team: last.team }, signed()));
      say(r.lines.join(" "), "good");
      await again();
    }) });
  return rows.length ? h("details", { class: "as-more" }, h("summary", null, plural(rows.length, "change") + " recorded"),
    h("ul", { class: "plain small" }, rows.map((x) => h("li", null, ago(x.at) + ", " + (x.by || "a person") + ": ",
      datum(x.kind === "team_set" ? (x.before ? "changed " : "made ") + ((x.after || {}).name || x.team) : "moved " + (x.project || "a project") + " to " + (x.after || "a team")))))
    , h("div", { class: "btns" }, undo)) : null;
}

function settingsBody(d, again) {
  if (d.solo) {
    const t = d.teams[0];
    return [h("p", { class: "small", "data-key": "tm-solo" }, icon("users"), " ", pick("You work alone, so Rihmasto made one team for you: ", "Automatic team of one: "),
      h("b", null, datum(t.name)), pick(". Nothing to set up. When a second person joins, the same team simply gets members; nothing moves and nothing is lost.",
        ". A second person joins this same team: no migration.")),
    t.projects.length ? h("p", { class: "small muted" }, plural(t.projects.length, "project") + " in it.") : null,
    h("details", { class: "as-more tm-more" }, h("summary", null, pick("Make another team", "Make a team")),
      h("p", { class: "small muted" }, "A second team is for a group of people who share projects; a project belongs to exactly one team."), makeForm(d, again)),
    historyList(d, again)];
  }
  return [h("p", { class: "small" }, pick("A project belongs to exactly one team, and a team has many projects. A team's words apply to all its projects (a project may say its own). "
    + "The other settings, such as structure, enforcement and modules, are made once for every team. IT defines a team; IT or the project's owner moves a project.",
  "A project is in exactly one team. Team terms apply to its projects; a project may override them. Structure, enforcement, modules and IT checks are one setting per home, shared by every team.")),
  d.teams.map((t) => teamBlock(t, d, again)), h("h4", null, pick("Make a team", "New team")), makeForm(d, again), historyList(d, again)];
}

export function teamsSettingsCard() {
  const holder = h("div", { class: "tm-holder", "data-control": "teams_page" });
  const again = () => api("GET", "/api/teams").then((d) => fill(holder, card({ title: pick("Teams", "Teams"), icon: "users", id: "set-teams",
    info: "Every project is in exactly one team. A person working alone is a team of one, made automatically. Teams hold people and projects; "
      + "their own words are shown with the scope they come from." }, settingsBody(d, again))))
    .catch(failed(holder));
  again();
  return holder;
}

// -- Ask Rihma's proposals: the same signed routes a click calls ---------------------------------------------------

Object.assign(PROPOSALS, {
  team_move: { words: ["Move the project to the team", "users"],
    describe: (a) => ["Move project " + a.project + " to " + (a.team_name || a.team) + (a.reason ? ". Reason: " + a.reason : "")],
    call: (a) => api("POST", "/api/projects/" + enc(a.project) + "/team", Object.assign({ team: a.team, reason: a.reason || "" }, signed())) },
  team_create: { words: ["Make the team", "users"],
    describe: (a) => ["Make a team called " + a.name + (a.reason ? ". Reason: " + a.reason : "")],
    call: (a) => api("POST", "/api/teams", Object.assign({ name: a.name, reason: a.reason || "" }, signed())) },
  team_undo: { words: ["Undo the team change", "undo"],
    describe: (a) => ["Undo the last change of " + (a.project ? "project " + a.project + "'s team" : "team " + a.team)],
    call: (a) => api("POST", "/api/teams/undo", Object.assign(a.project ? { project: a.project } : { team: a.team }, signed())) },
});
