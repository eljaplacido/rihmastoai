"""Untrusted code never runs as the account that runs Rihmasto while access is enforced (FR-ID2, D-0016).

The gate's run of a project's own tests, a product on the local road and every Gnomon cell go through
the isolation runner the access file names: a container through the docker CLI, or a separate operating
system account through sudo. Without one, the kernel refuses that work and says why, and the cockpit
refuses to start it. A stand-in docker CLI here runs the container's command on this machine, its
mounts mapped, so the gate's outcomes really come back through it; a stand-in Gnomon records how it
was started.
"""

import json
import os
import sys
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_access import AINO, EnforcedCockpitCase, access_doc, write_access  # noqa: E402

from kernel import access_isolation as isolation  # noqa: E402
from kernel import gate  # noqa: E402
from kernel.accessfile import AccessFileError, parse  # noqa: E402
from kernel.model import run_gnomon_task  # noqa: E402
from kernel.roads import BUILTIN_ROADS, LAUNCH, LocalProcessRoad  # noqa: E402

FAKE_DOCKER = r'''
import json, os, subprocess, sys
args = sys.argv[1:]
with open(LOG, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\n")
if args[0] != "run":
    sys.exit(0)
mounts, env, workdir, i = {}, {}, None, 1
while i < len(args):
    a = args[i]
    if a in ("--rm", "--read-only"):
        i += 1
        continue
    if not a.startswith("--"):
        break
    value = args[i + 1]
    if a == "--mount":
        fields = dict(f.split("=", 1) for f in value.split(",") if "=" in f)
        mounts[fields["dst"]] = fields["src"]
    elif a == "--env":
        key, _, val = value.partition("=")
        env[key] = val
    elif a == "--workdir":
        workdir = value
    i += 2
inner = args[i + 1:]


def host(path):
    for dst, src in mounts.items():
        if path == dst or path.startswith(dst + "/"):
            return src + path[len(dst):]
    return path


command = [sys.executable] + [host(a) for a in inner[1:]]
sys.exit(subprocess.run(command, cwd=host(workdir), env={**os.environ, **{k: host(v) for k, v in env.items()}}).returncode)
'''

FAKE_GNOMON = r'''
import json, os, sys
with open(LOG, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\n")
print(json.dumps({"output": "an answer", "bucket": "ok", "stop_reason": "done"}))
'''

SUITE = textwrap.dedent('''\
    import time
    import unittest
    from pathlib import Path


    class Product(unittest.TestCase):
        def test_holds(self):
            Path(MARKER).write_text("ran", encoding="utf-8")

        def test_breaks(self):
            self.assertEqual(1, 2)

        def test_waits(self):
            time.sleep(WAIT)
    ''')


class IsolationCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.docker_log, self.gnomon_log = self.tmp / "docker.log", self.tmp / "gnomon.log"
        self.docker, self.gnomon = self.tmp / "fake_docker.py", self.tmp / "fake_gnomon.py"
        self.docker.write_text(f"LOG = {str(self.docker_log)!r}\n{FAKE_DOCKER}", encoding="utf-8")
        self.gnomon.write_text(f"LOG = {str(self.gnomon_log)!r}\n{FAKE_GNOMON}", encoding="utf-8")
        self.marker = self.tmp / "suite-ran.txt"
        self.lane = self.tmp / "lane"
        self.lane.mkdir()
        env = mock.patch.dict(os.environ, {"GNOMON_CMD": f"{Path(sys.executable).as_posix()} "
                                                         f"{self.gnomon.as_posix()} unconfined"})
        env.start()
        self.addCleanup(env.stop)

    def repo(self, wait: float = 0) -> Path:
        repo = self.tmp / f"product-{time.monotonic_ns()}"
        (repo / "tests").mkdir(parents=True)
        (repo / "tests" / "test_product.py").write_text(
            f"MARKER = {str(self.marker)!r}\nWAIT = {wait}\n" + SUITE, encoding="utf-8")
        return repo

    def runner(self, **isolated) -> dict:
        doc = access_doc()
        doc.pop("isolation")
        if isolated:
            doc["isolation"] = isolated
        write_access(self.factory, doc)
        return doc

    def docker_calls(self) -> list:
        return [json.loads(line) for line in self.docker_log.read_text(encoding="utf-8").splitlines()] \
            if self.docker_log.exists() else []

    def gnomon_calls(self) -> list:
        return [json.loads(line) for line in self.gnomon_log.read_text(encoding="utf-8").splitlines()] \
            if self.gnomon_log.exists() else []

    def package(self) -> dict:
        start = [sys.executable, "-c", f"open({str(self.marker)!r}, 'w').write('product')"]
        return {"environment": "preview", "slot": "current", "revision": "0" * 40,
                "settings": {"APP_VERSION": "0" * 12},
                "target": {"host": "127.0.0.1", "port": None, "data_dir": "envs/preview/data",
                           "traffic_log": "envs/preview/traffic.jsonl", "log": "envs/preview/current.log"},
                "artifact": {"command": start, "checkout": "."}}


