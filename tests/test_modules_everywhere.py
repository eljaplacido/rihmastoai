"""A module that is off is off on every surface (FR-MOD5): a website's chat, a webhook, the MCP server's
write tools and the assistant's proposals ask the same set as the command line and the cockpit; what stops
something still live (revoking a chat, removing a webhook source) is never refused; and an attached
repository's own tests run only where access allows outside code to run."""

import contextlib
import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model, no_findings  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402
from test_integrations_hooks import HookCase  # noqa: E402
from test_standalone import ADD_TEST, StandaloneTestCase, git  # noqa: E402

from embed.server import _turn  # noqa: E402
from kernel import assistant, attach, gate, gate_external, modules, repo_checks  # noqa: E402
from kernel import embeds as kembeds  # noqa: E402
from kernel import hooks as khooks  # noqa: E402
from kernel.hooks import HookRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from mcp.server import TOOLS, WRITE_ROUTES, RihmaMCP  # noqa: E402

IDEA = "Our team keeps losing track of who borrowed the drills and laptops."
SITE = "https://www.example.org"
SAID = [{"role": "person", "text": "We need a loans tracker for the workshop."}]


def cli(home, *argv):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch("kernel.cli._model", model), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["--home", str(home), *argv])
    return code, (json.loads(out.getvalue()) if out.getvalue().strip() else None), err.getvalue()


class ChatsTest(FactoryTestCase):
    def test_FR_MOD5_AC_1_a_chat_whose_module_is_off_takes_no_message_and_its_owners_can_still_revoke_it(self):
        f = self.factory
        p = self.new()
        need = kembeds.create(f, kind="need", origins=[SITE], person="Aino", persona="business_owner")
        feedback = kembeds.create(f, kind="feedback", origins=[SITE], person="Aino", persona="product_owner",
                                  project_id=p.pid)
        modules.set_modules(f, person="Aino", persona="business_owner", preset="spec_only")
        with self.assertRaisesRegex(kembeds.EmbedRefused, "this chat is turned off"):
            kembeds.converse(f, need["id"], need["key"], SITE, SAID)
        status, out = _turn(f, need["id"], SITE, {"key": need["key"], "history": SAID}, model=None,
                            rate=kembeds.RateLimit(f.clock))
        self.assertEqual((status, out), (403, {"error": "this chat is turned off"}))   # the website is told
        self.assertEqual([e["messages"] for e in kembeds.embeds(f)], [0, 0])        # nothing was filed
        modules.set_modules(f, person="Aino", persona="it", enable=["integrations"])
        with self.assertRaisesRegex(kembeds.EmbedRefused, "turned off"):            # a need files into the square
            kembeds.converse(f, need["id"], need["key"], SITE, SAID)
        self.assertEqual(kembeds.turned_off(f, need), "square")
        modules.set_modules(p, person="Aino", persona="product_owner", enable=["change"])  # where feedback files
        out = kembeds.converse(f, feedback["id"], feedback["key"], SITE, SAID)
        self.assertEqual(out["filed"]["kind"], "change")
        modules.set_modules(f, person="Aino", persona="business_owner", preset="spec_only")
        self.assertNotIn("revoke_embed", modules.hidden_ids(f))                     # the assistant takes you there
        said = assistant.ask(f, "How do I revoke a chat?", persona="business_owner")
        self.assertEqual(said["navigate"], {"route": "#/settings", "control": "revoke_embed"})
        code, listed, err = cli(f.home, "embed", "list")                            # a read of what is live
        self.assertEqual(code, 0, err)
        code, out, err = cli(f.home, "embed", "revoke", need["id"], "--person", "Aino", "--persona", "business_owner")
        self.assertEqual(code, 0, err)                                               # the safety switch is core
        self.assertEqual(kembeds.embeds(f)[0]["state"], "revoked")
        rec = factory_project(f).ledger().of_kind("embed_revoked")[-1]["event"]["payload"]
        self.assertEqual((rec["id"], rec["by"], rec["persona"]), (need["id"], "Aino", "business_owner"))
        code, _, err = cli(f.home, "embed", "create", "--kind", "need", "--origin", SITE, "--person", "Aino",
                           "--persona", "business_owner")
        self.assertEqual(code, 2)                                                    # a new chat is Integrations'
        self.assertIn("embed create is part of Integrations", err)


