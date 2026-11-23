"""Brief section H, delivery (FR-H1, FR-H2, FR-H5, FR-H6), measured against what the kernel does.

Each test exercises the part of a requirement that is built, through the kernel's own APIs, on a
real product that intake, spec, compile and a builder cell made and that delivery runs as local
processes. What is not built is recorded in contract/deferred/h.json and has no test here.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import GOOD_ROUTES, good_cell, lazy_cell, model, no_findings  # noqa: E402
from test_deliver import IDEA, LOCAL_ROADS, MORE_ROUTES, DeliveryTestCase  # noqa: E402

from kernel import operate  # noqa: E402
from kernel import roads as roadmod  # noqa: E402
from kernel.autonomy import cap_of  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.deliver import deliver, latest_release  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import Lanes, _git  # noqa: E402
from kernel.ledgerstore import LedgerStore  # noqa: E402
from kernel.packs import build_pack  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.status import evidence  # noqa: E402
from kernel.store import Factory, FixedClock  # noqa: E402

# Release 2 of the product cannot start on a record only production holds, as a bad data migration
# would fail. Staging and the candidate start without that record, so only the promotion meets it.
HEIRLOOM_ROUTES = GOOD_ROUTES + '''

import json as _json
import os as _os

_ITEMS = _os.path.join(_os.environ.get("DATA_DIR", "data"), "items.json")
if _os.path.exists(_ITEMS):
    with open(_ITEMS, encoding="utf-8") as _fh:
        if any(i.get("name") == "heirloom" for i in _json.load(_fh)):
            raise RuntimeError("this release cannot read the heirloom record")
'''

# An auditor's recheck of one release: git and the Python standard library, nothing of the factory.
# It reads only a copy of the product repository and the project ledger.
RECHECK = r'''
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def main(folder, release):
    folder = Path(folder)
    out = {"kernel_importable": importlib.util.find_spec("kernel") is not None}
    lines = (folder / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line]
    broken, prev = None, None
    for i, rec in enumerate(records):
        expected = sha256(canonical({"event": rec.get("event"), "prev": prev, "seq": i}))
        if rec.get("seq") != i or rec.get("prev") != prev or rec.get("hash") != expected:
            broken = i
            break
        prev = rec["hash"]
    out["ledger"] = {"records": len(records), "intact": broken is None, "broken_seq": broken}
    if broken is not None:  # a chain that does not verify pins nothing
        print(json.dumps(out))
        return
    events = [r["event"] for r in records]
    started = [e["payload"] for e in events if e["kind"] == "release_started" and e["payload"]["release"] == release]
    done = [e["payload"] for e in events if e["kind"] == "release_done" and e["payload"]["release"] == release]
    pin = started[-1]
    out["pinned"] = {"revision": pin["revision"], "contract": pin["contract"],
                     "done_at_revision": bool(done) and done[-1]["revision"] == pin["revision"]}
    work = folder / "rebuild"
    work.mkdir()
    git(work, "clone", "-q", "--no-checkout", str(folder / "repo.git"), "w")
    work = work / "w"
    git(work, "checkout", "-q", "--detach", pin["revision"])
    out["rebuilt"] = {"head": git(work, "rev-parse", "HEAD"), "tree": git(work, "rev-parse", "HEAD^{tree}"),
                      "dockerfile": (work / "Dockerfile").exists()}
    contract = json.loads((work / "contract.json").read_text(encoding="utf-8"))
    body = {k: v for k, v in contract.items() if k != "revision"}
    out["contract_matches"] = "sha256:" + sha256(canonical(body)) == pin["contract"]
    env = {k: v for k, v in os.environ.items() if k not in ("TRAFFIC_LOG", "DATA_DIR")}
    env["DATA_DIR"] = str(folder / "data")
    suite = subprocess.run([sys.executable, "-I", "-S", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                           cwd=work, capture_output=True, text=True, env=env, timeout=300)
    ran = re.search(r"^Ran (\d+) tests?", suite.stderr, re.MULTILINE)
    out["suite"] = {"exit": suite.returncode, "ran": int(ran.group(1)) if ran else 0, "tail": suite.stderr[-800:]}
    print(json.dumps(out))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
'''


class GatePassedRevisionTest(unittest.TestCase):
    """FR-H1: what delivery builds is the revision a passed gate merged; a refused change is not in it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-brief-h-"))
        self.addCleanup(roadmod.rmtree, self.tmp)       # runs last, after every process is stopped
        self.addCleanup(roadmod.stop_started)
        self.factory = Factory(self.tmp / "home", clock=FixedClock())

    def test_FR_H1_AC_1_a_release_builds_the_revision_its_gate_passed_and_not_a_refused_change(self):
        p = self.factory.new_project("Equipment loans", mode="assume", maturity="explore")
        self.addCleanup(roadmod.stop_all, p)
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        lanes = Lanes(self.tmp / "lanes", size=1)
        self.assertEqual(build_task(p, "T-001", lanes=lanes, cell_runner=good_cell,
                                    verifier_runner=no_findings)["status"], "merged")
        refused = build_task(p, "T-002", lanes=lanes, cell_runner=lazy_cell, verifier_runner=no_findings,
                             max_rounds=0)
        self.assertEqual(refused["status"], "escalated")
        gates = [r["event"]["payload"] for r in p.ledger().of_kind("gate")]
        passed = [g["head"] for g in gates if g["task"] == "T-001" and g["verdict"] == "passed"]
        refused_heads = [g["head"] for g in gates if g["task"] == "T-002"]
        self.assertEqual(len(passed), 1)
        self.assertTrue(refused_heads)
        self.assertTrue(all(g["verdict"] != "passed" for g in gates if g["task"] == "T-002"))
        gated, refused_head = passed[0], refused_heads[-1]
        merged = [r["event"]["payload"] for r in p.ledger().of_kind("merged")]
        self.assertEqual([(m["task"], m["revision"], m["warranted"]) for m in merged], [("T-001", gated, "passed")])
        repo = p.path("repo.git")
        holding = [b.strip(" *") for b in _git(repo, "branch", "--contains", refused_head).splitlines()]
        self.assertEqual(holding, ["cell/T-002"])                          # the refused change never reached main

        out = deliver(p)
        self.assertEqual(out["state"], "done", out)
        rel = latest_release(p)
        self.assertEqual(rel["revision"], gated)                           # the release is the gated revision ...
        self.assertNotEqual(rel["revision"], refused_head)                 # ... and not the refused one
        art = rel["artifacts"]["local-preview"]
        self.assertEqual(art["ref"], f"repo.git@{gated}")
        checkout = p.dir / art["checkout"]
        self.assertEqual(_git(checkout, "rev-parse", "HEAD"), gated)       # the build ran from that hash
        tests_built = (checkout / "tests" / "test_items.py").read_text(encoding="utf-8")
        self.assertIn("test_R_1_AC_1_post_item_returns_201_with_id", tests_built)
        self.assertNotIn("always_true", tests_built)                       # the refused cell's test is not built
        health = roadmod.http_request("GET", roadmod.slot_state(p, "preview")["base_url"] + "/health")["json"]
        self.assertEqual(health["version"], gated[:12])                    # and the running product says so
        started = [r["event"]["payload"] for r in p.ledger().of_kind("release_started")]
        self.assertEqual([(s["release"], s["revision"]) for s in started], [(1, gated)])


