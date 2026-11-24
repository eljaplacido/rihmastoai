"""The assessment's rules for architecture and operations (kernel/assess.py): how the system starts, whether
it answers a health check, where its configuration comes from, how it logs, and how it is packaged.

Routes are found with the kernel's simple patterns (`kernel.adopt.endpoints`): a system whose routes they
miss reads "not measured", never "no health endpoint". Dockerfiles are read with the red team's parser
(`kernel/redteam/dockerrules.py`); nothing is built or run.
"""

from __future__ import annotations

import re
from typing import Any

from kernel.adopt import dockerfiles, endpoints
from kernel.assess_repo import Repo, at, base, fact, listed, result
from kernel.redteam.dockerrules import instructions

HEALTH = re.compile(r"^/(api/)?(health|healthz|healthcheck|ready|readyz|readiness|live|livez|liveness|status|ping|"
                    r"actuator/health)(/|$)", re.I)
PROBES = re.compile(r"\b(livenessProbe|readinessProbe|startupProbe)\s*:")
ENTRY = re.compile(r"""if __name__ == ['"]__main__['"]|^func main\(\)|public static void main\(|"""
                   r"""@SpringBootApplication|^\s*"(main|bin|start)"\s*:|\[project\.scripts\]|console_scripts""")
ENTRY_FILES = ("Procfile", "manage.py", "wsgi.py", "asgi.py", "main.py", "app.py", "server.js", "index.js", "main.go")
ENV_READ = re.compile(r"os\.environ|os\.getenv|\bgetenv\(|process\.env|System\.getenv|os\.Getenv|\bENV\[|"
                      r"GetEnvironmentVariable|env::var|@Value\(|BaseSettings|from_envvar")
LOGGING = re.compile(r"^\s*import logging\b|from logging import|logging\.getLogger|LoggerFactory|getLogger\(|"
                     r"""['"](winston|pino|bunyan|log4js)['"]|"log/slog"|go\.uber\.org/zap|sirupsen/logrus|ILogger<|"""
                     r"Serilog|\blog::(info|warn|error)!|\btracing::")
PRINTS = re.compile(r"\bprint\(|console\.(log|error)\(|System\.out\.print|fmt\.Print")
COMPOSE = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")


def _ops(key: str, title: str, verdict: str, **kw: Any) -> dict[str, Any]:
    return result(f"architecture.{key}", "architecture", title, verdict, **kw)


