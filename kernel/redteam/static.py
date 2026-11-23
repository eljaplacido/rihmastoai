"""The static layer: read a product's tree and run the rule catalogue over it. Nothing is executed.

Which layer reads a file is decided by its name (and, for a script with no extension, its first line):

| Layer | Files |
|---|---|
| python | `*.py`, `*.pyw`, a script with no extension whose first line names python; read with `ast` |
| javascript | `*.js`, `*.mjs`, `*.cjs`, `*.jsx`, `*.ts`, `*.tsx`, `*.mts`, `*.cts`, inline scripts |
| html | pages (`*.html`, `*.htm`) and what holds HTML: `*.vue`, `*.svelte`, Jinja, Nunjucks, ... |
| dockerfile | `Dockerfile`, `Dockerfile.*`, `Dockerfile-*`, `*.dockerfile`, `Containerfile`, any case |
| actions | `.github/workflows/*.yml` and `*.yaml` by the file's real folder, `action.yml` |
| secrets | every file: text up to 1 MB by content and name; images, fonts and media by name |

Each layer then says what it measured (`report.Coverage`): a file that does not parse, is too
large to read, or is binary but not media (an archive, a database: it could hold a secret the scan
cannot read) is a gap, named in the reason, and makes the layer `partial`. A layer with no files of
its kind is `not measured` and not applicable.

What the walk leaves out (links, junctions and files outside the target; tool, dependency and
virtual-environment folders; paths a person excluded) is listed in the report's notes
(`collect.py`).

Optional scanners (bandit, semgrep, trivy) are never needed. Each is listed with "not measured":
absent from PATH, or present but not run here (its own SARIF can be ingested like any scanner's).
"""

from __future__ import annotations

import ast
import os
import shutil
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from kernel.redteam import TOOL_VERSION
from kernel.redteam.collect import SourceFile, Walk, read_file
from kernel.redteam.configrules import (
    check_actions,
    check_dockerfile,
    entry_points,
    entry_scripts,
    is_entry_point,
    module_paths,
    script_entry_points,
)
from kernel.redteam.pyrules import check_python
from kernel.redteam.report import Canary, Coverage, Finding, Report
from kernel.redteam.rules import LAYERS, RULES
from kernel.redteam.secretscan import check_file, secret_file, test_path
from kernel.redteam.webrules import check_html, check_javascript

Hit = tuple[str, int]

# Binary files that do not carry credentials as text: judged by name, and that is all they need. Any other
# binary file (an archive, a database, an executable) could hold a secret the scan cannot read: a gap.
MEDIA = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".avif", ".woff", ".woff2", ".ttf", ".otf",
         ".eot", ".mp3", ".mp4", ".webm", ".ogg", ".wav")
JS_SUFFIXES = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts")
HTML_SUFFIXES = (".html", ".htm", ".xhtml", ".vue", ".svelte", ".jinja", ".jinja2", ".j2", ".njk", ".hbs", ".ejs",
                 ".twig")
EXTERNAL = ("bandit", "semgrep", "trivy")
NOUNS = {"python": ("Python file", "Python files"), "javascript": ("JavaScript file", "JavaScript files"),
         "html": ("HTML page", "HTML pages"), "dockerfile": ("Dockerfile", "Dockerfiles"),
         "actions": ("GitHub Actions workflow", "GitHub Actions workflows"), "secrets": ("file", "files")}
LIMITS = (
    "python: RT-PY-PATH is a dataflow heuristic inside one function; a path that crosses a function call is "
    "not followed.",
    "python: a call that passes **kwargs may carry a timeout; a string built across functions is followed only "
    "through a module function that returns it.",
    "javascript: careful regular expressions over comment-stripped text, not a parser; a sink reached through an "
    "alias is not seen. Server-side JavaScript (Node) has no injection rule: exec, SQL and file sinks there are "
    "not checked.",
    "actions: event data is looked for in run: scripts; the script: body of a github-script step is not read.",
    "secrets: text files up to 1 MB are read line by line; a credential split over several string literals is "
    "not joined; images, fonts and media by name only; any other binary file is a gap.",
)


def _dockerfile(lower: str, suffix: str) -> bool:
    if suffix in (".md", ".txt", ".rst"):
        return False
    return lower in ("dockerfile", "containerfile") or lower.endswith(".dockerfile") or \
        lower.startswith(("dockerfile.", "dockerfile-", "dockerfile_", "containerfile."))


