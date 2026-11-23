"""The delivery lifecycle: what was delivered moves the project and tells the catalogue (FR-Q7), the
security gate holds a release before staging and production (FR-H8-AC-2), holdouts run in a twin
slot (FR-H9), an adopted solution says what it waits for (FR-B1-AC-3), and the pipeline carries out
decided cards (FR-V2-AC-2).

The products are real, as in tests/test_deliver.py: built once per maturity, copied into each test,
delivered as local processes on loopback and stopped in cleanup.
"""

import json
import re
import sys
import threading
import types
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model, no_findings  # noqa: E402
from test_adopt import _Answer, python_repo  # noqa: E402
from test_deliver import AZURE, LOCAL_ROADS, DeliveryTestCase, FakeDocker  # noqa: E402

from adapters.sarif import ingest  # noqa: E402
from kernel import roads as roadmod  # noqa: E402
from kernel.adopt import adopt  # noqa: E402
from kernel.adopt import probe as probe_adopted  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.change import apply_change, submit, triage  # noqa: E402
from kernel.dashboard import catalogue, catalogue_state  # noqa: E402
from kernel.deliver import NO_TWIN, deliver, in_production, latest_release, release_reach  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.observations import observe  # noqa: E402
from kernel.pipeline import adopted_state, advance, tick  # noqa: E402
from kernel.security import NO_SCAN, accept_risk  # noqa: E402
from kernel.signals import receive, square  # noqa: E402
from kernel.signals import triage as triage_signal  # noqa: E402

SARIF = Path(__file__).parent / "fixtures" / "sarif"
HELD = "hx-twin-only-7731"   # what a holdout writes: it must never reach where end users try


def stage_moves(project) -> list:
    return [(r["event"]["payload"]["from"], r["event"]["payload"]["to"])
            for r in project.ledger().of_kind("stage_changed")]


def kinds(project) -> list:
    return [r["event"]["kind"] for r in project.ledger().records()]


# -- FR-Q7: the stage and the catalogue follow what was delivered ------------------------------------

class DemoLifecycleTest(DeliveryTestCase):
    maturity = "demo"

    def test_FR_Q7_AC_1_a_demo_waiting_for_its_acceptance_is_at_stage_6_and_trying_and_stays_so(self):
        p = self.project
        self.assertEqual((p.meta["stage"], catalogue_state(p)), (5, "building"))
        out = deliver(p)
        self.assertEqual(out["state"], "waiting", out)
        self.assertEqual(self.canon.get_card(out["waiting_on"])["kind"], "approval")
        self.assertEqual(p.meta["stage"], 6)
        self.assertEqual(stage_moves(p), [(5, 6)])
        moved = p.ledger().of_kind("stage_changed")[0]["event"]["payload"]
        self.assertEqual(moved["release"], 1)
        self.assertIn("landed in demo", moved["why"])
        self.assertEqual(catalogue_state(p), "trying")
        self.decide(out["waiting_on"], "approve", "business_owner")
        self.assertEqual(deliver(p)["state"], "done")
        self.assertEqual((p.meta["stage"], p.meta.get("released")), (6, None))
        self.assertEqual(stage_moves(p), [(5, 6)])                          # one move, recorded once
        item = next(i for i in catalogue(self.factory)["items"] if i["project"] == p.pid)
        self.assertEqual(item["state"], "trying")
        self.assertEqual(square(self.factory)["in_production"], 0)


class PilotLifecycleTest(DeliveryTestCase):
    maturity = "pilot"

    def test_FR_Q7_AC_1_a_release_on_staging_is_in_pilot_while_it_is_validated_or_being_validated(self):
        p = self.project
        self.assertEqual(catalogue_state(p), "building")
        out = deliver(p)
        self.assertEqual(self.canon.get_card(out["waiting_on"])["kind"], "validation")
        self.assertEqual((p.meta["stage"], catalogue_state(p)), (6, "pilot"))
        self.decide(out["waiting_on"], "accept", "business_owner")
        self.assertEqual(deliver(p)["state"], "done")
        self.assertEqual((p.meta["stage"], catalogue_state(p)), (6, "pilot"))
        self.assertFalse(in_production(p))


