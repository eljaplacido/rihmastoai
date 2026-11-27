"""An automation from a description (FR-SET1): "every night run the tests and tell me on Teams if they fail".

The owner (2026-11-24): "ask an agent to generate an automation based on your description."

``compose`` turns a sentence into a **draft** automation of kernel/automations.py (trigger, guard, action, scope,
limits, notify), with its plain-language summary (kernel/automations_text.py) and a dry run of what it would do
now, before the person confirms it. Nothing is set until they do: the cockpit's "Describe it" saves the draft
through the signed route, and Ask Rihma offers it as a proposal the person confirms.

- **Rules first**, in English and Finnish, without a model: the common phrasings of a schedule ("every night",
  "every 5 minutes", "on Mondays", "öisin", "joka aamu"), an event ("when a release is done", "when the gate
  fails", "on new commits", "kun julkaisu valmistuu"), an action ("run the tests", "run the gate", "probe
  production", "summarise", "aja testit") and whom to tell ("tell me on Teams if they fail", "ilmoita Slackiin").
- **A model for the rest** (the assistant role; a local one for a confidential project, else the rules alone and
  a note): it is given the allow-list and the schema, and its draft is checked as any automation is
  (``automations._checked``): an action off the allow-list, or one an automation may never take (decide,
  approve, deploy...), is refused with the reason.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from kernel import automations as au
from kernel.store import Factory

# A schedule: the pattern, and the trigger it gives (minutes, hours or a time to fill in).
_N = r"(\d{1,4})"
SCHEDULES: tuple[tuple[re.Pattern[str], Any], ...] = (
    (re.compile(rf"\bevery {_N} ?(?:minutes?|mins?|m)\b|\b{_N} minuutin välein"), lambda n: {"every": f"{n}m"}),
    (re.compile(rf"\bevery {_N} ?(?:hours?|h)\b|\b{_N} tunnin välein"), lambda n: {"every": f"{n}h"}),
    (re.compile(r"\b(?:hourly|every hour|tunneittain|joka tunti|tunnin välein)\b"), {"every": "1h"}),
    (re.compile(r"\b(?:every night|nightly|each night|at night|overnight|joka yö|öisin|yöllä|yöllisesti)\b"),
     {"daily": "02:00"}),
    (re.compile(r"\b(?:every morning|each morning|in the morning|aamuisin|joka aamu)\b"), {"daily": "07:00"}),
    (re.compile(r"\b(?:every evening|iltaisin|joka ilta)\b"), {"daily": "18:00"}),
    (re.compile(r"\b(?:every day|daily|each day|päivittäin|joka päivä)\b"), {"daily": "06:00"}),
    (re.compile(r"\b(?:every week|weekly|viikoittain|joka viikko)\b"), {"weekly": "mon 06:00"}),
)
DAY_WORDS = {"mon": ("monday", "maanantai"), "tue": ("tuesday", "tiistai"), "wed": ("wednesday", "keskiviikko"),
             "thu": ("thursday", "torstai"), "fri": ("friday", "perjantai"), "sat": ("saturday", "lauantai"),
             "sun": ("sunday", "sunnuntai")}
_AT = re.compile(r"\b(?:at|klo|kello)\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\b")
EVENTS: tuple[tuple[re.Pattern[str], list[str], dict[str, Any] | None], ...] = (
    (re.compile(r"\b(?:check fails|a check fails|checks? failed|tarkistus epäonnistuu)"), ["check_ran"],
     {"kind": "field", "key": "verdict", "equals": "failed"}),
    (re.compile(r"\bgate (?:fails|failed|is red)|\bportti epäonnistuu"), ["gate_failed"], None),
    (re.compile(r"\bgate passe?s|\bportti menee läpi"), ["gate_passed"], None),
    (re.compile(r"\b(?:promoted|reaches production|goes live|to production|tuotantoon)"), ["promoted"], None),
    (re.compile(r"\b(?:reaches test|on test|to test|testiin|testiympäristöön)"), ["release_reached_test"], None),
    (re.compile(r"\b(?:release (?:is )?(?:done|finished|out|ships?)|released|julkaisu valmistuu|julkaisu on valmis|"
                r"julkaistaan)"), ["release_done"], None),
    (re.compile(r"\b(?:rolled back|rollback|palautetaan)"), ["rolled_back"], None),
    (re.compile(r"\b(?:first build passes|first build)"), ["first_build_passed"], None),
    (re.compile(r"\b(?:question is added|new question|uusi kysymys)"), ["question_added"], None),
    (re.compile(r"\b(?:card waits|waiting card|a card is waiting|kortti odottaa)"), ["card_waiting"], None),
    (re.compile(r"\b(?:concept (?:is )?validated|konsepti validoidaan)"), ["concept_validated"], None),
    # "open an incident if it fails" says what to do, never when: only "when an incident opens" is a trigger
    (re.compile(r"\b(?:probe fails|probe failed|(?:when|if|once) an? incident (?:is )?open\w*|incident opens)"),
     ["probe_failed"], None),
)
_REPO = re.compile(r"\b(?:new commits?|every (?:push|commit)|on (?:each |every )?(?:push|commit)|someone pushes|"
                   r"is pushed|uusi commit|uusia committeja|committ\w*|pushat\w*)")
# An action: the pattern, and the action it gives (its text filled in later when it needs words).
ACTIONS: tuple[tuple[re.Pattern[str], dict[str, Any]], ...] = (
    (re.compile(r"\b(?:(?:run|do|make) (?:the |an |a new )?assessment|re-?assess|assess (?:it|the project|again)|"
                r"arvioi|arviointi)"), {"kind": "run_assessment"}),
    (re.compile(r"\b(?:gnomon(?:'s)? (?:audit|eval|benchmark)\w*|security posture|run (?:the |an )?(?:audit|eval)\b|"
                r"own tasks)"), {"kind": "run_eval"}),
    (re.compile(r"\b(?:run (?:the |its |our |all )?(?:unit )?tests|test suite|run the suite|aja (?:\w+ )?testit|"
                r"testaa|ajaa testit)"), {"kind": "command"}),
    (re.compile(r"\b(?:run (?:the )?gate|re-?gate|gate it|aja portti|tarkista portti)"), {"kind": "gate"}),
    (re.compile(r"\b(?:probe|ping|uptime|check (?:that )?(?:it|production|prod) is (?:up|alive)|"
                r"tarkista tuotanto|luotaa)"), {"kind": "probe", "environment": "production"}),
    (re.compile(r"\b(?:re-?read|re-?align|alignment|kohdista|lue (?:repo|uudelleen))"), {"kind": "align_scan"}),
    (re.compile(r"\b(?:re-?scan|scan (?:the )?folder|skannaa)"), {"kind": "rescan"}),
    (re.compile(r"\b(?:summari[sz]e|summary|digest of|yhteenveto|tiivistä)"), {"kind": "ask"}),
    (re.compile(r"\b(?:open a change|change proposal|muutosehdotus)"), {"kind": "change"}),
    (re.compile(r"\b(?:rebuild (?:the )?outputs?|build the outputs?)"), {"kind": "output"}),
    (re.compile(r"\b(?:log a signal|signal)"), {"kind": "signal"}),
)
_TELL = re.compile(r"\b(?:tell|notify|let me know|alert|message|send|post|ping me|ilmoit\w*|kerro|lähetä|hälytä)")
_IF_FAIL = re.compile(r"\b(?:if (?:it |they |that |this |the \w+ )?fails?|on failure|when (?:it|they) fails?|"
                      r"if anything fails|failing|jos (?:ne |se |jokin )?epäonnistu\w*|epäonnistu\w*)")
SINKS = {"teams": re.compile(r"\bteams\w*"), "slack": re.compile(r"\bslack\w*"),
         "email": re.compile(r"\b(?:e-?mail|mail|sähköpost\w*)"), "webhook": re.compile(r"\bwebhook")}
_EVERY_PROJECT = re.compile(r"\b(?:every project|all projects|each project|kaikki projektit|kaikissa projekteissa)")
_ATTACHED = re.compile(r"\b(?:attached (?:projects|repositories|repos)|every attached)")


def _said(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _time(said: str) -> str | None:
    m = _AT.search(said)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3) == "pm" and hour < 12:
        hour += 12
    if m.group(3) == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}" if hour < 24 and minute < 60 else None


def _day(said: str) -> str | None:
    for day, names in DAY_WORDS.items():
        if any(re.search(rf"\b(?:on |every )?{n}s?\b|\b{n}sin\b|\b{n}isin\b", said) for n in names):
            return day
    return None


def _schedule(said: str) -> dict[str, Any] | None:
    at, day = _time(said), _day(said)
    if day:
        return {"kind": "schedule", "weekly": f"{day} {at or '06:00'}"}
    for pattern, gives in SCHEDULES:
        m = pattern.search(said)
        if m:
            t = gives(next(g for g in m.groups() if g)) if callable(gives) else dict(gives)
            key = next(iter(t))
            if at and key == "daily":
                t = {"daily": at}
            if at and key == "weekly":
                t = {"weekly": t["weekly"][:4] + at}
            return {"kind": "schedule", **t}
    return {"kind": "schedule", "daily": at} if at else None


def _trigger(said: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The trigger and the guard the words give."""
    for pattern, types, guard in EVENTS:
        if pattern.search(said):
            return {"kind": "event", "types": types}, guard
    if _REPO.search(said):
        return {"kind": "repo"}, None
    return _schedule(said), None


