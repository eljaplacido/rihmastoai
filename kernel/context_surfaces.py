"""The context packs of the surfaces people and coding agents talk to (FR-CTX1; the roles are kernel/context_packs.py).

- **Ask Rihma**: the assistant's prompt for a question, from the snapshot of the person's persona
  (kernel/assistant.py ``prompt``, the same call ``ask`` makes);
- **goal help**: the plan's prompt (kernel/copilot.py ``prompt``, as ``model_plan`` builds it);
- **an agent channel answer**: what a Rihma agent reads for a question the records do not answer by rule
  (kernel/channel_rihma.py ``_records_prompt``);
- **the hand-off brief**: the Markdown a coding agent is given (kernel/agent_bridge.py ``render``);
- **the MCP tools**: the tool list an agent reads at the start of a session, and each read tool's answer for this
  project, exactly as the server serves them (mcp/server.py).
"""

from __future__ import annotations

import json
from typing import Any

from kernel import context_parts as cp

ASK = "How is this project going, and what waits on me?"
GOAL = "Deploy it to a test environment"
CHANNEL = "Is the way this is built sound for the people who use it?"
MCP_PERSON = "Context view"


def _unavailable(why: str) -> Exception:
    from kernel.context_packs import Unavailable

    return Unavailable(why)


def _assistant(factory: Any, project: Any, target: str | None, *, persona: str | None = None,
               question: str | None = None, **_: Any) -> dict[str, Any]:
    from kernel import assistant, assistant_rules
    from kernel.modules import hidden_ids

    q, who = question or ASK, persona or "product_owner"
    hidden = hidden_ids(project)
    snap = assistant.snapshot(factory, project=project, persona=who)
    prompt = assistant.prompt(q, snap, persona=who, view=target, hints=assistant.find_in_map(q, hidden=hidden),
                              hidden=hidden)
    parts = cp.split(prompt, [
        (None, "The rules", "kernel/assistant.py _catalogue", "static", "instructions"),
        ("The cockpit's views (", "The cockpit's views", "cockpit/ui_map.json views", "static", "catalogue"),
        ("Its controls", "The cockpit's controls, by id and label", "cockpit/ui_map.json controls", "static",
         "catalogue"),
        ("Actions you may propose", "Actions and the answer's shape", "kernel/assistant_rules.py ACTIONS", "static",
         "instructions"),
        ("\nThe person may ask you to reshape", "The widget library", "kernel/assistant.py _ui_rules", "static",
         "catalogue"),
        ("\nThe person is the ", "Who is asking, and where", "the person chip", "call", "records"),
        ("Map entries that match the question", "Map entries that match the question, in full",
         "cockpit/ui_map.json, kernel/assistant.py find_in_map", "call", "catalogue"),
        ("The question:", "The question", "the person", "call", "request"),
        ("Snapshot (JSON):", "The snapshot", "kernel/assistant_snapshot.py snapshot, fit_snapshot", "call",
         "records")])
    sent = json.loads(prompt.split("Snapshot (JSON):\n", 1)[1])
    compressed = [{"what": "the cockpit's controls", "how": "named by id and label; where each is and what it does "
                                                            "is given for the entries that match the question",
                   "why": "the full map is about 30,000 characters, said again in every question (FR-CTX1)"},
                  {"what": "the cockpit's views", "how": f"each purpose cut at a word to about "
                                                         f"{assistant_rules.CATALOGUE_PURPOSE} characters; a view "
                                                         "that matches the question is given whole",
                   "why": "the longest purposes say over 1,000 characters each, again in every question"}]
    budget = f"SNAPSHOT_BUDGET ({assistant.SNAPSHOT_BUDGET:,} characters)"
    compressed += [{"what": n, "how": "left out of the snapshot by whole items, and named in its not_shown",
                    "why": budget} for n in sent.get("not_shown", [])]
    return cp.pack(project.pid, "assistant", label="Ask Rihma", role="assistant", surface="Ask Rihma",
                   where="kernel/assistant.py prompt", text=prompt, parts=parts, target=q, compressed=compressed,
                   excluded=[{"what": "other projects' card titles", "why": "with a project open, another product's "
                                                                            "cards are counts only"},
                             {"what": "decision reasons", "why": "a decided card shows its verdict and who decided, "
                                                                 "never the reason (the red team's canaries)"},
                             {"what": "a holdout ruling's body and reason", "why": "they stay in the holdout custody"},
                             {"what": "anything outside the snapshot", "why": "the assistant answers only from it and "
                                                                              "says what it cannot see"}],
                   note=f"For the {who} persona; the snapshot is the persona's own (whose cards are \"yours\").")


