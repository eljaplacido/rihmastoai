/* The development board of a project (FR-DEV1, kernel/devboard.py, kernel/devbrief.py): the developer briefing on
   top (the latest sessions in any harness since the person's last look, what changed, the next development step
   with why, and only the decisions that block it), then the work as lanes: Planned, In progress, In review,
   Blocked, Done. Each card links to its requirements, criteria and tests, its commits, its gate rounds and the
   agents and harnesses that worked on it. Everything is read from the records; "Got it" records the person's look
   so the next briefing counts from there. Ask Rihma answers "what's next in development?" the same way, by rule. */

import { S, h, fill, icon, chip, api, enc, button, say, plural, signed, needPerson, act, mayAct } from "./core.js";
import { pick, technical, emptyState, datum, localDateTime, plurals, cardTitle } from "./words.js";
const ud = (text) => datum(plurals(text));    // a record's own words, its "(s)" plurals said properly
import { openAssistant, send as askRihma } from "./assistant.js";

export const LANE_WORDS = {
  planned: ["Planned", "Planned"], in_progress: ["Being built", "In progress"], review: ["Being checked", "In review"],
  blocked: ["Waiting on a person", "Blocked"], done: ["Done", "Done (on main)"],
};
const LANE_TONE = { planned: "neutral", in_progress: "accent", review: "warning", blocked: "critical", done: "good" };
const HARNESS = { "claude-code": "Claude Code", cursor: "Cursor", codex: "Codex", opencode: "OpenCode", gnomon: "Gnomon",
  workspace: ["A person's own work", "Workspace"], mcp: ["An AI tool connected to Rihmasto", "MCP"], other: "Other tool" };
export const harnessWord = (id) => { const w = HARNESS[id]; return Array.isArray(w) ? (technical() ? w[1] : w[0]) : w || (id ? String(id) : "unknown"); };
export const laneWord = (k) => (technical() ? LANE_WORDS[k][1] : LANE_WORDS[k][0]);

// "Ask Rihma" with the question already asked: the same answer as the chat gives, by rule.
export function askButton(question, label, key) {
  return button(label || "Ask Rihma", { icon: "sparkles", kind: "small quiet", key, control: "assistant",
    onclick: () => { openAssistant(); askRihma(question); } });
}

export function agentChips(agents) {
  return (agents || []).map((a) => chip("neutral", a.via === "workspace" ? "user" : "bot",
    harnessWord(a.harness) + (a.name && a.name !== harnessWord(a.harness) ? " · " + a.name : ""), { "data-ud": "" }));
}

// -- the briefing ----------------------------------------------------------------------------------------

function sessionsList(b) {
  if (!b.sessions.length) {
    return emptyState("dev_sessions", askButton("Why are there no agent sessions on this project, and how do I capture them?", "Ask Rihma why", "dev:ask-sessions"),
      { icon: "bot", what: "No agent session since " + b.since_basis + ".",
        how: pick("Work done by AI helpers inside Rihmasto or in tools like Claude Code shows here once it happens; the Trace view has the hooks that capture outside tools.",
          "Builder cells, workspaces and outside sessions appear here; install the session hooks from the Trace view to capture Claude Code and Cursor.") });
  }
  const by = Object.entries(b.by_harness).map(([k, n]) => chip("neutral", "bot", harnessWord(k) + " " + n));
  return h("div", null, h("div", { class: "chips dv-by" }, by),
    h("ul", { class: "plain dv-sess" }, b.sessions.map((s) => h("li", null,
      h("span", { class: "dv-at" }, localDateTime(s.at)), " ", chip("neutral", "bot", harnessWord(s.harness || s.who)), " ",
      ud(s.what), s.task ? h("span", { class: "muted" }, " · " + s.task) : null))));
}

