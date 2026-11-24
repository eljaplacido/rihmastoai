"""What a file in a person's folder is, by rule: skipped, secret-looking, binary, code, or a document of a
kind (docs/guides/inputs.md). kernel/material.py walks the folder and keeps to the budget with these rules.

- **Skipped folders**: version control, dependencies, virtual environments, caches and build output.
- **Secret-looking files** are never opened: `.env*` (not `.env.example`), `*.pem`, `*.key`, `id_rsa*`,
  `credentials*`, `*secret*`, key stores and the files kernel/redteam/secretscan.py knows. A file whose
  text holds a credential (`secretscan.check_secrets`) is not read either. Both are listed as
  "skipped: may hold secrets", never with their contents.
- **Kinds**: brief or spec, plan, review or comments, handover, notes, deploy or run log, data, slides,
  code, other: by the file's format, then its name, then its words. The most telling are read first. The
  files a project's AI tools read (CLAUDE.md, AGENTS.md, Cursor rules, skills, MCP servers) are "agent
  context", recognised by kernel/agent_context.py before any of these.
- **Code** is never read as text: it becomes an inventory (languages by extension with file counts,
  entry points, test folders, dependency manifests with the packages they name, CI workflows, Dockerfiles).
"""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any

from kernel.redteam.report import IDLE_MARKER
from kernel.redteam.secretscan import check_secrets, secret_file

SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "bower_components", "jspm_packages", ".venv", "venv", "env", ".env",
    "virtualenv", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".nox", ".cache",
    ".gradle", ".next", ".nuxt", ".parcel-cache", ".turbo", ".angular", ".svelte-kit", "build", "dist", "target",
    "out", "coverage", "htmlcov", ".coverage", ".terraform", "site-packages", ".idea", ".vs", ".vscode-test",
    ".eggs", "obj", ".ipynb_checkpoints", ".dart_tool", "Pods", ".gnomon", ".factory-tasks"})
KIND_LABEL = {"brief": "brief or spec", "plan": "plan", "review": "review or comments", "handover": "handover",
              "notes": "notes", "log": "deploy or run log", "data": "data", "slides": "slides", "code": "code",
              "other": "other", "agent": "agent context"}
PRIORITY = {"agent": 0,                     # agent context ranks first by its own rule (kernel/material.py _rank)
            "brief": 0, "plan": 1, "review": 1, "handover": 1, "code": 1, "notes": 2, "slides": 2, "other": 2,
            "data": 3, "log": 3}
LANGUAGES = {
    ".py": "Python", ".pyi": "Python", ".ipynb": "Jupyter notebook", ".js": "JavaScript", ".mjs": "JavaScript",
    ".cjs": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go",
    ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala", ".cs": "C#",
    ".fs": "F#", ".vb": "Visual Basic", ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++", ".hpp": "C++",
    ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".m": "Objective-C", ".dart": "Dart", ".lua": "Lua",
    ".pl": "Perl", ".r": "R", ".jl": "Julia", ".ex": "Elixir", ".exs": "Elixir", ".erl": "Erlang",
    ".clj": "Clojure", ".hs": "Haskell", ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".ps1": "PowerShell",
    ".bat": "Batch", ".cmd": "Batch", ".sql": "SQL", ".vue": "Vue", ".svelte": "Svelte", ".css": "CSS",
    ".scss": "Sass", ".sass": "Sass", ".less": "Less", ".tf": "Terraform", ".bicep": "Bicep", ".groovy": "Groovy",
    ".gradle": "Gradle", ".sol": "Solidity", ".zig": "Zig", ".nim": "Nim", ".ml": "OCaml", ".elm": "Elm"}