def _docker_lines(repo: Repo, ops: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    for rel in dockerfiles(repo.files):
        lines = repo.text(rel).splitlines()
        out += [at(rel, i.line, lines[i.line - 1] if 0 < i.line <= len(lines) else i.args)
                for i in instructions(repo.text(rel)) if i.op in ops]
    return out


def entry_points(repo: Repo) -> dict[str, Any]:
    title = "How the system starts is written down"
    code = repo.code()
    if not code:
        return _ops("entry_points", title, "not applicable", reason="no source code found by rule")
    found = _docker_lines(repo, ("CMD", "ENTRYPOINT"))
    found += repo.find(ENTRY, code + [f for f in ("package.json", "pyproject.toml", "setup.cfg", "setup.py")
                                      if f in repo.files], limit=4)
    found += [{"file": f, "fact": "a conventional entry point"} for f in repo.files if f in ENTRY_FILES]
    if found:
        return _ops("entry_points", title, "passed", summary=f"{len(found)} entry point(s) found", evidence=found)
    return _ops("entry_points", title, "failed", severity="low", summary="no entry point found by rule",
                evidence=[fact(f"no CMD or ENTRYPOINT, main function, start script or console script in "
                               f"{len(code)} source file(s)")],
                suggestion="Write down how the system starts: a start script, a console entry point or the "
                           "container's command.")


def _route_line(repo: Repo, route: dict[str, Any]) -> dict[str, Any]:
    hits = repo.find(re.compile(re.escape(str(route["path"]).rstrip("/")) + r"""['"/`]"""), [route["declared_in"]], 1)
    return hits[0] if hits else {"file": route["declared_in"], "fact": f"{route['method']} {route['path']}"}


def health(repo: Repo) -> dict[str, Any]:
    title = "A health endpoint is declared"
    routes = endpoints(repo.root, repo.files)
    healthy = [r for r in routes if HEALTH.match(str(r["path"]))]
    checks = _docker_lines(repo, ("HEALTHCHECK",))
    checks += repo.find(PROBES, repo.named(lambda f: f.lower().endswith((".yml", ".yaml"))), limit=2)
    if healthy or checks:
        return _ops("health", title, "passed", evidence=[_route_line(repo, r) for r in healthy[:4]] + checks,
                    summary=", ".join(f"{r['method']} {r['path']}" for r in healthy[:4]) or "a container health check")
    if not routes:
        return _ops("health", title, "not measured",
                    reason="no HTTP route was found with the kernel's simple patterns, so whether the system serves "
                           "HTTP is not known")
    return _ops("health", title, "failed", severity="medium",
                summary=f"{len(routes)} route(s) declared, none of them a health check",
                evidence=[_route_line(repo, r) for r in routes[:3]],
                suggestion="Add a GET /health route that answers 200 when the service can do its work, so operations "
                           "and the factory's probes can tell it is up.")


def config(repo: Repo) -> dict[str, Any]:
    title = "Configuration comes from the environment"
    code = repo.code()
    if not code:
        return _ops("config", title, "not applicable", reason="no source code found by rule")
    found = repo.find(ENV_READ, code, limit=4, code_only=True)
    examples = [{"file": f, "fact": "documents the settings"} for f in repo.files
                if base(f) in (".env.example", ".env.sample", ".env.template")]
    if found:
        return _ops("config", title, "passed", summary="settings are read from the environment",
                    evidence=found + examples)
    return _ops("config", title, "failed", severity="medium", summary="no read of the environment found by rule",
                evidence=[fact(f"no environment read (os.environ, getenv, process.env, ...) in {len(code)} source "
                               "file(s): settings appear to be fixed in the code"),
                          *({**e, "fact": "documents settings that no code reads"} for e in examples)],
                suggestion="Read addresses, credentials and switches from the environment, so one build runs in "
                           "every environment and no secret lives in the code.")


def logs(repo: Repo) -> dict[str, Any]:
    title = "The code logs through a logging library"
    code = repo.code()
    if not code:
        return _ops("logging", title, "not applicable", reason="no source code found by rule")
    found = repo.find(LOGGING, code, limit=3)
    if found:
        return _ops("logging", title, "passed", evidence=found)
    prints = repo.find(PRINTS, code, limit=3)
    return _ops("logging", title, "failed", severity="low",
                summary="prints only" if prints else "no logging found by rule",
                evidence=prints or [fact(f"no logging library in {len(code)} source file(s)")],
                suggestion="Log through a logging library with levels, so operations can filter and keep what "
                           "matters.")


def container(repo: Repo) -> dict[str, Any]:
    title = "The system is containerised"
    found = dockerfiles(repo.files)
    compose = [f for f in (repo.first(n) for n in COMPOSE) if f]
    if found:
        return _ops("container", title, "passed", summary=listed(found),
                    evidence=_docker_lines(repo, ("FROM",))[:3] + [{"file": f, "fact": "present"} for f in compose])
    if not repo.code():
        return _ops("container", title, "not applicable", reason="no source code found by rule")
    return _ops("container", title, "failed", severity="low", summary="no Dockerfile",
                evidence=[fact("no Dockerfile or Containerfile")],
                suggestion="Describe the runtime in a Dockerfile, so the system runs the same on every machine and "
                           "can go on a paved road.")


def dockerignore(repo: Repo) -> dict[str, Any]:
    title = "The image build leaves out what it should"
    found = dockerfiles(repo.files)
    if not found:
        return _ops("dockerignore", title, "not applicable", reason="no Dockerfile")
    folders = sorted({f.rsplit("/", 1)[0] + "/" if "/" in f else "" for f in found})
    missing = [d or "the root" for d in folders if (d + ".dockerignore") not in repo.files]
    if not missing:
        return _ops("dockerignore", title, "passed",
                    evidence=[{"file": d + ".dockerignore", "fact": "present"} for d in folders])
    return _ops("dockerignore", title, "failed", severity="low", summary="no .dockerignore beside a Dockerfile",
                evidence=[fact(f"no .dockerignore in {listed(missing)}")],
                suggestion="Add a .dockerignore (.git, .env, tests, local data), so the build context carries no "
                           "secret or history into the image.")


ARCHITECTURE = (entry_points, health, config, logs, container, dockerignore)

__all__ = ["ARCHITECTURE"]
