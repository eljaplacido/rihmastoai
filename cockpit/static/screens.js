/* Pages beyond Home and the project: the delivery square, the capability catalogue, Projects, the
   Inbox across projects, Settings (embeds, appearance, sign-in links), and the New project modal.
   Every write goes through the same routes as before, signed with the person and persona. */

import {
  S, $, $$, h, fill, icon, chip, api, act, say, signed, needPerson, nav, enc, link, plural, button, card, empty,
  pageHead, skeleton, openModal, closeModal, profileOf, profileChip, personaLabel, segmented, viewChoice,
  setViewChoice, avatar, ago, fmtAge, fmtAt, nowChip, iconButton, infoButton, attachTip, local, AuthError,
  KIND_LABEL, KIND_ICON, VERDICT_LABEL, CATALOGUE_STATE, FACTORY_PID, STAGE_ICON, ACCENTS, cap,
  mayAct, decides, everything, inboxPersona,
} from "./core.js";
import { squareDiagram, catalogueCard, catalogueState, WIDGET_DEFS, liveState } from "./widgets.js";
import { impactPanelFor, tryPanel, openThread } from "./project.js";
import { decideBlock, cardTop, details, commentRow } from "./decide.js";
import { projectHue } from "./scope.js";
import { elsewhereNote } from "./elsewhere.js";
import {
  word, technical, pick, nowSaid, ambitionWord, modeWord, titleOf, factoryWord, cardTitle, cardTitleEl, plainCard, measureHow, stageWord,
} from "./words.js";
import { squareLanes, squareScope, squarePid, setSquarePid, scopeSwitch, scopeLine } from "./square.js";
import { peopleCard, inboxPersonaFilter } from "./people.js";   // solo and team mode (FR-PPL1)
import { heldAll } from "./hitl_held.js";   // required answers that hold delivery (FR-HITL2)
import { dataTable } from "./charts.js";
import { currentTheme, setTheme, loadLayout, applyTheme } from "./dashboard.js";
import { loadModules, modulesCard, moduleShows } from "./modules.js";
import { scanStep, looksLikeFolder } from "./scan.js";
import { adoptLabel, adoptChoice, adoptEach } from "./feedin.js";
import { pathField, browseButtons } from "./picker.js";
import { foldersCard } from "./folders.js";
import { postureSection } from "./posture.js";
import { roadsCard, integrationsCard } from "./roads.js";
import { archivedSection } from "./setup.js";
import { agentObsSettingsCard } from "./agentobs.js";
import { aboutCard } from "./about.js";
import { enforcementSettingsCard as harnessSettingsCard } from "./whoacted.js";   // FR-NVL1
import { enforcementSettingsCard } from "./enforcement.js";   // how strict each stage is, for all projects (FR-ENF1)

const CHANNEL_ICON = { chat: "message-square", feed: "signal", form: "file-check", email: "send", monitoring: "activity",
  meeting: "users", embed: "code", manual: "edit" };
// Where a request came in, in the reader's words ("embed" is the website chat to a business owner).
const CHANNEL_PLAIN = { chat: "A chat", feed: "A feed", form: "A form", email: "An email", monitoring: "Monitoring", meeting: "A meeting",
  embed: "Website chat", manual: "Typed in by me" };
function channelWord(c) { return technical() ? cap(c) : CHANNEL_PLAIN[c] || cap(c); }
const SIGNAL_STATE = {
  new: ["warning", "dashed", "New"], routed: ["info", "arrow-right", "Routed to a project"], concept: ["accent", "lightbulb", "Concept"],
  validated: ["good", "check-circle", "Validated"], parked: ["neutral", "pause", "Parked"], rejected: ["neutral", "x-circle", "Rejected"],
};

// Fetch a page's data behind its loading placeholder. The placeholder is called off whether the fetch
// answers or fails, so the error the router shows is never painted over by a skeleton a second later.
async function loaded(main, what, fetcher) {
  const done = skeleton(main, what);
  try { return await fetcher(); } finally { done(); }
}

// Run a write with act(), which disables the block's buttons while it is in flight; a disabled button
// loses the focus to the page body. When nothing took the focus since (a re-render's own target, a
// field the write asked for), it goes back to the control that was used, else to the fallback.
function focusLost() { return !document.activeElement || document.activeElement === document.body; }
async function actKeep(container, control, fn, fallback) {
  const out = await act(container, fn);
  if (!focusLost()) return out;
  const back = control && control.isConnected ? control : typeof fallback === "function" ? fallback() : fallback;
  if (back && back.isConnected && typeof back.focus === "function") back.focus();
  return out;
}

// The people in a corner: one keyboard stop that names everyone with their persona (on focus, the same
// tooltip a pointer gets), and each avatar's own tooltip for the pointer.
function people(list, where) {
  if (!list || !list.length) return h("span", { class: "muted small" }, "No one has worked here yet");
  const said = list.map((p) => p.name + " (" + personaLabel(p.persona) + ")");
  return h("span", { class: "people", role: "group", tabindex: "0", "aria-label": "People " + where + ": " + said.join(", "),
    tip: said.join(", ") },
  list.slice(0, 5).map((p) => h("span", { tip: p.name + " · " + personaLabel(p.persona) }, avatar(p.name))),
  list.length > 5 ? h("small", { "aria-hidden": "true" }, "+" + (list.length - 5)) : null);
}

// A concept on the square has its own address, #/square/<card>; the square brings it into view.
function conceptHref(cardId) { return "#/square/" + enc(cardId); }

// The map's corners are links, and their people are small pictures a pointer can hover (a link holds no
// further keyboard stop). So each corner's link names its count and its people in words, and shows
// them on keyboard focus as on hover: no one needs a pointer to know who works in a corner.
function namePeopleOnMap(map, people) {
  $$(".sq-corner, .sq-factory", map).forEach((a) => {
    const id = a.classList.contains("sq-factory") ? "factory"
      : ([...a.classList].find((c) => c.startsWith("sq-") && c !== "sq-corner") || "").slice(3);
    const label = ($(".sq-label", a) || {}).textContent || "";
    const v = $(".sq-v", a);
    const words = (el) => [...el.childNodes].map((n) => n.textContent.trim()).filter(Boolean).join(" ");
    const count = v ? words(v) : "";
    const bands = $$(".sq-band", a).map(words).join(", ");
    const list = (people || {})[id] || [];
    const who = list.map((p) => p.name + " (" + personaLabel(p.persona) + ")").join(", ");
    a.setAttribute("aria-label", label + ": " + count + (bands ? " (" + bands + ")" : "") + "."
      + (who ? " People: " + who + "." : " No one yet."));
    if (who) attachTip(a, label + ": " + who);
  });
  return map;
}

// -- the delivery square ------------------------------------------------------------------------

function signalForm(sq) {
  const text = h("textarea", { rows: "3", maxlength: "8000", placeholder: "What was asked, in the words it came in", "aria-label": pick("The request", "The need") });
  const channel = h("select", { "aria-label": pick("Came in through", "Channel") }, sq.channels.map((c) => h("option", { value: c, selected: c === "chat" }, channelWord(c))));
  const source = h("input", { maxlength: "200", placeholder: "Where: #ops-team, a meeting, a feed", "aria-label": pick("Where exactly", "Source") });
  const form = h("form", { class: "sig-form", novalidate: true, id: "log-signal" },
    h("div", { class: "field" }, h("label", null, pick("The request", "The need")), text),
    h("div", { class: "row2" }, h("div", { class: "field" }, h("label", null, pick("Came in through", "Channel")), channel),
      h("div", { class: "field" }, h("label", null, pick("Where exactly", "Source")), source)),
    h("div", { class: "btns" }, h("button", { type: "submit", class: "btn primary", "data-control": "log_signal" }, icon("plus"), pick("Log the request", "Log the signal")),
      h("span", { class: "muted small" }, pick("Saved under your name. Rihma will file it under a project or turn it into a new idea for you to approve.",
        "Signed with your name. Triage routes it to a project, or makes a concept."))));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!text.value.trim()) { say("Write the need first.", "warning"); text.focus(); return; }
    if (!needPerson()) return;
    actKeep(form, form.querySelector('button[type="submit"]'), async () => {
      const out = await api("POST", "/api/signals", Object.assign({ text: text.value.trim(), channel: channel.value, source: source.value.trim() }, signed()));
      say(out.signal.id + pick(" is logged. Sort it to send it to a project or make it an idea.", " is logged. Triage it to route it."), "good");
      S.focusNext = '[data-key="' + CSS.escape("triage:" + out.signal.id) + '"]';   // the next step: its Triage
      await nav.rerender();
    });
  });
  return form;
}

function signalRow(s) {
  const st = SIGNAL_STATE[s.state] || ["neutral", "info", s.state];
  const r = s.routed_to || {};
  let action = null;
  if (s.state === "new") {
    action = button("Triage", { icon: "arrow-right", kind: "small", key: "triage:" + s.id });
    action.addEventListener("click", () => {
      if (!needPerson()) return;
      actKeep(action.parentNode, action, async () => {
        const out = await api("POST", "/api/signals/" + enc(s.id) + "/triage", signed());
        const t = out.signal;
        const cls = out.triage && out.triage.class ? " (" + String(out.triage.class).replace(/_/g, " ") + ")" : "";
        say(t.state === "routed" ? s.id + " is now change " + t.routed_to.card + cls + " on " + t.routed_to.project + "."
          : s.id + " is a concept to validate: " + t.routed_to.card + ".", "good");
        // Once triaged it is no longer new, and it may sit beyond the newest: it stays listed, so the
        // person sees what it became, and its link to that takes the focus (the Triage button is gone).
        SQ_SHOWN.delete(s.id);
        SQ_SHOWN.add(s.id);
        while (SQ_SHOWN.size > SQ_SHOWN_MAX) SQ_SHOWN.delete(SQ_SHOWN.values().next().value);
        S.focusNext = '[data-key="' + CSS.escape("signal:" + s.id + ":to") + '"]';
        await nav.rerender();
      }, () => $("#needs-h"));
    });
  } else if (r.project && r.card && s.state === "routed") {
    action = h("a", { class: "small", href: link(r.project, "changes", r.card), "data-key": "signal:" + s.id + ":to" }, r.card, icon("arrow-right"));
  } else if (r.project) {
    action = h("a", { class: "small", href: "#/p/" + enc(r.project), "data-key": "signal:" + s.id + ":to" }, "Open the project", icon("arrow-right"));
  } else if (r.card && s.state === "concept") {
    action = h("a", { class: "small", href: conceptHref(r.card), "data-key": "signal:" + s.id + ":to",
      "aria-label": "Concept " + r.card + " on the square" }, r.card, icon("arrow-right"));
  } else if (r.card) {
    // a parked or rejected concept left the square: its id, with no link to a card that is gone
    action = h("span", { class: "mono small muted" }, r.card);
  }
  return h("li", { class: "sig-row", "data-id": s.id },
    h("span", { class: "sig-ic", tip: cap(s.channel) }, icon(CHANNEL_ICON[s.channel] || "signal")),
    h("div", { class: "sig-b" }, h("p", null, s.text),
      h("div", { class: "sig-m" }, h("span", { class: "mono" }, s.id), h("span", null, cap(s.channel) + " · " + s.source),
        s.person ? h("span", null, "raised by " + s.person) : null, h("span", { tip: fmtAt(s.at) }, ago(s.at)))),
    h("div", { class: "sig-a" }, chip(st[0], st[1], st[2]), action));
}

