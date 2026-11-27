/* The whole log of a run (FR-LND1). The owner (2026-11-26): "Last action is also small terminal view". The small
   boxes (a job's last lines, the running cell's last action) open the whole log at #/jobs/<job id>, or
   #/jobs/cell:<pid> for the cell building a task: all of it (a very long log from its last 256 KiB, saying so),
   following new output while the run goes on and the page is visible (Follow), Copy, and for a finished job what
   it changed, each with its place. Agent activity lists the runs to open (runsCard). Read from
   GET /api/run-log (kernel/run_log.py); reading changes nothing. */

import { S, h, icon, api, enc, button, chip, card, say, fmtAt, pageHead, plural, fill, $ } from "./core.js";
import { pick, emptyState } from "./words.js";

const EVERY = 2000;
const STATE_TONE = { running: "info", done: "good", failed: "critical", capped: "warning", unknown: "nm" };
const L = { timer: null, seq: 0 };

export function logRoute(spec) { return spec.job ? "#/jobs/" + enc(spec.job) : "#/jobs/cell:" + enc(spec.project); }
export function logLink(spec, label) {
  return h("a", { href: logRoute(spec), class: "btn tiny quiet run-log-open", "data-control": "run_log_open",
    "data-key": "log:" + (spec.job || "cell:" + spec.project) }, icon("expand"), h("span", { class: "lbl" }, label || "Open the whole log"));
}

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); say("The log is copied.", "good"); }
  catch (e) { say("Select the log and copy it by hand.", "warning"); }
}

function changedBlock(rows) {
  if (!rows) return null;
  return card({ title: pick("What it changed", "What the records gained"), icon: "check", id: "rl-changed" },
    rows.length ? h("ul", { class: "plain rl-changed" }, rows.map((r) => h("li", null, h("a", { href: r.route }, r.said),
      h("span", { class: "muted small" }, " · " + fmtAt(r.at)))))
      : emptyState("run_changed"));
}

/* The page: the whole log of a job, or the steps of the cell building a task. */
export async function renderRunLog(seq, id) {
  const main = $("#main");
  const cell = String(id).startsWith("cell:");
  const pid = cell ? String(id).slice(5) : null;
  const pre = h("pre", { class: "rl-out", role: "log", "aria-live": "off", tabindex: "0", "aria-label": "The whole log", "data-raw": "" });
  const follow = h("input", { type: "checkbox", id: "rl-follow", "data-key": "rl-follow", checked: true });
  const state = h("span", { class: "rl-state" });
  const note = h("p", { class: "small muted rl-note" });
  const after = h("div", { class: "rl-after" });
  let next = cell ? 0 : -1;
  let text = "";
  clearTimeout(L.timer);
  L.seq = seq;
  const head = pageHead(cell ? "The cell's log" : "The whole log", cell
    ? pick("Every step the AI build team takes on a task, as it happens, and kept once it stops.", "Every tool step of the running cell, or of the one that ran last, from Gnomon's audit trail.")
    : pick("Everything the run printed, as it happens.", "The job's whole output, followed while it runs."), {
    icon: "terminal", actions: [
      h("label", { class: "rl-follow small", for: "rl-follow" }, follow, " Follow new output"),
      button("Copy", { icon: "copy", kind: "small", key: "rl-copy", "data-control": "run_log_copy", onclick: () => copyText(text) }),
      h("a", { href: "#/jobs", class: "btn small quiet", "data-key": "rl-back" }, icon("chevron-left"), h("span", { class: "lbl" }, "Every job"))] });
  main.replaceChildren(head, h("p", { class: "rl-head" }, state), note, pre, after);
  document.title = (cell ? "Cell log" : "Log " + id) + " · Rihmasto";
  const tick = async () => {
    if (L.seq !== seq || S.seq !== seq) return;
    let d;
    try {
      d = await api("GET", "/api/run-log?" + (cell ? "project=" + enc(pid) : "job=" + enc(id)) + "&from=" + next);
    } catch (e) {
      if (L.seq !== seq) return;
      state.replaceChildren(chip("nm", "info", "not read"));
      note.textContent = "The log could not be read: " + e.message;
      return;
    }
    if (L.seq !== seq || S.seq !== seq) return;
    let running;
    if (cell) {
      running = !!d.running && !d.ended;
      // a cell that stopped keeps its whole log, and what its round changed (FR-LND2)
      const said = running ? "building " + (d.task || "") : d.finished ? "finished " + (d.task || "") : "not running";
      fill(state, chip(running ? "info" : d.finished ? "good" : "nm", running ? "activity" : d.finished ? "check" : "info", said),
        d.model ? h("span", { class: "small muted" }, " " + (d.role || "cell") + " · " + d.model) : null,
        d.finished && d.at ? h("span", { class: "small muted" }, " · " + fmtAt(d.at)) : null);
      if (d.lines.length) text += (text ? "\n" : "") + d.lines.join("\n");
      next = d.next;
      note.textContent = d.why || (d.steps ? plural(d.steps, "step") + " so far." : "");
      if (d.finished && d.changed && !after.childElementCount) after.replaceChildren(changedBlock(d.changed));
    } else {
      const j = d.job;
      running = j.state === "running";
      state.replaceChildren(h("b", null, j.title || j.kind + " " + j.project), " ", chip(STATE_TONE[j.state] || "nm", null, j.state),
        h("span", { class: "small muted" }, " · started " + fmtAt(j.started)));
      text += d.text;
      next = d.next;
      note.textContent = d.exists ? (d.skipped ? "The first " + Math.round(d.skipped / 1024) + " KiB are left out: this shows the rest." : "")
        : d.why;
      if (!running && d.changed && !after.childElementCount) after.replaceChildren(changedBlock(d.changed));
    }
    const atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8;
    pre.textContent = text || (running ? "Waiting for the first output…" : "It printed nothing.");
    if (follow.checked && (atEnd || running)) pre.scrollTop = pre.scrollHeight;
    if (running && !document.hidden) L.timer = setTimeout(tick, EVERY);
    else if (running) L.timer = setTimeout(tick, EVERY * 3);
  };
  await tick();
}

/* Agent activity's card: the runs to open the whole log of. */
export function runsCard() {
  const body = h("div", { "data-control": "run_log_open" }, h("p", { class: "small muted" }, "Reading the runs…"));
  api("GET", "/api/run-log").then((d) => {
    const runs = d.runs || [];
    body.replaceChildren(runs.length ? h("ul", { class: "plain rl-runs" }, runs.map((r) => h("li", { class: "rl-run" },
      chip(STATE_TONE[r.state] || "nm", r.kind === "cell" ? "activity" : "terminal", r.state), " ", h("b", null, r.title),
      h("span", { class: "muted small" }, " · " + r.project + (r.started ? " · " + fmtAt(r.started) : "")), " ",
      logLink(r.kind === "cell" ? { project: r.project } : { job: r.id }, "Open the log"))))
      : emptyState("runs"));
  }).catch((e) => body.replaceChildren(h("p", { class: "small muted" }, "The runs could not be read: " + e.message)));
  return card({ title: "Runs and their logs", icon: "terminal", id: "aa-runs" }, body);
}
