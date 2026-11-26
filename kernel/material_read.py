"""Text out of the files a person's folder holds, by format, standard library only (docs/guides/inputs.md).

Each reader takes the file's bytes and returns an `Extracted`: the text, how much of the file it stands for
("read", "partly read", "not read") and a note that says why when it is not the whole file. Nothing here
decides what is sent anywhere: kernel/material.py classifies, checks for secrets and keeps to the budget.

- `.md .markdown .rst .txt` and other plain text: the text as it is;
- `.html .htm`: scripts and styles dropped, entities decoded, headings kept as `#` lines;
- `.docx`: the paragraphs of word/document.xml, headings kept; `.pptx`: each slide's text in slide order,
  under "Slide N"; `.xlsx`: each sheet's name, its header row and a few rows (shared strings resolved);
- `.odt .odp .ods`: content.xml, the same way;
- `.csv .tsv`: the header and a few rows, with the row count;
- `.json .yaml .yml .toml`: the structure and its keys, and a short sample;
- `.pdf`: the strings of the text operators (Tj, TJ, ' and ") of uncompressed or Flate streams: always
  "partly read"; a PDF with no text layer (a scan) is "not read: no text layer";
- a log: its first and last lines.
"""

from __future__ import annotations

import csv
import io
import json
import re
import tomllib
import zipfile
import zlib
from html.parser import HTMLParser
from typing import Any, NamedTuple
from xml.etree import ElementTree as ET

ROWS = 5                      # the rows of a table after its header
LOG_LINES = 15                # a log's first and last lines
SAMPLE_CHARS = 600            # a structured file's sample
MAX_MEMBER = 50 * 1024 * 1024  # an office file's part, uncompressed: more is a zip bomb, not a document
MAX_INFLATE = 16 * 1024 * 1024
PARTLY_PDF = ("text taken from the PDF's text operators: its layout, tables, and fonts with their own "
              "encodings may be lost")
TEXT_FORMATS = (".md", ".markdown", ".rst", ".txt", ".text", ".adoc", ".org")


class Extracted(NamedTuple):
    text: str
    state: str          # read, partly read, not read
    note: str = ""


def decode(data: bytes) -> str:
    """Bytes as text: UTF-8 (with or without its mark), else UTF-16 by its mark, else Latin-1."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _lines(text: str) -> list[str]:
    return [re.sub(r"[ \t ]+", " ", x).strip() for x in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]


def _tidy(text: str) -> str:
    """Runs of blank lines as one, spaces collapsed, ends trimmed."""
    return re.sub(r"\n{3,}", "\n\n", "\n".join(_lines(text))).strip()


# -- markup ----------------------------------------------------------------------------------------------

class _Html(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "head"}
    BLOCK = {"p", "div", "li", "br", "tr", "section", "article", "header", "footer", "table", "ul", "ol",
             "blockquote", "pre", "dd", "dt", "title", "main", "nav", "aside", "form"}
    SVG_TEXT = {"text", "title", "desc"}     # a diagram's labels: its shapes and paths are not text

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.title = ""
        self.in_title = False
        self.svg = 0
        self.svg_text = 0

    def _svg_tag(self, tag: str, start: bool) -> bool:
        """Inside an inline SVG only its text, titles and descriptions are read, one label to a line."""
        if tag == "svg":
            self.svg = self.svg + 1 if start else max(0, self.svg - 1)
            return True
        if not self.svg:
            return False
        if tag in self.SVG_TEXT:
            self.svg_text = self.svg_text + 1 if start else max(0, self.svg_text - 1)
            if not start:
                self.out.append("\n")
        return True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._svg_tag(tag, True):
            return
        if tag == "title":
            self.in_title = True
        elif tag in self.SKIP:
            self.skip += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in self.BLOCK:
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if self._svg_tag(tag, False):
            return
        if tag == "title":
            self.in_title = False
        elif tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif re.fullmatch(r"h[1-6]", tag) or tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if self.svg:
            if self.svg_text and not self.skip:
                self.out.append(data)
        elif self.in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data)


def html_text(data: bytes) -> Extracted:
    parser = _Html()
    parser.feed(decode(data))
    parser.close()
    body = _tidy("".join(parser.out))
    title = parser.title.strip()
    return Extracted((f"Title: {title}\n\n" if title and title not in body[:200] else "") + body, "read")


def _xml(z: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_MEMBER:
        raise ValueError(f"{name} is {info.file_size:,} bytes uncompressed: too large to read")
    return ET.fromstring(z.read(info))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(el: ET.Element, name: str) -> str:
    """An attribute by its local name, in any namespace."""
    return next((v for k, v in el.attrib.items() if _local(k) == name), "")


def _all(el: ET.Element, tag: str) -> list[ET.Element]:
    """Every element under ``el`` (itself too) with the local name ``tag``, in any namespace."""
    return [x for x in el.iter() if _local(x.tag) == tag]


def _text_of(el: ET.Element, tag: str = "t") -> str:
    return "".join(t.text or "" for t in _all(el, tag))


def docx_text(z: zipfile.ZipFile) -> Extracted:
    root = _xml(z, "word/document.xml")
    if root is None:
        return Extracted("", "not read", "no word/document.xml: not a Word document")
    out = []
    for p in _all(root, "p"):
        text = _text_of(p).strip()
        if not text:
            continue
        style = next((_attr(s, "val") for s in _all(p, "pStyle")), "")
        level = re.search(r"(?i)(?:heading|otsikko)\s*(\d)", style)
        out.append(("#" * int(level.group(1)) + " " if level else "# " if style.lower() == "title" else "") + text)
    return Extracted("\n".join(out), "read")


def _rels(z: zipfile.ZipFile, name: str, base: str) -> dict[str, str]:
    root = _xml(z, name)
    out = {}
    for rel in [] if root is None else _all(root, "Relationship"):
        target = _attr(rel, "Target")
        out[_attr(rel, "Id")] = target.lstrip("/") if target.startswith("/") else base + target
    return out


def _rid(el: ET.Element) -> str:
    """An element's relationship id (r:id), never its own plain id."""
    return next((v for k, v in el.attrib.items() if k.startswith("{") and _local(k) == "id"), "")


