"""FR-CON1: the console and "Open a terminal here", in the kernel and on the command line.

A run is a job in the project's workspace, line-streamed to its log, with a time limit and a stop that ends
every process it started; recorded as console_ran (who, persona, command line, exit, duration) with no
environment value and no output; for the personas the console allows; through IT's isolation runner when
access is enforced. Gnomon runs under the workspace's own surface. No terminal window opens in these tests:
the launcher is a stand-in.
"""

import contextlib
import io
import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from console_fakes import PERSON, Launcher, attached, fake_tool, git_repo  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402

from kernel import access as kaccess  # noqa: E402
from kernel import access_isolation as kisolation  # noqa: E402
from kernel import console as kconsole  # noqa: E402
from kernel import console_offers, console_term  # noqa: E402
from kernel import console_run as crun  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.store import write_json  # noqa: E402

PY = sys.executable
SECRET = "sk-" + "test-value-never-recorded-1234567890"   # built at run time: no key-shaped literal ships


def py(code: str) -> str:
    """A console line that runs ``code`` with this Python (quoted for the console's own split)."""
    return f'python -c "{code}"'


class ConsoleCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "lanes")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = git_repo(self.tmp / "orders", {
            "README.md": "# Orders\n",
            "package.json": json.dumps({"name": "orders", "scripts": {"test": "node test.js", "lint": "eslint ."}}),
            "Makefile": "build:\n\techo built\n\n.PHONY: build\ncheck: build\n\techo ok\n",
            ".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n      - run: npm ci\n      - run: |\n"
                                        "          npm test\n          npm run lint\n",
            "tests/test_one.py": "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n"
                                 "        self.assertTrue(True)\n"})
        self.p = attached(self.factory, self.repo)

    def records(self, kind):
        return [r["event"]["payload"] for r in self.p.ledger().of_kind(kind)]


