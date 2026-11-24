"""FR-V1-AC-7: asked how a project is doing, Ask Rihma answers from that project's records, without a model:
on the project's page, in English or Finnish, or with the project's cockpit link pasted in the question. A
"where is" question still gets the map. (The owner, 2026-11-24, asked "Whats the status of this project" on
a project's page and got the Projects page instead.)"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_assistant import Seeded  # noqa: E402

from kernel.assistant import ask  # noqa: E402
from kernel.assistant_status import asks_status, project_in  # noqa: E402


class StatusQuestionTest(Seeded):
    def test_FR_V1_AC_7_how_a_project_is_doing_is_answered_from_its_records_not_the_map(self):
        before = self.records()
        title = self.p.meta["title"]
        for question in ("Whats the status of this project", "How is it going?", "What is it waiting for?",
                         "missä mennään?", "Mikä on tämän projektin tilanne?"):
            with self.subTest(question=question):
                said = ask(self.factory, question, persona="business_owner", project_id=self.p.pid)
                self.assertTrue(said["answer"].startswith(title + ":"), said["answer"])
                self.assertIn("Health:", said["answer"])
                self.assertTrue(said["navigate"]["route"].startswith(f"#/p/{self.p.pid}/"), said["navigate"])
        link = f"No but I am asking about this project http://127.0.0.1:8802/#/p/{self.p.pid}/inbox"
        said = ask(self.factory, link, persona="business_owner")                  # no project open: the link names it
        self.assertTrue(said["answer"].startswith(title + ":"), said["answer"])
        self.assertEqual(project_in(link, self.factory), self.p.pid)
        self.assertIsNone(project_in("http://127.0.0.1:8802/#/p/no-such-project", self.factory))
        where = ask(self.factory, "Where is the inbox?", persona="business_owner", project_id=self.p.pid)
        self.assertEqual(where["navigate"]["route"], f"#/p/{self.p.pid}/inbox")   # a where-question keeps the map
        self.assertEqual(ask(self.factory, "Where do I see all projects?", persona="business_owner")["navigate"]["route"],
                         "#/projects")
        self.assertFalse(asks_status("Where is the inbox?"))
        self.assertEqual(self.records(), before)                                  # asking records nothing


if __name__ == "__main__":
    unittest.main()
