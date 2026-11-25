"""Access control, phase A (FR-M8, D-0016): who may decide as which persona, on which project.

Without an access file the factory is a single operator's, exactly as before, and says so. With one in
mode ``enforced`` a decision is signed by a verified identity: the cockpit takes it only from the
identity provider's signed token that IT's proxy forwards (verified with the provider's public keys; no
shared secret), the command line and the MCP server take it from the operating system's user, and every
write that records a person's decision or answer needs the persona granted on its project.
Impersonation fails: no token, a token another key signed, a persona not granted, a project outside the
scope, a person field that differs from the identity, a tampered or invalid access file, an MCP client
trying to decide, a CLI user not in the file.
"""

import contextlib
import hashlib
import io
import json
import os
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import test_brief_ln as ln  # noqa: E402  (its FactoryApiTest builds the world every write route acts on)
import test_cockpit  # noqa: E402
from access_fakes import Provider, segment  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402
from test_cli_capability import leaves  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from cockpit import server as cockpit  # noqa: E402
from kernel import access as kaccess  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.cli import build_parser, main  # noqa: E402
from kernel.learn import FACTORY_PID, factory_project  # noqa: E402
from kernel.people import Identity  # noqa: E402
from kernel.source_guard import ROOTS_ENV  # noqa: E402
from kernel.store import write_json  # noqa: E402
from mcp.server import RihmaMCP, tool_list  # noqa: E402

ISSUER = "https://login.example.org"
PUBLIC = "https://rihmasto.example.org"
AUDIENCE = "rihmasto-cockpit"          # the client id the organisation's provider issues ID tokens for
IDP = Provider(ISSUER, AUDIENCE)       # the provider's RS256 key: its JWKS goes in the access folder
OTHER_IDP = Provider(ISSUER, AUDIENCE, seed=2)   # someone else's key, with the same key id
AINO, IDA, MALLORY, DEV, ADMIN = (f"{ISSUER}#{s}" for s in ("aino-sub", "ida-sub", "mallory-sub", "dev-sub",
                                                              "admin-sub"))
NAMES = {AINO: "Aino Example", IDA: "Ida Example", MALLORY: "Mallory Example", DEV: "Dev Example",
         ADMIN: "Ilkka Example", "local:aino": "Aino Example", "local:mallory": "Mallory Example",
         "local:it-admin": "Ilkka Example"}
ELSEWHERE = "elsewhere-project"         # a project id no test creates: a scope that covers nothing here
FUTURE = "2099-12-31"
CALL_TIMEOUT = 30                       # a hosted runner with two cores, busy, is slower than a desk


def access_doc(project_scope=None, **changes) -> dict:
    """An enforced access file: Aino owns every project, Ida holds every persona everywhere, Mallory is a
    stakeholder on a project that does not exist, Dev a developer on one project, the ops group operates."""
    bindings = [
        {"subject": AINO, "persona": "business_owner", "scope": "*"},
        {"subject": AINO, "persona": "product_owner", "scope": "*"},
        {"subject": "local:aino", "persona": "product_owner", "scope": "*"},
        {"subject": "local:aino", "persona": "developer", "scope": "*"},
        {"subject": "local:mallory", "persona": "stakeholder", "scope": [ELSEWHERE]},
        {"subject": MALLORY, "persona": "stakeholder", "scope": [ELSEWHERE]},
        {"subject": ADMIN, "persona": "it", "scope": "*"},
        {"subject": "local:it-admin", "persona": "it", "scope": "*"},
        {"group": "rihmasto-ops", "persona": "operations", "scope": "*", "note": "the on-call team"},
        *({"subject": IDA, "persona": p, "scope": "*"} for p in kaccess.PERSONAS),
    ]
    if project_scope:
        bindings.append({"subject": DEV, "persona": "developer", "scope": [project_scope]})
    doc = {"schema": kaccess.SCHEMA, "mode": "enforced", "changed_by": "local:it-admin",
           "proxy": {"preset": "oauth2-proxy", "issuer": ISSUER, "origin": PUBLIC, "audience": AUDIENCE,
                     "groups_claim": "groups"},
           "people": [{"identity": k, "name": v} for k, v in NAMES.items()],
           "bindings": bindings,
           # where untrusted code runs: a container (the cockpit's jobs start only with a runner named)
           "isolation": {"runner": "container", "image": "python:3.12-slim",
                         "cells": ["docker", "run", "--rm", "-v", "{cwd}:{cwd}", "-w", "{cwd}", "gnomon", "gnomon"]}}
    doc.update(changes)
    return doc


def write_access(factory, doc=None, jwks=None) -> Path:
    """The access file and the provider's key file beside it, as IT writes them."""
    path = kaccess.access_path(factory)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, doc or access_doc())
    write_json(path.parent / "jwks.json", jwks or IDP.jwks())
    return path


def tree(root: Path) -> dict:
    return ln.tree(root)


