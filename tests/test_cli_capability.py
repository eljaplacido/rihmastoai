"""The command line covers the capability layer (FR-N2-AC-3): security, packs, evidence, embeds, autonomy,
signals, concepts, observations, updates, the square and the catalogue. Each command is a thin wrapper over
the kernel that prints JSON; a write is signed by a person and a persona; a refusal is a message on stderr
and exit 2. Every test drives `main(argv)` against a temporary factory home."""

import argparse
import contextlib
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from kernel import embeds  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.cli import CAPABILITY, HANDLERS, build_parser, main  # noqa: E402
from kernel.learn import FACTORY_PID  # noqa: E402
from kernel.model import FakeModel  # noqa: E402

SARIF = Path(__file__).parent / "fixtures" / "sarif"
FUTURE = "2099-12-31"


def summarising(prompt: str, role: str) -> str:
    """The analyst's summary of a need; it names a project that does not exist, which must not count."""
    assert "A business need arrived" in prompt and role == "analyst", prompt[:80]
    return ('```json\n{"title": "Pallet photos", "problem": "damage is not reported", "who": "field staff", '
            '"value": "fewer write-offs", "existing_project": "no-such-project"}\n```')
# Every capability feature, by its command (FR-N2-AC-3).
FEATURES = {
    "security": ("security ingest", "security accept", "security status"),
    "packs": ("pack",), "evidence": ("evidence",),
    "embeds": ("embed create", "embed list", "embed revoke"),
    "autonomy": ("autonomy show", "autonomy set"),
    "signals": ("signal log", "signal list", "signal triage"),
    "concepts": ("concept edit", "concept apply"),
    "observations": ("observe",), "updates": ("updates apply",), "square": ("square",), "catalogue": ("catalogue",),
}
# The commands that write a record signed by the person who runs them.
SIGNED_WRITES = ("security ingest", "security accept", "evidence", "embed create", "embed revoke", "autonomy set",
                 "concept edit")


