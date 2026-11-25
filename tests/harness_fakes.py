"""Fake coding agents for the harness-model tests (FR-HMD1): small Python scripts that answer as `claude -p
--output-format json`, `codex exec --json` and `opencode run --format json` do. No real Claude Code, Codex or OpenCode
runs in a test, and no model or network is used.

``fake_agent`` writes a script that answers ``--version`` as the real one does, reads its task (standard input, or the
file OpenCode is given), answers it from the factory's scripted model (tests/factory_fakes.py ``script``), Shape it in
chat's and the assistant's prompts with a fixed answer, and Test's tiny prompt with OK. It writes what it was given
(its arguments, its working folder and what is in it, its task, the names of its environment variables) to
``$FAKE_HARNESS_LOG``, so a test can see what reached it.

Modes: ``good``; ``fail`` (exits 1 with an error in the harness's own shape); ``deepseek`` (Claude Code's output names
a deepseek model, as a harness pointed at another provider would).
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

VERSIONS = {"claude-code": "2.1.331 (Claude Code)", "codex": "codex-cli 0.60.1", "opencode": "v2.0.32"}
ASSISTANT_ANSWER = "HARNESS-ASSISTANT: open Models setup to see each role."
SHAPE_REPLY = "Who borrows the tools, and who looks after them?"

SCRIPT = r'''
import json, os, sys
KIND, MODE, VERSION = {kind!r}, {mode!r}, {version!r}
sys.path[:0] = [{tests!r}, {root!r}]
args = sys.argv[1:]
if "--version" in args:
    print(VERSION)
    sys.exit(0)
if KIND == "opencode":
    task = open(args[args.index("--file") + 1], encoding="utf-8").read()
else:
    task = sys.stdin.read()
log = os.environ.get("FAKE_HARNESS_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({{"kind": KIND, "mode": MODE, "argv": args, "cwd": os.getcwd(),
                             "listing": sorted(os.listdir(os.getcwd())), "task": task, "env": sorted(os.environ),
                             "config": os.environ.get("OPENCODE_CONFIG_CONTENT")}}) + "\n")
if MODE == "fail":
    answer = ""
elif "Reply with the single word OK." in task:
    answer = "OK"
elif "You are Rihma, the analyst" in task:
    answer = "```json\n" + json.dumps({{"reply": {shape!r}, "ready": False, "ready_why": "it does not say who it is for",
                                        "draft": {{"title": "Equipment loans",
                                                   "problem": "Nobody knows who has borrowed the drills."}}}}) + "\n```"
elif "The question:\n<<<" in task:
    answer = "```json\n" + json.dumps({{"answer": {assistant!r}, "navigate": None, "propose": [], "sources": []}}) + "\n```"
elif "You review a change" in task:
    answer = "```json\n" + json.dumps({{"findings": []}}) + "\n```"
else:
    from factory_fakes import script
    answer = script(task, "analyst")
model = "deepseek-v4-pro" if MODE == "deepseek" else "claude-sonnet-4-5-20250929"
if KIND == "claude-code":
    if MODE == "fail":
        print(json.dumps({{"type": "result", "subtype": "error_during_execution", "is_error": True,
                          "errors": ["not logged in"]}}))
        sys.exit(1)
    print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": answer,
                      "duration_ms": 1200, "num_turns": 1, "session_id": "s-1", "total_cost_usd": 0.0123,
                      "usage": {{"input_tokens": 120, "output_tokens": 40, "cache_creation_input_tokens": 5,
                                "cache_read_input_tokens": 7}},
                      "modelUsage": {{model: {{"inputTokens": 120, "outputTokens": 40, "costUSD": 0.0123}}}}}}))
elif KIND == "codex":
    print(json.dumps({{"type": "thread.started", "thread_id": "t-1"}}))
    if MODE == "fail":
        print(json.dumps({{"type": "turn.failed", "error": {{"message": "not signed in"}}}}))
        sys.exit(1)
    print(json.dumps({{"type": "item.completed", "item": {{"id": "i-1", "type": "agent_message", "text": answer}}}}))
    print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 90, "cached_input_tokens": 10,
                                                          "output_tokens": 30}}}}))
else:
    print(json.dumps({{"type": "step_start", "part": {{"type": "step-start"}}}}))
    print(json.dumps({{"type": "text", "part": {{"type": "text", "text": answer}}}}))
    print(json.dumps({{"type": "step_finish", "part": {{"type": "step-finish", "cost": 0.002,
                      "tokens": {{"input": 70, "output": 20, "reasoning": 0, "cache": {{"read": 3, "write": 0}}}}}}}}))
'''


def fake_agent(folder: Path, kind: str, mode: str = "good", *, version: str | None = None) -> list[str]:
    """Write a fake ``kind`` coding agent in ``mode`` to ``folder``; the command that starts it."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"agent-{kind}-{mode}.py"
    tests = Path(__file__).resolve().parent
    path.write_text(SCRIPT.format(kind=kind, mode=mode, version=version or VERSIONS[kind], tests=str(tests),
                                  root=str(tests.parent), shape=SHAPE_REPLY, assistant=ASSISTANT_ANSWER),
                    encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return [Path(sys.executable).as_posix(), path.as_posix()]
