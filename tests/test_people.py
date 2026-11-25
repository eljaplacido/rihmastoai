"""Simple for one, governed for many (FR-PPL1, D-0024 item 4): solo mode, agents given a persona, team mode.

- Solo: one person, named once, decides cards that need several personas without switching; each record names
  the persona the decision used. A persona named without "as needed" is never changed.
- Agents: a persona given to an agent by delegation decides within its kinds, verdicts, count and time, and
  nothing else; the records name the agent, the delegation and the person who gave it.
- Team: platform users and one-use links (no password), deactivation, an Entra-style token from the test
  provider (its keys fetched from a JWKS stub on 127.0.0.1) mapped to a persona by group, per-project roles and
  visibility, pages per persona, and the move from solo to team keeping every record.
- Ask Rihma proposes the same moves and says who may decide a card.

No real identity provider is reached: the provider is tests/access_fakes.py's, its keys served on 127.0.0.1.
"""

import contextlib
import hashlib
import http.server
import io
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from access_fakes import Provider  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import access as kaccess  # noqa: E402
from kernel import agent_personas as kagents  # noqa: E402
from kernel import cli  # noqa: E402
from kernel import team as kteam  # noqa: E402
from kernel import team_access as kteam_access  # noqa: E402
from kernel.assistant import ask, ui_map  # noqa: E402
from kernel.assistant_rules import CONTROL_PAGES  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.delegation import revoke  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.store import write_json  # noqa: E402

ISSUER = "https://login.example.org"
AUDIENCE = "rihmasto-cockpit"
IDP = Provider(ISSUER, AUDIENCE)
OPS_GROUP = "0b8e5c1a-3d55-4a51-9b1e-6f2a1c4d7e90"       # an Entra ID group's object id
AINO, BEA = "Aino Example", "Bea Example"
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def run_cli(factory, *argv: str) -> int:
    """`rihmasto <argv>` on this factory home, its output kept from the test's own."""
    from unittest import mock

    from kernel.store import Clock

    # the command line reads the test's clock, as the factory under test does: a delegation's expiry is checked
    # against the same time it was made in, whatever today's date is
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()),             mock.patch.object(Clock, "now", lambda self: factory.clock.now()):
        return cli.main(["--home", str(factory.home), *argv])


def files(root: Path) -> dict:
    """Every file under ``root`` with its sha256, but the factory's own records (they grow with each change)."""
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*"))
            if p.is_file() and "_factory" not in p.parts and "_cockpit" not in p.parts and not p.name.endswith(".lock")}


class JwksStub:
    """The provider's JWKS address, on 127.0.0.1."""

    def __init__(self, jwks: dict) -> None:
        body = json.dumps(jwks).encode()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                pass

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/keys"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class PeopleCase(CockpitTestCase):
    def send(self, method: str, path: str, body: dict | None = None, *, session: str | None = None,
             bearer: str | None = None) -> tuple[int, dict]:
        """A request as the page sends it in team mode: the session in X-Rihmasto-Session, and (behind the
        provider's proxy) the provider's token in Authorization."""
        headers = {"Origin": self.origin} if method != "GET" else {}
        if session:
            headers["X-Rihmasto-Session"] = session
            headers["Authorization"] = f"Bearer {session}"
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.origin + path, data=data, headers=headers, method=method)
        try:
            with _DIRECT.open(req, timeout=10) as res:
                return res.status, json.loads(res.read() or b"null")
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"null")

    def cards(self):
        """A project with three cards that need three personas: a change (business owner), a deploy gate (IT)
        and an incident (operations)."""
        p = self.new(title="Equipment loans")
        canon = Canon(p)
        made = {k: canon.card(k, title)["id"] for k, title in (
            ("change", "Show overdue loans first"), ("deploy_gate", "Open production for release 1"),
            ("incident", "The loans page answers 500"))}
        return p, made

    def decisions(self, p) -> dict:
        return {d["card"]: d for d in Canon(p)._load("decisions.json")}

    def go_team(self) -> str:
        """Team mode turned on in this tab by the solo person: the tab's new session, as their user."""
        self.call("POST", "/api/people/solo", {"person": AINO, "persona": "business_owner"})
        status, out, _ = self.call("POST", "/api/people/mode", {"mode": "team", "person": AINO, "persona": "it"})
        self.assertEqual(status, 200, out)
        return out["session"]


