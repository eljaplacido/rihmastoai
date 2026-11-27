/* A project: its header (profile, stages, health, now, autonomy cap, pause and resume), its views in
   the order its stage and the lens bring them forward, and every view's decisions and evidence.
   Also the Projects list, the Insight (Floor) page and Jobs. Every write is signed and goes through
   the same routes as before; the kernel decides whether it stands. */

import {
  S, $, $$, h, fill, icon, chip, store, api, act, say, signed, needPerson, AuthError, nav, enc, link,
  personaLabel, decides, orList, stageName, bandOf, fmtAt, short, cap, plural, num, pct, fmtMoney, fmtCost,
  fmtMinutes, sepList, personBadge, agentBadge, actorBadge, linkIds, evChip, nowChip, healthChip,
  KIND_LABEL, KIND_ICON, VERDICT_LABEL, CLASS_LABEL, PERSPECTIVE_LABEL, EVIDENCE, EVIDENCE_ORDER, HEALTH, BRAND,
  FACTORY_PID, FACTORY_VIEWS, STAGE_VIEW, STAGE_ICON, VIEWS, button, iconButton, infoButton, card, segmented,
  pageHead, empty, skeleton, viewChoice, setViewChoice, attachTip, openModal, closeModal, avatar, ago, download,
  profileOf, mayAct, inboxPersona, everything,
} from "./core.js";
import { waterfall, dataTable, tipBox, bars } from "./charts.js";
import { ATTEST, liveState } from "./widgets.js";
import { intakeSummary } from "./inputs.js";
import { elsewhereNote } from "./elsewhere.js";   // decisions that wait on another role held (FR-ENF2)
import { trackPill, trackState, viewTrack } from "./track.js";
import { viewOutputs } from "./outputs.js";
import { viewOn, moduleShows } from "./modules.js";
import { changeButtons, nextStrip, openMaterial } from "./change.js";
import { sourcesPanel } from "./sources.js";   // a project's own sources (FR-SRC1)
import { agentsStrip, viewAgents, channelPanelButton } from "./agents.js";   // the agent channel (FR-CHN1)
import { lastActionBox } from "./expand.js";                                    // compact boxes open for review (FR-CMP1)
import { openAssistant, send as askRihma } from "./assistant.js";       // a failed job: ask Rihma why
import { handoffButton } from "./goal.js";                                     // hand off to an agent (FR-BRG1)
import { startHerePanel } from "./starthere.js";                               // Start here (FR-LND1)
import { wipCard } from "./wip.js";                                           // work in progress (FR-WIP1)
import { tasksTop, taskShown, taskCardExtra } from "./tasklive.js";            // tasks you open, live (FR-LND1)
import { logLink } from "./runlog.js";                                         // the whole log of a run (FR-LND1)
import { postureChip } from "./posture.js";
import { assuranceChip } from "./runners.js";
import { viewAssessment } from "./assessment.js";
import { overviewCard, jobStrip } from "./progress.js";
import { aiTools } from "./aitools.js";
import { kindChip, adoptedLine, adoptedOverview, adoptedSide } from "./adopted.js";
import { viewAutomations } from "./automations.js";
import { viewConsole } from "./console.js";
import { viewChecks } from "./health.js";
import { viewAlign, alignCallout } from "./alignment.js";
import { workCard } from "./workbalance.js";   // where the work went: development or conformance (FR-STR1)
import { insightsView } from "./insights.js";
import { graphView } from "./graph.js";   // the Knowledge graph tab (FR-GRV1)
import { viewReview } from "./review.js";
import { deployCard } from "./roads.js";
import { availableViews, capsuleNav, capsuleWaits, defaultView, rememberView, registered, labelOf } from "./capsules.js";
import { rememberProject, projectTitle } from "./scope.js";
import { cardTop, decideBlock, details, commentRow } from "./decide.js";
import {
  emptyLine, emptyState, emptyHow, word, technical, tw, term, pick, explain, datum, stageWord, modeWord, statusWord, viewWord, kernelWord,
  stuckWhy, nowSaid, plurals, cardTitle, cardTitleEl, ambitionWord, ambitionLong, autonomyWord, ledgerEvent, releaseStep, controlName, titleOf, etaSaid, waitingCount,
  localDateTime,
} from "./words.js";
import { applyViewLayout } from "./viewcustom.js";
import { viewContext } from "./context.js";   // what Rihmasto knows, and what each agent is given (FR-CTX1)
import { viewDestinations, whereCard } from "./destinations.js";   // where the capability goes (FR-DST1)
import { setupCard } from "./setup.js";   // Set up this project (FR-SET1)
import { viewAgentSessions, agentSessionsFor } from "./agentobs.js";
import { viewIncidents, notRunning } from "./heal.js";   // incidents, and the way on from a release not running (FR-HEAL1)
import { briefAfterAdvance } from "./devadvance.js";   // a developer's Advance opens the developer briefing (FR-DEV2)
import { heldBox, nowGo } from "./hitl_held.js";   // required answers that hold delivery (FR-HITL2)

// -- shims the views were written against: a state is a chip with an icon and a word ---------------

const TONE = { ok: "good", warn: "warning", crit: "critical", nm: "nm", run: "info", paused: "neutral" };
const TONE_ICON = { ok: "check-circle", warn: "alert", crit: "x-circle", nm: "dashed", run: "refresh" };
const ICON = { ok: "✓", warn: "!", crit: "✕", nm: "?", run: "↻" };
function badge(kind, text, title) {
  return chip(TONE[kind] || "neutral", TONE_ICON[kind] || null, text, title ? { tip: title } : null);
}
// Who decides is carried by shape: a person, a model in a role, or the kernel's rule.
function glyph(kind) {
  return icon(kind === "human" ? "user" : kind === "kernel" ? "diamond" : "bot", "glyph " + kind);
}
function who(kind, text) { return h("span", { class: "chip who-chip " + kind }, glyph(kind), h("span", null, text)); }
function label(text, attrs) { return h("span", Object.assign({ class: "label" }, attrs || {}), text); }
function verdictKind(v) {
  if (v === "passed") return "ok";
  if (v === "failed" || v === "violation" || v === "regressed") return "crit";
  if (v === "escalate") return "warn";
  return "nm";
}
function oldHead(kicker, title, sub) { return pageHead(title, sub); }
// A page's loading placeholder (after a second) is cleared on every way out of its render: drawn,
// superseded by a newer page or failed. A placeholder left behind would cover a newer page or an error.
async function placeheld(main, what, draw) {
  const done = skeleton(main, what);
  try {
    return await draw(done);
  } finally {
    done();
  }
}
function actorLegend() {
  return h("p", { class: "legend-row muted small" }, h("span", null, glyph("human"), " a person: owns the decision"),
    h("span", null, glyph("model"), " an agent: a model in a role, its delegate"),
    h("span", null, glyph("kernel"), pick(" an automatic rule: decides by fixed rules, never by a model", " the kernel: a deterministic rule")));
}
// -- the focus after a write ---------------------------------------------------------------------------
// act() disables a block's buttons while its write is in flight, which takes the focus off the one that
// was pressed. run() puts it back on that button when the write fails; settle() re-renders after a
// write that succeeded and gives the focus to the first of `to` (selectors, in order) that is on the
// page, so it never drops to the page's body.
function run(btn, container, fn) {
  return act(container, fn).then((v) => {
    const a = document.activeElement;
    if (btn && btn.isConnected && !btn.disabled && (!a || a === document.body)) btn.focus();
    return v;
  });
}
const FOCUSABLE = "a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]";
function focusFirst(to) {
  for (const sel of to) {
    const el = sel ? $(sel) : null;
    if (!el || !el.getClientRects().length) continue;
    if (!el.matches(FOCUSABLE)) el.setAttribute("tabindex", "-1");
    el.focus();
    return true;
  }
  return false;
}
async function settle(to) {
  await nav.rerender();
  const a = document.activeElement;
  if (!a || a === document.body) focusFirst((to || []).concat([".view-body h2.view-h", "#view-title"]));
}
// The headings of the cards beside one: those after it first, then those before it, nearest first.
// After a write that settles a card, the focus goes to the next card's heading.
function nextCards(el) {
  const art = el && el.closest("article[aria-labelledby]");
  const list = art && art.parentElement && art.closest(".cards");
  if (!art || !list) return [];
  const all = $$("article[aria-labelledby]", list).filter((x) => x.closest(".cards") === list);
  const i = all.indexOf(art);
  return all.slice(i + 1).concat(all.slice(0, Math.max(0, i)).reverse())
    .map((x) => "#" + CSS.escape(x.getAttribute("aria-labelledby")));
}
function typingNow() {
  const a = document.activeElement;
  return !!a && (a.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName));
}
// A re-render nobody asked for (a watched job ended) keeps the focus where the person left it. nav.rerender
// finds a control again only by its data-key; a tab, a link or a heading has none. focusMark() says what
// has the focus: its tag, id, address, name and words, which of the page's elements like it it was, and
// the headings of the regions around it. refocus() finds the same element on the new page (by its id,
// address or name alone when its words changed), else the nearest of those headings, else the view's
// heading, and never moves the page while it does.
function looseSig(el) {
  return [el.id || "", el.getAttribute("href") || "", el.getAttribute("aria-label") || ""].join("|");
}
function words(el) { return (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 120); }
function focusMark() {
  const a = document.activeElement;
  if (!a || a === document.body || a === document.documentElement || !a.isConnected) return null;
  const tag = a.tagName.toLowerCase();
  const loose = looseSig(a);
  const text = words(a);
  const alike = $$(tag).filter((x) => looseSig(x) === loose);   // words are compared only among these
  const near = [];
  for (let el = a.parentElement; el && el !== document.body; el = el.parentElement) {
    const by = el.getAttribute("aria-labelledby");
    if (by) near.push("#" + CSS.escape(by.split(/\s+/)[0]));
  }
  return { tag, loose, text, at: Math.max(0, alike.filter((x) => words(x) === text).indexOf(a)), looseAt: Math.max(0, alike.indexOf(a)),
    // without its words, an element is still itself when it has an id, an address or a name
    named: loose !== "||", near };
}
function refocus(m) {
  if (!m) return;
  const a = document.activeElement;
  if (a && a !== document.body && a.isConnected) return;   // the re-render found it, or the person moved on
  const alike = $$(m.tag).filter((x) => looseSig(x) === m.loose);
  const same = alike.filter((x) => words(x) === m.text);
  const el = same[m.at] || same[0] || (m.named ? alike[m.looseAt] || alike[0] : null) || null;
  const shown = (x) => x && x.isConnected && !x.disabled && x.getClientRects().length;
  const go = (x) => {
    if (!x.matches(FOCUSABLE)) x.setAttribute("tabindex", "-1");
    x.focus({ preventScroll: true });
  };
  if (shown(el)) { go(el); return; }
  for (const sel of m.near.concat([".view-body h2#view-title", "#view-title"])) {
    const x = $(sel);
    if (shown(x)) { go(x); return; }
  }
}
// Whether the project's intake has run: it leaves a brief.
function intakeRan(p) { return !!String(p.brief || "").trim(); }

