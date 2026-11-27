"""Ask Rihma about teams, the words a team or a project gives Rihmasto's terms and where a setting is set (FR-TM1,
FR-TM2, FR-TM3): answered by rule and without a model, a change only proposed and confirmed signed. Invented fixtures."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_view_fixture import every_kind  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import team as kteam  # noqa: E402
from kernel import teams, vocab, vocab_edit  # noqa: E402
from kernel.assistant import ask  # noqa: E402

IT = {"person": "Aino Example", "persona": "it"}


class TeamsChatTest(CockpitTestCase):
    def setUp(self):
        super().setUp()
        kteam.name_solo(self.factory, "Aino Example")
        self.p = every_kind(self)

    def ask(self, question, *, project=True, persona="it"):
        return ask(self.factory, question, persona=persona, project_id=self.p.pid if project else None)

    def test_FR_TM1_AC_10_ask_rihma_says_which_team_a_project_is_in_and_who_is_in_my_team(self):
        out = self.ask("Which team is this project in?")
        self.assertEqual(out["by"], "rule")
        self.assertIn("Aino Example", out["answer"])
        self.assertIn("nothing to set up", out["answer"])                  # a person working alone is told so
        who = self.ask("Who is in my team?", project=False)
        self.assertIn("Aino Example", who["answer"])
        self.assertEqual(who["navigate"]["control"], "teams_page")

    def test_FR_TM1_AC_10_ask_rihma_proposes_a_move_and_a_new_team_and_the_person_confirms_them_signed(self):
        made = self.ask("Create a team called Platform")
        self.assertEqual(made["propose"][0]["action"], "team_create")
        status, out, _ = self.call("POST", "/api/teams", {**made["propose"][0]["args"], **IT})
        self.assertEqual(status, 200, out)
        moved = self.ask("Move this project to the platform team because they run it")
        prop = moved["propose"][0]
        self.assertEqual((prop["action"], prop["args"]["team"]), ("team_move", out["team"]["id"]))
        self.assertIn("they run it", prop["args"]["reason"])
        self.assertEqual(teams.team_of(self.factory, self.p), teams.AUTO_ID)         # a proposal writes nothing
        status, out, _ = self.call("POST", f"/api/projects/{self.p.pid}/team",
                                   {"team": prop["args"]["team"], "reason": prop["args"]["reason"], **IT})
        self.assertEqual(status, 200, out)
        self.assertEqual(teams.team_of(self.factory, self.p), prop["args"]["team"])
        again = self.ask("Which team is this project in?")
        self.assertIn("Platform", again["answer"])
        unknown = self.ask("Move this project to the robots team")
        self.assertEqual(unknown["propose"], [])
        self.assertIn("no team", unknown["answer"])
        denied = self.ask("Move this project to the team Platform", persona="developer")
        self.assertEqual(denied["propose"], [])

    def test_FR_TM2_AC_10_ask_rihma_proposes_a_new_word_for_a_term_and_finds_it_by_that_word(self):
        out = self.ask("Call a requirement a story because our board says story")
        prop = out["propose"][0]
        self.assertEqual((prop["action"], prop["args"]["term"], prop["args"]["label"]),
                         ("vocab_set", "kind:requirement", "Story"))
        self.assertIn("our board says story", prop["args"]["reason"])
        self.assertEqual(vocab.read_layer(self.factory, "team", teams.AUTO_ID), {})   # a proposal writes nothing
        status, saved, _ = self.call("PUT", f"/api/teams/{prop['args']['team']}/vocabulary", {**prop["args"], **IT})
        self.assertEqual((status, saved["saved"]), (200, True), saved)
        found = self.ask("Where are the stories?")                    # the map knows the shipped word only
        self.assertEqual(found["by"], "rule")
        self.assertIn("Story", found["answer"])
        self.assertTrue(found["navigate"])                            # the map found where requirements are, by "stories"
        shown = self.ask("What do we call a requirement?")
        self.assertIn("Story", shown["answer"])
        self.assertIn("this team", shown["answer"])
        undo = self.ask("Undo the last change of words")
        self.assertEqual(undo["propose"][0]["action"], "vocab_undo")
        scoped = self.ask("Say check instead of criterion in this project")
        self.assertEqual(scoped["propose"][0]["args"].get("project"), self.p.pid)
        hide = self.ask("Hide the comment term")
        self.assertEqual(hide["propose"][0]["args"]["hidden"], True)
        syn = self.ask("Add the synonym brief for request")
        self.assertIn("brief", syn["propose"][0]["args"]["synonyms"])
        custom = self.ask("Add a term brief that means request")
        self.assertEqual((custom["propose"][0]["args"]["label"], custom["propose"][0]["args"]["means"]),
                         ("Brief", "kind:request"))
        status, made, _ = self.call("PUT", f"/api/teams/{custom['propose'][0]['args']['team']}/vocabulary",
                                    {**custom["propose"][0]["args"], **IT})
        self.assertEqual(status, 200, made)
        self.assertEqual(vocab.effective(self.factory, self.p)["terms"]["custom:brief"]["means"], "kind:request")

    def test_FR_TM2_AC_10_a_word_a_persona_may_not_change_is_not_proposed(self):
        out = self.ask("Call a requirement a story", persona="developer")
        self.assertEqual(out["propose"], [])
        self.assertIn("IT changes", out["answer"])
        self.assertEqual(vocab_edit.history(self.factory, "team", teams.AUTO_ID), [])

    def test_FR_TM3_AC_4_ask_rihma_answers_where_a_setting_is_set_by_rule(self):
        out = self.ask("Where is the enforcement level set?")
        self.assertEqual(out["by"], "rule")
        self.assertIn("shipped default", out["answer"].lower())
        self.assertIn("this project", out["answer"].lower())
        self.assertTrue(out["navigate"]["route"].startswith("#/p/"))
        every = self.ask("What applies where?", project=False)
        self.assertIn("Set per project", every["answer"])
        self.assertEqual(every["navigate"]["control"], "scope_view")


if __name__ == "__main__":
    unittest.main()
