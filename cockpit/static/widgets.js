/* The widget library. Each widget answers one question from one read model of GET /api/dashboard,
   and offers its data as a chart (or a list) and as a table: the same data in different views.
   Numbers carry their provenance (observed or derived) and their denominator; "not measured" is
   never shown as zero. */

import {
  S, h, icon, chip, fill, api, act, say, signed, needPerson, decides, personaLabel, link, enc, num, pct, plural,
  fmtAge, ago, fmtAt, fmtMoney, fmtMinutes, avatar, profileOf, profileChip, nowChip, healthChip, empty, button,
  KIND_LABEL, KIND_ICON, VERDICT_LABEL, CATALOGUE_STATE, HEALTH, EVIDENCE, NOW_STATE, FACTORY_PID, nav, stageName,
  download, attachTip, infoButton, orList, mayAct,
} from "./core.js";
import { columns, bars, stack100, segbar, waterfall, dataTable, legend, meter, SERIES, STATUS_MARK, tipBox } from "./charts.js";
import { TRACK, trackState } from "./track.js";
import { tileOn } from "./modules.js";
import {
  pick, tw, datum, kernelWord, stageWord, technical, localTime, basisWord, cardTitleEl, titleOf, nowSaid, activityLine,
  trackSaid, etaSaid, waitingCount, squareWord,
} from "./words.js";
const cap1 = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

const asOf = (d) => "as of " + localTime(d.generated_at);
export const PROV_NOTE = { observed: "Observed: counted directly from the records", derived: "Derived: computed from observed counts" };
const PROV_PLAIN = { observed: "counted", derived: "calculated" };

// The provenance word, with its meaning on hover and focus of the widget's ⓘ, and in the text for a screen reader.
// A business reader does not need it on every tile: it is said once, for a screen reader, and in the tooltip.
function foot(d, prov, denom) {
  return h("p", { class: "kpi-foot" }, technical() ? h("span", { class: "prov " + prov, tip: PROV_NOTE[prov] }, prov,
    h("span", { class: "vh" }, " (" + (PROV_NOTE[prov] || "").replace(/^\w+: /, "") + ")"))
    : h("span", { class: "vh" }, PROV_PLAIN[prov] || ""),
  denom ? h("span", null, denom) : null, h("span", { class: "fresh", tip: String(d.generated_at || "") }, asOf(d)));
}

function notMeasured(reason, compact) {
  return h("div", { class: "nm-box" + (compact ? " compact" : "") }, icon("dashed"),
    h("div", null, h("b", null, "Not measured yet"), h("p", null, reason)));
}

// -- read models that could not be read ------------------------------------------------------------
// GET /api/dashboard names each read model that failed in `problems` ("timeline: TypeError") and
// answers with an empty default for it. A widget built on one says so; it never shows that default as
// "nothing yet". The names are the server's: its safe() names and the project status functions, plus
// "inbox" when the persona's Inbox (the open questions the decisions count) could not be read.
const PROBLEM_SOURCES = {
  kpi_strip: ["now", "decisions", "inbox", "gate_trend", "coverage", "catalogue"], square: ["square"], pipeline: ["pipeline"],
  decisions: ["decisions", "inbox"], catalogue: ["catalogue"], live: ["live", "now", "last_cell"], timeline: ["timeline"],
  gate_trend: ["gate_trend"], coverage: ["coverage"], activity: ["activity"], models: ["models"], health: ["health", "now"],
  updates: ["updates"], autonomy: ["autonomy"], evidence_packs: ["evidence_packs"], try_it: ["try_it"], track: ["track"],
};
export function problemsOf(d, names) {
  const want = new Set(names || []);
  const seen = new Set();
  return (d.problems || []).map(String).filter((p) => want.has(p.split(":")[0].trim()) && !seen.has(p) && seen.add(p));
}
function unreadable(probs) {
  return h("div", { class: "nm-box err", role: "note" }, icon("alert"),
    h("div", null, h("b", null, "Could not be read"), h("p", null, "The records behind this widget could not be read ("
      + probs.join(", ") + "), so it cannot say what they hold. Nothing here means zero.")));
}
function isEmptyState(body) {
  if (!body || !body.classList) return false;
  if (body.matches(".empty, .nm-box, .viz-none") || body.querySelector(":scope > .empty, :scope > .nm-box, .viz-none")) return true;
  const tbody = body.querySelector("tbody");
  return !!tbody && !tbody.querySelector("tr");
}
function withProblems(type, view) {
  return (d, w) => {
    const body = view(d, w);
    const probs = problemsOf(d, PROBLEM_SOURCES[type]);
    if (!probs.length || type === "kpi_strip") return body;   // the key figures mark each figure itself
    if (isEmptyState(body)) return unreadable(probs);
    return h("div", null, h("p", { class: "w-warn", role: "note" }, icon("alert"),
      h("span", null, "Part of this widget's records could not be read (" + probs.join(", ") + "); what is shown may be incomplete.")), body);
  };
}

let kpiSeq = 0;
function kpiTile(d, o) {
  const broken = o.problems && o.problems.length;
  const partial = !broken && o.partial && o.partial.length;   // a figure read in part: shown, and said to be a floor
  const measured = !broken && o.value !== null && o.value !== undefined;
  let info = null;
  let described = null;
  if (o.info) {
    // the basis: a real button (keyboard and pointer), its text also read with the button and in the tile
    const id = "kpi-basis-" + (++kpiSeq);
    info = infoButton(o.label, h("p", null, o.info));
    info.classList.add("kpi-i");
    info.setAttribute("aria-describedby", id);
    attachTip(info, o.info);
    described = h("span", { class: "vh", id }, "Basis: " + o.info);
  }
  return h("div", { class: "kpi" + (measured ? "" : " nm") + (broken || partial ? " err" : ""), role: "group", "aria-label": o.label },
    h("div", { class: "kpi-h" }, icon(o.icon), h("span", null, o.label), info), described,
    measured ? h("div", { class: "kpi-v" }, o.display || num(o.value), o.unit ? h("small", null, o.unit) : null)
      : h("div", { class: "kpi-v nm-text" }, broken ? "— Could not be read" : "— Not measured"),
    measured && o.sub && !partial ? h("p", { class: "kpi-sub" }, o.sub) : null,
    partial ? h("p", { class: "kpi-sub" }, "Part of its records could not be read (" + o.partial.join(", ") + "); there may be more.")
      : broken ? h("p", { class: "kpi-sub" }, "Its records could not be read (" + o.problems.join(", ") + "); it is not zero.")
        : !measured ? h("p", { class: "kpi-sub" }, o.why) : null,
    foot(d, o.provenance, o.denom));
}

