"""The GitHub Actions rules (a workflow under `.github/workflows/`, or an `action.yml`).

- RT-GHA-INJECT: a `run:` script whose `${{ ... }}` expression holds data an outsider controls: the
  event (`github.event.issue.title`, `github.event['issue']['title']`, `toJSON(github.event)`) or
  `github.head_ref`; an `env.NAME` whose value is such data; or a step output set from it
  (`steps.meta.outputs.branch`, written to `$GITHUB_OUTPUT` from such data). The key may be quoted
  or in a flow mapping, and an expression may run over several lines. Fields an outsider cannot
  shape are not reported: numbers, ids, hashes and dates, logins (letters, digits and hyphens),
  the event's action, the base branch and the repository's name.
- RT-GHA-UNPINNED: `uses: owner/repo@ref` where the ref is not a 40-character commit SHA. Local
  actions (`./...`) and `docker://` images with a digest are not judged.
"""

from __future__ import annotations

import re

Hit = tuple[str, int]

_SHA = re.compile(r"[0-9a-f]{40}")
_USES = re.compile(r"""(?:^\s*(?:-\s+)?|[{,]\s*)["']?uses["']?\s*:\s*['"]?([^'"\s#,}]+)""")
_RUN = re.compile(r"""^(\s*)(?:-\s+)?["']?run["']?\s*:\s*(.*)$""")
_FLOW_RUN = re.compile(r"""[{,]\s*["']?run["']?\s*:""")
_EXPR = re.compile(r"\$\{\{(.*?)\}\}", re.S)
_EVENT = re.compile(r"""\bgithub\s*(?:\.\s*event\b|\[\s*['"]event['"]\s*\])((?:\s*\.\s*[\w*-]+|\s*\[\s*['"]?[\w*-]+"""
                    r"""['"]?\s*\])*)|\bgithub\s*(?:\.\s*head_ref|\[\s*['"]head_ref['"]\s*\])""")
_ACCESSOR = re.compile(r"""\[\s*['"]?([\w*-]+)['"]?\s*\]""")
_SAFE_FIELD = re.compile(r"\.(?:number|id|node_id|sha|created_at|updated_at|closed_at|merged|draft|run_id|run_number|"
                         r"run_attempt|size|additions|deletions|commits|changed_files|login|author_association|"
                         r"state|locked|html_url)$")
_SAFE_PATH = frozenset({".action", ".pull_request.base.ref", ".repository.full_name", ".repository.name",
                        ".repository.default_branch", ".pull_request.merged"})
_KEY_VALUE = re.compile(r"""^\s*(?:-\s+)?["']?([A-Za-z_][\w-]*)["']?\s*:\s*(.+)$""")
_ENV_REF = re.compile(r"\benv\s*\.\s*([A-Za-z_][\w-]*)")
_OUTPUT_REF = re.compile(r"\b(?:steps|needs)\s*\.\s*[\w-]+\s*\.\s*outputs\s*\.\s*([\w-]+)")
_SHELL_VAR = re.compile(r"\$\{?([A-Za-z_]\w*)")
_OUTPUT_SET = re.compile(r"""(?:\b([\w-]+)=[^\n]*>>\s*["']?\$\{?GITHUB_OUTPUT|::set-output\s+name=([\w-]+)::)""")


def _unpinned_action(ref: str) -> bool:
    if ref.startswith("./") or (ref.startswith("docker://") and "@sha256:" in ref):
        return False
    if ref.startswith("docker://"):
        return True
    _, _, version = ref.partition("@")
    return not _SHA.fullmatch(version)


def _event_data(expr: str) -> bool:
    """Event data an outsider shapes, in one expression."""
    for m in _EVENT.finditer(expr):
        if m.group(0).replace(" ", "").endswith("head_ref']") or "head_ref" in m.group(0):
            return True
        path = _ACCESSOR.sub(r".\1", m.group(1) or "").replace(" ", "")
        if not path or not (_SAFE_FIELD.search(path) or path in _SAFE_PATH):
            return True
    return False


class _Taint:
    """What a workflow carries from the event: env names and step outputs set from event data."""

    def __init__(self, lines: list[str]) -> None:
        self.env: set[str] = set()
        for line in lines:
            m = _KEY_VALUE.match(line)
            if m and any(_event_data(e) for e in _EXPR.findall(m.group(2))):
                self.env.add(m.group(1))
        self.outputs: set[str] = set()
        for line in lines:
            m = _OUTPUT_SET.search(line)
            if m and (any(self.untrusted(e) for e in _EXPR.findall(line)) or
                      any(v in self.env for v in _SHELL_VAR.findall(line))):
                self.outputs.add(m.group(1) or m.group(2))

    def untrusted(self, expr: str) -> bool:
        return _event_data(expr) or any(n in self.env for n in _ENV_REF.findall(expr)) or \
            any(n in getattr(self, "outputs", set()) for n in _OUTPUT_REF.findall(expr))


def _run_block(lines: list[str], i: int) -> list[int]:
    """The line indexes of the `run:` script that starts at line index ``i`` (a block scalar, or a plain
    value continued on deeper lines); one line for a run in a flow mapping."""
    m = _RUN.match(lines[i])
    if m is None:
        return [i] if _FLOW_RUN.search(lines[i]) else []
    key_column = len(m.group(0)) - len(m.group(0).lstrip()) + (2 if m.group(0).lstrip().startswith("- ") else 0)
    out = [i]
    for j in range(i + 1, len(lines)):  # a value runs while lines are indented past its key
        if lines[j].strip() and len(lines[j]) - len(lines[j].lstrip()) <= key_column:
            break
        out.append(j)
    return out


def check_actions(text: str) -> list[Hit]:
    lines = text.splitlines()
    taint = _Taint(lines)
    hits: set[Hit] = set()
    for i, line in enumerate(lines):
        hits.update(("RT-GHA-UNPINNED", i + 1) for ref in _USES.findall(line) if _unpinned_action(ref))
        block = _run_block(lines, i)
        if not block:
            continue
        script = "\n".join(lines[j] for j in block)
        for m in _EXPR.finditer(script):
            if taint.untrusted(m.group(1)):
                hits.add(("RT-GHA-INJECT", block[script.count("\n", 0, m.start())] + 1))
    return sorted(hits, key=lambda h: (h[1], h[0]))
