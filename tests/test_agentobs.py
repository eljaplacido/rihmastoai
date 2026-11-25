"""Agent observability (FR-OBS1): the IDE agents' sessions, read from the team's own hub, per project.

Every hub here is tests/agentobs_hub_stub.py on 127.0.0.1, answering as the hub's documented `/v1` contract does.
Nothing reaches any other address. Skipped without git (a repository is attached).
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from agentobs_hub_stub import EMPTY, PROJECT, HubStub  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import agentobs, assistant, modules  # noqa: E402
from kernel import automations as au  # noqa: E402
from kernel import automations_actions as acts  # noqa: E402
from kernel import automations_text as words  # noqa: E402
from kernel.agentobs import feeds, mapping, snapshot  # noqa: E402
from kernel.agentobs.client import Hub, HubUnreachable  # noqa: E402
from kernel.agentobs.view import build  # noqa: E402
from kernel.attach import attach  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.modules import ModuleOff  # noqa: E402

IT, DEV = "Ilkka Example", "Dana Example"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}


def make_repo(tmp: Path, *, hooks: bool = True, catalog: str | None = None,
              remote: str = "git@github.com:acme/checkout.git") -> Path:
    """A repository: the hub's hooks for Claude Code and OpenCode by name, and a git remote."""
    folder = tmp / "checkout"
    (folder / "src").mkdir(parents=True, exist_ok=True)
    (folder / "src" / "total.ts").write_text("export const total = 1;\n", encoding="utf-8")
    (folder / "AGENTS.md").write_text("# Conventions\n", encoding="utf-8")
    if hooks:
        for rel in (".claude/hooks/cockpit-hook.cmd", ".opencode/plugins/cockpit.js"):
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            (folder / rel).write_text("hook\n", encoding="utf-8")
    if catalog:
        (folder / "catalog-info.yaml").write_text(
            "metadata:\n  annotations:\n    cockpit.io/project-id: " + catalog + "\n", encoding="utf-8")
    git(folder, "init", "-q", "-b", "main")
    git(folder, "remote", "add", "origin", remote)
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "first")
    return folder


def attached(factory, tmp: Path, **kw):
    folder = make_repo(tmp, **kw)
    return attach(factory, "Checkout", repo=folder, person=DEV, persona="developer"), folder


def turn_on(project) -> None:
    modules.set_modules(project, person=DEV, persona="developer", enable=[agentobs.MODULE])


class ObsCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        if shutil.which("git") is None:
            self.skipTest("git is needed for an attached repository")

    def attached(self, **kw):
        return attached(self.factory, self.tmp, **kw)

    def on(self, project):
        turn_on(project)

    def hub_set(self, url):
        agentobs.set_settings(self.factory, url=url, person=IT, persona="it")

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()


