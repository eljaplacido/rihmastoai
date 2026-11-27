/* A project's own sources (FR-SRC1, kernel/native_sources.py, docs/guides/own-sources.md): where an adopted or
   attached project keeps its requirements, criteria, tests, test results, findings and tasks.

   One panel, in Project settings and in What Rihmasto understood: the next steps from the real state as buttons
   first; then what is mapped (Change, Stop, its last read), what was found by rule (Map), the planning documents that
   may be old plans (Use it anyway), the test roots and runs (Run its tests after a yes, Import results produced
   elsewhere), and the trace of each requirement to its test. Platform-wide and project-specific settings are said
   apart. Every empty part says what would be there and how; every write is signed. */

import { S, h, fill, icon, chip, api, act, say, signed, needPerson, button, ago, enc, plural } from "./core.js";
import { datum, emptyState, pick } from "./words.js";
import { openAssistant, send as askRihma } from "./assistant.js";

const FIELDS = ["id", "title", "statement", "criteria", "test", "status", "severity", "where"];
const TONE = { passed: "good", failed: "critical", "not run": "nm", "no test named": "warning" };
function base(pid) { return "/api/projects/" + enc(pid) + "/sources"; }

/* The panel for project ``pid``: drawn now with a line that it is reading, then filled. ``onChange`` runs after a
   write (the understanding card draws again). */
export function sourcesPanel(pid, opts) {
  const o = opts || {};
  const box = h("div", { class: "src-panel", "data-control": "sources_panel", "aria-live": "polite" },
    h("p", { class: "muted small" }, "Reading the project's own sources…"));
  load(box, pid, o);
  return box;
}

async function load(box, pid, o) {
  try {
    draw(box, pid, await api("GET", base(pid)), o);
  } catch (e) {
    fill(box, emptyState("sources", null, { icon: "alert", what: "The project's own sources could not be read: " + e.message,
      how: "Ask Rihma why, or try again once the cockpit answers." }));
  }
}

async function write(box, pid, o, path, body, said) {
  if (!needPerson()) return;
  const out = await act(box, () => api("POST", base(pid) + path, Object.assign({}, body || {}, signed())));
  if (!out) return;
  if (said) say(typeof said === "function" ? said(out) : said, "good");
  draw(box, pid, out.mapped ? out : await api("GET", base(pid)), o);
  if (o.onChange) o.onChange();
}

function ask(question) { openAssistant(); askRihma(question); }

function draw(box, pid, v, o) {
  if (!v.applies) {
    fill(box, emptyState("sources", null, { icon: "info", what: v.why,
      how: "Adopt or attach the project's repository; then Rihmasto finds where it keeps its requirements, tests and tasks." }));
    return;
  }
  const mapped = v.mapped.filter((s) => s.state === "mapped");
  fill(box,
    h("div", { class: "src-bar" },
      h("p", { class: "src-sum", "data-ud": "" }, mapped.length
        ? plural(mapped.length, "source") + " mapped" + (v.read ? ", read " + ago(v.read.at) : "")
        : "Nothing is mapped yet: Rihmasto guesses from documents until you say where the project keeps its own."),
      h("span", { class: "src-bar-r" },
        mapped.length ? button("Read again", { icon: "refresh", kind: "small", key: "src-read", "data-control": "sources_read",
          onclick: () => write(box, pid, o, "/read", {}, readSaid) }) : null,
        button("Ask Rihma", { icon: "sparkles", kind: "small", key: "src-ask",
          onclick: () => ask("Where does this project keep its requirements?") }))),
    nextSteps(box, pid, v, o),
    section("Mapped", "check", mapped.length ? h("ul", { class: "src-list" }, mapped.map((s) => mappedRow(box, pid, v, o, s)))
      : emptyState("sources", null, { what: "No source is mapped.", how: "Map one that was found below, or tell Rihma which files hold them." })),
    section("Found, not mapped", "search", v.detected.length ? h("ul", { class: "src-list" }, v.detected.map((p) => detectedRow(box, pid, v, o, p)))
      : emptyState("sources", null, { what: "Nothing more was found by rule.",
        how: pick("Tell Rihma in Ask Rihma which files hold them.", "Name the files in Ask Rihma, for example: use rules/*.json as requirements.") })),
    (v.stopped || []).length ? section("Stopped", "x", h("ul", { class: "src-list" }, v.stopped.map((s) => stoppedRow(box, pid, o, s))),
      "Kept, not read: what they hold is not offered again until you resume one.") : null,
    v.stale.length ? section("May be old plans", "clock", h("ul", { class: "src-list" }, v.stale.map((s) => staleRow(box, pid, o, s))),
      pick("Left out of what Rihmasto imports, until you say to use one.",
        "Not imported by default (" + v.rule.stale_days + " days older than the code, " + v.rule.stale_commits + " code commits since).")) : null,
    section("Test runs", "play", runsPart(box, pid, v, o)),
    section("Trace", "link", tracePart(v)),
    h("div", { class: "src-scope" },
      h("p", { class: "small" }, chip("accent", "folder", "This project"), " ", h("span", { "data-ud": "" }, v.scope.project)),
      h("p", { class: "small" }, chip("neutral", "globe", "Platform-wide"), " ", h("span", { "data-ud": "" }, v.scope.platform))),
    v.unreadable ? h("p", { class: "note warning" }, icon("alert"), h("span", { "data-ud": "" }, "Not measured: " + v.unreadable)) : null);
  if (o.onDrawn) o.onDrawn(v);   // the fold around it stays open while next steps remain (project.js, FR-SRC2)
}

