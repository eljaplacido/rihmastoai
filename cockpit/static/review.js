/* The Review page, each project's Review tab and Home's first card (FR-REV1): "You're not supposed to watch
   Claude Code work. You're supposed to wake up and review what it shipped."

   Since you last looked, grouped by what needs you: waiting on you, went wrong, decided for you, shipped, from
   your IDE, and the period's cost. Every row links to its record and says who or what did it. Act in place:
   approve or decline a card, settle or overturn an assumption, stop a delegation, report a change, mark what
   you looked at as reviewed, then Mark all reviewed. Every write is signed with the person and persona in the
   person chip and goes through a route the kernel already checks. Keyboard first: j and k move, a approves,
   d declines, r marks reviewed, o opens the record, Enter opens the preview, Esc closes it. */

import {
  S, $, $$, h, fill, icon, chip, api, act, say, signed, needPerson, nav, enc, fmtAt, fmtAge, plural, personaLabel,
  pageHead, button, segmented, openModal, closeModal, store,
} from "./core.js";
import { technical, kernelWord, kindWord, tw, pick, dayWord, cardTitle, titleOf, localDateTime } from "./words.js";
import { VERDICT_LABEL } from "./core.js";

// The kernel's headline in the reader's words: what was "decided for you" are assumptions to confirm or overturn.
const cap1 = (s) => (s ? String(s).charAt(0).toUpperCase() + String(s).slice(1) : s);
function headlineSaid(text) { return String(text || "").replace(/(\d+) decided for you/, "$1 assumed in your name (to confirm or overturn)"); }
// A group's name for a business reader; IDE commits are a developer's concern and hidden from them when there are none.
const GROUP_PLAIN = { ide: "Changes made by developers outside Rihmasto", decided: "Assumed in your name" };
// A row's title: an assumption says who assumed what; a card's title loses its "[embed E-001]" prefix.
function titleSaid(it) {
  const t = String(it.title || "");
  if (it.kind === "assumption" && /^Assumed: /.test(t)) return pick("Rihma assumed: “" + t.slice(9).replace(/: /, ", ") + "”", t);
  return it.kind === "card" ? cardTitle(t).text : t;
}

const GROUP_ICON = { waiting: "user", wrong: "alert", decided: "diamond", shipped: "package", ide: "code", agents: "bot" };
const GROUP_EMPTY_TECH = { waiting: "Nothing waits on you.", wrong: "Nothing went wrong.", decided: "Nothing was decided in your name.",
  shipped: "Nothing shipped.", ide: "No commit from your IDE was gated.",
  agents: "No agent posted progress, a proposal or a gate request." };
const GROUP_EMPTY_PLAIN = { ide: "No change from a developer's own tools was checked.",
  agents: "No AI agent posted progress, a proposal or a request to check its work." };
const GROUP_EMPTY = new Proxy(GROUP_EMPTY_TECH, { get: (t, k) => (technical() ? null : GROUP_EMPTY_PLAIN[k]) || t[k] });
const KIND_ICON = { card: "inbox", task_merged: "merge", release: "package", output: "send", commit_gated: "code",
  delegated_decision: "diamond", assumption: "flag", job_failed: "terminal" };
const NEEDS = { text: ["Your answer", "text"], reason: ["Why (recorded with the decision)", "reason"],
  correction: ["What is true instead (recorded, and a change card opens)", "correction"] };
const SINCE = [["", "Since you last reviewed"], ["24h", "24 h"], ["7d", "7 days"]];
const GATED = ["task_merged", "commit_gated", "gate", "security_gate", "holdouts_run"];
const R = { data: null, pid: null, sel: 0, open: null };

function query() {
  const since = store.get("gf.review.since") || "";
  return "?person=" + enc(S.person.trim()) + "&persona=" + enc(S.persona) + (since ? "&since=" + enc(since) : "");
}
function path(pid) { return (pid ? "/api/projects/" + enc(pid) + "/review" : "/api/review") + query(); }
function items() { return (R.data ? R.data.groups : []).flatMap((g) => g.items); }

