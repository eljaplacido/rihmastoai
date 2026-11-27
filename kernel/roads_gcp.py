"""The `gcp-cloudrun` paved road: a product on Google Cloud Run, as a service or a scheduled job (FR-GCP1).

IT configures the road (kernel/roads_gcp_config.py says what an entry holds; docs/guides/gcp.md is the
guide). The road renders, for each deploy package, the exact YAML and gcloud commands and validates them
before anything runs, and it runs them only when IT marked the road configured, its entry is whole, and
the `gcloud` CLI is on PATH and signed in on the deploying host. Otherwise `missing` says what is missing.

- **service**: a Cloud Run service (`service.yaml`, serving.knative.dev/v1). Each release is one revision,
  named for its release and revision. A production candidate is that revision with no traffic and the tag
  `candidate` (its own URL), beside the current one; promotion sends it all the traffic; rollback sends
  the traffic back to the previous revision. Probes and the smoke check read `/health` over HTTPS.
- **job**: a Cloud Run job (`job.yaml`, run.googleapis.com/v1) that Cloud Scheduler runs on a cron
  schedule with retries, by default in production only. In the test environment the smoke check
  executes it once and reads the execution; promotion updates the production job's image and keeps the
  previous image for rollback; probes read the last executions (kernel/roads_gcp_ops.py).

Every image is built by Cloud Build into IT's Artifact Registry repository and pinned by its digest when
the build reports one. Secrets come from Secret Manager by name (`sm:<secret>[:<version>]`): the YAML says
which secret and version, never a value. Plain settings are given by name and value. Nothing here is
tested against a real Google Cloud project: the tests run it against a fake gcloud on PATH.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

from kernel import roads_gcp_config as gc
from kernel.roads import (
    APP_PORT,
    CONTAINER_DATA,
    Road,
    RoadError,
    _clear_slot,
    _save_slot,
    azure_app_name,
    checkout,
    slot_path,
    slot_state,
    to_yaml,
    wait_healthy,
)
from kernel.store import read_json, write_json, write_text

KIND = gc.KIND
CANDIDATE_TAG = "candidate"
IMPERSONATE = "--impersonate-service-account="


class GcloudCLI:
    """The gcloud CLI on the deploying host, found on PATH when it is called. What it prints is handed back
    to the road and kept in the release record only as the road reads it; nothing here logs it."""

    def __init__(self, binary: str = "gcloud", timeout: float = 1800) -> None:
        self.binary, self.timeout = binary, timeout

    def path(self) -> str | None:
        return shutil.which(self.binary)

    def available(self) -> bool:
        return self.path() is not None

    def run(self, argv: list[str], *, check: bool = True, timeout: float | None = None) -> tuple[int, str]:
        exe = self.path()
        if exe is None:
            raise RoadError("the gcloud CLI is not on PATH on the deploying host", {"argv": argv})
        try:
            proc = subprocess.run([exe, *argv[1:]], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout or self.timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise RoadError(f"{' '.join(argv[:4])} did not finish in {timeout or self.timeout}s",
                            {"argv": argv}) from None
        except OSError as exc:
            raise RoadError(f"gcloud could not be started: {type(exc).__name__}", {"argv": argv}) from None
        if check and proc.returncode != 0:
            raise RoadError(f"{' '.join(argv[:4])} failed (exit {proc.returncode})",
                            {"argv": argv, "exit": proc.returncode, "stderr": (proc.stderr or "")[-2000:]})
        return proc.returncode, proc.stdout or ""

    def json(self, argv: list[str], *, timeout: float | None = None) -> Any:
        _, out = self.run(argv, timeout=timeout)
        try:
            return json.loads(out) if out.strip() else None
        except json.JSONDecodeError:
            raise RoadError(f"{' '.join(argv[:4])} did not answer JSON", {"argv": argv, "output": out[-500:]}) from None

    def account(self) -> str | None:
        """The account gcloud is signed in as on this host, or None."""
        code, out = self.run(["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"],
                             check=False, timeout=60)
        lines = [x.strip() for x in out.splitlines() if x.strip()]
        return lines[0] if code == 0 and lines else None


def resource_name(pid: str, env: str) -> str:
    """The service or job name in an environment: a short project id and the environment's code."""
    return azure_app_name(pid, env, "current")


