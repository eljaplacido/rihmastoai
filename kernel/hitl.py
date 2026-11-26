"""People in the loop (FR-HITL1): questions, decisions and feedback put to a named person or persona, answered and
signed, with each check family's enforcement, advise or require.

The owner (2026-11-25): "the human in the loop aspect is something that can be enforced when needed, and the personas
who would be on the place of each could be the ones nudged for feedback."

An **ask** is one item addressed to a persona (and, when named, a person, who may be outside the system:
kernel/hitl_links.py gives them a one-use link). It is a ``question`` (free answer), a ``decision`` (one of its
options) or ``feedback`` (free words), in a **check family**: quality, governance, legal, security, or general.
Each answer is recorded with the person, the persona, whether they are outside the system and the link they used.

Each check family is **advised** (an open ask is shown and nudged, nothing waits on it) or **required** (delivery
waits until every open ask of that family is answered: ``require_answered``, called by kernel/autonomy.py). The
level is read by name with a default: first from the enforcement settings when that module is present
(``kernel.enforce``), then this project's own setting, then the platform-wide one, else advise.

Records: ``<project>/hitl.json`` (the asks and this project's levels), ``_factory/hitl_settings.json`` (the
platform-wide levels and channels, kernel/hitl_send.py). Every change is in the project's ledger.
"""

from __future__ import annotations

import datetime as dt
import importlib
from typing import Any

from kernel.canon import DecisionRefused
from kernel.learn import FACTORY_PID
from kernel.people import PERSONAS, is_person
from kernel.store import Factory, Project, read_json, updating_json

FAMILIES = ("quality", "governance", "legal", "security", "general")
CHECK_FAMILIES = FAMILIES[:4]                  # the families that carry an enforcement level
KINDS = ("question", "decision", "feedback")
LEVELS = ("advise", "require")
# Who looks at each family when nobody is named: the persona responsible for it.
FAMILY_PERSONA = {"quality": "product_owner", "governance": "compliance", "legal": "compliance", "security": "it",
                  "general": "product_owner"}
FAMILY_LABEL = {"quality": "Quality", "governance": "Governance", "legal": "Legal", "security": "Security",
                "general": "General"}
SETTERS = ("business_owner", "product_owner", "compliance", "it")     # who sets a family's level
# Level names another enforcement module may use, read as "require" (anything else advises).
_REQUIRE_WORDS = {"require", "required", "block", "blocking", "enforce", "enforced", "force", "forced", "must",
                  "mandatory"}
MAX_TEXT = 2000
MAX_OPTIONS = 6
FILE = "hitl.json"
SETTINGS = "hitl_settings.json"


# -- records ------------------------------------------------------------------------------------------------

def _empty() -> dict[str, Any]:
    return {"asks": [], "enforcement": {}}


def _doc(project: Project) -> dict[str, Any]:
    return read_json(project.path(FILE), None) or _empty()


def settings(factory: Factory) -> dict[str, Any]:
    """The platform-wide settings: each family's level and the channels (kernel/hitl_send.py)."""
    return read_json(factory.projects_dir / FACTORY_PID / SETTINGS, None) or {"enforcement": {}, "channels": {}}


def updating_settings(factory: Factory) -> Any:
    return updating_json(factory.projects_dir / FACTORY_PID / SETTINGS, {"enforcement": {}, "channels": {}})


def asks(project: Project, *, state: str | None = None) -> list[dict[str, Any]]:
    return [a for a in _doc(project)["asks"] if state is None or a.get("state") == state]


def get(project: Project, ask_id: str) -> dict[str, Any]:
    found = next((a for a in asks(project) if a["id"] == ask_id), None)
    if found is None:
        raise KeyError(f"no ask {ask_id} in {project.pid}")
    return found


