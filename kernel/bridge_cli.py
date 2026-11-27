"""`rihmasto goal`, `rihmasto handoff` and `rihmasto channel`, part of the command line (kernel/cli.py).

    rihmasto goal <pid> "hook this to Google Drive" [--json]        a plan for a goal (kernel/copilot.py)
    rihmasto handoff <pid> [--change C-0004] [--to claude-code|codex|opencode|cursor|generic] [--json]
                                                                    the hand-off brief and how the agent takes it
    rihmasto channel <pid> [--thread T] [--since M-0007] [--follow] [--json]
                                                                    the agent channel, in a terminal
    rihmasto channel <pid> post --as NAME --text "..." [--kind progress] [--thread T] [--harness H]
                                [--criteria A,B] [--commit SHA] --person OPERATOR --persona P
                                                                    post as an agent without MCP, for its operator

Reading writes nothing. A post is signed by its operator, recorded and, when it asks @analyst or @verifier a
question, answered by a Rihma agent from the records (kernel/channel_rihma.py).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from typing import Any

from kernel import agent_bridge as bridge
from kernel import agent_channel as ch
from kernel import channel_rihma
from kernel.people import PERSONAS
from kernel.store import Factory

Args = argparse.Namespace
FOLLOW_EVERY = 2.0


def add_parsers(sub: Any) -> None:
    g = sub.add_parser("goal", help="a plan for a goal in a project (docs/guides/agentic-help.md)")
    g.add_argument("pid")
    g.add_argument("goal", help="the goal, in your words")
    g.add_argument("--json", action="store_true")
    h = sub.add_parser("handoff", help="the hand-off brief for a coding agent")
    h.add_argument("pid")
    h.add_argument("--change", help="a change card, such as C-0004")
    h.add_argument("--to", choices=list(bridge.AGENTS), default="generic")
    h.add_argument("--json", action="store_true")
    c = sub.add_parser("channel", help="the project's agent channel: read it, follow it, or post as an agent")
    c.add_argument("pid")
    c.add_argument("--thread")
    c.add_argument("--since", help="after a message id (M-0007) or a time")
    c.add_argument("--follow", action="store_true", help="keep showing new messages until Ctrl+C")
    c.add_argument("--json", action="store_true")
    cs = c.add_subparsers(dest="sub", required=False)
    p = cs.add_parser("post", help="post as an agent, signed for its operator")
    p.add_argument("--as", dest="agent", required=True, help="the agent's name, such as claude-code")
    p.add_argument("--text", required=True)
    p.add_argument("--kind", choices=["question", "answer", "progress", "feedback", "plan", "note"],
                   default="progress")
    p.add_argument("--reply-to", dest="reply_to", help="the message it answers, such as M-0012 (FR-CHN2)")
    p.add_argument("--thread", dest="post_thread")
    p.add_argument("--harness")
    p.add_argument("--criteria", help="criteria it refers to, comma separated")
    p.add_argument("--commit")
    p.add_argument("--person", required=True, help="the agent's operator, the named person who signs for it")
    p.add_argument("--persona", required=True, choices=PERSONAS)


def _line(m: dict[str, Any]) -> str:
    refs = " ".join(f"[{k}: {', '.join(v) if isinstance(v, list) else v}]" for k, v in (m.get("refs") or {}).items()
                    if v)
    held = " (waiting: the channel is paused)" if m.get("held") else ""
    state = f" ({m['state']})" if m.get("state") else ""
    return f"{m['id']} {m['at']} #{m['thread']} {ch.who(m)} [{m['kind']}{state}]{held}: {m['text']} {refs}".rstrip()


def _goal(f: Factory, a: Args, emit: Callable[[Any], None], say: Callable[[str], None]) -> None:
    from kernel.copilot import plan

    out = plan(f, f.project(a.pid), a.goal)
    if a.json:
        emit(out)
        return
    say(out["answer"])
    for g in out["gaps"]:
        say(f"\nGap: {g['what']}\n" + "\n".join(f"  - {o}" for o in g["options"]))
    for s in out["steps"]:
        act = s["action"]
        how = act.get("command") or act.get("route") or act.get("kind")
        off = "" if s["available"] else f"  (not available: {s['why_not']})"
        say(f"\n{s['id']}. {s['title']}: {how}{off}" + (f"\n    {s['detail']}" if s.get("detail") else ""))


def _handoff(f: Factory, a: Args, emit: Callable[[Any], None], say: Callable[[str], None]) -> None:
    project = f.project(a.pid)
    b = bridge.brief(project, change=a.change)
    use = bridge.for_agent(f, project, b, to=a.to)
    if a.json:
        emit({"brief": b, "use": use})
        return
    say(bridge.render(b))
    say(f"--- For {use['label']} ---\nSave the brief above as {use['prompt_file']}, then: {use['run']}")
    say(f"MCP configuration ({use['mcp']['file']}):\n"
        + (use["mcp"].get("toml") or json.dumps(use["mcp"].get("json"), indent=2)))


def _show(f: Factory, a: Args, emit: Callable[[Any], None], say: Callable[[str], None]) -> None:
    project = f.project(a.pid)
    since = a.since
    rows = ch.messages(project, since=since, thread=a.thread)
    if a.json and not a.follow:
        emit({"project": project.pid, "paused": ch.read(project).get("paused"), "messages": rows})
        return
    if ch.read(project).get("paused"):
        say(f"(paused by {ch.read(project)['paused']['person']}: agents' posts wait)")
    for m in rows:
        say(_line(m))
    if not a.follow:
        return
    since = rows[-1]["id"] if rows else since
    try:
        while True:
            time.sleep(FOLLOW_EVERY)
            for m in ch.messages(project, since=since, thread=a.thread):
                say(_line(m))
                since = m["id"]
    except KeyboardInterrupt:
        return


def _post(f: Factory, a: Args, emit: Callable[[Any], None]) -> None:
    project = f.project(a.pid)
    author = ch.agent(a.agent.lower(), a.person, a.persona, a.harness)
    refs = {k: v for k, v in (("criteria", [x for x in (a.criteria or "").split(",") if x.strip()]),
                              ("commits", [a.commit] if a.commit else []),
                              ("message", getattr(a, "reply_to", None))) if v}
    if a.kind == "progress":
        from kernel.agent_writes import progress

        msg = progress(project, author, a.text, criteria=refs.get("criteria"), commit=a.commit,
                       thread=a.post_thread or a.thread)
    else:
        msg = ch.post(project, author=author, kind=a.kind, text=a.text, thread=a.post_thread or a.thread, refs=refs)
    emit({"message": msg, "answer": channel_rihma.reply(project, msg)})


def handlers(emit: Callable[[Any], None], say: Callable[[str], None] = print) -> dict[str, Callable[[Factory, Args],
                                                                                                    None]]:
    def safe(fn: Callable[[Factory, Args], None]) -> Callable[[Factory, Args], None]:
        def run(f: Factory, a: Args) -> None:
            try:
                fn(f, a)
            except ch.ChannelRefused as exc:
                raise ValueError(str(exc)) from None
        return run

    return {"goal": safe(lambda f, a: _goal(f, a, emit, say)), "handoff": safe(lambda f, a: _handoff(f, a, emit, say)),
            "channel": safe(lambda f, a: _show(f, a, emit, say)), "channel post": safe(lambda f, a: _post(f, a, emit))}


if __name__ == "__main__":  # pragma: no cover
    sys.exit("run it as `rihmasto goal|handoff|channel`")
