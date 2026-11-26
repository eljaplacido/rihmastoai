"""Which Rihmasto this is (FR-PUB2): the version ``pyproject.toml`` declares, read at run time.

Rihmasto runs from a checkout, so the checkout's ``pyproject.toml`` is the truth: ``rihmasto --version`` prints
it, ``rihmasto doctor`` reports it, Settings, About and help shows it, Ask Rihma says it, and the MCP server
tells an IDE agent it as ``serverInfo.version``. An installed distribution's metadata is the fallback when the
file cannot be read; "unknown" is said when neither can, never a made-up number.
"""

from __future__ import annotations

import re
import tomllib
from functools import lru_cache
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNKNOWN = "unknown"


def declared(root: Path = ROOT) -> str | None:
    """The version ``pyproject.toml`` under ``root`` declares, or None."""
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = (data.get("project") or {}).get("version")
    return str(version) if version else None


def installed() -> str | None:
    """The version of an installed ``rihmasto`` distribution, or None."""
    try:
        return metadata.version("rihmasto")
    except metadata.PackageNotFoundError:
        return None


@lru_cache(maxsize=1)
def rihmasto_version() -> str:
    """This Rihmasto's version: the checkout's, else the installed one's, else "unknown"."""
    return declared() or installed() or UNKNOWN


def is_prerelease(version: str) -> bool:
    """An alpha, beta, release candidate or development version (PEP 440)."""
    return bool(re.search(r"(?:a|b|rc)\d+|\.dev\d+", version or ""))