function kpis(d) {
  const k = d.kpis || {};
  const fr = k.first_round || {};
  const pr = k.proven || {};
  // The API's first_round.series is the hourly pass rate of every gate round, repairs included, not of
  // first rounds: drawn under this figure it would describe another number, so the tile draws no line.
  const prov = (p) => (technical() ? "" : " (" + PROV_PLAIN[p] + ")");
  const untested = pr.of ? pr.of - pr.num : 0;
  return [
    { label: "Projects in flight", icon: "folder", value: k.in_flight ? k.in_flight.value : null, provenance: "observed",
      denom: k.in_flight ? "of " + plural(k.in_flight.of, "project") : null, info: k.in_flight && basisWord("in_flight", k.in_flight.basis) + prov("observed"),
      problems: problemsOf(d, ["now"]) },
    { label: "Decisions waiting", icon: "inbox", value: k.decisions ? k.decisions.value : null, provenance: "observed",
      sub: k.decisions && k.decisions.oldest_hours !== null && k.decisions.oldest_hours !== undefined
        ? "oldest waits " + fmtAge(k.decisions.oldest_hours) : (k.decisions && k.decisions.value ? null : "nothing waits"),
      denom: "across projects", info: k.decisions && basisWord("decisions", k.decisions.basis) + prov("observed"), problems: problemsOf(d, ["decisions"]),
      partial: problemsOf(d, ["inbox"]) },
    { key: "First-round gate pass", label: pick("Passed the quality check first time", "First-round gate pass"), icon: "gate", value: fr.of ? fr.value : null, display: pct(fr.value),
      provenance: "derived", denom: fr.of ? fr.num + " of " + plural(fr.of, "task") + pick(" checked", " gated") : null,
      why: pick("No task has been checked yet.", "No task has reached a gate yet."), info: fr.basis && basisWord("first_round", fr.basis) + prov("derived") },
    { key: "Criteria proven", label: pick("Agreed checks shown to work", "Criteria proven"), icon: "file-check", value: pr.of ? pr.value : null, display: pct(pr.value), provenance: "derived",
      denom: pr.of ? pr.num + " of " + plural(pr.of, tw("criterion"), tw("criterion", 2)) : null,
      sub: pr.of && !technical() ? (untested ? "The other " + untested + " have not been tested yet." : "Every agreed check is shown to work.") : null,
      why: pick("No work is planned yet, so there is nothing to prove.", "No contract is compiled yet, so there are no criteria."), info: pr.basis && basisWord("proven", pr.basis) + prov("derived"), problems: problemsOf(d, ["coverage"]) },
    { key: "Capabilities in use", label: pick("Live and in use", "Capabilities in use"), icon: "catalogue", value: k.in_use ? k.in_use.value : null, provenance: "observed",
      denom: k.in_use ? "of " + plural(k.in_use.of, "project") : null,   // the same denominator as Projects in flight
      sub: k.in_use && !technical() && (!k.in_use.value || k.in_use.live_to_try) ? (k.in_use.value ? "" : "None has reached production yet.")
        + (k.in_use.live_to_try ? (k.in_use.value ? "" : " ") + plural(k.in_use.live_to_try, "release") + " live to try (explore, demo or pilot), not in production." : "") : null,
      info: k.in_use && basisWord("in_use", k.in_use.basis) + prov("observed"),
      problems: problemsOf(d, ["catalogue"]) },
  ].filter((t) => tileOn(t.key || t.label));   // a figure of a module that is off is not shown (cockpit/static/modules.js)
}

// -- decisions: inline actions go through the same routes as the Inbox ----------------------------

// An ask put to a persona in People in the loop (kernel/hitl.py): it waits on whoever holds that persona.
const waitsOnMe = (it) => (it.kind === "ask" ? mayAct(it.deciders) : decides(it.kind, it.deciders));

export function decideButtons(item, opts) {
  const o = opts || {};
  const kind = item.kind;
  if (kind === "ask") {
    return waitsOnMe(item) ? h("a", { class: "btn small", href: link(item.project, "loop"), "data-control": "hitl_answer" }, "Answer")
      : h("span", { class: "muted small" }, "Waits on " + orList(item.deciders || []));
  }
  if (!decides(kind, item.deciders)) return h("span", { class: "muted small" }, "Waits on " + orList(item.deciders || []));
  const box = h("div", { class: "inline-decide" });
  const verdicts = (item.verdicts || []).filter((v) => !(kind === "question" && v === "assume"));
  if (kind === "question") return h("a", { class: "btn small", href: link(item.project, "questions", (item.refs || {}).question) }, "Answer");
  if (item.kind === "approval" && item.project !== FACTORY_PID && /plan/i.test(item.title || "")) {
    return h("a", { class: "btn small", href: link(item.project, "plan") }, icon("arrow-right"), "Open the plan");
  }
  verdicts.forEach((v, i) => {
    const b = h("button", { type: "button", class: "btn small" + (i === 0 ? " primary" : ""), "data-control": "decide",
      "data-key": item.card + ":" + v }, VERDICT_LABEL[v] || v);
    b.addEventListener("click", () => {
      if (!needPerson()) return;
      act(box, async () => {
        const out = await api("POST", "/api/projects/" + enc(item.project) + "/cards/" + enc(item.card) + "/decide",
          Object.assign({ verdict: v, reason: o.reason ? o.reason() : "" }, signed()));
        say(item.card + ": " + (VERDICT_LABEL[v] || v) + ", signed by " + S.person.trim() + " as " + personaLabel(S.persona) + "."
          + (out.project ? " It is now project " + out.project + "." : ""), "good");
        if (out.project) location.hash = "#/p/" + enc(out.project) + "/overview";
        else if (nav.rerender) await nav.rerender();
      });
    });
    box.append(b);
  });
  return box;
}

function decisionRow(it) {
  const mine = waitsOnMe(it);
  return h("li", { class: "dec-row" + (mine ? " mine" : "") },
    h("span", { class: "dec-ic" }, icon(KIND_ICON[it.kind] || "inbox")),
    h("div", { class: "dec-b" },
      h("a", { class: "dec-t", href: it.project === FACTORY_PID ? (it.kind === "concept" ? "#/square" : link(it.project, "inbox", it.card))
        : it.kind === "ask" ? link(it.project, "loop") : link(it.project, it.kind === "change" ? "changes" : "inbox", it.card) }, cardTitleEl(it.title)),
      h("div", { class: "dec-m" }, h("span", null, KIND_LABEL[it.kind] || it.kind), h("span", null, titleOf(it.project, it.project_title)),
        technical() ? h("span", { class: "mono" }, it.card) : null, h("span", { tip: "how long it has waited" }, icon("clock"), fmtAge(it.age_hours)),
        it.blocking ? chip("warning", "alert", it.kind === "ask" ? pick("Holds delivery", "Required") : pick("Holds work up", "Blocking")) : null)),
    h("div", { class: "dec-a" }, decideButtons(it)));
}

// Hourly buckets with the empty hours put back, so a time axis is never compressed.
function hourly(series, blank) {
  if (series.length < 2) return series;
  const out = [];
  const byKey = {};
  series.forEach((x) => { byKey[String(x.at).slice(0, 13)] = x; });
  const t0 = Date.parse(String(series[0].at).slice(0, 13) + ":00:00Z");
  const t1 = Date.parse(String(series[series.length - 1].at).slice(0, 13) + ":00:00Z");
  if (Number.isNaN(t0) || Number.isNaN(t1) || (t1 - t0) / 3600000 > 72) return series;
  for (let t = t0; t <= t1; t += 3600000) {
    const at = new Date(t).toISOString().replace(".000Z", "Z");
    out.push(byKey[at.slice(0, 13)] || blank(at));
  }
  return out;
}

// -- the widget definitions -----------------------------------------------------------------------

const DEF = {};
// How many rows a list shows: its size's cap, none in the side panel Expand opens, which shows it in full (FR-CMP2).
const upTo = (w, n) => (w.full ? undefined : n);

DEF.kpi_strip = {
  views: ["chart", "table"],
  render: (d) => h("div", { class: "kpi-strip" }, kpis(d).map((t) => kpiTile(d, t))),
  table: (d) => dataTable([{ label: "Figure", key: "label" }, { label: "Value", value: (r) => ((r.problems || []).length
    ? h("span", { class: "nm-text" }, "could not be read (" + r.problems.join(", ") + ")")
    : r.value === null || r.value === undefined ? null
      : (r.partial || []).length ? (r.display || num(r.value)) + " or more (part not read: " + r.partial.join(", ") + ")"
        : (r.display || num(r.value))) },
    { label: "Denominator", value: (r) => r.denom || "-" }, { label: "Provenance", key: "provenance" }], kpis(d), "Key figures"),
};

