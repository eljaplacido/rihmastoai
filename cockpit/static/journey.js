/* Guided journeys (FR-JRN1, kernel/journeys.py, docs/guides/guided-journeys.md): the real ways through Rihmasto,
   step by step, measured from the records.

   - In Ask Rihma, an answer about a journey shows where you are, the next step with its button and its command,
     the remaining steps folded, and Guide me step by step.
   - The guided panel sits at the top of Ask Rihma and stays with you across views and after a reload (it is kept
     on the server per person): the current step highlighted with Do it, I did it, Skip and Stop, and each step's
     result shown when it completes. Do it runs the step through its own route, signed with your name (Run the
     assessment, Read the repository, Set up the watch), starts the walkthrough that does it (the folder, the
     scan, Adopt), or opens the place where you do it with the control highlighted.
   - A project's Overview carries a Next step card, and an empty Home or Projects page offers the three ways in. */

import { S, $, h, fill, icon, api, act, say, signed, needPerson, nav, enc, button, AuthError } from "./core.js";
import { openAssistant, takeThere } from "./assistant.js";
import { datum } from "./words.js";

const G = { view: null, timer: 0, states: null, results: [], loading: false };
const POLL_MS = 3000;
const ICON = { brownfield: "plug", new_idea: "lightbulb", documents: "file-check", model: "cpu", ide: "code",
  deploy: "package", automations: "refresh" };
const STATE_ICON = { done: "check-circle", skipped: "chevron-right", under_way: "clock", todo: "dashed" };
// The route each step's Do it is carried out by: the same route as its button in the cockpit, signed.
const DO = {
  assess: (pid) => ["/api/projects/" + enc(pid) + "/assessment", {}],
  align: (pid) => ["/api/projects/" + enc(pid) + "/repo-alignment/scan", {}],
  watch: (pid) => ["/api/projects/" + enc(pid) + "/watch", {}],
};

function personQ() { return "person=" + encodeURIComponent(S.person.trim()) + "&persona=" + encodeURIComponent(S.persona || ""); }
function guiding() { return !!(G.view && G.view.guide && G.view.guide.state === "active"); }
function nextOf(prog) { return (prog.steps || []).find((s) => s.id === prog.next) || null; }

// -- doing a step -------------------------------------------------------------------------------------------------

export async function doStep(s, pid, block) {
  const a = (s && s.action) || {};
  if (a.do && pid && DO[a.do]) {
    if (!needPerson()) return;
    await act(block, async () => {
      const [path, body] = DO[a.do](pid);
      const out = await api("POST", path, Object.assign(body, signed()));
      const running = out && out.run && out.run.state === "running";
      // A step that runs in the background is started, not done: say so, and open its view, where its live
      // progress shows (FR-PRG1); the guide marks it done when its record says so.
      say(s.title + (running ? ": started, signed by " + S.person.trim() + ". Its progress shows here; the guide moves on when it ends."
        : ": done, signed by " + S.person.trim() + "."), "good");
      if (a.route) takeThere({ route: a.route, control: null });       // its result, or its live progress
      await refresh();
    });
    return;
  }
  if (a.walkthrough && nav.walk) { await nav.walk.start(a.walkthrough); return; }
  takeThere({ route: a.route || null, control: a.control || null });
}

async function mark(how, block) {
  if (!guiding() || !needPerson()) return;
  const step = nextOf(G.view.progress);
  if (!step) return;
  await act(block, async () => take(await api("POST", "/api/journeys/guide", Object.assign({ action: how, step: step.id }, signed()))));
}

export async function startGuide(name, pid) {
  if (!needPerson()) return;
  openAssistant();
  await act($("#as-guide") || $("#as-log"), async () => {
    take(await api("POST", "/api/journeys/guide", Object.assign({ action: "start", journey: name, project: pid || "" }, signed())));
  });
}

async function stopGuide(block) {
  if (!guiding() || !needPerson()) return;
  await act(block, async () => take(await api("POST", "/api/journeys/guide", Object.assign({ action: "stop" }, signed()))));
}

// -- the guided panel ----------------------------------------------------------------------------------------------

function take(out) {
  const was = G.states;
  G.view = out && out.guide;
  const prog = (G.view && G.view.progress) || null;
  const now = prog ? Object.fromEntries(prog.steps.map((s) => [s.id, s.state])) : null;
  if (was && now && G.view.guide.state === "active") {      // a step that completed since: its result is shown
    prog.steps.filter((s) => s.state === "done" && was[s.id] !== "done").forEach((s) => G.results.push(s));
    G.results = G.results.slice(-3);
  }
  G.states = now;
  draw();
  poll();
}

