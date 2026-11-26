/* Health (kernel/checks/, FR-CHK1): the checks a project runs for maintenance and administration, each with
   its last result, its trend and when it last ran, Run now and a builder to enable one; the factory-wide
   Health page; and Home's card when something fails. A result is passed, failed or not measured with why:
   not measured is never shown as passed. */

import { pick, emptyState, technical } from "./words.js";
import { S, $, h, fill, icon, chip, api, act, say, signed, needPerson, enc, button, card, empty, pageHead, skeleton,
  ago, link, nav } from "./core.js";
import { evalsCard, evalsFactoryCard } from "./evals.js";

const VERDICT = {
  passed: ["good", "check-circle", "Passed"], failed: ["critical", "x-circle", "Failed"],
  "not measured": ["nm", "dashed", "Not measured"], "not run yet": ["neutral", "clock", "Not run yet"],
};
const EVERY = [["", "On demand only"], ["15m", "Every 15 minutes"], ["1h", "Every hour"], ["6h", "Every 6 hours"],
  ["1d", "Every day"]];
const TREND_CLASS = { passed: "ok", failed: "bad", "not measured": "nm" };

export function verdictChip(state) {
  const [tone, ic, word] = VERDICT[state] || VERDICT["not measured"];
  return chip(tone, ic, word, { "data-verdict": state });
}

const checksOf = (pid) => "/api/projects/" + enc(pid) + "/checks";
const keyPath = (pid, key) => checksOf(pid) + "/" + enc(key);

function trend(rows) {
  return h("span", { class: "hl-trend", role: "img", "aria-label": "Last results: " + (rows.map((t) => t.verdict).join(", ") || "none") },
    rows.map((t) => h("span", { class: "hl-sq " + (TREND_CLASS[t.verdict] || "nm"), tip: t.verdict + " · " + ago(t.at) })));
}

function settingsLine(c) {
  const parts = Object.entries(c.config || {}).map(([k, v]) => k + ": " + (Array.isArray(v) ? v.join(", ") : String(v)));
  if (c.every) parts.push("every " + c.every);
  if ((c.on_fail || []).length) parts.push("on failure: " + c.on_fail.join(" and "));
  return parts.join(" · ");
}

function checkRow(pid, c, again) {
  const last = c.last || null;
  const tools = h("div", { class: "mdl-tools" });
  const run = button(c.running ? "Running" : "Run now", { icon: "play", kind: "small", key: "health-run:" + c.check,
    "data-control": "health_run", disabled: c.running, aria: "Run " + c.label + " now" });
  run.addEventListener("click", () => act(tools, async () => {
    if (!needPerson()) return;
    say("Running " + c.label + "…", "info");
    const out = await api("POST", keyPath(pid, c.check) + "/run", signed());
    say(c.label + ": " + (VERDICT[out.result.verdict] || [0, 0, out.result.verdict])[2] + ". " + out.result.summary,
      out.result.verdict === "passed" ? "good" : out.result.verdict === "failed" ? "warning" : "info");
    await again();
  }));
  const off = button("Disable", { icon: "x", kind: "small quiet", key: "health-disable:" + c.check,
    "data-control": "health_disable", aria: "Disable " + c.label });
  off.addEventListener("click", () => act(tools, async () => {
    if (!needPerson()) return;
    await api("POST", keyPath(pid, c.check) + "/disable", signed());
    say(c.label + " disabled.", "good");
    await again();
  }));
  tools.append(run, off);
  return h("li", { class: "mdl-row", "data-key": "check:" + c.check },
    h("div", { class: "mdl-main", "data-ud": "" },      // each check's name and summary are the catalogue's (kernel)
      h("b", null, c.label), h("span", { class: "mono muted small" }, " " + c.check),
      h("div", { class: "mdl-chips" }, verdictChip(c.state), last ? h("span", { class: "muted small" }, "ran " + ago(last.at)
        + (last.via ? " · " + last.via : "")) : null, trend(c.trend || [])),
      last ? h("p", { class: "hl-sum" }, last.summary) : h("p", { class: "muted small" }, c.what),
      settingsLine(c) ? h("p", { class: "muted small" }, settingsLine(c)) : null,
      last && (last.evidence || []).length ? h("details", { class: "hl-ev" }, h("summary", null, "Evidence"),
        h("pre", { class: "code" }, last.evidence.join("\n"))) : null),
    tools);
}

