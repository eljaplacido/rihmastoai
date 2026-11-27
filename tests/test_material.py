"""FR-MAT1: Rihmasto scans whatever a project folder holds, shows what would leave before it leaves, and keeps
confidential material on local models (kernel/material.py, kernel/material_read.py, kernel/material_kinds.py,
kernel/material_cli.py, kernel/confidential.py).

Every folder is built in the test (tests/material_fixture.py): no binary blob and no credential-shaped string
is committed. No model is ever asked: the panel is scripted, and a confidential refusal is checked to come
before any call.
"""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import material_fixture as mf  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402
from test_inputs import scripted  # noqa: E402

from kernel import confidential, material  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.intake import intake, load_source  # noqa: E402
from kernel.pipeline import advance  # noqa: E402

SHIPPED = json.loads((Path(__file__).resolve().parents[1] / "kernel" / "routing.json").read_text(encoding="utf-8"))
LOCAL = {"roles": {role: {"model": "qwen", "endpoint": "box" if role != "verifier" else "lan"}
                   for role in ("analyst", "holdout_author", "builder", "verifier", "assistant")},
         "endpoints": {"box": {"kind": "openai", "url": "http://127.0.0.1:8080/v1/chat/completions"},
                       "lan": {"kind": "openai", "url": "http://10.1.2.3:8080/v1/chat/completions"}}}
SECRETS = (mf.TOKEN, mf.AWS_KEY, "postgres://")


def routing(table: dict):
    """The routing the confidential check reads, as if kernel/routing.local.json said so."""
    return mock.patch("kernel.confidential._routing", return_value=table)


class MaterialCase(FactoryTestCase):
    def folder(self, *, secrets: bool = True) -> Path:
        return mf.build(self.tmp / "project", secrets=secrets)

    def rows(self, mp: dict) -> dict:
        return {r["path"]: r for r in mp["files"]}

    def cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch("kernel.material_cli.sys.stdin", io.StringIO()):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()


