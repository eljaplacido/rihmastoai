"""FR-BIZ1: what the business acceptance test found, fixed and held. The Evidence view's controls match the pack it
exports; signed answers from people in the loop count as human oversight in the pack; the activity feed shows who
asked whom, who answered from outside and who changed enforcement where; a nudge's link points at the cockpit that
sent it; the business lens says risks are not assessed before an assessment; asks wait in Decisions waiting and on
every persona's Home; one account of what is live; a project in shaping is not "all build work done"; a link not
sent says so; and the Assumptions view shows each assumption's weight. The browser half is
tests/test_acc_business_ui.py. Nothing is sent anywhere but a stand-in."""

import json
import os
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from adapters import sarif  # noqa: E402
from kernel import dashboard, hitl, hitl_links, hitl_nudge, relay, understanding  # noqa: E402
from kernel.evidence_pack import attestation, export  # noqa: E402
from kernel.status import health  # noqa: E402

AINO = {"person": "Aino Example", "persona": "business_owner"}
KAISA = {"person": "Kaisa Example", "persona": "compliance"}
SARIF = {"version": "2.1.0", "runs": [{
    "tool": {"driver": {"name": "Example Scanner", "version": "1.0.0",
                        "rules": [{"id": "EX-1", "defaultConfiguration": {"level": "warning"}}]}},
    "invocations": [{"executionSuccessful": True}],
    "results": [{"ruleId": "EX-1", "level": "warning", "message": {"text": "A header is missing"},
                 "locations": [{"physicalLocation": {"artifactLocation": {"uri": "app/routes.py"},
                                                     "region": {"startLine": 1}}}]}]}]}


def scanned(case, p):
    path = case.tmp / "scan.sarif"
    path.write_text(json.dumps(SARIF), encoding="utf-8")
    return sarif.ingest(p, path, person="Dana Example", persona="developer")


def loop(p):
    """A governance decision answered inside, a legal question answered from outside by a link, and a level set
    for all projects."""
    hitl.ask(p, text="May the pilot start on Monday?", kind="decision", family="governance", options=["Yes", "No"],
             **AINO)
    hitl.answer(p, "HQ-001", answer="Yes", **KAISA)
    hitl.ask(p, text="May we keep the loan history for two years?", family="legal", **AINO)
    link = hitl_links.create(p, name="Maria Example", persona="compliance", asks=["HQ-002"], person="Aino Example",
                             creator_persona="business_owner", role="External legal counsel")
    hitl_links.answer(p.factory, hitl_links.links(p.factory)[0], "HQ-002", "Two years is within the limit")
    hitl.set_level(p, "legal", "require", scope="platform", **KAISA)
    return link


class EvidenceViewTest(CockpitTestCase):
    def test_FR_BIZ1_AC_1_the_evidence_views_controls_name_the_scan_the_exported_pack_names(self):
        p = self.new(title="Shipment webhook")
        scanned(self, p)
        status, att, _ = self.call("GET", f"/api/projects/{p.pid}/attestation")
        self.assertEqual(status, 200, att)
        by = {c["control"]: c["by"] for c in att["controls"]}
        self.assertIn("security.json: the latest scan by `Example Scanner 1.0.0`", by["ai-act:art15"])
        self.assertNotIn("no security scan yet", by["ai-act:art15"])
        self.assertNotIn("no vulnerability handling evidence yet", by["nis2:art21"])
        path = export(p, self.tmp / "out", person="Kaisa Example", persona="compliance")
        with zipfile.ZipFile(path) as z:
            packed = {c["control"]: c["by"] for c in json.loads(z.read("attestation.json"))["controls"]}
        self.assertEqual(by, packed)                                        # the page and its pack say the same


