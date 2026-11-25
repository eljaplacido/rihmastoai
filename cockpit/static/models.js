/* Models setup (kernel/models_setup.py): which model answers for each of Rihmasto's roles, with a Test that
   sends a tiny prompt, and a form to point a role at an OpenAI-compatible endpoint. A key is given as the
   name of an environment variable or stored outside the repository; it is never shown again. Home shows a
   "Set up a model" card while no model Rihma talks with is reachable. */

import { S, $, h, fill, icon, chip, api, act, say, signed, needPerson, enc, button, card, pageHead, skeleton, openModal, closeModal, segmented } from "./core.js";
import { harnessCard, harnessChip, harnessHomeLine } from "./harness.js";
import { pick, tw } from "./words.js";

const READY = {
  ready: ["good", "check-circle", "Answers"], configured: ["info", "key", "Key set"], no_key: ["warning", "alert", "No key"],
  unreachable: ["critical", "x-circle", "Not reachable"], unknown: ["nm", "dashed", "Not checked"],
  maybe_key: ["info", "key", "Gnomon may have a key"],
};
const HOME = { at: 0, view: null };
const HOME_MS = 60000;

// A key Gnomon holds (`gnomon key set`) counts as set: Rihmasto sees only its name, never the value.
function keyChip(k) {
  if (!k.name) return chip("neutral", "key", "No key needed");
  if (k.kind === "gnomon_maybe") return chip("info", "key", "Gnomon may have its own key for this host", { tip: "Gnomon's credential store exists; Rihmasto never opens it. `gnomon key list` names the keys it holds." });
  const word = k.kind === "stored" ? "stored key " + k.name : k.kind === "gnomon" ? "key set by Gnomon (" + k.name + ")"
    : k.set ? k.name + " is set" : k.name + " is not set";
  return chip(k.set ? "good" : "warning", "key", word, { tip: "The key itself is never shown." });
}

function roleRow(r) {
  const st = READY[r.readiness.state] || READY.unknown;
  const result = h("p", { class: "mdl-result muted small", id: "mdl-res-" + r.role, "aria-live": "polite" });
  const test = button("Test", { icon: "play", kind: "small", "data-control": "models_test", key: "mdl-test:" + r.role, aria: "Test the " + r.label.toLowerCase() + "'s model" });
  test.addEventListener("click", () => {
    if (!needPerson()) return;
    fill(result, icon("clock"), " Sending a tiny prompt…");
    act(test.parentNode, async () => {
      const out = (await api("POST", "/api/models/" + enc(r.role) + "/test", signed())).test;
      fill(result, out.ok ? chip("good", "check-circle", "Answered in " + out.latency_ms + " ms") : chip("critical", "x-circle", "Failed"),
        " ", out.ok ? (out.reply ? "It said: " + out.reply : "") : out.error);
    });
  });
  const change = button("Change", { icon: "edit", kind: "small", "data-control": "models_set", key: "mdl-set:" + r.role, aria: "Change the " + r.label.toLowerCase() + "'s model", onclick: () => openSet(r) });
  const back = r.set_here ? button("Back to shipped", { icon: "undo", kind: "small", "data-control": "models_remove", key: "mdl-remove:" + r.role, aria: "Take the " + r.label.toLowerCase() + " back to the shipped routing" }) : null;
  if (back) {
    back.addEventListener("click", () => {
      if (!needPerson()) return;
      act(back.parentNode, async () => {
        await api("POST", "/api/models/" + enc(r.role) + "/remove", signed());
        say(r.label + " uses the shipped routing again.", "good");
        HOME.at = 0;
        await renderModels(S.seq);
      });
    });
  }
  return h("li", { class: "mdl-row", "data-key": "model:" + r.role },
    h("div", { class: "mdl-main" },
      h("b", { "data-ud": "" }, r.role === "holdout_author" ? pick("Hidden-test writer", r.label) : r.label),
      h("span", { class: "muted small", "data-ud": "" }, " " + r.purpose),   // the role as the routing names it
      h("div", { class: "sig-m" }, h("span", { class: "mono" }, r.model), h("span", null, "family " + r.family),
        h("span", { class: "mono" }, r.harness ? r.harness.label + " on this machine" : r.host || "(no host)"), r.fallback ? h("span", null, "fallback " + r.fallback.model + " at " + (r.fallback.host || "?")) : null),
      h("div", { class: "mdl-chips" }, chip(r.local ? "info" : "accent", r.local ? "server" : "globe", r.local ? "Local" : "Hosted"),
        harnessChip(r), r.harness ? null : keyChip(r.key), chip(st[0], st[1], st[2], { tip: r.readiness.why }), r.set_here ? chip("accent", "edit", "Set on this machine") : chip("neutral", "package", "Default", { tip: "The routing Rihmasto ships with" })),
      result),
    h("div", { class: "mdl-tools" }, test, change, back));
}

