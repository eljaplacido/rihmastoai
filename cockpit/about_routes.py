"""The cockpit's About and help routes (FR-PUB2; kernel/about.py).

- ``GET /api/about``: which Rihmasto this is (pyproject.toml's version, and whether it is a pre-release), the
  commands that say the same in a terminal, and the guides with their place in this checkout and on GitHub.
- ``GET /api/about/doctor``: this machine's check, ``rihmasto doctor`` trimmed to what a person reads.

Both read; neither records anything.
"""

from __future__ import annotations

from typing import Any

from kernel import about as kabout

ROUTES = [
    ("GET", r"/api/about", "get_about"),
    ("GET", r"/api/about/doctor", "get_about_doctor"),
]
# The machine check runs Gnomon's --version (up to 30 seconds): it never holds the write lock.
UNLOCKED = {"get_about_doctor"}
Reply = tuple[int, dict[str, Any]]


class AboutRoutes:
    """Mixed into the cockpit's Api: it has ``factory``."""

    factory: Any

    def get_about(self, **_: object) -> Reply:
        return 200, kabout.view()

    def get_about_doctor(self, **_: object) -> Reply:
        return 200, kabout.machine(self.factory.home)
