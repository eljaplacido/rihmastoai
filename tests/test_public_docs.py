"""The public repository explains itself (FR-PUB1): the README's breakdown, the architecture picture and its
Mermaid twin, a guide per scenario with what happens under the hood, configuring with your agents, verifying
what you install, and a version history that matches the declared version."""

import contextlib
import io
import json
import re
import sys
import tomllib
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from kernel.cli import main  # noqa: E402
from test_docs import named_subcommands, relative_links  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
SCENARIOS = ["start-blank.md", "existing-project.md", "improve-and-maintain.md", "fix-ungoverned-project.md",
             "workflows-and-automations.md"]
NEW_PAGES = [DOCS / "architecture.md", DOCS / "guides" / "configure-your-agents.md", DOCS / "scenarios" / "README.md",
             *(DOCS / "scenarios" / name for name in SCENARIOS)]
JSON_BLOCK = re.compile(r"^```json\n(.*?)^```", re.MULTILINE | re.DOTALL)


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def headings(path: Path) -> list:
    return [line.lstrip("#").strip().lower() for line in text(path).splitlines() if line.startswith("## ")]


def declared_version() -> str:
    return tomllib.loads(text(REPO / "pyproject.toml"))["project"]["version"]


def missing_subcommands(pages: list) -> list:
    named = set().union(*(named_subcommands(p) for p in pages))
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
    return missing


class ReadmeTest(unittest.TestCase):
    def test_FR_PUB1_AC_1_the_readme_breaks_rihmasto_down_in_the_order_a_newcomer_needs(self):
        found = headings(REPO / "README.md")
        wanted = ["what it is, and what it is not", "capabilities", "get started", "architecture", "tech stack",
                  "data layer", "knowledge layer", "agentic capabilities", "the gnomon harness and the kernel",
                  "use scenarios", "status", "documentation", "version history"]
        self.assertEqual([h for h in found if h in wanted], wanted, found)

    def test_FR_PUB1_AC_1_the_readme_says_honestly_what_is_alpha_and_what_runs_against_stand_ins(self):
        readme = " ".join(text(REPO / "README.md").split())
        for phrase in ("alpha", "tested only against stand-ins", "local preview", "has not happened yet",
                       "No paved road delivers an adopted repository yet", f"Version **{declared_version()}**"):
            self.assertIn(phrase, readme)

    def test_FR_PUB1_AC_1_the_readme_links_every_scenario_guide_and_the_agents_guide(self):
        linked = {(REPO / t.split("#")[0]).resolve() for t in relative_links(REPO / "README.md")}
        for page in NEW_PAGES[:2] + [DOCS / "scenarios" / name for name in SCENARIOS]:
            self.assertIn(page.resolve(), linked, page.name)


class ArchitectureTest(unittest.TestCase):
    def test_FR_PUB1_AC_2_the_architecture_picture_is_an_svg_drawn_for_light_and_dark(self):
        svg = DOCS / "assets" / "architecture.svg"
        root = ET.fromstring(text(svg))                         # well-formed XML, or this raises
        ns = "{http://www.w3.org/2000/svg}"
        self.assertEqual(root.tag, f"{ns}svg")
        self.assertTrue(root.get("viewBox"))
        self.assertTrue(root.find(f"{ns}title").text and root.find(f"{ns}desc").text)
        style = root.find(f"{ns}style").text
        self.assertIn("prefers-color-scheme: dark", style)
        self.assertIn("var(--bg)", style)                       # colours are tokens, redefined for dark
        labels = " ".join("".join(t.itertext()) for t in root.iter(f"{ns}text"))
        for layer in ("Rihmasto kernel", "Knowledge layer", "Data layer", "Agent layer", "Gnomon harness",
                      "Destinations", "Ask Rihma", "MCP server"):
            self.assertIn(layer, labels)
        self.assertNotIn("<script", text(svg))

    def test_FR_PUB1_AC_2_the_mermaid_twin_names_the_same_layers_and_the_readme_shows_the_picture(self):
        page = text(DOCS / "architecture.md")
        self.assertIn("```mermaid\nflowchart", page)
        mermaid = page.split("```mermaid", 1)[1].split("```", 1)[0]
        for layer in ("Rihmasto kernel", "Knowledge layer", "Data layer", "Agent layer", "Gnomon harness",
                      "Destinations"):
            self.assertIn(layer, mermaid)
        self.assertIn("](docs/assets/architecture.svg)", text(REPO / "README.md"))
        self.assertIn("](assets/architecture.svg)", page)


