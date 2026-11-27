"""The cockpit's routes for automations (kernel/automations.py, FR-AUT1), and the scheduler that runs them.

Every write is signed by a person and persona as the other write routes are: with access enforced, a persona
granted on the project the automation acts on (on the factory for a factory-wide one), and the kernel checks
every scoped project again. A preview and a dry run record nothing and run outside the write lock.

The **scheduler** is a thread in the cockpit's process: it runs one tick (kernel/automations_run.py) a minute
while the cockpit runs, and at once when a person presses Run now. A tick that finds another running (the
system's scheduler running `rihmasto automations tick`) answers busy and changes nothing. The thread is only
started by ``python -m cockpit.server``; a server made in a test starts none unless the test asks.
"""

from __future__ import annotations

import threading
import traceback
from typing import Any

from kernel import access_isolation as kisolation
from kernel import automations as kau
from kernel import automations_cli as kau_cli
from kernel import automations_events as kau_events
from kernel import automations_run as kau_run
from kernel import automations_text as kau_words
from kernel import checks as kchecks
from kernel import gnomon_evals as kge
from kernel import hooks as khooks
from kernel import relay as krelay
from kernel.learn import FACTORY_PID

AID = r"(?P<aid>AU-\d{3,6})"
PID = r"(?P<pid>" + FACTORY_PID + r"|[a-z0-9][a-z0-9-]{0,80})"   # cockpit/server.py PID, the same pattern
ROUTES = [
    ("GET", r"/api/automations", "get_automations"),
    ("GET", rf"/api/projects/{PID}/automations", "get_project_automations"),
    ("POST", r"/api/automations", "post_automation"),
    ("POST", r"/api/automations/preview", "post_automation_preview"),
    ("PUT", rf"/api/automations/{AID}", "put_automation"),
    ("POST", rf"/api/automations/{AID}/pause", "post_automation_pause"),
    ("POST", rf"/api/automations/{AID}/resume", "post_automation_resume"),
    ("POST", rf"/api/automations/{AID}/remove", "post_automation_remove"),
    ("POST", rf"/api/automations/{AID}/run", "post_automation_run"),
    ("POST", rf"/api/automations/{AID}/dry-run", "post_automation_dry_run"),
    ("PUT", rf"/api/projects/{PID}/tags", "put_project_tags"),
]
# A preview and a dry run record nothing: they run outside the write lock.
UNLOCKED = {"post_automation_preview", "post_automation_dry_run"}
Reply = tuple[int, dict[str, Any]]
TICK_EVERY = 60.0


def _server() -> Any:
    from cockpit import server

    return server


def _error(status: int, message: str) -> Exception:
    return _server().ApiError(status, message)


class Scheduler:
    """One tick a minute in a background thread, and one at once when woken."""

    def __init__(self, factory: Any, *, every: float = TICK_EVERY, model: Any = None) -> None:
        self.factory, self.every, self.model = factory, float(every), model
        self.last: dict[str, Any] | None = None
        self._wake, self._stop = threading.Event(), threading.Event()
        self._thread = threading.Thread(target=self._loop, name="automations", daemon=True)

    def start(self) -> Scheduler:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(10)

    def wake(self) -> None:
        self._wake.set()

    def running(self) -> bool:
        return self._thread.is_alive()

    def tick_once(self) -> dict[str, Any]:
        with kisolation.serving(self.factory):
            out = kau_run.tick(self.factory, kau_run.Tools(model=self.model))
        self.last = {"at": self.factory.clock.stamp(), "automations": out.get("automations"), "busy": out.get("busy")}
        return out

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick_once()
            except Exception:  # a bug in one tick is printed, never the end of the scheduler
                traceback.print_exc()
            self._wake.wait(self.every)
            self._wake.clear()


