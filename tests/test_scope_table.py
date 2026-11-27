"""What applies where (FR-TM3): one table says for every setting surface whether it is set per project, per team or is
the shipped default, and where a project's value comes from now. A completeness test iterates the map's controls on
Settings. No enterprise or business-unit level exists in the code, the routes or the chat. Invented fixtures."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import scope_table, teams, vocab_edit  # noqa: E402
from kernel import structure_policy as sp  # noqa: E402
from kernel.assistant_rules import ui_map  # noqa: E402
from kernel.control_pages import CONTROL_PAGES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IT = {"person": "Aino Example", "persona": "it"}


def settings_controls() -> list[str]:
    """The map's controls that sit on Settings (kernel/control_pages.py: the page outside a project)."""
    ids = {c["id"] for c in ui_map()["controls"]}
    return sorted(c for c, (_, page) in CONTROL_PAGES.items() if page == "settings" and c in ids)


class ScopeTableTest(FactoryTestCase):
    def test_FR_TM3_AC_1_every_settings_control_of_the_map_has_a_scope_entry(self):
        controls = settings_controls()
        self.assertGreater(len(controls), 35)
        missing = [c for c in controls if scope_table.covers(c) is None]
        self.assertEqual(missing, [], "add these controls to a surface of kernel/scope_table.py SURFACES")
        self.assertIsNone(scope_table.covers("a_new_setting"))              # the check fails on a gap
        known = {c["id"] for c in ui_map()["controls"]}
        stray = sorted(c for c in scope_table.COVERED if c not in known)
        self.assertEqual(stray, [], "a surface names a control the map does not have")
        for sid, label, scopes, _, team_link, proj_link, _reader in scope_table.SURFACES:
            self.assertTrue(label and scopes and set(scopes) <= set(scope_table.SCOPE_WORD), sid)
            if "project" in scopes:
                self.assertTrue(proj_link or team_link, sid)               # a link says where to change it
        ids = [s[0] for s in scope_table.SURFACES]
        self.assertEqual(len(ids), len(set(ids)))
        for named in ("structure", "enforcement", "itops", "modules", "runners", "people", "observer", "automations",
                      "evals", "vocabulary", "teams", "appearance"):
            self.assertIn(named, ids)

    def test_FR_TM3_AC_2_each_row_says_where_the_projects_value_comes_from(self):
        p = self.factory.new_project("Loans")
        rows = {r["id"]: r for r in scope_table.rows(self.factory, p)}
        self.assertEqual({rows[s]["source"] for s in ("structure", "enforcement", "vocabulary", "teams")}, {"default"})
        self.assertEqual(rows["structure"]["source_word"], "shipped default")
        sp.set_levels(self.factory, None, {"layout": "off"}, person="Aino Example", persona="it", reason="our layout",
                      kind="built")
        rows = {r["id"]: r for r in scope_table.rows(self.factory, p)}
        self.assertEqual((rows["structure"]["source"], rows["structure"]["source_word"]),
                         ("home", "set for all your projects"))
        sp.set_levels(self.factory, p, {"commit_hygiene": "advise"}, person="Aino Example", persona="developer",
                      reason="squashed on merge")
        rows = {r["id"]: r for r in scope_table.rows(self.factory, p)}
        self.assertEqual((rows["structure"]["source"], rows["structure"]["source_word"]),
                         ("project", "this project's own"))
        vocab_edit.set_term(self.factory, "team", teams.AUTO_ID, term="kind:task", fields={"label": "Job"}, **IT)
        self.assertEqual({r["id"]: r for r in scope_table.rows(self.factory, p)}["vocabulary"]["source"], "team")
        vocab_edit.set_term(self.factory, "project", p.pid, term="kind:test", fields={"label": "Check"}, **IT)
        self.assertEqual({r["id"]: r for r in scope_table.rows(self.factory, p)}["vocabulary"]["source"], "project")
        other = self.factory.new_project("Orders")
        self.assertEqual({r["id"]: r for r in scope_table.rows(self.factory, other)}["structure"]["source"], "home")
        tid = teams.create(self.factory, "Platform", **IT)["team"]["id"]
        teams.move_project(self.factory, p, tid, **IT)
        self.assertEqual({r["id"]: r for r in scope_table.rows(self.factory, p)}["teams"]["source"], "project")
        for row in scope_table.rows(self.factory, p):                       # each links to where it is changed
            self.assertTrue(row["change_for_team"] or row["change_for_project"] or row["scopes"] in (["default"],
                                                                                                    ["default", "personal"]), row["id"])

    def test_FR_TM3_AC_3_the_scope_wording_of_the_views_follows_the_table(self):
        words = (ROOT / "cockpit" / "static" / "words.js").read_text(encoding="utf-8")
        found = dict(re.findall(r'(\w+): "([^"]+)"', re.search(r"const SCOPE_WORDS = \{(.*?)\};", words, re.S).group(1)))
        for scope, word in scope_table.SCOPE_WORD.items():
            self.assertEqual(found["shipped" if scope == "default" else scope], word, scope)
        self.assertEqual(found["platform"], scope_table.SCOPE_WORD["home"])        # the old "platform" is the home's: all teams
        for name in ("structure.js", "enforcement.js"):
            js = (ROOT / "cockpit" / "static" / name).read_text(encoding="utf-8")
            self.assertIn("scopeWord as baseScopeWord", js, name)
            self.assertNotIn('platform: "All projects"', js, name)

    def test_FR_TM3_AC_5_there_is_no_enterprise_or_business_unit_level_anywhere(self):
        files = ["kernel/teams.py", "kernel/vocab.py", "kernel/vocab_edit.py", "kernel/scope_table.py",
                 "kernel/teams_chat.py", "kernel/teams_cli.py", "cockpit/team_routes.py", "cockpit/static/teams.js",
                 "cockpit/static/vocab.js", "cockpit/static/applieswhere.js"]
        for name in files:
            text = (ROOT / name).read_text(encoding="utf-8").lower()
            for word in ("enterprise", "business unit", "business-unit", "org level", "organisation level"):
                if word in text:
                    allowed = name == "kernel/teams.py" and word in ("enterprise", "business unit", "business-unit")
                    self.assertTrue(allowed, (name, word))                  # only the module doc says there is none
        self.assertIn("unit", teams.read(self.factory, teams.AUTO_ID))        # the one trace: an empty optional field
        self.assertEqual(teams.read(self.factory, teams.AUTO_ID)["unit"], "")
        self.assertNotIn("unit", " ".join(teams.describe(self.factory)["teams"][0]))
        self.assertEqual(set(scope_table.SCOPE_WORD), {"default", "home", "team", "project", "personal"})


class ScopeRouteTest(CockpitTestCase):
    def test_FR_TM3_AC_7_the_scope_route_reads_the_table_for_a_project_and_for_the_team(self):
        p = self.factory.new_project("Loans")
        status, out, _ = self.call("GET", f"/api/scope?project={p.pid}")
        self.assertEqual(status, 200, out)
        self.assertEqual(out["team"]["id"], teams.AUTO_ID)
        self.assertEqual({r["id"] for r in out["rows"]} >= {"structure", "enforcement", "vocabulary", "teams"}, True)
        status, out, _ = self.call("GET", "/api/scope")
        self.assertEqual((status, out["project"], out["team"]), (200, None, None))
        status, out, _ = self.call("GET", "/api/scope?project=no-such-project")
        self.assertIn(status, (404, 410))


if __name__ == "__main__":
    unittest.main()
