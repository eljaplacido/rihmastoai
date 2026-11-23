"""The gateway's configuration: workloads, their fallback ladders, upstreams, quotas and the audit.

A gateway config is one JSON file. It is checked whole when it is loaded, and a mistake is refused
with the path of the offending value, so a gateway never starts on a config it half understands.

- **Upstreams** are OpenAI-compatible endpoints. One that is not on your own network is declared
  `"cloud": true` and reached over https. A key is named only by its environment variable
  (`api_key_env`); a config that holds a key itself is refused.
- **Workloads** have a class (interactive, batch, specialist), a data class floor, an optional
  token bucket, and a ladder: L1 the workload's model on its upstreams, L2 a smaller model whose
  answers are flagged degraded, L3 a cloud upstream, L4 `"defer"` (queue the request).
- **The site mode** decides whether cloud upstreams may be used at all: `air-gapped` (never, the
  default) or `connected` (only for requests whose data class is at most `cloud_max_data_class`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

FORMAT = "rihma.gateway.v1"
DATA_CLASSES = ("public", "internal", "confidential", "restricted")
WORKLOAD_CLASSES = ("interactive", "batch", "specialist")
SITE_MODES = ("air-gapped", "connected")
LEVELS = ("L1", "L2", "L3")  # the rungs that call an upstream; L4 is the queue
DEFAULT_CONCURRENCY = {"interactive": 8, "batch": 2, "specialist": 2}
# Keys that would hold a secret. Keys are named by environment variable, never written down.
SECRET_KEYS = frozenset({"api_key", "apikey", "key", "token", "secret", "password", "authorization", "bearer"})
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


class ConfigError(ValueError):
    """The gateway config is wrong; the message names where."""


@dataclass(frozen=True)
class Upstream:
    name: str
    url: str
    cloud: bool = False
    api_key_env: str | None = None
    timeout_s: float = 60.0


@dataclass(frozen=True)
class Target:
    level: str
    upstream: str
    model: str
    degraded: bool = False


@dataclass(frozen=True)
class Bucket:
    per_minute: float
    burst: int


@dataclass(frozen=True)
class Workload:
    name: str
    workload_class: str
    data_class: str
    targets: tuple[Target, ...]
    defer: bool = False
    rate: Bucket | None = None
    description: str = ""


@dataclass(frozen=True)
class DeferPolicy:
    max_queue: int = 100
    retry_s: float = 30.0
    max_attempts: int = 5


@dataclass(frozen=True)
class GatewayConfig:
    site_mode: str
    cloud_max_data_class: str
    upstreams: dict[str, Upstream]
    workloads: dict[str, Workload]
    concurrency: dict[str, int]
    wait_s: float
    audit_path: Path
    content_capture: bool
    defer: DeferPolicy


def _require(ok: bool, where: str, expected: str) -> None:
    if not ok:
        raise ConfigError(f"{where}: expected {expected}")


def _keys(obj: Any, where: str, allowed: set[str], required: frozenset[str] = frozenset()) -> dict:
    _require(isinstance(obj, dict), where, "an object")
    secret = sorted(SECRET_KEYS & {str(k).lower() for k in obj})
    if secret:
        raise ConfigError(f"{where}: holds {', '.join(secret)}; name a key by its environment variable "
                          f"(api_key_env), never write it into the config")
    unknown = sorted(set(obj) - allowed)
    _require(not unknown, where, f"only the keys {sorted(allowed)}, not {unknown}")
    missing = sorted(required - set(obj))
    _require(not missing, where, f"the keys {missing}")
    return obj


def _number(value: Any, where: str, low: float, high: float) -> float:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high
    _require(ok, where, f"a number from {low} to {high}")
    return float(value)


def _integer(value: Any, where: str, low: int, high: int) -> int:
    ok = isinstance(value, int) and not isinstance(value, bool) and low <= value <= high
    _require(ok, where, f"a whole number from {low} to {high}")
    return int(value)


def _choice(value: Any, where: str, choices: tuple[str, ...]) -> str:
    _require(value in choices, where, "one of " + ", ".join(choices))
    return str(value)


def completions_url(url: str) -> str:
    """The chat completions URL of an endpoint given as its base (`.../v1`) or in full."""
    url = url.rstrip("/")
    return url if url.endswith("/chat/completions") else url + "/chat/completions"


def _upstream(name: str, raw: Any) -> Upstream:
    where = f"upstreams.{name}"
    _require(bool(NAME.match(name)), where, "a lower-case name of letters, digits, '.', '_' or '-'")
    obj = _keys(raw, where, {"url", "cloud", "api_key_env", "timeout_s", "description"}, frozenset({"url"}))
    url = obj["url"]
    parts = urlsplit(url) if isinstance(url, str) else None
    _require(parts is not None and parts.scheme in ("http", "https") and bool(parts.hostname), f"{where}.url",
             "the http(s) URL of an OpenAI-compatible endpoint")
    cloud = obj.get("cloud", False)
    _require(isinstance(cloud, bool), f"{where}.cloud", "true or false")
    _require(not cloud or (parts is not None and parts.scheme == "https"), f"{where}.url",
             "https for a cloud upstream")
    env = obj.get("api_key_env")
    _require(env is None or (isinstance(env, str) and bool(ENV_NAME.match(env))), f"{where}.api_key_env",
             "the name of an environment variable")
    timeout = _number(obj.get("timeout_s", 60), f"{where}.timeout_s", 0.1, 600)
    return Upstream(name=name, url=completions_url(url), cloud=cloud, api_key_env=env, timeout_s=timeout)


def _target(where: str, level: str, raw: Any, upstreams: dict[str, Upstream]) -> Target:
    obj = _keys(raw, where, {"upstream", "model", "degraded"}, frozenset({"upstream", "model"}))
    up = obj["upstream"]
    _require(up in upstreams, f"{where}.upstream", "a declared upstream: " + ", ".join(sorted(upstreams)))
    _require(isinstance(obj["model"], str) and bool(obj["model"].strip()), f"{where}.model", "a model name")
    _require(level != "L3" or upstreams[up].cloud, f"{where}.upstream", "a cloud upstream at L3")
    degraded = obj.get("degraded", False)
    _require(isinstance(degraded, bool), f"{where}.degraded", "true or false")
    # L2 is a smaller model: its answers are always flagged degraded.
    return Target(level=level, upstream=up, model=obj["model"], degraded=degraded or level == "L2")


def _ladder(where: str, raw: Any, upstreams: dict[str, Upstream]) -> tuple[tuple[Target, ...], bool]:
    obj = _keys(raw, where, {"L1", "L2", "L3", "L4"}, frozenset({"L1"}))
    targets: list[Target] = []
    for level in LEVELS:
        rung = obj.get(level, [])
        _require(isinstance(rung, list), f"{where}.{level}", "a list of targets")
        targets += [_target(f"{where}.{level}[{i}]", level, t, upstreams) for i, t in enumerate(rung)]
    _require(any(t.level == "L1" for t in targets), f"{where}.L1", "at least one target")
    _require(obj.get("L4") in (None, "defer"), f"{where}.L4", '"defer" (queue with a "no answer yet" status)')
    return tuple(targets), obj.get("L4") == "defer"


def _bucket(where: str, raw: Any) -> Bucket | None:
    if raw is None:
        return None
    obj = _keys(raw, where, {"per_minute", "burst"}, frozenset({"per_minute"}))
    per_minute = _number(obj["per_minute"], f"{where}.per_minute", 0.001, 1_000_000)
    burst = _integer(obj.get("burst", max(1, int(per_minute))), f"{where}.burst", 1, 1_000_000)
    return Bucket(per_minute=per_minute, burst=burst)


def _workload(name: str, raw: Any, upstreams: dict[str, Upstream]) -> Workload:
    where = f"workloads.{name}"
    _require(bool(NAME.match(name)), where, "a lower-case name of letters, digits, '.', '_' or '-'")
    obj = _keys(raw, where, {"class", "description", "data_class", "ladder", "rate"},
                frozenset({"class", "ladder"}))
    targets, defer = _ladder(f"{where}.ladder", obj["ladder"], upstreams)
    description = obj.get("description", "")
    _require(isinstance(description, str), f"{where}.description", "text")
    return Workload(name=name, workload_class=_choice(obj["class"], f"{where}.class", WORKLOAD_CLASSES),
                    data_class=_choice(obj.get("data_class", "internal"), f"{where}.data_class", DATA_CLASSES),
                    targets=targets, defer=defer, rate=_bucket(f"{where}.rate", obj.get("rate")),
                    description=description)


def _quotas(raw: Any) -> tuple[dict[str, int], float]:
    obj = _keys(raw, "quotas", {"concurrency", "wait_s"})
    given = _keys(obj.get("concurrency", {}), "quotas.concurrency", set(WORKLOAD_CLASSES))
    limits = dict(DEFAULT_CONCURRENCY)
    for klass, value in given.items():
        limits[klass] = _integer(value, f"quotas.concurrency.{klass}", 1, 10_000)
    return limits, _number(obj.get("wait_s", 0), "quotas.wait_s", 0, 60)


def _site(raw: Any) -> tuple[str, str]:
    obj = _keys(raw, "site", {"mode", "cloud_max_data_class", "name"}, frozenset({"mode"}))
    mode = _choice(obj["mode"], "site.mode", SITE_MODES)
    return mode, _choice(obj.get("cloud_max_data_class", "public"), "site.cloud_max_data_class", DATA_CLASSES)


def _audit(raw: Any, base: Path) -> tuple[Path, bool]:
    obj = _keys(raw, "audit", {"path", "content_capture"})
    path = obj.get("path", "gateway-audit.jsonl")
    _require(isinstance(path, str) and bool(path.strip()), "audit.path", "a file path")
    capture = obj.get("content_capture", False)
    _require(isinstance(capture, bool), "audit.content_capture", "true or false")
    return base / path, capture


def _defer(raw: Any) -> DeferPolicy:
    obj = _keys(raw, "defer", {"max_queue", "retry_s", "max_attempts"})
    return DeferPolicy(max_queue=_integer(obj.get("max_queue", 100), "defer.max_queue", 1, 100_000),
                       retry_s=_number(obj.get("retry_s", 30), "defer.retry_s", 0.1, 86_400),
                       max_attempts=_integer(obj.get("max_attempts", 5), "defer.max_attempts", 1, 1000))


def parse_config(raw: Any, base: Path | str = ".") -> GatewayConfig:
    """A checked config from its parsed JSON. Relative paths (the audit) resolve against ``base``."""
    top = _keys(raw, "config", {"format", "description", "site", "upstreams", "workloads", "quotas", "audit",
                                "defer"}, frozenset({"upstreams", "workloads"}))
    _require(top.get("format", FORMAT) == FORMAT, "format", FORMAT)
    _require(isinstance(top["upstreams"], dict) and bool(top["upstreams"]), "upstreams", "at least one upstream")
    _require(isinstance(top["workloads"], dict) and bool(top["workloads"]), "workloads", "at least one workload")
    upstreams = {name: _upstream(name, value) for name, value in top["upstreams"].items()}
    workloads = {name: _workload(name, value, upstreams) for name, value in top["workloads"].items()}
    mode, cloud_max = _site(top.get("site", {"mode": "air-gapped"}))
    concurrency, wait_s = _quotas(top.get("quotas", {}))
    audit_path, capture = _audit(top.get("audit", {}), Path(base))
    return GatewayConfig(site_mode=mode, cloud_max_data_class=cloud_max, upstreams=upstreams, workloads=workloads,
                         concurrency=concurrency, wait_s=wait_s, audit_path=audit_path, content_capture=capture,
                         defer=_defer(top.get("defer", {})))


def load_config(path: Path | str) -> GatewayConfig:
    """Read and check a gateway config file."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path.name}: not JSON ({exc})") from exc
    return parse_config(raw, path.resolve().parent)


def cloud_allowed(config: GatewayConfig, data_class: str) -> bool:
    """Whether a request of this data class may reach a cloud upstream at this site."""
    if config.site_mode != "connected":
        return False
    return DATA_CLASSES.index(data_class) <= DATA_CLASSES.index(config.cloud_max_data_class)