function section(title, iconName, body, note) {
  return h("div", { class: "src-sec" }, h("h4", { class: "src-h" }, icon(iconName), title),
    note ? h("p", { class: "muted small" }, note) : null, body);
}

// After a map, the toast says what comes next when the sources now wait for review in Alignment (FR-SRC2).
function mappedSaid(out) {
  const review = (out.next || []).find((s) => s.do.kind === "align");
  return "Mapped as " + out.source.id + " and read." + (review ? " Next: " + review.label + " in Alignment." : "");
}

// Read again fetches the upstream first: the toast says whether it moved, or why it could not (FR-SRC2).
function readSaid(out) {
  const f = out.fetched || {};
  return "Read again: " + (f.line || "read from the latest committed revision") + ".";
}

async function setUpWatch(box, pid, o) {
  if (!needPerson()) return;
  const out = await act(box, () => api("POST", "/api/projects/" + enc(pid) + "/watch", signed()));
  if (!out) return;
  say(out.watch.line, "good");
  draw(box, pid, await api("GET", base(pid)), o);
  if (o.onChange) o.onChange();
}

function doStep(box, pid, v, o, step, anchor) {
  const d = step.do;
  if (d.kind === "map") return write(box, pid, o, "/map", { key: d.key }, mappedSaid);
  if (d.kind === "read") return write(box, pid, o, "/read", {}, readSaid);
  if (d.kind === "align") { location.hash = "#/p/" + enc(pid) + "/align"; return null; }
  if (d.kind === "watch") return setUpWatch(box, pid, o);
  if (d.kind === "use_anyway") return write(box, pid, o, "/use-anyway", { path: d.path }, d.path + " is used anyway.");
  if (d.kind === "run") return confirmRun(box, pid, o, d.root, (v.roots.find((r) => r.root === d.root) || {}).command, anchor);
  if (d.kind === "import") { const f = box.querySelector(".src-import"); if (f) { f.hidden = false; f.querySelector("textarea").focus(); } return null; }
  return ask(d.question || "Where does this project keep its requirements?");
}

// The control a next step's button is: the review opens Alignment (FR-SRC2), the others act on a source.
function stepControl(kind) {
  if (kind === "align") return { "data-control": "sources_review" };
  return { "data-control": { map: "sources_map", run: "sources_run", import: "sources_import", use_anyway: "sources_use_anyway",
    read: "sources_read", watch: "watch_setup" }[kind] || null };
}

function nextSteps(box, pid, v, o) {
  if (!v.next.length) return null;
  return h("div", { class: "src-next" }, h("h4", { class: "src-h" }, icon("arrow-right"), "What to do next"),
    h("ol", { class: "src-steps" }, v.next.map((s, i) => h("li", null,
      button(s.label, { kind: "small" + (i === 0 ? " primary" : ""), key: "src-next:" + i, icon: "arrow-right",
        ...stepControl(s.do.kind),
        onclick: (e) => doStep(box, pid, v, o, s, e.currentTarget.closest("li")) }),
      h("span", { class: "muted small", "data-ud": "" }, s.why)))));
}

