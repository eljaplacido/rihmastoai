"""The cockpit's sign-in by the identity provider's signed token (FR-ID1, D-0016).

The cockpit holds no shared secret. It verifies the token IT's proxy forwards (RS256 or ES256, written
with Python's integers) with the provider's public keys from a JWKS file in the access folder, and takes
the identity, name and groups from it. The keys and tokens here are made in pure Python
(``access_fakes``), and RFC 6979's published P-256 vectors check the signer and the verifier.
"""

import base64
import contextlib
import hashlib
import hmac
import io
import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import test_cockpit  # noqa: E402
from access_fakes import (  # noqa: E402
    RFC6979_KEY,
    RFC6979_PUBLIC,
    RFC6979_SIGNATURES,
    SHA256_INFO,
    Provider,
    cube_root,
    ec_public,
    ec_sign,
    rfc6979_k,
    rsa_key,
    rsa_sign,
    segment,
)
from factory_fakes import FactoryTestCase  # noqa: E402
from test_cockpit import FakeRunner  # noqa: E402
from test_ui_drive import Browser, find_chrome  # noqa: E402
from test_access import AINO, AUDIENCE, IDP, ISSUER, MALLORY, PUBLIC, EnforcedCockpitCase, access_doc, write_access  # noqa: E402

from cockpit import server as cockpit  # noqa: E402
from kernel import access as kaccess  # noqa: E402
from kernel import jwt_verify as jv  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.store import write_json  # noqa: E402

ES = Provider(ISSUER, AUDIENCE, alg="ES256", kid="es-key-1", seed=5)


def keys_of(*providers: Provider) -> dict:
    return jv.parse_jwks(json.dumps({"keys": [p.jwk() for p in providers]}).encode())


def hs256(token_claims: dict, secret: bytes, kid: str = "test-key-1") -> str:
    head, body = segment({"alg": "HS256", "kid": kid, "typ": "JWT"}), segment(token_claims)
    mac = hmac.new(secret, f"{head}.{body}".encode("ascii"), hashlib.sha256).digest()
    return f"{head}.{body}.{segment(mac)}"