function conceptCard(c) {
  const may = mayAct((S.meta && S.meta.concept_editors) || []);
  const profiles = (S.meta && S.meta.profiles) || [];
  const key = "concept:" + c.card;
  const title = h("input", { value: c.title || "", maxlength: "80", "aria-label": "Title", disabled: !may || null, "data-key": key + ":title" });
  // the labels say what each choice changes; a business reader gets the plain words for each value
  const L = { profile: pick("Type of project", "Work profile"), maturity: pick("How far it should go", "Maturity"), mode: pick("Who answers its questions", "Mode") };
  const profile = h("select", { "aria-label": L.profile, disabled: !may || null, "data-key": key + ":profile" }, profiles.map((p) => h("option", { value: p.id, selected: p.id === c.profile }, p.label)));
  const maturity = h("select", { "aria-label": L.maturity, disabled: !may || null, "data-key": key + ":maturity" }, Object.keys(S.meta.maturities).map((m) => h("option", { value: m, selected: m === c.maturity }, ambitionWord(m))));
  const mode = h("select", { "aria-label": L.mode, disabled: !may || null, "data-key": key + ":mode" }, Object.keys(S.meta.modes).map((m) => h("option", { value: m, selected: m === c.mode }, modeWord(m))));
  const reason = h("input", { maxlength: "2000", placeholder: "Reason (recorded with your decision)", "aria-label": "Reason", "data-key": key + ":reason" });
  const p = profileOf(c.profile);
  const box = h("article", { class: "concept", id: "concept-" + c.card, "data-id": c.card },
    h("div", { class: "concept-h" }, h("span", { class: "cat-ic" }, icon(p.icon || "globe")),
      h("div", null, h("b", null, c.title), h("div", { class: "sig-m" }, h("span", { class: "mono" }, c.card), h("span", null, "from " + (c.signal || "?")),
        c.raised_by ? h("span", null, "raised by " + c.raised_by) : null, h("span", null, ago(c.created))))),
    h("p", { class: "concept-t" }, c.text || c.body || ""),
    (c.profile_basis || []).length ? h("p", { class: "muted small" }, pick("Suggested type (from the words ", "Profile proposed by rule from: "),
      (c.profile_basis || []).join(", "), pick(")", "")) : null,
    h("div", { class: "concept-f" },
      h("div", { class: "field" }, h("label", null, "Title"), title),
      h("div", { class: "field" }, h("label", null, L.profile), profile),
      h("div", { class: "field" }, h("label", null, L.maturity), maturity),
      h("div", { class: "field" }, h("label", null, L.mode), mode)));
  if (!may) {
    box.append(h("p", { class: "muted small" }, icon("user"), " A " + ((S.meta && S.meta.concept_editors) || []).map(personaLabel).join(" or ") + " validates, parks or rejects it."));
    return box;
  }
  // Only the fields the person changed are sent, so the record names exactly what was edited.
  const edits = () => {
    const now = { title: title.value.trim(), profile: profile.value, maturity: maturity.value, mode: mode.value };
    return Object.fromEntries(Object.entries(now).filter(([k, v]) => v && v !== (c[k] || "")));
  };
  const save = button("Save the edit", { icon: "edit", kind: "small", key: key + ":save" });
  save.addEventListener("click", () => {
    const changed = edits();
    if (!Object.keys(changed).length) { say("Nothing in " + c.card + " has changed yet.", "info"); return; }
    if (!needPerson()) return;
    const names = Object.keys(changed).join(", ");
    actKeep(box, save, async () => {
      await api("POST", "/api/concepts/" + enc(c.card) + "/edit", Object.assign({}, changed, signed()));
      say(c.card + " is edited (" + names + "), signed by " + S.person.trim() + ".", "good");
      S.focusNext = '[data-key="' + CSS.escape(key + ":save") + '"]';   // a button in flight is disabled, so it lost the focus
      await nav.rerender();
    });
  });
  const decide = (verdict, control) => {
    // Parking or rejecting a need says why, to the person who raised it.
    if (verdict !== "validate" && !reason.value.trim()) {
      say("Say why you " + (verdict === "park" ? "park " : "reject ") + c.card + ": the reason is recorded with your decision.", "warning");
      reason.focus();
      return;
    }
    if (!needPerson()) return;
    actKeep(box, control, async () => {
      const changed = edits();
      if (Object.keys(changed).length) {
        await api("POST", "/api/concepts/" + enc(c.card) + "/edit", Object.assign({}, changed, signed()));
      }
      const out = await api("POST", "/api/projects/" + FACTORY_PID + "/cards/" + enc(c.card) + "/decide",
        Object.assign({ verdict, reason: reason.value.trim() }, signed()));
      // A validated concept is a project at once; its intake runs from the need on its first Advance.
      say(c.card + ": " + (VERDICT_LABEL[verdict] || verdict) + ", signed by " + S.person.trim() + "."
        + (out.project ? " It is now project " + out.project + ". Its intake runs from the need when someone presses Advance." : ""), "good");
      if (out.project) {
        S.jumped = true;                  // the new project's heading takes the focus once it is shown
        location.hash = "#/p/" + enc(out.project) + "/overview";
        return;
      }
      // the card leaves the square: the next concept, or the list's heading, takes the focus
      const next = box.nextElementSibling || box.previousElementSibling;
      S.focusNext = next && next.dataset.id ? '[data-key="' + CSS.escape("concept:" + next.dataset.id + ":title") + '"]' : "#concepts-h";
      await nav.rerender();
    });
  };
  const verdictButton = (label, verdict, opts) => {
    const b = button(label, Object.assign({ key: "concept:" + c.card + ":" + verdict }, opts));
    b.addEventListener("click", () => decide(verdict, b));
    return b;
  };
  box.append(h("div", { class: "field" }, reason), h("div", { class: "btns", role: "group", "aria-label": "Decide " + c.card },
    verdictButton("Validate", "validate", { icon: "check", kind: "small primary", "data-control": "validate_concept" }),
    verdictButton("Park", "park", { icon: "pause", kind: "small" }),
    verdictButton("Reject", "reject", { icon: "x", kind: "small" }), save));
  return box;
}

// The square lists every new signal and the newest others; a person may ask for every signal.
let SQ_EVERY = false;
// The signals triaged on this page, newest last: they stay listed though they are no longer new.
const SQ_SHOWN = new Set();
const SQ_SHOWN_MAX = 20;          // the server lists at most this many named signals (SQUARE_SHOWN)

// A link to #/square/<card> brings that concept into view and gives it the focus, once: the address
// then drops the id, so a later re-render keeps the person's own place.
function focusConcept(main) {
  const m = /^#\/square\/([^/?#]+)/.exec(location.hash || "");
  if (!m) return;
  let id = m[1];
  try { id = decodeURIComponent(id); } catch (e) { /* keep it as written */ }
  history.replaceState(null, "", "#/square");
  const el = main.querySelector('.concept[data-id="' + CSS.escape(id) + '"]');
  if (!el) { say(id + " no longer waits on the square: it was validated, parked or rejected.", "warning"); return; }
  el.classList.add("focused");
  el.setAttribute("tabindex", "-1");
  el.scrollIntoView({ block: "center" });
  el.focus({ preventScroll: true });
}