BINARY = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tif", ".tiff", ".heic", ".psd", ".ai", ".sketch",
    ".fig", ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".mp4", ".mov", ".avi", ".mkv", ".webm", ".zip", ".tar", ".gz",
    ".tgz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war", ".ear", ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a",
    ".lib", ".obj", ".class", ".pyc", ".pyo", ".whl", ".egg", ".deb", ".rpm", ".msi", ".dmg", ".iso", ".img", ".woff",
    ".woff2", ".ttf", ".otf", ".eot", ".db", ".sqlite", ".sqlite3", ".mdb", ".accdb", ".parquet", ".avro", ".orc",
    ".feather", ".pkl", ".pickle", ".npy", ".npz", ".h5", ".hdf5", ".onnx", ".pt", ".pth", ".safetensors", ".ckpt",
    ".doc", ".xls", ".ppt", ".vsdx", ".one", ".pages", ".numbers", ".keynote", ".eml", ".msg", ".pst"})
MANIFESTS = re.compile(r"(?i)(requirements[\w.-]*\.txt|constraints[\w.-]*\.txt|pyproject\.toml|setup\.py|setup\.cfg"
                       r"|pipfile(\.lock)?|poetry\.lock|package\.json|package-lock\.json|yarn\.lock|pnpm-lock\.yaml"
                       r"|go\.mod|go\.sum|cargo\.toml|cargo\.lock|pom\.xml|build\.gradle(\.kts)?|settings\.gradle"
                       r"|gemfile(\.lock)?|composer\.json|composer\.lock|[\w.-]+\.csproj|[\w.-]+\.sln|deno\.json"
                       r"|dockerfile[\w.-]*|[\w.-]*\.dockerfile|docker-compose[\w.-]*\.ya?ml|compose\.ya?ml|makefile"
                       r"|cmakelists\.txt|environment\.ya?ml|tsconfig\.json|vite\.config\.\w+|webpack\.config\.\w+)")
CI = re.compile(r"(?i)(^|/)(\.github/workflows/[^/]+\.ya?ml|\.gitlab-ci\.ya?ml|azure-pipelines\.ya?ml|jenkinsfile"
                r"|\.circleci/config\.ya?ml|bitbucket-pipelines\.ya?ml|\.drone\.ya?ml|\.travis\.ya?ml)$")
ENTRY = re.compile(r"(?i)^(main|app|server|manage|wsgi|asgi|cli|run|index|__main__|program|startup)"
                   r"\.(py|js|mjs|ts|go|rs|java|kt|cs|rb|php)$")
TEST_DIRS = frozenset({"tests", "test", "__tests__", "spec", "specs", "testing", "e2e", "cypress", "playwright"})
TEST_FILE = re.compile(r"(?i)(^test_.+\.py|.+_test\.(py|go)|.+\.(test|spec)\.(js|ts|jsx|tsx|mjs))$")
CODE_HTML_DIRS = frozenset({"src", "static", "public", "templates", "app", "components", "www", "web", "views"})
HOUSEKEEPING = re.compile(r"(changelog|changes|history|news|releases?|licen[cs]e|copying|notice|security"
                          r"|contributing|code_of_conduct|authors|contributors|maintainers|codeowners|support"
                          r"|governance|funding|third[-_]party\w*|licen[cs]e[-_.]\w+)(\.(md|markdown|txt|rst))?",
                          re.IGNORECASE)
SECRET_NAME = re.compile(r"(?i)^(\.env(\..*)?|.*\.env|.*\.pem|.*\.key|.*\.p12|.*\.pfx|.*\.jks|.*\.keystore"
                         r"|.*\.kdbx|id_(rsa|dsa|ecdsa|ed25519)(\..*)?|credentials.*|.*secrets?.*|\.netrc|_netrc"
                         r"|\.git-credentials|\.htpasswd|\.pgpass|.*\.tfstate(\..*)?|.*\.ovpn|.*\.ppk)$")
