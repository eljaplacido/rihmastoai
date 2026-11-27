"""Publishing a release to a registry (FR-DST1): its container image, and its MCP face's registry entry.

The owner (2026-11-24): "Rihmasto is the middle layer of development and all backend work and any external
platform / channel or similar where the solutions are pushed and published or taken to testing."

    rihmasto publish <pid> --to <registry> [--release N] --person P --persona it

**A container image** goes to a registry IT named in `<home>/registries.json` (kernel/registries.py) with the
docker CLI on the deploying host: the release's own image when its road built one (a docker road's local
image, or a cloud road's image pulled by its digest), else one built from a clean checkout at the release's
revision; then `docker tag` and `docker push`, and the digest the registry gave back is recorded. With
`login` naming two environment variables, `docker login --password-stdin` gets the token on its input, never
in an argument. A registry that is not ready refuses, saying exactly what is missing, and the refusal is
recorded (`publish_refused`) with who asked.

**Test first, then production.** A release goes to a `test` registry first. A `production` registry takes it
only after the same release was published to a test registry, and only through IT's deploy gate: the first
publish opens a `deploy_gate` card (IT decides it, as a road's), and the next one, after IT approved, pushes.
IT's refusal stops it. Every publish is recorded in the project's `publishes.json` and its ledger
(`published`, `publish_failed`, `publish_waiting`), which the life-cycle automations react to.

**An MCP registry entry** (`kind: mcp-registry`) is a file: the server manifest (`server.json`) of the
capability's MCP face, written to `publish/<release>/mcp-server.json` in the project, naming the published
image when there is one. A person submits it to the registry; Rihmasto never submits anything to a public
registry.

This amends D-0015's "IT pushes the tag with its own tools" by the owner's word above: a person asks for
each publish, signed, and production keeps IT's gate.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from typing import Any, NoReturn

from kernel import registries
from kernel.canon import Canon, DecisionRefused
from kernel.people import is_person
from kernel.store import updating_json

PUBLISHERS = ("it", "developer", "operations", "product_owner")
RECORD = "publishes.json"
MCP_SCHEMA = "https://static.modelcontextprotocol.io/schemas/2025-09-29/server.schema.json"
DIGEST = re.compile(r"digest:\s*(sha256:[0-9a-f]{64})")
TIMEOUT = 1800


class PublishRefused(ValueError):
    """A publish that cannot go: what is missing, said exactly. Recorded before it is raised."""

    def __init__(self, message: str, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing = list(missing or [message])


class PublishFailed(RuntimeError):
    pass


class DockerPublisher:
    """The docker CLI on the deploying host, found on PATH when it is called. Its output is read for a digest
    and never kept whole; a token goes to `docker login` on its input only."""

    def __init__(self, binary: str = "docker", environ: Mapping[str, str] | None = None) -> None:
        self.binary, self.environ = binary, dict(os.environ if environ is None else environ)

    def __call__(self, *args: str, stdin: str | None = None) -> str:
        exe = shutil.which(self.binary, path=self.environ.get("PATH"))
        if exe is None:
            raise PublishFailed("the docker CLI is not on PATH on the deploying host")
        try:
            proc = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  input=stdin, stdin=None if stdin is not None else subprocess.DEVNULL,
                                  timeout=TIMEOUT, env=self.environ)
        except subprocess.TimeoutExpired:
            raise PublishFailed(f"docker {args[0]} did not finish in {TIMEOUT}s") from None
        except OSError as exc:
            raise PublishFailed(f"docker could not be started: {type(exc).__name__}") from None
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
            raise PublishFailed(f"docker {args[0]} failed (exit {proc.returncode}): {tail[0][:300]}")
        return proc.stdout or ""


def history(project: Any) -> list[dict[str, Any]]:
    found = project.read(RECORD, [])
    return found if isinstance(found, list) else []


def _keep(project: Any, entry: dict[str, Any]) -> dict[str, Any]:
    with updating_json(project.path(RECORD), []) as rows:
        entry = {"n": len(rows) + 1, **entry}
        rows.append(entry)
    return entry


def _release(project: Any, number: int | None) -> dict[str, Any]:
    from kernel.deliver import releases

    found = [r for r in releases(project) if r.get("state") not in ("superseded", "failed")
             and (number is None or r.get("release") == number)]
    if not found:
        raise PublishRefused(f"{project.pid} has no release {number}" if number else
                             f"{project.pid} has no release to publish yet: deliver it first (rihmasto deliver "
                             f"{project.pid})")
    return found[-1]


def _signs(person: str, persona: str) -> None:
    if not is_person(person):
        raise DecisionRefused(f"{person!r} is not a person: a publish is signed by a named person")
    if persona not in PUBLISHERS:
        raise DecisionRefused(f"a {persona} may not publish; {', '.join(PUBLISHERS)} may")


def _refuse(project: Any, name: str, rel: dict | None, why: str, missing: list[str], who: tuple[str, str]) -> NoReturn:
    project.log("publish_refused", {"registry": name, "release": (rel or {}).get("release"), "missing": missing,
                                    "by": who[0], "persona": who[1]})
    raise PublishRefused(why, missing)


def publish(project: Any, *, to: str, person: str, persona: str, release: int | None = None,
            environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Publish a release (the latest that was not superseded, unless named) to the registry ``to``."""
    _signs(person, persona)
    who, environ = (person, persona), dict(os.environ if environ is None else environ)
    cfg = registries.registry(project.factory, to)
    try:
        rel = _release(project, release)
    except PublishRefused as exc:
        _refuse(project, to, None, str(exc), exc.missing, who)
    missing = registries.missing(to, cfg, environ=environ)
    if missing:
        _refuse(project, to, rel, f"registry {to} is not ready: " + "; ".join(missing), missing, who)
    assert cfg is not None
    if cfg["kind"] == "mcp-registry":
        return mcp_entry(project, to, cfg, rel, who)
    if registries.tier(cfg) == "production":
        held = _production(project, to, cfg, rel, who)
        if held is not None:
            return held
    return _push(project, to, cfg, rel, who, environ)