export async function renderSquare(seq) {
  const main = $("#main");
  const ask = SQ_EVERY ? "?signals=all" : SQ_SHOWN.size ? "?show=" + enc([...SQ_SHOWN].join(",")) : "";
  const [all] = await loaded(main, "the delivery square", () => Promise.all([api("GET", "/api/square" + ask),
    S.projects ? Promise.resolve(S.projects) : api("GET", "/api/projects").then((p) => { S.projects = p; return p; })]));
  if (seq !== S.seq) return;
  // All projects, or one: the scope switch at the top (square.js, FR-UXO1).
  const pidNow = (S.projects || []).some((p) => p.id === squarePid()) ? squarePid() : "";
  const sc = squareScope(all, pidNow);
  const sq = sc.sq;
  document.title = "Delivery square · " + (pidNow ? ((S.projects || []).find((p) => p.id === pidNow) || {}).title : "all projects") + " · Rihmasto.ai";
  const listed = sq.signals_list || [];
  const counts = sq.signals || { new: listed.filter((s) => s.state === "new").length, total: listed.length };
  const pipe = WIDGET_DEFS.pipeline.render({ pipeline: sq.pipeline }, { size: "L" });
  // Every new signal is always listed, and the ones triaged here; older ones beyond the newest may be asked for.
  const kept = sq.signals_shown || [];
  const more = sq.signals_all && !SQ_EVERY ? null
    : h("p", { class: "muted small sig-more" }, SQ_EVERY ? "Every signal is listed. " : "Listed: every new signal, the newest others"
      + (kept.length ? " and " + (kept.length === 1 ? kept[0] + ", which you triaged here" : "the " + kept.length + " you triaged here (" + kept.join(", ") + ")") : "")
      + ", " + listed.length + " of " + counts.total + ". ",
    button(SQ_EVERY ? "Show the newest only" : "Show every signal", { kind: "small quiet", key: "signals:toggle",
      onclick: () => { SQ_EVERY = !SQ_EVERY; nav.rerender(); } }));
  const open = sq.end_user_feedback_open;
  const untriaged = typeof sq.end_user_feedback_untriaged === "number" ? sq.end_user_feedback_untriaged : null;
  fill(main,
    pageHead("Delivery square", word("square.lede") + ". A need arrives, a person validates it, Rihma builds it, end users test it, and it runs in production; feedback loops back.",
      { icon: "square", actions: [scopeSwitch(pidNow, (v) => { setSquarePid(v); nav.rerender(); }),
        button(pick("Log a request", "Log a signal"), { icon: "plus", kind: "primary", "data-control": "log_signal",
          onclick: () => { const t = $("#log-signal textarea"); if (t) { t.scrollIntoView({ block: "center" }); t.focus(); } } })] }),
    scopeLine(sc),
    squareLanes(sc),
    pidNow ? null : card({ title: "The square at a glance", icon: "square", cls: "sq-card", info: "The delivery square (toimitusneliö): four corners around one canon. "
      + "Every arrow is a hand-over with a person who decides." }, namePeopleOnMap(squareDiagram(sq, { people: sq.people }), sq.people)),
    h("div", { class: "sq-cols" },
      card({ title: pick("New requests", "Needs arrive"), icon: "signal", id: "needs", tools: [h("span", { class: "muted small" }, counts.new + " new · " + plural(counts.total, pick("request", "signal")) + pick(" in total", "")),
        people(sq.people.needs, "who raised needs")],
      info: "A signal is a need as it arrived: a chat, a data feed, a monitoring alert, a meeting, the website chat. Triage needs no model: "
          + "a signal about an existing project becomes a change on it; a new need becomes a concept for a business owner or product owner." },
      signalForm(sq),
      listed.length ? h("ul", { class: "sig-list" }, listed.map(signalRow)) : empty("signal", "No signal yet."), more),
      card({ title: pick("New ideas to approve", "Concepts to validate"), icon: "lightbulb", id: "concepts", tools: [people(sq.people.concept, "who decide concepts")],
        info: "Nothing becomes a project without a person's decision. Edit the title, profile, maturity and mode, then validate, park or reject." },
      (sq.concepts || []).length ? h("div", { class: "concepts" }, sq.concepts.map(conceptCard))
        : empty("lightbulb", pidNow ? "Concepts are not a project yet: switch to All projects to see them." : "No concept waits. A new need that fits no project appears here once it is triaged."))),
    card({ title: "Being built", icon: "factory", id: "factory", tools: [people(sq.people.factory, "who build")], info: pick("Projects per step, from the first request to live.", "Projects per stage, in four bands: Decide, Shape, Deliver, Run.") }, pipe),
    h("div", { class: "sq-cols" },
      card({ title: pick("People try it", "End users test"), icon: "users", id: "testing", tools: [
        typeof open === "number" ? h("span", { class: "muted small" }, technical() ? open + " open" + (untriaged === null ? "" : " · " + untriaged + " not triaged")
          : open ? plural(open, "piece") + " of feedback waiting for a decision" + (untriaged ? " (" + untriaged + " not sorted yet)" : "") : "No feedback waiting") : null,
        people(sq.people.testing, "who test")], info: "What end users report comes back as a change, triaged to the stage that can fix it. "
        + "It never goes straight to code. Every open report waits: a triaged one on a decision, one not triaged yet for its class. "
        + "The corner above counts them all." },
      (sq.feedback || []).length ? h("ul", { class: "fb-list" }, sq.feedback.map((f) => h("li", { class: "fb-row" },
        avatar(f.person || "?"), h("div", { class: "sig-b" }, h("a", { href: link(f.project, "changes", f.card) }, cardTitleEl(f.title)),
          h("div", { class: "sig-m" }, h("span", null, f.project_title), h("span", { class: "mono" }, f.card), f.person ? h("span", null, f.person) : null, h("span", null, ago(f.created)))),
        f.state === "open" ? (f.triaged ? chip("warning", "clock", "Waits on a decision") : chip("warning", "dashed", pick("Not sorted yet", "Not triaged"))) : chip("good", "check", cap(f.state)))))
        : empty("users", "No end-user feedback yet. A feedback embed or the Try it checklist files it.")),
      card({ title: "In production", icon: "server", id: "production", tools: [people(sq.people.production, "who run production")], info: "What runs in production, with DevOps, maintenance, security and compliance around it." },
        (sq.production || []).length ? h("ul", { class: "live-list" }, sq.production.map((p) => h("li", { class: "live-row" },
          h("span", { class: "cat-ic" }, icon(profileOf(p.profile).icon)), h("div", { class: "live-b" }, h("a", { href: "#/p/" + enc(p.project) }, p.title),
            h("div", { class: "live-m" }, nowSaid((p.now || {}).line))), nowChip(p.now, p.project))))
          : h("div", null, empty("server", pick("Nothing is live yet. Projects appear here once they are live.", "Nothing runs in production yet. A release at stage 7 appears here.")),
            h("ul", { class: "ops-list" }, (technical() ? [["shield", "Security", "CVEs and drift arrive as updates"], ["activity", "Monitoring", "probes open incidents and new signals"],
              ["file-check", "Compliance", "evidence packs per release"], ["refresh", "Maintenance", "changes go back through the factory"]]
              : [["shield", "Security", "security fixes arrive as update offers"], ["activity", "Monitoring", "if a live service fails, an incident is opened for you"],
                ["file-check", "Compliance", "each release has a proof package for auditors"], ["refresh", "Maintenance", "changes go through the same checks again"]]).map(([ic, t, d]) =>
              h("li", null, icon(ic), h("b", null, t), h("span", { class: "muted small" }, d))))))));
  // where the focus goes when the last concept is decided, or when a signal's row cannot take it
  ["#concepts-h", "#needs-h"].forEach((sel) => { const el = $(sel, main); if (el) el.setAttribute("tabindex", "-1"); });
  focusConcept(main);
}

// -- the capability catalogue -------------------------------------------------------------------

const CAT = { state: "all", profile: "", deliverable: "", q: "" };
// What a capability delivers: its own, or its work profile's (a proposed agent is a capability pack).
function deliverableOf(i) { return i.deliverable || profileOf(i.profile).deliverable || "product"; }
// A capability pack as last built; a release without one says so, never "no release".
function packWords(i) {
  if (i.pack) {
    return technical() ? "v" + i.pack.version + (i.pack.valid ? " · valid" : " · not valid")
      : "release " + String(i.pack.version || "").replace(/\.0$/, "") + (i.pack.valid ? " ready to hand over" : ", not complete");
  }
  if (!i.project) return pick("an idea: not built", "a concept: not built");
  return i.latest_release ? pick("release " + i.latest_release + " not packaged yet", "not built yet for release " + i.latest_release) : pick("not released yet", "no release yet");
}
function catCard(it) {
  const el = catalogueCard(it);
  const words = !it.pack && it.project && it.latest_release ? el.querySelector(".cat-pack .muted") : null;
  if (words) words.textContent = pick("Release " + it.latest_release + " not packaged yet", "Pack not built yet for release " + it.latest_release);
  if (it.card && !it.project) el.setAttribute("href", conceptHref(it.card));
  return el;
}
export async function renderCatalogue(seq) {
  const main = $("#main");
  const cat = await loaded(main, "the catalogue", () => api("GET", "/api/catalogue"));
  if (seq !== S.seq) return;
  document.title = "Catalogue · Rihmasto.ai";
  const mode = viewChoice("catalogue", "cards");
  const items = cat.items.filter((i) => (CAT.state === "all" || i.state === CAT.state) && (!CAT.profile || i.profile === CAT.profile)
    && (!CAT.deliverable || deliverableOf(i) === CAT.deliverable)
    && (!CAT.q || (i.title + " " + (i.summary || "")).toLowerCase().includes(CAT.q.toLowerCase())));
  // A filter re-renders the page in place (nav.rerender): the control that was used keeps the focus.
  const refilter = () => nav.rerender();
  const lifecycle = ["proposed", "shaping", "building", "trying", "pilot", "in_use"];
  const strip = h("ol", { class: "lifecycle", "aria-label": "Capabilities by state, from proposed to in use" },
    h("li", null, h("button", { type: "button", class: "lc" + (CAT.state === "all" ? " on" : ""), "aria-pressed": String(CAT.state === "all"),
      "data-key": "lc:all", onclick: () => { CAT.state = "all"; refilter(); } }, h("span", { class: "lc-n" }, String(cat.items.length)), h("span", { class: "lc-l" }, icon("catalogue"), "All"))),
    lifecycle.map((s) => h("li", null, h("button", { type: "button", class: "lc" + (CAT.state === s ? " on" : "") + ((cat.counts[s] || 0) ? "" : " zero"),
      "aria-pressed": String(CAT.state === s), "data-key": "lc:" + s, onclick: () => { CAT.state = CAT.state === s ? "all" : s; refilter(); } },
    h("span", { class: "lc-n" }, String(cat.counts[s] || 0)), h("span", { class: "lc-l" }, icon(CATALOGUE_STATE[s].icon), CATALOGUE_STATE[s].word)))));
  // the filters in plain words; the engineering-only profile is a developer's (FR-UXO1 readers' review)
  const profSel = h("select", { "aria-label": pick("Type", "Work profile"), "data-key": "cat:profile" }, h("option", { value: "" }, pick("All types", "Every profile")),
    cat.profiles.filter((p) => technical() || !/harness/i.test(p.id + " " + p.label)).map((p) => h("option", { value: p.id, selected: p.id === CAT.profile }, p.label)));
  profSel.addEventListener("change", () => { CAT.profile = profSel.value; refilter(); });
  const DELIV = { capability_pack: "Reusable AI service", ops_agent: "Report agent" };
  const delSel = h("select", { "aria-label": pick("Result", "Deliverable"), "data-key": "cat:deliverable" }, h("option", { value: "" }, pick("All results", "Every deliverable")),
    Object.keys(cat.deliverables).map((d) => h("option", { value: d, selected: d === CAT.deliverable }, technical() ? cap(d.replace("_", " ")) : DELIV[d] || cap(d.replace(/_/g, " ")))));
  delSel.addEventListener("change", () => { CAT.deliverable = delSel.value; refilter(); });
  const q = h("input", { type: "search", value: CAT.q, placeholder: "Search capabilities", "aria-label": "Search capabilities", "data-key": "cat:q" });
  q.addEventListener("change", () => { CAT.q = q.value.trim(); refilter(); });
  fill(main,
    pageHead(pick("What we have built", "Capability catalogue"), pick("The agents and products we have, live, being tried or proposed, what each one does, and whether it is released.",
      "Which agents and products we have, in use, in pilot or proposed, what each one does, and whether its pack is valid."), { icon: "catalogue",
      actions: [button("New project", { icon: "plus", kind: "primary", onclick: () => newProjectModal() })] }),
    strip,
    h("div", { class: "filters" }, profSel, delSel, q, h("span", { class: "spacer" }),
      segmented("cat-view", [["cards", "Cards", "catalogue"], ["table", "Table", "table"]], mode, (v) => { setViewChoice("catalogue", v); refilter(); }, { label: "View", iconOnly: true })),
    !items.length ? empty("catalogue", cat.items.length ? "No capability matches these filters." : "No capability yet. A validated concept or a new project starts one.")
      : mode === "table" ? dataTable([{ label: "Capability", value: (r) => h("a", { href: r.project ? "#/p/" + enc(r.project) : r.card ? conceptHref(r.card) : "#/square" }, r.title) },
        { label: "State", value: (r) => { const st = catalogueState(r); return chip(st.tone, st.icon, st.word); } },
        { label: "Profile", value: (r) => profileChip(r.profile, { short: true }) }, { label: "Deliverable", value: (r) => cap(deliverableOf(r).replace("_", " ")) },
        { label: "Stage", value: (r) => (r.stage ? r.stage + " of 7" : "concept") }, { label: "Maturity", value: (r) => r.maturity || "-" },
        { label: pick("Released", "Pack"), value: packWords }], items, "Capabilities")
        : h("div", { class: "cat-grid wide" }, items.map(catCard)),
    technical() ? h("p", { class: "muted small foot-note" }, icon("package"),
      " A capability pack names everything a release delivered by its hash, with its evals; it is valid only while they hold.") : null);
}

