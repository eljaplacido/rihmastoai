"""The cockpit's routes for Gnomon's audits, benchmarks and evals and for Rihma's role evals (FR-EVL1).

- ``GET /api/evals``: every project's latest audit results, the catalogue and what Gnomon this machine has;
- ``GET /api/projects/<pid>/evals``: a project's audits with their last result, trend and findings;
- ``POST /api/projects/<pid>/evals/<eval>/run``: a signed request (``eval_requested``), carried out as a job whose
  log streams on the Jobs page (``rihmasto evals carry``), recorded ``eval_ran``;
- ``POST /api/projects/<pid>/evals/findings/<finding>/change``: make a finding a change proposal, signed;
- ``GET /api/evals/roles``: the role eval sets and the latest comparison of models per set (Models setup);
- ``POST /api/evals/roles/run``: a signed request to run them (``role_eval_requested``), carried out as a job.
"""

from __future__ import annotations

from typing import Any

from cockpit.console_routes import PID
from cockpit.shape_routes import _error
from kernel import gnomon_evals_run as gr
from kernel import gnomon_evals_view as gv
from kernel import role_evals as rv

ROUTES = [
    ("GET", r"/api/evals", "get_evals"),
    ("GET", r"/api/evals/roles", "get_role_evals"),
    ("GET", rf"/api/projects/{PID}/evals", "get_project_evals"),
    ("POST", rf"/api/projects/{PID}/evals/(?P<eid>[a-z_]{{2,20}})/run", "post_eval_run"),
    ("POST", rf"/api/projects/{PID}/evals/findings/(?P<fid>F-[0-9a-f]{{10}})/change", "post_eval_finding_change"),
    ("POST", r"/api/evals/roles/run", "post_role_evals_run"),
]
Reply = tuple[int, dict[str, Any]]


class EvalRoutes:
    """Mixed into the cockpit's Api: it has ``factory``, ``server`` and ``_who``."""

    factory: Any
    server: Any

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _eval_project(self, pid: str) -> Any:
        project = self.factory.project(pid)
        if not project.path("project.json").exists():
            raise _error(404, f"no project {pid}")
        return project

    def get_evals(self, **_: object) -> Reply:
        return 200, gv.factory_view(self.factory) | {"roles": rv.view(self.factory)}

    def get_role_evals(self, **_: object) -> Reply:
        return 200, rv.view(self.factory)

    def get_project_evals(self, pid: str, **_: object) -> Reply:
        return 200, gv.project_view(self._eval_project(pid))

    def post_eval_run(self, pid: str, eid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._eval_project(pid)
        person, persona = self._who(body, pid)
        config = body.get("config")
        if config is not None and not isinstance(config, dict):
            raise _error(400, "config is an object of the eval's settings")
        req = gr.request(project, eid, person=person, persona=persona, config=config)
        job = self.server.start_job("eval", project.pid, ["-m", "kernel.cli", "evals", "carry", project.pid,
                                                          req["request"]], {"person": person, "persona": persona})
        return 201, {"request": req, "job": self.server.job_view(job)}

    def post_eval_finding_change(self, pid: str, fid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._eval_project(pid)
        person, persona = self._who(body, pid)
        return 200, gr.make_change(project, fid, person=person, persona=persona)

    def post_role_evals_run(self, body: dict[str, Any], **_: object) -> Reply:
        from kernel.learn import FACTORY_PID

        person, persona = self._who(body, FACTORY_PID)
        models = body.get("models")
        if models is not None and (not isinstance(models, list) or not all(isinstance(m, str) for m in models)):
            raise _error(400, "models is a list: configured, fallback or <model>@<endpoint>")
        req = rv.request(self.factory, person=person, persona=persona, role=body.get("role") or None,
                         models=models or None, for_project=body.get("for_project") or None)
        job = self.server.start_job("role_evals", FACTORY_PID, ["-m", "kernel.cli", "evals", "carry", FACTORY_PID,
                                                                req["request"]], {"person": person, "persona": persona})
        return 201, {"request": req, "job": self.server.job_view(job)}