function squareCorners(sq) {
  if (!sq) return [];
  const bands = (sq.pipeline && sq.pipeline.bands) || [];
  const band = (name) => (bands.find((b) => b.band === name) || {}).count || 0;
  const tech = technical();
  return [
    { id: "needs", icon: "signal", label: squareWord("needs"), value: sq.signals.new, of: sq.signals.total, unit: pick("new", "new signals"),
      sub: pick("Go to Ideas to approve them", "chats, feeds, monitoring, meetings, the website chat"), href: "#/square" },
    { id: "concept", icon: "lightbulb", label: squareWord("concept"), value: sq.concepts_waiting.length, unit: pick("waiting", "concepts waiting"),
      sub: pick("A business owner or product owner approves each", "a business owner or product owner validates"), href: "#/square" },
    { id: "factory", icon: "factory", label: squareWord("factory"), value: (sq.pipeline || {}).total || 0, unit: "projects",
      bands: tech ? bands.map((b) => ({ label: b.band, count: b.count })) : null,
      sub: tech ? null : band("Decide") + band("Shape") + " being shaped, " + band("Deliver") + " being built, " + band("Run") + " live",
      href: "#/projects" },
    { id: "testing", icon: "users", label: squareWord("testing"), value: sq.end_user_feedback_waiting, unit: pick("pieces of feedback waiting", "feedback waiting"),
      sub: pick("Feedback becomes a change request", "feedback flows back as changes"), href: "#/square" },
    { id: "production", icon: "server", label: squareWord("production"), value: sq.in_production, unit: pick("live", "in production"),
      sub: tech ? "DevOps, maintenance, security, compliance"
        : sq.in_production ? "Live services are watched; problems come back as new requests"
          : "Nothing is live yet. Live services are watched, and problems come back as new requests", href: "#/square" },
  ];
}

export function squareDiagram(sq, opts) {
  const o = opts || {};
  const c = squareCorners(sq);
  if (!c.length) return empty("square", "The delivery square could not be read.");
  const [needs, concept, factory, testing, production] = c;
  const ppl = (id) => {
    const list = (o.people || {})[id] || [];
    return list.length ? h("span", { class: "sq-people" }, list.slice(0, 4).map((p) => h("span", { tip: p.name + " · " + personaLabel(p.persona) }, avatar(p.name)))) : null;
  };
  const corner = (x, next) => h("a", { class: "sq-corner sq-" + x.id, href: x.href },
    h("span", { class: "sq-top" }, h("span", { class: "sq-ic" }, icon(x.icon)), h("span", { class: "sq-label" }, x.label), o.people ? ppl(x.id) : null),
    h("span", { class: "sq-v" }, String(x.value), h("small", null, x.unit + (x.of !== undefined ? pick(", " + x.of + " in total", " of " + x.of) : ""))),
    x.sub ? h("span", { class: "sq-sub" }, x.sub) : null,
    next ? h("span", { class: "sq-next" }, icon("arrow-right"), next) : null);
  const arrow = (cls, label) => h("span", { class: "sq-flow " + cls, "aria-hidden": "true" }, icon("arrow-right"), label ? h("span", null, label) : null);
  if (o.compact) {
    // a step flow: the same five places, one after the other, and the way back
    return h("ol", { class: "sq-steps" }, [needs, concept, factory, testing, production].map((x, i) => h("li", null,
      h("a", { class: "sq-step", href: x.href }, h("span", { class: "sq-ic" }, icon(x.icon)), h("span", { class: "sq-label" }, x.label),
        h("span", { class: "sq-v" }, String(x.value), h("small", null, x.unit))),
      i === 4 ? h("span", { class: "sq-back" }, icon("refresh"), pick("Problems and feedback come back as new requests", "Monitoring and feedback bring new needs")) : null)));
  }
  // the arrows show the direction; a business reader is not given arrow words that repeat the corners
  const tech = technical();
  return h("div", { class: "sq-map" },
    corner(needs, tech ? "to concept validation" : null), arrow("f-top", tech ? "validate" : null), corner(concept, tech ? "to the factory" : null),
    arrow("f-left", tech ? "monitor" : null),
    h("a", { class: "sq-factory", href: factory.href }, h("span", { class: "sq-top" }, h("span", { class: "sq-ic" }, icon(factory.icon)),
      h("span", { class: "sq-label" }, factory.label), o.people ? ppl("factory") : null, h("span", { class: "sq-v inline" }, String(factory.value), h("small", null, factory.unit))),
    factory.bands ? h("span", { class: "sq-bands" }, factory.bands.map((b) => h("span", { class: "sq-band" }, h("b", null, String(b.count)), b.label)))
      : h("span", { class: "sq-sub" }, factory.sub)),
    arrow("f-right", tech ? "build" : null),
    corner(production, tech ? "monitoring feeds new needs" : null), arrow("f-bottom", tech ? "release" : null), corner(testing, tech ? "feedback flows back" : null));
}

DEF.square = {
  views: ["chart", "table"],
  render: (d, w) => squareDiagram(d.square, { compact: w.size === "S" || w.size === "M" }),
  table: (d) => dataTable([{ label: "Corner", key: "label" }, { label: "Now", value: (r) => r.value + " " + r.unit }],
    squareCorners(d.square), "The delivery square"),
};

function pipelineStages(d) {
  const out = [];
  ((d.pipeline || {}).bands || []).forEach((b) => b.stages.forEach((s) => out.push({ band: b.band, ...s })));
  return out;
}
DEF.pipeline = {
  views: ["chart", "table"],
  render: (d) => {
    const stages = pipelineStages(d);
    if (!(d.pipeline || {}).total) return empty("pipeline", "No project yet.", button("New project", { icon: "plus", kind: "small", onclick: () => nav.newProject && nav.newProject() }));
    // the box is a size container: the stages go from seven columns to four, then to rows, by its width
    return h("div", { class: "pipe-box" }, h("div", { class: "pipe" }, stages.map((s) => h("div", { class: "pipe-col" + (s.projects.length ? "" : " empty") },
      h("div", { class: "pipe-h" }, h("span", { class: "pipe-n" }, String(s.stage)), h("span", { class: "pipe-name" }, stageWord(s.stage, s.name)),
        h("span", { class: "pipe-c" }, String(s.projects.length))),
      h("div", { class: "pipe-band" }, s.band),
      s.projects.map((p) => h("a", { class: "pchip", href: "#/p/" + enc(p.id), tip: p.title + " · " + (p.maturity || "") },
        icon(profileOf(p.profile).icon || "globe"), h("span", { class: "pchip-b" }, h("span", { class: "pchip-t" }, p.title),
          h("span", { class: "pchip-m" }, (p.maturity || "") + (p.paused ? " · paused" : "")))))))));
  },
  table: (d) => dataTable([{ label: tw("stage", 1, { cap: true }), value: (r) => r.stage + " " + stageWord(r.stage, r.name) }, { label: "Band", key: "band" },
    { label: "Projects", value: (r) => r.projects.map((p) => p.title).join(", ") || "-" }], pipelineStages(d), "Projects per stage"),
};

DEF.decisions = {
  views: ["list", "chart", "table"],
  render: (d, w) => {
    // as the Inbox orders them: yours first, then what holds work up, the panel's open questions last, oldest first
    const holds = (x) => (x.blocking || x.kind !== "question" ? 1 : 0);
    const items = (d.decisions || []).slice().sort((a, b) => (waitsOnMe(b) - waitsOnMe(a)) || (holds(b) - holds(a))
      || ((b.age_hours || 0) - (a.age_hours || 0)));
    if (!items.length) return empty("check-circle", "Nothing waits on a person right now.");
    if (w.view === "chart") {
      const by = {};
      items.forEach((i) => { by[i.kind] = (by[i.kind] || 0) + 1; });
      return bars({ rows: Object.entries(by).sort((a, b) => b[1] - a[1]).map(([k, n]) => ({ label: KIND_LABEL[k] || k, icon: KIND_ICON[k], value: n })), unit: "cards waiting" });
    }
    const mine = items.filter(waitsOnMe).length;
    return h("div", null, h("p", { class: "w-sum" }, h("b", null, String(mine)), " yours to decide as " + personaLabel(S.persona),
      h("span", { class: "muted" }, " · " + items.length + " waiting in all")),
    h("ul", { class: "dec-list" }, items.slice(0, upTo(w, w.size === "S" ? 4 : 8)).map(decisionRow)),
    items.length > 8 ? h("a", { class: "more-link", href: "#/inbox" }, "All " + items.length + " in the Inbox", icon("arrow-right")) : null);
  },
  table: (d) => dataTable([{ label: "Card", value: (r) => r.card + " " + r.title }, { label: "Kind", value: (r) => KIND_LABEL[r.kind] || r.kind },
    { label: "Project", key: "project_title" }, { label: "Waiting", value: (r) => fmtAge(r.age_hours) },
    { label: "Who decides", value: (r) => (S.personas.length && S.personas.every((p) => (r.deciders || []).includes(p.id))
      ? "Any persona" : (r.deciders || []).map(personaLabel).join(", ")) }], d.decisions || [], "Decisions waiting"),
};

