"""A repository's own development structure, captured by rule (FR-ALN1, docs/guides/alignment.md).

    rihmasto structure <folder> [--json]

A team that works in Claude Code, Cursor, VS Code or any IDE keeps its own specs, decisions, contracts, tests
and pipelines in the repository, in the conventions its tools use. This module finds them and says what
exists, where, and in which convention: the **structure map**. kernel/alignment.py then proposes how they map
onto a Rihmasto project; nothing here changes anything.

- **specs and requirements**: spec-kit (`specs/<n>-<name>/spec.md`, `plan.md`, `tasks.md`), Kiro
  (`.kiro/specs/<name>/requirements.md`, `design.md`, `tasks.md`), BMAD and agent-os documents, PRDs, RFCs and
  requirement documents, user stories, and Gherkin `.feature` files (kernel/repo_specs.py);
- **decisions**: ADRs under `adr/`, `docs/adr/`, `docs/decisions/` and the like, with their status;
- **API contracts**: OpenAPI and Swagger, AsyncAPI, GraphQL schemas, protobuf, JSON Schema;
- **tests**: the frameworks, the test files and each test's name, how they are run as the manifests state it,
  and coverage configuration (kernel/repo_suites.py);
- **task lists and checklists**, **CI/CD** jobs and what they run, **quality** tools (linters, formatters,
  type checkers, pre-commit), **architecture** documents, and the **AI tools'** setup (kernel/agent_context.py
  when it is present; until then, a hook that names those files and reads none of them).

Nothing found is ever run. A folder is walked as the material scan walks it (no dependency, build or cache
folder, no link followed); a project's repository is read from git's objects at a committed revision, never a
working tree. A file whose name or text may hold a credential is not read and never shown. Dates are commit
dates (`git log`), so a spec can be compared with the code it describes.
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from kernel import material_kinds as mk
from kernel import repo_specs as rs
from kernel import repo_suites as su

SCHEMA = "rihmasto.repo-structure/1"
MAX_FILE = 1024 * 1024               # a file larger than this is listed, not read
MAX_READ = 3000                      # files read at most; more are counted
MAX_TOTAL = 64 * 1024 * 1024
MAX_LOG = 4000                       # commits read for the dates
CODE_EXT = (".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".java", ".kt", ".cs", ".rb", ".php", ".rs",
            ".scala", ".swift", ".vue", ".svelte")
_GIT_ENV = {"GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1", "GIT_CONFIG_NOSYSTEM": "1"}
_GIT_SAFE = ["-c", "credential.helper=", "-c", "core.hooksPath=" + os.devnull]
AI_HOOK = "kernel.agent_context"     # the agent-context stream's module (FR-AGC1): used when present
AI_FILES = re.compile(r"(?i)(^|/)(claude\.md|agents\.md|gemini\.md|\.cursorrules|\.windsurfrules|\.clinerules"
                      r"|\.mcp\.json|\.github/copilot-instructions\.md|\.cursor/(rules|mcp)[^ ]*"
                      r"|\.claude/(skills|agents|commands)/.+|\.claude/settings\.json|\.windsurf/rules/.+"
                      r"|\.github/instructions/.+)$")

CONVENTIONS = (
    ("spec-kit", r"(^|/)(specs/\d{3,4}-[^/]+/[^/]+\.md|\.specify/.+\.md)$"),
    ("Kiro", r"(^|/)\.kiro/(specs|steering)/.+\.md$"),
    ("agent-os", r"(^|/)\.agent-os/.+\.md$"),
    ("BMAD", r"(^|/)(\.bmad-core/.+\.md|docs/(prd|architecture)(\.md|/.+\.md)|docs/stories/.+\.md)$"),
)
_SPEC_NAME = re.compile(r"(?i)(^|/)(prd|spec|specification|requirements?|user[-_ ]?stories|stories|epics?|features?"
                        r"|product[-_ ]brief|brd|srs)([-_.][\w-]*)?\.(md|markdown|rst)$")
_SPEC_DIR = re.compile(r"(?i)(^|/)(specs?|requirements|stories|prd|prds|rfcs?|epics|features|product)/"
                       r"[^/]+\.(md|markdown)$")
_RFC = re.compile(r"(?i)(^|/)(rfcs?/|rfc[-_]?\d+)")
_TASK_NAME = re.compile(r"(?i)(^|/)(tasks?|todo|backlog|checklist|roadmap)([-_.][\w-]*)?\.md$")
_ADR = re.compile(r"(?i)(^|/)(adr|adrs|decisions|decision[-_]records?|decision[-_]log|architecture[-_]decisions)/"
                  r"(?!readme|index|template)[^/]+\.md$")
_ARCH = re.compile(r"(?i)(^|/)(architecture[\w-]*\.md|design\.md|docs/(arch|architecture|design)[^/]*(/[^/]+)?\.md"
                   r"|[^/]+\.(puml|plantuml|dsl|mmd)|\.kiro/steering/.+\.md"
                   r"|specs/\d{3,4}-[^/]+/(plan|data-model)\.md)$")
_API = re.compile(r"(?i)(^|/)([^/]*(openapi|swagger|asyncapi|api)[^/]*\.(ya?ml|json)"
                  r"|(api|apis|openapi|swagger|schemas?|contracts)/[^/]+\.(ya?ml|json)|[^/]+\.schema\.json"
                  r"|[^/]+\.(graphql|gql|graphqls|proto))$")
_MANIFEST = re.compile(r"(?i)(^|/)(package\.json|pyproject\.toml|setup\.cfg|tox\.ini|pytest\.ini|makefile|go\.mod"
                       r"|cargo\.toml|pom\.xml|build\.gradle(\.kts)?|\.coveragerc|\.nycrc(\.json)?|\.?codecov\.yml"
                       r"|(jest|vitest)\.config\.[cm]?[jt]s|conftest\.py)$")
_TEST = re.compile(r"(?i)((^|/)test_[^/]+\.py|_test\.(py|go)|\.(test|spec)\.[cm]?[jt]sx?|(^|/)__tests__/[^/]+\.[jt]sx?"
                   r"|(^|/)src/test/.+\.(java|kt)|tests?\.cs|_spec\.rb)$")


def _is_md(low: str) -> bool:
    return low.endswith((".md", ".markdown", ".rst"))


def _is_spec(low: str) -> bool:
    if not _is_md(low) or _ADR.search(low):
        return False
    return any(re.search(rx, low) for _, rx in CONVENTIONS) or any(
        rx.search(low) for rx in (_SPEC_NAME, _SPEC_DIR, _RFC))


ROLES: tuple[tuple[str, Callable[[str], Any]], ...] = (
    ("feature", lambda low: low.endswith(".feature")),
    ("adr", _ADR.search),
    ("spec", _is_spec),
    ("tasks", lambda low: _is_md(low) and _TASK_NAME.search(low)),
    ("architecture", _ARCH.search),
    ("api", _API.search),
    ("test", lambda low: _TEST.search(low) and not PurePosixPath(low).name.startswith("conftest")),
    ("manifest", _MANIFEST.search),
    ("ci", mk.CI.search),
    ("quality", lambda low: su.quality(low, None) or PurePosixPath(low).name in ("pyproject.toml", "setup.cfg",
                                                                                  "tox.ini")),
    ("ai", AI_FILES.search),
)


def roles(rel: str) -> set[str]:
    """What a path is to the structure map, by its name and folder alone."""
    low = rel.lower()
    out = {role for role, test in ROLES if test(low)}
    return out | ({"code"} if low.endswith(CODE_EXT) and "test" not in out else set())


def convention_of(rel: str) -> str:
    low = rel.lower()
    for name, rx in CONVENTIONS:
        if re.search(rx, low):
            return name
    if low.endswith(".feature"):
        return "Gherkin"
    if _ADR.search(low):
        return "ADR"
    if _RFC.search(low):
        return "RFC"
    if re.search(r"(?i)(^|/)prds?[/.-]", low) or PurePosixPath(low).name.startswith("prd"):
        return "PRD"
    return "document"


def feature_of(rel: str) -> str | None:
    """The feature a spec belongs to: spec-kit's and agent-os's folder (`001-user-auth`), Kiro's spec name."""
    m = re.search(r"(?:^|/)(?:specs|\.kiro/specs|\.agent-os/specs)/([^/]+)/", rel)
    return m.group(1) if m else None


