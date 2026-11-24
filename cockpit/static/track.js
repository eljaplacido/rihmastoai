/* Staying on track, autopilot in a sandbox and delegated decisions (kernel/track.py, kernel/autopilot.py,
   kernel/delegation.py; D-0017). The project header's Track pill, the Track view (the answer and its reasons,
   every figure with its basis, human checkpoints, the autopilot and the delegations) and the Home widget's
   rows. A figure that was not measured says so, never 0 or passed. Every write is signed with the person and
   persona and goes through the kernel, which decides whether it stands. */

import {
  S, $, h, icon, chip, api, act, say, signed, needPerson, nav, enc, link, personaLabel, orList, plural, pct, fmtAge,
  fmtAt, fmtMoney, card, empty, stageName,
} from "./core.js";

export const TRACK = {
  on_track: { tone: "good", icon: "check-circle", word: "On track" },
  at_risk: { tone: "warning", icon: "alert", word: "At risk" },
  off_track: { tone: "critical", icon: "stop", word: "Off track" },
  not_measured: { tone: "nm", icon: "dashed", word: "Not measured" },
};
const RUN_STATE = { running: ["info", "bot", "Autopilot running"], expired: ["warning", "clock", "Autopilot time is up"],
  stopped: ["neutral", "stop", "Autopilot stopped"] };
const DLG_STATE = { active: ["info", "bot", "Active"], expired: ["neutral", "clock", "Expired"], revoked: ["neutral", "x", "Revoked"] };
const UNTIL = [["2h", "2 hours"], ["8h", "8 hours"], ["1d", "1 day"], ["3d", "3 days"], ["7d", "7 days"]];
const FIGURES = [["baseline", "Approved plan"], ["tasks", "Tasks"], ["gate_first_round", "Gate, first round"],
  ["assumption_debt", "Assumption debt"], ["scope", "Scope changes"], ["blocking", "Holding the run"],
  ["time", "Time against the budget"], ["cost", "Cost against the budget"], ["posture", "Posture kept"]];

const ap = () => (S.meta && S.meta.autopilot) || {};
const mayRun = () => (ap().may_run || []).includes(S.persona);

// The answer as a chip: on track, at risk, off track or not measured, with its first reasons as the tip.
export function trackState(t) {
  if (!t) return chip("nm", "dashed", "Track not read");
  const st = TRACK[t.state] || TRACK.not_measured;
  const why = (t.reasons || []).slice(0, 3).map((r) => r.why).join("; ") || t.basis || "";
  return chip(st.tone, st.icon, st.word, { tip: why });
}

// The project header's pill: the answer, a checkpoint due and a running autopilot; it opens the Track view.
export function trackPill(p) {
  const t = p.track;
  if (!t) return null;
  const st = TRACK[t.state] || TRACK.not_measured;
  const extra = [(t.due || []).length ? "checkpoint due" : null, (t.autopilot || {}).holding ? "autopilot " + t.autopilot.state : null]
    .filter(Boolean);
  const why = (t.reasons || []).slice(0, 3).map((r) => r.why).join("; ") || t.basis || "";
  return h("a", { class: "chip " + st.tone + " track-pill", href: link(p.meta.id, "track"), "data-control": "track_pill",
    tip: (why ? why + ". " : "") + "Open the Track view." },
  icon(st.icon), h("span", null, "Track: " + st.word + (extra.length ? " · " + extra.join(" · ") : "")));
}

// One line about a project for lists: its first reason, or what its answer rests on.
export function reasonLine(r) {
  return (r.reasons || []).length ? r.reasons.map((x) => x.why).slice(0, 2).join("; ") : (r.basis || "");
}

// -- the figures --------------------------------------------------------------------------------------------

