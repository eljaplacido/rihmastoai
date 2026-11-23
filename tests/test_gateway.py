"""The capability gateway (FR-Y1): the real server on a free loopback port, against fake OpenAI-compatible
upstreams on 127.0.0.1. A "cloud" upstream is declared https in the config, as it must be; the test's
caller sends its calls to a local fake instead, so nothing leaves the machine."""

import contextlib
import dataclasses
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from gateway.audit import AuditLog
from gateway.config import ConfigError, Upstream, completions_url, parse_config
from gateway.packs import check as check_pack
from gateway.packs import workloads_from_pack
from gateway.router import Gateway
from gateway.server import main as gateway_main
from gateway.server import make_server, start_drainer
from gateway.upstream import UpstreamResult, call_upstream
from kernel.ledger import verify

KEY_ENV = "RIHMA_TEST_GATEWAY_CLOUD_KEY"
KEY = "sk-test-NEVER-LOG-THIS-KEY"
PROMPT = "PROMPT-TEXT-about-payroll"
ANSWER = "ANSWER-TEXT"


class FakeUpstream:
    """An OpenAI-compatible upstream that answers as told and remembers what it was sent."""

    def __init__(self, name: str) -> None:
        self.name, self.status, self.received = name, 200, []
        self.hold: threading.Event | None = None
        self.arrived = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                outer.received.append({"headers": dict(self.headers), "body": body, "path": self.path})
                outer.arrived.set()
                if outer.hold is not None:
                    outer.hold.wait(10)
                outer.answer(self, body)

            def do_GET(self):                                                     # what a followed redirect sends
                outer.received.append({"headers": dict(self.headers), "body": None, "path": self.path})
                self.send_response(405)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, args=(0.05,), daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/v1"

    def answer(self, handler: BaseHTTPRequestHandler, body: dict) -> None:
        if isinstance(self.status, str) and self.status.startswith("http://"):
            handler.send_response(302)                                            # a redirect to elsewhere
            handler.send_header("Location", self.status)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        if self.status == "garbage":
            status, raw = 200, b"<html>not an answer</html>"
        elif self.status != 200:
            status, raw = self.status, b'{"error": "down"}'
        else:
            status, raw = 200, json.dumps({
                "id": "chatcmpl-1", "object": "chat.completion", "model": body["model"],
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": f"{ANSWER} from {self.name}"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(raw)))
        handler.end_headers()
        handler.wfile.write(raw)

    def close(self) -> None:
        if self.hold is not None:
            self.hold.set()
        self.srv.shutdown()
        self.srv.server_close()


class GatewayCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rihma-gateway-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.a, self.b, self.small, self.cloud = (FakeUpstream(n) for n in ("gpu-a", "gpu-b", "small", "cloud"))
        for fake in (self.a, self.b, self.small, self.cloud):
            self.addCleanup(fake.close)
        self.now = [1000.0]
        self.gw: Gateway | None = None

    def raw(self, mode: str = "air-gapped", cloud_max: str = "public", capture: bool = False) -> dict:
        return {
            "format": "rihma.gateway.v1",
            "site": {"mode": mode, "cloud_max_data_class": cloud_max},
            "upstreams": {
                "gpu-a": {"url": self.a.url},
                "gpu-b": {"url": self.b.url + "/chat/completions"},
                "small": {"url": self.small.url, "timeout_s": 5},
                "cloud": {"url": "https://cloud.example/v1", "cloud": True, "api_key_env": KEY_ENV},
            },
            "workloads": {
                "dev-assistant": {
                    "class": "interactive", "data_class": "internal", "description": "coding help in the editor",
                    "ladder": {"L1": [{"upstream": "gpu-a", "model": "big-coder"},
                                      {"upstream": "gpu-b", "model": "big-coder"}],
                               "L2": [{"upstream": "small", "model": "small-coder"}],
                               "L3": [{"upstream": "cloud", "model": "cloud-coder"}]}},
                "classify": {
                    "class": "batch", "data_class": "public", "rate": {"per_minute": 1, "burst": 2},
                    "ladder": {"L1": [{"upstream": "gpu-b", "model": "classifier-8b"}], "L4": "defer"}},
            },
            "quotas": {"concurrency": {"interactive": 4, "batch": 1}},
            "audit": {"path": "audit/gateway.jsonl", "content_capture": capture},
            "defer": {"max_attempts": 2, "retry_s": 5},
        }

    def route(self, upstream: Upstream, model: str, body: dict, env) -> UpstreamResult:
        """The real upstream call; a cloud upstream's call goes to the local fake instead."""
        if upstream.cloud:
            upstream = dataclasses.replace(upstream, url=completions_url(self.cloud.url))
        return call_upstream(upstream, model, body, env)

    def start(self, raw: dict, env=None, verbose: bool = False) -> Gateway:
        self.gw = Gateway(parse_config(raw, self.tmp), env=env if env is not None else {}, clock=lambda: self.now[0],
                          call=self.route)
        srv = make_server(self.gw, 0, verbose=verbose)
        threading.Thread(target=srv.serve_forever, args=(0.05,), daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.base = f"http://127.0.0.1:{srv.server_address[1]}"
        return self.gw

    def call(self, method: str, path: str, body=None, headers=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, dict(r.headers), json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, dict(e.headers), json.loads(e.read())

    def post(self, workload: str, headers=None, **extra):
        body = {"model": workload, "messages": [{"role": "user", "content": PROMPT}], **extra}
        return self.call("POST", "/v1/chat/completions", body, headers)

    def audit(self) -> list[dict]:
        return [r["event"]["payload"] for r in self.gw.audit.records()]


class RoutingTest(GatewayCase):
    def test_FR_Y1_AC_1_a_client_names_a_workload_and_the_gateway_sends_the_workloads_model(self):
        self.start(self.raw())
        status, headers, out = self.post("dev-assistant", data_class="internal")
        self.assertEqual(status, 200, out)
        self.assertEqual(out["choices"][0]["message"]["content"], f"{ANSWER} from gpu-a")
        self.assertEqual(self.a.received[0]["body"]["model"], "big-coder")       # the model, not the workload
        self.assertNotIn("data_class", self.a.received[0]["body"])               # the gateway's own field stays
        self.assertEqual(self.a.received[0]["path"], "/v1/chat/completions")
        self.assertEqual((out["gateway"]["workload"], out["gateway"]["level"], out["gateway"]["degraded"]),
                         ("dev-assistant", "L1", False))
        self.assertEqual((headers["X-Gateway-Level"], headers["X-Gateway-Degraded"]), ("L1", "false"))
        status, _, out = self.post("classify")
        self.assertEqual((status, out["gateway"]["upstream"]), (200, "gpu-b"))
        self.assertEqual(self.b.received[0]["body"]["model"], "classifier-8b")
        self.assertEqual(len(self.a.received), 1)
        status, _, health = self.call("GET", "/health")
        self.assertEqual((status, health["site_mode"], health["classes"]["batch"]["limit"]), (200, "air-gapped", 1))
        status, _, models = self.call("GET", "/v1/models")
        self.assertEqual(status, 200)
        self.assertEqual({m["id"]: m["workload_class"] for m in models["data"]},
                         {"dev-assistant": "interactive", "classify": "batch"})
        self.assertEqual(next(m for m in models["data"] if m["id"] == "classify")["levels"], ["L1", "L4"])
        self.assertNotIn("big-coder", json.dumps(models))                         # workloads, not models
        status, _, out = self.post("gpt-4o")
        self.assertEqual((status, out["error"]["code"]), (404, "model_not_found"))
        status, _, out = self.post("dev-assistant", stream=True)
        self.assertEqual(status, 400)
        self.assertIn("stream", out["error"]["message"])

    def test_FR_Y1_AC_1_when_L1_fails_the_next_upstream_answers_then_a_smaller_model_flagged_degraded(self):
        self.start(self.raw())
        self.a.status = "garbage"                                                 # a 200 that is no answer
        status, headers, out = self.post("dev-assistant")
        self.assertEqual((status, out["gateway"]["level"], out["gateway"]["upstream"]), (200, "L1", "gpu-b"))
        self.assertEqual(headers["X-Gateway-Degraded"], "false")
        self.a.status, self.b.status = 503, 500
        status, headers, out = self.post("dev-assistant")
        self.assertEqual(status, 200, out)
        self.assertEqual((out["gateway"]["level"], out["gateway"]["model"]), ("L2", "small-coder"))
        self.assertTrue(out["gateway"]["degraded"])
        self.assertIn("fallback", out["gateway"]["degraded_reason"])
        self.assertEqual((headers["X-Gateway-Level"], headers["X-Gateway-Degraded"]), ("L2", "true"))
        last = self.audit()[-1]
        self.assertEqual([(t["level"], t["upstream"], t["outcome"]) for t in last["attempts"]],
                         [("L1", "gpu-a", "http 503"), ("L1", "gpu-b", "http 500"), ("L2", "small", "answered")])
        self.assertTrue(last["degraded"])
        self.assertEqual(self.audit()[0]["attempts"][0]["outcome"], "answer is not JSON")

    def test_FR_Y1_AC_1_an_air_gapped_site_never_reaches_a_cloud_upstream(self):
        self.start(self.raw(mode="air-gapped"), env={KEY_ENV: KEY})
        self.a.status = self.b.status = self.small.status = 503
        status, _, out = self.post("dev-assistant", data_class="public")
        self.assertEqual((status, out["error"]["code"]), (503, "no_upstream"))
        self.assertEqual(self.cloud.received, [])
        self.assertEqual(out["error"]["skipped"], [{"level": "L3", "upstream": "cloud", "model": "cloud-coder",
                                                    "reason": "the site is air-gapped"}])
        self.assertEqual(self.audit()[-1]["status"], "failed")

    def test_FR_Y1_AC_1_a_connected_site_uses_L3_only_for_data_allowed_to_leave_it(self):
        self.a.status = self.b.status = self.small.status = 503
        self.start(self.raw(mode="connected", cloud_max="public"), env={KEY_ENV: KEY})
        status, _, out = self.post("dev-assistant", data_class="public")          # cannot go below the floor
        self.assertEqual(status, 503)
        self.assertIn("internal data may not leave the site", out["error"]["skipped"][0]["reason"])
        self.assertEqual(self.audit()[-1]["data_class"], "internal")
        self.assertEqual(self.cloud.received, [])
        self.start(self.raw(mode="connected", cloud_max="internal"), env={KEY_ENV: KEY})
        status, headers, out = self.post("dev-assistant")
        self.assertEqual((status, out["gateway"]["level"], headers["X-Gateway-Level"]), (200, "L3", "L3"))
        self.assertEqual(self.cloud.received[0]["body"]["model"], "cloud-coder")
        status, _, out = self.post("dev-assistant", headers={"X-Data-Class": "confidential"})
        self.assertEqual(status, 503)
        self.assertEqual(len(self.cloud.received), 1)
        status, _, out = self.post("dev-assistant", data_class="top-secret")
        self.assertEqual((status, out["error"]["code"]), (400, "invalid_data_class"))

    def test_FR_Y1_AC_1_when_nothing_may_answer_L4_queues_the_request_with_no_answer_yet(self):
        gw = self.start(self.raw())
        self.b.status = 503
        status, headers, out = self.post("classify")
        self.assertEqual(status, 202, out)
        self.assertEqual((out["status"], out["answer"]), ("queued", None))
        self.assertTrue(out["message"].startswith("no answer yet"))
        self.assertEqual(headers["X-Gateway-Level"], "L4")
        self.assertEqual(headers["Location"], f"/v1/deferred/{out['id']}")
        status, _, waiting = self.call("GET", headers["Location"])
        self.assertEqual((status, waiting["status"]), (202, "queued"))
        self.assertEqual(gw.drain(), 0)                                           # still down: one try used
        self.b.status = 200
        self.assertEqual(gw.drain(), 1)
        status, headers, done = self.call("GET", f"/v1/deferred/{out['id']}")
        self.assertEqual((status, done["gateway"]["level"], headers["X-Gateway-Level"]), (200, "L1", "L1"))
        self.assertIn(ANSWER, done["choices"][0]["message"]["content"])
        self.assertEqual(self.call("GET", f"/v1/deferred/{out['id']}")[0], 404)  # handed over once
        self.assertEqual([p["status"] for p in self.audit()], ["deferred", "answered"])
        self.assertEqual(self.audit()[1]["deferred_id"], out["id"])
        self.b.status = 503
        _, _, again = self.post("classify")
        gw.drain()
        gw.drain()
        status, _, gave_up = self.call("GET", f"/v1/deferred/{again['id']}")
        self.assertEqual((status, gave_up["error"]["code"]), (503, "deferred_gave_up"))
        self.assertEqual(self.audit()[-1]["status"], "failed")

    def test_FR_Y1_AC_1_the_server_retries_the_queue_on_its_own(self):
        raw = self.raw()
        raw["defer"]["retry_s"] = 0.1
        gw = self.start(raw)
        self.b.status = 503
        _, _, out = self.post("classify")
        stop = start_drainer(gw)
        self.addCleanup(stop.set)
        self.b.status = 200
        for _ in range(100):
            status, _, done = self.call("GET", f"/v1/deferred/{out['id']}")
            if status == 200:
                break
            stop.wait(0.05)
        self.assertEqual((status, done["gateway"]["workload"]), (200, "classify"))

    def test_FR_Y1_AC_1_the_gateway_listens_on_loopback_unless_behind_a_proxy(self):
        gw = Gateway(parse_config(self.raw(), self.tmp), env={})
        for host in ("0.0.0.0", "192.0.2.10"):
            with self.assertRaises(ValueError):
                make_server(gw, 0, host=host)

    def test_FR_Y1_AC_1_a_config_is_refused_where_it_is_wrong(self):
        def broken(change) -> str:
            raw = self.raw()
            change(raw)
            with self.assertRaises(ConfigError) as caught:
                parse_config(raw, self.tmp)
            return str(caught.exception)

        wl = "workloads"
        local_l3 = [{"upstream": "gpu-a", "model": "m"}]
        self.assertIn("L3", broken(lambda r: r[wl]["classify"]["ladder"].update(L3=local_l3)))
        self.assertIn("upstream", broken(lambda r: r[wl]["classify"]["ladder"]["L1"][0].update(upstream="nowhere")))
        self.assertIn("class", broken(lambda r: r[wl]["classify"].update({"class": "realtime"})))
        self.assertIn("https", broken(lambda r: r["upstreams"]["cloud"].update(url="http://cloud.example/v1")))
        self.assertIn("L4", broken(lambda r: r[wl]["classify"]["ladder"].update(L4="maybe")))
        self.assertIn("site.mode", broken(lambda r: r["site"].update(mode="sometimes")))
        self.assertIn("L1", broken(lambda r: r[wl]["classify"].update(ladder={"L2": []})))
        self.assertEqual(parse_config({"upstreams": {"u": {"url": "http://127.0.0.1:1/v1"}},
                                       "workloads": {"w": {"class": "batch", "ladder": {"L1": [
                                           {"upstream": "u", "model": "m"}]}}}}).site_mode, "air-gapped")

    def test_FR_Y1_AC_1_a_packs_declared_workloads_become_gateway_workloads(self):
        pack = {"format": "rihma.capability-pack.v1", "pack": "P-001", "version": "1.2.0",
                "runtime": {"declared": True, "workloads": [
                    {"name": "triage", "class": "batch", "data_class": "internal", "model": "classifier-8b"}]}}
        raw = self.raw()
        entries = workloads_from_pack(pack, "gpu-b")
        self.assertEqual(entries["triage"]["ladder"], {"L1": [{"upstream": "gpu-b", "model": "classifier-8b"}]})
        raw["workloads"].update(entries)
        config = parse_config(raw, self.tmp)
        self.assertEqual(config.workloads["triage"].workload_class, "batch")
        self.assertEqual(check_pack(config, pack), [])
        raw["workloads"]["triage"]["ladder"]["L1"][0]["model"] = "another-model"
        drift = check_pack(parse_config(raw, self.tmp), pack)
        self.assertEqual(len(drift), 1)
        self.assertIn("accepted with classifier-8b", drift[0])
        today = {"runtime": {"declared": False, "note": "the product template does not declare runtime models yet"}}
        self.assertEqual(workloads_from_pack(today, "gpu-b"), {})
        (self.tmp / "gateway.json").write_text(json.dumps(raw), encoding="utf-8")
        (self.tmp / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = gateway_main(["--config", str(self.tmp / "gateway.json"),
                                 "--check-pack", str(self.tmp / "pack.json")])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["declared"], 1)


class QuotaAndAuditTest(GatewayCase):
    def test_FR_Y1_AC_2_batch_at_its_concurrency_limit_is_held_back_while_interactive_passes(self):
        self.start(self.raw())
        self.b.hold = threading.Event()
        first = {}
        worker = threading.Thread(target=lambda: first.setdefault("reply", self.post("classify")))
        worker.start()
        self.assertTrue(self.b.arrived.wait(10))                                  # batch's one slot is taken
        status, headers, out = self.post("classify")
        self.assertEqual((status, out["error"]["code"]), (429, "concurrency_limited"))
        self.assertIn("Retry-After", headers)
        status, _, out = self.post("dev-assistant")                               # interactive still passes
        self.assertEqual((status, out["gateway"]["upstream"]), (200, "gpu-a"))
        self.b.hold.set()
        worker.join(10)
        self.assertEqual(first["reply"][0], 200)
        self.assertEqual(self.gw.health()["classes"]["batch"], {"in_flight": 0, "limit": 1})

    def test_FR_Y1_AC_2_a_workloads_token_bucket_holds_it_back_and_refills_with_time(self):
        self.start(self.raw())
        self.assertEqual([self.post("classify")[0] for _ in range(2)], [200, 200])
        status, headers, out = self.post("classify")
        self.assertEqual((status, out["error"]["code"], headers["Retry-After"]), (429, "rate_limited", "60"))
        self.assertEqual(self.post("dev-assistant")[0], 200)                      # another workload's bucket
        self.now[0] += 60
        self.assertEqual(self.post("classify")[0], 200)

    def test_FR_Y1_AC_2_every_request_is_one_record_in_a_hash_chained_audit_with_no_content(self):
        gw = self.start(self.raw())
        self.post("dev-assistant")                                                # answered
        self.post("no-such-workload")                                             # refused
        self.b.status = 503
        self.post("classify")                                                     # deferred
        self.post("classify")                                                     # concurrency is free: deferred
        self.post("classify")                                                     # rate limited: refused
        self.a.status = self.small.status = 503
        self.post("dev-assistant")                                                # failed
        req = urllib.request.Request(self.base + "/v1/chat/completions", data=b"not json", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as unreadable:              # refused, unread
            urllib.request.urlopen(req, timeout=10)
        unreadable.exception.close()
        self.assertEqual(unreadable.exception.code, 400)
        records = gw.audit.records()
        self.assertEqual(len(records), 7)
        self.assertTrue(verify(records).intact)
        self.assertEqual({r["event"]["kind"] for r in records}, {"gateway_request"})
        self.assertEqual([r["event"]["payload"]["status"] for r in records],
                         ["answered", "refused", "deferred", "deferred", "refused", "failed", "refused"])
        first = records[0]["event"]["payload"]
        self.assertEqual((first["workload"], first["level"], first["upstream"], first["model"]),
                         ("dev-assistant", "L1", "gpu-a", "big-coder"))
        self.assertEqual(first["tokens"], {"prompt": 7, "completion": 3, "total": 10})
        self.assertIsInstance(first["latency_ms"], float)
        self.assertIn("at", records[0]["event"])
        text = gw.audit.path.read_text(encoding="utf-8")
        self.assertNotIn(PROMPT, text)
        self.assertNotIn(ANSWER, text)
        again = AuditLog(gw.audit.path)                                           # a restart continues the chain
        again.record({"workload": "dev-assistant", "status": "refused"})
        self.assertEqual(again.records()[-1]["seq"], 7)
        self.assertTrue(again.verify().intact)
        with contextlib.redirect_stdout(io.StringIO()):
            (self.tmp / "gateway.json").write_text(json.dumps(self.raw()), encoding="utf-8")
            self.assertEqual(gateway_main(["--config", str(self.tmp / "gateway.json"), "--verify-audit"]), 0)
        lines = text.splitlines()
        lines[2] = lines[2].replace('"deferred"', '"answered"')
        gw.audit.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertEqual(verify(gw.audit.records()).broken_seq, 2)

    def test_FR_Y1_AC_2_content_enters_the_audit_only_when_content_capture_is_set(self):
        gw = self.start(self.raw(capture=True))
        self.post("dev-assistant")
        payload = gw.audit.records()[-1]["event"]["payload"]
        self.assertEqual(payload["content"]["messages"][0]["content"], PROMPT)
        self.assertIn(ANSWER, json.dumps(payload["content"]["choices"]))

    def test_FR_Y1_AC_2_an_upstream_key_comes_from_the_environment_and_is_never_stored_or_logged(self):
        self.a.status = self.b.status = self.small.status = 503
        raw = self.raw(mode="connected", cloud_max="internal")
        with mock.patch.dict(os.environ, {KEY_ENV: KEY}):
            gw = Gateway(parse_config(raw, self.tmp), clock=lambda: self.now[0], call=self.route)
            srv = make_server(gw, 0, verbose=True)
            threading.Thread(target=srv.serve_forever, args=(0.05,), daemon=True).start()
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
            self.base, self.gw = f"http://127.0.0.1:{srv.server_address[1]}", gw
            with contextlib.redirect_stderr(io.StringIO()) as log:
                status, _, out = self.post("dev-assistant")
        self.assertEqual((status, out["gateway"]["level"]), (200, "L3"), out)
        self.assertEqual(self.cloud.received[0]["headers"]["Authorization"], f"Bearer {KEY}")
        self.assertIn("POST /v1/chat/completions", log.getvalue())
        for where in (log.getvalue(), gw.audit.path.read_text(encoding="utf-8"), json.dumps(out)):
            self.assertNotIn(KEY, where)
        with mock.patch.dict(os.environ, {}), contextlib.redirect_stderr(io.StringIO()):
            os.environ.pop(KEY_ENV, None)
            status, _, out = self.post("dev-assistant")
        self.assertEqual(status, 503)
        self.assertEqual(out["error"]["attempts"][-1]["outcome"], f"no key: {KEY_ENV} is not set")
        self.assertEqual(len(self.cloud.received), 1)
        elsewhere = FakeUpstream("elsewhere")
        self.addCleanup(elsewhere.close)
        self.cloud.status = elsewhere.url + "/chat/completions"                   # the key never follows a redirect
        with mock.patch.dict(os.environ, {KEY_ENV: KEY}), contextlib.redirect_stderr(io.StringIO()):
            status, _, out = self.post("dev-assistant")
        self.assertEqual((status, out["error"]["attempts"][-1]["outcome"]), (503, "http 302"))
        self.assertEqual(elsewhere.received, [])
        raw["upstreams"]["cloud"]["api_key"] = KEY
        with self.assertRaises(ConfigError) as caught:
            parse_config(raw, self.tmp)
        self.assertIn("api_key_env", str(caught.exception))
        self.assertNotIn(KEY, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
