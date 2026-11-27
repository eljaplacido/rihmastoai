"""A repository's own specs, read by rule (FR-ALN1, docs/guides/alignment.md): requirements, user stories,
acceptance criteria, task lists and decision records, in the conventions teams use.

kernel/repo_structure.py decides which files these are by their paths; this module reads their text, with no
model and nothing run:

- **requirements** with the repository's own ids and titles: spec-kit (`**FR-001**: System MUST ...`, `User
  Story 1 - Title (Priority: P1)`), Kiro (`### Requirement 1` with its `**User Story:**`), BMAD and agent-os
  documents (`FR1: ...`, a story's **As a** / **I want** / **so that**), PRDs, RFCs and requirement documents
  (a line or heading that starts with an id such as `REQ-12`, `US-3` or `FR1`), and user stories written as
  "As a ..., I want ..., so that ...";
- **acceptance criteria**: given / when / then (spec-kit's acceptance scenarios, BDD lines), EARS (`WHEN ...
  THEN the system SHALL ...`, `IF`, `WHILE`, `WHERE`, a plain "the system shall"), Gherkin scenarios in
  `.feature` files, and the items of a list under an "Acceptance criteria" heading;
- **tasks**: checkbox lines (`- [ ]`, `- [x]`) with their ids (spec-kit `T001`, Kiro `1.`) and the
  requirements they name (Kiro's `_Requirements: 1.1, 2.3_`);
- **decisions**: an ADR's number, title, status and date.

Every item keeps the lines it came from, so a proposal can name its source.
"""

from __future__ import annotations

import re
from typing import Any

MAX_ITEMS = 400                       # per file: more is counted, never silently dropped

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_STRIP = re.compile(r"\*\*|__|`|\*(?=\S)|(?<=\S)\*")
_ID_LINE = re.compile(r"^\s*(?:[-*+]|\d+[.)])?\s*(?:\*\*|__)?\[?(?P<id>[A-Z][A-Z]{0,9}-?\d{1,4}(?:\.\d{1,3})?)\]?"
                      r"(?:\*\*|__)?\s*(?:[:.)\-–—]|\s-\s)\s*(?:\*\*|__)?\s*(?P<text>\S.*)$")
_STORY = re.compile(r"(?i)\bas an?\s+(?P<who>[^,]+?),?\s+I\s+(?:want|need|would like)\s+(?:to\s+)?(?P<want>.+?)"
                    r"(?:,?\s+so\s+that\s+(?P<why>.+?))?\s*\.?\s*$")
_KIRO_REQ = re.compile(r"(?i)^requirement\s+(\d+(?:\.\d+)?)\s*[:.\-–—]?\s*(.*)$")
_BMAD_STORY = re.compile(r"(?i)^story\s+(\d+(?:\.\d+)*)\s*[:.\-–—]?\s*(.*)$")
_SPECKIT_STORY = re.compile(r"(?i)^user\s+story\s+(\d+)\s*[-–—:]\s*(.*?)(?:\s*\(priority:\s*(P\d)\))?\s*$")
_CRITERIA_HEAD = re.compile(r"(?i)^(acceptance\s+(criteria|scenarios?|tests?)|success\s+criteria"
                            r"|definition\s+of\s+done)")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?!\[[ xX]\])(?P<text>\S.*)$")
_GWT = re.compile(r"(?is)^\s*given\s+(?P<given>.+?)[,;]?\s+when\s+(?P<when>.+?)[,;]?\s+then\s+(?P<then>.+?)\s*\.?$")
_WT = re.compile(r"(?is)^\s*when\s+(?P<when>.+?)[,;]?\s+then\s+(?P<then>.+?)\s*\.?$")
_EARS = re.compile(r"(?is)^\s*(?P<kw>when|if|while|where)\s+(?P<cond>.+?),?\s+(?:then\s+)?(?:the\s+)?"
                   r"(?P<sys>[\w\s-]{1,40}?)\s+shall\s+(?P<then>.+?)\s*\.?$")
