"""Incidents: every failure a person could meet becomes a record Rihmasto can trace, explain and learn from
(FR-HEAL1, D-0024 item 1, docs/guides/self-healing.md).

An **incident** is opened for a server error (a 500), a failed job or one lost on a restart, a cockpit action that
failed, a view that broke or came back empty, a refused step the person did not expect (a confidential project's
hosted role among them), a failed check, automation or runner, a scan that had to degrade, an IDE agent's failure
the observability hub saw it not recover from, a failed Gnomon audit or role eval (kernel/heal_evals.py), and a
person's own "Something's wrong here". Each one carries:

- a **fingerprint**: the kind, where it happened (a route, a view, a job's kind), the error's class and its message
  normalised (ids, numbers, paths, addresses, quoted values and anything that looks like a secret taken out), hashed.
  The same failure has the same fingerprint wherever and whenever it happens, so immune memory (kernel/immune.py)
  can recognise it;
- its **context**: the view and the route, a summary of the request (its keys, never the body of a secret), the
  server log lines around it, a job's log tail, the ledger records involved and the persona, every string masked
  (kernel/redteam/masking.py) and cut;
- its **record**: ``incident_opened`` in the project's ledger, or the factory's own when no project is involved; the
  contents stay in ``heal/incidents/I-0001.json`` under the factory home.

The same fingerprint while its incident is still open is counted on that incident, not opened again. An incident
moves open -> investigating -> fixed, and to learned once what fixed it is approved as a remedy. Nothing here
decides or fixes anything: kernel/immune.py offers remedies, kernel/heal_investigate.py and kernel/heal_fix.py
investigate and fix, each step recorded.
"""

from __future__ import annotations

import collections
import hashlib
import re
import threading
from pathlib import Path
from typing import Any

from kernel.people import PERSONAS, is_person
from kernel.redteam.masking import mask
from kernel.store import Factory, Project, read_json, records_lock, updating_json, write_json

KINDS = ("server_error", "refused", "job_failed", "job_lost", "action_failed", "view_broken", "view_empty",
         "confidential_refused", "check_failed", "automation_failed", "runner_failed", "scan_degraded",
         "product_not_running", "report", "agent_failed", "eval_failed")
STATES = ("open", "investigating", "fixed", "learned")
DONE = ("fixed", "learned")
MAX_TEXT = 2000
MAX_LINES = 40
LIST_LIMIT = 200
# What a request summary may show of a body: who and what kind, never free text or anything secret.
SHOWN_KEYS = ("person", "persona", "verdict", "kind", "intent", "maturity", "mode", "view", "role", "harness",
              "via", "to", "lens", "check", "preset", "level", "state", "posture")
KIND_WORDS = {
    "server_error": "The cockpit hit a bug while answering", "refused": "A step was refused",
    "job_failed": "A background job failed", "job_lost": "A background job was lost",
    "action_failed": "An action did not go through", "view_broken": "A view could not be drawn",
    "view_empty": "A view came back empty", "confidential_refused": "A confidential project refused a hosted model",
    "check_failed": "A check failed", "automation_failed": "An automation failed",
    "runner_failed": "A cell runner failed", "scan_degraded": "A scan could only read part of the folder",
    "product_not_running": "The product is not running", "report": "A person reported something wrong",
    "agent_failed": "An IDE agent failed and did not recover", "eval_failed": "An audit or eval failed"}


class IncidentRefused(ValueError):
    """An incident write the kernel will not take: no person, an unknown kind or state, a closed incident."""


# -- the server's log, kept in memory for an incident's context ---------------------------------------------

class ServerLog:
    """The last lines the cockpit server logged (requests, tracebacks): an incident keeps those around it."""

    def __init__(self, size: int = 400) -> None:
        self._lines: collections.deque[str] = collections.deque(maxlen=size)
        self._lock = threading.Lock()

    def add(self, text: str) -> None:
        with self._lock:
            for line in str(text).splitlines():
                if line.strip():
                    self._lines.append(line[:500])

    def tail(self, n: int = 20) -> list[str]:
        with self._lock:
            return [mask(x) for x in list(self._lines)[-n:]]


LOG = ServerLog()


# -- fingerprints -------------------------------------------------------------------------------------------

