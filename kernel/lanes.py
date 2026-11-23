"""Lanes: the workspaces where Gnomon runs, one run at a time per lane (FR-C2, FR-F5).

A product lane is a clone of the product's repository. Its committed `.gnomon/` surface grants
nothing beyond Gnomon's defaults: no verify command and no wider shell. So it runs
**without anyone's trust grant**, clamped to the defaults. Verification is the kernel's job in
the gate, which keeps the verifier apart from the builder (FR-G6). An owner who trusts a lane
once can turn on Gnomon's in-loop verify as an upgrade.

The analyst lane holds no product code. Intake, spec and holdout prompts run there.
"""

from __future__ import annotations

import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path

from kernel.filelock import LockHeld, locked
from kernel.store import REPO_ROOT, read_json, write_json, write_text

LANES_ENV = "GF_LANES"
ROUTING_FILE = REPO_ROOT / "kernel" / "routing.json"
# A machine's own routing (a GPU box on its network, a private gateway), merged over the shipped
# file when it exists. It is gitignored, so no machine's address reaches the repository.
ROUTING_LOCAL_FILE = REPO_ROOT / "kernel" / "routing.local.json"
ROUTING_TABLES = ("roles", "models", "endpoints")
SCAFFOLD_MARKER = "(The rules above are Gnomon's `gnomon init` system prompt, verbatim."

# Shell commands no cell may run, whatever its role. These match Gnomon's defaults, so the
# surface grants nothing extra.
BASH_DENY = [
    r"\bgit\s+push\b",
    r"\bgit\s+(reset\s+--hard|clean\s+-[a-z]*f|checkout\s+--)\b",
    r"\bgit\s+branch\b[^|;&]*\s(-D\b|--delete\b)",
    r"\bgit\s+commit\b[^|;&]*--no-verify\b",
]
# Gnomon's machine-local directories: MACHINE_LOCAL_DIRS in packages/gnomon-cli/src/init.ts at
# v0.6.6, which `gnomon init` adds to .gitignore. The factory compiles lanes itself, so it keeps
# the same list out of every commit. 0.6.6 added .gnomon-inbox and .gnomon-proposals, and bounds a
# bash flood by spilling the rest to .gnomon-out/ (up to 64 MB a file).
GNOMON_MACHINE_LOCAL = [".gnomon-sessions/", ".gnomon-audit/", ".gnomon-out/", ".gnomon-jobs/", ".gnomon-loops/",
                        ".gnomon-shadow/", ".gnomon-skills/", ".gnomon-trials/", ".gnomon-inbox/",
                        ".gnomon-proposals/"]
IGNORED = [".gnomon-audit/", ".gnomon-sessions/", ".factory-tasks/", "__pycache__/", ".verify/"] + \
    [d for d in GNOMON_MACHINE_LOCAL if d not in (".gnomon-audit/", ".gnomon-sessions/")]


def lanes_root() -> Path:
    return Path(os.environ.get(LANES_ENV) or Path.home() / "gf-lanes")


def lock_path(lane_dir: Path) -> Path:
    lane_dir = Path(lane_dir)
    return lane_dir.parent / f".{lane_dir.name}.lock"


@contextmanager
def lane_lock(lane_dir: Path, *, blocking: bool = True):
    """One gnomon run per lane: two runs in one workspace flag each other's records as tampered."""
    with locked(lock_path(lane_dir), blocking=blocking):
        yield


def merge_routing(shipped: dict, overlay: dict) -> dict:
    """The overlay over the shipped routing. Each role, model and endpoint the overlay names
    replaces the shipped one whole (a role's fallback included); any other key it sets, such as
    `max_context_tokens`, replaces the shipped value. Nothing is removed."""
    merged = dict(shipped)
    for key, value in overlay.items():
        if key in ROUTING_TABLES:
            if not isinstance(value, dict):
                raise ValueError(f"{ROUTING_LOCAL_FILE.name}: {key} must be an object")
            merged[key] = {**(shipped.get(key) or {}), **value}
        else:
            merged[key] = value
    return merged


