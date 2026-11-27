"""Where untrusted code runs while access is enforced (D-0016, FR-ID2).

With access enforced, code a model or a developer wrote never runs as the account that runs Rihmasto:
whatever that account can read (the factory home, the cockpit's memory), code running as it could read
too. Four kinds of work go through the isolation runner the access file names (``isolation``):
- **a suite**: the gate's run of a project's own tests (``kernel.gate.run_suite``);
- **an adopted suite**: adoption's baseline run of an existing repository's own tests
  (``kernel.adopt.run_baseline``), counted as a suite;
- **a product** on the local road (``kernel.roads.LocalProcessRoad``);
- **a cell**: every Gnomon call (``kernel.model.run_gnomon_task``): builders, the verifier, the analyst,
  the assistant and a website's chat alike.

Two runners:
- ``container``: the docker CLI (``docker_cli``; podman takes the same words) runs a suite in ``image``
  with no network, no capabilities, a read-only root, the checkout mounted read-only and one writable
  folder for the outcomes. A product runs on a docker road instead: the local road refuses and says so.
  A cell runs as ``cells`` says, the command that runs Gnomon in a container (``{cwd}``: the cell's folder).
- ``os_account``: a separate operating-system account, through ``sudo -n -u <account>``, on Linux or
  macOS. IT lets Rihmasto's account run commands as that account without a password, and gives that
  account write access to each lane folder (``lanes/lane-N``, ``lanes/analyst``: a builder writes
  there) through a group or default ACLs, and nothing else of the factory home. A cell runs Gnomon as
  it, unless ``cells`` names another command; its task file is made readable to the lane's group
  (``share``), never to everyone.

A cell, and a suite run as a separate account, can write the lane's ``.git`` too. Before the kernel's
own git runs there again, the folder is scrubbed: no hook, no config key a clone does not set, origin
the product repository again (``kernel.git_guard``, used by ``kernel.lanes.Lane`` and ``git`` here).

With access enforced and no runner, or one this machine cannot use, the kernel refuses that work and says
why (``IsolationRequired``), and the cockpit refuses to start a job that would do it. With a single
operator nothing changes. The access file that decides is the one of the factory the surface serves
(``serving``: the command line around each command, the cockpit around each request, the embed server
from its start), else the one the environment names (``RIHMASTO_HOME`` and its older names).
"""

from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from kernel import access as kaccess
from kernel import git_guard
from kernel.accessfile import Access, Runner
from kernel.store import Factory, home_from_env

