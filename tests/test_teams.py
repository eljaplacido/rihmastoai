"""Teams, tied to projects (D-0027, FR-TM1): the automatic team of one, teams IT defines, a project in exactly one
team, a move with a preview, signed, in the ledger and undone exactly. Fixtures are invented."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from kernel import team as kteam  # noqa: E402
from kernel import teams  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.store import write_json  # noqa: E402

IT = {"person": "Aino Example", "persona": "it"}


class TeamsTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.factory.new_project("Loans")

    def test_FR_TM1_AC_1_a_person_working_alone_is_a_team_of_one_made_automatically(self):
        kteam.name_solo(self.factory, "Aino Example")
        d = teams.describe(self.factory)
        self.assertTrue(d["solo"])
        self.assertEqual([t["id"] for t in d["teams"]], [teams.AUTO_ID])
        self.assertEqual(d["teams"][0]["name"], "Aino Example")
        self.assertEqual(d["teams"][0]["members"], ["Aino Example"])
        self.assertEqual(teams.team_of(self.factory, self.p), teams.AUTO_ID)
        self.assertNotIn("unit", d["teams"][0])                   # the empty field is never shown
        self.assertFalse(teams.folder(self.factory).exists())     # reading made nothing

    def test_FR_TM1_AC_2_an_existing_project_is_in_the_automatic_team_and_nothing_is_rewritten(self):
        self.assertNotIn("team", self.p.meta)
        before = (self.p.dir / "project.json").read_bytes()
        teams.describe(self.factory)
        teams.of_project(self.factory, self.p)
        self.assertEqual((self.p.dir / "project.json").read_bytes(), before)

    def test_FR_TM1_AC_3_adding_a_second_person_gives_the_same_team_members_without_a_migration(self):
        kteam.name_solo(self.factory, "Aino Example")
        kteam.set_mode(self.factory, "team", person="Aino Example", persona="it")
        doc = kteam.read(self.factory)             # the second person, as Settings > People adds them
        doc["users"].append({"id": "U-002", "name": "Bea Example", "personas": ["developer"], "scope": "*",
                             "identities": ["rihmasto:U-002"], "active": True})
        write_json(kteam.path(self.factory), doc)
        d = teams.describe(self.factory)
        self.assertEqual([t["id"] for t in d["teams"]], [teams.AUTO_ID])
        self.assertEqual(d["teams"][0]["members"], ["Aino Example", "Bea Example"])
        self.assertFalse(d["solo"])
        self.assertEqual(teams.team_of(self.factory, self.p), teams.AUTO_ID)

    def test_FR_TM1_AC_4_it_makes_a_team_and_moves_a_project_signed_and_undone_exactly(self):
        made = teams.create(self.factory, "Platform", members_=["Cleo Example"], **{"person": "Aino Example",
                                                                                      "persona": "it"})
        tid = made["team"]["id"]
        seen = teams.preview(self.factory, project=self.p.pid, to=tid)
        self.assertIn("moves from", seen["lines"][0])
        self.assertNotIn("team", self.p.meta)                     # a preview records nothing
        teams.move_project(self.factory, self.p, tid, reason="platform owns it", **IT)
        self.assertEqual(self.p.meta["team"], tid)
        self.assertEqual(teams.team_of(self.factory, self.p), tid)
        self.assertEqual([x["id"] for x in teams.describe(self.factory)["teams"][1]["projects"]], [self.p.pid])
        moved = [r["event"]["payload"] for r in self.p.ledger().of_kind(teams.MOVED_KIND)]
        self.assertEqual((moved[-1]["before"], moved[-1]["after"], moved[-1]["by"]),
                         (teams.AUTO_ID, tid, "Aino Example"))
        teams.undo(self.factory, project=self.p, **IT)
        self.assertEqual(teams.team_of(self.factory, self.p), teams.AUTO_ID)
        self.assertEqual(len(self.p.ledger().of_kind(teams.MOVED_KIND)), 2)    # the undo is in the record too
        with self.assertRaises(ValueError):
            teams.undo(self.factory, project=self.p, **IT)       # nothing left to undo

    def test_FR_TM1_AC_5_a_team_change_is_undone_to_the_earlier_record(self):
        tid = teams.create(self.factory, "Platform", **IT)["team"]["id"]
        teams.update(self.factory, tid, name="Platform team", add=["Dee Example"], **IT)
        self.assertEqual(teams.read(self.factory, tid)["members"], ["Dee Example"])
        teams.undo(self.factory, team=tid, **IT)
        doc = teams.read(self.factory, tid)
        self.assertEqual((doc["name"], doc["members"]), ("Platform", []))
        teams.undo(self.factory, team=tid, **IT)                  # undoing the creation takes the team away
        self.assertFalse(teams.exists(self.factory, tid))

    def test_FR_TM1_AC_6_only_it_defines_a_team_and_a_project_owner_may_move_a_project(self):
        with self.assertRaises(DecisionRefused):
            teams.create(self.factory, "Platform", person="Aino Example", persona="developer")
        tid = teams.create(self.factory, "Platform", **IT)["team"]["id"]
        teams.move_project(self.factory, self.p, tid, person="Pia Example", persona="product_owner")
        with self.assertRaises(DecisionRefused):
            teams.move_project(self.factory, self.p, teams.AUTO_ID, person="Dev Example", persona="developer")
        with self.assertRaises(DecisionRefused):
            teams.create(self.factory, "Robot", person="autopilot", persona="it")

    def test_FR_TM1_AC_7_there_is_no_enterprise_level_only_an_empty_unit_field(self):
        tid = teams.create(self.factory, "Platform", **IT)["team"]["id"]
        doc = teams.read(self.factory, tid)
        self.assertEqual(doc["unit"], "")
        text = " ".join(str(k) for k in teams.describe(self.factory)).lower()
        self.assertNotIn("enterprise", text)
        self.assertNotIn("business unit", text)

    def test_FR_TM1_AC_8_a_team_is_found_by_its_words(self):
        teams.create(self.factory, "Platform", **IT)
        self.assertEqual(teams.find(self.factory, "the platform team")["name"], "Platform")
        self.assertIsNone(teams.find(self.factory, "nonsense"))


if __name__ == "__main__":
    unittest.main()
