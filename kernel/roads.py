"""Paved roads: where a product may run, configured in advance by IT (FR-A8, FR-Q4).

A road is an entry in the factory's `paved_roads.json` (`Factory.paved_roads_path`). It names
its kind, whether IT has configured it, the environments it serves, the identity it deploys as
and the rules it keeps (region, TLS, egress). The factory deploys only to a configured road; a
road that is missing or not configured is a card for IT, never a guess.

Kinds:
- `local-process`: the product runs as a Python process (`app.server`, started as LAUNCH says)
  from a checkout of the product repository, on a free loopback port. Explore previews use it,
  and so do the tests.
- `docker`: the same contract through the docker CLI on the kernel's host: an image per
  revision, a container per environment and slot, a named volume for `/data`.
- `azure-containerapps`: renders an Azure Container Apps YAML and an `az` command plan, and
  validates them. It deploys only when the road is configured, names an identity and the
  `az` CLI is on PATH.

Every deployment goes through a deploy package: the artifact (image or process reference), the
environment settings, secret *references* (never values) and the road's rules. A slot is one
running copy in an environment: `current` serves the environment, `candidate` is a new release
beside it in production, and `twin` is a disposable copy on its own empty data: of the current
release for shadow tests, or of the release being delivered for its holdouts (FR-H9). The
local-process and docker roads host a twin; when a twin stops, its data goes with it.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from kernel.lanes import _git
from kernel.store import read_json, write_json, write_text

SCHEMA = "gnomonfactory.paved_roads/1"
PACKAGE_SCHEMA = "gnomonfactory.deploy_package/1"
KINDS = ("local-process", "docker", "azure-containerapps")
ENVIRONMENTS = ("preview", "demo", "staging", "production")
SLOTS = ("current", "candidate", "twin")
APP_PORT = 8080
# How the product is started. `python -m app.server` runs server.py as `__main__`, while
# app/routes.py registers its routes on the module `app.server`: a second copy that nothing
# serves, so every product route answers 404 (only /health, defined in server.py, works).
# Importing app.server and calling main() keeps one copy. The scaffold's `__main__` guard and
# its Dockerfile CMD have this problem; the roads start the product this way instead.
LAUNCH = ["-c", "from app.server import main; main()"]
CONTAINER_DATA = "/data"
CONTAINER_TRAFFIC = "/data/traffic.jsonl"

# An explore preview never leaves the kernel's machine, so it needs no road from IT.
BUILTIN_ROADS = {
    "local-preview": {"kind": "local-process", "configured": True, "environments": ["preview"],
                      "rules": {"network": "loopback only", "tls": "none: a local preview", "egress": "none"},
                      "note": "built in: an explore preview runs on the kernel's machine only"},
}
BUILTIN_MATURITY = {"explore": "local-preview"}

SECRET_NAME = re.compile(r"(?i)(secret|passw|token|api[_-]?key|private[_-]?key|connection[_-]?string|credential)")
_STARTED: dict = {}  # pid -> Popen, for the processes this kernel started


class RoadError(RuntimeError):
    """A road could not do what it was asked. ``native`` keeps what the tool said."""

    def __init__(self, message: str, native: dict | None = None):
        super().__init__(message)
        self.native = dict(native or {})


# -- small helpers ------------------------------------------------------------------------------

def stamp(project) -> str:
    return project.factory.clock.stamp()


def rel(project, path: Path) -> str:
    return Path(path).resolve().relative_to(project.dir.resolve()).as_posix()


def _force_remove(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def rmtree(path: Path) -> None:
    """Remove a tree, including git's read-only object files on Windows."""
    if Path(path).exists():
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_force_remove)
        else:  # pragma: no cover
            shutil.rmtree(path, onerror=_force_remove)


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _loopback(url: str) -> bool:
    return (urllib.parse.urlsplit(url).hostname or "") in ("127.0.0.1", "localhost", "::1")


_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _listening(url: str, timeout: float = 0.25) -> bool:
    """Whether something accepts connections at a loopback URL. On Windows a connection to a
    closed loopback port is not refused at once: it hangs for the whole timeout."""
    parts = urllib.parse.urlsplit(url)
    try:
        with socket.create_connection((parts.hostname, parts.port or 80), timeout=timeout):
            return True
    except OSError:
        return False


def http_request(method: str, url: str, body=None, *, timeout: float = 10.0) -> dict:
    """One HTTP call. Returns status, the JSON body if there is one, the text and the latency.
    A 4xx or 5xx is an answer, not an error; ``status`` is None only when nothing answered."""
    if _loopback(url) and not _listening(url):
        return {"status": None, "error": "ConnectionRefusedError: nothing listens there", "ms": 0.0,
                "is_json": False, "json": None, "text": ""}
    data, headers = None, {}
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
        elif isinstance(body, str):
            data, headers["Content-Type"] = body.encode("utf-8"), "text/plain; charset=utf-8"
        else:
            data, headers["Content-Type"] = json.dumps(body).encode("utf-8"), "application/json"
    req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
    opener = _NO_PROXY if _loopback(url) else urllib.request.build_opener()
    t0 = time.perf_counter()
    try:
        with opener.open(req, timeout=timeout) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
        exc.close()
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        return {"status": None, "error": f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}",
                "ms": round((time.perf_counter() - t0) * 1000, 1), "is_json": False, "json": None, "text": ""}
    ms = round((time.perf_counter() - t0) * 1000, 1)
    text = raw.decode("utf-8", "replace")
    try:
        parsed, is_json = json.loads(text), True
    except json.JSONDecodeError:
        parsed, is_json = None, False
    return {"status": status, "json": parsed, "is_json": is_json, "text": text, "ms": ms}


