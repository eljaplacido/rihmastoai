"""FR-MAT1-AC-6 and AC-7 in the cockpit: the folder preview route, and the scan's choices travelling with the
create and adopt requests (cockpit/server.py post_source_preview, post_project, post_adopt).

The preview reads local files, so it answers only a named person with a persona that may create or adopt a
project, and only for a folder under the home or a configured root; never a system folder or a folder of
keys. It records nothing.
"""

import hashlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import material_fixture as mf  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402
from test_material import LOCAL, SECRETS, SHIPPED, routing  # noqa: E402

from kernel.source_guard import ROOTS_ENV  # noqa: E402


def tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


class SourcePreviewTest(CockpitTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {ROOTS_ENV: str(self.tmp)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.folder = mf.build(self.tmp / "lobby")

    def preview(self, source, persona="product_owner", person="Aino", **more):
        return self.call("POST", "/api/source/preview", {"source": str(source), "person": person, "persona": persona,
                                                         **more})

    def test_FR_MAT1_AC_6_the_preview_shows_the_map_and_records_nothing(self):
        before = tree(self.factory.home) if self.factory.home.exists() else {}
        with routing(SHIPPED):
            status, body, _ = self.preview(self.folder, exclude=["slides/pilot-deck.pptx"])
        self.assertEqual(status, 200, body)
        rows = {r["path"]: r for r in body["map"]["files"]}
        self.assertEqual(rows["README.md"]["action"], "read")
        self.assertEqual(rows[".env"]["why"], "may hold secrets: never opened, by its name")
        self.assertEqual(rows["slides/pilot-deck.pptx"]["why"], "excluded by you (slides/pilot-deck.pptx)")
        self.assertEqual((body["git"], body["code"]), (False, True))
        self.assertEqual(body["send_to"], {"role": "analyst", "endpoint": "go", "host": "opencode.ai", "local": False})
        self.assertIn("the analyst role would go to the hosted endpoint", body["local_only"]["new"])
        for secret in SECRETS:
            self.assertNotIn(secret, str(body))
        self.assertEqual(tree(self.factory.home) if self.factory.home.exists() else {}, before)
        self.assertEqual(self.runner.started, [])

    def test_FR_MAT1_AC_6_the_preview_refuses_folders_outside_the_allowed_roots(self):
        for persona, person, why in (("end_user", "Aino", "may not have the cockpit read a folder"),
                                     ("product_owner", "factory", "not a person")):
            status, body, _ = self.preview(self.folder, persona=persona, person=person)
            self.assertEqual(status, 403, body)
            self.assertIn(why, body["error"])
        system = Path(os.environ.get("SYSTEMROOT", "/etc"))
        status, body, _ = self.preview(system)
        self.assertEqual(status, 403, body)
        self.assertIn("is a system folder", body["error"])
        keys = self.tmp / "me" / ".ssh"
        keys.mkdir(parents=True)
        status, body, _ = self.preview(keys)
        self.assertEqual(status, 403, body)
        self.assertIn("holds keys or credentials; it is never read", body["error"])
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        with mock.patch("kernel.source_guard.roots", return_value=[self.tmp / "lobby"]):
            status, body, _ = self.preview(elsewhere)
        self.assertEqual(status, 403, body)
        self.assertIn("is outside your home folder and the roots in RIHMASTO_SOURCE_ROOTS", body["error"])
        status, body, _ = self.preview(self.tmp / "missing")
        self.assertEqual(status, 400, body)
        self.assertIn("is not a folder", body["error"])

    def test_FR_MAT1_AC_6_a_scanned_folder_becomes_the_request_without_the_files_the_person_unticked(self):
        with routing(LOCAL):
            status, body, _ = self.call("POST", "/api/projects", {
                "title": "Visitor register", "source": str(self.folder), "folder": True, "exclude": ["data/*"],
                "requested_by": "Aino", "persona": "business_owner", "confidential": True})
        self.assertEqual(status, 201, body)
        p = self.factory.project(body["project"]["id"])
        mp = p.read("material.json")
        self.assertEqual(mp["exclude"], ["data/*"])
        scanned = p.ledger().of_kind("material_scanned")[-1]["event"]["payload"]
        self.assertEqual((scanned["person"], scanned["confirmed"]), ("Aino", "in the cockpit's scan step"))
        self.assertTrue(p.meta["confidential"])
        _, args, _ = self.runner.started[-1]
        request = Path(args[args.index("--source-file") + 1]).read_text(encoding="utf-8")
        self.assertTrue(request.startswith("## README.md (brief or spec)"))
        self.assertNotIn("data/budget.xlsx", request)
        for secret in SECRETS:
            self.assertNotIn(secret, request)
        # adopting: the exclusions and the setting travel with the job
        status, body, _ = self.call("POST", "/api/adopt", {
            "title": "Lobby", "source": str(self.folder), "intent": "improve", "person": "Aino",
            "persona": "developer", "exclude": ["data/*", "slides/kickoff.odp"], "confidential": True})
        self.assertEqual(status, 201, body)
        _, args, _ = self.runner.started[-1]
        self.assertEqual([a for a in args if a.startswith("--exclude=")], ["--exclude=data/*",
                                                                           "--exclude=slides/kickoff.odp"])
        self.assertIn("--confidential", args)

    def test_FR_MAT1_AC_7_the_cockpit_refuses_a_confidential_request_before_anything_is_created(self):
        with routing(SHIPPED):
            status, body, _ = self.call("POST", "/api/projects", {
                "title": "Visitor register", "source": "A register of the visitors in the lobby.",
                "requested_by": "Aino", "persona": "business_owner", "confidential": True})
        self.assertEqual(status, 403, body)
        self.assertIn("the analyst role would go to the hosted endpoint 'go'", body["error"])
        self.assertIn("docs/guides/local-models.md", body["error"])
        self.assertEqual(self.factory.projects(), [])
        self.assertEqual(self.runner.started, [])


if __name__ == "__main__":
    unittest.main()
