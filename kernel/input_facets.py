"""The facet checklist an input is read against, and what an input states (docs/guides/inputs.md).

A facet is one thing the people who build a solution need to know: its users and roles, its outcomes
and how success is measured, its scope, its data and how sensitive that is, its integrations, its
non-functional needs (security, privacy, availability, accessibility, performance), where it is
deployed, its constraints and how it is accepted. Each facet has the words a heading, a label or a
question names it by, in English and Finnish, and the cues that state it in running text.

Reading is by rule, never by a model:
- a heading whose words name a facet states it, with the lines of its section (a section that says
  only "TBD", "open" or "avoin" leaves it open, and that is recorded);
- a labelled line ("Users: ...", "Käyttäjät: ...") states it on that line;
- a sentence with one of the facet's cues states it on its line;
- an author's requirement (an id such as TLR-001 with its statement) and its given / when / then
  criteria, which state the acceptance facet;
- an author's decision ("D1: ...", "Decision 2: ...", "Päätös 3: ...", or an item under a
  "Decisions" heading), which states the facets its words name.
"""

from __future__ import annotations

import re
from typing import Any

MATURITY_ORDER = ("explore", "demo", "pilot", "production")


def _rx(body: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w-])(?:" + body + r")(?![\w-])", re.IGNORECASE)


