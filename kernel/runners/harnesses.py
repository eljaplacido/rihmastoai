"""The opt-in runners: Claude Code, Codex, OpenCode and a command a team names (D-0019, FR-HRN1).

Each is started headless in the working copy, with its tools held to the working copy as far as the harness lets
a caller say so, and asked never to prompt:

- **Claude Code**: ``claude -p --output-format stream-json --verbose --permission-mode dontAsk`` with
  ``--allowedTools`` Read, Glob, Grep, Edit, Write and Bash for a builder (read tools and ``git diff|log|show`` for a
  verifier), web tools disallowed; the prompt on standard input.
- **Codex**: ``codex exec --json`` with its own ``workspace-write`` sandbox (``read-only`` for a verifier),
  approvals ``never``, ``-C <workdir>``; the prompt on standard input (``-``).
- **OpenCode**: ``opencode run --format json --auto`` with the task file attached, edits denied to a verifier and the
  web denied to both through ``OPENCODE_CONFIG_CONTENT``.
- **A command**: the team's command line with ``{prompt_file}``, ``{workdir}`` and ``{role}`` filled in; the prompt also
  on standard input. A line of its output that is a JSON object with a ``tool`` is read as a tool call.

None of this is the factory's enforcement: whatever the harness did, the glue checks the result after the run.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

from kernel.runners import RunnerRefused
from kernel.runners.base import Runner

TARGET_KEYS = ("file_path", "path", "filePath", "command", "pattern", "url", "query")


def _json_lines(stdout: str) -> list[dict[str, Any]]:
    out = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def _target(args: Any) -> str:
    if isinstance(args, dict):
        for key in TARGET_KEYS:
            value = args.get(key)
            if isinstance(value, list):
                value = " ".join(str(v) for v in value)
            if isinstance(value, str) and value:
                return value[:300]
    return ""


class ClaudeCode(Runner):
    name = "claude-code"
    BUILDER_TOOLS = "Read,Glob,Grep,Edit,Write,Bash"
    VERIFIER_TOOLS = "Read,Glob,Grep,Bash(git diff:*),Bash(git log:*),Bash(git show:*)"

    def argv(self, cmd: list[str], prompt_file: Path, workdir: Path, role: str) -> list[str]:
        tools = self.BUILDER_TOOLS if role == "builder" else self.VERIFIER_TOOLS
        model = self.choice.get("model")
        return [*cmd, "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "dontAsk",
                "--allowedTools", tools, "--disallowedTools", "WebFetch,WebSearch",
                *(["--model", model] if model else [])]

    def parse(self, stdout: str) -> dict[str, Any]:
        calls, model, output, stop = [], self.choice.get("model"), "", "answered"
        for obj in _json_lines(stdout):
            kind = obj.get("type")
            if kind == "system" and obj.get("model"):
                model = obj["model"]
            elif kind == "assistant":
                message = obj.get("message") or {}
                for part in message.get("content") or []:
                    if isinstance(part, dict) and part.get("type") == "tool_use":
                        calls.append({"tool": str(part.get("name")), "target": _target(part.get("input"))})
            elif kind == "result":
                output = str(obj.get("result") or "")
                stop = "error" if obj.get("is_error") else str(obj.get("subtype") or "answered")
        return {"tool_calls": calls, "model": model, "output": output, "stop_reason": stop}


class Codex(Runner):
    name = "codex"

    def argv(self, cmd: list[str], prompt_file: Path, workdir: Path, role: str) -> list[str]:
        sandbox = "workspace-write" if role == "builder" else "read-only"
        model = self.choice.get("model")
        return [*cmd, "exec", "--json", "--sandbox", sandbox, "-c", 'approval_policy="never"', "--skip-git-repo-check",
                "-C", str(workdir), *(["--model", model] if model else []), "-"]

    @staticmethod
    def _call(obj: dict[str, Any], item: dict[str, Any], kind: str) -> dict[str, str] | None:
        """A tool call in one of Codex's events (its item events, or the older begin events), or None."""
        if obj.get("type") == "item.completed" and kind in ("command_execution", "file_change", "mcp_tool_call"):
            changes = [str(c.get("path")) for c in item.get("changes") or [] if isinstance(c, dict)]
            return {"tool": kind, "target": str(item.get("command") or " ".join(changes))[:300]}
        if kind in ("exec_command_begin", "patch_apply_begin"):
            return {"tool": kind, "target": _target(item)}
        return None

    def parse(self, stdout: str) -> dict[str, Any]:
        calls, output, stop = [], "", "answered"
        for obj in _json_lines(stdout):
            given = obj.get("item") if isinstance(obj.get("item"), dict) else obj.get("msg")
            item: dict[str, Any] = given if isinstance(given, dict) else {}
            kind = str(item.get("type") or "")
            call = self._call(obj, item, kind)
            if call:
                calls.append(call)
            elif kind == "agent_message":
                output = str(item.get("text") or item.get("message") or output)
            elif obj.get("type") == "turn.failed":
                stop = "error"
        return {"tool_calls": calls, "model": self.choice.get("model"), "output": output, "stop_reason": stop}