class AccessFileTest(FactoryTestCase):
    """FR-M8-AC-1: the two modes, the strict file, failing closed, and every change on record."""

    def write(self, doc) -> None:
        path = kaccess.access_path(self.factory)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(doc, bytes):
            path.write_bytes(doc)
        else:
            write_json(path, doc)

    def test_FR_M8_AC_1_without_a_file_the_factory_is_a_single_operator_and_says_so(self):
        access = kaccess.load(self.factory, record=True)
        self.assertFalse(access.enforced)
        self.assertEqual(kaccess.describe(access), "single operator: personas are self-declared")
        self.assertEqual(kaccess.view(access, None), {"mode": "single_operator",
                                                       "note": "single operator: personas are self-declared"})
        p = self.new()
        cid = Canon(p).card("validation", "Accept the demo?")["id"]
        d = Canon(p).decide(cid, "accept", person="Anyone", persona="business_owner")   # self-declared, as before
        self.assertNotIn("identity", d)
        self.assertNotIn("identity", p.ledger().of_kind("decision")[-1]["event"]["payload"])
        self.assertEqual(factory_project(self.factory, create=False), None)            # nothing recorded
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(err):
            self.assertEqual(main(["--home", str(self.factory.home), "status"]), 0)
        self.assertEqual(json.loads(out.getvalue())["projects"][0]["id"], p.pid)
        self.assertIn("single operator: personas are self-declared", err.getvalue())

    def test_FR_M8_AC_1_the_file_is_checked_whole_and_strictly(self):
        good = access_doc()
        kaccess.parse(json.dumps(good).encode())                                       # holds every rule
        proxy = dict(good["proxy"])
        broken = {
            "$.extra": dict(good, extra=1),
            "$.schema": dict(good, schema="rihmasto.access/2"),
            "$.mode": dict(good, mode="open"),
            "$.proxy": {k: v for k, v in good.items() if k != "proxy"},
            "$.proxy.user_header": dict(good, proxy=dict(proxy, user_header="Authorization")),
            "$.proxy.issuer": dict(good, proxy=dict(proxy, issuer="http://login.example.org")),
            "$.proxy.origin": dict(good, proxy=dict(proxy, origin="https://rihmasto.example.org/cockpit")),
            "$.proxy.secret_env": dict(good, proxy=dict(proxy, secret_env="lower-case")),
            "$.people[0].name": dict(good, people=[{"identity": AINO, "name": "factory"}]),
            "$.people[0].identity": dict(good, people=[{"identity": "aino", "name": "Aino"}]),
            "$.bindings[0]": dict(good, bindings=[{"subject": AINO, "group": "g", "persona": "it", "scope": "*"}]),
            "$.bindings[0].persona": dict(good, bindings=[{"subject": AINO, "persona": "root", "scope": "*"}]),
            "$.bindings[0].scope": dict(good, bindings=[{"subject": AINO, "persona": "it", "scope": []}]),
            "$.bindings[0].subject": dict(good, bindings=[{"subject": f"{ISSUER}#nobody", "persona": "it",
                                                           "scope": "*"}]),
            "$.changed_by": dict(good, changed_by=AINO),                       # Aino is not IT on every project
        }
        for where, doc in broken.items():
            with self.assertRaises(kaccess.AccessFileError, msg=where) as ctx:
                kaccess.parse(json.dumps(doc).encode())
            self.assertTrue(str(ctx.exception).startswith(where), (where, str(ctx.exception)))
        dup = dict(good, proxy=dict(proxy, email_header="x-forwarded-user"))
        self.assertRaises(kaccess.AccessFileError, kaccess.parse, json.dumps(dup).encode())
        for raw in (b"\xff\xfe", b"{not json", b"[" * 100000, b"[]"):
            self.assertRaises(kaccess.AccessFileError, kaccess.parse, raw)
        single = kaccess.parse(json.dumps({"schema": kaccess.SCHEMA, "mode": "single_operator",
                                           "changed_by": "Ilkka Example"}).encode())
        self.assertFalse(single.enforced)

    def test_FR_M8_AC_1_an_invalid_or_unreadable_file_refuses_every_decision(self):
        p = self.new()
        cid = Canon(p).card("validation", "Accept the demo?")["id"]
        admin = Identity("local:it-admin", "Ilkka Example")
        for doc in (b"{ not json", access_doc(mode="enforced", extra=True),
                    {"schema": kaccess.SCHEMA, "mode": "single_operator", "people": "tampered"}):
            self.write(doc)
            access = kaccess.load(self.factory, record=True)
            self.assertTrue(access.enforced)                                    # fails closed, whatever it says
            self.assertIn("the access file is not valid", access.error)
            with kaccess.signing(admin), self.assertRaises(kaccess.AccessBroken) as ctx:
                Canon(p).decide(cid, "accept", person="Ilkka Example", persona="business_owner")
            self.assertIn("every decision is refused until IT fixes it", str(ctx.exception))
            self.assertIn("not valid", kaccess.describe(access))
        self.assertEqual(Canon(p).get_card(cid)["state"], "open")
        self.assertEqual(Canon(p).decisions(), [])
        kaccess.access_path(self.factory).unlink()
        kaccess.access_path(self.factory).mkdir()                                 # a folder cannot be read as one
        self.assertIn("cannot be read", kaccess.load(self.factory).error)

    def test_FR_M8_AC_1_each_change_is_recorded_with_its_sha256_and_who_changed_it(self):
        self.write(access_doc())
        first = kaccess.load(self.factory, record=True, by="a test")
        kaccess.load(self.factory, record=True)                                   # unchanged: recorded once
        ledger = factory_project(self.factory).ledger()
        changes = [r["event"]["payload"] for r in ledger.of_kind("access_changed")]
        self.assertEqual(len(changes), 1)
        raw = kaccess.access_path(self.factory).read_bytes()
        self.assertEqual(changes[0]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual((changes[0]["previous"], changes[0]["mode"], changes[0]["valid"], changes[0]["claimed_by"],
                          changes[0]["detected_by"]), (None, "enforced", True, "local:it-admin", "a test"))
        # a tampered file (Mallory made an owner) is a change: on record before anything is decided under it
        tampered = access_doc()
        tampered["bindings"].append({"subject": MALLORY, "persona": "business_owner", "scope": "*"})
        self.write(tampered)
        second = kaccess.load(self.factory, record=True)
        changes = [r["event"]["payload"] for r in ledger.of_kind("access_changed")]
        self.assertEqual([c["sha256"] for c in changes], [first.sha256, second.sha256])
        self.assertEqual(changes[1]["previous"], first.sha256)
        # removed once access was enforced: closed, and the removal is on record
        kaccess.access_path(self.factory).unlink()
        gone = kaccess.load(self.factory, record=True)
        self.assertTrue(gone.enforced)
        self.assertIn("removed after access was enforced", gone.error)
        self.assertEqual(ledger.of_kind("access_changed")[-1]["event"]["payload"]["sha256"], None)
        # back to a single operator only by IT's explicit file, which is on record too
        self.write({"schema": kaccess.SCHEMA, "mode": "single_operator", "changed_by": "Ilkka Example"})
        self.assertFalse(kaccess.load(self.factory, record=True).enforced)
        self.assertEqual(ledger.of_kind("access_changed")[-1]["event"]["payload"]["mode"], "single_operator")
        self.assertTrue(ledger.verify().intact)

    def test_FR_M8_AC_1_the_kernel_takes_a_decision_only_from_the_identity_granted_on_the_project(self):
        p = self.new()
        canon = Canon(p)
        cid = canon.card("validation", "Accept the demo?")["id"]
        self.write(access_doc())
        with self.assertRaises(kaccess.AccessRefused):                            # no verified identity at all
            canon.decide(cid, "accept", person="Aino Example", persona="business_owner")
        mallory = Identity(MALLORY, "Mallory Example")
        with kaccess.signing(mallory), self.assertRaises(kaccess.AccessRefused):
            canon.decide(cid, "accept", person="Mallory Example", persona="business_owner")
        aino = Identity(AINO, "Aino Example")
        with kaccess.signing(aino), self.assertRaises(kaccess.AccessRefused):     # a name not her own
            canon.decide(cid, "accept", person="Ida Example", persona="business_owner")
        self.assertIsInstance(kaccess.AccessRefused("x"), DecisionRefused)
        with kaccess.signing(aino):
            d = canon.decide(cid, "accept", person="Aino Example", persona="business_owner")
        self.assertEqual((d["person"], d["identity"]), ("Aino Example", AINO))
        event = p.ledger().of_kind("decision")[-1]["event"]["payload"]
        self.assertEqual((event["person"], event["identity"]), ("Aino Example", AINO))
        self.assertEqual(kaccess.FACTORY_SCOPE, FACTORY_PID)


class EnforcedCockpitCase(CockpitTestCase):
    """The real cockpit on loopback, behind a stand-in for IT's proxy (oauth2-proxy passing the ID token):
    each request carries the provider's signed token in Authorization, and the session in its own header."""

    def setUp(self):
        super().setUp()
        self.sessions = {}
        self.tokens = {}

    def enforce(self, doc=None, jwks=None) -> None:
        write_access(self.factory, doc, jwks)
        kaccess.load(self.factory, record=True)

    def id_token(self, who, *, groups=None, email=None, idp=IDP, **claims) -> str:
        """The provider's ID token for ``who`` (signed once per test and kept, as a proxy keeps its session)."""
        key = (who, json.dumps(groups), email, id(idp), json.dumps(claims, sort_keys=True))
        if key not in self.tokens:
            extra = {"groups": groups} if groups is not None else {}
            self.tokens[key] = idp.token(who.rpartition("#")[2], **extra, **({"email": email} if email else {}),
                                         **claims)
        return self.tokens[key]

    def headers(self, who, *, id_token=None, groups=None, email=None) -> dict:
        if id_token is None and who:
            id_token = self.id_token(who, groups=groups, email=email)
        return {"Authorization": f"Bearer {id_token}"} if id_token else {}

    def pcall(self, method, path, body=None, *, who=AINO, token=None, origin=PUBLIC, **proxy):
        headers = self.headers(who, **proxy)
        token = token if token is not None else self.sessions.get(who)
        if token:
            headers[kaccess.SESSION_HEADER] = token
        if origin and method != "GET":
            headers["Origin"] = origin
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.origin + path, data=data, headers=headers, method=method)
        try:
            with test_cockpit._DIRECT.open(req, timeout=CALL_TIMEOUT) as res:
                payload, status = res.read(), res.status
        except urllib.error.HTTPError as exc:
            with exc:
                payload, status = exc.read(), exc.code
        except TimeoutError:     # say which route did not answer: the table walks a hundred and more of them
            raise AssertionError(f"{method} {path} did not answer in {CALL_TIMEOUT}s") from None
        return status, (json.loads(payload) if payload else None)

    def sign_in(self, who, **proxy) -> str:
        status, out = self.pcall("POST", "/auth", {}, who=who, token="", **proxy)
        self.assertEqual(status, 200, out)
        self.sessions[who] = out["token"]
        return out["token"]