function value(key, f) {
  if (!f.measured) return null;
  if (key === "baseline") return f.by ? "approved by " + f.by : "the first compiled contract";
  if (key === "tasks") return f.done + " of " + f.total + " done";
  if (key === "gate_first_round") return pct(f.value) + (f.trend ? ", " + f.trend : "");
  if (key === "assumption_debt") return plural(f.value, "past due", "past due") + " of " + f.open + " open";
  if (key === "scope") return plural(f.value, "change");
  if (key === "blocking") return f.value ? plural(f.value, "card") + ", oldest " + fmtAge(f.oldest_hours) : "none";
  if (key === "time") return pct(f.value) + " of the time used";
  if (key === "cost") return fmtMoney(f.value, f.currency) + " of " + fmtMoney(f.budget, f.currency);
  if (key === "posture") return f.value ? "kept" + (f.posture ? " (" + f.posture + ")" : "") : "not kept";
  return String(f.value);
}

function figureTile(key, label, f, pid) {
  const v = value(key, f);
  const more = key === "blocking" && (f.cards || []).length ? h("ul", { class: "plain small" }, f.cards.slice(0, 3).map((c) =>
    h("li", null, h("a", { href: link(pid, "inbox", c.card), class: "mono" }, c.card), " " + c.kind + ", " + fmtAge(c.age_hours))))
    : key === "gate_first_round" && f.measured ? h("p", { class: "kpi-sub" }, f.trend_basis) : null;
  return h("div", { class: "kpi" + (f.measured ? "" : " nm"), "data-figure": key },
    h("div", { class: "kpi-h" }, h("span", null, label)),
    v === null ? h("div", { class: "kpi-v nm-text" }, "— Not measured") : h("div", { class: "kpi-v tr-v" }, v),
    h("p", { class: "kpi-sub" }, f.basis), more);
}

function verdictCard(t) {
  const st = TRACK[t.state] || TRACK.not_measured;
  const reasons = t.reasons || [];
  return card({ title: "The answer", icon: "flag", id: "tr-ans", info: "Deterministic: the same records give the same answer. "
    + "Each reason names the figure it rests on; the thresholds are kernel/track.py's." },
  h("div", { class: "att-v" }, chip(st.tone, st.icon, st.word)),
  reasons.length ? h("ul", { class: "plain tr-reasons" }, reasons.map((r) => h("li", null,
    chip(TRACK[r.level].tone, TRACK[r.level].icon, TRACK[r.level].word), " ", h("span", null, r.why),
    h("span", { class: "muted small" }, " · " + r.figure.replace(/_/g, " ")))))
    : h("p", null, t.basis));
}

// -- checkpoints ----------------------------------------------------------------------------------------------

function lookForm(pid, row) {
  const id = "tr-look-" + row.stage;
  const note = h("input", { id, maxlength: "2000", autocomplete: "off", placeholder: "what you saw (optional, recorded)" });
  const go = h("button", { type: "submit", class: "btn human primary", "data-control": "checkpoint_look", "data-key": "look:" + row.stage },
    "I looked at stage " + row.stage);
  const form = h("form", { class: "tr-look", novalidate: true, "aria-label": "Record a look at stage " + row.stage },
    h("div", { class: "field" }, h("label", { for: id }, "Note"), note), h("div", { class: "btns" }, go));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!needPerson()) return;
    act(form, async () => {
      await api("POST", "/api/projects/" + enc(pid) + "/checkpoints/" + row.stage + "/look",
        Object.assign({ note: note.value.trim() }, signed()));
      say("Your look at stage " + row.stage + " is recorded, signed as " + personaLabel(S.persona) + ".", "good");
      await rerenderTo("#tr-cp-h");
    });
  });
  return form;
}

function checkpointsCard(pid, t, settings) {
  const cp = t.checkpoints || { stages: [], due: [] };
  const lookers = ap().checkpoint_lookers || [];
  const rows = cp.stages.map((r) => h("li", { class: "tr-cp" },
    h("div", null, h("b", null, "Stage " + r.stage + ", " + (r.name || stageName(r.stage))), " ",
      r.due ? chip("warning", "eye", "Due: a person looks") : r.looked ? chip("good", "check-circle", "Looked at")
        : chip("neutral", "clock", "Not reached")),
    r.looked ? h("p", { class: "muted small" }, "by " + r.looked.by + " (" + personaLabel(r.looked.persona) + "), " + fmtAt(r.looked.at)
      + (r.looked.note ? ": " + r.looked.note : "")) : null,
    r.due && lookers.includes(S.persona) ? lookForm(pid, r) : null));
  return card({ title: "Human checkpoints", icon: "eye", id: "tr-cp", info: "Stage boundaries a person must look at. With hold "
    + "on, the pipeline stops at a due checkpoint until a person records a look." },
  cp.stages.length ? h("p", { class: "muted small" }, cp.hold ? "A due checkpoint holds the run until a person looks."
    : "Checkpoints are shown; they do not hold the run.") : h("p", null, "No checkpoint is set on this project."),
  cp.stages.length ? h("ul", { class: "plain" }, rows) : null,
  (ap().track_setters || []).includes(S.persona) ? settingsForm(pid, cp, settings) : h("p", { class: "muted small" },
    "A " + orList(ap().track_setters || []) + " sets checkpoints and a budget."));
}

