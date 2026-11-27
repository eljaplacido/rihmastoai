"""What applies where tells the truth (FR-TM4): each surface reads its value source from the store it is kept in, and
a setting that is one document per home is called the home's ("all teams"), never a team's. Invented fixtures."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from kernel import automations, embeds, lanes, observe, scope_table, teams  # noqa: E402
from kernel import gnomon_evals as ge  # noqa: E402
from kernel import gnomon_evals_run as ge_run  # noqa: E402
from kernel import harness_enforcement as he  # noqa: E402
from kernel import structure_policy as sp  # noqa: E402
from kernel.runners import choice  # noqa: E402

IT = {"person": "Aino Example", "persona": "it"}
SITE = "https://loans.example"
NOTE = {"name": "Note it", "trigger": {"kind": "event", "types": ["release_done"]},
        "action": {"kind": "change", "text": "{project} released: check the docs"}}


def row(factory, project, sid):
    return {r["id"]: r for r in scope_table.rows(factory, project)}[sid]


class SourceTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.a = self.factory.new_project("Equipment loans")
        self.b = self.factory.new_project("Orders")

    def test_FR_TM4_AC_1_cell_runners_read_the_real_choice_not_a_fixed_team(self):
        for p in (self.a, self.b, None):
            self.assertEqual((row(self.factory, p, "runners")["source"], row(self.factory, p, "runners")["source_word"]),
                             ("default", "shipped default"))
        choice.propose(self.factory, role="builder", runner="gnomon", scope=self.a.pid, **IT)
        self.assertEqual(row(self.factory, self.a, "runners")["source"], "project")
        self.assertEqual(row(self.factory, self.b, "runners")["source"], "default")
        choice.propose(self.factory, role="verifier", runner="gnomon", **IT)         # the home's own, no project
        self.assertEqual(row(self.factory, self.b, "runners")["source"], "home")
        self.assertEqual(row(self.factory, None, "runners")["source"], "home")
        self.assertEqual(row(self.factory, self.a, "runners")["source"], "project")   # its own still wins

    def test_FR_TM4_AC_2_embeds_links_automations_and_evals_say_none_where_none_was_made(self):
        for sid in ("embeds", "observer", "automations", "evals"):
            r = row(self.factory, self.a, sid)
            self.assertEqual((r["source"], r["source_word"]), ("none", "nothing set here yet"), sid)
            self.assertEqual(row(self.factory, None, sid)["source"], "per_project", sid)   # the team's view: no project
        embeds.create(self.factory, kind="feedback", origins=[SITE], project_id=self.a.pid, **IT)
        observe.create(self.factory, scope="project", project=self.a.pid, hours=1, guest="Gita Guest", **IT)
        automations.add(self.factory, NOTE | {"scope": {"kind": "project", "projects": [self.a.pid]}}, **IT)
        ge_run.record(self.a, ge.find("security"), {"verdict": "passed", "summary": "ok", "scores": {}, "findings": []},
                      via="person", **IT)
        for sid in ("embeds", "observer", "automations", "evals"):
            self.assertEqual(row(self.factory, self.a, sid)["source"], "project", sid)
            self.assertEqual(row(self.factory, self.b, sid)["source"], "none", sid)       # another project: still none
            self.assertEqual(row(self.factory, None, sid)["source"], "per_project", sid)
        self.assertEqual(row(self.factory, self.a, "embeds")["source_word"], "made on this project")

    def test_FR_TM4_AC_3_a_home_wide_embed_link_or_automation_covers_every_project(self):
        embeds.create(self.factory, kind="need", origins=[SITE], **IT)
        observe.create(self.factory, scope="platform", project=None, hours=1, guest="Gita Guest", **IT)
        automations.add(self.factory, NOTE | {"scope": {"kind": "factory"}}, **IT)
        for sid in ("embeds", "observer", "automations"):
            self.assertEqual(row(self.factory, self.b, sid)["source"], "home", sid)
            self.assertEqual(row(self.factory, None, sid)["source"], "home", sid)

    def test_FR_TM4_AC_4_roads_harness_models_people_and_folders_read_their_own_stores(self):
        self.assertEqual({row(self.factory, self.a, s)["source"] for s in ("roads", "harness", "models", "people")},
                         {"default"})
        self.a.update_meta(paved_road="local-process")
        self.assertEqual(row(self.factory, self.a, "roads")["source"], "project")
        self.assertEqual(row(self.factory, self.b, "roads")["source"], "default")
        he.set_enforcement(self.factory, None, on=False, reason="a trial", **IT)
        self.assertEqual(row(self.factory, self.b, "harness")["source"], "home")
        he.set_enforcement(self.factory, self.a, on=True, reason="this one is strict", **IT)
        self.assertEqual(row(self.factory, self.a, "harness")["source"], "project")
        overlay = self.tmp / "routing.local.json"
        overlay.write_text(json.dumps({"roles": {"analyst": {"model": "a-model"}}}), encoding="utf-8")
        with mock.patch.object(lanes, "ROUTING_LOCAL_FILE", overlay):
            self.assertEqual(row(self.factory, self.a, "models")["source"], "home")
        self.assertEqual(row(self.factory, self.a, "models")["source"], "default")       # the isolated, empty overlay
        from kernel import team as kteam

        self.assertEqual(row(self.factory, self.a, "people")["source"], "default")        # working alone
        kteam.name_solo(self.factory, "Aino Example")
        kteam.set_mode(self.factory, "team", **IT)
        self.assertEqual(row(self.factory, self.a, "people")["source"], "home")


class HomeScopeTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.a = self.factory.new_project("Equipment loans")
        self.b = self.factory.new_project("Orders")
        self.platform = teams.create(self.factory, "Platform", **IT)["team"]["id"]
        teams.move_project(self.factory, self.b, self.platform, **IT)

    def test_FR_TM4_AC_5_a_setting_kept_once_per_home_is_called_the_homes_in_every_team(self):
        sp.set_levels(self.factory, None, {"layout": "off"}, reason="our layout", kind="built", **IT)
        for p in (self.a, self.b):                      # both teams share the one document
            r = row(self.factory, p, "structure")
            self.assertEqual((r["source"], r["source_word"]), ("home", "set for all teams"), p.pid)
        for sid in ("structure", "enforcement", "modules", "itops", "harness", "runners", "roads"):
            r = row(self.factory, self.b, sid)
            self.assertNotIn("team", r["scopes"], sid)
            self.assertNotEqual(r["source"], "team", sid)
            self.assertNotIn("This team", r["scope_words"], sid)
            self.assertIn("All teams", r["scope_words"], sid)
        self.assertEqual(row(self.factory, self.b, "vocabulary")["scopes"], ["default", "team", "project"])  # the words are a team's
        self.assertEqual(row(self.factory, None, "structure")["source"], "home")    # the home's own reading, no project
        from kernel import enforcement as ke
        from kernel import modules as km

        self.assertEqual(row(self.factory, None, "enforcement")["source"], "default")
        ke.set_levels(self.factory, None, preset=next(iter(ke.PRESETS)), reason="ours", **IT)
        km.set_modules(self.factory, preset=next(iter(km.PRESETS)), **IT)
        for p in (None, self.a, self.b):
            self.assertEqual(row(self.factory, p, "enforcement")["source"], "home", p and p.pid)
            self.assertEqual(row(self.factory, p, "modules")["source"], "home", p and p.pid)

    def test_FR_TM4_AC_6_a_home_of_one_person_says_all_projects_and_no_team(self):
        from kernel.store import Factory, FixedClock       # a second home, with one team

        home = Factory(self.tmp / "solo-home", clock=FixedClock())
        p = home.new_project("Loans")
        sp.set_levels(home, None, {"layout": "off"}, reason="ours", kind="built", **IT)
        r = row(home, p, "structure")
        self.assertEqual(r["source_word"], "set for all your projects")
        self.assertIn("All projects", r["scope_words"])
        self.assertNotIn("All teams", r["scope_words"])
        d = scope_table.describe(home, p)
        self.assertTrue(d["solo"])
        self.assertEqual(d["scope_words"]["home"], "All projects")
        self.assertFalse(scope_table.describe(self.factory, self.a)["solo"])
        self.assertEqual(scope_table.describe(self.factory, self.a)["scope_words"]["home"], "All teams")

    def test_FR_TM4_AC_7_a_project_in_a_team_is_told_which_team_and_a_project_alone_is_not_told_it_overrides(self):
        r = row(self.factory, self.b, "teams")
        self.assertEqual((r["source"], r["source_word"]), ("project", "this project is in Platform"))
        self.assertEqual(row(self.factory, self.a, "teams")["source"], "default")
        self.assertNotIn("overrides the team", json.dumps(scope_table.describe(self.factory, self.b)))
        self.assertNotIn("overrides the team", json.dumps(scope_table.describe(self.factory, None)))


class SoloTest(FactoryTestCase):
    def test_FR_TM7_AC_2_one_persons_table_says_your_words_not_a_team(self):
        from kernel import vocab_edit

        p = self.factory.new_project("Loans")
        vocab_edit.set_term(self.factory, "team", teams.AUTO_ID, term="kind:task", fields={"label": "Job"}, **IT)
        d = scope_table.describe(self.factory, p)
        self.assertTrue(d["solo"])
        self.assertEqual(d["scope_words"]["team"], "Your words")
        r = row(self.factory, p, "vocabulary")
        self.assertEqual((r["source"], r["source_word"]), ("team", "from your words"))
        self.assertIn("Your words", r["scope_words"])
        for r in d["rows"]:
            self.assertNotIn("team", " ".join(r["scope_words"]).lower(), r["id"])
            self.assertNotIn("overrides the team", r["source_word"], r["id"])


if __name__ == "__main__":
    unittest.main()