export function catalogueCard(it) {
  const st = catalogueState(it);
  const p = profileOf(it.profile);
  const href = it.project ? "#/p/" + enc(it.project) : "#/square";
  return h("a", { class: "cat-card", href },
    h("div", { class: "cat-top" }, h("span", { class: "cat-ic" }, icon(p.icon || "globe")), chip(st.tone, st.icon, st.word)),
    h("b", { class: "cat-t" }, it.title),
    h("p", { class: "cat-s" }, it.summary || ""),
    h("div", { class: "cat-meta" }, h("span", null, p.label), it.deliverable ? h("span", null, deliverableWord(it.deliverable)) : null,
      it.maturity ? h("span", null, it.maturity) : null),
    h("div", { class: "cat-pack", tip: technical() ? null : "A release package lists everything the release is made of, with a fingerprint of each, so anyone can check it is unchanged." },
      icon("package"), it.pack ? (technical() ? [h("span", { class: "mono" }, "v" + it.pack.version),
        it.pack.valid ? chip("good", "check-circle", "Valid") : chip("warning", "alert", "Not valid")]
        : h("span", null, "Release " + String(it.pack.version || "").replace(/\.0$/, "") + (it.pack.valid ? " ready to hand over" : ": not complete yet")))
        : h("span", { class: "muted" }, it.project ? pick("Not released yet", "No pack yet: no release") : pick("An idea: not built", "A concept: not built"))));
}
// What a capability is: an adopted system is kept and maintained, not built.
export function catalogueState(it) {
  if (it.adopted && it.state === "building") return { tone: "good", icon: "check-circle", word: pick("Adopted: kept running", "Adopted · maintained") };
  return CATALOGUE_STATE[it.state] || { tone: "neutral", icon: "dashed", word: it.state };
}
// A deliverable's name in the reader's words ("ops_agent" is a report agent to a business owner).
function deliverableWord(dv) {
  const plain = { ops_agent: "report agent", capability_pack: "reusable AI service", product: "product" };
  return technical() ? String(dv).replace("_", " ") : plain[dv] || String(dv).replace(/_/g, " ");
}
export function catalogueRow(it) {
  const st = catalogueState(it);
  const p = profileOf(it.profile);
  return h("li", { class: "cat-row" }, h("span", { class: "cat-ic", tip: p.label }, icon(p.icon || "globe")),
    h("div", { class: "cat-rb" }, h("a", { href: it.project ? "#/p/" + enc(it.project) : "#/square" }, it.title),
      h("small", null, p.label.split(/[:(]/)[0].trim() + " · " + deliverableWord(it.deliverable || "product")
        + (it.pack ? (technical() ? " · pack v" + it.pack.version + (it.pack.valid ? ", valid" : ", not valid")
          : " · release " + String(it.pack.version || "").replace(/\.0$/, "") + (it.pack.valid ? " ready to hand over" : ", not complete")) : ""))),
    chip(st.tone, st.icon, st.word));
}
DEF.catalogue = {
  views: ["list", "chart", "table"],
  render: (d, w) => {
    const items = (d.catalogue || {}).items || [];
    if (!items.length) return empty("catalogue", "No capability yet. A validated concept or a new project starts one.");
    if (w.view === "chart") {
      return bars({ rows: Object.keys(CATALOGUE_STATE).map((k) => ({ label: CATALOGUE_STATE[k].word, icon: CATALOGUE_STATE[k].icon,
        value: ((d.catalogue || {}).counts || {})[k] || 0 })), unit: "capabilities" });
    }
    if (w.size === "S" || w.size === "M") {
      return h("div", null, h("ul", { class: "cat-rows" }, items.slice(0, 7).map(catalogueRow)),
        items.length > 7 ? h("a", { class: "more-link", href: "#/catalogue" }, "All " + items.length + " in the catalogue", icon("arrow-right")) : null);
    }
    return h("div", { class: "cat-grid wide" }, items.slice(0, upTo(w, 8)).map(catalogueCard));
  },
  table: (d) => dataTable([{ label: "Capability", key: "title" }, { label: "State", value: (r) => (CATALOGUE_STATE[r.state] || {}).word || r.state },
    { label: "Profile", value: (r) => profileOf(r.profile).label }, { label: "Deliverable", value: (r) => (r.deliverable || "-").replace("_", " ") },
    { label: "Pack", value: (r) => (r.pack ? "v" + r.pack.version + (r.pack.valid ? ", valid" : ", not valid") : "none") }],
  (d.catalogue || {}).items || [], "Capabilities"),
};

// What a project's agents are doing. "Working", with the pulsing dot, only while kernel.status.live
// reports a running cell; otherwise the project's own state, with its icon and label.
export function liveState(r) {
  const lv = r.live || {};
  if (lv.running && !lv.ended) return { tone: "info", icon: "pulse", word: "Working", running: true };
  const n = r.now || {};
  const last = r.last_cell || {};
  if (n.state === "paused") return { tone: "neutral", icon: "pause", word: "Paused" };
  if (n.state === "waiting_on_you") return { tone: "warning", icon: "user", word: "Waiting on a person" };
  if (n.state === "done") return { tone: "good", icon: "check-circle", word: "Done" };
  if (n.state === "failed") return { tone: "critical", icon: "x-circle", word: "Failed" };
  if (last.bucket === "apparatus_failure" && /^Building /.test(n.line || "")) {
    return { tone: "serious", icon: "alert", word: "Apparatus failure",
      line: last.task + " round " + last.round + ": the harness failed, not the work. The next Advance retries it." };
  }
  return { tone: "neutral", icon: "play", word: "Ready", line: /^Building /.test(n.line || "")
    ? (n.line || "") + " · no cell is running; the next Advance continues" : null };
}
DEF.live = {
  views: ["list", "table"],
  render: (d) => {
    const rows = d.projects || [];
    if (!rows.length) return empty("pulse", "No project yet, so no agent is at work.");
    const order = (r) => { const st = liveState(r); return st.running ? 0 : st.word === "Waiting on a person" ? 1 : st.word === "Apparatus failure" ? 2 : 3; };
    const running = rows.filter((r) => liveState(r).running).length;
    return h("div", null, h("p", { class: "w-sum" }, h("b", null, String(running)),
      running === 1 ? pick(" AI build team working now", " builder cell running now") : pick(" AI build teams working now", " builder cells running now"),
      h("span", { class: "muted" }, " · " + plural(rows.length, "project"))),
    h("ul", { class: "live-list" }, rows.slice().sort((a, b) => order(a) - order(b)).map((r) => {
      const lv = r.live || {};
      const st = liveState(r);
      return h("li", { class: "live-row" + (st.running ? " on" : "") },
        h("span", { class: "live-dot" + (st.running ? " pulse" : ""), "aria-hidden": "true" }),
        h("div", { class: "live-b" }, h("a", { href: "#/p/" + enc(r.project) + (st.running ? "/tasks" : "") }, r.title),
          h("div", { class: "live-m" }, st.running
            ? [h("span", { class: "mono" }, lv.task), h("span", null, (lv.role || "cell").replace(/_/g, " ")), lv.model ? h("span", { class: "mono" }, lv.model) : null,
              h("span", null, plural(lv.steps || 0, "tool step")), lv.last ? h("span", { class: "mono" }, lv.last.tool + " " + (lv.last.target || "").slice(0, 40)) : null]
            : h("span", null, st.line || nowSaid((r.now || {}).line) || "idle"))),
        chip(st.tone, st.icon, st.word));
    })));
  },
  table: (d) => dataTable([{ label: "Project", key: "title" }, { label: "State", value: (r) => liveState(r).word },
    { label: "Task", value: (r) => (r.live && r.live.running ? r.live.task : "-") }, { label: "Model", value: (r) => (r.live && r.live.model) || "-" },
    { label: "Last step", value: (r) => (r.live && r.live.last ? r.live.last.tool + " " + (r.live.last.target || "") : "-") }], d.projects || [], "Live agents"),
};

function timelineFor(d, w) {
  const tls = d.timelines || {};
  const ids = Object.keys(tls);
  const pick = (w.filter && w.filter.project && tls[w.filter.project]) ? w.filter.project
    : ids.sort((a, b) => String(tls[b].end || "").localeCompare(String(tls[a].end || "")))[0];
  return { pid: pick, tl: pick ? tls[pick] : null, ids };
}
DEF.timeline = {
  views: ["chart", "table"],
  render: (d, w) => {
    const { pid, tl, ids } = timelineFor(d, w);
    if (!tl) return empty("timeline", "No task has run yet: timelines start when the build does.");
    const sel = ids.length > 1 ? h("select", { class: "w-select", "aria-label": "Project", "data-fk": "filter" }, ids.map((id) =>
      h("option", { value: id, selected: id === pid }, d.timelines[id].title || id))) : null;
    if (sel) sel.addEventListener("change", () => { if (nav.setWidgetFilter) nav.setWidgetFilter(w.id, { project: sel.value }); });
    return h("div", null, h("div", { class: "w-row" }, h("span", { class: "w-sum" }, h("b", null, tl.title || pid), " · " + plural(tl.tasks.length, "task")), sel),
      waterfall({ tasks: tl.tasks, href: (t) => link(pid, "tasks", t.task) }));
  },
  table: (d, w) => {
    const { tl } = timelineFor(d, w);
    const rows = [];
    ((tl || {}).tasks || []).forEach((t) => t.rounds.forEach((r) => rows.push({ task: t.task, title: t.title, ...r })));
    return dataTable([{ label: "Task", value: (r) => r.task + " " + (r.title || "") }, { label: tw("round", 1, { cap: true }), key: "round", num: true },
      { label: "Start", value: (r) => fmtAt(r.start) || null }, { label: "End", value: (r) => fmtAt(r.end) || null },
      { label: pick("Result", "Verdict"), value: (r) => r.verdict || pick("being checked", "in its gate") }, { label: "Model", value: (r) => r.model || "-" }], rows, "Task rounds");
  },
};

const GATE_SERIES = [{ key: "passed", label: "Passed", color: STATUS_MARK.good, icon: "check-circle" },
  { key: "not_passed", label: "Not passed", color: STATUS_MARK.critical, icon: "x-circle" }];
DEF.gate_trend = {
  views: ["chart", "table"],
  render: (d, w) => {
    const g = d.gate_trend || {};
    if (!g.rounds) return notMeasured(pick("Nothing has been checked yet: the trend starts with the first build.", "No gate has judged a round yet: the trend starts with the first build."));
    const series = hourly(g.series || [], (at) => ({ at, passed: 0, not_passed: 0 })).slice(-24);
    return h("div", null, h("div", { class: "w-headline" }, h("span", { class: "big" }, pct(g.pass_rate)),
      h("span", null, "of " + plural(g.rounds, tw("round"), tw("round", 2)) + pick(" passed the quality check", " passed the gate"), technical() ? h("small", { class: "prov derived" }, "derived") : null)),
    columns({ series: GATE_SERIES, height: w.size === "XL" ? 240 : 150, rows: series.map((s) => ({
      label: String(s.at).slice(5, 16).replace("T", " "), short: String(s.at).slice(11, 16),
      tipTitle: String(s.at).replace("T", " ").replace("Z", " UTC") + " (hour)", values: s })) }));
  },
  table: (d) => dataTable([{ label: "Hour (UTC)", value: (r) => String(r.at).replace("T", " ").slice(0, 16) },
    { label: "Passed", key: "passed", num: true }, { label: "Not passed", key: "not_passed", num: true },
    { label: "Rate", value: (r) => pct(r.passed / ((r.passed + r.not_passed) || 1)), num: true }], (d.gate_trend || {}).series || [], "Gate verdicts per hour"),
};

const COVER_SERIES = [{ key: "proven", label: "Proven (verified or held out)", color: STATUS_MARK.good, icon: "check-circle" },
  { key: "claimed", label: "Claimed", color: STATUS_MARK.warning, icon: "dashed" },
  { key: "failing", label: "Failing", color: STATUS_MARK.critical, icon: "x-circle" },
  { key: "not_measured", label: "Not measured", hatch: true, icon: "dashed" }];
DEF.coverage = {
  views: ["chart", "table"],
  render: (d) => {
    const c = d.coverage || {};
    if (!(c.projects || []).length) return notMeasured(pick("No work is planned yet, so there is nothing to prove.", "No contract is compiled yet, so no criterion has evidence."));
    const total = Object.values(c.total || {}).reduce((a, b) => a + b, 0);
    return h("div", null, h("div", { class: "w-headline" }, h("span", { class: "big" }, pct(c.proven_share)),
      h("span", null, "of " + plural(total, tw("criterion"), tw("criterion", 2)) + pick(" shown to work", " proven rather than claimed"), technical() ? h("small", { class: "prov derived" }, "derived") : null)),
    stack100({ series: COVER_SERIES, rows: c.projects.map((p) => ({ label: p.title, href: "#/p/" + enc(p.project) + "/spec",
      values: { proven: p.verified + p.held_out, claimed: p.claimed, failing: p.failing, not_measured: p.not_measured } })),
    summary: (r, t) => (r.values.proven) + " of " + t + " proven" }));
  },
  table: (d) => dataTable([{ label: "Project", key: "title" }, { label: "Verified", key: "verified", num: true }, { label: "Held out", key: "held_out", num: true },
    { label: "Claimed", key: "claimed", num: true }, { label: "Failing", key: "failing", num: true }, { label: "Not measured", key: "not_measured", num: true }],
  (d.coverage || {}).projects || [], "Evidence per project"),
};

function projectTitle(pid) {
  const p = ((S.dashboard || {}).projects || []).find((x) => x.project === pid) || (S.projects || []).find((x) => x.id === pid);
  return p ? p.title : pid;
}
function activityItem(e) {
  const a = e.actor || {};
  const person = a.type === "person";
  return h("li", { class: "act-row" }, avatar(a.name, person ? null : (a.name === "kernel" ? "kernel" : "agent")),
    h("div", { class: "act-b" }, h("p", null, h("b", null, person ? (a.name || "someone") : a.name === "kernel" ? cap1(kernelWord()) : a.name),
      technical() ? ": " : " ", datum(activityLine(e.summary))),
      h("div", { class: "act-m" }, h("a", { href: "#/p/" + enc(e.project) }, projectTitle(e.project)), person && a.persona ? h("span", null, personaLabel(a.persona) + (a.outside ? ", from outside" : "")) : null,
        !person && a.model ? h("span", { class: "mono" }, a.model) : null, h("span", { tip: fmtAt(e.at) }, ago(e.at)))));
}
DEF.activity = {
  views: ["list", "chart", "table"],
  render: (d, w) => {
    const ev = d.activity || [];
    if (!ev.length) return empty("activity", "Nothing has happened yet.");
    if (w.view === "chart") {
      const by = {};
      ev.forEach((e) => { const k = String(e.at || "").slice(0, 13); if (!k) return; by[k] = by[k] || { person: 0, agent: 0 }; by[k][e.actor && e.actor.type === "person" ? "person" : "agent"] += 1; });
      return columns({ series: [{ key: "person", label: "People", color: SERIES(1), icon: "user" }, { key: "agent", label: "Agents", color: SERIES(2), icon: "bot" }],
        rows: hourly(Object.keys(by).sort().map((k) => ({ at: k + ":00:00Z", ...by[k] })), (at) => ({ at, person: 0, agent: 0 }))
          .slice(-24).map((r) => ({ label: String(r.at).slice(0, 13).replace("T", " ") + ":00", short: String(r.at).slice(11, 13) + ":00", values: r })), height: 140 });
    }
    return h("ul", { class: "act-list" }, ev.slice(0, upTo(w, w.size === "S" ? 5 : 9)).map(activityItem));
  },
  table: (d) => dataTable([{ label: "When", value: (r) => fmtAt(r.at) }, { label: "Who", value: (r) => (r.actor || {}).name || "-" },
    { label: "Kind", value: (r) => ((r.actor || {}).type === "person" ? "person" : "agent") }, { label: "What", key: "summary" }, { label: "Project", key: "project" }],
  d.activity || [], "Recent activity"),
};

DEF.models = {
  views: ["chart", "table"],
  render: (d) => {
    const m = Object.entries(d.models || {});
    if (!m.length) return notMeasured("No builder cell has run yet, so no model has a record.");
    return h("div", null, bars({ max: 1, unit: pick("passed the quality check first time", "first-round gate pass"), rows: m.map(([name, r]) => ({ label: name,
      sub: plural(r.cells, pick("attempt", "cell round")) + " · " + r.escalated + pick(" sent to a person", " escalated to a person"),
      value: r.first_round_warranted_rate, display: pct(r.first_round_warranted_rate), why: "no first round was gated for this model" })) }),
    h("p", { class: "viz-note" }, pick("Share of tasks each AI builder got through the quality check at the first try.",
      "First-round gate pass rate per builder model (the gate's verdict 'warranted'); n is the cell rounds each ran.")));
  },
  table: (d) => dataTable([{ label: "Model", value: (r) => r[0] }, { label: "Cells", value: (r) => r[1].cells, num: true },
    { label: "First-round gate pass", value: (r) => pct(r[1].first_round_warranted_rate), num: true }, { label: "Escalated to a person", value: (r) => r[1].escalated, num: true },
    { label: "Mean rounds to pass", value: (r) => (r[1].mean_rounds_to_pass === null ? null : Math.round(r[1].mean_rounds_to_pass * 100) / 100), num: true }],
  Object.entries(d.models || {}), "Builder models"),
};

// A project whose health could not be read is counted and listed as "not read" in every view (hatched in
// the chart), beside the projects that were read, under the widget's warning; never left out, never zero.
const unreadText = (d, names) => (problemsOf(d, names).length ? "could not be read" : "not read");
DEF.health = {
  views: ["list", "chart", "table"],
  render: (d, w) => {
    const rows = d.projects || [];
    if (!rows.length) return empty("heart", "No project yet.");
    if (w.view === "chart") {
      const by = { on_track: 0, at_risk: 0, off_track: 0, unread: 0 };
      rows.forEach((r) => { const st = (r.health || {}).status; by[st !== "unread" && by[st] !== undefined ? st : "unread"] += 1; });
      return segbar({ parts: [{ label: "On track", value: by.on_track, color: STATUS_MARK.good, icon: "check-circle" },
        { label: "At risk", value: by.at_risk, color: STATUS_MARK.warning, icon: "alert", ink: "ink-dark" },
        { label: "Off track", value: by.off_track, color: STATUS_MARK.critical, icon: "stop" },
        { label: "Health not read", value: by.unread, hatch: true, icon: "dashed", ink: "ink-text" }] });
    }
    // one verdict per project on the page: the track's answer (Staying on track says the same), else the health's
    const tracks = {};
    ((d.track || {}).projects || []).forEach((t) => { tracks[t.project] = t; });
    return h("ul", { class: "health-list" }, rows.map((r) => {
      const f = (r.health || {}).forecast || {};
      const known = (x) => x !== null && x !== undefined;
      const said = r.health ? etaSaid(f, waitingCount((r.now || {}).line)) : "";
      return h("li", { class: "health-row" }, tracks[r.project] ? trackState(tracks[r.project]) : healthChip(r.health),
        h("div", { class: "hr-b" }, h("a", { href: "#/p/" + enc(r.project) }, r.title), h("p", { class: "muted small", "data-ud": "" }, nowSaid((r.now || {}).line))),
        !r.health ? h("span", { class: "hr-f" }, h("span", { class: "nm-text" }, "Forecast not read"))
          : h("span", { class: "hr-f", tip: f.basis || "" }, said || h("span", { class: "nm-text" }, pick("Time left not known yet", "ETA not measured")),
            known(f.tasks_left) && f.tasks_left ? h("small", null, plural(f.tasks_left, "task") + " left to build") : null));
    }));
  },
  table: (d) => {
    const unread = (r, fn) => (r.health ? fn(r.health) : h("span", { class: "nm-text" }, unreadText(d, ["health"])));
    return dataTable([{ label: "Project", key: "title" },
      { label: "Health", value: (r) => unread(r, (x) => (HEALTH[x.status] || {}).word || x.status) },
      { label: "Tasks left", value: (r) => unread(r, (x) => (x.forecast || {}).tasks_left), num: true },
      { label: "ETA", value: (r) => unread(r, (x) => fmtMinutes((x.forecast || {}).eta_minutes)) },
      { label: "Now", value: (r) => (r.now || {}).line || h("span", { class: "nm-text" }, unreadText(d, ["now"])) }],
    d.projects || [], "Project health");
  },
};

// Who may decide an update card: the card's own deciders (as the decisions read model carries them), else
// every persona that decides updates. The observation's `who` only suggests who should look at it.
function updateDeciders(d, u) {
  const card = (d.decisions || []).find((x) => x.card === u.card && x.project === u.project);
  if (card && (card.deciders || []).length) return card.deciders;
  return (S.personas || []).filter((p) => (p.decides || []).includes("update")).map((p) => p.id);
}

function updateView(u) {
  const lens = S.lens || "business";
  const v = u.views || {};
  if (lens === "delivery" || lens === "insight") return h("pre", { class: "json" }, JSON.stringify(v.developer || {}, null, 2));
  if (lens === "business") return h("p", { class: "upd-q" }, v.business || u.title);
  return h("p", null, v.expert || u.title);
}
DEF.updates = {
  views: ["list", "table"],
  render: (d, w) => {
    const ups = d.updates || [];
    if (!ups.length) return empty("bell", "No update from outside yet: a new model, a CVE or drifting evals appear here.");
    return h("ul", { class: "upd-list" }, ups.slice(0, upTo(w, w.size === "S" ? 2 : 5)).map((u) => h("li", { class: "upd" + (u.state === "open" ? " open" : "") },
      h("div", { class: "upd-h" }, icon("bell"), h("b", null, u.label || u.trigger), u.project_title ? h("span", { class: "muted" }, u.project_title) : null,
        u.state === "open" ? chip("warning", "clock", "Open") : u.decision ? chip("good", "check", VERDICT_LABEL[u.decision.verdict] || u.decision.verdict)
          : chip("neutral", "info", "For information")),
      updateView(u),
      u.state === "open" && u.card ? decideButtons({ kind: "update", card: u.card, project: u.project, verdicts: u.verdicts,
        deciders: updateDeciders(d, u) }) : null)));
  },
  table: (d) => dataTable([{ label: "Update", value: (r) => r.label || r.trigger }, { label: "Project", value: (r) => r.project_title || r.project || "the factory" },
    { label: "State", key: "state" }, { label: "Decision", value: (r) => (r.decision ? (VERDICT_LABEL[r.decision.verdict] || r.decision.verdict) + " by " + r.decision.person : "-") }],
  d.updates || [], "Updates"),
};

export function autonomyBlock(a, opts) {
  const o = opts || {};
  if (!a) return notMeasured("The autonomy policy could not be read.");
  const levels = (a.factory || {}).levels || [];
  const cap = (a.factory || {}).cap;
  const may = mayAct(a.setters || []);
  const ladder = h("ol", { class: "ladder" }, levels.map((l) => h("li", { class: "rung" + (l.allowed ? " on" : "") + (l.level === cap ? " cap" : "") },
    h("span", { class: "rung-n" }, String(l.level)), h("div", null, h("b", null, l.name), h("p", null, l.meaning)),
    l.level === cap ? chip("accent", "gauge", "Cap") : null)));
  const projects = (a.projects || []).filter((p) => p.own !== null && p.own !== undefined);
  const out = [h("p", { class: "w-sum" }, "The factory may act up to level ", h("b", null, String(cap) + " (" + (a.factory || {}).name + ")"), "."), ladder];
  if (projects.length) out.push(h("p", { class: "muted small" }, "Lower caps: ", projects.map((p) => p.title + " " + p.cap).join(", ")));
  if (may && !o.readOnly) {
    const sel = h("select", { "aria-label": "New cap" }, levels.map((l) => h("option", { value: String(l.level), selected: l.level === cap }, l.level + " " + l.name)));
    const reason = h("input", { "aria-label": "Reason", placeholder: "Why (required, recorded)", maxlength: "2000" });
    const form = h("form", { class: "cap-form", novalidate: true, "data-control": "autonomy" }, sel, reason, h("button", { type: "submit", class: "btn small primary" }, "Set the cap"));
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      if (!reason.value.trim()) { say("A cap change needs a reason: it is recorded with your name.", "warning"); reason.focus(); return; }
      if (!needPerson()) return;
      act(form, async () => {
        await api("PUT", "/api/autonomy", Object.assign({ level: Number(sel.value), reason: reason.value.trim() }, signed()));
        say("The factory's autonomy cap is " + sel.value + ", signed by " + S.person.trim() + ".", "good");
        if (nav.rerender) await nav.rerender();
      });
    });
    out.push(form);
  } else if (!o.readOnly) {
    out.push(h("p", { class: "muted small" }, "A " + (a.setters || []).map(personaLabel).join(", ") + " persona sets the cap, with a reason."));
  }
  return h("div", { class: "autonomy" }, out);
}
DEF.autonomy = {
  views: ["chart", "table"],
  render: (d) => autonomyBlock(d.autonomy),
  table: (d) => dataTable([{ label: "Scope", key: "title" }, { label: "Cap", key: "cap", num: true }, { label: "Level", key: "name" }],
    [{ title: "The factory", cap: ((d.autonomy || {}).factory || {}).cap, name: ((d.autonomy || {}).factory || {}).name }].concat((d.autonomy || {}).projects || []), "Autonomy caps"),
};

