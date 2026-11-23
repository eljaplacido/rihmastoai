"""Portability, phase 1 (docs/portability.md; FR-PT1 to FR-PT6).

Every release here is real: built through the gate by the fakes, then delivered on a local or a docker
road (the docker CLI is a stand-in that answers as docker would). cosign is not installed here and is
never downloaded: a stand-in cosign executable on PATH enforces what cosign 3.1 and later enforce,
that a blob is signed only into a Sigstore bundle. Products started here listen on 127.0.0.1 only,
started as their image starts them (the Dockerfile's CMD).
"""

import contextlib
import fnmatch
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import rihmasto_verify as verifier  # noqa: E402
from test_deliver import DeliveryTestCase, FakeDocker, _Health  # noqa: E402

from kernel import roads as roadmod  # noqa: E402
from kernel.bundle import KEY_ENV, deploy_package, export_bundle, status_document, sums, tree_sha256  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.cli import main as cli  # noqa: E402
from kernel.compile import WRITE_SCOPE  # noqa: E402
from kernel.deliver import deliver, pin_image  # noqa: E402
from kernel.lanes import GIT_ID, _git, protected_paths  # noqa: E402
from kernel.evidence_pack import GUARANTEES, governance_map  # noqa: E402
from kernel.evidence_pack import export as export_evidence  # noqa: E402
from kernel.ledger import canonical_json  # noqa: E402
from kernel import packs as packs_module  # noqa: E402
from kernel.packs import _UNHASHED, build_pack, content_sha256  # noqa: E402
from kernel.store import write_json  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SCHEMAS = REPO / "schemas"
DIGEST = "sha256:" + "cd" * 32
REGISTRY = "registry.example:5000/team"
AT = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)  # the factory's fixed clock


def nothing(name):
    """A host with neither docker nor cosign on PATH."""
    return None


def holding():
    """Every criterion holds. The fixture products build one task of three, so their packs are never valid
    on their own; the acceptance is not hashed, so the pack keeps its content and version."""
    real = packs_module.acceptance

    def valid(project, rel):
        return dict(real(project, rel), valid=True, not_valid_because=[])

    return mock.patch.object(packs_module, "acceptance", valid)


class RegistryDocker(FakeDocker):
    """The docker CLI on the deploying host. IT pushes with its own tools, outside Rihmasto; once it has
    (``pushed``), the image's RepoDigests name the digest the registry gave it, as docker records them."""

    pushed = False

    def __call__(self, argv, timeout):
        if argv[1:3] == ["image", "inspect"] and "{{json .RepoDigests}}" in argv:
            self.calls.append(list(argv))
            return 0, json.dumps([f"{argv[-1].rsplit(':', 1)[0]}@{DIGEST}"] if self.pushed else []), ""
        return super().__call__(argv, timeout)


COSIGN = r'''import hashlib, json, sys

args = sys.argv[1:]
with open(sys.argv[0] + ".calls", "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\n")


def opt(name):
    return args[args.index(name) + 1] if name in args else None


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob():
    with open(args[-1], "rb") as fh:
        return fh.read()


cmd = args[0] if args else ""
if cmd == "sign-blob":
    if not opt("--bundle"):  # cosign 3.1 and later: a Sigstore bundle, or a registry upload
        sys.stderr.write("Error: sign-blob needs --bundle: a detached signature is no longer written\n")
        sys.exit(1)
    pub, digest = "stand-in public key for " + opt("--key"), sha(blob())
    with open(opt("--bundle"), "w", encoding="utf-8") as fh:
        json.dump({"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
                   "messageSignature": {"messageDigest": {"algorithm": "SHA2_256", "digest": digest},
                                        "signature": sha((pub + digest).encode())}}, fh)
elif cmd == "public-key":
    with open(opt("--outfile"), "w", encoding="utf-8") as fh:
        fh.write("stand-in public key for " + opt("--key"))
elif cmd == "trusted-root" and args[1:2] == ["create"]:
    with open(opt("--out"), "w", encoding="utf-8") as fh:
        json.dump({"mediaType": "application/vnd.dev.sigstore.trustedroot+json;version=0.1"}, fh)
elif cmd == "verify-blob":
    if not opt("--trusted-root"):
        sys.stderr.write("Error: no --trusted-root: the public trusted root would be fetched over the network\n")
        sys.exit(1)
    with open(opt("--key"), encoding="utf-8") as fh:
        pub = fh.read()
    with open(opt("--bundle"), encoding="utf-8") as fh:
        signed = json.load(fh)["messageSignature"]
    digest = sha(blob())
    if signed["messageDigest"]["digest"] != digest or signed["signature"] != sha((pub + digest).encode()):
        sys.stderr.write("Error: invalid signature\n")
        sys.exit(1)
    print("Verified OK")
else:
    sys.exit(2)
'''


