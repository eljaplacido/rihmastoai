"""Who authorised which targets, until when: the scope dynamic and agentic red teaming runs inside.

Rihmasto red-teams only what it runs itself (D-0014). Before any request is sent, `check` answers
whether a target may be reached, and refuses, with the reason recorded in the project's ledger,
a target that is

1. **not on loopback**: only an IP literal in 127.0.0.0/8 or ::1, over http or https, with no user
   name or password in the URL. A host name is refused, since it could resolve elsewhere;
2. **not something the factory deployed or runs**: a `base_url` in the slot state the paved roads
   keep (`kernel/roads.py`, read by `kernel/deliver.py`: `envs/<environment>/<slot>.json`), or a
   surface the caller itself started for this run (the embed server, the assistant), on loopback;
3. **not in an unexpired scope**: a person with the `it` or `compliance` persona authorised it,
   with a reason and an expiry, and nobody revoked it.

A scope names its targets as environments (`staging`), a slot of one (`staging/twin`), a factory
surface (`embed`, `assistant`), or a loopback URL. A URL is bound, when the scope is authorised, to
the environment and slot the factory runs there: it never follows the port to another deployment.
It lasts at most 31 days, counted in UTC whatever the expiry's time zone. Scopes live in the ledger
only (`redteam_scope_authorised`, `redteam_scope_revoked`), so a scope cannot be edited without
breaking the hash chain, and a ledger that does not verify authorises nothing. Every record is
checked again when it is read, as `authorise` checks it (a named person, the `it` or `compliance`
persona, a reason, valid targets, at most 31 days): a record written straight into the ledger that
breaks a rule authorises nothing.

**What counts as deployed.** A slot under `envs/<environment>/<slot>.json` for one of the factory's
own environments and slots, labelled by its path (a file that claims another environment is not
taken at its word), whose process, when it names one, still runs. A surface counts only through
the handle `kernel/redteam/started.py` issued when the factory started it: a caller cannot declare a
surface's address.

**Who authorises.** A name that is one of the factory's own actors, or holds such a word (`Claude
Code`, `factory autopilot`, `LLM agent`), is not a person. The persona is the caller's word: the
factory keeps no register of who holds which persona, and the report names who authorised.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import os
import re
import urllib.parse
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from kernel.canon import DecisionRefused
from kernel.people import NOT_A_PERSON, is_person
from kernel.redteam.started import Started, issued
from kernel.roads import ENVIRONMENTS, SLOTS, slot_state

AUTHORISERS = ("it", "compliance")
SURFACES = ("embed", "assistant")
MAX_DAYS = 31
AUTHORISED = "redteam_scope_authorised"
REVOKED = "redteam_scope_revoked"
REFUSED = "redteam_target_refused"
# Words that make a name a machine's, not a person's (beside kernel.people's own list).
MACHINE_WORDS = frozenset(NOT_A_PERSON | {"ai", "gpt", "copilot", "opus", "sonnet", "haiku", "automation", "script",
                                         "pipeline", "robot", "daemon", "cron", "service", "agentic", "redteam"})
_TOKEN = re.compile(r"[a-z]+")
STILL_ACTIVE = 259


class ScopeRefused(DecisionRefused):
    """A scope that may not be recorded, or a target that may not be reached. Nothing was sent."""


@dataclass(frozen=True)
class Permit:
    """A target the red team may reach now, and the scope that allows it."""

    scope: str
    target: str
    base_url: str
    label: str
    environment: str | None
    slot: str | None
    release: Any
    person: str
    persona: str
    expires: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now(project: Any) -> dt.datetime:
    now: dt.datetime = project.factory.clock.now()
    return now if now.tzinfo else now.replace(tzinfo=dt.UTC)


def _stamp(moment: dt.datetime) -> str:
    return moment.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _expiry(expires: object, now: dt.datetime) -> dt.datetime:
    """An ISO date (valid through that day, UTC) or date-time, in the future and at most MAX_DAYS ahead."""
    try:
        if isinstance(expires, dt.datetime):
            until = expires
        elif isinstance(expires, dt.date):
            until = dt.datetime.combine(expires, dt.time(23, 59, 59))
        elif len(str(expires)) == 10:
            until = dt.datetime.combine(dt.date.fromisoformat(str(expires)), dt.time(23, 59, 59))
        else:
            until = dt.datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScopeRefused(f"the expiry must be a date (YYYY-MM-DD) or a date and time, got {expires!r}") from exc
    until = until if until.tzinfo else until.replace(tzinfo=dt.UTC)
    if until <= now:
        raise ScopeRefused(f"the expiry {_stamp(until)} is not in the future")
    if _days(until, now) > MAX_DAYS:
        raise ScopeRefused(f"a scope lasts at most {MAX_DAYS} days; authorise again when it ends")
    return until


def _days(until: dt.datetime, start: dt.datetime) -> int:
    """Whole days from ``start`` to ``until``, by their dates in UTC (an offset cannot stretch a scope)."""
    return (until.astimezone(dt.UTC).date() - start.astimezone(dt.UTC).date()).days


def named_person(name: object) -> bool:
    """A person who may authorise red teaming: `kernel.people.is_person`, at least two letters, and no
    word of the name one of a machine's (`Claude Code`, `factory autopilot`, `the model`)."""
    if not is_person(name) or not isinstance(name, str):
        return False
    words = _TOKEN.findall(name.lower())
    return sum(len(w) for w in words) >= 2 and not any(w in MACHINE_WORDS for w in words)