function isPlanCard(c) { return !!c && c.kind === "approval" && (c.refs || {}).scope === "plan"; }
function acceptsRelease(c) {
  return !!c && (c.kind === "validation" || (c.kind === "approval" && /^Accept the demo/.test(String(c.title || ""))));
}
function mayPause() { return mayAct((S.meta && S.meta.may_pause) || []); }
// Advance is how a project carries on, so it is offered to the personas who may pause and resume one
// (or those the kernel names as its advancers, where /api/meta names them); anyone else is told who does.
function advancers() { const m = S.meta || {}; return m.may_advance || m.may_pause || []; }
function mayAdvance() { return mayAct(advancers()); }
function nowLine(n, pid, p) {
  if (!n) return h("p", { class: "nowline" }, nowChip(null), h("span", { class: "muted" }, "What it is doing could not be read."));
  const st = p ? liveState({ live: { running: p.running }, now: n, last_cell: p.last_cell }) : null;
  const lead = st && n.state === "working" ? h("span", { class: "chip " + st.tone }, st.running ? h("span", { class: "live-dot pulse" }) : icon(st.icon), h("span", null, st.word))
    : nowChip(n, pid);
  return h("p", { class: "nowline" }, lead, h("span", { class: "now-t", "data-ud": "" }, st && st.line && n.state === "working" ? st.line : nowSaid(n.line)),
    n.state === "waiting_on_you" && pid ? h("a", { class: "now-go", href: link(pid, nowGo(n)[0]) }, nowGo(n)[1], icon("arrow-right")) : null);
}
// Evidence: verified, held out, claimed, failing or not measured; the chip opens the evidence below it.
function evidenceChip(row, pid, target) {
  const st = EVIDENCE[row ? row.state : "not_measured"] || EVIDENCE.not_measured;
  const b = h("button", { type: "button", class: "chip evbtn " + st.tone, "aria-expanded": "false",
    "aria-controls": target ? target.id : null, "data-key": target ? target.id + ":chip" : null }, icon(st.icon), h("span", null, st.word));
  attachTip(b, st.word + ": " + evidenceWhy(row));
  if (target) {
    b.addEventListener("click", () => {
      const open = target.hidden;
      target.hidden = !open;
      b.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }
  return b;
}
function evidenceCounts(counts, opts) {
  const o = opts || {};
  const parts = EVIDENCE_ORDER.filter((k) => (counts || {})[k]).map((k) => h("span", { class: "evc-i " + EVIDENCE[k].tone },
    icon(EVIDENCE[k].icon), counts[k] + " " + EVIDENCE[k].word.toLowerCase()));
  if (!parts.length) return h("span", { class: "evc muted" }, o.none || "no criteria");
  return h("span", { class: "evc" + (o.compact ? " compact" : "") }, o.lead ? label(o.lead) : null, parts);
}
function healthCard(p) {
  const pid = p.meta.id;
  const hl = p.health;
  if (!hl) return card({ title: "Health", icon: "heart", cls: "health" }, h("p", { class: "muted" }, "The health could not be read."));
  const f = hl.forecast || {};
  const measured = f.median_task_minutes !== null && f.median_task_minutes !== undefined;
  const nm = () => h("span", { class: "nm-text" }, "not measured");
  const row = (name, value) => h("div", null, h("dt", null, name), h("dd", null, value));
  // the answer's own reasons (the track's), then any health reason the track does not already name
  const tw = p.track ? p.track.reasons.map((r) => r.why) : [];
  const why = tw.concat(hl.reasons.filter((r) => !tw.some((t) => t.startsWith(r))));
  const waiting = waitingCount((p.now || {}).line);
  return card({ title: "Health", icon: "heart", cls: "health", info: pick("Whether the project is on track against the approved plan (not known before a plan is approved). "
    + "Each reason links to what it is about. The forecast comes from how long this project's finished tasks took.",
  "The project's one answer: its Track against the approved plan (not measured before a plan is approved). "
    + "Each reason names its record. The forecast comes from this project's merged tasks, or says not measured.") },
  h("div", { class: "health-st" }, p.track ? trackState(p.track) : healthChip(hl)),   // the header's one answer
  why.length
    ? h("ul", { class: "reasons", "aria-label": "Why" }, why.map((r) => h("li", null, icon("alert"), h("span", { "data-ud": "" }, linkIds(pid, r)))))
    : waiting ? h("p", { class: "small" }, icon("user"), " " + pick("Held up by " + waiting + (waiting === 1 ? " decision" : " decisions") + " only a person can make.",
      "Nothing stuck in the build; " + waiting + (waiting === 1 ? " card waits" : " cards wait") + " on a person."))
      : h("p", { class: "muted small" }, pick("Nothing holds it back: no stuck task, nothing stopped, nothing overdue or out of date.",
        "Nothing holds it back: no escalation, no stopped task, nothing overdue or stale.")),
  h("dl", { class: "forecast" },
    // Before the contract is compiled there are no tasks to count: not known yet, never 0.
    row("Tasks left", !p.contract ? h("span", { class: "nm-text" }, pick("not planned yet", "no contract yet"))
      : f.tasks_left === undefined || f.tasks_left === null ? nm() : String(f.tasks_left)),
    row(pick("Typical time per task", "Median per task"), measured ? fmtMinutes(f.median_task_minutes) : nm()),
    // what will be done, and what it waits for: never "under a minute" while decisions wait on people
    row(pick("Expected done", "ETA"), (measured || f.tasks_left === 0) && etaSaid(f, waiting) ? etaSaid(f, waiting) : nm())),
  h("p", { class: "basis muted small" }, pick("Based on: ", "Forecast basis: "), datum(pick(plurals(f.basis || "").replace(/\bmerged\b/g, "finished"), plurals(f.basis || "")))));
}
const VIEW_FN = {};
const VIEW_LABEL = Object.fromEntries(Object.entries(VIEWS).map(([k, v]) => [k, v.label]));
const FINDING_GROUP = {
  assumed_over_dissent: "Assumed over dissent", rests_on_refuted_assumption: "Resting on a refuted assumption",
  assumption_overdue: "Assumptions overdue", stale_approval: "Approvals out of date",
  answer_differs_from_assumption: "Answers that differ from the assumption",
};
const FINDINGS_SHOWN = 2;
const REF_VIEW = { question: "questions", assumption: "assumptions", decision: "ledger", requirement: "spec" };
const OBSERVATIONS = {
  end_user: [["", "Let the factory classify it"], ["defect", "Defect: something does not work"],
    ["change_request", "UI gap: it works, but not the way I need"],
    ["new_requirement", "Requirement: something I need is missing"], ["defect", "Data: wrong or lost data"]],
  it: [["infra_change", "Infra change: hosting, network, security or deploy rules"],
    ["", "Let the factory classify it"], ["question", "A question"]],
  operations: [["", "Let the factory classify it"], ["incident", "Incident: the service is failing now"],
    ["defect", "Defect"], ["infra_change", "Infra change"]],
};
const DEFAULT_OBSERVATIONS = [["", "Let the factory classify it"], ["change_request", "Change request"],
  ["new_requirement", "New requirement"], ["defect", "Defect"], ["infra_change", "Infra change"],
  ["incident", "Incident"], ["question", "A question"]];
const VERDICT_ORDER = ["passed", "failed", "violation", "not measured"];
const HEALTH_FIRST = ["business_owner", "product_owner", "stakeholder"];
const LANES = [["pending", "Pending"], ["building", "Building"], ["merged", "Merged"], ["done", "Marked done"],
  ["escalated", "Escalated"], ["stopped", "Stopped"]];
const SIGNALS = ["tests", "trace", "fail_first", "verifier"];
const EXAMPLE_TITLE = "Equipment loans";
const EXAMPLE_IDEA = "Our team keeps losing track of who borrowed the drills and laptops. "
  + "We want a simple way to lend and return things.";
// The live panel: what the running cell does, polled every 5 s while the page is visible.
const LIVE = { el: null, pid: null, tasks: [], timer: null, gen: 0, seen: null };
const LIVE_EVERY = 5000;
void ICON; void plural; void KIND_ICON;

// -- ported: evidence why ------------------------------------------------------------------------------

function evidenceWhy(row) {
  const ev = (row && row.evidence && row.evidence[0]) || {};
  const tests = ev.tests || [];
  if (!row) return pick("No proof was found for this acceptance check.", "No evidence was read for this criterion.");
  if (row.state === "verified") {
    return pick("The work on " + ev.task + " passed its quality check (attempt " + ev.round + "). Tests in the product that check it: ",
      "A gate passed on " + ev.task + ", round " + ev.round + (ev.revision ? " (merged at " + short(ev.revision) + ")" : "")
      + ". Tests on main that name it: ") + tests.join(", ") + ".";
  }
  if (row.state === "claimed") {
    return pick("No quality check has proven it yet. ", "No gate proved it. ")
      + (tests.length ? pick("A test in the product checks it: ", "A test on main names it: ") + tests.join(", ") + "." : "");
  }
  if (row.state === "held_out") return pick("It passed a hidden test against release " + ev.release + ".",
    "It passed against release " + ev.release + ", checked in a separate custody.");
  if (row.state === "failing") return "It failed against release " + ev.release + ".";
  if (row.kind === "holdout" || row.kind === "probe") return pick("No release has been checked against this yet.", "No release has run this " + row.kind + " yet.");
  return pick("No test in the product checks it yet.", "No test on main names it yet.");
}
function evidenceBody(row, pid) {
  const ev = (row && row.evidence && row.evidence[0]) || {};
  if (row && row.state === "verified" && ev.task) {
    return h("div", { class: "ev-b" }, pick("The work on ", "A gate passed on "), h("a", { href: link(pid, "tasks", ev.task), class: "mono" }, ev.task),
      pick(" passed its quality check (attempt " + ev.round + "). Tests in the product that check it: ",
        ", round " + ev.round + (ev.revision ? " (merged at " + short(ev.revision) + ")" : "") + ". Tests on main that name it: "),
      sepList((ev.tests || []).map((t) => h("code", null, t))), ".");
  }
  return h("div", { class: "ev-b" }, evidenceWhy(row));
}

// -- ported: projects, floor, jobs ---------------------------------------------------------------------

async function renderProjects(seq) {
  const main = $("#main");
  return placeheld(main, "projects", (done) => drawProjects(main, seq, done));
}
async function drawProjects(main, seq, done) {
  const [projects, jobs] = await Promise.all([api("GET", "/api/projects"), api("GET", "/api/jobs")]);
  if (seq !== S.seq) return;
  done();
  S.projects = projects;
  document.title = "Projects · " + BRAND;
  const waits = (p) => !!p.now && p.now.state === "waiting_on_you";
  const shown = projects.filter((p) => !S.onlyWaiting || waits(p));
  const rows = shown.map((p) => {
    const mine = Object.entries(p.open_by_kind || {}).reduce((n, [k, c]) => n + (decides(k) ? c : 0), 0);
    const name = p.factory
      ? h("td", { "data-label": "Project" }, h("a", { href: "#/p/" + enc(p.id) + "/inbox" }, h("b", null, p.title)),
        h("div", { class: "label" }, "the factory's own proposals"))
      : h("td", { "data-label": "Project" }, h("a", { href: "#/p/" + enc(p.id) }, h("b", null, p.title)),
        h("div", { class: "label" }, p.id));
    return h("tr", { class: p.factory ? "factory-row" : null }, name,
      h("td", { class: "now-cell", "data-label": "Now" }, nowChip(p.now, p.id),
        p.now ? h("div", { class: "now-t small" }, p.now.line) : null),
      p.factory ? h("td", { class: "muted", "data-label": "Stage" }, "decided like any card")
        : h("td", { "data-label": tw("stage", 1, { cap: true }) }, h("span", { class: "mono" }, p.stage + "/7"), " ", stageWord(p.stage, cap(p.stage_name)),
          h("div", { class: "label" }, bandOf(p.stage))),
      h("td", { "data-label": tw("maturity", 1, { cap: true }) + " · " + tw("mode") }, p.factory ? "" : p.maturity + " · " + modeWord(p.mode)),
      h("td", { class: "num", "data-label": "Yours to decide" }, mine ? badge("warn", mine + " waiting") : "0"),
      h("td", { class: "num", "data-label": pick("Open decisions", "Open cards") }, String(p.open_cards)),
      h("td", { "data-label": "Attention" }, p.stale_approvals ? badge("warn", p.stale_approvals + " " + tw("stale"), explain("stale")) : "",
        p.overdue_assumptions ? badge("warn", p.overdue_assumptions + " overdue") : ""));
  });
  const products = projects.filter((p) => !p.factory).length;
  const filter = h("label", null, h("input", { type: "checkbox", checked: S.onlyWaiting, "data-key": "onlywaiting" }),
    "Only projects waiting on you (" + projects.filter(waits).length + ")");
  filter.querySelector("input").addEventListener("change", (e) => { S.onlyWaiting = e.target.checked; nav.route(true); });
  const table = rows.length
    ? h("div", { class: "tbl" }, h("table", { class: "projects" },
      h("caption", { class: "vh" }, "Projects, with what each is doing and what waits on the " + personaLabel(S.persona) + " persona"),
      h("thead", null, h("tr", null, h("th", { scope: "col" }, "Project"), h("th", { scope: "col" }, "Now"),
        h("th", { scope: "col" }, tw("stage", 1, { cap: true })), h("th", { scope: "col" }, tw("maturity", 1, { cap: true }) + " · " + tw("mode")),
        h("th", { scope: "col", class: "num" }, "Yours to decide"), h("th", { scope: "col", class: "num" }, pick("Open decisions", "Open cards")),
        h("th", { scope: "col" }, "Attention"))),
      h("tbody", null, rows)))
    : h("p", { class: "empty" }, "No project is waiting on you right now. ",
      h("button", { type: "button", class: "btn quiet", id: "show-all" }, "Show every project"));
  const showAll = table.querySelector("#show-all");
  if (showAll) showAll.addEventListener("click", () => { S.onlyWaiting = false; nav.route(true); });
  if (!products) {
    // An empty factory teaches what it is for, then offers the one thing to do: start a project.
    fill(main,
      oldHead("Rihma · cockpit", "Projects", null),
      h("section", { class: "panel intro", "aria-labelledby": "intro-h" },
        h("h2", { id: "intro-h", class: "label-h" }, "This is Rihma"),
        h("p", { class: "intro-t" }, "Rihma turns a business need into a running, monitored service: a panel of "
          + "perspectives asks what it needs to know, " + pick("an automatic quality check reviews every task", "a gate verifies every task")
          + ", and you decide what matters."),
        h("p", { class: "muted" }, "Start with a sentence or two about the problem, as in the example in the form. "
          + "Nothing is built until the questions that block it are answered.")),
      newProjectForm(true),
      projects.length ? h("section", { class: "section", "aria-label": "Rihmasto itself" }, table) : null,
      jobsSection(jobs.slice(0, 5), "Recent jobs"));
    return;
  }
  main.replaceChildren(
    oldHead("Rihma · cockpit", "Projects", "Each project runs from a business need to the running service. "
      + "Each says what it is doing now; what you may decide as " + personaLabel(S.persona) + " is counted per project."),
    h("div", { class: "viewbar" }, h("span", { class: "muted small" }, plural(products, "project") + " in this factory"), filter),
    table,
    newProjectForm(false),
    jobsSection(jobs.slice(0, 5), "Recent jobs"));
}

function choiceGroup(name, legend, options, checked) {
  return h("fieldset", null, h("legend", null, legend), h("div", { class: "choices" },
    Object.entries(options).map(([value, why]) => {
      const id = "np-" + name + "-" + value;
      return h("div", { class: "choice" },
        h("input", { type: "radio", name, id, value, checked: value === checked, "aria-describedby": id + "-why" }),
        h("label", { for: id }, value), h("span", { class: "why", id: id + "-why" }, why));
    })));
}

function newProjectForm(first) {
  const form = h("form", { class: "form", "aria-labelledby": "np-h", novalidate: true },
    h("div", { class: "field" }, h("label", { for: "np-title" }, "Title"),
      h("input", { id: "np-title", name: "title", maxlength: "200", required: true, placeholder: "for example: " + EXAMPLE_TITLE })),
    h("div", { class: "field" }, h("label", { for: "np-source" }, "The idea, or a written spec (markdown)"),
      h("textarea", { id: "np-source", name: "source", rows: "6", required: true, placeholder: "For example: " + EXAMPLE_IDEA })),
    choiceGroup("mode", "Mode", S.meta.modes, "mixed"),
    choiceGroup("maturity", "Maturity", S.meta.maturities, "demo"),
    h("div", { class: "field" }, h("label", { for: "np-by" }, "Requested by"),
      h("input", { id: "np-by", name: "requested_by", maxlength: "200", value: S.person, autocomplete: "name" })),
    h("div", { class: "btns" }, h("button", { type: "submit", class: "btn primary" }, "Create and start the intake")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const data = {
      title: form.elements.title.value.trim(), source: form.elements.source.value,
      mode: form.elements.mode.value, maturity: form.elements.maturity.value,
      requested_by: form.elements.requested_by.value.trim(), persona: S.persona,
    };
    if (!data.title || !data.source.trim()) { say("A new project needs a title and the idea or spec.", "warn"); return; }
    if (!data.requested_by) { say("Name the person who asks for it.", "warn"); form.elements.requested_by.focus(); return; }
    act(form, async () => {
      const out = await api("POST", "/api/projects", data);
      say("Project " + out.project.id + " was created. The intake runs as job " + out.job.id
        + "; refresh to see its questions.", "ok");
      location.hash = "#/p/" + enc(out.project.id) + "/overview";
    });
  });
  return h("section", { class: "section panel" + (first ? " first" : ""), "aria-labelledby": "np-h" },
    h("h2", { id: "np-h" }, first ? "Start your first project" : "New project"),
    h("p", { class: "lede" }, "The perspectives panel reads the request and asks its questions. The mode decides "
      + "which questions come to a person; the maturity decides which stages and gates run."), form);
}

// -- the factory floor -----------------------------------------------------------------------

function tile(name, value, sub, kind) {
  return h("div", { class: "tile" + (kind ? " " + kind : "") }, label(name),
    h("div", { class: "tile-v" }, value), sub ? h("div", { class: "tile-s" }, sub) : null);
}

async function renderFloor(seq) {
  const main = $("#main");
  return placeheld(main, "the floor", (done) => drawFloor(main, seq, done));
}
async function drawFloor(main, seq, done) {
  const f = await api("GET", "/api/floor");
  if (seq !== S.seq) return;
  done();
  document.title = "Floor · " + BRAND;
  const g = f.gates || {};
  const o = f.overall;
  const sp = f.spend;
  const verdicts = VERDICT_ORDER.concat(Object.keys(o.verdicts || {}).filter((v) => !VERDICT_ORDER.includes(v)));
  const phases = Object.entries(f.by_phase || {});
  const models = Object.entries(f.model_reliability || {});
  const memory = f.immune_memory || [];
  const listed = (label_, nodes) => h("div", { class: "tiles", role: "list", "aria-label": label_ },
    nodes.map((t) => { t.setAttribute("role", "listitem"); return t; }));
  const gated = g.tasks_gated || 0;
  const firstRate = g.first_round_rate === null || g.first_round_rate === undefined ? null : g.first_round_rate;
  // The headline is the gate's judgement of the work: did each task pass its gate on the first round?
  const T = technical();
  const gateTiles = listed(T ? "The gate's judgement" : "The quality check's judgement", [
    tile(T ? "First-round pass rate" : "Passed first time", pct(firstRate) || "not measured",
      gated ? (g.first_round_passed || 0) + " of " + plural(gated, "task") + (T ? " passed their gate on the first round" : " passed their quality check on the first attempt")
        : T ? "no task has reached a gate yet" : "no task has been checked yet", firstRate === null ? "nm" : null),
    tile(tw("merged", 1, { cap: true }), num(g.merged || 0), T ? "tasks merged into the product's main" : "tasks that are part of the product"),
    tile(T ? "Escalated" : "Sent to a person", num(g.escalated || 0), T ? "sent to a person after their repair rounds" : "a person decided after the AI's repair attempts"),
    tile(T ? "Rounds judged" : "Attempts checked", num(g.rounds || 0), (g.rounds_passed || 0) + " of " + plural(g.rounds || 0, tw("round"), tw("round", 2))
      + (T ? " passed the gate" : " passed")),
  ]);
  gateTiles.classList.add("gate-tiles");
  // Beside it, each Gnomon run's harness outcome. A run that was not measured is counted apart, never as failed.
  // A builder cell that ran outside Gnomon is no Gnomon run: say how many there were, so 0 runs never reads as no work
  const cells = f.projects.reduce((n, p) => n + (p.cells || 0), 0);
  const harnessTiles = listed(T ? "Harness outcomes in numbers" : "How the AI tool ran, in numbers", [
    tile(T ? "Gnomon runs" : "Tool-level runs", num(o.runs), !o.runs && cells
      ? (T ? cells + " builder-cell rounds ran outside Gnomon; they are under Tasks and the Ledger, not here"
        : "not recorded for these projects; " + cells + " AI attempts were checked above")
      : T ? "every Gnomon run of every project" : "every AI run of every project"),
    tile(T ? "Harness pass rate" : "Runs that worked", pct(o.rate) || "not measured",
      o.measured ? o.passed + " of " + plural(o.measured, "measured run") + " passed" : "no run was measured yet",
      o.rate === null ? "nm" : null),
    tile("Not measured", num(o.not_measured), "left out of the rate, never counted as failed"),
    tile(T ? "Apparatus failures" : "Tool failures", num(o.apparatus_failures), T ? "the harness broke, not the work; left out too" : "the AI tool broke, not the work; left out too"),
  ]);
  // Spend is priced from Gnomon runs. With no run recorded nothing was priced: not measured, never 0.
  const noRuns = !o.runs;
  const spendTiles = listed("Spend", !T && noRuns ? [tile("AI cost", "not known yet", "No priced AI work was recorded.", "nm")] : [
    noRuns ? tile("Cloud spend", "not measured", "no Gnomon run is recorded, so no run was priced", "nm")
      : tile("Cloud spend", fmtMoney(sp.cloud, f.currency),
        sp.unmeasured_runs ? plural(sp.unmeasured_runs, "run") + " without a price"
          + (sp.cloud_measured_part ? "; the priced part is " + fmtMoney(sp.cloud_measured_part, f.currency) : "")
          : "every run priced", sp.cloud === null ? "nm" : null),
    noRuns ? tile("Local spend", "not measured", "no Gnomon run is recorded, so no token was counted", "nm")
      : tile("Local spend", num(sp.local_tokens) + " tokens", "local models cost no API money"),
  ]);
  const VERDICT_HEAD = { passed: ["ok", "✓"], failed: ["crit", "✕"], violation: ["crit", "✕"], "not measured": ["nm", "?"] };
  const phaseTable = phases.length ? h("div", { class: "tbl" }, h("table", null,
    h("caption", { class: "vh" }, "Harness outcomes by phase and verdict"),
    h("thead", null, h("tr", null, h("th", { scope: "col" }, "Phase"),
      verdicts.map((v) => h("th", { scope: "col", class: "num" },
        VERDICT_HEAD[v] ? h("span", { "aria-hidden": "true" }, VERDICT_HEAD[v][1] + " ") : null, v)),
      h("th", { scope: "col", class: "num" }, "Runs"))),
    h("tbody", null, phases.map(([phase, counts]) => h("tr", null,
      h("th", { scope: "row" }, h("span", { class: "mono" }, phase.split(" ")[0] + "/7"), " ", cap(phase.split(" ").slice(1).join(" ")),
        h("div", { class: "label" }, bandOf(phase.split(" ")[0]))),
      verdicts.map((v) => h("td", { class: "num" }, counts[v] ? String(counts[v]) : h("span", { class: "muted" }, "0"))),
      h("td", { class: "num" }, String(Object.values(counts).reduce((a, b) => a + b, 0))))))))
    : emptyState("cell", null, cells ? { what: pick("Tool-level runs are not recorded for these projects.", "No Gnomon runs are recorded."),
      how: pick(cells + " AI attempts were checked above; they ran without the tool's own record.",
        cells + " builder-cell rounds ran outside Gnomon (a scripted builder); they are under Tasks and the Ledger.") }
      : { what: pick("No AI runs recorded yet.", "No Gnomon runs are recorded yet."),
        how: pick("Runs appear here once the AI build team has worked on a project.", "Runs appear here once cells have run through Gnomon.") });
  const nm = () => h("span", { class: "nm-text" }, "not measured");
  const projectTable = f.projects.length ? h("div", { class: "tbl" }, h("table", null,
    h("caption", { class: "vh" }, "Each project: the gate's judgement, then its harness outcomes"),
    h("thead", null, h("tr", null, (T ? ["Project", "Stage", "First round passed", "Merged", "Escalated", "Runs",
      "Harness passed", "Not measured", "Apparatus failures"] : ["Project", "Step", "Passed first time", "Accepted", "Sent to a person", "Runs",
      "Runs that worked", "Not measured", "Tool failures"]).map((t, i) => h("th", { scope: "col", class: i > 1 ? "num" : null }, t)))),
    h("tbody", null, f.projects.map((p) => {
      const pg = p.gates || {};
      return h("tr", null,
        h("td", null, h("a", { href: link(p.id, "tasks") }, p.title || p.id)),
        h("td", null, h("span", { class: "mono" }, p.stage + "/7"), " ", stageWord(p.stage, cap(stageName(p.stage)))),
        h("td", { class: "num" }, pg.tasks_gated ? pg.first_round_passed + " of " + pg.tasks_gated : h("span", { class: "muted" }, "— (no tasks yet)")),
        h("td", { class: "num" }, String(pg.merged || 0)), h("td", { class: "num" }, String(pg.escalated || 0)),
        h("td", { class: "num" }, h("a", { href: link(p.id, "cell") }, String(p.runs))),
        h("td", { class: "num" }, p.measured ? p.passed + " of " + p.measured : nm()),
        h("td", { class: "num" }, String(p.not_measured)), h("td", { class: "num" }, String(p.apparatus_failures)));
    }))))
    : null;
  const modelTable = models.length ? h("div", { class: "tbl" }, h("table", null,
    h("caption", { class: "vh" }, "Each builder model's record"),
    // A builder model's escalations are its cells that handed the work on to another model, not the
    // tasks the gate escalated to a person (the tile above).
    h("thead", null, h("tr", null, (T ? ["Builder model", "Cells run", "First-round gate pass", "Re-routed to another model",
      "Mean rounds to pass"] : ["AI model that builds", "Tasks worked on", "Passed first time", "Handed to another model",
      "Average attempts to pass"]).map((t, i) => h("th", { scope: "col", class: i ? "num" : null }, t)))),
    h("tbody", null, models.map(([name, m]) => h("tr", null,
      h("td", { class: "mono" }, name), h("td", { class: "num" }, String(m.cells)),
      h("td", { class: "num" }, m.first_round_warranted_rate === null ? nm() : pct(m.first_round_warranted_rate)),
      h("td", { class: "num" }, String(m.escalated)),
      h("td", { class: "num" }, m.mean_rounds_to_pass === null ? nm()
        : String(Math.round(m.mean_rounds_to_pass * 100) / 100)))))))
    : emptyState("cell", null, { what: pick("No AI model has built anything yet.", "No builder cell has run yet."),
      how: pick("Each AI model's record appears here once it has worked on a task.", "A builder model's record appears here after its first cell.") });
  fill(main,
    oldHead("Rihma · factory", "Floor", T ? "The gate's judgement first: how many tasks passed their gate on the first "
      + "round, merged or escalated. Below it, each Gnomon run's harness outcome, where a run that was not measured "
      + "is counted apart, never as a failure." : "How well the AI builds, across every project: how many tasks passed their quality "
      + "check the first time, were accepted or needed a person. Below it, how the AI tool itself ran; a run that was not "
      + "measured is counted apart, never as a failure."),
    h("section", { class: "fl", "aria-labelledby": "fl-gt" }, h("h2", { id: "fl-gt", class: "label-h" }, T ? "The gate's judgement (each task)" : "The quality check's judgement (each task)"),
      gateTiles,
      f.projects.length ? card({ title: T ? "First-round pass per project" : "Passed first time, per project", icon: "gate", cls: "floor-chart",
        info: T ? "Each project's tasks that passed their gate on the first round, of its tasks gated. A project with no gated task is not measured, never 0."
          : "Each project's tasks that passed their quality check on the first attempt. A project with no checked task is not measured, never 0." },
      floorBars(f.projects)) : null),
    h("section", { class: "section fl harness", "aria-labelledby": "fl-hn" },
      h("h2", { id: "fl-hn", class: "label-h" }, T ? "Harness outcomes (each Gnomon run)" : "How the AI tool ran (each run)"),
      h("p", { class: "hnote", "data-ud": "" }, T ? String(f.harness_note || "").replace("a builder cell in a grant-free lane has no verify of its own",
        "a builder cell without Gnomon grants runs no self-check") : "How the AI build tool itself ran. Some runs cannot be scored; the quality check still judges the work."),
      harnessTiles,
      h("h3", { class: "label-h sub-h" }, T ? "By phase and verdict" : "By step and result"),
      h("p", { class: "muted small" }, pick("Each run is listed under its project's current step. Not measured is not failed.",
        "Phase: the project's current stage, not the stage the run happened in. Not measured is not failed.")), phaseTable),
    projectTable ? h("section", { class: "section fl", "aria-labelledby": "fl-pr" },
      h("h2", { id: "fl-pr", class: "label-h" }, "Per project"), projectTable) : null,
    h("section", { class: "section fl", "aria-labelledby": "fl-sp" }, h("h2", { id: "fl-sp", class: "label-h" }, "Spend"), spendTiles),
    h("section", { class: "section fl", "aria-labelledby": "fl-md" }, h("h2", { id: "fl-md", class: "label-h" }, T ? "Builder models" : "AI models that build"),
      h("p", { class: "muted small" }, T ? "The evidence a routing change must rest on. Rihma proposes a routing experiment; "
        + "it never re-routes silently." : "What a change of AI model must rest on. Rihma proposes trying another model; "
        + "it never switches silently."), modelTable),
    h("section", { class: "section fl", "aria-labelledby": "fl-im" }, h("h2", { id: "fl-im", class: "label-h" }, "Lessons across projects"),
      memory.length ? h("ul", { class: "plain lessons" }, memory.map(lessonItem))
        : h("p", { class: "muted" }, "No lessons yet. A lesson is left by every defect; one seen in two projects becomes a "
          + "proposal in ", h("a", { href: "#/p/" + FACTORY_PID + "/inbox" }, titleOf(FACTORY_PID)), ".")));
}

// A lesson reads as the check it left behind (given, when, then), never as the word signature the
// kernel groups lessons by; a lesson without a criterion is its own sentence, said once.
function lessonItem(m) {
  const ex = (m.examples || [])[0] || {};
  const given = ex.given && ex.given !== "-" ? ex.given : null;
  const when = ex.when && ex.when !== "-" ? ex.when : null;
  const check = given || when
    ? [given ? "Given " + given + ", " : "", (given ? "when " : "When ") + (when || "-") + ", then " + (ex.then || "-")].join("")
    : String(ex.then || "(no text recorded)");
  return h("li", { class: "lesson" }, h("p", { class: "lesson-t" }, check),
    h("p", { class: "muted small" }, "Seen in " + plural(m.projects.length, "project") + ": ", sepList(m.projects.map((pid) =>
      h("a", { href: link(pid, "changes") }, pid))),
    ex.criterion ? h("span", null, " · regression check ", h("span", { class: "mono" }, ex.criterion),
      m.projects.length > 1 && ex.project ? " in " + ex.project : "") : null));
}

function floorBars(projects) {
  return bars({ max: 1, unit: "first round passed", rows: projects.map((p) => {
    const g = p.gates || {};
    return { label: p.title || p.id, href: link(p.id, "tasks"), value: g.tasks_gated ? g.first_round_passed / g.tasks_gated : null,
      display: g.tasks_gated ? pct(g.first_round_passed / g.tasks_gated) + " · " + g.first_round_passed + " of " + g.tasks_gated : null,
      why: pick("no task has been checked in this project yet", "no task has reached a gate in this project"),
      sub: (g.merged || 0) + " " + tw("merged") + (g.escalated ? " · " + g.escalated + pick(" sent to a person", " escalated") : "") };
  }) });
}

// -- jobs ------------------------------------------------------------------------------------

const JOB_STATE = { running: "run", done: "ok", failed: "crit", interrupted: "crit", unknown: "nm" };
// A console run's own way on from the Jobs page (FR-NVL3): Stop one still running (one left from before a restart
// too), run again one that failed, was stopped or was interrupted by a restart.
function jobActions(j) {
  if (j.kind !== "console") return null;
  const base = "/api/projects/" + enc(j.project) + "/console";
  if (j.state === "running") {
    return button("Stop", { kind: "small", icon: "x-circle", key: "job:stop:" + j.id, "data-control": "console_stop",
      onclick: async () => { if (!needPerson()) return; await api("POST", base + "/runs/" + enc(j.id) + "/stop", signed()); nav.rerender(); } });
  }
  if (!["failed", "interrupted", "stopped", "timed_out"].includes(j.state) || !(j.args || [])[0]) return null;
  return button("Run it again", { kind: "small", icon: "refresh", key: "job:rerun:" + j.id, "data-control": "console_run",
    onclick: async () => {
      if (!needPerson()) return;
      const out = await api("POST", base + "/run", Object.assign({ line: j.args[0] }, signed()));
      say("Started again as " + out.job.id + ".", "good");
      nav.rerender();
    } });
}

function jobsSection(jobs, title) {
  return h("section", { class: "section", "aria-label": title }, h("h2", { class: "label-h" }, title),
    jobs.length ? h("div", { class: "cards" }, jobs.map((j) => h("article", { class: "card job" },
      h("div", { class: "hd" }, glyph("kernel"), h("b", null, j.title || j.kind + " " + j.project),
        badge(JOB_STATE[j.state] || "nm", j.state + (j.code !== null && j.code !== undefined ? " (" + j.code + ")" : "")),
        label(j.id)),
      h("div", { class: "facts" }, h("span", null, "started " + fmtAt(j.started)),
        j.by && j.by.person ? h("span", null, "by ", personBadge(j.by.person, j.by.persona)) : null,
        technical() ? h("span", { class: "mono" }, "python " + j.args.join(" ")) : null, technical() ? h("span", { class: "mono" }, "log " + j.log) : null),
      j.made ? h("p", null, h("a", { class: "btn small primary", href: "#/p/" + enc(j.made) + "/overview", "data-key": "job:open:" + j.id },
        icon("arrow-right"), h("span", { class: "lbl" }, "Open the project"))) : null,
      j.failure ? h("div", { class: "note warning", role: "status" }, icon("alert"), h("div", null,
        h("p", null, h("b", null, "Why it failed: "), j.failure.reason),
        h("p", null, h("b", null, "What to do: "), j.failure.next),
        h("p", { class: "btns" }, button("Ask Rihma what went wrong", { icon: "bot", kind: "small primary", key: "job:ask:" + j.id,
          // the job's own failure goes with the question, so the answer is about this job (FR-NVL3)
          "data-control": "job_ask", onclick: () => { openAssistant(); askRihma("Why did " + (j.title || j.kind) + " (" + j.id + ") fail?",
            { why: { view: "jobs", field: j.title || j.kind, kind: "error", basis: j.failure.reason, project: "" } }); } }), jobActions(j)))) : null,
      j.note ? h("p", { class: "note info" }, icon("info"), " ", j.note, " ", jobActions(j)) : null,
      jobStrip(j, { title: j.title || cap(j.kind) + " " + j.project, icon: "download" }),     // its steps, live (FR-PRG1)
      h("p", { class: "btns" }, logLink({ job: j.id })),   // the whole log, followed (runlog.js, FR-LND1)
      j.log_tail.length ? (technical() ? h("pre", { "aria-label": "Last lines of the log" }, j.log_tail.join("\n"))
        : h("details", null, h("summary", null, "What it printed"), h("pre", { "aria-label": "Last lines of the log" }, j.log_tail.join("\n"))))
        : h("p", { class: "muted" }, "No output yet."))))
      : emptyState("jobs"));
}

async function renderJobs(seq) {
  const main = $("#main");
  return placeheld(main, "jobs", (done) => drawJobs(main, seq, done));
}
async function drawJobs(main, seq, done) {
  const jobs = await api("GET", "/api/jobs");
  if (seq !== S.seq) return;
  done();
  document.title = "Jobs · " + BRAND;
  main.replaceChildren(
    oldHead("Rihma · cockpit", "Jobs", pick("Work running in the background, started from this cockpit (such as moving a project on).",
      "Background runs of the kernel's command line, started from this cockpit.")),
    jobsSection(jobs, "All jobs"));
  if (jobs.some((j) => j.state === "running")) {
    S.timer = setTimeout(() => { if (S.route && S.route.name === "jobs") nav.route(true); }, 4000);
  }
}

// -- ported: pause, stages, alignment, ledger badge, view head -----------------------------------------

function pauseControls(p) {
  const meta = p.meta;
  const url = "/api/projects/" + enc(meta.id);
  const may = mayPause();
  const who = orList((S.meta && S.meta.may_pause) || []);
  if (meta.pause) {
    const pz = meta.pause;
    const box = h("div", { class: "pausebar paused" });
    if (pz.reason) box.append(h("p", { class: "pz-why" }, label("Reason"), " ", pz.reason));
    if (!may) {
      box.append(h("p", { class: "muted small" }, "A " + who + " persona may resume it."));
      return box;
    }
    const b = h("button", { type: "button", class: "btn human primary", "data-key": "resume", "data-control": "resume" },
      h("span", { class: "ic", "aria-hidden": "true" }, "▶"), " Resume");
    b.addEventListener("click", () => {
      if (!needPerson()) return;
      run(b, box, async () => {
        const out = await api("POST", url + "/resume", signed());
        say(meta.title + " is resumed, signed by " + S.person.trim() + " as " + personaLabel(S.persona) + ". "
          + (out.now ? out.now.line : ""), "ok");
        await settle(['[data-key="pause"]', '[data-key="advance"]']);
      });
    });
    box.append(h("div", { class: "btns" }, b, h("span", { class: "muted small" },
      "Resuming is signed with your name; the next Advance carries on from where it stopped.")));
    return box;
  }
  if (!may) return null;
  const fid = "pause-form";
  const open = h("button", { type: "button", class: "btn", "aria-expanded": "false", "aria-controls": fid, "data-key": "pause", "data-control": "pause" },
    h("span", { class: "ic", "aria-hidden": "true" }, "‖"), " Pause");
  const reason = h("input", { id: fid + "-r", "data-key": fid + "-r", maxlength: "2000", autocomplete: "off",
    placeholder: "for example: the GPU box is being patched" });
  const go = h("button", { type: "submit", class: "btn human primary", "data-key": "pause-go" }, "Pause at the next safe point");
  const cancel = h("button", { type: "button", class: "btn quiet" }, "Cancel");
  const form = h("form", { class: "pauseform", id: fid, hidden: true, novalidate: true, "aria-label": "Pause " + meta.title },
    h("p", { class: "small" }, BRAND + " does not cut a running cell off mid-step. It stops at the next safe point, between "
      + "tasks or between repair rounds, records where, and waits until a person resumes it."),
    h("div", { class: "field" }, h("label", { for: fid + "-r" }, "Reason (optional, recorded)"), reason),
    h("div", { class: "btns" }, go, cancel));
  const toggle = (show) => {
    form.hidden = !show;
    open.setAttribute("aria-expanded", show ? "true" : "false");
    if (show) reason.focus(); else open.focus();
  };
  open.addEventListener("click", () => toggle(form.hidden));
  cancel.addEventListener("click", () => toggle(false));
  form.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); toggle(false); } });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!needPerson()) return;
    run(go, form, async () => {
      const out = await api("POST", url + "/pause", Object.assign({ reason: reason.value.trim() }, signed()));
      say((out.now ? out.now.line + " " : "") + "Signed by " + S.person.trim() + " as " + personaLabel(S.persona) + ".", "ok");
      await settle(['[data-key="resume"]', ".pausebar.paused"]);
    });
  });
  return h("div", { class: "pausebar" }, open, form);
}

// A stage count's label as the kernel says it, and as a business reader reads it.
const COUNT_PLAIN = { "criteria": "acceptance checks", "criterion": "acceptance check", "tasks merged": "tasks done",
  "blocking open": "blocking decisions open", "releases": "releases" };
function countText(c) {
  if (!c) return "";
  const lbl = technical() ? c.label : COUNT_PLAIN[c.label] || c.label;
  return (c.total === null || c.total === undefined ? String(c.value) : c.value + "/" + c.total) + " " + lbl;
}
// A stage's count, said only where its records exist: before the intake, the spec or the contract there
// is nothing to count, and the stage says so rather than showing a 0 that was never measured.
function stageCount(p, s) {
  if (p.meta.factory) return countText(s.count);
  if ((s.stage === 1 || s.stage === 2) && !intakeRan(p) && !(p.questions || []).length) return pick("not started yet", "no intake yet");
  if ((s.stage === 3 || s.stage === 4) && !p.spec && !p.contract) return pick("not written yet", "no spec yet");
  if (s.stage === 5 && !p.contract) return pick("nothing planned yet", "no contract yet");
  return countText(s.count);
}
// Stage 5's verified and claimed criteria exist only once a contract names criteria: before it there is
// nothing to count, so nothing is shown rather than "0 verified · 0 claimed".
function stageEvidence(p, s) {
  return s.evidence && (p.meta.factory || p.contract) ? s.evidence : null;
}

function stageRail(p) {
  const sum = p.stage_summary;
  const pid = p.meta.id;
  const planOpen = (p.open_cards || []).some(isPlanCard);
  const byBand = {};
  sum.stages.forEach((s) => { (byBand[s.band] = byBand[s.band] || []).push(s); });
  const stateText = (s) => (s.state === "off" ? "not at " + p.meta.maturity : s.state);
  // While the plan waits on approval, the spec stages lead to the plan.
  const viewOf = (n) => (planOpen && (n === 3 || n === 4) ? "plan" : STAGE_VIEW[n]);
  return h("nav", { class: "rail", "aria-label": "Stages" },
    h("div", { class: "rail-h" }, label("Stages"), h("span", { class: "mono muted" }, sum.current + "/7")),
    sum.bands.map((b) => {
      const stages = byBand[b.id] || [];
      const here = stages.some((s) => s.state === "now");
      return h("div", { class: "band" + (here ? " here" : ""), role: "group", "aria-labelledby": "band-" + b.id },
        h("div", { class: "band-h", id: "band-" + b.id }, label(b.label),
          h("span", { class: "vh" }, ", stages " + b.stages.join(" and "))),
        h("ol", { class: "stages" }, stages.map((s) => h("li", { class: "stage " + s.state },
          h("a", { href: link(pid, viewOf(s.stage)), "aria-current": s.state === "now" ? "step" : null },
            h("span", { class: "st-n", "aria-hidden": "true" }, s.state === "done" ? "✓" : String(s.stage)),
            h("span", { class: "st-b" },
              h("span", { class: "st-name" }, h("span", { class: "vh" }, "Stage " + s.stage + ": "), cap(s.name)),
              h("span", { class: "st-c" }, stageCount(p, s)),
              stageEvidence(p, s) ? h("span", { class: "st-e" },
                h("span", { class: "ok" }, h("span", { "aria-hidden": "true" }, "✓ "), s.evidence.verified + " verified"),
                h("span", { class: "sep", "aria-hidden": "true" }, " · "), h("span", { class: "vh" }, ", "),
                h("span", { class: "claimed" }, h("span", { "aria-hidden": "true" }, "○ "), s.evidence.claimed + " claimed"),
                h("span", { class: "vh" }, ", ")) : null,
              s.stage === 4 && planOpen ? h("span", { class: "st-w" }, glyph("human"), " plan waits on approval") : null,
              h("span", { class: "st-s" }, stateText(s))))))));
    }));
}