class SoloTest(PeopleCase):
    def test_FR_PPL1_AC_1_one_person_decides_cards_of_several_personas_without_switching_and_each_record_names_the_persona(self):
        p, made = self.cards()
        status, out, _ = self.call("POST", "/api/people/solo", {"person": AINO, "persona": "business_owner"})
        self.assertEqual((status, out), (200, {"mode": "solo", "name": AINO}))
        self.assertEqual(self.call("GET", "/api/meta")[1]["people"]["solo_name"], AINO)   # named once, every tab
        inbox = self.call("GET", "/api/inbox?persona=*")[1]
        mine = {c["id"]: c["decide_as"] for c in inbox["cards"] if c["project"] == p.pid}
        self.assertEqual(mine, {made["change"]: "business_owner", made["deploy_gate"]: "it",
                                made["incident"]: "operations"})
        for kind, verdict in (("change", "accept"), ("deploy_gate", "approve"), ("incident", "acknowledge")):
            status, out, _ = self.call("POST", f"/api/projects/{p.pid}/cards/{made[kind]}/decide",
                                       {"verdict": verdict, "person": AINO, "persona": "business_owner", "as_needed": True})
            self.assertEqual(status, 200, out)
        decided = self.decisions(p)
        self.assertEqual({k: (decided[made[k]]["person"], decided[made[k]]["persona"]) for k in made},
                         {"change": (AINO, "business_owner"), "deploy_gate": (AINO, "it"),
                          "incident": (AINO, "operations")})
        writes = [r["event"]["payload"] for r in p.ledger().of_kind("cockpit_write")]
        self.assertEqual([(w["person"], w["persona"]) for w in writes],
                         [(AINO, "business_owner"), (AINO, "it"), (AINO, "operations")])
        self.assertEqual(self.call("GET", f"/api/projects/{p.pid}/inbox?persona=*")[1]["cards"], [])

    def test_FR_PPL1_AC_1_a_persona_named_without_as_needed_is_never_changed(self):
        p, made = self.cards()
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/cards/{made['deploy_gate']}/decide",
                                   {"verdict": "approve", "person": AINO, "persona": "business_owner"})
        self.assertEqual(status, 403, out)                      # explicit: the kernel's own refusal, as before
        self.assertNotIn(made["deploy_gate"], self.decisions(p))