def read_routing(path: Path | None = None) -> dict | None:
    """The routing, unchecked: the file at ``path`` alone, or else the shipped file with this
    machine's ``kernel/routing.local.json`` merged over it when that exists. None when there is
    no routing file."""
    if path is not None:
        return read_json(path)
    routing = read_json(ROUTING_FILE)
    try:
        overlay = read_json(ROUTING_LOCAL_FILE)
    except ValueError as exc:
        raise ValueError(f"{ROUTING_LOCAL_FILE.name} is not valid JSON: {exc}") from exc
    if routing is None or overlay is None:
        return routing
    if not isinstance(overlay, dict):
        raise ValueError(f"{ROUTING_LOCAL_FILE.name} must hold one JSON object")
    return merge_routing(routing, overlay)


def load_routing(path: Path | None = None) -> dict:
    """The routing the factory runs on (``read_routing``), checked (FR-G6)."""
    routing = read_routing(path)
    if routing is None:
        raise FileNotFoundError(f"no routing file at {path or ROUTING_FILE}")
    check_routing(routing)
    return routing


def model_family(routing: dict, role: str) -> str:
    model = routing["roles"][role]["model"]
    return routing["models"].get(model, {}).get("family", model.split("-")[0])


def check_routing(routing: dict) -> None:
    """The verifier must come from another model family than the builder (FR-G6)."""
    roles = routing.get("roles", {})
    for needed in ("analyst", "builder", "verifier"):
        if needed not in roles:
            raise ValueError(f"routing has no role {needed!r}")
    if model_family(routing, "verifier") == model_family(routing, "builder"):
        raise ValueError("the verifier must be a different model family from the builder "
                         f"(both are {model_family(routing, 'builder')})")
    fb = roles["builder"].get("fallback")
    if fb:
        fam = routing["models"].get(fb["model"], {}).get("family", fb["model"].split("-")[0])
        if fam == model_family(routing, "verifier"):
            raise ValueError("the builder's fallback must also be a different model family from the verifier "
                             f"(both are {fam})")
    if roles["verifier"].get("fallback"):
        raise ValueError("the verifier has no fallback: a judge from the builder's family is no judge; "
                         "an unavailable verifier makes the verdict not measured")


def _toml_str(value: str) -> str:
    return json.dumps(value)


def _toml_list(items) -> str:
    return "[" + ", ".join(_toml_str(i) for i in items) + "]"


def scaffold_system_md() -> str:
    """Gnomon's own `gnomon init` system prompt, taken from the factory's surface."""
    text = (REPO_ROOT / ".gnomon" / "system.md").read_text(encoding="utf-8")
    cut = text.find(SCAFFOLD_MARKER)
    return (text[:cut] if cut != -1 else text).rstrip() + "\n"


def _window(value) -> str:
    """An endpoint's `max_context_tokens`: a positive whole number, or "auto" (CONTRACTS §24)."""
    if value == "auto":
        return _toml_str(value)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return str(value)
    raise ValueError(f"an endpoint's max_context_tokens must be a positive whole number or \"auto\", got {value!r}")


def config_toml(routing: dict, roles_used) -> str:
    """The lane's config.toml.

    Since Gnomon 0.6.6 (and the master build 0.6.5+fb458ea5) `[defaults] max_context_tokens` is
    only the fallback window: an endpoint that declares no number is asked for its own (its
    listing, then Gnomon's catalog), and the fallback applies when that finds nothing. To cap a
    model's window, the routing names `max_context_tokens` on the endpoint; it is compiled onto
    `[endpoints.<name>]`, where it wins and nothing is asked."""
    endpoints = sorted({routing["roles"][r]["endpoint"] for r in roles_used}
                       | {routing["roles"][r]["fallback"]["endpoint"] for r in roles_used
                          if routing["roles"][r].get("fallback")})
    lines = ["# Compiled by Rihma (kernel/lanes.py). Do not edit by hand.", "",
             "[defaults]", f"max_context_tokens = {routing.get('max_context_tokens', 98304)}", "",
             "[resilience]", "request_timeout_ms = 300000", ""]
    for name in endpoints:
        ep = routing["endpoints"][name]
        lines += [f"[endpoints.{name}]", f"kind = {_toml_str(ep['kind'])}", f"url = {_toml_str(ep['url'])}"]
        if ep.get("api_key_env"):
            lines.append(f"api_key_env = {_toml_str(ep['api_key_env'])}")
        if ep.get("max_context_tokens") is not None:
            lines.append(f"max_context_tokens = {_window(ep['max_context_tokens'])}")
        lines.append("")
    lines += ["[audit]", "enabled = true", 'dir = ".gnomon-audit"', 'record = "metadata"', "chain = true", ""]
    return "\n".join(lines)


