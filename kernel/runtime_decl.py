"""The runtime declaration: what a small capability needs where it runs (`rihma.runtime/1`, FR-SC2).

A small capability (an automation, a single workflow, one agentic capability) says in
`app/runtime.json` what it needs at run time: what starts a run (a schedule, a verified webhook, a
relay event, a person), the tools it offers, the model roles and integrations it calls, its secrets by
reference only, and the faces it is reached through (MCP, an OpenAI-compatible chat, a website embed,
HTTP). The factory judges it deterministically, with no model:

- at the gate, through the road's contract tests in the product (`tests/test_road_contract.py`);
- when the capability pack is built (`kernel/faces.py` `pack_runtime`), which carries the result as
  the pack's `runtime`, hashed like everything else the pack declares;
- in the image, where the faces refuse to answer while it is not valid (`factory/faces.py`).

This module is the standard library only and imports nothing from the kernel: the capability template
copies it into every capability product as `factory/runtime_decl.py`, so the factory and the image
judge a declaration with the same code. Every problem names its JSON path.
"""

from __future__ import annotations

import datetime
import fnmatch
import hashlib
import json
import re
from typing import Any

FORMAT = "rihma.runtime/1"
KINDS = ("automation", "workflow", "agent")
TRIGGERS = ("schedule", "webhook", "event", "manual")
FACES = ("mcp", "openai", "http", "embed")
EFFECTS = ("read", "write")
VIA = ("mcp", "api", "webhook", "relay", "database", "file", "queue")
WORKLOAD_CLASSES = ("interactive", "batch", "specialist")
DATA_CLASSES = ("public", "internal", "confidential", "restricted")
JSON_TYPES = ("string", "integer", "number", "boolean", "object", "array")
READS = ("capability_describe", "capability_runs")   # the reads every capability's MCP face offers
# Words no tool of a capability is named for: deciding stays with people in Rihmasto's Inbox.
NEVER = ("approve", "decide", "delete", "deploy", "merge", "push", "grant", "trust")
MAX_EVERY = 7 * 24 * 60     # minutes: a schedule runs at least once a week
MAX_TIMEOUT = 600           # seconds one run may take
KEYS = {"format", "name", "kind", "summary", "trigger", "faces", "tools", "model_roles", "integrations",
        "secrets", "embed", "timeout_seconds", "data_class"}
REQUIRED = ("format", "name", "kind", "summary", "trigger", "faces")

NAME = re.compile(r"[a-z][a-z0-9-]{1,62}[a-z0-9]\Z")
TOOL = re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
ROLE = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
WORKLOAD = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
SOURCE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}\Z")
EVENT_TYPE = re.compile(r"rihma\.[a-z0-9_.*]{1,80}\Z")
SECRET = re.compile(r"[A-Z][A-Z0-9_]{1,63}\Z")
# Where the deployer takes a secret's value from: the deployer's environment, the operating system's
# credential store, or Gnomon's (D-0015). Never the value itself.
SECRET_REF = re.compile(r"(?:env|os|gnomon):[A-Za-z][A-Za-z0-9_./-]{0,127}\Z")
ORIGIN = re.compile(r"(?:https://[a-z0-9.-]+|http://(?:localhost|127\.0\.0\.1))(?::\d{1,5})?\Z")
# The shapes of well-known live tokens: a declaration names secrets, it never holds one. A prefix counts
# only where a word starts, so "desk-assistant" or "risk-assessment" is a name, not a token.
SECRETISH = re.compile(r"(?<![A-Za-z0-9])(?:gh[pousr]_|github_pat_|sk-|xox[abposr]-|whsec_|AKIA)[A-Za-z0-9_-]{8,}")


def _text(value: Any, path: str, limit: int, out: list[str]) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        out.append(f"{path}: expected text of 1 to {limit} characters")