class RefusedTest(IsolationCase):
    """FR-ID2-AC-1: without a runner, untrusted work is refused and says why; a single operator's runs."""

    def test_FR_ID2_AC_1_without_a_runner_the_kernel_refuses_tests_products_and_cells(self):
        self.runner()
        project = self.new()
        road = LocalProcessRoad("local-preview", BUILTIN_ROADS["local-preview"])
        with isolation.serving(self.factory):
            for what, start in (("the gate's run of a project's own tests", lambda: gate.run_suite(self.repo())),
                                ("a Gnomon cell", lambda: run_gnomon_task(self.lane, "Who asked?", role="analyst")),
                                ("a product on the local road", lambda: road.deploy(project, self.package()))):
                with self.assertRaises(isolation.IsolationRequired, msg=what) as ctx:
                    start()
                self.assertIn(f"names no isolation runner, so {what} does not run", str(ctx.exception))
                self.assertIn("docs/guides/access.md#isolation", str(ctx.exception))
        self.assertFalse(self.marker.exists())                                 # nothing ran
        self.assertEqual(self.gnomon_calls(), [])
        self.assertEqual(list(self.lane.iterdir()), [])                        # not even a task file
        # a separate account on a machine without sudo -u: refused, and told to use a container
        self.runner(runner="os_account", account="rihmasto-run")
        with isolation.serving(self.factory), mock.patch.object(isolation, "SUDO_WORKS", False), \
                self.assertRaises(isolation.IsolationRequired) as ctx:
            gate.run_suite(self.repo())
        self.assertIn("works through sudo on Linux and macOS only", str(ctx.exception))
        # a single operator: the same work runs as before
        write_access(self.factory, {"schema": "rihmasto.access/1", "mode": "single_operator",
                                    "changed_by": "Ilkka Example"})
        with isolation.serving(self.factory):
            ran = gate.run_suite(self.repo(), pattern="test_holds")
            record = run_gnomon_task(self.lane, "Who asked?", role="analyst")
        self.assertEqual((ran["tests"], record["output"]), ({"test_holds": "ok"}, "an answer"))
        self.assertEqual(self.gnomon_calls()[-1]["argv"][0], "unconfined")