def _signs(person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: an ask and its answer are signed by a named person")
    if persona not in PERSONAS:
        raise DecisionRefused(f"persona must be one of {', '.join(PERSONAS)}")


# -- asking ----------------------------------------------------------------------------------------------

def _options(kind: str, options: list[Any] | None) -> list[str]:
    clean = [str(o).strip()[:200] for o in options or [] if str(o).strip()]
    if kind != "decision":
        return []
    if not 2 <= len(clean) <= MAX_OPTIONS:
        raise ValueError(f"a decision offers 2 to {MAX_OPTIONS} options to choose from")
    return list(dict.fromkeys(clean))


def _checked(text: str, kind: str, family: str, to_persona: str | None) -> tuple[str, str]:
    text = str(text or "").strip()
    if not text:
        raise ValueError("say what you ask: the question, the decision or the feedback wanted")
    if len(text) > MAX_TEXT:
        raise ValueError(f"an ask is at most {MAX_TEXT} characters")
    if kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(KINDS)}")
    if family not in FAMILIES:
        raise ValueError(f"family is one of {', '.join(FAMILIES)}")
    persona = to_persona or FAMILY_PERSONA[family]
    if persona not in PERSONAS:
        raise ValueError(f"the persona it goes to is one of {', '.join(PERSONAS)}")
    return text, persona


def ask(project: Project, *, text: str, person: str, persona: str, kind: str = "question", family: str = "general",
        to_persona: str | None = None, to_person: str | None = None, options: list[Any] | None = None,
        ref: str | None = None) -> dict[str, Any]:
    """Put a question, a decision or a request for feedback to the persona responsible (a named person when given)."""
    _signs(person, persona)
    text, to = _checked(text, kind, family, to_persona)
    opts = _options(kind, options)
    named = str(to_person or "").strip()[:120] or None
    with updating_json(project.path(FILE), _empty()) as doc:
        n = max([int(a["id"].split("-")[1]) for a in doc["asks"]], default=0) + 1
        item = {"id": f"HQ-{n:03d}", "kind": kind, "family": family, "text": text, "options": opts,
                "to": {"persona": to, "person": named, "external": False}, "by": person, "by_persona": persona,
                "at": project.factory.clock.stamp(), "state": "open", "answers": [], "ref": ref, "nudged": {}}
        doc["asks"].append(item)
    project.log("hitl_asked", {"ask": item["id"], "kind": kind, "family": family, "to_persona": to,
                               "to_person": named, "person": person, "persona": persona})
    return item


def persona_word(persona: str) -> str:
    """A persona as people say it: "Compliance", "IT / partner", "Business owner"."""
    from kernel.assistant_rules import PERSONA_LABEL

    return PERSONA_LABEL.get(persona, persona.replace("_", " "))


def not_yours(ask_id: str, to: str, persona: str) -> str:
    """Why a person signed in as another persona does not answer an ask, and what they can do (FR-HITL2)."""
    return (f"{ask_id} is put to {persona_word(to)}, and you are signed in as {persona_word(persona)}. If you hold "
            f"{persona_word(to)} too, switch to it in the person menu (or view as everything) and answer; otherwise "
            "nudge them or give them a link")


def _answer_ok(item: dict[str, Any], answer: str) -> str:
    answer = str(answer or "").strip()[:MAX_TEXT]
    if item["state"] != "open":
        raise DecisionRefused(f"{item['id']} is already {item['state']}: it was answered")
    if not answer:
        raise ValueError("an answer says something: choose an option or write it")
    if item["kind"] == "decision" and answer not in item["options"]:
        raise ValueError(f"choose one of: {', '.join(item['options'])}")
    return answer


