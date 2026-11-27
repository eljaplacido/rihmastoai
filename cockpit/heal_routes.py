"""The cockpit's routes for self-healing (FR-HEAL1, D-0024 item 1, docs/guides/self-healing.md).

Reads write nothing: the incidents (factory-wide, or a project's), each with the remedies Rihmasto offers for it;
what Rihmasto learned; the feedback groups and their proposals; the wording people approved, which the page
applies. Writes are signed by a person and persona (with access enforced, one granted where it acts) and recorded:

- reporting an incident ("Something's wrong here", or the page's central error handling: a failed action, a
  broken or empty view, a refused step the person did not expect, a failed job);
- investigating it with a Rihma agent (the assistant's model, outside the write lock: a model can be slow);
- taking a remedy (a learned one's use is counted; running a lost or failed job again starts the same job);
- resolving it (what fixed it is proposed as a remedy), approving or retiring a learned remedy;
- preparing a fix through the gate (outside the write lock) and, on approval, opening its pull request;
- giving feedback ("This is unclear", "This is wrong") and approving or rejecting what it proposes.

The server's own failures (a 500) are opened here too, by ``server_error`` (no person: the server records what it
met), with ``Watcher`` sweeping the ledgers and the jobs while the cockpit runs.
"""

from __future__ import annotations

import threading
import traceback
from typing import Any

from kernel import feedback as kfeedback
from kernel import heal_feed, heal_fix, heal_investigate, heal_wiring, immune
from kernel import incidents as inc

PID = r"(?P<pid>_factory|[a-z0-9][a-z0-9-]{0,80})"
IID = r"(?P<iid>I-\d{4,9})"
ROUTES = [
    ("GET", r"/api/incidents", "get_incidents"),
    ("GET", rf"/api/projects/{PID}/incidents", "get_project_incidents"),
    ("GET", r"/api/feedback", "get_feedback"),
    ("GET", r"/api/wording", "get_wording"),
    ("POST", r"/api/incidents", "post_incident"),
    ("POST", rf"/api/incidents/{IID}/investigate", "post_incident_investigate"),
    ("POST", rf"/api/incidents/{IID}/remedy", "post_incident_remedy"),
    ("POST", rf"/api/incidents/{IID}/resolve", "post_incident_resolve"),
    ("POST", rf"/api/incidents/{IID}/fix", "post_incident_fix"),
    ("POST", r"/api/fixes/(?P<fid>F-\d{4,9})/pr", "post_fix_pr"),
    ("POST", r"/api/remedies/(?P<rid>RM-\d{4,9})/approve", "post_remedy_approve"),
    ("POST", r"/api/remedies/(?P<rid>RM-\d{4,9})/retire", "post_remedy_retire"),
    ("POST", r"/api/feedback", "post_feedback"),
    ("POST", r"/api/feedback/(?P<fpid>FP-\d{4,9})/settle", "post_feedback_settle"),
]
# An investigation asks a model and a fix runs suites: outside the write lock (their records keep their own locks).
UNLOCKED = {"post_incident_investigate", "post_incident_fix"}
REPORTED = ("report", "action_failed", "view_broken", "view_empty", "refused", "job_failed", "product_not_running",
            "confidential_refused", "scan_degraded")
Reply = tuple[int, dict[str, Any]]


def _server() -> Any:
    from cockpit import server

    return server


def _error(status: int, message: str) -> Exception:
    return _server().ApiError(status, message)


def _text(body: dict[str, Any], key: str, *, required: bool = False, limit: int = 2000) -> str:
    return str(_server()._text(body, key, required=required, limit=limit))


def view_of(factory: Any, doc: dict[str, Any]) -> dict[str, Any]:
    """An incident as the page shows it, with what Rihmasto offers for it and its fixes."""
    return inc.public(doc) | {"offer": immune.offered(factory, doc),
                              "fixes": [{k: f.get(k) for k in ("id", "state", "branch", "gate", "pr", "target")}
                                        for f in heal_fix.fixes(factory, incident=doc["id"])]}


