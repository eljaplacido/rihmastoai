"""A neutral stand-in home for IT's view of integrations and data (FR-ITD1), and a connection that never leaves.

`build(home, port)` makes a factory home (clock fixed at 2026-11-25) with:

- "Order desk", at maturity pilot (it delivers to staging on the `local` local-process road), whose spec declares two
  data integrations: `orders_api` (rest, read-write, confidential data, credential ORDERS_API_TOKEN) bound to
  ``http://127.0.0.1:<port>/api`` with its token in the variable ORDERS_STAGING_TOKEN, and `recordings` (Google
  Drive, read, internal) bound to https://www.googleapis.com. No road card is approved yet;
- "Ledger notes", marked confidential;
- the relay: SUB-001, Teams notices for the Order desk only, its URL in DESK_TEAMS_URL (not set), and SUB-002, signed
  webhook events of every project to https://hooks.example.org/in, its secret in HOOK_SIGNING_SECRET;
- an inbound webhook source `order-events` bound to the Order desk, its secret in ORDER_EVENTS_SECRET.

`Listener()` answers on a loopback port (it accepts and closes). `offline(calls)` is a stand-in for the one TCP
connection a check opens (kernel/itdata_actions.py ``connect``): it records where it was asked to connect, reaches
loopback for real and refuses every other address, so a test never touches the network.

`write_routes(case, w)` are the cockpit's three writes for the completeness tables (tests/test_brief_ln.py,
tests/test_access.py): a webhook source made for them is checked, gets a rotation reminder and is turned off.
"""

from __future__ import annotations

import socket
import socketserver
import threading
from pathlib import Path
from typing import Any

from kernel.store import Factory, FixedClock, write_json

PERSON = ("Ilkka Example", "it")
ORDERS = {"name": "orders_api", "kind": "rest", "via": "http", "access": "read-write", "data_classes": ["confidential"],
          "credentials": ["ORDERS_API_TOKEN"], "provenance": "customer-confirmed"}
DRIVE = {"name": "recordings", "kind": "gdrive", "via": "http", "access": "read", "data_classes": ["internal"],
         "credentials": [], "provenance": "customer-confirmed"}
SECRET_VALUE = "itd-fixture-secret-value-never-shown"
VARS = ("ORDERS_STAGING_TOKEN", "DESK_TEAMS_URL", "HOOK_SIGNING_SECRET", "ORDER_EVENTS_SECRET", "ITD_EVENTS_SECRET")


class _Accept(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        return


class Listener:
    """Something that answers on a loopback port."""

    def __init__(self) -> None:
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Accept)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


def offline(calls: list) -> Any:
    """A ``connect`` that reaches loopback only, and records every address it was given."""
    def connect(address: tuple, timeout: float = 2.0) -> socket.socket:
        calls.append(address)
        if address[0] not in ("127.0.0.1", "localhost", "::1"):
            raise OSError("the test never leaves this machine")
        return socket.create_connection(address, timeout=timeout)
    return connect


def build(home: Path, port: int) -> dict[str, Any]:
    from kernel import confidential, hooks, relay

    factory = Factory(home, clock=FixedClock("2026-11-25T09:00:00Z"))
    project = factory.new_project("Order desk", mode="assume", maturity="pilot")
    spec = project.read("spec.json") or {}
    project.write("spec.json", {"title": "Order desk", "requirements": [], **spec, "integrations": [ORDERS, DRIVE]})
    write_json(factory.paved_roads_path, {
        "schema": "gnomonfactory.paved_roads/1",
        "roads": {"local": {"kind": "local-process", "configured": True, "environments": ["staging"], "integrations": {
            "orders_api": {"endpoint": f"http://127.0.0.1:{port}/api",
                           "secrets": [{"name": "ORDERS_API_TOKEN", "ref": "env:ORDERS_STAGING_TOKEN"}]},
            "recordings": {"endpoint": "https://www.googleapis.com"}}}},
        "maturity": {"pilot": {"staging": "local"}}})
    notes = factory.new_project("Ledger notes", mode="assume", maturity="explore")
    confidential.mark(notes, person=PERSON[0], persona=PERSON[1])
    relay.subscribe(factory, sink="teams", url_env="DESK_TEAMS_URL", personas=["it"], projects=[project.pid],
                    person=PERSON[0], persona=PERSON[1])
    relay.subscribe(factory, sink="webhook", url="https://hooks.example.org/in", secret_env="HOOK_SIGNING_SECRET",
                    person=PERSON[0], persona=PERSON[1])
    hooks.add_source(factory, "order-events", scheme="standard", secret_env="ORDER_EVENTS_SECRET", person=PERSON[0],
                     persona=PERSON[1], bind=[project.pid])
    return {"factory": factory, "project": project, "notes": notes}


def write_routes(case: Any, w: dict[str, Any]) -> list[tuple[Any, ...]]:
    """Check now, a rotation reminder and Turn off, each by IT on the platform's own webhook source."""
    from kernel import hooks

    hooks.add_source(case.factory, "itd-events", scheme="standard", secret_env="ITD_EVENTS_SECRET",
                     person=PERSON[0], persona=PERSON[1])
    return [
        ("post_itdata_check", "POST", "/api/it-data/check",
         lambda who, got: {"item": "hook:itd-events", "person": who, "persona": "it"}),
        ("post_itdata_rotate", "POST", "/api/it-data/rotate-reminder",
         lambda who, got: {"credential": "ITD_EVENTS_SECRET", "days": 30, "person": who, "persona": "it"}),
        ("post_itdata_disable", "POST", "/api/it-data/disable",
         lambda who, got: {"item": "hook:itd-events", "reason": "replaced by a connector", "person": who,
                           "persona": "it"}),
    ]