def _loopback_origin(url: str) -> str:
    """`scheme://host:port` of a loopback URL. Raises ScopeRefused for anything else."""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise ScopeRefused(f"{_redact(url)} is not a URL the red team can judge") from exc
    if parts.scheme not in ("http", "https"):
        raise ScopeRefused(f"{_redact(url)}: only http and https targets are red-teamed")
    if parts.username is not None or parts.password is not None:
        raise ScopeRefused(f"{_redact(url)}: a target URL may not carry a user name or password")
    host = parts.hostname or ""
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise ScopeRefused(f"{_redact(url)} is not on loopback: the red team reaches only 127.0.0.0/8 or ::1 "
                           "by address, never a host name")
    port = port or (443 if parts.scheme == "https" else 80)
    shown = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{shown}:{port}"


def _redact(url: str) -> str:
    """A URL fit for the ledger: no user information, no query, no fragment."""
    try:
        parts = urllib.parse.urlsplit(str(url))
        netloc = parts.netloc.rsplit("@", 1)[-1]
        return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, "", ""))[:200]
    except ValueError:
        return "an unreadable URL"


def _label(target: object) -> str:
    """A scope target in its stored form. Raises ScopeRefused for one the red team may never reach."""
    text = str(target or "").strip()
    env, _, slot = text.partition("/")
    if text in ENVIRONMENTS or text in SURFACES or (env in ENVIRONMENTS and slot in SLOTS):
        return text
    if "://" in text:
        return _loopback_origin(text)
    raise ScopeRefused(f"{text!r} is not a target: name an environment ({', '.join(ENVIRONMENTS)}), "
                       f"an environment/slot, a surface ({', '.join(SURFACES)}) or a loopback URL")


def _bind(project: Any, labels: list[str]) -> dict[str, str]:
    """Each URL target bound to the environment and slot the factory runs there now."""
    bound: dict[str, str] = {}
    for label in (x for x in labels if "://" in x):
        here = [d for d in deployed(project) if d["environment"] and _origin_or_none(d["base_url"]) == label]
        if not here:
            raise ScopeRefused(f"nothing the factory deployed runs at {label}: name its environment instead")
        bound[label] = f"{here[0]['environment']}/{here[0]['slot']}"
    return bound


