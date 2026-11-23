"""The factory's own servers, started for one agentic red team run on its sandbox (`--via http`).

The red team never imports the servers: it runs them as the factory does, `python -m embed.server`
and `python -m cockpit.server`, on 127.0.0.1 with port 0, against the sandbox's factory home, and
reads the address each one prints. The cockpit's one-use sign-in link is redeemed only when the run
calls `sign_in`, after the scope permitted the address. Each server stops when the run ends.

The model is the server's own (`--model none|gnomon` for the embed server, `--assistant map|gnomon`
for the cockpit), in its own process: the red team sees the answers but not the prompts, and says so.
"""

from __future__ import annotations

import contextlib
import json
import queue
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO

from kernel.model import Model
from kernel.redteam.agentic import Serve, Served
from kernel.redteam.surfaces import TurnFailed, post_json
from kernel.store import REPO_ROOT, Factory

START_TIMEOUT = 60.0
_COCKPIT_LINK = re.compile(r"(http://127\.0\.0\.1:\d+)/#k=([A-Za-z0-9_-]+)")
EMBED_MODELS = {"none": "none", "gnomon": "gnomon"}
COCKPIT_MODELS = {"none": "map", "gnomon": "gnomon"}


class ServerFailed(TurnFailed):
    """The factory's server did not start: nothing was sent, and the run is not measured."""


def _reader(stream: IO[str], lines: queue.Queue[str]) -> None:
    for line in iter(stream.readline, ""):
        lines.put(line)


def _start(args: list[str], log: Path, ready: Callable[[str], dict[str, str] | None],
           ) -> tuple[subprocess.Popen[str], dict[str, str], IO[str]]:
    """Start ``python -m <args>`` in the repository, and wait for the line ``ready`` accepts."""
    err = open(log, "w", encoding="utf-8")  # noqa: SIM115 - closed when the server stops
    proc = subprocess.Popen([sys.executable, "-m", *args], cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=err,
                            stdin=subprocess.DEVNULL, text=True, encoding="utf-8")
    lines: queue.Queue[str] = queue.Queue()
    threading.Thread(target=_reader, args=(proc.stdout, lines), daemon=True).start()
    give_up = time.monotonic() + START_TIMEOUT
    while time.monotonic() < give_up and proc.poll() is None:
        try:
            found = ready(lines.get(timeout=0.2))
        except queue.Empty:
            continue
        if found:
            return proc, found, err
    _stop(proc, err)
    raise ServerFailed(f"python -m {args[0]} did not start (see {log.name} in the sandbox, removed after the run)")


def _stop(proc: subprocess.Popen[str], err: IO[str]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
    with contextlib.suppress(OSError):
        err.close()


def _listening(line: str) -> dict[str, str] | None:
    try:
        doc = json.loads(line)
    except ValueError:
        return None
    return {"base": str(doc["listening"])} if isinstance(doc, dict) and doc.get("listening") else None


def embed_server(model: str) -> Serve:
    """Start `python -m embed.server` on the sandbox, with its own model (`none` or `gnomon`)."""
    if model not in EMBED_MODELS:
        raise ValueError(f"the embed server runs {', '.join(EMBED_MODELS)} as its model, not {model!r}")

    def serve(factory: Factory, _model: Model | None) -> Served:
        log = factory.home.parent / "embed-server.log"
        proc, found, err = _start(["embed.server", "--home", str(factory.home), "--port", "0",
                                   "--model", EMBED_MODELS[model]], log, _listening)
        return Served(found["base"], lambda: _stop(proc, err), observes_model=False, own_model=model != "none",
                      process=proc)
    return serve


def _link(line: str) -> dict[str, str] | None:
    m = _COCKPIT_LINK.search(line)
    return {"base": m.group(1), "bootstrap": m.group(2)} if m else None


def _sign_in(base: str, bootstrap: str) -> str:
    status, out = post_json(f"{base}/auth", {"bootstrap": bootstrap}, {"Origin": base})
    if status != 200 or not isinstance(out, dict) or not out.get("token"):
        raise TurnFailed(f"the cockpit refused its own sign-in link (HTTP {status})")
    return str(out["token"])


def cockpit_server(model: str) -> Serve:
    """Start `python -m cockpit.server` on the sandbox, with its own assistant model (`none`: the map)."""
    if model not in COCKPIT_MODELS:
        raise ValueError(f"the cockpit's assistant runs {', '.join(COCKPIT_MODELS)}, not {model!r}")

    def serve(factory: Factory, _model: Model | None) -> Served:
        log = factory.home.parent / "cockpit-server.log"
        proc, found, err = _start(["cockpit.server", "--home", str(factory.home), "--port", "0", "--quiet",
                                   "--assistant", COCKPIT_MODELS[model]], log, _link)
        base, bootstrap = found["base"], found["bootstrap"]
        return Served(base, lambda: _stop(proc, err), observes_model=False,
                      sign_in=lambda: _sign_in(base, bootstrap), own_model=model != "none", process=proc)
    return serve