export const ATTEST = {
  "attestable": { tone: "good", icon: "check-circle", word: "Attestable" },
  "chain broken": { tone: "critical", icon: "x-circle", word: "Chain broken" },
  "insufficient evidence": { tone: "warning", icon: "alert", word: "Insufficient evidence" },
};
export function exportButton(pid, label) {
  const b = button(label || "Export", { icon: "download", kind: "small", "data-control": "export_evidence" });
  b.addEventListener("click", () => {
    if (!needPerson()) return;
    act(b.parentNode, async () => {
      const out = await api("POST", "/api/projects/" + enc(pid) + "/evidence", signed());
      const name = await download(out.download, out.file);
      say("Evidence pack " + name + " exported and downloaded, signed by " + S.person.trim() + ". The link worked once.", "good");
    });
  });
  if (!mayAct((S.meta && S.meta.evidence_exporters) || [])) {
    b.disabled = true;
    attachTip(b, "A " + ((S.meta && S.meta.evidence_exporters) || []).map(personaLabel).join(", ") + " persona exports evidence");
  }
  return b;
}
DEF.evidence_packs = {
  views: ["list", "table"],
  render: (d) => {
    const packs = d.evidence_packs || [];
    if (!packs.length) return empty("file-check", "No project yet, so no evidence to export.");
    return h("ul", { class: "ev-list" }, packs.map((x) => {
      const st = ATTEST[x.verdict] || { tone: "nm", icon: "dashed", word: x.verdict };
      return h("li", { class: "ev-row" },
        h("div", { class: "ev-b" }, h("a", { href: "#/p/" + enc(x.project) + "/evidence" }, x.title),
          h("div", { class: "ev-m" }, chip(st.tone, st.icon, st.word, { tip: x.meaning }),
            x.pack ? h("span", null, icon("package"), technical() ? [x.pack.version ? "pack v" + x.pack.version : "pack not built", x.pack.valid ? " · valid" : " · not valid"]
              : (x.pack.version ? "release " + String(x.pack.version).replace(/\.0$/, "") : "release not built") + (x.pack.valid ? " ready to hand over" : ", not complete"))
              : h("span", { class: "muted" }, icon("package"), pick("not released yet", "no release")),
            h("span", null, plural(x.decisions, "decision")), h("span", null, plural(x.gates, pick("quality check result", "gate verdict"))),
            h("span", null, tw("ledger") + (x.ledger && x.ledger.intact ? " intact" : pick(" damaged", " broken"))))),
        exportButton(x.project));
    }));
  },
  table: (d) => dataTable([{ label: "Project", key: "title" }, { label: "Attestation", key: "verdict" },
    { label: "Pack", value: (r) => (r.pack ? (r.pack.version || "unbuilt") + (r.pack.valid ? ", valid" : ", not valid") : "none") },
    { label: "Decisions", key: "decisions", num: true }, { label: "Gate verdicts", key: "gates", num: true }, { label: "Runs", key: "runs", num: true },
    { label: "Exports", key: "exports", num: true }], d.evidence_packs || [], "Evidence packs"),
};

