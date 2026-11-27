"""The commands the console offers as buttons (FR-CON1): what is known about a project's workspace.

Found by rule, never guessed, and never run by being found:
- the commands a person stated for the project (test, build, lint and any other name), kept in its console
  settings (kernel/console.py);
- the commands the project's own instructions state (AGENTS.md, CLAUDE.md and the rest), as adoption or
  attaching recorded them (kernel/ide.py), each with its file and line;
- the test command adoption's rules detect (``kernel.adopt.detect_tests``);
- ``package.json`` scripts, as ``npm run <name>``;
- Makefile targets, as ``make <target>``;
- the ``run:`` steps of the GitHub Actions workflows and the ``script:`` lines of ``.gitlab-ci.yml``, each a
  line of its own. A step of several lines, or one with a pipe or ``&&``, runs through the shell.

Each offer is ``{"label", "line", "source", "shell"}``: what the button says, the command line it runs, where
it was found, and whether it needs the shell.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any

MAX_OFFERS = 40
MAX_FILE = 256 * 1024
_TARGET = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]{0,60})\s*:(?!=)")
_RUN = re.compile(r"^(\s*)-?\s*run:\s*(.*)$")
_SCRIPT = re.compile(r"^(\s*)script:\s*$")


def needs_shell(line: str) -> bool:
    """Whether a command line uses the shell's own words outside quotes: a pipe, ``&&``, ``;``, a redirect,
    a substitution, or several lines."""
    if "\n" in line.strip() or "$(" in line or "`" in line:
        return True
    lexer = shlex.shlex(line, posix=True, punctuation_chars="|&;<>")
    lexer.whitespace_split = True
    lexer.escape = "" if os.name == "nt" else "\\"
    lexer.commenters = ""
    try:
        return any(tok and set(tok) <= set("|&;<>") for tok in lexer)
    except ValueError:              # an unclosed quote: the split says so, plainly
        return False


def _read(path: Path) -> str:
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_FILE:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# A command written as a template, with words to fill in ("--lane <lane> <gates>", "{name}", "..."): offered to
# fill the command line for editing, never run on one click, and its angle brackets are not shell redirects.
TEMPLATE = re.compile(r"<[A-Za-z][\w .:/|-]{0,40}>|\{[A-Za-z_][\w-]{0,40}\}|(?<![\w.])\.\.\.(?![\w.])")


def _offer(label: str, line: str, source: str) -> dict[str, Any]:
    template = bool(TEMPLATE.search(line))
    return {"label": label, "line": line, "source": source,
            "shell": needs_shell(TEMPLATE.sub("x", line)), "template": template}


def short_label(command: str, kind: str | None = None) -> str:
    """A button's words for a stated command: its script's name ("lane_gates.py") or its first words, and what
    kind of command it is, never a command cut in the middle."""
    words = command.split()
    script = next((Path(w.strip("\"'")).name for w in words
                   if Path(w.strip("\"'")).suffix in (".py", ".ps1", ".sh", ".js", ".ts", ".bat", ".cmd")), None)
    short = script or " ".join(words[:3])
    short = short if len(short) <= 40 else short[:39] + "…"
    return f"{kind.capitalize()}: {short}" if kind else short


def npm_scripts(root: Path) -> list[dict[str, Any]]:
    try:
        doc = json.loads(_read(root / "package.json") or "{}")
    except (ValueError, RecursionError):
        return []
    scripts = doc.get("scripts") if isinstance(doc, dict) else None
    if not isinstance(scripts, dict):
        return []
    return [_offer(f"npm run {name}", f"npm run {name}", "package.json scripts")
            for name, body in scripts.items() if isinstance(name, str) and isinstance(body, str)
            and re.fullmatch(r"[A-Za-z0-9:_.-]{1,60}", name)]


def make_targets(root: Path) -> list[dict[str, Any]]:
    text = _read(root / "Makefile") or _read(root / "makefile")
    found: list[str] = []
    for line in text.splitlines():
        m = _TARGET.match(line)
        if m and not m.group(1).startswith(".") and m.group(1) not in found:
            found.append(m.group(1))
    return [_offer(f"make {t}", f"make {t}", "Makefile") for t in found]


def _block(lines: list[str], start: int, indent: int) -> tuple[str, int]:
    """A YAML block scalar (``run: |``) from ``start``: its lines, dedented, and where it ends."""
    body: list[str] = []
    i = start
    while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent):
        body.append(lines[i].strip())
        i += 1
    return "\n".join(b for b in body if b), i


def _workflow_runs(text: str) -> list[str]:
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = _RUN.match(lines[i])
        i += 1
        if not m:
            continue
        value = m.group(2).strip()
        if value in ("|", ">", "|-", ">-"):
            value, i = _block(lines, i, len(m.group(1)))
        value = value.strip().strip("'\"") if "\n" not in value else value
        if value and "${{" not in value:
            out.append(value)
    return out


def ci_steps(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    folder = root / ".github" / "workflows"
    files = sorted(folder.glob("*.y*ml")) if folder.is_dir() else []
    for wf in files[:10]:
        for line in _workflow_runs(_read(wf)):
            label = line.splitlines()[0][:60] + (" ..." if "\n" in line else "")
            out.append(_offer(label, line, f"CI step in .github/workflows/{wf.name}"))
    lines = _read(root / ".gitlab-ci.yml").splitlines()
    for i, line in enumerate(lines):
        m = _SCRIPT.match(line)
        if not m:
            continue
        for item in lines[i + 1:]:
            if not item.strip().startswith("- "):
                break
            step = item.strip()[2:].strip().strip("'\"")
            out.append(_offer(step[:60], step, "CI step in .gitlab-ci.yml"))
    return out


def detected_tests(root: Path) -> list[dict[str, Any]]:
    from kernel.adopt import detect_tests
    from kernel.attach import git

    listed = git(root, "ls-files", "-z", check=False) if (root / ".git").exists() else ""
    files = [f for f in listed.split("\0") if f][:20000]
    if not files:
        try:
            files = [str(p.relative_to(root)).replace("\\", "/") for p in root.glob("*") if p.is_file()]
            files += [str(p.relative_to(root)).replace("\\", "/") for p in root.glob("tests/*") if p.is_file()]
        except OSError:
            return []
    return [_offer(tests_label(t["runner"]), " ".join(t["command"]), f"detected by rule: {t['basis']}")
            for t in detect_tests(root, files)]


def tests_label(runner: str | None) -> str:
    """A detected suite's button: what it does and with which runner. Never a label that reads as another
    command ("pytest tests" for ``python -m pytest -q``)."""
    return f"Run the tests ({runner})" if runner else "Run the tests"


def stated(settings: dict[str, Any]) -> list[dict[str, Any]]:
    commands = settings.get("commands") or {}
    return [_offer(name, line, "stated for the project") for name, line in commands.items()
            if isinstance(name, str) and isinstance(line, str) and line.strip()]


def instructed(context: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The commands the project's own instructions state (its AGENTS.md, CLAUDE.md and the rest; kernel/ide.py
    records them when a project is adopted or attached): how its team builds, tests and runs it."""
    return [_offer(short_label(s["command"], s.get("kind")), s["command"],
                   f"stated in {s['file']} (line {s['line']}), {s['kind']}")
            for s in (context or {}).get("stated") or []
            if isinstance(s, dict) and isinstance(s.get("command"), str) and s["command"].strip()]


