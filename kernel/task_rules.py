"""What a task waits for before a person starts it or marks it done (FR-LND2).

A person could start T-003 while it waited for T-002, and mark an escalated task done while Start here and its panel
still said it waited on a decision. By rule, from the contract, ``tasks.json``, the ledger and the Inbox:

- a task waits for the tasks it depends on until each is merged by the gate or marked done by a person;
- an escalated task waits on its decision card while that card is open: decide it first (accept it as it is, or send
  it back), then it can be started or marked done.

``start`` is refused for either; ``mark done`` for the open decision (a person may close by hand a task whose
dependencies are unfinished: the board shows it done, apart from the gate's merge). ``lane`` places a task on the
board: a person's done has a lane of its own, apart from the gate's merged.
"""

from __future__ import annotations

from typing import Any

FINISHED = ("merged",)


def _states(project: Any) -> dict[str, Any]:
    got = project.read("tasks.json", {})
    return got if isinstance(got, dict) else {}


def _tasks(project: Any) -> dict[str, dict[str, Any]]:
    contract = project.read("contract.json", None)
    tasks = contract.get("tasks") if isinstance(contract, dict) else None
    return {t["id"]: t for t in tasks or [] if isinstance(t, dict) and t.get("id")}


def _marked_done(project: Any) -> set[str]:
    from kernel.task_detail import DONE

    out = set()
    for rec in project.ledger().records():
        ev = rec.get("event") if isinstance(rec, dict) else None
        if isinstance(ev, dict) and ev.get("kind") == DONE:
            out.add(str((ev.get("payload") or {}).get("task")))
    return out


def _open_card(project: Any, cid: str) -> bool:
    from kernel.canon import Canon

    try:
        return Canon(project).get_card(cid).get("state") == "open"
    except (KeyError, ValueError, OSError):
        return False


def waits(project: Any, tid: str) -> dict[str, Any] | None:
    """What ``tid`` waits for: an open decision card, unfinished tasks it depends on, or None."""
    states = _states(project)
    got = states.get(tid)
    st: dict[str, Any] = got if isinstance(got, dict) else {}
    if st.get("status") == "escalated" and st.get("card") and _open_card(project, str(st["card"])):
        cid = str(st["card"])
        return {"kind": "decision", "card": cid, "tasks": [],
                "said": f"{tid} waits on the decision {cid}: decide it first (accept it as it is, or send it back)",
                "route": f"#/p/{project.pid}/inbox/{cid}"}
    deps = [str(d) for d in (_tasks(project).get(tid) or {}).get("depends_on") or []]
    if not deps:
        return None
    done = _marked_done(project)
    left = [d for d in deps if (states.get(d) or {}).get("status") not in FINISHED and d not in done]
    if not left:
        return None
    return {"kind": "tasks", "card": None, "tasks": left,
            "said": f"{tid} waits for {', '.join(left)}: finish {'it' if len(left) == 1 else 'them'} first",
            "route": f"#/p/{project.pid}/tasks/{left[0]}"}


def lane(status: str, mark: dict[str, Any] | None) -> str:
    """The board lane of a task: the gate's status, with a person's done in a lane of its own."""
    if status != "merged" and (mark or {}).get("done"):
        return "done"
    return status if status in ("pending", "building", "merged", "escalated", "stopped") else "pending"


__all__ = ["lane", "waits"]
