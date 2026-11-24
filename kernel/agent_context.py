"""How the AI coding tools of a project are set up: its agent context, recognised by rule (FR-AGC1,
docs/guides/ide-and-rihmasto.md).

A team that works in Claude Code, Cursor, Copilot, Windsurf, Cline, Gemini or Codex leaves its conventions
in the repository for those tools. This module recognises them by their paths, with no model:

- **project instructions**: `CLAUDE.md` and `AGENTS.md` at any level, `GEMINI.md`, `.cursorrules`,
  `.cursor/rules/*.mdc` (their frontmatter: description, globs, alwaysApply), `.github/copilot-instructions.md`
  and `.github/instructions/*.instructions.md` (applyTo), `.windsurfrules`, `.windsurf/rules/*.md`,
  `.clinerules` (a file or a folder);
- **skills** (`.claude/skills/<name>/SKILL.md`: name, description, and the files bundled with it, listed),
  **subagents** (`.claude/agents/*.md`), **slash commands** (`.claude/commands/**`, `.cursor/commands/**`);
- **hooks and permissions** (`.claude/settings.json`): the hook events and matchers and the allow, ask and
  deny rule names, never a hook's command, an environment value or a rule that looks like a secret;
- **MCP servers** (`.mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json`): each server's name, transport, its
  command's name or its URL's host, never its arguments, environment values or headers;
- **personal settings** (`.claude/settings.local.json`, `CLAUDE.local.md`) are one person's, not the
  project's: listed, never read.

Nothing found here is ever run: not a hook, a command, a skill's script or an MCP server. Skills and MCP
servers are listed as candidates for Rihmasto's own catalogue only, offered to Rihmasto's cells after a
person approves. A file whose text holds a credential is not read (kernel/material_kinds.py).
kernel/agent_context_use.py puts what is found to use: intake, the assessment, the baseline, the builder.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from kernel import material_kinds as mk
from kernel import material_read as mr

SCHEMA = "rihmasto.agent-context/1"
KIND = "agent"                       # the material map's kind for these files
SUB_LABEL = {"instructions": "project instructions", "skill": "skill", "skill_file": "a skill's bundled file",
             "agent": "subagent", "command": "slash command", "settings": "hooks and permissions",
             "mcp": "MCP servers", "personal": "personal settings"}
GROUPS = ("instructions", "skills", "agents", "commands", "settings", "mcp", "personal")
GROUP_OF = {"instructions": "instructions", "skill": "skills", "agent": "agents", "command": "commands",
            "settings": "settings", "mcp": "mcp", "personal": "personal"}
MAX_TEXT = 256 * 1024                # an instruction file larger than this is listed, not read
MAX_FILES = 400
MAX_ROWS = 200
PERSONAL_WHY = "personal settings: one person's, not the project's; never read"
CATALOGUE_NOTE = ("Skills and MCP servers found here are candidates for Rihmasto's own catalogue only: they can be "
                  "offered to Rihmasto's cells after a person approves. Nothing found here is enabled or run.")
NOT_RUN = "nothing found here is run: hooks, commands, skills' scripts and MCP servers are only named"
_SECRETISH = re.compile(r"(?i)(token|secret|passw|api[_-]?key|bearer|authorization|private[_-]?key)\s*[=:]")


def _parts(rel: str) -> tuple[str, ...]:
    return PurePosixPath(rel).parts


def _after(parts: tuple[str, ...], folder: str) -> tuple[int, tuple[str, ...]] | None:
    """Where ``folder`` (a tool's folder, such as `.claude`) is in a path, and what follows it."""
    low = [p.lower() for p in parts]
    if folder in low[:-1]:
        i = len(low) - 1 - low[::-1].index(folder)
        return i, parts[i + 1:]
    return None


# Each AI tool's files, by their lower-case path at any level of the folder: the first rule that matches.
_PATHS = tuple((re.compile(r"(^|/)" + rule + r"$"), sub) for rule, sub in (
    (r"claude\.local\.md", "personal"),
    (r"(claude|agents|gemini)\.md", "instructions"),
    (r"\.(cursorrules|windsurfrules|clinerules|rules)", "instructions"),
    (r"conventions\.md", "instructions"),                     # Aider's conventions file
    (r"\.github/copilot-instructions\.md", "instructions"),
    (r"\.github/instructions/[^/]+\.instructions\.md", "instructions"),
    (r"(\.mcp\.json|\.cursor/mcp\.json|\.vscode/mcp\.json)", "mcp"),
    (r"\.cursor/rules/.+\.(mdc|md)", "instructions"),
    (r"\.windsurf/rules/.+\.md", "instructions"),
    (r"\.clinerules/(.+\.(md|txt)|(.+/)?[^/.]+)", "instructions"),
    (r"\.cursor/commands/.+\.md", "command"),
    (r"\.claude/settings\.json", "settings"),
    (r"\.claude/settings\.local\.json", "personal"),
    (r"\.claude/skills/[^/]+/skill\.md", "skill"),
    (r"\.claude/skills/[^/]+/.+", "skill_file"),
    (r"\.claude/agents/.+\.md", "agent"),
    (r"\.claude/rules/.+\.md", "instructions"),
    (r"\.claude/commands/.+\.md", "command")))


def sub_kind(rel: str) -> str | None:
    """What a file is to the project's AI tools, by its path, or None when it is none of theirs."""
    low = rel.replace("\\", "/").lower()
    return next((sub for rule, sub in _PATHS if rule.search(low)), None)


def tool_of(rel: str) -> str:
    """The AI tool a file is written for."""
    low = rel.lower()
    name = PurePosixPath(low).name
    if name == "agents.md":
        return "Codex, Cursor and other agents"
    if name == "gemini.md":
        return "Gemini CLI"
    if name == "conventions.md":
        return "Aider"
    if name == ".rules":
        return "Zed"
    if ".github/" in "/" + low or name == "copilot-instructions.md":
        return "GitHub Copilot"
    if ".cursor" in low:
        return "Cursor"
    if ".windsurf" in low:
        return "Windsurf"
    if ".clinerules" in low:
        return "Cline"
    if ".vscode/" in low:
        return "VS Code"
    return "Claude Code"


# -- frontmatter -----------------------------------------------------------------------------------------

def _unquote(v: str) -> str:
    v = v.strip()
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v


def _scalar(v: str) -> Any:
    if v.startswith("[") and v.endswith("]"):
        return [_unquote(x) for x in v[1:-1].split(",") if x.strip()]
    if v in (">", "|", ">-", "|-", ">+", "|+"):
        return ""                     # a block scalar: its lines follow
    if v.lower() in ("true", "yes"):
        return True
    if v.lower() in ("false", "no"):
        return False
    return _unquote(v)


_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$")
_ITEM = re.compile(r"^\s*-\s+(.*)$")


def _more(out: dict[str, Any], key: str, raw: str) -> None:
    """A line under ``key``: a list item, or the next line of a folded or block value."""
    item, value = _ITEM.match(raw), out.get(key)
    if item and isinstance(value, list):
        value.append(_unquote(item.group(1)))
    elif isinstance(value, str):
        out[key] = (value + " " + raw.strip()).strip()
    elif value == []:
        out[key] = raw.strip()


def frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """A Markdown file's YAML frontmatter, read by a small rule (keys, scalars, lists), and the body after it."""
    lines = text.splitlines()
    end = next((i for i in range(1, min(len(lines), 200)) if lines[i].strip() in ("---", "...")), None) \
        if lines and lines[0].strip() == "---" else None
    if end is None:
        return {}, text
    out: dict[str, Any] = {}
    key = None
    for raw in lines[1:end]:
        m = _KEY.match(raw)
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if m and not raw[:1].isspace():
            key = m.group(1).lower()
            out[key] = _scalar(m.group(2).strip()) if m.group(2).strip() else []
        elif key is not None:
            _more(out, key, raw)
    return out, "\n".join(lines[end + 1:])


def _text(value: Any, limit: int = 300) -> str:
    return " ".join(str(value or "").split())[:limit]


def globs_of(meta: dict[str, Any], key: str = "globs") -> list[str]:
    raw = meta.get(key)
    items = raw if isinstance(raw, list) else str(raw or "").split(",")
    return [g.strip().strip("\"'") for g in items if str(g).strip().strip("\"'")][:20]


def _title(body: str) -> str:
    return next((_text(x.lstrip("#"), 120) for x in body.splitlines() if x.startswith("#")), "")


def _folder(rel: str) -> str:
    """The folder a nested file speaks for: `web/` for `web/CLAUDE.md`, "" for the whole project."""
    parts = _parts(rel)
    cut = next((i for i, p in enumerate(parts) if p.lower() in (".cursor", ".windsurf", ".github", ".clinerules",
                                                                  ".claude")), len(parts) - 1)
    return "/".join(parts[:cut]) + "/" if cut else ""


# -- hooks, permissions and MCP servers, by name only ----------------------------------------------------

def _safe(s: Any) -> str | None:
    """A rule's or a name's text, or None when it may hold a secret."""
    t = _text(s, 120)
    if not t or _SECRETISH.search(t) or mk.secret_in_text("rule.txt", t):
        return None
    return t


def _json(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _dict(value: Any) -> dict[str, Any]:
    """A JSON object's value as a dict: anything else is empty."""
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _hook(event: str, groups: Any) -> dict[str, Any]:
    """One hook event: its matchers and how many hooks, never a hook's command."""
    groups = [g for g in _list(groups) if isinstance(g, dict)]
    matchers = [m for m in (_safe(g.get("matcher")) for g in groups) if m]
    return {"event": _text(event, 60), "matchers": matchers[:10],
            "hooks": sum(len(_list(g.get("hooks"))) for g in groups)}


def settings_summary(text: str) -> dict[str, Any]:
    """`.claude/settings.json`: hook events with their matchers, permission rule names, how many environment
    names. Never a hook's command or an environment value."""
    data = _json(text)
    if data is None:
        return {"error": "not read: it is not a JSON object"}
    perms = _dict(data.get("permissions"))
    names = {kind: [_safe(r) for r in _list(perms.get(kind))] for kind in ("allow", "ask", "deny")}
    return {"hooks": [_hook(e, g) for e, g in _dict(data.get("hooks")).items()][:20],
            "permissions": {kind: [r for r in rules if r][:40] for kind, rules in names.items()},
            "rules_not_shown": sum(r is None for rules in names.values() for r in rules),
            "env_names": len(_dict(data.get("env"))), "keys": [_text(k, 40) for k in list(data)[:20]]}


def _server(name: str, cfg: Any) -> dict[str, Any]:
    """One MCP server: its name, transport, its command's name or its URL's host. Never its arguments,
    environment values or headers."""
    cfg = _dict(cfg)
    url = str(cfg.get("url") or cfg.get("serverUrl") or "")
    command = PurePosixPath(str(cfg.get("command") or "").replace("\\", "/")).name
    where = {"host": urlsplit(url).hostname or "?"} if url else {"command": _safe(command) or "(not shown)"} \
        if command else {}
    return {"name": _safe(name) or "(a name not shown)", "transport": str(cfg.get("type") or
                                                                           ("http" if url else "stdio"))[:20],
            **where, "env": len(_dict(cfg.get("env"))), "headers": len(_dict(cfg.get("headers")))}


def mcp_summary(text: str) -> dict[str, Any]:
    """An MCP configuration (`mcpServers`, or VS Code's `servers`): each server by name only."""
    data = _json(text)
    if data is None:
        return {"error": "not read: it is not a JSON object", "servers": []}
    block = _dict(data.get("mcpServers") or data.get("servers"))
    return {"servers": [_server(n, c) for n, c in block.items()][:40]}


def _mcp_text(rel: str, info: dict[str, Any]) -> list[str]:
    out = [f"MCP servers configured for {tool_of(rel)} ({NOT_RUN}; arguments, environment values and headers "
           "are not read):"]
    for s in info["servers"]:
        where = f"command {s['command']}" if s.get("command") else f"host {s['host']}" if s.get("host") else ""
        out.append(f"- {s['name']} ({s['transport']}{', ' + where if where else ''})")
    return out if info["servers"] else [*out, "- none"]


def _settings_text(info: dict[str, Any]) -> list[str]:
    out = [f"Claude Code hooks and permissions ({NOT_RUN}; hook commands and environment values are not read):"]
    out += [f"- hook {h['event']}" + (f" on {', '.join(h['matchers'])}" if h["matchers"] else "")
            + f": {h['hooks']} hook{'s' if h['hooks'] != 1 else ''}" for h in info["hooks"]]
    out += [f"- {kind}: " + ", ".join(names) for kind, names in info["permissions"].items() if names]
    if info.get("rules_not_shown"):
        out.append(f"- {info['rules_not_shown']} rule(s) not shown: they may hold a secret")
    if info.get("env_names"):
        out.append(f"- {info['env_names']} environment setting(s): names and values not read")
    return out


def summary_text(rel: str, sub: str, info: dict[str, Any]) -> str:
    """What the request holds for a settings or MCP file: its summary, never its raw text."""
    if info.get("error"):
        return f"{rel}: {info['error']}"
    return "\n".join(_mcp_text(rel, info) if sub == "mcp" else _settings_text(info))


# -- one file --------------------------------------------------------------------------------------------

def _instructions(rel: str, meta: dict[str, Any], body: str) -> dict[str, Any]:
    """Project instructions: where they apply (the whole project, a folder, the files a rule's globs match, or
    when the agent finds them relevant)."""
    globs = globs_of(meta, "applyto" if "applyto" in meta else "globs")
    always = meta.get("alwaysapply") is True
    folder = _folder(rel)
    rule = "/rules/" in "/" + rel.lower() or rel.lower().endswith(".instructions.md")
    if globs:
        applies = "the files matching " + ", ".join(globs) + (f" under {folder}" if folder else "")
    elif rule and not always:
        applies = "when relevant: the agent decides by its description"
    else:
        applies = f"the files under {folder}" if folder else "the whole project"
    return {"title": _title(body), "description": _text(meta.get("description")), "globs": globs,
            "always_apply": always, "rule": rule, "folder": folder, "applies_to": applies}


def _skill(rel: str, meta: dict[str, Any], body: str) -> dict[str, Any]:
    return {"name": _text(meta.get("name") or _parts(rel)[-2], 80), "description": _text(meta.get("description")),
            "files": []}


def _subagent(rel: str, meta: dict[str, Any], body: str) -> dict[str, Any]:
    tools = meta.get("tools")
    return {"name": _text(meta.get("name") or PurePosixPath(rel).stem, 80),
            "description": _text(meta.get("description")),
            "tools": _text(", ".join(map(str, tools)) if isinstance(tools, list) else tools, 160)}


def _command(rel: str, meta: dict[str, Any], body: str) -> dict[str, Any]:
    found = _after(_parts(rel), ".claude") or _after(_parts(rel), ".cursor")
    name = "/".join(found[1][1:]) if found else PurePosixPath(rel).name
    return {"name": "/" + name.removesuffix(".md").replace("/", ":"),
            "description": _text(meta.get("description") or _title(body))}


_DESCRIBE = {"instructions": _instructions, "skill": _skill, "agent": _subagent, "command": _command}


def describe(rel: str, sub: str, text: str) -> dict[str, Any]:
    """One file's entry: where it is, for which tool, and what its frontmatter or summary says."""
    entry: dict[str, Any] = {"path": rel, "sub": sub, "label": SUB_LABEL[sub], "tool": tool_of(rel)}
    if sub in ("settings", "mcp"):
        info = settings_summary(text) if sub == "settings" else mcp_summary(text)
        return entry | info | {"request": summary_text(rel, sub, info)}
    meta, body = frontmatter(text)
    return entry | {"chars": len(text)} | _DESCRIBE[sub](rel, meta, body)


def read_entry(rel: str, sub: str, data: bytes | None, keep_text: bool = False) -> dict[str, Any]:
    """A file's entry from its bytes: personal files and secret-looking ones are named, never read."""
    if sub == "personal":
        return {"path": rel, "sub": sub, "label": SUB_LABEL[sub], "tool": tool_of(rel), "why": PERSONAL_WHY}
    if sub == "skill_file":
        return {"path": rel, "sub": sub, "label": SUB_LABEL[sub], "tool": tool_of(rel)}
    if mk.secret_by_name(rel):
        return {"path": rel, "sub": sub, "not_read": "may hold secrets: never opened, by its name"}
    if data is None or len(data) > MAX_TEXT:
        return {"path": rel, "sub": sub, "not_read": "too large to read" if data else "could not be read"}
    text = mr.decode(data).replace("\r\n", "\n")
    if mk.secret_in_text(rel, text):
        return {"path": rel, "sub": sub, "not_read": "may hold secrets: its text holds a credential"}
    entry = describe(rel, sub, text)
    if (keep_text or sub == "instructions") and sub not in ("settings", "mcp"):   # those: their summary only
        entry["text"] = text
    return entry


def weight(rel: str) -> int:
    """CLAUDE.md and AGENTS.md first among the instructions: they are the conventions most tools read."""
    return 0 if PurePosixPath(rel).name.lower() in ("claude.md", "agents.md") else 1


# -- the whole project -----------------------------------------------------------------------------------

def _bundle(skills: list[dict[str, Any]], files: list[str]) -> None:
    """Each skill's bundled files, listed under it (relative to the skill's folder), never read."""
    for rel in files:
        where = _after(_parts(rel), ".claude")          # a skill's file is always under .claude/skills/<name>/
        home = "/".join(_parts(rel)[:where[0] + 3]) + "/" if where else ""
        skill = next((s for s in skills if home and s["path"].startswith(home)), None)
        if skill is not None:
            skill["files"].append(rel[len(home):])


def assemble(entries: Iterable[dict[str, Any]], *, keep_text: bool = False) -> dict[str, Any]:
    """The project's agent context from its files' entries: grouped, skills with their bundled files, and the
    build, test and lint commands its instructions state."""
    from kernel.agent_context_use import stated_commands

    entries = list(entries)
    ctx: dict[str, Any] = {"schema": SCHEMA, "by": f"rule (kernel/agent_context.py), no model; {NOT_RUN}",
                           **{g: [] for g in GROUPS}, "not_read": [], "catalogue_note": CATALOGUE_NOTE}
    for e in entries:
        if e.get("not_read"):
            ctx["not_read"].append({k: e[k] for k in ("path", "sub", "not_read")})
        elif e["sub"] != "skill_file":
            ctx[GROUP_OF[e["sub"]]].append(e)
    _bundle(ctx["skills"], [e["path"] for e in entries if e["sub"] == "skill_file"])
    ctx["instructions"].sort(key=lambda e: (weight(e["path"]), e["path"].count("/"), e["path"].lower()))
    ctx["stated"] = stated_commands(ctx["instructions"])
    for g in GROUPS:
        ctx[g] = [e if keep_text and g not in ("settings", "mcp") else {k: v for k, v in e.items() if k != "text"}
                  for e in ctx[g][:MAX_ROWS]]
    ctx["counts"] = {g: len(ctx[g]) for g in GROUPS} | {"not_read": len(ctx["not_read"])}
    ctx["found"] = any(ctx["counts"].values())
    return ctx


def recognise(files: Iterable[str], read: Callable[[str], bytes | None], *, keep_text: bool = False
              ) -> dict[str, Any]:
    """The agent context among ``files`` (relative POSIX paths), each read through ``read``."""
    picked = [(rel, sub) for rel in files if (sub := sub_kind(rel))][:MAX_FILES]
    return assemble((read_entry(rel, sub, None if sub in ("personal", "skill_file") else read(rel), keep_text)
                     for rel, sub in picked), keep_text=keep_text)


def from_folder(root: str | Path, *, keep_text: bool = False) -> dict[str, Any]:
    """The agent context of a folder on this machine, walked as the material scan walks it."""
    from kernel.material import _walk

    base = Path(root)
    files, _, _ = _walk(base, ())

    def read(rel: str) -> bytes | None:
        try:
            return (base / rel).read_bytes() if (base / rel).stat().st_size <= MAX_TEXT else b"x" * (MAX_TEXT + 1)
        except OSError:
            return None

    return recognise(files, read, keep_text=keep_text)


_GIT = ["git", "-c", "credential.helper=", "-c", "core.hooksPath=" + os.devnull]


def _git(cwd: Path, *args: str) -> bytes:
    env = dict(os.environ) | {"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_LFS_SKIP_SMUDGE": "1"}
    try:
        proc = subprocess.run([*_GIT, *args], cwd=cwd, capture_output=True, env=env, stdin=subprocess.DEVNULL,
                              timeout=60, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git {args[0]} did not finish in 60 s") from exc
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip()[:200])
    return proc.stdout


def from_git(repo: str | Path, revision: str, *, keep_text: bool = False) -> dict[str, Any]:
    """The agent context of a committed revision of a git repository, read from git's objects: no checkout,
    nothing written, and the working tree never looked at."""
    repo = Path(repo)
    if not revision or revision.startswith("-"):
        raise ValueError(f"{revision!r} is not a revision")
    names = [n.decode("utf-8", "surrogateescape") for n in _git(repo, "ls-tree", "-r", "-z", "--name-only",
                                                                 revision).split(b"\0") if n]

    def read(rel: str) -> bytes | None:
        try:
            return _git(repo, "cat-file", "blob", f"{revision}:{rel}")
        except RuntimeError:
            return None

    return recognise(names, read, keep_text=keep_text) | {"revision": revision}