class ProvenanceTest(DeliveryTestCase):
    """FR-H2: a production release links its requirements, evidence, policy and approvals (unsigned)."""

    maturity = "production"

    def shipped(self) -> dict:
        out = self.ship()
        self.assertEqual(out["state"], "done", out)
        return latest_release(self.project)

    def test_FR_H2_AC_1_a_release_names_its_revisions_requirements_road_rules_and_who_approved_it(self):
        rel = self.shipped()
        contract = self.project.read("contract.json")
        self.assertEqual(rel["revision"], self.main())
        self.assertEqual(rel["contract_revision"], contract["revision"])
        self.assertEqual(rel["requirements"], [r["id"] for r in contract["requirements"]])
        rules = LOCAL_ROADS["roads"]["local"]["rules"]
        self.assertEqual({env: road["rules"] for env, road in rel["roads"].items()},
                         {"staging": rules, "production": rules})
        self.assertEqual([(c["step"], c["kind"], c["decision"]["verdict"], c["decision"]["person"],
                           c["decision"]["persona"]) for c in rel["cards"]],
                         [("user_validation", "validation", "accept", "Aino", "business_owner"),
                          ("deploy_gate", "deploy_gate", "approve", "Jaana", "it")])
        gate_card = self.canon.get_card(rel["cards"][1]["card"])
        self.assertEqual((gate_card["payload"]["rules"], gate_card["payload"]["artifact"]),
                         (rules, f"repo.git@{rel['revision']}"))
        # Each approval is in the ledger too, naming its card, the release and the requirements it rests on.
        logged = {r["event"]["payload"]["card"]: r["event"]["payload"]
                  for r in self.project.ledger().of_kind("decision")}
        for c in rel["cards"]:
            d = logged[c["card"]]
            self.assertEqual((d["id"], d["person"], d["verdict"]),
                             (c["decision"]["id"], c["decision"]["person"], c["decision"]["verdict"]))
            self.assertEqual(d["refs"], {"release": rel["release"], "requirements": rel["requirements"]})

    def test_FR_H2_AC_2_its_capability_pack_pins_the_same_revisions_with_every_criterion_and_is_not_signed(self):
        rel = self.shipped()
        pack = build_pack(self.project)
        self.assertEqual(pack["release"], rel["release"])
        self.assertEqual((pack["pinned"]["product_revision"], pack["pinned"]["contract_revision"]),
                         (rel["revision"], rel["contract_revision"]))
        self.assertEqual(pack["pinned"]["artifacts"], {"local": f"repo.git@{rel['revision']}"})
        contract = self.project.read("contract.json")
        criteria = [c["id"] for r in contract["requirements"] for c in r["acceptance"]]
        states = {c["id"]: c["state"] for c in pack["acceptance"]["criteria"]}
        self.assertEqual(sorted(states), sorted(criteria))
        self.assertEqual(states["R-1-AC-1"], "verified")                   # a passed gate proved it
        self.assertEqual(states["R-1-AC-2"], "held_out")                   # its holdout passed on staging
        self.assertEqual(pack["autonomy_cap"], cap_of(self.project))
        self.assertIsNone(pack["provenance"]["signature"])                 # it claims no signature
        self.assertEqual(pack["provenance"]["signature_note"], "not signed: no signer configured")
        self.assertEqual(self.project.read(f"releases/{rel['release']}/capability-pack.json"), pack)

    def test_FR_H2_AC_3_the_evidence_for_a_gate_proved_criterion_leads_to_the_gate_and_the_policy_that_merged_it(self):
        rel = self.shipped()
        row = next(e for e in evidence(self.project) if e["criterion"] == "R-1-AC-1")
        self.assertEqual(row["state"], "verified")
        proof = row["evidence"][0]
        self.assertEqual((proof["kind"], proof["task"], proof["revision"]), ("gate", "T-001", rel["revision"]))
        self.assertTrue(any("R_1_AC_1" in t for t in proof["tests"]))
        ledger = self.project.ledger()
        gate = [r["event"]["payload"] for r in ledger.of_kind("gate") if r["event"]["payload"]["task"] == "T-001"]
        self.assertEqual([(g["round"], g["head"], g["verdict"]) for g in gate][-1],
                         (proof["round"], rel["revision"], "passed"))
        merged = [r["event"]["payload"] for r in ledger.of_kind("merged")
                  if r["event"]["payload"]["revision"] == rel["revision"]]
        self.assertEqual([(m["task"], m["warranted"], m["permitted_by"]) for m in merged],
                         [("T-001", "passed", "policy:auto-merge-warranted")])
        held = next(e for e in evidence(self.project) if e["criterion"] == "R-1-AC-2")
        self.assertEqual((held["state"], held["evidence"]),
                         ("held_out", [{"kind": "holdout", "release": rel["release"]}]))


