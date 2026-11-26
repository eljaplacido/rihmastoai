/* Who acted, and Harness and enforcement (FR-NVL1).

   - A project's "Who acted" view: every run (each build attempt and each model call) with which Rihma agent and
     role, which harness and model, on this machine or hosted, and whether Gnomon's structure (the contract's
     criteria, the gate) applied; above it, the project's Harness and enforcement.
   - Harness and enforcement (here and in Settings for the platform): per role, the harness acting now, what Gnomon
     enforces on it, and what changing to each other harness does. Gnomon's enforcement is on by default; an opt-out
     is explicit, with its reason, signed and recorded, and never skips the gate. */

import { h, fill, icon, chip, button, api, enc, card, act, say, needPerson, signed, mayAct, cap } from "./core.js";
import { pick, datum, emptyState } from "./words.js";

const ROLE_WORDS = { builder: ["Builds the work", "builder"], analyst: ["Reads the project and asks", "analyst"],
  holdout_author: ["Writes the hidden tests", "holdout author"], verifier: ["Reviews each change", "verifier"],
  assistant: ["Answers in Ask Rihma", "assistant"] };
const TITLE = () => pick("AI tools and Rihmasto's rules", "Harness and enforcement");
function roleWord(r) { const w = ROLE_WORDS[r]; return w ? pick(w[0], w[1]) : r; }

function roleRow(r) {
  return h("tr", null, h("th", { scope: "row" }, roleWord(r.role)),
    h("td", null, h("b", null, r.label), r.model ? h("small", { class: "muted" }, " · ", datum(r.model)) : null),
    h("td", null, chip(r.in_run ? "good" : "info", r.in_run ? "shield" : "eye", r.in_run ? pick("Checked while it works", "in-run") : pick("Checked after it works", "after-run")),
      " ", datum(r.enforced)),
    h("td", null, h("details", null, h("summary", null, "If you change it"),
      h("ul", { class: "nvl-list small" }, r.others.map((o) => h("li", null, h("b", null, o.label + ": "), datum(o.then)))))));
}

function toggle(scope, eff, setters, redraw) {
  const on = eff.state.on;
  const may = mayAct(setters);
  const reason = h("input", { id: "enf-reason-" + scope, maxlength: "300", "data-key": "enf:reason:" + scope,
    placeholder: on ? "Why you opt out (recorded with it)" : "Why you turn it back on (optional)", "aria-label": "Reason" });
  const path = scope === "platform" ? "/api/harness-enforcement" : "/api/projects/" + enc(scope) + "/harness-enforcement";
  const go = button(on ? "Opt out of Gnomon's enforcement" : "Turn Gnomon's enforcement back on", { kind: on ? "small" : "small primary",
    icon: on ? "x-circle" : "shield", key: "enf:set:" + scope, "data-control": "enforcement_set", disabled: !may || null,
    onclick: () => act(go.parentNode, async () => {
      if (!needPerson()) return;
      const out = await api("PUT", path, Object.assign({ on: !on, reason: reason.value.trim() }, signed()));
      say("Gnomon's enforcement is " + out.state.said + ". " + cap(out.state.gate) + ".", "good");
      redraw(out);
    }) });
  return h("div", { class: "nvl-enf" }, h("div", { class: "field" }, reason), h("div", { class: "btns" }, go),
    may ? null : h("p", { class: "muted small" }, "A " + setters.join(" or ").replace(/_/g, " ") + " sets this."));
}

export function enforcementSection(scope, eff, setters, redraw) {
  const st = eff.state;
  return h("div", { class: "nvl-harness", "data-control": "harness_effects" },
    h("p", null, chip(st.on ? "good" : "warning", st.on ? "shield" : "alert", st.on ? "Gnomon enforces" : "Opted out"), " ",
      datum(st.said + "."), " ", h("small", { class: "muted" }, datum(st.gate + "."))),
    h("p", { class: "small" }, datum(eff.summary)),
    h("div", { class: "tbl" }, h("table", { class: "nvl-table" },
      h("thead", null, h("tr", null, h("th", { scope: "col" }, "Role"), h("th", { scope: "col" }, pick("AI tool now", "Harness now")),
        h("th", { scope: "col" }, "What Gnomon enforces"), h("th", { scope: "col" }, pick("If you change the tool", "Changing harness")))),
      h("tbody", null, eff.roles.map(roleRow)))),
    toggle(scope, eff, setters, redraw));
}

