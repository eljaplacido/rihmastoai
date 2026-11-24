/* Settings > Runners (kernel/runners, D-0019): which harness runs the factory's cells. Gnomon is the default and the
   reference: it enforces the rules during a run. Another harness (Claude Code, Codex, OpenCode or a command a team
   names) is opt-in: IT approves it on a card with its version pinned, and every rule is checked after its runs. The
   page never shows "checked after the run" as Gnomon's in-run assurance. The project line lives in Project settings. */

import { S, $, h, fill, icon, chip, api, act, say, signed, needPerson, enc, button, card, pageHead, skeleton, openModal, closeModal, segmented } from "./core.js";

const STATE = { active: ["good", "check-circle", "In use"], waiting: ["warning", "clock", "Waiting on IT"], declined: ["critical", "x-circle", "Declined"],
  withdrawn: ["nm", "dashed", "Withdrawn"] };
const ROLE_LABEL = { builder: "Builder", verifier: "Verifier" };
const PAGE = { data: null, look: null, project: null };

// The one chip that says which assurance a role's rounds have: never the in-run words for a harness checked after.
export function assuranceChip(a) {
  return a.assurance === "in_run"
    ? chip("good", "shield", "In-run policy enforced by Gnomon", { tip: a.assurance_label })
    : chip("warning", "eye", "Checked after the run", { tip: a.assurance_label });
}

function roleLine(role, a) {
  return h("li", { class: "rn-row", "data-key": "rn-applies:" + role },
    h("div", { class: "rn-main" }, h("b", null, ROLE_LABEL[role]), " ",
      h("span", null, a.label + (a.version ? " " + a.version : "")),
      a.from === "default" ? h("span", { class: "muted small" }, " (the default)") : h("span", { class: "muted small" }, " (" + a.from + " choice " + (a.id || "") + ")")),
    h("div", { class: "rn-chips" }, assuranceChip(a), a.sandbox === "docker" ? chip("info", "package", "Docker sandbox") : null,
      a.family ? chip("neutral", "cpu", "family " + a.family) : null));
}

function appliesCard(scope, a) {
  const title = scope === "factory" ? "The factory's default" : "Project " + scope;
  return card({ title, icon: scope === "factory" ? "factory" : "folder", id: "rn-applies-" + scope },
    h("ul", { class: "emb-list rn-list" }, ["builder", "verifier"].map((r) => roleLine(r, a[r]))),
    a.clash ? h("p", { class: "note warning" }, icon("alert"), h("span", null, a.clash + ": nothing runs until one of them changes.")) : null);
}

function lookList(look) {
  if (!look) return h("p", { class: "muted small", id: "rn-look-none" }, "Check looks for each runner on this machine and asks its version.");
  return h("div", null,
    h("ul", { class: "emb-list rn-list", "aria-label": "Runners on this machine" }, look.runners.map((r) =>
      h("li", { class: "rn-row", "data-key": "rn-found:" + r.id },
        h("div", { class: "rn-main" }, h("b", null, r.label), " ", h("span", { class: "muted small" }, r.about)),
        h("div", { class: "rn-chips" }, r.detected.found ? chip("good", "check-circle", "Found " + (r.detected.version || ""))
          : chip("warning", "alert", "Not found", { tip: r.detected.why }), assuranceChip(r)),
        r.detected.found ? null : h("p", { class: "muted small rn-why" }, r.detected.why)))),
    h("p", { class: "muted small", "data-key": "rn-docker" }, icon(look.docker.available ? "check-circle" : "alert"),
      look.docker.available ? " Docker " + look.docker.version + " answers: a runner can run in the docker sandbox."
        : " " + look.docker.why + ": a runner set to the docker sandbox does not run here."));
}

function decideButtons(c) {
  if (c.state !== "waiting" || !c.card) return null;
  if (S.persona !== "it") return h("span", { class: "muted small" }, "IT decides " + c.card + ".");
  const go = (verdict) => () => {
    if (!needPerson()) return;
    act($("#rn-choices"), async () => {
      await api("POST", "/api/projects/" + enc(PAGE.data.cards_project) + "/cards/" + enc(c.card) + "/decide",
        Object.assign({ verdict, reason: verdict === "approve" ? "approved in Settings > Runners" : "declined in Settings > Runners" }, signed()));
      say(c.card + (verdict === "approve" ? " approved: " + c.runner + " " + c.version + " runs the " + c.role + " from now on." : " declined."), "good");
      await renderRunners(S.seq);
    });
  };
  return h("span", { class: "btns" },
    button("Approve", { icon: "check", kind: "small primary", "data-control": "runners_decide", key: "rn-approve:" + c.id, aria: "Approve " + c.card, onclick: go("approve") }),
    button("Decline", { icon: "x", kind: "small", key: "rn-decline:" + c.id, aria: "Decline " + c.card, onclick: go("decline") }));
}