def _action(said: str, project: Any) -> dict[str, Any] | None:
    for pattern, gives in ACTIONS:
        if pattern.search(said):
            a = dict(gives)
            if a["kind"] in ("ask", "change", "signal"):
                a["text"] = _words_for(a["kind"], project)
            if a["kind"] == "rescan":
                a["folder"] = ""
            if a["kind"] == "run_eval":
                a["eval"] = next((eid for rx, eid in EVAL_WORDS if rx.search(said)), "security")
            if a["kind"] == "command" and project is not None and not _has_repo(project):
                a = {"kind": "run_check", "check": "tests"}   # built here: Health's Test suite runs its tests
            return a
    return None


# Which of Gnomon's audits or evals the words name (kernel/gnomon_evals.py); the security posture when none.
EVAL_WORDS = tuple((re.compile(rx), eid) for rx, eid in (
    (r"own tasks|pass rate", "eval"), (r"compliance|ai act|gdpr", "compliance"), (r"data.?flow", "dataflow"),
    (r"chaos|fault", "chaos"), (r"integrity|audit trail", "audit_verify"), (r"doctor|routes", "doctor"),
    (r"attack|corpus", "security_test"), (r"context cost", "context_cost"), (r"degradation", "degradation"),
    (r"security|posture", "security")))


