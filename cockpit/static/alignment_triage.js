/* The Alignment view's origin, impact and triage (kernel/alignment_triage.py, FR-ORG1).

   Every item says where it comes from: taken from your project (the file, the line, its last commit, and "may be an
   old plan" when the file is far behind the code) or Rihmasto's convention (the rule it comes from). Before Accept,
   each item shows what accepting does, and Accept all shows the same for the whole group first and asks once. The
   head of the view says, from the real state, how many items are from the project and how many are Rihmasto's
   convention, recommends what to do and offers it as buttons, each with its impact. The words of the kernel are
   shown as data (data-ud); the repository is never written. */

import { pick, emptyState } from "./words.js";
import { h, chip, api, say, signed, needPerson, enc, card, button } from "./core.js";

const FILTERS = [["all", () => "Everything"], ["project", () => "From your project"],
  ["old", () => pick("May be an old plan", "May be stale")], ["convention", () => "Rihmasto's convention"],
  ["deferred", () => "Deferred"]];
const ACTION_WORDS = { reject_stale: () => pick("Reject the old plan's items", "Reject stale"),
  defer_convention: () => "Defer convention items", accept_current: () => "Accept from current sources",
  restore: () => "Bring back deferred" };
let filter = "all";      // the origin shown, kept while the view re-renders

function base(pid) { return "/api/projects/" + enc(pid) + "/repo-alignment"; }
function said(text, tag, cls) { return h(tag || "p", { class: cls || "small", "data-ud": "" }, text); }

/* An item's origin as a chip, and the line that says it in full. */
export function originChip(o) {
  if (!o) return null;
  // a finding about something present in the project (a committed secret, failing tests), not a convention (FR-ORG2)
  if (o.kind === "found") return chip("critical", "alert", "Found in your project", { tip: o.said, "data-origin": "found" });
  if (o.kind === "convention" && o.risk) return chip("warning", "alert", pick("Rihmasto's rule, may be a real risk", "Rihmasto's convention, may be a real risk"),
    { tip: o.said, "data-origin": "risk" });
  if (o.kind === "convention") return chip("neutral", "flag", "Rihmasto's convention", { tip: o.said, "data-origin": "convention" });
  return o.old ? chip("warning", "alert", pick("From your project, may be an old plan", "From your project, may be stale"),
    { tip: o.said, "data-origin": "old" }) : chip("accent", "file-check", "From your project", { tip: o.said, "data-origin": "project" });
}
export function originLine(o) { return o ? said(o.said, "p", "small muted al-origin") : null; }
export function impactLine(item) {
  return item.impact ? h("p", { class: "small al-impact" }, h("span", { class: "muted" }, "Before you accept: "),
    h("span", { "data-ud": "" }, item.impact)) : null;
}
export function rowTags(item) { return (item.origin_tags || "") + (item.deferred ? " deferred" : ""); }

/* The confirm panel: the impact first, then one Confirm. */
function confirmPanel(host, text, label, go) {
  const old = host.querySelector(".al-confirm");
  if (old) old.remove();
  const ok = button(label, { icon: "check", kind: "small primary", key: "al-confirm-ok", aria: "Confirm: " + label });
  const no = button("Cancel", { icon: "x", kind: "small ghost", key: "al-confirm-no", aria: "Cancel: " + label });
  const box = h("div", { class: "al-confirm", role: "group", "aria-label": "Impact of " + label },
    h("p", { class: "small" }, h("b", null, "What this does: "), h("span", { "data-ud": "" }, text)), h("div", { class: "btns" }, ok, no));
  no.addEventListener("click", () => box.remove());
  ok.addEventListener("click", () => go(ok));
  host.append(box);
  ok.focus();
  return box;
}

async function triageDo(pid, payload, kit, btn) {
  if (!needPerson()) return;
  await kit.run(btn, btn.closest("section, li") || btn.parentNode, async () => {
    const out = await api("POST", base(pid) + "/triage", Object.assign(payload, signed()));
    say(out.said, "good");
    await kit.settle(['[data-key="al-scan"]']);
  });
}

/* Accept all of a group: the impact of the whole selection first, asked once. */
export function bulkAccept(pid, ids, label, kit, btn, decide) {
  const host = btn.closest("section") || btn.parentNode;
  kit.run(btn, host, async () => {
    const out = await api("GET", base(pid) + "/impact?items=" + enc(ids.join(",")) + "&verdict=accept");
    confirmPanel(host, out.said, label, (ok) => decide(ok));
  });
}