function choiceRow(c) {
  const st = STATE[c.state] || STATE.withdrawn;
  return h("li", { class: "rn-row", "data-key": "rn-choice:" + c.id },
    h("div", { class: "rn-main" }, h("b", null, c.id), " ", ROLE_LABEL[c.role] + ": " + c.runner + (c.version ? " " + c.version : ""),
      h("span", { class: "muted small" }, " for " + (c.scope === "factory" ? "the factory" : c.scope) + ", by " + c.by + (c.reason ? ": " + c.reason : ""))),
    h("div", { class: "rn-chips" }, chip(st[0], st[1], st[2]), assuranceChip(c), decideButtons(c)));
}

function field(id, label, control, help) {
  return h("div", { class: "field" }, h("label", { for: id }, label), control, help ? h("small", { class: "muted" }, help) : null);
}

function openChoose() {
  const d = PAGE.data;
  const projects = Object.keys(d.applies).filter((k) => k !== "factory");
  (S.projects || []).forEach((p) => { if (p.id && p.id[0] !== "_" && !projects.includes(p.id)) projects.push(p.id); });
  const scope = h("select", { id: "rn-scope" }, h("option", { value: "factory" }, "The factory (every project)"),
    projects.map((p) => h("option", { value: p, selected: p === PAGE.project }, "Project " + p)));
  let role = "builder";
  const roleSeg = segmented("rn-role", [["builder", "Builder"], ["verifier", "Verifier"]], role, (v) => { role = v; }, { label: "Role" });
  const runner = h("select", { id: "rn-runner" }, d.runners.map((r) => h("option", { value: r.id }, r.label)));
  const version = h("input", { id: "rn-version", maxlength: "100", autocomplete: "off", placeholder: "the version found here" });
  const model = h("input", { id: "rn-model", maxlength: "200", autocomplete: "off" });
  const family = h("input", { id: "rn-family", maxlength: "64", autocomplete: "off" });
  const command = h("input", { id: "rn-command", maxlength: "2000", autocomplete: "off", spellcheck: "false", placeholder: "my-agent --task {prompt_file} --cwd {workdir}" });
  const sandbox = h("select", { id: "rn-sandbox" }, h("option", { value: "off" }, "Off: on this machine, in the working copy"),
    h("option", { value: "docker" }, "Docker: only the working copy, no network but the model endpoint"));
  const image = h("input", { id: "rn-image", maxlength: "300", autocomplete: "off", placeholder: "an image that holds the harness" });
  const reason = h("input", { id: "rn-reason", maxlength: "2000", autocomplete: "off" });
  const commandF = field("rn-command", "Command line ({prompt_file} and {workdir} are filled in)", command);
  const imageF = field("rn-image", "Sandbox image", image);
  const sync = () => {
    const r = d.runners.find((x) => x.id === runner.value) || {};
    commandF.hidden = runner.value !== "command";
    imageF.hidden = sandbox.value !== "docker";
    const found = PAGE.look && PAGE.look.runners.find((x) => x.id === runner.value);
    version.placeholder = found && found.detected.version ? found.detected.version : "the version found here";
    family.placeholder = r.family || "";
  };
  runner.addEventListener("change", sync);
  sandbox.addEventListener("change", sync);
  sync();
  const form = h("form", { class: "np-form", novalidate: true },
    h("p", { class: "note" }, icon("shield"), h("span", null, "Gnomon applies at once. Another runner waits on a card IT decides, with its version pinned; "
      + "its rounds are checked after the run, never enforced during it.")),
    h("div", { class: "row2" }, field("rn-scope", "For", scope), h("div", { class: "field" }, h("label", null, "Role"), roleSeg)),
    field("rn-runner", "Runner", runner),
    h("div", { class: "row2" }, field("rn-version", "Version to pin (empty: the one found here)", version), field("rn-model", "Model (optional)", model)),
    field("rn-family", "Model family (the verifier's must differ from the builder's)", family),
    commandF, field("rn-sandbox", "Sandbox", sandbox), imageF, field("rn-reason", "Reason (recorded with your name)", reason),
    h("div", { class: "btns" }, h("button", { type: "submit", class: "btn primary", "data-control": "runners_set", "data-key": "rn-save" }, icon("check"), "Choose this runner")));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!needPerson()) return;
    act(form, async () => {
      const out = (await api("PUT", "/api/runners/" + role, Object.assign({ runner: runner.value, project: scope.value === "factory" ? "" : scope.value,
        version: version.value.trim(), model: model.value.trim(), family: family.value.trim(), command: command.value.trim(), sandbox: sandbox.value,
        image: image.value.trim(), reason: reason.value.trim() }, signed()))).choice;
      closeModal();
      say(out.state === "waiting" ? out.id + " waits on IT: card " + out.card + " in the factory's Inbox." : ROLE_LABEL[out.role] + " runs on " + out.runner + " from now on.", "good");
      await renderRunners(S.seq);
    });
  });
  openModal("Choose a runner", form, { icon: "layers", wide: true });
}

