/* Set up this project, suggested automations, Describe it, and archiving (FR-SET1; kernel/project_setup.py,
   kernel/automation_suggest.py, kernel/automation_compose.py, kernel/project_archive.py).

   - The project's Overview opens with "Set up this project": every feature that applies, its state, and one click
     for each offered item (signed), or the place where a person chooses.
   - The Automations tab and page show the suggestions from a scan of the project, each to set up or dismiss, and
     "Describe it": words in, a draft with its summary and a dry run out, then Set it up or open it in the builder.
   - Project settings has Archive; Projects has Archived and duplicates, with Restore and Remove (Remove asks for
     the project's id typed, says it cannot be undone, and keeps the records as an export file first). */

import { S, h, fill, icon, chip, api, act, say, signed, needPerson, enc, link, button, card, empty, openModal,
  closeModal, nav, plural, ago } from "./core.js";

const STATE = { set_up: ["good", "check-circle", "Set up"], offered: ["info", "sparkles", "Offered"],
  not_applicable: ["neutral", "dashed", "Not applicable"], dismissed: ["neutral", "x", "Dismissed"],
  unavailable: ["warning", "alert", "Unavailable"] };
const stateChip = (s) => { const [tone, ic, word] = STATE[s] || STATE.not_applicable; return chip(tone, ic, word); };
const base = (pid) => "/api/projects/" + enc(pid);

// -- Set up this project ---------------------------------------------------------------------------------

function openTarget(pid, a) {
  if (a.page) location.hash = "#/" + a.page;
  else location.hash = link(pid, a.view || "overview");
}

function setupRow(pid, it, again) {
  const a = it.action || null;
  const tools = h("div", { class: "mdl-tools", "data-ud": "" });   // its labels are the checklist's (kernel)
  if (a && it.state === "offered" && a.kind === "do") {
    tools.append(button(a.label, { icon: "check", kind: "small primary", "data-control": "setup_do", key: "setup:" + it.id,
      onclick: () => act(tools, async () => {
        if (!needPerson()) return;
        // the suggestion the button names, so the server sets up that one or refuses (never another one)
        await api("POST", base(pid) + "/setup/" + enc(it.id), a.suggestion ? { ...signed(), suggestion: a.suggestion } : signed());
        say(a.label + ": done, signed by " + S.person.trim() + ".", "good");
        await again();
      }) }));
  } else if (a) {
    tools.append(button(a.label, { icon: "arrow-right", kind: "small", key: "setup-open:" + it.id, onclick: () => openTarget(pid, a) }));
  }
  return h("li", { class: "mdl-row", "data-key": "setup-item:" + it.id, "data-state": it.state },
    h("div", { class: "mdl-main", "data-ud": "" }, h("b", null, it.label), " ", stateChip(it.state), h("p", { class: "muted small amn-sum" }, it.why)), tools);
}

export function setupCard(p) {
  const pid = p.meta.id;
  const box = h("div", { class: "setup-box", "data-slot": "setup" });
  if (p.meta.archived) {
    fill(box, h("p", { class: "callout" }, icon("folder"), h("span", null, "Archived by " + p.meta.archived.by + " " + ago(p.meta.archived.at)
      + ": read-only, and hidden from the lists."), button("Restore", { icon: "undo", kind: "small", "data-control": "restore_project", key: "setup-restore",
      onclick: () => act(box, async () => { if (!needPerson()) return; await api("POST", base(pid) + "/restore", signed()); say("Restored.", "good"); if (nav.rerender) await nav.rerender(); }) })));
    return box;
  }
  const draw = async () => {
    let c;
    try { c = await api("GET", base(pid) + "/setup"); } catch (e) { fill(box); return; }
    if (!box.isConnected) return;
    const list = h("ul", { class: "emb-list setup-list" }, c.items.filter((i) => i.state !== "not_applicable").map((i) => setupRow(pid, i, draw)));
    const na = c.items.filter((i) => i.state === "not_applicable");
    fill(box, card({ title: "Set up this project", icon: "sparkles", id: "setup-card", cls: "setup-card", info: "Everything Rihmasto offers that applies here. Ask Rihma: \"set up this project\"." },
      h("p", { class: "muted", "data-control": "setup_checklist" }, c.line), c.done ? h("details", { class: "amn-det" }, h("summary", null, "What is set up"), list) : list,
      na.length ? h("details", { class: "amn-det" }, h("summary", null, plural(na.length, "item") + " not applicable"),
        h("ul", { class: "plain small" }, na.map((i) => h("li", null, h("b", null, i.label + ": "), i.why)))) : null));
  };
  draw();
  return box;
}