def layers_of(rel: str, where: str = "", text: str | None = None) -> list[str]:
    """The code and configuration layers that read the file at ``rel`` (every file is also a secret's).
    ``where`` is its real path (a workflow is one by its folder, wherever the scan starts) and
    ``text`` its content (a script with no extension is Python when its first line says so)."""
    p = PurePosixPath(rel)
    lower, suffix = p.name.lower(), p.suffix.lower()
    out = []
    script = not suffix and text is not None and text.startswith("#!") and "python" in text.split("\n", 1)[0]
    if suffix in (".py", ".pyw") or script:
        out.append("python")
    if suffix in JS_SUFFIXES:
        out.append("javascript")
    if suffix in HTML_SUFFIXES:
        out.append("html")
    if _dockerfile(lower, suffix):
        out.append("dockerfile")
    parts = PurePosixPath(where or rel).parts
    workflow = len(parts) >= 3 and parts[-3:-1] == (".github", "workflows") and suffix in (".yml", ".yaml")
    if workflow or lower in ("action.yml", "action.yaml"):
        out.append("actions")
    return out


def collect(paths: Sequence[str | Path], root: str | Path | None = None,
            exclude: Sequence[str] = ()) -> tuple[Walk, list[SourceFile]]:
    """The walk (what it left out, and why) and every file under ``paths``."""
    targets = [Path(p) for p in paths]
    missing = [str(t) for t in targets if not t.exists()]
    if missing:
        raise FileNotFoundError(f"nothing to scan at {', '.join(missing)}")
    if root is not None:
        base = Path(root)
    elif len(targets) == 1:
        base = targets[0] if targets[0].is_dir() else targets[0].parent
    else:
        base = Path(os.path.commonpath([str(t.resolve()) for t in targets]))
    walk = Walk(base, exclude)
    files = [read_file(p, walk.rel(p)) for t in targets for p in walk.files(t)]
    return walk, files


@dataclass
class _Tally:
    files: dict[str, int] = field(default_factory=lambda: dict.fromkeys(LAYERS, 0))
    gaps: dict[str, list[str]] = field(default_factory=lambda: {layer: [] for layer in LAYERS})
    binary: int = 0

    def coverage(self, layer: str) -> Coverage:
        files, gaps, (one, many) = self.files[layer], self.gaps[layer], NOUNS[layer]
        counted = f"{files} {one if files == 1 else many}"
        extra = f"; {self.binary} of them media, judged by name only" if layer == "secrets" and self.binary else ""
        if files == 0:
            return Coverage(layer, "not measured", f"no {many} in the tree", 0, [], applicable=False)
        if not gaps:
            return Coverage(layer, "measured", f"{counted} read and checked{extra}", files)
        if len(gaps) >= files:
            return Coverage(layer, "not measured", f"none of {counted} could be checked: {gaps[0]}", files, gaps)
        more = f" and {len(gaps) - 3} more" if len(gaps) > 3 else ""
        return Coverage(layer, "partial", f"{files - len(gaps)} of {counted} checked; not checked: "
                        f"{'; '.join(gaps[:3])}{more}{extra}", files, gaps)


Entries = list[tuple[str, set[str]]]  # (a Dockerfile's folder, the entry points its CMD and ENTRYPOINT run)


def _folder(rel: str) -> str:
    """The folder of the file at ``rel``, "" for the scan's root."""
    parent = PurePosixPath(rel).parent.as_posix()
    return "" if parent == "." else parent


def _find(point: str, folder: str, texts: dict[str, str]) -> str | None:
    """The file in the tree an entry point names, relative to the scan's root."""
    return next((rel for rel in texts if is_entry_point(rel, {point}, folder)), None)