def authorise(project: Any, targets: Iterable[object], person: str, persona: str, reason: str,
              expires: object) -> dict[str, Any]:
    """A person with the `it` or `compliance` persona authorises red teaming of ``targets`` until
    ``expires``, for ``reason``. Recorded in the project's ledger; returns the scope."""
    if not named_person(person):
        raise ScopeRefused(f"{person!r} is not a person; authorising a red team is a person's decision")
    if persona not in AUTHORISERS:
        raise ScopeRefused(f"a {persona} may not authorise red teaming; {', '.join(AUTHORISERS)} may")
    if not str(reason or "").strip():
        raise ScopeRefused("authorising a red team needs a reason")
    labels = sorted({_label(t) for t in (targets or [])})
    if not labels:
        raise ScopeRefused("a scope names at least one target")
    until = _expiry(expires, _now(project))
    bound = _bind(project, labels)
    number = len(project.ledger().of_kind(AUTHORISED)) + 1
    scope: dict[str, Any] = {"scope": f"RT-SCOPE-{number:03d}", "targets": labels, "person": person,
                             "persona": persona, "reason": str(reason).strip(), "expires": _stamp(until),
                             "at": project.factory.clock.stamp()}
    if bound:
        scope["bound"] = bound
    project.log(AUTHORISED, scope)
    return scope


def revoke(project: Any, scope_id: str, *, person: str, persona: str, reason: str) -> dict[str, Any]:
    """End a scope before its expiry. The same people who may authorise one may revoke it."""
    if not named_person(person) or persona not in AUTHORISERS:
        raise ScopeRefused(f"revoking a scope is for a named person with the {' or '.join(AUTHORISERS)} persona")
    if not str(reason or "").strip():
        raise ScopeRefused("revoking a scope needs a reason")
    if scope_id not in {s.get("scope") for s in scopes(project)}:
        raise KeyError(f"no scope {scope_id!r}")
    record = {"scope": scope_id, "person": person, "persona": persona, "reason": str(reason).strip(),
              "at": project.factory.clock.stamp()}
    project.log(REVOKED, record)
    return record


def _moment(value: object) -> dt.datetime:
    moment = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


def _who_and_why(s: Mapping[str, Any]) -> str | None:
    if not named_person(s.get("person")):
        return "it names no person"
    if s.get("persona") not in AUTHORISERS:
        return f"a {s.get('persona')} may not authorise red teaming"
    if not str(s.get("reason") or "").strip():
        return "it gives no reason"
    return None


def _what(s: Mapping[str, Any]) -> str | None:
    targets = s.get("targets")
    if not isinstance(targets, list) or not targets or not str(s.get("scope") or "").startswith("RT-SCOPE-"):
        return "it names no scope or no target"
    try:
        labels = [_label(t) for t in targets]
    except ScopeRefused as exc:
        return str(exc)
    unbound = [x for x in labels if "://" in x and x not in (s.get("bound") or {})]
    return f"its URL target {unbound[0]} is not bound to a deployment" if unbound else None


def invalid(s: Mapping[str, Any]) -> str | None:
    """Why a scope record does not hold, checked again as `authorise` checks it; None when it holds."""
    try:
        until, at = _moment(s["expires"]), _moment(s["at"])
    except (KeyError, TypeError, ValueError):
        return "its expiry or the time it was authorised is missing or unreadable"
    if _days(until, at) > MAX_DAYS:
        return f"it lasts more than {MAX_DAYS} days"
    return _who_and_why(s) or _what(s)


def scopes(project: Any, *, active: bool = False) -> list[dict[str, Any]]:
    """Every scope in the ledger with its state (active, expired, revoked, or invalid with why);
    ``active`` keeps the live ones."""
    records = project.ledger().of_kind(AUTHORISED, REVOKED)
    revoked = {(r["event"]["payload"] or {}).get("scope") for r in records if r["event"]["kind"] == REVOKED}
    now, out = _now(project), []
    for r in records:
        if r["event"]["kind"] != AUTHORISED:
            continue
        s = dict(r["event"]["payload"] or {})
        why = invalid(s)
        if why is not None:
            s["state"], s["why"] = "invalid", why
        else:
            s["state"] = "revoked" if s["scope"] in revoked else ("expired" if _moment(s["expires"]) <= now
                                                                    else "active")
        if not active or s["state"] == "active":
            out.append(s)
    return out


