"""Which checks a project runs, and what they found (FR-CHK1).

- ``checks.json`` in the project holds the enabled checks: each by its key (a kind, or ``kind:name``), with its
  settings, its schedule (``every``), what a failure does (``on_fail``: log a signal, open a change proposal)
  and who enabled it (person, persona and, with access enforced, the verified identity).
- ``checks/results.json`` keeps each check's last results (50), with their evidence.
- The ledger has ``check_enabled``, ``check_disabled`` and ``check_ran`` (the verdict and a one-line summary,
  never a tool's whole output), each with who; a scheduled run names the person who enabled it.

Who: a check that runs the project's own code (tests, custom, repo gate) is enabled and run by a persona the
console allows on the project (kernel/console.py); any other by a developer, IT, operations, compliance or a
product owner. A scheduled run acts with the rights of the person who enabled the check, checked again
against the access file before every run, as an automation's are: a grant IT removed stops it, and the result
says so (not measured).
"""

from __future__ import annotations

import datetime as dt
import http.client
import re
import subprocess
import threading
from typing import Any

from kernel import access as kaccess
from kernel.canon import DecisionRefused
from kernel.checks import ENABLERS, Check, Ctx, catalogue, not_measured
from kernel.people import PERSONAS, SIGNER, Identity, is_person
from kernel.store import Factory, Project, updating_json

KEY = re.compile(r"([a-z_]{2,20})(?::([a-z0-9][a-z0-9-]{0,30}))?\Z")
EVERY = re.compile(r"(\d{1,4})([mhd])\Z")
ON_FAIL = ("signal", "change")
MAX_RESULTS = 50
MAX_TEXT = 2000
_RUNNING: set[tuple[str, str]] = set()
_LOCK = threading.Lock()


class ChecksRefused(DecisionRefused):
    """A change to a project's checks, or a run, the rules refuse (403, exit 2)."""


def check_of(key: str) -> tuple[Check, str]:
    m = KEY.match(str(key or ""))
    known = catalogue()
    if not m or m.group(1) not in known:
        raise ValueError(f"a check is one of {', '.join(known)}, optionally with a name (probe:prod), got {key!r}")
    return known[m.group(1)], key


def enabled(project: Project) -> dict[str, dict[str, Any]]:
    kept = project.read("checks.json", {}) or {}
    return dict(kept.get("enabled") or {}) if isinstance(kept, dict) else {}


def minutes(every: str | None) -> int | None:
    if not every:
        return None
    m = EVERY.match(str(every))
    if not m or int(m.group(1)) < 1:
        raise ValueError("every is a number and m, h or d: 15m, 6h, 1d")
    return int(m.group(1)) * {"m": 1, "h": 60, "d": 1440}[m.group(2)]


def _value(key: str, value: Any) -> Any:
    if isinstance(value, bool) or (isinstance(value, int) and 0 <= value < 10**7):
        return value
    if isinstance(value, str) and len(value) <= MAX_TEXT:
        return value.strip()
    if isinstance(value, list) and len(value) <= 50 and all(isinstance(v, str) and len(v) <= 200 for v in value):
        return [v.strip() for v in value]
    raise ValueError(f"{key} is a word, a whole number, true or false, or a short list of words")


def _config(check: Check, config: Any) -> dict[str, Any]:
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError("a check's settings are an object")
    unknown = [k for k in config if k not in check.options]
    if unknown:
        takes = ", ".join(check.options) or "no settings"
        raise ValueError(f"the {check.label} takes {takes}, not {', '.join(unknown)}")
    out = {k: _value(k, v) for k, v in config.items() if v not in (None, "")}
    missing = [k for k in check.needs if not out.get(k)]
    if missing:
        raise ValueError(f"the {check.label} needs {', '.join(missing)}")
    from kernel.checks import infra_settings  # a setting naming no usable target is refused (FR-ITO2)

    if bad := infra_settings.problems(check.kind, out):
        raise ValueError(f"the {check.label}'s settings: " + "; ".join(bad))
    return out


def _may(project: Project, check: Check, person: str, persona: str) -> None:
    if not is_person(person):
        raise ChecksRefused(f"{person!r} is not a person: a check is enabled and run by a named person")
    if persona not in PERSONAS:
        raise ChecksRefused(f"persona must be one of {', '.join(PERSONAS)}, got {persona!r}")
    if check.runs_code:
        from kernel.console import check_persona

        check_persona(project, person, persona)
    elif persona not in ENABLERS:
        raise ChecksRefused(f"checks are set and run by {', '.join(ENABLERS)}, not a {persona}")