def server_error(server: Any, exc: BaseException, *, method: str, path: str, route: str, match: dict[str, Any],
                 query: dict[str, Any], body: dict[str, Any]) -> dict[str, Any] | None:
    """Open the incident for a 500 and say what is offered; applies (and records) an approved safe remedy."""
    factory = server.factory
    pid = match.get("pid")
    try:
        project = factory.project(pid) if pid and pid != "_factory" else None
    except KeyError:
        project, pid = None, None
    trace = traceback.format_exception(type(exc), exc, exc.__traceback__)
    try:
        doc = inc.open_incident(factory, kind="server_error", where=route, message=str(exc),
                                error_class=type(exc).__name__, project=pid if project else None, context={
                                    "request": inc.request_summary(method, path, route, query, body),
                                    "trace": "".join(trace).splitlines()[-25:], "log": inc.LOG.tail(20),
                                    "records": inc.records_tail(project),
                                    "persona": body.get("persona") or query.get("persona"),
                                    "view": query.get("view")})
        offer = immune.offered(factory, doc)
        if offer["auto"]:
            immune.note_used(factory, offer["auto"]["learned"], incident=doc["id"], person=None, persona=None,
                             auto=True)
    except Exception:  # noqa: BLE001 - recording a failure must never fail the answer about it
        traceback.print_exc()
        return None
    return {"id": doc["id"], "summary": doc["summary"], "offer": offer}


class Watcher:
    """While the cockpit runs: a failed or lost job, and a failure the ledgers recorded, become incidents."""

    def __init__(self, server: Any, *, every: float = 30.0) -> None:
        self.server, self.every = server, every
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="heal-watch", daemon=True)

    def start(self) -> Watcher:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(10)

    def once(self) -> list[str]:
        touched = heal_wiring.sweep(self.server.factory)
        for job in list(self.server.jobs):
            if job.get("kind") != "console" and not job.get("incident"):
                doc = heal_feed.job_incident(self.server.factory, job, self.server.job_view(job))
                if doc:
                    touched.append(doc["id"])
        return touched

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.once()
            except Exception:  # noqa: BLE001 - a bug in one sweep is printed, never the end of the watcher
                traceback.print_exc()
            self._stop.wait(self.every)


