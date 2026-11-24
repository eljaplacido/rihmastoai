/* The intake summary (docs/guides/inputs.md): what the input stated, what was asked and what was assumed,
   side by side, from the project's `intake_summary` (kernel/input_summary.py). Each fact carries its document
   and lines; nothing here writes, and every decision on a question stays on its own card. */

import { h, icon, chip, plural, link, PERSPECTIVE_LABEL } from "./core.js";

const STATE = {
  given: ["good", "check-circle", "from your input"],
  answered: ["good", "user", "answered"],
  asked: ["warning", "comment", "asked, waiting"],
  assumed: ["info", "flag", "assumed"],
  "left open": ["nm", "dashed", "left open in your input"],
  open: ["nm", "dashed", "not stated, not asked"],
};

function where(item) {
  const [a, b] = item.lines || [];
  return item.document + " · " + (a === b ? "line " + a : "lines " + a + "–" + b);
}

function column(id, title, iconName, note, items, emptyText) {
  return h("section", { class: "is-col", "aria-labelledby": id },
    h("h4", { id, class: "is-col-h" }, icon(iconName), h("span", null, title), " ",
      h("span", { class: "is-count" }, String(items.length))),
    note ? h("p", { class: "muted small" }, note) : null,
    items.length ? h("ul", { class: "plain is-list" }, items) : h("p", { class: "muted small" }, emptyText));
}

function factItem(f) {
  return h("li", { class: "is-item" }, chip("neutral", null, f.label), " ", h("span", { class: "is-quote" }, f.text),
    h("span", { class: "is-where mono" }, where(f)));
}
function decisionItem(d) {
  return h("li", { class: "is-item" }, chip("accent", "check", "decision " + d.id), " ", h("span", { class: "is-quote" }, d.text),
    h("span", { class: "is-where mono" }, where(d)));
}
function requirementItem(r) {
  return h("li", { class: "is-item" }, chip("accent", "file-check", r.id), " ", h("span", { class: "is-quote" }, r.statement),
    h("span", { class: "is-where mono" }, where(r) + " · " + plural(r.criteria, "criterion", "criteria")));
}
function facetChips(s, q) {
  const labels = Object.fromEntries((s.facets || []).map((f) => [f.facet, f.label]));
  return (q.facets || []).map((f) => chip("neutral", null, labels[f] || f));
}
function askedItem(pid, s, q) {
  const state = q.status === "answered"
    ? chip("good", "user", "answered by " + q.by)
    : chip("warning", "comment", q.blocking ? "open · blocking" : "open");
  return h("li", { class: "is-item" },
    h("a", { href: link(pid, "questions", q.id), class: "mono" }, q.id), " ", h("span", { class: "is-quote" }, q.text), " ",
    state, facetChips(s, q), q.checklist ? chip("nm", null, "checklist") : null,
    q.status === "answered" ? h("span", { class: "is-answer" }, "“" + q.answer + "”") : null);
}
function assumedItem(pid, s, q) {
  return h("li", { class: "is-item" },
    h("a", { href: link(pid, "questions", q.id), class: "mono" }, q.id), " ", h("span", { class: "is-quote" }, q.text),
    h("span", { class: "is-answer" }, "→ " + q.answer), facetChips(s, q),
    h("span", { class: "is-where mono" }, (q.assumption || "") + (q.due ? " · due " + q.due : "")
      + (q.chosen_by ? " · chosen by " + q.chosen_by : "")));
}

function facetsTable(s) {
  return h("table", { class: "is-facets" },
    h("caption", { class: "muted small" }, "Every facet of the checklist, and where it stands"),
    h("thead", null, h("tr", null, h("th", { scope: "col" }, "Facet"), h("th", { scope: "col" }, "State"),
      h("th", { scope: "col" }, "Rests on"))),
    h("tbody", null, s.facets.map((f) => {
      const [tone, ic, word] = STATE[f.state] || STATE.open;
      return h("tr", null, h("th", { scope: "row" }, f.label), h("td", null, chip(tone, ic, word),
        f.note ? h("span", { class: "muted small is-note" }, " " + f.note) : null),
        h("td", { class: "mono" }, f.facts.concat(f.questions).join(", ") || "–"));
    })));
}

function notAsked(s) {
  if (!s.not_asked.length) return null;
  return h("div", { class: "is-not-asked" }, h("h4", { class: "is-col-h" }, icon("eye"),
    h("span", null, "Not asked, because your input already says it"), " ",
    h("span", { class: "is-count" }, String(s.not_asked.length))),
  h("ul", { class: "plain is-list" }, s.not_asked.map((x) => h("li", { class: "is-item" },
    h("span", { class: "is-quote" }, "“" + x.text + "”"), " ",
    h("span", { class: "muted small" }, (x.from === "profile" ? "the profile" : PERSPECTIVE_LABEL[x.perspective] || x.perspective)
      + " · rests on " + x.because.join(", "))))));
}

function proposal(s) {
  const m = s.model_proposed;
  if (!m || !m.measured) return null;
  const kind = m.kind && m.kind !== s.kind ? "reads it as " + m.kind : "agrees with the kind";
  return h("p", { class: "note is-model" }, icon("bot"), h("span", null, "Rihma's model (proposed, not decided) " + kind
    + (m.stated.length ? "; it also reads " + m.stated.map((x) => x.facet + " at " + where(x)).join(", ") : "")
    + ". Asked by " + m.asked_by + "."));
}

export function intakeSummary(p) {
  const s = p.intake_summary;
  if (!s) return null;
  const pid = p.meta.id;
  const given = s.from_input.facts.map(factItem).concat(s.from_input.decisions.map(decisionItem),
    s.from_input.requirements.map(requirementItem));
  const docs = s.documents.length > 1 ? " · " + s.documents.map((d) => d.name + " (" + d.kind + ")").join(", ") : "";
  return h("section", { class: "section intake-sum", "aria-labelledby": "is-h", "data-control": "intake_summary" },
    h("div", { class: "is-head" }, h("h3", { id: "is-h", tabindex: "-1" }, "Intake summary"),
      h("p", { class: "muted small" }, "Read as " + s.kind_label + " (by " + s.kind_by + ", " + s.confidence + "), in "
        + s.language_label + ": " + s.basis.join("; ") + docs + ".")),
    h("div", { class: "is-cols" },
      column("is-given-h", "From your input", "file-check", "Given by " + (s.by || "the request") + ", never asked again.",
        given, "Nothing the checklist reads: every facet is a gap."),
      column("is-asked-h", "Asked", "comment", "Put to a person, who answers on the card.",
        s.asked.map((q) => askedItem(pid, s, q)), "Nothing was put to a person."),
      column("is-assumed-h", "Assumed", "flag", "Each with a due date, until a person confirms or refutes it.",
        s.assumed.map((q) => assumedItem(pid, s, q)), "Nothing was assumed.")),
    proposal(s),
    notAsked(s),
    h("details", { class: "is-more" }, h("summary", null, "The facet checklist: " + s.counts.given + " given, "
      + plural(s.counts.open, "still open", "still open")), facetsTable(s)));
}
