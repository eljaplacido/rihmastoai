"""Ask Rihma about enforcement levels per environment, by rule and without a model (FR-ENF1, FR-ENF2).

A question about how strictly Rihmasto holds dev, test and production (advise or enforce, a human check, required
reviews, branch protection, GitHub environments) is answered from the records, with Take me there to the project's
Enforcement view or to Settings for the platform:

- "how is production enforced here?": the levels in force per environment, each cell's scope (the project's own,
  the platform's, the default), the reviews waiting and the last outcomes;
- "require review in test", "turn off checks in production", "block deploys to prod", "make staging require
  review for legal", "use the split", "treat eu-west as production", "the gate's changes go to testing": a
  proposal (``enforcement_levels_set``) with its preview's lines; the person confirms it in the cockpit, signed with
  their name. Inside a project the proposal is the project's own unless the question says the platform, every
  project or all projects ("everywhere" means every stage, not every project).
- A change that loosens (a level, a name placed in a less strict stage) carries the person's own reason, said in
  the question ("... because the demo week ends Friday"); without one Rihma asks for it and proposes nothing.

The assistant itself writes nothing.
"""

from __future__ import annotations

import re
from typing import Any

from kernel import enforcement as ke
from kernel.enforcement_guard import recent
from kernel.enforcement_preview import preview

PHRASES = ("enforcement", "enforce ", "enforced", "advise only", "require review", "require-review",
           "human check", "dev test prod", "dev/test/prod", "dev, test", "branch protection", "github environment",
           "required reviewer", "levels per environment", "advise or enforce", "split between dev", "the split",
           "advise everywhere", "strict preset", "ruleset")
ENV_WORDS = {"dev": ("dev", "development"), "test": ("test", "testing", "staging"), "prod": ("prod", "production")}
FAMILY_WORDS = {"quality": ("quality", "tests"), "security": ("security",), "legal": ("legal", "licence", "license"),
                "governance": ("governance",)}
LEVEL_WORDS = (("require_review", ("require review", "require-review", "require a review", "needs review",
                                   "requires review", "require reviews")),
               ("enforce", ("enforce", "block", "hold")), ("advise", ("advise", "advice", "just note")),
               ("off", ("turn off", "switch off", "no checks")))
CONTEXT = ("check", "checks", "deploy", "deploys", "deployment", "deployments", "release", "releases", "review",
           "reviews", "gate", "changes", "level", "levels")
PRESET_WORDS = {"split": ("the split", "use split", "usual split"), "strict": ("strict",),
                "advise": ("advise everywhere", "advise in every")}
PLATFORM_WORDS = ("platform", "every project", "all projects", "all my projects", "for all of them")
ASKING = ("how ", "what ", "is ", "are ", "where ", "why ", "does ", "do ", "which ", "who ")   # asks how things stand
SETTING = re.compile(r"\b(set|make|turn|change|use|switch|require|enforce|advise|block|hold|treat|place|count|send"
                     r"|go|goes|enter|enters)\b")
PLACE = re.compile(r"\b(?:treat|count|place)\s+([a-z0-9][a-z0-9._/-]{0,59})\s+as\s+(?:a\s+|the\s+)?([a-z]+)"
                   r"|\b([a-z0-9][a-z0-9._/-]{0,59})\s+counts?\s+as\s+(?:a\s+|the\s+)?([a-z]+)")
GATE = re.compile(r"\bgate(?:'s)?\b[^.]*?\b(?:enter|enters|go|goes|into)\s+(?:to\s+)?(?:the\s+)?([a-z]+)")
REASON = re.compile(r"\b(?:because|since|reason:)\s*(.{3,300})$")
_SPACE = re.compile(r"\s+")


def _low(question: str) -> str:
    return _SPACE.sub(" ", question.lower()).strip()