_NORMALISE = (
    (re.compile(r"(?i)\b[a-z][a-z0-9+.-]{1,20}://\S+"), "<url>"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "<email>"),
    (re.compile(r"\"[^\"]{0,200}\"|'[^']{0,200}'|`[^`]{0,200}`"), "<q>"),
    (re.compile(r"(?:[A-Za-z]:)?(?:[\\/][\w .@~+-]+){2,}[\\/]?"), "<path>"),
    (re.compile(r"\b[\w.-]+\.(?:py|js|json|md|txt|log|toml|yaml|yml|cfg|ini|lock|sh)\b"), "<file>"),
    (re.compile(r"\b[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{6}\b"), "<project>"),
    (re.compile(r"\b[A-Z]{1,6}(?:-[A-Z0-9]{1,8}){0,3}-\d+\b"), "<id>"),
    (re.compile(r"\b[0-9a-f]{7,64}\b", re.I), "<hex>"),
    (re.compile(r"\d+(?:[.:]\d+)*"), "<n>"),
)


def mask_text(text: Any, limit: int = MAX_TEXT) -> str:
    """A string fit for an incident: every secret masked, whitespace kept, cut to ``limit``."""
    out = mask(str(text if text is not None else ""))
    return out if len(out) <= limit else out[: limit - 1] + "…"


def normalise(message: Any) -> str:
    """A message with what changes from one occurrence to the next taken out: secrets first, then addresses,
    quoted values, paths, file names, project ids, record ids, hashes and numbers."""
    text = mask(str(message or ""))
    text = re.sub(r"[A-Za-z0-9]{0,4}\*{4,}", "<secret>", text)
    for pattern, word in _NORMALISE:
        text = pattern.sub(word, text)
    return " ".join(text.lower().split())[:200]


def fingerprint(kind: str, where: str, error_class: str = "", message: str = "") -> str:
    """The stable name of a failure: its kind, where, its error's class and its normalised message, hashed."""
    basis = "|".join([kind, normalise(where), re.sub(r"[^A-Za-z0-9_.]", "", error_class or "")[:80],
                      normalise(message)])
    return "fp-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


# -- context ------------------------------------------------------------------------------------------------

def request_summary(method: str, path: str, route: str | None, query: dict[str, Any] | None,
                    body: dict[str, Any] | None) -> dict[str, Any]:
    """What an incident keeps of a request: the method, the route's name, the path, the query's keys and the
    body's keys, with only who-and-what values shown (``SHOWN_KEYS``) and never free text or a secret."""
    body = body if isinstance(body, dict) else {}
    shown = {k: mask_text(body[k], 80) for k in SHOWN_KEYS if isinstance(body.get(k), (str, int, bool))}
    return {"method": method, "route": route, "path": mask_text(path, 300), "query": sorted(query or {})[:20],
            "body_keys": sorted(str(k) for k in body)[:30], "shown": shown}


def records_tail(project: Project | None, n: int = 8) -> list[dict[str, Any]]:
    """The last ledger records of a project, by sequence and kind: what was happening when it failed."""
    if project is None:
        return []
    try:
        records = project.ledger().records()[-n:]
    except (OSError, ValueError):
        return []
    return [{"seq": r.get("seq"), "kind": (r.get("event") or {}).get("kind"), "at": (r.get("event") or {}).get("at")}
            for r in records if isinstance(r, dict)]