// -- suggested automations -------------------------------------------------------------------------------

function suggestionRow(pid, s, again) {
  const tools = h("div", { class: "mdl-tools", "data-ud": "" });
  if (s.state === "offered") {
    tools.append(button("Set it up", { icon: "check", kind: "small primary", "data-control": "automations_suggest_accept", key: "sug-ok:" + s.id,
      onclick: () => act(tools, async () => {
        if (!needPerson()) return;
        const out = await api("POST", base(pid) + "/automation-suggestions/" + enc(s.id) + "/accept", signed());
        say(out.automation.id + " is set: " + s.label + ".", "good");
        await again();
      }) }),
    button("Not now", { icon: "x", kind: "small quiet", "data-control": "automations_suggest_dismiss", key: "sug-no:" + s.id,
      onclick: () => act(tools, async () => {
        if (!needPerson()) return;
        await api("POST", base(pid) + "/automation-suggestions/" + enc(s.id) + "/dismiss", signed());
        await again();
      }) }));
  }
  return h("li", { class: "mdl-row", "data-key": "sug:" + s.id, "data-state": s.state },
    h("div", { class: "mdl-main", "data-ud": "" }, h("b", null, s.label), " ", stateChip(s.state), s.automation ? h("span", { class: "mono muted small" }, " " + s.automation) : null,
      h("p", { class: "amn-sum" }, "Why: " + s.reason), s.summary ? h("p", { class: "muted small amn-sum" }, s.summary) : null,
      s.why ? h("p", { class: "muted small" }, s.why) : null), tools);
}

export function suggestionsCard(pid, onChange) {
  const body = h("div", { "aria-live": "polite" }, h("p", { class: "muted" }, "Scanning…"));
  const draw = async () => {
    if (!pid) { fill(body, h("p", { class: "muted" }, "Pick a project to scan.")); return; }
    let s;
    try { s = await api("GET", base(pid) + "/automation-suggestions"); } catch (e) { fill(body, empty("alert", e.message)); return; }
    if (!body.isConnected) return;
    const again = async () => { await draw(); if (onChange) await onChange(); };
    const rows = s.suggestions.filter((x) => x.state !== "dismissed");
    fill(body, rows.length ? h("ul", { class: "emb-list amn-list", id: "sug-list" }, rows.map((x) => suggestionRow(pid, x, again)))
      : empty("check-circle", "Nothing to suggest: what its shape asks for is set up or dismissed."));
  };
  const rescan = button("Scan again", { icon: "refresh", kind: "small", "data-control": "automations_suggest", key: "sug-scan:" + (pid || ""), onclick: () => draw() });
  draw();
  return card({ title: "Suggested for this project", icon: "sparkles", id: "sug-card", info: "From the project's shape and state: its repository, tests, releases, checks, whether it is confidential." },
    body, h("div", { class: "btns" }, rescan));
}

// -- Describe it --------------------------------------------------------------------------------------------

export function describeCard(pid, openBuilder, again) {
  const text = h("textarea", { id: "amn-describe", rows: "2", maxlength: "2000", "data-key": "amn-describe",
    placeholder: "every night run the tests and tell me on Teams if they fail" });
  const out = h("div", { class: "amn-described", "aria-live": "polite" });
  const read = button("Read it", { icon: "sparkles", kind: "primary", "data-control": "automations_describe", key: "amn-describe-go" });
  read.addEventListener("click", () => act(read.parentNode, async () => {
    if (!text.value.trim()) { say("Describe it first: when, what, and whom to tell.", "warning"); text.focus(); return; }
    if (!needPerson()) return;
    const r = await api("POST", "/api/automations/compose", Object.assign({ text: text.value.trim(), project: pid || "" }, signed()));
    drawDraft(out, r, openBuilder, again);
  }));
  // Ask Rihma's "generate an automation that ..." (goal.js): the words arrive here and are read at once
  const asked = S.automationAsk && (S.automationAsk.pid || "") === (pid || "") ? S.automationAsk : null;
  if (asked) {
    S.automationAsk = null;
    text.value = asked.text;
    if (S.person.trim()) setTimeout(() => { if (text.isConnected) read.click(); }, 0);
  }
  return card({ title: "Describe it", icon: "message-square", id: "amn-describe-card", info: "Your words become a draft with its summary and a dry run; nothing is set until you set it up." },
    h("div", { class: "field" }, h("label", { for: "amn-describe" }, "What should happen, and when"), text), h("div", { class: "btns" }, read), out);
}

