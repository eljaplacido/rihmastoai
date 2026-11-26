"""FR-HEAL1: self-healing by default (D-0024 item 1, docs/guides/self-healing.md).

Incidents with stable, secret-free fingerprints and their context; the built-in remedies; learned remedies proposed,
approved once, offered first and applied on their own only when safe; feedback grouped into an approved wording
change; a scan or a job that fails degrades instead of failing the flow; and where self-healing shows: What's next,
Insights, Ask Rihma and the ledger sweep. The investigation, the fix through the gate and the pull request are in
tests/test_heal_fix.py; the cockpit in a real browser in tests/test_ui_heal.py. No real model, no real GitHub.
"""

import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from cockpit import server as cockpit  # noqa: E402
from kernel import feedback, heal_feed, heal_wiring, immune  # noqa: E402
from kernel import incidents as inc  # noqa: E402
from kernel.learn import factory_project  # noqa: E402

SECRET = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
DEV = {"person": "Aino Example", "persona": "developer"}


def ledger_kinds(project) -> list:
    return [r["event"]["kind"] for r in project.ledger().records()]


class FingerprintTest(FactoryTestCase):
    def test_FR_HEAL1_AC_1_a_fingerprint_is_stable_across_ids_paths_numbers_and_secrets_and_holds_no_secret(self):
        a = inc.fingerprint("server_error", "get_outputs", "KeyError",
                            f"no card C-0012 in /home/aino/var/projects/loans-3f2a1c/canon.json token={SECRET}")
        b = inc.fingerprint("server_error", "get_outputs", "KeyError",
                            "no card C-0099 in C:\\Users\\ida\\var\\projects\\rooms-9a8b7c\\canon.json token="
                            + "ghp_" + "Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2Rr1Qq0Pp9Oo8Nn7")
        self.assertEqual(a, b)
        self.assertRegex(a, r"^fp-[0-9a-f]{16}$")
        self.assertNotEqual(a, inc.fingerprint("server_error", "get_outputs", "ValueError", "no card C-0012"))
        said = inc.normalise(f"refused at https://user:{SECRET}@git.example/x for aino@example.org, 42 times")
        self.assertNotIn(SECRET, said)
        self.assertNotIn("aino@example.org", said)
        self.assertNotIn("42", said)

    def test_FR_HEAL1_AC_1_an_incident_is_recorded_masked_and_the_same_failure_is_counted_not_opened_again(self):
        p = self.new()
        first = inc.open_incident(self.factory, kind="job_failed", where="job:run", project=p.pid,
                                  message=f"push failed with {SECRET}", context={"job": {"log_tail": [SECRET]}})
        again = inc.open_incident(self.factory, kind="job_failed", where="job:run", project=p.pid,
                                  message=f"push failed with {SECRET}")
        self.assertTrue(first["new"])
        self.assertFalse(again["new"])
        self.assertEqual((again["id"], again["count"]), (first["id"], 2))
        text = (self.factory.home / "heal" / "incidents" / f"{first['id']}.json").read_text(encoding="utf-8")
        self.assertNotIn(SECRET, text)
        self.assertIn("incident_opened", ledger_kinds(p))
        self.assertTrue(p.ledger().verify().intact)
        self.assertNotIn("internal error", first["summary"])


