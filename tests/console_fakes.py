"""Stand-ins for the console and the checks' tests (FR-CON1, FR-CHK1): a repository to attach, tools on PATH
written by the test, a console that runs nothing, a terminal launcher that opens nothing, and servers on
127.0.0.1 for the CI API and the probe."""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

PERSON = "Dana Developer"
GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]


def git_repo(path: Path, files: dict[str, str]) -> Path:
    """A git repository at ``path`` with ``files`` committed on main."""
    path.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text, encoding="utf-8", newline="\n")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], [*GIT_ID, "commit", "-q", "-m", "start"]):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    return path


def attached(factory: Any, repo: Path, title: str = "Orders") -> Any:
    from kernel.attach import attach

    return attach(factory, title, repo=repo, person=PERSON, persona="developer")


def fake_tool(folder: Path, name: str, code: str) -> Path:
    """A program called ``name`` on PATH that runs the Python ``code`` (its arguments in sys.argv)."""
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / f"{name}_impl.py"
    script.write_text(code, encoding="utf-8", newline="\n")
    if os.name == "nt":
        launcher = folder / f"{name}.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8", newline="")
    else:
        launcher = folder / name
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    return launcher


def git_only(folder: Path) -> Path:
    """A folder for PATH on which git is found and no other tool a test might fake or expect to be missing.

    Git's own folder on Windows (Git's ``cmd`` folder holds git alone); elsewhere git's folder is ``/usr/bin``,
    which on a hosted Linux runner also holds gh, gcloud and more, so a folder with a link to git alone."""
    import shutil

    git = Path(shutil.which("git") or "git")
    if os.name == "nt":
        return git.parent
    folder.mkdir(parents=True, exist_ok=True)
    if not (folder / "git").exists():
        os.symlink(git, folder / "git")
    return folder


def path_without(names: tuple[str, ...], folder: Path) -> str:
    """os.environ's PATH with none of the programs ``names`` on it and every other program kept: each folder
    holding one is replaced by a folder of links to all its other entries (on a hosted Linux runner gcloud and
    gh sit in /usr/bin beside git and everything else). Where a link cannot be made, that entry is left out."""
    import contextlib
    import shutil

    out = []
    for i, d in enumerate(os.environ.get("PATH", "").split(os.pathsep)):
        if not d or not any(shutil.which(n, path=d) for n in names):
            out.append(d)
            continue
        links = folder / f"path-{i}"
        links.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            for entry in Path(d).iterdir():
                if entry.name.split(".")[0].lower() not in names and not (links / entry.name).exists():
                    with contextlib.suppress(OSError):
                        os.symlink(entry, links / entry.name)
        out.append(str(links))
    return os.pathsep.join(out)


def printing(doc: Any, exit_code: int = 0) -> str:
    """The code of a tool that prints ``doc`` as JSON and exits with ``exit_code``."""
    return f"import sys\nprint({json.dumps(json.dumps(doc))})\nsys.exit({exit_code})\n"


class QuietJobs:
    """The console's runner in the write-route tables: it runs nothing, and the run ends at once (recorded)."""

    def __init__(self) -> None:
        self.started: list[Any] = []

    def start(self, plan: Any, log_path: Path, *, timeout: float, on_end: Any) -> str:
        self.started.append(plan)
        job_id = f"C-{len(self.started):04d}-abcd"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(f"$ {plan.display}\n", encoding="utf-8")
        on_end({"state": "done", "code": 0, "seconds": 0.0})
        return job_id

    def status(self, job_id: str) -> dict[str, Any]:
        return {"state": "done", "code": 0}

    def stop(self, job_id: str) -> bool:
        return False

    def wait(self, job_id: str, timeout: float = 30) -> dict[str, Any]:
        return self.status(job_id)


class Launcher:
    """A terminal launcher that opens nothing: it records what it was asked to open. It stands for a machine
    with a terminal program installed, on every system alike (a Linux CI runner has none of its own)."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path, dict[str, str]]] = []

    def terminal_argv(self, path: Path) -> list[str]:
        from kernel import console_term

        return console_term.terminal_argv(path, which=lambda name: name)

    def __call__(self, argv: list[str], cwd: Path, env: dict[str, str]) -> None:
        self.calls.append((list(argv), Path(cwd), dict(env)))


def write_routes(case: Any, w: dict[str, Any]) -> list[tuple[Any, ...]]:
    """The console's and the checks' write routes (FR-CON1, FR-CHK1) for the cockpit's completeness tables
    (tests/test_brief_ln.py, tests/test_access.py): each signed, each recorded. The console runs nothing here
    and the terminal opens nothing; the working copy is made under the test's own folder."""
    from unittest import mock

    b = w["built"].pid
    patcher = mock.patch.dict(os.environ, {"GF_LANES": str(case.tmp / "console-lanes")})
    patcher.start()
    case.addCleanup(patcher.stop)
    case.server.console_jobs = QuietJobs()
    case.server.terminal_launcher = Launcher()

    def dev(who: str, got: dict[str, Any]) -> dict[str, Any]:
        return {"person": who, "persona": "developer"}

    return [
        ("post_console_run", "POST", f"/api/projects/{b}/console/run",
         lambda who, got: {"line": "git status", **dev(who, got)}),
        ("post_console_stop", "POST", lambda got: f"/api/projects/{b}/console/runs/{got['post_console_run']['job']['id']}"
         "/stop", dev),
        ("post_console_terminal", "POST", f"/api/projects/{b}/console/terminal", dev),
        ("put_console_settings", "PUT", f"/api/projects/{b}/console/settings",
         lambda who, got: {"personas": ["developer", "it", "operations"], "commands": {"test": "python -m unittest"},
                           "person": who, "persona": "it"}),
        ("post_check_enable", "POST", f"/api/projects/{b}/checks/security_gate/enable",
         lambda who, got: {"every": "1d", "person": who, "persona": "compliance"}),
        ("post_check_run", "POST", f"/api/projects/{b}/checks/security_gate/run",
         lambda who, got: {"person": who, "persona": "compliance"}),
        ("post_check_disable", "POST", f"/api/projects/{b}/checks/security_gate/disable",
         lambda who, got: {"person": who, "persona": "compliance"}),
        ("post_checks_enable", "POST", "/api/checks/enable",
         lambda who, got: {"check": "sbom", "projects": [b], **dev(who, got)}),
    ]


class Stub:
    """An HTTP server on 127.0.0.1 that answers each path from ``routes`` (status, JSON body) and records
    every request's path and headers."""

    def __init__(self, routes: dict[str, tuple[Any, ...]]) -> None:
        self.routes, self.seen = routes, []
        stub = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - the base class names it
                stub.seen.append((self.path, dict(self.headers)))
                status, body, *delay = stub.routes.get(self.path.split("?")[0], (404, {"message": "Not Found"}))
                if delay:
                    time.sleep(delay[0])
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: Any) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
