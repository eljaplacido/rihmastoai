"""Plans a team keeps in tables and data files, read by rule (FR-ASP2; kernel/repo_structure.py calls it).

An independent check of FR-ASP1 found Alignment reading only checkbox lines and requirement lines that start with an
id: a requirements document kept as a Markdown table gave no requirement, a folder of JSON rule files ("laws",
"rules", "policies") gave none, and a README's table of rounds or milestones with their status gave no task. Their
owner's coding agent named these as what would make the picture realistic. Read as data, never run:

- **Requirements in a Markdown table** (`table_requirements`): a table with an id column (ID, Ref, Key, #, Req) and
  a text column (Requirement, Statement, Description, Rule, Story, Title); each row whose id looks like one
  (`R-01`, `FR-2`, `REQ12`) is a requirement with its line.
- **Requirements in JSON** (`json_requirements`, for `rule_file` paths: a JSON file in `laws/`, `rules/`,
  `policies/` or `requirements/`, or named `requirements*.json`): a list of objects, or one under `requirements`,
  `rules`, `laws`, `policies` or `items`, or an object of id to text; each with an id and a statement (statement,
  rule, law, text, requirement, description or title).
- **Tasks in a status table** (`table_tasks`, in task lists and READMEs): a table with a status column and a name
  column (Goal, Task, Title, Name, Milestone, Deliverable, Feature, What); each row is a task, done when its
  status says so (done, complete, shipped, merged, released, closed, a tick).
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any

from kernel.repo_specs import clean

MAX_ITEMS = 400
RULE_FILE = re.compile(r"(?i)(^|/)((laws|rules|policies|requirements)/[^/]+|requirements[\w.-]*)\.json$")
README = re.compile(r"(?i)(^|/)readme\.(md|markdown)$")
_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_RULE_ROW = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_REQ_ID = re.compile(r"^[A-Z][A-Za-z]{0,9}-?\d{1,4}(?:\.\d{1,3})?$")
ID_HEADS = ("id", "ref", "key", "#", "req", "req id", "requirement id", "code", "no", "no.")
TEXT_HEADS = ("requirement", "statement", "description", "rule", "story", "user story", "title", "text", "need")
STATUS_HEADS = ("status", "state", "done", "progress")
NAME_HEADS = ("goal", "task", "title", "name", "milestone", "deliverable", "feature", "what", "item", "description")
ORDER_HEADS = ("round", "id", "#", "step", "phase", "milestone", "sprint", "iteration", "stage", "version")
DONE = re.compile(r"(?i)^(done|complete(d)?|finished|shipped|merged|released|closed|yes|x|✅|✔️?|"
                  r"☑️?)\b")
JSON_LISTS = ("requirements", "rules", "laws", "policies", "items")
JSON_IDS = ("id", "ref", "key", "code")
JSON_TEXTS = ("statement", "rule", "law", "text", "requirement", "description", "title")


def _cells(line: str) -> list[str]:
    m = _ROW.match(line)
    return [clean(c) for c in m.group(1).split("|")] if m else []


def tables(text: str) -> list[tuple[list[str], list[tuple[int, list[str]]]]]:
    """Each Markdown table: its header cells (lower case) and its rows, each with its line number."""
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines) - 1:
        head = _cells(lines[i])
        if head and _RULE_ROW.match(lines[i + 1]):
            rows, j = [], i + 2
            while j < len(lines) and _cells(lines[j]):
                rows.append((j + 1, _cells(lines[j])))
                j += 1
            out.append(([h.lower() for h in head], rows))
            i = j
        else:
            i += 1
    return out


def _column(head: list[str], names: tuple[str, ...]) -> int | None:
    exact = next((k for k, h in enumerate(head) if h in names), None)
    return exact if exact is not None else next((k for k, h in enumerate(head) if any(h.startswith(n) for n in names
                                                                                     if len(n) > 2)), None)


def _req(rel: str, ref: str, statement: str, line: int) -> dict[str, Any]:
    return {"ref": ref, "title": statement[:100], "statement": statement, "lines": [line, line], "story": None,
            "criteria": [], "path": rel}


def table_requirements(rel: str, text: str, taken: set[str] | None = None) -> list[dict[str, Any]]:
    """The requirements a document keeps in a table: each row with an id and its text."""
    taken = set(taken or ())
    out: list[dict[str, Any]] = []
    for head, rows in tables(text):
        id_col, text_col = _column(head, ID_HEADS), _column(head, TEXT_HEADS)
        if id_col is None or text_col is None or id_col == text_col:
            continue
        for n, cells in rows:
            if max(id_col, text_col) >= len(cells):
                continue
            ref, said = cells[id_col], cells[text_col]
            if _REQ_ID.match(ref) and said and ref not in taken:
                taken.add(ref)
                out.append(_req(rel, ref, said, n))
    return out[:MAX_ITEMS]


def rule_file(rel: str) -> bool:
    """A JSON file that keeps requirements or rules by its folder or name."""
    return bool(RULE_FILE.search(rel))


def _json_rows(doc: Any) -> list[tuple[str, str]]:
    if isinstance(doc, dict):
        listed = next((doc[k] for k in JSON_LISTS if isinstance(doc.get(k), (list, dict))), None)
        if listed is not None:
            return _json_rows(listed)
        if all(isinstance(v, (str, dict)) for v in doc.values()):         # an object of id to text or to an object
            return [(str(k), v if isinstance(v, str) else _text_of(v)) for k, v in doc.items()]
        return []
    if isinstance(doc, list):
        return [(next((str(r[k]) for k in JSON_IDS if r.get(k) not in (None, "")), ""), _text_of(r))
                for r in doc if isinstance(r, dict)]
    return []


def _text_of(row: dict[str, Any]) -> str:
    return next((" ".join(str(row[k]).split()) for k in JSON_TEXTS if isinstance(row.get(k), str) and row[k].strip()),
                "")


def json_requirements(rel: str, text: str) -> list[dict[str, Any]]:
    """The requirements a JSON rule file keeps: each with an id and a statement."""
    try:
        doc = json.loads(text)
    except (ValueError, RecursionError):
        return []
    lines = text.splitlines()
    out = []
    for ref, said in _json_rows(doc)[:MAX_ITEMS]:
        if not ref or not said:
            continue
        line = next((n for n, raw in enumerate(lines, 1) if f'"{ref}"' in raw), 1)
        out.append(_req(rel, ref[:40], said, line))
    return out


def table_tasks(rel: str, text: str) -> list[dict[str, Any]]:
    """The tasks a status table keeps (rounds, milestones, a task list as a table): each row done or open."""
    out: list[dict[str, Any]] = []
    where = PurePosixPath(rel).name
    for head, rows in tables(text):
        status, name = _column(head, STATUS_HEADS), _column(head, NAME_HEADS)
        if status is None or name is None or status == name:
            continue
        order = _column(head, ORDER_HEADS)
        order = None if order in (status, name) else order
        for n, cells in rows:
            if max(status, name) < len(cells) and cells[name]:
                said = cells[status]
                out.append({"ref": _ref(head, cells, order), "title": cells[name], "done": bool(DONE.match(said)),
                            "line": n, "path": rel, "requirements": list(dict.fromkeys(
                                re.findall(r"\b([A-Z]{1,6}-\d{1,4})\b", cells[name]))),
                            "indent": 0, "why": f"a row of the table in {where}, its status \"{said or 'none'}\""})
    return out[:MAX_ITEMS]


def status_tasks(read: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """The status-table tasks of each (path, text) read once: task lists and READMEs."""
    return [t for rel, text in dict.fromkeys(read) for t in table_tasks(rel, text)]


def with_tables(rel: str, text: str, reqs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A document's requirements with those it keeps in tables; a JSON rule file's, read as JSON."""
    if rel.lower().endswith(".json"):
        return json_requirements(rel, text)
    return reqs + table_requirements(rel, text, {r["ref"] for r in reqs if r.get("ref")})


def _ref(head: list[str], cells: list[str], order: int | None) -> str | None:
    """A row's own order (Round 1, M2), when its table has an order column."""
    if order is None or order >= len(cells) or not cells[order]:
        return None
    ref = cells[order]
    return f"{head[order].capitalize()} {ref}" if ref.isdigit() else ref


__all__ = ["README", "RULE_FILE", "json_requirements", "rule_file", "status_tasks",
           "table_requirements", "table_tasks", "tables", "with_tables"]
