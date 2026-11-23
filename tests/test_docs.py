"""The docs a newcomer reads (FR-N4-AC-2): every relative link resolves, no page that ships links a page
the public release leaves out, and every `rihmasto` (or `rihma`) subcommand the README and the
getting-started guide name exists in the command line's parser."""

import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

from kernel.cli import main

REPO = Path(__file__).resolve().parent.parent
TOP_PAGES = [REPO / name for name in ("README.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "GOVERNANCE.md",
                                      "SECURITY.md")]
DOCS = [*TOP_PAGES, *sorted((REPO / "docs").rglob("*.md"))]
NAMING_COMMANDS = [REPO / "README.md", REPO / "docs" / "getting-started.md"]
# The pages written for a newcomer (FR-N4): they must name no local path or machine.
NEWCOMER_PAGES = [*TOP_PAGES, REPO / "pyproject.toml", REPO / "docs" / "README.md",
                  REPO / "docs" / "getting-started.md", REPO / "docs" / "how-it-works.md",
                  *sorted((REPO / "docs" / "guides").glob("*.md"))]
# What the public release leaves out (the owner's release decisions of 2026-11-23): the build history
# and the original brief stay in the private repository, so a page that ships must not link them.
LEFT_OUT_DIRS = ("blueprint", "evidence", "intake", "envelopes")
LEFT_OUT_FILES = ("docs/m0-log.md", "docs/release-checklist.md", "docs/ux-review.md")

