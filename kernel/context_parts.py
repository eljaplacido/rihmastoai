"""The parts of a context pack (FR-CTX1, docs/guides/context-and-data.md): how a prompt is measured and shown.

A context pack is what one Rihma agent role or surface is given in one call: the prompt the real code builds, cut
into its parts. Each part says where it came from, its size in characters and estimated tokens, and how stable it
is between calls:

- ``static``: the same in every call of the role, in any project (instructions, the answer's shape);
- ``project``: the same in every call for one project until its records change (the request, the brief);
- ``call``: different in each call (the question, a task's base revision, one perspective of the panel).

An endpoint that caches prompt prefixes reuses everything up to the first part that changes, so the cache-friendly
prefix is the run of parts before the first ``call`` part, with the lane's system prompt before them. A part less
stable than one after it (a ``call`` part before a ``static`` one) is a stable-prefix violation: it defeats that
cache for everything after it.

Tokens are estimated as characters / 4, as `tools/quality.py --prompts` does: an estimate, never a count.
"""

from __future__ import annotations

from typing import Any

CHARS_PER_TOKEN = 4
STABILITY = ("static", "project", "call")
RANK = {s: n for n, s in enumerate(STABILITY)}
# A violation counts only when what comes after the less stable part is worth caching.
VIOLATION_MIN = 200

# The prompt economy (docs/code-quality.md section 7, FR-Z1, FR-CTX1): what each pack may use, in estimated tokens,
# with why. The budget is this, or a quarter of the role's context window when that is smaller, so the answer and
# any tool turns keep the rest.
ECONOMY: dict[str, tuple[int, str]] = {
    "intake": (12_000, "the request, at most MAX_SOURCE_CHARS (40,000 characters, about 10,000 tokens), and 2,000 for "
                       "the instructions, what the request states and what was settled"),
    "spec": (8_000, "the brief and the stack, road and integration facts"),
    "holdout_author": (4_000, "the requirements, the interface and the holdout criteria"),
    "builder": (6_000, "the task, the interface and the rules, and the project's own conventions within "
                       "MAX_ENVELOPE_CHARS (16,000 characters)"),
    "verifier": (2_000, "one task's requirements and criteria, and the review's instructions"),
    "assistant": (8_000, "the snapshot within SNAPSHOT_BUDGET (12,000 characters, about 3,000 tokens), the cockpit's "
                         "catalogue and the question"),
    "goal": (4_000, "the project's facts, what this Rihmasto has and the rule-based plan"),
    "channel": (2_000, "the contract's requirements, what the project waits for, the open items and the question"),
    "handoff": (6_000, "a coding agent's brief: the goal, the criteria, the open items, the plan and the feedback"),
    "mcp": (6_000, "the tool list a coding agent reads at the start of a session, and one tool's answer"),
}
# Each MCP tool's answer and each command's JSON, in estimated tokens: one answer an agent reads in a turn.
OUTPUT_BUDGET = 2_000
# The roles that read a lane's system prompt, and which lane.
LANE_OF = {"analyst": "analyst", "holdout_author": "analyst", "assistant": "analyst", "builder": "product",
           "verifier": "product"}
# What may read each pack's content in the Context view. Every persona sees its parts, sources and sizes; the
# holdout author's content (the criteria a holdout checks, judged out of the builder's sight) only the custodians.
CONTENT_PERSONAS: dict[str, tuple[str, ...]] = {"holdout_author": ("compliance", "it")}