class RecordedTest(ConsoleCase):
    def test_FR_CON1_AC_1_a_run_is_recorded_with_who_and_how_it_ended_never_its_output_or_environment(self):
        with mock.patch.dict(os.environ, {"OPENCODE_API_KEY": SECRET}):
            out = kconsole.run(self.p, {"line": py("import os; print(6 * 7 * 1000 + 1, os.path.basename(os.getcwd()))")},
                               person=PERSON, persona="developer")
        self.assertEqual((out["state"], out["code"], out["workspace"]), ("done", 0, "attached"), out)
        log = Path(out["log"]).read_text(encoding="utf-8")
        self.assertIn("42001 orders", log)                              # it ran in the attached repository
        [rec] = self.records("console_ran")
        self.assertEqual((rec["person"], rec["persona"], rec["state"], rec["exit"], rec["workspace"]),
                         (PERSON, "developer", "done", 0, "attached"))
        self.assertIn("print(6 * 7 * 1000 + 1", rec["command"])
        self.assertIsInstance(rec["seconds"], float)
        ledger = self.p.path("ledger.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("42001", ledger)                               # its output stays in the job log
        self.assertNotIn(SECRET, ledger)
        self.assertNotIn(SECRET, log)
        # a failing command is recorded with its exit code
        out = kconsole.run(self.p, {"line": py("import sys; sys.exit(3)")}, person=PERSON, persona="it")
        self.assertEqual((out["state"], out["code"]), ("failed", 3))
        self.assertEqual(self.records("console_ran")[-1]["exit"], 3)

    def test_FR_CON1_AC_1_the_console_is_for_the_personas_it_allows_and_it_sets_which(self):
        before = self.p.path("ledger.jsonl").read_text(encoding="utf-8")
        for persona in ("stakeholder", "business_owner", "compliance"):
            with self.assertRaises(kconsole.ConsoleRefused) as caught:
                kconsole.run(self.p, {"line": "git status"}, person=PERSON, persona=persona)
            self.assertIn("developer, it", str(caught.exception))
        with self.assertRaises(kconsole.ConsoleRefused):
            kconsole.run(self.p, {"line": "git status"}, person="kernel", persona="developer")   # not a person
        self.assertEqual(self.p.path("ledger.jsonl").read_text(encoding="utf-8"), before)
        self.assertEqual(self.records("console_ran"), [])
        with self.assertRaises(kconsole.ConsoleRefused):                 # only IT changes who may
            kconsole.set_settings(self.p, person=PERSON, persona="developer", personas=["operations"])
        kconsole.set_settings(self.p, person="Ilkka IT", persona="it", personas=["it", "operations"])
        self.assertEqual(kconsole.settings(self.p)["personas"], ["it", "operations"])
        with self.assertRaises(kconsole.ConsoleRefused):
            kconsole.run(self.p, {"line": "git status"}, person=PERSON, persona="developer")
        self.assertEqual(kconsole.run(self.p, {"line": "git status"}, person="Olli Ops", persona="operations")["state"],
                         "done")
        self.assertEqual(self.records("console_settings")[-1]["personas"], ["it", "operations"])


class LauncherTest(ConsoleCase):
    def test_FR_CON1_AC_2_a_projects_py_3_runs_as_its_words_say(self):
        cwd = Path(kconsole.workspace(self.p)["path"])
        with mock.patch.object(kconsole.shutil, "which", return_value="C:\\Windows\\py.exe"):
            plan = kconsole.command_plan(self.p, "py -3 tools/status.py", cwd, "attached")
        self.assertEqual(plan.argv[:3], ["py", "-3", "tools/status.py"])           # the launcher is kept
        with mock.patch.object(kconsole.shutil, "which", return_value=None):
            plan = kconsole.command_plan(self.p, "py -3 tools/status.py", cwd, "attached")
        self.assertEqual(plan.argv[1:], ["tools/status.py"])                       # no launcher: its flag is dropped
        self.assertNotIn("-3", plan.argv)

    def test_FR_CON1_AC_2_a_failed_run_says_why_in_its_own_words(self):
        from cockpit.console_routes import _why

        log = self.tmp / "run.log"
        log.write_text("$ py -3 tools/status.py\n[in the working_copy workspace]\nUnknown option: -3\nusage: python "
                       "[option]\n\n[exit 2 after 0.1 s]\n", encoding="utf-8")
        self.assertEqual(_why({"state": "failed", "log": str(log)}), "Unknown option: -3")
        self.assertIsNone(_why({"state": "done", "log": str(log)}))                # a run that worked needs no why


class WorkspaceTest(ConsoleCase):
    def test_FR_CON1_AC_2_the_workspace_and_the_commands_it_offers(self):
        ws = kconsole.workspace(self.p)
        self.assertEqual((ws["kind"], Path(ws["path"])), ("attached", self.repo.resolve()))
        kconsole.set_settings(self.p, person=PERSON, persona="developer", commands={"test": "python -m unittest -v"})
        lines = {o["line"]: o for o in kconsole.offered(self.p)}
        for line in ("python -m unittest -v", "npm run test", "npm run lint", "make build", "make check", "npm ci"):
            self.assertIn(line, lines, sorted(lines))
        self.assertEqual(lines["python -m unittest -v"]["source"], "stated for the project")
        self.assertIn("npm test\nnpm run lint", lines)
        self.assertTrue(lines["npm test\nnpm run lint"]["shell"])        # a step of two lines runs in the shell
        self.assertFalse(lines["make build"]["shell"])
        self.assertTrue(any(o["source"].startswith("detected by rule") for o in lines.values()))

    def test_FR_CON1_AC_2_a_built_project_runs_in_the_consoles_working_copy_which_cannot_push(self):
        p = self.factory.new_project("Loans", maturity="demo", mode="mixed")
        bare = p.path("repo.git")
        source = git_repo(self.tmp / "loans-src", {"app.py": "print('loans')\n"})
        import subprocess

        subprocess.run(["git", "clone", "-q", "--bare", str(source), str(bare)], check=True, capture_output=True)
        ws = kconsole.workspace(p)
        self.assertEqual((ws["kind"], ws["exists"]), ("working_copy", False))   # made at the first run, not read
        out = kconsole.run(p, {"line": py("print(open('app.py').read())")}, person=PERSON, persona="developer")
        self.assertEqual(out["state"], "done", Path(out["log"]).read_text(encoding="utf-8"))
        path = Path(kconsole.workspace(p)["path"])
        self.assertEqual(path, self.tmp / "lanes" / "workspaces" / p.pid / "console")
        push = subprocess.run(["git", "remote", "get-url", "--push", "origin"], cwd=path, capture_output=True,
                              text=True).stdout.strip()
        self.assertEqual(push, kconsole.NO_PUSH)
        none = self.factory.new_project("Idea", maturity="demo", mode="mixed")
        with self.assertRaises(kconsole.ConsoleRefused) as caught:
            kconsole.run(none, {"line": "git status"}, person=PERSON, persona="developer")
        self.assertIn("no code yet", str(caught.exception))


class StreamingTest(ConsoleCase):
    def test_FR_CON1_AC_3_output_streams_line_by_line_while_the_command_runs(self):
        seen = []
        line = py("import time; print('first', flush=True); time.sleep(2); print('second', flush=True)")
        started = time.monotonic()
        stamps = []

        def echo(text):
            seen.append(text)
            stamps.append(time.monotonic() - started)

        out = kconsole.run(self.p, {"line": line}, person=PERSON, persona="developer", echo=echo)
        self.assertEqual(out["state"], "done")
        joined = "".join(seen)
        self.assertLess(joined.index("first"), joined.index("second"))
        first_at = next(s for s, t in zip(stamps, seen, strict=True) if "first" in t)
        self.assertLess(first_at, 1.8)                                    # before the command ended
        # the cockpit reads the log by offset: only whole lines while it runs
        log = self.tmp / "partial.log"
        log.write_bytes(b"one\ntw")
        self.assertEqual(crun.read_log(log, 0, ended=False), ("one\n", 4))
        self.assertEqual(crun.read_log(log, 4, ended=True), ("tw", 6))

    def test_FR_CON1_AC_3_one_program_without_a_shell_unless_asked_and_stdin_is_closed(self):
        with self.assertRaises(ValueError) as caught:
            kconsole.run(self.p, {"line": "git log | head -1"}, person=PERSON, persona="developer")
        self.assertIn("Run through the shell", str(caught.exception))
        out = kconsole.run(self.p, {"line": "git log --oneline | git hash-object --stdin", "shell": True},
                           person=PERSON, persona="developer")
        self.assertEqual(out["state"], "done", Path(out["log"]).read_text(encoding="utf-8"))
        self.assertTrue(self.records("console_ran")[-1]["shell"])
        out = kconsole.run(self.p, {"line": py("import sys; print(repr(sys.stdin.read()))")}, person=PERSON,
                           persona="developer")
        self.assertIn("''", Path(out["log"]).read_text(encoding="utf-8"))   # input reads as ended, never waits
        self.assertTrue(console_offers.needs_shell("a && b"))
        self.assertFalse(console_offers.needs_shell(py("import os; print(1)")))


class StopTest(ConsoleCase):
    def child_line(self, marker: Path) -> str:
        """A command whose own child writes ``marker`` after three seconds, unless it is stopped first."""
        script = self.tmp / "parent.py"
        inner = f"import time, pathlib; time.sleep(3); pathlib.Path({str(marker)!r}).write_text('late')"
        script.write_text("import subprocess, sys, time\n"
                          f"subprocess.Popen([sys.executable, '-c', {inner!r}])\n"
                          "print('started', flush=True)\ntime.sleep(30)\n", encoding="utf-8")
        return f'python "{script}"'

    def test_FR_CON1_AC_4_the_time_limit_and_stop_end_the_command_and_everything_it_started(self):
        marker = self.tmp / "late.txt"
        out = kconsole.run(self.p, {"line": self.child_line(marker)}, person=PERSON, persona="developer", timeout=2)
        log = Path(out["log"]).read_text(encoding="utf-8")
        self.assertEqual(out["state"], "timed_out", log)
        self.assertIn("started", log)
        self.assertIn("time limit of 2 s", log)
        self.assertEqual(self.records("console_ran")[-1]["state"], "timed_out")
        # Stop, from the cockpit's job runner
        jobs = crun.Jobs()
        ended = threading.Event()
        started = kconsole.start(self.p, {"line": self.child_line(marker)}, person=PERSON, persona="developer",
                                 jobs=jobs, on_end=lambda write: (write(), ended.set()))
        deadline = time.monotonic() + 10
        while "started" not in started["log"].read_text(encoding="utf-8") and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(jobs.stop(started["id"]))
        self.assertTrue(ended.wait(15))
        self.assertEqual(jobs.status(started["id"])["state"], "stopped")
        self.assertFalse(jobs.stop(started["id"]))                       # not running any more
        self.assertIn("stopped by a person", started["log"].read_text(encoding="utf-8"))
        self.assertEqual(self.records("console_ran")[-1]["state"], "stopped")
        time.sleep(3.5)
        self.assertFalse(marker.exists())                                # its child was stopped too


class IsolationTest(ConsoleCase):
    def enforce(self, isolation):
        doc = {"schema": kaccess.SCHEMA, "mode": "enforced", "changed_by": "local:it-admin",
               "proxy": {"preset": "oauth2-proxy", "issuer": "https://id.example", "origin": "https://r.example",
                         "audience": "rihmasto", "groups_claim": "groups"},
               "people": [{"identity": "local:dana", "name": PERSON}, {"identity": "local:it-admin", "name": "Ilkka IT"}],
               "bindings": [{"subject": "local:dana", "persona": "developer", "scope": "*"},
                            {"subject": "local:it-admin", "persona": "it", "scope": "*"}]}
        if isolation:
            doc["isolation"] = isolation
        path = kaccess.access_path(self.factory)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, doc)

    def test_FR_CON1_AC_5_with_access_enforced_a_run_goes_through_the_isolation_runner_or_not_at_all(self):
        self.enforce(None)
        with kisolation.serving(self.factory), self.assertRaises(kisolation.IsolationRequired):
            kconsole.run(self.p, {"line": "git status"}, person=PERSON, persona="developer")
        self.assertEqual(self.records("console_ran"), [])
        self.enforce({"runner": "container", "image": "python:3.12-slim", "docker_cli": ["docker"],
                      "cells": ["docker", "run", "--rm", "-v", "{cwd}:{cwd}", "-w", "{cwd}", "gnomon", "gnomon"]})
        with kisolation.serving(self.factory):
            plan = kconsole.prepare(self.p, {"line": "python -m unittest -v"}, person=PERSON, persona="developer")
        self.assertEqual(plan.argv[:3], ["docker", "run", "--rm"])
        for flag in ("--network", "none", "--cap-drop", "ALL", "--read-only", "python:3.12-slim", "python3"):
            self.assertIn(flag, plan.argv)
        self.assertTrue(any("dst=/work" in a for a in plan.argv))
        self.assertEqual((plan.isolated, plan.stop_argv[:3]), ("container", ["docker", "rm", "-f"]))
        with kisolation.serving(self.factory), mock.patch.dict(os.environ, {"GNOMON_CMD": "gnomon"}):
            (self.repo / ".gnomon").mkdir()
            g = kconsole.prepare(self.p, {"gnomon": "add a health endpoint"}, person=PERSON, persona="developer")
        self.assertEqual(g.argv[:4], ["docker", "run", "--rm", "-v"])          # IT's cells command, as every cell


