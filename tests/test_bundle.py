"""Offline bundles (FR-Q6-AC-4): a release as one folder or zip, with its pack, contract, source and image
reference, a SHA256SUMS for every file, and a signature only when cosign really signed."""

import hashlib
import json
import os
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from test_deliver import DeliveryTestCase  # noqa: E402

from kernel.bundle import KEY_ENV, export_bundle  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.deliver import deliver  # noqa: E402


def nothing(name):
    """A host with neither docker nor cosign on PATH."""
    return None


class FakeTools:
    """docker and cosign on PATH, answering as they would; each command is recorded."""

    def __init__(self, image_present=True, cosign_exit=0):
        self.calls, self.image_present, self.cosign_exit = [], image_present, cosign_exit

    def which(self, name):
        return f"/usr/bin/{name}" if name in ("docker", "cosign") else None

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        if argv[1:3] == ["image", "inspect"]:
            return (0, "sha256:" + "ab" * 32, "") if self.image_present else (1, "", "No such image")
        if argv[1] == "save":
            Path(argv[argv.index("--output") + 1]).write_bytes(b"an image tarball")
            return 0, "", ""
        if argv[1] == "sign-blob":
            if self.cosign_exit == 0:  # cosign 3.1 and later write a Sigstore bundle (FR-PT2)
                Path(argv[argv.index("--bundle") + 1]).write_text('{"mediaType": "sigstore"}', encoding="utf-8")
            return self.cosign_exit, "", "" if self.cosign_exit == 0 else "error: no password"
        return 0, "", ""