export async function renderRunners(seq) {
  const main = $("#main");
  const r = S.route || {};
  PAGE.project = r.id || null;
  const done = skeleton(main, "the runners");
  let data;
  try { data = await api("GET", "/api/runners" + (PAGE.project ? "?project=" + enc(PAGE.project) : "")); } finally { done(); }
  if (seq !== S.seq) return;
  PAGE.data = data;
  document.title = "Runners · Rihmasto.ai";
  const lookBox = h("div", { id: "rn-look", "aria-live": "polite" }, lookList(PAGE.look));
  const check = button("Check", { icon: "refresh", kind: "small", "data-control": "runners_check", key: "rn-check", aria: "Look for each runner on this machine" });
  check.addEventListener("click", () => act(check.parentNode, async () => {
    PAGE.look = await api("GET", "/api/runners?check=1");
    fill(lookBox, lookList(PAGE.look));
  }));
  const choose = button("Choose a runner", { icon: "layers", kind: "small primary", "data-control": "runners_set", key: "rn-choose", onclick: openChoose });
  fill(main,
    pageHead("Runners", "Which harness runs the factory's cells. Gnomon is the default and the reference; another harness is opt-in, approved by IT on a card with its version pinned.", { icon: "layers" }),
    h("p", { class: "note" }, icon("shield"), h("span", null, h("b", null, "Two levels of assurance. "),
      "With Gnomon the write scope, the protected paths and the shell rules are enforced during the run, with a hash-chained record of every tool call. "
      + "With another harness nothing is enforced during the run: after it, Rihmasto checks the diff stays in the write scope, no protected path is touched, "
      + "each criterion's tests fail first, and the independent verifier and the holdouts pass. A change that fails any of them never merges.")),
    Object.entries(data.applies).map(([scope, a]) => appliesCard(scope, a)),
    card({ title: "On this machine", icon: "monitor", id: "rn-machine", tools: [check, choose] }, lookBox),
    card({ title: "Choices", icon: "list", id: "rn-choices" }, data.choices.length
      ? h("ul", { class: "emb-list rn-list" }, data.choices.map(choiceRow))
      : h("p", { class: "muted small" }, "No choice yet: Gnomon runs both roles.")));
}

// Project settings' runner line: what runs this project's builder and verifier, and where to change it.
export async function projectRunnerLine(box, pid) {
  let data;
  try { data = await api("GET", "/api/runners?project=" + enc(pid)); } catch (e) { fill(box, h("span", { class: "muted small" }, "The runners could not be read.")); return; }
  if (!box.isConnected) return;
  const a = data.applies[pid];
  fill(box, h("div", { class: "rn-line" }, ["builder", "verifier"].map((r) => h("span", { class: "rn-line-role", "data-key": "ps-runner:" + r },
    h("b", null, ROLE_LABEL[r] + ": "), a[r].label + (a[r].version ? " " + a[r].version : "") + " ", assuranceChip(a[r]))),
  h("a", { href: "#/runners/" + enc(pid), class: "btn small", "data-control": "project_runner", "data-key": "ps-runners" }, icon("layers"),
    h("span", { class: "lbl" }, "Change in Settings > Runners"))));
}