def _items(value: Any, path: str, out: list[str]) -> list[dict]:
    """The objects of a list; a problem for anything that is not a list of objects."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        out.append(f"{path}: expected a list of objects")
        return []
    return value


def _only(obj: dict, path: str, allowed: set[str], out: list[str]) -> None:
    unknown = sorted(set(obj) - allowed)
    if unknown:
        out.append(f"{path}: unknown keys {unknown}")


def _unique(names: list[Any], path: str, out: list[str]) -> None:
    seen: set[Any] = set()
    for i, name in enumerate(names):
        if name in seen:
            out.append(f"{path}/{i}/name: {name!r} is named twice")
        seen.add(name)


def _schedule(trig: dict, secrets: set[str]) -> list[str]:
    every = trig.get("every_minutes")
    if type(every) is not int or not 1 <= every <= MAX_EVERY:
        return [f"/trigger/every_minutes: expected a whole number of minutes from 1 to {MAX_EVERY}"]
    return []


def _signed(trig: dict, secrets: set[str]) -> list[str]:
    """A webhook or a relay event is verified (Standard Webhooks) with a key the declaration names."""
    if trig.get("secret") not in secrets:
        return ["/trigger/secret: expected the name of a secret declared under /secrets: the key that verifies "
                "each delivery (Standard Webhooks)"]
    return []


def _webhook(trig: dict, secrets: set[str]) -> list[str]:
    out = _signed(trig, secrets)
    if "source" in trig and not SOURCE.match(str(trig["source"])):
        out.append("/trigger/source: expected a source id (lower-case letters, digits and hyphens)")
    return out


def _event(trig: dict, secrets: set[str]) -> list[str]:
    out = _signed(trig, secrets)
    types = trig.get("types")
    if not isinstance(types, list) or not types or not all(isinstance(t, str) and EVENT_TYPE.match(t) for t in types):
        out.append("/trigger/types: expected a list of event types or patterns, such as rihma.release.done")
    return out


# Each trigger kind: the keys it takes, and its own check.
_TRIGGER_RULES = {"schedule": ({"kind", "every_minutes"}, _schedule),
                  "webhook": ({"kind", "source", "secret"}, _webhook),
                  "event": ({"kind", "types", "secret"}, _event),
                  "manual": ({"kind"}, lambda trig, secrets: [])}


def _trigger(trig: Any, secrets: set[str], out: list[str]) -> None:
    if not isinstance(trig, dict) or trig.get("kind") not in TRIGGERS:
        out.append(f"/trigger/kind: expected one of {', '.join(TRIGGERS)}")
        return
    allowed, check = _TRIGGER_RULES[trig["kind"]]
    _only(trig, "/trigger", allowed, out)
    out += check(trig, secrets)


def _input(schema: Any, path: str, out: list[str]) -> None:
    """A tool's input: a JSON Schema object of named, typed properties."""
    if schema is None:
        return
    if not isinstance(schema, dict) or schema.get("type") != "object":
        out.append(f"{path}: expected a JSON Schema with type object")
        return
    _only(schema, path, {"type", "properties", "required", "additionalProperties"}, out)
    props = schema.get("properties") or {}
    if not isinstance(props, dict):
        out.append(f"{path}/properties: expected an object")
        return
    for key, prop in props.items():
        if not TOOL.match(str(key)) or not isinstance(prop, dict) or prop.get("type") not in JSON_TYPES:
            out.append(f"{path}/properties/{key}: expected a lower-case name with a type of {', '.join(JSON_TYPES)}")
    required = schema.get("required") or []
    if not isinstance(required, list) or any(r not in props for r in required):
        out.append(f"{path}/required: expected names of declared properties")


def _tools(tools: list[dict], out: list[str]) -> None:
    for i, tool in enumerate(tools):
        path, name = f"/tools/{i}", tool.get("name")
        _only(tool, path, {"name", "description", "effect", "input"}, out)
        if not isinstance(name, str) or not TOOL.match(name) or name in READS:
            out.append(f"{path}/name: expected a lower-case tool name that is not one of the reads {READS}")
        elif set(name.split("_")) & set(NEVER):
            out.append(f"{path}/name: a capability offers no tool that may {', '.join(NEVER)}")
        _text(tool.get("description"), f"{path}/description", 500, out)
        if tool.get("effect") not in EFFECTS:
            out.append(f"{path}/effect: expected read or write")
        _input(tool.get("input"), f"{path}/input", out)
    _unique([t.get("name") for t in tools], "/tools", out)


