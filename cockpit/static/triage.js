/* Decide what matters (FR-NVL1): a project's open decisions triaged by rule. The few that block work, ranked with
   why; one proposal that assumes the rest (each recorded as the person's delegated choice, open to a real answer
   later); and the assumptions that grew in importance as work touched them, with their trigger. The same answer
   comes from Ask Rihma ("I have 50 decisions: what blocks work? assume the rest"). */

import { S, $, h, fill, icon, chip, button, api, enc, link, pageHead, plural } from "./core.js";
import { pick, datum, emptyState, kindWord } from "./words.js";
import { confirmTriage, confirmTriageAll } from "./neverlost.js";

// The persona the triage is read for: its proposal holds only what that persona may decide (FR-NVL2).
function asPersona() { return "?persona=" + enc(S.persona || ""); }

function head(title, sub) {
  return h("div", { class: "q" }, h("h2", { class: "view-h", tabindex: "-1" }, title), sub ? h("p", null, sub) : null);
}

function blockingRow(pid, b) {
  const where = b.card ? link(pid, "inbox", b.card) : link(pid, "assumptions", b.assumption);
  return h("li", { class: "nvl-rank", "data-id": b.card || b.assumption },
    h("span", { class: "nvl-n", "aria-hidden": "true" }, String(b.rank)),
    h("div", null, h("a", { href: where, "data-control": "triage_open" }, h("b", null, (b.card || b.assumption) + " "),
      datum(b.title || "")),
    h("p", { class: "small" }, chip("warning", "alert", kindWord(b.kind) || b.kind.replace(/_/g, " ")), " ", datum(b.why))));
}

function restRow(r) {
  const a = r.assume || {};
  return h("li", { class: "nvl-rest" + (a.refused ? " nvl-refused" : ""), "data-id": r.card }, h("b", null, r.card + " "), datum(r.title || ""),
    h("p", { class: "small muted" }, a.verdict ? icon("check") : icon(a.refused ? "key" : "user"), " ", datum(a.said || "")));
}

function grewRow(pid, g) {
  return h("li", { class: "nvl-grew", "data-id": g.id }, h("b", null, g.id + " "), datum(g.text || ""),
    h("p", { class: "small" }, chip(g.blocking ? "warning" : "info", "pulse", g.blocking ? "Blocks the next step" : "Grew in importance"),
      " reconsider: ", datum(g.trigger || ""), g.blocks ? [" · ", datum(g.blocks)] : null),
    h("p", { class: "small muted" }, "Weight " + g.weight + ": ", datum(g.triggers.map((t) => t.said).join("; "))),
    h("a", { href: link(pid, "assumptions"), class: "btn small", "data-control": "assumption_grew", "data-key": "grew:" + g.id }, "Confirm or correct it"));
}

function body(pid, t) {
  const p = t.proposal || { count: 0 };
  const none = p.refused ? "Nothing you may assume here" : "Nothing to assume";
  const go = button(p.count ? "Assume the other " + p.count + " for me" : none, { kind: "primary", icon: "check",
    key: "triage:assume", "data-control": "triage_assume", disabled: !p.count || null, onclick: (e) => confirmTriage(pid, e.currentTarget) });
  return [
    h("p", { class: "lede", "data-ud": "" }, t.said),
    t.blocking.length ? h("section", { class: "card", "aria-labelledby": "nvl-b-h" }, h("h3", { class: "card-t", id: "nvl-b-h" }, "Blocking work, most first"),
      h("ol", { class: "nvl-list" }, t.blocking.map((b) => blockingRow(pid, b))))
      : emptyState("triage", null, { icon: "check-circle", what: "Nothing blocks work right now.",
        how: "A decision appears here when the next step waits on it: a plan to approve, a stuck task, a blocking question, a go-live." }),
    h("section", { class: "card", "aria-labelledby": "nvl-r-h" }, h("h3", { class: "card-t", id: "nvl-r-h" }, "The rest, assumed for you"),
      t.rest.length ? [h("p", { class: "small" }, pick("Rihma proposes an answer for each. Confirm once: every one is recorded as your choice, signed with your name, "
        + "and you can still answer any of them properly later.", "One proposal: questions are assumed with their perspective's suggestion (an assumption "
        + "with a due date), changes and updates deferred. Each is decided through the canon's own route, signed, and a triage_assumed record names them.")),
      h("ul", { class: "nvl-list" }, t.rest.map(restRow)), h("div", { class: "btns" }, go)]
        : emptyState("triage", null, { what: "No other decision is open.", how: "Decisions that do not block work gather here, with what Rihma would assume for each." })),
    h("section", { class: "card", "aria-labelledby": "nvl-g-h" }, h("h3", { class: "card-t", id: "nvl-g-h" }, "Assumptions that grew in importance"),
      t.grew.length ? h("ul", { class: "nvl-list" }, t.grew.map((g) => grewRow(pid, g)))
        : emptyState("triage", null, { what: "No assumption has grown in importance.",
          how: "An assumption grows as work touches it: a task, change, test or release on its requirement, an overdue review, or a failed check. It comes back here to reconsider." })),
  ];
}