_SHALL = re.compile(r"(?is)^\s*(?:the\s+)?(?P<sys>[\w\s-]{1,40}?)\s+(?:shall|must)\s+(?P<then>.+?)\s*\.?$")
_CHECKBOX = re.compile(r"^\s*[-*+]\s+\[(?P<done>[ xX])\]\s+(?P<text>.+?)\s*$")
_TASK_ID = re.compile(r"^(?:\*\*)?(?P<id>T\d{2,4}|\d+(?:\.\d+)*\.?|[A-Z]{1,6}-\d{1,4})(?:\*\*)?\s+(?P<rest>.*)$")
_TASK_REFS = re.compile(r"(?i)_?requirements?:\s*([\w.,\s-]+?)_?\s*$")
_GHERKIN_KW = re.compile(r"(?i)^\s*(feature|rule|background|scenario outline|scenario template|scenario|example|"
                         r"examples|given|when|then|and|but)\s*:?\s*(.*)$")
_ADR_STATUS = re.compile(r"(?i)^\s*(?:[-*]\s*)?(?:\*\*)?status(?:\*\*)?\s*:\s*(?:\*\*)?\s*([A-Za-z][\w -]{1,40})")
_ADR_DATE = re.compile(r"(?i)^\s*(?:[-*]\s*)?(?:\*\*)?date(?:\*\*)?\s*:\s*(?:\*\*)?\s*(\d{4}-\d{2}-\d{2})")
_ADR_NUM = re.compile(r"^(\d{1,5})[-_. ]")
STATUSES = ("proposed", "accepted", "rejected", "deprecated", "superseded", "draft", "approved")


_BULLET = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+")     # a list item's own marker, never part of its words


