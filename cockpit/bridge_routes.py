"""The cockpit's routes for the agent bridge and the agent channel (FR-BRG1, FR-CHN1, docs/guides/agentic-help.md).

Reads write nothing: a project's hand-off brief and how each agent takes it, the Agents strip, the channel, and the
factory-wide Agent activity monitor. Writes are signed by a person and persona as the other write routes are (with
access enforced, a persona granted on the project) and recorded by the kernel:

- recording a hand-off a person gave (copy, download, or "Run it with <runner>" when cell runners are in this
  Rihmasto, which files the brief as a change a person accepts before the factory's own builder cell runs it);
- a person's post in the channel (``@analyst`` or ``@verifier`` asks a Rihma agent, answered beside the request
  when a model is asked, so a slow model never holds the write lock);
- confirming or rejecting an agent's proposed answer: confirming answers the question through the Questions view's
  own route (``post_answer``), signed with the person's name, then records the verdict;
- pausing and resuming the channel.
"""

from __future__ import annotations

import threading
from typing import Any

from kernel import agent_bridge as bridge
from kernel import agent_channel as ch
from kernel import agent_writes as writes
from kernel import channel_rihma
from kernel.copilot_catalog import optional

PID = r"(?P<pid>_factory|[a-z0-9][a-z0-9-]{0,80})"
MID = r"(?P<mid>M-\d{1,9})"
ROUTES = [
    ("GET", rf"/api/projects/{PID}/handoff", "get_handoff"),
    ("POST", rf"/api/projects/{PID}/handoff", "post_handoff"),
    ("GET", rf"/api/projects/{PID}/agents", "get_agents"),
    ("GET", rf"/api/projects/{PID}/channel", "get_channel"),
    ("POST", rf"/api/projects/{PID}/channel", "post_channel"),
    ("POST", rf"/api/projects/{PID}/channel/{MID}/settle", "post_channel_settle"),
    ("POST", rf"/api/projects/{PID}/channel/pause", "post_channel_pause"),
    ("POST", rf"/api/projects/{PID}/channel/resume", "post_channel_resume"),
    ("GET", r"/api/agents", "get_agent_activity"),
]
UNLOCKED: set[str] = set()
VIAS = ("copy", "download", "run")
Reply = tuple[int, dict[str, Any]]


def _server() -> Any:
    from cockpit import server

    return server


def _error(status: int, message: str) -> Exception:
    return _server().ApiError(status, message)


def _text(body: dict[str, Any], key: str, *, required: bool = False, limit: int = 8000) -> str:
    return str(_server()._text(body, key, required=required, limit=limit))


def _runner(factory: Any, pid: str) -> str | None:
    """The builder runner chosen for the project when cell runners are in this Rihmasto, else None."""
    choice = optional("kernel.runners.choice")
    if choice is None:
        return None
    try:
        return str(choice.effective(factory, pid, "builder").get("runner") or "gnomon")
    except Exception:  # noqa: BLE001 - a choice that cannot be read offers no run
        return None


