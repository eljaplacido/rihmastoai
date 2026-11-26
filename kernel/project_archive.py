"""Archive, restore and remove a project (FR-SET1).

The owner (2026-11-24): "Delete so many duplicate projects." Until now a project, once made, stayed forever.

- **Archive**: the project is hidden from every list (``Factory.projects()`` leaves it out), read-only (its ledger
  takes no record but its restoring, kernel/store.py ``Project.log``), and restorable. Signed by a named person
  with a persona that may, recorded in the project's own ledger and in the factory's (``project_archived``).
- **Restore**: back in the lists and writable; recorded (``project_restored``).
- **Remove**: only an archived project, and only with a confirmation that names it (its id) and says it cannot be
  undone. Its records are first kept as an export file, a zip of the project's folder and its holdout custody,
  in ``<home>/exports/removed/``; the factory's ledger records the removal with the file and its sha256
  (``project_removed``). Then the folder is gone.

``duplicates`` finds projects that share a title, so a person can archive the copies they do not need: the
cockpit's Projects page, Ask Rihma ("archive the duplicate projects") and ``rihmasto project duplicates``.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path
from typing import Any

from kernel.canon import DecisionRefused
from kernel.people import PERSONAS, is_person
from kernel.store import Factory, Project

ARCHIVERS = ("business_owner", "product_owner", "developer", "it", "operations")
CANNOT_UNDO = "cannot be undone"
EXPORTS = ("exports", "removed")


class ArchiveRefused(DecisionRefused):
    """An archive, restore or removal the rules refuse: the reason says which."""


def is_archived(project: Project) -> bool:
    return bool(project.meta.get("archived"))


def _signed(project: Project, person: str, persona: str, verb: str) -> None:
    from kernel.access import require

    if not is_person(person):
        raise ArchiveRefused(f"{person!r} is not a person: a named person {verb}s a project")
    if persona not in PERSONAS:
        raise ArchiveRefused(f"persona must be one of {', '.join(PERSONAS)}")
    if persona not in ARCHIVERS:
        raise ArchiveRefused(f"a {persona} may not {verb} a project (may: {', '.join(ARCHIVERS)})")
    if project.pid.startswith("_"):
        raise ArchiveRefused("Rihma's own proposals are not a project to archive or remove")
    require(project, person, persona)


def _factory_log(factory: Factory, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The archive's record in the factory's ledger too, so it outlives a removed project."""
    from kernel.learn import factory_project

    return factory_project(factory).log(kind, {"project": payload.get("project"), **payload})


def row(project: Project) -> dict[str, Any]:
    """A project as the archive lists show it."""
    meta = project.meta
    return {"id": project.pid, "title": meta.get("title") or project.pid, "updated": meta.get("updated"),
            "created": meta.get("created"), "source_kind": meta.get("source_kind"), "profile": meta.get("profile"),
            "archived": meta.get("archived")}


def archived(factory: Factory) -> list[dict[str, Any]]:
    """Every archived project, newest archive first."""
    rows = [row(p) for p in factory.projects(archived=True) if is_archived(p)]
    return sorted(rows, key=lambda r: str((r["archived"] or {}).get("at")), reverse=True)


def archive(factory: Factory, pid: str, *, person: str, persona: str, reason: str = "") -> dict[str, Any]:
    """Hide a project from every list and make it read-only, restorable. Recorded first, then set."""
    project = factory.project(pid)
    _signed(project, person, persona, "archive")
    if is_archived(project):
        raise ArchiveRefused(f"{pid} is already archived")
    why = str(reason or "").strip()[:500]
    at = factory.clock.stamp()
    record = {"project": pid, "title": project.meta.get("title"), "person": person, "persona": persona, "reason": why}
    project.log("project_archived", record)
    project.update_meta(archived={"by": person, "persona": persona, "at": at, "reason": why})
    _factory_log(factory, "project_archived", record)
    return row(project)


def restore(factory: Factory, pid: str, *, person: str, persona: str) -> dict[str, Any]:
    """Bring an archived project back into the lists, writable again."""
    project = factory.project(pid)
    _signed(project, person, persona, "restore")
    if not is_archived(project):
        raise ArchiveRefused(f"{pid} is not archived")
    project.update_meta(archived=None)
    record = {"project": pid, "title": project.meta.get("title"), "person": person, "persona": persona}
    project.log("project_restored", record)
    _factory_log(factory, "project_restored", record)
    return row(project)


def _export_path(factory: Factory, pid: str) -> Path:
    stamp = re.sub(r"[^0-9TZ]", "", factory.clock.stamp())
    return factory.home.joinpath(*EXPORTS, f"{pid}-{stamp}.zip")


