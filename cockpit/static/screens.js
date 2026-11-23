/* Pages beyond Home and the project: the delivery square, the capability catalogue, Projects, the
   Inbox across projects, Settings (embeds, appearance, sign-in links), and the New project modal.
   Every write goes through the same routes as before, signed with the person and persona. */

import {
  S, $, $$, h, fill, icon, chip, api, act, say, signed, needPerson, nav, enc, link, plural, button, card, empty,
  pageHead, skeleton, openModal, closeModal, profileOf, profileChip, personaLabel, segmented, viewChoice,
  setViewChoice, avatar, ago, fmtAge, fmtAt, nowChip, iconButton, infoButton, attachTip, local,
  KIND_LABEL, KIND_ICON, VERDICT_LABEL, CATALOGUE_STATE, FACTORY_PID, STAGE_ICON, ACCENTS, cap,
} from "./core.js";
import { squareDiagram, catalogueCard, WIDGET_DEFS, liveState } from "./widgets.js";
import { decideForm, impactPanelFor } from "./project.js";
import { dataTable } from "./charts.js";
import { currentTheme, setTheme } from "./dashboard.js";

const CHANNEL_ICON = { chat: "message-square", feed: "signal", form: "file-check", email: "send", monitoring: "activity",
  meeting: "users", embed: "code", manual: "edit" };
const SIGNAL_STATE = {
  new: ["warning", "dashed", "New"], routed: ["info", "arrow-right", "Routed to a project"], concept: ["accent", "lightbulb", "Concept"],
  validated: ["good", "check-circle", "Validated"], parked: ["neutral", "pause", "Parked"], rejected: ["neutral", "x-circle", "Rejected"],
};

function people(list) {
  if (!list || !list.length) return h("span", { class: "muted small" }, "No one yet");
  return h("span", { class: "people" }, list.slice(0, 5).map((p) => h("span", { tip: p.name + " · " + personaLabel(p.persona) }, avatar(p.name))),
    list.length > 5 ? h("small", null, "+" + (list.length - 5)) : null);
}

// -- the delivery square ------------------------------------------------------------------------

function signalForm(sq) {
  const text = h("textarea", { rows: "3", maxlength: "8000", placeholder: "What was asked, in the words it came in", "aria-label": "The need" });
  const channel = h("select", { "aria-label": "Channel" }, sq.channels.map((c) => h("option", { value: c, selected: c === "chat" }, cap(c))));
  const source = h("input", { maxlength: "200", placeholder: "Where: #ops-team, a meeting, a feed", "aria-label": "Source" });
  const form = h("form", { class: "sig-form", novalidate: true, id: "log-signal" },
    h("div", { class: "field" }, h("label", null, "The need"), text),
    h("div", { class: "row2" }, h("div", { class: "field" }, h("label", null, "Channel"), channel),
      h("div", { class: "field" }, h("label", null, "Source"), source)),
    h("div", { class: "btns" }, h("button", { type: "submit", class: "btn primary", "data-control": "log_signal" }, icon("plus"), "Log the signal"),
      h("span", { class: "muted small" }, "Signed with your name. Triage routes it to a project, or makes a concept.")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!text.value.trim()) { say("Write the need first.", "warning"); text.focus(); return; }
    if (!needPerson()) return;
    act(form, async () => {
      const out = await api("POST", "/api/signals", Object.assign({ text: text.value.trim(), channel: channel.value, source: source.value.trim() }, signed()));
      say(out.signal.id + " is logged. Triage it to route it.", "good");
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
      act(action.parentNode, async () => {
        const out = await api("POST", "/api/signals/" + enc(s.id) + "/triage", signed());
        const t = out.signal;
        say(t.state === "routed" ? s.id + " is now change " + t.routed_to.card + " on " + t.routed_to.project + "."
          : s.id + " is a concept to validate: " + t.routed_to.card + ".", "good");
        await nav.rerender();
      });
    });
  } else if (r.project && r.card && s.state === "routed") {
    action = h("a", { class: "small", href: link(r.project, "changes", r.card) }, r.card, icon("arrow-right"));
  } else if (r.project) {
    action = h("a", { class: "small", href: "#/p/" + enc(r.project) }, "Open the project", icon("arrow-right"));
  } else if (r.card) {
    action = h("a", { class: "small", href: "#concept-" + r.card }, r.card, icon("arrow-right"));
  }
  return h("li", { class: "sig-row", "data-id": s.id },
    h("span", { class: "sig-ic", tip: cap(s.channel) }, icon(CHANNEL_ICON[s.channel] || "signal")),
    h("div", { class: "sig-b" }, h("p", null, s.text),
      h("div", { class: "sig-m" }, h("span", { class: "mono" }, s.id), h("span", null, cap(s.channel) + " · " + s.source),
        s.person ? h("span", null, "raised by " + s.person) : null, h("span", { tip: fmtAt(s.at) }, ago(s.at)))),
    h("div", { class: "sig-a" }, chip(st[0], st[1], st[2]), action));
}