def _slide_names(z: zipfile.ZipFile) -> list[str]:
    """The slides in the deck's own order (presentation.xml), else by their numbers."""
    names = [n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
    pres = _xml(z, "ppt/presentation.xml")
    rels = _rels(z, "ppt/_rels/presentation.xml.rels", "ppt/")
    ordered = [rels.get(_rid(s), "") for s in ([] if pres is None else _all(pres, "sldId"))]
    ordered = [n for n in ordered if n in names]
    rest = sorted((n for n in names if n not in ordered), key=lambda n: int(re.sub(r"\D", "", n)))
    return ordered + rest


def pptx_text(z: zipfile.ZipFile) -> Extracted:
    out = []
    for n, name in enumerate(_slide_names(z), 1):
        root = _xml(z, name)
        lines = [] if root is None else [_text_of(p).strip() for p in _all(root, "p")]
        out.append(f"Slide {n}\n" + "\n".join(x for x in lines if x))
    return Extracted("\n\n".join(out), "read" if out else "not read", "" if out else "no slides")


def _cell(c: ET.Element, shared: list[str]) -> str:
    kind = c.get("t", "")
    if kind == "inlineStr":
        return _text_of(c)
    v = next(iter(_all(c, "v")), None)
    value = (v.text or "") if v is not None else ""
    if kind == "s" and value.isdigit():
        return shared[int(value)] if int(value) < len(shared) else ""
    return value


def _table(name: str, rows: list[list[str]]) -> str:
    rows = [r for r in rows if any(x.strip() for x in r)]
    shown = rows[:ROWS + 1]
    head = f"Sheet {name}: {len(rows)} rows" if name else f"{len(rows)} rows"
    body = "\n".join(" | ".join(x.strip() for x in r) for r in shown)
    more = f"\n(the first {len(shown) - 1} rows after the header of {len(rows) - 1})" if len(rows) > len(shown) else ""
    return f"{head}\n{body}{more}"


def xlsx_text(z: zipfile.ZipFile) -> Extracted:
    strings = _xml(z, "xl/sharedStrings.xml")
    shared = [] if strings is None else [_text_of(si) for si in _all(strings, "si")]
    book = _xml(z, "xl/workbook.xml")
    if book is None:
        return Extracted("", "not read", "no xl/workbook.xml: not an Excel workbook")
    rels = _rels(z, "xl/_rels/workbook.xml.rels", "xl/")
    out = []
    for sheet in _all(book, "sheet"):
        root = _xml(z, rels.get(_rid(sheet), ""))
        rows = [] if root is None else [[_cell(c, shared) for c in _all(r, "c")] for r in _all(root, "row")]
        out.append(_table(sheet.get("name", "?"), rows))
    return Extracted("\n\n".join(out), "summarised", "each sheet's header and its first rows")


def _plain(el: ET.Element) -> str:
    return "".join(el.itertext()).strip()


def _ods(root: ET.Element) -> Extracted:
    tables = [_table(_attr(t, "name"), [[_plain(c) for c in _all(r, "table-cell")] for r in _all(t, "table-row")])
              for t in _all(root, "table")]
    return Extracted("\n\n".join(tables), "summarised", "each sheet's header and its first rows")


def _odp(root: ET.Element) -> Extracted:
    pages = [f"Slide {n}\n" + "\n".join(x for x in (_plain(p) for p in _all(page, "p")) if x)
             for n, page in enumerate(_all(root, "page"), 1)]
    return Extracted("\n\n".join(pages), "read")


def odf_text(z: zipfile.ZipFile, ext: str) -> Extracted:
    root = _xml(z, "content.xml")
    if root is None:
        return Extracted("", "not read", "no content.xml: not an OpenDocument file")
    if ext in (".ods", ".odp"):
        return _ods(root) if ext == ".ods" else _odp(root)
    out = []
    for el in root.iter():
        name = _local(el.tag)
        if name in ("h", "p"):
            text = "".join(el.itertext()).strip()
            if text:
                out.append(("#" * int(_attr(el, "outline-level") or 1) + " " if name == "h" else "") + text)
    return Extracted("\n".join(out), "read")


def office_text(data: bytes, ext: str) -> Extracted:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if ext == ".docx":
                return docx_text(z)
            if ext == ".pptx":
                return pptx_text(z)
            if ext == ".xlsx":
                return xlsx_text(z)
            return odf_text(z, ext)
    except (zipfile.BadZipFile, ET.ParseError, ValueError, KeyError, OSError) as exc:
        return Extracted("", "not read", f"the file could not be opened as {ext}: {type(exc).__name__}")


# -- tables and structured data --------------------------------------------------------------------------

def table_text(data: bytes, ext: str) -> Extracted:
    text = decode(data)
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter="\t" if ext == ".tsv" else ","))
    except csv.Error as exc:
        return Extracted(_head(text, 20), "summarised", f"not read as a table ({exc}): its first lines")
    return Extracted(_table("", rows), "summarised", "the header and the first rows")