class CockpitIdentityTest(EnforcedCockpitCase):
    """FR-M8-AC-2: the cockpit's identity comes only from the provider's signed token, bound to its session."""

    def test_FR_M8_AC_2_a_request_without_the_providers_signed_token_is_refused(self):
        p = self.new()
        cid = Canon(p).card("validation", "Accept the demo?")["id"]
        self.enforce()
        before = self.snapshot(p)
        forged = {"no token": "", "another key": OTHER_IDP.token("aino-sub"),
                  "not signed": f"{segment({'alg': 'none', 'typ': 'JWT'})}.{segment(IDP.claims('aino-sub'))}.",
                  "another audience": IDP.token("aino-sub", aud="another-app"),
                  "expired": IDP.token("aino-sub", ttl=-3600)}
        for what, id_token in forged.items():
            status, out = self.pcall("POST", "/auth", {}, who=AINO, token="", id_token=id_token)
            self.assertEqual((status, out["access"]), (401, "enforced"), (what, out))
            self.assertIn("did not come through the organisation's sign-in proxy with a valid token", out["error"])
        token = self.sign_in(AINO)
        decide = {"verdict": "accept", "person": "Aino Example", "persona": "business_owner", "reason": "ok"}
        url = f"/api/projects/{p.pid}/cards/{cid}/decide"
        self.assertEqual(self.pcall("POST", url, decide, token=token, id_token=forged["another key"])[0], 401)
        self.assertEqual(self.pcall("POST", url, decide, token=token, id_token="")[0], 401)
        self.assertEqual(self.pcall("GET", "/api/projects", token=token, id_token=forged["expired"])[0], 401)
        # straight to 127.0.0.1 with a session from the printed link and no proxy at all: refused
        self.assertEqual(self.call("GET", "/api/projects")[0], 401)
        self.assertEqual(self.call("POST", url, decide)[0], 401)
        self.assertEqual(self.call("POST", "/auth", {"bootstrap": self.server.issue_link()}, token=None)[0], 401)
        self.assertEqual(self.snapshot(p), before)
        # without the provider's key file nobody signs in (403), and the refusal says what IT puts there
        keys = kaccess.access_path(self.factory).with_name("jwks.json")
        keys.unlink()
        status, out = self.pcall("GET", "/api/projects", token=token)
        self.assertEqual(status, 403)
        self.assertIn("the key file jwks.json is not in the access folder", out["error"])
        write_json(keys, IDP.jwks())                      # IT puts it back: the same session works again
        self.assertEqual(self.pcall("GET", "/api/projects", token=token)[0], 200)

    def test_FR_M8_AC_2_a_session_answers_only_the_identity_it_was_opened_for(self):
        self.enforce()
        aino = self.sign_in(AINO)
        self.assertEqual(self.pcall("GET", "/api/projects", who=AINO, token=aino)[0], 200)
        self.assertEqual(self.pcall("GET", "/api/projects", who=MALLORY, token=aino)[0], 401)
        self.assertEqual(self.pcall("GET", "/api/projects", who=None, token=aino)[0], 401)
        # someone the proxy lets through but the access file grants nothing is refused at sign-in
        status, out = self.pcall("POST", "/auth", {}, who=f"{ISSUER}#stranger", token="")
        self.assertEqual(status, 401)
        self.assertIn(f"{ISSUER}#stranger is granted no persona", out["error"])

    def test_FR_M8_AC_2_the_person_is_the_verified_name_and_the_persona_must_be_granted_there(self):
        a, b = self.new(title="Equipment loans"), self.new(title="Room bookings")
        ca = Canon(a).card("change", "Show overdue loans first")["id"]
        cb = Canon(b).card("change", "Show free rooms first")["id"]
        self.enforce(access_doc(project_scope=a.pid))
        self.sign_in(AINO)
        self.sign_in(DEV)
        before = self.snapshot(a), self.snapshot(b)
        decide = {"verdict": "accept", "reason": "worth it"}
        url_a, url_b = (f"/api/projects/{a.pid}/cards/{ca}/decide", f"/api/projects/{b.pid}/cards/{cb}/decide")
        # a person field that is not the signed-in identity's name
        status, out = self.pcall("POST", url_a, dict(decide, person="Ida Example", persona="product_owner"))
        self.assertEqual(status, 403)
        self.assertIn("the person is the signed-in identity, Aino Example", out["error"])
        # a persona the identity does not hold, and a project outside the scope it holds one on
        self.assertEqual(self.pcall("POST", url_a, dict(decide, persona="compliance"))[0], 403)
        p = {"text": "a remark", "target": {"kind": "requirement", "id": "R-1"}, "persona": "developer"}
        self.assertEqual(self.pcall("POST", f"/api/projects/{b.pid}/comments", p, who=DEV)[0], 403)
        self.assertEqual(self.pcall("POST", url_b, dict(decide, persona="product_owner"), who=DEV)[0], 403)
        self.assertEqual((self.snapshot(a), self.snapshot(b)), before)
        status, out = self.pcall("POST", f"/api/projects/{a.pid}/comments", p, who=DEV)
        self.assertEqual(status, 201, out)
        self.assertEqual((out["comment"]["person"], out["comment"]["persona"]), ("Dev Example", "developer"))
        # granted: the decision records the verified person and, beside the name, the identity
        status, out = self.pcall("POST", url_a, dict(decide, persona="product_owner"))   # no person field: hers
        self.assertEqual(status, 200, out)
        d = Canon(a).decisions()[-1]
        self.assertEqual((d["person"], d["persona"], d["identity"]), ("Aino Example", "product_owner", AINO))
        events = [r["event"]["payload"] for r in a.ledger().records() if r["event"]["kind"] in ("decision",
                                                                                                  "cockpit_write")]
        self.assertEqual({(e["person"], e.get("identity")) for e in events[-2:]}, {("Aino Example", AINO)})

    def test_FR_M8_AC_2_groups_grant_personas_and_the_page_shows_the_verified_person(self):
        p = self.new()
        self.enforce()
        ops = f"{ISSUER}#ops-sub"
        groups = ["staff", "rihmasto-ops"]                 # the token's groups claim, a list
        token = self.sign_in(ops, groups=groups, email="olli@example.org")
        status, meta = self.pcall("GET", "/api/meta", who=ops, token=token, groups=groups, email="olli@example.org")
        self.assertEqual(status, 200, meta)
        self.assertEqual((meta["access"]["mode"], meta["access"]["name"], meta["access"]["identity"]),
                         ("enforced", "olli@example.org", ops))
        self.assertEqual(meta["access"]["grants"], [{"persona": "operations", "scope": "*"}])
        self.assertEqual(meta["access"]["note"], "enforced: signed in as olli@example.org")
        body = {"reason": "audit week", "persona": "operations"}
        status, out = self.pcall("POST", f"/api/projects/{p.pid}/pause", body, who=ops, token=token,
                                 groups=groups, email="olli@example.org")
        self.assertEqual(status, 200, out)
        self.assertEqual(p.meta["pause"]["requested_by"], "olli@example.org")
        # a token without the groups claim: the same person holds nothing
        self.assertEqual(self.pcall("GET", "/api/meta", who=ops, token=token, email="olli@example.org")[0], 401)
        # the page: the header names the mode, the name field is read-only, the persona list is filtered
        js = self.page_js()
        for needle in ("drawAccess", "offeredPersonas", "input.readOnly = true", '"same-origin"'):
            self.assertIn(needle, js)
        index = self.call("GET", "/", token=None, raw=True)[1].decode("utf-8")
        self.assertIn('id="access-note"', index)
        # Host and Origin: the proxy's public origin is accepted beside the server's own, nothing else
        status, _ = self.pcall("POST", f"/api/projects/{p.pid}/resume", {"persona": "operations"}, who=ops,
                               token=token, groups=["rihmasto-ops"], origin="https://evil.example")
        self.assertEqual(status, 403)

    def test_FR_M8_AC_2_a_tampered_or_invalid_file_closes_the_cockpit(self):
        p = self.new()
        cid = Canon(p).card("validation", "Accept the demo?")["id"]
        self.enforce()
        token = self.sign_in(AINO)
        before = self.snapshot(p)
        path = kaccess.access_path(self.factory)
        tampered = access_doc()
        tampered["bindings"].append({"subject": MALLORY, "persona": "business_owner", "scope": "*"})
        tampered["changed_by"] = MALLORY                                       # Mallory is not IT
        for content in (json.dumps(tampered), "{ truncated"):
            path.write_text(content, encoding="utf-8")
            body = {"verdict": "accept", "person": "Aino Example", "persona": "business_owner"}
            status, out = self.pcall("POST", f"/api/projects/{p.pid}/cards/{cid}/decide", body, token=token)
            self.assertEqual(status, 403, out)
            self.assertIn("the access file is not valid", out["error"])
            self.assertEqual(self.pcall("GET", "/api/projects", token=token)[0], 403)
        self.assertEqual(self.snapshot(p)[:2], before[:2])                      # nothing decided
        recorded = factory_project(self.factory).ledger().of_kind("access_changed")
        self.assertEqual([r["event"]["payload"]["valid"] for r in recorded], [True, False, False])