class ProductionLifecycleTest(DeliveryTestCase):
    maturity = "production"

    def test_FR_Q7_AC_1_a_promoted_release_puts_the_project_at_stage_7_released_in_use_and_in_production(self):
        p = self.project
        self.assertFalse(in_production(p))
        self.assertEqual(square(self.factory)["in_production"], 0)
        out = self.ship()
        self.assertEqual(out["state"], "done", out)
        self.assertEqual((p.meta["stage"], p.meta["released"]), (7, True))
        self.assertEqual(stage_moves(p), [(5, 6), (6, 7)])
        self.assertIn("promoted to production", p.ledger().of_kind("stage_changed")[-1]["event"]["payload"]["why"])
        self.assertTrue(in_production(p))
        self.assertEqual(catalogue_state(p), "in_use")
        self.assertEqual(square(self.factory)["in_production"], 1)
        # What runs decides, not the stage: with production stopped, the project is not in production.
        roadmod.stop_all(p, LOCAL_ROADS)
        self.assertEqual(p.meta["stage"], 7)
        self.assertFalse(in_production(p))
        self.assertEqual(square(self.factory)["in_production"], 0)
        self.assertEqual(catalogue_state(p), "pilot")                         # it was validated on staging


class ExploreLifecycleTest(DeliveryTestCase):
    maturity = "explore"

    def test_FR_Q7_AC_1_a_preview_that_is_done_is_trying_at_stage_6(self):
        p = self.project
        out = deliver(p)
        self.assertEqual(out["state"], "done", out)
        self.assertEqual((p.meta["stage"], catalogue_state(p)), (6, "trying"))
        self.assertEqual(stage_moves(p), [(5, 6)])


class CatalogueReadsReleasesTest(FactoryTestCase):
    def rel(self, n: int, maturity: str, state: str, **outcomes) -> dict:
        return {"release": n, "maturity": maturity, "state": state,
                "steps": [{"step": s, "outcome": o} for s, o in outcomes.items()]}

    def test_FR_Q7_AC_1_the_catalogue_state_comes_from_releases_and_what_runs_not_from_the_stage(self):
        p = self.new()
        self.assertEqual(catalogue_state(p), "shaping")
        p.update_meta(stage=5)
        self.assertEqual(catalogue_state(p), "building")
        p.update_meta(stage=7)                                               # a stage claims nothing by itself
        self.assertEqual(catalogue_state(p), "building")
        self.assertFalse(in_production(p))
        for rel, reach in ((self.rel(1, "pilot", "waiting", user_validation="waiting"), "pilot"),
                           (self.rel(1, "production", "waiting", user_validation="passed", deploy_gate="waiting"),
                            "pilot"),
                           (self.rel(1, "pilot", "failed", user_validation="failed"), None),
                           (self.rel(1, "pilot", "superseded", user_validation="waiting"), None),
                           (self.rel(1, "demo", "waiting", owner_acceptance="waiting"), "trying"),
                           (self.rel(1, "demo", "done", owner_acceptance="passed"), "trying"),
                           (self.rel(1, "demo", "failed", **{"holdouts:demo": "failed"}), None),
                           (self.rel(1, "explore", "done", **{"smoke:preview": "passed"}), "trying"),
                           (self.rel(1, "explore", "failed", **{"smoke:preview": "failed"}), None)):
            self.assertEqual(release_reach(rel), reach, rel)
        # The furthest release counts: a later release that failed does not undo a validation.
        p.write("releases/1.json", self.rel(1, "pilot", "done", user_validation="passed"))
        p.write("releases/2.json", self.rel(2, "pilot", "failed", **{"holdouts:staging": "failed"}))
        self.assertEqual(catalogue_state(p), "pilot")

    def test_FR_Q7_AC_1_an_adopted_solution_monitored_where_it_runs_is_in_use_and_in_production(self):
        p = self.factory.new_project("Legacy loans", source_kind="adopted")
        p.update_meta(intent="maintain", stage=5)
        self.assertEqual((in_production(p), catalogue_state(p)), (False, "building"))
        p.update_meta(intent="monitor", stage=7)
        self.assertEqual((in_production(p), catalogue_state(p)), (True, "in_use"))
        self.assertEqual(square(self.factory)["in_production"], 1)


# -- FR-H8-AC-2: the security gate in delivery ---------------------------------------------------------

