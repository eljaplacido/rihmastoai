/* People in the loop (kernel/hitl.py and kin, FR-HITL1): questions, decisions and feedback put to the persona or
   person responsible, answered and signed; one-use links for people outside the system; nudges that escalate as an
   ask ages; and, per check family, advise or require. Every write is signed with the person chip; Ask Rihma does the
   same by words ("who hasn't answered?", "send to the legal reviewer: ..."). Text from records is data-ud. */

import { h, fill, icon, chip, api, act, say, signed, needPerson, enc, button, card, personaLabel, mayAct, heldPersonas, everything, S, ago } from "./core.js";
import { pick, emptyState, datum } from "./words.js";
import { onceLinks } from "./hitl_once.js";

const FAMILY_ICON = { quality: "check-circle", governance: "shield", legal: "file-check", security: "key", general: "comment" };
const STEP_WORD = { nudge: ["Reminded", "warning"], escalate: ["Escalated", "serious"], overdue: ["Overdue", "critical"] };
const base = (pid) => "/api/projects/" + enc(pid) + "/hitl";
let shownOnce = null;     // new links' addresses (a link made, or a nudge's fresh one), shown once until drawn again

function field(id, label, el) { return h("div", { class: "field" }, h("label", { for: id }, label), el); }
function select(id, values, chosen, labelOf) {
  return h("select", { id }, values.map((v) => h("option", { value: v, selected: v === chosen || null }, labelOf ? labelOf(v) : v)));
}
function famWord(f) { return f.charAt(0).toUpperCase() + f.slice(1); }
function toWhom(a) { return a.to.person ? a.to.person + (a.to.external ? " (outside)" : "") : personaLabel(a.to.persona); }
const SET_IN = { default: "the default", "this project": "set for this project", "platform-wide": "set for all projects",
  "enforcement settings": "from the enforcement settings" };
const KIND_WORD = { question: "Question", decision: "Decision", feedback: "Feedback" };
function hoursWord(h0) {
  if (h0 < 1) return "under an hour";
  return h0 < 24 ? Math.round(h0) + " h" : Math.round(h0 / 24 * 10) / 10 + " days";
}

async function post(path, body, method) { return api(method || "POST", path, Object.assign(body || {}, signed())); }

// -- one ask ---------------------------------------------------------------------------------------------------

function answerForm(pid, a, again) {
  const id = "hl-ans-" + a.id;
  const input = a.kind === "decision" ? select(id, a.options, a.options[0])
    : h("textarea", { id, rows: "2", maxlength: "2000" });
  const note = h("input", { id: id + "-c", type: "text", maxlength: "2000" });
  const b = button("Answer", { icon: "check", kind: "small primary", "data-control": "hitl_answer", aria: "Answer " + a.id });
  b.addEventListener("click", () => act(b.parentElement, async () => {
    if (!needPerson()) return;
    await post(base(pid) + "/answer", { ask: a.id, answer: input.value, comment: note.value });
    say(a.id + " answered, signed with your name.", "good");
    await again();
  }));
  return h("div", { class: "hl-answer" }, field(id, a.kind === "decision" ? "Your choice" : "Your answer", input),
    field(id + "-c", "Anything to add (optional)", note), h("div", { class: "btns" }, b));
}

function sendButton(pid, a, again) {
  const b = button(pick("Send to their chat or email", "Send to their channels"), { icon: "send", kind: "small", "data-control": "hitl_send",
    aria: "Send " + a.id + " to " + toWhom(a) });
  b.addEventListener("click", () => act(b.parentElement, async () => {
    if (!needPerson()) return;
    const out = await post(base(pid) + "/send", { ask: a.id });
    say(out.said, out.results.some((r) => r.outcome === "delivered") ? "good" : "warning");
    await again();
  }));
  return b;
}

function stepChip(row) {
  if (!row || !row.step) return null;
  const [word, tone] = STEP_WORD[row.step];
  return chip(tone, "bell", word + (row.quiet ? " (quiet: solo, not required)" : ""));
}

