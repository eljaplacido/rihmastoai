"""The word in force is used wherever a kind's name appears (FR-TM6): in the text Rihmasto writes about a kind (graph
issues, Ask Rihma's answers from the map), a hidden kind leaves the Knowledge graph whole (its counts, its issues and a
focus agree with what is drawn, and a warning on a hidden record is said, not lost), and the page across projects says
which words it reads in. Invented fixtures."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from graph_view_fixture import every_kind  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import teams, vocab, vocab_edit, vocab_say  # noqa: E402
from kernel.assistant import ask  # noqa: E402

IT = {"person": "Aino Example", "persona": "it"}
ROOT = Path(__file__).resolve().parent.parent


def words(factory, project, **terms):
    for term, label in terms.items():
        vocab_edit.set_term(factory, "project", project.pid, term=f"kind:{term}", fields={"label": label}, **IT)


class SayTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.factory.new_project("Equipment loans")

    def eff(self):
        return vocab.effective(self.factory, self.p)

    def test_FR_TM6_AC_1_a_text_that_names_a_kind_says_it_in_the_word_in_force(self):
        self.assertEqual(vocab_say.say(self.eff(), "No test checks this requirement."), "No test checks this requirement.")
        words(self.factory, self.p, requirement="Story", test="Check")
        say = lambda t: vocab_say.say(self.eff(), t)                                    # noqa: E731
        self.assertEqual(say("No test checks this requirement."), "No check checks this story.")
        self.assertEqual(say("3 requirements and 2 Tests; Requirement R-1"), "3 stories and 2 Checks; Story R-1")
        self.assertEqual(say("REQUIREMENTS"), "STORIES")
        self.assertEqual(say("the requirements.md file and a retest"), "the requirements.md file and a retest")
        self.assertEqual(say(""), "")

    def test_FR_TM6_AC_2_a_hidden_kind_a_relation_and_a_custom_term_are_not_swapped_in(self):
        words(self.factory, self.p, requirement="Story")
        vocab_edit.set_term(self.factory, "project", self.p.pid, term="kind:comment", fields={"label": "Note", "hidden": True}, **IT)
        vocab_edit.set_term(self.factory, "project", self.p.pid, term=None, fields={"label": "Brief", "means": "kind:request"}, **IT)
        out = vocab_say.say(self.eff(), "a comment, a request and a requirement")
        self.assertEqual(out, "a comment, a request and a story")

    def test_FR_TM6_AC_3_two_kinds_renamed_across_each_other_are_read_once_not_twice(self):
        words(self.factory, self.p, requirement="Task", task="Story")
        self.assertEqual(vocab_say.say(self.eff(), "a requirement and a task"), "a task and a story")


class GraphHiddenTest(CockpitTestCase):
    def setUp(self):
        super().setUp()
        self.p = every_kind(self)

    def graph(self, query=""):
        status, out, _ = self.call("GET", f"/api/projects/{self.p.pid}/graph{query}")
        self.assertEqual(status, 200, out)
        return out

    def test_FR_TM6_AC_4_a_hidden_kind_leaves_before_anything_is_counted(self):
        before = self.graph()
        reqs = [n for n in before["nodes"] if n["kind"] == "requirement"]
        self.assertGreater(len(reqs), 1)
        vocab_edit.set_term(self.factory, "project", self.p.pid, term="kind:requirement", fields={"hidden": True}, **IT)
        after = self.graph()
        self.assertEqual([n for n in after["nodes"] if n["kind"] == "requirement"], [])
        shown = {n["id"] for n in after["nodes"]}
        self.assertEqual(after["counts"]["nodes"], before["counts"]["nodes"] - len(reqs))
        self.assertEqual(after["counts"]["matching"], after["counts"]["nodes"])
        self.assertEqual(after["counts"]["shown"], len(after["nodes"]))
        self.assertTrue(all(e["from"] in shown and e["to"] in shown for e in after["edges"]))
        self.assertNotIn("requirement", [k["id"] for k in after["kinds"]])
        self.assertEqual(sum(k["total"] for k in self.graph("")["kinds"]), after["counts"]["nodes"])

    def test_FR_TM6_AC_5_a_warning_on_a_hidden_record_is_said_not_lost_and_a_focus_on_it_says_hidden(self):
        before = self.graph()
        warned = sum(i["count"] for i in before["issues"] if i["id"] in ("untested", "refuted_basis"))
        self.assertGreater(warned, 0, "the fixture holds a requirement with a warning")
        vocab_edit.set_term(self.factory, "project", self.p.pid, term="kind:requirement", fields={"hidden": True}, **IT)
        after = self.graph()
        self.assertEqual([i for i in after["issues"] if i["id"] in ("untested", "refuted_basis")], [])
        held = after["hidden"]
        self.assertEqual(held["kinds"], ["requirement"])
        self.assertGreaterEqual(held["warnings"], 1)
        self.assertIn("warning", held["note"])
        self.assertIn("Requirement", held["note"])
        self.assertTrue(held["said"])
        focused = self.graph("?focus=R-1")
        self.assertEqual([n["id"] for n in focused["nodes"] if n["kind"] == "requirement"], [])
        self.assertTrue(focused["hidden"]["focus_hidden"])
        plain = self.graph("?focus=T-001")
        self.assertFalse(plain["hidden"]["focus_hidden"])

    def test_FR_TM6_AC_6_hiding_a_kind_that_raises_warnings_says_so_in_the_preview(self):
        seen = vocab_edit.preview(self.factory, "project", self.p.pid, term="kind:requirement", fields={"hidden": True})
        text = " ".join(seen["lines"])
        self.assertIn("warning", text)
        self.assertIn("still hold", text)
        self.assertGreaterEqual(seen["warnings"], 1)
        quiet = vocab_edit.preview(self.factory, "project", self.p.pid, term="kind:requirement", fields={"label": "Story"})
        self.assertNotIn("warning", " ".join(quiet["lines"]))
        self.assertEqual(quiet["warnings"], 0)

    def test_FR_TM6_AC_7_the_graphs_issue_text_uses_the_word_in_force(self):
        words(self.factory, self.p, requirement="Story", test="Check")
        out = self.graph()
        texts = [i["text"] for i in out["issues"]] + [i["text"] for i in out["issue_kinds"]]
        self.assertTrue(any("story" in t.lower() for t in texts))
        self.assertFalse(any(re.search(r"\brequirement", t, re.I) for t in texts), texts)
        self.assertFalse(any(re.search(r"\btest\b", t, re.I) for t in texts), texts)

    def test_FR_TM6_AC_8_the_page_across_projects_says_which_words_it_reads_in(self):
        other = self.factory.new_project("Orders")
        status, out, _ = self.call("GET", "/api/graph")
        self.assertEqual(status, 200, out)
        self.assertIsNone(out["vocabulary"]["mixed"])                            # nobody says anything differently
        words(self.factory, self.p, requirement="Story")
        status, out, _ = self.call("GET", "/api/graph")
        mixed = out["vocabulary"]["mixed"]
        self.assertEqual(mixed["reading"], "shipped")
        self.assertIn(self.p.pid, mixed["projects"])
        self.assertNotIn(other.pid, mixed["projects"])
        self.assertIn("shipped words", mixed["note"])
        tid = teams.create(self.factory, "Platform", **IT)["team"]["id"]
        for p in (self.p, other):
            teams.move_project(self.factory, p, tid, **IT)
        vocab_edit.set_term(self.factory, "team", tid, term="kind:task", fields={"label": "Job"}, **IT)
        status, out, _ = self.call("GET", "/api/graph")
        self.assertEqual(out["vocabulary"]["mixed"]["reading"], "team")          # both share the team; one keeps its own
        self.assertEqual(out["vocabulary"]["mixed"]["projects"], [self.p.pid])


class MapAnswerTest(CockpitTestCase):
    def test_FR_TM6_AC_9_askrihmas_answers_from_the_map_use_the_word_in_force(self):
        p = self.factory.new_project("Equipment loans")
        plain = ask(self.factory, "What is Spec & contract?", persona="product_owner", project_id=p.pid)
        self.assertIn("requirements", plain["answer"])
        words(self.factory, p, requirement="Story", criterion="Check")
        out = ask(self.factory, "What is Spec & contract?", persona="product_owner", project_id=p.pid)
        self.assertEqual(out["by"], "map")
        self.assertIn("stories", out["answer"])
        self.assertNotIn("requirements", out["answer"])
        self.assertEqual(out["navigate"]["route"], f"#/p/{p.pid}/spec")             # the way on is not reworded
        other = self.factory.new_project("Orders")
        elsewhere = ask(self.factory, "What is Spec & contract?", persona="product_owner", project_id=other.pid)
        self.assertIn("requirements", elsewhere["answer"])                               # another project: shipped words
        asked = ask(self.factory, "What do stories mean here?", persona="product_owner", project_id=p.pid)
        self.assertNotIn("shipped as Story", asked["answer"])                            # the term line is not swapped twice


class GraphChatTest(CockpitTestCase):
    def test_FR_TM6_AC_12_askrihma_says_which_terms_are_hidden_and_which_words_the_graph_reads_in(self):
        p = every_kind(self)
        other = self.factory.new_project("Orders")
        quiet = ask(self.factory, "Which terms are hidden?", persona="it", project_id=p.pid)
        self.assertEqual(quiet["by"], "rule")
        self.assertIn("No term is hidden", quiet["answer"])
        self.assertEqual(quiet["navigate"]["route"], f"#/p/{p.pid}/graph")
        vocab_edit.set_term(self.factory, "project", p.pid, term="kind:requirement", fields={"hidden": True}, **IT)
        out = ask(self.factory, "Why is a kind missing from the graph?", persona="it", project_id=p.pid)
        self.assertEqual(out["by"], "rule")
        self.assertIn("Hidden here: Requirement (this project)", out["answer"])
        self.assertRegex(out["answer"], r"[1-9]\d* warnings? still holds? on them")
        self.assertIn("show the requirement term again", out["answer"])
        elsewhere = ask(self.factory, "Which terms are hidden?", persona="it", project_id=other.pid)
        self.assertIn("No term is hidden", elsewhere["answer"])
        words(self.factory, other, task="Job")
        across = ask(self.factory, "Which words does the graph read in?", persona="it", project_id=None)
        self.assertIn("shipped words", across["answer"])
        self.assertIn("say some words differently", across["answer"])
        self.assertEqual(across["navigate"]["route"], "#/graph")


class SourceTest(unittest.TestCase):
    def test_FR_TM6_AC_10_the_browser_reads_the_same_words_over_what_it_draws_and_leaves_what_people_wrote(self):
        js = (ROOT / "cockpit" / "static" / "wordsapply.js").read_text(encoding="utf-8")
        for needle in ("shipped", "data-ud", "MutationObserver", "data-said", "TEXTAREA", "isConnected"):
            self.assertIn(needle, js, needle)
        index = (ROOT / "cockpit" / "static" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "cockpit" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertTrue("wordsapply.js" in index or "wordsapply.js" in app)


if __name__ == "__main__":
    unittest.main()
