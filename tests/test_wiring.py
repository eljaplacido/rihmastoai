"""The features wired together: checks and alignment in automations, alignment in the IDE section, the measured
dimensions of Insights (checks, alignment, every role's model runs, autonomy cap hits) and the packages a
distribution installs.

Each test names the criterion it shows, appended to the requirement of the feature it joins.
"""

import copy
import json
import os
import sys
import tomllib
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from alignment_fixture import change_repo, make_repo  # noqa: E402
from console_fakes import PERSON, attached, fake_tool, git_repo  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402

from kernel import alignment_records as ar  # noqa: E402
from kernel import automations as au  # noqa: E402
from kernel import automations_actions as acts  # noqa: E402
from kernel import automations_run as run  # noqa: E402
from kernel import automations_text as words  # noqa: E402
from kernel import compile as kcompile  # noqa: E402
from kernel import ide, insights, model_usage, relay  # noqa: E402
from kernel import intake as kintake  # noqa: E402
from kernel import spec as kspec  # noqa: E402
from kernel.assistant import ask as assistant_ask  # noqa: E402
from kernel.autonomy import AutonomyCapped, cleared_to_build, set_cap  # noqa: E402
from kernel.checks import store as cstore  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.model import FakeModel, run_gnomon_task  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
IT = {"person": "Ilkka", "persona": "it"}
DEV = {"person": PERSON, "persona": "developer"}


def tiles(model: dict) -> dict:
    return {t["key"]: t for t in model["tiles"]}


def runs(project, role: str | None = None) -> list:
    rows = [r["event"]["payload"] for r in project.ledger().of_kind("model_run")]
    return [r for r in rows if role is None or r["role"] == role]


class Wired(FactoryTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "lanes")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bin = self.tmp / "bin"
        fake_tool(self.bin, "smoke-test", "import sys\nprint('smoke: 2 endpoints answer 500')\nsys.exit(1)\n")
        fake_tool(self.bin, "smoke-ok", "print('smoke: fine')\n")
        path = mock.patch.dict(os.environ, {"PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", "")})
        path.start()
        self.addCleanup(path.stop)
        self.posted = []
        self.tools = run.Tools(environ={"SLACK_URL": "https://hooks.example/slack"},
                               post=lambda url, body, headers: self.posted.append(body.decode("utf-8")) or 200)

    def template(self, tid: str, project=None) -> dict:
        t = next(t for t in words.TEMPLATES if t["id"] == tid)
        draft = copy.deepcopy(t["draft"])
        if draft["action"].get("subscription") == "":
            sub = relay.subscribe(self.factory, sink="slack", url_env="SLACK_URL", personas=["it"], **IT)
            draft["action"]["subscription"] = sub["id"]
        if draft["scope"]["kind"] == "project":
            draft["scope"]["projects"] = [project.pid]
        return au.add(self.factory, draft, **(DEV if draft["action"]["kind"] == "align_scan" else IT))

    def ran(self, aid: str) -> list:
        return [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind("automation_ran")
                if r["event"]["payload"]["id"] == aid]


class ChecksInAutomationsTest(Wired):
    def test_FR_CHK1_AC_10_run_check_is_in_the_allow_list_and_a_failed_check_notifies_through_its_template(self):
        self.assertIn("run_check", au.ACTIONS)                 # registered when the automations load, no call needed
        self.assertIn("run_check", acts.HANDLERS)
        self.assertIn("check_failed_notify", [t["id"] for t in words.TEMPLATES])
        p = attached(self.factory, git_repo(self.tmp / "orders", {"README.md": "# Orders\n"}))
        a = self.template("check_failed_notify")
        self.assertEqual((a["trigger"], a["guard"]), ({"kind": "event", "types": ["check_ran"]},
                                                      {"kind": "field", "key": "verdict", "equals": "failed"}))
        cstore.enable(p, "custom:ok", config={"command": "smoke-ok"}, **DEV)
        self.assertEqual(cstore.run(p, "custom:ok", **DEV)["verdict"], "passed")
        run.tick(self.factory, self.tools)
        self.assertEqual(self.posted, [])                                       # a passing check says nothing
        cstore.enable(p, "custom:smoke", config={"command": "smoke-test"}, **DEV)
        self.assertEqual(cstore.run(p, "custom:smoke", **DEV)["verdict"], "failed")
        run.tick(self.factory, self.tools)
        self.assertEqual(len(self.posted), 1)
        self.assertIn(f"A check failed on {p.pid} (failed)", self.posted[0])
        self.assertEqual(self.ran(a["id"])[-1]["event"], "check_ran")
        b = au.add(self.factory, {"name": "Smoke nightly", "trigger": {"kind": "schedule", "daily": "02:00"},
                                  "action": {"kind": "run_check", "check": "custom:smoke"},
                                  "scope": {"kind": "project", "projects": [p.pid]}}, **DEV)
        self.assertEqual(b["action"], {"kind": "run_check", "check": "custom:smoke"})


