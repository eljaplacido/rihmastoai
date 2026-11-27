"""Models setup: which model answers for each of Rihmasto's roles, set by a person (FR-MDL1).

docs/guides/models-setup.md is the guide.

The roles are those of the routing (`kernel/routing.json`): the analyst, the holdout author, the builder, the
verifier and the assistant. A person sets a role's endpoint (an OpenAI-compatible base URL), its model and
how its API key is found: the NAME of an environment variable, or a key stored in a secrets file outside the
repository (``~/.rihmasto/secrets.json``, or ``$RIHMASTO_SECRETS_FILE``). Every change is written to this
machine's overlay, `kernel/routing.local.json` (gitignored, merged over the shipped file); the shipped
routing.json is never written. The merged routing is checked as the kernel checks it (FR-G6) before it is kept.

A key is never echoed back, never logged and never put in the ledger: the factory's ledger records who set
which role to which endpoint host, and whether the key comes from the environment, is stored, or is none.
Gnomon reads a key from the variable an endpoint's `api_key_env` names; a stored key is handed to Gnomon's
process in that variable (``gnomon_env``), so the routing never holds it.

The Test button is the one place Rihmasto calls an endpoint itself: a tiny prompt straight to the role's
endpoint, to say whether it answers and how fast, or what the error is. Every real model call still goes
through Gnomon.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from kernel import harness_setup as hs  # a role a coding agent answers (FR-HMD1)
from kernel import lanes
from kernel.canon import DecisionRefused
from kernel.model import GnomonModel
from kernel.people import PERSONAS, is_person
from kernel.store import REPO_ROOT, Factory, read_json, write_json

SECRETS_ENV = "RIHMASTO_SECRETS_FILE"
KEY_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,63}\Z")
CHAT_PATH = "/chat/completions"
TEST_PROMPT = "Reply with the single word OK."
TEST_TIMEOUT = 20
REACH_TIMEOUT = 0.3
ROLE_PURPOSE = {
    "analyst": "reads requests, asks the panel's questions, writes the spec, and talks with you in Shape it in chat",
    "holdout_author": "writes the hidden acceptance scenarios the builder never sees",
    "builder": "writes the code and its tests in a cell",
    "verifier": "checks the builder's work; it must be another model family than the builder",
    "assistant": "answers Ask Rihma in the cockpit",
}
# Common choices. A preset only fills the form: the person can change any field before saving.
PRESETS: list[dict[str, Any]] = [
    {"id": "llama_cpp", "label": "llama.cpp server on this machine", "base_url": "http://127.0.0.1:8080/v1",
     "model": "local-model", "key_env": None, "local": True},
    {"id": "ollama", "label": "Ollama on this machine", "base_url": "http://127.0.0.1:11434/v1",
     "model": "qwen3:32b", "key_env": None, "local": True},
    {"id": "vllm", "label": "vLLM on this machine", "base_url": "http://127.0.0.1:8000/v1",
     "model": "local-model", "key_env": None, "local": True},
    {"id": "opencode_go", "label": "OpenCode Go (the shipped hosted route)", "base_url": "https://opencode.ai/zen/go/v1",
     "model": "deepseek-v4-pro", "key_env": "OPENCODE_API_KEY", "local": False},
    {"id": "openai", "label": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-4.1-mini",
     "key_env": "OPENAI_API_KEY", "local": False},
    {"id": "openrouter", "label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
     "model": "qwen/qwen3-32b", "key_env": "OPENROUTER_API_KEY", "local": False},
    {"id": "hosted", "label": "Another OpenAI-compatible provider", "base_url": "https://", "model": "",
     "key_env": "", "local": False},
]


class ModelsRefused(ValueError):
    """A change Models setup does not take, with the reason."""


# -- keys: an environment variable, or a key stored outside the repository -------------------------------

def secrets_path() -> Path:
    """Where stored keys are kept: $RIHMASTO_SECRETS_FILE, else ~/.rihmasto/secrets.json. Never in the repository."""
    named = os.environ.get(SECRETS_ENV)
    path = Path(named).expanduser() if named else Path.home() / ".rihmasto" / "secrets.json"
    if path.resolve().is_relative_to(REPO_ROOT.resolve()):
        raise ModelsRefused(f"the secrets file must be outside the repository, not {path}")
    return path


def stored_keys() -> dict[str, str]:
    """The stored keys by the variable name they are handed to Gnomon in. Never shown or logged."""
    try:
        data = read_json(secrets_path(), {}) or {}
    except (ValueError, ModelsRefused):
        return {}
    keys = data.get("keys") if isinstance(data, dict) else None
    return {k: v for k, v in (keys or {}).items() if isinstance(k, str) and isinstance(v, str) and v}


def _write_keys(keys: dict[str, str]) -> None:
    path = secrets_path()
    write_json(path, {"_comment": "Model API keys stored by Rihmasto's Models setup. Keep this file private.",
                      "keys": dict(sorted(keys.items()))})
    if os.name != "nt":
        os.chmod(path, 0o600)


def gnomon_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    """The environment a Gnomon process runs in: this one, with each stored key in its variable when the
    variable is not set already (a key set in the environment wins)."""
    env = dict(os.environ if environ is None else environ)
    for name, value in stored_keys().items():
        env.setdefault(name, value)
    return env


def gnomon_keys() -> frozenset[str] | None:
    """The key variables Gnomon holds for itself, names only (kernel/gnomon_keys.py)."""
    from kernel import gnomon_keys as gk

    return gk.held()


def _key_of(ep: dict[str, Any], environ: dict[str, str] | None = None) -> tuple[str, str | None]:
    """How an endpoint's key is found and the key itself, never shown: "none", "env", "stored", "gnomon" (Gnomon
    holds it: `gnomon key list` names it; Rihmasto never sees the value) or "gnomon_maybe" (Gnomon could not say,
    but its credential store exists)."""
    name = ep.get("api_key_env")
    if not name:
        return "none", None
    env = os.environ if environ is None else environ
    if env.get(name):
        return "env", env[name]
    stored = stored_keys().get(name)
    if stored:
        return "stored", stored
    from kernel.gnomon_keys import kind_of

    return kind_of(name, gnomon_keys()), None


# -- addresses ----------------------------------------------------------------------------------------

def base_url_of(url: str) -> str:
    return url[: -len(CHAT_PATH)] if url.endswith(CHAT_PATH) else url


def chat_url(base_url: str) -> str:
    """The endpoint URL Gnomon calls for an OpenAI-compatible base URL (".../v1")."""
    base = base_url.strip().rstrip("/")
    parts = urlsplit(base)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ModelsRefused(f"the base URL must be http(s)://host[:port]/path with no user name, not {base_url!r}")
    if parts.query or parts.fragment:
        raise ModelsRefused("the base URL takes no query or fragment")
    return base if base.endswith(CHAT_PATH) else base + CHAT_PATH


def is_local(where: str | None, endpoint: dict[str, Any] | None = None) -> bool:
    """A host on this machine or the owner's own network, by the one rule confidential work uses
    (kernel/confidential.py), so Models setup never shows as local what a confidential project refuses."""
    from kernel.confidential import is_local as local

    return local(where, endpoint)


def _reachable(url: str) -> bool:
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((parts.hostname or "", port), timeout=REACH_TIMEOUT):
            return True
    except OSError:
        return False


def gnomon_found() -> bool:
    """Whether ``kernel.model.gnomon_cmd()`` names a Gnomon that exists on this machine."""
    from kernel.model import gnomon_cmd

    cmd = gnomon_cmd()
    if not cmd:
        return False
    if len(cmd) > 1 and cmd[1].endswith(".js"):
        return Path(cmd[1]).exists() and (Path(cmd[0]).exists() or shutil.which(cmd[0]) is not None)
    return Path(cmd[0]).exists() or shutil.which(cmd[0]) is not None


# -- the view -----------------------------------------------------------------------------------------

def _overlay() -> dict[str, Any]:
    try:
        overlay = read_json(lanes.ROUTING_LOCAL_FILE, {})
    except ValueError as exc:
        raise ModelsRefused(f"{lanes.ROUTING_LOCAL_FILE.name} is not valid JSON: {exc}") from exc
    if not isinstance(overlay, dict):
        raise ModelsRefused(f"{lanes.ROUTING_LOCAL_FILE.name} must hold one JSON object")
    return overlay


def _readiness(url: str, local: bool, key: tuple[str, str | None], needs_key: bool, probe: bool) -> dict[str, str]:
    if needs_key and key[0] == "gnomon_maybe":
        return {"state": "maybe_key", "why": "Gnomon may have its own key for this host: its credential store exists, "
                                             "and Rihmasto never opens it (`gnomon key list` names the keys it holds)"}
    if needs_key and not key[1] and key[0] != "gnomon":
        return {"state": "no_key", "why": "its key is not set"}
    if not local and key[0] == "gnomon":
        return {"state": "configured", "why": "a hosted endpoint whose key is set in Gnomon (`gnomon key list` names "
                                              "it); Rihmasto never sees it, and Test cannot send it"}
    if not local:
        return {"state": "configured", "why": "a hosted endpoint with its key; Test sends it a prompt"}
    if not probe:
        return {"state": "unknown", "why": "not checked"}
    if _reachable(url):
        return {"state": "ready", "why": "the server answers on its port"}
    return {"state": "unreachable", "why": "nothing answers on its port"}


def _endpoint_view(routing: dict[str, Any], name: str) -> dict[str, Any]:
    ep = routing.get("endpoints", {}).get(name) or {}
    url = str(ep.get("url") or "")
    host = urlsplit(url).hostname
    return {"endpoint": name, "url": url, "base_url": base_url_of(url), "host": host, "local": is_local(url, ep)}


def role_view(routing: dict[str, Any], role: str, overlay: dict[str, Any], *, environ: dict[str, str] | None = None,
              probe: bool = True) -> dict[str, Any]:
    """One role as Models setup shows it. The key is named (its variable) and said to be set or not; never shown."""
    spec = routing["roles"][role]
    ep = routing.get("endpoints", {}).get(spec["endpoint"]) or {}
    where = _endpoint_view(routing, spec["endpoint"])
    kind, value = _key_of(ep, environ)
    fb = spec.get("fallback")
    return {"role": role, "label": role.replace("_", " ").capitalize(), "purpose": ROLE_PURPOSE.get(role, ""),
            "model": spec["model"], "family": lanes.model_family(routing, role), **where, **hs.role_extra(ep),
            "key": {"kind": kind, "name": ep.get("api_key_env"), "set": bool(value) or kind == "gnomon"},
            "set_here": role in (overlay.get("roles") or {}),
            "fallback": {"model": fb["model"], **_endpoint_view(routing, fb["endpoint"])} if fb else None,
            "readiness": hs.readiness(ep, probe) or _readiness(where["url"], where["local"], (kind, value),
                                                                bool(ep.get("api_key_env")), probe)}


def models_view(*, environ: dict[str, str] | None = None, probe: bool = True) -> dict[str, Any]:
    """Every role with its model, endpoint and readiness; the presets; where the overlay and the keys live."""
    overlay = _overlay()
    routing = lanes.read_routing() or {"roles": {}}
    roles = [role_view(routing, r, overlay, environ=environ, probe=probe) for r in routing.get("roles", {})]
    talking = [r for r in roles if r["role"] in ("analyst", "assistant")]
    found = gnomon_found()
    try:
        keys_at = str(secrets_path())
    except ModelsRefused as exc:
        keys_at = f"(refused: {exc})"
    return {"roles": roles, "presets": PRESETS, "gnomon": found,
            "ready": found and any(r["readiness"]["state"] in ("ready", "configured") for r in talking),
            "overlay": {"path": "kernel/" + lanes.ROUTING_LOCAL_FILE.name,
                        "present": lanes.ROUTING_LOCAL_FILE.exists()},
            "secrets_file": keys_at, "personas": list(PERSONAS)} | hs.view_extra(roles, found, probe)


# -- setting and removing a role -------------------------------------------------------------------------

def family_of(model: str) -> str:
    """A model's family from its name when the person names none: its leading letters ("qwen3:32b" is qwen)."""
    name = model.rsplit("/", 1)[-1].lower()
    m = re.match(r"[a-z]+", name)
    return m.group(0) if m else name


