"""Suggested changes for the team's own repository (FR-ALN1, docs/guides/alignment.md).

Alignment proposes what Rihmasto's project takes from a repository (kernel/alignment.py). What the repository
itself could change to align is only ever suggested: each suggestion is text to copy or a patch to download,
and Rihmasto never writes it into the person's folder. The person applies it in their IDE, or not.

- **criterion ids in test names**: a test traced by its file or its text, not by its name, is renamed to carry
  the criterion's id, so the trace no longer rests on a guess (a unified diff for Python and JavaScript tests);
- **a task list entry** for each requirement no task serves;
- **a CI job that runs the tests**, when no job does;
- **tests to write** for the requirements with none, and **criteria to restate** so a test can observe them;
- **specs to bring up to date** where the code they describe moved on.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from kernel.alignment import _folder, _sha


def _suggestion(kind: str, title: str, why: str, text: str, *, path: str | None = None, patch: str | None = None,
                refs: Iterable[str] = ()) -> dict[str, Any]:
    name = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48]
    return {"id": f"sg-{_sha(kind, path, text)[:10]}", "kind": kind, "title": title, "why": why, "path": path,
            "text": text, "patch": patch, "file_name": f"{name}.{'patch' if patch else 'txt'}", "refs": list(refs),
            "applies_to": "your repository: copy it or download it and apply it yourself; Rihmasto never writes there"}


def _renamed(link: dict[str, Any], line: str) -> str | None:
    """The test's definition line with the criterion id in its name, or None when it cannot be rewritten."""
    name, cid = link["proposal"]["test"], link["proposal"]["criterion_id"]
    token = cid.replace("-", "_")
    if name.startswith("test") and f"def {name}" in line:
        rest = name[len("test"):].lstrip("_")
        return line.replace(f"def {name}", f"def test_{token}_{rest}" if rest else f"def test_{token}", 1)
    for quote in ("'", '"', "`"):
        if f"{quote}{name}{quote}" in line:
            return line.replace(f"{quote}{name}{quote}", f"{quote}{cid}: {name}{quote}", 1)
    return None


Hunk = tuple[int, list[str], list[str]]
Items = list[dict[str, Any]]


def _hunk(lk: dict[str, Any], t: dict[str, Any] | None) -> tuple[Hunk, str] | None:
    """The rename of one test as a hunk with a line of context on each side, and the line saying it."""
    ctx = list((t or {}).get("ctx") or [])
    at = 1 if t and t["line"] > 1 else 0               # where the definition is within its context
    new = _renamed(lk, ctx[at]) if at < len(ctx) else None
    if t is None or new is None:
        return None
    said = f"{lk['proposal']['file']}:{t['line']}  {ctx[at].strip()}  ->  {new.strip()}"
    return (t["line"] - at, ctx, ctx[:at] + [new] + ctx[at + 1:]), said


def _diff(path: str, hunks: list[Hunk]) -> str:
    out, last = [], 0
    for start, old, new in sorted(hunks):
        if start > last:                               # an overlapping context is left to the text list
            body = "".join(f" {x}\n" if x == y else f"-{x}\n+{y}\n" for x, y in zip(old, new, strict=True))
            out.append(f"@@ -{start},{len(old)} +{start},{len(new)} @@\n" + body)
            last = start + len(old) - 1
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n" + "".join(out)


def _patch(links: Items, tests: dict[tuple[str, str], dict[str, Any]]) -> tuple[str, list[str]]:
    """One unified diff renaming every test it can, a hunk per test."""
    by_file: dict[str, list[Hunk]] = {}
    said: list[str] = []
    for lk in links:
        found = _hunk(lk, tests.get((lk["proposal"]["file"], lk["proposal"]["test"])))
        if found:
            by_file.setdefault(lk["proposal"]["file"], []).append(found[0])
            said.append(found[1])
    return "".join(_diff(path, by_file[path]) for path in sorted(by_file)), said