# facet: label, perspective, the maturity from which a gap is asked, whether its gap blocks, the words
# that name it, the cues that state it, and the question the checklist asks with its proposal first.
FACETS: dict[str, dict[str, Any]] = {
    "users_roles": {
        "label": "users and roles", "perspective": "end_user", "from": "explore", "blocking": True,
        "words": r"users?|end[- ]users?|roles?|personas?|actors?|audiences?|stakeholders?|käyttäj\w*|rooli\w*"
                 r"|kohderyhm\w*|sidosryhm\w*",
        "cues": r"users? (?:are|is|will be|include)|used by|as an? [\w-]+(?: [\w-]+)?,? i want|käyttäji(?:nä|ä)"
                r"|käyttäjät ovat|roolit ovat",
        "question": "Who will use it, and in which roles?",
        "options": ["the people who raised the need, all with the same rights",
                    "two roles: people who use it and people who approve", "several roles, named per task"]},
    "outcomes": {
        "label": "outcomes and success measures", "perspective": "business", "from": "explore", "blocking": True,
        "words": r"goals?|objectives?|outcomes?|success(?: measures?| criteria| metrics?)?|kpis?|metrics?|benefits?"
                 r"|tavoit\w*|hyöt\w*|hyödy\w*|mittari\w*|onnistu\w*",
        "cues": r"(?:the |our )?(?:goal|objective|aim|purpose) (?:is|are|was)|success (?:is|means|will be)"
                r"|measured (?:as|by)|kpis?|tavoitteena|tavoite on|mittari\w*",
        "question": "What outcome should it bring, and how will success be measured?",
        "options": ["the need as stated is met; no measure beyond that",
                    "a measure against today's baseline, checked after a month", "a target a person names"]},
    "scope": {
        "label": "scope and out of scope", "perspective": "delivery", "from": "explore", "blocking": True,
        "words": r"scope|out of scope|in scope|non-goals?|not included|exclusions?|boundar(?:y|ies)|first version"
                 r"|mvp|rajau\w*|laajuu\w*|ensimmäi\w* versio\w*",
        "cues": r"out of scope|in scope|not in scope|non-goals?|excluded|not included|first version|mvp"
                r"|rajat\w* pois|ei kuulu|ei sisälly|ensimmäi\w* versio\w*",
        "question": "What is in scope for the first version, and what is out of it?",
        "options": ["only what the input describes; anything else is out of scope",
                    "the smallest version that shows the outcome", "the whole input, in one version"]},
    "data": {
        "label": "data and its sensitivity", "perspective": "it_security", "from": "demo", "blocking": True,
        "words": r"data|data model|data sources?|sensitivity|sensitive|confidential|data classification|tiedot"
                 r"|aineisto\w*|arkaluonteis\w*|luottamuksellis\w*|tietoluok\w*",
        "cues": r"personal data|sensitive|confidential|classified|public data|pii|sample data|real data"
                r"|production data|test data|data (?:is|are|comes?|includes?|holds?)|arkaluonteis\w*"
                r"|luottamuksellis\w*|henkilötie\w*",
        "question": "What data will it hold, and how sensitive is it?",
        "options": ["made-up sample data; nothing personal or confidential",
                    "internal data, no personal data", "personal or confidential data"]},
    "integrations": {
        "label": "integrations", "perspective": "it_security", "from": "pilot", "blocking": False,
        "words": r"integrations?|interfaces?|apis?|external systems?|systems?|connections?|connectors?|webhooks?"
                 r"|integraati\w*|rajapin\w*|järjestelm\w*|liittym\w*",
        "cues": r"integrat\w*|apis?|webhooks?|graphql|sftp|import\w* from|sync\w* (?:with|to|from)"
                r"|connects? (?:to|with)|through the existing|from the [\w'-]+ system|to the [\w'-]+ system"
                r"|google drive|drive folders?|shared drives?"
                r"|integraati\w*|rajapin\w*",
        "question": "Which existing systems must it read from or write to?",
        "options": ["none: it stands alone", "one system, read only", "several systems, reading and writing"]},
    "security": {
        "label": "security", "perspective": "it_security", "from": "pilot", "blocking": False,
        "words": r"security|secure|authenticat\w*|authori[sz]\w*|access control|identity|sign[- ]in|single sign-on"
                 r"|sso|log ?in|permissions?|mfa|tietoturv\w*|tunnistautu\w*|kirjautu\w*|käyttöoikeu\w*"
                 r"|pääsynhallin\w*",
        "cues": r"sso|single sign-on|authenticat\w*|authori[sz]\w*|mfa|two-factor|multi-factor|encrypt\w*"
                r"|access control|role-based access|rbac|entra id|azure ad|okta|oauth|oidc|saml|signs? in with"
                r"|tietoturv\w*|tunnistautu\w*|kirjautu\w*|kertakirjau\w*|käyttöoikeu\w*|salau\w*|salat\w*",
        "question": "Who may sign in, what may each do, and which security rules must it meet?",
        "options": ["the organisation's sign-in; every signed-in user has the same rights",
                    "the organisation's sign-in with roles", "no sign-in: a shared page"]},
    "privacy": {
        "label": "privacy", "perspective": "it_security", "from": "pilot", "blocking": False,
        "words": r"privacy|gdpr|personal data|data protection|retention|consent|tietosuoj\w*|henkilötie\w*"
                 r"|säilytys\w*|suostumu\w*",
        "cues": r"gdpr|privacy|personal data|data protection|retention|retained|deleted \d+ days|consent"
                r"|anonymi[sz]\w*|pseudonymi[sz]\w*|tietosuoj\w*|henkilötie\w*|säilytysai\w*|suostumu\w*",
        "question": "Does it handle personal data, and which privacy rules apply (retention, consent)?",
        "options": ["no personal data beyond users' names", "personal data, kept only as long as needed",
                    "personal data under a named retention rule"]},
    "availability": {
        "label": "availability", "perspective": "operations", "from": "production", "blocking": False,
        "words": r"availability|uptime|sla|service level|reliability|support hours|business continuity|backups?"
                 r"|downtime|saatavuu\w*|palvelutaso\w*|varmuuskopi\w*",
        "cues": r"availability|uptime|sla|24/7|24x7|office hours|business hours|downtime|rto|rpo|backups?"
                r"|failover|saatavuu\w*|palveluai\w*|virka-ai\w*|toimistoaika\w*|varmuuskopi\w*|käyttökatko\w*",
        "question": "When must it be available, and how long may it be down?",
        "options": ["office hours; a day's outage is tolerable", "every day, back within hours",
                    "around the clock, back within minutes"]},
    "accessibility": {
        "label": "accessibility and languages", "perspective": "end_user", "from": "pilot", "blocking": False,
        "words": r"accessib\w*|wcag|a11y|languages?|locali[sz]ation|translations?|saavutettav\w*|kieli\w*|kielet"
                 r"|kieliversi\w*",
        "cues": r"accessib\w*|wcag|screen readers?|keyboard only|a11y|in (?:english|finnish|swedish)|bilingual"
                r"|saavutettav\w*|ruudunlukij\w*|suomeksi|ruotsiksi|englanniksi|kieliversi\w*",
        "question": "Which accessibility and language needs must it meet?",
        "options": ["WCAG 2.2 AA, in the input's language", "WCAG 2.2 AA, in two languages",
                    "no screens, so none"]},
    "performance": {
        "label": "performance", "perspective": "operations", "from": "production", "blocking": False,
        "words": r"performance|response times?|latency|load|scalab\w*|capacity|volumes?|throughput|speed|fast"
                 r"|suorituskyk\w*|vasteai\w*|kuormitu\w*|skaalautu\w*",
        "cues": r"performance|response times?|latency|throughput|within \d+\s?(?:ms|milliseconds?|seconds?|s)"
                r"|under \d+\s?(?:ms|milliseconds?|seconds?)|\d+ (?:concurrent |simultaneous )?users"
                r"|requests? per (?:second|minute)|per second|scalab\w*|peak load"
                r"|within (?:one|two|five|ten) seconds?|suorituskyk\w*|vasteai\w*|kuormitu\w*|\d+ samanaikais\w*",
        "question": "How many people use it at once, and how fast must it answer?",
        "options": ["a few dozen people; pages answer within a second", "hundreds at once; within a second",
                    "a batch job; speed does not matter"]},
    "deployment": {
        "label": "deployment and environments", "perspective": "operations", "from": "pilot", "blocking": False,
        "words": r"deploy\w*|hosting|hosted|environments?|infrastructure|platform|cloud|on[- ]prem\w*|runtime"
                 r"|käyttöön\w*|ympäristö\w*|infrastruktuur\w*|alusta\w*|pilv\w*",
        "cues": r"deploy\w*|hosted (?:on|in|at)|hosting|on[- ]prem\w*|azure|aws|gcp|google cloud|kubernetes|k8s"
                r"|cloud run"
                r"|docker|containers?|staging|production environment|test environment|environments|paved road"
                r"|runs? on (?:the |our |an? |its )?(?:[\w'-]+ ){0,3}(?:servers?|cloud|tenant|platform|cluster"
                r"|premises)|ympäristö\w*|pilvipalvel\w*|konesali\w*",
        "question": "Where will it run, and in which environments?",
        "options": ["the paved road IT configured for this maturity", "the organisation's own cloud tenant",
                    "the organisation's own servers"]},
    "constraints": {
        "label": "constraints", "perspective": "business", "from": "pilot", "blocking": False,
        "words": r"constraints?|limitations?|budget|timeline|schedule|deadlines?|restrictions?|regulations?"
                 r"|rajoit\w*|reunaeh\w*|budjet\w*|aikataul\w*|määräai\w*",
        "cues": r"budget|deadline|by (?:q[1-4]|january|february|march|april|june|july|august|september|october"
                r"|november|december|the end of \w+)|must use|must run on|has to use|constraints?|cannot use"
                r"|may not use|budjet\w*|määräai\w*|aikataul\w*|rajoit\w*|reunaeh\w*|on käytettävä|pitää käyttää",
        "question": "Which constraints apply: a budget, a deadline, a technology or a rule it must follow?",
        "options": ["none beyond the paved road's", "a deadline a person names", "a budget a person names"]},
    "acceptance": {
        "label": "acceptance criteria", "perspective": "delivery", "from": "demo", "blocking": False,
        "words": r"acceptance(?: criteria| tests?)?|accept\w*|criteria|definition of done|test cases?|tests?"
                 r"|verification|hyväksymis\w*|hyväksyn\w*|valmiin määritelm\w*|testitapau\w*|testa\w*",
        "cues": r"given\b.+\bwhen\b.+\bthen|acceptance criteria|accepted when|definition of done|acceptance tests?"
                r"|hyväksymiskriteer\w*|hyväksytään,? kun|oletetaan\b.+\bkun\b.+\bniin",
        "question": "How will you accept it: what must you see working?",
        "options": ["the analyst's criteria, approved with the plan", "a demo a person accepts",
                    "criteria a person writes"]},
}
WORDS = {f: _rx(spec["words"]) for f, spec in FACETS.items()}
CUES = {f: _rx(spec["cues"]) for f, spec in FACETS.items()}
FACET_IDS = tuple(FACETS)

HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
LABEL = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*)?(?P<label>[^:*|#]{2,40}?)(?:\*\*)?\s*:\s*(?:\*\*)?\s*(?P<value>\S.*)$")
PLACEHOLDER = re.compile(r"^\s*(?:[-*+]\s+)?(?:tbd|tbc|todo|to be (?:decided|defined|confirmed)|open|unknown|n/?a"
                         r"|-+|\?+|avoin|auki|myöhemmin|päätetään myöhemmin)\s*[.!]?\s*$", re.IGNORECASE)
# An author's requirement: an id with a number at its end (TLR-001, FR-KRIT-7) and its statement. A
# criterion id (AC-1), a decision id (D-1, ADR-2) and the canon's own ids (Q-1, A-1, C-1) are not.
REQUIREMENT = re.compile(r"^\s*(?:#{1,6}\s*)?(?:[-*+]\s+)?(?:\*\*)?(?P<id>[A-Z][A-Z0-9]{0,11}(?:-[A-Z0-9]{1,12}){0,3}"
                         r"-\d{1,4})(?:\*\*)?\s*(?:[:.)]|\s[-–])\s*(?:\*\*)?\s*(?P<text>\S.*)$")
NOT_REQUIREMENT = re.compile(r"^(?:AC|D|DEC|ADR|Q|A|C|T|S|E|F|CM)-\d+$|-AC-\d+$")
DECISION = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*)?(?P<id>(?:D|DEC|ADR)-?\d{1,3}|decision \d{1,3}|päätös \d{1,3})"
                      r"(?:\*\*)?\s*[:.)]\s*(?:\*\*)?\s*(?P<text>\S.*)$", re.IGNORECASE)
