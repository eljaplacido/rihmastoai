"""Readers of a project's own sources (FR-SRC1): what a team keeps as its requirements, findings, tasks and test
results, read as the project writes them, by rule and with no model.

- **records**: JSON or YAML files, one record each or a list of them (a folder of rule files, a requirements file),
  read through a field mapping: which key is the id, the title, the statement, the criteria and the test that checks
  it. ``guess_mapping`` proposes one from the keys most records share;
- **jsonl**: one JSON object per line, as findings (an issues log): id, title, severity, status, where;
- **markdown**: the rows of a table with a status column (a round's README, a handoff note) and checkbox lines,
  as tasks with their status;
- **results**: test results as a runner or a gate writes them: JUnit XML, TAP, or JSON (a list of cases, a
  pytest-json-report, a map of names to verdicts, or bare counts).

Every record keeps its path and line, so whatever is shown from it says where it came from. Nothing here runs or
evaluates anything: YAML is read for the plain mappings, lists and scalars such files hold, XML with no document
type or entity, and each text is capped in size.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any

MAX_TEXT = 4 * 1024 * 1024
MAX_RECORDS = 5000
ID_KEYS = ("id", "key", "code", "rule_id", "law_id", "req_id", "requirement_id", "issue_id", "finding_id", "bug_id",
           "ref", "uid", "slug", "name")
TITLE_KEYS = ("title", "name", "summary", "headline", "rule", "law", "statement", "description", "text")
STATEMENT_KEYS = ("statement", "description", "rule", "law", "text", "body", "summary", "intent")
CRITERIA_KEYS = ("criteria", "acceptance", "acceptance_criteria", "checks", "expect", "expected", "expectations",
                 "invariants", "asserts", "then")
TEST_KEYS = ("test", "tests", "mutant", "mutant_test", "mutation_test", "verified_by", "test_file", "gate", "check")
STATUS_KEYS = ("status", "state", "done", "outcome")
SEVERITY_KEYS = ("severity", "sev", "level", "priority", "impact")
WHERE_KEYS = ("file", "path", "location", "loc", "where", "source")
DONE = re.compile(r"(?i)^\s*(done|complete[d]?|closed|merged|shipped|passed|pass|green|fixed|resolved|finished|yes"
                  r"|ok|landed|\[x\]|x|✅|✓|✔|☑)\s*[.!]?\s*$")
PASSED = ("pass", "passed", "ok", "success", "succeeded", "green", "true", "good")
FAILED = ("fail", "failed", "failure", "error", "errored", "broken", "red", "false", "bad")
SKIPPED = ("skip", "skipped", "pending", "xfail", "todo", "ignored", "disabled")


class SourceUnreadable(ValueError):
    """A file the adapter cannot read as its kind: said with why, never guessed."""


# -- YAML, the subset such files use ---------------------------------------------------------------------

def _scalar(text: str) -> Any:
    s = text.strip()
    if s.startswith("#"):
        return None
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    s = re.sub(r"\s+#.*$", "", s)
    if s.startswith("[") and s.endswith("]"):
        return [_scalar(p) for p in s[1:-1].split(",") if p.strip()]
    if s in ("", "~", "null"):
        return None
    if s in ("true", "false"):
        return s == "true"
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    return s


def _lines(text: str) -> list[tuple[int, int, str]]:
    out = []
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#") or raw.strip() in ("---", "..."):
            continue
        out.append((len(raw) - len(raw.lstrip(" ")), n, raw.strip()))
    return out


def _block(rows: list[tuple[int, int, str]], i: int, ind: int) -> tuple[Any, int]:
    if i >= len(rows):
        return None, i
    if rows[i][2].startswith("- ") or rows[i][2] == "-":
        return _seq(rows, i, rows[i][0])
    return _map(rows, i, rows[i][0])


def _seq(rows: list[tuple[int, int, str]], i: int, ind: int) -> tuple[list[Any], int]:
    out: list[Any] = []
    while i < len(rows) and rows[i][0] == ind and (rows[i][2].startswith("- ") or rows[i][2] == "-"):
        rest = rows[i][2][1:].strip()
        if not rest:
            val, i = _block(rows, i + 1, ind + 1)
        elif re.match(r"^[\w.-]+\s*:(\s|$)", rest):              # "- key: value" opens a mapping
            rows = rows[:i] + [(ind + 2, rows[i][1], rest)] + rows[i + 1:]
            val, i = _map(rows, i, ind + 2)
        else:
            val, i = _scalar(rest), i + 1
        out.append(val)
    return out, i


def _map(rows: list[tuple[int, int, str]], i: int, ind: int) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {"__line__": rows[i][1]} if i < len(rows) else {}
    while i < len(rows) and rows[i][0] == ind:
        m = re.match(r"^([\w.-]+|\"[^\"]+\"|'[^']+')\s*:\s*(.*)$", rows[i][2])
        if not m:
            break
        key, rest = m.group(1).strip("\"'"), m.group(2)
        if rest.strip() in ("|", ">", "|-", ">-"):
            j, parts = i + 1, []
            while j < len(rows) and rows[j][0] > ind:
                parts.append(rows[j][2])
                j += 1
            out[key], i = (" " if rest.startswith(">") else "\n").join(parts), j
        elif rest.strip() and not rest.strip().startswith("#"):
            out[key], i = _scalar(rest), i + 1
        elif i + 1 < len(rows) and (rows[i + 1][0] > ind or (rows[i + 1][0] == ind and rows[i + 1][2].startswith("-"))):
            out[key], i = _block(rows, i + 1, rows[i + 1][0])
        else:
            out[key], i = None, i + 1
    return out, i


def yaml_load(text: str) -> Any:
    """The plain mappings, lists and scalars of a YAML file; anchors, tags and flow mappings are not read."""
    rows = _lines(text)
    if not rows:
        return None
    val, _ = _block(rows, 0, rows[0][0])
    return val


# -- records: JSON or YAML -------------------------------------------------------------------------------

def _loads(text: str, path: str) -> Any:
    if len(text) > MAX_TEXT:
        raise SourceUnreadable(f"{path} is larger than {MAX_TEXT // (1024 * 1024)} MB: listed, not read")
    if path.lower().endswith((".yaml", ".yml")):
        return yaml_load(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceUnreadable(f"{path} is not valid JSON ({exc.msg} at line {exc.lineno})") from None


def objects(text: str, path: str) -> list[dict[str, Any]]:
    """The records a file holds: itself when it is one, the items of its list, or of the one list it carries."""
    doc = _loads(text, path)
    if isinstance(doc, list):
        return [d for d in doc if isinstance(d, dict)][:MAX_RECORDS]
    if not isinstance(doc, dict):
        return []
    if any(k in doc for k in ID_KEYS) and any(k in doc for k in TITLE_KEYS + CRITERIA_KEYS + TEST_KEYS):
        return [doc]
    lists = [v for k, v in doc.items() if isinstance(v, list) and v and all(isinstance(x, dict) for x in v)]
    return lists[0][:MAX_RECORDS] if len(lists) == 1 else []


def _first(keys: tuple[str, ...], objs: list[dict[str, Any]], taken: set[str], share: float = 0.6) -> str | None:
    lowered = [{k.lower(): k for k in o if k != "__line__"} for o in objs]
    for want in keys:
        have = [low[want] for low in lowered if want in low]
        if have and len(have) >= share * len(objs) and have[0] not in taken:
            return have[0]
    return None


def guess_mapping(objs: list[dict[str, Any]]) -> dict[str, str]:
    """The keys most records share for each field; a field no key fits is left out."""
    if not objs:
        return {}
    out: dict[str, str] = {}
    for field, keys, share in (("id", ID_KEYS, 0.6), ("title", TITLE_KEYS, 0.6), ("criteria", CRITERIA_KEYS, 0.3),
                               ("test", TEST_KEYS, 0.3), ("statement", STATEMENT_KEYS, 0.6),
                               ("status", STATUS_KEYS, 0.3), ("severity", SEVERITY_KEYS, 0.3),
                               ("where", WHERE_KEYS, 0.3)):
        key = _first(keys, objs, set(out.values()), share)
        if key:
            out[field] = key
    return out


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return "; ".join(_text(x) for x in v if x is not None)
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_text(x)}" for k, x in v.items() if k != "__line__")
    return " ".join(str(v).split())


def _line_of(lines: list[str], value: str, start: int) -> int:
    """The line a value first appears on at or after ``start`` (1-based), else ``start``."""
    if value:
        for n in range(max(start, 1), len(lines) + 1):
            if value in lines[n - 1]:
                return n
    return max(start, 1)


def _criteria(v: Any, line: int) -> list[dict[str, Any]]:
    items = v if isinstance(v, list) else [v] if v not in (None, "", {}) else []
    out = []
    for c in items:
        if isinstance(c, dict) and c.get("then"):
            out.append({"given": _text(c.get("given")) or "-", "when": _text(c.get("when")) or "-",
                        "then": _text(c.get("then")), "form": "given/when/then", "line": c.get("__line__") or line})
        elif _text(c):
            out.append({"given": "-", "when": "-", "then": _text(c), "form": "stated", "line": line})
    return out


def _tests(v: Any) -> list[str]:
    if isinstance(v, dict):
        v = [x for k, x in v.items() if k != "__line__"]
    items = v if isinstance(v, list) else [v] if v not in (None, "") else []
    return [str(x).strip() for x in items if isinstance(x, (str, int)) and str(x).strip()][:20]


def _field(o: dict[str, Any], mapping: dict[str, str], name: str) -> Any:
    """The value a record holds for a field, through the mapping; None when the field is not mapped."""
    key = mapping.get(name)
    return o.get(key) if key else None


def _record(o: dict[str, Any], mapping: dict[str, str], path: str, line: int) -> dict[str, Any]:
    ref, title = _text(_field(o, mapping, "id")), _text(_field(o, mapping, "title"))
    statement = _text(_field(o, mapping, "statement"))
    status = _field(o, mapping, "status")
    return {"ref": ref or None, "title": (title or statement or ref)[:300],
            "statement": (statement or title or ref)[:2000], "criteria": _criteria(_field(o, mapping, "criteria"),
                                                                                    line)[:50],
            "tests": _tests(_field(o, mapping, "test")), "status": None if status is None else _text(status)[:40],
            "path": path, "line": line, "lines": [line, line]}


def records(text: str, path: str, mapping: dict[str, str]) -> list[dict[str, Any]]:
    """Requirements from a JSON or YAML file through ``mapping``: each with its id, title, statement, criteria,
    the tests that check it, and its path and lines."""
    lines, at, out = text.splitlines(), 1, []
    quoted = not path.endswith((".yaml", ".yml"))
    for o in objects(text, path):
        ref, title = _text(_field(o, mapping, "id")), _text(_field(o, mapping, "title"))
        if not ref and not title:
            continue
        line = o.get("__line__") or _line_of(lines, f'"{ref}"' if ref and quoted else ref or title, at)
        at = line + 1
        out.append(_record(o, mapping, path, line))
    return out


# -- findings: JSONL -------------------------------------------------------------------------------------

def jsonl(text: str, path: str, mapping: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Findings, one JSON object per line; a line that is not one is skipped and counted."""
    if len(text) > MAX_TEXT:
        raise SourceUnreadable(f"{path} is larger than {MAX_TEXT // (1024 * 1024)} MB: listed, not read")
    rows = [(n, got) for n, got in enumerate(map(_json_line, text.splitlines()), 1) if isinstance(got, dict)]
    m = dict(mapping or {}) or guess_mapping([r for _, r in rows[:200]])
    m.setdefault("title", next((k for k in ("title", "summary", "message", "name", "text", "description")
                                if any(k in r for _, r in rows[:50])), "title"))
    return [f for n, r in rows[:MAX_RECORDS] if (f := _finding(r, m, path, n))]


