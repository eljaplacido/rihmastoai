"""Where the IDE and the terminal meet Rihmasto (FR-AGC1, docs/guides/ide-and-rihmasto.md).

    rihmasto ide <pid> [--name "Your Name"] [--persona developer] [--section] [--json]

The IDE and the terminal are the inner loop: one developer with an agent at their side, writing, running
and debugging. Rihmasto is the outer loop: what is built and why, who decided, the contract, independent
verification, delivery and evidence, the change loop, many parties. They meet in three places:

- **the repository**: Rihmasto reads the team's conventions (kernel/agent_context.py) and gates the
  team's changes (a workspace's submission on an adopted project; `repo gate` on an attached one);
- **the MCP server** (docs/mcp.md): the IDE agent sees the contract and what waits on a decision, and can
  file a change; it decides nothing;
- **the conventions file**: `section` is the text a person pastes into the project's AGENTS.md or CLAUDE.md
  themselves, "Rihmasto's contract and open questions for your IDE agent". Rihmasto never writes into a
  person's folder or repository.

This module writes nothing and runs nothing: `rihmasto ide` prints, and the cockpit's "Work on it from your
IDE" card shows the same. What the project's AI tools are found to be is read from the committed revision
(an adopted project's main, an attached repository's branch), never from a working tree.
"""

from __future__ import annotations

import json
import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel import agent_context as ac

BEGIN, END = "<!-- rihmasto:begin {pid} -->", "<!-- rihmasto:end {pid} -->"
SECTION_TITLE = "Rihmasto's contract and open questions for your IDE agent"
NAME = "<your name>"
MAX_REQS = 30
MAX_OPEN = 15


def kind_of(project: Any) -> str | None:
    """"adopted" or "attached" for a project whose code lives in a repository, else None."""
    kind = project.meta.get("source_kind")
    return kind if kind in ("adopted", "attached") else None


def context(project: Any) -> dict[str, Any]:
    """The project's agent context, read from its committed revision: an adopted project's main, an attached
    repository's branch; what adoption or attaching recorded when the repository cannot be read."""
    kind = kind_of(project)
    try:
        if kind == "adopted":
            return ac.from_git(project.path("repo.git"), "main") | {"read_from": "main of the product repository"}
        if kind == "attached":
            info = project.meta.get("attached") or {}
            branch = info.get("branch") or "HEAD"
            return ac.from_git(Path(info["repo"]), branch) | {"read_from": f"the committed {branch} of {info['repo']}"}
    except (RuntimeError, OSError, KeyError, ValueError):
        pass
    kept = project.read("agent_context.json", None)
    if isinstance(kept, dict):
        return kept | {"read_from": "what was recorded when the project was made (the repository could not be read)"}
    return ac.assemble([]) | {"read_from": "nothing: no repository"}


def record(project: Any, ctx: dict[str, Any], *, at: str) -> None:
    """Keep what was found when a project was adopted or attached, and its counts in the ledger (nothing
    when nothing was found)."""
    if not ctx.get("found"):
        return
    project.write("agent_context.json", ctx)
    project.log("agent_context_found", {"revision": at, **ctx["counts"],
                                        "stated": [f"{s['kind']}: {s['command']}" for s in ctx["stated"]],
                                        "note": ac.NOT_RUN})


# -- the IDE's side -------------------------------------------------------------------------------------

def mcp(factory: Any, *, name: str | None, persona: str) -> dict[str, Any]:
    """Ready-to-paste MCP configuration for Claude Code, Cursor and Codex, pointing at Rihmasto's own MCP
    server on this machine (docs/mcp.md), signed with the person and persona."""
    from kernel.workspace import mcp_config

    who = name or NAME
    cfg = mcp_config(factory, person=who, persona=persona)
    server = cfg["mcpServers"]["rihma"]
    cursor = {"mcpServers": {"rihma": {k: v for k, v in server.items() if k != "type"}}}
    argv = [server["command"], *server["args"]]
    toml = ("[mcp_servers.rihma]\n" + f"command = {json.dumps(server['command'])}\n"
            + "args = [" + ", ".join(json.dumps(a) for a in server["args"]) + "]\n")
    return {"claude_code": {"file": ".mcp.json", "json": cfg,
                            "command": "claude mcp add rihma -- " + " ".join(_quote(a) for a in argv)},
            "cursor": {"file": ".cursor/mcp.json", "json": cursor},
            "codex": {"file": "~/.codex/config.toml", "toml": toml},
            "signed_as": {"person": who, "persona": persona},
            "note": "Paste it into your own configuration: Rihmasto never writes into your folder. The server reads "
                    "the factory and files proposals (a change, a comment); people decide in the cockpit."}