def _has_repo(project: Any) -> bool:
    from kernel.adopt import is_adopted

    return bool((project.meta.get("attached") or {}).get("repo")) or is_adopted(project)


def _words_for(kind: str, project: Any) -> str:
    return {"ask": "Summarise the recent activity on {project} by area: what changed, what failed, what waits.",
            "change": "Look at {project} ({event}) and decide what to change.",
            "signal": "{project}: {event}"}[kind]


def _subscription(factory: Factory, said: str, pid: str | None) -> tuple[str | None, str | None]:
    """The relay subscription the words name by its kind (Teams, Slack, e-mail, a webhook), the project's own
    first; or the only one there is. (subscription id, the sink named)."""
    from kernel import relay

    sink = next((k for k, rx in SINKS.items() if rx.search(said)), None)
    subs = [s for s in relay.subscriptions(factory) if sink is None or s.get("sink") == sink]
    subs.sort(key=lambda s: 0 if pid and pid in (s.get("projects") or []) else 1)
    return (str(subs[0]["id"]) if subs else None), sink


def _scope(said: str, pid: str | None) -> dict[str, Any]:
    if _EVERY_PROJECT.search(said):
        return {"kind": "factory"}
    if _ATTACHED.search(said):
        return {"kind": "source", "source": "attached"}
    return {"kind": "project", "projects": [pid]} if pid else {"kind": "factory"}


