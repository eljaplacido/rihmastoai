"""FR-JRN1: guided journeys in the kernel, Ask Rihma and the command line.

The catalogue and its record-derived progress, plain-language routing without a model, per-person guide state,
and the read-only command line. The HTTP routes are in tests/test_journey_cockpit.py and the browser journey in
tests/test_ui_journey.py.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_walkthrough import code_folder  # noqa: E402
from walkthrough_fakes import allow_roots  # noqa: E402

from kernel import journey_chat as jc  # noqa: E402
from kernel import journey_guide as jg  # noqa: E402
from kernel import journey_intent as ji  # noqa: E402
from kernel import journey_state as js  # noqa: E402
from kernel import journeys as kj  # noqa: E402
from kernel import walkthrough as wk  # noqa: E402
from kernel.assistant import ask  # noqa: E402
from kernel.assistant_snapshot import relevant_first  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.walkthrough_adopt import journey_next  # noqa: E402

PERSON, PERSONA = "Aino Example", "developer"


def adopted_project(case: FactoryTestCase):
    """Enough real records to put a project after adoption, baseline, contract, assessment and alignment."""
    p = case.new(title="Orders")
    p.update_meta(source_kind="adopted", intent="maintain")
    p.write("adopted.json", {"source": "C:/example/orders"})
    p.write("baseline.json", {"verdict": "passed"})
    p.write("contract.json", {"requirements": [{"id": "R-1", "statement": "Existing behaviour stays.",
                                                "acceptance": []}]})
    p.write("assessments/index.json", [{"id": "AS-1", "at": case.clock.stamp(), "counts": {"findings": 2}}])
    p.log("adopted", {"source": "C:/example/orders", "person": PERSON})
    p.log("alignment_scanned", {"person": PERSON})
    return p


class CatalogueAndProgressTest(FactoryTestCase):
    def test_FR_JRN1_AC_1_the_catalogue_and_progress_name_real_steps_actions_and_commands(self):
        rows = kj.catalogue("business_owner")
        self.assertEqual([j["name"] for j in rows if j["starter"]], list(kj.STARTERS))
        self.assertEqual(len(rows), 7)
        brownfield = next(j for j in rows if j["name"] == "brownfield")
        self.assertEqual(brownfield["label"], "Bring in a system we already have")
        self.assertEqual(brownfield["steps"][0]["title"], "Say where the system's files are")
        for row in rows:
            self.assertTrue(row["about"] and row["steps"])
            self.assertEqual(len({s["id"] for s in row["steps"]}), len(row["steps"]))

        p = adopted_project(self)
        before = len(p.ledger().records())
        prog = js.progress(self.factory, "brownfield", project=p, person=PERSON, persona=PERSONA)
        states = {s["id"]: s["state"] for s in prog["steps"]}
        self.assertEqual(prog["next"], "checks")
        for sid in ("folder", "scan", "adopt", "baseline", "spec", "assess", "review"):
            self.assertEqual(states[sid], "done", sid)
        step = next(s for s in prog["steps"] if s["id"] == "checks")
        self.assertEqual(step["action"], {"control": "watch_setup", "route": f"#/p/{p.pid}/overview",
                                          "walkthrough": None, "do": "watch"})
        self.assertIn(f"checks enable {p.pid} secrets", step["command"])
        self.assertIn(f'--person "{PERSON}" --persona {PERSONA}', step["command"])
        self.assertEqual(js.journey_for(p), "brownfield")
        self.assertEqual(len(p.ledger().records()), before)       # measuring writes nothing

        p.log("watch_set", {"person": PERSON})
        p.log("change_submitted", {"person": PERSON})
        prog = js.progress(self.factory, "brownfield", project=p)
        change = next(s for s in prog["steps"] if s["id"] == "change")
        self.assertEqual(change["state"], "under_way")
        self.assertEqual(prog["next"], "change")
        p.log("change_applied", {"person": PERSON})
        self.assertEqual(js.progress(self.factory, "brownfield", project=p)["next"], "tools")
        done = js.progress(self.factory, "brownfield", project=p,
                           marks={"tools": {"how": "skipped", "at": self.clock.stamp()}})
        self.assertEqual(done["next"], "deploy")

    def test_FR_JRN1_AC_1_an_automation_run_counts_only_for_projects_it_reaches(self):
        first, second = self.new(title="First"), self.new(title="Second")
        payload = {"id": "AU-first", "project": first.pid, "outcome": "done"}
        first.log("automation_ran", payload)
        factory_project(self.factory).log("automation_ran", payload)
        for p, expected in ((first, "done"), (second, "todo")):
            prog = js.progress(self.factory, "automations", project=p)
            ran = next(s for s in prog["steps"] if s["id"] == "ran")
            self.assertEqual(ran["state"], expected, p.pid)

    def test_FR_JRN1_AC_2_plain_questions_get_a_record_grounded_answer_without_a_model(self):
        cases = {
            "how should I get started with a brownfield project": ("journey", "brownfield"),
            "I have a project in C:\\code\\orders": ("journey", "brownfield"),
            "minulla on olemassa oleva projekti": ("journey", "brownfield"),
            "what should I do next?": ("next", None),
            "mitä seuraavaksi": ("next", None),
            "how do I get started": ("start", None),
            "walk me through it": ("guide", None),
            "Where do I assess an existing system?": None,
            "How is the existing project doing?": None,
        }
        for question, expected in cases.items():
            self.assertEqual(ji.recognise(question), expected, question)
        self.assertEqual(ji.recognise("how should I start with a brownfeild project"), ("journey", "brownfield"))

        model = mock.Mock()
        out = ask(self.factory, "how should I get started with a brownfield project", persona=PERSONA, model=model)
        model.assert_not_called()
        self.assertEqual(out["by"], "journey")
        self.assertEqual(out["journey"]["next"], "folder")
        for said in ("Choose the folder or git address", "Walk me through it", "Guide me step by step"):
            self.assertIn(said, out["answer"])
        self.assertEqual(out["guide"], {"journey": "brownfield", "project": None})
        self.assertIsNone(factory_project(self.factory, False))

        how = jc.grounding("How do I run the assessment?")
        self.assertEqual(how["journey"], "Feed in an existing project")
        self.assertTrue(any("Run the assessment" in row and "<- asked" in row for row in how["steps"]))
        fitted = relevant_first({"project": {"title": "Orders"}}, "How do I run the assessment?")
        self.assertEqual(fitted["how_to"], how)
        self.assertIsNone(jc.grounding("What is the assessment's status?"))

    def test_FR_JRN1_AC_2_next_and_the_three_ways_in_follow_the_open_project_or_factory(self):
        p = adopted_project(self)
        out = jc.next_answer(self.factory, p, persona=PERSONA)
        self.assertEqual(out["journey"]["next"], "checks")
        self.assertEqual(out["guide"], {"journey": "brownfield", "project": p.pid})
        self.assertEqual(out["sources"], [p.pid])
        empty = FactoryTestCase()
        empty.setUp()
        self.addCleanup(empty.tearDown)
        starters = jc.next_answer(empty.factory, None, persona="business_owner")
        self.assertEqual([j["name"] for j in starters["starters"]], list(kj.STARTERS))
        self.assertIn("three ways in", starters["answer"])


class GuideTest(FactoryTestCase):
    def test_FR_JRN1_AC_3_a_guide_is_per_person_persistent_signed_and_restarts_from_records(self):
        other = "Ville Example"
        jg.start(self.factory, "brownfield", person=PERSON, persona=PERSONA)
        jg.start(self.factory, "model", person=other, persona=PERSONA)
        self.assertEqual(jg.view(self.factory, PERSON)["progress"]["next"], "folder")
        self.assertEqual(jg.view(self.factory, other)["progress"]["next"], "open")

        jg.mark(self.factory, person=PERSON, persona=PERSONA, step="folder", how="skip")
        got = jg.view(self.factory, PERSON)
        self.assertEqual(got["progress"]["next"], "scan")
        self.assertEqual(got["progress"]["steps"][0]["state"], "skipped")
        jg.mark(self.factory, person=PERSON, persona=PERSONA, step="scan", how="did")
        self.assertIn("You said you did it", jg.view(self.factory, PERSON)["progress"]["steps"][1]["said"])

        p = self.new(title="Orders")
        jg.attach(self.factory, person=PERSON, persona=PERSONA, project=p.pid)
        self.assertEqual(jg.view(self.factory, PERSON)["progress"]["project"], p.pid)
        stopped = jg.stop(self.factory, person=PERSON, persona=PERSONA)
        self.assertEqual(stopped["state"], "stopped")
        with self.assertRaises(jg.GuideRefused):
            jg.mark(self.factory, person=PERSON, persona=PERSONA, step="adopt", how="did")

        restarted = jg.start(self.factory, "brownfield", person=PERSON, persona=PERSONA, project=p.pid)
        self.assertEqual(restarted["marks"], {})                     # a new guide does not inherit old skips
        self.assertEqual(jg.view(self.factory, other)["guide"]["state"], "active")
        events = [r["event"] for r in factory_project(self.factory).ledger().records()
                  if r["event"]["kind"].startswith("journey_")]
        self.assertEqual([e["kind"] for e in events], ["journey_started", "journey_started", "journey_step",
                                                       "journey_step", "journey_step", "journey_ended",
                                                       "journey_started"])
        self.assertEqual(events[2]["payload"] | {}, {"journey": "brownfield", "step": "folder", "how": "skipped",
                                                     "person": PERSON, "persona": PERSONA})
        self.assertNotIn("C:/example", json.dumps(events))

    def test_FR_JRN1_AC_3_the_matching_walkthrough_measures_the_folder_and_scan_before_adoption(self):
        allow_roots(self, self.tmp)
        repo = code_folder(self.tmp / "orders", repo=False)
        jg.start(self.factory, "brownfield", person=PERSON, persona=PERSONA)
        walk = wk.start(self.factory, "plug_in", person=PERSON, persona=PERSONA)
        wk.reply(self.factory, walk["id"], person=PERSON, persona=PERSONA, text=str(repo))
        got = jg.view(self.factory, PERSON)
        self.assertEqual(got["walk"]["source"], str(repo.resolve()))
        states = {s["id"]: s["state"] for s in got["progress"]["steps"]}
        self.assertEqual((states["folder"], states["scan"]), ("done", "done"))
        self.assertEqual(got["progress"]["next"], "adopt")
        self.assertIn("Scanned:", next(s for s in got["progress"]["steps"] if s["id"] == "scan")["said"])

    def test_FR_JRN1_AC_3_refusals_do_not_start_or_change_a_guide(self):
        for action in (
            lambda: jg.start(self.factory, "unknown", person=PERSON, persona=PERSONA),
            lambda: jg.start(self.factory, "brownfield", person="factory", persona=PERSONA),
            lambda: jg.start(self.factory, "brownfield", person=PERSON, persona="unknown"),
            lambda: jg.start(self.factory, "brownfield", person=PERSON, persona=PERSONA, project="missing"),
            lambda: jg.stop(self.factory, person=PERSON, persona=PERSONA),
        ):
            with self.assertRaises(ValueError):
                action()
        self.assertIsNone(jg.guide_of(self.factory, PERSON))
        jg.start(self.factory, "ide", person=PERSON, persona=PERSONA)
        before = jg.guide_of(self.factory, PERSON)
        for step, how in (("unknown", "did"), ("section", "perhaps")):
            with self.assertRaises(jg.GuideRefused):
                jg.mark(self.factory, person=PERSON, persona=PERSONA, step=step, how=how)
        self.assertEqual(jg.guide_of(self.factory, PERSON), before)


class CommandLineTest(FactoryTestCase):
    def cli(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *args])
        return code, out.getvalue(), err.getvalue()

    def test_FR_JRN1_AC_4_the_read_only_cli_and_an_adoption_offer_the_same_next_step(self):
        code, out, err = self.cli("journey", "list", "--json")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(len(json.loads(out)["journeys"]), 7)
        code, out, _ = self.cli("journey", "list", "--persona", "business_owner")
        self.assertEqual(code, 0)
        self.assertIn("Bring in a system we already have (brownfield)", out)
        self.assertIn("Say where the system's files are", out)
        self.assertNotIn('"journeys"', out)
        code, out, _ = self.cli("journey", "brownfield")
        self.assertEqual(code, 0)
        self.assertIn("Feed in an existing project takes 11 steps", out)
        self.assertIn("0 of 11 done", out)
        self.assertIn(">[ ] Choose the folder or git address", out)
        self.assertIn("rihmasto scan <folder>", out)

        p = adopted_project(self)
        code, out, _ = self.cli("journey", "next", "--project", p.pid)
        self.assertEqual(code, 0)
        self.assertIn("Set up the watch", out)
        said, links = journey_next(self.factory, p, PERSONA)
        self.assertIn("Nothing watches it yet", said)
        self.assertEqual(links[0]["do"], "watch")
        self.assertEqual(links[0]["project"], p.pid)
        self.assertEqual(links[1]["guide"], "brownfield")
        self.assertEqual(links[1]["route"], f"#/p/{p.pid}/overview")


if __name__ == "__main__":
    unittest.main()
