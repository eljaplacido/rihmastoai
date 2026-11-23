"""Ingest one Gnomon run into the factory's ledger (FR-C2-AC-1, AC-2, AC-5, AC-6).

The factory does not take Gnomon's word for its own records. The run's audit trail is
re-verified here: each record's hash is SHA-256 over the record without its `hash`, as
sorted-key compact JSON, and each `prev` is the previous record's hash (the first is null). A
broken chain makes the run "tampered", and its verdict "not measured", whatever the record
claims.

"Sorted-key compact JSON" is Gnomon's own canonicaliser (`canonical()` in
packages/gnomon-core/src/audit.ts), which writes with JavaScript's `JSON.stringify`. Python's
`json.dumps` agrees with it on everything except three things, and this module matches
JavaScript on all three:
- **numbers:** JavaScript writes 0.00005 and 1.5e-7, Python 5e-05 and 1.5e-07;
- **key order:** JavaScript sorts by UTF-16 code unit, Python by code point (they differ only
  for keys mixing characters above U+FFFF with U+E000 to U+FFFF);
- **lone surrogates:** JavaScript escapes them as \\udxxx; Python cannot encode them at all.

Every record is kept and its kind counted, whatever the kind. A kind this adapter does not
know (a newer Gnomon's) is listed under `unknown_kinds`, never dropped. CONTRACTS §55 says a
reader treats such a record as content until it has the newer schema, so only its kind name
and count leave this module, never its fields.

One ledger event per run carries:
- the surface hash, the harness build, the role and the model;
- the audit chain head, the record count and the kinds seen;
- the verdict with its native values;
- the context window, where it came from, and the trims (with each trim's basis);
- the tokens and the priced cost. An escalated run whose record splits its usage before and
  after the escalation (`volatile.escalation_usage`) is priced per leg, so a local leg is never
  charged at the cloud model's price.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path

from adapters.gnomon_outcome import outcome

# Every audit kind Gnomon 0.6.6 writes: `audit_kind` in conformance/enumerations_golden.json
# (36 entries) and AUDIT_KINDS in packages/gnomon-core/src/audit.ts. 0.6.6 added skill_use,
# think_cap, inbox_item and proposal_decision.
AUDIT_KINDS = (
    "session_start", "session_resume", "turn", "chain_stage", "tool_call", "approval", "verify",
    "bootstrap", "context_mask", "degradation", "check", "trust", "guard", "skill_accept",
    "skill_reject", "skill_trial", "skill_use", "record_tamper", "record_tamper_resolved",
    "record_notice", "mcp_tools", "stall_signal", "completion_gate", "todo_gate", "job",
    "deliverable_first", "first_token_stall", "checkpoint", "think_cap", "finish_gate",
    "model_call", "escalation", "eval_run", "inbox_item", "proposal_decision", "session_end",
)

# Why a trim divided its budget (CONTRACTS §29, `trim.basis`, 0.6.6): the provider's own prompt
# counts for this endpoint and model, or the pre-call check's 1.5x safety factor.
TRIM_BASES = ("measured", "safety")
TRIM_REASONS = ("leg", "overflow", "pre_call")

_SURROGATE = re.compile("[\ud800-\udfff]")


def _js_string(text: str) -> str:
    """A string as JSON.stringify writes it. Python's escapes are the same (", \\, the control
    characters as \\b \\f \\n \\r \\t or \\u00xx), except that JavaScript escapes a lone surrogate."""
    out = json.dumps(text, ensure_ascii=False)
    return _SURROGATE.sub(lambda m: f"\\u{ord(m.group()):04x}", out)


def _js_number(value: float) -> str:
    """A float as JavaScript's Number::toString writes it (ECMA-262), from Python's shortest
    round-trip digits, which are the same digits JavaScript chooses."""
    if math.isnan(value) or math.isinf(value):
        return "null"  # JSON.stringify writes NaN and Infinity as null
    if value == 0:
        return "0"
    if value < 0:
        return "-" + _js_number(-value)
    _, digits, exponent = Decimal(repr(value)).as_tuple()
    if not isinstance(exponent, int):  # "n", "N" or "F": NaN and Infinity, handled above
        return "null"
    s = "".join(map(str, digits))
    stripped = s.rstrip("0")
    exponent += len(s) - len(stripped)
    s = stripped
    k, n = len(s), exponent + len(s)  # value = 0.s * 10**n, s has k digits
    if k <= n <= 21:
        return s + "0" * (n - k)
    if 0 < n <= 21:
        return s[:n] + "." + s[n:]
    if -6 < n <= 0:
        return "0." + "0" * (-n) + s
    e = n - 1
    return (s[0] + ("." + s[1:] if k > 1 else "")) + ("e+" if e >= 0 else "e-") + str(abs(e))


def canonical_json(value) -> str:
    """Gnomon's canonical JSON (audit.ts `canonical`): keys sorted, no whitespace, written as
    JavaScript writes them."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _js_number(value)
    if isinstance(value, str):
        return _js_string(value)
    if isinstance(value, list):
        return "[" + ",".join(canonical_json(v) for v in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value, key=lambda k: k.encode("utf-16-be", "surrogatepass"))
        return "{" + ",".join(_js_string(k) + ":" + canonical_json(value[k]) for k in keys) + "}"
    raise TypeError(f"not a JSON value: {type(value).__name__}")


