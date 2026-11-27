"""What Rihmasto understood of an adopted project, by rule, read as each persona; and a single operator's
session that outlives a restart of the cockpit (the owner, 2026-11-25)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_assess import fixture_repo, mirrored, no_scanner  # noqa: E402

from kernel import assess, understanding  # noqa: E402
from kernel.assistant import ask  # noqa: E402


class UnderstandingTest(FactoryTestCase):
    def test_FR_RPJ1_AC_1_an_adopted_project_says_what_it_understood_and_reads_as_each_persona(self):
        project = mirrored(self.factory, "Orders", fixture_repo("poor", self.tmp / "src"))
        project.write("inventory.json", {"languages": [{"language": "Python", "files": 3}],
                                         "readme": {"file": "README.md", "first_paragraph": "Takes orders from shops."},
                                         "test_command": {"detected": False}, "dockerfile": {"present": False},
                                         "endpoints": {"scanned": False}})
        u = understanding.take(project)
        self.assertEqual(u["what"], "Takes orders from shops.")
        self.assertIn("README.md", u["said_by"])
        self.assertTrue(any("tests" in g for g in u["not_understood"]))
        assess.assess(project, person="Aino", persona="developer", which=no_scanner)
        u = understanding.take(project)
        lenses = understanding.lenses(project, u)
        self.assertEqual(set(lenses), {"developer", "compliance", "business"})
        self.assertTrue(lenses["compliance"]["assessed"])
        self.assertTrue(lenses["compliance"]["security"] or lenses["compliance"]["compliance"])
        out = ask(self.factory, "What is this project?", persona="business_owner", project_id=project.pid)
        self.assertEqual(out["by"], "rule")
        self.assertIn("Takes orders from shops.", out["answer"])

    def test_FR_RPJ1_AC_1_a_project_that_was_not_adopted_has_no_understanding_card(self):
        project = mirrored(self.factory, "Orders", fixture_repo("poor", self.tmp / "src"))
        Path(project.path("inventory.json")).unlink(missing_ok=True)
        self.assertIsNone(understanding.take(project))


class SessionAfterRestartTest(FactoryTestCase):
    def test_FR_T1_AC_1_a_single_operators_session_outlives_a_restart_and_only_its_hash_is_kept(self):
        from cockpit.server import make_server

        first, link = make_server(self.factory, port=0)
        try:
            token = first.redeem(link)
        finally:
            first.server_close()
        kept = json.loads((self.factory.home / "_cockpit" / "sessions.json").read_text(encoding="utf-8"))
        self.assertNotIn(token, json.dumps(kept))               # the token itself is never written
        second, _ = make_server(self.factory, port=0)
        try:
            self.assertTrue(second.session_ok(token))
            self.assertFalse(second.session_ok("not-a-session"))
        finally:
            second.server_close()


if __name__ == "__main__":
    unittest.main()
