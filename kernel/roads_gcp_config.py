"""What IT configures on a `gcp-cloudrun` road, and the checks that keep it whole (FR-GCP1).

A road entry in `paved_roads.json` (docs/guides/gcp.md has a full example):

- `project_id` (one Google Cloud project), or `projects` (one per environment: `{"staging": ..., "production":
  ...}`), and `region` (such as `europe-north1`);
- `repository`: the Artifact Registry repository images go to (`<region>-docker.pkg.dev/<project>/<repo>`);
- `deployer`: who deploys: `{"service_account": <email>}` (impersonated on every gcloud call),
  `{"credential_file": <path>}` (a workload identity federation configuration, which holds no secret), or
  `{"ambient": true}` (the deploying host's own gcloud login, such as a VM's attached service account);
- `runtime_service_account`: the identity the product runs as (a Drive folder is shared with it);
- `workload`: `service` (HTTP, the default) or `job` (a batch run on a schedule), and for a job a `schedule`
  (`cron`, `time_zone`, `retries`, the scheduler's `service_account`, the `environments` it runs in, by
  default production) and `job` settings (`max_retries`, `timeout_seconds`, `command`);
- `network`: `ingress` (a service's), `egress` and a `vpc_connector` or `vpc_network` with `vpc_subnet`;
- `resources` (`cpu`, `memory`), `env` (plain settings by name), `secrets` (`{"name": NAME, "ref":
  "sm:<secret>[:<version>]"}`, Secret Manager by name, never a value) and `rules` (`egress` is required).

A project may choose its own workload and schedule (`cloudrun` in project.json, kernel/road_settings.py):
`choice_problems` checks it as the road's own. No check here calls Google Cloud.
"""

from __future__ import annotations

import re
from typing import Any

KIND = "gcp-cloudrun"
WORKLOADS = ("service", "job")
INGRESS = ("all", "internal", "internal-and-cloud-load-balancing")
EGRESS = ("all-traffic", "private-ranges-only")
CPUS = ("1", "2", "4", "8")
PROJECT_ID = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]\Z")
REGION = re.compile(r"[a-z]+(?:-[a-z]+)+\d{1,2}\Z")
REPOSITORY = re.compile(r"(?P<region>[a-z]+(?:-[a-z]+)+\d{1,2})-docker\.pkg\.dev/(?P<project>[a-z][a-z0-9-]{4,28}"
                        r"[a-z0-9])/(?P<repo>[a-z][a-z0-9-]{0,62})\Z")
SERVICE_ACCOUNT = re.compile(r"(?:[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\.iam|"
                             r"\d{6,20}-compute@developer)\.gserviceaccount\.com\Z")
CONNECTOR = re.compile(r"(?:projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/locations/[a-z0-9-]+/connectors/)?"
                       r"[a-z][a-z0-9-]{0,24}\Z")
NETWORK_NAME = re.compile(r"[a-z][a-z0-9-]{0,62}\Z")
MEMORY = re.compile(r"\d{2,5}Mi\Z|\d{1,2}Gi\Z")
ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,63}\Z")
SECRET_REF = re.compile(r"sm:(?P<secret>[A-Za-z0-9_-]{1,255})(?::(?P<version>latest|\d{1,9}))?\Z|"
                        r"(?P<path>projects/[a-z0-9-]{1,30}/secrets/[A-Za-z0-9_-]{1,255})"
                        r"(?:/versions/(?P<pversion>latest|\d{1,9}))?\Z")
TIME_ZONE = re.compile(r"(?:UTC|[A-Z][A-Za-z_]+(?:/[A-Z][A-Za-z0-9_+-]+){1,2})\Z")
# What Cloud Run sets in a container itself: a road may not set them.
RESERVED_ENV = ("PORT", "K_SERVICE", "K_REVISION", "K_CONFIGURATION", "CLOUD_RUN_JOB", "CLOUD_RUN_EXECUTION",
                "CLOUD_RUN_TASK_INDEX", "CLOUD_RUN_TASK_ATTEMPT", "CLOUD_RUN_TASK_COUNT")