def _signed(person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"refused: {person!r} is not a person; Models setup is changed by a named person")
    if persona not in PERSONAS:
        raise DecisionRefused(f"refused: persona must be one of {', '.join(PERSONAS)}")


def _endpoint_for(routing: dict[str, Any], overlay: dict[str, Any], role: str, url: str, key_env: str | None,
                  private: bool = False) -> str:
    """An existing endpoint with this URL, key variable and privacy, or this role's own one in the overlay.
    ``private`` declares a host on the owner's own network (a tailnet, a VPN) local for confidential work."""
    name = f"{role}-custom"
    for known, ep in (routing.get("endpoints") or {}).items():
        mine = known == name or not str(known).endswith("-custom")   # another role's own endpoint is its own
        if mine and isinstance(ep, dict) and ep.get("url") == url and (ep.get("api_key_env") or None) == key_env \
                and bool(ep.get("private")) == private:
            return str(known)
    overlay.setdefault("endpoints", {})[name] = {"kind": "openai", "url": url,
                                                 **({"api_key_env": key_env} if key_env else {}),
                                                 **({"private": True} if private else {})}
    return name


def _keep(overlay: dict[str, Any]) -> dict[str, Any]:
    """The overlay checked over the shipped routing (FR-G6), then written. Returns the merged routing."""
    shipped = read_json(lanes.ROUTING_FILE)
    if shipped is None:
        raise ModelsRefused(f"no routing file at {lanes.ROUTING_FILE}")
    merged = lanes.merge_routing(shipped, overlay)
    try:
        lanes.check_routing(merged)
    except ValueError as exc:
        raise ModelsRefused(f"refused: {exc}") from None
    write_json(lanes.ROUTING_LOCAL_FILE, overlay)
    return merged


