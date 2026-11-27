"""The factory home and project folders.

Every file the kernel writes goes through here: JSON is written atomically, with LF line
endings and a trailing newline, so a crash never leaves half a file and the bytes are the
same on every machine. Time comes from a clock object, so tests can fix it.

A record file (a canon's lists and cards, the factory's signals) is changed only through
``updating_json``: read, changed and written back under a lock, so writers at once, in threads
or in processes, never lose each other's change or take the same id.
"""

from __future__ import annotations

import contextlib
import copy
import datetime as dt
import json
import os
import re
import secrets
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from kernel.filelock import locked
from kernel.journal import before_write
from kernel.ledgerstore import LedgerStore
from kernel.people import signed_identity

if TYPE_CHECKING:
    from kernel.canon import Canon

# The factory home's variables (D-0013). RIHMASTO_HOME is the name; RIHMA_HOME and the working
# name's GNOMONFACTORY_HOME are still honoured, in that order. A child process reads the first one
# set, so a parent that hands its home down passes --home or sets every name in HOME_ENVS: HOME_ENV
# alone loses to an inherited RIHMASTO_HOME or RIHMA_HOME (the cockpit's job runner still sets only
# HOME_ENV, D-0013).
RIHMASTO_HOME_ENV = "RIHMASTO_HOME"
RIHMA_HOME_ENV = "RIHMA_HOME"
HOME_ENV = "GNOMONFACTORY_HOME"
HOME_ENVS = (RIHMASTO_HOME_ENV, RIHMA_HOME_ENV, HOME_ENV)
REPO_ROOT = Path(__file__).resolve().parent.parent
# The records an archived project still takes: its archiving and its restoring (kernel/project_archive.py).
ARCHIVE_KINDS = ("project_archived", "project_restored")
# The payload fields that name the person who made a write (a ledger record's signer).
SIGNED_KEYS = ("person", "by", "chosen_by", "requested_by", "stopped_by", "accepted_as_is_by")

MATURITIES = ("explore", "demo", "pilot", "production")
MODES = ("socratic", "assume", "mixed")
STAGES = {
    1: "need and decision",
    2: "concept",
    3: "technical translation",
    4: "spec and architecture",
    5: "build and verify",
    6: "user validation",
    7: "deploy and measure",
}


def home_from_env(environ: Mapping[str, str] | None = None) -> str | None:
    """The factory home the environment names: the first of RIHMASTO_HOME, RIHMA_HOME and
    GNOMONFACTORY_HOME that is set and not empty, or None when none is."""
    env = os.environ if environ is None else environ
    return next((env[name] for name in HOME_ENVS if env.get(name)), None)


def default_home(environ: Mapping[str, str] | None = None) -> Path:
    """The factory home when no --home is given: the environment's, else var/ in the checkout."""
    return Path(home_from_env(environ) or REPO_ROOT / "var")


class Clock:
    """Wall-clock time in UTC."""

    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.UTC).replace(microsecond=0)

    def stamp(self) -> str:
        return self.now().isoformat().replace("+00:00", "Z")

    def today(self) -> dt.date:
        return self.now().date()


class FixedClock(Clock):
    """A clock that says what it is told. Tests move it with ``advance``."""

    def __init__(self, at: str = "2026-11-22T12:00:00Z"):
        self._at = dt.datetime.fromisoformat(at.replace("Z", "+00:00"))

    def now(self) -> dt.datetime:
        return self._at

    def advance(self, **delta: float) -> None:
        self._at = self._at + dt.timedelta(**delta)


T = TypeVar("T")
# On Windows a file another thread or process has open cannot be replaced, nor opened while it is
# being replaced. That lasts milliseconds, so the step is tried again for about two seconds.
_SHARING_PAUSES = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0)


def _patiently(step: Callable[[], T]) -> T:
    for pause in _SHARING_PAUSES:
        try:
            return step()
        except PermissionError:
            if os.name != "nt":
                raise
            time.sleep(pause)
    return step()


def write_text(path: Path, text: str) -> None:
    """Write text atomically with LF line endings."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    before_write(path)      # a change that fails later puts this file back (kernel/journal.py)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        _patiently(lambda: os.replace(tmp, path))
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def write_json(path: Path, obj: object) -> None:
    write_text(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


class RecordUnreadable(json.JSONDecodeError):
    """A record file that is not valid JSON (damaged, truncated or hand-edited). Its message names the file and
    the line, and says what to do, never only the parser's words; it is still a JSONDecodeError (a ValueError)."""

    def __init__(self, path: Path, err: json.JSONDecodeError):
        super().__init__(err.msg, err.doc, err.pos)
        self.path = Path(path)
        self.plain = (f"{self.path.name} cannot be read (line {err.lineno}): it is not valid JSON. Restore it from a "
                      "backup or an export, or ask IT to; nothing else was changed")
        self.args = (self.plain,)

    def __str__(self) -> str:
        return self.plain

    def __reduce__(self) -> tuple[Any, ...]:
        return ValueError, (self.plain,)


