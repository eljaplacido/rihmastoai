"""Connectors: how a system is reached through Gnomon, and who turns one on (D-0015).

A connector is a folder, `connectors/<system>/`:

- `connector.json` (schema `rihma.connector/1`): the pinned MCP server Gnomon runs for it (stdio, a
  command and a pin), the sha256 of that server's tools/list, the read tools and what each maps to,
  the write tools and who decides each, the tools never allowed, the data classes it reads, the
  credentials it needs (references only: `env:`, `os:` or `cmd:`) and the namespace of its refs;
- `mapping.py`: pure functions from what a read tool returned to a proposal (a signal, a change, an
  observation or a note), its text quoted as untrusted data (`quote`);
- `fixtures/`: the pinned tools/list, a rug-pull tools/list, and injection samples;
- optionally a narrow `server.py`, and a README for its setup.

`validate` checks a connector.json and names every violation by its JSON path. No read or write tool
may decide, merge, approve, delete, deploy or push; a credential is never a value; a remote (HTTP)
server waits for Gnomon's HTTP client. One contract test suite runs over every connector folder
(tests/test_connectors_contract.py).

**Turning one on.** IT enables a connector (`rihmasto connector enable`): its entry goes into the
factory's `projects/_factory/connectors.json`, and a `connector` card, which only IT decides, pins the
sha256 of that entry with the sha256 of the folder's connector.json and of every file in the folder
(its server and mapping too). It may run only while that card was decided `enable`, nothing it pins
has changed, IT has not disabled it since, and a local server is the one `server.pin` pins
(`require_enabled`). Any change stops it: `check` records the stop, withdraws a card left open, and
opens a new card that pins the new hashes. An entry written by hand gets its card the same way.

Calling the server is Gnomon's: it runs the pinned server in an integration lane, checks each call
against policy and pins the tools/list itself. What Gnomon must add for that is listed in
docs/integrations.md; until then a connector is modelled, validated and decided, and nothing calls it.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from kernel.canon import Canon, DecisionRefused
from kernel.events import clean_text
from kernel.learn import factory_project
from kernel.ledger import canonical_json
from kernel.people import PERSONAS, is_person
from kernel.store import REPO_ROOT, Factory, Project, updating_json

CONNECTOR_SCHEMA = "rihma.connector/1"
ENTRIES_SCHEMA = "rihma.connectors/1"
DEFAULT_ROOT = REPO_ROOT / "connectors"
DATA_CLASSES = ("public", "internal", "confidential", "restricted")
MAPS_TO = ("signal", "change", "observation", "note")
NEVER = ("approve", "decide", "delete", "deploy", "merge", "push")
REQUIRED = ("schema", "system", "title", "server", "tools_sha256", "read_tools", "write_tools", "forbidden_tools",
            "data_classes", "credentials", "namespace")
OPTIONAL = ("setup", "notes")
PROPOSAL_KEYS = ("kind", "text", "ref", "channel", "project")
UNTRUSTED = "[untrusted text from "

SYSTEM = re.compile(r"[a-z0-9][a-z0-9-]{1,40}\Z")
NAMESPACE = re.compile(r"[a-z][a-z0-9-]{1,20}\Z")
TOOL = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{1,63}\Z")
CREDENTIAL_REF = re.compile(r"(?:env|os):[A-Z][A-Z0-9_]{1,63}\Z|cmd:\S.{0,200}\Z")
# The shapes of well-known live tokens: a connector.json names credentials, it never holds one.
SECRETISH = re.compile(r"(?:gh[pousr]_|github_pat_|sk-|xox[abposr]-|whsec_|AKIA)[A-Za-z0-9_-]{8,}")


class ConnectorInvalid(ValueError):
    """A connector.json that breaks the schema; ``violations`` names each break by its path."""

    def __init__(self, system: str, violations: list[dict[str, str]]) -> None:
        super().__init__(f"connector {system} is not valid: " + "; ".join(
            f"{v['path'] or '/'}: expected {v['expected']}, got {v['got']}" for v in violations[:5]))
        self.violations = violations


class ConnectorStopped(ValueError):
    """A connector that may not run: off, waiting for IT, declined, or changed since IT decided."""


class ToolsChanged(ValueError):
    """A server whose tools/list is not the one pinned (a rug pull): nothing may be called."""

    def __init__(self, system: str, pinned: str, seen: str) -> None:
        super().__init__(f"connector {system}: the tools/list changed (pinned {pinned[:12]}, now {seen[:12]}); "
                         "nothing is called until it is reviewed and pinned again")
        self.pinned, self.seen = pinned, seen


# -- the schema ------------------------------------------------------------------------------------

class _Report:
    def __init__(self) -> None:
        self.violations: list[dict[str, str]] = []

    def fail(self, path: str, expected: str, got: object) -> None:
        self.violations.append({"path": path, "expected": expected, "got": repr(got)[:120]})


def _words(name: str) -> set[str]:
    """A tool name's words: `mergePullRequest` and `merge_pull_request` both hold `merge`."""
    return set(re.split(r"[^a-z0-9]+", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()))


