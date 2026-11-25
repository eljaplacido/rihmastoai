/* An adopted project's own page parts (FR-RPJ1, docs/brownfield.md): its real state instead of the factory's
   seven stages (monitoring, maintaining or improving; what was taken; its baseline and the command that made
   it; its activity), the kind of work only once a person or the rule chose it, its watch, the stated test
   commands it could run as a baseline, and its Areas card (inventory and activity by area). */

import { h, fill, icon, chip, api, say, card, button, signed, needPerson, enc, profileChip, openModal, closeModal, AuthError } from "./core.js";

const STATE_ICON = { monitoring: "eye", maintaining: "shield", improving: "hammer" };
const n = (x) => Number(x || 0).toLocaleString("en");

// The kind of work, only when chosen: an open "Which kind of work is this?" question shows as not chosen.
export function kindChip(p) {
  const id = p.meta.profile;
  if (id) return profileChip(id);
  return chip("nm", "dashed", "Kind: not chosen yet", { tip: "No kind of work is chosen yet: a person answers “Which kind of work is this?”, or chooses one in Project settings.",
    "data-control": "kind_not_chosen" });
}

function baselineText(b) {
  return "baseline " + (b.revision || "?") + ": " + b.verdict + (b.command ? " (" + b.command + (b.stated ? ", stated" : "") + ")" : "");
}

// The header's line for an adopted project, where a built one shows its stages.
export function adoptedLine(p) {
  const a = p.adopted;
  const b = a.baseline || {};
  return h("div", { class: "adopted-line", "data-control": "adopted_state" },
    chip(a.state === "monitoring" ? "info" : "accent", STATE_ICON[a.state] || "eye", "Adopted: " + a.state),
    chip(b.failed ? "warning" : b.verdict === "passed" ? "good" : "nm", b.failed ? "alert" : "check-circle", baselineText(b)),
    h("span", { class: "small muted adopted-act" }, (a.watch && a.watch.watching ? a.watch.line : a.activity.line)));
}

function stateCard(p) {
  const a = p.adopted;
  const left = a.left_out && (a.left_out.uncommitted || a.left_out.untracked)
    ? n(a.left_out.uncommitted) + " uncommitted change(s) and " + n(a.left_out.untracked) + " untracked file(s) were left out" : null;
  const sync = a.last_sync;
  return card({ title: "How it is held", icon: STATE_ICON[a.state] || "eye", id: "adopted-state", cls: "adopted-card",
    info: "An adopted project arrived built (or as a body of work): the factory " + a.state.replace(/ing$/, "s") + " it from here, instead of moving it through the seven stages." },
  h("dl", { class: "kv" },
    h("div", null, h("dt", null, "state"), h("dd", null, "Adopted to " + a.intent + ": " + a.state)),
    h("div", null, h("dt", null, "taken"), h("dd", null, a.took_said + (left ? "; " + left : ""))),
    h("div", null, h("dt", null, "baseline"), h("dd", null, baselineText(a.baseline || {}),
      a.baseline && a.baseline.failed ? h("small", { class: "muted" }, " Existing tests fail: recorded, not judged.") : null)),
    h("div", null, h("dt", null, "used today"), h("dd", null, a.usage.said + " (maturity " + (a.usage.maturity || "?") + ")")),
    h("div", null, h("dt", null, "activity"), h("dd", null, a.activity.line)),
    h("div", null, h("dt", null, "upstream"), h("dd", null, sync && sync.at ? "last look " + sync.at.slice(0, 10) + ": " + n(sync.new_commits) + " new commit(s)" : "not looked at since adoption"))));
}

function watchCard(p, rerender) {
  const w = p.adopted.watch || {};
  const pid = p.meta.id;
  const parts = [h("p", { class: "watch-line" }, w.line)];
  if (!w.watching) {
    const set = button("Set up the watch", { icon: "eye", kind: "small primary", "data-control": "watch_setup", key: "watch:setup" });
    set.addEventListener("click", async () => {
      if (!needPerson()) return;
      set.disabled = true;
      try {
        const out = await api("POST", "/api/projects/" + enc(pid) + "/watch", signed());
        say(out.watch.line, "good");
        await rerender();
      } catch (e) { if (!(e instanceof AuthError)) say(e.message, "critical"); set.disabled = false; }
    });
    parts.push(h("p", { class: "small muted" }, "New commits become a summary in Review and the timeline; the activity by area is summed up every week; a failed check notifies a channel. Through the automations, in your name."), h("div", { class: "btns" }, set));
  }
  return card({ title: "Watching", icon: "eye", id: "adopted-watch", cls: "adopted-card" }, parts);
}

