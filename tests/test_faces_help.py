"""Every face's help and its guide name the same things: the factory home's variables with $RIHMASTO_HOME first,
every persona, and the rihmasto-* commands; and the factory's own project has one name everywhere."""

import contextlib
import io
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402

from kernel.people import PERSONAS  # noqa: E402
from kernel.store import HOME_ENVS  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
HOME_ORDER = ", ".join(f"${name}" for name in HOME_ENVS)


def help_of(main) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
        main(["--help"])
    return " ".join(out.getvalue().split())


class HelpTest(unittest.TestCase):
    def test_every_server_names_the_home_variables_rihmasto_home_first(self):
        from cockpit.server import main as cockpit
        from embed.server import main as embed
        from mcp.server import main as mcp

        for name, main in (("cockpit", cockpit), ("embed", embed), ("mcp", mcp)):
            said = help_of(main)
            self.assertIn(HOME_ORDER, said, name)

    def test_the_embed_server_finds_its_home_as_every_face_does(self):
        from kernel.store import home_from_env

        source = (REPO / "embed" / "server.py").read_text(encoding="utf-8")
        self.assertIn("home_from_env()", source)
        self.assertEqual(home_from_env({"RIHMASTO_HOME": "a", "RIHMA_HOME": "b"}), "a")

    def test_mcp_names_every_persona_and_its_guide_does_too(self):
        from mcp.server import main as mcp

        said = help_of(mcp)
        guide = (REPO / "docs" / "mcp.md").read_text(encoding="utf-8")
        for persona in PERSONAS:
            self.assertIn(persona, said)
            self.assertIn(f"`{persona}`", guide)
        self.assertIn(", ".join(f"`${name}`" for name in HOME_ENVS), guide)

    def test_the_guides_name_rihmasto_home_first_and_the_rihmasto_commands(self):
        for doc in ("docs/mcp.md", "docs/cockpit.md"):
            text = (REPO / doc).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"default: `\$(RIHMA_HOME|GNOMONFACTORY_HOME)`", doc)
        embeds = (REPO / "docs" / "guides" / "embeds.md").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"(?<![\w-])rihma(-embed|-cockpit)?(?= )", embeds), "an older command name")
        self.assertIn("rihmasto-embed", embeds)


class ReleasedDocsTest(unittest.TestCase):
    """What merged on the stable line is in the changelog's Unreleased, the README and a guide linked from docs/."""

    def test_the_merges_are_in_unreleased_the_readme_and_a_guide_each(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = changelog.split("## [Unreleased]", 1)[1].split("\n## [", 1)[0]
        for ref in ("FR-HITL1", "D-0026", "FR-ITD1", "FR-DEV1", "FR-AOP1"):
            self.assertIn(ref, unreleased)
        for heading in ("### Added", "### Changed", "### Fixed"):
            body = unreleased.split(heading, 1)[1].split("###", 1)[0]
            self.assertRegex(body, r"\n- ", heading)                        # no empty heading
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        for words in ("enforcement levels", "people in the loop", "AI architect", "compliance"):
            self.assertIn(words, readme.lower() if words.islower() else readme, words)
        index = (REPO / "docs" / "README.md").read_text(encoding="utf-8")
        for guide in ("enforcement-levels.md", "people-in-the-loop.md", "agent-operations.md",
                      "development-board.md", "integrations-and-data.md"):
            self.assertTrue((REPO / "docs" / "guides" / guide).is_file(), guide)
            self.assertIn(f"(guides/{guide})", index, guide)


class OneNameTest(FactoryTestCase):
    NAME = "Rihmasto itself"

    def test_the_factory_project_has_one_name_on_every_face(self):
        from kernel.learn import factory_project

        self.assertEqual(factory_project(self.factory).meta["title"], self.NAME)
        from cockpit.server import FACTORY_TITLE

        self.assertEqual(FACTORY_TITLE, self.NAME)
        demo = (REPO / "docs" / "demo.md").read_text(encoding="utf-8")
        self.assertIn(self.NAME, demo)
        words = (REPO / "cockpit" / "static" / "words.js").read_text(encoding="utf-8")
        self.assertIn(f'export function factoryWord() {{ return "{self.NAME}"; }}', words)
        for path in (REPO / "cockpit" / "static").glob("*.*"):
            if path.suffix in (".js", ".html"):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("Rihmasto.ai", text, path.name)   # the product's name, as every doc says it
                self.assertNotIn('brand-tld">.ai', text, path.name)   # the sidebar's brand too


if __name__ == "__main__":
    unittest.main()
