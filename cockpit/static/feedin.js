/* What a scanned folder is, said in the New project dialog with its choices (FR-RPJ1, docs/brownfield.md):
   a refusal with what to do about it, a long scan's progress, a project adopted already, uncommitted work beside
   the last commit, a workspace of several repositories and its copies, what a confidential adoption means and its
   one-click fix, a folder of documents only, and how the project is used today. scan.js renders the map. */

import { h, fill, icon, chip, api, say, segmented, signed, needPerson, enc, AuthError } from "./core.js";

const n = (x) => Number(x || 0).toLocaleString("en");
const plural = (k, one, many) => n(k) + " " + (k === 1 ? one : many || one + "s");
export const USAGE = [["explore", "An experiment"], ["demo", "A prototype"], ["pilot", "In use by a few"], ["production", "In production"]];

export function progressLine(p) {
  const q = p || {};
  return "Scanning… " + plural(q.files || 0, "file") + " looked at" + (q.read ? ", " + n(q.read) + " opened" : "")
    + " · " + Number(q.elapsed_s || 0).toFixed(1) + " s" + (q.folder ? " · in " + q.folder : "");
}

function note(tone, ic, title, ...body) {
  return h("div", { class: "proposal " + tone + " feed-note", role: tone === "warn" ? "alert" : "status" }, icon(ic),
    h("div", null, h("b", null, title), ...body));
}

// A refused or failed scan, with what the person can do: allow the folder (a single operator, after saying
// yes), ask IT to (under enforced access), or scan again.
export function refusalPanel(text, offer, on) {
  const acts = h("div", { class: "btns feed-acts" });
  const again = h("button", { type: "button", class: "btn small", "data-control": "scan_again", onclick: () => on.retry().catch(() => null) },
    icon("refresh"), h("span", { class: "lbl" }, "Scan again"));
  if (offer && offer.who === "you") {
    const allow = h("button", { type: "button", class: "btn small primary", "data-control": "allow_root" }, icon("folder"), h("span", { class: "lbl" }, offer.say));
    allow.addEventListener("click", () => {
      const yes = h("button", { type: "button", class: "btn small primary", "data-control": "allow_root_yes" }, icon("check"), h("span", { class: "lbl" }, "Yes, allow " + offer.root));
      const no = h("button", { type: "button", class: "btn small", onclick: () => fill(acts, allow, again) }, h("span", { class: "lbl" }, "Not now"));
      yes.addEventListener("click", async () => {
        if (!needPerson()) return;
        yes.disabled = true;
        try {
          await api("POST", "/api/source/roots", Object.assign({ folder: offer.root, confirm: true }, signed()));
          say(offer.root + " is allowed: the cockpit may read the folders under it. Recorded in the factory's ledger.", "good");
          await on.retry();
        } catch (e) { if (!(e instanceof AuthError)) say(e.message, "critical"); yes.disabled = false; }
      });
      fill(acts, h("p", { class: "small" }, "The cockpit may then read every folder under " + offer.root + " (never a system folder or one of keys). Allow it?"), yes, no);
      yes.focus();
    });
    fill(acts, allow, again);
  } else if (offer && offer.who === "it") {
    fill(acts, h("p", { class: "small" }, offer.say + ": IT allows a folder in Settings > Folders the cockpit may read."), again);
  } else fill(acts, again);
  return note("warn", "alert", "The folder was not scanned", h("p", { class: "small scan-error" }, text), acts);
}

function already(out, st, on) {
  const seen = out.adopted_as || [];
  if (!seen.length) return null;
  const first = seen[0];
  if (st.again) return note("info", "info", "Adopting it again as a new project", h("p", { class: "small" }, "It is already adopted as " + first.title + "; this makes a second project."));
  return h("div", { class: "proposal warn feed-note feed-seen", role: "alert" }, icon("alert"), h("div", null,
    h("b", null, "Already adopted as " + first.title),
    h("p", { class: "small" }, "The same " + (first.by === "origin" ? "repository (the same origin)" : "folder") + " was adopted to " + (first.intent || "improve") + " it."
      + (seen.length > 1 ? " " + plural(seen.length - 1, "more project") + " too." : "")),
    h("div", { class: "btns feed-acts" },
      h("a", { href: "#/p/" + enc(first.project) + "/overview", class: "btn small primary", "data-control": "open_adopted" }, icon("arrow-right"), h("span", { class: "lbl" }, "Open " + first.title)),
      h("button", { type: "button", class: "btn small", "data-control": "adopt_again", onclick: () => { st.again = true; on.onChange(); } },
        icon("plus"), h("span", { class: "lbl" }, "Adopt it again as a new project")))));
}

