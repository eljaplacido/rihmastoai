"""FR-AUT1-AC-13 and FR-AUT1-AC-14: `rihmasto automations` end to end from the command line, and the cockpit's
Automations routes, its scheduler and Ask Rihma's map. The browser walk is tests/test_ui_automations.py."""

import contextlib
import io
import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from cockpit.automation_routes import Scheduler  # noqa: E402
from kernel import automations as au  # noqa: E402
from kernel import relay  # noqa: E402
from kernel.agentobs.automation_hook import TEMPLATES as AGENTOBS_TEMPLATES  # noqa: E402
from kernel.assistant import ask, find_in_map  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.learn import factory_project  # noqa: E402

SIGNED = ["--person", "Aino", "--persona", "product_owner"]


class CommandLineTest(FactoryTestCase):
    def cli(self, *argv, code=0):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("kernel.cli._model", model), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            got = main(["--home", str(self.factory.home), *argv])
        self.assertEqual(got, code, (argv, err.getvalue()))
        return json.loads(out.getvalue()) if out.getvalue().strip() else err.getvalue()

    def test_FR_AUT1_AC_13_every_automations_command_works_from_the_command_line(self):
        a, b = self.new(title="Loans"), self.new(title="Bookings")
        made = self.cli("automations", "add", "--name", "When Loans releases", "--on", "release_done", "--project",
                        a.pid, "--action", "change", "--target-project", b.pid, "--text", "{project} released",
                        "--max-per-hour", "5", *SIGNED)
        self.assertEqual((made["id"], made["limits"]["max_per_hour"], made["action"]["project"]), ("AU-001", 5, b.pid))
        self.assertTrue(made["summary"].startswith(f"When a release is done, for project {a.pid}, open a change "
                                                   f"proposal on {b.pid}"), made["summary"])
        refused = self.cli("automations", "add", "--name", "x", "--every", "1h", "--json",
                           '{"action": {"kind": "decide"}}', "--factory", *SIGNED, code=2)
        self.assertIn("rihmasto automations add: an automation never may decide", refused)
        sub = relay.subscribe(self.factory, sink="webhook", url="https://ops.example/in", secret_env="OPS_KEY",
                              person="Ilkka", persona="it")
        tpl = self.cli("automations", "add", "--template", "notify_on_release", "--subscription", sub["id"],
                       "--person", "Ilkka", "--persona", "it")
        self.assertEqual((tpl["name"], tpl["action"]["subscription"], tpl["scope"]), ("Notify on release", sub["id"],
                                                                                    {"kind": "factory"}))
        self.assertEqual(len(self.cli("automations", "list")["automations"]), 2)
        self.assertEqual([x["id"] for x in self.cli("automations", "list", "--project", b.pid)["automations"]],
                         ["AU-001", "AU-002"])                                  # B is the target of AU-001
        self.assertEqual(len(self.cli("automations", "templates")["templates"]), 13 + len(AGENTOBS_TEMPLATES))
        edited = self.cli("automations", "edit", "AU-001", "--guard-count", "release_done:1:720", *SIGNED)
        self.assertEqual((edited["version"], edited["guard"]["kind"]), (2, "count"))
        a.log("release_done", {"release": 1})
        self.assertEqual(self.cli("automations", "dry-run", "AU-001")["firings"][0]["guard"], "holds")
        ticked = self.cli("automations", "tick")
        self.assertEqual({r["id"]: len(r["ran"]) for r in ticked["results"]}, {"AU-001": 1, "AU-002": 1})
        self.assertEqual(len(Canon(b).cards(kind="change")), 1)
        self.cli("automations", "pause", "AU-001", "--reason", "audit", *SIGNED)
        self.assertEqual(self.cli("automations", "list", "--state", "paused")["automations"][0]["paused_why"], "audit")
        self.cli("automations", "resume", "AU-001", *SIGNED)
        now = self.cli("automations", "run-now", "AU-001", "--project", a.pid, *SIGNED)
        self.assertEqual(now["tick"]["results"][0]["ran"][0]["outcome"], "nothing")   # the same words: not twice
        shown = self.cli("automations", "show", "AU-001")
        self.assertEqual([h["kind"] for h in shown["history"]][-2:], ["automation_run_requested", "automation_ran"])
        self.assertEqual(self.cli("automations", "tag", a.pid, "--tag", "ops", *SIGNED)["tags"], ["ops"])
        self.assertEqual(len(self.cli("automations", "history", "AU-001")["history"]), 7)
        self.cli("automations", "remove", "AU-002", "--person", "Ilkka", "--persona", "it")
        helped = self.cli("automations", "install-help")
        self.assertIn("automations tick", helped["cron"])
        self.assertTrue(helped["cron"].startswith("* * * * * cd "))
        self.assertIn('schtasks /Create /TN "Rihmasto automations" /SC MINUTE /MO 1', helped["windows_task_scheduler"])
        self.assertIn(str(self.factory.home.resolve()), helped["windows_task_scheduler"])
        self.assertTrue(factory_project(self.factory).ledger().verify().intact)

    def test_FR_AUT1_AC_4_hooks_bind_and_a_relay_receiver_of_one_project_from_the_command_line(self):
        a = self.new(title="Loans")
        self.cli("hooks", "add", "ci", "--scheme", "standard", "--secret-env", "HOOK_CI", "--bind", a.pid,
                 "--person", "Ilkka", "--persona", "it")
        self.assertEqual(self.cli("hooks", "list")["sources"][0]["projects"], [a.pid])
        self.assertEqual(self.cli("hooks", "bind", "ci", "--person", "Ilkka", "--persona", "it")["projects"], [])
        self.cli("hooks", "bind", "ci", "--project", a.pid, "--person", "Aino", "--persona", "developer", code=2)
        sub = self.cli("relay", "subscribe", "--sink", "webhook", "--url", "https://ops.example/in", "--secret-env",
                       "OPS_KEY", "--project", a.pid, "--person", "Ilkka", "--persona", "it")
        self.assertEqual(sub["projects"], [a.pid])


