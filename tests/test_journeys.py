"""Dead ends found by walking the owner's journeys in a real cockpit (FR-CHG1, FR-MDL1, FR-X1).

The owner's words: "I don't want to see stupid mistakes like me choosing a template for the project or me
generating a spec, then I'm getting stuck somewhere because Rihmasto assumed the project template wrong."

Each test here is the regression test of one thing that went wrong on the way: material added to a project
made from a folder, What's next after a change, a run that read added material and built on the old spec,
the autonomy cap on the command line, a model that is not set up, a confidential project whose local role
kept a hosted fallback, and an adoption whose job page did not lead to the project. Only scripted models
answer: no network call is made.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import material_fixture as mf  # noqa: E402
import test_project_change as tpc  # noqa: E402
from factory_fakes import model  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402
from test_inputs import scripted  # noqa: E402

from cockpit.server import Api  # noqa: E402
from kernel import autonomy, confidential  # noqa: E402
from kernel import next_step as kn  # noqa: E402
from kernel import project_material as km  # noqa: E402
from kernel import rewind as kr  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.models_setup import _fallback_note  # noqa: E402
from kernel.pipeline import AGAIN, _shape  # noqa: E402
from kernel.source_guard import ROOTS_ENV  # noqa: E402

PO = tpc.PO
LONG_AGO = "2000-01-01T00:00:00Z"


class MaterialOfAFolderTest(tpc.ChangeCase):
    def test_FR_CHG1_AC_6_material_added_to_a_project_made_from_a_folder_keeps_the_folders_map(self):
        folder = mf.build(self.tmp / "project")
        p = self.factory.new_project("Visitor register", profile="web_service")
        intake(p, str(folder), model=scripted({}), requested_by="Aino Example")
        files = p.read("material.json")["files"]
        self.assertEqual(km.material(p), {"original": None, "added": []})      # the map is not added material
        self.assertIn("settings", Api._change_view(p))                          # Project settings reads it
        out = km.add_material(p, text=tpc.DESKS, note="desks", **PO)
        kept = p.read("material.json")
        self.assertEqual((out["n"], kept["files"]), (1, files))                 # the map stays as it was
        self.assertEqual([(a["n"], a["note"]) for a in km.material(p)["added"]], [(1, "desks")])
        self.assertEqual(Api._change_view(p)["material"][0]["n"], 1)
        from kernel import material

        material.record(p, {**kept, "files": files[:1]}, person="Aino Example")   # scanned again: added is kept
        self.assertEqual(len(km.material(p)["added"]), 1)


class WhatsNextTest(tpc.ChangeCase):
    def test_FR_CHG1_AC_7_a_run_result_from_before_a_change_no_longer_says_what_the_project_waits_for(self):
        p = self.specced(maturity="pilot")
        last = {"state": "waiting", "stage": 4, "why": "a person approves the plan before building"}
        self.assertIn("approves the plan", kn.next_step(p, last=last, last_started=LONG_AGO)["waits_for"])
        kr.rewind(p, to="spec", reason="the spec missed the desks", **PO)
        seen = kn.next_step(p, last=last, last_started=LONG_AGO)               # went back after the run began
        self.assertNotIn("approves the plan", seen["waits_for"])
        self.assertEqual(seen["state"], "ready")
        self.assertIn("approves the plan", kn.next_step(p, last=last)["waits_for"])   # no start known: as before

    def test_FR_CHG1_AC_7_the_autonomy_cap_says_so_from_the_records_and_each_action_has_its_command(self):
        p = self.specced()
        compile_project(p)
        autonomy.set_cap(p.factory, 2, person="Aino Example", persona="business_owner", reason="no builds yet")
        seen = kn.next_step(p)                                                  # the command line has no last run
        self.assertEqual(seen["state"], "capped")
        self.assertIn("building needs autonomy level 3", seen["waits_for"])
        self.assertTrue(seen["actions"][0]["command"].startswith(f"rihmasto autonomy set 3 --project {p.pid}"))
        asking = self.intaken(mode="socratic")
        acts = kn.next_step(asking)["actions"]
        self.assertEqual(acts[0]["command"], f'rihmasto answer {asking.pid} Q-001 "..." --person ... --persona ...')
        self.assertEqual(acts[1]["command"], f"rihmasto assume {asking.pid} Q-001 --person ... --persona ...")
        self.assertEqual(kn.next_step(asking, running=True)["waits_for"],
                         "the job that runs for it now to end; the page says when it does")
        adopted = self.new()
        adopted.update_meta(source_kind="adopted", intent="improve")
        acts = kn.next_step(adopted)["actions"]
        self.assertEqual([a["label"] for a in acts], ["Describe what to improve", "Work on it in your own terminal"])

    def test_FR_MDL1_AC_7_a_model_that_did_not_answer_takes_any_persona_to_models_setup(self):
        p = self.specced()
        p.log("apparatus_failure", {"where": "pipeline", "error": "connection refused"})
        act = kn.next_step(p)["actions"][0]
        self.assertEqual((act["id"], act["page"], act["command"]), ("set_up_model", "models", "rihmasto models list"))
        self.assertIn("business_owner", act["personas"])
        self.assertIn("Models setup", act["where"])
        refused = kn.from_run(p, {"state": "refused", "why": "the analyst role is hosted"})
        self.assertEqual(refused["actions"][0]["page"], "models")


class AddedMaterialRunTest(tpc.ChangeCase):
    def test_FR_CHG1_AC_10_a_run_reads_added_material_and_stops_before_building_on_the_old_spec(self):
        p = self.specced()
        km.add_material(p, text=tpc.DESKS, note="desks", reintake=True, **PO)    # the cockpit's way: at the next run
        history: list = []
        out = _shape(p, FakeModel(tpc.desks_script), history)
        self.assertEqual((out["state"], out["material_read"], out["stage"]), ("waiting", True, 2))
        new = next(q for q in Canon(p).questions("open") if q["text"] == tpc.NEW_QUESTION)
        self.assertEqual(out["waiting_on"], [new["card"]])
        self.assertIn("the panel read the added material", history[0])
        again = _shape(p, model(), [])                                          # nothing past a blocking question
        self.assertEqual((again["state"], again["waiting_on"]), ("waiting", [new["card"]]))
        self.assertFalse(p.path("contract.json").exists())
        Canon(p).answer(new["id"], "by the half day", **PO)
        acts = [a["id"] for a in kn.next_step(p, last=out)["actions"]]
        self.assertEqual(acts[-2:], ["rewind", "advance"])                     # go back to the spec, or go on
        self.assertEqual(kn.next_step(p, last=out)["actions"][-1]["label"], "Go on with the spec as it is")
        self.assertEqual(_shape(p, model(), []), AGAIN)                         # a person's choice: it goes on
        pilot = self.specced(maturity="pilot")
        from kernel.plan import open_card

        open_card(pilot)                                                        # a plan waits on its approval
        acts = [a["id"] for a in kn.next_step(pilot, last={**out, "waiting_on": []})["actions"]]
        self.assertEqual(acts, ["decide", "rewind"])


class ConfidentialFallbackTest(tpc.ChangeCase):
    ROUTING = {"roles": {"analyst": {"model": "m", "endpoint": "box", "fallback": {"model": "h", "endpoint": "go"}}},
               "endpoints": {"box": {"url": "http://gpu-box:8080/v1/chat/completions", "private": True},
                             "go": {"url": "https://hosted.example/v1/chat/completions"}}}

    def test_FR_MDL1_AC_9_a_local_role_that_kept_a_hosted_fallback_says_how_to_drop_it(self):
        # The owner's decision (2026-11-24, "Skip"): the hosted fallback is skipped, not a reason to refuse.
        self.assertEqual(confidential.refusal(["analyst"], self.ROUTING), "")
        self.assertEqual([r["endpoint"] for r in confidential.skipped(["analyst"], self.ROUTING)], ["go"])
        note = _fallback_note("analyst", self.ROUTING)["note"]
        self.assertIn("skips it (never calls it)", note)
        self.assertIn("--no-fallback", note)
        alone = {**self.ROUTING, "roles": {"analyst": {"model": "m", "endpoint": "box"}}}
        self.assertEqual((confidential.refusal(["analyst"], alone), _fallback_note("analyst", alone)), ("", {}))


class PreviewOnTheCommandLineTest(tpc.ChangeCase):
    def test_FR_CHG1_AC_8_a_preview_needs_no_signer_and_a_change_still_does(self):
        p = self.specced()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), "settings", p.pid, "--kind", "integration", "--preview"])
        self.assertEqual((code, json.loads(out.getvalue())["rewind"]), (0, "questions"), err.getvalue())
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), "rewind", p.pid, "--to", "spec", "--reason", "r"])
        self.assertEqual(code, 2)
        self.assertIn("name --person and --persona", err.getvalue())
        self.assertTrue(p.path("spec.json").exists())


class AdoptedJobTest(CockpitTestCase):
    def test_FR_X1_AC_1_the_jobs_page_opens_the_project_an_adoption_made(self):
        with mock.patch.dict(os.environ, {ROOTS_ENV: str(self.tmp)}):
            repo = self.tmp / "existing-app"
            (repo / "app").mkdir(parents=True)
            (repo / "README.md").write_text("# Order tracker\n\nA small web service.\n", encoding="utf-8")
            (repo / "app" / "main.py").write_text("print('hi')\n", encoding="utf-8")
            for args in (["init", "-q"], ["add", "-A"],
                         ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "x"]):
                subprocess.run(["git", *args], cwd=repo, check=True)
            status, body, _ = self.call("POST", "/api/adopt", {"title": "Order tracker", "source": str(repo),
                                                               "intent": "improve", "person": "Aino",
                                                               "persona": "developer"})
        self.assertEqual(status, 201, body)
        job_id, _, log = self.runner.started[-1]
        made = self.factory.new_project("Order tracker")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("adopting\n" + json.dumps({"project": made.pid, "stage": 5}, indent=2) + "\n", encoding="utf-8")
        self.assertNotIn("made", next(j for j in self.call("GET", "/api/jobs")[1] if j["id"] == job_id))  # running
        self.runner.states[job_id] = "done"
        job = next(j for j in self.call("GET", "/api/jobs")[1] if j["id"] == job_id)
        self.assertEqual(job["made"], made.pid)


if __name__ == "__main__":
    unittest.main()