function uncommitted(out, st, on) {
  const c = out.changes || {};
  if (!out.git || !(c.uncommitted || c.untracked)) return null;
  const words = plural(c.uncommitted || 0, "uncommitted change") + (c.untracked ? " (and " + plural(c.untracked, "untracked file") + ")" : "");
  const take = segmented("np-take", [["commit", "Adopt the last commit"], ["working_copy", "Adopt the working copy as it is now"]], st.take,
    (v) => { st.take = v; on.rescan().catch((e) => { if (!(e instanceof AuthError)) say(e.message, "critical"); }); },
    { label: "What to adopt" });
  const takeBox = h("div", { "data-control": "adopt_take" }, take);
  return note("warn", "alert", words + " " + ((c.uncommitted || 0) + (c.untracked || 0) === 1 ? "is" : "are") + " not in the last commit",
    h("p", { class: "small" }, st.take === "commit" ? "They will not be included: the last commit is adopted, and the map above shows exactly that."
      : "The working copy as it is now is adopted as a snapshot baseline, uncommitted work included; your folder is never changed."), takeBox);
}

function workspace(out, st, on) {
  const ws = out.workspace;
  if (!ws || !ws.several) return null;
  if (!st.reposSeeded) { ws.repositories.filter((r) => !r.copy).forEach((r) => st.repos.add(r.path)); st.reposSeeded = true; }
  const items = ws.repositories.map((r) => {
    const box = h("input", { type: "checkbox", "data-repo": r.path, "aria-label": "Adopt " + r.path + " as its own project" });
    box.checked = st.repos.has(r.path);
    box.addEventListener("change", () => { if (box.checked) st.repos.add(r.path); else st.repos.delete(r.path); on.onChange(); });
    return h("li", { class: "scan-row" }, h("label", { class: "scan-label" }, box, h("span", { class: "scan-text" }, h("span", { class: "scan-path" }, r.path),
      h("small", { class: "scan-why" }, plural(r.commits, "commit") + (r.uncommitted || r.untracked ? ", " + n(r.uncommitted) + " uncommitted, " + n(r.untracked) + " untracked" : ", nothing uncommitted")),
      r.copy ? chip("neutral", "copy", r.copy_of ? "a copy of " + r.copy_of : "named as a copy") : null)));
  });
  const how = segmented("np-ws", [["one", "Adopt the folder as one"], ["each", "Adopt each as its own project"]], st.each ? "each" : "one",
    (v) => { st.each = v === "each"; on.onChange(); }, { label: "How to adopt the workspace" });
  const howBox = h("div", { "data-control": "adopt_workspace" }, how);
  return note("info", "layers", "A workspace of " + plural(ws.repositories.length, "git repository", "git repositories"),
    h("p", { class: "small" }, "Choose which to adopt, each as its own project, or adopt the whole folder as one (a snapshot)."
      + (ws.copies.length ? " Copies beside them (" + ws.copies.join(", ") + ") are read once: a file the same as another's is listed as its copy." : "")),
    howBox, st.each ? h("ul", { class: "scan-list feed-repos", role: "list" }, items) : null);
}

function confidential(out, on) {
  const c = out.confidential;
  if (!c) return null;
  const parts = [h("p", { class: "small" }, c.text)];
  if (c.offer) {
    const use = h("button", { type: "button", class: "btn small primary", "data-control": "use_local_model" }, icon("cpu"), h("span", { class: "lbl" }, "Use my local model for these roles"));
    use.addEventListener("click", async () => {
      if (!needPerson()) return;
      use.disabled = true;
      try {
        const got = await api("POST", "/api/models/use-local", signed());
        say(got.used.roles.join(", ") + " now use " + got.used.model + " on " + got.used.endpoint + " (" + got.used.host + "). Signed and recorded in Models setup.", "good");
        await on.rescan();
      } catch (e) { if (!(e instanceof AuthError)) say(e.message, "critical"); use.disabled = false; }
    });
    parts.push(h("p", { class: "small muted" }, c.fix + "."), h("div", { class: "btns feed-acts" }, use));
  } else parts.push(h("p", { class: "small muted" }, c.fix + ": ", h("a", { href: "#/models" }, "Models setup"), "."));
  return note("info", "shield", "Confidential: adopting calls no model", ...parts);
}

