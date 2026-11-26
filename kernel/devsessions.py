"""Sessions in outside coding tools, captured by hooks a project installs (FR-DEV1), and a developer's last look.

The owner (2026-11-25): "insights about the latest sessions, whether inside Rihmasto with Gnomon or in Claude Code".
A project offers a small hook script and the configuration for Claude Code (``SessionStart`` and ``SessionEnd`` in
``.claude/settings.json``) and for Cursor (``beforeSubmitPrompt`` and ``stop`` in ``.cursor/hooks.json``). When a
session starts or ends, the hook records **metadata only** in the project's ``dev_sessions.json``: the session's id,
the harness, the branch, the head commit and, at the end, how many commits and changed files it left and the task
ids its commits name. Never a prompt, a file's content or the transcript. Every record is in the ledger as
``dev_session_recorded``, signed by the named person who operates the agent. The hook never stops the agent: a
failure is one line on its error output, saying what to do.

Rihmasto writes nothing into the person's repository: the files are shown to copy or download.

A developer's **last look** (``dev_looked`` in the ledger, by Got it on the briefing) is where the briefing counts
"since" from.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from kernel.people import PERSONAS, is_person
from kernel.store import REPO_ROOT, updating_json

FILE = "dev_sessions.json"
KIND = "dev_session_recorded"
LOOKED = "dev_looked"
HARNESSES = {"claude-code": "Claude Code", "cursor": "Cursor", "codex": "Codex", "opencode": "OpenCode",
             "gnomon": "Gnomon", "other": "another tool"}
EVENTS = ("start", "end")
KEEP = 500
OPEN_HOURS = 12
SESSION = re.compile(r"[A-Za-z0-9._:-]{1,80}\Z")
BRANCH = re.compile(r"[\w./@+-]{1,120}\Z")
HEAD = re.compile(r"[0-9a-f]{7,40}\Z")
TASK = re.compile(r"\bT-\d{1,6}\b")
HOOK_FILE = ".rihmasto/session_hook.py"
GIT_TIMEOUT = 10


class SessionRefused(ValueError):
    """A session record the project does not take, with the reason."""


def _blank() -> dict[str, Any]:
    return {"schema": "rihmasto.dev_sessions/1", "sessions": []}


def sessions(project: Any, since: str | None = None) -> list[dict[str, Any]]:
    """The recorded sessions, oldest first; with ``since`` (a time), only the later ones."""
    doc = project.read(FILE, None)
    rows = doc.get("sessions") if isinstance(doc, dict) else None
    return [s for s in rows or [] if isinstance(s, dict) and (not since or str(s.get("at")) > since)]


def _when(stamp: Any) -> dt.datetime | None:
    """A record's time, or None for one that has none or cannot be read (it never counts as now)."""
    text = str(stamp or "").replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(text) if text else None
    except ValueError:
        return None


def open_sessions(project: Any) -> list[dict[str, Any]]:
    """The sessions whose last record is a start, or an end it resumed after, from the last few hours: still
    running in an outside tool."""
    last: dict[str, dict[str, Any]] = {}
    for s in sessions(project):
        last[f"{s.get('harness')}|{s.get('session')}"] = s
    now = project.factory.clock.now()
    out = []
    for s in last.values():
        at = _when(s.get("resumed") or s.get("at"))
        live = s.get("event") == "start" or bool(s.get("resumed"))
        if live and at is not None and (now - at).total_seconds() < OPEN_HOURS * 3600:
            out.append(s)
    return out


