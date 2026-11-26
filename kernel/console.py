"""The console (FR-CON1): run a project's commands, or ask Gnomon, in its workspace, governed like the rest.

The owner (2026-11-24): "if a user wants to run some of these things, it is possible inside Rihmasto, while
they keep developing in their chosen IDE. And if they want to run something inside a terminal in Rihmasto,
it should be possible."

**The workspace** is where a command runs: an attached repository's own folder (the person's working tree,
as attached); else the person's own open workspace on the project (kernel/workspace.py); else the console's
working copy, a clone of the project's ``repo.git`` (a built or adopted project) kept beside the workspaces
(``<lanes root>/workspaces/<pid>/console``), made at the first run and moved forward to the repository's
tip while it holds no change of its own. Its ``origin`` has no push URL: its work reaches main only through
a workspace's submission and the gate.

**A run** is a command line (offered as a button, kernel/console_offers.py, or typed), or a Gnomon task
(``gnomon task "<what to do>" [--role R] [--yes]``, under the workspace's own ``.gnomon/`` surface, with
the factory's routing compiled into the console's working copy when it has none; a confidential project's
roles must route locally, kernel/confidential.py). A command line runs as one program with its arguments,
never through a shell, unless the person asks for the shell (pipes, ``&&``, redirects). Each run:
- is allowed for the personas the project's console settings name (developer and IT unless IT changed
  them); with access enforced, the persona must also be granted on the project, and the run goes through
  IT's isolation runner (kernel/console_run.py);
- has a time limit (600 s unless asked, at most 3600 s) and a stop;
- is a job, its output kept in the job's log under ``<home>/jobs/``;
- is recorded in the project's ledger as ``console_ran``: who, which persona, the command line (known
  secret shapes masked), the workspace, how it ended, its exit code and how long it took. Never an
  environment value, and never what it printed: that stays in the job log.
"""

from __future__ import annotations

import os
import re
import secrets
import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kernel import console_offers
from kernel import console_run as crun
from kernel.canon import DecisionRefused
from kernel.people import PERSONAS, is_person
from kernel.store import Project

DEFAULT_PERSONAS = ("developer", "it")
SETTERS = ("it",)                                    # who changes which personas may use the console
STATERS = ("developer", "it", "product_owner")       # who states the project's own commands
DEFAULT_TIMEOUT, MAX_TIMEOUT = 600, 3600
MAX_LINE, MAX_PROMPT = 4000, 8000
NO_PUSH = "rihmasto-console-cannot-push://submit-through-the-gate"
GNOMON_DOCS = "docs/guides/console-and-checks.md#gnomon"
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_ROLE = re.compile(r"[a-z][a-z0-9_-]{0,40}\Z")


class ConsoleRefused(DecisionRefused):
    """A console run, a setting or a terminal the rules refuse: the reason says which (403, exit 2)."""


# -- settings ----------------------------------------------------------------------------------------------

def settings(project: Project) -> dict[str, Any]:
    """Who may use the console on this project, and the commands stated for it."""
    kept = (project.meta.get("console") or {}) if isinstance(project.meta.get("console"), dict) else {}
    personas = [p for p in kept.get("personas") or DEFAULT_PERSONAS if p in PERSONAS]
    commands = {k: v for k, v in (kept.get("commands") or {}).items() if isinstance(v, str)}
    return {"personas": personas, "commands": commands, "set_by": kept.get("set_by")}


def _signer(person: str, persona: str) -> None:
    if not is_person(person):
        raise ConsoleRefused(f"{person!r} is not a person: a console run is signed by a named person")
    if persona not in PERSONAS:
        raise ConsoleRefused(f"persona must be one of {', '.join(PERSONAS)}, got {persona!r}")


def _commands_in(commands: Any) -> dict[str, str]:
    if not isinstance(commands, dict) or len(commands) > 20:
        raise ValueError("commands is an object of at most 20 names (test, build, lint ...) to command lines")
    out = {}
    for name, line in commands.items():
        if not isinstance(name, str) or not _NAME.match(name) or not isinstance(line, str) or len(line) > MAX_LINE:
            raise ValueError(f"a stated command is a short lower-case name and a command line, got {name!r}")
        if line.strip():
            out[name] = line.strip()
    return out