def _goal(factory: Any, project: Any, target: str | None, *, question: str | None = None,
          **_: Any) -> dict[str, Any]:
    from kernel import copilot
    from kernel.copilot_catalog import catalogue

    goal = question or target or GOAL
    cat = catalogue(factory, project)
    rules = copilot.rule_plan(factory, project, goal, cat=cat)
    prompt = copilot.prompt(goal, rules["facts"], cat, rules)
    parts = cp.split(prompt, [
        (None, "Instructions and the answer's shape", "kernel/copilot.py prompt", "static", "instructions"),
        ("What this Rihmasto has (JSON):", "What this Rihmasto has", "kernel/copilot_catalog.py catalogue", "static",
         "catalogue"),
        ("The project's records (JSON):", "The project's records", "kernel/copilot.py facts", "project", "records"),
        ("The rule-based plan, to improve on", "The rule-based plan", "kernel/copilot.py rule_plan", "call",
         "records"),
        ("The goal:", "The goal", "the person", "call", "request")])
    cut = [{"what": "the rule-based plan's steps", "how": "whole steps left out, and the prompt says how many",
            "why": f"RULE_STEPS_BUDGET ({copilot.RULE_STEPS_BUDGET:,} characters)"}]
    cut = cut if "steps are not shown" in prompt else []
    return cp.pack(project.pid, "goal", label="Goal help", role="assistant", surface="goal help",
                   where="kernel/copilot.py prompt", text=prompt, parts=parts, target=goal, compressed=cut,
                   excluded=[{"what": "the canon's texts", "why": "the plan rests on the project's facts (stage, "
                                                                  "contract, posture, integrations) and the catalogue"},
                             cp_out("holdouts"), cp_out("others")])


def cp_out(kind: str) -> dict[str, str]:
    from kernel import context_packs as packs

    return {"holdouts": packs.HOLDOUTS_OUT, "others": packs.OTHERS_OUT, "secrets": packs.SECRETS_OUT}[kind]


def _channel(factory: Any, project: Any, target: str | None, *, question: str | None = None,
             **_: Any) -> dict[str, Any]:
    from kernel import channel_rihma

    q = question or CHANNEL
    role = target if target in ("analyst", "verifier") else "analyst"
    if channel_rihma.by_rule(project, q) is not None:
        raise _unavailable("the records answer that by rule: no model is asked, so no prompt is sent")
    prompt = channel_rihma._records_prompt(project, {"text": q, "refs": {}}, role)
    parts = cp.split(prompt, [
        (None, "Who answers, and how", "kernel/channel_rihma.py _records_prompt", "project", "instructions"),
        ("The contract's requirements", "The contract's requirements", "contract.json", "project", "records"),
        ("There is no contract yet", "The contract's requirements", "contract.json", "project", "records"),
        ("\nThe records the question names", "The records the question names", "the message's refs", "call",
         "records"),
        ("The question:", "The question", "the coding agent", "call", "request")])
    return cp.pack(project.pid, "channel", label="Agent channel answer", role=role, surface="agent channel",
                   where="kernel/channel_rihma.py _records_prompt", text=prompt, parts=parts, target=q,
                   compressed=[{"what": "the requirements", "how": "the first ten, each statement to 120 characters",
                                "why": "an answer of at most five sentences"}],
                   excluded=[cp_out("holdouts"), {"what": "people's decisions", "why": "a Rihma agent decides no "
                                                                                       "card and answers no person's "
                                                                                       "question"}, cp_out("others")],
                   note="Only a question the records cannot answer by rule reaches a model; most are answered from "
                        "the contract, the gate, the next step or the open items.")


