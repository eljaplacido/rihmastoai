"""`rihma doctor` (FR-N2-AC-2): Rihma needs Gnomon 0.6.5 or later; 0.6.6 is recommended."""

import contextlib
import io
import json
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kernel.cli import main
from kernel.doctor import MIN_GNOMON, RECOMMENDED_GNOMON, doctor, gnomon_version, parse_version, version_key

FAKE_GNOMON = 'import os\nprint(os.environ.get("FAKE_GNOMON_VERSION", ""))\n'
ROUTING = {"endpoints": {"go": {"kind": "openai", "url": "https://opencode.ai/zen/go/v1/chat/completions",
                                "api_key_env": "OPENCODE_API_KEY"},
                         "local": {"kind": "openai", "url": "http://127.0.0.1:8080/v1/chat/completions"}}}
SECRET = "sk-" + "test-0123456789-do-not-print"   # built at run time, so no key-shaped literal ships


class DoctorTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="gf-doctor-")
        self.tmp = Path(self._tmp.name)
        self.fake = self.tmp / "fake_gnomon.py"
        self.fake.write_text(FAKE_GNOMON, encoding="utf-8")
        self.cmd = [sys.executable, str(self.fake)]

    def tearDown(self):
        self._tmp.cleanup()

    def run_doctor(self, version, *, environ=None, cmd=None):
        with mock.patch.dict(os.environ, {"FAKE_GNOMON_VERSION": version}):
            return doctor(self.tmp / "home", gnomon=cmd or self.cmd, routing=ROUTING,
                          lanes_root=self.tmp / "lanes", environ=environ or {})

    def test_FR_N2_AC_2_doctor_reports_gnomons_version_and_support_and_never_a_keys_value(self):
        self.assertEqual((MIN_GNOMON, RECOMMENDED_GNOMON), ("0.6.5", "0.6.6"))
        cases = [  # (`gnomon --version`, supported, recommended, exit)
            ("gnomon/0.6.6+v0.6.6-d3c574a", True, True, 0),
            ("gnomon/0.6.5+v0.6.5-53f83bd", True, False, 0),     # this workstation's release
            ("gnomon/0.6.5+fb458ea5", True, False, 0),           # the source build pinned for cells (D-0003)
            ("gnomon/0.6.6-rc.1+abc1234", True, False, 0),        # a pre-release sorts below its release
            ("gnomon/0.7.0+npm", True, True, 0),
            ("gnomon/0.6.4+v0.6.4-1a2b3c4", False, False, 1),     # too old: a hard failure
        ]
        for raw, supported, recommended, code in cases:
            r = self.run_doctor(raw)
            g = r["gnomon"]
            self.assertTrue(g["found"], raw)
            self.assertEqual(g["raw"], raw)
            self.assertEqual((g["supported"], g["is_recommended"], r["exit"]), (supported, recommended, code), raw)
            self.assertEqual(bool(r["problems"]), code == 1, raw)
        self.assertEqual(self.run_doctor("gnomon/0.6.5+fb458ea5")["gnomon"]["build"], "fb458ea5")
        unreadable = self.run_doctor("not a version")
        self.assertEqual((unreadable["gnomon"]["found"], unreadable["exit"]), (True, 1))
        missing = self.run_doctor("", cmd=[str(self.tmp / "no-such-gnomon")])
        self.assertEqual((missing["gnomon"]["found"], missing["exit"]), (False, 1))
        self.assertIn("not found", missing["problems"][0])
        # The rest of the machine: Python, git, docker (optional), the lanes root, the factory home.
        r = self.run_doctor("gnomon/0.6.6+v0.6.6-d3c574a")
        self.assertEqual(r["schema"], "rihma.doctor/1")
        self.assertTrue(r["python"]["ok"])
        self.assertIn("found", r["git"])
        self.assertTrue(r["docker"]["optional"])
        self.assertEqual(r["lanes"], {"root": str(self.tmp / "lanes"), "exists": False, "writable": True,
                                      "created_under": str(self.tmp)})
        self.assertEqual(r["home"], {"path": str(self.tmp / "home"), "exists": False})
        self.assertEqual(list(self.tmp.iterdir()), [self.fake])            # the probe left nothing behind
        # Each endpoint that names a key variable: set or not, never the value.
        with_key = self.run_doctor("gnomon/0.6.6+v0.6.6-d3c574a", environ={"OPENCODE_API_KEY": SECRET})
        self.assertEqual(with_key["endpoints"], [{"name": "go", "api_key_env": "OPENCODE_API_KEY", "set": True}])
        self.assertNotIn(SECRET, json.dumps(with_key))
        self.assertEqual(r["endpoints"], [{"name": "go", "api_key_env": "OPENCODE_API_KEY", "set": False}])

    def test_FR_N2_AC_2_the_doctor_subcommand_prints_json_and_exits_1_on_a_hard_failure(self):
        fake = shlex.join([Path(sys.executable).as_posix(), self.fake.as_posix()])
        for version, code in (("gnomon/0.6.6+v0.6.6-d3c574a", 0), ("gnomon/0.6.3+v0.6.3-0000000", 1)):
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"GNOMON_CMD": fake, "FAKE_GNOMON_VERSION": version,
                                              "OPENCODE_API_KEY": SECRET, "GF_LANES": str(self.tmp / "lanes")}), \
                    contextlib.redirect_stdout(out):
                self.assertEqual(main(["--home", str(self.tmp / "home"), "doctor"]), code, version)
            report = json.loads(out.getvalue())
            self.assertEqual(report["gnomon"]["raw"], version)
            self.assertEqual(report["exit"], code)
            self.assertNotIn(SECRET, out.getvalue())
            self.assertIn({"name": "go", "api_key_env": "OPENCODE_API_KEY", "set": True}, report["endpoints"])

    def test_FR_N2_AC_2_gnomon_version_parses_every_build_form(self):
        self.assertEqual(parse_version("gnomon/0.6.5+v0.6.5-53f83bd"),
                         {"version": "0.6.5", "build": "v0.6.5-53f83bd", "prerelease": None})
        self.assertEqual(parse_version("gnomon/0.6.6+abf40c0-dirty")["build"], "abf40c0-dirty")
        self.assertEqual(parse_version("gnomon/0.6.6")["build"], None)
        self.assertEqual(parse_version("gnomon/0.6.6-rc.1+npm")["version"], "0.6.6-rc.1")
        self.assertIsNone(parse_version("command not found"))
        self.assertLess(version_key("0.6.6-rc.1"), version_key("0.6.6"))
        self.assertLess(version_key("0.6.5"), version_key("0.6.6"))
        self.assertLess(version_key("0.6.9"), version_key("0.6.10"))
        with mock.patch.dict(os.environ, {"FAKE_GNOMON_VERSION": "gnomon/0.6.6+v0.6.6-d3c574a"}):
            g = gnomon_version(self.cmd)
        self.assertEqual((g["found"], g["version"], g["build"]), (True, "0.6.6", "v0.6.6-d3c574a"))


if __name__ == "__main__":
    unittest.main()
