"""The connector model (FR-IG4): connector.json's schema, the connector card that only IT decides and
that pins the sha256 of an enabled entry, and a change that stops the connector and reopens the card.
Each test works on a copy of the example connector in a temporary folder."""

import contextlib
import copy
import io
import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from kernel import connectors  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.learn import FACTORY_PID  # noqa: E402

EXAMPLE = connectors.DEFAULT_ROOT / "example"


def example_doc() -> dict:
    return json.loads((EXAMPLE / "connector.json").read_text(encoding="utf-8"))


class ConnectorCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.tmp / "connectors"
        shutil.copytree(EXAMPLE, self.root / "example")

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()

    def fcanon(self):
        return Canon(self.factory.project(FACTORY_PID))

    def kinds(self):
        return [r["event"]["kind"] for r in self.factory.project(FACTORY_PID).ledger().records()]


class SchemaTest(ConnectorCase):
    def broken(self, change) -> list:
        doc = example_doc()
        change(doc)
        return [v["path"] for v in connectors.validate(doc, "example")]

    def test_FR_IG4_AC_1_a_connector_json_is_validated_and_each_break_is_named_by_its_path(self):
        self.assertEqual(connectors.validate(example_doc(), "example"), [])
        token = "gh" + "p_" + "A1b2C3d4" * 5                                  # the shape of a live token, made here
        cases = {
            "/title": lambda d: d.pop("title"),
            "/schema": lambda d: d.update(schema="rihma.connector/0"),
            "/system": lambda d: d.update(system="other"),
            "/namespace": lambda d: d.update(namespace="Has Spaces"),
            "/server/transport": lambda d: d["server"].update(transport="http"),
            "/server/pin": lambda d: d["server"].pop("pin"),
            "/tools_sha256": lambda d: d.update(tools_sha256="abc"),
            "/read_tools/2": lambda d: d["read_tools"].append({"name": "merge_pull_request", "maps_to": "signal"}),
            "/read_tools/0/maps_to": lambda d: d["read_tools"][0].update(maps_to="decision"),
            "/write_tools/0/deciders": lambda d: d["write_tools"].append(
                {"name": "add_comment", "deciders": ["model"], "args_template": {}}),
            "/forbidden_tools/1": lambda d: d["forbidden_tools"].append("get_item"),
            "/credentials/0/ref": lambda d: d["credentials"][0].update(ref="a-literal-token-value"),
            "/data_classes": lambda d: d.update(data_classes=["secret"]),
            "/notes": lambda d: d.update(notes=token),
            "/extra": lambda d: d.update(extra=True),
        }
        for path, change in cases.items():
            with self.subTest(path):
                self.assertIn(path, self.broken(change))
        camel = self.broken(lambda d: d["read_tools"].append({"name": "approvePullRequest", "maps_to": "signal"}))
        self.assertIn("/read_tools/2", camel)
        self.assertEqual(connectors.validate(["not", "an", "object"]), [
            {"path": "", "expected": "a JSON object", "got": "'list'"}])

    def test_FR_IG4_AC_1_the_command_line_validates_a_folder_and_refuses_a_broken_one_with_its_path(self):
        code, out, err = self.cli("connector", "validate", "example", "--root", str(self.root))
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(json.loads(out)["valid"])
        doc = example_doc()
        doc["server"]["transport"] = "http"
        (self.root / "example" / "connector.json").write_text(json.dumps(doc), encoding="utf-8")
        code, out, err = self.cli("connector", "validate", "example", "--root", str(self.root))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("/server/transport", err)
        code, _, err = self.cli("connector", "validate", "../escape", "--root", str(self.root))
        self.assertEqual(code, 2)