def _roles(roles: list[dict], out: list[str]) -> None:
    for i, role in enumerate(roles):
        path = f"/model_roles/{i}"
        _only(role, path, {"role", "workload", "class", "data_class", "model"}, out)
        if not ROLE.match(str(role.get("role"))):
            out.append(f"{path}/role: expected a lower-case role name")
        if not WORKLOAD.match(str(role.get("workload"))):
            out.append(f"{path}/workload: expected the gateway workload it calls, a lower-case name")
        if role.get("class") not in WORKLOAD_CLASSES:
            out.append(f"{path}/class: expected one of {', '.join(WORKLOAD_CLASSES)}")
        if role.get("data_class", "internal") not in DATA_CLASSES:
            out.append(f"{path}/data_class: expected one of {', '.join(DATA_CLASSES)}")
        if "model" in role:
            _text(role["model"], f"{path}/model", 120, out)
    _unique([r.get("role") for r in roles], "/model_roles", out)


def _integrations(items: list[dict], secrets: set[str], out: list[str]) -> None:
    for i, item in enumerate(items):
        path = f"/integrations/{i}"
        _only(item, path, {"system", "via", "purpose", "writes", "secrets"}, out)
        if not SOURCE.match(str(item.get("system"))):
            out.append(f"{path}/system: expected a lower-case system id")
        if item.get("via") not in VIA:
            out.append(f"{path}/via: expected one of {', '.join(VIA)}")
        _text(item.get("purpose"), f"{path}/purpose", 300, out)
        if not isinstance(item.get("writes", False), bool):
            out.append(f"{path}/writes: expected true or false")
        named = item.get("secrets") or []
        if not isinstance(named, list) or any(n not in secrets for n in named):
            out.append(f"{path}/secrets: expected names declared under /secrets")


def _secrets(items: list[dict], out: list[str]) -> set[str]:
    for i, item in enumerate(items):
        path = f"/secrets/{i}"
        _only(item, path, {"name", "ref"}, out)
        if not SECRET.match(str(item.get("name"))):
            out.append(f"{path}/name: expected an environment variable's name (A_NAME_LIKE_THIS)")
        if not SECRET_REF.match(str(item.get("ref"))):
            out.append(f"{path}/ref: expected a reference (env:NAME, os:NAME or gnomon:NAME), never a value")
    _unique([s.get("name") for s in items], "/secrets", out)
    return {str(s.get("name")) for s in items}


def _strings(value: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in _strings(v, f"{path}/{k}")]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in _strings(v, f"{path}/{i}")]
    return [(path, value)] if isinstance(value, str) else []


def _embed(decl: dict, faces: list, out: list[str]) -> None:
    embed = decl.get("embed")
    if embed is None:
        if "embed" in faces:
            out.append("/embed/origins: the embed face needs the websites that may use it")
        return
    if not isinstance(embed, dict) or set(embed) != {"origins"}:
        out.append("/embed: expected an object with origins only")
        return
    origins = embed["origins"]
    if not isinstance(origins, list) or not origins or not all(isinstance(o, str) and ORIGIN.match(o) for o in origins):
        out.append("/embed/origins: expected https origins (http only for localhost), at least one")


def _faces(decl: dict, out: list[str]) -> None:
    faces = decl.get("faces")
    if not isinstance(faces, list) or not faces or any(f not in FACES for f in faces) or len(set(faces)) != len(faces):
        out.append(f"/faces: expected a list of distinct faces from {', '.join(FACES)}")
        return
    _embed(decl, faces, out)