// -- projects -----------------------------------------------------------------------------------

function projectNow(p) {
  const st = liveState({ live: { running: p.running }, now: p.now, last_cell: p.last_cell });
  if (p.factory) return chip("neutral", "sparkles", "Proposals");
  return chip(st.tone, st.icon, st.word, { tip: nowSaid((p.now || {}).line) });
}
function miniStages(stage) {
  return h("span", { class: "mini-steps", "aria-label": "Stage " + stage + " of 7" }, [1, 2, 3, 4, 5, 6, 7].map((n) =>
    h("span", { class: "ms " + (n < stage ? "done" : n === stage ? "now" : "ahead") })));
}
const FACTORY_LINE = "Ideas not yet part of a project. Approve them to start one.";
// A project's settings as words: "quick try-out · Rihma assumes, you confirm" for a business reader.
const PAGES_LABEL = () => pick("Flow of work", "the Square");
function settingsWords(p) { return technical() ? p.maturity + " · " + p.mode : cap(ambitionWord(p.maturity)) + " · " + modeWord(p.mode); }
export async function renderProjectsPage(seq) {
  const main = $("#main");
  const projects = await loaded(main, "projects", () => api("GET", "/api/projects"));
  if (seq !== S.seq) return;
  S.projects = projects;
  document.title = "Projects · Rihmasto.ai";
  const mode = viewChoice("projects", "cards");
  const mineOf = (p) => Object.entries(p.open_by_kind || {}).reduce((n, [k, c]) => n + (decides(k) ? c : 0), 0);
  const shown = projects.filter((p) => !S.onlyWaiting || mineOf(p) > 0);
  const products = projects.filter((p) => !p.factory);
  const filter = h("label", { class: "check" }, h("input", { type: "checkbox", checked: S.onlyWaiting, "data-key": "onlywaiting",
    onchange: (e) => { S.onlyWaiting = e.target.checked; nav.rerender(); } }), "Only projects waiting on you");
  const cards = h("div", { class: "proj-grid" }, shown.map((p) => {
    const mine = mineOf(p);
    const prof = profileOf(p.profile);
    return h("a", { class: "proj-card" + (p.factory ? " factory" : ""), href: p.factory ? link(p.id, "inbox") : "#/p/" + enc(p.id) },
      h("div", { class: "pc-top" }, h("span", { class: "cat-ic" }, icon(p.factory ? "sparkles" : prof.icon || "globe")), projectNow(p)),
      h("b", { class: "pc-t" }, titleOf(p.factory ? FACTORY_PID : p.id, p.title)),
      h("p", { class: "pc-now", "data-ud": "" }, p.factory ? FACTORY_LINE : nowSaid((p.now || {}).line)),
      p.factory ? null : h("div", { class: "pc-stage" }, miniStages(p.stage), h("span", { class: "muted small" }, pick("Step ", "Stage ") + p.stage + " · " + stageWord(p.stage, cap(p.stage_name)))),
      h("div", { class: "pc-foot" }, p.factory ? null : h("span", null, settingsWords(p)),
        mine ? chip("warning", "user", plural(mine, "decision") + " for you") : h("span", { class: "muted" }, "Nothing for you"),
        p.stale_approvals ? chip("warning", "alert", p.stale_approvals + pick(" out of date", " stale")) : null));
  }));
  const table = dataTable([{ label: "Project", value: (p) => h("a", { href: p.factory ? link(p.id, "inbox") : "#/p/" + enc(p.id) }, titleOf(p.factory ? FACTORY_PID : p.id, p.title)) },
    { label: "Now", value: (p) => h("span", { class: "cell-now" }, projectNow(p), h("small", { class: "muted" }, p.factory ? FACTORY_LINE : nowSaid((p.now || {}).line))) },
    { label: pick("Step", "Stage"), value: (p) => (p.factory ? "-" : p.stage + " " + stageWord(p.stage, cap(p.stage_name))) }, { label: "Profile", value: (p) => (p.factory ? "-" : profileChip(p.profile, { short: true, noPreview: true })) },
    { label: pick("Goal · who answers", "Maturity · mode"), value: (p) => (p.factory ? "-" : settingsWords(p)) },
    { label: "Yours to decide", value: (p) => mineOf(p), num: true }, { label: "Open cards", key: "open_cards", num: true }], shown, "Projects");
  fill(main,
    pageHead("Projects", plural(products.length, "project") + ", each from the first request to the live service.",
      { icon: "folder", actions: [moduleShows("controls", "new_project") ? button("New project", { icon: "plus", kind: "primary", "data-control": "new_project", onclick: () => newProjectModal() }) : null] }),
    h("div", { class: "filters" }, filter, h("span", { class: "spacer" }),
      segmented("proj-view", [["cards", "Cards", "catalogue"], ["table", "Table", "table"]], mode, (v) => { setViewChoice("projects", v); nav.rerender(); }, { label: "View", iconOnly: true })),
    !products.length ? h("div", { class: "card intro" }, empty("folder", "No project yet. Rihma turns a business need into a running, monitored service.",
      button("Start your first project", { icon: "plus", kind: "primary", onclick: () => newProjectModal() })),
      nav.journey ? nav.journey.starters("projects") : null)   // the three ways in, guided (FR-JRN1)
      : !shown.length ? empty("check-circle", "No project waits on you right now.") : mode === "table" ? table : cards,
    archivedSection());   // archived projects and duplicates: restore, remove (setup.js, FR-SET1)
}

// -- the Inbox across projects ------------------------------------------------------------------

// Every card is named by its project and its id here: card ids repeat across projects (each project
// counts its own), so a key or an element id made from the card id alone would point at another card.
function ibKey(c) { return "ib-" + c.project + "-" + c.id; }
// The reasons people typed and have not sent yet, per project and card: a decision on one card
// re-renders the Inbox, and no one else's draft is lost with it.
const DRAFTS = new Map();
// A card that accepts a release (an approval of a demo, a validation) carries the release link and the
// checklist to try it with, as in the project's own Inbox.
function acceptsRelease(c) {
  return c.kind === "validation" || (c.kind === "approval" && /^Accept the demo/.test(String(c.title || "")));
}
// Where the focus goes once a card is decided and leaves the Inbox: the next card, or the page heading.
function focusAfter(article) {
  const all = $$(".inbox-card", $("#main"));
  const i = all.indexOf(article);
  const next = all[i + 1] || all[i - 1];
  const target = next ? next.querySelector('.dc-opt[data-key], [data-key$=":open"]') : null;
  return target ? '[data-key="' + CSS.escape(target.dataset.key) + '"]' : "#view-title";
}

// The choices with their meanings, Why and Confirm once one is picked (decide.js).
function inboxDecide(c) {
  const k = ibKey(c);
  let form = null;
  form = decideBlock(c, { key: k, reasonId: k + "-reason",
    draft: { get: () => DRAFTS.get(k), set: (v) => { if (v) DRAFTS.set(k, v); else DRAFTS.delete(k); } },
    decide: (v, reason, b) => actKeep(form, b, async () => {
      const out = await api("POST", "/api/projects/" + enc(c.project) + "/cards/" + enc(c.id) + "/decide",
        Object.assign({ verdict: v, reason }, signed(), c.decide_as ? { persona: c.decide_as } : {}));   // the persona it needs (FR-PPL1)
      DRAFTS.delete(k);
      say(c.project_title + ": " + (VERDICT_LABEL[v] || v) + (reason ? " (" + reason + ")" : "") + ", signed by " + S.person.trim() + " as "
        + personaLabel((out && out.decision && out.decision.persona) || S.persona) + "." + (out && out.project ? " It is now project " + out.project + "." : ""), "good");
      S.focusNext = focusAfter(form.closest(".inbox-card"));
      await nav.rerender();
    }) });
  return form;
}

