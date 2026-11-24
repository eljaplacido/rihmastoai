"""The optional sandbox for a runner other than Gnomon (FR-HRN1): a container with only the working copy (D-0019).

With ``sandbox: docker`` on a choice, the harness runs in a container of the image the choice names (one that holds
the harness): the working copy is the only folder mounted, every capability is dropped, no new privileges, and the
network is none. When the harness needs its model endpoint, the container joins an internal network of its own whose
one way out is a small proxy (standard-library Python, ``PROXY``) that opens a tunnel only to the endpoint's host
and port and refuses everything else. The variables the harness reads its key from are passed by name, never
written on the command line.

When Docker is not on this machine, or its daemon does not answer, a run that asked for the sandbox does not run,
and says so: it never falls back to running on the host. Gnomon's own ``[sandbox] exec`` governs Gnomon's shell; it
does not apply to another harness, so this is the sandbox for those.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from kernel.runners import RunnerRefused

PROXY_IMAGE = "python:3.12-slim"
PROXY_PORT = 3128
# The model endpoint each harness talks to unless the choice names its own, and the key variables it reads.
ENDPOINTS = {"claude-code": ["api.anthropic.com:443"], "codex": ["api.openai.com:443"], "opencode": [], "command": []}
KEY_VARS = {"claude-code": ["ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"],
            "codex": ["OPENAI_API_KEY", "CODEX_API_KEY"], "opencode": [], "command": []}

# A CONNECT proxy that tunnels only to the hosts and ports it is given: argv is <listen host> <port> <host:port>...
PROXY = r'''
import select, socket, sys, threading
HOST, PORT, ALLOWED = sys.argv[1], int(sys.argv[2]), {a.lower() for a in sys.argv[3:]}


def pipe(a, b):
    try:
        while True:
            ready, _, _ = select.select([a, b], [], [], 300)
            if not ready:
                return
            for s in ready:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except OSError:
        return
    finally:
        a.close()
        b.close()


def serve(conn):
    head = b""
    while b"\r\n\r\n" not in head and len(head) < 8192:
        chunk = conn.recv(1024)
        if not chunk:
            break
        head += chunk
    words = head.split(b"\r\n", 1)[0].decode("latin-1").split()
    target = words[1].lower() if len(words) == 3 and words[0] == "CONNECT" else ""
    if target not in ALLOWED:
        conn.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        conn.close()
        return
    host, _, port = target.rpartition(":")
    try:
        up = socket.create_connection((host, int(port)), timeout=20)
    except OSError:
        conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
        conn.close()
        return
    conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
    pipe(conn, up)


srv = socket.create_server((HOST, PORT))
print(srv.getsockname()[1], flush=True)
while True:
    c, _ = srv.accept()
    threading.Thread(target=serve, args=(c,), daemon=True).start()
'''


def docker_status(timeout: int = 15) -> dict[str, Any]:
    """Whether Docker can run a container here: its client on PATH and its daemon answering."""
    docker = shutil.which("docker")
    if docker is None:
        return {"available": False, "version": None, "why": "Docker is not on this machine: `docker` is not on PATH"}
    try:
        proc = subprocess.run([docker, "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True,
                              timeout=timeout, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "version": None, "why": f"Docker did not answer: {exc}"}
    if proc.returncode != 0 or not proc.stdout.strip():
        tail = " ".join((proc.stderr or "").strip().splitlines()[-2:])[:300]
        return {"available": False, "version": None, "why": f"Docker's daemon does not answer: {tail or 'no version'}"}
    return {"available": True, "version": proc.stdout.strip(), "why": ""}


def target_of(workdir: Path) -> str:
    """Where the working copy is in the container: the same path on Linux and macOS, /work on Windows."""
    return "/work" if os.name == "nt" else Path(workdir).as_posix()


def plan(argv: list[str], workdir: Path, choice: dict[str, Any], *, name: str,
         env_names: tuple[str, ...] = ()) -> dict[str, list[list[str]]]:
    """The docker commands for one sandboxed run: what is set up, the run itself, and what is taken down after."""
    image = str(choice.get("image") or "").strip()
    if not image:
        raise RunnerRefused("the docker sandbox needs an image that holds the harness (--image)")
    runner = str(choice.get("runner") or "command")
    endpoints = [str(e).lower() for e in (choice.get("endpoints") or ENDPOINTS.get(runner, []))]
    target, host = target_of(workdir), str(Path(workdir))
    inner = [w.replace(host, target) for w in argv]
    run = ["docker", "run", "--rm", "-i", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "--pids-limit", "512", "-v", f"{host}:{target}", "-w", target]
    if sys.platform != "win32":                       # the files come back owned by this account, not root
        run += ["--user", f"{os.getuid()}:{os.getgid()}"]
    for var in (*KEY_VARS.get(runner, []), *(choice.get("pass_env") or []), *env_names):
        run += ["-e", str(var)]                         # by name: docker takes the value from its own environment
    setup: list[list[str]] = []
    down: list[list[str]] = []
    if endpoints:
        net, proxy = f"{name}-net", f"{name}-proxy"
        setup = [["docker", "network", "create", "--internal", net],
                 ["docker", "run", "-d", "--rm", "--name", proxy, PROXY_IMAGE, "python", "-c", PROXY, "0.0.0.0",
                  str(PROXY_PORT), *endpoints],
                 ["docker", "network", "connect", net, proxy]]
        url = f"http://{proxy}:{PROXY_PORT}"
        run += ["--network", net, "-e", f"HTTPS_PROXY={url}", "-e", f"HTTP_PROXY={url}", "-e", f"https_proxy={url}"]
        down = [["docker", "rm", "-f", proxy], ["docker", "network", "rm", net]]
    else:
        run += ["--network", "none"]
    return {"setup": setup, "run": [run + [image, *inner]], "down": down, "endpoints": [endpoints]}


@contextlib.contextmanager
def sandboxed(argv: list[str], workdir: Path, choice: dict[str, Any], *,
              env_names: tuple[str, ...] = ()) -> Iterator[list[str]]:
    """The command a run starts with: ``argv`` as it is, through IT's isolation account when access is enforced,
    or in the docker sandbox the choice asks for (set up first and taken down after, whatever happens)."""
    if (choice.get("sandbox") or "off") != "docker":
        yield isolated(argv)
        return
    status = docker_status()
    if not status["available"]:
        raise RunnerRefused(f"the docker sandbox was asked for and {status['why']}: nothing ran")
    steps = plan(argv, workdir, choice, name=f"rihmasto-cell-{uuid.uuid4().hex[:8]}", env_names=env_names)
    try:
        for cmd in steps["setup"]:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        yield steps["run"][0]
    finally:
        for cmd in steps["down"]:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(cmd, capture_output=True, timeout=60, stdin=subprocess.DEVNULL)


def isolated(argv: list[str]) -> list[str]:
    """A harness on the host, as access enforcement asks (D-0016): as IT's separate account, or refused when IT
    runs cells only through its own command (which starts Gnomon, not another harness)."""
    from kernel.access_isolation import CELL, SUDO, runner

    r = runner(CELL)
    if r is None:
        return list(argv)
    if r.kind == "os_account" and not r.cells:
        return [SUDO, "-n", "-u", str(r.account), "--", *argv]
    raise RunnerRefused("IT runs cells through its own command, which starts Gnomon: another harness runs here only "
                        "in the docker sandbox (rihmasto runners set ... --sandbox docker)")