def _json_line(raw: str) -> Any:
    try:
        return json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        return None


def jsonl_unread(text: str) -> list[int]:
    """The lines of a JSONL file that hold text but no JSON object: said, never dropped silently (FR-SRC2)."""
    return [n for n, raw in enumerate(text.splitlines(), 1) if raw.strip() and not isinstance(_json_line(raw), dict)]


def _finding(r: dict[str, Any], m: dict[str, str], path: str, n: int) -> dict[str, Any] | None:
    title = _text(_field(r, m, "title")) or f"(no title) {_text(r)[:200]}"     # kept, never lost
    return {"id": _text(_field(r, m, "id")) or f"line {n}", "title": title[:300],
            "severity": (_text(_field(r, m, "severity")) or "not said").lower()[:20],
            "status": (_text(_field(r, m, "status")) or "open").lower()[:30],
            "where": _text(_field(r, m, "where"))[:200] or None, "path": path, "line": n}


# -- tasks: markdown tables and checklists ---------------------------------------------------------------

_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
TITLE_COLS = ("task", "title", "item", "what", "work", "deliverable", "name", "goal", "description", "step", "change")
STATUS_COLS = ("status", "state", "done", "progress", "result", "outcome")
ID_COLS = ("id", "#", "ref", "key", "no", "nr")


