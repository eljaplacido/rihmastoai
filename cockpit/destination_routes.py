"""The cockpit's routes for a project's destinations and publishing (kernel/destinations.py, kernel/publish.py,
FR-DST1).

Reads: the whole map, and the short "Where this goes" for the overview. Writes, each signed by a person and
persona (with access enforced, granted on the project) and recorded by the kernel:

- Deliver to test and Promote to production: recorded (`destination_delivery_requested`), then `rihmasto deliver`
  runs as a job, as Advance runs `rihmasto run`; production stops at IT's deploy gate as always;
- Check now: one feedback round (kernel/destinations_feedback.py), outside the write lock, since it probes;
- Publish: kernel/publish.py, outside the write lock, since a push takes time. A registry that is not ready
  answers 200 with ``state: refused`` and exactly what is missing: the refusal is recorded with who asked.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import destinations, destinations_feedback, publish, registries
from kernel.destinations_cli import request_delivery
from kernel.learn import FACTORY_PID

PID = r"(?P<pid>" + re.escape(FACTORY_PID) + r"|[a-z0-9][a-z0-9-]{0,80})"   # as cockpit/server.py PID
ROUTES = [
    ("GET", rf"/api/projects/{PID}/destinations", "get_destinations"),
    ("GET", rf"/api/projects/{PID}/destinations/where", "get_destinations_where"),
    ("POST", rf"/api/projects/{PID}/destinations/deliver", "post_destinations_deliver"),
    ("POST", rf"/api/projects/{PID}/destinations/check", "post_destinations_check"),
    ("POST", rf"/api/projects/{PID}/publish", "post_publish"),
]
UNLOCKED = {"post_destinations_check", "post_publish"}
Reply = tuple[int, dict[str, Any]]


def _error(status: int, message: str) -> Exception:
    from cockpit import server

    return server.ApiError(status, message)


class DestinationRoutes:
    """Mixed into the cockpit's Api: it has ``server``, ``factory`` and ``_who``."""

    factory: Any
    server: Any

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _dest_project(self, pid: str) -> Any:
        try:
            return self.factory.project(pid)
        except KeyError:
            raise _error(404, f"no project {pid}") from None

    def get_destinations(self, pid: str, **_: object) -> Reply:
        project = self._dest_project(pid)
        view = destinations.view(project)
        view["registries"] = registries.all_public(self.factory)
        view["publishes"] = publish.history(project)[-20:]
        return 200, view

    def get_destinations_where(self, pid: str, **_: object) -> Reply:
        return 200, destinations.where(self._dest_project(pid))

    def post_destinations_deliver(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._dest_project(pid)
        person, persona = self._who(body, pid)
        running = self.server.running_job(pid)
        if running is not None:
            raise _error(409, f"job {running['id']} is still running for {pid}")
        record = request_delivery(project, to=str(body.get("to") or "test"), person=person, persona=persona)
        job = self.server.start_job("deliver", project.pid, ["-m", "kernel.cli", "deliver", project.pid],
                                    {"person": person, "persona": persona})
        return 201, {"requested": record, "job": self.server.job_view(job)}

    def post_destinations_check(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._dest_project(pid)
        person, persona = self._who(body, pid)
        out = destinations_feedback.check(project, person=person, persona=persona, via="cockpit")
        keep = ("at", "probes", "changes", "failing", "summary", "said", "tone")
        return 200, {k: out[k] for k in keep} | {"view": out["view"]}

    def post_publish(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._dest_project(pid)
        person, persona = self._who(body, pid)
        registry = str(body.get("registry") or "").strip()
        if not registry:
            raise _error(400, "registry names the registry to publish to")
        release = body.get("release")
        if release is not None and (isinstance(release, bool) or not isinstance(release, int)):
            raise _error(400, "release is a release number")
        try:
            out = publish.publish(project, to=registry, person=person, persona=persona, release=release)
        except publish.PublishRefused as exc:
            return 200, {"state": "refused", "registry": registry, "why": str(exc), "missing": exc.missing}
        return 200, out