// -- the builder: enable a check -------------------------------------------------------------------------

function optionInput(name) {
  const id = "hl-o-" + name;
  return h("div", { class: "field", "data-option": name }, h("label", { for: id }, name === "deny"
    ? "deny (licences, comma between)" : name), h("input", { id, autocomplete: "off", spellcheck: "false" }));
}

function readOptions(form, check) {
  const config = {};
  (check.options || []).forEach((name) => {
    const el = form.querySelector("#hl-o-" + name);
    const v = el ? el.value.trim() : "";
    if (!v) return;
    if (name === "deny" || name === "exclude") config[name] = v.split(",").map((s) => s.trim()).filter(Boolean);
    else if (/^\d+$/.test(v)) config[name] = parseInt(v, 10);
    else if (v === "true" || v === "false") config[name] = v === "true";
    else config[name] = v;
  });
  return config;
}

// A check's name for a business reader: what it tells them, with the technical name in brackets where it helps.
const CHECK_PLAIN = { ci: "Automatic checks on each change (CI/CD)", dependencies: "Known weaknesses in the parts it uses",
  licences: "Licences of the parts it uses", sbom: "Software parts list (SBOM)", probe: "Is it online?",
  executions: "Did its scheduled jobs run?", secrets: "Passwords or keys left in the code", repo_gate: "Quality check on new code",
  security_gate: "Security check on new code", tests: "Its own tests", custom: "A check of your own (IT)" };
export function checkLabel(c) { return technical() ? c.label : CHECK_PLAIN[c.kind] || c.label; }
export function enableForm(catalogue, onEnable, opts) {
  const o = opts || {};
  const kind = h("select", { id: "hl-kind" }, catalogue.map((c) => h("option", { value: c.kind }, checkLabel(c))));
  const name = h("input", { id: "hl-name", autocomplete: "off", spellcheck: "false", placeholder: "prod" });
  const every = h("select", { id: "hl-every" }, EVERY.map(([v, l]) => h("option", { value: v }, l)));
  const sig = h("input", { type: "checkbox", id: "hl-f-signal" });
  const chg = h("input", { type: "checkbox", id: "hl-f-change" });
  const what = h("p", { class: "muted small", id: "hl-what" });
  const opts2 = h("div", { class: "hl-opts" });
  // the command, timeout and shell fields are an IT person's: folded for anyone else, never removed
  const optsBox = technical() ? opts2 : h("details", { class: "hl-adv" }, h("summary", null, "Advanced (IT)"), opts2);
  const form = h("div", { class: "hl-form" });
  const pick = () => catalogue.find((c) => c.kind === kind.value) || catalogue[0];
  const show = () => {
    const c = pick();
    fill(what, c.what + (c.needs.length ? " Needs: " + c.needs.join(", ") + "." : ""));
    fill(opts2, (c.options || []).map(optionInput));
    if (c.every && !o.keepEvery) every.value = c.every;
  };
  kind.addEventListener("change", show);
  const save = button(o.label || "Enable the check", { icon: "check", kind: "primary", key: o.key || "health-enable",
    "data-control": o["data-control"] || "health_enable" });
  save.addEventListener("click", () => act(form, async () => {
    if (!needPerson()) return;
    const c = pick();
    const key = c.kind + (name.value.trim() ? ":" + name.value.trim().toLowerCase().replace(/[^a-z0-9-]+/g, "-") : "");
    await onEnable(key, { config: readOptions(form, c), every: every.value || null,
      on_fail: [sig.checked ? "signal" : null, chg.checked ? "change" : null].filter(Boolean) });
  }));
  fill(form, h("div", { class: "row2" }, h("div", { class: "field" }, h("label", { for: "hl-kind" }, "Check"), kind),
    h("div", { class: "field" }, h("label", { for: "hl-name" }, "Name (optional, for several of one kind)"), name)),
  what, optsBox, h("div", { class: "field" }, h("label", { for: "hl-every" }, "Schedule"), every),
  h("fieldset", { class: "hl-fs" }, h("legend", null, "When it fails"),
    h("label", { class: "chk", for: "hl-f-signal" }, sig, technical() ? " Log a signal in the delivery square" : " Log a new request on Flow of work"),
    h("label", { class: "chk", for: "hl-f-change" }, chg, " Open a change proposal")),
  o.extra || null, h("div", { class: "btns" }, save));
  show();
  return form;
}

