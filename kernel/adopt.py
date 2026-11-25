"""Brownfield adoption: an existing solution enters the factory to be monitored, maintained or improved.

`adopt` takes a git repository (a local path, or a URL that `git clone` reads without
credentials) and makes it a project. A local folder that is not a git repository is snapshotted
first into a repository under the factory home (kernel/material_adopt.py), and a folder holding no
code is refused as material for a new project. The checkout's documents are scanned as context
(kernel/material.py), and a confidential adoption is held to local models (kernel/confidential.py):

- **Mirror.** The code is fetched into the project's `repo.git`. The upstream's default branch
  at adoption is the **baseline**; `main` is the baseline plus one kernel commit that puts the
  kernel's own compiled `.gnomon/` surface there. An upstream's own `.gnomon/` (its endpoints,
  keys, roles and prompts), Gnomon's machine-local directories and `.lfsconfig` are removed in
  that commit, under any name a file system opens them by (`.GNOMON`, the 8.3 short name
  `GNOMON~1`, `.gnomon.`): every later checkout of main (a builder cell, the gate's verifier, a
  workspace) runs under the kernel's surface, never one the upstream wrote. The upstream is a
  fetch-only remote: its push URL is disabled, and nothing in the kernel pushes there.
- **No credentials.** Credential helpers, prompts and Git LFS downloads are switched off for every
  git call adoption makes that reads the upstream, its checkout included; a URL (or a `base_url`)
  that carries a user, a password, a token or a query is refused. A later checkout of main runs
  git-lfs under its owner's git configuration, but main carries no `.lfsconfig` of the upstream's,
  so the only address git-lfs knows there is the clone's own origin, the local `repo.git` (which
  holds no LFS object: LFS content is never downloaded), never one the upstream chose. A private
  repository is cloned by its owner first and adopted from that local path.
- **Inventory, by rule, no model.** Languages by file extension, the test command found by rule
  (detected or not, never guessed; a test command the team's own CLAUDE.md or AGENTS.md states comes
  first when the kernel runs it, kernel/agent_context_use.py), the README's first paragraph, the HTTP routes the source
  declares (only when a `base_url` is given), and whether there is a Dockerfile. Only regular
  files inside the checkout are read: a symlink is never followed.
- **Characterisation baseline.** A detected Python suite runs once in a temporary checkout,
  with a per-suite timeout (`SUITE_TIMEOUT`, apart from git's): a suite still running then is
  "not measured: timed out". Its counts are evidence of *existing behaviour, not a spec*. Other toolchains
  run only when their tool is on PATH, offline; otherwise the baseline says "not measured:
  toolchain not run by the kernel". It is "passed" only when at least one test passed: zero
  tests, every test skipped, an unreadable summary or a missing dependency are "not measured".
  Running the suite runs the adopted code on this machine: stdin is closed, and the timeout, like
  the end of the run, stops every process the suite started.
- **As-is spec.** One requirement of `observed` provenance whose criteria are "the existing test
  suite keeps passing", and, with a `base_url`, one whose probe is "GET <base_url> answers". It
  compiles to a contract and a check plan like any spec (the contract's vocabulary has no
  observed tier, so the compiler names it there; see `kernel/compile.py`).
- **Stage.** `monitor` goes to stage 7, probing `base_url` (a server error is not a healthy
  answer). `maintain` and `improve` wait at stage 5: the as-is tasks are the existing code, so
  nothing is built until a change arrives through the change loop or a person's workspace.

Everything that reads the upstream runs before the project exists, and a failure after it exists
removes it again: nothing is left half-adopted.

`sync` fetches the upstream again and records the drift since the baseline. When the upstream
moved since the last look, a change card "Upstream changed: review" is opened for people to
decide; `main` is never moved by a sync. A tracked branch that is gone upstream (a renamed default
branch) is said so, once, on a change card of its own.
"""

from __future__ import annotations

import contextlib
import functools
import importlib.util
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from kernel.lanes import GNOMON_MACHINE_LOCAL, _git
from kernel.people import PERSONAS, is_person
from kernel.store import write_json, write_text

INTENTS = ("monitor", "maintain", "improve")
CHARACTERISATION = "existing behaviour, not a spec"
OBSERVED = "observed"
# The upstream's push URL. Git cannot push to a transport that does not exist, so even a person
# running `git push upstream` inside repo.git by hand is refused.
NO_PUSH = "rihma-never-pushes-upstream://read-only"
NO_CREDENTIALS = ["-c", "credential.helper=", "-c", "core.askPass=", "-c", "protocol.ext.allow=never"]
# curl gives up on a transfer slower than 1 kB/s for 30 s, so a stalled upstream cannot hold a
# fetch open until the timeout (and the timeout stops git and every helper it started).
NET_LIMITS = ["-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=30"]
URL_SCHEMES = ("https", "http", "git", "file")
VENDORED = ("node_modules/", "vendor/", ".venv/", "venv/", "site-packages/", "dist/", "build/", ".git/")
MAX_SCAN_BYTES = 512 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_ENDPOINTS = 200
# Each detected suite's run is bounded by its own limit, apart from git's (FR-DF5): a baseline whose
# suite runs longer says "not measured: timed out" and adoption goes on, rather than waiting.
SUITE_TIMEOUT = 300
SURFACE_COMMIT = "The kernel's own .gnomon/ surface over the adopted baseline"
# Top-level names an adopted main holds only as the kernel wrote them: the `.gnomon/` surface the
# builder and the verifier run under, Gnomon's machine-local directories (its sessions, inbox,
# skills and records), and `.lfsconfig`, which names the address git-lfs asks the owner's
# credential helper for whenever main is checked out (a lane, a workspace, the gate).
KERNEL_HELD = (".gnomon", *(d.rstrip("/") for d in GNOMON_MACHINE_LOCAL), ".lfsconfig")
# Code points HFS+ leaves out of a file name (git's own check for `.git` skips the same ones).
_HFS_IGNORED = dict.fromkeys([0x200C, 0x200D, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x206A, 0x2070),
                              0xFEFF])
_SHORT_NAME = re.compile(r"([^~]{2,6})~[1-9][0-9]*")

LANGUAGES = {
    ".py": "Python", ".pyi": "Python", ".ipynb": "Jupyter Notebook", ".js": "JavaScript", ".mjs": "JavaScript",
    ".cjs": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go",
    ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala", ".cs": "C#",
    ".fs": "F#", ".vb": "Visual Basic", ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++", ".hpp": "C++",
    ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".m": "Objective-C", ".dart": "Dart", ".r": "R",
    ".lua": "Lua", ".pl": "Perl", ".ex": "Elixir", ".exs": "Elixir", ".erl": "Erlang", ".hs": "Haskell",
    ".clj": "Clojure", ".sh": "Shell", ".bash": "Shell", ".ps1": "PowerShell", ".sql": "SQL",
    ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "CSS", ".vue": "Vue", ".svelte": "Svelte",
    ".tf": "HCL",
}

# Windows: CREATE_SUSPENDED, and PROCESS_TERMINATE | PROCESS_SET_QUOTA | PROCESS_SUSPEND_RESUME.
_CREATE_SUSPENDED = 0x00000004
_PROCESS_ACCESS = 0x0001 | 0x0100 | 0x0800


class AdoptionRefused(ValueError):
    """The source cannot be adopted as given (credentials, an unknown transport, not a repository)."""


# -- running what the kernel does not trust to stop by itself -------------------------------------------

@functools.lru_cache(maxsize=1)
def _win32() -> Any:
    """kernel32 and ntdll, typed for the few calls a job object needs (Windows only)."""
    if sys.platform != "win32":
        raise OSError("a job object is a Windows thing")
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k32.AssignProcessToJobObject.restype = wintypes.BOOL
    k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    k32.TerminateJobObject.restype = wintypes.BOOL
    k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k32.CloseHandle.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtResumeProcess.restype = ctypes.c_long
    ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
    return k32, ntdll


def _join_job(pid: int) -> int | None:
    """Windows: put a process that was started suspended into a new job object, then let it run,
    so every process it starts is in the job too. Returns the job's handle, or None when Windows
    would not make one (taskkill's tree walk is then what is left). The process always runs on."""
    if sys.platform != "win32":
        return None
    import ctypes

    k32, ntdll = _win32()
    handle = k32.OpenProcess(_PROCESS_ACCESS, False, pid)
    if not handle:
        raise OSError(ctypes.get_last_error(), "the started process could not be opened")
    try:
        job = k32.CreateJobObjectW(None, None)
        if job and not k32.AssignProcessToJobObject(job, handle):
            k32.CloseHandle(job)
            job = None
        if ntdll.NtResumeProcess(handle) != 0:
            if job:
                k32.CloseHandle(job)
            raise OSError("the started process could not be resumed")
    finally:
        k32.CloseHandle(handle)
    return int(job) if job else None