class VerifyTest(unittest.TestCase):
    """FR-ID1-AC-1: kernel.jwt_verify, RS256 and ES256 with the standard library."""

    def test_FR_ID1_AC_1_rfc6979_vectors_and_generated_keys_verify(self):
        self.assertEqual(ec_public(RFC6979_KEY), RFC6979_PUBLIC)          # RFC 6979, A.2.5: the public key
        key = jv.EcKey(*RFC6979_PUBLIC)
        for message, (k, r, s) in RFC6979_SIGNATURES.items():
            self.assertEqual(rfc6979_k(RFC6979_KEY, hashlib.sha256(message).digest()), k, message)
            self.assertEqual(ec_sign(RFC6979_KEY, message), (r, s), message)
            signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
            self.assertTrue(key.verify(message, signature), message)
            self.assertFalse(key.verify(message + b"!", signature), message)
            self.assertFalse(key.verify(message, r.to_bytes(32, "big") + (s ^ 1).to_bytes(32, "big")), message)
            self.assertFalse(key.verify(message, signature[:63]), message)
        for provider in (IDP, ES):
            header, claims = jv.verify(provider.token("aino-sub", groups=["a, b"]), keys_of(provider),
                                       jv.Expect(provider.alg, ISSUER, AUDIENCE))
            self.assertEqual((header["alg"], claims["sub"], claims["groups"]), (provider.alg, "aino-sub", ["a, b"]))
        n, e, _ = rsa_key(1)                                             # a 2048-bit test key, the same every run
        self.assertEqual((n.bit_length(), e), (2048, 65537))

    def test_FR_ID1_AC_1_a_token_holds_only_with_its_algorithm_key_issuer_audience_and_time(self):
        keys, expect, now = keys_of(IDP, ES), jv.Expect("RS256", ISSUER, AUDIENCE, 60), time.time()
        good = IDP.token("aino-sub")
        self.assertEqual(jv.verify(good, keys, expect)[1]["sub"], "aino-sub")
        head, body, sig = good.split(".")
        public = json.dumps(IDP.jwks()).encode()
        refused = {
            "alg none": (f"{segment({'alg': 'none', 'kid': 'test-key-1'})}.{body}.", "not signed"),
            "HS256 keyed with the public key file": (hs256(IDP.claims("aino-sub"), public), "shared secret"),
            "HS256 keyed with the modulus": (hs256(IDP.claims("aino-sub"), IDP.jwk()["n"].encode()), "shared secret"),
            "ES256 for an RS256 file": (ES.token("aino-sub"), "signed with ES256"),
            "an unknown key id": (IDP.token("aino-sub", header={"kid": "rotated-away"}), "not in the key file"),
            "another key, the same id": (Provider(ISSUER, AUDIENCE, seed=2).token("aino-sub"), "does not verify"),
            "a tampered payload": (f"{head}.{segment(IDP.claims('mallory-sub'))}.{sig}", "does not verify"),
            "a tampered header": (f"{segment({'alg': 'RS256', 'kid': 'test-key-1'})}.{body}.{sig}", "does not verify"),
            "a tampered signature": (f"{head}.{body}.{sig[:-2]}{'A' if sig[-2] != 'A' else 'B'}{sig[-1]}",
                                     "does not verify"),
            "a critical extension": (IDP.token("aino-sub", header={"crit": ["exp"]}), "crit"),
            "another issuer": (IDP.token("aino-sub", iss="https://login.example.net"), "another issuer"),
            "another audience": (IDP.token("aino-sub", aud="another-app"), "another audience"),
            "expired beyond the skew": (IDP.token("aino-sub", ttl=-61), "expired"),
            "not valid yet": (IDP.token("aino-sub", nbf=int(now) + 600), "not valid yet"),
            "issued in the future": (IDP.token("aino-sub", iat=int(now) + 600), "in the future"),
            "no expiry": (IDP.token("aino-sub", claims={"iss": ISSUER, "aud": AUDIENCE, "sub": "x"}), "no expiry"),
            "an encrypted token": ("a.b.c.d.e", "encrypted"),
            "too long": ("a" * (jv.MAX_TOKEN + 1), "longer than"),
            "not base64url": (f"{head}.{body}.{sig}*", "not base64url"),
        }
        for what, (token, why) in refused.items():
            with self.assertRaises(jv.TokenRefused, msg=what) as ctx:
                jv.verify(token, keys, expect)
            self.assertIn(why, str(ctx.exception), what)
        self.assertEqual(jv.verify(IDP.token("aino-sub", ttl=-30), keys, expect)[1]["sub"], "aino-sub")  # in the skew
        self.assertEqual(jv.verify(IDP.token("aino-sub", aud=["other", AUDIENCE]), keys, expect)[1]["sub"], "aino-sub")
        with self.assertRaises(jv.TokenRefused):                               # the file's algorithm, never HS*
            jv.verify(good, keys, jv.Expect("HS256", ISSUER, AUDIENCE))

    def test_FR_ID1_AC_1_the_whole_pkcs1_block_is_compared_so_the_e3_forgery_fails(self):
        key = rsa_key(seed=3, e=3)
        verifier = jv.RsaKey(key[0], 3)
        message = b"header.payload"
        self.assertTrue(verifier.verify(message, rsa_sign(key, message)))
        # Bleichenbacher's forgery: a cube whose top bytes read 00 01 FF 00 DigestInfo hash, garbage after
        prefix = b"\x00\x01\xff\x00" + SHA256_INFO + hashlib.sha256(message).digest()
        forged = cube_root(int.from_bytes(prefix + b"\x00" * (256 - len(prefix)), "big"))
        block = pow(forged, 3, key[0]).to_bytes(256, "big")
        self.assertEqual(block[:len(prefix)], prefix)                          # a parser that stops there takes it
        self.assertNotEqual(block[len(prefix):], b"\x00" * (256 - len(prefix)))
        self.assertFalse(verifier.verify(message, forged.to_bytes(256, "big")))

    def test_FR_ID1_AC_1_the_key_file_takes_public_signing_keys_only(self):
        rsa, ec = IDP.jwk(), ES.jwk()
        small = rsa_key(seed=4, bits=1024)
        bad = {
            "is a symmetric key": {"kty": "oct", "kid": "k", "k": "c2VjcmV0"},
            "is a 1024-bit key": dict(rsa, n=jv.b64url_encode(small[0].to_bytes(128, "big"))),
            "is not a point on P-256": dict(ec, y=jv.b64url_encode((RFC6979_PUBLIC[1] + 1).to_bytes(32, "big"))),
            "must name the key": {k: v for k, v in rsa.items() if k != "kid"},
        }
        for why, jwk in bad.items():
            with self.assertRaises(jv.KeyFileError, msg=why) as ctx:
                jv.parse_jwks(json.dumps({"keys": [jwk]}).encode())
            self.assertIn(why, str(ctx.exception))
        with self.assertRaises(jv.KeyFileError) as ctx:
            jv.parse_jwks(json.dumps({"keys": [rsa, rsa]}).encode())
        self.assertIn("is listed twice", str(ctx.exception))
        others = [dict(rsa, use="enc"), dict(rsa, alg="RS384", kid="b"), dict(ec, crv="P-384", kid="c")]
        with self.assertRaises(jv.KeyFileError) as ctx:                       # set aside: nothing left to sign with
            jv.parse_jwks(json.dumps({"keys": others}).encode())
        self.assertIn("holds no RS256 or ES256 signing key", str(ctx.exception))
        self.assertEqual(set(jv.parse_jwks(json.dumps({"keys": [*others, rsa, ec]}).encode())), {"test-key-1", "es-key-1"})


