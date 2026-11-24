"""Access control, repair round 4 (FR-ID5, D-0016): what the fourth attack found in the lane is closed.

- A repository a cell makes inside its lane (a nested ``.git``, a gitlink) carries a config of its own that
  git runs when it looks inside: the kernel refuses that work before its git runs there, and the next
  checkout removes it, with every change to a tracked file.
- The gate copies the head's tests onto its base checkout from git, never from the lane's files, so a link
  a cell left under ``tests/`` is never followed as the account that runs Rihmasto.
- The kernel's git sees the commits there are: no replace ref, graft or forged fetch refspec chooses what
  the gate diffs, checks out or takes as the next task's base.
- A token's name with an invisible character, lookalike letters or mixed scripts never passes for a listed
  person's.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from test_access import AINO, ISSUER, access_doc  # noqa: E402

from kernel import access as kaccess  # noqa: E402
from kernel import gate, git_guard  # noqa: E402
from kernel.assistant import find_in_map  # noqa: E402
from kernel.lanes import Lane, protected_paths  # noqa: E402
from kernel.name_skeleton import skeleton  # noqa: E402
from kernel.store import REPO_ROOT  # noqa: E402

GUIDE = REPO_ROOT / "docs" / "guides" / "access.md"
SECURITY = REPO_ROOT / "SECURITY.md"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args], cwd=cwd,
                          check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()


def link_dir(link: Path, target: Path) -> None:
    """A directory link anyone can make: a junction on Windows (no privilege needed), a symlink elsewhere."""
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        os.symlink(target, link, target_is_directory=True)


class LaneCase(FactoryTestCase):
    def setUp(self):
        super().setUp()
        seed = self.tmp / "seed"
        seed.mkdir()
        (seed / "a.txt").write_text("a\n", encoding="utf-8")
        (seed / "contract.json").write_text('{"v": 1}\n', encoding="utf-8")
        (seed / "app.py").write_text("WORKS = True\n", encoding="utf-8")
        (seed / "tests").mkdir()
        (seed / "tests" / "test_a.py").write_text("x = 1\n", encoding="utf-8")
        git(seed, "init", "-q", "-b", "main")
        git(seed, "add", "-A")
        git(seed, "commit", "-qm", "first")
        self.product = self.tmp / "product.git"
        git(self.tmp, "clone", "-q", "--bare", str(seed), str(self.product))
        self.main = git(self.tmp, "--git-dir", str(self.product), "rev-parse", "main")
        self.lane = Lane(self.tmp / "lanes" / "lane-1")
        self.base = self.lane.checkout(self.product, "cell/T-1")
        self.proof = self.tmp / "proof"

    def filter_script(self) -> str:
        """A clean filter that leaves the proof when git runs it, and passes its input on."""
        script = self.tmp / "filter.sh"
        script.write_text(f"#!/bin/sh\necho ran > '{self.proof.as_posix()}'\ncat\n", encoding="utf-8", newline="\n")
        script.chmod(0o755)
        return script.as_posix()


class NestedRepositoryTest(LaneCase):
    """FR-ID5-AC-1: a repository a cell makes inside its lane never runs as the kernel, nor carries over."""

    def plant_submodule(self) -> Path:
        """As the cell: a repository in sub/ with a clean filter in its own config, recorded as a gitlink and
        changed, so git must look inside it to tell whether it changed."""
        sub = self.lane.path / "sub"
        sub.mkdir()
        git(sub, "init", "-q", "-b", "main")
        (sub / "f.txt").write_text("one\n", encoding="utf-8")
        git(sub, "add", "-A")
        git(sub, "commit", "-qm", "x")
        git(sub, "config", "filter.evil.clean", self.filter_script())
        (sub / ".gitattributes").write_text("* filter=evil\n", encoding="utf-8")
        git(self.lane.path, "update-index", "--add", "--cacheinfo", f"160000,{git(sub, 'rev-parse', 'HEAD')},sub")
        (sub / "f.txt").write_text("two\n", encoding="utf-8")
        return sub

    def test_FR_ID5_AC_1_a_repository_a_cell_makes_in_its_lane_never_runs_as_the_kernel(self):
        self.plant_submodule()
        subprocess.run(["git", "add", "-A"], cwd=self.lane.path, capture_output=True, stdin=subprocess.DEVNULL)
        self.assertTrue(self.proof.exists())                  # control: an unguarded git runs the planted filter
        git(self.lane.path, "reset", "-q")
        git(self.lane.path, "update-index", "--add", "--cacheinfo",
            f"160000,{git(self.lane.path / 'sub', 'rev-parse', 'HEAD')},sub")
        self.proof.unlink()
        for kernel_git in (self.lane.changed, lambda: self.lane.commit_all("T-1 round 0: cell work")):
            with self.assertRaises(git_guard.Tampered) as ctx:
                kernel_git()
            self.assertIn("holds a repository inside it (sub, sub/.git)", str(ctx.exception))
            self.assertFalse(self.proof.exists())
        self.assertEqual(git(self.tmp, "--git-dir", str(self.product), "rev-parse", "main"), self.main)
        vendored = self.lane.path / "vendor" / "lib"           # an untracked one, never recorded, is refused too
        vendored.mkdir(parents=True)
        git(vendored, "init", "-q")
        self.assertIn("vendor/lib/.git", git_guard.nested(self.lane.path))

    def test_FR_ID5_AC_1_a_submodule_the_product_already_holds_stays_allowed(self):
        work = self.tmp / "adopted"                           # an adopted repository with a submodule of its own
        git(self.tmp, "clone", "-q", str(self.product), str(work))
        git(work, "update-index", "--add", "--cacheinfo", f"160000,{self.main},vendor/lib")
        git(work, "commit", "-qm", "an adopted submodule")
        git(work, "push", "-q", "origin", "main")
        lane = Lane(self.lane.path)
        lane.checkout(self.product, "cell/T-2")
        (lane.path / "b.txt").write_text("cell work\n", encoding="utf-8")
        head = lane.commit_all("T-2 round 0: cell work")      # the product's own gitlink is not the cell's
        self.assertEqual(git(lane.path, "show", "--name-only", "--format=", head), "b.txt")
        (lane.path / "vendor" / "lib").mkdir(parents=True, exist_ok=True)
        git(lane.path / "vendor" / "lib", "init", "-q")       # its folder holding a repository is the cell's
        with self.assertRaises(git_guard.Tampered) as ctx:
            lane.commit_all("T-2 round 1: cell work")
        self.assertIn("(vendor/lib/.git)", str(ctx.exception))

    def test_FR_ID5_AC_1_the_next_checkout_leaves_nothing_of_the_last_cell(self):
        self.plant_submodule()
        (self.lane.path / "a.txt").write_text("the last cell's change\n", encoding="utf-8")
        (self.lane.path / ".gitattributes").write_text("*.txt filter=evil\n", encoding="utf-8")
        nxt = Lane(self.lane.path)                            # the next task, the next lease
        base = nxt.checkout(self.product, "cell/T-2")
        self.assertFalse(self.proof.exists())
        self.assertEqual(base, self.main)
        self.assertFalse((nxt.path / "sub").exists())
        self.assertEqual((nxt.path / "a.txt").read_text(encoding="utf-8"), "a\n")
        self.assertEqual(git_guard.nested(nxt.path), [])
        self.assertEqual(nxt.changed(), [])


class LinkedTestsTest(LaneCase):
    """FR-ID5-AC-2: the gate never follows a link a cell left under tests/ as the kernel's account."""

    def test_FR_ID5_AC_2_a_link_under_tests_never_reaches_the_isolated_suite(self):
        secret = self.tmp / "kernel-only"
        secret.mkdir()
        (secret / "api-key.txt").write_text("sk-ONLY-THE-KERNEL-READS-THIS\n", encoding="utf-8")
        git_guard.remove(self.lane.path / "tests")            # as the cell: tests/ is now a link to it
        link_dir(self.lane.path / "tests", secret)
        seen = {}

        def isolated_suite(base_dir, pattern=None, timeout=600):
            tests = Path(base_dir) / "tests"
            seen["files"] = sorted(p.name for p in tests.iterdir())
            seen["test_a"] = (tests / "test_a.py").read_text(encoding="utf-8") if (tests / "test_a.py").exists() else None
            seen["linked"] = tests.is_symlink()
            return {"exit": 0, "tests": {}, "ran": 0, "seen": []}

        with mock.patch.object(gate, "run_suite", isolated_suite):
            self.assertEqual(gate._passing_at(self.lane.path, self.base, ["FR-X1-AC-1"], {}), ({}, {}))
        self.assertEqual(seen, {"files": ["test_a.py"], "test_a": "x = 1\n", "linked": False})