def set_settings(project: Project, *, person: str, persona: str, personas: list[str] | None = None,
                 commands: dict[str, str] | None = None) -> dict[str, Any]:
    """Change who may use the console (IT) or the project's stated commands (developer, IT, product owner)."""
    _signer(person, persona)
    current = settings(project)
    if personas is not None:
        if persona not in SETTERS:
            raise ConsoleRefused(f"only {', '.join(SETTERS)} sets which personas may use the console, "
                                 f"not a {persona}")
        if not personas or any(p not in PERSONAS for p in personas):
            raise ValueError(f"personas is a list of {', '.join(PERSONAS)}")
        current["personas"] = sorted(set(personas))
    if commands is not None:
        if persona not in STATERS:
            raise ConsoleRefused(f"a {persona} does not state a project's commands: {', '.join(STATERS)} do")
        current["commands"] = _commands_in(commands)
    kept = {"personas": current["personas"], "commands": current["commands"],
            "set_by": {"person": person, "persona": persona, "at": project.factory.clock.stamp()}}
    project.update_meta(console=kept)
    project.log("console_settings", {"person": person, "persona": persona, "personas": kept["personas"],
                                     "commands": sorted(kept["commands"])})
    return settings(project)


def check_persona(project: Project, person: str, persona: str) -> None:
    """Refused unless a named person signs as a persona the console allows on this project."""
    _signer(person, persona)
    allowed = settings(project)["personas"]
    if persona not in allowed:
        raise ConsoleRefused(f"the console on {project.pid} is for {', '.join(allowed)}; a {persona} may not run "
                             "commands here (IT changes this in the console's settings)")


# -- the workspace -----------------------------------------------------------------------------------------

def _working_copy(project: Project) -> Path:
    from kernel.workspace import workspaces_root

    return workspaces_root() / project.pid / "console"


def workspace(project: Project, person: str | None = None) -> dict[str, Any]:
    """Where the console runs for ``person`` (read only: nothing is made here)."""
    attached = project.meta.get("attached") or {}
    if attached.get("repo"):
        return {"kind": "attached", "path": str(attached["repo"]), "exists": Path(attached["repo"]).is_dir(),
                "note": "your repository's own folder: commands run in your working tree, as it is"}
    own = [w for w in project.read("workspaces.json", []) or [] if person and w.get("person") == person
           and (Path(w.get("path", "")) / ".git").exists()]
    if own:
        return {"kind": "workspace", "path": own[-1]["path"], "exists": True, "branch": own[-1].get("branch"),
                "note": f"your workspace on branch {own[-1].get('branch')}: its work reaches main through the gate"}
    if project.path("repo.git").is_dir():
        path = _working_copy(project)
        return {"kind": "working_copy", "path": str(path), "exists": (path / ".git").is_dir(),
                "note": "the console's working copy of the project's repository (made at the first run); it "
                        "cannot push: work reaches main through a workspace's submission and the gate"}
    return {"kind": None, "path": None, "exists": False,
            "note": f"{project.pid} has no code yet: the console needs a repository (compile its contract, adopt "
                    "a system, or attach your repository)"}


def ensure_workspace(project: Project, person: str | None = None) -> tuple[Path, str]:
    """The workspace's folder, made or moved forward when it is the console's working copy."""
    import shutil

    from kernel.git_clone import clone_options
    from kernel.lanes import _git

    ws = workspace(project, person)
    if ws["kind"] is None:
        raise ConsoleRefused(ws["note"])
    path = Path(ws["path"])
    if ws["kind"] != "working_copy":
        if not path.is_dir():
            raise ConsoleRefused(f"the workspace {path} is not there any more")
        return path, ws["kind"]
    if not (path / ".git").is_dir():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _git(path.parent, "clone", "-q", *clone_options(), str(project.path("repo.git")), path.name)
        except RuntimeError as exc:        # a half-made copy is never taken for the working copy next time
            shutil.rmtree(path, ignore_errors=True)
            raise ConsoleRefused(f"the console's working copy could not be made: {str(exc)[-300:]}") from None
        _git(path, "remote", "set-url", "--push", "origin", NO_PUSH)
    elif not _git(path, "status", "--porcelain", check=False):
        _git(path, "fetch", "-q", "origin", check=False)       # moved forward while it holds nothing of its own
        _git(path, "merge", "-q", "--ff-only", "@{u}", check=False)
    return path, "working_copy"