function documentsOnly(out, st, on) {
  if (out.code) return null;
  const build = on.onNoCode ? h("button", { type: "button", class: "btn small", "data-control": "scan_as_material", onclick: () => on.onNoCode() },
    icon("plus"), h("span", { class: "lbl" }, "Build something from these documents")) : null;
  const track = h("button", { type: "button", class: "btn small" + (st.track ? " primary" : ""), "data-control": "scan_track", "aria-pressed": String(!!st.track),
    onclick: () => { st.track = true; on.onChange(); } }, icon("eye"), h("span", { class: "lbl" }, "Track and evaluate this work"));
  return h("div", { class: "proposal warn scan-nocode feed-note", role: "alert" }, icon("alert"), h("div", null,
    h("b", null, "This folder holds documents only."),
    h("p", { class: "small" }, st.track ? "Tracked and evaluated: a project in a monitoring state whose material is these documents (an experiment, a report). It asks no build questions."
      : "What should Rihmasto do with them? Build something from them (a new project whose material they are), or track and evaluate the work they record (an experiment or a report)."),
    h("div", { class: "btns feed-acts" }, build, track)));
}

// The dialog's Maturity (How it runs) follows the answer, so the two never disagree.
function syncMaturity(v) {
  const b = document.querySelector('form.np-form [data-key="np-maturity:' + v + '"]');
  if (b && b.getAttribute("aria-checked") !== "true") b.click();
}

function usage(out, st) {
  if (!out.usage) return null;
  const now = st.usage || out.usage.maturity;
  setTimeout(() => syncMaturity(now), 0);
  const seg = segmented("np-usage", USAGE, now, (v) => { st.usage = v; syncMaturity(v); }, { label: "How is it used today" });
  return h("div", { class: "field feed-usage", "data-control": "adopt_usage" }, h("span", { class: "label-h" }, "How is it used today?"), seg,
    h("small", { class: "muted" }, "Inferred from its files: " + out.usage.why + ". Change it if it is used differently: it sets the project's maturity."));
}

// The submit button's words for what the person chose.
export function adoptLabel(res, ch) {
  if (res && ch.track) return "Track this work";
  if (res && ch.each) return "Adopt " + plural(ch.repos.size, "project");
  if (res && ch.again) return "Adopt it again";
  return "Adopt the project";
}

// What the adopt request carries from the scan step: the last commit or the working copy, adopting again,
// documents to track (monitored), and the maturity a person confirmed ("How is it used today").
export function adoptChoice(res, ch, posture) {
  const out = {};
  if (ch.take === "working_copy") out.take = "working_copy";
  if (ch.again) out.again = true;
  if (ch.track) Object.assign(out, { documents: true, intent: "monitor" });
  if (!posture && res && (ch.usage || res.usage)) out.maturity = ch.usage || res.usage.maturity;
  return out;
}

// A workspace adopted as several projects: one request per chosen repository, its title naming it.
export function adoptEach(res, ch, data) {
  if (!res || !ch.each || !res.workspace) return null;
  return res.workspace.repositories.filter((r) => ch.repos.has(r.path)).map((r) => Object.assign({}, data,
    { source: r.folder, title: data.title + " · " + r.path, exclude: [], take: undefined }));
}

// The notices for a scanned folder, in the order a person decides: adopted already, what is adopted, the
// workspace, documents only, confidential, how it is used.
export function adoptNotices(out, st, on) {
  if (!on.adopting) {          // a new project: its intake asks the analyst role, which a confidential project needs local
    return [on.confidential && out.local_only && out.local_only.new
      ? note("warn", "shield", "Confidential: a role's model is hosted.", h("p", { class: "small" }, out.local_only.new)) : null];
  }
  return [already(out, st, on), uncommitted(out, st, on), workspace(out, st, on), documentsOnly(out, st, on),
    on.confidential ? confidential(out, on) : null, out.code || st.track ? usage(out, st) : null];
}