class HooksTest(HookCase):
    def test_FR_MOD5_AC_5_a_webhook_whose_module_is_off_stores_nothing_and_it_can_still_remove_its_source(self):
        f = self.factory
        doc = {"type": "issue.created", "id": "ISS-7"}
        modules.set_modules(f, person="Aino", persona="business_owner", preset="spec_only")
        self.assertEqual(self.refused("ipaas", *self.standard(doc)), 403)          # Integrations is off
        self.assertEqual(self.refused("tracker", *self.standard(doc)), 403)
        self.assertEqual(self.refused("ipaas", *self.standard(doc, key=b"some other key entirely")), 401)  # unverified
        with self.assertRaisesRegex(HookRefused, "this source is turned off"):
            self.ring("ipaas", *self.standard(doc))
        modules.set_modules(f, person="Aino", persona="it", enable=["integrations"])
        self.assertEqual(self.refused("ipaas", *self.standard(doc)), 403)          # a signal files into the square
        self.assertEqual(khooks.turned_off(f, khooks.sources(f)[0]), "square")
        modules.set_modules(self.p, person="Aino", persona="product_owner", enable=["change"])  # where it files
        self.assertEqual(self.ring("tracker", *self.standard(doc))["status"], 202)
        modules.set_modules(f, person="Aino", persona="business_owner", preset="spec_only")
        for argv in (("hooks", "list"), ("relay", "list"), ("connector", "status", "--root", str(self.tmp))):
            code, _, err = cli(f.home, *argv)                                       # the lists a switch is found in
            self.assertEqual(code, 0, (argv, err))
        code, _, err = cli(f.home, "hooks", "remove", "ipaas", "--person", "Ilkka", "--persona", "it")
        self.assertEqual(code, 0, err)                                              # the safety switch is core
        rec = factory_project(f).ledger().of_kind("hook_source_removed")[-1]["event"]["payload"]
        self.assertEqual((rec["id"], rec["by"], rec["persona"]), ("ipaas", "Ilkka", "it"))
        code, _, err = cli(f.home, "hooks", "add", "more", "--scheme", "github", "--secret-env", "HOOK_MORE",
                           "--person", "Ilkka", "--persona", "it")
        self.assertEqual(code, 2)                                                   # a new source is Integrations'
        self.assertIn("hooks add is part of Integrations", err)


class CockpitChatsTest(CockpitTestCase):
    def test_FR_MOD5_AC_1_the_cockpit_revokes_a_chat_while_integrations_is_off_and_creates_none(self):
        e = kembeds.create(self.factory, kind="need", origins=[SITE], person="Aino", persona="business_owner")
        modules.set_modules(self.factory, person="Aino", persona="business_owner", preset="spec_only")
        status, out, _ = self.call("POST", "/api/embeds", {"kind": "need", "origins": [SITE], "person": "Aino",
                                                           "persona": "business_owner"})
        self.assertEqual(status, 403)
        status, out, _ = self.call("POST", f"/api/embeds/{e['id']}/revoke", {"person": "Aino",
                                                                             "persona": "business_owner"})
        self.assertEqual(status, 200, out)
        self.assertEqual(kembeds.embeds(self.factory)[0]["state"], "revoked")


class McpTest(FactoryTestCase):
    def call(self, server, name, **arguments):
        out = server.tools_call({"name": name, "arguments": arguments})
        return out["isError"], out["content"][0]["text"]

    def test_FR_MOD5_AC_2_the_mcp_servers_write_tools_are_refused_where_their_module_is_off(self):
        self.assertEqual({n for n, t in TOOLS.items() if not t["read"]}, set(WRITE_ROUTES))   # every write is mapped
        p = self.new()
        modules.set_modules(self.factory, person="Aino", persona="business_owner", preset="spec_only")
        s = RihmaMCP(self.factory, person="Aino", persona="business_owner", lanes_root=self.tmp / "no-lanes")
        failed, text = self.call(s, "rihma_signal", text="we need a loans tracker", source="email")
        self.assertTrue(failed)
        self.assertIn("refused: post_signal is part of Delivery square and signals", text)
        failed, text = self.call(s, "rihma_report_change", pid=p.pid, text="the form is too long")
        self.assertTrue(failed)
        self.assertIn("post_change is part of Change loop", text)
        self.assertIn(f"--enable change --project {p.pid}", text)
        self.assertEqual(p.ledger().of_kind("mcp_write"), [])                         # nothing was written
        self.assertEqual(factory_project(self.factory).ledger().of_kind("mcp_write"), [])
        failed, text = self.call(s, "rihma_comment", pid=p.pid, target_kind="project", target_id=p.pid,
                                 text="looks right")
        self.assertFalse(failed, text)                                                # a comment is core
        modules.set_modules(p, person="Aino", persona="business_owner", enable=["change"])
        failed, text = self.call(s, "rihma_report_change", pid=p.pid, text="the form is too long")
        self.assertFalse(failed, text)                                                # the project's own set decides


