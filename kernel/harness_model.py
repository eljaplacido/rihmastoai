"""Harness-backed models: the coding agent a person already has answers for a role (FR-HMD1).

docs/guides/harness-models.md is the guide. Gnomon reaches models through `openai` and `ollama` endpoints only. A
text role (the analyst, the holdout author, the verifier, the assistant) whose endpoint in the routing is
``{"kind": "harness", "harness": "claude-code"}`` (Models setup, `rihmasto models use`) is answered by that harness,
run headless as a pure text completion:

- **Claude Code**: ``claude -p --output-format json --tools ""`` with MCP servers and sessions off, the role's rules
  as the whole system prompt and the task on standard input.
- **Codex**: ``codex exec --json --sandbox read-only`` with approvals ``never``, the task on standard input.
- **OpenCode**: ``opencode run --format json`` with every tool switched off and denied, the task attached as a file.
- **A command you name**: its line with ``{prompt_file}`` and ``{role}`` filled in, the task also on standard input.

Every run starts in an empty temporary folder, with an environment that leaves out where the factory keeps its
home, lanes and keys (kernel/runners/base.py ``harness_env``): no harness is given the repository, the contract or
the holdout custody. A prompt for any role but the holdout author that holds a holdout scenario's text is refused
before anything runs. The verifier, which has no tools here, is given the change's diff in its task instead.

The builder never runs here: it writes code, so its harness is a cell runner (kernel/runners, D-0019). A harness is
never a fallback. Gnomon is not asked for these roles: its surface keeps a placeholder endpoint for them that nothing
listens on (``gnomon_endpoint``), so a Gnomon call for one fails closed instead of reaching another model.

Each call is a ``model_run`` in the ledger (the project's, else the factory's): role, harness, version, model, tokens,
cost, time, and **run by <harness>, not through Gnomon's lane: no Gnomon audit trail for this call**.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import tempfile
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any

KIND = "harness"
HARNESSES: dict[str, dict[str, Any]] = {
    "claude-code": {"label": "Claude Code", "family": "claude", "hosted": True},
    "codex": {"label": "Codex", "family": "gpt", "hosted": True},
    "opencode": {"label": "OpenCode", "family": None, "hosted": False},     # local only when declared private
    "command": {"label": "A command you name", "family": None, "hosted": False},
}
TEXT_ROLES = ("analyst", "holdout_author", "verifier", "assistant")
# Gnomon's surface names an endpoint for every role; a harness role's points where nothing listens (the discard port).
PLACEHOLDER_URL = "http://127.0.0.1:9/v1/chat/completions"
ASSURANCE = "run by {label}, not through Gnomon's lane: no Gnomon audit trail for this call"
INSTRUCTION = "Answer the task given on standard input. You have no tools: answer from the task alone."
FILE_INSTRUCTION = "Answer the task in the attached file. You have no tools: answer from the task alone."
VERIFIER_RULES = """You review a change for Rihma, a governed software factory. You have no tools and need none: the
task holds the criteria and the change's diff. Try to break the change; report only what the task asks for.
When the task asks for JSON, answer with one JSON value in a ```json fenced block, and nothing after it.
"""
DIFF_LIMIT = 200_000
HELD_MIN = 16                    # a scenario's string this long, not in the spec or contract, is never sent
DETECT_TTL = 60.0
_DIFF = re.compile(r"`git diff ([0-9a-f]{7,40})(?: -- ([^`]+))?`")
_PROJECT: ContextVar[Any] = ContextVar("harness_project", default=None)
_FOUND: dict[tuple, tuple[float, dict[str, Any]]] = {}


class HarnessRefused(ValueError):
    """A harness route or run Rihmasto does not take, with the reason."""


def label_of(name: str) -> str:
    return str(HARNESSES.get(name, {}).get("label") or name)


def default_model(name: str) -> str:      # the routing's name for "the model the harness is set to use"
    return f"{name}-default"


# -- the routing ----------------------------------------------------------------------------------------

def _dict(value: Any) -> dict[str, Any]:
    """A harness's JSON object, or an empty one when its output has something else there."""
    return {str(k): v for k, v in value.items()} if isinstance(value, dict) else {}


def is_harness(endpoint: Any) -> bool:
    return isinstance(endpoint, dict) and endpoint.get("kind") == KIND


def hosted(endpoint: Any) -> bool:
    """Whether a harness endpoint's model is hosted whatever its owner declares: Claude Code's and Codex's are."""
    return is_harness(endpoint) and bool(HARNESSES.get(str(endpoint.get("harness")), {}).get("hosted"))


def gnomon_endpoint(endpoint: dict[str, Any]) -> dict[str, Any]:
    """The endpoint as Gnomon's surface names it: a harness endpoint becomes a placeholder nothing answers on."""
    return {"kind": "openai", "url": PLACEHOLDER_URL} if is_harness(endpoint) else endpoint


def route_of(routing: dict[str, Any], role: str) -> dict[str, Any] | None:
    """The harness that answers ``role``, or None when its primary endpoint is not a harness."""
    spec = (routing.get("roles") or {}).get(role)
    if not isinstance(spec, dict):
        return None
    ep = _dict((routing.get("endpoints") or {}).get(spec.get("endpoint")))
    if not is_harness(ep):
        return None
    name, model = str(ep.get("harness") or ""), str(spec.get("model") or "")
    family = ((routing.get("models") or {}).get(model) or {}).get("family") or HARNESSES.get(name, {}).get("family")
    return {"role": role, "endpoint": spec.get("endpoint"), "harness": name, "label": label_of(name),
            "model": "" if model == default_model(name) else model, "family": family,
            "private": ep.get("private") is True, "command": ep.get("command"), "version": ep.get("version")}


def check_harness_routes(routing: dict[str, Any]) -> None:
    """A harness answers a text role, as a primary endpoint, with its model family known (FR-G6 needs it)."""
    endpoints = routing.get("endpoints") or {}
    for role, spec in (routing.get("roles") or {}).items():
        if not isinstance(spec, dict):
            continue
        fb = spec.get("fallback")
        if isinstance(fb, dict) and is_harness(endpoints.get(fb.get("endpoint"))):
            raise ValueError(f"the {role}'s fallback is a harness: a harness answers as a role's own endpoint, "
                             "never as a fallback")
        route = route_of(routing, role)
        if route is None:
            continue
        if route["harness"] not in HARNESSES:
            raise ValueError(f"the {role}'s endpoint names no known harness ({route['harness']!r}); they are "
                             f"{', '.join(HARNESSES)}")
        if role == "builder":
            raise ValueError("the builder writes code, so its harness is a cell runner, not a model: "
                             f"rihmasto runners set builder {route['harness']} (docs/guides/harnesses.md)")
        if not route["family"]:
            raise ValueError(f"name the model family {route['label']} answers with for the {role} (--family): "
                             "the verifier must be another family than the builder")
        if route["harness"] == "command" and not str(route.get("command") or "").strip():
            raise ValueError(f"the {role}'s command harness needs its command line")


def _routing() -> dict[str, Any]:
    from kernel.lanes import read_routing

    try:
        return read_routing() or {}
    except ValueError:            # an unreadable overlay: Gnomon's path says so in its own words
        return {}


# -- the project a call is for ----------------------------------------------------------------------------

class ForProject:
    """A model whose calls are for ``project``: a harness call records its ``model_run`` in that project's ledger and
    is checked against that project's holdouts. Everything else is the wrapped model's."""

    def __init__(self, model: Any, project: Any) -> None:
        self.model, self.project = model, project

    def ask(self, prompt: str, *, role: str) -> str:
        token = _PROJECT.set(self.project)
        try:
            return str(self.model.ask(prompt, role=role))
        finally:
            _PROJECT.reset(token)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.model, name)


def for_project(project: Any, model: Any, roles: Any) -> Any:
    """``model`` bound to ``project`` when one of ``roles`` is answered by a harness; else ``model`` as it is."""
    if model is None or project is None:
        return model
    routing = _routing()
    return ForProject(model, project) if any(route_of(routing, r) for r in roles) else model


# -- detection --------------------------------------------------------------------------------------------

def choice_of(route: dict[str, Any]) -> dict[str, Any]:
    return {"command": route.get("command")} if route.get("harness") == "command" else {}


def detect(name: str, route: dict[str, Any] | None = None, *, fresh: bool = False) -> dict[str, Any]:
    """Whether harness ``name`` is on this machine and its version (kernel/runners/detect.py), kept a minute."""
    from kernel.runners.detect import detect as look
    from kernel.runners.detect import env_name

    choice = choice_of(route or {"harness": name})
    key = (name, os.environ.get(env_name(name)), str(choice.get("command") or ""))
    held = _FOUND.get(key)
    if held and not fresh and time.monotonic() - held[0] < DETECT_TTL:
        return held[1]
    found = look(name, choice)
    _FOUND[key] = (time.monotonic(), found)
    return found


# -- one run ----------------------------------------------------------------------------------------------

def system_rules(role: str) -> str:
    from kernel.lanes import ANALYST_RULES

    return VERIFIER_RULES if role == "verifier" else ANALYST_RULES


def _argv(name: str, cmd: list[str], route: dict[str, Any], prompt_file: Path, work: Path,
          role: str) -> tuple[list[str], bool, dict[str, str]]:
    """The command line, whether the task goes on standard input, and the extra environment."""
    model = route.get("model") or ""
    pick = ["--model", model] if model else []
    if name == "claude-code":
        return [*cmd, "-p", INSTRUCTION, "--output-format", "json", "--tools", "", "--disallowedTools", "mcp__*",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--no-session-persistence",
                "--permission-mode", "dontAsk", "--system-prompt", system_rules(role), *pick], True, {}
    if name == "codex":
        return [*cmd, "exec", "--json", "--sandbox", "read-only", "-c", 'approval_policy="never"',
                "--skip-git-repo-check", "-C", str(work), *pick, "-"], True, {}
    if name == "opencode":
        off = ("*", "read", "write", "edit", "patch", "bash", "glob", "grep", "list", "webfetch", "task", "todowrite",
               "todoread")
        conf = {"tools": {t: False for t in off}, "permission": {"edit": "deny", "bash": "deny", "webfetch": "deny"}}
        return ([*cmd, "run", "--format", "json", "--file", str(prompt_file), *pick, FILE_INSTRUCTION], False,
                {"OPENCODE_CONFIG_CONTENT": json.dumps(conf)})
    from kernel.runners.detect import split

    words = split(str(route.get("command") or ""))
    filled = [w.replace("{prompt_file}", str(prompt_file)).replace("{role}", role) for w in words]
    return ([*cmd, *filled[1:]] if cmd else filled), True, {}


def _objects(stdout: str) -> list[dict[str, Any]]:
    out, text = [], (stdout or "").strip()
    with contextlib.suppress(ValueError):
        whole = json.loads(text)
        if isinstance(whole, dict):
            return [whole]
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            with contextlib.suppress(ValueError):
                obj = json.loads(line)
                if isinstance(obj, dict):
                    out.append(obj)
    return out


def _num(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _parse_claude(objs: list[dict[str, Any]]) -> dict[str, Any]:
    res: dict[str, Any] = next((o for o in reversed(objs) if o.get("type") == "result"), {})
    usage, by_model = _dict(res.get("usage")), _dict(res.get("modelUsage"))
    model = max(by_model, key=lambda m: _num(_dict(by_model[m]).get("outputTokens")), default=None)
    error = ""
    if not res:
        error = "no result in its output"
    elif res.get("is_error") or res.get("subtype") not in (None, "success"):
        error = "; ".join(str(e) for e in res.get("errors") or []) or str(res.get("result") or res.get("subtype"))
    return {"output": str(res.get("result") or ""), "model": model, "error": error,
            "usage": {"input": _num(usage.get("input_tokens")), "output": _num(usage.get("output_tokens")),
                      "cache_read": _num(usage.get("cache_read_input_tokens")),
                      "cache_write": _num(usage.get("cache_creation_input_tokens"))},
            "cost_usd": res.get("total_cost_usd") if isinstance(res.get("total_cost_usd"), (int, float)) else None}


def _parse_codex(objs: list[dict[str, Any]]) -> dict[str, Any]:
    output, error, usage = "", "", {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for o in objs:
        item = _dict(o.get("item"))
        if item.get("type") == "agent_message":
            output = str(item.get("text") or output)
        elif o.get("type") == "turn.completed" and isinstance(o.get("usage"), dict):
            u = _dict(o["usage"])
            usage = {"input": _num(u.get("input_tokens")), "output": _num(u.get("output_tokens")),
                     "cache_read": _num(u.get("cached_input_tokens")), "cache_write": 0}
        elif o.get("type") in ("turn.failed", "error"):
            error = str(_dict(o.get("error")).get("message") or o.get("message") or "the turn failed")
    return {"output": output, "model": None, "error": error, "usage": usage, "cost_usd": None}


def _parse_opencode(objs: list[dict[str, Any]]) -> dict[str, Any]:
    texts: list[str] = []
    error, cost, model = "", None, None
    usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for o in objs:
        part = _dict(o.get("part"))
        if o.get("type") == "text" or part.get("type") == "text":
            texts.append(str(part.get("text") or o.get("text") or ""))
        elif o.get("type") in ("step_finish", "step-finish") or part.get("type") == "step-finish":
            tokens = _dict(part.get("tokens"))
            cache = _dict(tokens.get("cache"))
            for key, value in (("input", tokens.get("input")), ("output", tokens.get("output")),
                               ("cache_read", cache.get("read")), ("cache_write", cache.get("write"))):
                usage[key] += _num(value)
            if isinstance(part.get("cost"), (int, float)):
                cost = (cost or 0.0) + float(part["cost"])
            model = part.get("modelID") or model
        elif o.get("type") == "error":
            given = _dict(o.get("error"))
            error = str(given.get("message") or _dict(given.get("data")).get("message") or "an error")
    return {"output": "\n".join(t for t in texts if t).strip(), "model": model, "error": error, "usage": usage,
            "cost_usd": cost}


def _parse_command(stdout: str, objs: list[dict[str, Any]]) -> dict[str, Any]:
    last = next((o for o in reversed(objs) if "output" in o), None)
    if last is None:
        return {"output": (stdout or "").strip()[-50000:], "model": None, "error": "", "usage": {}, "cost_usd": None}
    usage = last.get("usage") if isinstance(last.get("usage"), dict) else {}
    return {"output": str(last.get("output") or ""), "model": last.get("model"), "error": str(last.get("error") or ""),
            "usage": {k: _num(usage.get(k)) for k in ("input", "output", "cache_read", "cache_write")},
            "cost_usd": last.get("cost_usd") if isinstance(last.get("cost_usd"), (int, float)) else None}


def parse(name: str, stdout: str) -> dict[str, Any]:
    """The answer, the model, the token use and the cost a harness's output shows; ``error`` when it failed."""
    objs = _objects(stdout)
    if name == "claude-code":
        return _parse_claude(objs)
    if name == "codex":
        return _parse_codex(objs)
    if name == "opencode":
        return _parse_opencode(objs)
    return _parse_command(stdout, objs)


def run(route: dict[str, Any], prompt: str, *, role: str, timeout: int = 900) -> dict[str, Any]:
    """Ask ``route``'s harness once, in an empty folder, as a text completion. A record in Gnomon's shape: ``output``,
    ``bucket`` ("result" or "apparatus_failure"), ``stop_reason``, ``model``, with the harness, its version, the
    token use and cost, the time taken and the assurance. Writes nothing to any ledger."""
    from kernel.runners.base import harness_env
    from kernel.runners.detect import command_of

    name = route["harness"]
    found = detect(name, route)
    record: dict[str, Any] = {
        "role": role, "harness": {"name": name, "label": label_of(name), "version": found.get("version")},
        "model": route.get("model") or None, "family": route.get("family"), "usage": {}, "cost_usd": None,
        "seconds": 0.0, "output": "", "assurance": ASSURANCE.format(label=label_of(name)), "bucket": "result"}
    if not found["found"]:
        return record | {"bucket": "apparatus_failure", "stop_reason": found["why"]}
    text = prompt if name == "claude-code" else f"{system_rules(role)}\n---\n\n{prompt}"
    clock = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="rihmasto-harness-") as tmp:
        work, task = Path(tmp) / "work", Path(tmp) / "task"
        for folder in (work, task):
            folder.mkdir()
        prompt_file = task / "task.md"
        prompt_file.write_text(text, encoding="utf-8", newline="\n")
        try:
            argv, stdin, extra = _argv(name, command_of(name, choice_of(route)), route, prompt_file, work, role)
            proc = subprocess.run(argv, cwd=work, input=text if stdin else None, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout, env=harness_env() | extra,
                                  stdin=None if stdin else subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return record | {"bucket": "apparatus_failure", "seconds": round(time.monotonic() - clock, 3),
                             "stop_reason": f"{label_of(name)} did not answer in {timeout}s"}
        except (OSError, ValueError) as exc:
            return record | {"bucket": "apparatus_failure", "stop_reason": f"{label_of(name)} could not start: {exc}"}
    seen = parse(name, proc.stdout or "")
    record |= {"output": seen["output"], "model": seen.get("model") or record["model"], "usage": seen["usage"],
               "cost_usd": seen["cost_usd"], "seconds": round(time.monotonic() - clock, 3), "_exit": proc.returncode,
               "stop_reason": "answered"}
    tail = " ".join((proc.stderr or "").strip().splitlines()[-3:])[:400]
    if proc.returncode != 0 or seen["error"] or not seen["output"].strip():
        why = seen["error"] or tail or ("no answer" if proc.returncode == 0 else "no message")
        record |= {"bucket": "apparatus_failure", "stop_reason": f"{label_of(name)} exit {proc.returncode}: {why}"}
    return record


# -- the guard every Gnomon call passes (kernel/model.py run_gnomon_task) -----------------------------------

def _held(project: Any) -> list[str]:
    """The project's holdout scenarios' strings that its spec and contract do not already show, long ones only."""
    from kernel.custody import _scenario_values, _visible

    folder = Path(project.holdouts_dir)
    if not folder.is_dir():
        return []
    visible = _visible(project.factory.projects_dir, project.pid, lambda path: True)
    found = {s.strip() for path in sorted(folder.glob("*.json")) for s in _scenario_values(path)}
    return [s for s in found if len(s) >= HELD_MIN and s not in visible]


def refuse_held(project: Any, prompt: str, role: str) -> None:
    """A task for any role but the holdout author that quotes one of the project's holdout scenarios is not sent."""
    if role == "holdout_author" or project is None:
        return
    if any(s in prompt for s in _held(project)):
        raise HarnessRefused(f"refused: the {role}'s task holds text of a holdout scenario, which only the holdout "
                             "author is given; nothing was sent")


def with_diff(cwd: Path, prompt: str) -> str:
    """The verifier's task with the change it reviews: it has no tools here, so the diff its task names is given."""
    from kernel.lanes import _git

    m = _DIFF.search(prompt)
    if m is None:
        return prompt
    paths = (m.group(2) or "").split()
    diff = _git(Path(cwd), "-c", "core.quotePath=false", "diff", "--no-color", "--no-ext-diff", "--no-textconv",
                m.group(1), "--", *paths, check=False)
    cut = "\n[... the diff is cut here ...]" if len(diff) > DIFF_LIMIT else ""
    return (f"{prompt.rstrip()}\n\n## The change ({m.group(0)}), given here because you have no tools\n\n"
            f"```diff\n{diff[:DIFF_LIMIT]}{cut}\n```\n")


def _builder_family(project: Any, routing: dict[str, Any]) -> str | None:
    from kernel.access_isolation import served
    from kernel.lanes import model_family
    from kernel.runners import choice

    factory = project.factory if project is not None else served()
    with contextlib.suppress(Exception):     # an unreadable choice: the routing's builder is the word
        if factory is not None:
            return choice.family_of(choice.effective(factory, getattr(project, "pid", None), "builder"), "builder")
    return model_family(routing, "builder") if "builder" in (routing.get("roles") or {}) else None


def check_family(route: dict[str, Any], record: dict[str, Any], project: Any, routing: dict[str, Any]) -> None:
    """The family the harness answered with, from the model its output names. A verifier that answered with the
    builder's family gives no verdict (FR-G6)."""
    from kernel.models_setup import family_of

    seen = family_of(str(record["model"])) if record.get("model") and record["model"] != route.get("model") else None
    record["family"] = seen or route.get("family")
    if seen and route.get("family") and seen != str(route["family"]).lower():
        record["family_declared"] = route["family"]
    builder = _builder_family(project, routing) if route["role"] == "verifier" else None
    if builder and str(record["family"]).lower() == str(builder).lower():
        record |= {"bucket": "apparatus_failure", "output": "",
                   "stop_reason": f"the verifier answered with {record['model'] or route['label']} (family "
                                  f"{record['family']}), the builder's family: no verdict from it"}


def record_run(project: Any, record: dict[str, Any]) -> None:
    """The call as a ``model_run`` in the project's ledger, else the factory's own. Never the prompt or answer."""
    from kernel.access_isolation import served
    from kernel.learn import factory_project

    h = record["harness"]
    payload = {"role": record["role"], "harness": h["name"], "label": h["label"], "version": h["version"],
               "model": record.get("model"), "family": record.get("family"), "tokens": record.get("usage") or {},
               "cost_usd": record.get("cost_usd"), "seconds": record.get("seconds"),
               "ok": record.get("bucket") == "result", "stop_reason": record.get("stop_reason"),
               "assurance": record["assurance"], "task": record.get("task")}
    with contextlib.suppress(OSError):
        if project is not None:
            project.log("model_run", payload)
            return
        factory = served()
        if factory is not None:
            factory_project(factory).log("model_run", payload | {"project": None})


def answer(cwd: str | Path, prompt: str, *, role: str, timeout: int = 900) -> dict[str, Any] | None:
    """The record of a harness's answer when ``role`` is answered by a harness; None when Gnomon answers it."""
    from kernel import model_usage
    from kernel.model import ModelError

    routing = _routing()
    route = route_of(routing, role)
    if route is None:
        return None
    if role not in TEXT_ROLES:
        raise ModelError(f"the {role} is not a text role: its harness is a cell runner (docs/guides/harnesses.md)")
    project, task = _PROJECT.get() or model_usage.current()[0], model_usage.current()[1]   # bound, or the block's
    try:
        refuse_held(project, prompt, role)
    except HarnessRefused as exc:
        raise ModelError(str(exc)) from None
    if role == "verifier":
        prompt = with_diff(Path(cwd), prompt)
    record = run(route, prompt, role=role, timeout=timeout)
    check_family(route, record, project, routing)
    record_run(project, record | {"task": task})
    return record


class HarnessModel:
    """A Model (kernel/model.py) answered by one harness for every role it is asked as, without the routing."""

    def __init__(self, harness: str, *, model: str = "", family: str | None = None, command: str | None = None,
                 timeout: int = 900) -> None:
        self.route = {"harness": harness, "label": label_of(harness), "model": model, "command": command,
                      "family": family or HARNESSES.get(harness, {}).get("family")}
        self.timeout = timeout
        self.last_record: dict[str, Any] | None = None

    def ask(self, prompt: str, *, role: str) -> str:
        from kernel.model import ModelError

        record = run(self.route | {"role": role}, prompt, role=role, timeout=self.timeout)
        self.last_record = record
        if record["bucket"] != "result":
            raise ModelError(str(record.get("stop_reason")))
        return str(record["output"])
