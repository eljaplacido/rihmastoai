"""FR-H10: the dynamic layer (kernel/redteam/dynamic.py) probes what the factory runs, inside a scope.

tests/fixtures/redteam/dynamic/vulnerable/app/server.py is a small product with one seeded defect
per dynamic rule, each on a line marked `seeded: <rule>`; .../clean/app/server.py is the same
product written safely. Both serve the interface in .../dynamic/spec.json on 127.0.0.1 (port 0),
and each counts the connections it accepts, so a refused run can be shown to have sent nothing.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import io
import json
import sys
import threading
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_redteam_static import SEED  # noqa: E402

from adapters.sarif import ingest  # noqa: E402
from kernel.redteam import client as client_module  # noqa: E402
from kernel.redteam import dynamic, static  # noqa: E402
from kernel.redteam.__main__ import main  # noqa: E402
from kernel.redteam.client import Answer  # noqa: E402
from kernel.redteam.contentprobes import header_gaps, leak  # noqa: E402
from kernel.redteam.probing import Route, Tally, routes_of  # noqa: E402
from kernel.redteam.protocolprobes import RATE_BODY, RATE_BURST, _cors_problem  # noqa: E402
from kernel.redteam.report import markdown, write_sarif  # noqa: E402
from kernel.redteam.rules import DYNAMIC_LAYERS, DYNAMIC_RULES, OWASP_2025, RULES, SEVERITY_LEVEL  # noqa: E402
from kernel.redteam.scope import REFUSED, ScopeRefused, authorise, revoke  # noqa: E402
from kernel.redteam.started import register  # noqa: E402
from kernel.roads import slot_path  # noqa: E402
from kernel.security import findings as security_findings  # noqa: E402
from kernel.security import latest, security_gate  # noqa: E402
from kernel.store import write_json  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "redteam"
DYNAMIC = FIXTURES / "dynamic"
SPEC = json.loads((DYNAMIC / "spec.json").read_text(encoding="utf-8"))

# What the vulnerable server must yield, (rule, route): one finding per seeded defect, nothing else.
EXPECTED = {
    ("RT-DYN-CSP", "/"), ("RT-DYN-NOSNIFF", "/"), ("RT-DYN-FRAME", "/"), ("RT-DYN-REFERRER", "/"),
    ("RT-DYN-LEAK", "/items/{id}"), ("RT-DYN-LEAK", "/items"),
    ("RT-DYN-TRAVERSAL", "/static/{name}"), ("RT-DYN-TRAVERSAL", "/files/{name}"),
    ("RT-DYN-REFLECT", "/search"),
    ("RT-DYN-METHOD", "/items/{id}"), ("RT-DYN-METHOD", "/"),
    ("RT-DYN-MALFORMED", "/items"), ("RT-DYN-OVERSIZE", "/items"),
    ("RT-DYN-CORS", "/"), ("RT-DYN-RATELIMIT", "/items"),
}


def load(kind: str) -> ModuleType:
    """A fixture server's module, loaded from its file under a name of its own."""
    path = DYNAMIC / kind / "app" / "server.py"
    spec = importlib.util.spec_from_file_location(f"redteam_dynamic_{kind}_server", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VULNERABLE, CLEAN = load("vulnerable"), load("clean")


def seeds(path: Path) -> dict[str, int]:
    out = {}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = SEED.search(line)
        for rid in (m.group(2).split() if m else []):
            out[rid] = n
    return out


def answer(status: int | None = 200, headers: dict[str, str] | None = None, body: str = "x", *,
           target: str = "/", error: str | None = None) -> Answer:
    return Answer("GET", target, "/", status, {k.lower(): v for k, v in (headers or {}).items()}, body, error)


class DynamicTestCase(FactoryTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.project = self.new()
        self.project.write("spec.json", SPEC)
        self.vulnerable = self.start(VULNERABLE)
        self.clean = self.start(CLEAN)
        self.deploy("staging", "current", self.vulnerable.url)
        self.deploy("demo", "current", self.clean.url)

    def start(self, module: ModuleType) -> Any:
        server = module.Server()
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def deploy(self, env: str, slot: str, base_url: str) -> None:
        """The slot state a paved road writes when it deploys (kernel/roads.py)."""
        write_json(slot_path(self.project, env, slot), {"road": "local", "kind": "local-process", "environment": env,
                                                        "slot": slot, "release": 1, "base_url": base_url})

    def allow(self, *targets: str, days: int = 7) -> dict[str, Any]:
        until = (self.clock.today() + dt.timedelta(days=days)).isoformat()
        return authorise(self.project, list(targets), "Aino", "it", "pre-release red team", until)

    def kinds(self, kind: str) -> list[dict[str, Any]]:
        return [r["event"]["payload"] for r in self.project.ledger().of_kind(kind)]


class RecallTest(DynamicTestCase):
    def test_FR_H10_AC_10_each_probe_catches_its_seeded_defect_in_the_vulnerable_server(self) -> None:
        self.allow("staging")
        report = dynamic.scan_environment(self.project, "staging")
        found = {(f.rule, f.path) for f in report.findings}
        self.assertEqual(found, EXPECTED, "every seed is caught, and nothing else is reported")
        self.assertEqual(len(report.findings), len(EXPECTED))
        self.assertEqual({f.rule for f in report.findings}, set(DYNAMIC_RULES),
                         "every dynamic rule has caught its seed")
        self.assertEqual(report.verdict, "failed")
        evidence = {(f.rule, f.path): f.evidence for f in report.findings}
        self.assertIn("plain traversal (../server.py)", evidence[("RT-DYN-TRAVERSAL", "/static/{name}")])
        self.assertIn("dot-encoded traversal (%2e%2e%2fserver.py)", evidence[("RT-DYN-TRAVERSAL", "/files/{name}")])
        self.assertIn("TRACE", evidence[("RT-DYN-METHOD", "/")])
        self.assertIn("PUT answered 200", evidence[("RT-DYN-METHOD", "/items/{id}")])
        self.assertIn("a stack trace", evidence[("RT-DYN-LEAK", "/items")])
        self.assertIn("with credentials", evidence[("RT-DYN-CORS", "/")])
        self.assertIn(f"{RATE_BURST} POST requests in a row", evidence[("RT-DYN-RATELIMIT", "/items")])
        self.assertEqual([c.layer for c in report.coverage], list(DYNAMIC_LAYERS))
        self.assertEqual({c.layer: c.state for c in report.coverage}, dict.fromkeys(DYNAMIC_LAYERS, "measured"))
        # The run is in the ledger with its scope and the requests it sent: one connection each.
        run = self.kinds(dynamic.RUN_RECORD)[-1]
        self.assertEqual((run["scope"], run["environment"], run["slot"], run["verdict"]),
                         ("RT-SCOPE-001", "staging", "current", "failed"))
        self.assertEqual(run["requests"], self.vulnerable.connections)
        self.assertEqual(self.clean.connections, 0, "nothing reached the deployment outside the run's target")

    def test_FR_H10_AC_10_every_dynamic_rule_has_a_seed_and_names_a_cwe_an_owasp_category_a_severity_and_a_fix(
            self) -> None:
        planted = seeds(DYNAMIC / "vulnerable" / "app" / "server.py")
        self.assertEqual(set(planted), set(DYNAMIC_RULES), "every dynamic rule has a seed, and every seed a rule")
        self.assertEqual(seeds(DYNAMIC / "clean" / "app" / "server.py"), {}, "the clean twin plants nothing")
        self.assertEqual(tuple(dynamic.PROBES), DYNAMIC_LAYERS, "every layer has its probe, in report order")
        self.assertFalse(set(DYNAMIC_RULES) & set(RULES), "the static catalogue is unchanged")
        for r in DYNAMIC_RULES.values():
            with self.subTest(rule=r.id):
                self.assertRegex(r.cwe, r"^CWE-\d+$")
                self.assertIn(r.owasp, OWASP_2025)
                self.assertEqual(r.level, SEVERITY_LEVEL[r.severity])
                self.assertIn(r.layer, DYNAMIC_LAYERS)
                self.assertTrue(r.title and r.fix)

    def test_FR_H10_AC_10_the_checks_catch_the_variants_of_each_defect(self) -> None:
        page = {"Content-Type": "text/html", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'"}
        self.assertEqual(header_gaps(answer(headers=page)), [])
        for drop, rule in (("Content-Security-Policy", "RT-DYN-CSP"), ("X-Content-Type-Options", "RT-DYN-NOSNIFF"),
                           ("Referrer-Policy", "RT-DYN-REFERRER")):
            with self.subTest(missing=drop):
                self.assertIn(rule, {g[0] for g in header_gaps(answer(headers={k: v for k, v in page.items()
                                                                               if k != drop}))})
        csp_only = page | {"Content-Security-Policy": "default-src 'self'"}
        self.assertEqual([g[0] for g in header_gaps(answer(headers=csp_only))], ["RT-DYN-FRAME"])
        self.assertEqual([g[0] for g in header_gaps(answer(headers=page | {"Referrer-Policy": "unsafe-url"}))],
                         ["RT-DYN-REFERRER"])
        untyped = {k: v for k, v in page.items() if k not in ("Content-Type", "Content-Security-Policy")}
        self.assertEqual([g[0] for g in header_gaps(answer(headers=untyped, body="<p>hi"))],
                         ["RT-DYN-CSP", "RT-DYN-FRAME"], "a page with no type may be sniffed as HTML")
        for body, kind in (('Traceback (most recent call last):\n  File "x.py", line 3', "a stack trace"),
                           ("at com.loans.Api.get(Api.java:42)", "a stack trace"),
                           ("at handler (/srv/app/index.js:10:5)", "a stack trace"),
                           ("goroutine 1 [running]:", "a stack trace"),
                           ("sqlite3.OperationalError: near \"'\": syntax error", "a database error"),
                           ("You have an error in your SQL syntax near ''", "a database error"),
                           ("could not open C:\\inetpub\\app\\views\\home.php", "a file path"),
                           ("failed in /home/deploy/app/routes.py", "a file path")):
            with self.subTest(leak=body):
                self.assertEqual(leak(answer(500, body=body))[0], kind)
        self.assertEqual(_cors_problem("http://rihmasto-probe.invalid", "true", "http://rihmasto-probe.invalid"),
                         "Access-Control-Allow-Origin echoes it, with credentials")
        self.assertEqual(_cors_problem("null", "true", "null"),
                         "Access-Control-Allow-Origin echoes it, with credentials")
        self.assertEqual(_cors_problem("*", "true", "http://rihmasto-probe.invalid"),
                         "Access-Control-Allow-Origin * with credentials")


class PrecisionTest(DynamicTestCase):
    def test_FR_H10_AC_11_the_clean_twin_yields_no_finding_and_every_layer_is_measured(self) -> None:
        self.allow("demo")
        report = dynamic.scan_environment(self.project, "demo")
        self.assertEqual([f"{f.rule} {f.path}: {f.evidence}" for f in report.findings], [])
        self.assertEqual({c.layer: c.state for c in report.coverage}, dict.fromkeys(DYNAMIC_LAYERS, "measured"),
                         [c.reason for c in report.coverage if c.state != "measured"])
        self.assertEqual(report.verdict, "passed")
        ratelimit = next(c for c in report.coverage if c.layer == "ratelimit")
        self.assertIn("was refused with 429", ratelimit.reason)
        self.assertEqual(self.vulnerable.connections, 0)

    def test_FR_H10_AC_11_near_misses_a_careless_check_would_report_stay_quiet(self) -> None:
        json_api = {"Content-Type": "application/json", "X-Content-Type-Options": "nosniff"}
        self.assertEqual(header_gaps(answer(headers=json_api, body='{"a": 1}')), [],
                         "the page headers apply to pages, not to JSON")
        self.assertEqual(header_gaps(answer(204, {}, "")), [], "an empty answer has no type to sniff")
        legacy = {"Content-Type": "text/html", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN",
                  "Content-Security-Policy": "default-src 'self'", "Referrer-Policy": "strict-origin-when-cross-origin"}
        self.assertEqual(header_gaps(answer(headers=legacy)), [], "X-Frame-Options alone protects from framing")
        for body, target in (('{"error": "no such file", "file": "/srv/app/main.py"}',
                              "/get?file=%2Fsrv%2Fapp%2Fmain.py"),
                             ('{"error": "not found", "path": "/files//home/deploy/app/x.py"}',
                              "/files/%2Fhome%2Fdeploy%2Fapp%2Fx.py"),
                             ("<p>No page at C:\\inetpub\\app\\x.php</p>", "/files/C:%5cinetpub%5capp%5cx.php"),
                             ('<p>Not found. <script src="/app/main.js"></script></p>', "/x"),
                             ("<p>See https://docs.example.com/app/errors.py</p>", "/x"),
                             ('{"error": "KeyError", "detail": "\'name\'"}', "/items"),
                             ("<p>Not found</p>", "/x")):
            with self.subTest(echo=body):
                self.assertIsNone(leak(answer(404, body=body, target=target)),
                                  "what the request sent, a page's script and a URL are not leaks")
        self.assertIsNone(leak(answer(200, body="Traceback (most recent call last)")), "only error pages are read")
        self.assertEqual(_cors_problem("*", "", "http://rihmasto-probe.invalid"), "",
                         "a public API may allow any origin")
        self.assertEqual(_cors_problem("http://rihmasto-probe.invalid", "", "http://rihmasto-probe.invalid"), "",
                         "echoing an origin without credentials exposes no more than *")
        self.assertEqual(_cors_problem("http://127.0.0.1:8080", "true", "http://rihmasto-probe.invalid"), "")
        self.assertEqual(routes_of([{"method": "GET", "path": "/a\r\nX-Injected: 1"}, {"method": "TRACE", "path": "/"},
                                    {"method": "get", "path": "/items/{id}"}, "not a row"]),
                         [Route("GET", "/items/{id}")], "a spec row cannot smuggle a header into a probe")


class ScopeTest(DynamicTestCase):
    def assertRefusedWithNothingSent(self, target: str, why: str, **kw: Any) -> None:
        before = len(self.kinds(REFUSED))
        with self.assertRaises(ScopeRefused) as caught:
            dynamic.scan(self.project, target, **kw)
        self.assertIn(why, str(caught.exception))
        self.assertEqual(len(self.kinds(REFUSED)), before + 1, "the refusal is recorded")
        self.assertEqual((self.vulnerable.connections, self.clean.connections), (0, 0), "not one connection was made")

    def test_FR_H10_AC_12_a_target_outside_the_scope_or_not_deployed_by_the_factory_is_refused_with_nothing_sent(
            self) -> None:
        stray = self.start(VULNERABLE)  # on loopback, but the factory did not deploy it
        self.assertRefusedWithNothingSent(self.vulnerable.url, "no unexpired scope names staging")
        with self.assertRaisesRegex(ScopeRefused, "nothing the factory deployed runs at"):
            self.allow(stray.url)
        self.allow("demo")
        self.assertRefusedWithNothingSent(self.vulnerable.url + "/items", "no unexpired scope names staging")
        self.assertRefusedWithNothingSent(stray.url, "is not a base_url the factory deployed or runs")
        self.assertRefusedWithNothingSent(self.vulnerable.url.replace("127.0.0.1", "localhost"), "is not on loopback")
        self.assertRefusedWithNothingSent("http://192.0.2.10:8080/", "is not on loopback")
        self.allow("staging", days=1)
        self.clock.advance(days=3)
        self.assertRefusedWithNothingSent(self.vulnerable.url, "no unexpired scope names staging")
        scope = self.allow("staging")
        revoke(self.project, scope["scope"], person="Kaisa", persona="compliance", reason="release postponed")
        self.assertRefusedWithNothingSent(self.vulnerable.url, "no unexpired scope names staging")
        self.assertEqual(stray.connections, 0, "the server the factory did not deploy received nothing")
        self.assertEqual(self.kinds(dynamic.RUN_RECORD), [], "a refused run is not a run")
        with self.assertRaises(LookupError):
            dynamic.scan_environment(self.project, "preview")
        with self.assertRaises(ValueError):
            dynamic.scan_environment(self.project, "../staging")

    def test_FR_H10_AC_12_a_surface_the_factory_runs_is_probed_only_inside_its_own_scope(self) -> None:
        from embed.server import make_server

        srv = make_server(self.factory, 0)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        started = register("embed", self.factory.home, server=srv)
        embed = started.base_url
        self.allow("demo", "staging")
        self.assertRefusedWithNothingSent(embed, "is not a base_url the factory deployed or runs")
        self.assertRefusedWithNothingSent(embed, "no unexpired scope names embed", running={"embed": started})
        self.allow("embed")
        # A caller cannot declare a surface's address: the clean product's server is not the factory's embed.
        self.assertRefusedWithNothingSent(self.clean.url, "not one the factory started",
                                          running={"embed": self.clean.url})
        report = dynamic.scan(self.project, embed, running={"embed": started}, interface=[])
        self.assertEqual(report.target, f"embed ({embed})")
        self.assertGreater(self.kinds(dynamic.RUN_RECORD)[-1]["requests"], 0)
        states = {c.layer: c.state for c in report.coverage}
        self.assertEqual({states["bodies"], states["ratelimit"]}, {"not measured"},
                         "without an interface the run says what it could not reach")
        self.assertTrue(all(c.applicable for c in report.coverage), "an unknown write route is not an absent one")
        self.assertNotEqual(report.verdict, "passed")

    def test_FR_H10_AC_12_every_request_is_checked_against_the_scope_before_it_is_sent(self) -> None:
        self.allow("demo")
        real = client_module.check
        with mock.patch.object(client_module, "check", side_effect=real) as spy:
            dynamic.scan_environment(self.project, "demo")
        self.assertEqual(spy.call_count, 1 + self.clean.connections, "the target once, then every request")

    def test_FR_H10_AC_12_a_scope_that_ends_mid_run_stops_the_run_and_the_rest_is_not_measured(self) -> None:
        self.allow("demo", days=1)
        real, calls, allowed = client_module.check, [0], 9

        def expiring(*args: Any, **kw: Any) -> Any:
            calls[0] += 1
            if calls[0] == allowed + 2:  # the target's check, then `allowed` requests
                self.clock.advance(days=2)
            return real(*args, **kw)

        with mock.patch.object(client_module, "check", side_effect=expiring):
            report = dynamic.scan_environment(self.project, "demo")
        self.assertEqual(self.clean.connections, allowed)
        states = {c.layer: c.state for c in report.coverage}
        self.assertEqual(states["headers"], "measured")
        self.assertEqual(states["errors"], "partial")
        self.assertEqual({states[layer] for layer in DYNAMIC_LAYERS[2:]}, {"not measured"})
        stopped = next(c for c in report.coverage if c.layer == "cors")
        self.assertIn("the scope refused a request mid-run", stopped.reason)
        self.assertEqual(report.verdict, "not measured", "what was not probed is never passed")
        self.assertIn("no unexpired scope names demo", self.kinds(REFUSED)[-1]["reason"])
        self.assertTrue(self.kinds(dynamic.RUN_RECORD)[-1]["halted"])


class BudgetTest(DynamicTestCase):
    def test_FR_H10_AC_13_a_run_never_sends_more_than_its_budget_and_what_it_did_not_reach_is_not_measured(
            self) -> None:
        self.allow("demo")
        report = dynamic.scan_environment(self.project, "demo", budget=20)
        self.assertEqual(self.clean.connections, 20)
        states = {c.layer: c.state for c in report.coverage}
        self.assertEqual((states["headers"], states["errors"], states["traversal"]),
                         ("measured", "measured", "partial"))
        self.assertEqual({states[layer] for layer in DYNAMIC_LAYERS[3:]}, {"not measured"})
        traversal = next(c for c in report.coverage if c.layer == "traversal")
        self.assertIn("budget of 20 requests was spent", traversal.reason)
        self.assertEqual(report.verdict, "not measured")
        self.assertIn("**Verdict: not measured.**", markdown(report))
        self.assertIn("| Layer | State | Requests |", markdown(report))
        run = self.kinds(dynamic.RUN_RECORD)[-1]
        self.assertEqual((run["requests"], run["budget"], run["verdict"]), (20, 20, "not measured"))
        for budget in (0, 1001):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                dynamic.scan_environment(self.project, "demo", budget=budget)
        self.assertEqual(self.clean.connections, 20, "a budget out of bounds sends nothing")

    def test_FR_H10_AC_13_the_rate_limit_probe_sends_a_small_fixed_number_of_requests(self) -> None:
        self.allow("staging", "demo")
        calls: list[tuple[str, str]] = []
        real = client_module.Client.request

        def spy(client: Any, method: str, target: str, **kw: Any) -> Answer:
            calls.append((method, kw["route"], kw.get("body") or b""))
            return real(client, method, target, **kw)

        with mock.patch.object(client_module.Client, "request", spy):
            dynamic.scan_environment(self.project, "staging")
            open_writes = [c for c in calls if c == ("POST", "/items", RATE_BODY)]
            calls.clear()
            dynamic.scan_environment(self.project, "demo")
            limited_writes = [c for c in calls if c == ("POST", "/items", RATE_BODY)]
        self.assertEqual(len(open_writes), RATE_BURST, "a server with no limit gets the whole burst and no more")
        self.assertLess(len(limited_writes), RATE_BURST, "the probe stops at the first 429")
        self.assertLessEqual(RATE_BURST, 12)
        tally = Tally("x")
        tally.count(answer(429))
        self.assertEqual(tally.coverage("ok").state, "not measured", "a 429 before a judgement is not a judgement")


class ReportTest(DynamicTestCase):
    def test_FR_H10_AC_14_the_dynamic_sarif_is_a_tool_of_its_own_beside_the_static_scan(self) -> None:
        self.allow("staging")
        first = dynamic.scan_environment(self.project, "staging")
        out = self.tmp / "dynamic.sarif"
        write_sarif(out, first)
        record = ingest(self.project, out, person="Kaisa", persona="compliance")
        self.assertEqual(record["tools"][0]["name"], "Rihmasto red team (dynamic)")
        self.assertEqual({(f["rule"], f["location"]["uri"]) for f in record["findings"]}, EXPECTED)
        self.assertEqual({f["rule"]: f["cwe"] for f in record["findings"]},
                         {r.id: [r.cwe] for r in DYNAMIC_RULES.values()})
        static_out = self.tmp / "static.sarif"
        write_sarif(static_out, static.scan([FIXTURES / "clean_app"], which=lambda tool: None))
        ingest(self.project, static_out)
        self.assertEqual(sorted(k[0] for k in latest(self.project)),
                         ["Rihmasto red team (dynamic)", "Rihmasto red team (static)"])
        self.assertEqual(security_gate(self.project)["verdict"], "failed", "the clean static scan hides nothing")
        second = self.tmp / "again.sarif"
        write_sarif(second, dynamic.scan_environment(self.project, "staging"))
        before = {f["fingerprint"] for f in record["findings"]}
        self.assertEqual({f["fingerprint"] for f in ingest(self.project, second)["findings"]}, before,
                         "a finding keeps its fingerprint from run to run, so a person's acceptance follows it")
        self.assertEqual(len([f for f in security_findings(self.project) if f["rule"] != "RT-CANARY"]), len(EXPECTED),
                         "the clean static scan adds only its planted canary, as a note to review")

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("kernel.redteam.__main__.Factory", lambda home: self.factory), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["dynamic", *argv])
        return code, out.getvalue(), err.getvalue()

    def test_FR_H10_AC_14_python_m_kernel_redteam_dynamic_prints_the_summary_and_exits_by_its_verdict(self) -> None:
        pid = self.project.pid
        code, out, err = self.run_cli(pid, "--env", "staging")
        self.assertEqual((code, err), (3, "redteam: refused, nothing was sent: no unexpired scope names staging, "
                                           f"staging/current ({self.vulnerable.url})\n"))
        self.assertEqual(self.vulnerable.connections, 0)
        self.allow("staging", "demo")
        sarif, summary = self.tmp / "out" / "dyn.sarif", self.tmp / "out" / "dyn.md"
        code, out, _ = self.run_cli(pid, "--env", "staging", "--sarif", str(sarif), "--markdown", str(summary))
        self.assertEqual(code, 1)
        self.assertIn("# Red team: dynamic scan of staging/current", out)
        self.assertIn("**Verdict: failed.**", out)
        self.assertEqual(json.loads(sarif.read_text(encoding="utf-8"))["runs"][0]["tool"]["driver"]["name"],
                         "Rihmasto red team (dynamic)")
        self.assertIn("RT-DYN-TRAVERSAL", summary.read_text(encoding="utf-8"))
        code, out, _ = self.run_cli(pid, "--env", "demo", "--json")
        self.assertEqual((code, json.loads(out)["verdict"]), (0, "passed"))
        self.assertEqual(self.run_cli(pid, "--env", "demo", "--budget", "3")[0], 4)
        self.assertEqual(self.run_cli("no-such-project", "--env", "demo")[0], 2)
        self.assertEqual(self.run_cli(pid, "--env", "preview")[0], 2)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as usage:
            main(["dynamic", pid, "--env", "prod"])
        self.assertEqual(usage.exception.code, 2)
        listed = io.StringIO()
        with contextlib.redirect_stdout(listed):
            self.assertEqual(main(["rules", "--dynamic"]), 0)
        self.assertEqual(len(listed.getvalue().strip().splitlines()), len(DYNAMIC_RULES))


if __name__ == "__main__":
    unittest.main()