class CardTest(ConnectorCase):
    def test_FR_IG4_AC_2_enabling_opens_a_connector_card_that_pins_the_entry_and_only_it_decides(self):
        with self.assertRaises(DecisionRefused):
            connectors.enable(self.factory, "example", person="Pekka", persona="developer", root=self.root)
        self.assertFalse(self.factory.projects_dir.joinpath(FACTORY_PID, "connectors.json").exists())
        card = connectors.enable(self.factory, "example", person="Ilkka", persona="it", root=self.root)
        [entry] = connectors.entries(self.factory)
        sha = connectors.file_sha256(self.root / "example" / "connector.json")
        self.assertEqual((card["kind"], card["deciders"], card["verdicts"]), ("connector", ["it"], ["enable", "decline"]))
        files = connectors.folder_sha256(self.root, "example")
        self.assertEqual(card["payload"]["pin"], connectors.pin_of(entry, sha, files))
        self.assertEqual(card["payload"]["folder_sha256"], files)
        self.assertEqual(card["payload"]["connector_sha256"], sha)
        self.assertEqual(connectors.state_of(self.factory, "example", root=self.root)["state"], "waiting")
        with self.assertRaises(connectors.ConnectorStopped):
            connectors.require_enabled(self.factory, "example", root=self.root)
        for persona in ("developer", "business_owner", "product_owner", "compliance"):
            with self.assertRaises(DecisionRefused, msg=persona):
                self.fcanon().decide(card["id"], "enable", person="Pekka", persona=persona)
        self.fcanon().decide(card["id"], "enable", person="Ilkka", persona="it")
        self.assertEqual(connectors.state_of(self.factory, "example", root=self.root)["state"], "enabled")
        self.assertEqual(connectors.require_enabled(self.factory, "example", root=self.root)["system"], "example")
        self.assertIn("connector_enabled", self.kinds())

    def test_FR_IG4_AC_2_a_declined_or_disabled_connector_may_not_run(self):
        card = connectors.enable(self.factory, "example", person="Ilkka", persona="it", root=self.root)
        self.fcanon().decide(card["id"], "decline", person="Ilkka", persona="it", reason="not this quarter")
        self.assertEqual(connectors.state_of(self.factory, "example", root=self.root)["state"], "declined")
        with self.assertRaises(connectors.ConnectorStopped):
            connectors.require_enabled(self.factory, "example", root=self.root)
        connectors.disable(self.factory, "example", person="Ilkka", persona="it")
        self.assertEqual(connectors.state_of(self.factory, "example", root=self.root)["state"], "off")
        code, out, _ = self.cli("connector", "status", "--root", str(self.root))
        self.assertEqual((code, json.loads(out)["connectors"][0]["state"]), (0, "off"))

    def test_FR_IG4_AC_2_a_disabled_connector_written_back_by_hand_stays_stopped_until_it_decides_again(self):
        card = connectors.enable(self.factory, "example", person="Ilkka", persona="it", root=self.root)
        self.fcanon().decide(card["id"], "enable", person="Ilkka", persona="it")
        path = self.factory.projects_dir / FACTORY_PID / "connectors.json"
        saved = path.read_bytes()                                  # the enabled entry, as IT's card pinned it
        connectors.disable(self.factory, "example", person="Ilkka", persona="it")
        path.write_bytes(saved)                                    # written back by hand, with no decision
        state = connectors.state_of(self.factory, "example", root=self.root)
        self.assertEqual((state["state"], state["card"]), ("stopped", card["id"]))
        self.assertIn("disabled", state["reason"])
        with self.assertRaises(connectors.ConnectorStopped):
            connectors.require_enabled(self.factory, "example", root=self.root)
        code, out, err = self.cli("connector", "check", "--root", str(self.root))
        self.assertEqual(code, 0, err)
        [stopped] = json.loads(out)["stopped"]
        new = self.fcanon().get_card(stopped["reopened"])
        self.assertEqual((new["state"], new["payload"]["supersedes"]), ("open", card["id"]))
        self.assertEqual(connectors.state_of(self.factory, "example", root=self.root)["state"], "waiting")
        self.fcanon().decide(new["id"], "enable", person="Ilkka", persona="it")
        self.assertEqual(connectors.require_enabled(self.factory, "example", root=self.root)["system"], "example")


