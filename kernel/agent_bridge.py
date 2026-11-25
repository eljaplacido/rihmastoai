"""The agent bridge, Rihmasto to agents (FR-BRG1, docs/guides/agentic-help.md): a project's hand-off brief for a
coding agent, and how each agent takes it.

The brief (``brief``) carries what an agent needs to work on the project the way Rihmasto governs it:

- the goal or the change (a change card's text), and the accepted contract's criteria relevant to it;
- the open questions and assumptions, never answered here; the plan (the tasks and their state) and, for a goal,
  the steps of its plan (kernel/copilot.py);
- the assessment's findings, review feedback, the gates that failed and the checks that fail, and the insights that
  matter (drift, failing gates), each when this build has it;
- the project's own conventions (its AGENTS.md and the commands it states, kernel/ide.py when present), how to run
  the tests, and how to report back: the MCP tools and the agent channel (kernel/agent_channel.py).

``for_agent`` gives the agent-specific way to use it: a prompt file, the MCP configuration (Rihmasto's own server,
signed with the operator's name) and the command line (`claude -p`, `codex exec`, `opencode run`; Cursor reads the
prompt and its MCP file). Building the brief writes nothing; ``record`` notes that a person gave a hand-off, in the
ledger and the channel, never the brief's text in the ledger. Holdout scenarios are never in a brief.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from kernel import agent_channel as ch
from kernel.copilot_catalog import optional

AGENTS = {"claude-code": "Claude Code", "codex": "Codex", "opencode": "OpenCode", "cursor": "Cursor",
          "generic": "any coding agent"}
MAX_CRITERIA = 40
MAX_ITEMS = 12
REPORT_BACK = [
    "Post what you did to the project's agent channel: `rihma_progress` over MCP (what you did, the files you "
    "touched, the criteria you believe you addressed), or `rihmasto channel {pid} post --as <agent> --kind progress "
    "--text \"...\" --person <operator> --persona developer` without MCP.",
    "Ask Rihma when something is unclear: `rihma_ask_rihma` (a criterion, why the gate failed, what is next).",
    "Never answer an open question yourself: `rihma_propose_answer` suggests one, and a person confirms it.",
    "When a commit is ready, `rihma_request_gate` asks the gate to check it; its result comes back in the channel.",
    "A new requirement is a decision: file it with `rihma_report_change` before you build it.",
]


def _criteria(project: Any, wanted: set[str]) -> list[dict[str, Any]]:
    contract = project.read("contract.json") or {}
    out = []
    for r in contract.get("requirements", []):
        if wanted and r["id"] not in wanted:
            continue
        for c in r.get("acceptance", []):
            out.append({"id": c["id"], "requirement": r["id"], "statement": r["statement"][:300],
                        "given": c.get("given"), "when": c.get("when"), "then": c.get("then")})
    return out[:MAX_CRITERIA]


def _change(project: Any, card_id: str | None) -> dict[str, Any] | None:
    from kernel.canon import Canon

    if not card_id:
        return None
    card = Canon(project).get_card(card_id.upper())
    if card["kind"] != "change":
        raise ValueError(f"{card['id']} is a {card['kind']} card, not a change")
    payload = card.get("payload") or {}
    return {"id": card["id"], "title": card["title"], "state": card["state"],
            "text": str(payload.get("text") or card.get("body") or card["title"])[:4000],
            "requirements": list((card.get("refs") or {}).get("requirements") or [])}


def _findings(project: Any) -> list[str]:
    from kernel.assess import history, load, summary

    if not history(project):
        return []
    try:
        return [str(f) for f in summary(load(project))["findings"]][:MAX_ITEMS]
    except (LookupError, OSError, KeyError, ValueError):
        return []


def failed_gates(project: Any, since: str | None = None) -> list[dict[str, Any]]:
    out = []
    for r in project.ledger().of_kind("gate"):
        g, at = r["event"]["payload"], str(r["event"].get("at") or "")
        if since and at <= since:
            continue
        if g.get("verdict") not in ("passed", "warranted", "pass"):
            out.append({"task": g.get("task"), "round": g.get("round"), "verdict": g.get("verdict"), "at": at,
                        "failing": [k for k, v in (g.get("signals") or {}).items() if v not in ("passed", "pass")],
                        "objections": [str(o)[:300] for o in g.get("objections") or []][:3]})
    return out[-5:]


def failed_checks(project: Any) -> list[dict[str, Any]] | None:
    store = optional("kernel.checks.store")
    if store is None:
        return None
    try:
        rows = []
        for key in store.enabled(project):
            last = (store.results(project, key, limit=1) or [None])[-1]
            if last and last.get("verdict") == "failed":
                rows.append({"check": key, "summary": str(last.get("summary") or "")[:300], "at": last.get("at")})
        return rows
    except Exception:  # noqa: BLE001 - a check store that cannot be read is "not available", never a crash
        return None


def insights(factory: Any, pid: str) -> dict[str, Any] | None:
    mod = optional("kernel.insights")
    if mod is None:
        return None
    try:
        return mod.summary(factory, pid=pid)
    except Exception:  # noqa: BLE001
        return None


def alignment_gaps(project: Any) -> list[dict[str, Any]] | None:
    mod = optional("kernel.alignment_records")
    if mod is None:
        return None
    try:
        return [{"id": g.get("id"), "title": g.get("title"), "detail": str(g.get("detail") or "")[:300]}
                for g in mod.open_gaps(project)][:MAX_ITEMS]
    except Exception:  # noqa: BLE001
        return None


def review_feedback(project: Any) -> list[dict[str, Any]] | None:
    """What the Review says went wrong and waits on a person for this project (kernel/review.py ``review``, the
    last seven days, without diffs): the agent's feedback. None when the Review is not in this build."""
    mod = optional("kernel.review")
    if mod is None:
        return None
    try:
        out = mod.review(project.factory, project=project.pid, since="7d", diffs=False)
    except (KeyError, ValueError, OSError):
        return None
    return [{"group": g["id"], "kind": it["kind"], "title": str(it["title"])[:300], "at": it.get("at")}
            for g in out["groups"] if g["id"] in ("wrong", "waiting") for it in g["items"]][:MAX_ITEMS]


