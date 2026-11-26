/* The data and context layer (FR-CTX1, docs/guides/context-and-data.md).
   A project's Context view: what Rihmasto knows about the project and where it came from, and what each Rihma
   agent is given right now (its context pack: parts, sources, sizes, budget, what was compressed and what was
   left out), with the compression audit's findings. The Data and context page: the factory home's stores, the
   ledgers' integrity, retention and a signed clean-up, and the Context health per agent role. A pack's content
   is shown only to a persona allowed to read it; holdout content never leaves its custody. */

import { S, h, fill, icon, chip, button, api, enc, say, act, needPerson, signed, empty, fmtAt, pageHead, card, num } from "./core.js";
import { dataTable } from "./charts.js";

const STAB = { static: ["good", "the same in every call"], project: ["info", "the same for this project"],
  call: ["warning", "changes with each call"] };

function kb(bytes) {
  if (bytes === null || bytes === undefined) return "-";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1048576).toFixed(1) + " MB";
}
function pctOf(r) { return Math.round((r || 0) * 100) + "%"; }
function bar(value, of, over) {
  const w = of ? Math.min(100, Math.round(value / of * 100)) : 0;
  return h("span", { class: "cx-bar" + (over ? " over" : ""), role: "img", "aria-label": num(value) + " of " + num(of) + " tokens" },
    h("span", { class: "cx-fill", style: { width: w + "%" } }));
}
function stabChip(s) { const t = STAB[s] || ["neutral", s]; return chip(t[0], null, s, { title: t[1] }); }
function okChip(ok, yes, no) { return ok ? chip("good", "check-circle", yes) : chip("critical", "x-circle", no); }

// -- what Rihmasto knows -----------------------------------------------------------------------------------

function knows(m) {
  const g = m.graph || {};
  const counts = (o) => Object.entries(o || {}).map(([k, v]) => k.replace(/_/g, " ") + " " + v).join(", ") || "none";
  return h("div", { class: "cx-grid" },
    card({ title: "Sources", icon: "folder", info: "Where what Rihmasto knows came from, and when each was last read." },
      dataTable([{ label: "Source", value: (s) => s.label }, { label: "State", value: (s) => s.present ? chip("good", "check", "present") : chip("neutral", "dashed", "none") },
        { label: "What", value: (s) => h("span", { class: "small" }, s.detail) }, { label: "Updated", value: (s) => s.updated ? fmtAt(s.updated) : null, none: "-" }],
      m.sources, "Sources of the project's context")),
    card({ title: "Records", icon: "layers" },
      h("dl", { class: "kv" },
        h("div", null, h("dt", null, "Questions"), h("dd", null, counts(m.records.questions))),
        h("div", null, h("dt", null, "Assumptions"), h("dd", null, counts(m.records.assumptions) + (m.records.assumptions_overdue ? " · " + m.records.assumptions_overdue + " overdue" : ""))),
        h("div", null, h("dt", null, "Decisions"), h("dd", null, m.records.decisions.total + " (" + m.records.decisions.stale + " stale)")),
        h("div", null, h("dt", null, "Open cards"), h("dd", null, counts(m.records.cards.open))),
        h("div", null, h("dt", null, "Ledger"), h("dd", null, okChip(m.ledger.intact, "intact", "broken at " + m.ledger.broken_seq), " ",
          num(m.ledger.records) + " records · " + kb(m.ledger.bytes))),
        h("div", null, h("dt", null, "Graph"), h("dd", null, g.outcome === "answered"
          ? counts(g.nodes) + " · " + (g.contradictions ? chip("warning", "alert", g.contradictions + " contradiction(s)") : "no contradictions")
          : h("span", { class: "nm-text" }, "not measured: " + (g.why || g.outcome)))),
        h("div", null, h("dt", null, "Spec"), h("dd", null, m.spec.present ? m.spec.requirements + " requirements · " + m.spec.superseded.length + " superseded version(s)" : "not written yet")),
        h("div", null, h("dt", null, "Contract"), h("dd", null, m.contract.present ? m.contract.tasks + " tasks · revision " + String(m.contract.revision || "").slice(0, 19) : "not compiled yet")),
        h("div", null, h("dt", null, "Model runs"), h("dd", null, m.usage.runs + " · " + (Object.keys(m.usage.roles).join(", ") || "none"))))),
    card({ title: "Freshness", icon: "clock", info: "A record written before something it rests on changed is stale." },
      m.freshness.length ? h("ul", { class: "plain cx-fresh" }, m.freshness.map((f) => h("li", null,
        f.stale ? chip("warning", "alert", "stale") : chip("good", "check", "fresh"), " ", h("b", null, f.what),
        h("span", { class: "muted small" }, " · " + (f.updated ? fmtAt(f.updated) : "-")), f.why ? h("p", { class: "small" }, f.why) : null)))
        : h("p", { class: "muted small" }, "Nothing written yet to be stale.")),
    card({ title: "Kept on disk", icon: "server" },
      dataTable([{ label: "Store", value: (r) => r[0] }, { label: "Size", value: (r) => kb(r[1].bytes), num: true }, { label: "Files", value: (r) => String(r[1].files), num: true }],
        Object.entries(m.stores.by_store), "What the project keeps on disk")));
}