function inboxCard(c, tries) {
  const isPlan = c.kind === "approval" && (c.refs || {}).scope === "plan";
  const pl = c.payload || {};
  const k = ibKey(c);
  const body = [];
  // what the checks said on a failed task or release is for a technical reader: folded under Details for anyone else
  const folded = !technical() && ["escalation", "holdout_ruling"].includes(c.kind);
  const said = c.body && c.body.trim() !== c.title.trim() ? h("p", { class: "body" }, cardTitle(c.body).text) : null;
  if (c.kind === "update" && pl.views) {
    const v = pl.views;
    body.push(S.lens === "delivery" || S.lens === "insight" ? h("pre", { class: "json" }, JSON.stringify(v.developer, null, 2))
      : h("p", null, S.lens === "business" ? v.business : v.expert));
  } else if (said && !folded) body.push(said);
  if (c.kind === "concept") body.push(h("p", { class: "muted small" }, profileChip(pl.profile), " · ", ambitionWord(pl.maturity), " · ",
    technical() ? pl.mode : "questions answered by " + modeWord(pl.mode), " · " + pick("change these on ", "edit it on the "),
    h("a", { href: conceptHref(c.id) }, PAGES_LABEL())));
  let action;
  if (c.kind === "question") action = h("a", { class: "btn small", href: link(c.project, "questions", (c.refs || {}).question), "data-control": "answer", "data-key": k + ":open" }, icon("comment"), "Answer the question");
  else if (isPlan) action = h("a", { class: "btn small primary", href: link(c.project, "plan"), "data-key": k + ":open" }, icon("arrow-right"), "Open the plan to approve it");
  else if (c.kind === "concept") action = h("a", { class: "btn small", href: conceptHref(c.id), "data-key": k + ":open" }, icon("square"),
    pick("Approve, park or reject it on " + PAGES_LABEL(), "Validate it on the Square"));
  else action = inboxDecide(c);
  const tryIt = acceptsRelease(c) && !isPlan
    ? h("section", { class: "trybox", "aria-label": "Try release " + (pl.release || "") + " before you decide" },
      h("span", { class: "label" }, "Try it before you decide"),
      tryPanel(c.project, tries[c.project] || null, { where: k, url: pl.url }))
    : null;
  const where = INBOX.group === "project" ? null
    : h("a", { class: "small ib-proj", href: c.project === FACTORY_PID ? link(c.project, "inbox") : "#/p/" + enc(c.project) }, icon("folder"), titleOf(c.project, c.project_title));
  return h("article", { class: "card decision inbox-card", "data-id": c.id, "data-project": c.project, "aria-labelledby": k + "-h" },
    cardTop(c, k + "-h", { icon: KIND_ICON[c.kind], project: where }),
    c.blocking || c.decide_as ? h("p", { class: "ib-flags" }, c.blocking ? chip("warning", "alert", "Blocking work") : null,
      c.decide_as ? chip("info", "user", "You decide as " + personaLabel(c.decide_as).toLowerCase(), { class: "chip info ib-as" }) : null) : null,
    body,
    c.kind === "change" && impactPanelFor ? impactPanelFor(c.project, c, !technical()) : null, tryIt, action,
    commentRow(() => openThread(c.project, { kind: "card", id: c.id }, [])),
    details(c, folded && said ? [h("p", { class: "label" }, "What the checks said"), said] : null));
}
const INBOX = { group: "project" };

// Decisions that hold work up first (an escalation, a holdout that blocks a release, the approvals and
// gates, the roads and trust a deploy waits on), then changes, updates to try and concepts, and the
// panel's many questions last. Within a group a blocking card comes first, then the oldest.
const INBOX_ORDER = ["escalation", "holdout_ruling", "approval", "go_ahead", "validation", "deploy_gate", "incident", "road", "trust", "runner",
  "change", "update", "concept", "question"];

export async function renderInboxAll(seq) {
  const main = $("#main");
  const [inbox, tries] = await loaded(main, "the Inbox", async () => {
    const box = await api("GET", "/api/inbox?persona=" + enc(inboxPersona()));
    // the checklist for each project with a card that accepts a release, read once per project
    const pids = [...new Set(box.cards.filter(acceptsRelease).map((c) => c.project))];
    const read = await Promise.all(pids.map((pid) => api("GET", "/api/projects/" + enc(pid) + "/try").catch((e) => {
      if (e instanceof AuthError) throw e;
      return null;
    })));
    return [box, Object.fromEntries(pids.map((pid, i) => [pid, read[i]]))];
  });
  if (seq !== S.seq) return;
  document.title = "Inbox · all projects · Rihmasto.ai";
  S.inboxCount = inbox.count;
  // By project first: the project is each group's heading, so no card is read without its project (FR-UXO1).
  const group = viewChoice("inbox2", "project");
  INBOX.group = group;
  const groups = {};
  const keyOf = (c) => {
    if (group === "project") return titleOf(c.project, c.project_title);
    if (group === "age") {
      const hrs = c.created ? (Date.now() - Date.parse(c.created)) / 3600000 : 0;
      return hrs < 24 ? "Today" : hrs < 24 * 7 ? "This week" : "Older";
    }
    return KIND_LABEL[c.kind] || c.kind;
  };
  const rank = (c) => (group === "kind" ? (INBOX_ORDER.indexOf(c.kind) + 1 || INBOX_ORDER.length + 1) : 0);
  const shownCards = everything() && S.inboxAs ? inbox.cards.filter((c) => c.decide_as === S.inboxAs) : inbox.cards;
  shownCards.slice().sort((a, b) => rank(a) - rank(b) || Number(!!b.blocking) - Number(!!a.blocking)
    || String(a.created || "").localeCompare(String(b.created || "")))
    .forEach((c) => { (groups[keyOf(c)] = groups[keyOf(c)] || []).push(c); });
  const head = (g, cs) => {
    if (group !== "project") return h("h2", { class: "ib-h" }, g, h("span", { class: "count" }, String(cs.length)));
    const pid = cs[0].project;
    return h("h2", { class: "ib-h ib-ph" }, h("span", { class: "ib-dot", "data-hue": String(projectHue(pid)) }),
      h("a", { href: link(pid, "inbox"), "data-key": "ibp:" + pid, tip: "Open this project's Inbox" }, g),
      h("span", { class: "count", "aria-label": plural(cs.length, "card") + " waiting on you" }, String(cs.length)));
  };
  fill(main,
    pageHead("Inbox", word("inbox.lede") + (everything()
      ? " Every card you may decide in any persona you hold, across every project; each is signed with the persona it needs."
      : " Across every project and the new ideas not yet in one, as " + personaLabel(S.persona) + "."), { icon: "inbox" }),
    everything() ? inboxPersonaFilter(inbox.cards) : null, elsewhereNote(inbox.elsewhere),   // another role held (FR-ENF2)
    heldAll(S.projects),   // required answers that hold delivery, across projects (hitl_held.js, FR-HITL2)
    h("div", { class: "filters" }, h("span", { class: "muted" }, plural(inbox.count, "decision") + (inbox.count === 1 ? " waits" : " wait") + " for you"), h("span", { class: "spacer" }),
      segmented("inbox-group", [["project", "By project"], ["kind", "By kind"], ["age", "By age"]], group, (v) => { setViewChoice("inbox2", v); nav.rerender(); }, { label: "Group the cards" })),
    shownCards.length ? Object.entries(groups).map(([g, cs]) => h("section", { class: "ib-group", "data-cz": "ib-" + slugOf(g) }, head(g, cs),
      h("div", { class: "cards" }, cs.map((c) => inboxCard(c, tries)))))
      : empty("check-circle", word("inbox.empty")));
  $$(".ib-dot", main).forEach((d) => d.style.setProperty("--proj-h", d.dataset.hue));
}
function slugOf(s) { return String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40); }

// -- settings: embeds, appearance, sign-in -------------------------------------------------------

function embedCreators() {
  const ids = (S.meta && S.meta.embed_creators) || [];
  const words = ids.map(personaLabel);
  return words.length > 1 ? words.slice(0, -1).join(", ") + " or " + words[words.length - 1] : words.join("");
}
// After the key box closes, the focus goes back to Create a chat (the page re-rendered under the
// dialog, so the button that opened it is a new one), else to where the form was opened from.
function backToOpener(opener) {
  const create = $('[data-key="create-embed"]');
  const to = create || (opener && opener.isConnected ? opener : $("#view-title"));
  if (to && typeof to.focus === "function") to.focus();
}

export function openEmbedForm(prefill) {
  const pf = prefill || {};
  const opener = document.activeElement;
  const may = mayAct((S.meta && S.meta.embed_creators) || []);
  const kinds = h("div", { class: "seg" }, ["feedback", "need"].map((k) => h("label", { class: "seg-b radio" },
    h("input", { type: "radio", name: "em-kind", value: k, checked: (pf.kind || "feedback") === k }), k === "feedback" ? "Feedback on a product" : "A business need")));
  // Feedback is on a product: Rihma itself is never offered. A proposed project the list does not hold
  // (Rihma itself, or one that is gone) is said plainly, and nothing is chosen in its place.
  const products = (S.projects || []).filter((p) => !p.factory);
  const listed = !pf.project || products.some((p) => p.id === pf.project);
  const project = h("select", { "aria-label": "Project", id: "em-project" },
    listed && products.length ? null : h("option", { value: "", selected: true }, products.length ? "Choose a product" : "No product yet"),
    products.map((p) => h("option", { value: p.id, selected: listed && p.id === pf.project }, p.title)));
  const unlisted = listed ? null : h("p", { class: "note warning", id: "em-project-note" }, icon("alert"), h("span", null,
    pf.project === FACTORY_PID || String(pf.project).startsWith("_")
      ? "Rihma itself takes no website feedback. Choose the product the feedback is about."
      : "The proposed project " + pf.project + " is not one of the products. Choose the product the feedback is about."));
  if (unlisted) project.setAttribute("aria-describedby", "em-project-note");
  const origins = h("textarea", { rows: "2", placeholder: "https://shop.example.fi", "aria-label": "Allowed websites" }, pf.origins || "");
  const label = h("input", { maxlength: "80", value: pf.label || "", placeholder: "Shop feedback", "aria-label": "Label" });
  const brief = h("textarea", { rows: "2", maxlength: "600", placeholder: "One or two sentences the chat may say about the product", "aria-label": "Public brief" }, pf.brief || "");
  const form = h("form", { class: "embed-form", novalidate: true },
    h("p", { class: "note" }, icon("shield"), h("span", null, "The chat sees nothing of the project's records. It can only file feedback as a change, or a need as a signal.")),
    h("fieldset", null, h("legend", null, "What it collects"), kinds),
    h("div", { class: "field" }, h("label", { for: "em-project" }, "Project (for feedback)"), project, unlisted),
    h("div", { class: "field" }, h("label", null, "Allowed websites, one per line"), origins),
    h("div", { class: "row2" }, h("div", { class: "field" }, h("label", null, "Label"), label), h("div", { class: "field" }, h("label", null, "Public brief"), brief)),
    h("div", { class: "btns" }, h("button", { type: "submit", class: "btn primary", "data-control": "create_embed", disabled: !may || null }, icon("message-square"), "Create the chat"),
      may ? h("span", { class: "muted small" }, "Signed with your name. The key is shown once.") : h("span", { class: "muted small" }, "A " + embedCreators() + " creates an embed.")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const kind = form.querySelector("input[name=em-kind]:checked").value;
    if (kind === "feedback" && !project.value) { say("Choose the product the feedback is about.", "warning"); project.focus(); return; }
    if (!needPerson()) return;
    actKeep(form, form.querySelector('button[type="submit"]'), async () => {
      const out = await api("POST", "/api/embeds", Object.assign({ kind, project: kind === "feedback" ? project.value : null,
        origins: origins.value.split(/[\s,]+/).filter(Boolean), label: label.value.trim(), brief: brief.value.trim() }, signed()));
      say("Chat " + out.embed.id + " is created. Copy its key now: it is shown once.", "good");   // replaces an earlier refusal
      showKey(out, () => backToOpener(opener));
      if (S.route && S.route.name === "settings") nav.route(true);
    });
  });
  openModal("A chat window for a website", form, { icon: "message-square" });
}