def conventions(project: Any) -> dict[str, Any] | None:
    ide = optional("kernel.ide")
    if ide is None or ide.kind_of(project) is None:
        return None
    try:
        ctx = ide.context(project)
    except Exception:  # noqa: BLE001
        return None
    return {"read_from": ctx.get("read_from"), "stated": ctx.get("stated") or [],
            "instructions": [str(i.get("path") or i) for i in ctx.get("instructions") or []][:MAX_ITEMS]}


def _tests(project: Any, conv: dict[str, Any] | None) -> list[str]:
    stated = [s["command"] for s in (conv or {}).get("stated") or [] if isinstance(s, dict) and s.get("kind") == "test"]
    if stated:
        return stated
    if project.meta.get("source_kind") == "attached":
        return [f"the repository's own test command; `rihmasto repo gate {project.pid} --head <commit>` runs the gate"]
    return ["python -m unittest discover -s tests (the paved road's product suite)",
            f"`rihmasto workspace submit {project.pid} <folder>` sends your commits through the gate"]


def _plan(project: Any) -> list[dict[str, Any]]:
    """The contract's tasks with their state, then any task the records hold beyond them."""
    tasks = project.read("tasks.json", {}) or {}
    titles = {t["id"]: t for t in (project.read("contract.json") or {}).get("tasks", [])}
    ids = [*titles, *(t for t in tasks if t not in titles)]
    return [{"id": t, "title": (titles.get(t) or {}).get("title"), "criteria": (titles.get(t) or {}).get("criteria"),
             "status": (tasks.get(t) or {}).get("status") or "pending"} for t in ids][:30]