function settingsForm(pid, cp, settings) {
  const budget = (settings || {}).budget || {};
  const boxes = [2, 3, 4, 5, 6, 7].map((n) => {
    const id = "tr-st-" + n;
    return h("div", { class: "choice" }, h("input", { type: "checkbox", id, value: String(n),
      checked: cp.stages.some((r) => r.stage === n) }), h("label", { for: id }, n + " " + stageName(n)));
  });
  const hold = h("input", { type: "checkbox", id: "tr-hold", checked: !!cp.hold });
  const due = h("input", { type: "date", id: "tr-due", value: budget.due || "" });
  const amount = h("input", { type: "number", id: "tr-amount", min: "0", step: "any", value: budget.amount === undefined ? "" : String(budget.amount) });
  const go = h("button", { type: "submit", class: "btn human", "data-control": "track_settings", "data-key": "tr-set" }, "Save checkpoints and budget");
  const form = h("form", { class: "tr-set", novalidate: true, "aria-label": "Checkpoints and budget" },
    h("fieldset", null, h("legend", null, "Checkpoints at stages"), h("div", { class: "choices tr-stages" }, boxes)),
    h("div", { class: "choice" }, hold, h("label", { for: "tr-hold" }, "A due checkpoint holds the run")),
    h("div", { class: "tr-row" }, h("div", { class: "field" }, h("label", { for: "tr-due" }, "Due date"), due),
      h("div", { class: "field" }, h("label", { for: "tr-amount" }, "Cost budget, in the price table's currency"), amount)),
    h("div", { class: "btns" }, go));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!needPerson()) return;
    const stages = boxes.map((b) => b.querySelector("input")).filter((i) => i.checked).map((i) => Number(i.value));
    const body = Object.assign({ checkpoints: stages, hold: hold.checked, due: due.value || "" }, signed());
    if (amount.value !== "") body.budget = Number(amount.value);
    act(form, async () => {
      await api("PUT", "/api/projects/" + enc(pid) + "/tracking", body);
      say("Checkpoints and budget are saved, signed as " + personaLabel(S.persona) + ".", "good");
      await rerenderTo("#tr-cp-h");
    });
  });
  return h("details", { class: "tr-details" }, h("summary", { "data-key": "tr-open" }, "Set checkpoints and a budget"), form);
}

// -- the autopilot ------------------------------------------------------------------------------------------

function decidedList(run) {
  const decided = run.decided || [];
  const declined = run.declined || [];
  return h("div", null,
    h("p", { class: "label-h" }, plural(decided.length, "card") + " decided by delegation " + run.delegation),
    decided.length ? h("ul", { class: "plain small" }, decided.map((d) => h("li", null, h("span", { class: "mono" }, d.card), " "
      + d.kind + ": " + d.verdict + " (rule " + d.rule + "), in the name of " + d.person + " as " + personaLabel(d.persona)))) : null,
    declined.length ? h("p", { class: "label-h" }, plural(declined.length, "card") + " left to a person") : null,
    declined.length ? h("ul", { class: "plain small" }, declined.map((d) => h("li", null, h("span", { class: "mono" }, d.card), " " + d.why))) : null);
}