class AlignmentWiredTest(Wired):
    def setUp(self):
        super().setUp()
        from kernel.attach import attach

        self.repo = make_repo(self.tmp / "loans")
        self.p = attach(self.factory, "Loans", repo=self.repo, **DEV)

    def test_FR_ALN1_AC_9_the_ide_section_carries_the_accepted_alignment_and_the_open_gaps(self):
        self.assertNotIn("Aligned from your repository", ide.section(self.p))     # nothing aligned yet
        view = ar.scan(self.p, **DEV)
        req = next(i for g in view["groups"] if g["id"] == "requirements" for i in g["items"])
        ar.decide(self.p, [req["id"]], "accept", **DEV)
        text = ide.section(self.p)
        self.assertIn("### Aligned from your repository", text)
        self.assertIn(ar.accepted(self.p, "requirements")[0]["proposal"]["id"], text)
        self.assertIn("### Open gaps", text)
        self.assertLess(text.index("### Open gaps"), text.index(ide.END.format(pid=self.p.pid)))   # inside the markers

    def test_FR_ALN1_AC_10_a_repository_change_re_reads_it_for_alignment_and_records_the_drift(self):
        self.assertIn("align_scan", au.ACTIONS)
        ar.scan(self.p, **DEV)                                            # the scan a person did first
        a = self.template("align_on_change", self.p)
        self.assertEqual((a["trigger"]["kind"], a["action"]["kind"]), ("repo", "align_scan"))
        run.tick(self.factory, self.tools)                               # the head is noted, nothing fires
        self.assertEqual(self.ran(a["id"]), [])
        change_repo(self.repo)
        self.clock.advance(minutes=6)
        run.tick(self.factory, self.tools)
        row = self.ran(a["id"])[-1]
        self.assertEqual((row["trigger"], row["action"], row["outcome"]), ("repo", "align_scan", "done"))
        self.assertIn("drifted since the scan before", row["detail"])
        scans = [r["event"]["payload"] for r in self.p.ledger().of_kind("alignment_scanned")]
        self.assertEqual((len(scans), scans[-1]["person"]), (2, PERSON))  # signed by the automation's owner
        self.assertGreater(sum(scans[-1]["drift"].values()), 0)
        drift = tiles(insights.read(self.factory, "drift", pid=self.p.pid))["repo_drift"]
        self.assertTrue(drift["measured"])
        self.assertEqual(drift["value"], sum(scans[-1]["drift"].values()))


class InsightsMeasuredTest(Wired):
    def test_FR_INS1_AC_8_insights_reads_the_checks_and_the_alignment_records_as_they_are_named(self):
        p = attached(self.factory, git_repo(self.tmp / "orders", {"README.md": "# Orders\n"}))
        health = tiles(insights.read(self.factory, "health", pid=p.pid))["checks"]
        self.assertFalse(health["measured"])
        cstore.enable(p, "custom:smoke", config={"command": "smoke-test"}, **DEV)
        cstore.enable(p, "custom:ok", config={"command": "smoke-ok"}, **DEV)
        cstore.run(p, "custom:smoke", **DEV)
        cstore.run(p, "custom:ok", **DEV)
        health = tiles(insights.read(self.factory, "health", pid=p.pid))["checks"]
        self.assertEqual((health["value"], health["sub"]), (1, "of 2 checks"))
        self.assertIn("check_ran", health["basis"])
        from kernel.attach import attach

        repo = make_repo(self.tmp / "loans")
        q = attach(self.factory, "Loans", repo=repo, **DEV)
        self.assertFalse(tiles(insights.read(self.factory, "drift", pid=q.pid))["repo_drift"]["measured"])
        view = ar.scan(q, **DEV)
        item = next(i for g in view["groups"] if g["id"] == "requirements" for i in g["items"])
        ar.decide(q, [item["id"]], "reject", **DEV)
        drift = tiles(insights.read(self.factory, "drift", pid=q.pid))["repo_drift"]
        self.assertEqual(drift["value"], 0)                                 # the first scan has nothing before it
        self.assertIn("alignment_scanned", drift["basis"])
        self.assertIn("rejected", drift["sub"])


