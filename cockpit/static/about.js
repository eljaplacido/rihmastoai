/* About and help, a card in Settings (FR-PUB2; kernel/about.py, cockpit/about_routes.py).
   Which Rihmasto this is (pyproject.toml's version), a check of this machine as `rihmasto doctor` does it, and
   the guides: getting started, verifying what you install, the scenarios, contributing, the whole documentation.
   Ask Rihma answers the same questions by rule (kernel/assistant_help.py) and Take me there lands here. */

import { h, fill, icon, chip, api, card, button, act, AuthError } from "./core.js";
import { pick, datum } from "./words.js";

function versionLine(a) {
  const tone = a.prerelease ? "warning" : "good";
  const said = a.prerelease ? pick("An early version: see the changelog for what is ready", "A pre-release (PEP 440)") : pick("A release", "A final release");
  return h("p", { class: "abt-ver" }, h("span", null, "Rihmasto "), h("b", { class: "mono", "data-key": "about:version" }, datum(a.version)), " ",
    chip(tone, a.prerelease ? "alert" : "check-circle", said));
}

function commandRow(label, cmd) {
  return h("li", { class: "abt-cmd" }, h("span", { class: "small" }, label), h("code", { class: "mono" }, cmd));
}

function docRow(d) {
  return h("li", { class: "abt-doc", "data-key": "about:doc:" + d.id },
    h("a", { href: d.url, target: "_blank", rel: "noopener noreferrer" }, icon("book"), h("span", null, d.title)),
    h("span", { class: "small muted" }, " ", datum(d.says)),
    h("div", { class: "small muted mono abt-path" }, datum(d.path)));
}

function toolLine(name, t) {
  if (!t.found) return h("li", null, chip("neutral", "x-circle", name + ": " + pick("not found", "not on PATH")));
  return h("li", null, chip(t.ok === false || t.supported === false ? "warning" : "good", "check-circle", name),
    " ", datum(t.version || pick("version not read", "no version printed")));
}

function machineView(m) {
  const lead = m.ok ? chip("good", "check-circle", pick("This machine can run Rihmasto", "doctor: exit 0"))
    : chip("critical", "alert", pick("Something needs fixing first", "doctor: exit 1"));
  const lines = [["Python", m.python], ["Gnomon", m.gnomon], ["git", m.git], [pick("Docker (optional)", "docker (optional)"), m.docker]];
  const list = (items, tone) => items.length ? h("ul", { class: "abt-issues " + tone }, items.map((t) => h("li", null, datum(t)))) : null;
  return [h("p", null, lead), h("ul", { class: "abt-tools" }, lines.map(([n, t]) => toolLine(n, t))),
    list(m.problems, "critical"), list(m.warnings, "warning")];
}

function body(a) {
  const result = h("div", { class: "abt-machine", role: "status", "aria-live": "polite" },
    h("p", { class: "small muted" }, pick("Press Check this machine to see whether Python, Gnomon, git and Docker are ready here.",
      "Check this machine runs rihmasto doctor here: Python, Gnomon (0.6.5 or later), git and docker.")));
  const check = button("Check this machine", { icon: "pulse", kind: "small", key: "about:check",
    onclick: () => act(check.parentNode, async () => {
      fill(result, h("p", { class: "small muted" }, pick("Checking… this can take up to half a minute.", "Running doctor…")));
      fill(result, machineView(await api("GET", "/api/about/doctor")));
    }) });
  const forAll = a.docs.filter((d) => d.for === "everyone");
  const forDevs = a.docs.filter((d) => d.for !== "everyone");
  return [versionLine(a),
    h("div", { class: "abt-row" }, check), result,
    h("h4", { class: "abt-h" }, pick("In a terminal", "Commands")),
    h("ul", { class: "abt-cmds" }, commandRow(pick("Which version", "Version"), a.commands.version),
      commandRow(pick("Check this machine", "Doctor"), a.commands.doctor)),
    h("h4", { class: "abt-h" }, pick("Guides", "Documentation")),
    h("ul", { class: "abt-docs" }, forAll.map(docRow)),
    h("h4", { class: "abt-h" }, pick("For contributors", "Contributors and maintainers")),
    h("ul", { class: "abt-docs" }, forDevs.map(docRow))];
}

export function aboutCard() {
  const holder = h("div", { class: "abt-holder", "data-control": "about_help", id: "about-help" },
    card({ title: "About and help", icon: "info" }, h("p", { class: "small muted" }, pick("Loading…", "Reading /api/about…"))));
  api("GET", "/api/about").then((a) => fill(holder, card({ title: "About and help", icon: "info", id: "about-card",
    info: pick("Which Rihmasto this is, whether this computer is ready to run it, and where the guides are. Ask Rihma answers the same questions.",
      "The version pyproject.toml declares, rihmasto doctor's check, and the documentation. Ask Rihma answers the same by rule.") }, body(a))))
    .catch((e) => { if (!(e instanceof AuthError)) fill(holder, card({ title: "About and help", icon: "info" }, h("p", { class: "small" }, e.message))); });
  return holder;
}