class GcpCloudRunRoad(Road):
    """A product on Cloud Run: rendered and validated always, deployed only when the road is ready."""

    kind = KIND

    def __init__(self, name: str, cfg: dict, gcloud: GcloudCLI | None = None) -> None:
        super().__init__(name, cfg)
        self.gcloud = gcloud or GcloudCLI(cfg.get("gcloud_cli", "gcloud"))

    def missing(self) -> list:
        out = [f"road {self.name!r}: {p}" for p in gc.config_problems(self.cfg)]
        if not self.gcloud.available():
            return out + ["the gcloud CLI is not on PATH on the deploying host"]
        if "credential_file" not in (self.cfg.get("deployer") or {}) and self.gcloud.account() is None:
            out.append("gcloud is not signed in on the deploying host (gcloud auth list shows no active account)")
        return out

    def workload(self, project: Any) -> str:
        return str(gc.effective(self.cfg, project.meta).get("workload", "service"))

    def settings(self, project: Any, env: str, slot: str, revision: str) -> dict:
        out = super().settings(project, env, slot, revision)
        out.pop("PORT", None)   # Cloud Run sets PORT from the container port itself
        return out

    def image(self, project: Any, revision: str) -> str:
        return f"{self.cfg.get('repository') or '<repository>'}/gf-{project.pid}:{revision[:12]}"

    def target(self, project: Any, env: str, slot: str, release: int, revision: str, artifact: dict) -> dict:
        cfg = gc.effective(self.cfg, project.meta)
        name, workload = resource_name(project.pid, env), cfg.get("workload", "service")
        schedule = cfg.get("schedule") if workload == "job" else None
        current = slot_state(project, env, "current") or {}
        return {
            "workload": workload, "project_id": gc.project_for(cfg, env), "region": cfg.get("region"),
            "name": name, "revision_name": f"{name}-r{release}-{revision[:7]}",
            "previous_revision": current.get("revision_name") if slot == "candidate" else None,
            "runtime_service_account": cfg.get("runtime_service_account"), "repository": cfg.get("repository"),
            "deployer": dict(cfg.get("deployer") or {}), "network": dict(cfg.get("network") or {}),
            "resources": dict(cfg.get("resources") or {}), "env": gc.env_for(cfg, env),
            "data_bucket": cfg.get("data_bucket") if slot == "current" else None,
            "job": dict(cfg.get("job") or {}) if workload == "job" else None,
            "schedule": dict(schedule) if isinstance(schedule, dict) and env in schedule.get(
                "environments", ["production"]) else None,
            "yaml": f"releases/{release}/cloudrun-{workload}-{env}-{slot}.yaml",
            "labels": {"gnomonfactory-project": project.pid, "gnomonfactory-env": env,
                       "gnomonfactory-release": str(release)}}

    def render(self, project: Any, pkg: dict) -> None:
        pkg["rendered"] = render(pkg)

    # -- running it --------------------------------------------------------------------------------

    def _ready(self, project: Any, pkg: dict | None = None) -> None:
        missing = self.missing()
        if missing:
            raise RoadError("the Google Cloud road is not ready: " + "; ".join(missing), {"missing": missing})
        if pkg is not None:
            from kernel.roads import validate_package

            self.render(project, pkg)        # with every setting the package holds now
            problems = validate_package(pkg)
            if problems:
                raise RoadError("the deploy package is not valid: " + "; ".join(problems), {"problems": problems})

    def _login(self, cmds: dict) -> None:
        if cmds.get("login"):
            self.gcloud.run(cmds["login"], timeout=120)

    def build(self, project: Any, revision: str) -> dict:
        self._ready(project)
        work = checkout(project, revision)
        image = self.image(project, revision)
        cmds = commands(self.cfg, {"image": image, "checkout": str(work)})
        self._login(cmds)
        out = self.gcloud.json(cmds["build"], timeout=3600) or {}
        images = ((out.get("results") or {}).get("images") or []) if isinstance(out, dict) else []
        digest = next((i.get("digest") for i in images if isinstance(i, dict)
                       and str(i.get("name", "")).split("@")[0] in (image, image.rsplit(":", 1)[0])), None)
        art = {"type": "image", "ref": image}
        return art | {"digest": digest} if digest and re.fullmatch(r"sha256:[0-9a-f]{64}", str(digest)) else art

    def deploy(self, project: Any, package: dict) -> dict:
        self._ready(project, package)
        t, cmds = package["target"], package["rendered"]["commands"]
        path = project.dir / t["yaml"]
        write_text(path, package["rendered"]["yaml"])
        self._login(cmds)
        self.gcloud.run([str(path) if a == "<yaml>" else a for a in cmds["deploy"]], timeout=1800)
        previous = slot_state(project, package["environment"], "current")
        if t["workload"] == "job":
            state = self._deployed_job(project, package)
        else:
            state = self._deployed_service(project, package)
        if package["slot"] == "current" and previous and previous.get("revision") != package["revision"]:
            write_json(slot_path(project, package["environment"], "previous"), previous)
        return state

    def _deployed_service(self, project: Any, package: dict) -> dict:
        t, cmds = package["target"], package["rendered"]["commands"]
        described = self.gcloud.json(cmds["describe"], timeout=300) or {}
        status = described.get("status") or {} if isinstance(described, dict) else {}
        url = status.get("url")
        if package["slot"] == "candidate":
            url = next((x.get("url") for x in status.get("traffic") or [] if x.get("tag") == CANDIDATE_TAG), None)
        if not url:
            raise RoadError(f"Cloud Run gave no URL for {t['name']} ({package['slot']})", {"status": status})
        state = self._state(project, package, workload="service", service=t["name"], revision_name=t["revision_name"],
                            project_id=t["project_id"], region=t["region"], base_url=str(url).rstrip("/"))
        _save_slot(project, state)
        state["health"] = wait_healthy(state["base_url"], version=package["revision"][:12],
                                       timeout=float(self.cfg.get("start_timeout", 600)))
        _save_slot(project, state)
        return state

    def _deployed_job(self, project: Any, package: dict) -> dict:
        t, cmds = package["target"], package["rendered"]["commands"]
        scheduled = None
        if t.get("schedule"):
            exists = self.gcloud.run(cmds["scheduler_describe"], check=False, timeout=120)[0] == 0
            self.gcloud.run(cmds["scheduler_update" if exists else "scheduler_create"], timeout=300)
            scheduled = {k: t["schedule"].get(k) for k in ("cron", "time_zone", "retries")} | {
                "scheduler_job": package["rendered"]["scheduler"]["name"], "updated": exists}
        image = package["rendered"]["model"]["spec"]["template"]["spec"]["template"]["spec"]["containers"][0]["image"]
        # A job has no URL to probe (base_url None); people follow its executions in the Cloud console.
        console = (f"https://console.cloud.google.com/run/jobs/details/{t['region']}/{t['name']}/executions"
                   f"?project={t['project_id']}")
        state = self._state(project, package, workload="job", job=t["name"], image=image, schedule=scheduled,
                            project_id=t["project_id"], region=t["region"], base_url=None, console=console)
        _save_slot(project, state)
        return state

    def stop(self, project: Any, env: str, slot: str) -> dict | None:
        state = slot_state(project, env, slot)
        if state and slot == "candidate" and state.get("workload") == "service":
            self.gcloud.run(state["package"]["rendered"]["commands"]["untag"], check=False, timeout=300)
        _clear_slot(project, env, slot)
        return state

    def delivery_step(self, delivery: Any, name: str, env: str) -> dict | None:
        """A job's own delivery steps (kernel/roads_gcp_ops.py); None leaves a service's to delivery."""
        if self.workload(delivery.project) != "job":
            return None
        from kernel.roads_gcp_ops import job_step

        return job_step(self, delivery, name, env)

    def previous(self, project: Any, env: str) -> dict | None:
        return read_json(slot_path(project, env, "previous"))