def _spawn(argv: list[str], *, cwd: Path, env: dict[str, str], out: IO[bytes],
           err: IO[bytes]) -> tuple[subprocess.Popen[bytes], int | None]:
    """Start ``argv`` in a process group of its own, stdin closed, output to files. Returns the
    process and, on Windows, the job object that holds its whole tree."""
    if sys.platform != "win32":
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                start_new_session=True)
        return proc, None
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | _CREATE_SUSPENDED)
    try:
        return proc, _join_job(proc.pid)
    except BaseException:
        proc.kill()
        proc.wait()
        raise


def _stop(proc: subprocess.Popen[bytes], job: int | None) -> None:
    """Stop every process ``proc`` started, whether or not ``proc`` itself still runs: the job
    object on Windows, the process group on POSIX."""
    if sys.platform == "win32":
        if job:
            k32, _ = _win32()
            k32.TerminateJobObject(job, 1)
            k32.CloseHandle(job)
        elif proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
    if proc.poll() is None:
        proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=10)


def _tail(fh: IO[bytes]) -> str:
    size = fh.seek(0, os.SEEK_END)
    fh.seek(max(0, size - MAX_OUTPUT_BYTES))
    return fh.read().decode("utf-8", errors="replace")


def _run(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float) -> tuple[int, str, str]:
    """Run a command the kernel does not trust to stop by itself (an adopted test suite, git
    against an upstream). Output goes to files, never pipes, so a child left behind cannot keep
    the kernel waiting for the end of a pipe; on a timeout, and after the command exits, every
    process it started is stopped. Returns (exit code, stdout, stderr). Raises
    subprocess.TimeoutExpired on a timeout and OSError when the command cannot start."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc, job = _spawn(argv, cwd=cwd, env=env, out=out, err=err)
        try:
            code: int | None = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = None
        finally:
            _stop(proc, job)
        if code is None:
            raise subprocess.TimeoutExpired(argv, timeout)
        return code, _tail(out), _tail(err)


# -- git, without credentials ------------------------------------------------------------------------

def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    # No prompt, no askpass, and no Git LFS download during a checkout: git-lfs would go to the
    # address the repository's .lfsconfig names, and ask the owner's credential helper for it.
    # (Main carries no .lfsconfig of the upstream's, for the checkouts made outside adoption.)
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", GIT_ASKPASS="", SSH_ASKPASS="",
               GIT_LFS_SKIP_SMUDGE="1")
    return env


def _net(cwd: Path, *args: str, timeout: int = 300) -> str:
    """A git call that may reach the upstream or check out what it wrote: no credential helper, no
    prompt, no LFS download, curl's low-speed limit, and a timeout that stops git and every helper
    it started."""
    what = next((a for a in args if not a.startswith("-")), "")
    try:
        code, out, err = _run(["git", *NO_CREDENTIALS, *NET_LIMITS, *args], cwd=cwd, env=_git_env(),
                              timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git {what} did not finish in {timeout}s") from exc
    except OSError as exc:
        raise RuntimeError(f"git {what} could not start: {exc}") from exc
    if code != 0:
        raise RuntimeError(f"git {what} failed: {err.strip()[-300:]}")
    return out.strip()


def _git_read(cwd: Path, *args: str) -> str:
    """A local git call whose output carries what the upstream wrote (file names, commit messages,
    branch names): bytes that are not UTF-8 are replaced, never fatal."""
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, stdin=subprocess.DEVNULL, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: "
                           f"{proc.stderr.decode('utf-8', errors='replace').strip()}")
    return proc.stdout.decode("utf-8", errors="replace").strip()


def check_source(source) -> tuple[str, str]:
    """('path', absolute path) for a git repository, ('folder', absolute path) for a folder that is not one
    (kernel/material_adopt.py snapshots it), or ('url', url). Refuses anything that would need a credential."""
    text = str(source or "").strip()
    if not text:
        raise AdoptionRefused("no source given")
    if "::" in text.split("://", 1)[0]:
        raise AdoptionRefused("a git transport helper (<transport>::<address>) is not accepted")
    if "://" in text:
        parts = urllib.parse.urlsplit(text)
        if parts.scheme.lower() not in URL_SCHEMES:
            raise AdoptionRefused(f"only {', '.join(URL_SCHEMES)} URLs are adopted directly; for ssh or a private "
                                  "repository, clone it yourself and adopt the local path")
        if parts.username or parts.password or "@" in parts.netloc:
            raise AdoptionRefused("the URL carries a user or a credential; Rihma never handles credentials: clone it "
                                  "yourself and adopt the local path")
        if parts.query or parts.fragment:
            raise AdoptionRefused("a clone URL carries no query or fragment (credentials never pass through Rihma)")
        return "url", text
    if re.match(r"^[\w.+-]+@[\w.-]+:", text):
        raise AdoptionRefused("an ssh address needs a key; clone it yourself and adopt the local path")
    path = Path(text).expanduser().resolve()
    if not path.is_dir():
        raise AdoptionRefused(f"{path} is not a directory")
    proc = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=path, capture_output=True, text=True)
    return ("path" if proc.returncode == 0 else "folder"), str(path)


def _default_branch(bare: Path, location: str) -> str:
    try:
        out = _net(bare, "ls-remote", "--symref", location, "HEAD", timeout=120)
        m = re.search(r"^ref:\s+refs/heads/(\S+)\s+HEAD", out, re.MULTILINE)
        if m:
            return m.group(1)
    except RuntimeError:
        pass
    branches = _git_read(bare, "for-each-ref", "--format=%(refname:strip=3)", "refs/remotes/upstream").split()
    for name in ("main", "master", "trunk", "develop"):
        if name in branches:
            return name
    if not branches:
        raise AdoptionRefused("the source has no branch with commits")
    return sorted(branches)[0]


def _mirror(dest: Path, location: str, *, timeout: int) -> tuple[str, str]:
    """A bare repository at ``dest`` holding the upstream as a fetch-only remote, with main at
    the upstream's default branch. Returns (default branch, baseline revision)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    _git(dest.parent, "init", "-q", "--bare", "-b", "main", dest.name)
    _git(dest, "remote", "add", "upstream", location)
    _git(dest, "config", "remote.upstream.pushurl", NO_PUSH)
    _git(dest, "config", "remote.upstream.fetch", "+refs/heads/*:refs/remotes/upstream/*")
    _git(dest, "config", "remote.upstream.tagOpt", "--no-tags")
    _net(dest, "fetch", "-q", "upstream", timeout=timeout)
    branch = _default_branch(dest, location)
    baseline = _git(dest, "rev-parse", f"refs/remotes/upstream/{branch}")
    _git(dest, "update-ref", "refs/heads/main", baseline)
    return branch, baseline


def _opens(name: str, target: str) -> bool:
    """Whether a top-level ``name`` may open ``target`` on a file system the factory runs on: the
    same name in another case (NTFS, APFS, HFS+), with what NTFS drops (trailing dots and spaces, a
    `:stream`) or what HFS+ ignores, or an 8.3 short name Windows gives it (`GNOMON~1`, `GNOMO~12`,
    or its first two letters, up to four hex digits and a tilde: `GN4F2A~5`)."""
    plain = unicodedata.normalize("NFC", name.translate(_HFS_IGNORED)).split(":", 1)[0].rstrip(" .")
    if plain.casefold() == target.casefold() or plain.upper() == target.upper():
        return True
    short = _SHORT_NAME.fullmatch(plain.upper())
    if short is None or len(plain) > 8:
        return False
    stem, base = short.group(1), target.upper().replace(".", "").replace(" ", "")
    return stem[:2] == base[:2] and (base.startswith(stem) or re.fullmatch(r"[0-9A-F]{0,4}", stem[2:]) is not None)


