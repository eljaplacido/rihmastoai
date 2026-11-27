/* Self-healing in the cockpit (FR-HEAL1, docs/guides/self-healing.md): never a dead end.

   - The central error handling: a view that fails to load or draw, an action that fails, and an error nobody
     caught all show what happened in plain words, with "Try again", the remedies Rihmasto knows (learned ones
     first: "Rihmasto has seen this before") and "Investigate with Rihma", in place of a bare error. A failure the
     server met is already an incident (its answer names it); one the page met is reported as one, signed.
   - The Incidents page and a project's Incidents tab: open, investigating, fixed and learned; each incident's
     context, remedies, investigation (with its trace, in the incident's channel thread), fix and pull request;
     What Rihmasto learned (approve once, retire); the feedback proposals to approve.
   - "Something's wrong here" and "This is unclear / this is wrong" at the foot of every view and on each Ask
     Rihma answer; the wording people approved replaces the words in its view. */

import {
  S, $, $$, h, fill, icon, chip, button, api, enc, say, needPerson, signed, empty, fmtAt, pageHead, card, nav,
  openModal, closeModal, plural, ago, AuthError, segmented,
} from "./core.js";

const STATE = { open: ["warning", "alert", "Open"], investigating: ["info", "search", "Investigating"],
  fixed: ["good", "check-circle", "Fixed"], learned: ["good", "sparkles", "Learned"] };
const H = { filter: "", wording: null, reported: new Set(), shownAuto: new Set() };

function stateChip(s) { const [tone, ic, word] = STATE[s] || ["neutral", "info", s]; return chip(tone, ic, word); }
function base(pid) { return pid && pid !== "_factory" ? "/api/projects/" + enc(pid) + "/incidents" : "/api/incidents"; }
function personSet() { return !!(S.person || "").trim(); }

// -- reporting ------------------------------------------------------------------------------------------------

/* Report what the page met as an incident (signed with the person chip). Without a name it is not recorded, and
   the panel says so; the server's own failures are recorded by the server whatever the page does. */
export async function report(kind, where, message, extra) {
  if (!personSet()) return null;
  const o = extra || {};
  const key = kind + "|" + where + "|" + message;
  if (o.once && H.reported.has(key)) return null;
  H.reported.add(key);
  try {
    const out = await api("POST", "/api/incidents", Object.assign({ kind, where, message: String(message || "").slice(0, 1900),
      project: o.pid || (S.route && S.route.pid) || "", words: o.words || "", error_class: o.errorClass || "",
      job: o.job || "", context: Object.assign({ view: where, route: location.hash }, o.context || {}) }, signed()));
    return out.incident;
  } catch (e) { return null; }
}

// What to show for an error: the server's incident when it opened one, else the page's own report.
async function incidentFor(err, where, pid) {
  if (err && err.incident) return { id: err.incident.id, summary: err.incident.summary, offer: err.incident.offer };
  // a read the server refused or could not do is not a drawing error (FR-NVL3): only the page's own is
  const kind = err && err.status === 403 ? "refused" : err && err.status ? "action_failed" : "view_broken";
  const inc = await report(kind, where, (err && err.message) || String(err), { pid, once: true,
    errorClass: err && err.name, context: { status: err && err.status, browser: err && err.stack ? String(err.stack).slice(0, 1500) : null } });
  return inc ? { id: inc.id, summary: inc.summary, offer: inc.offer } : null;
}

// -- remedies ---------------------------------------------------------------------------------------------------

export async function takeRemedy(inc, a, opts) {
  const o = opts || {};
  if (a.kind === "investigate") return investigate(inc.id, o.pid);
  if (a.kind === "retry_read" || a.kind === "retry") {
    if (o.retry) return o.retry();
    if (nav.rerender) return nav.rerender();
    return null;
  }
  if (!needPerson()) return null;
  const out = await api("POST", "/api/incidents/" + enc(inc.id) + "/remedy", Object.assign({ remedy: a.id }, signed()));
  if (a.kind === "link" && a.href) { location.hash = a.href; return out; }
  if (a.kind === "explain") {
    if (a.learned && nav.rerender) nav.rerender();     // its use is counted: What Rihmasto learned shows it
    openModal(a.label, h("div", { class: "heal-explain" }, h("p", null, a.text || a.why || ""),
      a.command ? h("pre", { class: "mono small" }, a.command) : null), { icon: "info" });
    return out;
  }
  if (a.kind === "api" && a.path) {
    const done = await api(a.method || "POST", a.path, signed());
    say(a.label + ": started" + (done && done.job ? " as job " + done.job.id : "") + ".", "good");
    return done;
  }
  if (a.kind === "retry_job" && out.job) say("Job " + out.job.id + " started again by " + S.person.trim() + ".", "good");
  return out;
}

