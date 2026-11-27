"""Live progress for long jobs (FR-PRG1): what a job will do, what it is doing now, and what it found so far.

A long job (an assessment, an adoption, a folder scan, a gate round, a delivery, an audit) reports through a
`Reporter`:

- a **plan** first: its groups of steps, each step with a label (for an assessment: reading the code, one rule
  check per area, one step per perspective of the panel with the model that answers, the record);
- then **events**: a step started (with the words for what it does now), done (with its counts: passed,
  findings, not measured), failed (why), skipped (why), and **partial results** (the findings a step found).

The reporter is kept with the job, in memory, while the job's process runs: `register` files it under a key
(`key_for(project, "assessment")`) where a route and Ask Rihma find it (`live`). `since(cursor)` answers with
only what changed after a cursor, so a page that polls every second reads a few events, not the whole job.

The estimate is honest: it comes from the step durations of earlier runs of the same kind on the same project
(`History`, kept beside the cockpit's own files), the median of the last few runs per step. A step never timed
before has no estimate, and a first run says "first run: no estimate" instead of inventing one.

A person may cancel: `cancel()` asks, and the job stops at its next step (`start` raises `Cancelled`), so a
step is never cut off half done and nothing half made is recorded.
"""

from __future__ import annotations

import contextlib
import json
import statistics
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

SCHEMA = "rihmasto.progress/1"
STATES = ("waiting", "running", "done", "failed", "skipped")
ENDS = ("done", "failed", "cancelled")
KEEP_RUNS = 5               # the earlier runs an estimate reads, per kind
MAX_FINDINGS = 60           # partial findings kept per step: a long list is counted, not carried
MAX_EVENTS = 2000           # a job that reports more keeps its steps' state; old events are dropped
_TEXT = 300


class Cancelled(Exception):
    """A person cancelled the job: it stopped between two steps and recorded nothing half made."""


def step(sid: str, label: str, *, by: str | None = None, said: str = "") -> dict[str, Any]:
    """One step of a plan: its id (unique in the plan), its label, who does it (a model, when one does)."""
    return {"id": sid, "label": label, "by": by, "said": said}


def group(gid: str, label: str, steps: Iterable[dict[str, Any]], *, parallel: bool = False) -> dict[str, Any]:
    """A group of steps shown together, such as "Rule checks". ``parallel``: its steps may run at once."""
    return {"id": gid, "label": label, "parallel": parallel, "steps": [dict(s) for s in steps]}


def _short(text: Any, limit: int = _TEXT) -> str:
    return " ".join(str(text or "").split())[:limit]


def _finding(raw: dict[str, Any]) -> dict[str, Any]:
    """A partial finding as the view lists it: never the evidence, only what a person scans."""
    keys = ("id", "key", "title", "severity", "perspective", "by", "panel")
    return {k: _short(raw[k], 200) for k in keys if raw.get(k) is not None}


class History:
    """Each kind's step durations from its earlier runs, in one JSON file per project (or the factory)."""

    def __init__(self, path: Path | None) -> None:
        self.path = path

    def _read(self) -> dict[str, Any]:
        if self.path is None:
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) and data.get("schema") == SCHEMA else {}

    def runs(self, kind: str) -> list[dict[str, Any]]:
        got = (self._read().get("runs") or {}).get(kind)
        return [r for r in got if isinstance(r, dict)] if isinstance(got, list) else []

    def expected(self, kind: str) -> tuple[int, dict[str, float]]:
        """How many earlier runs there are, and each step's median duration in them, in seconds."""
        runs = self.runs(kind)[-KEEP_RUNS:]
        took: dict[str, list[float]] = {}
        for r in runs:
            for sid, secs in (r.get("steps") or {}).items():
                if isinstance(secs, (int, float)) and secs >= 0:
                    took.setdefault(sid, []).append(float(secs))
        return len(runs), {sid: round(statistics.median(v), 2) for sid, v in took.items()}

    def remember(self, kind: str, steps: dict[str, float], total: float, at: str) -> None:
        """Keep one finished run's step durations; the oldest beyond the last few are dropped."""
        if self.path is None:
            return
        data = self._read() or {"schema": SCHEMA, "runs": {}}
        runs = data.setdefault("runs", {}).setdefault(kind, [])
        runs.append({"at": at, "total_s": round(total, 2), "steps": {k: round(v, 2) for k, v in steps.items()}})
        data["runs"][kind] = runs[-KEEP_RUNS:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)