def _has(low: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", low) for w in words)


def _level(low: str) -> str | None:
    return next((lvl for lvl, words in LEVEL_WORDS if _has(low, words)), None)


def _envs(low: str) -> list[str]:
    return [e for e, words in ENV_WORDS.items() if _has(low, words)]


def _families(low: str) -> list[str]:
    return [f for f, words in FAMILY_WORDS.items() if _has(low, words)]


def _stage(word: str) -> str | None:
    return next((e for e, words in ENV_WORDS.items() if word in words), None)


def asks(question: str) -> bool:
    """Whether the question is about enforcement: its phrases, a level for a stage ("turn off checks in
    production"), placing a stage's name, or the stage the gate's changes enter."""
    low = _low(question)
    if any(p in low + " " for p in PHRASES):
        return True
    if _level(low) and _envs(low) and (_families(low) or _has(low, CONTEXT)):
        return True
    return bool(_placing(low))


def _placing(low: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    m = PLACE.search(low)
    if m:
        name, word = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        if _stage(word):
            out["names"] = {name: _stage(word)}
    g = GATE.search(low)
    if g and _stage(g.group(1)):
        out["gate_env"] = _stage(g.group(1))
    return out


def _levels_asked(low: str) -> dict[str, Any] | None:
    level, envs = _level(low), _envs(low)
    if level is None or not envs:
        return None
    fams = _families(low) or list(ke.FAMILIES)
    return {"levels": {e: {f: level for f in fams} for e in envs}}


def wanted(question: str) -> dict[str, Any] | None:
    """The change a question asks for (levels, a preset, a name placed, the gate's stage), or None when it only
    asks how things stand."""
    low = _low(question)
    if not SETTING.search(low) or low.startswith(ASKING):
        return None
    plain = REASON.sub("", low)                      # the reason's words never pick a level or a stage
    placing = _placing(plain)
    if placing:
        return placing
    preset = next((k for k, words in PRESET_WORDS.items() if any(w in plain for w in words)), None)
    return {"preset": preset} if preset else _levels_asked(plain)


def reason_of(question: str) -> str:
    """The person's own reason, from "because ...", "since ..." or "reason: ..." in their words (as they wrote it)."""
    said = _SPACE.sub(" ", question).strip()
    m = REASON.search(said.lower())
    return said[m.start(1):].rstrip(".").strip()[:300] if m else ""


def _out(answer: str, route: str | None, control: str | None, propose: list | None = None) -> dict[str, Any]:
    return {"answer": answer, "navigate": {"route": route, "control": control} if route else None,
            "propose": propose or [], "dropped": [], "sources": [], "by": "map", "matches": ["enforcement"]}


def _word(level: str) -> str:
    return level.replace("_", " ")


def _state(factory: Any, project: Any) -> str:
    d = ke.describe(factory, project)
    parts = []
    for env in ke.ENVIRONMENTS:
        cells = [c for c in d["cells"] if c["env"] == env]
        own = sorted({c["scope"] for c in cells})
        levels = sorted({c["level"] for c in cells}, key=ke.RANK.__getitem__)
        said = _word(levels[0]) if len(levels) == 1 else ", ".join(
            f"{c['family']} {_word(c['level'])}" for c in cells)
        parts.append(f"{env}: {said} (from {' and '.join(own)})")
    return "; ".join(parts)


def _platform(question: str) -> bool:
    """The question names every project; "everywhere" names every stage, not every project."""
    return _has(_low(question), PLATFORM_WORDS)


def answer(factory: Any, question: str, project: Any, persona: str,
           holding: tuple[str, ...] | None = None) -> dict[str, Any] | None:
    """The answer, or None when the question is not about enforcement levels."""
    if not asks(question):
        return None
    scope = None if project is None or _platform(question) else project
    route, control = (("#/settings", "enforcement_platform") if scope is None
                      else (f"#/p/{scope.pid}/enforcement", "enforcement_levels"))
    where = "the platform (every project that has not set its own)" if scope is None else str(scope.meta.get("title"))
    change = wanted(question)
    if change is not None:
        may = persona in ke.SETTERS or any(p in ke.SETTERS for p in holding or ())
        return _change_answer(factory, scope, where, change, (persona, may), (route, control), reason_of(question))
    return _out(_status(factory, scope, where), route, control)


def _loosens(seen: dict[str, Any]) -> bool:
    return any(c.get("looser") for c in seen.get("placing") or []) or any(
        ke.RANK[c["to"]] < ke.RANK[c["from"]] for c in seen["changes"])


def _change_answer(factory: Any, scope: Any, where: str, change: dict[str, Any], who: tuple[str, bool],
                   nav: tuple[str, str], reason: str) -> dict[str, Any]:
    persona, may = who
    seen = preview(factory, scope, **change)
    if not seen["changes"] and not seen.get("placing"):
        return _out(f"That is already how {where} is set: {_state(factory, scope)}.", *nav)
    lines = " ".join(seen["lines"])
    if not may:
        return _out(f"{lines} A business owner, IT, compliance or a developer sets it, on the view I open.", *nav)
    if _loosens(seen) and not reason:
        return _out(f"For {where}: {lines} This makes a stage less strict, so it needs your reason, recorded with the "
                    "change. Say it with the request, for example: \"... because the demo week ends Friday\", or "
                    "write it on the view I open.", *nav)
    pid = scope.pid if scope is not None else None
    prop = {"action": "enforcement_levels_set", "why": lines, "persona": persona, "project": pid,
            "args": {"project": pid, **change, **({"reason": reason} if reason else {})}}
    said = f" Your reason goes with it: {reason}." if reason else ""
    return _out(f"For {where}: {lines}{said} I can make the change; you confirm it, signed with your name.", *nav,
                [prop])


def _status(factory: Any, scope: Any, where: str) -> str:
    text = f"Enforcement for {where}: {_state(factory, scope)}."
    if scope is not None:
        rows = recent(scope, limit=50)
        waiting = [r for r in rows if r.get("outcome") in ("review", "refused")]
        text += (f" The last {ke.count(len(rows), 'outcome')} recorded here, {len(waiting)} of them asking a person."
                 if rows else " Nothing has crossed into an environment here yet.")
    return text + (" Advise notes and nudges; require review opens a card for the named reviewer; enforce holds the "
                   "work until they decide. The view also reads your GitHub environments, branch protection and "
                   "rulesets, read only.")
