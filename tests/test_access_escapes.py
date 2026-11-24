"""Access control, repair round 3 (FR-ID4, D-0016): the escapes the last attack found are closed.

- Adoption's baseline run of an existing repository's tests goes through the isolation runner while access
  is enforced, and is not run (not measured, saying why) when there is none.
- A cell, or a suite run as a separate account, can write its lane's ``.git``; the kernel's own git there
  never runs a hook, fsmonitor, filter or remote it planted, and a lane whose ``.git`` was replaced is
  cloned anew.
- A token's name that is a listed person's name under another identity is not taken as it is.
- A separate account can read a cell's task file, and the guide gives it write access to the lanes.
- The key file refuses a key with private members.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from access_fakes import rsa_key  # noqa: E402
from factory_fakes import FactoryTestCase  # noqa: E402
from test_access import AINO, IDP, ISSUER, NAMES, EnforcedCockpitCase, access_doc, write_access  # noqa: E402
from test_access_isolation import IsolationCase  # noqa: E402
from test_access_tokens import ES  # noqa: E402

from kernel import access as kaccess  # noqa: E402
from kernel import access_isolation as isolation  # noqa: E402
from kernel import gate, git_guard  # noqa: E402
from kernel import jwt_verify as jv  # noqa: E402
from kernel.assistant import find_in_map  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.lanes import Lane  # noqa: E402
from kernel.model import run_gnomon_task  # noqa: E402
from kernel.osuser import os_user  # noqa: E402
from kernel.store import REPO_ROOT, read_json  # noqa: E402

GUIDE = REPO_ROOT / "docs" / "guides" / "access.md"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


def repo_with_tests(root: Path, marker: Path) -> Path:
    """An existing repository whose own test writes ``marker`` when it is imported: proof it ran."""
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "test_x.py").write_text(textwrap.dedent(f"""\
        import unittest
        open({str(marker)!r}, "w").write("ran")


        class T(unittest.TestCase):
            def test_a(self):
                pass
        """), encoding="utf-8")
    (root / "README.md").write_text("# adoptee\n", encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "first")
    return root


class AdoptionTest(IsolationCase):
    """FR-ID4-AC-1: adoption runs the adopted repository's tests only through the isolation runner."""

    def adopt(self, title: str) -> tuple[int, str]:
        source = repo_with_tests(self.tmp / f"src-{title}", self.marker)
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), "adopt", "--person", "Op Example", "--persona",
                         "business_owner", "--source", str(source), "--intent", "maintain", title])
        return code, err.getvalue()

    def access(self, **isolated) -> None:
        me = f"local:{os_user()}"
        doc = access_doc()
        doc["people"].append({"identity": me, "name": "Op Example"})
        doc["bindings"].append({"subject": me, "persona": "business_owner", "scope": "*"})
        doc.pop("isolation")
        if isolated:
            doc["isolation"] = isolated
        write_access(self.factory, doc)

    def baseline(self, title: str) -> dict:
        project = next(p for p in self.factory.projects() if p.meta.get("title") == title)
        return read_json(project.path("baseline.json"))

    def test_FR_ID4_AC_1_adoption_runs_the_adopted_tests_only_through_the_isolation_runner(self):
        self.access()                                                         # enforced, no runner
        code, err = self.adopt("Adoptee")
        self.assertEqual(code, 0, err)
        self.assertFalse(self.marker.exists())                                # the adopted code never ran
        character = self.baseline("Adoptee")
        self.assertEqual(character["verdict"], "not measured")
        self.assertIn("names no isolation runner, so the gate's run of a project's own tests does not run",
                      character["runs"][0]["reason"])
        self.access(runner="container", image="python:3.12-slim", docker_cli=[sys.executable, str(self.docker)])
        code, err = self.adopt("Adoptee two")
        self.assertEqual(code, 0, err)
        self.assertTrue(self.marker.exists())                                 # it ran, in the container
        self.assertEqual(self.baseline("Adoptee two")["verdict"], "passed")
        argv = self.docker_calls()[0]
        flags = " ".join(argv[:argv.index("python:3.12-slim")])
        for closed in ("run --rm", "--network none", "--cap-drop ALL", "--read-only", ",dst=/work,readonly",
                       "--env PIP_NO_INDEX=1", "--env DATA_DIR=/tmp/data"):
            self.assertIn(closed, flags)
        self.assertEqual(argv[argv.index("python:3.12-slim") + 1:][:3], ["python3", "-m", "unittest"])

    def test_FR_ID4_AC_1_a_separate_account_runs_the_adopted_tests_through_sudo(self):
        self.access(runner="os_account", account="rihmasto-run", python="/usr/bin/python3")
        checkout = self.tmp / "scratch" / "w"
        checkout.mkdir(parents=True)
        env = {"PIP_NO_INDEX": "1", "API_TOKEN": "not passed", "DATA_DIR": "unused"}
        with isolation.serving(self.factory), mock.patch.object(isolation, "SUDO_WORKS", True), \
                isolation.adopted_suite([sys.executable, "-m", "unittest"], checkout=checkout, env=env,
                                        tool="python") as job:
            self.assertEqual(job.argv[:6], ["sudo", "-n", "-u", "rihmasto-run", "--", "env"])
            self.assertIn("PIP_NO_INDEX=1", job.argv)
            self.assertNotIn("API_TOKEN=not passed", job.argv)
            self.assertEqual(job.argv[-3:], ["/usr/bin/python3", "-m", "unittest"])


