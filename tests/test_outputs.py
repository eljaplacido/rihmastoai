"""Outputs per audience (kernel/outputs.py, kernel/output_builders.py, kernel/report.py), on the demo home.

The demo (kernel/demo.py) is built once: its webhook project has a release, a product repository, a decision,
assumptions and verified criteria; Equipment loans has none of them yet.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock

from cockpit.server import make_server
from kernel import output_builders as ob
from kernel import outputs, report, roads
from kernel.assistant import ask
from kernel.canon import DecisionRefused
from kernel.cli import main as cli_main
from kernel.compile import init_repo
from kernel.lanes import PROTECTED, _git
from kernel.store import Factory

OWNER, DEV = ("demo-owner", "business_owner"), ("demo-dev", "developer")
SECTIONS = report.SECTIONS
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class _Runner:
    """The cockpit's job runner, starting nothing."""

    def __init__(self) -> None:
        self.started: list = []

    def start(self, args: list, log_path) -> str:
        self.started.append(args)
        return f"J-{len(self.started):04d}"

    def status(self, job_id: str) -> dict:
        return {"state": "done", "code": 0}


DEMO: dict = {}


def setUpModule() -> None:
    """One demo home for every test here: each test chooses the outputs it needs before it builds."""
    if shutil.which("git") is None:
        raise unittest.SkipTest("git is needed to build the demo home")
    from kernel.demo import build_demo

    DEMO["tmp"] = Path(tempfile.mkdtemp(prefix="rihma-outputs-")).resolve()
    try:
        build_demo(DEMO["tmp"] / "demo", echo=lambda line: None)
    except Exception:
        tearDownModule()
        raise
    DEMO["factory"] = Factory(DEMO["tmp"] / "demo")


def tearDownModule() -> None:
    roads.stop_started()
    with contextlib.suppress(OSError, KeyError):
        roads.rmtree(DEMO["tmp"])


class DemoCase(unittest.TestCase):
    @property
    def factory(self) -> Factory:
        return DEMO["factory"]

    @property
    def tmp(self) -> Path:
        return DEMO["tmp"]

    def project(self, title: str):
        return next(p for p in self.factory.projects() if p.meta.get("title") == title)

    def folder(self) -> Path:
        return Path(tempfile.mkdtemp(dir=self.tmp))

    def kinds(self, project, kind: str) -> list:
        return [r["event"]["payload"] for r in project.ledger().of_kind(kind)]


