"""An adopted repository by area: what each part holds and how it moves (FR-RPJ1; docs/brownfield.md, Areas).

A game, a content site, a data or ML project is not only code: its assets, levels, world and lore grow beside
it. By rule, with no model, from the project's own mirror (``repo.git``) at the upstream's head:

- **inventory** by top-level area: files, bytes, the file types, and the binary asset kinds it holds
  (models, textures, audio, scenes, video, fonts, model weights);
- **activity** from the git history: per area over the last 7 and 30 days, the commits, files changed and
  lines added and removed; the areas most recently active; the authors and their commits;
- **documents** of design, lore and world, indexed by their first heading.

It is kept as ``areas.json`` at adoption and refreshed by a watch (kernel/adopt_watch.py); the project's
Areas card, Insights (optional data) and Ask Rihma's goal help read it. A snapshot has no history: its
activity says "not measured: a snapshot has one commit".
"""

from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any

from kernel.material_git import git

ASSETS = {
    "models": {".fbx", ".obj", ".glb", ".gltf", ".blend", ".dae", ".3ds", ".max", ".ma", ".mb", ".uasset", ".vox"},
    "textures": {".png", ".jpg", ".jpeg", ".tga", ".dds", ".psd", ".exr", ".hdr", ".bmp", ".webp", ".ktx", ".tif",
                 ".tiff", ".svg", ".aseprite"},
    "audio": {".wav", ".ogg", ".mp3", ".flac", ".aiff", ".bank", ".wem", ".mid"},
    "scenes": {".tscn", ".scn", ".unity", ".umap", ".scene", ".prefab", ".tres", ".level", ".ldtk", ".tmx", ".godot"},
    "video": {".mp4", ".mov", ".webm", ".avi"},
    "fonts": {".ttf", ".otf", ".woff", ".woff2"},
    "weights": {".safetensors", ".ckpt", ".pt", ".pth", ".onnx", ".gguf", ".h5", ".pkl"},
}
_KIND = {ext: kind for kind, exts in ASSETS.items() for ext in exts}
_DESIGN = re.compile(r"(?i)(^|/)(design|lore|world\w*|story|stories|gdd|narrative|characters?|quests?|setting|docs?"
                     r"|wiki|notes?)(/|[-_ .]|$)")
_DOC_EXT = (".md", ".markdown", ".txt", ".rst", ".org", ".adoc")
MAX_DOCS = 40
MAX_COMMITS = 3000
TOP = "(top level)"
WINDOWS = (7, 30)


def _area(path: str) -> str:
    parts = PurePosixPath(path).parts
    return parts[0] if len(parts) > 1 else TOP


