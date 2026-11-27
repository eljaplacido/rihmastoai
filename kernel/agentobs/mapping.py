"""Which hub project is this project's, and whether its repository carries the hub's hooks (FR-OBS1).

**The mapping.** The hub names a project as its hooks resolve it, in this order: a ``cockpit.io/project-id``
annotation in the repository's ``catalog-info.yaml``; else ``owner/repo`` from the git remote ``origin`` (anything
but letters, digits, dots, underscores and hyphens made a hyphen); else ``local/<the folder's name>``. Rihmasto
works out the same candidates from the adopted or attached repository, without running anything in it, and
suggests the first one the hub knows. Nothing is mapped until a developer or IT confirms it or chooses another;
the choice is kept in the project's ``agentobs.json`` (the factory's records, never the repository) and recorded
in its ledger (``agentobs_mapped``, ``agentobs_unmapped``).

**The hooks.** The hub's ``install`` command writes a hook wrapper per harness: ``.claude/hooks/cockpit-hook.cmd``
or ``.sh`` (Claude Code, with entries in ``.claude/settings.json``), ``.cursor/hooks/cockpit-hook.*`` (Cursor, with
``.cursor/hooks.json``) and ``.opencode/plugins/cockpit.js`` (OpenCode). Whether those names exist is all that is
looked at: no file is opened or run.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from kernel.agentobs import FILE, MAPPERS
from kernel.canon import DecisionRefused
from kernel.people import is_person

HOOK_FILES = {"claude-code": (".claude/hooks/cockpit-hook.cmd", ".claude/hooks/cockpit-hook.sh"),
              "cursor": (".cursor/hooks/cockpit-hook.cmd", ".cursor/hooks/cockpit-hook.sh"),
              "opencode": (".opencode/plugins/cockpit.js",)}
CATALOG = "catalog-info.yaml"
ANNOTATION = re.compile(r"^\s*cockpit\.io/project-id\s*:\s*[\"']?([^\"'\s#]+)", re.MULTILINE)
HUB_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9._-]{1,100}\Z")
_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")
_REMOTE = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?\Z")


def _git(cwd: Path, *args: str) -> str:
    """git's answer in ``cwd``, or "" (no hooks, no credential helper, nothing prompted, nothing fetched)."""
    from kernel.agent_context import _git as safe_git

    try:
        return safe_git(cwd, *args).decode("utf-8", "replace").strip()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
        return ""


def repository(project: Any) -> dict[str, Any]:
    """Where the project's code is: an attached repository's folder; an adopted project's product repository and
    the folder or address it was adopted from. Empty for a project Rihmasto builds itself."""
    kind = project.meta.get("source_kind")
    if kind == "attached":
        info = project.meta.get("attached") or {}
        return {"kind": kind, "folder": Path(info["repo"]) if info.get("repo") else None, "git": None,
                "source": info.get("repo")}
    if kind == "adopted":
        source = str(project.meta.get("upstream") or "")
        folder = Path(source) if source and "://" not in source and not source.startswith("git@") else None
        return {"kind": kind, "folder": folder if folder and folder.is_dir() else None,
                "git": project.path("repo.git"), "source": source or None}
    return {"kind": kind, "folder": None, "git": None, "source": None}


def _segment(value: str) -> str:
    return _SEGMENT.sub("-", value.strip()).strip("-") or "unknown"


def _remote_id(url: str) -> str | None:
    found = _REMOTE.search(url.strip())
    return f"{_segment(found.group(1))}/{_segment(found.group(2))}" if found else None


def _catalog_text(repo: dict[str, Any]) -> str:
    folder, bare = repo["folder"], repo["git"]
    try:
        if folder is not None and (folder / CATALOG).is_file() and (folder / CATALOG).stat().st_size <= 65536:
            return (folder / CATALOG).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return _git(bare, "show", f"main:{CATALOG}")[:65536] if bare is not None and Path(bare).is_dir() else ""


def candidates(project: Any) -> list[dict[str, str]]:
    """The ids the hub's hooks would give this repository, most specific first, each with where it came from."""
    repo = repository(project)
    out: list[dict[str, str]] = []
    found = ANNOTATION.search(_catalog_text(repo))
    if found and HUB_ID.match(found.group(1)):
        out.append({"id": found.group(1), "from": f"the cockpit.io/project-id annotation in {CATALOG}"})
    remote = _git(repo["folder"], "config", "--get", "remote.origin.url") if repo["folder"] is not None else ""
    if not remote and repo["kind"] == "adopted" and repo["source"] and repo["folder"] is None:
        remote = str(repo["source"])                          # adopted from a git address
    rid = _remote_id(remote) if remote else None
    if rid:
        out.append({"id": rid, "from": "the git remote origin"})
    name = repo["folder"].name if repo["folder"] is not None else None
    if name:
        out.append({"id": f"local/{_segment(name)}", "from": "the folder's name (no catalog file, no remote)"})
    return [c for i, c in enumerate(out) if c["id"] not in [d["id"] for d in out[:i]]]


