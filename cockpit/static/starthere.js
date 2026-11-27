/* Start here (FR-LND1): the top of a project's first view says in one line what Rihmasto understood the project to
   be (with Correct it), the one to three things to do now from its real state, each a button that opens the place
   and points at the control that does it, and what Rihmasto does on its own meanwhile. Read by rule
   (GET /api/projects/<pid>/start-here, kernel/start_here.py); a person may hide it for themselves (recorded, and it
   comes back by itself when a new step appears). Ask Rihma's "what should I do here?" answers with the same steps. */

import { S, h, icon, api, enc, button, signed, needPerson, act, say, nav } from "./core.js";
import { pick, datum, emptyState } from "./words.js";
import { openAssistant, send as askRihma, takeThere } from "./assistant.js";
import { openHandoff } from "./goal.js";

const CONTROL_DOES = {   // a step whose control opens a dialog right here does it, not only takes you there
  handoff: (pid) => openHandoff(pid, {}),
};

function go(pid, s) {
  const run = CONTROL_DOES[s.control];
  if (run) { run(pid); return; }
  takeThere({ route: s.route, control: s.control || null });
}

function stepItem(pid, s, i) {
  return h("li", { class: "sh-step", "data-step": s.id },
    h("span", { class: "sh-n", "aria-hidden": "true" }, String(i + 1)),
    h("div", { class: "sh-what" }, h("b", { "data-ud": "" }, s.label), h("p", { class: "small muted", "data-ud": "" }, s.why),
      (s.findings || []).length ? h("ul", { class: "sh-find small" }, s.findings.map((f) =>
        h("li", null, f.severity ? h("span", { class: "chip neutral" }, h("span", null, f.severity)) : null, " ", datum(f.title)))) : null),
    button(i === 0 ? "Do this now" : "Open", { icon: "arrow-right", kind: "small" + (i === 0 ? " primary" : ""),
      key: "sh-go:" + s.id, "data-control": "start_here", onclick: () => go(pid, s) }));
}

function meanwhileBlock(pid, mw) {
  if ((mw.rows || []).length) {
    return h("div", { class: "sh-mw" }, h("h4", { class: "label-h" }, pick("Meanwhile, without you", "Meanwhile, on its own")),
      h("ul", { class: "small" }, mw.rows.map((r) => h("li", null, h("a", { href: r.route }, datum(r.what)),
        r.log ? [" · ", h("a", { href: logHref(r.log), "data-control": "run_log_open" }, "open the log")] : null))));
  }
  const n = mw.none;
  return h("div", { class: "sh-mw" }, h("h4", { class: "label-h" }, "Meanwhile"),
    h("p", { class: "small muted" }, n ? n.why + "." : "Nothing runs on its own here yet."),
    n ? button(n.label, { icon: "plus", kind: "small quiet", key: "sh-mw", "data-control": "start_here", onclick: () => go(pid, n) }) : null);
}

function logHref(log) { return log.job ? "#/jobs/" + enc(log.job) : "#/jobs/cell:" + enc(log.project); }

async function choose(pid, hide, box) {
  if (!needPerson()) return;
  await act(box, async () => {
    await api("POST", "/api/projects/" + enc(pid) + "/start-here", Object.assign({ hide }, signed()));
    say(hide ? "Start here is hidden for you. It comes back when something new needs doing, or with Show Start here." : "Start here is shown again.", "good");
    await draw(box, pid);
  });
}

function hiddenLine(pid, box) {
  return h("p", { class: "sh-hidden small muted" }, icon("eye"), " Start here is hidden for you. ",
    button("Show Start here", { kind: "tiny quiet", key: "sh-show", "data-control": "start_here_hide", onclick: () => choose(pid, false, box) }));
}

