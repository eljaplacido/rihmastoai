"""Shared fakes for the v1 kernel tests: a scripted model, a scripted builder cell, a temp factory."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kernel import lanes
from kernel.model import FakeModel
from kernel.models_setup import SECRETS_ENV
from kernel.store import REPO_ROOT, Factory, FixedClock

# The key variables a test of Models setup must not find set on the machine that runs it.
KEY_VARS = ("OPENCODE_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "RIHMASTO_KEY_ANALYST",
            "RIHMASTO_KEY_ASSISTANT", "RIHMASTO_KEY_BUILDER")


def isolated_routing(case: unittest.TestCase, tmp: Path) -> Path:
    """The shipped routing copied to ``tmp``, the machine's overlay and the stored keys there too, and no key
    variable set, until ``case`` ends: a test of Models setup never writes this checkout's routing or reads
    this machine's keys. Returns the folder."""
    folder = Path(tmp) / "routing"
    folder.mkdir(parents=True, exist_ok=True)
    if not (folder / "routing.json").exists():
        shutil.copyfile(REPO_ROOT / "kernel" / "routing.json", folder / "routing.json")
    for name, path in (("ROUTING_FILE", folder / "routing.json"), ("ROUTING_LOCAL_FILE", folder / "routing.local.json")):
        patcher = mock.patch.object(lanes, name, path)
        patcher.start()
        case.addCleanup(patcher.stop)
    env = mock.patch.dict(os.environ, {SECRETS_ENV: str(folder / "secrets.json")})
    env.start()
    case.addCleanup(env.stop)
    for name in KEY_VARS:
        os.environ.pop(name, None)
    held = mock.patch("kernel.models_setup.gnomon_keys", return_value=frozenset())   # nor the keys Gnomon holds here
    held.start()
    case.addCleanup(held.stop)
    from kernel.runners.detect import env_name  # nor the coding agents installed here (FR-HMD1): a test's fakes only

    nowhere = {env_name(k): json.dumps([str(Path(tmp) / "nowhere" / k)]) for k in ("claude-code", "codex", "opencode")}
    agents = mock.patch.dict(os.environ, {k: v for k, v in nowhere.items() if k not in os.environ})
    agents.start()
    case.addCleanup(agents.stop)
    return folder

PANEL = {
    "business": [
        {"text": "Who approves a loan?", "why": "decides the workflow", "blocking": True,
         "proposed_answer": "the team lead approves",
         "options": ["any team member", "the team lead approves", "the IT desk", "a fourth", "a fifth that is cut"]},
        {"text": "How is benefit measured?", "why": "baseline", "blocking": False,
         "proposed_answer": "fewer lost items per month"},
    ],
    "end_user": [{"text": "Do users need a mobile view?", "why": "daily use", "blocking": False,
                  "proposed_answer": "a simple page that works on a phone"}],
    "it_security": [{"text": "Is single sign-on required?", "why": "identity", "blocking": False,
                     "proposed_answer": "no, a shared team page is enough for the demo"}],
    "operations": [{"text": "What availability is needed?", "why": "support", "blocking": False,
                    "proposed_answer": "office hours"}],
    "delivery": [{"text": "What is the smallest first version?", "why": "scope", "blocking": False,
                  "proposed_answer": "add an item, lend it, return it"}],
}

SPEC = {
    "title": "Equipment loans", "summary": "Track which team equipment is lent to whom.",
    "users": ["team members"],
    "requirements": [
        {"statement": "A team member can add an item with a name.", "sources": ["request"], "priority": "must",
         "acceptance": [{"given": "no items", "when": "POST /items with a name", "then": "201 and the item has an id",
                         "kind": "test"},
                        {"given": "an item", "when": "GET /items", "then": "the item is listed", "kind": "holdout"}]},
        {"statement": "A loan needs the approver's name.", "sources": ["Q-001"], "priority": "must",
         "acceptance": [{"given": "an item", "when": "POST /items/{id}/loan without approver",
                         "then": "400 with an error", "kind": "test"}]},
        {"statement": "Benefit is reported as lost items per month.", "sources": ["Q-002"], "priority": "should",
         "acceptance": [{"given": "-", "when": "GET /report", "then": "200 with lost_per_month", "kind": "test"}]},
        {"statement": "The page loads fast.", "sources": ["proposed"], "priority": "could",
         "acceptance": [{"given": "-", "when": "GET /health", "then": "answers in under 500 ms", "kind": "test"},
                        {"given": "-", "when": "GET /health", "then": "answers in under 500 ms", "kind": "probe"}]},
    ],
    "out_of_scope": ["billing"],
}