def _check_keys(doc: dict[str, Any], rep: _Report) -> None:
    for key in REQUIRED:
        if key not in doc:
            rep.fail(f"/{key}", "a required key", "missing")
    for key in sorted(set(doc) - set(REQUIRED) - set(OPTIONAL)):
        rep.fail(f"/{key}", "no unknown keys", key)
    if doc.get("schema") != CONNECTOR_SCHEMA:
        rep.fail("/schema", CONNECTOR_SCHEMA, doc.get("schema"))


def _check_top(doc: dict[str, Any], folder: str | None, rep: _Report) -> None:
    _check_keys(doc, rep)
    system = doc.get("system")
    if not isinstance(system, str) or not SYSTEM.match(system):
        rep.fail("/system", "lower-case letters, digits and hyphens", system)
    elif folder is not None and system != folder:
        rep.fail("/system", f"the folder's name, {folder}", system)
    if not isinstance(doc.get("namespace"), str) or not NAMESPACE.match(doc["namespace"]):
        rep.fail("/namespace", "a short lower-case namespace for refs, such as jira", doc.get("namespace"))
    if not isinstance(doc.get("title"), str) or not doc["title"].strip():
        rep.fail("/title", "a title", doc.get("title"))
    if not isinstance(doc.get("tools_sha256"), str) or not HEX64.match(doc["tools_sha256"]):
        rep.fail("/tools_sha256", "the sha256 of the server's tools/list (64 hex digits)", doc.get("tools_sha256"))
    classes = doc.get("data_classes")
    if not isinstance(classes, list) or not classes or not set(map(str, classes)) <= set(DATA_CLASSES):
        rep.fail("/data_classes", f"one or more of {DATA_CLASSES}", classes)


def _check_server(server: Any, rep: _Report) -> None:
    if not isinstance(server, dict):
        rep.fail("/server", "an object: transport, command and pin", server)
        return
    if server.get("transport") != "stdio":
        rep.fail("/server/transport", "stdio (a remote server waits for Gnomon's HTTP client)", server.get("transport"))
    command = server.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(c, str) and c for c in command):
        rep.fail("/server/command", "the command Gnomon starts, as a list of strings", command)
    pin = server.get("pin")
    if not isinstance(pin, dict) or not isinstance(pin.get("version"), str) or not pin["version"].strip():
        rep.fail("/server/pin", "the pinned server: a version, and a sha256 for a local server", pin)
    elif "sha256" in pin and not (isinstance(pin["sha256"], str) and HEX64.match(pin["sha256"])):
        rep.fail("/server/pin/sha256", "64 hex digits", pin["sha256"])


def _check_tool(key: str, item: Any, path: str, rep: _Report) -> None:
    if key == "read_tools" and item.get("maps_to") not in MAPS_TO:
        rep.fail(f"{path}/maps_to", f"one of {MAPS_TO}", item.get("maps_to"))
    if key == "write_tools":
        deciders = item.get("deciders")
        if not isinstance(deciders, list) or not deciders or not set(deciders) <= set(PERSONAS):
            rep.fail(f"{path}/deciders", f"the personas who decide this write, from {PERSONAS}", deciders)
        if not isinstance(item.get("args_template"), dict):
            rep.fail(f"{path}/args_template", "the argument template a decided write must match", None)
    for extra in ("example_args", "args_template"):
        if extra in item and not isinstance(item[extra], dict):
            rep.fail(f"{path}/{extra}", "an object", item[extra])