DECISIONS_HEADING = _rx(r"decisions?|decided|decision log|päätökset|päätös\w*|linjauks\w*")
LIST_ITEM = re.compile(r"^\s*(?:[-*+•]|\d{1,3}[.)])\s+(?P<text>\S.*)$")
MARKER = re.compile(r"^(?:[-*+•]|\d{1,3}[.)])\s+")
GHERKIN = re.compile(r"\b(?:given|oletetaan)\b\s*(?P<given>.*?)\s*,?\s*\b(?:when|kun)\b\s*(?P<when>.*?)\s*,?\s*"
                     r"\b(?:then|niin)\b\s*(?P<then>.+)$", re.IGNORECASE)
GHERKIN_STEP = re.compile(r"^\s*(?:[-*+]\s+)?(?P<step>given|when|then|and|oletetaan|kun|niin|ja)\b\s*(?P<text>.*)$",
                          re.IGNORECASE)
CRITERION_LABEL = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*)?(?:AC-?\d{1,3}|acceptance|criterion|hyväksymiskriteeri)"
                             r"(?:\*\*)?\s*:\s*(?P<then>\S.*)$", re.IGNORECASE)
MAX_CUES = 4          # cue facts kept per facet and document: enough to show, never the whole text
MAX_QUOTE = 300


def facets_named(text: str) -> list[str]:
    """The facets a heading, a label or a question names, by their words and cues."""
    return [f for f in FACET_IDS if WORDS[f].search(text) or CUES[f].search(text)]


def facets_stated(text: str) -> list[str]:
    """The facets a sentence states in running text, by their cues only."""
    return [f for f in FACET_IDS if CUES[f].search(text)]


def required(facet: str, maturity: str) -> bool:
    """Whether the checklist asks a facet's gap at this maturity (explore asks the fewest)."""
    return MATURITY_ORDER.index(FACETS[facet]["from"]) <= MATURITY_ORDER.index(maturity)


def _quote(lines: list[str], first: int, last: int) -> str:
    """The lines' own words, without their list markers, cut to a quote's length."""
    text = " ".join(MARKER.sub("", x.strip()) for x in lines[first - 1:last] if x.strip())
    return text if len(text) <= MAX_QUOTE else text[:MAX_QUOTE - 1].rstrip() + "…"


def _fact(facet: str, lines: list[str], first: int, last: int, how: str) -> dict[str, Any]:
    return {"facet": facet, "lines": [first, last], "how": how, "text": _quote(lines, first, last)}


def headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """Each markdown heading: its line, its level and its text, outside code fences."""
    out, fenced = [], False
    for n, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        m = None if fenced else HEADING.match(line)
        if m:
            out.append((n, len(m.group(1)), m.group(2).strip()))
    return out


