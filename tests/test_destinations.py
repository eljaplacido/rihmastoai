"""FR-DST1: destinations, publishing and the feedback from where a capability goes.

Over one project with something at every kind of destination (tests/destinations_fixture.py): staging on a
local-process road and production on a gcp-cloudrun road (a fake gcloud on PATH), a Google Drive integration, a
website chat, a Teams subscription of the relay and an MCP face. Publishing runs a fake docker on PATH; nothing
reaches a registry or a cloud. Every server listens on 127.0.0.1.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import destinations_fixture as fx  # noqa: E402

from kernel import destinations, destinations_cli, publish  # noqa: E402
from kernel.automations_run import matches  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.cli import main as cli_main  # noqa: E402
from kernel.destinations_feedback import check  # noqa: E402
from kernel.roads import rmtree  # noqa: E402

IT, DEV = fx.PERSON, ("Pekka Example", "developer")
GATE = ("Jaana Example", "it")


class DestinationsCase(unittest.TestCase):
    def setUp(self):
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed for the product repository")
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-dst-")).resolve()
        self.addCleanup(rmtree, self.tmp)
        self.health = fx.Health()
        self.addCleanup(self.health.stop)
        self.docker = fx.FakeDocker(self.tmp / "docker")
        path = os.pathsep.join([str(self.tmp / "gcloud"), str(self.tmp / "docker"), os.environ.get("PATH", "")])
        env = mock.patch.dict(os.environ, {"PATH": path})
        env.start()
        self.addCleanup(env.stop)
        for name in ("GHCR_USER", "GHCR_TOKEN", "DESK_TEAMS_URL"):
            os.environ.pop(name, None)
        w = fx.build(self.tmp / "home", self.health, self.tmp / "gcloud")
        self.factory, self.project, self.rev = w["factory"], w["project"], w["revision"]

    def view(self) -> dict:
        return destinations.view(self.project)

    def one(self, did: str, view: dict | None = None) -> dict:
        v = view or self.view()
        return next(d for g in v["groups"].values() for d in g if d["id"] == did)

    def kinds(self) -> list:
        return [r["event"]["kind"] for r in self.project.ledger().records()]

    def payloads(self, kind: str) -> list:
        return [r["event"]["payload"] for r in self.project.ledger().of_kind(kind)]

    def logins(self, **env) -> None:
        patcher = mock.patch.dict(os.environ, {"GHCR_USER": "example-bot", "GHCR_TOKEN": fx.TOKEN, **env})
        patcher.start()
        self.addCleanup(patcher.stop)


class ModelTest(DestinationsCase):
    def test_FR_DST1_AC_1_every_place_the_capability_goes_is_read_from_what_exists_grouped_with_its_state(self):
        before = len(self.project.ledger().records())
        v = self.view()
        self.assertEqual(list(v["groups"]), ["deployed", "data", "channels", "published"])
        staging, prod = self.one("deployed:staging", v), self.one("deployed:production", v)
        self.assertEqual((staging["state"], staging["tier"], staging["details"]["road_kind"]),
                         ("delivered", "test", "local-process"))
        self.assertEqual((prod["state"], prod["tier"], prod["details"]["road_kind"]),
                         ("delivered", "production", "gcp-cloudrun"))
        self.assertEqual(prod["last_delivery"]["release"], 1)
        self.assertEqual(prod["url"], self.health.url("production"))
        self.assertEqual({a["id"] for a in prod["actions"]}, {"promote", "open", "check"})
        self.assertIn("deliver", {a["id"] for a in staging["actions"]})
        drive = self.one("data:recordings:staging", v)
        self.assertEqual((drive["state"], drive["details"]["kind"], drive["details"]["access"]),
                         ("planned", "gdrive", "read"))
        self.assertIn("IT approves the binding", drive["missing"][0])
        embed = next(d for d in v["groups"]["channels"] if d["kind"] == "embed")
        self.assertEqual((embed["state"], embed["details"]["origins"]), ("delivered", ["https://desk.example"]))
        teams = self.one("channels:relay:SUB-001", v)
        self.assertEqual(teams["state"], "planned")
        self.assertEqual(teams["missing"], ["the environment variable DESK_TEAMS_URL is not set where the relay runs"])
        mcp, http = self.one("channels:face:mcp", v), self.one("channels:face:http", v)
        self.assertEqual((mcp["state"], mcp["details"]["consumers"], mcp["details"]["tools"]),
                         ("delivered", ["olli"], ["lookup_desk"]))
        self.assertEqual(http["state"], "configured")
        self.assertEqual({a["registry"] for a in mcp["actions"]}, {"mcp-listing"})
        test_reg, listing = self.one("published:ghcr-test", v), self.one("published:mcp-listing", v)
        self.assertEqual(test_reg["state"], "planned")             # its login's variables are not set here
        self.assertTrue(all("GHCR_" in m for m in test_reg["missing"]), test_reg["missing"])
        self.assertEqual((listing["state"], listing["environment"]), ("configured", "production"))
        self.assertIn("runs in staging (delivered), production (delivered)", v["summary"]["line"])
        self.assertEqual(len(self.project.ledger().records()), before)       # reading writes nothing

    def test_FR_DST1_AC_1_a_gcp_road_is_ready_only_with_its_gcloud_and_a_relay_channel_fails_by_its_deliveries(self):
        self.project.path("envs", "production", "current.json").unlink()
        self.assertEqual(self.one("deployed:production")["state"], "configured")   # the fake gcloud is signed in
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "docker")}):
            prod = self.one("deployed:production")
        self.assertEqual(prod["state"], "planned")
        self.assertIn("the gcloud CLI is not on PATH on the deploying host", prod["missing"])
        from kernel import relay

        os.environ["DESK_TEAMS_URL"] = "https://teams.example/hook"
        self.assertEqual(self.one("channels:relay:SUB-001")["state"], "configured")
        Canon(self.project).card("deploy_gate", "Deploy release 1 to production?")      # a notice for IT
        relay.run(self.factory, environ=dict(os.environ), post=lambda url, body, headers: 500)
        teams = self.one("channels:relay:SUB-001")
        self.assertEqual((teams["state"], teams["health"]["why"]), ("failing", "HTTP 500"))
        relay.run(self.factory, environ=dict(os.environ), post=lambda url, body, headers: 200)


class FeedbackTest(DestinationsCase):
    def test_FR_DST1_AC_3_a_failing_destination_feeds_health_review_the_agent_channel_and_automations(self):
        from kernel import agent_channel, review
        from kernel.checks import store as cstore
        from kernel.checks.health import project_health

        first = check(self.project, person=IT[0], persona=IT[1])
        self.assertEqual((first["changes"], first["failing"]), ([], []))
        self.assertEqual(self.one("deployed:production")["state"], "healthy")     # the probe answered
        self.health.server.answers.pop("production")                               # production goes down
        out = check(self.project, person=IT[0], persona=IT[1])
        self.assertEqual([c["destination"] for c in out["changes"]], ["deployed:production"])
        card = Canon(self.project).get_card(out["changes"][0]["card"])
        self.assertEqual((card["kind"], card["state"]), ("incident", "open"))
        msg = agent_channel.read(self.project)["messages"][-1]
        self.assertEqual((msg["thread"], msg["kind"], msg["author"]["kind"]), ("destinations", "check_result", "system"))
        self.assertIn("Production on gcp", msg["text"])
        self.assertEqual(msg["refs"]["cards"], [card["id"]])
        failing = self.payloads("destination_failing")
        self.assertEqual((len(failing), failing[0]["destination"], failing[0]["by"]),
                         (1, "deployed:production", IT[0]))
        self.assertEqual(check(self.project, person=IT[0], persona=IT[1])["changes"], [])   # said once
        self.assertEqual(len(self.payloads("destination_failing")), 1)
        rec = self.project.ledger().of_kind("destination_failing")[-1]
        ev = {"kind": "destination_failing", "seq": rec["seq"], "project": self.project.pid}
        self.assertTrue(matches({"kind": "event", "types": ["destination_failing"]}, ev))
        wrong = next(g for g in review.review(self.factory, person=DEV[0], persona=DEV[1])["groups"]
                     if g["id"] == "wrong")
        self.assertTrue(any("A destination is failing: Production on gcp" in i["title"] for i in wrong["items"]),
                        [i["title"] for i in wrong["items"]])
        cstore.enable(self.project, "destinations", person=IT[0], persona=IT[1])
        row = cstore.run(self.project, "destinations", person=IT[0], persona=IT[1])
        self.assertEqual(row["verdict"], "failed")
        self.assertIn("Destinations", project_health(self.project)["failing"])

    def test_FR_DST1_AC_3_a_round_is_signed_and_a_recovery_is_recorded(self):
        with self.assertRaises(DecisionRefused):
            check(self.project, person="factory", persona="it")
        self.health.server.answers.pop("staging")
        check(self.project, person=IT[0], persona=IT[1])
        card = self.payloads("destination_failing")[-1]["card"]
        Canon(self.project).decide(card, "acknowledge", person=IT[0], persona="operations")
        self.health.server.answers["staging"] = self.rev[:12]
        out = check(self.project, person=IT[0], persona=IT[1])
        self.assertEqual(out["changes"], [{"destination": "deployed:staging", "became": "healthy"}])
        self.assertEqual(self.payloads("destination_recovered")[-1]["state"], "healthy")


class PublishTest(DestinationsCase):
    def test_FR_DST1_AC_2_publishing_is_refused_without_configuration_saying_exactly_what_is_missing(self):
        with self.assertRaises(publish.PublishRefused) as nowhere:
            publish.publish(self.project, to="quay", person=IT[0], persona=IT[1])
        self.assertIn("no registry named 'quay'", str(nowhere.exception))
        with self.assertRaises(publish.PublishRefused) as unset:
            publish.publish(self.project, to="ghcr-test", person=IT[0], persona=IT[1])
        self.assertEqual(unset.exception.missing, [
            "the environment variable GHCR_USER (login.username_env of 'ghcr-test') is not set on the deploying host",
            "the environment variable GHCR_TOKEN (login.password_env of 'ghcr-test') is not set on the deploying host"])
        refused = self.payloads("publish_refused")
        self.assertEqual([(r["registry"], r["by"], r["persona"]) for r in refused],
                         [("quay", IT[0], "it"), ("ghcr-test", IT[0], "it")])
        with self.assertRaises(DecisionRefused):
            publish.publish(self.project, to="ghcr-test", person=IT[0], persona="end_user")
        self.assertEqual(self.docker.calls(), [])                                 # docker was never asked

    def test_FR_DST1_AC_2_a_release_goes_to_a_test_registry_first_then_to_production_through_the_deploy_gate(self):
        self.logins()
        with self.assertRaises(publish.PublishRefused) as early:
            publish.publish(self.project, to="ghcr", person=IT[0], persona=IT[1])
        self.assertIn("publish release 1 to a test registry first (ghcr-test)", str(early.exception))
        out = publish.publish(self.project, to="ghcr-test", person=DEV[0], persona=DEV[1])
        image = f"ghcr.io/example-org/test/rihmasto-{self.project.pid}:r1-{self.rev[:12]}"
        self.assertEqual((out["state"], out["image"], out["environment"]), ("published", image, "test"))
        self.assertTrue(out["digest"].startswith("sha256:"))
        calls = self.docker.calls()
        self.assertEqual([c["args"][0] for c in calls], ["build", "login", "tag", "push"])
        login = calls[1]
        self.assertEqual(login["args"], ["login", "ghcr.io", "--username", "example-bot", "--password-stdin"])
        self.assertTrue(login["stdin_read"])
        self.assertNotIn(fx.TOKEN, json.dumps(calls) + json.dumps(publish.history(self.project))
                         + (self.project.path("ledger.jsonl").read_text(encoding="utf-8")
                            if self.project.path("ledger.jsonl").exists() else ""))
        self.assertEqual(self.one("published:ghcr-test")["state"], "healthy")
        waiting = publish.publish(self.project, to="ghcr", person=IT[0], persona=IT[1])
        self.assertEqual(waiting["state"], "waiting")
        gate = Canon(self.project).get_card(waiting["waiting_on"])
        self.assertEqual((gate["kind"], gate["deciders"]), ("deploy_gate", ["it"]))
        self.assertEqual(gate["payload"]["publish"]["tested"], image)
        self.assertEqual(len(self.docker.calls()), 4)                              # nothing pushed to production
        self.assertEqual(publish.publish(self.project, to="ghcr", person=IT[0], persona=IT[1])["waiting_on"],
                         gate["id"])                                               # the same card, still open
        with self.assertRaises(DecisionRefused):
            Canon(self.project).decide(gate["id"], "approve", person=DEV[0], persona=DEV[1])
        Canon(self.project).decide(gate["id"], "approve", person=GATE[0], persona=GATE[1])
        prod = publish.publish(self.project, to="ghcr", person=IT[0], persona=IT[1])
        self.assertEqual((prod["state"], prod["image"]),
                         ("published", f"ghcr.io/example-org/rihmasto-{self.project.pid}:r1-{self.rev[:12]}"))
        self.assertEqual([c["args"][0] for c in self.docker.calls()[4:]], ["build", "tag", "push"])  # login existing
        self.assertEqual([(p["registry"], p["environment"]) for p in self.payloads("published")],
                         [("ghcr-test", "test"), ("ghcr", "production")])
        rec = self.project.ledger().of_kind("published")[-1]
        self.assertTrue(matches({"kind": "event", "types": ["published"]},
                                {"kind": "published", "seq": rec["seq"], "project": self.project.pid}))

    def test_FR_DST1_AC_2_a_refused_gate_stops_it_and_a_failed_push_is_failing(self):
        self.logins()
        publish.publish(self.project, to="ghcr-test", person=DEV[0], persona=DEV[1])
        gate = publish.publish(self.project, to="ghcr", person=IT[0], persona=IT[1])["waiting_on"]
        Canon(self.project).decide(gate, "refuse", person=GATE[0], persona=GATE[1], reason="not this week")
        with self.assertRaises(publish.PublishRefused) as stopped:
            publish.publish(self.project, to="ghcr", person=IT[0], persona=IT[1])
        self.assertIn("IT refused publishing release 1 to ghcr (Jaana Example): not this week", str(stopped.exception))
        self.docker.write({"fail": ["push"]})
        failed = publish.publish(self.project, to="ghcr-test", person=DEV[0], persona=DEV[1])
        self.assertEqual(failed["state"], "failed")
        self.assertIn("denied", failed["why"])
        reg = self.one("published:ghcr-test")
        self.assertEqual((reg["state"], reg["health"]["verdict"]), ("failing", "failed"))
        self.assertEqual(self.payloads("publish_failed")[-1]["registry"], "ghcr-test")

    def test_FR_DST1_AC_2_an_mcp_registry_entry_is_a_file_a_person_submits(self):
        self.logins()
        publish.publish(self.project, to="ghcr-test", person=DEV[0], persona=DEV[1])
        out = publish.publish(self.project, to="mcp-listing", person=DEV[0], persona=DEV[1])
        self.assertEqual((out["state"], out["submitted"]), ("written", False))
        doc = json.loads(self.project.path("publish", "1", "mcp-server.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["name"], "io.github.example-org/desk-helper")
        self.assertEqual(doc["packages"][0]["registryType"], "oci")
        self.assertTrue(doc["packages"][0]["identifier"].startswith("ghcr.io/example-org/test/"))
        self.assertIn("submit it yourself", out["next"][0])
        listing = self.one("published:mcp-listing")
        self.assertEqual(listing["state"], "configured")
        self.assertIn("submit it yourself", listing["note"])
        self.assertEqual(self.payloads("mcp_entry_written")[-1]["by"], DEV[0])


class CliAndChatTest(DestinationsCase):
    def cli(self, *argv: str) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli_main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_FR_DST1_AC_5_the_command_line_shows_checks_and_publishes(self):
        code, out, err = self.cli("destinations", self.project.pid)
        self.assertEqual((code, err), (0, ""))
        for line in ("Deployed", "Data and integrations", "Channels", "Published", "[delivered] Production on gcp"):
            self.assertIn(line, out)
        code, out, _ = self.cli("destinations", self.project.pid, "--json")
        self.assertEqual(json.loads(out)["project"], self.project.pid)
        code, out, err = self.cli("destinations", self.project.pid, "--check")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("signed", err)
        code, out, _ = self.cli("destinations", self.project.pid, "--check", "--json", "--person", IT[0],
                                "--persona", IT[1])
        self.assertEqual(code, 0)
        self.assertEqual(self.payloads("destinations_checked")[-1]["via"], "command line")
        code, out, err = self.cli("publish", self.project.pid, "--to", "ghcr-test", "--person", IT[0], "--persona", "it")
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("rihmasto publish: registry ghcr-test is not ready"), err)
        self.logins()
        code, out, err = self.cli("publish", self.project.pid, "--to", "ghcr-test", "--release", "1", "--person",
                                  IT[0], "--persona", "it")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["state"], "published")

    def test_FR_DST1_AC_4_ask_rihma_answers_where_this_is_running_and_proposes_delivering_there(self):
        from kernel.assistant import ask

        out = ask(self.factory, "Where is this running?", persona="it", project_id=self.project.pid)
        self.assertIn("Production on gcp: delivered", out["answer"])
        self.assertEqual(out["navigate"]["route"], f"#/p/{self.project.pid}/destinations")
        self.assertEqual([p["action"] for p in out["propose"]], ["open"])
        act = ask(self.factory, "Please publish it to the test registry", persona="it", project_id=self.project.pid)
        self.assertIn("Deliver or publish there", act["propose"][0]["why"])
        fi = ask(self.factory, "Missä tämä pyörii tuotannossa?", persona="it", project_id=self.project.pid)
        self.assertEqual(fi["navigate"]["route"], f"#/p/{self.project.pid}/destinations")
        other = destinations_cli.chat_answer(self.project, "Who decides the deploy gate?")
        self.assertIsNone(other)


if __name__ == "__main__":
    unittest.main()