def answer(project: Project, ask_id: str, *, answer: str, person: str, persona: str, comment: str = "",
           external: bool = False, via: str | None = None) -> dict[str, Any]:
    """Record an answer, signed. A person inside answers as the persona it was put to; a person outside answers
    through their link (kernel/hitl_links.py), as the persona that link recorded."""
    _signs(person, persona)
    with updating_json(project.path(FILE), _empty()) as doc:
        item = next((a for a in doc["asks"] if a["id"] == ask_id), None)
        if item is None:
            raise KeyError(f"no ask {ask_id} in {project.pid}")
        if persona != item["to"]["persona"]:
            raise DecisionRefused(not_yours(ask_id, item["to"]["persona"], persona))
        said = _answer_ok(item, answer)
        given = {"answer": said, "comment": str(comment or "").strip()[:MAX_TEXT], "person": person,
                 "persona": persona, "external": bool(external), "via": via, "at": project.factory.clock.stamp()}
        item["answers"].append(given)
        item["state"] = "answered"
    project.log("hitl_answered", {"ask": ask_id, "family": item["family"], "answer": said[:200], "person": person,
                                  "persona": persona, "external": bool(external), "via": via})
    return item


def address(project: Project, ask_ids: list[str], *, name: str, link_id: str) -> list[dict[str, Any]]:
    """Mark asks as addressed to a person outside, through a link (kernel/hitl_links.py)."""
    with updating_json(project.path(FILE), _empty()) as doc:
        hit = [a for a in doc["asks"] if a["id"] in ask_ids]
        for a in hit:
            a["to"].update(person=name, external=True, link=link_id)
    return hit


def unaddress(project: Project, link_id: str) -> list[str]:
    """A withdrawn link takes its asks back from that person (FR-HITL2): they go back to the persona inside, and
    no nudge makes the withdrawn person a new link."""
    with updating_json(project.path(FILE), _empty()) as doc:
        hit = [a for a in doc["asks"] if a["to"].get("link") == link_id]
        for a in hit:
            a["to"].update(person=None, external=False, link=None, withdrawn_from=a["to"].get("person"))
    return [a["id"] for a in hit]


def mark_nudged(project: Project, ask_id: str, step: str) -> None:
    with updating_json(project.path(FILE), _empty()) as doc:
        for a in doc["asks"]:
            if a["id"] == ask_id:
                a.setdefault("nudged", {})[step] = project.factory.clock.stamp()


# -- age -------------------------------------------------------------------------------------------------