def suggest(cands: list[dict[str, str]], hub_projects: list[dict[str, Any]]) -> dict[str, str] | None:
    """The first candidate the hub knows, by its project id or its repository id."""
    known: dict[str, str] = {}
    for p in hub_projects:
        for key in ("project_id", "repository_id"):
            if isinstance(p.get(key), str):
                known.setdefault(p[key], str(p.get("project_id")))
    for c in cands:
        if c["id"] in known:
            return {"id": known[c["id"]], "from": c["from"]}
    return None


def current(project: Any) -> dict[str, Any] | None:
    """The mapping a person recorded, or None."""
    doc = project.read(FILE, None)
    return doc if isinstance(doc, dict) and doc.get("hub_project") else None


def map_project(project: Any, hub_project: str, *, person: str, persona: str, how: str = "chosen",
                reason: str = "") -> dict[str, Any] | None:
    """A developer or IT maps the project to a hub project (an empty id unmaps it); recorded in its ledger."""
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a mapping is chosen by a named person")
    if persona not in MAPPERS:
        raise DecisionRefused(f"a {persona} may not map a project to the hub; a developer or IT does")
    hub_project = hub_project.strip()
    if hub_project and not HUB_ID.match(hub_project):
        raise ValueError("a hub project id is owner/name, such as acme/checkout or local/my-repo")
    before = current(project)
    if not hub_project:
        if before is None:
            return None
        project.write(FILE, {"hub_project": None, "unmapped_by": person, "at": project.factory.clock.stamp()})
        project.log("agentobs_unmapped", {"hub_project": before["hub_project"], "person": person, "persona": persona,
                                          "reason": reason.strip()[:300]})
        return None
    came_from = next((c["from"] for c in candidates(project) if c["id"] == hub_project), None)
    doc = {"hub_project": hub_project, "how": "suggested" if how == "suggested" else "chosen", "from": came_from,
           "by": person, "persona": persona, "at": project.factory.clock.stamp(), "reason": reason.strip()[:300]}
    project.write(FILE, doc)
    project.log("agentobs_mapped", {k: doc[k] for k in ("hub_project", "how", "from", "reason")}
                | {"person": person, "persona": persona, "previous": before["hub_project"] if before else None})
    return doc


def _names(repo: dict[str, Any]) -> tuple[set[str], str]:
    """The file names to look among, and what they were read from."""
    wanted = [n for names in HOOK_FILES.values() for n in names] + [CATALOG]
    if repo["folder"] is not None:
        return {n for n in wanted if (repo["folder"] / n).exists()}, f"the folder {repo['folder']}"
    if repo["git"] is not None and Path(repo["git"]).is_dir():
        listed = set(_git(repo["git"], "ls-tree", "-r", "--name-only", "main").splitlines())
        return {n for n in wanted if n in listed}, "main of the product repository"
    return set(), "nothing: no repository"


def instrumentation(project: Any) -> dict[str, Any]:
    """Whether the repository carries the hub's hooks, by file names only, and the hub's commands for a person to
    run in their own shell (Rihmasto installs nothing)."""
    repo = repository(project)
    names, read_from = _names(repo)
    harnesses = [h for h, files in HOOK_FILES.items() if names & set(files)]
    folder = str(repo["folder"]) if repo["folder"] is not None else "<your clone of the repository>"
    return {"applies": repo["kind"] in ("adopted", "attached"), "instrumented": bool(harnesses),
            "harnesses": harnesses, "files": sorted(names), "catalog": CATALOG in names, "read_from": read_from,
            "by": "file names only: nothing is opened or run", "commands": commands(folder)}


def commands(folder: str) -> list[dict[str, str]]:
    """The hub's own commands, run by a person in the hub's checkout: preview, install, confirm."""
    q = f'"{folder}"' if " " in folder else folder
    return [{"label": "Preview what it would add", "command": f"npm run cockpit -- install --project {q} --dry-run"},
            {"label": "Install the hooks", "command": f"npm run cockpit -- install --project {q}"},
            {"label": "Confirm, after restarting the IDE or agent",
             "command": f"npm run cockpit -- doctor --project {q}"}]


def record_found(project: Any) -> None:
    """At adoption or attaching: note in the ledger that the repository carries the hub's hooks (names only)."""
    found = instrumentation(project)
    if found["instrumented"]:
        project.log("agentobs_instrumentation_seen", {"harnesses": found["harnesses"], "files": found["files"],
                                                      "by": found["by"]})