def wait_healthy(base_url: str, *, version: str | None = None, timeout: float = 20.0, alive=None) -> dict:
    """Poll ``/health`` until it answers 200 with status ok (and ``version`` when given)."""
    deadline, last = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        if alive is not None and not alive():
            raise RoadError("the service exited before it answered /health", {"last": last})
        r = http_request("GET", base_url + "/health", timeout=2.0)
        body = r["json"] if isinstance(r["json"], dict) else {}
        if r["status"] == 200 and body.get("status") == "ok":
            if version is None or body.get("version") == version:
                return {"url": base_url + "/health", "status": 200, "body": body, "ms": r["ms"]}
        last = {"status": r["status"], "body": r["json"] if r["is_json"] else r["text"][:300], "error": r.get("error")}
        time.sleep(0.1)
    raise RoadError(f"no healthy answer from {base_url}/health within {timeout}s"
                    + (f" for version {version}" if version else ""), {"last": last})


def checkout(project, revision: str) -> Path:
    """A working copy of the product at ``revision``, shared by every road that builds it."""
    dest = project.path("builds", revision[:12])
    if (dest / ".git").exists():
        if _git(dest, "rev-parse", "HEAD", check=False) == revision:
            return dest
        rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".checkout-", dir=dest.parent))
    try:
        _git(tmp, "clone", "-q", "--no-checkout", str(project.path("repo.git")), "w")
        _git(tmp / "w", "checkout", "-q", "--detach", revision)
        write_text(tmp / "w" / ".dockerignore", ".git\n")
        os.replace(tmp / "w", dest)
    finally:
        rmtree(tmp)
    return dest


# -- slots: what runs where -----------------------------------------------------------------------

def slot_path(project, env: str, slot: str) -> Path:
    return project.path("envs", env, f"{slot}.json")


def slot_state(project, env: str, slot: str = "current") -> dict | None:
    return read_json(slot_path(project, env, slot))


def _save_slot(project, state: dict) -> None:
    write_json(slot_path(project, state["environment"], state["slot"]), state)


def _clear_slot(project, env: str, slot: str) -> None:
    slot_path(project, env, slot).unlink(missing_ok=True)


def running_slots(project) -> list:
    envs = project.path("envs")
    if not envs.exists():
        return []
    out = []
    for env_dir in sorted(p for p in envs.iterdir() if p.is_dir()):
        for slot in SLOTS:
            state = slot_state(project, env_dir.name, slot)
            if state:
                out.append(state)
    return out


def parse_traffic(text: str) -> list:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("method"), str) and isinstance(rec.get("path"), str):
            out.append(rec)
    return out


# -- the roads file -------------------------------------------------------------------------------

class PavedRoads:
    """The roads IT has configured, as read from `paved_roads.json`, plus the built-in preview."""

    def __init__(self, config: dict | None = None, *, source: str | None = None):
        config = config if isinstance(config, dict) else {}
        self.source = source
        self.problems: list = []
        if config.get("schema") not in (None, SCHEMA):
            self.problems.append(f"schema must be {SCHEMA}, got {config.get('schema')!r}")
        self.roads = {name: dict(cfg) for name, cfg in BUILTIN_ROADS.items()}
        for name, cfg in (config.get("roads") or {}).items():
            if not isinstance(cfg, dict):
                self.problems.append(f"road {name!r} is not an object")
                continue
            if cfg.get("kind") not in KINDS:
                self.problems.append(f"road {name!r}: kind must be one of {KINDS}, got {cfg.get('kind')!r}")
            self.roads[name] = dict(cfg)
        self.maturity = dict(BUILTIN_MATURITY)
        self.maturity.update(config.get("maturity") or {})

    @classmethod
    def load(cls, source=None) -> "PavedRoads":
        """From a PavedRoads, a config dict, a Factory (its `paved_roads_path`), a path, or nothing."""
        if isinstance(source, PavedRoads):
            return source
        if isinstance(source, dict):
            return cls(source, source="(given)")
        path = getattr(source, "paved_roads_path", None) or (Path(source) if source else None)
        if path is None:
            return cls({}, source=None)
        try:
            raw = read_json(path)
        except json.JSONDecodeError as exc:
            roads = cls({}, source=str(path))
            roads.problems.append(f"{path} is not valid JSON: {exc}")
            return roads
        return cls(raw or {}, source=str(path) if raw is not None else None)

    def name_for(self, project, env: str) -> str | None:
        """The road for ``env``: the project's own `paved_road`, else the maturity's road."""
        meta = project.meta
        chosen = meta.get("paved_road") or self.maturity.get(meta.get("maturity"))
        if isinstance(chosen, dict):
            chosen = chosen.get(env)
        return chosen or None

    def missing(self, name: str | None, env: str, *, docker=None, az=None) -> list:
        """What stands between this road and a deployment to ``env``. Empty means ready."""
        if name is None:
            where = self.source or "paved_roads.json (it does not exist yet)"
            return [f"no paved road is named for the {env} environment in {where}"]
        cfg = self.roads.get(name)
        if cfg is None:
            return [f"road {name!r} is not in paved_roads.json"]
        out = []
        if cfg.get("kind") not in KINDS:
            return [f"road {name!r} has an unknown kind {cfg.get('kind')!r}"]
        if cfg.get("configured") is not True:
            out.append(f"road {name!r} is not marked \"configured\": true by IT")
        envs = cfg.get("environments")
        if envs is not None and env not in envs:
            out.append(f"road {name!r} does not serve the {env} environment")
        return out + make_road(name, cfg, docker=docker, az=az).missing()

    def road(self, name: str, *, docker=None, az=None) -> "Road":
        return make_road(name, self.roads[name], docker=docker, az=az)


def make_road(name: str, cfg: dict, *, docker=None, az=None) -> "Road":
    kind = cfg.get("kind")
    if kind == "local-process":
        return LocalProcessRoad(name, cfg)
    if kind == "docker":
        return DockerRoad(name, cfg, docker=docker)
    if kind == "azure-containerapps":
        return AzureContainerAppsRoad(name, cfg, az=az)
    raise RoadError(f"road {name!r} has an unknown kind {kind!r}")


