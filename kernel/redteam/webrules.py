"""The JavaScript rules: careful regular expressions over text (`jslex.py`), not a parser.

- RT-JS-DOMXSS: HTML written into the page from a value that is not a literal: `innerHTML` or
  `outerHTML` assigned (`.x =`, `["x"] =`, `+=`, `||=`, `??=`, a destructuring target),
  `insertAdjacentHTML`, `document.write`, `Object.assign(el, {innerHTML: ...})`, jQuery's
  `.html(...)` and React's `{__html: ...}`. A value wholly passed through an HTML sanitiser is not
  reported, nor a template literal whose every placeholder is such a call. A sanitiser is named so:
  `sanitize`, `sanitise`, `purify` (`DOMPurify.sanitize`), or an escape that says it is for HTML
  (`escapeHtml`, `html_escape`, `_.escape`, `he.escape`, a bare `escape` or `esc`). `escapeRegExp`,
  `CSS.escape`, `noEscape`, `unescape` and `describe` are not. Data written in the script is not
  reported either: inside a `forEach` or `map` callback over a `const` array literal that holds
  only strings (no placeholder), numbers, booleans and objects and arrays of those, the element
  (`t.label`, `t`) and the index (`(i + 1)`) are data, as long as the script uses the array nowhere
  else and the callback never assigns, redeclares, destructures into, passes on or rebinds them. A
  value built through a local variable (`let h = ...; h += t.label; el.innerHTML = h`) is not
  followed, and stays reported;
- RT-JS-EVAL: `eval(...)`, `window.eval(...)`, `(0, eval)(...)`, `Function(...)` with or without
  `new`, and `setTimeout` / `setInterval` given a string built in code, each with an argument that is
  not a literal. A method named `eval` being defined (`eval(node) { ... }`) is not a call.
"""

from __future__ import annotations

import re

from kernel.redteam.htmlrules import check_html_with
from kernel.redteam.jslex import (
    line_of,
    normalise,
    scan_to,
    split_args,
    split_plus,
    statement_end,
    strip_comments,
)

Hit = tuple[str, int]

_OPERATOR = r"\s*(?:\+|\|\||&&|\?\?)?=(?!=)"
_ASSIGN_SINK = re.compile(r"\.\s*(?:innerHTML|outerHTML)" + _OPERATOR)
_BRACKET_SINK = re.compile(r"""\[\s*(["'`])(?:innerHTML|outerHTML)\1\s*\]""" + _OPERATOR)
_DESTRUCTURED = re.compile(r"\[[^\[\]=;]*\.\s*(?:innerHTML|outerHTML)\s*(?:,[^\[\];=]*)?\]\s*=(?!=)")
_CALL_SINK = re.compile(r"(?:\.insertAdjacentHTML|\bdocument\.write(?:ln)?|\.\s*html)\s*\(")
_PROPERTY_SINK = re.compile(r"(?<![\w$.])(?:__html|innerHTML|outerHTML)\s*:")
_ASSIGN_CALL = re.compile(r"\bObject\s*\.\s*assign\s*\(")
_EVAL = re.compile(r"(?<![\w$.])(?:(?:window|globalThis|self|top|parent|frames)\s*\.\s*)?eval\s*\(|"
                   r"\(\s*0\s*,\s*eval\s*\)\s*\(|(?<![\w$.])(?:new\s+)?Function\s*\(")
_TIMER = re.compile(r"(?<![\w$.])(?:window\s*\.\s*)?set(?:Timeout|Interval)\s*\(")
_STRING = re.compile(r"""\A(?:'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"|`(?:\\.|\$(?!\{)|[^`$\\])*`|-?\d+(?:\.\d+)?)\Z""",
                     re.S)
_CALLEE = re.compile(r"\A([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(")
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_SANITISING = frozenset({"sanitize", "sanitise", "sanitizer", "sanitiser", "purify"})
_ESCAPING = frozenset({"escape", "esc", "encode"})
_HTML_WORDS = frozenset({"html", "xml", "attr", "attribute", "entities", "entity"})
_NOT_HTML = frozenset({"no", "not", "un", "reg", "exp", "regex", "regexp", "css", "url", "uri", "sql", "shell", "json",
                       "selector", "identifier", "string", "js", "path"})
_ESCAPE_LIBRARIES = frozenset({"_", "lodash", "he", "validator", "html", "escaper"})
_PLACEHOLDER = re.compile(r"\$\{")
_CONST_ARRAY = re.compile(r"\bconst\s+([A-Za-z_$][\w$]*)\s*=\s*\[")
_DATA_TOKEN = re.compile(r"[A-Za-z_$][\w$]*\s*:|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?")
_DATA_SHAPE = re.compile(r"[\[\]{},:\s]*\Z")
_EACH = re.compile(r"\s*\.\s*(?:forEach|map)\s*\(\s*(?:function\s*)?\(?\s*([A-Za-z_$][\w$]*)\s*"
                   r"(?:,\s*([A-Za-z_$][\w$]*)\s*)?\)?\s*(?:=>)?\s*\{")
