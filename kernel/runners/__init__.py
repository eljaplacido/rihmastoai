"""Cell runners: which harness runs a factory cell (D-0019, FR-HRN1). docs/guides/harnesses.md is the guide.

A runner takes a task envelope (the task, its write scope, its protected paths, the project's own conventions
and the criteria whose tests must fail first) and a working copy, and leaves a diff and a run record: the tool
calls when the harness shows them, its version, timings and exit.

- ``gnomon`` is the default and the reference. Gnomon enforces the write scope, the protected paths and the shell
  rules during the run, and keeps a hash-chained record of every tool call: **in-run policy enforced by Gnomon**.
- ``claude-code``, ``codex``, ``opencode`` and ``command`` (any command line a team names) are opt-in, chosen by IT
  on a card with the runner's version pinned. Gnomon's in-run enforcement does not apply to them: every rule is
  **checked after the run** (kernel/runners/glue.py), and a change that breaks one never merges.

The evidence says which applied: every round's record carries the runner, its version and its assurance, and
the cockpit and the evidence pack never show a round checked after the run as Gnomon-level assurance.
"""

from __future__ import annotations

from typing import Any

IN_RUN = "in_run"
AFTER_RUN = "after_run"
ASSURANCE = {
    IN_RUN: "in-run policy enforced by Gnomon",
    AFTER_RUN: "in-run policy not enforced by this harness; checked after the run",
}
ROLES = ("builder", "verifier")
DEFAULT = "gnomon"

# What Rihmasto knows of each runner before it looks for it on this machine.
RUNNERS: dict[str, dict[str, Any]] = {
    "gnomon": {"label": "Gnomon", "binary": "gnomon", "assurance": IN_RUN, "family": None,
               "about": "the factory's own harness: scope, protected paths and shell rules enforced during the run, "
                        "a hash-chained record of every tool call"},
    "claude-code": {"label": "Claude Code", "binary": "claude", "assurance": AFTER_RUN, "family": "claude",
                    "about": "claude -p headless, stream-json output, tools limited to read, edit and bash in the "
                             "working copy, a permission mode that never prompts"},
    "codex": {"label": "Codex", "binary": "codex", "assurance": AFTER_RUN, "family": "gpt",
              "about": "codex exec headless with JSON events, its own workspace-write sandbox"},
    "opencode": {"label": "OpenCode", "binary": "opencode", "assurance": AFTER_RUN, "family": None,
                 "about": "opencode run headless with JSON events; the model names the family"},
    "command": {"label": "A command you name", "binary": None, "assurance": AFTER_RUN, "family": None,
                "about": "any command line a team names, with {prompt_file} and {workdir} filled in"},
}


class RunnerRefused(ValueError):
    """A runner choice or run Rihmasto does not take, with the reason."""


def assurance_of(name: str | None) -> dict[str, str]:
    """The assurance a round run by ``name`` has: its key and the words the evidence uses for it."""
    key = IN_RUN if (name or DEFAULT) == DEFAULT else AFTER_RUN
    return {"assurance": key, "assurance_label": ASSURANCE[key]}


def label_of(name: str) -> str:
    return str(RUNNERS.get(name, {}).get("label") or name)


def evidence_rows(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each builder round (the payloads of a ledger's ``cell_ran`` records), with the runner that ran it, its version
    and its assurance. A round recorded before runners were named was Gnomon's, the only runner then."""
    rows = []
    for p in cells:
        given = p.get("runner")
        line: dict[str, Any] = given if isinstance(given, dict) else {"name": DEFAULT, "label": label_of(DEFAULT)}
        key = IN_RUN if line.get("name", DEFAULT) == DEFAULT else AFTER_RUN   # never taken from the record's own words
        rows.append({"task": p.get("task"), "round": p.get("round"), "runner": line.get("name", DEFAULT),
                     "version": line.get("version"), "assurance": key, "assurance_label": ASSURANCE[key],
                     "sandbox": line.get("sandbox"), "head": p.get("head")})
    return rows


def evidence_line(rows: list[dict[str, Any]]) -> str:
    """The evidence pack's line on who ran the rounds and what assurance applied."""
    after = [r for r in rows if r["assurance"] == AFTER_RUN]
    if not after:
        return f"- Cell runners: {len(rows)} round(s), every one {ASSURANCE[IN_RUN]}."
    names = sorted({f"{label_of(r['runner'])} {r.get('version') or '(version unknown)'}" for r in after})
    return (f"- Cell runners: {len(rows) - len(after)} round(s) {ASSURANCE[IN_RUN]}; {len(after)} round(s) by "
            f"{', '.join(names)}: {ASSURANCE[AFTER_RUN]} (`cell-runners.json`).")