class CockpitRefusesTest(EnforcedCockpitCase):
    """FR-ID2-AC-1: the cockpit refuses to start a run or a new project's intake without a runner."""

    def test_FR_ID2_AC_1_the_cockpit_refuses_to_start_untrusted_work_and_says_why(self):
        p = self.new()
        doc = access_doc()
        doc.pop("isolation")
        self.enforce(doc)
        self.sign_in(AINO)
        projects, started = len(self.factory.projects()), len(self.runner.started)
        status, out = self.pcall("POST", "/api/projects", {"title": "Parking permits", "persona": "business_owner",
                                                           "source": "People need parking permits."})
        self.assertEqual(status, 403, out)
        self.assertIn("names no isolation runner", out["error"])
        status, out = self.pcall("POST", f"/api/projects/{p.pid}/advance", {"persona": "product_owner"})
        self.assertEqual(status, 403, out)
        self.assertIn("a Gnomon cell does not run", out["error"])
        self.assertEqual((len(self.factory.projects()), len(self.runner.started)), (projects, started))
        status, meta = self.pcall("GET", "/api/meta")
        self.assertIn("No isolation runner: the gate's test runs, local products and Gnomon cells are refused",
                      meta["access"]["detail"])
        self.enforce()                                                         # IT names a runner: it starts
        status, out = self.pcall("POST", f"/api/projects/{p.pid}/advance", {"persona": "product_owner"})
        self.assertEqual(status, 202, out)
        self.assertEqual(len(self.runner.started), started + 1)


class ContainerTest(IsolationCase):
    """FR-ID2-AC-2: a container runner: the suite in a closed container, products on a docker road, cells as told."""

    def container(self, **more) -> None:
        self.runner(runner="container", image="python:3.12-slim", docker_cli=[sys.executable, str(self.docker)],
                    **more)

    def test_FR_ID2_AC_2_the_suite_runs_in_a_closed_container_and_its_outcomes_come_back(self):
        self.container()
        repo = self.repo()
        with isolation.serving(self.factory):
            ran = gate.run_suite(repo, pattern="test_holds")
            both = gate.run_suite(repo, pattern="test_b")
        self.assertEqual((ran["exit"], ran["tests"]), (0, {"test_holds": "ok"}))
        self.assertEqual((both["exit"], both["tests"]), (1, {"test_breaks": "FAIL"}))
        self.assertTrue(self.marker.exists())
        argv = self.docker_calls()[0]
        flags = " ".join(argv[:argv.index("python:3.12-slim")])
        for closed in ("run --rm", "--network none", "--cap-drop ALL", "--security-opt no-new-privileges",
                       "--read-only", "--tmpfs /tmp", f"src={repo.resolve()},dst=/work,readonly", "--workdir /work",
                       "--env DATA_DIR=/gate/data"):
            self.assertIn(closed, flags)
        self.assertEqual(argv[argv.index("python:3.12-slim") + 1:][:2], ["python3", "-c"])
        self.assertIn("/gate/outcomes.json", argv)
        mount = next(a for a in argv if a.endswith(",dst=/gate"))           # the one writable folder
        self.assertFalse(Path(mount.split(",")[1].removeprefix("src=")).exists())   # gone after the run

    def test_FR_ID2_AC_2_a_container_that_outlives_the_gates_time_is_removed(self):
        self.container()
        with isolation.serving(self.factory):
            ran = gate.run_suite(self.repo(wait=4), pattern="test_waits", timeout=1)
        self.assertEqual(ran["exit"], None)
        calls = self.docker_calls()
        name = calls[0][calls[0].index("--name") + 1]
        self.assertTrue(name.startswith("rihmasto-gate-"))
        self.assertEqual(calls[-1], ["rm", "-f", name])

    def test_FR_ID2_AC_2_products_take_a_docker_road_and_cells_run_as_isolation_cells_says(self):
        self.container()
        project = self.new()
        road = LocalProcessRoad("local-preview", BUILTIN_ROADS["local-preview"])
        with isolation.serving(self.factory):
            with self.assertRaises(isolation.IsolationRequired) as ctx:
                road.deploy(project, self.package())
            self.assertIn("a product runs on a docker road and never on the local road", str(ctx.exception))
            with self.assertRaises(isolation.IsolationRequired) as ctx:
                run_gnomon_task(self.lane, "Who asked?", role="analyst")
            self.assertIn("isolation.cells", str(ctx.exception))
        self.assertFalse(self.marker.exists())
        self.container(cells=[sys.executable, str(self.gnomon), "in-a-container", "--volume", "{cwd}:{cwd}"])
        with isolation.serving(self.factory):
            record = run_gnomon_task(self.lane, "Who asked?", role="analyst")
        self.assertEqual(record["output"], "an answer")
        call = self.gnomon_calls()[-1]
        self.assertEqual(call["argv"][:3], ["in-a-container", "--volume", f"{self.lane}:{self.lane}"])
        self.assertEqual(call["argv"][3:5], ["task", "--task-file"])
        self.assertNotIn("unconfined", call["argv"])                       # $GNOMON_CMD is not used