def _open(project: Any) -> dict[str, Any]:
    from kernel.canon import Canon

    canon = Canon(project)
    return {"questions": [{"id": q["id"], "text": q["text"][:300], "blocking": q["blocking"]}
                          for q in canon.questions("open")][:MAX_ITEMS],
            "assumptions": [{"id": a["id"], "text": a["text"][:300], "due": a.get("due")}
                            for a in canon.assumptions("open")][:MAX_ITEMS],
            "canon_goal": canon.goal}


def _feedback(project: Any) -> dict[str, Any]:
    """What came back on the work: findings, review, failed gates and checks, insights, alignment gaps."""
    return {"findings": _findings(project), "review": review_feedback(project), "failed_gates": failed_gates(project),
            "failed_checks": failed_checks(project), "insights": insights(project.factory, project.pid),
            "alignment": alignment_gaps(project)}


def _goal_steps(project: Any, goal: str | None) -> list[str] | None:
    if not goal:
        return None
    from kernel.copilot import rule_plan

    return [s["title"] for s in rule_plan(project.factory, project, goal)["steps"]]


def brief(project: Any, *, change: str | None = None, goal: str | None = None) -> dict[str, Any]:
    """The hand-off brief for a coding agent: everything above, from the records, never a holdout."""
    from kernel.next_step import next_step

    meta = project.meta
    card = _change(project, change)
    opened = _open(project)
    conv = conventions(project)
    said = goal or (card["text"] if card else str(opened.pop("canon_goal") or meta.get("title") or ""))
    opened.pop("canon_goal", None)
    return {
        "project": {"id": project.pid, "title": meta.get("title"), "stage": meta.get("stage"),
                    "maturity": meta.get("maturity"), "source_kind": meta.get("source_kind"),
                    "confidential": bool(meta.get("confidential"))},
        "goal": said, "change": card,
        "criteria": _criteria(project, set(card["requirements"]) if card else set()),
        **opened, "plan": _plan(project), "plan_steps": _goal_steps(project, goal),
        "waits_for": next_step(project).get("waits_for"), **_feedback(project),
        "conventions": conv, "tests": _tests(project, conv),
        "report_back": [line.format(pid=project.pid) for line in REPORT_BACK],
    }


def _section(title: str, lines: list[str]) -> list[str]:
    return [f"## {title}", "", *(lines or ["- None."]), ""]


def _head(b: dict[str, Any]) -> list[str]:
    p = b["project"]
    kind = f", {p['source_kind']}" if p.get("source_kind") else ""
    out = [f"# Hand-off: {p['title']} (`{p['id']}`)", "",
           f"Governed in Rihmasto: stage {p['stage']}, maturity {p['maturity']}{kind}. It waits for {b['waits_for']}.",
           "", *_section("The goal", [b["goal"] or "None stated."])]
    if b["change"]:
        out += _section(f"The change {b['change']['id']}", [b["change"]["text"]])
    return out


def _work(b: dict[str, Any]) -> list[str]:
    crit = [f"- **{c['id']}** ({c['requirement']}): given {c['given']}, when {c['when']}, then {c['then']}"
            for c in b["criteria"]]
    asks = [f"- {q['id']}{' (blocking)' if q['blocking'] else ''}: {q['text']}" for q in b["questions"]]
    asks += [f"- {a['id']} (assumed, due {a['due']}): {a['text']}" for a in b["assumptions"]]
    plan = [f"- {t['id']}: {t['title'] or ''} ({t['status']})" for t in b["plan"]]
    plan += [f"- Goal step: {s}" for s in b["plan_steps"] or []]
    return (_section("Criteria to meet", crit) + _section("Open questions (people answer these; propose, never decide)",
                                                          asks) + _section("The plan", plan))