class ApprovedStateTest(DeliveryTestCase):
    """FR-H5: production goes back to the last promoted release by itself; its data never goes back."""

    maturity = "production"

    def items(self) -> list:
        return [i["name"] for i in self.send("production", "GET", "/items")["json"]]

    def test_FR_H5_AC_1_a_promotion_that_fails_in_production_restores_the_last_promoted_release_by_itself(self):
        self.assertEqual(self.ship()["state"], "done")
        rev1 = self.main()
        self.assertEqual(self.send("production", "POST", "/items", {"name": "heirloom"})["status"], 201)
        self.commit_routes(HEIRLOOM_ROUTES, "A release that cannot read the heirloom record")
        out = self.ship()
        self.assertEqual((out["state"], out["release"], out["failed_step"]), ("failed", 2, "promote:production"))
        self.assertEqual(self.step(out, "canary:production")["native"]["decision"], "promote")  # it got that far
        rollback = latest_release(self.project)["rollback"]
        self.assertEqual(rollback["restored"], {"release": 1, "revision": rev1})
        self.assertEqual(rollback["kept"], {"release": 1, "revision": rev1})
        self.assertIn("no person involved", rollback["by"])
        self.assertTrue(rollback["current_health"]["ok"])
        self.assertEqual(self.health("production")["version"], rev1[:12])
        self.assertEqual(roadmod.slot_state(self.project, "production")["release"], 1)
        self.assertIsNone(roadmod.slot_state(self.project, "production", "candidate"))
        self.assertEqual(self.items(), ["heirloom"])                       # production's data is as it was
        logged = [r["event"]["payload"] for r in self.project.ledger().of_kind("rolled_back")]
        self.assertEqual([(x["release"], x["restored"]) for x in logged], [(2, {"release": 1, "revision": rev1})])
        incident = self.canon.get_card(out["incident"])
        self.assertEqual((incident["kind"], incident["state"], incident["refs"]),
                         ("incident", "open", {"release": 2, "environment": "production"}))
        # People decided the validations and deploy gates only; restoring release 1 was the factory's.
        self.assertEqual([d["kind"] for d in self.canon.decisions()], ["validation", "deploy_gate"] * 2)

    def test_FR_H5_AC_2_rolling_production_code_back_keeps_the_data_written_under_the_newer_release(self):
        self.assertEqual(self.ship()["state"], "done")
        rev1 = self.main()
        release1 = roadmod.slot_state(self.project, "production")
        self.assertEqual(self.send("production", "POST", "/items", {"name": "drill"})["status"], 201)
        rev2 = self.commit_routes(MORE_ROUTES, "A count route")
        self.assertEqual(self.ship()["state"], "done")
        self.assertEqual(self.health("production")["version"], rev2[:12])
        self.assertEqual(self.send("production", "POST", "/items", {"name": "saw"})["status"], 201)
        self.assertEqual(self.send("production", "GET", "/count")["json"], {"count": 2})
        rb = operate.rollback(self.project, "production", release=2, reason="release 2 rolled back",
                              roads=LOCAL_ROADS, restore=release1)
        self.assertEqual(rb["restored"], {"release": 1, "revision": rev1})
        self.assertEqual(self.health("production")["version"], rev1[:12])  # the code went back ...
        self.assertEqual(self.send("production", "GET", "/count")["status"], 404)
        self.assertEqual(self.items(), ["drill", "saw"])                   # ... the data did not
        self.assertEqual(roadmod.slot_state(self.project, "production")["package"]["target"]["data_dir"],
                         release1["package"]["target"]["data_dir"])