function conceptCard(c) {
  const may = ((S.meta && S.meta.concept_editors) || []).includes(S.persona);
  const profiles = (S.meta && S.meta.profiles) || [];
  const title = h("input", { value: c.title || "", maxlength: "80", "aria-label": "Title", disabled: !may || null });
  const profile = h("select", { "aria-label": "Work profile", disabled: !may || null }, profiles.map((p) => h("option", { value: p.id, selected: p.id === c.profile }, p.label)));
  const maturity = h("select", { "aria-label": "Maturity", disabled: !may || null }, Object.keys(S.meta.maturities).map((m) => h("option", { value: m, selected: m === c.maturity }, m)));
  const mode = h("select", { "aria-label": "Mode", disabled: !may || null }, Object.keys(S.meta.modes).map((m) => h("option", { value: m, selected: m === c.mode }, m)));
  const reason = h("input", { maxlength: "2000", placeholder: "Reason (recorded with your decision)", "aria-label": "Reason" });
  const p = profileOf(c.profile);
  const box = h("article", { class: "concept", id: "concept-" + c.card, "data-id": c.card },
    h("div", { class: "concept-h" }, h("span", { class: "cat-ic" }, icon(p.icon || "globe")),
      h("div", null, h("b", null, c.title), h("div", { class: "sig-m" }, h("span", { class: "mono" }, c.card), h("span", null, "from " + (c.signal || "?")),
        c.raised_by ? h("span", null, "raised by " + c.raised_by) : null, h("span", null, ago(c.created))))),
    h("p", { class: "concept-t" }, c.text || c.body || ""),
    (c.profile_basis || []).length ? h("p", { class: "muted small" }, "Profile proposed by rule from: ", (c.profile_basis || []).join(", ")) : null,
    h("div", { class: "concept-f" },
      h("div", { class: "field" }, h("label", null, "Title"), title),
      h("div", { class: "field" }, h("label", null, "Work profile"), profile),
      h("div", { class: "field" }, h("label", null, "Maturity"), maturity),
      h("div", { class: "field" }, h("label", null, "Mode"), mode)));
  if (!may) {
    box.append(h("p", { class: "muted small" }, icon("user"), " A " + ((S.meta && S.meta.concept_editors) || []).map(personaLabel).join(" or ") + " validates, parks or rejects it."));
    return box;
  }
  const save = button("Save the edit", { icon: "edit", kind: "small", key: "concept:" + c.card + ":save" });
  save.addEventListener("click", () => {
    if (!needPerson()) return;
    act(box, async () => {
      await api("POST", "/api/concepts/" + enc(c.card) + "/edit", Object.assign({ title: title.value.trim(), profile: profile.value,
        maturity: maturity.value, mode: mode.value }, signed()));
      say(c.card + " is edited, signed by " + S.person.trim() + ".", "good");
      await nav.rerender();
    });
  });
  const decide = (verdict) => {
    if (!needPerson()) return;
    act(box, async () => {
      const changed = title.value.trim() !== c.title || profile.value !== c.profile || maturity.value !== c.maturity || mode.value !== c.mode;
      if (changed) {
        await api("POST", "/api/concepts/" + enc(c.card) + "/edit", Object.assign({ title: title.value.trim(), profile: profile.value,
          maturity: maturity.value, mode: mode.value }, signed()));
      }
      const out = await api("POST", "/api/projects/" + FACTORY_PID + "/cards/" + enc(c.card) + "/decide",
        Object.assign({ verdict, reason: reason.value.trim() }, signed()));
      say(c.card + ": " + (VERDICT_LABEL[verdict] || verdict) + ", signed by " + S.person.trim() + "."
        + (out.project ? " It is now project " + out.project + "; its intake starts from the need." : ""), "good");
      if (out.project) location.hash = "#/p/" + enc(out.project) + "/overview";
      else await nav.rerender();
    });
  };
  box.append(h("div", { class: "field" }, reason), h("div", { class: "btns", role: "group", "aria-label": "Decide " + c.card },
    button("Validate", { icon: "check", kind: "small primary", "data-control": "validate_concept", key: "concept:" + c.card + ":validate", onclick: () => decide("validate") }),
    button("Park", { icon: "pause", kind: "small", key: "concept:" + c.card + ":park", onclick: () => decide("park") }),
    button("Reject", { icon: "x", kind: "small", key: "concept:" + c.card + ":reject", onclick: () => decide("reject") }), save));
  return box;
}

