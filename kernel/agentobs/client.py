"""A read-only client for the agent observability hub's HTTP API (FR-OBS1).

The contract Rihmasto relies on, as the hub documents and serves it (its `/v1` API reference); every route here
is a GET, and nothing Rihmasto sends could write:

==============================================  ================================================================
``GET /health``                                 ``{ok, service, chain_attests}``: ``persisted`` (a database whose
                                                chain the application cannot rewrite) or ``derived-on-load`` (a
                                                file ledger whose chain is rebuilt at boot)
``GET /v1/projects``                            ``{projects: [{project_id, repository_id, title, last_event_at,
                                                last_harness, event_count, ...}]}``
``GET /v1/projects/{id}``                       ``{project}``; 404 ``{"error": "project not found"}``
``GET /v1/projects/{id}/sessions``              ``{sessions: [{session_id, harness_name, started_at, ended_at,
                                                duration_ms, status, had_failure, files, tools, steps (the most
                                                recent 200), step_count, ...}]}``
``GET /v1/projects/{id}/metrics``               ``{metrics: {completed_sessions, failed_sessions, tool_events,
                                                tool_failures, ...}}``, every rate null when its base is empty
``GET /v1/projects/{id}/intelligence``          ``{intelligence: {governance, trajectory, quality, context, ...}}``
``GET /v1/projects/{id}/insight``               ``{insight: {rework: {threshold, files, ...}, harness_activity}}``
``GET /v1/projects/{id}/chain``                 ``{verification: {valid, checked, reachable, breaks}}``: 200 when
                                                intact, 409 when broken, 404 for no such project, 503 when the
                                                history is too long to verify in one pass
==============================================  ================================================================

A project id holds a slash (``owner/repo``) and is percent-encoded once in the path. The hub's reads need no token
by default (its token guards writes); when IT names one, it is sent as a bearer token, read from the environment
at the moment of the request and never kept, logged or shown. Redirects are never followed; a loopback or private
hub is reached without a proxy; an answer is at most 32 MB of JSON.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from kernel.agentobs import settings, where
from kernel.graph_records import object_of

MAX_BYTES = 32 * 1024 * 1024
TIMEOUT = 5.0
# The statuses a route answers with a JSON body Rihmasto reads (the chain answers 409 when broken).
READABLE = {"chain": (200, 404, 409, 503), "project": (200, 404)}


class HubUnreachable(RuntimeError):
    """The hub did not answer: not running, the wrong address, a network in the way."""


class HubError(RuntimeError):
    """The hub answered, but not with what the contract says."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None          # a redirect is an answer, never followed


class Hub:
    """One hub, by its base address. ``opener`` is for a test; by default urllib's, as said above."""

    def __init__(self, base: str, *, token_env: str | None = None, local: bool = True, timeout: float = TIMEOUT,
                 opener: Any = None) -> None:
        self.base = base.rstrip("/")
        self.token_env = token_env
        self.timeout = timeout
        handlers: list[Any] = [urllib.request.ProxyHandler({})] if local else []
        self.opener = opener or urllib.request.build_opener(*handlers, _NoRedirect())

    def ui(self, project_id: str | None = None) -> str:
        """The hub's own page, opened on a project (its `#project=<id>` address)."""
        return self.base + "/" + (f"#project={urllib.parse.quote(project_id, safe='')}" if project_id else "")

    def _request(self, path: str) -> urllib.request.Request:
        headers = {"Accept": "application/json", "User-Agent": "rihmasto-agentobs/1"}
        token = os.environ.get(self.token_env or "") if self.token_env else None
        if token:
            headers["Authorization"] = "Bearer " + token
        return urllib.request.Request(self.base + path, headers=headers, method="GET")

    def get(self, path: str, ok: tuple[int, ...] = (200,)) -> tuple[int, Any]:
        """(status, JSON body) of a GET; HubUnreachable when nothing answered, HubError for any other answer."""
        try:
            with self.opener.open(self._request(path), timeout=self.timeout) as resp:
                status, raw = resp.status, resp.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read(MAX_BYTES + 1)
            exc.close()
        except (urllib.error.URLError, OSError, ValueError) as exc:
            reason = getattr(exc, "reason", exc)
            raise HubUnreachable(f"{self.base} did not answer ({type(reason).__name__})") from None
        if status not in ok:
            raise HubError(f"{path.split('?')[0]} answered {status}", status)
        if len(raw) > MAX_BYTES:
            raise HubError(f"{path.split('?')[0]} answered more than {MAX_BYTES // (1024 * 1024)} MB", status)
        try:
            return status, json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise HubError(f"{path.split('?')[0]} answered something that is not JSON", status) from None

    def _project(self, project_id: str, tail: str = "") -> str:
        return "/v1/projects/" + urllib.parse.quote(project_id, safe="") + tail

    def health(self) -> dict[str, Any]:
        return _obj(self.get("/health")[1])

    def projects(self) -> list[dict[str, Any]]:
        return [p for p in _obj(self.get("/v1/projects")[1]).get("projects") or [] if isinstance(p, dict)]

    def project(self, project_id: str) -> dict[str, Any] | None:
        """The hub's summary of a project; None when the hub has never heard of it (404)."""
        status, body = self.get(self._project(project_id), READABLE["project"])
        return _obj(_obj(body).get("project")) if status == 200 else None

    def sessions(self, project_id: str) -> list[dict[str, Any]]:
        body = _obj(self.get(self._project(project_id, "/sessions"))[1])
        return [s for s in body.get("sessions") or [] if isinstance(s, dict)]

    def section(self, project_id: str, name: str) -> dict[str, Any]:
        """``metrics``, ``intelligence`` or ``insight``: the object the route wraps under that name."""
        return _obj(_obj(self.get(self._project(project_id, "/" + name))[1]).get(name))

    def chain(self, project_id: str) -> dict[str, Any]:
        """The chain's verdict with the status it came with: ``{"status", "verification" | "error"}``."""
        status, body = self.get(self._project(project_id, "/chain"), READABLE["chain"])
        body = _obj(body)
        return {"status": status, "verification": _obj(body.get("verification")) or None,
                "error": body.get("error") if status != 200 and status != 409 else None,
                "event_count": body.get("event_count"), "ceiling": body.get("ceiling")}


_obj = object_of        # a field as a dict; anything else (absent, a string, a list) as an empty one


def from_settings(factory: Any, *, timeout: float = TIMEOUT, opener: Any = None) -> Hub | None:
    """The hub IT set, or None when no address is set."""
    s = settings(factory)
    if not s["url"]:
        return None
    local = where(s["url"], private=bool(s["private"])) != "hosted"
    return Hub(s["url"], token_env=s["token_env"], local=local, timeout=timeout, opener=opener)