// -- who did it, and the chips of a row --------------------------------------------------------------------

function byText(by) {
  if (!by) return "";
  const persona = by.persona ? " (" + personaLabel(by.persona) + ")" : "";
  if (by.type === "person") return (by.name || "a person") + persona + (by.via ? " · " + by.via : "") + (by.agent ? " · " + by.agent : "");
  if (by.type === "agent") return [by.name, by.model, by.runner].filter(Boolean).join(" · ");
  if (by.type === "autopilot" || by.type === "delegation") {
    return [by.name, by.type === "autopilot" ? by.delegation : null, by.rule].filter(Boolean).join(" · ")
      + (by.person ? " · in " + by.person + "'s name" + persona : "");
  }
  if (by.type === "automation") return "automation " + by.name + persona;
  if (by.name === "the gate" && !technical()) return "the quality check";
  if (by.name === "the panel") return pick("Rihma's question panel (AI)", "the intake panel (analyst)");
  return by.name && by.name !== "the kernel" && by.name !== "kernel" ? by.name : kernelWord();
}
function byBadge(by) {
  const kind = by && by.type === "person" ? "person" : by && by.type === "kernel" ? "kernel" : "agent";
  const glyph = kind === "person" ? h("span", { class: "avatar person", "aria-hidden": "true" },
    String((by && by.name) || "?").split(/\s+/).map((w) => w[0] || "").join("").slice(0, 2).toUpperCase())
    : h("span", { class: "avatar " + kind, "aria-hidden": "true" }, icon(kind === "kernel" ? "diamond" : "bot"));
  // a rule is said once: "rule: the quality check", never "kernel: the kernel"
  return h("span", { class: "who rv-who" }, glyph, h("span", { class: "vh" }, (kind === "kernel" ? "rule" : by && by.type) + ": "), h("span", { class: "who-n" }, byText(by)));
}
function diffChip(d) {
  if (!d) return null;
  if (!d.measured) return chip("nm", "dashed", "diff not measured", { tip: d.why || "not measured" });
  return h("span", { class: "chip info rv-diff-chip", tip: d.files + " files changed" },
    icon("code"), h("span", null, plural(d.files, "file")), h("span", { class: "rv-add" }, "+" + d.added), h("span", { class: "rv-del" }, "−" + d.deleted));
}
function chips(it) {
  const out = [];
  if (it.project_title) out.push(h("span", { class: "chip profile rv-proj" }, h("span", null, titleOf(it.project, it.project_title))));
  const from = it.kind === "card" ? cardTitle(it.title).from : null;
  if (from) out.push(chip("neutral", null, from));
  if (it.kind === "card") {
    out.push(chip("neutral", null, kindWord(it.card_kind) || cap1(it.label || it.card_kind)));
    out.push(chip(it.age_hours > 24 ? "warning" : "neutral", "clock", "waiting " + fmtAge(it.age_hours)));
    if (it.new) out.push(chip("accent", null, "new"));
  }
  if (it.verdict && GATED.includes(it.kind)) {
    out.push(chip(it.verdict === "passed" ? "good" : "critical", it.verdict === "passed" ? "check" : "x-circle", tw("gate") + " " + it.verdict));
  }
  if (it.decided) out.push(chip("accent", "diamond", "decided: " + it.decided, { tip: "Decided by a delegation in your name" }));
  if (typeof it.rounds === "number") out.push(chip("neutral", null, plural(it.rounds, tw("round"), tw("round", 2))));
  if (it.where) out.push(chip(it.environment === "production" ? "accent" : "info", "server", it.where));
  if (it.due) {
    out.push(chip(it.overdue ? "critical" : "neutral", "clock", technical() ? (it.overdue ? "overdue since " : "due ") + it.due
      : it.overdue ? "overdue since " + dayWord(it.due) : "confirm or change by " + dayWord(it.due),
    { tip: "After this date the assumption is flagged overdue until a person confirms or overturns it." }));
  }
  out.push(diffChip(it.diff));
  if (it.reviewed) out.push(chip("good", "check-circle", "reviewed by " + it.reviewed.person, { tip: fmtAt(it.reviewed.at) }));
  return out;
}