def sections(lines: list[str]) -> list[tuple[int, str, int, int]]:
    """Each heading with the lines its section holds (first, last), up to the next heading."""
    marks = headings(lines)
    ends = [n for n, _, _ in marks[1:]] + [len(lines) + 1] if marks else []
    return [(n, text, n + 1, end - 1) for (n, _, text), end in zip(marks, ends, strict=True)]


def _content(lines: list[str], first: int, last: int) -> list[int]:
    return [n for n in range(first, last + 1) if lines[n - 1].strip() and not PLACEHOLDER.match(lines[n - 1])]


Covered = set[tuple[str, int]]   # (facet, line) pairs a fact already states; ("*", line) in a facet's section


def _section_facts(lines: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Covered]:
    """Facts from headings that name a facet, the facets a heading leaves open, and the lines covered."""
    facts: list[dict[str, Any]] = []
    left_open: list[dict[str, Any]] = []
    covered: Covered = set()
    for at, text, first, last in sections(lines):
        body = _content(lines, first, last)
        for facet in (f for f in FACET_IDS if WORDS[f].search(text)):
            if body:
                facts.append(_fact(facet, lines, body[0], body[-1], "section"))
                covered.update((key, n) for n in range(at, last + 1) for key in (facet, "*"))
            else:      # the heading, up to its "TBD": the lines that leave it open
                said = [n for n in range(first, last + 1) if lines[n - 1].strip()]
                left_open.append({"facet": facet, "lines": [at, max([at, *said])], "how": "left open"})
    return facts, left_open, covered


def _label_facts(lines: list[str], covered: Covered) -> list[dict[str, Any]]:
    """Facts from labelled lines ("Users: warehouse staff") a section did not already cover."""
    facts = []
    for n, line in enumerate(lines, 1):
        m = LABEL.match(line)
        if not m or HEADING.match(line) or PLACEHOLDER.match(m.group("value")) or len(m.group("label").split()) > 4:
            continue
        for facet in (f for f in FACET_IDS if WORDS[f].search(m.group("label")) and (f, n) not in covered):
            facts.append(_fact(facet, lines, n, n, "label"))
            covered.add((facet, n))
    return facts


def _cue_facts(lines: list[str], covered: Covered) -> list[dict[str, Any]]:
    """Facts from sentences whose cues state a facet, at most a few per facet."""
    facts: list[dict[str, Any]] = []
    kept: dict[str, int] = {}
    fenced = False
    for n, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if fenced or HEADING.match(line) or not line.strip():
            continue
        for facet in facets_stated(line) if ("*", n) not in covered else ():   # a facet's own section rules
            if (facet, n) in covered or kept.get(facet, 0) >= MAX_CUES:
                continue
            facts.append(_fact(facet, lines, n, n, "cue"))
            covered.add((facet, n))
            kept[facet] = kept.get(facet, 0) + 1
    return facts


def _criterion(text: str) -> dict[str, str] | None:
    m = GHERKIN.search(text)
    if m and m.group("then").strip():
        return {k: m.group(k).strip(" ,.;") for k in ("given", "when")} | {"then": m.group("then").strip()}
    m = CRITERION_LABEL.match(text)
    return {"given": "", "when": "", "then": m.group("then").strip()} if m else None


def _steps(block: list[tuple[int, str]]) -> list[tuple[dict[str, str], int, int]]:
    """Criteria written over several lines: Given ..., When ..., Then ... (And continues the step)."""
    out: list[tuple[dict[str, str], int, int]] = []
    cur: dict[str, str] = {}
    first = last = 0
    keys = {"given": "given", "oletetaan": "given", "when": "when", "kun": "when", "then": "then", "niin": "then"}
    for n, line in block:
        m = GHERKIN_STEP.match(line)
        step = keys.get(m.group("step").lower()) if m else None
        if m and step == "given" and cur.get("then"):
            out.append((cur, first, last))
            cur = {}
        if m and step:
            first = first if cur else n
            cur[step] = (cur.get(step, "") + " " + m.group("text").strip()).strip()
            last = n
        elif m and cur:               # "And ...": the step before it goes on
            key = "then" if cur.get("then") else "when" if cur.get("when") else "given"
            cur[key] = (cur[key] + " and " + m.group("text").strip()).strip()
            last = n
    if cur.get("then"):
        out.append((cur, first, last))
    return [({"given": c.get("given", ""), "when": c.get("when", ""), "then": c["then"]}, a, b) for c, a, b in out]


