"""The Google Drive connector against a Drive v3 stand-in on 127.0.0.1 (FR-GDR1-AC-1 to AC-4).

kernel/connectors_gdrive.py is the client a capability imports (as app/gdrive.py); kernel/gdrive_standin.py
answers as Drive does, checks the tokens it issued and the scopes they carry, and verifies a service
account's signed JWT with the public half of a test key made here. Nothing reaches Google.
"""

import base64
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from access_fakes import rsa_key  # noqa: E402

from kernel import connectors_gdrive as gd  # noqa: E402
from kernel import integration_decl, integration_standins  # noqa: E402
from kernel import roads as roadmod  # noqa: E402
from kernel.compile import gdrive_client_files  # noqa: E402
from kernel.gdrive_standin import DriveStandin, serving  # noqa: E402
from kernel.integration_bind import wire  # noqa: E402
from kernel.roads_gcp import GcpCloudRunRoad  # noqa: E402
from kernel.store import Factory, FixedClock  # noqa: E402

DECL = {"name": "recordings", "kind": "gdrive", "access": "read-write", "data_classes": ["confidential"],
        "credentials": [], "purpose": "reads new recordings and writes their transcripts"}
EMAIL = "transcriber@example-prod-123.iam.gserviceaccount.com"


def _der(tag: int, content: bytes) -> bytes:
    n = len(content)
    size = bytes([n]) if n < 128 else bytes([0x80 | ((n.bit_length() + 7) // 8)]) + n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([tag]) + size + content


def _int(x: int) -> bytes:
    return _der(0x02, x.to_bytes(x.bit_length() // 8 + 1, "big"))


def pkcs8(n: int, e: int, d: int) -> str:
    """A PKCS#8 PEM of a test RSA key, as a service account's JSON key holds one."""
    rsa = _der(0x30, b"".join(_int(x) for x in (0, n, e, d, 0, 0, 0, 0, 0)))
    alg = _der(0x30, _der(0x06, bytes.fromhex("2a864886f70d010101")) + _der(0x05, b""))
    body = base64.b64encode(_der(0x30, _int(0) + alg + _der(0x04, rsa))).decode()
    return "-----BEGIN PRIVATE KEY-----\n" + "\n".join(body[i:i + 64] for i in range(0, len(body), 64)) + \
        "\n-----END PRIVATE KEY-----\n"


class DriveCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-gdrive-"))
        self.addCleanup(roadmod.rmtree, self.tmp)
        self.drive = DriveStandin(require_auth=True)
        self.url = self.enterContext(serving(self.drive))
        self.host = self.url.removeprefix("http://")

    def client(self, access: str = "read-write") -> gd.Drive:
        return gd.Drive(self.url, access=access, metadata_host=self.host, backoff=0)

    def recordings(self, n: int, folder: str = "IN") -> list:
        return [self.drive.add(f"meeting-{i}.m4a", b"audio-%d" % i, parents=[folder], mime="audio/mp4")
                for i in range(n)]


class ListNewTest(DriveCase):
    def test_FR_GDR1_AC_1_list_new_reads_every_page_and_a_cursor_returns_only_what_arrived_since(self):
        made = self.recordings(7)
        self.drive.add("agenda.txt", "not audio", parents=["IN"], mime="text/plain")
        self.drive.add("other.m4a", b"x", parents=["ELSEWHERE"], mime="audio/mp4")
        self.drive.add("sub", b"", parents=["IN"], mime=gd.FOLDER_MIME)
        trashed = self.drive.add("deleted.m4a", b"x", parents=["IN"], mime="audio/mp4")
        trashed["trashed"] = True
        d = self.client("read")
        first = d.list_new("IN", None, page_size=3, mime_prefixes=("audio/",))
        self.assertEqual([f["name"] for f in first.files], [f["name"] for f in made])   # oldest first
        self.assertEqual(first.pages, 3)
        self.assertEqual(first.cursor, {"modified_after": made[-1]["modifiedTime"], "seen": [made[-1]["id"]]})
        again = d.list_new("IN", first.cursor, page_size=3, mime_prefixes=("audio/",))
        self.assertEqual((again.files, again.cursor), ([], first.cursor))      # nothing new: nothing twice
        same_second = self.drive.add("late.m4a", b"y", parents=["IN"], mime="audio/mp4",
                                     modified=made[-1]["modifiedTime"])        # arrived within the cursor's second
        newer = self.recordings(2)
        later = d.list_new("IN", first.cursor, page_size=2, mime_prefixes=("audio/",))
        self.assertEqual([f["id"] for f in later.files], [same_second["id"], newer[0]["id"], newer[1]["id"]])
        self.assertEqual(later.cursor["modified_after"], newer[1]["modifiedTime"])
        queries = [r for r in self.drive.requests if r["path"] == "/drive/v3/files"]
        self.assertTrue(queries)
        everything = d.list_new("IN")
        self.assertEqual(len(everything.files), 11)                          # every file but the folder and the bin
        with self.assertRaises(ValueError):
            d.list_new("IN' or name != '", None)                             # an id never reaches a query unchecked
        with self.assertRaises(ValueError):
            d.list_new("IN", {"modified_after": "yesterday"})


class TransferTest(DriveCase):
    def test_FR_GDR1_AC_2_download_upload_and_a_cursor_kept_in_drive_so_a_rerun_writes_nothing_twice(self):
        made = self.recordings(2)
        d = self.client()
        self.assertEqual(d.download(made[1]["id"]), b"audio-1")
        up = d.upload("OUT", "meeting-1.txt", "Hyvää huomenta.".encode("utf-8"), "text/plain")
        stored = self.drive.files[up["id"]]
        self.assertEqual((stored["name"], stored["parents"], stored["content"], stored["mimeType"]),
                         ("meeting-1.txt", ["OUT"], "Hyvää huomenta.".encode("utf-8"), "text/plain"))
        self.assertEqual([f["id"] for f in d.find("OUT", "meeting-1.txt")], [up["id"]])
        self.assertEqual(d.find("OUT", "meeting-2.txt"), [])
        self.assertIsNone(d.load_cursor("OUT"))
        batch = d.list_new("IN")
        d.save_cursor("OUT", batch.cursor)
        self.assertEqual(d.load_cursor("OUT"), batch.cursor)
        d.save_cursor("OUT", {"modified_after": batch.cursor["modified_after"], "seen": []})   # updated in place
        self.assertEqual(len(d.find("OUT", gd.CURSOR_FILE)), 1)
        with self.assertRaises(gd.DriveError) as caught:
            d.download("missing")
        self.assertEqual(caught.exception.status, 404)

    def test_FR_GDR1_AC_2_an_integration_declared_read_never_uploads_and_a_read_scope_cannot(self):
        d = self.client("read")
        before = len(self.drive.requests)
        with self.assertRaises(PermissionError):
            d.upload("OUT", "x.txt", b"x")
        self.assertEqual(len(self.drive.requests), before)                    # refused before any call
        token = self.drive.issue(gd.SCOPES["read"])
        sneaky = gd.Drive(self.url, access="read-write", token=token, backoff=0)
        with self.assertRaises(gd.DriveError) as caught:
            sneaky.upload("OUT", "x.txt", b"x")
        self.assertEqual(caught.exception.status, 403)                       # the scope says read
        self.assertEqual(self.drive.files, {})


class CredentialTest(DriveCase):
    def test_FR_GDR1_AC_3_a_token_by_name_a_service_account_key_or_the_metadata_server_with_the_drive_scopes(self):
        self.recordings(1)
        token = self.drive.issue(gd.SCOPES["read"])
        env = {"RECORDINGS_URL": self.url, "RECORDINGS_ACCESS": "read", "RECORDINGS_TOKEN": token}
        self.assertEqual(len(gd.Drive.from_env("recordings", env).list_new("IN").files), 1)
        n, e, d = rsa_key(seed=11, bits=1024)
        self.drive.public_key, self.drive.client_email = (n, e), EMAIL
        key = self.tmp / "key.json"
        key.write_text(json.dumps({"type": "service_account", "client_email": EMAIL, "private_key_id": "k1",
                                   "private_key": pkcs8(n, e, d), "token_uri": self.url + "/token"}), encoding="utf-8")
        env = {"RECORDINGS_URL": self.url, "RECORDINGS_ACCESS": "read-write", "RECORDINGS_KEY_FILE": str(key)}
        client = gd.Drive.from_env("recordings", env, backoff=0)
        self.assertEqual(client.upload("OUT", "t.txt", b"t")["name"], "t.txt")
        issued = [s for t, s in self.drive.tokens.items() if t != token]
        self.assertEqual(issued[-1], gd.SCOPES["read-write"])                 # the JWT asked for the declared scopes
        n2, e2, d2 = rsa_key(seed=12, bits=1024)
        key.write_text(json.dumps({"client_email": EMAIL, "private_key": pkcs8(n2, e2, d2),
                                   "token_uri": self.url + "/token"}), encoding="utf-8")
        with self.assertRaises(gd.DriveError) as caught:
            gd.Drive.from_env("recordings", env, backoff=0).list_new("IN")
        self.assertIn("Invalid JWT Signature", str(caught.exception))
        on_cloud = gd.Drive(self.url, access="read", metadata_host=self.host, backoff=0)   # no credential: the runtime's
        self.assertEqual(len(on_cloud.list_new("IN").files), 1)
        self.assertEqual(list(self.drive.tokens.values())[-1], gd.SCOPES["read"])
        self.assertTrue(any(r["path"].startswith("/computeMetadata/") for r in self.drive.requests))

    def test_FR_GDR1_AC_3_errors_name_the_call_and_status_never_a_token_or_content_and_nothing_is_printed(self):
        made = self.recordings(1)
        bad = gd.Drive(self.url, access="read", token="ya29.not-a-real-token-1234", backoff=0)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(gd.DriveError) as caught:
                bad.list_new("IN")
            d = self.client()
            self.drive.fail_next = [503]
            self.assertEqual(len(d.list_new("IN").files), 1)                  # retried once, then answered
            self.drive.fail_next = [500, 500, 500]
            with self.assertRaises(gd.DriveError) as down:
                d.download(made[0]["id"])
        self.assertEqual((caught.exception.status, caught.exception.call), (401, "list files"))
        self.assertNotIn("ya29.not-a-real-token", str(caught.exception))
        self.assertEqual(down.exception.status, 500)
        self.assertNotIn("audio-0", str(down.exception))
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
        source = Path(gd.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import logging", source)
        self.assertNotIn("print(", source)
        kept = json.dumps(self.drive.requests)                               # what reached Drive, as recorded
        self.assertFalse([t for t in [*self.drive.tokens, "ya29.not-a-real-token"] if t in kept])


class DeclaredTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-gdrive-decl-"))
        self.addCleanup(roadmod.rmtree, self.tmp)

    def contract(self, decl: dict) -> dict:
        d = integration_decl.normalize(decl, provenance="customer-confirmed", decided_by="owner")
        return {"requirements": [integration_decl.requirement(d)]}

    def test_FR_GDR1_AC_4_a_gdrive_declaration_is_known_to_the_spec_and_scaffolds_the_client_the_product_imports(self):
        self.assertEqual(integration_decl.check(DECL), [])
        self.assertIn("gdrive", integration_decl.guidance())
        self.assertIn("Google Drive", integration_decl.guidance())
        kind = next(k for k in integration_decl.kinds() if k["kind"] == "gdrive")
        self.assertEqual((kind["via"], kind["client"]), (["http"], "app/gdrive.py"))
        contract = self.contract(DECL)
        req = contract["requirements"][0]
        self.assertEqual(req["id"], "INT-RECORDINGS")
        self.assertIn("Google Drive v3 API", req["acceptance"][0]["when"])
        found, problems = integration_decl.from_contract(contract)
        self.assertEqual((problems, found[0]["kind"], found[0]["access"]), ([], "gdrive", "read-write"))
        files = gdrive_client_files(contract)
        self.assertEqual(files, {"app/gdrive.py": Path(gd.__file__).read_text(encoding="utf-8")})
        self.assertEqual(gdrive_client_files({"requirements": []}), {})
        (self.tmp / "app").mkdir()
        (self.tmp / "app" / "gdrive.py").write_text(files["app/gdrive.py"], encoding="utf-8")
        probe = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                                "import app.gdrive as g; print(g.Drive.__name__, sorted(g.SCOPES))", str(self.tmp)],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(probe.stdout.strip(), "Drive ['read', 'read-write']", probe.stderr)   # nothing from Rihmasto

    def test_FR_GDR1_AC_4_the_gate_runs_the_products_tests_against_a_drive_stand_in_and_catches_a_write(self):
        decl = dict(DECL, access="read")
        (self.tmp / "contract.json").write_text(json.dumps(self.contract(decl)), encoding="utf-8")
        (self.tmp / "tests" / "standins").mkdir(parents=True)
        (self.tmp / "tests" / "standins" / "recordings.json").write_text(json.dumps({"files": [
            {"name": "a.m4a", "parents": ["IN"], "content": "audio", "mimeType": "audio/mp4"}]}), encoding="utf-8")
        with integration_standins.running(self.tmp) as stand:
            self.assertEqual(stand.env["RECORDINGS_KIND"], "gdrive")
            client = gd.Drive.from_env("recordings", stand.env, metadata_host=stand.env["GCE_METADATA_HOST"], backoff=0)
            self.assertEqual([f["name"] for f in client.list_new("IN").files], ["a.m4a"])
            writer = gd.Drive(stand.env["RECORDINGS_URL"], access="read-write", token="t", backoff=0)
            writer.upload("IN", "b.txt", b"b")                               # the product wrote to a read integration
            report = stand.report()
        seen = report["standins"]["recordings"]
        self.assertEqual((seen["api"], seen["requests"]), ("gdrive", 2))
        contract = json.loads((self.tmp / "contract.json").read_text(encoding="utf-8"))
        signal = integration_standins.signal(contract, report)
        self.assertEqual(signal[0].verdict, "failed")
        self.assertIn("declared read and was written", json.dumps(signal[0].native))

    def test_FR_GDR1_AC_4_on_a_google_cloud_road_the_package_names_the_drive_settings_and_never_a_secret(self):
        from gcp_fakes import road

        factory = Factory(self.tmp / "home", clock=FixedClock())
        project = factory.new_project("Recording transcripts", mode="assume", maturity="production")
        r = GcpCloudRunRoad("gcp", road())
        rev = "fedcba9876543210fedcba9876543210fedcba98"
        pkg = r.package(project, env="production", slot="current", release=1, revision=rev,
                        artifact={"type": "image", "ref": r.image(project, rev)})
        decl = integration_decl.normalize(dict(DECL, credentials=["RECORDINGS_TOKEN"]), provenance="customer-confirmed")
        rel = {"integrations": {"production": {"recordings": {
            "state": "approved", "declaration": decl, "card": "C-0009", "pin": "ab" * 32, "by": "Jaana",
            "binding": {"endpoint": "https://www.googleapis.com",
                        "secrets": [{"name": "RECORDINGS_TOKEN", "ref": "sm:drive-token:latest"}]}}}}}
        wire(pkg, rel, "production")
        r.render(project, pkg)
        self.assertEqual(roadmod.validate_package(pkg), [])
        env = {e["name"]: e for e in pkg["rendered"]["model"]["spec"]["template"]["spec"]["containers"][0]["env"]}
        self.assertEqual(env["RECORDINGS_URL"]["value"], "https://www.googleapis.com")
        self.assertEqual(env["RECORDINGS_ACCESS"]["value"], "read-write")
        self.assertEqual(env["RECORDINGS_TOKEN"]["valueFrom"], {"secretKeyRef": {"name": "drive-token", "key": "latest"}})
        self.assertNotIn("value", env["RECORDINGS_TOKEN"])


if __name__ == "__main__":
    unittest.main()