def export(project: Project) -> dict[str, Any]:
    """The project's records as one zip: its folder under ``project/`` and its holdout custody under
    ``holdouts/``. Nothing is left out; the file's sha256 is returned."""
    out = _export_path(project.factory, project.pid)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for top, folder in (("project", project.dir), ("holdouts", project.holdouts_dir)):
            if not folder.exists():
                continue
            for path in sorted(folder.rglob("*")):
                if path.is_file() and not path.name.endswith(".lock"):
                    zf.write(path, f"{top}/{path.relative_to(folder).as_posix()}")
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    return {"file": str(out), "relative": out.relative_to(project.factory.home).as_posix(), "sha256": digest,
            "bytes": out.stat().st_size}


def confirmation(project: Project) -> str:
    """What a person confirms before a removal: the project named, and that it cannot be undone."""
    title = project.meta.get("title") or project.pid
    return (f"Remove {title} ({project.pid}) for good: this {CANNOT_UNDO}. Its records are kept first as an "
            f"export file in {'/'.join(EXPORTS)}/.")


def remove(factory: Factory, pid: str, *, person: str, persona: str, confirm: str) -> dict[str, Any]:
    """Remove an archived project after its records are exported; ``confirm`` is the project's id, typed."""
    from kernel.roads import rmtree

    project = factory.project(pid)
    _signed(project, person, persona, "remove")
    if not is_archived(project):
        raise ArchiveRefused(f"{pid} is not archived: archive it first, then remove it")
    if str(confirm or "").strip() != pid:
        raise ArchiveRefused(f"to remove it, confirm by naming it: {pid} (removing a project {CANNOT_UNDO})")
    title = project.meta.get("title")
    kept = export(project)
    _factory_log(factory, "project_removed", {"project": pid, "title": title, "export": kept["relative"],
                                              "sha256": kept["sha256"], "person": person, "persona": persona})
    rmtree(project.dir)
    rmtree(project.holdouts_dir)
    return {"removed": pid, "title": title, "export": kept}


def _key(title: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(title or "").lower()).strip()


def duplicates(factory: Factory) -> list[dict[str, Any]]:
    """Projects that share a title (letters and digits, any case): per title, the one to keep (the one with the
    most records, then the newest) and the copies a person may archive."""
    groups: dict[str, list[Project]] = {}
    for p in factory.projects():
        if not p.pid.startswith("_"):
            groups.setdefault(_key(p.meta.get("title")), []).append(p)
    out = []
    for key, members in sorted(groups.items()):
        if len(members) < 2 or not key:
            continue
        ranked = sorted(members, key=lambda p: (len(p.ledger().records()), str(p.meta.get("updated"))), reverse=True)
        out.append({"title": ranked[0].meta.get("title"), "keep": row(ranked[0]),
                    "copies": [row(p) for p in ranked[1:]]})
    return out


# -- `rihmasto project` ----------------------------------------------------------------------------------

def add_parsers(sub: Any) -> None:
    grp = sub.add_parser("project", help="archive, restore or remove a project; list the archived and duplicates")
    g = grp.add_subparsers(dest="sub", required=True)
    g.add_parser("archived", help="the archived projects")
    g.add_parser("duplicates", help="projects that share a title, and the copies to archive")
    for name, what in (("archive", "hide it from every list, read-only, restorable"),
                       ("restore", "bring an archived project back"),
                       ("remove", "remove an archived project for good, its records exported first")):
        p = g.add_parser(name, help=what)
        p.add_argument("pid")
        p.add_argument("--person", required=True)
        p.add_argument("--persona", required=True, choices=PERSONAS)
        if name == "archive":
            p.add_argument("--reason", default="")
        if name == "remove":
            p.add_argument("--confirm", default="", help="the project's id again: removing it cannot be undone")


def handlers(show: Any) -> dict[str, Any]:
    def removing(f: Factory, a: Any) -> None:
        if a.confirm.strip() != a.pid:
            project = f.project(a.pid)
            raise ArchiveRefused(f"{confirmation(project)} Run it again with --confirm {a.pid}")
        show(remove(f, a.pid, person=a.person, persona=a.persona, confirm=a.confirm))

    return {
        "project archived": lambda f, a: show({"archived": archived(f)}),
        "project duplicates": lambda f, a: show({"duplicates": duplicates(f)}),
        "project archive": lambda f, a: show(archive(f, a.pid, person=a.person, persona=a.persona, reason=a.reason)),
        "project restore": lambda f, a: show(restore(f, a.pid, person=a.person, persona=a.persona)),
        "project remove": removing,
    }