def _criteria(block: list[tuple[int, str]]) -> list[dict[str, Any]]:
    """The criteria under one requirement: one line each, or Gherkin steps over several lines."""
    found = []
    for n, line in block:
        c = _criterion(line)
        if c:
            found.append({**c, "lines": [n, n]})
    if not found:
        found = [{**c, "lines": [a, b]} for c, a, b in _steps(block)]
    return found[:3]


def requirements(lines: list[str]) -> list[dict[str, Any]]:
    """The author's own requirements: id, statement word for word, its lines and its criteria."""
    marks = [(n, m) for n, line in enumerate(lines, 1) if (m := REQUIREMENT.match(line))
             and not NOT_REQUIREMENT.search(m.group("id"))]
    stops = {n for n, _, _ in headings(lines)}
    out = []
    for i, (n, m) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(lines) + 1
        end = min([s for s in stops if n < s < end] + [end])
        block = [(k, lines[k - 1]) for k in range(n + 1, end) if lines[k - 1].strip()]
        statement = m.group("text").strip().strip("*").strip()
        out.append({"id": m.group("id"), "statement": statement, "lines": [n, block[-1][0] if block else n],
                    "acceptance": _criteria(block)})
    return out


def decisions(lines: list[str]) -> list[dict[str, Any]]:
    """The author's decisions: named ones anywhere ("D1: ...", "Decision 2: ...") and every list item
    under a heading that names decisions. Each states the facets its words name."""
    found: dict[int, dict[str, Any]] = {}
    for n, line in enumerate(lines, 1):
        m = DECISION.match(line)
        if m:
            found[n] = {"id": re.sub(r"\s+", " ", m.group("id")).upper().replace("DECISION ", "D")
                        .replace("PÄÄTÖS ", "D"), "text": m.group("text").strip()}
    for _, text, first, last in sections(lines):
        if not DECISIONS_HEADING.search(text):
            continue
        for n in range(first, last + 1):
            m = LIST_ITEM.match(lines[n - 1])
            if m and n not in found and not PLACEHOLDER.match(lines[n - 1]):
                found[n] = {"id": "", "text": m.group("text").strip()}
    return [{"id": d["id"] or f"D{k}", "text": d["text"], "lines": [n, n], "facets": facets_named(d["text"])}
            for k, (n, d) in enumerate(sorted(found.items()), 1)]


def _criteria_facts(lines: list[str], reqs: list[dict[str, Any]], covered: Covered) -> list[dict[str, Any]]:
    """The acceptance facet, stated by each requirement's criteria a section did not already cover."""
    facts = []
    for r in reqs:
        if not r["acceptance"]:
            continue
        first = min(c["lines"][0] for c in r["acceptance"])
        last = max(c["lines"][1] for c in r["acceptance"])
        if ("acceptance", first) not in covered:
            facts.append({**_fact("acceptance", lines, first, last, "criteria"), "requirement": r["id"]})
            covered.update(("acceptance", n) for n in range(first, last + 1))
    return facts


def facts_of(lines: list[str]) -> dict[str, Any]:
    """Everything one document states, by rule: facts per facet, what it leaves open, the author's
    requirements and decisions."""
    facts, left_open, covered = _section_facts(lines)
    reqs = requirements(lines)
    facts += _criteria_facts(lines, reqs, covered)
    decs = decisions(lines)
    for d in decs:
        n = d["lines"][0]
        for facet in (f for f in d["facets"] if (f, n) not in covered):
            facts.append({**_fact(facet, lines, n, n, "decision"), "decision": d["id"]})
            covered.add((facet, n))
    facts += _label_facts(lines, covered)
    facts += _cue_facts(lines, covered)
    stated = {f["facet"] for f in facts}
    facts.sort(key=lambda f: (f["lines"][0], FACET_IDS.index(f["facet"])))
    return {"facts": facts, "left_open": [o for o in left_open if o["facet"] not in stated],
            "requirements": reqs, "decisions": decs}