class SecurityBeforeStagingTest(DeliveryTestCase):
    maturity = "pilot"

    def held(self, out: dict) -> None:
        self.assertEqual(out["state"], "waiting", out)
        self.assertEqual((out["blocked"]["by"], out["blocked"]["findings"]), ("security", ["SEC-1-1"]))
        self.assertIn("SEC-1-1 (B602, Bandit, app/routes.py:14)", out["waiting_on"])
        self.assertIn("before staging", out["waiting_on"])
        self.assertIsNone(roadmod.slot_state(self.project, "staging", "current"))   # nothing entered staging
        self.assertEqual([c for c in self.canon.cards() if c["refs"].get("release") == 1], [])
        step = self.step(out, "deploy:staging")
        self.assertEqual((step["outcome"], step["native"]["security"]["verdict"]), ("waiting", "failed"))
        self.assertEqual(self.project.meta["stage"], 5)                              # it did not land

    def test_FR_H8_AC_2_an_open_finding_holds_the_release_before_staging_until_a_person_accepts_the_risk(self):
        p = self.project
        ingest(p, SARIF / "bandit.sarif")
        out = deliver(p)
        self.held(out)
        waiting = p.ledger().of_kind("release_waiting")[-1]["event"]["payload"]
        self.assertEqual((waiting["step"], waiting["blocked"]["by"]), ("deploy:staging", "security"))
        again = deliver(p)                                                    # the same finding still holds it
        self.held(again)
        self.assertEqual(again["release"], 1)
        accept_risk(p, "SEC-1-1", person="Jaana", persona="it", expires="2026-12-31",
                    reason="the shell call is in the admin tool only, behind the VPN; fixed in Q1")
        out = deliver(p)
        self.assertEqual(self.canon.get_card(out["waiting_on"])["kind"], "validation")
        self.assertNotIn("blocked", out)
        security = self.step(out, "deploy:staging")["native"]["security"]
        self.assertEqual((security["verdict"], security["accepted"], security["holds"]), ("passed", ["SEC-1-1"], False))
        self.assertIsNotNone(roadmod.slot_state(p, "staging", "current"))

    def test_FR_H8_AC_2_a_clean_scan_lets_a_held_release_go_on(self):
        p = self.project
        ingest(p, SARIF / "bandit.sarif")
        self.held(deliver(p))
        ingest(p, SARIF / "bandit-clean.sarif")                               # the tool's next scan: nothing open
        out = deliver(p)
        self.assertEqual(self.canon.get_card(out["waiting_on"])["kind"], "validation")
        security = self.step(out, "deploy:staging")["native"]["security"]
        self.assertEqual((security["verdict"], security["blocking"]), ("passed", []))

    def test_FR_H8_AC_2_no_security_scan_never_holds_a_release_and_is_recorded(self):
        out = deliver(self.project)
        self.assertEqual(self.canon.get_card(out["waiting_on"])["kind"], "validation")
        security = self.step(out, "deploy:staging")["native"]["security"]
        self.assertEqual((security["verdict"], security["reason"], security["holds"]),
                         ("not measured", NO_SCAN, False))
        self.assertIn("security_gate", kinds(self.project))


class SecurityInDemoTest(DeliveryTestCase):
    maturity = "demo"

    def test_FR_H8_AC_2_in_demo_an_open_finding_is_recorded_in_the_step_and_holds_nothing(self):
        p = self.project
        ingest(p, SARIF / "bandit.sarif")
        out = deliver(p)
        self.assertEqual(self.canon.get_card(out["waiting_on"])["kind"], "approval")
        self.assertNotIn("blocked", out)
        security = self.step(out, "deploy:demo")["native"]["security"]
        self.assertEqual((security["verdict"], security["blocking"], security["holds"]), ("failed", ["SEC-1-1"], False))
        self.assertIn("recorded, not held", security["note"])


class SecurityBeforeProductionTest(DeliveryTestCase):
    maturity = "production"

    def test_FR_H8_AC_2_a_finding_that_arrives_after_staging_holds_the_release_before_production(self):
        p = self.project
        out = deliver(p)
        self.decide(out["waiting_on"], "accept", "business_owner")
        gate = deliver(p)
        self.assertEqual(self.canon.get_card(gate["waiting_on"])["kind"], "deploy_gate")
        ingest(p, SARIF / "bandit.sarif")                                     # a scan arrives while IT decides
        self.decide(gate["waiting_on"], "approve", "it", person="Jaana")
        out = deliver(p)
        self.assertEqual((out["state"], out["blocked"]["environment"]), ("waiting", "production"), out)
        self.assertIn("before production", out["waiting_on"])
        self.assertEqual(self.step(out, "deploy_candidate:production")["outcome"], "waiting")
        self.assertIsNone(roadmod.slot_state(p, "production", "candidate"))
        self.assertIsNone(roadmod.slot_state(p, "production", "current"))
        self.assertEqual(p.meta["stage"], 6)
        accept_risk(p, "SEC-1-1", person="Kaisa", persona="compliance", expires="2026-12-31",
                    reason="accepted for the pilot users only, reviewed weekly")
        out = deliver(p)
        self.assertEqual(out["state"], "done", out)
        self.assertEqual(self.step(out, "deploy_candidate:production")["native"]["security"]["verdict"], "passed")
        self.assertEqual(p.meta["stage"], 7)