function refLinks(pid, refs) {
  const out = [];
  for (const [k, v] of Object.entries(refs || {})) {
    if (REF_VIEW[k] && typeof v === "string") out.push(h("a", { href: link(pid, REF_VIEW[k], v) }, k + " " + v));
    else if (Array.isArray(v) && v.length) out.push(h("span", { class: "muted" }, k + ": " + v.map((x) => PERSPECTIVE_LABEL[x] || x).join(", ")));
  }
  return sepList(out);
}

// The canon's contradictions, grouped by kind with a count each. The first two of a group are
// shown; "Show all n" opens the rest. Listed, never resolved silently.
function alignmentPanel(pid, findings) {
  const kinds = [];
  const byKind = {};
  findings.forEach((f) => {
    if (!byKind[f.kind]) { byKind[f.kind] = []; kinds.push(f.kind); }
    byKind[f.kind].push(f);
  });
  const groups = kinds.map((kind) => {
    const list = byKind[kind];
    const gid = "fg-" + kind;
    const name = FINDING_GROUP[kind] || cap(String(kind).replace(/_/g, " "));
    const items = list.map((f, i) => h("li", { class: "finding", hidden: i >= FINDINGS_SHOWN && !S.alignOpen[kind] },
      h("span", { class: "fmark", "aria-hidden": "true" }, "!"),
      h("div", { class: "fbody" }, h("span", { class: "vh" }, "Warning: "), h("p", { "data-ud": "" }, f.text),
        h("div", { class: "refs" }, refLinks(pid, f.refs)))));
    let more = null;
    if (list.length > FINDINGS_SHOWN) {
      const words = () => (S.alignOpen[kind] ? "Show the first " + FINDINGS_SHOWN : "Show all " + list.length);
      more = h("button", { type: "button", class: "btn quiet fg-more", "aria-controls": gid + "-l",
        "aria-expanded": S.alignOpen[kind] ? "true" : "false", "data-key": gid + ":more" }, words());
      more.addEventListener("click", () => {
        S.alignOpen[kind] = !S.alignOpen[kind];
        items.forEach((li, i) => { if (i >= FINDINGS_SHOWN) li.hidden = !S.alignOpen[kind]; });
        more.textContent = words();
        more.setAttribute("aria-expanded", S.alignOpen[kind] ? "true" : "false");
      });
    }
    return h("section", { class: "fgroup", "aria-labelledby": gid + "-h" },
      h("h3", { class: "fg-h", id: gid + "-h" }, h("span", { class: "fg-name" }, name),
        h("span", { class: "fg-n" }, h("span", { "aria-hidden": "true" }, "· "), h("span", { class: "vh" }, ": "), String(list.length))),
      h("ul", { class: "findings", id: gid + "-l" }, items), more);
  });
  return h("aside", { class: "side", "aria-labelledby": "al-h" },
    h("div", { class: "panel align" },
      h("h2", { id: "al-h", class: "label-h" }, pick("Contradictions", "Alignment")),
      h("p", { class: "muted small" }, pick("Where the project's own answers and decisions contradict each other: listed for a person, never settled silently.",
        "Where the canon disagrees with itself: listed, never resolved silently.")),
      findings.length
        ? [h("p", { class: "fg-sum small" }, plural(findings.length, "finding") + " in " + plural(kinds.length, "group")), groups]
        : h("p", { class: "calm" }, badge("ok", "No contradictions found"))));
}

function ledgerBadge(l) {
  if (l.intact) return badge("ok", tw("ledger") + " intact · " + plural(l.records, pick("entry", "record"), pick("entries", "records")), explain("ledger"));
  return badge("crit", tw("ledger") + pick(" damaged", " broken") + (l.broken_seq !== null && l.broken_seq !== undefined ? " at seq " + l.broken_seq : ""), explain("ledger"));
}

// A view's heading states its scope: "Webshop · Inbox" (FR-UXO1).
function viewHead(title, question) {
  const pid = S.route && S.route.name === "project" ? S.route.pid : null;
  return h("div", { class: "q" }, h("h2", { class: "view-h", tabindex: "-1" },
    pid ? h("span", { class: "vh-scope" }, projectTitle(pid) + " · ") : null, title), question ? h("p", null, question) : null);
}

// -- ported: the views ---------------------------------------------------------------------------------

// -- overview

// What Rihmasto understood of an adopted project, by rule from its records, so a person can judge it and correct
// it: what it says it is, its shape, tests, what was read, the contract, the assessment, and what is not understood.
function understoodCard(p) {
  const u = p.understood;
  if (!u) return null;
  const row = (k, v) => (v ? h("div", null, h("dt", null, k), h("dd", null, v)) : null);
  const as = u.assessment;
  return card({ title: "What " + BRAND + " understood", icon: "info", id: "ov-understood", cls: "understood",
    info: "Read by rule from what adoption and the later steps recorded; no model wrote it. If it is wrong or thin, "
      + "correct it: add a description or material, and every later step uses it." },
  h("p", { class: "lede", "data-ud": "" }, u.what || "No description found: it has no README paragraph and no summary yet."),
  h("p", { class: "muted small" }, "From " + u.said_by + (u.source ? " · " + u.source : "") + "."),
  h("dl", { class: "kv" },
    row("Shape", u.shape.join(" · ")),
    row("Areas", (u.areas || []).join(", ")),
    row("Tests", u.tests),
    row("Read", u.read),
    row("AI-tool setup", u.ai_tools.length ? u.ai_tools.join(", ") : "none found"),
    row(cap(tw("contract")), u.contract),
    row("Assessment", as ? h("a", { href: link(p.meta.id, "assessment") }, as.id + ": " + (as.counts.findings || 0) + " findings of "
      + (as.counts.checks || 0) + " checks") : "not run yet")),
  u.not_understood.length ? h("div", { class: "note warning" }, icon("alert"), h("div", null,
    h("b", null, "Not understood yet"), h("ul", null, u.not_understood.map((g) => h("li", null, g))))) : null,
  ownSources(p, u),
  u.lenses ? lensBlock(p, u.lenses) : null,
  h("div", { class: "btns" }, button("Correct or add to it", { icon: "edit", kind: "small", key: "ov-correct",
    "data-control": "understood_correct", onclick: () => openMaterial(p) })));
}

// Where the project keeps its own requirements, tests, findings and tasks (sources.js, FR-SRC1): what is mapped, in
// one line, and the panel folded until opened (it reads the repository when it opens).
// The fold stays open while next steps remain (guide, don't describe; FR-SRC2): a person's own close is kept until a
// step is left, and a technical reader's panel is read at once, so a Map that re-draws the card never hides the rest.
const SRC_FOLD = new Map();   // pid -> "open" | "closed" (the person's own choice, this page's life)
function ownSources(p, u) {
  const n = u.native;
  const pid = p.meta.id;
  const body = h("div", { class: "src-own" });
  const chose = SRC_FOLD.get(pid);
  const fold = h("details", { class: "src-fold", "data-control": "sources_panel",
    open: chose ? (chose === "open" ? true : null) : (n || !technical() ? null : true) },
    h("summary", { "data-key": "ov-sources" }, "Project's own sources"), body);
  const onDrawn = (v) => {
    if ((v.next || []).length && SRC_FOLD.get(pid) !== "closed") { fold.open = true; SRC_FOLD.set(pid, "open"); }
  };
  const draw = () => { if (!body.firstChild) body.append(sourcesPanel(pid, { onChange: () => nav.rerender && nav.rerender(), onDrawn })); };
  fold.querySelector("summary").addEventListener("click", () => SRC_FOLD.set(pid, fold.open ? "closed" : "open"));
  fold.addEventListener("toggle", () => { if (fold.open) draw(); });
  if (fold.open || technical()) draw();
  return h("div", { class: "src-understood" },
    n ? h("dl", { class: "kv" },
      h("div", null, h("dt", null, "Its own sources"), h("dd", { "data-ud": "" }, n.line + (n.trace ? "; " + n.trace : ""))),
      n.tasks.open + n.tasks.done ? h("div", null, h("dt", null, "Its own tasks"), h("dd", null, n.tasks.open + " open, " + n.tasks.done + " done")) : null,
      n.findings.length ? h("div", null, h("dt", null, "Its own findings"), h("dd", null,
        h("ul", { class: "plain small" }, n.findings.map((f) => h("li", { "data-ud": "" }, f))))) : null) : null,
    fold);
}

// The same understanding for each reader, opening on the person's own: a developer (what is being built and what is
// next), compliance and IT (security, compliance and privacy), a business owner (goal, what is agreed, the risks).
const LENS_OF = { developer: "dev", it: "risk", operations: "risk", compliance: "risk" };
let lensShown = null;
function lensBlock(p, L) {
  const list = (items, none) => (items && items.length ? h("ul", null, items.map((x) => h("li", { "data-ud": "" }, x))) : h("p", { class: "muted small" }, none));
  const d = L.developer, c = L.compliance, b = L.business;
  const panes = {
    dev: ["What is being built", () => h("div", null,
      d.history ? h("p", { class: "muted small" }, cap(d.history) + ".") : null,
      h("h4", null, "Latest changes"), list((d.recent || []).map((r) => r.date + " · " + r.subject), "No changes recorded on main yet."),
      h("h4", null, "What to do next"), list(d.next, "Nothing waits on you."),
      d.waits_for ? h("p", { class: "muted small" }, "It waits for " + d.waits_for + ".") : null)],
    risk: ["Security, compliance, privacy", () => h("div", null,
      c.assessed ? null : h("p", null, "Not assessed yet: ", h("a", { href: link(p.meta.id, "assessment") }, "run the assessment"), " to see these."),
      h("h4", null, "Security"), list(c.security, c.assessed ? "No security finding by rule." : "Not measured."),
      h("h4", null, "Compliance"), list(c.compliance, c.assessed ? "No compliance finding by rule." : "Not measured."),
      h("h4", null, "Privacy"), list(c.privacy, c.assessed ? "No finding names personal data, secrets or consent." : "Not measured."),
      h("p", { class: "muted small" }, c.confidential ? "Confidential: its material goes to local models only." : "Not marked confidential."))],
    biz: ["Goal and business impact", () => h("div", null,
      h("h4", null, "Goal"), b.goal ? h("p", { "data-ud": "" }, b.goal) : h("p", { class: "note warning" }, icon("alert"), h("span", null, b.impact)),
      h("h4", null, "What is agreed"), h("p", null, b.agreed || "nothing yet"),
      h("h4", null, "Risks to it"), b.assessed === false ? h("p", { "data-lens-risks": "not-assessed" }, "Not assessed yet: ",
        h("a", { href: link(p.meta.id, "assessment") }, "run the assessment"), " to see the risks to it.")
        : list(b.risks, "No serious finding (critical or high)."))],
  };
  const pick0 = lensShown || LENS_OF[S.persona] || "biz";
  const body = h("div", { class: "lens-body" });
  const tabs = h("div", { class: "segmented", role: "tablist", "aria-label": "Read it as" });
  const show = (key) => {
    lensShown = key;
    fill(body, panes[key][1]());
    tabs.querySelectorAll("button").forEach((x) => x.setAttribute("aria-selected", String(x.dataset.lens === key)));
  };
  Object.entries(panes).forEach(([key, [label]]) => tabs.append(h("button", { type: "button", role: "tab", "data-lens": key,
    "data-key": "ov-lens:" + key, onclick: () => show(key) }, label)));
  show(pick0);
  return h("div", { class: "understood-lens" }, tabs, body);
}

VIEW_FN.overview = function viewOverview(p, inbox, ctx) {
  const meta = p.meta;
  if (meta.factory) return factoryOverview(p, inbox);
  const overdue = p.assumptions.filter((a) => a.overdue);
  const openQs = p.questions.filter((q) => q.status === "open");
  const spec = p.spec || {};
  const last = p.stage_summary ? p.stage_summary.last : 7;
  const healthFirst = HEALTH_FIRST.includes(S.persona);
  const planCard = (p.open_cards || []).find(isPlanCard);
  const out = [
    viewHead("Overview", word("q.overview")),
    understoodCard(p),                          // what Rihmasto understood of it, first: judge it, correct it
    setupCard(p),                               // Set up this project (FR-SET1)
    nextStrip(p),
    nav.journey ? nav.journey.card(p) : null,   // where it is on its journey, and the next step (FR-JRN1)
    agentsStrip(p),
    p.meta.factory ? null : wipCard(p),       // its uncommitted work in progress (FR-WIP1)
    planCard ? h("p", { class: "callout" }, glyph("human"), h("span", null, "The plan waits on approval before anything is built: "
      + "read it, edit a requirement, approve it, or send it back with a reason."),
    h("a", { href: link(meta.id, "plan"), class: "callout-go" }, "Open the plan")) : null,
    p.running ? livePanel(p, "ov") : null,
    overviewCard(meta.id, "assessment", { attrs: { "data-control": "assessment_progress_card" } }),   // running now, live (FR-PRG1)
    healthFirst ? healthCard(p) : null,
    p.adopted ? h("p", { class: "lede" + (healthFirst ? " section" : "") }, p.adopted.line + ".")
      : h("p", { class: "lede" + (healthFirst ? " section" : "") }, pick(
        meta.stage > last
          ? "Now at step " + meta.stage + " (" + stageWord(meta.stage, meta.stage_name).toLowerCase() + "), further than planned for a "
            + ambitionWord(meta.maturity) + ". Raise the goal in Project settings if it should go live."
          : "Step " + meta.stage + " of 7: " + stageWord(meta.stage, meta.stage_name).toLowerCase() + ". For a " + ambitionWord(meta.maturity)
            + ", the work goes as far as step " + last + ".",
        "Stage " + meta.stage + " of 7, " + stageWord(meta.stage, meta.stage_name) + ", in the " + bandOf(meta.stage)
          + " band. At " + meta.maturity + " maturity " + BRAND + " runs stages 1 to " + last
          + (meta.stage > last ? "; stages " + (last + 1) + " to " + meta.stage + " ran by request." : "."))),
    adoptedOverview(p, () => nav.rerender()),
    h("dl", { class: "kv" },
      h("div", null, h("dt", null, "goal"), h("dd", null, datum(p.goal || "(none)"))),
      h("div", null, h("dt", null, term("maturity")), h("dd", null, ambitionWord(meta.maturity) + ": ",
        datum(technical() ? S.meta.maturities[meta.maturity] || "" : ambitionLong(meta.maturity, S.meta.maturities[meta.maturity] || "").replace(/^[^:]+: /, "")))),
      h("div", null, h("dt", null, term("mode")), h("dd", null, modeWord(meta.mode) + ": ", datum((S.meta.modes[meta.mode] || "").replace(/^\w+: /, "")))),
      h("div", null, h("dt", null, term("ledger")), h("dd", null, ledgerBadge(p.ledger))),
      h("div", null, h("dt", null, "requested by"), h("dd", null, meta.requested_by || "(not recorded)")),
      h("div", null, h("dt", null, "updated"), h("dd", { tip: fmtAt(meta.updated) }, localDateTime(meta.updated)))),
  ];
  const waiting = waitingPanel(meta.id, inbox);
  const attention = h("div", { class: "panel" }, h("h3", { class: "label-h" }, "Needs attention"),
    h("ul", { class: "plain" },
      h("li", null, plural(openQs.length, "open question"), " · ",
        h("a", { href: link(meta.id, "questions") }, "Questions")),
      h("li", null, overdue.length ? badge("warn", overdue.length + " overdue") : "no overdue", " assumption"
        + (overdue.length === 1 ? "" : "s") + " of " + p.assumptions.length, " · ",
        h("a", { href: link(meta.id, "assumptions") }, "Assumptions")),
      h("li", null, p.stale.length ? [badge("warn", p.stale.length + " " + tw("stale")), " approvals"]
        : pick("No approvals are out of date", "No stale approvals"), " · ",
        h("a", { href: link(meta.id, "ledger") }, pick("Decision record", "Ledger and decisions"))),
      p.contract ? h("li", null, evidenceCounts((p.evidence_summary || {}).counts, { none: "no " + tw("criterion", 2) + " yet" }), " · ",
        h("a", { href: link(meta.id, "spec") }, pick("Proof per acceptance check", "Evidence per criterion"))) : null));
  out.push(h("div", { class: "two" }, waiting, attention));
  if (!healthFirst) out.push(h("div", { class: "section" }, healthCard(p)));
  out.push(aiTools(p));   // an adopted or attached project: its AI tools, and working on it from an IDE (aitools.js)
  out.push(alignCallout(p));   // adopted or attached, not aligned yet: the next step (alignment.js)
  out.push(workCard(meta.id));   // where the work went: development or conformance to Rihmasto's structure (FR-STR1)
  if (p.stale.length) {
    out.push(h("section", { class: "section", "aria-labelledby": "stale-h" },
      h("h3", { id: "stale-h" }, pick("Out-of-date approvals: these must be given again", "Stale approvals: these must be given again")),
      decisionsTable(p.stale)));
  }
  if (spec.summary || (spec.requirements || []).length) {
    out.push(h("section", { class: "section", "aria-labelledby": "sum-h" }, h("h3", { id: "sum-h" }, "What is being built"),
      spec.summary ? h("p", { "data-ud": "" }, spec.summary) : null,
      h("p", { class: "muted" }, plural((spec.requirements || []).length, "requirement") + " · ",
        h("a", { href: link(meta.id, "spec") }, viewWord("spec", "Spec & contract")))));
  }
  const readings = Object.entries(p.readings || {});
  if (readings.length) {
    out.push(h("section", { class: "section", "aria-labelledby": "rd-h" }, h("h3", { id: "rd-h" }, pick("How each side reads the request", "Readings by perspective")),
      h("div", { class: "opinions" }, readings.map(([persp, text]) => h("div", { class: "op" },
        h("div", { class: "label" }, glyph("model"), " ", PERSPECTIVE_LABEL[persp] || persp), datum(text))))));
  }
  out.push(h("section", { class: "section", "aria-labelledby": "br-h" },
    h("details", null, h("summary", { id: "br-h" }, pick("The brief, with the source of every statement", "The brief, with provenance on every statement")),
      p.brief.trim() ? renderMarkdown(p.brief) : h("p", { class: "muted" }, pick("No brief yet: it is written when the project starts.", "No brief yet: the intake has not run.")))));
  out.push(advancePanel(p));
  return h("div", null, out);
};

function waitingPanel(pid, inbox) {
  return h("div", { class: "panel" }, h("h3", { class: "label-h" }, "Waiting on you as " + personaLabel(S.persona)),
    inbox.cards.length
      ? h("ul", { class: "plain" }, inbox.cards.slice(0, 6).map((c) => h("li", null,
        technical() ? [h("a", { href: link(pid, "inbox", c.id), class: "mono" }, c.id), " "] : null,
        h("a", { href: link(pid, "inbox", c.id) }, KIND_LABEL[c.kind] || c.kind), ": ", cardTitleEl(c.title))))
      : h("p", { class: "muted" }, "Nothing needs you right now."),
    h("p", null, h("a", { href: link(pid, "inbox") }, "Open the Inbox (" + inbox.cards.length + ")")));
}

function factoryOverview(p, inbox) {
  const pid = p.meta.id;
  const approved = p.decisions.filter((d) => d.verdict === "approve").length;
  return h("div", null,
    viewHead("Overview", "What does " + BRAND + " propose to change in itself?"),
    h("dl", { class: "kv" },
      h("div", null, h("dt", null, "goal"), h("dd", null, p.goal || "(none)")),
      h("div", null, h("dt", null, "open proposals"), h("dd", null, String(p.open_cards.length))),
      h("div", null, h("dt", null, "approved so far"), h("dd", null, String(approved))),
      h("div", null, h("dt", null, term("ledger")), h("dd", null, ledgerBadge(p.ledger)))),
    h("div", { class: "two" }, waitingPanel(pid, inbox),
      h("div", { class: "panel" }, h("h3", { class: "label-h" }, "Where proposals come from"),
        h("p", null, "A defect leaves a lesson. When the same lesson shows up in two projects, " + BRAND
          + " proposes a default check for every future project. Routing changes are proposed the same way, from each "
          + "builder model's record on the ", h("a", { href: "#/floor" }, "Floor"), "."))));
}

function advancePanel(p) {
  const box = h("section", { class: "section panel", "aria-labelledby": "adv-h" },
    h("h3", { id: "adv-h" }, "Advance"),
    technical() ? h("p", { class: "lede" }, "Runs ", h("code", null, "python -m kernel.cli run " + p.meta.id),
      " in the background. The factory goes as far as it can and stops at the next gate a person must decide. "
      + "It never decides for anyone.")
      : h("p", { class: "lede" }, "Moves the project on in the background, as far as it can go, and stops at the next decision a person "
        + "must make. It never decides for anyone."));
  const running = p.jobs.some((j) => j.state === "running" && j.kind !== "console");   // a console run holds nothing
  const paused = !!p.meta.pause;
  if (!mayAdvance()) {
    box.append(h("p", { class: "muted small" }, glyph("human"), " A " + orList(advancers()) + " persona advances the project. "
      + (running ? "A job is running for it now." : paused ? "It is paused." : "")),
    jobsSection(p.jobs.slice(0, 3), "Jobs for this project"));
    return box;
  }
  const button = h("button", { type: "button", class: "btn primary", "data-key": "advance-panel", disabled: running || paused },
    running ? "A job is running" : paused ? "Paused: resume it first" : "Advance the project");
  if (paused) {
    box.append(h("p", { class: "muted small" }, "The project is paused. Advance stays off until a person resumes it from the header."));
  }
  button.addEventListener("click", () => advanceWrite(p, button, box, ["#adv-h"]));
  box.append(h("div", { class: "btns" }, button), jobsSection(p.jobs.slice(0, 3), "Jobs for this project"));
  return box;
}

// -- live: what the running Gnomon cell is doing (kernel/status.live), read from its audit trail.
// It polls every 5 s while the page is visible and stops while it is hidden (Page Visibility API).

function livePanel(p, where) {
  const hid = "live-h-" + where;
  const el = h("section", { class: "live" + (where === "lane" ? " in-lane" : " panel"), "aria-labelledby": hid },
    h("div", { class: "live-h" }, h("h3", { class: "label-h", id: hid }, where === "lane" ? "Live" : "Live · the running cell"),
      h("span", { class: "live-st" })),
    h("div", { class: "live-b" }, h("p", { class: "muted small" }, "Reading Gnomon's audit trail…")),
    h("p", { class: "live-at muted small" }));
  LIVE.el = el;
  LIVE.pid = p.meta.id;
  LIVE.tasks = p.tasks || [];
  LIVE.seen = null;
  return el;
}

function stopLive() {
  clearTimeout(LIVE.timer);
  LIVE.timer = null;
  LIVE.gen += 1;
}

function startLive() {
  stopLive();
  if (!LIVE.el || !LIVE.el.isConnected || document.hidden) return;
  liveTick(LIVE.gen);
}

async function liveTick(gen) {
  const el = LIVE.el;
  if (gen !== LIVE.gen || !el || !el.isConnected || document.hidden) return;
  let lv = null;
  let err = null;
  try {
    lv = await api("GET", "/api/projects/" + enc(LIVE.pid) + "/live");
  } catch (e) {
    if (e instanceof AuthError) return;
    err = e;
  }
  if (gen !== LIVE.gen || !el.isConnected) return;
  fillLive(el, lv, err);
  LIVE.timer = setTimeout(() => liveTick(gen), LIVE_EVERY);
}

function fillLive(el, lv, err) {
  const st = $(".live-st", el);
  const body = $(".live-b", el);
  const d = new Date();
  const at = [d.getHours(), d.getMinutes(), d.getSeconds()].map((x) => String(x).padStart(2, "0")).join(":");
  const seen = err ? "error:" + err.message : JSON.stringify(lv);
  if (seen !== LIVE.seen) {   // re-draw only what changed, so a focused link keeps its place
    LIVE.seen = seen;
    if (err) {
      st.replaceChildren(badge("nm", "not read"));
      body.replaceChildren(h("p", { class: "muted small" }, "The live view could not be read: " + err.message));
    } else if (!lv.running) {
      st.replaceChildren(h("span", { class: "s nm" }, h("span", { class: "ic", "aria-hidden": "true" }, "○"), "idle"));
      body.replaceChildren(h("p", { class: "live-none" }, pick("The AI build team is not working on this project right now.", "No cell is running for this project.")),
        h("p", { class: "muted small" }, pick("When a task is being built, each step the AI takes shows here as it happens.",
          "When a task builds, what its Gnomon cell does shows here, read from Gnomon's own audit trail.")));
    } else {
      const task = LIVE.tasks.find((t) => t.id === lv.task);
      const last = lv.last;
      st.replaceChildren(lv.ended
        ? h("span", { class: "s" }, h("span", { class: "ic", "aria-hidden": "true" }, "■"), "session ended")
        : badge("run", "running"));
      fill(body,
        h("p", { class: "live-task" }, h("a", { href: link(LIVE.pid, "tasks", lv.task), class: "mono" }, lv.task),
          task && task.title ? h("span", null, " " + task.title) : null),
        h("p", { class: "live-who" }, agentBadge(lv.role ? String(lv.role).replace(/_/g, " ") : "cell", lv.model),
          h("span", { class: "live-steps" }, plural(lv.steps || 0, "tool step") + " so far")),
        last ? lastActionBox(h("div", { class: "live-last" }, label("Last action"), h("span", { class: "mono live-tool" }, last.tool || "?"),
          last.target ? h("code", null, last.target) : null, last.at ? h("span", { class: "muted small" }, fmtAt(last.at)) : null),
        lv.recent, "live-last:" + LIVE.pid)   // Expand shows the steps before it (FR-CMP1)
          : h("p", { class: "muted small" }, "No tool step yet."),
        logLink({ project: LIVE.pid }),   // every step, following, at #/jobs/cell:<pid> (runlog.js, FR-LND1)
        lv.ended ? h("p", { class: "muted small" }, "The cell's Gnomon session has ended.") : null);
    }
  }
  $(".live-at", el).textContent = (lv && lv.running ? "From the audit trail in " + lv.lane + " · " : "") + "checked " + at
    + (document.hidden ? "" : ", every 5 s while this page is visible");
}

// -- inbox