class EveryWriteRouteTest(EnforcedCockpitCase):
    """FR-M8-AC-3: every cockpit write route that takes a person or persona, in enforced mode."""

    def writes(self, w):
        b = w["built"].pid
        # a folder of code for the routes that read one (FR-MAT1): under a root the cockpit may read
        src = self.tmp / "existing-app"
        src.mkdir(exist_ok=True)
        (src / "README.md").write_text("# Orders\n\nA small order service.\n", encoding="utf-8")
        (src / "app.py").write_text("print('orders')\n", encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {ROOTS_ENV: str(self.tmp)})
        patcher.start()
        self.addCleanup(patcher.stop)
        # ln.FactoryApiTest.writes ends with the Alignment tab's writes (FR-ALN1, ln.alignment_writes): a scan of a
        # repository attached for them and a decision on an item it proposed, each refused for Mallory here.
        return [*ln.FactoryApiTest.writes(self, w),
                ("post_advance", "POST", f"/api/projects/{b}/advance",
                 lambda who, got: {"person": who, "persona": "developer"}),
                ("post_assessment_cancel", "POST", f"/api/projects/{b}/assessment/cancel",
                 lambda who, got: {"person": who, "persona": "developer"}),
                ("post_assistant", "POST", "/api/assistant",
                 lambda who, got: {"question": "What waits on me?", "persona": "developer", "person": who}),
                ("post_source_preview", "POST", "/api/source/preview",
                 lambda who, got: {"source": str(src), "person": who, "persona": "developer"}),
                ("post_adopt", "POST", "/api/adopt",
                 lambda who, got: {"title": "Orders", "source": str(src), "intent": "maintain", "person": who,
                                   "persona": "developer"}),
                ("post_settings_preview", "POST", f"/api/projects/{b}/settings/preview",     # records nothing
                 lambda who, got: {"maturity": "pilot", "person": who, "persona": "product_owner"}),
                ("post_model_test", "POST", "/api/models/analyst/test",       # records nothing; its key is not set
                 lambda who, got: {"person": who, "persona": "it"}),
                ("post_automation_preview", "POST", "/api/automations/preview",           # records nothing
                 lambda who, got: {"automation": ln.AUTOMATION | {"scope": {"kind": "project", "projects": [b]}},
                                   "person": who, "persona": "product_owner"}),
                ("post_automation_dry_run", "POST",                                       # records nothing
                 lambda got: f"/api/automations/{got['post_automation']['automation']['id']}/dry-run",
                 lambda who, got: {"person": who, "persona": "product_owner"}),
                *self.scan_writes(src)]

    def scan_writes(self, src: Path) -> list:
        """FR-RPJ1's scan in the background and its Cancel (they record nothing; test_brief_ln's writes hold the
        rest: the folders the cockpit may read, the local model, an adopted project's areas, watch and baseline)."""
        dev = lambda who, got: {"person": who, "persona": "developer"}          # noqa: E731
        return [("post_source_scan", "POST", "/api/source/scan", lambda who, got: {"source": str(src),
                                                                                   **dev(who, got)}),
                ("post_source_scan_cancel", "POST",
                 lambda got: f"/api/source/scan/{got['post_source_scan']['scan']['id']}/cancel", dev),
                # FR-PICK1: the computer's own dialog never opens under enforced access (409, after the persona check)
                ("post_pick_native", "POST", "/api/pick/native", lambda who, got: {"kind": "folder", **dev(who, got)}),
                ("post_pick_cancel", "POST", "/api/pick/native/cancel", dev)]

    def test_FR_M8_AC_3_every_write_route_refuses_a_persona_not_granted_on_its_project(self):
        w = ln.FactoryApiTest.world(self)
        self.enforce()
        self.sign_in(MALLORY)
        self.sign_in(IDA)
        home = self.factory.home
        routes = self.writes(w)
        every_write = {name for method, _, name in cockpit.ROUTES if method in ("POST", "PUT")}
        takes_no_person = {"post_link", "post_profile_propose", "post_posture_preview"}   # record nothing, sign nothing
        self.assertEqual({r[0] for r in routes} | takes_no_person, every_write)
        got = {}
        for name, method, path, body in routes:
            path = path(got) if callable(path) else path
            before = tree(home)
            status, out = self.pcall(method, path, body("Mallory Example", got), who=MALLORY)
            self.assertEqual(status, 403, (name, out))
            self.assertIn("is not granted the", out["error"], name)
            self.assertEqual(tree(home), before, name)
            if name == "post_assessment_cancel":
                from kernel import progress

                rep = progress.Reporter("assessment")          # Mallory's refusal above did not cancel it
                progress.register(progress.key_for(w["built"], "assessment"), rep)
            ledgers = self.ledgers()
            status, out = self.pcall(method, path, body("Ida Example", got), who=IDA)
            if name == "post_console_terminal":   # FR-CON1-AC-7: through IT's proxy the person is elsewhere
                self.assertEqual((status, tree(home)), (403, before), out)
                self.assertIn("from its own address", out["error"])
                continue
            if name == "post_pick_native":        # FR-PICK1: under enforced access, the folder browser instead
                self.assertEqual((status, tree(home)), (409, before), out)
                self.assertIn("use the folder browser", out["error"])
                continue
            self.assertIn(status, (200, 201, 202), (name, out))
            got[name] = out
            added = [r["event"]["payload"] for pid, recs in self.ledgers().items()
                     for r in recs[len(ledgers.get(pid, [])):]]
            if name in ("put_layout", "put_view_layouts", "post_advance", "post_assistant", "post_source_preview",
                        "post_settings_preview", "post_model_test", "post_automation_preview",
                        "post_automation_dry_run", "post_source_scan", "post_source_scan_cancel",
                        "post_pick_recent", "post_pick_cancel"):
                continue                     # kept outside every ledger: a preview or a Test records nothing
            self.assertTrue(any(e.get("identity") == IDA for e in added), (name, added))
        for p in self.factory.projects():
            self.assertTrue(p.ledger().verify().intact, p.pid)

    def ledgers(self) -> dict:
        return {p.pid: p.ledger().records() for p in self.factory.projects()}


