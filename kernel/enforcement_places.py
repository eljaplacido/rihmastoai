"""Where a name lands among development, testing and production, and which stage the gate's changes enter
(D-0026 enforcement levels, FR-ENF2).

A pipeline names its environments freely: ``staging``, ``prod-eu``, ``qa2``, ``eu-west``, ``customer-a``. Rihmasto
places a name by its whole words, never by a part of a word: ``productivity-tools`` is not production, ``latest``
and ``contest`` are not testing. A name Rihmasto does not know is never quietly taken as development, the least
strict stage: it counts as production, the strictest, and every answer says so and how to place it. A person
places a name for a project or for all projects (``names``: {name: dev|test|prod}); that is signed and recorded
with the levels (kernel/enforcement.py ``set_levels``), and placing a name in a less strict stage than it had
needs a reason, as loosening a level does.

The gate judges a change of an attached repository before it goes on. Which stage that change enters is the
project's (or the platform's) ``gate_env``: development unless a person says the main line feeds testing or
production; the gate then asks that stage's levels.
"""

from __future__ import annotations

import re
from typing import Any

ENVIRONMENTS = ("dev", "test", "prod")
INHERIT = "inherit"
# Rihmasto's own environments, and a pipeline's usual names, in the three.
ENV_OF = {"dev": "dev", "development": "dev", "local": "dev", "preview": "dev", "demo": "dev", "sandbox": "dev",
          "test": "test", "testing": "test", "staging": "test", "stage": "test", "qa": "test", "uat": "test",
          "acceptance": "test", "preprod": "test", "preproduction": "test", "pre-production": "test",
          "prod": "prod", "production": "prod", "live": "prod"}
UNKNOWN_AS = "prod"            # an unknown name fails closed: the strictest stage, said every time
DEFAULT_GATE_ENV = "dev"
_WORD = re.compile(r"[a-z]+")
_PRE = re.compile(r"(?<![a-z])pre[-_ .]?(?=prod)")
NAME = re.compile(r"[a-z0-9][a-z0-9._ /-]{0,59}\Z")
WHERE = {"dev": "development", "test": "testing", "prod": "production"}


def norm(name: Any) -> str:
    return " ".join(str(name or "").strip().lower().split())


def env_of(name: Any) -> str | None:
    """One of dev, test, prod for a name, by its whole words (``prod-eu``, ``staging2``), or None when unknown."""
    key = norm(name)
    if key in ENV_OF:
        return ENV_OF[key]
    found = {ENV_OF[w] for w in _WORD.findall(_PRE.sub("pre", key)) if w in ENV_OF}
    return max(found, key=ENVIRONMENTS.index) if found else None


def _named(doc: dict[str, Any]) -> dict[str, str]:
    names = doc.get("names") or {}
    return {k: v for k, v in names.items() if v in ENVIRONMENTS} if isinstance(names, dict) else {}


def place(name: Any, project_doc: dict[str, Any], platform_doc: dict[str, Any]) -> dict[str, Any]:
    """Where ``name`` lands: named by a person (the project's, else all projects'), known by its words, or unknown
    and held as production; with the words that say so."""
    key = norm(name) or "dev"
    for scope, doc in (("project", project_doc), ("platform", platform_doc)):
        env = _named(doc).get(key)
        if env:
            return {"name": key, "env": env, "how": "named", "scope": scope, "says": None}
    env = env_of(key)
    if env:
        return {"name": key, "env": env, "how": "known", "scope": "default", "says": None}
    return {"name": key, "env": UNKNOWN_AS, "how": "unknown", "scope": "default",
            "says": f"'{key}' is not a stage name Rihmasto knows, so it counts as production, the strictest. Place "
                    f"it in the Enforcement view (or tell Ask Rihma: treat {key} as testing)."}


def gate_env(project_doc: dict[str, Any], platform_doc: dict[str, Any]) -> dict[str, str]:
    """The stage a change judged by the gate enters, and the scope that says so."""
    for scope, doc in (("project", project_doc), ("platform", platform_doc)):
        if doc.get("gate_env") in ENVIRONMENTS:
            return {"env": doc["gate_env"], "scope": scope}
    return {"env": DEFAULT_GATE_ENV, "scope": "default"}


# -- changing them (kernel/enforcement.py set_levels records the changes) ----------------------------------

def _was(doc: dict[str, Any], key: str) -> str:
    return _named(doc).get(key) or env_of(key) or UNKNOWN_AS


def names_change(doc: dict[str, Any], names: Any) -> list[dict[str, Any]]:
    """Place names in a stage (``inherit`` removes the placing); the changes, each saying whether it loosens."""
    if names is None:
        return []
    if not isinstance(names, dict):
        raise ValueError("names is an object: {environment name: dev, test or prod}")
    out = []
    for raw, to in names.items():
        key = norm(raw)
        if not NAME.match(key) or to not in (*ENVIRONMENTS, INHERIT):
            raise ValueError("a name is placed in dev, test or prod (or inherit); a name is up to 60 letters, "
                             "digits, spaces, dots, slashes and dashes")
        before = _named(doc).get(key)
        after = None if to == INHERIT else to
        if before == after:
            continue
        rank_was = ENVIRONMENTS.index(_was(doc, key))
        held = doc.setdefault("names", {})
        if after is None:
            held.pop(key, None)
        else:
            held[key] = after
        out.append({"name": key, "from": before, "to": after,
                    "looser": ENVIRONMENTS.index(_was(doc, key)) < rank_was})
    return out


def gate_change(doc: dict[str, Any], to: Any) -> list[dict[str, Any]]:
    """The stage the gate's changes enter (``inherit`` gives it back to all projects' or the default)."""
    if to is None:
        return []
    if to not in (*ENVIRONMENTS, INHERIT):
        raise ValueError("the gate's changes enter dev, test or prod (or inherit)")
    before = doc.get("gate_env") if doc.get("gate_env") in ENVIRONMENTS else None
    after = None if to == INHERIT else to
    if before == after:
        return []
    if after is None:
        doc.pop("gate_env", None)
    else:
        doc["gate_env"] = after
    looser = ENVIRONMENTS.index(after or DEFAULT_GATE_ENV) < ENVIRONMENTS.index(before or DEFAULT_GATE_ENV)
    return [{"gate_env": True, "from": before, "to": after, "looser": looser}]
