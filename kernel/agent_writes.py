"""The agent bridge, agents to Rihmasto (FR-BRG1, FR-CHN1): what a coding agent writes back, and what it reads.

Every write is signed as the agent's named operator (the person who runs it), recorded in the ledger and posted in
the project's agent channel (kernel/agent_channel.py), so it shows on the project's timeline, in the channel and in
the Agents strip as "<agent> for <operator>". None decides a card:

- ``progress``: what the agent did, the files it touched, the criteria it believes it addressed, a commit;
- ``propose_answer``: an answer it suggests to an open question. It is a proposal in the channel, never an answer:
  a person confirms it (the Questions view's own path answers the question then) or rejects it;
- ``request_gate``: asks the repository gate to check a commit of an attached repository (kernel/gate_external.py),
  or a check to run (kernel/checks, when present). The result posts itself into the channel. An adopted project's
  gate runs on a workspace submission, which the request says how to send.

The reads (``next_view``, ``plan_view``, ``questions_view``, ``feedback``, ``activity``) write nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kernel import agent_channel as ch
from kernel.agent_bridge import failed_checks, failed_gates, review_feedback
from kernel.copilot_catalog import optional

MAX_FILES = 40


def _log(project: Any, kind: str, author: dict[str, Any], **extra: Any) -> None:
    project.log(kind, {"agent": author["name"], "harness": author.get("harness"), "operator": author["operator"],
                       "person": author["operator"], "persona": author["persona"], **extra})


def progress(project: Any, author: dict[str, Any], text: str, *, files: list[str] | None = None,
             criteria: list[str] | None = None, commit: str | None = None, thread: str | None = None) -> dict[str, Any]:
    """An agent's progress note on the project's timeline and in its channel."""
    refs = {"files": (files or [])[:MAX_FILES], "criteria": criteria or [], "commits": [commit] if commit else []}
    msg = ch.post(project, author=author, kind="progress", text=text, thread=thread,
                  refs={k: v for k, v in refs.items() if v})
    _log(project, "agent_progress", msg["author"], message=msg["id"], files=len(refs["files"]),
         criteria=refs["criteria"][:20], commit=commit)
    return msg


def propose_answer(project: Any, author: dict[str, Any], question: str, text: str, *,
                   thread: str | None = None) -> dict[str, Any]:
    """A suggested answer to an open question: a proposal a person confirms or rejects, never an answer itself."""
    from kernel.canon import Canon

    qid = question.strip().upper()
    try:
        q = Canon(project).question(qid)
    except KeyError:
        raise ch.ChannelRefused(f"no question {qid} in {project.pid}") from None
    if q["status"] != "open":
        raise ch.ChannelRefused(f"{qid} is {q['status']}: only an open question takes a proposed answer")
    msg = ch.post(project, author=author, kind="proposal", state="open", thread=thread, refs={"questions": [qid]},
                  text=f"Proposed answer to {qid} ({q['text'][:160]}): {text.strip()}")
    _log(project, "agent_proposed_answer", msg["author"], message=msg["id"], question=qid)
    return msg


def proposal_text(msg: dict[str, Any]) -> str:
    """The answer a proposal suggests, without its preamble."""
    text = msg["text"]
    return text.split("): ", 1)[1] if "): " in text else text


def _gate_result(project: Any, request: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    failing = [s["name"] for s in out.get("signals") or [] if s.get("verdict") not in ("passed", "pass")]
    text = (f"Gate on {str(out.get('head') or '')[:12]}: {out.get('verdict')}"
            + (f"; not passed: {', '.join(failing)}" if failing else "") + ".")
    trace = {"basis": "gate", "task": out.get("task"), "round": out.get("round"), "base": out.get("base"),
             "head": out.get("head"), "signals": out.get("signals"), "objections": out.get("objections")}
    return ch.post(project, author=ch.SYSTEM, kind="gate_result", text=text, thread=request["thread"],
                   refs={"message": request["id"], "commits": [str(out.get("head") or "")]}, trace=trace)


def run_gate(project: Any, request: dict[str, Any], author: dict[str, Any], head: str | None,
             gate: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """Run the requested gate signed as the operator, and post its result into the channel."""
    from kernel import gate_external

    gate = gate or gate_external.gate
    try:
        out = gate(project, person=author["operator"], persona=author["persona"], head=head)
    except (ValueError, LookupError, OSError, RuntimeError) as exc:
        return ch.post(project, author=ch.SYSTEM, kind="gate_result", thread=request["thread"],
                       refs={"message": request["id"]}, text=f"The gate did not run: {exc}",
                       trace={"basis": "gate", "refused": str(exc)[:500]})
    return _gate_result(project, request, out)


def run_check(project: Any, request: dict[str, Any], author: dict[str, Any], key: str) -> dict[str, Any]:
    store = optional("kernel.checks.store")
    try:
        out = store.run(project, key, person=author["operator"], persona=author["persona"], via="agent")
    except Exception as exc:  # noqa: BLE001 - a check that cannot run says why in the channel
        return ch.post(project, author=ch.SYSTEM, kind="check_result", thread=request["thread"],
                       refs={"message": request["id"], "checks": [key]}, text=f"The check {key} did not run: {exc}")
    return ch.post(project, author=ch.SYSTEM, kind="check_result", thread=request["thread"],
                   refs={"message": request["id"], "checks": [key]},
                   text=f"Check {key}: {out.get('verdict')}. {str(out.get('summary') or '')[:300]}",
                   trace={"basis": "check", "check": key, "verdict": out.get("verdict"),
                          "evidence": (out.get("evidence") or [])[:5]})


def request_gate(project: Any, author: dict[str, Any], *, head: str | None = None, check: str | None = None,
                 thread: str | None = None) -> dict[str, Any]:
    """Record an agent's request for the gate (or a check). Returns the request, and ``run``: what to call to carry
    it out (None when it cannot run here, and the request says why)."""
    kind = project.meta.get("source_kind")
    if check:
        store = optional("kernel.checks.store")
        if store is None:
            raise ch.ChannelRefused("checks are not in this Rihmasto yet")
        if check not in store.enabled(project):
            raise ch.ChannelRefused(f"the check {check} is not enabled on {project.pid}: a person enables it on its "
                                    "Health tab")
        msg = ch.post(project, author=author, kind="note", thread=thread, refs={"checks": [check]},
                      text=f"Asked for the check {check} to run.")
        _log(project, "agent_gate_requested", msg["author"], message=msg["id"], check=check)
        return {"request": msg, "run": lambda gate=None: run_check(project, msg, msg["author"], check)}
    if kind not in ("attached", "adopted"):
        raise ch.ChannelRefused(f"{project.pid} is built by the factory itself: its cells meet the gate on every "
                                "round; a gate on request is for an attached or adopted repository")
    msg = ch.post(project, author=author, kind="note", thread=thread,
                  refs={"commits": [head]} if head else None,
                  text=f"Asked the gate to check {head or 'the branch head'}.")
    _log(project, "agent_gate_requested", msg["author"], message=msg["id"], head=head)
    if kind == "adopted":
        ch.post(project, author=ch.SYSTEM, kind="note", thread=msg["thread"], refs={"message": msg["id"]},
                text=f"An adopted project's gate runs when its operator sends the work: `rihmasto workspace submit "
                     f"{project.pid} <folder> --person \"{author['operator']}\" --persona developer`.")
        return {"request": msg, "run": None}
    return {"request": msg, "run": lambda gate=None: run_gate(project, msg, msg["author"], head, gate)}


# -- reads -----------------------------------------------------------------------------------------------

def activity(project: Any, limit: int = 8) -> dict[str, Any]:
    """The Agents strip: recent agent posts, the hand-offs given and the gates requested, newest first."""
    rows = ch.read(project)["messages"]
    shown = [m for m in rows if m["author"]["kind"] == "agent" or m["kind"] in ("handoff", "gate_result",
                                                                                  "check_result")]
    items = [{"id": m["id"], "at": m["at"], "who": ch.who(m), "kind": m["kind"], "text": m["text"][:200],
              "author_kind": m["author"]["kind"], "harness": m["author"].get("harness"), "state": m.get("state"),
              "held": bool(m.get("held"))} for m in reversed(shown)][:limit]
    agents = sorted({m["author"]["name"] for m in rows if m["author"]["kind"] == "agent"})
    return {"project": project.pid, "items": items, "agents": agents,
            "handoffs": len([m for m in rows if m["kind"] == "handoff"]),
            "gates": len([m for m in rows if m["kind"] == "gate_result"]),
            "proposals_waiting": [m["id"] for m in rows if m["kind"] == "proposal" and m.get("state") == "open"],
            "paused": ch.read(project).get("paused")}


def feedback(project: Any, since: str | None = None) -> dict[str, Any]:
    """What came back for the agents: review feedback, failed gates and checks, change cards, settled proposals and
    people's messages in the channel, since a time (all when none)."""
    from kernel.canon import Canon

    cards = [{"id": c["id"], "title": c["title"], "state": c["state"], "created": c.get("created")}
             for c in Canon(project).cards(state=None, kind="change") if not since or str(c.get("created")) > since]
    said = [m for m in ch.read(project)["messages"] if not since or m["at"] > since]
    return {"project": project.pid, "since": since, "review": review_feedback(project),
            "failed_gates": failed_gates(project, since), "failed_checks": failed_checks(project),
            "change_cards": cards[-20:],
            "settled_proposals": [{"id": m["id"], "state": m["state"], "by": (m.get("settled") or {}).get("person")}
                                  for m in said if m["kind"] == "proposal" and m.get("state") != "open"],
            "from_people": [{"id": m["id"], "who": m["author"]["name"], "kind": m["kind"], "text": m["text"][:500]}
                            for m in said if m["author"]["kind"] == "person"][-20:]}


