/* Stage names and the gate's stage, on a project's Enforcement view (kernel/enforcement_places.py, FR-ENF2).
   A pipeline's environment is placed in development, testing or production by the whole words of its name; a name
   Rihmasto does not know counts as production, the strictest, until a person places it here. Which stage a change
   judged by the gate enters is set here too (development unless a person says otherwise). Every save is signed and
   recorded; placing a name, or the gate's changes, in a less strict stage needs a reason. Also: how the main line's
   protection reads, from classic branch protection and repository rulesets together. */

import { h, chip, api, enc, card, button, say, plural, signed, needPerson, act, mayAct } from "./core.js";
import { pick, datum, emptyState } from "./words.js";

const ENVS = ["dev", "test", "prod"];
const ENV_WORD = { dev: "Development", test: "Testing", prod: "Production" };
const scopeWord = (s) => pick({ project: "This project", platform: "All projects", default: "Rihmasto's default" }[s],
  { project: "Project", platform: "Platform", default: "Default" }[s]) || s;
const ROW = { display: "flex", flexWrap: "wrap", alignItems: "center", gap: "6px 8px", margin: "6px 0" };
const GROW = { flex: "1 1 150px", minWidth: "0", maxWidth: "100%", width: "auto" };

function stageSelect(id, value, label, inherit) {
  const opts = (inherit ? [["inherit", inherit]] : []).concat(ENVS.map((e) => [e, ENV_WORD[e]]));
  return h("select", { id, "data-key": id, "aria-label": label, style: GROW }, opts.map(([v, t]) => h("option", { value: v, selected: v === value || null }, t)));
}

// The main line's protection, from both places GitHub keeps it (FR-ENF2).
export function protectionLine(prot) {
  const parts = [];
  if (prot.pull_request) parts.push(pick("changes come through a pull request", "pull request required"));
  if (prot.required_reviews) parts.push(plural(prot.required_reviews, "required review"));
  else if (prot.pull_request) parts.push(pick("no approving review needed", "0 required reviews"));
  if ((prot.required_checks || []).length) parts.push(pick("checks: ", "required checks: ") + prot.required_checks.join(", "));
  const from = (prot.sources || []).length ? " (" + prot.sources.join(", ") + ")" : "";
  return h("p", { class: "small", "data-key": "enf-protection" }, pick("Main line protection: ", "Branch protection: "),
    prot.protected ? datum(parts.join(", ") + from) : (prot.readable ? "none" : datum(prot.why || "not readable")));
}

// Environments whose names Rihmasto does not know: held as production until a person places them.
export function placedNote(envs) {
  const unknown = (envs || []).filter((e) => e.placed === "unknown");
  if (!unknown.length) return null;
  return h("p", { class: "note warning small", "data-key": "enf-unknown" }, datum(unknown.map((e) => e.placed_says).join(" ")));
}

function gateRow(pid, d, again, may, reason) {
  const g = d.gate_env || { env: "dev", scope: "default" };
  const sel = stageSelect("enf-gate-env", g.scope === "project" ? g.env : "inherit", pick("Where a checked change goes", "Gate stage"),
    pick("As for all projects", "Platform") + (g.scope === "project" ? "" : ": " + ENV_WORD[g.env]));
  const save = button(pick("Save", "Save the gate's stage"), { icon: "check", kind: "small quiet", key: "enf-gate-save", "data-control": "enforcement_places", disabled: !may || null,
    onclick: () => act(save.parentNode, async () => {
      if (!needPerson()) return;
      const res = await api("PUT", "/api/projects/" + enc(pid) + "/enforcement", Object.assign({ gate_env: sel.value, reason: reason.value.trim() }, signed()));
      say(plural(res.changes.length, "setting") + " changed, signed and recorded.", "good");
      await again();
    }) });
  return h("div", { style: ROW }, h("label", { for: sel.id }, pick("A change Rihmasto checks goes to", "The gate's changes enter")), sel,
    chip(g.scope === "project" ? "accent" : "neutral", "layers", scopeWord(g.scope), { "data-scope": g.scope }), save);
}

function namesList(d) {
  const rows = d.names || [];
  if (!rows.length) {
    return emptyState("enforcement_names", null, { icon: "layers", what: pick("No stage name placed by a person yet.", "No environment name placed."),
      how: pick("Names like staging, prod-eu or qa2 are placed by their words. Place any other name here, such as eu-west, and it counts in that stage from then on.",
        "Names are placed by whole words (staging: test, prod-eu: prod); an unknown name counts as prod until placed here.") });
  }
  return h("ul", { class: "plain enf-names" }, rows.map((r) => h("li", { "data-name": r.name }, datum(r.name), " → ", ENV_WORD[r.env], " ",
    chip(r.scope === "project" ? "accent" : "neutral", "layers", scopeWord(r.scope), { "data-scope": r.scope }))));
}

export function placesCard(pid, d, again) {
  const may = mayAct(d.setters);
  const reason = h("input", { id: "enf-places-reason", "data-key": "enf-places-reason", autocomplete: "off", maxlength: "300", style: GROW,
    placeholder: pick("Why (needed when a stage gets less strict)", "Reason (required when loosening)") });
  const name = h("input", { id: "enf-name", "data-key": "enf-name", autocomplete: "off", spellcheck: "false", maxlength: "60", style: GROW, placeholder: "eu-west" });
  const stage = stageSelect("enf-name-env", "prod", pick("Counts as", "Stage"), pick("Remove the placing", "Inherit"));
  const place = button(pick("Place it", "Save the name"), { icon: "check", kind: "small", key: "enf-name-save", "data-control": "enforcement_places", disabled: !may || null,
    onclick: () => act(place.parentNode, async () => {
      if (!needPerson()) return;
      if (!name.value.trim()) { say("Write the stage's name first, as your pipeline calls it.", "warning"); return; }
      const res = await api("PUT", "/api/projects/" + enc(pid) + "/enforcement", Object.assign({ names: { [name.value.trim()]: stage.value }, reason: reason.value.trim() }, signed()));
      say(plural(res.changes.length, "setting") + " changed, signed and recorded.", "good");
      await again();
    }) });
  const body = h("div", { class: "enf-places" },
    h("p", { class: "small" }, pick("A stage whose name Rihmasto does not know counts as production, the strictest, until you place it here.",
      "Unknown environment names count as prod (fail closed) until placed.")),
    gateRow(pid, d, again, may, reason), namesList(d),
    h("div", { style: ROW }, h("label", { for: name.id }, pick("Name", "Environment name")), name,
      h("label", { for: stage.id }, pick("counts as", "stage")), stage, place),
    h("div", { style: ROW }, h("label", { for: reason.id }, pick("Why", "Reason")), reason));
  return card({ title: pick("Stage names", "Environment names and the gate"), icon: "layers", id: "enf-places",
    info: "Where each of your pipeline's stages counts, and which stage a change checked by Rihmasto's gate goes to." }, body);
}