def road_for_slot(state: dict, roads=None, *, docker=None, az=None) -> "Road":
    """The road a running slot was deployed with (its config re-read, else its kind alone)."""
    paved = PavedRoads.load(roads)
    cfg = paved.roads.get(state["road"]) or {"kind": state["kind"]}
    return make_road(state["road"], cfg, docker=docker, az=az)


# -- roads ----------------------------------------------------------------------------------------

class Road:
    kind = ""

    def __init__(self, name: str, cfg: dict):
        self.name, self.cfg = name, dict(cfg)

    @property
    def rules(self) -> dict:
        return dict(self.cfg.get("rules") or {})

    def missing(self) -> list:
        return []

    def shadow_target(self) -> str:
        """`twin` (default): shadow replays against a fresh copy of the current release, so the
        live slot never sees replayed traffic. `live`: against the live current slot."""
        return "live" if self.cfg.get("shadow_target") == "live" else "twin"

    def shadow_safe(self, env: str) -> bool:
        return env in (self.cfg.get("shadow_safe") or [])

    def hosts_twin(self) -> bool:
        """Whether delivery may start a `twin` slot beside an environment's current one, so the
        holdouts write their data there instead of where end users try the product."""
        return False

    def volatile(self):
        return self.cfg.get("volatile")

    def secrets(self) -> tuple[list, list]:
        """Secret references (name and where the value lives) and any problem with them.
        A value written into the road is never copied into a package."""
        refs, problems = [], []
        for s in self.cfg.get("secrets") or []:
            if not isinstance(s, dict) or not s.get("name"):
                problems.append("a road secret has no name")
                continue
            if "value" in s:
                problems.append(f"road secret {s['name']} carries a value in paved_roads.json; "
                                "a road names where a secret lives, never the secret itself")
            if not s.get("ref"):
                problems.append(f"road secret {s['name']} has no ref (where the value lives)")
            refs.append({"name": str(s["name"]), "ref": s.get("ref")})
        return refs, problems

    def settings(self, project, env: str, slot: str, revision: str) -> dict:
        return {"APP_VERSION": revision[:12], "PORT": str(APP_PORT), "DATA_DIR": CONTAINER_DATA,
                "TRAFFIC_LOG": CONTAINER_TRAFFIC}

    def target(self, project, env: str, slot: str, release: int, revision: str, artifact: dict) -> dict:
        return {}

    def package(self, project, *, env: str, slot: str, release: int, revision: str, artifact: dict,
                contract_revision: str | None = None) -> dict:
        """The deploy package: everything a deployment needs, and nothing secret."""
        secrets, problems = self.secrets()
        pkg = {"schema": PACKAGE_SCHEMA, "project": project.pid, "release": release, "environment": env,
               "slot": slot, "road": {"name": self.name, "kind": self.kind}, "revision": revision,
               "contract_revision": contract_revision, "artifact": dict(artifact),
               "settings": self.settings(project, env, slot, revision), "secrets": secrets, "rules": self.rules,
               "target": self.target(project, env, slot, release, revision, artifact),
               "road_problems": problems}
        self.render(project, pkg)
        return pkg

    def render(self, project, pkg: dict) -> None:
        """Add a kind-specific `rendered` section (the Azure YAML and command plan)."""

    def build(self, project, revision: str) -> dict:
        raise NotImplementedError

    def deploy(self, project, package: dict) -> dict:
        raise NotImplementedError

    def stop(self, project, env: str, slot: str) -> dict | None:
        raise NotImplementedError

    def read_traffic(self, project, env: str, slot: str = "current") -> list | None:
        return None

    def _state(self, project, package: dict, **extra) -> dict:
        return {"road": self.name, "kind": self.kind, "environment": package["environment"], "slot": package["slot"],
                "release": package["release"], "revision": package["revision"], "rev12": package["revision"][:12],
                "artifact": package["artifact"], "started": stamp(project), "package": package, **extra}


def _detach() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {"start_new_session": True}


def _terminate(proc) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(5)


def _ours(state: dict) -> bool:
    """Before killing by pid, make sure the pid is still the product we started."""
    cmdline = Path(f"/proc/{state['pid']}/cmdline")
    if cmdline.exists():
        try:
            return b"app.server" in cmdline.read_bytes()
        except OSError:
            return False
    r = http_request("GET", f"{state['base_url']}/health", timeout=2.0)
    return r["status"] == 200 and isinstance(r["json"], dict) and r["json"].get("version") == state.get("rev12")


def _kill_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except (OSError, SystemError):
        return
    if os.name == "nt":
        return
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def stop_started() -> int:
    """Stop every product process this kernel process started (a safety net for tests)."""
    n = 0
    for pid, proc in list(_STARTED.items()):
        _terminate(proc)
        _STARTED.pop(pid, None)
        n += 1
    return n


def stop_all(project, roads=None, *, docker=None, az=None) -> list:
    """Stop every slot of a project, in every environment."""
    stopped = []
    for state in running_slots(project):
        try:
            road_for_slot(state, roads, docker=docker, az=az).stop(project, state["environment"], state["slot"])
        except RoadError:
            _clear_slot(project, state["environment"], state["slot"])
        stopped.append((state["environment"], state["slot"]))
    return stopped