def next_view(project: Any) -> dict[str, Any]:
    from kernel.next_step import next_step

    return {"project": project.pid, **next_step(project)}


def plan_view(project: Any) -> dict[str, Any]:
    spec = project.read("spec.json", {}) or {}
    contract = project.read("contract.json") or {}
    tasks = project.read("tasks.json", {}) or {}
    return {"project": project.pid, "spec": {"title": spec.get("title"), "summary": spec.get("summary"),
                                             "integrations": spec.get("integrations") or []},
            "contract": {"revision": contract.get("revision"),
                         "requirements": [{"id": r["id"], "statement": r["statement"],
                                           "criteria": [{"id": c["id"], "given": c.get("given"), "when": c.get("when"),
                                                         "then": c.get("then")} for c in r.get("acceptance", [])]}
                                          for r in contract.get("requirements", [])]},
            "tasks": [{"id": t["id"], "title": t.get("title"), "criteria": t.get("criteria"),
                       "status": (tasks.get(t["id"]) or {}).get("status")} for t in contract.get("tasks", [])],
            "note": "no contract yet: criteria come with it" if not contract else None}


def questions_view(project: Any) -> dict[str, Any]:
    from kernel.canon import Canon

    canon = Canon(project)
    return {"project": project.pid,
            "questions": [{"id": q["id"], "text": q["text"], "perspective": q["perspective"], "blocking": q["blocking"],
                           "options": q.get("options", [])} for q in canon.questions("open")],
            "assumptions": [{"id": a["id"], "text": a["text"], "due": a.get("due")} for a in canon.assumptions("open")],
            "note": "People answer these in the cockpit. rihma_propose_answer suggests an answer for a person to "
                    "confirm."}