function stopForm(pid, run) {
  const reason = h("input", { id: "ap-stop-r", maxlength: "2000", autocomplete: "off", placeholder: "for example: I am back" });
  const go = h("button", { type: "submit", class: "btn human primary", "data-control": "autopilot_stop", "data-key": "ap-stop" },
    "Stop the autopilot");
  const form = h("form", { novalidate: true, "aria-label": "Stop autopilot " + run.id },
    h("div", { class: "field" }, h("label", { for: "ap-stop-r" }, "Reason (optional, recorded)"), reason), h("div", { class: "btns" }, go));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!needPerson()) return;
    act(form, async () => {
      const out = await api("POST", "/api/projects/" + enc(pid) + "/autopilot/stop", Object.assign({ reason: reason.value.trim() }, signed()));
      say(run.id + " is stopped and its delegation revoked; what it held back is released."
        + (out && out.job ? " Its job " + out.job.id + " is still running: " + out.job.ending + "." : ""), "good");
      await rerenderTo('[data-key="ap-open"]');
    });
  });
  return form;
}

function startForm(pid) {
  const rules = ap().rules || {};
  const mine = (S.personas.find((x) => x.id === S.persona) || { decides: [] }).decides;
  const kinds = Object.keys(rules).map((k) => {
    const id = "ap-k-" + k;
    const may = mine.includes(k);
    return h("div", { class: "choice" }, h("input", { type: "checkbox", id, value: k, checked: may, disabled: !may,
      "aria-describedby": id + "-why" }), h("label", { for: id }, k), h("span", { class: "why", id: id + "-why" },
      may ? Object.values(rules[k])[0] : "a " + personaLabel(S.persona) + " may not decide it"));
  });
  const until = h("select", { id: "ap-until" }, UNTIL.map(([v, t]) => h("option", { value: v, selected: v === "8h" }, t)));
  const reason = h("input", { id: "ap-reason", maxlength: "2000", autocomplete: "off", placeholder: "for example: try it overnight" });
  const go = h("button", { type: "submit", class: "btn human primary", "data-control": "autopilot_start", "data-key": "ap-start" },
    "Start the autopilot");
  const form = h("form", { class: "ap-start", novalidate: true, "aria-label": "Start an autopilot" },
    h("fieldset", null, h("legend", null, "Delegate these cards to the factory's rules"), h("div", { class: "choices" }, kinds)),
    h("div", { class: "tr-row" }, h("div", { class: "field" }, h("label", { for: "ap-until" }, "Until"), until),
      h("div", { class: "field" }, h("label", { for: "ap-reason" }, "Reason (recorded)"), reason)),
    h("p", { class: "muted small" }, "It delivers only to a sandbox, sends events only to sandbox receivers and writes through no "
      + "connector. Never delegated: " + Object.keys(ap().never || {}).join(", ") + "."),
    h("div", { class: "btns" }, go));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!needPerson()) return;
    const chosen = kinds.map((k) => k.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
    if (!chosen.length) { say("Choose at least one kind of card to delegate.", "warning"); return; }
    act(form, async () => {
      const out = await api("POST", "/api/projects/" + enc(pid) + "/autopilot", Object.assign({ kinds: chosen,
        until: until.value, reason: reason.value.trim() }, signed()));
      say(out.run.id + " runs until " + fmtAt(out.run.until) + " as job " + out.job.id + ", in the name of "
        + S.person.trim() + " as " + personaLabel(S.persona) + ".", "good");
      await rerenderTo('[data-key="ap-stop"]');
    });
  });
  return form;
}

function autopilotCard(pid, a) {
  const run = a.run;
  const box = a.sandbox || {};
  const st = run ? RUN_STATE[run.state] || RUN_STATE.stopped : null;
  return card({ title: "Autopilot in a sandbox", icon: "bot", id: "tr-ap", info: "A person lets the factory run on its own for a "
    + "while: it decides only the card kinds delegated, by their rules, delivers only to a sandbox and stops for a person." },
  h("p", null, chip(box.sandbox ? "good" : "warning", box.sandbox ? "check-circle" : "alert", box.sandbox ? "Lands in a sandbox"
    : "Delivery waits for a person"), " ", h("span", { class: "muted small" }, box.why || "")),
  run ? h("p", null, chip(st[0], st[1], st[2]), " " + run.id + ", started by " + run.person + " (" + personaLabel(run.persona)
    + "), until " + fmtAt(run.until) + (run.stopped ? "; stopped by " + run.stopped.by + " " + fmtAt(run.stopped.at) : "")) : null,
  run ? decidedList(run) : h("p", { class: "muted" }, "No autopilot has run on this project."),
  !mayRun() ? h("p", { class: "muted small" }, "A " + orList(ap().may_run || []) + " starts or stops an autopilot.")
    : a.holding ? stopForm(pid, run) : h("details", { class: "tr-details" }, h("summary", { "data-key": "ap-open" }, "Start an autopilot"),
      startForm(pid)));
}

