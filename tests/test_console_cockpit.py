"""FR-CON1 and FR-CHK1 through the cockpit's API: a console run as a job whose output is read back line by
line until it ends, Stop, "Open a terminal here" (a stand-in launcher; refused through a public origin), and
checks enabled, run and shown on Health and in What's next."""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from console_fakes import PERSON, Launcher, attached, fake_tool, git_repo  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402
from test_brief_ln import tree  # noqa: E402

PUBLIC = "https://rihmasto.example"


class ConsoleApiCase(CockpitTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "lanes")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = git_repo(self.tmp / "orders", {"README.md": "# Orders\n",
                                                   "Makefile": "build:\n\techo built\n"})
        self.p = attached(self.factory, self.repo)
        self.who = {"person": PERSON, "persona": "developer"}

    def follow(self, jid, limit=20):
        """Read the run's output by offset until it ends, as the Console tab does."""
        offset, text, deadline = 0, "", time.monotonic() + limit
        while time.monotonic() < deadline:
            status, out, _ = self.call("GET", f"/api/projects/{self.p.pid}/console/output?job={jid}&offset={offset}")
            self.assertEqual(status, 200, out)
            text, offset = text + out["text"], out["offset"]
            if out["ended"]:
                return text, out["job"]
            time.sleep(0.1)
        self.fail(f"{jid} did not end: {text}")


class ConsoleApiTest(ConsoleApiCase):
    def test_FR_CON1_AC_8_a_run_from_the_cockpit_is_a_job_whose_output_streams_until_it_ends(self):
        status, view, _ = self.call("GET", f"/api/projects/{self.p.pid}/console?person=Dana%20Developer")
        self.assertEqual(status, 200, view)
        self.assertEqual(view["workspace"]["kind"], "attached")
        self.assertIn("make build", [o["line"] for o in view["offers"]])
        self.assertEqual(view["settings"]["personas"], ["developer", "it"])
        line = 'python -c "import time; print(1, flush=True); time.sleep(1); print(2)"'
        status, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/console/run", {"line": line, **self.who})
        self.assertEqual(status, 201, out)
        jid = out["job"]["id"]
        text, job = self.follow(jid)
        self.assertEqual((job["state"], job["code"], job["kind"]), ("done", 0, "console"))
        self.assertIn("1\n2", text.replace("\r\n", "\n"))
        self.assertIn("[exit 0 after", text)
        jobs = self.call("GET", f"/api/jobs?project={self.p.pid}")[1]
        self.assertEqual(jobs[0]["id"], jid)
        rec = self.p.ledger().of_kind("console_ran")[-1]["event"]["payload"]
        self.assertEqual((rec["via"], rec["person"], rec["exit"]), ("cockpit", PERSON, 0))
        writes = [r["event"]["payload"] for r in self.p.ledger().of_kind("cockpit_write")]
        self.assertEqual(writes[-1]["action"], "console_run")
        # a persona the console does not allow is refused and nothing is written
        before = tree(self.factory.home)
        status, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/console/run",
                                   {"line": "git status", "person": PERSON, "persona": "stakeholder"})
        self.assertEqual(status, 403, out)
        self.assertEqual(tree(self.factory.home), before)

    def test_FR_CON1_AC_8_stop_ends_a_run_from_the_cockpit(self):
        line = 'python -c "import time; print(0, flush=True); time.sleep(30)"'
        status, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/console/run",
                                   {"line": line, "timeout": 120, **self.who})
        self.assertEqual(status, 201, out)
        jid = out["job"]["id"]
        time.sleep(0.8)
        status, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/console/runs/{jid}/stop", self.who)
        self.assertEqual(status, 200, out)
        self.assertEqual((out["stopped"], out["job"]["state"]), (True, "stopped"))
        text, job = self.follow(jid)
        self.assertIn("stopped by a person", text)
        self.assertEqual(self.p.ledger().of_kind("console_ran")[-1]["event"]["payload"]["state"], "stopped")
        status, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/console/runs/{jid}/stop", self.who)
        self.assertEqual((status, out["stopped"]), (200, False))

    def test_FR_CON1_AC_7_open_a_terminal_here_only_from_the_loopback_address(self):
        path = f"/api/projects/{self.p.pid}/console/terminal"
        status, out, _ = self.call("POST", path, self.who)
        self.assertEqual(status, 409, out)                          # a server made in a test opens nothing
        self.assertIn(f"rihmasto shell {self.p.pid}", out["error"])
        launcher = Launcher()
        self.server.terminal_launcher = launcher
        self.assertTrue(self.call("GET", f"/api/projects/{self.p.pid}/console")[1]["terminal"]["available"])
        status, out, _ = self.call("POST", path, self.who)
        self.assertEqual(status, 200, out)
        self.assertEqual(launcher.calls[0][1], self.repo.resolve())
        self.assertEqual(self.p.ledger().of_kind("console_opened")[-1]["event"]["payload"]["how"], "terminal")
        self.server.public_origin = PUBLIC
        status, out, _ = self.call("POST", path, self.who, origin=PUBLIC)
        self.assertEqual(status, 403, out)
        self.assertIn("from its own address", out["error"])
        self.assertIn(PUBLIC, out["error"])
        self.assertEqual(len(launcher.calls), 1)


class HealthApiTest(ConsoleApiCase):
    def test_FR_CHK1_AC_9_checks_are_enabled_run_and_shown_on_health_and_in_whats_next(self):
        status, out, _ = self.call("GET", f"/api/projects/{self.p.pid}/checks")
        self.assertEqual((status, out["line"]), (200, "no check enabled"))
        self.assertIn("probe", [c["kind"] for c in out["catalogue"]])
        bin_dir = self.tmp / "bin"
        fake_tool(bin_dir, "smoke-test", "import sys\nprint('broken')\nsys.exit(1)\n")
        with mock.patch.dict(os.environ, {"PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}):
            status, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/checks/custom%3Asmoke/enable",
                                       {"config": {"command": "smoke-test"}, "every": "1d", **self.who})
            self.assertEqual(status, 200, out)
            status, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/checks/custom:smoke/run", self.who)
        self.assertEqual((status, out["result"]["verdict"]), (200, "failed"), out)
        self.assertEqual(out["health"]["line"], "1 check failing: Custom check (smoke)")
        view = self.call("GET", f"/api/projects/{self.p.pid}")[1]
        self.assertIn("checks_failing", [a["id"] for a in view["next"]["actions"]])
        everywhere = self.call("GET", "/api/checks")[1]
        self.assertEqual(everywhere["failing"], [f"{self.p.pid}: Custom check (smoke)"])
        status, out, _ = self.call("POST", "/api/checks/enable", {"check": "secrets", "projects": [self.p.pid],
                                                                  **self.who})
        self.assertEqual(status, 200, out)
        status, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/checks/custom:smoke/disable",
                                   {"person": PERSON, "persona": "end_user"})
        self.assertEqual(status, 403, out)
        status, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/checks/custom:smoke/disable", self.who)
        self.assertEqual((status, [c["check"] for c in out["health"]["checks"]]), (200, ["secrets"]))


if __name__ == "__main__":
    unittest.main()
