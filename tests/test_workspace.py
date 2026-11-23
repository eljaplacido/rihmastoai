import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import GOOD_ROUTES, GOOD_TEST, TRIVIAL_TEST, FactoryTestCase, model, no_findings  # noqa: E402

from kernel.canon import Canon  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes, _git  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.status import evidence  # noqa: E402
from kernel.store import REPO_ROOT  # noqa: E402
from kernel.workspace import (CONTEXT_FILE, MCP_FILE, RULE, WorkspaceRefused, launch, open_workspace,  # noqa: E402
                              submit_workspace, terminal_command, workspaces)

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
AUTHOR = ["-c", "user.name=Aino", "-c", "user.email=aino@example.invalid"]
PERSON = {"type": "person", "name": "Aino", "persona": "developer"}


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def commit_all(path: Path, message: str) -> str:
    _git(path, "add", "-A")
    _git(path, *AUTHOR, "commit", "-q", "-m", message)
    return _git(path, "rev-parse", "HEAD")


class WorkspaceCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.lanes_root = self.tmp / "lanes"

    def compiled(self):
        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        return p

    def open(self, p, agent="shell", person="Aino"):
        return open_workspace(p, person=person, persona="developer", agent=agent, root=self.lanes_root)

    def submit(self, p, ws, **kwargs):
        return submit_workspace(p, ws["path"], person="Aino", persona="developer",
                                lanes=Lanes(self.lanes_root, size=1), verifier_runner=no_findings, **kwargs)

    def main(self, p) -> str:
        return _git(p.path("repo.git"), "rev-parse", "main")


class OpenTest(WorkspaceCase):
    def test_FR_W1_AC_1_a_workspace_is_a_branch_with_context_and_mcp_config_and_launches_nothing(self):
        p = self.compiled()
        real, calls = subprocess.Popen, []

        def spy(args, *a, **k):
            calls.append(list(args) if isinstance(args, (list, tuple)) else [args])
            return real(args, *a, **k)

        with mock.patch("subprocess.Popen", spy):
            ws = self.open(p, agent="claude")
        self.assertTrue(calls)
        self.assertTrue(all(Path(str(c[0])).name.lower().startswith("git") for c in calls), calls)  # only git ran
        self.assertEqual(set(ws), {"path", "branch", "agent", "command"})
        path = Path(ws["path"])
        self.assertEqual(ws["branch"], "work/aino/1")
        self.assertEqual(path, self.lanes_root / "workspaces" / p.pid / "aino-1")
        self.assertEqual(_git(path, "rev-parse", "--abbrev-ref", "HEAD"), "work/aino/1")
        self.assertEqual(_git(path, "rev-parse", "HEAD"), self.main(p))
        context = (path / CONTEXT_FILE).read_text(encoding="utf-8")
        for part in (RULE, "## Now", "## Evidence", "## Brief", "## Spec", "## Open cards", "## Open questions",
                     "R-1-AC-1", "workspace submit", "not_measured".replace("_", " ")):
            self.assertIn(part, context)
        self.assertIn(Canon(p).brief.strip().splitlines()[0], context)
        mcp = json.loads((path / MCP_FILE).read_text(encoding="utf-8"))["mcpServers"]["rihma"]
        self.assertEqual(mcp["type"], "stdio")
        self.assertEqual(mcp["args"][0], str(REPO_ROOT / "mcp" / "server.py"))
        args = mcp["args"]
        self.assertEqual(args[args.index("--home") + 1], str(self.factory.home.resolve()))
        self.assertEqual((args[args.index("--person") + 1], args[args.index("--persona") + 1]), ("Aino", "developer"))
        self.assertEqual(_git(path, "status", "--porcelain"), "")                    # the kernel's files are not work
        self.assertEqual(ws["command"], terminal_command(path, "claude"))
        self.assertEqual(ws["command"][-1], "claude")
        opened = [r["event"]["payload"] for r in p.ledger().of_kind("workspace_opened")]
        self.assertEqual(opened, [{"person": "Aino", "persona": "developer", "agent": "claude", "branch": "work/aino/1"}])
        listed = workspaces(p)
        self.assertEqual([(w["branch"], w["agent"], w["person"], w["ahead"]) for w in listed],
                         [("work/aino/1", "claude", "Aino", 0)])
        self.assertEqual(self.open(p)["branch"], "work/aino/2")                      # a second one of her own
        with self.assertRaises(WorkspaceRefused):
            self.open(p, agent="vim")
        with self.assertRaises(WorkspaceRefused):
            self.open(p, person="assistant")

    def test_FR_W1_AC_1_the_terminal_command_per_platform_and_launch_only_on_request(self):
        path = self.tmp / "ws"
        path.mkdir()
        has = lambda *names: (lambda n: f"/usr/bin/{n}" if n in names else None)  # noqa: E731
        self.assertEqual(terminal_command(path, "claude", system="Windows", which=has("wt.exe")),
                         ["wt.exe", "-d", str(path), "claude"])
        self.assertEqual(terminal_command(path, "opencode", system="Windows", which=has()),
                         ["cmd", "/c", "start", "", "/D", str(path), "opencode"])
        self.assertEqual(terminal_command(path, "opencode", system="Linux", which=has("x-terminal-emulator")),
                         ["x-terminal-emulator", "-e", "opencode"])
        self.assertEqual(terminal_command(path, "opencode", system="Linux", which=has("gnome-terminal")),
                         ["gnome-terminal", f"--working-directory={path}", "--", "opencode"])
        self.assertEqual(terminal_command(path, "claude", system="Darwin", which=has("open")),
                         ["open", "-a", "Terminal", str(path)])
        self.assertEqual(terminal_command(path, "claude", system="Linux", which=has()), ["claude"])
        with mock.patch.dict(os.environ, {"SHELL": "/bin/zsh", "GNOMON_CMD": "gnomon-test"}):
            self.assertEqual(terminal_command(path, "shell", system="Linux", which=has()), ["/bin/zsh"])
            self.assertEqual(terminal_command(path, "gnomon", system="Linux", which=has()), ["gnomon-test"])
        started = []

        class Proc:
            pid = 4242

        def popen(argv, **kwargs):
            started.append((argv, kwargs["cwd"]))
            return Proc()

        out = launch({"path": str(path), "command": ["claude"], "branch": "work/aino/1", "agent": "claude"},
                     popen=popen)
        self.assertEqual((out["pid"], started), (4242, [(["claude"], str(path))]))