SUITE = "the gate's run of a project's own tests"
PRODUCT = "a product on the local road"
CELL = "a Gnomon cell"
SUDO = "sudo"
SUDO_WORKS = os.name != "nt"         # sudo -u runs a command as another account on Linux and macOS
OUT = "/gate"                       # the suite's one writable folder, in a container
# What a product on the local road is given, as a separate account (sudo passes no other variable).
PRODUCT_ENV = ("HOST", "PORT", "DATA_DIR", "TRAFFIC_LOG", "APP_VERSION", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE")
GUIDE = "docs/guides/access.md#isolation"

_SERVING: list[Factory] = []
_LOCK = threading.Lock()


class IsolationRequired(kaccess.AccessRefused):
    """Untrusted work refused while access is enforced: there is no runner to keep it from Rihmasto's own
    account. The command line exits 2 with the reason; the cockpit answers 403 with it."""


# -- which factory decides ------------------------------------------------------------------------------

@contextlib.contextmanager
def serving(factory: Factory) -> Iterator[None]:
    """While this block runs, the work this process starts serves ``factory``: its access file decides."""
    with _LOCK:
        _SERVING.append(factory)
    try:
        yield
    finally:
        with _LOCK:
            _SERVING.remove(factory)


def serve(factory: Factory) -> None:
    """Serve ``factory`` for the rest of this process (a server that serves one factory, the embed server)."""
    with _LOCK:
        _SERVING.append(factory)


def served() -> Factory | None:
    with _LOCK:
        if _SERVING:
            return _SERVING[-1]
    home = home_from_env()
    return Factory(home) if home else None


# -- whether, and how, untrusted work runs ----------------------------------------------------------------

def unusable(access: Access, what: str) -> str | None:
    """Why ``what`` (SUITE, PRODUCT, CELL) cannot run while access is enforced here; None when it can."""
    if access.error is not None:
        return f"access is enforced, but {access.error}: {what} does not run until IT fixes it"
    r = access.isolation
    if r is None and access.source == "team":    # team mode with no runner named: as in solo (kernel/team.py)
        return None
    if r is None:
        return (f"access is enforced and the access file names no isolation runner, so {what} does not run: "
                "code a model or a developer wrote never runs as the account that runs Rihmasto. IT names a "
                f"container or a separate account in the access file's \"isolation\" ({GUIDE})")
    if r.kind == "os_account" and not SUDO_WORKS:
        return (f"the access file's isolation runner is a separate account, which works through sudo on Linux "
                f"and macOS only: {what} does not run on this Windows machine; IT names a container runner instead")
    if what == PRODUCT and r.kind == "container":
        return ("access is enforced with a container runner, so a product runs on a docker road and never on "
                "the local road: IT names a docker road for this environment in paved_roads.json (the explore "
                "preview's too)")
    if what == CELL and r.kind == "container" and r.cells is None:
        return ("access is enforced with a container runner whose \"cells\" is not set, so a Gnomon cell does not "
                "run: IT names the command that runs Gnomon in a container in the access file's isolation.cells "
                f"({GUIDE})")
    return None


def runner(what: str, factory: Factory | None = None) -> Runner | None:
    """IT's runner for ``what``; None when access is not enforced (it runs as before). IsolationRequired
    when access is enforced and ``what`` cannot run isolated here."""
    factory = factory or served()
    if factory is None:
        return None
    access = kaccess.load(factory)
    if not access.enforced:
        return None
    why = unusable(access, what)
    if why is not None:
        raise IsolationRequired(why)
    return access.isolation


def require(factory: Factory, what: str = CELL) -> None:
    """The cockpit's check before it starts a job: refused, with why, when ``what`` could not run."""
    runner(what, factory)


def describe(access: Access) -> str:
    """One sentence on where untrusted code runs, for the cockpit's access note and ``access check``."""
    if not access.enforced:
        return "single operator: untrusted code runs as the operator's account, as before"
    r = access.isolation
    if r is None and access.source == "team":
        return "team mode: untrusted code runs as the operator's account, as in solo (IT's access file isolates it)"
    if r is None:
        return ("no isolation runner: the gate's test runs, local products and Gnomon cells are refused, and "
                "adoption's baseline is not run")
    if r.kind == "container":
        cells = "Gnomon cells as isolation.cells says" if r.cells else "no Gnomon cells (isolation.cells is not set)"
        return f"untrusted code runs in a container ({r.image}): test runs there, products on a docker road, {cells}"
    return f"untrusted code runs as the separate account {r.account}, through sudo"


# -- the three kinds of work ------------------------------------------------------------------------------

@dataclass
class Confined:
    """A suite's command as it runs: where its outcomes land. Used as a context manager, it stops a
    container that outlived the gate's time (the docker CLI was stopped, the container was not) and
    removes its own folder afterwards."""

    argv: list[str]
    env: dict[str, str]
    report: Path
    scratch: Path | None = None
    stop_argv: list[str] = field(default_factory=list)
    lane: Path | None = None        # a checkout a separate account ran in: scrubbed afterwards

    def __enter__(self) -> Confined:
        return self

    def __exit__(self, kind: type[BaseException] | None, *_: object) -> None:
        if kind is not None and issubclass(kind, subprocess.TimeoutExpired):
            self.halt()
        if self.scratch is not None:
            shutil.rmtree(self.scratch, ignore_errors=True)
        if self.lane is not None and (self.lane / ".git").is_dir():
            git_guard.scrub(self.lane)

    def halt(self) -> None:
        """Stop a container the docker CLI left running when its time ran out."""
        if self.stop_argv:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(self.stop_argv, capture_output=True, timeout=60, check=False)


def _bind(source: Path, target: str, *, readonly: bool = False) -> list[str]:
    """A bind mount, as ``--mount`` takes it (CSV: a field with a comma or a quote is quoted)."""
    src = f"src={source}"
    if "," in src or '"' in src:
        src = '"' + src.replace('"', '""') + '"'
    return ["--mount", f"type=bind,{src},dst={target}" + (",readonly" if readonly else "")]


def _container_user() -> list[str]:
    """Run as this account's numbers inside the container, so what it writes stays removable here."""
    getuid, getgid = getattr(os, "getuid", None), getattr(os, "getgid", None)
    return ["--user", f"{getuid()}:{getgid()}"] if getuid and getgid else []


def suite(argv: list[str], *, repo_dir: Path, env: Mapping[str, str], report: Path) -> Confined:
    """How the gate runs ``argv`` (``<python> -c <runner> <report> <pattern>``) in ``repo_dir``: as it is,
    or through IT's runner, with the outcomes written where ``report`` of the result says."""
    r = runner(SUITE)
    if r is None:
        return Confined(list(argv), dict(env), report)
    scratch = Path(tempfile.mkdtemp(prefix="gate-isolated-"))
    (scratch / "data").mkdir()
    flags, code, rest = argv[1], argv[2], argv[4:]
    if r.kind == "container":
        name = f"rihmasto-gate-{secrets.token_hex(6)}"
        cmd = [*r.docker_cli, "run", "--rm", "--name", name, "--network", "none", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--read-only", "--tmpfs", "/tmp", *_container_user(),
               *_bind(Path(repo_dir).resolve(), "/work", readonly=True), "--workdir", "/work",
               *_bind(scratch.resolve(), OUT), "--env", f"DATA_DIR={OUT}/data", "--env", "HOME=/tmp",
               "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONIOENCODING=utf-8", str(r.image),
               r.python, flags, code, f"{OUT}/outcomes.json", *rest]
        return Confined(cmd, dict(os.environ), scratch / "outcomes.json", scratch, [*r.docker_cli, "rm", "-f", name])
    for folder in (scratch, scratch / "data"):
        folder.chmod(0o777)          # the separate account writes its outcomes and data here, and nothing else
    cmd = [SUDO, "-n", "-u", str(r.account), "--", "env", f"DATA_DIR={scratch / 'data'}", "HOME=/tmp",
           "PYTHONDONTWRITEBYTECODE=1", "PYTHONIOENCODING=utf-8", r.python, flags, code,
           str(scratch / "outcomes.json"), *rest]
    return Confined(cmd, dict(os.environ), scratch / "outcomes.json", scratch, lane=Path(repo_dir))


ADOPTED_ENV = ("PYTHONDONTWRITEBYTECODE", "PIP_NO_INDEX", "npm_config_offline", "GOPROXY", "GOFLAGS",
               "CARGO_NET_OFFLINE", "GIT_TERMINAL_PROMPT")


def adopted_suite(argv: list[str], *, checkout: Path, env: Mapping[str, str], tool: str) -> Confined:
    """How adoption runs an existing repository's own test command (``argv``; ``tool`` its program's bare
    name) in its ``checkout``: as it is, or through IT's runner with the offline settings only, the
    checkout read-only and a data folder of its own. IsolationRequired when access is enforced and there
    is no runner: the baseline is then not measured, and says why (``kernel.adopt.run_baseline``)."""
    r = runner(SUITE)
    if r is None:
        return Confined(list(argv), dict(env), Path(os.devnull))
    given = [f"{k}={env[k]}" for k in ADOPTED_ENV if k in env]
    program = r.python if argv and argv[0] == sys.executable else tool
    if r.kind == "container":
        name = f"rihmasto-adopt-{secrets.token_hex(6)}"
        cmd = [*r.docker_cli, "run", "--rm", "--name", name, "--network", "none", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--read-only", "--tmpfs", "/tmp", *_container_user(),
               *_bind(Path(checkout).resolve(), "/work", readonly=True), "--workdir", "/work",
               *[w for kv in given for w in ("--env", kv)], "--env", "DATA_DIR=/tmp/data", "--env", "HOME=/tmp",
               str(r.image), program, *argv[1:]]
        return Confined(cmd, dict(os.environ), Path(os.devnull), stop_argv=[*r.docker_cli, "rm", "-f", name])
    scratch = Path(tempfile.mkdtemp(prefix="adopt-isolated-"))
    scratch.chmod(0o777)              # the separate account's data folder, and nothing else it writes
    for folder in (Path(checkout).parent, Path(checkout)):
        folder.chmod(folder.stat().st_mode | 0o055)      # it reads the checkout (what the upstream holds)
    cmd = [SUDO, "-n", "-u", str(r.account), "--", "env", *given, f"DATA_DIR={scratch}", "HOME=/tmp",
           program, *argv[1:]]
    return Confined(cmd, dict(os.environ), Path(os.devnull), scratch)


def git(repo_dir: Path) -> list[str]:
    """The kernel's git in a checkout untrusted code ran in (the gate's lane after its suites): the
    folder scrubbed, then git with no hook, fsmonitor or signing program (``kernel.git_guard``)."""
    return git_guard.git(repo_dir)


def copy_tests(repo_dir: Path, base_dir: Path) -> None:
    """The head's tests onto the gate's base checkout (its fail-first and template checks), taken from the
    head commit in git, never from the lane's files: a link or junction a cell left under ``tests/`` is
    never followed as the account that runs Rihmasto, so what only that account can read never reaches
    the suite's copy. A link the head commits stays a link there (the isolated suite cannot follow it)."""
    head = subprocess.run([*git(repo_dir), "rev-parse", "--verify", "HEAD^{commit}"], cwd=repo_dir, check=True,
                          capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()
    for args in (["rm", "-r", "-q", "--ignore-unmatch", "--", "tests"], ["checkout", "-q", head, "--", "tests"]):
        subprocess.run(["git", *git_guard.flags(), *args], cwd=base_dir, check=True, capture_output=True,
                       text=True, stdin=subprocess.DEVNULL, env={**os.environ, **git_guard.env()})


def share(task_file: Path) -> None:
    """A cell's task file, readable by the lane's group when a separate account runs the cell (mkstemp
    makes it 0600, which that account could not read); never readable by everyone."""
    r = runner(CELL)
    if r is not None and r.kind == "os_account":
        os.chmod(task_file, 0o640)


def product(argv: list[str], env: Mapping[str, str], *, writable: tuple[Path, ...] = (),
            files: tuple[Path, ...] = ()) -> list[str]:
    """The command that starts a product on the local road: ``argv`` as it is, or as IT's separate account,
    given the product's variables and write access to its data folder and traffic log only."""
    r = runner(PRODUCT)
    if r is None:
        return list(argv)
    for folder in writable:
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o777)
    for path in files:
        path.touch()
        path.chmod(0o666)
    python = r.python if argv and argv[0] == sys.executable else argv[0]
    given = [f"{k}={env[k]}" for k in PRODUCT_ENV if k in env]
    return [SUDO, "-n", "-u", str(r.account), "--", "env", *given, python, *argv[1:]]


def cell(cmd: list[str], cwd: Path) -> list[str]:
    """The command a Gnomon call starts with (``gnomon_cmd()``): as it is, IT's ``cells`` with ``{cwd}``
    filled in, or Gnomon as the separate account."""
    r = runner(CELL)
    if r is None:
        return list(cmd)
    if r.cells:
        return [w.replace("{cwd}", str(cwd)) for w in r.cells]
    return [SUDO, "-n", "-u", str(r.account), "--", *cmd]
