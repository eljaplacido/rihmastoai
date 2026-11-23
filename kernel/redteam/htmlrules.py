"""The HTML rules, for pages and for the templates and components that hold HTML (Vue, Svelte, Jinja...).

- RT-HTML-SRI: a script from another origin with no integrity hash: a `<script src>` (or a
  `<link rel="modulepreload">`) whose address a browser loads from elsewhere, read as a browser
  reads it (entities decoded, white space and backslashes as a browser treats them: `\\\\cdn` is
  `//cdn`), with no `integrity="sha256-|sha384-|sha512-..."` attribute of its own (not
  `data-integrity`, not empty); and a module script that imports from another origin
  (`import x from "https://..."`), which no integrity attribute can cover.
- The JavaScript rules run on every inline `<script>` at its own lines, on every inline event
  handler (`onload="..."`, entities decoded), and on template bindings that write HTML: Vue's
  `v-html`, Angular's `[innerHTML]` and Svelte's `{@html ...}` (RT-JS-DOMXSS when the value is not a
  literal).
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable

Hit = tuple[str, int]
JsCheck = Callable[[str, int], list[Hit]]
SafeHtml = Callable[[str], bool]

_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.I | re.S)
_TAG = re.compile(r"""<([A-Za-z][\w:.-]*)((?:[^>"']|"[^"]*"|'[^']*')*)>""", re.S)
_ATTR = re.compile(r"""([^\s=/>"']+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?""")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_INTEGRITY = re.compile(r"\s*(?:sha(?:256|384|512)-[A-Za-z0-9+/_=-]+\s*)+")
_EXTERNAL = re.compile(r"(?i)\A(?:[a-z][a-z0-9+.-]*:)?//")
_IMPORT_URL = re.compile(r"""\bimport\b[^;'"`]*?\(?\s*(["'`])((?:https?:)?//[^"'`]+)\1""")
_SVELTE_HTML = re.compile(r"\{@html\s+([^}]*)\}")
_HTML_BINDINGS = ("v-html", "[innerhtml]", "v-bind:innerhtml", ":innerhtml")
_JS_TYPES = ("", "text/javascript", "application/javascript", "module")


def blank(text: str) -> str:
    return "".join("\n" if c == "\n" else " " for c in text)


def _line(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def attributes(attrs: str) -> list[tuple[str, str, int]]:
    """(name in lower case, value with entities decoded, where the attribute starts) for a tag's attributes."""
    out = []
    for m in _ATTR.finditer(attrs):
        value = next((g for g in m.groups()[1:] if g is not None), "")
        out.append((m.group(1).lower(), html.unescape(value), m.start()))
    return out


def external(url: str) -> bool:
    """Whether a browser loads ``url`` from another origin: `https://`, `//`, and the forms a browser
    reads as those (leading white space, tabs and new lines inside, backslashes for slashes)."""
    cleaned = re.sub(r"[\t\n\r]", "", url).strip().replace("\\", "/")
    return bool(_EXTERNAL.match(cleaned))


def _sri_missing(attrs: list[tuple[str, str, int]]) -> bool:
    values = {name: value for name, value, _ in attrs}
    return external(values.get("src", "")) and not _INTEGRITY.fullmatch(values.get("integrity", "") or "x")


def _scripts(text: str, check_js: JsCheck) -> list[Hit]:
    hits: list[Hit] = []
    for m in _SCRIPT.finditer(text):
        attrs = attributes(m.group(1))
        names = {name: value for name, value, _ in attrs}
        if "src" in names:
            if _sri_missing(attrs):
                hits.append(("RT-HTML-SRI", _line(text, m.start())))
            continue
        if names.get("type", "").lower() not in _JS_TYPES:
            continue
        body, first = m.group(2), _line(text, m.start(2))
        hits.extend(check_js(body, first - 1))
        hits += [("RT-HTML-SRI", first + body.count("\n", 0, i.start())) for i in _IMPORT_URL.finditer(body)]
    return hits


def _attribute_hits(name: str, value: str, line: int, check_js: JsCheck, safe_html: SafeHtml) -> list[Hit]:
    """An inline event handler's code, or a binding that writes HTML, judged by the JavaScript rules."""
    if not value:
        return []
    if name.startswith("on") and len(name) > 2:
        return [(rid, line) for rid, _ in check_js(value, 0)]
    return [("RT-JS-DOMXSS", line)] if name in _HTML_BINDINGS and not safe_html(value) else []


def _preload_missing(tag: str, attrs: list[tuple[str, str, int]]) -> bool:
    """A `<link rel="modulepreload">` from another origin with no integrity."""
    if tag != "link" or not any(n == "rel" and "modulepreload" in v.lower() for n, v, _ in attrs):
        return False
    return _sri_missing([("src" if n == "href" else n, v, a) for n, v, a in attrs])


def _tags(text: str, check_js: JsCheck, safe_html: SafeHtml) -> list[Hit]:
    """Inline handlers, HTML bindings and module preloads, in every tag outside scripts."""
    hits: list[Hit] = []
    for m in _TAG.finditer(text):
        tag, attrs = m.group(1).lower(), attributes(m.group(2) or "")
        for name, value, at in attrs:
            hits += _attribute_hits(name, value, _line(text, m.start(2) + at), check_js, safe_html)
        if _preload_missing(tag, attrs):
            hits.append(("RT-HTML-SRI", _line(text, m.start())))
    return hits


def check_html_with(source: str, check_js: JsCheck, safe_html: SafeHtml) -> list[Hit]:
    """RT-HTML-SRI and the JavaScript rules in one page or template."""
    text = _HTML_COMMENT.sub(lambda m: blank(m.group(0)), source)
    hits = _scripts(text, check_js)
    outside = _SCRIPT.sub(lambda m: blank(m.group(0)), text)
    hits += _tags(outside, check_js, safe_html)
    hits += [("RT-JS-DOMXSS", _line(outside, m.start())) for m in _SVELTE_HTML.finditer(outside)
             if not safe_html(m.group(1))]
    return sorted(set(hits), key=lambda h: (h[1], h[0]))
