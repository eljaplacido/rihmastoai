"""Observer links' write routes for the completeness tables (tests/test_brief_ln.py, tests/test_access.py; FR-SHR1):
each signed, in an order where each one's target exists. A link to the built project is made for a named guest and
revoked; a guest's suggested answer to an open intake question (made through the kernel, as the guest's page does,
before the row's requests) is declined. Where the sharer is (following) records nothing: ``presence_row``."""

from __future__ import annotations

from typing import Any

from kernel import observe
from kernel.canon import Canon


def _suggested(case: Any, pid: str) -> str:
    """A guest's suggestion waiting on the built project: an open question, a link that allows it, a visit."""
    project = case.factory.project(pid)
    q = Canon(project).add_question("Who borrows the drills most?", "business")
    made = observe.create(case.factory, scope="project", project=pid, hours=1, guest="Gita Guest", intake=True,
                          person="Sari Sharer", persona="product_owner")
    session = observe.open_link(case.factory, made["token"])["session"]
    link = observe.session(case.factory, session)
    return observe.suggest(case.factory, link, q["id"], "The site foremen")["id"]


def write_routes(case: Any, w: dict[str, Any]) -> list:
    b = w["built"].pid
    held: dict[str, str] = {}

    def suggestion_path(got: dict[str, Any]) -> str:
        held.setdefault("id", _suggested(case, b))
        return f"/api/projects/{b}/observe/suggestions"

    return [
        ("post_observe_link", "POST", "/api/observe/links",
         lambda who, got: {"scope": "project", "project": b, "hours": 24, "guest": "Maria Example", "person": who,
                           "persona": "product_owner"}),
        ("post_observe_revoke", "POST", "/api/observe/revoke",
         lambda who, got: {"link": got["post_observe_link"]["link"]["id"], "person": who, "persona": "product_owner"}),
        ("post_observe_suggestion", "POST", suggestion_path,
         lambda who, got: {"suggestion": held["id"], "verdict": "decline", "person": who, "persona": "product_owner"}),
    ]


def presence_row(w: dict[str, Any]) -> tuple:
    """Where the sharer is: kept in memory, recorded nowhere."""
    b = w["built"].pid
    return ("post_observe_presence", "POST", "/api/observe/presence",
            lambda who, got: {"project": b, "view": "plan", "person": who, "persona": "product_owner"})
