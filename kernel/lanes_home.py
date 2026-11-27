"""Which lanes a factory home uses, so a throwaway home never shares the owner's (FR-NVL3).

Lanes (``$GF_LANES``, else ``~/gf-lanes``) hold the workspaces, the lane locks and Gnomon's records of every home
that runs on the machine. The owner's acceptance run started the demo as the README says, without GF_LANES: its
console made a workspace in the same ~/gf-lanes the owner's real homes use, beside their lane locks.

``settle`` runs when the cockpit starts:

- ``$GF_LANES`` set: it is used, as always;
- a demo home (kernel/demo.py writes ``demo.json``) or a home with a ``.lanes-here`` file keeps its lanes inside
  itself, in ``<home>/lanes``, and the cockpit's environment says so to everything it starts;
- otherwise the shared root is used, and the home is written down there (``.homes.json``): a cockpit on a home
  that shares the root with another home that still exists is warned, with how to keep them apart.

Standard library only.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import MutableMapping
from pathlib import Path

from kernel.store import updating_json

LANES_ENV = "GF_LANES"
HERE = ".lanes-here"
HOMES = ".homes.json"
DEMO = "demo.json"


def keeps_own(home: Path) -> bool:
    """A demo home, or one marked to keep its lanes inside itself."""
    return (home / DEMO).is_file() or (home / HERE).is_file()


def settle(home: str | Path, environ: MutableMapping[str, str] | None = None) -> str:
    """Choose the lanes for ``home`` (see the module) and say in one line which, with a warning when shared."""
    env = os.environ if environ is None else environ
    home = Path(home).resolve()
    if env.get(LANES_ENV):
        return f"Lanes: {env[LANES_ENV]} (GF_LANES)."
    if keeps_own(home):
        env[LANES_ENV] = str(home / "lanes")
        return f"Lanes: {home / 'lanes'}, inside this home, apart from every other home's."
    root = Path.home() / "gf-lanes"
    others: list[str] = []
    with contextlib.suppress(OSError), updating_json(root / HOMES, []) as homes:
        others = [h for h in homes if isinstance(h, str) and h != str(home) and Path(h).is_dir()]
        if str(home) not in homes:
            homes.append(str(home))
    if not others:
        return f"Lanes: {root}."
    return (f"Lanes: {root} is shared with another home ({others[0]}): workspaces and lane locks are shared too. "
            f"To keep this home's apart, start it with GF_LANES set (for example GF_LANES={home / 'lanes'}), or "
            f"create {home / HERE}.")

