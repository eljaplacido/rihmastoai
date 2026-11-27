"""Fakes for the self-healing tests (FR-HEAL1): a small repository with a bug and a remote, the fix that mends it, a
scripted verifier, a fake ``gh`` put first on PATH, and the self-healing write routes for the cockpit's completeness
tables (tests/test_brief_ln.py, tests/test_access.py). No real GitHub, no real model: ``gh`` is a script that records
its arguments and prints a pull request's address; the remote is a bare repository in the test's folder.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest import mock

CALC = "def parse(text):\n    return int(text)\n"
CALC_FIXED = "def parse(text):\n    text = text.strip()\n    return int(text) if text else 0\n"
SUITE = ("import unittest\n\nfrom app.calc import parse\n\n\nclass CalcTest(unittest.TestCase):\n"
         "    def test_parse_reads_a_number(self):\n        self.assertEqual(parse('7'), 7)\n")
REPRO = ("import unittest\n\nfrom app.calc import parse\n\n\nclass IncidentTest(unittest.TestCase):\n"
         "    def test_reproduces_empty_input(self):\n        self.assertEqual(parse(''), 0)\n")
FIX = {"summary": "parse reads an empty text as 0", "test": {"path": "tests/test_incident.py", "content": REPRO},
       "change": [{"path": "app/calc.py", "content": CALC_FIXED}]}
NO_FINDINGS = "```json\n{\"findings\": []}\n```"
GH = r'''import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": args, "cwd": os.getcwd()}) + "\n")
if args[:2] == ["auth", "status"]:
    sys.exit(0 if os.environ.get("FAKE_GH_SIGNED_IN", "1") == "1" else 1)
if args[:2] == ["pr", "create"]:
    print("https://github.example/acme/calc/pull/7")
    sys.exit(0)
sys.exit(2)
'''


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


def make_repo(root: Path) -> Path:
    """A repository with a bug (an empty text crashes ``parse``), its suite, and a bare ``origin`` beside it."""
    repo = root / "calc"
    if (repo / ".git").exists():
        return repo
    (repo / "app").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "app" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "app" / "calc.py").write_text(CALC, encoding="utf-8")
    (repo / "tests" / "test_calc.py").write_text(SUITE, encoding="utf-8")
    _git(repo.parent, "init", "-q", "-b", "main", "calc")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "calc")
    _git(root, "init", "-q", "--bare", "-b", "main", "remote.git")
    _git(repo, "remote", "add", "origin", str(root / "remote.git"))
    _git(repo, "push", "-q", "origin", "main")
    return repo


def fake_gh(case: Any, root: Path, *, signed_in: bool = True) -> Path:
    """A ``gh`` first on PATH for the rest of the test; returns the file each call's arguments are written to."""
    folder = root / "fake-bin"
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "fake_gh.py"
    script.write_text(GH, encoding="utf-8")
    if os.name == "nt":
        (folder / "gh.cmd").write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = folder / "gh"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    log = root / "gh-calls.jsonl"
    env = {"PATH": str(folder) + os.pathsep + os.environ.get("PATH", ""), "FAKE_GH_LOG": str(log),
           "FAKE_GH_SIGNED_IN": "1" if signed_in else "0"}
    patcher = mock.patch.dict(os.environ, env)
    patcher.start()
    case.addCleanup(patcher.stop)
    os.environ.pop("RIHMASTO_GH", None)
    return log


def gh_calls(log: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def attached_incident(case: Any) -> tuple[Any, dict[str, Any]]:
    """The calc repository attached as a project, and an incident on it (a crash on an empty text)."""
    from kernel import incidents
    from kernel.attach import attach

    repo = make_repo(case.tmp / "heal")
    found = [p for p in case.factory.projects() if p.meta.get("title") == "Calc"]
    project = found[0] if found else attach(case.factory, "Calc", repo=repo, person="Aino Example",
                                            persona="developer")
    doc = incidents.open_incident(case.factory, kind="job_failed", where="job:run", project=project.pid,
                                  message="ValueError: invalid literal for int() with base 10: ''",
                                  error_class="exit 1", by="the job runner",
                                  context={"repo": str(repo), "trace": [f'  File "{repo}/app/calc.py", line 2']})
    return project, doc


def write_routes(case: Any, w: dict[str, Any]) -> list[tuple[Any, ...]]:
    """The self-healing write routes (cockpit/heal_routes.py, FR-HEAL1), each signed and recorded, in an order where
    each one's target exists."""
    b = w["built"].pid
    project, doc = attached_incident(case)
    fake_gh(case, case.tmp / "heal")
    case.server.fix_verifier = lambda prompt: NO_FINDINGS
    if hasattr(case, "pcall"):
        # With access enforced the suites run only through IT's isolation runner (a container, not on this test
        # machine), so the fix's gate says not measured. The enforced table checks who may act, not the gate
        # (tests/test_heal_fix.py judges it): here the gate's record is a passed one.
        passed = {"verdict": "passed", "warranted": True, "objections": [],
                  "signals": [{"name": n, "verdict": "passed", "detail": "-"} for n in ("tests", "fail_first",
                                                                                        "verifier")]}
        patcher = mock.patch("kernel.heal_fix._gate", return_value=passed)
        patcher.start()
        case.addCleanup(patcher.stop)

    def inc(got: dict[str, Any]) -> str:
        return got["post_incident"]["incident"]["id"]

    def dev(who: str, got: dict[str, Any]) -> dict[str, Any]:
        return {"person": who, "persona": "developer"}

    return [
        ("post_incident", "POST", "/api/incidents",
         lambda who, got: {"kind": "report", "where": "overview", "words": "the page froze", "project": b,
                           "person": who, "persona": "developer"}),
        ("post_incident_investigate", "POST", lambda got: f"/api/incidents/{inc(got)}/investigate", dev),
        ("post_incident_remedy", "POST", lambda got: f"/api/incidents/{inc(got)}/remedy",
         lambda who, got: {"remedy": "investigate", "person": who, "persona": "developer"}),
        ("post_incident_resolve", "POST", lambda got: f"/api/incidents/{inc(got)}/resolve",
         lambda who, got: {"how": {"kind": "retry_read"}, "person": who, "persona": "developer"}),
        ("post_remedy_approve", "POST", lambda got: f"/api/remedies/{got['post_incident_resolve']['remedy']['id']}"
         "/approve", lambda who, got: {"person": who, "persona": "it"}),
        ("post_remedy_retire", "POST", lambda got: f"/api/remedies/{got['post_incident_resolve']['remedy']['id']}"
         "/retire", lambda who, got: {"reason": "a better one came", "person": who, "persona": "it"}),
        ("post_incident_fix", "POST", f"/api/incidents/{doc['id']}/fix",
         lambda who, got: {"fix": FIX, "target": "project", "person": who, "persona": "developer"}),
        ("post_fix_pr", "POST", lambda got: f"/api/fixes/{got['post_incident_fix']['fix']['id']}/pr",
         lambda who, got: {"approve": True, "person": who, "persona": "developer"}),
        ("post_feedback", "POST", "/api/feedback",
         lambda who, got: {"kind": "unclear", "where": {"view": "overview", "text": "Waits for"}, "words": "for what?",
                           "suggest": "Waiting on", "person": who, "persona": "product_owner"}),
        ("post_feedback_settle", "POST",
         lambda got: f"/api/feedback/{got['post_feedback']['feedback']['proposal']['id']}/settle",
         lambda who, got: {"verdict": "approve", "person": who, "persona": "product_owner"}),
    ]
