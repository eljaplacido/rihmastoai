"""Destinations (FR-DST1), the groups beyond the roads: channels, published targets, connectors and sources.

kernel/destinations.py builds every destination with its `dest` and `action`; this module reads, never writes:

- **channels**: the website chats (embeds) that belong to the project; the relay's subscriptions that carry its
  events (Teams, Slack, email, signed webhooks), healthy or failing by their delivery log; and the faces its
  release declares in `app/runtime.json` (MCP, HTTP, OpenAI-compatible chat, website embed), delivered once a
  person served one (`capability_served`), with who served it as its consumers;
- **published**: every registry IT named (kernel/registries.py) with what this project published there
  (kernel/publish.py), and the outputs built for its audiences (kernel/outputs.py);
- the state of the connector through which Rihmasto itself reaches a data system, and the webhook sources bound
  to the project.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

FACE_LABEL = {"mcp": "MCP face", "http": "HTTP API face", "openai": "OpenAI-compatible chat face",
              "embed": "Website embed face"}
SINK_LABEL = {"teams": "Teams notices", "slack": "Slack notices", "email": "Email notices",
              "webhook": "Signed webhook events"}
Dest = Callable[..., dict[str, Any]]


def connector_state(factory: Any, system: str | None) -> dict[str, Any] | None:
    if not system:
        return None
    from kernel import connectors

    try:
        return {k: v for k, v in connectors.state_of(factory, system).items() if k in ("system", "state", "reason")}
    except (OSError, ValueError, KeyError) as exc:
        return {"system": system, "state": "unknown", "reason": type(exc).__name__}


def hook_sources(project: Any, dest: Dest) -> list[dict[str, Any]]:
    """Inbound webhook sources IT bound to this project: what the capability is fed from."""
    from kernel import hooks

    rings: dict[str, dict] = {}
    for rec in project.ledger().of_kind("hook_received"):
        rings[str(rec["event"]["payload"].get("source"))] = {"at": rec["event"].get("at"), "what": "a ring arrived"}
    out = []
    for src in hooks.sources(project.factory):
        if src.get("state") != "active" or project.pid not in (src.get("projects") or []):
            continue
        last = rings.get(str(src.get("id")))
        out.append(dest(f"data:hook:{src['id']}", "data", "hook", f"Webhook source {src['id']}",
                        state="delivered" if last else "configured", last=last,
                        details={"scheme": src.get("scheme"), "becomes": src.get("becomes")},
                        note="feeds the project: each ring is recorded in its ledger"))
    return out


# -- channels --------------------------------------------------------------------------------------------

def _embeds(project: Any, dest: Dest) -> list[dict[str, Any]]:
    from kernel import embeds

    out = []
    for e in embeds.embeds(project.factory):
        if e.get("project") != project.pid or e.get("state") != "active":
            continue
        out.append(dest(f"channels:embed:{e['id']}", "channels", "embed",
                        f"Website chat {e.get('label') or e['id']}", state="delivered",
                        last={"at": e.get("created"), "what": f"created by {e.get('created_by')}"},
                        details={"kind": e.get("kind"), "origins": e.get("origins"), "messages": e.get("messages", 0)},
                        note=f"{e.get('messages', 0)} message(s) from {', '.join(e.get('origins') or [])}"))
    return out


def _unset(sub: dict[str, Any]) -> list[str]:
    mail = sub.get("mail") or {}
    names = [sub.get("url_env"), sub.get("secret_env"), mail.get("user_env"), mail.get("password_env")]
    return [f"the environment variable {n} is not set where the relay runs"
            for n in names if n and not os.environ.get(n)]


def _relay_one(project: Any, sub: dict[str, Any], dest: Dest, state_of: Callable[..., str]) -> dict[str, Any]:
    from kernel import relay

    rows = [r for r in relay.deliveries(project.factory, subscription=sub["id"], limit=0)
            if r.get("kind") == "delivery" and r.get("project") == project.pid]
    health = None
    if rows:
        last_row = rows[-1]
        health = {"verdict": "passed" if last_row["outcome"] == "delivered" else "failed", "at": last_row.get("at"),
                  "why": last_row.get("error") or last_row.get("type"), "by": "relay"}
    delivered = [r for r in rows if r.get("outcome") == "delivered"]
    missing = _unset(sub)
    scope = "this project's own" if sub.get("projects") else "factory-wide"
    return dest(f"channels:relay:{sub['id']}", "channels", "relay",
                f"{SINK_LABEL.get(str(sub.get('sink')), sub.get('sink'))} ({sub['id']})",
                state="planned" if missing else state_of(health, delivered=bool(rows)),
                last={"at": delivered[-1].get("at"), "what": delivered[-1].get("type")} if delivered else None,
                health=health, missing=missing, note=f"{scope} subscription",
                details={"sink": sub.get("sink"), "scope": scope, "personas": sub.get("personas"),
                         "types": sub.get("types"), "deliveries": len(rows)})


def _relay(project: Any, dest: Dest, state_of: Callable[..., str]) -> list[dict[str, Any]]:
    from kernel import relay

    return [_relay_one(project, sub, dest, state_of) for sub in relay.subscriptions(project.factory)
            if not sub.get("projects") or project.pid in sub["projects"]]


def _release_done(project: Any) -> dict | None:
    from kernel.deliver import releases

    done = [r for r in releases(project) if r.get("state") == "done"]
    return done[-1] if done else None


def _faces(project: Any, dest: Dest, action: Callable[..., dict]) -> list[dict[str, Any]]:
    from kernel.faces import pack_runtime

    rel = _release_done(project)
    if rel is None:
        return []
    runtime = pack_runtime(project, rel.get("revision"))
    if not runtime.get("declared"):
        return []
    served: dict[str, list[dict]] = {}
    for rec in project.ledger().of_kind("capability_served"):
        pl = rec["event"]["payload"]
        served.setdefault(str(pl.get("face")), []).append({**pl, "at": rec["event"].get("at")})
    listings = [n for n, c in _registries(project).items() if c.get("kind") == "mcp-registry"]
    return [_face_one(project, face, rel, runtime, served.get(face) or [], listings, dest, action)
            for face in runtime.get("faces") or []]


def _face_one(project: Any, face: str, rel: dict, runtime: dict, rows: list[dict], listings: list[str], dest: Dest,
              action: Callable[..., dict]) -> dict[str, Any]:
    last = rows[-1] if rows else None
    acts = [action("publish", "Write the MCP registry entry", control="destinations_publish", registry=listings[0])
            ] if face == "mcp" and listings else []
    port = "" if face == "mcp" else " --port 0"
    return dest(f"channels:face:{face}", "channels", "face", FACE_LABEL.get(face, face),
                state="delivered" if last else "configured",
                last={"at": last["at"], "release": last.get("release"),
                      "what": f"served over {last.get('transport')} by {last.get('by')}"} if last else None,
                details={"capability": runtime.get("name"), "release": rel["release"],
                         "tools": [t["name"] for t in runtime.get("tools") or []],
                         "consumers": sorted({str(r.get("by")) for r in rows if r.get("by")})},
                actions=acts, note=f"rihmasto capability serve {project.pid} --face {face}{port}")


def channels(project: Any, dest: Dest, action: Callable[..., dict]) -> list[dict[str, Any]]:
    from kernel.destinations import state_of

    return _embeds(project, dest) + _relay(project, dest, state_of) + _faces(project, dest, action)


# -- published ---------------------------------------------------------------------------------------------

def _registries(project: Any) -> dict[str, dict]:
    from kernel import registries

    return registries.load(project.factory)["registries"]


WAITING_NOTE = {"waiting": "waits on IT's deploy gate {card}", "refused by the gate": "IT refused it at the deploy "
                "gate {card}", "written": "{file} is written: submit it yourself"}


def _registry_state(last: dict | None, missing: list[str]) -> tuple[str, dict | None, str | None]:
    """A registry's state, health and note from the last publish to it."""
    if last is None:
        return ("planned" if missing else "configured"), None, None
    if last["state"] == "published":
        digest = last.get("digest")
        health = {"verdict": "passed" if digest else "not measured", "at": last.get("at"), "by": "registry",
                  "why": f"the registry gave {digest}" if digest else "no digest came back"}
        return ("healthy" if digest else "delivered"), health, None
    if last["state"] == "failed":
        return "failing", {"verdict": "failed", "at": last.get("at"), "why": last.get("why"), "by": "publish"}, None
    note = WAITING_NOTE.get(last["state"], last["state"]).format(card=last.get("card"), file=last.get("file"))
    return "configured", None, note