# The command line's signed writes, each with a persona the local user "mallory" is not granted where it acts.
def cli_writes(pid: str, tmp: Path) -> dict:
    who = ["--person", "Mallory Example"]
    return {
        "new": ["new", "Parking permits", "--source", "idea", "--requested-by", "Mallory Example"],
        "intake": ["intake", pid, "--source", "Replace the request", "--requested-by", "Mallory Example"],
        "answer": ["answer", pid, "Q-001", "the lead", *who, "--persona", "business_owner"],
        "assume": ["assume", pid, "Q-001", *who, "--persona", "business_owner"],
        "decide": ["decide", pid, "C-0001", "accept", *who, "--persona", "product_owner"],
        "change": ["change", pid, "it crashes", *who, "--persona", "end_user"],
        "assess": ["assess", pid, *who, "--persona", "developer"],
        "assessment change": ["assessment", "change", pid, "F-1", *who, "--persona", "developer"],
        "adopt": ["adopt", "Old app", "--source", str(tmp), "--intent", "monitor", *who, "--persona", "developer"],
        "workspace open": ["workspace", "open", pid, *who, "--persona", "developer", "--agent", "shell"],
        "workspace submit": ["workspace", "submit", pid, "ws", *who, "--persona", "developer"],
        "security ingest": ["security", "ingest", pid, "scan.sarif", *who, "--persona", "it"],
        "security accept": ["security", "accept", pid, "F-1", "--reason", "r", "--expires", FUTURE, *who,
                            "--persona", "it"],
        "evidence": ["evidence", pid, "--out", str(tmp / "out"), *who, "--persona", "compliance"],
        "embed create": ["embed", "create", "--kind", "need", "--origin", "https://shop.example", *who,
                         "--persona", "it"],
        "embed revoke": ["embed", "revoke", "E-1", *who, "--persona", "it"],
        "autonomy set": ["autonomy", "set", "2", "--reason", "audit", *who, "--persona", "compliance"],
        "posture set": ["posture", "set", pid, "balanced", "--reason", "audit", *who, "--persona", "business_owner"],
        "posture confirm": ["posture", "confirm", pid, "A-001", *who, "--persona", "business_owner"],
        "signal log": ["signal", "log", "--text", "pallets", "--channel", "chat", "--source", "ops", *who,
                       "--persona", "stakeholder"],
        "concept edit": ["concept", "edit", "C-0001", "--title", "x", *who, "--persona", "business_owner"],
        "pack": ["pack", "withdraw", pid, "a recall", *who, "--persona", "it"],
        "hooks add": ["hooks", "add", "repo-events", *who, "--persona", "it", "--scheme", "github",
                      "--secret-env", "HOOK_SECRET"],
        "hooks remove": ["hooks", "remove", "repo-events", *who, "--persona", "it"],
        "hooks bind": ["hooks", "bind", "repo-events", "--project", pid, *who, "--persona", "it"],
        # automations (kernel/automations_cli.py, FR-AUT1)
        "automations add": ["automations", "add", "--name", "n", "--every", "1h", "--action", "signal", "--text", "t",
                            "--factory", *who, "--persona", "stakeholder"],
        "automations edit": ["automations", "edit", "AU-001", "--every", "2h", *who, "--persona", "stakeholder"],
        "automations pause": ["automations", "pause", "AU-001", *who, "--persona", "stakeholder"],
        "automations resume": ["automations", "resume", "AU-001", *who, "--persona", "stakeholder"],
        "automations remove": ["automations", "remove", "AU-001", *who, "--persona", "stakeholder"],
        "automations run-now": ["automations", "run-now", "AU-001", *who, "--persona", "stakeholder"],
        "automations tag": ["automations", "tag", pid, "--tag", "ops", *who, "--persona", "stakeholder"],
        "relay subscribe": ["relay", "subscribe", *who, "--persona", "it", "--sink", "webhook",
                            "--url", "https://hooks.example/in"],
        "relay cockpit": ["relay", "cockpit", "https://rihmasto.example", *who, "--persona", "it"],
        "relay unsubscribe": ["relay", "unsubscribe", "SUB-1", *who, "--persona", "it"],
        "connector enable": ["connector", "enable", "example", *who, "--persona", "it"],
        "connector disable": ["connector", "disable", "example", *who, "--persona", "it"],
        "integration declare": ["integration", "declare", pid, "--name", "orders_db", "--kind", "sqlite", "--access",
                                "read", "--data-class", "internal", *who, "--persona", "product_owner"],
        "integration withdraw": ["integration", "withdraw", pid, "orders_db", "--reason", "r", *who,
                                 "--persona", "product_owner"],
        "inputs refine": ["inputs", "refine", pid, *who, "--persona", "product_owner"],   # who asks a model to read
        "autopilot start": ["autopilot", "start", pid, "--until", "8h", "--delegate", "question", *who,
                            "--persona", "developer", "--arm-only"],
        "autopilot stop": ["autopilot", "stop", pid, *who, "--persona", "developer"],
        "autopilot relay": ["autopilot", "relay", "SUB-1", *who, "--persona", "it"],
        "delegation grant": ["delegation", "grant", pid, "--kinds", "question", "--until", "8h", *who,
                             "--persona", "business_owner"],
        "delegation revoke": ["delegation", "revoke", pid, "DL-001", *who, "--persona", "business_owner"],
        "tracking set": ["tracking", "set", pid, "--checkpoints", "5", *who, "--persona", "product_owner"],
        "tracking look": ["tracking", "look", pid, "5", *who, "--persona", "product_owner"],
        "tracking digest": ["tracking", "digest", "SUB-1", "daily", *who, "--persona", "it"],
        "output": ["output", pid, "--choose", "report", *who, "--persona", "business_owner"],
        # the modules and an attached repository of your own (kernel/standalone.py)
        "modules set": ["modules", "set", "--preset", "full", *who, "--persona", "it"],
        "repo attach": ["repo", "attach", "Old app", "--repo", str(tmp), *who, "--persona", "developer"],
        "repo contract": ["repo", "contract", pid, "--contract", "contract.json", *who, "--persona", "developer"],
        "repo gate": ["repo", "gate", pid, *who, "--persona", "developer"],
        "repo holdouts": ["repo", "holdouts", pid, "--base-url", "http://127.0.0.1:9", *who, "--persona", "it"],
        "repo scan": ["repo", "scan", pid, *who, "--persona", "it"],
        "repo releases": ["repo", "releases", pid, *who, "--persona", "compliance"],
        "contract export": ["contract", "export", pid, "--out", str(tmp / "out"), *who, "--persona", "product_owner"],
        # change anything set at creation, go back a step, add material (FR-CHG1)
        "settings": ["settings", pid, "--maturity", "pilot", "--reason", "r", *who, "--persona", "product_owner"],
        "rewind": ["rewind", pid, "--to", "questions", "--reason", "r", *who, "--persona", "product_owner"],
        "material add": ["material", "add", pid, "--text", "more", *who, "--persona", "product_owner"],
        # Shape it in chat and Models setup (kernel/shape_cli.py); `shape` alone is the interactive chat
        "shape": ["shape", *who, "--persona", "business_owner"],
        "shape start": ["shape", "start", "--text", "drills go missing", *who, "--persona", "business_owner"],
        "shape say": ["shape", "say", "SH-001", "the team borrows them", *who, "--persona", "business_owner"],
        "shape attach": ["shape", "attach", "SH-001", str(tmp), *who, "--persona", "business_owner"],
        "shape edit": ["shape", "edit", "SH-001", "problem", "drills go missing", *who, "--persona", "business_owner"],
        "shape create": ["shape", "create", "SH-001", *who, "--persona", "business_owner"],
        "models set": ["models", "set", "analyst", "--base-url", "http://127.0.0.1:9/v1", "--model", "m", *who,
                       "--persona", "it"],
        "models remove": ["models", "remove", "analyst", *who, "--persona", "it"],
        "runners set": ["runners", "set", "builder", "gnomon", *who, "--persona", "it"],      # D-0019
        # -- walkthroughs in a terminal (kernel/walkthrough_cli.py, FR-WLK1)
        "walkthrough": ["walkthrough", "tour", *who, "--persona", "developer"],
        # the console, a shell and the checks (kernel/console_cli.py; FR-CON1, FR-CHK1)
        "console": ["console", pid, *who, "--persona", "developer", "--", "git", "status"],
        "shell": ["shell", pid, *who, "--persona", "developer"],
        "checks enable": ["checks", "enable", pid, "secrets", *who, "--persona", "developer"],
        "checks disable": ["checks", "disable", pid, "secrets", *who, "--persona", "developer"],
        "checks run": ["checks", "run", pid, "secrets", *who, "--persona", "developer"],
        # alignment with a repository's own specs and tests (FR-ALN1): a decision is signed; reading is not
        "align": ["align", pid, "accept", "req-0000000000", *who, "--persona", "developer"],
        # since you last looked (FR-REV1): `review` signs mark, done and digest; reading it takes no signer
        "review": ["review", "done", *who, "--persona", "developer"],
        # the paved roads (kernel/road_settings.py, FR-GCP1): IT configures a road, chooses a project's, rolls back
        "road configure": ["road", "configure", "company-gcp", "--file", str(tmp / "road.json"), *who, "--persona", "it"],
        "road choose": ["road", "choose", pid, "company-gcp", *who, "--persona", "it"],
        "road rollback": ["road", "rollback", pid, "--reason", "r", *who, "--persona", "it"],
        **bridge_cli_writes(pid),
        # the coding agent you already have answers the text roles (kernel/harness_setup.py, FR-HMD1)
        "models use": ["models", "use", "claude-code", "--roles", "assistant", *who, "--persona", "it"],
        # FR-RPJ1: a stated test command run as an adopted project's baseline
        "baseline": ["baseline", pid, "--command", "python tools/check.py test", *who, "--persona", "developer",
                     "--yes"],
    }