def _cells(line: str) -> list[str]:
    m = _ROW.match(line)
    return [c.strip() for c in m.group(1).split("|")] if m else []


def _col(head: list[str], names: tuple[str, ...]) -> int | None:
    low = [re.sub(r"[*_`]", "", h).strip().lower() for h in head]
    return next((i for n in names for i, h in enumerate(low) if h == n or h.startswith(n + " ")), None)


def _clean(cell: str) -> str:
    return re.sub(r"[*_`]|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", cell).strip()


def _columns(head: list[str]) -> tuple[int | None, int | None, int | None]:
    """The status, title and id columns of a table's header; the title is the first other column when unnamed."""
    st, tid, title = _col(head, STATUS_COLS), _col(head, ID_COLS), _col(head, TITLE_COLS)
    if title is None:
        title = next((k for k in range(len(head)) if k not in (st, tid)), None)
    return st, title, tid


def _row(cells: list[str], cols: tuple[int | None, int | None, int | None], path: str, n: int) -> dict[str, Any] | None:
    st, title, tid = cols
    if st is None or title is None or len(cells) <= max(st, title):
        return None
    status = _clean(cells[st])
    return {"title": _clean(cells[title])[:300], "status": status[:60] or "not said",
            "done": bool(DONE.match(status)) or status.startswith(("✅", "✓", "✔")),
            "ref": _clean(cells[tid])[:40] if tid is not None and tid < len(cells) else None,
            "path": path, "line": n, "requirements": []}