class AgentPersonaTest(PeopleCase):
    def test_FR_PPL1_AC_2_a_persona_given_to_an_agent_decides_only_what_its_delegation_covers(self):
        p, made = self.cards()
        second = Canon(p).card("incident", "The loans page is slow")["id"]
        third = Canon(p).card("incident", "Disk nearly full")["id"]
        status, out, _ = self.call("POST", f"/api/projects/{p.pid}/agent-personas",
                                   {"persona": "operations", "agent": "ops-agent", "kinds": ["incident"],
                                    "verdicts": ["acknowledge"], "max": 2, "until": "3d", "person": AINO})
        self.assertEqual(status, 201, out)
        d = out["delegation"]
        self.assertTrue(d["words"].startswith("operations: delegated to ops-agent until 2026-11-25 12:00 UTC"), d)
        self.assertIn(d["words"], [a["words"] for a in self.call("GET", "/api/agent-personas")[1]["agents"]])
        refused = {
            "another kind": (made["change"], "accept", "ops-agent"),
            "another verdict": (made["incident"], "rollback", "ops-agent"),
            "another agent": (made["incident"], "acknowledge", "build-agent"),
        }
        for why, (card, verdict, agent) in refused.items():
            with self.assertRaises(DecisionRefused, msg=why):
                kagents.decide(p, d["id"], card, verdict, agent=agent)
        out = kagents.decide(p, d["id"], made["incident"], "acknowledge", agent="ops-agent", reason="restarted")
        self.assertEqual((out["person"], out["persona"], out["agent"], out["delegation"]),
                         (AINO, "operations", "ops-agent", d["id"]))
        dec = self.decisions(p)[made["incident"]]
        self.assertEqual((dec["person"], dec["persona"], dec["delegation"]), (AINO, "operations", d["id"]))
        self.assertIn("by ops-agent under delegation", dec["reason"])
        # through the command line, as the agent's operator runs it
        code = run_cli(self.factory, "access", "agent-decide", p.pid, d["id"], second, "--verdict", "acknowledge",
                       "--as", "ops-agent", "--person", AINO, "--persona", "operations")
        self.assertEqual(code, 0)
        with self.assertRaises(DecisionRefused):               # its two decisions are made
            kagents.decide(p, d["id"], third, "acknowledge", agent="ops-agent")
        declined = [r["event"]["payload"]["why"] for r in p.ledger().of_kind("delegation_declined")]
        self.assertTrue(any("not a change card" in w or "covers incident" in w for w in declined), declined)
        revoke(p, d["id"], person=AINO, persona="operations")
        self.assertIn("revoked", kagents.listed(self.factory)[0]["words"])

    def test_FR_PPL1_AC_2_what_is_never_delegated_and_a_rihma_agent_without_a_rule_are_refused(self):
        p, _ = self.cards()
        for kinds, agent_kind, persona in ((["deploy_gate"], "bridge", "it"), (["change"], "rihma", "business_owner"),
                                           (["incident"], "bridge", "developer_x")):
            with self.assertRaises((DecisionRefused, ValueError)):
                kagents.assign(p, kinds, agent_kind=agent_kind, agent="ops-agent", until="1d", person=AINO,
                               persona=persona)
        d = kagents.assign(p, ["approval"], agent_kind="rihma", agent="analyst", until="1d", person=AINO,
                           persona="product_owner")
        self.assertEqual((d["agent"], d["rules"]), ({"kind": "rihma", "name": "analyst"}, {"approval": "plan_when_tested"}))
        self.assertTrue(d["words"].startswith("product owner: delegated to analyst until"), d["words"])