def clean(text: str) -> str:
    """A line as a person reads it: emphasis and code marks removed, spaces folded."""
    return " ".join(_STRIP.sub("", text).split()).strip()


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(line number from 1, level, text) for each heading outside a fenced block."""
    out, fenced = [], False
    for n, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        m = None if fenced else _HEADING.match(line)
        if m:
            out.append((n, len(m.group(1)), clean(m.group(2))))
    return out


def criterion(text: str, line: int, form: str = "") -> dict[str, Any]:
    """One acceptance criterion as given / when / then, with the form it was written in: gwt, ears, shall or
    list (a statement taken as its then)."""
    t = clean(_BULLET.sub("", text))      # "- ZONE_BOUNDS ..." is the criterion, never "- ZONE_BOUNDS"
    t = re.sub(r"^(?:scenario|ac)\s*\d*\s*[:.\-–]\s*", "", t, flags=re.I)
    for rx, kind in ((_GWT, "gwt"), (_WT, "gwt")):
        m = rx.match(t)
        if m:
            d = m.groupdict()
            kind = "ears" if kind == "gwt" and not d.get("given") and re.search(r"(?i)\bshall\b", d["then"]) else kind
            return {"given": d.get("given") or "-", "when": d["when"], "then": d["then"], "form": form or kind,
                    "text": t, "line": line}
    m = _EARS.match(t)
    if m:
        cond = m.group("cond").strip()
        given, when = (cond, "-") if m.group("kw").lower() in ("if", "while", "where") else ("-", cond)
        return {"given": given, "when": when, "then": f"the {m.group('sys').strip()} shall {m.group('then')}",
                "form": "ears", "text": t, "line": line}
    m = _SHALL.match(t)
    if m and len(m.group("sys").split()) <= 4:
        return {"given": "-", "when": "-", "then": t.rstrip("."), "form": "shall", "text": t, "line": line}
    return {"given": "-", "when": "-", "then": t.rstrip("."), "form": form or "list", "text": t, "line": line}


def _section_end(heads: list[tuple[int, int, str]], i: int, total: int) -> int:
    level = heads[i][1]
    for n, lv, _ in heads[i + 1:]:
        if lv <= level:
            return n - 1
    return total


def _criteria_in(lines: list[str], start: int, end: int) -> list[dict[str, Any]]:
    """The criteria between two lines (1-based, inclusive): the items under an acceptance heading or label,
    and any given/when/then or EARS line."""
    out: list[dict[str, Any]] = []
    under = False
    for n in range(start, min(end, len(lines)) + 1):
        raw = lines[n - 1]
        text = clean(raw)
        head = _HEADING.match(raw)
        if head or re.match(r"^\s*(\*\*|__)[^*_]+(\*\*|__)\s*:?\s*$", raw) or re.match(r"(?i)^\*\*[^*]+:\*\*", raw):
            label = clean(head.group(2) if head else raw).rstrip(":")
            under = bool(_CRITERIA_HEAD.match(label))
            if under or head:
                continue
        item = _LIST_ITEM.match(raw)
        body = clean(item.group("text")) if item else text
        if not body:
            continue
        if (under and item) or _GWT.match(body) or _EARS.match(body):
            out.append(criterion(body, n))
    return out[:MAX_ITEMS]


def _story(text: str) -> dict[str, str] | None:
    m = _STORY.search(clean(text))
    if not m or len(m.group("want")) < 3:
        return None
    return {k: (v or "").strip().rstrip(".") for k, v in m.groupdict().items()}


def _story_in(lines: list[str], start: int, end: int) -> tuple[dict[str, str] | None, int]:
    """A user story written over one or a few lines (BMAD writes **As a** / **I want** / **so that** apart)."""
    window = []
    for n in range(start, min(end, len(lines)) + 1):
        text = clean(lines[n - 1]).removeprefix("User Story:").strip()
        if re.match(r"(?i)^as an?\b", text):
            window = [text]
            first = n
            for m in range(n + 1, min(n + 4, end, len(lines)) + 1):
                more = clean(lines[m - 1])
                if not more or not re.match(r"(?i)^(i\s+(want|need|would)|so\s+that)", more):
                    break
                window.append(more)
            story = _story(" ".join(window))
            if story:
                return story, first
    return None, 0


def statement_of(story: dict[str, str]) -> str:
    who, want, why = story["who"], story["want"], story.get("why")
    return f"As a {who}, I want {want}" + (f", so that {why}" if why else "") + "."


def _heading_ref(title: str) -> tuple[str | None, str]:
    """A heading's own ref (Requirement 1, User Story 2, Story 1.1, FR-001) and its title without it."""
    kiro, sk = _KIRO_REQ.match(title), _SPECKIT_STORY.match(title)
    bmad, idm = _BMAD_STORY.match(title), _ID_LINE.match(title)
    if kiro:
        return f"Requirement {kiro.group(1)}", kiro.group(2) or f"Requirement {kiro.group(1)}"
    if sk:
        return f"User Story {sk.group(1)}", sk.group(2)
    if bmad:
        return f"Story {bmad.group(1)}", bmad.group(2) or f"Story {bmad.group(1)}"
    if idm:
        return idm.group("id"), clean(idm.group("text"))
    return None, title


def _sibling_criteria(lines: list[str], heads: list[tuple[int, int, str]], i: int) -> list[dict[str, Any]]:
    """The criteria of a later section at the same level headed "Acceptance criteria", before the parent ends."""
    level = heads[i][1]
    for j in range(i + 1, len(heads)):
        n, lv, title = heads[j]
        if lv < level:
            break
        if lv == level and _CRITERIA_HEAD.match(title):
            return _criteria_in(lines, n, _section_end(heads, j, len(lines)))
    return []


def _req(rel: str, ref: str | None, title: str, statement: str, lines: list[int], story: dict[str, str] | None,
         criteria: list[dict[str, Any]]) -> dict[str, Any]:
    return {"ref": ref, "title": title, "statement": statement, "lines": lines, "story": story, "criteria": criteria,
            "path": rel}


def _headed(rel: str, lines: list[str], heads: list[tuple[int, int, str]], i: int, used: set[int]
            ) -> dict[str, Any] | None:
    """The requirement a heading starts: one with its own ref, or one holding a user story not taken yet."""
    n, end = heads[i][0], _section_end(heads, i, len(lines))
    ref, title = _heading_ref(heads[i][2])
    own = heads[i + 1][0] - 1 if i + 1 < len(heads) else len(lines)   # before its first sub-heading
    story, at = _story_in(lines, n + 1, end if ref else own)
    if ref is None and (story is None or at in used):
        return None
    if story is not None:
        used.add(at)
        generic = ref is None and title.lower().strip(": ") in ("story", "user story", "user stories")
        title = story["want"][:100] if title == ref or generic else title
    statement = statement_of(story) if story is not None else _first_line(lines[n:end], title)
    crit = _criteria_in(lines, n + 1, end) or _sibling_criteria(lines, heads, i)   # BMAD: the next section
    return _req(rel, ref, title, statement, [n, end], story, crit)