export async function renderSquare(seq) {
  const main = $("#main");
  const done = skeleton(main, "the delivery square");
  const sq = await api("GET", "/api/square");
  done();
  if (seq !== S.seq) return;
  document.title = "Square · Rihmasto.ai";
  const fresh = (sq.signals_list || []).filter((s) => s.state === "new").length;
  const pipe = WIDGET_DEFS.pipeline.render({ pipeline: sq.pipeline }, { size: "L" });
  fill(main,
    pageHead("Delivery square", "Needs arrive from the operation, a concept is validated, the factory builds, end users test, and production runs. Feedback loops back.",
      { icon: "square", actions: [button("Log a signal", { icon: "plus", kind: "primary", "data-control": "log_signal",
        onclick: () => { const t = $("#log-signal textarea"); if (t) { t.scrollIntoView({ block: "center" }); t.focus(); } } })] }),
    card({ title: "The square at a glance", icon: "square", cls: "sq-card", info: "The delivery square (toimitusneliö): four corners around one canon. "
      + "Every arrow is a hand-over with a person who decides." }, squareDiagram(sq, { people: sq.people })),
    h("div", { class: "sq-cols" },
      card({ title: "Needs arrive", icon: "signal", id: "needs", tools: [h("span", { class: "muted small" }, fresh + " new · " + plural((sq.signals_list || []).length, "signal")), people(sq.people.needs)],
        info: "A signal is a need as it arrived: a chat, a data feed, a monitoring alert, a meeting, the website chat. Triage needs no model: "
          + "a signal about an existing project becomes a change on it; a new need becomes a concept for a business owner or product owner." },
      signalForm(sq),
      (sq.signals_list || []).length ? h("ul", { class: "sig-list" }, sq.signals_list.map(signalRow)) : empty("signal", "No signal yet.")),
      card({ title: "Concepts to validate", icon: "lightbulb", id: "concepts", tools: [people(sq.people.concept)],
        info: "Nothing becomes a project without a person's decision. Edit the title, profile, maturity and mode, then validate, park or reject." },
      (sq.concepts || []).length ? h("div", { class: "concepts" }, sq.concepts.map(conceptCard))
        : empty("lightbulb", "No concept waits. A triaged new need appears here."))),
    card({ title: "The factory", icon: "factory", tools: [people(sq.people.factory)], info: "Projects per stage, in four bands: Decide, Shape, Deliver, Run." }, pipe),
    h("div", { class: "sq-cols" },
      card({ title: "End-user testing", icon: "users", tools: [people(sq.people.testing)], info: "What end users report comes back as a change, triaged to the stage that can fix it. "
        + "It never goes straight to code." },
      (sq.feedback || []).length ? h("ul", { class: "fb-list" }, sq.feedback.map((f) => h("li", { class: "fb-row" },
        avatar(f.person || "?"), h("div", { class: "sig-b" }, h("a", { href: link(f.project, "changes", f.card) }, f.title),
          h("div", { class: "sig-m" }, h("span", null, f.project_title), h("span", { class: "mono" }, f.card), f.person ? h("span", null, f.person) : null, h("span", null, ago(f.created)))),
        f.state === "open" ? (f.triaged ? chip("warning", "clock", "Waits on a decision") : chip("warning", "dashed", "Not triaged")) : chip("good", "check", cap(f.state)))))
        : empty("users", "No end-user feedback yet. A feedback embed or the Try it checklist files it.")),
      card({ title: "Production", icon: "server", tools: [people(sq.people.production)], info: "What runs in production, with DevOps, maintenance, security and compliance around it." },
        (sq.production || []).length ? h("ul", { class: "live-list" }, sq.production.map((p) => h("li", { class: "live-row" },
          h("span", { class: "cat-ic" }, icon(profileOf(p.profile).icon)), h("div", { class: "live-b" }, h("a", { href: "#/p/" + enc(p.project) }, p.title),
            h("div", { class: "live-m" }, (p.now || {}).line || "")), nowChip(p.now, p.project))))
          : h("div", null, empty("server", "Nothing runs in production yet. A release at stage 7 appears here."),
            h("ul", { class: "ops-list" }, [["shield", "Security", "CVEs and drift arrive as updates"], ["activity", "Monitoring", "probes open incidents and new signals"],
              ["file-check", "Compliance", "evidence packs per release"], ["refresh", "Maintenance", "changes go back through the factory"]].map(([ic, t, d]) =>
              h("li", null, icon(ic), h("b", null, t), h("span", { class: "muted small" }, d))))))));
}

// -- the capability catalogue -------------------------------------------------------------------