function statedCard(p, rerender) {
  const offers = p.adopted.stated || [];
  if (!offers.length) return null;
  const pid = p.meta.id;
  return card({ title: "Stated test commands", icon: "terminal", id: "adopted-stated", cls: "adopted-card",
    info: "The project's instructions state these test commands, which the kernel does not run on its own: run one as the baseline once you say yes." },
  h("ul", { class: "plain" }, offers.map((o) => {
    const run = button("Run it as the baseline", { kind: "small", icon: "play", "data-control": "baseline_stated", aria: "Run " + o.command + " as the baseline" });
    run.addEventListener("click", () => {
      const yes = button("Yes, run it", { kind: "primary", icon: "play", "data-control": "baseline_stated_yes" });
      yes.addEventListener("click", async () => {
        if (!needPerson()) return;
        yes.disabled = true;
        try {
          const out = await api("POST", "/api/projects/" + enc(pid) + "/baseline/stated", Object.assign({ command: o.command, confirm: true }, signed()));
          closeModal();
          say("Running " + o.command + " as job " + out.job.id + ": its result becomes the baseline, with the command named.", "good");
          await rerender();
        } catch (e) { if (!(e instanceof AuthError)) say(e.message, "critical"); yes.disabled = false; }
      });
      openModal("Run a stated command", h("div", null, h("p", null, h("code", null, o.command), " (" + o.where + ")"),
        h("p", { class: "note" }, icon("alert"), h("span", null, o.runs_code)), h("div", { class: "btns" }, yes)), { icon: "terminal" });
      yes.focus();
    });
    return h("li", { class: "stated-row" }, h("code", null, o.command), h("small", { class: "muted" }, " " + o.where + ": " + o.why + ". "), run);
  })));
}

// The Areas card fills itself: what each top-level area holds, what moved in 30 days, the design and lore documents.
function areasCard(p) {
  const body = h("div", { class: "areas-body", "data-control": "project_areas" }, h("p", { class: "muted small" }, "Reading the areas…"));
  api("GET", "/api/projects/" + enc(p.meta.id) + "/areas").then((got) => {
    const a = got.areas || {};
    if (!a.measured) { fill(body, h("p", { class: "muted small" }, got.summary)); return; }
    const moved = {};
    (((a.activity || {}).windows || {})["30"] || []).forEach((m) => { moved[m.area] = m; });
    const rows = (a.areas || []).slice(0, 12).map((x) => h("tr", null, h("th", { scope: "row" }, x.area), h("td", { class: "num" }, n(x.files)),
      h("td", null, Object.entries(x.assets || {}).map(([k, v]) => v + " " + k).join(", ") || "—"),
      h("td", null, moved[x.area] ? n(moved[x.area].commits) + " commit" + (moved[x.area].commits === 1 ? "" : "s")
        + ", +" + n(moved[x.area].added) + "/-" + n(moved[x.area].removed) : "—")));
    fill(body, h("div", { class: "tbl" }, h("table", { class: "areas-tbl" },
      h("caption", { class: "vh" }, "Areas of " + p.meta.title),
      h("thead", null, h("tr", null, ["Area", "Files", "Assets", "Last 30 days"].map((t) => h("th", { scope: "col" }, t)))),
      h("tbody", null, rows))),
    (a.documents || []).length ? h("p", { class: "small" }, h("b", null, "Design and lore: "), a.documents.slice(0, 10).map((d) => d.title).join(" · ")) : null,
    h("p", { class: "small muted" }, (a.activity || {}).measured ? (a.activity.basis + ".") : (a.activity || {}).basis));
  }).catch((e) => { if (!(e instanceof AuthError)) fill(body, h("p", { class: "muted small" }, "The areas could not be read: " + e.message)); });
  return card({ title: "Areas", icon: "layers", id: "adopted-areas", cls: "adopted-card areas-card", dataId: "project_areas",
    info: "By rule from the repository, no model: what each top-level folder holds (with asset kinds such as models, textures, audio and scenes) and how it moved over 30 days." }, body);
}

// The side column's card for an adopted project, where a built one counts its stages.
export function adoptedSide(p) {
  const a = p.adopted;
  const rows = [["Adopted", "to " + a.intent + ": " + a.state], ["Taken", a.took_said], ["Baseline", baselineText(a.baseline || {})],
    ["Used today", a.usage.said], ["Watch", a.watch && a.watch.watching ? "watching" : "not watched yet"]];
  return card({ title: "Its state", icon: STATE_ICON[a.state] || "eye", cls: "stage-counts adopted-side",
    info: "An adopted project is monitored, maintained or improved from where it is: it did not go through the factory's seven stages." },
  h("ul", { class: "sc-list" }, rows.map(([k, v]) => h("li", { class: "sc" }, h("span", { class: "sc-n" }, k), h("span", { class: "sc-c" }, v)))));
}

export function adoptedOverview(p, rerender) {
  if (!p.adopted) return null;
  return h("div", { class: "section adopted-sec" }, h("div", { class: "two" }, stateCard(p), watchCard(p, rerender)),
    statedCard(p, rerender), p.adopted.has_areas ? areasCard(p) : null);
}