class ModuleAndSettingsTest(ObsCase):
    def test_FR_OBS1_AC_1_the_module_is_off_by_default_in_no_preset_and_turned_on_per_project(self):
        self.assertNotIn("agentobs", modules.enabled(self.factory))
        self.assertTrue(modules.MODULES["agentobs"]["optin"])
        for preset in modules.PRESETS.values():
            self.assertNotIn("agentobs", preset["modules"])
        p, _ = self.attached()
        self.assertFalse(agentobs.module_on(p))
        with self.assertRaises(ModuleOff):
            snapshot.record(self.factory, p, person=DEV, persona="developer")
        code, _, err = self.cli("agentobs", "map", p.pid, "--hub-project", PROJECT, "--person", DEV, "--persona",
                                "developer")
        self.assertEqual(code, 2)
        self.assertIn("modules set --enable agentobs", err)
        self.on(p)
        self.assertTrue(agentobs.module_on(p))
        self.assertFalse(agentobs.module_on(self.factory))                 # the factory's set is as it was
        self.assertEqual(p.ledger().of_kind("modules_set")[-1]["event"]["payload"]["to"][-1], "agentobs")
        modules.set_modules(self.factory, person=IT, persona="it", preset="full")
        modules.set_modules(self.factory, person=IT, persona="it", enable=["agentobs"])
        got = modules.factory_set(self.factory)
        self.assertEqual((got["preset"], "agentobs" in got["modules"]), ("full", True))   # full, and the opt-in

    def test_FR_OBS1_AC_2_it_sets_the_hub_a_hosted_one_only_with_consent_and_a_token_only_by_name(self):
        with self.assertRaisesRegex(DecisionRefused, "IT does"):
            agentobs.set_settings(self.factory, url="http://127.0.0.1:8787", person=DEV, persona="developer")
        with self.assertRaisesRegex(agentobs.HostedRefused, "hosted address"):
            agentobs.set_settings(self.factory, url="https://hub.example.com", person=IT, persona="it")
        self.assertIsNone(factory_project(self.factory, create=False))       # refused: nothing recorded
        with self.assertRaisesRegex(ValueError, "https only"):
            agentobs.set_settings(self.factory, url="http://hub.example.com", person=IT, persona="it", hosted=True)
        with self.assertRaisesRegex(ValueError, "environment variable"):
            agentobs.set_settings(self.factory, url="http://127.0.0.1:8787", person=IT, persona="it",
                                  token_env="s3cr3t-value")
        with self.assertRaisesRegex(ValueError, "no credentials"):
            agentobs.set_settings(self.factory, url="http://user:pw@127.0.0.1:8787", person=IT, persona="it")
        lan = "http://" + ".".join(["192", "168", "1", "20"]) + ":8787"     # joined: no literal address ships
        for url, private, where in (("http://127.0.0.1:8787", False, "loopback"), (lan, False,
                                    "private"), ("http://hub.tail1234.ts.net:8787", True, "declared")):
            s = agentobs.set_settings(self.factory, url=url, person=IT, persona="it", private=private,
                                      token_env="COCKPIT_HUB_TOKEN")
            self.assertEqual((s["url"], s["where"], s["hosted_consent"]), (url, where, None))
        s = agentobs.set_settings(self.factory, url="https://hub.example.com", person=IT, persona="it", hosted=True)
        self.assertEqual((s["where"], s["hosted_consent"]["by"]), ("hosted", IT))
        recs = [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind("agentobs_settings_set")]
        self.assertEqual([r["where"] for r in recs], ["loopback", "private", "declared", "hosted"])
        self.assertEqual(recs[0]["token_env"], "COCKPIT_HUB_TOKEN")
        code, _, err = self.cli("agentobs", "settings", "--url", "https://other.example.com", "--person", IT,
                                "--persona", "it")
        self.assertEqual(code, 2)
        self.assertIn("hosted address", err)