PRESET_CASES = {
    # oauth2-proxy passing Entra ID's ID token in Authorization: the object id names the person, app roles group
    "oauth2-proxy and Entra ID": dict(
        issuer="https://login.microsoftonline.com/9c1f0000-0000-4000-8000-00000000e17a/v2.0",
        proxy={"preset": "oauth2-proxy", "subject_claim": "oid", "name_claim": "preferred_username",
               "groups_claim": "roles"},
        audience="0b5c0000-0000-4000-8000-0000000c11e7", header="Authorization", bearer=True,
        claims={"oid": "3f2a0000-0000-4000-8000-000000a1b0c0", "preferred_username": "aino@example.org",
                "roles": ["Rihmasto.Operations"]},
        sub="pairwise-for-this-app", subject="3f2a0000-0000-4000-8000-000000a1b0c0", name="aino@example.org",
        group="Rihmasto.Operations"),
    # oauth2-proxy passing Keycloak's access token: the realm's roles, read by path
    "oauth2-proxy and Keycloak": dict(
        issuer="https://keycloak.example.org/realms/staff", audience="rihmasto", header="X-Forwarded-Access-Token",
        proxy={"preset": "oauth2-proxy", "token_header": "X-Forwarded-Access-Token",
               "groups_claim": "realm_access.roles"},
        claims={"email": "kim@example.org", "realm_access": {"roles": ["ops, nights"]}},
        sub="kc-7d1c", subject="kc-7d1c", name="kim@example.org", group="ops, nights"),
    # any OIDC proxy, here with Okta's groups claim, in a header the file names
    "an OIDC proxy and Okta": dict(
        issuer="https://example.okta.com/oauth2/default", proxy={"preset": "oidc", "token_header": "X-Id-Token",
                                                                  "groups_claim": "groups"},
        audience="0oa1example", header="X-Id-Token", claims={"email": "ola@example.org", "groups": ["Rihmasto Ops"]},
        sub="00u1example", subject="00u1example", name="ola@example.org", group="Rihmasto Ops"),
    # Google IAP: ES256, the fixed issuer, an audience naming the backend; no groups, so bind the subject
    "Google IAP": dict(
        issuer="https://cloud.google.com/iap", proxy={"preset": "google-iap"}, alg="ES256",
        audience="/projects/123456789/apps/rihmasto-example", header="x-goog-iap-jwt-assertion",
        claims={"email": "ines@example.org", "hd": "example.org"}, sub="accounts.google.com:1180001",
        subject="accounts.google.com:1180001", name="ines@example.org", group=None),
}


