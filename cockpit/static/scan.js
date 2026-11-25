/* The "Scan the folder" step of New project (FR-MAT1, FR-RPJ1, docs/guides/inputs.md): before anything is sent
   or created, the folder's material map shows what happens to each file, grouped: read, summarised, listed,
   skipped with its reason, and what the person unticked. Unticking a file scans again without it, so what
   the step shows is what would be sent. A long scan shows how far it is and can be stopped; a refusal or an
   error is shown, with what to do about it. What the folder is (a repository with uncommitted work, one adopted
   already, a workspace of several, documents only) is said by feedin.js, with its choices. */

import { S, h, fill, icon, chip, api, say, AuthError } from "./core.js";
import { SUB_LABEL } from "./aitools.js";
import { adoptNotices, progressLine, refusalPanel } from "./feedin.js";
import { liveStrip } from "./progress.js";

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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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
  let running = null;          // the scan in progress: its id, for Cancel
  // What the person chose about what the folder is (feedin.js): the last commit or the working copy, adopting
  // again, how it is used, tracking documents, a workspace's repositories.
  const st = { take: "commit", again: false, usage: null, track: false, each: false, repos: new Set() };
  const head = h("h3", { id: "scan-h", class: "scan-h" }, icon("search"), "What Rihmasto would read");
  const summary = h("p", { class: "scan-sum small", role: "status", "aria-live": "polite" });
  const body = h("div", { class: "scan-body" });
  const el = h("section", { class: "scan-step", "aria-labelledby": "scan-h", "data-control": "scan_source", hidden: true },
    head, summary, body);
  const changed = () => { if (o.onScanned) o.onScanned(out); };

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

  // Code and housekeeping files are counted on one line each, not listed one by one.
  const counted = (mine, test, ic, said) => {
    const these = mine.filter(([r]) => test(r));
    return [these, these.length ? h("li", { class: "scan-row scan-code" }, h("span", { class: "scan-label" }, h("span", { class: "scan-mark" }, icon(ic)),
      h("span", { class: "scan-text" }, n(these.length) + said))) : null];
  };

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
      if (!mine.length) return null;
      const [code, codeLine] = key === "listed" ? counted(mine, (r) => r.kind === "code" && /^code:/.test(r.why), "code", " code files: counted in the code inventory, not read") : [[], null];
      const [kept, keptLine] = key === "listed" ? counted(mine, (r) => !!r.housekeeping, "list",
        " housekeeping files (ignore lists, editor settings, checksums, example settings, lockfiles): listed, not read") : [[], null];
      const shown = mine.filter((x) => !code.includes(x) && !kept.includes(x));
      return h("details", { class: "scan-group scan-" + key, open: open || null },
        h("summary", null, chip(tone, ic, label), h("span", { class: "scan-count" }, n(mine.length))),
        h("ul", { class: "scan-list", role: "list" }, shown.map(([r]) => row(r, key)), codeLine, keptLine));
    });
    const notes = adoptNotices(out, st, {
      adopting: !!o.adopting, confidential: o.confidential ? o.confidential() : false,
      onNoCode: o.onNoCode ? () => o.onNoCode(source) : null,
      onChange: () => { render(); changed(); },
      rescan: () => rescan(null),
    });
    const after = [];
    if (mp.cut.length) after.push(h("ul", { class: "scan-cut small muted" }, mp.cut.slice(0, 12).map((c) => h("li", null, "Cut: " + c)),
      mp.cut.length > 12 ? h("li", null, "Cut: " + n(mp.cut.length - 12) + " more files for the budget, each listed above with why.") : null));
    if (out.git && o.adopting) {
      after.push(h("p", { class: "small muted" }, st.take === "working_copy" ? "A git repository: its working copy as it is now is copied into a baseline repository in the factory. Your folder is never changed."
        : "A git repository: its last commit is adopted, and its documents are scanned as context."));
    } else if (o.adopting && out.code) after.push(h("p", { class: "small muted" }, "Not a git repository: the files above that are not skipped are copied into a baseline repository in the factory. Your folder is never changed."));
    fill(body, notes, groups, after);
  }

  // A refused or failed scan says why, in the step, instead of staying on "Scanning".
  function stopped(text, offer) {
    out = null;
    fill(summary, "The folder was not scanned.");
    fill(body, refusalPanel(text, offer, { retry: () => rescan(null) }));
    changed();
  }

  async function rescan(focusPath) {
    const person = (o.person ? o.person() : "") || S.person.trim();
    const started = await api("POST", "/api/source/scan", { source, exclude: [...unticked], person, persona: S.persona, take: st.take });
    let scan = started.scan;
    running = scan.id || null;
    const line = h("span", { class: "scan-progress", "aria-live": "off" });   // ticks quietly; the result is announced
    if (scan.state === "running") {
      fill(summary, line, " ", h("button", { type: "button", class: "btn small", "data-control": "scan_cancel", onclick: () => cancel() },
        icon("x"), h("span", { class: "lbl" }, "Cancel the scan")));
    }
    const tiles = liveStrip({ title: "Scanning the folder", icon: "search", attrs: { "data-control": "scan_progress" } });   // FR-PRG1
    if (scan.state === "running") fill(body, tiles.el);
    while (scan.state === "running") {
      fill(line, progressLine(scan.progress));
      tiles.set(scan.live);
      await sleep(350);
      if (running !== scan.id) return out;           // a newer scan, or a reset, took over
      scan = (await api("GET", "/api/source/scan/" + encodeURIComponent(scan.id))).scan;
    }
    running = null;
    if (scan.state === "refused" || scan.state === "failed") { stopped(scan.error, scan.offer); return out; }
    if (scan.state === "cancelled") { stopped("You cancelled the scan. Nothing was read or sent.", null); return out; }
    out = scan.result;
    if (!st.usage && out.usage) st.usage = out.usage.maturity;
    render();
    if (focusPath) {
      const back = body.querySelector('input[data-path="' + CSS.escape(focusPath) + '"]');
      if (back) back.focus();
    }
    changed();
    return out;
  }

  async function cancel() {
    const id = running;
    if (!id) return;
    const person = (o.person ? o.person() : "") || S.person.trim();
    await api("POST", "/api/source/scan/" + encodeURIComponent(id) + "/cancel", { person, persona: S.persona }).catch(() => null);
  }

  return {
    el,
    get result() { return out; },
    get source() { return source; },
    get choice() { return st; },
    exclude: () => [...unticked],
    async scan(folder) {
      if (folder !== source) { unticked.clear(); Object.assign(st, { take: "commit", again: false, usage: null, track: false, each: false }); st.repos.clear(); }
      source = folder;
      el.hidden = false;
      fill(summary, "Scanning the folder…");
      fill(body);
      return rescan(null);
    },
    reset() {
      source = "";
      out = null;
      running = null;
      unticked.clear();
      Object.assign(st, { take: "commit", again: false, usage: null, track: false, each: false });
      st.repos.clear();
      el.hidden = true;
      fill(summary);
      fill(body);
    },
  };
}