class MappingAndViewTest(ObsCase):
    def test_FR_OBS1_AC_3_the_mapping_is_suggested_from_the_repository_confirmed_by_a_person_and_recorded(self):
        p, folder = self.attached(catalog="acme/checkout-pinned")
        before = tree(folder)
        ids = [c["id"] for c in mapping.candidates(p)]
        self.assertEqual(ids, ["acme/checkout-pinned", "acme/checkout", "local/checkout"])   # catalog, remote, folder
        listed = [{"project_id": PROJECT, "repository_id": PROJECT}]
        self.assertEqual(mapping.suggest(mapping.candidates(p), listed)["id"], PROJECT)
        self.assertIsNone(mapping.suggest([{"id": "x/y", "from": "f"}], listed))
        with self.assertRaisesRegex(DecisionRefused, "developer or IT"):
            mapping.map_project(p, PROJECT, person="Sanna Example", persona="stakeholder")
        with self.assertRaisesRegex(ValueError, "owner/name"):
            mapping.map_project(p, "../../etc", person=DEV, persona="developer")
        doc = mapping.map_project(p, PROJECT, person=DEV, persona="developer", how="suggested")
        self.assertEqual((doc["hub_project"], doc["from"], doc["how"]), (PROJECT, "the git remote origin", "suggested"))
        rec = p.ledger().of_kind("agentobs_mapped")[-1]["event"]["payload"]
        self.assertEqual((rec["hub_project"], rec["person"], rec["persona"]), (PROJECT, DEV, "developer"))
        mapping.map_project(p, "", person=DEV, persona="developer")
        self.assertIsNone(mapping.current(p))
        self.assertEqual(p.ledger().of_kind("agentobs_unmapped")[-1]["event"]["payload"]["hub_project"], PROJECT)
        self.assertEqual(tree(folder), before)                              # nothing written to the repository
        self.assertEqual(git(folder, "status", "--porcelain"), "")

    def test_FR_OBS1_AC_4_the_view_reads_the_hub_by_its_contract_and_only_for_developers_and_it(self):
        p, _ = self.attached()
        self.on(p)
        with HubStub() as stub, mock.patch.dict(os.environ, {"COCKPIT_HUB_TOKEN": "tok-for-the-test"}):
            agentobs.set_settings(self.factory, url=stub.url, person=IT, persona="it", token_env="COCKPIT_HUB_TOKEN")
            mapping.map_project(p, PROJECT, person=DEV, persona="developer")
            v = build(self.factory, p, persona="developer")
            self.assertTrue(stub.requests)
            self.assertEqual({r["method"] for r in stub.requests}, {"GET"})          # read only
            self.assertTrue(all(r["headers"].get("Authorization") == "Bearer tok-for-the-test" for r in stub.requests))
            n = len(stub.requests)
            other = build(self.factory, p, persona="business_owner")
            self.assertEqual(len(stub.requests), n)                                   # not for them: nothing read
        self.assertFalse(other["applies"])
        self.assertNotIn("tok-for-the-test", json.dumps(v))
        sec = v["sections"]
        self.assertEqual((sec["sessions"]["count"], sec["sessions"]["totals"]),
                         (5, {"claude-code": 3, "cursor": 1, "opencode": 1}))
        self.assertEqual(sec["sessions"]["harnesses"], ["claude-code", "cursor", "opencode"])
        self.assertEqual(sec["rework"]["files"][0]["file"], "src/checkout/total.ts")
        self.assertEqual(sec["rework"]["files_above_threshold"], 2)
        self.assertEqual((sec["failures"]["recovered_failures"], sec["failures"]["blocked_failures"],
                          sec["failures"]["undetermined_failures"]), (1, 1, 1))
        self.assertEqual([r["session_id"] for r in sec["failures"]["unrecovered_sessions"]], ["s-opencode-1"])
        rows = {r["session_id"]: r for r in v["sessions"]}
        self.assertEqual(rows["s-claude-1"]["failures"]["recovered"], 1)
        self.assertEqual(rows["s-cursor-1"]["failures"]["undetermined"], 1)
        self.assertEqual({k: rows[k]["contract_first"] for k in rows},
                         {"s-claude-1": True, "s-cursor-1": False, "s-opencode-1": True, "s-claude-2": False,
                          "s-claude-3": None})
        self.assertEqual((sec["governance"]["contract_engagement_rate"], sec["governance"]["per_session"]),
                         (0.5, {"read_first": 2, "edited_without": 2, "not_measured": 1}))
        self.assertIn("fail", rows["s-opencode-1"]["strip"])
        self.assertEqual(sec["trajectory"]["corrective"], 5)
        self.assertEqual((sec["chain"]["valid"], sec["chain"]["checked"], sec["chain"]["attests"]),
                         (True, 87, "derived-on-load"))
        self.assertIn("self-consistent", sec["chain"]["meaning"])
        self.assertTrue(v["hub"]["ui"].endswith("/#project=acme%2Fcheckout"))
        self.assertEqual(Hub("http://127.0.0.1:1").ui(PROJECT), "http://127.0.0.1:1/#project=acme%2Fcheckout")

    def test_FR_OBS1_AC_5_what_the_hub_does_not_have_is_not_measured_with_why_and_how_never_zero(self):
        p, folder = self.attached(hooks=False)
        self.on(p)
        v = build(self.factory, p, persona="it")
        self.assertFalse(v["hub"]["configured"])
        self.assertTrue(all(not s["measured"] and s["why"] and s["how"] for s in v["sections"].values()))
        self.hub_set("http://127.0.0.1:9")                                   # nothing listens there
        v = build(self.factory, p, persona="it")
        self.assertFalse(v["hub"]["reachable"])
        self.assertIn("did not answer", v["sections"]["chain"]["why"])
        with HubStub() as stub:
            self.hub_set(stub.url)
            v = build(self.factory, p, persona="it")
            self.assertIn("not mapped", v["sections"]["sessions"]["why"])
            self.assertEqual(v["mapping"]["suggested"]["id"], PROJECT)
            mapping.map_project(p, "acme/nowhere", person=DEV, persona="developer")
            v = build(self.factory, p, persona="it")
            how = v["sections"]["rework"]["how"]
            self.assertIn("no project acme/nowhere", v["sections"]["rework"]["why"])
            self.assertIn("npm run cockpit -- install --project " + str(folder), how)
            self.assertFalse(v["instrumentation"]["instrumented"])
            mapping.map_project(p, EMPTY, person=DEV, persona="developer")
            v = build(self.factory, p, persona="it")
            self.assertTrue(all(not v["sections"][k]["measured"] for k in ("sessions", "rework", "failures",
                                                                          "trajectory", "governance")))
            self.assertNotIn(0, [v["sections"][k].get("count") for k in v["sections"]])
            mapping.map_project(p, PROJECT, person=DEV, persona="developer")
            stub.chain_status = 503
            self.assertIn("longer than it verifies", build(self.factory, p, persona="it")["sections"]["chain"]["why"])
            stub.chain_status = 409
            chain = build(self.factory, p, persona="it")["sections"]["chain"]
            self.assertEqual((chain["measured"], chain["valid"], chain["breaks"]), (True, False, 1))
        with self.assertRaises(HubUnreachable):
            Hub("http://127.0.0.1:9", timeout=1).health()


