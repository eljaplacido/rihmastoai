"""FR-S2: epics in the canon, made and linked by a person, qualified, and read down to tasks, commits and tests.

On a copy of the demo home's shipment webhook (requirements R-1..R-3, tasks T-001..T-003 merged with their rounds):
a product owner creates an epic and links requirements and a blocking question through the cockpit and the command
line; a non-person and a developer are refused and change nothing; the tree says whether each epic qualifies and
what is missing, with each requirement's tasks, lanes, commits and tests; the board's cards name their epics; and Ask
Rihma shows the same tree and proposes the same signed create and link.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from acc_fakes import WEBHOOK, copy_home, pid_of  # noqa: E402
from test_acc_developer import Served  # noqa: E402

from kernel import assistant  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.store import Factory  # noqa: E402

PO = {"person": "Pia Product", "persona": "product_owner"}


class EpicsCase(unittest.TestCase):
    def setUp(self):
        if shutil.which("git") is None:
            raise unittest.SkipTest("git is needed to build the demo home")
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-epics-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "lanes")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.factory = Factory(copy_home(self.tmp))
        self.p = self.factory.project(pid_of(self.factory, WEBHOOK))
        self.served = Served(self, self.factory)
        self.base = f"/api/projects/{self.p.pid}"

    def cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()


class EpicWriteTest(EpicsCase):
    def test_FR_S2_AC_1_a_product_owner_creates_and_links_an_epic_signed_and_others_are_refused(self):
        before = (self.p.path("canon/epics.json").exists(), len(self.p.ledger().records()))
        for who in ({"person": "kernel", "persona": "product_owner"}, {"person": "Dev Tester", "persona": "developer"}):
            status, out = self.served.call("POST", f"{self.base}/epics", {"title": "Stock is right", **who})
            self.assertEqual(status, 403, out)
        self.assertEqual((self.p.path("canon/epics.json").exists(), len(self.p.ledger().records())), before)
        status, out = self.served.call("POST", f"{self.base}/epics",
                                       {"title": "Stock is right", "requirements": ["R-9"], **PO})
        self.assertEqual(status, 400, out)
        self.assertIn("no requirement R-9", out["error"])
        status, out = self.served.call("POST", f"{self.base}/epics", {
            "title": "Incoming stock is always right", "owner": "Olli Owner", "criterion": "the counts match the dock",
            "requirements": ["R-1", "R-2"], **PO})
        self.assertEqual(status, 201, out)
        epic = out["epic"]
        self.assertEqual((epic["id"], epic["requirements"], epic["by"]), ("E-1", ["R-1", "R-2"], PO))
        kept = json.loads(self.p.path("canon/epics.json").read_text(encoding="utf-8"))
        self.assertEqual(kept[0]["owner"], "Olli Owner")
        made = self.p.ledger().of_kind("epic_created")[-1]["event"]["payload"]
        self.assertEqual((made["id"], made["person"], made["persona"]), ("E-1", "Pia Product", "product_owner"))
        q = Canon(self.p).add_question("Which dock counts first?", "business", blocking=True)
        status, out = self.served.call("POST", f"{self.base}/epics/E-1", {"requirements": "R-1,R-2,R-3",
                                                                          "questions": [q["id"]], **PO})
        self.assertEqual((status, out["epic"]["requirements"], out["epic"]["questions"]),
                         (200, ["R-1", "R-2", "R-3"], [q["id"]]))
        linked = self.p.ledger().of_kind("epic_linked")[-1]["event"]["payload"]
        self.assertEqual((linked["id"], linked["person"]), ("E-1", "Pia Product"))
        # the command line, signed the same way
        code, out, err = self.cli("epics", "add", self.p.pid, "--title", "Arrivals are announced", "--requirements",
                                  "R-3", "--person", "Pia Product", "--persona", "product_owner")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["id"], "E-2")
        code, _, err = self.cli("epics", "link", self.p.pid, "E-2", "--owner", "Olli Owner", "--person", "Dev Tester",
                                "--persona", "developer")
        self.assertEqual(code, 2)
        self.assertIn("a business owner or a product owner writes it", err)


class EpicTreeTest(EpicsCase):
    def test_FR_S2_AC_2_the_tree_says_whether_each_epic_qualifies_and_reads_down_to_commits_and_tests(self):
        q = Canon(self.p).add_question("Which dock counts first?", "business", blocking=True)
        self.served.call("POST", f"{self.base}/epics", {
            "title": "Incoming stock is always right", "owner": "Olli Owner", "criterion": "the counts match",
            "requirements": ["R-1", "R-2"], **PO})
        self.served.call("POST", f"{self.base}/epics", {"title": "Half a wish", "requirements": [], **PO})
        before = len(self.p.ledger().records())
        status, tree = self.served.call("GET", f"{self.base}/epics")
        self.assertEqual(status, 200, tree)
        e1, e2 = tree["epics"]
        self.assertFalse(e1["qualified"])
        self.assertEqual(e1["missing"], [f"its blocking questions linked ({q['id']} linked to no epic)"])
        self.assertEqual(e2["missing"][:2], ["a named business owner", "an acceptance criterion in the owner's words"])
        r1 = e1["requirements"][0]
        self.assertEqual(r1["id"], "R-1")
        [t1] = r1["tasks"]
        self.assertEqual((t1["id"], t1["lane"]), ("T-001", "done"))
        self.assertGreater(t1["commits"], 0)
        self.assertTrue(t1["tests"] and all(t["result"] == "ok" for t in t1["tests"]), t1)
        self.assertEqual([r["id"] for r in tree["unlinked"]], ["R-3"])
        self.served.call("POST", f"{self.base}/epics/E-1", {"questions": [q["id"]], **PO})
        self.assertTrue(self.served.call("GET", f"{self.base}/epics")[1]["epics"][0]["qualified"])
        board = self.served.call("GET", f"{self.base}/dev/board")[1]
        epics_of = {c["id"]: c.get("epics") for c in board["cards"] if c["kind"] == "task"}
        self.assertEqual(epics_of, {"T-001": ["E-1"], "T-002": ["E-1"], "T-003": []})
        self.assertEqual(board["filters"]["epics"], ["E-1"])
        self.assertEqual(len(self.p.ledger().records()), before + 1)       # only the link wrote
        code, out, err = self.cli("epics", "list", self.p.pid)
        self.assertEqual(code, 0, err)
        self.assertEqual([e["id"] for e in json.loads(out)["epics"]], ["E-1", "E-2"])


class EpicChatTest(EpicsCase):
    def ask(self, question: str, persona: str = "product_owner") -> dict:
        return assistant.ask(self.factory, question, persona=persona, project_id=self.p.pid, view="board",
                             person="Pia Product")

    def test_FR_S2_AC_3_ask_rihma_shows_the_tree_and_proposes_the_same_signed_create_and_link(self):
        out = self.ask("show the epics")
        self.assertIn("This project has no epic yet", out["answer"])
        self.assertEqual(out["navigate"], {"route": f"#/p/{self.p.pid}/board", "control": "epics"})
        out = self.ask('create an epic "Incoming stock is always right" with R-1, R-2, owned by Olli Owner, done when '
                       "the counts match the dock")
        [prop] = out["propose"]
        self.assertEqual(prop["args"]["op"], "create_epic")
        self.assertEqual(prop["args"]["call"], {"method": "POST", "path": f"/api/projects/{self.p.pid}/epics", "body": {
            "title": "Incoming stock is always right", "owner": "Olli Owner", "criterion": "the counts match the dock",
            "requirements": ["R-1", "R-2"], "questions": []}})
        self.assertEqual(len(self.p.ledger().of_kind("epic_created")), 0)          # a proposal writes nothing
        status, made = self.served.call("POST", prop["args"]["call"]["path"], {**prop["args"]["call"]["body"], **PO})
        self.assertEqual(status, 201, made)
        link = self.ask("put R-3 under E-1")["propose"][0]["args"]
        self.assertEqual((link["op"], link["call"]["body"]), ("link_epic", {"requirements": ["R-1", "R-2", "R-3"]}))
        self.assertEqual(self.ask("create an epic Faster counts", persona="developer")["propose"], [])
        said = self.ask("show the epics")["answer"]
        self.assertIn("E-1 Incoming stock is always right qualifies: R-1: T-001 done; R-2: T-002 done", said)
        self.assertIn("Under no epic: R-3", said)


if __name__ == "__main__":
    unittest.main()
