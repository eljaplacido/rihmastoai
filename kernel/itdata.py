"""Integrations and data, as IT sees them (FR-ITD1): every connection the platform has, read from what exists.

The owner (2026-11-25): "from IT perspective, you would want to view for integrations and the data side of things
as well". This module reads, never writes. Each connection is one **item** with the same shape everywhere (the
platform's page, a project's view, Ask Rihma's answers and the data-flow diagram read it alike):

- ``kind``: model (an endpoint a Rihma role sends its prompts to), relay (a Teams, Slack, email or webhook channel
  the relay sends events to), hook (an inbound webhook source), connector (a system Gnomon reaches for Rihmasto),
  registry (where release images go), road (where a product runs), chat (a website chat) and integration (a data
  system a product declares, kernel/integration_decl.py; kernel/itdata_project.py reads those);
- ``direction``: ``in`` (data comes in), ``out`` (data goes out) or ``both``;
- ``locality``: ``this machine``, ``your network`` (a private address, the rule confidential work uses,
  kernel/confidential.py), ``outside`` or ``not known`` (an address in a variable that is not set here);
- ``credentials``: each by NAME with where it lives (an environment variable, the stored key file, Gnomon's key
  store, the computer's keychain, a command, a vault) and whether it is set here. A value is never read or shown;
- ``missing``: what stands between it and working, each a sentence that says what to do;
- ``health``: the last check (kernel/itdata_actions.py: when, passed or failed, how long it took, failures in a
  row), and ``state``: on, off, waiting, failing or not set up.
"""

from __future__ import annotations

import os
import re
import shutil
import urllib.parse
from pathlib import Path
from typing import Any

from kernel.store import read_json

STATE_DIR = "itdata"
LOCAL, NETWORK, OUTSIDE, UNKNOWN = "this machine", "your network", "outside", "not known"
LOCALITIES = (LOCAL, NETWORK, OUTSIDE, UNKNOWN)
LEAVES = (OUTSIDE, UNKNOWN)                 # data sent there may leave the machine and the owner's network
STATES = ("on", "off", "waiting", "failing", "not set up")
KIND_LABEL = {"model": "Model endpoints", "relay": "Relay channels", "hook": "Inbound webhooks",
              "connector": "Connectors", "registry": "Registries", "road": "Where it runs", "chat": "Website chats",
              "integration": "Data integrations"}
KINDS = tuple(KIND_LABEL)
LOOPBACK = ("127.0.0.1", "localhost", "::1")
SINK_LABEL = {"teams": "Teams notices", "slack": "Slack notices", "email": "Email notices",
              "webhook": "Signed webhook events"}
ROAD_OUTSIDE = ("azure-containerapps", "gcp-cloudrun")
_ENV = re.compile(r"[A-Z_][A-Z0-9_]{0,80}\Z")


# -- locality and credentials -----------------------------------------------------------------------------

def host_of(url: str | None) -> str | None:
    text = str(url or "").strip()
    if not text:
        return None
    return urllib.parse.urlsplit(text if "://" in text else "//" + text).hostname or None


def port_of(url: str | None) -> int | None:
    parts = urllib.parse.urlsplit(str(url or ""))
    try:
        return parts.port or {"https": 443, "http": 80, "postgres": 5432, "mysql": 3306}.get(parts.scheme)
    except ValueError:
        return None


def locality(url: str | None, endpoint: dict[str, Any] | None = None) -> str:
    """Where an address is: this machine, the owner's own network, outside, or not known (no address)."""
    from kernel.confidential import is_local

    host = host_of(url)
    if not host and not (endpoint or {}).get("private"):
        return UNKNOWN
    if host in LOOPBACK or str(host or "").endswith(".localhost"):
        return LOCAL
    return NETWORK if is_local(url, endpoint) else OUTSIDE


def env_credential(name: str | None) -> dict[str, Any] | None:
    """A credential held in an environment variable: its name, and whether it is set here (never its value)."""
    if not name:
        return None
    return {"name": name, "where": "environment variable", "set": bool(os.environ.get(name))}


