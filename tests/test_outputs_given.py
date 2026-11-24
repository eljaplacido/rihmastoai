"""FR-OUT7: what a chosen output settles is known everywhere it matters (kernel/outputs.py, kernel/holdouts.py).

- The factory's own runner, probes and shadow replay carry no session: the road's sign-in turning them away is
  not measured, never a product failure and never a pass. Checked against a real product with sign-in, started
  on 127.0.0.1 in a process of its own.
- Intake never asks again what the chosen outputs settle, and the brief keeps the choice as the chooser's word.
- The builder's envelope tells the builder how the sign-in works when the product has it.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_scaffold_auth import write_product  # noqa: E402

from kernel import holdouts, operate, outputs  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.compile import init_repo  # noqa: E402
from kernel.demo import LOANS, REQUESTS, ScriptedModel  # noqa: E402
from kernel.dispatch import envelope  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import _git  # noqa: E402
from kernel.roads import http_request  # noqa: E402

OWNER = ("Aino", "business_owner")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class SignInWallTest(unittest.TestCase):
    """A real product with the road's sign-in, served on 127.0.0.1."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="rihma-wall-")
        folder = write_product(Path(cls.tmp.name) / "product", True)
        port = _free_port()
        env = {k: v for k, v in os.environ.items() if k not in ("DATA_DIR", "TRAFFIC_LOG", "PYTHONPATH")}
        env.update(PORT=str(port), HOST="127.0.0.1", DATA_DIR=str(Path(cls.tmp.name) / "data"))
        cls.proc = subprocess.Popen([sys.executable, "-m", "app.server"], cwd=folder, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            if http_request("GET", cls.url + "/health", timeout=1)["status"] == 200:
                return
            time.sleep(0.1)
        cls.tearDownClass()
        raise RuntimeError("the product with sign-in did not start")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.proc.terminate()
        cls.proc.wait(10)
        cls.tmp.cleanup()

    def test_FR_OUT7_AC_1_the_sign_in_turning_the_runner_away_is_not_measured_never_failed_or_passed(self):
        walled = {"criterion": "R-1-AC-1", "steps": [{"method": "GET", "path": "/items", "expect_status": 200}]}
        result = operate.run_scenario(self.url, walled)
        self.assertEqual((result["verdict"], result["reason"]), ("not measured", holdouts.SIGNED_OUT))
        self.assertEqual(result["observed"]["status"], 401)                     # what it saw is kept
        refused = {"criterion": "R-2-AC-1", "steps": [{"method": "GET", "path": "/items", "expect_status": 401}]}
        self.assertEqual(operate.run_scenario(self.url, refused)["verdict"], "passed")   # the 401 it expects
        wrong = {"criterion": "R-3-AC-1", "steps": [{"method": "GET", "path": "/health", "expect_status": 404}]}
        self.assertEqual(operate.run_scenario(self.url, wrong)["verdict"], "failed")     # a real mismatch fails
        probes = operate._probe_round(self.url, None, [walled])
        self.assertEqual((probes["failed"], probes["not_measured"], probes["checks"]), (0, 1, 1))
        records = [{"method": "GET", "path": "/items", "status": 200}, {"method": "GET", "path": "/health", "status": 200}]
        report = holdouts.set_apart_signed_out(operate.replay(records, current_url=self.url, candidate_url=self.url,
                                                              safe=True))
        self.assertEqual((report["signed_out"], report["differing"]), (1, 0))
        verdict = holdouts.shadow_verdict(report)
        self.assertEqual(verdict["verdict"], "not measured")                     # never passed
        self.assertIn("1 of 2 replayed requests met the sign-in", verdict["reason"])
        kept = [e for e in report["entries"] if not e.get("signed_out")]
        self.assertEqual([e["path"] for e in kept], ["/health"])                  # the canary's sample
        self.assertEqual(holdouts.shadow_verdict({"differing": 1, "signed_out": 1})["verdict"], "failed")


class GivenAtIntakeTest(FactoryTestCase):
    def test_FR_OUT7_AC_2_intake_never_asks_again_what_the_chosen_outputs_settle(self):
        prompts: list[str] = []

        class Recording(ScriptedModel):
            def ask(self, prompt: str, *, role: str) -> str:
                prompts.append(prompt)
                return super().ask(prompt, role=role)

        sso = "Is single sign-on required?"
        plain = self.new(title="Equipment loans", mode="assume")
        intake(plain, REQUESTS[LOANS],
               model=Recording(), requested_by="Aino")
        self.assertIn(sso, [q["text"] for q in Canon(plain).questions()])       # without the choice: asked
        chosen = self.new(title="Equipment loans with sign-in", mode="assume")
        outputs.choose(chosen, ["login_web_app", "report"], person=OWNER[0], persona=OWNER[1], when="intake")
        prompts.clear()
        intake(chosen, REQUESTS[LOANS],
               model=Recording(), requested_by="Aino")
        self.assertNotIn(sso, [q["text"] for q in Canon(chosen).questions()])   # settled: never asked again
        fact = outputs.GIVEN["login_web_app"]["fact"]
        panel = [p for p in prompts if "perspective on a panel" in p]
        self.assertTrue(panel and all(fact in p for p in panel))                # the panel is told
        skipped = [r["event"]["payload"] for r in chosen.ledger().of_kind("question_not_asked")]
        self.assertEqual([(s["text"], s["by"], s["persona"], s["rests_on"]) for s in skipped],
                         [(sso, "Aino", "business_owner", "outputs_chosen")])
        brief = Canon(chosen).brief
        self.assertIn("## Outputs chosen [owner]", brief)
        self.assertIn(f"- {fact} [owner: Aino]", brief)                          # the spec reads the brief


class BuilderNotesTest(FactoryTestCase):
    def test_FR_OUT7_AC_3_the_builders_envelope_says_how_the_sign_in_works_only_when_the_product_has_it(self):
        contract = {"schema": "gnomonfactory.contract/1", "contract": "x", "revision": "sha256:" + "0" * 64,
                    "requirements": [{"id": "R-1", "statement": "Lend an item.", "acceptance": [
                        {"id": "R-1-AC-1", "given": "an item", "when": "it is lent", "then": "201"}]}],
                    "tasks": [{"id": "T-1", "criteria": ["R-1-AC-1"], "scope": {"write": ["app/routes.py"]}}]}
        said = {}
        for title, sign_in in (("Loans with sign-in", True), ("Loans without", False)):
            project = self.new(title=title)
            if sign_in:
                outputs.choose(project, ["login_web_app"], person=OWNER[0], persona=OWNER[1])
            init_repo(project, {**contract, "contract": project.pid})
            base = _git(project.path("repo.git"), "rev-parse", "main")
            said[sign_in] = envelope(project, {**contract, "contract": project.pid}, "T-1", base=base)
        for needed in ("req.user", "require_role", "csrf_field", "session_headers", "app/sign_in.py"):
            self.assertIn(needed, said[True])
            self.assertNotIn(needed, said[False])


if __name__ == "__main__":
    unittest.main()
