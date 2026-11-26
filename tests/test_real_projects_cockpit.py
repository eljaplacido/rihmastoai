"""FR-RPJ1 in the cockpit's routes: the scan in the background with its progress, Cancel and refusals; the
folders the cockpit may read; adopting the working copy, documents and again; a local model for a confidential
project's roles; and an adopted project's state, areas, watch and stated baseline.
"""

import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rpj_fixture as fx  # noqa: E402
from factory_fakes import isolated_routing  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import adopt  # noqa: E402
from kernel.material import Progress  # noqa: E402
from kernel.source_guard import ROOTS_ENV  # noqa: E402

WHO = {"person": "Aino Tester", "persona": "developer"}


class RealProjectsCockpitTest(CockpitTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {ROOTS_ENV: str(self.tmp)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def scan(self, folder, **more):
        status, body, _ = self.call("POST", "/api/source/scan", {"source": str(folder), **WHO, **more})
        self.assertIn(status, (200, 202), body)
        scan = body["scan"]
        end = time.monotonic() + 60
        while scan["state"] == "running" and time.monotonic() < end:
            time.sleep(0.1)
            scan = self.call("GET", f"/api/source/scan/{scan['id']}")[1]["scan"]
        return scan

    def test_FR_RPJ1_AC_7_the_scan_runs_in_the_background_and_a_refusal_is_its_state(self):
        scan = self.scan(fx.notes(self.tmp / "vault"))
        self.assertEqual(scan["state"], "done", scan)
        self.assertEqual(scan["progress"]["files"], 9)
        self.assertEqual(scan["result"]["map"]["totals"]["files"], 9)
        status, body, _ = self.call("POST", "/api/source/scan", {"source": "C:/Windows" if os.name == "nt" else "/etc",
                                                                  **WHO})
        self.assertEqual(status, 200)                    # never a 403 in the console: the step says why
        self.assertEqual(body["scan"]["state"], "refused")
        self.assertIn("system folder", body["scan"]["error"])
        self.assertIsNone(body["scan"]["offer"])
        status, body, _ = self.call("POST", "/api/source/scan", {"source": str(self.tmp), "person": "x", "persona": "x"})
        self.assertEqual(status, 403, body)
        job = {"id": "S-000000000000", "state": "running", "progress": Progress(), "folder": "x"}   # a long scan
        self.server._rpj_scans = {"S-000000000000": job}
        self.server._rpj_lock = threading.Lock()
        status, body, _ = self.call("POST", "/api/source/scan/S-000000000000/cancel", WHO)
        self.assertEqual(status, 200, body)
        self.assertTrue(job["progress"].cancelled)

    def test_FR_RPJ1_AC_8_a_folder_outside_is_offered_and_allowed_without_a_restart(self):
        with mock.patch("pathlib.Path.home", return_value=self.tmp / "me"), \
                mock.patch.dict(os.environ, {ROOTS_ENV: str(self.tmp / "only")}):
            dev = self.tmp / "dev" / "app"
            dev.mkdir(parents=True)
            scan = self.scan(dev)
            self.assertEqual(scan["state"], "refused")
            self.assertEqual(scan["offer"]["who"], "you")
            status, body, _ = self.call("POST", "/api/source/roots", {"folder": str(self.tmp / "dev"), **WHO})
            self.assertEqual(status, 403)
            self.assertIn("say yes", body["error"])
            status, body, _ = self.call("POST", "/api/source/roots", {"folder": str(self.tmp / "dev"), "confirm": True,
                                                                       **WHO})
            self.assertEqual(status, 200, body)
            self.assertIn("allowed in Settings", [r["from"] for r in body["roots"]])
            self.assertEqual(self.scan(dev)["state"], "done")
            self.assertEqual(self.call("GET", "/api/source/roots")[1]["who"], "you, after saying yes")

    def test_FR_RPJ1_AC_3_the_preview_scans_what_will_be_adopted_and_adopt_takes_the_working_copy(self):
        repo = fx.uncommitted(self.tmp / "ledger")
        got = self.scan(repo)["result"]
        self.assertEqual((got["take"], got["changes"]), ("commit", {"uncommitted": 1, "untracked": 2}))
        self.assertNotIn("draft.md", [r["path"] for r in got["map"]["files"]])
        got = self.scan(repo, take="working_copy")["result"]
        self.assertIn("draft.md", [r["path"] for r in got["map"]["files"]])
        status, body, _ = self.call("POST", "/api/adopt", {"title": "Ledger", "source": str(repo), "intent": "maintain",
                                                            "take": "working_copy", "maturity": "pilot", **WHO})
        self.assertEqual(status, 201, body)
        args = self.runner.started[-1][1]
        self.assertIn("--working-copy", args)
        self.assertEqual(args[args.index("--maturity") + 1], "pilot")

    def test_FR_RPJ1_AC_4_an_adopted_folder_is_said_and_adopted_again_only_on_purpose(self):
        src = fx.game(self.tmp / "isles")
        p = adopt.adopt(self.factory, "Isles", source=str(src), intent="monitor", person=WHO["person"],
                        persona=WHO["persona"], suite_timeout=1)
        got = self.scan(src)["result"]
        self.assertEqual([(x["project"], x["by"]) for x in got["adopted_as"]], [(p.pid, "path")])
        body = {"title": "Isles again", "source": str(src), "intent": "monitor", **WHO}
        status, out, _ = self.call("POST", "/api/adopt", body)
        self.assertEqual(status, 409, out)
        self.assertIn("already adopted as Isles", out["error"])
        self.assertEqual(self.call("POST", "/api/adopt", {**body, "again": True})[0], 201)

    def test_FR_RPJ1_AC_6_a_workspace_is_listed_with_its_repositories(self):
        got = self.scan(fx.workspace(self.tmp / "harbour"))["result"]
        self.assertFalse(got["git"])
        self.assertEqual([r["path"] for r in got["workspace"]["repositories"]], ["harbour-app", "harbour-tools"])
        self.assertEqual(got["map"]["totals"]["duplicates"], 2)

    def test_FR_RPJ1_AC_15_a_documents_folder_is_offered_to_track_and_adopted_as_documents(self):
        src = fx.experiment(self.tmp / "buoys")
        got = self.scan(src)["result"]
        self.assertFalse(got["code"])
        self.assertEqual(got["usage"]["maturity"], "explore")
        body = {"title": "Buoys", "source": str(src), "intent": "monitor", **WHO}
        self.assertEqual(self.call("POST", "/api/adopt", body)[0], 400)            # no code: not without saying so
        status, out, _ = self.call("POST", "/api/adopt", {**body, "documents": True})
        self.assertEqual(status, 201, out)
        self.assertIn("--documents", self.runner.started[-1][1])

    def test_FR_RPJ1_AC_17_the_page_names_who_adopted_it_and_rihma_signs_commands_with_the_person(self):
        src = fx.experiment(self.tmp / "buoys")
        p = adopt.adopt(self.factory, "Buoys", source=str(src), intent="monitor", person=WHO["person"],
                        persona=WHO["persona"], documents=True, maturity="explore")
        status, body, _ = self.call("GET", f"/api/projects/{p.pid}")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["meta"]["requested_by"], WHO["person"])
        self.assertEqual([(t["id"], t["adopted"]) for t in body["tasks"]], [("T-001", True)])
        self.assertIn("not built or gated by the factory", body["tasks"][0]["note"])
        status, out, _ = self.call("POST", "/api/assistant", {"question": "how do I work on this in my terminal?",
                                                               "project": p.pid, **WHO})
        self.assertEqual(status, 200, out)
        self.assertIn(f'rihmasto workspace open {p.pid} --person "Aino Tester" --persona developer', out["answer"])
        self.assertNotIn("<your name>", out["answer"])

    def test_FR_RPJ1_AC_5_a_confidential_adoption_is_said_plainly_and_fixed_in_one_click(self):
        isolated_routing(self, self.tmp)
        got = self.scan(fx.notes(self.tmp / "vault"))["result"]
        said = got["confidential"]
        self.assertTrue(said["text"].startswith("Adopting works (it calls no model). These roles would be refused "
                                                "until they use a local model: analyst"))
        self.assertEqual(said["offer"]["roles"], ["analyst", "holdout_author", "builder"])
        self.assertIn("verifier", said["offer"]["left"])
        status, body, _ = self.call("POST", "/api/models/use-local", {"person": "Aino Tester", "persona": "it"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["used"]["still_hosted"], ["verifier"])
        self.assertTrue(body["confidential"]["text"].endswith("verifier (the hosted endpoint 'go', opencode.ai)."))
        from kernel.learn import factory_project

        sets = [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind("models_set")]
        self.assertEqual([s["role"] for s in sets], ["analyst", "holdout_author", "builder"])
        self.assertEqual(sets[0]["via"], "confidential: use my local model")

    def test_FR_RPJ1_AC_10_the_project_view_carries_its_adopted_state_areas_watch_and_stated_baseline(self):
        p = adopt.adopt(self.factory, "Isles", source=str(fx.game(self.tmp / "isles")), intent="monitor",
                        person=WHO["person"], persona=WHO["persona"], suite_timeout=60)
        view = self.call("GET", f"/api/projects/{p.pid}")[1]
        self.assertEqual(view["adopted"]["state"], "monitoring")
        self.assertTrue(view["adopted"]["has_areas"])
        self.assertEqual(view["health"]["status"], "at_risk")
        areas = self.call("GET", f"/api/projects/{p.pid}/areas")[1]
        self.assertIn("assets: 4 files", areas["summary"])
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/watch", WHO)
        self.assertEqual(status, 200, out)
        self.assertTrue(out["watch"]["line"].startswith("Watching: "))
        stated = {"command": "python tools/pipeline/check.py test", **WHO}
        self.assertEqual(self.call("POST", f"/api/projects/{p.pid}/baseline/stated", stated)[0], 400)   # no yes
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/baseline/stated", {**stated, "confirm": True})
        self.assertEqual(status, 201, out)
        self.assertEqual(self.runner.started[-1][1][2:4], ["baseline", p.pid])
        other = self.factory.new_project("Not adopted")
        self.assertIsNone(self.call("GET", f"/api/projects/{other.pid}")[1]["adopted"])

    def test_FR_RPJ1_AC_23_an_adopted_project_says_who_adopted_it_as_requested_by(self):
        p = adopt.adopt(self.factory, "Isles", source=str(fx.game(self.tmp / "isles")), intent="improve",
                        person=WHO["person"], persona=WHO["persona"], suite_timeout=5)
        self.assertEqual(p.meta.get("requested_by"), WHO["person"])    # an adoption records who asked for it
        meta = self.call("GET", f"/api/projects/{p.pid}")[1]["meta"]
        self.assertEqual(meta["requested_by"], WHO["person"])
        other = self.factory.new_project("Not adopted")
        self.assertIsNone(self.call("GET", f"/api/projects/{other.pid}")[1]["meta"].get("requested_by"))


if __name__ == "__main__":
    unittest.main()
