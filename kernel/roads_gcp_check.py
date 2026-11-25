"""The checks a `gcp-cloudrun` deploy package passes before anything runs (FR-GCP1-AC-2).

`check_rendered` reads the package's rendered YAML back, renders the package again and compares, so a
rendering made before the package changed (or edited by hand) is refused, and then checks what the road
promises: names Cloud Run takes, the region the road allows, one instance with one writer, the product's
port and `/health`, the runtime service account, an image pinned to the release, every setting with exactly
one of a value or a Secret Manager reference and never a secret's value, a schedule Cloud Scheduler takes
and that calls this job, and an egress rule. No check calls Google Cloud.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from kernel import roads_gcp_config as gc
from kernel.roads import APP_PORT, SECRET_NAME, from_yaml

NAME = re.compile(r"[a-z](?:[-a-z0-9]{0,47}[a-z0-9])?\Z")
REVISION = re.compile(r"[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?\Z")
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}\Z")
SECRET_KEY = re.compile(r"(?:projects/[a-z0-9-]{1,30}/secrets/)?[A-Za-z0-9_-]{1,255}\Z")


def _read_back(rendered: dict[str, Any], fresh: dict[str, Any]) -> list[str]:
    model, text = rendered.get("model"), rendered.get("yaml")
    if not isinstance(model, dict) or not isinstance(text, str):
        return ["the Cloud Run package has no rendered model and YAML"]
    try:
        if from_yaml(text) != model:
            return ["the rendered YAML does not read back as the model"]
    except ValueError as exc:
        return [f"the rendered YAML does not parse: {exc}"]
    if model != fresh["model"] or rendered.get("scheduler") != fresh["scheduler"]:
        return ["the rendered YAML is not what the package says now: render it again from the package"]
    return []


def _env_entry(e: dict[str, Any]) -> list[str]:
    """One container setting: a name Cloud Run lets the product have, and exactly one of a value (never a
    secret's) or a Secret Manager reference."""
    name, out = e.get("name"), []
    if not gc.ENV_NAME.match(str(name or "")) or name in gc.RESERVED_ENV:
        out.append(f"env {name!r} is not a variable the product may be given on Cloud Run")
    if ("value" in e) == ("valueFrom" in e):
        return out + [f"env {name} must have exactly one of value or valueFrom"]
    if "value" in e:
        secretish = SECRET_NAME.search(str(name)) and e["value"] not in (None, "")
        return out + ([f"env {name} looks like a secret and is given a value"] if secretish else [])
    ref = (e["valueFrom"] or {}).get("secretKeyRef") or {}
    if not SECRET_KEY.match(str(ref.get("name", ""))) or not str(ref.get("key", "")):
        out.append(f"env {name} does not name a Secret Manager secret and version")
    return out


def _env_problems(container: dict[str, Any], pkg: dict[str, Any]) -> list[str]:
    out = [p for e in container.get("env") or [] for p in _env_entry(e)]
    return out + [f"secret {s.get('name')}: the gcp-cloudrun road reads secrets from Secret Manager by name "
                  "(sm:<secret>[:<version>]); this ref is not one"
                  for s in pkg.get("secrets") or [] if gc.secret_ref(s.get("ref")) is None]


def _container_problems(container: dict[str, Any], pkg: dict[str, Any]) -> list[str]:
    out = _env_problems(container, pkg)
    image = str(container.get("image", ""))
    if not (image.endswith(":" + str(pkg["revision"])[:12]) or DIGEST.search(image)):
        out.append("the container image is neither tagged with the revision nor pinned by digest")
    repo = (pkg["target"].get("repository") or "").rstrip("/")
    if repo and not image.startswith(repo + "/"):
        out.append(f"the image is not in the road's repository {repo}")
    limits = (container.get("resources") or {}).get("limits") or {}
    if str(limits.get("cpu")) not in gc.CPUS or not gc.MEMORY.match(str(limits.get("memory", ""))):
        out.append("resources.limits must name a cpu and a memory Cloud Run takes")
    return out


def _revision_problems(meta: dict[str, Any], template: dict[str, Any]) -> list[str]:
    out = []
    if (meta.get("annotations") or {}).get("run.googleapis.com/ingress") not in gc.INGRESS:
        out.append(f"the ingress must be one of {gc.INGRESS}")
    tmeta = template.get("metadata") or {}
    rev = tmeta.get("name", "")
    if not REVISION.match(rev) or not rev.startswith(f"{meta.get('name')}-"):
        out.append(f"revision {rev!r} must be named after its service")
    if (tmeta.get("annotations") or {}).get("autoscaling.knative.dev/maxScale") != "1":
        out.append("maxScale must be 1: the product keeps its data in files with one writer")
    return out


def _http_problems(containers: list[dict[str, Any]]) -> list[str]:
    out = []
    for c in containers[:1]:
        if [p.get("containerPort") for p in c.get("ports") or []] != [APP_PORT]:
            out.append(f"the container port must be {APP_PORT}")
        if ((c.get("startupProbe") or {}).get("httpGet") or {}).get("path") != "/health":
            out.append("the startup probe must read /health")
    return out


def _traffic_problems(traffic: list[dict[str, Any]], pkg: dict[str, Any]) -> list[str]:
    out = []
    if sum(int(x.get("percent", 0)) for x in traffic) != 100:
        out.append("the traffic must add up to 100 percent")
    untouched = any(x.get("tag") == "candidate" and x.get("percent") == 0 for x in traffic)
    if pkg["slot"] == "candidate" and pkg["target"].get("previous_revision") and not untouched:
        out.append("a candidate beside a current revision takes no traffic until it is promoted")
    return out


def _service_problems(model: dict[str, Any], pkg: dict[str, Any]) -> list[str]:
    if model.get("apiVersion") != "serving.knative.dev/v1" or model.get("kind") != "Service":
        return ["a service is a serving.knative.dev/v1 Service"]
    spec = model.get("spec") or {}
    template = spec.get("template") or {}
    return (_revision_problems(model.get("metadata") or {}, template)
            + _http_problems((template.get("spec") or {}).get("containers") or [])
            + _traffic_problems(spec.get("traffic") or [], pkg))


def _job_problems(model: dict[str, Any], pkg: dict[str, Any], scheduler: dict[str, Any] | None) -> list[str]:
    t, out = pkg["target"], []
    if model.get("apiVersion") != "run.googleapis.com/v1" or model.get("kind") != "Job":
        return ["a job is a run.googleapis.com/v1 Job"]
    task = ((model.get("spec") or {}).get("template") or {}).get("spec") or {}
    if task.get("parallelism") != 1 or task.get("taskCount") != 1:
        out.append("a job runs one task at a time: the product keeps its data in files with one writer")
    out += gc.job_problems({"max_retries": (task.get("template") or {}).get("spec", {}).get("maxRetries"),
                            "timeout_seconds": int(str((task.get("template") or {}).get("spec", {})
                                                       .get("timeoutSeconds", "0")) or 0)})
    if t.get("schedule"):
        out += gc.schedule_problems(t["schedule"])
        uri = ((scheduler or {}).get("httpTarget") or {}).get("uri", "")
        if not uri.endswith(f"/namespaces/{t['project_id']}/jobs/{t['name']}:run"):
            out.append("the scheduler does not call this job")
    return out


def check_rendered(pkg: dict[str, Any], render: Callable[[dict[str, Any]], dict[str, Any]]) -> list[str]:
    """Every problem with a gcp-cloudrun package as rendered; empty when it may be deployed."""
    t, rules = pkg.get("target") or {}, pkg.get("rules") or {}
    if t.get("workload") not in gc.WORKLOADS:
        return ["the package names no Cloud Run workload (service or job)"]
    out = _read_back(pkg.get("rendered") or {}, render(pkg))
    if out:
        return out
    model = pkg["rendered"]["model"]
    out += _where_problems(model, t, rules)
    inner = _inner_spec(model, t["workload"])
    if not gc.SERVICE_ACCOUNT.match(str(inner.get("serviceAccountName", ""))):
        out.append("the product runs as no service account (runtime_service_account)")
    containers = inner.get("containers") or []
    if len(containers) != 1:
        out.append("the template must hold exactly one container")
    out += [p for c in containers for p in _container_problems(c, pkg)]
    if t["workload"] == "job":
        return out + _job_problems(model, pkg, pkg["rendered"].get("scheduler"))
    return out + _service_problems(model, pkg)


def _where_problems(model: dict[str, Any], t: dict[str, Any], rules: dict[str, Any]) -> list[str]:
    """Its name, its project, the region the road allows, and the road's egress rule."""
    out = []
    if not NAME.match(str((model.get("metadata") or {}).get("name", ""))):
        out.append(f"name {(model.get('metadata') or {}).get('name')!r} is not a valid Cloud Run name")
    if not gc.PROJECT_ID.match(str(t.get("project_id") or "")):
        out.append(f"{t.get('project_id')!r} is not a Google Cloud project id")
    if not gc.REGION.match(str(t.get("region") or "")):
        out.append("the road names no region")
    elif rules.get("regions") and t["region"] not in rules["regions"]:
        out.append(f"region {t['region']} is not among the road's regions {rules['regions']}")
    return out + ([] if "egress" in rules else ["the road declares no egress rule"])


def _inner_spec(model: dict[str, Any], workload: str) -> dict[str, Any]:
    template = (model.get("spec") or {}).get("template") or {}
    if workload == "job":
        return ((template.get("spec") or {}).get("template") or {}).get("spec") or {}
    return template.get("spec") or {}