export function deferButton(pid, item, kit) {
  const back = !!item.deferred;
  const b = button(back ? "Bring back" : "Defer", { icon: back ? "refresh" : "clock", kind: "small ghost",
    key: "al-defer:" + item.id, "data-control": "align_triage", aria: (back ? "Bring back " : "Defer ") + item.title });
  b.addEventListener("click", () => triageDo(pid, { do: back ? "restore" : "defer", items: [item.id] }, kit, b));
  return b;
}

/* A group's counts by origin, for its header. */
export function groupOrigins(g) {
  const o = g.origins || {};
  const parts = [];
  if (o.project) parts.push(chip("accent", null, o.project + " from your project" + (o.old ? " (" + o.old + pick(" may be old", " may be stale") + ")" : ""), { "data-ud": "" }));
  if (o.convention) parts.push(chip("neutral", null, o.convention + " Rihmasto's convention", { "data-ud": "" }));
  if (g.deferred) parts.push(chip("neutral", "clock", g.deferred + " deferred"));
  return parts;
}

function applyFilter(root, f) {
  filter = f;
  root.dataset.filter = f;
  root.querySelectorAll(".al-filter .btn").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.f === f)));
  // a folded "more" list opens when the filter would hide everything shown
  root.querySelectorAll(".al-group").forEach((g) => {
    const rows = [...g.querySelectorAll(".al-row")];
    const shown = rows.filter((r) => f === "all" || (r.dataset.o || "").split(" ").includes(f));
    g.classList.toggle("al-none", rows.length > 0 && shown.length === 0);
  });
  const none = f !== "all" && !root.querySelector(".al-group:not(.al-none) .al-row");
  let box = root.querySelector('[data-empty="align_filter"]');
  if (none && !box) {
    box = emptyState("align_filter", null, { icon: "filter", what: "No item here with this origin.",
      how: "Choose Everything to see every item; Bring back puts a deferred one in the list again, and Read the repository again finds new ones." });
    const bar = root.querySelector(".al-triage");
    if (bar) bar.after(box);
  }
  if (box) box.hidden = !none;
}

function filterBar(root, t) {
  // each filter counts the rows it shows, deferred and decided ones included (kernel: triage.filters, FR-ORG2)
  const n = t.filters || { all: null, project: t.project, old: t.stale, convention: t.convention, deferred: t.deferred };
  const btns = FILTERS.map(([f, label]) => {
    const b = button(label() + (n[f] !== null && n[f] !== undefined ? " (" + n[f] + ")" : ""), { kind: "small ghost",
      key: "al-f:" + f, "data-control": "align_triage" });
    b.dataset.f = f;
    b.setAttribute("aria-pressed", String(f === filter));
    b.addEventListener("click", () => applyFilter(root, f));
    return b;
  });
  return h("div", { class: "btns al-filter", role: "group", "aria-label": "Show items by origin" }, btns);
}

/* The head of the view: counts by origin, the recommendation and its actions, each with its impact. */
export function triageHead(pid, a, kit, root) {
  const t = a.triage;
  if (!t) return null;
  const acts = t.actions.map((x) => {
    const label = (ACTION_WORDS[x.do] || (() => x.label))() + " (" + x.count + ")";
    const b = button(label, { icon: x.do === "accept_current" ? "check-circle" : x.do === "reject_stale" ? "x-circle" : "clock",
      kind: "small" + (x.do === "accept_current" ? " primary" : ""), key: "al-t:" + x.do, "data-control": "align_triage", aria: label });
    b.addEventListener("click", () => {
      if (!needPerson()) return;
      // the items its impact was said for: anything decided since is skipped, and said (FR-ORG2)
      confirmPanel(b.closest(".al-triage"), x.impact, label, (ok) => triageDo(pid, { do: x.do, items: x.items }, kit, ok));
    });
    return b;
  });
  const advice = h("ul", { class: "plain al-advice" }, t.advice.map((x) => h("li", { "data-about": x.about || x.do || null },
    said(x.text, "p"))));
  return card({ title: "What to do with these", icon: "sliders", id: "al-triage", cls: "al-triage",
    info: "Each item is either taken from your project (a file, a line and its last commit) or Rihmasto's convention "
      + "(a rule of how Rihmasto keeps a project). Rihmasto takes your project as it is: its conventions are yours to "
      + "enforce where they help. " + ((a.origin_rules || {}).said || "") },
  said(t.said, "p", "al-triage-said"), advice,
  acts.length ? h("div", { class: "btns al-acts" }, acts) : null,
  filterBar(root, t));
}

export function startFilter(root) { applyFilter(root, filter); }

export function suggestionImpact(s) {
  return h("div", null, s.origin ? h("p", { class: "btns" }, originChip(s.origin)) : null,
    s.impact ? h("p", { class: "small al-impact" }, h("span", { class: "muted" }, "If you apply it: "), h("span", { "data-ud": "" }, s.impact.said)) : null);
}