def ref_credential(name: str, ref: str) -> dict[str, Any]:
    """A credential a road binding or a connector refers to (``env:``, ``os:``, ``cmd:`` or a vault URL)."""
    text = str(ref or "")
    if text.startswith("env:"):
        var = text[4:]
        return {"name": name, "where": "environment variable " + var, "set": bool(os.environ.get(var))}
    if text.startswith("os:"):
        return {"name": name, "where": "the computer's keychain", "set": None}
    if text.startswith("cmd:"):
        return {"name": name, "where": "a command's output", "set": None}
    if text.startswith(("https://", "vault:")):
        return {"name": name, "where": "a vault at " + (host_of(text) or "its address"), "set": None}
    return {"name": name, "where": "not named yet", "set": False}


def key_credential(name: str | None) -> dict[str, Any] | None:
    """A model endpoint's key: set in the environment, in the stored key file, maybe in Gnomon's key store."""
    if not name:
        return None
    if os.environ.get(name):
        return {"name": name, "where": "environment variable", "set": True}
    from kernel import models_setup
    from kernel.gnomon_keys import kind_of

    try:
        if name in models_setup.stored_keys():
            return {"name": name, "where": "the stored key file (outside the repository)", "set": True}
    except (OSError, ValueError):
        pass
    if kind_of(name, None) == "gnomon_maybe":
        return {"name": name, "where": "Gnomon's key store, maybe (`gnomon key list` names it)", "set": None}
    return {"name": name, "where": "environment variable", "set": False}


def unset(creds: list[dict[str, Any]]) -> list[str]:
    return [f"{c['name']} is not set where Rihmasto runs: set it there ({c['where']}), then check again"
            for c in creds if c.get("set") is False]


# -- one item ---------------------------------------------------------------------------------------------

def item(iid: str, kind: str, label: str, *, direction: str, where: str, **more: Any) -> dict[str, Any]:
    """One connection, as every view, answer and the diagram reads it."""
    creds = [c for c in more.pop("credentials", []) or [] if c]
    out = {"id": iid, "kind": kind, "label": label, "direction": direction, "locality": where,
           "host": more.pop("host", None), "data_classes": list(more.pop("data_classes", []) or []),
           "credentials": creds, "missing": list(more.pop("missing", []) or []) + unset(creds),
           "projects": list(more.pop("projects", []) or []), "scope": more.pop("scope", "platform"),
           "disable": more.pop("disable", None), "open": more.pop("open", None), "health": None,
           "native": more.pop("native", None)}
    out.update(more)
    return out


def leaves(it: dict[str, Any]) -> bool:
    """Whether data sent to this connection may leave the machine and the owner's own network."""
    return it["direction"] in ("out", "both") and it["locality"] in LEAVES and not it.get("refused")


# -- the platform's connections ------------------------------------------------------------------------------

ROLE_ROLES = ("analyst", "holdout_author", "builder", "verifier", "assistant")


def _model_endpoints() -> dict[str, dict[str, Any]]:
    """Each endpoint a role uses, with the roles (and whether as their fallback)."""
    from kernel.confidential import routes
    from kernel.lanes import read_routing

    routing = read_routing() or {}
    found: dict[str, dict[str, Any]] = {}
    for r in routes(ROLE_ROLES, routing):
        ep = (routing.get("endpoints") or {}).get(r["endpoint"]) or {}
        row = found.setdefault(r["endpoint"], {"endpoint": ep, "url": r["url"], "local": r["local"], "roles": []})
        row["roles"].append(r["role"] + (" (fallback)" if r["which"] == "fallback" else ""))
    return found


def role_words(roles: list[str]) -> str:
    """"analyst, holdout author (as a fallback), builder": each role once, in words."""
    mains = {r for r in roles if not r.endswith("(fallback)")}
    names = dict.fromkeys(r.split(" ")[0] for r in roles)
    return ", ".join(n.replace("_", " ") + ("" if n in mains else " (as a fallback)") for n in names)