class ChoosingTest(DemoCase):
    def test_FR_OUT1_AC_1_a_named_person_chooses_the_outputs_and_the_ledger_keeps_who_and_what_before(self):
        loans = self.project("Equipment loans")
        before = len(loans.ledger().records())
        view = outputs.view(loans)
        self.assertEqual(view["chosen"], [])
        self.assertEqual(view["proposed"], ["container", "api", "report", "source"])   # a product's proposal
        self.assertFalse(any(t["chosen"] for t in view["targets"]))                  # never shown as a choice
        self.assertEqual(len(view["targets"]), 7)
        self.assertTrue(all(t["contains"] and t["audience"] for t in view["targets"]))
        for person, persona, targets, error in (("demo-stakeholder", "stakeholder", ["report"], DecisionRefused),
                                                ("factory", "business_owner", ["report"], DecisionRefused),
                                                ("demo-owner", "business_owner", ["a_brochure"], ValueError)):
            with self.subTest(person=person, persona=persona), self.assertRaises(error):
                outputs.choose(loans, targets, person=person, persona=persona)
        self.assertEqual(len(loans.ledger().records()), before)                       # a refusal records nothing
        self.assertIsNone(loans.read("outputs.json"))
        outputs.choose(loans, ["report", "container"], person=OWNER[0], persona=OWNER[1], reason="for the handover")
        first = self.kinds(loans, "outputs_chosen")[-1]
        self.assertEqual((first["by"], first["persona"], first["targets"], first["before"], first["reason"]),
                         ("demo-owner", "business_owner", ["container", "report"], [], "for the handover"))
        outputs.choose(loans, "report,api", person=DEV[0], persona=DEV[1])
        second = self.kinds(loans, "outputs_chosen")[-1]
        self.assertEqual((second["before"], second["added"], second["removed"]), (["container", "report"], ["api"],
                                                                                  ["container"]))
        record = loans.read("outputs.json")
        self.assertEqual((record["targets"], record["by"], len(record["history"])), (["api", "report"], "demo-dev", 2))
        self.assertFalse(outputs.wants_sign_in(loans))
        outputs.choose(loans, ["login_web_app", "report"], person=OWNER[0], persona=OWNER[1])
        self.assertTrue(outputs.wants_sign_in(loans))
        self.assertNotIn("sign_in", self.kinds(loans, "outputs_chosen")[-1])          # no repository: nothing added yet

    def test_FR_OUT1_AC_2_a_build_needs_a_choice_and_every_build_is_recorded_with_who_asked(self):
        access = self.project("Access review check")
        outputs.choose(access, ["report", "mcp_server"], person=DEV[0], persona=DEV[1])
        before = len(self.kinds(access, "output_built"))
        with self.assertRaises(DecisionRefused):
            outputs.build(access, ["container"], self.folder(), person=DEV[0], persona=DEV[1])
        with self.assertRaises(DecisionRefused):
            outputs.build(access, ["report"], self.folder(), person="demo-stakeholder", persona="stakeholder")
        self.assertEqual(len(self.kinds(access, "output_built")), before)
        out = outputs.build(access, ["report", "mcp_server"], self.folder(), person=DEV[0], persona=DEV[1])
        rows = {r["target"]: r for r in out["outputs"]}
        self.assertEqual(rows["report"]["state"], "built")
        self.assertEqual(rows["mcp_server"]["state"], "not built")
        self.assertIn("planned", rows["mcp_server"]["why"])
        recorded = self.kinds(access, "output_built")[before:]
        self.assertEqual([(r["target"], r["state"], r["by"], r["persona"]) for r in recorded],
                         [("mcp_server", "not built", "demo-dev", "developer"), ("report", "built", "demo-dev", "developer")])

    def test_FR_OUT1_AC_3_the_same_records_build_the_same_bytes(self):
        webhook = self.project("Shipment webhook to the stock system")
        targets = ["report", "api", "container", "source"]
        outputs.choose(webhook, targets, person=OWNER[0], persona=OWNER[1])
        one, two = self.folder(), self.folder()
        first = outputs.build(webhook, targets, one, person=OWNER[0], persona=OWNER[1])["outputs"]
        second = outputs.build(webhook, targets, two, person=DEV[0], persona=DEV[1])["outputs"]
        self.assertEqual([(r["file"], r["sha256"]) for r in first], [(r["file"], r["sha256"]) for r in second])
        for row in first:
            with self.subTest(target=row["target"]), zipfile.ZipFile(one / row["file"]) as z:
                self.assertEqual((one / row["file"]).read_bytes(), (two / row["file"]).read_bytes())
                self.assertEqual({i.date_time for i in z.infolist()}, {(1980, 1, 1, 0, 0, 0)})
                manifest = json.loads(z.read("MANIFEST.json"))["files"]
                self.assertEqual(sorted(manifest), sorted(n for n in z.namelist() if n != "MANIFEST.json"))
                for name, digest in manifest.items():
                    self.assertEqual(outputs._sha(z.read(name)), digest)
            self.assertEqual(outputs._sha((one / row["file"]).read_bytes()), row["sha256"])

    def test_FR_OUT1_AC_4_the_command_line_shows_chooses_and_builds_and_refuses_an_unsigned_write(self):
        pid = self.project("Shipment webhook to the stock system").pid
        home = ["--home", str(self.factory.home)]

        def run(*args: str) -> tuple[int, str, str]:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli_main([*home, "output", pid, *args])
            return code, out.getvalue(), err.getvalue()

        code, shown, _ = run()
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(shown)["targets"]), 7)
        code, _, said = run("--choose", "report")
        self.assertEqual(code, 2)
        self.assertIn("give --person and --persona", said)
        code, chosen, _ = run("--choose", "report,api", "--person", OWNER[0], "--persona", OWNER[1])
        self.assertEqual((code, json.loads(chosen)["chosen"]), (0, ["api", "report"]))
        folder = self.folder()
        code, built, _ = run("--target", "report", "--out", str(folder), "--person", OWNER[0], "--persona", OWNER[1])
        self.assertEqual(code, 0)
        self.assertTrue((folder / json.loads(built)["outputs"][0]["file"]).is_file())


