/* What Ask Rihma talks about (FR-UXO1). The owner: "When I talk to the assistant it's not clear whether it comments
   on the entire platform, where I'm right now, or a specific project."

   A scope line at the top of the chat says it ("Talking about: Home and Horizon · Inbox", or "all projects"); it
   follows the page and can be switched: this view, this project, or the whole platform. Each answer carries the
   scope it was given in, and says so when the question named another project and Rihma switched to it. The
   conversation is kept per project (and one for the whole platform). A how-to answer's steps are numbered, each
   command with a Copy button, and the step that opens the place has the action button (Take me there). */

import { S, h, icon, store, say, button } from "./core.js";
import { labelOf } from "./capsules.js";
import { projectTitle, scopedLabel } from "./scope.js";
import { viewLayoutIntent, describeIntent, previewIntent, keepIntent, undoIntent, previewingView } from "./viewcustom.js";

const MODES = [["view", "This view"], ["project", "This project"], ["platform", "Whole platform"]];
function mode() { const m = store.get("gf.askscope") || "view"; return MODES.some(([k]) => k === m) ? m : "view"; }
function setMode(m) { store.set("gf.askscope", m); }

function here() {
  const r = S.route || {};
  const inProject = r.name === "project";
  const view = inProject ? (S.projectViews || {}).current || r.view || "overview" : r.name;
  return { inProject, pid: inProject ? r.pid : null, view };
}
/* What a question asked now is about: the project and the view sent with it, and how the line says it. */
export function askScope() {
  const m = mode();
  const at = here();
  if (m === "platform" || !at.inProject) {
    const page = !at.inProject && m === "view" && at.view && at.view !== "home" ? scopedLabel(at.view) : null;
    return { mode: at.inProject ? m : (m === "platform" ? "platform" : "view"), project: null,
      view: m === "platform" ? null : at.view, label: page ? "all projects · " + page : "all projects" };
  }
  const title = projectTitle(at.pid);
  return m === "project" ? { mode: m, project: at.pid, view: null, label: title }
    : { mode: m, project: at.pid, view: at.view, label: title + " · " + labelOf(at.view) };
}
// The conversation's key: one per persona and project, and one for the whole platform.
export function convKey() {
  const s = askScope();
  return "gf.assistant." + (S.persona || "-") + "." + (s.project || "-");
}

export function scopeLine(onChange) {
  const s = askScope();
  const at = here();
  const pick = h("select", { id: "as-scope-pick", "data-control": "assistant_scope", "aria-label": "What Rihma talks about" },
    MODES.filter(([k]) => at.inProject || k !== "project").map(([k, l]) => h("option", { value: k, selected: k === s.mode }, at.inProject || k !== "view" ? l : "This page")));
  pick.addEventListener("change", () => { setMode(pick.value); onChange(); });
  return [h("span", { class: "as-scope-t" }, icon(s.project ? "folder" : "layers"), h("span", null, "Talking about: "), h("b", null, s.label)), pick];
}

/* The line above an answer: what it was about, and that Rihma switched when the question named another project. */
export function answerScope(out, asked) {
  const sc = out.scope || {};
  const about = sc.project ? (sc.title || sc.project) + (sc.view ? " · " + labelOf(sc.view) : "") : "all projects";
  return h("p", { class: "as-about" + (sc.switched ? " switched" : "") }, icon(sc.switched ? "arrow-right" : sc.project ? "folder" : "layers"),
    sc.switched ? h("span", null, "You named ", h("b", null, about), (asked && asked.project ? ", so I switched to it from " + projectTitle(asked.project) : ", so I answer about it") + ".")
      : h("span", null, "About ", h("b", null, about)));
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); say("Copied: " + text, "good"); }
  catch (e) { say("Select the command and copy it by hand.", "warning"); }
}
/* A how-to answer's steps: numbered, a command each with Copy, and the action that opens the place. */
export function stepsBlock(out, idx, go) {
  const steps = out.steps || [];
  if (!steps.length) return null;
  return h("ol", { class: "as-steps" }, steps.map((s, i) => h("li", null, h("span", null, s.text),
    (s.commands || []).map((c, j) => h("div", { class: "as-cmd" }, h("code", null, c),
      button("Copy", { icon: "copy", kind: "tiny quiet", key: "cmd:" + idx + ":" + i + ":" + j, aria: "Copy the command " + c, onclick: () => copy(c) }))),
    s.action === "navigate" && go ? h("div", { class: "btns" }, button("Take me there", { icon: "arrow-right", kind: "small primary",
      key: "go:" + idx, onclick: go })) : null)));
}

/* A layout change for the view on screen, asked in words: answered here, with Preview, then Keep or Undo. */
export function localAnswer(q) {
  const it = viewLayoutIntent(q);
  if (!it) return null;
  return { answer: describeIntent(it) + " on this view: Preview shows it, then Keep or Undo. It is kept for you only.",
    viewLayout: it, propose: [], dropped: [], sources: [], by: "map", scope: { project: askScope().project, title: askScope().project ? projectTitle(askScope().project) : null, view: here().view } };
}
export function layoutBlock(item, save, rerender) {
  const it = item.out.viewLayout;
  const state = item.out.layoutState;
  const set = (st) => { item.out.layoutState = st; save(); rerender(); };
  if (state === "kept") return h("p", { class: "prop-st" }, icon("check"), " Kept: this view's layout is saved for you.");
  if (state === "undone") return h("p", { class: "prop-st muted" }, icon("undo"), " Previewed, then undone: nothing was kept.");
  if (state === "preview" && previewingView()) {
    return h("div", { class: "prop" }, h("p", { class: "prop-st" }, icon("eye"), " Shown as a preview on this view."),
      h("div", { class: "btns" }, button("Keep", { icon: "check", kind: "small primary", key: "vl:keep", onclick: () => { keepIntent(); set("kept"); } }),
        button("Undo", { icon: "undo", kind: "small quiet", key: "vl:undo", onclick: () => { undoIntent(); set("undone"); } })));
  }
  return h("div", { class: "prop" }, h("div", { class: "prop-h" }, icon("sliders"), h("b", null, describeIntent(it))),
    h("div", { class: "btns" }, button("Preview", { icon: "eye", kind: "small primary", key: "vl:preview", onclick: () => {
      if (previewIntent(it)) set("preview"); else say("Open the view first: the change is for the view on screen.", "warning");
    } })));
}
