"""The compression audit: every context pack, MCP answer and command output against its budget (FR-CTX1).

`rihmasto context audit [<pid>]` and the cockpit's Context health measure, for each project:

- **over budget**: a pack over its role's budget (kernel/context_parts.py ECONOMY, or a quarter of the window);
- **said twice**: a line of 80 characters or more that appears in two parts of one pack, or twice in one;
- **stable prefix**: a part that changes more often placed before one that changes less (a ``call`` part before
  a ``static`` one), which defeats prompt caching for everything after it;
- **oversized output**: an MCP tool's answer or a command's JSON over OUTPUT_BUDGET tokens;
- **conventions sent to a role that does not need them**: the project's own conventions (CLAUDE.md, AGENTS.md,
  skills) in a pack other than the panel's, the builder's or a coding agent's brief.

Each finding carries a proposed compression (a summary, a reference instead of the full text, a shared prefix).
``FIXES`` lists what FR-CTX1 already compressed, measured before and after on the same fixture. The factory-wide
health is per role: average and largest pack, how many are over budget, and the cache-friendly prefix ratios.
Reading the audit writes nothing.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
from typing import Any

from kernel import context_packs as packs
from kernel import context_parts as cp

MIN_LINE = 80
NEEDS_CONVENTIONS = ("intake", "builder", "handoff")
# What FR-CTX1 compressed, measured with tests/test_mcp.py's seed project (a built project: intake, spec, a
# compiled contract, T-001 merged) at commit 26f45c8 and after; tokens as characters / 4. "shared" is the share
# of a call (the lane's system prompt with it) that is the same in every project, which a prompt cache reuses.
FIXES: list[dict[str, Any]] = [
    {"what": "Ask Rihma's prompt", "where": "kernel/assistant.py _catalogue, kernel/assistant_rules.py hint",
     "how": "the catalogue names each of the 124 controls by id and label; where a control is and what it does is "
            "given for the map entries that match the question",
     "before": {"chars": 43_008, "catalogue_chars": 39_522}, "after": {"chars": 18_652, "catalogue_chars": 14_647}},
    {"what": "MCP tools' answers", "where": "mcp/server.py COMPACT, mcp/bridge_tools.py handoff",
     "how": "JSON without indentation in every answer and resource; the hand-off tool gives its brief once, in "
            "Markdown, with the items by reference", "before": {"chars": 25_798, "handoff_chars": 9_463},
     "after": {"chars": 15_569, "handoff_chars": 4_338}},
    {"what": "The spec's prompt", "where": "kernel/spec.py spec_prompt",
     "how": "the stack, the road's facts, integrations, the instructions and the answer's shape first; the brief "
            "last", "before": {"shared": 0.117}, "after": {"shared": 0.753}},
    {"what": "The holdout author's prompt", "where": "kernel/compile.py holdout_prompt",
     "how": "the instructions and the answer's shape first; the product, its interface and the criteria last",
     "before": {"shared": 0.204}, "after": {"shared": 0.621}},
    {"what": "The verifier's prompt", "where": "kernel/gate.py verifier_prompt",
     "how": "the review's instructions first; the task and its base revision last",
     "before": {"shared": 0.8}, "after": {"shared": 0.921}},
    {"what": "Goal help's prompt", "where": "kernel/copilot.py prompt, fitted_steps",
     "how": "the catalogue before the project's facts, the goal last; the rule-based steps fitted by whole steps "
            "where a 6,000-character slice could cut its JSON", "before": {"shared": 0.246},
     "after": {"shared": 0.615}},
]
PROPOSALS = {
    "over_budget": "summarise the largest part, or give a reference (an id, a file) in place of its full text",
    "said_twice": "say it once: keep it in the part that needs it and refer to it from the other",
    "stable_prefix": "move the parts that change less to the front, so a prompt cache reuses them",
    "oversized_output": "page the answer, or return ids and counts with the detail on request",
    "conventions_unneeded": "leave the project's conventions out of this role's context",
}
# The commands whose JSON an agent may read, measured on each project (read only).
COMMANDS = (("status", ("status", "{pid}")), ("handoff --json", ("handoff", "{pid}", "--json")),
            ("goal --json", ("goal", "{pid}", "Deploy it to a test environment", "--json")),
            ("channel --json", ("channel", "{pid}", "--json")), ("context map", ("context", "map", "{pid}")))


def _lines(text: str) -> list[str]:
    return [" ".join(x.split()) for x in re.split(r"\n", text) if len(x.strip()) >= MIN_LINE]


def said_twice(p: dict[str, Any]) -> list[dict[str, Any]]:
    """Lines of MIN_LINE characters or more that a pack carries twice, with the parts they are in."""
    seen: dict[str, list[str]] = {}
    for x in p["parts"]:
        for line in _lines(x["content"]):
            seen.setdefault(line, []).append(x["name"])
    return [{"line": line[:120], "parts": names, "chars": len(line) * (len(names) - 1)}
            for line, names in seen.items() if len(names) > 1]


def _finding(kind: str, pid: str, where: str, detail: str, **more: Any) -> dict[str, Any]:
    return {"kind": kind, "project": pid, "where": where, "detail": detail, "proposal": PROPOSALS[kind], **more}


def pack_findings(p: dict[str, Any]) -> list[dict[str, Any]]:
    """What the audit finds in one pack."""
    pid, out = p["project"], []
    if p["over_budget"]:
        big = max(p["parts"], key=lambda x: x["chars"])
        out.append(_finding("over_budget", pid, p["id"], f"{p['with_system']['tokens']:,} of {p['budget']['tokens']:,} "
                                                         f"tokens; the largest part is {big['name']} ({big['chars']:,} "
                                                         "characters)", tokens=p["with_system"]["tokens"]))
    twice = said_twice(p)
    if twice:
        out.append(_finding("said_twice", pid, p["id"], f"{len(twice)} line(s) said twice, "
                                                        f"{sum(t['chars'] for t in twice):,} characters",
                            lines=twice[:5]))
    for v in p["violations"]:
        out.append(_finding("stable_prefix", pid, p["id"], f"{v['part']} ({v['stability']}) comes before "
                                                           f"{v['chars_behind']:,} characters that change less: "
                                                           f"{', '.join(v['before'])}"))
    if p["id"] not in NEEDS_CONVENTIONS:
        sent = [x["name"] for x in p["parts"] if x["kind"] == "conventions" and x["chars"]]
        if sent:
            out.append(_finding("conventions_unneeded", pid, p["id"], f"{', '.join(sent)} sent to "
                                                                      f"{p['label']}"))
    for o in p.get("outputs") or []:
        if o["over_budget"]:
            out.append(_finding("oversized_output", pid, o["tool"], f"{o['tokens']:,} of {cp.OUTPUT_BUDGET:,} tokens"))
    return out


def command_outputs(factory: Any, project: Any) -> list[dict[str, Any]]:
    """Each read command's JSON as an agent running it would read it, measured; one that fails is not measured."""
    from kernel.cli import main

    out = []
    for name, argv in COMMANDS:
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                code = main(["--home", str(factory.home), *[a.format(pid=project.pid) for a in argv]])
        except (SystemExit, Exception) as exc:  # noqa: BLE001 - not measured, never guessed
            out.append({"command": name, "measured": False, "why": type(exc).__name__})
            continue
        text = buf.getvalue()
        out.append({"command": name, "measured": code == 0, "chars": len(text), "tokens": cp.tokens(len(text)),
                    "over_budget": cp.tokens(len(text)) > cp.OUTPUT_BUDGET,
                    "compact_chars": _compact_size(text)})
    return out