def _role_block(name: str, spec: dict, *, tools, write_allow=None, steps=(30, 120),
                description: str = "") -> list[str]:
    lines = [f"[roles.{name}]", f"model = {_toml_str(spec['model'])}", f"endpoint = {_toml_str(spec['endpoint'])}",
             f"max_steps = {steps[0]}", f"max_steps_total = {steps[1]}", f"tools = {_toml_list(tools)}"]
    if write_allow:
        lines.append(f"write_allow = {_toml_list(write_allow)}")
    if "bash" in tools:
        lines.append("bash_deny = [")
        lines += [f"  {_toml_str(p)}," for p in BASH_DENY]
        lines.append("]")
    if description:
        lines.append(f"description = {_toml_str(description)}")
    lines.append("")
    if spec.get("fallback"):  # Gnomon switches to it when the primary endpoint fails (rate limits, outages)
        fb = spec["fallback"]
        lines += [f"[roles.{name}.fallback]", f"model = {_toml_str(fb['model'])}",
                  f"endpoint = {_toml_str(fb['endpoint'])}", ""]
    return lines


POLICY_TOML = """# Compiled by Rihma. Grants nothing beyond Gnomon's defaults: no verify command,
# no wider shell. The kernel runs the checks in the gate, apart from the builder.

[approval]
gate = "on_write"

[sandbox]
level = "confined"
network = false
"""

# The product lane's own part of system.md, after Gnomon's `init` prompt (both of its roles have
# tools). It is role-neutral: the builder and the verifier read the same file, so a rule only one of
# them can follow lives in that role's task, not here. The builder's rules (a failing test first,
# the unittest check, the standard library only, the report) are in its envelope
# (kernel/dispatch.py); the verifier's are in its prompt (kernel/gate.py). FR-Z1-AC-2.
PRODUCT_RULES = """
(The rules above are Gnomon's `gnomon init` system prompt, verbatim. What follows is this product.)

This repository is a product built by Rihma. Your task file says what your role does here, which
paths you may write, and how the work is checked; the rules for your role are in it.

For every role:
- `.gnomon/`, `contract.json` and `factory/` are read-only. Write nothing outside the paths your
  task names; a task that names none allows no writes.
- `tests/test_road_contract.py` is the paved road's own check: read-only too.
- Files you write use LF line endings.
"""


# What PRODUCT_RULES makes read-only. The gate refuses a builder cell's change that touches one, and
# a workspace's submission (kernel/gate.py, kernel/workspace.py). The last is the paved road's own
# tests (kernel/scaffold.py ROAD_CONTRACT_TESTS): Gnomon's write_allow has no exclusions, so `tests/**`
# lets the write tool reach it, and this check is what refuses the change (FR-DF1-AC-2).
PROTECTED = (".gnomon/", "contract.json", "factory/", "tests/test_road_contract.py")


def protected_paths(repo_dir: Path, base: str, head: str) -> list[str]:
    """The paths a change from ``base`` to ``head`` touches that no cell may write. Renames count
    as a delete and an add (so a protected file moved away is seen), names are not quoted, and the
    match ignores case: `.GNOMON/roles.toml` is `.gnomon/roles.toml` on Windows and macOS."""
    proc = subprocess.run(["git", "-c", "core.quotePath=false", "diff", "--name-only", "--no-renames", "-z",
                           f"{base}...{head}", "--"], cwd=repo_dir, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git diff {base[:12]}...{head[:12]} failed in {repo_dir}: "
                           f"{proc.stderr.decode('utf-8', 'replace').strip()}")
    names = [n.decode("utf-8", "replace") for n in proc.stdout.split(b"\0") if n]
    folded = [(n, n.casefold()) for n in names]
    return [n for n, f in folded
            if any(f == p.casefold().rstrip("/") or f.startswith(p.casefold()) for p in PROTECTED)]