const CAT = { state: "all", profile: "", deliverable: "", q: "" };
export async function renderCatalogue(seq) {
  const main = $("#main");
  const done = skeleton(main, "the catalogue");
  const cat = await api("GET", "/api/catalogue");
  done();
  if (seq !== S.seq) return;
  document.title = "Catalogue · Rihmasto.ai";
  const mode = viewChoice("catalogue", "cards");
  const items = cat.items.filter((i) => (CAT.state === "all" || i.state === CAT.state) && (!CAT.profile || i.profile === CAT.profile)
    && (!CAT.deliverable || (i.deliverable || "product") === CAT.deliverable)
    && (!CAT.q || (i.title + " " + (i.summary || "")).toLowerCase().includes(CAT.q.toLowerCase())));
  const lifecycle = ["proposed", "shaping", "building", "trying", "pilot", "in_use"];
  const strip = h("ol", { class: "lifecycle", "aria-label": "Capabilities by state, from proposed to in use" },
    h("li", null, h("button", { type: "button", class: "lc" + (CAT.state === "all" ? " on" : ""), "aria-pressed": String(CAT.state === "all"),
      onclick: () => { CAT.state = "all"; nav.route(true); } }, h("span", { class: "lc-n" }, String(cat.items.length)), h("span", { class: "lc-l" }, icon("catalogue"), "All"))),
    lifecycle.map((s) => h("li", null, h("button", { type: "button", class: "lc" + (CAT.state === s ? " on" : "") + ((cat.counts[s] || 0) ? "" : " zero"),
      "aria-pressed": String(CAT.state === s), onclick: () => { CAT.state = CAT.state === s ? "all" : s; nav.route(true); } },
    h("span", { class: "lc-n" }, String(cat.counts[s] || 0)), h("span", { class: "lc-l" }, icon(CATALOGUE_STATE[s].icon), CATALOGUE_STATE[s].word)))));
  const profSel = h("select", { "aria-label": "Work profile" }, h("option", { value: "" }, "Every profile"),
    cat.profiles.map((p) => h("option", { value: p.id, selected: p.id === CAT.profile }, p.label)));
  profSel.addEventListener("change", () => { CAT.profile = profSel.value; nav.route(true); });
  const delSel = h("select", { "aria-label": "Deliverable" }, h("option", { value: "" }, "Every deliverable"),
    Object.keys(cat.deliverables).map((d) => h("option", { value: d, selected: d === CAT.deliverable }, cap(d.replace("_", " ")))));
  delSel.addEventListener("change", () => { CAT.deliverable = delSel.value; nav.route(true); });
  const q = h("input", { type: "search", value: CAT.q, placeholder: "Search capabilities", "aria-label": "Search capabilities" });
  q.addEventListener("change", () => { CAT.q = q.value.trim(); nav.route(true); });
  fill(main,
    pageHead("Capability catalogue", "Which agents and products we have, in use, in pilot or proposed, what each one does, and whether its pack is valid.", { icon: "catalogue",
      actions: [button("New project", { icon: "plus", kind: "primary", onclick: () => newProjectModal() })] }),
    strip,
    h("div", { class: "filters" }, profSel, delSel, q, h("span", { class: "spacer" }),
      segmented("cat-view", [["cards", "Cards", "catalogue"], ["table", "Table", "table"]], mode, (v) => { setViewChoice("catalogue", v); nav.route(true); }, { label: "View", iconOnly: true })),
    !items.length ? empty("catalogue", cat.items.length ? "No capability matches these filters." : "No capability yet. A validated concept or a new project starts one.")
      : mode === "table" ? dataTable([{ label: "Capability", value: (r) => h("a", { href: r.project ? "#/p/" + enc(r.project) : "#/square" }, r.title) },
        { label: "State", value: (r) => { const st = CATALOGUE_STATE[r.state]; return chip(st.tone, st.icon, st.word); } },
        { label: "Profile", value: (r) => profileChip(r.profile, { short: true }) }, { label: "Deliverable", value: (r) => cap((r.deliverable || "product").replace("_", " ")) },
        { label: "Stage", value: (r) => (r.stage ? r.stage + " of 7" : "concept") }, { label: "Maturity", value: (r) => r.maturity || "-" },
        { label: "Pack", value: (r) => (r.pack ? "v" + r.pack.version + (r.pack.valid ? " · valid" : " · not valid") : "none") }], items, "Capabilities")
        : h("div", { class: "cat-grid wide" }, items.map(catalogueCard)),
    h("p", { class: "muted small foot-note" }, icon("package"), " A capability pack names everything a release delivered by its hash, with its evals; it is valid only while they hold."));
}

// -- projects -----------------------------------------------------------------------------------

