/* Where the work went (kernel/work_balance.py, FR-STR1): of the decisions and changes in a period, how many moved
   development (code, tests, features, fixes) and how many conformed to Rihmasto's structure (records, traces,
   conventions). Two bars with the items behind each, one plain sentence, and a warning with what to do when
   conformance dominates while development stalls. On a project's Overview, and across projects at the top of
   Insights. Counted from the records; nothing here writes one. */

import { h, fill, icon, chip, api, enc, card, plural, ago, AuthError, local, segmented } from "./core.js";
import { bars, SERIES } from "./charts.js";
import { pick, datum, emptyState } from "./words.js";

const STORE = "gf.workbalance.window";
const WINDOWS = [["7d", "7 days"], ["30d", "30 days"], ["90d", "90 days"], ["all", "All"]];
const SHOWN = 12;
// A next step's button wraps its words on a phone instead of widening the page.
const WRAP = { whiteSpace: "normal", height: "auto", maxWidth: "100%", textAlign: "left", alignItems: "flex-start" };

function windowNow() {
  let w = null;
  try { w = local.get(STORE); } catch (e) { w = null; }
  return WINDOWS.some(([k]) => k === w) ? w : "30d";
}

function itemList(side, items, more) {
  return h("ul", { class: "plain wb-items", "data-side": side }, items.slice(0, SHOWN).map((i) => h("li", { class: "small" },
    h("a", { href: i.href }, datum(i.title)), i.at ? h("span", { class: "muted" }, " · " + ago(i.at)) : null)),
  items.length > SHOWN || more ? h("li", { class: "small muted" }, plural(items.length - SHOWN + (more || 0), "more item")) : null);
}

function sideDetails(key, label, s) {
  if (!s.n) return null;
  return h("details", { class: "as-more wb-side", "data-key": "wb-" + key },
    h("summary", null, label + ": " + plural(s.n, "item")), itemList(key, s.items, s.more));
}

function projectRows(w) {
  if (w.scope !== "factory" || w.projects.length < 2) return null;
  return h("details", { class: "as-more", "data-key": "wb-projects" }, h("summary", null, pick("By project", "Per project")),
    h("ul", { class: "plain wb-projects" }, w.projects.filter((r) => r.development || r.conformance).map((r) => h("li", { class: "small" },
      h("a", { href: r.href }, datum(r.title)), ": " + r.development + pick(" moved the work on, ", " development, ") + r.conformance
        + pick(" followed Rihmasto's way", " conformance"), r.warning ? [" ", chip("warning", "alert", pick("Mostly following the way", "Conformance dominates"))] : null))));
}

function body(w) {
  if (!w.measured) {
    return emptyState("work", null, { icon: "activity", what: pick("Nothing counted in this period yet.", "No development or conformance recorded in this window."),
      how: pick("Accepting or rejecting what Rihmasto found in the code, finishing a change or a new version of the code shows here.",
        "Alignment decisions on Rihmasto's conventions, a convention raised to Enforce and Will fix on its card count as conformance; "
        + "merges, passing checks, applied changes, releases and the repository's own commits count as development. What is taken in "
        + "from the project's own files counts in neither.") });
  }
  const dev = w.development;
  const con = w.conformance;
  return [
    h("p", { class: "wb-line", "data-key": "wb-line" }, datum(w.line)),
    w.warning ? h("div", { class: "note warning wb-warn", role: "note", "data-key": "wb-warning" }, icon("alert"),
      h("div", { style: { minWidth: "0" } }, datum(w.warning), w.suggestions.length ? h("ul", { class: "plain wb-next" }, w.suggestions.map((s, n) =>
        h("li", { style: { margin: "6px 0" } }, h("a", { href: s.route, class: "btn small" + (n ? "" : " primary"), "data-key": "wb-go:" + n, style: WRAP },
          icon("arrow-right"), h("span", { class: "lbl", style: { whiteSpace: "normal" } }, datum(s.text)))))) : null)) : null,
    bars({ unit: "items", rows: [
      { label: pick("Moved the work on", "Moved development"), value: dev.n, color: SERIES(1), sub: dev.said || null,
        tip: pick("Code changed, tests added or passing, features and fixes", "Merges, passing checks, commits, applied changes, releases") },
      { label: pick("Followed Rihmasto's way", "Conformed to Rihmasto's structure"), value: con.n, color: SERIES(3), sub: con.said || null,
        tip: pick("Traces, gaps and enforced conventions of Rihmasto's own", "Decisions on Rihmasto's conventions, Enforce set, Will fix on its cards") }] }),
    sideDetails("dev", pick("What moved the work on", "Development"), dev),
    sideDetails("conform", pick("What followed Rihmasto's way", "Conformance"), con),
    // The project's own records taken in: its own structure, in neither bar, as the Alignment view says (FR-STR2).
    sideDetails("take_in", pick("Taken in from the project's own files (in neither bar)", "Taken in (neither bar)"), w.taken_in || { n: 0 }),
    projectRows(w),
  ];
}

/* The card: ``pid`` for one project, null across every project. */
export function workCard(pid) {
  const box = h("div", { class: "wb-body", "aria-live": "polite" }, h("p", { class: "muted small" }, "Counting the records…"));
  let win = windowNow();
  const draw = () => api("GET", "/api/work-balance?window=" + enc(win) + (pid ? "&project=" + enc(pid) : ""))
    .then((w) => fill(box, body(w)))
    .catch((e) => { if (!(e instanceof AuthError)) fill(box, h("p", { class: "note warning" }, icon("alert"), h("span", null, e.message))); });
  const pickWin = segmented("wb-window", WINDOWS, win, (v) => { win = v; try { local.set(STORE, v); } catch (e) { /* kept for this view only */ } draw(); },
    { label: pick("Period", "Window"), cls: "small" });
  draw();
  return h("div", { class: "section wb", "data-control": "work_balance" }, card({ title: pick("Where the work went", "Where the work went: development or conformance"),
    icon: "activity", id: pid ? "wb-card" : "wb-all",
    info: "Of the decisions and changes in the period, how many moved development and how many only conformed to Rihmasto's own "
      + "structure. Counted from the records, never estimated. A warning appears when following Rihmasto's way takes most of the work." },
  h("div", { class: "btns wb-window" }, pickWin), box));   // the period under the title, so a phone keeps the title whole
}