def _name(text: str) -> str:
    first = re.split(r"[.!?\n]", text.strip())[0]
    return (first[:1].upper() + first[1:])[:80] or "Described automation"


def by_rules(factory: Factory, text: str, *, project: Any = None) -> dict[str, Any]:
    """The draft the rules read from the words, and what they could not read (``missing``)."""
    said, pid = _said(text), project.pid if project is not None else None
    trigger, guard = _trigger(said)
    action = _action(said, project)
    tell = bool(_TELL.search(said))
    sub, sink = _subscription(factory, said, pid) if tell else (None, None)
    when = "failed" if _IF_FAIL.search(said) else "always"
    if action is None and tell:
        action = {"kind": "notify", "subscription": sub or "", "text": "{project}: {event}"}
    draft: dict[str, Any] = {"name": _name(text), "trigger": trigger, "guard": guard, "action": action,
                             "scope": _scope(said, pid)}
    if tell and sub and action is not None and action["kind"] != "notify":
        draft["notify"] = {"subscription": sub, "when": when}
    _paced(action, trigger)
    missing = [k for k in ("trigger", "action") if draft[k] is None]
    return {"draft": draft, "needs": _needs(action, tell, sub), "missing": missing, "sink": sink}


def _paced(action: dict[str, Any] | None, trigger: dict[str, Any] | None) -> None:
    """"Every 15 minutes probe production": the probe check keeps the schedule's pace (15m to 1d)."""
    every = (trigger or {}).get("every")
    if action is not None and action["kind"] == "probe" and every and 15 <= au.minutes_of(every) <= 1440:
        action["every"] = every


def _needs(action: dict[str, Any] | None, tell: bool, sub: str | None) -> list[str]:
    """What the person still picks: a channel to tell (none is set up), a folder to re-scan."""
    if action is None:
        return []
    return (["subscription"] if tell and not sub else []) + (["folder"] if action["kind"] == "rescan" else [])


# -- the model, for what the rules cannot read ---------------------------------------------------------------

def _prompt(text: str, pid: str | None) -> str:
    acts = "\n".join(f"- {k}: {v['label']}" for k, v in au.ACTIONS.items())
    return f"""Turn the person's description into ONE automation for Rihmasto. Answer only with a JSON object:
{{"name": str, "trigger": {{"kind": "schedule", "every"|"daily"|"weekly": ...}} or {{"kind": "event", "types": [str]}}
 or {{"kind": "repo"}}, "guard": null or {{"kind": "count"|"branch"|"field"|"open_cards", ...}},
 "action": {{"kind": <one of the actions below>, ...}}, "scope": {{"kind": "project", "projects": ["{pid or ''}"]}}
 or {{"kind": "factory"}}, "notify": null or {{"subscription": "SUB-...", "when": "failed"|"always"}}}}
Schedules are in UTC: every 5m to 7d, daily "HH:MM", weekly "mon HH:MM". Events are record kinds such as
release_done, gate_failed, promoted, release_reached_test, check_ran. The only actions:
{acts}
An automation never decides, approves, deploys, merges or grants anything.

Description: {text.strip()[:1000]}"""