class SnapshotAndFeedsTest(ObsCase):
    def mapped(self, stub):
        p, _ = self.attached()
        self.on(p)
        self.hub_set(stub.url)
        mapping.map_project(p, PROJECT, person=DEV, persona="developer")
        return p

    def test_FR_OBS1_AC_6_a_snapshot_records_counts_and_ids_and_what_is_new_and_automations_use_it(self):
        with HubStub() as stub:
            p = self.mapped(stub)
            first = snapshot.record(self.factory, p, person=DEV, persona="developer")
            self.assertEqual(first["new"], ["agent_failure_unrecovered", "agent_rework_heavy"])
            again = snapshot.record(self.factory, p, person=DEV, persona="developer")
            self.assertEqual(again["new"], [])                                # nothing new: no second notice
            self.assertEqual(len(p.ledger().of_kind("agent_rework_heavy")), 1)
            rec = p.ledger().of_kind("agent_sessions_observed")[0]["event"]["payload"]
            self.assertEqual((rec["sessions"], rec["unrecovered_sessions"], rec["chain_valid"], rec["person"]),
                             (5, ["s-opencode-1"], True, DEV))
            self.assertNotIn("steps", json.dumps(rec))                        # counts and ids, never the steps
            self.assertIn("agent_snapshot", au.ACTIONS)
            self.assertEqual(acts.MODULE["agent_snapshot"], "agentobs")
            ids = {t["id"] for t in words.TEMPLATES}
            self.assertTrue({"agent_rework_notify", "agent_snapshot_daily", "agent_failure_notify"} <= ids)
            t = next(t for t in words.TEMPLATES if t["id"] == "agent_snapshot_daily")
            a = au.add(self.factory, {**t["draft"], "scope": {"kind": "project", "projects": [p.pid]}}, person=DEV,
                       persona="developer")
            out = acts.run(self.factory, au.get(self.factory, a["id"]), {"project": p.pid, "trigger": "schedule"},
                           None)
            self.assertEqual(out["outcome"], "done", out)
            self.assertEqual(p.ledger().of_kind("agent_sessions_observed")[-1]["event"]["payload"]["via"],
                             f"automation {a['id']}")
            rework = next(t for t in words.TEMPLATES if t["id"] == "agent_rework_notify")
            self.assertEqual(rework["draft"]["trigger"]["types"], ["agent_rework_heavy"])

    def test_FR_OBS1_AC_7_insights_review_the_channel_the_copilot_and_the_checks_read_it_through_hooks(self):
        with HubStub() as stub:
            p = self.mapped(stub)
            qa = {t["key"]: t for t in feeds.insight_tiles(self.factory, "qa", pid=p.pid, window="all")}
            self.assertEqual((qa["ide_rework"]["value"], qa["ide_unrecovered"]["value"]), (2, 1))
            gov = feeds.insight_tiles(self.factory, "governance", window="all")[0]
            self.assertEqual((gov["value"], gov["unit"]), (50.0, "%"))
            use = feeds.insight_tiles(self.factory, "usage", pid=p.pid, window="7d")[0]
            self.assertEqual(use["value"], 5)
            self.assertIn("claude-code 3", use["sub"])
            self.assertEqual(feeds.insight_tiles(self.factory, "security", pid=p.pid), [])
            items = feeds.review_items(self.factory, pid=p.pid)
            self.assertEqual({i["kind"] for i in items}, {"agent_failure", "agent_rework"})
            self.assertTrue(all(i["group"] == "from_ide_agents" and i["links"] for i in items))
            fail = next(i for i in items if i["kind"] == "agent_failure")
            self.assertIn("src/checkout/tax.ts", fail["title"])
            later = feeds.review_items(self.factory, pid=p.pid, since="2026-11-22T00:00:00Z")
            self.assertEqual([i["kind"] for i in later], [])                    # only the newest session since then
            msgs = [{"id": "M-0001", "author": {"kind": "agent", "name": "claude-code"},
                     "trace": {"session_id": "s-claude-1"}},
                    {"id": "M-0002", "author": {"kind": "person", "name": DEV}, "trace": {"session_id": "s-cursor-1"}}]
            links = feeds.session_links(self.factory, p, msgs)
            self.assertEqual(list(links), ["M-0001"])
            self.assertEqual(links["M-0001"]["harness"], "claude-code")
            check = feeds.check_result(self.factory, p)
            self.assertEqual(check["verdict"], "failed")
            self.assertIn("edit on src/checkout/tax.ts", check["evidence"][0])
            stub.empty = True
            self.assertEqual(feeds.check_result(self.factory, p)["verdict"], "not measured")
            if feeds.optional("kernel.insights.base") is not None:            # the tile shape, when it is built
                self.assertEqual(set(qa["ide_rework"]), set(feeds.optional("kernel.insights.base").tile(
                    "k", "l", 1, basis="b")))
            spec = feeds.check_spec()
            self.assertEqual(spec is None, feeds.optional("kernel.checks") is None)

    def test_FR_OBS1_AC_8_an_attached_repository_carrying_the_hubs_hooks_is_seen_by_name_and_offered(self):
        p, folder = self.attached()
        seen = p.ledger().of_kind("agentobs_instrumentation_seen")
        self.assertEqual(seen[-1]["event"]["payload"]["harnesses"], ["claude-code", "opencode"])
        inst = mapping.instrumentation(p)
        self.assertEqual((inst["instrumented"], inst["files"]),
                         (True, [".claude/hooks/cockpit-hook.cmd", ".opencode/plugins/cockpit.js"]))
        self.assertIn("names only", inst["by"])
        offer = feeds.catalogue_entry(self.factory, p)
        self.assertEqual((offer["suggest"], offer["on"]), (True, False))
        self.on(p)
        self.assertFalse(feeds.catalogue_entry(self.factory, p)["suggest"])
        self.assertEqual(git(folder, "status", "--porcelain"), "")             # nothing written there
        plain = self.factory.new_project("Built here", mode="mixed", maturity="demo")
        self.assertFalse(mapping.instrumentation(plain)["applies"])
        self.assertFalse(feeds.catalogue_entry(self.factory, plain)["suggest"])