SAFE_ENV = re.compile(r"(?i)^\.env\.(example|sample|template|dist|defaults?|schema)$|^(example|sample)\.env$")
NAME_HINTS = (
    ("log", re.compile(r"(^|[-_. /])(logs?|deploy[-_]?log|run[-_]?log|build[-_]?log|output)([-_. /]|$)")),
    ("brief", re.compile(r"readme|brief|spec|requirement|vaatimu|määrittely|maarittely|(^|[-_. /])prd|scope"
                         r"|(^|[-_. /])needs?([-_. /]|$)|tarve|(^|[-_. /])input|charter|proposal|tarjous|rfp|rfq"
                         r"|user[-_ ]?stor|use[-_ ]?case|tehtävänanto|toimeksianto")),
    ("plan", re.compile(r"plan|roadmap|design|architect|decision|(^|[-_. /])adr|milestone|suunnitel|schedule"
                        r"|aikataulu|strategy|strategia")),
    ("review", re.compile(r"review|comment|feedback|palaute|audit|retro|katselm|kommentti|(^|[-_. /])issues?")),
    ("handover", re.compile(r"hand-?over|hand-?off|onboard|runbook|playbook|operations|luovutus|ylläpito"
                            r"|maintenance|howto|how-to|guide|manual|ohje")),
    ("notes", re.compile(r"note|meeting|minutes|muistio|memo|journal|diary|todo|backlog|ideas?|palaveri")),
    ("slides", re.compile(r"slides?|deck|presentation|esitys")),
)
_TIMESTAMP = re.compile(r"^\s*\[?\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}|^\s*\[?\d{2}:\d{2}:\d{2}"
                        r"|^\s*(INFO|WARN|ERROR|DEBUG)\b")
_ACCEPTANCE = re.compile(r"(?im)^\s*[-*]?\s*(given|when|then)\b|acceptance criteria|hyväksymiskriteeri")
_MODAL = re.compile(r"(?i)\b(must|shall|should|pitää|täytyy)\b")
_DECISION = re.compile(r"(?im)^\s*(#+\s*)?(decision|päätös|we decided|decided:)")


def skipped_dir(name: str, has_venv_marker: bool) -> str | None:
    """Why a folder is not walked, or None."""
    if name in SKIP_DIRS or name.endswith(".egg-info"):
        return "dependencies, build output, a cache or version control"
    if has_venv_marker:
        return "a Python virtual environment"
    return None


def secret_by_name(rel: str) -> bool:
    """Whether a file's name says it may hold secrets: it is never opened."""
    name = PurePosixPath(rel).name
    if SAFE_ENV.match(name):
        return False
    return bool(SECRET_NAME.match(name)) or secret_file(rel, "") is not None


def secret_in_text(rel: str, text: str) -> bool:
    """Whether a file's text holds something that looks like a credential (kernel/redteam/secretscan.py):
    a key with a known format, a private key, or a random value assigned to a credential name."""
    if secret_file(rel, text[:4096]) is not None:
        return True
    hits, canaries = check_secrets(rel, text)
    return bool(hits) or any(kind != IDLE_MARKER for _, kind, _ in canaries)


def language(rel: str) -> str | None:
    """The language of a code file, by its extension; HTML is code under a web app's folders."""
    p = PurePosixPath(rel.lower())
    if p.suffix in (".html", ".htm") and set(p.parts[:-1]) & CODE_HTML_DIRS:
        return "HTML"
    return LANGUAGES.get(p.suffix)


def kind_of(rel: str, ext: str, text: str = "") -> str:
    """A document's kind: by its format, then by its name, then by its words."""
    if ext in (".pptx", ".odp"):
        return "slides"
    if ext in (".csv", ".tsv", ".xlsx", ".ods", ".json", ".yaml", ".yml", ".toml"):
        return "data"
    if ext == ".log":
        return "log"
    name = rel.lower()
    for kind, rule in NAME_HINTS:
        if rule.search(name):
            return kind
    return content_kind(text)


def content_kind(text: str) -> str:
    """A document whose name says nothing, by its words: criteria and many musts read as a brief, decisions
    as a plan, timestamped lines as a log."""
    lines = [x for x in text.splitlines()[:400] if x.strip()]
    if len(lines) >= 5 and sum(bool(_TIMESTAMP.match(x)) for x in lines) * 2 >= len(lines):
        return "log"
    if _ACCEPTANCE.search(text) or sum(bool(_MODAL.search(x)) for x in lines) >= 3:
        return "brief"
    if len(_DECISION.findall(text)) >= 2:
        return "plan"
    return "other"