def offered(project: Project, person: str | None = None) -> list[dict[str, Any]]:
    ws = workspace(project, person)
    root = Path(ws["path"]) if ws["exists"] else None
    kept = project.read("agent_context.json", None)        # what its instructions state (kernel/ide.py)
    found = console_offers.offers(root, settings(project), kept if isinstance(kept, dict) else None)
    # Before the working copy is made (at the first run), and after: the test commands adoption's baseline ran.
    lines = {o["line"] for o in found}
    for run in (project.read("baseline.json", {}) or {}).get("runs") or []:
        line = " ".join(str(x) for x in run.get("command") or [])
        if line and line not in lines:
            lines.add(line)
            found.append(console_offers._offer(console_offers.tests_label(run.get("runner")), line,
                                               "the adoption's baseline ran it"))
    if root is None:      # before the first run, the repository's last commit is read for them by rule
        found += [o for o in console_offers.from_repository(project.path("repo.git")) if o["line"] not in lines]
    return found[:console_offers.MAX_OFFERS]


# -- plans -------------------------------------------------------------------------------------------------

def split(line: str) -> list[str]:
    """A command line as words, quotes honoured; a backslash stays a backslash (Windows paths)."""
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True
    lexer.escape = "" if os.name == "nt" else "\\"
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError as exc:
        raise ValueError(f"the command line does not parse: {exc}") from None


def _env(project: Project, *, gnomon: bool = False) -> dict[str, str]:
    from kernel.models_setup import gnomon_env

    env = gnomon_env() if gnomon else dict(os.environ)     # a stored model key reaches Gnomon only
    env.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", RIHMASTO_PROJECT=project.pid,
               RIHMASTO_HOME=str(Path(project.factory.home).resolve()))
    return env


def command_plan(project: Project, line: str, cwd: Path, kind: str, *, shell: bool = False) -> crun.Plan:
    """A typed or offered command line as it will run: one program with its arguments, or through the shell."""
    from kernel.redteam.masking import mask

    line = str(line or "").strip()
    if not line or len(line) > MAX_LINE:
        raise ValueError(f"the command line is empty or longer than {MAX_LINE} characters")
    if shell:
        argv = ([os.environ.get("COMSPEC") or "cmd.exe", "/d", "/s", "/c", line] if os.name == "nt"
                else [os.environ.get("SHELL") or "/bin/sh", "-c", line])
    else:
        if console_offers.needs_shell(line):
            raise ValueError("this command line uses the shell's own words (a pipe, &&, a redirect): tick Run "
                             "through the shell, or open a terminal here")
        argv = split(line)
        if argv and argv[0] in ("python", "python3", "py"):
            argv[0] = sys.executable or argv[0]
    return crun.Plan(argv=argv, cwd=cwd, env=_env(project), display=mask(line)[:MAX_LINE], shell=shell,
                     workspace=kind)


def _surface(project: Project, cwd: Path, kind: str) -> None:
    """Gnomon needs a ``.gnomon/`` surface in the workspace: the workspace's own, or, in the console's working
    copy only, the factory's routing compiled there and kept out of commits. A person's repository is never
    written to: one without a surface is refused, with how to give it one."""
    if (cwd / ".gnomon").is_dir():
        return
    if kind != "working_copy":
        raise ConsoleRefused(f"{cwd} has no Gnomon surface (.gnomon/), and Rihmasto never writes into your "
                             f"repository: run `gnomon init` there, or open a terminal here ({GNOMON_DOCS})")
    from kernel.lanes import load_routing, write_product_surface

    write_product_surface(cwd, load_routing(), ["**"])
    exclude = cwd / ".git" / "info" / "exclude"
    text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if ".gnomon/" not in text:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(text + ".gnomon/\n", encoding="utf-8", newline="\n")


def gnomon_plan(project: Project, prompt: str, cwd: Path, kind: str, *, role: str | None = None,
                yes: bool = False) -> crun.Plan:
    """``gnomon task`` in the workspace: Gnomon's own governance (its surface, policy and audit trail) holds,
    and without ``yes`` every gated tool call is refused, as in any run with nobody to ask."""
    from kernel.confidential import require_local
    from kernel.model import gnomon_cmd

    prompt = str(prompt or "").strip()
    if not prompt or len(prompt) > MAX_PROMPT:
        raise ValueError(f"say what Gnomon should do, in at most {MAX_PROMPT} characters")
    if role is not None and not _ROLE.match(role):
        raise ValueError(f"{role!r} is not a role name")
    require_local(project, [role or "builder"], where="console")
    _surface(project, cwd, kind)
    argv = [*gnomon_cmd(), "task", prompt, *(["--role", role] if role else []), *(["--yes"] if yes else [])]
    shown = f"gnomon task {shlex.quote(prompt[:300])}" + (f" --role {role}" if role else "") + (" --yes" if yes else "")
    return crun.Plan(argv=argv, cwd=cwd, env=_env(project, gnomon=True), display=shown, kind="gnomon",
                     workspace=kind)


