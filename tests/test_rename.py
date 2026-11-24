"""The Rihmasto rename of the command line (D-0013).

The distribution is `rihmasto` under Apache-2.0, its commands are rihmasto, rihmasto-cockpit,
rihmasto-embed and rihmasto-mcp, and the rihma commands stay as aliases of the same entry points.
The parser says rihmasto. The factory home is --home, else RIHMASTO_HOME, else RIHMA_HOME, else
GNOMONFACTORY_HOME, else var/ in the checkout; a variable that is set but empty counts as unset.
The Python packages and the schema ids keep their names: they are wire formats.
"""

import contextlib
import importlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from kernel import store
from kernel.cli import PROG, build_parser, main
from kernel.store import REPO_ROOT, Factory

PYPROJECT = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
SUFFIXES = ("", "-cockpit", "-embed", "-mcp")
HOME_VARS = ("RIHMASTO_HOME", "RIHMA_HOME", "GNOMONFACTORY_HOME")
REPOSITORY = re.compile(r"https://github\.com/[\w.-]+/rihmastoai")


def environment(**values: str):
    """The process environment with none of the factory home's variables but those given."""
    env = {k: v for k, v in os.environ.items() if k not in HOME_VARS}
    return mock.patch.dict(os.environ, {**env, **values}, clear=True)


class DistributionTest(unittest.TestCase):
    def test_the_distribution_is_rihmasto_under_apache_2_0_with_a_readme_urls_and_classifiers(self):
        project = PYPROJECT["project"]
        self.assertEqual((project["name"], project["license"]), ("rihmasto", "Apache-2.0"))
        self.assertTrue((REPO_ROOT / project["readme"]).is_file(), project["readme"])
        repository = project["urls"]["Repository"]
        self.assertRegex(repository, f"^{REPOSITORY.pattern}$")
        self.assertTrue(all(url.startswith(repository) for url in project["urls"].values()), project["urls"])
        self.assertIn("Programming Language :: Python :: 3.11", project["classifiers"])
        # a licence expression and a licence classifier together are refused by setuptools (PEP 639)
        self.assertEqual([c for c in project["classifiers"] if c.startswith("License ::")], [])
        self.assertIn("setuptools>=77", PYPROJECT["build-system"]["requires"])
        self.assertEqual(project["dependencies"], [])

    def test_every_rihmasto_command_has_its_rihma_alias_on_the_same_entry_point(self):
        scripts = PYPROJECT["project"]["scripts"]
        self.assertEqual(set(scripts), {f"{name}{s}" for name in ("rihmasto", "rihma") for s in SUFFIXES})
        for suffix in SUFFIXES:
            self.assertEqual(scripts[f"rihmasto{suffix}"], scripts[f"rihma{suffix}"], suffix)
        self.assertEqual(scripts["rihmasto"], "kernel.cli:main")
        for target in set(scripts.values()):
            module, _, function = target.partition(":")
            self.assertTrue(callable(getattr(importlib.import_module(module), function)), target)

    def test_the_python_packages_keep_their_names(self):
        packages = PYPROJECT["tool"]["setuptools"]["packages"]
        self.assertEqual([p for p in packages if "." not in p], ["kernel", "adapters", "cockpit", "embed", "mcp"])
        self.assertEqual([p for p in packages if "." in p], ["kernel.runners"])   # the cell runners (D-0019)
        self.assertTrue(all((REPO_ROOT / p.replace(".", "/") / "__init__.py").is_file() for p in packages))


class ParserTest(unittest.TestCase):
    def test_the_parser_and_its_help_say_rihmasto(self):
        parser = build_parser()
        self.assertEqual((parser.prog, PROG), ("rihmasto", "rihmasto"))
        text = parser.format_help()
        self.assertTrue(text.startswith("usage: rihmasto "), text[:80])
        self.assertIn("rihmasto new", text)
        self.assertIsNone(re.search(r"^\s+rihma\s", text, re.MULTILINE))         # no usage line keeps the old name
        home = next(a.help for a in parser._actions if a.dest == "home")
        self.assertLess(home.index("$RIHMASTO_HOME"), home.index("$RIHMA_HOME"))
        self.assertLess(home.index("$RIHMA_HOME"), home.index("$GNOMONFACTORY_HOME"))

    def test_a_refusal_is_signed_with_the_new_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = main(["--home", tmp, "pack", "no-such-project"])
        self.assertEqual(code, 2)
        self.assertTrue(err.getvalue().startswith("rihmasto pack: "), err.getvalue())


