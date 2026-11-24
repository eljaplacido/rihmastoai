"""The cockpit's routes for autopilot, delegation and staying on track (FR-AP2-AC-5, FR-AP3-AC-4).

Every write is signed with a person and a persona and goes through the kernel, which refuses what it
does not allow; the reads write nothing. The job runner here starts nothing and records what it was asked.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import delegation, roads  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.learn import factory_project  # noqa: E402

AINO = {"person": "Aino", "persona": "developer"}


class TrackRoutesTest(CockpitTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(roads.stop_started)

    def ledgers(self):
        return {p.pid: len(p.ledger().records()) for p in self.factory.projects()}

    def test_FR_AP3_AC_4_the_cockpit_reads_the_track_on_the_project_the_dashboard_and_its_own_route(self):
        p = self.intake_project()
        before = self.ledgers()
        status, out, _ = self.call("GET", f"/api/projects/{p.pid}/track")
        self.assertEqual(status, 200, out)
        self.assertEqual(out["track"]["state"], "not_measured")
        self.assertEqual(out["track"]["figures"]["blocking"]["value"], 1)
        self.assertFalse(out["autopilot"]["holding"])
        status, proj, _ = self.call("GET", f"/api/projects/{p.pid}")
        self.assertEqual(proj["track"]["state"], "not_measured")
        status, dash, _ = self.call("GET", "/api/dashboard")
        self.assertEqual([r["project"] for r in dash["track"]["projects"]], [p.pid])
        self.assertIn(("track", "M"), [tuple(x.values()) for x in self.call("GET", "/api/meta")[1]["lens_defaults"]
                                       ["business"]])
        self.assertEqual(self.ledgers(), before)                              # a read records nothing
        factory_project(self.factory)
        status, out, _ = self.call("GET", "/api/projects/_factory/track")
        self.assertEqual((status, out["track"]["state"]), (200, "not_measured"))       # the factory has no plan

    def test_FR_AP2_AC_5_a_person_starts_and_stops_an_autopilot_and_revokes_a_delegation_signed_through_the_kernel(self):
        p = self.intake_project()
        base = f"/api/projects/{p.pid}"
        status, out, _ = self.call("POST", base + "/autopilot", {"kinds": ["question", "trust"], "until": "8h", **AINO})
        self.assertEqual(status, 403, out)
        self.assertIn("never delegated", out["error"])
        status, out, _ = self.call("POST", base + "/autopilot", {"kinds": ["question"], "until": "8h",
                                                                  "person": "Sam", "persona": "stakeholder"})
        self.assertEqual(status, 403, out)
        status, out, _ = self.call("POST", base + "/autopilot", {"kinds": ["question", "escalation"], "until": "8h",
                                                                  "reason": "try it overnight", **AINO})
        self.assertEqual(status, 201, out)
        self.assertEqual((out["run"]["id"], out["run"]["person"], out["job"]["kind"]), ("AP-001", "Aino", "autopilot"))
        self.assertEqual(self.runner.started[-1][1], ["-m", "kernel.cli", "autopilot", "run", p.pid])
        audit = [r["event"]["payload"] for r in p.ledger().of_kind("cockpit_write")]
        self.assertEqual((audit[-1]["action"], audit[-1]["person"]), ("autopilot_start", "Aino"))
        self.assertEqual(self.call("POST", base + "/autopilot", {"kinds": ["question"], "until": "8h", **AINO})[0], 409)
        self.runner.states = {k: "done" for k in self.runner.states}
        self.assertEqual(self.call("POST", base + "/autopilot", {"kinds": ["question"], "until": "8h", **AINO})[0], 403)
        # a second delegation, revoked by a person who may decide its kind
        d = delegation.grant(p, ["approval"], person="Ida", persona="product_owner", until="1d")
        self.assertEqual(self.call("POST", base + f"/delegations/{d['id']}/revoke",
                                   {"person": "Sam", "persona": "stakeholder"})[0], 403)
        status, out, _ = self.call("POST", base + f"/delegations/{d['id']}/revoke", AINO)
        self.assertEqual((status, out["delegation"]["state"]), (200, "revoked"))
        self.assertEqual(self.call("POST", base + "/delegations/DL-099/revoke", AINO)[0], 404)
        status, out, _ = self.call("POST", base + "/autopilot/stop", {"reason": "back", "person": "Ida",
                                                                       "persona": "business_owner"})
        self.assertEqual((status, out["run"]["state"]), (200, "stopped"))
        self.assertEqual([x["state"] for x in delegation.delegations(p)], ["revoked", "revoked"])
        self.assertEqual(self.call("POST", base + "/autopilot/stop", AINO)[0], 403)   # nothing holds it now

    def test_FR_AP4_AC_1_the_cockpits_stop_says_the_autopilot_job_under_way_ends_at_its_next_safe_point(self):
        p = self.intake_project()
        base = f"/api/projects/{p.pid}"
        status, out, _ = self.call("POST", base + "/autopilot", {"kinds": ["question"], "until": "8h", **AINO})
        self.assertEqual(status, 201, out)
        job_id = out["job"]["id"]
        status, out, _ = self.call("POST", base + "/autopilot/stop", AINO)
        self.assertEqual((status, out["run"]["state"]), (200, "stopped"))
        self.assertEqual((out["job"]["id"], out["job"]["kind"], out["job"]["state"]), (job_id, "autopilot", "running"))
        self.assertIn("delivers nothing and ends at its next safe point", out["job"]["ending"])
        self.runner.states = {k: "done" for k in self.runner.states}       # the job ended at its safe point
        self.assertEqual(self.call("POST", base + "/autopilot", {"kinds": ["question"], "until": "8h", **AINO})[0], 201)
        self.runner.states = {k: "done" for k in self.runner.states}       # its passes are over
        status, out, _ = self.call("POST", base + "/autopilot/stop", AINO)
        self.assertEqual((status, out["job"]), (200, None))                 # no job under way: nothing to end

    def test_FR_AP3_AC_3_a_plan_owner_sets_checkpoints_in_the_cockpit_and_a_person_records_a_look(self):
        p = self.intake_project()
        base = f"/api/projects/{p.pid}"
        self.assertEqual(self.call("PUT", base + "/tracking", {"checkpoints": [2], "person": "Sam",
                                                                "persona": "stakeholder"})[0], 403)
        self.assertEqual(self.call("PUT", base + "/tracking", {"checkpoints": ["2"], **AINO})[0], 400)
        self.assertEqual(self.call("PUT", base + "/tracking", {"due": "next week", **AINO})[0], 400)
        status, out, _ = self.call("PUT", base + "/tracking", {"checkpoints": [2, 5], "hold": True, "due": "2026-12-31",
                                                                "budget": 250, **AINO})
        self.assertEqual(status, 200, out)
        self.assertEqual((out["settings"]["checkpoints"], out["settings"]["budget"]),
                         ([2, 5], {"due": "2026-12-31", "amount": 250.0}))
        self.assertEqual(out["track"]["due"], [2])
        self.assertEqual(self.call("POST", base + "/checkpoints/5/look", AINO)[0], 403)   # not reached
        status, out, _ = self.call("POST", base + "/checkpoints/2/look", {"note": "questions read", **AINO})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["checkpoints"]["due"], [])
        looked = p.ledger().of_kind("checkpoint_looked")[-1]["event"]["payload"]
        self.assertEqual((looked["person"], looked["persona"], looked["note"]), ("Aino", "developer", "questions read"))
        self.assertEqual(Canon(p).question("Q-001")["status"], "open")        # a look decides nothing


if __name__ == "__main__":
    unittest.main()
