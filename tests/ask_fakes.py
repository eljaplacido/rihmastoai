"""Machines and asks between agents and machines (FR-XAG1): the signed write routes for the cockpit's completeness
tables (tests/test_brief_ln.py, tests/test_access.py). A machine is recorded in Rihmasto's own ledger, an ask and
everything done to it in its project's. Test connection (``post_reach``) records nothing and takes no person."""

from __future__ import annotations

from typing import Any

from kernel import asks

RECORD_NOTHING = {"post_reach"}


def write_rows(case: Any, w: dict[str, Any]) -> list[tuple[Any, ...]]:
    b = w["built"]
    spare = asks.create(b, to="codex", text="Is main green?", person="Aino Example", persona="it")["ask"]["id"]

    def aid(got: dict[str, Any]) -> str:                       # the ask post_ask put
        return got["post_ask"]["ask"]["id"]

    def signed(who: str, **extra: Any) -> dict[str, Any]:
        return {**extra, "person": who, "persona": "it"}
    return [
        ("post_machine", "POST", "/api/machines",
         lambda who, got: signed(who, name="laptop", reach="ssh", address="me@laptop", os="windows",
                                 agents=["claude-code"])),
        ("post_ask", "POST", f"/api/projects/{b.pid}/asks",
         lambda who, got: signed(who, to="claude-code", machine="laptop", text="Run git status and say the branch.")),
        ("post_ask_copy", "POST", lambda got: f"/api/projects/{b.pid}/asks/{aid(got)}/copy",
         lambda who, got: signed(who)),
        ("post_ask_link", "POST", lambda got: f"/api/projects/{b.pid}/asks/{aid(got)}/link",
         lambda who, got: signed(who)),
        ("post_ask_answer", "POST", lambda got: f"/api/projects/{b.pid}/asks/{aid(got)}/answer",
         lambda who, got: signed(who, text="main, clean")),
        ("post_ask_withdraw", "POST", f"/api/projects/{b.pid}/asks/{spare}/withdraw", lambda who, got: signed(who)),
        ("post_machine_remove", "POST", "/api/machines/remove", lambda who, got: signed(who, name="laptop")),
    ]