// -- acting in place: every write through its own signed route ---------------------------------------------

function textModal(title, label, prefill, submit) {
  const box = h("textarea", { id: "rv-text", rows: "4", maxlength: "4000", "data-key": "rv-text" });
  box.value = prefill || "";
  const go = h("button", { type: "submit", class: "btn human primary", "data-key": "rv-send" }, "Send, signed");
  const form = h("form", { class: "rv-form", novalidate: true },
    h("div", { class: "field" }, h("label", { for: "rv-text" }, label), box),
    h("p", { class: "muted small" }, "Signed by " + (S.person.trim() || "you") + " as " + personaLabel(S.persona) + "."),
    h("div", { class: "btns" }, go, button("Cancel", { kind: "quiet", onclick: () => closeModal() })));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!box.value.trim()) { say("Write it first: it is recorded with your name.", "warning"); return; }
    const ok = await act(form, () => submit(box.value.trim()));
    if (ok !== undefined) closeModal();
  });
  openModal(title, form, { icon: "edit" });
  box.focus();
  box.setSelectionRange(box.value.length, box.value.length);
}

async function run(it, a) {
  if (a.do === "open") { location.hash = a.href; return; }
  if (!needPerson()) return;
  const send = async (extra) => {
    const out = await api("POST", a.path, Object.assign({}, a.body || {}, extra || {}, signed()));
    say(said(it, a), "good");
    await reload();
    return out;
  };
  if (a.do === "change") {
    textModal("Report a change", "What should change? It goes to the project's change triage.", (a.prefill || "") + "",
      (text) => send({ text }));
    return;
  }
  if (a.needs) {
    const [label, field] = NEEDS[a.needs] || ["Why", "reason"];
    textModal(a.label + ": " + it.title, label, "", (text) => send({ [field]: text }));
    return;
  }
  const row = $('[data-id="' + CSS.escape(it.id) + '"]');
  await act(row, () => send());
}
function said(it, a) {
  if (a.do === "reviewed") return "Marked reviewed: " + it.title + ". The record shows you looked.";
  if (a.do === "decide") return a.label + " on " + (it.card || it.title) + ", signed.";
  if (a.do === "change") return "Reported a change about " + it.title + ".";
  if (a.do === "revoke") return "The delegation is stopped: its next card waits for a person.";
  return a.label + ": done, signed.";
}
function keyed(it, key) {
  const found = (it.actions || []).find((a) => a.key === key);
  const first = (it.links || []).find((l) => l.href);
  return found || (key === "o" && first ? { do: "open", label: "Open", href: first.href } : null);
}

function actButtons(it) {
  return h("div", { class: "rv-acts" }, (it.actions || []).filter((a) => a.do !== "open").map((a) => {
    const tone = a.do === "reviewed" || a.meaning === "approve" || a.label === "Confirm" ? "human" : "";
    const marks = a.do === "reviewed" ? { "data-control": "review_mark" } : {};
    // a verdict carries the same label as on Home and in the Inbox ("Start a trial", not "Trial")
    const label = a.do === "decide" && a.body && VERDICT_LABEL[a.body.verdict] ? VERDICT_LABEL[a.body.verdict] : a.label;
    return h("button", Object.assign({ type: "button", class: "btn tiny " + tone, "data-key": "rv:" + a.do + ":" + (a.key || a.label),
      "aria-keyshortcuts": a.key || null, onclick: (e) => { e.stopPropagation(); select(it.id); run(it, a); } }, marks),
    label, a.key ? h("kbd", { class: "rv-k" }, a.key) : null);
  }));
}

// -- rows, groups and the page ----------------------------------------------------------------------------