class GnomonTest(ConsoleCase):
    def test_FR_CON1_AC_6_a_gnomon_task_runs_in_the_workspace_under_its_own_surface(self):
        gnomon = fake_tool(self.tmp / "bin", "gnomon-fake",
                           "import os, sys\nprint('gnomon in', os.path.basename(os.getcwd()), sys.argv[1:])\n")
        env = {"GNOMON_CMD": str(gnomon).replace("\\", "/")}
        with mock.patch.dict(os.environ, env), self.assertRaises(kconsole.ConsoleRefused) as caught:
            kconsole.run(self.p, {"gnomon": "add a health endpoint"}, person=PERSON, persona="developer")
        self.assertIn("never writes into your repository", str(caught.exception))
        self.assertFalse((self.repo / ".gnomon").exists())
        (self.repo / ".gnomon").mkdir()
        with mock.patch.dict(os.environ, env):
            out = kconsole.run(self.p, {"gnomon": "add a health endpoint", "role": "builder"}, person=PERSON,
                               persona="developer")
        log = Path(out["log"]).read_text(encoding="utf-8")
        self.assertEqual(out["state"], "done", log)
        self.assertIn("'task', 'add a health endpoint', '--role', 'builder'", log)
        self.assertNotIn("--yes", log)                                       # gated calls stay refused unless asked
        rec = self.records("console_ran")[-1]
        self.assertEqual((rec["kind"], rec["command"]), ("gnomon", "gnomon task 'add a health endpoint' --role builder"))
        # a confidential project's run must route locally
        self.p.update_meta(confidential=True)
        hosted = {"roles": {"builder": {"model": "m", "endpoint": "cloud"}}, "models": {"m": {"family": "x"}},
                  "endpoints": {"cloud": {"kind": "openai", "url": "https://api.example.com/v1"}}}
        with mock.patch.dict(os.environ, env), mock.patch("kernel.confidential._routing", return_value=hosted), \
                self.assertRaises(PermissionError):
            kconsole.run(self.p, {"gnomon": "add a health endpoint"}, person=PERSON, persona="developer")