class Reporter:
    """A job's progress: its plan, its steps' state, its events in order, and a way to stop it."""

    def __init__(self, kind: str, title: str = "", *, history: History | None = None,
                 clock: Callable[[], float] = time.monotonic, stamp: Callable[[], str] | None = None) -> None:
        self.kind, self.title = kind, _short(title, 200)
        self.history = history
        self._clock, self._stamp = clock, stamp or (lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        self._lock = threading.RLock()
        self.groups: list[dict[str, Any]] = []
        self.steps: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.dropped = 0
        self.state, self.why = "running", ""
        self.result: dict[str, Any] | None = None
        self.started = clock()
        self.ended: float | None = None
        self.started_at = self._stamp()
        self.cancel_asked: dict[str, Any] | None = None
        self.earlier, self.expect = history.expected(kind) if history else (0, {})

    # -- the plan and the events ------------------------------------------------------------------------

    def _now(self) -> float:
        return round(self._clock() - self.started, 2)

    def _emit(self, kind: str, sid: str | None = None, **data: Any) -> None:
        event = {"seq": self.dropped + len(self.events) + 1, "t": self._now(), "kind": kind}
        if sid is not None:
            event["step"] = sid
            event["state"] = self._public(self.steps[sid])
        self.events.append(event | data)
        if len(self.events) > MAX_EVENTS:
            self.events.pop(0)
            self.dropped += 1

    def plan(self, groups: Iterable[dict[str, Any]]) -> None:
        """The job's groups and steps, before the first step starts."""
        with self._lock:
            self.groups = [group(g["id"], g["label"], g["steps"], parallel=bool(g.get("parallel")))
                           for g in groups]
            for g in self.groups:
                for s in g["steps"]:
                    self.steps[s["id"]] = s | {"group": g["id"], "state": "waiting", "counts": {}, "why": "",
                                               "findings": [], "more": 0, "t0": None, "t1": None,
                                               "expected_s": self.expect.get(s["id"])}
            self._emit("plan", plan=self._plan())

    def _step(self, sid: str) -> dict[str, Any]:
        if sid not in self.steps:
            raise KeyError(f"{sid} is not a step of the {self.kind}'s plan")
        return self.steps[sid]

    def start(self, sid: str, said: str = "") -> None:
        """A step starts; a cancel asked for stops the job here, before the step does anything."""
        with self._lock:
            self.check()
            s = self._step(sid)
            s.update(state="running", t0=self._now(), said=_short(said) or s.get("said") or "")
            self._emit("started", sid)

    def say(self, sid: str, said: str) -> None:
        """What a running step does now, in words ("The IT and security perspective is reading ...")."""
        with self._lock:
            self._step(sid)["said"] = _short(said)
            self._emit("said", sid)

    def found(self, sid: str, findings: Iterable[dict[str, Any]]) -> None:
        """Partial results: findings a step found, before the job ends."""
        with self._lock:
            s = self._step(sid)
            new = [_finding(f) for f in findings]
            room = max(0, MAX_FINDINGS - len(s["findings"]))
            s["findings"] += new[:room]
            s["more"] += len(new) - len(new[:room])
            if new:
                self._emit("found", sid, findings=new[:room])

    def done(self, sid: str, counts: dict[str, int] | None = None, said: str = "", by: str | None = None) -> None:
        """A step ended; ``counts`` are its verdicts (passed, findings, not measured) or what it proposed."""
        with self._lock:
            s = self._step(sid)
            s.update(state="done", t1=self._now(), counts=dict(counts or {}), said=_short(said) or s["said"])
            if by:
                s["by"] = _short(by, 200)
            self._emit("done", sid)

    def failed(self, sid: str, why: str) -> None:
        with self._lock:
            self._step(sid).update(state="failed", t1=self._now(), why=_short(why))
            self._emit("failed", sid)

    def skip(self, sid: str, why: str) -> None:
        with self._lock:
            self._step(sid).update(state="skipped", why=_short(why))
            self._emit("skipped", sid)

    # -- cancelling and ending --------------------------------------------------------------------------

    def cancel(self, by: dict[str, Any] | None = None) -> bool:
        """Ask the job to stop at its next step; False when it already ended."""
        with self._lock:
            if self.state != "running":
                return False
            if self.cancel_asked is None:
                self.cancel_asked = {"by": by or {}, "t": self._now()}
                self._emit("cancel_asked", by=by or {})
            return True

    def check(self) -> None:
        """Raise `Cancelled` when a person asked the job to stop."""
        if self.cancel_asked is not None:
            raise Cancelled("cancelled by " + str((self.cancel_asked.get("by") or {}).get("person") or "a person"))

    def finish(self, state: str = "done", why: str = "", result: dict[str, Any] | None = None) -> None:
        """The job ended: done, failed (why) or cancelled. A step still running ends with it, and a finished
        run's step durations are kept for the next run's estimate."""
        if state not in ENDS:
            raise ValueError(f"a job ends {', '.join(ENDS)}, not {state!r}")
        with self._lock:
            if self.state != "running":
                return
            for s in self.steps.values():
                if s["state"] == "running":
                    s.update(state="failed" if state == "failed" else "skipped", t1=self._now(),
                             why=_short(why) or ("cancelled" if state == "cancelled" else "the job ended"))
                    self._emit("failed" if state == "failed" else "skipped", s["id"])
            ended = self._now()
            self.state, self.why, self.result, self.ended = state, _short(why), result, ended
            self._emit("end", end=state, why=self.why, result=result)
            if state == "done" and self.history is not None:
                took = {s["id"]: s["t1"] - s["t0"] for s in self.steps.values()
                        if s["state"] == "done" and s["t0"] is not None and s["t1"] is not None}
                with contextlib.suppress(OSError):
                    self.history.remember(self.kind, took, ended, self._stamp())

    @contextlib.contextmanager
    def running(self) -> Iterator[Reporter]:
        """Run the job's body: it ends done, cancelled, or failed with the error's words (and the error goes on)."""
        try:
            yield self
        except Cancelled as exc:
            self.finish("cancelled", str(exc))
            raise
        except BaseException as exc:
            self.finish("failed", f"{type(exc).__name__}: {exc}")
            raise
        self.finish("done", result=self.result)

    # -- reading ---------------------------------------------------------------------------------------

    @staticmethod
    def _public(s: dict[str, Any]) -> dict[str, Any]:
        keys = ("id", "group", "label", "by", "state", "said", "counts", "why", "more", "t0", "t1", "expected_s")
        return {k: s.get(k) for k in keys} | {"found": len(s["findings"]) + s["more"]}

    def _plan(self) -> list[dict[str, Any]]:
        return [{"id": g["id"], "label": g["label"], "parallel": g["parallel"],
                 "steps": [s["id"] for s in g["steps"]]} for g in self.groups]

    def now(self) -> str:
        """The current step in words: what runs now (several, when steps run at once), or how the job ended."""
        running = [s for s in self.steps.values() if s["state"] == "running"]
        if self.state != "running":
            return {"done": "Finished.", "cancelled": "Cancelled: nothing was recorded.",
                    "failed": f"Stopped: {self.why}"}[self.state]
        if self.cancel_asked is not None:
            return "Stopping after the step that runs now…"
        return " · ".join(s["said"] or s["label"] for s in running) or "Starting…"

    def estimate(self) -> dict[str, Any]:
        """Time left from earlier runs' step durations, or why there is none."""
        from kernel.progress_estimate import estimate

        return estimate(self)

    def since(self, cursor: int = 0) -> dict[str, Any]:
        """What changed after ``cursor`` (an event's seq): those events, and the job's state now. From cursor 0
        (or a cursor older than the events kept) the whole plan and every step come too."""
        with self._lock:
            whole = cursor <= self.dropped
            events = [e for e in self.events if e["seq"] > cursor]
            done = sum(1 for s in self.steps.values() if s["state"] in ("done", "failed", "skipped"))
            out = {"schema": SCHEMA, "kind": self.kind, "title": self.title, "state": self.state, "why": self.why,
                   "result": self.result, "cursor": self.dropped + len(self.events), "events": events,
                   "elapsed_s": self.ended if self.ended is not None else self._now(), "started_at": self.started_at,
                   "now": self.now(), "steps_done": done, "steps_total": len(self.steps),
                   "cancel_asked": self.cancel_asked, "estimate": self.estimate(), "whole": whole}
            if whole:
                out["plan"] = self._plan()
                out["steps"] = {sid: self._public(s) for sid, s in self.steps.items()}
                out["findings"] = {sid: list(s["findings"]) for sid, s in self.steps.items() if s["findings"]}
            return out


class _Silent:
    """A reporter for a job nobody watches: every call does nothing and nothing is cancelled."""

    def __getattr__(self, name: str) -> Callable[..., None]:
        return lambda *args, **kwargs: None


SILENT: Any = _Silent()


# -- where a running job's reporter is found ----------------------------------------------------------------

_LIVE: dict[str, Reporter] = {}
_LIVE_LOCK = threading.Lock()


def key_for(project: Any, kind: str) -> str:
    """The key a project's job of ``kind`` is registered under: the project's folder and the kind."""
    return f"{Path(project.path('project.json')).parent}#{kind}"


def register(key: str, reporter: Reporter) -> Reporter:
    with _LIVE_LOCK:
        _LIVE[key] = reporter
    return reporter


def live(key: str) -> Reporter | None:
    """The reporter registered under ``key``: the job running now, or the last one, until the next starts."""
    with _LIVE_LOCK:
        return _LIVE.get(key)


__all__ = ["ENDS", "SCHEMA", "SILENT", "STATES", "Cancelled", "History", "Reporter", "group", "key_for", "live",
           "register", "step"]
