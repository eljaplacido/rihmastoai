/* "AI tools in this project" and "Work on it from your IDE" (FR-AGC1, docs/guides/ide-and-rihmasto.md), on the
   overview of an adopted or attached project. The first card says how the team's AI coding tools are set up:
   its instructions (CLAUDE.md, AGENTS.md, Cursor rules and the rest), skills, subagents, slash commands, hooks
   and permissions and MCP servers, each with where it is; nothing found is run. The second gives ready-to-paste
   MCP configuration for Claude Code, Cursor and Codex pointing at Rihmasto's own MCP server, how a developer's
   change comes back, and the section to paste into their own AGENTS.md or CLAUDE.md: Rihmasto never writes
   into the person's folder. Both read GET /api/projects/<pid>/ai-tools, which records nothing. */

import { S, h, fill, icon, chip, api, enc, card, button, say, plural, AuthError } from "./core.js";

const GROUPS = [
  ["instructions", "Project instructions", "file-check"],
  ["skills", "Skills", "sparkles"],
  ["agents", "Subagents", "bot"],
  ["commands", "Slash commands", "terminal"],
  ["settings", "Hooks and permissions", "shield"],
  ["mcp", "MCP servers", "plug"],
  ["personal", "Personal settings", "user"],
];

async function copyText(text, what) {
  try { await navigator.clipboard.writeText(text); say(what + " copied.", "good"); } catch (e) { say("Copy it by hand from the box.", "warning"); }
}