class OpenCode(Runner):
    name = "opencode"
    stdin = False

    def argv(self, cmd: list[str], prompt_file: Path, workdir: Path, role: str) -> list[str]:
        model = self.choice.get("model")
        return [*cmd, "run", "--format", "json", "--auto", "--file", str(prompt_file),
                *(["--model", model] if model else []),
                "Do the task in the attached file, in this folder, then report as it asks."]

    def extra_env(self, role: str) -> dict[str, str]:
        rules = {"webfetch": "deny", **({} if role == "builder" else {"edit": "deny"})}
        return {"OPENCODE_CONFIG_CONTENT": json.dumps({"permission": rules})}

    def parse(self, stdout: str) -> dict[str, Any]:
        calls, texts = [], []
        for obj in _json_lines(stdout):
            given = obj.get("part")
            part: dict[str, Any] = given if isinstance(given, dict) else {}
            if obj.get("type") == "tool_use" or part.get("type") == "tool":
                held = part.get("state")
                state: dict[str, Any] = held if isinstance(held, dict) else {}
                calls.append({"tool": str(part.get("tool") or obj.get("tool") or "tool"),
                              "target": _target(state.get("input"))})
            elif obj.get("type") == "text" or part.get("type") == "text":
                texts.append(str(part.get("text") or obj.get("text") or ""))
        return {"tool_calls": calls, "model": self.choice.get("model"), "output": "\n".join(texts).strip()}


class Command(Runner):
    name = "command"

    def argv(self, cmd: list[str], prompt_file: Path, workdir: Path, role: str) -> list[str]:
        from kernel.runners.detect import split

        template = self.choice.get("command")
        if not isinstance(template, str) or not template.strip():
            raise RunnerRefused("the command runner needs its command line")
        words = split(template)
        if not any("{prompt_file}" in w for w in words):
            raise RunnerRefused("the command line must say where the task goes: {prompt_file}")
        fill = {"{prompt_file}": str(prompt_file), "{workdir}": str(workdir), "{role}": role}
        filled = [functools.reduce(lambda w, kv: w.replace(*kv), fill.items(), word) for word in words]
        return [*cmd, *filled[1:]] if cmd else filled

    def parse(self, stdout: str) -> dict[str, Any]:
        calls = [{"tool": str(o["tool"]), "target": _target(o) or str(o.get("target") or "")[:300]}
                 for o in _json_lines(stdout) if "tool" in o]
        text = "\n".join(line for line in stdout.splitlines() if not line.strip().startswith("{")).strip()
        return {"tool_calls": calls, "model": self.choice.get("model"), "output": text[-20000:]}


HARNESSES: dict[str, type[Runner]] = {"claude-code": ClaudeCode, "codex": Codex, "opencode": OpenCode,
                                      "command": Command}


def runner_for(name: str, choice: dict[str, Any] | None = None) -> Runner:
    if name not in HARNESSES:
        raise RunnerRefused(f"{name!r} is not a runner that runs beside Gnomon; they are {', '.join(HARNESSES)}")
    return HARNESSES[name](choice)
