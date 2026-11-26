"""A project with something at every kind of destination (FR-DST1), and a fake docker on PATH.

`build(home)` makes a factory home with one project at maturity production:

- its product repository (a bare `repo.git`) holds a Dockerfile and an `app/runtime.json` that offers an MCP and
  an HTTP face, and release 1 of that revision is done;
- staging runs on a `local-process` road and production on a `gcp-cloudrun` road (its gcloud is the fake of
  tests/gcp_fakes.py on PATH); each environment's slot points at a small health server on 127.0.0.1, which a
  test can turn failing;
- the spec declares a Google Drive integration, bound on the staging road and not yet approved by IT;
- a website chat (embed) belongs to it, a Teams subscription of the relay carries its events, and release 1's
  MCP face was served once;
- `registries.json` names a test and a production container registry (GitHub's) and an MCP registry listing,
  with the login's variables by name only.

`FakeDocker(folder)` writes a docker program into ``folder`` (`docker.cmd` on Windows, `docker` elsewhere) that
records each call's arguments in `calls.jsonl`, never what it reads on its input (a login's token): only that it
read something. `push` answers a digest per image, unless the state says it fails. Nothing reaches a registry.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from gcp_fakes import FakeGcloud, road as gcp_road

from kernel.store import Factory, FixedClock, write_json

PERSON = ("Ilkka Example", "it")
TOKEN = "fixture-token-value-never-shown"
RUNTIME = {"format": "rihma.runtime/1", "name": "desk-helper", "kind": "agent", "summary": "Answers desk questions.",
           "trigger": {"kind": "manual"}, "faces": ["mcp", "http"],
           "tools": [{"name": "lookup_desk", "description": "Find a desk by its number.", "effect": "read"}]}
DRIVE = {"name": "recordings", "kind": "gdrive", "via": "http", "access": "read", "data_classes": ["internal"],
         "credentials": [], "provenance": "customer-confirmed"}
REGISTRIES = {"schema": "rihmasto.registries/1", "registries": {
    "ghcr-test": {"kind": "ghcr", "environment": "test", "configured": True, "owner": "IT: the platform team",
                  "namespace": "example-org/test", "login": {"username_env": "GHCR_USER", "password_env": "GHCR_TOKEN"}},
    "ghcr": {"kind": "ghcr", "environment": "production", "configured": True, "namespace": "example-org",
             "login": "existing"},
    "mcp-listing": {"kind": "mcp-registry", "environment": "production", "configured": True,
                    "namespace": "io.github.example-org"}}}

FAKE = r'''
import hashlib, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
state = json.loads((HERE / "state.json").read_text(encoding="utf-8"))
args = sys.argv[1:]
call = {"args": args}
if "--password-stdin" in args:
    call["stdin_read"] = bool(sys.stdin.read())
with open(HERE / "calls.jsonl", "a", encoding="utf-8") as fh:
    fh.write(json.dumps(call) + "\n")
verb = args[0] if args else ""
if verb in state.get("fail", []):
    print("denied: requested access to the resource is denied", file=sys.stderr)
    sys.exit(1)
if verb == "push":
    print("The push refers to repository [" + args[1].rsplit(":", 1)[0] + "]")
    print("r1: digest: sha256:" + hashlib.sha256(args[1].encode()).hexdigest() + " size: 528")
elif verb == "image":
    print("[]")
sys.exit(0)
'''


class FakeDocker:
    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "docker_fake.py").write_text(FAKE, encoding="utf-8")
        if os.name == "nt":
            (self.folder / "docker.cmd").write_text(f'@echo off\r\n"{sys.executable}" "%~dp0docker_fake.py" %*\r\n',
                                                    encoding="utf-8")
        else:
            script = self.folder / "docker"
            script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/docker_fake.py" "$@"\n',
                              encoding="utf-8")
            script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self.write({"fail": []})
        (self.folder / "calls.jsonl").write_text("", encoding="utf-8")

    def write(self, state: dict) -> None:
        (self.folder / "state.json").write_text(json.dumps(state), encoding="utf-8")

    def calls(self) -> list:
        text = (self.folder / "calls.jsonl").read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]


class _Health(BaseHTTPRequestHandler):
    def do_GET(self):
        env = self.path.strip("/").split("/")[0]
        answer = self.server.answers.get(env)
        status, body = (200, {"status": "ok", "version": answer}) if answer else (503, {"status": "down"})
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        return


class Health:
    """`/<env>/health` on 127.0.0.1: answers ok with a version, or 503 once a test turns it down."""

    def __init__(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Health)
        self.server.answers = {}
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def url(self, env: str) -> str:
        return f"{self.base}/{env}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


def write_routes(case, w: dict) -> list:
    """Destinations' write routes (FR-DST1) for the cockpit's completeness tables (tests/test_brief_ln.py,
    tests/test_access.py): each signed, each recorded. Deliver starts a job on the case's fake runner; the check
    probes nothing (no release runs there); publishing to a registry IT never named is refused, and recorded."""
    b = w["built"].pid

    def delivered(got: dict) -> str:
        """The delivery's job ends before the next write, so a later Advance on the project is not refused."""
        job = (got.get("post_destinations_deliver") or {}).get("job") or {}
        states = getattr(getattr(case, "runner", None), "states", None)
        if job.get("id") and isinstance(states, dict):
            states[job["id"]] = "done"
        return f"/api/projects/{b}/destinations/check"

    return [
        ("post_destinations_deliver", "POST", f"/api/projects/{b}/destinations/deliver",
         lambda who, got: {"to": "test", "person": who, "persona": "developer"}),
        ("post_destinations_check", "POST", delivered,
         lambda who, got: {"person": who, "persona": "operations"}),
        ("post_publish", "POST", f"/api/projects/{b}/publish",
         lambda who, got: {"registry": "ghcr-test", "person": who, "persona": "it"}),
    ]


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def _repo(project, work: Path) -> str:
    work.mkdir(parents=True, exist_ok=True)
    (work / "app").mkdir(exist_ok=True)
    (work / "app" / "runtime.json").write_text(json.dumps(RUNTIME, indent=1), encoding="utf-8")
    (work / "Dockerfile").write_text("FROM python:3.12-slim\nCOPY . /app\n", encoding="utf-8")
    _git(work, "init", "-q", "-b", "main")
    _git(work, "add", "-A")
    _git(work, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "desk helper")
    _git(work.parent, "clone", "-q", "--bare", str(work), str(project.path("repo.git")))
    return _git(work, "rev-parse", "HEAD")