function changedLine(c) {
  const parts = [];
  if (c.gates.passed || c.gates.failed) parts.push(chip(c.gates.failed ? "warning" : "good", "check-circle",
    pick(plural(c.gates.passed, "check") + " passed, " + c.gates.failed + " failed", plural(c.gates.passed, "gate round") + " passed, " + c.gates.failed + " failed")));
  if (c.merged.length) parts.push(chip("good", "merge", pick("finished: ", "merged: ") + c.merged.join(", ")));
  const t = c.tests;
  if (t.measured) parts.push(chip(t.failed.length ? "critical" : "good", "flask", plural(t.ran || 0, "test") + " ran on " + t.task
    + (t.failed.length ? ", " + t.failed.length + " failed" : ", all passed")));
  if (c.criteria_changed) parts.push(chip("info", "file-check", pick("the requirements changed", "contract recompiled")));
  if (c.decisions) parts.push(chip("neutral", "check", plural(c.decisions, "decision")));
  return parts.length ? h("div", { class: "chips" }, parts) : h("p", { class: "muted small" }, "Nothing changed in the records since then.");
}

function nextBlock(b) {
  const n = b.next;
  const go = h("a", { class: "btn primary", href: n.action.route, "data-key": "dev:next", "data-control": n.action.control || "dev_briefing" },
    icon("arrow-right"), h("span", { class: "lbl" }, n.action.label));
  return h("div", { class: "dv-next", "data-id": "dev_next" },
    h("p", { class: "dv-next-l" }, pick("Next step", "Next development step")),
    h("p", { class: "dv-next-t", "data-ud": "" }, plurals(n.title)),
    h("p", { class: "dv-next-w" }, h("b", null, "Why: "), ud(n.why)),
    h("div", { class: "btns" }, go, askButton("What's next in development?", "Ask Rihma", "dev:ask-next")));
}

function blockingList(b) {
  if (!b.blocking.length) return h("p", { class: "small" }, chip("good", "check-circle", "Nothing waits on a decision for this step"));
  return h("div", null, h("p", { class: "small" }, pick("Only these decisions hold this step up:", "Only these decisions block this step:")),
    h("ul", { class: "plain dv-block" }, b.blocking.map((x) => h("li", null,
      h("a", { href: x.route, "data-key": "dev:block:" + x.card }, x.card), " ", ud(cardTitle(x.what).text),
      h("span", { class: "muted small" }, " · for " + x.for)))));
}

export function briefingCard(pid, b, again) {
  const seen = button("Got it", { icon: "check", kind: "small", key: "dev:seen", "data-control": "dev_seen",
    tip: "The next briefing counts from now",
    onclick: () => act(seen.parentNode, async () => {
      if (!needPerson()) return;
      await api("POST", "/api/projects/" + enc(pid) + "/dev/seen", signed());
      say("Noted: the next briefing counts from now.", "good");
      again();
    }) });
  return h("section", { class: "card dv-brief", "aria-labelledby": "dv-brief-h", "data-id": "dev_briefing", "data-control": "dev_briefing" },
    h("header", { class: "card-head" }, h("span", { class: "card-ic" }, icon("bell")),
      h("h3", { class: "card-t", id: "dv-brief-h" }, pick("Your briefing", "Developer briefing")),
      h("span", { class: "card-tools" }, h("span", { class: "muted small" }, "since " + b.since_basis), seen)),
    nextBlock(b), blockingList(b),
    h("h4", { class: "dv-sub" }, pick("Latest work by AI helpers", "Latest sessions in any harness")), sessionsList(b),
    h("h4", { class: "dv-sub" }, "What changed"), changedLine(b.changed));
}

// -- the board -------------------------------------------------------------------------------------------