// -- delegations -----------------------------------------------------------------------------------------------

function mayRevoke(d) {
  const kinds = (S.meta.card_kinds || {});
  return d.person === S.person.trim() || d.kinds.some((k) => ((kinds[k] || {}).deciders || []).includes(S.persona));
}

function revokeButton(pid, d) {
  const b = h("button", { type: "button", class: "btn tiny", "data-control": "revoke_delegation", "data-key": "revoke:" + d.id,
    "aria-label": "Revoke " + d.id }, "Revoke");
  b.addEventListener("click", () => {
    if (!needPerson()) return;
    act(b.parentNode, async () => {
      await api("POST", "/api/projects/" + enc(pid) + "/delegations/" + enc(d.id) + "/revoke", signed());
      say(d.id + " is revoked: its next card waits for a person.", "good");
      await rerenderTo("#tr-dl-h");
    });
  });
  return b;
}

function delegationsCard(pid, list) {
  return card({ title: "Delegations", icon: "user", id: "tr-dl", info: "Card kinds a person let the factory's rules decide on "
    + "this project, until a time. Each decision names that person, their persona and the delegation." },
  list.length ? h("ul", { class: "plain" }, list.slice().reverse().map((d) => {
    const st = DLG_STATE[d.state] || DLG_STATE.expired;
    return h("li", { class: "tr-dl" }, h("div", null, h("b", { class: "mono" }, d.id), " ", chip(st[0], st[1], st[2]), " ",
      d.kinds.map((k) => k + " (" + d.rules[k] + ")").join(", ")),
    h("p", { class: "muted small" }, "by " + d.person + " (" + personaLabel(d.persona) + "), " + (d.state === "active" ? "until " : "ended ")
      + fmtAt(d.revoked ? d.revoked.at : d.until) + (d.revoked ? ", revoked by " + d.revoked.by : "") + (d.run ? ", for " + d.run : "")),
    d.state === "active" && mayRevoke(d) ? h("div", { class: "btns" }, revokeButton(pid, d)) : null);
  })) : h("p", { class: "muted" }, "Nothing is delegated on this project: every card waits for a person."));
}

// -- the view ---------------------------------------------------------------------------------------------------

async function rerenderTo(sel) {
  if (nav.rerender) await nav.rerender();
  const el = $(sel) || $("#view-title");
  if (el) { if (!el.hasAttribute("tabindex") && !/^(A|BUTTON|INPUT|SELECT|TEXTAREA|SUMMARY)$/.test(el.tagName)) el.setAttribute("tabindex", "-1"); el.focus(); }
}

export function viewTrack(p, inbox, ctx) {
  const pid = p.meta.id;
  const head = h("div", { class: "q" }, h("h2", { id: "view-title", tabindex: "-1" }, "Track"),
    h("p", null, "Is this project on track against its approved plan, and who keeps hold of it?"));
  const data = ctx.track;
  if (!data) return h("div", null, head, empty("flag", "The track could not be read."));
  const t = data.track;
  return h("div", { class: "tr-view" }, head,
    h("div", { class: "ev-grid" }, verdictCard(t), checkpointsCard(pid, t, data.settings)),
    h("section", { class: "section", "aria-labelledby": "tr-fig-h" }, h("h3", { id: "tr-fig-h" }, "Every figure, with its basis"),
      h("div", { class: "kpi-strip" }, FIGURES.map(([k, label]) => figureTile(k, label, t.figures[k] || { measured: false, basis: "not read" }, pid)))),
    h("div", { class: "ev-grid section" }, autopilotCard(pid, data.autopilot), delegationsCard(pid, data.autopilot.delegations || [])));
}