_META_LINE = re.compile(r"(?i)^[*_\s]*(priority|status|owner|effort|estimate|labels?|tags?|type|depends on|assignee"
                        r"|points|severity|milestone|component|version|created|updated)[*_\s]*:")


def _first_line(lines: list[str], fallback: str) -> str:
    """A section's first line of prose: neither a heading, a criteria label, a line ending in a colon nor a
    field of the document's own bookkeeping ("Priority: High", "**Status**: Draft")."""
    for i, raw in enumerate(lines):
        b = clean(_BULLET.sub("", raw))
        if not b or _HEADING.match(raw) or _CRITERIA_HEAD.match(b) or b.endswith(":") or _META_LINE.match(b):
            continue
        for more in lines[i + 1:]:       # a line wrapped in the source goes on until a blank, a bullet or a heading
            if not more.strip() or _BULLET.match(more) or _HEADING.match(more) or b.endswith((".", "!", "?")) \
                    or more.lstrip().startswith(("```", "~~~", "|")):
                break
            b = f"{b} {clean(more)}"
        return b
    return fallback


def _lined(rel: str, n: int, raw: str) -> dict[str, Any] | None:
    """A requirement on one line: one that starts with an id, or a user story."""
    m = _ID_LINE.match(raw)
    if m and not _CHECKBOX.match(raw) and not re.match(r"^T\d{2,4}$", m.group("id")):
        body = clean(m.group("text"))
        return _req(rel, m.group("id"), body[:100], body, [n, n], None, [])
    story = _story(raw)
    return _req(rel, None, story["want"][:100], statement_of(story), [n, n], story, []) if story else None


def requirements(rel: str, text: str) -> list[dict[str, Any]]:
    """The requirements a document states, each with its own ref, title, statement, lines and criteria."""
    lines = text.splitlines()
    heads = _headings(lines)
    out: list[dict[str, Any]] = []
    taken: set[int] = set()
    used: set[int] = set()                     # the lines of the stories already taken
    for i in range(len(heads)):
        req = _headed(rel, lines, heads, i, used)
        if req is not None:
            out.append(req)
            taken.update(range(req["lines"][0], req["lines"][1] + 1))
    for n, raw in enumerate(lines, 1):         # an id'd line or a story outside any heading taken above
        req = None if n in taken else _lined(rel, n, raw)
        if req is not None:
            out.append(req)
    return out[:MAX_ITEMS]


class _Feature:
    """A Gherkin file read line by line: its feature, the scenario open, the tags waiting for the next one."""

    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.feature: dict[str, Any] | None = None
        self.scenario: dict[str, Any] | None = None
        self.tags: list[str] = []
        self.last = "given"

    def close(self) -> None:
        f, s = self.feature, self.scenario
        if f is not None and s is not None:
            c = {k: "; ".join(s[k]) or "-" for k in ("given", "when", "then")}
            f["criteria"].append({**c, "form": "gherkin", "text": s["name"], "line": s["line"], "tags": s["tags"]})

    def step(self, kw: str, rest: str, n: int) -> None:
        if kw == "feature":
            ref = next((t for t in self.tags if re.fullmatch(r"[A-Za-z][\w]*-[\w-]+", t)), None)
            self.feature = _req(self.rel, ref, rest, rest, [n, n], None, []) | {"tags": self.tags}
            self.tags = []
        elif kw.startswith("scenario") or kw == "example":
            self.close()
            self.scenario = {"name": rest, "line": n, "given": [], "when": [], "then": [], "tags": self.tags}
            self.tags = []
        elif kw == "background":
            self.scenario = None
        elif self.scenario is not None and kw in ("given", "when", "then", "and", "but"):
            self.last = kw if kw in ("given", "when", "then") else self.last
            self.scenario[self.last].append(rest)