# -- the code inventory ----------------------------------------------------------------------------------

def _packages(rel: str, text: str) -> list[str]:
    """The packages a dependency manifest names (never its other contents)."""
    name = PurePosixPath(rel).name.lower()
    if name.startswith("requirements") and name.endswith(".txt"):
        return [m.group(1) for m in re.finditer(r"(?m)^\s*([A-Za-z0-9][\w.-]*)", text)]
    if name == "package.json":
        try:
            data = json.loads(text)
        except (ValueError, RecursionError):   # a manifest nested to break a parser is not read
            return []
        if not isinstance(data, dict):
            return []
        deps = [*(data.get("dependencies") or {}), *(data.get("devDependencies") or {})]
        return [str(d) for d in deps][:60]
    if name == "go.mod":
        return re.findall(r"(?m)^\s*(?:require\s+)?([\w.-]+\.[\w./-]+)\s+v\d", text)
    if name == "pyproject.toml":
        block = re.search(r"(?s)dependencies\s*=\s*\[(.*?)\]", text)
        return re.findall(r"[\"']([A-Za-z0-9][\w.-]*)", block.group(1)) if block else []
    return []


def _test_folder(rel: str) -> str | None:
    """The test folder a code file belongs to (its nearest folder named like tests), or its own folder when
    its name says it is a test; None for other code."""
    parts = PurePosixPath(rel).parts
    folder = next(("/".join(parts[:i + 1]) + "/" for i, x in enumerate(parts[:-1]) if x.lower() in TEST_DIRS), None)
    if folder or not TEST_FILE.match(parts[-1]):
        return folder
    return "/".join(parts[:-1]) + "/" if len(parts) > 1 else "./"


def inventory(code: list[str], manifests: dict[str, str], ci: list[str]) -> dict[str, Any]:
    """The code inventory, by rule: languages with file counts, entry points, test folders, dependency
    manifests and the packages they name, CI workflows and Dockerfiles. No code is read."""
    langs: dict[str, int] = {}
    tests: dict[str, int] = {}
    for rel in code:
        lang = language(rel)
        if lang:
            langs[lang] = langs.get(lang, 0) + 1
        key = _test_folder(rel)
        if key:
            tests[key] = tests.get(key, 0) + 1
    entries = sorted((r for r in code if ENTRY.match(PurePosixPath(r).name)), key=lambda r: (r.count("/"), r))
    return {"files": len(code), "languages": [{"language": k, "files": v} for k, v in
                                              sorted(langs.items(), key=lambda kv: (-kv[1], kv[0]))],
            "entry_points": entries[:12], "tests": [{"folder": k, "files": v} for k, v in sorted(tests.items())][:12],
            "manifests": [{"file": k, "packages": _packages(k, t)[:30]} for k, t in sorted(manifests.items())][:30],
            "ci": sorted(ci)[:12],
            "dockerfiles": sorted(k for k in manifests if "dockerfile" in k.lower() or "compose" in k.lower())[:12]}


def inventory_text(inv: dict[str, Any]) -> str:
    """The inventory as the panel reads it."""
    out = ["Code inventory, by rule (the code itself is not read):",
           "- languages: " + (", ".join(f"{x['language']} ({x['files']} files)" for x in inv["languages"]) or "none"),
           "- entry points: " + (", ".join(inv["entry_points"]) or "none found by name"),
           "- tests: " + (", ".join(f"{t['folder']} ({t['files']} file{'s' if t['files'] != 1 else ''})"
                                     for t in inv["tests"]) or "none found")]
    for m in inv["manifests"]:
        out.append(f"- dependency manifest {m['file']}" + (": " + ", ".join(m["packages"]) if m["packages"] else ""))
    out.append("- CI workflows: " + (", ".join(inv["ci"]) or "none"))
    return "\n".join(out)
