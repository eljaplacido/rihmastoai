"""FR-WLK1 in the cockpit: the walkthrough routes over the real server, and Plug in an existing project waiting
on a real adoption job (the cockpit's own job runner, a real child process) for a git repository and for a
folder that is not one, then showing the result. Confirm goes through the cockpit's own route with its module
check, so what a button would be refused is refused here too, and said in the chat. Ask Rihma offers a
walkthrough beside its answer. The cockpit's map names every walkthrough with a label of its own.
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_cockpit import CockpitTestCase  # noqa: E402
from test_walkthrough import code_folder  # noqa: E402
from walkthrough_fakes import allow_roots  # noqa: E402

from cockpit.server import SubprocessRunner  # noqa: E402
from kernel import modules  # noqa: E402
from kernel.assistant import ui_map  # noqa: E402
from kernel.assistant_rules import CONTROL_PAGES  # noqa: E402
from kernel.learn import FACTORY_PID, factory_project  # noqa: E402

WHO = {"person": "Aino Example", "persona": "developer"}
JOB_WAIT = 300


class WalkCockpitCase(CockpitTestCase):
    def setUp(self):
        super().setUp()
        allow_roots(self, self.tmp)

    def post(self, path: str, body: dict, status: int = 200) -> dict:
        got, out, _ = self.call("POST", path, {**body, **WHO})
        self.assertEqual(got, status, out)
        return out

    def start(self, name: str, **body) -> dict:
        return self.post("/api/walkthroughs", {"name": name, **body}, 201)["walkthrough"]

    def reply(self, wid: str, **body) -> dict:
        return self.post(f"/api/walkthroughs/{wid}/reply", body)["walkthrough"]

    def to_confirm(self, folder: Path) -> dict:
        w = self.start("plug_in")
        for body in ({"text": str(folder)}, {"choice": "default"}, {"choice": "no"}, {"choice": "maintain"},
                     {"choice": "none"}):
            w = self.reply(w["id"], **body)
        self.assertEqual(w["awaiting"], {"kind": "confirm", "label": "Adopt Orders", "action": "adopt"})
        return w

    def wait_job(self, wid: str) -> dict:
        """The walkthrough read as the page reads it while it waits, until the job ended."""
        seen, end = [], time.monotonic() + JOB_WAIT
        while time.monotonic() < end:
            status, out, _ = self.call("GET", f"/api/walkthroughs/{wid}")
            self.assertEqual(status, 200, out)
            job = out["walkthrough"]["job_view"]
            seen += [p for p in job["progress"] if p not in seen]
            if job["state"] not in ("running", "unknown"):
                return {"job": job, "progress": seen}
            time.sleep(0.25)
        self.fail("the adoption job did not end")


class PlugInCockpitTest(WalkCockpitCase):
    def adopt_and_wait(self, folder: Path) -> dict:
        self.server.runner = SubprocessRunner(self.factory.home)        # a real job, as the cockpit runs it
        w = self.to_confirm(folder)
        self.assertEqual([p.pid for p in self.factory.projects()], [FACTORY_PID])     # nothing before confirm
        out = self.post(f"/api/walkthroughs/{w['id']}/confirm", {})["walkthrough"]
        self.assertEqual((out["step"], out["awaiting"]["kind"]), ("adopting", "job"))
        ended = self.wait_job(w["id"])
        self.assertEqual(ended["job"]["state"], "done", ended)
        self.assertIn("running its own tests once for a baseline", ended["progress"])
        return self.reply(w["id"], job=True)

    def check_result(self, out: dict, *, git: bool) -> None:
        project = next(p for p in self.factory.projects() if p.pid != FACTORY_PID)
        self.assertEqual((out["state"], out["project"]), ("done", project.pid))
        result = next(m for m in out["messages"] if m.get("result"))
        self.assertEqual(result["result"]["baseline"]["verdict"], "passed")
        self.assertIn("Orders is adopted. Its baseline: passed", result["text"])
        self.assertIn("What's next:", result["text"])
        self.assertEqual(result["links"][0], {"label": "Open the project", "route": f"#/p/{project.pid}/overview"})
        self.assertEqual((project.meta["intent"], bool((project.read("adopted.json") or {}).get("snapshot"))),
                         ("maintain", not git))
        asked = [r["event"]["payload"] for r in factory_project(self.factory).ledger().records()
                 if r["event"]["kind"] == "cockpit_write" and r["event"]["payload"]["action"] == "adopt_requested"]
        self.assertEqual([(a["person"], a["persona"]) for a in asked], [("Aino Example", "developer")])

    def test_FR_WLK1_AC_4_plug_in_waits_on_the_real_adoption_job_of_a_git_repository_and_shows_the_result(self):
        out = self.adopt_and_wait(code_folder(self.tmp / "orders", repo=True))
        self.check_result(out, git=True)

    def test_FR_WLK1_AC_4_a_folder_that_is_not_a_git_repository_is_adopted_the_same_way(self):
        out = self.adopt_and_wait(code_folder(self.tmp / "orders", repo=False))
        self.check_result(out, git=False)

    def test_FR_WLK1_AC_4_a_job_that_fails_says_why_and_offers_to_try_again(self):
        w = self.to_confirm(code_folder(self.tmp / "orders", repo=True))
        out = self.post(f"/api/walkthroughs/{w['id']}/confirm", {})["walkthrough"]
        job_id, _, log = self.runner.started[-1]
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("adopt: fetching the code\nrihmasto adopt: the upstream could not be read\n", encoding="utf-8")
        self.runner.states[job_id] = "failed"
        self.assertEqual(self.call("GET", f"/api/walkthroughs/{w['id']}")[1]["walkthrough"]["job_view"]["progress"],
                         ["fetching the code"])
        out = self.reply(w["id"], job=True)
        self.assertEqual((out["step"], out["awaiting"]["kind"]), ("confirm", "confirm"))
        self.assertIn("the upstream could not be read", [m["text"] for m in out["messages"]][-2])
        status, body, _ = self.call("POST", f"/api/walkthroughs/{w['id']}/reply", {"choice": "nope", **WHO})
        self.assertEqual(status, 400, body)


class GovernedTest(WalkCockpitCase):
    def test_FR_WLK1_AC_8_confirm_goes_through_the_cockpit_s_own_route_and_its_refusal_is_said_in_the_chat(self):
        papers = self.tmp / "papers"
        papers.mkdir()
        (papers / "brief.md").write_text("# Loans\n\n" + "We lend drills and lose them. " * 30, encoding="utf-8")
        modules.set_modules(self.factory, person="Aino Example", persona="it", preset="assess_only")  # intake off
        w = self.start("documents")
        for body in ({"text": str(papers)}, {"choice": "default"}, {"choice": "no"}, {"choice": "none"}):
            w = self.reply(w["id"], **body)
        out = self.post(f"/api/walkthroughs/{w['id']}/confirm", {})
        self.assertIn("post_project is part of Intake and spec", out["refused"])
        self.assertEqual(out["walkthrough"]["awaiting"]["kind"], "confirm")
        self.assertEqual([p.pid for p in self.factory.projects()], [FACTORY_PID])     # nothing was created
        self.assertEqual(self.runner.started, [])
        status, body, _ = self.call("POST", f"/api/walkthroughs/{w['id']}/confirm", {"person": "factory",
                                                                                    "persona": "developer"})
        self.assertEqual(status, 403, body)                                   # signed by a named person

    def test_FR_WLK1_AC_8_routes_resume_cancel_and_the_assistant_offers_a_walkthrough(self):
        w = self.start("tour")
        self.assertEqual(self.start("tour")["id"], w["id"])                   # resumed
        status, body, _ = self.call("POST", "/api/walkthroughs", {"name": "plug_in", **WHO})
        self.assertEqual(status, 409, body)
        listed = self.call("GET", "/api/walkthroughs?person=Aino%20Example")[1]
        self.assertEqual((listed["yours"]["id"], len(listed["walkthroughs"])), (w["id"], 5))
        out = self.post(f"/api/walkthroughs/{w['id']}/cancel", {})["walkthrough"]
        self.assertEqual(out["state"], "cancelled")
        self.assertIsNone(self.call("GET", "/api/walkthroughs?person=Aino%20Example")[1]["yours"])
        status, said, _ = self.call("POST", "/api/assistant", {"question": "minulla on olemassa oleva projekti",
                                                                "persona": "developer", "person": "Aino Example"})
        self.assertEqual((status, said["walkthrough"]["name"]), (200, "plug_in"))
        status, said, _ = self.call("POST", "/api/assistant", {"question": "Where is the ledger?",
                                                                "persona": "developer", "person": "Aino Example"})
        self.assertIsNone(said["walkthrough"])

    def test_FR_WLK1_AC_8_the_cockpit_s_map_names_each_walkthrough_with_its_own_label(self):
        controls = {c["id"]: c for c in ui_map()["controls"]}
        labels = {cid: controls[cid]["label"] for cid in ("walkthroughs", "walk_plug_in", "walk_new_idea",
                                                          "walk_documents", "walk_model", "walk_tour")}
        self.assertEqual(labels, {"walkthroughs": "Walkthroughs", "walk_plug_in": "Plug in an existing project",
                                  "walk_new_idea": "Start from a new idea", "walk_documents": "Start from documents",
                                  "walk_model": "Set up a model", "walk_tour": "Get started"})
        self.assertEqual(CONTROL_PAGES["walkthroughs"], (None, "home"))
        js = self.page_js()
        for cid in labels:
            self.assertRegex(js, rf'data-control"\s*:\s*"{cid}"')
        status, out, _ = self.call("POST", "/api/assistant", {"question": "Where are the walkthroughs?",
                                                               "persona": "developer", "person": "Aino Example"})
        self.assertEqual(out["navigate"], {"route": "#/home", "control": "walkthroughs"})


if __name__ == "__main__":
    unittest.main()