def _published(project: Any, release: int, tier: str, kind_of: str = "container") -> list[dict[str, Any]]:
    return [h for h in history(project) if h.get("release") == release and h.get("state") == "published"
            and h.get("environment") == tier and h.get("type") == kind_of]


def _tested_first(project: Any, name: str, rel: dict, who: tuple[str, str]) -> dict[str, Any]:
    """The release's last publish to a test registry; refused, and recorded, when there is none."""
    n = rel["release"]
    tested = _published(project, n, "test")
    if tested:
        return tested[-1]
    tests = [r for r, c in registries.load(project.factory)["registries"].items()
             if registries.tier(c) == "test" and c.get("kind") in registries.CONTAINER_KINDS]
    where = f" ({', '.join(tests)})" if tests else ": IT names one with environment test"
    why = f"publish release {n} to a test registry first{where}"
    _refuse(project, name, rel, why, [why], who)


def _gate_refused(project: Any, name: str, rel: dict, card: dict, gates: list[dict], who: tuple[str, str]) -> NoReturn:
    n, d = rel["release"], card["decision"]
    if not any(h.get("state") == "refused by the gate" for h in gates):
        _keep(project, {"registry": name, "release": n, "card": card["id"], "state": "refused by the gate",
                        "type": "container", "environment": "production", "at": project.factory.clock.stamp()})
    _refuse(project, name, rel, f"IT refused publishing release {n} to {name} ({d['person']}): "
            f"{d.get('reason') or 'no reason given'}", [f"the deploy gate {card['id']} was refused"], who)


def _open_gate(project: Any, name: str, cfg: dict, rel: dict, tested: dict, who: tuple[str, str]) -> dict[str, Any]:
    n, repo = rel["release"], registries.repository(cfg, project)
    card = Canon(project).card(
        "deploy_gate", f"Publish release {n} to {name}?", blocking=True,
        body=(f"Release {n} (revision {str(rel.get('revision'))[:12]}) was published to the test registry "
              f"{tested['registry']} as {tested['image']}. Approving pushes it to the production registry {name} as "
              f"{repo}. Refusing stops it. IT decides."),
        refs={"release": n, "registry": name},
        payload={"publish": {"registry": name, "kind": cfg["kind"], "repository": repo, "tested": tested.get("image"),
                             "digest": tested.get("digest")},
                 "release": n, "revision": rel.get("revision"), "road": name, "kind": cfg["kind"],
                 "artifact": tested.get("image"), "persona": "it"})
    _keep(project, {"registry": name, "release": n, "card": card["id"], "state": "waiting", "type": "container",
                    "environment": "production", "at": project.factory.clock.stamp(), "by": who[0], "persona": who[1]})
    return card


def _production(project: Any, name: str, cfg: dict, rel: dict, who: tuple[str, str]) -> dict[str, Any] | None:
    """Test first, then IT's deploy gate. None when the push may go; else the waiting result."""
    n = rel["release"]
    tested = _tested_first(project, name, rel, who)
    gates = [h for h in history(project) if h.get("registry") == name and h.get("release") == n and h.get("card")]
    card = Canon(project).get_card(gates[-1]["card"]) if gates else None
    if card is not None and card["state"] == "decided":
        if card["decision"]["verdict"] == "approve":
            return None
        _gate_refused(project, name, rel, card, gates, who)
    if card is None or card["state"] != "open":
        card = _open_gate(project, name, cfg, rel, tested, who)
    project.log("publish_waiting", {"registry": name, "release": n, "card": card["id"], "by": who[0],
                                    "persona": who[1]})
    return {"state": "waiting", "registry": name, "release": n, "waiting_on": card["id"],
            "why": f"IT's deploy gate {card['id']} decides a publish to production"}