def _held_by_upstream(work: Path) -> list[bytes]:
    """The index paths, as git stores them, whose first component opens a name the kernel holds on
    main (KERNEL_HELD): what a checkout of main would write into the kernel's surface."""
    proc = subprocess.run(["git", "ls-files", "-z"], cwd=work, capture_output=True, stdin=subprocess.DEVNULL,
                          check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-files failed in {work}: {proc.stderr.decode('utf-8', errors='replace').strip()}")
    held = []
    for path in filter(None, proc.stdout.split(b"\0")):
        first = re.split(rb"[/\\]", path, maxsplit=1)[0].decode("utf-8", errors="replace")
        if any(_opens(first, name) for name in KERNEL_HELD):
            held.append(path)
    return held


def _unstage(work: Path, paths: list[bytes]) -> None:
    """Remove exactly these paths from the index (no pathspec, so no case folding or globbing)."""
    proc = subprocess.run(["git", "update-index", "--force-remove", "-z", "--stdin"], cwd=work,
                          input=b"".join(p + b"\0" for p in paths), capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"git update-index failed in {work}: "
                           f"{proc.stderr.decode('utf-8', errors='replace').strip()}")


def _own_surface(bare: Path, scratch: Path, baseline: str, *, timeout: int, confidential: bool = False) -> dict[str, Any]:
    """Put the kernel's compiled `.gnomon/` surface on main, over the baseline, as one kernel
    commit. What the upstream holds under a name the kernel holds (KERNEL_HELD), in any case or
    short name, is removed in the same commit. Plumbing only: nothing is checked out, and no filter
    that the upstream's attributes name runs on the surface. A confidential adoption's surface names
    no hosted fallback (kernel/confidential.py)."""
    from kernel.compile import WRITE_SCOPE
    from kernel.confidential import without_hosted_fallbacks
    from kernel.lanes import GIT_ID, load_routing, write_product_surface

    work = scratch / "surface"
    _net(scratch, "clone", "-q", "--no-checkout", str(bare), work.name, timeout=timeout)
    _git(work, "read-tree", baseline)
    upstream = _held_by_upstream(work)
    if upstream:
        _unstage(work, upstream)
    routing = load_routing()
    write_product_surface(work, without_hosted_fallbacks(routing) if confidential else routing, WRITE_SCOPE)
    for path in sorted(p for p in (work / ".gnomon").rglob("*") if p.is_file()):
        blob = _git(work, "hash-object", "-w", "--no-filters", "--", str(path))
        _git(work, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path.relative_to(work).as_posix()}")
    removed = [p.decode("utf-8", errors="replace") for p in upstream[:50]]
    if _git(work, "write-tree") == _git(work, "rev-parse", f"{baseline}^{{tree}}"):
        return {"revision": baseline, "compiled": False, "removed": removed}
    _git(work, *GIT_ID, "commit", "-q", "--no-verify", "-m", SURFACE_COMMIT)
    _git(work, "push", "-q", "origin", "HEAD:refs/heads/main")
    return {"revision": _git(work, "rev-parse", "HEAD"), "compiled": True, "removed": removed}


# -- inventory, by rule ------------------------------------------------------------------------------

def _read(root: Path, rel: str) -> str:
    """A file of the checkout as text, or "" for anything else: only a regular file inside the
    checkout is read (a symlink to a key, a holdout or /dev/zero is never followed), and only up to
    MAX_SCAN_BYTES; a larger file reads as ""."""
    path = root / rel
    try:
        if not stat.S_ISREG(path.lstat().st_mode) or not path.resolve().is_relative_to(root.resolve()):
            return ""
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(fd, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                return ""
            data = fh.read(MAX_SCAN_BYTES + 1)
    except (OSError, RuntimeError, ValueError):
        return ""
    return "" if len(data) > MAX_SCAN_BYTES else data.decode("utf-8", errors="replace")


def languages(files) -> list:
    counts: dict = {}
    for f in files:
        lang = LANGUAGES.get(os.path.splitext(f)[1].lower())
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    return [{"language": k, "files": v} for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


_PY_TEST = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$")
_NPM_DEFAULT = "no test specified"


def detect_tests(root: Path, files) -> list:
    """Each test command the repository declares, found by rule. Nothing is guessed: an ecosystem
    with no rule that matches is simply not listed."""
    files = list(files)
    names = set(files)
    found = []
    py_tests = [f for f in files if _PY_TEST.search(f)]
    pytest_basis = []
    if "pytest.ini" in names:
        pytest_basis.append("pytest.ini")
    if any(f == "conftest.py" or f.endswith("/conftest.py") for f in files):
        pytest_basis.append("conftest.py")
    for cfg, marker in (("pyproject.toml", "[tool.pytest"), ("setup.cfg", "[tool:pytest]"), ("tox.ini", "[pytest]")):
        if cfg in names and marker in _read(root, cfg):
            pytest_basis.append(f"{cfg} {marker}")
    if not pytest_basis and any(re.search(r"^\s*(import pytest|from pytest\b)", _read(root, f), re.MULTILINE)
                                for f in py_tests[:200]):
        pytest_basis.append("a test file imports pytest")
    if pytest_basis:
        found.append({"ecosystem": "python", "runner": "pytest", "tool": "python",
                      "command": ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                      "basis": "; ".join(pytest_basis)})
    elif py_tests:
        start = ["-s", "tests"] if any(f.startswith("tests/") for f in py_tests) else []
        found.append({"ecosystem": "python", "runner": "unittest", "tool": "python",
                      "command": ["python", "-m", "unittest", "discover", *start, "-v"],
                      "basis": f"{len(py_tests)} test file(s) named test_*.py or *_test.py, no pytest marker"})
    if "package.json" in names:
        try:
            script = ((json.loads(_read(root, "package.json")) or {}).get("scripts") or {}).get("test")
        except (ValueError, AttributeError, RecursionError):  # a crafted nesting is no package.json
            script = None
        if isinstance(script, str) and script.strip() and _NPM_DEFAULT not in script:
            found.append({"ecosystem": "node", "runner": "npm", "tool": "npm", "command": ["npm", "test"],
                          "basis": f"package.json scripts.test: {script[:80]}"})
    if "go.mod" in names and any(f.endswith("_test.go") for f in files):
        found.append({"ecosystem": "go", "runner": "go test", "tool": "go", "command": ["go", "test", "./..."],
                      "basis": "go.mod and *_test.go files"})
    if "Cargo.toml" in names:
        found.append({"ecosystem": "rust", "runner": "cargo test", "tool": "cargo",
                      "command": ["cargo", "test", "--offline"], "basis": "Cargo.toml"})
    if "pom.xml" in names:
        found.append({"ecosystem": "java", "runner": "maven", "tool": "mvn", "command": ["mvn", "-q", "-o", "test"],
                      "basis": "pom.xml"})
    elif "build.gradle" in names or "build.gradle.kts" in names:
        found.append({"ecosystem": "java", "runner": "gradle", "tool": "gradle",
                      "command": ["gradle", "test", "--offline"], "basis": "build.gradle"})
    return found


_UNDERLINE = re.compile(r"^[=\-~^*_`#+]{3,}$")


def first_paragraph(text: str, limit: int = 800) -> str:
    para: list[str] = []
    in_code = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("```") or s.startswith("~~~"):
            in_code = not in_code
            if para:
                break
            continue
        if in_code:
            continue
        if not s:
            if para:
                break
            continue
        if _UNDERLINE.match(s):
            if len(para) == 1:      # the line above was a reStructuredText or setext heading
                para = []
                continue
            if para:
                break
            continue
        if s.startswith(("#", "<", "[![", "![", ".. ", "|")) or s.startswith("---"):
            if para:
                break
            continue
        para.append(s)
    return " ".join(para)[:limit]


def readme(root: Path, files) -> dict:
    top = [f for f in files if "/" not in f and f.lower().startswith("readme")]
    order = sorted(top, key=lambda f: (0 if f.lower().endswith(".md") else 1, f))
    for f in order:
        para = first_paragraph(_read(root, f))
        if para:
            return {"file": f, "first_paragraph": para}
    return {"file": order[0] if order else None, "first_paragraph": None,
            "note": "no README" if not order else "the README has no paragraph of text"}


_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_ROUTE_FILES = (".py", ".js", ".mjs", ".cjs", ".ts", ".go", ".java", ".kt", ".rb", ".php")
_ROUTES = [
    # Rihma's own paved road: @route("GET", "/items")
    ("rihma", re.compile(r"""@route\(\s*['"](GET|POST|PUT|PATCH|DELETE)['"]\s*,\s*['"]([^'"]+)['"]""")),
    # Flask: @app.route("/items", methods=["GET", "POST"])
    ("flask", re.compile(r"""@\w+\.route\(\s*['"]([^'"]+)['"](?:[^)\n]*?methods\s*=\s*[\[(]([^\])]*)[\])])?""")),
    # FastAPI, Flask 2, Express, Koa and the like: app.get("/items" / @router.post("/items"
    ("verb", re.compile(r"""\b(?:app|router|api|server|bp|blueprint)\.(get|post|put|patch|delete)\(\s*['"`]([^'"`]+)['"`]""",
                        re.IGNORECASE)),
    # Go net/http and gorilla/mux
    ("go", re.compile(r"""\.(?:HandleFunc|Handle)\(\s*"([^"]+)\"""")),
    # Spring
    ("spring", re.compile(r"""@(Get|Post|Put|Patch|Delete|Request)Mapping\(\s*(?:value\s*=\s*|path\s*=\s*)?"([^"]+)\"""")),
    # Django urls.py
    ("django", re.compile(r"""\b(?:re_)?path\(\s*r?['"]([^'"]*)['"]""")),
]


def endpoints(root: Path, files) -> list:
    """The HTTP routes the source declares, found with simple patterns. A route a pattern misses
    is not invented."""
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []

    def add(method, path, where):
        path = path if path.startswith("/") else "/" + path
        key = (method, path)
        if key not in seen and len(out) < MAX_ENDPOINTS:
            seen.add(key)
            out.append({"method": method, "path": path, "declared_in": where})

    for f in files:
        if not f.endswith(_ROUTE_FILES) or f.startswith(VENDORED) or "/node_modules/" in f:
            continue
        text = _read(root, f)
        if not text:
            continue
        for kind, pat in _ROUTES:
            if kind == "django" and not f.endswith("urls.py"):
                continue
            for m in pat.finditer(text):
                if kind == "rihma":
                    add(m.group(1), m.group(2), f)
                elif kind == "flask":
                    methods = re.findall(r"[A-Za-z]+", m.group(2) or "") or ["GET"]
                    for meth in methods:
                        if meth.upper() in _METHODS:
                            add(meth.upper(), m.group(1), f)
                elif kind == "verb":
                    add(m.group(1).upper(), m.group(2), f)
                elif kind == "go":
                    add("ANY", m.group(1), f)
                elif kind == "spring":
                    verb = m.group(1).upper()
                    add("ANY" if verb == "REQUEST" else verb, m.group(2), f)
                elif kind == "django":
                    add("ANY", m.group(1), f)
    return out


def dockerfiles(files) -> list:
    out = []
    for f in files:
        base = f.rsplit("/", 1)[-1]
        if base in ("Dockerfile", "Containerfile") or base.startswith("Dockerfile.") or base.endswith(".Dockerfile"):
            out.append(f)
    return sorted(out)


def inventory(root: Path, files, *, base_url: str | None) -> dict:
    files = sorted(f for f in files if not f.startswith(VENDORED) and "/node_modules/" not in f)
    tests = detect_tests(root, files)
    docker = dockerfiles(files)
    found = endpoints(root, files)      # also a word on its kind of work: HTTP routes (kernel/adopt_kind.py)
    if base_url:
        routes = {"scanned": True, "found": found,
                  "note": None if found else "no route declaration found with the kernel's simple patterns"}
    else:
        routes = {"scanned": False, "found": [], "note": "not scanned: no base_url was given"}
    return {"by": "rule (kernel/adopt.py), no model", "files": len(files), "languages": languages(files),
            "tests": tests, "test_command": ({"detected": True, **tests[0]} if tests else
                                             {"detected": False, "reason": "no test command found by rule"}),
            "readme": readme(root, files), "endpoints": routes, "http_routes": len(found),
            "dockerfile": {"present": bool(docker), "files": docker}}


# -- the characterisation baseline -------------------------------------------------------------------

_COUNT = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|passing|failing|pending)\b")


def _counts_pytest(text: str) -> dict | None:
    tail = "\n".join(text.strip().splitlines()[-3:])
    found: dict[str, int] = {}
    for n, word in _COUNT.findall(tail):
        key = {"error": "errors", "passing": "passed", "failing": "failed", "pending": "skipped"}.get(word, word)
        found[key] = found.get(key, 0) + int(n)
    if not found:
        return None
    return {"passed": found.get("passed", 0) + found.get("xpassed", 0), "failed": found.get("failed", 0),
            "errors": found.get("errors", 0), "skipped": found.get("skipped", 0) + found.get("xfailed", 0)}


def _counts_unittest(text: str) -> dict | None:
    ran = re.search(r"^Ran (\d+) tests?", text, re.MULTILINE)
    if not ran:
        return None
    n = int(ran.group(1))
    summary = re.search(r"^(OK|FAILED)\b(?: \(([^)]*)\))?", text, re.MULTILINE)
    parts = dict((k.strip(), int(v)) for k, v in re.findall(r"([a-z ]+)=(\d+)", summary.group(2) or "")) \
        if summary else {}
    failed, errors, skipped = parts.get("failures", 0), parts.get("errors", 0), parts.get("skipped", 0)
    other = parts.get("expected failures", 0) + parts.get("unexpected successes", 0)
    return {"ran": n, "passed": max(0, n - failed - errors - skipped - other), "failed": failed,
            "errors": errors, "skipped": skipped}


def _counts_generic(text: str) -> dict | None:
    surefire = re.findall(r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)", text)
    if surefire:  # maven: the last line is the build's summary
        run, fail, err, skip = map(int, surefire[-1])
        return {"passed": run - fail - err - skip, "failed": fail, "errors": err, "skipped": skip}
    cargo = re.findall(r"test result: \w+\. (\d+) passed; (\d+) failed(?:; (\d+) ignored)?", text)
    if cargo:  # one line per test binary: the library, each integration test, the doc-tests
        return {"passed": sum(int(c[0]) for c in cargo), "failed": sum(int(c[1]) for c in cargo), "errors": 0,
                "skipped": sum(int(c[2] or 0) for c in cargo)}
    go_fail = len(re.findall(r"^--- FAIL:", text, re.MULTILINE))
    go_ok = len([line for line in re.findall(r"^ok\s+\S+.*$", text, re.MULTILINE) if "[no tests to run]" not in line])
    if go_fail or go_ok:
        return {"passed": None, "failed": go_fail, "errors": 0, "skipped": 0, "packages_ok": go_ok}
    return _counts_pytest(text)  # jest's and mocha's summaries read the same way


def _counts(runner: str, stdout: str, stderr: str) -> dict | None:
    out = stdout + "\n" + stderr
    if runner == "unittest":
        return _counts_unittest(stderr or out)
    if runner == "pytest":
        return _counts_pytest(stdout or out)
    return _counts_generic(out)


def _any_passed(counts: dict | None) -> bool:
    return counts is not None and ((counts.get("passed") or 0) > 0 or (counts.get("packages_ok") or 0) > 0)


_MISSING_MODULE = (re.compile(r"ModuleNotFoundError: No module named '([\w.]+)'"),
                   re.compile(r"Cannot find module '([^'./][^']*)'"))
_LOAD_FAILURES = ("unittest.loader._FailedTest", "ERROR collecting", "ImportError while importing test module",
                  "Cannot find module")


def _holds_module(root: Path, name: str) -> bool:
    """Whether the repository holds a module of that name itself: then an import of it that fails
    is the code's own failure, not a missing dependency."""
    return any((base / name).is_dir() or (base / f"{name}.py").is_file() for base in (root, root / "src"))


def _missing_dependencies(out: str, root: Path) -> list[str]:
    """The third-party modules a suite could not load: dependencies the kernel does not install."""
    if not any(marker in out for marker in _LOAD_FAILURES):
        return []
    names = sorted({m.group(1).split(".")[0] for pat in _MISSING_MODULE for m in pat.finditer(out)})
    return [n for n in names if n and not _holds_module(root, n)]


def _count_line(counts: dict) -> str:
    return ", ".join(f"{counts[k]} {k}" for k in ("passed", "failed", "errors", "skipped")
                     if counts.get(k) is not None)


def _baseline_verdict(runner: str, code: int, counts: dict | None, out: str, root: Path) -> tuple[str, str]:
    """The verdict of one characterisation run. Passed only when it exits 0 and at least one test
    passed: zero tests, every test skipped or a summary the kernel cannot read are not measured,
    and so is a suite that could not load a dependency the kernel does not install."""
    if runner == "pytest" and code == 5:
        return "not measured", "not measured: pytest collected no tests"
    if counts is not None and runner == "unittest" and counts.get("ran") == 0:
        return "not measured", "not measured: no tests ran"
    if code == 0:
        if _any_passed(counts):
            return "passed", "the existing suite passes"
        seen = "the kernel cannot read this summary" if counts is None else _count_line(counts)
        return "not measured", f"not measured: no test passed or the summary could not be read ({seen})"
    missing = _missing_dependencies(out, root)
    if missing:
        return "not measured", ("not measured: a dependency the kernel does not install is missing ("
                                + ", ".join(missing[:5]) + "); the existing tests did not run")
    if counts and ((counts.get("failed") or 0) + (counts.get("errors") or 0)) > 0:
        return "failed", ("some existing tests fail at the baseline: that is the existing behaviour, recorded, "
                          "not judged")
    return "not measured", (f"not measured: the command exited {code} with no test summary the kernel can read "
                            "(dependencies may be missing: the kernel runs offline and installs nothing)")


def _offline_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(PYTHONDONTWRITEBYTECODE="1", PIP_NO_INDEX="1", npm_config_offline="true", GOPROXY="off",
               GOFLAGS="-mod=readonly", CARGO_NET_OFFLINE="true", GIT_TERMINAL_PROMPT="0")
    return env


def _command(test: dict, which: Callable[[str], str | None]) -> list[str] | str:
    """The argv that runs a detected suite, or the reason it is not run."""
    cmd = list(test["command"])
    if test["ecosystem"] == "python":
        if test["runner"] == "pytest" and importlib.util.find_spec("pytest") is None:
            return f"not measured: pytest is not installed for {sys.executable}; the kernel installs nothing"
        return [sys.executable or "python", *cmd[1:]]
    tool = which(test["tool"])
    if tool is None:
        return f"not measured: toolchain not run by the kernel ({test['tool']} is not on PATH)"
    return [tool, *cmd[1:]]


def run_baseline(root: Path, test: dict, *, timeout: int,
                 which: Callable[[str], str | None] = shutil.which) -> dict:
    """Run one detected test command once and read its counts. A run the kernel cannot read, or one
    in which no test passed, is not measured, never passed. Stdin is closed, and the timeout, like
    the end of the run, stops every process the suite started."""
    base = {"ecosystem": test["ecosystem"], "runner": test["runner"], "command": list(test["command"]),
            "meaning": CHARACTERISATION}
    argv = _command(test, which)
    if isinstance(argv, str):
        return base | {"verdict": "not measured", "reason": argv}
    from kernel import access_isolation as isolation

    env = _offline_env()
    data_dir = tempfile.mkdtemp(prefix="adopt-data-")
    env["DATA_DIR"] = data_dir
    try:  # access enforced: through IT's isolation runner, or not run at all (D-0016, FR-ID4-AC-1)
        job = isolation.adopted_suite(argv, checkout=root, env=env, tool=test["tool"])
    except isolation.IsolationRequired as exc:
        shutil.rmtree(data_dir, ignore_errors=True)
        return base | {"verdict": "not measured", "reason": f"not measured: {exc}"}
    started = time.monotonic()
    try:
        with job:
            code, stdout, stderr = _run(job.argv, cwd=root, env=job.env, timeout=timeout)
    except subprocess.TimeoutExpired:  # stopped at its limit, with every process it started (FR-DF5)
        return base | {"verdict": "not measured", "limit_s": timeout,
                       "reason": f"not measured: timed out: the suite did not finish in {timeout}s"}
    except OSError as exc:
        return base | {"verdict": "not measured", "reason": f"not measured: the command could not start ({exc})"}
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
    out = stdout + "\n" + stderr
    counts = _counts(test["runner"], stdout, stderr)
    verdict, reason = _baseline_verdict(test["runner"], code, counts, out, root)
    return base | {"exit": code, "seconds": round(time.monotonic() - started, 2), "counts": counts,
                   "tail": out.strip().splitlines()[-6:], "verdict": verdict, "reason": reason}


def characterise(root: Path, tests: list, *, timeout: int,
                 which: Callable[[str], str | None] = shutil.which) -> dict:
    from kernel.verdicts import combine_verdicts

    if not tests:
        return {"verdict": "not measured", "reason": "not measured: no test command was detected by rule",
                "meaning": CHARACTERISATION, "runs": []}
    runs = [run_baseline(root, t, timeout=timeout, which=which) for t in tests]
    verdict = combine_verdicts([r["verdict"] for r in runs])
    reasons = [r["reason"] for r in runs if r["verdict"] != "passed"]
    return {"verdict": verdict, "meaning": CHARACTERISATION, "runs": runs,
            "reason": "; ".join(reasons) if reasons else "every detected suite passes at the baseline"}


# -- the as-is spec -------------------------------------------------------------------------------------

def _base_url(url: str | None) -> str | None:
    """The address of the running service, or None. Nothing that can carry a credential is kept:
    it goes to the ledger, the spec and the brief, where nothing can be taken back."""
    if not url:
        return None
    url = str(url).strip().rstrip("/")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise AdoptionRefused(f"base_url must be an http or https URL, got {url!r}")
    if parts.username or parts.password or "@" in parts.netloc:
        raise AdoptionRefused("base_url carries a user or a credential; Rihma never handles credentials")
    if parts.query or parts.fragment:
        raise AdoptionRefused("base_url carries a query or a fragment, where tokens travel; Rihma never handles "
                              "credentials: give the address without it")
    return url


def as_is_spec(title: str, *, inv: dict, baseline_rev: str, base_url: str | None, maturity: str,
               source_label: str) -> dict:
    """The spec of what the adopted solution does today, written by rule. Its requirements are
    observed: existing behaviour, not something anyone asked for."""
    tests = inv["tests"]
    crit: list[dict[str, Any]] = []
    for t in tests or [None]:
        when = f"its test suite runs ({' '.join(t['command'])})" if t else \
            "its test suite runs (no test command was detected by rule: not measured until one is named)"
        crit.append({"id": f"R-1-AC-{len(crit) + 1}", "given": f"the adopted code at baseline {baseline_rev[:12]}",
                     "when": when, "then": "the existing test suite keeps passing", "kind": "test"})
    reqs = [{"id": "R-1", "statement": "The existing behaviour is kept: the adopted code's own test suite keeps "
                                      "passing (characterisation: existing behaviour, not a spec).",
             "sources": [OBSERVED], "priority": "must", "provenance": OBSERVED, "acceptance": crit}]
    if base_url:
        reqs.append({"id": "R-2", "statement": "The running service keeps answering where it runs today.",
                     "sources": [OBSERVED], "priority": "must", "provenance": OBSERVED,
                     "acceptance": [{"id": "R-2-AC-1", "given": "the service as it runs today",
                                     "when": f"GET {base_url}", "then": f"GET {base_url} answers", "kind": "probe"}]})
    readme_text = inv["readme"].get("first_paragraph")
    langs = ", ".join(lang["language"] for lang in inv["languages"][:4]) or "not identified"
    return {"title": title, "summary": readme_text or f"An existing solution adopted from {source_label}.",
            "users": [], "maturity": maturity, "stack": f"adopted ({langs})", "look": "neutral",
            "interface": [{"method": e["method"], "path": e["path"], "purpose": f"declared in {e['declared_in']}"}
                          for e in inv["endpoints"]["found"] if e["method"] in _METHODS],
            "requirements": reqs,
            "out_of_scope": ["Anything the adopted code does that its tests and probes do not show: it is "
                             "observed, not specified, until a change makes it a requirement."],
            "adopted": {"source": source_label, "baseline": baseline_rev, "provenance": OBSERVED}}


def _profile_line(profile: dict[str, Any]) -> str:
    """The brief's line on the work profile: which and why, or that a person is asked (kernel/adopt_kind.py)."""
    from kernel.adopt_kind import line

    return line(profile)


_TOOK = {"commit": "its last commit (what is not committed is not included)",
         "working copy": "its working copy as it was, uncommitted changes included, as a snapshot (the folder is "
                         "never changed)",
         "snapshot": "a snapshot of the folder (the folder is never changed)",
         "documents": "a snapshot of its documents, to track and evaluate the work (nothing is built from them)"}


def _brief(title: str, *, intent: str, source_label: str, branch: str, baseline_rev: str, inv: dict,
           character: dict, base_url: str | None, person: str, persona: str, profile: dict[str, Any],
           took: str = "commit", left_out: dict[str, int] | None = None) -> str:
    tc = inv["test_command"]
    langs = ", ".join(f"{lang['language']} ({lang['files']})" for lang in inv["languages"][:6]) or "none identified"
    what = "A body of work (its documents)" if took == "documents" else "An existing solution"
    left = (f" {left_out['uncommitted']} uncommitted change(s) and {left_out['untracked']} untracked file(s) were "
            "left out." if left_out and (left_out.get("uncommitted") or left_out.get("untracked")) else "")
    lines = [f"# Brief: {title}", "",
             f"{what} adopted to **{intent}** it, by {person} ({persona}).", "",
             f"- Taken: {_TOOK.get(took, took)}.{left}",
             f"- Source: {source_label}, branch `{branch}`, baseline `{baseline_rev[:12]}`. The upstream is never "
             "pushed to.",
             f"- Languages: {langs}.",
             f"- Test command: {' '.join(tc['command']) + ' (' + tc['basis'] + ')' if tc['detected'] else tc['reason']}.",
             f"- Characterisation baseline: {character['verdict']} ({character['reason']}). This is existing "
             "behaviour, not a spec.",
             f"- Dockerfile: {', '.join(inv['dockerfile']['files']) if inv['dockerfile']['present'] else 'none'}.",
             f"- Running at: {base_url or 'not given'}.",
             _profile_line(profile)]
    para = inv["readme"].get("first_paragraph")
    if para:
        lines += ["", "## From its README", "", para]
    lines += ["", "## How it is held", "",
              "Every requirement here is observed: what the code does today, not what anyone asked for. A change "
              "makes a requirement of it through the change loop, and a person decides."]
    return "\n".join(lines) + "\n"


# -- adopt ------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class _Request:
    """What a person asked to adopt, checked."""
    title: str
    kind: str
    label: str
    intent: str
    base_url: str | None
    person: str
    persona: str
    maturity: str
    confidential: bool = False
    took: str = "commit"          # the last commit, a snapshot, the working copy as it is, or documents to track


def _label(kind: str, location: str) -> str:
    return location if kind == "url" else Path(location).as_posix()


def _check_request(person: str, persona: str, intent: str, profile: str | None, maturity: str, mode: str) -> None:
    from kernel.profiles import PROFILES
    from kernel.store import MATURITIES, MODES

    if not is_person(person):
        raise AdoptionRefused(f"{person!r} is not a person; adopting a solution is a person's act")
    if persona not in PERSONAS:
        raise AdoptionRefused(f"persona must be one of {', '.join(PERSONAS)}, got {persona!r}")
    if intent not in INTENTS:
        raise AdoptionRefused(f"intent must be one of {', '.join(INTENTS)}, got {intent!r}")
    if profile is not None and profile not in PROFILES:
        raise AdoptionRefused(f"profile must be one of {', '.join(PROFILES)}, got {profile!r}")
    if maturity not in MATURITIES or mode not in MODES:
        raise AdoptionRefused(f"maturity must be one of {MATURITIES} and mode one of {MODES}")


def _take(bare: Path, location: str, *, base_url: str | None, timeout: int,
          which: Callable[[str], str | None], suite_timeout: int = 0, exclude: tuple[str, ...] = (),
          confidential: bool = False, progress: Callable[[str], None] = lambda step: None) -> dict[str, Any]:
    """Everything adoption reads from the upstream, before the project exists: the mirror, a
    checkout of the baseline with its inventory, characterisation and documents (scanned as context,
    kernel/material.py), and the kernel's surface on main. The checkout goes through the
    credential-free path too, so an LFS filter never reaches the owner's credential helper or a prompt."""
    from kernel.agent_context_use import apply_stated
    from kernel.material_adopt import context
    from kernel.profiles_shapes import file_hints

    progress("fetching the code")
    branch, baseline = _mirror(bare, location, timeout=timeout)
    with tempfile.TemporaryDirectory(prefix="gf-adopt-", ignore_cleanup_errors=True) as tmp:
        scratch = Path(tmp)
        _net(scratch, "clone", "-q", "-c", "core.autocrlf=false", str(bare), "w", timeout=timeout)
        work = scratch / "w"
        files = [f for f in _git_read(work, "ls-files", "-z").split("\0") if f]
        progress("reading the code and the documents")
        inv = inventory(work, files, base_url=base_url) | {"revision": baseline}
        documents = context(work, exclude)
        archived = [r["path"] for r in documents[0]["files"] if r.get("archive")]
        inv["file_hints"] = file_hints(files + archived)      # its files' word on its kind of work (FR-RPJ1)
        apply_stated(inv, documents[0].get("agent_context"))   # the team's own test command first (FR-AGC1)
        progress("running its own tests once for a baseline")
        character = characterise(work, inv["tests"], timeout=suite_timeout or SUITE_TIMEOUT, which=which)
        surface = _own_surface(bare, scratch, baseline, timeout=timeout, confidential=confidential)
    return {"branch": branch, "baseline": baseline, "inventory": inv, "character": character, "surface": surface,
            "material": documents}


def _propose(project: Any, title: str, inv: dict[str, Any]) -> dict[str, Any]:
    """The work profile: a person's choice at creation stands; otherwise it is proposed by rule from
    the title and the README, and from its files: HTTP routes in the code count as an API. An uncertain
    proposal is kept as uncertain, with its candidates, and a person is asked (kernel/adopt_kind.py)."""
    from kernel.profiles import propose_profile
    from kernel.profiles_shapes import hint_text

    if project.meta.get("profile"):
        return {"profile": project.meta["profile"], "by": "person at creation"}
    routes = int(inv.get("http_routes") or 0)
    hints = inv.get("file_hints") or []
    proposal = propose_profile(f"{title}\n{inv['readme'].get('first_paragraph') or ''}" + ("\napi" if routes else "")
                               + ("\n" + hint_text(hints) if hints else ""))
    out = {"profile": proposal["profile"], "by": "rule",
           "from": "the README and the title" + (f", and {routes} HTTP route(s) in its code" if routes else "")
           + "".join(f", and {h['why']}" for h in hints[:3]),
           "keywords": proposal["basis"], "confidence": proposal["confidence"]}
    strong = {h["profile"] for h in hints if len(h["words"]) >= 3}     # a game engine's file, training runs
    if proposal["confidence"] != "clear" and proposal["profile"] in strong:
        out["confidence"] = "clear"                                        # its files settle what its words leave open
    elif proposal["confidence"] != "clear":
        out |= {"candidates": proposal["candidates"], "why": proposal["uncertain_because"]}
    return out


def _record_source(project: Any, taken: dict[str, Any], req: _Request, profile: dict[str, Any]) -> None:
    branch, baseline, surface = taken["branch"], taken["baseline"], taken["surface"]
    project.write("adopted.json", {
        "source": req.label, "source_kind": req.kind, "intent": req.intent, "default_branch": branch,
        "baseline": baseline, "main": surface["revision"], "base_url": req.base_url,
        "adopted_by": {"person": req.person, "persona": req.persona}, "at": project.factory.clock.stamp(),
        "upstream_push": "disabled: remote.upstream.pushurl is not a transport", "profile": profile,
        "last_upstream": baseline, "last_sync": None, "took": req.took, "origin": taken.get("origin"),
        **({"left_out": taken["left_out"]} if taken.get("left_out") else {}),
        **({"snapshot": taken["snapshot"]} if taken.get("snapshot") else {})})
    project.update_meta(intent=req.intent, upstream=req.label, baseline=baseline)
    project.log("adopted", {"source": req.label, "source_kind": req.kind, "intent": req.intent, "branch": branch,
                            "baseline": baseline, "base_url": req.base_url, "person": req.person,
                            "persona": req.persona, "upstream_push": "disabled"})
    project.log("surface_compiled", {"revision": surface["revision"], "over": baseline,
                                     "removed_upstream_surface": surface["removed"],
                                     "why": "the gate's verifier and the builder cells run under the kernel's own "
                                            "surface, never one the upstream wrote (under any name a file system "
                                            "opens it by), and git-lfs is never sent to an address the upstream "
                                            "chose (.lfsconfig)"})


def _record_baseline(project: Any, taken: dict[str, Any]) -> None:
    inv, baseline = taken["inventory"], taken["baseline"]
    project.write("inventory.json", inv)
    project.log("inventory_taken", {"revision": baseline, "files": inv["files"],
                                    "languages": [x["language"] for x in inv["languages"]],
                                    "test_command": " ".join(inv["test_command"]["command"])
                                    if inv["test_command"]["detected"] else None,
                                    "readme": inv["readme"]["file"], "dockerfile": inv["dockerfile"]["present"],
                                    "endpoints": len(inv["endpoints"]["found"]),
                                    "endpoints_scanned": inv["endpoints"]["scanned"]})
    character = dict(taken["character"], revision=baseline, at=project.factory.clock.stamp())
    project.write("baseline.json", character)
    project.log("characterised", {"revision": baseline, "verdict": character["verdict"],
                                  "meaning": CHARACTERISATION, "reason": character["reason"],
                                  "runs": [{k: r.get(k) for k in ("runner", "verdict", "counts", "exit")}
                                           for r in character["runs"]]})


def _as_is_tasks(project: Any, spec: dict[str, Any], contract: dict[str, Any], baseline: str) -> None:
    """The as-is tasks are the existing code: nothing to build until a change reopens one. Factory
    default checks a person accepted earlier stay pending: they are real work, not observed."""
    observed = {r["id"] for r in spec["requirements"]}
    state = project.read("tasks.json", {}) or {}
    as_is, pending = [], []
    for t in contract["tasks"]:
        if {c.rsplit("-AC-", 1)[0] for c in t["criteria"]} <= observed:
            state[t["id"]] = {"status": "merged", "revision": baseline, "rounds": [], "adopted": True,
                              "note": "the existing code at adoption; not built or gated by the factory"}
            as_is.append(t["id"])
        else:
            pending.append(t["id"])
    project.write("tasks.json", state)
    project.log("adoption_tasks", {"as_is": as_is, "pending": pending,
                                   "note": "as-is tasks hold the existing code; no merge or gate is claimed for them"})


def _write_as_is(project: Any, taken: dict[str, Any], req: _Request) -> dict[str, Any]:
    from kernel.compile import compile_project
    from kernel.spec import render_spec_md

    spec = as_is_spec(req.title, inv=taken["inventory"], baseline_rev=taken["baseline"], base_url=req.base_url,
                      maturity=req.maturity, source_label=req.label)
    project.write("spec.json", spec)
    write_text(project.path("spec.md"), render_spec_md(spec))
    project.log("as_is_spec_written", {"requirements": len(spec["requirements"]),
                                       "criteria": sum(len(r["acceptance"]) for r in spec["requirements"]),
                                       "provenance": OBSERVED, "contract_provenance": "vendor-proposed",
                                       "why": "the contract's vocabulary (tools/contract_check.py) has no observed "
                                              "tier: the compiler enters observed requirements as vendor-proposed "
                                              "and notes that they are observed"})
    _as_is_tasks(project, spec, compile_project(project), taken["baseline"])
    return spec


def _stage(project: Any, spec: dict[str, Any], req: _Request) -> None:
    if req.base_url:
        for r in spec["requirements"]:
            for c in r["acceptance"]:
                if c["kind"] == "probe":
                    write_json(project.holdouts_dir / f"{c['id']}.json",
                               {"criterion": c["id"], "kind": "probe", "steps": [{"method": "GET", "path": ""}],
                                "author_role": "kernel: adoption, by rule"})
    project.update_meta(stage=7 if req.intent == "monitor" else 5)
    if req.intent != "monitor":
        why = "nothing is built until a change arrives through the change loop or a person's workspace"
    elif req.base_url:
        why = f"monitor: probes against the running service at {req.base_url}"
    else:
        why = "monitor: upstream drift only; probes not measured, because no base_url was given"
    project.log("adoption_staged", {"intent": req.intent, "stage": project.meta["stage"], "why": why})


def _hold(project: Any, taken: dict[str, Any], req: _Request) -> None:
    """Record an adoption whose upstream was read: the source, the inventory and the baseline, the
    profile, the brief, the as-is spec and contract, the as-is tasks and the stage."""
    from kernel import adopt_kind
    from kernel.canon import Canon
    from kernel.material_adopt import hold
    from kernel.profiles import choose

    profile = _propose(project, req.title, taken["inventory"])
    _record_source(project, taken, req, profile)
    _record_baseline(project, taken)
    hold(project, taken, person=req.person, persona=req.persona, confidential=req.confidential)
    if adopt_kind.unclear(profile):     # not clear from its files and words: a person is asked which kind
        adopt_kind.ask(project, profile)
    elif profile["by"] == "rule":
        choose(project, profile["profile"], basis={k: v for k, v in profile.items() if k != "profile"})
    Canon(project).write_brief(_brief(req.title, intent=req.intent, source_label=req.label, branch=taken["branch"],
                                      baseline_rev=taken["baseline"], inv=taken["inventory"],
                                      character=taken["character"], base_url=req.base_url, person=req.person,
                                      persona=req.persona, profile=profile, took=req.took,
                                      left_out=taken.get("left_out")))
    spec = _write_as_is(project, taken, req)
    _stage(project, spec, req)


def _roll_back(project: Any) -> None:
    """Remove a project whose adoption failed after it was created, so nothing is left
    half-adopted. What cannot be removed is marked failed, and is never taken as adopted."""
    shutil.rmtree(project.holdouts_dir, ignore_errors=True)
    shutil.rmtree(project.dir, ignore_errors=True)
    if project.path("project.json").exists():
        with contextlib.suppress(OSError):
            project.update_meta(adoption="failed", stage=1)


def _taking(kind: str, location: str, *, working_copy: bool, documents: bool) -> tuple[str, dict[str, Any]]:
    """What is taken (the last commit, the working copy, a snapshot, documents), where it came from (its origin,
    credentials out) and what the last commit leaves out (FR-RPJ1)."""
    from kernel import material_git as mg

    took = "documents" if documents else "working copy" if working_copy and kind == "path" else \
        "snapshot" if kind == "folder" else "commit"
    seen: dict[str, Any] = {"origin": location if kind == "url" else mg.origin(Path(location)) if kind == "path"
                            else None}
    if took == "commit" and kind == "path":       # what the last commit leaves out, said in the brief
        seen["left_out"] = mg.working_changes(Path(location))
    return took, seen


def adopt(factory: Any, title: str, *, source: Any, intent: str, person: str, persona: str,
          base_url: str | None = None, profile: str | None = None, maturity: str = "production",
          mode: str = "mixed", timeout: int = 600, which: Callable[[str], str | None] = shutil.which,
          suite_timeout: int = SUITE_TIMEOUT, exclude: tuple[str, ...] = (), confidential: bool = False,
          posture: dict[str, Any] | None = None, progress: Callable[[str], None] = lambda step: None,
          working_copy: bool = False, documents: bool = False) -> Any:
    """Adopt an existing solution as a project. Returns the project.

    Everything that reads the upstream runs before the project exists, so an unreachable or
    unreadable source leaves nothing; a failure after the project exists removes it again.
    ``timeout`` bounds each git call; ``suite_timeout`` bounds each detected test suite's run.
    A folder that is not a git repository is snapshotted first (kernel/material_adopt.py); ``exclude``
    drops files from the snapshot and the scanned documents; ``confidential`` keeps it on local models;
    ``posture`` (kernel/posture.py) is recorded with who chose it, at the maturity and mode given. ``progress``
    hears each step as it starts, in plain words (the cockpit's adoption job prints them).
    A git repository's last commit is adopted, and what is not committed is counted and left out; with
    ``working_copy`` its working tree as it is now is snapshotted instead. ``documents`` adopts a folder of
    documents only, to track and evaluate the work (FR-RPJ1), where it is otherwise refused."""
    from kernel.material_adopt import NoCode, snapshot

    _check_request(person, persona, intent, profile, maturity, mode)
    kind, location = check_source(source)
    took, seen = _taking(kind, location, working_copy=working_copy, documents=documents)
    req = _Request(title=title, kind=kind, label=_label(kind, location), intent=intent, base_url=_base_url(base_url),
                   person=person, persona=persona, maturity=maturity, confidential=confidential, took=took)
    factory.home.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".adopting-", dir=factory.home))
    snap: dict[str, Any] | None = None
    try:
        if kind == "folder" or (took in ("working copy", "documents") and kind != "url"):
            progress("copying the folder into a baseline repository")
            try:      # the person's folder is never changed: its snapshot is the upstream
                location, snap = snapshot(factory.home, location, exclude, documents=documents)
            except NoCode as exc:
                raise AdoptionRefused(str(exc)) from None
        taken = _take(staging / "repo.git", location, base_url=req.base_url, timeout=timeout, which=which,
                      suite_timeout=suite_timeout, exclude=exclude, confidential=confidential,
                      progress=progress) | {"snapshot": snap, **seen}
        progress("recording the baseline, the as-is spec and the contract")
        project = factory.new_project(title, maturity=maturity, mode=mode, source_kind="adopted", profile=profile,
                                      posture=posture)
        try:
            os.replace(staging / "repo.git", project.path("repo.git"))
            _hold(project, taken, req)
        except BaseException:
            _roll_back(project)
            raise
    except BaseException:
        if snap:
            shutil.rmtree(snap["repository"], ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    if intent == "monitor" and req.base_url:
        probe(project)
    from kernel.areas import record as record_areas

    record_areas(project)        # its inventory and activity by area (FR-RPJ1); never fails the adoption
    return project


# -- monitoring -------------------------------------------------------------------------------------

def _server_error(result: dict[str, Any]) -> dict[str, Any]:
    """A probe the service answered with a server error (5xx) failed: an answer is not health."""
    if result.get("verdict") != "passed":
        return result
    errors = [s for s in result.get("trail") or [] if isinstance(s.get("status"), int) and s["status"] >= 500]
    if not errors:
        return result
    return result | {"verdict": "failed", "failed_step": errors[0]["step"], "observed": {"status": errors[0]["status"]},
                     "reason": f"status {errors[0]['status']}: a server error is not a healthy answer"}


def probe(project: Any, *, timeout: float = 10.0) -> dict[str, Any]:
    """One probe round against the adopted service: every probe scenario of the project at its
    base_url. A failing probe, a server error included, opens (or adds to) an incident card."""
    from kernel.operate import _append, load_scenarios, open_incident, run_scenario

    adopted = project.read("adopted.json") or {}
    at = project.factory.clock.stamp()
    base_url = adopted.get("base_url")
    if not base_url:
        return {"verdict": "not applicable", "reason": "no base_url was given at adoption", "at": at}
    scenarios = load_scenarios(project, ("probe",))
    results = [_server_error(run_scenario(base_url, s, timeout=timeout)) for s in scenarios]
    failed = [r for r in results if r["verdict"] != "passed"]
    verdict = "not measured" if not results else ("failed" if failed else "passed")
    result = {"environment": "production", "slot": "adopted", "base_url": base_url, "at": at, "scenarios": results,
              "checks": len(results), "failed": len(failed), "ok": verdict == "passed", "verdict": verdict}
    _append(project.path("ops", "probes.jsonl"), result)
    project.log("probed", {"base_url": base_url, "verdict": verdict, "checks": len(results), "failed": len(failed)})
    if failed:
        why = "; ".join(f"{r['criterion']}: {r.get('reason')}" for r in failed)
        inc = open_incident(project, release="adopted", env="production",
                            title=f"Probe failing for the adopted service at {base_url}",
                            body=f"{len(failed)} of {len(results)} probe checks failed: {why}",
                            payload={"probe": {"failed": len(failed), "checks": len(results), "base_url": base_url}})
        result["incident"] = inc["card"]
    return result


# -- sync -------------------------------------------------------------------------------------------

def _upstream_head(bare: Path, branch: str) -> str | None:
    return _git(bare, "rev-parse", "--verify", "-q", f"refs/remotes/upstream/{branch}^{{commit}}", check=False) or None


def _drift(bare: Path, adopted: dict[str, Any], head: str, *, at: str) -> dict[str, Any]:
    """The drift of the upstream's head from the baseline. Commit messages and file names are the
    upstream's own bytes: what is not UTF-8 is replaced."""
    branch, baseline = adopted["default_branch"], adopted["baseline"]
    new = int(_git_read(bare, "rev-list", "--count", f"{baseline}..{head}"))
    rewritten = int(_git_read(bare, "rev-list", "--count", f"{head}..{baseline}"))
    files = [f for f in _git_read(bare, "diff", "--name-only", baseline, head).splitlines() if f]
    commits = [line for line in _git_read(bare, "log", "--format=%h %s", "-n", "20", f"{baseline}..{head}").splitlines()
               if line]
    return {"verdict": "passed", "branch": branch, "baseline": baseline, "upstream": head, "new_commits": new,
            "rewritten": rewritten, "files_changed": len(files), "files": files[:200], "commits": commits,
            "moved_since_last_sync": head != (adopted.get("last_upstream") or baseline), "at": at, "card": None}


def _drift_card(project: Any, adopted: dict[str, Any], drift: dict[str, Any]) -> str:
    from kernel.change import submit

    new, rewritten, files = drift["new_commits"], drift["rewritten"], drift["files"]
    history = (f", and {rewritten} baseline commit(s) are no longer upstream (history was rewritten)"
               if rewritten else "")
    lines = ["Upstream changed: review", "",
             f"The upstream {adopted['source']} moved on {drift['branch']}: {new} commit(s) since the baseline "
             f"{drift['baseline'][:12]}{history}; {drift['files_changed']} file(s) differ.",
             "Nothing was merged: main stays at what the factory holds until a person decides.", ""]
    lines += [f"- {c}" for c in drift["commits"][:20]]
    if files:
        lines += ["", "Files: " + ", ".join(files[:30]) + (" ..." if len(files) > 30 else "")]
    card = submit(project, persona="developer", person="upstream sync", text="\n".join(lines))
    project.log("upstream_change_opened", {"card": card["id"], "upstream": drift["upstream"], "new_commits": new})
    return str(card["id"])


def _branch_gone(project: Any, adopted: dict[str, Any], *, at: str) -> dict[str, Any]:
    """The tracked branch is gone upstream after a fetch that worked: most often the default branch
    was renamed. A change card says so once per new default branch; the factory keeps tracking the
    old name until a person decides."""
    from kernel.change import submit

    bare, branch, baseline = project.path("repo.git"), adopted["default_branch"], adopted["baseline"]
    try:
        now = _default_branch(bare, "upstream")
    except AdoptionRefused:
        now = None
    head = _upstream_head(bare, now) if now and now != branch else None
    gone = {"verdict": "not measured", "branch": branch, "default_branch_now": now if head else None, "at": at,
            "card": None, "reason": f"not measured: the tracked branch {branch} is no longer upstream"
                                    + (f"; the upstream's default branch is now {now}" if head else "")}
    told = (adopted.get("branch_gone") or {}).get("default_branch_now")
    if head and told != now:
        ahead = int(_git_read(bare, "rev-list", "--count", f"{baseline}..{head}"))
        text = "\n".join(["Upstream changed: review", "",
                          f"The upstream {adopted['source']} no longer has the branch {branch} that the factory "
                          f"tracks: its default branch is now {now}, {ahead} commit(s) ahead of the baseline "
                          f"{baseline[:12]}.",
                          f"The factory keeps tracking {branch} until a person decides; nothing was merged and main "
                          "is not moved."])
        gone["card"] = submit(project, persona="developer", person="upstream sync", text=text)["id"]
        adopted["branch_gone"] = {k: gone[k] for k in ("branch", "default_branch_now", "card", "at")}
    project.log("upstream_branch_gone", {k: gone[k] for k in ("branch", "default_branch_now", "card")})
    adopted["last_sync"] = {"at": at, "verdict": "not measured", "reason": gone["reason"], "card": gone["card"]}
    project.write("adopted.json", adopted)
    return gone


def sync(project: Any, *, timeout: int = 300) -> dict[str, Any]:
    """Fetch the upstream again and record the drift since the baseline. When the upstream moved
    since the last look, open a change card for people to review. `main` is not moved."""
    adopted = project.read("adopted.json")
    if not adopted:
        raise ValueError(f"{project.pid} was not adopted: there is no upstream to sync")
    bare, at = project.path("repo.git"), project.factory.clock.stamp()
    try:
        _net(bare, "fetch", "-q", "--prune", "upstream", timeout=timeout)
    except RuntimeError as exc:
        project.log("upstream_sync_failed", {"error": str(exc)[:300]})
        return {"verdict": "not measured", "reason": f"not measured: the upstream could not be fetched ({exc})",
                "at": at}
    head = _upstream_head(bare, adopted["default_branch"])
    if head is None:
        return _branch_gone(project, adopted, at=at)
    drift = _drift(bare, adopted, head, at=at)
    project.log("upstream_synced", {k: drift[k] for k in ("branch", "baseline", "upstream", "new_commits",
                                                            "rewritten", "files_changed", "moved_since_last_sync")}
                | {"files": drift["files"][:50]})
    if drift["moved_since_last_sync"] and (drift["new_commits"] or drift["rewritten"]):
        drift["card"] = _drift_card(project, adopted, drift)
    adopted.update(last_upstream=head, last_sync={k: drift[k] for k in ("upstream", "new_commits", "rewritten",
                                                                       "files_changed", "at", "card")})
    project.write("adopted.json", adopted)
    return drift


def is_adopted(project: Any) -> bool:
    meta = project.meta
    return (meta.get("source_kind") == "adopted" and meta.get("adoption") != "failed"
            and project.path("adopted.json").exists())


__all__ = ["INTENTS", "AdoptionRefused", "adopt", "sync", "probe", "inventory", "detect_tests", "check_source",
           "first_paragraph", "as_is_spec", "is_adopted"]