function row(it) {
  const li = h("li", { class: "rv-row" + (it.reviewed ? " done" : ""), "data-id": it.id, tabindex: "-1", role: "option", "aria-selected": "false" },
    h("span", { class: "rv-ic", "aria-hidden": "true" }, icon(KIND_ICON[it.kind] || "activity")),
    h("div", { class: "rv-body" },
      h("button", { type: "button", class: "rv-title", "data-key": "rv-open", "data-ud": "", onclick: () => { select(it.id); openDrawer(it); } }, titleSaid(it)),
      h("div", { class: "rv-meta" }, chips(it), byBadge(it.by), it.at ? h("span", { class: "muted small rv-at", tip: fmtAt(it.at) }, localDateTime(it.at)) : null),
      it.detail ? h("p", { class: "rv-detail muted small" }, it.detail) : null),
    actButtons(it));
  li.addEventListener("click", (e) => { if (!e.target.closest("button, a")) select(it.id); });
  return li;
}
function group(g) {
  if (!technical() && g.id === "ide" && !g.count) return null;
  return h("section", { class: "rv-group", "data-group": g.id, "aria-labelledby": "rv-g-" + g.id },
    h("h2", { class: "rv-gh", id: "rv-g-" + g.id }, icon(GROUP_ICON[g.id] || "activity"), h("span", null, technical() ? g.label : GROUP_PLAIN[g.id] || g.label),
      h("span", { class: "count" + (g.count ? "" : " zero") }, String(g.count))),
    g.count ? h("p", { class: "muted small rv-q" }, g.question) : null,
    g.count ? h("ul", { class: "rv-list", role: "listbox", "aria-label": g.label }, g.items.map(row))
      : h("p", { class: "muted small rv-none" }, GROUP_EMPTY[g.id] || "Nothing."));
}
function costBlock(c) {
  const body = !c.measured ? h("p", { class: "muted small" }, technical() ? "Not measured: " + c.why + "."
    : /no model run/.test(c.why || "") ? "No AI cost recorded in this period." : "AI cost not known: " + c.why + ".")
    : h("table", { class: "rv-cost" }, h("thead", null, h("tr", null, ["Project", "Role", "Runs", "Tokens in", "Tokens out", "Cost"].map((x) => h("th", null, x)))),
      h("tbody", null, c.rows.map((r) => h("tr", null, h("td", null, r.title || r.project), h("td", null, r.role), h("td", null, String(r.runs)),
        h("td", null, r.tokens_measured ? String(r.tokens_in) : "not measured"), h("td", null, r.tokens_measured ? String(r.tokens_out) : "not measured"),
        h("td", null, r.spend.cloud === null ? "not measured" : r.spend.cloud.toFixed(4) + " " + c.currency)))));
  return h("section", { class: "rv-group", "data-group": "cost", "aria-labelledby": "rv-g-cost" },
    h("h2", { class: "rv-gh", id: "rv-g-cost" }, icon("coins"), h("span", null, "Cost and usage")), body);
}
function head(d, pid) {
  const since = store.get("gf.review.since") || "";
  const seg = segmented("rv-since", SINCE, since, (v) => { store.set("gf.review.since", v); reload(); }, { label: "Period" });
  const all = button("Mark all reviewed", { icon: "check-circle", kind: "human primary", key: "rv-done", "data-control": "mark_all_reviewed",
    onclick: () => markAll(pid) });
  const digest = pid ? null : button("Morning digest", { icon: "bell", kind: "quiet", key: "rv-digest", "data-control": "review_digest",
    onclick: () => openDigest() });
  return [pid ? h("div", { class: "rv-head-p" }, h("h2", { class: "view-h" }, "Review"), h("p", { class: "lede" }, headlineSaid(d.headline)))
    : pageHead("Review", headlineSaid(d.headline), { icon: "eye" }),
  h("div", { class: "rv-bar" }, seg, h("span", { class: "muted small rv-period", tip: fmtAt(d.since) + " – " + fmtAt(d.until) },
    "From " + localDateTime(d.since) + " (" + d.basis + ") to " + localDateTime(d.until)),
    h("span", { class: "rv-bar-r" }, digest, all)),
  // the keys are there for whoever wants them, folded: a mouse user does not need the legend in sight
  h("details", { class: "muted small rv-keys" }, h("summary", null, "Keyboard shortcuts"),
    h("p", null, ["j k move", "a first choice", "d second choice", "r reviewed", "o open", "Enter preview"].map((k) => h("kbd", null, k)),
      " The key of each choice is shown on its button."))];
}
function draw(root) {
  const d = R.data;
  fill(root, head(d, R.pid), d.groups.map(group), costBlock(d.cost), h("aside", { class: "rv-drawer", id: "rv-drawer", hidden: true, "aria-labelledby": "rv-dh" }));
  const list = items();
  R.sel = Math.min(R.sel, Math.max(0, list.length - 1));
  if (list.length) mark(list[R.sel].id, false);
}