function masked(key) { return key.slice(0, 3) + "•".repeat(Math.max(8, key.length - 3)); }
// Where a snippet points: the embed server (configured with --embed-base or RIHMA_EMBED_BASE), never the
// cockpit, which stays on loopback and serves no widget. Unset, it is the local embed server, for testing.
function embedBaseNote(info) {
  if (info.embed_base) {
    return h("p", { class: "note" }, icon("link"), h("span", null, "Snippets point at the embed server, ", h("code", null, info.embed_base),
      ". A website never reaches the cockpit."));
  }
  return h("p", { class: "note warning" }, icon("alert"), h("span", null, h("b", null, "No embed server address is set. "),
    "Snippets point at the local embed server, ", h("code", null, info.embed_base_local || "http://127.0.0.1:8790"),
    ", which only this machine reaches: for testing. For a website, start the cockpit with ", h("code", null, "--embed-base https://…"),
    " or set ", h("code", null, info.embed_base_env || "RIHMA_EMBED_BASE"), "."));
}
function showKey(out, onClose) {
  let shown = false;
  const keyEl = h("code", { class: "key" }, masked(out.key));
  const snip = h("pre", { class: "code snippet" }, out.snippet.replace(out.key, masked(out.key)));
  const reveal = button("Show", { icon: "eye", kind: "small quiet" });
  reveal.addEventListener("click", () => {
    shown = !shown;
    keyEl.textContent = shown ? out.key : masked(out.key);
    snip.textContent = shown ? out.snippet : out.snippet.replace(out.key, masked(out.key));
    reveal.querySelector(".lbl").textContent = shown ? "Hide" : "Show";
  });
  const copy = (text, what) => async () => {
    try { await navigator.clipboard.writeText(text); say(what + " copied.", "good"); } catch (e) { say("Copy it by hand.", "warning"); }
  };
  openModal("Chat " + out.embed.id + " is ready", h("div", { class: "key-box" },
    h("p", { class: "note warning" }, icon("key"), h("span", null, h("b", null, "This key is shown once. "), "Only its hash is kept; it cannot be shown again.")),
    h("div", { class: "key-row" }, keyEl, reveal, button("Copy the key", { icon: "copy", kind: "small", onclick: copy(out.key, "The key") })),
    h("p", { class: "muted small" }, "Paste this into the website's page:"), snip, embedBaseNote(out),
    h("div", { class: "btns" }, button("Copy the snippet", { icon: "code", kind: "primary", onclick: copy(out.snippet, "The snippet") }),
      button("Done", { kind: "quiet", onclick: () => closeModal() })),
    h("p", { class: "muted small" }, "Allowed: " + out.embed.origins.join(", ") + ". Revoke it any time in Settings.")), { icon: "check-circle", onClose });
}

// A theme change from Settings: applied at once and saved with the layout of the lens in view. When the
// save is refused or fails, the person is told; the change stays in this browser.
function changeTheme(changes) {
  setTheme(changes).catch((e) => {
    if (!(e instanceof AuthError)) say("Shown in this browser, but not saved with your layout: " + e.message, "critical");
  });
}
// The accent swatches: a radiogroup with one tab stop; the arrow keys move and choose, as in every
// segmented control. Choosing re-renders nothing, so the focus stays on the swatch.
function accentSwatches(current) {
  const group = h("div", { class: "swatches", role: "radiogroup", "aria-label": "Accent" });
  const pick = (b, a, focus) => {
    $$(".swatch", group).forEach((x) => { x.setAttribute("aria-checked", String(x === b)); x.tabIndex = x === b ? 0 : -1; });
    if (focus) b.focus();
    changeTheme({ accent: a });
  };
  ACCENTS.forEach((a) => {
    const on = current === a || (!ACCENTS.includes(current) && a === ACCENTS[0]);
    const b = h("button", { type: "button", role: "radio", "aria-checked": String(on), tabindex: on ? "0" : "-1",
      class: "swatch acc-" + a, "aria-label": cap(a), tip: cap(a), "data-key": "accent:" + a });
    b.addEventListener("click", () => pick(b, a, false));
    group.append(b);
  });
  group.addEventListener("keydown", (e) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    const all = $$(".swatch", group);
    const i = all.indexOf(document.activeElement);
    if (i < 0 || (!step && e.key !== "Home" && e.key !== "End")) return;
    e.preventDefault();
    const j = e.key === "Home" ? 0 : e.key === "End" ? all.length - 1 : (i + step + all.length) % all.length;
    pick(all[j], ACCENTS[j], true);
  });
  return group;
}

export async function renderSettings(seq) {
  const main = $("#main");
  // The layout of the lens in view is read first, so the page shows the person's own theme and a change
  // made here is saved with that lens's layout (and a lens switched to here re-reads its own).
  const [em, projects] = await loaded(main, "settings", () => Promise.all([api("GET", "/api/embeds"), api("GET", "/api/projects"),
    loadLayout().catch((e) => { if (e instanceof AuthError) throw e; return null; })]));
  if (seq !== S.seq) return;
  S.projects = projects;
  applyTheme(currentTheme());
  document.title = "Settings · Rihmasto.ai";
  const may = mayAct(em.creators || []);
  const t = currentTheme();
  const rows = em.embeds.map((e) => {
    const revoke = e.state === "active" && may ? button("Revoke", { icon: "x", kind: "small", key: "revoke:" + e.id, "data-control": "revoke_embed", aria: "Revoke " + (e.label || e.id) }) : null;
    if (revoke) {
      revoke.addEventListener("click", () => {
        if (!needPerson()) return;
        actKeep(revoke.parentNode, revoke, async () => {
          await api("POST", "/api/embeds/" + enc(e.id) + "/revoke", signed());
          say(e.id + " is revoked: the website's chat stops at once.", "good");
          S.focusNext = '[data-key="' + CSS.escape("embed:" + e.id) + '"]';   // its row, which now says Revoked
          await nav.rerender();
        });
      });
    }
    return h("li", { class: "emb-row", tabindex: "-1", "data-key": "embed:" + e.id }, h("span", { class: "cat-ic" }, icon(e.kind === "feedback" ? "message-square" : "lightbulb")),
      h("div", { class: "sig-b" }, h("b", null, (e.label || e.id) + " "), h("span", { class: "mono muted small" }, e.id),
        h("div", { class: "sig-m" }, h("span", null, e.kind === "feedback" ? "Feedback on " + ((projects.find((p) => p.id === e.project) || {}).title || e.project) : "Business needs"),
          h("span", null, e.origins.join(", ")), h("span", null, plural(e.messages || 0, "message")), h("span", null, "by " + e.created_by + " · " + ago(e.created)))),
      e.state === "active" ? chip("good", "check-circle", "Active") : chip("neutral", "x-circle", "Revoked"), revoke);
  });
  const themeRow = (name, label, options, value, key) => h("div", { class: "set-row" }, h("span", null, label),
    segmented(name, options, value, (v) => changeTheme({ [key]: v }), { label }));
  const scale = h("input", { type: "range", min: "0.9", max: "1.25", step: "0.05", value: String(t.font_scale || 1), "aria-label": "Text size",
    "data-key": "set:scale" });
  scale.addEventListener("change", () => changeTheme({ font_scale: Number(scale.value) }));
  // Only a persona that may create an embed is offered Create; the others are told who creates one.
  const create = may ? button("Create a chat", { icon: "plus", kind: "small primary", "data-control": "create_embed", key: "create-embed", onclick: () => openEmbedForm() })
    : h("span", { class: "muted small" }, icon("user"), " A " + embedCreators() + " creates a chat.");
  await loadModules();
  if (seq !== S.seq) return;
  // Integrations off: no new chat, but a chat made before is still listed, so its owners can revoke it (FR-MOD5).
  const embedsOn = moduleShows("controls", "create_embed");
  const offNote = embedsOn ? null : h("p", { class: "note warning", "data-key": "embeds-off" }, icon("alert"), h("span", null,
    h("b", null, "Integrations is off. "), "These chats take no messages while it is off. Revoke one here to stop it for good."));
  fill(main,
    pageHead("Settings", pick("The AI models, where the AI works, the parts of Rihmasto in use, standard setups for hosting and data, integrations, "
      + "website embeds, how the cockpit looks, and sign-in links.",
    "The models, the cell runners, the modules in use, the paved roads, integrations, embeds for websites, how the cockpit looks, and sign-in links."), { icon: "settings" }),
    card({ title: "Models", icon: "cpu", id: "set-models", tools: [h("a", { href: "#/models", class: "btn small primary", "data-control": "models_open", "data-key": "set:models" },
      icon("cpu"), h("span", { class: "lbl" }, "Open Models setup"))] },
    h("p", null, "Which model answers for each role (the analyst, the builder, the verifier, the assistant and more): a server on this machine or a hosted "
      + "OpenAI-compatible provider, with a Test that sends it a tiny prompt.")),
    card({ title: "Runners", icon: "layers", id: "set-runners", tools: [h("a", { href: "#/runners", class: "btn small primary", "data-control": "runners_open", "data-key": "set:runners" },
      icon("layers"), h("span", { class: "lbl" }, "Open Runners"))] },
    h("p", null, pick("Which AI coding tool builds the work: Gnomon, which enforces the rules while it works, or another tool such as Claude Code, "
      + "Codex or OpenCode, approved by IT with its version fixed and checked after every run.",
    "Which harness runs the factory's cells: Gnomon, which enforces the rules during a run, or another harness such as Claude Code, Codex or "
      + "OpenCode, approved by IT with its version pinned and checked after every run."))),
    peopleCard(projects),             // People and access: solo or team (people.js, FR-PPL1)
    modulesCard(projects),
    roadsCard(), integrationsCard(),   // paved roads and what a capability can reach (roads.js)
    foldersCard(),             // the folders the cockpit may read for a person (FR-RPJ1)
    agentObsSettingsCard(),   // the agent observability hub's address, once the module is on somewhere (FR-OBS1)
    aboutCard(),              // About and help: the version, this machine, the guides (about.js, FR-PUB2)
    harnessSettingsCard(),   // Harness and enforcement: Gnomon on by default, an opt-out recorded (FR-NVL1)
    enforcementSettingsCard(),   // levels per environment for every project (FR-ENF1)
    !embedsOn && !em.embeds.length ? null : card({ title: "Embeds: a chat window for a website", icon: "message-square", id: "embeds", cls: "emb-card",
      tools: [embedsOn ? create : null],
      info: "An embed has exactly one capability: it files end-user feedback as a change, or a business need as a signal. It answers only from a public brief "
        + "and never from the project's records. Its key is shown once and kept only as a hash; a person revokes it with one click." },
    offNote,
    h("p", { class: "note" }, icon("shield"), h("span", null, "An embed sees nothing of a project's records: it only files what people tell it.")),
    embedsOn ? embedBaseNote(em) : null,
    rows.length ? h("ul", { class: "emb-list" }, rows) : empty("message-square", "No embed yet.")),
    h("div", { class: "sq-cols" },
      card({ title: "Appearance", icon: "sun", info: "Kept with your layout for the lens you are in, and in this browser." },
        themeRow("set-mode", "Mode", [["dark", "Dark", "moon"], ["light", "Light", "sun"], ["system", "System", "monitor"]], t.mode, "mode"),
        h("div", { class: "set-row" }, h("span", null, "Accent"), accentSwatches(t.accent)),
        themeRow("set-density", "Density", [["comfortable", "Comfortable"], ["compact", "Compact"]], t.density, "density"),
        themeRow("set-radius", "Corners", [["soft", "Soft"], ["crisp", "Crisp"]], t.radius, "radius"),
        h("div", { class: "set-row" }, h("span", null, "Text size"), scale)),
      card({ title: "Sign-in and the assistant", icon: "key" },
        h("p", null, "A sign-in link works once. For another tab, make a new one-use link (valid for 10 minutes) from the person menu."),
        button("Open in another browser tab", { icon: "link", onclick: () => nav.openPerson && nav.openPerson(false) }),
        h("p", { class: "muted small" }, "The assistant " + (S.meta.assistant === "gnomon" ? "asks Gnomon in the analyst lane"
          : S.meta.assistant === "model" ? "asks an injected model" : "answers from the cockpit map")
          + ". It proposes; you confirm."))));
}