def _by(project: Project, person: str, persona: str) -> dict[str, Any]:
    signer = SIGNER.get()
    held = signer is not None and signer.name == person
    return {"person": person, "persona": persona, "at": project.factory.clock.stamp(),
            "identity": signer.id if held and signer else None,
            "groups": list(signer.groups) if held and signer else []}


def may(project: Project, key: str, person: str, persona: str) -> None:
    """Refused unless ``person`` as ``persona`` may set and run ``key`` on ``project`` (nothing is written)."""
    _may(project, check_of(key)[0], person, persona)


def sign_on(project: Project, person: str, persona: str) -> None:
    """With access enforced, the signing identity must hold the persona on ``project`` too (a change made on
    several projects at once is signed on each)."""
    access = kaccess.load(project.factory)
    if access.enforced:
        kaccess.sign(access, SIGNER.get(), person, persona, project.pid)


def enable(project: Project, key: str, *, person: str, persona: str, config: Any = None, every: str | None = None,
           on_fail: list[str] | None = None) -> dict[str, Any]:
    """Enable (or change) a check on a project, signed; recorded as ``check_enabled``."""
    check, key = check_of(key)
    _may(project, check, person, persona)
    minutes(every)
    if on_fail is not None and (not isinstance(on_fail, list) or any(x not in ON_FAIL for x in on_fail)):
        raise ValueError(f"on_fail is a list of {', '.join(ON_FAIL)}")
    settings, fails = _config(check, config), sorted(set(on_fail or []))
    entry = {"kind": check.kind, "config": settings, "every": every or None, "on_fail": fails,
             "by": _by(project, person, persona)}
    with updating_json(project.path("checks.json"), {}) as kept:
        kept.setdefault("enabled", {})[key] = entry
    project.log("check_enabled", {"check": key, "kind": check.kind, "every": entry["every"],
                                  "settings": sorted(settings), "on_fail": fails, "person": person,
                                  "persona": persona})
    return {"check": key, **entry}


def disable(project: Project, key: str, *, person: str, persona: str) -> dict[str, Any]:
    check, key = check_of(key)
    _may(project, check, person, persona)
    with updating_json(project.path("checks.json"), {}) as kept:
        if key not in (kept.get("enabled") or {}):
            raise ValueError(f"{key} is not enabled on {project.pid}")
        del kept["enabled"][key]
    project.log("check_disabled", {"check": key, "person": person, "persona": persona})
    return {"check": key, "enabled": False}