export async function refresh() {
  if (!S.person.trim() || G.loading) return;
  G.loading = true;
  try { take(await api("GET", "/api/journeys/guide?" + personQ())); } catch (e) { if (!(e instanceof AuthError)) G.view = G.view || null; } finally { G.loading = false; }
}

function poll() {
  clearTimeout(G.timer);
  if (!guiding()) return;
  G.timer = setTimeout(() => { if (!document.hidden) refresh(); else poll(); }, POLL_MS);
}

function stepRow(s, current) {
  return h("li", { class: "jr-row " + s.state + (current ? " current" : ""), "aria-current": current ? "step" : null },
    icon(STATE_ICON[s.state] || "dashed"), h("span", null, h("b", null, s.title), s.optional ? h("small", { class: "muted" }, " optional") : null,
      s.said ? h("small", { class: "jr-said" }, datum(s.said)) : null));
}

function commandLine(s, key) {
  const cmd = String(s.command || "").split("   ")[0];
  if (!cmd) return null;
  return h("p", { class: "jr-cmd small" }, h("span", { class: "muted" }, "Or on the command line: "), h("code", { "data-key": key }, cmd));
}

function drawPanel(box) {
  const g = G.view;
  const prog = g.progress;
  const step = nextOf(prog);
  const pid = prog.project;
  const at = step ? prog.steps.indexOf(step) + 1 : prog.total;
  const results = G.results.map((s, i) => h("p", { class: "jr-result", role: "status", "data-key": "jr-result:" + i },
    icon("check-circle"), h("span", null, h("b", null, s.title + ": "), datum(s.said || "done"))));
  const doIt = step ? button(step.button, { icon: "play", kind: "small primary", key: "jr:do", "data-control": "journey_do",
    onclick: () => doStep(step, pid, box) }) : null;
  fill(box,
    h("div", { class: "jr-head" }, icon(ICON[prog.journey] || "flag"),
      h("div", { class: "jr-title" }, h("b", null, prog.label + (prog.title ? ": " + prog.title : "")),
        h("small", { class: "muted" }, prog.complete ? "Every step is done" : "Step " + at + " of " + prog.total + ", " + prog.done + " done")),
      button("Stop", { icon: "x", kind: "small quiet", key: "jr:stop", "data-control": "journey_stop", aria: "Stop guiding", onclick: () => stopGuide(box) })),
    results,
    step ? h("div", { class: "jr-now" },
      h("p", { class: "jr-step" }, h("b", null, step.title)),
      h("p", { class: "small" }, step.said || step.not_yet ? h("span", { class: "jr-state" }, datum((step.said || step.not_yet) + ". ")) : null, datum(step.why)),
      step.off ? h("p", { class: "small muted" }, icon("info"), " " + step.off) : null,
      h("div", { class: "btns" }, doIt,
        button("I did it", { icon: "check", kind: "small", key: "jr:did", "data-control": "journey_did", onclick: () => mark("did", box) }),
        button("Skip", { icon: "chevron-right", kind: "small quiet", key: "jr:skip", "data-control": "journey_skip", onclick: () => mark("skip", box) })),
      commandLine(step, "jr:cmd"),
      step.if_fails ? h("details", { class: "jr-fails small" }, h("summary", null, "If it fails"), h("p", null, datum(step.if_fails))) : null)
      : h("p", { class: "small" }, "That is every step. Ask what is next any time."),
    h("details", { class: "jr-all" }, h("summary", { "data-key": "jr:all" }, "All " + prog.total + " steps"),
      h("ol", { class: "jr-list" }, prog.steps.map((s) => stepRow(s, step && s.id === step.id)))));
}

function draw() {
  const dr = $("#assistant");
  if (!dr) return;
  let box = $("#as-guide");
  if (!box) {
    box = h("div", { class: "dr-guide", id: "as-guide", role: "region", "aria-label": "Guided journey" });
    dr.insertBefore(box, $("#as-log"));
  }
  box.hidden = !guiding();
  if (guiding()) drawPanel(box); else fill(box);
}

// -- an answer about a journey, in Ask Rihma ---------------------------------------------------------------------

