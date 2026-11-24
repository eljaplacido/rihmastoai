"""The keys Gnomon holds for itself, by name only (FR-MDL1-AC-10).

Gnomon keeps keys a person gives it (`gnomon key set <endpoint>`) in its own credential store, outside every
repository, and puts one in its process's environment when the variable an endpoint's `api_key_env` names is
not set (packages/gnomon-core/src/credentials.ts: ``credentialsPath``, ``applyCredentials``). So an endpoint
whose variable Rihmasto cannot see may still have its key. Models setup asks Gnomon which names it holds with
`gnomon key list`, which prints names only, never a value. When Gnomon cannot say, it looks only at whether
the store exists. Rihmasto never opens the store and never reads a key.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

TTL = 30.0                                    # seconds a listing is kept: Models setup asks on every view
_LISTED = re.compile(r"^  ([A-Z_][A-Z0-9_]{0,63})(?:\s|$)")
_HELD: dict[str, Any] = {}


def store_path() -> Path:
    """Where Gnomon keeps the keys `gnomon key set` stores: under $XDG_DATA_HOME when set, else %APPDATA% on
    Windows and ~/.local/share elsewhere. Only its presence is ever asked."""
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg:
        return Path(xdg) / "gnomon" / "credentials.json"
    if os.name == "nt":
        base = os.environ.get("APPDATA", "").strip() or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "gnomon" / "credentials.json"
    return Path.home() / ".local" / "share" / "gnomon" / "credentials.json"


def held() -> frozenset[str] | None:
    """The key variables Gnomon holds, by `gnomon key list`; None when it cannot say (no Gnomon here, or the
    command failed). Kept for TTL seconds."""
    from kernel.model import gnomon_cmd
    from kernel.models_setup import gnomon_found

    cmd = os.environ.get("GNOMON_CMD", "")
    kept = _HELD.get(cmd)
    if kept is not None and time.monotonic() - kept[0] < TTL:
        return kept[1]
    names: frozenset[str] | None = None
    if gnomon_found():
        try:
            proc = subprocess.run([*gnomon_cmd(), "key", "list"], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=15, stdin=subprocess.DEVNULL)
            if proc.returncode == 0:
                names = frozenset(m.group(1) for x in proc.stdout.splitlines() if (m := _LISTED.match(x)))
        except (OSError, subprocess.TimeoutExpired):
            names = None
    _HELD[cmd] = (time.monotonic(), names)
    return names


def forget() -> None:
    """Drop the kept listings: the next view asks Gnomon again."""
    _HELD.clear()


def kind_of(name: str, names: frozenset[str] | None) -> str:
    """How a key not set here is found: "gnomon" (Gnomon names it), "gnomon_maybe" (Gnomon could not say, and
    its store exists) or "env" (not set anywhere Rihmasto knows of)."""
    if names is not None:
        return "gnomon" if name in names else "env"
    return "gnomon_maybe" if store_path().exists() else "env"