def write_product_surface(repo_dir: Path, routing: dict, write_allow) -> None:
    """The `.gnomon/` surface of a product repository: builder and verifier, nothing extra."""
    g = Path(repo_dir) / ".gnomon"
    roles = ["# Compiled by Rihma (kernel/lanes.py). Do not edit by hand.", ""]
    roles += _role_block("builder", routing["roles"]["builder"],
                         tools=["read", "glob", "grep", "write", "edit", "bash", "todo"],
                         write_allow=list(write_allow), steps=(40, 160),
                         description="Implements inside its write scope; each criterion gets a test that fails first.")
    roles += _role_block("verifier", routing["roles"]["verifier"], tools=["read", "glob", "grep"],
                         steps=(25, 60), description="Read-only. Tries to break the change.")
    write_text(g / "roles.toml", "\n".join(roles))
    write_text(g / "config.toml", config_toml(routing, ["builder", "verifier"]))
    write_text(g / "policy.toml", POLICY_TOML)
    write_text(g / "system.md", product_system_md())
    write_text(g / "tools.toml", (REPO_ROOT / ".gnomon" / "tools.toml").read_text(encoding="utf-8"))


def product_system_md() -> str:
    """A product lane's system.md: Gnomon's `init` prompt, then the role-neutral product rules."""
    return scaffold_system_md() + PRODUCT_RULES


# The analyst lane's whole system.md. Its roles have no tools, so Gnomon's `init` prompt (use the
# declared tools, compute through `compute`, run what you produced) would contradict them; this
# short prompt replaces it (FR-Z1-AC-1).
ANALYST_RULES = """You work in Rihma's analyst lane. Rihma is a governed software factory: people decide
what gets built, and your answers inform them. Your task is one of: reviewing a request, writing a
specification or acceptance scenarios, or answering a question about the cockpit from a snapshot.

You have no tools and need none: the task holds everything you need. Answer only from it; where it
is silent, say what is missing instead of inventing a fact, a number or an id.

When the task asks for JSON, answer with one JSON value in a ```json fenced block, in the shape it
asks for, and nothing after it.
"""


def analyst_system_md() -> str:
    """The analyst lane's system.md: its own short prompt, without Gnomon's tool-use rules."""
    return ANALYST_RULES


# The toolless roles that answer from their task file: intake and spec, holdout scenarios, and the
# cockpit assistant, which answers from a snapshot and only proposes actions.
ANALYST_LANE_ROLES = ("analyst", "holdout_author", "assistant")


def ensure_analyst_lane(routing: dict, root: Path | None = None) -> Path:
    """The lane where intake, spec and holdout prompts run. It holds no product code."""
    lane = (root or lanes_root()) / "analyst"
    g = lane / ".gnomon"
    g.mkdir(parents=True, exist_ok=True)
    roles = ["# Compiled by Rihma (kernel/lanes.py). Do not edit by hand.", ""]
    for role in ANALYST_LANE_ROLES:
        spec = routing["roles"].get(role) or routing["roles"]["analyst"]
        roles += _role_block(role, spec, tools=[], steps=(2, 4),
                             description="Answers from its task file. Has no tools, so it cannot wander.")
    write_text(g / "roles.toml", "\n".join(roles))
    used = ["analyst"] + [r for r in ANALYST_LANE_ROLES[1:] if r in routing["roles"]]
    write_text(g / "config.toml", config_toml(routing, used))
    write_text(g / "policy.toml", POLICY_TOML)
    write_text(g / "system.md", analyst_system_md())
    write_text(g / "tools.toml", (REPO_ROOT / ".gnomon" / "tools.toml").read_text(encoding="utf-8"))
    if not (lane / ".git").exists():
        _git(lane, "init", "-q", "-b", "main")
    write_text(lane / ".gitignore", "\n".join(IGNORED) + "\n")
    return lane


def _git(cwd: Path, *args, check: bool = True) -> str:
    """Run the kernel's git. It names itself (KERNEL_GIT_ENV), which a guarded product repository
    asks of anyone who moves main (``guard_repo``)."""
    env = dict(os.environ)
    env[KERNEL_GIT_ENV] = "1"
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", env=env)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()}")
    return proc.stdout.strip()


GIT_ID = ["-c", "user.name=Rihma kernel", "-c", "user.email=kernel@rihma.local"]
KERNEL_GIT_ENV = "RIHMA_KERNEL_GIT"
GUARD_MARK = "# rihma: guarded product repository"
# The product repository's pre-receive hook once a workspace is opened on it: main, the cells'
# branches and the judged heads move only through the kernel's own git, so a person or the agent
# in their terminal who pushes there by hand is told to submit instead. Ref names are compared in
# lower case, since refs/heads/MAIN is refs/heads/main on a case-insensitive file system. It is a
# guard rail, not a boundary against someone who can write the repository's files.
PRE_RECEIVE = GUARD_MARK + """
if [ -n "$RIHMA_KERNEL_GIT" ]; then exit 0; fi
status=0
while read -r old new ref; do
  lower=$(printf '%s' "$ref" | tr '[:upper:]' '[:lower:]')
  case "$lower" in
    refs/heads/main|refs/heads/cell/*|refs/rihma/*)
      echo "rihma: $ref moves only through the gate. Submit your work: rihma workspace submit" >&2
      status=1;;
  esac
done
exit $status
"""