// -- what each agent is given ---------------------------------------------------------------------------------

function packRows(packs, onOpen) {
  return h("ul", { class: "plain cx-packs", "data-control": "context_pack" }, packs.map((p) => h("li", { class: "cx-pack", "data-pack": p.id },
    h("div", { class: "cx-pt" }, h("b", null, p.label), p.target ? h("span", { class: "muted small" }, " · " + String(p.target).slice(0, 60)) : null),
    p.unavailable ? h("p", { class: "muted small" }, p.unavailable) : h("div", { class: "cx-pm" },
      bar(p.with_system, p.budget, p.over_budget),
      h("span", { class: "small" }, num(p.with_system) + " of " + num(p.budget) + " tokens"),
      p.over_budget ? chip("critical", "alert", "over budget") : null,
      chip("neutral", null, pctOf(p.prefix.ratio) + " cacheable", { title: "the share of a call a prompt cache reuses between calls" }),
      p.violations ? chip("warning", "alert", p.violations + " order issue(s)") : null,
      button("Open", { icon: "eye", kind: "small", key: "cx-open:" + p.id, "aria-label": "Open the " + p.label + " pack", onclick: () => onOpen(p.id) })))));
}

function partRow(x) {
  return h("li", { class: "cx-part" },
    h("details", null, h("summary", null, h("b", null, x.name), " ", stabChip(x.stability),
      h("span", { class: "muted small" }, " " + num(x.chars) + " chars · ~" + num(x.tokens) + " tokens · " + x.source)),
    x.content === null ? h("p", { class: "muted small" }, "Its content is not shown to your persona.")
      : h("pre", { class: "cx-pre" }, x.content)));
}

function drawPack(box, p) {
  if (p.unavailable) { fill(box, h("p", { class: "muted" }, p.label + ": " + p.unavailable)); return; }
  const parts = (p.system ? [p.system] : []).concat(p.parts);
  fill(box, h("div", { class: "cx-detail", "data-pack": p.id },
    h("h3", { class: "label-h" }, icon("eye"), " ", p.label, p.target ? " · " + String(p.target).slice(0, 80) : ""),
    h("p", { class: "small" }, num(p.with_system.chars) + " characters, ~" + num(p.with_system.tokens) + " tokens with the system prompt; budget "
      + num(p.budget.tokens) + " (" + p.budget.why + "). " + pctOf(p.prefix.ratio) + " is reused between calls of this project, "
      + pctOf(p.shared.ratio) + " between every project. Built by " + p.where + "."),
    p.note ? h("p", { class: "muted small" }, p.note) : null,
    p.content_note ? h("p", { class: "toast-inline warning" }, icon("shield"), p.content_note) : null,
    h("ul", { class: "plain cx-parts" }, parts.map(partRow)),
    p.violations.length ? h("div", null, h("h4", null, "Order"), h("ul", { class: "plain" }, p.violations.map((v) =>
      h("li", { class: "small" }, chip("warning", "alert", "order"), " " + v.part + " changes more often than " + num(v.chars_behind) + " characters after it")))) : null,
    h("h4", null, "Compressed"), p.compressed.length ? h("ul", { class: "plain cx-list" }, p.compressed.map((c) =>
      h("li", { class: "small" }, h("b", null, c.what), ": " + c.how + " (" + c.why + ")"))) : h("p", { class: "muted small" }, "Nothing was cut."),
    h("h4", null, "Left out, and why"), h("ul", { class: "plain cx-list" }, p.excluded.map((e) =>
      h("li", { class: "small" }, icon("shield"), " ", h("b", null, e.what), ": " + e.why))),
    p.outputs ? h("div", null, h("h4", null, "Each tool's answer"), dataTable([{ label: "Tool", key: "tool" },
      { label: "Characters", value: (o) => num(o.chars), num: true }, { label: "Tokens", value: (o) => num(o.tokens), num: true },
      { label: "Budget", value: (o) => o.over_budget ? chip("critical", "alert", "over") : chip("good", "check", "within") }], p.outputs, "Each MCP tool's answer")) : null));
}

