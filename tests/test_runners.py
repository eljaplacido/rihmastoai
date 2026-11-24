"""FR-HRN1: other harnesses run the factory's cells, opt-in, with the evidence saying so (D-0019).

Every harness here is a fake executable written by the test (tests/runner_fakes.py): no real Claude Code, Codex or
OpenCode runs, and no model or network is used.
"""

import contextlib
import io
import json
import os
import socket
import subprocess
import sys
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, good_cell, isolated_routing, model, no_findings  # noqa: E402
from runner_fakes import HOLDOUT_MARK, fake_harness, logged, use  # noqa: E402

from kernel import evidence_pack  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.compile import compile_project  # noqa: E402
from kernel.dispatch import build_task  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.lanes import GIT_ID, Lanes, _git  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.runners import AFTER_RUN, ASSURANCE, IN_RUN, RunnerRefused, choice, evidence_rows  # noqa: E402
from kernel.runners.detect import detect, env_name  # noqa: E402
from kernel.runners.glue import in_scope, signal_custody  # noqa: E402
from kernel.runners.harnesses import runner_for  # noqa: E402
from kernel.runners.sandbox import PROXY, plan  # noqa: E402
from kernel.spec import make_spec  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
DEV, IT = ("Dana Developer", "developer"), ("Ilkka Admin", "it")


class RunnerCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        isolated_routing(self, self.tmp)
        self.bin = self.tmp / "bin"
        self.log = self.tmp / "harness.jsonl"
        patcher = mock.patch.dict(os.environ, {"FAKE_HARNESS_LOG": str(self.log)})
        patcher.start()
        self.addCleanup(patcher.stop)
        for kind in ("gnomon", "claude-code", "codex", "opencode", "command"):   # never the real ones here
            use(self, kind, [str(self.tmp / "nowhere" / kind)])

    def compiled(self, *, agents: str | None = None):
        p = self.new(mode="assume")
        intake(p, IDEA, model=model(), requested_by="Aino")
        make_spec(p, model=model())
        compile_project(p)
        if agents:                                                       # the product's own conventions, on main
            seed = self.tmp / f"seed-{p.pid}"
            _git(self.tmp, "clone", "-q", str(p.path("repo.git")), seed.name)
            (seed / "AGENTS.md").write_text(agents, encoding="utf-8", newline="\n")
            _git(seed, "add", "AGENTS.md")
            _git(seed, *GIT_ID, "commit", "-q", "-m", "conventions")
            _git(seed, "push", "-q", "origin", "HEAD:main")
        return p

    def harness(self, kind: str, mode: str = "good", **kw):
        use(self, kind, fake_harness(self.bin, kind, mode, **kw))

    def approve(self, role: str, runner: str, *, project=None, **given) -> dict:
        c = choice.propose(self.factory, role=role, runner=runner, scope=project, person=DEV[0], persona=DEV[1],
                           reason="the team's standard harness", **given)
        if c.get("card"):
            Canon(factory_project(self.factory)).decide(c["card"], "approve", person=IT[0], persona=IT[1])
        return c

    def build(self, p, **kw):
        kw.setdefault("verifier_runner", no_findings)
        return build_task(p, "T-001", lanes=Lanes(self.tmp / "lanes", size=1), reflex_backoff=(), **kw)

    def main_of(self, p) -> str:
        return _git(p.path("repo.git"), "rev-parse", "main")


