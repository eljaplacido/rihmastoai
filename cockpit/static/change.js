/* Change anything set for a project (FR-CHG1): the Project settings dialog with its impact preview, Go back
   a step, Add material, and the "What's next" strip on the overview (kernel/next_step.py) whose buttons
   carry out what they name. Every write is signed like any other; the kernel decides whether it stands. */

import {
  S, $, h, fill, icon, chip, api, act, say, signed, needPerson, nav, enc, link, orList, cap, plural,
  openModal, closeModal, profileOf,
} from "./core.js";
import { postureChip, openPosture } from "./posture.js";
import { projectRunnerLine } from "./runners.js";

const STEP_LABEL = { material: "the material", questions: "the questions", spec: "the spec", plan: "the plan" };
const FIELD_LABEL = { title: "Title", kind: "Kind of work", mode: "Mode", maturity: "Maturity", build_without_waiting: "Build without waiting for me" };

function changers() { return ((S.meta && S.meta.change) || {}).changers || []; }
function adders() { return ((S.meta && S.meta.change) || {}).material_adders || []; }
function mayChange() { return changers().includes(S.persona); }
function base(pid) { return "/api/projects/" + enc(pid); }
function field(id, label, control, help) {
  return h("div", { class: "field" }, h("label", { for: id }, label), control, help ? h("small", { class: "muted" }, help) : null);
}
function select(id, options, value) {
  return h("select", { id, "data-key": id }, options.map(([v, l]) => h("option", { value: v, selected: v === value }, l)));
}
// One dialog in place of another: the next opens once the first has closed (its close clears the dialog).
function swap(open) {
  const dlg = $("#modal");
  if (!dlg.open) { open(); return; }
  dlg.addEventListener("close", () => open(), { once: true });
  closeModal();
}
// After a write: close the dialog, say what was recorded, draw the project again.
async function done(text) {
  closeModal();
  say(text, "good");
  if (nav.rerender) await nav.rerender();
}

// -- the header's buttons -----------------------------------------------------------------------------------

export function changeButtons(p) {
  return h("div", { class: "chg-acts" },
    h("button", { type: "button", class: "btn small", "data-control": "project_settings", "data-key": "project-settings",
      "aria-haspopup": "dialog", onclick: () => openSettings(p) }, icon("sliders"), h("span", { class: "lbl" }, "Project settings")));
}

// -- Project settings --------------------------------------------------------------------------------------