class SubmitTest(WorkspaceCase):
    def test_FR_W1_AC_2_a_persons_commits_pass_the_same_gate_and_merge_named_as_the_author(self):
        p = self.compiled()
        ws = self.open(p)
        path = Path(ws["path"])
        write(path / "app" / "routes.py", GOOD_ROUTES)
        write(path / "tests" / "test_items.py", GOOD_TEST)
        head = commit_all(path, "Items can be added (R-1-AC-1)")
        self.assertEqual(workspaces(p)[0]["ahead"], 1)
        out = self.submit(p, ws, task="T-001")
        self.assertEqual(out["status"], "merged")
        self.assertEqual({s["name"]: s["verdict"] for s in out["gate"]["signals"]},
                         {"tests": "passed", "trace": "passed", "fail_first": "passed", "verifier": "passed"})
        gate = [r["event"]["payload"] for r in p.ledger().of_kind("gate")][-1]
        self.assertEqual((gate["task"], gate["verdict"], gate["author"], gate["workspace"]),
                         ("T-001", "passed", PERSON, "work/aino/1"))
        merged = [r["event"]["payload"] for r in p.ledger().of_kind("merged")][-1]
        self.assertEqual((merged["revision"], merged["author"]), (head, PERSON))
        self.assertTrue(merged["permitted_by"].startswith("policy:"))
        self.assertEqual(self.main(p), head)                                         # her commit is main
        self.assertEqual(_git(p.path("repo.git"), "log", "-1", "--format=%an", "main"), "Aino")
        self.assertEqual((p.read("tasks.json")["T-001"]["status"], p.read("tasks.json")["T-001"]["author"]),
                         ("merged", PERSON))
        state = {e["criterion"]: e["state"] for e in evidence(p)}
        self.assertEqual(state["R-1-AC-1"], "verified")
        # a change that names no task: the suite and the verifier judge it; trace and fail-first do not apply
        write(path / "app" / "extra.py", "VALUE = 1\n")
        write(path / "tests" / "test_extra.py", "import unittest\n\nfrom app.extra import VALUE\n\n\n"
                                               "class Extra(unittest.TestCase):\n    def test_value(self):\n"
                                               "        self.assertEqual(VALUE, 1)\n")
        second = commit_all(path, "A small helper")
        out = self.submit(p, ws)
        self.assertEqual(out["status"], "merged")
        self.assertEqual({s["name"]: s["verdict"] for s in out["gate"]["signals"]},
                         {"tests": "passed", "trace": "not applicable", "fail_first": "not applicable",
                          "verifier": "passed"})
        self.assertEqual(self.main(p), second)

    def test_FR_W1_AC_2_a_failing_change_is_escalated_not_merged_then_a_fix_merges(self):
        p = self.compiled()
        ws = self.open(p)
        path = Path(ws["path"])
        main_before = self.main(p)
        write(path / "tests" / "test_items.py", TRIVIAL_TEST)                       # a test that cannot fail
        commit_all(path, "A test for R-1-AC-1")
        out = self.submit(p, ws, task="T-001")
        self.assertEqual(out["status"], "escalated")
        self.assertTrue(any(o.startswith("fail_first:") for o in out["objections"]), out["objections"])
        self.assertEqual(self.main(p), main_before)                                  # nothing reached main
        card = Canon(p).get_card(out["card"])
        self.assertEqual((card["kind"], card["refs"]["workspace"], card["refs"]["task"]),
                         ("escalation", "work/aino/1", "T-001"))
        self.assertEqual(card["payload"]["author"], PERSON)
        gate = [r["event"]["payload"] for r in p.ledger().of_kind("gate")][-1]
        self.assertEqual((gate["verdict"], gate["author"]), ("failed", PERSON))
        self.assertIn("escalated", [r["event"]["kind"] for r in p.ledger().records()])
        # a failing suite with no task named escalates too
        write(path / "tests" / "test_broken.py", "import unittest\n\n\nclass B(unittest.TestCase):\n"
                                                "    def test_broken(self):\n        self.assertEqual(1, 2)\n")
        commit_all(path, "Broken")
        out = self.submit(p, ws)
        self.assertEqual(out["status"], "escalated")
        self.assertTrue(any(o.startswith("tests:") for o in out["objections"]), out["objections"])
        self.assertEqual(self.main(p), main_before)
        # the person fixes it and submits again: it merges, and the escalations close
        (path / "tests" / "test_broken.py").unlink()
        write(path / "app" / "routes.py", GOOD_ROUTES)
        write(path / "tests" / "test_items.py", GOOD_TEST)
        commit_all(path, "Fix")
        out = self.submit(p, ws, task="T-001")
        self.assertEqual(out["status"], "merged")
        self.assertEqual(Canon(p).cards(kind="escalation"), [])

    def test_FR_W1_AC_2_an_empty_submission_or_one_touching_the_surface_is_refused(self):
        p = self.compiled()
        ws = self.open(p)
        path = Path(ws["path"])
        write(path / "app" / "routes.py", GOOD_ROUTES)                              # not committed
        with self.assertRaises(WorkspaceRefused):
            self.submit(p, ws)
        refused = [r["event"]["payload"] for r in p.ledger().of_kind("workspace_refused")]
        self.assertIn("no commits ahead of main", refused[-1]["reason"])
        self.assertNotIn("gate", [r["event"]["kind"] for r in p.ledger().records()])
        _git(path, "checkout", "-q", "--", ".")
        write(path / "contract.json", "{}\n")
        commit_all(path, "Edit the contract")
        with self.assertRaises(WorkspaceRefused):
            self.submit(p, ws)
        self.assertIn("contract.json", [r["event"]["payload"] for r in p.ledger().of_kind("workspace_refused")][-1]
                      ["reason"])
        with self.assertRaises(WorkspaceRefused):
            submit_workspace(p, self.tmp / "elsewhere", person="Aino", persona="developer")


if __name__ == "__main__":
    unittest.main()
