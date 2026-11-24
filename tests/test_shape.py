"""FR-SHP1: Shape it in chat (D-0022). A person works out what is needed with Rihma, in conversation.

The owner: "the platform provides also the mode that user can just open a chat and maybe give a file ...
figure out the specs with Rihmasto".

Rihma is a scripted model: it answers from what the person has said so far, with one or two questions and the
draft it would keep. Intake after "Create the project from this" uses the shared scripted panel.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase  # noqa: E402
from factory_fakes import script as panel_script  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import shape as kshape  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.input_summary import summary  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.model import FakeModel, ModelError  # noqa: E402
from kernel.store import Factory  # noqa: E402

NEED = "Our team keeps losing track of who borrowed the drills and laptops."
NOTES = "# Notes from the team meeting\n\nThe tool store is open on weekdays. Loans are written on paper today.\n"


def rihma(prompt: str, role: str) -> str:
    """Rihma as a script: the draft grows with what the person said; questions until it is good enough."""
    if "You are Rihma, the analyst" not in prompt:
        return panel_script(prompt, role)
    said = " ".join(re.findall(r"^Person: (.*)$", prompt, re.M)).lower()
    draft = {"title": "Equipment loans", "problem": "Nobody knows who has borrowed the drills and laptops."}
    if "weekdays" in prompt:
        draft["constraints"] = ["The tool store is open on weekdays."]
    if "team members" in said:
        draft["for_whom"] = "The team members who borrow tools, and the tool store keeper."
        draft["outcomes"] = ["Every loan is known: who has what, since when."]
        draft["scope_in"] = ["Lend an item", "Return an item", "See what is out"]
        draft["scope_out"] = ["Billing"]
    if "sensitive" in said:
        draft["open_questions"] = ["Is the borrowers' data sensitive: are names enough?"]
    ready = "for_whom" in draft
    reply = "That is enough to start: create the project when you are ready." if ready else \
        "Who borrows the tools, and who looks after them?"
    return "```json\n" + json.dumps({"reply": reply, "draft": draft, "ready": ready,
                                     "ready_why": "who, problem, outcome and scope are there" if ready else
                                     "it does not say who it is for yet",
                                     "suggest": {"profile": "web_service", "mode": "assume", "maturity": "explore",
                                                 "why": "a small internal tool to try quickly"}}) + "\n```"


def docx(paragraphs: list) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


class ShapeKernelTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.model = FakeModel(rihma)

    def turn(self, sid: str, text: str) -> dict:
        kshape.say(self.factory, sid, text, person="Aino Example", persona="business_owner")
        return kshape.answer(self.factory, sid, self.model)

    def kinds(self) -> list:
        return [r["event"]["kind"] for r in factory_project(self.factory).ledger().records()
                if r["event"]["kind"].startswith("shape_")]

    def test_FR_SHP1_AC_1_a_person_starts_with_a_file_and_a_sentence_and_rihma_asks_and_keeps_a_draft(self):
        notes = self.tmp / "notes.md"
        notes.write_text(NOTES, encoding="utf-8")
        conv = kshape.start(self.factory, person="Aino Example", persona="business_owner")
        self.assertEqual(conv["messages"][0]["from"], "rihma")                  # Rihma opens the conversation
        conv = kshape.attach(self.factory, conv["id"], path=str(notes), person="Aino Example",
                             persona="business_owner", pending=False)
        conv = self.turn(conv["id"], NEED)
        role, prompt = self.model.calls[-1]
        self.assertEqual(role, "analyst")                                         # the analyst role answers
        self.assertIn("weekdays", prompt)                                         # Rihma read the attached file
        self.assertIn(NEED, prompt)
        self.assertIn("at most two questions", prompt)
        last = conv["messages"][-1]
        self.assertEqual((last["from"], last["text"]), ("rihma", "Who borrows the tools, and who looks after them?"))
        view = kshape.view(conv)
        self.assertEqual(view["draft"]["constraints"], ["The tool store is open on weekdays."])
        self.assertEqual(view["missing"], ["Who it is for", "Outcomes", "In scope"])
        self.assertFalse(view["good_enough"])
        conv = self.turn(conv["id"], "The team members borrow them; Pekka keeps the store.")
        view = kshape.view(conv)
        self.assertTrue(view["good_enough"] and view["ready"])                    # Rihma says it is good enough
        self.assertIn("create the project", view["messages"][-1]["text"])
        # kept under the factory home, the material as text beside it
        folder = self.factory.home / "_shape" / conv["id"]
        self.assertEqual(json.loads((folder / "shape.json").read_text(encoding="utf-8"))["id"], conv["id"])
        self.assertIn("weekdays", (folder / "files" / "01.txt").read_text(encoding="utf-8"))
        self.assertEqual(self.kinds(), ["shape_started", "shape_attached", "shape_said", "shape_said"])
        said = [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind("shape_said")]
        self.assertEqual(said[0]["person"], "Aino Example")
        self.assertNotIn(NEED, json.dumps(said))                                  # the words stay in the conversation

    def test_FR_SHP1_AC_2_the_person_edits_the_draft_and_rihma_leaves_their_words_as_they_are(self):
        conv = kshape.start(self.factory, person="Aino Example", persona="business_owner")
        self.turn(conv["id"], NEED)
        conv = kshape.edit_draft(self.factory, conv["id"], {"problem": "Drills go missing every month.",
                                                            "scope_out": ["Billing", "Repairs"]},
                                 person="Aino Example", persona="business_owner")
        self.assertEqual(set(conv["edited"]), {"problem", "scope_out"})
        conv = self.turn(conv["id"], "The team members borrow them.")
        self.assertEqual(conv["draft"]["problem"], "Drills go missing every month.")   # theirs, not Rihma's
        self.assertEqual(conv["draft"]["scope_out"], ["Billing", "Repairs"])
        self.assertEqual(conv["draft"]["outcomes"], ["Every loan is known: who has what, since when."])
        _, prompt = self.model.calls[-1]
        self.assertIn("Fields the person edited: problem, scope_out", prompt)
        edited = factory_project(self.factory).ledger().of_kind("shape_draft_edited")[-1]["event"]["payload"]
        self.assertEqual((edited["person"], edited["fields"]), ("Aino Example", ["problem", "scope_out"]))
        with self.assertRaisesRegex(ValueError, "the draft's fields are"):
            kshape.edit_draft(self.factory, conv["id"], {"budget": "1"}, person="Aino Example", persona="it")

    def test_FR_SHP1_AC_3_with_no_model_the_chat_says_so_and_points_at_models_setup_and_keeps_the_words(self):
        conv = kshape.start(self.factory, person="Aino Example", persona="business_owner")
        kshape.say(self.factory, conv["id"], NEED, person="Aino Example", persona="business_owner")
        conv = kshape.answer(self.factory, conv["id"], None)
        last = conv["messages"][-1]
        self.assertEqual((last["note"], last["link"]), ("no_model", "#/models"))
        self.assertIn("No model is set up", last["text"])
        self.assertEqual(conv["messages"][-2]["text"], NEED)
        self.assertFalse(conv["pending"])

        def broken(prompt, role):
            raise ModelError("gnomon task --role analyst exit 1: endpoint refused")
        kshape.say(self.factory, conv["id"], "again", person="Aino Example", persona="business_owner")
        conv = kshape.answer(self.factory, conv["id"], FakeModel(broken))
        self.assertEqual(conv["messages"][-1]["note"], "error")
        self.assertIn("endpoint refused", conv["messages"][-1]["text"])
        kshape.say(self.factory, conv["id"], "once more", person="Aino Example", persona="business_owner")
        conv = kshape.answer(self.factory, conv["id"], FakeModel(lambda p, r: "Plain words, no JSON."))
        self.assertEqual(conv["messages"][-1]["text"], "Plain words, no JSON.")   # said as it is, draft untouched
        with self.assertRaises(DecisionRefused):
            kshape.say(self.factory, conv["id"], "x", person="factory", persona="it")
        # a turn whose answer was lost (the cockpit stopped while Rihma answered) does not block the chat for ever
        kshape.say(self.factory, conv["id"], "are you there?", person="Aino Example", persona="business_owner")
        with self.assertRaisesRegex(ValueError, "still answering"):
            kshape.say(self.factory, conv["id"], "hello?", person="Aino Example", persona="business_owner")
        self.clock.advance(minutes=16)
        self.assertFalse(kshape.get(self.factory, conv["id"])["pending"])
        kshape.say(self.factory, conv["id"], "hello?", person="Aino Example", persona="business_owner")

    def test_FR_SHP1_AC_4_create_turns_the_draft_into_the_request_and_intake_never_asks_what_it_says(self):
        conv = kshape.start(self.factory, person="Aino Example", persona="business_owner")
        self.turn(conv["id"], NEED)
        self.turn(conv["id"], "The team members borrow them. Is the data sensitive?")
        out = kshape.create(self.factory, conv["id"], person="Aino Example", persona="business_owner", model=self.model,
                            maturity="demo")
        self.assertEqual((out["profile"], out["mode"], out["maturity"]), ("web_service", "assume", "demo"))
        p = self.factory.project(out["project"])
        self.assertEqual(p.meta["title"], "Equipment loans")
        request = p.read("source.json")["text"]
        self.assertIn("## Users and roles", request)
        self.assertIn("Every loan is known", request)
        self.assertIn("Is the borrowers' data sensitive", request)                # an open question stays a question
        s = summary(p)
        states = {f["facet"]: f["state"] for f in s["facets"]}
        for facet in ("users_roles", "outcomes", "scope"):
            self.assertEqual(states[facet], "given", facet)                       # never asked again
        self.assertNotEqual(states["data"], "given")
        asked = [q for q in Canon(p).questions() if q["id"] in {g["question"] for g in p.read("inputs.json")["gap_questions"]}]
        self.assertTrue(all(not set(s_["facets"]) & {"users_roles", "outcomes", "scope"}
                            for s_ in s["asked"] + s["assumed"] if s_["id"] in {q["id"] for q in asked}))
        kept = p.read("shape.json")
        self.assertEqual((kept["id"], kept["state"], kept["project"]), (conv["id"], "created", p.pid))
        self.assertEqual(p.ledger().of_kind("shaped_in_chat")[-1]["event"]["payload"]["shape"], conv["id"])
        created = factory_project(self.factory).ledger().of_kind("shape_created")[-1]["event"]["payload"]
        self.assertEqual((created["project"], created["person"], created["maturity"]), (p.pid, "Aino Example", "demo"))
        with self.assertRaisesRegex(ValueError, "already became project"):
            kshape.say(self.factory, conv["id"], "more", person="Aino Example", persona="business_owner")
        with self.assertRaisesRegex(ValueError, "already became project"):
            kshape.create(self.factory, conv["id"], person="Aino Example", persona="business_owner", model=self.model)

    def test_FR_SHP1_AC_5_a_conversation_is_kept_and_resumed_later(self):
        conv = kshape.start(self.factory, person="Aino Example", persona="business_owner")
        self.turn(conv["id"], NEED)
        again = Factory(self.factory.home, clock=self.clock)                      # later: another process
        listed = kshape.conversations(again)
        self.assertEqual([(c["id"], c["title"], c["messages"]) for c in listed], [(conv["id"], "Equipment loans", 3)])
        kshape.say(again, conv["id"], "The team members borrow them.", person="Aino Example", persona="business_owner")
        resumed = kshape.answer(again, conv["id"], self.model)
        self.assertEqual(len(resumed["messages"]), 5)
        self.assertTrue(kshape.view(resumed)["good_enough"])
        _, prompt = self.model.calls[-1]
        self.assertIn(NEED, prompt)                                               # Rihma remembers the start

    def test_FR_SHP1_AC_6_a_word_document_and_a_folder_are_read_and_a_pdf_is_asked_for_as_text(self):
        conv = kshape.start(self.factory, person="Aino Example", persona="business_owner")
        data = base64.b64encode(docx(["Loans are on paper.", "The store opens at eight."])).decode("ascii")
        conv = kshape.attach(self.factory, conv["id"], name="meeting.docx", data_base64=data, person="Aino Example",
                             persona="business_owner", pending=False)
        self.assertEqual(conv["attachments"][-1]["kind"], "file")
        folder = self.tmp / "specs"
        (folder / "docs").mkdir(parents=True)
        (folder / "README.md").write_text("# Loans\n\nA loan has a due date.\n", encoding="utf-8")
        (folder / "brief.md").write_text("Users: team members\n", encoding="utf-8")
        conv = kshape.attach(self.factory, conv["id"], path=str(folder), person="Aino Example", persona="business_owner",
                             pending=False)
        self.assertEqual((conv["attachments"][-1]["kind"], conv["attachments"][-1]["files"]), ("folder", ["README.md", "brief.md"]))
        text = kshape.prompt(self.factory, conv)
        self.assertIn("The store opens at eight.", text)
        self.assertIn("A loan has a due date.", text)
        for name, raw in (("scan.pdf", b"%PDF-1.7 ..."), ("photo.png", b"\x89PNG\r\n\x1a\n\x00\x00")):
            with self.assertRaisesRegex(ValueError, "paste its text"):
                kshape.attach(self.factory, conv["id"], name=name, data_base64=base64.b64encode(raw).decode("ascii"),
                              person="Aino Example", persona="business_owner")
        self.assertEqual(len(kshape.get(self.factory, conv["id"])["attachments"]), 2)   # a refusal attaches nothing

    def test_FR_SHP1_AC_7_the_command_line_shapes_creates_and_chats(self):
        def cli(*argv, stdin=""):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                    mock.patch("kernel.cli._model", return_value=self.model), mock.patch("builtins.input", side_effect=lines(stdin)):
                code = main(["--home", str(self.factory.home), *argv])
            return code, out.getvalue(), err.getvalue()

        def lines(text):
            items = text.splitlines()

            def read(_prompt=""):
                if not items:
                    raise EOFError
                return items.pop(0)
            return read

        who = ["--person", "Aino Example", "--persona", "business_owner"]
        code, out, err = cli("shape", "start", "--text", NEED, *who)
        self.assertEqual(code, 0, err)
        sid = json.loads(out)["id"]
        code, out, _ = cli("shape", "say", sid, "The team members borrow them.", *who)
        self.assertTrue(json.loads(out)["good_enough"])
        code, out, _ = cli("shape", "edit", sid, "scope_out", "Billing; Repairs", *who)
        self.assertEqual(json.loads(out)["draft"]["scope_out"], ["Billing", "Repairs"])
        code, out, _ = cli("shape", "show", sid, "--brief")
        self.assertIn("# Equipment loans", json.loads(out))
        code, out, _ = cli("shape", "show")
        self.assertEqual([c["id"] for c in json.loads(out)["conversations"]], [sid])
        code, out, err = cli("shape", "create", sid, "--mode", "mixed", *who)
        self.assertEqual(code, 0, err)
        self.assertEqual((json.loads(out)["mode"], json.loads(out)["shape"]), ("mixed", sid))
        # the interactive chat: a sentence, the draft, the answer, then the project
        code, out, err = cli("shape", *who, stdin=f"{NEED}\n/draft\nThe team members borrow them.\n/create\n")
        self.assertEqual(code, 0, err)
        self.assertIn("Rihma: Who borrows the tools", out)
        self.assertIn("Still needed: Who it is for, Outcomes, In scope", out)
        self.assertRegex(out, r"Project equipment-loans-\w+ is created")
        code, out, err = cli("shape", *who, stdin="hello\n/quit\n")
        self.assertIn("--resume SH-003", out)
        code, out, err = cli("shape", "--resume", "SH-003", *who, stdin="The team members borrow them.\n")
        self.assertIn("create the project when you are ready", out)
        code, _, err = cli("shape", "say", sid, "x", "--person", "factory", "--persona", "it")
        self.assertEqual(code, 2)
        self.assertIn("is not a person", err)


class ShapeCockpitTest(CockpitTestCase):
    def setUp(self):
        super().setUp()
        self.server.shape_model = FakeModel(rihma)

    def settled(self, sid: str) -> dict:
        end = time.monotonic() + 10
        while time.monotonic() < end:
            out = self.call("GET", f"/api/shape/{sid}")[1]
            if not out["shape"]["pending"]:
                return out["shape"]
            time.sleep(0.05)
        raise AssertionError(f"{sid} is still pending")

    def test_FR_SHP1_AC_8_the_cockpit_chat_answers_beside_the_request_and_creates_the_project_as_a_job(self):
        who = {"person": "Aino Example", "persona": "business_owner"}
        note = {"name": "notes.md", "data_base64": base64.b64encode(NOTES.encode("utf-8")).decode("ascii")}
        status, out, _ = self.call("POST", "/api/shape", {"text": NEED, "attach": note, **who})
        self.assertEqual(status, 201, out)
        sid = out["shape"]["id"]
        self.assertTrue(out["model"])
        conv = self.settled(sid)
        self.assertEqual([m["from"] for m in conv["messages"]], ["rihma", "person", "person", "rihma"])
        self.assertEqual(conv["draft"]["constraints"], ["The tool store is open on weekdays."])
        status, out, _ = self.call("PUT", f"/api/shape/{sid}/draft", {"draft": {"problem": "Drills go missing."}, **who})
        self.assertEqual((status, out["shape"]["edited"]["problem"]["by"]), (200, "Aino Example"))
        status, out, _ = self.call("POST", f"/api/shape/{sid}/say", {"text": "The team members borrow them.", **who})
        self.assertEqual(status, 200)
        conv = self.settled(sid)
        self.assertTrue(conv["good_enough"])
        self.assertEqual(conv["draft"]["problem"], "Drills go missing.")
        self.assertEqual(conv["suggestion"]["maturity"], "explore")
        status, listed, _ = self.call("GET", "/api/shape")
        self.assertEqual([c["id"] for c in listed["conversations"]], [sid])
        status, out, _ = self.call("POST", f"/api/shape/{sid}/create", {"profile": "web_service", "mode": "mixed",
                                                                        "maturity": "demo", **who})
        self.assertEqual(status, 201, out)
        pid = out["project"]["id"]
        self.assertEqual((out["shape"]["state"], out["shape"]["project"]), ("created", pid))
        job_args = self.runner.started[-1][1]
        self.assertEqual(job_args[:4], ["-m", "kernel.cli", "intake", pid])      # intake runs as a job, as New project's
        source = Path(job_args[job_args.index("--source-file") + 1]).read_text(encoding="utf-8")
        self.assertIn("## Users and roles", source)
        self.assertIn("Drills go missing.", source)
        p = self.factory.project(pid)
        self.assertEqual((p.meta["mode"], p.meta["maturity"], p.meta["profile"]), ("mixed", "demo", "web_service"))
        audit = [r["event"]["payload"] for r in p.ledger().of_kind("cockpit_write")]
        self.assertEqual(audit[0]["action"], "new_project")
        status, out, _ = self.call("POST", f"/api/shape/{sid}/say", {"text": "more", **who})
        self.assertEqual(status, 400)
        self.assertEqual(self.call("GET", "/api/shape/SH-999")[0], 404)

    def test_FR_SHP1_AC_8_without_a_model_the_cockpit_chat_says_so_at_once(self):
        self.server.shape_model = None
        who = {"person": "Aino Example", "persona": "business_owner"}
        status, out, _ = self.call("POST", "/api/shape", {"text": NEED, **who})
        self.assertEqual(status, 201)
        self.assertFalse(out["model"])
        last = out["shape"]["messages"][-1]
        self.assertEqual((last["note"], last["link"], out["shape"]["pending"]), ("no_model", "#/models", False))
        status, out, _ = self.call("POST", "/api/shape", {"text": NEED, "person": "factory", "persona": "it"})
        self.assertEqual(status, 403)


class AskRihmaTest(FactoryTestCase):
    def test_FR_SHP1_AC_9_ask_rihma_takes_a_person_to_shape_it_in_chat(self):
        from kernel.assistant import ask

        cases = {"I want to figure out the spec in a chat": {"route": "#/shape", "control": None},
                 "Where do I attach a file?": {"route": "#/shape", "control": "shape_attach"},
                 "How do I turn the chat into a project?": {"route": "#/shape", "control": "shape_create"},
                 "Where is the chat?": {"route": None, "control": "assistant"}}         # still the assistant's
        for question, where in cases.items():
            out = ask(self.factory, question, persona="business_owner")
            self.assertEqual(out["navigate"], where, question)