// -- new project: a work profile, a maturity and a mode ---------------------------------------------

// The person's own word that a keyword of the rule was found in: the keyword itself, or a longer word
// that holds it ("train" in "trainees"); null when the text does not hold it at all.
function wordHolding(text, keyword) {
  const low = String(text || "").toLowerCase();
  const k = String(keyword).toLowerCase();
  if (k.includes(" ")) return low.includes(k) ? k : null;
  const words = low.match(/[\p{L}\p{N}]+/gu) || [];
  return words.includes(k) ? k : words.find((w) => w.includes(k)) || null;
}

// What Rihma proposed, said plainly where the person is looking: the profile, the words it rests on,
// and how sure the rule is. When nothing in the text pointed anywhere, it says so instead of quietly
// keeping the default (which looks like a button that did nothing). A keyword found only inside a longer
// word is shown with that word, the person's own, and makes the proposal uncertain.
function showProposal(target, out, warning, text) {
  if (!out) {
    fill(target, h("div", { class: "proposal warn", role: "status" }, icon("alert"), h("span", null, warning)));
    return;
  }
  const label = profileOf(out.profile).label;
  const words = (out.basis || []).filter((w) => !/^no keyword/.test(w));
  const held = words.map((w) => ({ w, in: text === undefined ? w : wordHolding(text, w) }));
  const partial = held.filter((x) => x.in && x.in !== x.w);
  const ranked = Object.entries(out.scores || {}).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]);
  const runnerUp = ranked.length > 1 && ranked[1][1] >= ranked[0][1] - 1 ? profileOf(ranked[1][0]).label : null;
  const uncertain = out.uncertain || out.confidence === "uncertain" || !words.length || Boolean(runnerUp) || partial.length > 0;
  const why = words.length
    ? h("span", null, words.length === 1 ? "From the word " : "From the words ", ...held.flatMap((x, i) => [i ? ", " : null, h("code", { class: "kw" }, x.w),
      x.in && x.in !== x.w ? " (in “" + x.in + "”)" : null]), ".")
    : h("span", null, "Nothing in the text pointed to a kind of work, so Rihma kept the default. Add a few words about what it does, or pick one below.");
  fill(target, h("div", { class: "proposal" + (uncertain ? " warn" : " good"), role: "status" },
    icon(uncertain ? "alert" : "sparkles"),
    h("div", null,
      h("b", null, "Rihma proposes: " + label),
      h("p", { class: "small" }, why),
      partial.length ? h("p", { class: "small" }, "The rule found " + partial.map((x) => "“" + x.w + "” inside “" + x.in + "”").join(", ")
        + ": part of a longer word, which may mean something else. Check the choice below.") : null,
      words.length && out.uncertain_because && !partial.length && !runnerUp ? h("p", { class: "small" }, "Not sure: " + out.uncertain_because + ". Pick the one that fits.") : null,
      uncertain && runnerUp ? h("p", { class: "small" }, "Close call: it could also be " + runnerUp + ". Pick the one that fits.") : null,
      !uncertain ? h("p", { class: "small muted" }, "Pick another below if it fits better.") : null)));
}