def check_sums(folder: Path) -> list:
    """Every line of SHA256SUMS holds, and it lists every file but the signature's own."""
    lines = (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    listed = {}
    for line in lines:
        digest, name = line.split("  ", 1)
        listed[name] = digest
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name
    files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
    return [f for f in files if f not in listed]


class BundleTest(DeliveryTestCase):
    maturity = "explore"

    def setUp(self):
        super().setUp()
        self.factory.paved_roads_path.unlink()
        deliver(self.project)
        self.out = self.tmp / "bundles"

    def test_FR_Q6_AC_4_a_release_exports_as_one_offline_folder_with_sums_and_no_fake_signature(self):
        with self.assertRaises(DecisionRefused):
            export_bundle(self.project, self.out, person="Sanna", persona="stakeholder", which=nothing)
        with self.assertRaises(DecisionRefused):
            export_bundle(self.project, self.out, person="factory", persona="it", which=nothing)
        with mock.patch.dict(os.environ, {KEY_ENV: "cosign.key"}):                 # a key, but no cosign
            folder = export_bundle(self.project, self.out, person="Ilkka", persona="it", which=nothing)
        self.assertEqual(folder.name, f"{self.project.pid}-1.0.0-offline")
        rev = self.main()
        names = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
        self.assertEqual(names, {"capability-pack.json", "capability-pack.yaml", "contract.json", "image.json",
                                 f"source/product-{rev[:12]}.zip", "BUNDLE.json", "README.md", "SHA256SUMS",
                                 "signature.json", "deploy-package.json", "evidence.zip", "rihmasto_verify.py",
                                 "pack-status.json"})
        # only the signature's own files, and the status, which a fresh copy replaces
        self.assertEqual(check_sums(folder), ["SHA256SUMS", "pack-status.json", "signature.json"])
        pack = json.loads((folder / "capability-pack.json").read_text(encoding="utf-8"))
        self.assertEqual((pack["version"], pack["pinned"]["product_revision"]), ("1.0.0", rev))
        self.assertIn("rihma.capability-pack.v1", (folder / "capability-pack.yaml").read_text(encoding="utf-8"))
        contract = json.loads((folder / "contract.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["revision"], pack["pinned"]["contract_revision"])  # as the product carried it
        with zipfile.ZipFile(folder / f"source/product-{rev[:12]}.zip") as z:
            self.assertIn("product/app/server.py", z.namelist())
            self.assertIn("product/app/routes.py", z.namelist())                    # the built code at that revision
        image = json.loads((folder / "image.json").read_text(encoding="utf-8"))["artifacts"][0]
        self.assertEqual((image["type"], image["exported"]), ("process", None))
        self.assertIn("runs the product as a process", image["note"])
        signature = json.loads((folder / "signature.json").read_text(encoding="utf-8"))
        self.assertEqual((signature["signed"], signature["note"]), (False, "not signed: cosign not installed"))
        self.assertEqual(signature["status"], {"signed": False, "note": "not signed: cosign not installed"})
        self.assertFalse((folder / "SHA256SUMS.sigstore.json").exists())
        bundle = json.loads((folder / "BUNDLE.json").read_text(encoding="utf-8"))
        self.assertEqual((bundle["release"], bundle["pack_version"], bundle["revision"]), (1, "1.0.0", rev))
        self.assertIn("Holdout scenarios", (folder / "README.md").read_text(encoding="utf-8"))
        logged = self.project.ledger().of_kind("bundle_exported")[-1]["event"]["payload"]
        self.assertEqual((logged["by"], logged["persona"], logged["signed"]), ("Ilkka", "it", False))
        self.assertEqual(logged["sha256sums"], hashlib.sha256((folder / "SHA256SUMS").read_bytes()).hexdigest())
        with self.assertRaises(FileExistsError):
            export_bundle(self.project, self.out, person="Ilkka", persona="it", which=nothing)
        self.assertFalse(any(p.name.endswith(".partial") for p in self.out.iterdir()))
        from kernel.bundle import _run

        self.assertEqual(_run(["rihma-no-such-tool"], 5)[0], 127)                 # a tool that is gone is said

    def test_FR_Q6_AC_4_an_image_is_exported_and_sums_signed_only_when_the_tools_are_there(self):
        rel = self.project.read("releases/1.json")
        rel["artifacts"] = {"docker-staging": {"type": "image", "ref": "gf-loans:abc123", "id": "sha256:" + "ab" * 32}}
        self.project.write("releases/1.json", rel)
        tools = FakeTools()
        with mock.patch.dict(os.environ, {KEY_ENV: "cosign.key"}):
            path = export_bundle(self.project, self.out, person="Kaisa", persona="compliance", as_zip=True,
                                 which=tools.which, run=tools)
        self.assertEqual(path.suffix, ".zip")
        unzipped = self.tmp / "unzipped"
        with zipfile.ZipFile(path) as z:
            z.extractall(unzipped)
        self.assertEqual(sorted(check_sums(unzipped)), ["SHA256SUMS", "SHA256SUMS.sigstore.json", "pack-status.json",
                                                        "pack-status.json.sigstore.json", "signature.json"])
        image = json.loads((unzipped / "image.json").read_text(encoding="utf-8"))["artifacts"][0]
        self.assertEqual((image["exported"], image["ref"]), ("images/gf-loans_abc123.tar", "gf-loans:abc123"))
        self.assertEqual((unzipped / image["exported"]).read_bytes(), b"an image tarball")
        signature = json.loads((unzipped / "signature.json").read_text(encoding="utf-8"))
        self.assertEqual((signature["signed"], signature["by"], signature["signs"]), (True, "cosign", "SHA256SUMS"))
        sign = next(c for c in tools.calls if c[1] == "sign-blob")
        self.assertIn("--tlog-upload=false", sign)                                  # offline: nothing is uploaded
        self.assertEqual(sign[sign.index("--key") + 1], "cosign.key")               # a reference, never the key
        # cosign without a key, cosign that fails, and an image that is not on this host: said, never faked
        for env, cosign_exit, present, why in (({}, 0, True, "names no key"), ({KEY_ENV: "k"}, 1, False, "cosign failed")):
            tools = FakeTools(image_present=present, cosign_exit=cosign_exit)
            with mock.patch.dict(os.environ, env, clear=False):
                if not env:
                    os.environ.pop(KEY_ENV, None)
                folder = export_bundle(self.project, self.tmp / f"out-{cosign_exit}", person="Kaisa",
                                       persona="compliance", which=tools.which, run=tools)
            signature = json.loads((folder / "signature.json").read_text(encoding="utf-8"))
            self.assertFalse(signature["signed"])
            self.assertIn(why, signature["note"])
            self.assertFalse((folder / "SHA256SUMS.sigstore.json").exists())
            image = json.loads((folder / "image.json").read_text(encoding="utf-8"))["artifacts"][0]
            if not present:
                self.assertIsNone(image["exported"])
                self.assertEqual(image["note"], "not exported: the image is not present on this host")


if __name__ == "__main__":
    unittest.main()