def _key_name(role: str, key_env: str | None, key: str | None) -> str | None:
    name = (key_env or "").strip() or (f"RIHMASTO_KEY_{role.upper()}" if key else None)
    if name is not None and not KEY_NAME.match(name):
        raise ModelsRefused("the key's variable is a name such as MY_PROVIDER_KEY (capitals, digits and _), "
                            "never the key itself")
    return name


def _role_routing(role: str) -> dict[str, Any]:
    routing = lanes.read_routing() or {}
    if role not in (routing.get("roles") or {}):
        raise ModelsRefused(f"there is no role {role!r}; the roles are {', '.join(routing.get('roles') or {})}")
    return routing


def _model_name(model: str) -> str:
    model = model.strip()
    if not model or len(model) > 200:
        raise ModelsRefused("name the model, as the endpoint knows it")
    return model


def _ledger(factory: Factory, kind: str, payload: dict[str, Any]) -> None:
    """A change of Models setup in the factory's own ledger: who, which role, which host; never a key."""
    from kernel.learn import factory_project

    canon = factory_project(factory)
    canon.log(kind, payload)


def _fallback_note(role: str, merged: dict[str, Any]) -> dict[str, Any]:
    """A local role that kept a hosted fallback says so: a confidential project skips that fallback, never calls it."""
    from kernel.confidential import skipped

    hosted = skipped([role], merged)
    if not hosted:
        return {}
    return {"note": f"Its fallback goes to the hosted endpoint {hosted[0]['endpoint']!r}: a confidential project "
                    "skips it (never calls it) and records the skip in its ledger. Set the role again without the "
                    "fallback (untick Keep the fallback, or --no-fallback) to drop it for every project."}