# -- FR-H9: holdouts never leave data where end users try the product ----------------------------------

class HoldoutTwinTest(DeliveryTestCase):
    maturity = "demo"

    def setUp(self):
        super().setUp()
        self.addCleanup(mock.patch.stopall)
        from kernel.store import write_json

        write_json(self.project.holdouts_dir / "X-TWIN.json", {"criterion": "X-TWIN", "kind": "holdout", "steps": [
            {"method": "POST", "path": "/items", "body": {"name": HELD}, "expect_status": 201},
            {"method": "GET", "path": "/items", "expect_status": 200, "expect_json": [{"name": HELD}]}]})

    def test_FR_H9_AC_1_holdouts_run_in_a_twin_of_the_same_revision_that_is_stopped_with_its_data(self):
        p = self.project
        out = deliver(p)
        self.assertEqual(out["state"], "waiting", out)
        step = self.step(out, "holdouts:demo")
        self.assertEqual((step["outcome"], step["native"]["slot"]), ("passed", "twin"))
        rel = latest_release(p)
        current = roadmod.slot_state(p, "demo", "current")
        self.assertEqual((rel["holdouts"]["environment"], rel["holdouts"]["slot"]), ("demo", "twin"))
        self.assertNotEqual(rel["holdouts"]["base_url"], current["base_url"])        # not where users try
        twin = p.read(rel["packages"]["demo:twin"])
        self.assertEqual((twin["slot"], twin["revision"], twin["artifact"]["ref"]),
                         ("twin", rel["revision"], current["artifact"]["ref"]))  # the same revision
        self.assertIsNone(roadmod.slot_state(p, "demo", "twin"))                     # stopped
        self.assertFalse(p.path("envs", "demo", "twin", "data").exists())           # its data went with it
        self.assertEqual(self.send("demo", "GET", "/items")["json"], [])            # users find none of it
        traffic = p.path("envs", "demo", "traffic.jsonl")
        self.assertNotIn(HELD, traffic.read_text(encoding="utf-8") if traffic.exists() else "")
        card = self.canon.get_card(out["waiting_on"])
        self.assertEqual(card["payload"]["holdouts"]["slot"], "twin")
        self.assertIn("a twin of it", card["body"])

    def test_FR_H9_AC_1_a_road_that_cannot_host_a_twin_runs_them_in_the_shared_slot_and_says_so(self):
        p = self.project
        mock.patch.object(roadmod.LocalProcessRoad, "hosts_twin", return_value=False).start()
        out = deliver(p)
        step = self.step(out, "holdouts:demo")
        self.assertEqual((step["outcome"], step["native"]["slot"], step["native"]["note"]),
                         ("passed", "current", NO_TWIN))
        rel = latest_release(p)
        self.assertEqual(rel["holdouts"]["note"], "holdouts ran in the shared slot: this road has no twin")
        self.assertEqual(rel["holdouts"]["base_url"], roadmod.slot_state(p, "demo", "current")["base_url"])
        self.assertNotIn("demo:twin", rel["packages"])
        self.assertIn(HELD, json.dumps(self.send("demo", "GET", "/items")["json"]))   # honest: it is there