def _quote(arg: str) -> str:
    return f'"{arg}"' if any(c in arg for c in " \t'\"") or not arg else arg if sys.platform == "win32" \
        else shlex.quote(arg)


def comes_back(project: Any) -> list[str]:
    """How a developer's change comes back into Rihmasto from the IDE."""
    pid = project.pid
    if kind_of(project) == "attached":
        return ["Commit in your repository as you always do: Rihmasto never writes to it, pushes to it or merges "
                "into it.", f"`rihmasto repo gate {pid} --head <revision>` judges the commit against the contract "
                "(a temporary clone, never your working tree); uncommitted changes are never judged.",
                "A new requirement is a decision: file it (`rihma_report_change` from your IDE, or the cockpit) "
                "before you build it."]
    return [f"`rihmasto workspace open {pid} --person \"<your name>\" --persona developer --agent claude` clones "
            "main onto your own branch, with Rihmasto's MCP server set up in its `.mcp.json`; open that folder in "
            "your IDE.",
            f"`rihmasto workspace submit {pid} <that folder> --person \"<your name>\" --persona developer "
            "[--task T-00n]` sends your commits through the gate a builder cell meets: the tests run by the "
            "kernel, the criteria traced, the independent verifier. Warranted, it merges into main.",
            f"A change pushed to the upstream instead is seen by `rihmasto sync {pid}`, which opens an "
            "\"Upstream changed: review\" card; main never moves by itself.",
            "A new requirement is a decision: file it (`rihma_report_change` from your IDE, or the cockpit) before "
            "you build it."]


def section(project: Any) -> str:
    """The text a person pastes into the project's AGENTS.md or CLAUDE.md, between its markers: the
    contract, what waits on a decision, and how a change comes back. Rihmasto never writes it there."""
    from kernel.canon import Canon

    pid, meta = project.pid, project.meta
    canon = Canon(project)
    contract = project.read("contract.json", None) or {}
    lines = [BEGIN.format(pid=pid), f"## {SECTION_TITLE}", "",
             f"This project is governed in Rihmasto: **{meta.get('title')}** (`{pid}`). Rihmasto holds what is built "
             "and why, who decided it, and verifies every change independently. Work here as usual, and keep to "
             "what follows. Paste a newer copy over this one from `rihmasto ide " + pid + " --section`.", ""]
    reqs = contract.get("requirements") or []
    lines += [f"### The contract (revision {str(contract.get('revision', ''))[:19] or 'none yet'})", ""]
    lines += [f"- **{r['id']}**: {r['statement']} ({', '.join(c['id'] for c in r.get('acceptance', []))})"
              for r in reqs[:MAX_REQS]] or ["- No contract yet: build nothing new until one is given."]
    if len(reqs) > MAX_REQS:
        lines.append(f"- ...and {len(reqs) - MAX_REQS} more: `rihma_project` over MCP lists them.")
    cards, questions = canon.cards(), canon.questions("open")
    lines += ["", "### Waiting on a decision (people decide these in Rihmasto's cockpit, never here)", ""]
    lines += [f"- {c['id']} ({c['kind'].replace('_', ' ')}): {c['title']}" for c in cards[:MAX_OPEN]]
    lines += [f"- {q['id']}{' (blocking)' if q.get('blocking') else ''}: {q['text']}" for q in questions[:MAX_OPEN]]
    if not cards and not questions:
        lines.append("- Nothing waits.")
    lines += ["", "### How your change comes back", ""] + [f"- {x}" for x in comes_back(project)]
    lines += ["", "### Rules", "",
              "- Never edit `.gnomon/`, `contract.json` or `factory/`: the kernel owns them.",
              "- A change to what is built is a decision: propose it, do not build it unasked.",
              "- Rihma over MCP (`rihma_project`, `rihma_waiting`, `rihma_evidence`, `rihma_report_change`, "
              "`rihma_comment`) reads the factory and files proposals; it decides nothing.",
              END.format(pid=pid)]
    return "\n".join(lines) + "\n"