class ChangeTest(ConnectorCase):
    def enabled(self) -> dict:
        card = connectors.enable(self.factory, "example", person="Ilkka", persona="it", root=self.root)
        self.fcanon().decide(card["id"], "enable", person="Ilkka", persona="it")
        return card

    def test_FR_IG4_AC_3_a_changed_connector_json_stops_the_connector_and_reopens_its_card(self):
        old = self.enabled()
        doc = example_doc()
        doc["read_tools"].append({"name": "list_comments", "maps_to": "note"})
        (self.root / "example" / "connector.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        state = connectors.state_of(self.factory, "example", root=self.root)
        self.assertEqual(state["state"], "stopped")
        with self.assertRaises(connectors.ConnectorStopped):
            connectors.require_enabled(self.factory, "example", root=self.root)
        [stopped] = connectors.check(self.factory, root=self.root)
        new = self.fcanon().get_card(stopped["reopened"])
        self.assertEqual((new["kind"], new["state"], new["payload"]["supersedes"]), ("connector", "open", old["id"]))
        self.assertNotEqual(new["payload"]["pin"], old["payload"]["pin"])
        self.assertEqual(new["payload"]["pin"], state["pin"])
        self.assertIn("list_comments", new["body"])
        self.assertIn("connector_stopped", self.kinds())
        self.assertEqual(connectors.check(self.factory, root=self.root), [])          # once per change
        self.fcanon().decide(new["id"], "enable", person="Ilkka", persona="it")
        self.assertEqual(connectors.state_of(self.factory, "example", root=self.root)["state"], "enabled")

    def test_FR_IG4_AC_3_a_changed_server_or_mapping_stops_it_and_a_server_off_its_pin_never_runs(self):
        self.enabled()
        folder = self.root / "example"
        with open(folder / "mapping.py", "a", encoding="utf-8", newline="\n") as fh:
            fh.write("# changed after IT decided\n")
        code, out, _ = self.cli("connector", "status", "--root", str(self.root))
        self.assertEqual((code, json.loads(out)["connectors"][0]["state"]), (0, "stopped"))
        with self.assertRaises(connectors.ConnectorStopped):
            connectors.require_enabled(self.factory, "example", root=self.root)
        [stopped] = connectors.check(self.factory, root=self.root)
        self.fcanon().decide(stopped["reopened"], "enable", person="Ilkka", persona="it")
        self.assertEqual(connectors.require_enabled(self.factory, "example", root=self.root)["system"], "example")
        with open(folder / "server.py", "a", encoding="utf-8", newline="\n") as fh:
            fh.write("# changed after IT decided\n")
        self.assertEqual(connectors.state_of(self.factory, "example", root=self.root)["state"], "stopped")
        with self.assertRaises(connectors.ConnectorStopped):
            connectors.require_enabled(self.factory, "example", root=self.root)
        [stopped] = connectors.check(self.factory, root=self.root)
        card = self.fcanon().get_card(stopped["reopened"])
        self.assertEqual([v["path"] for v in card["payload"]["violations"]], ["/server/pin/sha256"])
        self.fcanon().decide(card["id"], "enable", person="Ilkka", persona="it")
        with self.assertRaises(connectors.ConnectorInvalid):              # server.py is not the one pinned
            connectors.require_enabled(self.factory, "example", root=self.root)
        code, _, err = self.cli("connector", "validate", "example", "--root", str(self.root))
        self.assertEqual(code, 2)
        self.assertIn("/server/pin/sha256", err)

    def test_FR_IG4_AC_3_an_entry_changed_by_hand_stops_it_and_a_card_left_open_is_withdrawn(self):
        first = connectors.enable(self.factory, "example", person="Ilkka", persona="it", root=self.root)
        path = self.factory.projects_dir / FACTORY_PID / "connectors.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = copy.deepcopy(data)
        changed["connectors"][0]["writes"] = True
        path.write_text(json.dumps(changed), encoding="utf-8")
        self.assertEqual(connectors.state_of(self.factory, "example", root=self.root)["state"], "stopped")
        code, out, err = self.cli("connector", "check", "--root", str(self.root))
        self.assertEqual(code, 0, err)
        reopened = json.loads(out)["stopped"][0]["reopened"]
        self.assertEqual(self.fcanon().get_card(first["id"])["state"], "withdrawn")
        with self.assertRaises(DecisionRefused):
            self.fcanon().decide(first["id"], "enable", person="Ilkka", persona="it")
        self.assertEqual(self.fcanon().get_card(reopened)["payload"]["entry"]["writes"], True)
        self.assertEqual(connectors.state_of(self.factory, "example", root=self.root)["state"], "waiting")

    def test_FR_IG4_AC_3_a_connector_json_that_breaks_the_schema_stays_stopped_whatever_is_decided(self):
        self.enabled()
        doc = example_doc()
        doc["forbidden_tools"] = []
        doc["read_tools"].append({"name": "delete_item", "maps_to": "signal"})
        (self.root / "example" / "connector.json").write_text(json.dumps(doc), encoding="utf-8")
        [stopped] = connectors.check(self.factory, root=self.root)
        card = self.fcanon().get_card(stopped["reopened"])
        self.assertTrue(card["payload"]["violations"])
        self.fcanon().decide(card["id"], "enable", person="Ilkka", persona="it")
        with self.assertRaises(connectors.ConnectorInvalid):
            connectors.require_enabled(self.factory, "example", root=self.root)


if __name__ == "__main__":
    unittest.main()