_READ_FIRST = re.compile(r"^(?:[^/]+|\.github/workflows/[^/]+\.ya?ml|tests?/[^/]+)$")
MAX_READ = 200_000


def from_repository(repo: Path) -> list[dict[str, Any]]:
    """The commands found by rule in a repository's last commit, read straight from ``repo`` (its bare clone)
    before the console's working copy is made at its first run: a first visit offers them too."""
    import tempfile

    from kernel.adopt import detect_tests
    from kernel.attach import git

    if not repo.is_dir():
        return []
    try:
        listed = [f for f in git(repo, "ls-tree", "-r", "--name-only", "-z", "HEAD", check=False).split("\0") if f]
    except (OSError, RuntimeError):
        return []
    found: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="rihma-offers-") as tmp:
        root = Path(tmp)
        for rel in [f for f in listed if _READ_FIRST.match(f)][:300]:
            try:
                body = git(repo, "show", f"HEAD:{rel}", check=False)
            except (OSError, RuntimeError):
                continue
            if len(body) <= MAX_READ:
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(body, encoding="utf-8")
        found += [_offer(tests_label(t["runner"]), " ".join(t["command"]), f"detected by rule: {t['basis']}")
                  for t in detect_tests(root, listed[:20000])]
        for read in (npm_scripts, make_targets, ci_steps):
            found += read(root)
    return found


def offers(root: Path | None, settings: dict[str, Any], context: dict[str, Any] | None = None,
           repo: Path | None = None) -> list[dict[str, Any]]:
    """Every command the console offers for a workspace at ``root`` (None: what was stated, and what the
    repository ``repo`` holds by rule when it is given)."""
    found = stated(settings) + instructed(context)
    if root is not None and root.is_dir():
        for read in (detected_tests, npm_scripts, make_targets, ci_steps):
            found += read(root)
    elif repo is not None:
        found += from_repository(repo)
    seen: set[str] = set()
    out = []
    for offer in found:
        if offer["line"] not in seen:
            seen.add(offer["line"])
            out.append(offer)
    return out[:MAX_OFFERS]