class TerminalTest(ConsoleCase):
    def test_FR_CON1_AC_7_open_a_terminal_in_the_workspace_with_the_routing_environment(self):
        which = {"wt.exe": "C:/wt.exe"}.get
        self.assertEqual(console_term.terminal_argv(Path("C:/w"), system="Windows", which=which)[:3],
                         ["wt.exe", "-d", str(Path("C:/w"))])
        self.assertEqual(console_term.terminal_argv(Path("/w"), system="Windows", which=lambda n: None)[0],
                         "powershell.exe")
        self.assertEqual(console_term.terminal_argv(Path("/w"), system="Linux",
                                                    which={"gnome-terminal": "/usr/bin/gnome-terminal"}.get),
                         ["gnome-terminal", f"--working-directory={Path('/w')}"])
        self.assertEqual(console_term.terminal_argv(Path("/w"), system="Darwin")[:3], ["open", "-a", "Terminal"])
        with self.assertRaises(kconsole.ConsoleRefused):
            console_term.terminal_argv(Path("/w"), system="Linux", which=lambda n: None)
        launcher = Launcher()
        gnomon = self.tmp / "gbin" / "gnomon"
        with mock.patch.dict(os.environ, {"GNOMON_CMD": str(gnomon).replace("\\", "/"), "OPENCODE_API_KEY": SECRET}):
            out = console_term.open_terminal(self.p, person=PERSON, persona="developer", launcher=launcher)
        [(argv, cwd, env)] = launcher.calls
        self.assertEqual((cwd, out["workspace"]), (self.repo.resolve(), "attached"))
        self.assertEqual(env["RIHMASTO_PROJECT"], self.p.pid)
        self.assertTrue(env["PATH"].split(os.pathsep)[0].replace("\\", "/").endswith("gbin"))
        self.assertEqual(env["OPENCODE_API_KEY"], SECRET)                   # the routing's key reaches Gnomon there
        [rec] = self.records("console_opened")
        self.assertEqual((rec["person"], rec["how"]), (PERSON, "terminal"))
        self.assertNotIn(SECRET, self.p.path("ledger.jsonl").read_text(encoding="utf-8"))
        self.assertNotIn(SECRET, json.dumps(out))
        with self.assertRaises(kconsole.ConsoleRefused):
            console_term.open_terminal(self.p, person=PERSON, persona="end_user", launcher=launcher)
        self.assertEqual(len(launcher.calls), 1)
        # a Linux machine without a desktop: no terminal program, said so, and nothing is launched
        bare = BareLinux()
        self.assertIsNone(console_term.missing_terminal(launcher))
        self.assertEqual(console_term.missing_terminal(bare), console_term.NO_TERMINAL)
        with self.assertRaises(kconsole.ConsoleRefused) as caught:
            console_term.open_terminal(self.p, person=PERSON, persona="developer", launcher=bare)
        self.assertIn("open one yourself in", str(caught.exception))
        self.assertEqual(bare.calls, [])


