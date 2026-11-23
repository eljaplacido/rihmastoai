"""Brownfield adoption: an existing solution enters the factory to be monitored, maintained or improved.

`adopt` takes a git repository (a local path, or a URL that `git clone` reads without
credentials) and makes it a project:

- **Mirror.** The code is fetched into the project's `repo.git`, and `main` is set to the
  upstream's default branch at adoption: the **baseline**. The upstream is a fetch-only remote:
  its push URL is disabled, and nothing in the kernel pushes there. Credentials are never
  handled: credential helpers and prompts are switched off, and a URL that carries a user, a
  password, a token or a query is refused. A private repository is cloned by its owner first
  and adopted from that local path.
- **Inventory, by rule, no model.** Languages by file extension, the test command found by rule
  (detected or not, never guessed), the README's first paragraph, the HTTP routes the source
  declares (only when a `base_url` is given), and whether there is a Dockerfile.
- **Characterisation baseline.** A detected Python suite runs once in a temporary checkout,
  with a timeout. Its counts are evidence of *existing behaviour, not a spec*. Other toolchains
  run only when their tool is on PATH, offline; otherwise the baseline says "not measured:
  toolchain not run by the kernel". Running the suite runs the adopted code on this machine.
- **As-is spec.** One requirement of `observed` provenance whose criteria are "the existing test
  suite keeps passing", and, with a `base_url`, one whose probe is "GET <base_url> answers". It
  compiles to a contract and a check plan like any spec (the contract's vocabulary has no
  observed tier, so the compiler names it there; see `kernel/compile.py`).
- **Stage.** `monitor` goes to stage 7, probing `base_url`. `maintain` and `improve` wait at
  stage 5: the as-is tasks are the existing code, so nothing is built until a change arrives
  through the change loop or a person's workspace.

`sync` fetches the upstream again and records the drift since the baseline. When the upstream
moved since the last look, a change card "Upstream changed: review" is opened for people to
decide; `main` is never moved by a sync.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any

from kernel.lanes import _git
from kernel.people import PERSONAS, is_person
from kernel.store import write_json, write_text

INTENTS = ("monitor", "maintain", "improve")
CHARACTERISATION = "existing behaviour, not a spec"
OBSERVED = "observed"
# The upstream's push URL. Git cannot push to a transport that does not exist, so even a person
# running `git push upstream` inside repo.git by hand is refused.
NO_PUSH = "rihma-never-pushes-upstream://read-only"
NO_CREDENTIALS = ["-c", "credential.helper=", "-c", "core.askPass=", "-c", "protocol.ext.allow=never"]
URL_SCHEMES = ("https", "http", "git", "file")
VENDORED = ("node_modules/", "vendor/", ".venv/", "venv/", "site-packages/", "dist/", "build/", ".git/")
MAX_SCAN_BYTES = 512 * 1024
MAX_ENDPOINTS = 200

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


class AdoptionRefused(ValueError):
    """The source cannot be adopted as given (credentials, an unknown transport, not a repository)."""


# -- git, without credentials ------------------------------------------------------------------------

def _git_env() -> dict:
    env = dict(os.environ)
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", GIT_ASKPASS="", SSH_ASKPASS="")
    return env


def _net(cwd: Path, *args, timeout: int = 300) -> str:
    """A git call that may reach the upstream: no credential helper, no prompt, a timeout."""
    try:
        proc = subprocess.run(["git", *NO_CREDENTIALS, *args], cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, env=_git_env())
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git {args[0]} did not finish in {timeout}s") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip()[-300:]}")
    return proc.stdout.strip()


def check_source(source) -> tuple[str, str]:
    """('path', absolute path) or ('url', url). Refuses anything that would need a credential."""
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
    if proc.returncode != 0:
        raise AdoptionRefused(f"{path} is not a git repository")
    return "path", str(path)


def _default_branch(bare: Path, location: str) -> str:
    try:
        out = _net(bare, "ls-remote", "--symref", location, "HEAD", timeout=120)
        m = re.search(r"^ref:\s+refs/heads/(\S+)\s+HEAD", out, re.MULTILINE)
        if m:
            return m.group(1)
    except RuntimeError:
        pass
    branches = _git(bare, "for-each-ref", "--format=%(refname:strip=3)", "refs/remotes/upstream").split()
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


# -- inventory, by rule ------------------------------------------------------------------------------

def _read(root: Path, rel: str) -> str:
    path = root / rel
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


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
        except (ValueError, AttributeError):
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
    if base_url:
        found = endpoints(root, files)
        routes = {"scanned": True, "found": found,
                  "note": None if found else "no route declaration found with the kernel's simple patterns"}
    else:
        routes = {"scanned": False, "found": [], "note": "not scanned: no base_url was given"}
    return {"by": "rule (kernel/adopt.py), no model", "files": len(files), "languages": languages(files),
            "tests": tests, "test_command": ({"detected": True, **tests[0]} if tests else
                                             {"detected": False, "reason": "no test command found by rule"}),
            "readme": readme(root, files), "endpoints": routes,
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
    m = re.search(r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)", text)
    if m:  # maven surefire
        run, fail, err, skip = map(int, m.groups())
        return {"passed": run - fail - err - skip, "failed": fail, "errors": err, "skipped": skip}
    m = re.search(r"test result: \w+\. (\d+) passed; (\d+) failed", text)
    if m:  # cargo
        return {"passed": int(m.group(1)), "failed": int(m.group(2)), "errors": 0, "skipped": 0}
    go_fail = len(re.findall(r"^--- FAIL:", text, re.MULTILINE))
    go_ok = len(re.findall(r"^ok\s+\S+", text, re.MULTILINE))
    if go_fail or go_ok:
        return {"passed": None, "failed": go_fail, "errors": 0, "skipped": 0, "packages_ok": go_ok}
    return _counts_pytest(text)  # jest's and mocha's summaries read the same way


def _offline_env() -> dict:
    env = dict(os.environ)
    env.update(PYTHONDONTWRITEBYTECODE="1", PIP_NO_INDEX="1", npm_config_offline="true", GOPROXY="off",
               GOFLAGS="-mod=readonly", CARGO_NET_OFFLINE="true", GIT_TERMINAL_PROMPT="0")
    return env


def run_baseline(root: Path, test: dict, *, timeout: int, which=shutil.which) -> dict:
    """Run one detected test command once and read its counts. A run the kernel cannot read is
    not measured, never passed."""
    cmd = list(test["command"])
    base = {"ecosystem": test["ecosystem"], "runner": test["runner"], "command": cmd, "meaning": CHARACTERISATION}
    if test["ecosystem"] == "python":
        if test["runner"] == "pytest" and importlib.util.find_spec("pytest") is None:
            return base | {"verdict": "not measured", "reason": "not measured: pytest is not installed for "
                                                                f"{sys.executable}; the kernel installs nothing"}
        argv = [sys.executable or "python", *cmd[1:]]
    else:
        tool = which(test["tool"])
        if tool is None:
            return base | {"verdict": "not measured",
                           "reason": f"not measured: toolchain not run by the kernel ({test['tool']} is not on PATH)"}
        argv = [tool, *cmd[1:]]
    env = _offline_env()
    data_dir = tempfile.mkdtemp(prefix="adopt-data-")
    env["DATA_DIR"] = data_dir
    started = time.monotonic()
    try:
        proc = subprocess.run(argv, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return base | {"verdict": "not measured", "reason": f"not measured: the suite did not finish in {timeout}s"}
    except OSError as exc:
        return base | {"verdict": "not measured", "reason": f"not measured: the command could not start ({exc})"}
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
    seconds = round(time.monotonic() - started, 2)
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if test["runner"] == "unittest":
        counts = _counts_unittest(proc.stderr or out)
    elif test["runner"] == "pytest":
        counts = _counts_pytest(proc.stdout or out)
    else:
        counts = _counts_generic(out)
    record = base | {"exit": proc.returncode, "seconds": seconds, "counts": counts,
                     "tail": out.strip().splitlines()[-6:]}
    if test["runner"] == "pytest" and proc.returncode == 5:
        return record | {"verdict": "not measured", "reason": "not measured: pytest collected no tests"}
    if counts is not None and test["runner"] == "unittest" and counts.get("ran") == 0:
        return record | {"verdict": "not measured", "reason": "not measured: no tests ran"}
    if proc.returncode == 0:
        return record | {"verdict": "passed", "reason": "the existing suite passes"
                         + ("" if counts else "; its counts are not measured (the kernel cannot read this summary)")}
    if counts and ((counts.get("failed") or 0) + (counts.get("errors") or 0)) > 0:
        return record | {"verdict": "failed", "reason": "some existing tests fail at the baseline: that is the existing "
                                                        "behaviour, recorded, not judged"}
    return record | {"verdict": "not measured",
                     "reason": f"not measured: the command exited {proc.returncode} with no test summary the kernel "
                               "can read (dependencies may be missing: the kernel runs offline and installs nothing)"}


def characterise(root: Path, tests: list, *, timeout: int, which=shutil.which) -> dict:
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
    if not url:
        return None
    url = str(url).strip().rstrip("/")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise AdoptionRefused(f"base_url must be an http or https URL, got {url!r}")
    if parts.username or parts.password:
        raise AdoptionRefused("base_url carries a credential; Rihma never handles credentials")
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


def _brief(title: str, *, intent: str, source_label: str, branch: str, baseline_rev: str, inv: dict,
           character: dict, base_url: str | None, person: str, persona: str) -> str:
    tc = inv["test_command"]
    langs = ", ".join(f"{lang['language']} ({lang['files']})" for lang in inv["languages"][:6]) or "none identified"
    lines = [f"# Brief: {title}", "",
             f"An existing solution adopted to **{intent}** it, by {person} ({persona}).", "",
             f"- Source: {source_label}, branch `{branch}`, baseline `{baseline_rev[:12]}`. The upstream is never "
             "pushed to.",
             f"- Languages: {langs}.",
             f"- Test command: {' '.join(tc['command']) + ' (' + tc['basis'] + ')' if tc['detected'] else tc['reason']}.",
             f"- Characterisation baseline: {character['verdict']} ({character['reason']}). This is existing "
             "behaviour, not a spec.",
             f"- Dockerfile: {', '.join(inv['dockerfile']['files']) if inv['dockerfile']['present'] else 'none'}.",
             f"- Running at: {base_url or 'not given'}."]
    para = inv["readme"].get("first_paragraph")
    if para:
        lines += ["", "## From its README", "", para]
    lines += ["", "## How it is held", "",
              "Every requirement here is observed: what the code does today, not what anyone asked for. A change "
              "makes a requirement of it through the change loop, and a person decides."]
    return "\n".join(lines) + "\n"


# -- adopt ------------------------------------------------------------------------------------------

def _label(kind: str, location: str) -> str:
    return location if kind == "url" else Path(location).as_posix()


def adopt(factory, title: str, *, source, intent: str, person: str, persona: str, base_url: str | None = None,
          profile: str | None = None, maturity: str = "production", mode: str = "mixed", timeout: int = 600,
          which=shutil.which):
    """Adopt an existing solution as a project. Returns the project."""
    from kernel.canon import Canon
    from kernel.compile import compile_project
    from kernel.profiles import choose, propose_profile

    if not is_person(person):
        raise AdoptionRefused(f"{person!r} is not a person; adopting a solution is a person's act")
    if persona not in PERSONAS:
        raise AdoptionRefused(f"persona must be one of {', '.join(PERSONAS)}, got {persona!r}")
    if intent not in INTENTS:
        raise AdoptionRefused(f"intent must be one of {', '.join(INTENTS)}, got {intent!r}")
    from kernel.profiles import PROFILES
    from kernel.store import MATURITIES, MODES

    if profile is not None and profile not in PROFILES:
        raise AdoptionRefused(f"profile must be one of {', '.join(PROFILES)}, got {profile!r}")
    if maturity not in MATURITIES or mode not in MODES:
        raise AdoptionRefused(f"maturity must be one of {MATURITIES} and mode one of {MODES}")
    kind, location = check_source(source)
    base_url = _base_url(base_url)
    label = _label(kind, location)

    # Fetch before the project exists: an unreachable source leaves nothing half-adopted.
    factory.home.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".adopting-", dir=factory.home))
    try:
        branch, baseline_rev = _mirror(staging / "repo.git", location, timeout=timeout)
        project = factory.new_project(title, maturity=maturity, mode=mode, source_kind="adopted", profile=profile)
        os.replace(staging / "repo.git", project.path("repo.git"))
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    at = factory.clock.stamp()
    adopted = {"source": label, "source_kind": kind, "intent": intent, "default_branch": branch,
               "baseline": baseline_rev, "base_url": base_url, "adopted_by": {"person": person, "persona": persona},
               "at": at, "upstream_push": "disabled: remote.upstream.pushurl is not a transport",
               "last_upstream": baseline_rev, "last_sync": None}
    project.write("adopted.json", adopted)
    project.update_meta(intent=intent, upstream=label, baseline=baseline_rev)
    project.log("adopted", {"source": label, "source_kind": kind, "intent": intent, "branch": branch,
                            "baseline": baseline_rev, "base_url": base_url, "person": person, "persona": persona,
                            "upstream_push": "disabled"})

    with tempfile.TemporaryDirectory(prefix="gf-adopt-") as tmp:
        work = Path(tmp) / "w"
        _git(Path(tmp), "-c", "core.autocrlf=false", "clone", "-q", str(project.path("repo.git")), "w")
        files = [f for f in _git(work, "ls-files", "-z").split("\0") if f]
        inv = inventory(work, files, base_url=base_url)
        inv["revision"] = baseline_rev
        project.write("inventory.json", inv)
        project.log("inventory_taken", {"revision": baseline_rev, "files": inv["files"],
                                        "languages": [x["language"] for x in inv["languages"]],
                                        "test_command": " ".join(inv["test_command"]["command"])
                                        if inv["test_command"]["detected"] else None,
                                        "readme": inv["readme"]["file"], "dockerfile": inv["dockerfile"]["present"],
                                        "endpoints": len(inv["endpoints"]["found"]),
                                        "endpoints_scanned": inv["endpoints"]["scanned"]})
        character = characterise(work, inv["tests"], timeout=timeout, which=which)
    character.update(revision=baseline_rev, at=factory.clock.stamp())
    project.write("baseline.json", character)
    project.log("characterised", {"revision": baseline_rev, "verdict": character["verdict"],
                                  "meaning": CHARACTERISATION, "reason": character["reason"],
                                  "runs": [{k: r.get(k) for k in ("runner", "verdict", "counts", "exit")}
                                           for r in character["runs"]]})

    if profile is None:
        proposal = propose_profile(f"{title}\n{inv['readme'].get('first_paragraph') or ''}")
        choose(project, proposal["profile"], basis={"by": "rule", "from": "the README and the title",
                                                    "keywords": proposal["basis"]})

    Canon(project).write_brief(_brief(title, intent=intent, source_label=label, branch=branch,
                                      baseline_rev=baseline_rev, inv=inv, character=character, base_url=base_url,
                                      person=person, persona=persona))
    spec = as_is_spec(title, inv=inv, baseline_rev=baseline_rev, base_url=base_url, maturity=maturity,
                      source_label=label)
    from kernel.spec import render_spec_md

    project.write("spec.json", spec)
    write_text(project.path("spec.md"), render_spec_md(spec))
    project.log("as_is_spec_written", {"requirements": len(spec["requirements"]),
                                       "criteria": sum(len(r["acceptance"]) for r in spec["requirements"]),
                                       "provenance": OBSERVED, "contract_provenance": "vendor-proposed",
                                       "why": "the contract's vocabulary (tools/contract_check.py) has no observed "
                                              "tier: the compiler enters observed requirements as vendor-proposed "
                                              "and notes that they are observed"})
    contract = compile_project(project)

    # The as-is tasks are the existing code: nothing to build until a change reopens one. Factory
    # default checks a person accepted earlier stay pending: they are real work, not observed.
    observed = {r["id"] for r in spec["requirements"]}
    state = project.read("tasks.json", {}) or {}
    as_is, pending = [], []
    for t in contract["tasks"]:
        if {c.rsplit("-AC-", 1)[0] for c in t["criteria"]} <= observed:
            state[t["id"]] = {"status": "merged", "revision": baseline_rev, "rounds": [], "adopted": True,
                              "note": "the existing code at adoption; not built or gated by the factory"}
            as_is.append(t["id"])
        else:
            pending.append(t["id"])
    project.write("tasks.json", state)
    project.log("adoption_tasks", {"as_is": as_is, "pending": pending,
                                   "note": "as-is tasks hold the existing code; no merge or gate is claimed for them"})

    if base_url:
        for r in spec["requirements"]:
            for c in r["acceptance"]:
                if c["kind"] == "probe":
                    write_json(project.holdouts_dir / f"{c['id']}.json",
                               {"criterion": c["id"], "kind": "probe", "steps": [{"method": "GET", "path": ""}],
                                "author_role": "kernel: adoption, by rule"})
    project.update_meta(stage=7 if intent == "monitor" else 5)
    if intent != "monitor":
        why = "nothing is built until a change arrives through the change loop or a person's workspace"
    elif base_url:
        why = f"monitor: probes against the running service at {base_url}"
    else:
        why = "monitor: upstream drift only; probes not measured, because no base_url was given"
    project.log("adoption_staged", {"intent": intent, "stage": project.meta["stage"], "why": why})
    if intent == "monitor" and base_url:
        probe(project)
    return project


# -- monitoring -------------------------------------------------------------------------------------

def probe(project, *, timeout: float = 10.0) -> dict:
    """One probe round against the adopted service: every probe scenario of the project at its
    base_url. A failing probe opens (or adds to) an incident card."""
    from kernel.operate import _append, load_scenarios, open_incident, run_scenario

    adopted = project.read("adopted.json") or {}
    at = project.factory.clock.stamp()
    base_url = adopted.get("base_url")
    if not base_url:
        return {"verdict": "not applicable", "reason": "no base_url was given at adoption", "at": at}
    scenarios = load_scenarios(project, ("probe",))
    results = [run_scenario(base_url, s, timeout=timeout) for s in scenarios]
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

def sync(project, *, timeout: int = 300) -> dict:
    """Fetch the upstream again and record the drift since the baseline. When the upstream moved
    since the last look, open a change card for people to review. `main` is not moved."""
    from kernel.change import submit

    adopted = project.read("adopted.json")
    if not adopted:
        raise ValueError(f"{project.pid} was not adopted: there is no upstream to sync")
    bare, branch, baseline = project.path("repo.git"), adopted["default_branch"], adopted["baseline"]
    before = adopted.get("last_upstream") or baseline
    at = project.factory.clock.stamp()
    try:
        _net(bare, "fetch", "-q", "--prune", "upstream", timeout=timeout)
        head = _git(bare, "rev-parse", f"refs/remotes/upstream/{branch}")
    except RuntimeError as exc:
        out = {"verdict": "not measured", "reason": f"not measured: the upstream could not be fetched ({exc})",
               "at": at}
        project.log("upstream_sync_failed", {"error": str(exc)[:300]})
        return out
    new = int(_git(bare, "rev-list", "--count", f"{baseline}..{head}"))
    rewritten = int(_git(bare, "rev-list", "--count", f"{head}..{baseline}"))
    files = [f for f in _git(bare, "diff", "--name-only", baseline, head).splitlines() if f]
    commits = [line for line in _git(bare, "log", "--format=%h %s", "-n", "20", f"{baseline}..{head}").splitlines()
               if line]
    moved = head != before
    drift = {"verdict": "passed", "branch": branch, "baseline": baseline, "upstream": head, "new_commits": new,
             "rewritten": rewritten, "files_changed": len(files), "files": files[:200], "commits": commits,
             "moved_since_last_sync": moved, "at": at, "card": None}
    project.log("upstream_synced", {k: drift[k] for k in ("branch", "baseline", "upstream", "new_commits",
                                                            "rewritten", "files_changed", "moved_since_last_sync")}
                | {"files": files[:50]})
    if moved and (new or rewritten):
        lines = ["Upstream changed: review", "",
                 f"The upstream {adopted['source']} moved on {branch}: {new} commit(s) since the baseline "
                 f"{baseline[:12]}" + (f", and {rewritten} baseline commit(s) are no longer upstream (history was "
                                       "rewritten)" if rewritten else "") + f"; {len(files)} file(s) differ.",
                 "Nothing was merged: main stays at what the factory holds until a person decides.", ""]
        lines += [f"- {c}" for c in commits[:20]]
        if files:
            lines += ["", "Files: " + ", ".join(files[:30]) + (" ..." if len(files) > 30 else "")]
        card = submit(project, persona="developer", person="upstream sync", text="\n".join(lines))
        drift["card"] = card["id"]
        project.log("upstream_change_opened", {"card": card["id"], "upstream": head, "new_commits": new})
    adopted.update(last_upstream=head, last_sync={k: drift[k] for k in ("upstream", "new_commits", "rewritten",
                                                                       "files_changed", "at", "card")})
    project.write("adopted.json", adopted)
    return drift


def is_adopted(project) -> bool:
    return project.meta.get("source_kind") == "adopted" and project.path("adopted.json").exists()


__all__ = ["INTENTS", "AdoptionRefused", "adopt", "sync", "probe", "inventory", "detect_tests", "check_source",
           "first_paragraph", "as_is_spec", "is_adopted"]