export function openSettings(p) {
  const pid = p.meta.id;
  const now = ((p.change || {}).settings) || { title: p.meta.title, kind: p.meta.profile, mode: p.meta.mode, maturity: p.meta.maturity };
  const profiles = (S.meta && S.meta.profiles) || [];
  const title = h("input", { id: "ps-title", "data-key": "ps-title", maxlength: "200", value: now.title || "", autocomplete: "off" });
  const kind = select("ps-kind", profiles.map((x) => [x.id, x.label]), now.kind);
  const mode = select("ps-mode", Object.keys(S.meta.modes).map((m) => [m, cap(m) + ": " + S.meta.modes[m]]), now.mode);
  const maturity = select("ps-maturity", Object.keys(S.meta.maturities).map((m) => [m, cap(m) + ": " + S.meta.maturities[m]]), now.maturity);
  // At explore and demo the factory waits once for a person's go-ahead on the spec before the first build (kernel/go_ahead.py).
  const nowait = h("input", { type: "checkbox", id: "ps-nowait", "data-key": "ps-nowait", "data-control": "build_without_waiting",
    checked: now.build_without_waiting !== false });
  const reason = h("input", { id: "ps-reason", "data-key": "ps-reason", maxlength: "2000", autocomplete: "off",
    placeholder: "for example: it is an integration, not a web app" });
  const impact = h("div", { class: "chg-impact", id: "ps-impact", "aria-live": "polite" },
    h("p", { class: "muted small" }, "Change a value, then preview what it means for the work already done. Nothing is saved until you save."));
  const redo = h("input", { type: "checkbox", id: "ps-redo", "data-key": "ps-redo" });
  const runnerBox = h("div", { "data-slot": "runners", "aria-live": "polite" }, h("span", { class: "muted small" }, "Reading the runners…"));
  const redoRow = h("div", { class: "chg-redo", hidden: true }, redo, h("label", { for: "ps-redo" }, ""));
  const preview = h("button", { type: "button", class: "btn", "data-key": "ps-preview" }, icon("eye"), h("span", { class: "lbl" }, "Preview the impact"));
  const save = h("button", { type: "submit", class: "btn human primary", "data-key": "ps-save", disabled: true }, "Save the settings");
  const values = () => ({ title: title.value.trim(), kind: kind.value, mode: mode.value, maturity: maturity.value,
    build_without_waiting: nowait.checked });
  let shown = null;
  const stale = () => { shown = null; save.disabled = true; };
  [title, kind, mode, maturity, nowait].forEach((el) => el.addEventListener(el.tagName === "INPUT" && el.type !== "checkbox" ? "input" : "change", stale));
  preview.addEventListener("click", async () => {
    if (!needPerson()) return;
    const asked = values();
    const out = await act(form, () => api("POST", base(pid) + "/settings/preview", Object.assign({}, asked, signed())));
    if (!out) return;
    shown = JSON.stringify(asked);
    drawImpact(impact, redoRow, out);
    // the buttons are on again once the preview is in: Save only for a change a persona that may change can save
    save.disabled = !Object.keys(out.changes).length || !mayChange();
  });
  const form = h("form", { class: "chg-form", novalidate: true, "aria-label": "Settings of " + p.meta.title },
    h("p", { class: "muted small" }, "Everything set when the project was made can change. The ledger keeps what it was, who changed it and why; nothing is deleted."),
    field("ps-title", "Title", title),
    h("div", { class: "row2" }, field("ps-kind", "Kind of work", kind, "The questions, checks and template follow it."),
      field("ps-maturity", "Maturity", maturity, "Which stages and gates run, and how big the spec is.")),
    field("ps-mode", "Mode", mode, "Who answers the panel's questions: people, the factory, or both."),
    h("div", { class: "field chg-nowait" }, h("div", { class: "chg-redo" }, nowait,
      h("label", { for: "ps-nowait" }, "Build without waiting for me")),
      h("small", { class: "muted" }, "Off: at explore and demo the factory waits once, before the first build, for your Go or Skip on the spec. On: it builds the spec as written.")),
    // The posture (prototype, balanced, production, regulated) has its own change flow (kernel/posture_change.py):
    // its chip opens the Posture dialog in place of this one, with the kernel's preview of what changes now and later.
    h("div", { class: "field chg-posture", "data-slot": "posture" }, h("span", { class: "label-h" }, "Posture"),
      h("div", { class: "chg-posture-row" }, postureChip(p, () => swap(() => openPosture(p))),
        h("span", { class: "muted small" }, (p.meta.posture ? "Change it" : "Choose one")
          + " in its own dialog: it previews what changes now and later before anyone saves, and a change that loosens it needs a "
          + orList(((S.meta && S.meta.postures) || {}).looseners || []) + "."))),
    // What runs this project's builder and verifier, and its assurance (D-0019): chosen in Settings > Runners, approved by IT.
    h("div", { class: "field chg-runner" }, h("span", { class: "label-h" }, "Cell runners"), runnerBox),
    field("ps-reason", "Reason (required, recorded with your name)", reason),
    impact, redoRow,
    h("div", { class: "btns" }, preview, save),
    mayChange() ? null : h("p", { class: "muted small" }, "A " + orList(changers()) + " persona changes a project's settings."),
    h("div", { class: "chg-more" }, h("span", { class: "muted small" }, "Or:"),
      h("button", { type: "button", class: "btn small", "data-control": "rewind_project", "data-key": "ps-rewind",
        onclick: () => swap(() => openRewind(p)) }, icon("undo"), h("span", { class: "lbl" }, "Go back a step")),
      h("button", { type: "button", class: "btn small", "data-control": "add_material", "data-key": "ps-material",
        onclick: () => swap(() => openMaterial(p)) }, icon("upload"), h("span", { class: "lbl" }, "Add material"))));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (shown !== JSON.stringify(values())) { say("Preview the impact first: the values changed since.", "warning"); preview.focus(); return; }
    if (!reason.value.trim()) { say("A settings change needs a reason: it is recorded with your name.", "warning"); reason.focus(); return; }
    if (!needPerson()) return;
    act(form, async () => {
      const out = await api("PUT", base(pid) + "/settings", Object.assign(values(), { reason: reason.value.trim(), redo: redo.checked }, signed()));
      const what = Object.keys(out.changed).map((f) => FIELD_LABEL[f].toLowerCase()).join(", ");
      await done(p.meta.title + ": " + what + " changed, signed by " + S.person.trim() + "."
        + (out.rewound ? " It went back to " + STEP_LABEL[out.rewound.to] + "." : "")
        + (out.assumed && out.assumed.length ? " " + plural(out.assumed.length, "question") + " assumed." : ""));
    });
  });
  openModal("Project settings · " + p.meta.title, form, { icon: "sliders", wide: true });
  projectRunnerLine(runnerBox, pid);
}