def _feedback_lines(b: dict[str, Any]) -> list[str]:
    lines = [f"- Finding: {f}" for f in b["findings"]]
    lines += [f"- Review ({r['group']}): {r['title']}" if isinstance(r, dict) else f"- Review: {r}"
              for r in b["review"] or []]
    lines += [f"- Gate {g['task']} round {g['round']}: {g['verdict']}; failing {', '.join(g['failing']) or '-'}"
              for g in b["failed_gates"]]
    lines += [f"- Check {c['check']} failed: {c['summary']}" for c in b["failed_checks"] or []]
    lines += [f"- Alignment gap: {g['title']}" for g in b["alignment"] or []]
    out = _section("Feedback to address", lines)
    if b["insights"]:
        out += _section("Insights", [f"- {k}: {v}" for k, v in b["insights"].items() if isinstance(v, dict)])
    return out


def render(b: dict[str, Any]) -> str:
    """The brief as the Markdown an agent reads."""
    conv = b["conventions"] or {}
    out = _head(b) + _work(b) + _feedback_lines(b)
    out += _section("The project's conventions", [f"- Read from {conv.get('read_from')}"] if conv else [])
    out += _section("How to run the tests", [f"- {t}" for t in b["tests"]])
    out += _section("How to report back", [f"- {line}" for line in b["report_back"]])
    out += ["Never edit `.gnomon/`, `contract.json` or `factory/`. Holdout scenarios are never given to an agent."]
    return "\n".join(out) + "\n"


def for_agent(factory: Any, project: Any, b: dict[str, Any], *, to: str = "generic", operator: str = "<your name>",
              persona: str = "developer") -> dict[str, Any]:
    """How ``to`` takes the brief: the prompt file, the MCP configuration and the command line."""
    from kernel.workspace import mcp_config

    if to not in AGENTS:
        raise ValueError(f"to is one of {', '.join(AGENTS)}")
    pid = project.pid
    prompt_file = f".rihmasto/handoff-{pid}.md"
    cfg = mcp_config(factory, person=operator, persona=persona)
    server = cfg["mcpServers"]["rihma"]
    run = {"claude-code": f'claude -p "$(cat {prompt_file})" --mcp-config .mcp.json',
           "codex": f'codex exec "$(cat {prompt_file})"', "opencode": f'opencode run "$(cat {prompt_file})"',
           "cursor": f"open the chat in Cursor and attach {prompt_file}; Rihma's tools come from .cursor/mcp.json",
           "generic": f"give your agent {prompt_file} as its task, and Rihma's MCP server for its tools"}[to]
    mcp = {"claude-code": {"file": ".mcp.json", "json": cfg},
           "cursor": {"file": ".cursor/mcp.json", "json": {"mcpServers": {"rihma": {k: v for k, v in server.items()
                                                                                    if k != "type"}}}},
           "codex": {"file": "~/.codex/config.toml", "toml": "[mcp_servers.rihma]\n"
                     f"command = {json.dumps(server['command'])}\nargs = ["
                     + ", ".join(json.dumps(a) for a in server["args"]) + "]\n"}}.get(to, {"file": ".mcp.json",
                                                                                         "json": cfg})
    return {"to": to, "label": AGENTS[to], "prompt_file": prompt_file, "mcp": mcp, "run": run,
            "note": "Save the brief as the prompt file in your working copy. Rihmasto never writes into your folder, "
                    "and the agent's writes come back as proposals and channel posts, signed for its operator."}


def digest(text: str) -> str:
    """The brief's fingerprint as the ledger keeps it."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def record(project: Any, b: dict[str, Any], *, to: str, person_name: str, persona: str, via: str) -> dict[str, Any]:
    """A person gave a hand-off: the ledger notes who, to which agent and the brief's sha256; the channel shows it."""
    text = render(b)
    msg = ch.post(project, author=ch.person(person_name, persona), kind="handoff",
                  text=f"Handed off to {AGENTS.get(to, to)} ({via})" + (f", for {b['change']['id']}" if b["change"]
                                                                       else "") + ".",
                  refs={"cards": [b["change"]["id"]] if b["change"] else [],
                        "criteria": [c["id"] for c in b["criteria"]][:20]})
    project.log("agent_handoff", {"to": to, "via": via, "person": person_name, "persona": persona,
                                  "change": b["change"]["id"] if b["change"] else None, "sha256": digest(text),
                                  "message": msg["id"]})
    return msg