function keyPart(r) {
  const env = h("input", { id: "mdl-key-env", maxlength: "64", value: r.key.kind !== "stored" && r.key.name ? r.key.name : "", autocomplete: "off",
    spellcheck: "false", placeholder: "MY_PROVIDER_API_KEY", "aria-label": "The environment variable's name" });
  const key = h("input", { id: "mdl-key", type: "password", maxlength: "4000", autocomplete: "off", "aria-label": "The key, stored outside the repository" });
  const envF = h("div", { class: "field" }, h("label", { for: "mdl-key-env" }, "The NAME of the environment variable that holds the key"), env);
  const keyF = h("div", { class: "field" }, h("label", { for: "mdl-key" }, "The key: stored in " + (HOME.view ? HOME.view.secrets_file : "a file outside the repository") + ", never shown again"), key);
  let how = r.key.kind === "stored" ? "store" : r.key.name ? "env" : "none";
  const show = () => { envF.hidden = how !== "env"; keyF.hidden = how !== "store"; };
  const seg = segmented("mdl-key-how", [["none", "No key"], ["env", "An environment variable"], ["store", "Store a key"]], how,
    (v) => { how = v; show(); }, { label: "How the key is found" });
  show();
  return { el: h("div", null, h("div", { class: "field" }, h("label", null, "The API key"), seg), envF, keyF),
    value: () => (how === "env" ? { key_env: env.value.trim() } : how === "store" ? { key: key.value } : {}),
    set: (p) => { env.value = p.key_env || ""; how = p.key_env ? "env" : "none"; seg.querySelectorAll(".seg-b").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.key === "mdl-key-how:" + how))); show(); } };
}

function openSet(r) {
  const presets = (HOME.view && HOME.view.presets) || [];
  const preset = h("select", { id: "mdl-preset", "data-control": "models_preset", "aria-label": "Start from a preset" },
    h("option", { value: "" }, "Keep what is there"), presets.map((p) => h("option", { value: p.id }, p.label)));
  const base = h("input", { id: "mdl-base", maxlength: "500", value: r.base_url, autocomplete: "off", spellcheck: "false", "aria-label": "Base URL" });
  const model = h("input", { id: "mdl-model", maxlength: "200", value: r.model, autocomplete: "off", spellcheck: "false", "aria-label": "Model name" });
  const family = h("input", { id: "mdl-family", maxlength: "64", value: "", placeholder: r.family, autocomplete: "off", "aria-label": "Model family (optional)" });
  const keep = h("input", { type: "checkbox", id: "mdl-keep", checked: true });
  const priv = h("input", { type: "checkbox", id: "mdl-private", "data-control": "models_private", checked: !!r.local });
  const key = keyPart(r);
  preset.addEventListener("change", () => {
    const p = presets.find((x) => x.id === preset.value);
    if (!p) return;
    base.value = p.base_url;
    if (p.model) model.value = p.model;
    key.set(p);
  });
  const form = h("form", { class: "np-form", novalidate: true },
    h("p", { class: "note" }, icon("shield"), h("span", null, "Written to ", h("code", null, "kernel/routing.local.json"), " on this machine, never to the shipped ",
      h("code", null, "routing.json"), ". The " + tw("ledger") + " records who set which role to which host; never the key.")),
    h("div", { class: "field" }, h("label", { for: "mdl-preset" }, "Preset"), preset),
    h("div", { class: "field" }, h("label", { for: "mdl-base" }, "Base URL (OpenAI-compatible, for example http://127.0.0.1:8080/v1)"), base),
    h("div", { class: "row2" }, h("div", { class: "field" }, h("label", { for: "mdl-model" }, "Model name"), model),
      h("div", { class: "field" }, h("label", { for: "mdl-family" }, "Model family (optional)"), family)),
    key.el,
    h("div", { class: "field" }, h("label", { class: "chk", for: "mdl-private" }, priv,
      " On my own network (this machine, a tailnet or a VPN): confidential projects may use it"),
      h("small", { class: "muted" }, "An address like 127.0.0.1, 192.168.x.x or 100.x.x.x counts already; tick this for a host reached by name.")),
    r.fallback ? h("div", { class: "field" }, h("label", { class: "chk", for: "mdl-keep" }, keep, " Keep the fallback (" + r.fallback.model + " at " + (r.fallback.host || "?") + ")")) : null,
    h("div", { class: "btns" }, h("button", { type: "submit", class: "btn primary", "data-control": "models_set", "data-key": "mdl-save" }, icon("check"), "Save")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!needPerson()) return;
    act(form, async () => {
      const out = await api("PUT", "/api/models/" + enc(r.role), Object.assign({ base_url: base.value.trim(), model: model.value.trim(),
        family: family.value.trim(), keep_fallback: !r.fallback || keep.checked, private: priv.checked }, key.value(), signed()));
      closeModal();
      say(r.label + " now uses " + out.role.model + " at " + out.role.host + "." + (out.role.note ? " " + out.role.note : ""),
        out.role.note ? "warning" : "good");
      HOME.at = 0;
      await renderModels(S.seq);
    });
  });
  openModal("The " + r.label.toLowerCase() + "'s model", form, { icon: "cpu", wide: true });
}