_DATA_PART = re.compile(r"\A\(?\s*([A-Za-z_$][\w$]*)(?:\s*\.\s*[A-Za-z_$][\w$]*|\s*\[\s*\d+\s*\])*"
                        r"(?:\s*[-+*]\s*\d+)?\s*\)?\Z")
# What may follow a data name inside its callback. Not `)` or `,`: `function (t)` would rebind it, and
# `f(t)` cannot be told apart from that by a regular expression, so both end its standing as data.
_DATA_FOLLOWERS = frozenset(".[+-*;]}'\"`")
_DECLARED = re.compile(r"\b(?:let|const|var)\s*\Z")
_IDENTIFIER = re.compile(r"(?<![\w$.])[A-Za-z_$][\w$]*")


def sanitiser_name(callee: str) -> bool:
    """Whether a function's name says it makes text safe for HTML (see the module's docstring)."""
    parts = callee.split(".")
    words = [w.lower() for w in _WORD.findall(parts[-1])]
    receiver = parts[-2].lower() if len(parts) > 1 else ""
    if not words or receiver == "css" or any(w in _NOT_HTML for w in words):
        return False
    if any(w in _SANITISING for w in words):
        return True
    if not any(w in _ESCAPING for w in words):
        return False
    return any(w in _HTML_WORDS for w in words) or receiver in _ESCAPE_LIBRARIES or words in (["escape"], ["esc"])


def _sanitised(expr: str) -> bool:
    """The whole expression is one call to a sanitiser: `escapeHtml(x)`, not `escapeHtml(x) + y`."""
    m = _CALLEE.match(expr)
    return m is not None and sanitiser_name(m.group(1)) and scan_to(expr, m.end(), ")") == len(expr) - 1


def _from_data(part: str, data: frozenset[str]) -> bool:
    """`t.label`, `t`, `(i + 1)`: a name that holds only data written in the script (see `data_spans`)."""
    m = _DATA_PART.match(part)
    return m is not None and m.group(1) in data


def _template_safe(expr: str, data: frozenset[str] = frozenset()) -> bool:
    if not (expr.startswith("`") and expr.endswith("`")):
        return False
    holes = []
    for m in _PLACEHOLDER.finditer(expr):
        end = scan_to(expr, m.end(), "}")
        holes.append(expr[m.end():end].strip())
    return all(_sanitised(h) or _from_data(h, data) for h in holes)


def safe_html(expr: str, data: frozenset[str] = frozenset()) -> bool:
    """A value fixed in the source, wholly passed through a sanitiser, or built from ``data``: names
    that hold only data written in the script."""
    expr = expr.strip().rstrip(";").strip()
    parts = [p.strip() for p in split_plus(expr)]
    return all(_STRING.match(p) or _sanitised(p) or _template_safe(p, data) or _from_data(p, data)
               for p in parts if p)


def _data_literal(original: str, blanked: str) -> bool:
    """An array literal's body holds data only: strings with no placeholder, numbers, true, false,
    null, and arrays and objects of those (an identifier in a value position is not data)."""
    if "${" in original:
        return False
    rest = _DATA_TOKEN.sub(" ", re.sub(r"[\"'`]", " ", blanked))
    return bool(_DATA_SHAPE.match(rest))


def _stays_data(text: str, code: str, name: str) -> bool:
    """Whether ``name`` keeps the element it was given throughout a callback's body (``text``, and
    ``code`` with its strings blanked): never assigned or destructured into, its properties never
    assigned (looked for in template placeholders too), never declared again, passed on or a
    parameter again."""
    word = re.escape(name)
    if re.search(rf"(?<![\w$.]){word}(?:\s*\.\s*[\w$]+|\s*\[[^\]]*\])*\s*(?:[-+*/%]?=(?!=)|\+\+|--)", text):
        return False
    if re.search(rf"[\[{{][^\[\]{{}};]*(?<![\w$.]){word}(?![\w$])[^\[\]{{}};]*[\]}}]\s*=(?!=)", code):
        return False
    for use in re.finditer(rf"(?<![\w$.]){word}(?![\w$])\s*(.?)", code):
        if use.group(1) not in _DATA_FOLLOWERS or _DECLARED.search(code, max(0, use.start() - 16), use.start()):
            return False
    return True


def _placeholder_names(text: str) -> set[str]:
    """The names used inside template placeholders (`${...}`): code that blanking strings hides."""
    out: set[str] = set()
    for m in _PLACEHOLDER.finditer(text):
        out.update(_IDENTIFIER.findall(text[m.end():scan_to(text, m.end(), "}")]))
    return out


def _data_arrays(text: str, code: str) -> dict[str, list[int]]:
    """Each name a `const` array literal of data is declared under, with where its declarations stand."""
    arrays: dict[str, list[int]] = {}
    for m in _CONST_ARRAY.finditer(code):
        end = scan_to(code, m.end(), "]")
        if _data_literal(text[m.end():end], code[m.end():end]):
            arrays.setdefault(m.group(1), []).append(m.start(1))
    return arrays