def _renames(items: Items, structure: dict[str, Any]) -> Items:
    guessed = [i for i in items if i["group"] == "trace" and i.get("basis") != "by name"]
    if not guessed:
        return []
    tests = {(f["path"], t["name"]): t for f in structure.get("tests", {}).get("files", []) for t in f["tests"]}
    patch, said = _patch(guessed, tests)
    listed = said or [f"{i['proposal']['file']}::{i['proposal']['test']} -> {i['proposal']['criterion_id']}"
                      for i in guessed]
    many = len(guessed) > 1
    return [_suggestion("rename_tests", "Add criterion ids to these test names",
                        f"{len(guessed)} test{'s are' if many else ' is'} traced by file or text, not by name: "
                        "with the id in the name, the trace is exact and the gate reads it (tests named "
                        "test_<criterion id>_...)",
                        "\n".join(listed), patch=patch or None, refs=[i["id"] for i in guessed])]



def _task_entries(items: Items) -> Items:
    served = {x for i in items if i["group"] == "tasks" for x in i["proposal"]["targets"]}
    lists = {_folder(i["source"]["path"]): i["source"]["path"] for i in items if i["group"] == "tasks"}
    loose: dict[str, Items] = {}
    for r in (i for i in items if i["group"] == "requirements" and not ({i["id"], *i["children"]} & served)):
        target = lists.get(_folder(r["source"]["path"])) or min(lists.values(), default="tasks.md")
        loose.setdefault(target, []).append(r)
    return [_suggestion("tasks_entry", f"Add a task list entry in {path}",
                        f"{plural(len(reqs), 'requirement')} from this spec {'have' if len(reqs) > 1 else 'has'} no "
                        "task in the repository's task lists",
                        "\n".join(f"- [ ] {r['proposal']['id']} {r['proposal']['statement']}" for r in reqs), path=path,
                        refs=[r["id"] for r in reqs]) for path, reqs in sorted(loose.items())]


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _ci_jobs(items: Items, structure: dict[str, Any]) -> Items:
    run = structure.get("tests", {}).get("run") or ["pytest"]
    out = []
    for gap in (i for i in items if i.get("kind") == "ci_no_tests"):
        path = gap["source"]["path"] or ".github/workflows/tests.yml"
        steps = "\n".join(f"      - run: {cmd}" for cmd in run[:3])
        text = ("  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n" + steps
                if path.startswith(".github/") else "Add a job or step that runs: " + "; ".join(run[:3]))
        out.append(_suggestion("ci_tests", f"This CI does not run the tests: add a test job to {path}", gap["why"],
                               text, path=path, refs=[gap["id"]]))
    return out


def _where(i: dict[str, Any]) -> str:
    return f"{i['proposal']['id']} ({i['source']['path']}:{i['source']['lines'][0]})"


def _gapped(items: Items, kind: str) -> Items:
    """The items the gaps of a kind are about."""
    index = {i["id"]: i for i in items}
    return [index[g["proposal"]["refs"][0]] for g in items if g.get("kind") == kind]


def _write_tests(items: Items) -> Items:
    reqs = _gapped(items, "no_test")
    text = "\n".join(f"- {_where(r)}: {r['proposal']['statement']}  -> test_{r['proposal']['id'].replace('-', '_')}"
                     "_AC_1_..." for r in reqs)
    return [_suggestion("write_tests", "Write a test for each requirement with none", "no test of the repository "
                        "traces to these requirements", text, refs=[r["id"] for r in reqs])] if reqs else []


def _restate(items: Items) -> Items:
    crits = _gapped(items, "untestable")
    text = "\n".join(f"- {_where(c)}: {c['untestable']}.\n  Given <a state>, When <an action>, Then <something a "
                     "test can see>" for c in crits)
    return [_suggestion("testable", "Restate these criteria so a test can observe them", "each says something no "
                        "test can check as written", text, refs=[c["id"] for c in crits])] if crits else []


def _stale(items: Items) -> Items:
    stale = [g for g in items if g.get("kind") == "stale_spec"]
    return [_suggestion("stale_spec", "Bring these specs up to date with the code", "the code they describe was "
                        "committed after them", "\n".join(f"- {g['why']}" for g in stale),
                        refs=[g["id"] for g in stale])] if stale else []


def _lists(items: Items) -> Items:
    """The tests to write, the criteria to restate and the specs to bring up to date, as lists to copy."""
    return _write_tests(items) + _restate(items) + _stale(items)


def suggestions(proposal: dict[str, Any], structure: dict[str, Any]) -> Items:
    """What the repository could change to align with what was proposed: never written, only offered."""
    items = proposal["items"]
    return _renames(items, structure) + _task_entries(items) + _ci_jobs(items, structure) + _lists(items)
