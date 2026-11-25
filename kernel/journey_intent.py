"""Which journey a person's plain words ask for (FR-JRN1), by rule, in English and Finnish, with typos.

``recognise`` reads a question into one of:

- ``("journey", name)``: the words name a journey ("how should I get started with a brownfield project", "I have
  a project in C:\\code\\orders", "bring in my repo", "olemassa oleva projekti", "connect my IDE", "first deploy");
- ``("next", None)``: what to do next ("what should I do next", "now what", "mitä seuraavaksi");
- ``("start", None)``: how to start, with nothing that names a journey ("how do I get started", "mistä aloitan");
- ``("guide", None)``: hand-holding, and nothing else ("walk me through it", "hold my hand", "opasta minua");
- None: anything else, which the map, the status answer, a goal's plan or the model answers.

A question that asks where something is ("Where do I assess an existing system?") is the map's, and one that
asks how a project is doing is the status answer's. A topic that another hook or the model also answers
(automations, a deploy, an IDE) needs a cue that asks for guidance ("how do I", "guide me", "walk me through")
before it is a journey. Words a little misspelt ("brownfeild", "exisitng", "olemasa") are read as the word they
are closest to among the words the rules know.
"""

from __future__ import annotations

import difflib
import re

# The words the rules know, for reading a misspelt word as the one it is closest to (only words of 5 letters
# or more are corrected, and only into these: "idea" never becomes "ide").
_WORDS = (
    "brownfield greenfield legacy onboard onboarding existing repository repositories codebase project projects "
    "application system service started starting assessment assess automations automation automate deploy "
    "deployment documents document specification walkthrough through guide hand already import adopt bring "
    "connect cursor claude codex opencode coding agent model models local endpoint first steps next "
    "olemassa oleva olevan olevaa nykyinen projekti projektin projektia koodi järjestelmä sovellus seuraavaksi "
    "opasta ohjaa perehdytä alkuun aloitan aloittaa aloitus käyttöönotto automaatio automaatiot dokumentit "
    "määrittely julkaisu julkaise tuotantoon malli mallin kehitysympäristö "
    # common words kept as they are, so none is read as a known word it looks like
    "start begin where there which about would could should their these those thing things doing going status "
    "state stuck plain please today right write wrote build built rules check checks")
VOCAB = tuple(_WORDS.split())
_KNOWN = frozenset(VOCAB)

WHERE = re.compile(r"^\s*(where|missä|mistä löydän)\b(?! (do|should|can) (i|we) (start|begin))")
GUIDE = (r"\bwalk (me|us) through\b", r"\bhold my hand\b", r"\bhand ?-?holding\b", r"\bguide (me|us)\b",
         r"\bstep[- ]by[- ]step\b", r"\bshow (me|us) how\b", r"\bhelp (me|us)\b", r"\bguided?\b",
         r"\bopasta\w*\b", r"\bohjaa\b", r"\bneuvo\w*\b", r"\bauta\b", r"\baskel askeleelta\b", r"\bkädestä\b")
HOW = (r"\bhow (do|can|should|would|could) (i|we)\b", r"\bhow to\b", r"\bwhat are the steps\b", r"\bwhat steps\b",
       r"\bget(ting)? started\b", r"\bi want to\b", r"\bi need to\b", r"\bmiten\b", r"\bkuinka\b",
       r"\bmitä (pitää|täytyy|tarvitsee)\b", *GUIDE)
# "What should I do?" alone asks what is next; after a problem ("I chose the wrong template, what do I do?") it is
# the model's to answer, so the bare form counts only in a short question.
BARE_NEXT = re.compile(r"^\W*(so |ok |okay |and )?what (should|do|can|must) (i|we) do\W*$")
NEXT = (r"\bwhat (should|do|can|must) (i|we) do (now|next)\b(?!.{0,30}\b(with|to|about|for)\b)",
        r"\bwhat( i|')?s next\b", r"\bwhat is next\b", r"\bwhat next\b", r"\bwhat now\b", r"\bnow what\b",
        r"\bnext (best )?steps?\b", r"\bwhere do (i|we) go from here\b", r"\bwhat( is|'s) left\b",
        r"\bwhat remains\b", r"\bmitä (teen |tehdään |nyt |)?seuraavaksi\b",
        r"\bmitä nyt\b", r"\bseuraava (askel|vaihe)\b", r"\bmitä on jäljellä\b", r"\bmitä minun pitäisi tehdä\b")