def alive(pid: object) -> bool:
    """Whether the process ``pid`` still runs (never signalled: on Windows only queried)."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _slots(project: Any) -> list[dict[str, Any]]:
    """The slots the factory runs: its own environments and slots, labelled by their path, whose process
    (when the slot names one) is alive."""
    out = []
    for env in ENVIRONMENTS:
        for slot in SLOTS:
            state = slot_state(project, env, slot)
            if not isinstance(state, dict) or not state.get("base_url"):
                continue
            if state.get("environment", env) != env or state.get("slot", slot) != slot:
                continue   # a file that claims another place is not taken at its word
            if "pid" in state and not alive(state["pid"]):
                continue   # the process the factory started is gone: whatever answers there is not it
            out.append({"base_url": state["base_url"], "labels": [env, f"{env}/{slot}"], "environment": env,
                        "slot": slot, "release": state.get("release")})
    return out


def deployed(project: Any, running: Mapping[str, Started] | None = None) -> list[dict[str, Any]]:
    """What the factory deployed (its running slots) and the surfaces it started, with labels."""
    out = _slots(project)
    for surface, handle in (running or {}).items():
        if surface not in SURFACES:
            raise ScopeRefused(f"{surface!r} is not a surface the factory runs ({', '.join(SURFACES)})")
        if not isinstance(handle, Started) or handle.surface != surface or not issued(handle):
            raise ScopeRefused(f"the {surface} named here is not one the factory started for this run: hand over "
                               "the handle kernel.redteam.started.register gave for the server it started")
        out.append({"base_url": handle.base_url, "labels": [surface], "environment": None, "slot": None,
                    "release": None})
    return out


def _refuse(project: Any, target: str, reason: str, record: bool) -> ScopeRefused:
    if record:
        project.log(REFUSED, {"target": _redact(target), "reason": reason})
    return ScopeRefused(reason)


def refused(project: Any, target: str, reason: str) -> ScopeRefused:
    """A refusal of ``target``, recorded in the ledger; the caller raises it."""
    return _refuse(project, target, reason, True)


def loopback_origin(url: str) -> str:
    """`scheme://host:port` of a loopback URL given by IP address; ScopeRefused for anything else."""
    return _loopback_origin(url)


def _origin_or_none(url: str) -> str | None:
    try:
        return _loopback_origin(url)
    except ScopeRefused:
        return None   # a slot on another address is not red-teamed, whatever its scope says


def _matches(project: Any, origin: str, running: Mapping[str, Started] | None) -> list[dict[str, Any]]:
    return [d for d in deployed(project, running) if _origin_or_none(d["base_url"]) == origin]


def _names(scope: Mapping[str, Any], label: str, d: Mapping[str, Any]) -> bool:
    """Whether the scope names this deployment by ``label``; a URL only for what it was bound to."""
    if label not in scope["targets"]:
        return False
    return "://" not in label or (scope.get("bound") or {}).get(label) == f"{d['environment']}/{d['slot']}"


def check(project: Any, target: str, *, running: Mapping[str, Started] | None = None,
          record: bool = True) -> Permit:
    """May the red team send a request to ``target`` now? A Permit, or ScopeRefused (recorded)."""
    try:
        origin = _loopback_origin(str(target))
        matches = _matches(project, origin, running)
    except ScopeRefused as exc:
        raise _refuse(project, str(target), str(exc), record) from None
    if not matches:
        raise _refuse(project, target, f"{origin} is not a base_url the factory deployed or runs", record)
    if not project.ledger().verify().intact:
        raise _refuse(project, target, "the project's ledger does not verify: no scope can be trusted", record)
    for scope in scopes(project, active=True):
        for d in matches:
            label = next((x for x in [*d["labels"], origin] if _names(scope, x, d)), None)
            if label:
                return Permit(scope["scope"], _redact(target), d["base_url"], label, d["environment"], d["slot"],
                              d["release"], scope["person"], scope["persona"], scope["expires"])
    names = ", ".join(sorted({x for d in matches for x in d["labels"]}))
    raise _refuse(project, target, f"no unexpired scope names {names} ({origin})", record)