// -- a project's Health tab -----------------------------------------------------------------------------

export function viewChecks(p) {
  const pid = p.meta.id;
  const box = h("div", { class: "hl-tab" }, checksHead(), h("p", { class: "muted" }, "Loading…"));
  drawChecks(box, pid).catch((e) => { if (box.isConnected) fill(box, checksHead(), empty("alert", e.message)); });
  return box;
}

function checksHead() {
  return h("div", { class: "q" }, h("h2", { id: "view-title", tabindex: "-1" }, "Health"),
    h("p", null, pick("Is this project still healthy after it shipped? Its checks: tests, automatic checks on each change, the software "
      + "it depends on, leaked passwords, licences, whether it answers, and its quality checks, each passed, failed or not measured with why.",
    "Is this project still healthy after it shipped? Its checks: tests, CI/CD, dependencies, secrets, "
      + "licences, probes and gates, each passed, failed or not measured with why.")));
}

async function drawChecks(box, pid) {
  const data = await api("GET", checksOf(pid));
  if (!box.isConnected) return;
  const again = () => drawChecks(box, pid);
  const form = enableForm(data.catalogue || [], async (key, body) => {
    await api("POST", keyPath(pid, key) + "/enable", Object.assign(body, signed()));
    say(key + " enabled.", "good");
    await again();
  });
  const c = data.counts || {};
  fill(box, checksHead(),
    h("p", { class: "hl-line", id: "hl-line" }, icon(data.failing.length ? "alert" : "pulse"), h("span", null, cap(data.line) + ".")),
    h("div", { class: "mdl-chips hl-counts" }, verdictChip("passed"), h("span", null, String(c.passed || 0)), verdictChip("failed"),
      h("span", null, String(c.failed || 0)), verdictChip("not measured"), h("span", null, String(c["not measured"] || 0))),
    card({ title: "Checks", icon: "pulse", id: "hl-list-card" }, h("ul", { class: "emb-list", id: "hl-list" },
      data.checks.length ? data.checks.map((x) => checkRow(pid, x, again))
        : h("li", null, emptyState("checks", null, { icon: "pulse", what: "No check enabled yet.",
          how: pick("Turn one on below; its result appears here after its first run.", "Enable one below; its result and last run appear here.") })))),
    card({ title: "Enable a check", icon: "plus", id: "hl-new", info: "A check that runs the project's own code (tests, "
      + "a custom command, the repo gate) is enabled by a persona the console allows here." }, h("div", { "data-control": "health_enable" }, form)),
    evalsCard(pid),                                  // Gnomon's audits and evals (evals.js, FR-EVL1)
    h("p", { class: "small" }, h("a", { href: "#/health", "data-key": "hl-all:" + pid }, "Health across every project")));
  if (nav.refreshShell) nav.refreshShell();
}

function cap(s) { s = String(s || ""); return s.charAt(0).toUpperCase() + s.slice(1); }

// -- the factory-wide Health page ------------------------------------------------------------------------