class ScenarioGuidesTest(unittest.TestCase):
    def test_FR_PUB1_AC_3_each_scenario_has_a_guide_that_says_what_happens_under_the_hood(self):
        for name in SCENARIOS:
            self.assertIn("what happens under the hood", headings(DOCS / "scenarios" / name), name)
        self.assertIn("how much structure to take on", headings(DOCS / "scenarios" / "existing-project.md"))

    def test_FR_PUB1_AC_3_the_docs_index_and_the_scenario_index_link_every_new_page(self):
        index = {(DOCS / t.split("#")[0]).resolve() for t in relative_links(DOCS / "README.md")}
        scenarios = {(DOCS / "scenarios" / t.split("#")[0]).resolve()
                     for t in relative_links(DOCS / "scenarios" / "README.md")}
        for page in NEW_PAGES:
            self.assertIn(page.resolve(), index, page.name)
        for name in SCENARIOS:
            self.assertIn((DOCS / "scenarios" / name).resolve(), scenarios, name)

    def test_FR_PUB1_AC_3_the_agents_guide_covers_each_agent_through_mcp_and_hooks_with_valid_json(self):
        guide = DOCS / "guides" / "configure-your-agents.md"
        found = headings(guide)
        for agent in ("claude code", "cursor", "codex", "opencode", "hooks (optional)"):
            self.assertIn(agent, found)
        blocks = JSON_BLOCK.findall(text(guide))
        self.assertGreaterEqual(len(blocks), 4)
        for block in blocks:
            json.loads(block)                                    # every snippet pastes as valid JSON
        self.assertIn("[mcp_servers.rihma]", text(guide))

    def test_FR_PUB1_AC_3_every_rihmasto_command_the_new_pages_name_exists(self):
        self.assertEqual(missing_subcommands(NEW_PAGES), [])


class InstallAndHistoryTest(unittest.TestCase):
    def test_FR_PUB1_AC_4_getting_started_says_how_to_verify_gnomon_before_installing_it(self):
        guide = " ".join(text(DOCS / "getting-started.md").split())
        self.assertIn("## Verify what you install", text(DOCS / "getting-started.md").replace("###", "##"))
        for phrase in ("SHA256SUMS", "sha256sum --check", "gh attestation verify", "Get-FileHash",
                       "scripts/verify-release.sh", "gnomon trust grant"):
            self.assertIn(phrase, guide)

    def test_FR_PUB1_AC_5_the_changelog_has_a_dated_section_for_the_declared_version_below_unreleased(self):
        log = text(REPO / "CHANGELOG.md")
        version = declared_version()
        sections = re.findall(r"(?m)^## \[([^\]]+)\](?: - (\d{4}-\d{2}-\d{2}))?$", log)
        self.assertEqual(sections[0], ("Unreleased", ""))
        self.assertEqual(sections[1][0], version)
        self.assertRegex(sections[1][1], r"^\d{4}-\d{2}-\d{2}$")
        self.assertIn(f"| [{version}](#", log)                   # the versions table names it
        self.assertIn(f"| {version} (latest) | yes |", text(REPO / "SECURITY.md"))

    def test_FR_PUB1_AC_5_contributing_says_how_to_sign_off_sync_test_gate_and_keep_the_changelog(self):
        page = " ".join(text(REPO / "CONTRIBUTING.md").split())
        for phrase in ("Developer Certificate of Origin", "Sync pull requests", "python tools/quality.py --gate",
                       "tools/contract_check.py", "## Find your way around", "## Versions and the changelog",
                       "Browser tests"):
            self.assertIn(phrase, page)


if __name__ == "__main__":
    unittest.main()