def _check_tools(doc: dict[str, Any], rep: _Report) -> None:
    seen: dict[str, str] = {}
    for key in ("read_tools", "write_tools", "forbidden_tools"):
        items = doc.get(key)
        if not isinstance(items, list):
            rep.fail(f"/{key}", "a list", items)
            continue
        for i, item in enumerate(items):
            entry = item if isinstance(item, dict) else {"name": item}
            path = f"/{key}/{i}"
            name = entry.get("name")
            if key != "forbidden_tools" and not isinstance(item, dict):
                rep.fail(path, "an object with a name", item)
            elif not isinstance(name, str) or not TOOL.match(name):
                rep.fail(path, "a tool name", name)
            elif name in seen:
                rep.fail(path, "a tool named once", f"{name}, also in {seen[name]}")
            else:
                seen[name] = key
                if key != "forbidden_tools" and _words(name) & set(NEVER):
                    rep.fail(path, f"no tool that does any of {NEVER}: list it under forbidden_tools", name)
                if key != "forbidden_tools":
                    _check_tool(key, entry, path, rep)


def _check_credentials(creds: Any, rep: _Report) -> None:
    if not isinstance(creds, list):
        rep.fail("/credentials", "a list of references", creds)
        return
    for i, c in enumerate(creds):
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or not ENV_NAME.match(c["name"]):
            rep.fail(f"/credentials/{i}/name", "the credential's name, A_NAME_LIKE_THIS", c)
        elif not isinstance(c.get("ref"), str) or not CREDENTIAL_REF.match(c["ref"]):
            rep.fail(f"/credentials/{i}/ref", "a reference, env:NAME, os:NAME or cmd:<command>, never a value",
                     "a value")


def _check_secrets(value: Any, path: str, rep: _Report) -> None:
    if isinstance(value, str) and SECRETISH.search(value):
        rep.fail(path, "no secret: name a credential by reference", "a secret-looking value")
    elif isinstance(value, dict):
        for k, v in value.items():
            _check_secrets(v, f"{path}/{k}", rep)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _check_secrets(v, f"{path}/{i}", rep)


def validate(doc: Any, folder: str | None = None) -> list[dict[str, str]]:
    """Every way a connector.json breaks the schema, each with its JSON path; empty when it holds."""
    rep = _Report()
    if not isinstance(doc, dict):
        rep.fail("", "a JSON object", type(doc).__name__)
        return rep.violations
    _check_top(doc, folder, rep)
    _check_server(doc.get("server"), rep)
    _check_tools(doc, rep)
    _check_credentials(doc.get("credentials"), rep)
    _check_secrets(doc, "", rep)
    return rep.violations


# -- reading a folder ------------------------------------------------------------------------------

def folder_of(root: str | Path, system: str) -> Path:
    if not SYSTEM.match(system):
        raise ValueError("a connector's system is lower-case letters, digits and hyphens")
    return Path(root) / system


def discover(root: str | Path = DEFAULT_ROOT) -> list[str]:
    """Every connector folder under ``root``: each holds a connector.json."""
    base = Path(root)
    return sorted(p.parent.name for p in base.glob("*/connector.json")) if base.is_dir() else []


