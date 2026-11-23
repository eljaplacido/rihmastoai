import json
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model  # noqa: E402

from kernel.compile import author_holdouts, compile_project, contract_check, to_contract  # noqa: E402
from kernel.dispatch import envelope  # noqa: E402
from kernel.filelock import LockHeld  # noqa: E402
from kernel.gate import run_suite  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."


def specced(case):
    p = case.new(mode="assume")
    intake(p, IDEA, model=model(), requested_by="Aino")
    make_spec(p, model=model())
    return p


class CompileTest(FactoryTestCase):
    def test_FR_O2_AC_5_same_spec_same_revision_and_the_contract_passes_the_check(self):
        p = specced(self)
        a = to_contract(p, p.read("spec.json"))
        b = to_contract(p, json.loads(json.dumps(p.read("spec.json"))))
        self.assertEqual(a["revision"], b["revision"])
        report, _ = contract_check().check(a)
        self.assertEqual(report.violations, [])
        self.assertEqual(a["counts"], {"requirements": 4, "criteria": 6, "tasks": 4})
        self.assertEqual(a["tasks"][1]["depends_on"], ["T-001"])

    def test_FR_O2_AC_5_the_scaffolded_product_passes_its_own_suite(self):
        p = specced(self)
        contract = compile_project(p)
        work = self.tmp / "clone"
        subprocess.run(["git", "clone", "-q", str(p.path("repo.git")), str(work)], check=True)
        self.assertEqual(json.loads((work / "contract.json").read_text(encoding="utf-8"))["revision"],
                         contract["revision"])
        res = run_suite(work)
        self.assertEqual(res["exit"], 0, res)
        self.assertEqual(res["ran"], 4)

    def test_FR_O3_AC_1_holdouts_live_outside_the_project_and_never_in_an_envelope(self):
        p = specced(self)
        contract = compile_project(p)
        saved = author_holdouts(p, model=model())
        self.assertEqual(sorted(saved), ["R-1-AC-2", "R-4-AC-2"])
        for cid in saved:
            path = p.holdouts_dir / f"{cid}.json"
            self.assertTrue(path.exists())
            self.assertNotIn(str(p.dir), str(path.resolve()))
        found = [f for f in p.dir.rglob("*") if f.is_file() and "R-1-AC-2.json" in f.name]
        self.assertEqual(found, [])
        text = envelope(p, contract, "T-001", base="0" * 40)
        self.assertIn("R-1-AC-1", text)
        self.assertNotIn("R-1-AC-2", text)
        self.assertIn("checked end to end", text)

    def test_FR_C2_AC_3_product_surface_grants_nothing_beyond_the_defaults(self):
        p = specced(self)
        compile_project(p)
        work = self.tmp / "clone"
        subprocess.run(["git", "clone", "-q", str(p.path("repo.git")), str(work)], check=True)
        policy = tomllib.loads((work / ".gnomon" / "policy.toml").read_text(encoding="utf-8"))
        self.assertNotIn("verify", policy)
        self.assertNotIn("readonly_bash", policy.get("approval", {}))
        self.assertFalse(policy["sandbox"]["network"])
        roles = tomllib.loads((work / ".gnomon" / "roles.toml").read_text(encoding="utf-8"))["roles"]
        self.assertEqual(roles["builder"]["write_allow"], ["app/**", "tests/**"])
        deny = " ".join(roles["builder"]["bash_deny"])
        for word in ("push", "reset", "clean", "branch", "no-verify"):
            self.assertIn(word, deny)
        self.assertNotIn("write", roles["verifier"]["tools"])
        self.assertNotIn("bash", roles["verifier"]["tools"])
        self.assertNotEqual(roles["builder"]["model"], roles["verifier"]["model"])

    def test_FR_C2_AC_4_one_holder_per_lane(self):
        lanes = Lanes(self.tmp / "lanes", size=1)
        with lanes.lease("p:T-001") as lane:
            self.assertEqual(lane.name, "lane-1")
            with self.assertRaises(LockHeld):
                with Lanes(self.tmp / "lanes", size=1).lease("p:T-002"):
                    pass
        with lanes.lease("p:T-002") as lane:  # free again after release
            self.assertEqual(lane.name, "lane-1")

    def test_FR_O2_AC_5_the_product_serves_its_routes_when_started_as_a_module(self):
        import os
        import socket
        import time
        import urllib.request

        p = specced(self)
        compile_project(p)
        work = self.tmp / "clone"
        subprocess.run(["git", "clone", "-q", str(p.path("repo.git")), str(work)], check=True)
        (work / "app" / "routes.py").write_text(
            "from app.server import route\n\n\n@route('GET', '/ping')\ndef ping(req):\n    return 200, {'pong': True}\n",
            encoding="utf-8", newline="\n")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        env = dict(os.environ, PORT=str(port), HOST="127.0.0.1", DATA_DIR=str(self.tmp / "data"))
        proc = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=work, env=env)
        try:
            for _ in range(50):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1) as r:
                        self.assertEqual(r.status, 200)
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                self.fail("the product never served /ping")
        finally:
            proc.terminate()
            proc.wait(timeout=10)

    def test_FR_C2_AC_3_the_analyst_lane_has_no_tools_and_grants_nothing(self):
        from kernel.lanes import ensure_analyst_lane, load_routing

        lane = ensure_analyst_lane(load_routing(), root=self.tmp / "lanes")
        roles = tomllib.loads((lane / ".gnomon" / "roles.toml").read_text(encoding="utf-8"))["roles"]
        self.assertEqual({r: v["tools"] for r, v in roles.items()}, {"analyst": [], "holdout_author": [], "assistant": []})
        policy = tomllib.loads((lane / ".gnomon" / "policy.toml").read_text(encoding="utf-8"))
        self.assertNotIn("verify", policy)

    def test_FR_O3_AC_1_missing_holdouts_are_written_late_without_overwriting_existing_ones(self):
        p = specced(self)
        compile_project(p)
        author_holdouts(p, model=model())
        (p.holdouts_dir / "R-1-AC-2.json").unlink()
        kept = (p.holdouts_dir / "R-4-AC-2.json").read_text(encoding="utf-8")
        self.assertEqual(author_holdouts(p, model=model(), only="missing"), ["R-1-AC-2"])
        self.assertEqual((p.holdouts_dir / "R-4-AC-2.json").read_text(encoding="utf-8"), kept)
        self.assertEqual(author_holdouts(p, model=model(), only="missing"), [])
        with self.assertRaises(PermissionError):           # overwriting one needs a person's ruling
            author_holdouts(p, model=model(), only=["R-4-AC-2"])

    def test_FR_E4_AC_1_one_interface_is_shown_to_the_builder_and_the_holdout_author(self):
        from kernel.compile import holdout_prompt
        from kernel.spec import interface_of

        p = specced(self)
        spec = p.read("spec.json")
        self.assertEqual([(e["method"], e["path"]) for e in spec["interface"]],
                         [("POST", "/items"), ("GET", "/items"), ("POST", "/items/{id}/loan"),
                          ("GET", "/report"), ("GET", "/health")])   # read from the criteria' paths
        contract = compile_project(p)
        envelope_text = envelope(p, contract, "T-001", base="0" * 40)
        rows = [r for r in p.read("checkplan.json")["checks"] if r["kind"] != "test"]
        holdout_text = holdout_prompt(spec, rows)
        for e in interface_of(spec):
            line = f"- {e['method']} {e['path']}:"
            self.assertIn(line, envelope_text)
            self.assertIn(line, holdout_text)
        self.assertIn("use exactly these paths", envelope_text)
        self.assertIn("Use exactly these methods and paths", holdout_text)
        self.assertIn("## Interface", p.path("spec.md").read_text(encoding="utf-8"))

    def test_FR_E4_AC_2_criteria_written_as_handler_calls_name_the_interface_too(self):
        from kernel.spec import interface_from_criteria

        reqs = [{"acceptance": [
            {"given": "a signed payload", "when": "handle('POST', '/carriers/carrier-a/events', payload) runs",
             "then": "it returns 202 and handle('GET', '/events/A-1001') returns the event"},
            {"given": "-", "when": 'handle("GET", "/metrics/backlog?window=24h") runs', "then": "200"},
            {"given": "-", "when": "GET /health", "then": "200"}]}]
        self.assertEqual([(e["method"], e["path"]) for e in interface_from_criteria(reqs)],
                         [("POST", "/carriers/carrier-a/events"), ("GET", "/events/A-1001"),
                          ("GET", "/metrics/backlog"), ("GET", "/health")])

    def test_FR_O3_AC_2_a_rewrite_sees_the_persons_reason_and_what_the_service_answered(self):
        from kernel.model import FakeModel

        p = specced(self)
        compile_project(p)
        author_holdouts(p, model=model())
        prompts = []

        def recording(prompt, role):
            prompts.append(prompt)
            return model().ask(prompt, role=role)

        failing = [{"criterion": "R-1-AC-2", "request": {"method": "GET", "path": "/items/E001"},
                    "expected": {"expect_status": 200}, "observed": {"status": 404, "body": {"error": "not found"}}},
                   {"criterion": "R-9-AC-9", "request": {}, "expected": {}, "observed": {}}]
        saved = author_holdouts(p, model=FakeModel(recording), only=["R-1-AC-2"], person="test-developer",
                                reason="The spec fixes no seed ids; list the items first.", evidence=failing)
        self.assertEqual(saved, ["R-1-AC-2"])
        self.assertIn("Their reason: The spec fixes no seed ids; list the items first.", prompts[0])
        self.assertIn('"status": 404', prompts[0])
        self.assertNotIn("R-9-AC-9", prompts[0])                   # only the criteria being rewritten
        self.assertIn("never guess its ids", prompts[0])
        first = []
        author_holdouts(p, model=FakeModel(lambda pr, role: first.append(pr) or model().ask(pr, role=role)),
                        only="missing")
        self.assertEqual(first, [])                                # nothing missing: no call at all

    def test_FR_F5_AC_1_a_holder_waits_for_a_free_lane_and_never_shares_one(self):
        import threading
        import time

        lanes = Lanes(self.tmp / "lanes", size=1)
        held = threading.Event()
        release = threading.Event()

        def first():
            with lanes.lease("p:T-001"):
                held.set()
                release.wait(5)

        t = threading.Thread(target=first)
        t.start()
        held.wait(5)
        with self.assertRaises(LockHeld):                     # no wait: refused at once
            with lanes.lease("p:T-002"):
                pass
        threading.Timer(0.5, release.set).start()
        started = time.monotonic()
        with lanes.lease("p:T-002", wait=10, poll=0.1) as lane:   # waits, then gets the lane
            self.assertEqual(lane.name, "lane-1")
            self.assertGreaterEqual(time.monotonic() - started, 0.4)
        t.join(5)
        self.assertEqual(Lanes(self.tmp / "x", size=None).size, 3)   # the default pool

    def test_FR_U1_AC_1_the_look_is_asked_once_and_the_product_ships_its_design_system(self):
        from kernel.canon import Canon
        from kernel.intake import LOOK_QUESTION

        p = self.new(mode="socratic")
        intake(p, IDEA, model=model(), requested_by="Aino")
        looks = [q for q in Canon(p).questions() if q["text"] == LOOK_QUESTION]
        self.assertEqual(len(looks), 1)                                  # asked once
        Canon(p).answer(looks[0]["id"], "Warm, please", person="Aino", persona="business_owner")
        Canon(p).answer("Q-001", "the team lead approves", person="Aino", persona="business_owner")
        spec = make_spec(p, model=model())
        self.assertEqual(spec["look"], "warm")
        contract = compile_project(p)
        work = self.tmp / "clone"
        subprocess.run(["git", "clone", "-q", str(p.path("repo.git")), str(work)], check=True)
        self.assertEqual(json.loads((work / "factory" / "look.json").read_text(encoding="utf-8")), {"look": "warm"})
        self.assertIn("esc()", (work / "factory" / "DESIGN.md").read_text(encoding="utf-8"))
        self.assertIn("--accent", (work / "app" / "static" / "product.css").read_text(encoding="utf-8"))
        self.assertIn("COPY factory/look.json", (work / "Dockerfile").read_text(encoding="utf-8"))
        self.assertIn("factory/DESIGN.md", envelope(p, contract, "T-001", base="0" * 40))
        self.assertEqual(run_suite(work)["exit"], 0)
        other = specced(self)                                            # assume mode: neutral by default
        self.assertEqual(other.read("spec.json")["look"], "neutral")

    def test_FR_G6_AC_1_roles_fall_back_on_endpoint_failure_but_the_verifier_never_shares_a_family(self):
        import copy

        from kernel.compile import update_repo_surface
        from kernel.lanes import check_routing, load_routing

        routing = load_routing()
        p = specced(self)
        compile_project(p)
        work = self.tmp / "clone"
        subprocess.run(["git", "clone", "-q", str(p.path("repo.git")), str(work)], check=True)
        roles = tomllib.loads((work / ".gnomon" / "roles.toml").read_text(encoding="utf-8"))["roles"]
        fallback = routing["roles"]["builder"]["fallback"]
        self.assertEqual(roles["builder"]["fallback"], fallback)
        self.assertNotIn("fallback", roles["verifier"])
        config = tomllib.loads((work / ".gnomon" / "config.toml").read_text(encoding="utf-8"))
        self.assertIn(fallback["endpoint"], config["endpoints"])          # the fallback's endpoint is declared
        bad = copy.deepcopy(routing)
        bad["roles"]["builder"]["fallback"] = {"model": "glm-5.3", "endpoint": "go"}
        with self.assertRaises(ValueError):
            check_routing(bad)                                              # fallback in the verifier's family
        bad = copy.deepcopy(routing)
        bad["roles"]["verifier"]["fallback"] = dict(fallback)
        with self.assertRaises(ValueError):
            check_routing(bad)                                              # a verifier never falls back
        old = copy.deepcopy(routing)
        del old["roles"]["builder"]["fallback"]
        self.assertIsNone(update_repo_surface(p, routing))                  # unchanged: nothing committed
        rev = update_repo_surface(p, old, reason="test: drop the fallback")
        self.assertTrue(rev)
        self.assertEqual(p.ledger().of_kind("surface_updated")[-1]["event"]["payload"]["revision"], rev)