# -- rendering: a pure function of the package -------------------------------------------------------

def _flags(cfg_or_target: dict, pid: str | None, region: str | None) -> list[str]:
    deployer = cfg_or_target.get("deployer") or {}
    out = (["--project", pid or "<project>"] if pid is not None else []) + (
        ["--region", region or "<region>"] if region is not None else [])
    return out + ([IMPERSONATE + deployer["service_account"]] if deployer.get("service_account") else [])


def commands(cfg: dict, build: dict | None = None, t: dict | None = None, scheduler: dict | None = None) -> dict:
    """The exact gcloud commands: the login and the build from the road's entry; the deploy, the describe,
    the traffic moves, the executions and the schedule from a package's target."""
    deployer = cfg.get("deployer") or {}
    out: dict[str, list[str]] = {}
    if deployer.get("credential_file"):
        out["login"] = ["gcloud", "auth", "login", f"--cred-file={deployer['credential_file']}", "--quiet"]
    if build:
        repo = gc.REPOSITORY.match(str(cfg.get("repository", "")))
        out["build"] = ["gcloud", "builds", "submit", build["checkout"], "--tag", build["image"],
                        *_flags(cfg, repo.group("project") if repo else "<project>", None), "--format=json"]
    if t:
        out.update(_target_commands(t, scheduler))
    return out