function nextCard(prog, key, compact) {
  const step = nextOf(prog);
  const pid = prog.project;
  if (!step) return h("p", { class: "small" }, icon("check-circle"), " Every step of " + prog.label + " is done.");
  const box = h("div", { class: "jr-next" },
    h("p", { class: "jr-step" }, h("span", { class: "muted small" }, "Next: "), h("b", null, step.title)),
    compact ? null : h("p", { class: "small" }, datum(step.why)),
    step.off ? h("p", { class: "small muted" }, icon("info"), " " + step.off) : null);
  box.append(h("div", { class: "btns" },
    button(step.button, { icon: "play", kind: "small primary", key: key + ":do", onclick: () => doStep(step, pid, box) }),
    button("Guide me step by step", { icon: "flag", kind: "small", key: key + ":guide", "data-control": "journey_guide",
      onclick: () => startGuide(prog.journey, pid) })),
  commandLine(step, key + ":cmd"));
  return box;
}

function startersList(rows, key) {
  return h("ul", { class: "jr-starters", "data-control": "journey_starters" }, rows.map((j) => h("li", null,
    h("button", { type: "button", class: "wk-card", "data-key": key + ":" + j.name, onclick: () => startGuide(j.name, null) },
      icon(ICON[j.name] || "flag"), h("span", null, h("b", null, j.label), h("small", null, datum(j.about)))))));
}

export function journeyBlock(out, item) {
  const k = "jr:" + ((item && item.at) || "a");
  if (out.journey) {
    const prog = out.journey;
    return h("div", { class: "jr-block" }, nextCard(prog, k),
      h("details", { class: "jr-all" }, h("summary", { "data-key": k + ":all" }, "All " + prog.total + " steps, " + prog.done + " done"),
        h("ol", { class: "jr-list" }, prog.steps.map((s) => stepRow(s, s.id === prog.next)))));
  }
  if (out.starters) return h("div", { class: "jr-block" }, startersList(out.starters, k + ":start"));
  if (out.projects) {
    return h("ul", { class: "jr-projects" }, out.projects.map((r, i) => h("li", null,
      h("b", null, r.title), h("small", { class: "muted" }, " " + r.label + ", " + r.done + " of " + r.total + " done"),
      r.next ? h("div", { class: "btns" }, button(r.next.title, { icon: "arrow-right", kind: "small", key: k + ":p:" + i,
        onclick: () => doStep(r.next, r.project, null) })) : null)));
  }
  return null;
}

// -- the Overview's Next step card and the ways in ---------------------------------------------------------------

export function journeyCard(p) {
  const pid = p && p.meta && p.meta.id;
  const box = h("section", { class: "section panel jr-card", "data-control": "journey_next", "aria-labelledby": "jr-card-h" },
    h("h3", { id: "jr-card-h", class: "label-h" }, icon("flag"), " Next step"), h("p", { class: "muted small" }, "Reading where it is…"));
  if (!pid) return box;
  api("GET", "/api/journeys/next?project=" + enc(pid) + "&persona=" + encodeURIComponent(S.persona || "")).then((out) => {
    const prog = out.journey;
    fill(box, h("h3", { id: "jr-card-h", class: "label-h" }, icon(ICON[prog.journey] || "flag"), " Next step: " + prog.label),
      h("p", { class: "small" }, prog.done + " of " + prog.total + " steps done" + (prog.anchor ? "; it was " + prog.anchor : "") + "."),
      nextCard(prog, "jr-ov"));
  }).catch((e) => { if (!(e instanceof AuthError)) fill(box); });
  return box;
}

export function starters(where) {
  const box = h("div", { class: "jr-ways" }, h("p", { class: "small" }, h("b", null, "Three ways in. "), "Rihma guides you step by step, measured from what is really done."));
  api("GET", "/api/journeys?persona=" + encodeURIComponent(S.persona || "")).then((out) => {
    box.append(startersList(out.journeys.filter((j) => j.starter), "jr-ways:" + (where || "page")));
  }).catch(() => fill(box));
  return box;
}

// A walkthrough's link that runs a journey's step ("Run the assessment") or starts the guide ("Guide me through the rest").
export function runLink(l) {
  if (l.guide) return startGuide(l.guide, l.project);
  return doStep({ title: l.label, action: { do: l.do, route: l.route, control: l.control } }, l.project, null);
}

nav.journey = { block: journeyBlock, card: journeyCard, starters, runLink, refresh, start: startGuide, guiding };

// After a reload: the guide that was going is read again (kept on the server per person).
export function resumeGuide() {
  refresh();
  window.addEventListener("hashchange", () => { if (guiding()) refresh(); });
}