def _shape(value: Any, depth: int = 0) -> list[str]:
    pad = "  " * depth
    if isinstance(value, dict):
        out = [f"{pad}an object with {len(value)} keys: " + ", ".join(map(str, list(value)[:25]))]
        if depth < 1:
            for k, v in list(value.items())[:12]:
                if isinstance(v, (dict, list)) and v:
                    out += [f"{pad}- {k}:"] + _shape(v, depth + 1)
        return out
    if isinstance(value, list):
        out = [f"{pad}a list of {len(value)} items"]
        return out + (_shape(value[0], depth + 1) if value and isinstance(value[0], (dict, list)) and depth < 1 else [])
    return [f"{pad}{type(value).__name__}"]


def structured_text(data: bytes, ext: str) -> Extracted:
    text = decode(data)
    sample = text[:SAMPLE_CHARS].rstrip() + ("\n..." if len(text) > SAMPLE_CHARS else "")
    try:
        if ext == ".json":
            shape = _shape(json.loads(text))
        elif ext == ".toml":
            shape = _shape(tomllib.loads(text))
        else:
            keys = re.findall(r"(?m)^([A-Za-z_][\w.-]*)\s*:", text)
            shape = [f"top-level keys: {', '.join(dict.fromkeys(keys)) or 'none found'}"]
    except (ValueError, RecursionError) as exc:      # TOMLDecodeError is a ValueError; nesting can break a parser
        shape = [f"not parsed ({type(exc).__name__})"]
    return Extracted("Structure:\n" + "\n".join(shape) + "\n\nSample:\n" + sample, "summarised",
                     "its structure and keys, and a short sample")


def _head(text: str, n: int) -> str:
    return "\n".join(text.splitlines()[:n])


def log_text(data: bytes) -> Extracted:
    lines = decode(data).splitlines()
    if len(lines) <= 2 * LOG_LINES:
        return Extracted("\n".join(lines), "summarised", "a log: all of its lines, it is short")
    gap = len(lines) - 2 * LOG_LINES
    text = "\n".join(lines[:LOG_LINES] + [f"... ({gap:,} lines not read) ..."] + lines[-LOG_LINES:])
    return Extracted(text, "summarised", f"a log: its first and last {LOG_LINES} of {len(lines):,} lines")


