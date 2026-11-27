"""What Alignment reads of a repository and what it cannot, said plainly (FR-LND2).

Start here's first step on an adopted project leads to Alignment's Read the repository. A team often keeps its real
requirements, findings and tasks somewhere Alignment does not read: YAML rule or data files, an issue log, task rows in
a round's notes (JSON rule files and a README's status table are read, FR-ASP2). Proposing only an old requirements
document then leads the owner to accept the outdated plan. So:

- ``READS`` and ``CANNOT`` say, in words, what kernel/repo_structure.py reads and what it does not read yet;
- ``unread(capture)`` names the files of the repository that look like such sources and that no role of the structure
  map read: rule and data files in a folder named for requirements, rules, issues, findings, evidence or tasks
  (grouped as ``rules/*.yaml``), issue and evidence logs (``.jsonl``), and documents with task rows (a table row or
  a checkbox that carries a task id) that are not read as task lists. kernel/repo_structure.py keeps them in the
  structure map as ``unread``; kernel/start_here.py names them in its step.

By rule, from names and, for documents only, a look for task rows; nothing found is run.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

READS = ("requirement lines in specs and requirement documents, JSON rule files, task lists, a README's status "
         "table, ADRs, API contracts and test names")
CANNOT = "other rule or data files (.yaml, .csv), issue or evidence logs (.jsonl) or task rows in other documents"
SOURCE_DIR = re.compile(r"(?i)^(rules?|laws?|polic(?:y|ies)|requirements?|reqs|specs?|issues?|findings?|evidence|"
                        r"tasks?|backlog|stories|criteria|acceptance|tickets?|bugs?|decisions?|plans?)$")
DATA_EXT = (".json", ".yaml", ".yml", ".toml", ".csv")
LOG_EXT = (".jsonl", ".ndjson")
DOC_EXT = (".md", ".markdown")
TASK_ROW = re.compile(r"(?m)^\s*(?:\|.*\b[A-Z]{1,6}-\d{1,5}\b.*\||[-*] \[[ xX]\] .+)\s*$")
MAX_DOCS = 40                     # documents looked at for task rows, at most
MAX_DOC = 256 * 1024
KINDS = {"data": "rules or data", "log": "an issue or evidence log", "rows": "task rows in a document"}
SHOWN = 8


def _in_source_dir(rel: str) -> bool:
    return any(SOURCE_DIR.match(part) for part in PurePosixPath(rel).parts[:-1])


def _grouped(paths: list[str], kind: str) -> list[dict[str, Any]]:
    """Files of one kind grouped by folder and extension: ``rules/*.json`` (2 files)."""
    by: dict[str, list[str]] = {}
    for rel in paths:
        p = PurePosixPath(rel)
        key = str(p.parent / f"*{p.suffix}") if p.parent != PurePosixPath(".") else rel
        by.setdefault(key, []).append(rel)
    return [{"path": key if len(rels) > 1 else rels[0], "files": len(rels), "kind": KINDS[kind]}
            for key, rels in sorted(by.items())]


def proposal_dates(capture: Any) -> dict[str, int]:
    """Each file a proposal is taken from, with its last commit: where it came from and how old (FR-ORG1)."""
    rels = [r for role in ("spec", "feature", "tasks", "adr", "api", "test") for r in capture.by_role.get(role, [])]
    return {rel: capture.src.dates[rel] for rel in rels if rel in capture.src.dates}


def unread(capture: Any) -> list[dict[str, Any]]:
    """The likely sources of a repository's real work that the structure map did not read, each with its kind."""
    from kernel import material_kinds as mk
    from kernel import repo_structure as rs

    data: list[str] = []
    logs: list[str] = []
    docs: list[str] = []
    read_roles = set(rs.READ_ROLES) | {"ai"}
    for rel, size in capture.src.files:
        low = rel.lower()
        if rs.archived(rel) or mk.secret_by_name(rel) or read_roles & rs.roles(rel):
            continue
        if low.endswith(LOG_EXT):
            logs.append(rel)
        elif low.endswith(DATA_EXT) and _in_source_dir(rel):
            data.append(rel)
        elif low.endswith(DOC_EXT) and size <= MAX_DOC and len(docs) < MAX_DOCS:
            docs.append(rel)
    rows = []
    for rel in docs:
        raw = capture.src.read(rel)
        text = raw.decode("utf-8", "replace") if raw else ""
        if len(TASK_ROW.findall(text)) >= 2 and not mk.secret_in_text(rel, text):
            rows.append(rel)
    return _grouped(data, "data") + _grouped(logs, "log") + _grouped(rows, "rows")


def named(items: list[dict[str, Any]], limit: int = SHOWN) -> str:
    """The unread sources in words: ``rules/*.json (2 files), docs/evidence/issues.jsonl``."""
    words = [u["path"] + (f" ({u['files']} files)" if u.get("files", 1) > 1 else "") for u in items[:limit]]
    more = len(items) - limit
    return ", ".join(words) + (f" and {more} more" if more > 0 else "")


__all__ = ["CANNOT", "READS", "named", "unread"]