def tokens(chars: int) -> int:
    """Estimated tokens for ``chars`` characters (characters / 4, rounded up)."""
    return (max(chars, 0) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def part(name: str, content: str, source: str, stability: str, *, kind: str = "instructions",
         cut: str | None = None) -> dict[str, Any]:
    """One part of a pack: its name, where it came from, how stable it is, and its size."""
    if stability not in RANK:
        raise ValueError(f"stability is one of {', '.join(STABILITY)}")
    return {"name": name, "source": source, "stability": stability, "kind": kind, "chars": len(content),
            "tokens": tokens(len(content)), "content": content, **({"cut": cut} if cut else {})}


Mark = tuple[str | None, str, str, str, str]   # (marker, name, source, stability, kind)


def split(text: str, marks: list[Mark]) -> list[dict[str, Any]]:
    """``text`` cut at each marker found, in order, into parts that join back to it exactly. The first mark's
    marker is None (the start). A marker not found is skipped: what it would have started stays in the part
    before it."""
    found: list[tuple[int, Mark]] = []
    at = 0
    for mark in marks:
        marker = mark[0]
        i = 0 if marker is None else text.find(marker, at)
        if i < 0 or (found and i <= found[-1][0]):
            continue
        found.append((i, mark))
        at = i + 1
    if not found or found[0][0] != 0:
        found.insert(0, (0, (None, "Prompt", "the code", "call", "instructions")))
    out = []
    for n, (i, (_m, name, source, stability, kind)) in enumerate(found):
        end = found[n + 1][0] if n + 1 < len(found) else len(text)
        out.append(part(name, text[i:end], source, stability, kind=kind))
    return out


def _prefix(parts: list[dict[str, Any]], stop: tuple[str, ...] = ("call",)) -> int:
    """Characters before the first part that changes between calls (``stop``: between projects too)."""
    total = 0
    for p in parts:
        if p["stability"] in stop:
            break
        total += p["chars"]
    return total


def violations(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each part less stable than a later part worth caching: what is placed before what, and how many characters
    an endpoint could cache if they swapped places."""
    out = []
    for i, p in enumerate(parts):
        later = [q for q in parts[i + 1:] if RANK[q["stability"]] < RANK[p["stability"]]]
        size = sum(q["chars"] for q in later)
        if later and size >= VIOLATION_MIN:
            out.append({"part": p["name"], "stability": p["stability"], "before": [q["name"] for q in later],
                        "chars_behind": size})
    return out


def window(role: str | None) -> int | None:
    """The context window, in tokens, of the role's endpoint as the routing names it (its own, else the routing's
    default); None for a surface no Rihma role answers (a coding agent's)."""
    if role not in LANE_OF:
        return None
    from kernel.lanes import load_routing

    try:
        routing = load_routing()
    except (OSError, ValueError):
        return None
    spec = (routing.get("roles") or {}).get(role) or {}
    ep = (routing.get("endpoints") or {}).get(spec.get("endpoint") or "") or {}
    value = ep.get("max_context_tokens", routing.get("max_context_tokens"))
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        value = routing.get("max_context_tokens")
    return value if isinstance(value, int) and value > 0 else None


def budget(kind: str, role: str | None) -> dict[str, Any]:
    """A pack's budget in tokens: the prompt economy's for its kind, or a quarter of the window when smaller."""
    economy, why = ECONOMY.get(kind, (OUTPUT_BUDGET, "one answer"))
    win = window(role)
    if win is not None and win // 4 < economy:
        return {"tokens": win // 4, "why": f"a quarter of the role's {win:,}-token window", "window": win}
    return {"tokens": economy, "why": why, "window": win}


def system_part(role: str | None) -> dict[str, Any] | None:
    """The lane's system prompt a role reads before its task (kernel/lanes.py), as a static part; None when the
    surface has none of Rihma's."""
    from kernel import lanes

    lane = LANE_OF.get(role or "")
    if lane is None:
        return None
    text = lanes.analyst_system_md() if lane == "analyst" else lanes.product_system_md()
    where = "kernel/lanes.py analyst_system_md" if lane == "analyst" else "kernel/lanes.py product_system_md"
    return part(f"The {lane} lane's system prompt", text, where, "static", kind="system")


def pack(pid: str, pack_id: str, *, label: str, role: str | None, surface: str, where: str, text: str,
         parts: list[dict[str, Any]], excluded: list[dict[str, str]] | None = None,
         compressed: list[dict[str, str]] | None = None, target: str | None = None,
         note: str | None = None) -> dict[str, Any]:
    """A context pack: the parts, their sizes, the budget, the cache-friendly prefix and what was left out."""
    if "".join(p["content"] for p in parts) != text:
        raise AssertionError(f"the parts of {pack_id} do not join back to its prompt")
    system = system_part(role)
    head = system["chars"] if system else 0
    chars = len(text)
    spent = tokens(head + chars)
    plan = budget(pack_id, role)
    within, shared = head + _prefix(parts), head + _prefix(parts, ("call", "project"))
    return {"id": pack_id, "label": label, "role": role, "surface": surface, "where": where, "target": target,
            "project": pid, "system": system, "parts": parts, "text": text, "chars": chars,
            "tokens": tokens(chars), "with_system": {"chars": head + chars, "tokens": spent},
            "budget": plan, "over_budget": spent > plan["tokens"],
            "prefix": {"chars": within, "ratio": round(within / max(head + chars, 1), 3)},
            "shared": {"chars": shared, "ratio": round(shared / max(head + chars, 1), 3)},
            "violations": violations(parts), "excluded": list(excluded or []), "compressed": list(compressed or []),
            "content_personas": list(CONTENT_PERSONAS.get(pack_id, ())) or "every persona",
            **({"note": note} if note else {})}


def may_see(pack_id: str, persona: str | None) -> bool:
    """Whether a persona may read a pack's content (its sizes and sources every persona may)."""
    allowed = CONTENT_PERSONAS.get(pack_id)
    return allowed is None or persona in allowed


def shown(p: dict[str, Any], persona: str | None, held: list[str] | None = None) -> dict[str, Any]:
    """A pack as a person sees it: every content (the system prompt's too) only for a persona that may see it,
    and with anything of the holdout custody replaced either way (it never leaves its custody)."""
    from kernel.custody import redact

    see = may_see(p["id"], persona)

    def one(x: dict[str, Any]) -> dict[str, Any]:
        if not see:
            return {k: v for k, v in x.items() if k != "content"} | {"content": None}
        return x | {"content": redact(x["content"], held or [])}

    out = {k: v for k, v in p.items() if k != "text"}
    out["parts"] = [one(x) for x in p["parts"]]
    out["system"] = one(p["system"]) if p.get("system") else None
    out["content_shown"] = see
    if not see:
        out["content_note"] = (f"Its content is shown to {', '.join(CONTENT_PERSONAS[p['id']])} only: the criteria "
                               "a holdout checks are judged out of the builder's sight.")
    return out


def summary(p: dict[str, Any]) -> dict[str, Any]:
    """A pack in one row: what the list in the Context view shows."""
    keys = ("id", "label", "role", "surface", "where", "target", "chars", "tokens", "over_budget", "prefix", "shared")
    return {k: p[k] for k in keys} | {"budget": p["budget"]["tokens"], "with_system": p["with_system"]["tokens"],
                                      "parts": len(p["parts"]), "excluded": len(p["excluded"]),
                                      "compressed": len(p["compressed"]), "violations": len(p["violations"])}
