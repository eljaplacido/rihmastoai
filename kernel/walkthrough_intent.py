"""Which walkthrough a person's plain words ask for (FR-WLK1): Ask Rihma offers it as a button.

By rule, in English and Finnish: "I have an existing project", "minulla on olemassa oleva projekti", "new idea",
"uusi idea", "how do I get started", "set up a model" and their kin. With a model, the assistant may suggest one
itself: an answer whose Take me there names a walkthrough's control (cockpit/ui_map.json) offers that one. The
offer is a button; nothing starts until the person presses it.
"""

from __future__ import annotations

import re
from typing import Any

# (walkthrough, patterns): the first that matches wins, so the narrower ones come first.
RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("model", (r"\b(set ?up|setup|configure|connect|add|point)\b.{0,20}"
               r"\b(a |an |the |my |local |own )?(model|llm|endpoint)s?\b",
               r"\bmodels? setup\b", r"\blocal models?\b", r"\b(asett|aseta|asenna|määrit|kytke)\w*\b.{0,20}\bmall",
               r"\bmallin (asetus|määritys|käyttöönotto)", r"\bpaikallinen malli")),
    ("documents", (r"\b(start|begin|create|make)\b.{0,30}\b(documents?|docs|spec|specification|material|folder)\b",
                   r"\b(i have|got|here is|here are)\b.{0,20}"
                   r"\b(documents?|a spec|specification|material|requirements doc)",
                   r"\b(dokumen|asiakirj|määrittely|materiaal)\w*\b.{0,40}\b(projekt|aloit|luo)",
                   r"\b(minulla on|meillä on)\b.{0,20}\b(dokumen|asiakirj|määrittely|materiaal)")),
    ("plug_in", (r"\b(existing|current|old|legacy|my own)\b.{0,15}"
                 r"\b(project|repo|repository|code ?base|app|system|code)\b",
                 r"\bplug(ging)? in\b", r"\bbrown ?-?field\b", r"\bonboard\w*\b", r"\bfeed (it |my |our )?in\b",
                 r"\b(adopt|import|bring in|hook up|connect)\b.{0,20}"
                 r"\b(project|repo|repository|code)",
                 # the folder picker (FR-PICK1): "open the folder picker", "browse for my project's folder"
                 r"\b(folder|file|directory) ?(picker|chooser|explorer|browser|dialog)\b",
                 r"\b(browse|pick|choose|select)\b.{0,25}\b(folder|directory)\b",
                 r"\bkansio\w*\b.{0,20}\b(valit|selai|selaa)", r"\b(valitse|selaa)\b.{0,20}\bkansio",
                 r"\bolemassa ?olev\w*\b", r"\b(nykyi|vanha|oma)\w*\b.{0,15}\b(projekt|repo|koodi|järjestelm|sovellu)",
                 r"\b(tuo|liitä|kytke)\w*\b.{0,20}\b(projekt|repo|koodi)")),
    ("new_idea", (r"\bnew idea\b", r"\b(an|my|i have an?|got an?) idea\b", r"\bidea for\b",
                  r"\bstart (something|a new|from scratch)\b", r"\buusi idea\b", r"\bidea\w*\b.{0,20}\b(uude|projekt)",
                  r"\buusi projekti\b", r"\b(minulla|meillä) on (idea|ajatus)")),
    ("tour", (r"\bget(ting)? started\b", r"\b(where|how) (do|should|can) (i|we) (start|begin)\b", r"\bshow me around\b",
              r"\b(a |the )?tour\b", r"\bnew here\b", r"\bfirst steps?\b", r"\balkuun\b", r"\baloita\w*\b",
              r"\bmistä (aloitan|aloittaa|lähden)", r"\bkierros\b", r"\besittely\b", r"\bopastus\b")),
)
# Words that mean another thing is asked about, though a walkthrough's words are there too.
UNLESS = {"plug_in": r"\b(assess|reassess|arvioi|arviointi)"}
CONTROLS = {"walk_plug_in": "plug_in", "walk_new_idea": "new_idea", "walk_documents": "documents",
            "walk_model": "model", "walk_tour": "tour"}


def recognise(text: str) -> str | None:
    """The walkthrough the words ask for, by rule, or None."""
    said = " ".join(str(text or "").lower().split())
    for name, patterns in RULES:
        if any(re.search(p, said) for p in patterns) and not re.search(UNLESS.get(name, r"$^"), said):
            return name
    return None


def offer(question: str, answer: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The walkthrough to offer beside an answer: by rule from the question, else the one the model's Take me
    there names. None when neither names one. (An answer that is a journey, FR-JRN1, carries the walkthrough in
    its own steps: the chat shows that instead of this offer.)"""
    from kernel.walkthrough import flow

    name, by = recognise(question), "rule"
    nav = (answer or {}).get("navigate") or {}
    if name is None and isinstance(nav, dict) and nav.get("control") in CONTROLS:
        name, by = CONTROLS[nav["control"]], answer.get("by") if answer else "rule"
    if name is None:
        return None
    f = flow(name)
    out = {"name": name, "label": f.label, "about": f.about, "by": by}
    where = named_path(question) if name in ("plug_in", "documents") else None
    if where:            # "adopt the project in C:\dev\x": the walkthrough starts from that folder (FR-PICK1)
        out["said"] = where
    return out


# A folder or a git address named in the words: a drive (C:\...), a share (\\host\...), / or ~, or https://.
_START = r"""(?:[A-Za-z]:[\\/]|\\\\|~[\\/]|/(?=[\w.~]))"""
_PATH = re.compile(r"""(?:^|[\s"'(])(""" + _START + r"""[^\s"'<>|?*]*|https?://\S+)""")
# In quotes a path is taken whole, spaces and all: "C:\Users\me\My Projects\shop", 'D:\Omat tiedostot\x'.
_QUOTED = re.compile(r"""(?:^|[\s(:])["'“”‘’](""" + _START + r"""[^"'“”‘’<>|?*\r\n]*)["'“”‘’]""")


def named_path(text: str) -> str | None:
    """The folder path or git address the words name (a quoted one whole, with its spaces), or None."""
    said = str(text or "")
    quoted = _QUOTED.search(said)
    if quoted and quoted.group(1).strip():
        return quoted.group(1).strip()
    m = _PATH.search(said)
    return m.group(1).rstrip(".,;:)") if m else None