FENCE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
INLINE = re.compile(r"\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
REFERENCE = re.compile(r"^\s*\[[^\]]+\]:\s*<?(\S+?)>?(?:\s+\"[^\"]*\")?\s*$", re.MULTILINE)
EXTERNAL = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
CODE = re.compile(r"```.*?```|`[^`\n]+`", re.DOTALL)
COMMAND = re.compile(r"(?<![\w-])(?:rihmasto|rihma|kernel\.cli)[ \t]+([a-z][a-z-]*)")
# Machine details by their shape only: the exact names that must never ship (hosts, people) are kept
# out of the repository, in the release export's local denylist, so these checks do not name them.
WINDOWS_USER_PATH = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]", re.IGNORECASE)
HOME_PATH = re.compile(r"/(?:home|Users)/[a-z][\w.-]*/", re.IGNORECASE)
PRIVATE_ADDRESS = re.compile(r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")


def left_out(relative: str) -> bool:
    """Whether the public release leaves out this repository path (forward slashes)."""
    first, _, _ = relative.partition("/")
    return (first in LEFT_OUT_DIRS or relative in LEFT_OUT_FILES
            or (relative.startswith("docs/") and relative.count("/") == 1 and relative.endswith(".html")))


def relative_links(path: Path) -> list:
    text = FENCE.sub("", path.read_text(encoding="utf-8"))
    targets = INLINE.findall(text) + REFERENCE.findall(text)
    return [t for t in targets if not EXTERNAL.match(t) and not t.startswith("#")]


def named_subcommands(path: Path) -> set:
    names = set()
    for block in CODE.findall(path.read_text(encoding="utf-8")):
        names.update(COMMAND.findall(block))
    return names


class DocsTest(unittest.TestCase):
    def test_FR_N4_AC_2_every_relative_link_in_the_docs_resolves_to_a_file_in_the_repository(self):
        broken, checked = [], 0
        for doc in DOCS:
            for target in relative_links(doc):
                checked += 1
                resolved = (doc.parent / unquote(target.split("#")[0].split("?")[0])).resolve()
                if not resolved.exists() or REPO not in (resolved, *resolved.parents):
                    broken.append(f"{doc.relative_to(REPO)}: {target}")
        self.assertGreater(checked, 50)
        self.assertEqual(broken, [])

    def test_FR_N4_AC_2_no_page_that_ships_links_a_page_the_release_leaves_out(self):
        shipped = [d for d in DOCS if not left_out(d.relative_to(REPO).as_posix())]
        self.assertIn(REPO / "GOVERNANCE.md", shipped)
        found = []
        for doc in shipped:
            for target in relative_links(doc):
                resolved = (doc.parent / unquote(target.split("#")[0].split("?")[0])).resolve()
                if REPO in resolved.parents and left_out(resolved.relative_to(REPO).as_posix()):
                    found.append(f"{doc.relative_to(REPO)}: {target}")
        self.assertEqual(found, [])

    def test_FR_N4_AC_2_the_docs_index_links_every_page_in_docs_that_ships(self):
        index = REPO / "docs" / "README.md"
        linked = {(index.parent / unquote(t.split("#")[0])).resolve() for t in relative_links(index)}
        pages = [p for p in sorted((REPO / "docs").rglob("*.md"))
                 if p != index and not left_out(p.relative_to(REPO).as_posix())]
        self.assertGreater(len(pages), 20)
        self.assertEqual([p.relative_to(REPO).as_posix() for p in pages if p not in linked], [])

    def test_FR_N4_AC_2_the_release_check_knows_what_is_left_out(self):
        for path in ("docs/m0-log.md", "docs/release-checklist.md", "docs/rihma-v1.html", "blueprint/x.log",
                     "evidence/T-004/gate.md", "intake/brief.md", "envelopes/T-004.md"):
            self.assertTrue(left_out(path), path)
        for path in ("docs/how-it-works.md", "docs/guides/profiles.md", "decisions/D-0013-name-rihmasto.md",
                     "README.md", "kernel/cli.py", "cockpit/static/index.html"):
            self.assertFalse(left_out(path), path)

    def test_FR_N4_AC_2_every_rihma_subcommand_the_readme_and_getting_started_name_exists(self):
        named = set().union(*(named_subcommands(p) for p in NAMING_COMMANDS))
        self.assertTrue({"demo", "doctor", "new", "run"} <= named, named)
        missing = []
        for sub in sorted(named):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                try:
                    main([sub, "--help"])
                    code = 0
                except SystemExit as exc:
                    code = exc.code
            if code != 0:
                missing.append(sub)
        self.assertEqual(missing, [], f"named in the docs but not in the parser: {missing}")

    def test_FR_N4_AC_2_the_link_check_catches_a_broken_link_and_skips_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "probe.md"
            doc.write_text("[ok](getting-started.md) [web](https://example.com) [anchor](#top)\n"
                           "[broken](no-such-page.md)\n\n```\n[in code](nowhere.md)\nrihma not-a-command\n```\n"
                           "Run `rihma demo`, then `python -m kernel.cli doctor`; rihma-cockpit is no subcommand.\n"
                           "Then `rihmasto status`; `rihmasto-cockpit --home var/demo` is no subcommand either.\n",
                           encoding="utf-8")
            self.assertEqual(relative_links(doc), ["getting-started.md", "no-such-page.md"])
            self.assertEqual(named_subcommands(doc), {"not-a-command", "demo", "doctor", "status"})

    def test_newcomer_pages_name_no_local_path_or_machine(self):
        for page in NEWCOMER_PAGES:
            text = page.read_text(encoding="utf-8")
            self.assertIsNone(WINDOWS_USER_PATH.search(text), page.name)
            self.assertIsNone(HOME_PATH.search(text), page.name)
            self.assertIsNone(PRIVATE_ADDRESS.search(text), page.name)

    def test_newcomer_page_check_catches_a_home_path_and_a_private_address(self):
        # Neutral probes, joined at run time so that a scan of the shipped files for literal home
        # paths and addresses finds none in this test.
        user_path = "\\".join(["D:", "Users", "someone", "repo"])
        home = "/".join(["", "home", "someone", "repo"])
        address = ".".join(["192", "168", "1", "20"])
        self.assertIsNotNone(WINDOWS_USER_PATH.search(f"see {user_path}"))
        self.assertIsNotNone(HOME_PATH.search(f"see {home}"))
        self.assertIsNotNone(PRIVATE_ADDRESS.search(f"http://{address}:8080/v1"))
        self.assertIsNone(PRIVATE_ADDRESS.search("http://127.0.0.1:8787, Gnomon 0.6.6 and version 10.2.3"))


if __name__ == "__main__":
    unittest.main()