VIEW_FN.inbox = function viewInbox(p, inbox, ctx) {
  const out = [viewHead("Inbox", word("inbox.lede")), elsewhereNote(inbox.elsewhere)];   // FR-ENF2
  const held = heldBox(p.meta.id, p.now);   // what holds delivery for a person's answer (hitl_held.js, FR-HITL2)
  if (held) out.push(held);
  if (!inbox.cards.length) {
    const others = inbox.others || [];
    out.push(emptyState("inbox", nowLine(p.now, null, p), { what: "Nothing waits on you as " + (everything() ? "any persona you hold" : personaLabel(S.persona)) + "." }));
    if (others.length) {
      const deciders = Array.from(new Set(others.flatMap((c) => c.deciders || []))).map(personaLabel);
      out.push(h("p", { class: "small muted" }, others.length + " decision(s) wait on another persona. "
        + (deciders.length ? deciders.join(" or ") + " decides them. " : "")
        + "Working alone? Switch persona in the person menu to decide them."));
    }
    return h("div", null, out);
  }
  const picked = new Set();
  // What holds the work up comes first; the rest waits, folded, until it is relevant: a person working alone is
  // nudged only for what blocks work now.
  const now = inbox.cards.filter(blocksWork);
  const later = inbox.cards.filter((c) => !blocksWork(c));
  const changes = later.filter((c) => c.kind === "change");
  const questions = later.filter((c) => c.kind === "question");
  out.push(h("p", { class: "lede" }, now.length
    ? plural(now.length, "decision") + " block work right now." + (later.length ? " " + later.length + " more can wait: folded below." : "")
    : (held ? "No decision here blocks work; delivery waits on the answer above." : "Nothing blocks work right now.")   // never against the held box
      + (later.length ? " " + plural(later.length, "decision") + " can wait until they matter: folded below." : "")));
  const draw = (c) => {
    const art = inboxCard(p, c, ctx || {});
    if (c.kind === "change" && changes.length > 1) {
      art.prepend(pickBox(c, picked));
    }
    return art;
  };
  if (now.length) out.push(h("h2", { class: "label-h" }, "Blocking work now"), h("div", { class: "cards" }, now.map(draw)));
  if (later.length) {
    out.push(h("details", { class: "ib-later", open: !now.length || null },
      h("summary", null, h("b", null, "Not blocking (" + later.length + ")"), h("span", { class: "muted small" },
        ": answer when it becomes relevant, or let Rihma go on with its suggestions")),
      changes.length > 1 ? batchBar(p, changes, picked) : null,
      questions.length > 1 ? assumeBar(p, questions) : null,
      h("div", { class: "cards" }, later.map(draw))));
  }
  return h("div", null, out);
};

// A card that holds the work up: a blocking question, or a decision the next step needs (a plan to approve, a
// validation, a deploy gate, an incident, a stuck task, a holdout ruling, a go-ahead).
const HOLDS = new Set(["approval", "validation", "deploy_gate", "incident", "escalation", "holdout_ruling", "go_ahead"]);
function blocksWork(c) { return c.blocking === true || HOLDS.has(c.kind); }

// Many open questions at once: go on with each one's suggested default (assume), recorded as the person's choice
// and open to an answer later; the ones that matter are answered one by one below.
function assumeBar(p, questions) {
  const pid = p.meta.id;
  const b = button("Go on with the suggested defaults for all " + questions.length, { kind: "small", key: "ib-assume",
    "data-control": "inbox_batch_assume" });
  b.addEventListener("click", async () => {
    if (!needPerson()) return;
    await act(b.parentNode, async () => {
      let done = 0;
      const left = [];
      for (const c of questions) {
        try {
          await api("POST", "/api/projects/" + enc(pid) + "/cards/" + enc(c.id) + "/decide",
            Object.assign({ verdict: "assume", reason: "the suggested default, chosen with " + (questions.length - 1) + " other(s)" }, signed()));
          done += 1;
        } catch (e) { if (e instanceof AuthError) throw e; left.push(c.id + ": " + e.message); }
        b.textContent = "assumed " + done + " of " + questions.length + "…";
      }
      say(plural(done, "question") + " go on with their suggested default, each recorded as your choice; answer any later in Questions."
        + (left.length ? " Not assumed, answer these yourself: " + left.join("; ") : ""), left.length ? "warning" : "good");
      nav.rerender();
    });
  });
  return h("section", { class: "card ib-batch", "aria-label": "Go on with the defaults" },
    h("p", null, h("b", null, questions.length + " questions wait on an answer. "), "Answer the ones that matter below; for the rest, "
      + "go on with what Rihma suggests. Each is recorded as your choice, and you can answer it properly later."),
    h("div", { class: "btns" }, b));
}

// Many change cards decided together (an assessment's findings, filed at once): each is decided through the same
// signed route and recorded on its own in the ledger, so nothing is lost for an audit; accepted ones then go into
// the spec and the contract in one run.
function batchCount(picked) {
  const el = $("#ib-count");
  if (el) el.textContent = picked.size + " selected";
}
// ``p`` is the project, or null in the Inbox across projects: each change is then decided in its own project, and
// picked by project and id (two projects each have a C-0002).
export const pickKey = (c) => (c.project ? c.project + "/" : "") + c.id;
export function pickBox(c, picked) {
  const box = h("input", { type: "checkbox", "data-key": "ib-pick:" + pickKey(c), "aria-label": "Select " + c.id + " to decide with others" });
  box.addEventListener("change", () => { if (box.checked) picked.add(pickKey(c)); else picked.delete(pickKey(c)); batchCount(picked); });
  return h("label", { class: "ib-pick" }, box, h("span", { class: "small muted" }, "Decide with others"));
}
export function batchBar(p, changes, picked) {
  const pid = p ? p.meta.id : null;
  const reason = h("input", { id: "ib-reason", maxlength: "300", placeholder: "Why (recorded with each decision)", "aria-label": "Reason for the selected decisions" });
  const setAll = (on) => {
    changes.forEach((c) => { const b = document.querySelector('[data-key="ib-pick:' + pickKey(c) + '"]'); if (b) b.checked = on; if (on) picked.add(pickKey(c)); else picked.delete(pickKey(c)); });
    batchCount(picked);
  };
  const decideAll = async (verdict, btn) => {
    if (!needPerson()) return;
    if (!picked.size) { say("Select the changes to decide first.", "warning"); return; }
    if (verdict !== "accept" && !reason.value.trim()) { say("Say why: a reason is recorded with each " + verdict + ".", "warning"); reason.focus(); return; }
    const ids = Array.from(picked);
    await act(btn.parentNode, async () => {
      let done = 0;
      const left = [];
      for (const key of ids) {
        const c = changes.find((x) => pickKey(x) === key) || { id: key };
        const cid = c.id;
        try {
          await api("POST", "/api/projects/" + enc(c.project || pid) + "/cards/" + enc(cid) + "/decide",
            Object.assign({ verdict, reason: reason.value.trim() || "accepted with " + (ids.length - 1) + " other(s)" }, signed(),
              c.decide_as ? { persona: c.decide_as } : {}));   // the persona it needs (FR-PPL1)
          done += 1;
        } catch (e) { if (e instanceof AuthError) throw e; left.push(cid + ": " + e.message); }
        btn.textContent = verdict + " " + done + " of " + ids.length + "…";
      }
      say(plural(done, "change") + " decided " + verdict + ", each signed by " + S.person.trim() + " and recorded."
        + (verdict === "accept" && done ? " Accepted ones go into the spec and the contract now: see Jobs." : "")
        + (left.length ? " Not decided: " + left.join("; ") : ""), left.length ? "warning" : "good");
      nav.rerender();
    });
  };
  const btn = (label, verdict, kind) => { const b = button(label, { kind: "small " + (kind || ""), key: "ib-" + verdict, "data-control": "inbox_batch_decide" });
    b.addEventListener("click", () => decideAll(verdict, b)); return b; };
  return h("section", { class: "card ib-batch", "aria-label": "Decide several changes together" },
    h("p", null, h("b", null, changes.length + " change cards wait on a decision. "), "Decide them one by one below, or select several and decide them together."),
    h("div", { class: "btns" }, button("Select all " + changes.length, { kind: "small", key: "ib-all", onclick: () => setAll(true) }),
      button("Clear", { kind: "small", key: "ib-none", onclick: () => setAll(false) }), h("span", { id: "ib-count", class: "muted small" }, "0 selected")),
    h("div", { class: "field" }, reason),
    h("div", { class: "btns" }, btn("Accept selected", "accept", "primary"), btn("Defer selected", "defer"), btn("Reject selected", "reject")));
}

function inboxCard(p, c, ctx) {
  const pid = p.meta.id;
  const art = h("article", { class: "card decision", "data-id": c.id, "aria-labelledby": "card-" + c.id },
    cardTop(c, "card-" + c.id, { icon: KIND_ICON[c.kind] }));
  if (c.kind === "question" && c.question) {
    art.append(questionBody(p, c.question, "inbox", c.title), details(c));
    return art;
  }
  // The plan's approval card is the plan itself: requirements, criteria, edit, approve or reject.
  if (isPlanCard(c) && ctx.plan && ctx.plan.spec) {
    art.classList.add("plan-card");
    art.append(h("p", { class: "lede" }, "Nothing is built until a person approves this plan. Read each requirement and "
      + "its criteria, edit any of them, then approve it, or reject it with a reason to have it redrawn."),
    planBody(p, ctx.plan, "in"), planDecide(pid, c, "in"));
    return art;
  }
  const payload = c.payload || {};
  const objections = Array.isArray(payload.objections) ? payload.objections : [];
  const body = String(c.body || "").trim();
  const sameAsObjections = objections.length > 0 && body === objections.map((o) => "- " + o).join("\n");
  // A stuck task's raw gate output is a developer's: a business reader gets why it is stuck and what is recommended.
  const plainWhy = c.kind === "escalation" ? stuckWhy(body + "\n" + objections.join("\n")) : "";
  if (plainWhy) art.append(h("p", { class: "body stuck-why" }, plainWhy));
  if (body && !sameAsObjections && !plainWhy && body !== String(c.title || "").trim()) art.append(h("div", { class: "body" }, cardTitle(body).text));
  if (payload.then && (payload.given || payload.when)) art.append(proposedCheck(payload, !body));
  // What the checks said: in plain sight for a technical reader, folded under Details for everyone else.
  const said = objections.length ? h("div", null, label(technical() ? "Objections" : "What the checks said"),
    h("ul", { class: "objections" }, objections.map((o) => h("li", null, o)))) : null;
  if (said && technical()) art.append(said);
  // Impact before the decision: what deciding would touch (FR-P5), folded for a business reader.
  if (c.kind === "change") art.append(impactPanel(pid, c, !technical()));
  // A card that accepts a release carries the release link and the checklist to try it with.
  if (acceptsRelease(c)) {
    art.append(h("section", { class: "trybox", "aria-label": "Try release " + (payload.release || "") + " before you decide" },
      label("Try it before you decide"), tryPanel(pid, ctx.tryIt, { where: c.id, url: payload.url })));
  }
  art.append(decideForm(pid, c),
    details(c, [c.kind === "change" && payload.triage ? triageLine(payload.triage, payload) : null, technical() ? null : said]));
  return art;
}

function proposedCheck(pl, withProjects) {
  return h("div", { class: "gwt" }, label("The check every project would carry"),
    h("dl", null, h("dt", null, "given"), h("dd", null, pl.given || "-"), h("dt", null, "when"), h("dd", null, pl.when || "-"),
      h("dt", null, "then"), h("dd", null, pl.then)),
    withProjects && Array.isArray(pl.projects) && pl.projects.length
      ? h("p", { class: "muted small" }, "Seen in " + pl.projects.join(", ")) : null);
}

// The choices with their meanings; Why and Confirm once one is picked (decide.js).
function decideForm(pid, c) {
  let form = null;
  form = decideBlock(c, { key: c.id, reasonId: "reason-" + c.id, decide: (v, reason, b) => {
    const to = nextCards(form).concat(["#" + CSS.escape("chg-" + c.id)]);   // the next card; in Changes, this one stays
    return run(b, form, async () => {
      await api("POST", "/api/projects/" + enc(pid) + "/cards/" + enc(c.id) + "/decide",
        Object.assign({ verdict: v, reason }, signed()));
      say((technical() ? c.id + ": " : "") + (VERDICT_LABEL[v] || v) + (reason ? " (" + reason + ")" : "") + ", signed by "
        + S.person.trim() + " as " + personaLabel(S.persona) + ".", "ok");
      await settle(to);
    });
  } });
  return form;
}

function triageLine(t, payload) {
  return h("div", { class: "facts" },
    h("span", null, "from " + personaLabel(payload.source) + (payload.person ? " (" + payload.person + ")" : "")),
    h("span", null, "class ", h("b", null, CLASS_LABEL[t.class] || t.class)),
    h("span", null, pick("goes back to step ", "way back: stage ") + t.way_back + ", " + stageWord(t.way_back, stageName(t.way_back)).toLowerCase()),
    t.needs_decision ? h("span", null, "needs a business decision first") : null,
    h("span", null, pick("sorted by ", "triaged by ") + (t.by || "rules")));
}

// -- impact if changed (FR-P5): read only, shown before the decision

function impactPanel(pid, c, collapsed) {
  const inner = impactInner(pid, c);
  if (collapsed) {
    return h("details", { class: "impact" }, h("summary", null, label("Impact if changed"), " ",
      h("span", { class: "muted small" }, "as triaged")), inner);
  }
  return h("section", { class: "impact", "aria-label": "Impact if " + c.id + " is accepted" }, label("Impact if changed"), inner);
}

function impactInner(pid, c) {
  if (c.impact_error) return h("p", { class: "muted" }, "The impact could not be read: " + c.impact_error);
  if (!c.impact) {
    return h("p", { class: "muted" }, pick("Not known yet: the change has not been sorted to the requirements it touches.",
      "Not known yet: triage has not named the requirements this change touches."));
  }
  return impactBody(pid, c.impact);
}

function impactBody(pid, im) {
  const none = () => h("span", { class: "muted" }, "none");
  const tests = im.tests || {};
  const reqs = im.requirements || [];
  const unknown = im.unknown_requirements || [];
  const crits = im.criteria || [];
  const reopened = im.tasks_reopened || [];
  const stale = im.approvals_going_stale || [];
  const rels = im.releases_carrying || [];
  const row = (name, ...value) => h("div", null, h("dt", null, name), h("dd", null, value));
  const summary = reqs.length
    ? "Deciding this would reopen " + plural(reopened.length, "task") + " and make " + plural(stale.length, "approval")
      + " " + tw("stale") + (rels.length ? ", in " + plural(rels.length, "release") + " that carry them" : "") + "."
    : pick("It names no agreed requirement.", "It names no requirement in the contract.");
  return h("div", { class: "impact-in" },
    h("p", { class: "impact-sum" }, summary),
    h("dl", { class: "impact-dl" },
      row("Requirements", reqs.length ? sepList(reqs.map((r) => h("a", { href: link(pid, "spec", r), class: "mono" }, r))) : none(),
        unknown.length ? h("span", { class: "muted" }, " · not in the contract: " + unknown.join(", ")) : null),
      row(pick("Acceptance checks and their tests", "Criteria and their tests"), crits.length ? h("ul", { class: "plain" }, crits.map((c) => h("li", null,
        h("span", { class: "mono" }, c), " → ", (tests[c] || []).length ? sepList(tests[c].map((t) => h("code", null, t)))
          : ((im.kinds || {})[c] && im.kinds[c] !== "test")
            ? h("span", { class: "muted" }, im.kinds[c] + pick(": checked against the running product, kept apart from the builders",
              ": checked against the running service, in a separate custody"))
            : h("span", { class: "muted" }, pick("no test in the product checks it", "no test on main names it"))))) : none()),
      row("Tasks that would reopen", reopened.length
        ? sepList(reopened.map((t) => h("a", { href: link(pid, "tasks", t), class: "mono" }, t))) : none()),
      row(pick("Approvals that would go out of date", "Approvals that would go stale"), stale.length ? h("ul", { class: "plain" }, stale.map((a) => h("li", null,
        h("a", { href: link(pid, "ledger", a.id), class: "mono" }, a.id), " " + (KIND_LABEL[a.kind] || a.kind).toLowerCase()
          + " given by ", h("b", null, a.person), a.card ? h("span", { class: "muted" }, " on " + a.card) : null))) : none()),
      row("Releases carrying them", rels.length ? h("ul", { class: "plain" }, rels.map((r) => h("li", null,
        "release " + r.release, r.state ? " · " + r.state : "",
        r.revision ? h("span", { class: "mono muted" }, " · " + short(r.revision)) : null))) : none())),
    h("p", { class: "muted small" }, "Shown before the decision. Nothing changes until a person decides."));
}

// -- questions

// Opinions side by side, never averaged away. With othersOnly, the asking perspective is left out:
// its proposal is the recommended option above.
function opinionsGrid(q, othersOnly) {
  const list = (q.opinions_side_by_side || []).filter((o) => !othersOnly || !o.asked);
  const said = list.filter((o) => o.opinion);
  const silent = list.filter((o) => !o.opinion);
  return h("div", { class: "opwrap" },
    label(othersOnly ? "The other perspectives" : "Every perspective"),
    said.length ? h("div", { class: "opinions", role: "list", "aria-label": othersOnly ? "Opinions of the other perspectives"
      : "Opinions of every perspective" },
    said.map((o) => h("div", { class: "op" + (o.asked ? " asked" : ""), role: "listitem" },
      h("div", { class: "label" }, glyph("model"), " ", PERSPECTIVE_LABEL[o.perspective] || o.perspective,
        o.asked ? " · asked, proposes" : ""),
      datum(o.opinion)))) : null,
    silent.length ? h("p", { class: "muted small" }, "No opinion from "
      + silent.map((o) => PERSPECTIVE_LABEL[o.perspective] || o.perspective).join(", ") + ".") : null);
}

function answerLine(pid, q) {
  const a = q.answer || {};
  if (q.status === "withdrawn") {   // it no longer fit once the project changed (FR-CHG1): kept, never deleted
    return h("div", { class: "answerline" }, "Withdrawn" + ((q.withdrawn || {}).why ? ": " + q.withdrawn.why : "") + ".");
  }
  if (q.status === "answered") {
    return h("div", { class: "answerline" }, "Answered by ", personBadge(a.by, a.persona), ": ", datum(a.text));
  }
  return h("div", { class: "answerline" }, agentBadge("Rihma assumes"), a.assumption ? " (" : "",
    a.assumption ? h("a", { href: link(pid, "assumptions", a.assumption) }, a.assumption) : null,
    a.assumption ? ")" : "", ": ", a.text, a.chosen_by ? [", chosen by ", personBadge(a.chosen_by)] : "");
}

// A question offers its options as radio buttons, the panel's proposal first and marked as the
// recommendation, then "Other: write your own". Answering records the chosen text as the owner's
// word; "Let Rihma assume" is the separate, secondary path to an assumption with a due date.
function questionBody(p, q, where, title, extra) {
  const pid = p.meta.id;
  const box = h("div", { class: "qbody" });
  const persp = PERSPECTIVE_LABEL[q.perspective] || q.perspective;
  const why = q.rationale ? h("p", { class: "why" }, label("Why the " + persp + " perspective asks"), " ", datum(q.rationale)) : null;
  // An Inbox card already carries the question as its title; it is not said twice.
  if (String(title || "").trim() !== String(q.text || "").trim()) box.append(h("p", { class: "qtext", "data-ud": "" }, q.text));
  if (q.status !== "open") {
    // a question without a rationale has no "Why" line (the native append would write "null")
    box.append(...[why, opinionsGrid(q, false), answerLine(pid, q)].filter(Boolean));
    return box;
  }
  const id = "ans-" + where + "-" + q.id;
  const options = q.options || [];
  const name = id + "-opt";
  const own = h("textarea", { id, rows: "2", "data-key": id, placeholder: "Write your own answer" });
  let pick = null;
  const form = h("div", { class: "decide" });
  if (options.length) {
    const otherId = name + "-other";
    const otherRadio = h("input", { type: "radio", name, id: otherId, value: "other", "data-key": otherId });
    own.addEventListener("input", () => { if (own.value.trim()) otherRadio.checked = true; });
    // Nothing is chosen for the person: Rihma's suggestion is named, and they pick (FR-UXO1).
    const radios = options.map((o, i) => {
      const oid = name + "-" + i;
      const rec = i === 0 && !!q.recommended;
      return h("div", { class: "opt" + (rec ? " rec" : "") },
        h("input", { type: "radio", name, id: oid, value: String(i), "data-key": oid }),
        h("label", { for: oid }, h("span", { class: "opt-t" }, o),
          rec ? h("span", { class: "rec-tag" }, glyph("model"), "Rihma suggests this") : null));
    });
    if (options.length && q.recommended) form.append(h("p", { class: "suggests" }, glyph("model"), " Rihma suggests: ", h("b", null, options[0])));
    form.append(h("fieldset", { class: "opts" }, h("legend", null, technical() ? "Your answer to " + q.id : "Your answer"), radios,
      h("div", { class: "opt other" }, otherRadio, h("label", { for: otherId }, "Other: write your own"),
        h("label", { for: id, class: "vh" }, "Your own answer to " + q.id), own)));
    pick = () => {
      const chosen = form.querySelector('input[name="' + CSS.escape(name) + '"]:checked');
      if (!chosen || chosen.value === "other") return { text: own.value.trim(), own: true };
      return { text: options[Number(chosen.value)], own: false };
    };
  } else {
    form.append(h("div", { class: "field" }, h("label", { for: id }, "Your answer to " + q.id), own));
    pick = () => ({ text: own.value.trim(), own: true });
  }
  form.append(...[why, opinionsGrid(q, true)].filter(Boolean));
  const answer = h("button", { type: "button", class: "btn human primary", "data-key": id + ":answer", "data-control": "answer" }, "Answer");
  const assume = h("button", {
    type: "button", class: "btn quiet secondary", "data-key": id + ":assume", "data-control": "assume", disabled: !q.proposed,
    "aria-describedby": id + "-assume",
  }, "Let Rihma assume");
  // Once it is settled, the focus goes on to the next question: in One at a time its heading, else the
  // next card's heading (or the one before it), never the page's body.
  const onward = () => (where === "one" ? ["#one-h"] : nextCards(box));
  answer.addEventListener("click", () => {
    const chosen = pick();
    if (!chosen.text) { say("Pick an answer, or write your own.", "warn"); (form.querySelector('input[type="radio"]') || own).focus(); return; }
    if (!needPerson()) return;
    const to = onward();
    run(answer, form, async () => {
      await api("POST", "/api/projects/" + enc(pid) + "/questions/" + enc(q.id) + "/answer",
        Object.assign({ text: chosen.text }, signed()));
      say(q.id + " is answered by " + S.person.trim() + " (“" + chosen.text + "”); the brief was regenerated.", "ok");
      await settle(to);
    });
  });
  assume.addEventListener("click", () => {
    if (!needPerson()) return;
    const to = onward();
    run(assume, form, async () => {
      const out = await api("POST", "/api/projects/" + enc(pid) + "/questions/" + enc(q.id) + "/assume", signed());
      say(q.id + " is assumed as " + out.assumption.id + ", due " + out.assumption.due
        + "; the brief was regenerated.", "ok");
      await settle(to);
    });
  });
  form.append(h("div", { class: "btns answer-btns" }, answer, h("span", { class: "or muted small" }, "or"), assume, extra || null),
    h("p", { class: "muted small", id: id + "-assume" }, q.proposed
      ? "Answer records your choice as the owner's word. Letting Rihma assume instead takes the " + persp
        + " perspective's proposal (“" + q.proposed + "”) as an assumption with a due date, to be confirmed later."
      : "No perspective proposed an answer, so only a person can answer this one."));
  box.append(form);
  return box;
}

function questionCard(p, q, where, extra) {
  return h("article", { class: "card", "data-id": q.id, "aria-labelledby": "qh-" + where + "-" + q.id },
    h("div", { class: "hd" }, glyph("model"), label(q.id, { id: "qh-" + where + "-" + q.id }),
      h("span", { class: "s model" }, "asked by " + (PERSPECTIVE_LABEL[q.perspective] || q.perspective)),
      q.blocking ? badge("warn", "blocking") : null,
      badge(q.status === "open" || q.status === "withdrawn" ? "nm" : "ok", q.status)),
    questionBody(p, q, where, null, extra));
}

// One at a time: the first open question only, with Answer, Let Rihma assume, or Skip for now,
// then the next (the conversational intake pattern). A skipped question comes back last.
function oneAtATime(p, open) {
  const pid = p.meta.id;
  const skipped = (S.skipped[pid] || []).filter((id) => open.some((q) => q.id === id));
  const queue = open.filter((q) => !skipped.includes(q.id)).concat(skipped.map((id) => open.find((q) => q.id === id)));
  if (!queue.length) {
    // "Answered or assumed" only when the panel asked something; the state is the header's own.
    return h("div", { class: "empty teach", "data-empty": "questions" }, h("p", { class: "empty-t" }, p.questions.length ? "No open questions." : noQuestions(p)),
      h("p", { class: "empty-how" }, p.questions.length ? pick("Everything asked is answered or assumed.", "Everything the panel asked is answered or assumed.")
        : emptyHow("questions")), nowLine(p.now, null, p));
  }
  const q = queue[0];
  const skip = h("button", { type: "button", class: "btn quiet", "data-key": "one:skip" }, "Skip for now");
  skip.addEventListener("click", () => {
    S.skipped[pid] = skipped.filter((id) => id !== q.id).concat([q.id]);
    S.focusNext = "#one-h";
    nav.rerender();
  });
  const again = skipped.includes(q.id);
  return h("section", { class: "one", "aria-labelledby": "one-h" },
    h("div", { class: "one-top" }, h("h3", { id: "one-h", tabindex: "-1", class: "label-h" },
      "One at a time · " + plural(open.length, "open question") + " left"),
    skipped.length ? h("span", { class: "muted small" }, skipped.length + " skipped for now") : null),
    again ? h("p", { class: "muted small" }, "You skipped this one earlier; here it is again.") : null,
    questionCard(p, q, "one", skip));
}

VIEW_FN.questions = function viewQuestions(p, inbox, ctx) {
  const qs = p.questions.filter((q) => S.showSettled || q.status === "open" || q.id === ctx.focus);
  const open = p.questions.filter((q) => q.status === "open");
  const toggle = h("label", null, h("input", { type: "checkbox", checked: S.showSettled, "data-key": "settled" }),
    "Show answered and assumed questions too");
  toggle.querySelector("input").addEventListener("change", (e) => { S.showSettled = e.target.checked; nav.route(true); });
  const one = h("label", null, h("input", { type: "checkbox", checked: S.oneAtATime, "data-key": "oneatatime" }), "One at a time");
  one.querySelector("input").addEventListener("change", (e) => {
    S.oneAtATime = e.target.checked;
    store.set("gf.oneatatime", S.oneAtATime ? "1" : "");
    nav.route(true);
  });
  const out = [viewHead("Questions", pick("What does the project still need to know? Each side's view is shown side by side, never averaged away.",
    "What does the intake panel still need to know? Each perspective's opinion is kept side by side, never averaged away.")),
  h("div", { class: "viewbar" }, h("span", { class: "muted small" },
    open.length + " open of " + p.questions.length), h("span", { class: "vb-r" }, one, S.oneAtATime ? null : toggle)),
  intakeSummary(p)];   // from your input, asked, assumed (cockpit/static/inputs.js)
  if (S.oneAtATime && !ctx.focus) {
    out.push(oneAtATime(p, open));
    return h("div", null, out);
  }
  if (!qs.length) {
    out.push(p.questions.length ? emptyState("questions", null, { what: "No open questions.",
      how: pick("Everything asked is answered or assumed. Tick “Show answered and assumed questions too” to see them.",
        "Every question is answered or assumed; “Show answered and assumed questions too” lists them.") })
      : intakeRan(p) ? emptyState("questions", null, { what: pick("No questions were needed.", "The panel asked no questions."),
        how: pick("The request was clear enough to write the requirements from.", "The intake found nothing blocking; the spec follows.") })
        : emptyState("questions"));
    return h("div", null, out);
  }
  out.push(h("div", { class: "cards" }, qs.map((q) => questionCard(p, q, "q"))));
  return h("div", null, out);
};
function noQuestions(p) {
  return intakeRan(p) ? pick("No questions were needed.", "The panel asked no questions.") : emptyLine("questions");
}