class TargetsTest(DemoCase):
    def setUp(self) -> None:
        self.webhook = self.project("Shipment webhook to the stock system")
        outputs.choose(self.webhook, ["container", "api", "source", "report", "evidence_pack"], person=OWNER[0],
                       persona=OWNER[1])
        self.rel = outputs.release_of(self.webhook)

    def zipped(self, target: str) -> zipfile.ZipFile:
        folder = self.folder()
        row = outputs.build(self.webhook, [target], folder, person=OWNER[0], persona=OWNER[1])["outputs"][0]
        self.assertEqual(row["state"], "built", row)
        return zipfile.ZipFile(folder / row["file"])

    def test_FR_OUT3_AC_1_the_container_holds_the_release_source_compose_on_loopback_and_a_readme(self):
        with self.zipped("container") as z:
            names = set(z.namelist())
            for name in ("product/Dockerfile", "product/app/server.py", "compose.yaml", "image.json", "README.md"):
                self.assertIn(name, names)
            server = _git(self.webhook.path("repo.git"), "show", f"{self.rel['revision']}:app/server.py")
            self.assertEqual(z.read("product/app/server.py").decode("utf-8").strip(), server)
            compose = z.read("compose.yaml").decode("utf-8")
            for said in ('"127.0.0.1:8080:8080"', "build: ./product", "data:/data", f'APP_VERSION: "{self.rel["revision"][:12]}"'):
                self.assertIn(said, compose)
            self.assertFalse(json.loads(z.read("image.json"))["pinned"])
            self.assertIn("docker compose up --build", z.read("README.md").decode("utf-8"))
        signed_in = ob.compose_yaml(self.webhook, self.rel, {"pinned": False}, True)
        self.assertIn('FIRST_ADMIN_PASSWORD: "${FIRST_ADMIN_PASSWORD:-}"', signed_in)    # from the shell, never a value

    def test_FR_OUT3_AC_2_the_api_is_openapi_3_1_with_each_operations_criteria_and_evidence(self):
        with self.zipped("api") as z:
            doc = json.loads(z.read("openapi.json"))
        self.assertEqual((doc["openapi"], doc["info"]["version"]), ("3.1.0", "release-1"))
        spec_paths = {row["path"] for row in self.webhook.read("spec.json")["interface"]}
        self.assertLessEqual(spec_paths | {"/health"}, set(doc["paths"]))
        post = doc["paths"]["/webhooks/shipments"]["post"]
        self.assertEqual({c["id"]: c["evidence"] for c in post["x-rihmasto-criteria"]},
                         {"R-1-AC-1": "verified", "R-3-AC-1": "verified"})
        self.assertEqual(set(post["responses"]), {"202", "422"})
        self.assertEqual(doc["paths"]["/shipments/{id}"]["get"]["parameters"][0]["name"], "id")
        signed = ob.openapi(self.webhook, self.rel, True)
        self.assertEqual(signed["paths"]["/sign-in"]["post"]["security"], [])
        self.assertEqual(set(signed["components"]["securitySchemes"]), {"session", "csrf"})
        self.assertEqual(signed["security"], [{"session": [], "csrf": []}])

    def test_FR_OUT3_AC_3_the_source_is_a_git_bundle_that_clones_to_the_release(self):
        with self.zipped("source") as z:
            bundle = self.folder() / "product.bundle"
            bundle.write_bytes(z.read("product.bundle"))
            readme = z.read("README.md").decode("utf-8")
        self.assertIn("git clone --branch main product.bundle", readme)
        self.assertIn(self.rel["revision"], readme)
        clone = self.folder() / "clone"
        subprocess.run(["git", "clone", "-q", str(bundle), str(clone)], check=True, capture_output=True)
        self.assertEqual(_git(clone, "cat-file", "-t", self.rel["revision"]), "commit")
        check = subprocess.run(["git", "bundle", "verify", str(bundle)], cwd=clone, capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)

    def run_readme(self, zipped: Path, pid: str) -> tuple[Path, list]:
        """The source README's commands, word for word, in a folder outside any repository; the team's repository
        is a bare one beside it."""
        here = self.folder()
        outside = here / "unpacked"
        outside.mkdir()
        with zipfile.ZipFile(zipped) as z:
            z.extractall(outside)
            readme = z.read("README.md").decode("utf-8")
        team = here / "team.git"
        subprocess.run(["git", "init", "-q", "--bare", str(team)], check=True, capture_output=True)
        env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(here)}                # no repository above
        commands = readme.split("```sh\n", 1)[1].split("```", 1)[0].strip().splitlines()
        cwd, ran = outside, []
        for line in commands:
            words = shlex.split(line.replace("<your repository URL>", team.as_posix()))
            if words[0] == "cd":
                cwd = cwd / words[1]
                continue
            proc = subprocess.run(words, cwd=cwd, env=env, capture_output=True, text=True)
            ran.append((line, proc.returncode, proc.stderr.strip()[-300:]))
        return team, ran

    def test_FR_OUT3_AC_4_the_source_readme_runs_word_for_word_outside_any_repository(self):
        bare = self.factory.new_project("Bundle without a release", maturity="explore", mode="assume")
        init_repo(bare, {"schema": "gnomonfactory.contract/1", "contract": bare.pid, "requirements": [], "tasks": [],
                         "revision": "sha256:" + "0" * 64})
        for project, rel in ((self.webhook, self.rel), (bare, None)):
            outputs.choose(project, ["source"], person=OWNER[0], persona=OWNER[1])
            folder = self.folder()
            row = outputs.build(project, ["source"], folder, person=OWNER[0], persona=OWNER[1])["outputs"][0]
            self.assertEqual(row["release"], rel["release"] if rel else None)
            team, ran = self.run_readme(folder / row["file"], project.pid)
            with self.subTest(project=project.pid):
                self.assertEqual([(line, code) for line, code, _ in ran if code], [], ran)   # every command succeeded
                self.assertIn("git bundle verify ../product.bundle", [line for line, _, _ in ran])
                expected = rel["revision"] if rel else _git(project.path("repo.git"), "rev-parse", "main")
                self.assertEqual(_git(team, "rev-parse", f"refs/heads/rihmasto/{project.pid}"), expected)

    def test_FR_OUT4_AC_1_the_report_says_who_asked_what_was_built_decided_assumed_and_proven_each_with_its_record(self):
        md = report.markdown(self.webhook, self.rel, outputs.view(self.webhook, built=False))
        for title in SECTIONS:
            self.assertIn(f"## {title}", md)
        for said in ("demo-product asked for", "Release 1 took the product", "demo-dev (developer) decided retry",
                     "*(decision D-001)*", "*(assumption A-001)*", "**verified**", "Not measured: no model run was recorded"):
            self.assertIn(said, md)
        self.assertNotRegex(md, r"\b0(\.0+)? USD")                                     # an unpriced cost is not zero
        bullets = [line for line in md.splitlines() if line.startswith("- ")]
        self.assertGreater(len(bullets), 15)
        for line in bullets:
            self.assertRegex(line, r"\*\([^()]+\)\*$")                                  # every statement names its record

    def test_FR_OUT4_AC_2_the_report_is_the_same_however_often_outputs_are_built_and_escapes_every_value(self):
        first = report.markdown(self.webhook, self.rel, outputs.view(self.webhook, built=False))
        outputs.build(self.webhook, ["evidence_pack", "report", "api"], self.folder(), person=OWNER[0], persona=OWNER[1])
        self.assertEqual(report.markdown(self.webhook, self.rel, outputs.view(self.webhook, built=False)), first)
        page = report.html_page(self.webhook, self.rel, outputs.view(self.webhook, built=False))
        self.assertNotIn("<script", page)
        self.assertIn("default-src 'none'", page)
        self.assertEqual(report._inline("<script>**x** `y`"), "&lt;script&gt;<b>x</b> <code>y</code>")


