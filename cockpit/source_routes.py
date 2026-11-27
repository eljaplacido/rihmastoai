"""The cockpit's routes for feeding in real projects (FR-RPJ1; docs/guides/inputs.md, docs/brownfield.md).

- **A scan that shows its progress.** ``POST /api/source/scan`` starts the scan of a folder in the background
  and answers at once; ``GET /api/source/scan/<id>`` says how far it is (files looked at, the folder, the time)
  and, when done, the map with what the dialog needs: a git repository's uncommitted work (the preview scans
  exactly what will be adopted: the last commit, or the working copy), the repositories of a workspace and
  their copies, the projects that already adopted it, how it seems to be used, and what a confidential
  adoption means. ``POST /api/source/scan/<id>/cancel`` stops it. A refusal is the scan's state, with what
  the person can do about it ("Allow C:\\dev", or "Ask IT to allow it"), never a stuck "Scanning".
- **Folders the cockpit may read.** ``GET /api/source/roots``; ``POST /api/source/roots`` allows one (IT under
  enforced access, a single operator after saying yes), ``POST /api/source/roots/remove`` takes one back.
- **A local model for a confidential project's roles.** ``POST /api/models/use-local`` (kernel/confidential_local.py).

Scanning records nothing; allowing a folder and pointing roles at a local model are signed and recorded.
"""

from __future__ import annotations

import secrets
import threading
from pathlib import Path
from typing import Any

from kernel import confidential as kconfidential
from kernel import confidential_local as klocal
from kernel import material as kmaterial
from kernel import material_git as kgit
from kernel import progress_jobs
from kernel import source_guard as ksource
from kernel.adopt_seen import adopted_as, workspace_seen
from kernel.learn import FACTORY_PID

SID = r"(?P<sid>S-[0-9a-f]{12})"
ROUTES = [
    ("POST", r"/api/source/scan", "post_source_scan"),
    ("GET", rf"/api/source/scan/{SID}", "get_source_scan"),
    ("POST", rf"/api/source/scan/{SID}/cancel", "post_source_scan_cancel"),
    ("GET", r"/api/source/roots", "get_source_roots"),
    ("POST", r"/api/source/roots", "post_source_root"),
    ("POST", r"/api/source/roots/remove", "post_source_root_remove"),
    ("POST", r"/api/models/use-local", "post_models_use_local"),
]
UNLOCKED = {"post_source_scan", "post_source_scan_cancel"}
KEEP = 24
Reply = tuple[int, dict[str, Any]]


def _server() -> Any:
    from cockpit import server

    return server


def guess_usage(mp: dict[str, Any], commits: int) -> dict[str, str]:
    """How the project seems to be used today, by rule from its files and history: a guess a person confirms."""
    inv = mp.get("inventory") or {}
    names = " ".join(r["path"].lower() for r in mp["files"])
    ci, docker, tests = bool(inv.get("ci")), bool(inv.get("dockerfiles")), bool(inv.get("tests"))
    deploy = any(w in names for w in ("deploy", "helm", "terraform", "k8s", "kubernetes", "fly.toml", "render.yaml"))
    if not kmaterial.has_code(mp):
        return {"maturity": "explore", "why": "documents only: an experiment or a report"}
    if ci and (docker or deploy) and commits >= 50:
        return {"maturity": "production", "why": f"CI, deployment files and {commits} commits"}
    if ci and tests:
        return {"maturity": "pilot", "why": "tests and CI, but no sign of a deployment"}
    if tests or commits >= 20:
        return {"maturity": "demo", "why": f"{'tests' if tests else str(commits) + ' commits'} but no CI"}
    return {"maturity": "explore", "why": f"{commits} commit(s), no tests and no CI"}


class SourceRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``server``, ``access`` and ``_sign``."""

    factory: Any
    server: Any
    access: Any

    def _sign(self, person: str, persona: str, pid: str | None) -> tuple[str, str]:  # pragma: no cover
        raise NotImplementedError

    # -- the scan, in the background --------------------------------------------------------------------

    def _scans(self) -> dict[str, dict[str, Any]]:
        if not hasattr(self.server, "_rpj_scans"):
            self.server._rpj_scans = {}
            self.server._rpj_lock = threading.Lock()
        return self.server._rpj_scans

    def _refused(self, text: str, why: str) -> Reply:
        try:
            offer = ksource.offer(text, enforced=self.access.enforced, home=self.factory.home) if text else None
        except (OSError, ValueError):
            offer = None
        return 200, {"scan": {"state": "refused", "error": why, "offer": offer, "progress": None}}

    def post_source_scan(self, body: dict[str, Any], **_: object) -> Reply:
        srv = _server()
        text = srv._text(body, "source", required=True, limit=2000)
        person, persona = self._sign(srv._text(body, "person", limit=200), srv._text(body, "persona", limit=64),
                                     FACTORY_PID)          # who asks is checked first, as for every write
        srv._require_person(person, persona)
        try:
            path = ksource.check_folder(text, persona, self.factory.home)
        except ksource.SourceRefused as exc:
            return self._refused(text, str(exc))
        except ValueError as exc:
            return self._refused("", str(exc))
        exclude = self._excludes(body)        # type: ignore[attr-defined]
        take = "working_copy" if body.get("take") == "working_copy" else "commit"
        sid = f"S-{secrets.token_hex(6)}"
        job: dict[str, Any] = {"id": sid, "state": "running", "progress": kmaterial.Progress(), "folder": str(path)}
        scans = self._scans()
        with self.server._rpj_lock:
            for old in list(scans)[:-KEEP]:
                scans.pop(old, None)
            scans[sid] = job
        threading.Thread(target=self._run_scan, args=(job, path, exclude, take), daemon=True).start()
        return 202, {"scan": self._scan_view(job)}

    def _run_scan(self, job: dict[str, Any], path: Path, exclude: list[str], take: str) -> None:
        try:
            job["result"] = self._scan_result(path, exclude, take, job["progress"])
            job["state"] = "done"
        except kmaterial.ScanCancelled:
            job["state"] = "cancelled"
        except Exception as exc:  # noqa: BLE001 - the step shows the error instead of a scan that never ends
            job["state"], job["error"] = "failed", f"the scan stopped: {type(exc).__name__}: {exc}"[:500]

    def _scan_result(self, path: Path, exclude: list[str], take: str, progress: kmaterial.Progress) -> dict[str, Any]:
        root = kgit.is_repo_root(path)
        git = root or kgit.git(path, "rev-parse", "--git-dir") is not None
        head = kgit.head(path) if root else None
        changes = kgit.working_changes(path) if root else {"uncommitted": 0, "untracked": 0}
        # The last commit, or the working copy as git sees it (what .gitignore keeps out is never taken).
        tree = kgit.GitTree(path) if head and take == "commit" else kgit.WorkTree(path) if root else None
        mp = kmaterial.preview(path, exclude, tree=tree, progress=progress)
        commits = kgit.git(path, "rev-list", "--count", "HEAD") if head else None
        origin = kgit.origin(path) if root else None
        ws = None if git else kgit.workspace(path)
        workspace_seen(self.factory, ws)            # each repository adopted already says so (FR-RPJ1)
        code = kmaterial.has_code(mp)
        return {"map": mp, "git": git, "code": code, "head": head, "take": "commit" if head and take == "commit"
                else "working_copy" if root and head else "folder", "changes": changes, "origin": origin, "workspace": ws,
                "adopted_as": adopted_as(self.factory, path, origin),
                "usage": guess_usage(mp, int(commits) if commits and commits.strip().isdigit() else 0),
                "send_to": kconfidential.send_to("analyst"),
                "local_only": {"new": kconfidential.refusal(["analyst"]) or None,
                               "all": kconfidential.refusal(kconfidential.ROLES) or None},
                "confidential": klocal.notice()}

    @staticmethod
    def _scan_view(job: dict[str, Any]) -> dict[str, Any]:
        out = {k: job.get(k) for k in ("id", "state", "error", "folder")}
        out["progress"] = job["progress"].view()
        out["live"] = progress_jobs.scan(out["progress"], job["state"], job.get("error") or "")   # FR-PRG1
        if job["state"] == "done":
            out["result"] = job["result"]
        return out

    def _scan_job(self, sid: str) -> dict[str, Any]:
        job = self._scans().get(sid)
        if job is None:
            raise _server().ApiError(404, f"no scan {sid}: it finished long ago, or the cockpit restarted")
        return job

    def get_source_scan(self, sid: str, **_: object) -> Reply:
        return 200, {"scan": self._scan_view(self._scan_job(sid))}

    def post_source_scan_cancel(self, sid: str, body: dict[str, Any], **_: object) -> Reply:
        srv = _server()
        srv._require_person(*self._sign(srv._text(body, "person", limit=200), srv._text(body, "persona", limit=64),
                                        FACTORY_PID))
        job = self._scan_job(sid)
        job["progress"].cancelled = True
        return 200, {"scan": self._scan_view(job)}

    # -- adopting: the working copy, documents, adopted already (cockpit/server.py post_adopt) --------------

    @staticmethod
    def _adopt_take(body: dict[str, Any]) -> list[str]:
        return [*(["--working-copy"] if body.get("take") == "working_copy" else []),
                *(["--documents"] if body.get("documents") is True else [])]

    def _adopt_again(self, body: dict[str, Any], kind: str, location: str) -> None:
        if body.get("again") is True:
            return
        origin = location if kind == "url" else kgit.origin(Path(location)) if kind == "path" else None
        seen = adopted_as(self.factory, None if kind == "url" else location, origin)
        if seen:
            raise _server().ApiError(409, f"already adopted as {seen[0]['title']} ({seen[0]['project']}, the same "
                                          f"{seen[0]['by']}): open it, or adopt it again as a new project")

    # -- folders the cockpit may read ---------------------------------------------------------------------

    def get_source_roots(self, **_: object) -> Reply:
        import os

        env = [p for p in os.environ.get(ksource.ROOTS_ENV, "").split(os.pathsep) if p.strip()]
        rows = [{"path": str(Path.home()), "from": "your home folder"}]
        rows += [{"path": p, "from": ksource.ROOTS_ENV} for p in env]
        rows += [{"path": r["path"], "from": "allowed in Settings", "by": r.get("by"), "persona": r.get("persona")}
                 for r in ksource.allowed(self.factory.home)]
        return 200, {"roots": rows, "enforced": bool(self.access.enforced),
                     "who": "IT" if self.access.enforced else "you, after saying yes"}

    def _root_change(self, body: dict[str, Any], remove: bool) -> Reply:
        srv = _server()
        person, persona = self._sign(srv._text(body, "person", limit=200), srv._text(body, "persona", limit=64),
                                     FACTORY_PID)
        folder = srv._text(body, "folder", required=True, limit=2000)
        from kernel.learn import factory_project

        log = factory_project(self.factory).log      # the factory's ledger: who allowed which folder, when
        try:
            if remove:
                ksource.disallow(self.factory.home, folder, person=person, persona=persona,
                                 enforced=bool(self.access.enforced), log=log)
            else:
                ksource.allow(self.factory.home, folder, person=person, persona=persona,
                              enforced=bool(self.access.enforced), confirmed=body.get("confirm") is True, log=log)
        except ksource.SourceRefused as exc:
            raise srv.ApiError(403, str(exc)) from None
        except ValueError as exc:
            raise srv.ApiError(400, str(exc)) from None
        return 200, self.get_source_roots()[1]

    def post_source_root(self, body: dict[str, Any], **_: object) -> Reply:
        return self._root_change(body, remove=False)

    def post_source_root_remove(self, body: dict[str, Any], **_: object) -> Reply:
        return self._root_change(body, remove=True)

    def post_models_use_local(self, body: dict[str, Any], **_: object) -> Reply:
        srv = _server()
        person, persona = self._sign(srv._text(body, "person", limit=200), srv._text(body, "persona", limit=64),
                                     FACTORY_PID)
        roles = body.get("roles") if isinstance(body.get("roles"), list) else None
        from kernel.models_setup import ModelsRefused

        try:
            out = klocal.use_local(self.factory, person=person, persona=persona,
                                   roles=[str(r)[:40] for r in roles] if roles else None)
        except ModelsRefused as exc:
            raise srv.ApiError(400, str(exc)) from None
        return 200, {"used": out, "confidential": klocal.notice()}