// -- assumptions

VIEW_FN.assumptions = function viewAssumptions(p) {
  const pid = p.meta.id;
  const out = [viewHead("Assumptions", word("q.assumptions"))];
  if (!p.assumptions.length) {
    out.push(emptyState("assumptions"));
    return h("div", null, out);
  }
  const open = p.assumptions.filter((a) => a.status === "open");
  const rows = p.assumptions.map((a) => {
    let action = h("span", { class: "muted" }, a.settled ? "by " + a.settled.by + " (" + personaLabel(a.settled.persona) + ")"
      + (a.settled.correction ? ": " + a.settled.correction : "") : "");
    if (a.status === "open") {
      const cid = "corr-" + a.id;
      const cell = h("div", { class: "rowform" });
      const confirm = h("button", { type: "button", class: "btn human", "data-key": a.id + ":confirm" }, "Confirm");
      const input = h("input", { id: cid, "data-key": cid, placeholder: "what is true instead" });
      const refute = h("button", { type: "button", class: "btn", "data-key": a.id + ":refute" }, "Refute");
      // Once settled, the focus goes to the next open assumption's Confirm (or the one before it).
      const i = open.findIndex((x) => x.id === a.id);
      const onward = open.slice(i + 1).concat(open.slice(0, Math.max(0, i)).reverse())
        .map((x) => '[data-key="' + CSS.escape(x.id + ":confirm") + '"]');
      const decide = (confirmed, btn) => {
        const correction = input.value.trim();
        if (!confirmed && !correction) { say("A refutation needs the correction.", "warn"); input.focus(); return; }
        if (!needPerson()) return;
        run(btn, cell, async () => {
          await api("POST", "/api/projects/" + enc(pid) + "/assumptions/" + enc(a.id) + "/settle",
            Object.assign({ confirmed, correction }, signed()));
          say(a.id + (confirmed ? " is confirmed." : " is refuted; a change card was opened for it."), "ok");
          await settle(onward.concat(['tr[data-id="' + CSS.escape(a.id) + '"] td']));
        });
      };
      confirm.addEventListener("click", () => decide(true, confirm));
      refute.addEventListener("click", () => decide(false, refute));
      cell.append(confirm, h("label", { for: cid, class: "vh" }, "Correction for " + a.id), input, refute);
      action = cell;
    }
    return h("tr", { class: a.overdue ? "overdue" : null, "data-id": a.id },
      h("td", { class: "mono" }, a.id),
      h("td", null, datum(a.text), a.question ? h("div", { class: "label" }, "from ",
        h("a", { href: link(pid, "questions", a.question) }, a.question)) : null),
      h("td", null, PERSPECTIVE_LABEL[a.perspective] || a.perspective),
      h("td", { "data-weight": a.id }, a.weight === undefined ? "-" : [String(a.weight), a.grew   // as Decide what matters weighs it
        ? [" ", chip(a.blocking ? "warning" : "info", "pulse", a.blocking ? "Blocks the next step" : "Grew in importance"),
          a.trigger ? h("div", { class: "label", "data-ud": "" }, a.trigger) : null] : null]),
      h("td", { class: "num" }, a.overdue ? badge("warn", "overdue " + a.due) : a.due),
      h("td", null, badge(a.status === "open" ? "nm" : a.status === "confirmed" ? "ok" : "crit", a.status)),
      h("td", null, action));
  });
  const overdue = p.assumptions.filter((a) => a.overdue).length;
  out.push(h("p", { class: "muted" }, overdue ? overdue + " overdue: past their due date and still unchecked." : "None overdue."),
    h("div", { class: "tbl" }, h("table", null, h("caption", { class: "vh" }, "Assumptions with due dates"),
      h("thead", null, h("tr", null, ["ID", "Assumption", "Perspective", "Weight", "Due", "Status", "Confirm or refute"].map((t) =>
        h("th", { scope: "col" }, t)))),
      h("tbody", null, rows))));
  return h("div", null, out);
};

// -- spec and contract

// Provenance: a person's word (confirmed, endorsed), the factory's assumption, or its proposal.
function provBadge(r) {
  const prov = r.provenance || "unknown";
  const by = r.decided_by && (prov === "customer-confirmed" || prov === "customer-endorsed") ? " by " + r.decided_by : "";
  if (prov === "customer-confirmed" || prov === "customer-endorsed") return who("human", pick(prov === "customer-confirmed" ? "confirmed" : "agreed", prov) + by);
  if (prov === "assumption") return badge("warn", "assumption", explain("assumption"));
  if (prov === "vendor-proposed") return who("model", pick("proposed by the AI", "vendor-proposed"));
  return badge("nm", prov);
}

function sourceToken(pid, s) {
  if (/^Q-\d+$/.test(s)) return h("a", { href: link(pid, "questions", s) }, s);
  const m = /^change:(C-\d+)$/.exec(s);
  if (m) return h("a", { href: link(pid, "changes", m[1]) }, "change " + m[1]);
  const ed = /^edit:(.+)$/.exec(s);
  if (ed) return h("span", null, "edited by " + ed[1]);
  return h("span", null, s);
}

function sourcesLine(pid, r) {
  const sources = r.sources || [];
  return h("div", { class: "sources" }, label("Sources ·"), " ",
    sources.length ? sepList(sources.map((s) => sourceToken(pid, s))) : h("span", { class: "muted" }, "none recorded"),
    " ", provBadge(r), r.decided_on ? h("span", { class: "muted" }, " on " + r.decided_on) : null);
}

// How an acceptance check is checked, for a business reader (the kernel's kinds: test, holdout, probe).
const CHECK_KIND_PLAIN = { test: "a test", holdout: "a hidden test", probe: "a live check", manual: "a person" };
// With evidence (a contract is compiled), every criterion carries its chip: verified, held out,
// claimed, failing or not measured (FR-O6). A spec without a contract has no evidence yet.
function criteriaTable(criteria, evidenceOf, pid) {
  const cols = [tw("criterion", 1, { cap: true })].concat(evidenceOf ? [pick("Proof", "Evidence")] : [], [pick("Checked by", "Check"), "Given", "When", "Then"]);
  return h("div", { class: "tbl" }, h("table", { class: "crit" + (evidenceOf ? " with-ev" : "") },
    h("thead", null, h("tr", null, cols.map((t) => h("th", { scope: "col" }, t)))),
    h("tbody", null, criteria.map((c) => {
      // "crit-ev", not "ev-row": that is the Evidence packs widget's grid row, and a grid <tr> squeezes its cell.
      const more = evidenceOf ? h("tr", { class: "crit-ev", id: "evd-" + c.id, hidden: true },
        h("td", { colspan: String(cols.length) }, label("Evidence for " + c.id), " ", evidenceBody(evidenceOf[c.id], pid))) : null;
      return [h("tr", { "data-id": c.id }, h("td", { class: "mono" }, c.id),
        evidenceOf ? h("td", { class: "ev-cell" }, evidenceChip(evidenceOf[c.id], pid, more)) : null,
        h("td", null, who("kernel", technical() ? c.kind || "?" : CHECK_KIND_PLAIN[c.kind] || c.kind || "?")), h("td", { "data-ud": "" }, c.given), h("td", { "data-ud": "" }, c.when),
        h("td", { "data-ud": "" }, c.then)), more];
    }))));
}

function impactDetails(pid, rid) {
  const body = h("div", { "aria-live": "polite" });
  const d = h("details", { class: "impact" }, h("summary", null, label("Impact if changed"), " ",
    h("span", { class: "muted small" }, "what changing " + rid + " would touch")), body);
  let loaded = false;
  d.addEventListener("toggle", async () => {
    if (!d.open || loaded) return;
    loaded = true;
    body.replaceChildren(h("p", { class: "muted" }, "Reading the impact…"));
    try {
      const im = await api("GET", "/api/projects/" + enc(pid) + "/impact?requirements=" + enc(rid));
      body.replaceChildren(impactBody(pid, im));
    } catch (e) {
      loaded = false;
      if (!(e instanceof AuthError)) body.replaceChildren(h("p", { class: "muted" }, e.message));
    }
  });
  return d;
}

VIEW_FN.spec = function viewSpec(p) {
  const pid = p.meta.id;
  const out = [viewHead(viewWord("spec", "Spec & contract"), pick("What exactly is being built, who said so, and how is each requirement checked?",
    "What exactly is being built, who said so, and how is each criterion checked?"))];
  const c = p.contract;
  const spec = p.spec;
  if (!c && !spec) {
    out.push(emptyState("spec"));
    return h("div", null, out);
  }
  const evSum = p.evidence_summary || {};
  const evidenceOf = c ? Object.fromEntries((p.evidence || []).map((e) => [e.criterion, e])) : null;
  if (c) {
    out.push(h("dl", { class: "kv" },
      technical() ? h("div", null, h("dt", null, "contract revision"), h("dd", { class: "mono" }, short(c.revision))) : null,
      h("div", null, h("dt", null, "requirements"), h("dd", null, String((c.counts || {}).requirements || c.requirements.length))),
      h("div", null, h("dt", null, tw("criterion", 2)), h("dd", null, String((c.counts || {}).criteria || ""))),
      h("div", null, h("dt", null, "tasks"), h("dd", null, String((c.counts || {}).tasks || c.tasks.length))),
      h("div", { class: "wide" }, h("dt", null, pick("proof", "evidence")), h("dd", null, evidenceCounts(evSum.counts)))),
    h("p", { class: "muted small evnote" }, pick("Verified means the work passed its quality check and a test in the finished product "
      + "checks this acceptance check. Claimed means a test checks it, but no quality check has proven it yet. Open a chip to see the proof.",
    "Verified means a gate passed at the merged revision and a test on main "
      + "names the criterion. Claimed means a test names it, but no gate proved it. Open a chip for its evidence.")));
  } else {
    out.push(h("p", { class: "muted" }, pick("The requirements are written; they are not yet turned into checks the work must pass.",
      "The spec is written; the contract is not compiled yet.")));
  }
  if (spec && spec.summary) out.push(h("p", { class: "section lede", "data-ud": "" }, spec.summary));
  const reqs = c ? c.requirements : (spec.requirements || []).map((r) => ({
    id: r.id, statement: r.statement, provenance: r.provenance, group: r.priority, decided_by: r.decided_by,
    sources: r.sources || [],
    criteria: (r.acceptance || []).map((a) => ({ id: a.id, kind: a.kind, given: a.given, when: a.when, then: a.then })),
  }));
  out.push(h("div", { class: "cards section" }, reqs.map((r) => h("article", {
    class: "card req" + (r.provenance === "withdrawn" ? " withdrawn" : ""), "data-id": r.id, "aria-labelledby": "rq-" + r.id,
  },
  h("div", { class: "hd" }, label(r.id, { id: "rq-" + r.id }), r.group ? label(r.group) : null,
    c && r.provenance !== "withdrawn" ? evidenceCounts((evSum.by_requirement || {})[r.id], { compact: true, none: "no " + tw("criterion", 2) })
      : null),
  h("p", { class: "stmt", "data-ud": "" }, r.statement),
  sourcesLine(pid, r),
  criteriaTable(r.criteria || [], evidenceOf, pid),
  c && r.provenance !== "withdrawn" ? impactDetails(pid, r.id) : null))));
  if (spec && (spec.out_of_scope || []).length) {
    out.push(h("section", { class: "section" }, h("h3", null, "Out of scope"),
      h("ul", null, spec.out_of_scope.map((x) => h("li", { "data-ud": "" }, x)))));
  }
  return h("div", null, out);
};

// -- the plan: approved by a person before anything is built (kernel/plan.py, FR-P7)

let uid = 0;   // unique ids for rows a person adds to a form

function planBody(p, plan, where) {
  const pid = p.meta.id;
  const spec = plan.spec;
  const canEdit = !!plan.card && !plan.compiled && decides("approval", plan.editors);
  const editors = orList(plan.editors || []);
  return h("div", { class: "plan" },
    spec.summary ? h("p", { class: "plan-sum", "data-ud": "" }, spec.summary) : null,
    h("p", { class: "plan-own small" }, glyph("human"), h("span", null, canEdit
      ? pick("Editing a requirement makes you its owner: it counts as confirmed by you, and the plan is sent for approval again as edited.",
        "Editing a requirement makes you its owner: it becomes customer-confirmed by you, and the approval card is "
        + "reissued for the edited plan.")
      : pick("Whoever edits a requirement becomes its owner. A " + editors + " may edit the plan while it waits on approval.",
        "Editing a requirement makes its editor the owner (customer-confirmed). A " + editors
        + " persona may edit the plan while it waits on approval."))),
    h("div", { class: "cards plan-reqs" }, (spec.requirements || []).map((r) => planReq(pid, r, where, canEdit))),
    (spec.interface || []).length ? h("div", { class: "plan-if" }, label("Interface"),
      h("ul", { class: "plain mono small" }, spec.interface.map((e) => h("li", null, (e.method || "") + " " + (e.path || ""))))) : null,
    planIntegrations(spec.integrations || [], where),
    (spec.out_of_scope || []).length ? h("p", { class: "plan-oos small" }, label("Out of scope"), " ",
      sepList(spec.out_of_scope.map((x) => h("span", null, x)))) : null);
}

// The systems the product reaches (kernel/integration_decl.py, FR-DS1): what each is, how it is reached,
// whether the product may write there, and what data it touches. IT binds each on a paved road later.
function planIntegrations(rows, where) {
  if (!rows.length) return null;
  const hid = "pi-" + where;
  return h("section", { class: "plan-if plan-int", "data-control": "integrations", "aria-labelledby": hid },
    label("Data integrations", { id: hid }),
    h("ul", { class: "plain small" }, rows.map((d) => h("li", null,
      h("span", { class: "mono" }, d.name), " · " + d.kind + (d.system ? " (" + d.system + ")" : "") + " via " + d.via + " · ",
      h("strong", null, d.access === "read-write" ? "reads and writes" : "reads only"),
      " · " + (d.data_classes || []).join(", ") + " data",
      d.declared_by ? " · declared by " + d.declared_by : " · " + (d.provenance || "proposed")))),
    h("p", { class: "muted small" }, "IT binds each one to a real system on the paved road of every environment, and "
      + "approves it on a road card before delivery. Credentials are named here, never held."));
}

function planReq(pid, r, where, canEdit) {
  const hid = "pr-" + where + "-" + r.id;
  const crits = (r.acceptance || []).map((a) => ({ id: a.id, kind: a.kind, given: a.given, when: a.when, then: a.then }));
  const art = h("article", { class: "card req plan-req", "data-id": r.id, "aria-labelledby": hid },
    h("div", { class: "hd" }, label(r.id, { id: hid }), r.priority ? label(r.priority) : null,
      h("span", { class: "plan-n muted small" }, plural(crits.length, tw("criterion"), tw("criterion", 2)))),
    h("p", { class: "stmt", "data-ud": "" }, r.statement),
    sourcesLine(pid, r),
    crits.length ? criteriaTable(crits, null, pid) : h("p", { class: "muted small" }, "No criteria yet."));
  if (canEdit) art.append(reqEditor(pid, r, "ed-" + where + "-" + r.id));
  return art;
}

// "Edit": the statement, then criteria rows a person can add or remove. Saving is signed and
// makes the person the requirement's owner; the kernel refuses anyone who may not edit the plan.
function reqEditor(pid, r, fid) {
  const kinds = (S.meta && S.meta.criterion_kinds) || ["test", "holdout", "probe"];
  const toggle = h("button", { type: "button", class: "btn", "aria-expanded": "false", "aria-controls": fid,
    "data-key": fid + ":edit" }, "Edit " + r.id);
  const st = h("textarea", { id: fid + "-st", rows: "2", "data-key": fid + "-st" });
  const rows = h("div", { class: "crows" });
  const add = h("button", { type: "button", class: "btn quiet", "data-key": fid + ":add" },
    h("span", { "aria-hidden": "true" }, "+ "), "Add a criterion");
  const save = h("button", { type: "submit", class: "btn human primary", "data-key": fid + ":save" }, "Save the edit");
  const cancel = h("button", { type: "button", class: "btn quiet" }, "Cancel");
  const renumber = () => rows.querySelectorAll(".crow").forEach((row, i) => {
    $(".crow-n", row).textContent = "Criterion " + (i + 1);
    row.setAttribute("aria-label", "Criterion " + (i + 1));
    $(".crow-x button", row).setAttribute("aria-label", "Remove criterion " + (i + 1));
  });
  const addRow = (c) => {
    const k = fid + "-c" + (uid += 1);
    const blank = (v) => (v === undefined || v === null || v === "-" ? "" : String(v));
    const input = (name, value, hint) => h("div", { class: "field" }, h("label", { for: k + "-" + name }, name),
      h("input", { id: k + "-" + name, "data-key": k + "-" + name, "data-f": name, value: blank(value), placeholder: hint,
        autocomplete: "off", maxlength: "2000" }));
    const kind = (c && c.kind) || "test";
    const remove = h("button", { type: "button", class: "btn quiet" }, "Remove");
    const row = h("div", { class: "crow", role: "group" }, h("span", { class: "crow-n label" }),
      input("given", c && c.given, "the starting state"), input("when", c && c.when, "what someone does"),
      input("then", c && c.then, "what must be true"),
      h("div", { class: "field" }, h("label", { for: k + "-kind" }, "check"),
        h("select", { id: k + "-kind", "data-f": "kind" }, kinds.map((x) => h("option", { value: x, selected: x === kind }, x)))),
      h("div", { class: "crow-x" }, remove));
    remove.addEventListener("click", () => {
      if (rows.querySelectorAll(".crow").length <= 1) { say("A requirement keeps at least one criterion.", "warn"); return; }
      row.remove();
      renumber();
      add.focus();
    });
    rows.append(row);
    renumber();
    return row;
  };
  const reset = () => {
    st.value = r.statement || "";
    rows.replaceChildren();
    (r.acceptance || []).forEach(addRow);
    if (!rows.children.length) addRow(null);
  };
  reset();
  const form = h("form", { class: "reqedit", id: fid, hidden: true, novalidate: true, "aria-label": "Edit " + r.id },
    h("div", { class: "field" }, h("label", { for: fid + "-st" }, "Statement"), st),
    h("fieldset", { class: "crit-set" }, h("legend", null, "Criteria: given, when, then"), rows, h("div", { class: "btns" }, add)),
    h("p", { class: "muted small" }, "Saving makes you the owner of " + r.id + " (customer-confirmed by you). The approval "
      + "card is withdrawn and reissued for the edited plan."),
    h("div", { class: "btns" }, save, cancel));
  const show = (on) => {
    form.hidden = !on;
    toggle.setAttribute("aria-expanded", on ? "true" : "false");
    if (on) st.focus(); else toggle.focus();
  };
  toggle.addEventListener("click", () => show(form.hidden));
  cancel.addEventListener("click", () => { reset(); show(false); });
  add.addEventListener("click", () => { const row = addRow(null); $('[data-f="given"]', row).focus(); });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const statement = st.value.trim();
    const all = Array.from(rows.querySelectorAll(".crow"));
    const acceptance = all.map((row) => {
      const get = (f) => $('[data-f="' + f + '"]', row).value.trim();
      return { given: get("given"), when: get("when"), then: get("then"), kind: get("kind") };
    });
    if (!statement) { say("The statement cannot be empty.", "warn"); st.focus(); return; }
    const missing = acceptance.findIndex((a) => !a.then);
    if (missing >= 0) {
      say("Criterion " + (missing + 1) + " needs its “then”: what must be true.", "warn");
      $('[data-f="then"]', all[missing]).focus();
      return;
    }
    // The kernel keeps at least one test per requirement (the gate builds against tests): it would turn
    // the first criterion into a test without a word. The form says so instead and changes nothing.
    if (!acceptance.some((a) => a.kind === "test")) {
      say(pick(r.id + " needs at least one acceptance check that a test checks: the work is built against tests. "
        + "Set one check to test, then save.", r.id + " needs at least one criterion checked by a test: the gate builds against tests. "
        + "Set one criterion's check to test, then save."), "warn");
      $('[data-f="kind"]', all[0]).focus();
      return;
    }
    if (!needPerson()) return;
    run(save, form, async () => {
      const out = await api("POST", "/api/projects/" + enc(pid) + "/plan/requirements/" + enc(r.id),
        Object.assign({ statement, acceptance }, signed()));
      const card = out.plan && out.plan.card;
      say(r.id + " is edited and now owned by " + S.person.trim() + " (customer-confirmed)."
        + (card ? " The approval card is reissued as " + card.id + "." : ""), "ok");
      S.focusNext = '[data-key="' + CSS.escape(fid + ":edit") + '"]';
      await nav.rerender();
    });
  });
  return h("div", { class: "reqedit-w" }, h("div", { class: "btns" }, toggle), form);
}

// Approve, or reject with a required reason: the plan is then redrawn with that reason.
function planDecide(pid, card, where) {
  if (!decides("approval", card.deciders)) {
    return h("p", { class: "muted small plan-wait" }, glyph("human"), " Waits on a decision by " + orList(card.deciders) + ".");
  }
  const rid = "rej-" + where + "-" + card.id;
  const box = h("div", { class: "decide plan-decide" + (where === "pv" ? " standalone" : "") });
  const approve = h("button", { type: "button", class: "btn human primary", "data-key": card.id + ":approve" }, "Approve the plan");
  const reason = h("textarea", { id: rid, rows: "2", "data-key": rid });
  const reject = h("button", { type: "button", class: "btn human", "data-key": card.id + ":reject" }, "Reject and redraw");
  // After the decision the focus goes to the plan's state line, which now says who decided it.
  const decide = (verdict, why, btn) => run(btn, box, async () => {
    await api("POST", "/api/projects/" + enc(pid) + "/cards/" + enc(card.id) + "/decide",
      Object.assign({ verdict, reason: why }, signed()));
    say(verdict === "approve"
      ? "The plan is approved, signed by " + S.person.trim() + ". Advance compiles the contract and starts the build."
      : "The plan is rejected, signed by " + S.person.trim() + ". The next Advance redraws it with your reason in front "
        + "of the analyst.", "ok");
    await settle(where === "pv" ? ["#plan-st"] : nextCards(box));
  });
  approve.addEventListener("click", () => { if (needPerson()) decide("approve", "", approve); });
  reject.addEventListener("click", () => {
    const why = reason.value.trim();
    if (!why) { say("Rejecting the plan needs a reason: the plan is redrawn with it.", "warn"); reason.focus(); return; }
    if (needPerson()) decide("reject", why, reject);
  });
  box.append(h("div", { class: "pd-row" },
    h("div", { class: "pd-a" }, label("Approve"), h("p", { class: "small" }, pick("The build starts the next time the project moves on (Advance).",
      "The contract is compiled and the build starts at the next Advance.")), h("div", { class: "btns" }, approve)),
    h("div", { class: "pd-r" }, label("Or reject"), h("div", { class: "field" },
      h("label", { for: rid }, "Why (required): the plan is redrawn with this reason"), reason), h("div", { class: "btns" }, reject))));
  return box;
}

function planStatus(p, plan) {
  const pid = p.meta.id;
  const st = (cls, ...kids) => h("p", { class: "plan-st" + (cls ? " " + cls : ""), id: "plan-st" }, kids);
  const a = plan.approved;
  if (a) {
    return st(null, badge("ok", "approved"), " by ", personBadge(a.by), " on ",
      h("a", { href: link(pid, "ledger"), class: "mono" }, a.card), ", plan version " + a.spec_version + ". ",
      plan.compiled ? [pick("The build has started: a change now goes through ", "The contract is compiled: a change now goes through "),
        h("a", { href: link(pid, "changes") }, "Changes"), "."]
        : pick("Advance starts the build.", "Advance compiles the contract and starts the build."));
  }
  if (plan.card) {
    return st(null, h("span", { class: "s warn" }, glyph("human"), "waiting on approval"), " ",
      h("span", { class: "mono" }, plan.card.id), " · plan version " + plan.spec.version + " · nothing is built until a person approves it.");
  }
  const last = (plan.history || []).slice(-1)[0];
  // Approved, and the next Advance has not run yet: the kernel records plan_approved only then, but the
  // decision stands now and says so (never "no approval card is open").
  if (last && last.verdict === "approve" && (last.spec_version === undefined || last.spec_version === null
    || last.spec_version === plan.spec.version)) {
    return st(null, badge("ok", "approved"), " by ", personBadge(last.person, last.persona), " on ",
      h("a", { href: link(pid, "ledger"), class: "mono" }, last.card), ", plan version " + (last.spec_version || plan.spec.version) + ". ",
      pick("The next Advance starts the build.", "The next Advance compiles the contract and starts the build."));
  }
  if (last && last.verdict === "reject" && !last.redone) {
    // A rejection recorded without a reason (through the API) says so: the redraw has nothing to go on.
    return st(null, badge("warn", "rejected"), " by ", personBadge(last.person, last.persona),
      last.reason ? [": “" + last.reason + "”. ", "The next Advance redraws the plan with this reason in front of the analyst."]
        : [" with no reason given. ", "The next Advance redraws the plan without a reason to go on."]);
  }
  if (!plan.required) {
    return st("muted", pick("With the ambition " + p.meta.maturity + " the plan is not held for approval: the build starts when the project moves on.",
      "At " + p.meta.maturity + " maturity the plan is not held for approval: the contract is compiled when the project advances."));
  }
  return st("muted", "No approval card is open. The next Advance opens one for this plan.");
}

function planHistory(plan) {
  const rows = (plan.history || []).slice().reverse();
  if (!rows.length) return null;
  return h("section", { class: "section", "aria-labelledby": "ph-h" }, h("h3", { id: "ph-h", class: "label-h" }, "Earlier plan cards"),
    h("ul", { class: "plain plan-hist" }, rows.map((x) => h("li", null, h("span", { class: "mono" }, x.card),
      " · version " + (x.spec_version || "?") + " · ",
      x.verdict ? [VERDICT_LABEL[x.verdict] || x.verdict, " by ", personBadge(x.person, x.persona),
        x.reason ? ": “" + x.reason + "”" : x.verdict === "reject" ? ", with no reason given" : ""]
        : [x.state, x.closed && x.closed.why ? ": " + x.closed.why : ""]))));
}