def _load(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError as exc:
            raise RecordUnreadable(path, exc) from None


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return _patiently(lambda: _load(path))
    except FileNotFoundError:
        return default


def lock_path(path: Path) -> Path:
    """The lock file that guards one record file: its name with `.lock` after it."""
    path = Path(path)
    return path.with_name(path.name + ".lock")


# A record file's lock is held for milliseconds (never across a model call), so a writer that still
# waits after this long has found a stuck holder, and says so.
RECORD_WAIT_SECONDS = 120.0


def records_lock(path: Path) -> contextlib.AbstractContextManager[None]:
    """Hold a lock over record files (kernel/filelock.py): waited for across threads and processes,
    and re-entrant in the thread that holds it, so one locked change may make another."""
    return locked(path, reentrant=True, timeout=RECORD_WAIT_SECONDS)


@contextlib.contextmanager
def updating_json(path: Path, default: Any, *, lock: Path | None = None) -> Iterator[Any]:
    """The kernel's one read-modify-write of a JSON record file. Under the file's lock (or ``lock``,
    when several files share one) it reads the file (a copy of ``default`` when there is none),
    yields the value for the block to change in place, and writes it back atomically when the
    block ends, if it changed. A block that raises writes nothing."""
    with records_lock(lock or lock_path(path)):
        value = read_json(path, copy.deepcopy(default))
        before = copy.deepcopy(value)
        yield value
        if value != before:
            write_json(path, value)


_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(text: str, limit: int = 32) -> str:
    slug = _NON_SLUG.sub("-", text.lower()).strip("-")
    return (slug[:limit].rstrip("-")) or "project"


class ProjectUnreadable(ValueError):
    """A project whose project.json cannot be read: it is kept out of every list (the others keep working) and
    named, with how to restore it, wherever it is asked for (FR-NVL3)."""

    def __init__(self, pid: str, title: str, cause: str):
        self.pid, self.title, self.cause = pid, title, cause
        super().__init__(f"{title} cannot be read (project.json is not valid: {cause}). Its other records are kept: "
                         f"restore project.json from a backup or an export of {pid}, or ask IT to; the other "
                         "projects keep working")


def _first_title(ledger: Path) -> str | None:
    """The title a project was created with, from its ledger's first record (when project.json cannot say)."""
    try:
        with open(ledger, encoding="utf-8") as fh:
            first = json.loads(fh.readline() or "{}")
    except (OSError, ValueError):
        return None
    event = first.get("event") if isinstance(first, dict) else None
    title = ((event or {}).get("payload") or {}).get("title") if isinstance(event, dict) else None
    return title if isinstance(title, str) and title else None


class ProjectArchived(ValueError):
    """A write to an archived project: it is read-only until a person restores it (kernel/project_archive.py)."""


class Project:
    """One product the factory works on: a folder holding its canon, spec, contract and ledger."""

    def __init__(self, factory: Factory, pid: str):
        self.factory = factory
        self.pid = pid
        self.dir = factory.projects_dir / pid

    def path(self, *parts: str) -> Path:
        return self.dir.joinpath(*parts)

    def read(self, name: str, default: Any = None) -> Any:
        return read_json(self.path(name), default)

    def write(self, name: str, obj: object) -> None:
        write_json(self.path(name), obj)

    @property
    def meta(self) -> dict[str, Any]:
        try:
            meta: dict[str, Any] = self.read("project.json", {})
        except RecordUnreadable as exc:
            raise ProjectUnreadable(self.pid, self.title_anyway(), f"line {exc.lineno}") from None
        if not isinstance(meta, dict):
            raise ProjectUnreadable(self.pid, self.title_anyway(), "it holds no project")
        return meta

    def title_anyway(self) -> str:
        """The project's title even when project.json cannot be read: its ledger's first record, else its id."""
        return _first_title(self.path("ledger.jsonl")) or self.pid

    def unreadable(self) -> ProjectUnreadable | None:
        """Why project.json cannot be read, or None when it can."""
        try:
            _ = self.meta
        except ProjectUnreadable as exc:
            return exc
        return None

    def update_meta(self, **changes: Any) -> dict[str, Any]:
        """Change some of project.json's fields, under its lock: a change made at the same time
        (the pipeline moving the stage while a person asks for a pause) is kept, never written over."""
        with updating_json(self.path("project.json"), {}) as meta:
            meta.update(changes)
            meta["updated"] = self.factory.clock.stamp()
        result: dict[str, Any] = meta
        return result

    @property
    def holdouts_dir(self) -> Path:
        """Holdout checks live outside the project folder, in a separate custody (FR-O3)."""
        return self.factory.holdouts_dir / self.pid

    def ledger(self) -> LedgerStore:
        return LedgerStore(self.path("ledger.jsonl"), clock=self.factory.clock)

    def log(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Record a transition in the project's ledger (FR-L2: state changes are appended). While a
        verified identity signs the write (enforced access, D-0016), a record that names its person
        also names that identity. An archived project is read-only: only its restoring is recorded."""
        if kind not in ARCHIVE_KINDS and self.meta.get("archived"):
            raise ProjectArchived(f"{self.pid} is archived: it is read-only until a person restores it "
                                  f"(rihmasto project restore {self.pid})")
        if "identity" not in payload:
            for key in SIGNED_KEYS:
                stamp = signed_identity(payload.get(key))
                if stamp:
                    payload = {**payload, **stamp}
                    break
        return self.ledger().append(kind, payload)

    def __repr__(self) -> str:
        return f"Project({self.pid!r})"


class Factory:
    """The factory home: projects, holdouts, paved roads and the factory-level ledger."""

    def __init__(self, home: str | Path | None = None, clock: Clock | None = None):
        # Absolute and resolved from the start: a relative --home (README: `--home var/demo`) would otherwise be read
        # against whichever folder a git clone or a job runs in, and Windows' 8.3 short temp paths (RUNNER~1) must
        # match Path.resolve() everywhere (cockpit/server.py, tests).
        self.home = (Path(home).expanduser() if home else default_home()).resolve()
        self.clock = clock or Clock()
        self.projects_dir = self.home / "projects"
        self.holdouts_dir = self.home / "holdouts"

    @property
    def paved_roads_path(self) -> Path:
        return self.home / "paved_roads.json"

    def new_project(self, title: str, *, maturity: str | None = None, mode: str | None = None,
                    source_kind: str = "idea", profile: str | None = None,
                    posture: Mapping[str, Any] | None = None) -> Project:
        """A new project, at demo maturity in mixed mode unless named. With ``posture`` (name, weights, by,
        persona: kernel/posture.py) its mode and maturity are the posture's unless named, and the choice is
        recorded with who made it."""
        from kernel.posture import for_new_project, record_choice
        from kernel.profiles import PROFILES

        maturity, mode, chosen = for_new_project(posture, maturity, mode)
        if profile is not None and profile not in PROFILES:
            raise ValueError(f"profile must be one of {', '.join(PROFILES)}, got {profile!r}")
        if maturity not in MATURITIES:
            raise ValueError(f"maturity must be one of {', '.join(MATURITIES)}, got {maturity!r}")
        if mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}, got {mode!r}")
        pid = f"{slugify(title)}-{secrets.token_hex(3)}"
        project = Project(self, pid)
        project.dir.mkdir(parents=True, exist_ok=False)
        now = self.clock.stamp()
        project.write("project.json", {
            "id": pid, "title": title, "maturity": maturity, "mode": mode,
            "source_kind": source_kind, "stage": 1, "created": now, "updated": now,
            **({"profile": profile} if profile else {}), **({"posture": dict(chosen, at=now)} if chosen else {}),
        })
        _open_canon()(project).init(goal=title)
        project.log("project_created", {"id": pid, "title": title, "maturity": maturity, "mode": mode,
                                        **({"profile": profile} if profile else {})})
        if profile:
            project.log("profile_chosen", {"profile": profile, "basis": {"by": "person at creation"}})
        if chosen:
            record_choice(project, chosen)
        return project

    def project(self, pid: str) -> Project:
        project = Project(self, pid)
        if not project.path("project.json").exists():
            raise KeyError(f"no project {pid!r} in {self.projects_dir}")
        return project

    def projects(self, *, archived: bool = False) -> list[Project]:
        """Every project, but not an archived one unless asked (kernel/project_archive.py): an archived project is
        hidden from every list, and still opened by its id."""
        if not self.projects_dir.exists():
            return []
        found = [p for p in self._folders() if p.unreadable() is None]
        return found if archived else [p for p in found if not p.meta.get("archived")]

    def _folders(self) -> list[Project]:
        return [Project(self, p.name) for p in sorted(self.projects_dir.iterdir()) if (p / "project.json").exists()]

    def unreadable_projects(self) -> list[dict[str, Any]]:
        """The projects whose project.json cannot be read, each named with what to do (FR-NVL3): kept out of
        projects() so one damaged file never takes the others down."""
        if not self.projects_dir.exists():
            return []
        out = []
        for project in self._folders():
            bad = project.unreadable()
            if bad is not None:
                out.append({"id": project.pid, "title": bad.title, "file": "project.json",
                            "said": f"{bad.title} cannot be read (project.json is not valid: {bad.cause})",
                            "how": f"Restore projects/{project.pid}/project.json from a backup or an export, or ask "
                                   "IT to. Its ledger and other records are kept; the other projects keep working."})
        return out


def _open_canon() -> Callable[[Project], Canon]:
    """The canon's constructor, imported when first needed (kernel.canon imports this module).
    Typed here so this strictly checked module never calls an unannotated function."""
    import kernel.canon

    return kernel.canon.Canon
