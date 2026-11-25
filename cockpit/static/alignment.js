/* The Alignment view: what a team's repository already holds (its specs, criteria, tests, tasks, decisions,
   API contracts) and how Rihmasto would take it (kernel/alignment.py). Every item is proposed, never applied:
   Accept, Edit or Reject it, or accept a group's open items at once. Accepting writes into the project's
   contract and records, signed with your name; the repository is never written. Suggested changes for the
   repository are text to copy or a patch to download. Read the repository again after it changed: the drift
   says what is new, changed or removed. */

import { pick, viewWord, emptyState } from "./words.js";
import { S, h, icon, chip, api, say, signed, needPerson, enc, plural, cap, short, ago, card, button, empty, link,
  personBadge } from "./core.js";

const STATUS = { open: ["info", "dashed", "To decide"], accepted: ["good", "check-circle", "Accepted"],
  rejected: ["neutral", "x-circle", "Rejected"], changed: ["warning", "alert", "Changed since accepted"] };
const EDITABLE = { requirements: [["id", "Rihmasto id"], ["statement", "Statement"]],
  criteria: [["given", "Given"], ["when", "When"], ["then", "Then"]], tasks: [["title", "Title"]],
  decisions: [["title", "Title"], ["status", "Status"]], trace: [], contracts: [], gaps: [] };
const GROUP_ICON = { requirements: "file-check", criteria: "check-circle", trace: "link", tasks: "list",
  decisions: "flag", contracts: "plug", gaps: "alert" };
const SHOWN = 40;

function statusChip(s) { const t = STATUS[s] || ["neutral", "info", s]; return chip(t[0], t[1], t[2]); }
function base(pid) { return "/api/projects/" + enc(pid) + "/repo-alignment"; }
function where(src) {
  if (!src || !src.path) return null;
  return h("span", { class: "mono small al-src" }, src.path + (src.lines && src.lines[0] ? ":" + src.lines[0] : ""));
}

async function decide(pid, items, verdict, kit, btn, edits) {
  if (!needPerson()) return;
  await kit.run(btn, btn.closest("li, section") || btn.parentNode, async () => {
    const out = await api("POST", base(pid) + "/decide", Object.assign({ items, verdict, edits: edits || {} }, signed()));
    say((verdict === "accept" ? "Accepted " : "Rejected ") + plural(out.items.length, "item") + ", signed by "
      + S.person.trim() + (out.contract ? ". The contract is now " + short(out.contract) + "." : "."), "good");
    await kit.settle(['[data-key="al-scan"]']);
  });
}

function scanCard(pid, a, kit) {
  const what = pick("the code", "the repository");
  const go = button(a.scanned ? "Read " + what + " again" : "Read " + what, { icon: "refresh", kind: "small primary",
    key: "al-scan", "data-control": "align_scan" });
  go.addEventListener("click", () => {
    if (!needPerson()) return;
    kit.run(go, go.parentNode, async () => {
      const out = await api("POST", base(pid) + "/scan", signed());
      say("Scan " + out.scan.n + " recorded, signed by " + S.person.trim() + ": " + out.summary.text + ".", "good");
      await kit.settle(['[data-key="al-scan"]']);
    });
  });
  const s = a.scan;
  return card({ title: pick("The team's code", "Your repository"), icon: "merge", id: "al-run",
    info: "Rihmasto reads the repository's committed revision by rule, with no model, and runs nothing it finds. It "
      + "recognises spec-kit, Kiro, BMAD and agent-os specs, PRDs and RFCs, user stories, Gherkin and EARS criteria, ADRs, "
      + "OpenAPI, GraphQL and protobuf contracts, test suites, task lists, CI/CD, quality tools and AI tools. A file "
      + "that may hold a secret is never read." },
  h("div", { class: "btns" }, go),
  s ? h("p", { class: "small" }, "Scan " + s.n + " of ", h("span", { class: "mono" }, short(s.revision)), ", ", ago(s.at), " by ",
    personBadge(s.by.person, s.by.persona), ".") : null,
  a.structure ? h("p", { class: "small muted" }, "Found: " + ((a.structure.conventions || []).join(", ") || "no convention recognised")
    + ". Nothing is written to your repository.") : null);
}