def set_role(factory: Factory, role: str, *, base_url: str, model: str, person: str, persona: str,
             family: str | None = None, key_env: str | None = None, key: str | None = None,
             keep_fallback: bool = True, private: bool = False) -> dict[str, Any]:
    """Point a role at an endpoint and a model, signed by a person. ``key`` is stored outside the repository
    under ``key_env`` (default RIHMASTO_KEY_<ROLE>); without it ``key_env`` names a variable already set.
    ``private`` declares the endpoint's host on the owner's own network, so confidential work may use it."""
    _signed(person, persona)
    routing, model = _role_routing(role), _model_name(model)
    url, name = chat_url(base_url), _key_name(role, key_env, key)
    overlay = _overlay()
    endpoint = _endpoint_for(routing, overlay, role, url, name, private)
    fb = routing["roles"][role].get("fallback") if keep_fallback else None
    overlay.setdefault("roles", {})[role] = {"model": model, "endpoint": endpoint, **({"fallback": fb} if fb else {})}
    known = (routing.get("models") or {}).get(model, {}).get("family")
    overlay.setdefault("models", {})[model] = {"family": (family or "").strip().lower() or known or family_of(model)}
    merged = _keep(overlay)
    if key:
        _write_keys({**stored_keys(), str(name): key.strip()})
    view = role_view(merged, role, overlay, probe=False)
    view.update(_fallback_note(role, merged))
    _ledger(factory, "models_set", {
        "role": role, "model": model, "family": view["family"], "endpoint": endpoint, "host": view["host"],
        "local": view["local"], "key": "stored" if key else "env" if name else "none", "person": person,
        "persona": persona})
    return view


def _drop_unused(overlay: dict[str, Any]) -> set[str]:
    """Take out of the overlay the roles' own endpoints no role uses any more, and the tables left empty.
    Returns the key variables those endpoints named."""
    merged = lanes.merge_routing(read_json(lanes.ROUTING_FILE) or {}, overlay)
    used = {s["endpoint"] for s in merged["roles"].values()} | \
        {s["fallback"]["endpoint"] for s in merged["roles"].values() if s.get("fallback")}
    gone = [n for n in (overlay.get("endpoints") or {}) if n.endswith("-custom") and n not in used]
    names = {overlay["endpoints"][n].get("api_key_env") for n in gone} - {None}
    for n in gone:
        del overlay["endpoints"][n]
    for table in ("roles", "endpoints", "models"):
        if table in overlay and not overlay[table]:
            del overlay[table]
    return {str(n) for n in names}