class RoutingOverlayTest(unittest.TestCase):
    """The shipped routing names no machine; a machine's own routing is a gitignored overlay."""

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory(prefix="gf-routing-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def patched(self, overlay):
        """The shipped routing as a temporary file, and ``overlay`` (a dict, raw text or None) as
        the machine's routing.local.json beside it."""
        from unittest import mock

        import kernel.lanes as lanes

        shipped = json.loads(lanes.ROUTING_FILE.read_text(encoding="utf-8"))
        (self.tmp / "routing.json").write_text(json.dumps(shipped), encoding="utf-8")
        local = self.tmp / "routing.local.json"
        local.unlink(missing_ok=True)
        if overlay is not None:
            local.write_text(overlay if isinstance(overlay, str) else json.dumps(overlay), encoding="utf-8")
        for name, path in (("ROUTING_FILE", self.tmp / "routing.json"), ("ROUTING_LOCAL_FILE", local)):
            patch = mock.patch.object(lanes, name, path)
            patch.start()
            self.addCleanup(patch.stop)
        return shipped

    def test_FR_G6_AC_1_the_shipped_routing_reaches_only_loopback_or_public_endpoints(self):
        from urllib.parse import urlsplit

        from kernel.lanes import ROUTING_FILE, load_routing

        shipped = load_routing(ROUTING_FILE)
        for name, ep in shipped["endpoints"].items():
            parts = urlsplit(ep["url"])
            self.assertIn(parts.scheme, ("http", "https"), name)
            if parts.scheme == "http":                                     # plain http: this machine only
                self.assertEqual(parts.hostname, "127.0.0.1", name)
        self.assertEqual(shipped["roles"]["assistant"]["endpoint"], "local")

    def test_FR_G6_AC_1_a_machine_overlay_is_merged_over_the_shipped_routing_and_checked_the_same_way(self):
        from kernel.lanes import load_routing, read_routing

        shipped = self.patched(None)
        self.assertEqual(load_routing(), shipped)                          # no overlay: the shipped file
        box = {"kind": "openai", "url": "http://gpu-box.example:18080/v1/chat/completions"}
        self.patched({"roles": {"assistant": {"model": "qwen3.6-35b", "endpoint": "box"}},
                      "endpoints": {"box": box}, "max_context_tokens": 65536})
        merged = load_routing()
        self.assertEqual(merged["roles"]["assistant"], {"model": "qwen3.6-35b", "endpoint": "box"})  # whole
        self.assertEqual(merged["roles"]["builder"], shipped["roles"]["builder"])
        self.assertEqual(merged["endpoints"]["box"], box)
        self.assertEqual(set(merged["endpoints"]), set(shipped["endpoints"]) | {"box"})
        self.assertEqual(merged["max_context_tokens"], 65536)
        self.assertEqual(load_routing(self.tmp / "routing.json"), shipped)  # a path reads that file alone
        builder = shipped["roles"]["builder"]
        self.patched({"roles": {"verifier": {"model": builder["model"], "endpoint": builder["endpoint"]}}})
        with self.assertRaises(ValueError) as caught:
            load_routing()
        self.assertIn("different model family", str(caught.exception))
        self.patched("{not json")
        with self.assertRaises(ValueError) as caught:
            read_routing()
        self.assertIn("routing.local.json", str(caught.exception))
        self.patched({"endpoints": ["not", "an", "object"]})
        with self.assertRaises(ValueError):
            read_routing()

    def test_FR_N2_AC_2_doctor_reads_the_key_variables_of_the_routing_with_the_machine_overlay(self):
        from kernel.doctor import doctor

        self.patched({"endpoints": {"box": {"kind": "openai", "url": "https://gpu-box.example/v1/chat/completions",
                                            "api_key_env": "BOX_API_KEY"}}})
        report = doctor(self.tmp / "home", gnomon=[sys.executable, "-c", "print('gnomon/0.6.6+npm')"],
                        lanes_root=self.tmp / "lanes", environ={"BOX_API_KEY": "sk-not-printed"})
        self.assertIn({"name": "box", "api_key_env": "BOX_API_KEY", "set": True}, report["endpoints"])
        self.assertTrue(report["routing_overlay"]["present"])
        self.assertNotIn("sk-not-printed", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