class FakeCosign:
    """A cosign executable on PATH, as a person would have it installed (a script and its launcher)."""

    def __init__(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        self.script = folder / "cosign_standin.py"
        self.script.write_text(COSIGN, encoding="utf-8", newline="\n")
        if os.name == "nt":
            self.exe = folder / "cosign.cmd"
            self.exe.write_text(f'@"{sys.executable}" "{self.script}" %*\r\n', encoding="utf-8")
        else:
            self.exe = folder / "cosign"
            self.exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{self.script}" "$@"\n', encoding="utf-8")
            self.exe.chmod(0o755)
        self.folder = folder

    def calls(self) -> list:
        log = Path(str(self.script) + ".calls")
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []

    def on_path(self, key: str = "kms://example/keys/factory"):
        return mock.patch.dict(os.environ, {"PATH": str(self.folder) + os.pathsep + os.environ.get("PATH", ""),
                                            KEY_ENV: key})

    def run(self, *args: str) -> None:
        subprocess.run([str(self.exe), *args], check=True, capture_output=True, timeout=120)

    def published_key(self, out: Path, key: str = "kms://example/keys/factory") -> str:
        """The key the factory published (`cosign public-key`), handed to a site apart from any bundle."""
        self.run("public-key", "--key", key, "--outfile", str(out))
        return str(out)


def signature_line(report: dict) -> dict:
    return next(c for c in report["checks"] if c["check"] == "signature of SHA256SUMS")


class DockerReleaseCase(DeliveryTestCase):
    """An explore release on a docker road; with a registry on the road, its image is tagged for it, and
    (``pinned``) IT pushes it with its own tools and pins it."""

    maturity = "explore"
    registry = REGISTRY
    pinned = True

    def setUp(self):
        super().setUp()
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Health)
        server.version = self.main()[:12]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        road = {"kind": "docker", "configured": True, "environments": ["preview"],
                "rules": {"tls": "reverse proxy", "egress": "none"},
                "secrets": [{"name": "API_TOKEN", "ref": "https://vault.example/secrets/api-token"}]}
        if self.registry:
            road["registry"] = self.registry
        self.roads = {"schema": roadmod.SCHEMA, "roads": {"team-docker": road}, "maturity": {"explore": "team-docker"}}
        write_json(self.factory.paved_roads_path, self.roads)
        self.fake = RegistryDocker(port=server.server_address[1])
        self.cli = roadmod.DockerCLI(runner=self.fake)
        self.addCleanup(roadmod.stop_all, self.project, self.roads, docker=self.cli)
        self.out = deliver(self.project, docker=self.cli)
        self.repo = f"{REGISTRY}/gf-{self.project.pid}"
        if self.registry and self.pinned:
            self.pin()

    def pin(self) -> dict:
        """IT pushes the tag with its own tools (outside Rihmasto), then pins the release by its digest."""
        self.fake.pushed = True
        return pin_image(self.project, person="Ilkka", persona="it", docker=self.cli)


class DigestTest(DockerReleaseCase):
    pinned = False

    def test_FR_PT1_AC_1_a_pushed_image_is_pinned_by_digest_in_the_pack_and_the_site_deploy_package(self):
        self.assertEqual(self.out["state"], "done", self.out)
        rev12 = self.main()[:12]
        self.assertIn(["docker", "tag", f"gf-{self.project.pid}:{rev12}", f"{self.repo}:{rev12}"], self.fake.calls)
        out = self.pin()                                              # once IT pushed it, a person pins it
        self.assertEqual(out["pinned"], {"team-docker": f"{self.repo}@{DIGEST}"})
        rel = self.project.read("releases/1.json")
        self.assertEqual(rel["artifacts"]["team-docker"]["ref"], f"{self.repo}@{DIGEST}")  # the road runs it so
        pack = build_pack(self.project)
        self.assertEqual(pack["pinned"]["artifacts"], {"team-docker": f"{self.repo}@{DIGEST}"})
        self.assertNotIn(f":{rev12}", json.dumps(pack["pinned"]["artifacts"]))     # no tag
        self.assertNotIn("not_by_digest", pack["pinned"])
        pkg, _ = deploy_package(self.project, pack)
        self.assertEqual(pkg["schema"], "gnomonfactory.deploy_package/2")
        self.assertEqual((pkg["artifact"]["ref"], pkg["artifact"]["digest"]), (f"{self.repo}@{DIGEST}", DIGEST))
        self.assertEqual((pkg["pack"]["version"], pkg["pack"]["content_sha256"]),
                         (pack["version"], pack["content_sha256"]))
        self.assertEqual(roadmod.validate_site_package(pkg), [])
        pinned = self.project.ledger().of_kind("image_pinned")[-1]["event"]["payload"]
        self.assertEqual((pinned["digest"], pinned["tag"], pinned["by"], pinned["persona"]),
                         (DIGEST, f"{self.repo}:{rev12}", "Ilkka", "it"))

    def test_FR_PT1_AC_3_rihmasto_pushes_nothing_it_tags_and_a_person_with_the_it_persona_pins_after_the_push(self):
        self.assertEqual(self.out["state"], "done", self.out)
        self.assertFalse([c for c in self.fake.calls if c[1] == "push"], self.fake.calls)  # no write to a registry
        rev12 = self.main()[:12]
        push = self.project.read("releases/1.json")["artifacts"]["team-docker"]["push"]
        self.assertEqual((push["tag"], push["registry"]), (f"{self.repo}:{rev12}", REGISTRY))
        self.assertIn("D-0015", push["by"])
        self.assertIn(f"rihmasto pack pin {self.project.pid}", push["then"])
        tagged = self.project.ledger().of_kind("image_tagged")[-1]["event"]["payload"]
        self.assertEqual(tagged["tag"], f"{self.repo}:{rev12}")
        pack = build_pack(self.project)                                # not pushed yet: the local image id
        self.assertEqual(pack["pinned"]["artifacts"], {"team-docker": "sha256:" + "ab" * 32})
        self.assertIn("rihmasto pack pin", pack["pinned"]["not_by_digest"]["team-docker"])
        with self.assertRaises(DecisionRefused):
            pin_image(self.project, person="Pekka", persona="developer", docker=self.cli)
        early = pin_image(self.project, person="Ilkka", persona="it", docker=self.cli)
        self.assertEqual(early["pinned"], {})
        self.assertIn("push it first", early["not_pinned"]["team-docker"])
        self.assertEqual(self.project.ledger().of_kind("image_pinned"), [])
        self.assertFalse([c for c in self.fake.calls if c[1] == "push"])


def compose_cli() -> bool:
    """Whether docker compose is installed here: `docker compose config` then reads the file for real."""
    return bool(shutil.which("docker")) and subprocess.run(["docker", "compose", "version"], capture_output=True,
                                                           timeout=120, check=False).returncode == 0


