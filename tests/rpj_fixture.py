"""Neutral folders shaped like the real projects people feed into Rihmasto (FR-RPJ1), built in the test.

Nothing here is anyone's real project: invented names and text only. Each builder makes one shape:

- ``experiment``: a documents-only training experiment, with housekeeping files, a long README and a
  ``results.zip`` (metrics, a report, a log, an image, an archive inside, a secret-looking entry);
- ``uncommitted``: a git repository with a change and untracked files beside its last commit, and the
  instructions and a skill its AI tools read;
- ``workspace``: a folder holding two git repositories and a ``_snapshot`` copy of one;
- ``notes``: a folder of notes and scripts with no git (a second brain);
- ``game``: a game-like repository with assets, levels and lore, history over the last weeks, a failing
  test and a stated test command no known runner runs.
"""

from __future__ import annotations

import io
import os
import subprocess
import time
import zipfile
from pathlib import Path

GIT_ID = ["-c", "user.name=Fixture Author", "-c", "user.email=author@example.invalid"]
README_WORDS = "The lighthouse dataset holds wave heights from four buoys, cleaned and split by season. "


def _write(root: Path, files: dict[str, str | bytes]) -> None:
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            p.write_bytes(body)
        else:
            p.write_text(body, encoding="utf-8", newline="\n")


def git(root: Path, *args: str, when: float | None = None) -> str:
    env = dict(os.environ)
    if when is not None:
        stamp = f"{int(when)} +0000"
        env.update(GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
    out = subprocess.run(["git", "-c", "core.autocrlf=false", *GIT_ID, *args], cwd=root, capture_output=True,
                         text=True, env=env, check=True)
    return out.stdout.strip()


def commit(root: Path, files: dict[str, str | bytes], message: str, when: float | None = None) -> None:
    _write(root, files)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message, when=when)


def repo(root: Path, files: dict[str, str | bytes], message: str = "First version") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    commit(root, files, message)
    return root


def results_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("results/metrics.csv", "run,epoch,loss,accuracy\nr1,1,0.91,0.62\nr1,2,0.55,0.74\nr2,1,0.80,0.66\n")
        z.writestr("results/report.md", "# Evaluation report\n\nRun r1 reaches 0.74 accuracy on the held-out season.\n")
        z.writestr("results/train.log", "\n".join(f"2026-11-0{i % 9 + 1} 10:00:0{i % 10} INFO step {i} loss 0.{90 - i}"
                                                  for i in range(30)) + "\n")
        z.writestr("results/curve.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
        z.writestr("results/inner.zip", b"PK\x05\x06" + b"\0" * 18)
        z.writestr("results/.env", "MODE=demo\n")
        z.writestr("results/plot.py", "print('a plot')\n")
    return buf.getvalue()


def bomb_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("big.txt", "0" * (40 * 1024 * 1024))
    return buf.getvalue()


def experiment(root: Path) -> Path:
    junk = {".gitattributes": "* text=auto\n", ".gitignore": "*.pt\n", ".editorconfig": "root = true\n",
            ".ignore": "data/\n", "SHA256SUMS": "abc  results.zip\n", ".env.example": "API_TOKEN=\n",
            "uv.lock": "version = 1\n", "data/.gitignore": "*\n"}
    readme = "# Buoy season experiment\n\n" + README_WORDS * 120 + "\n\n## Runs\n\nSee results.zip.\n"
    _write(root, {**junk, "README.md": readme, "plan.md": "# Plan\n\nTrain two runs, compare by season.\n",
                  "notes/day-1.md": "# Day one\n\nThe split by season leaks: fixed.\n",
                  "results.zip": results_zip()})
    return root


def uncommitted(root: Path) -> Path:
    repo(root, {"README.md": "# Ledger helper\n\nA small helper that tidies ledgers.\n",
                "app/main.py": "def main():\n    return 1\n", "tests/test_main.py": "import unittest\n",
                "CLAUDE.md": "# Ledger helper\n\nRun the tests with `python -m unittest`.\n",
                ".claude/skills/tidy/SKILL.md": "---\nname: tidy\ndescription: tidy a ledger\n---\n\nTidy it.\n"})
    _write(root, {"app/main.py": "def main():\n    return 2\n", "draft.md": "# A draft not committed\n",
                  "app/extra.py": "X = 1\n"})
    return root


def workspace(root: Path) -> Path:
    app = {"README.md": "# Harbour app\n\nBookings for the harbour.\n", "app/server.py": "print('serve')\n",
           "docs/plan.md": "# Harbour plan\n\nPhase one: berths.\n" + "Detail line.\n" * 40}
    repo(root / "harbour-app", app)
    repo(root / "harbour-tools", {"README.md": "# Harbour tools\n\nScripts.\n", "tools/sync.py": "print(1)\n"})
    _write(root / "harbour-app_snapshot", app)
    return root


def notes(root: Path) -> Path:
    files: dict[str, str | bytes] = {".obsidian/app.json": "{}\n", "README.md": "# My knowledge base\n\nA vault.\n",
                                     "scripts/daily.py": "print('daily')\n"}
    for n in range(6):
        files[f"notes/topic-{n}.md"] = f"# Topic {n}\n\nWhat I learned about topic {n}.\n"
    _write(root, files)
    return root


def game(root: Path, *, now: float | None = None) -> Path:
    now = now or time.time()
    day = 86400
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "main")
    commit(root, {"README.md": "# Lantern Isles\n\nA small exploration title.\n", "project.godot": "[application]\n",
                  "CLAUDE.md": "# Lantern Isles\n\n## Tests\n\n```\npython tools/pipeline/check.py test\n```\n",
                  "tools/pipeline/check.py": "import sys\nprint('3 passed, 1 failed')\nsys.exit(1)\n",
                  "tests/test_world.py": "import unittest\n\n\nclass World(unittest.TestCase):\n"
                                         "    def test_ok(self):\n        self.assertTrue(True)\n\n"
                                         "    def test_tide(self):\n        self.assertEqual(1, 2)\n",
                  "code/player.py": "SPEED = 3\n"}, "Start the isles", when=now - 60 * day)
    commit(root, {"assets/textures/sea.png": b"\x89PNG\r\n\x1a\n" + b"\1" * 200,
                  "assets/models/boat.glb": b"glTF" + b"\2" * 300, "assets/audio/waves.ogg": b"OggS" + b"\3" * 100,
                  "levels/harbour.tscn": "[gd_scene]\n"}, "First assets", when=now - 20 * day)
    commit(root, {"lore/history.md": "# The drowned lantern\n\nLong ago the isles sank.\n",
                  "lore/factions.md": "# Factions of the isles\n\nKeepers and drifters.\n",
                  "assets/textures/sky.png": b"\x89PNG\r\n\x1a\n" + b"\4" * 200}, "Lore and sky", when=now - 3 * day)
    return root