class BareLinux(Launcher):
    """A launcher on a Linux machine with no terminal program installed."""

    def terminal_argv(self, path: Path) -> list[str]:
        return console_term.terminal_argv(path, system="Linux", which=lambda name: None)


class CommandLineTest(ConsoleCase):
    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_FR_CON1_AC_9_rihmasto_console_and_rihmasto_shell(self):
        code, out, err = self.cli("console", self.p.pid, "--person", PERSON, "--persona", "developer", "--",
                                  "python", "-c", "print('from the command line')")
        self.assertEqual(code, 0, err)
        self.assertIn("from the command line", out)
        self.assertEqual(self.records("console_ran")[-1]["via"], "command line")
        code, out, err = self.cli("console", self.p.pid, "--person", PERSON, "--persona", "developer", "--",
                                  "python", "-c", "import sys; sys.exit(4)")
        self.assertEqual(code, 4)
        code, _, err = self.cli("console", self.p.pid, "--person", PERSON, "--persona", "stakeholder", "--", "git",
                                "status")
        self.assertEqual(code, 2)
        self.assertIn("rihmasto console: the console on", err)
        code, out, _ = self.cli("console", self.p.pid, "--offers")
        self.assertIn("make build", out)
        calls = []
        with mock.patch("kernel.console_term.subprocess.call", lambda argv, **kw: calls.append((argv, kw)) or 0):
            code, out, err = self.cli("shell", self.p.pid, "--person", PERSON, "--persona", "developer")
        self.assertEqual(code, 0, err)
        self.assertEqual(Path(calls[0][1]["cwd"]), self.repo.resolve())
        self.assertEqual(self.records("console_opened")[-1]["how"], "subshell")


if __name__ == "__main__":
    unittest.main()
