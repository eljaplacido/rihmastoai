"""Small capabilities on the factory's side (FR-SC2, FR-SC5): the runtime a capability pack declares, and
`rihmasto capability`, which serves a delivered capability on this machine (docs/guides/small-capabilities.md).

    rihmasto capability check <pid> [--release N]
    rihmasto capability serve <pid> --face mcp [--port N] [--release N] [--schedule]
    rihmasto capability serve <pid> --face openai|http|embed --port N [--release N] [--schedule]

`check` judges the runtime declaration (`app/runtime.json`) at a release's revision, as the pack carries
it, and writes nothing. `serve` runs a delivered release (the latest, or --release N) from a clean
checkout of its revision, in this process (which serves and does nothing else from then on), with its
capability pack and a fresh status document beside it, so the pack
guard checks the pack's hash, the file trees, the status and the smoke set before any face answers: a pack
whose acceptance does not hold, or a withdrawn version, keeps every face at 503. It listens on 127.0.0.1
only; MCP is served over stdio unless --port is given. Each serve is recorded in the project's ledger
(`capability_served`): who asked (the local user), what the pack's status decided and on whose word, what
was assumed, and the pack and declaration hashes that prove what ran.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from typing import Any

from kernel import runtime_decl
from kernel.store import Factory, Project

Args = argparse.Namespace
RUNTIME_FILE = "app/runtime.json"
NOT_DECLARED = {"declared": False, "note": "the product template does not declare runtime models yet"}
LOOPBACK = "127.0.0.1"
# What the faces process never inherits: the pack it is given is the release's, nothing else narrows it,
# and only --schedule starts the schedule (a shell's RIHMA_SCHEDULE=on would run it unasked and unrecorded).
_NOT_INHERITED = ("DATA_DIR", "APP_VERSION", "PORT", "HOST", "RIHMA_FACES", "RIHMA_PACK", "RIHMA_PACK_SHA256",
                  "RIHMA_PACK_STATUS", "RIHMA_IMAGE_DIGEST", "TRAFFIC_LOG", "RIHMA_SCHEDULE")


def read_declaration(project: Project, revision: str) -> Any:
    """`app/runtime.json` at ``revision``; None when the product has none (a web-service product)."""
    from kernel.lanes import _git

    try:
        text = _git(project.path("repo.git"), "show", f"{revision}:{RUNTIME_FILE}")
    except (RuntimeError, OSError):   # no such file at the revision, or no product repository at all
        return None
    try:
        return json.loads(text)
    except ValueError:
        return f"{RUNTIME_FILE} is not JSON"


def pack_runtime(project: Project, revision: Any) -> dict:
    """The pack's `runtime`: what the declaration at the release's revision says the capability needs
    (kernel/runtime_decl.py `for_pack`), or that the product declares none."""
    decl = read_declaration(project, str(revision)) if revision else None
    return dict(NOT_DECLARED) if decl is None else runtime_decl.for_pack(decl)


def _release(project: Project, number: int | None) -> dict:
    from kernel.deliver import releases

    found = [r for r in releases(project) if number is None or r.get("release") == number]
    if not found:
        raise LookupError(f"{project.pid} has no release {number}" if number else
                          f"{project.pid} has no release yet: deliver it first (rihmasto deliver {project.pid})")
    return found[-1]


def check(project: Project, release: int | None = None) -> dict:
    """The runtime declaration at a release, judged as the pack judges it. Reads only."""
    rel = _release(project, release)
    return {"project": project.pid, "release": rel["release"], "revision": rel.get("revision"),
            "runtime": pack_runtime(project, rel.get("revision"))}


def _command(face: str, port: int | None, schedule: bool) -> list[str]:
    if port is None and face != "mcp":
        raise ValueError(f"the {face} face is served over HTTP: give --port (0 takes a free one)")
    argv = [sys.executable, "factory/faces.py", "--face", face]
    argv += ["--stdio"] if port is None else ["--port", str(port), "--host", LOOPBACK]
    return argv + (["--schedule"] if schedule else [])


def plan(project: Project, *, face: str, release: int | None = None, port: int | None = None,
         schedule: bool = False) -> dict:
    """What `serve` starts: the faces process (its command, folder and environment), with the release's
    pack and a status document written beside it for the guard. Builds the pack as `rihmasto pack` does."""
    from kernel.bundle import status_document
    from kernel.packs import build_pack
    from kernel.roads import checkout

    rel = _release(project, release)
    runtime = pack_runtime(project, rel.get("revision"))    # judged first: a refusal writes nothing
    if not runtime.get("declared"):
        why = "; ".join(runtime.get("problems") or [runtime.get("note", "")])
        raise ValueError(f"release {rel['release']} declares no runtime, so it has no faces: {why}")
    if face not in runtime["faces"]:
        raise ValueError(f"{runtime['name']} offers no {face} face; it offers {', '.join(runtime['faces'])}")
    argv = _command(face, port, schedule)
    pack = build_pack(project, rel["release"])
    site = f"capability/{rel['release']}"
    status = status_document(project, pack)
    project.write(f"{site}/capability-pack.json", pack)
    project.write(f"{site}/pack-status.json", status)
    env = {k: v for k, v in os.environ.items() if k not in _NOT_INHERITED}
    env.update(DATA_DIR=str(project.path("capability", "data")), APP_VERSION=str(rel.get("revision"))[:12],
               RIHMA_PACK=str(project.path(site, "capability-pack.json")), RIHMA_PACK_SHA256=pack["content_sha256"],
               RIHMA_PACK_STATUS=str(project.path(site, "pack-status.json")), PYTHONUNBUFFERED="1",
               PYTHONDONTWRITEBYTECODE="1")
    return {"argv": argv, "cwd": str(checkout(project, str(rel.get("revision")))), "env": env, "face": face,
            "port": port, "release": rel["release"], "revision": rel.get("revision"), "pack": pack, "status": status}


def assumptions(info: dict) -> list[str]:
    """What a serve assumes, said so: who can reach it and which of its secrets this environment lacks."""
    env, runtime = info["env"], info["pack"]["runtime"]
    out = [f"it listens on {LOOPBACK} only: only processes on this machine reach it"
           if info["port"] is not None else "MCP over stdio: only the process that started it reaches it"]
    if not env.get("RIHMA_FACES_TOKEN") and info["face"] != "embed":
        out.append("no RIHMA_FACES_TOKEN is set: the face asks no bearer token")
    missing = [name for name in runtime.get("secrets") or [] if not env.get(name)]
    if missing:
        out.append("these declared secrets are not set here, so a run that needs one fails: " + ", ".join(missing))
    return out


def record_served(project: Project, info: dict, by: str) -> dict:
    """The ledger's trace of a serve: who asked, what decided it may answer, what was assumed, what proves it."""
    pack, status, runtime = info["pack"], info["status"], info["pack"]["runtime"]
    payload = {"by": by, "face": info["face"], "transport": "stdio" if info["port"] is None else "http",
               "release": info["release"], "revision": info["revision"], "capability": runtime["name"],
               "schedule": "--schedule" in info["argv"] and (runtime.get("trigger") or {}).get("kind") == "schedule",
               "decided": {"pack_status": status["state"], "reason": status["reason"],
                           "by": status.get("decided_by") or "the pack's acceptance (the gate's evidence)"},
               "assumed": assumptions(info),
               "proof": {"pack_version": pack["version"], "pack_sha256": pack["content_sha256"],
                         "declaration_sha256": runtime["declaration_sha256"]}}
    project.log("capability_served", payload)
    return payload


