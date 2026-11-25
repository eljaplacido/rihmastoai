"""Models setup for the coding agents a person already has: Claude Code, Codex and OpenCode (FR-HMD1).

docs/guides/harness-models.md is the guide; kernel/harness_model.py runs them. Here:

- ``harnesses``: which of them are on this machine, with their versions (kernel/runners/detect.py's detection);
- ``use``: point roles at one (``rihmasto models use claude-code --roles all``, the cockpit's "Use Claude Code"),
  signed by a person, written to this machine's overlay (kernel/routing.local.json) and checked as every routing
  change is (the verifier another model family than the builder, FR-G6), and recorded in the factory's ledger;
- ``probe``: Models setup's Test for a role a harness answers: a tiny prompt through the harness, its latency or error;
- ``view_extra``, ``role_extra``, ``readiness`` and ``doctor_part``: what Models setup, Home's "Set up a model" card and
  `rihmasto doctor` add, among them "No API key? Claude Code found: use it" when one is installed.

"For every role" is the text roles: the analyst, the holdout author, the verifier and the assistant. The builder
writes code, so its harness is a cell runner (`rihmasto runners set builder claude-code`, docs/guides/harnesses.md).
A harness run per call is slower than an API endpoint and spends the person's own subscription; the page says so.
"""

from __future__ import annotations

from typing import Any

from kernel import harness_model as hm

FOUND_HERE = ("claude-code", "codex", "opencode")
ALL_ROLES = hm.TEXT_ROLES
SLOWER = ("A harness starts once per call: slower than an API endpoint, and each call spends your own "
          "subscription or plan with that tool.")
TEST_PROMPT = "Reply with the single word OK."
TEST_TIMEOUT = 120
PRESETS: list[dict[str, Any]] = [
    {"id": "use_claude_code", "harness": "claude-code", "label": "Use Claude Code (your login)"},
    {"id": "use_codex", "harness": "codex", "label": "Use Codex"},
    {"id": "use_opencode", "harness": "opencode", "label": "Use OpenCode"},
]


def harnesses(*, look: bool = True) -> list[dict[str, Any]]:
    """Claude Code, Codex and OpenCode: each one's label, family, whether its model is hosted, and (with ``look``)
    whether it is on this machine and its version."""
    out = []
    for name in FOUND_HERE:
        meta = hm.HARNESSES[name]
        row = {"id": name, "label": meta["label"], "family": meta["family"], "hosted": meta["hosted"],
               "preset": next(p for p in PRESETS if p["harness"] == name)}
        if look:
            found = hm.detect(name)
            row |= {"found": bool(found["found"]), "version": found.get("version"), "why": found.get("why") or ""}
        out.append(row)
    return out


def found_harnesses() -> list[dict[str, Any]]:
    return [h for h in harnesses() if h.get("found")]


def _roles(given: Any, routing: dict[str, Any]) -> list[str]:
    words = given if isinstance(given, list) else str(given or "all").split(",")
    names = [str(w).strip() for w in words if str(w).strip()]
    if not names or names == ["all"]:
        return [r for r in ALL_ROLES if r in (routing.get("roles") or {})]
    for name in names:
        if name == "builder":
            raise hm.HarnessRefused("the builder writes code, so its harness is a cell runner: rihmasto runners set "
                                    "builder <harness> (docs/guides/harnesses.md)")
        if name not in ALL_ROLES or name not in (routing.get("roles") or {}):
            raise hm.HarnessRefused(f"there is no text role {name!r}; they are {', '.join(ALL_ROLES)} (or all)")
    return list(dict.fromkeys(names))


def _family(harness: str, model: str, family: str | None) -> str:
    from kernel.models_setup import family_of

    named = (family or "").strip().lower()
    if named:
        return named
    if hm.HARNESSES[harness]["family"]:
        return str(hm.HARNESSES[harness]["family"])
    if model:
        return family_of(model)
    raise hm.HarnessRefused(f"name the model family {hm.label_of(harness)} answers with (--family), or its model "
                            "(--model provider/name): the verifier must be another family than the builder")