class SeenCommitsTest(LaneCase):
    """FR-ID5-AC-3: no replace ref, graft or forged refspec chooses what the kernel's git sees in a lane."""

    def cell_edits_contract(self) -> str:
        (self.lane.path / "contract.json").write_text('{"v": "tampered"}\n', encoding="utf-8")
        git(self.lane.path, "commit", "-qam", "edit a protected file")
        return git(self.lane.path, "rev-parse", "HEAD")

    def test_FR_ID5_AC_3_a_replace_ref_or_a_graft_never_hides_a_protected_change(self):
        head = self.cell_edits_contract()
        look_alike = git(self.lane.path, "commit-tree", f"{head}^{{tree}}", "-m", "an older root")
        fake = git(self.lane.path, "commit-tree", f"{self.base}^{{tree}}", "-p", self.base, "-m", "looks harmless")
        git(self.lane.path, "update-ref", f"refs/replace/{head}", fake)
        self.assertEqual(git(self.lane.path, "diff", "--name-only", f"{self.base}...{head}"), "")  # it would hide it
        self.assertEqual(protected_paths(self.lane.path, self.base, head), ["contract.json"])
        git(self.lane.path, "pack-refs", "--all")                 # packed now: the scrub drops it too
        # grafts: the base and the head both descend from a commit with the head's tree, so nothing differs
        grafts = self.lane.path / ".git" / "info" / "grafts"
        grafts.write_text(f"{head} {look_alike}\n{self.base} {look_alike}\n", encoding="utf-8")
        self.assertEqual(git(self.lane.path, "-c", "core.useReplaceRefs=false", "diff", "--name-only",
                             f"{self.base}...{head}"), "")
        self.assertEqual(protected_paths(self.lane.path, self.base, head), ["contract.json"])
        git_guard.scrub(self.lane.path)
        self.assertFalse(grafts.exists())
        self.assertEqual(git(self.lane.path, "for-each-ref", "refs/replace/"), "")

    def test_FR_ID5_AC_3_a_replaced_base_never_reaches_the_fail_first_check(self):
        (self.lane.path / "app.py").write_text("raise SystemExit('broken')\n", encoding="utf-8")
        git(self.lane.path, "add", "app.py")
        broken = git(self.lane.path, "write-tree")
        git(self.lane.path, "reset", "-q", "--hard")
        git(self.lane.path, "update-ref", f"refs/replace/{self.base}",
            git(self.lane.path, "commit-tree", broken, "-m", "first"))
        seen = {}

        def isolated_suite(base_dir, pattern=None, timeout=600):
            seen["app"] = (Path(base_dir) / "app.py").read_text(encoding="utf-8")
            return {"exit": 1, "tests": {}, "ran": 0, "seen": []}

        with mock.patch.object(gate, "run_suite", isolated_suite):
            gate._passing_at(self.lane.path, self.base, ["FR-X1-AC-1"], {})
        self.assertEqual(seen["app"], "WORKS = True\n")

    def test_FR_ID5_AC_3_the_next_task_starts_from_the_products_main(self):
        forged = self.cell_edits_contract()
        git(self.lane.path, "config", "remote.origin.fetch", "+refs/heads/main:refs/remotes/origin/elsewhere")
        git(self.lane.path, "update-ref", "refs/remotes/origin/main", forged)
        base = Lane(self.lane.path).checkout(self.product, "cell/T-2")
        self.assertEqual(base, self.main)
        self.assertNotEqual(base, forged)
        self.assertEqual(git(self.lane.path, "config", "--get-all", "remote.origin.fetch"), git_guard.DEFAULT_FETCH)
        self.assertEqual((self.lane.path / "contract.json").read_text(encoding="utf-8"), '{"v": 1}\n')


