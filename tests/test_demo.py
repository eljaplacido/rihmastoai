"""`rihma demo` (FR-N4-AC-1): a demo factory home with no keys, no network and no Gnomon.

The demo runs once for the whole class, through the command line, with every way to Gnomon
replaced by a recorder that fails, every model key removed from the environment, and every socket
connection or name lookup beyond loopback refused. The local preview's health check is the only
connection the demo makes, and it stays on 127.0.0.1.
"""

import contextlib
import io
import os
import shutil
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from kernel import dashboard, roads
from kernel.canon import Canon
from kernel.cli import main
from kernel.learn import factory_project
from kernel.lanes import ROUTING_FILE
from kernel.signals import signals, square
from kernel.store import Factory, read_json

LOOPBACK = {"127.0.0.1", "::1", "localhost", None}


class DemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="rihma-demo-test-"))
        cls.home = cls.tmp / "demo"
        cls.gnomon_calls, cls.network = [], []

        def no_gnomon(*args, **kwargs):
            cls.gnomon_calls.append(args[:1])
            raise AssertionError("the demo called Gnomon")

        real_connect, real_lookup = socket.socket.connect, socket.getaddrinfo

        def connect(sock, address):
            host = address[0] if isinstance(address, tuple) else address
            if host not in LOOPBACK:
                cls.network.append(("connect", host))
                raise OSError(f"the test refuses a connection to {host}")
            return real_connect(sock, address)

        def lookup(host, *args, **kwargs):
            if host not in LOOPBACK:
                cls.network.append(("lookup", host))
                raise socket.gaierror(f"the test refuses a lookup of {host}")
            return real_lookup(host, *args, **kwargs)

        keys = {ep["api_key_env"] for ep in (read_json(ROUTING_FILE) or {}).get("endpoints", {}).values()
                if isinstance(ep, dict) and ep.get("api_key_env")}
        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.dict(os.environ, {"GNOMON_CMD": "rihma-demo-test-no-such-gnomon"}))
            for key in keys | {k for k in os.environ if k.endswith("_API_KEY")}:
                os.environ.pop(key, None)
            for target in ("kernel.model.run_gnomon_task", "kernel.gate.run_gnomon_task",
                           "kernel.dispatch.run_gnomon_task", "kernel.model.gnomon_cmd",
                           "kernel.model.GnomonModel.ask", "kernel.dispatch.ingest_latest_run"):
                stack.enter_context(mock.patch(target, side_effect=no_gnomon))
            stack.enter_context(mock.patch.object(socket.socket, "connect", connect))
            stack.enter_context(mock.patch.object(socket, "getaddrinfo", lookup))
            stack.enter_context(contextlib.redirect_stdout(out))
            started = time.monotonic()
            cls.exit = main(["demo", "--home", str(cls.home)])
            cls.seconds = time.monotonic() - started
        cls.output = out.getvalue()
        cls.factory = Factory(cls.home)

    @classmethod
    def tearDownClass(cls):
        roads.stop_started()
        roads.rmtree(cls.tmp)

    def projects(self):
        return {p.meta["title"]: p for p in self.factory.projects() if not p.pid.startswith("_")}

    def test_FR_N4_AC_1_the_demo_builds_a_home_with_no_keys_no_network_and_no_gnomon(self):
        self.assertEqual(self.exit, 0, self.output)
        self.assertEqual(self.gnomon_calls, [])
        self.assertEqual(self.network, [])
        self.assertLess(self.seconds, 60, f"the demo took {self.seconds:.1f} s")
        self.assertIn(f"rihma-cockpit --home {self.home.resolve()}", self.output)
        self.assertIn("python -m cockpit.server --home", self.output)
        marker = read_json(self.home / "demo.json")
        self.assertEqual(marker["schema"], "rihma.demo/1")
        for p in self.factory.projects():                                   # nothing half-written or rewritten
            self.assertTrue(p.ledger().verify().intact, p.pid)
        for p in self.projects().values():                                  # the preview was stopped again
            self.assertEqual(roads.running_slots(p), [])

    def test_FR_N4_AC_1_the_dashboard_shows_the_demo_projects_at_their_stages(self):
        projects = self.projects()
        self.assertEqual(set(projects), {"Equipment loans", "Shipment webhook to the stock system",
                                         "Access review check"})
        self.assertEqual({t: p.meta["profile"] for t, p in projects.items()},
                         {"Equipment loans": "web_service", "Shipment webhook to the stock system": "integration",
                          "Access review check": "ops_agent"})
        self.assertEqual(dashboard.pipeline(self.factory)["total"], 3)
        queue = dashboard.queue(self.factory)
        self.assertEqual(queue["by_kind"], {"question": 2, "escalation": 1, "change": 1})
        self.assertGreater(queue["oldest_hours"], 1)                        # ages, not all zero
        trend = dashboard.gate_trend(self.factory)
        self.assertGreater(trend["rounds"], 0)
        self.assertIsNotNone(trend["pass_rate"])
        self.assertTrue(dashboard.activity(self.factory))
        self.assertTrue(dashboard.timeline(projects["Access review check"])["tasks"])
        self.assertEqual(len(dashboard.coverage(self.factory)["projects"]), 2)
        self.assertGreaterEqual(dashboard.catalogue(self.factory)["counts"]["proposed"], 1)
        sq = square(self.factory)
        self.assertEqual(len(sq["concepts_waiting"]), 1)
        self.assertEqual({s["state"] for s in signals(self.factory)}, {"routed", "concept"})
        # the escalation keeps the gate's objections; the webhook's escalation was retried and merged
        access = Canon(projects["Access review check"])
        escalation = access.cards(kind="escalation")[0]
        self.assertTrue(any(o.startswith("fail_first:") for o in escalation["payload"]["objections"]))
        webhook = projects["Shipment webhook to the stock system"]
        self.assertEqual({s["status"] for s in webhook.read("tasks.json").values()}, {"merged"})
        self.assertEqual([c["decision"]["verdict"] for c in Canon(webhook).cards(state="decided", kind="escalation")],
                         ["retry"])
        release = webhook.read("releases/1.json")
        self.assertEqual((release["state"], release["maturity"]), ("done", "explore"))
        pack = webhook.read("releases/1/capability-pack.json")
        self.assertEqual(pack["format"], "rihma.capability-pack.v1")
        self.assertTrue(pack["acceptance"]["valid"])
        self.assertEqual([c["kind"] for c in Canon(webhook).cards()], ["change", "update"])
        holdouts = projects["Access review check"].holdouts_dir
        self.assertTrue(list(holdouts.glob("*.json")))                      # kept in their own custody
        self.assertFalse(str(holdouts).startswith(str(projects["Access review check"].dir)))

    def test_FR_N4_AC_1_every_decision_in_the_demo_is_made_by_a_demo_persona(self):
        decisions = []
        for p in self.factory.projects():
            decisions += Canon(p).project.read("canon/decisions.json", []) or []
            for rec in p.ledger().records():
                pl = rec["event"]["payload"]
                for key in ("person", "by", "chosen_by", "validated_by", "approved_by"):
                    if isinstance(pl.get(key), str) and pl[key]:
                        self.assertTrue(pl[key].startswith("demo-"), (p.pid, rec["event"]["kind"], key, pl[key]))
            for q in Canon(p).questions("answered"):
                self.assertTrue(q["answer"]["by"].startswith("demo-"))
            source = p.read("source.json") or {}
            if source.get("requested_by"):
                self.assertTrue(source["requested_by"].startswith("demo-"))
        self.assertGreaterEqual(len(decisions), 2)
        for d in decisions:
            self.assertTrue(d["person"].startswith("demo-"), d)
        for s in signals(self.factory):
            self.assertTrue(s["person"].startswith("demo-"), s)
        for c in Canon(factory_project(self.factory)).cards(state="decided"):
            self.assertTrue(c["decision"]["person"].startswith("demo-"))

    def test_FR_N4_AC_1_the_demo_never_overwrites_a_folder_that_is_not_a_demo_home(self):
        other = self.tmp / "real-home"
        (other / "projects").mkdir(parents=True)
        keep = other / "paved_roads.json"
        keep.write_text("{}", encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = main(["demo", "--home", str(other)])
        self.assertEqual(code, 2)
        self.assertIn("not a demo home", err.getvalue())
        self.assertTrue(keep.exists())
        shutil.rmtree(other)


if __name__ == "__main__":
    unittest.main()
