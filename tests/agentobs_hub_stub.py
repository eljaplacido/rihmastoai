"""A stand-in for the agent observability hub's read API, on 127.0.0.1 only (FR-OBS1 tests).

Built from the hub's documented `/v1` contract (routes, shapes and statuses), with fixture data: one project,
``acme/checkout``, with five sessions across three harnesses (Claude Code, Cursor, OpenCode), rework concentrated
in one file, a failure that was recovered, one that was never recovered and one that cannot be told (a shell
command), a session that read the contract before editing and one that did not, and a verified hash chain. A
second project, ``acme/empty``, has no session. Every request is kept (``requests``) so a test can see that only
GETs were sent, and with which headers. Nothing here is the hub's code; it answers as the contract says.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

PROJECT = "acme/checkout"
EMPTY = "acme/empty"
NOW = "2026-11-22T12:00:00Z"


def _at(base: dt.datetime, days: float, minutes: float = 0) -> str:
    return (base - dt.timedelta(days=days) + dt.timedelta(minutes=minutes)).isoformat(timespec="milliseconds") \
        .replace("+00:00", "Z")


def _step(at: str, event: str, tool: str | None = None, file: str | None = None) -> dict[str, Any]:
    return {"event_id": f"e-{at}-{event}-{tool}", "event_type": event, "occurred_at": at, "run_id": "turn-1",
            "label": event.replace(".", " "), "tool_name": tool, "file_path": file,
            "status": "error" if event == "tool.failed" else None, "duration_ms": 1200 if tool else None}


def _session(sid: str, harness: str, start: str, steps: list[tuple], base: dt.datetime, days: float) -> dict:
    rows = [_step(_at(base, days, i), *s) for i, s in enumerate(steps)]
    files = sorted({s[2] for s in steps if len(s) > 2 and s[2]})
    return {"session_id": sid, "harness_name": harness, "started_at": start, "ended_at": rows[-1]["occurred_at"],
            "duration_ms": 60000 * len(rows), "status": "ended", "had_failure": any(s[0] == "tool.failed" for s in steps),
            "last_activity_at": rows[-1]["occurred_at"], "idle_ms": 0, "liveness": "stale", "current_step": None,
            "event_count": len(rows), "tool_count": sum(1 for s in steps if len(s) > 1), "file_count": len(files),
            "prompt_count": 1, "tools": sorted({s[1] for s in steps if len(s) > 1}), "files": files, "steps": rows,
            "step_count": len(rows), "run_ids": ["turn-1"]}


def fixture(now: str = NOW) -> dict[str, Any]:
    """The hub's answers for the fixture project, timed against ``now``."""
    base = dt.datetime.fromisoformat(now.replace("Z", "+00:00"))
    total, tax, test = "src/checkout/total.ts", "src/checkout/tax.ts", "tests/checkout.test.ts"
    plan = [
        ("s-claude-1", "claude-code", 3, [("session.started",), ("prompt.submitted",), ("tool.completed", "Read", "AGENTS.md"),
                                          ("tool.completed", "Edit", total), ("tool.failed", "Edit", total),
                                          ("tool.completed", "Edit", total), ("tool.completed", "Bash"),
                                          ("session.ended",)]),
        ("s-cursor-1", "cursor", 2, [("session.started",), ("prompt.submitted",), ("tool.completed", "edit", total),
                                     ("tool.completed", "edit", total), ("tool.failed", "shell"),
                                     ("session.ended",)]),
        ("s-opencode-1", "opencode", 1, [("session.started",), ("prompt.submitted",), ("tool.completed", "read", "AGENTS.md"),
                                         ("tool.completed", "edit", test), ("tool.failed", "edit", tax),
                                         ("session.ended",)]),
        ("s-claude-2", "claude-code", 1, [("session.started",), ("prompt.submitted",), ("tool.completed", "Edit", total),
                                          ("tool.completed", "Edit", total), ("tool.completed", "Edit", tax),
                                          ("tool.completed", "Edit", tax), ("tool.completed", "Edit", tax),
                                          ("session.ended",)]),
        ("s-claude-3", "claude-code", 0.2, [("session.started",), ("prompt.submitted",),
                                            ("tool.completed", "Read", "README.md"), ("session.ended",)]),
    ]
    sessions = [_session(sid, h, _at(base, d), steps, base, d) for sid, h, d, steps in plan]
    sessions.sort(key=lambda s: s["started_at"], reverse=True)
    project = {"project_id": PROJECT, "workspace_id": "acme", "repository_id": PROJECT, "title": "checkout",
               "last_event_at": sessions[0]["ended_at"], "last_event_type": "session.ended",
               "last_harness": "claude-code", "event_count": 87, "open_blocker_count": 0,
               "last_chain_hash": "sha256:00", "updated_at": sessions[0]["ended_at"]}
    rework = {"threshold": 3, "files": [{"file": total, "label": "total.ts", "directory": "checkout", "edits": 7,
                                         "sessions": 3},
                                        {"file": tax, "label": "tax.ts", "directory": "checkout", "edits": 4,
                                         "sessions": 2},
                                        {"file": test, "label": "checkout.test.ts", "directory": "tests", "edits": 1,
                                         "sessions": 1}],
              "total_files_edited": 3, "total_edits": 12, "files_above_threshold": 2, "top_share": 0.9166}
    activity = [{"harness_name": h, "sessions": n, "events": 10 * n, "tool_events": 6 * n, "files": 2,
                 "tool_share": 0.3, "last_activity_at": sessions[0]["ended_at"]}
                for h, n in (("claude-code", 3), ("cursor", 1), ("opencode", 1))]
    intelligence = {
        "governance": {"contract_status": "present", "skills_status": "absent", "sessions_total": 5,
                       "sessions_touching_code": 4, "sessions_reading_contract": 2, "sessions_contract_first": 2,
                       "contract_engagement_rate": 0.5, "doc_reads": 2, "doc_edits": 0, "source_edits": 12,
                       "doc_to_code_ratio": 0.16, "docs": [{"file": "AGENTS.md", "label": "AGENTS.md",
                                                            "kind": "contract", "reads": 2, "sessions": 2}],
                       "skill_invocations": 0, "decision_points": [], "decision_point_count": 0,
                       "decisions_recorded": 0},
        "trajectory": {"steps_total": 22, "productive": 11, "exploratory": 4, "execution": 2, "corrective": 5,
                       "other": 0, "exploration_ratio": 0.36, "corrective_share": 0.22,
                       "loops": [{"session_id": "s-claude-2", "tool": "Edit", "file": tax, "label": "Edit / tax.ts",
                                  "occurrences": 3}], "median_steps_to_first_edit": 2, "sessions_measured": 5},
        "quality": {"tool_events": 40, "tool_steps": 20, "tool_failures": 3, "tool_failure_rate": 0.15,
                    "recovered_failures": 1, "blocked_failures": 1, "undetermined_failures": 1, "recovery_rate": 0.5,
                    "test_events": 0, "test_activity_share": 0, "sessions_editing_without_tests": 3,
                    "sessions_touching_code": 4},
        "context": {}, "tool_duration_histogram": [], "maturity": None}
    metrics = {"completed_sessions": 5, "failed_sessions": 3, "failure_rate": 0.6, "tool_events": 40,
               "tool_failures": 3, "tool_failure_rate": 0.075}
    return {"project": project, "sessions": sessions, "insight": {"session_count": 5, "active_sessions": 0,
                                                                  "harnesses": ["claude-code", "cursor", "opencode"],
                                                                  "rework": rework, "harness_activity": activity},
            "intelligence": intelligence, "metrics": metrics,
            "chain": {"valid": True, "checked": 87, "reachable": 87, "breaks": []}}