def _registry_row(project: Any, name: str, cfg: dict, hist: list[dict], dest: Dest,
                  action: Callable[..., dict]) -> dict[str, Any]:
    from kernel import registries

    missing = registries.missing(name, cfg)
    t = registries.tier(cfg)
    done = [h for h in hist if h.get("state") == "published"]
    state, health, note = _registry_state(hist[-1] if hist else None, missing)
    kind = cfg.get("kind")
    label = {"mcp-registry": "Write the MCP registry entry"}.get(str(kind), f"Publish to {t or 'it'}")
    acts = [] if kind == "package" else [action("publish", label, control="destinations_publish", registry=name,
                                                disabled=missing[0] if missing else None)]
    return dest(f"published:{name}", "published", "registry",
                f"{name} ({registries.LABEL.get(str(kind), kind)})", state=state, environment=t,
                last={"release": done[-1]["release"], "at": done[-1].get("at"), "what": done[-1].get("image")}
                if done else None, health=health, missing=missing, actions=acts, note=note,
                details={k: v for k, v in registries.public(name, cfg).items() if k not in ("missing", "name")})


def _outputs(project: Any, dest: Dest) -> list[dict[str, Any]]:
    from kernel.outputs import TARGETS

    built: dict[str, dict] = {}
    for rec in project.ledger().of_kind("output_built"):
        pl = rec["event"]["payload"]
        if pl.get("state") == "built":
            built[str(pl.get("target"))] = {**pl, "at": rec["event"].get("at")}
    return [dest(f"published:output:{t}", "published", "output", (TARGETS.get(t) or {}).get("label", t),
                 state="delivered", last={"release": b.get("release"), "at": b.get("at"),
                                          "what": f"{b.get('file')}, built by {b.get('by')}"},
                 details={"file": b.get("file"), "sha256": b.get("sha256"),
                          "audience": (TARGETS.get(t) or {}).get("audience")})
            for t, b in sorted(built.items())]


def published(project: Any, dest: Dest, action: Callable[..., dict]) -> list[dict[str, Any]]:
    from kernel.publish import history

    hist = history(project)
    rows = [_registry_row(project, n, c, [h for h in hist if h.get("registry") == n], dest, action)
            for n, c in sorted(_registries(project).items())]
    return rows + _outputs(project, dest)
