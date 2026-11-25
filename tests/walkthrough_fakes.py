"""Helpers for the walkthrough tests (FR-WLK1): a walkthrough brought to a step through the kernel, and the
route that acts on it, for the tables of every signed write route (tests/test_brief_ln.py, tests/test_access.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kernel import walkthrough as wk

OWNER, PERSONA = "Ida Example", "developer"
# The replies that bring each walkthrough from its first step to the step named.
TO_STEP: dict[tuple[str, str], list[dict[str, Any]]] = {
    ("tour", "home"): [],
    ("tour", "inbox"): [{"choice": "next"}],
    ("plug_in", "confirm"): [{"source": True}, {"choice": "default"}, {"choice": "no"}, {"choice": "maintain"},
                             {"choice": "none"}],
}


def allow_roots(case: Any, folder: Path) -> None:
    """The cockpit reads folders under ``folder`` (kernel/source_guard.py) until ``case`` ends."""
    import os
    from unittest import mock

    from kernel.source_guard import ROOTS_ENV

    patcher = mock.patch.dict(os.environ, {ROOTS_ENV: str(folder)})
    patcher.start()
    case.addCleanup(patcher.stop)


def walk_to(factory: Any, name: str, step: str, source: str | Path | None = None, *, person: str = OWNER,
            persona: str = PERSONA) -> dict[str, Any]:
    """A walkthrough of ``name`` for ``person``, started afresh and brought to ``step``."""
    w = wk.start(factory, name, person=person, persona=persona, replace=True)
    for said in TO_STEP[(name, step)]:
        if said.get("source"):
            w = wk.reply(factory, w["id"], person=person, persona=persona, text=str(source))
        else:
            w = wk.reply(factory, w["id"], person=person, persona=persona, **said)
    assert w["step"] == step, (w["step"], w["messages"][-1])
    return w


def walk_route(test: Any, name: str, step: str, action: str, source: str | Path | None = None) -> str:
    """The path of a walkthrough route (reply, confirm or cancel) on a walkthrough brought to ``step``."""
    return f"/api/walkthroughs/{walk_to(test.factory, name, step, source)['id']}/{action}"


def write_rows(test: Any, repo: Path) -> list[tuple[Any, ...]]:
    """The walkthrough routes as rows of the signed-write tables: (route, method, path, body for a person)."""
    return [
        ("post_walkthrough", "POST", "/api/walkthroughs",
         lambda who, got: {"name": "tour", "person": who, "persona": PERSONA}),
        ("post_walkthrough_reply", "POST", lambda got: walk_route(test, "tour", "home", "reply"),
         lambda who, got: {"choice": "next", "person": who, "persona": PERSONA}),
        ("post_walkthrough_confirm", "POST", lambda got: walk_route(test, "plug_in", "confirm", "confirm", repo),
         lambda who, got: {"person": who, "persona": PERSONA}),          # carried out by post_adopt
        ("post_walkthrough_cancel", "POST", lambda got: walk_route(test, "tour", "inbox", "cancel"),
         lambda who, got: {"person": who, "persona": PERSONA}),
    ]