class HubStub:
    """``with HubStub() as hub:`` a hub on 127.0.0.1 at ``hub.url``. ``chain_status`` 409 breaks the chain, 503
    makes it too long; ``empty`` empties the fixture project."""

    def __init__(self, now: str = NOW, *, attests: str = "derived-on-load") -> None:
        self.data = fixture(now)
        self.attests, self.chain_status, self.empty = attests, 200, False
        self.requests: list[dict[str, Any]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802 - http.server's name
                stub.requests.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
                status, body = stub.answer(urllib.parse.urlsplit(self.path).path)
                self._send(status, body)

            def do_POST(self) -> None:  # noqa: N802 - http.server's name
                stub.requests.append({"method": "POST", "path": self.path, "headers": dict(self.headers)})
                self._send(401, {"error": "unauthorized"})

            def _send(self, status: int, body: Any) -> None:
                raw = json.dumps(body).encode("utf-8") if not isinstance(body, bytes) else body
                self.send_response(status)
                self.send_header("Content-Type", "application/json" if not isinstance(body, bytes) else "text/plain")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

    def __enter__(self) -> HubStub:
        self.thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def _projects(self) -> list[dict[str, Any]]:
        empty = dict(self.data["project"], project_id=EMPTY, repository_id=EMPTY, title="empty", event_count=0)
        return [self.data["project"], empty]

    def answer(self, path: str) -> tuple[int, Any]:
        """The status and body the hub's contract gives for ``path``."""
        if path == "/health":
            return 200, {"ok": True, "service": "cockpit-hub-api", "chain_attests": self.attests}
        if path == "/v1/projects":
            return 200, {"projects": self._projects()}
        parts = path.split("/")
        if len(parts) < 4 or parts[1:3] != ["v1", "projects"]:
            return 404, b"404 Not Found"
        pid, tail = urllib.parse.unquote(parts[3]), "/".join(parts[4:])
        known = {p["project_id"]: p for p in self._projects()}
        full = pid == PROJECT and not self.empty
        if tail == "":
            return (200, {"project": known[pid]}) if pid in known else (404, {"error": "project not found"})
        if tail == "chain":
            return self._chain(pid, known)
        if tail == "sessions":
            return 200, {"project_id": pid, "sessions": self.data["sessions"] if full else []}
        if tail in ("insight", "intelligence", "metrics"):
            return 200, {"project_id": pid, tail: self.data[tail] if full else {}}
        return 404, b"404 Not Found"

    def _chain(self, pid: str, known: dict[str, Any]) -> tuple[int, Any]:
        if pid not in known:
            return 404, {"error": "project not found"}
        if self.chain_status == 503:
            return 503, {"error": "chain too long to verify in one pass", "event_count": 250000, "ceiling": 200000}
        ver = dict(self.data["chain"])
        if self.chain_status == 409:
            ver.update(valid=False, breaks=[{"event_id": "e-1", "reason": "hash mismatch"}])
        return self.chain_status, {"project_id": pid, "verification": ver}