def results(project: Project, key: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    kept = project.read("checks/results.json", {}) or {}
    rows = kept.get(key, []) if key else [r for v in kept.values() for r in v]
    return sorted(rows, key=lambda r: str(r.get("at")))[-limit:]


def running(project: Project, key: str) -> bool:
    with _LOCK:
        return (project.pid, key) in _RUNNING


def _keep(project: Project, key: str, row: dict[str, Any]) -> None:
    with updating_json(project.path("checks", "results.json"), {}) as kept:
        kept[key] = (kept.get(key) or [])[-(MAX_RESULTS - 1):] + [row]


def _on_fail(project: Project, key: str, entry: dict[str, Any], row: dict[str, Any], before: str | None) -> list[str]:
    """What a failure does, once per change from another verdict to failed: never once per run."""
    if row["verdict"] != "failed" or before == "failed":
        return []
    by, done = entry["by"], []
    text = f"Check {key} failed on {project.pid}: {row['summary']}"
    if "signal" in entry.get("on_fail", []):
        from kernel.signals import receive

        receive(project.factory, text, channel="monitoring", source=f"check {key}", person=by["person"],
                persona=by["persona"], ref=f"check:{project.pid}:{key}")
        done.append("signal")
    if "change" in entry.get("on_fail", []):
        from kernel.change import submit

        submit(project, persona=by["persona"], person=by["person"], text=text)
        done.append("change")
    return done


def _measure(project: Project, check: Check, entry: dict[str, Any], person: str, persona: str,
             timeout: int | None) -> dict[str, Any]:
    ctx = Ctx(project, dict(entry.get("config") or {}), person=person, persona=persona, timeout=timeout or 600)
    try:
        return check.run(ctx)
    except (ValueError, LookupError, OSError, RuntimeError, PermissionError, subprocess.SubprocessError,
            http.client.HTTPException) as exc:
        return not_measured(f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # a check that breaks is recorded, never left due to block the others
        return not_measured(f"the check itself broke ({type(exc).__name__}: {exc}); its result is kept so the "
                            "others still run")


def run(project: Project, key: str, *, person: str, persona: str, via: str = "person",
        timeout: int | None = None) -> dict[str, Any]:
    """Run an enabled check now and record its result; returns the result as kept."""
    check, key = check_of(key)
    entry = enabled(project).get(key)
    if entry is None:
        raise ValueError(f"{key} is not enabled on {project.pid}: enable it first (rihmasto checks enable)")
    _may(project, check, person, persona)
    with _LOCK:
        if (project.pid, key) in _RUNNING:
            raise ChecksRefused(f"{key} is running on {project.pid} now")
        _RUNNING.add((project.pid, key))
    started = dt.datetime.now(dt.UTC)
    try:
        out = _measure(project, check, entry, person, persona, timeout)
    finally:
        with _LOCK:
            _RUNNING.discard((project.pid, key))
    return record(project, key, entry, out, person=person, persona=persona, via=via,
                  seconds=(dt.datetime.now(dt.UTC) - started).total_seconds())


def record(project: Project, key: str, entry: dict[str, Any], out: dict[str, Any], *, person: str, persona: str,
           via: str, seconds: float = 0.0) -> dict[str, Any]:
    before = (results(project, key, 1) or [{}])[-1].get("verdict")
    row = {**out, "check": key, "kind": entry["kind"], "at": project.factory.clock.stamp(),
           "seconds": round(seconds, 2), "by": {"person": person, "persona": persona}, "via": via}
    _keep(project, key, row)
    row["on_fail"] = _on_fail(project, key, entry, row, before)
    project.log("check_ran", {"check": key, "kind": entry["kind"], "verdict": row["verdict"],
                              "summary": row["summary"][:300], "person": person, "persona": persona, "via": via,
                              **({"on_fail": row["on_fail"]} if row["on_fail"] else {})})
    from kernel import itops_heal  # a failing infrastructure check opens its incident with its evidence (FR-ITO1)

    incident = itops_heal.on_result(project, key, entry, row, before)
    return row | ({"incident": incident} if incident else {})


# -- the schedule -------------------------------------------------------------------------------------------

def _parse(stamp: Any) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def due(factory: Factory) -> list[tuple[Project, str]]:
    """Each enabled check whose schedule says it should run now."""
    now = factory.clock.now()
    out = []
    for project in factory.projects():
        for key, entry in enabled(project).items():
            every = minutes(entry.get("every")) if entry.get("every") else None
            if every is None or running(project, key):
                continue
            last = (results(project, key, 1) or [{}])[-1].get("at")
            at = _parse(last)
            if at is None or (now - at).total_seconds() >= every * 60:
                out.append((project, key))
    return out


def _rights(project: Project, entry: dict[str, Any]) -> Identity | None:
    access = kaccess.load(project.factory)
    if not access.enforced:
        return None
    by = entry["by"]
    if not by.get("identity"):
        raise ChecksRefused("access is enforced and no verified identity enabled this check: its owner enables "
                            "it again, signed in")
    ident = Identity(by["identity"], by["person"], tuple(by.get("groups") or ()))
    kaccess.sign(access, ident, by["person"], by["persona"], project.pid)
    return ident


def scheduled(project: Project, key: str) -> dict[str, Any]:
    """One scheduled run, with the rights of the person who enabled the check, checked again now."""
    from kernel import access_isolation as kisolation

    entry = enabled(project)[key]
    by = entry["by"]
    try:
        ident = _rights(project, entry)
    except DecisionRefused as exc:            # access refused, or no verified identity enabled it
        return record(project, key, entry, not_measured(f"the scheduled run did not start: {exc}"),
                      person=by["person"], persona=by["persona"], via="schedule")
    with kaccess.signing(ident), kisolation.serving(project.factory):
        try:
            return run(project, key, person=by["person"], persona=by["persona"], via="schedule")
        except (DecisionRefused, PermissionError) as exc:
            return record(project, key, entry, not_measured(f"the scheduled run was refused: {exc}"),
                          person=by["person"], persona=by["persona"], via="schedule")


def tick(factory: Factory) -> list[dict[str, Any]]:
    """Run every check that is due (the cockpit's ticker, or ``rihmasto checks tick`` from cron). One check that
    breaks never stops the others due in the same tick."""
    from kernel.checks import tick_guard

    return [tick_guard.one(p, k, scheduled) for p, k in due(factory)]