class LaneEscapeTest(FactoryTestCase):
    """FR-ID4-AC-2: what a cell plants in its lane's .git never runs as the kernel's account."""

    def setUp(self):
        super().setUp()
        self.product = self.tmp / "product.git"
        seed = self.tmp / "seed"
        seed.mkdir()
        (seed / "a.txt").write_text("a\n", encoding="utf-8")
        (seed / "tests").mkdir()
        (seed / "tests" / "test_a.py").write_text("", encoding="utf-8")
        git(seed, "init", "-q", "-b", "main")
        git(seed, "add", "-A")
        git(seed, "commit", "-qm", "first")
        git(self.tmp, "clone", "-q", "--bare", str(seed), str(self.product))
        self.proofs = self.tmp / "proofs"
        self.proofs.mkdir()

    def plant(self, where: Path, name: str, proof: str = "") -> Path:
        """A hook script that leaves ``proofs/<proof>`` (its own name unless given) when it runs; a filter or
        signing program (``proof`` given) also passes its input on, a hook reads nothing."""
        where.mkdir(parents=True, exist_ok=True)
        script = where / name
        passes = "cat\n" if proof else ""
        script.write_text(f"#!/bin/sh\necho ran > '{(self.proofs / (proof or name)).as_posix()}'\n{passes}exit 0\n",
                          encoding="utf-8", newline="\n")
        script.chmod(0o755)
        return script

    def poison(self, lane: Lane) -> None:
        """As a cell in a container that mounts its lane can: hooks, a hooks path, fsmonitor, a filter driver,
        a signing program, origin pointing at a repository of its own with a receive hook, and a commondir
        sending git to that repository's config, which names a filter of its own."""
        dot = lane.path / ".git"
        for hook in ("pre-commit", "prepare-commit-msg", "commit-msg", "post-commit", "pre-push",
                     "reference-transaction", "post-checkout", "post-merge"):
            self.plant(dot / "hooks", hook)
        other = self.plant(lane.path / "my-hooks", "pre-commit").parent
        evil = lane.path / "evil.git"
        git(lane.path, "init", "-q", "--bare", str(evil))
        self.plant(evil / "hooks", "pre-receive")
        monitor = self.plant(lane.path, "fsmonitor")
        cfg = dot / "config"
        cfg.write_text(cfg.read_text(encoding="utf-8") + textwrap.dedent(f"""\
            [core]
            \thooksPath = {other.as_posix()}
            \tfsmonitor = {monitor.as_posix()}
            [filter "evil"]
            \tclean = {(self.proofs / 'filter').as_posix()}.sh
            [commit]
            \tgpgSign = true
            [gpg]
            \tprogram = {(self.proofs / 'gpg').as_posix()}.sh
            """), encoding="utf-8")
        self.plant(self.proofs, "filter.sh", "filter")
        self.plant(self.proofs, "gpg.sh", "gpg")
        # commondir would send git to another repository's config: there, a filter driver of its own
        git(evil, "config", "filter.evil.smudge", f"{(self.proofs / 'common').as_posix()}.sh")
        git(evil, "config", "filter.evil.clean", f"{(self.proofs / 'common').as_posix()}.sh")
        self.plant(self.proofs, "common.sh", "common")
        git(lane.path, "config", "remote.origin.url", str(evil))
        (lane.path / ".gitattributes").write_text("*.txt filter=evil\n", encoding="utf-8")
        (lane.path / "b.txt").write_text("cell work\n", encoding="utf-8")
        (dot / "commondir").write_text(evil.as_posix() + "\n", encoding="utf-8")

    def ran(self) -> list[str]:
        return sorted(p.name for p in self.proofs.iterdir() if not p.name.endswith(".sh"))

    def test_FR_ID4_AC_2_what_a_cell_plants_in_its_lanes_git_never_runs_as_the_kernel(self):
        lane = Lane(self.tmp / "lanes" / "lane-1")
        lane.checkout(self.product, "cell/T-1")
        self.poison(lane)
        head = lane.commit_all("T-1 round 1: cell work")                    # as dispatch does after the cell
        self.assertEqual(self.ran(), [])
        lane.push("cell/T-1", "main")
        self.assertEqual(self.ran(), [])                                      # no hook, monitor, filter or signer
        self.assertEqual(git(self.tmp, "--git-dir", str(self.product), "rev-parse", "main"), head)  # the product's
        config = (lane.path / ".git" / "config").read_text(encoding="utf-8")
        for gone in ("hooksPath", "fsmonitor", "evil", "gpg"):
            self.assertNotIn(gone, config)
        self.assertEqual([h.name for h in (lane.path / ".git" / "hooks").iterdir()
                          if not h.name.endswith(".sample")], [])
        self.poison(lane)                                                     # the next lease, the next cell
        lane2 = Lane(lane.path)
        lane2.checkout(self.product, "cell/T-2")
        self.assertEqual(self.ran(), [])
        # the gate's own git in the lane, after its suites: no post-checkout on its worktree
        self.plant(lane2.path / ".git" / "hooks", "post-checkout")
        self.assertEqual(gate._passing_at(lane2.path, "HEAD", [], {}), ({}, {}))
        self.assertEqual(self.ran(), [])

    def test_FR_ID4_AC_2_a_lane_whose_git_was_replaced_is_cloned_anew(self):
        lane = Lane(self.tmp / "lanes" / "lane-1")
        lane.checkout(self.product, "cell/T-1")
        elsewhere = self.tmp / "elsewhere"
        git(self.tmp, "init", "-q", str(elsewhere))
        self.plant(elsewhere / ".git" / "hooks", "post-checkout")
        git_guard.remove(lane.path / ".git")
        (lane.path / ".git").write_text(f"gitdir: {(elsewhere / '.git').as_posix()}\n", encoding="utf-8")
        with self.assertRaises(git_guard.Tampered):
            lane.commit_all("cell work")
        lane.checkout(self.product, "cell/T-2")
        self.assertTrue((lane.path / ".git").is_dir())
        self.assertEqual(lane.git("rev-parse", "HEAD"), git(self.tmp, "--git-dir", str(self.product),
                                                           "rev-parse", "main"))
        self.assertEqual(self.ran(), [])