def _compact_size(text: str) -> int | None:
    try:
        return len(json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":")))
    except ValueError:
        return None


def project_audit(factory: Any, project: Any, *, persona: str | None = None, commands: bool = True) -> dict[str, Any]:
    """One project's packs, outputs and findings."""
    built = packs.every(factory, project, persona=persona)
    ready = [p for p in built if "unavailable" not in p]
    cmds = command_outputs(factory, project) if commands else []
    findings = [f for p in ready for f in pack_findings(p)] + _command_findings(project.pid, cmds)
    outputs = [o for p in ready for o in p.get("outputs") or []]
    return {"project": project.pid, "title": project.meta.get("title"),
            "packs": [cp.summary(p) for p in ready] + [p for p in built if "unavailable" in p],
            "outputs": [{k: v for k, v in o.items() if k != "content"} for o in outputs],
            "commands": cmds, "findings": findings, "_packs": ready}


def _command_findings(pid: str, cmds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    over = [c for c in cmds if c.get("over_budget")]
    return [_finding("oversized_output", pid, f"rihmasto {c['command']}",
                     f"{c['tokens']:,} of {cp.OUTPUT_BUDGET:,} tokens") for c in over]


def health(audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per pack (role or surface): average and largest size in tokens with the system prompt, how many are over
    budget, and the average cache-friendly prefix ratios (within a project, and shared by every project)."""
    rows = []
    for pack_id in packs.PACKS:
        got = [p for a in audits for p in a["_packs"] if p["id"] == pack_id]
        if not got:
            rows.append({"pack": pack_id, "label": packs.LABELS[pack_id], "measured": 0})
            continue
        sizes = [p["with_system"]["tokens"] for p in got]
        rows.append({"pack": pack_id, "label": packs.LABELS[pack_id], "role": got[0]["role"], "measured": len(got),
                     "average_tokens": round(sum(sizes) / len(sizes)), "max_tokens": max(sizes),
                     "budget": got[0]["budget"]["tokens"], "over_budget": sum(p["over_budget"] for p in got),
                     "prefix_ratio": round(sum(p["prefix"]["ratio"] for p in got) / len(got), 3),
                     "shared_ratio": round(sum(p["shared"]["ratio"] for p in got) / len(got), 3)})
    return rows


def audit(factory: Any, pid: str | None = None, *, persona: str | None = None,
          commands: bool = True) -> dict[str, Any]:
    """The audit of one project, or of every product in the factory, with the health per role and what FR-CTX1
    compressed. Writes nothing."""
    projects = [factory.project(pid)] if pid else [p for p in factory.projects() if not p.pid.startswith("_")]
    audits = [project_audit(factory, p, persona=persona, commands=commands) for p in projects]
    findings = [f for a in audits for f in a["findings"]]
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
    return {"schema": "rihmasto.context-audit/1", "scope": pid or "factory", "tokens": "estimated: characters / 4",
            "health": health(audits), "findings": findings, "counts": counts, "fixes": FIXES,
            "projects": [{k: v for k, v in a.items() if k != "_packs"} for a in audits]}