class CockpitOutputsTest(DemoCase):
    def setUp(self) -> None:
        self.runner = _Runner()
        self.server, bootstrap = make_server(self.factory, 0, runner=self.runner)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.token = self.call("POST", "/auth", {"bootstrap": bootstrap}, token=None)[1]["token"]

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def call(self, method: str, path: str, body=None, token: str | None = "", raw: bool = False):
        headers = {"Origin": self.server.origin}
        if token is not None:
            headers["Authorization"] = f"Bearer {token or self.token}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        if data:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.server.origin + path, data=data, headers=headers, method=method)
        try:
            with _DIRECT.open(req, timeout=30) as res:
                payload, status = res.read(), res.status
        except urllib.error.HTTPError as exc:
            with exc:
                payload, status = exc.read(), exc.code
        return status, payload if raw else (json.loads(payload) if payload else None)

    def test_FR_OUT5_AC_1_the_cockpit_api_shows_chooses_builds_and_hands_each_file_over_once(self):
        webhook = self.project("Shipment webhook to the stock system")
        base = f"/api/projects/{webhook.pid}/outputs"
        status, view = self.call("GET", base)
        self.assertEqual((status, len(view["targets"])), (200, 7))
        status, said = self.call("PUT", base, {"targets": ["report"], "person": "Ville", "persona": "stakeholder"})
        self.assertEqual(status, 403, said)
        status, view = self.call("PUT", base, {"targets": ["report", "api"], "person": "Aino", "persona": "business_owner",
                                              "reason": "handover"})
        self.assertEqual((status, view["chosen"], view["chosen_by"]["by"]), (200, ["api", "report"], "Aino"))
        status, out = self.call("POST", base + "/build", {"targets": ["report"], "person": "Aino",
                                                          "persona": "business_owner"})
        self.assertEqual(status, 201, out)
        row = out["outputs"][0]
        self.assertEqual((row["state"], row["files"]), ("built", ["report.html", "report.md"]))
        status, data = self.call("GET", row["download"], raw=True)
        self.assertEqual(status, 200)
        self.assertIn("report.md", zipfile.ZipFile(io.BytesIO(data)).namelist())
        self.assertEqual(self.call("GET", row["download"])[0], 404)                       # the link worked once
        self.assertEqual(self.call("POST", base + "/build", {"targets": ["container"], "person": "Aino",
                                                             "persona": "business_owner"})[0], 403)   # not chosen
        status, made = self.call("POST", "/api/projects", {"title": "Room booking", "source": "Book meeting rooms.",
                                                           "requested_by": "Aino", "persona": "business_owner",
                                                           "outputs": ["report", "login_web_app"]})
        self.assertEqual(status, 201, made)
        record = self.factory.project(made["project"]["id"]).read("outputs.json")
        self.assertEqual((record["targets"], record["by"], record["when"]), (["login_web_app", "report"], "Aino", "intake"))
        count = len(self.factory.projects())
        status, _ = self.call("POST", "/api/projects", {"title": "Desk booking", "source": "Book desks.",
                                                        "requested_by": "Ville", "persona": "stakeholder",
                                                        "outputs": ["report"]})
        self.assertEqual((status, len(self.factory.projects())), (403, count))           # refused before it was made

    def test_FR_OUT5_AC_3_the_ui_map_names_the_outputs_view_and_its_controls_and_the_assistant_takes_a_person_there(self):
        status, ui = self.call("GET", "/api/ui-map")
        self.assertEqual(status, 200)
        self.assertIn("#/p/{pid}/outputs", {v["route"] for v in ui["views"]})
        self.assertLessEqual({"choose_outputs", "build_output", "build_outputs", "download_output"},
                             {c["id"] for c in ui["controls"]})
        webhook = self.project("Shipment webhook to the stock system")
        out = ask(self.factory, "Where do I download the container for a developer?", persona="developer",
                  project_id=webhook.pid)
        self.assertEqual(out["navigate"]["route"], f"#/p/{webhook.pid}/outputs")