class SeparateAccountTest(IsolationCase):
    """FR-ID2-AC-3: a separate operating-system account, through sudo, and a strict runner in the file."""

    def test_FR_ID2_AC_3_a_separate_account_runs_each_kind_of_work_through_sudo(self):
        self.runner(runner="os_account", account="rihmasto-run", python="/usr/bin/python3")
        repo = self.repo()
        cmd = [sys.executable, "-c", "the runner", "/tmp/report.json", "test_x"]
        with isolation.serving(self.factory), mock.patch.object(isolation, "SUDO_WORKS", True):
            with isolation.suite(cmd, repo_dir=repo, env=dict(os.environ), report=Path("unused")) as run:
                scratch = run.report.parent
                self.assertEqual(run.argv[:6], ["sudo", "-n", "-u", "rihmasto-run", "--", "env"])
                self.assertIn(f"DATA_DIR={scratch / 'data'}", run.argv)
                self.assertEqual(run.argv[-5:], ["/usr/bin/python3", "-c", "the runner", str(run.report), "test_x"])
            self.assertFalse(scratch.exists())                                # removed afterwards
            env = {"HOST": "127.0.0.1", "PORT": "8080", "DATA_DIR": str(self.tmp / "d"), "API_TOKEN": "not passed"}
            product = isolation.product([sys.executable, *LAUNCH], env, writable=(self.tmp / "d",),
                                        files=(self.tmp / "t.jsonl",))
            self.assertEqual(product[:6], ["sudo", "-n", "-u", "rihmasto-run", "--", "env"])
            self.assertEqual(product[6:9], ["HOST=127.0.0.1", "PORT=8080", f"DATA_DIR={self.tmp / 'd'}"])
            self.assertEqual(product[9:], ["/usr/bin/python3", *LAUNCH])
            self.assertNotIn("API_TOKEN=not passed", product)
            self.assertTrue((self.tmp / "t.jsonl").exists())
            cell = isolation.cell(["gnomon"], self.lane)
            self.assertEqual(cell, ["sudo", "-n", "-u", "rihmasto-run", "--", "gnomon"])

    def test_FR_ID2_AC_3_the_access_file_checks_the_runner_strictly(self):
        good = access_doc()
        self.assertEqual(parse(json.dumps(good).encode()).isolation.kind, "container")
        broken = {
            "$.isolation.runner": {"runner": "chroot"},
            "$.isolation.image": {"runner": "container"},
            "$.isolation.account": {"runner": "os_account"},
            "$.isolation.docker_cli": {"runner": "os_account", "account": "rihmasto-run", "docker_cli": "docker"},
            "$.isolation.cells": {"runner": "container", "image": "python:3.12-slim", "cells": []},
            "$.isolation.extra": {"runner": "container", "image": "python:3.12-slim", "extra": 1},
        }
        for where, isolated in broken.items():
            with self.assertRaises(AccessFileError, msg=where) as ctx:
                parse(json.dumps(dict(good, isolation=isolated)).encode())
            self.assertTrue(str(ctx.exception).startswith(where), (where, str(ctx.exception)))
        with self.assertRaises(AccessFileError):
            parse(json.dumps({"schema": "rihmasto.access/1", "mode": "single_operator",
                              "isolation": {"runner": "container", "image": "python:3.12-slim"}}).encode())


if __name__ == "__main__":
    unittest.main()