async function load(root) {
  R.data = await api("GET", path(R.pid));
  if (!root.isConnected) return;
  draw(root);
}
async function reload() {
  const root = $("#rv-root");
  if (root) await load(root);
  if (nav.refreshShell) nav.refreshShell();
}

export async function renderReview(seq) {
  R.pid = null;
  const data = await api("GET", path(null));
  if (seq !== S.seq) return;
  R.data = data;
  document.title = "Review · Rihmasto.ai";
  const root = h("div", { id: "rv-root", class: "rv" });
  fill($("#main"), root);
  draw(root);
}

// The project's Review tab: drawn at once, filled when its review is read.
export function viewReview(p) {
  R.pid = p.meta.id;
  const root = h("div", { id: "rv-root", class: "rv" }, h("p", { class: "muted" }, "Reading what happened since you last looked…"));
  load(root).catch((e) => { if (root.isConnected) fill(root, h("p", { class: "w-warn", role: "alert" }, icon("alert"), e.message)); });
  return root;
}

// Home's first card: since you last looked, in one line, and the way to the Review.
export async function reviewCard(box) {
  if (!box) return;
  let d;
  try { d = await api("GET", "/api/review" + query()); } catch (e) { return; }
  if (!box.isConnected) return;
  const c = d.counts;
  fill(box, h("a", { class: "card rv-card", href: "#/review", "data-control": "review_card", "data-key": "home:review" },
    h("span", { class: "card-ic" }, icon("eye")),
    h("span", { class: "rv-card-t" }, h("b", null, headlineSaid(d.headline)),
      h("small", { class: "muted" }, c.unreviewed ? plural(c.unreviewed, "change") + " to review · " : "", "Open the Review")),
    icon("chevron-right")));
}

// -- the selection, the keys and the preview drawer --------------------------------------------------------

function mark(id, focus) {
  $$(".rv-row").forEach((r) => { const on = r.dataset.id === id; r.classList.toggle("sel", on); r.setAttribute("aria-selected", String(on)); });
  const el = $('.rv-row[data-id="' + CSS.escape(id) + '"]');
  if (el && focus) { el.focus({ preventScroll: false }); el.scrollIntoView({ block: "nearest" }); }
}
function select(id) {
  const i = items().findIndex((x) => x.id === id);
  if (i >= 0) { R.sel = i; mark(id, true); }
  if (R.open && R.open !== id) openDrawer(items()[R.sel]);
}
function move(step) {
  const list = items();
  if (!list.length) return;
  R.sel = (R.sel + step + list.length) % list.length;
  mark(list[R.sel].id, true);
  if (R.open) openDrawer(list[R.sel]);
}
function closeDrawer() {
  const dr = $("#rv-drawer");
  if (!dr) return;
  dr.hidden = true;
  document.documentElement.classList.remove("rv-drawer-open");
  const back = R.open && $('.rv-row[data-id="' + CSS.escape(R.open) + '"]');
  R.open = null;
  if (back) back.focus();
}