class SignInChoiceTest(DemoCase):
    def test_FR_OUT2_AC_3_choosing_the_sign_in_scaffolds_it_or_adds_it_to_main_only_when_the_suite_passes(self):
        fresh = self.factory.new_project("Sign-in app", maturity="explore", mode="assume")
        outputs.choose(fresh, ["login_web_app"], person=OWNER[0], persona=OWNER[1])
        init_repo(fresh, {"schema": "gnomonfactory.contract/1", "contract": fresh.pid, "requirements": [], "tasks": [],
                          "revision": "sha256:" + "0" * 64})
        repo = fresh.path("repo.git")
        self.assertIn("first_admin_from_env", _git(repo, "show", "main:app/sign_in.py"))
        self.assertIn("USER 10001:10001", _git(repo, "show", "main:Dockerfile"))
        access = self.project("Access review check")
        head = _git(access.path("repo.git"), "rev-parse", "main")
        with mock.patch("kernel.scaffold_auth.has_sign_in_hook", return_value=False), self.assertRaises(DecisionRefused):
            outputs.choose(access, ["login_web_app"], person=OWNER[0], persona=OWNER[1])
        self.assertEqual(_git(access.path("repo.git"), "rev-parse", "main"), head)          # main did not move
        self.assertEqual(self.kinds(access, "sign_in_refused")[-1]["by"], "demo-owner")
        self.assertNotIn("login_web_app", outputs.chosen(access))
        webhook = self.project("Shipment webhook to the stock system")
        outputs.choose(webhook, ["login_web_app", "report"], person=OWNER[0], persona=OWNER[1])
        added = self.kinds(webhook, "sign_in_added")[-1]
        self.assertEqual((added["suite"], added["by"]), ("passed", "demo-owner"))
        self.assertGreaterEqual(added["sign_in_checks"], 10)                           # the road's checks ran and passed
        self.assertGreater(added["ran"], added["sign_in_checks"])                       # with the product's own tests
        self.assertEqual(_git(webhook.path("repo.git"), "rev-parse", "main"), added["revision"])
        self.assertIn("SIGN_IN_MODE", _git(webhook.path("repo.git"), "show", "main:factory/SIGN-IN.md"))
        view = {t["id"]: t for t in outputs.view(webhook)["targets"]}
        self.assertIn("next release carries it", view["login_web_app"]["why"])           # release 1 predates it
        for path in ("app/sign_in.py", "tests/test_road_sign_in.py"):
            self.assertIn(path, PROTECTED)                                               # no cell may change them

    def test_FR_OUT2_AC_6_a_sign_in_added_later_runs_unprivileged_and_scans_clean(self):
        from kernel.redteam import static

        later = self.factory.new_project("Sign-in chosen later", maturity="explore", mode="assume")
        init_repo(later, {"schema": "gnomonfactory.contract/1", "contract": later.pid, "requirements": [], "tasks": [],
                          "revision": "sha256:" + "0" * 64})
        repo = later.path("repo.git")
        self.assertNotIn("USER 10001", _git(repo, "show", "main:Dockerfile"))           # compiled without sign-in
        outputs.choose(later, ["login_web_app"], person=OWNER[0], persona=OWNER[1])
        added = self.kinds(later, "sign_in_added")[-1]
        self.assertEqual((added["suite"], added["user"]), ("passed", "10001"))
        self.assertIn("chown -R 10001:10001 /data", added["data_volume"])                # how a volume is handed over
        clone = self.folder() / "main"
        _git(self.folder(), "clone", "-q", str(repo), str(clone))
        dockerfile = (clone / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile, r"(?m)^USER 10001:10001$")
        self.assertIn("chown 10001:10001 /data", dockerfile)
        self.assertIn("## The service's user and its data volume", (clone / "factory/SIGN-IN.md").read_text("utf-8"))
        found = static.scan([clone], which=lambda tool: None)
        self.assertEqual([(f.rule, f.path, f.line) for f in found.findings], [])