VIEW_FN.plan = function viewPlan(p, inbox, ctx) {
  const plan = ctx.plan;
  const out = [viewHead("Plan", "What will be built? Approve it, edit it, or send it back with a reason, before anything is built.")];
  if (!plan || !plan.spec) {
    out.push(emptyState("plan"));
    return h("div", null, out);
  }
  out.push(planStatus(p, plan), planBody(p, plan, "pv"));
  if (plan.card) out.push(planDecide(p.meta.id, plan.card, "pv"));
  out.push(planHistory(plan));
  return h("div", null, out);
};

// -- try it: the release to open and one plain check per criterion (kernel/status.try_it, FR-R1).
// The ticks are the person's own aid: kept in this tab's sessionStorage, never sent as a decision.

function tryPanel(pid, tr, opts) {
  const o = opts || {};
  const where = o.where || "tv";
  if (!tr) return h("p", { class: "muted small" }, "The checklist could not be read.");
  // Only an http(s) address becomes a link; anything else is not offered.
  const found = [o.url, tr.url].find((u) => typeof u === "string" && /^https?:\/\/[^\s]+$/i.test(u)) || null;
  // Where the kernel says the release's environment no longer runs (running: false), its address is said,
  // never offered as a link to a page that would not answer.
  const stopped = !!found && found === tr.url && tr.running === false;
  const url = stopped ? null : found;
  const items = tr.items || [];
  // Kept per person, project, release and criterion: one person's ticks are not another's.
  const key = (cid) => ["gf.try", S.person.trim() || "-", pid, tr.release || "none", cid].join("|");
  const count = h("p", { class: "try-n small", "aria-live": "polite" });
  const recount = () => {
    const n = items.filter((it) => store.get(key(it.criterion)) === "1").length;
    count.textContent = n + " of " + plural(items.length, "check") + " ticked by you";
  };
  const head = url
    ? h("div", { class: "try-h" },
      h("a", { class: "btn primary tryopen", href: url, target: "_blank", rel: "noopener noreferrer" },
        "Open release " + (tr.release || "") + (tr.env ? " (" + tr.env + ")" : ""), h("span", { "aria-hidden": "true" }, " ↗"),
        h("span", { class: "vh" }, ", opens in a new tab")),
      h("code", { class: "try-url" }, url))
    : stopped ? h("div", null, h("p", { class: "muted" }, "Release " + (tr.release || "") + (tr.env ? " (" + tr.env + ")" : "") + " ran at ",
      h("code", { class: "try-url" }, found), ", but nothing runs there now: its environment was stopped. "
      + "The checklist is ready for when it runs again."), notRunning(pid, tr))
      : h("div", null, h("p", { class: "muted" }, "No release runs at a reachable address yet. The checklist is ready for when one does."),
        (tr.release ? notRunning(pid, tr) : null));
  if (!items.length) {
    return h("div", { class: "trypanel" }, head, emptyState("try", null, { what: pick("Nothing to check yet.", "No criteria yet."),
      how: pick("The checks to try appear here once the work is planned (step 4).", "They come with the contract, at stage 4.") }));
  }
  const list = h("ol", { class: "trylist" }, items.map((it, i) => {
    const id = "try-" + where + "-" + i;
    const box = h("input", { type: "checkbox", id, "data-key": id, checked: store.get(key(it.criterion)) === "1" });
    box.addEventListener("change", () => {
      if (box.checked) store.set(key(it.criterion), "1"); else store.del(key(it.criterion));
      recount();
    });
    return h("li", { class: "tryitem", "data-id": where === "tv" ? it.criterion : null },
      h("div", { class: "try-row" }, box, h("label", { for: id, "data-ud": "" }, it.text), evChip(it.evidence)),
      h("p", { class: "try-meta" }, label(it.criterion), " ", h("span", { "data-ud": "" }, it.requirement + ": " + it.statement)),
      o.report ? reportForm(pid, it, id) : null);
  }));
  recount();
  return h("div", { class: "trypanel" }, head,
    h("p", { class: "muted small" }, "Tick each check as you try it. The ticks are only your own aid: they stay in this tab "
      + "and are never sent as a decision."), count, list);
}

// "Report what you saw" on one check: a change, named after its criterion, signed by the tester.
function reportForm(pid, it, id) {
  if (!moduleShows("controls", "report", pid)) return null;       // the change loop's module is off here
  const rid = id + "-rep";
  const options = OBSERVATIONS[S.persona] || DEFAULT_OBSERVATIONS;
  const kind = h("select", { id: rid + "-k", "data-key": rid + "-k" }, options.map(([, t], i) => h("option", { value: String(i) }, t)));
  const text = h("textarea", { id: rid + "-t", rows: "3", "data-key": rid + "-t", placeholder: "What you did, what you saw, what you expected" });
  const send = h("button", { type: "submit", class: "btn human", "data-key": rid + ":send", "data-control": "report" }, "Send the report");
  const form = h("form", { class: "report", novalidate: true },
    h("div", { class: "field" }, h("label", { for: rid + "-k" }, "What is it?"), kind),
    h("div", { class: "field" }, h("label", { for: rid + "-t" }, "What did you see?"), text),
    h("div", { class: "btns" }, send, h("span", { class: "muted small" }, "Filed as a change that names " + it.criterion
      + ", signed with your name.")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const said = text.value.trim();
    if (!said) { say("Describe what you saw first.", "warn"); text.focus(); return; }
    if (!needPerson()) return;
    const hint = options[Number(kind.value)][0] || null;
    run(send, form, async () => {
      const out = await api("POST", "/api/projects/" + enc(pid) + "/changes",
        Object.assign({ text: "[" + it.criterion + "] " + said, hint }, signed()));
      const t = out.triage || {};
      say(out.card.id + " records what you saw on " + it.criterion + ": a " + (CLASS_LABEL[t.class] || t.class)
        + ", going back to stage " + t.way_back + " (" + stageName(t.way_back) + ").", "ok");
      await settle(['[data-key="' + CSS.escape(rid + ":sum") + '"]']);
    });
  });
  return h("details", { class: "report-d" }, h("summary", { "data-key": rid + ":sum" }, "Report what you saw"), form);
}

VIEW_FN.try = function viewTry(p, inbox, ctx) {
  const pid = p.meta.id;
  const out = [viewHead("Try it", "Does the running release do what was agreed? Try each check, then report what you saw.")];
  out.push(tryPanel(pid, ctx.tryIt, { report: true, where: "tv" }));
  out.push(h("p", { class: "muted small section" }, "Each report goes to ", h("a", { href: link(pid, "changes") }, "Changes"),
    ", where you can follow it. " + BRAND + " sends it back to the stage that can fix it."));
  return h("div", null, out);
};

// -- tasks: the work and what each gate saw

const SIGNAL_TECH = { tests: "tests", trace: "trace", fail_first: "fail-first", verifier: "verifier", scope: "write scope", custody: "holdout custody" };
// The same four checks in plain words: the tests ran, each check is traced to a test, a test failed before the
// fix, and an independent reviewer agreed.
const SIGNAL_PLAIN = { tests: "tests", trace: "every check has a test", fail_first: "test failed before the fix", verifier: "independent review",
  scope: "stayed in its files", custody: "hidden tests kept apart" };
const SIGNAL_LABEL = new Proxy({}, { get: (_, k) => (technical() ? SIGNAL_TECH : SIGNAL_PLAIN)[k] });

const LANE_ICON = { pending: "○", building: "↻", merged: "✓", done: "✓", escalated: "!", stopped: "✕" };

function roundDetails(r) {
  return h("div", { class: "round" },
    h("div", { class: "hd" }, label(tw("round") + " " + r.round),
      r.gate ? badge(verdictKind(r.gate.verdict), tw("gate") + " " + r.gate.verdict, explain("gate"))
        : badge("nm", pick("not checked: the AI tool itself failed", "no gate: the harness failed")),
      r.cell && r.cell.model ? h("span", { class: "facts" }, agentBadge("builder", r.cell.model),
        (r.cell.stop_reason ? " " + r.cell.stop_reason : "")
        + (r.cell.tool_steps !== undefined && r.cell.tool_steps !== null ? ", " + r.cell.tool_steps + " tool steps" : "")) : null,
      // who ran the round and what assurance applied (D-0019): a harness other than Gnomon is never shown as in-run
      r.cell && r.cell.runner ? h("span", { class: "facts", "data-key": "runner:" + r.round }, r.cell.runner.label + (r.cell.runner.version ? " " + r.cell.runner.version : "") + " ",
        assuranceChip({ assurance: r.cell.runner.name === "gnomon" ? "in_run" : "after_run", assurance_label: r.cell.runner.assurance_label })) : null),
    r.gate ? h("div", { class: "signals", role: "list", "aria-label": "Gate signals" }, r.gate.signals.map((s) =>
      h("span", { role: "listitem" }, badge(verdictKind(s.verdict), (SIGNAL_LABEL[s.name] || s.name) + ": " + s.verdict, s.detail || null)))) : null,
    r.gate && r.gate.signals.some((s) => s.detail) ? h("ul", { class: "objections" }, r.gate.signals.filter((s) => s.detail).map((s) =>
      h("li", null, (SIGNAL_LABEL[s.name] || s.name) + ": ", datum(s.detail)))) : null,
    r.gate && r.gate.objections.length ? h("div", null, label(pick("What the checks said", "Objections")),
      h("ul", { class: "objections" }, r.gate.objections.map((o) => h("li", { "data-ud": "" }, o)))) : null);
}

// The last gate's four signals as small chips: tests, trace, fail-first, verifier.
function signalChips(gate, round) {
  const by = {};
  (gate.signals || []).forEach((s) => { by[s.name] = s; });
  return h("ul", { class: "sigs", "aria-label": pick("Last quality check, attempt ", "Last gate, round ") + round }, SIGNALS.map((n) => {
    const s = by[n];
    const v = s ? s.verdict : "not measured";
    const kind = verdictKind(v);
    return h("li", { class: "s sig " + kind, title: (SIGNAL_LABEL[n] || n) + ": " + v + (s && s.detail ? ": " + s.detail : "") },
      h("span", { class: "ic", "aria-hidden": "true" }, ICON[kind] || "?"), SIGNAL_LABEL[n] || n,
      h("span", { class: "vh" }, ": " + v));
  }));
}

function taskCard(pid, t) {
  const last = t.rounds.length ? t.rounds[t.rounds.length - 1] : null;
  const known = LANES.some(([k]) => k === t.status);
  const lane = t.lane && LANES.some(([k]) => k === t.lane) ? t.lane : known ? t.status : "pending";
  return h("article", { class: "tcard " + lane, "data-id": t.id, "aria-labelledby": "tk-" + t.id },
    h("div", { class: "tc-h" }, label(t.id, { id: "tk-" + t.id }),
      h("span", { class: "rounds mono" }, plural(t.rounds.length, tw("round"), tw("round", 2))),
      known ? null : badge("nm", t.status)),
    t.title ? h("p", { class: "tc-t", "data-ud": "" }, t.title) : null,
    taskCardExtra(pid, t),   // its source, a person's mark, and Open (tasklive.js, FR-LND1)
    last && last.gate ? signalChips(last.gate, last.round)
      : h("p", { class: "muted small" }, last ? pick("Not checked: the AI tool itself failed.", "No gate: the harness failed.")
        : t.adopted ? "Adopted as it was: " + (t.note || "not built or gated by the factory") + "." : "Not built yet."),
    t.status === "escalated" && t.card
      ? h("p", { class: "tc-go" }, h("a", { href: link(pid, "inbox", t.card) }, "Decide " + t.card + " in the Inbox")) : null,
    t.status === "stopped" && t.stopped_by ? h("p", { class: "tc-f" }, "stopped by ", personBadge(t.stopped_by)) : null,
    t.status === "merged" ? h("p", { class: "tc-f" }, pick("done", "merged"),
      t.revision && technical() ? [" at ", h("span", { class: "mono" }, short(t.revision))] : null,
      t.accepted_as_is_by ? [" · accepted as is by ", personBadge(t.accepted_as_is_by)] : null) : null,
    t.reopened_by ? h("p", { class: "tc-f" }, "reopened by " + t.reopened_by.join(", ")) : null,
    h("details", { class: "tc-d" }, h("summary", null, "Details"),
      h("div", { class: "facts" },
        t.criteria.length ? h("span", null, tw("criterion", 2) + " " + t.criteria.join(", ")) : null,
        t.depends_on.length ? h("span", null, "after " + t.depends_on.join(", ")) : null,
        t.permitted_by ? h("span", null, "permitted by " + t.permitted_by) : null),
      t.rounds.map(roundDetails)));
}

// The tasks as a board: Pending, Building, Merged, Escalated, Stopped. On a phone the lanes stack.
VIEW_FN.tasks = function viewTasks(p, inbox, ctx) {
  const pid = p.meta.id;
  const out = [viewHead("Tasks", pick("Where is the work, and how did each piece do in its quality check?", "Where is the work, and what did each gate see?"))];
  out.push(...tasksTop(p, ctx).filter(Boolean));   // the filters and the open task's panel (tasklive.js, FR-LND1)
  if (!p.tasks.length) {
    out.push(emptyState("tasks"));
  } else {
    const lanes = Object.fromEntries(LANES.map(([k]) => [k, []]));
    // a person's done has its own lane, apart from the gate's merged (FR-LND2); the filter is this project's
    p.tasks.filter(taskShown(p)).forEach((t) => { (lanes[t.lane || t.status] || lanes.pending).push(t); });
    // The Building lane carries the live panel: what the running cell is doing right now.
    out.push(h("div", { class: "board tasks-board" }, LANES.map(([k, name]) => h("section", { class: "lane " + k, "aria-labelledby": "ln-" + k },
      h("h3", { class: "lane-h", id: "ln-" + k }, h("span", { class: "ic", "aria-hidden": "true" }, LANE_ICON[k]), statusWord(k) || name,
        h("span", { class: "lane-n" }, h("span", { class: "vh" }, ": "), String(lanes[k].length))),
      k === "building" ? livePanel(p, "lane") : null,
      lanes[k].length ? h("ul", { class: "lane-l" }, lanes[k].map((t) => h("li", null, taskCard(pid, t))))
        : k === "building" ? null : h("p", { class: "lane-e" }, "none")))));
  }
  out.push(advancePanel(p));
  return h("div", null, out);
};

// -- cell: every Gnomon run of the project (FR-M3)

VIEW_FN.cell = function viewCell(p, inbox, ctx) {
  const rows = ctx.cell || [];
  const out = [viewHead(viewWord("cell", "Cell"), pick("Every attempt the AI build team made on this project: who worked, what was decided, and whether the record of it holds.",
    "Every Gnomon run of this project: who ran, what it decided, and whether its record holds."))];
  if (!rows.length) {
    out.push(emptyState("cell"));
    return h("div", null, out);
  }
  const measured = rows.filter((r) => !r.apparatus_failure && r.verdict !== "not measured");
  const passed = measured.filter((r) => r.verdict === "passed").length;
  out.push(h("p", { class: "muted" }, plural(rows.length, "run") + " · " + passed + " of " + plural(measured.length, "measured run")
    + " passed · " + rows.filter((r) => r.apparatus_failure).length + pick(" failures of the AI tool itself, counted apart", " apparatus failures, counted apart")));
  out.push(h("div", { class: "tbl" }, h("table", { class: "runs" }, h("caption", { class: "vh" }, "Gnomon runs"),
    h("thead", null, h("tr", null, (technical() ? ["Run", "Role and model", "Verdict and native values", "Audit chain", "Cost and tokens"]
      : ["Run", "Who worked (role and AI model)", "Result", "Record intact?", "Cost"])
      .map((t, i) => h("th", { scope: "col", class: i === 4 ? "num" : null }, t)))),
    h("tbody", null, rows.map((r) => {
      const n = r.native || {};
      const ch = r.chain || {};
      const tk = r.tokens || {};
      const native = ["bucket " + (n.bucket || "-"), "code " + (n.code !== undefined && n.code !== null ? n.code : "-")]
        .concat(n.verify ? ["verify " + n.verify] : []).join(" · ");
      const id = String(r.run || "-");
      return h("tr", { "data-id": r.run || null },
        h("td", null, h("span", { class: "mono nowrap" }, r.task ? r.task + (r.round !== null && r.round !== undefined ? " · round " + r.round : "") : "no task"),
          h("div", { class: "runid", title: id }, id.length > 22 ? "…" + id.slice(-21) : id), h("div", { class: "label" }, fmtAt(r.at))),
        h("td", null, agentBadge(String(r.role || "agent").replace(/_/g, " "), r.model)),
        h("td", null, badge(verdictKind(r.verdict), r.verdict),
          r.apparatus_failure ? [" ", badge("warn", pick("the AI tool failed", "apparatus failure"))] : null,
          r.tampered ? [" ", badge("crit", "tampered")] : null,
          h("div", { class: "native" }, native)),
        h("td", null, ch.intact ? badge("ok", "intact") : badge("crit", "broken"),
          h("div", { class: "native" }, ch.intact ? plural(ch.records, "record") + " re-verified"
            : ch.broken_seq !== null && ch.broken_seq !== undefined ? "breaks at record " + ch.broken_seq : "no trail")),
        h("td", { class: "num" }, fmtCost(r.cost),
          h("div", { class: "native" }, tk.in === null || tk.in === undefined ? "tokens not measured"
            : num(tk.in) + " in · " + num(tk.out) + " out")));
    })))));
  out.push(h("p", { class: "muted small" }, "A cost that was not measured (a model missing from the price table, or a run "
    + "without token counts) is shown as not measured, never as zero. The factory-wide view is the ",
  h("a", { href: "#/floor" }, "Floor"), "."));
  return h("div", null, out);
};

// -- releases

function renderValue(v, depth) {
  if (v === null || v === undefined) return h("span", { class: "muted" }, "none");
  if (Array.isArray(v)) {
    if (!v.length) return h("span", { class: "muted" }, "none");
    return h("ul", null, v.map((x) => h("li", null, renderValue(x, depth + 1))));
  }
  if (typeof v === "object") {
    if (depth > 3) return h("code", null, JSON.stringify(v));
    return h("dl", null, Object.entries(v).map(([k, x]) => [h("dt", null, k), h("dd", null, renderValue(x, depth + 1))]));
  }
  if (typeof v === "boolean") return badge(v ? "ok" : "nm", v ? "yes" : "no");
  return String(v);
}

const RELEASE_FIRST = ["environment", "env", "status", "state", "revision", "image", "road", "at", "created"];
const RELEASE_PARTS = ["steps", "gates", "holdouts", "shadow", "canary", "rollback", "provenance"];

VIEW_FN.releases = function viewReleases(p) {
  const out = [viewHead("Releases", word("q.releases"))];
  if (!p.releases.length) {
    out.push(emptyState("releases", null, p.meta.maturity === "explore" ? { how: emptyHow("releases")
      + pick(" With the ambition explore, the result stays a preview on this computer.", " At explore maturity the result stays a local preview.") } : null));
    return h("div", null, out);
  }
  out.push(h("div", { class: "cards" }, p.releases.slice().reverse().map((r) => {
    const d = r.data && typeof r.data === "object" ? r.data : {};
    const env = d.environment || d.env;
    const head = RELEASE_FIRST.filter((k) => k in d && k !== "environment" && k !== "env");
    const parts = RELEASE_PARTS.filter((k) => k in d);
    const rest = Object.keys(d).filter((k) => !RELEASE_FIRST.includes(k) && !RELEASE_PARTS.includes(k));
    return h("article", { class: "card release", "data-id": r.name, "aria-labelledby": "rl-" + r.name },
      h("div", { class: "hd" }, glyph("kernel"), h("b", { id: "rl-" + r.name }, "Release " + r.name),
        env ? h("span", { class: "s kernel" }, String(env)) : null),
      r.data === null ? h("p", { class: "empty" }, "This release file could not be read.") : null,
      head.length ? h("dl", { class: "kv" }, head.map((k) => h("div", null, h("dt", null, k), h("dd", null, renderValue(d[k], 2))))) : null,
      h("div", { class: "grid3 val" }, parts.concat(rest).map((k) => h("div", { class: "panel" },
        label(k), renderValue(d[k], 1)))),
      h("details", null, h("summary", null, "Raw release record"), h("pre", null, JSON.stringify(r.data, null, 2))));
  })));
  return h("div", null, out);
};

// -- changes

function decidedLine(c) {
  if (c.decision) {
    const d = c.decision;
    return h("p", { class: "answerline" }, VERDICT_LABEL[d.verdict] || d.verdict, " by ", personBadge(d.person, d.persona),
      d.delegation ? h("a", { href: link(S.project ? S.project.meta.id : "", "track"), class: "muted" }, " by delegation " + d.delegation) : null,
      d.reason ? ": " + d.reason : "", h("span", { class: "muted" }, " · " + fmtAt(d.at)));
  }
  if (c.closed) return h("p", { class: "answerline" }, cap(c.state) + " by ", agentBadge(kernelWord()), ": ", datum(c.closed.why));
  return null;
}

function changeCard(p, c) {
  const pid = p.meta.id;
  const pl = c.payload || {};
  const t = pl.triage || null;
  const open = c.state === "open";
  const state = c.state === "decided" && c.decision
    ? badge(c.decision.verdict === "accept" ? "ok" : "nm", c.decision.verdict)
    : badge(open ? "warn" : "ok", open ? "open" : c.state);
  return h("article", { class: "card" + (open ? " decision" : ""), "data-id": c.id, "aria-labelledby": "chg-" + c.id },
    h("div", { class: "hd" }, glyph(open ? "human" : "kernel"), label(c.id),
      t ? label(CLASS_LABEL[t.class] || t.class) : badge("nm", pick("not sorted yet", "not triaged"), explain("triage")), state),
    h("h3", { class: "card-t", id: "chg-" + c.id }, datum(c.title)),
    c.body && c.body.trim() !== c.title.trim() ? h("div", { class: "body", "data-ud": "" }, c.body) : null,
    t ? triageLine(t, pl) : h("div", { class: "facts" }, h("span", null, "from " + personaLabel(pl.source)
      + (pl.person ? " (" + pl.person + ")" : ""))),
    impactPanel(pid, c, !open),
    open && decides("change") ? decideForm(pid, c)
      : open ? h("p", { class: "muted small" }, "Waits on a decision by " + c.deciders.map(personaLabel).join(" or ") + ".")
        : decidedLine(c));
}

VIEW_FN.changes = function viewChanges(p, inbox, ctx) {
  const pid = p.meta.id;
  const persona = personaLabel(S.persona);
  const options = OBSERVATIONS[S.persona] || DEFAULT_OBSERVATIONS;
  const form = h("form", { class: "form panel", "aria-labelledby": "ch-h", novalidate: true },
    h("h3", { id: "ch-h" }, pick("Report a change or something you noticed, as " + persona, "Report a change or an observation as the " + persona + " persona")),
    h("div", { class: "field" }, h("label", { for: "ch-kind" }, "What is it?"),
      h("select", { id: "ch-kind", name: "kind" }, options.map(([, text], i) => h("option", { value: String(i) }, text)))),
    h("div", { class: "field" }, h("label", { for: "ch-text" }, "What did you see, or what should change?"),
      h("textarea", { id: "ch-text", name: "text", rows: "4", required: true })),
    h("div", { class: "btns" }, h("button", { type: "submit", class: "btn primary", "data-control": "report" }, "Submit")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = form.elements.text.value.trim();
    if (!text) { say("Describe the change first.", "warn"); form.elements.text.focus(); return; }
    if (!needPerson()) return;
    const hint = options[Number(form.elements.kind.value)][0] || null;
    run(form.querySelector('button[type="submit"]'), form, async () => {
      const out = await api("POST", "/api/projects/" + enc(pid) + "/changes", Object.assign({ text, hint }, signed()));
      const t = out.triage;
      say(out.card.id + " is a " + (CLASS_LABEL[t.class] || t.class) + ": it goes back to " + tw("stage") + " " + t.way_back + " ("
        + stageWord(t.way_back, stageName(t.way_back)) + ")" + (t.needs_decision ? " after a business decision." : "."), "ok");
      await settle(["#" + CSS.escape("chg-" + out.card.id)]);   // the new change's card
    });
  });
  const mine = h("label", null, h("input", { type: "checkbox", checked: S.onlyMine, "data-key": "onlymine" }),
    "Only my reports" + (S.person.trim() ? " (" + S.person.trim() + ")" : ""));
  mine.querySelector("input").addEventListener("change", (e) => { S.onlyMine = e.target.checked; nav.route(true); });
  const changes = p.changes.filter((c) => !S.onlyMine || (c.payload || {}).person === S.person.trim() || c.id === ctx.focus)
    .slice().reverse();
  const openFirst = changes.filter((c) => c.state === "open").concat(changes.filter((c) => c.state !== "open"));
  return h("div", null,
    viewHead("Changes", "What should change, where does each change go back to, and what would it touch?"),
    form,
    h("div", { class: "viewbar section" }, h("h3", null, "Changes"), mine),
    openFirst.length ? h("div", { class: "cards" }, openFirst.map((c) => changeCard(p, c)))
      : S.onlyMine ? emptyState("changes", null, { what: "You have not reported anything here.",
        how: "Reports you send with the form above appear here; untick “Only my reports” to see everyone's." })
        : emptyState("changes", h("p", { class: "muted small" }, "When something does not work, or should work differently, describe it in "
          + "the form above in your own words: what you did, what you saw, what you expected. " + BRAND + " sends each report back to the "
          + tw("stage") + " that can fix it, and shows what changing it would touch before anyone decides."),
        { what: "No changes yet.", how: pick("A change appears here once someone reports one, with the form above or Change in the header.",
          "A change card appears here once one is filed (the form above, Change in the header, or `rihmasto change`); each lists its impact.") }),
    (p.lessons || []).length ? h("section", { class: "section" }, h("h3", null, pick("What was learned", "Lessons left behind")),
      h("ul", { class: "plain" }, p.lessons.map((l) => h("li", null, h("span", { class: "mono" }, l.card), ": ", datum(l.text),
        l.regression_criterion ? pick(" → a new check ", " → regression criterion ") + l.regression_criterion : "")))) : null);
};

// -- ledger

// Every decision row names its accountable person: a decision is only ever a person's.
function decisionsTable(decisions) {
  return h("div", { class: "tbl" }, h("table", null,
    h("thead", null, h("tr", null, ["Decision", pick("About", "Card"), tw("verdict", 1, { cap: true }), "Accountable person", "At",
      tw("stale", 1, { cap: true })].map((t) => h("th", { scope: "col" }, t)))),
    h("tbody", null, decisions.slice().reverse().map((d) => h("tr", { "data-id": d.id }, h("td", { class: "mono" }, d.id),
      h("td", { class: "mono" }, d.card || "-"), h("td", null, VERDICT_LABEL[d.verdict] || d.verdict),
      h("td", null, personBadge(d.person, d.persona), d.delegation ? h("span", { class: "muted small" }, " by delegation " + d.delegation) : null),
      h("td", { class: "num" }, fmtAt(d.at)),
      h("td", null, d.stale ? badge("warn", tw("stale") + (d.stale_reason ? ": " + d.stale_reason : ""), explain("stale")) : ""))))));
}