def _clean(value: Any, depth: int = 0) -> Any:
    """A context value masked and cut, however deep."""
    if depth > 5:
        return None
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {str(k)[:80]: _clean(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_clean(v, depth + 1) for v in list(value)[-MAX_LINES:]]
    return value if isinstance(value, (int, float, bool)) or value is None else mask_text(value)


# -- the store ----------------------------------------------------------------------------------------------

def heal_dir(factory: Factory) -> Path:
    return Path(factory.home) / "heal"


def _dir(factory: Factory) -> Path:
    return heal_dir(factory) / "incidents"


def _lock(factory: Factory) -> Path:
    return heal_dir(factory) / "incidents.lock"


def _path(factory: Factory, iid: str) -> Path:
    if not re.fullmatch(r"I-\d{4,9}", iid or ""):
        raise KeyError(f"no incident {iid}")
    return _dir(factory) / f"{iid}.json"


def _all(factory: Factory) -> list[dict[str, Any]]:
    folder = _dir(factory)
    if not folder.is_dir():
        return []
    out = []
    for f in sorted(folder.glob("I-*.json")):
        doc = read_json(f, None)
        if isinstance(doc, dict):
            out.append(doc)
    return out


def get(factory: Factory, iid: str) -> dict[str, Any]:
    doc = read_json(_path(factory, iid), None)
    if not isinstance(doc, dict):
        raise KeyError(f"no incident {iid}")
    return doc


def ledger_of(factory: Factory, pid: str | None) -> Project:
    """The ledger an incident is recorded in: its project's, or the factory's own canon's."""
    from kernel.learn import FACTORY_PID, factory_project

    if pid and pid != FACTORY_PID:
        return factory.project(pid)
    return factory_project(factory)


def _check_signer(person: str | None, persona: str | None) -> None:
    if person is None:
        return
    if not is_person(person) or persona not in PERSONAS:
        raise IncidentRefused(f"{person!r} is not a person with a persona: an incident a person reports is signed")


def _seen_again(factory: Factory, same: dict[str, Any], ctx: Any, now: str, person: str | None,
                persona: str | None) -> dict[str, Any]:
    """One more occurrence on an open incident: counted, its context kept; a person's report is recorded."""
    same["count"] = int(same.get("count", 1)) + 1
    same["last_seen"] = now
    same["occurrences"] = (same.get("occurrences") or [])[-19:] + [{"at": now, "context": ctx}]
    write_json(_path(factory, same["id"]), same)
    if person:
        ledger_of(factory, same.get("project")).log("incident_seen", {
            "id": same["id"], "fingerprint": same["fingerprint"], "count": same["count"], "person": person,
            "persona": persona})
    return same | {"new": False}


def open_incident(factory: Factory, *, kind: str, where: str, message: str = "", error_class: str = "",
                  project: str | None = None, context: dict[str, Any] | None = None, person: str | None = None,
                  persona: str | None = None, by: str = "the cockpit", words: str = "") -> dict[str, Any]:
    """Open an incident, or count one more occurrence on the open incident with the same fingerprint and scope.
    Returns the incident with ``new`` saying which. ``person`` signs one a person reported."""
    if kind not in KINDS:
        raise IncidentRefused(f"an incident's kind is one of {', '.join(KINDS)}")
    _check_signer(person, persona)
    pid = project if project and project != "_factory" else None
    if pid is not None:
        factory.project(pid)                                   # KeyError: no such project
    fp = fingerprint(kind, where, error_class, message)
    now = factory.clock.stamp()
    ctx = _clean(dict(context or {}))
    signer = {"person": person, "persona": persona} if person else {}
    with records_lock(_lock(factory)):
        same = next((i for i in reversed(_all(factory)) if i["fingerprint"] == fp and i.get("project") == pid
                     and i["state"] not in DONE), None)
        if same is not None:
            return _seen_again(factory, same, ctx, now, person, persona)
        doc = _new_doc(factory, {"fingerprint": fp, "kind": kind, "where": mask_text(where, 200),
                                 "error_class": mask_text(error_class, 80), "message": mask_text(message, 600),
                                 "project": pid, "opened": now, "last_seen": now, "by": by,
                                 "reported_by": signer or None, "words": mask_text(words, 2000) if words else None,
                                 "context": ctx})
    ledger_of(factory, pid).log("incident_opened", {
        "id": doc["id"], "fingerprint": fp, "kind": kind, "class": doc["class"], "where": doc["where"],
        "summary": doc["summary"][:300], "by": by, **signer})
    return doc | {"new": True}


def _new_doc(factory: Factory, fields: dict[str, Any]) -> dict[str, Any]:
    """A new incident's file, numbered after the last one, with its class and its summary in plain words."""
    from kernel.immune import classify

    n = max([int(i["id"][2:]) for i in _all(factory)] or [0]) + 1
    doc: dict[str, Any] = {"id": f"I-{n:04d}", "state": "open", "count": 1, "occurrences": [], "history": [],
                           **fields}
    doc["class"] = classify(doc)["id"]
    doc["summary"] = summary_line(doc)
    write_json(_path(factory, doc["id"]), doc)
    return doc


def summary_line(doc: dict[str, Any]) -> str:
    """What happened, in plain words: never a bare exception name."""
    from kernel.immune import classify

    cls = classify(doc)
    head = cls.get("title") or KIND_WORDS.get(doc["kind"], "Something went wrong")
    where = doc.get("where") or ""
    said = (doc.get("message") or "").strip()
    if cls["id"] != "unknown":
        return f"{head} ({where})." if where else f"{head}."
    tail = f": {said[:240]}" if said and not re.fullmatch(r"(?i)internal error: \w+", said) else "."
    return f"{head} ({where}){tail}" if where else f"{head}{tail}"


def incidents(factory: Factory, *, pid: str | None = None, state: str | None = None,
              limit: int = LIST_LIMIT) -> list[dict[str, Any]]:
    """The incidents, newest first: of one project (``pid``; the factory's own with ``_factory``), or all."""
    rows = _all(factory)
    if pid is not None:
        want = None if pid == "_factory" else pid
        rows = [i for i in rows if i.get("project") == want]
    if state is not None:
        rows = [i for i in rows if i["state"] == state]
    return list(reversed(rows))[:limit]


def counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    found = collections.Counter(i["state"] for i in rows)
    return {s: found.get(s, 0) for s in STATES} | {"all": len(rows)}


def update(factory: Factory, iid: str, *, state: str | None = None, event: str, person: str, persona: str,
           note: str = "", **fields: Any) -> dict[str, Any]:
    """Move an incident on (or add to it), signed by a person, and record it in its ledger."""
    _check_signer(person, persona)
    if not person:
        raise IncidentRefused("a person signs a step on an incident")
    if state is not None and state not in STATES:
        raise IncidentRefused(f"an incident's state is one of {', '.join(STATES)}")
    path = _path(factory, iid)
    with updating_json(path, None, lock=_lock(factory)) as doc:
        if not isinstance(doc, dict):
            raise KeyError(f"no incident {iid}")
        before = doc["state"]
        if state is not None:
            doc["state"] = state
        doc.update({k: _clean(v) if k not in ("resolution", "investigation", "fix") else v for k, v in fields.items()})
        doc["history"] = (doc.get("history") or [])[-49:] + [{
            "at": factory.clock.stamp(), "event": event, "from": before, "to": doc["state"], "person": person,
            "persona": persona, "note": mask_text(note, 500)}]
        out = dict(doc)
    ledger_of(factory, out.get("project")).log(event, {"id": iid, "fingerprint": out["fingerprint"],
                                                       "state": out["state"], "person": person, "persona": persona,
                                                       **({"note": mask_text(note, 300)} if note else {})})
    return out


def resolve(factory: Factory, iid: str, *, how: dict[str, Any], person: str, persona: str,
            note: str = "", anyway: bool = False) -> dict[str, Any]:
    """An incident is fixed, and what fixed it (``how``: a remedy taken, a retry that worked, an agent's fix, a
    person's own act) is proposed as a remedy for the same fingerprint next time (kernel/immune.py). A failed
    check's incident is not closed while that check's last result still fails, unless ``anyway`` with a note."""
    from kernel import immune

    doc = get(factory, iid)
    if doc["state"] in DONE:
        raise IncidentRefused(f"{iid} is already {doc['state']}")
    failing = still_failing(factory, doc)
    if failing and not (anyway and note.strip()):
        raise IncidentRefused(f"{iid}'s check {failing} still fails on its last run: run it again on Health once "
                              "the cause is fixed, then mark it fixed (or close it anyway, saying why)")
    action = immune.resolution_action(how)
    started = doc.get("opened")
    out = update(factory, iid, state="fixed", event="incident_resolved", person=person, persona=persona, note=note,
                 resolution={"how": action, "by": person, "persona": persona, "at": factory.clock.stamp(),
                             "opened": started})
    remedy = immune.learn(factory, out, action, person=person, persona=persona)
    return out | {"remedy": remedy}


def still_failing(factory: Factory, doc: dict[str, Any]) -> str | None:
    """The check a check_failed incident is about, when its last recorded result is still failed; else None."""
    where = str(doc.get("where") or "")
    if doc.get("kind") != "check_failed" or not where.startswith("check:") or not doc.get("project"):
        return None
    from kernel.checks import store as cstore

    key = where.removeprefix("check:")
    try:
        last = (cstore.results(factory.project(doc["project"]), key, 1) or [{}])[-1]
    except (KeyError, OSError, ValueError):
        return None
    return key if last.get("verdict") == "failed" else None


def mark_learned(factory: Factory, fp: str, rid: str) -> list[str]:
    """Every fixed incident of this fingerprint whose resolution became the approved remedy ``rid``: learned."""
    changed = []
    with records_lock(_lock(factory)):
        for doc in _all(factory):
            if doc["fingerprint"] == fp and doc["state"] == "fixed":
                doc["state"], doc["learned"] = "learned", rid
                write_json(_path(factory, doc["id"]), doc)
                changed.append(doc["id"])
    return changed


def public(doc: dict[str, Any], *, full: bool = True) -> dict[str, Any]:
    """An incident as the cockpit shows it: without the occurrences' contexts unless ``full``."""
    out = {k: v for k, v in doc.items() if k != "occurrences"}
    out["occurrences"] = len(doc.get("occurrences") or [])
    if not full:
        out.pop("context", None)
        out.pop("history", None)
    return out