class LoopEvidenceTest(CockpitTestCase):
    def test_FR_BIZ1_AC_2_signed_answers_from_people_in_the_loop_count_as_human_oversight_in_the_pack(self):
        p = self.new(title="Shipment webhook")
        loop(p)
        path = export(p, self.tmp / "out", person="Kaisa Example", persona="compliance")
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            people = json.loads(z.read("people-in-the-loop.json"))
            readme = z.read("README.md").decode("utf-8")
            att = json.loads(z.read("attestation.json"))
        self.assertIn("people-in-the-loop.json", names)
        self.assertEqual([a["ask"] for a in people["answers"]], ["HQ-001", "HQ-002"])
        outside = people["answers"][1]
        self.assertEqual((outside["person"], outside["external"], outside["via"]), ("Maria Example", True, "RL-001"))
        self.assertEqual([e["scope"] for e in people["enforcement"]], ["platform"])
        self.assertIn("- Decisions by people: 2 (0 in `decisions.json`, 2 signed answer(s) from people in the loop in "
                      "`people-in-the-loop.json`, 1 of them from outside).", readme)
        art14 = next(c for c in att["controls"] if c["control"] == "ai-act:art14")
        self.assertIn("people-in-the-loop.json: 2 signed answer(s) from people in the loop (1 from outside",
                      art14["by"])
        self.assertIn("people-in-the-loop.json", next(line for line in readme.splitlines()
                                                      if line.startswith("| `ai-act:art14`")))
        status, view, _ = self.call("GET", f"/api/projects/{p.pid}/attestation")    # the Evidence view counts them
        self.assertEqual((status, view["decisions"], view["answers"]), (200, 0, 2))

    def test_FR_BIZ1_AC_2_a_pack_with_no_answer_says_what_it_said_before(self):
        files = {"ledger-check.json": {"intact": True}, "gnomon-runs.json": [], "capability-pack.json": {},
                 "decisions.json": [], "evidence.json": []}
        art14 = next(c for c in attestation(files)["controls"] if c["control"] == "ai-act:art14")
        self.assertTrue(art14["by"].startswith("decisions.json: every decision signed by a named person and persona;"))
        self.assertNotIn("people-in-the-loop", art14["by"])


class ActivityTest(FactoryTestCase):
    def test_FR_BIZ1_AC_3_the_activity_feed_shows_asks_outside_answers_links_and_enforcement_with_its_scope(self):
        p = self.new(title="Shipment webhook")
        loop(p)
        rows = {(e["kind"], e["summary"]): e["actor"] for e in dashboard.activity(self.factory)}
        self.assertIn(("hitl_asked", "asked compliance (governance decision HQ-001)"), rows)
        self.assertIn(("hitl_answered", "answered HQ-001"), rows)
        outside = rows[("hitl_answered", "answered HQ-002, from outside via RL-001")]
        self.assertEqual(outside, {"type": "person", "name": "Maria Example", "persona": "compliance", "outside": True})
        self.assertIn(("hitl_link_given", "gave Maria Example a one-use link (RL-001) for HQ-002"), rows)
        self.assertEqual(rows[("hitl_enforcement_set", "set legal checks to must answer before delivery for all "
                                                       "projects")]["name"], "Kaisa Example")


class NudgeLinkTest(CockpitTestCase):
    def test_FR_BIZ1_AC_4_a_nudge_card_points_at_the_cockpit_that_sent_it_unless_IT_set_one(self):
        p = self.new(title="Shipment webhook")
        hitl.set_level(p, "governance", "require", **AINO)            # a required ask is reminded, solo too
        hitl.ask(p, text="May the pilot start on Monday?", kind="decision", family="governance",
                 options=["Yes", "No"], **AINO)
        relay.subscribe(self.factory, sink="teams", url_env="TEAMS_STANDIN", personas=["compliance"], person="Ilkka",
                        persona="it")
        self.clock.advance(hours=26)
        posted = []

        def post(url, body, headers):
            posted.append(json.loads(body))
            return 200

        with mock.patch.dict(os.environ, {"TEAMS_STANDIN": "http://127.0.0.1:9/teams"}), \
                mock.patch.object(relay, "post_json", post):
            status, out, _ = self.call("POST", f"/api/projects/{p.pid}/hitl/nudge", AINO)
        self.assertEqual((status, out["count"]), (200, 1), out)
        card = json.dumps(posted[0])
        self.assertIn(f"{self.origin}/#/p/{p.pid}/loop", card)
        self.assertNotIn("127.0.0.1:8787", card)
        relay.set_cockpit(self.factory, "https://rihmasto.example.org", person="Ilkka", persona="it")
        sent = []
        self.clock.advance(hours=60)                                        # the escalate step, with IT's address
        hitl_nudge.nudge(p, base="", environ={"TEAMS_STANDIN": "http://127.0.0.1:9/teams"}, solo=False,
                         post=lambda u, b, h: sent.append(b.decode()) or 200, cockpit=self.origin, **AINO)
        self.assertIn(f"https://rihmasto.example.org/#/p/{p.pid}/loop", sent[0])