VIEW_FN.ledger = function viewLedger(p) {
  const l = p.ledger;
  const verdict = l.intact
    ? h("div", { class: "panel" }, badge("ok", "intact"), pick(" Nothing in the record has been changed or removed since it was written",
      " The hash chain verifies"),
    l.tail_checked ? pick(", up to the last entry the cockpit remembered.", " up to the head the cockpit kept (seq " + (l.kept_head ? l.kept_head.seq : "?") + ").") : ".")
    : h("div", { class: "panel" }, badge("crit", pick("damaged", "broken")), pick(" The record has been changed after it was written",
      " The chain does not verify"),
    l.broken_seq !== null && l.broken_seq !== undefined ? pick(": the first changed entry is number ", ": the first broken record is seq ") + l.broken_seq : "",
    l.tail_checked ? pick(", compared with the last entry the cockpit remembered.", ", checked against the head the cockpit kept.") : ".");
  return h("div", null,
    viewHead(viewWord("ledger", "Ledger"), pick("Can the record be trusted? Every decision and event is added in order and can never be edited.",
      "Can the record be trusted? Every transition is appended and hash-chained.")),
    verdict,
    h("dl", { class: "kv section" },
      h("div", null, h("dt", null, pick("entries", "records")), h("dd", null, String(l.records))),
      technical() ? h("div", null, h("dt", null, "head"), h("dd", { class: "mono" }, "seq " + l.head.seq + " · " + short(l.head.hash))) : null,
      technical() ? h("div", null, h("dt", null, "head the cockpit kept"), h("dd", { class: "mono" }, l.kept_head ? "seq " + l.kept_head.seq + " · " + short(l.kept_head.hash) : "none yet")) : null,
      h("div", null, h("dt", null, pick("checked to the end", "tail checked")), h("dd", null, l.tail_checked ? "yes" : "no"))),
    actorLegend(),
    h("section", { class: "section", "aria-labelledby": "dc-h" }, h("h3", { id: "dc-h" }, "Decisions"),
      p.decisions.length ? decisionsTable(p.decisions) : emptyState("ledger")),
    h("section", { class: "section", "aria-labelledby": "ev-h" }, h("h3", { id: "ev-h" }, "Recent events"),
      h("div", { class: "tbl" }, h("table", null,
        h("thead", null, h("tr", null, [pick("No.", "Seq"), "Event", "Who acted", "At"].map((t) => h("th", { scope: "col" }, t)))),
        h("tbody", null, l.recent.slice().reverse().map((e) => h("tr", null, h("td", { class: "num" }, String(e.seq)),
          h("td", { class: "mono" }, e.kind), h("td", null, actorBadge(e.actor)), h("td", { class: "num" }, fmtAt(e.at)))))))));
};

// -- the brief: a small, safe markdown renderer (text nodes only) ------------------------------

function inline(text) {
  const parts = [];
  const re = /\*\*([^*]+)\*\*|\[(owner(?::[^\]]*)?|assumed|proposed)\]/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    if (m[1] !== undefined) parts.push(h("strong", null, m[1]));
    else {
      const kind = m[2].startsWith("owner") ? "owner" : m[2];
      parts.push(h("span", { class: "tag " + kind }, m[2]));
    }
    last = re.lastIndex;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function renderMarkdown(text) {
  const out = h("div", { class: "md" });
  let list = null;
  for (const line of String(text).split("\n")) {
    if (!line.trim()) { list = null; continue; }
    let m = /^(#{1,4})\s+(.*)$/.exec(line);
    if (m) { list = null; out.append(h("h" + Math.min(6, m[1].length + 2), null, inline(m[2]))); continue; }
    m = /^(\s*)[-*] (.*)$/.exec(line);
    if (m) {
      if (!list) { list = h("ul"); out.append(list); }
      list.append(h("li", { class: m[1].length ? "sub" : null }, inline(m[2])));
      continue;
    }
    list = null;
    out.append(h("p", null, inline(line)));
  }
  return out;
}

// -- the project page -------------------------------------------------------------------------------

// The views this project has, by capsule (capsules.js): every registered view that applies and whose module is on.
function orderedViews(p, ctx, planOpen, current) {
  return availableViews(p, { planOpen, current, lens: ctx, builtIn: (id) => !!VIEW_FN[id] }, viewOn);
}
// A registered view drawn by a module of its own (capsules.js registerView with `render` or `module`).
function registeredBody(view, p, inbox, ctxObj) {
  const r = registered(view);
  if (r && r.render) return r.render(p, inbox, ctxObj);
  const holder = h("div", { "aria-busy": "true" }, h("p", { class: "muted small" }, "Opening " + labelOf(view) + "…"));
  import("./" + r.module).then((m) => { holder.removeAttribute("aria-busy"); fill(holder, m.render(p, inbox, ctxObj)); })
    .catch((e) => { holder.removeAttribute("aria-busy"); fill(holder, empty("alert", labelOf(view) + " could not open: " + e.message)); });
  return holder;
}

export async function renderProject(r, keep, seq) {
  const main = $("#main");
  const done = keep ? () => {} : skeleton(main, "the project");
  try {
    return await drawProject(main, r, seq, done);
  } finally {
    done();   // drawn, superseded or failed: the placeholder never covers the page or the error after it
  }
}

async function drawProject(main, r, seq, done) {
  const pid = r.pid;
  const isFactory = pid === FACTORY_PID;
  const base = "/api/projects/" + enc(pid);
  const none = Promise.resolve(null);
  const [p, inbox, ctx] = await Promise.all([
    api("GET", base),
    api("GET", base + "/inbox?persona=" + enc(inboxPersona())),   // "everything": every card the person holds (FR-PPL1)
    isFactory ? none : api("GET", base + "/context?persona=" + enc(S.persona) + "&lens=" + enc(S.lens || "")),
  ]);
  if (seq !== S.seq) return false;
  const planOpen = !isFactory && (p.open_cards || []).some(isPlanCard);
  // The Plan tab stays where it was while it is the view in front, also once the plan is approved.
  const views = orderedViews(p, ctx, planOpen, r.view);
  const view = r.view && VIEWS[r.view] && (isFactory ? FACTORY_VIEWS.includes(r.view) : viewOn(r.view, pid)) ? r.view
    : isFactory ? views[0] : defaultView(pid, views);   // the persona's capsule (capsules.js)
  const shown = views.concat(views.includes(view) ? [] : [view]);
  const taskMode = viewChoice("tasks", "board");
  const [findings, cellRows, planFirst, tryFirst, timeline, comments, attestation, pack, track, outputs, assessment] = await Promise.all([
    isFactory || view !== "overview" ? none : api("GET", base + "/alignment"),
    view === "cell" ? api("GET", base + "/cell") : none,
    !isFactory && view === "plan" ? api("GET", base + "/plan") : none,
    !isFactory && view === "try" ? api("GET", base + "/try") : none,
    !isFactory && view === "tasks" && taskMode === "timeline" ? api("GET", base + "/timeline") : none,
    isFactory ? none : api("GET", base + "/comments").catch(() => null),
    !isFactory && view === "evidence" ? api("GET", base + "/attestation") : none,
    !isFactory && view === "releases" && (p.releases || []).length ? api("GET", base + "/pack").catch((e) => ({ error: e.message })) : none,
    !isFactory && view === "track" ? api("GET", base + "/track") : none,
    !isFactory && view === "outputs" ? api("GET", base + "/outputs") : none,
    !isFactory && view === "assessment" ? api("GET", base + "/assessment").catch((e) => ({ error: e.message })) : none,
  ]);
  const align = !isFactory && view === "align" ? await api("GET", base + "/repo-alignment").catch((e) => ({ error: e.message })) : null;
  if (seq !== S.seq) return false;
  let plan = planFirst;
  let tryIt = tryFirst;
  const needPlan = !plan && !isFactory && view === "inbox" && inbox.cards.some(isPlanCard);
  const needTry = !tryIt && !isFactory && view === "inbox" && inbox.cards.some(acceptsRelease);
  if (needPlan || needTry) {
    [plan, tryIt] = await Promise.all([needPlan ? api("GET", base + "/plan") : Promise.resolve(plan),
      needTry ? api("GET", base + "/try") : Promise.resolve(tryIt)]);
    if (seq !== S.seq) return false;
  }
  done();
  S.project = p;
  S.inbox = inbox;
  S.context = ctx;
  S.projectViews = { pid, views: shown, current: view, inbox: inbox.cards.length, planOpen };
  const meta = p.meta;
  document.title = meta.title + " · " + labelOf(view) + " · " + BRAND;
  rememberProject(pid);
  rememberView(pid, view);
  // The capsules: five top tabs, each with its own short row of views (capsules.js, FR-UXO1).
  const waits = capsuleWaits(p, inbox, shown);
  const drawTabs = () => capsuleNav(pid, shown, view, waits, { planOpen, customizing: !!S.customizingView,
    onChange: () => { const old = $(".caps", main); if (old) old.replaceWith(drawTabs()); } });
  const tabs = isFactory ? h("nav", { class: "caps", "aria-label": "Project areas" }, h("ul", { class: "tabs caps-sub", role: "list" },
    shown.map((v) => h("li", null, h("a", { href: link(pid, v), "aria-current": v === view ? "page" : null, class: v === view ? "on" : null },
      icon(VIEWS[v].icon), h("span", null, labelOf(v)),
      v === "inbox" && inbox.cards.length ? h("span", { class: "count" }, String(inbox.cards.length)) : null)))))
    : drawTabs();
  const ctxObj = { pid, focus: r.focus, cell: cellRows, plan, tryIt, planOpen, timeline, comments, attestation, pack, track, outputs, assessment, align };
  let body = VIEW_FN[view] ? VIEW_FN[view](p, inbox, ctxObj) : registeredBody(view, p, inbox, ctxObj);
  if (comments) decorateComments(body, pid, view, comments.comments || []);
  if (view === "overview" && !isFactory) {
    body = h("div", { class: "with-side" }, body, h("div", { class: "side-col" }, alignmentPanel(pid, findings || []), stageCounts(p),
      whereCard(pid)));   // "Where this goes" (destinations.js, FR-DST1)
  }
  // Start here on the project's first view: what it is, what to do now, what runs meanwhile (starthere.js, FR-LND1)
  const first = !isFactory && !r.focus && (!r.view || view === "overview");   // entering it, or its Overview
  const viewBody = h("div", { class: "view-body", "data-view": view }, first ? startHerePanel(p, { entering: !r.view }) : null, body);
  fill(main, projectHead(p, isFactory, ctx), tabs, viewBody);
  S.redrawTabs = isFactory ? null : () => { const old = $(".caps", main); if (old) old.replaceWith(drawTabs()); };
  applyViewLayout(viewBody, "p:" + view);   // the person's own layout of this view (viewcustom.js)
  if (LIVE.el) startLive();
  if (!isFactory) watchJobs(p, seq);
  if (nav.refreshShell) nav.refreshShell();
  return true;
}

// While one of the project's jobs runs, the page checks every 4 s whether it ended, and re-renders
// once it has: Advance and the job cards never say "running" for a job that is done. The check waits
// while the person types in a field, so a re-render never takes what they wrote; it stops with the page.
// The person did nothing to cause that re-render, so the focus stays where they left it (refocus).
const JOBS_EVERY = 4000;
function watchJobs(p, seq) {
  // a console run follows itself on the Console tab (console.js): it never re-renders the page
  const running = (p.jobs || []).filter((j) => j.state === "running" && j.kind !== "console").map((j) => j.id);
  if (!running.length) return;
  const pid = p.meta.id;
  const again = () => { if (seq === S.seq) S.timer = setTimeout(tick, JOBS_EVERY); };
  const tick = async () => {
    if (seq !== S.seq) return;
    if (document.hidden) { again(); return; }
    let jobs = null;
    try {
      jobs = await api("GET", "/api/jobs?project=" + enc(pid));
    } catch (e) {
      if (e instanceof AuthError) return;
    }
    if (seq !== S.seq) return;
    const ended = (jobs || []).filter((j) => running.includes(j.id) && j.state !== "running");
    if (!jobs || ended.length < running.length || typingNow() || $("#modal").open) { again(); return; }
    const j = ended[0];
    const oc = j.outcome || {};
    const why = oc.state ? oc.state.replace(/_/g, " ") + (oc.why ? ", " + oc.why.replace(/\.$/, "") : "") : "";
    say("Job " + j.id + " ended (" + j.state + ")." + (why ? " Where it stopped: " + why + "." : ""), j.state === "failed" ? "warning" : "info");
    const mark = focusMark();
    await nav.rerender();
    if (S.route && S.route.name === "project" && S.route.pid === pid) refocus(mark);   // still this project's page
  };
  again();
}

// The header: profile, title, maturity and mode, health, autonomy cap, ledger; the now line; the
// seven stages as a compact stepper; Pause or Resume and Advance.
function projectHead(p, isFactory, ctx) {
  const meta = p.meta;
  const sum = p.stage_summary || {};
  const au = p.autonomy;
  const chips = isFactory ? [ledgerBadge(p.ledger)] : [
    chip("neutral", "layers", tw("maturity", 1, { cap: true }) + ": " + ambitionWord(meta.maturity),
      { tip: ambitionLong(meta.maturity, (S.meta.maturities || {})[meta.maturity] || explain("maturity")) }),
    chip("neutral", "comment", tw("mode", 1, { cap: true }) + ": " + modeWord(meta.mode), { tip: (S.meta.modes || {})[meta.mode] || explain("mode") }),
    // one on-track answer: the Track pill (it carries every reason the health reads), else the health
    trackPill(p) || healthChip(p.health),
    au ? autonomyChip(p) : null,
    postureChip(p),                   // how it runs: the posture, what it does and what holds the project (posture.js)
    // a confidential project says so where it is worked on: its model calls go to local models only
    meta.confidential ? chip("neutral", "shield", "Confidential: local models only", { tip: "Its model calls go only "
      + "to endpoints on this machine or a private network; a role routed to a hosted endpoint is refused, never sent, "
      + "and a hosted fallback is skipped. Models setup routes the roles." }) : null,
    ledgerBadge(p.ledger),
    p.stale.length ? badge("warn", p.stale.length + " " + tw("stale") + " " + (p.stale.length === 1 ? "approval" : "approvals"), explain("stale")) : null,
    p.problems.length ? badge("crit", "unreadable: " + p.problems.join(", ")) : null,
    sum.current > sum.last ? badge("nm", pick("further along than planned for a " + ambitionWord(meta.maturity),
      "beyond " + meta.maturity + "'s stages 1-" + sum.last + ": later stages ran by request")) : null,
  ];
  return h("header", { class: "proj-head" },
    h("div", { class: "ph-top" },
      h("div", { class: "ph-id" },
        isFactory ? h("span", { class: "chip profile" }, icon("sparkles"), h("span", null, pick("Rihmasto's own improvements", "The factory's own canon")))
          : kindChip(p),            // never a kind that is not chosen (adopted.js)
        h("h1", { id: "view-title", tabindex: "-1" }, isFactory ? titleOf(meta.id, meta.title) : meta.title),
        technical() ? h("span", { class: "mono muted small" }, meta.id) : null),   // the id is a developer's; Details keeps it
      isFactory ? null : h("div", { class: "ph-acts" }, changeButtons(p), handoffButton(p), channelPanelButton(p),
        pauseControls(p), advanceButton(p))),
    h("div", { class: "chips" }, chips),
    nowLine(p.now, meta.id, p),
    isFactory ? h("p", { class: "lede" }, "Proposals to change " + BRAND + " itself, such as a default check every new project carries. "
      + "A person decides each one" + pick(". The accepted ones apply to new projects.", ", like any card; "),
      technical() ? h("code", null, "python -m kernel.cli learn") : null, technical() ? " applies the accepted ones." : null)
      : p.adopted ? adoptedLine(p) : stepper(p, ctx));     // an adopted project's real state, not stages (FR-RPJ1)
}

// The autonomy cap in the header is a button: it opens this project's ladder, what each level lets the
// factory do, and, for a persona that sets caps, a form to set this project's own cap (never above the
// factory's) with a reason. The kernel decides whether it stands (PUT /api/projects/<pid>/autonomy).
function autonomyChip(p) {
  const au = p.autonomy;
  const b = h("button", { type: "button", class: "chip accent au-chip", "data-control": "autonomy", "data-key": "autonomy",
    "aria-haspopup": "dialog", tip: "Level " + au.cap + ", " + au.name + ": " + au.meaning + ". Open the ladder." },
  icon("gauge"), h("span", null, pick(autonomyWord(au.cap), "Autonomy cap " + au.cap + " of 5 · " + au.name)));
  b.addEventListener("click", () => openAutonomy(p));
  return b;
}

async function openAutonomy(p) {
  const pid = p.meta.id;
  const au = p.autonomy;
  const setters = ((S.meta && S.meta.autonomy) || {}).setters || [];
  const may = mayAct(setters);
  let all = null;
  let err = null;
  try {
    all = await api("GET", "/api/autonomy");
  } catch (e) {
    if (e instanceof AuthError) return;
    err = e;
  }
  const fac = (all && all.factory) || null;
  const mine = ((all && all.projects) || []).find((x) => x.project === pid) || {};
  const own = mine.own === undefined || mine.own === null ? null : mine.own;
  const history = ((all && all.history) || []).filter((x) => x.project === pid).slice(0, 5);
  let changed = false;
  const body = h("div", { class: "au-body" },
    h("p", null, "The factory may act alone up to level ", h("b", null, au.cap + " (" + au.name + ")"), " on this project: " + au.meaning + "."),
    fac ? h("p", { class: "muted small" }, "The factory's own cap is " + fac.cap + " (" + fac.name + "). "
      + (own !== null ? "This project has its own cap of " + own + "." : "This project follows the factory's cap.")
      + " A project's cap may be lower than the factory's, never higher.")
      : h("p", { class: "muted small" }, "The factory's cap could not be read" + (err ? ": " + err.message : "") + "."),
    h("ol", { class: "ladder" }, (au.levels || []).map((l) => h("li", { class: "rung" + (l.allowed ? " on" : "") + (l.level === au.cap ? " cap" : "") },
      h("span", { class: "rung-n" }, String(l.level)), h("div", null, h("b", null, l.name), h("p", null, l.meaning)),
      l.level === au.cap ? chip("accent", "gauge", "Cap") : null))));
  if (may && fac) {
    const levels = (au.levels || []).filter((l) => l.level <= fac.cap);
    const sel = h("select", { id: "au-level", "data-key": "au-level" }, levels.map((l) => h("option", { value: String(l.level), selected: l.level === au.cap },
      l.level + " " + l.name)));
    const reason = h("input", { id: "au-reason", "data-key": "au-reason", maxlength: "2000", autocomplete: "off",
      placeholder: "for example: the pilot runs on customer data" });
    const save = h("button", { type: "submit", class: "btn human primary" }, "Set this project's cap");
    const form = h("form", { class: "au-form", novalidate: true, "aria-label": "Set the autonomy cap of " + p.meta.title },
      h("div", { class: "field" }, h("label", { for: "au-level" }, "Cap for this project"), sel),
      h("div", { class: "field" }, h("label", { for: "au-reason" }, "Reason (required, recorded with your name)"), reason),
      h("div", { class: "btns" }, save));
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      if (!reason.value.trim()) { say("A cap change needs a reason: it is recorded with your name.", "warning"); reason.focus(); return; }
      if (!needPerson()) return;
      run(save, form, async () => {
        const out = await api("PUT", "/api/projects/" + enc(pid) + "/autonomy",
          Object.assign({ level: Number(sel.value), reason: reason.value.trim() }, signed()));
        changed = true;
        say(p.meta.title + ": the autonomy cap is " + out.cap + ", signed by " + S.person.trim() + ".", "good");
        closeModal();
      });
    });
    body.append(form);
  } else if (!may) {
    body.append(h("p", { class: "muted small" }, "A " + orList(setters) + " persona sets the cap, always with a reason."));
  }
  if (history.length) {
    body.append(h("section", { "aria-labelledby": "au-hist-h" }, h("h3", { id: "au-hist-h", class: "label-h" }, "Earlier changes"),
      h("ul", { class: "plain small" }, history.map((x) => h("li", null, (x.from === null || x.from === undefined ? "the factory's cap" : String(x.from))
        + " → " + x.to + " by ", personBadge(x.by, x.persona), x.reason ? ": “" + x.reason + "”" : "", x.at ? h("span", { class: "muted" }, " · " + fmtAt(x.at)) : null)))));
  }
  openModal("Autonomy cap · " + p.meta.title, body, { icon: "gauge", onClose: () => { if (changed && nav.rerender) nav.rerender(); } });
}

const STEP_STATE = { done: "done", now: "the current stage", ahead: "ahead" };
function stepper(p) {
  const sum = p.stage_summary;
  const pid = p.meta.id;
  const planOpen = (p.open_cards || []).some(isPlanCard);
  const viewOf = (n) => (planOpen && (n === 3 || n === 4) ? "plan" : STAGE_VIEW[n]);
  return h("ol", { class: "stepper", "aria-label": "Stages: " + sum.current + " of 7" }, sum.stages.map((s) => {
    const st = s.state;
    const said = stageCount(p, s);
    const state = st === "off" ? "not at " + p.meta.maturity : STEP_STATE[st] || st;
    const name = stageWord(s.stage, cap(s.name));
    // The link names its stage at every width: below 1100px only its icon shows, and the icon is hidden.
    const a = h("a", { href: link(pid, viewOf(s.stage)), class: "step " + st, "aria-current": st === "now" ? "step" : null,
      "aria-label": tw("stage", 1, { cap: true }) + " " + s.stage + ": " + name + ", " + said + ", " + state },
    h("span", { class: "step-ic" }, icon(st === "done" ? "check" : STAGE_ICON[s.stage])),
    h("span", { class: "step-t" }, h("span", { class: "step-n" }, name), h("small", null, said)));
    attachTip(a, () => tipBox(tw("stage", 1, { cap: true }) + " " + s.stage + " · " + name, [{ value: said, label: "" },
      { value: state, label: bandOf(s.stage) + " band" }]));
    return h("li", null, a);
  }));
}

function stageCounts(p) {
  if (p.adopted) return adoptedSide(p);      // an adopted project did not go through the stages (FR-RPJ1)
  const sum = p.stage_summary || { stages: [] };
  return card({ title: tw("stage", 2, { cap: true }), icon: "pipeline", cls: "stage-counts",
    info: "The seven " + tw("stage", 2) + " in four bands: Decide (1 and 2), Shape (3 and 4), Deliver (5 and 6) and Run (7)." },
  h("ul", { class: "sc-list" }, sum.stages.map((s) => h("li", { class: "sc " + s.state },
    h("span", { class: "sc-ic" }, icon(s.state === "done" ? "check" : STAGE_ICON[s.stage])),
    h("span", { class: "sc-n" }, s.stage + " " + stageWord(s.stage, cap(s.name))), h("span", { class: "sc-c" }, stageCount(p, s)),
    stageEvidence(p, s) ? h("span", { class: "sc-e" }, s.evidence.verified + " " + pick("proven", "verified") + " · " + s.evidence.claimed + " claimed") : null))));
}

// Advance starts a run signed with the person's name, like every other write; the kernel goes as far
// as it can. The focus moves to the next control, since the button is off while the job runs.
function advanceWrite(p, btn, container, to) {
  if (!needPerson()) return;
  run(btn, container, async () => {
    const out = await api("POST", "/api/projects/" + enc(p.meta.id) + "/advance", signed());
    say(technical() ? "Job " + out.job.id + " started by " + S.person.trim() + ": python " + out.job.args.join(" ")
      : p.meta.title + " is moving on in the background, started by " + S.person.trim() + ". It stops at the next decision a person makes.", "good");
    await settle(to);
    briefAfterAdvance(p.meta.id, S.person.trim());
  });
}
function advanceButton(p) {
  if (!mayAdvance()) return null;   // like Pause: the Advance panel says who advances the project
  const running = p.jobs.some((j) => j.state === "running" && j.kind !== "console");   // a console run holds nothing
  const paused = !!p.meta.pause;
  const b = button(running ? "Running" : "Advance", { icon: running ? "refresh" : "play", kind: "primary", key: "advance",
    disabled: running || paused, tip: paused ? "Paused: resume it first" : running ? "A job is running for this project"
      : pick("Moves the project on as far as it can, up to the next decision a person makes",
        "Runs kernel.cli run in the background, up to the next gate a person decides") });
  b.addEventListener("click", () => advanceWrite(p, b, b.parentNode, ['[data-key="pause"]', '[data-key="resume"]', "#adv-h"]));
  return b;
}

// Tasks as a board, a timeline or a table (Ctrl+B cycles); the choice is kept per view.
const TASK_MODES = [["board", "Board", "pipeline"], ["timeline", "Timeline", "timeline"], ["table", "Table", "table"]];
const tasksBoard = VIEW_FN.tasks;
VIEW_FN.tasks = function viewTasks(p, inbox, ctx) {
  const mode = viewChoice("tasks", "board");
  const pid = p.meta.id;
  // A re-render that keeps the place: the chosen mode's button keeps the focus (by its data-key).
  const bar = h("div", { class: "viewbar" }, segmented("tasks-mode", TASK_MODES, mode, (v) => { setViewChoice("tasks", v); nav.rerender(); },
    { label: "Show the tasks as" }), h("span", { class: "muted small" }, h("kbd", null, "Ctrl B"), " cycles"));
  if (mode === "timeline") {
    const tl = ctx.timeline || { tasks: [] };
    return h("div", null, viewHead("Tasks", pick("Where did the time go? Each attempt on one timeline, coloured by whether it passed its quality check.",
      "Where did the time go? Each round on one time axis, coloured by its gate's verdict.")), bar,
      card({ title: "Timeline", icon: "timeline" }, waterfall({ tasks: tl.tasks, href: (t) => link(pid, "tasks", t.task) })),
      p.running ? livePanel(p, "ov") : null, advancePanel(p));
  }
  if (mode === "table") {
    return h("div", null, viewHead("Tasks", pick("Every task with its status, attempts and last quality check.", "Every task with its status, rounds and last gate.")), bar,
      (p.tasks || []).length ? dataTable([{ label: "Task", value: (t) => h("a", { href: link(pid, "tasks", t.id), class: "mono" }, t.id) },
        { label: "Title", value: (t) => datum(t.title || "-") }, { label: "Status", value: (t) => statusWord(t.status) },
        { label: tw("round", 2, { cap: true }), value: (t) => t.rounds.length, num: true },
        { label: pick("Last quality check", "Last gate"), value: (t) => { const l = t.rounds[t.rounds.length - 1]; return l && l.gate ? l.gate.verdict : "-"; } },
        { label: tw("criterion", 2, { cap: true }), value: (t) => (t.criteria || []).join(", ") || "-" }], p.tasks, "Tasks")
        : emptyState("tasks"), advancePanel(p));
  }
  const board = tasksBoard(p, inbox, ctx);
  board.insertBefore(bar, board.children[1] || null);
  return board;
};
// Ctrl+B cycles the mode, but never while the person types: in a field it is the field's own key, and a
// re-render would take what they wrote. The focus goes to the new mode's button unless it is on a
// control the re-render finds again.
export function cycleTasksMode() {
  if (!S.route || S.route.name !== "project" || (S.projectViews || {}).current !== "tasks") return false;
  if (typingNow() || $("#modal").open) return false;
  const pz = $("#pause-form");
  if (pz && !pz.hidden) return false;   // an open Pause form keeps its reason
  const order = TASK_MODES.map((m) => m[0]);
  const next = order[(order.indexOf(viewChoice("tasks", "board")) + 1) % order.length];
  setViewChoice("tasks", next);
  const a = document.activeElement;
  if (!a || a === document.body || !(a.dataset && a.dataset.key) || a.closest(".seg")) {
    S.focusNext = '[data-key="tasks-mode:' + next + '"]';
  }
  nav.rerender();
  return true;
}

