/* The "Scan the folder" step of New project (FR-MAT1, docs/guides/inputs.md): before anything is sent or
   created, the folder's material map shows what happens to each file, grouped: read, summarised, listed,
   skipped with its reason, and what the person unticked. Unticking a file scans again without it, so what
   the step shows is what would be sent. Only then does the dialog create the project or adopt it. */

import { S, h, fill, icon, chip, api, say, AuthError } from "./core.js";
import { SUB_LABEL } from "./aitools.js";

// The files the folder's AI tools read (CLAUDE.md, AGENTS.md, Cursor rules, skills, MCP servers: FR-AGC1) have
// a group of their own, first: they are the project's conventions, and the request reads them right after the README.
const GROUPS = [
  ["agent", "How AI tools here are set up", "bot", "info", true],
  ["read", "Read in full", "check-circle", "good", true],
  ["summarised", "Summarised", "layers", "info", true],
  ["unticked", "Unticked by you", "x", "neutral", true],
  ["listed", "Listed only, not read", "list", "neutral", false],
  ["skipped", "Skipped", "shield", "warning", true],
];
const KIND = { brief: "brief or spec", plan: "plan", review: "review or comments", handover: "handover", notes: "notes",
  log: "deploy or run log", data: "data", slides: "slides", code: "code", other: "other", agent: "agent context" };
const ACTION = { read: "read in full", summarised: "summarised", listed: "listed only", skipped: "skipped" };
const kindOf = (r) => (r.kind === "agent" ? (SUB_LABEL[r.sub] || KIND.agent) + ", " + (ACTION[r.action] || r.action) : KIND[r.kind] || r.kind);

// A source that is a folder on this machine, not text or a git address: one line, a drive, a share, / or ~.
export function looksLikeFolder(text) {
  const t = String(text || "").trim();
  return !!t && !/[\r\n]/.test(t) && !/:\/\//.test(t) && /^([A-Za-z]:[\\/]|\\\\|\/|~[\\/]?)/.test(t);
}

function groupOf(row, unticked) {
  if (unticked.has(row.path)) return "unticked";
  return row.kind === "agent" ? "agent" : row.action;
}

const n = (x) => Number(x || 0).toLocaleString("en");