def build(home: Path, health: Health, gcloud_dir: Path) -> dict:
    """The factory home and its one project; the fake gcloud's folder must be on PATH while it is used."""
    from kernel import embeds, relay

    FakeGcloud(gcloud_dir)
    factory = Factory(home, clock=FixedClock())
    project = factory.new_project("Desk helper", mode="assume", maturity="production")
    rev = _repo(project, home.parent / "work")
    spec = project.read("spec.json") or {}
    project.write("spec.json", {"title": "Desk helper", "requirements": [], **spec, "integrations": [DRIVE]})
    write_json(factory.paved_roads_path, {
        "schema": "gnomonfactory.paved_roads/1",
        "roads": {"local": {"kind": "local-process", "configured": True, "environments": ["staging"],
                            "integrations": {"recordings": {"endpoint": "https://www.googleapis.com"}}},
                  "gcp": gcp_road()},
        "maturity": {"production": {"staging": "local", "production": "gcp"}}})
    stamp = factory.clock.stamp()
    write_json(project.path("releases", "1.json"), {
        "release": 1, "project": project.pid, "maturity": "production", "state": "done", "revision": rev,
        "rev12": rev[:12], "plan": [], "steps": [], "cards": [], "artifacts": {
            "local": {"type": "process", "ref": f"repo.git@{rev}"}}, "created": stamp, "updated": stamp})
    for env, road, kind in (("staging", "local", "local-process"), ("production", "gcp", "gcp-cloudrun")):
        health.server.answers[env] = rev[:12]
        write_json(project.path("envs", env, "current.json"), {
            "road": road, "kind": kind, "environment": env, "slot": "current", "release": 1, "revision": rev,
            "rev12": rev[:12], "started": stamp, "base_url": health.url(env), "artifact": {"ref": rev},
            "package": {"integrations": []}})
    embeds.create(factory, kind="feedback", origins=["https://desk.example"], person=PERSON[0], persona=PERSON[1],
                  project_id=project.pid, label="Desk page")
    relay.subscribe(factory, sink="teams", url_env="DESK_TEAMS_URL", personas=["it"], projects=[project.pid],
                    person=PERSON[0], persona=PERSON[1])
    project.log("capability_served", {"by": "olli", "face": "mcp", "transport": "stdio", "release": 1,
                                      "revision": rev, "capability": "desk-helper"})
    write_json(home / "registries.json", REGISTRIES)
    return {"factory": factory, "project": project, "revision": rev}