def validate(decl: Any) -> list[str]:
    """Every problem with a runtime declaration, each with its JSON path; empty when it is valid."""
    if not isinstance(decl, dict):
        return ["/: expected a JSON object"]
    out: list[str] = [f"/{k}: required" for k in REQUIRED if k not in decl]
    _only(decl, "/", KEYS, out)
    if decl.get("format") != FORMAT:
        out.append(f"/format: expected {FORMAT}")
    if not NAME.match(str(decl.get("name"))):
        out.append("/name: expected a lower-case name of letters, digits and hyphens, 3 to 64 long")
    if decl.get("kind") not in KINDS:
        out.append(f"/kind: expected one of {', '.join(KINDS)}")
    _text(decl.get("summary"), "/summary", 300, out)
    names = _secrets(_items(decl.get("secrets"), "/secrets", out), out)
    _trigger(decl.get("trigger"), names, out)
    _faces(decl, out)
    _tools(_items(decl.get("tools"), "/tools", out), out)
    _roles(_items(decl.get("model_roles"), "/model_roles", out), out)
    _integrations(_items(decl.get("integrations"), "/integrations", out), names, out)
    timeout = decl.get("timeout_seconds", 60)
    if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT:
        out.append(f"/timeout_seconds: expected a whole number of seconds from 1 to {MAX_TIMEOUT}")
    if decl.get("data_class", "internal") not in DATA_CLASSES:
        out.append(f"/data_class: expected one of {', '.join(DATA_CLASSES)}")
    out += [f"{path}: holds what looks like a live token; name the secret under /secrets instead"
            for path, text in _strings(decl) if SECRETISH.search(text)]
    return out


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def for_pack(decl: Any) -> dict:
    """What a capability pack carries of a declaration: `declared` true with what it needs (secrets by name
    only, the gateway workloads its model roles call, and the agent route its OpenAI face offers), or false
    with the problems that keep it from being declared. Deterministic: the same declaration always gives
    the same section."""
    problems = validate(decl)
    if problems:
        return {"declared": False, "note": "app/runtime.json is not a valid runtime declaration", "problems": problems}
    roles = decl.get("model_roles") or []
    out = {"declared": True, "format": FORMAT,
           "declaration_sha256": hashlib.sha256(canonical(decl).encode("utf-8")).hexdigest(),
           "name": decl["name"], "kind": decl["kind"], "summary": decl["summary"], "trigger": decl["trigger"],
           "faces": list(decl["faces"]), "tools": [{"name": t["name"], "effect": t["effect"]}
                                                   for t in decl.get("tools") or []],
           "model_roles": [dict(r) for r in roles],
           "workloads": [{"name": r["workload"], "class": r["class"], "data_class": r.get("data_class", "internal"),
                          "model": r["model"]} for r in roles if r.get("model")],
           "integrations": [{k: i[k] for k in ("system", "via", "writes") if k in i}
                            for i in decl.get("integrations") or []],
           "secrets": sorted(str(s["name"]) for s in decl.get("secrets") or []),
           "data_class": decl.get("data_class", "internal"), "timeout_seconds": decl.get("timeout_seconds", 60)}
    if "openai" in decl["faces"]:   # the agent as a model: a gateway workload named after the capability
        out["agent"] = {"model": decl["name"], "data_class": out["data_class"]}
    return out


def due(trigger: Any, last: datetime.datetime | None, now: datetime.datetime) -> bool:
    """Whether a scheduled run is due: never run before, or its interval has passed since the last run."""
    if not isinstance(trigger, dict) or trigger.get("kind") != "schedule":
        return False
    return last is None or now - last >= datetime.timedelta(minutes=int(trigger.get("every_minutes") or MAX_EVERY))


def matches_event(trigger: Any, event_type: str) -> bool:
    """Whether an event of this type starts a run of a capability with this trigger."""
    if not isinstance(trigger, dict) or trigger.get("kind") != "event":
        return False
    return any(fnmatch.fnmatchcase(event_type, pattern) for pattern in trigger.get("types") or [])
