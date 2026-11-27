"""FR-NVL3: never lost when something breaks. What the never-lost acceptance run found when records were
damaged, a write failed, the cockpit restarted mid-run or a project was removed, each fixed by rule and tested
through the real cockpit server on a temp factory (tests/test_cockpit.py CockpitTestCase). No model is asked."""

import contextlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_cockpit import CockpitTestCase  # noqa: E402

from kernel.canon import Canon  # noqa: E402

DEV = {"person": "Ida Example", "persona": "developer"}


def cockpit_server_file():
    from cockpit import server

    return server.__file__


@contextlib.contextmanager
def mock_serve(made):
    """The cockpit's main() up to its listening: what home it serves is kept in ``made``, nothing listens, and the
    shared lanes root is a temporary one."""
    from unittest import mock

    from cockpit import server

    def refuse(factory, *a, **k):
        made["home"] = factory.home
        raise OSError("not listening in a test")

    with mock.patch.object(server, "make_server", refuse), \
            mock.patch.object(server, "assistant_model_for", lambda *_: (None, "")), \
            mock.patch.object(Path, "home", return_value=Path(tempfile.mkdtemp(prefix="gf-test-user-"))), \
            mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("GF_LANES", None)
        yield


class NeverLostAccTest(CockpitTestCase):
    def get(self, path):
        status, out, _ = self.call("GET", path)
        return status, out

    # -- AC-1: one unreadable project is isolated -----------------------------------------------------------

    def test_FR_NVL3_AC_1_one_unreadable_project_json_leaves_every_other_project_working(self):
        good = self.new(title="Stock levels")
        bad = self.new(title="Stress project 07")
        bad.path("project.json").write_text("not json", encoding="utf-8")
        for path in ("/api/dashboard", "/api/projects", "/api/inbox?persona=developer",
                     "/api/triage?persona=developer"):
            status, out = self.get(path)
            self.assertEqual(status, 200, (path, out))
            self.assertNotIn("Expecting value", json.dumps(out), path)
        status, out = self.get("/api/projects")
        self.assertIn(good.pid, [p["id"] for p in out])
        self.assertNotIn(bad.pid, [p["id"] for p in out])
        status, out = self.get("/api/unreadable")
        broken = out["unreadable"]
        self.assertEqual([b["id"] for b in broken], [bad.pid])
        self.assertEqual(broken[0]["title"], "Stress project 07")
        self.assertIn("Stress project 07 cannot be read (project.json is not valid", broken[0]["said"])
        self.assertIn("restore", broken[0]["how"].lower())
        status, out = self.get("/api/dashboard")
        self.assertEqual([b["id"] for b in out["unreadable"]], [bad.pid])
        # the broken project's own page names the project and the file, never the parser's words
        status, out = self.get(f"/api/projects/{bad.pid}")
        self.assertIn(status, (409, 400), out)
        self.assertIn("Stress project 07 cannot be read (project.json is not valid", out["error"])
        self.assertNotIn("Expecting value", out["error"])
        # Ask Rihma names the file
        status, out, _ = self.call("POST", "/api/assistant", {"question": "why is this project broken?",
                                                              "project": bad.pid, **DEV})
        self.assertEqual(status, 200, out)
        self.assertIn("project.json", out["answer"])
        self.assertNotIn("Expecting value", out["answer"])
        # Home and Projects name it with how to restore it
        js = self.page_js()
        self.assertIn('api("GET", "/api/unreadable")', js)
        self.assertIn("unreadableNote(d.unreadable)", js)

    # -- AC-2: a failed write is all or nothing, said plainly, and a retry works ------------------------------------

    def test_FR_NVL3_AC_2_a_write_the_disk_refuses_records_nothing_and_says_so_plainly(self):
        import errno
        from unittest import mock

        from kernel.ledgerstore import LedgerStore

        p = self.intake_project()
        before = self.snapshot(p)
        self.assertEqual(Canon(p).question("Q-001")["status"], "open")
        real = LedgerStore.append
        for code, said in ((errno.EACCES, "is read-only or in use"), (errno.ENOSPC, "The disk is full")):
            def refuse(store, kind, payload, code=code):
                raise OSError(code, os.strerror(code), str(store.path))

            with mock.patch.object(LedgerStore, "append", refuse):
                status, out, _ = self.call("POST", f"/api/projects/{p.pid}/questions/Q-001/answer",
                                           {"text": "the team lead approves", "person": "Tess Tester",
                                            "persona": "business_owner"})
            self.assertEqual(status, 507, out)
            self.assertIn(said, out["error"])
            self.assertIn("ledger.jsonl", out["error"])
            self.assertIn("Nothing was recorded", out["error"])
            self.assertNotIn("Errno", out["error"])
            self.assertNotIn(str(self.tmp), out["error"])      # never the full path
            self.assertTrue(out["plain"])
            self.assertEqual(self.snapshot(p), before)          # no decision, card still open, no record
            self.assertEqual(Canon(p).question("Q-001")["status"], "open")
        self.assertIs(LedgerStore.append, real)
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/questions/Q-001/answer",
                                   {"text": "the team lead approves", "person": "Tess Tester",
                                    "persona": "business_owner"})
        self.assertEqual(status, 200, out)
        self.assertEqual(Canon(p).question("Q-001")["status"], "answered")

    def test_FR_NVL3_AC_2_a_failed_append_cuts_the_ledger_back_and_restores_every_file(self):
        from kernel import journal
        from kernel.store import write_json

        p = self.new()
        target = p.path("canon", "decisions.json")
        was = target.read_bytes()
        size = p.path("ledger.jsonl").stat().st_size
        with self.assertRaises(OSError), journal.all_or_nothing():
            write_json(target, [{"id": "D-9"}])
            write_json(p.path("canon", "made.json"), [])
            p.log("note", {"x": 1})
            raise PermissionError(13, "Permission denied", str(p.path("ledger.jsonl")))
        self.assertEqual(target.read_bytes(), was)
        self.assertFalse(p.path("canon", "made.json").exists())
        self.assertEqual(p.path("ledger.jsonl").stat().st_size, size)
        # a rule's refusal (no errno) is not undone: it wrote nothing to undo
        with self.assertRaises(PermissionError), journal.all_or_nothing():
            write_json(target, [{"id": "D-9"}])
            raise PermissionError("a business_owner may not")
        self.assertNotEqual(target.read_bytes(), was)

    # -- AC-3: a cockpit that restarts shows the runs it had in flight ----------------------------------------------

    def restart(self):
        from cockpit.server import make_server

        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.server, bootstrap = make_server(self.factory, 0, runner=self.runner)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.origin = self.server.origin
        self.token = self.call("POST", "/auth", {"bootstrap": bootstrap}, token=None)[1]["token"]

    def console_row(self, p, jid, pid, footer=""):
        from kernel import job_registry

        log = self.factory.home / "jobs" / f"20261122T120000Z-console-{p.pid}-{jid[-4:]}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(f"$ python loop.py\n[in the working_copy workspace]\n0\n1\n{footer}", encoding="utf-8")
        job_registry.remember({"id": jid, "kind": "console", "project": p.pid, "args": ["python loop.py"],
                               "log": str(log), "started": "2026-11-22T12:00:00Z",
                               "by": {"person": "Tess Tester", "persona": "developer"}, "what": "command"})
        if pid:
            job_registry.process(log, pid)
        return log

    def test_FR_NVL3_AC_3_runs_in_flight_at_a_restart_show_as_interrupted_or_still_running_with_stop(self):
        p = self.new(title="Stock levels service")
        gone = subprocess.Popen([sys.executable, "-c", "pass"])
        gone.wait()
        orphan = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        self.addCleanup(lambda: (orphan.kill(), orphan.wait()))
        self.console_row(p, "C-0007-9da1", gone.pid)
        self.console_row(p, "C-0003-ab12", orphan.pid)
        self.restart()
        status, jobs = self.get("/api/jobs")
        self.assertEqual(status, 200, jobs)
        by_id = {j["id"]: j for j in jobs}
        self.assertEqual(by_id["C-0007-9da1"]["state"], "interrupted")
        self.assertIn("Interrupted by a cockpit restart", by_id["C-0007-9da1"]["failure"]["reason"])
        self.assertIn("Run it again", by_id["C-0007-9da1"]["failure"]["next"])
        self.assertEqual(by_id["C-0003-ab12"]["state"], "running")
        self.assertIn("from before the cockpit restarted", by_id["C-0003-ab12"]["note"])
        status, out = self.get(f"/api/projects/{p.pid}/console")
        self.assertEqual([r["id"] for r in out["runs"]], ["C-0003-ab12", "C-0007-9da1"])
        # the console's own Stop ends the orphan
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/console/runs/C-0003-ab12/stop", DEV)
        self.assertEqual(status, 200, out)
        self.assertTrue(out["stopped"])
        orphan.wait(20)
        self.assertIsNotNone(orphan.poll())
        # the next run's id goes on from the highest, never C-0001 again
        from kernel import console_run

        self.assertGreaterEqual(console_run.JOBS._n, 7)
        # Ask Rihma never says nothing runs: it names the interrupted run
        status, out = self.get("/api/why?view=jobs&kind=empty")
        self.assertIn("interrupted when the cockpit restarted", out["answer"])
        self.assertNotIn("nothing is running", out["answer"])
        # and a third restart keeps them as they ended
        self.restart()
        by_id = {j["id"]: j for j in self.get("/api/jobs")[1]}
        self.assertEqual((by_id["C-0007-9da1"]["state"], by_id["C-0003-ab12"]["state"]), ("interrupted", "stopped"))

    # -- AC-5: a run ended from outside is said as one, and Ask Rihma answers about that job --------------------------

    def test_FR_NVL3_AC_5_a_killed_run_says_it_was_ended_from_outside_and_ask_rihma_answers_about_it(self):
        from kernel import job_registry, job_words

        p = self.new(title="Stock levels service")
        log = self.console_row(p, "C-0002-cd34", None, footer="[exit 4294967295 after 10.0 s]\n")
        job_registry.ended(log, "failed", 4294967295)
        self.restart()
        job = next(j for j in self.get("/api/jobs")[1] if j["id"] == "C-0002-cd34")
        self.assertEqual((job["state"], job["code"]), ("failed", -1))
        self.assertIn("ended from outside after 10 s (exit -1)", job["failure"]["reason"])
        self.assertIn("Run it again", job["failure"]["next"])
        # the button sends the job's own failure: the answer is about this job, by rule
        status, out, _ = self.call("POST", "/api/assistant", {
            "question": "Why did Console (C-0002-cd34) fail?", "view": "jobs", "why": {
                "view": "jobs", "field": job["title"], "kind": "error", "basis": job["failure"]["reason"]}, **DEV})
        self.assertEqual(status, 200, out)
        self.assertIn("ended from outside", out["answer"])
        self.assertEqual(out["fill"]["route"], "#/jobs")
        # typed, it is found from the log too
        self.assertIn("ended from outside", job_words.answer(self.factory, p)["answer"])
        self.assertIn("job_ask", self.page_js())
        self.assertIn("jobActions(j)", self.page_js())

    # -- AC-6: a panel the model answered nothing usable for is never a done stage --------------------------------

    def test_FR_NVL3_AC_6_a_panel_with_no_usable_answer_says_the_model_is_the_reason_not_a_done_stage(self):
        from kernel import next_step, status
        from kernel.intake import intake
        from kernel.model import FakeModel

        p = self.new(title="Stock levels service")
        bad = FakeModel(lambda prompt, role: '{"output":"The Inbox is under Inbox in the sidebar."}'[12:-2])
        intake(p, "Track stock levels in the warehouse", model=bad, requested_by="Tess Tester")
        readings = p.read("readings.json")
        self.assertTrue(readings and all(r == "(no usable answer; not measured)" for r in readings.values()))
        line = status.now(p)
        self.assertEqual(line["state"], "failed")
        self.assertIn("The model gave no usable answer to the panel: check Models setup", line["line"])
        self.assertNotIn("ready for the next step", line["line"])
        nxt = next_step.next_step(p)
        self.assertEqual(nxt["state"], "model_not_set_up")
        self.assertIn("Run the panel again", [a["label"] for a in nxt["actions"]])
        # Why next to "(no usable answer; not measured)": the model, never "the project is still early", no stray ")"
        status_, out = self.get(f"/api/why?project={p.pid}&view=overview&kind=not_measured&field=business_owner"
                                "&basis=(no%20usable%20answer%3B%20not%20measured)")
        self.assertEqual(status_, 200, out)
        self.assertIn("the model gave no usable answer", out["answer"])
        self.assertNotIn("still early", out["answer"])
        self.assertNotIn('"\x29"', out["answer"])
        self.assertEqual(out["fill"]["view"], "models")
        # a panel that answers next time clears it
        intake(p, "Track stock levels in the warehouse", model=self.good_model(), requested_by="Tess Tester")
        self.assertIsNone(p.meta.get("panel_unusable"))

    def good_model(self):
        from factory_fakes import model

        return model()

    # -- AC-7: a demo or marked home keeps its lanes; a shared root is said ------------------------------------------

    def test_FR_NVL3_AC_7_a_demo_home_keeps_its_own_lanes_and_a_shared_lanes_root_is_warned(self):
        from unittest import mock

        from kernel import lanes, lanes_home

        user = self.tmp / "user"
        demo = self.tmp / "demo"
        demo.mkdir()
        (demo / "demo.json").write_text("{}", encoding="utf-8")
        env = {}
        with mock.patch.object(Path, "home", return_value=user):
            said = lanes_home.settle(demo, env)
            self.assertEqual(env["GF_LANES"], str((demo / "lanes").resolve()))
            self.assertIn("inside this home", said)
            with mock.patch.dict(os.environ, env):
                self.assertEqual(lanes.lanes_root(), (demo / "lanes").resolve())
            # GF_LANES set by the person stands
            self.assertIn("(GF_LANES)", lanes_home.settle(demo, {"GF_LANES": str(self.tmp / "mine")}))
            # two real homes on the shared root: the second is warned, with how to keep them apart
            one, two = self.tmp / "one", self.tmp / "two"
            one.mkdir()
            two.mkdir()
            self.assertEqual(lanes_home.settle(one, {}), f"Lanes: {user / 'gf-lanes'}.")
            said = lanes_home.settle(two, {})
            self.assertIn("is shared with another home", said)
            self.assertIn(str(one.resolve()), said)
            self.assertIn("GF_LANES", said)
        # the cockpit prints it at start
        self.assertIn("klanes_home.settle(factory.home)", Path(cockpit_server_file()).read_text(encoding="utf-8"))

    # -- AC-8: a relative home works, and a git failure is said in plain words -----------------------------------

    def test_FR_NVL3_AC_8_a_relative_home_is_made_absolute_and_git_failures_are_plain(self):
        from kernel import console

        said = console.git_said("Cloning into 'x'...\nlfs smudge --skip -- %f -c filter.lfs.process=git-lfs\n"
                                "fatal: repository '..\\home\\projects\\p\\repo.git' does not exist")
        self.assertIn("the project's repository (repo.git) was not found", said)
        self.assertNotIn("lfs smudge", said)
        self.assertNotIn("filter.lfs", said)
        self.assertIn('git said "unable to access', console.git_said("fatal: unable to access the remote"))
        # the cockpit started with a relative --home serves the absolute one
        from cockpit import server as cockpit_server

        made = {}
        here = os.getcwd()
        os.chdir(self.tmp)
        try:
            with mock_serve(made):
                cockpit_server.main(["--home", "home", "--port", "0", "--quiet"])
        finally:
            os.chdir(here)
        self.assertTrue(made["home"].is_absolute())
        self.assertEqual(made["home"], (self.tmp / "home").resolve())
        # and the console clones from an absolute path
        self.assertIn('project.path("repo.git").resolve()', Path(console.__file__).read_text(encoding="utf-8"))
        # an old failure's toast is cleared when the person goes to another page
        self.assertIn('$$("#status .toast.critical")', self.page_js())

    # -- AC-9: Data and context opens at once; context health is measured once while nothing changed -----------------

    def test_FR_NVL3_AC_9_context_health_is_kept_while_the_records_stand_and_the_page_opens_at_once(self):
        from unittest import mock

        from kernel import context_audit

        p = self.new(title="Stock levels service")
        self.new(title="Equipment loans")
        real = context_audit.project_audit
        with mock.patch.object(context_audit, "project_audit", side_effect=real) as built:
            first = self.get("/api/context/health")
            self.assertEqual(first[0], 200, first[1])
            self.assertEqual(built.call_count, 2)
            self.assertEqual(self.get("/api/context/health"), first)
            self.assertEqual(built.call_count, 2)               # nothing changed: nothing measured again
            p.log("note", {"what": "a change"})
            self.get("/api/context/health")
            self.assertEqual(built.call_count, 3)               # the changed project only
        js = self.page_js()
        self.assertIn('"data-loading": "context-health"', js)
        self.assertIn('"data-loading": "data"', js)

    # -- AC-10: Home asked in many tabs at once is built once ------------------------------------------------------

    def test_FR_NVL3_AC_10_dashboards_asked_at_once_share_one_build(self):
        import time
        from unittest import mock

        from cockpit import server as cockpit_server

        self.new(title="Stock levels service")
        real = cockpit_server.Api._dashboard
        calls = []

        def slow(api):
            calls.append(1)
            time.sleep(0.6)
            return real(api)

        answers = []
        with mock.patch.object(cockpit_server.Api, "_dashboard", slow):
            started = time.monotonic()
            threads = [threading.Thread(target=lambda: answers.append(self.get("/api/dashboard"))) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
            took = time.monotonic() - started
        self.assertEqual([a[0] for a in answers], [200] * 8)
        self.assertLessEqual(len(calls), 2, "eight tabs at once share the build")
        self.assertLess(took, 3.0)
        # a write after it: the next dashboard is built again, never an old answer
        before = len(calls)
        self.call("POST", "/api/projects", {"title": "Third one", "person": "Ida Example", "persona": "business_owner"})
        with mock.patch.object(cockpit_server.Api, "_dashboard", slow):
            self.get("/api/dashboard")
        self.assertEqual(len(calls), before + 1)

    # -- AC-4: a removed project's old link says what happened, and Ask Rihma goes on at the platform -------------

    def test_FR_NVL3_AC_4_a_removed_projects_link_names_who_removed_it_and_where_its_records_are(self):
        from kernel import project_archive

        gone = self.new(title="Access review check")
        project_archive.archive(self.factory, gone.pid, person="Tess Tester", persona="developer")
        project_archive.remove(self.factory, gone.pid, person="Tess Tester", persona="developer", confirm=gone.pid)
        status, out = self.get(f"/api/projects/{gone.pid}")
        self.assertEqual(status, 410, out)
        self.assertRegex(out["error"], r"Access review check was removed on 2026-11-22 by Tess Tester; its records "
                                       r"are kept in exports/removed/\S+\.zip")
        status, out = self.get("/api/projects/never-was-123")
        self.assertEqual(status, 404, out)
        self.assertIn("no project never-was-123", out["error"])
        # Why? Ask Rihma on the page: the removal, by rule, with the way back; never the error again
        why = {"view": "project", "kind": "error", "basis": "no project " + gone.pid}
        status, out, _ = self.call("POST", "/api/assistant", {"question": "Why did this fail here?",
                                                              "project": gone.pid, "why": why, **DEV})
        self.assertEqual(status, 200, out)
        self.assertIn("was removed on 2026-11-22 by Tess Tester", out["answer"])
        self.assertEqual(out["fill"]["route"], "#/projects")
        self.assertIn("who", out)
        status, out = self.get(f"/api/why?project={gone.pid}&view=overview&kind=error")
        self.assertEqual(status, 200, out)
        self.assertIn("was removed", out["answer"])
        # a typed question is answered at the platform scope, not refused
        status, out, _ = self.call("POST", "/api/assistant", {"question": "What should I do next?",
                                                              "project": gone.pid, **DEV})
        self.assertEqual(status, 200, out)
        self.assertNotIn("no project", out["answer"])
        # the page draws a plain panel with the way back, never a bug report
        js = self.page_js()
        self.assertIn("This project is not here", js)
        self.assertIn("goneProject(e, r.pid)", js)
