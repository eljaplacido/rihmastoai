"""The categorical palette checks of the dataviz method, in the standard library, for the browser tests.

The same rules as the method's validator (validate_palette.js): OKLCH lightness inside the mode's band, chroma
at least 0.10, adjacent pairs at least 6 apart under protanopia and deuteranopia simulated with Machado,
Oliveira and Fernandes (2009) at severity 1.0 (8 is the target; 6 to 8 is legal only with secondary encoding,
which every Insights chart has: a legend, gaps and a table twin), and at least 15 apart under normal vision
(a hard floor). Delta E is the Euclidean distance in OKLab, times 100. Contrast below 3:1 against the surface
is reported for relief (the table view), never failed.
"""

from __future__ import annotations

import math

BAND = {"light": (0.43, 0.77), "dark": (0.48, 0.67)}
CHROMA_FLOOR = 0.10
CVD_FLOOR = 6.0
NORMAL_FLOOR = 15.0
MACHADO = {
    "protan": ((0.152286, 1.052583, -0.204868), (0.114503, 0.786281, 0.099216), (-0.003882, -0.048116, 1.051998)),
    "deutan": ((0.367322, 0.860646, -0.227968), (0.280085, 0.672501, 0.047413), (-0.011820, 0.042940, 0.968881)),
}


def srgb(hexcolor: str) -> tuple[float, float, float]:
    h = hexcolor.strip().lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return r, g, b


def linear(hexcolor: str) -> tuple[float, float, float]:
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb(hexcolor))
    return r, g, b


def oklab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = rgb
    lc = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    mc = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    sc = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * lc + 0.7936177850 * mc - 0.0040720468 * sc,
            1.9779984951 * lc - 2.4285922050 * mc + 0.4505937099 * sc,
            0.0259040371 * lc + 0.7827717662 * mc - 0.8086757660 * sc)


def simulate(hexcolor: str, kind: str) -> tuple[float, float, float]:
    r, g, b = linear(hexcolor)
    m = MACHADO[kind]
    r2, g2, b2 = (max(0.0, min(1.0, row[0] * r + row[1] * g + row[2] * b)) for row in m)
    return r2, g2, b2


def delta_e(a: str, b: str, kind: str | None = None) -> float:
    pa = oklab(simulate(a, kind) if kind else linear(a))
    pb = oklab(simulate(b, kind) if kind else linear(b))
    return 100 * math.dist(pa, pb)


def luminance(hexcolor: str) -> float:
    r, g, b = linear(hexcolor)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def validate(palette: list[str], mode: str, surface: str) -> dict:
    """The checks over the adjacent pairs of a categorical palette: failures, and the relief it needs."""
    lo, hi = BAND[mode]
    fails = []
    for c in palette:
        L, a, b = oklab(linear(c))
        if not lo <= L <= hi:
            fails.append(f"{c}: lightness {L:.3f} outside {lo}-{hi} ({mode})")
        if math.hypot(a, b) < CHROMA_FLOOR:
            fails.append(f"{c}: chroma {math.hypot(a, b):.3f} below {CHROMA_FLOOR}")
    for x, y in zip(palette, palette[1:], strict=False):
        cvd = min(delta_e(x, y, "protan"), delta_e(x, y, "deutan"))
        if cvd < CVD_FLOOR:
            fails.append(f"{x}/{y}: CVD delta E {cvd:.1f} below {CVD_FLOOR}")
        normal = delta_e(x, y)
        if normal < NORMAL_FLOOR:
            fails.append(f"{x}/{y}: normal-vision delta E {normal:.1f} below {NORMAL_FLOOR}")
    relief = [c for c in palette if contrast(c, surface) < 3.0]
    return {"ok": not fails, "fails": fails, "relief": relief}


def hex_of(css: str) -> str:
    """'rgb(42, 120, 214)' or '#2a78d6' as '#2a78d6'."""
    css = css.strip()
    if css.startswith("#"):
        return css.lower()
    nums = [int(float(x)) for x in css[css.index("(") + 1:css.index(")")].replace("/", ",").split(",")[:3]]
    return "#" + "".join(f"{n:02x}" for n in nums)