class HomeOrderTest(unittest.TestCase):
    def test_RIHMASTO_HOME_wins_then_RIHMA_HOME_then_GNOMONFACTORY_HOME_then_var(self):
        with environment(RIHMASTO_HOME="a", RIHMA_HOME="b", GNOMONFACTORY_HOME="c"):
            self.assertEqual(Factory().home, Path("a"))
        with environment(RIHMA_HOME="b", GNOMONFACTORY_HOME="c"):
            self.assertEqual(Factory().home, Path("b"))
        with environment(GNOMONFACTORY_HOME="c"):
            self.assertEqual(Factory().home, Path("c"))
        with environment():
            self.assertEqual(Factory().home, REPO_ROOT / "var")

    def test_a_variable_set_but_empty_counts_as_unset(self):
        with environment(RIHMASTO_HOME="", RIHMA_HOME="", GNOMONFACTORY_HOME="c"):
            self.assertEqual(Factory().home, Path("c"))
        self.assertIsNone(store.home_from_env({"RIHMASTO_HOME": "", "RIHMA_HOME": ""}))

    def test_home_wins_over_every_variable(self):
        with environment(RIHMASTO_HOME="a", RIHMA_HOME="b", GNOMONFACTORY_HOME="c"):
            self.assertEqual(Factory("x").home, Path("x"))

    def test_the_order_is_read_from_a_given_mapping_too(self):
        self.assertEqual(store.HOME_ENVS, HOME_VARS)
        self.assertEqual(store.home_from_env({"RIHMA_HOME": "b", "GNOMONFACTORY_HOME": "c"}), "b")
        self.assertEqual(store.home_from_env({"GNOMONFACTORY_HOME": "c", "RIHMASTO_HOME": "a"}), "a")
        self.assertEqual(store.default_home({}), REPO_ROOT / "var")
        self.assertEqual(store.default_home({"RIHMA_HOME": "b"}), Path("b"))

    def projects_seen(self, env: dict, *argv: str) -> list:
        """The project ids `python -m kernel.cli status` lists, started as a child with ``env``."""
        run = subprocess.run([sys.executable, "-m", "kernel.cli", *argv, "status"], cwd=REPO_ROOT, env=env,
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        return [p["id"] for p in json.loads(run.stdout)["projects"]]

    def test_the_command_line_reads_RIHMASTO_HOME_before_the_older_names(self):
        with tempfile.TemporaryDirectory() as new, tempfile.TemporaryDirectory() as old:
            pid = Factory(new).new_project("Equipment loans").pid
            env = {k: v for k, v in os.environ.items() if k not in HOME_VARS}
            env.update(RIHMASTO_HOME=new, RIHMA_HOME=old, GNOMONFACTORY_HOME=old)
            self.assertEqual(self.projects_seen(env), [pid])
            env.pop("RIHMASTO_HOME")                                                # the older name still works
            self.assertEqual(self.projects_seen(env), [])

    def test_a_parent_hands_its_home_down_with_home_or_under_every_name(self):
        """D-0013: the child reads the first name set, so a home handed down as GNOMONFACTORY_HOME alone
        loses to an inherited RIHMASTO_HOME; --home, or every name in HOME_ENVS, wins."""
        with tempfile.TemporaryDirectory() as mine, tempfile.TemporaryDirectory() as inherited:
            pid = Factory(mine).new_project("Equipment loans").pid
            env = {k: v for k, v in os.environ.items() if k not in HOME_VARS} | {"RIHMASTO_HOME": inherited}
            self.assertEqual(self.projects_seen(env | {store.HOME_ENV: mine}), [])
            self.assertEqual(self.projects_seen(env | dict.fromkeys(store.HOME_ENVS, mine)), [pid])
            self.assertEqual(self.projects_seen(env | {store.HOME_ENV: mine}, "--home", mine), [pid])


if __name__ == "__main__":
    unittest.main()