class PresetsTest(EnforcedCockpitCase):
    """FR-ID1-AC-2: each kind of sign-in proxy, its token's header, and the groups claim it is told to read."""

    def ask(self, method, path, header=None, value=None, *, session=None, body=None, headers=()):
        sent = {"Origin": PUBLIC, **({header: value} if header else {}), **dict(headers)}
        if session:
            sent[kaccess.SESSION_HEADER] = session
        data = json.dumps(body if body is not None else {}).encode() if method == "POST" else None
        if data is not None:
            sent["Content-Type"] = "application/json"
        req = urllib.request.Request(self.origin + path, data=data, headers=sent, method=method)
        try:
            with test_cockpit._DIRECT.open(req, timeout=10) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def file_for(self, case: dict, subject_id: str) -> dict:
        proxy = {"issuer": case["issuer"], "origin": PUBLIC, "audience": case["audience"], **case["proxy"]}
        bind = {"group": case["group"]} if case["group"] else {"subject": subject_id}
        people = [{"identity": "local:it-admin", "name": "Ilkka Example"}]
        if not case["group"]:
            people.append({"identity": subject_id, "name": "Ines Example"})
        return access_doc(proxy=proxy, people=people, bindings=[
            {"subject": "local:it-admin", "persona": "it", "scope": "*"}, {**bind, "persona": "operations", "scope": "*"}])

    def test_FR_ID1_AC_2_each_preset_signs_in_with_the_providers_token_and_its_groups_claim(self):
        for what, case in PRESET_CASES.items():
            with self.subTest(what):
                idp = Provider(case["issuer"], case["audience"], alg=case.get("alg", "RS256"), seed=11)
                ident = f"{case['issuer']}#{case['subject']}"
                self.enforce(self.file_for(case, ident), idp.jwks())
                token = idp.token(case["sub"], **case["claims"])
                value = f"Bearer {token}" if case.get("bearer") else token
                status, out = self.ask("POST", "/auth", case["header"], value)
                self.assertEqual(status, 200, out)
                status, meta = self.ask("GET", "/api/meta", case["header"], value, session=out["token"])
                self.assertEqual(status, 200, meta)
                name = "Ines Example" if not case["group"] else case["name"]
                self.assertEqual((meta["access"]["identity"], meta["access"]["name"]), (ident, name))
                self.assertEqual(meta["access"]["grants"], [{"persona": "operations", "scope": "*"}])
                # the same person's token from another provider's key, or another group, signs no one in
                other = Provider(case["issuer"], case["audience"], alg=case.get("alg", "RS256"), seed=12)
                forged = other.token(case["sub"], **case["claims"])
                self.assertEqual(self.ask("POST", "/auth", case["header"], f"Bearer {forged}" if case.get("bearer")
                                          else forged)[0], 401)
                if case["group"]:
                    plain = idp.token(case["sub"], **{k: v for k, v in case["claims"].items()
                                                      if k not in ("roles", "groups", "realm_access")})
                    status, out = self.ask("POST", "/auth", case["header"], f"Bearer {plain}" if case.get("bearer")
                                           else plain)
                    self.assertEqual(status, 401, out)
                    self.assertIn("is granted no persona", out["error"])

    def test_FR_ID1_AC_2_aws_alb_signs_its_header_and_names_itself_and_the_client(self):
        issuer = "https://cognito-idp.eu-north-1.amazonaws.com/eu-north-1_Example"
        signer = "arn:aws:elasticloadbalancing:eu-north-1:111122223333:loadbalancer/app/rihmasto/50dc6c495c0c9188"
        alb = Provider(issuer, None, alg="ES256", kid="3f8e0000-0000-4000-8000-0000000a1b00", seed=13)
        case = {"issuer": issuer, "audience": "7example2client", "group": "rihmasto-ops",
                "proxy": {"preset": "aws-alb", "signer": signer, "groups_claim": "cognito:groups"}}
        self.enforce(self.file_for(case, ""), alb.jwks())
        token = alb.alb_token("c0g-sub", signer=signer, client="7example2client", email="ari@example.org",
                              **{"cognito:groups": ["rihmasto-ops"]})
        self.assertIn("=", token.split(".")[0] + token.split(".")[1])          # padded base64, as the ALB writes it
        status, out = self.ask("POST", "/auth", "x-amzn-oidc-data", token)
        self.assertEqual(status, 200, out)
        status, meta = self.ask("GET", "/api/meta", "x-amzn-oidc-data", token, session=out["token"])
        self.assertEqual((meta["access"]["identity"], meta["access"]["name"]), (f"{issuer}#c0g-sub", "ari@example.org"))
        for what, forged in (("another load balancer", alb.alb_token("c0g-sub", signer=signer + "0", client="7example2client",
                                                                      **{"cognito:groups": ["rihmasto-ops"]})),
                             ("another client", alb.alb_token("c0g-sub", signer=signer, client="another",
                                                              **{"cognito:groups": ["rihmasto-ops"]}))):
            status, out = self.ask("POST", "/auth", "x-amzn-oidc-data", forged)
            self.assertEqual(status, 401, what)
            self.assertIn("is not the one the access file names", out["error"], what)
        # the plain headers the ALB also sends are never read
        status, _ = self.ask("POST", "/auth", "x-amzn-oidc-identity", "c0g-sub")
        self.assertEqual(status, 401)

    def test_FR_ID1_AC_2_the_access_file_names_the_algorithm_and_refuses_a_shared_secret(self):
        good = access_doc()
        proxy = good["proxy"]
        broken = {
            "$.proxy.secret_env": dict(proxy, secret_env="RIHMASTO_PROXY_SECRET"),
            "$.proxy.user_header": dict(proxy, user_header="X-Forwarded-User"),
            "$.proxy.algorithm": dict(proxy, algorithm="HS256"),
            "$.proxy.preset": dict(proxy, preset="basic-auth"),
            "$.proxy.token_header": dict(proxy, token_header="X-Forwarded-User"),
            "$.proxy.issuer": dict(proxy, preset="google-iap", issuer=ISSUER),
            "$.proxy.signer": dict(proxy, preset="aws-alb", algorithm="ES256"),
            "$.proxy.keys": dict(proxy, keys="../../ledger.jsonl"),
            "$.proxy.clock_skew": dict(proxy, clock_skew=3600),
        }
        for where, bad in broken.items():
            with self.assertRaises(kaccess.AccessFileError, msg=where) as ctx:
                kaccess.parse(json.dumps(dict(good, proxy=bad)).encode())
            self.assertTrue(str(ctx.exception).startswith(where), (where, str(ctx.exception)))
        with self.assertRaises(kaccess.AccessFileError) as ctx:
            kaccess.parse(json.dumps(dict(good, proxy=dict(proxy, preset="oidc", token_header="Cookie"))).encode())
        self.assertIn("names a header the cockpit reads for itself", str(ctx.exception))
        with self.assertRaises(kaccess.AccessFileError) as ctx:
            kaccess.parse(json.dumps(dict(good, proxy=broken["$.proxy.secret_env"])).encode())
        self.assertIn("the cockpit holds no shared secret", str(ctx.exception))
        self.assertEqual(kaccess.parse(json.dumps(good).encode()).proxy.algorithm, "RS256")