class LocalProcessRoad(Road):
    """The product as a local process: `python -m app.server` from a checkout, on loopback."""

    kind = "local-process"

    def hosts_twin(self) -> bool:
        return True

    def python(self) -> str:
        return self.cfg.get("python") or sys.executable or "python3"

    def _dirs(self, env: str, slot: str) -> dict:
        base = f"envs/{env}" if slot == "current" else f"envs/{env}/{slot}"
        return {"data_dir": f"{base}/data", "traffic_log": f"{base}/traffic.jsonl", "log": f"envs/{env}/{slot}.log"}

    def settings(self, project, env, slot, revision):
        d = self._dirs(env, slot)
        port = (self.cfg.get("ports") or {}).get(env) if slot == "current" else None
        return {"APP_VERSION": revision[:12], "PORT": str(port) if port else "auto", "DATA_DIR": d["data_dir"],
                "TRAFFIC_LOG": d["traffic_log"]}

    def target(self, project, env, slot, release, revision, artifact):
        port = (self.cfg.get("ports") or {}).get(env) if slot == "current" else None
        return {"host": "127.0.0.1", "port": port, **self._dirs(env, slot), "cwd": artifact.get("checkout")}

    def build(self, project, revision):
        work = checkout(project, revision)
        if not (work / "app" / "server.py").exists():
            raise RoadError("the product has no app/server.py at this revision", {"revision": revision})
        return {"type": "process", "ref": f"repo.git@{revision}", "checkout": rel(project, work),
                "command": list(self.cfg.get("command") or [self.python(), *LAUNCH])}

    def deploy(self, project, package):
        env, slot, t = package["environment"], package["slot"], package["target"]
        self.stop(project, env, slot)
        data, traffic, log = (project.dir / t["data_dir"], project.dir / t["traffic_log"], project.dir / t["log"])
        if slot != "current":  # a candidate or a twin starts empty
            rmtree(data)
            traffic.unlink(missing_ok=True)
        data.mkdir(parents=True, exist_ok=True)
        port = t.get("port") or free_port()
        envvars = {k: v for k, v in os.environ.items() if k not in ("DATA_DIR", "TRAFFIC_LOG", "PORT", "APP_VERSION")}
        envvars.update(PORT=str(port), DATA_DIR=str(data), TRAFFIC_LOG=str(traffic),
                       APP_VERSION=package["settings"]["APP_VERSION"], PYTHONUNBUFFERED="1",
                       PYTHONDONTWRITEBYTECODE="1")
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "ab") as fh:
            try:
                proc = subprocess.Popen(package["artifact"]["command"], cwd=project.dir / package["artifact"]["checkout"],
                                        env=envvars, stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                                        **_detach())
            except OSError as exc:
                raise RoadError(f"could not start the product: {exc}", {"command": package["artifact"]["command"]})
        _STARTED[proc.pid] = proc
        state = self._state(project, package, pid=proc.pid, port=port, base_url=f"http://127.0.0.1:{port}")
        _save_slot(project, state)
        try:
            state["health"] = wait_healthy(state["base_url"], version=package["revision"][:12],
                                           timeout=float(self.cfg.get("start_timeout", 20)),
                                           alive=lambda: proc.poll() is None)
        except RoadError as exc:
            self.stop(project, env, slot)
            exc.native["log_tail"] = log.read_text(encoding="utf-8", errors="replace")[-2000:] if log.exists() else ""
            raise
        _save_slot(project, state)
        return state

    def stop(self, project, env, slot):
        state = slot_state(project, env, slot)
        if not state:
            return None
        proc = _STARTED.pop(state.get("pid"), None)
        if proc is not None:
            _terminate(proc)
        elif state.get("pid") and _ours(state):
            _kill_pid(state["pid"])
        _clear_slot(project, env, slot)
        if slot == "twin":
            self._discard(project, env, state)
        return state

    def _discard(self, project, env: str, state: dict) -> None:
        """A twin is disposable: what was written to it (holdout or replayed data) goes with it."""
        target = (state.get("package") or {}).get("target") or self._dirs(env, "twin")
        try:
            rmtree(project.dir / target["data_dir"])
            (project.dir / target["traffic_log"]).unlink(missing_ok=True)
        except OSError:  # a file still held open: the next twin starts empty all the same (deploy clears it)
            pass

    def read_traffic(self, project, env, slot="current"):
        state = slot_state(project, env, slot)
        rel_path = (state or {}).get("package", {}).get("target", {}).get("traffic_log") \
            or self._dirs(env, slot)["traffic_log"]
        path = project.dir / rel_path
        return parse_traffic(path.read_text(encoding="utf-8", errors="replace")) if path.exists() else []


# -- docker -------------------------------------------------------------------------------------

def _run_subprocess(argv, timeout):
    proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