export function newProjectModal(opts) {
  const profiles = (S.meta && S.meta.profiles) || [];
  // Nothing is assumed: unless the person picks one, intake proposes the kind of work by rule from the
  // material, and asks which it is when the words point to more than one (FR-DF4).
  let chosen = "auto";
  const title = h("input", { maxlength: "200", placeholder: "for example: Equipment loans", "aria-label": "Title" });
  const source = h("textarea", { rows: "4", maxlength: "200000", placeholder: "For example: Our team keeps losing track of who borrowed the drills and laptops. We want a simple way to lend and return things.", "aria-label": "The need" });
  const by = h("input", { maxlength: "200", value: S.person, autocomplete: "name", "aria-label": "Requested by" });
  const basis = h("p", { class: "muted small propose-basis", "aria-live": "polite" });
  // The work profile: a radiogroup of cards with one tab stop. Choosing marks the card in place (nothing
  // is rebuilt, so the focus stays), and the arrow keys move and choose, as in every segmented control.
  // A Preview card says what is still to come for that profile.
  const grid = h("div", { class: "prof-grid", role: "radiogroup", "aria-label": "Work profile" });
  const draw = () => $$(".prof-card", grid).forEach((b) => {
    const on = b.dataset.key === "profile:" + chosen;
    b.setAttribute("aria-checked", String(on));
    b.tabIndex = on ? 0 : -1;
  });
  const auto = h("button", { type: "button", role: "radio", "aria-checked": "false", class: "prof-card", "data-key": "profile:auto" },
    h("span", { class: "prof-top" }, h("span", { class: "cat-ic" }, icon("sparkles")), chip("neutral", "info", "Not sure")),
    h("b", null, "Let Rihma choose"), h("span", { class: "prof-s" }, "Proposed from the need or the folder by rule when the intake reads it. If the words point to more than one kind, you are asked which."),
    h("small", null, "change it later in Project settings"));
  auto.addEventListener("click", () => { chosen = "auto"; draw(); });
  fill(grid, [auto].concat(profiles.map((p) => {
    const preview = p.status === "preview";
    const b = h("button", { type: "button", role: "radio", "aria-checked": "false", class: "prof-card", "data-key": "profile:" + p.id },
      h("span", { class: "prof-top" }, h("span", { class: "cat-ic" }, icon(p.icon)),
        preview ? chip("accent", "eye", "Preview", { tip: p.note || "Its own template is still to come." }) : chip("good", "check", "Ready")),
      h("b", null, p.label), h("span", { class: "prof-s" }, p.summary),
      preview && p.note ? h("span", { class: "prof-note" }, String(p.note).replace(/`([^`]+)`/g, "$1")) : null,
      h("small", null, (((S.meta.deliverables || {})[p.deliverable]) || "").split(":")[0]));
    b.addEventListener("click", () => { chosen = p.id; draw(); });
    return b;
  })));
  grid.addEventListener("keydown", (e) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    const all = $$(".prof-card", grid);
    const i = all.indexOf(document.activeElement);
    if (i < 0 || (!step && e.key !== "Home" && e.key !== "End")) return;
    e.preventDefault();
    const next = all[e.key === "Home" ? 0 : e.key === "End" ? all.length - 1 : (i + step + all.length) % all.length];
    chosen = next.dataset.key.split(":")[1];
    draw();
    next.focus();
  });
  draw();
  const propose = button("Let Rihma propose", { icon: "sparkles", kind: "small", "data-control": "propose_profile" });
  // The button is disabled while Rihma reads the need, so it loses the focus; it gets it back after
  // (unless the need was empty, and its field took the focus). The proposal is said in the live region.
  propose.addEventListener("click", () => actKeep(propose.parentNode, propose, async () => {
    const text = (title.value + "\n" + source.value).trim();
    if (!text) {
      showProposal(basis, null, "Write the need first: Rihma proposes a work profile from its words.");
      source.focus();
      return;
    }
    fill(basis, h("span", { class: "muted" }, icon("sparkles"), " Reading the need…"));
    const out = await api("POST", "/api/profiles/propose", { text });
    chosen = out.profile;
    draw();
    showProposal(basis, out, null, text);
    const card = grid.querySelector('[aria-checked="true"]');
    if (card) {
      card.classList.add("just-proposed");
      card.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      setTimeout(() => card.classList.remove("just-proposed"), 1600);
    }
  }));
  // How it runs: a posture with its weights and the kernel's preview, or no posture (maturity and mode as before).
  const how = postureSection({ profile: () => (chosen === "auto" ? null : chosen), watch: grid });
  const val = (seg) => (seg.querySelector('[aria-checked="true"]') || {}).dataset.key.split(":")[1];
  // Start from a need, or from an existing project: a local git folder or an address git clones without a
  // password. Adopting reads the repository (it never changes the folder) and records its tests as a baseline.
  const repo = h("input", { maxlength: "2000", placeholder: "C:\\code\\my-app, /home/me/my-app or https://github.com/org/my-app.git",
    "aria-label": "Folder or git address", autocomplete: "off", spellcheck: "false", "data-control": "adopt_project" });
  const runsAt = h("input", { maxlength: "500", placeholder: "https://my-app.example.com (optional)", "aria-label": "Where it runs today" });
  const intents = { monitor: "Watch it: probes, incidents, upstream changes as cards.",
    maintain: "Keep it healthy: updates, fixes and security, through the gate.",
    improve: "Develop it further: changes go round the factory's full loop." };
  const intentHelp = h("small", { class: "muted", "aria-live": "polite" }, intents.improve);
  const intent = segmented("np-intent", [["monitor", "Monitor"], ["maintain", "Maintain"], ["improve", "Improve"]], "improve",
    (k) => { intentHelp.textContent = intents[k]; }, { label: "What Rihmasto should do" });
  // Confidential material stays on local models: a role routed to a hosted model is refused, never sent.
  const secret = h("input", { type: "checkbox", id: "np-confidential", "data-control": "confidential" });
  const secretField = h("div", { class: "field np-secret" },
    h("label", { class: "np-check", for: "np-confidential" }, secret, h("span", null, "Confidential: keep on local models")),
    h("small", { class: "muted" }, "Intake and every model call for this project may go only to a model on this machine or your private network. A role routed to a hosted model is refused, never sent."));
  // At explore and demo the factory waits once for the person's Go or Skip on the spec before the first build (kernel/go_ahead.py).
  const nowait = h("input", { type: "checkbox", id: "np-nowait", "data-control": "build_without_waiting" });
  const nowaitField = h("div", { class: "field np-secret" },
    h("label", { class: "np-check", for: "np-nowait" }, nowait, h("span", null, "Build without waiting for me")),
    h("small", { class: "muted" }, "Unticked, Rihmasto shows you the spec before the first build at explore and demo maturity, with Go or Skip. Ticked, it builds the spec as written."));
  // A folder, in either path, is scanned first: the person sees what would be read before anything is sent.
  let startFrom = "need";
  const scanner = scanStep({ get adopting() { return startFrom === "existing"; }, confidential: () => secret.checked,
    person: () => by.value.trim(), onScanned: () => setSubmit(),
    onNoCode: (folder) => {
      start.querySelector('[data-key="np-start:need"]').click();
      source.value = folder;
      actKeep(form, submit, () => scanner.scan(folder)).then(setSubmit);   // after act() gives the buttons back
    } });
  secret.addEventListener("change", () => scanner.refresh());   // what a confidential project would send, said again
  const folderOf = () => {
    const v = startFrom === "existing" ? repo.value : source.value;
    return looksLikeFolder(v) ? v.trim() : "";
  };
  const scanned = () => !!folderOf() && !!scanner.result && scanner.source === folderOf();
  // Choosing a folder by browsing goes straight to the scan, as typing it and pressing Scan the folder does.
  const scanNow = () => { if (form.isConnected) form.requestSubmit(); };
  const needBrowse = browseButtons({ kind: "folder", name: "a folder of material", title: "Choose a folder of material", start: () => (looksLikeFolder(source.value) ? source.value.trim() : ""),
    onPick: (p) => { source.value = p; source.dispatchEvent(new Event("input")); scanNow(); } });
  const needPart = h("div", { class: "np-part" },
    h("div", { class: "field" }, h("label", null, "The need, the idea or a written spec"), source,
      h("small", { class: "muted" }, "Or the path of a folder on this machine: Rihmasto scans any files in it (documents, slides, sheets, PDFs, code) and shows what it would read first."),
      needBrowse),
    h("div", { class: "np-prof-h" }, h("span", { class: "label-h" }, "Work profile"), propose), basis, grid, nowaitField);
  const repoPart = h("div", { class: "np-part" },
    h("div", { class: "field" }, h("label", null, "Folder or git address"),
      pathField(repo, { kind: "folder", name: "the project's folder", title: "Choose the project's folder", onPick: scanNow }),
      h("small", { class: "muted" }, "A folder on this machine (a git repository or not), or an https address git clones without a password. For a private repository, clone it first and give the folder. Rihmasto scans it first, and never changes your folder.")),
    h("div", { class: "field" }, h("label", null, "What should Rihmasto do with it?"), intent, intentHelp),
    h("div", { class: "field" }, h("label", null, "Where it runs today"), runsAt,
      h("small", { class: "muted" }, "Optional: Rihmasto probes it there and opens an incident if it stops answering.")),
    h("p", { class: "muted small" }, "Rihma proposes the work profile from the repository's README; you can change it later."));
  repoPart.hidden = true;
  // Shape it in chat (D-0022): no form at all; the profile, mode and maturity are chosen when the chat creates the project.
  const chatPart = h("div", { class: "np-part" }, h("p", { class: "note" }, icon("message-square"), h("span", null,
    "Talk it through with Rihma: start with nothing, a sentence or a file. Rihma asks one or two questions at a time and keeps a draft brief "
    + "you can edit; when it is good enough, you create the project from it.")),
  h("div", { class: "btns" }, h("a", { href: "#/shape", class: "btn primary", "data-control": "shape_open", "data-key": "np:shape", onclick: () => closeModal() },
    icon("message-square"), h("span", { class: "lbl" }, "Open the chat"))));
  chatPart.hidden = true;
  const submit = h("button", { type: "submit", class: "btn primary", "data-control": "new_project" }, icon("plus"), "Create and start the intake");
  const submitNote = h("span", { class: "muted small" }, "Nothing is built until the questions that block it are answered.");
  function setSubmit() {
    const scan = !!folderOf() && !scanned();
    const need = startFrom === "need";
    const ch = scanner.choice;
    const res = scanned() ? scanner.result : null;
    const label = adoptLabel(res, ch);
    fill(submit, icon(scan ? "search" : need ? "plus" : ch.track ? "eye" : "folder"), scan ? "Scan the folder" : need ? "Create and start the intake" : label);
    submit.disabled = !need && !!res && ((!res.code && !ch.track) || ((res.adopted_as || []).length > 0 && !ch.again)
      || (ch.each && !ch.repos.size));
    submitNote.textContent = scan ? "Rihmasto shows what it would read of the folder first. Nothing is sent or created yet."
      : need ? "Nothing is built until the questions that block it are answered."
        : "It runs as a job: Rihmasto reads the project and runs its tests for a baseline. Your folder is never changed.";
  }
  const formParts = [];        // what a form start shows, and Shape it in chat leaves out
  const start = segmented("np-start", [["need", "A need or a spec"], ["existing", "An existing project"], ["chat", "Shape it in chat"]], "need", (k) => {
    startFrom = k;
    needPart.hidden = k !== "need";
    repoPart.hidden = k !== "existing";
    chatPart.hidden = k !== "chat";
    formParts.forEach((el) => { el.hidden = k === "chat"; });
    scanner.reset();
    setSubmit();
  }, { label: "Start from", control: "np_start" });
  for (const field of [repo, source]) {
    field.addEventListener("input", () => { if (scanner.source && scanner.source !== folderOf()) scanner.reset(); setSubmit(); });
  }
  formParts.push(h("div", { class: "field" }, h("label", null, "Title"), title),
    how.el,
    secretField,
    h("div", { class: "field" }, h("label", null, "Requested by"), by),
    h("div", { class: "btns" }, submit, submitNote));
  const form = h("form", { class: "np-form", novalidate: true },
    h("div", { class: "field" }, h("label", null, "Start from"), start),
    formParts[0], needPart, repoPart, scanner.el, chatPart, ...formParts.slice(1));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const folder = folderOf();
    if (folder && !scanned()) {          // the scan step first: what would be read, before anything is sent
      if (!by.value.trim()) { say("Name the person who asks for it: the scan is signed.", "warning"); by.focus(); return; }
      actKeep(form, submit, () => scanner.scan(folder)).then(setSubmit);   // after act() gives the buttons back
      return;
    }
    const picked = folder ? { exclude: scanner.exclude() } : {};
    if (startFrom === "existing") {
      const data = Object.assign({ title: title.value.trim(), source: repo.value.trim(), intent: val(intent),
        base_url: runsAt.value.trim(), person: by.value.trim(), persona: S.persona, confidential: secret.checked }, how.value(), picked,
      folder ? adoptChoice(scanner.result, scanner.choice, !!how.value().posture) : {});
      if (!data.title) { say("Give the project a title.", "warning"); title.focus(); return; }
      if (!data.source) { say("Give the folder or the git address of the existing project.", "warning"); repo.focus(); return; }
      if (!data.person) { say("Name the person who adopts it.", "warning"); by.focus(); return; }
      const many = folder ? adoptEach(scanner.result, scanner.choice, data) : null;
      actKeep(form, submit, async () => {
        const jobs = [];
        for (const one of many || [data]) jobs.push((await api("POST", "/api/adopt", one)).job.id);
        closeModal();
        say(many ? "Adopting " + many.length + " projects as jobs " + jobs.join(", ") + ": each opens from the Jobs page when its baseline is recorded."
          : (data.documents ? "Tracking " : "Adopting ") + data.title + " as job " + jobs[0] + ": when its baseline is recorded, Open the project here takes you to it.", "good");
        location.hash = "#/jobs";
      });
      return;
    }
    const data = Object.assign({ title: title.value.trim(), source: folder || source.value, profile: chosen === "auto" ? null : chosen,
      requested_by: by.value.trim(), persona: S.persona, confidential: secret.checked, build_without_waiting: nowait.checked }, how.value(),
      folder ? { folder: true, exclude: scanner.exclude() } : {});
    if (!data.title || !data.source.trim()) { say("A new project needs a title and the need.", "warning"); (data.title ? source : title).focus(); return; }
    if (!data.requested_by) { say("Name the person who asks for it.", "warning"); by.focus(); return; }
    actKeep(form, form.querySelector('button[type="submit"]'), async () => {
      const out = await api("POST", "/api/projects", data);
      closeModal();
      say("Project " + out.project.id + " is created. Its intake runs as job " + out.job.id + ".", "good");
      S.jumped = true;                    // the new project's heading takes the focus once it is shown
      location.hash = "#/p/" + enc(out.project.id) + "/overview";
    });
  });
  openModal("New project", form, { icon: "plus", wide: true });
  // Opened for an existing project (Ask Rihma's Take me there to the folder picker): that path, its folder given.
  if (opts && opts.start === "existing") {
    start.querySelector('[data-key="np-start:existing"]').click();
    if (opts.folder) { repo.value = opts.folder; setSubmit(); }
  }
}
void iconButton; void infoButton; void attachTip; void local; void fmtAge; void STAGE_ICON; void $$;
