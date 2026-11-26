"""Confidential material: keep it on local models (docs/guides/inputs.md, Confidential material).

A person marks a project confidential when they create or adopt it (`--confidential`, the cockpit's
"Confidential: keep on local models" box). The setting is recorded in the project and the ledger. While it
is set, intake and every model call for the project may only go to an endpoint on this machine (loopback)
or on a private network address: the routes in kernel/routing.json with this machine's
kernel/routing.local.json over them. A role whose primary endpoint is hosted is refused with a message
naming the role and how to configure a local model (docs/guides/local-models.md), and the refusal is
recorded. Nothing is ever sent silently.

A role whose primary endpoint is local but whose fallback is hosted is not refused (the owner's decision of
2026-11-24, "Skip"): the hosted fallback is skipped and never called. The lanes a confidential project's
calls run in are compiled without it (``without_hosted_fallbacks``: the analyst lane under
``<lanes>/confidential``, and the product's own surface), so Gnomon has no hosted endpoint to fall back to;
the ledger records ``confidential_fallback_skipped`` once per run, naming the role and the host.

An endpoint is local by its address: `localhost`, a name reserved for private networks (.local, .lan,
.internal, .home.arpa), a loopback, private, link-local or shared (100.64.0.0/10, a Tailscale or carrier
network) IP address; or because its owner declared it private in the routing overlay
(`"private": true` on the endpoint in kernel/routing.local.json): a GPU box on a tailnet or a VPN, reached by
name. Any other host name is taken as hosted: Rihmasto does not resolve names, so it cannot know where one points.
"""

from __future__ import annotations

import contextlib
import ipaddress
import urllib.parse
from collections.abc import Iterable, Iterator
from contextvars import ContextVar
from typing import Any

from kernel.harness_model import for_project, hosted
from kernel.model import GnomonModel

GUIDE = "docs/guides/local-models.md"
ROLES = ("analyst", "holdout_author", "builder", "verifier")     # every role a project's work asks


class ConfidentialRefused(PermissionError):
    """A confidential project's model call would leave for a hosted endpoint."""


def _routing() -> dict[str, Any]:
    """The routing the factory runs on: the shipped file with this machine's overlay."""
    from kernel.lanes import read_routing

    return read_routing() or {}


SHARED = ipaddress.ip_network("100.64.0.0/10")      # Tailscale and carrier-grade NAT: never the open internet
# Names reserved for private networks, which public DNS never answers (.lan by long convention).
PRIVATE_NAMES = (".localhost", ".local", ".lan", ".internal", ".home.arpa")


def is_local(url: str | None, endpoint: dict[str, Any] | None = None) -> bool:
    """Whether an endpoint is on this machine or a private network: by its address (a URL or a bare host), or
    because its owner declared it private (``endpoint["private"] is True``, kernel/routing.local.json)."""
    if isinstance(endpoint, dict) and endpoint.get("private") is True:
        return not hosted(endpoint)        # Claude Code's and Codex's model is hosted, whatever is declared (FR-HMD1)
    text = str(url or "").strip()
    host = (urllib.parse.urlsplit(text if "://" in text else "//" + text).hostname or "").strip("[]").lower()
    if host == "localhost" or host.endswith(PRIVATE_NAMES):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local or (ip.version == 4 and ip in SHARED)