export function scanStep(opts) {
  const o = opts || {};
  const unticked = new Set(o.exclude || []);   // a walkthrough's full map opens with what was unticked before
  let source = "";
  let out = null;
  let timer = 0;
  const head = h("h3", { id: "scan-h", class: "scan-h" }, icon("search"), "What Rihmasto would read");
  const summary = h("p", { class: "scan-sum small", role: "status", "aria-live": "polite" });
  const body = h("div", { class: "scan-body" });
  const el = h("section", { class: "scan-step", "aria-labelledby": "scan-h", "data-control": "scan_source", hidden: true },
    head, summary, body);

  function row(r, group) {
    const kind = h("span", { class: "scan-kind" }, kindOf(r));
    const why = r.why ? h("small", { class: "scan-why" }, r.why) : null;
    const size = r.chars ? h("small", { class: "scan-size" }, n(r.chars) + " chars") : null;
    const name = h("span", { class: "scan-path" }, r.path);
    if (group === "skipped" || (group === "agent" && r.action === "skipped")) {
      return h("li", { class: "scan-row" }, h("span", { class: "scan-label" }, h("span", { class: "scan-mark" }, icon("x-circle")),
        h("span", { class: "scan-text" }, name, kind, why)));
    }
    const box = h("input", { type: "checkbox", "data-path": r.path, "aria-label": (group === "unticked" ? "Send " : "Do not send ") + r.path });
    box.checked = group !== "unticked";
    box.addEventListener("change", () => {
      if (box.checked) unticked.delete(r.path); else unticked.add(r.path);
      clearTimeout(timer);
      timer = setTimeout(() => rescan(r.path).catch((e) => { if (!(e instanceof AuthError)) say(e.message, "critical"); }), 250);
    });
    return h("li", { class: "scan-row" }, h("label", { class: "scan-label" }, box, h("span", { class: "scan-text" }, name, kind, size, why)));
  }

  function render() {
    const mp = out.map;
    const t = mp.totals;
    const to = out.send_to || {};
    const where = to.endpoint ? " to the " + to.role + " role's endpoint “" + to.endpoint + "” (" + (to.host || "?") + ", " + (to.local ? "local" : "hosted") + ")" : "";
    fill(summary, n(t.read) + " read, " + n(t.summarised) + " summarised, " + n(t.listed) + " listed, " + n(t.skipped) + " skipped. "
      + n(t.chars) + " of " + n(t.budget) + " characters would be sent" + where + " when you go on. Nothing has been sent.");
    const rows = mp.files.map((r) => [r, groupOf(r, unticked)]);
    const groups = GROUPS.map(([key, label, ic, tone, open]) => {
      const mine = rows.filter(([, g]) => g === key);
      const code = key === "listed" ? mine.filter(([r]) => r.kind === "code" && /^code:/.test(r.why)) : [];
      const shown = mine.filter((x) => !code.includes(x));
      if (!mine.length) return null;
      return h("details", { class: "scan-group scan-" + key, open: open || null },
        h("summary", null, chip(tone, ic, label), h("span", { class: "scan-count" }, n(mine.length))),
        h("ul", { class: "scan-list", role: "list" }, shown.map(([r]) => row(r, key)),
          code.length ? h("li", { class: "scan-row scan-code" }, h("span", { class: "scan-label" }, h("span", { class: "scan-mark" }, icon("code")),
            h("span", { class: "scan-text" }, n(code.length) + " code files: counted in the code inventory, not read"))) : null));
    });
    const notes = [];
    if (!out.code && o.adopting) notes.push(h("div", { class: "proposal warn scan-nocode", role: "alert" }, icon("alert"),
      h("div", null, h("b", null, "This folder holds no code, only documents."),
        h("p", { class: "small" }, "There is nothing to adopt. You can start a new project from it instead: its documents become the material."),
        o.onNoCode ? h("button", { type: "button", class: "btn small", "data-control": "scan_as_material", onclick: () => o.onNoCode(source) },
          icon("plus"), "Start a new project from it") : null)));
    if (o.confidential && o.confidential() && out.local_only && (o.adopting ? out.local_only.all : out.local_only.new)) {
      notes.push(h("div", { class: "proposal warn", role: "alert" }, icon("shield"),
        h("div", null, h("b", null, "Confidential: a role's model is hosted."),
          h("p", { class: "small" }, o.adopting ? out.local_only.all : out.local_only.new))));
    }
    const after = [];
    if (mp.cut.length) after.push(h("ul", { class: "scan-cut small muted" }, mp.cut.slice(0, 12).map((c) => h("li", null, "Cut: " + c)),
      mp.cut.length > 12 ? h("li", null, "Cut: " + n(mp.cut.length - 12) + " more files for the budget, each listed above with why.") : null));
    if (out.git && o.adopting) after.push(h("p", { class: "small muted" }, "A git repository: its committed files are adopted, and its documents are scanned as context."));
    else if (o.adopting && out.code) after.push(h("p", { class: "small muted" }, "Not a git repository: the files above that are not skipped are copied into a baseline repository in the factory. Your folder is never changed."));
    fill(body, notes, groups, after);
  }

  async function rescan(focusPath) {
    const person = (o.person ? o.person() : "") || S.person.trim();
    out = await api("POST", "/api/source/preview", { source, exclude: [...unticked], person, persona: S.persona });
    render();
    if (focusPath) {
      const back = body.querySelector('input[data-path="' + CSS.escape(focusPath) + '"]');
      if (back) back.focus();
    }
    if (o.onScanned) o.onScanned(out);
  }

  return {
    el,
    get result() { return out; },
    get source() { return source; },
    exclude: () => [...unticked],
    async scan(folder) {
      if (source && folder !== source) unticked.clear();
      source = folder;
      el.hidden = false;
      fill(summary, "Scanning the folder…");
      fill(body);
      await rescan(null);
      return out;
    },
    reset() {
      source = "";
      out = null;
      unticked.clear();
      el.hidden = true;
      fill(summary);
      fill(body);
    },
  };
}
