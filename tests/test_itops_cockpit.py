"""FR-ITO1: the IT checks in the cockpit and on the command line: the routes read and write what the kernel does, each
write signed; the map, the parity tables and Ask Rihma's operations hold together (tests/itops_fixture.py)."""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import itops_fixture as fx  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from cockpit import server as cockpit  # noqa: E402
from cockpit.solo_routes import NEEDS  # noqa: E402
from kernel import assistant_ops, parity  # noqa: E402
from kernel.assistant_rules import ui_map  # noqa: E402
from kernel.checks import infra  # noqa: E402
from kernel.checks import store as cstore  # noqa: E402
from kernel.cli import main  # noqa: E402

WHO = {"person": "Ilkka Example", "persona": "it"}


class CockpitItOpsTest(CockpitTestCase):
    def setUp(self):
        super().setUp()
        self.s = fx.Standins()
        self.addCleanup(self.s.stop)
        w = fx.populate(self.factory, self.s, self.tmp / "data")
        self.project, self.docs = w["project"], w["docs"]
        self.calls = []
        for name, fake in fx.guard(self.calls).items():
            patcher = mock.patch.object(infra, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_FR_ITO1_AC_6_the_routes_read_the_set_and_write_it_signed(self):
        pid = self.project.pid
        status, view, _ = self.call("GET", f"/api/projects/{pid}/itops")
        self.assertEqual(status, 200, view)
        self.assertEqual({t["id"] for t in view["set"]["types"]}, {"web_service", "database", "integration"})
        self.assertTrue(any(s["id"] == "it_db_nightly" for s in view["suggestions"]))
        self.assertIn("infra", {t["id"] for t in view["targets"]})
        self.assertTrue(any(r["id"] == "role:goal_plans" for r in view["evalsets"]["sets"]))
        status, out, _ = self.call("POST", f"/api/projects/{pid}/itops/apply", {"only": ["database", "dns"], **WHO})
        self.assertEqual((status, sorted(out["enabled"])), (200, ["database", "dns"]), out)
        status, out, _ = self.call("POST", f"/api/projects/{pid}/itops/run", WHO)
        self.assertEqual({r["check"]: r["verdict"] for r in out["ran"]}, {"database": "passed", "dns": "passed"}, out)
        status, out, _ = self.call("POST", f"/api/projects/{pid}/itops/assess", {"target": "family:database", **WHO})
        self.assertEqual((status, out["outcome"], out["verdict"]), (200, "done", "passed"), out)
        status, out, _ = self.call("POST", f"/api/projects/{pid}/itops/override",
                                   {"check": "tls", "action": "add", "why": "the shop", **WHO})
        self.assertEqual(next(r for r in out["set"]["checks"] if r["check"] == "tls")["scope"], "project override")
        status, out, _ = self.call("POST", "/api/itops/defaults",
                                   {"type": "documents", "check": "secrets", "action": "add", **WHO})
        self.assertEqual(status, 200, out)
        status, out, _ = self.call("GET", f"/api/projects/{self.docs.pid}/itops")
        self.assertEqual([r["check"] for r in out["set"]["checks"]], ["secrets"])
        status, out, _ = self.call("POST", f"/api/projects/{pid}/itops/evalsets", {"set": "gnomon:chaos", **WHO})
        self.assertIn("gnomon_chaos", cstore.enabled(self.project))
        status, out, _ = self.call("GET", f"/api/projects/{pid}/itops/evalsets")
        self.assertEqual([t["set"] for t in out["trends"]], ["gnomon:chaos"])
        status, out, _ = self.call("GET", "/api/itops")
        self.assertEqual(next(t for t in out["defaults"]["types"] if t["id"] == "documents")["scope"],
                         "platform default (changed by IT)")
        status, out, _ = self.call("POST", f"/api/projects/{pid}/itops/apply", {"person": "Ilkka Example",
                                                                                "persona": "end_user"})
        self.assertEqual(status, 403, out)

    def test_FR_ITO1_AC_6_every_write_has_its_persona_its_control_and_its_chat_path(self):
        writes = [name for method, _, name in cockpit.ROUTES if method == "POST" and name.startswith("post_itops")]
        self.assertEqual(len(writes), 7)
        for name in writes:
            self.assertIn(name, NEEDS, name)
        controls = {c["id"] for c in ui_map()["controls"]}
        mine = {c for c in controls if c.startswith("itops_")}
        self.assertEqual(mine, {"itops_set", "itops_apply", "itops_run", "itops_override", "itops_types",
                                "itops_defaults", "itops_default_change", "itops_assess", "itops_evalsets",
                                "itops_evalset"})
        for c in mine:
            self.assertTrue(c in parity.READS or c in parity.CHAT, c)
        self.assertEqual({v["id"] for v in ui_map()["views"] if v["id"] == "itops"}, {"itops"})
        for op in ("apply_it_checks", "run_it_checks", "change_it_check", "set_it_types", "change_it_default",
                   "run_assessment_now", "toggle_evalset"):
            self.assertIn(op, assistant_ops.OPS)
        self.assertEqual(parity.CLI_ROUTES["itops apply"], "post_itops_apply")
        self.assertEqual(parity.CLI_ROUTES["itops assess"], "post_itops_assess")

    def test_FR_ITO1_AC_6_the_command_line_shows_applies_and_assesses(self):
        def cli(*argv):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["--home", str(self.factory.home), *argv])
            return code, out.getvalue(), err.getvalue()

        code, out, err = cli("itops", "show", self.project.pid)
        self.assertEqual(code, 0, err)
        self.assertIn("database", {r["check"] for r in json.loads(out)["checks"]})
        code, out, err = cli("itops", "apply", self.project.pid, "--person", "Ilkka Example", "--persona", "it")
        self.assertEqual(code, 0, err)
        self.assertIn("database", json.loads(out)["enabled"])
        code, out, err = cli("itops", "assess", self.project.pid, "--target", "family:database", "--person",
                             "Ilkka Example", "--persona", "it")
        self.assertEqual((code, json.loads(out)["verdict"]), (0, "passed"), err)
        code, out, err = cli("itops", "apply", self.project.pid, "--person", "Ilkka Example", "--persona", "end_user")
        self.assertEqual(code, 2, (out, err))

    def test_FR_ITO2_AC_1_the_routes_record_a_port_that_answers_without_http_and_say_who_runs_the_set(self):
        from test_itops_fix import Others

        o = Others()
        self.addCleanup(o.stop)
        pid = self.project.pid
        cstore.enable(self.project, "app", person=WHO["person"], persona="it",
                      config={"url": f"http://127.0.0.1:{o.banner}/health"})
        self.call("POST", f"/api/projects/{pid}/itops/types", {"types": ["web_service"], **WHO})
        status, out, _ = self.call("POST", f"/api/projects/{pid}/itops/run", WHO)
        self.assertEqual(status, 200, out)
        self.assertEqual({r["check"]: r["verdict"] for r in out["ran"]}["app"], "failed", out)
        status, out, _ = self.call("POST", f"/api/projects/{pid}/itops/assess", {"target": "check:app", **WHO})
        self.assertEqual((status, out["verdict"]), (200, "failed"), out)
        status, view, _ = self.call("GET", f"/api/projects/{pid}/itops")
        self.assertEqual(view["setters"], ["it", "operations", "developer"])


if __name__ == "__main__":
    unittest.main()