function diffView(d) {
  if (!d) return null;
  if (!d.measured) return h("p", { class: "muted small" }, "Diff not measured: " + d.why + ".");
  const lines = String(d.diff || "").split("\n");
  return [h("p", { class: "small" }, plural(d.files, "file") + " changed, +" + d.added + " −" + d.deleted + (d.cut ? " (cut at a readable size)" : "")),
    d.per_file ? h("ul", { class: "rv-files" }, d.per_file.map((f) => h("li", null, h("code", null, f.path), " +" + (f.added === null ? "bin" : f.added)
      + " −" + (f.deleted === null ? "bin" : f.deleted)))) : null,
    d.diff ? h("pre", { class: "rv-diffpre", tabindex: "0", "aria-label": "The diff" }, lines.map((l) => h("span", {
      class: l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : l.startsWith("@@") ? "hunk" : null }, l + "\n"))) : null];
}

async function openDrawer(it) {
  const dr = $("#rv-drawer");
  if (!dr || !it) return;
  R.open = it.id;
  const body = h("div", { class: "rv-dbody", "aria-live": "polite" }, h("p", { class: "muted small" }, it.detail || ""));
  fill(dr, h("div", { class: "rv-dhead" }, h("h2", { id: "rv-dh" }, it.title),
    h("button", { type: "button", class: "icon-btn", "aria-label": "Close the preview", "data-key": "rv-close", onclick: closeDrawer }, icon("x"))),
  h("div", { class: "rv-meta" }, chips(it)), h("p", null, byBadge(it.by)),
  h("ul", { class: "rv-links" }, (it.links || []).filter((l) => l.href).map((l) => h("li", null, h("a", { href: l.href }, l.label, icon("arrow-right"))))),
  actButtons(it), body);
  dr.hidden = false;
  document.documentElement.classList.add("rv-drawer-open");
  if (!it.project) return;
  let d;
  try {
    d = await api("GET", "/api/projects/" + enc(it.project) + "/review/detail?item=" + enc(it.id.slice(it.project.length + 1)) + "&" + query().slice(1));
  } catch (e) { if (R.open === it.id) fill(body, h("p", { class: "w-warn" }, icon("alert"), e.message)); return; }
  if (R.open !== it.id || !body.isConnected) return;
  const facts = (d.facts || []).filter(([k]) => !["person", "persona", "identity"].includes(k));
  const signals = d.signals && typeof d.signals === "object" ? Object.entries(d.signals) : [];
  fill(body, diffView(d.diff),
    signals.length ? h("dl", { class: "kv rv-signals" }, signals.map(([k, v]) => [h("dt", null, k), h("dd", null, String(v))])) : null,
    (d.objections || []).length ? h("ul", { class: "rv-obj" }, d.objections.map((o) => h("li", null, String(o)))) : null,
    facts.length ? h("details", { class: "rv-facts" }, h("summary", null, "The record"), h("dl", { class: "kv" }, facts.map(([k, v]) => [h("dt", null, k), h("dd", { class: "mono" }, String(v))]))) : null);
}

function typing(e) { const t = e.target; return t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)); }
document.addEventListener("keydown", (e) => {
  if (!$("#rv-root") || !R.data || e.ctrlKey || e.metaKey || e.altKey || typing(e) || $("#modal").open || $("#palette").open) return;
  if ($("#assistant") && !$("#assistant").hidden && $("#assistant").contains(document.activeElement)) return;
  const it = items()[R.sel];
  const k = e.key;
  if (k === "j" || k === "ArrowDown" && document.activeElement && document.activeElement.classList.contains("rv-row")) { e.preventDefault(); move(1); return; }
  if (k === "k" || k === "ArrowUp" && document.activeElement && document.activeElement.classList.contains("rv-row")) { e.preventDefault(); move(-1); return; }
  if (k === "Escape" && R.open) { e.preventDefault(); closeDrawer(); return; }
  if (!it) return;
  if (k === "Enter" && document.activeElement && document.activeElement.classList.contains("rv-row")) { e.preventDefault(); openDrawer(it); return; }
  const a = ["a", "d", "r", "o"].includes(k) ? keyed(it, k) : null;
  if (a) { e.preventDefault(); run(it, a); }
});

