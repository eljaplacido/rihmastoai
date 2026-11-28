"""Teams stay whole (D-0027, FR-TM5): the checks that keep a team, its name and its words from being broken by a change.

- a **name** is unique (whatever the case or the spacing), holds a letter or a digit and is not another team's id, and a
  new team's id is made from the name with accents folded (a name with no plain letters gets a short code), never the
  id of an old team, of words an old team left behind or of a team a project still names;
- **members** are names in a list, and a team does not take a person out of the home (People does that);
- undoing a team's **creation** is refused while it holds projects or has words of its own: it names them and says
  what to do first, so a project is never silently put in another team and no words are lost or taken over later;
- a **preview** asks for the same role as the change it previews, and a refusal says in plain words who may.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

from kernel.canon import DecisionRefused

MAX_NAME = 80
ROLE_WORD = {"it": "IT"}


# -- who ----------------------------------------------------------------------------------------------------

def who_words(allowed: tuple[str, ...]) -> str:
    named = [ROLE_WORD.get(a, a) for a in allowed]
    return named[0] if len(named) == 1 else ", ".join(named[:-1]) + " or " + named[-1]


def require_persona(persona: str, allowed: tuple[str, ...], what: str, who: str | None = None) -> None:
    """Refuse a persona that may not ``what``; a missing one is asked for, not named as an empty role."""
    if not persona:
        raise DecisionRefused(f"say which role you act as: {what} is done by {who or who_words(allowed)}")
    if persona not in allowed:
        article = "an" if persona[:1].lower() in "aeiou" else "a"
        raise DecisionRefused(f"{article} {persona} may not {what}; only {who or who_words(allowed)} may")


# -- names and ids ------------------------------------------------------------------------------------------

def clean_name(factory: Any, value: Any, own: str | None = None) -> str:
    """A team's name: plain, with something in it, and not another team's name or id (``own`` may keep its own)."""
    from kernel import teams

    name = " ".join(str(value or "").split())
    if not name or len(name) > MAX_NAME:
        raise ValueError(f"a team has a name of 1 to {MAX_NAME} characters")
    if not any(c.isalnum() for c in name):
        raise ValueError("a team's name holds a letter or a digit")
    low = name.casefold()
    for d in teams.all_teams(factory):
        if d["id"] == own:
            continue
        if low == str(d["name"]).casefold():
            raise ValueError(f"a team called {d['name']!r} already exists: pick another name")
        if low == str(d["id"]).casefold():
            raise ValueError(f"{name!r} is the id of the team {d['name']!r}: pick another name")
    return name


def _slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:40].rstrip("-")


def _taken(factory: Any, tid: str) -> bool:
    from kernel import teams, vocab

    named = any(p.meta.get("team") == tid for p in factory.projects())
    return teams.exists(factory, tid) or tid == teams.AUTO_ID or vocab.path_of(factory, "team", tid).exists() or named


def new_id(factory: Any, name: str) -> str:
    """The id of a new team: the name folded to plain letters, or a code when there are none, never one in use."""
    base = _slug(name) or hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()[:6]
    base = base if base.startswith("team") else "team-" + base
    tid, n = base, 2
    while _taken(factory, tid):
        tid, n = f"{base}-{n}", n + 1
    return tid


# -- members ------------------------------------------------------------------------------------------------

def names_of(value: Any) -> list[str]:
    """A list of names (or one), as the routes and the commands give them; anything else is refused."""
    if value is None:
        return []
    if not isinstance(value, (str, list, tuple)):
        raise ValueError("members are a list of names")
    return [" ".join(str(x).split()) for x in ([value] if isinstance(value, str) else value)]


def check_remove(factory: Any, auto: bool, remove: list[str]) -> None:
    """The automatic team is everyone the home knows: a person leaves it in People, not here."""
    from kernel import teams

    if not auto:
        return
    home = set(teams._people(factory))
    held = [n for n in remove if n in home]
    if held:
        who = "is a person" if len(held) == 1 else "are people"
        raise ValueError(f"{', '.join(held)} {who} of this home, so every team has them: take them out in "
                         "Settings > People (deactivate), not in a team")


# -- undoing a creation -------------------------------------------------------------------------------------

def check_undo(factory: Any, tid: str, last: dict[str, Any]) -> None:
    """Undoing a team's creation, or a change that would give it a name another team now has, is refused with why."""
    from kernel import teams, vocab

    if tid == teams.AUTO_ID:              # the automatic team always exists: undoing its rename takes the override off
        return
    doc = teams.read(factory, tid)
    if last.get("before") is not None:
        clean_name(factory, last["before"]["name"], own=tid)
        return
    held = teams.projects_of(factory, tid)
    if held:
        names = ", ".join(str(p.meta.get("title") or p.pid) for p in held[:5])
        raise ValueError(f"{names} {'is' if len(held) == 1 else 'are'} in {doc['name']}: move "
                         f"{'it' if len(held) == 1 else 'them'} to another team first (each project's settings), then "
                         "undo the team")
    if vocab.read_layer(factory, "team", tid):
        raise ValueError(f"{doc['name']} has words of its own: give them back first (Settings > Words, or undo "
                         "the change of words), then undo the team")