function drawImpact(box, redoRow, out) {
  const changes = Object.entries(out.changes || {});
  if (!changes.length) {
    fill(box, h("p", { class: "muted small" }, "Nothing changes: every value is the one the project has."));
    redoRow.hidden = true;
    return;
  }
  fill(box, h("h3", { class: "label-h" }, "What the change means"),
    h("ul", { class: "plain small chg-changes" }, changes.map(([f, c]) => h("li", null, h("b", null, FIELD_LABEL[f] + ": "),
      label(f, c.from), " → ", label(f, c.to)))),
    h("ul", { class: "chg-list" }, (out.impact || []).map((r) => h("li", { "data-what": r.what }, r.says))),
    out.questions ? keepsLine(out.questions) : null);
  const label2 = $("label", redoRow);
  if (out.rewind) {
    label2.textContent = "Also go back to " + STEP_LABEL[out.rewind] + " now. It undoes " + out.undoes + ".";
  } else if ((out.assumes || []).length) {
    label2.textContent = "Also let the factory assume " + plural(out.assumes.length, "open question") + " now, in your name.";
  }
  redoRow.hidden = !(out.rewind || (out.assumes || []).length);
}
function label(f, v) {
  if (f === "build_without_waiting") return v ? "on" : "off";
  return f === "kind" ? profileOf(v).label : String(v);
}
// A new kind going back to the questions: what a person chose is kept, the factory's own assumptions are withdrawn.
function keepsLine(q) {
  return h("p", { class: "small chg-keeps", "data-key": "ps-keeps" },
    h("b", null, "Kept: "), plural(q.kept_answers, "answer") + " and " + plural(q.kept_assumptions, "assumption") + " a person chose. ",
    h("b", null, "Withdrawn: "), plural(q.withdrawn_open, "open question") + " and " + plural(q.withdrawn_assumptions, "assumption")
      + " the factory made on its own, made for the old kind.");
}

// -- Go back a step ------------------------------------------------------------------------------------------