function detailsOf(c) {
  const crit = (c.criteria || []).map((x) => h("li", null, h("b", { class: "mono" }, x.id), " ",
    x.then ? ud("Given " + (x.given || "…") + ", when " + (x.when || "…") + ", then " + x.then) : null));
  const tests = (c.tests || []).map((t) => h("li", null, chip(t.result === "ok" ? "good" : "critical", t.result === "ok" ? "check" : "x", t.result), " ", h("code", null, t.name)));
  const commits = (c.commits || []).map((x) => h("li", null, h("code", null, x.short), " ", ud(x.subject),
    h("span", { class: "muted small" }, " · " + localDateTime(x.at) + (x.on_main ? "" : pick(" · not finished yet", " · not on main")))));
  const gates = (c.gates || []).map((g) => h("li", null, chip(g.verdict === "passed" ? "good" : "warning", "gate",
    pick("check " + g.round + ": " + g.verdict, "round " + g.round + ": " + g.verdict)), g.objections ? " " + plural(g.objections, "objection") : "",
    h("span", { class: "muted small" }, " · " + localDateTime(g.at))));
  const part = (title, list) => (list.length ? [h("p", { class: "dv-dh" }, title), h("ul", { class: "plain dv-dl" }, list)] : []);
  return h("details", { class: "tc-d" }, h("summary", null, "Details"),
    part(pick("What it must do", "Criteria"), crit), part("Tests", tests),
    part(pick("Changes to the code", "Commits") + (c.commits_total > (c.commits || []).length ? " (newest " + c.commits.length + " of " + c.commits_total + ")" : ""), commits),
    part(pick("Quality checks", "Gate rounds"), gates),
    c.depends_on && c.depends_on.length ? h("p", { class: "small muted" }, "After " + c.depends_on.join(", ")) : null);
}

function cardEl(c) {
  const facts = [];
  (c.requirements || []).forEach((r) => facts.push(chip("info", "file-check", r)));
  if (c.rounds) facts.push(chip("neutral", "gate", pick(plural(c.rounds, "check"), plural(c.rounds, "round"))));
  if (c.commits_total) facts.push(chip("neutral", "code", pick(plural(c.commits_total, "change"), plural(c.commits_total, "commit"))));
  return h("article", { class: "tcard dv-card dv-" + c.lane, "data-card": c.id, "data-kind": c.kind },
    h("div", { class: "tc-h" }, h("span", { class: "mono" }, c.id), c.kind !== "task" ? chip("neutral", "info", c.kind.replace(/_/g, " ")) : null),
    h("p", { class: "tc-t", "data-ud": "" }, c.kind === "task" ? plurals(c.title) : cardTitle(c.title).text),
    h("p", { class: "tc-f", "data-ud": "" }, plurals(c.why)),
    c.waits_on ? h("p", { class: "tc-f" }, icon("user"), " ", h("a", { href: "#/p/" + enc(S.route.pid) + "/inbox/" + enc(c.waits_on.card) }, "Decide " + c.waits_on.card)) : null,
    facts.length || (c.agents || []).length ? h("div", { class: "chips" }, facts, agentChips(c.agents)) : null,
    c.kind === "task" ? detailsOf(c) : null,
    c.open ? h("a", { class: "tc-go small", href: c.open, "data-key": "dev:open:" + c.id }, "Open " + c.id) : null);
}

const FILTERS = { lane: "", harness: "", requirement: "", mine: false, text: "" };

function keep(c) {
  const f = FILTERS;
  const mine = !f.mine || (c.waits_on && mayAct(c.waits_on.who));
  const hay = (c.id + " " + c.title + " " + (c.why || "")).toLowerCase();
  return (!f.lane || c.lane === f.lane) && mine && (!f.text || hay.includes(f.text.toLowerCase()))
    && (!f.harness || (c.agents || []).some((a) => String(a.harness || a.name) === f.harness))
    && (!f.requirement || (c.requirements || []).includes(f.requirement));
}

function select(name, label, values, word) {
  const s = h("select", { "aria-label": label, "data-key": "dev:f:" + name },
    h("option", { value: "" }, label + ": all"), values.map((v) => h("option", { value: v, selected: FILTERS[name] === v || null }, word ? word(v) : v)));
  return s;
}