def use(factory: Any, harness: str, *, person: str, persona: str, roles: Any = "all", model: str = "",
        family: str | None = None, private: bool = False, command: str | None = None) -> dict[str, Any]:
    """Point ``roles`` (all the text roles by default) at ``harness``, signed by a person. Refused when the harness
    is not on this machine, when Claude Code or Codex is declared private, or when the result breaks FR-G6."""
    from kernel import lanes
    from kernel import models_setup as ms

    ms._signed(person, persona)
    if harness not in hm.HARNESSES:
        raise hm.HarnessRefused(f"there is no harness {harness!r}; they are {', '.join(hm.HARNESSES)}")
    if private and hm.HARNESSES[harness]["hosted"]:
        raise hm.HarnessRefused(f"{hm.label_of(harness)}'s model is hosted by its provider, so it cannot be declared "
                                "private: a confidential project refuses it like any hosted model")
    if harness == "command" and not str(command or "").strip():
        raise hm.HarnessRefused("the command harness needs its command line (--command)")
    routing = lanes.read_routing() or {}
    chosen, model = _roles(roles, routing), (model or "").strip()
    found = hm.detect(harness, {"harness": harness, "command": command}, fresh=True)
    if not found["found"]:
        raise hm.HarnessRefused(found["why"])
    fam = _family(harness, model, family)
    name, key = f"{harness}-custom", model or hm.default_model(harness)
    overlay = ms._overlay()
    overlay.setdefault("endpoints", {})[name] = {
        "kind": hm.KIND, "harness": harness, "version": found.get("version"),
        **({"private": True} if private else {}), **({"command": command} if command else {})}
    for role in chosen:
        overlay.setdefault("roles", {})[role] = {"model": key, "endpoint": name}
    overlay.setdefault("models", {})[key] = {"family": fam}
    ms._drop_unused(overlay)
    merged = ms._keep(overlay)
    ms._ledger(factory, "models_use", {
        "harness": harness, "version": found.get("version"), "roles": chosen, "model": key, "family": fam,
        "private": private, "person": person, "persona": persona,
        "assurance": hm.ASSURANCE.format(label=hm.label_of(harness))})
    views = [ms.role_view(merged, r, overlay, probe=False) for r in chosen]
    return {"harness": harness, "label": hm.label_of(harness), "version": found.get("version"), "family": fam,
            "roles": views, "note": SLOWER, "assurance": hm.ASSURANCE.format(label=hm.label_of(harness))}


def add_use_parser(models: Any, signer: Any) -> None:
    """`rihmasto models use <harness> [--roles all|analyst,assistant,...]`, signed (kernel/shape_cli.py)."""
    u = signer(models.add_parser("use", help="answer the text roles with a coding agent you already have "
                                             "(docs/guides/harness-models.md)"))
    u.add_argument("harness", choices=list(hm.HARNESSES))
    u.add_argument("--roles", default="all", help="all (the analyst, holdout author, verifier and assistant), or "
                                                 "a comma-separated list such as analyst,assistant")
    u.add_argument("--model", help="the model the harness uses (default: the one it is set to use)")
    u.add_argument("--family", help="the model family it answers with (OpenCode and a command need it unless "
                                    "--model names it)")
    u.add_argument("--private", action="store_true",
                   help="OpenCode or a command on a model on your own network: confidential projects may use it")
    u.add_argument("--command", help="the command harness's line, with {prompt_file} where the task goes")


# -- what Models setup, Home and doctor show ------------------------------------------------------------------

def role_extra(endpoint: dict[str, Any]) -> dict[str, Any]:
    """A role's harness, as Models setup shows it: which one, the version set, and the honest assurance."""
    if not hm.is_harness(endpoint):
        return {}
    name = str(endpoint.get("harness"))
    return {"harness": {"name": name, "label": hm.label_of(name), "version": endpoint.get("version"),
                        "hosted": hm.hosted(endpoint), "assurance": hm.ASSURANCE.format(label=hm.label_of(name)),
                        "note": SLOWER}}


