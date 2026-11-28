"""The checks of a Gnomon posture, each one of Gnomon's documented settings, and a suggestion when one fails (FR-GNP1).

A check holds, holds in part, or does not hold; its points count toward its dimension's score. The dimensions and
their maximums (100 in all):

=========================  ====  ============================================================================
verification               20    `[verify] command` (a check after a turn), `after` that sees shell changes too,
                                 `protects` (the checked files cannot be changed to pass), `exit_on_fail`
containment                20    `[sandbox] exec` "os" or "docker" (not "off"), `network = false`, `reads =
                                 "scoped"`
governance                 20    `[governance]` declared, at `prevent` or `enforce` (`observe` and `advise` hold
                                 in part), `[approval]` declared
audit                      15    `[audit] enabled`, `chain = true` (each record hashed to the one before),
                                 `[audit.anchor]` (sealed heads copied to an outside witness)
efficiency                 15    `[defaults] edit_format = "hashline"`, `[context]` declared, `[resilience]`
                                 declared (timeouts and retries)
freshness                  10    `.gnomon/skills/`, and `.gnomon/trials/` or `.gnomon/loops/`; no legacy key
                                 Gnomon no longer reads (`[sandbox] level`)
=========================  ====  ============================================================================

A suggestion names the file (`.gnomon/policy.toml` or `.gnomon/config.toml`), the exact setting and why; its id
(``GP-`` and the check's key) is stable, so a suggestion filed once is known when it shows again.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

DIMENSIONS = (("verification", "Verification & change", 20), ("containment", "Containment & sandbox", 20),
              ("governance", "Governance & guards", 20), ("audit", "Audit & provenance", 15),
              ("efficiency", "Loop, edit & context", 15), ("freshness", "Freshness", 10))
POLICY, CONFIG = ".gnomon/policy.toml", ".gnomon/config.toml"
Read = dict[str, Any]
Test = Callable[[dict[str, Any], dict[str, Any], list[str]], float]


def _t(table: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        table = table.get(k) if isinstance(table, dict) else None      # type: ignore[assignment]
    return table


def _level(p: dict[str, Any]) -> float:
    gov = p.get("governance")
    if not isinstance(gov, dict):
        return 0.0
    level = str(gov.get("level") or "prevent")                        # Gnomon's default level is prevent
    return 1.0 if level in ("prevent", "enforce") else 0.5 if level in ("observe", "advise") else 0.0


def _nonempty_dict(v: Any) -> float:
    return 1.0 if isinstance(v, dict) and bool(v) else 0.0


# (key, dimension, points, test, severity, title, why, file, setting)
CHECKS: tuple[tuple[str, str, int, Test, str, str, str, str, str], ...] = (
    ("verify_command", "verification", 8, lambda c, p, f: 1.0 if _t(p, "verify", "command") else 0.0, "high",
     "Declare a [verify] command", "without one Gnomon accepts a change without running any check", POLICY,
     '[verify] command = "<your test command>"'),
    ("verify_after", "verification", 4,
     lambda c, p, f: 1.0 if _t(p, "verify", "after") in ("change", "always") else 0.0, "medium",
     "Run the check after any change", "after = \"write\" (the default) misses files the shell changed", POLICY,
     '[verify] after = "change"'),
    ("verify_protects", "verification", 4, lambda c, p, f: 1.0 if _t(p, "verify", "protects") else 0.0, "medium",
     "Protect the files the check runs", "a turn could change the tests to make them pass", POLICY,
     '[verify] protects = ["@detected"]'),
    ("verify_exit", "verification", 4, lambda c, p, f: 1.0 if _t(p, "verify", "exit_on_fail") is True else 0.0, "low",
     "Make a failed check fail the task", "a failed or unrunnable check otherwise still exits 0", POLICY,
     "[verify] exit_on_fail = true"),
    ("sandbox_exec", "containment", 10,
     lambda c, p, f: 1.0 if _t(p, "sandbox", "exec") in ("os", "docker") else 0.0, "high",
     "Contain shell commands", "with exec off, commands run directly on the host with no boundary", POLICY,
     '[sandbox] exec = "os"'),
    ("sandbox_network", "containment", 5, lambda c, p, f: 1.0 if _t(p, "sandbox", "network") is False else 0.0,
     "medium", "Close the network to commands", "a command can reach any host", POLICY,
     "[sandbox] network = false"),
    ("sandbox_reads", "containment", 5, lambda c, p, f: 1.0 if _t(p, "sandbox", "reads") == "scoped" else 0.0, "low",
     "Scope what commands read", "under exec = \"os\" a command reads the whole machine by default (Linux)", POLICY,
     '[sandbox] reads = "scoped"'),
    ("governance", "governance", 14, lambda c, p, f: _level(p), "high",
     "Govern at prevent", "secret reads, CI tampering and destructive patterns are not blocked below prevent",
     POLICY, '[governance] level = "prevent"'),
    ("approval", "governance", 6, lambda c, p, f: _nonempty_dict(p.get("approval")), "medium",
     "Declare the approval modes", "what a session may do without asking is then Gnomon's default, not yours",
     POLICY, '[approval] modes = ["ask", "auto"] and default = "ask"'),
    ("audit_enabled", "audit", 6, lambda c, p, f: 1.0 if _t(c, "audit", "enabled") is True else 0.0, "high",
     "Turn on the audit trail", "there is no record of what a session did", CONFIG, "[audit] enabled = true"),
    ("audit_chain", "audit", 5, lambda c, p, f: 1.0 if _t(c, "audit", "chain") is True else 0.0, "medium",
     "Chain the audit records by hash", "a record could be changed or removed unseen", CONFIG,
     "[audit] chain = true"),
    ("audit_anchor", "audit", 4, lambda c, p, f: _nonempty_dict(_t(c, "audit", "anchor")), "low",
     "Anchor the audit trail outside this machine", "a full local re-chain cannot be detected without a witness",
     CONFIG, "[audit.anchor] with a witness to copy sealed heads to"),
    ("edit_format", "efficiency", 5, lambda c, p, f: 1.0 if _t(c, "defaults", "edit_format") == "hashline" else 0.0,
     "low", "Try line-hashed edits", "hashline anchors cut stale-edit retries on multi-edit tasks", CONFIG,
     '[defaults] edit_format = "hashline"'),
    ("context", "efficiency", 5, lambda c, p, f: _nonempty_dict(c.get("context")), "low",
     "Declare how context is kept", "how much history each turn re-sends is then left to defaults", CONFIG,
     "[context] with its retention settings"),
    ("resilience", "efficiency", 5, lambda c, p, f: _nonempty_dict(c.get("resilience")), "low",
     "Declare timeouts and retries", "a stalled endpoint is then waited on with defaults", CONFIG,
     "[resilience] with stream timeouts"),
    ("skills", "freshness", 4, lambda c, p, f: 1.0 if "skills" in f else 0.0, "low",
     "Give the project's skills to Gnomon", "sessions start without the project's own know-how",
     ".gnomon/skills/", "a skill folder per repeated task"),
    ("trials", "freshness", 4, lambda c, p, f: 1.0 if "trials" in f or "loops" in f else 0.0, "low",
     "Add a trial or a loop", "without one, gnomon eval and improve have nothing to measure", ".gnomon/trials/",
     "a trial spec (.toml) for a task the project repeats"),
    ("legacy", "freshness", 2, lambda c, p, f: 0.0 if _t(p, "sandbox", "level") is not None else 1.0, "medium",
     "Replace a key Gnomon no longer reads", "[sandbox] level is the old key: Gnomon reads exec", POLICY,
     '[sandbox] exec = "os" in place of level'),
)


def score(got: Read) -> dict[str, Any]:
    """The posture from what ``read`` found: the total, the dimensions (the weakest first) and the suggestions."""
    config = got["files"].get("config.toml") or {}
    policy = got["files"].get("policy.toml") or {}
    folders = list(got.get("folders") or [])
    points: dict[str, float] = {d: 0.0 for d, _, _ in DIMENSIONS}
    checks: dict[str, list[dict[str, Any]]] = {d: [] for d, _, _ in DIMENSIONS}
    suggestions: list[dict[str, Any]] = []
    for key, dim, pts, test, severity, title, why, file, setting in CHECKS:
        held = test(config, policy, folders)
        points[dim] += pts * held
        checks[dim].append({"key": key, "held": held, "points": pts, "setting": setting, "file": file})
        if held < 1.0:          # a check that holds in part is one step less severe than one that does not hold
            said = severity if held == 0.0 else "medium" if severity == "high" else "low"
            suggestions.append({"id": "GP-" + key.replace("_", "-"), "key": key, "dimension": dim, "severity": said,
                                "title": title, "why": why, "file": file, "setting": setting, "partly": held > 0.0})
    dims: list[dict[str, Any]] = [{"key": d, "label": label, "score": round(points[d], 1), "max": most,
             "pct": round(100 * points[d] / most, 1), "checks": checks[d]} for d, label, most in DIMENSIONS]
    dims.sort(key=lambda d: (d["pct"], d["key"]))
    order = {"high": 0, "medium": 1, "low": 2}
    suggestions.sort(key=lambda s: (order[s["severity"]], s["dimension"], s["key"]))
    return {"total": round(sum(points.values())), "max": 100, "dimensions": dims,
            "weakest": [d["label"] for d in dims[:3] if d["pct"] < 100], "suggestions": suggestions}