def _model_item(name: str, row: dict[str, Any]) -> dict[str, Any]:
    ep, url = row["endpoint"], row["url"]
    harness = ep.get("kind") == "harness"
    where = OUTSIDE if harness else locality(url, ep)
    if where == OUTSIDE and row["local"]:
        where = NETWORK                            # declared private by its owner in the routing overlay
    missing = []
    if harness and shutil.which(str(ep.get("harness") or "")) is None and not ep.get("command"):
        missing.append(f"the coding agent {ep.get('harness')} is not on PATH here: install it, or choose another "
                       "model in Models setup")
    label = f"Coding agent {ep.get('harness')}" if harness else f"{name} ({host_of(url) or 'no address'})"
    return item(f"model:{name}", "model", label, direction="out", where=where, host=None if harness else host_of(url),
                credentials=[key_credential(ep.get("api_key_env"))], missing=missing, roles=row["roles"],
                data_classes=["the project's records, in prompts"], open="#/models",
                probe=None if harness else probe_of(url),
                note=("it sends the prompts to its own provider" if harness else
                      f"{ep.get('kind') or 'openai'} endpoint for the " + role_words(row["roles"])),
                disable={"why_not": "a model endpoint is changed in Models setup: choose another model for its roles "
                                    "there (Settings > Models), or ask Rihma to set a model"})


def demo_home(factory: Any) -> bool:
    """A demo home (kernel/demo.py) runs on its scripted model, contacts no outside host and has no lanes of its own."""
    return factory is not None and (Path(factory.home) / "demo.json").is_file()


def models(factory: Any = None) -> list[dict[str, Any]]:
    if demo_home(factory):         # the demo's scripted model, never the checkout's shipped routing
        return [item("model:demo-model", "model", "demo-model (scripted, on this machine)", direction="out",
                     where=LOCAL, host=None, credentials=[], missing=[], roles=list(ROLE_ROLES),
                     data_classes=["the demo's records, in prompts"], open="#/models", probe=None,
                     note="the demo's scripted answers: nothing leaves this machine",
                     disable={"why_not": "a demo home always runs on its scripted model"})]
    return [_model_item(name, row) for name, row in sorted(_model_endpoints().items())]


def probe_of(url: str | None) -> dict[str, Any] | None:
    host, port = host_of(url), port_of(url)
    return {"host": host, "port": port} if host and port else None


def _relay_target(sub: dict[str, Any]) -> str | None:
    if sub.get("sink") == "email":
        mail = sub.get("mail") or {}
        return f"smtp://{mail.get('host')}:{mail.get('port') or 25}"
    return sub.get("url") or (os.environ.get(str(sub.get("url_env"))) if sub.get("url_env") else None)


def _relay_health(factory: Any, sub_id: str) -> dict[str, Any] | None:
    from kernel import relay

    rows = [r for r in relay.deliveries(factory, subscription=sub_id, limit=0) if r.get("kind") == "delivery"]
    if not rows:
        return None
    failures = 0
    for r in reversed(rows):
        if r.get("outcome") == "delivered":
            break
        failures += 1
    last = rows[-1]
    return {"ok": last.get("outcome") == "delivered", "at": last.get("at"), "failures": failures, "by": "relay",
            "why": last.get("error") or last.get("type"), "latency_ms": None}


def relays(factory: Any, pid: str | None = None) -> list[dict[str, Any]]:
    """The relay's subscriptions: every one on the platform, or those that carry ``pid``'s events."""
    from kernel import relay

    out = []
    for sub in relay.subscriptions(factory):
        if pid and sub.get("projects") and pid not in sub["projects"]:
            continue
        mail = sub.get("mail") or {}
        target = _relay_target(sub)
        creds = [env_credential(n) for n in (sub.get("url_env"), sub.get("secret_env"), mail.get("user_env"),
                                             mail.get("password_env"))]
        out.append(item(f"relay:{sub['id']}", "relay", f"{SINK_LABEL.get(str(sub.get('sink')), sub.get('sink'))} "
                        f"({sub['id']})", direction="out", where=locality(target), host=host_of(target),
                        credentials=creds, projects=sub.get("projects") or [], probe=probe_of(target),
                        data_classes=["events: card titles, decisions, who decided"],
                        native=_relay_health(factory, sub["id"]), open="#/settings",
                        note="this project's own subscription" if sub.get("projects") else "every project's events",
                        disable={"how": "relay"}))
    return out