// Releases: each release's capability pack first (version, valid or why not, pinned hashes, YAML), then
// each release as the steps it went through, its holdouts and the rest of its record.
const OUTCOME = { passed: ["good", "check-circle"], done: ["good", "check-circle"], failed: ["critical", "x-circle"],
  skipped: ["nm", "dashed"], waiting: ["warning", "clock"] };
function outcomeChip(o) { const t = OUTCOME[o] || ["neutral", "info"]; return chip(t[0], t[1], cap(String(o || "not recorded"))); }
function hhmm(at) { return at ? String(at).replace("T", " ").replace(/:\d\dZ$/, " UTC").replace(/Z$/, " UTC") : ""; }
// Reading the pack never builds one (GET only reads what was written). Building is its own signed
// write: POST .../pack/build, which records a new version only when what the pack names changed.
function buildPackButton(pid, pk) {
  if (!moduleShows("controls", "build_pack", pid)) return null;  // the capability layer's module is off here
  const may = mayAct(pk.builders || []);
  const who = orList(pk.builders || []);
  const b = button(pk.pack ? "Build again" : "Build the capability pack", { icon: "package", kind: pk.pack ? "small" : "small primary",
    "data-control": "build_pack", key: "build-pack", disabled: !may || null,
    tip: may ? "Builds the latest release's pack, signed with your name. The version changes only when what it names changed."
      : who + " builds it." });
  b.addEventListener("click", () => {
    if (!needPerson()) return;
    run(b, b.parentNode, async () => {
      const out = await api("POST", "/api/projects/" + enc(pid) + "/pack/build", signed());
      say("Capability pack v" + out.pack.version + " for release " + out.pack.release + ", signed by " + S.person.trim() + ".", "good");
      await settle(['[data-key="build-pack"]']);
    });
  });
  return h("div", { class: "btns" }, b, may ? null : h("span", { class: "muted small" }, who + " builds it."));
}
// The models of one role, each said once: a model the pack names both bare and with the endpoint it ran
// through ("m" and "m@go") is one model, said with its endpoint.
function modelNames(v) {
  const all = Array.from(new Set((Array.isArray(v) ? v : []).map(String)));
  return all.filter((m) => m.includes("@") || !all.some((x) => x.startsWith(m + "@"))).join(", ");
}
// The runtime a small capability declares (kernel/runtime_decl.py) and how each of its faces is reached
// (docs/guides/small-capabilities.md). A web-service product's pack declares none and says so in one line.
const FACE_REACH = { mcp: ["MCP", "stdio, or POST /mcp"], openai: ["OpenAI-compatible chat", "POST /v1/chat/completions"],
  http: ["HTTP", "POST /capability/run"], embed: ["Website embed", "GET /embed/widget.js"] };
function startedBy(t) {
  const k = (t || {}).kind;
  if (k === "schedule") return "a schedule, every " + t.every_minutes + " minutes";
  if (k === "webhook") return "a verified webhook" + (t.source ? " from " + t.source : "");
  if (k === "event") return "a relay event: " + (t.types || []).join(", ");
  return k === "manual" ? "a person, by hand" : "not declared";
}
function runtimeSection(pack, pid) {
  const rt = pack.runtime || {};
  if (!rt.declared) {
    return h("p", { class: "muted small pack-runtime", "data-control": "capability_faces" }, "Runtime: ", rt.note || "not declared",
      (rt.problems || []).length ? " (" + rt.problems.slice(0, 3).join("; ") + ")" : "");
  }
  const list = (xs, f, none) => (xs || []).map(f).join(", ") || none;
  const rows = [["Kind", rt.kind], ["Started by", startedBy(rt.trigger)],
    ["Its own tools", list(rt.tools, (t) => t.name + " (" + t.effect + ")", "none")],
    ["Model roles", list(rt.model_roles, (r) => r.role + " via the gateway workload " + r.workload, "none")],
    ["Integrations", list(rt.integrations, (i) => i.system + " via " + i.via + (i.writes ? ", writes" : ""), "none")],
    ["Secrets, by name", list(rt.secrets, (s) => s, "none")]];
  const first = (rt.faces || ["mcp"])[0];
  const cmd = "rihmasto capability serve " + pid + " --face " + first + (first === "mcp" ? "" : " --port 8090");
  const copy = async () => {
    try { await navigator.clipboard.writeText(cmd); say("The command is copied.", "good"); } catch (e) { say("Copy it by hand.", "warning"); }
  };
  return h("section", { class: "pack-runtime", "data-control": "capability_faces", "aria-labelledby": "pack-rt-h" },
    h("h4", { id: "pack-rt-h" }, "Runtime and faces"),
    h("dl", { class: "pins" }, rows.map(([k, v]) => h("div", null, h("dt", null, k), h("dd", null, String(v))))),
    h("ul", { class: "faces", "aria-label": "Faces" }, (rt.faces || []).map((f) => h("li", null,
      chip("accent", "plug", (FACE_REACH[f] || [f])[0]), h("span", { class: "mono small" }, (FACE_REACH[f] || ["", ""])[1])))),
    h("p", { class: "small" }, "Serve it on this machine, behind its pack guard: ", h("code", { class: "mono" }, cmd)),
    h("div", { class: "btns" }, button("Copy the command", { icon: "copy", kind: "small", key: "copy-serve", onclick: copy })));
}
function packCard(pk, pid) {
  if (!pk) return null;
  const title = tw("capability_pack", 1, { cap: true });
  if (pk.error) return card({ title, icon: "package" }, h("p", { class: "muted" }, pk.error));
  if (!pk.pack) {
    return card({ title, icon: "package", cls: "pack", id: "pack",
      info: pick(explain("capability_pack") + " Looking at it never builds it.", "One manifest per release that names everything delivered by its hash. Showing it never builds it.") },
    h("p", null, chip("nm", "dashed", "Not built yet"), " ", datum(pk.note || "")), buildPackButton(pid, pk));
  }
  const pack = pk.pack;
  const acc = pack.acceptance || {};
  const pin = pack.pinned || {};
  const rows = [["Contract revision", pin.contract_revision], ["Product revision", pin.product_revision]]
    .concat(Object.entries(pin.artifacts || {}).map(([k, v]) => ["Artifact " + k, v]))
    .concat(Object.entries((pin.built_and_judged_by || {}).by_role || {}).map(([k, v]) => ["Built by " + k.replace(/_/g, " "), modelNames(v)]));
  const pins = h("dl", { class: "pins" }, rows.map(([k, v]) => h("div", null, h("dt", null, k), h("dd", { class: "mono" }, v ? String(v) : h("span", { class: "nm-text" }, "not recorded")))));
  const prov = h("p", { class: "muted small" }, cap((pack.provenance || {}).signature_note || ""), " · SBOM ", (pack.provenance || {}).sbom_note || "");
  return card({ title: title + " v" + pack.version, icon: "package", cls: "pack", id: "pack",
    info: pick(explain("capability_pack") + " It is valid only while every acceptance check is proven and passing.",
      "One manifest per release that names everything delivered by its hash: pack version equals behaviour version. "
      + "It is valid only while every criterion is verified or held out and passing.") },
  h("div", { class: "pack-top" }, acc.valid ? chip("good", "check-circle", "Valid") : chip("warning", "alert", "Not valid"),
    h("span", null, "release " + pack.release + " · " + pack.maturity + " · " + String(pack.deliverable || "product").replace("_", " ")
      + " · " + pick("AI independence ", "autonomy ") + pack.autonomy_cap),
    technical() ? h("span", { class: "mono muted small", tip: pack.content_sha256 }, "content " + short(pack.content_sha256)) : null),
  !acc.valid && (acc.not_valid_because || []).length ? h("p", { class: "small" }, "Not valid because: ",
    sepList(acc.not_valid_because.slice(0, 8).map((x) => h("span", null, h("span", { class: "mono" }, x.criterion), " " + x.state.replace("_", " "))))) : null,
  // A business reader gets the answer above; the fingerprints, the parts list and the signature are folded for them.
  technical() ? [pins, runtimeSection(pack, pid), prov]
    : h("details", { class: "pack-tech" }, h("summary", null, "Fingerprints, parts list and how it runs (for technical readers)"), pins, runtimeSection(pack, pid), prov),
  pk.current === false ? h("p", { class: "note warning" }, icon("alert"), h("span", null, "This pack is for release " + pack.release
    + "; release " + pk.latest_release + " has none yet.")) : null,
  h("details", { class: "yaml" }, h("summary", null, icon("code"), "YAML view"), h("pre", { class: "code" }, pk.yaml)),
  buildPackButton(pid, pk));
}
VIEW_FN.releases = function viewReleases(p, inbox, ctx) {
  const out = h("div", null, viewHead("Releases", pick("What was delivered where, through which steps, and did the hidden tests and the trial with a few users hold?",
    "What was delivered where, through which steps, and did the holdouts, shadow and canary hold?")));
  if (p.meta.id !== FACTORY_PID) out.append(deployCard(p.meta.id));   // where each environment deploys (roads.js)
  if (!p.releases.length) {
    out.append(emptyState("releases", null, { icon: "package", how: emptyHow("releases") + (p.meta.maturity === "explore"
      ? pick(" With the ambition explore, the result stays a preview on this computer.", " At explore maturity the result stays a local preview.") : "") }));
    return out;
  }
  const pc = packCard(ctx.pack, p.meta.id);
  if (pc) out.append(pc);
  p.releases.slice().reverse().forEach((r) => {
    const d = r.data && typeof r.data === "object" ? r.data : {};
    const steps = Array.isArray(d.steps) ? d.steps : [];
    const ho = d.holdouts && typeof d.holdouts === "object" ? d.holdouts : null;
    const extra = Object.keys(d).filter((k) => !["steps", "holdouts", "state", "env", "environment", "revision", "created", "at", "release", "number", "project", "maturity"].includes(k));
    out.append(h("article", { class: "card release", "data-id": r.name, "aria-labelledby": "rl-" + r.name },
      h("header", { class: "card-head" }, h("span", { class: "card-ic" }, icon("package")), h("h3", { class: "card-t", id: "rl-" + r.name }, "Release " + r.name),
        d.env || d.environment ? chip("neutral", "server", String(d.env || d.environment)) : null, d.state ? outcomeChip(d.state) : null),
      r.data === null ? h("p", { class: "muted" }, "This release file could not be read.") : null,
      h("dl", { class: "kv" }, d.revision ? h("div", null, h("dt", null, pick("Version of the code", "Revision")), h("dd", { class: "mono" }, short(d.revision))) : null,
        d.maturity ? h("div", null, h("dt", null, tw("maturity", 1, { cap: true })), h("dd", null, d.maturity)) : null,
        d.created || d.at ? h("div", null, h("dt", null, "Created"), h("dd", null, hhmm(d.created || d.at))) : null),
      steps.length ? h("ol", { class: "rel-steps" }, steps.map((st) => h("li", { class: "rel-step " + (st.outcome || "") },
        h("span", { class: "rs-ic" }, icon((OUTCOME[st.outcome] || ["", "info"])[1])),
        h("div", { class: "rs-b" }, h("div", { class: "rs-h" }, h("b", null, String(st.step || "?")), outcomeChip(st.outcome),
          st.at ? h("span", { class: "muted small" }, hhmm(st.at)) : null),
        st.native && typeof st.native === "object" ? h("details", null, h("summary", null, "What it recorded"),
          h("pre", { class: "code" }, JSON.stringify(st.native, null, 2))) : null)))) : h("p", { class: "muted" }, "No steps recorded."),
      ho ? h("div", { class: "rel-ho" }, h("div", { class: "rs-h" }, icon("shield"), h("b", null, tw("holdout", 2, { cap: true })),
        ho.verdict ? outcomeChip(ho.verdict) : null, h("span", { class: "muted small" }, (ho.passed !== undefined ? ho.passed + " of " + ho.scenarios
          + pick(" hidden tests passed", " scenarios passed") : "")
          + (ho.environment ? " against " + ho.environment : "") + pick(". The AI builders never see these tests.", ". Scenarios stay in their own custody."))),
      Array.isArray(ho.results) && ho.results.length ? dataTable([{ label: tw("criterion", 1, { cap: true }), value: (x) => h("span", { class: "mono" }, x.criterion) },
        { label: "Kind", key: "kind" }, { label: "Steps", key: "steps", num: true }, { label: pick("Result", "Verdict"), value: (x) => outcomeChip(x.verdict) }], ho.results,
      pick("Hidden test results", "Holdout results")) : null) : null,
      extra.length ? h("details", { class: "raw" }, h("summary", null, "The rest of the release record (" + extra.join(", ") + ")"),
        h("pre", { class: "code" }, JSON.stringify(Object.fromEntries(extra.map((k) => [k, d[k]])), null, 2))) : null));
  });
  return out;
};

// Export on the Evidence view: the same signed write as the Evidence packs widget's button, after which
// the view is drawn again, so "What the pack holds" counts this export and its ledger records. A persona
// that may not export is told who may in words beside the button, which stays focusable (aria-disabled)
// and is described by them, rather than only in a hover tooltip.
function evidenceExport(pid) {
  const who = (S.meta && S.meta.evidence_exporters) || [];
  const may = mayAct(who);
  const noteId = "ev-export-who";
  const b = button(pick("Download the proof package", "Export evidence pack"), { icon: "download", kind: "small", "data-control": "export_evidence", key: "export-evidence" });
  const note = may ? null : h("span", { class: "muted small", id: noteId }, pick("A " + orList(who) + " downloads the proof package.", "A " + orList(who) + " persona exports evidence."));
  if (!may) {
    b.setAttribute("aria-disabled", "true");
    b.setAttribute("aria-describedby", noteId);
  }
  b.addEventListener("click", () => {
    if (!may) { say(note.textContent, "warning"); return; }
    if (!needPerson()) return;
    run(b, b.parentNode, async () => {
      const out = await api("POST", "/api/projects/" + enc(pid) + "/evidence", signed());
      const name = await download(out.download, out.file);
      say("Evidence pack " + name + " exported and downloaded, signed by " + S.person.trim() + ". The link worked once.", "good");
      await settle(['[data-key="export-evidence"]']);
    });
  });
  return h("div", { class: "btns" }, b, note);
}

// Assessment: an adopted system judged from every perspective (cockpit/static/assessment.js).
VIEW_FN.assessment = (p, inbox, ctx) => viewAssessment(p, ctx, { viewHead, run, settle });
// Alignment: a repository's own specs, tests and tasks mapped onto the project (cockpit/static/alignment.js).
VIEW_FN.align = (p, inbox, ctx) => viewAlign(p, ctx, { viewHead, run, settle });

// Evidence: the attestation (never "compliant"), the control table, and the export.
VIEW_FN.evidence = function viewEvidence(p, inbox, ctx) {
  const pid = p.meta.id;
  const a = ctx.attestation;
  const head = viewHead("Evidence", pick("Can we show what was built, which versions, who approved it, and that it was checked?",
    "Can we show what ran, which versions, who approved, and that it was checked?"));
  if (!a) return h("div", null, head, emptyState("evidence", null, { what: pick("The proof could not be read.", "The attestation could not be read."), icon: "file-check" }));
  const st = ATTEST[a.verdict] || { tone: "nm", icon: "dashed", word: a.verdict };
  const STATUS = { evidenced: ["good", "check-circle", pick("Proven", "Evidenced")], partial: ["warning", "alert", "Partial"],
    no: ["nm", "dashed", pick("No proof", "Not evidenced")] };
  const gets = technical()
    ? [["file-check", "MANIFEST.json: every file with its sha256"], ["layers", "The full ledger, with its hash chain checked at export"],
      ["shield", "Holdout scores only: the scenarios stay in their custody"], ["user", "Every decision with its named person and persona"]]
    : [["file-check", "A list of every file with its fingerprint, so any change shows"], ["layers", "The whole decision record, checked to be unchanged"],
      ["shield", "The hidden tests' scores, without the tests themselves"], ["user", "Every decision with the person who made it and their role"]];
  return h("div", null,
    head,
    h("div", { class: "ev-grid" },
      card({ title: pick("What the proof shows", "Attestation"), icon: "shield", cls: "attest", info: pick("The proof package is for a reviewer or "
        + "auditor to judge. It says whether the records hold up; it never claims the project meets a standard.",
      "The evidence pack is evidence for a reviewer to judge. "
        + "It says attestable, chain broken or insufficient evidence; it never claims conformity with a framework.") },
      h("div", { class: "att-v" }, chip(st.tone, st.icon, st.word)), h("p", { "data-ud": "" }, cap(a.meaning) + "."),
      h("p", { class: "muted small" }, pick("This does not say the project meets a standard: a reviewer judges that.", "This is not a statement of conformity.")),
      h("ul", { class: "plain att-gets" }, gets.map(([ic, t]) => h("li", null, icon(ic), t))),
      evidenceExport(pid)),
      card({ title: pick("What the proof package holds", "What the pack holds"), icon: "layers" },
        h("dl", { class: "kv" },
          h("div", null, h("dt", null, tw("ledger", 1, { cap: true })), h("dd", null, a.ledger && a.ledger.intact
            ? chip("good", "check-circle", "intact · " + plural(a.ledger.records, pick("entry", "record"), pick("entries", "records")))
            : chip("critical", "x-circle", pick("damaged", "broken")))),
          h("div", null, h("dt", null, "Decisions by people"), h("dd", { "data-att": "decisions" }, String(a.decisions + (a.answers || 0)),
            a.answers ? h("span", { class: "muted" }, " · " + plural(a.answers, "signed answer") + " from people in the loop") : null)),
          h("div", null, h("dt", null, pick("Quality check results", "Gate verdicts")), h("dd", null, String(a.gates))),
          h("div", null, h("dt", null, pick("AI build attempts", "Gnomon runs")), h("dd", null, String(a.runs))),
          h("div", null, h("dt", null, tw("criterion", 2, { cap: true })), h("dd", null, String(a.criteria), a.not_measured && a.not_measured.length
            ? h("span", { class: "muted" }, " · " + a.not_measured.length + " not measured") : null)),
          h("div", null, h("dt", null, tw("capability_pack", 1, { cap: true })), h("dd", null, a.pack ? (a.pack.version ? "v" + a.pack.version : "not built yet")
            + (a.pack.valid ? " · valid" : " · not valid") : h("span", { class: "nm-text" }, "no release yet"))),
          h("div", null, h("dt", null, "Exported before"), h("dd", null, plural(a.exports || 0, "time")))))),
    card({ title: pick("What it can prove, by topic", "Controls"), icon: "file-check", cls: "controls",
      info: pick("What the package can prove, by area an auditor looks at: proven, partly or not. A reviewer judges whether that is enough.",
        "What the bundle can evidence, by control family: evidenced, partial or no. A reviewer judges conformity.") },
    dataTable([{ label: pick("Area", "Control"), value: (c) => h("span", { class: "mono nowrap" }, c.control) }, { label: "Topic", key: "topic" },
      { label: pick("Proof", "Evidence"), value: (c) => { const s = STATUS[c.status] || ["nm", "dashed", c.status]; return chip(s[0], s[1], s[2]); } },
      { label: "Where", value: (c) => h("span", { "data-ud": "", class: "small" }, c.by || "") }], a.controls || [], "Controls the evidence pack covers")));
};

VIEW_FN.track = viewTrack;      // staying on track, the autopilot and delegations (track.js)
VIEW_FN.insights = (p, inbox, ctx) => insightsView(ctx.pid);    // the project's insights (insights.js)
VIEW_FN.agents = (p) => viewAgents(p);   // the agent channel (agents.js, FR-CHN1)
VIEW_FN.context = (p) => viewContext(p);   // the data and context layer (context.js, FR-CTX1)
VIEW_FN.graph = (p, inbox, ctx) => graphView(ctx.pid);   // the Knowledge graph (graph.js, FR-GRV1)
VIEW_FN.incidents = (p) => viewIncidents(p);   // what went wrong here and what Rihmasto learned (heal.js, FR-HEAL1)
// -- outputs: what each audience receives (cockpit/static/outputs.js, kernel/outputs.py) -----------------
VIEW_FN.outputs = (p, inbox, ctx) => viewOutputs(p, ctx, { viewHead, run, settle });
// -- automations: what runs on its own for the project (cockpit/static/automations.js, kernel/automations.py)
VIEW_FN.automations = (p) => viewAutomations(p);
// -- the console and Health: commands in the workspace, and the project's checks (console.js, health.js)
VIEW_FN.console = (p) => viewConsole(p);
VIEW_FN.checks = (p) => viewChecks(p);
VIEW_FN.review = viewReview;    // since you last looked, for this project (review.js)
// The AI tools the team uses in this repository, and working on it from an IDE (aitools.js), in the Agents capsule.
VIEW_FN.aitools = (p) => h("div", null, viewHead("AI tools", technical()
  ? "How the repository's AI coding tools are set up, and the MCP configuration to work on it from your IDE."
  : "Which AI assistants the team uses on this project, and how to connect yours."),
aiTools(p) || emptyState("aitools", null, { icon: "sparkles", what: pick("This project is built by Rihmasto itself, so it has no AI tools of its own.",
  "This project is built by Rihmasto itself: no repository AI tool configuration to show."),
how: pick("Bring in existing code (Projects, New project, adopt or attach) to see how that team's AI tools are set up here.",
  "Adopt or attach a repository (Projects, New project) to see its CLAUDE.md, AGENTS.md, rules, skills, hooks and MCP servers here.") }));
VIEW_FN.destinations = (p) => viewDestinations(p);   // where the capability goes (destinations.js, FR-DST1)
// -- agent sessions: what the IDE agents did, from the team's own hub (cockpit/static/agentobs.js, FR-OBS1)
VIEW_FN.agent_sessions = (p) => viewAgentSessions(p);

// -- comments: a remark on a requirement, criterion, task, release or card decides nothing ----------

const COMMENT_TARGET = { spec: ["requirement", ".card.req[data-id]"], plan: ["requirement", ".plan-req[data-id]"],
  tasks: ["task", ".tcard[data-id]"], releases: ["release", ".card.release[data-id]"], inbox: ["card", ".card.decision[data-id]"],
  changes: ["card", ".card[data-id]"] };
function decorateComments(root, pid, view, all) {
  const t = COMMENT_TARGET[view];
  if (!t) return;
  if (view === "spec") {
    $$("table.crit tr[data-id]", root).forEach((row) => {
      const id = row.getAttribute("data-id");
      const mine = all.filter((c) => c.target.kind === "criterion" && c.target.id === id);
      // its data-key brings the focus back to it when the thread closes and the view re-renders
      const b = h("button", { type: "button", class: "icon-btn tiny crit-cm" + (mine.length ? " has" : ""), "data-control": "comment",
        "data-key": "cmc:" + id,
        "aria-label": "Comment on " + id + (mine.length ? " (" + mine.length + ")" : ""), tip: mine.length ? plural(mine.length, "comment") : "Comment on " + id },
      icon("comment"));
      b.addEventListener("click", () => openThread(pid, { kind: "criterion", id }, mine));
      row.firstElementChild.append(b);
    });
  }
  $$(t[1], root).forEach((el) => {
    const id = el.getAttribute("data-id");
    const mine = all.filter((c) => c.target.kind === t[0] && c.target.id === id);
    if (view === "inbox") {   // on a decision, commenting is its own, secondary row at the foot (decide.js)
      const row = commentRow(() => openThread(pid, { kind: t[0], id }, mine), mine.length);
      $("button", row).setAttribute("data-key", "cm:" + id);
      el.insertBefore(row, el.querySelector(".card-details"));
      return;
    }
    const b = h("button", { type: "button", class: "btn tiny quiet comment-btn", "data-control": "comment", "data-key": "cm:" + id },
      icon("comment"), h("span", null, mine.length ? plural(mine.length, "comment") : "Comment"));
    b.addEventListener("click", () => openThread(pid, { kind: t[0], id }, mine));
    const head = el.querySelector(".hd, .tc-h, .card-head") || el;
    head.append(b);
  });
}

export function openThread(pid, target, existing) {
  const list = h("ul", { class: "thread" });
  const draw = (items) => fill(list, items.length ? items.map((c) => h("li", { class: "cm" }, avatar(c.person),
    h("div", { class: "cm-b" }, h("div", { class: "cm-h" }, h("b", null, c.person), h("span", { class: "muted small" }, personaLabel(c.persona) + " · " + ago(c.at))),
      h("p", null, c.text),
      c.promoted_to ? chip("info", "refresh", "Promoted to change " + c.promoted_to)
        : (mayAct(S.meta.comment_promoters || []) ? promoteButton(pid, c) : null))))
    : h("li", { class: "muted small" }, "No comments yet."));
  draw(existing || []);
  const text = h("textarea", { rows: "3", maxlength: "4000", "aria-label": "Your comment", placeholder: "Write a comment" });
  const send = h("button", { type: "submit", class: "btn primary", "data-control": "comment" }, icon("send"), "Comment");
  const form = h("form", { class: "cm-form", novalidate: true }, text,
    h("p", { class: "muted small" }, icon("info"), " A comment decides nothing. A product owner or business owner may promote it into a change."),
    h("div", { class: "btns" }, send));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!text.value.trim()) { text.focus(); return; }
    if (!needPerson()) return;
    run(send, form, async () => {
      await api("POST", "/api/projects/" + enc(pid) + "/comments", Object.assign({ target, text: text.value.trim() }, signed()));
      text.value = "";
      const out = await api("GET", "/api/projects/" + enc(pid) + "/comments?kind=" + enc(target.kind) + "&id=" + enc(target.id));
      draw(out.comments);
      say("Your comment is signed and kept. It decides nothing.", "good");
      text.focus();   // the thread stays open, ready for the next comment
    });
  });
  openModal("Comments on " + target.kind + " " + target.id, h("div", { class: "cm-thread" }, list, form),
    { icon: "comment", onClose: () => nav.rerender && nav.rerender() });
}
function promoteButton(pid, c) {
  const b = button("Promote to change", { icon: "refresh", kind: "tiny" });
  b.addEventListener("click", () => {
    if (!needPerson()) return;
    run(b, b.parentNode, async () => {
      const out = await api("POST", "/api/projects/" + enc(pid) + "/comments/" + enc(c.id) + "/promote", signed());
      closeModal();
      say(c.id + " is now change " + out.card.id + pick(", sorted as a ", ", triaged as a ") + (CLASS_LABEL[out.triage.class] || out.triage.class) + ".", "good");
    });
  });
  return b;
}

export function impactPanelFor(pid, c, collapsed) { return impactPanel(pid, c, collapsed); }
export { renderProjects, renderFloor, renderJobs, newProjectForm, stopLive, startLive, LIVE, jobsSection, decideForm, questionBody, tryPanel, healthCard, nowLine, evidenceCounts };