function mapping(m) {
  const keys = Object.entries(m || {});
  return keys.length ? keys.map(([f, k]) => f + " ← " + k).join(", ") : "read by its format";
}

function mappedRow(box, pid, v, o, s) {
  const last = s.last || {};
  const row = h("li", { class: "src-item", "data-source": s.id, "data-kind": s.kind },
    h("div", { class: "src-top" }, h("b", { "data-ud": "" }, s.kind_label), h("code", null, s.glob || "test roots"),
      chip("neutral", null, s.id), chip("info", "clock", "read again " + s.every_said)),
    s.kind === "tests" ? rootsList(box, pid, o, s) : h("p", { class: "src-line", "data-ud": "" },
      s.last ? plural(last.records || 0, "record") + " from " + plural(last.files || 0, "file") + ", read " + ago(last.read_at) : "Not read yet.",
      " · ", mapping(s.mapping)),
    (last.errors || []).length ? h("ul", { class: "src-errors" }, last.errors.map((e) => h("li", { "data-ud": "" }, icon("alert"), e))) : null,
    h("div", { class: "btns" },
      button("Change", { icon: "edit", kind: "small", key: "src-change:" + s.id, "data-control": "sources_change",
        onclick: () => toggle(row, ".src-change-form", () => changeForm(box, pid, v, o, s)) }),
      button("Stop", { icon: "x", kind: "small", key: "src-stop:" + s.id, "data-control": "sources_stop",
        onclick: () => toggle(row, ".src-stop-form", () => stopForm(box, pid, o, s)) })));
  return row;
}

function toggle(row, sel, make) {
  const have = row.querySelector(sel);
  if (have) { have.remove(); return; }
  const f = make();
  row.append(f);
  const first = f.querySelector("input, select, textarea");
  if (first) first.focus();
}

function changeForm(box, pid, v, o, s) {
  const id = (x) => "src-" + s.id + "-" + x;
  const glob = h("input", { id: id("glob"), "data-key": id("glob"), value: s.glob || "", maxlength: "200", autocomplete: "off" });
  const every = h("select", { id: id("every"), "data-key": id("every") },
    Object.entries(v.every).map(([k, l]) => h("option", { value: k, selected: k === s.every }, l)));
  const fields = s.kind === "requirements" || s.kind === "findings" ? FIELDS.map((f) => h("label", { class: "src-field" },
    h("span", null, f), h("input", { "data-field": f, value: (s.mapping || {})[f] || "", maxlength: "80", autocomplete: "off",
      "aria-label": "The key that holds the " + f }))) : [];
  const form = h("form", { class: "src-change-form", novalidate: true, "aria-label": "Change " + s.id },
    s.kind === "tests" ? null : h("label", { for: id("glob") }, "Files"), s.kind === "tests" ? null : glob,
    h("label", { for: id("every") }, "Read again"), every,
    fields.length ? h("div", { class: "src-fields" }, fields) : null,
    h("div", { class: "btns" }, button("Save", { type: "submit", kind: "small primary", key: "src-save:" + s.id })));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    e.stopPropagation();   // inside Project settings, its own form never submits the settings
    const m = {};
    form.querySelectorAll("[data-field]").forEach((x) => { if (x.value.trim()) m[x.dataset.field] = x.value.trim(); });
    const spec = s.kind === "tests" ? {} : { glob: glob.value.trim(), mapping: m };
    write(box, pid, o, "/map", { source: s.id, spec, every: every.value }, s.id + " changed and read again.");
  });
  return form;
}

function stopForm(box, pid, o, s) {
  const reason = h("input", { "data-key": "src-reason:" + s.id, maxlength: "500", autocomplete: "off", "aria-label": "Why stop reading it",
    placeholder: "why, for example: the rules moved to another folder" });
  const form = h("form", { class: "src-stop-form", novalidate: true, "aria-label": "Stop reading " + s.id }, reason,
    button("Stop reading it", { type: "submit", kind: "small danger", key: "src-stop-ok:" + s.id }));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    e.stopPropagation();   // inside Project settings, its own form never submits the settings
    write(box, pid, o, "/" + enc(s.id) + "/stop", { reason: reason.value.trim() }, s.id + " is no longer read; it is kept, stopped.");
  });
  return form;
}

