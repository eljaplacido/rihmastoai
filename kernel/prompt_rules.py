"""The rules people approved from their feedback, kept by every prompt a Rihma agent is given (FR-HEAL1, D-0024
item 5).

"This is unclear" or "This is wrong" on an agent's answer becomes a **prompt** proposal (kernel/feedback.py); once a
person approves it, its sentence is kept in ``heal/prompt_rules.json``. This is the one hook every agent prompt
reads it through: the intake panel's perspectives (kernel/intake.py, and on material added later), the spec
(kernel/spec.py), Ask Rihma (kernel/assistant.py), goal help (kernel/copilot.py) and the agent channel's answers
(kernel/channel_rihma.py). With no approved rule a prompt is unchanged, character for character.
"""

from __future__ import annotations

from typing import Any

MAX_RULES = 12
MAX_CHARS = 400


def rules(factory: Any) -> list[str]:
    """The approved prompt rules, oldest first, each cut to ``MAX_CHARS``; [] without a factory or a rule."""
    if factory is None:
        return []
    from kernel import feedback

    try:
        changes = feedback.applied(factory, "prompt")
    except (OSError, ValueError):
        return []
    return [str(c["to"]).strip()[:MAX_CHARS] for c in changes if str(c.get("to") or "").strip()][-MAX_RULES:]


def block(factory: Any) -> str:
    """The rules as a prompt section, or "" when there is none."""
    kept = rules(factory)
    if not kept:
        return ""
    return ("\nRules the people of this factory approved from their feedback on Rihma's answers; keep to them:\n"
            + "".join(f"- {r}\n" for r in kept))


def kept(factory: Any, prompt: str) -> str:
    """``prompt`` with the approved rules after it (unchanged when there is none)."""
    return prompt + block(factory)