function drawDraft(out, r, openBuilder, again) {
  if (!r.ok) {
    fill(out, h("p", { class: "note warning" }, icon("alert"), h("span", null, r.why || "It does not check out.")),
      r.draft && r.draft.trigger && openBuilder ? button("Open in the builder", { icon: "edit", kind: "small", key: "amn-describe-builder", onclick: () => openBuilder(r.draft, again) }) : null);
    return;
  }
  const d = r.dry_run || {};
  const save = button("Set it up", { icon: "check", kind: "small primary", key: "amn-describe-save", "data-control": "automations_save" });
  save.addEventListener("click", () => act(out, async () => {
    if (!needPerson()) return;
    const made = await api("POST", "/api/automations", Object.assign({ automation: r.draft }, signed()));
    say(made.automation.id + " is set: " + made.automation.summary, "good");
    fill(out, h("p", { class: "note" }, icon("check-circle"), h("span", null, made.automation.id + " is set.")));
    if (again) await again();
  }));
  fill(out, h("p", { class: "note amn-summary", id: "amn-describe-summary" }, icon("info"), h("span", null, r.summary)),
    h("p", { class: "muted small" }, "Read by " + (r.by === "model" ? "the assistant model, checked against the allow-list" : "the rules") + "."
      + (d.first_at ? " First run: " + d.first_at + "." : "") + (d.projects ? " Reaches: " + (d.projects.join(", ") || "no project now") + "." : "")),
    d.firings && d.firings.length ? h("ul", { class: "plain small" }, d.firings.map((f) => h("li", null, (f.project || "the factory") + ": " + f.would))) : null,
    r.note ? h("p", { class: "muted small" }, r.note) : null,
    h("div", { class: "btns" }, save, openBuilder ? button("Open in the builder", { icon: "edit", kind: "small", key: "amn-describe-builder", onclick: () => openBuilder(r.draft, again) }) : null));
}

// -- archive, restore, remove ---------------------------------------------------------------------------------

export function archiveButton(p, swap) {
  return h("button", { type: "button", class: "btn small", "data-control": "archive_project", "data-key": "ps-archive",
    onclick: () => swap(() => openArchive(p)) }, icon("folder"), h("span", { class: "lbl" }, "Archive this project"));
}

function openArchive(p) {
  const pid = p.meta.id;
  const reason = h("input", { id: "ar-reason", "data-key": "ar-reason", maxlength: "500", autocomplete: "off", placeholder: "for example: a duplicate of another project" });
  const form = h("form", { class: "chg-form", novalidate: true },
    h("p", null, "Archiving hides " + p.meta.title + " from every list and makes it read-only. Projects, Archived restores it, or removes it for good."),
    h("div", { class: "field" }, h("label", { for: "ar-reason" }, "Reason (recorded with your name)"), reason),
    h("div", { class: "btns" }, h("button", { type: "submit", class: "btn human primary", "data-key": "ar-go" }, icon("folder"), "Archive")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!needPerson()) return;
    act(form, async () => {
      await api("POST", base(pid) + "/archive", Object.assign({ reason: reason.value.trim() }, signed()));
      closeModal();
      ARCHIVED_OPEN = true;              // Projects opens with Archived shown, where it can be restored
      say(p.meta.title + " is archived.", "good");
      location.hash = "#/projects";
    });
  });
  openModal("Archive · " + p.meta.title, form, { icon: "folder" });
}

