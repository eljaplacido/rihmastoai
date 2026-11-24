"""Confidential material: keep it on local models (docs/guides/inputs.md, Confidential material).

A person marks a project confidential when they create or adopt it (`--confidential`, the cockpit's
"Confidential: keep on local models" box). The setting is recorded in the project and the ledger. While it
is set, intake and every model call for the project may only go to an endpoint on this machine (loopback)
or on a private network address: the routes in kernel/routing.json with this machine's
kernel/routing.local.json over them, the role's fallback included. A role that would go to a hosted
endpoint is refused with a message naming the role and how to configure a local model
(docs/guides/local-models.md), and the refusal is recorded. Nothing is ever sent silently.

An endpoint is local by its address: `localhost`, a name reserved for private networks (.local, .lan,
.internal, .home.arpa), a loopback, private, link-local or shared (100.64.0.0/10, a Tailscale or carrier
network) IP address; or because its owner declared it private in the routing overlay
(`"private": true` on the endpoint in kernel/routing.local.json): a GPU box on a tailnet or a VPN, reached by
name. Any other host name is taken as hosted: Rihmasto does not resolve names, so it cannot know where one points.
"""

from __future__ import annotations

import ipaddress
import urllib.parse
from collections.abc import Iterable
from typing import Any

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
        return True
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
                url = ep.get("url")
                out.append({"role": role, "which": which, "endpoint": route["endpoint"], "url": url,
                            "local": is_local(url, ep)})
    return out


def _host(url: str | None) -> str:
    return urllib.parse.urlsplit(str(url or "")).hostname or "no address"


def refusal(roles: Iterable[str], routing: dict[str, Any] | None = None) -> str:
    """Why confidential material may not be sent for ``roles``, or "" when every route is local."""
    hosted = [r for r in routes(roles, routing) if not r["local"]]
    if not hosted:
        return ""
    named = "; ".join(f"the {r['role']} role{' (its fallback)' if r['which'] == 'fallback' else ''} would go to "
                      f"the hosted endpoint {r['endpoint']!r} ({_host(r['url'])})" for r in hosted)
    fallbacks = sorted({r["role"] for r in hosted if r["which"] == "fallback"})
    drop = (" A hosted fallback goes when you set the role again without it: in Models setup (Settings, Models), "
            "Change, untick Keep the fallback; or `rihmasto models set " + fallbacks[0] + " ... --private "
            "--no-fallback`.") if fallbacks else ""
    return (f"refused: this project is confidential (keep on local models), and {named}. Nothing was sent. "
            "Route those roles, fallbacks included, to a model on this machine or your private network in "
            f"Models setup or kernel/routing.local.json ({GUIDE}), then run it again.{drop}")


def confidential(project: Any) -> bool:
    return bool((project.meta or {}).get("confidential"))


def require_local(project: Any, roles: Iterable[str] = ROLES, *, where: str,
                  routing: dict[str, Any] | None = None) -> None:
    """Refuse, and record the refusal, when a confidential project's call for ``roles`` would leave for a
    hosted endpoint. A project that is not confidential is never refused here."""
    if not confidential(project):
        return
    roles = list(roles)
    why = refusal(roles, routing)
    if why:
        hosted = [{k: r[k] for k in ("role", "which", "endpoint")} for r in routes(roles, routing) if not r["local"]]
        project.log("confidential_refused", {"where": where, "hosted": hosted, "guide": GUIDE})
        raise ConfidentialRefused(why)


def local_model(project: Any, model: Any, role: str) -> Any:
    """``model`` when the project may send to ``role``'s endpoints, else None: a caller that can work by
    rule alone (a change's triage) does so for a confidential project rather than send."""
    if model is None or not confidential(project) or not refusal([role]):
        return model
    project.log("confidential_by_rule", {"role": role, "why": "the role's endpoint is hosted: worked by rule"})
    return None


def mark(project: Any, *, person: str | None, persona: str | None, on: bool = True) -> None:
    """Record the setting in the project and the ledger, with who set it and which routes it holds to."""
    project.update_meta(confidential=on)
    project.log("confidential_set", {"confidential": on, "person": person, "persona": persona,
                                     "rule": "only endpoints on loopback or a private network address",
                                     "routes": routes(ROLES)})


def send_to(role: str = "analyst", routing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Where a request would go for ``role``: the endpoint's name, its host and whether it is local."""
    first = next((r for r in routes([role], routing) if r["which"] == "primary"), None)
    if first is None:
        return {"role": role, "endpoint": None, "host": None, "local": False}
    return {"role": role, "endpoint": first["endpoint"], "host": _host(first["url"]), "local": first["local"]}