def hooks_in(factory: Any, pid: str | None = None) -> list[dict[str, Any]]:
    from kernel import hooks
    from kernel.learn import factory_project

    fp = factory_project(factory, False)
    rings: dict[str, str] = {}
    for rec in fp.ledger().of_kind("hook_received") if fp else []:
        rings[str(rec["event"]["payload"].get("source"))] = str(rec["event"].get("at"))
    out = []
    for src in hooks.sources(factory):
        if src.get("state") != "active" or (pid and pid not in (src.get("projects") or [])):
            continue
        at = rings.get(str(src["id"]))
        out.append(item(f"hook:{src['id']}", "hook", f"Webhook source {src['id']}", direction="in", where=OUTSIDE,
                        credentials=[env_credential(src.get("secret_env"))], projects=src.get("projects") or [],
                        native={"ok": True, "at": at, "by": "hooks", "why": "a ring arrived", "failures": 0}
                        if at else None, data_classes=[f"a ring becomes a {src.get('becomes')}"],
                        note=f"{src.get('scheme')} signatures; senders reach /hooks/{src['id']}",
                        disable={"how": "hook"}, open="#/settings"))
    return out


def _connector_doc(system: str) -> dict[str, Any]:
    from kernel import connectors

    try:
        return connectors.load(connectors.DEFAULT_ROOT, system)
    except (OSError, ValueError, KeyError, connectors.ConnectorInvalid):
        return {}


def connectors_in(factory: Any, only: set[str] | None = None) -> list[dict[str, Any]]:
    from kernel import connectors

    out = []
    for st in connectors.status(factory):
        if only is not None and st["system"] not in only:
            continue
        doc = _connector_doc(st["system"])
        creds = [ref_credential(c.get("name", "?"), c.get("ref", "")) for c in doc.get("credentials") or []
                 if isinstance(c, dict)]
        state = {"enabled": "on", "off": "off", "waiting": "waiting"}.get(st["state"], "not set up")
        why = st.get("reason") or "IT decides its card in the Inbox"
        missing = [] if state in ("on", "off") else [f"the connector is {st['state']}: {why}"]
        x = item(f"connector:{st['system']}", "connector", f"{doc.get('title') or st['system']} connector",
                 direction="in", where=LOCAL, data_classes=doc.get("data_classes") or [], credentials=creds,
                 missing=missing, connector_state=state, disable={"how": "connector"} if state != "off" else
                 {"why_not": "it is off already: IT turns it on with rihmasto connector enable"}, open="#/settings",
                 note="read only, through Gnomon's pinned MCP server on this machine")
        if state == "off":
            x["missing"] = []                     # an unused connector's settings wait on nobody
        out.append(x)
    return out


def registries_in(factory: Any, names: set[str] | None = None) -> list[dict[str, Any]]:
    from kernel import registries

    out = []
    for name, cfg in sorted(registries.load(factory)["registries"].items()):
        if names is not None and name not in names:
            continue
        login = registries.login_names(cfg) or ()
        host = registries.host(cfg)
        out.append(item(f"registry:{name}", "registry", f"{name} ({registries.LABEL.get(str(cfg.get('kind')), '')})",
                        direction="out", where=locality(host) if host else OUTSIDE, host=host,
                        credentials=[env_credential(n) for n in login if n],
                        missing=[m for m in registries.missing(name, cfg) if "is not set" not in m],
                        data_classes=["release images"], environment=registries.tier(cfg),
                        disable={"why_not": "a registry is IT's entry in registries.json in the factory home: remove "
                                            "it there"}, open=None))
    return out


def roads_in(factory: Any) -> list[dict[str, Any]]:
    from kernel.roads import PavedRoads

    out = []
    for name, cfg in sorted(PavedRoads.load(factory).roads.items()):
        if not cfg.get("configured"):
            continue
        kind = str(cfg.get("kind"))
        out.append(item(f"road:{name}", "road", f"Paved road {name} ({kind})", direction="out",
                        where=OUTSIDE if kind in ROAD_OUTSIDE else LOCAL, data_classes=["the product and its data"],
                        environments=cfg.get("environments") or [], open="#/settings",
                        disable={"why_not": "a paved road is IT's configuration in Settings > Paved roads"}))
    return out