class AskRihmaTest(ObsCase):
    def test_FR_OBS1_AC_9_ask_rihma_explains_opens_and_proposes_turning_it_on_and_mapping(self):
        p, _ = self.attached()
        ask = lambda q, persona="developer": assistant.ask(self.factory, q, persona=persona, project_id=p.pid)  # noqa
        out = ask("Show me the agent sessions")
        self.assertEqual(out["navigate"]["route"], "#/settings")
        self.assertEqual([x["action"] for x in out["propose"]], ["agentobs_enable"])
        self.assertIn("off", out["answer"])
        self.on(p)
        self.assertIn("for developers and IT", ask("How are the IDE agents doing?", "stakeholder")["answer"])
        with HubStub() as stub:
            self.hub_set(stub.url)
            out = ask("Which rework hotspots do the IDE agents have?")
            self.assertEqual(out["propose"][0]["action"], "agentobs_map")
            self.assertEqual(out["propose"][0]["args"]["hub_project"], PROJECT)
            mapping.map_project(p, PROJECT, person=DEV, persona="developer")
            out = ask("How are the agent sessions going?")
            self.assertEqual(out["navigate"]["route"], f"#/p/{p.pid}/agent_sessions")
            self.assertIn("5 sessions", out["answer"])
            self.assertIn("unrecovered failures: 1 sessions", out["answer"])
            self.assertIn("contract read before edit: 50%", out["answer"])
        self.assertIsNone(assistant.agentobs_q.answer(self.factory, "Where do I log a signal?", p, "developer"))
        ui = json.loads((Path(__file__).parent.parent / "cockpit" / "ui_map.json").read_text(encoding="utf-8"))
        view = next(v for v in ui["views"] if v["id"] == "agent_sessions")
        self.assertEqual((view["label"], view["route"]), ("Agent sessions", "#/p/{pid}/agent_sessions"))
        self.assertIn("rework hotspots", view["synonyms"])
        controls = {c["id"]: c for c in ui["controls"]}
        for cid in ("agent_sessions_map", "agent_sessions_snapshot", "agent_observability_settings"):
            self.assertIn(cid, assistant.CONTROL_PAGES)
            self.assertIn(cid, controls)
        hits = assistant.find_in_map("where are the rework hotspots")
        self.assertEqual(hits[0]["id"], "agent_sessions")