START = (r"\bget(ting)? started\b", r"\b(where|how) (do|should|can) (i|we) (start|begin)\b", r"\bfirst steps?\b",
         r"\bnew here\b", r"\bshow me around\b", r"\bmistä (aloitan|aloittaa|lähden)\b", r"\bpääsen alkuun\b",
         r"\balkuun\b", r"\baloitus\b", r"\bwhere to start\b", r"\bhow to start\b", r"\bjust installed\b")
# Words that ask how something is doing: without a cue that asks for guidance, the status answer's (FR-V1-AC-7).
STATUS = re.compile(r"\b(status|doing|going|health|healthy|stuck|waiting|blocked|progress|tilanne|tila|etenee|"
                    r"odottaa|jumissa)\b")
PATH = r"([a-z]:\\|~/|/home/|/users/|/srv/|\\\\|https?://\S+\.git\b|github\.com/|gitlab\.)"
# (journey, strong patterns that name it alone, topic patterns that name it after a cue in HOW)
RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("model", (r"\b(set ?up|setup|configure|connect|add|point)\b.{0,20}\b(a |an |the |my |local |own )?"
               r"(model|llm|endpoint)s?\b", r"\bmodels? setup\b", r"\blocal (model|llm)s?\b",
               r"\b(asett|aseta|asenna|määrit|kytke)\w*\b.{0,20}\bmall", r"\bmallin (asetus|määritys|käyttöönotto)",
               r"\bpaikallinen malli"), (r"\b(llm|ai model|language model|which model)s?\b", r"\bkielimall\w*")),
    ("ide", (r"\b(connect|hook up|use|set ?up|link)\b.{0,25}\b(ide|vs ?code|cursor|claude code|codex|opencode|"
             r"coding agent|my agent)\b", r"\b(ide|kehitysympäristö|koodausagentti)\w*\b.{0,20}\b(kytk|yhdist|liit)",
             r"\b(kytke|yhdistä|liitä)\b.{0,20}\b(ide|kehitysympäristö|koodausagentti|claude code|cursor)"),
     (r"\b(ide|vs ?code|cursor|claude code|codex|opencode|coding agent)\b",)),
    ("brownfield", (r"\bbrown ?-?field\b", r"\blegacy\b", r"\bonboard(ing)?\b.{0,30}\b(project|repo|code|app|system)",
                    r"\bonboard (my|an|our|a|the)\b", r"\bfeed (it )?in\b", r"\bfeed (my|our|an|the)\b",
                    r"\b(existing|my own|an old|our old)\b.{0,15}\b(project|repo|repository|code ?base|codebase|app|"
                    r"application|system|service|code)s?\b",
                    r"\balready (have|got|wrote|built)\b.{0,20}\b(code|project|repo|app|system|codebase)",
                    r"\b(bring|import|adopt|plug|hook)( in| over| up)?\b.{0,20}\b(my|our|an|the|existing)?\s?"
                    r"(project|repo|repository|code|codebase|app)\b", r"\bplug(ging)? in\b",
                    r"\b(i|we) have (a |an |my |our )?(project|repo|repository|code|app)\b.{0,12}\b(in|at|on)\b",
                    r"\bolemassa ?olev\w*\b",
                    r"\b(nykyi|vanha|oma)\w*\b.{0,15}\b(projekt|repo|koodi|järjestelm|sovellu)",
                    r"\b(tuo|liitä|kytke|syötä|perehdytä)\w*\b.{0,20}\b(projekt|repo|koodi|järjestelm|sovellu)",
                    r"\b(minulla|meillä) on (jo )?(valmis )?(koodi|projekti|repo|sovellus|järjestelmä)",
                    PATH), (r"\b(adopt|adoption|scan my folder)\b",)),
    ("documents", (r"\b(start|begin|create|make)\b.{0,30}\b(documents?|docs|spec|specification|material|"
                   r"requirements)\b", r"\b(i have|got|here is|here are)\b.{0,20}\b(documents?|a spec|"
                   r"specification|material|requirements doc)",
                   r"\b(dokumen|asiakirj|määrittely|materiaal)\w*\b.{0,40}\b(projekt|aloit|luo)",
                   r"\b(minulla on|meillä on)\b.{0,20}\b(dokumen|asiakirj|määrittely|materiaal)"), ()),
    ("new_idea", (r"\bnew idea\b", r"\b(an|my|i have an?|got an?) idea\b", r"\bidea for\b", r"\bgreen ?-?field\b",
                  r"\bstart (something|a new|from scratch|fresh)\b", r"\bfrom scratch\b", r"\buusi idea\b",
                  r"\bidea\w*\b.{0,20}\b(uude|projekt)", r"\buusi projekti\b", r"\b(minulla|meillä) on (idea|ajatus)",
                  r"\bnew project\b.{0,20}\b(idea|need)"), ()),
    ("deploy", (r"\bfirst (deploy|deployment|release)\b", r"\b(ensimmäinen) (julkaisu|käyttöönotto)\b"),
     (r"\b(deploy|deployment|release it|ship it|to production|go live|paved road)\b", r"\b(julkai|tuotantoon)\w*")),
    ("automations", (r"\b(set ?up|create|make|add) (an |my |some )?automations?\b", r"\bautomaatio\w* (käyttöön|"
                     r"pystyyn)\b"), (r"\bautomat(e|ion|ions)\b", r"\bautomaatio\w*\b", r"\bschedul\w*\b")),
)