function rootsList(box, pid, o, s) {
  return h("ul", { class: "src-roots" }, (s.roots || []).map((r) => h("li", { "data-root": r.root || "." },
    h("code", null, (r.root || ".") + " · " + r.command),
    button("Run its tests", { icon: "play", kind: "small", key: "src-run:" + (r.root || "."), "data-control": "sources_run",
      onclick: (e) => confirmRun(box, pid, o, r.root, r.command, e.currentTarget.closest("li")) }))));
}

/* Running the project's own code asks for a yes in place, beside the button that asked. */
function confirmRun(box, pid, o, root, command, anchor) {
  const at = anchor || box;
  const have = at.querySelector(".src-run-ok");
  if (have) { have.remove(); return; }
  const where = root || "the repository's root";
  const yes = button("Yes, run it", { icon: "play", kind: "small human primary", key: "src-run-ok:" + (root || ".") });
  const ok = h("div", { class: "src-run-ok note warning" }, icon("alert"),
    h("span", null, "Run ", h("code", null, command || "its tests"), " in " + where + "? It runs the project's own code on this "
      + "machine, offline, in a temporary checkout, with a time limit."), yes);
  yes.addEventListener("click", () => {
    if (!needPerson()) return;
    act(ok, async () => {
      const out = await api("POST", base(pid) + "/run", Object.assign({ root: root || "", confirm: true }, signed()));
      ok.remove();
      say("Running " + (command || "its tests") + " in " + where + " as job " + out.job.id + ": follow it live in Running now; "
        + "its result is kept here.", "good");
      if (o.onChange) o.onChange();
    });
  });
  at.append(ok);
  yes.focus();
}

function detectedRow(box, pid, v, o, p) {
  return h("li", { class: "src-item found", "data-key-src": p.key, "data-kind": p.kind },
    h("div", { class: "src-top" }, h("b", { "data-ud": "" }, v.kinds[p.kind]), h("code", null, p.glob || "test roots")),
    h("p", { class: "src-line", "data-ud": "" }, p.why),
    p.sample ? h("p", { class: "muted small" }, "For example: ", datum(p.sample)) : null,
    h("div", { class: "btns" }, button("Map", { icon: "check", kind: "small primary", key: "src-map:" + p.key, "data-control": "sources_map",
      onclick: () => write(box, pid, o, "/map", { key: p.key }, mappedSaid) })));
}

// A stopped source: who stopped it and why, and Resume (the same signed map, of the source as it was; FR-SRC2).
function stoppedRow(box, pid, o, s) {
  const st = s.stopped || {};
  return h("li", { class: "src-item stopped", "data-source": s.id, "data-kind": s.kind },
    h("div", { class: "src-top" }, h("b", { "data-ud": "" }, s.kind_label), h("code", null, s.glob || "test roots"),
      chip("neutral", null, s.id), chip("nm", "x", "stopped")),
    h("p", { class: "src-line", "data-ud": "" }, "Stopped by " + (st.person || "?") + (st.at ? " " + ago(st.at) : "")
      + (st.reason ? ": " + st.reason : "")),
    h("div", { class: "btns" }, button("Resume", { icon: "refresh", kind: "small", key: "src-resume:" + s.id, "data-control": "sources_resume",
      aria: "Resume reading " + s.id, onclick: () => write(box, pid, o, "/map", { source: s.id, spec: {} }, s.id + " is read again.") })));
}

function staleRow(box, pid, o, s) {
  return h("li", { class: "src-item stale", "data-path": s.path },
    h("div", { class: "src-top" }, h("code", null, s.path), chip("warning", "clock", "may be an old plan")),
    h("p", { class: "src-line", "data-ud": "" }, s.why),
    h("div", { class: "btns" }, button("Use it anyway", { icon: "check", kind: "small", key: "src-anyway:" + s.path,
      "data-control": "sources_use_anyway", onclick: () => write(box, pid, o, "/use-anyway", { path: s.path }, s.path + " is used anyway.") })));
}

