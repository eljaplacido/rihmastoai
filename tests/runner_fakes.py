"""Fake harness executables for the cell-runner tests (FR-HRN1): small Python scripts that behave like each CLI.

No real Claude Code, Codex or OpenCode runs in a test, and no model or network is used. ``fake_harness`` writes a
script that answers ``--version`` as the real one does, reads its task (standard input, or the file OpenCode is
given), does what its mode says in its working folder, and prints its tool calls in the harness's own output shape.
It writes what it was given (its arguments, its task, the names of its environment variables, and any holdout it
could find) to ``$FAKE_HARNESS_LOG``, so a test can see what reached it.

Modes: ``good`` meets T-001 inside its write scope; ``protected`` also edits contract.json; ``outside`` also writes
docs/notes.md; ``holdouts`` looks for the holdout custody from its folder and its environment, then meets T-001;
``review`` answers as a verifier with no findings; ``lazy`` writes a test that cannot fail.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

from factory_fakes import GOOD_ROUTES, GOOD_TEST, TRIVIAL_TEST

VERSIONS = {"claude-code": "2.1.0 (Claude Code)", "codex": "codex-cli 0.50.0", "opencode": "opencode v1.2.3",
            "command": "agent 3.1.0"}
HOLDOUT_MARK = "HOLDOUT-SCENARIO-MARK-7f3a"

SCRIPT = r'''
import json, os, sys
KIND, MODE, VERSION = {kind!r}, {mode!r}, {version!r}
GOOD_ROUTES, GOOD_TEST, TRIVIAL_TEST, MARK = {routes!r}, {test!r}, {trivial!r}, {mark!r}
args = sys.argv[1:]
if "--version" in args:
    print(VERSION)
    sys.exit(0)
if KIND == "opencode":
    task = open(args[args.index("--file") + 1], encoding="utf-8").read()
else:
    task = sys.stdin.read()
found = []
named = ("RIHMA", "GNOMON", "HOLDOUT", "GF_")      # where a factory would say its home, lanes or custody are
seen = [os.getcwd()] + [v for k, v in os.environ.items() if any(t in k.upper() for t in named) and os.path.isdir(v)]
if MARK in task:
    found.append("the task")
if MODE == "holdouts":
    for top in seen:
        for root, dirs, files in os.walk(top):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")][:50]
            for name in files[:200]:
                try:
                    if MARK in open(os.path.join(root, name), encoding="utf-8", errors="replace").read():
                        found.append(os.path.join(root, name))
                except OSError:
                    pass
writes = []


def put(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    writes.append(path)


if MODE in ("good", "protected", "outside", "holdouts"):
    put("app/routes.py", GOOD_ROUTES)
    put("tests/test_items.py", GOOD_TEST)
if MODE == "lazy":
    put("tests/test_items.py", TRIVIAL_TEST)
if MODE == "protected":
    with open("contract.json", "a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n")
    writes.append("contract.json")
if MODE == "outside":
    put("docs/notes.md", "notes\n")
log = os.environ.get("FAKE_HARNESS_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({{"kind": KIND, "mode": MODE, "argv": args, "cwd": os.getcwd(), "task": task,
                             "env": sorted(os.environ), "found": found}}) + "\n")
answer = "```json\n" + json.dumps({{"findings": []}}) + "\n```" if MODE == "review" else "done: " + ", ".join(writes)
if KIND == "claude-code":
    print(json.dumps({{"type": "system", "subtype": "init", "model": "fake-claude"}}))
    for w in writes:
        print(json.dumps({{"type": "assistant", "message": {{"content": [
            {{"type": "tool_use", "name": "Write", "input": {{"file_path": w}}}}]}}}}))
    print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": answer}}))
elif KIND == "codex":
    for w in writes:
        print(json.dumps({{"type": "item.completed", "item": {{"type": "file_change", "changes": [{{"path": w}}]}}}}))
    print(json.dumps({{"type": "item.completed", "item": {{"type": "agent_message", "text": answer}}}}))
elif KIND == "opencode":
    for w in writes:
        state = {{"input": {{"filePath": w}}}}
        print(json.dumps({{"type": "tool_use", "part": {{"type": "tool", "tool": "write", "state": state}}}}))
    print(json.dumps({{"type": "text", "part": {{"type": "text", "text": answer}}}}))
else:
    for w in writes:
        print(json.dumps({{"tool": "write", "target": w}}))
    print(answer)
'''


def fake_harness(folder: Path, kind: str, mode: str = "good", *, version: str | None = None) -> list[str]:
    """Write a fake ``kind`` harness in ``mode`` to ``folder``; the command that starts it."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"fake-{kind}-{mode}.py"
    path.write_text(SCRIPT.format(kind=kind, mode=mode, version=version or VERSIONS[kind], routes=GOOD_ROUTES,
                                  test=GOOD_TEST, trivial=TRIVIAL_TEST, mark=HOLDOUT_MARK),
                    encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return [Path(sys.executable).as_posix(), path.as_posix()]


def use(case: object, kind: str, command: list[str]) -> None:
    """Point runner ``kind`` at ``command`` until ``case`` ends (``$RIHMASTO_RUNNER_<KIND>``)."""
    from unittest import mock

    from kernel.runners.detect import env_name

    patcher = mock.patch.dict(os.environ, {env_name(kind): json.dumps(command)})
    patcher.start()
    case.addCleanup(patcher.stop)  # type: ignore[attr-defined]


def logged(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
