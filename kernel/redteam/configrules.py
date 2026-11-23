"""The configuration rules: Dockerfiles (`dockerrules.py`) and GitHub Actions workflows
(`actionsrules.py`), and the container entry points the Python rules allow. This module keeps the
names the rest of the red team imports.
"""

from __future__ import annotations

from kernel.redteam.actionsrules import check_actions
from kernel.redteam.dockerrules import (
    Instruction,
    check_dockerfile,
    entry_points,
    entry_scripts,
    entry_words,
    imported_modules,
    instructions,
    is_entry_point,
    module_paths,
    script_entry_points,
    words,
)

__all__ = ["Instruction", "check_actions", "check_dockerfile", "entry_points", "entry_scripts", "entry_words",
           "imported_modules", "instructions", "is_entry_point", "module_paths", "script_entry_points", "words"]