class FacesHookTest(DemoCase):
    def test_FR_OUT6_AC_1_an_mcp_server_is_planned_until_the_faces_module_offers_its_hook(self):
        webhook = self.project("Shipment webhook to the stock system")
        outputs.choose(webhook, ["mcp_server"], person=DEV[0], persona=DEV[1])
        fake = types.ModuleType(ob.FACES_MODULE)
        saved = sys.modules.get(ob.FACES_MODULE)
        sys.modules[ob.FACES_MODULE] = fake        # the faces module, offering no hook yet, then offering it
        try:
            row = {t["id"]: t for t in outputs.view(webhook)["targets"]}["mcp_server"]
            self.assertEqual((row["status"], row["ready"]), ("planned", False))
            fake.output_files = lambda project, rel, face: {"mcp.json": json.dumps({"face": face, "project": project.pid})}
            row = {t["id"]: t for t in outputs.view(webhook)["targets"]}["mcp_server"]
            self.assertEqual((row["status"], row["ready"]), ("available", True))
            folder = self.folder()
            built = outputs.build(webhook, ["mcp_server"], folder, person=DEV[0], persona=DEV[1])["outputs"][0]
            with zipfile.ZipFile(folder / built["file"]) as z:
                self.assertEqual(json.loads(z.read("mcp.json"))["face"], "mcp_server")
        finally:
            if saved is None:
                sys.modules.pop(ob.FACES_MODULE, None)
            else:
                sys.modules[ob.FACES_MODULE] = saved

    def test_FR_OUT6_AC_2_a_posture_may_propose_outputs_and_never_chooses_them(self):
        loans = self.factory.new_project("Posture proposal", maturity="explore", mode="assume")
        fake = types.ModuleType(outputs.POSTURE_MODULE)
        saved = sys.modules.get(outputs.POSTURE_MODULE)
        sys.modules[outputs.POSTURE_MODULE] = fake
        try:
            self.assertEqual(outputs.proposed_targets(loans), ["container", "api", "report", "source"])   # no hook
            fake.proposed_outputs = lambda project: ["evidence_pack", "report"]
            view = outputs.view(loans)
            self.assertEqual((view["proposed"], view["chosen"]), (["report", "evidence_pack"], []))
            fake.proposed_outputs = lambda project: ["a_brochure"]                 # an unknown target: ignored
            self.assertEqual(outputs.proposed_targets(loans), ["container", "api", "report", "source"])
        finally:
            if saved is None:
                sys.modules.pop(outputs.POSTURE_MODULE, None)
            else:
                sys.modules[outputs.POSTURE_MODULE] = saved
        self.assertIsNone(loans.read("outputs.json"))                              # a proposal records nothing


if __name__ == "__main__":
    unittest.main()