def file_sha256(path: Path) -> str:
    """A file's sha256, its line endings read as LF, so a checkout on any machine hashes the same."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def folder_sha256(root: str | Path, system: str) -> str:
    """The sha256 of every file in a connector's folder (its connector.json, server, mapping and
    fixtures), each by its path and its own sha256: a change to any of them changes it. Python's
    byte-code caches are left out."""
    folder = folder_of(root, system)
    files = {p.relative_to(folder).as_posix(): file_sha256(p) for p in sorted(folder.rglob("*"))
             if p.is_file() and "__pycache__" not in p.relative_to(folder).parts and p.suffix != ".pyc"}
    return hashlib.sha256(canonical_json(files).encode("utf-8")).hexdigest() if files else "missing"


def check_files(folder: Path, doc: dict[str, Any]) -> list[dict[str, str]]:
    """A server in the folder, named by the command, must be the one `server.pin.sha256` pins."""
    base = folder.resolve()
    local = [c for c in doc["server"]["command"] if (base / c).is_file() and base in (base / c).resolve().parents]
    pinned = doc["server"]["pin"].get("sha256")
    if not local:
        return [] if pinned is None else [{"path": "/server/pin/sha256", "got": "no file",
                                           "expected": "a server file in the folder, named by the command"}]
    seen = file_sha256(base / local[0])
    if seen != pinned:
        return [{"path": "/server/pin/sha256", "expected": f"the sha256 of {local[0]}, {seen}", "got": repr(pinned)}]
    return []


def load(root: str | Path, system: str) -> dict[str, Any]:
    """A connector's connector.json, validated, with its local server checked against its pin;
    ConnectorInvalid names what breaks."""
    path = folder_of(root, system) / "connector.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise ConnectorInvalid(system, [{"path": "", "expected": "JSON", "got": "not JSON"}]) from None
    violations = validate(doc, system) or check_files(path.parent, doc)
    if violations:
        raise ConnectorInvalid(system, violations)
    result: dict[str, Any] = doc
    return result


def tools_sha256(tools: list[Any]) -> str:
    """The sha256 of a tools/list result: each tool's name, description and input schema, by name."""
    rows = sorted(({"name": t.get("name"), "description": t.get("description", ""),
                    "inputSchema": t.get("inputSchema", {})} for t in tools if isinstance(t, dict)),
                  key=lambda t: str(t["name"]))
    return hashlib.sha256(canonical_json(rows).encode("utf-8")).hexdigest()


def check_tools(doc: dict[str, Any], tools: list[Any]) -> str:
    """The tools/list's hash when it is the pinned one; ToolsChanged (a rug pull) otherwise."""
    seen = tools_sha256(tools)
    if seen != doc["tools_sha256"]:
        raise ToolsChanged(doc["system"], doc["tools_sha256"], seen)
    return seen


def quote(text: object, *, ref: str, limit: int = 2000) -> str:
    """Untrusted text as data: cleaned (no HTML, no hidden characters), on one line, with its source."""
    return f"{UNTRUSTED}{ref}] {clean_text(text, limit, one_line=True)}"


def check_proposal(doc: dict[str, Any], proposal: Any) -> list[str]:
    """What is wrong with a mapping's proposal: its kind, keys, ref namespace and quoted text."""
    if not isinstance(proposal, dict):
        return ["a proposal is a JSON object"]
    problems = [f"unknown key {k!r}" for k in sorted(set(proposal) - set(PROPOSAL_KEYS))]
    if proposal.get("kind") not in MAPS_TO:
        problems.append(f"the kind is one of {MAPS_TO}")
    if not str(proposal.get("ref", "")).startswith(f"{doc['namespace']}:"):
        problems.append(f"the ref is in the namespace {doc['namespace']}:")
    text = proposal.get("text")
    if not isinstance(text, str) or not text.startswith(UNTRUSTED):
        problems.append("the text is quoted as untrusted data (connectors.quote)")
    elif clean_text(text, len(text) + 1, one_line=True) != text:
        problems.append("the text holds HTML or hidden characters")
    return problems


# -- turning one on: the entry and the connector card ----------------------------------------------

def _fp(factory: Factory) -> Project:
    """The factory's own project, made on first use: it holds the entries and the connector cards."""
    return factory_project(factory)


def _fp_if_any(factory: Factory) -> Project | None:
    """The factory's own project when it exists; a read never makes it."""
    return factory_project(factory, False)