class ComposeTest(DockerReleaseCase):
    def rendered(self) -> tuple:
        pack = build_pack(self.project)
        out = roadmod.render_compose(deploy_package(self.project, pack)[0])
        self.assertEqual(out["problems"], [])
        path = self.tmp / "site" / "compose.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(out["yaml"], encoding="utf-8", newline="\n")
        return pack, out, path

    def test_FR_PT3_AC_1_compose_runs_the_image_by_digest_with_the_pack_beside_it_and_secrets_by_name(self):
        pack, rendered, path = self.rendered()
        model, app = rendered["model"], rendered["model"]["services"]["app"]
        self.assertEqual(app["image"], f"{self.repo}@{DIGEST}")
        self.assertIn({"type": "volume", "source": "data", "target": "/data"}, app["volumes"])
        self.assertEqual(model["volumes"], {"data": {}})
        binds = [m for m in app["volumes"] if m["type"] == "bind"]
        self.assertEqual(binds, [{"type": "bind", "source": ".", "target": "/pack", "read_only": True}])  # beside
        self.assertEqual((app["environment"]["RIHMA_PACK"], app["environment"]["RIHMA_PACK_STATUS"]),
                         ("/pack/capability-pack.json", "/pack/pack-status.json"))
        self.assertTrue(app["environment"]["API_TOKEN"].startswith("${API_TOKEN:?"))   # by name only
        self.assertEqual((app["environment"]["RIHMA_PACK_SHA256"], app["environment"]["RIHMA_IMAGE_DIGEST"]),
                         (pack["content_sha256"], DIGEST))
        self.assertEqual(roadmod.secret_leaks(model), [])
        self.assertNotIn("vault.example", rendered["yaml"])
        self.assertEqual(roadmod.from_yaml(rendered["yaml"]), model)
        recorded = FakeDocker()
        self.assertEqual(roadmod.compose_config(path, roadmod.DockerCLI(runner=recorded))["verdict"], "passed")
        self.assertEqual(recorded.calls, [["docker", "compose", "-f", str(path), "config", "--quiet", "--no-interpolate"]])
        if compose_cli():
            real = roadmod.compose_config(path)                                       # it reads the file only
            self.assertEqual(real["verdict"], "passed", real)

    def test_FR_PT3_AC_3_the_pack_folder_is_mounted_whole_so_a_status_replaced_by_a_rename_reaches_the_guard(self):
        _, rendered, _ = self.rendered()
        app = rendered["model"]["services"]["app"]
        self.assertFalse([m for m in app["volumes"] if str(m.get("target", "")).startswith("/pack/")])  # no file bind
        self.assertIn({"type": "bind", "source": ".", "target": "/pack", "read_only": True}, app["volumes"])
        single = json.loads(json.dumps(rendered["model"]))
        single["services"]["app"]["volumes"][1] = {"type": "bind", "source": "./pack-status.json",
                                                   "target": "/pack/pack-status.json", "read_only": True}
        problems = roadmod.validate_compose(single)
        self.assertTrue(any("single file" in p for p in problems), problems)
        self.assertIn("the pack's folder is not mounted at /pack", problems)
        folder = export_bundle(self.project, self.tmp / "out", person="Ilkka", persona="it", which=nothing)
        self.assertEqual(roadmod.from_yaml((folder / "compose.yaml").read_text(encoding="utf-8")), rendered["model"])
        for name in ("capability-pack.json", "pack-status.json"):      # the folder mounted is the bundle's
            self.assertTrue((folder / name).is_file(), name)
        self.assertIn("however it is written", (folder / "README.md").read_text(encoding="utf-8"))

    def test_FR_PT3_AC_4_a_secret_reaches_the_product_as_its_environment_variable_never_a_compose_file_secret(self):
        _, rendered, path = self.rendered()
        model, app = rendered["model"], rendered["model"]["services"]["app"]
        self.assertNotIn("secrets", model)
        self.assertNotIn("secrets", app)
        self.assertNotIn("/run/secrets", rendered["yaml"])
        self.assertEqual(app["environment"]["API_TOKEN"], roadmod.secret_from_env("API_TOKEN"))
        as_file = json.loads(json.dumps(model))
        as_file["secrets"] = {"api_token": {"environment": "API_TOKEN"}}
        as_file["services"]["app"]["secrets"] = ["api_token"]
        self.assertTrue(any("/run/secrets" in p for p in roadmod.validate_compose(as_file)))
        given = json.loads(json.dumps(model))
        given["services"]["app"]["environment"]["API_TOKEN"] = "${OTHER_VARIABLE}"
        self.assertIn("environment API_TOKEN looks like a secret and is given a value", roadmod.validate_compose(given))
        if compose_cli():                                                 # compose sets it from the environment
            env = dict(os.environ, API_TOKEN="placeholder-not-a-secret")
            proc = subprocess.run(["docker", "compose", "-f", str(path), "config", "--format", "json"], env=env,
                                  capture_output=True, text=True, timeout=120, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            seen = json.loads(proc.stdout)["services"]["app"]
            self.assertEqual(seen["environment"]["API_TOKEN"], "placeholder-not-a-secret")
            self.assertFalse(seen.get("secrets"))
            unset = {k: v for k, v in os.environ.items() if k != "API_TOKEN"}
            refused = subprocess.run(["docker", "compose", "-f", str(path), "config", "--quiet"], env=unset,
                                     capture_output=True, text=True, timeout=120, check=False)
            self.assertNotEqual(refused.returncode, 0)                    # no value: compose will not start it

    def test_FR_PT3_AC_2_nothing_is_rendered_from_a_package_with_a_secret_value_or_without_a_pack(self):
        pkg, _ = deploy_package(self.project, build_pack(self.project))
        leaky = json.loads(json.dumps(pkg))
        leaky["secrets"][0]["value"] = "s3cr3t-do-not-ship"
        out = roadmod.render_compose(leaky)
        self.assertIsNone(out["yaml"])
        self.assertTrue(any("carries a value" in p for p in out["problems"]), out["problems"])
        packless = dict(pkg, pack={})
        self.assertIn("the package names no capability pack by version and content_sha256",
                      roadmod.render_compose(packless)["problems"])
        model = roadmod.render_compose(pkg)["model"]
        model["services"]["app"]["environment"]["DB_PASSWORD"] = "hunter2"
        model["services"]["app"]["volumes"][1]["read_only"] = False
        problems = roadmod.validate_compose(model)
        self.assertTrue(any("DB_PASSWORD" in p for p in problems) and any("read-only" in p for p in problems))


class UnpushedTest(DockerReleaseCase):
    registry = None

    def test_FR_PT1_AC_2_an_unpushed_image_is_pinned_by_its_local_id_never_its_tag_and_says_why(self):
        self.assertEqual(self.out["state"], "done", self.out)
        self.assertFalse(any(c[1] == "push" for c in self.fake.calls))
        pack = build_pack(self.project)
        self.assertEqual(pack["pinned"]["artifacts"], {"team-docker": "sha256:" + "ab" * 32})
        self.assertIn("cannot pull it by digest", pack["pinned"]["not_by_digest"]["team-docker"])
        self.assertNotIn(f":{self.main()[:12]}", json.dumps(pack["pinned"]["artifacts"]))

    def test_FR_PT3_AC_2_an_image_not_pinned_by_digest_is_not_rendered_and_the_bundle_says_why(self):
        pkg, _ = deploy_package(self.project, build_pack(self.project))
        out = roadmod.render_compose(pkg)
        self.assertIsNone(out["yaml"])
        self.assertTrue(any("not pinned by digest" in p for p in out["problems"]), out["problems"])
        folder = export_bundle(self.project, self.tmp / "out", person="Ilkka", persona="it", which=nothing)
        self.assertFalse((folder / "compose.yaml").exists())
        site = json.loads((folder / "BUNDLE.json").read_text(encoding="utf-8"))["site"]
        self.assertIn("not pinned by digest", site["note"])


class SchemaAndVerifierTest(DockerReleaseCase):
    def bundle(self, out: str = "out", **kw) -> Path:
        with holding():
            return export_bundle(self.project, self.tmp / out, person="Kaisa", persona="compliance", **kw)

    def test_FR_PT4_AC_1_the_pack_bundle_status_and_deploy_package_conform_to_the_published_schemas(self):
        folder = self.bundle(which=nothing)
        names = sorted(p.name for p in SCHEMAS.glob("*.json"))
        self.assertEqual(names, sorted(verifier.SCHEMAS.values()))
        for name, schema_file in verifier.SCHEMAS.items():
            schema = json.loads((SCHEMAS / schema_file).read_text(encoding="utf-8"))
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertTrue(schema["$id"].startswith("urn:rihmasto:schema:"))
            doc = json.loads((folder / name).read_text(encoding="utf-8"))
            self.assertEqual(verifier.schema_problems(doc, schema), [], name)
        leaky = json.loads((folder / "deploy-package.json").read_text(encoding="utf-8"))
        leaky["secrets"][0]["value"] = "s3cr3t"
        schema = json.loads((SCHEMAS / "deploy-package.v2.schema.json").read_text(encoding="utf-8"))
        self.assertTrue(verifier.schema_problems(leaky, schema))                  # a value where a name stands
        pack_schema = json.loads((SCHEMAS / "capability-pack.v1.schema.json").read_text(encoding="utf-8"))
        unhashed = {k.split(".")[0] for k in pack_schema["x-rihmasto-unhashed"]}
        self.assertTrue(set(_UNHASHED) <= unhashed)
        self.assertIn("not RFC 8785", pack_schema["$comment"])
        self.assertIn("no floats", pack_schema["$comment"])
        pack = json.loads((folder / "capability-pack.json").read_text(encoding="utf-8"))
        hashed = {k: v for k, v in pack.items() if k not in _UNHASHED}
        self.assertNotRegex(canonical_json(hashed), r"[0-9]\.[0-9]+e?[0-9]*[,}\]]")  # no floats in what is hashed
        self.assertEqual(verifier.pack_sha256(pack), content_sha256(pack))     # the verifier hashes as the kernel

    def signed(self) -> tuple:
        """A signed bundle, the stand-in cosign, and the key the factory published (apart from the bundle)."""
        cosign = FakeCosign(self.tmp / "bin")
        with cosign.on_path():
            folder = self.bundle("signed", which=lambda name: str(cosign.exe) if name == "cosign" else None)
        return folder, cosign, cosign.published_key(self.tmp / "factory-cosign.pub")

    def tampered(self, folder: Path, name: str) -> Path:
        """A copy of the bundle with contract.json changed and SHA256SUMS written again to match it."""
        copy = self.tmp / name
        shutil.copytree(folder, copy)
        (copy / "contract.json").write_text('{"tampered": true}\n', encoding="utf-8", newline="\n")
        (copy / "SHA256SUMS").write_text(sums(copy), encoding="utf-8", newline="\n")
        return copy

    def check(self, folder: Path, *args: str, cosign: FakeCosign | None = None) -> tuple:
        """The verifier's command line on ``folder``: its exit code and its last line."""
        out = io.StringIO()
        found = (lambda name: str(cosign.exe) if name == "cosign" else None) if cosign else nothing
        with contextlib.redirect_stdout(out), mock.patch.object(verifier.shutil, "which", found):
            code = verifier.main([str(folder), "--at", "2026-11-22T12:00:00Z", *args])
        return code, out.getvalue().strip().splitlines()[-1]

    def test_FR_PT4_AC_2_the_verifier_passes_a_good_bundle_offline_and_says_how_far_the_signature_went(self):
        folder, cosign, published = self.signed()
        report = verifier.verify(folder, at=AT, schemas=SCHEMAS, cosign=str(cosign.exe), key=published)
        verdicts = {c["check"]: c["verdict"] for c in report["checks"]}
        self.assertEqual(verdicts, {
            "SHA256SUMS": "passed", "capability pack": "passed", "pack named alike": "passed", "status": "passed",
            "app files": "passed", "evidence manifest": "passed", "ledger chain": "passed",
            "statements": "not applicable", "schemas": "passed", "signature of SHA256SUMS": "verified",
            "signature of pack-status.json": "verified"}, report["checks"])
        self.assertEqual(report["verdict"], "passed")
        with mock.patch.object(verifier.shutil, "which", nothing):                    # the same bundle, no cosign
            report = verifier.verify(folder, at=AT, schemas=SCHEMAS, key=published)
        self.assertEqual(signature_line(report)["verdict"], "not verified: no verifier")
        self.assertEqual(report["verdict"], "not verified: no verifier")
        self.assertEqual(self.check(folder, "--key", published), (3, "verdict: not verified: no verifier"))

    def test_FR_PT4_AC_3_one_changed_byte_fails_the_verifier_and_names_the_file(self):
        folder = self.bundle(which=nothing)
        self.assertEqual(verifier.verify(folder, at=AT, schemas=SCHEMAS)["verdict"], "not signed")
        for name in ("contract.json", "compose.yaml", "evidence.zip"):
            tampered = self.tmp / f"tampered-{name}"
            shutil.copytree(folder, tampered)
            data = bytearray((tampered / name).read_bytes())
            data[len(data) // 2] ^= 0x01
            (tampered / name).write_bytes(bytes(data))
            report = verifier.verify(tampered, at=AT, schemas=SCHEMAS)
            self.assertEqual(report["verdict"], "failed", name)
            sums = next(c for c in report["checks"] if c["check"] == "SHA256SUMS")
            self.assertEqual((sums["verdict"], sums["detail"]), ("failed", f"{name} does not match its sha256"))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(verifier.main([str(self.tmp / "tampered-contract.json"), "--at", "2026-11-22T12:00:00Z"]), 2)
        self.assertIn("contract.json does not match its sha256", out.getvalue())

    def test_FR_PT4_AC_4_a_bundle_signed_again_with_another_key_is_never_trusted_through_its_own_cosign_pub(self):
        folder, cosign, published = self.signed()
        forged = self.tampered(folder, "re-signed")                  # changed, summed and signed again, key swapped
        cosign.run("sign-blob", "--yes", "--key", "another-key", "--bundle", str(forged / "SHA256SUMS.sigstore.json"),
                   str(forged / "SHA256SUMS"))
        cosign.run("public-key", "--key", "another-key", "--outfile", str(forged / "cosign.pub"))
        report = verifier.verify(forged, at=AT, schemas=SCHEMAS, cosign=str(cosign.exe))      # no --key
        self.assertEqual(signature_line(report)["verdict"], "not verified: no trusted key")
        self.assertNotIn("verified", [c["verdict"] for c in report["checks"]])
        self.assertEqual(report["verdict"], "not verified: no trusted key")
        self.assertEqual(self.check(forged, cosign=cosign), (3, "verdict: not verified: no trusted key"))
        report = verifier.verify(forged, at=AT, schemas=SCHEMAS, cosign=str(cosign.exe), key=published)
        self.assertEqual((signature_line(report)["verdict"], report["verdict"]), ("failed", "failed"))
        self.assertEqual(self.check(forged, "--key", published, cosign=cosign), (2, "verdict: failed"))
        self.assertEqual(self.check(folder, "--key", published, cosign=cosign), (0, "verdict: passed"))

    def test_FR_PT4_AC_5_a_signed_bundle_missing_a_signature_or_its_status_fails_and_a_key_expects_a_signature(self):
        folder, cosign, published = self.signed()
        forged = self.tmp / "forged-status"                           # forged valid until 2099, signature removed
        shutil.copytree(folder, forged)
        status = json.loads((forged / "pack-status.json").read_text(encoding="utf-8"))
        status.update(state="valid", reason="forged", expires_at="2099-01-01T00:00:00Z")
        (forged / "pack-status.json").write_text(json.dumps(status), encoding="utf-8")
        (forged / "pack-status.json.sigstore.json").unlink()
        for key in (None, published):
            report = verifier.verify(forged, at=AT, schemas=SCHEMAS, cosign=str(cosign.exe), key=key)
            line = next((c for c in report["checks"] if c["check"] == "signature of pack-status.json"), {})
            self.assertEqual((line.get("verdict"), report["verdict"]), ("failed", "failed"), key)
        removed = self.tmp / "status-removed"                          # the status and its signature both gone
        shutil.copytree(folder, removed)
        for name in ("pack-status.json", "pack-status.json.sigstore.json"):
            (removed / name).unlink()
        report = verifier.verify(removed, at=AT, schemas=SCHEMAS, cosign=str(cosign.exe), key=published)
        self.assertEqual(report["verdict"], "failed")
        self.assertIn("BUNDLE.json names pack-status.json", json.dumps(report["checks"]))
        stripped = self.tampered(folder, "stripped")                   # changed, summed again, its signature removed
        (stripped / "SHA256SUMS.sigstore.json").unlink()
        report = verifier.verify(stripped, at=AT, schemas=SCHEMAS, cosign=str(cosign.exe), key=published)
        self.assertIn("--key expects the factory's signature", signature_line(report)["detail"])
        self.assertEqual(self.check(stripped, "--key", published, cosign=cosign), (2, "verdict: failed"))
        self.assertEqual(self.check(stripped, cosign=cosign), (3, "verdict: not signed"))  # no key: never passed

    def test_FR_PT4_AC_6_a_bundle_not_verified_against_the_factory_key_never_reads_passed_and_exits_3(self):
        unsigned = self.bundle(which=nothing)
        self.assertEqual(self.check(unsigned), (3, "verdict: not signed"))
        self.assertEqual(verifier.verify(unsigned / "evidence.zip")["verdict"], "not signed")  # an evidence pack
        folder, cosign, published = self.signed()
        for args, found, said in (((), None, "not verified: no verifier"),
                                  (("--key", published), None, "not verified: no verifier"),
                                  ((), cosign, "not verified: no trusted key")):
            self.assertEqual(self.check(folder, *args, cosign=found), (3, f"verdict: {said}"))
        self.assertEqual(self.check(folder, "--key", published, cosign=cosign), (0, "verdict: passed"))


class SigningTest(DeliveryTestCase):
    maturity = "explore"

    def setUp(self):
        super().setUp()
        self.factory.paved_roads_path.unlink()
        deliver(self.project)

    def test_FR_PT2_AC_1_with_cosign_3_1_a_bundle_holds_a_sigstore_bundle_and_verify_blob_passes_offline(self):
        cosign = FakeCosign(self.tmp / "bin")
        with cosign.on_path():                                 # found on PATH, as installed: the kernel's own calls
            folder = export_bundle(self.project, self.tmp / "out", person="Kaisa", persona="compliance")
        signature = json.loads((folder / "signature.json").read_text(encoding="utf-8"))
        self.assertTrue(signature["signed"], signature)
        self.assertEqual((signature["file"], signature["signs"]), ("SHA256SUMS.sigstore.json", "SHA256SUMS"))
        self.assertEqual(signature["verification"], {"cosign.pub": "cosign.pub", "trusted_root.json": "trusted_root.json"})
        for name in ("SHA256SUMS.sigstore.json", "trusted_root.json", "cosign.pub"):
            self.assertTrue((folder / name).is_file(), name)
        self.assertFalse((folder / "SHA256SUMS.sig").exists())                     # no detached signature
        sign = next(c for c in cosign.calls() if c[0] == "sign-blob")
        self.assertIn("--tlog-upload=false", sign)                                  # offline: nothing is uploaded
        self.assertEqual(sign[sign.index("--key") + 1], "kms://example/keys/factory")  # a reference, never a key
        verify = [str(cosign.exe), "verify-blob", "--key", str(folder / "cosign.pub"), "--bundle",
                  str(folder / "SHA256SUMS.sigstore.json"), "--trusted-root", str(folder / "trusted_root.json"),
                  "--insecure-ignore-tlog=true", str(folder / "SHA256SUMS")]
        self.assertEqual(subprocess.run(verify, capture_output=True, timeout=120, check=False).returncode, 0)
        (folder / "SHA256SUMS").write_bytes((folder / "SHA256SUMS").read_bytes() + b"\n")
        self.assertNotEqual(subprocess.run(verify, capture_output=True, timeout=120, check=False).returncode, 0)

    def test_FR_PT2_AC_2_a_signed_bundle_checked_without_cosign_reads_not_verified_no_verifier(self):
        cosign = FakeCosign(self.tmp / "bin")
        with cosign.on_path(), holding():
            folder = export_bundle(self.project, self.tmp / "out", person="Kaisa", persona="compliance")
        published = cosign.published_key(self.tmp / "factory-cosign.pub")
        with mock.patch.object(verifier.shutil, "which", nothing):
            report = verifier.verify(folder, at=AT, key=published)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = verifier.main([str(folder), "--at", "2026-11-22T12:00:00Z", "--key", published])
        lines = [c for c in report["checks"] if c["check"].startswith("signature of")]
        self.assertEqual([c["verdict"] for c in lines], ["not verified: no verifier"] * 2)
        self.assertNotIn("verified", [c["verdict"] for c in report["checks"]])
        self.assertEqual(report["verdict"], "not verified: no verifier")            # never passed
        self.assertEqual((code, out.getvalue().strip().splitlines()[-1]), (3, "verdict: not verified: no verifier"))


def image_command(root: Path) -> list:
    """The command the product's image starts with (its Dockerfile's last CMD), run by this Python."""
    cmd = [line for line in (root / "Dockerfile").read_text(encoding="utf-8").splitlines() if line.startswith("CMD ")]
    return [sys.executable if word == "python3" else word for word in json.loads(cmd[-1][4:])]


def start_product(root: Path, **env_extra) -> tuple:
    """The product as its container starts it (the Dockerfile's CMD), from ``root``, on a loopback port."""
    port = roadmod.free_port()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("RIHMA_") and k not in ("DATA_DIR", "PORT", "HOST", "APP_VERSION", "TRAFFIC_LOG")}
    env.update(PORT=str(port), HOST="127.0.0.1", PYTHONDONTWRITEBYTECODE="1", APP_VERSION="guarded",
               RIHMA_PACK_STATUS_EVERY="0.2", **{k: str(v) for k, v in env_extra.items()})
    proc = subprocess.Popen(image_command(root), cwd=root, env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc, f"http://127.0.0.1:{port}"


def health(base: str) -> tuple:
    r = roadmod.http_request("GET", base + "/health", timeout=2.0)
    return r["status"], r["json"] if isinstance(r["json"], dict) else {}


def wait_for(base: str, status: int, saying: str = "", timeout: float = 20.0) -> dict:
    """/health's body once it answers ``status``, past the guard's first round (and with a reason
    holding ``saying``, when given)."""
    deadline, last = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        last = health(base)
        reasons = last[1].get("guard") or []
        if last[0] == status and not any(r.startswith("starting") for r in reasons) \
                and (not saying or any(saying in r for r in reasons)):
            return last[1]
        time.sleep(0.1)
    raise AssertionError(f"/health never answered {status} {saying!r}: last {last}")


class GuardTest(DeliveryTestCase):
    """The delivered product, started as a site starts its container: the pack and its status beside it."""

    maturity = "explore"

    def setUp(self):
        super().setUp()
        self.factory.paved_roads_path.unlink()
        deliver(self.project)
        rel = self.project.read("releases/1.json")
        self.checkout = self.project.dir / rel["artifacts"]["local-preview"]["checkout"]
        with holding():
            self.pack = build_pack(self.project)
        self.site = self.tmp / "site"
        self.site.mkdir()
        self.write("capability-pack.json", self.pack)
        self.write("pack-status.json", self.fresh(status_document(self.project, self.pack)))

    def write(self, name: str, doc: dict) -> None:
        (self.site / name).write_text(json.dumps(doc), encoding="utf-8")

    @staticmethod
    def fresh(doc: dict, **delta) -> dict:
        """The status as issued, expiring a day from the real now (the factory's clock is fixed)."""
        return dict(doc, expires_at=(datetime.now(UTC) + timedelta(**(delta or {"days": 1}))).isoformat())

    def product(self, name: str = "srv") -> Path:
        root = self.tmp / name
        shutil.copytree(self.checkout, root, ignore=shutil.ignore_patterns(".git"))
        return root

    def start(self, root: Path, **env) -> str:
        data = Path(tempfile.mkdtemp(prefix="guard-data-", dir=self.tmp))
        defaults = {"RIHMA_PACK": self.site / "capability-pack.json", "RIHMA_PACK_STATUS": self.site / "pack-status.json",
                    "RIHMA_PACK_SHA256": self.pack["content_sha256"], "DATA_DIR": data}
        self.proc, base = start_product(root, **{**defaults, **env})
        self.addCleanup(roadmod._terminate, self.proc)
        return base

    def stamped(self, state: str, hours: int, **extra) -> dict:
        """This pack's status, issued ``hours`` after the factory's clock, expiring a day from the real now."""
        doc = self.fresh(status_document(self.project, self.pack))
        issued = datetime.fromisoformat(doc["issued_at"].replace("Z", "+00:00")) + timedelta(hours=hours)
        return dict(doc, state=state, issued_at=issued.isoformat().replace("+00:00", "Z"), **extra)

    def holds(self, base: str, status: int, saying: str, seconds: float = 1.2) -> None:
        """/health answers ``status``, a reason holding ``saying``, through several of the guard's rounds."""
        wait_for(base, status, saying)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            code, body = health(base)
            self.assertEqual(code, status, body)
            self.assertTrue(any(saying in r for r in body.get("guard") or []), body)
            time.sleep(0.2)

    def test_FR_PT5_AC_4_a_withdrawal_seen_stays_through_a_missing_corrupt_older_or_newer_status_and_a_restart(self):
        data, root = Path(tempfile.mkdtemp(prefix="guard-data-", dir=self.tmp)), self.product()
        self.write("pack-status.json", self.stamped("valid", 0))
        base = self.start(root, DATA_DIR=data)
        wait_for(base, 200)
        self.write("pack-status.json", self.stamped("suspended", 1, reason="a criterion no longer holds"))
        wait_for(base, 503, "suspended")
        self.write("pack-status.json", self.stamped("valid", 0))         # issued before the newest seen: a replay
        self.holds(base, 503, "suspended")
        self.write("pack-status.json", self.stamped("valid", 2))         # issued after it: taken
        wait_for(base, 200)
        self.write("pack-status.json", self.stamped("withdrawn", 3, reason="recalled",
                                                    decided_by={"person": "Ilkka", "persona": "it", "at": "now"}))
        reason = "the pack is withdrawn: recalled (decided by Ilkka)"
        wait_for(base, 503, reason)
        (self.site / "pack-status.json").unlink()                        # the file removed
        self.holds(base, 503, reason)
        (self.site / "pack-status.json").write_text('{"format": "rihma.pack-st', encoding="utf-8")  # half written
        self.holds(base, 503, reason)
        self.write("pack-status.json", self.stamped("valid", 2))         # the older valid one replayed
        self.holds(base, 503, reason)
        self.write("pack-status.json", self.stamped("valid", 4))         # a newer valid one: a withdrawal is final
        self.holds(base, 503, reason)
        roadmod._terminate(self.proc)                                    # a restart, the old status beside it
        self.write("pack-status.json", self.stamped("valid", 2))
        self.holds(self.start(root, DATA_DIR=data), 503, reason)

    def test_FR_PT5_AC_5_the_image_starts_through_the_guard_so_an_app_server_that_starts_none_still_holds(self):
        root = self.product("edited")
        server = root / "app" / "server.py"
        text = server.read_text(encoding="utf-8").replace("    _start_guard()\n", "")  # a builder drops the guard
        server.write_text(text + "\n# changed by a builder cell\n", encoding="utf-8", newline="\n")
        app = {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted((root / "app").rglob("*"))
               if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
        edited = json.loads(json.dumps(self.pack))                       # the pack pins the edited files, as it would
        edited["pinned"]["app_files_sha256"] = tree_sha256(app)
        edited["content_sha256"] = content_sha256(edited)
        self.write("capability-pack.json", edited)
        self.write("pack-status.json", dict(self.fresh(status_document(self.project, edited)), state="withdrawn",
                                            reason="recalled"))
        base = self.start(root, RIHMA_PACK_SHA256=edited["content_sha256"])
        self.assertIn("the pack is withdrawn: recalled", wait_for(base, 503, "withdrawn")["guard"])
        self.assertEqual(image_command(root)[1:], ["factory/pack_guard.py"])   # the entrypoint is the guard
        self.assertFalse([p for p in WRITE_SCOPE if fnmatch.fnmatch("Dockerfile", p)])  # not a builder's to write
        self.assertNotIn("trees_note", self.pack["pinned"])              # the pack sees the guard wired
        work = self.tmp / "clone"                                        # factory/ is protected: an edit is seen
        _git(self.tmp, "clone", "-q", str(self.project.path("repo.git")), str(work))
        with open(work / "factory" / "pack_guard.py", "a", encoding="utf-8", newline="\n") as fh:
            fh.write("\n# changed\n")
        _git(work, *GIT_ID, "commit", "-q", "-am", "edit the guard")
        self.assertEqual(protected_paths(work, "origin/main", "HEAD"), ["factory/pack_guard.py"])

    def test_FR_PT5_AC_1_a_withdrawn_version_turns_health_to_503_with_the_reason_and_the_ledger_names_the_person(self):
        base = self.start(self.product())
        self.assertEqual(wait_for(base, 200)["pack"], self.pack["version"])
        home, pid = str(self.factory.home), self.project.pid
        with contextlib.redirect_stderr(io.StringIO()) as err:
            refused = cli(["--home", home, "pack", "withdraw", pid, "a reason", "--person", "Pekka",
                           "--persona", "developer"])
        self.assertEqual(refused, 2)
        self.assertIn("may not withdraw", err.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = cli(["--home", home, "pack", "withdraw", pid, "the supplier recalled the model", "--person",
                        "Ilkka", "--persona", "it"])
        self.assertEqual(code, 0)
        issued = json.loads(out.getvalue())
        self.assertEqual((issued["status"]["state"], issued["status"]["decided_by"]["person"]), ("withdrawn", "Ilkka"))
        self.assertIn("signed", issued["signature"])                   # signed only when cosign really signed
        logged = self.project.ledger().of_kind("pack_withdrawn")[-1]["event"]["payload"]
        self.assertEqual((logged["by"], logged["persona"], logged["version"]), ("Ilkka", "it", self.pack["version"]))
        self.write("pack-status.json", json.loads(Path(issued["file"]).read_text(encoding="utf-8")))
        reason = "the pack is withdrawn: the supplier recalled the model (decided by Ilkka)"
        self.assertIn(reason, wait_for(base, 503, "withdrawn")["guard"])  # when the guard next reads the status

    def test_FR_PT5_AC_2_an_edited_app_file_keeps_the_product_from_ever_becoming_ready(self):
        root = self.product()
        with open(root / "app" / "routes.py", "a", encoding="utf-8", newline="\n") as fh:
            fh.write("\n# edited after the pack was built\n")
        base = self.start(root)
        body = wait_for(base, 503, "app files")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:                             # several rounds of the guard: never ready
            status, body = health(base)
            self.assertEqual(status, 503, body)
            time.sleep(0.2)
        self.assertIn("the app files differ from those the pack pins", body["guard"])

    def test_FR_PT5_AC_3_health_turns_200_only_while_pack_trees_status_and_smoke_set_all_pass(self):
        base = self.start(self.product())
        self.assertEqual(wait_for(base, 200)["status"], "ok")
        self.write("pack-status.json", self.fresh(status_document(self.project, self.pack), days=-1))
        wait_for(base, 503, "expired")
        self.write("pack-status.json", self.fresh(dict(status_document(self.project, self.pack), version="9.9.9")))
        wait_for(base, 503, "the status document names another pack")
        self.write("pack-status.json", self.fresh(status_document(self.project, self.pack)))
        wait_for(base, 200)
        other = json.loads(json.dumps(self.pack))
        other["smoke"]["checks"][0]["expect_status"] = 418
        self.write("capability-pack.json", other)
        wait_for(base, 503, "the pack's content does not hash to its content_sha256")
        other["content_sha256"] = content_sha256(other)               # it hashes, but it is not the one named
        self.write("capability-pack.json", other)
        wait_for(base, 503, "RIHMA_PACK_SHA256")
        smoke = self.tmp / "smoke"                                     # that pack, named and valid: only its
        smoke.mkdir()                                                  # smoke check fails
        (smoke / "pack.json").write_text(json.dumps(other), encoding="utf-8")
        status = self.fresh(status_document(self.project, dict(other, acceptance=self.pack["acceptance"])))
        (smoke / "status.json").write_text(json.dumps(status), encoding="utf-8")
        smoked = self.start(self.product("smoked"), RIHMA_PACK=smoke / "pack.json",
                            RIHMA_PACK_STATUS=smoke / "status.json", RIHMA_PACK_SHA256=other["content_sha256"])
        self.assertEqual(wait_for(smoked, 503, "smoke")["guard"], ["smoke GET /static/product.css: 200, expected 418"])
        bare = self.start(self.product("bare"), RIHMA_PACK="")         # no pack beside it: the guard is off
        self.assertNotIn("pack", wait_for(bare, 200))
        image = (self.checkout / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY factory/pack_guard.py ./factory/pack_guard.py", image)


class GovernanceTest(DeliveryTestCase):
    maturity = "production"

    def test_FR_PT6_AC_1_the_gate_card_the_evidence_pack_and_the_bundle_mark_each_guarantee(self):
        out = self.ship()
        self.assertEqual(out["state"], "done", out)
        gate = self.canon.cards(state=None, kind="deploy_gate")[-1]
        card_map = gate["payload"]["governance"]
        self.assertEqual([g["guarantee"] for g in card_map], list(GUARANTEES))
        self.assertTrue(all(g["state"] in ("held", "partial", "lost") and g["why"] for g in card_map))
        self.assertIn("Governance there: pinning held", gate["body"])
        path = export_evidence(self.project, self.tmp / "evidence", person="Kaisa", persona="compliance")
        with zipfile.ZipFile(path) as z:
            shipped = json.loads(z.read("governance-map.json"))
            readme = z.read("README.md").decode("utf-8")
        self.assertEqual((shipped["target"], shipped["map"]), ("local-process", card_map))  # the same map
        self.assertIn("## Governance map", readme)
        folder = export_bundle(self.project, self.tmp / "out", person="Kaisa", persona="compliance", which=nothing)
        exported = json.loads((folder / "BUNDLE.json").read_text(encoding="utf-8"))["governance"]
        self.assertEqual([g["guarantee"] for g in exported], list(GUARANTEES))
        states = {g["guarantee"]: g["state"] for g in exported}
        self.assertEqual((states["revocation"], states["telemetry"]), ("lost", "lost"))  # no compose kit, no channel
        self.assertIn("## Governance", (folder / "README.md").read_text(encoding="utf-8"))

    def test_FR_PT6_AC_2_a_guarantee_resting_on_an_unverified_platform_is_never_held(self):
        pushed = {"azure": {"type": "image", "ref": f"acr.example/gf-x@{DIGEST}", "digest": DIGEST}}
        on_docker = {g["guarantee"]: g["state"] for g in governance_map("docker", pushed)}
        self.assertEqual((on_docker["pinning"], on_docker["evals"]), ("held", "held"))
        on_azure = governance_map("azure-containerapps", pushed)
        self.assertNotIn("held", [g["state"] for g in on_azure])
        self.assertTrue(all("UNVERIFIED" in g["why"] for g in on_azure if g["guarantee"] in ("pinning", "evals")))
        tagged = governance_map("compose", {"azure": {"type": "image", "ref": "acr.example/gf-x:abc"}}, signed=True,
                                guarded=True)
        self.assertEqual(tagged[0]["state"], "lost")                   # a movable tag keeps nothing pinned
        signed = {g["guarantee"]: g["state"] for g in governance_map("compose", pushed, signed=True, guarded=True)}
        self.assertEqual((signed["pinning"], signed["evals"], signed["telemetry"]), ("held", "held", "lost"))

    def test_FR_PT6_AC_3_the_staging_validation_card_carries_the_governance_map_as_the_deploy_gate_does(self):
        out = self.ship()
        self.assertEqual(out["state"], "done", out)
        for kind in ("validation", "deploy_gate"):
            card = self.canon.cards(state=None, kind=kind)[-1]
            self.assertEqual([g["guarantee"] for g in card["payload"]["governance"]], list(GUARANTEES), kind)
            self.assertTrue(all(g["state"] in ("held", "partial", "lost") for g in card["payload"]["governance"]))
            self.assertIn("Governance there: pinning held", card["body"], kind)


class DemoGovernanceTest(DeliveryTestCase):
    maturity = "demo"

    def test_FR_PT6_AC_3_the_demo_acceptance_card_carries_the_governance_map_of_the_demo_road(self):
        out = deliver(self.project)
        self.assertEqual(out["state"], "waiting", out)
        card = self.canon.get_card(out["waiting_on"])
        self.assertEqual(card["kind"], "approval")
        self.assertEqual([g["guarantee"] for g in card["payload"]["governance"]], list(GUARANTEES))
        self.assertIn("Governance there: pinning held", card["body"])


if __name__ == "__main__":
    unittest.main()