export function render(p) {
  const pid = p.meta.id;
  const root = h("div", { class: "nvl-view" }, head("Decide what matters", pick("What blocks work comes first; Rihma assumes the rest for you to confirm once.",
    "Blocking kinds first, ranked; the rest in one proposal; assumption weights from the records.")),
  h("p", { class: "muted", "aria-busy": "true" }, "Reading the open decisions…"));
  api("GET", "/api/projects/" + enc(pid) + "/triage" + asPersona()).then((t) => {
    if (root.isConnected || root.parentNode) fill(root, root.firstChild, body(pid, t));
  }).catch((e) => {
    // the shell adds "Why? Ask Rihma" to the error box (neverlost.js)
    fill(root, root.firstChild, h("div", { class: "note critical" }, icon("alert"), h("span", null, "The triage could not be read: " + e.message)));
  });
  return root;
}

// -- Decide what matters across every project (FR-NVL2) -------------------------------------------------------

function blockingAllRow(b) {
  const where = b.card ? link(b.project, "inbox", b.card) : link(b.project, "assumptions", b.assumption);
  return h("li", { class: "nvl-rank", "data-id": b.project + ":" + (b.card || b.assumption) },
    h("span", { class: "nvl-n", "aria-hidden": "true" }, String(b.rank)),
    h("div", null, h("a", { href: where, "data-control": "triage_open" }, h("b", null, datum(b.project_title), " · " + (b.card || b.assumption) + " "),
      datum(b.title || "")),
    h("p", { class: "small" }, chip("warning", "alert", kindWord(b.kind) || b.kind.replace(/_/g, " ")), " ", datum(b.why))));
}

function partRow(part) {
  return h("li", { class: "nvl-rest", "data-id": part.project }, h("a", { href: link(part.project, "triage"), "data-control": "triage_open" },
    h("b", null, datum(part.title))), " · ", plural(part.count, "decision") + " to assume: ",
  datum(part.cards.join(", ")));
}

function decideBody(t) {
  const p = t.proposal || { count: 0, projects: [] };
  const go = button(p.count ? "Assume the other " + p.count + " across " + plural(p.projects.length, "project") : "Nothing you may assume",
    { kind: "primary", icon: "check", key: "triage:assume:all", "data-control": "triage_assume", disabled: !p.count || null,
      onclick: (e) => confirmTriageAll(p.projects, e.currentTarget) });
  return [
    h("p", { class: "lede", "data-ud": "" }, t.said),
    t.blocking.length ? h("section", { class: "card", "aria-labelledby": "nvl-ba-h" }, h("h3", { class: "card-t", id: "nvl-ba-h" }, "Blocking work, most first, in every project"),
      h("ol", { class: "nvl-list" }, t.blocking.slice(0, 50).map(blockingAllRow)))
      : emptyState("decide", null, { icon: "check-circle", what: "Nothing blocks work in any project.",
        how: "A decision appears here when a project's next step waits on it: a plan to approve, a stuck task, a blocking question, a go-live." }),
    h("section", { class: "card", "aria-labelledby": "nvl-pa-h" }, h("h3", { class: "card-t", id: "nvl-pa-h" }, "The rest, assumed for you in each project"),
      p.projects.length ? [h("p", { class: "small" }, pick("Confirm once: each project records every one as your choice, signed with your name, and you can still answer any of them properly later.",
        "One confirm runs each project's own triage confirm (POST /api/projects/<pid>/triage/assume), signed; each project records triage_assumed.")),
      h("ul", { class: "nvl-list" }, p.projects.map(partRow)), h("div", { class: "btns" }, go)]
        : emptyState("decide", null, { what: "Nothing you may assume in any project.",
          how: "Decisions that do not block work gather here, per project, with what Rihma would assume for each; one your persona may not decide stays with those who may." })),
  ];
}

export async function renderDecide(seq) {
  let t;
  try { t = await api("GET", "/api/triage" + asPersona()); } catch (e) {
    fill($("#main"), pageHead("Decide what matters", null, { icon: "list" }),
      h("div", { class: "note critical" }, icon("alert"), h("span", null, "The decisions could not be read: " + e.message)));
    return;
  }
  if (seq !== undefined && seq !== S.seq) return;
  document.title = "Decide what matters · Rihmasto.ai";
  fill($("#main"), pageHead("Decide what matters", pick("What blocks work in every project comes first; Rihma assumes the rest for you to confirm once.",
    "Blocking kinds first, ranked across projects; the rest in one proposal per project."), { icon: "list" }), h("div", { class: "nvl-view" }, decideBody(t)));
}