class LookalikeNameTest(unittest.TestCase):
    """FR-ID5-AC-4: a name with invisible characters, lookalike letters or mixed scripts never passes."""

    def test_FR_ID5_AC_4_a_lookalike_name_carries_its_subject(self):
        access = kaccess.parse(json.dumps(access_doc()).encode())
        listed = access.people[AINO]
        self.assertEqual(listed, "Aino Example")
        stranger = f"{ISSUER}#stranger-sub"
        cyrillic_a = "\u0410ino Example"
        for claimed in ("Aino \u200bExample", "Aino Example\u200d", cyrillic_a, "Aino Exampl\u0435",
                        "Aino\u2060 Example", "Ain0 Example", "\u202eAino Example",
                        "Aino Examp\u04cfe","AINO EXAMPLE\u00ad"):
            ident = kaccess.identity(access, stranger, email=claimed)
            self.assertTrue(ident.name.endswith(" (stranger-sub)"), ascii(claimed))
            self.assertNotIn("\u200b", ident.name)
        self.assertEqual(kaccess.identity(access, stranger, email="Aino \u200bExample").name,
                         f"{listed} (stranger-sub)")                         # shown without the invisible one
        self.assertEqual(kaccess.identity(access, stranger, email="Pat Exampl\u0435").name,
                         "Pat Exampl\u0435 (stranger-sub)")                  # mixed scripts, whoever it resembles
        for own in ("Sam Example", "\u039d\u03af\u03ba\u03bf\u03c2 \u03a0\u03b1\u03c0\u03ac\u03c2",
                    "\u0421\u0430\u0448\u0430 \u041f\u0435\u0442\u0440\u043e\u0432", "Jos\u00e9 Garc\u00eda"):
            self.assertEqual(kaccess.identity(access, stranger, email=own).name, own)   # one script, nobody's
        self.assertEqual(skeleton(listed), skeleton(cyrillic_a))


class GuideTest(unittest.TestCase):
    """FR-ID5-AC-5: the guide and SECURITY.md say what the lane's git no longer runs or sees, and the
    assistant's map takes a person there."""

    def test_FR_ID5_AC_5_the_guide_says_what_a_cell_can_no_longer_plant(self):
        guide = " ".join(GUIDE.read_text(encoding="utf-8").split())
        for said in ("**A repository inside the lane.**", "**Links under `tests/`.**",
                     "**What the kernel's git sees.**", "**Lookalike names.**",
                     "### Tutorial: see a nested repository refused"):
            self.assertIn(said, guide)
        security = " ".join(SECURITY.read_text(encoding="utf-8").split())
        for said in ("nested repository", "replace refs", "copied from git"):
            self.assertIn(said, security)
        for question in ("a nested repository in the lane", "nested repository refused", "lookalike name in a token",
                         "replace refs and grafts"):
            self.assertEqual(find_in_map(question)[0]["id"], "access", question)


if __name__ == "__main__":
    unittest.main()
