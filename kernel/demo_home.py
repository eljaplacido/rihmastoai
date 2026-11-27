"""A demo home stays self-contained when the cockpit opens it (FR-AOP3).

`rihmasto demo` builds a throwaway home with no model keys, no network and no Gnomon. Opening the cockpit on it
must not reach the machine's own state: by default the cockpit prepares the analyst lane under ``~/gf-lanes`` and
asks real Gnomon, which on a demo would touch the person's real lanes and send demo questions to a real model.

On a demo home (its ``demo.json`` marker) the cockpit therefore uses the home's own lanes (``<home>/lanes``, set as
``GF_LANES`` for this process, whatever it was), and the assistant answers from the cockpit map and Rihma's rules
unless the person asks for Gnomon with ``--assistant gnomon`` (in the demo's own lanes then).
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

MARKER = "demo.json"     # kernel/demo.py DEMO_MARKER
LANES_ENV = "GF_LANES"   # kernel/lanes.py LANES_ENV


def is_demo(home: Path) -> bool:
    return (Path(home) / MARKER).is_file()


def contain(factory: Any, choice: str | None,
            environ: MutableMapping[str, str] | None = None) -> tuple[str | None, list[str]]:
    """The assistant choice to use and what to say, with the demo's lanes set; nothing changes for a real home."""
    env = os.environ if environ is None else environ
    if not is_demo(factory.home):
        return choice, []
    lanes = Path(factory.home) / "lanes"
    env[LANES_ENV] = str(lanes)
    notes = [f"This is a demo home: it keeps its own lanes ({lanes}) and touches none of this machine's."]
    if choice is None:
        choice = "map"
        notes.append("On a demo home the assistant answers from the cockpit map and Rihma's rules; start the cockpit "
                     "with --assistant gnomon to ask Gnomon instead (in the demo's own lanes).")
    return choice, notes
