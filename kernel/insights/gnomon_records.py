"""Model and tool use as the records hold it: Gnomon's runs in the ledgers, and Gnomon's own trails in the lanes.

- **Runs** are the ledger's ``gnomon_run`` events (adapters/gnomon_ingest.py writes one per builder cell, with
  the role, model, endpoint, tokens, priced cost, context window and trims, and the audit trail's kinds
  counted). A record another cell runner writes (``runner_run``, D-0019) or the run of another role (analyst,
  holdout author, verifier, assistant: ``model_run``, kernel/model_usage.py) is read the same way; ``runner`` is
  the harness that ran it, Gnomon for a ``gnomon_run``.
- **Trails** are Gnomon's own hash-chained audit trails, ``<lane>/.gnomon-audit/<session>.jsonl`` (kernel/lanes.py
  compiles ``[audit] dir = ".gnomon-audit"`` into every lane). A run's trail is found by its session id, which
  names it alone, so the tool calls by tool and the largest prompt are attributed to the right run. A lane
  keeps its trails across leases but not forever: a run whose trail is gone counts its tool calls (from the
  ledger's kinds) but not which tools.
- **Skills** are Gnomon's learned notes: accepted ones under ``.gnomon/skills/`` on the product's main, and the
  audit kinds ``skill_use``, ``skill_trial``, ``skill_accept`` and ``skill_reject`` counted per run.

Nothing here reads a credential, a prompt or an answer: the records are metadata (``record = "metadata"``).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from kernel.insights.base import Scope, obj, when

RUN_KINDS = ("gnomon_run", "runner_run", "model_run")
COMPACTION_KINDS = ("context_mask", "checkpoint")
SKILL_KINDS = ("skill_use", "skill_trial", "skill_accept", "skill_reject")
PEAK_KEYS = ("prompt_tokens", "input_tokens", "tokens_in", "input")
MAX_TRAIL_BYTES = 32 * 1024 * 1024


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _hosting(cost: dict[str, Any], model: str | None, prices: dict[str, Any]) -> str | None:
    kind = cost.get("kind")
    if kind in ("local", "cloud", "mixed"):
        return {"cloud": "hosted"}.get(kind, kind)
    entry = obj(prices.get("models")).get(model or "")
    if isinstance(entry, dict):
        return "local" if entry.get("local") else "hosted"
    return None


def _trims(ctx: dict[str, Any]) -> int | None:
    trims = ctx.get("trims")
    if not isinstance(trims, dict):
        return None
    return sum(v for k, v in trims.items() if k != "dropped" and isinstance(v, int))


def _cost(cost: dict[str, Any]) -> dict[str, Any]:
    measured = bool(cost.get("measured"))
    return {"cost": cost.get("amount") if measured else None, "currency": cost.get("currency"),
            "cost_why": None if measured else (cost.get("why") or "no price recorded")}


def _harnessed(payload: dict[str, Any]) -> dict[str, Any]:
    """A harness's ``model_run`` (kernel/harness_model.py: ``harness``, tokens as input/output, ``cost_usd``) in the
    shape the other runs have: its runner is the harness, its cost the harness's own report."""
    toks, usd = obj(payload.get("tokens")), payload.get("cost_usd")
    priced = isinstance(usd, (int, float)) and not isinstance(usd, bool)
    return dict(payload, runner=payload.get("harness"),
                tokens={"in": toks.get("input"), "out": toks.get("output"), "cached": toks.get("cache_read")},
                cost={"measured": True, "amount": float(usd), "currency": "USD", "kind": "cloud"} if priced else
                {"measured": False, "why": f"{payload.get('label') or payload.get('harness')} reported no cost"},
                verdict=payload.get("verdict") or ("passed" if payload.get("ok") else "failed"))


def run_of(project: Any, at: Any, payload: dict[str, Any], kind: str, prices: dict[str, Any]) -> dict[str, Any]:
    """One run as the insights read it. Absent values stay None, never zero."""
    if kind == "model_run" and isinstance(payload.get("harness"), str) and "cost_usd" in payload:
        payload = _harnessed(payload)          # a coding agent's run (kernel/harness_model.py record_run)
    toks, cost, ctx = obj(payload.get("tokens")), obj(payload.get("cost")), obj(payload.get("context"))
    kinds = obj(payload.get("chain")).get("kinds")
    model = payload.get("model") or None
    return {"project": project.pid, "at": at, "run": payload.get("run"), "task": payload.get("task"),
            "round": payload.get("round"), "role": payload.get("role") or None, "model": model,
            "endpoint": payload.get("endpoint") or None,
            "runner": payload.get("runner") or ("gnomon" if kind == "gnomon_run" else None),
            "in": _int(toks.get("in")), "out": _int(toks.get("out")), "cached": _int(toks.get("cached")),
            "calls": _int(toks.get("calls")), **_cost(cost), "hosting": _hosting(cost, model, prices),
            "window": _int(ctx.get("window")), "window_source": ctx.get("source"), "trims": _trims(ctx),
            "kinds": kinds if isinstance(kinds, dict) else None, "verdict": payload.get("verdict"), "kind": kind}