def gherkin(rel: str, text: str) -> list[dict[str, Any]]:
    """A `.feature` file: its Feature as a requirement and each Scenario as a criterion (given / when / then,
    And and But joined to the step before). Tags such as @REQ-12 are kept as refs."""
    read = _Feature(rel)
    lines = text.splitlines()
    for n, raw in enumerate(lines, 1):
        s = raw.strip()
        m = None if s.startswith("#") else _GHERKIN_KW.match(s)
        if s.startswith("@"):
            read.tags = [t.lstrip("@") for t in s.split() if t.startswith("@")]
        elif m:
            read.step(m.group(1).lower(), m.group(2).strip(), n)
        if read.feature is not None:
            read.feature["lines"][1] = n
    read.close()
    feature = read.feature
    if feature is None:
        return []
    story = _story(" ".join(clean(x) for x in lines[feature["lines"][0]:feature["lines"][0] + 4]))
    if story:
        feature["story"], feature["statement"] = story, statement_of(story)
    return [feature]


def tasks(rel: str, text: str) -> list[dict[str, Any]]:
    """Checkbox lines: their id when they have one, done or open, and the requirements they name."""
    out: list[dict[str, Any]] = []
    lines = text.splitlines()
    for n, raw in enumerate(lines, 1):
        m = _CHECKBOX.match(raw)
        if not m:
            continue
        body = clean(m.group("text"))
        tid = _TASK_ID.match(body)
        ref = tid.group("id").rstrip(".") if tid else None
        title = clean(tid.group("rest")) if tid else body
        title = re.sub(r"^\[P\]\s*", "", title)
        refs: list[str] = []
        indent = len(raw) - len(raw.lstrip())
        for follow in lines[n:n + 8]:                      # Kiro names them on an indented line after the task
            if _CHECKBOX.match(follow) and len(follow) - len(follow.lstrip()) <= indent:
                break
            r = _TASK_REFS.search(clean(follow))
            if r:
                refs = [x.strip() for x in r.group(1).split(",") if x.strip()]
                break
        refs += re.findall(r"\b(US\d+|FR-\d{3}|[A-Z]{2,6}-\d{1,4})\b", title)
        out.append({"ref": ref, "title": title, "done": m.group("done") != " ", "line": n, "path": rel,
                    "requirements": list(dict.fromkeys(refs)), "indent": indent})
        if len(out) >= MAX_ITEMS:
            break
    return out


def decision(rel: str, text: str) -> dict[str, Any]:
    """An ADR: its number, title, status and date, read from the MADR and Nygard layouts."""
    lines = text.splitlines()
    heads = _headings(lines)
    title = heads[0][2] if heads else rel.rsplit("/", 1)[-1]
    num = _ADR_NUM.match(rel.rsplit("/", 1)[-1])
    m = re.match(r"^(?:ADR[-\s]?)?(\d{1,5})[.:\s-]+\s*(.*)$", title, re.IGNORECASE)
    title = (m.group(2) or title) if m else title
    found = [s.group(1).strip().lower() for s in map(_ADR_STATUS.match, lines[:80]) if s]
    dates = [d.group(1) for d in map(_ADR_DATE.match, lines[:80]) if d] + [None]
    status = found[0] if found else _status_below(lines, heads)
    ident = m.group(1) if m else num.group(1) if num else None
    return {"ref": f"ADR-{int(ident):04d}" if ident else None, "title": clean(title), "status": status or "unknown",
            "date": dates[0], "path": rel, "line": heads[0][0] if heads else 1}


def _status_below(lines: list[str], heads: list[tuple[int, int, str]]) -> str | None:
    """The status a "## Status" heading has on the line after it (the Nygard and MADR layouts)."""
    for n, _lv, h in heads:
        if h.lower() == "status":
            nxt = next((clean(x) for x in lines[n:n + 4] if clean(x)), "")
            word = nxt.split()[0].lower().strip(".,") if nxt else ""
            return word if word in STATUSES else (nxt.lower()[:40] or None)
    return None


def doc_title(text: str, fallback: str) -> str:
    heads = _headings(text.splitlines()[:60])
    return heads[0][2] if heads else fallback