def _target_commands(t: dict, scheduler: dict | None) -> dict:
    where = _flags(t, t["project_id"], t["region"])
    name = t["name"]
    if t["workload"] == "service":
        out = {"deploy": ["gcloud", "run", "services", "replace", "<yaml>", *where, "--format=json"],
               "describe": ["gcloud", "run", "services", "describe", name, *where, "--format=json"],
               "untag": ["gcloud", "run", "services", "update-traffic", name, "--remove-tags", CANDIDATE_TAG, *where],
               # a rollback: all traffic back to the revision that served before
               "traffic_to": ["gcloud", "run", "services", "update-traffic", name, "--to-revisions",
                              "<revision>=100", *where]}
        return out
    out = {"deploy": ["gcloud", "run", "jobs", "replace", "<yaml>", *where, "--format=json"],
           "execute": ["gcloud", "run", "jobs", "execute", name, "--wait", *where, "--format=json"],
           "executions": ["gcloud", "run", "jobs", "executions", "list", "--job", name, *where, "--limit", "5",
                          "--format=json"],
           "rollback_image": ["gcloud", "run", "jobs", "update", name, "--image", "<previous image>", *where]}
    if scheduler:
        loc = ["--location", t["region"] or "<region>", *_flags(t, t["project_id"], None)]
        s = scheduler
        flags = ["--schedule", s["schedule"], "--time-zone", s["timeZone"], "--uri", s["httpTarget"]["uri"],
                 "--http-method", "POST", "--oauth-service-account-email",
                 s["httpTarget"]["oauthToken"]["serviceAccountEmail"], "--max-retry-attempts",
                 str(s["retryConfig"]["retryCount"])]
        out |= {"scheduler_describe": ["gcloud", "scheduler", "jobs", "describe", s["name"], *loc, "--format=json"],
                "scheduler_create": ["gcloud", "scheduler", "jobs", "create", "http", s["name"], *loc, *flags],
                "scheduler_update": ["gcloud", "scheduler", "jobs", "update", "http", s["name"], *loc, *flags]}
    return out


def _image(art: dict) -> str:
    ref, digest = str(art.get("ref", "")), art.get("digest")
    return f"{ref.rsplit(':', 1)[0]}@{digest}" if digest and not ref.endswith(f"@{digest}") else ref


def _env(pkg: dict) -> list[dict]:
    t = pkg["target"]
    plain = {k: str(v) for k, v in pkg["settings"].items() if k not in gc.RESERVED_ENV}
    plain |= {k: str(v) for k, v in (t.get("env") or {}).items() if k not in plain}
    out: list[dict] = [{"name": k, "value": v} for k, v in plain.items()]
    for s in pkg.get("secrets") or []:     # a ref that is not Secret Manager's is rendered so validation names it
        ref = gc.secret_ref(s.get("ref")) or {"name": "<not a Secret Manager reference>", "key": "?"}
        out.append({"name": str(s.get("name")), "valueFrom": {"secretKeyRef": ref}})
    return out


def _container(pkg: dict) -> dict:
    t = pkg["target"]
    res = t.get("resources") or {}
    c: dict[str, Any] = {"image": _image(pkg["artifact"]), "env": _env(pkg),
                         "resources": {"limits": {"cpu": str(res.get("cpu", "1")),
                                                  "memory": str(res.get("memory", "512Mi"))}}}
    if t.get("data_bucket"):
        c["volumeMounts"] = [{"name": "data", "mountPath": CONTAINER_DATA}]
    return c


def _template_annotations(t: dict) -> dict:
    net, out = t.get("network") or {}, {}
    if net.get("vpc_connector"):
        out["run.googleapis.com/vpc-access-connector"] = str(net["vpc_connector"])
    elif net.get("vpc_network"):
        out["run.googleapis.com/network-interfaces"] = json.dumps(
            [{"network": net["vpc_network"], "subnetwork": net.get("vpc_subnet") or net["vpc_network"]}])
    if net.get("egress"):
        out["run.googleapis.com/vpc-access-egress"] = str(net["egress"])
    if t.get("data_bucket"):
        out["run.googleapis.com/execution-environment"] = "gen2"
    return out


