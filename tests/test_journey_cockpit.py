"""FR-JRN1's cockpit API: guided-journey reads write nothing; guide writes are signed and validated."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_cockpit import CockpitTestCase  # noqa: E402
from test_guided_journeys import PERSON, PERSONA, adopted_project  # noqa: E402

from kernel.learn import factory_project  # noqa: E402

WHO = {"person": PERSON, "persona": PERSONA}


class JourneyCockpitTest(CockpitTestCase):
    def post(self, path: str, body: dict, status: int = 200, **kwargs) -> dict:
        got, out, _ = self.call("POST", path, {**WHO, **body}, **kwargs)
        self.assertEqual(got, status, out)
        return out

    def tree(self) -> dict[str, bytes]:
        return {str(p.relative_to(self.factory.home)): p.read_bytes()
                for p in self.factory.home.rglob("*") if p.is_file()} if self.factory.home.exists() else {}

    def test_FR_JRN1_AC_5_catalogue_next_and_guide_reads_write_nothing(self):
        before = self.tree()
        status, out, _ = self.call("GET", "/api/journeys?persona=business_owner")
        self.assertEqual(status, 200, out)
        self.assertEqual(out["starters"], ["brownfield", "new_idea", "documents"])
        self.assertEqual(len(out["journeys"]), 7)
        self.assertEqual(out["journeys"][0]["label"], "Bring in a system we already have")
        status, out, _ = self.call("GET", "/api/journeys/next")
        self.assertEqual(status, 200, out)
        self.assertEqual([j["name"] for j in out["starters"]], ["brownfield", "new_idea", "documents"])
        self.assertEqual(self.call("GET", "/api/journeys/guide?person=Aino%20Example")[1], {"guide": None})
        self.assertEqual(self.call("GET", "/api/journeys/guide")[1], {"guide": None})
        self.assertEqual(self.tree(), before)

        p = adopted_project(self)
        before = self.tree()
        status, out, _ = self.call("GET", f"/api/journeys/next?project={p.pid}&persona=developer")
        self.assertEqual(status, 200, out)
        self.assertEqual(out["journey"]["next"], "checks")
        step = next(s for s in out["journey"]["steps"] if s["id"] == "checks")
        self.assertEqual(step["action"]["do"], "watch")
        self.assertEqual(out["guide"], {"journey": "brownfield", "project": p.pid})
        self.assertEqual(self.tree(), before)
        status, out, _ = self.call("GET", "/api/journeys/next?project=missing")
        self.assertEqual(status, 404, out)

    def test_FR_JRN1_AC_5_start_mark_attach_stop_and_resume_through_the_real_routes(self):
        out = self.post("/api/journeys/guide", {"action": "start", "journey": "brownfield"}, 201)
        self.assertEqual(out["guide"]["guide"]["journey"], "brownfield")
        self.assertEqual(out["guide"]["progress"]["next"], "folder")
        self.assertEqual(self.call("GET", "/api/journeys/guide?person=Ville%20Example")[1], {"guide": None})

        out = self.post("/api/journeys/guide", {"action": "skip", "step": "folder"})
        self.assertEqual(out["guide"]["progress"]["next"], "scan")
        self.assertEqual(out["guide"]["progress"]["steps"][0]["state"], "skipped")
        p = self.new(title="Orders")
        out = self.post("/api/journeys/guide", {"action": "project", "project": p.pid})
        self.assertEqual(out["guide"]["progress"]["project"], p.pid)
        out = self.post("/api/journeys/guide", {"action": "stop"})
        self.assertEqual(out["guide"]["guide"]["state"], "stopped")
        self.assertEqual(self.call("GET", f"/api/journeys/guide?person={PERSON.replace(' ', '%20')}")[1]
                         ["guide"]["guide"]["state"], "stopped")
        out = self.post("/api/journeys/guide", {"action": "start", "journey": "brownfield", "project": p.pid}, 201)
        self.assertEqual(out["guide"]["guide"]["marks"], {})
        kinds = [r["event"]["kind"] for r in factory_project(self.factory).ledger().records()
                 if r["event"]["kind"].startswith("journey_")]
        self.assertEqual(kinds, ["journey_started", "journey_step", "journey_step", "journey_ended",
                                 "journey_started"])

    def test_FR_JRN1_AC_6_bad_actions_projects_steps_and_identities_are_refused_without_a_state_change(self):
        for body, status in (
            ({"action": "start", "journey": "unknown"}, 400),
            ({"action": "start", "journey": 12}, 400),
            ({"action": "start", "journey": "brownfield", "person": "factory"}, 403),
            ({"action": "start", "journey": "brownfield", "persona": "unknown"}, 403),
            ({"action": "start", "journey": "brownfield", "project": "missing"}, 400),
            ({"action": "unknown"}, 400),
            ({"action": "stop"}, 409),
        ):
            self.post("/api/journeys/guide", body, status)
        self.assertEqual(self.call("GET", f"/api/journeys/guide?person={PERSON.replace(' ', '%20')}")[1],
                         {"guide": None})
        self.post("/api/journeys/guide", {"action": "start", "journey": "ide"}, 201)
        before = self.tree()
        self.post("/api/journeys/guide", {"action": "did", "step": "unknown"}, 400)
        self.post("/api/journeys/guide", {"action": "did", "step": 12}, 400)
        self.assertEqual(self.tree(), before)

    def test_FR_JRN1_AC_6_guide_writes_need_the_cockpit_session_and_its_own_origin(self):
        body = {"action": "start", "journey": "brownfield"}
        self.post("/api/journeys/guide", body, 401, token=None)
        self.post("/api/journeys/guide", body, 401, token="not-a-session")
        self.post("/api/journeys/guide", body, 403, origin="http://evil.example")
        self.post("/api/journeys/guide", body, 403, origin=None)
        self.assertEqual(self.call("GET", f"/api/journeys/guide?person={PERSON.replace(' ', '%20')}")[1],
                         {"guide": None})


if __name__ == "__main__":
    unittest.main()