class TeamTest(PeopleCase):
    def test_FR_PPL1_AC_3_users_sign_in_with_one_use_links_and_a_deactivated_user_is_refused(self):
        p, made = self.cards()
        old = self.token
        tab = self.go_team()
        self.assertEqual(self.send("GET", "/api/projects", session=old)[0], 401)      # the solo session ends
        status, me = self.send("GET", "/api/meta", session=tab)
        self.assertEqual((status, me["access"]["note"], me["people"]["mode"]), (200, f"team: signed in as {AINO}", "team"))
        status, out = self.send("POST", "/api/people/users", {"name": BEA, "personas": ["product_owner"],
                                                              "person": AINO, "persona": "it"}, session=tab)
        self.assertEqual(status, 201, out)
        uid = out["user"]["id"]
        status, out = self.send("POST", f"/api/people/users/{uid}/link", {"kind": "invite", "person": AINO,
                                                                          "persona": "it"}, session=tab)
        self.assertEqual(status, 201, out)
        token = out["link"]["url"].rpartition("#k=")[2]
        self.assertNotIn(token, kteam.path(self.factory).read_text(encoding="utf-8"))    # only its sha256 is kept
        status, out = self.send("POST", "/auth", {"bootstrap": token})
        self.assertEqual(status, 200, out)
        bea = out["token"]
        self.assertEqual(self.send("POST", "/auth", {"bootstrap": token})[0], 401)          # once
        status, out = self.send("POST", f"/api/projects/{p.pid}/cards/{made['change']}/decide",
                                {"verdict": "accept", "person": BEA, "persona": "product_owner"}, session=bea)
        self.assertEqual(status, 200, out)
        dec = self.decisions(p)[made["change"]]
        self.assertEqual((dec["person"], dec["persona"], dec["identity"]), (BEA, "product_owner", f"rihmasto:{uid}"))
        status, out = self.send("POST", f"/api/projects/{p.pid}/cards/{made['deploy_gate']}/decide",
                                {"verdict": "approve", "person": BEA, "persona": "it"}, session=bea)
        self.assertEqual(status, 403, out)                                                    # not granted
        status, out = self.send("POST", f"/api/people/users/{uid}/link", {"person": BEA, "persona": "it"}, session=bea)
        self.assertEqual(status, 403, out)                                                    # only IT changes people
        self.send("PUT", f"/api/people/users/{uid}", {"active": False, "person": AINO, "persona": "it"}, session=tab)
        status, out = self.send("GET", "/api/projects", session=bea)
        self.assertEqual(status, 401, out)
        self.assertIn("deactivated", out["error"])
        kinds = [r["event"]["payload"]["action"] for r in factory_project(self.factory).ledger().of_kind(kteam.RECORD)]
        self.assertEqual(kinds, ["solo_named", "mode", "user_added", "link_made", "signed_in", "user_deactivated"])

    def test_FR_PPL1_AC_4_an_entra_style_token_signs_in_and_its_group_maps_to_a_persona(self):
        p, made = self.cards()
        tab = self.go_team()
        stub = JwksStub(IDP.jwks())
        self.addCleanup(stub.close)
        idp = {"preset": "oauth2-proxy", "issuer": ISSUER, "origin": "https://rihmasto.example.org",
               "audience": AUDIENCE, "groups_claim": "groups", "subject_claim": "oid"}
        status, out = self.send("PUT", "/api/people/idp", {"idp": idp, "jwks_url": stub.url, "person": AINO,
                                                           "persona": "it"}, session=tab)
        self.assertEqual(status, 200, out)
        status, out = self.send("POST", "/api/people/keys", {"fetch": True, "person": AINO, "persona": "it"}, session=tab)
        self.assertEqual((status, out["keys"]), (200, ["test-key-1"]), out)
        status, out = self.send("POST", "/api/people/groups", {"group": OPS_GROUP, "to": "operations", "person": AINO,
                                                               "persona": "it"}, session=tab)
        self.assertEqual(status, 200, out)
        jwt = IDP.token("x", oid="7d1c0f3a", email="carl@example.org", groups=[OPS_GROUP, "x,other"])
        status, out = self.send("POST", "/api/people/test-token", {"token": jwt}, session=tab)
        self.assertEqual((out["ok"], out["identity"], out["grants"]),
                         (True, f"{ISSUER}#7d1c0f3a", [{"persona": "operations", "scope": "*"}]), out)
        status, out = self.send("POST", "/auth", {}, bearer=jwt)
        self.assertEqual(status, 200, out)
        carl = out["token"]
        status, out = self._as_proxy("POST", f"/api/projects/{p.pid}/cards/{made['incident']}/decide",
                                     {"verdict": "acknowledge", "person": "carl@example.org", "persona": "operations"},
                                     jwt, carl)
        self.assertEqual(status, 200, out)
        self.assertEqual(self.decisions(p)[made["incident"]]["identity"], f"{ISSUER}#7d1c0f3a")
        status, out = self._as_proxy("POST", f"/api/projects/{p.pid}/cards/{made['change']}/decide",
                                     {"verdict": "accept", "person": "carl@example.org", "persona": "business_owner"},
                                     jwt, carl)
        self.assertEqual(status, 403, out)
        other = Provider(ISSUER, AUDIENCE, seed=2).token("x", oid="7d1c0f3a", groups=[OPS_GROUP])
        self.assertFalse(kteam_access.test_token(self.factory, other)["ok"])                 # another key: refused

    def _as_proxy(self, method: str, path: str, body: dict, jwt: str, session: str) -> tuple[int, dict]:
        headers = {"Origin": self.origin, "Content-Type": "application/json", "Authorization": f"Bearer {jwt}",
                   "X-Rihmasto-Session": session}
        req = urllib.request.Request(self.origin + path, data=json.dumps(body).encode(), headers=headers, method=method)
        try:
            with _DIRECT.open(req, timeout=10) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def test_FR_PPL1_AC_5_roles_scope_what_a_member_sees_and_decides_and_pages_follow_the_persona(self):
        p, made = self.cards()
        other = self.new(title="Room bookings")
        tab = self.go_team()
        who = {"person": AINO, "persona": "it"}
        uid = self.send("POST", "/api/people/users", {"name": BEA, "personas": ["developer"], "scope": [p.pid], **who},
                        session=tab)[1]["user"]["id"]
        status, out = self.send("POST", "/api/people/roles", {"project": p.pid, "user": uid,
                                                              "personas": ["product_owner"], **who}, session=tab)
        self.assertEqual(status, 200, out)
        self.send("PUT", "/api/people/views", {"to": "product_owner", "hidden": ["insights_all", "automations_all"],
                                               **who}, session=tab)
        link = self.send("POST", f"/api/people/users/{uid}/link", who, session=tab)[1]["link"]["url"]
        bea = self.send("POST", "/auth", {"bootstrap": link.rpartition("#k=")[2]})[1]["token"]
        self.assertEqual([x["id"] for x in self.send("GET", "/api/projects", session=bea)[1]], [p.pid])
        self.assertEqual(self.send("GET", f"/api/projects/{other.pid}", session=bea)[0], 404)
        self.assertEqual(self.send("POST", f"/api/projects/{other.pid}/changes",
                                   {"text": "x", "person": BEA, "persona": "product_owner"}, session=bea)[0], 404)
        meta = self.send("GET", "/api/meta", session=bea)[1]["people"]
        self.assertEqual((meta["holds"], meta["hidden_pages"]), (["product_owner"], ["automations_all", "insights_all"]))
        inbox = self.send("GET", "/api/inbox?persona=*", session=bea)[1]
        self.assertEqual([(c["id"], c["decide_as"]) for c in inbox["cards"]], [(made["change"], "product_owner")])
        status, out = self.send("POST", f"/api/projects/{p.pid}/cards/{made['change']}/decide",
                                {"verdict": "defer", "person": BEA, "persona": "developer", "as_needed": True}, session=bea)
        self.assertEqual((status, self.decisions(p)[made["change"]]["persona"]), (200, "product_owner"), out)
        said = kteam_access.who_decides(self.factory, p.pid, made["incident"])
        self.assertIn(f"{AINO} as operations", said["text"])
        self.assertNotIn(BEA, said["text"])

    def test_FR_PPL1_AC_6_moving_from_solo_to_team_keeps_every_record_and_the_command_line_signs_as_before(self):
        p, made = self.cards()
        self.call("POST", "/api/people/solo", {"person": AINO, "persona": "business_owner"})
        self.call("POST", f"/api/projects/{p.pid}/cards/{made['change']}/decide",
                  {"verdict": "accept", "person": AINO, "persona": "business_owner", "as_needed": True})
        before, head = files(self.factory.home), p.ledger().head()
        out = kteam.set_mode(self.factory, "team", person=AINO, persona="it")
        self.assertEqual(files(self.factory.home), before)                          # nothing rewritten
        self.assertEqual(p.ledger().head(), head)
        self.assertTrue(p.ledger().verify().intact and factory_project(self.factory).ledger().verify().intact)
        user = out["user"]
        self.assertEqual((user["name"], user["owner"], len(user["personas"]), user["scope"]), (AINO, True, 9, "*"))
        self.assertTrue(any(i.startswith("local:") for i in user["identities"]))
        access = kaccess.load(self.factory)
        self.assertEqual((access.mode, access.source), ("enforced", "team"))
        self.assertEqual(self.decisions(p)[made["change"]]["person"], AINO)             # the record is as it was
        # the command line signs as this machine's user, which is the solo person's user now
        self.assertEqual(run_cli(self.factory, "access", "user-add", BEA, "--personas", "developer", "--person", AINO), 0)
        self.assertEqual(run_cli(self.factory, "access", "user-add", "Cid Example", "--personas", "developer",
                                 "--person", BEA), 2)                                      # not the local user
        with self.assertRaises(kaccess.AccessRefused):                                   # unsigned: refused
            kteam.set_mode(self.factory, "solo", person=AINO, persona="it")
        self.assertEqual(run_cli(self.factory, "access", "solo", "--person", AINO), 0)
        self.assertEqual(kaccess.load(self.factory).mode, "single_operator")

    def test_FR_PPL1_AC_6_a_broken_team_file_refuses_every_decision_and_it_s_access_file_governs_over_it(self):
        p, made = self.cards()
        kteam.set_mode(self.factory, "team", person=AINO, persona="it")
        kteam.path(self.factory).write_text("{not json", encoding="utf-8")
        with self.assertRaises(kaccess.AccessRefused):
            kaccess.require(p, AINO, "business_owner")
        kteam.path(self.factory).write_text(json.dumps(kteam.blank() | {"mode": "team"}), encoding="utf-8")
        path = kaccess.access_path(self.factory)
        path.parent.mkdir(parents=True)
        write_json(path, {"schema": kaccess.SCHEMA, "mode": "single_operator", "changed_by": "Ilkka Example"})
        self.assertEqual((kaccess.load(self.factory).mode, kteam.mode(self.factory)), ("single_operator", "it"))
        with self.assertRaises(DecisionRefused):
            kteam.add_user(self.factory, BEA, personas=["developer"], person=AINO, persona="it")


