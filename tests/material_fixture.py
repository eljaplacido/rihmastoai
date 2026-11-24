"""The material fixtures (FR-MAT1): a real project folder of every format, built for each test.

The text files are committed under tests/fixtures/material/project. The binary formats are built here with
zipfile and zlib, so no binary blob is committed: a Word brief, a slide deck (its second slide first in the
deck's own order), a workbook, OpenDocument text, slides and a sheet, a PDF whose text is in a Flate stream,
a scanned PDF with no text layer, and a picture. The secret-looking files are built here too, so no
credential-shaped string is committed: an environment file, an SSH key, a credentials file, a note whose
text holds a token, and code holding a cloud key.
"""

from __future__ import annotations

import shutil
import zipfile
import zlib
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "material" / "project"
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
REL = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
ODF = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
       'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
       'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
       'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"')
# Built at run time, never committed: they look like credentials on purpose.
AWS_KEY = "AKIA" + "J7Q2XK4M9TB3W8RZ"
TOKEN = "x8Hq2Lm9" + "Zp4Rt7Vw1Ks6Yn3B"


def _zip(path: Path, parts: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            z.writestr(name, text)


def docx(path: Path, paragraphs: list[tuple[str, str]]) -> None:
    """A Word document: (style, text) paragraphs; a style such as Heading1 makes a heading."""
    body = "".join((f'<w:p><w:pPr><w:pStyle w:val="{s}"/></w:pPr>' if s else "<w:p>")
                   + f"<w:r><w:t>{t}</w:t></w:r></w:p>" for s, t in paragraphs)
    _zip(path, {"word/document.xml": f"<w:document {W}><w:body>{body}</w:body></w:document>"})


def pptx(path: Path, slides: list[list[str]], order: list[int]) -> None:
    """A deck: each slide's paragraphs, shown in ``order`` (slide numbers from 1) by presentation.xml."""
    parts = {}
    for n, lines in enumerate(slides, 1):
        paras = "".join(f"<a:p><a:r><a:t>{x}</a:t></a:r></a:p>" for x in lines)
        parts[f"ppt/slides/slide{n}.xml"] = (f"<p:sld {A} {P}><p:cSld><p:spTree><p:sp><p:txBody>{paras}"
                                              "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>")
    ids = "".join(f'<p:sldId id="{255 + n}" r:id="rId{n}"/>' for n in order)
    parts["ppt/presentation.xml"] = f"<p:presentation {P} {R}><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>"
    rels = "".join(f'<Relationship Id="rId{n}" Target="slides/slide{n}.xml"/>' for n in range(1, len(slides) + 1))
    parts["ppt/_rels/presentation.xml.rels"] = f"<Relationships {REL}>{rels}</Relationships>"
    _zip(path, parts)


def xlsx(path: Path, sheet: str, rows: list[list[str | int]]) -> None:
    """A workbook of one sheet: text cells through the shared strings, numbers as values."""
    shared: list[str] = []
    xml_rows = []
    for r, row in enumerate(rows, 1):
        cells = []
        for value in row:
            if isinstance(value, int):
                cells.append(f"<c><v>{value}</v></c>")
            else:
                shared.append(value)
                cells.append(f'<c t="s"><v>{len(shared) - 1}</v></c>')
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    _zip(path, {
        "xl/workbook.xml": f'<workbook {S} {R}><sheets><sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets>'
                           "</workbook>",
        "xl/_rels/workbook.xml.rels": f'<Relationships {REL}><Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                                      "</Relationships>",
        "xl/sharedStrings.xml": f"<sst {S}>" + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>",
        "xl/worksheets/sheet1.xml": f"<worksheet {S}><sheetData>{''.join(xml_rows)}</sheetData></worksheet>"})


def odf(path: Path, body: str) -> None:
    _zip(path, {"content.xml": f"<office:document-content {ODF}><office:body>{body}</office:body>"
                               "</office:document-content>"})


def pdf(path: Path, content: bytes, *, flate: bool = True, image: bool = False) -> None:
    """A one-page PDF whose content stream is Flate-compressed (or an image stream, for a scan)."""
    if image:
        data, head = b"\xff\xd8\xff\xe0fakejpeg", b"/Filter /DCTDecode /Subtype /Image"
    else:
        data, head = (zlib.compress(content), b"/Filter /FlateDecode") if flate else (content, b"")
    stream = b"4 0 obj\n<< /Length %d %s >>\nstream\n" % (len(data), head) + data + b"\nendstream\nendobj\n"
    doc = (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
           b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
           b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>\nendobj\n" + stream + b"%%EOF\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(doc)


def build(dest: Path, *, secrets: bool = True) -> Path:
    """The whole fixture folder at ``dest``: the committed text files, the binary formats and the secrets."""
    shutil.copytree(FIXTURE, dest)
    docx(dest / "brief.docx", [("Heading1", "Lobby visitor register"),
                               ("", "Visitors sign in on a tablet; the host is told at once."),
                               ("Heading2", "Users"), ("", "Receptionists and hosts at the main office.")])
    pptx(dest / "slides" / "pilot-deck.pptx", [["Why a register"], ["Pilot plan", "Tampere first, then Oulu"]],
         order=[2, 1])
    xlsx(dest / "data" / "budget.xlsx", "Budget", [["Item", "Cost"], ["Tablets", 800], ["Licences", 1200]])
    odf(dest / "notes" / "workshop.odt", '<office:text><text:h text:outline-level="1">Workshop</text:h>'
        "<text:p>Hosts asked for a daily summary.</text:p></office:text>")
    odf(dest / "slides" / "kickoff.odp", "<office:presentation><draw:page><text:p>Kickoff</text:p></draw:page>"
        "<draw:page><text:p>Scope and team</text:p></draw:page></office:presentation>")
    odf(dest / "data" / "rooms.ods", '<office:spreadsheet><table:table table:name="Rooms"><table:table-row>'
        "<table:table-cell><text:p>Room</text:p></table:table-cell><table:table-cell><text:p>Seats</text:p>"
        "</table:table-cell></table:table-row><table:table-row><table:table-cell><text:p>Lobby</text:p>"
        "</table:table-cell><table:table-cell><text:p>6</text:p></table:table-cell></table:table-row>"
        "</table:table></office:spreadsheet>")
    pdf(dest / "docs" / "security-spec.pdf",
        b"BT /F1 12 Tf 72 720 Td (Visitor data stays in the EU \\(Finland\\)) Tj 0 -14 Td "
        b"[(Badges ) -120 (are printed at the desk)] TJ ET")
    pdf(dest / "docs" / "floorplan-scan.pdf", b"", image=True)
    (dest / "assets").mkdir()
    (dest / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)))
    if secrets:
        (dest / ".env").write_text("DATABASE_URL=postgres://app@db/register\n", encoding="utf-8")
        (dest / "id_rsa").write_text("not opened\n", encoding="utf-8")
        (dest / "config" / "credentials.yaml").write_text("user: app\n", encoding="utf-8")
        (dest / "notes" / "handy.txt").write_text(f"Remember the token for the mail relay:\napi_token = \"{TOKEN}\"\n",
                                                  encoding="utf-8")
        (dest / "src" / "cloud.py").write_text(f'KEY_ID = "{AWS_KEY}"\n', encoding="utf-8")
    return dest