def _handoff(factory: Any, project: Any, target: str | None, **_: Any) -> dict[str, Any]:
    from kernel import agent_bridge as bridge

    try:
        text = bridge.render(bridge.brief(project, change=target or None))
    except KeyError as exc:
        raise _unavailable(f"no change card {exc.args[0] if exc.args else target}") from None
    parts = cp.split(text, [
        (None, "The project and the goal", "project.json, canon/goal.md or the change card", "project", "request"),
        ("## Criteria to meet", "Criteria to meet", "contract.json", "project", "records"),
        ("## Open questions", "Open questions and assumptions", "canon", "project", "records"),
        ("## The plan", "The plan", "contract.json, tasks.json", "project", "records"),
        ("## Feedback to address", "Feedback to address", "the gate, the checks, review, alignment", "project",
         "records"),
        ("## Insights", "Insights", "kernel/insights", "project", "records"),
        ("## The project's conventions", "The project's conventions", "kernel/ide.py", "project", "conventions"),
        ("## How to run the tests", "How to run the tests", "the stated test command, or the paved road's",
         "project", "instructions"),
        ("## How to report back", "How to report back", "kernel/agent_bridge.py REPORT_BACK", "project",
         "instructions")])
    return cp.pack(project.pid, "handoff", label="Hand-off brief", role=None, surface="hand-off brief",
                   where="kernel/agent_bridge.py render", text=text, parts=parts, target=target or None,
                   compressed=[{"what": "the criteria, questions and plan", "how": f"at most {bridge.MAX_CRITERIA} "
                                                                                   f"criteria, {bridge.MAX_ITEMS} "
                                                                                   "items of each list, 30 tasks",
                                "why": "a brief an agent reads whole"}],
                   excluded=[cp_out("holdouts"), {"what": "the canon's discussion and decision reasons",
                                                  "why": "the agent gets what to build and the open items, never "
                                                         "who argued what"}, cp_out("secrets")])


def _server(factory: Any, persona: str | None) -> Any:
    from mcp.server import RihmaMCP

    try:
        return RihmaMCP(factory, person=MCP_PERSON, persona=persona or "developer")
    except Exception as exc:  # noqa: BLE001 - enforced access signs as the local user: say why it is not shown
        raise _unavailable(f"the MCP server cannot be started here ({exc})") from None


def outputs(factory: Any, project: Any, *, persona: str | None = None) -> list[dict[str, Any]]:
    """Each read tool's answer for this project as the server serves it: its text block, measured."""
    from mcp.server import TOOLS

    server = _server(factory, persona)
    out = []
    for name, t in TOOLS.items():
        if not t["read"] or name == "rihma_ask":
            continue
        args = {"pid": project.pid} if "pid" in t["params"] else {}
        res = server.tools_call({"name": name, "arguments": args})
        text = "".join(c.get("text", "") for c in res.get("content") or [])
        out.append({"tool": name, "chars": len(text), "tokens": cp.tokens(len(text)), "is_error": res.get("isError"),
                    "structured_chars": len(json.dumps(res.get("structuredContent"), ensure_ascii=False,
                                                       separators=(",", ":"), default=str)),
                    "over_budget": cp.tokens(len(text)) > cp.OUTPUT_BUDGET, "content": text})
    return out


def _mcp(factory: Any, project: Any, target: str | None, *, persona: str | None = None, **_: Any) -> dict[str, Any]:
    from mcp.server import tool_list

    _server(factory, persona)
    lines = [json.dumps(t, ensure_ascii=False, separators=(",", ":")) + "\n" for t in tool_list()]
    parts = [cp.part(f"Tool {t['name']}", line, "mcp/server.py TOOLS, mcp/bridge_tools.py", "static", kind="tool")
             for t, line in zip(tool_list(), lines, strict=True)]
    p = cp.pack(project.pid, "mcp", label="MCP tools", role=None, surface="MCP tools",
                where="mcp/server.py tools/list and tools/call", text="".join(lines), parts=parts,
                compressed=[{"what": "each tool's answer", "how": "JSON without indentation; the hand-off brief "
                                                                  "once, in Markdown, with its items by reference",
                             "why": "a third smaller, and nothing said twice (FR-CTX1)"}],
                excluded=[cp_out("holdouts"), {"what": "decisions", "why": "no tool decides a card, answers a "
                                                                         "question, approves or deploys"}],
                note="The tool list is read once per session; each tool's answer is in outputs, measured against "
                     f"{cp.OUTPUT_BUDGET:,} tokens.")
    p["outputs"] = outputs(factory, project, persona=persona)
    return p


SURFACE_PACKS = {"assistant": _assistant, "goal": _goal, "channel": _channel, "handoff": _handoff, "mcp": _mcp}
