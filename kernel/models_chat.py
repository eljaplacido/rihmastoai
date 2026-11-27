"""Ask Rihma, by rule: a coding agent asked to answer as Rihmasto's model goes to Models setup (FR-SET1).

"Use Claude Code as the model", "how do I make claude code answer as rihmasto's model?" and "use opencode" ask for
the coding agent already on this machine to answer Rihmasto's text roles (the analyst, the holdout author, the
verifier and Ask Rihma): Models setup's Use Claude Code, Use Codex or Use OpenCode, or `rihmasto models use
<harness>` (kernel/harness_setup.py). Connecting an IDE or a coding agent to Rihmasto over MCP is a different thing,
the IDE journey's; words about an IDE, MCP, a hand-off or the contract stay there.
"""

from __future__ import annotations

import re
from typing import Any

# the words for each harness, and its control on Models setup
AGENTS = (("claude-code", r"claude(?: ?code)?", "models_use_claude"), ("codex", r"codex", "models_use_codex"),
          ("opencode", r"open ?code", "models_use_opencode"))
MODEL = re.compile(r"\b(models?|llm|answers?|answering|roles?|analyst|verifier|instead of an? api key|no api key|"
                   r"api key|subscription|my login|own login|as rihmasto|as rihma|malli\w*)\b")
IDE = re.compile(r"\b(ide|mcp|editor|vs ?code|cursor|connect|hook up|hand ?-?off|contract|workspace|branch|pull "
                 r"request|repo|repository|skills?|context)\b")
BARE = re.compile(r"^\W*(?:please |can i |could i |i want to |let me )?(?:use|switch to|try)\s+(?:my |the )?"
                  r"(?P<agent>[a-z ]{4,14}?)\W*$")


def harness_named(question: str) -> tuple[str, str] | None:
    """The harness and its Models setup control when the words ask for a coding agent as the model; else None."""
    said = " ".join(question.rsplit("\n\nNow: ", 1)[-1].lower().replace("’", "'").split())
    for harness, words, control in AGENTS:
        if not re.search(rf"\b{words}\b", said):
            continue
        bare = BARE.match(said)
        if bare and re.fullmatch(words, bare.group("agent").strip()):
            return harness, control
        if MODEL.search(said) and not IDE.search(said):
            return harness, control
    return None


def answer(question: str, persona: str) -> dict[str, Any] | None:
    """Models setup's Use <agent>, with Take me there and the command; None when the words ask something else."""
    named = harness_named(question)
    if named is None:
        return None
    harness, control = named
    from kernel.harness_model import label_of

    label = label_of(harness)
    text = (f"To have {label} answer Rihmasto's text roles (the analyst, the holdout author, the verifier and Ask "
            f"Rihma) with your own login and no API key in Rihmasto: open Models setup and press Use {label}, or run "
            f"`rihmasto models use {harness} --person \"<your name>\" --persona it`. Test there shows it answers. "
            "It is slower than an API endpoint and spends your own plan. Connecting your IDE to Rihmasto over MCP is "
            "something else: ask \"how do I connect my IDE?\".")
    return {"answer": text, "navigate": {"route": "#/models", "control": control}, "propose": [], "dropped": [],
            "sources": [], "by": "rule", "matches": [control, "models"], "persona": persona}
