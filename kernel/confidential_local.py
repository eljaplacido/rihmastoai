"""Confidential adoption, said plainly and fixed in one click (FR-RPJ1; docs/guides/local-models.md).

Adopting a confidential project calls no model: it reads the repository and runs its tests. So a hosted role is
no reason to stop it; it is a reason the project's later model work would be refused. The New project dialog
says exactly that (`notice`): "Adopting works (it calls no model). These roles would be refused until they use
a local model: ...". When the routing already has a local or private endpoint that a role uses (Models setup),
`offer` names it and `use_local` points the hosted roles at it with that role's model, signed by a person and
recorded in the factory's ledger like any change of Models setup (``models_set``); each role's fallback is kept
(a confidential project skips a hosted fallback, never calls it).
"""

from __future__ import annotations

from typing import Any

from kernel import confidential as kc


def hosted(roles: Any = kc.ROLES, routing: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [r for r in kc.routes(roles, routing) if r["which"] == "primary" and not r["local"]]


def _locals(routing: dict[str, Any]) -> list[dict[str, Any]]:
    """The local models the routing already uses (a role's primary or fallback), each once, with its family."""
    out: dict[str, dict[str, Any]] = {}
    for spec in (routing.get("roles") or {}).values():
        for route in (spec, (spec or {}).get("fallback")) if isinstance(spec, dict) else ():
            if not isinstance(route, dict) or not route.get("endpoint") or not route.get("model"):
                continue
            ep = (routing.get("endpoints") or {}).get(route["endpoint"]) or {}
            if kc.is_local(ep.get("url"), ep) and route["model"] not in out:
                family = ((routing.get("models") or {}).get(route["model"]) or {}).get("family")
                out[route["model"]] = {"endpoint": route["endpoint"], "model": route["model"], "family": family,
                                       "host": kc._host(ep.get("url"))}
    return list(out.values())


def _verifier(routing: dict[str, Any], plan: dict[str, dict[str, Any]], found: list[dict[str, Any]]
              ) -> tuple[dict[str, Any] | None, str | None]:
    """A local model for the verifier of another family than the builder's (as planned, or as routed now)."""
    builder = plan.get("builder") or (routing.get("roles") or {}).get("builder") or {}
    fam = builder.get("family") or ((routing.get("models") or {}).get(builder.get("model")) or {}).get("family")
    return next((c for c in found if c["family"] != fam), None), fam


def offer(routing: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Which local model each hosted role could use, or None when there is none to offer. The verifier keeps
    to a family other than the builder's (the routing's own rule); with no such local model it is left out."""
    routing = kc._routing() if routing is None else routing
    away = [r["role"] for r in hosted(kc.ROLES, routing)]
    found = _locals(routing)
    if not away or not found:
        return None
    plan: dict[str, dict[str, Any]] = {r: found[0] for r in away if r != "verifier"}
    left: dict[str, str] = {}
    if "verifier" in away:
        pick, fam = _verifier(routing, plan, found)
        if pick is None:
            left["verifier"] = f"no local model of another family than the builder's ({fam}): set one in Models setup"
        else:
            plan["verifier"] = pick
    if not plan:
        return None
    first = next(iter(plan.values()))
    return {"endpoint": first["endpoint"], "model": first["model"], "host": first["host"], "roles": list(plan),
            "plan": {r: {k: v[k] for k in ("endpoint", "model", "host")} for r, v in plan.items()}, "left": left}


def notice(routing: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """What a confidential adoption's dialog says, and what it offers; None when every role is local."""
    away = hosted(kc.ROLES, routing)
    if not away:
        return None
    named = ", ".join(f"{r['role']} (the hosted endpoint {r['endpoint']!r}, {kc._host(r['url'])})" for r in away)
    got = offer(routing)
    return {"text": f"Adopting works (it calls no model). These roles would be refused until they use a local model: "
                    f"{named}.", "roles": [r["role"] for r in away], "offer": got,
            "fix": (f"Use my local model for {', '.join(got['roles'])}: {got['model']} on {got['endpoint']} "
                    f"({got['host']}), for every project on this machine (the routing is machine-wide)"
                    + "".join(f"; the {r} is left out: {why}" for r, why in got["left"].items())
                    if got else _no_offer(routing, [r["role"] for r in away]))}


def _no_offer(routing: dict[str, Any] | None, away: list[str]) -> str:
    """Why there is no one-click choice, so a person knows what to set up: no local model at all, or, for the
    verifier alone, none of another family than the builder's (the verifier never checks its own family)."""
    routing = kc._routing() if routing is None else routing
    found = _locals(routing)
    if found and away == ["verifier"]:
        _, fam = _verifier(routing, {}, found)
        have = ", ".join(sorted({f"{c['model']} ({c['family'] or 'family not stated'})" for c in found}))
        return (f"No one-click choice: the verifier checks the builder's work, so it needs a local model of another "
                f"family than the builder's ({fam}); "
                + (f"the local models in use are {have}" if len(found) > 1 else f"the local model in use is {have}")
                + ". Add one and route the verifier to it")
    return "Route them to a model on this machine or your private network in Models setup"


def use_local(factory: Any, *, person: str, persona: str, roles: list[str] | None = None) -> dict[str, Any]:
    """Point the hosted roles (or ``roles`` among them) at the local endpoint `offer` names, signed."""
    from kernel import models_setup as ms

    ms._signed(person, persona)
    got = offer()
    if got is None:
        raise ms.ModelsRefused("refused: no local or private endpoint is in use by any role: set one up in Models "
                               "setup first")
    chosen = [r for r in got["roles"] if roles is None or r in roles]
    routing = ms.lanes.read_routing() or {}
    overlay = ms._overlay()
    for role in chosen:
        fb = (routing.get("roles") or {}).get(role, {}).get("fallback")
        to = got["plan"][role]
        overlay.setdefault("roles", {})[role] = {"model": to["model"], "endpoint": to["endpoint"],
                                                 **({"fallback": fb} if fb else {})}
    ms._keep(overlay)
    for role in chosen:
        to = got["plan"][role]
        ms._ledger(factory, "models_set", {"role": role, "model": to["model"], "endpoint": to["endpoint"],
                                           "host": to["host"], "local": True, "key": "unchanged", "person": person,
                                           "persona": persona, "via": "confidential: use my local model"})
    return {"roles": chosen, "endpoint": got["endpoint"], "model": got["model"], "host": got["host"],
            "left": got["left"], "still_hosted": [r["role"] for r in hosted()]}