function remedyButtons(inc, opts) {
  const offer = inc.offer || { remedies: [] };
  return h("div", { class: "btns heal-remedies" }, (offer.remedies || []).map((a, i) =>
    button(a.label, { kind: i === 0 && !(opts && opts.quiet) ? "primary" : (a.kind === "investigate" ? "quiet" : ""), icon: a.kind === "investigate" ? "sparkles" : a.learned ? "sparkles" : null,
      key: "remedy:" + inc.id + ":" + a.id, "data-control": a.kind === "investigate" ? "investigate_incident" : "take_remedy", tip: a.why || null,
      onclick: async (e) => {
        const b = e.currentTarget; b.disabled = true;
        try { await takeRemedy(inc, a, opts); } catch (err) { if (!(err instanceof AuthError)) say(err.message, "critical"); }
        finally { if (b.isConnected) b.disabled = false; }
      } })));
}

// -- the panel shown in place of an error ---------------------------------------------------------------------------

/* Replaces a dead end: what happened, the remedies, Try again, Investigate, report. ``where`` names the view. */
export function incidentPanel(err, where, opts) {
  const o = opts || {};
  const box = h("div", { class: "heal-panel", role: "alert", "data-incident": "" });
  const retry = async () => {
    const ok = o.retry ? await o.retry() : (nav.route ? (await nav.route(true), true) : false);
    const id = box.dataset.incident;
    if (ok !== false && id && personSet()) {     // trying again worked: Rihmasto learns that it does
      api("POST", "/api/incidents/" + enc(id) + "/resolve", Object.assign({ how: { kind: "retry_read" } }, signed())).catch(() => null);
    }
  };
  const draw = (inc) => {
    if (inc) box.dataset.incident = inc.id;
    const offer = (inc && inc.offer) || {};
    fill(box, h("div", { class: "heal-head" }, h("span", { class: "heal-ic" }, icon("alert")),
      h("div", null, h("h2", { id: "view-title", tabindex: "-1" }, offer.title || "Something went wrong here"),
        h("p", { class: "heal-said" }, !inc ? plainWords(err) : offer.title && inc.summary.startsWith(offer.title) ? "Where: " + (inc.where || inc.summary.slice(offer.title.length).replace(/[().\s]/g, "")) : inc.summary),
        offer.explain ? h("p", { class: "muted small" }, offer.explain) : null,
        offer.seen_before ? h("p", { class: "heal-seen" }, icon("sparkles"), " ", offer.seen_before) : null)),
      h("div", { class: "btns" },
        button("Try again", { kind: "primary", icon: "refresh", key: "heal:retry", onclick: retry }),
        inc ? remedyButtons(Object.assign({}, inc, { offer: Object.assign({}, offer, { remedies: (offer.remedies || []).filter((a) => a.id !== "try_again") }) }), { pid: o.pid, retry, quiet: true }) : null,
        !inc && !(err && err.down) ? button("Report it", { icon: "flag", key: "heal:report", "data-control": "report_problem", onclick: async () => {
          if (!needPerson()) return;
          const made = await incidentFor(err, where, o.pid);
          if (made) draw(made);
        } }) : null,
        button("Back to Home", { kind: "quiet", icon: "home", key: "heal:home", onclick: () => { location.hash = "#/home"; } })),
      h("p", { class: "muted small" }, inc ? ["Incident ", h("a", { href: o.pid ? "#/p/" + enc(o.pid) + "/incidents" : "#/incidents", "data-control": "incidents_open" }, inc.id),
        " keeps what happened, signed and masked."] : err && err.down ? "Nothing is reported while the cockpit is down: start it again (rihmasto-cockpit), then Try again."
        : personSet() ? "Report it: Rihmasto keeps what happened and can investigate it." : "Set your name in the person chip and Report it: Rihmasto keeps what happened and can investigate it."));
    const auto = offer.auto;
    if (auto && inc && !H.shownAuto.has(inc.id) && auto.kind === "link" && auto.href) {   // an approved, safe remedy
      H.shownAuto.add(inc.id);
      say("Rihmasto applied what fixed this before: " + auto.label + ".", "info");
      location.hash = auto.href;
    }
  };
  draw(null);
  if (err && err.down) return box;     // the server is down: nothing can be recorded until it is back
  incidentFor(err, where, o.pid).then((inc) => { if (inc && box.isConnected) draw(inc); });
  return box;
}