class HealRoutes:
    """Mixed into the cockpit's Api: it has ``server``, ``factory``, ``_who`` and ``_project``."""

    server: Any
    factory: Any

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _heal_signer(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:
        person, persona = self._who(body, pid or "_factory")
        _server()._require_person(person, persona)
        return person, persona

    def _incident(self, iid: str) -> dict[str, Any]:
        try:
            return inc.get(self.factory, iid)
        except KeyError:
            raise _error(404, f"no incident {iid}") from None

    def _reply(self, pid: str | None, query: dict[str, Any]) -> Reply:
        rows = inc.incidents(self.factory, pid=pid, state=query.get("state") or None)
        return 200, {"project": pid, "incidents": [view_of(self.factory, d) for d in rows],
                     "counts": inc.counts(inc.incidents(self.factory, pid=pid)), "states": list(inc.STATES),
                     "learned": immune.learned_list(self.factory, pid=pid)}

    # reads

    def get_incidents(self, query: dict[str, Any], **_: object) -> Reply:
        return self._reply(query.get("project") or None, query)

    def get_project_incidents(self, pid: str, query: dict[str, Any], **_: object) -> Reply:
        self._project(pid)
        return self._reply(pid, query)

    def get_feedback(self, **_: object) -> Reply:
        doc = kfeedback.read(self.factory)
        return 200, {"groups": kfeedback.groups(self.factory), "proposals": list(reversed(doc["proposals"])),
                     "applied": {c: kfeedback.applied(self.factory, c) for c in kfeedback.CHANGES},
                     "kinds": list(kfeedback.KINDS)}

    def get_wording(self, **_: object) -> Reply:
        return 200, {"changes": kfeedback.applied(self.factory, "wording")}

    # writes

    def post_incident(self, body: dict[str, Any], **_: object) -> Reply:
        pid = _text(body, "project", limit=100) or None
        person, persona = self._heal_signer(body, pid)
        kind = _text(body, "kind", limit=32) or "report"
        if kind not in REPORTED:
            raise _error(400, f"a reported incident's kind is one of {', '.join(REPORTED)}")
        ctx = body.get("context") if isinstance(body.get("context"), dict) else {}
        ctx = {k: ctx[k] for k in ("view", "route", "browser", "status", "api", "control") if k in ctx}
        job = self._job_of(_text(body, "job", limit=40))
        if job is not None:
            view = self.server.job_view(job)
            ctx["job"] = {"id": job["id"], "kind": job["kind"], "state": view["state"], "code": view.get("code"),
                          "args": job.get("args"), "log_tail": view.get("log_tail", [])[-15:]}
            pid = pid or (job["project"] if job["project"] != "_factory" else None)
        try:
            project = self.factory.project(pid) if pid and pid != "_factory" else None
        except KeyError:
            raise _error(404, f"no project {pid}") from None
        ctx |= {"records": inc.records_tail(project), "persona": persona, "log": inc.LOG.tail(10)}
        try:
            doc = inc.open_incident(self.factory, kind=kind, where=_text(body, "where", limit=200) or
                                    str(ctx.get("view") or "the cockpit"), message=_text(body, "message"),
                                    error_class=_text(body, "error_class", limit=80), project=pid, context=ctx,
                                    person=person, persona=persona, by="a person", words=_text(body, "words"))
        except inc.IncidentRefused as exc:
            raise _error(400, str(exc)) from None
        if job is not None:
            job["incident"] = doc["id"]
        return 201, {"incident": view_of(self.factory, doc), "new": doc["new"]}

    def _job_of(self, jid: str) -> dict[str, Any] | None:
        if not jid:
            return None
        found = next((j for j in list(self.server.jobs) if j["id"] == jid), None)
        if found is None:
            raise _error(404, f"no job {jid}")
        return found

    def post_incident_investigate(self, iid: str, body: dict[str, Any], **_: object) -> Reply:
        doc = self._incident(iid)
        person, persona = self._heal_signer(body, doc.get("project"))
        model = getattr(self.server, "assistant_model", None)
        try:
            found = heal_investigate.investigate(self.factory, iid, person=person, persona=persona, model=model)
        except inc.IncidentRefused as exc:
            raise _error(409, str(exc)) from None
        return 200, {"investigation": found, "incident": view_of(self.factory, inc.get(self.factory, iid))}

    def post_incident_remedy(self, iid: str, body: dict[str, Any], **_: object) -> Reply:
        doc = self._incident(iid)
        person, persona = self._heal_signer(body, doc.get("project"))
        rid = _text(body, "remedy", required=True, limit=64)
        action = next((a for a in immune.offered(self.factory, doc)["remedies"] if a["id"] == rid), None)
        if action is None:
            raise _error(400, f"{rid} is not a remedy offered for {iid}")
        job = None
        if action["kind"] == "retry_job":
            job = self._run_again(doc, person, persona)
        if action.get("learned"):
            immune.note_used(self.factory, action["learned"], incident=iid, person=person, persona=persona)
        out = inc.update(self.factory, iid, event="incident_remedy_taken", person=person, persona=persona,
                         note=f"{action['label']}" + (f" (job {job['id']})" if job else ""))
        return 200, {"action": action, "job": self.server.job_view(job) if job else None,
                     "incident": view_of(self.factory, out)}

    def _run_again(self, doc: dict[str, Any], person: str, persona: str) -> dict[str, Any]:
        """The same job again, from the request the incident kept: only the kernel's own command line."""
        from kernel import access_isolation as kisolation

        job = (doc.get("context") or {}).get("job") or {}
        args = job.get("args")
        if not isinstance(args, list) or args[:2] != ["-m", "kernel.cli"] or not all(isinstance(a, str) for a in args):
            raise _error(409, "this incident kept no job of the kernel's own to run again: start it where it was")
        if "*" in "".join(args):
            raise _error(409, "the kept request is masked: start it again where it was")
        kisolation.require(self.factory)
        pid = doc.get("project") or "_factory"
        running = self.server.running_job(pid)
        if running is not None:
            raise _error(409, f"job {running['id']} is still running for {pid}")
        return self.server.start_job(str(job.get("kind") or "run"), pid, args, {"person": person, "persona": persona})

    def post_incident_resolve(self, iid: str, body: dict[str, Any], **_: object) -> Reply:
        doc = self._incident(iid)
        person, persona = self._heal_signer(body, doc.get("project"))
        try:
            out = inc.resolve(self.factory, iid, how=body.get("how") if isinstance(body.get("how"), dict) else {},
                              person=person, persona=persona, note=_text(body, "note", limit=500),
                              anyway=body.get("anyway") is True)
        except (inc.IncidentRefused, ValueError) as exc:
            raise _error(409, str(exc)) from None
        return 200, {"incident": view_of(self.factory, out), "remedy": out.get("remedy")}

    def post_incident_fix(self, iid: str, body: dict[str, Any], **_: object) -> Reply:
        doc = self._incident(iid)
        person, persona = self._heal_signer(body, doc.get("project"))
        fix = body.get("fix") if isinstance(body.get("fix"), dict) else None
        target = _text(body, "target", limit=16) or None
        try:
            made = heal_fix.prepare(self.factory, iid, person=person, persona=persona, fix=fix, target=target,
                                    verifier=getattr(self.server, "fix_verifier", None))
        except heal_fix.FixRefused as exc:
            raise _error(409, str(exc)) from None
        return 201, {"fix": made}

    def post_fix_pr(self, fid: str, body: dict[str, Any], **_: object) -> Reply:
        try:
            fix = heal_fix.get(self.factory, fid)
        except KeyError:
            raise _error(404, f"no fix {fid}") from None
        person, persona = self._heal_signer(body, fix.get("project"))
        try:
            out = heal_fix.open_pr(self.factory, fid, person=person, persona=persona,
                                   approve=body.get("approve") is True)
        except heal_fix.FixRefused as exc:
            raise _error(403 if "approv" in str(exc) else 409, str(exc)) from None
        return 200, {"fix": out}

    def post_remedy_approve(self, rid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._heal_signer(body, None)
        try:
            return 200, {"remedy": immune.approve(self.factory, rid, person=person, persona=persona)}
        except KeyError:
            raise _error(404, f"no remedy {rid}") from None

    def post_remedy_retire(self, rid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._heal_signer(body, None)
        try:
            return 200, {"remedy": immune.retire(self.factory, rid, person=person, persona=persona,
                                                 reason=_text(body, "reason", limit=500))}
        except KeyError:
            raise _error(404, f"no remedy {rid}") from None

    def post_feedback(self, body: dict[str, Any], **_: object) -> Reply:
        pid = _text(body, "project", limit=100) or None
        person, persona = self._heal_signer(body, pid)
        where = body.get("where") if isinstance(body.get("where"), dict) else {}
        try:
            item = kfeedback.give(self.factory, kind=_text(body, "kind", limit=16) or "unclear", where=where,
                                  words=_text(body, "words"), suggest=_text(body, "suggest", limit=500),
                                  person=person, persona=persona, project=pid)
        except kfeedback.FeedbackRefused as exc:
            raise _error(400, str(exc)) from None
        except KeyError:
            raise _error(404, f"no project {pid}") from None
        return 201, {"feedback": item}

    def post_feedback_settle(self, fpid: str, body: dict[str, Any], **_: object) -> Reply:
        person, persona = self._heal_signer(body, None)
        try:
            out = kfeedback.settle(self.factory, fpid, verdict=_text(body, "verdict", required=True, limit=16),
                                   person=person, persona=persona, text=_text(body, "text", limit=500))
        except KeyError:
            raise _error(404, f"no proposal {fpid}") from None
        except kfeedback.FeedbackRefused as exc:
            raise _error(403 if "approved by" in str(exc) else 400, str(exc)) from None
        return 200, {"proposal": out}
