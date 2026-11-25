"""A repository's test suites, CI/CD, API contracts and quality tools, read by rule (FR-ALN1).

Companion to kernel/repo_specs.py, for kernel/repo_structure.py. Nothing here runs anything: a test is
known by its file and its name, a CI job by the commands it says it runs, a script by its text. YAML is read
by its indentation, as far as these files need, with no YAML library and nothing evaluated.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

from kernel.agent_context import _dict as _object  # a JSON object as a dict; {} for anything else

MAX_TESTS = 2000                    # per file
TEST_CMD = re.compile(
    r"(?i)(\bpy\.?test\b|\bunittest\b|\bnose2?\b|\btox\b|\bnox\b|\b(npm|pnpm|yarn|bun)\s+(run\s+)?test|\bnpm\s+t\b"
    r"|\bjest\b|\bvitest\b|\bmocha\b|\bkarma\b|\bcypress\s+run|\bplaywright\s+test|\bgo\s+test\b"
    r"|\bcargo\s+(test|nextest)|\bmvnw?\b[^\n]*\b(test|verify)\b|\bgradlew?\b[^\n]*\b(test|check)\b|\bdotnet\s+test"
    r"|\brspec\b|\brake\s+test|\bphpunit\b|\bmake\s+(test|check)\b|\bctest\b|\bbazel\s+test|manage\.py\s+test"
    r"|\bdeno\s+test|\bbehave\b|\bcucumber\b)")
_PY_DEF = re.compile(r"^(?P<ind>\s*)(?:async\s+)?def\s+(?P<name>test\w*)\s*\(")
_PY_CLASS = re.compile(r"^(?P<ind>\s*)class\s+(?P<name>\w+)")
_JS_TEST = re.compile(r"""\b(?:it|test|specify)(?:\.(?:only|skip|concurrent|each\([^)]*\)))?\s*\(\s*(['"`])"""
                      r"""(?P<name>.+?)\1""")
_JS_DESCRIBE = re.compile(r"""\bdescribe(?:\.(?:only|skip|each\([^)]*\)))?\s*\(\s*(['"`])(?P<name>.+?)\1""")
_GO_TEST = re.compile(r"^func\s+(?P<name>Test\w*)\s*\(\s*\w+\s+\*testing\.T\s*\)")
_JVM_TEST = re.compile(r"^\s*(?:public\s+|private\s+|internal\s+)?(?:void|fun|async\s+Task|Task)\s+`?"
                       r"(?P<name>[\w ]+?)`?\s*\(")
_RB_TEST = re.compile(r"""^\s*it\s+(['"])(?P<name>.+?)\1""")
_ANNOTATION = re.compile(r"^\s*(@Test|@ParameterizedTest|\[Fact\]|\[Theory\]|\[Test\]|\[TestMethod\]|\[TestCase)")
_JS_FILE = re.compile(r"(\.(test|spec)\.[cm]?[jt]sx?$|/__tests__/|\.[cm]?[jt]sx?$)")
JS_FRAMEWORKS = ("jest", "vitest", "mocha", "jasmine", "playwright", "cypress")
HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
RUN_KEYS = ("run", "script", "command", "bash", "pwsh", "powershell", "sh", "cmd")
_GITLAB_RESERVED = {"stages", "variables", "image", "services", "before_script", "after_script", "cache", "include",
                    "default", "workflow", "pages"}
_BY_SUFFIX = (("_test.go", "go test"), (".java", "junit"), (".kt", "junit"), ("_spec.rb", "rspec"))
Test = dict[str, Any]


def _py_framework(text: str, hints: set[str]) -> str:
    if "pytest" in hints or re.search(r"^\s*(import|from)\s+pytest\b", text, re.MULTILINE):
        return "pytest"
    return "unittest" if re.search(r"\bunittest\b|TestCase\)", text) else "pytest"


def _js_framework(rel: str, text: str, hints: set[str]) -> str:
    for fw in ("vitest", "@playwright/test", "mocha", "jasmine"):
        if f"'{fw}'" in text or f'"{fw}"' in text or fw in hints:
            return fw.replace("@playwright/test", "playwright")
    return "cypress" if rel.startswith("cypress/") else "jest"


def framework_of(rel: str, text: str, hints: set[str]) -> str:
    """The test framework a test file is written for, from its imports and the repository's manifests."""
    name = PurePosixPath(rel).name.lower()
    if name.endswith(".py"):
        return _py_framework(text, hints)
    if name.endswith(".cs"):
        return "xunit" if "[Fact]" in text else "nunit" if "[Test]" in text else "mstest"
    found = next((fw for suffix, fw in _BY_SUFFIX if name.endswith(suffix)), None)
    if found:
        return found
    return _js_framework(rel, text, hints) if _JS_FILE.search(rel.lower()) else "unknown"


def _test(name: str, i: int, lines: list[str], suite: str | None = None, doc: str = "") -> Test:
    """A test with the text around its definition (for a suggested rename)."""
    return {"name": name, "line": i + 1, "suite": suite, "doc": doc[:200], "ctx": lines[max(0, i - 1):i + 2]}


def _docstring(lines: list[str], i: int) -> str:
    doc = lines[i + 1].strip() if i + 1 < len(lines) else ""
    return doc.strip("\"' ").removeprefix("r") if doc.startswith(('"""', "'''", 'r"""')) else ""


def _py_tests(lines: list[str]) -> list[Test]:
    found: list[Test] = []
    klass: tuple[int, str] | None = None
    for i, line in enumerate(lines):
        c = _PY_CLASS.match(line)
        klass = (len(c.group("ind")), c.group("name")) if c else klass
        m = _PY_DEF.match(line)
        if not m:
            continue
        klass = None if klass and len(m.group("ind")) <= klass[0] else klass
        found.append(_test(m.group("name"), i, lines, klass[1] if klass else None, _docstring(lines, i)))
    return found


def _js_tests(lines: list[str]) -> list[Test]:
    found: list[Test] = []
    describe: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        ind = len(line) - len(line.lstrip())
        describe = [x for x in describe if x[0] < ind]
        d, m = _JS_DESCRIBE.search(line), _JS_TEST.search(line)
        if d:
            describe.append((ind, d.group("name")))
        elif m:
            found.append(_test(m.group("name"), i, lines, " > ".join(x[1] for x in describe) or None))
    return found


def _line_tests(rx: re.Pattern) -> Callable[[list[str]], list[Test]]:
    def read(lines: list[str]) -> list[Test]:
        return [_test(m.group("name").strip(), i, lines) for i, line in enumerate(lines) if (m := rx.match(line))]
    return read


def _annotated_tests(lines: list[str]) -> list[Test]:
    """JUnit, xUnit and NUnit: a method after a test annotation."""
    found: list[Test] = []
    pending = False
    for i, line in enumerate(lines):
        m = _JVM_TEST.match(line) if pending else None
        if m:
            found.append(_test(m.group("name").strip(), i, lines))
        pending = bool(_ANNOTATION.match(line)) or (pending and m is None)
    return found


READERS: dict[str, Callable[[list[str]], list[Test]]] = {
    "pytest": _py_tests, "unittest": _py_tests, "go test": _line_tests(_GO_TEST), "rspec": _line_tests(_RB_TEST),
    **{fw: _js_tests for fw in JS_FRAMEWORKS}}


def tests_in(rel: str, text: str, hints: set[str]) -> dict[str, Any]:
    """A test file: its framework and its tests, each with its name, line, the text around its definition (for
    a suggested rename) and, for Python, its docstring's first line."""
    fw = framework_of(rel, text, hints)
    found = READERS.get(fw, _annotated_tests)(text.splitlines())
    return {"path": rel, "framework": fw, "tests": found[:MAX_TESTS]}


# -- manifests: how the tests are run, never running them ------------------------------------------------

def _json(text: str) -> dict[str, Any]:
    try:
        return _object(json.loads(text))
    except (ValueError, RecursionError):
        return {}


def _package_json(text: str) -> dict[str, Any]:
    doc = _json(text)
    deps = {**_object(doc.get("dependencies")), **_object(doc.get("devDependencies"))}
    scripts = _object(doc.get("scripts"))
    tests = [k for k in scripts if k == "test" or k.startswith("test")]
    return {"frameworks": {d for d in ("jest", "vitest", "mocha", "jasmine", "@playwright/test", "cypress", "karma",
                                        "ava") if d in deps},
            "run": [f"npm run {k}" if k != "test" else "npm test" for k in tests][:6],
            "scripts": {k: str(scripts[k])[:200] for k in tests},
            "coverage": any(x in text for x in ("coverageThreshold", "--coverage", "c8 ", "nyc"))}


def _python_config(name: str, text: str) -> dict[str, Any]:
    pytest = name == "pytest.ini" or any(x in text for x in ("[tool.pytest", "[pytest]", "[tool:pytest]"))
    return {"frameworks": {"pytest"} if pytest else set(),
            "run": (["pytest"] if pytest else []) + (["tox"] if name == "tox.ini" else []),
            "coverage": any(x in text for x in ("[tool.coverage", "[coverage:", "--cov"))}


def _makefile(text: str) -> dict[str, Any]:
    return {"run": [f"make {t}" for t in re.findall(r"^(test[\w-]*|check)\s*:", text, re.MULTILINE)[:4]]}


def _python_reader(name: str) -> Callable[[str], dict[str, Any]]:
    return lambda text: _python_config(name, text)


def _jvm(run: str) -> Callable[[str], dict[str, Any]]:
    return lambda text: {"frameworks": {"junit"}, "run": [run], "coverage": "jacoco" in text}


MANIFEST_READERS: dict[str, Callable[[str], dict[str, Any]]] = {
    "package.json": _package_json, "makefile": _makefile,
    "go.mod": lambda text: {"frameworks": {"go test"}, "run": ["go test ./..."]},
    "cargo.toml": lambda text: {"run": ["cargo test"]}, "pom.xml": _jvm("mvn test"),
    "build.gradle": _jvm("gradle test"), "build.gradle.kts": _jvm("gradle test"),
    **{n: (lambda text: {"coverage": True}) for n in (".coveragerc", ".nycrc", ".nycrc.json", "codecov.yml",
                                                     ".codecov.yml")},
    **{n: (lambda text: {"coverage": "coverage" in text.lower()}) for n in (
        "jest.config.js", "jest.config.ts", "vitest.config.ts", "vitest.config.js")},
    **{n: _python_reader(n) for n in ("pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini")},
}


def manifest_facts(rel: str, text: str) -> dict[str, Any]:
    """What a manifest says about testing: the frameworks it names, the test command it states (never run),
    and whether it configures coverage."""
    read = MANIFEST_READERS.get(PurePosixPath(rel).name.lower())
    found = read(text) if read else {}
    return {"frameworks": set(), "run": [], "coverage": False} | found


# -- YAML by indentation --------------------------------------------------------------------------------

def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _value(lines: list[str], i: int, after: str) -> tuple[list[str], int]:
    """The value of a key on line ``i``: inline, a block scalar (| or >) or a list of items below it."""
    after = after.strip()
    base = _indent(lines[i])
    if after and not after.startswith(("|", ">")):
        return [after.strip("'\"")], i + 1
    out, j = [], i + 1
    while j < len(lines) and (not lines[j].strip() or _indent(lines[j]) > base
                              or (lines[j].lstrip().startswith("- ") and _indent(lines[j]) == base and not after)):
        s = lines[j].strip()
        if s and not s.startswith("#"):
            out.append(s[2:].strip("'\"") if (s.startswith("- ") and not after) else s)
        j += 1
    return out, j


def _commands(lines: list[str], start: int, end: int) -> list[str]:
    """Every command a block of a CI file runs: the values of run, script, command, bash and the rest."""
    cmds: list[str] = []
    i = start
    while i < end:
        m = re.match(r"^([\w-]+)\s*:\s*(.*)$", lines[i].strip().removeprefix("- "))
        if m and m.group(1) in RUN_KEYS:
            vals, j = _value(lines, i, m.group(2))
            cmds += [v for v in vals if v and not v.startswith(("name:", "when:", "working_directory:"))]
            i = max(j, i + 1)
        else:
            i += 1
    return [c[:200] for c in cmds][:60]


def _keys_at(lines: list[str], start: int, end: int, level: int | None = None) -> list[tuple[int, str]]:
    """(line index, key) of the mapping keys at the first indentation found below ``start``."""
    out: list[tuple[int, str]] = []
    for i in range(start, end):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith(("#", "- ")):
            continue
        level = _indent(line) if level is None else level
        if _indent(line) < level:
            break
        m = re.match(r"^(\s*)([\w.\-/{}\"' ]+?)\s*:(\s|$)", line)
        if m and len(m.group(1)) == level:
            out.append((i, m.group(2).strip("'\"")))
    return out


def _block_end(lines: list[str], i: int) -> int:
    base, j = _indent(lines[i]), i + 1
    while j < len(lines) and (not lines[j].strip() or _indent(lines[j]) > base or lines[j].lstrip().startswith("#")):
        j += 1
    return j


def _top(lines: list[str]) -> dict[str, int]:
    return {k: i for i, k in _keys_at(lines, 0, len(lines), 0)}


# -- CI/CD ----------------------------------------------------------------------------------------------

def _job(name: str, cmds: list[str], uses: list[str] | None = None) -> dict[str, Any]:
    return {"name": name, "runs": cmds, "uses": (uses or [])[:20],
            "runs_tests": any(TEST_CMD.search(c) for c in cmds)}


def _jobs_under(lines: list[str], at: int) -> list[dict[str, Any]]:
    """GitHub Actions and CircleCI: the keys under `jobs:`, each with its commands and the actions it uses."""
    out = []
    for j, key in _keys_at(lines, at + 1, _block_end(lines, at)):
        jend = _block_end(lines, j)
        uses = [u.strip().removeprefix("- ").removeprefix("uses:").strip() for u in lines[j:jend]
                if re.match(r"^\s*(-\s*)?uses\s*:", u)]
        out.append(_job(key, _commands(lines, j + 1, jend), uses))
    return out


def _gitlab_jobs(lines: list[str]) -> list[dict[str, Any]]:
    return [_job(key, _commands(lines, i + 1, _block_end(lines, i))) for key, i in _top(lines).items()
            if key not in _GITLAB_RESERVED and not key.startswith(".")]


def _listed_jobs(lines: list[str]) -> list[dict[str, Any]]:
    """Azure Pipelines and the rest: `- job:` (or stage, deployment) entries, or the whole file as one."""
    named = [(i, m.group(1)) for i, line in enumerate(lines)
             if (m := re.match(r"^\s*-\s*(?:job|deployment|stage)\s*:\s*([\w-]+)", line))]
    if not named:
        return [_job("pipeline", _commands(lines, 0, len(lines)))]
    stops = [i for i, _ in named[1:]] + [len(lines)]
    return [_job(key, _commands(lines, i, stop)) for (i, key), stop in zip(named, stops, strict=True)]


def _jenkins(text: str) -> list[dict[str, Any]]:
    stages = re.findall(r"stage\s*\(\s*['\"](.+?)['\"]", text)
    cmds = re.findall(r"\b(?:sh|bat|powershell)\s*\(?\s*(?:script\s*:\s*)?['\"]{1,3}(.+?)['\"]{1,3}", text)
    return [_job(", ".join(stages[:6]) or "pipeline", cmds)]


CI_SYSTEMS = (("jenkinsfile", "Jenkins"), (".github/workflows/", "GitHub Actions"), ("gitlab-ci", "GitLab CI"),
              ("azure-pipelines", "Azure Pipelines"), (".circleci/", "CircleCI"),
              ("bitbucket-pipelines", "Bitbucket Pipelines"))


def ci(rel: str, text: str) -> dict[str, Any]:
    """A CI/CD file's system and jobs, each with the commands it runs and whether one of them runs tests."""
    low = rel.lower()
    system = next((name for marker, name in CI_SYSTEMS if marker in low), "CI")
    lines = text.splitlines()
    top = _top(lines)
    if system == "Jenkins":
        jobs = _jenkins(text)
    elif system in ("GitHub Actions", "CircleCI") and "jobs" in top:
        jobs = _jobs_under(lines, top["jobs"])
    elif system == "GitLab CI":
        jobs = _gitlab_jobs(lines)
    else:
        jobs = _listed_jobs(lines)
    return {"path": rel, "system": system, "jobs": jobs[:40]}


# -- API contracts --------------------------------------------------------------------------------------

def _yaml_scalar(lines: list[str], key: str, level: int = 0) -> str | None:
    found = (re.match(rf"^\s{{{level}}}{re.escape(key)}\s*:\s*(.+?)\s*$", line) for line in lines)
    return next((m.group(1).strip("'\"") for m in found if m), None)


def _operation(lines: list[str], k: int, method: str, path: str) -> dict[str, Any]:
    block = lines[k + 1:_block_end(lines, k)]
    return {"method": method.upper(), "path": path, "line": k + 1,
            "operation": _yaml_scalar([b.strip() for b in block], "operationId"),
            "summary": (_yaml_scalar([b.strip() for b in block], "summary") or "")[:160]}


def _openapi_yaml(lines: list[str]) -> dict[str, Any]:
    top = _top(lines)
    info = lines[top["info"] + 1:_block_end(lines, top["info"])] if "info" in top else []
    ops: list[dict[str, Any]] = []
    for section in ("paths", "channels"):
        at = top.get(section)
        for j, path in _keys_at(lines, at + 1, _block_end(lines, at)) if at is not None else []:
            ops += [_operation(lines, k, method, path) for k, method in _keys_at(lines, j + 1, _block_end(lines, j))
                    if method.lower() in HTTP_METHODS or section == "channels"]
    return {"title": _yaml_scalar(info, "title", 2), "version": _yaml_scalar(info, "version", 2),
            "operations": ops[:400]}


def _openapi_json(doc: dict[str, Any]) -> dict[str, Any]:
    info, paths = _object(doc.get("info")), _object(doc.get("paths"))
    ops =[{"method": method.upper(), "path": path, "line": None, "operation": op.get("operationId"),
            "summary": str(op.get("summary") or "")[:160]}
           for path, item in paths.items() if isinstance(item, dict)
           for method, op in item.items() if method.lower() in HTTP_METHODS and isinstance(op, dict)]
    return {"title": info.get("title"), "version": info.get("version"), "operations": ops[:400]}


def _graphql(rel: str, text: str) -> dict[str, Any]:
    types = re.findall(r"^\s*(?:extend\s+)?(?:type|input|enum|interface|union|scalar)\s+(\w+)", text, re.MULTILINE)
    fields = []
    for root in ("Query", "Mutation", "Subscription"):
        m = re.search(rf"type\s+{root}\s*\{{(.*?)\}}", text, re.DOTALL)
        fields += [{"method": root.upper(), "path": f, "operation": f, "summary": ""}
                   for f in re.findall(r"^\s*(\w+)\s*[(:]", m.group(1), re.MULTILINE)] if m else []
    return {"path": rel, "kind": "GraphQL", "title": PurePosixPath(rel).name, "version": None, "types": types[:200],
            "operations": fields[:300]}


def _proto(rel: str, text: str) -> dict[str, Any]:
    rpcs = [{"method": "RPC", "path": r, "operation": r, "summary": ""}
            for r in re.findall(r"\brpc\s+(\w+)\s*\(", text)]
    pkg = re.search(r"^\s*package\s+([\w.]+)\s*;", text, re.MULTILINE)
    types = re.findall(r"^\s*(?:service|message)\s+(\w+)", text, re.MULTILINE)
    return {"path": rel, "kind": "protobuf", "title": pkg.group(1) if pkg else PurePosixPath(rel).name,
            "version": None, "types": types[:200], "operations": rpcs[:300]}


def _json_contract(rel: str, text: str) -> dict[str, Any] | None:
    doc = _json(text)
    if "openapi" in doc or "swagger" in doc:
        return {"path": rel, "kind": "OpenAPI" if "openapi" in doc else "Swagger", **_openapi_json(doc)}
    if "json-schema" not in str(doc.get("$schema", "")):
        return None
    props = _object(doc.get("properties"))
    return {"path": rel, "kind": "JSON Schema", "title": doc.get("title") or doc.get("$id") or rel, "version": None,
            "types": list(props)[:100], "operations": []}


def _yaml_contract(rel: str, text: str) -> dict[str, Any] | None:
    lines = text.splitlines()
    head = _top(lines)
    kind = next((k for key, k in (("openapi", "OpenAPI"), ("swagger", "Swagger"), ("asyncapi", "AsyncAPI"))
                 if key in head), None)
    return {"path": rel, "kind": kind, **_openapi_yaml(lines)} if kind else None


def api_contract(rel: str, text: str) -> dict[str, Any] | None:
    """An API contract: OpenAPI or Swagger (YAML or JSON), AsyncAPI, a GraphQL schema, a protobuf file or a
    JSON Schema, with what it declares. None when the file is none of these."""
    low = rel.lower()
    if low.endswith((".graphql", ".gql", ".graphqls")):
        return _graphql(rel, text)
    if low.endswith(".proto"):
        return _proto(rel, text)
    if low.endswith(".json"):
        return _json_contract(rel, text)
    return _yaml_contract(rel, text) if low.endswith((".yaml", ".yml")) else None


# -- quality tools --------------------------------------------------------------------------------------

QUALITY_FILES = (
    (r"(^|/)(\.?ruff\.toml)$", "ruff", "linter and formatter"), (r"(^|/)\.flake8$", "flake8", "linter"),
    (r"(^|/)\.?pylintrc$", "pylint", "linter"), (r"(^|/)\.?mypy\.ini$", "mypy", "type checker"),
    (r"(^|/)pyrightconfig\.json$", "pyright", "type checker"), (r"(^|/)\.isort\.cfg$", "isort", "formatter"),
    (r"(^|/)(\.eslintrc(\.\w+)?|eslint\.config\.[cm]?[jt]s)$", "eslint", "linter"),
    (r"(^|/)(\.prettierrc(\.\w+)?|prettier\.config\.[cm]?js)$", "prettier", "formatter"),
    (r"(^|/)tsconfig(\.[\w-]+)?\.json$", "TypeScript", "type checker"),
    (r"(^|/)biome\.jsonc?$", "biome", "linter and formatter"), (r"(^|/)\.stylelintrc(\.\w+)?$", "stylelint", "linter"),
    (r"(^|/)\.golangci\.ya?ml$", "golangci-lint", "linter"), (r"(^|/)\.rubocop\.yml$", "rubocop", "linter"),
    (r"(^|/)\.editorconfig$", "EditorConfig", "formatter"),
    (r"(^|/)\.pre-commit-config\.yaml$", "pre-commit", "git hooks"),
    (r"(^|/)\.husky/[^/]+$", "husky", "git hooks"), (r"(^|/)\.clang-format$", "clang-format", "formatter"),
    (r"(^|/)rustfmt\.toml$", "rustfmt", "formatter"), (r"(^|/)clippy\.toml$", "clippy", "linter"),
    (r"(^|/)\.swiftlint\.yml$", "swiftlint", "linter"),
    (r"(^|/)sonar-project\.properties$", "SonarQube", "static analysis"),
    (r"(^|/)\.markdownlint(\.\w+)?$", "markdownlint", "linter"), (r"(^|/)checkstyle\.xml$", "checkstyle", "linter"),
)
SECTION_TOOLS = (("[tool.ruff", "ruff", "linter and formatter"), ("[tool.black", "black", "formatter"),
                 ("[tool.mypy", "mypy", "type checker"), ("[mypy", "mypy", "type checker"),
                 ("[tool.pyright", "pyright", "type checker"), ("[tool.isort", "isort", "formatter"),
                 ("[flake8", "flake8", "linter"), ("[tool.pylint", "pylint", "linter"))


def quality(rel: str, text: str | None) -> list[dict[str, Any]]:
    """The linters, formatters, type checkers and hooks a file configures."""
    out: list[dict[str, Any]] = [{"path": rel, "tool": tool, "kind": kind} for rx, tool, kind in QUALITY_FILES
                                 if re.search(rx, rel.lower())]
    name = PurePosixPath(rel).name.lower()
    if text and name in ("pyproject.toml", "setup.cfg", "tox.ini"):
        out += [{"path": rel, "tool": tool, "kind": kind} for marker, tool, kind in SECTION_TOOLS if marker in text]
    if text and name == ".pre-commit-config.yaml":
        hooks = re.findall(r"^\s*-\s*id\s*:\s*([\w.-]+)", text, re.MULTILINE)
        out = [{**o, "hooks": hooks[:30]} for o in out]
    return list({o["tool"]: o for o in reversed(out)}.values())[::-1]      # each tool once