class SessionTest(EnforcedCockpitCase):
    """FR-ID1-AC-3: a session is bound to the token's subject and ends with it."""

    def test_FR_ID1_AC_3_a_session_ends_with_its_token_and_answers_its_subject_only(self):
        doc = access_doc()
        doc["proxy"]["clock_skew"] = 0
        self.enforce(doc)
        short = IDP.token("aino-sub", ttl=2)
        status, out = self.pcall("POST", "/auth", {}, token="", id_token=short)
        self.assertEqual(status, 200, out)
        self.assertLessEqual(out["expires_in"], 2)                            # not the cockpit's 12 hours
        session = out["token"]
        self.assertEqual(self.pcall("GET", "/api/projects", token=session, id_token=short)[0], 200)
        # another subject's token with this session, or the session where the token goes: refused
        self.assertEqual(self.pcall("GET", "/api/projects", token=session, who=MALLORY)[0], 401)
        self.assertEqual(self.call("GET", "/api/projects", token=session)[0], 401)
        meta = self.pcall("GET", "/api/meta", token=session, id_token=short)[1]
        self.assertTrue(meta["access"]["session_ends"].endswith("Z"))
        self.assertIn("the session ends with the sign-in token", meta["access"]["detail"])
        exp = json.loads(base64.urlsafe_b64decode(short.split(".")[1] + "=="))["exp"]
        time.sleep(max(0.0, exp - time.time()) + 0.3)
        fresh = IDP.token("aino-sub")                                        # the proxy forwards a fresh token
        status, out = self.pcall("GET", "/api/projects", token=session, id_token=fresh)
        self.assertEqual((status, out["access"]), (401, "enforced"))          # the session ended with its token
        status, out = self.pcall("POST", "/auth", {}, token="", id_token=fresh)
        self.assertEqual(status, 200, out)
        self.assertEqual(self.pcall("GET", "/api/projects", token=out["token"], id_token=fresh)[0], 200)