def view(project: Any, *, name: str | None, persona: str) -> dict[str, Any]:
    """What the cockpit's "AI tools in this project" and "Work on it from your IDE" cards show."""
    kind = kind_of(project)
    if kind is None:
        return {"applies": False, "why": "a project whose code Rihmasto builds itself: there is no team repository "
                                         "to read"}
    return {"applies": True, "kind": kind, "context": context(project),
            "ide": mcp(project.factory, name=name, persona=persona), "comes_back": comes_back(project),
            "section": section(project), "section_title": SECTION_TITLE,
            "section_file": f"rihmasto-{project.pid}-agents-section.md"}


# -- the terminal ---------------------------------------------------------------------------------------

def overview(ctx: dict[str, Any] | None) -> list[str]:
    """"How AI tools here are set up", as a terminal shows it. [] when there is nothing."""
    if not ctx or not ctx.get("found"):
        return []
    out = ["How AI tools here are set up:"]
    for group, label, said in _LINES:
        out += [f"  {label:<14}{e['path']}  [{said(e)}]" for e in ctx[group]]
    out += [f"  stated {s['kind']:<7}{s['command']}  [{s['file']}, line {s['line']}]" for s in ctx["stated"]]
    if ctx["skills"] or ctx["mcp"]:
        out.append(f"  {ac.CATALOGUE_NOTE}")
    return [*out, ""]


def _described(e: dict[str, Any]) -> str:
    files = f"; {len(e['files'])} bundled file(s)" if e.get("files") else ""
    return f"{e['name']}: {e['description'] or 'no description'}{files}"


def _hooks(e: dict[str, Any]) -> str:
    hooks = ", ".join(h["event"] for h in e.get("hooks") or []) or "no hooks"
    return f"{hooks}; {sum(len(v) for v in (e.get('permissions') or {}).values())} permission rule(s)"


# Each group of the terminal's overview: its label, and what a line says of one file.
_LINES: tuple[tuple[str, str, Callable[[dict[str, Any]], str]], ...] = (
    ("instructions", "instructions", lambda e: f"{e['tool']}; applies to {e['applies_to']}"),
    ("skills", "skill", _described), ("agents", "subagent", _described),
    ("commands", "command", lambda e: e["name"]), ("settings", "hooks", _hooks),
    ("mcp", "MCP servers", lambda e: ", ".join(s["name"] for s in e.get("servers") or [])),
    ("personal", "personal", lambda e: "listed, never read"), ("not_read", "not read", lambda e: e["not_read"]))


def render(out: dict[str, Any]) -> str:
    if not out["applies"]:
        return f"{out['why']}\n"
    ide = out["ide"]
    lines = overview(out["context"]) or ["No AI tool configuration was found in the repository.", ""]
    lines += [f"(read from {out['context'].get('read_from')})", "", "Work on it from your IDE", "",
              f"Claude Code: {ide['claude_code']['file']} in your clone",
              json.dumps(ide["claude_code"]["json"], indent=2),
              "", "or from the command line:", f"  {ide['claude_code']['command']}", "",
              f"Cursor: {ide['cursor']['file']}", json.dumps(ide["cursor"]["json"], indent=2), "",
              f"Codex: {ide['codex']['file']}", ide["codex"]["toml"], ide["note"], "",
              "How your change comes back:"] + [f"- {x}" for x in out["comes_back"]]
    lines += ["", f"For your AGENTS.md or CLAUDE.md, to paste yourself: `rihmasto ide {out['pid']} --section`"]
    return "\n".join(lines) + "\n"


def add_parsers(sub: Any) -> None:
    p = sub.add_parser("ide", help="work on a project from your IDE: its AI tools, MCP config, how a change "
                                   "comes back; prints only (kernel/ide.py)")
    p.add_argument("pid")
    p.add_argument("--name", help="the name Rihmasto's MCP server signs as (default: a placeholder to fill in)")
    p.add_argument("--persona", default="developer")
    p.add_argument("--section", action="store_true",
                   help="only the text to paste into AGENTS.md or CLAUDE.md yourself")
    p.add_argument("--json", action="store_true")


def handlers(emit: Callable[[Any], None]) -> dict[str, Callable[[Any, Any], Any]]:
    def ide(factory: Any, args: Any) -> int:
        from kernel.people import PERSONAS

        if args.persona not in PERSONAS:
            raise ValueError(f"persona must be one of {', '.join(PERSONAS)}")
        project = factory.project(args.pid)
        if args.section:
            sys.stdout.write(section(project))
            return 0
        out = view(project, name=args.name, persona=args.persona) | {"pid": project.pid}
        if args.json:
            emit(out)
        else:
            sys.stdout.write(render(out))
        return 0

    return {"ide": ide}