function filterBar(b, redraw) {
  const f = b.filters;
  const lane = select("lane", pick("Where", "Lane"), f.lanes, laneWord);
  const har = select("harness", pick("Who worked", "Harness"), f.harnesses, harnessWord);
  const req = select("requirement", "Requirement", f.requirements);
  const text = h("input", { type: "search", placeholder: "Find a task", "aria-label": "Find a task", value: FILTERS.text, "data-key": "dev:f:text" });
  const mine = h("input", { type: "checkbox", id: "dv-mine", checked: FILTERS.mine || null, "data-key": "dev:f:mine" });
  [[lane, "lane"], [har, "harness"], [req, "requirement"]].forEach(([el, k]) => el.addEventListener("change", () => { FILTERS[k] = el.value; redraw(); }));
  text.addEventListener("input", () => { FILTERS.text = text.value; redraw(); });
  mine.addEventListener("change", () => { FILTERS.mine = mine.checked; redraw(); });
  return h("div", { class: "dv-filters", "data-control": "dev_filters", role: "group", "aria-label": "Filter the board" },
    lane, har, req, text, h("label", { class: "dv-mine", for: "dv-mine" }, mine, " Waiting on me"));
}

function lanes(b) {
  const cards = b.cards.filter(keep);
  return h("div", { class: "board dv-board", "data-id": "dev_lanes" }, b.lanes.map((k) => {
    const mine = cards.filter((c) => c.lane === k);
    return h("section", { class: "lane dv-lane " + k, "aria-labelledby": "dvl-" + k, "data-lane": k },
      h("h3", { class: "lane-h", id: "dvl-" + k }, chip(LANE_TONE[k], "dashed", laneWord(k)),
        h("span", { class: "lane-n" }, h("span", { class: "vh" }, ": "), String(mine.length))),
      mine.length ? h("ul", { class: "lane-l" }, mine.map((c) => h("li", null, cardEl(c)))) : h("p", { class: "lane-e" }, "none"));
  }));
}

function noTasks(b) {
  return emptyState("dev_board", askButton("Why does this project have no development tasks yet, and how do I get them?", "Ask Rihma why", "dev:ask-empty"),
    { icon: "pipeline", what: pick("No building work is planned yet.", "No contract tasks yet."),
      how: ud(b.no_tasks.why + ": " + b.no_tasks.how + ".") });
}

async function draw(box, pid) {
  const person = S.person.trim();
  const [b, brief] = await Promise.all([api("GET", "/api/projects/" + enc(pid) + "/dev/board"),
    api("GET", "/api/projects/" + enc(pid) + "/dev/briefing" + (person ? "?person=" + enc(person) : ""))]);
  if (!box.isConnected) return;
  const again = () => draw(box, pid).catch((e) => say(e.message, "critical"));
  const holder = h("div", { class: "dv-lanes-holder" });
  const redraw = () => fill(holder, lanes(b));
  redraw();
  const commits = b.commits.measured ? null : h("p", { class: "note small" }, icon("info"), " ",
    pick("Changes to the code are not shown: ", "Commits not measured: "), ud(b.commits.why + "; " + b.commits.how + "."));
  fill(box, head(), briefingCard(pid, brief, again),
    b.no_tasks ? noTasks(b) : null,
    b.cards.length ? [filterBar(b, redraw), commits, holder] : null);
  box.removeAttribute("aria-busy");
}

function head() {
  return h("div", { class: "q" }, h("h2", { class: "view-h", id: "view-title", tabindex: "-1" }, pick("Building board", "Development board")),
    h("p", null, pick("Where each piece of the building work is, who worked on it, and what to do next.",
      "Each task by lane, with its criteria, tests, commits, gate rounds and the agents that worked on it, and the next step.")));
}

export function render(p) {
  const pid = p.meta.id;
  const box = h("div", { class: "dv-view", "aria-busy": "true" }, head(), h("p", { class: "muted" }, "Reading the records…"));
  draw(box, pid).catch((e) => { box.removeAttribute("aria-busy"); if (box.isConnected) fill(box, head(), emptyState("dev_board", askButton("Why can the development board not be read?", "Ask Rihma why", "dev:ask-error"), { icon: "alert", what: "The board could not be read: " + e.message, how: "Try again in a moment; if it stays, Ask Rihma what is wrong." })); });
  return box;
}
