"""The agent bridge's MCP tools (FR-BRG1, FR-CHN1), registered on Rihma's MCP server (mcp/server.py) with one line.

Reads: ``rihma_next`` (what the project waits for and the actions), ``rihma_plan`` (spec, contract, criteria,
tasks), ``rihma_questions`` (open questions and assumptions), ``rihma_handoff`` (the hand-off brief),
``rihma_feedback`` (review feedback, failed gates and checks, change cards since a time), ``rihma_insights``,
``rihma_alignment`` and ``rihma_health`` (when this build has them), ``rihma_channel_read`` (the agent channel).

Writes, each signed as the agent for the server's named operator, recorded, and posted in the agent channel:
``rihma_progress``, ``rihma_propose_answer`` (a suggestion a person confirms, never an answer), ``rihma_request_gate``,
``rihma_channel_post`` and ``rihma_ask_rihma`` (a question a Rihma agent answers from the records, or through a model
when the server has one for its agents: ``RIHMA_AGENT_MODEL=gnomon``). None decides a card. Holdout content is
redacted from every answer by the server, as for every other tool.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Any

from kernel import agent_bridge as bridge
from kernel import agent_channel as ch
from kernel import agent_writes as writes
from kernel import channel_rihma

LIST = re.compile(r"[,\s]+")


def _items(text: str | None) -> list[str]:
    return [x for x in LIST.split(text or "") if x]


def register(ns: dict[str, Any]) -> None:
    """Add the bridge's tools to the server's table and their handlers to its class (``ns``: the server's globals)."""
    p, pid_arg = ns["_p"], ns["PID_ARG"]
    agent_args = {"agent": p("Your name as an agent, for example claude-code, codex or cursor (default: agent).",
                             required=False, limit=41),
                  "harness": p("Optional: the harness and version, for example 'claude-code 2.1'.", required=False,
                               limit=80)}
    thread = {"thread": p("Optional: a thread of the channel (default: main).", required=False, limit=41)}
    T = ns["TOOLS"]
    T.update({
        "rihma_next": {"title": "What the project waits for", "read": True, "params": {"pid": pid_arg},
                       "description": "What a project waits for, who can act, and the actions that move it forward, "
                                      "each with its cockpit control and command line."},
        "rihma_plan": {"title": "The plan", "read": True, "params": {"pid": pid_arg},
                       "description": "A project's spec in short, its contract's requirements with each criterion's "
                                      "given, when and then, and its tasks with their state."},
        "rihma_questions": {"title": "Open questions", "read": True, "params": {"pid": pid_arg},
                            "description": "The open questions and assumptions. People answer them; "
                                           "rihma_propose_answer suggests an answer for a person to confirm."},
        "rihma_handoff": {"title": "Hand-off brief", "read": True,
                          "params": {"pid": pid_arg, "change": p("Optional: a change card, such as C-0004.",
                                                                 required=False, limit=12),
                                     "to": p("Which agent the brief is for.", required=False, limit=16,
                                             enum=list(bridge.AGENTS))},
                          "description": "The project's hand-off brief for a coding agent: the goal or the change, the "
                                         "criteria, open questions, the plan, findings, failed gates and checks, the "
                                         "conventions, how to run the tests and how to report back."},
        "rihma_feedback": {"title": "Feedback since", "read": True,
                           "params": {"pid": pid_arg, "since": p("Optional: a time, such as 2026-11-24T10:00:00Z.",
                                                                 required=False, limit=32)},
                           "description": "Review feedback, failed gates and checks, change cards, settled proposals "
                                          "and people's messages in the channel, since a time."},
        "rihma_insights": {"title": "Insights", "read": True, "params": {"pid": pid_arg},
                           "description": "The project's key figures per dimension (health, drift, QA...), when "
                                          "Insights is in this Rihmasto."},
        "rihma_alignment": {"title": "Alignment gaps", "read": True, "params": {"pid": pid_arg},
                            "description": "The open gaps between the repository and the contract, when repository "
                                           "alignment is in this Rihmasto."},
        "rihma_health": {"title": "Health checks", "read": True, "params": {"pid": pid_arg},
                         "description": "The project's checks and the ones failing, when checks are in this Rihmasto."},
        "rihma_channel_read": {"title": "Read the agent channel", "read": True,
                               "params": {"pid": pid_arg, "since": p("Optional: after this message id (M-0007) or "
                                                                     "time.", required=False, limit=32), **thread},
                               "description": "The project's agent channel: people, Rihma's agents, coding agents and "
                                              "results, oldest first, with what each message refers to."},
        "rihma_progress": {"title": "Post progress", "read": False,
                           "params": {"pid": pid_arg, "text": p("What you did, in plain words.", limit=8000),
                                      "files": p("Optional: files you touched, comma separated.", required=False,
                                                 limit=4000),
                                      "criteria": p("Optional: criteria you believe you addressed, comma separated.",
                                                    required=False, limit=2000),
                                      "commit": p("Optional: the commit.", required=False, limit=64),
                                      **agent_args, **thread},
                           "description": "Post your progress to the project's timeline and agent channel, signed as "
                                          "you for this server's operator. It decides nothing."},
        "rihma_propose_answer": {"title": "Propose an answer", "read": False,
                                 "params": {"pid": pid_arg,
                                            "question": p("The open question, such as Q-002.", limit=12),
                                            "text": p("The answer you suggest.", limit=4000), **agent_args, **thread},
                                 "description": "Suggest an answer to an open question. It becomes a proposal in the "
                                                "channel that a person confirms or rejects; it is never an answer by "
                                                "itself."},
        "rihma_request_gate": {"title": "Request the gate", "read": False,
                               "params": {"pid": pid_arg, "head": p("Optional: the commit to check (default: the "
                                                                    "branch head).", required=False, limit=64),
                                          "check": p("Optional: an enabled check to run instead.", required=False,
                                                     limit=64), **agent_args, **thread},
                               "description": "Ask the gate to check a commit of an attached repository (or an enabled "
                                              "check to run). The result posts itself into the agent channel."},
        "rihma_channel_post": {"title": "Post in the agent channel", "read": False,
                               "params": {"pid": pid_arg, "text": p("The message. Name @analyst or @verifier to ask "
                                                                    "Rihma.", limit=8000),
                                          "kind": p("What it is.", required=False, limit=16,
                                                    enum=["question", "progress", "feedback", "plan", "note"]),
                                          "criteria": p("Optional: criteria it refers to, comma separated.",
                                                        required=False, limit=2000),
                                          "commit": p("Optional: a commit it refers to.", required=False, limit=64),
                                          **agent_args, **thread},
                               "description": "Post a message in the project's agent channel, signed as you for this "
                                              "server's operator. A question naming @analyst or @verifier is answered "
                                              "by a Rihma agent."},
        "rihma_ask_rihma": {"title": "Ask Rihma", "read": False,
                            "params": {"pid": pid_arg, "question": p("Your question, for example 'what does "
                                                                     "FR-X-AC-2 mean?' or 'why did the gate fail?'",
                                                                     limit=4000),
                                       "commit": p("Optional: a commit the question is about.", required=False,
                                                   limit=64), **agent_args, **thread},
                            "description": "Ask a Rihma agent in the project's channel. It answers from the records "
                                           "(criteria, the gate, the next step, open questions) with its sources, or "
                                           "through a model when one is set up for Rihma's agents."},
    })
    ns["WRITE_ROUTES"].update({n: "post_channel" for n in ("rihma_progress", "rihma_propose_answer",
                                                          "rihma_request_gate", "rihma_channel_post",
                                                          "rihma_ask_rihma")})
    cls, tool_error = ns["RihmaMCP"], ns["ToolError"]

    def refused(fn):
        def wrapped(self, *args, **kwargs):
            try:
                return fn(self, *args, **kwargs)
            except (ch.ChannelRefused, ValueError, KeyError, LookupError) as exc:
                raise tool_error(str(exc.args[0] if isinstance(exc, KeyError) and exc.args else exc)) from None
        wrapped.__name__ = fn.__name__
        return wrapped

    for name, fn in _handlers(ns).items():
        setattr(cls, "tool_" + name, refused(fn))


def _handlers(ns: dict[str, Any]) -> dict[str, Any]:
    note = ns["DECIDE_IN_COCKPIT"]

    def author(self, agent: str | None, harness: str | None) -> dict[str, Any]:
        return ch.agent((agent or "agent").lower(), self.person, self.persona, harness)

    def writing(self, tool: str, pid: str):
        project = self._project(pid)
        self._module_on(tool, pid)
        self._granted(pid)
        return project

    def model(self) -> Any:
        given = getattr(self, "channel_model", None)
        if given is not None or os.environ.get("RIHMA_AGENT_MODEL") != "gnomon":
            return given
        from kernel.assistant import assistant_model

        self.channel_model = assistant_model()
        return self.channel_model

    def optional(value: Any, what: str) -> Any:
        return value if value is not None else {"available": False, "note": f"{what} is not in this Rihmasto yet"}

    def next_(self, pid: str) -> dict:
        return writes.next_view(self._project(pid)) | {"note": note}

    def plan(self, pid: str) -> dict:
        return writes.plan_view(self._project(pid))

    def questions(self, pid: str) -> dict:
        return writes.questions_view(self._project(pid))

    def handoff(self, pid: str, change: str | None = None, to: str | None = None) -> dict:
        project = self._project(pid)
        b = bridge.brief(project, change=change)
        return {"brief": b, "markdown": bridge.render(b),
                "use": bridge.for_agent(self.kernel_factory, project, b, to=to or "generic", operator=self.person,
                                        persona=self.persona)}

    def feedback(self, pid: str, since: str | None = None) -> dict:
        return writes.feedback(self._project(pid), since)

    def insights(self, pid: str) -> dict:
        self._project(pid)
        return {"project": pid, "insights": optional(bridge.insights(self.kernel_factory, pid), "Insights")}

    def alignment(self, pid: str) -> dict:
        return {"project": pid, "gaps": optional(bridge.alignment_gaps(self._project(pid)), "Repository alignment")}

    def health(self, pid: str) -> dict:
        project = self._project(pid)
        store = bridge.optional("kernel.checks.store")
        enabled = sorted(store.enabled(project)) if store is not None else None
        return {"project": pid, "enabled": optional(enabled, "Checks"),
                "failing": optional(bridge.failed_checks(project), "Checks")}

    def channel_read(self, pid: str, since: str | None = None, thread: str | None = None) -> dict:
        project = self._project(pid)
        doc = ch.read(project)
        return {"project": pid, "paused": doc.get("paused"),
                "messages": ch.messages(project, since=since, thread=thread, held=False)}

    def progress(self, pid: str, text: str, files: str | None = None, criteria: str | None = None,
                 commit: str | None = None, agent: str | None = None, harness: str | None = None,
                 thread: str | None = None) -> dict:
        project = writing(self, "rihma_progress", pid)
        msg = writes.progress(project, author(self, agent, harness), text, files=_items(files),
                              criteria=_items(criteria), commit=commit, thread=thread)
        return {"message": msg, "signed": self._signed(project, "progress", msg["id"]),
                "note": "Posted to the timeline and the agent channel. It decides nothing."}

    def propose_answer(self, pid: str, question: str, text: str, agent: str | None = None,
                       harness: str | None = None, thread: str | None = None) -> dict:
        project = writing(self, "rihma_propose_answer", pid)
        msg = writes.propose_answer(project, author(self, agent, harness), question, text, thread=thread)
        return {"message": msg, "signed": self._signed(project, "propose_answer", msg["id"]),
                "note": "A proposal: a person confirms or rejects it in the cockpit. The question stays open until "
                        "then."}

    def request_gate(self, pid: str, head: str | None = None, check: str | None = None, agent: str | None = None,
                     harness: str | None = None, thread: str | None = None) -> dict:
        project = writing(self, "rihma_request_gate", pid)
        req = writes.request_gate(project, author(self, agent, harness), head=head, check=check, thread=thread)
        result = None
        if req["run"] is not None and getattr(self, "gate_sync", False):
            result = req["run"](getattr(self, "gate_fn", None))
        elif req["run"] is not None:
            threading.Thread(target=req["run"], name=f"gate-{pid}", daemon=True).start()
        return {"request": req["request"], "result": result, "signed": self._signed(project, "request_gate",
                                                                                     req["request"]["id"]),
                "note": "The result posts itself into the agent channel: rihma_channel_read shows it."}

    def channel_post(self, pid: str, text: str, kind: str | None = None, criteria: str | None = None,
                     commit: str | None = None, agent: str | None = None, harness: str | None = None,
                     thread: str | None = None) -> dict:
        project = writing(self, "rihma_channel_post", pid)
        refs = {k: v for k, v in (("criteria", _items(criteria)), ("commits", [commit] if commit else [])) if v}
        msg = ch.post(project, author=author(self, agent, harness), kind=kind or "note", text=text, thread=thread,
                      refs=refs)
        answer = channel_rihma.reply(project, msg, model=model(self))
        return {"message": msg, "answer": answer, "signed": self._signed(project, "channel_post", msg["id"])}

    def ask_rihma(self, pid: str, question: str, commit: str | None = None, agent: str | None = None,
                  harness: str | None = None, thread: str | None = None) -> dict:
        project = writing(self, "rihma_ask_rihma", pid)
        msg = ch.post(project, author=author(self, agent, harness), kind="question", text=question, thread=thread,
                      refs={"commits": [commit]} if commit else None, ask=True)
        answer = channel_rihma.reply(project, msg, model=model(self))
        return {"question": msg, "answer": answer, "signed": self._signed(project, "ask_rihma", msg["id"]),
                "note": "Rihma's agents answer from the records and decide nothing." if answer else
                        "Not answered now: the channel is paused, or a limit holds. rihma_channel_read shows why."}

    return {"next": next_, "plan": plan, "questions": questions, "handoff": handoff, "feedback": feedback,
            "insights": insights, "alignment": alignment, "health": health, "channel_read": channel_read,
            "progress": progress, "propose_answer": propose_answer, "request_gate": request_gate,
            "channel_post": channel_post, "ask_rihma": ask_rihma}
