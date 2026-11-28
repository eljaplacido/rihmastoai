/* Gnomon posture: how well Gnomon governs a project and what to tighten first, computed by Rihmasto from the
   project's own .gnomon/config.toml and policy.toml (kernel/gnomon_posture, FR-GNP1). A project view
   (#/p/<pid>/gnomon_posture, the Govern capsule) for developers and IT. Read when the view opens; nothing is kept.
   Not measured says why, never a zero. Each suggestion names the exact setting in the project's own file and may be
   filed as a change card, signed, for a person to decide: nothing is applied here and Gnomon is granted no trust.
   What the kernel wrote (why, settings, where it read) is shown as its own words (data-ud). */

import { S, h, fill, icon, chip, api, enc, card, button, say, plural, signed, needPerson, act, empty } from "./core.js";
import { bars, SERIES } from "./charts.js";
import { datum } from "./words.js";

const base = (pid) => "/api/projects/" + enc(pid) + "/gnomon-posture";
const TONE = { high: "critical", medium: "warning", low: "neutral" };

function suggestionRow(pid, s, again, may) {
  const file = s.card ? chip("good", "check-circle", "Filed as " + s.card)
    : button("File as a change", { icon: "inbox", kind: "small quiet", key: "gp-file:" + s.id, "data-control": "gnomon_posture_propose",
      disabled: may ? null : true });
  if (!s.card) file.addEventListener("click", () => act(file.parentElement, async () => {
    if (!needPerson()) return;
    const r = await api("POST", base(pid) + "/propose", Object.assign({ suggestion: s.id }, signed()));
    say("Filed as change " + r.card.id + ": decide it in the Inbox.", "good");
    await again();
  }));
  return h("li", { class: "gp-sug", "data-suggestion": s.id },
    h("p", null, chip(TONE[s.severity] || "neutral", "alert", s.severity), " ", h("b", null, datum(s.title)),
      s.dimension ? h("span", { class: "muted small" }, " · " + s.dimension) : null),
    h("p", { class: "small" }, datum(s.why + ".")),
    h("p", { class: "small" }, "Set in ", h("code", { "data-ud": "" }, s.where || s.file), ": ", h("code", { "data-ud": "" }, s.setting)),
    h("div", { class: "btns" }, file));
}

function postureCard(pid, v, again) {
  const sugs = v.suggestions || [];
  const head = v.measured
    ? h("p", { class: "obs-lead" }, h("b", null, v.total + "/100"), v.weakest.length ? " · weakest: " + v.weakest.join(", ") : " · every setting checked holds")
    : h("div", { class: "obs-nm" }, h("p", null, chip("nm", "dashed", "Not measured"), " ", datum(v.why + ".")));
  const dims = v.measured ? bars({ rows: v.dimensions.map((d, i) => ({ label: d.label, value: d.pct, display: d.score + "/" + d.max,
    tip: d.label + ": " + d.pct + "%", color: d.pct < 34 ? "var(--critical-mark)" : d.pct < 67 ? "var(--warning-mark)" : SERIES(i + 1) })), unit: "%" }) : null;
  return h("div", { "data-control": "gnomon_posture_card" }, card({ title: "Gnomon safety", icon: "shield", id: "gp-posture", dataId: "gnomon_posture_card",
    info: "How well Gnomon governs this project, scored from its own .gnomon/config.toml and policy.toml: verification, containment, governance, audit, loop and context, freshness, the weakest first. Nothing here is applied: a suggestion becomes a change card at most." },
  head, dims, v.said ? h("p", { class: "small muted", "data-key": "gp-read" }, datum(v.said)) : null,
  (v.problems || []).map((p) => h("p", { class: "small" }, chip("warning", "alert", "Not read"), " ", datum(p))),
  sugs.length ? [h("h4", null, plural(sugs.length, "suggestion")), h("ul", { class: "plain gp-sugs" }, sugs.map((s) => suggestionRow(pid, s, again, v.may_file)))] : null));
}

async function draw(box, pid) {
  const again = () => draw(box, pid);
  const v = await api("GET", base(pid) + "?persona=" + enc(S.persona));
  if (!box.isConnected && box.dataset.drawn) return;
  box.dataset.drawn = "1";
  fill(box, h("div", { class: "gp-cards" }, postureCard(pid, v, again),
    h("p", { class: "small muted" }, icon("info"), " Computed from the project's own Gnomon files when this view opens; nothing is kept, nothing is applied.")));
}

export function render(p) {
  const pid = p.meta.id;
  const box = h("div", { class: "gp-view" }, h("p", { class: "muted" }, "Reading the project's Gnomon files…"));
  draw(box, pid).catch((e) => { if (box.isConnected) fill(box, empty("alert", e.message)); });
  return box;
}
