"""Names that look alike to a person (D-0016, FR-ID4-AC-3, FR-ID5-AC-4).

A verified token can still carry a name its holder chose (Keycloak's account console, an editable Okta
profile field). The kernel takes it as the display name of an identity the access file does not list,
so it must not let that name pass for someone the file does list. Two checks, after Unicode's confusable
detection (UTS #39), reduced to what the standard library can do without the confusables data file:

- ``skeleton(name)``: what a name looks like. Compatibility forms folded (NFKD), every mark, format
  character (zero-width space and joiners, direction marks), control and unassigned character dropped,
  case folded, letters of Cyrillic, Greek and Armenian that look like Latin ones mapped to those, and
  the digits and strokes that pass for letters too (``0`` for ``o``; ``1``, ``l`` and ``|`` for ``i``;
  ``rn`` for ``m``); spacing and punctuation do not count. Two names with one skeleton look alike.
- ``disguised(name)``: a name that holds an invisible character, or mixes letters of Latin, Cyrillic,
  Greek, Armenian, Cherokee or Coptic, is disguised whoever it resembles.

Both err towards caution: a name they catch only carries its subject after it, without its invisible
characters (``visible``), "Aino Example (stranger-sub)"; nobody is refused for it.
"""

from __future__ import annotations

import unicodedata

DROPPED = {"Mn", "Me", "Cf", "Cc", "Co", "Cn", "Cs"}
INVISIBLE = {"Cf", "Cc", "Co", "Cn", "Cs"}
LOOKALIKE_SCRIPTS = {"LATIN", "CYRILLIC", "GREEK", "ARMENIAN", "CHEROKEE", "COPTIC"}
_AS_LATIN = str.maketrans({
    # Cyrillic (after case folding, so the capitals are covered too)
    "\u0430": "a", "\u0432": "b", "\u0433": "r", "\u0435": "e", "\u0437": "3", "\u043a": "k", "\u043c": "m",
    "\u043d": "h", "\u043e": "o", "\u043f": "n", "\u0440": "p", "\u0441": "c", "\u0442": "t", "\u0443": "y",
    "\u0445": "x", "\u044c": "b", "\u0455": "s", "\u0456": "i", "\u0458": "j", "\u04bb": "h", "\u0501": "d",
    "\u051b": "q", "\u051d": "w", "\u04cf": "i", "\u04af": "y", "\u0491": "r",
    # Greek
    "\u03b1": "a", "\u03b2": "b", "\u03b3": "y", "\u03b5": "e", "\u03b6": "z", "\u03b7": "n", "\u03b9": "i",
    "\u03ba": "k", "\u03bc": "u", "\u03bd": "v", "\u03bf": "o", "\u03c1": "p", "\u03c4": "t", "\u03c5": "u",
    "\u03c7": "x", "\u03c9": "w", "\u03c3": "o", "\u03c2": "c",
    # Armenian
    "\u0585": "o", "\u057d": "u", "\u0570": "h", "\u0578": "n", "\u0581": "g", "\u0566": "q", "\u0561": "w",
    # Latin letters, digits and strokes that pass for others
    "\u0131": "i", "\u0261": "g", "\u0251": "a", "\u028f": "y", "\u0269": "i", "\u01c0": "i",
    "0": "o", "1": "i", "l": "i", "|": "i", "!": "i",
})
_SEQUENCES = (("rn", "m"), ("vv", "w"))


def skeleton(name: str) -> str:
    """What ``name`` looks like (see the module's text): two names with one skeleton look alike."""
    text = "".join(c for c in unicodedata.normalize("NFKD", name) if unicodedata.category(c) not in DROPPED)
    text = text.casefold().translate(_AS_LATIN)
    text = "".join(c for c in text if c.isalnum())
    for seq, looks_like in _SEQUENCES:
        text = text.replace(seq, looks_like)
    return text


def _script(char: str) -> str | None:
    if not char.isalpha():
        return None
    word = unicodedata.name(char, "").split(" ", 1)[0]
    return word if word in LOOKALIKE_SCRIPTS else None


def visible(name: str) -> str:
    """``name`` without its invisible characters, as a record shows it."""
    return "".join(c for c in name if unicodedata.category(c) not in INVISIBLE).strip()


def disguised(name: str) -> bool:
    """Whether ``name`` holds an invisible character or mixes the letters of scripts that look alike."""
    if any(unicodedata.category(c) in INVISIBLE for c in name):
        return True
    scripts = {_script(c) for c in unicodedata.normalize("NFKC", name)} - {None}
    return len(scripts) > 1
