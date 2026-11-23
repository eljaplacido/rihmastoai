"""The Dockerfile rules, and the container entry points the Python rules allow.

A Dockerfile is read as Docker reads it: the `# escape=` parser directive, line continuations
(comment lines inside them skipped), and heredocs (`RUN <<EOF ... EOF`), whose lines are the
instruction's content and never instructions of their own. `ARG` defaults are substituted into
`FROM` and `USER` (`ARG BASE=python:latest` then `FROM ${BASE}`).

- RT-DOCKER-UNPINNED: a `FROM` image with no tag or the `latest` tag and no `@sha256:` digest. A
  stage built on an earlier stage, `scratch`, or an `ARG` with no default is not judged;
- RT-DOCKER-ADDURL: `ADD` from an `http(s)`, `ftp` or `git` URL without `--checksum`, or a `RUN`
  that pipes a download into a shell or an interpreter (`curl ... | sh`, `sh -c "$(curl ...)"`);
- RT-DOCKER-ROOT: the final stage runs as root: it sets no `USER` (nor does the stage it builds on),
  or its last `USER` is `root` or `0`. An image whose tag says `nonroot` is taken at its word.

Container entry points: the Python modules a Dockerfile's `CMD` or `ENTRYPOINT` runs (`-m app.server`,
`-c "from app.server import main"`, `app/main.py`, `app.main:app` for an ASGI or WSGI server), and
the shell scripts it runs (`./entrypoint.sh`), whose own `python ...` lines name more. Binding all
interfaces is expected there, so RT-PY-BINDALL does not report it. An entry point is a path relative
to the Dockerfile's own folder (the build context), or an absolute path in the image whose tail is
that relative path (`/srv/app/server.py`); a file elsewhere with the same name is not one. In
`-c "from app.server import main"`, `app.server` is the module run, not `main`.
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, replace

Hit = tuple[str, int]

_URL = re.compile(r"(?i)^(?:https?|ftp)://|^git@")
_ESCAPE_DIRECTIVE = re.compile(r"(?i)^#\s*escape\s*=\s*([\\`])\s*$")
_DIRECTIVE = re.compile(r"^#\s*[A-Za-z]+\s*=")
_HEREDOC = re.compile(r"<<(-?)\s*([\"']?)([A-Za-z_]\w*)\2")
_VAR = re.compile(r"\$\{(\w+)(?::?-([^}]*))?\}|\$(\w+)")
_PIPE_SHELL = re.compile(r"(?i)\b(?:curl|wget|fetch)\b[^|;&\n]*\|\s*(?:sudo\s+(?:-\S+\s+)*)?(?:env\s+)?"
                         r"(?:/\S*/)?(?:ba|z|da|k|a)?sh\b|\b(?:curl|wget)\b[^|;&\n]*\|\s*(?:sudo\s+)?"
                         r"(?:/\S*/)?(?:python\d?|perl|ruby|node)\b")
_SUBST_SHELL = re.compile(r"(?i)\b(?:ba|z|da|k)?sh\s+(?:-c\s+)?[\"']?\$\((?:curl|wget)\b|<\(\s*(?:curl|wget)\b")
_FROM_IMPORT = re.compile(r"\A\s*from\s+([A-Za-z_][\w.]*)\s+import\b")
_IMPORT = re.compile(r"\A\s*import\s+(.+)\Z", re.S)
_MODULE_APP = re.compile(r"\A([A-Za-z_][\w.]*):[A-Za-z_]\w*\Z")


@dataclass(frozen=True)
class Instruction:
    line: int
    op: str
    args: str
    body: str = ""     # the lines of its heredocs


def _escape_char(lines: list[str]) -> str:
    """The escape character the parser directives at the top set (`# escape=\\`` on Windows)."""
    for raw in lines:
        s = raw.strip()
        m = _ESCAPE_DIRECTIVE.match(s)
        if m:
            return m.group(1)
        if not _DIRECTIVE.match(s):
            return "\\"
    return "\\"


def _heredocs(args: str, lines: list[str], i: int) -> tuple[str, int]:
    """The content of each heredoc an instruction opens, from line index ``i``; and where it ends."""
    body: list[str] = []
    for m in _HEREDOC.finditer(args):
        term, tabs = m.group(3), m.group(1) == "-"
        while i < len(lines):
            content = lines[i]
            i += 1
            if (content.lstrip("\t") if tabs else content).strip() == term:
                break
            body.append(content)
    return "\n".join(body), i


def instructions(text: str) -> list[Instruction]:
    """A Dockerfile's instructions, each at the line it starts on, continuations joined, heredocs held."""
    lines = text.splitlines()
    escape = _escape_char(lines)
    out: list[Instruction] = []
    buf: list[str] = []
    start, i = 0, 0
    while i < len(lines):
        s = lines[i].strip()
        i += 1
        if not s or s.startswith("#"):
            continue
        if not buf:
            start = i
        if s.endswith(escape):
            buf.append(s[:-1].strip())
            continue
        op, _, args = " ".join([*buf, s]).partition(" ")
        buf = []
        body, i = _heredocs(args, lines, i)
        out.append(Instruction(start, op.upper(), args.strip(), body))
    if buf:
        op, _, args = " ".join(buf).partition(" ")
        out.append(Instruction(start, op.upper(), args.strip()))
    return out


def words(args: str) -> list[str]:
    """An instruction's arguments: the JSON array form, or the shell form split like a shell."""
    if args.startswith("["):
        try:
            value = json.loads(args)
            return [str(v) for v in value] if isinstance(value, list) else []
        except ValueError:
            pass  # not JSON: Docker treats it as the shell form too
    try:
        return shlex.split(args)
    except ValueError:
        return args.split()


def _substitute(text: str, known: dict[str, str]) -> str:
    def one(m: re.Match[str]) -> str:
        name = m.group(1) or m.group(3)
        if name in known and known[name]:
            return known[name]
        return m.group(2) if m.group(2) is not None else m.group(0)
    return _VAR.sub(one, text)


def _resolved(steps: list[Instruction]) -> list[Instruction]:
    """The instructions with `ARG` defaults put into `FROM` (global ones) and `USER` (the stage's)."""
    global_args: dict[str, str] = {}
    stage: dict[str, str] | None = None
    out = []
    for s in steps:
        if s.op == "ARG":
            for word in words(s.args):
                name, eq, value = word.partition("=")
                target = global_args if stage is None else stage
                target[name] = value if eq else global_args.get(name, "")
        elif s.op == "FROM":
            stage = {}
            s = replace(s, args=_substitute(s.args, global_args))
        elif s.op == "USER":
            s = replace(s, args=_substitute(s.args, stage or {}))
        out.append(s)
    return out


def _image(args: str) -> tuple[str, str | None]:
    parts = [w for w in args.split() if not w.startswith("--")]
    image = parts[0] if parts else ""
    alias = parts[2] if len(parts) >= 3 and parts[1].lower() == "as" else None
    return image, alias


def _unpinned(image: str, stages: set[str]) -> bool:
    if not image or "$" in image or image.lower() == "scratch" or image in stages or "@sha256:" in image:
        return False
    name = image.rsplit("/", 1)[-1]
    tag = name.split(":", 1)[1] if ":" in name else None
    return tag is None or tag == "latest"


def _fetches(step: Instruction) -> bool:
    """ADD of a remote URL without a checksum, or RUN that pipes a download into a shell."""
    if step.op == "ADD":
        if "--checksum=" in step.args:
            return False
        found = [w for w in words(step.args) if not w.startswith("--")]
        return any(_URL.search(w) for w in found[:-1])
    if step.op == "RUN":
        script = f"{step.args}\n{step.body}"
        return bool(_PIPE_SHELL.search(script) or _SUBST_SHELL.search(script))
    return False


def _user(args: str) -> str:
    return args.split(":", 1)[0].strip().strip("'\"")


def _runs_as_root(steps: list[Instruction]) -> Hit | None:
    """The final stage's user is root: its last USER (or its base stage's), or none at all."""
    users: dict[str, str | None] = {}
    final: list[Instruction] = []
    alias: str | None = None
    user: str | None = None
    for step in steps:
        if step.op == "FROM":
            if alias:
                users[alias] = user
            image, alias = _image(step.args)
            user = users.get(image) if image in users else ("nonroot" if "nonroot" in image else None)
            final = []
        elif step.op == "USER":
            user = _user(step.args)
        final.append(step)
    if not final:
        return None
    last_user = next((s for s in final[::-1] if s.op == "USER"), None)
    if user is None or user in ("root", "0"):
        return "RT-DOCKER-ROOT", (last_user or final[0]).line
    return None


def check_dockerfile(text: str) -> list[Hit]:
    steps = _resolved(instructions(text))
    hits: list[Hit] = []
    stages: set[str] = set()
    for step in steps:
        if step.op == "FROM":
            image, alias = _image(step.args)
            if _unpinned(image, stages):
                hits.append(("RT-DOCKER-UNPINNED", step.line))
            stages.update([alias] if alias else [])
        elif _fetches(step):
            hits.append(("RT-DOCKER-ADDURL", step.line))
    root = _runs_as_root(steps)
    return sorted([*hits, *([root] if root else [])], key=lambda h: (h[1], h[0]))


# -- container entry points ------------------------------------------------------------------------

def module_paths(module: str) -> set[str]:
    base = module.replace(".", "/")
    return {f"{base}.py", f"{base}/__main__.py"}


def imported_modules(code: str) -> list[str]:
    """The modules a `python -c` snippet imports: `app.server` in `from app.server import main`,
    `a` and `b.c` in `import a, b.c as d`. The names imported from a module are not modules."""
    out: list[str] = []
    for statement in re.split(r"[;\n]", code):
        m = _FROM_IMPORT.match(statement)
        if m:
            out.append(m.group(1))
            continue
        m = _IMPORT.match(statement)
        if m:
            out += [part.split()[0] for part in m.group(1).split(",") if part.split()]
    return out


def entry_words(argv: list[str]) -> set[str]:
    """The Python files one command line runs."""
    out: set[str] = set()
    for i, w in enumerate(argv):
        nxt = argv[i + 1] if i + 1 < len(argv) else ""
        if w == "-m" and nxt:
            out |= module_paths(nxt)
        elif w == "-c" and nxt:  # python -c "<code>", or sh -c "<a command line>"
            for module in imported_modules(nxt):
                out |= module_paths(module)
            out |= entry_words(words(nxt)) if " -m " in f" {nxt} " or ".py" in nxt else set()
        elif w.endswith(".py"):
            while w.startswith("./"):
                w = w[2:]
            out.add(w)
        elif _MODULE_APP.match(w):
            out |= module_paths(w.split(":", 1)[0])
    return out


def _commands(text: str) -> list[list[str]]:
    return [words(step.args) for step in instructions(text) if step.op in ("CMD", "ENTRYPOINT")]


def entry_points(text: str) -> set[str]:
    """Paths of the Python files a Dockerfile's CMD or ENTRYPOINT runs, as the image spells them:
    relative to the working folder, or absolute (with a leading `/`)."""
    out: set[str] = set()
    for argv in _commands(text):
        out |= entry_words(argv)
    return out


def entry_scripts(text: str) -> set[str]:
    """The shell scripts a Dockerfile's CMD or ENTRYPOINT runs (`./entrypoint.sh`)."""
    return {w[2:] if w.startswith("./") else w for argv in _commands(text) for w in argv if w.endswith(".sh")}


def script_entry_points(script: str) -> set[str]:
    """The Python files a shell script runs (`exec python server.py`)."""
    out: set[str] = set()
    for line in script.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            out |= entry_words(words(line))
    return out


def is_entry_point(rel: str, entries: set[str], folder: str = "") -> bool:
    """Whether the file at ``rel`` is one of the ``entries`` of the Dockerfile in ``folder`` ("" for
    the scan's root): the same path relative to that folder, or an absolute path ending in it."""
    if folder and not rel.startswith(folder + "/"):
        return False
    inside = rel[len(folder) + 1:] if folder else rel
    return any(inside == e or (e.startswith("/") and e.endswith("/" + inside)) for e in entries)