def _volumes(t: dict) -> list:
    """The current slot's data on a Cloud Storage bucket IT names (`data_bucket`), mounted at /data."""
    if not t.get("data_bucket"):
        return []
    return [{"name": "data", "csi": {"driver": "gcsfuse.run.googleapis.com",
                                     "volumeAttributes": {"bucketName": t["data_bucket"]}}}]


def service_model(pkg: dict) -> dict:
    t = pkg["target"]
    container = _container(pkg) | {"ports": [{"name": "http1", "containerPort": APP_PORT}],
                                   "startupProbe": {"httpGet": {"path": "/health", "port": APP_PORT}},
                                   "livenessProbe": {"httpGet": {"path": "/health", "port": APP_PORT}}}
    spec: dict[str, Any] = {"serviceAccountName": t["runtime_service_account"], "containerConcurrency": 80,
                            "timeoutSeconds": 300, "containers": [container]}
    if _volumes(t):
        spec["volumes"] = _volumes(t)
    rev, prev = t["revision_name"], t.get("previous_revision")
    if pkg["slot"] == "candidate":
        traffic = ([{"revisionName": prev, "percent": 100}] if prev else []) + [
            {"revisionName": rev, "percent": 0 if prev else 100, "tag": CANDIDATE_TAG}]
    else:
        traffic = [{"revisionName": rev, "percent": 100}]
    return {"apiVersion": "serving.knative.dev/v1", "kind": "Service",
            "metadata": {"name": t["name"], "labels": dict(t["labels"]),
                         "annotations": {"run.googleapis.com/ingress": (t.get("network") or {}).get("ingress",
                                                                                                  "internal")}},
            "spec": {"template": {"metadata": {"name": rev, "labels": dict(t["labels"]), "annotations": {
                # one instance: the paved-road product keeps its data in files with one writer
                "autoscaling.knative.dev/maxScale": "1", **_template_annotations(t)}}, "spec": spec},
                "traffic": traffic}}


def job_model(pkg: dict) -> dict:
    t = pkg["target"]
    job = t.get("job") or {}
    container = _container(pkg)
    command = list(job.get("command") or gc.DEFAULT_JOB_COMMAND)
    container |= {"command": command[:1], "args": command[1:]}
    spec: dict[str, Any] = {"serviceAccountName": t["runtime_service_account"],
                            "maxRetries": int(job.get("max_retries", 1)),
                            "timeoutSeconds": str(int(job.get("timeout_seconds", 3600))), "containers": [container]}
    if _volumes(t):
        spec["volumes"] = _volumes(t)
    return {"apiVersion": "run.googleapis.com/v1", "kind": "Job",
            "metadata": {"name": t["name"], "labels": dict(t["labels"])},
            "spec": {"template": {"metadata": {"labels": dict(t["labels"]), "annotations": _template_annotations(t)},
                                  "spec": {"parallelism": 1, "taskCount": 1, "template": {"spec": spec}}}}}


def scheduler_model(t: dict) -> dict | None:
    """The Cloud Scheduler job that runs the Cloud Run job on its schedule, through the Run API as the
    scheduler's service account."""
    s = t.get("schedule")
    if not s:
        return None
    uri = (f"https://{t['region']}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/{t['project_id']}"
           f"/jobs/{t['name']}:run")
    return {"name": f"{t['name']}-schedule", "location": t["region"], "schedule": s.get("cron"),
            "timeZone": s.get("time_zone"), "retryConfig": {"retryCount": int(s.get("retries", 0) or 0)},
            "httpTarget": {"uri": uri, "httpMethod": "POST",
                           "oauthToken": {"serviceAccountEmail": s.get("service_account")}}}


def render(pkg: dict) -> dict:
    """The package's Cloud Run YAML, its Cloud Scheduler job and the gcloud commands, from the package alone."""
    t = pkg["target"]
    model = job_model(pkg) if t["workload"] == "job" else service_model(pkg)
    scheduler = scheduler_model(t) if t["workload"] == "job" else None
    return {"format": f"cloudrun-{t['workload']}-yaml", "workload": t["workload"], "model": model,
            "yaml": to_yaml(model), "scheduler": scheduler, "commands": commands(t, None, t, scheduler),
            # Egress is enforced by IT on the VPC the road names; the package carries the rule so the deploy
            # gate shows it beside the service or job.
            "egress": (pkg.get("rules") or {}).get("egress")}


def validate_cloudrun(pkg: dict) -> list:
    """What is wrong with a gcp-cloudrun package's rendering; empty means it may be deployed."""
    from kernel.roads_gcp_check import check_rendered

    return check_rendered(pkg, render)