def run_faces(info: dict) -> int:
    """The faces of the checkout, in this process (it serves and nothing else from here on): its folder,
    environment and arguments as `plan` gave them. Returns when stdio's input closes, or on Ctrl+C."""
    import importlib

    for name in _NOT_INHERITED:
        os.environ.pop(name, None)
    os.environ.update(info["env"])
    sys.dont_write_bytecode = True
    os.chdir(info["cwd"])
    sys.path.insert(0, info["cwd"])
    try:
        return int(importlib.import_module("factory.faces").main(info["argv"][2:]) or 0)
    except KeyboardInterrupt:
        return 0


def serve(factory: Factory, args: Args) -> int:
    """Serve until the faces stop (stdio: when its input closes) or Ctrl+C. Stdout is the protocol's (MCP
    over stdio) or the faces' listening line; what this command says goes to stderr."""
    from kernel.osuser import os_user

    project = factory.project(args.pid)
    info = plan(project, face=args.face, release=args.release, port=args.port, schedule=args.schedule)
    trace = record_served(project, info, f"local:{os_user()}")
    note = {"serving": info["face"], "release": info["release"], "pack": trace["proof"]["pack_version"],
            "pack_status": info["status"]["state"], "assumed": trace["assumed"],
            "by_hand": " ".join(info["argv"][1:]) + f"   (in {info['cwd']})"}
    sys.stderr.write(json.dumps(note, ensure_ascii=False) + "\n")
    sys.stderr.flush()
    return run_faces(info)


def add_parsers(sub: Any) -> None:
    """`rihmasto capability check|serve`, as the command line's parser adds them."""
    group = sub.add_parser("capability", help="small capabilities: their runtime and their faces (kernel/faces.py)")
    cmds = group.add_subparsers(dest="sub", required=True)
    p = cmds.add_parser("check", help="the runtime declaration at a release, as the pack judges it; writes nothing")
    p.add_argument("pid")
    p.add_argument("--release", type=int, help="the release (default: the latest)")
    p = cmds.add_parser("serve", help="serve a delivered capability on 127.0.0.1, checked by its pack guard")
    p.add_argument("pid")
    p.add_argument("--face", required=True, choices=runtime_decl.FACES)
    p.add_argument("--port", type=int, help="serve HTTP on this port (0: a free one); MCP without it is stdio")
    p.add_argument("--release", type=int, help="the release (default: the latest)")
    p.add_argument("--schedule", action="store_true", help="also run on the declared schedule while it serves")


def handlers(show: Callable[[Any], None]) -> dict[str, Callable[[Factory, Args], int | None]]:
    """The `rihmasto capability` handlers; `check` exits 1 when the release declares no valid runtime."""
    def checked(f: Factory, a: Args) -> int:
        out = check(f.project(a.pid), a.release)
        show(out)
        return 0 if out["runtime"].get("declared") else 1

    return {"capability check": checked, "capability serve": serve}