export async function renderHealth(seq) {
  const main = $("#main");
  const done = skeleton(main, "Health");
  let data;
  try { data = await api("GET", "/api/checks"); } finally { done(); }
  if (seq !== S.seq) return;
  document.title = "Health · Rihmasto.ai";
  const again = () => renderHealth(S.seq);
  const c = data.counts || {};
  const none = !data.projects || data.projects.every((p) => !p.checks.length);
  fill(main, pageHead("Health", pick("Every project's checks: tests, automatic checks on each change, the software "
    + "it depends on, leaked passwords, licences, whether it is online, and its quality checks.",
  "Every project's checks: tests, CI/CD, dependencies, secrets, licences, probes and gates."), { icon: "pulse" }),
  none ? h("p", { class: "note" }, icon("info"), h("span", null, pick("No health checks are on yet. Choose checks below, or ask IT to set them up.",
    "No check is enabled on any project. Enable one below, or `rihmasto checks enable <pid> <check>`."))) : null,
  h("div", { class: "kpi-strip hl-kpis" }, [["passed", "Passing"], ["failed", "Failing"], ["not measured", "Not measured"],
    ["not run yet", "Not run yet"]].map(([k, label]) => h("div", { class: "card hl-kpi", "data-key": "hl-kpi:" + k },
    h("span", { class: "muted small" }, label), h("b", { class: "hl-kpi-n" }, String(c[k] || 0))))),
  data.failing.length ? card({ title: cap(data.line), icon: "alert", id: "hl-failing" }, h("ul", { class: "plain", id: "hl-failing-list" },
    data.failing.map((f) => h("li", null, verdictChip("failed"), " " + f)))) : h("p", { class: "hl-line", id: "hl-failing" }, cap(data.line) + "."),
  card({ title: "By project", icon: "folder", id: "hl-projects" }, projectsTable(data.projects || [])),
  card({ title: "Enable a check on several projects", icon: "plus", id: "hl-all-new" }, severalForm(data, again)),
  evalsFactoryCard());                               // every project's latest Gnomon audits (FR-EVL1)
}

function projectsTable(projects) {
  if (!projects.length) return empty("folder", "No project yet.");
  return h("div", { class: "tbl" }, h("table", null,
    h("thead", null, h("tr", null, h("th", null, "Project"), h("th", null, "Checks"), h("th", null, "Last run"))),
    h("tbody", null, projects.map((p) => {
      const ran = p.checks.map((x) => x.last && x.last.at).filter(Boolean).sort().pop();
      return h("tr", { "data-key": "hl-p:" + p.project },
        h("th", null, h("a", { href: link(p.project, "checks") }, p.title || p.project)),
        h("td", null, p.checks.length ? h("div", { class: "mdl-chips" }, p.checks.map((x) => h("span", { class: "hl-cell" },
          verdictChip(x.state), h("span", { class: "small" }, " " + x.label)))) : h("span", { class: "muted" }, "none enabled")),
        h("td", null, ran ? ago(ran) : h("span", { class: "muted" }, "never")));
    }))));
}

function severalForm(data, again) {
  const picks = h("div", { class: "hl-picks", role: "group", "aria-label": "Projects" }, (data.projects || []).map((p) =>
    h("label", { class: "chk", for: "hl-pp-" + p.project }, h("input", { type: "checkbox", id: "hl-pp-" + p.project, value: p.project,
      class: "hl-pp" }), " " + (p.title || p.project))));
  return enableForm(data.catalogue || [], async (key, body) => {
    const projects = [...document.querySelectorAll(".hl-pp")].filter((x) => x.checked).map((x) => x.value);
    if (!projects.length) { say("Tick the projects first.", "warning"); return; }
    await api("POST", "/api/checks/enable", Object.assign(body, { check: key, projects }, signed()));
    say(key + " enabled on " + projects.length + " project" + (projects.length === 1 ? "" : "s") + ".", "good");
    await again();
  }, { label: "Enable on these projects", key: "health-enable-all", "data-control": "health_enable_all",
    extra: h("fieldset", { class: "hl-fs" }, h("legend", null, "Projects"), picks) });
}

// -- Home: checks failing or not measured ----------------------------------------------------------------

export async function healthCard(box) {
  if (!box) return;
  let data;
  try { data = await api("GET", "/api/checks"); } catch (e) { return; }
  const c = data.counts || {};
  if (!box.isConnected || (!c.failed && !c["not measured"])) { if (box.isConnected) fill(box); return; }
  const unmeasured = (data.projects || []).flatMap((p) => p.checks.filter((x) => x.state === "not measured")
    .map((x) => p.project + ": " + x.label));
  fill(box, card({ title: c.failed ? cap(data.line) : unmeasured.length + " check" + (unmeasured.length === 1 ? "" : "s")
    + " not measured", icon: "alert", id: "home-health-card", cls: "setup-card" },
  h("ul", { class: "plain small" }, (c.failed ? data.failing : unmeasured).slice(0, 4).map((f) => h("li", null, f))),
  h("div", { class: "btns" }, h("a", { href: "#/health", class: "btn primary", "data-key": "home:health" }, icon("pulse"),
    h("span", { class: "lbl" }, "Open Health")))));
}