// -- Mark all reviewed, and the morning digest -------------------------------------------------------------

async function markAll(pid) {
  if (!needPerson()) return;
  const since = store.get("gf.review.since") || "";
  const out = await act($(".rv-bar"), () => api("POST", "/api/review/done", Object.assign(pid ? { project: pid } : {}, since ? { since } : {}, signed())));
  if (!out) return;
  store.set("gf.review.since", "");
  say("Marked all reviewed (" + out.done.headline.replace("Since you last looked: ", "") + "). Your next review starts now.", "good");
  await reload();
}

function offset() {
  const m = -new Date().getTimezoneOffset();
  const a = Math.abs(m);
  return (m >= 0 ? "+" : "-") + String(Math.floor(a / 60)).padStart(2, "0") + ":" + String(a % 60).padStart(2, "0");
}
async function openDigest() {
  if (!needPerson()) return;
  const d = await api("GET", "/api/review/digest?person=" + enc(S.person.trim()) + "&persona=" + enc(S.persona));
  const now = d.digest && !d.digest.off ? d.digest : null;
  const recv = h("select", { id: "rv-recv", "data-key": "rv-recv" }, d.receivers.map((r) => h("option", { value: r.id, selected: now && now.subscription === r.id }, r.id + " (" + r.sink + ")")));
  const at = h("input", { id: "rv-at", type: "time", value: (now && now.at) || "07:30", "data-key": "rv-at" });
  const days = h("select", { id: "rv-days", "data-key": "rv-days" }, [["weekdays", "Weekdays"], ["daily", "Every day"]].map(([v, l]) => h("option", { value: v, selected: now && v === "daily" && now.days.length === 7 }, l)));
  const tz = h("input", { id: "rv-tz", value: (now && now.tz) || offset(), maxlength: "64", "data-key": "rv-tz" });
  const save = h("button", { type: "submit", class: "btn human primary", "data-key": "rv-digest-save", disabled: !d.receivers.length }, "Save, signed");
  const off = button("Turn it off", { kind: "quiet", key: "rv-digest-off", onclick: () => put({ off: true }) });
  const put = async (body) => {
    const out = await act(form, () => api("PUT", "/api/review/digest", Object.assign(body, signed())));
    if (!out) return;
    closeModal();
    say(out.digest.off ? "Your morning digest is off." : "Your morning digest goes to " + out.digest.subscription + " at " + out.digest.at + " (" + out.digest.tz + ").", "good");
  };
  const form = h("form", { class: "rv-form", novalidate: true },
    h("p", { class: "small" }, "The same review as a message, at the time you set, with a link back here. Held back when nothing happened."),
    d.receivers.length ? null : h("p", { class: "w-warn" }, icon("alert"), "IT has set no Teams, Slack or mail receiver for the " + personaLabel(S.persona) + " persona yet."),
    h("div", { class: "field" }, h("label", { for: "rv-recv" }, "Receiver"), recv),
    h("div", { class: "rv-row2" }, h("div", { class: "field" }, h("label", { for: "rv-at" }, "Time"), at),
      h("div", { class: "field" }, h("label", { for: "rv-days" }, "Days"), days),
      h("div", { class: "field" }, h("label", { for: "rv-tz" }, "Time zone"), tz)),
    h("div", { class: "btns" }, save, now ? off : null));
  form.addEventListener("submit", (e) => { e.preventDefault(); put({ subscription: recv.value, at: at.value, days: days.value, tz: tz.value.trim() }); });
  openModal("Morning digest", form, { icon: "bell" });
}