async function openPack(pid, packId, box) {
  fill(box, h("p", { class: "muted small" }, "Building the pack…"));
  try {
    drawPack(box, await api("GET", "/api/projects/" + enc(pid) + "/context/pack?pack=" + enc(packId) + "&persona=" + enc(S.persona || "")));
    box.scrollIntoView({ block: "nearest" });
  } catch (e) { fill(box, empty("alert", e.message)); }
}

function findings(list) {
  if (!list.length) return h("p", { class: "muted small" }, "Nothing found: every pack is within its budget, says each line once, and puts what changes after what does not.");
  return h("ul", { class: "plain cx-list" }, list.map((f) => h("li", { class: "small" },
    chip(f.kind === "over_budget" || f.kind === "oversized_output" ? "critical" : "warning", "alert", f.kind.replace(/_/g, " ")),
    " ", h("b", null, f.where), ": " + f.detail, h("p", { class: "muted small" }, "Proposed: " + f.proposal))));
}

export function viewContext(p) {
  const pid = p.meta.id;
  const body = h("div", { class: "cx-body" }, h("p", { class: "muted small" }, "Reading what Rihmasto knows…"));
  const view = h("div", { class: "cx-view" },
    h("div", { class: "q" }, h("h2", { id: "view-title", tabindex: "-1" }, "Context"),
      h("p", null, "What Rihmasto knows about this project and where it came from, and what each of its agents is given right now.")), body);
  api("GET", "/api/projects/" + enc(pid) + "/context-map?persona=" + enc(S.persona || "")).then((d) => {
    const detail = h("div", { class: "cx-pack-detail", id: "cx-detail", "aria-live": "polite" });
    const audit = h("div", { "data-control": "context_audit" }, h("p", { class: "muted small" }, "Auditing…"));
    fill(body, knows(d.map),
      card({ title: "What each agent is given", icon: "bot", info: "Each Rihma agent's context pack: the prompt the code builds now, cut into its parts." },
        packRows(d.packs, (id) => openPack(pid, id, detail)), detail),
      card({ title: "Compression findings", icon: "gauge" }, audit));
    api("GET", "/api/projects/" + enc(pid) + "/context/audit").then((a) => fill(audit, findings(a.findings)))
      .catch((e) => fill(audit, empty("alert", e.message)));
  }).catch((e) => fill(body, empty("alert", e.message)));
  return view;
}

// -- the Data and context page ---------------------------------------------------------------------------------

function health(doc) {
  return card({ title: "Context health", icon: "gauge", id: "cx-health", info: "Per agent role: pack sizes against the budget, and how much of each call a prompt cache reuses." },
    h("div", { "data-control": "context_health" },
      dataTable([{ label: "Role", value: (r) => r.label }, { label: "Measured", value: (r) => String(r.measured), num: true },
        { label: "Average", value: (r) => r.measured ? num(r.average_tokens) : null, num: true, none: "-" },
        { label: "Largest", value: (r) => r.measured ? num(r.max_tokens) : null, num: true, none: "-" },
        { label: "Budget", value: (r) => r.budget ? num(r.budget) : null, num: true, none: "-" },
        { label: "Over", value: (r) => r.measured ? (r.over_budget ? chip("critical", "alert", String(r.over_budget)) : chip("good", "check", "0")) : null, none: "-" },
        { label: "Cacheable", value: (r) => r.measured ? pctOf(r.prefix_ratio) : null, num: true, none: "-" }], doc.health, "Context health per agent role"),
      h("h4", null, "Compressed so far"),
      dataTable([{ label: "What", key: "what" }, { label: "How", value: (f) => h("span", { class: "small" }, f.how) },
        { label: "Before", value: (f) => h("span", { class: "mono small" }, JSON.stringify(f.before)) },
        { label: "After", value: (f) => h("span", { class: "mono small" }, JSON.stringify(f.after)) }], doc.fixes, "What was compressed"),
      h("h4", null, "Findings across the factory"), findings(doc.findings)));
}