class KernelAbsentRecheckTest(DeliveryTestCase):
    """FR-H6: a release is rebuilt and rechecked from the repository and the ledger, the kernel absent."""

    maturity = "pilot"

    def auditor(self) -> Path:
        """A folder holding only a copy of the product repository and the project ledger."""
        folder = self.tmp / "auditor"
        folder.mkdir()
        shutil.copytree(self.project.path("repo.git"), folder / "repo.git")
        shutil.copy2(self.project.path("ledger.jsonl"), folder / "ledger.jsonl")
        return folder

    def recheck(self, folder: Path, release: int) -> dict:
        script = self.tmp / "recheck.py"
        script.write_text(RECHECK, encoding="utf-8")
        proc = subprocess.run([sys.executable, "-I", "-S", str(script), str(folder), str(release)], cwd=folder,
                              capture_output=True, text=True, timeout=600)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_FR_H6_AC_1_the_repository_and_the_ledger_alone_rebuild_a_release_and_rerun_its_tests(self):
        out = self.ship()
        self.assertEqual(out["state"], "done", out)
        rel = latest_release(self.project)
        got = self.recheck(self.auditor(), rel["release"])
        self.assertFalse(got["kernel_importable"])                         # the factory's kernel is absent
        self.assertTrue(got["ledger"]["intact"])
        self.assertEqual(got["pinned"], {"revision": rel["revision"], "contract": rel["contract_revision"],
                                         "done_at_revision": True})
        built = self.project.path("builds", rel["revision"][:12])          # what the kernel built and ran
        self.assertEqual(got["rebuilt"], {"head": rel["revision"], "tree": _git(built, "rev-parse", "HEAD^{tree}"),
                                          "dockerfile": True})
        self.assertTrue(got["contract_matches"])
        self.assertEqual(got["suite"]["exit"], 0, got["suite"]["tail"])
        self.assertGreaterEqual(got["suite"]["ran"], 5)                    # the scaffold's and the criterion's

    def test_FR_H6_AC_2_the_kernel_free_recheck_agrees_with_the_kernel_on_the_chain_and_catches_an_edited_pin(self):
        self.assertEqual(self.ship()["state"], "done")
        rel = latest_release(self.project)
        folder = self.auditor()
        got = self.recheck(folder, rel["release"])
        kernel_view = LedgerStore(folder / "ledger.jsonl").verify()
        self.assertEqual((got["ledger"]["intact"], got["ledger"]["broken_seq"]),
                         (kernel_view.intact, kernel_view.broken_seq))
        self.assertTrue(got["ledger"]["intact"])
        # Someone edits the ledger so the release seems to pin another revision.
        path = folder / "ledger.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        seq = next(i for i, line in enumerate(lines) if json.loads(line)["event"]["kind"] == "release_started")
        rec = json.loads(lines[seq])
        rec["event"]["payload"]["revision"] = "0" * 40
        lines[seq] = json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        roadmod.rmtree(folder / "rebuild")
        got = self.recheck(folder, rel["release"])
        self.assertEqual((got["ledger"]["intact"], got["ledger"]["broken_seq"]), (False, seq))
        self.assertNotIn("pinned", got)                                    # a broken chain pins nothing
        self.assertEqual(LedgerStore(path).verify().broken_seq, seq)       # the kernel agrees


if __name__ == "__main__":
    unittest.main()