def guard_repo(repo: Path) -> bool:
    """Install the guard (PRE_RECEIVE) in a bare product repository. A pre-receive hook someone
    else put there is left alone. Returns whether the guard is in place."""
    repo = Path(repo)
    if not (repo / "objects").is_dir() or not (repo / "refs").is_dir():
        return False
    hook = repo / "hooks" / "pre-receive"
    text = "#!/bin/sh\n" + PRE_RECEIVE
    if hook.exists():
        current = hook.read_text(encoding="utf-8", errors="replace")
        if GUARD_MARK not in current:
            return False
        if current == text:
            return True
    write_text(hook, text)
    os.chmod(hook, 0o755)
    return True


class Lane:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.name = self.path.name

    def git(self, *args, check: bool = True) -> str:
        return _git(self.path, *args, check=check)

    def checkout(self, repo: Path, branch: str, base: str = "main") -> str:
        """A clean working tree on a new branch from the product's ``base``."""
        if not (self.path / ".git").exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            _git(self.path.parent, "clone", "-q", str(repo), self.path.name)
        else:
            self.git("remote", "set-url", "origin", str(repo))
        self.git("fetch", "-q", "origin")
        self.git("checkout", "-q", "-B", branch, f"origin/{base}")
        self.git("clean", "-q", "-fdx", "-e", ".gnomon-audit", "-e", ".gnomon-sessions", "-e", ".factory-tasks")
        exclude = self.path / ".git" / "info" / "exclude"
        text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        missing = [i for i in IGNORED if i not in text]
        if missing:
            write_text(exclude, text + "".join(f"{i}\n" for i in missing))
        return self.head()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def changed(self) -> list[str]:
        out = self.git("status", "--porcelain", "--untracked-files=all")
        return [line[3:] for line in out.splitlines() if line.strip()]

    def commit_all(self, message: str) -> str:
        self.git("add", "-A")
        if not self.git("status", "--porcelain"):
            return self.head()
        self.git(*GIT_ID, "commit", "-q", "-m", message)
        return self.head()

    def push(self, branch: str, target: str | None = None) -> None:
        self.git("push", "-q", "origin", f"{branch}:{target or branch}")


class Lanes:
    """The pool. A lease is the lane's lock: one holder at a time (FR-F5)."""

    def __init__(self, root: Path | None = None, size: int | None = None):
        self.root = Path(root or lanes_root())
        self.size = size if size is not None else int(os.environ.get("GF_LANES_SIZE", "3"))

    def paths(self) -> list[Path]:
        return [self.root / f"lane-{i}" for i in range(1, self.size + 1)]

    def _try(self, candidates):
        for path in candidates:
            lock = lane_lock(path, blocking=False)
            try:
                lock.__enter__()
            except LockHeld:
                continue
            return path, lock
        return None, None

    @contextmanager
    def lease(self, holder: str, *, lane: str | None = None, wait: float = 0, poll: float = 5):
        """Hold one lane. With ``wait`` > 0, a holder that finds every lane taken waits (up to
        ``wait`` seconds) for one to come free instead of failing; a lane is never shared."""
        import time

        candidates = [self.root / lane] if lane else self.paths()
        deadline = time.monotonic() + max(0.0, wait)
        path, lock = self._try(candidates)
        while path is None and time.monotonic() < deadline:
            time.sleep(min(poll, max(0.0, deadline - time.monotonic())))
            path, lock = self._try(candidates)
        if path is None:
            raise LockHeld(f"no free lane among {[p.name for p in candidates]} for {holder}")
        lease_file = path.parent / f".{path.name}.lease.json"
        try:
            # The holder's process and when it took the lane: a reader can tell a holder that died
            # (its lock is free again) and the trails an earlier holder left in the lane.
            write_json(lease_file, {"holder": holder, "pid": os.getpid(), "since": time.time()})
            yield Lane(path)
        finally:
            write_json(lease_file, {"holder": None})
            lock.__exit__(None, None, None)