class ServerErrorTest(CockpitTestCase):
    def boom(self):
        def get_boom(api, **_):
            raise AttributeError(f"'NoneType' object has no attribute 'releases' ({SECRET})")
        routes = cockpit.ROUTES + [("GET", re.compile(r"/api/projects/(?P<pid>[a-z0-9-]+)/boom/?\Z"), "get_boom")]
        for patcher in (mock.patch.object(cockpit, "ROUTES", routes),
                        mock.patch.object(cockpit.Api, "get_boom", get_boom, create=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_FR_HEAL1_AC_1_a_500_opens_an_incident_with_its_context_and_says_it_in_plain_words(self):
        p = self.new()
        self.boom()
        status, out, _ = self.call("GET", f"/api/projects/{p.pid}/boom?persona=developer&view=outputs")
        self.assertEqual(status, 500)
        self.assertEqual(out["error"], "internal error: AttributeError")
        seen = out["incident"]
        self.assertEqual(seen["summary"], "The cockpit hit a bug (get_boom).")
        self.assertEqual([r["id"] for r in seen["offer"]["remedies"]], ["try_again", "investigate"])
        doc = inc.get(self.factory, seen["id"])
        ctx = doc["context"]
        self.assertEqual((ctx["request"]["method"], ctx["request"]["route"], ctx["persona"], ctx["view"]),
                         ("GET", "get_boom", "developer", "outputs"))
        self.assertTrue(any("get_boom" in line for line in ctx["trace"]))
        self.assertTrue(ctx["records"])
        self.assertNotIn(SECRET, json.dumps(doc))
        self.assertIn("incident_opened", ledger_kinds(p))
        status, again, _ = self.call("GET", f"/api/projects/{p.pid}/boom")
        self.assertEqual((again["incident"]["id"], inc.get(self.factory, seen["id"])["count"]), (seen["id"], 2))
        status, listed, _ = self.call("GET", f"/api/projects/{p.pid}/incidents")
        self.assertEqual((status, listed["counts"]["open"], listed["incidents"][0]["id"]), (200, 1, seen["id"]))


class BuiltInRemediesTest(FactoryTestCase):
    def offer(self, **doc):
        doc = {"id": "I-0001", "fingerprint": "fp-x", "project": "loans-3f2a1c", "where": "", "message": "", **doc}
        out = immune.offered(self.factory, doc)
        return out["class"], [r["id"] for r in out["remedies"]], out

    def test_FR_HEAL1_AC_2_each_known_class_gets_its_remedies(self):
        cases = {
            "product_not_running": dict(kind="product_not_running", where="try"),
            "model_unreachable": dict(kind="job_failed", message="the model endpoint did not answer: connection "
                                                                 "refused"),
            "folder_outside_roots": dict(kind="action_failed", message="refused: /srv/x is outside your home folder "
                                                                       "and the roots in RIHMASTO_SOURCE_ROOTS"),
            "hosted_on_confidential": dict(kind="confidential_refused", message="refused: confidential"),
            "job_lost": dict(kind="job_lost"),
            "tool_missing": dict(kind="check_failed", message="not measured: semgrep is not installed"),
            "job_failed": dict(kind="job_failed", message="exit 3"),
            "view_broken": dict(kind="view_broken"),
        }
        wanted = {"product_not_running": ["start_on_road", "why_not_running"],
                  "model_unreachable": ["models_setup", "use_coding_agent", "investigate"],
                  "folder_outside_roots": ["allow_folder", "investigate"],
                  "hosted_on_confidential": ["use_local_model", "investigate"],
                  "job_lost": ["run_again", "investigate"], "tool_missing": ["install_tool", "investigate"],
                  "job_failed": ["run_again", "open_jobs", "investigate"],
                  "view_broken": ["try_again", "investigate"]}
        for name, doc in cases.items():
            cls, ids, out = self.offer(**doc)
            self.assertEqual((cls, ids), (name, wanted[name]), name)
        _, _, out = self.offer(kind="product_not_running", where="try")
        self.assertEqual(out["remedies"][0]["path"], "/api/projects/loans-3f2a1c/advance")
        self.assertFalse(out["remedies"][0]["safe"])                     # starting a job is never safe on its own
        _, _, tool = self.offer(kind="check_failed", message="tool not installed")
        self.assertTrue(tool["not_measured"])
        _, _, write = self.offer(kind="server_error", context={"request": {"method": "POST"}})
        self.assertEqual((write["remedies"][0]["kind"], write["remedies"][0]["safe"]), ("retry", False))


class LearnedRemedyTest(CockpitTestCase):
    def test_FR_HEAL1_AC_3_a_resolution_is_learned_approved_once_offered_first_and_applied_only_when_safe(self):
        p = self.new()
        first = inc.open_incident(self.factory, kind="view_broken", where="outputs", project=p.pid,
                                  message="TypeError: x is undefined")
        status, out, _ = self.call("POST", f"/api/incidents/{first['id']}/resolve",
                                   {"how": {"kind": "link", "href": "#/p/" + p.pid + "/overview", "label": "Open the "
                                            "overview"}, **DEV})
        self.assertEqual(status, 200, out)
        rid = out["remedy"]["id"]
        self.assertEqual(out["remedy"]["state"], "proposed")
        # a proposed remedy is not offered yet; a stakeholder may not approve it
        nxt = inc.open_incident(self.factory, kind="view_broken", where="outputs", project=p.pid,
                                message="TypeError: x is undefined")
        self.assertIsNone(immune.offered(self.factory, nxt)["auto"])
        status, _, _ = self.call("POST", f"/api/remedies/{rid}/approve", {"person": "Sanna", "persona": "stakeholder"})
        self.assertEqual(status, 403)
        status, ok, _ = self.call("POST", f"/api/remedies/{rid}/approve", {"person": "Ilkka", "persona": "it"})
        self.assertEqual(status, 200, ok)
        self.assertRegex(ok["remedy"]["approved"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(inc.get(self.factory, first["id"])["state"], "learned")
        offer = immune.offered(self.factory, nxt)
        self.assertEqual(offer["remedies"][0]["learned"], rid)                    # offered first
        self.assertIn("Rihmasto has seen this before", offer["seen_before"])
        self.assertEqual(offer["auto"]["learned"], rid)                            # a link is safe: on its own
        immune.note_used(self.factory, rid, incident=nxt["id"], person=None, persona=None, auto=True)
        listed = immune.learned_list(self.factory, pid=p.pid)[0]
        self.assertEqual((listed["uses"], listed["auto_uses"], listed["approved"]["person"]), (1, 1, "Ilkka"))
        kinds = ledger_kinds(factory_project(self.factory))
        for k in ("remedy_proposed", "remedy_approved", "remedy_used"):
            self.assertIn(k, kinds)
        # a remedy that changes something (a job, code) stays a proposal a person confirms each time
        job = inc.open_incident(self.factory, kind="job_failed", where="job:run", project=p.pid, message="exit 1")
        inc.resolve(self.factory, job["id"], how={"kind": "retry_job", "id": "run_again"}, **{"person": "Aino",
                                                                                                "persona": "developer"})
        rem = immune.remedies(self.factory)[-1]
        immune.approve(self.factory, rem["id"], person="Ilkka", persona="it")
        again = inc.open_incident(self.factory, kind="job_failed", where="job:run", project=p.pid, message="exit 1")
        self.assertIsNone(immune.offered(self.factory, again)["auto"])
        # retired: no longer offered
        status, _, _ = self.call("POST", f"/api/remedies/{rid}/retire", {"reason": "the view was fixed", "person":
                                                                          "Ilkka", "persona": "it"})
        self.assertEqual(status, 200)
        self.assertIsNone(immune.offered(self.factory, nxt)["seen_before"])


class FeedbackTest(CockpitTestCase):
    def test_FR_HEAL1_AC_6_repeated_feedback_becomes_an_approved_wording_change_applied_from_a_data_file(self):
        where = {"view": "overview", "text": "Waits for"}
        status, one, _ = self.call("POST", "/api/feedback", {"kind": "unclear", "where": where, "words": "for what?",
                                                             "person": "Aino", "persona": "business_owner"})
        self.assertEqual((status, one["feedback"]["proposal"]), (201, None))      # one note is not yet a proposal
        status, two, _ = self.call("POST", "/api/feedback", {"kind": "unclear", "where": where, "words": "unclear",
                                                             "suggest": "Waiting on", "person": "Pekka",
                                                             "persona": "developer"})
        proposal = two["feedback"]["proposal"]
        self.assertEqual((proposal["change"], proposal["text"], len(proposal["items"])), ("wording", "Waiting on", 2))
        groups = self.call("GET", "/api/feedback")[1]["groups"]
        self.assertEqual(groups[0]["count"], 2)
        status, out, _ = self.call("POST", f"/api/feedback/{proposal['id']}/settle",
                                   {"verdict": "approve", "person": "Sanna", "persona": "stakeholder"})
        self.assertEqual(status, 403)                                             # not a persona that approves
        status, out, _ = self.call("POST", f"/api/feedback/{proposal['id']}/settle",
                                   {"verdict": "approve", "person": "Petra", "persona": "product_owner"})
        self.assertEqual((status, out["proposal"]["state"]), (200, "approved"))
        wording = self.call("GET", "/api/wording")[1]["changes"]
        self.assertEqual([(c["view"], c["from"], c["to"]) for c in wording], [("overview", "Waits for", "Waiting on")])
        self.assertIn("feedback_change_applied", ledger_kinds(factory_project(self.factory)))
        # feedback on an assistant answer becomes a rule Ask Rihma reads in its snapshot
        rule = feedback.give(self.factory, kind="wrong", where={"view": "assistant", "text": "the gate passed"},
                             words="it did not", suggest="Say which gate, by task id", person="Aino",
                             persona="developer")
        feedback.settle(self.factory, rule["proposal"]["id"], verdict="approve", person="Ilkka", persona="it")
        from kernel.assistant_snapshot import snapshot
        self.assertEqual(snapshot(self.factory)["heal"]["rules_people_approved"], ["Say which gate, by task id"])


class DegradeTest(CockpitTestCase):
    def test_FR_HEAL1_AC_7_a_scan_that_fails_or_runs_long_degrades_to_a_partial_map_with_what_was_skipped(self):
        folder = self.tmp / "big"
        (folder / "docs").mkdir(parents=True)
        (folder / "README.md").write_text("# Big\n", encoding="utf-8")
        (folder / "docs" / "a.md").write_text("notes\n", encoding="utf-8")

        def broken(path, exclude):
            raise OSError("[WinError 1920] the file cannot be accessed by the system")
        mp, why = heal_feed.resilient_preview(folder, [], preview=broken)
        self.assertIn("OSError", why)
        self.assertTrue(mp["partial"])
        self.assertEqual(sorted(r["path"] for r in mp["files"]), ["README.md", "docs/a.md"])
        self.assertTrue(all(r["action"] == "listed" for r in mp["files"]))
        self.assertIn("Nothing was read", mp["cut"][0])

        def slow(path, exclude):
            import time
            time.sleep(2)
            return {}
        mp, why = heal_feed.resilient_preview(folder, [], budget=0.2, preview=slow)
        self.assertIn("longer than", why)
        # through the cockpit: a 200 with the partial map and its incident, never a 500
        from kernel.source_guard import ROOTS_ENV
        with mock.patch.dict("os.environ", {ROOTS_ENV: str(self.tmp)}), \
                mock.patch("kernel.material.preview", side_effect=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")):
            status, out, _ = self.call("POST", "/api/source/preview", {"source": str(folder), **DEV})
        self.assertEqual(status, 200, out)
        self.assertTrue(out["map"]["partial"])
        self.assertEqual(inc.get(self.factory, out["map"]["incident"])["kind"], "scan_degraded")

    def test_FR_HEAL1_AC_7_a_failed_job_is_an_incident_and_run_it_again_starts_the_same_job(self):
        from kernel.access_isolation import SUITE  # noqa: F401  (isolation is off for a single operator)

        p = self.new()
        job = self.server.start_job("run", p.pid, ["-m", "kernel.cli", "run", p.pid], DEV)
        Path(job["log"]).parent.mkdir(parents=True, exist_ok=True)
        Path(job["log"]).write_text("Traceback ...\nRuntimeError: the lane is held\n", encoding="utf-8")
        self.runner.states[job["id"]] = "failed"
        watched = cockpit.Watcher(self.server).once()
        doc = inc.get(self.factory, watched[0])
        self.assertEqual((doc["kind"], doc["class"]), ("job_failed", "job_failed"))
        self.assertIn("RuntimeError: the lane is held", doc["context"]["job"]["log_tail"])
        self.assertEqual(cockpit.Watcher(self.server).once(), [])            # once per job
        status, out, _ = self.call("POST", f"/api/incidents/{doc['id']}/remedy", {"remedy": "run_again", **DEV})
        self.assertEqual(status, 200, out)
        self.assertEqual(self.runner.started[-1][1], ["-m", "kernel.cli", "run", p.pid])


class VisibilityTest(CockpitTestCase):
    def test_FR_HEAL1_AC_9_incidents_show_in_whats_next_insights_ask_rihma_and_the_ledger_sweep(self):
        p = self.new()
        doc = inc.open_incident(self.factory, kind="view_broken", where="outputs", project=p.pid, message="boom")
        from kernel.next_step import next_step
        acts = next_step(p)["actions"]
        self.assertIn(("incidents_open", "incidents"), [(a.get("control"), a.get("view")) for a in acts])
        from kernel import insights
        tiles = {t["key"]: t for t in insights.read(self.factory, "health", pid=p.pid)["tiles"]}
        self.assertEqual(tiles["incidents"]["value"], 1)
        inc.resolve(self.factory, doc["id"], how={"kind": "retry_read"}, person="Aino", persona="developer")
        tiles = {t["key"]: t for t in insights.read(self.factory, "health", pid=p.pid)["tiles"]}
        self.assertEqual((tiles["incidents"]["value"], tiles["time_to_resolve"]["value"]), (0, 0.0))
        # Ask Rihma: the proposals are checked like a click
        from kernel.assistant_rules import check_proposal
        other = inc.open_incident(self.factory, kind="view_broken", where="tasks", project=p.pid, message="x")
        ok = {"action": "investigate_incident", "args": {"incident": other["id"]}}
        self.assertIsNone(check_proposal(self.factory, None, "developer", ok))
        closed = {"action": "investigate_incident", "args": {"incident": doc["id"]}}
        self.assertIn("already fixed", check_proposal(self.factory, None, "developer", closed))
        self.assertIsNone(check_proposal(self.factory, None, "developer", {"action": "take_remedy", "args": {
            "incident": other["id"], "remedy": "try_again"}}))
        from kernel.assistant_snapshot import snapshot
        self.assertEqual(snapshot(self.factory)["heal"]["incidents"][0]["id"], other["id"])
        # a failure the kernel recorded becomes an incident on the next sweep, once
        p.log("check_ran", {"check": "sbom", "kind": "security", "verdict": "not measured",
                            "summary": "syft is not installed", "person": "Aino", "persona": "developer"})
        made = heal_wiring.sweep(self.factory)
        self.assertEqual(inc.get(self.factory, made[0])["class"], "tool_missing")
        self.assertEqual(heal_wiring.sweep(self.factory), [])
        status, page, _ = self.call("GET", "/api/incidents?state=open")
        self.assertEqual((status, page["counts"]["open"]), (200, 2))


if __name__ == "__main__":
    unittest.main()