def bridge_cli_writes(pid: str) -> dict:
    """The agent channel's signed command (kernel/bridge_cli.py, FR-CHN1): an agent posts for its operator."""
    return {"channel post": ["channel", pid, "post", "--as", "claude-code", "--text", "added the form",
                             "--person", "Mallory Example", "--persona", "developer"]}


class CommandLineAndMcpTest(FactoryTestCase):
    """FR-M8-AC-3 and FR-M8-AC-4: the command line and the MCP server sign as the operating system's user."""

    def setUp(self):
        super().setUp()
        self.p = self.new(mode="socratic")
        self.card = Canon(self.p).card("change", "Show overdue loans first")["id"]
        path = kaccess.access_path(self.factory)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, access_doc())
        kaccess.load(self.factory, record=True)

    def cli(self, user: str, *argv: str) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("kernel.access.os_user", return_value=user), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_FR_M8_AC_3_every_signed_command_refuses_a_persona_not_granted_where_it_acts(self):
        # A signed command takes --person or --requested-by as an option; `graph answers <pid> <person>`
        # names whose answers to trace, read only, and signs nothing.
        signed = {name for name, parser in leaves(build_parser()).items()
                  if any(a.dest in ("person", "requested_by") and a.option_strings for a in parser._actions)}
        commands = cli_writes(self.p.pid, self.tmp)
        self.assertEqual(set(commands), signed)                      # intake too: it rewrites a project's request
        home = self.factory.home
        for name, argv in commands.items():
            before = tree(home)
            code, out, err = self.cli("mallory", *argv)
            self.assertEqual((code, out), (2, ""), (name, err))
            self.assertTrue(err.startswith(f"rihmasto {name}: "), (name, err))
            self.assertIn("is not granted the", err, name)
            self.assertNotIn("Traceback", err)
            self.assertEqual(tree(home), before, name)

    def test_FR_M8_AC_4_the_command_line_signs_as_the_local_user_the_file_names(self):
        decide = ["decide", self.p.pid, self.card, "accept", "--persona", "product_owner"]
        code, _, err = self.cli("stranger", *decide, "--person", "Aino Example")
        self.assertEqual(code, 2)
        self.assertIn("local:stranger is not in the access file", err)
        code, _, err = self.cli("aino", *decide, "--person", "Ida Example")       # another person's name
        self.assertEqual(code, 2)
        self.assertIn("the person is the signed-in identity, Aino Example", err)
        self.assertEqual(Canon(self.p).decisions(), [])
        code, out, err = self.cli("aino", *decide, "--person", "Aino Example")
        self.assertEqual(code, 0, err)
        d = Canon(self.p).decisions()[-1]
        self.assertEqual((d["person"], d["persona"], d["identity"]), ("Aino Example", "product_owner", "local:aino"))
        # a signal logged without --person is signed with the verified name
        code, out, err = self.cli("it-admin", "signal", "log", "--text", "Pallets need tracking", "--channel", "chat",
                                  "--source", "ops weekly", "--persona", "it")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["person"], "Ilkka Example")
        code, _, err = self.cli("aino", "status")
        self.assertIn("enforced: decisions are signed by verified identities", err)

    def test_FR_M8_AC_4_the_mcp_server_proposes_as_the_verified_operator_and_never_decides(self):
        with mock.patch("kernel.access.os_user", return_value="stranger"), self.assertRaises(ValueError) as ctx:
            RihmaMCP(self.factory, person="Aino Example", persona="developer")
        self.assertIn("local:stranger is not in the access file", str(ctx.exception))
        with mock.patch("kernel.access.os_user", return_value="aino"):
            with self.assertRaises(ValueError):
                RihmaMCP(self.factory, person="Ida Example", persona="developer")   # not her name
            with self.assertRaises(ValueError):
                RihmaMCP(self.factory, person="Aino Example", persona="compliance")  # not granted
            server = RihmaMCP(self.factory, person="Aino Example", persona="developer")
        self.assertEqual(server.identity.id, "local:aino")
        made = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "rihma_report_change", "arguments": {"pid": self.p.pid, "text": "Rename the report"}}})
        result = made["result"]["structuredContent"]
        self.assertEqual(result["signed"], {"person": "Aino Example", "persona": "developer", "identity": "local:aino"})
        notes = [r["event"]["payload"] for r in self.p.ledger().of_kind("mcp_write", "change_submitted")]
        self.assertEqual({(n["person"], n["identity"]) for n in notes}, {("Aino Example", "local:aino")})
        # an MCP client trying to decide: there is no such tool, and the card stays open
        tried = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "rihma_decide", "arguments": {"pid": self.p.pid, "card": self.card, "verdict": "accept"}}})
        self.assertIn("error", tried)
        self.assertNotIn("decide", " ".join(t["name"] for t in tool_list()))
        self.assertEqual(Canon(self.p).get_card(self.card)["state"], "open")
        # a proposal on a project outside the operator's grants is refused
        with mock.patch("kernel.access.os_user", return_value="mallory"):
            outsider = RihmaMCP(self.factory, person="Mallory Example", persona="stakeholder")
        said = outsider.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "rihma_comment", "arguments": {"pid": self.p.pid, "target_kind": "requirement",
                                                   "target_id": "R-1", "text": "a remark"}}})
        self.assertTrue(said["result"]["isError"])
        self.assertIn("is not granted the stakeholder persona", said["result"]["content"][0]["text"])
        self.assertEqual(Canon(self.p).comments(), [])


if __name__ == "__main__":
    unittest.main()