def age_hours(project: Project, item: dict[str, Any]) -> float:
    try:
        at = dt.datetime.fromisoformat(str(item["at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return 0.0
    return max(0.0, (project.factory.clock.now() - at).total_seconds() / 3600)


# -- enforcement -----------------------------------------------------------------------------------------

def normal(level: object) -> str:
    """A level by any name: "require" (and the names that mean it) requires; anything else advises."""
    name = getattr(level, "name", level)
    return "require" if str(name or "").strip().lower() in _REQUIRE_WORDS else "advise"


def _from_enforce(project: Project, family: str) -> str | None:
    """The level the enforcement settings give this family, when that module is present (read by name)."""
    try:
        mod = importlib.import_module("kernel.enforce")
    except ImportError:
        return None
    for name in ("level_of", "level"):
        fn = getattr(mod, name, None)
        if callable(fn):
            try:
                found = fn(project, family)
            except (KeyError, LookupError, OSError, TypeError, ValueError):
                return None
            return None if found is None else normal(found)
    return None


def level(project: Project, family: str) -> tuple[str, str]:
    """(advise | require, where it is set): enforcement settings, this project, platform-wide, or the default."""
    if family not in CHECK_FAMILIES:
        return "advise", "default"
    outside = _from_enforce(project, family)
    if outside is not None:
        return outside, "enforcement settings"
    own = _doc(project).get("enforcement", {}).get(family)
    if own:
        return normal(own), "this project"
    platform = settings(project.factory).get("enforcement", {}).get(family)
    if platform:
        return normal(platform), "platform-wide"
    return "advise", "default"


def levels(project: Project) -> list[dict[str, Any]]:
    out = []
    for fam in CHECK_FAMILIES:
        lvl, where = level(project, fam)
        out.append({"family": fam, "label": FAMILY_LABEL[fam], "level": lvl, "set_in": where,
                    "persona": FAMILY_PERSONA[fam]})
    return out


def set_level(project: Project, family: str, lvl: str, *, person: str, persona: str,
              scope: str = "project") -> dict[str, Any]:
    """Advise or require a check family, for this project or platform-wide (every project without its own)."""
    _signs(person, persona)
    if persona not in SETTERS:
        raise DecisionRefused(f"a {persona} does not set enforcement: {', '.join(SETTERS)} do")
    if family not in CHECK_FAMILIES:
        raise ValueError(f"family is one of {', '.join(CHECK_FAMILIES)}")
    if lvl not in LEVELS:
        raise ValueError("level is advise (shown and nudged) or require (delivery waits on it)")
    if scope not in ("project", "platform"):
        raise ValueError("scope is project or platform")
    record = {"family": family, "level": lvl, "scope": scope, "person": person, "persona": persona}
    if scope == "platform":      # every project's rule: on the factory's own record (FR-HITL2)
        from kernel.learn import factory_project

        with updating_settings(project.factory) as cfg:
            cfg.setdefault("enforcement", {})[family] = lvl
        factory_project(project.factory).log("hitl_enforcement_set", record | {"from_project": project.pid})
    else:
        with updating_json(project.path(FILE), _empty()) as doc:
            doc.setdefault("enforcement", {})[family] = lvl
    project.log("hitl_enforcement_set", record)
    return {"family": family, "level": lvl, "scope": scope, "levels": levels(project)}


def blocking(project: Project) -> list[dict[str, Any]]:
    """The open asks of a required family: delivery waits on them."""
    if project.pid == FACTORY_PID or not project.path(FILE).exists():
        return []
    return [a for a in asks(project, state="open") if level(project, a["family"])[0] == "require"]


def require_answered(project: Project, what: str) -> None:
    """Raise Held (a wait, never an error) while a required family has an open ask; says what to do."""
    open_ones = blocking(project)
    if not open_ones:
        return
    from kernel.posture_rules import Held

    names = ", ".join(f"{a['id']} ({FAMILY_LABEL[a['family']].lower()}, for the "
                      f"{(a['to'].get('person') or a['to']['persona'].replace('_', ' '))})" for a in open_ones[:5])
    raise Held(4, 0, f"{what} waits on {len(open_ones)} required answer(s): {names}. Answer them in People in the "
                     "loop, nudge who has not answered, or set that family to advise")


def holds(project: Project) -> list[dict[str, Any]]:
    """What holds delivery for a person's answer, as the project's Now line, its Inbox and the all-projects Inbox
    show it (FR-HITL2): each required open ask with who it waits on."""
    try:
        open_ones = blocking(project)
    except (OSError, ValueError):
        return []
    return [{"id": a["id"], "family": a["family"], "kind": a["kind"], "text": a["text"][:160],
             "to": a["to"].get("person") or persona_word(a["to"]["persona"]), "persona": a["to"]["persona"],
             "external": bool(a["to"].get("external"))} for a in open_ones]


def holds_line(rows: list[dict[str, Any]]) -> str:
    names = ", ".join(f"{r['id']} ({FAMILY_LABEL[r['family']].lower()}, for {r['to']})" for r in rows[:3])
    return f"delivery waits on {len(rows)} required answer(s) in People in the loop: {names}"


def who_has_not_answered(project: Project) -> list[dict[str, Any]]:
    """Every open ask with who it waits on and how long, oldest first."""
    rows = [{"id": a["id"], "kind": a["kind"], "family": a["family"], "text": a["text"],
             "persona": a["to"]["persona"], "person": a["to"].get("person"), "external": a["to"].get("external"),
             "hours": round(age_hours(project, a), 1),
             "required": level(project, a["family"])[0] == "require"} for a in asks(project, state="open")]
    return sorted(rows, key=lambda r: -r["hours"])