// Spend over the agent runs Agent operations reads. With no run there is nothing to price or count: both figures are "not
// measured", never 0.0000 USD and 0 tokens. A cloud sum with an unpriced run in it is not measured either.
function spendOf(d) {
  const s = d.spend || {};
  const noRun = s.runs === 0;
  return { s, noRun, cloudNm: noRun || s.cloud === null || s.cloud === undefined, localNm: noRun || s.local_tokens === null || s.local_tokens === undefined };
}
const runsKnown = (s) => s.runs !== null && s.runs !== undefined;
DEF.spend = {
  views: ["chart", "table"],
  render: (d) => {
    const { s, noRun, cloudNm, localNm } = spendOf(d);
    // the runs and prices Agent operations reads (kernel/agentops_prices.py spend, FR-AOP3): one count, one table
    const blind = s.untokened ? "; " + plural(s.untokened, "run") + " recorded no token counts, so no price measures " + (s.untokened > 1 ? "them" : "it") : "";
    const why = technical() ? (noRun ? "No agent run yet, so nothing is priced." : plural(s.unmeasured_runs || 0, "run") + " without a cost" + blind
      + (s.cloud_measured_part ? "; the priced part is " + fmtMoney(s.cloud_measured_part, s.currency) : "") + ". Models are priced on Agent operations.")
      : noRun ? "AI cost: not known yet. No priced AI work was recorded." : "AI cost: not known yet. Some AI work has no price or recorded no use (priced on Agent operations).";
    const over = (s.window_words ? " over " + s.window_words : "");
    return h("div", { class: "kpi-strip two" },
      h("div", { class: "kpi" + (cloudNm ? " nm" : "") }, h("div", { class: "kpi-h" }, icon("coins"), h("span", null, pick("AI cost", "Cloud spend"))),
        cloudNm ? h("div", { class: "kpi-v nm-text" }, pick("— Not known yet", "— Not measured")) : h("div", { class: "kpi-v" }, fmtMoney(s.cloud, s.currency)),
        h("p", { class: "kpi-sub" }, cloudNm ? why : pick("All AI work is priced.", "Every run is priced.")),
        foot(d, "derived", noRun ? pick("no priced AI work yet", "no run yet") + over : runsKnown(s) ? "over " + plural(s.runs, "run") + (s.window_words ? ", " + s.window_words : "") : null)),
      h("div", { class: "kpi" + (localNm ? " nm" : "") }, h("div", { class: "kpi-h" }, icon("cpu"), h("span", null, pick("AI on this computer", "Local tokens"))),
        localNm ? h("div", { class: "kpi-v nm-text" }, pick("— Not known yet", "— Not measured")) : h("div", { class: "kpi-v" }, num(s.local_tokens)),
        h("p", { class: "kpi-sub" }, noRun ? pick("No AI work on this computer was recorded.", "No agent run yet, so no token is counted.")
          : pick("AI on this computer costs nothing per use.", "Local models cost no API money.")),
        foot(d, "observed", "tokens on local models")));
  },
  table: (d) => {
    const { s, noRun, cloudNm, localNm } = spendOf(d);
    return dataTable([{ label: "Figure", key: "k" }, { label: "Value", key: "v" }], [
      { k: "Runs", v: runsKnown(s) ? num(s.runs) : null },
      { k: "Cloud spend", v: cloudNm ? null : fmtMoney(s.cloud, s.currency) },
      { k: "Runs without a price", v: s.unmeasured_runs === null || s.unmeasured_runs === undefined ? null : num(s.unmeasured_runs) },
      { k: "Local tokens", v: localNm ? null : num(s.local_tokens) }], "Spend");
  },
};

