/* Settings > Folders the cockpit may read (FR-RPJ1, docs/guides/inputs.md): the user's home, the operator's
   RIHMASTO_SOURCE_ROOTS and the folders allowed here. IT allows one under enforced access; a single operator
   allows one after saying yes. Each is signed and recorded in the factory's ledger, and works at once, without
   a restart. System folders and folders of keys are never allowed. */

import { S, h, fill, icon, chip, api, say, card, button, signed, needPerson, AuthError } from "./core.js";

export function foldersCard() {
  const list = h("ul", { class: "plain fold-list", "aria-live": "polite" });
  const input = h("input", { id: "fold-new", maxlength: "2000", autocomplete: "off", spellcheck: "false", "data-control": "allow_folder",
    placeholder: "C:\\dev, /srv/projects", "aria-label": "A folder to allow" });
  const confirm = h("input", { type: "checkbox", id: "fold-yes" });
  const add = button("Allow the folder", { icon: "folder", kind: "small primary", key: "fold-add", "data-control": "allow_folder_add" });
  const who = h("p", { class: "muted small" });
  const form = h("form", { class: "fold-form", novalidate: true, "aria-label": "Allow a folder" },
    h("div", { class: "field" }, h("label", { for: "fold-new" }, "Folder"), input),
    h("label", { class: "np-check", for: "fold-yes" }, confirm, h("span", null, "Yes: the cockpit may read every folder under it")),
    h("div", { class: "btns" }, add), who);
  let roots = null;

  function draw() {
    fill(list, (roots.roots || []).map((r) => h("li", { class: "fold-row" }, icon("folder"), h("span", { class: "mono fold-path" }, r.path),
      chip("neutral", null, r.from + (r.by ? " by " + r.by : "")),
      r.from === "allowed in Settings" ? button("Take back", { kind: "small", aria: "Take back " + r.path, "data-control": "allow_folder_remove",
        onclick: (e) => change("/api/source/roots/remove", r.path, e.currentTarget) }) : null)));
    fill(who, roots.enforced ? (S.persona === "it" ? "Access is enforced: you, as IT, allow a folder." : "Access is enforced: IT allows a folder. Ask IT to allow one.")
      : "A single operator: you allow a folder after saying yes. System folders and folders of keys are never allowed.");
    add.disabled = !!roots.enforced && S.persona !== "it";
  }

  async function change(route, folder, control) {
    if (!needPerson()) return;
    control.disabled = true;
    try {
      roots = await api("POST", route, Object.assign({ folder, confirm: confirm.checked }, signed()));
      say((route.endsWith("remove") ? folder + " is taken back." : folder + " is allowed: the cockpit may read the folders under it.") + " Recorded in the factory's ledger.", "good");
      input.value = "";
      confirm.checked = false;
      draw();
    } catch (e) { if (!(e instanceof AuthError)) say(e.message, "critical"); } finally { control.disabled = false; }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!input.value.trim()) { say("Name the folder to allow.", "warning"); input.focus(); return; }
    if (!roots.enforced && !confirm.checked) { say("Say yes first: the cockpit may then read every folder under it.", "warning"); confirm.focus(); return; }
    change("/api/source/roots", input.value.trim(), add);
  });
  add.type = "submit";
  api("GET", "/api/source/roots").then((got) => { roots = got; draw(); })
    .catch((e) => { if (!(e instanceof AuthError)) fill(list, h("li", { class: "muted" }, "The folders could not be read: " + e.message)); });
  return card({ title: "Folders the cockpit may read", icon: "folder", id: "set-folders", cls: "fold-card",
    info: "New project scans a folder only under these: your home, the operator's RIHMASTO_SOURCE_ROOTS, and the folders allowed here. A system folder or a folder of keys is never read." },
  list, form);
}