def table_rows(text: str, path: str) -> list[dict[str, Any]]:
    """The rows of every table that has a status column, as tasks: title, status, done, id, line."""
    lines, out, i = text.splitlines(), [], 0
    while i + 1 < len(lines):
        if not (_ROW.match(lines[i]) and _SEP.match(lines[i + 1])):
            i += 1
            continue
        cols, i = _columns(_cells(lines[i])), i + 2
        while i < len(lines) and _ROW.match(lines[i]):
            out.append(_row(_cells(lines[i]), cols, path, i + 1))
            i += 1
    return [r for r in out if r and r["title"]][:MAX_RECORDS]


def markdown_tasks(text: str, path: str) -> list[dict[str, Any]]:
    """A markdown file's tasks: its tables' rows with a status, then its checkbox lines."""
    from kernel import repo_specs as rs

    rows = table_rows(text, path)
    for t in rs.tasks(path, text):
        rows.append({"title": t["title"], "status": "done" if t["done"] else "open", "done": t["done"],
                     "ref": t.get("ref"), "path": path, "line": t["line"], "requirements": t.get("requirements", [])})
    return rows[:MAX_RECORDS]


# -- test results ----------------------------------------------------------------------------------------

def verdict_word(v: Any) -> str:
    if isinstance(v, bool):
        return "passed" if v else "failed"
    s = str(v or "").strip().lower()
    if s in PASSED:
        return "passed"
    if s in FAILED:
        return "failed"
    return "skipped" if s in SKIPPED else "not said"