def remove_role(factory: Factory, role: str, *, person: str, persona: str) -> dict[str, Any]:
    """Take a role back to the shipped routing: its overlay entry goes, with an endpoint and a stored key only
    it used. Signed by a person."""
    _signed(person, persona)
    overlay = _overlay()
    if role not in (overlay.get("roles") or {}):
        raise ModelsRefused(f"{role} is not set on this machine: it already uses the shipped routing")
    del overlay["roles"][role]
    names = _drop_unused(overlay)
    merged = _keep(overlay)
    still = {ep.get("api_key_env") for ep in merged.get("endpoints", {}).values() if isinstance(ep, dict)}
    keys = stored_keys()
    if any(n in keys and n not in still for n in names):
        _write_keys({k: v for k, v in keys.items() if k in still or k not in names})
    _ledger(factory, "models_removed", {"role": role, "person": person, "persona": persona,
                                        "now": merged["roles"][role]["endpoint"]})
    return role_view(merged, role, overlay, probe=False)


# -- the Test button --------------------------------------------------------------------------------------

def _scrub(text: str, secret: str | None) -> str:
    text = " ".join(str(text).split())[:300]
    return text.replace(secret, "[key]") if secret else text


def _answer_text(raw: bytes) -> str:
    data = json.loads(raw.decode("utf-8", errors="replace"))
    choice = (data.get("choices") or [{}])[0] if isinstance(data, dict) else {}
    message = choice.get("message") or {}
    return str(message.get("content") or choice.get("text") or "").strip()


def probe_role(role: str, *, environ: dict[str, str] | None = None, timeout: float = TEST_TIMEOUT) -> dict[str, Any]:
    """Send the role's endpoint a tiny prompt and say how long it took, or what went wrong. Records nothing."""
    routing = _role_routing(role)
    tested = hs.probe(role, routing)          # a harness: a tiny prompt through it (FR-HMD1)
    if tested is not None:
        return tested
    spec = routing["roles"][role]
    ep = routing.get("endpoints", {}).get(spec["endpoint"]) or {}
    url, (kind, key) = str(ep.get("url") or ""), _key_of(ep, environ)
    out: dict[str, Any] = {"role": role, "model": spec["model"], "host": urlsplit(url).hostname, "ok": False}
    if ep.get("api_key_env") and not key and kind in ("gnomon", "gnomon_maybe"):
        return {**out, "error": f"the key for {ep['api_key_env']} is " + ("set in Gnomon" if kind == "gnomon" else
                                "perhaps held by Gnomon") + ", which Rihmasto never reads, so Test cannot send it; a run "
                                "goes through Gnomon and uses it. To test here, set the variable or store a key"}
    if ep.get("api_key_env") and not key:
        return {**out, "error": f"its key is not set: set {ep['api_key_env']} or store a key in Models setup"}
    body = json.dumps({"model": spec["model"], "messages": [{"role": "user", "content": TEST_PROMPT}],
                       "max_tokens": 16, "temperature": 0}).encode("utf-8")
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if is_local(url, ep) \
        else urllib.request.build_opener()
    start, request = time.monotonic(), urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with opener.open(request, timeout=timeout) as res:
            raw = res.read(65536)
        reply = _answer_text(raw)
    except urllib.error.HTTPError as exc:
        with exc:
            detail = exc.read(400).decode("utf-8", errors="replace")
        return {**out, "error": _scrub(f"HTTP {exc.code}: {detail}", key)}
    except (urllib.error.URLError, OSError) as exc:
        return {**out, "error": _scrub(f"could not reach {out['host']}: {getattr(exc, 'reason', exc)}", key)}
    except (ValueError, AttributeError) as exc:
        return {**out, "error": _scrub(f"the answer is not an OpenAI-compatible reply: {exc}", key)}
    ms = round((time.monotonic() - start) * 1000)
    return {**out, "ok": True, "latency_ms": ms, "reply": _scrub(reply, key)[:120]}


# -- the model the cockpit's chat asks ---------------------------------------------------------------------

class LaneModel(GnomonModel):
    """Gnomon in the analyst lane, compiled again from the routing before each call, so a role set in
    Models setup answers from the next message on."""

    def __init__(self, timeout: int = 900) -> None:
        super().__init__(lanes.lanes_root() / "analyst", timeout=timeout)

    def refresh(self) -> None:
        with lanes.lane_lock(self.lane_dir):
            self.lane_dir = lanes.ensure_analyst_lane(lanes.load_routing())

    def ask(self, prompt: str, *, role: str) -> str:
        self.refresh()
        return super().ask(prompt, role=role)