function askCard(pid, a, view, again) {
  const nudge = (view.nudges || []).find((n) => n.ask === a.id);
  const req = view.blocking.includes(a.id);
  const mine = a.state === "open" && mayAct([a.to.persona]);
  const answers = a.answers.map((x) => h("p", { class: "small" }, icon("check-circle"), " ", datum(x.answer),
    h("span", { class: "muted" }, " · " + x.person + " as " + personaLabel(x.persona) + (x.external ? ", from outside via " + x.via : "")
      + " · " + ago(x.at)), x.comment ? h("span", null, " · ", datum(x.comment)) : null));
  return h("li", { class: "card hl-ask", "data-ask": a.id, "data-state": a.state },
    h("div", { class: "hl-top" }, chip("neutral", FAMILY_ICON[a.family] || "comment", famWord(a.family)),
      chip("neutral", null, KIND_WORD[a.kind] || a.kind), req ? chip("critical", "flag", pick("Delivery waits on it", "Required")) : null, stepChip(nudge),
      h("span", { class: "muted small hl-at" }, a.id + " · " + ago(a.at))),
    h("p", { class: "hl-text" }, datum(a.text)),
    h("p", { class: "muted small" }, (a.state === "open" ? "Waits on " : "Put to ") + toWhom(a) + ", asked by " + a.by
      + (nudge && a.state === "open" ? " · open " + hoursWord(nudge.hours) : "")),
    a.options.length && a.state === "open" ? h("p", { class: "small" }, "Choices: ", datum(a.options.join(" · "))) : null,
    answers,
    a.state === "open" ? h("div", { class: "btns" }, sendButton(pid, a, again)) : null,
    mine ? answerForm(pid, a, again) : a.state === "open" ? notYours(a) : null);
}

// Why there is no answer form here, and what to do: switch persona when the person holds it (FR-HITL2).
function notYours(a) {
  const who = personaLabel(a.to.persona);
  const holds = heldPersonas().includes(a.to.persona) && !everything();
  return h("p", { class: "small muted hl-notyours", "data-ask-hint": a.id }, icon("info"), " ",
    a.to.external ? a.to.person + " answers it on their own page."
      : holds ? "Put to " + who + ", and you are signed in as " + personaLabel(S.persona) + ". You hold " + who
        + " too: switch to it in the person menu to answer here."
      : "Put to " + who + ": they answer it here. Send it to their channels, or nudge them.");
}

// -- asking ----------------------------------------------------------------------------------------------------

function askForm(pid, view, again) {
  const text = h("textarea", { id: "hl-text", rows: "2", maxlength: "2000", placeholder: "Can we keep customers' emails for two years?" });
  const kind = select("hl-kind", view.kinds, "question", (k) => KIND_WORD[k] || k);
  const fam = select("hl-fam", view.families, "general", famWord);
  const to = select("hl-to", S.personas.map((p) => p.id), view.family_persona.general, personaLabel);
  const person = h("input", { id: "hl-person", type: "text", maxlength: "120", placeholder: "optional: a name" });
  const options = h("input", { id: "hl-opts", type: "text", placeholder: "Yes, No, Not yet" });
  const optField = field("hl-opts", "Choices, separated by commas", options);
  optField.hidden = true;
  kind.addEventListener("change", () => { optField.hidden = kind.value !== "decision"; });
  fam.addEventListener("change", () => { to.value = view.family_persona[fam.value] || to.value; });
  const b = button("Ask", { icon: "send", kind: "primary", "data-control": "hitl_ask" });
  b.addEventListener("click", () => act(b.parentElement, async () => {
    if (!needPerson()) return;
    const opts = kind.value === "decision" ? options.value.split(",").map((s) => s.trim()).filter(Boolean) : [];
    const out = await post(base(pid) + "/asks", { text: text.value, kind: kind.value, family: fam.value, to_persona: to.value,
      to_person: person.value, options: opts });
    say(out.ask.id + " is put to " + toWhom(out.ask) + ". Send it to their channels, or give a person outside a link.", "good");
    await again();
  }));
  return card({ title: "Ask someone", icon: "comment", id: "hl-askc" },
    h("p", { class: "muted small" }, pick("Put a question, a decision or a request for feedback to the person responsible. They answer here, or on a page of their own.",
      "Put an ask to a persona (or a named person). Answers are signed and in the ledger.")),
    field("hl-text", "What you ask", text), h("div", { class: "hl-grid" }, field("hl-kind", "Kind", kind), field("hl-fam", "Check", fam),
      field("hl-to", "Goes to", to), field("hl-person", "Person (optional)", person)), optField, h("div", { class: "btns" }, b));
}

