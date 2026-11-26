"""FR-NVL2: never lost, answered right. What an independent check of FR-NVL1 found, each fixed by rule and tested
through the real cockpit server on a temp factory (tests/test_cockpit.py CockpitTestCase). No model is asked."""

import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).parent))

from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import neverlost, neverlost_chat, triage, triage_all, who_acted  # noqa: E402
from kernel.canon import Canon  # noqa: E402

DEV = {"person": "Ida Example", "persona": "developer"}


class NeverLostFixTest(CockpitTestCase):
    def why(self, pid, **q):
        status, out, _ = self.call("GET", "/api/why?" + urlencode(dict(q, project=pid or "")))
        self.assertEqual(status, 200, out)
        return out

    def ask(self, pid, question, persona="developer", **extra):
        status, out, _ = self.call("POST", "/api/assistant", {"question": question, "persona": persona,
                                                              "project": pid, "person": "Ida Example", **extra})
        self.assertEqual(status, 200, out)
        return out

    def released(self):
        """A built project with a release and a recorded model run: Releases and Insights have data."""
        p = self.built_project()
        p.log("model_run", {"role": "analyst", "model": "m", "endpoint": "go"})
        p.log("release_done", {"release": "v1", "person": "Ida Example"})
        return p

    # -- AC-1: a view with data is never taken as empty -------------------------------------------------------

    def test_FR_NVL2_AC_1_a_view_whose_records_have_data_says_what_it_shows_instead_of_a_made_up_reason(self):
        p = self.released()
        for question, said in (("why is Insights empty?", r"Project insights is not empty here: it shows figures "
                                                           r"from \d+ recorded runs"),
                               ("why are releases empty?", "Releases is not empty here: it shows 1 release")):
            out = self.ask(p.pid, question)
            self.assertEqual(out["by"], "why", question)
            self.assertRegex(out["answer"], said)
            self.assertNotIn("because nothing is recorded", out["answer"])
            self.assertEqual(out["why"]["premise"], "shows")
        out = self.why(p.pid, view="releases")
        self.assertIn("Releases is not empty here: it shows 1 release", out["answer"])
        self.assertEqual(out["fill"]["route"], f"#/p/{p.pid}/releases")
        out = self.ask(p.pid, "why is the Track view not measured?")
        self.assertIn("Track is measured here: it shows progress on", out["answer"])
        # a view with no records still gets its rule; a view Rihmasto has no rule for never takes the premise
        fresh = self.new(title="Fresh one")
        self.assertIn("Releases is empty because a release is cut", self.why(fresh.pid, view="releases")["answer"])
        out = self.why(None, view="ledger")
        self.assertIn("Rihmasto has no record that says it should show something", out["answer"])
        self.assertIn("because nothing is recorded", self.why(None, view="ledger", basis="Nothing yet.")["answer"])

    # -- AC-2: a typed question is read for its subject -------------------------------------------------------

    def test_FR_NVL2_AC_2_a_typed_question_names_its_subject_cleanly_and_never_an_unrelated_view(self):
        p = self.released()
        out = self.ask(p.pid, "why is cost not measured?")
        self.assertTrue(out["answer"].startswith("Cost is not measured because the runs recorded no token counts"),
                        out["answer"])
        self.assertEqual(out["fill"]["view"], "models")
        out = self.ask(p.pid, "why is the cost empty?")
        self.assertTrue(out["answer"].startswith("Cost is empty because the runs recorded"), out["answer"])
        self.assertNotIn("Floor", out["answer"])
        out = self.ask(p.pid, "why is the cost per task on insights not measured?")
        self.assertTrue(out["answer"].startswith("Cost per task on Project insights is not measured"), out["answer"])
        # "the page" is the view the person is on; with none, the answer says so instead of naming Home
        out = self.ask(p.pid, "why is the page blank?", view="releases")
        self.assertTrue(out["answer"].startswith("Releases is not empty here"), out["answer"])
        status, out, _ = self.call("POST", "/api/assistant", {"question": "why is the page blank?",
                                                              "persona": "developer", "person": "Ida Example"})
        self.assertEqual(status, 200, out)
        self.assertTrue(out["answer"].startswith("This page: Rihmasto has no record"), out["answer"])
        self.assertNotIn("Home is empty", out["answer"])

    # -- AC-3: a failure asked about in general ---------------------------------------------------------------

    def test_FR_NVL2_AC_3_why_did_it_fail_is_answered_by_the_error_rules_from_the_last_failure_on_the_page(self):
        p = self.built_project()
        for question in ("why did it fail?", "why is it broken?", "why did my last action fail?"):
            out = self.ask(p.pid, question)
            self.assertEqual(out["by"], "why", question)
            self.assertEqual(out["why"]["kind"], "error", question)
            self.assertIn("no failure message came with the question", out["answer"])
            self.assertEqual(out["fill"]["view"], "incidents_all")
        out = self.ask(p.pid, "why did my last action fail?",
                       last_error={"message": "refused: the project is paused", "view": "tasks"})
        self.assertEqual((out["fill"]["view"], out["fill"]["control"]), ("overview", "resume"))
        self.assertIn('The message was: "refused: the project is paused"', out["answer"])
        self.assertEqual(out["who"]["how"], "by rule")
        # a named thing is left to the answers that know it; an empty question is not a failure
        self.assertIsNone(neverlost.chat_answer(self.factory, p, "Why did the gate fail on T-001?"))
        out = self.ask(p.pid, "why is the tasks view empty?", last_error={"message": "refused: the project is paused"})
        self.assertNotEqual(out["why"]["kind"], "error")

    # -- AC-4: a value not measured is named by its label and follows its own hint -----------------------------

    def test_FR_NVL2_AC_4_a_tile_not_measured_is_named_by_its_label_and_its_answer_follows_the_tiles_hint(self):
        p = self.built_project()
        out = self.why(p.pid, view="insights", kind="not_measured",
                       field="Checks failing· Not measuredNot measured: no check enabled Pin to Home",
                       basis="To measure it: turn on a check in the project's Health.")
        self.assertTrue(out["answer"].startswith("Checks failing on Project insights is not measured because "
                                                 "nothing has measured it yet: to measure it, turn on a check in the "
                                                 "project's Health."), out["answer"])
        self.assertNotIn("Pin to Home", out["answer"])
        self.assertEqual((out["fill"]["view"], out["fill"]["control"]), ("checks", "health_enable"))
        out = self.why(p.pid, view="insights", kind="not_measured", field="Median time to resolve",
                       basis="no incident resolved in the window. To measure it: resolve an incident.")
        self.assertEqual(out["fill"]["view"], "incidents")
        self.assertNotIn("Go on with the project", out["answer"])
        out = self.why(p.pid, view="insights", kind="not_measured", field="Probes answering")
        self.assertEqual(out["fill"]["control"], "health_enable")
        # a value sent with its reason as the name: the name is empty, the reason is the basis
        out = self.why(p.pid, view="overview", kind="not_measured", field=": no task finished yet")
        self.assertEqual(out["why"]["field"], "")
        self.assertEqual(out["why"]["basis"], "no task finished yet")
        self.assertFalse(out["answer"].startswith(":"))

    # -- AC-5: a run keeps the enforcement it ran under ---------------------------------------------------------

    def test_FR_NVL2_AC_5_each_run_carries_the_enforcement_in_force_when_it_ran_never_todays(self):
        p = self.built_project()
        self.clock.advance(minutes=5)
        status, out, _ = self.call("PUT", f"/api/projects/{p.pid}/harness-enforcement", {"on": False, "reason": "a trial",
                                                                                   **DEV})
        self.assertEqual(status, 200, out)
        first = who_acted.runs(self.factory, p)[0]
        self.assertEqual((first["id"], first["applied"], first["opted_out"]), ("T-001/0", True, False))
        self.assertIn("in-run policy enforced by Gnomon", first["gnomon"])
        self.assertNotIn("opted out", first["gnomon"])
        # a build attempt and a model call made while opted out say so, and only they
        self.clock.advance(minutes=5)
        tasks = p.read("tasks.json")
        tasks.setdefault("T-002", {"status": "building"})["rounds"] = [{"round": 0, "cell": {"model": "m"}, "gate": {"verdict": "passed"}}]
        p.path("tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
        p.log("cell_ran", {"task": "T-002", "round": 0, "head": "abc"})
        p.log("model_run", {"role": "verifier", "model": "m", "task": "T-002"})
        rows = {r["id"]: r for r in who_acted.runs(self.factory, p)}
        late = rows["T-002/0"]
        self.assertEqual((late["applied"], late["opted_out"]), (False, True))
        self.assertIn("Gnomon ran it without its in-run policy", late["gnomon"])
        self.assertIn("when it ran, Gnomon's enforcement was off for this project: opted out by Ida Example",
                      late["gnomon"])
        self.assertNotIn("in-run policy enforced by Gnomon", late["gnomon"])
        model = [r for r in rows.values() if r["id"].startswith("M-")][-1]
        self.assertEqual((model["applied"], model["opted_out"]), (False, True))
        # turning it back on changes no past run
        self.clock.advance(minutes=5)
        self.call("PUT", f"/api/projects/{p.pid}/harness-enforcement", {"on": True, **DEV})
        rows = {r["id"]: r for r in who_acted.runs(self.factory, p)}
        self.assertTrue(rows["T-001/0"]["applied"])
        self.assertTrue(rows["T-002/0"]["opted_out"])
        # the platform's opt-out counts by time, for a project with no setting of its own
        q = self.built_project()
        self.clock.advance(minutes=5)
        status, out, _ = self.call("PUT", "/api/harness-enforcement", {"on": False, "reason": "a harness trial",
                                                                 "person": "Ilkka", "persona": "it"})
        self.assertEqual(status, 200, out)
        self.assertTrue(who_acted.runs(self.factory, q)[0]["applied"])
        self.clock.advance(minutes=5)
        q.log("model_run", {"role": "analyst", "model": "m"})
        self.assertIn("off for the platform", who_acted.runs(self.factory, q)[-1]["gnomon"])

    # -- AC-6: the proposal holds only what the persona may decide ----------------------------------------------

    def test_FR_NVL2_AC_6_a_persona_that_may_not_decide_is_offered_nothing_and_its_confirm_is_refused_with_why(self):
        asking = self.built_project()                       # two changes: a business or product owner decides each
        for title in ("Show overdue loans first", "Send a reminder a day before"):
            Canon(asking).card("change", title, refs={"requirements": ["R-1"]})
        status, t, _ = self.call("GET", f"/api/projects/{asking.pid}/triage?persona=stakeholder")
        self.assertEqual(status, 200, t)
        self.assertEqual(t["proposal"]["count"], 0)
        self.assertEqual(t["proposal"]["refused"], 2)
        self.assertTrue(all("a stakeholder may not decide this" in r["assume"]["said"] for r in t["rest"]
                            if r["assume"].get("refused")))
        self.assertIn("as stakeholder you may not decide them", t["said"])
        self.assertNotIn("I propose", t["said"])
        status, out, _ = self.call("POST", f"/api/projects/{asking.pid}/triage/assume",
                                   {"person": "Sanna", "persona": "stakeholder"})
        self.assertEqual(status, 403, out)
        self.assertIn("a stakeholder may not decide this", out["error"])
        self.assertEqual(asking.ledger().of_kind("triage_assumed"), [])
        # Ask Rihma offers the same: nothing to confirm for a stakeholder, everything for a business owner
        out = self.ask(asking.pid, "I have 50 decisions: what blocks work? assume the rest", persona="stakeholder")
        self.assertEqual(out["triage"]["proposal"]["count"], 0)
        out = self.ask(asking.pid, "I have 50 decisions: what blocks work? assume the rest", persona="business_owner")
        self.assertTrue(out["triage"]["proposal"]["count"])
        self.assertEqual(triage.triage(asking)["proposal"]["count"], out["triage"]["proposal"]["count"])

    # -- AC-7: the chat rules take only their own questions ----------------------------------------------------

    def test_FR_NVL2_AC_7_ordinary_questions_are_not_taken_by_the_triage_harness_or_who_acted_rules(self):
        p = self.built_project()
        for question in ("why do assumptions matter?", "what is an assumption and why is it important?",
                         "how do I enforce a review before merge?", "is access enforced on this project?"):
            self.assertIsNone(neverlost_chat.answer(self.factory, p, question), question)
            self.assertNotIn(self.ask(p.pid, question)["by"], ("triage", "why"), question)
        for question, by in (("Which assumptions grew in importance?", "triage"),
                             ("If I change harness, does Gnomon still enforce its structure?", "rule"),
                             ("can I opt out of Gnomon's enforcement?", "rule")):
            self.assertEqual(neverlost_chat.answer(self.factory, p, question)["by"], by, question)
        p.log("model_run", {"role": "verifier", "model": "m", "task": "T-001"})
        out = self.ask(p.pid, "who acted on T-002?")
        self.assertIn("No run is recorded on T-002 yet", out["answer"])
        out = self.ask(p.pid, "who acted on T-001?")
        self.assertIn("on T-001", out["answer"])
        self.assertIn("Build T-001, attempt 1", out["answer"])
        self.assertNotIn("T-002", out["answer"])

    # -- AC-8: the owner's 50 decisions, across projects ----------------------------------------------------------

    def test_FR_NVL2_AC_8_from_home_the_blocking_decisions_are_ranked_across_projects_with_one_proposal(self):
        one = self.intake_project(mode="socratic")
        two = self.intake_project(mode="socratic")
        built = self.built_project()
        Canon(built).card("incident", "Production is down", refs={})
        t = triage_all.across(self.factory, "business_owner")
        self.assertEqual(t["blocking"][0]["kind"], "incident")             # what stops most work first
        self.assertEqual(t["blocking"][0]["project"], built.pid)
        self.assertEqual({b["project"] for b in t["blocking"]}, {one.pid, two.pid, built.pid})
        self.assertEqual([b["rank"] for b in t["blocking"]], list(range(1, len(t["blocking"]) + 1)))
        self.assertEqual({x["project"] for x in t["proposal"]["projects"]}, {one.pid, two.pid})
        self.assertEqual(t["proposal"]["count"], sum(x["count"] for x in t["proposal"]["projects"]))
        self.assertIn(f"I propose to assume the other {t['proposal']['count']} across 2 projects", t["said"])
        status, out, _ = self.call("GET", "/api/triage?persona=business_owner")
        self.assertEqual((status, out["proposal"]["count"]), (200, t["proposal"]["count"]))
        status, out, _ = self.call("POST", "/api/assistant", {"question": "I have 50 decisions: what blocks work? "
                                                              "assume the rest", "persona": "business_owner",
                                                              "person": "Aino"})
        self.assertEqual((status, out["by"], out["navigate"]["route"]), (200, "triage", "#/triage"))
        self.assertEqual(out["triage_all"]["proposal"]["count"], t["proposal"]["count"])
        self.assertNotIn("Open a project", out["answer"])
        # confirming it is each project's own confirm, signed and recorded in each
        for part in out["triage_all"]["proposal"]["projects"]:
            status, done, _ = self.call("POST", f"/api/projects/{part['project']}/triage/assume",
                                        {"person": "Aino", "persona": "business_owner", "cards": part["cards"]})
            self.assertEqual(status, 200, done)
            self.assertEqual(sorted(done["assumed"] + done["deferred"]), sorted(part["cards"]))
        self.assertEqual(triage_all.across(self.factory, "business_owner")["proposal"]["count"], 0)
        status, out, _ = self.call("GET", "/api/triage?persona=nobody")
        self.assertEqual((status, out["persona"]), (200, None))


if __name__ == "__main__":
    unittest.main()