SECRET_WORD = re.compile(r"(?i)(secret|passw|token|api[_-]?key|private[_-]?key|connection[_-]?string|credential)")
CRON_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
CRON_ITEM = re.compile(r"(?:\*|(?P<a>\d{1,2})(?:-(?P<b>\d{1,2}))?)(?:/(?P<step>\d{1,2}))?\Z")
DEFAULT_JOB_COMMAND = ["python3", "-c", "import json; from app.job import run; "
                                        "print(json.dumps(run({'kind': 'schedule'}), default=str))"]


def _obj(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def project_for(cfg: dict[str, Any], env: str) -> str | None:
    """The Google Cloud project an environment deploys to: its own in `projects`, else `project_id`."""
    per = _obj(cfg.get("projects"))
    return per.get(env) or cfg.get("project_id") or None


def env_for(cfg: dict[str, Any], env: str) -> dict[str, str]:
    """The road's plain settings in one environment: a value, or the environment's own value (a test folder in
    staging, the real one in production); a setting with no value for the environment is not set there."""
    out = {}
    for name, value in (cfg.get("env") or {}).items():
        own = value.get(env) if isinstance(value, dict) else value
        if isinstance(own, str):
            out[str(name)] = own
    return out


def secret_ref(ref: object) -> dict[str, str] | None:
    """A Secret Manager reference as Cloud Run takes it ({"name", "key"}), or None when it is not one."""
    m = SECRET_REF.match(str(ref or ""))
    if m is None:
        return None
    if m.group("path"):
        return {"name": m.group("path"), "key": m.group("pversion") or "latest"}
    return {"name": m.group("secret"), "key": m.group("version") or "latest"}


def _cron_field(text: str, low: int, high: int) -> bool:
    for item in text.split(","):
        m = CRON_ITEM.match(item)
        if m is None:
            return False
        a, b, step = (int(x) if x else None for x in (m.group("a"), m.group("b"), m.group("step")))
        if any(v is not None and not low <= v <= high for v in (a, b)) or (a is not None and b is not None and b < a):
            return False
        if step is not None and step < 1:
            return False
    return True


def cron_problems(cron: object) -> list[str]:
    """A five-field cron expression in numbers (minute hour day-of-month month day-of-week), as Cloud
    Scheduler takes it; names (MON, JAN) and the six-field form are not."""
    fields = str(cron or "").split()
    if len(fields) != 5:
        return [f"schedule.cron {cron!r} must have five fields: minute hour day-of-month month day-of-week"]
    names = ("minute", "hour", "day of the month", "month", "day of the week")
    return [f"schedule.cron: {f!r} is not a valid {n} ({lo}-{hi}, *, a range or a step)"
            for f, n, (lo, hi) in zip(fields, names, CRON_RANGES, strict=True) if not _cron_field(f, lo, hi)]


def schedule_problems(schedule: object, environments: list[str] | None = None) -> list[str]:
    """A job's schedule: its cron, time zone, retries, the scheduler's service account and its environments."""
    if not isinstance(schedule, dict):
        return ["a job needs a schedule: {\"cron\": ..., \"time_zone\": ..., \"service_account\": ...}"]
    out = cron_problems(schedule.get("cron"))
    if not TIME_ZONE.match(str(schedule.get("time_zone", ""))):
        out.append(f"schedule.time_zone {schedule.get('time_zone')!r} is not a time zone name such as Europe/Helsinki")
    retries = schedule.get("retries", 0)
    if not isinstance(retries, int) or isinstance(retries, bool) or not 0 <= retries <= 5:
        out.append("schedule.retries must be a whole number from 0 to 5")
    if not SERVICE_ACCOUNT.match(str(schedule.get("service_account", ""))):
        out.append("schedule.service_account must name the service account Cloud Scheduler calls the job as "
                   "(it needs roles/run.invoker on the job)")
    envs = schedule.get("environments", ["production"])
    if not isinstance(envs, list) or (environments is not None and not set(envs) <= set(environments)):
        out.append(f"schedule.environments must be a list of the road's environments, got {envs!r}")
    return out


def job_problems(job: object) -> list[str]:
    if job is None:
        return []
    if not isinstance(job, dict):
        return ["job must be an object: max_retries, timeout_seconds, command"]
    out = []
    retries, timeout = job.get("max_retries", 1), job.get("timeout_seconds", 3600)
    if not isinstance(retries, int) or isinstance(retries, bool) or not 0 <= retries <= 10:
        out.append("job.max_retries must be a whole number from 0 to 10")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 86400:
        out.append("job.timeout_seconds must be from 1 to 86400")
    command = job.get("command")
    if command is not None and (not isinstance(command, list) or not command
                                or not all(isinstance(c, str) and c for c in command)):
        out.append("job.command must be a list of words, such as [\"python3\", \"-m\", \"app.transcribe\"]")
    return out


def _deployer_problems(deployer: object) -> list[str]:
    if not isinstance(deployer, dict) or len([k for k in ("service_account", "credential_file", "ambient")
                                              if k in deployer]) != 1:
        return ["deployer must name one identity to deploy as: {\"service_account\": ...}, {\"credential_file\": "
                "...} (workload identity federation) or {\"ambient\": true}"]
    if "service_account" in deployer and not SERVICE_ACCOUNT.match(str(deployer["service_account"])):
        return [f"deployer.service_account {deployer['service_account']!r} is not a service account email"]
    if "credential_file" in deployer and not str(deployer["credential_file"]).strip():
        return ["deployer.credential_file names no file"]
    if "ambient" in deployer and deployer["ambient"] is not True:
        return ["deployer.ambient must be true"]
    return []


def _network_problems(network: object, rules: dict[str, Any]) -> list[str]:
    net = network if isinstance(network, dict) else {}
    out = []
    if net.get("ingress", "internal") not in INGRESS:
        out.append(f"network.ingress must be one of {INGRESS}")
    egress = net.get("egress")
    if egress is not None and egress not in EGRESS:
        out.append(f"network.egress must be one of {EGRESS}")
    if egress and not (net.get("vpc_connector") or net.get("vpc_network")):
        out.append("network.egress routes through a VPC: name a vpc_connector, or a vpc_network and vpc_subnet")
    if net.get("vpc_connector") and not CONNECTOR.match(str(net["vpc_connector"])):
        out.append("network.vpc_connector is not a connector name or projects/.../connectors/... path")
    out += [f"network.{key} is not a network name" for key in ("vpc_network", "vpc_subnet")
            if net.get(key) and not NETWORK_NAME.match(str(net[key]))]
    return out + _egress_rule_problems(rules, egress)


def _egress_rule_problems(rules: dict[str, Any], egress: object) -> list[str]:
    if "egress" not in rules:
        return ["the road declares no egress rule (rules.egress)"]
    if str(rules.get("egress")).startswith("none") and egress != "all-traffic":
        return ["rules.egress is none: send all traffic through IT's VPC (network.egress all-traffic), where its "
                "firewall decides what leaves"]
    return []


def _plain(value: object) -> bool:
    return isinstance(value, str) or isinstance(value, dict) and all(isinstance(v, str) for v in value.values())


def _setting_problems(env: object) -> list[str]:
    out = []
    for name, value in (env.items() if isinstance(env, dict) else []):
        if not ENV_NAME.match(str(name)) or name in RESERVED_ENV:
            out.append(f"env {name!r} is not a variable a road may set")
        elif SECRET_WORD.search(str(name)):
            out.append(f"env {name} looks like a secret: name it under secrets with a Secret Manager ref")
        elif not _plain(value):
            out.append(f"env {name} must be a string, or one per environment ({{\"production\": ...}})")
    return out


def env_problems(env: object, secrets: object) -> list[str]:
    """Plain settings by name (never a secret-like name) and secrets by Secret Manager reference only."""
    out = _setting_problems(env)
    for s in secrets if isinstance(secrets, list) else []:
        name = s.get("name") if isinstance(s, dict) else None
        if not ENV_NAME.match(str(name or "")) or name in RESERVED_ENV:
            out.append(f"secret {name!r} needs a variable name, such as MODEL_API_KEY")
        elif "value" in s:
            out.append(f"secret {name} carries a value; a road names where a secret lives, never the secret itself")
        elif secret_ref(s.get("ref")) is None:
            out.append(f"secret {name}: ref must be sm:<secret>[:<version>] or projects/<p>/secrets/<s>[/versions/<v>] "
                       "(Secret Manager, by name)")
    return out


def _where_problems(cfg: dict[str, Any]) -> list[str]:
    out = []
    envs = cfg.get("environments") or ["staging", "production"]
    for env in envs:
        pid = project_for(cfg, env)
        if not pid:
            out.append(f"no Google Cloud project for {env} (project_id, or projects.{env})")
        elif not PROJECT_ID.match(str(pid)):
            out.append(f"{pid!r} is not a Google Cloud project id")
    if not REGION.match(str(cfg.get("region", ""))):
        out.append(f"region {cfg.get('region')!r} is not a Cloud Run region such as europe-north1")
    rules = _obj(cfg.get("rules"))
    if rules.get("regions") and cfg.get("region") not in rules["regions"]:
        out.append(f"region {cfg.get('region')} is not among the road's regions {rules['regions']}")
    if not REPOSITORY.match(str(cfg.get("repository", ""))):
        out.append("repository must be an Artifact Registry repository: <region>-docker.pkg.dev/<project>/<repo>")
    return out


def config_problems(cfg: dict[str, Any]) -> list[str]:
    """Every way a gcp-cloudrun road entry is incomplete or unsafe; empty when IT's entry is whole."""
    out = _where_problems(cfg) + _deployer_problems(cfg.get("deployer"))
    if not SERVICE_ACCOUNT.match(str(cfg.get("runtime_service_account", ""))):
        out.append("runtime_service_account must name the service account the product runs as")
    out += choice_problems({k: cfg[k] for k in ("workload", "schedule", "job") if k in cfg},
                           cfg.get("environments") or ["staging", "production"])
    rules = _obj(cfg.get("rules"))
    out += _network_problems(cfg.get("network"), rules)
    res = _obj(cfg.get("resources"))
    if str(res.get("cpu", "1")) not in CPUS:
        out.append(f"resources.cpu must be one of {CPUS}")
    if not MEMORY.match(str(res.get("memory", "512Mi"))):
        out.append("resources.memory must be like 512Mi or 2Gi")
    return out + env_problems(cfg.get("env"), cfg.get("secrets"))


def choice_problems(choice: dict[str, Any], environments: list[str]) -> list[str]:
    """A workload with its schedule and job settings, as a road or a project's choice gives them."""
    workload = choice.get("workload", "service")
    if workload not in WORKLOADS:
        return [f"workload must be one of {WORKLOADS}, got {workload!r}"]
    if workload == "service":
        return [] if "schedule" not in choice else ["a schedule runs a job: set workload job, or drop the schedule"]
    return schedule_problems(choice.get("schedule"), environments) + job_problems(choice.get("job"))


def effective(cfg: dict[str, Any], meta: dict[str, Any] | None) -> dict[str, Any]:
    """The road's entry with a project's own choice of workload, schedule and job settings over it."""
    own = (meta or {}).get("cloudrun")
    out = dict(cfg)
    if isinstance(own, dict):
        out.update({k: own[k] for k in ("workload", "schedule", "job") if k in own})
        if own.get("workload") == "service":
            out.pop("schedule", None)
    return out
