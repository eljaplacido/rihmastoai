"""Teams stay whole (FR-TM5): a team that holds projects or words is not undone out from under them, names are unique
and made of something, a person of the home is not removed by a team, Rihmasto's own records are in no team, a preview
asks for the same role as the change, and a move says which words change. Invented fixtures."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import team as kteam  # noqa: E402
from kernel import teams, vocab, vocab_edit  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.store import write_json  # noqa: E402

IT = {"person": "Aino Example", "persona": "it"}
ASK = {"person": "Aino Example", "persona": "it"}


class UndoTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.a = self.factory.new_project("Equipment loans")
        self.tid = teams.create(self.factory, "Platform team", **IT)["team"]["id"]

    def test_FR_TM5_AC_1_undoing_a_team_that_holds_a_project_is_refused_and_says_which(self):
        teams.move_project(self.factory, self.a, self.tid, **IT)
        with self.assertRaises(ValueError) as caught:
            teams.undo(self.factory, team=self.tid, **IT)
        self.assertIn("Equipment loans", str(caught.exception))
        self.assertIn("move", str(caught.exception).lower())
        self.assertTrue(teams.exists(self.factory, self.tid))            # nothing was taken away
        self.assertEqual(teams.team_of(self.factory, self.a), self.tid)
        teams.undo(self.factory, project=self.a, **IT)                    # the project goes back, then the team may go
        teams.undo(self.factory, team=self.tid, **IT)
        self.assertFalse(teams.exists(self.factory, self.tid))

    def test_FR_TM5_AC_2_undoing_a_team_that_has_words_of_its_own_is_refused_until_they_are_given_back(self):
        vocab_edit.set_term(self.factory, "team", self.tid, term="kind:task", fields={"label": "Job"}, **IT)
        with self.assertRaises(ValueError) as caught:
            teams.undo(self.factory, team=self.tid, **IT)
        self.assertIn("words", str(caught.exception))
        self.assertTrue(teams.exists(self.factory, self.tid))
        vocab_edit.undo(self.factory, "team", self.tid, **IT)
        teams.undo(self.factory, team=self.tid, **IT)
        self.assertFalse(vocab.path_of(self.factory, "team", self.tid).exists())

    def test_FR_TM5_AC_3_a_new_team_never_takes_over_an_old_teams_words_or_projects(self):
        ghost = vocab.path_of(self.factory, "team", "team-ghost")          # words an older removal left behind
        write_json(ghost, {"schema": vocab.SCHEMA, "terms": {"kind:task": {"label": "Job"}}})
        self.a.update_meta(team="team-ghost")                                 # and a project that still names it
        made = teams.create(self.factory, "Ghost", **IT)["team"]["id"]
        self.assertNotEqual(made, "team-ghost")
        self.assertEqual(vocab.label(vocab.effective(self.factory, None, made), "kind:task"), "Task")
        self.assertEqual(teams.projects_of(self.factory, made), [])
        self.assertEqual(teams.team_of(self.factory, self.a), teams.AUTO_ID)


class NamesTest(FactoryTestCase):
    def test_FR_TM5_AC_4_team_names_are_unique_whatever_the_case_or_spacing(self):
        teams.create(self.factory, "Zed", **IT)
        for again in ("Zed", "zed", "  ZED  ", "ZeD"):
            with self.assertRaises(ValueError, msg=again) as caught:
                teams.create(self.factory, again, **IT)
            self.assertIn("already", str(caught.exception))
        other = teams.create(self.factory, "Ops", **IT)["team"]["id"]
        with self.assertRaises(ValueError):
            teams.update(self.factory, other, name="zed", **IT)             # a rename may not collide either
        teams.update(self.factory, other, name="OPS", **IT)                  # its own name in another case is fine
        self.assertEqual(teams.read(self.factory, other)["name"], "OPS")
        self.assertEqual(len([t for t in teams.all_teams(self.factory) if t["name"].lower() == "zed"]), 1)

    def test_FR_TM5_AC_5_a_name_holds_a_letter_or_a_digit_and_is_not_another_teams_id(self):
        for bad in (".", "---", "  ", "<>", "team-solo"):
            with self.assertRaises(ValueError, msg=bad):
                teams.create(self.factory, bad, **IT)
        teams.create(self.factory, "Platform", **IT)
        with self.assertRaises(ValueError):
            teams.create(self.factory, "team-platform", **IT)               # that is the first team's own id

    def test_FR_TM5_AC_6_names_without_plain_letters_get_distinct_ids_not_team_project(self):
        a = teams.create(self.factory, "é ü", **IT)["team"]["id"]
        b = teams.create(self.factory, "ö ä", **IT)["team"]["id"]
        c = teams.create(self.factory, "数据", **IT)["team"]["id"]
        self.assertEqual(len({a, b, c}), 3)
        for tid in (a, b, c):
            self.assertNotIn("project", tid)
            self.assertTrue(tid.startswith("team-"))
        self.assertEqual(teams.create(self.factory, "Zürich", **IT)["team"]["id"], "team-zurich")   # accents fold


class MembersTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        kteam.name_solo(self.factory, "Aino Example")

    def test_FR_TM5_AC_7_members_that_are_not_a_list_of_names_are_refused_not_a_crash(self):
        for bad in (5, {"a": 1}, 1.5, True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                teams.create(self.factory, "Platform" + str(bad)[:3], members_=bad, **IT)
        tid = teams.create(self.factory, "Platform", **IT)["team"]["id"]
        with self.assertRaises(ValueError):
            teams.update(self.factory, tid, add=5, **IT)

    def test_FR_TM5_AC_8_a_person_of_the_home_is_not_removed_by_a_team_and_it_says_where_to(self):
        with self.assertRaises(ValueError) as caught:
            teams.update(self.factory, teams.AUTO_ID, remove=["Aino Example"], **IT)
        self.assertIn("People", str(caught.exception))
        self.assertIn("Aino Example", str(caught.exception))
        out = teams.update(self.factory, teams.AUTO_ID, remove=["Nobody Example"], **IT)    # not in it: nothing to say
        self.assertEqual(out["lines"], ["Nothing changes."])

    def test_FR_TM5_AC_9_after_the_switch_to_team_mode_the_automatic_team_is_not_named_after_one_person(self):
        self.assertEqual(teams.read(self.factory, teams.AUTO_ID)["name"], "Aino Example")      # alone: your team
        kteam.set_mode(self.factory, "team", **IT)
        self.assertEqual(teams.read(self.factory, teams.AUTO_ID)["name"], "Our team")
        p = self.factory.new_project("Loans")
        tid = teams.create(self.factory, "Platform", **IT)["team"]["id"]
        teams.move_project(self.factory, p, tid, **IT)
        teams.move_project(self.factory, p, teams.AUTO_ID, **IT)                                 # moving back keeps it
        self.assertEqual(teams.read(self.factory, teams.AUTO_ID)["name"], "Our team")
        teams.update(self.factory, teams.AUTO_ID, name="Everyone", **IT)                         # a person's own name sticks
        self.assertEqual(teams.read(self.factory, teams.AUTO_ID)["name"], "Everyone")
        teams.undo(self.factory, team=teams.AUTO_ID, **IT)                                        # and the rename undoes
        self.assertEqual(teams.read(self.factory, teams.AUTO_ID)["name"], "Our team")


class RoleTest(FactoryTestCase):
    def test_FR_TM5_AC_10_the_refusal_is_in_plain_words_with_the_right_article_and_a_missing_role(self):
        with self.assertRaises(DecisionRefused) as caught:
            teams.create(self.factory, "Platform", person="Mari Example", persona="end_user")
        self.assertIn("an end_user may not define a team", str(caught.exception))
        self.assertIn("only IT may", str(caught.exception))
        with self.assertRaises(DecisionRefused) as caught:
            teams.create(self.factory, "Platform", person="Mari Example", persona="")
        self.assertIn("say which role", str(caught.exception))
        self.assertNotIn("a  may", str(caught.exception))
        with self.assertRaises(DecisionRefused) as caught:
            vocab_edit.check_who("team", "Mari Example", "end_user")
        self.assertIn("an end_user may not change a team's words", str(caught.exception))


class MoveTest(FactoryTestCase):
    def test_FR_TM5_AC_11_a_move_says_which_words_change_and_how_many_records_read_differently(self):
        p = self.factory.new_project("Equipment loans")
        tid = teams.create(self.factory, "Platform", **IT)["team"]["id"]
        vocab_edit.set_term(self.factory, "team", tid, term="kind:task", fields={"label": "Job"}, **IT)
        vocab_edit.set_term(self.factory, "team", tid, term="kind:requirement", fields={"label": "Story"}, **IT)
        seen = teams.preview(self.factory, project=p.pid, to=tid)
        text = " ".join(seen["lines"])
        self.assertIn("Task", text)
        self.assertIn("Job", text)
        self.assertIn("Story", text)
        self.assertIn("read differently", text)
        self.assertEqual({t["term"] for t in seen["words"]}, {"kind:task", "kind:requirement"})
        self.assertIn("records", seen)
        self.assertIn("nodes", seen)
        p.update_meta(team=tid)
        back = teams.preview(self.factory, project=p.pid, to=teams.AUTO_ID)
        self.assertIn("Job", " ".join(back["lines"]))                      # leaving takes the team's words away
        same = teams.preview(self.factory, project=p.pid, to=tid)
        self.assertEqual(same["changes"], [])
        plain = self.factory.new_project("Orders")
        other = teams.create(self.factory, "Ops", **IT)["team"]["id"]       # no words either side: it says so
        self.assertIn("No word changes", " ".join(teams.preview(self.factory, project=plain.pid, to=other)["lines"]))


class RouteTest(CockpitTestCase):
    def test_FR_TM5_AC_12_rihmastos_own_records_are_in_no_team_for_a_read_and_a_move(self):
        self.factory.new_project("Loans")
        tid = teams.create(self.factory, "Platform", **IT)["team"]["id"]
        status, out, _ = self.call("GET", "/api/projects/_factory/team")
        self.assertEqual((status, out["applies"]), (200, False))
        status, out, _ = self.call("POST", "/api/projects/_factory/team", {"team": tid, **ASK})
        self.assertEqual(status, 400, out)
        self.assertIn("no team", out["error"])
        meta = self.factory.projects_dir / "_factory" / "project.json"
        self.assertFalse(meta.exists() and "team" in json.loads(meta.read_text(encoding="utf-8")))

    def test_FR_TM5_AC_13_members_that_are_a_number_are_a_400_not_a_500(self):
        status, out, _ = self.call("POST", "/api/teams", {"name": "Platform", "members": 5, **ASK})
        self.assertEqual(status, 400, out)
        status, out, _ = self.call("POST", "/api/teams", {"name": "Platform", **ASK})
        tid = out["team"]["id"]
        status, out, _ = self.call("PUT", f"/api/teams/{tid}", {"add": 5, **ASK})
        self.assertEqual(status, 400, out)
        status, out, _ = self.call("PUT", f"/api/teams/{tid}", {"name": "Platform", "remove": ["Aino Example"],
                                                                "person": "Aino Example", "persona": "it"})
        self.assertEqual(status, 200, out)

    def test_FR_TM5_AC_14_a_preview_asks_for_the_same_role_as_the_change(self):
        p = self.factory.new_project("Loans")
        tid = teams.create(self.factory, "Platform", **IT)["team"]["id"]
        mari = {"person": "Mari Example", "persona": "end_user"}
        previews = (("/api/teams/preview", {"team": tid, "name": "Platform two"}),
                    ("/api/teams/preview", {"name": "A new team"}),
                    ("/api/teams/preview", {"project": p.pid, "to": tid}),
                    ("/api/vocabulary/preview", {"team": tid, "term": "kind:task", "label": "Job"}),
                    ("/api/vocabulary/preview", {"project": p.pid, "term": "kind:task", "label": "Job"}))
        for path, body in previews:
            status, out, _ = self.call("POST", path, {**body, **mari})
            self.assertEqual(status, 403, (path, body, out))
            self.assertIn("end_user", out["error"])
            status, out, _ = self.call("POST", path, {**body, "person": "Aino Example"})
            self.assertEqual(status, 403, (path, body, out))
            self.assertIn("say which role", out["error"])
            status, out, _ = self.call("POST", path, {**body, **ASK})
            self.assertEqual(status, 200, (path, body, out))
        status, out, _ = self.call("POST", "/api/teams/preview", {"project": p.pid, "to": tid, "person": "Pia Example",
                                                                  "persona": "product_owner"})
        self.assertEqual(status, 200, out)                                   # a project's owner may move it
        status, out, _ = self.call("POST", "/api/teams/preview", {"team": tid, "name": "X", "person": "Pia Example",
                                                                  "persona": "product_owner"})
        self.assertEqual(status, 403, out)                                   # but only IT defines a team


class ChatTest(CockpitTestCase):
    def test_FR_TM5_AC_15_ask_rihma_answers_for_the_team_the_question_names(self):
        from kernel.assistant import ask

        kteam.name_solo(self.factory, "Aino Example")
        p = self.factory.new_project("Equipment loans")
        ops = teams.create(self.factory, "Ops", members_=["Cleo Example", "Dee Example"], **IT)["team"]["id"]
        teams.create(self.factory, "Platform", members_=["Eli Example"], **IT)
        teams.move_project(self.factory, p, ops, **IT)
        for question in ("Who is in the Ops team?", "who is in team ops", "Who is in Ops?"):
            out = ask(self.factory, question, persona="it", project_id=None)
            self.assertEqual(out["by"], "rule", question)
            self.assertIn("Cleo Example", out["answer"], question)
            self.assertIn("Dee Example", out["answer"], question)
            self.assertNotIn("Eli Example", out["answer"], question)
            self.assertIn("Equipment loans", out["answer"], question)
        out = ask(self.factory, "Who is in the Ops team?", persona="it", project_id=p.pid)      # not the project's own
        self.assertIn("Cleo Example", out["answer"])
        out = ask(self.factory, "Who is in the Robots team?", persona="it", project_id=None)
        self.assertIn("no team called", out["answer"])
        self.assertIn("Ops", out["answer"])


if __name__ == "__main__":
    unittest.main()
