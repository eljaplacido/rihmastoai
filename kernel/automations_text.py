"""Automations in plain words (FR-AUT1): the summary a person reads before saving one, what a dry run says it
would do, and the templates the builder starts from.

    "Every night at 02:00 UTC, for every attached project, run the gate on the attached repository; notify
    SUB-001 if it fails."

The words come from the automation's own parts, never from a model, so the summary is what will run.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import automations as au

_PLACEHOLDER = re.compile(r"\{(project|event|automation|ref|verdict|branch)\}")

DAY_NAMES = dict(zip(au.DAYS, ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
                     strict=True))
EVENT_WORDS = {
    "release_done": "a release is done", "release_failed": "a release fails", "gate_failed": "the gate fails",
    "gate_passed": "the gate passes", "question_added": "a question is added", "card_waiting": "a card waits",
    "change_submitted": "a change is filed", "adopted": "a project is adopted", "material_added": "material is added",
    "upstream_synced": "the upstream is synced", "hook_received": "an inbound webhook rings",
    "incident_opened": "an incident opens", "probe_failed": "a probe fails", "decision": "a card is decided",
    "signal_received": "a signal arrives", "project_created": "a project is created",
    # the life-cycle transitions (kernel/automations_events.py, D-0023)
    "concept_validated": "a concept is validated", "plan_approved": "the spec or the plan is approved",
    "first_build_passed": "the first build passes the gate", "release_reached_test": "a release reaches a test road",
    "promoted": "a release is promoted to production", "rolled_back": "a release is rolled back",
    "check_failed": "a check fails",
}
SCOPE_WORDS = {"factory": "for every project", "source": "for every {source} project",
               "tag": "for every project tagged {tag}", "profile": "for every {profile} project"}


def _unit(every: str) -> str:
    n, unit = int(every[:-1]), {"m": "minute", "h": "hour", "d": "day"}[every[-1]]
    return f"Every {unit}" if n == 1 else f"Every {n} {unit}s"


def when(t: dict[str, Any]) -> str:
    if t["kind"] == "schedule":
        if t.get("every"):
            return _unit(t["every"])
        if t.get("daily"):
            hour = int(t["daily"][:2])
            return f"Every {'night' if hour < 6 or hour >= 22 else 'day'} at {t['daily']} UTC"
        return f"Every {DAY_NAMES[t['weekly'][:3]]} at {t['weekly'][4:]} UTC"
    if t["kind"] == "event":
        return "When " + " or ".join(EVENT_WORDS.get(x, x.replace("_", " ") + " is recorded") for x in t["types"])
    if t["kind"] == "hook":
        return f"When the inbound source {t['source']} rings"
    return f"When new commits land on {t.get('branch') or 'the tracked branch'}"


def guard(g: dict[str, Any] | None) -> str:
    if not g:
        return ""
    if g["kind"] == "count":
        what = EVENT_WORDS.get(g["event"], g["event"].replace("_", " "))
        return f", and only when {what} at least {g['at_least']} times within {g['within_hours']} hours"
    if g["kind"] == "branch":
        return f", only on {g['is']}"
    if g["kind"] == "field":
        return f", only when {g['key']} is {g['equals']}"
    cards = f"{g['card_kind']} cards" if g.get("card_kind") else "cards"
    return f", only when {g['at_least']} or more {cards} are open"


def scope(s: dict[str, Any]) -> str:
    if s["kind"] in ("project", "projects"):
        names = s["projects"]
        return f"for project {names[0]}" if len(names) == 1 else "for projects " + ", ".join(names)
    return SCOPE_WORDS[s["kind"]].format(**s)


def action(a: dict[str, Any], project: str | None = None) -> str:
    kind = a["kind"]
    if kind == "notify":
        return f"send a notification to {a['subscription']}"
    if kind == "change":
        where = a.get("project") or project
        return f"open a change proposal{' on ' + where if where else ''}: “{a['text'][:80]}”"
    if kind == "signal":
        return f"log a signal: “{a['text'][:80]}”"
    if kind == "ask":
        return f"ask a model “{a['text'][:80]}” and post the answer as a comment"
    if kind == "rescan":
        return f"re-scan {a['folder']} and add what is new as material"
    if kind == "output":
        return "rebuild " + (", ".join(a["targets"]) if a.get("targets") else "the chosen outputs")
    if kind == "probe":
        where = a.get("environment") or "the environment the event names (else production)"
        return f"run the probe check on {where}" + (f", and keep probing production every {a['every']}"
                                                    if a.get("every") else "")
    if kind == "gate" and not a.get("verifier", True):
        return "run the gate on the attached repository, without its verifier"
    return str(au.ACTIONS[kind]["label"])


def limits(lim: dict[str, Any]) -> str:
    parts = [f"At most {lim['max_per_hour']} runs an hour", f"paused after {lim['breaker']} failed runs in a row"]
    if lim.get("quiet"):
        parts.append(f"quiet {lim['quiet']} UTC")
    if lim.get("dry_run"):
        parts.append("a dry run: it records what it would do and does nothing")
    return "; ".join(parts) + "."


def describe(a: dict[str, Any]) -> str:
    """The automation in one paragraph, from its parts."""
    told = ""
    if a.get("notify"):
        n = a["notify"]
        told = f"; notify {n['subscription']} " + ("if it fails" if n["when"] == "failed" else "of every run")
    return (f"{when(a['trigger'])}{guard(a.get('guard'))}, {scope(a['scope'])}, {action(a['action'])}{told}. "
            f"{limits(a['limits'])}")


def fill(text: str, values: dict[str, Any]) -> str:
    """A text with its placeholders ({project}, {event}, {automation}, {ref}, {verdict}, {branch}) filled from
    ids only: never from a record's free text."""
    return _PLACEHOLDER.sub(lambda m: str(values.get(m.group(1)) or ""), text)