def _source_image(project: Any, rel: dict, docker: DockerPublisher) -> str:
    """The release's image on this host: its road's, pulled when it lives in a registry, or built now."""
    from kernel.roads import checkout

    for art in (rel.get("artifacts") or {}).values():
        if isinstance(art, dict) and art.get("type") == "image" and art.get("ref"):
            if "@" in str(art["ref"]) or art.get("digest"):
                docker("pull", str(art["ref"]))
            return str(art["ref"])
    revision = str(rel.get("revision") or "")
    try:
        work = checkout(project, revision)
    except (RuntimeError, OSError) as exc:
        raise PublishFailed(f"release {rel['release']} has no image and its revision could not be checked out: "
                            f"{type(exc).__name__}") from None
    if not (work / "Dockerfile").exists():
        raise PublishFailed(f"release {rel['release']} has no image, and the product has no Dockerfile at "
                            f"{revision[:12]} to build one")
    tag = f"gf-{project.pid}:{revision[:12]}"
    docker("build", "--tag", tag, "--label", f"org.opencontainers.image.revision={revision}",
           "--label", f"gnomonfactory.project={project.pid}", str(work))
    return tag


def _push(project: Any, name: str, cfg: dict, rel: dict, who: tuple[str, str],
          environ: Mapping[str, str]) -> dict[str, Any]:
    docker = DockerPublisher(str(cfg.get("docker_cli") or "docker"), environ)
    n, tier = rel["release"], registries.tier(cfg)
    image = f"{registries.repository(cfg, project)}:r{n}-{str(rel.get('revision'))[:12]}"
    entry: dict[str, Any] = {"registry": name, "kind": cfg["kind"], "type": "container", "environment": tier,
                             "release": n, "revision": rel.get("revision"), "image": image, "by": who[0],
                             "persona": who[1]}
    try:
        source = _source_image(project, rel, docker)
        names = registries.login_names(cfg)
        if names is not None:
            docker("login", str(registries.host(cfg)), "--username", environ[names[0]], "--password-stdin",
                   stdin=environ[names[1]])
        docker("tag", source, image)
        digest = DIGEST.search(docker("push", image))
    except PublishFailed as exc:
        entry.update(state="failed", why=str(exc), at=project.factory.clock.stamp())
        _keep(project, entry)
        project.log("publish_failed", {k: entry[k] for k in ("registry", "environment", "release", "image", "why",
                                                             "by", "persona")})
        return {"state": "failed", **entry}
    entry.update(state="published", source=source, digest=digest.group(1) if digest else None,
                 at=project.factory.clock.stamp())
    entry = _keep(project, entry)
    project.log("published", {k: entry.get(k) for k in ("registry", "kind", "environment", "release", "revision",
                                                        "image", "digest", "by", "persona")})
    return {**entry}


# -- an MCP registry entry: a file a person submits -------------------------------------------------------

def mcp_entry(project: Any, name: str, cfg: dict, rel: dict, who: tuple[str, str]) -> dict[str, Any]:
    from kernel.faces import pack_runtime

    n = rel["release"]
    runtime = pack_runtime(project, rel.get("revision"))
    if not runtime.get("declared") or "mcp" not in runtime.get("faces", []):
        why = (f"release {n} offers no MCP face: its app/runtime.json "
               + ("does not list mcp under faces" if runtime.get("declared") else "is missing or not valid"))
        _refuse(project, name, rel, why, [why], who)
    image = next((h for h in reversed(history(project)) if h.get("release") == n and h.get("state") == "published"
                  and h.get("type") == "container"), None)
    server = f"{str(cfg['namespace']).strip('.')}/{runtime['name']}"
    doc: dict[str, Any] = {"$schema": MCP_SCHEMA, "name": server, "description": str(runtime["summary"])[:100],
                           "version": f"0.{n}.0"}
    if image is not None:
        doc["packages"] = [{"registryType": "oci", "identifier": image["image"], "transport": {"type": "stdio"}}]
    doc["_meta"] = {"io.rihmasto/capability": {"release": n, "revision": rel.get("revision"),
                                               "tools": [t["name"] for t in runtime.get("tools") or []],
                                               "declaration_sha256": runtime.get("declaration_sha256")}}
    where = f"publish/{n}/mcp-server.json"
    project.write(where, doc)
    steps = ["Check the file, then submit it yourself with the registry's publisher tool (mcp-publisher publish)."]
    if image is None:
        steps.insert(0, "No image of this release is published yet: publish it to a container registry first, "
                        "so the entry can name a package.")
    else:
        steps.append(f"The image needs the label io.modelcontextprotocol.server.name={server} for the registry to "
                     "accept it.")
    entry = _keep(project, {"registry": name, "kind": "mcp-registry", "type": "mcp-entry",
                            "environment": registries.tier(cfg), "release": n, "revision": rel.get("revision"),
                            "file": where, "server": server, "state": "written", "submitted": False,
                            "at": project.factory.clock.stamp(), "by": who[0], "persona": who[1]})
    project.log("mcp_entry_written", {"registry": name, "release": n, "file": where, "server": server,
                                      "by": who[0], "persona": who[1]})
    return {**entry, "manifest": doc, "next": steps}
