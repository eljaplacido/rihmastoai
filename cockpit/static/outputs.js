/* A project's Outputs view: what each audience receives (kernel/outputs.py, docs/guides/outputs.md).
   A person chooses the targets; each is built from the project's records and its release. Every choice and
   every build is in the ledger with who asked. A built file comes as a one-time download link. project.js
   draws it as one of a project's views and hands in its own helpers (viewHead, run, settle). */

import {
  S, $$, h, icon, chip, api, say, signed, needPerson, enc, orList, cap, plural, short, ago, download, button, card,
  empty, personaLabel, mayAct,
} from "./core.js";

const LINKS = {};   // pid -> { target: { download, file } } from the last build, until a link is used

function may(list) { return mayAct(list || []); }
function guarded(b, allowed, who, noteId) {
  if (allowed) return null;
  b.setAttribute("aria-disabled", "true");
  b.setAttribute("aria-describedby", noteId);
  return h("span", { class: "muted small", id: noteId }, "A " + orList(who) + " persona does this.");
}
async function build(pid, targets) {
  const out = await api("POST", "/api/projects/" + enc(pid) + "/outputs/build", Object.assign({ targets }, signed()));
  LINKS[pid] = LINKS[pid] || {};
  (out.outputs || []).forEach((row) => { if (row.download) LINKS[pid][row.target] = { download: row.download, file: row.file }; });
  return out.outputs || [];
}

function choice(pid, o, ui) {
  const proposedOnly = !o.chosen.length;
  const boxes = o.targets.map((t) => h("label", { class: "check" },
    h("input", { type: "checkbox", name: "out-target", value: t.id, "data-key": "out-pick:" + t.id,
      checked: (proposedOnly ? t.proposed : t.chosen) || null }),
    h("span", null, h("b", { "data-ud": "" }, t.label), " ", h("span", { class: "muted small" }, "for " + t.audience))));
  const reason = h("input", { id: "out-reason", type: "text", maxlength: "500", placeholder: "For the handover to the team", "data-key": "out-reason" });
  const save = button("Save the choice", { icon: "check", kind: "primary small", key: "out-save", "data-control": "choose_outputs" });
  const allowed = may(o.choosers);
  const note = guarded(save, allowed, o.choosers, "out-choose-who");
  save.addEventListener("click", () => {
    if (!allowed) { say(note.textContent, "warning"); return; }
    if (!needPerson()) return;
    const targets = $$('input[name="out-target"]:checked', save.closest("section")).map((x) => x.value);
    ui.run(save, save.parentNode, async () => {
      await api("PUT", "/api/projects/" + enc(pid) + "/outputs", Object.assign({ targets, reason: reason.value.trim() }, signed()));
      say("Outputs chosen: " + (targets.join(", ") || "none") + ". Recorded with your name.", "good");
      await ui.settle(['[data-key="out-save"]']);
    });
  });
  const by = o.chosen_by;
  const line = by && by.by ? h("p", { class: "muted small" }, "Chosen by ", h("b", null, by.by), " (" + personaLabel(by.persona) + ") "
    + ago(by.at) + (by.when === "intake" ? ", at intake" : "") + (by.reason ? ": “" + by.reason + "”" : "") + ".")
    : h("p", { class: "muted small" }, "Nobody has chosen yet. The ticked ones are proposed; saving records your choice.");
  return card({ title: "What this project delivers", icon: "send", id: "out-choose",
    info: "Choosing is a recorded act: the ledger keeps who chose which outputs, as which persona, and what was chosen before. "
      + "Choosing the web app with sign-in adds the paved road's sign-in to the product." },
  line, h("fieldset", null, h("legend", { class: "vh" }, "Output targets"), h("div", { class: "out-pick" }, boxes)),
  h("div", { class: "field" }, h("label", { for: "out-reason" }, "Why (optional)"), reason),
  h("div", { class: "btns" }, save, note));
}

function downloadButton(pid, t, link, ui) {
  if (!link) return null;
  const dl = button("Download", { icon: "download", kind: "small", key: "out-dl:" + t.id, "data-control": "download_output",
    aria: "Download " + link.file + ", built just now" });
  dl.addEventListener("click", () => ui.run(dl, dl.parentNode, async () => {
    delete LINKS[pid][t.id];
    const name = await download(link.download, link.file);
    say(name + " downloaded. The link worked once: build it again for another.", "good");
    await ui.settle(['[data-key="out-build:' + t.id + '"]']);
  }));
  return dl;
}