class LensTest(FactoryTestCase):
    def test_FR_BIZ1_AC_5_before_an_assessment_the_business_lens_says_its_risks_are_not_assessed(self):
        p = self.new(title="Stock levels service")
        p.update_meta(source_kind="adopted", intent="maintain", maturity="production")
        u = {"contract": None}
        lens = understanding.lenses(p, u)
        self.assertEqual((lens["business"]["assessed"], lens["compliance"]["assessed"]), (False, False))
        self.assertEqual(lens["business"]["risks"], [])
        p.write("inventory.json", {"files": 2, "languages": [{"language": "Python", "files": 2}], "tests": {},
                                   "readme": None, "routes": [],
                                   "dockerfile": {"present": False, "files": []}})
        said = understanding.answer(p)["answer"]                           # Ask Rihma says the same
        self.assertIn("its risks are not assessed yet (Run the assessment to see them)", said)


class WaitingTest(CockpitTestCase):
    def test_FR_BIZ1_AC_6_a_required_ask_waits_in_decisions_and_on_the_compliance_home(self):
        p = self.new(title="Shipment webhook")
        hitl.set_level(p, "legal", "require", **AINO)
        hitl.ask(p, text="May we keep the loan history for two years?", family="legal", **AINO)
        before = self.call("GET", "/api/dashboard")[1]
        asks = [d for d in before["decisions"] if d["kind"] == "ask"]
        self.assertEqual([(a["card"], a["deciders"], a["blocking"]) for a in asks], [("HQ-001", ["compliance"], True)])
        self.assertEqual(before["kpis"]["decisions"]["value"], len(before["decisions"]))
        status, out, _ = self.call("GET", "/api/layout?persona=compliance&lens=compliance&person=Kaisa+Example")
        self.assertEqual(status, 200, out)
        self.assertIn("decisions", [w["type"] for w in out["layout"]["widgets"]])


class LiveTest(CockpitTestCase):
    def test_FR_BIZ1_AC_7_live_and_in_use_counts_an_adopted_system_in_production_of_the_same_projects(self):
        stock = self.new(title="Stock levels service")
        stock.update_meta(source_kind="adopted", intent="maintain", maturity="production")
        self.new(title="Equipment loans")
        self.assertEqual(dashboard.catalogue_state(stock), "in_use")
        k = self.call("GET", "/api/dashboard")[1]["kpis"]
        self.assertEqual((k["in_use"]["value"], k["in_use"]["of"]), (1, k["in_flight"]["of"]))
        self.assertIn("live_to_try", k["in_use"])


class ShapingTest(FactoryTestCase):
    def test_FR_BIZ1_AC_8_a_project_with_no_plan_has_no_tasks_rather_than_all_of_them_done(self):
        p = self.new(title="Equipment loans")
        f = health(p)["forecast"]
        self.assertEqual((f["tasks_left"], f["tasks_total"]), (0, 0))


class LinkSentTest(CockpitTestCase):
    def test_FR_BIZ1_AC_9_a_link_meant_for_email_that_was_not_sent_says_so(self):
        p = self.new(title="Shipment webhook")
        hitl.ask(p, text="May we keep the loan history for two years?", family="legal", **AINO)
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/hitl/links",
                                   {"name": "Maria Example", "asks": ["HQ-001"], "channel": "email",
                                    "address": "maria@example.org"} | AINO)
        self.assertEqual(status, 201, out)
        self.assertIn("Not sent by email", out["said"])
        view = self.call("GET", f"/api/projects/{p.pid}/hitl")[1]
        self.assertEqual((view["links"][0]["channel"], view["links"][0]["delivered"]), ("email", False))


class WeightTest(CockpitTestCase):
    def test_FR_BIZ1_AC_10_the_assumptions_view_carries_each_open_assumptions_weight(self):
        from kernel.assumption_weight import weights

        p = self.built_project(mode="assume")
        weighed = {w["id"]: w for w in weights(p)}
        self.assertTrue(weighed)
        view = self.call("GET", f"/api/projects/{p.pid}")[1]
        rows = {a["id"]: a for a in view["assumptions"] if a["id"] in weighed}
        self.assertEqual({k: (r["weight"], r["grew"]) for k, r in rows.items()},
                         {k: (w["weight"], w["grew"]) for k, w in weighed.items()})


if __name__ == "__main__":
    unittest.main()