class BridgeRoutes:
    """Mixed into the cockpit's Api: it has ``server``, ``factory``, ``_who``, ``_project`` and ``post_answer``."""

    server: Any
    factory: Any

    def _who(self, body: dict[str, Any], pid: str | None) -> tuple[str, str]:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _project(self, pid: str) -> Any:  # pragma: no cover - Api's own
        raise NotImplementedError

    def _signer(self, body: dict[str, Any], pid: str) -> tuple[str, str]:
        person, persona = self._who(body, pid)
        _server()._require_person(person, persona)
        return person, persona

    # reads

    def get_handoff(self, pid: str, query: dict[str, Any], **_: object) -> Reply:
        project = self._project(pid)
        to = query.get("to") or "generic"
        if to not in bridge.AGENTS:
            raise _error(400, f"to is one of {', '.join(bridge.AGENTS)}")
        try:
            b = bridge.brief(project, change=query.get("change") or None)
        except (KeyError, ValueError) as exc:
            raise _error(400, str(exc.args[0] if exc.args else exc)) from None
        runner = _runner(self.factory, pid)
        label = (optional("kernel.runners").label_of(runner) if runner else None)
        return 200, {"brief": b, "markdown": bridge.render(b), "agents": bridge.AGENTS,
                     "use": bridge.for_agent(self.factory, project, b, to=to, operator=query.get("person") or
                                             "<your name>", persona=query.get("persona") or "developer"),
                     "run": {"available": runner is not None, "runner": runner, "label": label,
                             "why_not": None if runner else "cell runners are not in this Rihmasto yet"}}

    def get_agents(self, pid: str, **_: object) -> Reply:
        return 200, writes.activity(self._project(pid))

    def get_channel(self, pid: str, query: dict[str, Any], **_: object) -> Reply:
        project = self._project(pid)
        try:
            rows = ch.messages(project, since=query.get("since") or None, thread=query.get("thread") or None)
        except ch.ChannelRefused as exc:
            raise _error(400, str(exc)) from None
        doc = ch.read(project)
        threads = sorted({m["thread"] for m in doc["messages"]})
        return 200, {"project": pid, "messages": rows, "paused": doc.get("paused"), "threads": threads or [ch.MAIN],
                     "kinds": list(ch.KINDS), "model": getattr(self.server, "assistant_model", None) is not None}

    def get_agent_activity(self, **_: object) -> Reply:
        return 200, ch.monitor(self.factory)

    # writes

    def post_handoff(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._project(pid)
        person, persona = self._signer(body, pid)
        to, via = _text(body, "to", limit=16) or "generic", _text(body, "via", limit=16) or "copy"
        if to not in bridge.AGENTS or via not in VIAS:
            raise _error(400, f"to is one of {', '.join(bridge.AGENTS)}; via one of {', '.join(VIAS)}")
        try:
            b = bridge.brief(project, change=_text(body, "change", limit=16) or None)
        except (KeyError, ValueError) as exc:
            raise _error(400, str(exc.args[0] if exc.args else exc)) from None
        card = None
        if via == "run":
            runner = _runner(self.factory, pid)
            if runner is None:
                raise _error(409, "Run it with a runner needs cell runners, which are not in this Rihmasto yet")
            from kernel.change import submit, triage

            text = (f"Deliver with the factory's builder cell ({runner}): {b['goal'][:300]}\n\n" + bridge.render(b))
            card = submit(project, persona=persona, person=person, text=text[:20000])
            triage(project, card["id"], model=None)
        msg = bridge.record(project, b, to=to, person_name=person, persona=persona, via=via)
        return 201, {"message": msg, "card": card["id"] if card else None}

    def post_channel(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._project(pid)
        person, persona = self._signer(body, pid)
        text = _text(body, "text", required=True)
        kind = _text(body, "kind", limit=16) or ("question" if ch.MENTION.search(text) else "note")
        refs = body.get("refs") if isinstance(body.get("refs"), dict) else None
        try:
            msg = ch.post(project, author=ch.person(person, persona), kind=kind, text=text,
                          thread=_text(body, "thread", limit=41) or None, refs=refs)
        except ch.ChannelRefused as exc:
            raise _error(400, str(exc)) from None
        model = getattr(self.server, "assistant_model", None)
        answer = None
        if channel_rihma.addressed(msg) and model is not None:
            threading.Thread(target=channel_rihma.reply, args=(project, msg), kwargs={"model": model},
                             name=f"channel-{pid}-{msg['id']}", daemon=True).start()
        elif channel_rihma.addressed(msg):
            answer = channel_rihma.reply(project, msg)
        return 201, {"message": msg, "answer": answer, "pending": answer is None and model is not None
                     and channel_rihma.addressed(msg) is not None}

    def post_channel_settle(self, pid: str, mid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._project(pid)
        person, persona = self._signer(body, pid)
        verdict = _text(body, "verdict", required=True, limit=16)
        try:
            msg = ch.get(project, mid)
        except ch.ChannelRefused as exc:
            raise _error(404, str(exc)) from None
        if msg["kind"] != "proposal" or msg.get("state") != "open":
            raise _error(409, f"{mid} is not an open proposal")
        answered = None
        if verdict == "confirm":
            qid = ((msg.get("refs") or {}).get("questions") or [None])[0]
            if not qid:
                raise _error(409, f"{mid} names no question")
            text = _text(body, "text", limit=4000) or writes.proposal_text(msg)
            _, answered = self.post_answer(pid, qid, {"text": text, "person": person,   # type: ignore[attr-defined]
                                                      "persona": persona})
        try:
            settled = ch.settle(project, mid, verdict=verdict, person_name=person, persona=persona,
                                note=_text(body, "note", limit=500))
        except ch.ChannelRefused as exc:
            raise _error(400, str(exc)) from None
        return 200, {"message": settled, "answered": answered}

    def post_channel_pause(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._project(pid)
        person, persona = self._signer(body, pid)
        try:
            return 200, {"paused": ch.pause(project, person_name=person, persona=persona,
                                            reason=_text(body, "reason", limit=500))}
        except ch.ChannelRefused as exc:
            raise _error(409, str(exc)) from None

    def post_channel_resume(self, pid: str, body: dict[str, Any], **_: object) -> Reply:
        project = self._project(pid)
        person, persona = self._signer(body, pid)
        try:
            released = ch.resume(project, person_name=person, persona=persona)
        except ch.ChannelRefused as exc:
            raise _error(409, str(exc)) from None
        model = getattr(self.server, "assistant_model", None)
        asked = [m for m in released if channel_rihma.addressed(m)]
        if asked:                                   # what waited is answered now, in order, beside the request
            threading.Thread(target=lambda: [channel_rihma.reply(project, m, model=model) for m in asked],
                             name=f"channel-{pid}-resume", daemon=True).start()
        return 200, {"released": [m["id"] for m in released]}