class DetectAndCommandTest(RunnerCase):
    def test_FR_HRN1_AC_1_each_runner_is_found_with_its_version_or_says_clearly_that_it_is_not(self):
        for kind, version in (("claude-code", "2.1.0"), ("codex", "0.50.0"), ("opencode", "1.2.3")):
            self.harness(kind)
            found = detect(kind)
            self.assertEqual((found["found"], found["version"]), (True, version), found)
        self.harness("command")
        named = detect("command", {"command": "agent --task {prompt_file}"})       # a named command: version + line
        self.assertTrue(named["found"])
        self.assertRegex(named["version"], r"^\d+\.\d+.*\+cmd\.[0-9a-f]{12}$")
        use(self, "codex", [str(self.tmp / "nowhere" / "codex")])
        missing = detect("codex")
        self.assertFalse(missing["found"])
        self.assertIn("Codex was not found", missing["why"])
        self.assertIn(env_name("codex"), missing["why"])                            # and what to do
        with mock.patch.dict(os.environ, {env_name("codex"): ""}), mock.patch("shutil.which", return_value=None):
            self.assertIn("`codex` is not on PATH", detect("codex")["why"])
        self.assertIn("no command is named", detect("command", {})["why"])

    def test_FR_HRN1_AC_1_each_command_line_is_headless_never_prompts_and_keeps_its_tools_to_the_working_copy(self):
        wd, task = self.tmp / "wd", self.tmp / "wd" / ".factory-tasks" / "builder-x.md"
        claude = runner_for("claude-code", {"model": "m1"}).argv(["claude"], task, wd, "builder")
        self.assertEqual(claude[:5], ["claude", "-p", "--output-format", "stream-json", "--verbose"])
        self.assertEqual(claude[claude.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(claude[claude.index("--allowedTools") + 1], "Read,Glob,Grep,Edit,Write,Bash")
        self.assertIn("WebFetch", claude[claude.index("--disallowedTools") + 1])
        review = runner_for("claude-code", {}).argv(["claude"], task, wd, "verifier")
        self.assertNotIn("Edit", review[review.index("--allowedTools") + 1].split(","))
        codex = runner_for("codex", {}).argv(["codex"], task, wd, "builder")
        self.assertEqual(codex[:3], ["codex", "exec", "--json"])
        self.assertEqual(codex[codex.index("--sandbox") + 1], "workspace-write")
        self.assertIn('approval_policy="never"', codex)
        self.assertEqual(runner_for("codex", {}).argv(["codex"], task, wd, "verifier")[4], "read-only")
        oc = runner_for("opencode", {})
        self.assertEqual(oc.argv(["opencode"], task, wd, "builder")[:4], ["opencode", "run", "--format", "json"])
        self.assertEqual(json.loads(oc.extra_env("verifier")["OPENCODE_CONFIG_CONTENT"])["permission"]["edit"], "deny")
        cmd = runner_for("command", {"command": "agent --task {prompt_file} --cwd {workdir} --as {role}"})
        self.assertEqual(cmd.argv([], task, wd, "builder"), ["agent", "--task", str(task), "--cwd", str(wd), "--as",
                                                            "builder"])
        with self.assertRaises(RunnerRefused):
            runner_for("command", {"command": "agent --cwd {workdir}"}).argv([], task, wd, "builder")


class BuildWithAHarnessTest(RunnerCase):
    def test_FR_HRN1_AC_2_a_harness_builds_inside_its_scope_and_the_round_says_who_ran_it_and_its_assurance(self):
        for kind in ("claude-code", "codex", "opencode", "command"):
            with self.subTest(kind=kind):
                p = self.compiled(agents="Use four-space indents. Name tests after the criterion.\n")
                self.harness(kind)
                given = {"command": "agent --task {prompt_file} --cwd {workdir}", "family": "acme"} \
                    if kind == "command" else {"family": "kimi"} if kind == "opencode" else {}
                self.approve("builder", kind, project=p.pid, **given)
                out = self.build(p)
                self.assertEqual(out["status"], "merged", out)
                gate = out["rounds"][-1]["gate"]
                signals = {s["name"]: s["verdict"] for s in gate["signals"]}
                self.assertEqual(signals, {"tests": "passed", "trace": "passed", "fail_first": "passed",
                                           "verifier": "passed", "scope": "passed", "custody": "passed"})
                cell = out["rounds"][-1]["cell"]["runner"]
                self.assertEqual((cell["name"], cell["assurance"]), (kind, AFTER_RUN))
                self.assertEqual(cell["assurance_label"], ASSURANCE[AFTER_RUN])
                self.assertTrue(cell["version"])
                ran = p.ledger().of_kind("runner_ran")[-1]["event"]["payload"]
                self.assertEqual(ran["tool_steps"], 2)
                written = ["app/routes.py", "tests/test_items.py"]
                self.assertEqual(sorted(c["target"] for c in ran["tool_calls"]), written)
                self.assertEqual(sorted(ran["changed"]), written)
                task = logged(self.log)[-1]["task"]
                self.assertIn("Write only inside: app/**, tests/**.", task)
                self.assertIn("contract.json", task)
                self.assertIn("Use four-space indents.", task)                       # the project's own conventions
                self.assertIn("R-1-AC-1", task)

    def test_FR_HRN1_AC_3_a_harness_that_touches_a_protected_path_or_writes_outside_its_scope_never_merges(self):
        for mode, signal, verdict in (("protected", "protected", "violation"), ("outside", "scope", "violation"),
                                      ("lazy", "fail_first", "failed")):
            with self.subTest(mode=mode):
                p = self.compiled()
                self.harness("claude-code", mode)
                self.approve("builder", "claude-code", project=p.pid)
                before = self.main_of(p)
                out = self.build(p, max_rounds=1)
                self.assertEqual(out["status"], "escalated", out)
                gate = out["rounds"][-1]["gate"]
                self.assertEqual({s["name"]: s["verdict"] for s in gate["signals"]}[signal], verdict, gate["signals"])
                self.assertFalse(gate["warranted"])
                self.assertTrue(any(o.startswith(signal) for o in gate["objections"]), gate["objections"])
                self.assertEqual(self.main_of(p), before)                         # nothing reached main
                if mode == "protected":
                    self.assertNotIn("verifier", {s["name"] for s in gate["signals"]})

    def test_FR_HRN1_AC_4_holdouts_are_never_visible_to_a_harness(self):
        p = self.compiled()
        custody = self.factory.holdouts_dir / p.pid
        custody.mkdir(parents=True, exist_ok=True)
        (custody / "R-1-AC-9.json").write_text(json.dumps({"scenario": HOLDOUT_MARK}), encoding="utf-8")
        self.harness("claude-code", "holdouts")
        self.approve("builder", "claude-code", project=p.pid)
        named = {"RIHMASTO_HOME": str(self.factory.home), "GF_LANES": str(self.tmp / "lanes")}
        with mock.patch.dict(os.environ, named):
            out = self.build(p)
        self.assertEqual(out["status"], "merged", out)
        seen = logged(self.log)[-1]
        self.assertEqual(seen["found"], [])                                     # not in its folder, task or env
        self.assertNotIn("RIHMASTO_HOME", seen["env"])
        self.assertNotIn("GF_LANES", seen["env"])
        self.assertNotIn(HOLDOUT_MARK, seen["task"])
        # a working copy that held a custody file, or overlapped the custody, is a violation
        lane = self.tmp / "lanes" / "lane-1"
        (lane / "copied.json").write_bytes((custody / "R-1-AC-9.json").read_bytes())
        self.assertEqual(signal_custody(custody, lane).verdict, "violation")
        self.assertEqual(signal_custody(lane / "app", lane).verdict, "violation")
        (lane / "copied.json").unlink()
        self.assertEqual(signal_custody(custody, lane).verdict, "passed")

    def test_FR_HRN1_AC_9_with_no_choice_gnomon_builds_exactly_as_before_and_the_round_says_in_run(self):
        p = self.compiled()
        calls = []

        def gnomon(path, prompt, **kw):
            calls.append(kw["role"])
            return good_cell(path, prompt) | {"harness": "gnomon/0.6.6+fb458ea5"}

        with mock.patch("kernel.dispatch.run_gnomon_task", side_effect=gnomon):
            out = self.build(p)
        self.assertEqual((out["status"], calls), ("merged", ["builder"]))
        gate = out["rounds"][-1]["gate"]
        self.assertEqual({s["name"] for s in gate["signals"]}, {"tests", "trace", "fail_first", "verifier"})
        line = out["rounds"][-1]["cell"]["runner"]
        self.assertEqual((line["name"], line["assurance"]), ("gnomon", IN_RUN))
        self.assertEqual(line["version"], "gnomon/0.6.6+fb458ea5")
        self.assertEqual(p.ledger().of_kind("runner_ran"), [])
        self.assertEqual(logged(self.log), [])


class ChoosingTest(RunnerCase):
    def test_FR_HRN1_AC_5_another_runner_waits_on_an_it_card_with_its_version_pinned(self):
        p = self.compiled()
        self.harness("claude-code")
        fp_before = factory_project(self.factory, False)
        for who in (("factory", "developer"), ("Dana Developer", "business_owner")):
            with self.assertRaises(DecisionRefused):
                choice.propose(self.factory, role="builder", runner="claude-code", person=who[0], persona=who[1])
        self.assertIsNone(fp_before)
        self.assertIsNone(factory_project(self.factory, False))                    # refused: nothing written
        made = choice.propose(self.factory, role="builder", runner="claude-code", person=DEV[0], persona=DEV[1])
        self.assertEqual((made["state"], made["version"]), ("waiting", "2.1.0"))  # the version found here, pinned
        fp = factory_project(self.factory)
        card = Canon(fp).get_card(made["card"])
        self.assertEqual((card["kind"], card["deciders"]), ("runner", ["it"]))
        self.assertIn("checked after every run", card["body"])
        self.assertEqual(choice.effective(self.factory, p.pid, "builder")["runner"], "gnomon")   # not yet
        with self.assertRaises(DecisionRefused):
            Canon(fp).decide(made["card"], "approve", person=DEV[0], persona=DEV[1])           # only IT
        Canon(fp).decide(made["card"], "approve", person=IT[0], persona=IT[1])
        self.assertEqual(choice.effective(self.factory, p.pid, "builder")["runner"], "claude-code")
        proposed = fp.ledger().of_kind("runner_proposed")[-1]["event"]["payload"]
        self.assertEqual((proposed["person"], proposed["version"]), (DEV[0], "2.1.0"))
        # another version on the machine: the task does not run, and the ledger says why
        self.harness("claude-code", version="2.2.0 (Claude Code)")
        out = self.build(p)
        self.assertEqual(out["status"], "runner_refused")
        self.assertIn("IT pinned 2.1.0", out["why"])
        self.assertEqual(logged(self.log), [])
        self.assertIn("2.2.0", p.ledger().of_kind("runner_refused")[-1]["event"]["payload"]["why"])
        # back to Gnomon: at once, no card
        back = choice.propose(self.factory, role="builder", runner="gnomon", person=IT[0], persona=IT[1])
        self.assertEqual((back["state"], back.get("card")), ("active", None))
        self.assertEqual(choice.effective(self.factory, p.pid, "builder")["runner"], "gnomon")

    def test_FR_HRN1_AC_5_a_runner_not_found_or_a_sandbox_without_docker_refuses_before_any_round(self):
        p = self.compiled()
        with self.assertRaises(RunnerRefused):                                     # not here, no version named
            choice.propose(self.factory, role="builder", runner="codex", person=DEV[0], persona=DEV[1])
        self.harness("codex")
        self.approve("builder", "codex", project=p.pid, sandbox="docker", image="example/codex:1")
        down = {"available": False, "version": None, "why": "Docker is not on this machine: `docker` is not on PATH"}
        with mock.patch("kernel.runners.sandbox.docker_status", return_value=down):
            out = self.build(p)
        self.assertEqual(out["status"], "runner_refused")
        self.assertIn("Docker is not on this machine", out["why"])
        self.assertEqual(logged(self.log), [])

    def test_FR_HRN1_AC_6_each_role_has_its_runner_a_project_overrides_the_factory_and_families_differ(self):
        p, q = self.compiled(), self.compiled()
        for kind in ("claude-code", "codex", "opencode"):
            self.harness(kind, "review" if kind == "codex" else "good")
        self.approve("builder", "claude-code")                                       # the factory's default
        with self.assertRaises(RunnerRefused) as caught:                             # the same family as the builder
            choice.propose(self.factory, role="verifier", runner="claude-code", person=DEV[0], persona=DEV[1])
        self.assertIn("another model family", str(caught.exception))
        self.approve("builder", "opencode", project=q.pid, model="moonshot/kimi-k2")   # q's own builder
        self.assertEqual(choice.effective(self.factory, q.pid, "builder")["runner"], "opencode")
        self.assertEqual(choice.effective(self.factory, q.pid, "builder")["family"], "kimi")
        self.assertEqual(choice.effective(self.factory, p.pid, "builder")["runner"], "claude-code")
        self.approve("verifier", "codex", project=p.pid)                             # p's verifier: another family
        out = self.build(p, verifier_runner=None)
        self.assertEqual(out["status"], "merged", out)
        verifier = next(s for s in out["rounds"][-1]["gate"]["signals"] if s["name"] == "verifier")
        self.assertEqual(verifier["verdict"], "passed")
        review = [e for e in logged(self.log) if e["mode"] == "review"][-1]
        self.assertIn("read-only", review["argv"])
        self.assertNotEqual(Path(review["cwd"]).resolve(), (self.tmp / "lanes" / "lane-1").resolve())  # a copy
        roles = [r["event"]["payload"]["role"] for r in p.ledger().of_kind("runner_ran")]
        self.assertEqual(roles, ["builder", "verifier"])
        view = choice.view(self.factory, look=False)
        self.assertEqual(view["applies"]["factory"]["builder"]["runner"], "claude-code")
        self.assertEqual(view["applies"][q.pid]["builder"]["runner"], "opencode")
        self.assertIsNone(view["applies"][p.pid]["clash"])


class EvidenceTest(RunnerCase):
    def test_FR_HRN1_AC_7_the_evidence_pack_says_which_assurance_applied_to_each_round(self):
        p = self.compiled()
        p.log("cell_ran", {"task": "T-000", "round": 0, "head": "a" * 40, "model": "m"})       # before runners
        p.log("cell_ran", {"task": "T-000", "round": 1, "head": "b" * 40, "runner": {          # a record's own words
            "name": "codex", "version": "0.50.0", "assurance": "in_run", "assurance_label": ASSURANCE[IN_RUN]}})
        self.harness("claude-code")
        self.approve("builder", "claude-code", project=p.pid)
        self.assertEqual(self.build(p)["status"], "merged")
        rows = evidence_rows([r["event"]["payload"] for r in p.ledger().of_kind("cell_ran")])
        self.assertEqual([(r["runner"], r["assurance"]) for r in rows],
                         [("gnomon", IN_RUN), ("codex", AFTER_RUN), ("claude-code", AFTER_RUN)])
        zipped = evidence_pack.export(p, self.tmp / "out", person="Kaisa Auditor", persona="compliance")
        with zipfile.ZipFile(zipped) as z:
            carried = json.loads(z.read("cell-runners.json"))
            readme = z.read("README.md").decode("utf-8")
        self.assertEqual([r["assurance_label"] for r in carried],
                         [ASSURANCE[IN_RUN], ASSURANCE[AFTER_RUN], ASSURANCE[AFTER_RUN]])
        self.assertEqual(carried[-1]["version"], "2.1.0")
        self.assertIn(f"1 round(s) {ASSURANCE[IN_RUN]}; 2 round(s) by Claude Code 2.1.0, Codex 0.50.0: "
                      f"{ASSURANCE[AFTER_RUN]}", readme)


class SandboxTest(RunnerCase):
    def test_FR_HRN1_AC_8_the_docker_sandbox_mounts_only_the_working_copy_and_reaches_only_the_model_endpoint(self):
        wd = self.tmp / "lane"
        steps = plan(["claude", "-p", str(wd / ".factory-tasks" / "t.md")], wd,
                     {"runner": "claude-code", "image": "example/claude:2.1.0", "sandbox": "docker"}, name="rc-1")
        run = steps["run"][0]
        mounts = [run[i + 1] for i, w in enumerate(run) if w == "-v"]
        self.assertEqual(len(mounts), 1)
        self.assertTrue(mounts[0].startswith(str(wd) + ":"))
        for flag in ("--cap-drop", "--security-opt", "--rm"):
            self.assertIn(flag, run)
        self.assertEqual(run[run.index("--network") + 1], "rc-1-net")
        self.assertIn(["docker", "network", "create", "--internal", "rc-1-net"], steps["setup"])
        self.assertIn("api.anthropic.com:443", steps["setup"][1])
        self.assertIn("ANTHROPIC_API_KEY", run)                                    # by name, never its value
        self.assertFalse(any("=" in w and w.startswith("ANTHROPIC") for w in run))
        self.assertIn(["docker", "network", "rm", "rc-1-net"], steps["down"])
        none = plan(["agent"], wd, {"runner": "command", "image": "example/agent:1"}, name="rc-2")["run"][0]
        self.assertEqual(none[none.index("--network") + 1], "none")
        with self.assertRaises(RunnerRefused):
            plan(["agent"], wd, {"runner": "command"}, name="rc-3")

    def test_FR_HRN1_AC_8_the_sandbox_proxy_tunnels_to_the_endpoint_and_refuses_any_other_host(self):
        upstream = socket.create_server(("127.0.0.1", 0))
        port = upstream.getsockname()[1]

        def answer() -> None:                                                     # the model endpoint, on 127.0.0.1
            conn = upstream.accept()[0]
            with conn:
                conn.sendall(b"model says hi")
                with contextlib.suppress(OSError):
                    conn.recv(16)

        threading.Thread(target=answer, daemon=True).start()
        proxy = subprocess.Popen([sys.executable, "-c", PROXY, "127.0.0.1", "0", f"127.0.0.1:{port}"],
                                 stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (proxy.kill(), proxy.wait(5), proxy.stdout.close(), upstream.close()))
        listen = int(proxy.stdout.readline())

        def connect(target: str) -> bytes:
            with socket.create_connection(("127.0.0.1", listen), timeout=10) as s:
                s.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
                data = b""
                with contextlib.suppress(OSError):
                    while b"hi" not in data and len(data) < 4096:
                        chunk = s.recv(1024)
                        if not chunk:
                            break
                        data += chunk
                return data

        self.assertIn(b"403", connect("example.org:443"))
        got = connect(f"127.0.0.1:{port}")
        self.assertIn(b"200 Connection established", got)
        self.assertIn(b"model says hi", got)


class CommandLineTest(RunnerCase):
    def cli(self, *argv: str) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_FR_HRN1_AC_9_rihmasto_runners_list_check_and_set(self):
        self.harness("claude-code")
        code, out, err = self.cli("runners", "check", "claude-code")
        self.assertEqual(code, 0, err)
        found = json.loads(out)
        self.assertEqual((found["runners"][0]["found"], found["runners"][0]["version"]), (True, "2.1.0"))
        self.assertIn("available", found["docker"])
        code, out, err = self.cli("runners", "set", "builder", "claude-code", "--reason", "team standard",
                                  "--person", DEV[0], "--persona", DEV[1])
        self.assertEqual(code, 0, err)
        made = json.loads(out)
        self.assertEqual((made["state"], made["version"], made["assurance"]), ("waiting", "2.1.0", AFTER_RUN))
        code, out, _ = self.cli("runners", "list")
        listed = json.loads(out)
        self.assertEqual(listed["choices"][0]["state"], "waiting")
        self.assertEqual(listed["applies"]["factory"]["builder"]["runner"], "gnomon")
        code, out, err = self.cli("decide", "_factory", made["card"], "approve", "--person", IT[0], "--persona", "it")
        self.assertEqual(code, 0, err)
        listed = json.loads(self.cli("runners", "list")[1])
        self.assertEqual(listed["applies"]["factory"]["builder"]["runner"], "claude-code")
        code, out, err = self.cli("runners", "set", "verifier", "claude-code", "--person", DEV[0], "--persona", DEV[1])
        self.assertEqual((code, out), (2, ""))
        self.assertIn("another model family", err)
        code, out, err = self.cli("runners", "set", "builder", "gnomon", "--person", "factory", "--persona", "it")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("not a person", err)

    def test_FR_HRN1_AC_9_in_scope_reads_a_write_scope_as_the_task_names_it(self):
        scope = ["app/**", "tests/**"]
        for path, inside in (("app/routes.py", True), ("tests/a/b/test_x.py", True), ("APP/x.py", True),
                             ("docs/x.md", False), ("contract.json", False), ("application/x.py", False)):
            self.assertEqual(in_scope(path, scope), inside, path)
        self.assertTrue(in_scope("app/x.py", ["app/*.py"]))
        self.assertFalse(in_scope("app/sub/x.py", ["app/*.py"]))


if __name__ == "__main__":
    unittest.main()