function targetCard(pid, o, t, ui) {
  const state = t.status === "planned" ? chip("nm", "dashed", "Planned")
    : t.chosen ? chip("good", "check-circle", "Chosen") : t.proposed ? chip("info", "lightbulb", "Proposed") : chip("neutral", null, "Not chosen");
  const ready = t.status === "planned" ? null : t.ready ? chip("good", "check", "Ready to build") : chip("warning", "clock", "Not ready");
  const b = button("Build and download", { icon: "download", kind: "small", key: "out-build:" + t.id, "data-control": "build_output",
    aria: "Build and download the " + t.label.toLowerCase() });
  const builder = may(o.builders);
  const why = t.status === "planned" ? cap(t.why || "planned, not built yet") + "."
    : !t.chosen ? "Choose it first." : !t.ready ? cap(t.why || "not ready") + "." : null;
  const noteId = "out-why-" + t.id;
  const note = builder ? (why ? h("span", { class: "muted small", id: noteId }, why) : null) : guarded(b, false, o.builders, noteId);
  if (why && builder) { b.setAttribute("aria-disabled", "true"); b.setAttribute("aria-describedby", noteId); }
  b.addEventListener("click", () => {
    if (!builder || why) { say((note && note.textContent) || "Not ready.", "warning"); return; }
    if (!needPerson()) return;
    ui.run(b, b.parentNode, async () => {
      const [row] = await build(pid, [t.id]);
      if (row && row.download) {
        delete LINKS[pid][t.id];
        const name = await download(row.download, row.file);
        say(t.label + ": " + name + " built from the records and downloaded, signed by " + S.person.trim() + ".", "good");
      } else say(t.label + " was not built: " + ((row && row.why) || "no reason given") + ".", "warning");
      await ui.settle(['[data-key="out-build:' + t.id + '"]']);
    });
  });
  const link = (LINKS[pid] || {})[t.id];
  const last = t.last_build;
  return h("section", { class: "card out-card", "aria-labelledby": "out-h-" + t.id, "data-id": t.id },
    h("div", { class: "hd" }, h("span", { class: "card-ic" }, icon(t.icon || "send")), h("h3", { class: "card-t", id: "out-h-" + t.id, "data-ud": "" }, t.label)),
    h("p", { class: "muted small" }, "For " + t.audience),
    h("div", { class: "chips" }, state, ready),
    // what the target holds, as the kernel lists it (kernel/outputs.py): a record of the target, not reworded here
    h("ul", { "data-ud": "" }, (t.contains || []).map((c) => h("li", null, c))),
    last ? h("p", { class: "out-last" }, "Last built " + ago(last.at) + " by " + last.by + (last.release ? " from release " + last.release : "") + ": ",
      h("span", { class: "mono" }, last.file)) : null,
    link ? h("p", { class: "out-last" }, "Ready to download once: ", h("span", { class: "mono" }, link.file)) : null,
    h("div", { class: "btns" }, b, downloadButton(pid, t, link, ui), note));
}

export function viewOutputs(p, ctx, ui) {
  const pid = p.meta.id;
  const o = ctx.outputs;
  const head = ui.viewHead("Outputs", "What does each audience receive, and is it ready?");
  if (!o) return h("div", null, head, empty("send", "The outputs could not be read."));
  const rel = o.release;
  const all = button("Build every chosen output", { icon: "download", kind: "small", key: "out-all", "data-control": "build_outputs" });
  const allowed = may(o.builders) && o.chosen.length > 0;
  all.addEventListener("click", () => {
    if (!allowed) { say(o.chosen.length ? "A " + orList(o.builders) + " persona builds outputs." : "Choose an output first.", "warning"); return; }
    if (!needPerson()) return;
    ui.run(all, all.parentNode, async () => {
      const rows = await build(pid, o.chosen);
      const made = rows.filter((r) => r.download).length;
      say(plural(made, "output") + " built, signed by " + S.person.trim() + (rows.length > made ? "; " + (rows.length - made) + " not built yet (each card says why)" : "")
        + ". Each Download link works once.", made ? "good" : "warning");
      await ui.settle(['[data-key="out-all"]']);
    });
  });
  if (!allowed) all.setAttribute("aria-disabled", "true");
  return h("div", null, head,
    h("p", { class: "lede" }, rel ? "Built from release " + rel.release + " (revision " + short(rel.revision) + ", " + String(rel.state).replace(/_/g, " ")
      + ") and the project's records, with no model: the same records give the same files."
      : "No release yet: the report, the API description, the source and the evidence pack can be built now; the container and the sign-in wait for a release."),
    choice(pid, o, ui),
    h("div", { class: "btns" }, all),
    h("div", { class: "grid3 out-grid" }, o.targets.map((t) => targetCard(pid, o, t, ui))));
}
