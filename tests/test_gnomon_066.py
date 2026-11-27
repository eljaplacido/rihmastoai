"""Lanes and the Gnomon command under Gnomon 0.6.6 (docs/gnomon-0.6.6-audit.md)."""

import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from kernel.lanes import (  # noqa: E402
    GNOMON_MACHINE_LOCAL,
    ROUTING_FILE,
    Lane,
    config_toml,
    ensure_analyst_lane,
    load_routing,
)
from kernel.model import ModelError, gnomon_cmd, run_gnomon_task  # noqa: E402


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


class LanesUnder066Test(unittest.TestCase):
    def setUp(self):
        from factory_fakes import no_local_routing

        patcher = no_local_routing()                # the machine's own routing overlay is never read by a test
        patcher.start()
        self.addCleanup(patcher.stop)
        self._tmp = tempfile.TemporaryDirectory(prefix="gf-066-")
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_FR_C2_AC_7_a_lane_keeps_gnomons_machine_local_directories_out_of_the_products_commits(self):
        # MACHINE_LOCAL_DIRS in packages/gnomon-cli/src/init.ts at v0.6.6, which `gnomon init` ignores.
        for d in (".gnomon-inbox/", ".gnomon-proposals/", ".gnomon-out/", ".gnomon-trials/", ".gnomon-skills/",
                  ".gnomon-jobs/", ".gnomon-loops/", ".gnomon-shadow/", ".gnomon-audit/", ".gnomon-sessions/"):
            self.assertIn(d, GNOMON_MACHINE_LOCAL)
        seed = self.tmp / "seed"
        seed.mkdir()
        _git(seed, "init", "-q", "-b", "main")
        (seed / "README.md").write_text("product\n", encoding="utf-8")
        _git(seed, "add", "-A")
        _git(seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed")
        repo = self.tmp / "repo.git"
        _git(self.tmp, "clone", "-q", "--bare", str(seed), str(repo))
        lane = Lane(self.tmp / "lanes" / "lane-1")
        lane.checkout(repo, "cell/T-1")
        for rel in (".gnomon-inbox/20261122T201600456Z-c3d4.json", ".gnomon-proposals/20261122T201500123Z-a1b2.json",
                    ".gnomon-out/task-1/bash-1.txt", ".gnomon-trials/_eval/r/report.json", "app.py"):
            path = lane.path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x\n", encoding="utf-8")
        self.assertEqual(lane.changed(), ["app.py"])
        lane.commit_all("T-1 round 0")
        committed = _git(lane.path, "show", "--name-only", "--format=", "HEAD").split()
        self.assertEqual(committed, ["app.py"])
        analyst = ensure_analyst_lane(load_routing(), root=self.tmp / "lanes")
        ignored = (analyst / ".gitignore").read_text(encoding="utf-8").splitlines()
        for d in GNOMON_MACHINE_LOCAL:
            self.assertIn(d, ignored)

    def test_FR_C2_AC_7_an_endpoints_own_window_compiles_to_its_block_and_defaults_stays_the_fallback(self):
        routing = load_routing(ROUTING_FILE)                     # the shipped routing, whatever this machine overlays
        plain = tomllib.loads(config_toml(routing, ["analyst", "assistant"]))
        self.assertEqual(plain["defaults"]["max_context_tokens"], routing["max_context_tokens"])
        for ep in plain["endpoints"].values():                   # nothing declared: Gnomon asks each endpoint
            self.assertNotIn("max_context_tokens", ep)
        capped = dict(routing, endpoints={**routing["endpoints"],
                                          "local": {**routing["endpoints"]["local"], "max_context_tokens": 98304},
                                          "go": {**routing["endpoints"]["go"], "max_context_tokens": "auto"}})
        compiled = tomllib.loads(config_toml(capped, ["analyst", "assistant"]))
        self.assertEqual(compiled["endpoints"]["local"]["max_context_tokens"], 98304)
        self.assertEqual(compiled["endpoints"]["go"]["max_context_tokens"], "auto")
        self.assertEqual(compiled["defaults"]["max_context_tokens"], routing["max_context_tokens"])
        for bad in (0, -1, "big", True, 1.5):
            wrong = dict(routing, endpoints={**routing["endpoints"],
                                             "local": {**routing["endpoints"]["local"], "max_context_tokens": bad}})
            with self.assertRaises(ValueError, msg=bad):
                config_toml(wrong, ["analyst", "assistant"])


class GnomonCommandTest(unittest.TestCase):
    def setUp(self):
        from factory_fakes import no_local_routing

        patcher = no_local_routing()                # the machine's own routing overlay is never read by a test
        patcher.start()
        self.addCleanup(patcher.stop)
        self._tmp = tempfile.TemporaryDirectory(prefix="gf-066-")
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_FR_C6_AC_2_gnomon_is_found_as_the_shell_finds_it_and_one_that_cannot_start_is_an_apparatus_failure(self):
        env = {k: v for k, v in os.environ.items() if k != "GNOMON_CMD"}
        shim = str(self.tmp / "npm" / "gnomon.CMD")          # npm's Windows shim: a bare "gnomon" does not start
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("pathlib.Path.home", return_value=self.tmp), \
                mock.patch("shutil.which", side_effect=lambda name: shim if name == "gnomon" else None):
            self.assertEqual(gnomon_cmd(), [shim])
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("pathlib.Path.home", return_value=self.tmp), \
                mock.patch("shutil.which", return_value=None):
            self.assertEqual(gnomon_cmd(), ["gnomon"])
        missing = (self.tmp / "no-such-gnomon").as_posix()
        with mock.patch.dict(os.environ, {"GNOMON_CMD": missing}):
            with self.assertRaises(ModelError) as caught:
                run_gnomon_task(self.tmp / "lane", "hello", role="analyst", timeout=30)
        self.assertIn("could not be started", str(caught.exception))
        self.assertEqual(list((self.tmp / "lane" / ".factory-tasks").iterdir()), [])  # the task file is removed


if __name__ == "__main__":
    unittest.main()