def script(prompt: str, role: str) -> str:
    if "perspective on a panel" in prompt:
        for p, qs in PANEL.items():
            if f"You are the **{p}** perspective" in prompt:
                return "```json\n" + json.dumps({"reading": f"{p} reading", "questions": qs}) + "\n```"
    if "A panel of perspectives" in prompt:
        return "```json\n" + json.dumps({"opinions": [
            {"question": "Q-001", "perspective": "it_security", "opinion": "approval must be logged for audit"},
            {"question": "Q-001", "perspective": "end_user", "opinion": "any team member should approve"}]}) + "\n```"
    if "You turn a brief into a software specification" in prompt:
        return "```json\n" + json.dumps(SPEC) + "\n```"
    if "You write acceptance scenarios" in prompt:
        return "```json\n" + json.dumps({"scenarios": [
            {"criterion": "R-1-AC-2", "steps": [{"method": "POST", "path": "/items", "body": {"name": "drill"},
                                                  "expect_status": 201},
                                                 {"method": "GET", "path": "/items", "expect_status": 200,
                                                  "expect_contains": "drill"}]},
            {"criterion": "R-4-AC-2", "steps": [{"method": "GET", "path": "/health", "expect_status": 200,
                                                  "max_ms": 500}]}]}) + "\n```"
    if "Classify a piece of feedback" in prompt:
        if "crash" in prompt or "500" in prompt:
            return '```json\n{"class": "defect", "requirements": ["R-1"], "summary": "crash on empty name", ' \
                   '"regression": {"given": "-", "when": "POST /items with an empty name", "then": "400, not 500"}}\n```'
        return '```json\n{"class": "change_request", "requirements": ["R-2"], "summary": "approver optional"}\n```'
    if "Amend a software specification" in prompt:
        return "```json\n" + json.dumps({"modify": [{"id": "R-2", "statement": "A loan records the approver if given.",
                                                     "acceptance": [{"given": "an item", "when": "POST loan without approver",
                                                                     "then": "201", "kind": "test"}]}],
                                         "add": [], "withdraw": []}) + "\n```"
    raise AssertionError(f"unscripted prompt for role {role}: {prompt[:120]}")


def model() -> FakeModel:
    return FakeModel(script)


def no_local_routing():
    """A test never reads the machine's own routing overlay (kernel/routing.local.json: a private gateway, a
    coding agent as a model): it would make a test pass or fail by whose checkout it runs in."""
    return mock.patch.object(lanes, "ROUTING_LOCAL_FILE", Path(tempfile.gettempdir()) / "gf-no-routing-overlay.json")


class FactoryTestCase(unittest.TestCase):
    def setUp(self):
        patcher = no_local_routing()
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-test-"))
        self.clock = FixedClock()
        self.factory = Factory(self.tmp / "home", clock=self.clock)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def new(self, *, mode="mixed", maturity="demo", title="Equipment loans"):
        return self.factory.new_project(title, mode=mode, maturity=maturity)


# A builder cell that implements the scaffolded product correctly, criterion by criterion.
GOOD_ROUTES = '''from app.server import load_data, route, save_data


@route("POST", "/items")
def add_item(req):
    body = req.body if isinstance(req.body, dict) else {}
    name = str(body.get("name", "")).strip()
    if not name:
        return 400, {"error": "name is required"}
    items = load_data("items", [])
    item = {"id": str(len(items) + 1), "name": name}
    items.append(item)
    save_data("items", items)
    return 201, item


@route("GET", "/items")
def list_items(req):
    return 200, load_data("items", [])
'''

GOOD_TEST = '''import unittest

import app.routes  # noqa: F401
from app.server import handle


class ItemsTest(unittest.TestCase):
    def test_R_1_AC_1_post_item_returns_201_with_id(self):
        status, body, _ = handle("POST", "/items", {"name": "drill"})
        self.assertEqual(status, 201)
        self.assertIn("id", body)
'''

TRIVIAL_TEST = '''import unittest


class ItemsTest(unittest.TestCase):
    def test_R_1_AC_1_always_true(self):
        self.assertTrue(True)
'''


def good_cell(lane_path, prompt):
    Path(lane_path, "app", "routes.py").write_text(GOOD_ROUTES, encoding="utf-8", newline="\n")
    Path(lane_path, "tests", "test_items.py").write_text(GOOD_TEST, encoding="utf-8", newline="\n")
    return {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": 7, "model": "fake-builder",
            "output": "done"}


def lazy_cell(lane_path, prompt):
    Path(lane_path, "tests", "test_items.py").write_text(TRIVIAL_TEST, encoding="utf-8", newline="\n")
    return {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": 2, "model": "fake-builder",
            "output": "done"}


def no_findings(prompt):
    return '```json\n{"findings": []}\n```'


def generic_cell(lane_path, prompt):
    """A builder that meets whatever visible criteria its envelope lists: for each one it adds a
    route and a test that fails before the route exists and passes after."""
    import re as _re

    ids = sorted(set(_re.findall(r"^- \*\*(R-\d+-AC-\d+)\*\*", prompt, _re.MULTILINE)))
    routes = Path(lane_path, "app", "routes.py")
    text = routes.read_text(encoding="utf-8")
    tests = ["import unittest", "", "import app.routes  # noqa: F401", "from app.server import handle", "", "",
             "class CriteriaTest(unittest.TestCase):"]
    for cid in ids:
        slug = cid.lower().replace("-", "_")
        if f"/criteria/{cid}" not in text:
            text += f'\n\n@route("GET", "/criteria/{cid}")\ndef {slug}(req):\n    return 200, {{"criterion": "{cid}"}}\n'
        tok = cid.replace("-", "_")
        tests += [f"    def test_{tok}_is_met(self):",
                  f'        status, body, _ = handle("GET", "/criteria/{cid}")',
                  "        self.assertEqual(status, 200)", ""]
    routes.write_text(text, encoding="utf-8", newline="\n")
    name = "test_" + "_".join(i.lower().replace("-", "_") for i in ids[:1]) + ".py" if ids else "test_none.py"
    Path(lane_path, "tests", name).write_text("\n".join(tests) + "\n", encoding="utf-8", newline="\n")
    return {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": 5, "model": "fake-builder",
            "output": "done"}