DEF.feed_health = {
  views: ["chart", "table"],
  render: (d) => notMeasured((d.feed_health || {}).why || "No feed has reported yet."),
  table: (d) => dataTable([{ label: "Feed", key: "k" }, { label: "Freshness", key: "v" }], [{ k: "All feeds", v: null }], "Feed health"),
};
DEF.eval_trend = {
  views: ["chart", "table"],
  render: (d) => notMeasured((d.eval_trend || {}).why || "No eval run is recorded yet."),
  table: () => dataTable([{ label: "Eval", key: "k" }, { label: "Trend", key: "v" }], [{ k: "All evals", v: null }], "Eval trend"),
};
DEF.try_it = {
  views: ["list", "table"],
  // The address is where the release was last deployed. Nothing here checks that it still answers, so each
  // row says "last deployed" and offers the checklist, never a running service to try now.
  render: (d) => {
    const rows = (d.try_it || []).filter((t) => t.url);
    if (!rows.length) return notMeasured("No release has been deployed to an address yet. The checklist is ready for when one is.");
    return h("div", null, h("ul", { class: "try-list" }, rows.map((t) => h("li", null, icon("package"),
      h("a", { href: link(t.project, "try"), "aria-label": t.title + ": its checklist" }, t.title),
      h("span", { class: "muted small" }, "release " + t.release + ", last deployed" + (t.env ? " to " + t.env : "") + " · "
        + plural(t.checks, "check"))))),
    h("p", { class: "viz-note try-note" }, icon("info"), h("span", null, "Where each release was last deployed. Whether it still "
      + "answers is not checked here: its checklist opens the address, and it may be stopped.")));
  },
  table: (d) => dataTable([{ label: "Project", key: "title" }, { label: "Release", key: "release", none: "no release yet" },
    { label: "Environment", key: "env", none: "-" }, { label: "Last deployed at", key: "url", none: "not deployed" },
    { label: "Checks", key: "checks", num: true }], d.try_it || [], "What to try"),
};