function teach() {
  return h("div", { class: "empty teach", "data-empty": "align" }, h("p", { class: "empty-t" }, pick("Not compared yet.", "Not aligned yet.")),
    h("p", { class: "empty-how" }, pick("Read the code to see what it already holds: its requirements and how they are tested, its tasks "
      + "and decisions, and the gaps between them. Each becomes a proposal you accept, edit or reject; what you accept joins this "
      + "project's agreed checks, signed with your name.",
    "Read the repository to see what it already holds: its requirements and acceptance criteria, which tests "
      + "check them, its tasks, decisions and API contracts, and the gaps between them. Each becomes a proposal you accept, "
      + "edit or reject; what you accept goes into this project's contract, signed with your name.")),
    h("p", { class: "muted small" }, pick("The code stays the team's: suggested changes are text to copy or a file to download.",
      "Your repository stays yours: suggested changes for it are text to copy or a patch to download, and you keep working in your IDE.")));
}

function summaryCard(a) {
  const st = a.status || {};
  const d = a.drift || {};
  const drift = d.since ? h("p", { class: "small", id: "al-drift" }, "Since scan " + d.since + ": " + plural(d.new.length, "new item")
    + ", " + d.changed.length + " changed, " + d.removed.length + " removed.") : null;
  return card({ title: a.summary.text, icon: "gauge", id: "al-sum", cls: "al-sum" },
    h("p", { class: "btns" }, ["open", "changed", "accepted", "rejected"].filter((k) => st[k])
      .map((k) => chip(STATUS[k][0], STATUS[k][1], st[k] + " " + STATUS[k][2].toLowerCase()))),
    drift,
    d.removed && d.removed.length ? h("details", { class: "as-more" }, h("summary", null, "Removed from the repository"),
      h("ul", { class: "plain as-list" }, d.removed.map((r) => h("li", { class: "as-row" }, h("span", { class: "mono small" }, r.id),
        " " + r.title + (r.decided ? " (it was " + r.decided + "ed: the contract keeps what was accepted; a requirement leaves it "
          + "through the change loop)" : ""))))) : null);
}

function editForm(pid, item, kit) {
  const fields = EDITABLE[item.group] || [];
  const inputs = fields.map(([k, label]) => {
    const id = "al-e-" + item.id + "-" + k;
    const big = k === "statement" || k === "then";
    const el = h(big ? "textarea" : "input", { id, name: k, rows: big ? 3 : null, "data-key": "edit:" + item.id + ":" + k });
    el.value = String(item.proposal[k] === undefined || item.proposal[k] === null ? "" : item.proposal[k]);
    return [k, el, h("div", { class: "field" }, h("label", { for: id }, label), el)];
  });
  const save = button("Accept with changes", { icon: "check", kind: "small primary", type: "submit", key: "al-save:" + item.id });
  const form = h("form", { class: "form al-edit", novalidate: true, "aria-label": "Edit " + item.title },
    inputs.map((x) => x[2]), h("div", { class: "btns" }, save));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const changes = {};
    inputs.forEach(([k, el]) => { if (el.value.trim() !== String(item.proposal[k] || "")) changes[k] = el.value.trim(); });
    decide(pid, [item.id], "accept", kit, save, Object.keys(changes).length ? { [item.id]: changes } : {});
  });
  return form;
}