FAKE_GNOMON = """import json, sys
print(json.dumps({"session": "s-1", "model": "qwen3.6-35b", "endpoint": "local", "output": "{}",
                  "volatile": {"tokens_in": 1200, "tokens_out": 300, "requests": 2}}))
"""


class UsageEveryRoleTest(Wired):
    def test_FR_INS1_AC_9_every_role_s_model_run_is_recorded_in_the_project_and_counted_by_usage(self):
        p = self.new(title="Loans")
        script = self.tmp / "fake_gnomon.py"
        script.write_text(FAKE_GNOMON, encoding="utf-8")
        cmd = f"{Path(sys.executable).as_posix()} {script.as_posix()}"
        lane = self.tmp / "lane"
        lane.mkdir()
        with mock.patch.dict(os.environ, {"GNOMON_CMD": cmd}):
            with model_usage.for_project(p, task="T-001"):
                run_gnomon_task(lane, "review the change", role="verifier")
                run_gnomon_task(lane, "build it", role="builder")              # the builder has its own record
            run_gnomon_task(lane, "outside any project", role="analyst")          # nothing names a project
        [verifier] = runs(p, "verifier")
        self.assertEqual((verifier["model"], verifier["endpoint"], verifier["tokens"]["in"], verifier["task"]),
                         ("qwen3.6-35b", "local", 1200, "T-001"))
        self.assertTrue(verifier["cost"]["measured"])                         # priced (a local model)
        self.assertGreaterEqual(verifier["seconds"], 0)
        self.assertEqual(runs(p, "builder"), [])
        self.assertEqual(len(runs(p)), 1)
        secret = "the holdout scenario nobody may see"
        with model_usage.for_project(p, task="holdouts"):
            FakeModel({"holdout_author": [secret]}).ask(f"write {secret}", role="holdout_author")
        [held] = runs(p, "holdout_author")
        self.assertNotIn(secret, json.dumps(held))                            # ids and counts only
        self.assertFalse(held["cost"]["measured"])                            # no token counts: never zero
        with model_usage.for_project(p, task="intake"):
            FakeModel({"analyst": ["{}"]}).ask("the request", role="analyst")
        assistant_ask(self.factory, "How is Loans doing?", persona="product_owner", project_id=p.pid,
                      model=FakeModel(lambda prompt, role: json.dumps({"answer": "It waits on its intake."})))
        self.assertEqual({r["role"] for r in runs(p)}, {"verifier", "holdout_author", "analyst", "assistant"})
        for fn in (kintake.intake, kspec.make_spec, kcompile.author_holdouts):  # the entry points say the project
            self.assertTrue(hasattr(fn, "__wrapped__"), fn.__name__)
        usage = tiles(insights.read(self.factory, "usage", pid=p.pid))
        self.assertEqual(usage["runs"]["value"], 4)
        self.assertEqual(usage["tokens"]["value"], 1500)
        self.assertNotIn("Tokens of the analyst", json.dumps(insights.read(self.factory, "usage", pid=p.pid)["gaps"]))

    def test_FR_INS1_AC_9_an_autonomy_cap_hit_is_recorded_and_governance_counts_it(self):
        p = self.new(title="Loans")
        set_cap(p, 2, person="Kaisa", persona="business_owner", reason="look first")
        with self.assertRaises(AutonomyCapped):
            cleared_to_build(p)
        [hit] = [r["event"]["payload"] for r in p.ledger().of_kind("autonomy_capped")]
        self.assertEqual((hit["needed"], hit["cap"], hit["what"]), (3, 2, "building"))
        gov = tiles(insights.read(self.factory, "governance", pid=p.pid))["autonomy_capped"]
        self.assertEqual(gov["value"], 1)
        self.assertIn("building", gov["line"])


class PackagesTest(unittest.TestCase):
    def test_FR_REL1_AC_5_the_distribution_lists_every_package_directory(self):
        listed = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]["packages"]
        found = sorted(".".join(init.parent.relative_to(REPO).parts)
                       for top in ("kernel", "adapters", "cockpit", "embed", "mcp")
                       for init in (REPO / top).rglob("__init__.py") if "__pycache__" not in init.parts)
        self.assertEqual(sorted(listed), found)
        for name in ("kernel.checks", "kernel.redteam", "kernel.insights", "kernel.runners"):
            self.assertIn(name, listed)


if __name__ == "__main__":
    unittest.main()
