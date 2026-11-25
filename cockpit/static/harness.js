/* The coding agent you already have (kernel/harness_setup.py, FR-HMD1): Models setup's card that lists Claude Code,
   Codex and OpenCode as found on this machine with their versions, and answers every text role (or those chosen)
   with one; the chip on a role a harness answers; and Home's "No API key? ... found: use it" line. A harness run
   per call is slower than an API endpoint and spends the person's own subscription: both places say so. */

import { h, icon, chip, api, act, say, signed, needPerson, button } from "./core.js";

const ROLE_SETS = [["all", "Every text role"], ["analyst,assistant", "The analyst and the assistant"],
  ["analyst", "The analyst"], ["holdout_author", "The holdout author"], ["verifier", "The verifier"], ["assistant", "The assistant"]];

// The map's control for each harness's Use button (cockpit/ui_map.json).
const CONTROLS = {
  "claude-code": { "data-control": "models_use_claude" },
  codex: { "data-control": "models_use_codex" },
  opencode: { "data-control": "models_use_opencode" },
};

function useButton(x, label, opts) {
  return button(label, Object.assign(opts, CONTROLS[x.id] || {}));
}

async function useHarness(box, harness, body, done) {
  if (!needPerson()) return;
  await act(box, async () => {
    const out = (await api("POST", "/api/models/use", Object.assign({ harness }, body, signed()))).use;
    say(out.label + " " + (out.version || "") + " now answers " + out.roles.map((r) => r.label.toLowerCase()).join(", ") + ". " + out.note, "good");
    await done();
  });
}

// A role answered by a harness: which one, and the honest assurance as its tip.
export function harnessChip(r) {
  if (!r.harness) return null;
  return chip("accent", "terminal", "Answered by " + r.harness.label + (r.harness.version ? " " + r.harness.version : ""),
    { tip: r.harness.assurance + ". " + r.harness.note });
}

// Models setup's card: each harness found here or not, and the button that answers the chosen roles with it.
export function harnessCard(data, done) {
  const list = data.harnesses || [];
  const roles = h("select", { id: "hm-roles", "aria-label": "Which roles the coding agent answers" },
    ROLE_SETS.map(([v, label]) => h("option", { value: v }, label)));
  const model = h("input", { id: "hm-model", maxlength: "200", autocomplete: "off", spellcheck: "false", placeholder: "its own default",
    "aria-label": "The model it uses (optional; OpenCode: provider/model)" });
  const box = h("div", { class: "hm-box" });
  const rows = list.map((x) => {
    const p = x.preset || {};
    const use = useButton(x, p.label || "Use " + x.label, { icon: "terminal", kind: x.found ? "primary small" : "small", disabled: !x.found,
      key: "hm-use:" + x.id, aria: (p.label || "Use " + x.label) + " for the chosen roles" });
    use.addEventListener("click", () => useHarness(box, x.id, { roles: roles.value, model: model.value.trim() }, done));
    return h("li", { class: "hm-row", "data-key": "harness:" + x.id },
      h("div", { class: "mdl-main" }, h("b", null, x.label),
        h("div", { class: "mdl-chips" }, x.found ? chip("good", "check-circle", "Found: " + x.version) : chip("neutral", "x-circle", "Not found", { tip: x.why }),
          chip(x.hosted ? "accent" : "info", x.hosted ? "globe" : "server", x.hosted ? "Hosted model" : "Model you choose"),
          x.family ? h("span", { class: "muted small" }, "family " + x.family) : null)),
      h("div", { class: "mdl-tools" }, use));
  });
  box.append(
    h("p", { class: "note" }, icon("info"), h("span", null, "No API key? Rihmasto can ask the coding agent you already use, run headless with no tools in an empty folder. "
      + (data.harness_note || ""))),
    h("div", { class: "row2" }, h("div", { class: "field" }, h("label", { for: "hm-roles" }, "Roles"), roles),
      h("div", { class: "field" }, h("label", { for: "hm-model" }, "Model (optional)"), model)),
    h("ul", { class: "emb-list mdl-list" }, rows),
    h("p", { class: "muted small" }, "The builder writes code: its harness is chosen in Settings > Runners. A call run by a harness is recorded as run by it, not through Gnomon's lane."));
  return box;
}

// Home's line while no model answers: the harness found here, and one click to use it for every text role.
export function harnessHomeLine(view, done) {
  const found = (view.harnesses || []).filter((x) => x.found);
  if (!found.length) return null;
  const first = found[0];
  const box = h("div", { class: "hm-home", "data-key": "home:harness" });
  const use = useButton(first, (first.preset || {}).label || "Use " + first.label, { icon: "terminal", kind: "primary",
    key: "home:hm-use", aria: "Answer every text role with " + first.label });
  use.addEventListener("click", () => useHarness(box, first.id, { roles: "all" }, done));
  box.append(h("p", null, h("b", null, "No API key? "), found.map((x) => x.label + " " + x.version).join(", ") + " found: use it. ",
    h("span", { class: "muted small" }, view.harness_note || "")), h("div", { class: "btns" }, use));
  return box;
}