function plainWords(err) {
  const m = (err && err.message) || String(err || "");
  if (/^internal error: \w+$/.test(m)) return "The cockpit hit a bug while answering. It kept serving: try again, or have Rihma investigate.";
  if (err && (err.status === 404 || err.status === 410)) return m;
  return m || "The page met an error it did not expect.";
}

/* A project that is not here (removed, or never there) or whose project.json cannot be read: what happened and the
   way back, never a bug report (FR-NVL3). */
export function goneProject(err, pid) {
  const unreadable = err && err.status === 400 && /cannot be read \(project\.json/.test(err.message || "");
  return h("div", { class: "heal-panel heal-gone", role: "alert", "data-gone": unreadable ? "unreadable" : "removed",
    "data-nvl": unreadable ? null : "1" },
    h("div", { class: "heal-head" }, h("span", { class: "heal-ic" }, icon(unreadable ? "alert" : "info")),
      h("div", null, h("h2", { id: "view-title", tabindex: "-1" }, unreadable ? "This project cannot be read" : "This project is not here"),
        h("p", { class: "heal-said" }, err.message),
        h("p", { class: "muted small" }, unreadable ? "The other projects keep working." : "Its old link (" + pid + ") no longer opens a project."))),
    h("div", { class: "btns" },
      button("Open Projects", { kind: "primary", icon: "folder", key: "gone:projects", "data-control": "nav_projects", onclick: () => { location.hash = "#/projects"; } }),
      button("Back to Home", { kind: "quiet", icon: "home", key: "gone:home", onclick: () => { location.hash = "#/home"; } })));
}

/* Projects whose project.json cannot be read: named with how to restore them, the others go on (FR-NVL3). */
export function unreadableNote(list) {
  if (!list || !list.length) return null;
  return h("div", { class: "note warning", "data-unreadable": "", role: "status" }, icon("alert"), " ",
    h("div", null, list.map((b) => h("p", null, h("b", null, b.said + "."), " ", b.how, " ",
      h("a", { href: "#/p/" + enc(b.id), "data-control": "open_unreadable" }, "What happened")))));
}

// A failed action: the toast says what happened and offers the way on.
export function actionError(e) {
  const region = $("#status");
  if (!region) return;
  const inc = e && e.incident;
  const unexpected = e && !e.down && !e.plain && (e.status === 403 || e.status === 409 || e.status >= 500 || !e.status);
  const t = h("div", { class: "toast critical heal-toast" }, icon("x-circle"),
    h("span", null, inc ? inc.summary : e.message),
    inc ? button("Investigate with Rihma", { kind: "small", key: "toast:investigate", "data-control": "investigate_incident",
      onclick: () => investigate(inc.id, S.route && S.route.pid) }) : null,
    !inc && unexpected ? button("I did not expect this", { kind: "small", key: "toast:report", "data-control": "report_problem",
      onclick: async () => {
        if (!needPerson()) return;
        const made = await report(e.status === 403 ? "refused" : "action_failed", (S.route && (S.route.view || S.route.name)) || "the cockpit",
          e.message, { context: { status: e.status } });
        if (made) { t.remove(); say("Reported as " + made.id + ": open Incidents to investigate it.", "good"); }
      } }) : null,
    h("button", { type: "button", class: "icon-btn", "aria-label": "Dismiss", onclick: () => t.remove() }, icon("x")));
  region.replaceChildren(t);
}

// -- investigate --------------------------------------------------------------------------------------------------

export async function investigate(iid, pid) {
  if (!needPerson()) return null;
  const body = h("div", { class: "heal-inv" }, h("p", { class: "muted" }, "Rihma is reading the incident and the records…"));
  openModal("Investigate " + iid + " with Rihma", body, { icon: "sparkles", wide: true });
  try {
    const out = await api("POST", "/api/incidents/" + enc(iid) + "/investigate", signed());
    fill(body, investigation(out.incident, out.investigation, pid));
    return out;
  } catch (e) {
    if (!(e instanceof AuthError)) fill(body, h("p", { class: "w-warn" }, icon("alert"), e.message));
    return null;
  }
}

function traceLine(t) {
  if (!t) return null;
  const bits = [t.basis === "model" ? "Through " + (t.model || "a model") + " (" + (t.role || "analyst") + ")" : "By rule: " + (t.rests_on || "the records"),
    t.tokens ? t.tokens + " tokens" : null, t.duration_ms ? Math.round(t.duration_ms) + " ms" : null].filter(Boolean);
  return h("details", { class: "heal-trace" }, h("summary", null, "Trace: " + bits.join(" · ")),
    h("p", { class: "small" }, "Read: " + (t.read || []).join("; ")),
    (t.records || []).length ? h("p", { class: "small mono" }, "Records: " + t.records.join(", ")) : null);
}

function investigation(inc, found, pid) {
  if (!found) return null;
  const nxt = found.next || {};
  return h("div", { class: "heal-found" },
    h("p", null, chip("accent", "sparkles", found.classification), " ", found.diagnosis),
    h("p", null, h("b", null, "Next step: "), nxt.text || nxt.remedy || nxt.kind),
    traceLine(found.trace),
    h("p", { class: "small" }, h("a", { href: "#/p/" + enc(found.project) + "/agents" }, "The incident's thread: " + found.thread)),
    found.fix ? fixBlock(inc, found, pid) : null,
    // already investigating: the remedies without another "Investigate with Rihma"
    inc ? remedyButtons(Object.assign({}, inc, { offer: Object.assign({}, inc.offer,
      { remedies: ((inc.offer || {}).remedies || []).filter((a) => a.kind !== "investigate") }) }), { pid }) : null);
}

function fixBlock(inc, found) {
  const fixes = (inc && inc.fixes) || [];
  const last = fixes[0];
  return h("div", { class: "heal-fix panel" }, h("p", null, h("b", null, "A fix is proposed: "), found.fix.summary || "a reproducing test and the change"),
    last ? h("p", { class: "small" }, "Fix " + last.id + " on ", h("code", null, last.branch), ": the gate says ", h("b", null, last.gate.verdict),
      last.pr && last.pr.url ? [" · ", h("a", { href: last.pr.url, target: "_blank", rel: "noopener noreferrer" }, "the pull request")] : null) : null,
    h("div", { class: "btns" },
      !last ? button("Prepare the fix through the gate", { key: "fix:" + inc.id, "data-control": "prepare_fix", onclick: async (e) => {
        if (!needPerson()) return;
        e.currentTarget.disabled = true;
        try { const out = await api("POST", "/api/incidents/" + enc(inc.id) + "/fix", signed()); say("Fix " + out.fix.id + ": the gate says " + out.fix.gate.verdict + ".", out.fix.gate.verdict === "passed" ? "good" : "warning"); closeModal(); if (nav.rerender) nav.rerender(); }
        catch (err) { say(err.message, "critical"); }
      } }) : null,
      last && last.gate.verdict === "passed" && !(last.pr && last.pr.url) ? button("Approve and open the pull request", { kind: "primary", key: "pr:" + last.id, "data-control": "open_pr",
        onclick: async () => {
          if (!needPerson()) return;
          try { const out = await api("POST", "/api/fixes/" + enc(last.id) + "/pr", Object.assign({ approve: true }, signed()));
            say(out.fix.pr.url ? "Pull request opened: " + out.fix.pr.url : "The branch is ready: " + out.fix.pr.commands.join(" ; "), "good"); if (nav.rerender) nav.rerender(); }
          catch (err) { say(err.message, "critical"); }
        } }) : null));
}

// -- the Incidents page and tab ---------------------------------------------------------------------------------

function incidentCard(inc, pid) {
  const ctx = inc.context || {};
  const resolve = button("This fixed it", { key: "resolve:" + inc.id, "data-control": "resolve_incident", onclick: () => {
    if (!needPerson()) return;
    let warned = false;     // its check still fails: the first Send is refused with why; a second closes it anyway
    askText("Resolve " + inc.id, "What fixed it? Rihmasto proposes it as a remedy for next time.", "", async (how) => {
      try {
        await api("POST", "/api/incidents/" + enc(inc.id) + "/resolve", Object.assign({ how: { kind: "explain", text: how || "fixed by hand", label: (how || "Fixed by hand").slice(0, 80) }, note: how, anyway: warned }, signed()));
      } catch (e) {
        if (!warned && /still fails/.test(e.message)) { warned = true; throw new Error(e.message + ". Press Send again to close it anyway: what you wrote is kept as why."); }
        throw e;
      }
      say(inc.id + " resolved: what fixed it is proposed as a remedy.", "good"); if (nav.rerender) nav.rerender();
    });
  } });
  const done = inc.state === "fixed" || inc.state === "learned";
  return h("li", { class: "card heal-card", "data-id": inc.id },
    h("div", { class: "heal-top" }, stateChip(inc.state), h("b", { class: "mono" }, inc.id), h("span", { class: "heal-sum" }, inc.summary),
      inc.count > 1 ? chip("neutral", null, plural(inc.count, "time")) : null, h("span", { class: "muted small heal-at" }, ago(inc.last_seen || inc.opened))),
    inc.offer && inc.offer.seen_before ? h("p", { class: "heal-seen small" }, icon("sparkles"), " ", inc.offer.seen_before) : null,
    inc.investigation ? investigation(inc, inc.investigation, pid) : null,
    !done && !inc.investigation ? remedyButtons(inc, { pid }) : null,
    !done ? h("div", { class: "btns" }, resolve) : inc.resolution ? h("p", { class: "small muted" }, "Fixed by " + inc.resolution.by + ": " + ((inc.resolution.how || {}).label || "")) : null,
    h("details", { class: "heal-ctx" }, h("summary", null, "Context and fingerprint"),
      h("p", { class: "small mono" }, inc.fingerprint + " · " + inc.kind + " at " + inc.where + (inc.project ? " · " + inc.project : "")),
      ctx.request ? h("p", { class: "small mono" }, ctx.request.method + " " + ctx.request.path) : null,
      (ctx.trace || ctx.log || (ctx.job || {}).log_tail) ? h("pre", { class: "small heal-log" }, [].concat(ctx.trace || [], (ctx.job || {}).log_tail || []).slice(-15).join("\n")) : null,
      (inc.history || []).length ? h("ul", { class: "plain small" }, inc.history.map((x) => h("li", null, fmtAt(x.at) + " · " + x.event.replace(/_/g, " ") + " by " + x.person + (x.note ? ": " + x.note : "")))) : null));
}

function learnedList(rows) {
  if (!rows.length) return empty("sparkles", "Nothing learned yet: when an incident is resolved, what fixed it is proposed here.");
  return h("ul", { class: "plain heal-learned" }, rows.map((r) => h("li", { class: "heal-rm", "data-id": r.id },
    h("div", { class: "heal-top" }, chip(r.state === "approved" ? "good" : r.state === "retired" ? "neutral" : "warning", null, r.state),
      h("b", null, r.action.label), h("span", { class: "muted small" }, r.title || r.fingerprint)),
    h("p", { class: "small muted" }, plural(r.uses || 0, "use") + (r.auto_uses ? " (" + r.auto_uses + " on its own)" : "") + " · learned from " + r.learned_from.join(", ")
      + (r.last_used ? " · last used " + ago(r.last_used) : "") + (r.approved ? " · approved by " + r.approved.person : "") + " · " + remedyClaim(r.action)),
    h("div", { class: "btns" },
      r.state === "proposed" ? button("Approve remedy", { kind: "small", key: "rm-ok:" + r.id, "data-control": "approve_remedy", onclick: () => remedyAct(r.id, "approve") }) : null,
      r.state !== "retired" ? button("Retire remedy", { kind: "small quiet", key: "rm-off:" + r.id, "data-control": "retire_remedy", onclick: () => remedyAct(r.id, "retire") }) : null))));
}

/* What a remedy does when offered, as it behaves: only a safe link opens on its own once approved; words a person
   wrote are shown for a person to follow; anything else is always confirmed. */
export function remedyClaim(a) {
  if (a.kind === "explain") return "shows what fixed it last time: a person does it";
  if (a.safe && a.kind === "link") return "safe: opens on its own once approved";
  return "always confirmed";
}

async function remedyAct(rid, what) {
  if (!needPerson()) return;
  try { await api("POST", "/api/remedies/" + enc(rid) + "/" + what, signed()); say(rid + (what === "approve" ? " approved: offered first from now on." : " retired."), "good"); if (nav.rerender) nav.rerender(); }
  catch (e) { say(e.message, "critical"); }
}

function feedbackBlock(fb) {
  const open = (fb.proposals || []).filter((p) => p.state === "proposed");
  if (!open.length) return h("p", { class: "muted small" }, "No feedback waits on a decision. " + plural((fb.groups || []).length, "group") + " of feedback so far.");
  return h("ul", { class: "plain" }, open.map((p) => h("li", { class: "heal-rm", "data-id": p.id },
    h("p", null, chip("info", null, p.change.replace("_", " ")), " In ", h("b", null, p.where.view || "-"), ": “", p.from || "", "” → ",
      p.text ? h("b", null, "“" + p.text + "”") : h("i", null, "say the new words when you approve")), h("p", { class: "small muted" }, plural(p.items.length, "person's note", "people's notes")),
    h("div", { class: "btns" }, button("Approve wording change", { kind: "small", key: "fp-ok:" + p.id, "data-control": "approve_feedback", onclick: () => {
      if (!needPerson()) return;
      askText("Approve " + p.id, "The new words (applied from a data file, recorded)", p.text || "", async (text) => {
        await api("POST", "/api/feedback/" + enc(p.id) + "/settle", Object.assign({ verdict: "approve", text }, signed()));
        H.wording = null; say(p.id + " approved and applied.", "good"); if (nav.rerender) nav.rerender();
      });
    } })))));
}

// A small form in the dialog: one text, then ``done(text)``; an error stays in the dialog.
function askText(title, label, value, done) {
  const field = h("textarea", { id: "heal-ask", rows: 3, "aria-label": label });
  field.value = value || "";
  const warn = h("p", { class: "small", role: "alert" });
  const ok = button("Send", { kind: "primary", key: "heal-ask:ok", onclick: async () => {
    ok.disabled = true;
    try { await done(field.value.trim()); closeModal(); } catch (e) { warn.textContent = e.message; ok.disabled = false; }
  } });
  openModal(title, h("div", { class: "form" }, h("label", { for: "heal-ask" }, label), field, warn, h("div", { class: "btns" }, ok)), { icon: "edit" });
}

async function incidentsBody(pid) {
  const q = H.filter ? "?state=" + enc(H.filter) : "";
  const [d, fb] = await Promise.all([api("GET", base(pid) + q), pid ? Promise.resolve(null) : api("GET", "/api/feedback")]);
  const c = d.counts;
  const seg = segmented("heal-state", [["", "All (" + c.all + ")"], ["open", "Open (" + c.open + ")"], ["investigating", "Investigating (" + c.investigating + ")"],
    ["fixed", "Fixed (" + c.fixed + ")"], ["learned", "Learned (" + c.learned + ")"]], H.filter, (v) => { H.filter = v; if (nav.rerender) nav.rerender(); }, { label: "Incident state" });
  return h("div", { class: "heal-page", "data-sig": incidentsSig(d) }, seg,
    d.incidents.length ? h("ul", { class: "plain heal-list" }, d.incidents.map((i) => incidentCard(i, pid)))
      : empty("check-circle", H.filter ? "No incident is " + H.filter + "." : "No incident yet: when something fails, it shows here with what Rihmasto can do about it."),
    card({ title: "What Rihmasto learned", icon: "sparkles", id: "heal-learned", info: "A remedy is proposed from what resolved an incident. Approve it once and it is offered first; a safe link opens on its own, words are shown for a person to follow. Retire one to stop it." }, learnedList(d.learned || [])),
    fb ? card({ title: "Feedback", icon: "message-square", id: "heal-feedback", info: "Repeated “This is unclear” and “This is wrong” notes become wording, assistant rule or prompt changes a person approves." }, feedbackBlock(fb)) : null);
}

function incidentsSig(d) { return (d.incidents || []).map((i) => i.id + ":" + i.state + ":" + i.count).join(","); }

/* While the page is open, a new incident or a changed one shows without a reload (FR-HEAL1): the list is read again
   every 15 s and drawn again only when it changed, so an open detail is not closed for nothing. */
export const INCIDENTS_FRESH_MS = 15000;
function keepFresh(box, pid) {
  setTimeout(async () => {
    const page = box.querySelector(".heal-page");
    if (!box.isConnected || !page) return;
    try {
      const d = await api("GET", base(pid) + (H.filter ? "?state=" + enc(H.filter) : ""));
      if (box.isConnected && incidentsSig(d) !== page.dataset.sig) fill(box, await incidentsBody(pid));
    } catch (e) { /* the next round reads again */ }
    if (box.isConnected) keepFresh(box, pid);
  }, INCIDENTS_FRESH_MS);
}

export async function renderIncidents(seq) {
  const body = await incidentsBody(null);
  if (seq !== undefined && seq !== S.seq) return;
  document.title = "Incidents · Rihmasto";
  const box = h("div", { class: "heal-fresh" }, body);
  fill($("#main"), pageHead("Incidents", "What went wrong, what Rihmasto can do about it, and what it learned.", { icon: "alert" }), box);
  keepFresh(box, null);
}

export function viewIncidents(p) {
  const root = h("div", { class: "heal-view" }, h("p", { class: "muted" }, "Reading the incidents…"));
  incidentsBody(p.meta.id).then((b) => { if (root.isConnected) { fill(root, b); keepFresh(root, p.meta.id); } })
    .catch((e) => { if (root.isConnected) fill(root, incidentPanel(e, "incidents", { pid: p.meta.id })); });
  return root;
}

// Home and Review: a card while incidents are open.
export async function incidentsCard(box) {
  if (!box) return;
  let d;
  try { d = await api("GET", "/api/incidents?state=open"); } catch (e) { return; }
  if (!box.isConnected || !d.counts.open) return;
  fill(box, h("a", { class: "card rv-card heal-home", href: "#/incidents", "data-control": "incidents_open", "data-key": "home:incidents" },
    h("span", { class: "card-ic" }, icon("alert")), h("span", { class: "rv-card-t" }, h("b", null, plural(d.counts.open, "incident") + " open"),
      h("small", { class: "muted" }, (d.incidents[0] || {}).summary || "", " · Open the Incidents")), icon("chevron-right")));
}

// -- feedback and the foot of every view -----------------------------------------------------------------------------

export function feedbackForm(where) {
  if (!needPerson()) return;
  const kind = h("select", { id: "fb-kind", "aria-label": "Kind" }, h("option", { value: "unclear" }, "This is unclear"), h("option", { value: "wrong" }, "This is wrong"));
  const shown = h("input", { id: "fb-text", value: (where.text || "").slice(0, 200), "aria-label": "The words shown" });
  const words = h("textarea", { id: "fb-words", rows: 3, "aria-label": "What is unclear or wrong" });
  const suggest = h("input", { id: "fb-suggest", "aria-label": "Better words (optional)" });
  const send = button("Send feedback", { kind: "primary", key: "fb:send", onclick: async () => {
    try { const out = await api("POST", "/api/feedback", Object.assign({ kind: kind.value, where: Object.assign({}, where, { text: shown.value }), words: words.value,
      suggest: suggest.value, project: (S.route && S.route.pid) || "" }, signed()));
      closeModal(); say("Thank you: " + (out.feedback.proposal ? "it joins proposal " + out.feedback.proposal.id + ", for a person to approve." : "recorded."), "good"); }
    catch (e) { say(e.message, "critical"); }
  } });
  openModal("This is unclear / this is wrong", h("div", { class: "form" }, h("label", { for: "fb-kind" }, "Kind"), kind,
    h("label", { for: "fb-text" }, "The words shown"), shown, h("label", { for: "fb-words" }, "What is unclear or wrong"), words,
    h("label", { for: "fb-suggest" }, "Better words (optional)"), suggest, h("div", { class: "btns" }, send)), { icon: "message-square" });
}

export function footer(view) {
  return h("div", { class: "heal-foot", role: "group", "aria-label": "Feedback on this view" },
    button("Something's wrong here", { kind: "small quiet", icon: "flag", key: "foot:report", "data-control": "report_problem", onclick: () => {
      if (!needPerson()) return;
      askText("Something's wrong here", "What is wrong here? Rihmasto keeps it with this view's context.", "", async (words) => {
        if (!words) throw new Error("Say what is wrong, in your own words.");
        const made = await report("report", view, words, { words });
        if (!made) throw new Error("It could not be recorded: try again.");
        say("Reported as " + made.id + ". Open Incidents to investigate it.", "good");
      });
    } }),
    button("This is unclear / this is wrong", { kind: "small quiet", icon: "message-square", key: "foot:feedback", "data-control": "give_feedback",
      onclick: () => feedbackForm({ view, text: (window.getSelection && String(window.getSelection())) || ($("#view-title") || {}).textContent || "" }) }));
}

// After a view is drawn: the approved wording, and the foot.
export async function afterRender(main, view) {
  if (!main || !main.isConnected) return;
  if (!$(".heal-foot", main) && !$(".heal-panel", main)) main.append(footer(view));
  try {
    if (!H.wording) H.wording = (await api("GET", "/api/wording")).changes || [];
  } catch (e) { H.wording = []; }
  const mine = H.wording.filter((c) => !c.view || c.view === view);
  if (!mine.length) return;
  const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((n) => { const hit = mine.find((c) => c.from && n.nodeValue.trim() === c.from.trim()); if (hit) n.nodeValue = n.nodeValue.replace(hit.from.trim(), hit.to); });
}

// The Try view: a release whose product does not run offers the way on, never a link that leads nowhere.
export function notRunning(pid, tr) {
  return h("div", { class: "btns heal-notrun" },
    button("Why it is not running", { kind: "small", icon: "sparkles", key: "try:why", "data-control": "investigate_incident", onclick: async () => {
      if (!needPerson()) return;
      const made = await report("product_not_running", "try", "release " + (tr.release || "") + " does not run: nothing runs there now", { pid });
      if (made) await investigate(made.id, pid);
    } }),
    button("Start it on its road", { kind: "small", icon: "play", key: "try:start", "data-control": "take_remedy", onclick: async () => {
      if (!needPerson()) return;
      const made = await report("product_not_running", "try", "release " + (tr.release || "") + " does not run: nothing runs there now", { pid });
      const start = made && ((made.offer || {}).remedies || []).find((a) => a.id === "start_on_road");
      if (start) await takeRemedy(made, start, { pid }).catch((e) => say(e.message, "critical"));
    } }));
}

// Errors nobody caught: reported once, and said with the way on.
export function wireErrors() {
  const seen = (msg, stack) => {
    if (!S.token) return;
    report("view_broken", (S.route && (S.route.view || S.route.name)) || "the cockpit", msg, { once: true, context: { browser: String(stack || "").slice(0, 1500) } })
      .then((inc) => { if (inc) actionError({ message: msg, incident: { id: inc.id, summary: inc.summary } }); });
  };
  window.addEventListener("error", (e) => { if (e && e.message) seen(e.message, e.error && e.error.stack); });
  window.addEventListener("unhandledrejection", (e) => {
    const r = e && e.reason;
    if (r instanceof AuthError) return;
    seen((r && r.message) || String(r), r && r.stack);
  });
}
void $$;