# -- PDF -------------------------------------------------------------------------------------------------

_STREAM = re.compile(rb"(?<!end)stream\r?\n")
_PDF_TOKEN = re.compile(rb"\((?:\\.|[^\\)])*\)\s*(?:Tj|'|\")|\[(?:\\.|[^\]\\])*\]\s*TJ|<[0-9A-Fa-f\s]*>\s*Tj"
                        rb"|(?<![A-Za-z])(?:T\*|Td|TD|ET)(?![A-Za-z])", re.S)
_PDF_STRING = re.compile(rb"\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]*>", re.S)
_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}


def _pdf_string(raw: bytes) -> str:
    if raw.startswith(b"<"):
        digits = re.sub(rb"\s", b"", raw[1:-1])
        return bytes.fromhex((digits + b"0" * (len(digits) % 2)).decode("ascii")).decode("latin-1")
    body, out, i = raw[1:-1], bytearray(), 0
    while i < len(body):
        c = body[i:i + 1]
        if c == b"\\" and i + 1 < len(body):
            octal = re.match(rb"[0-7]{1,3}", body[i + 1:i + 4])
            if octal:
                out.append(int(octal.group(), 8) & 0xFF)
                i += 1 + len(octal.group())
                continue
            out += _ESCAPES.get(body[i + 1:i + 2], b"")
            i += 2
            continue
        out += c
        i += 1
    return out.decode("latin-1")


def _streams(data: bytes) -> list[bytes]:
    out, total = [], 0
    for m in _STREAM.finditer(data):
        end = data.find(b"endstream", m.end())
        if end < 0:
            continue
        head = data[max(0, m.start() - 2000):m.start()]          # the stream's dictionary, after its "obj"
        head = head[head.rfind(b"obj") + 3:] if b"obj" in head else head
        raw = data[m.end():end]
        if b"/FlateDecode" in head:
            try:
                raw = zlib.decompressobj().decompress(raw, MAX_INFLATE)
            except zlib.error:
                continue
        elif b"/Filter" in head:
            continue                       # images and other encodings hold no text the kernel reads
        total += len(raw)
        if total > 4 * MAX_INFLATE:
            break
        out.append(raw)
    return out


def _pdf_ops(stream: bytes) -> str:
    out: list[str] = []
    for m in _PDF_TOKEN.finditer(stream):
        token = m.group()
        if token.rstrip().endswith((b"Tj", b"TJ", b"'", b'"')):
            if token.endswith((b"'", b'"')):
                out.append("\n")
            out.append("".join(_pdf_string(s) for s in _PDF_STRING.findall(token)))
        else:
            out.append("\n")
    return "".join(out)


def pdf_text(data: bytes) -> Extracted:
    if b"/Encrypt" in data[-4096:] or re.search(rb"/Encrypt\s", data[:65536]):
        return Extracted("", "not read", "an encrypted PDF")
    text = _tidy("\n".join(_pdf_ops(s) for s in _streams(data)))
    printable = sum(ch.isalnum() for ch in text)
    if printable < 20:
        return Extracted("", "not read", "no text layer: a scanned PDF, or fonts the kernel cannot decode")
    return Extracted(text, "partly read", PARTLY_PDF)


# -- by format -------------------------------------------------------------------------------------------

OFFICE = (".docx", ".pptx", ".xlsx", ".odt", ".odp", ".ods")
TABLES = (".csv", ".tsv")
STRUCTURED = (".json", ".yaml", ".yml", ".toml")
HTML = (".html", ".htm", ".xhtml")
READABLE = (*TEXT_FORMATS, *OFFICE, *TABLES, *STRUCTURED, *HTML, ".pdf", ".log")


def extract(data: bytes, ext: str, *, log: bool = False) -> Extracted:
    """The text of a file's bytes by its format (its extension, lower case, with the dot)."""
    if log or ext == ".log":
        return log_text(data)
    if ext in OFFICE:
        return office_text(data, ext)
    if ext in TABLES:
        return table_text(data, ext)
    if ext in STRUCTURED:
        return structured_text(data, ext)
    if ext in HTML:
        return html_text(data)
    if ext == ".pdf":
        return pdf_text(data)
    return Extracted(decode(data).replace("\r\n", "\n").strip(), "read")
