"""`rihmasto teams`, `rihmasto vocab` and `rihmasto scope` (FR-TM1, FR-TM2, FR-TM3): the same teams, words and scope as
the cockpit, each write signed and in the ledger, a refusal one line on stderr and exit 2. Invented fixtures."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from kernel import teams, vocab  # noqa: E402
from kernel.cli import main  # noqa: E402

IT = ["--person", "Aino Example", "--persona", "it"]


class TeamsCliTest(FactoryTestCase):
    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()

    def ok(self, *argv):
        code, out, err = self.cli(*argv)
        self.assertEqual((code, err), (0, ""), argv)
        return json.loads(out)

    def test_FR_TM1_AC_11_the_command_line_lists_makes_moves_and_undoes_teams_signed(self):
        p = self.factory.new_project("Loans")
        self.assertEqual([t["id"] for t in self.ok("teams", "list")["teams"]], [teams.AUTO_ID])
        self.assertEqual(self.ok("teams", "which", p.pid)["team"]["id"], teams.AUTO_ID)
        made = self.ok("teams", "create", "Platform", "--member", "Cleo Example", *IT)
        tid = made["team"]["id"]
        self.ok("teams", "set", tid, "--add", "Dee Example", *IT)
        self.assertEqual(teams.read(self.factory, tid)["members"], ["Cleo Example", "Dee Example"])
        self.ok("teams", "move", p.pid, tid, "--reason", "they run it", *IT)
        self.assertEqual(self.ok("teams", "which", p.pid)["team"]["name"], "Platform")
        self.ok("teams", "undo", "--project", p.pid, *IT)
        self.assertEqual(self.ok("teams", "which", p.pid)["team"]["id"], teams.AUTO_ID)
        kinds = {r["event"]["kind"] for r in self.factory.project("_factory").ledger().records()}
        self.assertIn("team_set", kinds)
        code, out, err = self.cli("teams", "create", "Robots", "--person", "Aino Example", "--persona", "developer")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("developer may not define a team", err)
        code, out, err = self.cli("teams", "move", p.pid, "no-such-team", *IT)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no team", err)

    def test_FR_TM2_AC_11_the_command_line_shows_previews_sets_and_undoes_words(self):
        p = self.factory.new_project("Loans")
        shown = self.ok("vocab", "show", "--project", p.pid)
        self.assertEqual(shown["terms"], "every term reads as shipped")
        seen = self.ok("vocab", "preview", "--project", p.pid, "--term", "kind:task", "--label", "Job")
        self.assertEqual(seen["after"]["label"], "Job")
        self.assertEqual(vocab.read_layer(self.factory, "project", p.pid), {})        # a preview records nothing
        self.ok("vocab", "set", "--project", p.pid, "--term", "kind:task", "--label", "Job", "--reason", "our word", *IT)
        self.ok("vocab", "set", "--team", teams.AUTO_ID, "--term", "kind:request", "--synonym", "brief", *IT)
        row = self.ok("vocab", "show", "--project", p.pid)["terms"]
        self.assertEqual({r["id"]: r["scope"] for r in row}, {"kind:task": "project", "kind:request": "team"})
        self.ok("vocab", "undo", "--project", p.pid, *IT)
        self.assertEqual(vocab.read_layer(self.factory, "project", p.pid), {})
        code, out, err = self.cli("vocab", "set", "--team", teams.AUTO_ID, "--term", "kind:task", "--label", "Job",
                                  "--person", "Pia Example", "--persona", "product_owner")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("may not change a team's words", err)

    def test_FR_TM3_AC_6_the_command_line_shows_what_applies_where(self):
        p = self.factory.new_project("Loans")
        out = self.ok("scope", "show", "--project", p.pid)
        self.assertEqual(out["project"], p.pid)
        rows = {r["id"]: r for r in out["rows"]}
        self.assertEqual(rows["structure"]["source"], "default")
        self.assertIn("vocabulary", rows)
        self.assertEqual(self.ok("scope", "show")["project"], None)


if __name__ == "__main__":
    unittest.main()