class AssistantTest(FactoryTestCase):
    def test_FR_MOD5_AC_3_the_assistant_offers_no_action_or_route_of_a_module_that_is_off(self):
        modules.set_modules(self.factory, person="Aino", persona="business_owner", preset="spec_only")
        p = self.new()
        intake(p, IDEA, model=model(), requested_by="Aino")
        answer = {"answer": "I can file it and show you the square.", "sources": [], "propose": [
            {"action": "report_change", "args": {"text": "the form is too long"}},
            {"action": "open", "args": {"route": "#/square"}},
            {"action": "layout_edit", "args": {"ops": [{"op": "add", "widget": "square"}]}},
            {"action": "open", "args": {"route": f"#/p/{p.pid}/questions"}}]}

        class Model:
            def ask(self, prompt, role):
                return "```json\n" + json.dumps(answer) + "\n```"

        out = assistant.ask(self.factory, "Report a change: the form is too long", persona="product_owner",
                            project_id=p.pid, model=Model(), ui={"widgets": ["square", "decisions"]})
        self.assertEqual([x["args"] for x in out["propose"]], [{"route": f"#/p/{p.pid}/questions"}])
        refused = {x["action"] + ":" + json.dumps(x["args"], sort_keys=True): x["refused"] for x in out["dropped"]}
        self.assertEqual(len(refused), 3)
        self.assertIn("Change loop is not enabled here", refused['report_change:{"text": "the form is too long"}'])
        self.assertIn("Delivery square and signals is not enabled here", refused['open:{"route": "#/square"}'])
        self.assertTrue(all("Settings, Modules turns it on" in why for why in refused.values()))
        modules.set_modules(p, person="Aino", persona="product_owner", enable=["change", "square"])
        out = assistant.ask(self.factory, "Report a change: the form is too long", persona="product_owner",
                            project_id=p.pid, model=Model(), ui={"widgets": ["square", "decisions"]})
        self.assertEqual(out["dropped"], [])                                          # all of it is on there


class FakeIsolation:
    """The access stream's isolation runner as attach.outside_code calls it: require, then serve."""

    SUITE = "the gate's run of a project's own tests"

    def __init__(self, refuse: str | None = None):
        self.refuse, self.asked, self.serving_now = refuse, [], False

    def module(self) -> types.ModuleType:
        mod = types.ModuleType(attach.ISOLATION)
        mod.SUITE, mod.require, mod.serving = self.SUITE, self.require, self.serving
        return mod

    def require(self, factory, what):
        self.asked.append((factory, what))
        if self.refuse:
            raise modules.AccessRefused(self.refuse)

    @contextlib.contextmanager
    def serving(self, factory):
        self.serving_now = True
        try:
            yield
        finally:
            self.serving_now = False


class OutsideCodeTest(StandaloneTestCase):
    def test_FR_MOD5_AC_4_an_attached_repositorys_tests_run_only_where_access_lets_outside_code_run(self):
        self.cli("modules", "set", "--preset", "full", "--person", "Aino", "--persona", "developer")
        p = self.attached("--contract", str(self.contract_file), "--branch", "main")
        self.change("fix", {"calc.py": "def add(a, b):\n    return a + b\n", "tests/test_add.py": ADD_TEST})
        real, ran = gate.run_suite, []

        def suite(*args, **kwargs):
            ran.append(runner.serving_now)
            return real(*args, **kwargs)

        enforced = types.SimpleNamespace(enforced=True)
        with mock.patch("kernel.gate.run_suite", side_effect=suite), \
                mock.patch.dict(sys.modules, {attach.ISOLATION: None}), \
                mock.patch.object(attach.kaccess, "load", return_value=enforced):
            runner = FakeIsolation()                # a Rihmasto with no isolation runner at all: refused, nothing ran
            with self.assertRaisesRegex(attach.IsolationNeeded, "no isolation runner"):
                gate_external.gate(p, person="Aino", persona="developer", head="fix", task="T-001",
                                   verifier_runner=no_findings)
            with self.assertRaises(attach.IsolationNeeded):
                repo_checks.record_releases(p, person="Aino", persona="developer", check=True)
            self.assertEqual(ran, [])
            self.assertEqual(p.ledger().of_kind("gate"), [])
            out = repo_checks.record_releases(p, person="Aino", persona="developer")   # git's claims run no code
            self.assertEqual([r["tag"] for r in out["recorded"]], ["v0.1"])
        runner = FakeIsolation(refuse="access is enforced and the access file names no isolation runner")
        with mock.patch.dict(sys.modules, {attach.ISOLATION: runner.module()}), \
                mock.patch("kernel.gate.run_suite", side_effect=suite):
            with self.assertRaisesRegex(modules.AccessRefused, "names no isolation runner"):
                gate_external.gate(p, person="Aino", persona="developer", head="fix", task="T-001",
                                   verifier_runner=no_findings)
            self.assertEqual((ran, runner.asked), ([], [(self.factory, FakeIsolation.SUITE)]))
            runner.refuse = None                                     # IT named a runner: the suite runs through it
            out = gate_external.gate(p, person="Aino", persona="developer", head="fix", task="T-001",
                                     verifier_runner=no_findings)
            self.assertEqual(out["verdict"], "passed")
            self.assertTrue(ran and all(ran))                        # every run of their tests, served
            ran.clear()
            repo_checks.record_releases(p, person="Aino", persona="developer", check=True)
            self.assertTrue(ran and all(ran))
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