function projectNow(p) {
  const st = liveState({ live: { running: p.running }, now: p.now, last_cell: p.last_cell });
  if (p.factory) return chip("neutral", "sparkles", "Proposals");
  return chip(st.tone, st.icon, st.word, { tip: (p.now || {}).line || "" });
}
function miniStages(stage) {
  return h("span", { class: "mini-steps", "aria-label": "Stage " + stage + " of 7" }, [1, 2, 3, 4, 5, 6, 7].map((n) =>
    h("span", { class: "ms " + (n < stage ? "done" : n === stage ? "now" : "ahead") })));
}
export async function renderProjectsPage(seq) {
  const main = $("#main");
  const done = skeleton(main, "projects");
  const projects = await api("GET", "/api/projects");
  done();
  if (seq !== S.seq) return;
  S.projects = projects;
  document.title = "Projects · Rihmasto.ai";
  const mode = viewChoice("projects", "cards");
  const mineOf = (p) => Object.entries(p.open_by_kind || {}).reduce((n, [k, c]) => n + (((S.personas.find((x) => x.id === S.persona) || {}).decides || []).includes(k) ? c : 0), 0);
  const shown = projects.filter((p) => !S.onlyWaiting || mineOf(p) > 0);
  const products = projects.filter((p) => !p.factory);
  const filter = h("label", { class: "check" }, h("input", { type: "checkbox", checked: S.onlyWaiting, "data-key": "onlywaiting",
    onchange: (e) => { S.onlyWaiting = e.target.checked; nav.route(true); } }), "Only projects waiting on you");
  const cards = h("div", { class: "proj-grid" }, shown.map((p) => {
    const mine = mineOf(p);
    const prof = profileOf(p.profile);
    return h("a", { class: "proj-card" + (p.factory ? " factory" : ""), href: p.factory ? link(p.id, "inbox") : "#/p/" + enc(p.id) },
      h("div", { class: "pc-top" }, h("span", { class: "cat-ic" }, icon(p.factory ? "sparkles" : prof.icon || "globe")), projectNow(p)),
      h("b", { class: "pc-t" }, p.title),
      h("p", { class: "pc-now" }, p.factory ? "Proposals to change Rihma itself, decided like any card." : (p.now || {}).line || ""),
      p.factory ? null : h("div", { class: "pc-stage" }, miniStages(p.stage), h("span", { class: "muted small" }, "Stage " + p.stage + " · " + cap(p.stage_name))),
      h("div", { class: "pc-foot" }, p.factory ? null : h("span", null, p.maturity + " · " + p.mode),
        mine ? chip("warning", "user", plural(mine, "card") + " for you") : h("span", { class: "muted" }, "Nothing for you"),
        p.stale_approvals ? chip("warning", "alert", p.stale_approvals + " stale") : null));
  }));
  const table = dataTable([{ label: "Project", value: (p) => h("a", { href: p.factory ? link(p.id, "inbox") : "#/p/" + enc(p.id) }, p.title) },
    { label: "Now", value: (p) => h("span", { class: "cell-now" }, projectNow(p), h("small", { class: "muted" }, (p.now || {}).line || "")) },
    { label: "Stage", value: (p) => (p.factory ? "-" : p.stage + " " + cap(p.stage_name)) }, { label: "Profile", value: (p) => (p.factory ? "-" : profileChip(p.profile, { short: true, noPreview: true })) },
    { label: "Maturity · mode", value: (p) => (p.factory ? "-" : p.maturity + " · " + p.mode) },
    { label: "Yours to decide", value: (p) => mineOf(p), num: true }, { label: "Open cards", key: "open_cards", num: true }], shown, "Projects");
  fill(main,
    pageHead("Projects", "Each thread runs from a business need to the running service. " + plural(products.length, "project") + " in this factory.",
      { icon: "folder", actions: [button("New project", { icon: "plus", kind: "primary", "data-control": "new_project", onclick: () => newProjectModal() })] }),
    h("div", { class: "filters" }, filter, h("span", { class: "spacer" }),
      segmented("proj-view", [["cards", "Cards", "catalogue"], ["table", "Table", "table"]], mode, (v) => { setViewChoice("projects", v); nav.route(true); }, { label: "View", iconOnly: true })),
    !products.length ? h("div", { class: "card intro" }, empty("folder", "No project yet. Rihma turns a business need into a running, monitored service.",
      button("Start your first project", { icon: "plus", kind: "primary", onclick: () => newProjectModal() })))
      : !shown.length ? empty("check-circle", "No project waits on you right now.") : mode === "table" ? table : cards);
}

// -- the Inbox across projects ------------------------------------------------------------------

function inboxCard(c) {
  const isPlan = c.kind === "approval" && (c.refs || {}).scope === "plan";
  const pl = c.payload || {};
  const body = [];
  if (c.kind === "update" && pl.views) {
    const v = pl.views;
    body.push(S.lens === "delivery" || S.lens === "insight" ? h("pre", { class: "json" }, JSON.stringify(v.developer, null, 2))
      : h("p", null, S.lens === "business" ? v.business : v.expert));
  } else if (c.body && c.body.trim() !== c.title.trim()) body.push(h("p", { class: "body" }, c.body));
  if (c.kind === "concept") body.push(h("p", { class: "muted small" }, profileChip(pl.profile), " · ", pl.maturity, " · ", pl.mode, " · edit it on the ", h("a", { href: "#concept-" + c.id }, "Square")));
  let action;
  if (c.kind === "question") action = h("a", { class: "btn small", href: link(c.project, "questions", (c.refs || {}).question), "data-control": "answer" }, icon("comment"), "Answer the question");
  else if (isPlan) action = h("a", { class: "btn small primary", href: link(c.project, "plan") }, icon("arrow-right"), "Open the plan to approve it");
  else if (c.kind === "concept") action = h("a", { class: "btn small", href: "#/square" }, icon("square"), "Validate it on the Square");
  else action = decideForm(c.project, c);
  return h("article", { class: "card decision inbox-card", "data-id": c.id },
    h("div", { class: "hd" }, h("span", { class: "dec-ic" }, icon(KIND_ICON[c.kind] || "inbox")), h("span", { class: "label" }, KIND_LABEL[c.kind] || c.kind),
      h("span", { class: "mono muted small" }, c.id), h("a", { class: "small", href: c.project === FACTORY_PID ? link(c.project, "inbox") : "#/p/" + enc(c.project) }, c.project_title),
      c.blocking ? chip("warning", "alert", "Blocking") : null, h("span", { class: "muted small ib-age" }, icon("clock"), ago(c.created))),
    h("h3", { class: "card-t" }, c.title), body,
    c.kind === "change" && impactPanelFor ? impactPanelFor(c.project, c) : null, action);
}
export async function renderInboxAll(seq) {
  const main = $("#main");
  const done = skeleton(main, "the Inbox");
  const inbox = await api("GET", "/api/inbox?persona=" + enc(S.persona));
  done();
  if (seq !== S.seq) return;
  document.title = "Inbox · Rihmasto.ai";
  S.inboxCount = inbox.count;
  const group = viewChoice("inbox", "kind");
  const groups = {};
  const keyOf = (c) => {
    if (group === "project") return c.project_title;
    if (group === "age") {
      const hrs = c.created ? (Date.now() - Date.parse(c.created)) / 3600000 : 0;
      return hrs < 24 ? "Today" : hrs < 24 * 7 ? "This week" : "Older";
    }
    return KIND_LABEL[c.kind] || c.kind;
  };
  // decisions that hold work up first; the panel's many questions last
  const ORDER = ["escalation", "approval", "validation", "deploy_gate", "incident", "change", "update", "concept", "holdout_ruling", "road", "trust", "question"];
  const rank = (c) => (group === "kind" ? ORDER.indexOf(c.kind) : 0);
  inbox.cards.slice().sort((a, b) => rank(a) - rank(b) || String(a.created || "").localeCompare(String(b.created || "")))
    .forEach((c) => { (groups[keyOf(c)] = groups[keyOf(c)] || []).push(c); });
  fill(main,
    pageHead("Inbox", "Every card the " + personaLabel(S.persona) + " persona may decide, across every project and Rihma itself. Each decision is signed with your name.",
      { icon: "inbox" }),
    h("div", { class: "filters" }, h("span", { class: "muted" }, plural(inbox.count, "card") + " for you"), h("span", { class: "spacer" }),
      segmented("inbox-group", [["kind", "By kind"], ["project", "By project"], ["age", "By age"]], group, (v) => { setViewChoice("inbox", v); nav.route(true); }, { label: "Group the cards" })),
    inbox.cards.length ? Object.entries(groups).map(([g, cs]) => h("section", { class: "ib-group" }, h("h2", { class: "ib-h" }, g, h("span", { class: "count" }, String(cs.length))),
      h("div", { class: "cards" }, cs.map(inboxCard))))
      : empty("check-circle", "Nothing needs you right now."));
}