def _count(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100_000:
        raise SessionRefused(f"{name} is a count from 0 to 100000")
    return value


def _checked(harness: str, event: str, session: str, person: str, persona: str) -> None:
    if harness not in HARNESSES:
        raise SessionRefused(f"harness is one of {', '.join(HARNESSES)}")
    if event not in EVENTS:
        raise SessionRefused("event is start or end")
    if not SESSION.match(session or ""):
        raise SessionRefused("a session id is up to 80 letters, digits, dots, colons, underscores and hyphens")
    if not is_person(person) or persona not in PERSONAS:
        raise SessionRefused(f"{person!r} with {persona!r}: a session is signed by the named person who operates "
                             "the agent, with their persona")


def _meta(branch: str | None, head: str | None, tasks: Any, reason: str | None) -> dict[str, Any]:
    """The optional metadata, checked: nothing that could carry what the session said."""
    out: dict[str, Any] = {}
    if branch:
        if not BRANCH.match(branch):
            raise SessionRefused("a branch name is up to 120 letters, digits and . / @ + - _")
        out["branch"] = branch
    if head:
        if not HEAD.match(head):
            raise SessionRefused("a head is a commit id of 7 to 40 hexadecimal digits")
        out["head"] = head
    found = sorted({t for t in tasks or [] if isinstance(t, str) and TASK.fullmatch(t)})[:20]
    if found:
        out["tasks"] = found
    if reason:
        out["reason"] = re.sub(r"[^a-z_ -]", "", str(reason).lower())[:40]
    return out


def _previous(rows: list[dict[str, Any]], harness: str, session: str,
              event: str | None = None) -> dict[str, Any] | None:
    return next((s for s in reversed(rows) if s.get("harness") == harness and s.get("session") == session
                 and (event is None or s.get("event") == event)), None)


def _seconds(row: dict[str, Any], start: dict[str, Any] | None) -> None:
    began, ended = _when((start or {}).get("at")), _when(row.get("at"))
    if began is not None and ended is not None:
        row["seconds"] = max(0, int((ended - began).total_seconds()))


def _again(rows: list[dict[str, Any]], before: dict[str, Any], row: dict[str, Any]) -> dict[str, Any] | None:
    """A record of a session already recorded changes its first records instead of adding new ones (FR-DEV2):
    Cursor's ``beforeSubmitPrompt`` and ``stop`` come at every turn, and Claude Code resumes a session by its id. A
    start after the end marks the session resumed (open again); a later end updates the end with the whole session's
    counts. None when ``row`` is the session's first end."""
    start = _previous(rows, row["harness"], row["session"], "start")
    if row["event"] == "start":
        if before.get("event") == "end":
            before["resumed"] = row["at"]
        return {"session": start or before, "recorded": False}
    if before.get("event") != "end":
        return None
    before.update(row)
    before.pop("resumed", None)
    _seconds(before, start)
    return {"session": before, "recorded": False}


def record(project: Any, *, harness: str, event: str, session: str, person: str, persona: str,
           branch: str | None = None, head: str | None = None, commits: int | None = None,
           files_changed: int | None = None, tasks: Any = None, reason: str | None = None) -> dict[str, Any]:
    """Record a session's start or end (metadata only): one start and one end per session, whatever the harness
    sends. A second start, or a start after the end (Cursor's next turn), is not recorded again; it marks the session
    resumed. A second end updates the first end, its counts covering the whole session since the start."""
    _checked(harness, event, session, person, persona)
    row: dict[str, Any] = {"session": session, "harness": harness, "harness_label": HARNESSES[harness],
                           "event": event, "person": person, "persona": persona, "at": project.factory.clock.stamp(),
                           **_meta(branch, head, tasks, reason)}
    for name, value in (("commits", commits), ("files_changed", files_changed)):
        if _count(value, name) is not None:
            row[name] = value
    with updating_json(project.path(FILE), _blank()) as doc:
        rows = doc.setdefault("sessions", [])
        before = _previous(rows, harness, session)
        again = _again(rows, before, row) if before is not None else None
        if again is not None:
            return again
        if event == "end":
            _seconds(row, before)
        row["id"] = f"S-{int(doc.get('next', len(rows) + 1)):04d}"
        doc["next"] = int(row["id"][2:]) + 1
        rows.append(row)
        del rows[:-KEEP]
    project.log(KIND, {k: row.get(k) for k in ("id", "session", "harness", "event", "person", "persona", "branch",
                                               "tasks", "commits", "files_changed") if row.get(k) is not None})
    return {"session": row, "recorded": True}


# -- a developer's last look -------------------------------------------------------------------------------

def look(project: Any, *, person: str, persona: str) -> dict[str, Any]:
    """Record that ``person`` read the development briefing now: the next one counts from here."""
    if not is_person(person) or persona not in PERSONAS:
        raise SessionRefused("a look is signed by a named person with their persona")
    rec = project.log(LOOKED, {"person": person, "persona": persona})
    return {"person": person, "at": rec["event"].get("at")}


def last_look(project: Any, person: str | None) -> str | None:
    """When ``person`` last pressed Got it on this project's developer briefing, or None."""
    if not person:
        return None
    looks = [r["event"] for r in project.ledger().of_kind(LOOKED)
             if (r["event"].get("payload") or {}).get("person") == person]
    return looks[-1].get("at") if looks else None


# -- the hooks a project installs --------------------------------------------------------------------------

SCRIPT = '''#!/usr/bin/env python3
"""Rihmasto session hook, generated for one project. It tells Rihmasto that a coding-agent session started or
ended in this repository: the session's id, the tool, the branch, the head commit and, at the end, how many commits
and changed files it left. Metadata only: never a prompt, a file's content or the transcript. It never stops the
agent: a failure is one line on its error output."""
import sys

ROOT = @@ROOT@@
HOME = @@HOME@@
PROJECT = @@PID@@
PERSON = @@PERSON@@
PERSONA = @@PERSONA@@


def main():
    try:
        sys.path.insert(0, ROOT)
        from kernel.devsessions import hook_main
        hook_main(sys.argv[1:], sys.stdin, home=HOME, pid=PROJECT, person=PERSON, persona=PERSONA)
    except Exception as exc:  # noqa: BLE001 - a hook never stops the agent
        sys.stderr.write("rihmasto session hook: not recorded (%s). Open the project's Trace in Rihmasto: it "
                         "says how to set the hook up again.\\n" % exc)
    if "cursor" in sys.argv and "start" in sys.argv:
        print('{"continue": true}')
    return 0


sys.exit(main())
'''


def _command(python: str, harness: str, event: str) -> str:
    return f'"{Path(python).as_posix()}" {HOOK_FILE} --harness {harness} --event {event}'


def _claude(python: str) -> dict[str, Any]:
    hook = lambda e: [{"hooks": [{"type": "command", "command": _command(python, "claude-code", e)}]}]  # noqa: E731
    return {"hooks": {"SessionStart": hook("start"), "SessionEnd": hook("end")}}


def _cursor(python: str) -> dict[str, Any]:
    return {"version": 1, "hooks": {"beforeSubmitPrompt": [{"command": _command(python, "cursor", "start")}],
                                    "stop": [{"command": _command(python, "cursor", "end")}]}}


def hooks(project: Any, *, person: str, persona: str, python: str) -> dict[str, Any]:
    """The files a project's repository takes to capture Claude Code and Cursor sessions, to copy or download."""
    values = {"@@ROOT@@": REPO_ROOT.as_posix(), "@@HOME@@": Path(project.factory.home).resolve().as_posix(),
              "@@PID@@": project.pid, "@@PERSON@@": person, "@@PERSONA@@": persona}
    script = SCRIPT
    for key, value in values.items():
        script = script.replace(key, json.dumps(value))
    return {"project": project.pid, "person": person, "persona": persona, "files": [
        {"path": HOOK_FILE, "for": "both", "content": script},
        {"path": ".claude/settings.json", "for": "claude-code", "merge": True,
         "content": json.dumps(_claude(python), indent=2) + "\n"},
        {"path": ".cursor/hooks.json", "for": "cursor", "merge": True,
         "content": json.dumps(_cursor(python), indent=2) + "\n"}],
        "records": "metadata only: the session id, the tool, the branch, the head commit, counts of commits and "
                   "changed files, and the task ids its commits name",
        "ignore": ".rihmasto/ in the repository's .gitignore: the script names this computer's Rihmasto folder"}


# -- the hook itself -----------------------------------------------------------------------------------------

def _git(cwd: str, *args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _args(argv: list[str]) -> dict[str, str]:
    out = {}
    for i, a in enumerate(argv[:-1]):
        if a in ("--harness", "--event"):
            out[a[2:]] = argv[i + 1]
    return out


def _input(stdin: Any) -> dict[str, Any]:
    try:
        data = json.loads(stdin.read(1_000_000) or "{}")
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _since_start(project: Any, harness: str, session: str, cwd: str) -> dict[str, Any]:
    """At the end: the commits since the session's start head, the files changed since then, their task ids."""
    start = _previous(sessions(project), harness, session, "start")     # the one start: the whole session
    base = (start or {}).get("head")
    if not base:
        return {}
    count = _git(cwd, "rev-list", "--count", f"{base}..HEAD")
    files = [f for f in _git(cwd, "diff", "--name-only", base).splitlines() if f.strip()]
    subjects = _git(cwd, "log", "--format=%s", f"{base}..HEAD")
    return {"commits": int(count) if count.isdigit() else None, "files_changed": len(files),
            "tasks": TASK.findall(subjects)}


def hook_main(argv: list[str], stdin: Any, *, home: str, pid: str, person: str, persona: str) -> dict[str, Any]:
    """What the generated hook runs: read the harness's input, read git in its folder, record the metadata."""
    from kernel.store import Factory

    args = _args(argv)
    data = _input(stdin)
    harness, event = args.get("harness", "other"), args.get("event", "")
    session = str(data.get("session_id") or data.get("conversation_id") or data.get("sessionId") or "")[:80]
    cwd = str(data.get("cwd") or (data.get("workspace_roots") or ["."])[0] or ".")
    project = Factory(home).project(pid)
    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or None
    head = _git(cwd, "rev-parse", "HEAD") or None
    more = _since_start(project, harness, session, cwd) if event == "end" else {}
    tasks = list(more.pop("tasks", [])) + TASK.findall(branch or "")
    return record(project, harness=harness, event=event, session=session, person=person, persona=persona,
                  branch=branch, head=head, tasks=tasks, reason=str(data.get("reason") or data.get("source") or "")
                  or None, **more)


__all__ = ["EVENTS", "HARNESSES", "SessionRefused", "hook_main", "hooks", "last_look", "look", "open_sessions",
           "record", "sessions"]
