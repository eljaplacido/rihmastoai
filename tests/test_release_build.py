"""FR-REL1: a release is built from a version tag that matches the declared version, with source
archives, a CycloneDX SBOM, checksums and notes from CHANGELOG.md; the workflow tests first, publishes
only on a pushed tag, and only its publishing job may write."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import release_build as rb  # noqa: E402

PYPROJECT = """[project]
name = "rihmasto"
version = "{version}"
description = "A governed AI solution factory."
license = "Apache-2.0"
requires-python = ">=3.11"
dependencies = []
"""
CHANGELOG = """# Changelog

## [Unreleased]

### Added

- Something not yet released.

## [1.2.0] - 2026-11-24

### Added

- The first thing.
- The second thing.

## [1.1.0] - 2026-10-01

- Older.
"""


class ReleaseBuildTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()
        self.addCleanup(self._tmp.cleanup)

    def repo(self, version: str = "1.2.0") -> Path:
        (self.root / "pyproject.toml").write_text(PYPROJECT.format(version=version), encoding="utf-8")
        (self.root / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
        (self.root / "kernel").mkdir(exist_ok=True)
        (self.root / "kernel" / "a.py").write_text("print('a')\n", encoding="utf-8")
        (self.root / "untracked.txt").write_text("never shipped\n", encoding="utf-8")
        for cmd in (["init", "-q"], ["add", "pyproject.toml", "CHANGELOG.md", "kernel"],
                    ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "x"]):
            subprocess.run(["git", *cmd], cwd=self.root, check=True, capture_output=True)
        return self.root

    def test_FR_REL1_AC_1_a_tag_that_does_not_match_the_declared_version_builds_nothing(self):
        root = self.repo("1.2.0")
        out = Path(self._tmp.name) / "dist"
        for tag, why in (("v1.3.0", "does not match"), ("1.2.0", "needs a tag"), ("vnext", "not a version"),
                         (None, "needs a tag")):
            with self.subTest(tag=tag), self.assertRaisesRegex(rb.ReleaseRefused, why):
                rb.build(out, tag=tag, root=root)
        self.assertFalse(out.exists())
        self.repo("1.4.0")                                  # declared, but CHANGELOG has no [1.4.0]
        with self.assertRaisesRegex(rb.ReleaseRefused, r"no section ## \[1.4.0\]"):
            rb.build(out, tag="v1.4.0", root=root)

    def test_FR_REL1_AC_2_a_release_holds_the_archives_an_sbom_checksums_and_its_changelog_section(self):
        root = self.repo("1.2.0")
        out = Path(self._tmp.name) / "dist"
        got = rb.build(out, tag="v1.2.0", root=root)
        self.assertEqual(got["version"], "1.2.0")
        self.assertFalse(got["prerelease"])
        self.assertEqual(got["files"], ["rihmasto-1.2.0.tar.gz", "rihmasto-1.2.0.zip", "rihmasto-1.2.0.cdx.json",
                                        "SHA256SUMS"])
        with tarfile.open(out / "rihmasto-1.2.0.tar.gz") as tar:
            names = tar.getnames()
        self.assertIn("rihmasto-1.2.0/kernel/a.py", names)
        self.assertNotIn("rihmasto-1.2.0/untracked.txt", names)          # only what git tracks ships
        with zipfile.ZipFile(out / "rihmasto-1.2.0.zip") as z:
            self.assertIn("rihmasto-1.2.0/pyproject.toml", z.namelist())
        sums = dict(reversed(line.split("  ")) for line in (out / "SHA256SUMS").read_text().splitlines())
        for name in got["files"][:3]:
            self.assertEqual(sums[name], hashlib.sha256((out / name).read_bytes()).hexdigest(), name)
        bom = json.loads((out / "rihmasto-1.2.0.cdx.json").read_text(encoding="utf-8"))
        self.assertEqual((bom["bomFormat"], bom["specVersion"]), ("CycloneDX", "1.5"))
        comp = bom["metadata"]["component"]
        self.assertEqual((comp["name"], comp["version"], comp["purl"]),
                         ("rihmasto", "1.2.0", "pkg:github/eljaplacido/rihmastoai@v1.2.0"))
        self.assertEqual(comp["licenses"], [{"license": {"id": "Apache-2.0"}}])
        self.assertEqual([c["name"] for c in bom["components"]], ["gnomon"])
        self.assertRegex(bom["serialNumber"], r"^urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-")
        notes = (out / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        self.assertIn("The second thing.", notes)
        self.assertNotIn("not yet released", notes)
        self.assertNotIn("Older.", notes)
        first = {n: (out / n).read_bytes() for n in got["files"]}            # the same commit, the same bytes
        rb.build(out, tag="v1.2.0", root=root)
        self.assertEqual({n: (out / n).read_bytes() for n in got["files"]}, first)

    def test_FR_REL1_AC_3_a_rehearsal_takes_the_declared_version_and_a_pre_release_is_marked(self):
        root = self.repo("1.3.0rc1")
        got = rb.build(Path(self._tmp.name) / "dist", dry_run=True, root=root)
        self.assertEqual((got["version"], got["prerelease"], got["dry_run"]), ("1.3.0rc1", True, True))
        self.assertIn("not yet released", (Path(self._tmp.name) / "dist" / "RELEASE_NOTES.md").read_text())
        for version, pre in (("1.0.0", False), ("1.0.0a1", True), ("1.0.0b2", True), ("1.0.0.dev0", True)):
            self.assertEqual(rb.prerelease(version), pre, version)
        self.assertTrue(rb.VERSION.match(rb.project_version(ROOT)), "pyproject's own version is a release version")

    def test_FR_REL1_AC_4_the_workflow_tests_first_publishes_only_on_a_tag_and_only_publishing_writes(self):
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertNotIn("\r", text)
        self.assertIn('tags: ["v*.*.*"]', text)
        self.assertIn("workflow_dispatch:", text)
        jobs = re.split(r"(?m)^  (?=[a-z]+:\n)", text.split("\njobs:\n", 1)[1])
        jobs = {j.split(":", 1)[0]: j for j in jobs if j.strip()}
        self.assertEqual(list(jobs), ["checks", "build", "publish"])
        top = text.split("\njobs:\n", 1)[0]
        self.assertIn("permissions:\n  contents: read", top)                 # read only unless a job says more
        self.assertNotIn("permissions", jobs["checks"])
        self.assertIn("python -m unittest discover -s tests", jobs["checks"])
        self.assertIn("contract_check.py", jobs["checks"])
        self.assertIn("needs: checks", jobs["build"])
        self.assertNotIn("contents: write", jobs["build"])
        self.assertIn("if: github.event_name == 'push'\n        uses: actions/attest-build-provenance", jobs["build"])
        self.assertIn("--dry-run", jobs["build"])
        self.assertIn("needs: build\n    if: github.event_name == 'push'", jobs["publish"])
        self.assertIn("contents: write", jobs["publish"])
        self.assertIn("--verify-tag", jobs["publish"])
        for name, job in jobs.items():                                       # no expression inside a script
            for block in re.findall(r"run: \|\n((?:          .*\n?)+)", job):
                self.assertNotIn("${{", block, name)
            self.assertNotIn("persist-credentials: true", job)


if __name__ == "__main__":
    unittest.main()