function saveText(text, name) {
  const a = h("a", { href: URL.createObjectURL(new Blob([text], { type: "text/markdown" })), download: name, class: "vh" });
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

const path = (p) => h("code", { class: "ait-path" }, p);
// `code` in a line of text, as code.
const md = (text) => String(text).split(/`([^`]+)`/).map((part, i) => (i % 2 ? h("code", null, part) : part));

function line(e) {
  const bits = [path(e.path), h("span", { class: "ait-tool" }, e.tool || "")];
  if (e.sub === "instructions") bits.push(h("small", { class: "ait-why" }, (/^when /.test(e.applies_to) ? "Applies " : "Applies to ")
    + e.applies_to + (e.description ? ". " + e.description : "")));
  else if (e.sub === "skill") bits.push(h("small", { class: "ait-why" }, e.name + ": " + (e.description || "no description")
    + (e.files && e.files.length ? " · " + plural(e.files.length, "bundled file") + ", listed, never run" : "")));
  else if (e.sub === "agent") bits.push(h("small", { class: "ait-why" }, e.name + ": " + (e.description || "no description") + (e.tools ? " · tools: " + e.tools : "")));
  else if (e.sub === "command") bits.push(h("small", { class: "ait-why" }, e.name + (e.description ? ": " + e.description : "")));
  else if (e.sub === "settings") {
    const hooks = (e.hooks || []).map((x) => x.event + (x.matchers.length ? " on " + x.matchers.join(", ") : "")).join("; ") || "no hooks";
    const rules = Object.entries(e.permissions || {}).filter(([, v]) => v.length).map(([k, v]) => k + ": " + v.join(", ")).join(" · ");
    bits.push(h("small", { class: "ait-why" }, "Hooks: " + hooks + ". " + (rules || "No permission rules.")
      + (e.rules_not_shown ? " " + plural(e.rules_not_shown, "rule") + " not shown: may hold a secret." : "")
      + " Hook commands and environment values are never read or run."));
  } else if (e.sub === "mcp") {
    bits.push(h("small", { class: "ait-why" }, (e.servers || []).map((s) => s.name + " (" + s.transport
      + (s.command ? ", " + s.command : s.host ? ", " + s.host : "") + ")").join(", ") || "no servers"));
  } else if (e.sub === "personal") bits.push(h("small", { class: "ait-why" }, "One person's: listed, never read."));
  return h("li", { class: "ait-row" }, bits);
}

function toolsCard(ctx) {
  const groups = GROUPS.map(([key, label, ic]) => {
    const rows = ctx[key] || [];
    if (!rows.length) return null;
    return h("div", { class: "ait-group" }, h("h4", null, icon(ic), label, h("span", { class: "ait-n" }, String(rows.length))),
      h("ul", { class: "plain ait-list" }, rows.map(line)));
  });
  const stated = (ctx.stated || []).length ? h("div", { class: "ait-group" }, h("h4", null, icon("play"), "Commands the instructions state"),
    h("ul", { class: "plain ait-list" }, ctx.stated.map((s) => h("li", { class: "ait-row" }, h("span", { class: "ait-tool" }, s.kind),
      h("code", { class: "ait-path" }, s.command), h("small", { class: "ait-why" }, s.file + ", line " + s.line))))) : null;
  const notRead = (ctx.not_read || []).length ? h("p", { class: "small muted" }, "Not read: "
    + ctx.not_read.map((x) => x.path + " (" + x.not_read + ")").join("; ")) : null;
  const body = ctx.found ? [groups, stated, notRead,
    (ctx.skills || []).length || (ctx.mcp || []).length ? h("p", { class: "note ait-note" }, icon("info"), h("span", null, ctx.catalogue_note)) : null]
    : [h("p", { class: "muted" }, "No AI tool configuration was found in the repository: no CLAUDE.md, AGENTS.md, Cursor rules, skills or MCP servers.")];
  return card({ title: "AI tools in this project", icon: "bot", id: "ait", cls: "ait-card", dataId: "ai_tools",
    info: "How the team's AI coding tools are set up, read by rule from the committed repository. Rihmasto's panels and builders follow the same conventions; nothing found is ever run." },
  h("div", { "data-control": "ai_tools" }, body, h("p", { class: "small muted" }, "Read from " + (ctx.read_from || "the repository") + ".")));
}

function snippet(label, text, key) {
  return h("div", { class: "ait-snip" },
    h("div", { class: "ait-snip-h" }, h("span", null, label), button("Copy", { icon: "copy", kind: "small quiet", key: "ide-copy:" + key,
      onclick: () => copyText(text, label) })),
    h("pre", { class: "code snippet", tabindex: "0", "aria-label": label }, text));
}

function ideCard(out) {
  const ide = out.ide;
  const who = ide.signed_as.person === "<your name>" ? h("p", { class: "small muted" }, icon("user"),
    " Say who you are in the person menu to have your name in it; until then it reads <your name>.") : null;
  const tools = [
    ["claude", "Claude Code", [snippet(ide.claude_code.file + " in your clone", JSON.stringify(ide.claude_code.json, null, 2), "claude-json"),
      snippet("or from the command line", ide.claude_code.command, "claude-cmd")]],
    ["cursor", "Cursor", [snippet(ide.cursor.file, JSON.stringify(ide.cursor.json, null, 2), "cursor-json")]],
    ["codex", "Codex", [snippet(ide.codex.file, ide.codex.toml, "codex-toml")]],
  ].map(([key, label, body], i) => h("details", { class: "ait-ide", open: i === 0 || null, "data-key": "ide:" + key },
    h("summary", null, label), body));
  const section = out.section;
  return card({ title: "Work on it from your IDE", icon: "code", id: "ide", cls: "ait-card", dataId: "ide_setup",
    info: "The IDE and the terminal are the inner loop; Rihmasto is the outer loop. They meet in the repository, over Rihmasto's MCP server and in your conventions file." },
  h("div", { "data-control": "ide_setup" },
    h("p", { class: "small" }, "Point your IDE's agent at Rihmasto's MCP server: it sees the contract and what waits on a decision, and can file a change. It decides nothing."),
    who, tools, h("p", { class: "small muted" }, ide.note),
    h("h4", { class: "ait-sub" }, "How your change comes back"),
    h("ul", { class: "ait-back" }, out.comes_back.map((x) => h("li", null, md(x)))),
    h("h4", { class: "ait-sub" }, out.section_title),
    h("p", { class: "small" }, "Paste it into your project's AGENTS.md or CLAUDE.md yourself: Rihmasto never writes into your folder or repository."),
    h("div", { class: "chips", "data-control": "ide_section" },
      button("Copy the section", { icon: "copy", kind: "small", key: "ide-section:copy", onclick: () => copyText(section, "The section") }),
      button("Download it", { icon: "download", kind: "small quiet", key: "ide-section:download", onclick: () => saveText(section, out.section_file) })),
    h("details", { class: "ait-ide" }, h("summary", null, "Show the section"),
      h("pre", { class: "code snippet", tabindex: "0", "aria-label": out.section_title }, section))));
}

// The two cards, filled in once the project's repository is read; null for a project Rihmasto builds itself.
export function aiTools(p) {
  const kind = p.meta.source_kind;
  if (kind !== "adopted" && kind !== "attached") return null;
  const holder = h("div", { class: "two ait", "aria-busy": "true" }, h("p", { class: "muted small" }, "Reading how the AI tools here are set up…"));
  const q = "?persona=" + enc(S.persona) + "&person=" + enc((S.person || "").trim());
  api("GET", "/api/projects/" + enc(p.meta.id) + "/ai-tools" + q).then((out) => {
    holder.removeAttribute("aria-busy");
    if (!out.applies) { fill(holder); holder.hidden = true; return; }
    fill(holder, toolsCard(out.context), ideCard(out));
  }).catch((e) => {
    if (e instanceof AuthError) return;
    holder.removeAttribute("aria-busy");
    fill(holder, h("p", { class: "muted small" }, chip("warning", "alert", "Not read"), " " + e.message));
  });
  return holder;
}

// The material map's group for these files: "How AI tools here are set up" (scan.js).
export const SUB_LABEL = { instructions: "project instructions", skill: "skill", skill_file: "a skill's bundled file",
  agent: "subagent", command: "slash command", settings: "hooks and permissions", mcp: "MCP servers", personal: "personal settings" };