function openRemove(row, again) {
  const typed = h("input", { id: "rm-confirm", "data-key": "rm-confirm", autocomplete: "off", spellcheck: "false" });
  const go = h("button", { type: "submit", class: "btn human primary", "data-key": "rm-go", disabled: true }, icon("x"), "Remove for good");
  typed.addEventListener("input", () => { go.disabled = typed.value.trim() !== row.id; });
  const form = h("form", { class: "chg-form", novalidate: true },
    h("p", { class: "note warning" }, icon("alert"), h("span", null, "Remove " + row.title + " (" + row.id + ") for good: this cannot be undone. Its records are kept first as an export file in exports/removed/.")),
    h("div", { class: "field" }, h("label", { for: "rm-confirm" }, "Type " + row.id + " to confirm"), typed), h("div", { class: "btns" }, go));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!needPerson() || typed.value.trim() !== row.id) return;
    act(form, async () => {
      const out = await api("POST", base(row.id) + "/remove", Object.assign({ confirm: typed.value.trim() }, signed()));
      closeModal();
      say(row.title + " is removed; its records are in " + out.export.relative + ".", "good");
      await again();
    });
  });
  openModal("Remove · " + row.title, form, { icon: "alert" });
}

function archivedRow(r, again) {
  const tools = h("div", { class: "mdl-tools" },
    button("Restore", { icon: "undo", kind: "small", "data-control": "restore_project", key: "arc-restore:" + r.id,
      onclick: () => act(tools, async () => { if (!needPerson()) return; await api("POST", base(r.id) + "/restore", signed()); say(r.title + " is restored.", "good"); await again(); }) }),
    button("Remove", { icon: "x", kind: "small quiet", "data-control": "remove_project", key: "arc-remove:" + r.id, onclick: () => openRemove(r, again) }));
  const a = r.archived || {};
  return h("li", { class: "mdl-row", "data-key": "arc:" + r.id }, h("div", { class: "mdl-main" }, h("b", null, r.title), h("span", { class: "mono muted small" }, " " + r.id),
    h("p", { class: "muted small amn-sum" }, "Archived by " + (a.by || "?") + " " + ago(a.at) + (a.reason ? ": " + a.reason : ""))), tools);
}

function copyRow(g, c, again) {
  const tools = h("div", { class: "mdl-tools" }, button("Archive this copy", { icon: "folder", kind: "small", "data-control": "archive_project", key: "dup-archive:" + c.id,
    onclick: () => act(tools, async () => {
      if (!needPerson()) return;
      await api("POST", base(c.id) + "/archive", Object.assign({ reason: "a copy of " + g.keep.id }, signed()));
      say(c.title + " (" + c.id + ") is archived.", "good");
      await again();
    }) }));
  return h("li", { class: "mdl-row", "data-key": "dup:" + c.id }, h("div", { class: "mdl-main" }, h("b", null, c.title), h("span", { class: "mono muted small" }, " " + c.id),
    h("p", { class: "muted small amn-sum" }, "A copy of " + g.keep.id + (c.updated ? "; updated " + ago(c.updated) : ""))), tools);
}

// Whether Archived and duplicates is open: as the person left it, else open while there are duplicates.
let ARCHIVED_OPEN = null;

export function archivedSection() {
  const box = h("div", { class: "section", "data-slot": "archived" });
  const draw = async () => {
    let data;
    try { data = await api("GET", "/api/archived-projects"); } catch (e) { fill(box); return; }
    if (!box.isConnected) return;
    const again = async () => { await draw(); if (nav.rerender) await nav.rerender(); };
    const copies = data.duplicates.reduce((n, g) => n + g.copies.length, 0);
    const open = ARCHIVED_OPEN === null ? data.duplicates.length > 0 : ARCHIVED_OPEN;
    const det = h("details", { class: "amn-det", open: open ? true : null, ontoggle: (e) => { ARCHIVED_OPEN = e.target.open; } },
      h("summary", { "data-control": "archived_projects" }, "Archived (" + data.archived.length + ") and duplicates (" + copies + ")"),
      data.duplicates.length ? card({ title: "Duplicates", icon: "layers", id: "dup-card", info: "Projects that share a title: the one with the most records is kept." },
        h("ul", { class: "emb-list" }, data.duplicates.flatMap((g) => g.copies.map((c) => copyRow(g, c, again))))) : null,
      card({ title: "Archived", icon: "folder", id: "arc-card" }, data.archived.length
        ? h("ul", { class: "emb-list" }, data.archived.map((r) => archivedRow(r, again))) : h("p", { class: "muted" }, "No archived project.")));
    fill(box, det);
  };
  draw();
  return box;
}