export function openRewind(p, preset) {
  const pid = p.meta.id;
  const steps = ((p.change || {}).steps) || [];
  const possible = steps.filter((s) => !s.refused);
  let chosen = (possible.find((s) => s.to === preset) || possible[possible.length - 1] || {}).to || null;
  const list = h("div", { class: "chg-steps", role: "radiogroup", "aria-label": "The step to go back to" }, steps.map((s) => {
    const id = "rw-" + s.to;
    const input = h("input", { type: "radio", name: "rw-step", id, value: s.to, "data-key": "rw:" + s.to, disabled: !!s.refused, checked: s.to === chosen });
    input.addEventListener("change", () => { chosen = s.to; });
    return h("div", { class: "chg-step" + (s.refused ? " off" : "") }, input,
      h("label", { for: id }, h("b", null, "Back to " + STEP_LABEL[s.to]), h("span", { class: "muted small" }, "Undoes " + s.undoes + "."),
        s.refused ? h("span", { class: "small chg-why" }, s.refused)
          : h("span", { class: "small" }, (s.sets_aside.length ? "Sets aside, kept as superseded: " + s.sets_aside.join(", ") + ". " : "")
            + (s.withdraws.length ? "Withdraws " + s.withdraws.join(", ") + ". " : "") + s.keeps + ".")));
  }));
  const reason = h("input", { id: "rw-reason", "data-key": "rw-reason", maxlength: "2000", autocomplete: "off",
    placeholder: "for example: the spec was written for the wrong kind of work" });
  const go = h("button", { type: "submit", class: "btn human primary", "data-key": "rw:go", disabled: !possible.length || !mayChange() }, icon("undo"), "Go back");
  const form = h("form", { class: "chg-form", novalidate: true, "aria-label": "Go back a step in " + p.meta.title },
    h("p", { class: "muted small" }, "The step runs again at the next Advance. What it sets aside moves to the project's superseded folder: nothing is deleted, and the ledger records who went back and why. A released project changes through the change loop instead."),
    list, field("rw-reason", "Reason (required, recorded with your name)", reason),
    h("div", { class: "btns" }, go),
    mayChange() ? null : h("p", { class: "muted small" }, "A " + orList(changers()) + " persona sends a project back a step."));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!chosen) return;
    if (!reason.value.trim()) { say("Going back needs a reason: it is recorded with your name.", "warning"); reason.focus(); return; }
    if (!needPerson()) return;
    act(form, async () => {
      const out = await api("POST", base(pid) + "/rewind", Object.assign({ to: chosen, reason: reason.value.trim() }, signed()));
      await done(p.meta.title + " went back to " + STEP_LABEL[out.to] + ", signed by " + S.person.trim() + ": " + out.then + ".");
    });
  });
  openModal("Go back a step · " + p.meta.title, form, { icon: "undo", wide: true });
}

// -- Add material ----------------------------------------------------------------------------------------------

export function openMaterial(p) {
  const pid = p.meta.id;
  const added = ((p.change || {}).material) || [];
  const text = h("textarea", { id: "mt-text", "data-key": "mt-text", rows: "6", maxlength: "200000",
    placeholder: "Paste more of the request: notes from a meeting, a spec section, a customer's email." });
  const path = h("input", { id: "mt-path", "data-key": "mt-path", maxlength: "2000", autocomplete: "off", spellcheck: "false",
    placeholder: "or a file or folder on the cockpit's machine, for example C:\\work\\request.md" });
  const note = h("input", { id: "mt-note", "data-key": "mt-note", maxlength: "300", autocomplete: "off", placeholder: "for example: the desk booking rules" });
  const again = h("input", { type: "checkbox", id: "mt-reintake", "data-key": "mt-reintake", checked: true });
  const submit = h("button", { type: "submit", class: "btn human primary", "data-key": "mt-add", disabled: !adders().includes(S.persona) }, icon("upload"), "Add the material");
  const form = h("form", { class: "chg-form", novalidate: true, "aria-label": "Add material to " + p.meta.title },
    h("p", { class: "muted small" }, "The original request is kept; the material is added after it under its own heading, and the ledger records it."),
    field("mt-text", "Material (text)", text), field("mt-path", "Or a path", path, "Read the way the intake reads a file or a folder."),
    field("mt-note", "What it is (optional)", note),
    h("div", { class: "chg-redo" }, again, h("label", { for: "mt-reintake" }, "Let the panel read it now (re-intake): new questions for what is new; every answer stays.")),
    h("div", { class: "btns" }, submit),
    added.length ? h("section", { "aria-labelledby": "mt-h" }, h("h3", { id: "mt-h", class: "label-h" }, "Added so far"),
      h("ul", { class: "plain small" }, added.map((a) => h("li", null, "Material " + a.n + (a.note ? ": " + a.note : "") + " · " + a.chars + " characters, by " + a.by)))) : null);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const body = { text: text.value, path: path.value.trim(), note: note.value.trim(), reintake: again.checked };
    if (!body.text.trim() && !body.path) { say("Give the material as text or as a path.", "warning"); text.focus(); return; }
    if (!needPerson()) return;
    act(form, async () => {
      const out = await api("POST", base(pid) + "/material", Object.assign(body, signed()));
      await done("Material " + out.n + " added to " + p.meta.title + " by " + S.person.trim() + "."
        + (out.job ? " The panel reads it in job " + out.job.id + "." : ""));
    });
  });
  openModal("Add material · " + p.meta.title, form, { icon: "upload", wide: true });
}