class RoutesTest(CockpitTestCase):
    def test_FR_OBS1_AC_4_the_cockpit_routes_read_and_sign_and_refuse_a_hosted_hub_without_consent(self):
        if shutil.which("git") is None:
            self.skipTest("git is needed for an attached repository")
        p, _ = attached(self.factory, self.tmp)
        status, out, _ = self.call("PUT", "/api/agent-observability", {"url": "https://hub.example.com",
                                                                       "person": IT, "persona": "it"})
        self.assertEqual(status, 403, out)
        self.assertIn("hosted address", out["error"])
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/agent-sessions/map",
                                   {"hub_project": PROJECT, "person": DEV, "persona": "developer"})
        self.assertEqual(status, 403, out)                                    # the module is off for the project
        self.assertIn("Agent observability", out["error"])
        turn_on(p)
        with HubStub() as stub:
            status, out, _ = self.call("PUT", "/api/agent-observability", {"url": stub.url, "person": IT,
                                                                           "persona": "it"})
            self.assertEqual((status, out["settings"]["url"], out["on_anywhere"]), (200, stub.url, True))
            status, out, _ = self.call("GET", f"/api/projects/{p.pid}/agent-sessions?persona=developer")
            self.assertEqual((status, out["mapping"]["suggested"]["id"]), (200, PROJECT))
            status, out, _ = self.call("POST", f"/api/projects/{p.pid}/agent-sessions/map",
                                       {"hub_project": PROJECT, "how": "suggested", "person": DEV,
                                        "persona": "developer"})
            self.assertEqual((status, out["mapping"]["how"]), (200, "suggested"))
            status, out, _ = self.call("GET", f"/api/projects/{p.pid}/agent-sessions?persona=it")
            self.assertTrue(out["sections"]["chain"]["valid"])
            status, out, _ = self.call("GET", f"/api/projects/{p.pid}/agent-sessions?persona=end_user")
            self.assertFalse(out["applies"])
            status, out, _ = self.call("POST", f"/api/projects/{p.pid}/agent-sessions/snapshot",
                                       {"person": DEV, "persona": "developer"})
            self.assertEqual((status, out["snapshot"]["sessions"]), (200, 5))
            status, out, _ = self.call("GET", "/api/agent-observability?check=1")
            self.assertEqual(out["hub"]["chain_attests"], "derived-on-load")
            status, out, _ = self.call("GET", f"/api/projects/{p.pid}/ai-tools?persona=developer")
            self.assertTrue(out["agent_observability"]["instrumentation"]["instrumented"])

    def test_FR_OBS1_FR_PPL1_viewing_everything_the_solo_person_reads_sets_and_asks_without_switching(self):
        """The solo person holds every persona: viewing "everything" with business owner as the last persona
        named, the view is read as a developer, the hub's address is signed as IT, and Ask Rihma answers."""
        if shutil.which("git") is None:
            self.skipTest("git is needed for an attached repository")
        p, _ = attached(self.factory, self.tmp)
        turn_on(p)
        base = f"/api/projects/{p.pid}/agent-sessions?persona=business_owner"
        self.assertFalse(self.call("GET", base)[1]["applies"])                  # a persona named alone is kept
        status, out, _ = self.call("GET", base + "&as_needed=1")
        self.assertEqual((status, out["applies"], out["persona"]), (200, True, "developer"), out)
        self.assertIn("no address is set", json.dumps(out["sections"]))         # not measured, and says why
        with HubStub() as stub:
            status, out, _ = self.call("PUT", "/api/agent-observability", {"url": stub.url, "person": IT,
                                                                           "persona": "business_owner",
                                                                           "as_needed": True})
            self.assertEqual((status, out["settings"]["url"]), (200, stub.url), out)
            self.assertEqual(out["settings"]["set_by"], IT)
            question = {"question": "How are the agent sessions going?", "persona": "business_owner",
                        "person": IT, "project": p.pid}
            status, out, _ = self.call("POST", "/api/assistant", question)
            self.assertIn("switch persona", out["answer"])                      # a persona named alone is kept
            status, out, _ = self.call("POST", "/api/assistant", question | {"everything": True})
            self.assertEqual(status, 200, out)
            self.assertNotIn("switch persona", out["answer"])
            self.assertEqual([x["action"] for x in out["propose"]], ["agentobs_map"])


if __name__ == "__main__":
    unittest.main()