def leaves(parser: argparse.ArgumentParser, prefix: tuple = ()) -> dict:
    """Every command line the parser takes, as its table key, with its own parser."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            out = {}
            for name, sub in action.choices.items():
                out.update(leaves(sub, (*prefix, name)))
            return out
    return {" ".join(prefix): parser}


class CliCase(FactoryTestCase):
    def cli(self, *argv: str) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()

    def ok(self, *argv: str):
        code, out, err = self.cli(*argv)
        self.assertEqual((code, err), (0, ""), argv)
        return json.loads(out)

    def refused(self, *argv: str) -> str:
        code, out, err = self.cli(*argv)
        self.assertEqual((code, out), (2, ""), argv)
        self.assertTrue(err.startswith(f"rihmasto {argv[0]}"), err)
        self.assertNotIn("Traceback", err)
        return err

    def kinds(self, project) -> list:
        return [r["event"]["kind"] for r in project.ledger().records()]

    def payloads(self, project, kind: str) -> list:
        return [r["event"]["payload"] for r in project.ledger().records() if r["event"]["kind"] == kind]


class CommandTableTest(unittest.TestCase):
    def test_FR_N2_AC_3_every_capability_feature_has_a_command_and_every_command_one_handler(self):
        parsed = leaves(build_parser())
        self.assertEqual(set(parsed), set(HANDLERS) | set(CAPABILITY))     # the table selects every command
        self.assertEqual(set(HANDLERS) & set(CAPABILITY), set())
        for feature, commands in FEATURES.items():
            self.assertLessEqual(set(commands), set(CAPABILITY), feature)
        for name in SIGNED_WRITES:
            required = {a.dest: a.required for a in parsed[name]._actions if a.dest in ("person", "persona")}
            self.assertEqual(required, {"person": True, "persona": True}, name)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
            main(["autonomy", "set", "3", "--reason", "x", "--persona", "it"])        # unsigned: the parser stops it
        self.assertEqual(stop.exception.code, 2)


class SecurityCliTest(CliCase):
    def test_FR_N2_AC_3_security_ingest_accept_and_status_sign_each_write(self):
        p = self.new()
        self.assertEqual(self.ok("security", "status", p.pid)["verdict"], "not measured")
        scan = self.ok("security", "ingest", p.pid, str(SARIF / "bandit.sarif"), "--person", "Ilkka", "--persona", "it")
        self.assertEqual((scan["scan"], scan["counts"]["error"], scan["ingested_by"]),
                         (1, 1, {"person": "Ilkka", "persona": "it"}))
        status = self.ok("security", "status", p.pid)
        self.assertEqual((status["verdict"], len(status["findings"])), ("failed", 3))
        blocking = next(f["id"] for f in status["findings"] if f["level"] == "error")
        self.assertIn("may not accept", self.refused("security", "accept", p.pid, blocking, "--reason", "fixed soon",
                                                     "--expires", FUTURE, "--person", "Pekka",
                                                     "--persona", "developer"))
        self.assertIn("not after today", self.refused("security", "accept", p.pid, blocking, "--reason", "r",
                                                      "--expires", "2000-01-01", "--person", "Ilkka",
                                                      "--persona", "it"))
        self.assertIn("SEC-9-9", self.refused("security", "accept", p.pid, "SEC-9-9", "--reason", "r", "--expires",
                                              FUTURE, "--person", "Ilkka", "--persona", "it"))
        acc = self.ok("security", "accept", p.pid, blocking, "--reason", "shell=True on a fixed command",
                      "--expires", FUTURE, "--person", "Ilkka", "--persona", "it")
        self.assertEqual((acc["id"], acc["person"], acc["persona"], acc["expires"]), ("RA-001", "Ilkka", "it", FUTURE))
        status = self.ok("security", "status", p.pid)
        self.assertEqual(status["verdict"], "passed")
        self.assertEqual(next(f["state"] for f in status["findings"] if f["id"] == blocking), "accepted")
        self.assertEqual(status["accepted_risks"][0]["person"], "Ilkka")
        self.assertEqual(self.payloads(p, "security_scan")[0]["by"], "Ilkka")
        self.assertEqual(self.payloads(p, "risk_accepted")[0]["reason"], "shell=True on a fixed command")

    def test_FR_N2_AC_3_a_refused_ingest_records_no_scan(self):
        p = self.new()
        self.assertIn("SARIF version", self.refused("security", "ingest", p.pid, str(SARIF / "wrong-version.sarif"),
                                                    "--person", "Ilkka", "--persona", "it"))
        self.refused("security", "ingest", p.pid, str(self.tmp / "missing.sarif"), "--person", "Ilkka",
                     "--persona", "it")
        self.assertIn("not a person", self.refused("security", "ingest", p.pid, str(SARIF / "bandit.sarif"),
                                                   "--person", "model", "--persona", "it"))
        self.assertIn("no project", self.refused("security", "status", "no-such-project"))
        self.assertNotIn("security_scan", self.kinds(p))
        self.assertEqual(self.ok("security", "status", p.pid)["verdict"], "not measured")


class PackAndEvidenceCliTest(CliCase):
    def test_FR_N2_AC_3_pack_prints_a_releases_capability_pack_as_json_or_yaml(self):
        p = self.new()
        self.assertIn("no release yet", self.refused("pack", p.pid))
        p.write("releases/1.json", {"release": 1, "maturity": "demo", "revision": "abc123",
                                    "artifacts": {"demo": {"ref": "local-process@abc123"}}})
        pack = self.ok("pack", p.pid)
        self.assertEqual((pack["format"], pack["version"], pack["release"]), ("rihma.capability-pack.v1", "1.0.0", 1))
        self.assertEqual(pack["pinned"]["product_revision"], "abc123")
        self.assertFalse(pack["acceptance"]["valid"])                         # no contract, so nothing verified
        self.assertIsNone(pack["provenance"]["signature"])
        code, text, err = self.cli("pack", p.pid, "--release", "1", "--yaml")
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(text.startswith("# rihma.capability-pack.v1"))
        self.assertIn('version: "1.0.0"', text)                               # same content, same version
        self.assertTrue(p.path("releases", "1", "capability-pack.json").exists())
        self.assertIn("no release yet", self.refused("pack", p.pid, "--release", "9"))

    def test_FR_N2_AC_3_evidence_exports_a_zip_signed_by_a_person_and_persona(self):
        p = self.new()
        out = self.tmp / "exports"
        self.assertIn("may not export", self.refused("evidence", p.pid, "--out", str(out), "--person", "Sanna",
                                                     "--persona", "stakeholder"))
        self.assertIn("not a person", self.refused("evidence", p.pid, "--out", str(out), "--person", "factory",
                                                   "--persona", "compliance"))
        res = self.ok("evidence", p.pid, "--out", str(out), "--person", "Kaisa", "--persona", "compliance")
        path = Path(res["file"])
        self.assertEqual(path.parent, out)
        self.assertEqual(res["verdict"], "insufficient evidence")             # no release and no decision yet
        self.assertNotIn("compliant", res["meaning"])
        with zipfile.ZipFile(path) as z:
            self.assertIn("attestation.json", z.namelist())
            self.assertEqual(json.loads(z.read("MANIFEST.json"))["exported_by"], "Kaisa")
        self.assertEqual(self.payloads(p, "evidence_exported")[0]["by"], "Kaisa")


class EmbedCliTest(CliCase):
    def test_FR_N2_AC_3_embed_create_prints_the_key_once_and_list_and_revoke_never_show_it(self):
        p = self.new()
        e = self.ok("embed", "create", "--kind", "feedback", "--project", p.pid, "--origin", "https://intranet.example",
                    "--origin", "http://localhost:8000", "--label", "Loans page", "--brief", "Equipment loans.",
                    "--endpoint", "https://feedback.example", "--person", "Aino", "--persona", "product_owner")
        key = e["key"]
        self.assertTrue(key.startswith("rk_"))
        self.assertNotIn("key_sha256", e)
        self.assertEqual((e["id"], e["origins"], e["created_by"]),
                         ("E-001", ["http://localhost:8000", "https://intranet.example"], "Aino"))
        self.assertIn(f'data-key="{key}"', e["snippet"])
        self.assertIn("https://feedback.example/e/E-001/widget.js", e["snippet"])
        embeds.check(self.factory, "E-001", key, "https://intranet.example")  # the printed key is the real one
        code, listing, _ = self.cli("embed", "list")
        self.assertEqual(code, 0)
        self.assertNotIn(key, listing)
        self.assertNotIn("key_sha256", listing)
        self.assertEqual(json.loads(listing)["embeds"][0]["state"], "active")
        for f in self.factory.home.rglob("*"):
            if f.is_file():
                self.assertNotIn(key, f.read_text(encoding="utf-8", errors="replace"), f)  # only its hash is kept
        self.assertIn("may not create", self.refused("embed", "create", "--kind", "need", "--origin",
                                                     "https://intranet.example", "--person", "Pekka",
                                                     "--persona", "developer"))
        self.assertIn("an origin is", self.refused("embed", "create", "--kind", "need", "--origin", "ftp://x.example",
                                                   "--person", "Aino", "--persona", "it"))
        self.assertIn("belongs to a project", self.refused("embed", "create", "--kind", "feedback", "--origin",
                                                           "https://intranet.example", "--person", "Aino",
                                                           "--persona", "it"))
        self.assertIn("revokes", self.refused("embed", "revoke", "E-001", "--person", "Tero", "--persona", "end_user"))
        self.assertIn("E-099", self.refused("embed", "revoke", "E-099", "--person", "Aino", "--persona", "it"))
        code, revoked, _ = self.cli("embed", "revoke", "E-001", "--person", "Aino", "--persona", "it")
        self.assertEqual((code, json.loads(revoked)["state"]), (0, "revoked"))
        self.assertNotIn("key_sha256", revoked)
        with self.assertRaises(embeds.EmbedRefused):
            embeds.check(self.factory, "E-001", key, "https://intranet.example")
        self.assertEqual([x["persona"] for x in self.payloads(self.factory.project(FACTORY_PID), "embed_revoked")],
                         ["it"])


class AutonomyCliTest(CliCase):
    def test_FR_N2_AC_3_autonomy_show_and_set_by_a_person_with_a_reason(self):
        shown = self.ok("autonomy", "show")
        self.assertEqual((shown["scope"], shown["cap"]), ("factory", 4))
        self.assertIn("may not set", self.refused("autonomy", "set", "3", "--reason", "x", "--person", "Pekka",
                                                  "--persona", "developer"))
        self.assertIn("reason", self.refused("autonomy", "set", "3", "--reason", " ", "--person", "Kaisa",
                                             "--persona", "compliance"))
        self.assertEqual(self.ok("autonomy", "set", "3", "--reason", "build and trial only", "--person", "Kaisa",
                                 "--persona", "compliance"), {"scope": "factory", "cap": 3})
        p = self.new()
        self.assertEqual(self.ok("autonomy", "set", "2", "--project", p.pid, "--reason", "suggest only",
                                 "--person", "Ilkka", "--persona", "it"), {"scope": "project", "cap": 2})
        self.assertIn("exceed", self.refused("autonomy", "set", "4", "--project", p.pid, "--reason", "more",
                                             "--person", "Ilkka", "--persona", "it"))
        shown = self.ok("autonomy", "show", p.pid)
        self.assertEqual((shown["scope"], shown["cap"], shown["factory_cap"]), ("project", 2, 3))
        self.assertEqual([lv["allowed"] for lv in shown["levels"]], [True, True, False, False])
        factory_set = self.payloads(self.factory.project(FACTORY_PID), "autonomy_cap_set")[0]
        self.assertEqual((factory_set["by"], factory_set["reason"], factory_set["to"]),
                         ("Kaisa", "build and trial only", 3))
        self.assertEqual(self.payloads(p, "autonomy_cap_set")[0]["by"], "Ilkka")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.cli("autonomy", "set", "5", "--reason", "x", "--person", "Kaisa", "--persona", "compliance")


class SquareCliTest(CliCase):
    def test_FR_N2_AC_3_signals_concepts_square_and_catalogue_take_a_need_to_a_project(self):
        loans = self.new(title="Equipment loans")
        s1 = self.ok("signal", "log", "--text", "The equipment loans page should show overdue loans first",
                     "--channel", "chat", "--source", "#ops-team", "--person", "Sanna", "--persona", "operations")
        self.assertEqual((s1["id"], s1["state"], s1["person"]), ("S-001", "new", "Sanna"))
        routed = self.ok("signal", "triage", "S-001")
        self.assertEqual((routed["state"], routed["routed_to"]["project"]), ("routed", loans.pid))
        self.assertEqual(Canon(loans).get_card(routed["routed_to"]["card"])["kind"], "change")
        s2 = self.ok("signal", "log", "--text", "Warehouse staff need a way to report damaged pallets from a phone",
                     "--channel", "feed", "--source", "service desk export")
        self.assertIsNone(s2["person"])                                        # a feed has no person
        card = self.ok("signal", "triage", "S-002")["routed_to"]["card"]
        self.assertIn("already concept", self.refused("signal", "triage", "S-002"))
        self.assertIn("not a person", self.refused("signal", "log", "--text", "x", "--channel", "chat", "--source",
                                                   "y", "--person", "model"))
        self.assertEqual([s["id"] for s in self.ok("signal", "list", "--state", "concept")["signals"]], ["S-002"])
        square = self.ok("square")
        self.assertEqual((square["signals"]["total"], [c["card"] for c in square["concepts_waiting"]]), (2, [card]))
        catalogue = self.ok("catalogue")
        self.assertEqual({i["state"] for i in catalogue["items"]}, {"shaping", "proposed"})
        self.assertIn("may not edit", self.refused("concept", "edit", card, "--maturity", "pilot", "--person", "Pekka",
                                                   "--persona", "developer"))
        self.assertIn("at least one", self.refused("concept", "edit", card, "--person", "Aino",
                                                   "--persona", "business_owner"))
        edited = self.ok("concept", "edit", card, "--title", "Damaged pallet reports", "--profile", "mobile_prototype",
                         "--maturity", "explore", "--person", "Aino", "--persona", "business_owner")
        self.assertEqual((edited["title"], edited["profile"], edited["maturity"], edited["mode"]),
                         ("Damaged pallet reports", "mobile_prototype", "explore", "mixed"))
        self.assertEqual(self.ok("concept", "apply"), {"applied": []})         # nothing decided yet
        self.ok("decide", FACTORY_PID, card, "validate", "--person", "Aino", "--persona", "business_owner")
        applied = self.ok("concept", "apply")["applied"]
        self.assertEqual(applied[0]["verdict"], "validate")
        made = self.factory.project(applied[0]["project"]).meta
        self.assertEqual((made["title"], made["profile"], made["maturity"]),
                         ("Damaged pallet reports", "mobile_prototype", "explore"))
        self.assertEqual(self.ok("concept", "apply"), {"applied": []})         # carried out once
        self.assertEqual(self.ok("signal", "list", "--state", "validated")["signals"][0]["id"], "S-002")
        self.assertEqual(self.payloads(self.factory.project(FACTORY_PID), "concept_edited")[0]["by"], "Aino")

    def test_FR_N2_AC_3_signal_triage_with_a_model_takes_its_summary_and_the_rule_still_routes(self):
        self.new(title="Equipment loans")
        self.ok("signal", "log", "--text", "Field staff want to attach photos of damaged pallets", "--channel",
                "meeting", "--source", "weekly operations meeting", "--person", "Sanna", "--persona", "operations")
        with mock.patch("kernel.cli._model", lambda: FakeModel(summarising)):
            out = self.ok("signal", "triage", "S-001", "--with-model")
        # The model named a project that does not exist: the rule routes the need to a concept, with its title.
        self.assertEqual((out["state"], out["routed_to"]["project"]), ("concept", None))
        concept = Canon(self.factory.project(FACTORY_PID)).get_card(out["routed_to"]["card"])
        self.assertEqual((concept["payload"]["title"], concept["payload"]["raised_by"]), ("Pallet photos", "Sanna"))


class ObservationCliTest(CliCase):
    def test_FR_N2_AC_3_observe_opens_update_cards_and_updates_apply_records_the_decision(self):
        p = self.new()
        facts = {"project": p.pid, "criterion": "R-1-AC-1", "before": "0.94", "after": "0.88"}
        obs = self.ok("observe", "eval_drift", "--facts", json.dumps(facts), "--source", "nightly evals")
        touched = obs["touched"][0]
        self.assertEqual((obs["id"], touched["project"]), ("O-001", p.pid))
        self.assertEqual(set(touched["views"]), {"developer", "expert", "business"})
        self.assertEqual(Canon(p).get_card(touched["card"])["kind"], "update")
        self.assertEqual(self.ok("updates", "apply", p.pid), {"project": p.pid, "applied": []})
        self.ok("decide", p.pid, touched["card"], "trial", "--person", "Pekka", "--persona", "developer")
        applied = self.ok("updates", "apply", p.pid)["applied"]
        self.assertEqual((applied[0]["card"], applied[0]["verdict"]), (touched["card"], "trial"))
        self.assertEqual(self.factory.project(p.pid).meta["trial"]["approved_by"], "Pekka")
        self.assertEqual(self.ok("updates", "apply", p.pid)["applied"], [])    # recorded once
        quiet = self.ok("observe", "usage_low", "--source", "monthly report")  # touches nothing: rendered only
        self.assertEqual((quiet["touched"], sorted(quiet["views"])), ([], ["business", "developer", "expert"]))
        self.assertIn("JSON object", self.refused("observe", "eval_drift", "--facts", "[1, 2]", "--source", "x"))
        self.refused("observe", "eval_drift", "--facts", "{not json", "--source", "x")
        self.assertIn("no project", self.refused("updates", "apply", "no-such-project"))


if __name__ == "__main__":
    unittest.main()