def _hash(record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _kinds(records) -> tuple[dict, list]:
    counts = Counter(str(r.get("kind")) for r in records)
    return dict(sorted(counts.items())), sorted(k for k in counts if k not in AUDIT_KINDS)


def verify_audit(path: str | Path) -> dict:
    """Re-verify a Gnomon audit JSONL. Never raises on bad content: it reports where it broke.

    Every record that parses is counted by kind, before and after a break, so nothing a trail
    holds is dropped from the report."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return {"intact": False, "broken_seq": None, "head": None, "records": 0, "error": str(exc),
                "kinds": {}, "unknown_kinds": []}
    lines = [ln for ln in lines if ln.strip()]
    parsed = []
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            parsed.append(rec)
    kinds, unknown = _kinds(parsed)
    found = {"kinds": kinds, "unknown_kinds": unknown}
    if not lines:
        return {"intact": False, "broken_seq": 0, "head": None, "records": 0, "error": "empty trail", **found}
    prev, head = None, None
    for i, line in enumerate(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            return {"intact": False, "broken_seq": i, "head": head, "records": i, "error": "not JSON", **found}
        if not isinstance(rec, dict):
            return {"intact": False, "broken_seq": i, "head": head, "records": i, "error": "not a record", **found}
        if "hash" not in rec:
            return {"intact": False, "broken_seq": i, "head": head, "records": i,
                    "error": "no hash: the trail is not chained ([audit] chain = false)", **found}
        try:
            ok = rec.get("seq") == i and rec.get("prev") == prev and rec.get("hash") == _hash(rec)
        except TypeError:
            ok = False
        if not ok:
            return {"intact": False, "broken_seq": i, "head": head, "records": i, **found}
        prev = head = rec["hash"]
    return {"intact": True, "broken_seq": None, "head": head, "records": len(lines), **found}


def find_trail(audit_dir: str | Path, record: dict) -> Path | None:
    """The run's audit JSONL: `<session>.jsonl` beside its record."""
    session = record.get("session")
    if session:
        p = Path(audit_dir) / f"{session}.jsonl"
        return p if p.exists() else None
    return None


def tokens(record: dict) -> dict:
    v = record.get("volatile") or {}
    calls = (v.get("model_calls") or {}).get("calls") or []
    return {"in": v.get("tokens_in"), "out": v.get("tokens_out"),
            "cached": sum(c.get("cached_tokens") or 0 for c in calls) if calls else None,
            "calls": v.get("requests") if v.get("requests") is not None else len(calls) or None}


def context(record: dict) -> dict:
    """The run's context window and what was trimmed to fit it (CONTRACTS §24 and §29).

    - `window` and `source`: the window and where it came from (`declared`, `listing:<shape>`,
      `catalog`, `default`). Since 0.6.6 `[defaults] max_context_tokens` is only the fallback.
    - `trims`: trims by reason, `pre_call` included (0.6.6), and the messages they dropped.
    - `basis`: per trim in the recorded calls, what its ratio rested on: `measured` (the
      provider's own counts), `safety` (the 1.5x factor before any usage was seen), or
      `unstated` (a trim against the fallback window, or a build before 0.6.6).
    - `ratio`: the measured real/estimate ratio, when the provider reported usage.
    Absent values are None, never zero."""
    sent = (record.get("counters") or {}).get("model_calls") or {}
    received = (record.get("volatile") or {}).get("model_calls") or {}
    wire = record.get("wire") or {}
    trims = sent.get("trims") if isinstance(sent.get("trims"), dict) else None
    basis: Counter[str] = Counter()
    for call in sent.get("calls") or []:
        trim = call.get("trim") if isinstance(call, dict) else None
        if isinstance(trim, dict):
            stated = trim.get("basis")
            basis[stated if stated in TRIM_BASES else "unstated"] += 1
    return {
        "window": sent.get("window") if sent.get("window") is not None else wire.get("max_context_tokens"),
        "source": wire.get("max_context_tokens_source"),
        "trims": ({**{r: trims.get(r, 0) for r in TRIM_REASONS}, "dropped": trims.get("dropped", 0)}
                  if trims is not None else None),
        "basis": dict(sorted(basis.items())),
        "ratio": received.get("ratio"),
    }


def _leg_tokens(record: dict) -> tuple[dict, dict] | None:
    """An escalated run's tokens before and after its escalation, from Gnomon's
    `volatile.escalation_usage`. The cached tokens are split by the calls before it (its first
    `requests` calls) only when those calls add up to the leg's input. None when the record does not
    split its legs."""
    v = _obj(record.get("volatile"))
    usage = _obj(v.get("escalation_usage"))
    before, after = usage.get("before"), usage.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return None
    cached = _cached_split(_obj(v.get("model_calls")).get("calls"), before)
    return ({"in": before.get("input"), "out": before.get("output"), "cached": cached[0]},
            {"in": after.get("input"), "out": after.get("output"), "cached": cached[1]})


def _obj(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _cached_split(calls: object, before: dict) -> tuple[int | None, int | None]:
    """The cached tokens before the escalation (its first ``requests`` calls) and after it, or
    (None, None) when the calls do not add up to the first leg's input."""
    n = before.get("requests")
    if not isinstance(calls, list) or not all(isinstance(c, dict) for c in calls) or not isinstance(n, int):
        return None, None
    if sum(c.get("prompt_tokens") or 0 for c in calls[:n]) != before.get("input"):
        return None, None
    return (sum(c.get("cached_tokens") or 0 for c in calls[:n]),
            sum(c.get("cached_tokens") or 0 for c in calls[n:]))


def _joined(legs: list) -> dict:
    """One run's cost from its legs' costs, local and cloud kept apart. Any leg not measured makes
    the run's cost not measured, never zero."""
    missing = [leg for leg in legs if not leg.get("measured")]
    if missing:
        return {"measured": False, "kind": None, "amount": None, "legs": legs,
                "why": "; ".join(f"{leg['model']}: {leg.get('why')}" for leg in missing)}
    local = sum(leg.get("local_tokens", 0) for leg in legs if leg["kind"] == "local")
    cloud = [leg for leg in legs if leg["kind"] != "local"]
    if not cloud:
        return {"measured": True, "kind": "local", "amount": 0.0, "local_tokens": local, "legs": legs}
    out = {"measured": True, "kind": "cloud" if len(cloud) == len(legs) else "mixed",
           "amount": round(sum(leg["amount"] for leg in cloud), 6), "currency": cloud[0].get("currency"),
           "legs": legs}
    if local:
        out["local_tokens"] = local
    return out


def run_cost(record: dict, toks: dict, *, prices: dict | None = None) -> dict:
    """The run's priced cost (FR-L4). An escalated run whose record splits its legs is priced per
    leg: the tokens before the escalation at the model it started on, the rest at the model it ended
    on. Otherwise the run is priced at its model."""
    from kernel.pricing import price_run

    esc = _obj(record.get("escalation"))
    first = _obj(esc.get("from")).get("model")
    final = esc.get("final_model") or _obj(esc.get("to")).get("model") or record.get("model")
    legs = _leg_tokens(record) if first and final and first != final else None
    if legs is None:
        return price_run(record.get("model"), toks, prices=prices)
    return _joined([dict(price_run(model, t, prices=prices), model=model)
                    for model, t in zip((first, final), legs, strict=True)])


def ingest(project, record: dict, audit_path: str | Path | None, *, task: str | None = None,
           round_no: int | None = None, prices=None) -> dict:
    """Append one `gnomon_run` event to the project's ledger and return its payload."""
    out = outcome(record)
    chain = verify_audit(audit_path) if audit_path else {"intact": False, "broken_seq": None, "head": None,
                                                          "records": 0, "error": "no audit trail found",
                                                          "kinds": {}, "unknown_kinds": []}
    verdict = out["verdict"]
    tampered = out["tampered"] or not chain["intact"]
    if tampered:
        verdict = "not measured"
    toks = tokens(record)
    payload = {
        "run": record.get("session"), "task": task, "round": round_no,
        "surface_hash": record.get("surface_hash") or (record.get("trust") or {}).get("surface_hash"),
        "harness": record.get("harness"), "role": record.get("role"), "model": record.get("model"),
        "endpoint": record.get("endpoint"),
        "chain": {"intact": chain["intact"], "head": chain["head"], "records": chain["records"],
                  "broken_seq": chain["broken_seq"], "kinds": chain["kinds"],
                  "unknown_kinds": chain["unknown_kinds"]},
        "verdict": verdict, "apparatus_failure": out["apparatus_failure"], "tampered": tampered,
        "native": out["native"], "tokens": toks, "context": context(record),
        "cost": run_cost(record, toks, prices=prices),
    }
    project.log("gnomon_run", payload)
    return payload