# -- where the files come from ------------------------------------------------------------------------

def _git(cwd: Path, *args: str, data: bytes | None = None) -> bytes:
    """git in ``cwd`` with no prompt, credential helper, hook or LFS download; b"" when it fails."""
    try:
        proc = subprocess.run(["git", *_GIT_SAFE, *args], cwd=cwd, input=data, capture_output=True,
                              env=dict(os.environ) | _GIT_ENV, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return b""
    return proc.stdout if proc.returncode == 0 else b""


def _dates(cwd: Path, revision: str) -> dict[str, int]:
    """Each path's last commit time (seconds), newest first from `git log`; {} outside git."""
    out: dict[str, int] = {}
    stamp = 0
    raw = _git(cwd, "log", "-n", str(MAX_LOG), "--format=%x00%ct", "--name-only", "--no-renames", revision, "--")
    for line in raw.decode("utf-8", "replace").splitlines():
        if line.startswith("\0"):
            stamp = int(line[1:] or 0)
        elif line.strip() and line not in out:
            out[line] = stamp
    return out


class Source:
    """The files of a folder or a revision: their paths and sizes, a reader, and their commit dates."""

    def __init__(self, files: list[tuple[str, int]], read: Callable[[str], bytes | None], dates: dict[str, int],
                 read_from: str, revision: str | None = None, ai: Callable[[], dict[str, Any] | None] | None = None):
        self.files, self.read, self.dates = files, read, dates
        self.read_from, self.revision, self.ai = read_from, revision, ai


def folder_source(root: str | Path) -> Source:
    """A folder on this machine, walked as the material scan walks it; dates from its git history if any."""
    from kernel.material import _walk

    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise ValueError(f"no folder {base}")
    rels, _, _ = _walk(base, ())
    files = []
    for rel in rels:
        try:
            files.append((rel, (base / rel).stat().st_size))
        except OSError:
            continue

    def read(rel: str) -> bytes | None:
        try:
            return (base / rel).read_bytes()
        except OSError:
            return None

    top = _git(base, "rev-parse", "--show-toplevel").decode("utf-8", "replace").strip()
    dates: dict[str, int] = {}
    if top:
        prefix = base.relative_to(Path(top).resolve()).as_posix() if base != Path(top).resolve() else ""
        dates = {k[len(prefix) + 1:] if prefix else k: v for k, v in _dates(base, "HEAD").items()
                 if not prefix or k.startswith(prefix + "/")}

    def ai() -> dict[str, Any] | None:
        mod = _ai_module()
        return mod.from_folder(base) if mod else None

    return Source(files, read, dates, f"the folder {base}", None, ai)


def git_source(repo: str | Path, revision: str) -> Source:
    """A committed revision of a git repository, read from git's objects: never a checkout or a working tree."""
    repo = Path(repo)
    if not revision or revision.startswith("-"):
        raise ValueError(f"{revision!r} is not a revision")
    sha = _git(repo, "rev-parse", "--verify", "-q", f"{revision}^{{commit}}").decode().strip()
    if not sha:
        raise ValueError(f"{revision!r} names no commit in {repo}")
    files, blobs = [], {}
    for entry in _git(repo, "ls-tree", "-r", "-z", "--long", sha).split(b"\0"):
        head, _, path = entry.partition(b"\t")
        parts = head.split()
        if len(parts) == 4 and parts[1] == b"blob" and parts[0] in (b"100644", b"100755"):
            rel = path.decode("utf-8", "replace")
            files.append((rel, int(parts[3]) if parts[3].isdigit() else 0))
            blobs[rel] = parts[2].decode()
    cache: dict[str, bytes] = {}

    def prefetch(rels: list[str]) -> None:
        wanted = [blobs[r] for r in rels if r in blobs]
        raw = _git(repo, "cat-file", "--batch", data="\n".join(wanted).encode() + b"\n") if wanted else b""
        pos, by_sha = 0, {v: k for k, v in blobs.items() if k in rels}
        while pos < len(raw):
            nl = raw.index(b"\n", pos)
            head = raw[pos:nl].split()
            if len(head) < 3 or head[1] != b"blob":
                pos = nl + 1
                continue
            size = int(head[2])
            cache[by_sha.get(head[0].decode(), "")] = raw[nl + 1:nl + 1 + size]
            pos = nl + 1 + size + 1

    def read(rel: str) -> bytes | None:
        return cache.get(rel)

    def ai() -> dict[str, Any] | None:
        mod = _ai_module()
        return mod.from_git(repo, sha) if mod else None

    src = Source(files, read, _dates(repo, sha), f"the committed {revision} ({sha[:12]}) of {repo}", sha, ai)
    src.prefetch = prefetch  # type: ignore[attr-defined]
    return src


def _ai_module() -> Any:
    try:
        return importlib.import_module(AI_HOOK)
    except ModuleNotFoundError as exc:
        if exc.name != AI_HOOK:
            raise
        return None


# -- the structure map --------------------------------------------------------------------------------

def _text(src: Source, rel: str, skipped: list[dict[str, str]]) -> str | None:
    data = src.read(rel)
    if data is None:
        return None
    text = data.decode("utf-8", "replace")
    if mk.secret_in_text(rel, text):
        skipped.append({"path": rel, "why": "may hold secrets: not read, never shown"})
        return None
    return text


def _ai_tools(src: Source, files: list[str]) -> dict[str, Any]:
    try:
        ctx = src.ai() if src.ai else None
    except (RuntimeError, OSError, ValueError):
        ctx = None
    if isinstance(ctx, dict):
        return {"read_by": "kernel/agent_context.py", "found": bool(ctx.get("found")), "counts": ctx.get("counts", {}),
                "files": sorted({e["path"] for g in ("instructions", "skills", "agents", "commands", "settings", "mcp")
                                 for e in ctx.get(g, []) if isinstance(e, dict) and e.get("path")})[:100],
                "stated": ctx.get("stated", [])[:20]}
    names = [r for r in files if AI_FILES.search(r)]
    return {"read_by": "names only: kernel/agent_context.py (FR-AGC1) reads them when it is present",
            "found": bool(names), "counts": {"files": len(names)}, "files": names[:100], "stated": []}


READ_ROLES = ("spec", "feature", "tasks", "adr", "api", "test", "manifest", "ci", "quality", "architecture")


class _Capture:
    """One capture of a source: its files by role, the texts read, and what was not read and why."""

    def __init__(self, src: Source) -> None:
        self.src = src
        self.skipped: list[dict[str, str]] = []
        self.by_role: dict[str, list[str]] = {}
        for rel, _size in src.files:
            if mk.secret_by_name(rel):
                self.skipped.append({"path": rel, "why": "may hold secrets: never opened, by its name"})
                continue
            for role in roles(rel):
                self.by_role.setdefault(role, []).append(rel)
        wanted = self._wanted()
        prefetch = getattr(src, "prefetch", None)
        if prefetch is not None:
            prefetch(wanted)
        self.texts = {rel: t for rel in wanted if (t := _text(src, rel, self.skipped)) is not None}

    def _wanted(self) -> list[str]:
        sizes, total = dict(self.src.files), 0
        wanted: list[str] = []
        for rel in dict.fromkeys(r for role in READ_ROLES for r in self.by_role.get(role, [])):
            size = sizes.get(rel, 0)
            why = (f"larger than {MAX_FILE // 1024} KB: listed, not read" if size > MAX_FILE else
                   "beyond what one scan reads" if len(wanted) >= MAX_READ or total + size > MAX_TOTAL else None)
            if why:
                self.skipped.append({"path": rel, "why": why})
            else:
                wanted.append(rel)
                total += size
        return wanted

    def read(self, role: str) -> list[tuple[str, str]]:
        """(path, text) of the files of a role that were read."""
        return [(rel, self.texts[rel]) for rel in self.by_role.get(role, []) if rel in self.texts]

    def manifests(self) -> tuple[list[dict[str, Any]], set[str]]:
        out, hints = [], set()
        for rel, text in self.read("manifest"):
            facts = su.manifest_facts(rel, text)
            hints |= facts["frameworks"] | ({"pytest"} if rel.lower().endswith("conftest.py") else set())
            out.append({"path": rel, "frameworks": sorted(facts["frameworks"]), "run": facts["run"],
                        "coverage": facts["coverage"], "scripts": facts.get("scripts", {})})
        return out, hints

    def tests(self) -> dict[str, Any]:
        manifests, hints = self.manifests()
        suites = [su.tests_in(rel, text, hints) for rel, text in self.read("test")]
        suites = [s | {"date": self.src.dates.get(s["path"])} for s in suites if s["tests"]]
        return {"frameworks": sorted({s["framework"] for s in suites} | hints), "files": suites,
                "run": list(dict.fromkeys(c for m in manifests for c in m["run"])),
                "coverage": [m["path"] for m in manifests if m["coverage"]], "manifests": manifests,
                "count": sum(len(s["tests"]) for s in suites)}

    def specs(self) -> list[dict[str, Any]]:
        out = _specs(self.by_role, self.texts, self.src.dates)
        code = self.by_role.get("code", []) + self.by_role.get("test", [])
        for spec in out:                      # the code a spec names, with its date, to tell a stale spec
            spec["mentioned"] = [{"path": rel, "date": self.src.dates.get(rel)} for m in spec.pop("mentions")
                                 for rel in code if rel == m or rel.endswith("/" + m)][:40]
        return out

    def sections(self) -> dict[str, Any]:
        dates = self.src.dates
        code = self.by_role.get("code", [])
        return {
            "specs": self.specs(),
            "tasks": [t for rel, text in self.read("tasks") for t in rs.tasks(rel, text)],
            "decisions": [rs.decision(rel, text) | {"date_committed": dates.get(rel)}
                          for rel, text in self.read("adr")],
            "contracts": [c for rel, text in self.read("api") if (c := su.api_contract(rel, text))],
            "tests": self.tests(),
            "ci": [su.ci(rel, text) for rel, text in self.read("ci")],
            "quality": [q for rel in self.by_role.get("quality", []) for q in su.quality(rel, self.texts.get(rel))],
            "architecture": [{"path": rel, "title": rs.doc_title(self.texts.get(rel, ""), PurePosixPath(rel).name),
                              "convention": convention_of(rel)} for rel in self.by_role.get("architecture", [])],
            "ai_tools": _ai_tools(self.src, [r for r, _ in self.src.files]),
            "code": {"files": len(code), "newest": max((dates.get(r, 0) for r in code), default=0) or None},
            "dated": bool(dates), "skipped": self.skipped[:200]}


def _summed(out: dict[str, Any]) -> None:
    """The conventions found and the counts, from the sections."""
    out["conventions"] = sorted({s["convention"] for s in out["specs"]} | ({"ADR"} if out["decisions"] else set())
                                | {c["kind"] for c in out["contracts"]} | set(out["tests"]["frameworks"])
                                | {c["system"] for c in out["ci"]})
    reqs = [r for s in out["specs"] for r in s["requirements"]]
    out["counts"] = {"specs": len(out["specs"]), "requirements": len(reqs),
                     "criteria": sum(len(r["criteria"]) for r in reqs), "tests": out["tests"]["count"],
                     "test_files": len(out["tests"]["files"]), "ci_files": len(out["ci"]),
                     "skipped": len(out["skipped"]),
                     **{k: len(out[k]) for k in ("tasks", "decisions", "contracts", "quality", "architecture")}}


def capture(src: Source) -> dict[str, Any]:
    """The structure map of a source: what exists, where, and in which convention."""
    out: dict[str, Any] = {"schema": SCHEMA, "read_from": src.read_from, "revision": src.revision,
                           "by": "rule (kernel/repo_structure.py), no model; nothing found is run",
                           **_Capture(src).sections()}
    _summed(out)
    return out


def _specs(by_role: dict[str, list[str]], texts: dict[str, str], dates: dict[str, int]) -> list[dict[str, Any]]:
    out = []
    for rel in dict.fromkeys(by_role.get("spec", []) + by_role.get("feature", [])):
        if rel not in texts:
            continue
        text = texts[rel]
        name = PurePosixPath(rel).name.lower()
        kind = ("feature" if name.endswith(".feature") else name.rsplit(".", 1)[0] if name.split(".")[0] in (
            "spec", "plan", "tasks", "requirements", "design", "prd", "research", "data-model", "quickstart")
            else "document")
        if kind in ("plan", "tasks", "design", "research", "data-model", "quickstart"):
            continue                          # a plan, a design or a task list states no requirement of its own
        reqs = rs.gherkin(rel, text) if kind == "feature" else rs.requirements(rel, text)
        if not reqs and kind not in ("spec", "requirements", "prd"):
            continue
        out.append({"path": rel, "convention": convention_of(rel), "kind": kind, "feature": feature_of(rel),
                    "title": rs.doc_title(text, PurePosixPath(rel).name), "requirements": reqs,
                    "date": dates.get(rel), "mentions": _mentions(text)})
    return out


_PATHLIKE = re.compile(r"(?<![\w/])((?:[\w.-]+/)*[\w.-]+\.(?:py|js|mjs|ts|tsx|jsx|go|java|kt|cs|rb|php|rs|vue))\b")


def _mentions(text: str) -> list[str]:
    """The code paths a document names (src/auth/login.py), to compare its date with theirs."""
    return sorted(set(_PATHLIKE.findall(text)))[:80]


# -- entry points ---------------------------------------------------------------------------------------

def from_folder(root: str | Path) -> dict[str, Any]:
    return capture(folder_source(root))


def from_git(repo: str | Path, revision: str) -> dict[str, Any]:
    return capture(git_source(repo, revision))


def source_of(project: Any) -> Source:
    """A project's repository at its committed revision: an adopted project's upstream as last fetched (`sync`
    moves it; the baseline before any), an attached repository's branch. The kernel's own surface commit on an
    adopted project's main is the factory's, not the team's: it is not read."""
    kind = project.meta.get("source_kind")
    if kind == "attached":
        info = project.meta.get("attached") or {}
        return git_source(Path(info["repo"]), info.get("branch") or "HEAD")
    if kind == "adopted" and project.path("repo.git").exists():
        adopted = project.read("adopted.json", {}) or {}
        bare = project.path("repo.git")
        upstream = f"refs/remotes/upstream/{adopted.get('branch') or 'main'}"
        rev = upstream if _git(bare, "rev-parse", "--verify", "-q", upstream + "^{commit}").strip() else None
        return git_source(bare, rev or adopted.get("baseline") or "main")
    raise ValueError(f"{project.pid} has no repository of its own: alignment reads an adopted or attached "
                     "project's repository")


def for_project(project: Any) -> dict[str, Any]:
    return capture(source_of(project))


def listed(items: Any, empty: str) -> str:
    return ", ".join(items) or empty


def render(m: dict[str, Any]) -> str:
    """The structure map as a terminal shows it."""
    c, t, ai = m["counts"], m["tests"], m["ai_tools"]
    lines = [f"Structure of {m['read_from']}", f"Conventions: {listed(m['conventions'], 'none recognised')}", "",
             f"Specs: {c['specs']} documents, {c['requirements']} requirements, {c['criteria']} criteria"]
    lines += [f"  {s['path']} [{s['convention']}, {s['kind']}]: {len(s['requirements'])} requirements"
              for s in m["specs"][:30]]
    lines += [f"Tasks: {c['tasks']} ({sum(x['done'] for x in m['tasks'])} done)", f"Decisions: {c['decisions']}"]
    lines += [f"  {d['ref'] or '-'} {d['title']} ({d['status']}) {d['path']}" for d in m["decisions"][:20]]
    lines.append(f"API contracts: {c['contracts']}")
    lines += [f"  {x['path']} [{x['kind']}] {len(x.get('operations', []))} operations" for x in m["contracts"][:20]]
    lines += [f"Tests: {c['tests']} in {c['test_files']} files; frameworks {listed(t['frameworks'], 'none')}; "
              f"run with {listed(t['run'], 'no stated command')}; coverage {listed(t['coverage'], 'not configured')}",
              f"CI/CD: {c['ci_files']} files"]
    lines += [f"  {f['path']} [{f['system']}] job {j['name']}: {'runs tests' if j['runs_tests'] else 'no tests'}"
              for f in m["ci"][:10] for j in f["jobs"][:10]]
    lines += [f"Quality: {listed(sorted({q['tool'] for q in m['quality']}), 'none')}",
              f"Architecture: {listed([a['path'] for a in m['architecture'][:10]], 'none')}",
              f"AI tools: {len(ai['files'])} files ({ai['read_by']})"]
    lines += [f"Not read: {len(m['skipped'])} files (each with its reason in --json)"] if m["skipped"] else []
    return "\n".join(lines)
