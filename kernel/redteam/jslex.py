"""Reading JavaScript as text, carefully enough for the rules: comments, strings, regular expressions.

- A `//` comment ends at any line terminator JavaScript knows (`\\n`, `\\r`, U+2028, U+2029), so
  code after one of them is never blanked as comment.
- A regular expression literal (`/'/g`, a `/` where an expression starts) is skipped as one token:
  a quote or a backtick inside it opens no string, and its body is blanked.
- `\\uXXXX` and `\\u{X}` escapes that spell identifier characters are decoded first, so
  `inner\\u0048TML` is `innerHTML`.

`strip_comments` keeps offsets and line numbers; with ``strings`` it also blanks the contents of
string and template literals (their quotes stay), so a sink's name inside a string is not taken for
code.
"""

from __future__ import annotations

import re

_TERMINATORS = ("\n", "\r", "\u2028", "\u2029")
_CLOSERS = {"(": ")", "[": "]", "{": "}"}
# After these, a `/` starts a regular expression, not a division.
_REGEX_AFTER = frozenset("(,=:[!&|?{};+-*%<>~^")
_REGEX_KEYWORDS = frozenset({"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw",
                             "instanceof", "yield", "await"})
_ESCAPED_ID = re.compile(r"\\u(?:([0-9a-fA-F]{4})|\{([0-9a-fA-F]{1,6})\})")
_WORD_BEFORE = re.compile(r"([A-Za-z_$][\w$]*)\s*\Z")


def decode_escapes(source: str) -> str:
    """The source with identifier characters spelled as `\\u` escapes written out; line breaks are not
    decoded, so lines stay where they are."""
    def one(m: re.Match[str]) -> str:
        ch = chr(int(m.group(1) or m.group(2), 16))
        return ch if ch.isalnum() or ch in "_$" else m.group(0)
    return _ESCAPED_ID.sub(one, source)


def normalise(source: str) -> str:
    """Line ends as `\\n` (CR LF and a lone CR), identifier escapes decoded."""
    return decode_escapes(source.replace("\r\n", "\n").replace("\r", "\n"))


def blank(text: str) -> str:
    return "".join("\n" if c == "\n" else " " for c in text)


def _comment_end(text: str, i: int) -> int:
    if text.startswith("//", i):
        ends = [j for j in (text.find(t, i) for t in _TERMINATORS) if j >= 0]
        return min(ends) if ends else len(text)
    end = text.find("*/", i + 2)
    return len(text) if end < 0 else end + 2


def quote_after(quote: str, c: str) -> str:
    """The string state after character ``c``: a quote closes it, and a line ends a '...' or "..."."""
    if c == quote or (c in "\n\r" and quote != "`"):
        return ""
    return quote


def _regex_start(out: list[str]) -> bool:
    """Whether a `/` here starts a regular expression: nothing before it, an operator or punctuation,
    or a keyword after which an expression comes."""
    before = "".join(out[-40:]).rstrip()
    if not before or before[-1] in _REGEX_AFTER:
        return True
    m = _WORD_BEFORE.search(before)
    return bool(m and m.group(1) in _REGEX_KEYWORDS)


def regex_end(text: str, i: int) -> int:
    """Where a regular expression literal that opens at ``i`` ends (after its flags), or -1 when the line
    ends first (then it was a division)."""
    j, in_class = i + 1, False
    while j < len(text):
        c = text[j]
        if c in _TERMINATORS:
            return -1
        if c == "\\":
            j += 2
            continue
        if c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "/" and not in_class:
            j += 1
            while j < len(text) and (text[j].isalpha()):
                j += 1
            return j
        j += 1
    return -1


def strip_comments(text: str, *, strings: bool = False) -> str:
    """JavaScript with its comments and regular expression bodies blanked; offsets and lines kept."""
    out: list[str] = []
    i, n, quote = 0, len(text), ""
    while i < n:
        c = text[i]
        if quote:
            step = 2 if c == "\\" else 1
            quote = quote_after(quote, c)
            kept = text[i:i + step]
            out.append(blank(kept) if strings and quote else kept)
            i += step
            continue
        if text.startswith("//", i) or text.startswith("/*", i):
            end = _comment_end(text, i)
            out.append(blank(text[i:end]))
            i = end
            continue
        if c == "/" and _regex_start(out):
            end = regex_end(text, i)
            if end > 0:
                out.append("/" + blank(text[i + 1:end]))
                i = end
                continue
        if c in "'\"`":
            quote = c
        out.append(c)
        i += 1
    return "".join(out)


def scan_to(text: str, start: int, stops: str) -> int:
    """The index of the first of ``stops`` at nesting depth 0 from ``start``, skipping strings."""
    depth, quote, i = 0, "", start
    while i < len(text):
        c = text[i]
        if quote:
            i += 2 if c == "\\" else 1
            quote = quote_after(quote, c)
            continue
        if c in "'\"`":
            quote = c
        elif c in _CLOSERS:
            depth += 1
        elif c in ")]}" and depth:
            depth -= 1
        elif c in stops and depth == 0:
            return i
        i += 1
    return len(text)


def split_args(text: str) -> list[str]:
    """The top-level arguments of a call whose text starts just after its `(`."""
    end = scan_to(text, 0, ")")
    body, args, i = text[:end], [], 0
    while i <= len(body):
        j = scan_to(body, i, ",")
        args.append(body[i:j].strip())
        i = j + 1
    return [a for a in args if a]


def split_plus(expr: str) -> list[str]:
    out, i = [], 0
    while i <= len(expr):
        j = scan_to(expr, i, "+")
        out.append(expr[i:j])
        i = j + 1
    return out


_CONTINUES_AFTER = ("+", "(", ",", "?", ":", "||", "&&", "=")
_CONTINUES_BEFORE = ("+", ".", "?", ":", "||", "&&", ")")


def statement_end(text: str, start: int) -> int:
    """Where the expression from ``start`` ends: a `;`, or a line end the expression does not run past."""
    i = start
    while True:
        j = scan_to(text, i, ";\n")
        if j >= len(text) or text[j] == ";":
            return j
        before, after = text[start:j].rstrip(), text[j + 1:].lstrip()
        if before and not before.endswith(_CONTINUES_AFTER) and not after.startswith(_CONTINUES_BEFORE):
            return j
        i = j + 1


def line_of(text: str, index: int, offset: int) -> int:
    return text.count("\n", 0, index) + 1 + offset
