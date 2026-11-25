"""A fake gcloud on PATH, and the health of the services it "deploys", for the gcp-cloudrun road's tests.

`FakeGcloud(folder)` writes a small gcloud program into ``folder`` (`gcloud` on POSIX, `gcloud.cmd` on
Windows, both running `gcloud_fake.py` with this interpreter) and a `state.json` beside it. It answers what
the road asks, as gcloud would, from that state: the signed-in account, Cloud Build, `run services replace`
and `describe` (a URL per service and per tagged revision, served by `HealthServer` on 127.0.0.1),
`update-traffic`, `run jobs replace`, `execute --wait` (succeeding or failing as the state says), `executions
list`, `jobs update --image`, and Cloud Scheduler's `describe`, `create` and `update`. Every call is
appended to `calls.jsonl` (its arguments only). Nothing here reaches Google Cloud.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIGEST = "auto"     # a digest per image tag; None: the build reports none

FAKE = r'''
import hashlib, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, ROOT)
from kernel.roads import from_yaml  # noqa: E402

STATE = HERE / "state.json"


def load():
    return json.loads(STATE.read_text(encoding="utf-8"))


def save(state):
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def flag(args, name):
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def out(doc, code=0):
    print(json.dumps(doc))
    sys.exit(code)


def fail(message, code=1):
    print("ERROR: " + message, file=sys.stderr)
    sys.exit(code)


def services(state, args):
    verb = args[2]
    if verb == "replace":
        model = from_yaml(Path(args[3]).read_text(encoding="utf-8"))
        name = model["metadata"]["name"]
        svc = state["services"].setdefault(name, {"revisions": {}, "traffic": []})
        tpl = model["spec"]["template"]
        env = {e["name"]: e.get("value") for e in tpl["spec"]["containers"][0]["env"]}
        svc["revisions"][tpl["metadata"]["name"]] = {"image": tpl["spec"]["containers"][0]["image"],
                                                     "version": env.get("APP_VERSION")}
        svc["traffic"] = model["spec"]["traffic"]
        save(state)
        out(model)
    name = args[3]
    svc = state["services"].get(name)
    if svc is None:
        fail("service " + name + " not found")
    if verb == "describe":
        base = state["health_base"] + "/svc/" + name
        traffic = [dict(t, **({"url": base + "/tag/" + t["tag"]} if t.get("tag") else {})) for t in svc["traffic"]]
        out({"metadata": {"name": name}, "status": {"url": base, "traffic": traffic}})
    if verb == "update-traffic":
        tags = flag(args, "--remove-tags")
        to = flag(args, "--to-revisions")
        if tags:
            svc["traffic"] = [{k: v for k, v in t.items() if k != "tag"} for t in svc["traffic"] if t.get("percent")]
        if to:
            rev = to.split("=")[0]
            if rev not in svc["revisions"]:
                fail("revision " + rev + " not found")
            svc["traffic"] = [{"revisionName": rev, "percent": 100}]
        save(state)
        out({"status": {"traffic": svc["traffic"]}})
    fail("unknown run services command", 2)


def jobs(state, args):
    verb = args[2]
    if verb == "replace":
        model = from_yaml(Path(args[3]).read_text(encoding="utf-8"))
        name = model["metadata"]["name"]
        job = state["jobs"].setdefault(name, {"executions": []})
        job["image"] = model["spec"]["template"]["spec"]["template"]["spec"]["containers"][0]["image"]
        save(state)
        out(model)
    if verb == "executions":
        name = flag(args, "--job")
        out(list(reversed(state["jobs"].get(name, {}).get("executions", []))))
    name = args[3]
    job = state["jobs"].get(name)
    if job is None:
        fail("job " + name + " not found")
    if verb == "update":
        job["image"] = flag(args, "--image")
        save(state)
        out({"metadata": {"name": name}})
    if verb == "execute":
        ok = state.get("execute_outcome", "succeeded") == "succeeded"
        n = len(job["executions"]) + 1
        ex = {"metadata": {"name": name + "-x" + str(n)}, "status": {
            "conditions": [{"type": "Completed", "status": "True" if ok else "False",
                            "message": "" if ok else "Task failed with exit code 1"}],
            "succeededCount": 1 if ok else 0, "failedCount": 0 if ok else 1,
            "startTime": "2026-11-24T06:00:%02dZ" % n, "completionTime": "2026-11-24T06:01:%02dZ" % n}}
        job["executions"].append(ex)
        save(state)
        if not ok:
            fail("(gcloud.run.jobs.execute) The execution failed.")
        out(ex)
    fail("unknown run jobs command", 2)


def scheduler(state, args):
    verb = args[2]
    name = args[4] if verb in ("create", "update") else args[3]
    if verb == "describe":
        if name not in state["scheduler"]:
            fail("NOT_FOUND: Job not found.")
        out(state["scheduler"][name])
    if verb == "create" and name in state["scheduler"]:
        fail("ALREADY_EXISTS")
    if verb == "update" and name not in state["scheduler"]:
        fail("NOT_FOUND")
    state["scheduler"][name] = {k: flag(args, "--" + k) for k in (
        "schedule", "time-zone", "uri", "http-method", "oauth-service-account-email", "max-retry-attempts", "location")}
    save(state)
    out(state["scheduler"][name])


def main():
    args = sys.argv[1:]
    with open(HERE / "calls.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(args) + "\n")
    state = load()
    if args[:2] == ["auth", "list"]:
        if state.get("account"):
            print(state["account"])
        sys.exit(0)
    if args[:2] == ["auth", "login"]:
        sys.exit(0)
    if args[:2] == ["builds", "submit"]:
        digest = state.get("build_digest")
        if digest == "auto":     # each image its own digest, as a registry gives it
            digest = "sha256:" + hashlib.sha256(flag(args, "--tag").encode()).hexdigest()
        out({"results": {"images": [{"name": flag(args, "--tag"), "digest": digest}]}})
    if args[:2] == ["run", "services"]:
        services(state, args)
    if args[:2] == ["run", "jobs"]:
        jobs(state, args)
    if args[:2] == ["scheduler", "jobs"]:
        scheduler(state, args)
    fail("unknown command: " + " ".join(args[:3]), 2)


main()
'''


class FakeGcloud:
    """The fake gcloud program in ``folder``, its state and the calls it got."""

    def __init__(self, folder: Path, *, account: str | None = "deployer@example-ops-123.iam.gserviceaccount.com",
                 digest: str | None = DIGEST) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "gcloud_fake.py").write_text(f"ROOT = {str(ROOT)!r}\n" + FAKE, encoding="utf-8")
        if os.name == "nt":
            (self.folder / "gcloud.cmd").write_text(
                f'@echo off\r\n"{sys.executable}" "%~dp0gcloud_fake.py" %*\r\n', encoding="utf-8")
        else:
            script = self.folder / "gcloud"
            script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/gcloud_fake.py" "$@"\n',
                              encoding="utf-8")
            script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self.write({"account": account, "build_digest": digest, "health_base": "http://127.0.0.1:9",
                    "services": {}, "jobs": {}, "scheduler": {}, "execute_outcome": "succeeded"})
        (self.folder / "calls.jsonl").write_text("", encoding="utf-8")

    def state(self) -> dict:
        return json.loads((self.folder / "state.json").read_text(encoding="utf-8"))

    def write(self, state: dict) -> None:
        (self.folder / "state.json").write_text(json.dumps(state, indent=1), encoding="utf-8")

    def update(self, **changes) -> None:
        self.write(self.state() | changes)

    def calls(self) -> list:
        text = (self.folder / "calls.jsonl").read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def clear(self) -> None:
        (self.folder / "calls.jsonl").write_text("", encoding="utf-8")

    def path_env(self) -> dict:
        """PATH with this folder first, so `gcloud` is the fake."""
        return {"PATH": str(self.folder) + os.pathsep + os.environ.get("PATH", "")}

    def add_execution(self, job: str, ok: bool, n: int) -> None:
        state = self.state()
        state["jobs"].setdefault(job, {"executions": []})["executions"].append(
            {"metadata": {"name": f"{job}-s{n}"}, "status": {
                "conditions": [{"type": "Completed", "status": "True" if ok else "False",
                                "message": "" if ok else "Task failed with exit code 1"}],
                "succeededCount": int(ok), "failedCount": int(not ok),
                "startTime": f"2026-11-25T06:00:{n:02d}Z", "completionTime": f"2026-11-25T06:05:{n:02d}Z"}})
        self.write(state)


class _Health(BaseHTTPRequestHandler):
    """`/svc/<service>[/tag/<tag>]/health`, answering the version of the revision serving there now."""

    def do_GET(self):
        parts = self.path.strip("/").split("/")
        state = self.server.fake.state()
        svc = state["services"].get(parts[1]) if len(parts) > 2 and parts[0] == "svc" else None
        version = None
        if svc is not None:
            tag = parts[3] if len(parts) > 4 and parts[2] == "tag" else None
            live = [t for t in svc["traffic"] if (t.get("tag") == tag if tag else t.get("percent"))]
            if live:
                version = svc["revisions"].get(live[0]["revisionName"], {}).get("version")
        body = json.dumps({"status": "ok", "version": version} if version else {"error": "no such service"}).encode()
        self.send_response(200 if version else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


class HealthServer:
    """The services' URLs on 127.0.0.1, answering /health from the fake's state."""

    def __init__(self, fake: FakeGcloud) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Health)
        self.server.fake = fake
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        fake.update(health_base=f"http://127.0.0.1:{self.server.server_address[1]}")

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


def road(**changes) -> dict:
    """A whole gcp-cloudrun road entry with example identities, as IT writes one."""
    entry = {
        "kind": "gcp-cloudrun", "configured": True, "owner": "IT: the platform team",
        "environments": ["staging", "production"],
        "projects": {"staging": "example-test-123", "production": "example-prod-123"}, "region": "europe-north1",
        "repository": "europe-north1-docker.pkg.dev/example-build-123/rihmasto",
        "deployer": {"service_account": "deployer@example-ops-123.iam.gserviceaccount.com"},
        "runtime_service_account": "runtime@example-prod-123.iam.gserviceaccount.com",
        "network": {"ingress": "internal", "egress": "all-traffic", "vpc_connector": "rihmasto-connector"},
        "secrets": [{"name": "MODEL_API_KEY", "ref": "sm:model-api-key:3"}],
        "env": {"LOG_LEVEL": "info"},
        "rules": {"region": "europe-north1", "regions": ["europe-north1"], "tls": "required: Cloud Run serves HTTPS",
                  "egress": "none: all traffic through IT's VPC"},
        "canary": {"tolerance": 0.0, "min_sample": 3, "probe_rounds": 3}}
    entry.update(changes)
    return entry


SCHEDULE = {"cron": "0 6 * * 1-5", "time_zone": "Europe/Helsinki", "retries": 2,
            "service_account": "scheduler@example-prod-123.iam.gserviceaccount.com"}


def job_road(**changes) -> dict:
    entry = road(workload="job", schedule=dict(SCHEDULE), job={"max_retries": 1, "timeout_seconds": 1800,
                                                               "command": ["python3", "-m", "app.transcribe"]})
    entry.update(changes)
    return entry