def plan(a: dict[str, Any], f: dict[str, Any]) -> str:
    """What one firing would do, for a dry run."""
    where = f.get("project")
    ev = (f.get("event") or {}).get("kind")
    because = f" (after {ev})" if ev else " (asked now)" if f.get("requested_by") else ""
    return f"would {action(a['action'], where)}{' on ' + where if where and a['action']['kind'] != 'change' else ''}" \
           f"{because}"


# The builder's starting points. Each draft names what a person still fills in (``needs``).
TEMPLATES: list[dict[str, Any]] = [
    {"id": "nightly_regate", "label": "Nightly re-gate", "needs": ["subscription"],
     "about": "Every night, re-gate every attached repository; notify a channel when the gate fails.",
     "draft": {"name": "Nightly re-gate", "trigger": {"kind": "schedule", "daily": "02:00"},
               "action": {"kind": "gate"}, "scope": {"kind": "source", "source": "attached"},
               "notify": {"subscription": "", "when": "failed"}}},
    {"id": "notify_on_release", "label": "Notify on release", "needs": ["subscription"],
     "about": "When any project's release is done, notify a channel.",
     "draft": {"name": "Notify on release", "trigger": {"kind": "event", "types": ["release_done"]},
               "action": {"kind": "notify", "subscription": "", "text": "{project} released ({event})"},
               "scope": {"kind": "factory"}}},
    {"id": "weekly_rescan", "label": "Re-scan a folder weekly", "needs": ["project", "folder"],
     "about": "Every Monday, re-scan a project's folder and add what is new as material.",
     "draft": {"name": "Weekly re-scan", "trigger": {"kind": "schedule", "weekly": "mon 06:00"},
               "action": {"kind": "rescan", "folder": ""}, "scope": {"kind": "project", "projects": []}}},
    {"id": "cross_project", "label": "Cross-project dependency", "needs": ["project", "target"],
     "about": "When project A releases, open a change proposal on project B.",
     "draft": {"name": "When A releases, check B", "trigger": {"kind": "event", "types": ["release_done"]},
               "action": {"kind": "change", "project": "",
                          "text": "{project} released ({event}): check that this project still works with it"},
               "scope": {"kind": "project", "projects": []}}},
    {"id": "gate_twice", "label": "Ask after two failed gates", "needs": ["project"],
     "about": "When the gate fails twice within a day, ask a model what goes wrong and post it as a comment.",
     "draft": {"name": "Why does the gate fail?", "trigger": {"kind": "event", "types": ["gate_failed"]},
               "guard": {"kind": "count", "event": "gate_failed", "at_least": 2, "within_hours": 24},
               "action": {"kind": "ask", "text": "The gate failed twice today. What is the likely cause?"},
               "scope": {"kind": "project", "projects": []}}},
    # the life-cycle transitions (kernel/automations_events.py, D-0023)
    {"id": "test_checks", "label": "When a release reaches test, run its checks and notify",
     "needs": ["subscription"],
     "about": "When a release reaches a test road, run the probe check there (health and every probe scenario) "
              "and notify a channel of the result.",
     "draft": {"name": "Check a release on test", "trigger": {"kind": "event", "types": ["release_reached_test"]},
               "action": {"kind": "probe"}, "scope": {"kind": "factory"},
               "notify": {"subscription": "", "when": "always"}}},
    {"id": "production_probe", "label": "When promoted to production, enable the probe check and notify",
     "needs": ["subscription"],
     "about": "When a release is promoted to production, probe it at once and every hour from then on (a failing "
              "probe opens the incident card), and notify a channel of each result.",
     "draft": {"name": "Probe production", "trigger": {"kind": "event", "types": ["promoted"]},
               "action": {"kind": "probe", "environment": "production", "every": "1h"},
               "scope": {"kind": "factory"}, "notify": {"subscription": "", "when": "always"}}},
    {"id": "concept_validated", "label": "When a concept is validated, notify the product owner",
     "needs": ["subscription"],
     "about": "When a concept is validated on the Square and its project is made, notify the product owner's "
              "channel.",
     "draft": {"name": "Tell the product owner", "trigger": {"kind": "event", "types": ["concept_validated"]},
               "action": {"kind": "notify", "subscription": "",
                          "text": "A concept was validated: {project} is made and waits for its intake"},
               "scope": {"kind": "factory"}}},
    {"id": "gate_twice_change", "label": "When the gate fails twice, open a change proposal", "needs": ["project"],
     "about": "When the gate fails twice within a day, open a change proposal on the project so people look at it.",
     "draft": {"name": "Two failed gates", "trigger": {"kind": "event", "types": ["gate_failed"]},
               "guard": {"kind": "count", "event": "gate_failed", "at_least": 2, "within_hours": 24},
               "action": {"kind": "change", "text": "The gate failed twice within a day on {project}: look at why "
                                                    "and decide what to change"},
               "scope": {"kind": "project", "projects": []}}},
]
# The checks', alignment's and the Review's templates (kernel/automations_more.py), whichever module loads first.
from kernel.automations_more import templates as _more  # noqa: E402

TEMPLATES += [t for t in _more() if t["id"] not in {x["id"] for x in TEMPLATES}]
