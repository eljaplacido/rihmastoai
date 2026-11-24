"""A confidential project skips a local role's hosted fallback (FR-MAT1-AC-10; the owner's decision of 2026-11-24).

A role whose primary endpoint is on this machine or the owner's network but whose fallback is hosted is no
longer refused: the fallback is skipped, never called, and the ledger records the skip once per run. A role
whose primary is hosted is refused as before. The lanes a confidential project's calls run in are compiled
without the hosted fallback, so Gnomon has nothing to fall back to: a stand-in Gnomon (tests/fixtures/
stub_gnomon.py) that falls back exactly as Gnomon does sends nothing to a "hosted" stub on 127.0.0.1, while
the same call for a project that is not confidential does reach it. Scripted models only; the only network is
two stubs on 127.0.0.1.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory_fakes import model as scripted  # noqa: E402

from kernel import confidential, lanes  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.model import GnomonModel, ModelError  # noqa: E402
from kernel.models_setup import _fallback_note  # noqa: E402
from kernel.pipeline import advance  # noqa: E402
from kernel.store import Factory, read_json  # noqa: E402

STUB = Path(__file__).parent / "fixtures" / "stub_gnomon.py"
HOSTED = "api.hosted.example"


def _routing(local_port: int) -> dict:
    """Every role local on 127.0.0.1, the analyst's and the builder's fallback hosted."""
    shipped = read_json(lanes.ROUTING_FILE)
    endpoints = {"box": {"kind": "openai", "url": f"http://127.0.0.1:{local_port}/v1/chat/completions"},
                 "far": {"kind": "openai", "url": f"https://{HOSTED}/v1/chat/completions", "api_key_env": "FAR_KEY"}}
    roles = {r: {"model": "qwen-box" if r != "verifier" else "llama-box", "endpoint": "box"}
             for r in shipped["roles"]}
    for r in ("analyst", "builder"):
        roles[r]["fallback"] = {"model": "deepseek-far", "endpoint": "far"}
    return {**shipped, "roles": roles, "endpoints": endpoints,
            "models": {"qwen-box": {"family": "qwen"}, "llama-box": {"family": "llama"},
                       "deepseek-far": {"family": "deepseek"}}}


class _Stub:
    """An OpenAI-compatible stub on 127.0.0.1 that counts what reaches it; ``fail`` answers 500."""

    def __init__(self, fail: bool) -> None:
        stub = self
        self.hits: list[str] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                stub.hits.append(body.decode("utf-8", "replace"))
                code, out = (500, b"{}") if fail else (200, json.dumps(
                    {"choices": [{"message": {"content": "answered by the hosted stub"}}]}).encode())
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class ConfidentialSkipTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-conf-skip-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.local, self.hosted = _Stub(fail=True), _Stub(fail=False)
        self.addCleanup(self.local.close)
        self.addCleanup(self.hosted.close)
        folder = self.tmp / "routing"
        folder.mkdir()
        shutil.copyfile(lanes.ROUTING_FILE, folder / "routing.json")
        (folder / "routing.local.json").write_text(json.dumps(_routing(self.local.port)), encoding="utf-8")
        for name, path in (("ROUTING_FILE", folder / "routing.json"),
                           ("ROUTING_LOCAL_FILE", folder / "routing.local.json")):
            patcher = mock.patch.object(lanes, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {
            "GNOMON_CMD": f"{Path(sys.executable).as_posix()} {STUB.as_posix()}",
            lanes.LANES_ENV: str(self.tmp / "lanes"),
            "STUB_GNOMON_HOSTS": json.dumps({HOSTED: f"127.0.0.1:{self.hosted.port}"}), "FAR_KEY": "stub"})
        env.start()
        self.addCleanup(env.stop)
        self.factory = Factory(self.tmp / "home")
        self.routing = lanes.load_routing()

    def project(self, secret: bool):
        p = self.factory.new_project("Payroll notes" if secret else "Equipment loans", maturity="demo", mode="assume")
        if secret:
            confidential.mark(p, person="Aino Virtanen", persona="business_owner")
        return p

    def skips(self, p) -> list:
        return [r["event"]["payload"] for r in p.ledger().of_kind("confidential_fallback_skipped")]

    def test_FR_MAT1_AC_10_a_local_role_with_a_hosted_fallback_is_not_refused_and_its_skip_is_recorded(self):
        p = self.project(secret=True)
        self.assertEqual(confidential.refusal(["analyst", "builder"]), "")
        confidential.require_local(p, ("analyst",), where="intake")
        self.assertEqual(self.skips(p), [{"role": "analyst", "endpoint": "far", "host": HOSTED, "where": "intake",
                                          "why": "confidential: the hosted fallback is never called"}])
        self.assertEqual(p.ledger().of_kind("confidential_refused"), [])
        note = _fallback_note("analyst", self.routing)["note"]
        self.assertIn("skips it (never calls it)", note)

    def test_FR_MAT1_AC_10_a_role_whose_primary_is_hosted_is_still_refused(self):
        p = self.project(secret=True)
        hosted = {**self.routing, "roles": {**self.routing["roles"],
                                            "analyst": {"model": "deepseek-far", "endpoint": "far"}}}
        with self.assertRaises(confidential.ConfidentialRefused) as caught:
            confidential.require_local(p, ("analyst",), where="intake", routing=hosted)
        self.assertIn("the analyst role would go to the hosted endpoint 'far'", str(caught.exception))
        self.assertEqual(p.ledger().of_kind("confidential_refused")[-1]["event"]["payload"]["hosted"],
                         [{"role": "analyst", "which": "primary", "endpoint": "far"}])

    def test_FR_MAT1_AC_10_the_skip_is_recorded_once_per_run(self):
        p = self.project(secret=True)
        intake(p, "Equipment loans for the team.", model=scripted(), requested_by="Aino Virtanen")
        self.assertEqual([(s["role"], s["where"]) for s in self.skips(p)], [("analyst", "intake")])  # a call alone
        with confidential.one_run():
            for where in ("spec", "inputs refine", "spec"):
                confidential.require_local(p, ("analyst",), where=where)
            confidential.require_local(p, ("builder", "verifier"), where="build")
        run = self.skips(p)[1:]
        self.assertEqual([(s["role"], s["where"], s["host"]) for s in run],
                         [("analyst", "spec", HOSTED), ("builder", "build", HOSTED)])   # once each in the run
        def twice(project, **_):                                                # a pass that asks the analyst twice
            for where in ("spec", "holdouts"):
                confidential.require_local(project, ("analyst",), where=where)
            return {"state": "progress"}

        with mock.patch("kernel.pipeline._advance", twice):
            advance(p, model=scripted())                                        # the pipeline's run is one run
            advance(p, model=scripted())                                        # and the next is another
        self.assertEqual([s["where"] for s in self.skips(p)[3:]], ["spec", "spec"])

    def test_FR_MAT1_AC_10_no_request_reaches_the_hosted_endpoint_from_a_confidential_project(self):
        shared = GnomonModel(lanes.ensure_analyst_lane(self.routing), timeout=60)
        control = self.project(secret=False)
        self.assertEqual(confidential.guard(control, shared, ("analyst",), where="test"), shared)
        self.assertEqual(shared.ask("Say OK.", role="analyst"), "answered by the hosted stub")   # Gnomon falls back
        self.assertEqual(len(self.hosted.hits), 1)
        p = self.project(secret=True)
        safe = confidential.guard(p, shared, ("analyst",), where="intake")
        self.assertIsInstance(safe, confidential.LocalLaneModel)
        with self.assertRaises(ModelError):
            safe.ask("Say OK.", role="analyst")                                 # the local one fails: no fallback
        self.assertEqual(len(self.hosted.hits), 1, "a confidential call reached the hosted endpoint")
        self.assertGreaterEqual(len(self.local.hits), 2)
        lane = Path(os.environ[lanes.LANES_ENV]) / "confidential" / "analyst" / ".gnomon"
        self.assertNotIn("fallback", (lane / "roles.toml").read_text(encoding="utf-8"))
        self.assertNotIn(HOSTED, (lane / "config.toml").read_text(encoding="utf-8"))
        intake(p, "Payroll notes for the finance team.", model=shared, requested_by="Aino Virtanen")
        self.assertEqual(len(self.hosted.hits), 1, "the intake reached the hosted endpoint")

    def test_FR_MAT1_AC_10_the_product_surface_of_a_confidential_project_names_no_hosted_fallback(self):
        work = self.tmp / "surface"
        p = self.project(secret=True)
        lanes.write_product_surface(work, confidential.routing_for(p, self.routing), ["app/**"])
        self.assertNotIn("fallback", (work / ".gnomon" / "roles.toml").read_text(encoding="utf-8"))
        self.assertNotIn(HOSTED, (work / ".gnomon" / "config.toml").read_text(encoding="utf-8"))
        other = self.tmp / "other"
        lanes.write_product_surface(other, confidential.routing_for(self.project(secret=False), self.routing),
                                    ["app/**"])
        self.assertIn("[roles.builder.fallback]", (other / ".gnomon" / "roles.toml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