function itemRow(pid, item, kit) {
  const live = item.status === "open" || item.status === "changed";
  const row = h("li", { class: "as-row al-row", "data-id": item.id, "data-status": item.status });
  const acts = [];
  if (live) {
    const ok = button("Accept", { icon: "check", kind: "small", key: "al-accept:" + item.id, "data-control": "align_decide",
      aria: "Accept " + item.title });
    ok.addEventListener("click", () => decide(pid, [item.id], "accept", kit, ok));
    acts.push(ok);
    if ((EDITABLE[item.group] || []).length) {
      const ed = button("Edit", { icon: "edit", kind: "small ghost", key: "al-edit:" + item.id, aria: "Edit " + item.title });
      ed.addEventListener("click", () => {
        const open = row.querySelector(".al-edit");
        if (open) { open.remove(); ed.setAttribute("aria-expanded", "false"); return; }
        row.append(editForm(pid, item, kit));
        ed.setAttribute("aria-expanded", "true");
        const first = row.querySelector(".al-edit input, .al-edit textarea");
        if (first) first.focus();
      });
      acts.push(ed);
    }
    const no = button(item.status === "changed" ? "Keep as accepted" : "Reject", { icon: "x", kind: "small ghost",
      key: "al-reject:" + item.id, aria: (item.status === "changed" ? "Keep as accepted " : "Reject ") + item.title });
    no.addEventListener("click", () => decide(pid, [item.id], "reject", kit, no));
    acts.push(no);
  }
  const d = item.decision;
  row.append(...[
    h("div", { class: "as-h" }, h("b", { class: "al-t" }, item.title), statusChip(item.status),
      item.confidence !== undefined ? chip(item.weak ? "warning" : "accent", null, Math.round(item.confidence * 100) + "% " + item.basis,
        { tip: "How sure the trace is, and what it rests on" }) : null),
    h("p", { class: "small" }, h("span", { class: "muted" }, "Adds: "), item.adds),
    h("p", { class: "small muted" }, cap(item.why) + ". ", where(item.source)),
    d ? h("p", { class: "small muted" }, cap(d.verdict) + "ed by ", personBadge(d.person, d.persona), " " + ago(d.at)
      + (d.edited ? ", with changes to " + d.edited.join(", ") : "") + ".") : null,
    acts.length ? h("div", { class: "btns al-acts" }, acts) : null].filter(Boolean));
  return row;
}

function groupCard(pid, g, kit) {
  const open = g.items.filter((i) => i.status === "open");
  const bulk = open.length > 1 ? button("Accept all " + open.length + " open", { icon: "check-circle", kind: "small",
    key: "al-bulk:" + g.id, "data-control": "align_bulk", aria: "Accept all " + open.length + " open " + g.label.toLowerCase() }) : null;
  if (bulk) bulk.addEventListener("click", () => decide(pid, open.map((i) => i.id), "accept", kit, bulk));
  const rows = g.items.map((i) => itemRow(pid, i, kit));
  return card({ title: g.label, icon: GROUP_ICON[g.id], id: "al-g-" + g.id, cls: "al-group",
    tools: h("span", { class: "btns" }, chip(g.open ? "info" : "good", g.open ? "dashed" : "check-circle", g.open + " to decide"), bulk) },
  g.items.length ? h("ul", { class: "plain as-list" }, rows.slice(0, SHOWN)) : h("p", { class: "muted small" }, "Nothing found."),
  rows.length > SHOWN ? h("details", { class: "as-more" }, h("summary", null, plural(rows.length - SHOWN, "more item")),
    h("ul", { class: "plain as-list" }, rows.slice(SHOWN))) : null);
}

function save(name, text) {
  const a = h("a", { href: URL.createObjectURL(new Blob([text], { type: "text/plain" })), download: name });
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

function suggestionRow(s) {
  const body = s.patch || s.text;
  const copy = button("Copy", { icon: "copy", kind: "small", key: "al-copy:" + s.id, "data-control": "align_suggestions",
    aria: "Copy " + s.title });
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(body); say("Copied. Apply it in your repository yourself.", "good"); }
    catch (e) { say("Copy it by hand from the box.", "warning"); }
  });
  const dl = button(s.patch ? "Download the patch" : "Download", { icon: "download", kind: "small ghost", key: "al-dl:" + s.id,
    aria: (s.patch ? "Download the patch for " : "Download ") + s.title });
  dl.addEventListener("click", () => { save(s.file_name, body); say("Saved " + s.file_name + ": nothing was written to your repository.", "good"); });
  return h("li", { class: "as-row", "data-id": s.id },
    h("div", { class: "as-h" }, h("b", null, s.title), s.path ? h("span", { class: "mono small al-src" }, s.path) : null),
    h("p", { class: "small muted" }, cap(s.why) + "."),
    h("pre", { class: "al-pre", tabindex: "0", "aria-label": s.title }, body),
    h("div", { class: "btns" }, copy, dl));
}