def _array_uses(text: str, code: str) -> dict[str, list[int]]:
    """Each data array declared once and never named in a template placeholder, with where each use
    of its name (its declaration aside) ends."""
    arrays = _data_arrays(text, code)
    hidden = _placeholder_names(text)
    uses: dict[str, list[int]] = {name: [] for name, where in arrays.items() if len(where) == 1 and name not in hidden}
    for u in _IDENTIFIER.finditer(code):
        if u.group(0) in uses and u.start() not in arrays[u.group(0)]:
            uses[u.group(0)].append(u.end())
    return uses


def data_spans(text: str, code: str) -> list[tuple[int, int, frozenset[str]]]:
    """(start, end, names): inside each span, the names hold only data written in the script (see the
    module's docstring). ``code`` is ``text`` with string contents blanked, at the same offsets."""
    out = []
    for ends in _array_uses(text, code).values():
        loops = [loop for loop in (_EACH.match(code, end) for end in ends) if loop is not None]
        if not loops or len(loops) < len(ends):
            continue
        for loop in loops:
            start, close = loop.end(), scan_to(code, loop.end(), "}")
            names = frozenset(n for n in loop.groups() if n and _stays_data(text[start:close], code[start:close], n))
            out.append((start, close, names))
    return out


def _data_at(spans: list[tuple[int, int, frozenset[str]]], index: int) -> frozenset[str]:
    return frozenset().union(*(names for start, end, names in spans if start <= index < end))


def _property_value(text: str, start: int) -> str:
    """The value of an object property that starts at ``start``: up to its `,` or the object's `}`."""
    return text[start:scan_to(text, start, ",}")]


Spans = list[tuple[int, int, frozenset[str]]]


def _call_values(name: str, args: list[str]) -> list[str]:
    """The arguments of an HTML-writing call that become HTML."""
    if "insertAdjacentHTML" in name:
        return args[1:2]
    return args if "write" in name else args[:1]   # jQuery's .html(value); .html() with no argument reads


def _unsafe_at(text: str, code: str, spans: Spans) -> list[int]:
    """Where HTML is written from a value that is not safe: assignments, calls and properties."""
    out = []
    assigned = [*_ASSIGN_SINK.finditer(code), *(m for m in _BRACKET_SINK.finditer(text) if code[m.start()] == "[")]
    out += [m.start() for m in assigned
            if not safe_html(text[m.end():statement_end(text, m.end())], _data_at(spans, m.start()))]
    out += [m.start() for m in _DESTRUCTURED.finditer(code)]
    for m in _CALL_SINK.finditer(code):
        values = _call_values(m.group(0), split_args(text[m.end():]))
        if any(not safe_html(v, _data_at(spans, m.start())) for v in values):
            out.append(m.start())
    calls = [(a.end(), scan_to(code, a.end(), ")")) for a in _ASSIGN_CALL.finditer(code)]
    for m in _PROPERTY_SINK.finditer(code):
        judged = m.group(0).startswith("__html") or any(start < m.start() < end for start, end in calls)
        if judged and not safe_html(_property_value(text, m.end()), _data_at(spans, m.start())):
            out.append(m.start())
    return out


def _dom_hits(text: str, code: str, offset: int) -> set[Hit]:
    return {("RT-JS-DOMXSS", line_of(text, at, offset)) for at in _unsafe_at(text, code, data_spans(text, code))}


def _definition(text: str, end: int) -> bool:
    """Whether the parenthesis that opens at ``end - 1`` belongs to a method being defined (`eval(x) {`)."""
    close = scan_to(text, end, ")")
    return text[close + 1:close + 40].lstrip().startswith("{")


def _eval_hits(text: str, code: str, offset: int) -> set[Hit]:
    hits: set[Hit] = set()
    for m in _EVAL.finditer(code):
        if not _definition(text, m.end()) and any(not _STRING.match(a) for a in split_args(text[m.end():])):
            hits.add(("RT-JS-EVAL", line_of(text, m.start(), offset)))
    for m in _TIMER.finditer(code):
        args = split_args(text[m.end():])
        first = args[0] if args else ""
        built = re.search(r"[\"'`]", first) and not _STRING.match(first) and "=>" not in first and \
            not first.startswith(("function", "async"))
        if built:
            hits.add(("RT-JS-EVAL", line_of(text, m.start(), offset)))
    return hits


def check_javascript(source: str, offset: int = 0) -> list[Hit]:
    """Every (rule id, line) the JavaScript rules find; ``offset`` is added to each line."""
    source = normalise(source)
    text = strip_comments(source)
    code = strip_comments(source, strings=True)  # the same offsets, string contents blanked
    hits = _dom_hits(text, code, offset) | _eval_hits(text, code, offset)
    return sorted(hits, key=lambda h: (h[1], h[0]))


def check_html(source: str) -> list[Hit]:
    """RT-HTML-SRI for each script from another origin with no integrity, and the JavaScript rules on
    inline scripts, inline handlers and template bindings (`htmlrules.py`)."""
    return check_html_with(source, check_javascript, safe_html)