class ChatTest(PeopleCase):
    def test_FR_PPL1_AC_8_ask_rihma_proposes_the_moves_and_says_who_may_decide_a_card(self):
        p, made = self.cards()
        kteam.name_solo(self.factory, AINO)
        asked = {
            "Switch to team mode": ("people_mode", {"mode": "team"}),
            "Add a user Bea Example as developer": ("people_add_user", {"name": BEA, "personas": ["developer"]}),
            f"Map group {OPS_GROUP} to operations": ("people_map_group", {"group": OPS_GROUP, "to": "operations"}),
        }
        for question, (action, args) in asked.items():
            out = ask(self.factory, question, persona="business_owner")
            self.assertEqual([(x["action"], x["args"]) for x in out["propose"]], [(action, args)], question)
            self.assertEqual(out["navigate"], {"route": "#/settings", "control": "people_access"})
        out = ask(self.factory, "Delegate operations to the ops agent", persona="operations", project_id=p.pid)
        self.assertEqual(out["propose"][0]["args"]["agent"], "ops-agent")
        self.assertEqual(out["propose"][0]["args"]["kinds"], ["incident"])
        out = ask(self.factory, f"Who may decide {made['deploy_gate']}?", persona="business_owner", project_id=p.pid)
        self.assertIn("is decided as it.", out["answer"])
        self.assertIn(f"In solo mode that is you, {AINO}", out["answer"])
        status, out, _ = self.call("POST", "/api/assistant", {"question": "Switch to team mode", "persona": "it",
                                                              "person": AINO})
        self.assertEqual((status, out["propose"][0]["action"]), (200, "people_mode"))
        self.assertEqual(kteam.mode(self.factory), "solo")                        # a proposal writes nothing
        controls = {c["id"]: c for c in ui_map()["controls"]}
        for cid in ("people_access", "people_mode", "people_add_user", "people_invite", "people_map_group",
                    "people_test_token", "people_delegate_agent", "viewing_as"):
            self.assertIn(cid, CONTROL_PAGES)
            self.assertTrue(controls[cid]["label"] and controls[cid]["label"] not in ("Settings", "People"))
        out = ask(self.factory, "Where do I invite a user?", persona="it")
        self.assertEqual(out["navigate"], {"route": "#/settings", "control": "people_invite"})