class SessionPageTest(FactoryTestCase):
    """FR-ID1-AC-3, in Chrome: the page signs in again through the proxy when its session ends with the
    token, and the person menu says when it ends and where untrusted code runs, by keyboard, at both
    widths and in both themes."""

    @classmethod
    def setUpClass(cls):
        cls.chrome = find_chrome()
        if cls.chrome is None:
            raise unittest.SkipTest("Chrome is not installed (RIHMA_CHROME names another browser binary)")

    def setUp(self):
        super().setUp()
        self.new()
        self.server, _ = cockpit.make_server(self.factory, 0, runner=FakeRunner())
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.browser = Browser(self.chrome, self.tmp / "chrome")
        self.browser.shots = Path(os.environ.get("RIHMA_SHOTS") or self.tmp / "shots")
        self.browser.shots.mkdir(parents=True, exist_ok=True)
        self.addCleanup(self.browser.close)

    def forward(self, token: str) -> None:
        """What IT's proxy does on every request: the provider's current token in Authorization."""
        self.browser.cmd("Network.setExtraHTTPHeaders", {"headers": {"Authorization": f"Bearer {token}"}})

    def test_FR_ID1_AC_3_the_page_signs_in_again_when_its_session_ends_with_the_token(self):
        b = self.browser
        doc = access_doc()
        doc["proxy"]["clock_skew"] = 0
        write_access(self.factory, doc)
        short = IDP.token("aino-sub", ttl=3)
        b.cmd("Network.enable")
        self.forward(short)
        b.step = "signed in"
        b.cmd("Page.navigate", {"url": f"{self.server.origin}/"})
        note = "enforced: signed in as Aino Example"
        signed_in = (f"!document.documentElement.classList.contains('signed-out') && "
                     f"document.querySelector('#access-note').textContent === {json.dumps(note)}")
        b.wait(signed_in, "the verified person in the top bar")
        exp = json.loads(base64.urlsafe_b64decode(short.split(".")[1] + "=="))["exp"]
        self.forward(IDP.token("aino-sub"))                                      # the proxy refreshed the token
        time.sleep(max(0.0, exp - time.time()) + 0.3)
        b.step = "session ended"
        b.eval("location.hash = '#/projects'; true")
        b.wait("location.hash === '#/projects' && document.querySelector('#main').dataset.loaded !== '0'",
               "the projects page")
        b.wait(f"performance.getEntriesByType('resource').filter((e) => e.name.endsWith('/auth')).length === 2"
               f" && {signed_in}", "a second, quiet sign-in")
        self.assertFalse(b.eval("!!document.querySelector('.signin-card')"))
        expected = [p for p in b.problems if p[1] == "log:network:error" and "401" in str(p[2])]
        self.assertEqual([p for p in b.problems if p not in expected], [])      # only the session's own end
        self.assertLessEqual(len(expected), 1)
        self.assertEqual(b.violations(), [])
        # the person menu, by keyboard: when the session ends and where untrusted code runs
        for width, scheme in ((1440, "light"), (1440, "dark"), (390, "light"), (390, "dark")):
            b.step = f"person menu {width} {scheme}"
            b.cmd("Emulation.setDeviceMetricsOverride", {"width": width, "height": 900, "deviceScaleFactor": 1,
                                                         "mobile": width < 600})
            b.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": scheme}]})
            b.eval("document.querySelector('#person-chip').focus(); true")
            for kind in ("keyDown", "keyUp"):                                  # Enter, as a keyboard types it
                b.cmd("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter", "text": "\r",
                                                 "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13})
            b.wait("!document.querySelector('#person-pop').hidden && document.querySelector('#person-pop')"
                   ".contains(document.activeElement)", "the person menu, focused")
            text = b.eval("document.querySelector('#access-pop').textContent")
            self.assertRegex(text, r"the session ends with the sign-in token, at \d\d:\d\d UTC on \d{4}-\d\d-\d\d\.")
            self.assertIn(". Untrusted code runs in a container (python:3.12-slim)", text)
            shown, sideways = b.eval("[document.querySelector('#access-pop').getClientRects().length > 0, "
                                     "document.documentElement.scrollWidth - innerWidth]")
            self.assertEqual((shown, sideways <= 0), (True, True), (width, scheme))
            time.sleep(0.4)                                                    # the menu has faded in
            b.screenshot(b.shots / f"access-pop-{width}-{scheme}.png")
            b.key("Escape", 27)
            b.wait("document.querySelector('#person-pop').hidden", "the person menu closed")
        self.assertEqual([p for p in b.problems if p not in expected], [])


class KeyFileTest(FactoryTestCase):
    """FR-ID1-AC-4: the provider's key file: every change on record, an unusable one closes the sign-in only."""

    def test_FR_ID1_AC_4_a_changed_key_file_is_on_record_and_a_broken_one_stops_sign_in_only(self):
        path = write_access(self.factory)
        keys = path.with_name("jwks.json")
        first = kaccess.load(self.factory, record=True, by="a test")
        self.assertEqual((first.keys_error, sorted(first.keys)), (None, ["test-key-1"]))
        write_json(keys, {"keys": [IDP.jwk(), ES.jwk()]})                   # IT rotates in a second key
        second = kaccess.load(self.factory, record=True, by="a test")
        keys.write_text('{"keys": [{"kty": "oct", "kid": "x", "k": "c2VjcmV0"}]}', encoding="utf-8")
        third = kaccess.load(self.factory, record=True, by="a test")
        self.assertIn("is a symmetric key", third.keys_error)
        changes = [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind("access_changed")]
        self.assertEqual([c["keys_sha256"] for c in changes], [first.keys_sha256, second.keys_sha256,
                                                               hashlib.sha256(keys.read_bytes()).hexdigest()])
        self.assertEqual({c["sha256"] for c in changes}, {first.sha256})        # the access file did not change
        self.assertIn("is a symmetric key", changes[-1]["keys_error"])
        sent = Message()
        sent["Authorization"] = f"Bearer {IDP.token('aino-sub')}"
        with self.assertRaises(kaccess.AccessBroken) as ctx:                     # the cockpit's sign-in is closed
            kaccess.from_proxy(third, sent)
        self.assertIn("nobody can sign in until IT fixes it", str(ctx.exception))
        self.assertIn("is a symmetric key", kaccess.describe(third))
        # the command line signs as the local user: it works on
        p = self.new()
        cid = Canon(p).card("change", "Show overdue loans first")["id"]
        with mock.patch("kernel.access.os_user", return_value="aino"), contextlib.redirect_stdout(io.StringIO()):
            code = main(["--home", str(self.factory.home), "decide", p.pid, cid, "accept", "--person", "Aino Example",
                         "--persona", "product_owner"])
        self.assertEqual(code, 0)


class AccessCheckTest(FactoryTestCase):
    """FR-ID1-AC-5: `rihmasto access check` and `rihmasto access keys`, read only."""

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), "access", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_FR_ID1_AC_5_access_check_shows_what_a_saved_token_signs_in_as_and_writes_nothing(self):
        code, out, _ = self.cli("check")
        self.assertEqual((code, json.loads(out)["mode"]), (0, "single_operator"))
        write_access(self.factory)
        good, forged = self.tmp / "token.txt", self.tmp / "forged.txt"
        good.write_text(IDP.token("aino-sub", groups=["rihmasto-ops"]) + "\n", encoding="utf-8")
        forged.write_text(Provider(ISSUER, AUDIENCE, seed=2).token("aino-sub"), encoding="utf-8")
        before = sorted(p.relative_to(self.factory.home) for p in self.factory.home.rglob("*"))
        code, out, _ = self.cli("check", "--token-file", str(good))
        report = json.loads(out)
        self.assertEqual(code, 0, report)
        self.assertEqual((report["token"]["identity"], report["token"]["name"]), (AINO, "Aino Example"))
        self.assertEqual({g["persona"] for g in report["token"]["grants"]}, {"business_owner", "product_owner",
                                                                             "operations"})
        self.assertEqual((report["sign_in"]["keys"], report["sign_in"]["algorithm"]), (["test-key-1"], "RS256"))
        self.assertIn("container", report["isolation"]["runner"])
        self.assertNotIn(good.read_text(encoding="utf-8").strip(), out)          # the token is never printed back
        code, out, _ = self.cli("check", "--token-file", str(forged))
        self.assertEqual(code, 2)
        self.assertIn("does not verify", json.loads(out)["token"]["refused"])
        self.assertEqual(sorted(p.relative_to(self.factory.home) for p in self.factory.home.rglob("*")), before)

    def test_FR_ID1_AC_5_access_keys_prints_a_jwks_from_pem_public_keys(self):
        files = []
        for provider in (IDP, ES):
            path = self.tmp / f"{provider.kid}.pem"
            path.write_text(provider.pem(), encoding="ascii")
            files.append(f"{provider.kid}={path}")
        code, out, err = self.cli("keys", *files)
        self.assertEqual(code, 0, err)
        jwks = json.loads(out)
        self.assertEqual(jwks, {"keys": [IDP.jwk(), ES.jwk()]})
        self.assertEqual(set(jv.parse_jwks(out.encode())), {IDP.kid, ES.kid})
        code, _, err = self.cli("keys", "no-equals-sign")
        self.assertEqual(code, 2)
        self.assertIn("is not <kid>=<file.pem>", err)


if __name__ == "__main__":
    unittest.main()