// A run's chip says the enforcement it ran under, as its record carries it, never today's (FR-NVL2).
function runChip(r) {
  if (r.applied) return chip("good", "shield", pick("Gnomon's rules applied", "Gnomon in-run"));
  if (r.opted_out) return chip("warning", "alert", pick("Ran while Rihmasto's rules were switched off", "enforcement opted out then"));
  return chip("info", "eye", pick("Checked another way", "not in Gnomon's lane"));
}

function runRow(r) {
  return h("li", { class: "nvl-run", "data-id": r.id }, h("b", null, datum(r.what)),
    h("p", { class: "small" }, runChip(r),
      " ", datum(r.agent + " (" + r.role + ") · " + r.harness + " · model " + r.model + " · " + r.where)),
    h("p", { class: "small muted" }, datum(r.gnomon)));
}

function whoBody(pid, d, holder) {
  const redraw = (eff) => { d.harness = eff; fill(holder, whoBody(pid, d, holder)); };
  return [
    card({ title: TITLE(), icon: "shield", id: "nvl-enf-p" },
      enforcementSection(pid, d.harness, (d.harness.project_setters || ["it", "compliance", "developer", "product_owner"]), redraw)),
    card({ title: "Every run, and who acted", icon: "bot", id: "nvl-runs" },
      d.runs.length ? h("ul", { class: "nvl-list", "data-control": "who_acted" }, d.runs.slice().reverse().map(runRow))
        : emptyState("who", null, { icon: "bot", what: "No run is recorded on this project yet.",
          how: "Each build attempt and each model call appears here once the work starts, with the agent, harness and model that acted." })),
  ];
}

export function render(p) {
  const pid = p.meta.id;
  const holder = h("div", { class: "nvl-view" }, h("p", { class: "muted", "aria-busy": "true" }, "Reading who acted…"));
  const root = h("div", null, h("div", { class: "q" }, h("h2", { class: "view-h", tabindex: "-1" }, "Who acted"),
    h("p", null, pick("Which AI and which tool did each piece of work, and whether Rihmasto's rules applied.",
      "Per run: Rihma agent and role, harness, model, local or hosted, and whether Gnomon's contract, criteria and gate applied."))), holder);
  api("GET", "/api/projects/" + enc(pid) + "/who").then((d) => fill(holder, whoBody(pid, d, holder)))
    .catch((e) => fill(holder, h("div", { class: "note critical" }, icon("alert"), h("span", null, "Who acted could not be read: " + e.message))));
  return root;
}

// Settings: the platform's harness and enforcement.
export function enforcementSettingsCard() {
  const holder = h("div", { class: "nvl-settings" });
  const draw = (eff) => fill(holder, card({ title: TITLE(), icon: "shield", id: "nvl-enf",
    info: pick("Which AI tool and model do each job, and whether Rihmasto's rules and quality checks apply to them. On by default; turning it off is recorded with your reason and never skips the quality check.",
      "Which harness and model act for each role, and whether Gnomon's structure (the contract, its criteria and the gate) applies to them. On by default; an opt-out is recorded with its reason and never skips the gate.") },
  enforcementSection("platform", eff, eff.setters || ["it", "compliance"], (out) => draw(Object.assign(out, { setters: eff.setters })))));
  api("GET", "/api/harness-enforcement").then(draw)
    .catch((e) => fill(holder, h("div", { class: "note critical" }, icon("alert"), h("span", null, "Harness and enforcement could not be read: " + e.message))));
  return holder;
}
