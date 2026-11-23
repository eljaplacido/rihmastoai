"""FR-H10: the scope dynamic and agentic red teaming runs inside (kernel/redteam/scope.py).

A person with the `it` or `compliance` persona authorises targets until a date; `check` refuses,
before any request is sent, a target that is not on loopback, not deployed by the factory, or not
in an unexpired scope. A small server on loopback counts requests to show that nothing was sent.
"""

from __future__ import annotations

import datetime as dt
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from kernel.redteam.scope import (  # noqa: E402
    AUTHORISED,
    REFUSED,
    REVOKED,
    ScopeRefused,
    authorise,
    check,
    deployed,
    revoke,
    scopes,
)
from kernel.redteam.started import register  # noqa: E402
from kernel.roads import slot_path  # noqa: E402
from kernel.store import write_json  # noqa: E402


class _Counter(BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self) -> None:  # noqa: N802 - the http.server name
        type(self).hits += 1
        self.send_response(200)
        self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        return


def payloads(project: Any, kind: str) -> list[dict[str, Any]]:
    return [r["event"]["payload"] for r in project.ledger().of_kind(kind)]


class ScopeTestCase(FactoryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.project = self.new()
        # A loopback server the factory did NOT deploy: it must never receive a request from the red team.
        _Counter.hits = 0
        self.stray = ThreadingHTTPServer(("127.0.0.1", 0), _Counter)
        threading.Thread(target=self.stray.serve_forever, daemon=True).start()
        self.addCleanup(self.stray.server_close)
        self.addCleanup(self.stray.shutdown)
        self.stray_url = f"http://127.0.0.1:{self.stray.server_address[1]}"
        self.staging = self.deploy("staging", "current", 40101, release=3)
        self.twin = self.deploy("staging", "twin", 40102, release=3)
        self.demo = self.deploy("demo", "current", 40103, release=2)

    def deploy(self, env: str, slot: str, port: int, *, release: int, host: str = "127.0.0.1") -> str:
        """The slot state a paved road writes when it deploys (kernel/roads.py)."""
        base_url = f"http://{host}:{port}"
        write_json(slot_path(self.project, env, slot), {"road": "local", "kind": "local-process", "environment": env,
                                                        "slot": slot, "release": release, "base_url": base_url})
        return base_url

    def until(self, days: int = 7) -> str:
        return (self.clock.today() + dt.timedelta(days=days)).isoformat()


class AuthoriseTest(ScopeTestCase):
    def test_FR_H10_AC_6_only_a_person_with_the_it_or_compliance_persona_authorises_a_scope(self) -> None:
        p = self.project
        refused = [
            (["staging"], "factory", "it", "pre-release test", self.until()),
            (["staging"], "Aino", "developer", "pre-release test", self.until()),
            (["staging"], "Aino", "business_owner", "pre-release test", self.until()),
            (["staging"], "Aino", "it", "  ", self.until()),
            ([], "Aino", "it", "pre-release test", self.until()),
            (["staging"], "Aino", "it", "pre-release test", (self.clock.today() - dt.timedelta(days=1)).isoformat()),
            (["staging"], "Aino", "it", "pre-release test", self.until(days=40)),
            (["staging"], "Aino", "it", "pre-release test", "next week"),
            (["http://192.0.2.10:8080"], "Aino", "it", "pre-release test", self.until()),
            (["http://localhost:8080"], "Aino", "it", "pre-release test", self.until()),
            (["prod"], "Aino", "it", "pre-release test", self.until()),
            (["staging/blue"], "Aino", "it", "pre-release test", self.until()),
        ]
        for targets, person, persona, reason, expires in refused:
            with self.subTest(targets=targets, person=person, persona=persona, reason=reason, expires=expires), \
                    self.assertRaises(ScopeRefused):
                authorise(p, targets, person, persona, reason, expires)
        self.assertEqual(payloads(p, AUTHORISED), [], "nothing refused is recorded as a scope")

        first = authorise(p, ["staging", "embed"], "Aino", "it", "pre-release test of loans", self.until())
        self.assertEqual(first, {"scope": "RT-SCOPE-001", "targets": ["embed", "staging"], "person": "Aino",
                                 "persona": "it", "reason": "pre-release test of loans",
                                 "expires": f"{self.until()}T23:59:59Z", "at": self.clock.stamp()})
        second = authorise(p, [self.staging + "/items"], "Kaisa", "compliance", "audit sample",
                           dt.datetime(2026, 11, 30, 12, 0, tzinfo=dt.UTC))
        self.assertEqual((second["scope"], second["targets"], second["expires"]),
                         ("RT-SCOPE-002", ["http://127.0.0.1:40101"], "2026-11-30T12:00:00Z"))
        self.assertEqual(payloads(p, AUTHORISED), [first, second], "the ledger is where a scope lives")
        self.assertTrue(p.ledger().verify().intact)

    def test_FR_H10_AC_6_a_scope_is_revoked_by_the_same_people_and_ends_at_its_expiry(self) -> None:
        p = self.project
        s = authorise(p, ["demo"], "Aino", "it", "demo check", self.until(2))
        with self.assertRaises(ScopeRefused):
            revoke(p, s["scope"], person="Aino", persona="developer", reason="done")
        with self.assertRaises(ScopeRefused):
            revoke(p, s["scope"], person="Aino", persona="it", reason=" ")
        with self.assertRaises(KeyError):
            revoke(p, "RT-SCOPE-999", person="Kaisa", persona="compliance", reason="done")
        self.assertEqual([x["state"] for x in scopes(p)], ["active"])
        revoke(p, s["scope"], person="Kaisa", persona="compliance", reason="the test is over")
        self.assertEqual([x["state"] for x in scopes(p)], ["revoked"])
        self.assertEqual(payloads(p, REVOKED)[0]["person"], "Kaisa")
        later = authorise(p, ["demo"], "Aino", "it", "second round", self.until(1))
        self.clock.advance(days=3)
        self.assertEqual({x["scope"]: x["state"] for x in scopes(p)},
                         {s["scope"]: "revoked", later["scope"]: "expired"})
        self.assertEqual(scopes(p, active=True), [])


class CheckTest(ScopeTestCase):
    def assertRefused(self, target: str, why: str, **kw: Any) -> dict[str, Any]:
        before = len(payloads(self.project, REFUSED))
        with self.assertRaises(ScopeRefused) as caught:
            check(self.project, target, **kw)
        self.assertIn(why, str(caught.exception))
        recorded = payloads(self.project, REFUSED)
        self.assertEqual(len(recorded), before + 1, "every refusal is recorded")
        self.assertIn(why, recorded[-1]["reason"])
        return recorded[-1]

    def test_FR_H10_AC_7_a_target_in_an_unexpired_scope_on_a_deployed_loopback_address_is_permitted(self) -> None:
        p = self.project
        self.assertRefused(self.staging + "/items", "no unexpired scope names staging")
        authorise(p, ["staging"], "Aino", "it", "pre-release test", self.until())
        permit = check(p, self.staging + "/items?owner=x")
        self.assertEqual((permit.scope, permit.label, permit.environment, permit.slot, permit.release),
                         ("RT-SCOPE-001", "staging", "staging", "current", 3))
        self.assertEqual((permit.person, permit.persona, permit.base_url), ("Aino", "it", self.staging))
        self.assertEqual(permit.target, self.staging + "/items", "the query is not kept")
        self.assertEqual(check(p, self.twin).slot, "twin", "an environment's scope covers its twin")
        self.assertRefused(self.demo, "no unexpired scope names demo, demo/current")
        authorise(p, ["demo/current"], "Kaisa", "compliance", "demo walk", self.until(1))
        self.assertEqual(check(p, self.demo + "/").label, "demo/current")
        self.clock.advance(days=2)
        self.assertRefused(self.demo, "no unexpired scope", )
        self.assertEqual(check(p, self.staging).scope, "RT-SCOPE-001")
        revoke(p, "RT-SCOPE-001", person="Aino", persona="it", reason="release shipped")
        self.assertRefused(self.staging, "no unexpired scope")
        self.assertEqual(_Counter.hits, 0)

    def test_FR_H10_AC_7_anything_not_on_loopback_or_not_deployed_is_refused_before_any_request(self) -> None:
        p = self.project
        with self.assertRaisesRegex(ScopeRefused, "nothing the factory deployed runs at"):
            authorise(p, [self.stray_url], "Aino", "it", "the stray server", self.until())
        authorise(p, ["staging", "demo", "preview"], "Aino", "it", "everything we may", self.until())
        self.assertRefused("http://192.0.2.10:40101/", "is not on loopback")
        self.assertRefused("http://localhost:40101/", "is not on loopback")
        self.assertRefused("http://2130706433:40101/", "is not on loopback")
        self.assertRefused("http://127.1:40101/", "is not on loopback")
        self.assertRefused("ftp://127.0.0.1:40101/", "only http and https")
        self.assertRefused("not a url", "only http and https")
        leaky = "http://ops:hunter22@127.0.0.1:40101/x?token=abc"  # redteam: canary (must not reach the ledger)
        record = self.assertRefused(leaky, "user name or password")
        self.assertNotIn("hunter22", str(record))
        self.assertNotIn("token=abc", str(record))
        self.assertRefused("http://127.0.0.1@192.0.2.10:40101/", "user name or password")
        # On loopback and named in a scope, but nothing the factory deployed: the stray server.
        self.assertRefused(self.stray_url + "/admin", "is not a base_url the factory deployed or runs")
        self.assertRefused("http://127.0.0.1:40199/", "is not a base_url the factory deployed or runs")
        # A slot on another address is not reachable, whatever its environment's scope says.
        self.deploy("preview", "current", 40104, release=1, host="192.0.2.20")
        self.assertRefused("http://192.0.2.20:40104/", "is not on loopback")
        self.assertEqual(_Counter.hits, 0, "no request reached a server the factory did not deploy")

    def test_FR_H10_AC_7_a_surface_the_factory_runs_needs_its_own_scope_and_a_broken_ledger_authorises_nothing(
            self) -> None:
        from embed.server import make_server

        p = self.project
        srv = make_server(self.factory, 0)
        self.addCleanup(srv.server_close)
        started = register("embed", self.factory.home, server=srv)
        embed = started.base_url
        self.assertRefused(embed + "/e/E-001/messages", "not a base_url the factory deployed", running=None)
        self.assertRefused(embed + "/e/E-001/messages", "no unexpired scope names embed", running={"embed": started})
        authorise(p, ["embed"], "Kaisa", "compliance", "prompt injection round", self.until())
        self.assertEqual(check(p, embed + "/e/E-001/messages", running={"embed": started}).label, "embed")
        self.assertRefused(embed, "not one the factory started", running={"embed": embed})
        with self.assertRaises(ScopeRefused):
            check(p, embed, running={"cockpit": started})
        self.assertEqual([d["labels"] for d in deployed(p)],
                         [["demo", "demo/current"], ["staging", "staging/current"], ["staging", "staging/twin"]])
        authorise(p, ["staging"], "Aino", "it", "pre-release test", self.until())
        self.assertEqual(check(p, self.staging).scope, "RT-SCOPE-002")
        ledger = p.path("ledger.jsonl")
        lines = ledger.read_text(encoding="utf-8").splitlines(keepends=True)
        index = next(i for i, line in enumerate(lines) if AUTHORISED in line and "RT-SCOPE-002" in line)
        lines[index] = lines[index].replace("pre-release test", "pre-release tests")
        ledger.write_text("".join(lines), encoding="utf-8", newline="\n")
        self.assertRefused(self.staging, "the project's ledger does not verify")


if __name__ == "__main__":
    unittest.main()