// -- settings: embeds, appearance, sign-in -------------------------------------------------------

export function openEmbedForm(prefill) {
  const pf = prefill || {};
  const may = ((S.meta && S.meta.embed_creators) || []).includes(S.persona);
  const kinds = h("div", { class: "seg" }, ["feedback", "need"].map((k) => h("label", { class: "seg-b radio" },
    h("input", { type: "radio", name: "em-kind", value: k, checked: (pf.kind || "feedback") === k }), k === "feedback" ? "Feedback on a product" : "A business need")));
  const project = h("select", { "aria-label": "Project" }, (S.projects || []).filter((p) => !p.factory).map((p) => h("option", { value: p.id, selected: p.id === pf.project }, p.title)));
  const origins = h("textarea", { rows: "2", placeholder: "https://shop.example.fi", "aria-label": "Allowed websites" }, pf.origins || "");
  const label = h("input", { maxlength: "80", value: pf.label || "", placeholder: "Shop feedback", "aria-label": "Label" });
  const brief = h("textarea", { rows: "2", maxlength: "600", placeholder: "One or two sentences the chat may say about the product", "aria-label": "Public brief" }, pf.brief || "");
  const form = h("form", { class: "embed-form", novalidate: true },
    h("p", { class: "note" }, icon("shield"), h("span", null, "The chat sees nothing of the project's records. It can only file feedback as a change, or a need as a signal.")),
    h("fieldset", null, h("legend", null, "What it collects"), kinds),
    h("div", { class: "field" }, h("label", null, "Project (for feedback)"), project),
    h("div", { class: "field" }, h("label", null, "Allowed websites, one per line"), origins),
    h("div", { class: "row2" }, h("div", { class: "field" }, h("label", null, "Label"), label), h("div", { class: "field" }, h("label", null, "Public brief"), brief)),
    h("div", { class: "btns" }, h("button", { type: "submit", class: "btn primary", "data-control": "create_embed", disabled: !may || null }, icon("message-square"), "Create the chat"),
      may ? h("span", { class: "muted small" }, "Signed with your name. The key is shown once.") : h("span", { class: "muted small" }, "A " + ((S.meta && S.meta.embed_creators) || []).map(personaLabel).join(", ") + " persona creates an embed.")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!needPerson()) return;
    const kind = form.querySelector("input[name=em-kind]:checked").value;
    act(form, async () => {
      const out = await api("POST", "/api/embeds", Object.assign({ kind, project: kind === "feedback" ? project.value : null,
        origins: origins.value.split(/[\s,]+/).filter(Boolean), label: label.value.trim(), brief: brief.value.trim() }, signed()));
      showKey(out);
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
function showKey(out) {
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
    h("p", { class: "muted small" }, "Allowed: " + out.embed.origins.join(", ") + ". Revoke it any time in Settings.")), { icon: "check-circle" });
}

export async function renderSettings(seq) {
  const main = $("#main");
  const done = skeleton(main, "settings");
  const [em, projects] = await Promise.all([api("GET", "/api/embeds"), api("GET", "/api/projects")]);
  done();
  if (seq !== S.seq) return;
  S.projects = projects;
  document.title = "Settings · Rihmasto.ai";
  const may = (em.creators || []).includes(S.persona);
  const t = currentTheme();
  const rows = em.embeds.map((e) => {
    const revoke = e.state === "active" && may ? button("Revoke", { icon: "x", kind: "small", key: "revoke:" + e.id }) : null;
    if (revoke) {
      revoke.addEventListener("click", () => {
        if (!needPerson()) return;
        act(revoke.parentNode, async () => {
          await api("POST", "/api/embeds/" + enc(e.id) + "/revoke", signed());
          say(e.id + " is revoked: the website's chat stops at once.", "good");
          await nav.rerender();
        });
      });
    }
    return h("li", { class: "emb-row" }, h("span", { class: "cat-ic" }, icon(e.kind === "feedback" ? "message-square" : "lightbulb")),
      h("div", { class: "sig-b" }, h("b", null, (e.label || e.id) + " "), h("span", { class: "mono muted small" }, e.id),
        h("div", { class: "sig-m" }, h("span", null, e.kind === "feedback" ? "Feedback on " + ((projects.find((p) => p.id === e.project) || {}).title || e.project) : "Business needs"),
          h("span", null, e.origins.join(", ")), h("span", null, plural(e.messages || 0, "message")), h("span", null, "by " + e.created_by + " · " + ago(e.created)))),
      e.state === "active" ? chip("good", "check-circle", "Active") : chip("neutral", "x-circle", "Revoked"), revoke);
  });
  const themeRow = (name, label, options, value, key) => h("div", { class: "set-row" }, h("span", null, label),
    segmented(name, options, value, (v) => setTheme({ [key]: v }), { label }));
  const scale = h("input", { type: "range", min: "0.9", max: "1.25", step: "0.05", value: String(t.font_scale || 1), "aria-label": "Text size" });
  scale.addEventListener("change", () => setTheme({ font_scale: Number(scale.value) }));
  fill(main,
    pageHead("Settings", "Embeds for websites, how the cockpit looks, and sign-in links.", { icon: "settings" }),
    card({ title: "Embeds: a chat window for a website", icon: "message-square", id: "embeds",
      tools: [button("Create a chat", { icon: "plus", kind: "small primary", "data-control": "create_embed", onclick: () => openEmbedForm() })],
      info: "An embed has exactly one capability: it files end-user feedback as a change, or a business need as a signal. It answers only from a public brief "
        + "and never from the project's records. Its key is shown once and kept only as a hash; a person revokes it with one click." },
    h("p", { class: "note" }, icon("shield"), h("span", null, "An embed sees nothing of a project's records: it only files what people tell it.")),
    embedBaseNote(em),
    rows.length ? h("ul", { class: "emb-list" }, rows) : empty("message-square", "No embed yet.")),
    h("div", { class: "sq-cols" },
      card({ title: "Appearance", icon: "sun", info: "Kept with your layout for the lens you are in, and in this browser." },
        themeRow("set-mode", "Mode", [["dark", "Dark", "moon"], ["light", "Light", "sun"], ["system", "System", "monitor"]], t.mode, "mode"),
        h("div", { class: "set-row" }, h("span", null, "Accent"), h("div", { class: "swatches", role: "radiogroup", "aria-label": "Accent" }, ACCENTS.map((a) => {
          const b = h("button", { type: "button", role: "radio", "aria-checked": String(t.accent === a), class: "swatch acc-" + a, "aria-label": cap(a), tip: cap(a) });
          b.addEventListener("click", () => { setTheme({ accent: a }); nav.route(true); });
          return b;
        }))),
        themeRow("set-density", "Density", [["comfortable", "Comfortable"], ["compact", "Compact"]], t.density, "density"),
        themeRow("set-radius", "Corners", [["soft", "Soft"], ["crisp", "Crisp"]], t.radius, "radius"),
        h("div", { class: "set-row" }, h("span", null, "Text size"), scale)),
      card({ title: "Sign-in and the assistant", icon: "key" },
        h("p", null, "A sign-in link works once. For another tab, make a new one-use link (valid for 10 minutes) from the person menu."),
        button("Link for another tab", { icon: "link", onclick: () => nav.openPerson && nav.openPerson(false) }),
        h("p", { class: "muted small" }, "The assistant " + (S.meta.assistant === "gnomon" ? "asks Gnomon in the analyst lane"
          : S.meta.assistant === "model" ? "asks an injected model" : "answers from the cockpit map")
          + ". It proposes; you confirm."))));
}

// -- new project: a work profile, a maturity and a mode ---------------------------------------------

// What Rihma proposed, said plainly where the person is looking: the profile, the words it rests on,
// and how sure the rule is. When nothing in the text pointed anywhere, it says so instead of quietly
// keeping the default (which looks like a button that did nothing).
function showProposal(target, out, warning) {
  if (!out) {
    fill(target, h("div", { class: "proposal warn", role: "status" }, icon("alert"), h("span", null, warning)));
    return;
  }
  const label = profileOf(out.profile).label;
  const words = (out.basis || []).filter((w) => !/^no keyword/.test(w));
  const ranked = Object.entries(out.scores || {}).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]);
  const runnerUp = ranked.length > 1 && ranked[1][1] >= ranked[0][1] - 1 ? profileOf(ranked[1][0]).label : null;
  const uncertain = out.uncertain || !words.length || Boolean(runnerUp);
  const why = words.length
    ? h("span", null, "From the words ", ...words.flatMap((w, i) => [i ? ", " : null, h("code", { class: "kw" }, w)]), ".")
    : h("span", null, "Nothing in the text pointed to a kind of work, so Rihma kept the default. Add a few words about what it does, or pick one below.");
  fill(target, h("div", { class: "proposal" + (uncertain ? " warn" : " good"), role: "status" },
    icon(uncertain ? "alert" : "sparkles"),
    h("div", null,
      h("b", null, "Rihma proposes: " + label),
      h("p", { class: "small" }, why),
      uncertain && runnerUp ? h("p", { class: "small" }, "Close call: it could also be " + runnerUp + ". Pick the one that fits.") : null,
      !uncertain ? h("p", { class: "small muted" }, "Pick another below if it fits better.") : null)));
}