def timeout_of(value: Any) -> int:
    if value in (None, ""):
        return DEFAULT_TIMEOUT
    if isinstance(value, bool) or not isinstance(value, (int, float, str)) or not str(value).isdigit():
        raise ValueError(f"the time limit is a whole number of seconds up to {MAX_TIMEOUT}")
    return max(1, min(int(value), MAX_TIMEOUT))


def prepare(project: Project, request: dict[str, Any], *, person: str, persona: str) -> crun.Plan:
    """A request (``line`` and ``shell``, or ``gnomon`` with ``role`` and ``yes``) as an isolated plan, after
    the persona is checked; nothing runs or is recorded here."""
    from kernel import access_isolation as kisolation

    check_persona(project, person, persona)
    kisolation.runner(kisolation.CELL if request.get("gnomon") else kisolation.SUITE)   # refused before anything
    cwd, kind = ensure_workspace(project, person)
    if request.get("gnomon"):
        plan = gnomon_plan(project, str(request["gnomon"]), cwd, kind, role=request.get("role") or None,
                           yes=request.get("yes") is True)
    else:
        plan = command_plan(project, str(request.get("line") or ""), cwd, kind, shell=request.get("shell") is True)
    return crun.isolate(plan)


# -- recording and running ---------------------------------------------------------------------------------

def log_path(project: Project) -> Path:
    stamp = re.sub(r"[^0-9TZ]", "", project.factory.clock.stamp())
    return Path(project.factory.home) / "jobs" / f"{stamp}-console-{project.pid}-{secrets.token_hex(2)}.log"


def record(project: Project, plan: crun.Plan, out: dict[str, Any], *, person: str, persona: str, log: Path,
           via: str) -> dict[str, Any]:
    """``console_ran`` in the project's ledger: who, the command line, how it ended; never its output."""
    return project.log("console_ran", {"person": person, "persona": persona, "via": via, "kind": plan.kind,
                                       "command": plan.display, "shell": plan.shell, "workspace": plan.workspace,
                                       "isolated": plan.isolated, "state": out["state"], "exit": out.get("code"),
                                       "seconds": out.get("seconds"), "log": log.name})


def start(project: Project, request: dict[str, Any], *, person: str, persona: str,
          on_end: Callable[[Callable[[], None]], None] | None = None,
          timeout: Any = None, jobs: Any = None) -> dict[str, Any]:
    """Start a run in the background (the cockpit): the job's id, its log and what it runs. ``on_end`` wraps
    the recording at its end (the cockpit signs it with the verified identity); ``jobs`` runs it (crun.JOBS)."""
    limit = timeout_of(timeout)
    plan = prepare(project, request, person=person, persona=persona)
    path = log_path(project)

    def ended(out: dict[str, Any]) -> None:
        def write() -> None:
            record(project, plan, out, person=person, persona=persona, log=path, via="cockpit")
        (on_end or (lambda w: w()))(write)

    job_id = (jobs or crun.JOBS).start(plan, path, timeout=limit, on_end=ended)
    return {"id": job_id, "log": path, "display": plan.display, "kind": plan.kind, "workspace": plan.workspace,
            "isolated": plan.isolated, "timeout": limit}


def run(project: Project, request: dict[str, Any], *, person: str, persona: str, timeout: Any = None,
        echo: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Run in the foreground (``rihmasto console``), streaming to ``echo``; recorded like any other run."""
    limit = timeout_of(timeout)
    plan = prepare(project, request, person=person, persona=persona)
    path = log_path(project)
    out = crun.execute(plan, path, timeout=limit, echo=echo)
    record(project, plan, out, person=person, persona=persona, log=path, via="command line")
    return {**out, "command": plan.display, "workspace": plan.workspace, "log": str(path)}