class ScanTest(MaterialCase):
    def test_FR_MAT1_AC_1_every_format_of_a_real_folder_is_read_for_what_it_is(self):
        mp, text, documents = material.gather(self.folder())
        rows = self.rows(mp)
        parts = dict(documents)
        # Word: paragraphs with their headings; slides: in the deck's own order, numbered
        self.assertEqual(parts["brief.docx"], "# Lobby visitor register\nVisitors sign in on a tablet; the host is "
                                              "told at once.\n## Users\nReceptionists and hosts at the main office.")
        self.assertEqual(parts["slides/pilot-deck.pptx"], "Slide 1\nPilot plan\nTampere first, then Oulu\n\n"
                                                          "Slide 2\nWhy a register")
        self.assertEqual(parts["slides/kickoff.odp"], "Slide 1\nKickoff\n\nSlide 2\nScope and team")
        self.assertEqual(parts["notes/workshop.odt"], "# Workshop\nHosts asked for a daily summary.")
        # sheets: the name, the header and the rows, shared strings resolved; a CSV's header and first rows
        self.assertEqual(parts["data/budget.xlsx"], "Sheet Budget: 3 rows\nItem | Cost\nTablets | 800\nLicences | 1200")
        self.assertEqual(parts["data/rooms.ods"], "Sheet Rooms: 2 rows\nRoom | Seats\nLobby | 6")
        self.assertIn("name | host | arrived\nMaija | Aino | 09:10", parts["data/visitors.csv"])
        self.assertIn("(the first 5 rows after the header of 7)", parts["data/visitors.csv"])
        # HTML: headings kept, scripts and styles dropped, entities decoded
        html = parts["plan/roadmap.html"]
        self.assertTrue(html.startswith("# Roadmap & milestones\n\nFirst the sign-in screen"), ascii(html))
        self.assertIn("## Decision\n\nWe use the company's single sign-on — no local passwords.", html)
        self.assertNotIn("alert", html)
        self.assertNotIn("secretSauce", html)
        self.assertNotIn("color:red", html)
        # structured files: their keys and a short sample; a log: its first and last lines
        self.assertIn("an object with 2 keys: lobby, hosts", parts["config/settings.json"])
        self.assertIn("top-level keys: retention_days, notify", parts["config/app.yaml"])
        log = parts["logs/deploy.log"]
        self.assertIn("deploy step 1 done", log)
        self.assertIn("deploy step 60 done", log)
        self.assertIn("(30 lines not read)", log)
        self.assertNotIn("deploy step 30 done", log)
        self.assertEqual((rows["logs/deploy.log"]["action"], rows["logs/deploy.log"]["kind"]), ("summarised", "log"))
        # PDF: the text operators of a Flate stream, said to be partly read; a scan has no text layer
        self.assertEqual(parts["docs/security-spec.pdf"], "Visitor data stays in the EU (Finland)\n"
                                                          "Badges are printed at the desk")
        self.assertEqual(rows["docs/security-spec.pdf"]["state"], "partly read")
        self.assertIn("text operators", rows["docs/security-spec.pdf"]["why"])
        self.assertEqual(rows["docs/floorplan-scan.pdf"]["action"], "listed")
        self.assertIn("not read: no text layer", rows["docs/floorplan-scan.pdf"]["why"])
        self.assertEqual(rows["assets/logo.png"]["why"], "binary: not read")
        self.assertEqual(rows["CHANGELOG.md"]["why"], "a housekeeping file: not the author's request")
        # the same folder scans the same way every time
        self.assertEqual(material.scan(self.tmp / "project"), mp)

    def test_FR_MAT1_AC_1_a_file_name_that_is_not_utf8_is_shown_not_fatal(self):
        latin = b"\xe4ij\xe4.py".decode("utf-8", "surrogateescape")      # how Linux hands over such a name
        shown = material._shown({"files": [{"path": "src/" + latin}], "order": [latin], "n": 3})
        self.assertEqual(shown, {"files": [{"path": "src/�ij�.py"}], "order": ["�ij�.py"], "n": 3})
        json.dumps(shown, ensure_ascii=False).encode("utf-8")               # writable as UTF-8
        self.assertEqual(material._shown("plain.md"), "plain.md")

    def test_FR_MAT1_AC_1_files_are_classified_and_code_becomes_an_inventory(self):
        mp, text, documents = material.gather(self.folder())
        kinds = {p: r["kind"] for p, r in self.rows(mp).items()}
        for path, kind in (("README.md", "brief"), ("docs/requirements.md", "brief"), ("brief.docx", "brief"),
                           ("plan/roadmap.html", "plan"), ("review-comments.txt", "review"),
                           ("handover/runbook.md", "handover"), ("notes/meeting-2026-11-20.txt", "notes"),
                           ("logs/deploy.log", "log"), ("data/visitors.csv", "data"), ("data/budget.xlsx", "data"),
                           ("slides/pilot-deck.pptx", "slides"), ("src/app.py", "code"), ("other.md", "other")):
            self.assertEqual(kinds[path], kind, path)
        inv = mp["inventory"]
        self.assertEqual(inv["languages"], [{"language": "Python", "files": 3}])
        self.assertEqual(inv["entry_points"], ["src/app.py"])
        self.assertEqual(inv["tests"], [{"folder": "tests/", "files": 1}])
        self.assertEqual([(m["file"], m["packages"]) for m in inv["manifests"]],
                         [("Dockerfile", []), ("requirements.txt", ["flask", "requests"])])
        self.assertEqual(inv["ci"], [".github/workflows/ci.yml"])
        self.assertNotIn('print("register")', text)                      # code is never read as text
        self.assertIn("- languages: Python (3 files)", dict(documents)["code inventory"])
        # most telling first: the README, then briefs and specs, then plans and the inventory, data and logs last
        order = [o["path"] for o in mp["order"]]
        self.assertEqual(order[0], "README.md")
        self.assertLess(order.index("docs/requirements.md"), order.index("plan/roadmap.html"))
        self.assertLess(order.index("plan/roadmap.html"), order.index("notes/meeting-2026-11-20.txt"))
        self.assertEqual(order[-1], "logs/deploy.log")
        self.assertIn("## README.md (brief or spec)\n\n# Visitor register", text)
        self.assertIn("## code inventory\n\nCode inventory, by rule", text)

    def test_FR_MAT1_AC_2_secret_looking_files_are_skipped_and_never_read_into_anything(self):
        mp, text, _ = material.gather(self.folder())
        rows = self.rows(mp)
        for path, how in ((".env", "never opened, by its name"), ("id_rsa", "never opened, by its name"),
                          ("config/credentials.yaml", "never opened, by its name"),
                          ("notes/handy.txt", "its text holds a credential"),
                          ("src/cloud.py", "its text holds a credential")):
            self.assertEqual(rows[path]["action"], "skipped", path)
            self.assertEqual(rows[path]["why"], f"may hold secrets: {how}", path)
        self.assertEqual(mp["totals"]["secrets"], 5)
        everything = text + json.dumps(mp)
        for secret in SECRETS:
            self.assertNotIn(secret, everything)
        self.assertNotIn("Remember the token", everything)
        self.assertNotIn("handy", "".join(o["path"] for o in mp["order"]))
        with self.assertRaisesRegex(ValueError, "may hold secrets"):           # a single file is checked as well
            load_source(str(self.tmp / "project" / "notes" / "handy.txt"))
        with self.assertRaisesRegex(ValueError, "never read"):
            load_source(str(self.tmp / "project" / ".env"))
        self.assertTrue(load_source(str(self.tmp / "project" / "brief.docx"))[1].startswith("# Lobby visitor register"))

    def test_FR_MAT1_AC_3_the_budget_reads_the_most_telling_first_and_says_what_it_cut(self):
        root = self.tmp / "big"
        (root / "notes").mkdir(parents=True)
        (root / "brief.md").write_text("# Brief\n\n" + "The register must log visitors.\n" * 900, encoding="utf-8")
        (root / "plan.md").write_text("# Plan\n\n" + "First the lobby, then the gates.\n" * 400, encoding="utf-8")
        for n in range(4):
            (root / "notes" / f"note-{n}.md").write_text(f"# Note {n}\n\n" + "A remark from the pilot.\n" * 200,
                                                         encoding="utf-8")
        mp, text, _ = material.gather(root, budget=20_000)
        rows = self.rows(mp)
        self.assertLessEqual(len(text), 20_000)
        self.assertEqual(mp["totals"]["chars"], len(text))
        self.assertEqual(rows["brief.md"]["action"], "summarised")
        self.assertRegex(rows["brief.md"]["why"], r"^the budget: its first [\d,]+ of 28,80\d characters$")
        self.assertIn(rows["plan.md"]["action"], ("summarised", "read"))
        listed = [p for p, r in rows.items() if r["action"] == "listed"]
        self.assertTrue(listed and all(p.startswith("notes/") for p in listed), listed)
        for path in listed:                                 # nothing is cut silently
            self.assertIn(f"{path}: listed only, ", "\n".join(mp["cut"]))
            self.assertEqual(rows[path]["why"], "the budget of 20,000 characters went to more telling files")
        self.assertIn("brief.md: the budget: its first", "\n".join(mp["cut"]))
        # the person's exclusions: an exact path, a glob and a folder; skipped with their reason
        (root / "old").mkdir()
        (root / "old" / "draft.md").write_text("# An old draft\n", encoding="utf-8")
        mp = material.scan(root, ["brief.md", "notes/note-1.*", "old/"], budget=20_000)
        rows = self.rows(mp)
        self.assertEqual(rows["brief.md"]["why"], "excluded by you (brief.md)")
        self.assertEqual(rows["notes/note-1.md"]["why"], "excluded by you (notes/note-1.*)")
        self.assertEqual(mp["skipped_dirs"], [{"path": "old/", "why": "excluded by you (old/)"}])
        self.assertNotIn("old/draft.md", rows)
        self.assertEqual(rows["plan.md"]["action"], "read")
        self.assertEqual(mp["totals"]["excluded"], 2)

    def test_FR_MAT1_AC_3_dependencies_caches_venvs_and_links_are_not_walked(self):
        root = self.tmp / "app"
        for d in ("node_modules/x", ".git/objects", "venv/lib", "pkg/__pycache__", "build", "dist", "target", "env2"):
            (root / d).mkdir(parents=True)
            (root / d / "file.md").write_text("# Not the request\n", encoding="utf-8")
        (root / "env2" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
        (root / "README.md").write_text("# App\n\nA small app.\n", encoding="utf-8")
        mp = material.scan(root)
        self.assertEqual([r["path"] for r in mp["files"]], ["README.md"])
        why = {d["path"]: d["why"] for d in mp["skipped_dirs"]}
        self.assertEqual(why["env2/"], "a Python virtual environment")
        self.assertEqual(why["node_modules/"], "dependencies, build output, a cache or version control")
        self.assertEqual(set(why), {".git/", "build/", "dist/", "env2/", "node_modules/", "target/", "venv/",
                                    "pkg/__pycache__/"})


class IntakeFromMaterialTest(MaterialCase):
    def test_FR_MAT1_AC_4_intake_builds_the_request_from_the_map_and_records_counts_only(self):
        folder = self.folder()
        p = self.factory.new_project("Visitor register", profile="web_service")
        model = scripted({})
        intake(p, str(folder), model=model, requested_by="Aino")
        mp = p.read("material.json")
        self.assertEqual(mp["schema"], material.SCHEMA)
        source = p.read("source.json")
        self.assertEqual(source["kind"], "folder")
        self.assertTrue(source["text"].startswith("## README.md (brief or spec)\n\n# Visitor register"))
        prompts = "".join(prompt for _, prompt in model.calls)
        self.assertIn("## slides/pilot-deck.pptx (slides)", prompts)
        for secret in SECRETS:
            self.assertNotIn(secret, prompts)
        # the reading's documents are the map's parts, in its order (the any-input stream reads each)
        reading = p.read("inputs.json")
        self.assertEqual([d["name"] for d in reading["documents"]], [o["path"] for o in mp["order"]])
        self.assertEqual(reading["kind"], "folder")
        record = p.ledger().of_kind("material_scanned")[-1]["event"]["payload"]
        self.assertEqual({k: record[k] for k in ("files", "read", "summarised", "listed", "skipped", "secrets")},
                         {k: mp["totals"][k] for k in ("files", "read", "summarised", "listed", "skipped", "secrets")})
        self.assertEqual(record["request_sha256"], mp["request_sha256"])
        ledger = p.path("ledger.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("Receptionists and hosts at the main office", ledger)     # never the contents
        self.assertTrue(p.ledger().verify().intact)

    def test_FR_MAT1_AC_5_scan_shows_the_map_and_new_sends_nothing_until_the_person_confirms(self):
        folder = self.folder()
        code, out, err = self.cli("scan", str(folder), "--exclude", "slides/*")
        self.assertEqual((code, err), (0, ""))
        for said in ("Scan of ", "(nothing has been sent)", "Read in full (", "Summarised (", "Listed only, not read (",
                     "Skipped (", ".env  [other]  may hold secrets: never opened, by its name",
                     "slides/pilot-deck.pptx  [other]  excluded by you (slides/*)",
                     "3 code files: counted in the code inventory, not read",
                     "characters would be sent to the analyst"):
            self.assertIn(said, out)
        code, out, err = self.cli("scan", str(folder), "--json")
        self.assertEqual(json.loads(out)["schema"], material.SCHEMA)
        # without --yes and with no terminal: the map is shown, nothing is created and nothing is sent
        with mock.patch("kernel.cli._model", side_effect=AssertionError("no model before the person confirms")):
            code, out, err = self.cli("new", "Visitor register", "--source", str(folder), "--requested-by", "Aino")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("Read in full (", err)
        self.assertIn("Nothing was sent and nothing was created: confirm with --yes", err)
        self.assertEqual(self.factory.projects(), [])
        # confirmed: the project keeps the map with who confirmed it, and intake reads the confirmed request
        model = scripted({})
        with mock.patch("kernel.cli._model", return_value=model):
            code, out, err = self.cli("new", "Visitor register", "--source", str(folder), "--requested-by", "Aino",
                                      "--exclude", "data/*", "--yes", "--profile", "web_service")
        self.assertEqual(code, 0, err)
        p = self.factory.project(json.loads(out)["project"])
        record = p.ledger().of_kind("material_scanned")[-1]["event"]["payload"]
        self.assertEqual((record["person"], record["confirmed"]), ("Aino", "--yes"))
        self.assertEqual(p.read("material.json")["exclude"], ["data/*"])
        reading = p.read("inputs.json")
        self.assertEqual(reading["kind"], "folder")
        self.assertNotIn("data/budget.xlsx", [d["name"] for d in reading["documents"]])
        self.assertNotIn("Tablets | 800", "".join(prompt for _, prompt in model.calls))


class ConfidentialTest(MaterialCase):
    def test_FR_MAT1_AC_7_a_confidential_project_never_sends_to_a_hosted_endpoint(self):
        folder = self.folder(secrets=False)
        p = self.factory.new_project("Visitor register", profile="web_service", mode="assume", maturity="explore")
        confidential.mark(p, person="Aino", persona="business_owner")
        model = scripted({})
        with routing(SHIPPED), self.assertRaises(confidential.ConfidentialRefused) as refused:
            intake(p, str(folder), model=model, requested_by="Aino")
        why = str(refused.exception)
        for said in ("confidential (keep on local models)", "the analyst role would go to the hosted endpoint 'go' "
                     "(opencode.ai)", "Nothing was sent", "kernel/routing.local.json", "docs/guides/local-models.md"):
            self.assertIn(said, why)
        self.assertEqual(model.calls, [])                                        # never sent
        self.assertIsNone(p.read("source.json"))
        kinds = [r["event"]["kind"] for r in p.ledger().records()]
        self.assertIn("confidential_set", kinds)
        self.assertEqual(p.ledger().of_kind("confidential_refused")[-1]["event"]["payload"]["hosted"],
                         [{"role": "analyst", "which": "primary", "endpoint": "go"}])   # a fallback is skipped
        # with every role on loopback or a private address, it goes on
        with routing(LOCAL):
            out = intake(p, str(folder), model=model, requested_by="Aino")
        self.assertTrue(model.calls)
        self.assertIn("questions", out)
        calls = len(model.calls)
        with routing(SHIPPED):            # routed to a hosted model again: the run stops at the spec, refused, with why
            state = advance(p, model=model)
        self.assertEqual((state["state"], state["confidential"]), ("refused", True))
        self.assertIn("analyst role", state["why"])
        self.assertEqual(len(model.calls), calls)
        self.assertEqual(p.ledger().of_kind("confidential_refused")[-1]["event"]["payload"]["where"], "spec")

    def test_FR_MAT1_AC_7_confidential_from_the_command_line_is_refused_before_anything_is_created(self):
        folder = self.folder(secrets=False)
        with routing(SHIPPED), mock.patch("kernel.cli._model", side_effect=AssertionError("never asked")):
            code, out, err = self.cli("new", "Visitor register", "--source", str(folder), "--requested-by", "Aino",
                                      "--yes", "--confidential")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("rihmasto new: refused: this project is confidential", err)
        self.assertIn("docs/guides/local-models.md", err)
        self.assertEqual(self.factory.projects(), [])
        model = scripted({})
        with routing(LOCAL), mock.patch("kernel.cli._model", return_value=model):
            code, out, err = self.cli("new", "Visitor register", "--source", str(folder), "--requested-by", "Aino",
                                      "--yes", "--confidential", "--profile", "web_service")
        self.assertEqual(code, 0, err)
        p = self.factory.project(json.loads(out)["project"])
        self.assertTrue(p.meta["confidential"])
        setting = p.ledger().of_kind("confidential_set")[-1]["event"]["payload"]
        self.assertEqual((setting["confidential"], setting["person"]), (True, "Aino"))
        self.assertTrue(all(r["local"] for r in setting["routes"]))

    def test_FR_MAT1_AC_7_every_model_call_of_a_confidential_project_is_held_to_local_endpoints(self):
        from kernel.assistant import ask
        from kernel.change import submit, triage
        from kernel.compile import author_holdouts
        from kernel.dispatch import build
        from kernel.input_summary import refine
        from kernel.spec import make_spec

        p = self.factory.new_project("Visitor register", profile="web_service")
        confidential.mark(p, person="Aino", persona="business_owner")
        p.write("inputs.json", {"kind": "need"})          # a reading to refine: the refusal comes before it is read
        model = scripted({})
        with routing(SHIPPED):
            for call, role in ((lambda: make_spec(p, model=model), "analyst"),
                               (lambda: author_holdouts(p, model=model), "holdout_author"),
                               (lambda: build(p), "builder"),
                               (lambda: refine(p, model, person="Aino", persona="business_owner"), "analyst")):
                with self.subTest(role=role), self.assertRaisesRegex(confidential.ConfidentialRefused,
                                                                     f"the {role} role would go to"):
                    call()
            card = submit(p, persona="end_user", person="Tester", text="The sign-in button is too small.")
            result = triage(p, card["id"], model=model)                   # a change is triaged by rule instead
            self.assertEqual(result["by"], "rules")
        hosted = {**SHIPPED, "roles": {**SHIPPED["roles"], "assistant": {"model": "glm-5.3", "endpoint": "go"}}}
        with routing(hosted):
            answer = ask(self.factory, "Where is the Questions view?", persona="developer", project_id=p.pid,
                         model=model)
            self.assertIn("confidential", answer["note"])
        self.assertEqual(model.calls, [])
        wheres = [r["event"]["payload"]["where"] for r in p.ledger().of_kind("confidential_refused")]
        self.assertEqual(wheres, ["spec", "holdouts", "build", "inputs refine"])
        self.assertEqual(p.ledger().of_kind("confidential_by_rule")[-1]["event"]["payload"]["role"], "analyst")

    def test_FR_MAT1_AC_7_an_endpoint_is_local_only_by_its_address(self):
        for url, local in (("http://127.0.0.1:8080/v1", True), ("http://localhost:11434", True),
                           ("http://[::1]:8080", True), ("http://10.0.0.7/v1", True), ("http://192.168.1.20", True),
                           ("http://172.16.4.2", True), ("https://opencode.ai/zen/go/v1", False),
                           ("http://8.8.8.8", False), ("http://gpu-box:8080", False), ("", False)):
            self.assertEqual(confidential.is_local(url), local, url)
        self.assertEqual(confidential.refusal(["analyst"], LOCAL), "")
        self.assertIn("the builder role would go to", confidential.refusal(["builder"], SHIPPED))
        self.assertEqual(confidential.refusal(["assistant"], SHIPPED), "")        # local, its hosted fallback skipped
        self.assertEqual([r["endpoint"] for r in confidential.skipped(["assistant"], SHIPPED)], ["go"])


if __name__ == "__main__":
    unittest.main()