class DisplayNameTest(EnforcedCockpitCase):
    """FR-ID4-AC-3: a token's name that is a listed person's name under another identity is not taken."""

    def test_FR_ID4_AC_3_a_stranger_named_like_a_listed_person_cannot_decide_as_that_person(self):
        access = kaccess.parse(json.dumps(access_doc()).encode())
        stranger = f"{ISSUER}#stranger-sub"
        for claimed in ("Aino Example", " aino  EXAMPLE ", "Ａino Example"):   # case, spacing, full width
            ident = kaccess.identity(access, stranger, groups=("rihmasto-ops",), email=claimed)
            self.assertEqual(ident.name, f"{claimed.strip()} (stranger-sub)")
        self.assertEqual(kaccess.identity(access, AINO).name, NAMES[AINO])          # listed: the file's name
        self.assertEqual(kaccess.identity(access, stranger, email="Sam Example").name, "Sam Example")
        p = self.new()
        self.enforce()
        cid = Canon(p).card("incident", "Checkout is down")["id"]
        proxy = {"groups": ["rihmasto-ops"], "email": "Aino Example"}
        self.sign_in(stranger, **proxy)
        status, out = self.pcall("POST", f"/api/projects/{p.pid}/cards/{cid}/decide",
                                 {"verdict": "acknowledge", "person": "Aino Example", "persona": "operations",
                                  "reason": "on it"}, who=stranger, **proxy)
        self.assertEqual(status, 403, out)
        self.assertIn("Aino Example (stranger-sub)", out["error"])
        status, out = self.pcall("POST", f"/api/projects/{p.pid}/cards/{cid}/decide",
                                 {"verdict": "acknowledge", "person": "Aino Example (stranger-sub)",
                                  "persona": "operations", "reason": "on it"}, who=stranger, **proxy)
        self.assertEqual(status, 200, out)
        decision = p.ledger().of_kind("decision")[-1]["event"]["payload"]
        self.assertEqual((decision["person"], decision["identity"]), ("Aino Example (stranger-sub)", stranger))