export function newProjectModal() {
  const profiles = (S.meta && S.meta.profiles) || [];
  let chosen = "web_service";
  const title = h("input", { maxlength: "200", placeholder: "for example: Equipment loans", "aria-label": "Title" });
  const source = h("textarea", { rows: "4", maxlength: "200000", placeholder: "For example: Our team keeps losing track of who borrowed the drills and laptops. We want a simple way to lend and return things.", "aria-label": "The need" });
  const by = h("input", { maxlength: "200", value: S.person, autocomplete: "name", "aria-label": "Requested by" });
  const basis = h("p", { class: "muted small propose-basis", "aria-live": "polite" });
  const grid = h("div", { class: "prof-grid", role: "radiogroup", "aria-label": "Work profile" });
  const draw = () => fill(grid, profiles.map((p) => {
    const b = h("button", { type: "button", role: "radio", "aria-checked": String(p.id === chosen), class: "prof-card", "data-key": "profile:" + p.id },
      h("span", { class: "prof-top" }, h("span", { class: "cat-ic" }, icon(p.icon)), p.status === "preview" ? chip("accent", "eye", "Preview") : chip("good", "check", "Ready")),
      h("b", null, p.label), h("span", { class: "prof-s" }, p.summary), h("small", null, (((S.meta.deliverables || {})[p.deliverable]) || "").split(":")[0]));
    b.addEventListener("click", () => { chosen = p.id; draw(); });
    return b;
  }));
  draw();
  const propose = button("Let Rihma propose", { icon: "sparkles", kind: "small", "data-control": "propose_profile" });
  propose.addEventListener("click", () => act(propose.parentNode, async () => {
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
    showProposal(basis, out);
    const card = grid.querySelector('[aria-checked="true"]');
    if (card) {
      card.classList.add("just-proposed");
      card.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      setTimeout(() => card.classList.remove("just-proposed"), 1600);
    }
  }));
  const maturity = segmented("np-maturity", Object.keys(S.meta.maturities).map((m) => [m, cap(m)]), "demo", () => {}, { label: "Maturity" });
  const mode = segmented("np-mode", Object.keys(S.meta.modes).map((m) => [m, cap(m)]), "mixed", () => {}, { label: "Mode" });
  const val = (seg) => (seg.querySelector('[aria-checked="true"]') || {}).dataset.key.split(":")[1];
  const form = h("form", { class: "np-form", novalidate: true },
    h("div", { class: "field" }, h("label", null, "Title"), title),
    h("div", { class: "field" }, h("label", null, "The need, the idea or a written spec"), source),
    h("div", { class: "np-prof-h" }, h("span", { class: "label-h" }, "Work profile"), propose), basis, grid,
    h("div", { class: "row2" }, h("div", { class: "field" }, h("label", null, "Maturity"), maturity, h("small", { class: "muted" }, "Explore, demo, pilot or production: which stages and gates run.")),
      h("div", { class: "field" }, h("label", null, "Mode"), mode, h("small", { class: "muted" }, "Who answers the panel's questions: people, the factory, or both."))),
    h("div", { class: "field" }, h("label", null, "Requested by"), by),
    h("div", { class: "btns" }, h("button", { type: "submit", class: "btn primary", "data-control": "new_project" }, icon("plus"), "Create and start the intake"),
      h("span", { class: "muted small" }, "Nothing is built until the questions that block it are answered.")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const data = { title: title.value.trim(), source: source.value, profile: chosen, maturity: val(maturity), mode: val(mode),
      requested_by: by.value.trim(), persona: S.persona };
    if (!data.title || !data.source.trim()) { say("A new project needs a title and the need.", "warning"); (data.title ? source : title).focus(); return; }
    if (!data.requested_by) { say("Name the person who asks for it.", "warning"); by.focus(); return; }
    act(form, async () => {
      const out = await api("POST", "/api/projects", data);
      closeModal();
      say("Project " + out.project.id + " is created. Its intake runs as job " + out.job.id + ".", "good");
      location.hash = "#/p/" + enc(out.project.id) + "/overview";
    });
  });
  openModal("New project", form, { icon: "plus", wide: true });
}
void iconButton; void infoButton; void attachTip; void local; void fmtAge; void STAGE_ICON; void $$;