def readiness(endpoint: dict[str, Any], probe: bool) -> dict[str, str] | None:
    """A harness role's readiness: on this machine or not. None for an endpoint that is not a harness."""
    if not hm.is_harness(endpoint):
        return None
    name = str(endpoint.get("harness"))
    if not probe:
        return {"state": "configured", "why": f"answered by {hm.label_of(name)}; not checked"}
    found = hm.detect(name, {"harness": name, "command": endpoint.get("command")})
    if found["found"]:
        return {"state": "ready", "why": f"{hm.label_of(name)} {found.get('version')} is on this machine"}
    return {"state": "unreachable", "why": found["why"]}


def view_extra(roles: list[dict[str, Any]], gnomon: bool, probe: bool) -> dict[str, Any]:
    """Models setup's harnesses and presets, and whether a model Rihma talks with answers: a harness needs no
    Gnomon, an endpoint does."""
    talking = [r for r in roles if r["role"] in ("analyst", "assistant")]
    ready = any(r["readiness"]["state"] in ("ready", "configured") and (gnomon or r.get("harness")) for r in talking)
    return {"harnesses": harnesses(look=probe), "harness_presets": PRESETS, "harness_note": SLOWER, "ready": ready,
            "text_roles": list(ALL_ROLES)}


def talking_by_harness() -> bool:
    """Whether the analyst or the assistant is answered by a harness that is on this machine (no Gnomon needed)."""
    routing = hm._routing()
    for role in ("analyst", "assistant"):
        route = hm.route_of(routing, role)
        if route and hm.detect(route["harness"], route)["found"]:
            return True
    return False


def probe(role: str, routing: dict[str, Any]) -> dict[str, Any] | None:
    """Test for a role a harness answers: a tiny prompt through it, how long it took or what went wrong. Records
    nothing. None when the role's endpoint is not a harness."""
    route = hm.route_of(routing, role)
    if route is None:
        return None
    record = hm.run(route, TEST_PROMPT, role=role, timeout=TEST_TIMEOUT)
    out = {"role": role, "model": record.get("model") or route["model"] or hm.default_model(route["harness"]),
           "host": f"{route['label']} on this machine", "harness": record["harness"], "ok": False, "note": SLOWER}
    if record["bucket"] != "result":
        return out | {"error": str(record.get("stop_reason"))[:300]}
    reply = " ".join(str(record["output"]).split())[:120]
    return out | {"ok": True, "latency_ms": round(float(record["seconds"]) * 1000), "reply": reply,
                  "tokens": record.get("usage"), "cost_usd": record.get("cost_usd")}


def doctor_part(routing: dict[str, Any], endpoints: list[dict[str, Any]], gnomon_found: bool,
                found: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """What `rihmasto doctor` adds: the harnesses on this machine (``found``, else looked for) and, when a key is
    missing (or Gnomon is) and no text role uses one yet, the suggestion to use the one that is installed."""
    found = found_harnesses() if found is None else found
    used = [r for r in ALL_ROLES if hm.route_of(routing, r)]
    out: dict[str, Any] = {"harnesses": [{k: h[k] for k in ("id", "label", "version", "family")} for h in found],
                           "harness_roles": used, "suggestions": []}
    missing = any(not e["set"] for e in endpoints) or not gnomon_found
    if found and missing and not used:
        h = found[0]
        names = " / ".join(x["label"] for x in found)
        out["suggestions"].append(
            f"No API key? {names} found: use it. `rihmasto models use {h['id']} --roles all --person \"<you>\" "
            f"--persona it` answers the text roles with {h['label']} {h['version']} (docs/guides/harness-models.md). "
            + SLOWER)
    return out
