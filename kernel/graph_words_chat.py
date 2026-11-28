"""Ask Rihma which words the Knowledge graph reads in and which kinds it leaves out (D-0027, FR-TM6), by rule and
without a model: whatever the graph's notes say ("Hidden by your words", "Several readings"), asking says too.

- "which terms are hidden?", "why is a kind missing from the graph?": each hidden term with where it was hidden,
  that the records of a hidden kind are left out before anything is counted, and how many warnings still hold on them;
- "which words does the graph read in?": the words in force here and, across projects, which projects say some
  differently.

The answer carries the way on (the graph's page); changing a term is Vocabulary's and Ask Rihma's "hide" and
"show again".
"""

from __future__ import annotations

import re
from typing import Any

from kernel import graph_hide, vocab, vocab_graph
from kernel.learn import FACTORY_PID

ASKS = re.compile(r"\bhidden\b.*\b(?:terms?|kinds?|words?|graph)\b|\b(?:terms?|kinds?)\b.*\bhidden\b"
                  r"|\b(?:missing|gone|left\s+out|not\s+shown|disappear\w*)\b.*\b(?:graph|kinds?)\b"
                  r"|\bwhich\s+words?\b.*\bgraph\b|\bwords?\b.*\bgraph\b.*\bread\b|\bgraph\b.*\bread\s+in\b")


def asks(low: str) -> bool:
    return bool(ASKS.search(low))


def _where(factory: Any, project: Any) -> tuple[dict[str, Any], list[Any]]:
    mine = [project] if project is not None else [p for p in factory.projects() if p.pid != FACTORY_PID]
    return (vocab.effective(factory, project) if project is not None else vocab.context(factory, None, mine)), mine


def answer(factory: Any, project: Any) -> tuple[str, dict[str, str | None]]:
    """The text and the way on: the hidden terms, the warnings left on them, and the words the graph reads in."""
    eff, mine = _where(factory, project)
    nav: dict[str, str | None] = {"route": f"#/p/{project.pid}/graph" if project is not None else "#/graph",
                                  "control": "graph" if project is not None else "graph_all"}
    hidden = [r for r in eff["terms"].values() if r["hidden"]]
    reading = "its team's and its own words" if project is not None else (
        "this team's words" if eff["team"] else "Rihmasto's shipped words")
    out = [f"The graph reads in {reading}."]
    if hidden:
        said = ", ".join(f"{r['label']} ({vocab.SCOPE_WORD[r['scope']]})" for r in hidden[:8])
        warned = graph_hide.warnings_on(mine, graph_hide.hidden_kinds(eff))
        out.append(f"Hidden here: {said}. Records of a hidden kind are left out before anything is counted, so the "
                   f"counts match what is drawn; {warned} warning{'s' if warned != 1 else ''} still hold"
                   f"{'s' if warned == 1 else ''} on them. Say \"show the {hidden[0]['label'].lower()} term again\" "
                   "to bring it back.")
    else:
        out.append("No term is hidden: every kind of record is in the graph.")
    spread = vocab_graph.mixed(factory, mine, eff) if project is None else None
    return " ".join(out + ([spread["note"]] if spread else [])), nav
