"""Round three wired together: self-healing with agent observability, Gnomon's audits and the role evals, solo and
team mode, and its own feedback; solo mode with every new write route.

- FR-HEAL1-AC-10: an IDE agent's failure the observability hub saw it not recover from opens an incident (the hub is
  tests/agentobs_hub_stub.py on 127.0.0.1);
- FR-HEAL1-AC-11: a failed Gnomon audit (a fake ``gnomon`` on PATH, tests/gnomon_fakes.py) or a role eval with wrong
  answers (scripted models) opens an incident with its findings as context;
- FR-HEAL1-AC-12: in solo mode the solo person approves learned remedies and Rihmasto's own pull requests; in team
  mode approvals follow the team's roles;
- FR-HEAL1-AC-13: an approved prompt rule is read by every agent prompt through one hook (kernel/prompt_rules.py);
- FR-PPL1-AC-9: every write route names the persona it needs in solo mode (cockpit/solo_routes.py NEEDS).
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import gnomon_fakes as gf  # noqa: E402
from agentobs_hub_stub import PROJECT, HubStub  # noqa: E402
from factory_fakes import FactoryTestCase, isolated_routing  # noqa: E402
from test_agentobs import DEV, ObsCase  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402
from test_gnomon_evals import EvalsCase  # noqa: E402
from test_people import AINO, BEA, PeopleCase  # noqa: E402
from test_role_evals import bad, good  # noqa: E402

from cockpit import server as cockpit  # noqa: E402
from cockpit import solo_routes  # noqa: E402
from kernel import channel_rihma, copilot, feedback, heal_fix, heal_wiring, immune, intake, prompt_rules  # noqa: E402
from kernel import delegation as kdelegation  # noqa: E402
from kernel import incidents as inc  # noqa: E402
from kernel import role_evals as rv  # noqa: E402
from kernel import team as kteam  # noqa: E402
from kernel.agentobs import mapping, snapshot  # noqa: E402
from kernel.assistant import ask  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.model import FakeModel  # noqa: E402
from kernel.spec import spec_prompt  # noqa: E402
from kernel.store import write_json  # noqa: E402

RULE = "Name the requirement id each answer rests on."
RIHMASTO_FIX = {"id": "F-0001", "incident": "I-0001", "target": "rihmasto", "gate": {"verdict": "passed",
                                                                                   "objections": []},
                "pr": None, "branch": "rihmasto/fix-i-0001", "base_branch": "main"}


def remedy(factory, pid: str | None = None) -> dict:
    """A proposed remedy: an incident resolved by a person, what fixed it learned for its fingerprint."""
    doc = inc.open_incident(factory, kind="view_broken", where="outputs", project=pid, message="TypeError: x")
    how = immune.resolution_action({"kind": "link", "href": "#/home", "label": "Open Home"})
    return immune.learn(factory, doc, how, person="Aino", persona="developer")


class AgentFailureTest(ObsCase):
    def test_FR_HEAL1_AC_10_an_unrecovered_agent_failure_from_the_observability_hub_opens_an_incident(self):
        with HubStub() as stub:
            p, _ = self.attached()
            self.on(p)
            self.hub_set(stub.url)
            mapping.map_project(p, PROJECT, person=DEV, persona="developer")
            first = snapshot.record(self.factory, p, person=DEV, persona="developer")
            self.assertIn("agent_failure_unrecovered", first["new"])
            opened = heal_wiring.sweep(self.factory)
            again = snapshot.record(self.factory, p, person=DEV, persona="developer")   # nothing new: nothing opened
        self.assertEqual(again["new"], [])
        self.assertEqual(heal_wiring.sweep(self.factory), [])
        rows = [i for i in inc.incidents(self.factory, pid=p.pid) if i["kind"] == "agent_failed"]
        self.assertEqual([r["id"] for r in rows], opened)
        doc = inc.get(self.factory, rows[0]["id"])
        self.assertEqual((doc["context"]["hub_project"], doc["context"]["sessions"]), (PROJECT, ["s-opencode-1"]))
        self.assertEqual(doc["where"], f"agent:{PROJECT}")
        offer = immune.offered(self.factory, doc)
        link = next(r for r in offer["remedies"] if r["id"] == "open_agent_sessions")
        self.assertEqual(link["href"], f"#/p/{p.pid}/agent_sessions")
        self.assertIn("incident_opened", [r["event"]["kind"] for r in p.ledger().records()])


class AuditIncidentTest(EvalsCase):
    def test_FR_HEAL1_AC_11_a_failed_gnomon_audit_opens_an_incident_with_its_findings_as_context(self):
        row, _ = self.run_eval("security")
        self.assertEqual((row["verdict"], row.get("incident")), ("passed", None))     # passed: nothing opened
        gf.answer(self.fake, security=gf.risky_security())
        row, _ = self.run_eval("security")
        self.assertEqual(row["verdict"], "failed")
        doc = inc.get(self.factory, row["incident"])
        self.assertEqual((doc["kind"], doc["project"], doc["where"]), ("eval_failed", self.p.pid, "eval:security"))
        ctx = doc["context"]
        self.assertEqual([f["id"] for f in ctx["findings"]], [f["id"] for f in row["findings"]])
        self.assertEqual((ctx["eval"], ctx["issues"], ctx["new_findings"]), ("security", 3, 3))
        self.assertTrue(all(f["title"] and f["severity"] for f in ctx["findings"]))
        self.assertIn("open_audits", [r["id"] for r in immune.offered(self.factory, doc)["remedies"]])
        row, _ = self.run_eval("security")                                   # failing again: counted, not reopened
        self.assertEqual(row["incident"], doc["id"])
        self.assertEqual(inc.get(self.factory, doc["id"])["count"], 2)


class RoleEvalIncidentTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"GF_LANES": str(self.tmp / "lanes")})
        patcher.start()
        self.addCleanup(patcher.stop)
        isolated_routing(self, self.tmp)

    def test_FR_HEAL1_AC_11_a_role_eval_with_wrong_answers_opens_an_incident_with_the_wrong_cases(self):
        out = rv.run(self.factory, person=AINO, persona="it", role="assistant", models=["qwen3.6-35b@local",
                                                                                        "glm-5.3@go"],
                     model_for=lambda cand: FakeModel(good if cand["endpoint"] == "local" else bad))
        right = [r for r in out["runs"] if r["endpoint"] == "local"]
        wrong = [r for r in out["runs"] if r["endpoint"] == "go"]
        self.assertTrue(right and all("incident" not in r for r in right))     # every case right: nothing opened
        self.assertTrue(wrong and all(r["incident"] for r in wrong))
        doc = inc.get(self.factory, wrong[0]["incident"])
        self.assertEqual((doc["kind"], doc["project"]), ("eval_failed", None))
        self.assertTrue(doc["where"].startswith("role_eval:"))
        ctx = doc["context"]
        self.assertEqual((ctx["candidate"], ctx["role"]), ("glm-5.3@go", "assistant"))
        self.assertEqual(len(ctx["findings"]), ctx["cases"] - ctx["correct"])
        self.assertTrue(all(f["case"] and f["failed"] for f in ctx["findings"]))
        self.assertIn("models_on_evals", [r["id"] for r in immune.offered(self.factory, doc)["remedies"]])


class SoloApprovalTest(FactoryTestCase):
    def test_FR_HEAL1_AC_12_in_solo_mode_the_solo_person_approves_remedies_and_rihmasto_pull_requests(self):
        f = self.factory
        kteam.name_solo(f, AINO)
        # the solo person approves in whichever persona they look through; another name does not
        approved = immune.approve(f, remedy(f)["id"], person=AINO, persona="end_user")
        self.assertEqual((approved["state"], approved["approved"]["persona"]), ("approved", "end_user"))
        other = remedy(f, self.new().pid)
        with self.assertRaisesRegex(PermissionError, "or the solo person"):
            immune.approve(f, other["id"], person=BEA, persona="end_user")
        heal_fix._may_open(f, dict(RIHMASTO_FIX), AINO, "developer", True)       # IT, or the solo person
        with self.assertRaisesRegex(heal_fix.FixRefused, "the IT persona, or the solo person"):
            heal_fix._may_open(f, dict(RIHMASTO_FIX), BEA, "developer", True)
        with self.assertRaisesRegex(heal_fix.FixRefused, "approval"):
            heal_fix._may_open(f, dict(RIHMASTO_FIX), AINO, "it", False)        # still only on an approval
        proposal = feedback.give(f, kind="unclear", where={"view": "overview", "text": "Waits for"}, words="for what?",
                                 suggest="Waiting on", person=BEA, persona="end_user")["proposal"]
        self.assertEqual(feedback.settle(f, proposal["id"], verdict="approve", person=AINO,
                                         persona="stakeholder")["state"], "approved")
        # the cockpit signs a pull request "as needed" with the persona Rihmasto's own repository needs
        write_json(heal_fix._dir(f) / "F-0001.json", RIHMASTO_FIX)
        self.assertEqual(solo_routes.NEEDS["post_fix_pr"](f, {"fid": "F-0001"}, {}), ("it",))
        # team mode: the same person approves only as a persona that may
        kteam.set_mode(f, "team", person=AINO, persona="it")
        with self.assertRaisesRegex(heal_fix.FixRefused, "owner of this Rihmasto"):
            heal_fix._may_open(f, dict(RIHMASTO_FIX), AINO, "developer", True)
        heal_fix._may_open(f, dict(RIHMASTO_FIX), AINO, "it", True)
        with self.assertRaises(PermissionError):
            immune.approve(f, other["id"], person=AINO, persona="end_user")


class TeamApprovalTest(PeopleCase):
    def test_FR_HEAL1_AC_12_in_team_mode_approvals_follow_the_team_roles(self):
        tab = self.go_team()
        status, out = self.send("POST", "/api/people/users", {"name": BEA, "personas": ["developer"], "person": AINO,
                                                              "persona": "it"}, session=tab)
        self.assertEqual(status, 201, out)
        status, out = self.send("POST", f"/api/people/users/{out['user']['id']}/link",
                                {"kind": "invite", "person": AINO, "persona": "it"}, session=tab)
        token = out["link"]["url"].rpartition("#k=")[2]
        bea = self.send("POST", "/auth", {"bootstrap": token})[1]["token"]
        rid = remedy(self.factory)["id"]
        status, out = self.send("POST", f"/api/remedies/{rid}/approve", {"person": BEA, "persona": "it"}, session=bea)
        self.assertEqual(status, 403, out)                               # IT is not one of Bea's roles
        status, out = self.send("POST", f"/api/remedies/{rid}/approve", {"person": BEA, "persona": "developer"},
                                session=bea)
        self.assertEqual((status, out["remedy"]["approved"]["persona"]), (200, "developer"))
        with self.assertRaises(heal_fix.FixRefused):                     # Rihmasto's own repository: IT's
            heal_fix._may_open(self.factory, dict(RIHMASTO_FIX), BEA, "developer", True)


class PromptRulesTest(FactoryTestCase):
    def prompts(self, p) -> dict:
        """Each agent prompt as built now: the intake panel, the spec, Ask Rihma, goal help, a channel answer."""
        asked: dict[str, str] = {}

        def answer(prompt, role):
            asked.setdefault("ask" if "Snapshot (JSON)" in prompt else "goal", prompt)
            return "```json\n" + json.dumps({"answer": "The ledger view.", "navigate": None, "propose": [],
                                             "sources": [], "steps": []}) + "\n```"
        ask(self.factory, "Where is the ledger?", persona="developer", project_id=p.pid, model=FakeModel(answer))
        copilot.model_plan(self.factory, p, "add sign-in", FakeModel(answer))
        return {"panel": intake._perspective_prompt("business", "A loans tracker", "text", "demo", factory=p.factory),
                "spec": spec_prompt(p), "ask": asked["ask"], "goal": asked["goal"],
                "channel": channel_rihma._records_prompt(p, {"text": "Which criterion covers returns?", "refs": {}},
                                                         "analyst")}

    def test_FR_HEAL1_AC_13_an_approved_prompt_rule_changes_every_agent_prompt(self):
        p = self.new()
        before = self.prompts(p)
        self.assertTrue(all(RULE not in text for text in before.values()))
        given = feedback.give(self.factory, kind="wrong", where={"view": "agents", "text": "R-2 covers it"},
                              words="it does not say which", suggest=RULE, person="Aino", persona="developer")
        proposal = given["proposal"]
        self.assertEqual(proposal["change"], "prompt")
        self.assertEqual(prompt_rules.rules(self.factory), [])                  # proposed is not approved
        feedback.settle(self.factory, proposal["id"], verdict="approve", person="Petra", persona="product_owner")
        self.assertEqual(prompt_rules.rules(self.factory), [RULE])
        after = self.prompts(p)
        for name, text in after.items():
            self.assertIn(RULE, text, name)
            self.assertNotEqual(text, before[name], name)
        block = prompt_rules.block(self.factory)
        self.assertEqual(after["panel"], before["panel"] + block)               # the rule after, nothing else moved
        self.assertEqual(after["spec"], before["spec"] + block)


class NeedsTest(CockpitTestCase):
    def test_FR_PPL1_AC_9_every_write_route_names_the_persona_it_needs_and_solo_mode_signs_with_it(self):
        writes = {name for method, _, name in cockpit.ROUTES if method != "GET"}
        self.assertEqual(sorted(writes - set(solo_routes.NEEDS)), [])           # every write route has an entry
        self.assertEqual(sorted(set(solo_routes.NEEDS) - writes), [])           # and none of a route that is gone
        new = ("post_agent_sessions_map", "post_agent_sessions_snapshot", "put_agent_observability", "post_people_solo",
               "post_agent_persona", "post_eval_run", "post_role_evals_run", "post_eval_finding_change",
               "post_incident", "post_incident_fix", "post_fix_pr", "post_remedy_approve", "post_feedback_settle",
               "post_assume", "post_settle", "post_delegation_revoke", "post_automation", "post_automation_run")
        self.assertTrue(set(new) <= set(solo_routes.NEEDS))
        p = self.new()
        everything = {"person": AINO, "persona": "end_user", "as_needed": True}
        # agent observability: the hub's address is IT's
        status, out, _ = self.call("PUT", "/api/agent-observability", {"url": "http://127.0.0.1:9", **everything})
        self.assertEqual(status, 200, out)
        rec = factory_project(self.factory).ledger().of_kind("agentobs_settings_set")[-1]["event"]["payload"]
        self.assertEqual((rec["person"], rec["persona"]), (AINO, "it"))
        # an automation that advances a project: a persona its action allows
        draft = {"name": "Advance nightly", "trigger": {"kind": "schedule", "every": "1d"},
                 "action": {"kind": "advance"}, "scope": {"kind": "project", "projects": [p.pid]}}
        status, out, _ = self.call("POST", "/api/automations", {"automation": draft, **everything})
        self.assertEqual(status, 201, out)
        rec = factory_project(self.factory).ledger().of_kind("automation_set")[-1]["event"]["payload"]
        self.assertEqual((rec["person"], rec["persona"]), (AINO, "business_owner"))
        # a delegation someone else made: revoked by a persona that decides what it covers
        d = kdelegation.grant(p, ["approval"], person="Ola Example", persona="product_owner", until="3d")
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/delegations/{d['id']}/revoke", everything)
        self.assertEqual(status, 200, out)
        rec = p.ledger().of_kind("delegation_revoked")[-1]["event"]["payload"]
        self.assertEqual((rec["by"], rec["persona"]), (AINO, "business_owner"))
        # a write any persona makes keeps the persona sent
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/comments",
                                   {"target": {"kind": "requirement", "id": "R-1"}, "text": "a note", **everything})
        self.assertEqual((status, out["comment"]["persona"]), (201, "end_user"), out)


if __name__ == "__main__":
    unittest.main()