class TwinRoadsTest(unittest.TestCase):
    def test_FR_H9_AC_1_the_local_and_docker_roads_host_a_twin_on_its_own_data_and_azure_does_not(self):
        project = types.SimpleNamespace(pid="tool-library-1a2b3c")
        rev = "0123456789ab" + "c" * 28
        local = roadmod.PavedRoads.load(LOCAL_ROADS).road("local")
        docker = roadmod.DockerRoad("team", {"kind": "docker", "rules": {"tls": "proxy", "egress": "none"}},
                                    docker=roadmod.DockerCLI(runner=FakeDocker()))
        azure = roadmod.AzureContainerAppsRoad("azure", AZURE)
        self.assertEqual((local.hosts_twin(), docker.hosts_twin(), azure.hosts_twin()), (True, True, False))
        art = {"type": "image", "ref": f"gf-x:{rev[:12]}"}
        twin = docker.package(project, env="staging", slot="twin", release=1, revision=rev, artifact=art)["target"]
        here = docker.package(project, env="staging", slot="current", release=1, revision=rev, artifact=art)["target"]
        self.assertEqual((twin["container"], twin["volume"], twin["host_port"]),
                         ("gf-tool-library-1a2b3c-staging-twin", "gf-tool-library-1a2b3c-staging-twin-data", None))
        self.assertEqual(here["volume"], "gf-tool-library-1a2b3c-staging-data")
        proc = {"type": "process", "ref": f"repo.git@{rev}", "checkout": "builds/x", "command": ["python3"]}
        lt = local.package(project, env="staging", slot="twin", release=1, revision=rev, artifact=proc)["target"]
        self.assertEqual((lt["data_dir"], lt["port"]), ("envs/staging/twin/data", None))


# -- FR-B1-AC-3: an adopted solution in the pipeline -------------------------------------------------

def count_cell(lane_path, prompt):
    """A builder that adds a count of the loans, with a test per visible criterion that fails until it exists."""
    ids = sorted(set(re.findall(r"^- \*\*(R-\d+-AC-\d+)\*\*", prompt, re.MULTILINE)))
    loans = Path(lane_path, "loans.py")
    loans.write_text(loans.read_text(encoding="utf-8") + "\n\ndef count(items):\n    return len(items)\n",
                     encoding="utf-8", newline="\n")
    lines = ["import unittest", "", "", "class CountTest(unittest.TestCase):"]
    for cid in ids:
        lines += [f"    def test_{cid.replace('-', '_')}_count_holds_with_the_existing_behaviour(self):",
                  "        from loans import add, count", "", "        items = []", "        add(items, 'drill')",
                  "        self.assertEqual(count(items), 1)", ""]
    Path(lane_path, "tests", "test_count.py").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return {"code": 0, "bucket": "result", "stop_reason": "answered", "tool_steps": 3, "model": "fake-builder",
            "output": "done"}


class AdoptedPipelineTest(FactoryTestCase):
    def adopt(self, intent: str, **kw):
        src = python_repo(self.tmp / f"src-{intent}-{len(self.factory.projects())}")
        return adopt(self.factory, "Legacy loans", source=str(src), intent=intent, person="Aino",
                     persona="developer", which=lambda name: None, **kw)

    def test_FR_X1_AC_3_an_adopted_solution_to_maintain_waits_for_a_change_a_submission_or_a_person(self):
        for intent in ("maintain", "improve"):
            p = self.adopt(intent)
            out = advance(p, model=model())
            self.assertEqual((out["state"], out["stage"], out["intent"]), ("waiting", 5, intent), out)
            self.assertEqual(out["waiting_for"], ["a change", "a workspace submission", "a person"])
            self.assertNotIn("intake", out["why"])
            self.assertEqual(out["waiting_on"], [])
            self.assertNotIn("build_round", kinds(p))                         # nothing was built
            card = submit(p, persona="end_user", person="Sanna", text="Please list overdue loans too")
            self.assertEqual(advance(p, model=model())["waiting_on"], [card["id"]])   # a person decides it

    def test_FR_X1_AC_3_an_adopted_solution_to_monitor_is_monitoring_with_its_last_probe(self):
        quiet = self.adopt("monitor")                                         # no base_url: nothing to probe
        out = advance(quiet, model=model())
        self.assertEqual((out["state"], out["stage"], out["probe"]["verdict"]), ("monitoring", 7, "not measured"))
        self.assertIn("no base_url", out["probe"]["reason"])
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Answer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            p = self.adopt("monitor", base_url=url)
            out = advance(p, model=model())
            self.assertEqual((out["state"], out["probe"]["verdict"], out["probe"]["base_url"]),
                             ("monitoring", "passed", url))
            self.assertEqual(out["waiting_on"], [])
        finally:
            server.shutdown()
            server.server_close()
        failed = probe_adopted(p)                                             # the service went away
        out = advance(p, model=model())
        self.assertEqual((out["state"], out["probe"]["verdict"]), ("monitoring", "failed"))
        self.assertEqual(out["waiting_on"], [failed["incident"]])
        self.assertEqual(adopted_state(p)["probe"]["incident"], failed["incident"])

    def test_FR_X1_AC_3_a_change_applied_to_an_adopted_solution_goes_round_the_normal_loop(self):
        p = self.adopt("maintain", maturity="demo")
        card = submit(p, persona="developer", person="Aino", kind_hint="defect",
                      text="The count of lent equipment is missing, so nobody knows how much is out")
        tri = triage(p, card["id"])
        if tri.get("needs_requirement"):                                      # no default requirement (FR-DF3)
            Canon(p).answer(tri["needs_requirement"]["question"], "R-1", person="Olli", persona="business_owner")
        if tri["needs_decision"]:                                             # a label never skips the business (FR-P4)
            Canon(p).decide(card["id"], "accept", person="Olli", persona="business_owner",
                            reason="the count belongs in the service")
        applied = apply_change(p, card["id"])
        self.assertEqual((applied["class"], applied["changed"]), ("defect", ["R-1"]))
        self.assertIsNone(adopted_state(p))                                   # a change is under way
        out = advance(p, model=model(), lanes=Lanes(self.tmp / "lanes", size=1), cell_runner=count_cell,
                      verifier_runner=no_findings, deliver_kwargs={})
        self.assertIn({"build": {"T-001": "merged"}}, out["history"], out)
        self.assertEqual(p.read("tasks.json")["T-001"]["status"], "merged")
        self.assertTrue(p.meta["built"])
        gates = [g["event"]["payload"] for g in p.ledger().of_kind("gate")]
        self.assertEqual([(g["task"], g["verdict"]) for g in gates], [("T-001", "passed")])
        # Then delivery, as for any product: no paved road is configured, so it waits on IT's road card.
        self.assertEqual(out["state"], "waiting", out)
        self.assertEqual(Canon(p).get_card(out["waiting_on"][0])["kind"], "road")


