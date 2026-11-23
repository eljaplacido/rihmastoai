"""The surfaces the factory itself started for a red team run: the only addresses `running=` may name.

A caller never declares a surface's address. It hands over what the factory started, and the
address is read from that:

- an in-process server of the factory's own embed server (`embed.server.make_server`) or cockpit
  (`cockpit.server.make_server`), serving the factory home the run works on: its address is the one
  its socket is bound to, on loopback;
- or a process the red team launched itself (`launch.py`: `python -m embed.server` or
  `python -m cockpit.server` with `--home` the run's home), still running: its address is the one it
  printed when it started.

`register` returns a `Started` handle, kept in this process's registry; `scope.check` honours a
surface only through a handle this registry issued, for a server or process that still runs. A
string, or a handle made by hand, names nothing the factory started, and is refused.
"""

from __future__ import annotations

import ipaddress
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SERVER_MODULES = {"embed": "embed.server", "assistant": "cockpit.server"}


class NotStarted(ValueError):
    """What was handed over is not a surface the factory started for this run."""


@dataclass(frozen=True)
class Started:
    """A surface the factory started: which, where, on which factory home."""

    surface: str
    base_url: str
    home: str


_ISSUED: dict[int, tuple[Started, Callable[[], bool]]] = {}


def _same_home(a: object, b: str | Path) -> bool:
    try:
        return Path(str(a)).resolve() == Path(b).resolve()
    except (OSError, ValueError):
        return False


def _server_home(server: Any) -> object:
    factory = getattr(server, "factory", None) or getattr(getattr(server.RequestHandlerClass, "chat", None),
                                                           "factory", None)
    return getattr(factory, "home", None)


def _from_server(surface: str, server: Any, home: str | Path) -> tuple[str, Callable[[], bool]]:
    module = SERVER_MODULES[surface]
    kinds = {type(server).__module__, getattr(getattr(server, "RequestHandlerClass", None), "__module__", "")}
    if module not in kinds:
        raise NotStarted(f"the server handed over for the {surface} is not the factory's own ({module})")
    if not _same_home(_server_home(server), home):
        raise NotStarted(f"the {surface} server handed over serves another factory home, not the run's")
    host, port = server.server_address[:2]
    if not ipaddress.ip_address(host).is_loopback:
        raise NotStarted(f"the {surface} server listens on {host}, not on loopback")
    shown = f"[{host}]" if ":" in str(host) else host
    return f"http://{shown}:{port}", lambda: server.socket.fileno() != -1


def _from_process(surface: str, process: subprocess.Popen[str], base_url: str,
                  home: str | Path) -> tuple[str, Callable[[], bool]]:
    args = [str(a) for a in (process.args if isinstance(process.args, list | tuple) else [process.args])]
    module = SERVER_MODULES[surface]
    named = next((args[i + 1] for i, a in enumerate(args[:-1]) if a == "--home"), None)
    if module not in args or "-m" not in args or named is None or not _same_home(named, home):
        raise NotStarted(f"the process handed over for the {surface} is not `python -m {module} --home <the run's>`")
    if process.poll() is not None:
        raise NotStarted(f"the {surface} process the red team started has stopped")
    return base_url.rstrip("/"), lambda: process.poll() is None


def register(surface: str, home: str | Path, *, server: Any = None, process: subprocess.Popen[str] | None = None,
             base_url: str = "") -> Started:
    """A handle for a surface the factory started (an in-process server, or a launched process and the
    address it printed). NotStarted for anything else."""
    if surface not in SERVER_MODULES:
        raise NotStarted(f"{surface!r} is not a surface the factory runs")
    if (server is None) == (process is None):
        raise NotStarted("hand over the server the factory started, or the process the red team launched")
    url, alive = _from_server(surface, server, home) if server is not None else \
        _from_process(surface, process, base_url, home)  # type: ignore[arg-type]
    handle = Started(surface, url, str(Path(home)))
    _ISSUED[id(handle)] = (handle, alive)
    return handle


def issued(handle: object) -> bool:
    """Whether ``handle`` came from `register`, and what it names still runs."""
    entry = _ISSUED.get(id(handle))
    return entry is not None and entry[0] is handle and entry[1]()


def forget(handle: Started) -> None:
    """The surface stopped: its handle names nothing any more."""
    _ISSUED.pop(id(handle), None)