def runs(scope: Scope, *, previous: bool = False) -> list[dict]:
    from kernel.pricing import load_prices

    prices = load_prices()
    return [run_of(p, t, pl, rec["event"]["kind"], prices)
            for p, t, pl, rec in scope.events(*RUN_KINDS, previous=previous)]


def kind_count(run: dict, *kinds: str) -> int | None:
    """How many audit records of these kinds the run's trail held; None when its kinds were not recorded."""
    if run["kinds"] is None:
        return None
    return sum(int(run["kinds"].get(k) or 0) for k in kinds)


def lanes_root() -> Path:
    from kernel.lanes import lanes_root as root

    return root()


def find_trail(run_id: Any, root: Path | None = None) -> Path | None:
    """A run's own trail in any lane: ``<lane>/.gnomon-audit/<session>.jsonl`` (the assistant's lanes sit one
    folder deeper). The session id is checked to be a plain file name first."""
    plain = isinstance(run_id, str) and bool(run_id) and not run_id.startswith(".")
    if not plain or any(c in str(run_id) for c in "/\\:*?\"<>|"):
        return None
    base = root or lanes_root()
    if not base.is_dir():
        return None
    for pattern in (f"*/.gnomon-audit/{run_id}.jsonl", f"*/*/.gnomon-audit/{run_id}.jsonl"):
        for path in base.glob(pattern):
            if path.is_file():
                return path
    return None


def read_trail(path: Path) -> dict:
    """Tool calls by tool, model calls and the largest prompt a trail records. A line that does not parse is
    skipped (the ledger already says whether the chain was intact)."""
    tools: dict[str, int] = {}
    peak: int | None = None
    model_calls = 0
    try:
        if path.stat().st_size > MAX_TRAIL_BYTES:
            return {"tools": None, "peak": None, "model_calls": None, "why": "the trail is larger than 32 MB"}
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {"tools": None, "peak": None, "model_calls": None, "why": str(exc)}
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        kind = rec.get("kind")
        if kind == "tool_call":
            name = str(rec.get("tool") or "unnamed")[:60]
            tools[name] = tools.get(name, 0) + 1
        elif kind == "model_call":
            model_calls += 1
            n = _prompt(rec)
            peak = peak if n is None else max(peak or 0, n)
    return {"tools": tools, "peak": peak, "model_calls": model_calls, "why": None}


def _prompt(rec: dict[str, Any]) -> int | None:
    """A model call's prompt size, wherever the record keeps it (its own field or its usage)."""
    where = obj(rec.get("usage")) or rec
    return next((n for key in PEAK_KEYS if (n := _int(where.get(key))) is not None), None)


def trails(run_list: list[dict], root: Path | None = None) -> dict:
    """Each run's trail read, by run id, and the runs whose trail is gone."""
    found, missing = {}, 0
    for r in run_list:
        path = find_trail(r["run"], root)
        if path is None:
            missing += 1
            continue
        found[r["run"]] = read_trail(path)
    return {"by_run": found, "missing": missing}


def skills_on_main(project: Any) -> list[str] | None:
    """The learned notes accepted on the product's main (``.gnomon/skills/*.md``); None without a repository."""
    repo = project.path("repo.git")
    if not repo.exists():
        return None
    try:
        out = subprocess.run(["git", "ls-tree", "--name-only", "main", ".gnomon/skills/"], cwd=repo,
                             capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return sorted(Path(n).stem for n in out.stdout.split() if n.endswith(".md"))


def first_at(scope: Scope) -> Any:
    """The first run in the scope at all, for "since when" lines."""
    times = [t for _, t, _, _ in scope.every(*RUN_KINDS) if t]
    return min(times) if times else None


__all__ = ["COMPACTION_KINDS", "RUN_KINDS", "SKILL_KINDS", "find_trail", "first_at", "kind_count", "read_trail",
           "run_of", "runs", "skills_on_main", "trails", "when"]