def routes(roles: Iterable[str], routing: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Each role's endpoints, its fallback's too: the role, primary or fallback, the endpoint's name and
    URL, and whether it is local."""
    routing = _routing() if routing is None else routing
    endpoints = routing.get("endpoints") or {}
    out = []
    for role in roles:
        spec = (routing.get("roles") or {}).get(role)
        if not isinstance(spec, dict):
            continue
        for which, route in (("primary", spec), ("fallback", spec.get("fallback"))):
            if isinstance(route, dict) and route.get("endpoint"):
                ep = endpoints.get(route["endpoint"]) or {}
                url = ep.get("url") or (f"harness://{ep.get('harness')}" if ep.get("kind") == "harness" else None)
                out.append({"role": role, "which": which, "endpoint": route["endpoint"], "url": url,
                            "local": is_local(url, ep)})
    return out


def _host(url: str | None) -> str:
    return urllib.parse.urlsplit(str(url or "")).hostname or "no address"


def refusal(roles: Iterable[str], routing: dict[str, Any] | None = None) -> str:
    """Why confidential material may not be sent for ``roles``, or "" when every role's primary endpoint is
    local. A hosted fallback is no reason: it is skipped (``skipped``), never called."""
    hosted = [r for r in routes(roles, routing) if r["which"] == "primary" and not r["local"]]
    if not hosted:
        return ""
    named = "; ".join(f"the {r['role']} role would go to the hosted endpoint {r['endpoint']!r} ({_host(r['url'])})"
                      for r in hosted)
    return (f"refused: this project is confidential (keep on local models), and {named}. Nothing was sent. "
            "Route those roles to a model on this machine or your private network in Models setup or "
            f"kernel/routing.local.json ({GUIDE}), then run it again.")


def skipped(roles: Iterable[str], routing: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The hosted fallbacks of roles whose primary endpoint is local: a confidential project never calls them."""
    rs = routes(roles, routing)
    local = {r["role"] for r in rs if r["which"] == "primary" and r["local"]}
    return [r for r in rs if r["which"] == "fallback" and not r["local"] and r["role"] in local]


def without_hosted_fallbacks(routing: dict[str, Any]) -> dict[str, Any]:
    """The routing with every role's hosted fallback left out, for the lanes a confidential project's calls run
    in: Gnomon cannot fall back to an endpoint its surface does not name."""
    endpoints = routing.get("endpoints") or {}
    roles = {}
    for name, spec in (routing.get("roles") or {}).items():
        fb = spec.get("fallback") if isinstance(spec, dict) else None
        ep = endpoints.get(fb.get("endpoint")) if isinstance(fb, dict) else None
        if isinstance(fb, dict) and not is_local((ep or {}).get("url"), ep):
            spec = {k: v for k, v in spec.items() if k != "fallback"}
        roles[name] = spec
    return {**routing, "roles": roles}


def confidential(project: Any) -> bool:
    return bool((project.meta or {}).get("confidential"))


def routing_for(project: Any, routing: dict[str, Any]) -> dict[str, Any]:
    """The routing a project's own lane is compiled from: without hosted fallbacks while it is confidential."""
    return without_hosted_fallbacks(routing) if confidential(project) else routing


_RUN: ContextVar[set[tuple[str, str, str]] | None] = ContextVar("confidential_run", default=None)


@contextlib.contextmanager
def one_run() -> Iterator[None]:
    """A run (kernel/pipeline.py advance): a skipped fallback is recorded once in it, however often it asks."""
    token = _RUN.set(set())
    try:
        yield
    finally:
        _RUN.reset(token)


def _record_skips(project: Any, roles: list[str], routing: dict[str, Any] | None, where: str) -> None:
    """Record each hosted fallback skipped for ``roles``: once per run, naming the role and the host. Outside
    a run each call is its own."""
    seen = _RUN.get()
    for r in skipped(roles, routing):
        key = (str(getattr(project, "pid", "")), r["role"], r["endpoint"])
        if seen is not None and key in seen:
            continue
        if seen is not None:
            seen.add(key)
        project.log("confidential_fallback_skipped", {"role": r["role"], "endpoint": r["endpoint"],
                                                      "host": _host(r["url"]), "where": where,
                                                      "why": "confidential: the hosted fallback is never called"})


def require_local(project: Any, roles: Iterable[str] = ROLES, *, where: str,
                  routing: dict[str, Any] | None = None) -> None:
    """Refuse, and record the refusal, when a confidential project's call for ``roles`` would go to a hosted
    primary endpoint; record the hosted fallbacks it skips. A project that is not confidential is never
    refused here."""
    if not confidential(project):
        return
    roles = list(roles)
    why = refusal(roles, routing)
    if why:
        hosted = [{k: r[k] for k in ("role", "which", "endpoint")} for r in routes(roles, routing)
                  if r["which"] == "primary" and not r["local"]]
        project.log("confidential_refused", {"where": where, "hosted": hosted, "guide": GUIDE})
        raise ConfidentialRefused(why)
    _record_skips(project, roles, routing, where)


class LocalLaneModel(GnomonModel):
    """Gnomon in an analyst lane compiled for confidential work (``<lanes>/confidential/analyst``): every
    role's hosted fallback is left out of its surface, so Gnomon has none to fall back to. It is compiled
    again from the routing before each call, as Models setup's lane is."""

    confidential_lane = True

    def __init__(self, timeout: int = 900, deadline: int | None = None) -> None:
        from kernel.lanes import lanes_root

        super().__init__(lanes_root() / "confidential" / "analyst", timeout=timeout, deadline=deadline)

    def ask(self, prompt: str, *, role: str) -> str:
        from kernel import lanes

        routing = without_hosted_fallbacks(lanes.load_routing())
        with lanes.lane_lock(self.lane_dir):
            self.lane_dir = lanes.ensure_analyst_lane(routing, root=self.lane_dir.parent)
        return super().ask(prompt, role=role)


def local_lane(model: Any) -> Any:
    """A Gnomon model whose lane cannot fall back to a hosted endpoint, for a confidential project's call;
    any other model (a scripted one) as it is."""
    if not isinstance(model, GnomonModel) or getattr(model, "confidential_lane", False):
        return model
    return LocalLaneModel(timeout=model.timeout, deadline=model.deadline)


def guard(project: Any, model: Any, roles: Iterable[str], *, where: str) -> Any:
    """``require_local``, then the model the call may use: for a confidential project, one whose lane has no
    hosted fallback (``local_lane``). A role a harness answers records its call in the project's ledger."""
    require_local(project, roles, where=where)
    return for_project(project, local_lane(model) if confidential(project) else model, roles)


def local_model(project: Any, model: Any, role: str) -> Any:
    """``model`` when the project may send to ``role``'s endpoints (in a lane with no hosted fallback while it
    is confidential), else None: a caller that can work by rule alone (a change's triage) does so for a
    confidential project rather than send."""
    if model is None or not confidential(project):
        return model
    if refusal([role]):
        project.log("confidential_by_rule", {"role": role, "why": "the role's endpoint is hosted: worked by rule"})
        return None
    _record_skips(project, [role], None, "a change")
    return local_lane(model)


def mark(project: Any, *, person: str | None, persona: str | None, on: bool = True) -> None:
    """Record the setting in the project and the ledger, with who set it and which routes it holds to."""
    project.update_meta(confidential=on)
    project.log("confidential_set", {"confidential": on, "person": person, "persona": persona,
                                     "rule": "only endpoints on loopback or a private network address; a hosted "
                                             "fallback is skipped",
                                     "routes": routes(ROLES)})


def send_to(role: str = "analyst", routing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Where a request would go for ``role``: the endpoint's name, its host and whether it is local."""
    first = next((r for r in routes([role], routing) if r["which"] == "primary"), None)
    if first is None:
        return {"role": role, "endpoint": None, "host": None, "local": False}
    return {"role": role, "endpoint": first["endpoint"], "host": _host(first["url"]), "local": first["local"]}


def assistant_kept_local(project: Any, model: Any) -> tuple[Any, dict[str, Any]]:
    """No model, and a note, for a confidential project whose assistant model is hosted (kernel/assistant.py):
    it is answered from the cockpit map, and nothing about it is sent."""
    if model is None or project is None or not confidential(project) or not refusal(["assistant"]):
        return model, {}
    return None, {"note": "this project is confidential and the assistant's model is hosted: answered from the map"}
