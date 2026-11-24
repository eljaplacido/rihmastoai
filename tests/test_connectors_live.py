"""The PostgreSQL connector against a real database, when asked (FR-DS4-AC-3).

The live check runs only with `RIHMA_LIVE_POSTGRES=1` and a DSN in `RIHMA_POSTGRES_DSN` whose host is
loopback: it runs on the database's own host, and no test reaches beyond this machine. The pinned
server's command (connectors/postgres/connector.json) must be installed there; Rihmasto installs nothing.
Otherwise it is skipped, and the skip says why.

It speaks MCP to the pinned server over stdio as Gnomon would, with the DSN as `DATABASE_URI`, and checks
what the offline pin could not: that the real tools/list is the pinned one, that the read tools' results
map to valid proposals, and that a statement that writes is refused and leaves nothing behind.

    RIHMA_LIVE_POSTGRES=1 RIHMA_POSTGRES_DSN=postgresql://reader:...@127.0.0.1:5432/db \\
        python -m unittest tests.test_connectors_live -v
"""

import importlib.util
import json
import os
import shutil
import subprocess
import threading
import unittest
import urllib.parse
from unittest import mock

from kernel import connectors

ROOT = connectors.DEFAULT_ROOT
LOOPBACK = ("127.0.0.1", "localhost", "::1")
PROBE_TABLE = "rihma_live_write_probe"


def live_dsn() -> tuple[str | None, str]:
    """The DSN to check against, or None and why the live check does not run."""
    if os.environ.get("RIHMA_LIVE_POSTGRES") != "1":
        return None, "the live check runs with RIHMA_LIVE_POSTGRES=1 and RIHMA_POSTGRES_DSN"
    dsn = os.environ.get("RIHMA_POSTGRES_DSN", "").strip()
    if not dsn:
        return None, "RIHMA_POSTGRES_DSN names no database"
    if urllib.parse.urlsplit(dsn).hostname not in LOOPBACK:
        return None, "the DSN's host is not loopback: run the live check on the database's own host"
    return dsn, ""


def mapping():
    spec = importlib.util.spec_from_file_location("live_postgres_mapping", ROOT / "postgres" / "mapping.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiveServer:
    """The pinned server as a child process, spoken to over stdio as Gnomon would."""

    def __init__(self, command: list, dsn: str) -> None:
        env = dict(os.environ, DATABASE_URI=dsn, PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen(command, cwd=ROOT / "postgres", stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, encoding="utf-8", env=env)
        self.watchdog = threading.Timer(120, self.proc.kill)
        self.watchdog.start()
        self.next_id = 0

    def request(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method,
                                          "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        while True:  # a server may send notifications before its answer
            answer = json.loads(self.proc.stdout.readline())
            if answer.get("id") == self.next_id:
                return answer

    def call(self, name: str, args: dict) -> tuple[str, bool]:
        result = self.request("tools/call", {"name": name, "arguments": args})["result"]
        return "".join(c.get("text", "") for c in result.get("content", [])), bool(result.get("isError"))

    def __enter__(self) -> "LiveServer":
        self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "rihmasto-live-check", "version": "1"}})
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.proc.stdin.flush()
        return self

    def __exit__(self, *exc) -> None:
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=30)
        finally:
            self.proc.kill()
            self.proc.stdout.close()
            self.watchdog.cancel()


class LiveGateTest(unittest.TestCase):
    def test_FR_DS4_AC_3_the_live_check_runs_only_when_asked_and_only_against_a_database_on_loopback(self):
        cases = {
            (): (None, "RIHMA_LIVE_POSTGRES=1"),
            (("RIHMA_LIVE_POSTGRES", "1"),): (None, "names no database"),
            (("RIHMA_LIVE_POSTGRES", "1"), ("RIHMA_POSTGRES_DSN", "postgresql://r@db.example.invalid/x")):
                (None, "not loopback"),
            (("RIHMA_LIVE_POSTGRES", "1"), ("RIHMA_POSTGRES_DSN", "postgresql://r@127.0.0.1:5432/x")):
                ("postgresql://r@127.0.0.1:5432/x", ""),
        }
        for env, (dsn, why) in cases.items():
            with self.subTest(env), mock.patch.dict(os.environ, dict(env), clear=False):
                for name in ("RIHMA_LIVE_POSTGRES", "RIHMA_POSTGRES_DSN"):
                    if name not in dict(env):
                        os.environ.pop(name, None)
                got, reason = live_dsn()
                self.assertEqual(got, dsn)
                self.assertIn(why, reason)


@unittest.skipUnless(live_dsn()[0], live_dsn()[1])
class LivePostgresTest(unittest.TestCase):
    def setUp(self):
        self.doc = connectors.load(ROOT, "postgres")
        command = self.doc["server"]["command"]
        if shutil.which(command[0]) is None:
            self.skipTest(f"the pinned server {command[0]} {self.doc['server']['pin']['version']} is not installed "
                          "on this host")
        self.command, self.dsn, self.mapping = command, live_dsn()[0], mapping()

    def test_FR_DS4_AC_3_the_real_server_answers_the_pinned_tools_its_reads_map_and_a_write_is_refused(self):
        with LiveServer(self.command, self.dsn) as srv:
            tools = srv.request("tools/list")["result"]["tools"]
            seen = connectors.tools_sha256(tools)
            self.assertEqual(seen, self.doc["tools_sha256"],
                             f"the real tools/list differs from the pin (now {seen}): review it, then update "
                             "fixtures/tools.json and tools_sha256; until then the connector may not run")
            for tool, args in (("list_schemas", {}), ("list_objects", {"schema_name": "public"}),
                               ("execute_sql", {"sql": "SELECT 1 AS one"})):
                text, error = srv.call(tool, args)
                self.assertFalse(error, (tool, text[:300]))
                proposals = self.mapping.from_result(tool, text)
                if tool != "list_objects":                 # an empty public schema lists nothing
                    self.assertTrue(proposals, (tool, text[:300]))
                for proposal in proposals:
                    self.assertEqual(connectors.check_proposal(self.doc, proposal), [], proposal)
            srv.call("execute_sql", {"sql": f"CREATE TABLE {PROBE_TABLE} (id integer)"})
            text, _ = srv.call("execute_sql", {"sql": f"SELECT to_regclass('public.{PROBE_TABLE}') AS found"})
            rows = self.mapping.rows(text)
            self.assertTrue(rows, text[:300])
            self.assertIsNone(rows[0].get("found"), "a statement that writes ran: the server is not read-only")


if __name__ == "__main__":
    unittest.main()