// -- people outside --------------------------------------------------------------------------------------------

function linkForm(pid, view, again) {
  const open = view.asks.filter((a) => a.state === "open");
  if (!open.length) return h("p", { class: "muted small" }, "Ask something first: a link carries open asks only.");
  const name = h("input", { id: "hl-ln", type: "text", maxlength: "120", placeholder: "Maria Example" });
  const role = h("input", { id: "hl-lr", type: "text", maxlength: "120", placeholder: "External legal counsel" });
  const chan = select("hl-lc", ["copy", "email", "whatsapp", "teams", "slack"], "copy",
    (c) => ({ copy: "I copy it myself", email: "Email", whatsapp: "WhatsApp", teams: "Teams channel", slack: "Slack channel" })[c]);
  const addr = h("input", { id: "hl-la", type: "text", maxlength: "200", placeholder: "+358401234567, name@example.org or SUB-001" });
  const hours = h("input", { id: "hl-lh", type: "number", min: "1", max: "720", value: "72" });
  const boxes = open.map((a) => h("label", { class: "chk-l hl-pick" }, h("input", { type: "checkbox", value: a.id, checked: true }),
    " " + a.id + " · ", datum(a.text.slice(0, 80))));
  const b = button("Make the link", { icon: "link", kind: "primary", "data-control": "hitl_link" });
  b.addEventListener("click", () => act(b.parentElement, async () => {
    if (!needPerson()) return;
    const asks = boxes.map((l) => l.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
    const out = await post(base(pid) + "/links", { name: name.value, role: role.value, asks, channel: chan.value,
      address: addr.value, hours: Number(hours.value) || 72 });
    shownOnce = { once: out.once || [], warning: out.warning || null };
    say(out.link.id + " made for " + out.link.name + ". " + out.sent.said, out.sent.outcome === "failed" || out.warning ? "warning" : "good");
    await again();
  }));
  // A link on this computer's own address reaches nobody outside: say so before it is made (FR-HITL2).
  const local = view.link_base_local ? h("p", { class: "small hl-local", role: "note" }, icon("alert"), " ",
    "Links point at ", h("span", { class: "mono", "data-ud": "" }, view.link_base), ": this computer only, so nobody outside can open them. "
      + "IT sets where outside links point under Channels below.") : null;
  return h("div", null, local, field("hl-ln", "Their name", name), field("hl-lr", "Their role, in words", role),
    h("fieldset", null, h("legend", null, "Which asks"), boxes),
    h("div", { class: "hl-grid" }, field("hl-lc", "Send it by", chan), field("hl-la", "Their number, address or channel", addr),
      field("hl-lh", "Open for (hours)", hours)), h("div", { class: "btns" }, b));
}

function onceBox() {
  if (!shownOnce || !shownOnce.once.length) return null;
  const box = onceLinks(shownOnce.once, shownOnce.warning);
  shownOnce = null;
  return box;
}

function linkRow(pid, l, again) {
  const live = l.state === "active" || l.state === "opened";
  const b = live ? button("Withdraw", { icon: "x", kind: "small", "data-control": "hitl_link_revoke", aria: "Withdraw " + l.id }) : null;
  if (b) b.addEventListener("click", () => act(b.parentElement, async () => {
    if (!needPerson()) return;
    await post(base(pid) + "/revoke", { link: l.id });
    say(l.id + " withdrawn: it no longer opens.", "good");
    await again();
  }));
  const tone = { active: "info", opened: "good", revoked: "neutral", expired: "neutral" }[l.state] || "neutral";
  return h("li", { class: "hl-link", "data-link": l.id }, chip(tone, "link", l.state), " ",
    h("b", null, l.name), h("span", { class: "muted small" }, (l.role ? " · " + l.role : "") + " · as " + personaLabel(l.persona)
      + " · " + l.asks.join(", ") + " · by " + l.channel + " · until " + l.expires.slice(0, 16).replace("T", " ")), b ? " " : null, b);
}

function outsideCard(pid, view, again) {
  return card({ title: pick("People outside Rihmasto", "Outside reviewers"), icon: "users", id: "hl-out" },
    h("p", { class: "muted small" }, "A one-use link opens a page with only the asks you choose: nothing else of this project. Their answers are signed with their name."),
    view.links.length ? h("ul", { class: "plain hl-links" }, view.links.map((l) => linkRow(pid, l, again))) : null,
    h("details", { class: "hl-more" }, h("summary", null, "Give someone a link"), linkForm(pid, view, again)));
}

// -- nudges, enforcement and channels -------------------------------------------------------------------------

function nudgeBar(pid, view, again) {
  const due = (view.nudges || []).filter((n) => n.to_send);
  const b = button("Nudge now", { icon: "bell", kind: "small", "data-control": "hitl_nudge", disabled: !due.length,
    tip: due.length ? null : "Nothing is due a reminder: an open ask is reminded after a day, escalated after three, overdue after a week." });
  b.addEventListener("click", () => act(b.parentElement, async () => {
    if (!needPerson()) return;
    const out = await post(base(pid) + "/nudge", {});
    // a fresh link for a person outside is shown once here to pass on; what went nowhere says what IT adds (FR-HITL2)
    if ((out.once || []).length) shownOnce = { once: out.once, warning: out.warning || null };
    say(out.said, (out.not_sent || []).length || out.warning ? "warning" : "good");
    await again();
  }));
  return h("div", { class: "hl-nudge" }, h("span", { class: "small" }, due.length ? due.length + " reminder(s) due" : "No reminder due now"), b);
}

function levelRow(pid, lv, view, again) {
  const sel = select("hl-lv-" + lv.family, ["advise", "require"], lv.level,
    (v) => (v === "require" ? pick("Must answer before delivery", "Require") : pick("Advise only", "Advise")));
  const scope = select("hl-sc-" + lv.family, ["project", "platform"], "project", (v) => (v === "project" ? "This project" : "All projects"));
  const b = button("Set", { kind: "small", "data-control": "hitl_enforce", aria: "Set " + lv.label });
  b.addEventListener("click", () => act(b.parentElement, async () => {
    if (!needPerson()) return;
    await post(base(pid) + "/enforcement", { family: lv.family, level: sel.value, scope: scope.value }, "PUT");
    say(lv.label + " checks: " + sel.value + " (" + (scope.value === "project" ? "this project" : "all projects") + ").", "good");
    await again();
  }));
  const where = SET_IN[lv.set_in] || lv.set_in;
  return h("li", { class: "hl-level" }, h("div", null, h("b", null, lv.label), h("div", { class: "muted small" },
    where.charAt(0).toUpperCase() + where.slice(1) + " · reviewer: " + personaLabel(lv.persona))),
    h("span", { class: "hl-lv-c" }, sel, scope, b));
}

function channelsCard(view, again) {
  const c = view.channels;
  const wa = c.whatsapp;
  const prov = select("hl-wp", ["", "twilio", "meta"], wa.provider || "", (v) => ({ "": "None", twilio: "Twilio", meta: "Meta WhatsApp Cloud API" })[v]);
  const url = h("input", { id: "hl-wu", type: "text", placeholder: "https://api.twilio.com/... or https://graph.facebook.com/..." });
  const key = h("input", { id: "hl-wk", type: "text", value: wa.key_env || "", placeholder: "WHATSAPP_KEY" });
  const from = h("input", { id: "hl-wf", type: "text", value: wa.sender || "", placeholder: "+14155238886" });
  const linkBase = h("input", { id: "hl-lb", type: "text", value: c.link_base || "", placeholder: "https://review.example.org" });
  const b = button("Save channels", { kind: "small", "data-control": "hitl_channels", disabled: !mayAct(["it"]),
    tip: mayAct(["it"]) ? null : "IT sets the channels." });
  b.addEventListener("click", () => act(b.parentElement, async () => {
    if (!needPerson()) return;
    await api("PUT", "/api/hitl/channels", Object.assign({ provider: prov.value, url: url.value, key_env: key.value, sender: from.value,
      link_base: linkBase.value }, signed(), { persona: "it" }));
    say("Channels saved: a key is read from its variable on this machine, never stored.", "good");
    await again();
  }));
  const subs = c.relay.length ? c.relay.map((s) => s.id + " " + s.sink + " for " + s.personas.map(personaLabel).join(", ")).join(" · ")
    : "No Teams, Slack or email channel yet: IT adds one (rihmasto relay subscribe).";
  return h("details", { class: "hl-more" }, h("summary", null, "Channels (platform-wide, set by IT)"),
    h("p", { class: "small" }, subs),
    h("p", { class: "small muted" }, "WhatsApp: " + (wa.configured ? wa.provider + (wa.key_present ? ", key present" : ", key not set on this machine (" + wa.key_env + ")") : "not set up")),
    h("div", { class: "hl-grid" }, field("hl-wp", "WhatsApp provider", prov), field("hl-wu", "Provider URL", url),
      field("hl-wk", "Key's variable name (never the key)", key), field("hl-wf", "Sender number", from),
      field("hl-lb", "Where outside links point", linkBase)), h("div", { class: "btns" }, b));
}

function rulesCard(pid, view, again) {
  return card({ title: pick("How strictly each check is enforced", "Enforcement per check family"), icon: "shield", id: "hl-rules" },
    h("p", { class: "muted small" }, pick("Advise: shown and reminded, nothing waits. Must answer: delivery waits until it is answered.",
      "advise: shown and nudged; require: delivery is held (autonomy.cleared_to_deliver) until every open ask of the family is answered.")),
    h("ul", { class: "plain hl-levels" }, view.levels.map((lv) => levelRow(pid, lv, view, again))), channelsCard(view, again));
}

// -- the view --------------------------------------------------------------------------------------------------

function waitingList(pid, view, again) {
  const open = view.asks.filter((a) => a.state === "open");
  const done = view.asks.filter((a) => a.state !== "open");
  if (!view.asks.length) {
    const ask = button("Ask Rihma how", { icon: "bot", kind: "small", "data-control": "hitl_waiting",
      onclick: async () => { const m = await import("./assistant.js"); m.openAssistant(); m.send("Who hasn't answered?"); } });
    return emptyState("loop", ask, { icon: "users", what: "No question waits on anyone.",
      how: pick("Ask someone below: a reviewer inside, or a person outside with a one-use link. What they have not answered appears here, with how long it has waited.",
        "Put an ask below (or say \"send to the legal reviewer: ...\" in Ask Rihma); open asks appear here with their age and nudge step.") });
  }
  return h("section", { "data-control": "hitl_waiting", "aria-label": "Waiting on" },
    h("h3", { class: "label-h" }, icon("clock"), " Waiting on someone (" + open.length + ")"),
    open.length ? h("ul", { class: "plain hl-list" }, open.map((a) => askCard(pid, a, view, again)))
      : h("p", { class: "muted small" }, "Everything put to people is answered."),
    done.length ? h("details", { class: "hl-more" }, h("summary", null, "Answered (" + done.length + ")"),
      h("ul", { class: "plain hl-list" }, done.map((a) => askCard(pid, a, view, again)))) : null);
}

function head(view) {
  const open = view ? view.waiting.length : 0;
  const req = view ? view.blocking.length : 0;
  return h("div", { class: "q" }, h("h2", { id: "view-title", tabindex: "-1" }, "People in the loop"),
    h("p", null, pick("Who still has to answer, and what waits on them: reviewers here and people outside Rihmasto.",
      "Asks put to personas and people (inside or outside), their answers, nudges and each check family's enforcement.")),
    view ? h("p", { class: "small", "data-ud": "" }, open + " waiting" + (req ? " · " + req + " must be answered before delivery" : "")) : null);
}

async function draw(box, pid) {
  const view = await api("GET", base(pid));
  const again = () => draw(box, pid).catch((e) => say(e.message, "critical"));
  fill(box, head(view), h("div", { class: "hl-cols" },
    h("div", { class: "hl-main" }, onceBox(), nudgeBar(pid, view, again), waitingList(pid, view, again), rulesCard(pid, view, again)),
    h("div", { class: "hl-side" }, askForm(pid, view, again), outsideCard(pid, view, again))));
}

export function render(p) {
  const pid = p.meta.id;
  const box = h("div", { class: "hl-view" }, head(null), h("p", { class: "muted" }, "Reading who is in the loop…"));
  draw(box, pid).catch((e) => fill(box, head(null), emptyState("loop", null, { icon: "alert", what: "People in the loop could not be read.",
    how: e.message + " Ask Rihma what to do, or reload the page." })));
  return box;
}