function runsPart(box, pid, v, o) {
  const text = h("textarea", { "data-key": "src-import-text", rows: "4", "aria-label": "The results file's content",
    placeholder: "Paste a JUnit XML, TAP or JSON results file, or choose the file" });
  const file = h("input", { type: "file", "data-key": "src-import-file", accept: ".xml,.json,.tap,.txt", "aria-label": "Choose a results file" });
  file.addEventListener("change", async () => { if (file.files[0]) text.value = await file.files[0].text(); });
  const when = h("input", { "data-key": "src-import-when", maxlength: "40", autocomplete: "off", "aria-label": "When it was produced",
    placeholder: "when it ran, for example 2026-11-26T03:00:00Z" });
  const where = h("input", { "data-key": "src-import-where", maxlength: "120", autocomplete: "off", "aria-label": "Where it ran",
    placeholder: "where it ran, for example the build host" });
  const form = h("form", { class: "src-import", hidden: true, novalidate: true, "aria-label": "Import results produced elsewhere" },
    text, file, h("div", { class: "src-two" }, when, where),
    h("div", { class: "btns" }, button("Import results", { type: "submit", kind: "small primary", key: "src-import-ok", "data-control": "sources_import" })));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    e.stopPropagation();   // inside Project settings, its own form never submits the settings
    if (!text.value.trim()) { say("Paste the results or choose the file first.", "warning"); text.focus(); return; }
    write(box, pid, o, "/import-results", { text: text.value, produced_at: when.value.trim(), machine: where.value.trim(),
      name: file.files[0] ? file.files[0].name : "" }, (out) => "Imported: " + out.run.verdict + ".");
  });
  const runs = v.runs.length ? h("ul", { class: "src-runs" }, v.runs.map((r) => h("li", { "data-run": r.id },
    chip(r.verdict === "passed" ? "good" : r.verdict === "failed" ? "critical" : "nm", r.from === "imported" ? "download" : "play", r.verdict),
    " ", h("span", { "data-ud": "" }, r.line))))
    : emptyState("sources", null, { what: "No run of its own tests is kept yet.",
      how: v.roots.length ? "Run a test root here after your yes, or import the results of a run elsewhere."
        : "Import the results of a run elsewhere, or map the tests' roots first." });
  return h("div", null, v.root_note ? h("p", { class: "note info small" }, icon("info"), h("span", { "data-ud": "" }, v.root_note)) : null, runs,
    h("div", { class: "btns" }, button("Import results", { icon: "download", kind: "small", key: "src-import", "data-control": "sources_import",
      onclick: () => { form.hidden = !form.hidden; if (!form.hidden) text.focus(); } })), form);
}

function tracePart(v) {
  const t = v.trace;
  if (!t.rows.length) {
    return emptyState("sources", null, { what: "No requirement is read from the project's own source yet.",
      how: "Map where it keeps them (its rule files, its requirements file); each one's test then shows its latest result here." });
  }
  const shown = t.rows.slice(0, 40);
  return h("div", null, h("p", { class: "small", "data-ud": "" }, t.line),
    h("div", { class: "src-table-wrap" }, h("table", { class: "src-trace" },
      h("thead", null, h("tr", null, h("th", null, "Requirement"), h("th", null, "Where"), h("th", null, "Its test"), h("th", null, "Result"))),
      // On a phone each row stacks, its result first (sources.css), so no column is off the screen (FR-SRC2).
      h("tbody", null, shown.map((r) => h("tr", { "data-ref": r.ref || "" },
        h("td", { class: "src-req", "data-ud": "" }, (r.ref ? r.ref + " " : "") + r.title),
        h("td", { class: "src-where" }, h("code", null, r.path + ":" + r.line)),
        h("td", { class: "src-tests", "data-ud": "" }, r.tests.map((x) => x.name + " (" + x.status + ")").join(", ") || "none named"),
        h("td", { class: "src-res" }, chip(TONE[r.result] || "neutral", null, r.result, { tip: r.from || "" }))))))),
    t.rows.length > shown.length ? h("p", { class: "muted small" }, plural(t.rows.length - shown.length, "more requirement")) : null);
}

void S;
