/* Epics on a project's Board (FR-S2, kernel/epics.py): the customer's wishes above the requirements, each linked down
   to its stories and features (the spec's requirements), their tasks with their lane, and each task's commits and
   tests. Whether an epic qualifies (a named owner, a criterion in the owner's words, its blocking questions linked)
   is said on it, with what is missing. A business owner or product owner creates an epic and links requirements and
   questions to it; everyone else reads it. Ask Rihma's "show the epics" answers the same tree (kernel/epic_chat.py). */

import { S, h, icon, chip, api, enc, button, say, act, needPerson, signed, openModal, closeModal, mayAct, plural, orList } from "./core.js";
import { datum } from "./words.js";

const LANE_TONE = { planned: "neutral", in_progress: "accent", review: "warning", blocked: "critical", done: "good" };
const LANE = { planned: "Planned", in_progress: "In progress", review: "In review", blocked: "Blocked", done: "Done" };

function taskRow(t) {
  const failed = (t.tests || []).filter((x) => x.result !== "ok").length;
  return h("li", { class: "ep-task", "data-task": t.id },
    h("a", { href: t.open || "#", class: "mono" }, t.id), " ", datum(t.title), " ",
    chip(LANE_TONE[t.lane] || "neutral", "dashed", LANE[t.lane] || t.lane),
    t.commits ? chip("neutral", "code", plural(t.commits, "commit")) : null,
    (t.tests || []).length ? chip(failed ? "critical" : "good", "flask", plural(t.tests.length, "test") + (failed ? ", " + failed + " failed" : "")) : null);
}

function reqRow(r) {
  return h("li", { class: "ep-req", "data-req": r.id },
    h("b", { class: "mono" }, r.id), " ", datum(r.statement),
    r.tasks.length ? h("ul", { class: "plain ep-tasks" }, r.tasks.map(taskRow))
      : h("p", { class: "muted small" }, "No task yet: the contract compiles it into tasks."));
}

function epicEl(pid, e, tree, again) {
  const ok = e.qualified;
  return h("article", { class: "ep-epic", "data-epic": e.id },
    h("div", { class: "ep-head" }, h("span", { class: "mono" }, e.id), " ", h("b", null, datum(e.title)), " ",
      chip(ok ? "good" : "warning", ok ? "check-circle" : "alert", ok ? "Qualifies" : "Not qualified yet")),
    ok ? null : h("p", { class: "small ep-missing" }, "Missing: " + e.missing.join("; ") + "."),
    h("p", { class: "small muted" }, "Owner: " + (e.owner || "not named") + (e.criterion ? " · Done when: " : ""), e.criterion ? datum(e.criterion) : null),
    (e.questions || []).length ? h("p", { class: "small muted" }, "Questions linked: " + e.questions.join(", ")) : null,
    e.requirements.length ? h("ul", { class: "plain ep-reqs" }, e.requirements.map(reqRow))
      : h("p", { class: "muted small" }, "No requirement under it yet."),
    mayAct(tree.deciders) ? button("Link requirements", { icon: "edit", kind: "small", key: "ep-link:" + e.id, "data-control": "epic_link",
      onclick: () => openEpicForm(pid, tree, again, e) }) : null);
}

// The form for a new epic, or for what an existing one holds.
function openEpicForm(pid, tree, again, e) {
  const field = (id, label, value, attrs) => {
    const el = h("input", Object.assign({ id, "data-key": id, value: value || "", autocomplete: "off", maxlength: "2000" }, attrs || {}));
    return [el, h("div", { class: "field" }, h("label", { for: id }, label), el)];
  };
  const [title, titleF] = field("ep-title", "Title: the wish in the customer's words", e ? e.title : "", e ? { disabled: true } : null);
  const [owner, ownerF] = field("ep-owner", "Owner (a named business owner)", e ? e.owner : "");
  const [crit, critF] = field("ep-criterion", "Done when (the owner's words)", e ? e.criterion : "");
  const [qs, qsF] = field("ep-questions", "Blocking questions it depends on (Q-001, Q-002)", e ? (e.questions || []).join(", ") : "");
  const held = new Set(e ? e.requirements.map((r) => r.id) : []);
  const boxes = tree.requirements.map((rid) => h("label", { class: "ep-pick" },
    h("input", { type: "checkbox", value: rid, "data-key": "ep-req:" + rid, checked: held.has(rid) || null }), " " + rid));
  const save = button(e ? "Save" : "Create the epic", { icon: "check", kind: "primary human", key: "ep-save", "data-control": e ? "epic_link" : "epic_new" });
  const box = h("div", { class: "ep-form" }, titleF, ownerF, critF,
    h("fieldset", null, h("legend", null, "Requirements under it (its stories and features)"), boxes.length ? boxes : h("p", { class: "muted small" }, "The spec has no requirements yet.")),
    qsF, h("div", { class: "btns" }, save));
  save.addEventListener("click", () => act(box, async () => {
    if (!needPerson()) return;
    const body = Object.assign({ owner: owner.value.trim(), criterion: crit.value.trim(), questions: qs.value,
      requirements: boxes.map((b) => b.querySelector("input")).filter((x) => x.checked).map((x) => x.value) }, signed());
    const out = e ? await api("POST", "/api/projects/" + enc(pid) + "/epics/" + enc(e.id), body)
      : await api("POST", "/api/projects/" + enc(pid) + "/epics", Object.assign({ title: title.value.trim() }, body));
    closeModal();
    say((e ? "Saved " : "Created ") + out.epic.id + ", signed by " + S.person.trim() + ".", "good");
    again();
  }));
  openModal(e ? "What " + e.id + " holds" : "New epic", box, { icon: "flag", wide: true });
}

export function epicsCard(pid, tree, again) {
  const writer = mayAct(tree.deciders);
  const add = writer ? button("New epic", { icon: "plus", kind: "small", key: "ep-new", "data-control": "epic_new", onclick: () => openEpicForm(pid, tree, again, null) }) : null;
  const loose = tree.unlinked || [];
  return h("section", { class: "card ep-card", "aria-labelledby": "ep-h", "data-id": "epics", "data-control": "epics" },
    h("header", { class: "card-head" }, h("span", { class: "card-ic" }, icon("flag")), h("h3", { class: "card-t", id: "ep-h" }, "Epics"),
      h("span", { class: "card-tools" }, add)),
    tree.epics.length ? h("div", { class: "ep-list" }, tree.epics.map((e) => epicEl(pid, e, tree, again)))
      : h("p", { class: "muted small" }, "No epic yet. An epic is a customer's wish with its owner and what done looks like, in the owner's words; "
        + (writer ? "create one and put the requirements under it." : orList(tree.deciders) + " creates one.")),
    loose.length ? h("details", { class: "ep-loose" }, h("summary", null, plural(loose.length, "requirement") + " under no epic"),
      h("ul", { class: "plain ep-reqs" }, loose.map(reqRow))) : null);
}
