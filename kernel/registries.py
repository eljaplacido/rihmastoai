"""The registries a capability is published to (FR-DST1): IT names them in `<home>/registries.json`.

A registry is a publishing destination: a container registry for the capability's image (GitHub's
`ghcr`, Google's `artifact-registry`, Azure's `acr`, Docker Hub's `dockerhub`, or any other `container`
registry), an MCP registry listing (`mcp-registry`: Rihmasto writes the server manifest a person submits;
it never submits it), or a package registry (`package`: shown as a destination, publishing to it is not
built). Each registry serves one tier, `test` or `production`: a release goes to a test registry first,
and to a production one only through IT's deploy gate (kernel/publish.py).

    {"schema": "rihmasto.registries/1",
     "registries": {
       "ghcr-test": {"kind": "ghcr", "environment": "test", "configured": true, "owner": "IT: the platform team",
                     "namespace": "example-org/test",
                     "login": {"username_env": "GHCR_USER", "password_env": "GHCR_TOKEN"}},
       "ghcr": {"kind": "ghcr", "environment": "production", "configured": true, "namespace": "example-org",
                "login": "existing"},
       "mcp-listing": {"kind": "mcp-registry", "environment": "production", "configured": true,
                       "namespace": "io.github.example-org"}}}

**Credentials by name only.** `login` is `"existing"` (the deploying host's docker is already signed in to
the registry, by IT, with its own credential helper) or the NAMES of two environment variables that hold the
user name and the token. Rihmasto reads their values only to hand the token to `docker login
--password-stdin`; no value is ever in a file, an argument, a record or an answer. A value that looks like a
token anywhere in the file is a problem, and the registry is not ready. `missing` says exactly what stands
between a registry and a publish.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Mapping
from typing import Any

from kernel.connectors import SECRETISH
from kernel.store import read_json

SCHEMA = "rihmasto.registries/1"
FILE = "registries.json"
# Container registry kinds and their default host (None: IT names it, as it differs per account).
CONTAINER_KINDS: dict[str, str | None] = {"ghcr": "ghcr.io", "dockerhub": "docker.io", "artifact-registry": None,
                                          "acr": None, "container": None}
KINDS = (*CONTAINER_KINDS, "mcp-registry", "package")
TIERS = ("test", "production")
LABEL = {"ghcr": "GitHub Container Registry", "dockerhub": "Docker Hub", "artifact-registry": "Artifact Registry",
         "acr": "Azure Container Registry", "container": "Container registry", "mcp-registry": "MCP registry listing",
         "package": "Package registry"}
ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{1,63}\Z")
HOST = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:\d{1,5})?\Z")
NAMESPACE = re.compile(r"[a-z0-9][a-z0-9._/-]{0,120}\Z")
MCP_NAMESPACE = re.compile(r"[a-z0-9][a-z0-9.-]{1,100}\Z")


def path(factory: Any):
    return factory.home / FILE


def load(factory: Any) -> dict[str, Any]:
    """The registries IT named, with any problem in the file itself. A missing file is no registry."""
    p = path(factory)
    try:
        raw = read_json(p)
    except (json.JSONDecodeError, ValueError) as exc:
        return {"registries": {}, "problems": [f"{p.name} is not valid JSON: {exc}"], "source": str(p)}
    raw = raw if isinstance(raw, dict) else {}
    problems = [] if raw.get("schema") in (None, SCHEMA) else [f"schema must be {SCHEMA}, got {raw.get('schema')!r}"]
    found = raw.get("registries") or {}
    regs = {str(k): dict(v) for k, v in found.items() if isinstance(v, dict)} if isinstance(found, dict) else {}
    problems += [f"registry {k!r} is not an object" for k, v in (found.items() if isinstance(found, dict) else [])
                 if not isinstance(v, dict)]
    return {"registries": regs, "problems": problems, "source": str(p) if p.exists() else None}


def registry(factory: Any, name: str) -> dict[str, Any] | None:
    return load(factory)["registries"].get(name)


def tier(cfg: dict[str, Any]) -> str | None:
    t = cfg.get("environment")
    return t if t in TIERS else None


def host(cfg: dict[str, Any]) -> str | None:
    return str(cfg.get("host") or CONTAINER_KINDS.get(str(cfg.get("kind"))) or "").strip().rstrip("/") or None


def _secret_values(value: Any, where: str = "$") -> list[str]:
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in _secret_values(v, f"{where}.{k}")]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in _secret_values(v, f"{where}[{i}]")]
    return [where] if isinstance(value, str) and SECRETISH.search(value) else []


def login_names(cfg: dict[str, Any]) -> tuple[str, str] | None:
    login = cfg.get("login")
    if isinstance(login, dict):
        return str(login.get("username_env") or ""), str(login.get("password_env") or "")
    return None


def _login_missing(name: str, cfg: dict[str, Any], environ: Mapping[str, str]) -> list[str]:
    login = cfg.get("login")
    if login == "existing":
        return []
    names = login_names(cfg)
    if names is None:
        return [f"registry {name!r} names no login: \"existing\" (docker is signed in on the deploying host) or "
                "{\"username_env\": NAME, \"password_env\": NAME}, the names of the variables that hold them"]
    out = []
    for key, value in zip(("username_env", "password_env"), names, strict=True):
        if not ENV_NAME.match(value):
            out.append(f"registry {name!r}: login.{key} is the NAME of an environment variable (A_NAME_LIKE_THIS)")
        elif not environ.get(value):
            out.append(f"the environment variable {value} (login.{key} of {name!r}) is not set on the deploying host")
    return out


def missing(name: str, cfg: dict[str, Any] | None, *, environ: Mapping[str, str] | None = None,
            docker: str = "docker") -> list[str]:
    """What stands between this registry and a publish to it. Empty means ready."""
    if cfg is None:
        return [f"no registry named {name!r}: IT names it in registries.json in the factory home"]
    environ = os.environ if environ is None else environ
    kind = cfg.get("kind")
    if kind not in KINDS:
        return [f"registry {name!r}: kind must be one of {', '.join(KINDS)}, got {kind!r}"]
    out = [f"registry {name!r} carries a value that looks like a secret at {w}: name the variable that holds it"
           for w in _secret_values(cfg)]
    if cfg.get("configured") is not True:
        out.append(f"registry {name!r} is not marked \"configured\": true by IT")
    if tier(cfg) is None:
        out.append(f"registry {name!r}: environment is test or production")
    if kind == "package":
        return out + ["publishing to a package registry is not built yet: it is shown as a planned destination"]
    if kind == "mcp-registry":
        if not MCP_NAMESPACE.match(str(cfg.get("namespace") or "")):
            out.append(f"registry {name!r}: namespace is the reverse-DNS name the listing is published under "
                       "(io.github.example-org)")
        return out
    return out + _container_missing(name, cfg, environ, docker)


def _container_missing(name: str, cfg: dict[str, Any], environ: Mapping[str, str], docker: str) -> list[str]:
    out = []
    if not HOST.match(host(cfg) or ""):
        out.append(f"registry {name!r}: host names the registry (europe-north1-docker.pkg.dev, example.azurecr.io)")
    if not NAMESPACE.match(str(cfg.get("namespace") or "")):
        out.append(f"registry {name!r}: namespace is where images go in it (example-org, project/repository)")
    out += _login_missing(name, cfg, environ)
    if shutil.which(str(cfg.get("docker_cli") or docker), path=environ.get("PATH")) is None:
        out.append("the docker CLI is not on PATH on the deploying host")
    return out


def repository(cfg: dict[str, Any], project: Any) -> str:
    """Where the capability's image goes: host/namespace/name (the name is the project's, or IT's `image`)."""
    image = str(cfg.get("image") or f"rihmasto-{project.pid}").strip("/")
    return f"{host(cfg)}/{str(cfg.get('namespace')).strip('/')}/{image}"


def public(name: str, cfg: dict[str, Any], *, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """A registry as a view shows it: never a value, only the names of the variables."""
    names = login_names(cfg)
    return {"name": name, "kind": cfg.get("kind"), "label": LABEL.get(str(cfg.get("kind")), str(cfg.get("kind"))),
            "environment": tier(cfg), "host": host(cfg) if cfg.get("kind") in CONTAINER_KINDS else None,
            "namespace": cfg.get("namespace"), "owner": cfg.get("owner"),
            "login": "existing" if cfg.get("login") == "existing" else
            ({"username_env": names[0], "password_env": names[1]} if names else None),
            "missing": missing(name, cfg, environ=environ)}


def all_public(factory: Any, *, environ: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    return [public(n, c, environ=environ) for n, c in sorted(load(factory)["registries"].items())]