// Staying on track (kernel/track.py): each project against its approved plan, worst first, with a checkpoint
// due and a running autopilot; a project with no approved plan yet is "not measured", never on track.
DEF.track = {
  views: ["list", "table"],
  render: (d) => {
    const t = d.track || {};
    const rows = t.projects || [];
    if (!rows.length) return empty("flag", "No project yet.");
    const counts = t.counts || {};
    return h("div", null,
      h("p", { class: "muted small tr-counts" }, Object.keys(TRACK).filter((s) => counts[s]).map((s) => counts[s] + " "
        + TRACK[s].word.toLowerCase()).join(" · ") + (t.autopilots ? " · " + plural(t.autopilots, "autopilot") + " holding" : "")),
      h("ul", { class: "health-list" }, rows.map((r) => h("li", { class: "health-row" }, trackState(r),
        h("div", { class: "hr-b" }, h("a", { href: link(r.project, "track") }, r.title || r.project),
          h("p", { class: "muted small", "data-ud": "" }, trackSaid(r))),
        h("span", { class: "hr-f" }, (r.due || []).length ? chip("warning", "eye", "Checkpoint due") : null,
          (r.autopilot || {}).holding ? chip("info", "bot", "Autopilot " + r.autopilot.state) : null)))));
  },
  table: (d) => dataTable([{ label: "Project", value: (r) => r.title || r.project },
    { label: "Track", value: (r) => (TRACK[r.state] || TRACK.not_measured).word },
    { label: "Why", value: (r) => trackSaid(r) },
    { label: "Tasks done", value: (r) => (r.tasks.total === null || r.tasks.total === undefined ? null : r.tasks.done + " of " + r.tasks.total) },
    { label: "Checkpoints due", value: (r) => (r.due || []).join(", ") || "-" },
    { label: "Autopilot", value: (r) => ((r.autopilot || {}).holding ? r.autopilot.id + ", " + r.autopilot.state : "-") }],
  (d.track || {}).projects || [], "Staying on track"),
};

Object.entries(DEF).forEach(([type, def]) => {
  def.render = withProblems(type, def.render);
  def.table = withProblems(type, def.table);
});
export const WIDGET_DEFS = DEF;

// The ⓘ text for a widget: its question, and where its numbers come from.
export const SOURCES = {
  kpi_strip: "kernel.dashboard and kernel.projections.floor: counted from the canon and the ledgers.",
  square: "kernel.signals.square: signals, concepts, the pipeline, end-user feedback and production.",
  pipeline: "kernel.dashboard.pipeline: each project's current stage.",
  decisions: "kernel.dashboard.queue, plus concepts to validate and updates to try. Deciding here uses the Inbox's own route.",
  catalogue: "kernel.dashboard.catalogue: every capability, its state and its capability pack.",
  live: "kernel.status.live: read from Gnomon's own audit trail in the lane each project holds.",
  timeline: "kernel.dashboard.timeline: each round's start, end and gate verdict from the ledger.",
  gate_trend: "kernel.dashboard.gate_trend: rounds passed and not passed per hour.",
  coverage: "kernel.dashboard.coverage: each criterion's evidence state.",
  activity: "kernel.dashboard.activity: the latest ledger events with who acted.",
  models: "kernel.learn.model_reliability: each builder model's record across the ledgers.",
  health: "kernel.status.health: reasons and a forecast from each project's own history.",
  updates: "kernel.observations: one observation rendered for the lens you are in.",
  autonomy: "kernel.autonomy: the ladder, capped by a person with a reason.",
  evidence_packs: "kernel.evidence_pack.attestation, computed read-only; Export writes the bundle.",
  spend: "kernel.agentops_prices.spend: the runs and price table of Agent operations, over 30 days; an unpriced run is never counted as zero.",
  feed_health: "An integration's freshness probe.",
  eval_trend: "A model or agent release's evals, re-measured over time.",
  try_it: "kernel.status.try_it: where the latest release was deployed, and its checks. Whether it still runs is not checked.",
  track: "kernel.track: each project's figures against its approved plan, every one with its basis; checkpoints and autopilots.",
};