function render(pid, d, box) {
  if (!d.applies) return null;
  if (d.hidden) return hiddenLine(pid, box);
  const u = d.understood;
  const steps = d.steps || [];
  return h("section", { class: "card start-here", "aria-labelledby": "sh-h", "data-control": "start_here" },
    h("header", { class: "card-head" }, h("span", { class: "card-ic" }, icon("flag")),
      h("h3", { class: "card-t", id: "sh-h" }, "Start here"),
      (d.new || []).length ? h("span", { class: "chip accent" }, h("span", null, "new since you hid it")) : null,
      h("span", { class: "card-tools" }, button("Hide", { icon: "x", kind: "tiny quiet", key: "sh-hide", aria: "Hide Start here for you",
        "data-control": "start_here_hide", onclick: () => choose(pid, true, box) }))),
    h("p", { class: "sh-u" }, h("span", { class: "muted small" }, pick("What we understood: ", "Understood: ")),
      h("span", { "data-ud": "" }, u.line), " ",
      button("Correct it", { icon: "edit", kind: "tiny quiet", key: "sh-correct", "data-control": "start_here",
        onclick: () => takeThere({ route: u.correct.route, control: u.correct.control }) })),
    h("p", { class: "muted small" }, "From " + u.basis + ", by rule."),
    steps.length ? h("ol", { class: "sh-steps", "aria-label": "What to do now" }, steps.map((s, i) => stepItem(pid, s, i)))
      : emptyState("start_here", null, { what: "Nothing waits on you here now." }),
    meanwhileBlock(pid, d.meanwhile || { rows: [] }),
    h("p", { class: "sh-ask small" }, button("Ask Rihma what to do here", { icon: "bot", kind: "tiny quiet", key: "sh-ask", "data-control": "start_here",
      onclick: () => { openAssistant(); askRihma("What should I do here?"); } })));
}

async function draw(box, pid) {
  const q = "?persona=" + enc(S.persona) + (S.person.trim() ? "&person=" + enc(S.person.trim()) : "");
  let d;
  try { d = await api("GET", "/api/projects/" + enc(pid) + "/start-here" + q); } catch (e) {
    box.replaceChildren(h("p", { class: "small muted" }, "Start here could not be read: " + e.message));
    return;
  }
  const el = render(pid, d, box);
  box.replaceChildren(...(el ? [el] : []));
}

/* The panel for the top of a project's first view: drawn as soon as its record is read. Entering a project on a
   phone, the tall project header would leave its first step below the first screen (FR-LND2): the page then starts
   at Start here, the header one scroll up. */
const NARROW = "(max-width: 640px)";
export function startHerePanel(p, opts = {}) {
  const pid = p.meta.id;
  const box = h("div", { class: "sh-box", "data-panel": "start_here" });
  draw(box, pid).then(() => {
    if (!opts.entering || !box.isConnected || !box.querySelector(".start-here") || !window.matchMedia(NARROW).matches) return;
    const seq = S.seq;
    requestAnimationFrame(() => { if (S.seq === seq && box.isConnected) box.scrollIntoView({ block: "start" }); });
  });
  return box;
}

/* Under Ask Rihma's answer to "what should I do here?": each step its own button, as on the panel. */
function chatBlock(out, idx) {
  // a coding agent's sync plan (kernel/agent_sync_chat.py, FR-LND2) has its steps as buttons too
  const d = out.start_here || (out.sync_plan ? { applies: true, project: out.project, steps: out.sync_plan } : {});
  const pid = d.project;
  if (!d.applies || !(d.steps || []).length) return null;
  return h("ol", { class: "as-steps sh-chat" }, d.steps.map((s, i) => h("li", null, h("span", null, s.label + ": " + s.why + "."),
    h("div", { class: "btns" }, button(i === 0 ? "Do this now" : "Open", { icon: "arrow-right", kind: "small" + (i === 0 ? " primary" : ""),
      key: "sh-chat:" + idx + ":" + i, "data-control": "start_here", onclick: () => go(pid, s) })))));
}
nav.startHere = { block: chatBlock };