def chats_in(factory: Any, pid: str | None = None) -> list[dict[str, Any]]:
    from kernel import embeds

    out = []
    for e in embeds.embeds(factory):
        if e.get("state") != "active" or (pid and e.get("project") != pid):
            continue
        out.append(item(f"chat:{e['id']}", "chat", f"Website chat {e.get('label') or e['id']}", direction="both",
                        where=OUTSIDE, projects=[e["project"]] if e.get("project") else [],
                        data_classes=["what visitors type", "the answers"], open="#/settings",
                        note="from " + ", ".join(e.get("origins") or []),
                        disable={"why_not": "a website chat is revoked in Settings > Website chats"}))
    return out


# -- what the checks and the reminders kept ----------------------------------------------------------------

def state_path(factory: Any, name: str) -> Path:
    return Path(factory.home) / STATE_DIR / name


def kept(factory: Any, name: str) -> dict[str, Any]:
    found = read_json(state_path(factory, name), {})
    return found if isinstance(found, dict) else {}


PER_PROJECT = ("integration", "road")      # their ids repeat in every project (road:demo, integration:orders)


def health_key(it: dict[str, Any]) -> str:
    """Where a check's result is kept: a project's own integration or environment by project and id, since every
    project has a road:demo; a connection of the platform by its id alone (one result, whichever view checked it)."""
    if it["kind"] in PER_PROJECT and it.get("scope") == "project" and it["projects"]:
        return f"{it['projects'][0]}|{it['id']}"
    return str(it["id"])


def _newest(mine: dict[str, Any] | None, native: dict[str, Any] | None) -> dict[str, Any] | None:
    """The newest health; a check that measured nothing (ok None) never hides what the item's own probe said."""
    if mine and mine.get("ok") is None and native:
        return native
    return max([h for h in (mine, native) if h], key=lambda h: str(h.get("at") or ""), default=None)


def with_health(factory: Any, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each item with its newest health (the last check here, or the relay's, hooks' or probe's own) and its state."""
    checks = kept(factory, "health.json")
    for it in items:
        it["health"] = _newest(checks.get(health_key(it)), it.pop("native", None))
        it["state"] = state_of(it)
    return items


def state_of(it: dict[str, Any]) -> str:
    if it.get("connector_state") in ("off", "waiting"):
        return str(it["connector_state"])
    if it["health"] is not None and it["health"].get("ok") is False:
        return "failing"
    return "not set up" if it["missing"] else "on"


def credentials(factory: Any, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every credential the connections name, by name only, with what uses it and its rotation reminder."""
    reminders = kept(factory, "rotation.json")
    found: dict[str, dict[str, Any]] = {}
    for it in items:
        for c in it["credentials"] if it.get("state") != "off" else []:
            row = found.setdefault(c["name"], {**c, "used_by": []})
            row["used_by"].append({"id": it["id"], "label": it["label"]})
    today = factory.clock.stamp()[:10]
    for name, row in found.items():
        due = reminders.get(name)
        row["rotation"] = {**due, "overdue": str(due.get("due")) <= today} if isinstance(due, dict) else None
    return sorted(found.values(), key=lambda r: r["name"])


def is_env_name(name: str) -> bool:
    return bool(_ENV.match(str(name or "")))


def _count(items: list[dict[str, Any]], key: str, values: tuple[str, ...]) -> dict[str, int]:
    return {v: sum(1 for it in items if it[key] == v) for v in values}


def _line(n: int, out_of: list[str], failing: list[str], waiting: list[str]) -> str:
    line = f"{n} connection" + ("s" if n != 1 else "")
    line += f"; {len(out_of)} may send data outside this machine and your network" if out_of else \
        "; none sends data outside this machine and your network"
    if failing:
        line += f"; {len(failing)} failing: {', '.join(failing[:3])}"
    if waiting:
        line += f"; {len(waiting)} not set up yet"
    return line + "."


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    """How many connections, where they are, what fails, what may leave the machine: counts and one line."""
    out_of = [it["label"] for it in items if leaves(it)]
    failing = [it["label"] for it in items if it["state"] == "failing"]
    waiting = [it["label"] for it in items if it["state"] in ("not set up", "waiting")]
    return {"total": len(items), "by_locality": _count(items, "locality", LOCALITIES), "leaving": out_of,
            "failing": failing, "waiting": waiting, "by_kind": _count(items, "kind", KINDS),
            "line": _line(len(items), out_of, failing, waiting)}