def junit(text: str) -> list[dict[str, Any]]:
    if re.search(r"<!(DOCTYPE|ENTITY)", text[:4096], re.IGNORECASE):
        raise SourceUnreadable("a JUnit file with a document type or entities is not read")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SourceUnreadable(f"not JUnit XML ({exc})") from None
    out = []
    for case in root.iter("testcase"):
        kids = {c.tag for c in case}
        status = ("failed" if kids & {"failure", "error"} else "skipped" if "skipped" in kids else "passed")
        out.append({"name": case.get("name") or "?", "suite": case.get("classname") or None, "status": status})
    return out[:MAX_RECORDS * 4]


_TAP = re.compile(r"^(not ok|ok)\b\s*\d*\s*-?\s*(.*?)\s*(#\s*(SKIP|TODO)\b.*)?$", re.IGNORECASE)


def tap(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in text.splitlines():
        m = _TAP.match(raw.strip())
        if m:
            status = "skipped" if m.group(4) else ("passed" if m.group(1).lower() == "ok" else "failed")
            out.append({"name": m.group(2) or f"test {len(out) + 1}", "suite": None, "status": status})
    return out[:MAX_RECORDS * 4]


def _case(x: dict[str, Any]) -> dict[str, Any] | None:
    name = next((x[k] for k in ("name", "nodeid", "id", "test", "title", "gate") if x.get(k)), None)
    status = next((x[k] for k in ("status", "outcome", "result", "verdict", "passed", "ok") if k in x), None)
    if name is None or status is None:
        return None
    return {"name": str(name)[:300], "suite": x.get("suite") or x.get("classname"), "status": verdict_word(status)}


def json_results(text: str) -> tuple[list[dict[str, Any]], dict[str, int] | None]:
    """Cases from a JSON results file, or bare counts when the file gives only those."""
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceUnreadable(f"not a JSON results file ({exc.msg})") from None
    if isinstance(doc, dict):
        listed = next((doc[k] for k in ("tests", "results", "cases", "gates", "testcases", "checks")
                       if isinstance(doc.get(k), list)), None)
        if listed is None:
            return _results_object(doc)
        doc = listed
    if isinstance(doc, list):
        return [c for c in (_case(x) for x in doc if isinstance(x, dict)) if c][:MAX_RECORDS * 4], None
    return [], None


def _results_object(doc: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int] | None]:
    """An object with no list of cases: bare counts, or a map of names to verdicts."""
    counts = {k: int(doc[k]) for k in ("passed", "failed", "skipped", "errors") if isinstance(doc.get(k), int)}
    if counts:
        return [], counts
    if doc and all(isinstance(v, (str, bool)) for v in doc.values()):
        return [{"name": str(k), "suite": None, "status": verdict_word(v)} for k, v in doc.items()], None
    return [], None


def results(text: str, fmt: str | None = None) -> dict[str, Any]:
    """A results file read in its format (``junit``, ``tap`` or ``json``; found from the text when not given)."""
    if len(text) > MAX_TEXT:
        raise SourceUnreadable(f"a results file is read up to {MAX_TEXT // (1024 * 1024)} MB")
    s = text.lstrip()
    fmt = fmt or ("junit" if s.startswith("<") else "tap" if re.search(r"(?m)^(TAP version|ok \d|not ok \d)", s)
                  else "json")
    if fmt not in ("junit", "tap", "json"):
        raise SourceUnreadable("a results file is JUnit XML, TAP or JSON")
    counts = None
    if fmt == "junit":
        cases = junit(text)
    elif fmt == "tap":
        cases = tap(text)
    else:
        cases, counts = json_results(text)
    if counts is None:
        counts = {w: sum(1 for c in cases if c["status"] == w) for w in ("passed", "failed", "skipped")}
    if not cases and not any(counts.values()):
        raise SourceUnreadable(f"no test result found in it as {fmt}")
    return {"format": fmt, "cases": cases, "counts": counts}