# -- FR-V2-AC-2: the pipeline carries out decided cards --------------------------------------------------

class DecidedCardsTest(FactoryTestCase):
    def test_FR_V2_AC_2_each_pass_of_the_pipeline_records_the_update_cards_people_decided(self):
        p = self.new(mode="assume")
        obs = observe(self.factory, "eval_drift", facts={"project": p.pid, "criterion": "R-1-AC-1",
                                                          "before": "0.94", "after": "0.88"}, source="nightly evals")
        card = obs["touched"][0]["card"]
        Canon(p).decide(card, "trial", person="Pekka", persona="developer", reason="measure the new prompt")
        out = advance(p, model=model())                                       # it stops at the missing intake ...
        self.assertEqual(out["state"], "failed")
        self.assertEqual(out["history"], [{"updates": [{"card": card, "verdict": "trial"}]}])   # ... after the update
        self.assertEqual((p.meta["trial"]["card"], p.meta["trial"]["approved_by"]), (card, "Pekka"))
        again = advance(p, model=model())
        self.assertEqual(again["history"], [])                                # carried out once
        self.assertEqual(len(p.ledger().of_kind("update_applied")), 1)

    def test_FR_V2_AC_2_tick_carries_out_decided_concepts_and_advances_nothing_else(self):
        f = self.factory
        other = self.new(mode="assume")
        s = receive(f, "Warehouse staff need to report damaged pallets from a phone", channel="meeting",
                    source="ops weekly", person="Sanna", persona="stakeholder")
        concept = triage_signal(f, s["id"])["routed_to"]["card"]
        from kernel.learn import factory_project

        self.assertEqual(tick(f), {"concepts_applied": [], "projects_created": []})   # nothing decided yet
        Canon(factory_project(f)).decide(concept, "validate", person="Aino", persona="business_owner",
                                         reason="worth a demo")
        out = tick(f)
        self.assertEqual(len(out["projects_created"]), 1)
        self.assertEqual(out["concepts_applied"][0]["card"], concept)
        new = f.project(out["projects_created"][0])
        self.assertEqual(new.read("need.json")["requested_by"], "Aino")
        self.assertFalse(new.path("source.json").exists())                    # its intake waits for a run
        self.assertEqual((new.meta["stage"], other.meta["stage"]), (1, 1))     # no project was advanced
        self.assertNotIn("intake_done", kinds(new))
        self.assertEqual(tick(f)["concepts_applied"], [])                     # carried out once


if __name__ == "__main__":
    unittest.main()
