"""Whether a folder or repository is already adopted (FR-RPJ1; docs/brownfield.md, Adopted already).

The New project dialog says so before a second project is made by accident: a project adopted from the same
folder (its resolved path, or the folder its snapshot was taken from) or the same repository (the same origin
address, whatever the scheme, with any credential taken out: kernel/material_git.py). Adopting it again as a
new project stays possible, as an explicit choice (the cockpit's ``again``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from kernel.material_git import same_origin_key


def _same_path(a: str | None, b: Path) -> bool:
    if not a:
        return False
    try:
        left = Path(a).expanduser().resolve()
    except (OSError, ValueError):
        return False
    return os.path.normcase(str(left)) == os.path.normcase(str(b))


def adopted_as(factory: Any, folder: str | Path | None = None, origin: str | None = None) -> list[dict[str, Any]]:
    """The adopted projects that hold this folder or repository: their id, title and why (path or origin)."""
    from kernel.adopt import is_adopted

    where = Path(folder).expanduser().resolve() if folder else None
    key = same_origin_key(origin)
    out = []
    for p in factory.projects():
        if p.pid.startswith("_") or not is_adopted(p):
            continue
        a = p.read("adopted.json") or {}
        by = _same(a, where, key)
        if by:
            out.append({"project": p.pid, "title": p.meta.get("title") or p.pid, "by": by,
                        "intent": a.get("intent"), "at": a.get("at")})
    return out


def _same(a: dict[str, Any], where: Path | None, key: str | None) -> str | None:
    """Why an adoption's record holds this folder ("path") or repository ("origin"), or None."""
    froms = [x for x in (a.get("source"), (a.get("snapshot") or {}).get("from")) if x and "://" not in x]
    if where is not None and any(_same_path(x, where) for x in froms):
        return "path"
    source = str(a.get("source"))
    origins = {same_origin_key(a.get("origin")), same_origin_key(source) if "://" in source else None}
    return "origin" if key and key in origins else None
