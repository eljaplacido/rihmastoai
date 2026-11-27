"""The words a team and a project give Rihmasto's own terms (D-0027, FR-TM2): shipped default, then the team's, then
the project's; read at read time, never rewriting a record; each definition kept with who, why and since when; a
preview before saving; Undo to the earlier reading exactly. Fixtures are invented."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graph_view_fixture import every_kind  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import teams, vocab, vocab_edit  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402

IT = {"person": "Aino Example", "persona": "it"}
OWNER = {"person": "Pia Example", "persona": "product_owner"}


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
            and p.name not in ("vocabulary.json", "ledger.jsonl") and ".vocab" not in p.name
            and p.parent.name != "_teams"}


class VocabTest(CockpitTestCase):
    def setUp(self):
        super().setUp()
        self.p = every_kind(self)
        self.tid = teams.create(self.factory, "Platform", **IT)["team"]["id"]
        teams.move_project(self.factory, self.p, self.tid, **IT)

    def read(self, project=True):
        return vocab.effective(self.factory, self.p if project else None, None if project else self.tid)["terms"]

    def test_FR_TM2_AC_1_a_term_resolves_shipped_then_the_team_then_the_project(self):
        t = self.read()["kind:requirement"]
        self.assertEqual((t["label"], t["scope"]), ("Requirement", "shipped"))
        vocab_edit.set_term(self.factory, "team", self.tid, term="kind:requirement", fields={"label": "Story"},
                            reason="we write stories", **IT)
        t = self.read()["kind:requirement"]
        self.assertEqual((t["label"], t["scope"], t["shipped"]["label"]), ("Story", "team", "Requirement"))
        vocab_edit.set_term(self.factory, "project", self.p.pid, term="kind:requirement",
                            fields={"label": "Feature"}, **OWNER)
        t = self.read()["kind:requirement"]
        self.assertEqual((t["label"], t["scope"], t["team"]["label"], t["project"]["label"]),
                         ("Feature", "project", "Story", "Feature"))
        self.assertEqual(self.read(project=False)["kind:requirement"]["label"], "Story")    # the team's reading

    def test_FR_TM2_AC_2_a_term_can_be_renamed_described_given_synonyms_hidden_or_given_a_custom_word(self):
        v = vocab_edit
        v.set_term(self.factory, "team", self.tid, term="kind:criterion",
                   fields={"description": "A check written as given, when, then", "synonyms": ["acceptance check"]}, **IT)
        v.set_term(self.factory, "team", self.tid, term="rel:has_criterion", fields={"label": "is checked by"}, **IT)
        v.set_term(self.factory, "team", self.tid, term="kind:comment", fields={"hidden": True}, **IT)
        v.set_term(self.factory, "team", self.tid, fields={"label": "Brief", "means": "kind:request"}, **IT)
        t = self.read()
        self.assertIn("acceptance check", t["kind:criterion"]["synonyms"])
        self.assertEqual(t["kind:criterion"]["description"], "A check written as given, when, then")
        self.assertEqual(t["rel:has_criterion"]["label"], "is checked by")
        self.assertTrue(t["kind:comment"]["hidden"])
        self.assertEqual(t["custom:brief"]["means"], "kind:request")
        self.assertIn("Brief", t["kind:request"]["synonyms"])         # another word for a kind is its synonym
        with self.assertRaises(ValueError):                            # a custom term means a record kind
            v.set_term(self.factory, "team", self.tid, fields={"label": "Odd", "means": "rel:asks"}, **IT)

    def test_FR_TM2_AC_3_the_graph_reads_through_the_overlay_and_no_stored_record_changes(self):
        before = tree(self.factory.home)
        vocab_edit.set_term(self.factory, "team", self.tid, term="kind:requirement", fields={"label": "Story"}, **IT)
        vocab_edit.set_term(self.factory, "team", self.tid, term="kind:comment", fields={"hidden": True}, **IT)
        self.assertEqual(tree(self.factory.home), before)               # no record, spec or project file changed
        status, out, _ = self.call("GET", f"/api/projects/{self.p.pid}/graph")
        self.assertEqual(status, 200, out)
        kinds = {k["id"]: k for k in out["kinds"]}
        self.assertEqual((kinds["requirement"]["label"], kinds["requirement"]["scope"]), ("Story", "team"))
        self.assertNotIn("comment", kinds)                              # hidden from the legend
        self.assertFalse([n for n in out["nodes"] if n["kind"] == "comment"])
        self.assertEqual(out["vocabulary"]["team"], self.tid)
        vocab_edit.undo(self.factory, "team", self.tid, **IT)
        vocab_edit.undo(self.factory, "team", self.tid, **IT)
        status, out, _ = self.call("GET", f"/api/projects/{self.p.pid}/graph")
        self.assertEqual({k["id"]: k["label"] for k in out["kinds"]}["requirement"], "Requirement")

    def test_FR_TM2_AC_4_old_records_are_included_the_preview_counts_what_reads_differently(self):
        seen = vocab_edit.preview(self.factory, "team", self.tid, term="kind:requirement", fields={"label": "Story"})
        self.assertGreaterEqual(seen["nodes"], 3)                       # the project's requirements, old and new
        self.assertGreaterEqual(seen["records"], 1)
        self.assertLessEqual(seen["records"], seen["nodes"])
        self.assertIn("the Knowledge graph's labels and legend", seen["views"])
        self.assertIn("nothing stored is rewritten", seen["lines"][-1])
        self.assertEqual(vocab.read_layer(self.factory, "team", self.tid), {})      # a preview records nothing

    def test_FR_TM2_AC_5_each_definition_is_kept_with_who_why_and_since_when_and_undo_restores_exactly(self):
        vocab_edit.set_term(self.factory, "team", self.tid, term="kind:task", fields={"label": "Work item"},
                            reason="our board says work item", **IT)
        first = vocab.read_layer(self.factory, "team", self.tid)["kind:task"]
        self.assertEqual((first["by"], first["why"], first["since"][:4]), ("Aino Example", "our board says work item",
                                                                           "2026"))
        vocab_edit.set_term(self.factory, "team", self.tid, term="kind:task", fields={"label": "Job"}, **IT)
        defs = vocab_edit.definitions(self.factory, self.p, "kind:task")
        self.assertEqual([d["label"] for d in defs], ["Job", "Work item"])
        self.assertEqual(self.read()["kind:task"]["label"], "Job")
        vocab_edit.undo(self.factory, "team", self.tid, **IT)
        self.assertEqual(vocab.read_layer(self.factory, "team", self.tid)["kind:task"], first)   # exactly
        self.assertTrue(vocab_edit.definitions(self.factory, self.p, "kind:task")[0]["undone"])
        vocab_edit.undo(self.factory, "team", self.tid, **IT)
        self.assertNotIn("kind:task", vocab.read_layer(self.factory, "team", self.tid))
        with self.assertRaises(ValueError):
            vocab_edit.undo(self.factory, "team", self.tid, **IT)
        kinds = [r["event"]["kind"] for r in self.p.factory.project("_factory").ledger().of_kind(
            vocab_edit.SET_KIND, vocab_edit.UNDONE_KIND)]
        self.assertEqual(kinds, ["vocab_set", "vocab_set", "vocab_undone", "vocab_undone"])

    def test_FR_TM2_AC_6_only_it_changes_a_team_s_words_and_it_or_the_owner_a_project_s(self):
        with self.assertRaises(DecisionRefused):
            vocab_edit.set_term(self.factory, "team", self.tid, term="kind:task", fields={"label": "Job"},
                                person="Pia Example", persona="product_owner")
        with self.assertRaises(DecisionRefused):
            vocab_edit.set_term(self.factory, "project", self.p.pid, term="kind:task", fields={"label": "Job"},
                                person="Dev Example", persona="developer")
        vocab_edit.set_term(self.factory, "project", self.p.pid, term="kind:task", fields={"label": "Job"}, **OWNER)
        self.assertEqual(self.read()["kind:task"]["scope"], "project")

    def test_FR_TM2_AC_7_the_routes_preview_save_and_undo_signed_and_a_solo_person_needs_no_approval(self):
        body = {"term": "kind:criterion", "label": "Check", "reason": "we say check", "person": "Aino Example",
                "persona": "it", "team": self.tid}
        status, out, _ = self.call("POST", "/api/vocabulary/preview", body)
        self.assertEqual((status, out["after"]["label"]), (200, "Check"), out)
        self.assertEqual(vocab.read_layer(self.factory, "team", self.tid), {})
        status, out, _ = self.call("PUT", f"/api/teams/{self.tid}/vocabulary", body)
        self.assertEqual((status, out["saved"]), (200, True), out)
        status, out, _ = self.call("GET", f"/api/vocabulary?project={self.p.pid}&term=kind:criterion")
        row = out["terms"]["kind:criterion"]
        self.assertEqual((row["label"], row["scope"], row["by"]), ("Check", "team", "Aino Example"))
        self.assertEqual(out["definitions"][0]["label"], "Check")
        status, out, _ = self.call("POST", "/api/vocabulary/undo", {"team": self.tid, **IT})
        self.assertEqual(status, 200, out)
        status, out, _ = self.call("PUT", f"/api/projects/{self.p.pid}/vocabulary",
                                   {"term": "kind:task", "label": "Job", "person": "Pia Example",
                                    "persona": "business_owner", "as_needed": True})
        self.assertEqual(status, 200, out)
        status, out, _ = self.call("PUT", f"/api/teams/{self.tid}/vocabulary",
                                   {"term": "kind:task", "label": "Job", "person": "Dev Example",
                                    "persona": "developer"})
        self.assertEqual(status, 403, out)

    def test_FR_TM2_AC_8_the_ontology_file_is_the_one_source_and_is_not_edited(self):
        ontology = Path(__file__).resolve().parent.parent / "kernel" / "ontology.json"
        before = ontology.read_bytes()
        vocab_edit.set_term(self.factory, "team", self.tid, term="kind:task", fields={"label": "Job"}, **IT)
        self.assertEqual(ontology.read_bytes(), before)
        self.assertEqual(vocab.shipped()["kind:task"]["label"], "Task")
        doc = json.loads((self.factory.home / "_teams" / f"{self.tid}.vocab.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["terms"]["kind:task"]["label"], "Job")


if __name__ == "__main__":
    unittest.main()