def _imports(text: str, inside: str) -> set[str]:
    """The module files an entry point imports (one level), as paths relative to the image's folder."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return set()
    package = PurePosixPath(inside).parent.parts
    out: set[str] = set()
    for node in ast.walk(tree):
        modules = [a.name for a in node.names] if isinstance(node, ast.Import) else []
        if isinstance(node, ast.ImportFrom):
            base = list(package[: len(package) - node.level + 1]) if node.level else []
            head = ".".join([*base, *([node.module] if node.module else [])])
            modules = [head, *(f"{head}.{a.name}" for a in node.names)] if head else []
        for m in modules:
            out |= module_paths(m) | {m.replace(".", "/") + "/__init__.py"}
    return out


def _entries(files: list[SourceFile]) -> Entries:
    """Each Dockerfile's entry points: what its CMD and ENTRYPOINT run, what a shell script it runs runs,
    and what those modules import."""
    texts = {f.rel: f.text for f in files if f.text is not None}
    out: Entries = []
    for f in files:
        if f.text is None or "dockerfile" not in layers_of(f.rel, f.where):
            continue
        folder, points = _folder(f.rel), entry_points(f.text)
        for script in entry_scripts(f.text):
            found = _find(script, folder, texts)
            points |= script_entry_points(texts[found]) if found else set()
        for point in list(points):
            found = _find(point, folder, texts)
            inside = found[len(folder) + 1:] if found and folder else found
            points |= _imports(texts[found], inside) if found and inside else set()
        out.append((folder, points))
    return out


def _entry_point(rel: str, entries: Entries) -> bool:
    """A container's entry point, where binding every interface is expected; a test suite's file never
    ships, so it binds what its test needs (a test that a server refuses `0.0.0.0` names it)."""
    return test_path(rel) or any(is_entry_point(rel, points, folder) for folder, points in entries)


def _code_hits(layer: str, f: SourceFile, entries: Entries) -> list[Hit]:
    """The hits of one code or configuration layer. Raises SyntaxError for Python that does not parse."""
    text = f.text or ""
    checks: dict[str, Callable[[], list[Hit]]] = {
        "python": lambda: check_python(ast.parse(text, filename=f.rel), entry_point=_entry_point(f.rel, entries),
                                       filename=f.rel),
        "javascript": lambda: check_javascript(text),
        "html": lambda: check_html(text),
        "dockerfile": lambda: check_dockerfile(text),
        "actions": lambda: check_actions(text),
    }
    return checks[layer]()


class _Scan:
    def __init__(self, entries: Entries) -> None:
        self.entries = entries
        self.tally = _Tally()
        self.findings: list[Finding] = []
        self.canaries: list[Canary] = []

    def add(self, f: SourceFile, hits: Iterable[Hit]) -> None:
        lines = (f.text or "").splitlines()
        for rid, line in hits:
            if rid == "RT-SECRET-FILE":  # its content is the secret: the evidence names the file's kind only
                snippet = f"{f.rel}: {secret_file(f.rel, (f.text or '')[:4096])} (content not shown)"
            else:
                snippet = lines[line - 1] if 0 < line <= len(lines) else f.rel
            self.findings.append(Finding.of(RULES[rid], f.rel, f.line(line), snippet))

    def file(self, f: SourceFile) -> None:
        kinds = layers_of(f.rel, f.where, f.text)
        for layer in (*kinds, "secrets"):
            self.tally.files[layer] += 1
            if f.error:
                self.tally.gaps[layer].append(f.error)
        if f.error:
            return
        hits, canaries = check_file(f.rel, f.text)
        if f.binary:
            media = f.rel.lower().endswith(MEDIA)
            self.tally.binary += media
            for layer in (*kinds, *(() if media or hits else ("secrets",))):
                self.tally.gaps[layer].append(f"{f.rel} is binary, its content not read")
        self.add(f, hits)
        self.canaries += [Canary(f.rel, f.line(line), kind, ev) for line, kind, ev in canaries]
        for layer in ([] if f.binary else kinds):
            self.code(layer, f)

    def code(self, layer: str, f: SourceFile) -> None:
        try:
            self.add(f, _code_hits(layer, f, self.entries))
        except (SyntaxError, ValueError) as exc:
            where = f" at line {exc.lineno}" if isinstance(exc, SyntaxError) and exc.lineno else ""
            self.tally.gaps[layer].append(f"{f.rel} does not parse{where}")
        except RecursionError:  # generated code nested deeper than the checks can walk: a gap, not a crash
            self.tally.gaps[layer].append(f"{f.rel} is nested too deeply to check")


def external_scanners(which: Callable[[str], str | None] = shutil.which) -> list[Coverage]:
    """Optional scanners: never needed, never assumed. Each says "not measured" and why."""
    out = []
    for tool in EXTERNAL:
        reason = (f"{tool} is not on PATH: optional, not needed by these rules" if not which(tool) else
                  f"{tool} is on PATH but not run by this layer; run it with SARIF output and ingest the file")
        out.append(Coverage(f"external:{tool}", "not measured", reason, applicable=False))
    return out


def _target(paths: Sequence[str | Path]) -> str:
    return ", ".join(Path(p).name if Path(p).is_absolute() else Path(p).as_posix() for p in paths)


def scan(paths: Sequence[str | Path], *, root: str | Path | None = None,
         which: Callable[[str], str | None] = shutil.which, exclude: Sequence[str] = ()) -> Report:
    """Scan the files under ``paths`` with every static rule; findings are relative to ``root``.
    ``exclude`` holds glob patterns of paths (relative to ``root``) not to read; they are listed."""
    walk, files = collect(paths, root, exclude)
    run = _Scan(_entries(files))
    for f in files:
        run.file(f)
    for folder in walk.skipped.unlisted:   # a folder the walk could not list: what it holds was not checked
        run.tally.files["secrets"] += 1
        run.tally.gaps["secrets"].append(f"{folder} could not be listed")
    findings = sorted(run.findings, key=lambda x: (x.path, x.line, x.rule))
    coverage = [run.tally.coverage(layer) for layer in LAYERS] + external_scanners(which)
    return Report(_target(paths), findings, coverage, run.canaries, TOOL_VERSION, list(LIMITS) + walk.skipped.notes())