export async function renderModels(seq) {
  const main = $("#main");
  const done = skeleton(main, "the models");
  let data;
  try { data = await api("GET", "/api/models"); } finally { done(); }
  if (seq !== S.seq) return;
  HOME.view = data;
  HOME.at = Date.now();
  document.title = "Models · Rihmasto.ai";
  fill(main,
    pageHead("Models", "Which model answers for each of Rihmasto's roles. Point a role at any OpenAI-compatible endpoint: a server on this machine or a hosted provider.", { icon: "cpu" }),
    data.gnomon ? null : h("p", { class: "note warning", "data-key": "mdl-no-gnomon" }, icon("alert"), h("span", null, h("b", null, "Gnomon was not found on this machine. "),
      "Every model call goes through it, except a role a coding agent answers (below): install it or set GNOMON_CMD, then start the cockpit again. Test still checks an endpoint directly.")),
    h("p", { class: "note" }, icon("info"), h("span", null, "Changes are saved in ", h("span", { class: "mono" }, data.overlay.path),
      (data.overlay.present ? "" : " (not written yet)") + pick(", on top of the settings Rihmasto ships with. Stored keys are kept in ",
        ", merged over the shipped routing. Stored keys are kept in "), h("span", { class: "mono" }, data.secrets_file),
      pick(", apart from the code.", ", outside the repository."))),
    card({ title: "Roles", icon: "cpu", id: "mdl-roles", info: "The verifier must be another model family than the builder and its fallback; a change that breaks this is refused." },
      h("ul", { class: "emb-list mdl-list" }, data.roles.map(roleRow))),
    card({ title: "Use the coding agent you already have", icon: "terminal", id: "mdl-harness",
      info: "Claude Code, Codex or OpenCode answers the text roles, run headless with no tools; each call is recorded as run by it, not through Gnomon's lane." },
    harnessCard(data, async () => { HOME.at = 0; await renderModels(S.seq); })));
}

// Home's card while no model Rihma talks with (the analyst or the assistant) answers. Read at most once a minute.
export async function modelSetupCard(box) {
  if (!box) return;
  try {
    if (!HOME.view || Date.now() - HOME.at > HOME_MS) { HOME.view = await api("GET", "/api/models"); HOME.at = Date.now(); }
  } catch (e) { return; }
  if (!box.isConnected || HOME.view.ready) { fill(box); return; }
  const why = HOME.view.gnomon ? "No model Rihma talks with answers yet: the analyst and the assistant have no reachable endpoint or no key."
    : "Gnomon was not found on this machine, and every model call but a coding agent's goes through it.";
  fill(box, card({ title: "Set up a model", icon: "cpu", id: "home-setup-card", cls: "setup-card" },
    h("p", null, why, " Point the analyst at a model on this machine or a hosted one, and test it."),
    harnessHomeLine(HOME.view, async () => { HOME.at = 0; HOME.view = null; await modelSetupCard(box); }),
    h("div", { class: "btns" }, h("a", { href: "#/models", class: "btn primary", "data-control": "models_open", "data-key": "home:models" }, icon("cpu"),
      h("span", { class: "lbl" }, "Open Models setup")))));
}