class DockerCLI:
    """The docker CLI on the kernel's host. ``runner(argv, timeout) -> (exit, stdout, stderr)``
    replaces the subprocess in tests, so the commands can be checked without a daemon."""

    def __init__(self, binary: str = "docker", *, runner=None, timeout: float = 900):
        self.binary, self.runner, self.timeout = binary, runner or _run_subprocess, timeout

    def available(self) -> bool:
        return self.runner is not _run_subprocess or shutil.which(self.binary) is not None

    def __call__(self, *args, check: bool = True, timeout: float | None = None) -> str:
        argv = [self.binary, *(str(a) for a in args)]
        try:
            code, out, err = self.runner(argv, timeout or self.timeout)
        except FileNotFoundError:
            raise RoadError(f"{self.binary} is not installed on this host", {"argv": argv})
        except subprocess.TimeoutExpired:
            raise RoadError(f"docker {args[0]} did not finish in {timeout or self.timeout}s", {"argv": argv})
        if check and code != 0:
            raise RoadError(f"docker {args[0]} failed (exit {code})", {"argv": argv, "exit": code,
                                                                      "stderr": (err or "")[-2000:]})
        return (out or "").strip()

    @staticmethod
    def _flags(flag: str, items: dict | None) -> list:
        return [x for k, v in (items or {}).items() for x in (flag, f"{k}={v}")]

    def build(self, context, tag: str, *, labels: dict | None = None) -> str:
        return self("build", "--tag", tag, *self._flags("--label", labels), str(context))

    def image_id(self, tag: str) -> str:
        return self("image", "inspect", "--format", "{{.Id}}", tag)

    def run(self, name: str, image: str, *, publish: str, volume: str, env: dict | None = None,
            labels: dict | None = None, restart: str = "unless-stopped", command=None) -> str:
        return self("run", "--detach", "--name", name, "--restart", restart, "--publish", publish,
                    "--volume", volume, *self._flags("--env", env), *self._flags("--label", labels), image,
                    *(command or []))

    def host_port(self, name: str, container_port: int = APP_PORT) -> int:
        out = self("port", name, f"{container_port}/tcp")
        first = out.splitlines()[0] if out else ""
        try:
            return int(first.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            raise RoadError(f"docker port gave no host port for {name}", {"output": out})

    def remove(self, name: str) -> None:
        self("rm", "--force", name, check=False)

    def remove_volume(self, volume: str) -> None:
        self("volume", "rm", "--force", volume, check=False)

    def remove_image(self, tag: str) -> None:
        self("image", "rm", tag, check=False)

    def logs(self, name: str, tail: int = 50) -> str:
        return self("logs", "--tail", str(tail), name, check=False)

    def read_file(self, name: str, path: str) -> str:
        return self("exec", name, "cat", path, check=False)


class DockerRoad(Road):
    """The product as a container: one image per revision, one container per environment and
    slot, a named volume for `/data` (the environment's volume for `current`)."""

    kind = "docker"

    def __init__(self, name, cfg, docker=None):
        super().__init__(name, cfg)
        self.docker = docker or DockerCLI(cfg.get("docker_cli", "docker"))

    def hosts_twin(self) -> bool:
        return True

    def missing(self):
        return [] if self.docker.available() else ["the docker CLI is not on PATH on the deploying host"]

    def image(self, project, revision: str) -> str:
        return f"gf-{project.pid}:{revision[:12]}"

    def target(self, project, env, slot, release, revision, artifact):
        base = f"gf-{project.pid}-{env}"
        port = (self.cfg.get("ports") or {}).get(env) if slot == "current" else None
        return {"container": f"{base}-{slot}", "volume": f"{base}-data" if slot == "current" else f"{base}-{slot}-data",
                "bind": self.cfg.get("bind", "127.0.0.1"), "host_port": port, "container_port": APP_PORT,
                "restart": "unless-stopped",
                "command": None if self.cfg.get("use_image_cmd") else list(self.cfg.get("command") or ["python3", *LAUNCH]),
                "labels": {"gnomonfactory.project": project.pid, "gnomonfactory.env": env,
                           "gnomonfactory.slot": slot, "gnomonfactory.release": str(release)}}

    def build(self, project, revision):
        work = checkout(project, revision)
        tag = self.image(project, revision)
        self.docker.build(work, tag, labels={"gnomonfactory.project": project.pid, "gnomonfactory.revision": revision})
        return {"type": "image", "ref": tag, "id": self.docker.image_id(tag)}

    def deploy(self, project, package):
        env, slot, t = package["environment"], package["slot"], package["target"]
        self.stop(project, env, slot)
        if slot != "current":
            self.docker.remove_volume(t["volume"])
        self.docker.run(t["container"], package["artifact"]["ref"],
                        publish=f"{t['bind']}:{t['host_port'] or ''}:{APP_PORT}",
                        volume=f"{t['volume']}:{CONTAINER_DATA}",
                        env={"APP_VERSION": package["settings"]["APP_VERSION"], "TRAFFIC_LOG": CONTAINER_TRAFFIC},
                        labels=t["labels"], restart=t["restart"], command=t.get("command"))
        host = "127.0.0.1" if t["bind"] in ("0.0.0.0", "", "::") else t["bind"]
        port = self.docker.host_port(t["container"], APP_PORT)
        state = self._state(project, package, container=t["container"], volume=t["volume"], port=port,
                            base_url=f"http://{host}:{port}")
        _save_slot(project, state)
        try:
            state["health"] = wait_healthy(state["base_url"], version=package["revision"][:12],
                                           timeout=float(self.cfg.get("start_timeout", 60)))
        except RoadError as exc:
            exc.native["logs"] = self.docker.logs(t["container"])[-2000:]
            self.stop(project, env, slot)
            raise
        _save_slot(project, state)
        return state

    def stop(self, project, env, slot):
        state = slot_state(project, env, slot)
        self.docker.remove((state or {}).get("container") or f"gf-{project.pid}-{env}-{slot}")
        if state and slot != "current":
            self.docker.remove_volume(state["volume"])
        _clear_slot(project, env, slot)
        return state

    def read_traffic(self, project, env, slot="current"):
        state = slot_state(project, env, slot)
        if not state:
            return []
        return parse_traffic(self.docker.read_file(state["container"], CONTAINER_TRAFFIC))


# -- Azure Container Apps ---------------------------------------------------------------------

_APP_NAME = re.compile(r"^[a-z][a-z0-9-]{0,30}[a-z0-9]$")
_SECRET_REF_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
_ENV_CODE = {"preview": "pv", "demo": "dm", "staging": "st", "production": "pr"}
_SLOT_CODE = {"current": "", "candidate": "-c", "twin": "-t"}


def azure_app_name(pid: str, env: str, slot: str) -> str:
    """Container App names are at most 32 characters: a short project id, the env and slot codes."""
    slug, _, tail = pid.rpartition("-")
    short = (slug[:12].rstrip("-") + "-" + tail) if slug else pid[:19]
    return f"gf-{short}-{_ENV_CODE[env]}{_SLOT_CODE[slot]}"


class AzureContainerAppsRoad(Road):
    """Renders an Azure Container Apps YAML and the `az` plan; deploys only when IT has
    configured the road, named an identity, and the `az` CLI is on PATH."""

    kind = "azure-containerapps"

    def __init__(self, name, cfg, az=None):
        super().__init__(name, cfg)
        self.az = az  # runner(argv, timeout) -> (exit, stdout, stderr); None means subprocess

    def az_available(self) -> bool:
        return self.az is not None or shutil.which("az") is not None

    def missing(self):
        out = []
        if not self.cfg.get("identity"):
            out.append(f"road {self.name!r} names no identity to deploy as (identity)")
        for key in ("subscription", "resource_group", "environment", "registry"):
            if not self.cfg.get(key):
                out.append(f"road {self.name!r} has no {key}")
        if not self.rules.get("region"):
            out.append(f"road {self.name!r} has no rules.region")
        if not self.az_available():
            out.append("the az CLI is not on PATH on the deploying host")
        return out

    def image(self, project, revision):
        return f"{self.cfg.get('registry') or '<registry>'}/gf-{project.pid}:{revision[:12]}"

    def target(self, project, env, slot, release, revision, artifact):
        return {"app": azure_app_name(project.pid, env, slot), "subscription": self.cfg.get("subscription"),
                "resource_group": self.cfg.get("resource_group"), "environment": self.cfg.get("environment"),
                "registry": self.cfg.get("registry"), "region": self.rules.get("region"),
                "yaml": f"releases/{release}/containerapp-{env}-{slot}.yaml"}

    def model(self, project, pkg: dict) -> dict:
        t, rules, identity = pkg["target"], self.rules, self.cfg.get("identity")
        ingress_rules = rules.get("ingress") or {}
        env_vars = [{"name": k, "value": v} for k, v in pkg["settings"].items()]
        secrets = []
        for s in pkg["secrets"]:
            ref_name = re.sub(r"[^a-z0-9-]+", "-", s["name"].lower()).strip("-")
            secrets.append({"name": ref_name, "keyVaultUrl": s["ref"], "identity": identity or "<identity>"})
            env_vars.append({"name": s["name"], "secretRef": ref_name})
        container = {"name": "app", "image": pkg["artifact"]["ref"], "env": env_vars,
                     "resources": {"cpu": float(self.cfg.get("cpu", 0.5)), "memory": self.cfg.get("memory", "1Gi")},
                     "probes": [{"type": "Liveness", "httpGet": {"path": "/health", "port": APP_PORT}},
                                {"type": "Readiness", "httpGet": {"path": "/health", "port": APP_PORT}}],
                     "volumeMounts": [{"volumeName": "data", "mountPath": CONTAINER_DATA}]}
        storage = self.cfg.get("storage") if pkg["slot"] == "current" else None
        volume = {"name": "data", "storageType": "AzureFile", "storageName": storage} if storage \
            else {"name": "data", "storageType": "EmptyDir"}
        configuration = {
            "activeRevisionsMode": "Single",
            "ingress": {"external": bool(ingress_rules.get("external", True)), "targetPort": APP_PORT,
                        "transport": ingress_rules.get("transport", "auto"),
                        "allowInsecure": not (rules.get("tls", "required") == "required")},
        }
        if identity:
            configuration["registries"] = [{"server": t["registry"], "identity": identity}]
        if secrets:
            configuration["secrets"] = secrets
        model = {
            "name": t["app"], "type": "Microsoft.App/containerApps", "location": t["region"],
            "properties": {
                "managedEnvironmentId": (f"/subscriptions/{t['subscription']}/resourceGroups/{t['resource_group']}"
                                         f"/providers/Microsoft.App/managedEnvironments/{t['environment']}"),
                "configuration": configuration,
                # One replica: the paved-road product keeps JSON files on one volume, one writer.
                "template": {"containers": [container], "scale": {"minReplicas": 1, "maxReplicas": 1},
                             "volumes": [volume]},
            },
            "tags": {"gnomonfactory-project": project.pid, "gnomonfactory-release": str(pkg["release"]),
                     "gnomonfactory-env": pkg["environment"], "gnomonfactory-slot": pkg["slot"]},
        }
        if identity:
            model["identity"] = {"type": "UserAssigned", "userAssignedIdentities": {identity: {}}}
        return model

    def render(self, project, pkg):
        model = self.model(project, pkg)
        t = pkg["target"]
        group = ["--name", t["app"], "--resource-group", t["resource_group"] or "<resource_group>"]
        registry_name = (t["registry"] or "<registry>").split(".")[0]
        pkg["rendered"] = {
            "format": "azure-containerapps-yaml",
            "model": model,
            "yaml": to_yaml(model),
            "commands": {
                "login": ["az", "login", "--identity", "--resource-id", self.cfg.get("identity") or "<identity>"],
                "subscription": ["az", "account", "set", "--subscription", t["subscription"] or "<subscription>"],
                "build": ["az", "acr", "build", "--registry", registry_name, "--image",
                          f"gf-{project.pid}:{pkg['revision'][:12]}", "<checkout>"],
                "exists": ["az", "containerapp", "show", *group, "--output", "none"],
                "create": ["az", "containerapp", "create", *group, "--yaml", t["yaml"]],
                "update": ["az", "containerapp", "update", *group, "--yaml", t["yaml"]],
                "fqdn": ["az", "containerapp", "show", *group, "--query",
                         "properties.configuration.ingress.fqdn", "--output", "tsv"],
                "delete": ["az", "containerapp", "delete", *group, "--yes"],
            },
            # Egress is enforced by IT on the Container Apps environment's network, not in the
            # app's YAML: the package carries the rule so the deploy gate shows it beside the app.
            "egress": self.rules.get("egress"),
        }

    def _az(self, argv, *, check=True, timeout=1800) -> str:
        runner = self.az or _run_subprocess
        code, out, err = runner(argv, timeout)
        if check and code != 0:
            raise RoadError(f"{' '.join(argv[:3])} failed (exit {code})", {"argv": argv, "stderr": (err or "")[-2000:]})
        return (out or "").strip()

    def build(self, project, revision):
        if self.missing():
            raise RoadError("the Azure road is not ready", {"missing": self.missing()})
        work = checkout(project, revision)
        plan = self.package(project, env="production", slot="current", release=0, revision=revision,
                            artifact={"type": "image", "ref": self.image(project, revision)})["rendered"]["commands"]
        self._az(plan["login"])
        self._az(plan["subscription"])
        self._az([str(work) if a == "<checkout>" else a for a in plan["build"]])
        return {"type": "image", "ref": self.image(project, revision)}

    def deploy(self, project, package):
        """Runs the rendered plan. Not exercised by the tests: it needs a configured subscription."""
        if self.missing():
            raise RoadError("the Azure road is not ready", {"missing": self.missing()})
        problems = validate_package(package)
        if problems:
            raise RoadError("the deploy package is not valid", {"problems": problems})
        cmds = package["rendered"]["commands"]
        write_text(project.dir / package["target"]["yaml"], package["rendered"]["yaml"])
        yaml_path = str(project.dir / package["target"]["yaml"])
        self._az(cmds["login"])
        self._az(cmds["subscription"])
        exists = (self.az or _run_subprocess)(cmds["exists"], 300)[0] == 0
        self._az([yaml_path if a == package["target"]["yaml"] else a for a in cmds["update" if exists else "create"]])
        fqdn = self._az(cmds["fqdn"])
        state = self._state(project, package, app=package["target"]["app"], base_url=f"https://{fqdn}")
        _save_slot(project, state)
        state["health"] = wait_healthy(state["base_url"], version=package["revision"][:12],
                                       timeout=float(self.cfg.get("start_timeout", 600)))
        _save_slot(project, state)
        return state

    def stop(self, project, env, slot):
        state = slot_state(project, env, slot)
        if state and slot != "current":
            self._az(state["package"]["rendered"]["commands"]["delete"], check=False)
        _clear_slot(project, env, slot)
        return state


# -- validation ---------------------------------------------------------------------------------

def secret_leaks(obj, path: str = "$") -> list:
    """Every place in a package where a secret's value (rather than its name) appears."""
    out = []
    if isinstance(obj, dict):
        name = obj.get("name")
        if isinstance(name, str) and "value" in obj and SECRET_NAME.search(name) and obj["value"] not in (None, ""):
            out.append(f"{path}: {name} is given a literal value")
        for k, v in obj.items():
            if k in ("secrets", "road_problems") and isinstance(v, list):
                for i, s in enumerate(v):
                    if isinstance(s, dict) and "value" in s:
                        out.append(f"{path}.{k}[{i}]: secret {s.get('name')} carries a value")
            if k == "settings" and isinstance(v, dict):
                for sk, sv in v.items():
                    if SECRET_NAME.search(sk) and sv not in (None, ""):
                        out.append(f"{path}.settings.{sk}: a secret-like setting is given a literal value")
            if k != "road_problems":
                out += secret_leaks(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += secret_leaks(v, f"{path}[{i}]")
    return out


def validate_package(pkg: dict) -> list:
    """Structural problems with a deploy package; an empty list means it may be deployed."""
    problems = []
    for key in ("schema", "project", "release", "environment", "slot", "road", "revision", "artifact",
                "settings", "rules", "target"):
        if key not in pkg:
            problems.append(f"the package has no {key}")
    if problems:
        return problems
    if pkg["schema"] != PACKAGE_SCHEMA:
        problems.append(f"schema must be {PACKAGE_SCHEMA}")
    if pkg["environment"] not in ENVIRONMENTS:
        problems.append(f"environment must be one of {ENVIRONMENTS}")
    if pkg["slot"] not in SLOTS:
        problems.append(f"slot must be one of {SLOTS}")
    art = pkg["artifact"]
    if art.get("type") not in ("image", "process") or not art.get("ref"):
        problems.append("the artifact needs a type (image or process) and a ref")
    if art.get("type") == "process" and not art.get("command"):
        problems.append("a process artifact needs a command")
    if pkg["settings"].get("APP_VERSION") != str(pkg["revision"])[:12]:
        problems.append("settings.APP_VERSION must be the revision's first 12 characters")
    if not isinstance(pkg["rules"], dict):
        problems.append("rules must be an object")
    problems += pkg.get("road_problems") or []
    problems += secret_leaks({k: v for k, v in pkg.items() if k != "road_problems"})
    if pkg["road"].get("kind") == "azure-containerapps":
        problems += validate_containerapp(pkg)
    return problems


def validate_containerapp(pkg: dict) -> list:
    rendered = pkg.get("rendered") or {}
    model, text = rendered.get("model"), rendered.get("yaml")
    if not isinstance(model, dict) or not isinstance(text, str):
        return ["the Azure package has no rendered model and YAML"]
    problems = []
    try:
        if from_yaml(text) != model:
            problems.append("the rendered YAML does not read back as the model")
    except ValueError as exc:
        problems.append(f"the rendered YAML does not parse: {exc}")
    rules = pkg["rules"]
    if not _APP_NAME.match(model.get("name", "")) or "--" in model.get("name", ""):
        problems.append(f"name {model.get('name')!r} is not a valid Container App name")
    if model.get("type") != "Microsoft.App/containerApps":
        problems.append("type must be Microsoft.App/containerApps")
    region = model.get("location")
    if not region:
        problems.append("no location: the road's rules name no region")
    elif rules.get("regions") and region not in rules["regions"]:
        problems.append(f"location {region} is not among the road's regions {rules['regions']}")
    props = model.get("properties") or {}
    if not re.match(r"^/subscriptions/[^/<]+/resourceGroups/[^/<]+/providers/Microsoft\.App/managedEnvironments/[^/<]+$",
                    props.get("managedEnvironmentId", "")):
        problems.append("managedEnvironmentId is not a managed environment resource id")
    conf = props.get("configuration") or {}
    ingress = conf.get("ingress") or {}
    if rules.get("tls", "required") == "required" and ingress.get("allowInsecure") is not False:
        problems.append("the road requires TLS but ingress allows insecure HTTP")
    if ingress.get("targetPort") != APP_PORT:
        problems.append(f"ingress.targetPort must be {APP_PORT}")
    if ingress.get("transport") not in ("auto", "http", "http2"):
        problems.append("ingress.transport must be auto, http or http2")
    if "egress" not in rules:
        problems.append("the road declares no egress rule")
    for s in conf.get("secrets") or []:
        if set(s) - {"name", "keyVaultUrl", "identity"}:
            problems.append(f"secret {s.get('name')} must only reference a Key Vault secret")
        if not _SECRET_REF_NAME.match(s.get("name", "")):
            problems.append(f"secret name {s.get('name')!r} is not valid")
        if not str(s.get("keyVaultUrl", "")).startswith("https://"):
            problems.append(f"secret {s.get('name')} has no Key Vault URL")
    secret_names = {s.get("name") for s in conf.get("secrets") or []}
    containers = (props.get("template") or {}).get("containers") or []
    if len(containers) != 1:
        problems.append("the template must hold exactly one container")
    for c in containers:
        if not str(c.get("image", "")).endswith(":" + str(pkg["revision"])[:12]):
            problems.append("the container image is not tagged with the revision")
        for e in c.get("env") or []:
            if not e.get("name") or (("value" in e) == ("secretRef" in e)):
                problems.append(f"env {e.get('name')} must have exactly one of value or secretRef")
            elif "secretRef" in e and e["secretRef"] not in secret_names:
                problems.append(f"env {e['name']} refers to an unknown secret {e['secretRef']}")
    scale = (props.get("template") or {}).get("scale") or {}
    if scale.get("maxReplicas") != 1:
        problems.append("maxReplicas must be 1: the product keeps its data in files with one writer")
    identity = model.get("identity")
    if identity is not None:
        ids = list((identity.get("userAssignedIdentities") or {}))
        if identity.get("type") != "UserAssigned" or len(ids) != 1 or not ids[0].startswith("/subscriptions/"):
            problems.append("identity must be one user-assigned identity resource id")
    return problems


# -- a small YAML subset: what the Azure renderer writes, and a reader to check it ---------------

_PLAIN_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def _scalar(v) -> str:
    if isinstance(v, dict):
        return "{}"
    if isinstance(v, list):
        return "[]"
    return json.dumps(v, ensure_ascii=False)  # null, true, false, numbers, double-quoted strings


def _key(k: str) -> str:
    return k if _PLAIN_KEY.match(k) else json.dumps(k, ensure_ascii=False)


def _emit(obj, ind: int, lines: list) -> None:
    pad = " " * ind
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{_key(k)}:")
                _emit(v, ind + 2, lines)
            else:
                lines.append(f"{pad}{_key(k)}: {_scalar(v)}")
    else:
        for item in obj:
            if isinstance(item, dict) and item:
                sub: list = []
                _emit(item, ind + 2, sub)
                sub[0] = pad + "- " + sub[0][ind + 2:]
                lines.extend(sub)
            elif isinstance(item, list) and item:
                lines.append(pad + "-")
                _emit(item, ind + 2, lines)
            else:
                lines.append(pad + "- " + _scalar(item))


def to_yaml(obj: dict) -> str:
    lines: list = []
    _emit(obj, 0, lines)
    return "\n".join(lines) + "\n"


def _split_key(content: str):
    """(key, rest) for a mapping line, or None if the line is not a `key:` line."""
    if content.startswith('"'):
        try:
            key, end = json.JSONDecoder().raw_decode(content)
        except json.JSONDecodeError:
            return None
        rest = content[end:]
    else:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)", content)
        if not m:
            return None
        key, rest = m.group(1), content[m.end():]
    if rest == ":":
        return key, ""
    if rest.startswith(": "):
        return key, rest[2:].strip()
    return None


def _value(text: str, n: int):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise ValueError(f"line {n}: {text!r} is not a scalar this reader knows")


def from_yaml(text: str):
    """Read the YAML subset `to_yaml` writes: block mappings and sequences of JSON scalars."""
    lines = []
    for n, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw:
            raise ValueError(f"line {n}: a tab in the indentation")
        if raw.strip() and not raw.lstrip().startswith("#"):
            lines.append([len(raw) - len(raw.lstrip(" ")), raw.strip(), n])
    if not lines:
        return None
    value, i = _block(lines, 0, lines[0][0])
    if i != len(lines):
        raise ValueError(f"line {lines[i][2]}: unexpected indentation")
    return value


def _is_item(line) -> bool:
    return line[1] == "-" or line[1].startswith("- ")


def _block(lines, i, ind):
    return _seq(lines, i, ind) if _is_item(lines[i]) else _map(lines, i, ind)


def _map(lines, i, ind):
    out = {}
    while i < len(lines) and lines[i][0] == ind and not _is_item(lines[i]):
        kv = _split_key(lines[i][1])
        if kv is None:
            raise ValueError(f"line {lines[i][2]}: expected `key: value`")
        key, rest = kv
        if key in out:
            raise ValueError(f"line {lines[i][2]}: duplicate key {key!r}")
        i += 1
        if rest:
            out[key] = _value(rest, lines[i - 1][2])
        elif i < len(lines) and lines[i][0] > ind:
            out[key], i = _block(lines, i, lines[i][0])
        else:
            raise ValueError(f"line {lines[i - 1][2]}: {key!r} has no value")
    if i < len(lines) and lines[i][0] > ind:
        raise ValueError(f"line {lines[i][2]}: unexpected indentation")
    return out, i


def _seq(lines, i, ind):
    out = []
    while i < len(lines) and lines[i][0] == ind and _is_item(lines[i]):
        rest = lines[i][1][1:].strip()
        if not rest:
            i += 1
            if i >= len(lines) or lines[i][0] <= ind:
                raise ValueError(f"line {lines[i - 1][2]}: an empty item")
            value, i = _block(lines, i, lines[i][0])
        elif _split_key(rest) is not None:
            lines[i] = [ind + 2, rest, lines[i][2]]  # "- key: v" opens a mapping two columns in
            value, i = _map(lines, i, ind + 2)
        else:
            value, i = _value(rest, lines[i][2]), i + 1
        out.append(value)
    return out, i