function cleanup(d, redraw) {
  const propose = button("Propose a clean-up", { icon: "refresh", key: "data-cleanup", "data-control": "data_cleanup", onclick: (e) => {
    if (!needPerson()) return;
    act(e.currentTarget.closest("section"), async () => {
      const out = await api("POST", "/api/data/cleanup", signed());
      say(out.proposal.id + " proposed: " + out.proposal.items.length + " item(s), " + kb(out.proposal.bytes) + ".", "good");
      redraw();
    });
  } });
  const apply = (cid) => button("Apply " + cid, { icon: "check", kind: "small", key: "data-apply:" + cid, "data-control": "data_apply", onclick: (e) => {
    if (!needPerson()) return;
    act(e.currentTarget.closest("section"), async () => {
      const out = await api("POST", "/api/data/cleanup/" + enc(cid) + "/apply", signed());
      say(cid + ": " + out.proposal.removed.length + " removed, " + out.proposal.kept.length + " kept.", "good");
      redraw();
    });
  } });
  return card({ title: "Clean-up", icon: "refresh", id: "data-clean", info: "What can go safely, by rule. Ledgers, records and the holdout custody are never cleaned." },
    h("p", { class: "small" }, d.cleanable.items.length + " item(s) can be cleaned now (" + kb(d.cleanable.bytes) + "): job logs and unreferenced snapshots older than "
      + d.retain_days + " days. A proposal is signed with your name; " + d.cleaners.join(" or ") + " applies it. Never cleaned: " + d.never_cleaned + "."),
    d.cleanable.items.length ? h("ul", { class: "plain cx-list" }, d.cleanable.items.map((i) => h("li", { class: "small mono" }, i.path + " · " + kb(i.bytes)))) : null,
    h("div", { class: "cx-actions" }, propose),
    d.proposals.length ? h("ul", { class: "plain cx-list" }, d.proposals.map((p) => h("li", { class: "small" },
      chip(p.state === "applied" ? "good" : "warning", null, p.state), " ", h("b", null, p.id), " by " + p.person + " · " + p.items.length + " item(s) · "
      + kb(p.bytes), p.state === "proposed" ? apply(p.id) : null))) : null);
}

export async function renderData(seq) {
  const main = $main();
  let d, doc;
  try { [d, doc] = await Promise.all([api("GET", "/api/data"), api("GET", "/api/context/health")]); } catch (e) { fill(main, empty("alert", e.message)); return; }
  if (seq !== S.seq) return;
  document.title = "Data and context · Rihmasto.ai";
  const redraw = () => renderData(S.seq);
  fill(main, pageHead("Data and context", "What the factory keeps, whether its ledgers hold, what can be cleaned, and how large each agent's context is.",
    { icon: "server", actions: [button("Refresh", { icon: "refresh", kind: "quiet", key: "data-refresh", onclick: redraw })] }),
  h("div", { class: "cx-grid" },
    health(doc),
    card({ title: "Stores", icon: "server", id: "data-stores" },
      h("p", { class: "small" }, kb(d.bytes) + " in the factory home · " + d.projects + " project(s) · " + d.incidents + " incident(s)"),
      dataTable([{ label: "Store", value: (r) => r.label }, { label: "Size", value: (r) => kb(r.bytes), num: true },
        { label: "Files", value: (r) => String(r.files), num: true }, { label: "Kept", value: (r) => h("span", { class: "small" }, r.retention) }],
      d.stores, "The factory home's stores")),
    card({ title: "Ledgers", icon: "layers", id: "data-ledgers" },
      h("p", { class: "small" }, okChip(!d.integrity.broken.length, d.integrity.intact + " of " + d.integrity.ledgers + " intact", d.integrity.broken.length + " broken")),
      dataTable([{ label: "Ledger", value: (l) => l.title || l.ledger }, { label: "Records", value: (l) => num(l.records), num: true },
        { label: "Size", value: (l) => kb(l.bytes), num: true }, { label: "Chain", value: (l) => okChip(l.intact, "intact", "broken at " + l.broken_seq) }],
      d.ledgers, "Every ledger, its hash chain verified now")),
    cleanup(d, redraw)));
}

function $main() { return document.getElementById("main"); }
