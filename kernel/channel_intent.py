"""Whether a person asks Rihma to put a question to a coding agent, and what the question is (FR-CHN3).

FR-CHN2 matched any "ask <agent>" in a message, so questions that only mention an agent were posted to it: "what
should I ask the coding agent to do next?" became "@coding-agent ...: To do next?", and a bare "ask claude code"
became the question "Ask claude code". Here:

- ``request``: the words ask Rihma to consult an agent only when they are a request to Rihma: at the start of the
  message or of a sentence, after at most a greeting, Rihma's name, "please" or "can you / could you / would you"
  ("Rihma, consult Claude Code on ...", "Can you check with the agent whether ...", "Thanks. Now ask Codex ...").
  "What should I ask ...", "Can I ask my agent ...", "Should we ask ..." and "how do I ask ..." are questions to
  Rihma about agents, answered as such;
- ``question``: what is left to ask, without the request ("to" and "about" dropped); empty when nothing is, and
  then Rihma asks the person what to ask (``what_to_ask``) instead of posting an empty question.
"""

from __future__ import annotations

import re

_GREETING = r"(?:(?:hey|hi|hello|ok|okay|so|now|then|and|also|thanks|thank you|great|good)\b[\s,.!]*)*"
_NAME = r"(?:(?:rihma|@[a-z0-9._-]+)\b[\s,:]*)?"
_SOFT = (r"(?:please\s+|pls\s+|(?:can|could|would|will) you(?: please)?\s+|go ahead and\s+|"
         r"i(?:'d| would)? (?:like|want) you to\s+|voisitko\s+|voitko\s+|ole hyvä ja\s+)?")
_LEAD_OK = re.compile(rf"^\s*{_GREETING}{_NAME}{_GREETING}{_SOFT}{_GREETING}$", re.I)
_SENTENCE = re.compile(r"[.!?;\n]\s*")
_LEAD = re.compile(r"^(?:on|about|regarding|for|and|to|whether to)\b[\s,:]*", re.I)
_WORD = re.compile(r"[^\W\d_]{2,}", re.U)


def _prefix(text: str, start: int) -> str:
    """The words of the sentence before ``start``."""
    before = text[:start]
    cuts = [m.end() for m in _SENTENCE.finditer(before)]
    return before[cuts[-1]:] if cuts else before


def request(pattern: re.Pattern[str], text: str) -> re.Match[str] | None:
    """The first match of ``pattern`` that is a request to Rihma (see the module's doc), or None."""
    for m in pattern.finditer(text or ""):
        if _LEAD_OK.match(_prefix(text, m.start())):
            return m
    return None


def question(text: str, m: re.Match[str]) -> str:
    """What is left to ask once the request is taken off, capitalised; "" when nothing is."""
    rest = text[m.end():].strip(" ,:;-\n\t")
    rest = _LEAD.sub("", rest).strip()
    if len(_WORD.findall(rest)) < 2 and not re.search(r"\b[A-Z]{1,6}-[A-Z0-9-]+\b", rest):
        return ""
    return rest[0].upper() + rest[1:]


def what_to_ask(label: str, mid: str | None = None) -> str:
    """Rihma's answer when a person asked it to ask an agent but said nothing to ask."""
    return (f"What should I ask {label}? Write the question after the name, such as \"Ask {label}: which tests "
            "cover the loan list?\", and I put it to the agent here" + (f" (nothing was posted for {mid})." if mid
                                                                         else "."))