// -- What's next ---------------------------------------------------------------------------------------------------

function canAct(a) { return !a.personas || !a.personas.length || a.personas.includes(S.persona); }

async function post(pid, path, body) {
  if (!needPerson()) return null;
  return api("POST", base(pid) + path, Object.assign(body || {}, signed()));
}

function runAction(p, a, btn) {
  const pid = p.meta.id;
  const openers = { project_settings: () => openSettings(p), rewind_project: () => openRewind(p, a.step), add_material: () => openMaterial(p) };
  if (openers[a.control]) return openers[a.control]();
  if (a.control === "advance") {
    return act(btn.parentNode, async () => {
      const out = await post(pid, "/advance");
      if (!out) return;
      say("Job " + out.job.id + " started by " + S.person.trim() + ".", "good");
      if (nav.rerender) await nav.rerender();
    });
  }
  if (a.control === "go_ahead") {      // the look at the spec before the first build: Go or Skip, signed like any decision
    return act(btn.parentNode, async () => {
      const out = await post(pid, "/cards/" + enc(a.card) + "/decide", { verdict: a.verdict, reason: a.label });
      if (!out) return;
      say(a.card + ": " + a.label + ", signed by " + S.person.trim() + ".", "good");
      if (nav.rerender) await nav.rerender();
    });
  }
  if (a.control === "resume") {
    return act(btn.parentNode, async () => { if (await post(pid, "/resume")) { say(p.meta.title + " resumed.", "good"); if (nav.rerender) await nav.rerender(); } });
  }
  if (a.control === "autonomy" || a.control === "pause") {
    const el = $('[data-control="' + a.control + '"]');
    return el ? el.click() : null;
  }
  if (a.control === "modules" || a.page) { location.hash = "#/" + (a.page || "settings"); return null; }
  if (a.view) location.hash = link(pid, a.view, a.question || a.card || null);
  return null;
}

export function nextStrip(p) {
  const nx = p.next;
  if (!nx) return null;
  const pid = p.meta.id;
  const acts = nx.actions || [];
  const buttons = acts.filter((a) => a.control || a.view || a.page).map((a, i) => {
    const ok = canAct(a);
    const target = a.question || a.card || a.step;
    const look = a.control === "go_ahead";      // Go and Skip on the look at the spec stand out as a person's act
    const b = h("button", Object.assign({ type: "button", class: "btn small" + (look ? " human" : "") + (i === 0 && ok ? " primary" : ""),
      "data-key": "next:" + a.id + (target ? ":" + target : ""),
      disabled: !ok, tip: ok ? null : "A " + orList(a.personas) + " persona can" }, look ? { "data-control": "go_ahead" } : {}),
    h("span", { class: "lbl" }, a.label));
    b.addEventListener("click", () => runAction(p, a, b));
    return b;
  });
  const commands = acts.filter((a) => !a.control && !a.view && !a.page);
  return h("section", { class: "section panel next-strip", "data-control": "next_step", "aria-labelledby": "next-h" },
    h("div", { class: "next-top" }, h("h3", { id: "next-h", class: "label-h" }, icon("arrow-right"), " What's next"),
      chip("neutral", "users", nx.who.includes("the factory") ? "The factory"
        : nx.who.length >= (S.personas || []).length ? "Anyone can act" : "Who can act: " + orList(nx.who))),
    h("p", { class: "next-wait" }, "Waits for " + nx.waits_for + "."),
    buttons.length ? h("div", { class: "btns next-btns" }, buttons) : null,
    commands.length ? h("ul", { class: "plain small" }, commands.map((a) => h("li", null, h("b", null, a.label + ": "),
      a.command ? h("code", null, a.command) : null, a.where ? h("span", { class: "muted" }, " · " + a.where) : null))) : null);
}