def said(text: str) -> str:
    """The words as the rules read them: lower case, one space, misspelt words read as the closest known one."""
    low = " ".join(str(text or "").lower().replace("\u2019", "'").split())
    return re.sub(r"[a-zåäö]{5,}", _closest, low)


def _closest(m: re.Match[str]) -> str:
    word = m.group(0)
    if word in _KNOWN:
        return word
    near = difflib.get_close_matches(word, VOCAB, n=1, cutoff=0.82)
    return near[0] if near else word


def _any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def journey_named(text: str) -> str | None:
    """The journey the words name: by a strong phrase, or by its topic after a cue that asks for guidance."""
    cue = _any(HOW, text)
    for name, strong, topic in RULES:
        if _any(strong, text) or (cue and topic and _any(topic, text)):
            return name
    return None


# One action on one thing ("how do I pause an automation", "remove a check"): the map's control answers, not a journey.
ONE_ACTION = re.compile(r"\b(pause|resume|remove|delete|rename|edit|stop|disable|enable|dry[ -]?run|run (it )?now|"
                        r"archive|restore|undo|revoke)\b")


def recognise(text: str) -> tuple[str, str | None] | None:
    """What the words ask for, by rule (see the module's docstring), or None."""
    s = said(text)
    if not s or WHERE.search(s):
        return None
    if re.search(r"\bautopilot\b", s) or ONE_ACTION.search(s):
        return None                                      # a named cockpit control is the map's, not a generic start
    name = journey_named(s)
    if name is not None and STATUS.search(s) and not _any(HOW, s):
        return None                                      # "how is the existing project doing": its status
    if name is not None:
        return "journey", name
    if _any(NEXT, s) or BARE_NEXT.search(s):
        return "next", None
    if _any(START, s):
        return "start", None
    if _any(GUIDE, s) and len(s.split()) <= 7:
        return "guide", None
    return None


def asks_how(text: str) -> bool:
    """Whether the words ask how to do something (for grounding the model's answer in a journey's steps)."""
    return _any(HOW, said(text))
