"""A repository that keeps its own sources, for the project-native sources tests (FR-SRC1).

`make_repo` commits, the way a small team keeps an engine of rules: an old plan and a task list in January (never
touched again), then ten commits to the code over February and March; then, in March, the real sources: a folder of
rule files (three JSON, one YAML), each with an id, a title, its criteria and the mutant test that checks it; an
issues file (JSONL); two rounds' READMEs whose tables say each task's status; two Python packages that each keep
their own tests (pytest from the repository's root cannot import them); and a gate's results file committed from a
run on a build host. Every name is invented.
"""

from __future__ import annotations

import json
from pathlib import Path

from alignment_fixture import git, write

OLD_PLAN = """# Requirements

## Requirements

- **REQ-001**: The system MUST print a weekly summary
- **REQ-002**: The system MUST email the summary

## Tasks

- [ ] T001 Write the summary printer
- [ ] T002 Send the summary by email
"""


def rule(n: int, title: str, criteria: list, mutant: str) -> str:
    return json.dumps({"id": f"RULE-{n:03d}", "title": title, "criteria": criteria, "mutant": mutant}, indent=2) + "\n"


RULES = {
    "rules/rule_001.json": rule(1, "A score never goes below zero", ["a score of 0 minus 5 stays 0"],
                                "test_rule_001_mutant"),
    "rules/rule_002.json": rule(2, "A turn ends after three moves", ["the fourth move starts the next turn"],
                                "test_rule_002_mutant"),
    "rules/rule_003.json": rule(3, "A tie goes to the earlier player", ["equal scores: the first to reach it wins"],
                                "test_rule_003_mutant"),
    "rules/rule_004.yaml": ("id: RULE-004\ntitle: A board holds at most eight pieces\ncriteria:\n"
                            "  - a ninth piece is refused\nmutant: test_rule_004_mutant\n"),
}
ISSUES = "\n".join(json.dumps(x) for x in [
    {"id": "ISS-1", "title": "A tie is given to the later player", "severity": "high", "status": "open",
     "file": "engine/core_3.py"},
    {"id": "ISS-2", "title": "The board accepts a ninth piece", "severity": "medium", "status": "open"},
    {"id": "ISS-3", "title": "Typo in the help text", "severity": "low", "status": "closed"},
]) + "\n"
ROUND = """# Round {n}

| Task | Owner | Status |
|------|-------|--------|
| Scores never go below zero | dev | done |
| Ties go to the earlier player | dev | {tie} |
| The board refuses a ninth piece | dev | open |
"""
PKG = {
    "pkg_a/pyproject.toml": "[tool.pytest.ini_options]\npythonpath = [\".\"]\n",
    "pkg_a/alpha.py": "def score(x):\n    return max(0, x)\n",
    "pkg_a/tests/test_alpha.py": "import alpha\n\n\ndef test_score_floor():\n    assert alpha.score(-5) == 0\n",
    "pkg_b/pyproject.toml": "[tool.pytest.ini_options]\npythonpath = [\".\"]\n",
    "pkg_b/beta.py": "def turns(moves):\n    return moves // 3\n",
    "pkg_b/tests/test_beta.py": "import beta\n\n\ndef test_turns():\n    assert beta.turns(4) == 1\n",
}
GATES = json.dumps({"gates": [{"name": "test_rule_001_mutant", "status": "pass"},
                              {"name": "test_rule_002_mutant", "status": "pass"},
                              {"name": "test_rule_003_mutant", "status": "fail"}]}, indent=2) + "\n"
JUNIT = ("<?xml version=\"1.0\"?>\n<testsuite name=\"gates\" tests=\"4\">\n"
         "  <testcase classname=\"rules\" name=\"test_rule_001_mutant\"/>\n"
         "  <testcase classname=\"rules\" name=\"test_rule_002_mutant\"/>\n"
         "  <testcase classname=\"rules\" name=\"test_rule_003_mutant\"/>\n"
         "  <testcase classname=\"rules\" name=\"test_rule_004_mutant\"><failure message=\"ninth piece\"/></testcase>\n"
         "</testsuite>\n")


def write_routes(case, w=None) -> list:
    """The project's own sources' writes (FR-SRC1), on this repository attached for the case: map its tests' root,
    use an old plan anyway, read again, import results, run the mapped root, then stop the source."""
    from kernel.attach import attach

    repo = case.tmp / "own-sources-repo"
    if not (repo / ".git").exists():
        make_repo(repo)
    found = [p for p in case.factory.projects() if p.meta.get("title") == "Board engine"]
    pid = (found[0] if found else attach(case.factory, "Board engine", repo=repo, person="Ida Example",
                                         persona="developer")).pid
    base = f"/api/projects/{pid}/sources"
    dev = lambda who, got: {"person": who, "persona": "developer"}          # noqa: E731
    return [
        ("post_native_map", "POST", base + "/map",
         lambda who, got: {"spec": {"kind": "tests", "roots": [{"root": "", "command": "python tools/gate.py"}]},
                           **dev(who, got)}),
        ("post_native_use_anyway", "POST", base + "/use-anyway",
         lambda who, got: {"path": "docs/requirements.md", **dev(who, got)}),
        ("post_native_read", "POST", base + "/read", dev),
        ("post_native_import", "POST", base + "/import-results",
         lambda who, got: {"text": JUNIT, "machine": "the build host", "produced_at": "2026-11-26T03:00:00Z",
                           **dev(who, got)}),
        ("post_native_run", "POST", base + "/run", lambda who, got: {"root": "", "confirm": True, **dev(who, got)}),
        ("post_native_stop", "POST", base + "/SRC-1/stop", lambda who, got: {"reason": "moved", **dev(who, got)}),
    ]


def make_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    write(root, {"README.md": "# Board engine\n\nA rules engine for a board of eight pieces.\n",
                 "docs/requirements.md": OLD_PLAN, "docs/tasks.md": "# Tasks\n\n- [ ] T010 Old task one\n- [x] T011 Old two\n"})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "The first plan", when="2026-01-05T10:00:00+00:00")
    for i in range(10):
        write(root, {f"engine/core_{i}.py": f"STEP = {i}\n"})
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", f"Engine step {i}", when=f"2026-02-{(i * 3 + 1):02d}T10:00:00+00:00")
    write(root, {**RULES, "evidence/issues.jsonl": ISSUES, "rounds/round-1/README.md": ROUND.format(n=1, tie="open"),
                 "rounds/round-2/README.md": ROUND.format(n=2, tie="done"), **PKG, "results/gates.json": GATES})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "Rules, issues, rounds and packages", when="2026-03-12T10:00:00+00:00")
    return root