def _rev(project: Any) -> str | None:
    adopted = project.read("adopted.json") or {}
    bare = project.path("repo.git")
    for ref in (f"refs/remotes/upstream/{adopted.get('default_branch')}", adopted.get("baseline"), "main"):
        if ref and (out := git(bare, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")):
            return out.strip()
    return None


def inventory(bare: Any, rev: str) -> list[dict[str, Any]]:
    listing = git(bare, "ls-tree", "-r", "-z", "--long", rev, timeout=300) or ""
    areas: dict[str, dict[str, Any]] = {}
    for item in listing.split("\0"):
        if "\t" not in item:
            continue
        meta, path = item.split("\t", 1)
        size = meta.split()[-1]
        a = areas.setdefault(_area(path), {"area": _area(path), "files": 0, "bytes": 0, "types": Counter(),
                                           "assets": Counter()})
        ext = PurePosixPath(path.lower()).suffix or "(none)"
        a["files"] += 1
        a["bytes"] += int(size) if size.isdigit() else 0
        a["types"][ext] += 1
        if ext in _KIND:
            a["assets"][_KIND[ext]] += 1
    out = []
    for a in sorted(areas.values(), key=lambda x: (-x["files"], x["area"])):
        out.append({**a, "types": [{"type": t, "files": n} for t, n in a["types"].most_common(6)],
                    "assets": dict(a["assets"].most_common())})
    return out


def _number(text: str) -> int:
    return int(text) if text.isdigit() else 0           # a binary file's numstat is "-"


def _commit(text: str) -> tuple[int, str, dict[str, list[int]]] | None:
    """One commit of ``git log --numstat``: when, who, and per area the files, lines added and removed."""
    head, _, rest = text.partition("\n")
    parts = head.split("\t")
    if len(parts) < 3 or not parts[1].isdigit():
        return None
    touched: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for bits in (line.split("\t") for line in rest.splitlines()):
        if len(bits) == 3:
            t = touched[_area(bits[2])]
            t[0], t[1], t[2] = t[0] + 1, t[1] + _number(bits[0]), t[2] + _number(bits[1])
    return int(parts[1]), parts[2], touched


def _count(win: dict[str, dict[str, int]], touched: dict[str, list[int]]) -> None:
    for area, (files, added, removed) in touched.items():
        w = win.setdefault(area, {"commits": 0, "files": 0, "added": 0, "removed": 0})
        w["commits"], w["files"] = w["commits"] + 1, w["files"] + files
        w["added"], w["removed"] = w["added"] + added, w["removed"] + removed


def activity(bare: Any, rev: str, now: float) -> dict[str, Any]:
    raw = git(bare, "log", rev, f"-n{MAX_COMMITS}", "--no-renames", "--format=%x00%H%x09%at%x09%an",
              "--numstat", timeout=300) or ""
    commits = [c for c in raw.split("\0") if c.strip()]
    if len(commits) <= 1:
        return {"measured": False, "commits": len(commits),
                "basis": "not measured: one commit (a snapshot, or a new repository) has no history to read"}
    win: dict[int, dict[str, dict[str, int]]] = {d: {} for d in WINDOWS}
    authors: dict[int, Counter[str]] = {d: Counter() for d in WINDOWS}
    last_touch: dict[str, int] = {}
    for at, who, touched in filter(None, map(_commit, commits)):
        last_touch.update({a: max(last_touch.get(a, 0), at) for a in touched})
        for d in (d for d in WINDOWS if now - at <= d * 86400):
            authors[d][who] += 1
            _count(win[d], touched)
    return _activity_view(rev, len(commits), win, authors, last_touch)


def _activity_view(rev: str, n: int, win: dict[int, dict[str, dict[str, int]]], authors: dict[int, Counter[str]],
                   last_touch: dict[str, int]) -> dict[str, Any]:
    """The measured activity: areas per window, the recently touched areas and the authors per window."""
    return {"measured": True, "commits": n, "basis": f"the git history at {rev[:12]} ({n} commits"
            + (f", the last {MAX_COMMITS} read" if n >= MAX_COMMITS else "") + ")",
            "windows": {str(d): sorted(({"area": a, **v} for a, v in win[d].items()),
                                       key=lambda x: (-x["commits"], x["area"])) for d in WINDOWS},
            "recent": [a for a, _ in sorted(last_touch.items(), key=lambda kv: -kv[1])][:6],
            "authors": {str(d): [{"name": nm, "commits": k} for nm, k in authors[d].most_common(8)] for d in WINDOWS}}


def documents(bare: Any, rev: str, paths: list[str]) -> list[dict[str, Any]]:
    out = []
    for path in [p for p in paths if p.lower().endswith(_DOC_EXT) and _DESIGN.search(p)][:MAX_DOCS]:
        text = git(bare, "cat-file", "-p", f"{rev}:{path}") or ""
        title = next((ln.lstrip("# ").strip() for ln in text.splitlines()[:40] if ln.startswith("#")), "")
        out.append({"path": path, "area": _area(path), "title": title[:120] or PurePosixPath(path).stem})
    return out


def take(project: Any, now: float | None = None) -> dict[str, Any]:
    """The project's areas now, by rule from its mirror."""
    bare, rev = project.path("repo.git"), _rev(project)
    if rev is None:
        return {"measured": False, "basis": "not measured: the project has no mirror to read"}
    paths = [p for p in (git(bare, "ls-tree", "-r", "-z", "--name-only", rev, timeout=300) or "").split("\0") if p]
    return {"measured": True, "revision": rev, "by": "rule (kernel/areas.py), no model",
            "areas": inventory(bare, rev), "activity": activity(bare, rev, now or time.time()),
            "documents": documents(bare, rev, paths), "at": project.factory.clock.stamp()}


def record(project: Any, person: str | None = None, persona: str | None = None) -> dict[str, Any]:
    """Take the areas and keep them in the project (``areas.json``), with a ledger record of the counts (and of
    the person who asked, when one did). A failure is kept as not measured: it never stops the work that asked."""
    try:
        got = take(project)
    except Exception as exc:  # noqa: BLE001 - reading the history is best effort; adoption never fails on it
        got = {"measured": False, "basis": f"not measured: {type(exc).__name__}"}
    project.write("areas.json", got)
    project.log("areas_taken", {"measured": got["measured"], "areas": len(got.get("areas") or []),
                                "documents": len(got.get("documents") or []),
                                "commits": (got.get("activity") or {}).get("commits"),
                                **({"person": person, "persona": persona} if person else {})})
    return got


def summary(got: dict[str, Any] | None, days: int = 30) -> str:
    """The areas in a few sentences: what each holds and what moved, for Ask Rihma and a weekly watch."""
    if not got or not got.get("measured"):
        return "The areas are not measured yet: " + str((got or {}).get("basis") or "no inventory was taken") + "."
    parts = [f"{a['area']}: {a['files']} files" + (f" ({held(a)})" if a["assets"] else "") for a in got["areas"][:6]]
    lines = ["By area: " + "; ".join(parts) + "."]
    act = got.get("activity") or {}
    lines += _moved(act, days) if act.get("measured") else [str(act.get("basis") or "Activity is not measured.")]
    if got.get("documents"):
        lines.append("Design and lore documents: " + ", ".join(d["title"] for d in got["documents"][:8]) + ".")
    return " ".join(lines)


def held(area: dict[str, Any]) -> str:
    """An area's asset kinds, as words: "2 textures, 1 audio"."""
    return ", ".join(f"{n} {k}" for k, n in list(area["assets"].items())[:3])


def _moved(act: dict[str, Any], days: int) -> list[str]:
    moved = act["windows"].get(str(days)) or []
    said = [f"{m['area']} {m['commits']} commit(s), {m['files']} file change(s), +{m['added']}/-{m['removed']} lines"
            for m in moved[:5]]
    out = [f"In the last {days} days: " + "; ".join(said) + "."] if said else \
        [f"Nothing changed in the last {days} days."]
    who = act["authors"].get(str(days)) or []
    return out + (["By: " + ", ".join(f"{w['name']} ({w['commits']})" for w in who[:4]) + "."] if who else [])