def _it_signs(person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: enabling a connector is signed by a named person")
    if persona != "it":
        raise DecisionRefused(f"a {persona} may not enable or disable a connector: IT does")


def entries(factory: Factory) -> list[dict[str, Any]]:
    """The connectors IT enabled, from `projects/_factory/connectors.json`."""
    fp = _fp_if_any(factory)
    return list((fp.read("connectors.json", {}) or {}).get("connectors", [])) if fp else []


def connector_sha256(root: str | Path, system: str) -> str:
    path = folder_of(root, system) / "connector.json"
    return file_sha256(path) if path.is_file() else "missing"


def pin_of(entry: dict[str, Any], connector_sha: str, folder_sha: str) -> str:
    """What a connector card pins: the sha256 of its entry with its connector.json's sha256 and the
    sha256 of every file in its folder (folder_sha256), so the code that would run is the code decided."""
    pinned = {"connector_sha256": connector_sha, "entry": entry, "folder_sha256": folder_sha}
    return hashlib.sha256(canonical_json(pinned).encode()).hexdigest()


def _disabled(factory: Factory, card_id: str) -> bool:
    """Whether IT turned the connector off after this card: its decision no longer counts, even when
    the entry is written back by hand."""
    fp = _fp_if_any(factory)
    return fp is not None and any(r["event"]["payload"].get("card") == card_id
                                  for r in fp.ledger().of_kind("connector_disabled"))


def latest_card(factory: Factory, system: str) -> dict[str, Any] | None:
    fp = _fp_if_any(factory)
    cards = [c for c in Canon(fp).cards(state=None, kind="connector") if c["payload"].get("system") == system] \
        if fp else []
    return max(cards, key=lambda c: int(c["id"].split("-")[1]), default=None)


def _open_card(factory: Factory, entry: dict[str, Any], root: str | Path, *, reason: str,
               supersedes: str | None = None) -> dict[str, Any]:
    system = entry["system"]
    sha, files = connector_sha256(root, system), folder_sha256(root, system)
    violations: list[dict[str, str]] = []
    try:
        doc = load(root, system)
    except ConnectorInvalid as exc:
        doc, violations = {}, exc.violations
    except FileNotFoundError:
        doc, violations = {}, [{"path": "", "expected": "a connector.json", "got": "missing"}]
    reads = ", ".join(t["name"] for t in doc.get("read_tools", [])) or "nothing"
    names = ", ".join(c["name"] for c in doc.get("credentials", [])) or "none"
    body = "\n".join([f"Reason: {reason}.", f"Reads: {reads}.",
                      f"Data classes: {', '.join(doc.get('data_classes', [])) or 'unknown'}.",
                      f"Credentials (names only): {names}.",
                      f"Pinned: this entry and every file of its folder (sha256 {files[:12]}).",
                      *(f"Not valid: {v['path'] or '/'} expected {v['expected']}" for v in violations)])
    fp = _fp(factory)
    return Canon(fp).card("connector", f"Turn on the {doc.get('title') or system} connector?", body=body,
                          refs={"connector": system},
                          payload={"system": system, "pin": pin_of(entry, sha, files), "connector_sha256": sha,
                                   "folder_sha256": files, "entry": entry, "violations": violations,
                                   "supersedes": supersedes})


def enable(factory: Factory, system: str, *, person: str, persona: str,
           root: str | Path = DEFAULT_ROOT) -> dict[str, Any]:
    """IT enables a connector: its entry is written and a connector card pins it, for IT to decide."""
    _it_signs(person, persona)
    doc = load(root, system)
    entry = {"system": system, "folder": str(folder_of(root, system).resolve()), "lane": f"integration-{system}",
             "namespace": doc["namespace"], "data_classes": doc["data_classes"],
             "read_tools": [t["name"] for t in doc["read_tools"]], "writes": False,
             "enabled_by": person, "at": factory.clock.stamp()}
    fp = _fp(factory)
    old = latest_card(factory, system)
    with updating_json(fp.path("connectors.json"), {"schema": ENTRIES_SCHEMA, "connectors": []}) as data:
        data["connectors"] = [e for e in data["connectors"] if e["system"] != system] + [entry]
    if old is not None and old["state"] == "open":
        Canon(fp).close(old["id"], "superseded: the connector was enabled again")
    card = _open_card(factory, entry, root, reason=f"enabled by {person}", supersedes=old["id"] if old else None)
    fp.log("connector_enabled", {"system": system, "card": card["id"], "by": person, "persona": persona})
    return card


def disable(factory: Factory, system: str, *, person: str, persona: str) -> dict[str, Any]:
    """IT turns a connector off: its entry is removed and an open card withdrawn."""
    _it_signs(person, persona)
    fp = _fp_if_any(factory)
    if fp is None or not any(e["system"] == system for e in entries(factory)):
        raise KeyError(f"no enabled connector {system!r}")
    with updating_json(fp.path("connectors.json"), {"schema": ENTRIES_SCHEMA, "connectors": []}) as data:
        data["connectors"] = [e for e in data["connectors"] if e["system"] != system]
    card = latest_card(factory, system)
    if card is not None and card["state"] == "open":
        Canon(fp).close(card["id"], "the connector was disabled")
    # The card is named: its decision no longer counts, so an entry written back by hand stays stopped.
    fp.log("connector_disabled", {"system": system, "card": card["id"] if card else None, "by": person,
                                  "persona": persona})
    return {"system": system, "state": "off"}


def state_of(factory: Factory, system: str, *, root: str | Path = DEFAULT_ROOT) -> dict[str, Any]:
    """Whether a connector may run: off, waiting (for IT), enabled, declined, or stopped (changed)."""
    entry = next((e for e in entries(factory) if e["system"] == system), None)
    if entry is None:
        return {"system": system, "state": "off"}
    pin = pin_of(entry, connector_sha256(root, system), folder_sha256(root, system))
    card = latest_card(factory, system)
    out = {"system": system, "pin": pin, "card": card["id"] if card else None}
    if card is None:
        return out | {"state": "stopped", "reason": "it has no connector card yet", "pinned": None}
    if card["payload"].get("pin") != pin or _disabled(factory, card["id"]):
        why = "it changed since its card was opened" if card["payload"].get("pin") != pin else \
            "IT disabled it after its card: only a new card can turn it on"
        return out | {"state": "stopped", "reason": why, "pinned": card["payload"].get("pin")}
    if card["state"] == "open":
        return out | {"state": "waiting", "reason": "its connector card waits for IT"}
    decision = card.get("decision") or {}
    if card["state"] != "decided":
        return out | {"state": "stopped", "reason": f"its card was {card['state']}"}
    return out | {"state": "enabled" if decision.get("verdict") == "enable" else "declined",
                  "decided_by": decision.get("person")}


def status(factory: Factory, *, root: str | Path = DEFAULT_ROOT) -> list[dict[str, Any]]:
    """Every connector folder and every entry, with its state."""
    systems = sorted(set(discover(root)) | {e["system"] for e in entries(factory)})
    return [state_of(factory, s, root=root) for s in systems]


def check(factory: Factory, *, root: str | Path = DEFAULT_ROOT) -> list[dict[str, Any]]:
    """Stop every connector whose entry or connector.json changed since its card: record the stop,
    withdraw a card left open, and open a new card that pins what is there now."""
    out = []
    for entry in entries(factory):
        state = state_of(factory, entry["system"], root=root)
        if state["state"] != "stopped":
            continue
        fp = _fp(factory)
        old = latest_card(factory, entry["system"])
        if old is not None and old["state"] == "open":
            Canon(fp).close(old["id"], "superseded: the connector changed")
        card = _open_card(factory, entry, root, reason=state["reason"], supersedes=old["id"] if old else None)
        fp.log("connector_stopped", {"system": entry["system"], "card": old["id"] if old else None,
                                     "reopened": card["id"], "pinned": state.get("pinned"), "now": state["pin"]})
        out.append({"system": entry["system"], "state": "stopped", "reopened": card["id"], "reason": state["reason"]})
    return out


def require_enabled(factory: Factory, system: str, *, root: str | Path = DEFAULT_ROOT) -> dict[str, Any]:
    """The connector's connector.json when it may run. Checked before any call: ConnectorStopped when it
    may not, and ConnectorInvalid when IT enabled a connector.json that breaks the schema."""
    state = state_of(factory, system, root=root)
    if state["state"] != "enabled":
        raise ConnectorStopped(f"connector {system} may not run: it is {state['state']}"
                               + (f" ({state['reason']})" if state.get("reason") else ""))
    return load(root, system)