def by_model(factory: Factory, text: str, *, project: Any, model: Any) -> dict[str, Any]:
    """The model's draft, or why there is none; its draft is checked by ``compose`` like the rules' one."""
    from kernel import model_usage
    from kernel.assistant import _own_lane
    from kernel.confidential import confidential, refusal
    from kernel.model import ModelError, extract_json

    secret = project is not None and confidential(project)
    if secret and refusal(["assistant"]):
        return {"draft": None, "note": "this project is confidential and the assistant's model is hosted: only "
                                       "the rules read it (Models setup makes the assistant local)"}
    try:
        with model_usage.for_project(project, task="automation_compose", factory=factory):
            raw = extract_json(_own_lane(model, secret).ask(_prompt(text, getattr(project, "pid", None)),
                                                            role="assistant"))
    except (ModelError, OSError, RuntimeError, ValueError) as exc:
        return {"draft": None, "note": f"the model gave no usable draft ({exc})"}
    if not isinstance(raw, dict):
        return {"draft": None, "note": "the model's answer is not a JSON object"}
    keep = ("name", "trigger", "guard", "action", "scope", "limits", "notify")
    return {"draft": {k: raw[k] for k in keep if k in raw}, "note": None}


# -- checking, the summary and the dry run --------------------------------------------------------------------

def rehearse(factory: Factory, checked: dict[str, Any]) -> dict[str, Any]:
    """What the draft would do, now: the projects it reaches, what one firing would do on each, and when a
    schedule would fire first. Records nothing."""
    from kernel import automations_run as run
    from kernel import automations_text as words

    now = factory.clock.now()
    pids = [p.pid for p in au.projects_in(factory, checked["scope"])]
    t = checked["trigger"]
    first = run.next_slot(t, now) if t["kind"] == "schedule" else None
    per = pids if au.ACTIONS[checked["action"]["kind"]]["per_project"] else [None]
    rows = [{"project": pid, "would": words.plan(checked, {"project": pid, "trigger": t["kind"]})} for pid in per[:10]]
    return {"projects": pids, "firings": rows,
            "first_at": first.isoformat().replace("+00:00", "Z") if isinstance(first, dt.datetime) else None,
            "when": words.when(t)}


def check(factory: Factory, draft: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """The draft as kernel/automations.py checks it: (checked parts, None) or (None, why not)."""
    try:
        return au._checked(factory, draft), None
    except au.AutomationRefused as exc:
        return None, f"refused: {exc}"
    except (ValueError, KeyError, TypeError) as exc:
        return None, str(exc.args[0] if isinstance(exc, KeyError) and exc.args else exc)


def compose(factory: Factory, text: str, *, project: Any = None, model: Any = None) -> dict[str, Any]:
    """A draft automation from a description: the rules' reading, else the model's; checked, with its summary
    and dry run. ``ok`` is whether it can be saved as it stands; ``needs`` what the person still picks."""
    from kernel import automations_text as words

    if not str(text or "").strip():
        raise ValueError("describe the automation: when, what, and whom to tell")
    if len(text) > au.MAX_TEXT:
        raise ValueError(f"the description is longer than {au.MAX_TEXT} characters")
    ruled = by_rules(factory, text, project=project)
    out: dict[str, Any] = {"text": text.strip(), "by": "rules", "needs": ruled["needs"], "note": None}
    draft = ruled["draft"]
    if ruled["missing"] and model is not None:
        modelled = by_model(factory, text, project=project, model=model)
        out["note"] = modelled["note"]
        if modelled["draft"]:
            draft, out["by"], out["needs"] = modelled["draft"], "model", []
    out["draft"] = draft
    if out["by"] == "rules" and ruled["missing"]:
        out.update(ok=False, why="I could not read " + " and ".join(
            {"trigger": "when it should run", "action": "what it should do"}[k] for k in ruled["missing"])
            + " from that: say it as \"every night\", \"when a release is done\" or \"on new commits\", and "
              "\"run the tests\", \"run the gate\", \"probe production\", \"run the assessment\", \"run the Gnomon "
              "security posture audit\" or \"tell me on Teams\".",
            summary=None, dry_run=None)
        return out
    checked, why = check(factory, draft)
    out.update(ok=checked is not None, why=why, summary=words.describe(checked) if checked else None,
               dry_run=rehearse(factory, checked) if checked else None)
    if "subscription" in out["needs"]:
        out["note"] = (f"there is no {ruled['sink'] or 'notification'} channel to tell you on yet: IT adds one with "
                       "`rihmasto relay subscribe`; until then it runs without telling anyone")
    return out