class CockpitRoutesTest(CockpitTestCase):
    def body(self, **extra):
        return {"person": "Aino", "persona": "product_owner", **extra}

    def test_FR_AUT1_AC_14_the_automations_page_and_a_projects_tab_read_and_write_through_the_kernel(self):
        p, q = self.new(title="Loans"), self.new(title="Bookings")
        status, out, _ = self.call("GET", "/api/automations")
        self.assertEqual((status, out["automations"], out["scheduler"]["running"]), (200, [], False))
        self.assertEqual({a["id"] for a in out["actions"]}, set(au.ACTIONS))
        self.assertEqual(len(out["templates"]), 13 + len(AGENTOBS_TEMPLATES))   # with run_check's, align_scan's,
        # review_digest's, the weekly Gnomon audit's (FR-EVL1) and agent observability's
        draft = {"name": "Every hour", "trigger": {"kind": "schedule", "every": "1h"},
                 "action": {"kind": "signal", "text": "hourly {project}"}, "scope": {"kind": "projects",
                                                                                   "projects": [p.pid, q.pid]}}
        status, out, _ = self.call("POST", "/api/automations/preview", self.body(automation=dict(draft, name="")))
        self.assertEqual((status, out), (200, {"ok": False, "why": "the name is empty"}))
        status, out, _ = self.call("POST", "/api/automations", self.body(automation=draft))
        self.assertEqual(status, 201, out)
        aid = out["automation"]["id"]
        self.assertEqual(out["automation"]["projects_now"], sorted([p.pid, q.pid]))
        refused = self.body(automation=dict(draft, action={"kind": "decide"}))
        status, out, _ = self.call("POST", "/api/automations", refused)
        self.assertEqual(status, 403, out)
        status, out, _ = self.call("GET", f"/api/projects/{q.pid}/automations")
        self.assertEqual([a["id"] for a in out["automations"]], [aid])
        status, out, _ = self.call("GET", "/api/automations?state=paused")
        self.assertEqual(out["automations"], [])
        self.assertEqual(self.call("GET", "/api/projects/_factory/automations")[1]["automations"], [])
        status, out, _ = self.call("PUT", f"/api/projects/{p.pid}/tags", self.body(tags=["Ops", "nightly"]))
        self.assertEqual((status, out["tags"]), (200, ["nightly", "ops"]))
        # Run now is recorded at once; the scheduler carries it out, woken for it
        sched = Scheduler(self.factory, every=3600)
        self.server.automation_scheduler = sched
        status, out, _ = self.call("POST", f"/api/automations/{aid}/run", self.body())
        self.assertEqual((status, out["requested"]["person"]), (200, "Aino"))
        sched.start()
        self.addCleanup(sched.stop)
        deadline = time.monotonic() + 10
        while not factory_project(self.factory).ledger().of_kind("automation_ran") and time.monotonic() < deadline:
            time.sleep(0.1)
        ran = [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind("automation_ran")]
        self.assertEqual(sorted(r["project"] for r in ran), sorted([p.pid, q.pid]))
        self.assertEqual({r["requested_by"] for r in ran}, {"Aino"})
        status, out, _ = self.call("GET", "/api/automations")
        self.assertTrue(out["scheduler"]["running"])
        self.assertEqual(out["automations"][0]["history"][-1]["kind"], "automation_ran")

    def test_FR_AUT1_AC_14_ask_rihma_explains_automations_and_takes_a_person_there(self):
        p = self.new(title="Loans")
        top = find_in_map("Where do I set up a nightly automation?")[0]
        self.assertEqual(top["id"], "automations_all")
        out = ask(self.factory, "how do I schedule a nightly re-gate?", persona="developer")
        self.assertEqual(out["navigate"]["route"], "#/automations")
        out = ask(self.factory, "where are this project's automations?", persona="developer", project_id=p.pid)
        self.assertEqual(out["navigate"]["route"], f"#/p/{p.pid}/automations")
        out = ask(self.factory, "how do I pause an automation?", persona="developer", project_id=p.pid)
        self.assertEqual(out["navigate"]["control"], "automations_pause")


if __name__ == "__main__":
    unittest.main()
