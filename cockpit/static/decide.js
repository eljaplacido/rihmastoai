/* An Inbox card that says what it wants (FR-UXO1). The owner: "Inbox is very unclear, it's not clear where it's
   asking for comments."

   A card leads with one plain line, "Decide: <what, in plain words>: <its choices>". The choices are clear
   options, each with a one-line meaning; nothing is chosen for the person. Once they pick one, "Why? (optional,
   saved with your decision)" opens with Confirm; the reason is part of the decision. Commenting is separate and
   secondary ("Add a comment": it decides nothing). The card's ids, refs and the record's own wording are folded
   under Details. Used by a project's Inbox (project.js) and the Inbox across projects (screens.js). */

import { h, icon, chip, needPerson, fmtAt, personaLabel, KIND_LABEL, VERDICT_LABEL, ago } from "./core.js";
import { meaning, technical, word, plainCard, cardTitle } from "./words.js";

// A reason the kernel asks for: parking or rejecting a need is said to the person who raised it.
const REASON_NEEDED = new Set(["concept.park", "concept.reject", "approval.reject"]);
// Approving a blocking enforcement card is an override: its reason is recorded with it (kernel/canon.py, FR-ENF2).
const reasonNeeded = (c, v) => REASON_NEEDED.has(c.kind + "." + v) || (c.kind === "enforcement" && v === "approve" && !!c.blocking);

// "Decide: <what>": the choices are the buttons below, so the line does not list them; where the request came
// from ("From the website chat") is a small tag beside it.
export function decideLine(c) {
  const from = cardTitle(c.title).from;
  return h("span", { class: "dl" }, h("span", { class: "dl-k" }, "Decide:"), " ", plainCard(c),
    from ? [" ", h("span", { class: "chip neutral src-tag" }, from)] : null);
}

// The card's technical facts, folded: its id and kind, the record's own title, refs and who may decide.
export function details(c, extra) {
  const refs = Object.entries(c.refs || {}).map(([k, v]) => h("div", null, h("dt", null, k), h("dd", { class: "mono" }, Array.isArray(v) ? v.join(", ") : String(v))));
  return h("details", { class: "card-details" + (technical() ? " tech" : "") },
    h("summary", null, word("details")),
    h("dl", { class: "kv tight" },
      h("div", null, h("dt", null, "card"), h("dd", { class: "mono" }, c.id + " · " + (KIND_LABEL[c.kind] || c.kind))),
      c.plain && c.title && c.plain !== c.title ? h("div", null, h("dt", null, "recorded as"), h("dd", null, cardTitle(c.title).text)) : null,
      h("div", null, h("dt", null, "opened"), h("dd", null, fmtAt(c.created))),
      h("div", null, h("dt", null, "who may decide"), h("dd", null, (c.deciders || []).map(personaLabel).join(", "))),
      refs),
    extra || null);
}

export function cardTop(c, idAttr, opts) {
  const o = opts || {};
  return [
    h("div", { class: "hd" }, h("span", { class: "dec-ic" }, icon(o.icon || "inbox")), h("span", { class: "label" }, KIND_LABEL[c.kind] || c.kind),
      technical() ? h("span", { class: "mono muted small" }, c.id) : null,
      o.project || null,
      c.blocking ? chip("warning", "alert", technical() ? "Blocking" : "Holds work up") : null,
      h("span", { class: "muted small ib-age" }, icon("clock"), ago(c.created))),
    h("h3", { class: "card-t decide-t", id: idAttr }, decideLine(c)),
  ];
}

/* The choices, then (once one is picked) Why and Confirm. ``key`` prefixes every data-key (the card's id in a
   project, project and id across projects); ``reasonId`` is the reason field's id; ``draft`` keeps what was typed
   across a re-render; ``decide(verdict, reason)`` makes the signed write and returns once it is done. */
export function decideBlock(c, opts) {
  const o = opts || {};
  const key = o.key || c.id;
  let chosen = null;
  const reason = h("textarea", { id: o.reasonId || "reason-" + key, rows: "2", "data-key": key + ":reason", maxlength: "2000" });
  if (o.draft) {
    reason.value = o.draft.get() || "";
    reason.addEventListener("input", () => o.draft.set(reason.value));
  }
  const whyLabel = h("label", { for: reason.id });
  const confirm = h("button", { type: "button", class: "btn primary human", "data-key": key + ":confirm", "data-control": "decide" });
  const change = h("button", { type: "button", class: "btn quiet", "data-key": key + ":unpick" }, "Change my choice");
  const why = h("div", { class: "why-box", hidden: true }, h("div", { class: "field" }, whyLabel, reason), h("div", { class: "btns" }, confirm, change));
  const radios = (c.verdicts || []).map((v) => {
    const b = h("button", { type: "button", role: "radio", "aria-checked": "false", class: "dc-opt", "data-key": key + ":" + v, "data-control": "decide" },
      h("b", null, VERDICT_LABEL[v] || v), meaning(c.kind, v) ? h("span", { class: "dc-m" }, meaning(c.kind, v)) : null);
    b.addEventListener("click", () => pick(v));
    return b;
  });
  const group = h("div", { class: "dc-opts", role: "radiogroup", "aria-label": "Your choice on " + (c.plain || c.title) }, radios);
  group.addEventListener("keydown", (e) => {
    const step = e.key === "ArrowDown" || e.key === "ArrowRight" ? 1 : e.key === "ArrowUp" || e.key === "ArrowLeft" ? -1 : 0;
    const i = radios.indexOf(document.activeElement);
    if (!step || i < 0) return;
    e.preventDefault();
    radios[(i + step + radios.length) % radios.length].focus();
  });
  function pick(v) {
    chosen = v;
    radios.forEach((r) => r.setAttribute("aria-checked", String(r.dataset.key === key + ":" + v)));
    const needed = reasonNeeded(c, v);
    whyLabel.textContent = needed ? "Why? (needed: it is saved with your decision and told to who asked)" : "Why? (optional, saved with your decision)";
    confirm.textContent = "Confirm: " + (VERDICT_LABEL[v] || v);
    why.hidden = false;
    reason.focus();
  }
  change.addEventListener("click", () => {
    chosen = null;
    radios.forEach((r) => r.setAttribute("aria-checked", "false"));
    why.hidden = true;
    if (radios[0]) radios[0].focus();
  });
  confirm.addEventListener("click", async () => {
    if (!chosen) return;
    if (reasonNeeded(c, chosen) && !reason.value.trim()) { reason.focus(); reason.setAttribute("aria-invalid", "true"); return; }
    if (!needPerson()) return;
    await o.decide(chosen, reason.value.trim(), confirm);
  });
  return h("div", { class: "decide decide2" }, h("p", { class: "dc-h" }, technical() ? "Verdict" : "Your choice"), group, why);
}

// "Add a comment": secondary, separate from the decision, and says it decides nothing.
export function commentRow(onclick, count) {
  const b = h("button", { type: "button", class: "btn tiny quiet comment-btn", "data-control": "comment" },
    icon("comment"), h("span", null, count ? "Comments (" + count + ")" : "Add a comment"));
  b.addEventListener("click", onclick);
  return h("div", { class: "card-foot" }, b, h("span", { class: "muted small" }, "Comments are saved but do not count as a decision."));
}