function suggestionsCard(a) {
  const ss = a.suggestions || [];
  return card({ title: "Suggested changes for your repository", icon: "code", id: "al-sug",
    info: "What your repository could change to align: criterion ids in test names, task list entries, a CI job that runs "
      + "the tests, tests to write, criteria to restate, specs to bring up to date. Rihmasto never writes them there: copy "
      + "them or download a patch, and apply them in your IDE (git apply)." },
  ss.length ? h("ul", { class: "plain as-list" }, ss.map(suggestionRow)) : h("p", { class: "muted small" }, "Nothing to suggest."));
}

function ideCard(a) {
  if (!a.ide || !a.ide.length) return null;
  const text = a.ide.join("\n");
  const copy = button("Copy for your IDE agent", { icon: "copy", kind: "small", key: "al-ide" });
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(text); say("Copied: paste it into your AGENTS.md or CLAUDE.md yourself.", "good"); }
    catch (e) { say("Copy it by hand from the box.", "warning"); }
  });
  return card({ title: "Continue in your IDE", icon: "terminal", id: "al-ide",
    info: "What was accepted into the contract and the gaps still open, for your IDE agent. The repo gate checks your "
      + "commits against the accepted criteria (rihmasto repo gate), and `rihmasto align <pid>` shows the same here." },
  h("pre", { class: "al-pre", tabindex: "0", "aria-label": "For your IDE agent" }, text), h("div", { class: "btns" }, copy));
}

export function viewAlign(p, ctx, kit) {
  const pid = p.meta.id;
  const a = ctx.align;
  const head = kit.viewHead(viewWord("align", "Alignment"), pick("What does the existing code already hold, and how does it match the plan?",
    "What does your repository already hold, and how would Rihmasto take it?"));
  if (!a || a.error) return h("div", null, head, empty("merge", (a && a.error) || "The alignment could not be read."));
  if (!a.applies) {
    return h("div", null, head, emptyState("align", null, { icon: "merge", what: pick("Rihmasto builds this project's code itself, so there is no team code to compare.",
      "Not applicable: " + a.why), how: pick("This view applies when a project brings in existing code (adopt or attach, from New project).",
      "Alignment applies to an adopted or attached repository (New project, adopt or attach).") }));
  }
  const out = h("div", { class: "align" }, head, scanCard(pid, a, kit));
  if (!a.scanned) { out.append(teach()); return out; }
  out.append(summaryCard(a));
  a.groups.forEach((g) => out.append(groupCard(pid, g, kit)));
  out.append(suggestionsCard(a));
  const ide = ideCard(a);
  if (ide) out.append(ide);
  return out;
}

// On an adopted or attached project's Overview: the step right after adoption, until the repository is aligned.
export function alignCallout(p) {
  const kind = p.meta.source_kind;
  if (kind !== "adopted" && kind !== "attached") return null;
  const box = h("div", { class: "section al-callout", hidden: true });
  api("GET", base(p.meta.id)).then((a) => {
    if (!a || !a.applies || a.scanned) return;
    box.append(h("p", { class: "note" }, icon("merge"), h("span", null, pick("Next: compare this project with what the team's code already "
      + "holds (its requirements, tests and tasks). Nothing is written there. ", "Next: align this project with your repository's own "
      + "specs, tests and tasks. Nothing is written there. ")), h("a", { href: link(p.meta.id, "align") }, "Open " + viewWord("align", "Alignment"))));
    box.hidden = false;
  }).catch(() => {});
  return box;
}