class TaskFileTest(IsolationCase):
    """FR-ID4-AC-4: a separate account can read its cell's task file; the guide gives it the lanes to write."""

    def test_FR_ID4_AC_4_a_separate_account_reads_its_cells_task_file(self):
        self.runner(runner="os_account", account="rihmasto-run")
        seen = {}
        real_chmod = os.chmod

        def chmod(path, mode, *a, **k):
            seen[str(path)] = mode
            return real_chmod(path, mode, *a, **k)

        def run(cmd, **_):
            task = cmd[cmd.index("--task-file") + 1]
            seen["cmd"], seen["task"] = cmd, task
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"output": "an answer", "bucket": "ok"}), "")

        with isolation.serving(self.factory), mock.patch.object(isolation, "SUDO_WORKS", True), \
                mock.patch.object(isolation.os, "chmod", chmod), mock.patch("kernel.model.subprocess.run", run):
            record = run_gnomon_task(self.lane, "Who asked?", role="analyst")
        self.assertEqual(record["output"], "an answer")
        self.assertEqual(seen["cmd"][:5], ["sudo", "-n", "-u", "rihmasto-run", "--"])
        self.assertEqual(seen.get(seen["task"]), 0o640)                        # its group reads it; not everyone
        text = " ".join(GUIDE.read_text(encoding="utf-8").split())
        self.assertNotIn("read access to the lanes and nothing else", text)
        self.assertIn("write access to each lane folder", text)
        for said in ("### Tutorial: see the isolation work", "**adoption's baseline run**", "**The lane's `.git`.**",
                     "(mode 0640), never to everyone"):
            self.assertIn(said, text)
        for question in ("what does the kernel do with a lane's .git", "adoption baseline isolated"):
            self.assertEqual(find_in_map(question)[0]["id"], "access", question)


class PrivateKeyTest(unittest.TestCase):
    """FR-ID4-AC-5: the key file refuses a key that carries private members."""

    def test_FR_ID4_AC_5_the_key_file_refuses_a_key_with_private_members(self):
        d = rsa_key(seed=1)[2]                                                # IDP's own private exponent
        rsa, ec = IDP.jwk(), ES.jwk()
        for jwk, members in ((dict(rsa, d=jv.b64url_encode(d.to_bytes(256, "big"))), "d"),
                             (dict(rsa, p="AQAB", q="AQAB"), "p, q"),
                             (dict(ec, d=jv.b64url_encode((7).to_bytes(32, "big"))), "d"),
                             (dict(rsa, use="enc", d="AQAB", kid="set-aside"), "d")):
            with self.assertRaises(jv.KeyFileError, msg=members) as ctx:
                jv.parse_jwks(json.dumps({"keys": [jwk, ec]}).encode())
            self.assertIn(f"holds a private key ({members})", str(ctx.exception))
        self.assertEqual(set(jv.parse_jwks(json.dumps({"keys": [rsa, ec]}).encode())), {"test-key-1", "es-key-1"})


if __name__ == "__main__":
    unittest.main()