class AutomationRoutes:
    """Mixed into the cockpit's Api: it has ``server``, ``factory`` and ``_who``."""

    server: Any
    factory: Any

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _auto_signer(self, body: dict[str, Any], spec: dict[str, Any] | None = None) -> tuple[str, str]:
        """Signed where it acts: on the first project it names, else on the factory."""
        scope = (spec or {}).get("scope") or {}
        pids = scope.get("projects") if isinstance(scope, dict) else None
        pid = pids[0] if isinstance(pids, list) and pids and isinstance(pids[0], str) else FACTORY_PID
        person, persona = self._who(body, pid)
        _server()._require_person(person, persona)
        return person, persona

    def _auto(self, aid: str) -> dict[str, Any]:
        try:
            return kau.get(self.factory, aid)
        except KeyError:
            raise _error(404, f"no automation {aid}") from None

    @staticmethod
    def _draft(body: dict[str, Any]) -> dict[str, Any]:
        spec = body.get("automation")
        if not isinstance(spec, dict):
            raise _error(400, "automation is an object: name, trigger, guard, action, scope, limits, notify")
        return spec

    def _view(self, a: dict[str, Any]) -> dict[str, Any]:
        return kau_cli.view(a, self.factory) | {"history": kau_run.history(self.factory, a["id"], limit=10)}

    # reads

    def get_automations(self, query: dict[str, Any], **_: object) -> Reply:
        """Every automation (or those of a state or a project), with what the builder offers."""
        project = query.get("project") or None
        state = query.get("state") if query.get("state") in ("active", "paused") else None
        try:
            rows = kau_cli.listing(self.factory, project, state)
        except KeyError:
            raise _error(404, f"no project {project}") from None
        sched = getattr(self.server, "automation_scheduler", None)
        removed = [{"id": a["id"], "name": a.get("name"), "by": a.get("removed_by"), "at": a.get("removed_at")}
                   for a in kau.automations(self.factory, removed=True) if a.get("state") == "removed"][-10:]
        return 200, {"automations": [r | {"history": kau_run.history(self.factory, r["id"], limit=10)} for r in rows],
                     "removed": removed[::-1],      # who removed which, kept in sight (FR-NVL3)
                     **self._offers(), "scheduler": {"running": bool(sched and sched.running()),
                                                     "last": sched.last if sched else None}}

    def _templates(self) -> list[dict[str, Any]]:
        """Each template with what it waits for before it can be set up (a relay subscription IT adds) and who may
        set it up, so one that cannot work yet is marked before it is opened (FR-NVL3)."""
        subs = krelay.subscriptions(self.factory)
        out = []
        for t in kau_words.TEMPLATES:
            kind = ((t.get("draft") or {}).get("action") or {}).get("kind")
            waits = ["needs IT: a relay subscription"] if "subscription" in (t.get("needs") or []) and not subs else []
            out.append(t | {"waits": waits, "personas": list((kau.ACTIONS.get(kind) or {}).get("personas") or [])})
        return out

    def _offers(self) -> dict[str, Any]:
        return {"templates": self._templates(), "events": list(kau_events.COMMON_EVENTS), "triggers": list(kau.TRIGGERS),
                "guards": list(kau.GUARDS), "scopes": list(kau.SCOPES),
                "actions": [{"id": k, "label": v["label"], "personas": list(v["personas"]),
                             "per_project": v["per_project"]} for k, v in kau.ACTIONS.items()],
                # what run_eval and run_check name: the builder chooses one, its sentence says which
                "evals": [{"id": e.id, "label": e.label} for e in kge.CATALOGUE],
                "checks": [{"id": c["kind"], "label": c["label"]} for c in kchecks.public()],
                "subscriptions": [{"id": s["id"], "sink": s["sink"], "projects": s.get("projects") or []}
                                  for s in krelay.subscriptions(self.factory)],
                "sources": [{"id": s["id"], "scheme": s["scheme"], "projects": s.get("projects") or []}
                            for s in khooks.sources(self.factory) if s["state"] == "active"],
                "projects": [{"id": p.pid, "title": p.meta.get("title"), "tags": p.meta.get("tags") or [],
                              "profile": p.meta.get("profile"), "source": p.meta.get("source_kind")}
                             for p in self.factory.projects() if not p.pid.startswith("_")]}

    def get_project_automations(self, pid: str, **_: object) -> Reply:
        if pid == FACTORY_PID:
            return 200, {"automations": [], "history": [], "tags": []}
        try:
            project = self.factory.project(pid)
        except KeyError:
            raise _error(404, f"no project {pid}") from None
        rows = kau_cli.listing(self.factory, pid)
        return 200, {"automations": rows, "history": kau_run.history(self.factory, project=pid, limit=30),
                     "tags": project.meta.get("tags") or []}

    # writes

    def post_automation(self, body: dict[str, Any], **_: object) -> Reply:
        spec = self._draft(body)
        person, persona = self._auto_signer(body, spec)
        return 201, {"automation": self._view(kau.add(self.factory, spec, person=person, persona=persona))}

    def post_automation_preview(self, body: dict[str, Any], **_: object) -> Reply:
        """The plain-language summary of a draft, and the projects it would reach now; records nothing."""
        spec = self._draft(body)
        self._auto_signer(body, spec)
        try:
            checked = kau._checked(self.factory, spec)
        except (ValueError, KeyError) as exc:
            return 200, {"ok": False, "why": str(exc.args[0] if isinstance(exc, KeyError) else exc)}
        return 200, {"ok": True, "summary": kau_words.describe(checked),
                     "projects": [p.pid for p in kau.projects_in(self.factory, checked["scope"])]}

    def put_automation(self, aid: str, body: dict[str, Any], **_: object) -> Reply:
        current = self._auto(aid)
        spec = self._draft(body)
        person, persona = self._auto_signer(body, {**current, **spec})
        return 200, {"automation": self._view(kau.edit(self.factory, aid, spec, person=person, persona=persona))}

    def post_automation_pause(self, aid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._auto_signer(body, self._auto(aid))
        reason = _server()._text(body, "reason", limit=500)
        return 200, {"automation": self._view(kau.pause(self.factory, aid, person=person, persona=persona,
                                                        reason=reason))}

    def post_automation_resume(self, aid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._auto_signer(body, self._auto(aid))
        return 200, {"automation": self._view(kau.resume(self.factory, aid, person=person, persona=persona))}

    def post_automation_remove(self, aid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._auto_signer(body, self._auto(aid))
        return 200, {"automation": kau.remove(self.factory, aid, person=person, persona=persona)}

    def post_automation_run(self, aid: str, body: dict[str, Any], **_: object) -> Reply:
        """Run now: recorded at once, carried out by the scheduler's next tick, which this wakes."""
        auto = self._auto(aid)
        person, persona = self._auto_signer(body, auto)
        project = _server()._text(body, "project", limit=100) or None
        per_project = (kau.ACTIONS.get(auto["action"]["kind"]) or {}).get("per_project")
        if per_project and project is None and not kau.projects_in(self.factory, auto["scope"]):
            return 200, {"requested": None, "ran": False, "projects_now": [],      # never "runs now" for nothing
                         "why": f"No project matches {aid}'s scope now, so nothing ran: Edit its scope, or tag a "
                                "project so it matches."}
        req = kau_run.request_run(self.factory, aid, person=person, persona=persona, project=project)
        sched = getattr(self.server, "automation_scheduler", None)
        if sched is not None:
            sched.wake()
        return 200, {"requested": req, "scheduler": bool(sched and sched.running())}

    def post_automation_dry_run(self, aid: str, body: dict[str, Any], **_: object) -> Reply:
        self._auto_signer(body, self._auto(aid))
        return 200, {"dry_run": kau_run.dry_run(self.factory, aid)}

    def put_project_tags(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        try:
            project = self.factory.project(pid)
        except KeyError:
            raise _error(404, f"no project {pid}") from None
        person, persona = self._who(body, pid)
        tags = body.get("tags")
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise _error(400, "tags is a list of words")
        return 200, {"tags": kau.set_tags(project, tags, person=person, persona=persona)}
