"""Zip archives in a person's folder, looked into without extracting them (docs/guides/inputs.md, Archives).

An experiment's ``results.zip`` holds its metrics, logs and reports. The scan (kernel/material.py) lists the
archive's entries and reads the readable text inside (csv, json, md, txt, html, logs and the other formats
kernel/material_read.py reads) by the same rules as a file in the folder: excluded, secret-looking, binary,
housekeeping and code entries are listed or skipped with their reason, documents go into the budget like any
other. Nothing is ever written to disk: each entry is read through the archive, at most ``MAX_MEMBER`` bytes
of it.

A zip bomb is refused: an archive whose entries would inflate past ``MAX_EXPANDED`` in all, or more than
``MAX_RATIO`` times their compressed size, is listed and not opened; an entry over the ratio is listed and
not read; and no archive gives more than ``MAX_TOTAL`` bytes of text, whatever its headers say, since every
read is capped by the bytes actually inflated. An archive inside an archive is listed, never opened, and an
encrypted entry is listed, never read.
"""

from __future__ import annotations

import zipfile
from pathlib import PurePosixPath
from typing import Any

MAX_ARCHIVE = 4 * 1024 ** 3          # an archive larger than this is listed: its directory is not read
MAX_ENTRIES = 2000                   # entries looked at; more are counted
MAX_MEMBER = 2 * 1024 * 1024         # an entry's bytes read at most; a larger entry is listed
MAX_TOTAL = 24 * 1024 * 1024         # the bytes read from one archive in all
MAX_EXPANDED = 8 * 1024 ** 3         # every entry inflated, by the archive's own directory
MAX_RATIO = 200                      # inflated size over compressed size, per entry and in all
SEP = "!/"                           # an entry's path: <archive>!/<entry>
ARCHIVES = (".zip", ".jar", ".war", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar")


def is_archive(rel: str) -> bool:
    return PurePosixPath(rel.lower()).suffix == ".zip"


def _shown(name: str) -> str:
    """An entry's name as text: control characters replaced, a leading slash or drive dropped."""
    clean = "".join(ch if ch.isprintable() else "?" for ch in name.replace("\\", "/"))
    if len(clean) > 1 and clean[1] == ":":
        clean = clean[2:]
    return clean.lstrip("/") or "?"


def bomb(infos: list[zipfile.ZipInfo]) -> str | None:
    """Why an archive is refused as a zip bomb, or None."""
    expanded = sum(i.file_size for i in infos)
    packed = sum(i.compress_size for i in infos) or 1
    if expanded > MAX_EXPANDED:
        return f"refused: its entries would inflate to {expanded / 1024 ** 3:.1f} GB (a zip bomb, or too large)"
    if expanded > 1024 * 1024 and expanded / packed > MAX_RATIO:
        return f"refused: its entries inflate {expanded // packed}x their packed size (a zip bomb)"
    return None


def look(scan: Any, rel: str, size: int) -> dict[str, Any]:
    """The archive's own row; its entries' rows are added to ``scan`` (their text to its documents)."""
    from kernel import material as m

    if size > MAX_ARCHIVE:
        return m._row(rel, size, "listed", f"an archive too large to open ({size / 1024 ** 3:.1f} GB)")
    try:
        with scan.tree.open(rel) as fh, zipfile.ZipFile(fh) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            why = bomb(infos)
            if why:
                return m._row(rel, size, "listed", f"an archive, not opened: {why}", archive_entries=len(infos))
            budget = {"left": MAX_TOTAL, "read": 0}
            for info in infos[:MAX_ENTRIES]:
                scan.rows.append(_entry(scan, zf, info, rel, budget))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, EOFError, ValueError) as exc:
        return m._row(rel, size, "listed", f"an archive that could not be opened ({type(exc).__name__})")
    more = max(0, len(infos) - MAX_ENTRIES)
    tail = f"; {more:,} more entries were not looked at" if more else ""
    return m._row(rel, size, "listed", f"an archive of {len(infos):,} entries: its readable text is read from inside "
                                       f"it, never extracted to disk{tail}", archive_entries=len(infos))


def _entry(scan: Any, zf: zipfile.ZipFile, info: zipfile.ZipInfo, archive: str, budget: dict[str, int]
           ) -> dict[str, Any]:
    """One entry's row, by the folder's rules; a readable document's text goes to the scan's documents."""
    from kernel import material as m
    from kernel import material_kinds as mk

    rel = f"{archive}{SEP}{_shown(info.filename)}"
    size, mark = info.file_size, {"archive": archive}
    ext = PurePosixPath(rel.lower()).suffix
    decided = m._by_rule(rel, size, scan.patterns, nested=True)
    if decided is not None:
        return decided | mark
    if ext in ARCHIVES:
        return m._row(rel, size, "listed", "an archive inside an archive: not opened", **mark)
    if info.flag_bits & 0x1:
        return m._row(rel, size, "listed", "encrypted: not read", **mark)
    if mk.language(PurePosixPath(rel).name) or mk.MANIFESTS.fullmatch(PurePosixPath(rel).name):
        return m._row(rel, size, "listed", "code inside an archive: listed, not read", **mark)
    if size > MAX_MEMBER:
        return m._row(rel, size, "listed", f"too large to read inside the archive ({size / 1048576:.1f} MB)", **mark)
    if info.compress_size and size > 64 * 1024 and size / info.compress_size > MAX_RATIO:
        return m._row(rel, size, "listed", "refused: it inflates far beyond its packed size (a zip bomb)", **mark)
    if size > budget["left"]:
        return m._row(rel, size, "listed", "not read: the archive's read limit is used up", **mark)
    with zf.open(info) as fh:                  # never more than the bytes it really inflates to, capped
        data = fh.read(min(MAX_MEMBER, budget["left"]) + 1)
    if len(data) > min(MAX_MEMBER, budget["left"]):
        return m._row(rel, size, "listed", "refused: it inflates beyond what its header says", **mark)
    budget["left"] -= len(data)
    row: dict[str, Any] = scan._document(rel, size, data)
    row.update(mark)                           # the same row the budget fills in later
    return row
