"""Which local folders the cockpit may read for a person (docs/guides/inputs.md, The material map).

The cockpit runs on the machine whose files it would read, so a folder a person names there is read only:
- by a persona that may create or adopt a project (`READERS`), signed like any write;
- under the user's home folder or a root the operator configured (``RIHMASTO_SOURCE_ROOTS``, folders
  separated by the system's path separator);
- never a system folder (the operating system, programs, devices), and never a folder of keys or
  credentials (``.ssh``, ``.gnupg``, ``.aws`` and the like), wherever it is.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOTS_ENV = "RIHMASTO_SOURCE_ROOTS"
READERS = ("business_owner", "product_owner", "developer", "it")
SYSTEM = ("C:/Windows", "C:/Program Files", "C:/Program Files (x86)", "C:/ProgramData", "/etc", "/usr", "/bin",
          "/sbin", "/lib", "/lib64", "/boot", "/dev", "/proc", "/sys", "/var", "/opt", "/root", "/System",
          "/Library", "/private/etc", "/private/var")
KEY_FOLDERS = frozenset({".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".config/gcloud", ".password-store"})


class SourceRefused(PermissionError):
    """A folder the cockpit may not read for this person."""


def roots() -> list[Path]:
    """Where the cockpit may read: the user's home and the configured roots."""
    found = [Path.home()]
    found += [Path(p) for p in os.environ.get(ROOTS_ENV, "").split(os.pathsep) if p.strip()]
    return [p.expanduser().resolve() for p in found]


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _within(path: Path, folder: str) -> bool:
    """Whether ``path`` is ``folder`` or under it, case-insensitively (a Windows drive's folders)."""
    p, f = path.as_posix().lower().rstrip("/"), folder.lower().rstrip("/")
    return p == f or p.startswith(f + "/")


def check_folder(text: str, persona: str) -> Path:
    """The folder a person named, resolved, when the cockpit may read it for them; else SourceRefused (or
    ValueError when it is no folder)."""
    if persona not in READERS:
        raise SourceRefused(f"refused: a {persona} may not have the cockpit read a folder; "
                            f"{', '.join(READERS)} may")
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("no folder given")
    path = Path(raw).expanduser().resolve()
    why = _refused(path)
    if why:
        raise SourceRefused(f"refused: {path} {why}")
    if not path.is_dir():
        raise ValueError(f"{path} is not a folder")
    return path


def _keys(path: Path) -> bool:
    parts = [p.lower() for p in path.parts]
    pairs = {"/".join(parts[i:i + 2]) for i in range(len(parts))}
    return bool(KEY_FOLDERS & (set(parts) | pairs))


def _refused(path: Path) -> str:
    """Why the cockpit may not read ``path``, or "". A system folder is read only where a root inside it was
    given (a home under /root, a root under /var)."""
    system = next((s for s in SYSTEM if _within(path, s)), None)
    if system and not any(_under(path, r) and _within(r, system) for r in roots()):
        return f"is a system folder; the cockpit reads folders under your home or the roots in {ROOTS_ENV}"
    if not any(_under(path, r) for r in roots()):
        return f"is outside your home folder and the roots in {ROOTS_ENV}; the operator may add a root there"
    if _keys(path):
        return "holds keys or credentials; it is never read"
    return ""
