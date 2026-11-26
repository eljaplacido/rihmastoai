"""Brief sections L (ledger and audit) and N (interfaces): FR-L2, FR-L3 and FR-N1, measured against what
the code does (task V-69).

Each test drives the real kernel, the real ledger files and the real cockpit server. What the brief
asks for and the code does not do is recorded in ``contract/deferred/ln.json`` and is never tested here:
signing a ledger head and anchoring it off this machine (FR-L3), state rebuilt from the ledger alone
(FR-L2), and a server-sent event stream (FR-N1).
"""

import hashlib
import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import agentops_fakes  # noqa: E402  (Agent operations, FR-AOP1)
import enforcement_fakes  # noqa: E402  (enforcement levels per environment, FR-ENF1)
import gnomon_fakes  # noqa: E402  (Gnomon's audits and the role evals, FR-EVL1)
import heal_fakes  # noqa: E402  (incidents, remedies, fixes and feedback, FR-HEAL1)
import neverlost_fakes  # noqa: E402  (decision triage and Gnomon's enforcement, FR-NVL1)
import hitl_fakes  # noqa: E402  (people in the loop, FR-HITL1)
import itops_fixture  # noqa: E402  (what IT checks, FR-ITO1)
import walkthrough_fakes  # noqa: E402  (walkthroughs, FR-WLK1)
from console_fakes import write_routes as console_writes  # noqa: E402  (FR-CON1, FR-CHK1)
from context_fakes import write_routes as context_writes  # noqa: E402  (FR-CTX1)
from destinations_fixture import write_routes as destination_writes  # noqa: E402  (FR-DST1)
from itdata_fixture import write_routes as itdata_writes  # noqa: E402  (integrations and data, FR-ITD1)
from factory_fakes import FactoryTestCase, isolated_routing, model  # noqa: E402
from gcp_fakes import SCHEDULE as GCP_SCHEDULE  # noqa: E402  (a Google Cloud road and a job's schedule, FR-GCP1)
from gcp_fakes import road as gcp_road  # noqa: E402
from test_cockpit import IDEA, CockpitTestCase  # noqa: E402

from cockpit import server as cockpit  # noqa: E402
from kernel.autonomy import set_cap  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.intake import intake  # noqa: E402
from kernel.learn import FACTORY_PID  # noqa: E402
from kernel.ledger import canonical_json, event_hash, verify  # noqa: E402
from kernel.ledgerstore import LedgerStore  # noqa: E402
from kernel.packs import build_pack  # noqa: E402
from kernel.projections import cell  # noqa: E402
from kernel.safestop import request_pause, resume  # noqa: E402
from kernel.signals import receive, triage  # noqa: E402
from kernel.spec import make_spec  # noqa: E402
from kernel.status import evidence, health, now, try_it  # noqa: E402
from kernel.store import write_json  # noqa: E402

NON_PERSON = "factory"     # kernel.people.NOT_A_PERSON: the factory is not a person


def tree(root: Path) -> dict:
    """Every file under ``root`` by its path, with the sha256 of its bytes."""
    root = Path(root)
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def changed(before: dict, after: dict) -> set:
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


def strings(value) -> set:
    """Every string value in a JSON value, however deep."""
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(strings(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(strings(v) for v in value)) if value else set()
    return set()


def rechain(records: list, seq: int, change) -> list:
    """The ledger rewritten from ``seq`` on, every hash recomputed: a chain consistent with itself."""
    out, prev = [], None
    for r in records:
        event = json.loads(canonical_json(r["event"]))
        if r["seq"] == seq:
            change(event)
        if r["seq"] < seq:
            out.append(json.loads(canonical_json(r)))
            prev = r["hash"]
            continue
        h = event_hash(r["seq"], event, prev)
        out.append({"seq": r["seq"], "event": event, "prev": prev, "hash": h})
        prev = h
    return out


def write_records(path: Path, records: list) -> None:
    path.write_text("".join(canonical_json(r) + "\n" for r in records), encoding="utf-8", newline="\n")


# -- FR-L2: only the kernel writes state, and only by appending a transition ------------------------------

class AppendOnlyTest(FactoryTestCase):
    def test_FR_L2_AC_1_the_ledger_file_only_grows_one_record_at_a_time_and_keeps_every_earlier_byte(self):
        store = LedgerStore(self.tmp / "one" / "ledger.jsonl", clock=self.clock)
        self.assertEqual(store.head(), {"seq": -1, "hash": None})
        before, prev = b"", None
        for i in range(6):
            record = store.append("step", {"n": i})
            now = store.path.read_bytes()
            self.assertTrue(now.startswith(before), i)                       # nothing earlier was rewritten
            added = now[len(before):]
            self.assertEqual(added.count(b"\n"), 1, i)                       # exactly one new line
            self.assertTrue(added.endswith(b"\n"))
            self.assertEqual(json.loads(added), record)                      # the line is the stored record
            self.assertEqual((record["seq"], record["prev"]), (i, prev))     # it follows the last one
            self.assertEqual(store.head(), {"seq": i, "hash": record["hash"]})
            before, prev = now, record["hash"]
        self.assertTrue(store.verify(head=store.head()).intact)
        # the store offers no way to change or remove a record, only to add one and read
        self.assertEqual({m for m in dir(LedgerStore) if not m.startswith("_")},
                         {"append", "head", "of_kind", "records", "verify"})

    def test_FR_L2_AC_1_writers_appending_at_once_never_share_a_sequence_number(self):
        path = self.tmp / "shared" / "ledger.jsonl"
        writers, each = 4, 10
        start = threading.Barrier(writers)
        errors = []

        def write(w):
            store = LedgerStore(path)                                        # each writer its own store
            try:
                start.wait(10)
                for i in range(each):
                    store.append("step", {"writer": w, "n": i})
            except Exception as exc:  # noqa: BLE001 - reported below, never swallowed
                errors.append(repr(exc))

        threads = [threading.Thread(target=write, args=(w,)) for w in range(writers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(120)
        self.assertEqual(errors, [])
        records = LedgerStore(path).records()
        self.assertEqual([r["seq"] for r in records], list(range(writers * each)))
        self.assertTrue(verify(records).intact)
        got = [(r["event"]["payload"]["writer"], r["event"]["payload"]["n"]) for r in records]
        self.assertEqual(sorted(got), sorted((w, i) for w in range(writers) for i in range(each)))
        for w in range(writers):                                             # each writer's own order kept
            self.assertEqual([n for x, n in got if x == w], list(range(each)))


class TransitionTest(FactoryTestCase):
    def transition(self, p, kind: str, person, fn):
        """Run one kernel call; it must change the project's state and append its transition."""
        before, ledger_before = tree(p.dir), p.path("ledger.jsonl").read_bytes()
        n = len(p.ledger().records())
        out = fn()
        diff = changed(before, tree(p.dir))
        self.assertIn("ledger.jsonl", diff, kind)                            # a transition was appended
        self.assertTrue(diff - {"ledger.jsonl", "ledger.jsonl.lock"}, kind)  # and the state changed with it
        self.assertTrue(p.path("ledger.jsonl").read_bytes().startswith(ledger_before), kind)
        new = p.ledger().records()[n:]
        mine = [r["event"]["payload"] for r in new if r["event"]["kind"] == kind]
        self.assertTrue(mine, (kind, [r["event"]["kind"] for r in new]))
        if person is not None:                                               # a person's change names them
            self.assertTrue(any(person in strings(pl) for pl in mine), (kind, mine))
        self.assertTrue(p.ledger().verify().intact)
        return out

    def test_FR_L2_AC_2_each_state_change_appends_its_transition_and_a_refused_one_changes_nothing(self):
        p = self.new()
        first = p.ledger().records()[0]["event"]
        self.assertEqual((first["kind"], first["payload"]["id"]), ("project_created", p.pid))
        canon = Canon(p)
        t = self.transition
        t(p, "question_added", None, lambda: canon.add_question("Who approves a loan?", "business", blocking=True))
        t(p, "card_opened", None, lambda: canon.ask("Q-001"))
        t(p, "question_answered", "Aino",
          lambda: canon.answer("Q-001", "the team lead", person="Aino", persona="business_owner"))
        change = t(p, "card_opened", None,
                   lambda: canon.card("change", "Show overdue loans first", refs={"requirements": ["R-1"]}))
        t(p, "decision", "Olli", lambda: canon.decide(change["id"], "accept", person="Olli", persona="product_owner"))
        t(p, "comment", "Sanna", lambda: canon.comment({"kind": "requirement", "id": "R-1"}, "keep it short",
                                                       person="Sanna", persona="stakeholder"))
        t(p, "pause_requested", "Pekka", lambda: request_pause(p, person="Pekka", persona="developer", reason="audit"))
        t(p, "resumed", "Pekka", lambda: resume(p, person="Pekka", persona="developer"))
        t(p, "autonomy_cap_set", "Kaisa",
          lambda: set_cap(p, 2, person="Kaisa", persona="compliance", reason="answers only for now"))
        # a change the kernel refuses appends nothing and changes no file of the project
        open_card = canon.card("change", "Lend to other teams", refs={"requirements": ["R-2"]})
        canon.add_question("What availability is needed?", "operations")
        refused = [lambda: canon.decide(open_card["id"], "accept", person=NON_PERSON, persona="product_owner"),
                   lambda: canon.decide(open_card["id"], "accept", person="Dev", persona="developer"),
                   lambda: canon.answer("Q-002", "office hours", person="model", persona="operations"),
                   lambda: canon.comment({"kind": "requirement", "id": "R-1"}, "x", person="agent",
                                         persona="stakeholder"),
                   lambda: request_pause(p, person="llm", persona="developer"),
                   lambda: set_cap(p, 1, person="assistant", persona="compliance", reason="x")]
        for i, fn in enumerate(refused):
            before = tree(p.dir)
            with self.assertRaises(DecisionRefused, msg=i):
                fn()
            self.assertEqual(tree(p.dir), before, i)


# -- FR-L3: ledger heads kept outside the ledger, so a rewritten history shows -----------------------------

class KeptHeadTest(CockpitTestCase):
    def test_FR_L3_AC_1_the_cockpit_keeps_the_head_outside_the_project_and_a_rewritten_tail_shows_against_it(self):
        p = self.new()
        Canon(p).comment({"kind": "requirement", "id": "R-1"}, "first remark", person="Sanna", persona="stakeholder")
        status, view, _ = self.call("GET", f"/api/projects/{p.pid}")
        self.assertEqual(status, 200, view)
        self.assertTrue(view["ledger"]["intact"])
        heads = self.server.heads_path.resolve()
        self.assertTrue(heads.is_relative_to(self.factory.home.resolve()))
        self.assertFalse(heads.is_relative_to(p.dir.resolve()))              # not beside the ledger it checks
        kept = json.loads(heads.read_text(encoding="utf-8"))[p.pid]
        self.assertEqual(kept, p.ledger().head())
        # an honest append moves the kept head forward
        p.log("note", {"text": "a second remark"})
        view = self.call("GET", f"/api/projects/{p.pid}")[1]
        self.assertTrue(view["ledger"]["intact"])
        self.assertTrue(view["ledger"]["tail_checked"])
        self.assertEqual(view["ledger"]["kept_head"], kept)
        kept = json.loads(heads.read_text(encoding="utf-8"))[p.pid]
        self.assertEqual(kept, p.ledger().head())
        # the last record rewritten with a self-consistent hash: the chain alone cannot see it ...
        records = p.ledger().records()
        forged = rechain(records, kept["seq"], lambda e: e["payload"].update(text="rewritten"))
        write_records(p.path("ledger.jsonl"), forged)
        self.assertTrue(p.ledger().verify().intact)
        self.assertEqual(len(p.ledger().records()), len(records))
        # ... the kept head can, and the cockpit does not move its head onto the rewritten record
        view = self.call("GET", f"/api/projects/{p.pid}")[1]
        self.assertFalse(view["ledger"]["intact"])
        self.assertEqual(view["ledger"]["broken_seq"], kept["seq"])
        self.assertEqual(json.loads(heads.read_text(encoding="utf-8"))[p.pid], kept)


class PackHeadTest(FactoryTestCase):
    def release(self, p):
        write_json(p.path("releases", "1.json"), {"release": 1, "maturity": "demo", "state": "done",
                                                    "revision": "abc123", "steps": []})

    def test_FR_L3_AC_2_a_capability_pack_names_the_ledger_head_it_was_built_at_and_says_it_is_not_signed(self):
        p = self.new()
        Canon(p).comment({"kind": "requirement", "id": "R-1"}, "a remark", person="Sanna", persona="stakeholder")
        self.release(p)
        head = p.ledger().head()
        pack = build_pack(p)
        prov = pack["provenance"]
        self.assertEqual(prov["ledger_head"], head["hash"])
        self.assertIsNone(prov["signature"])                                  # what is not done is said
        self.assertEqual(prov["signature_note"], "not signed: no signer configured")
        self.assertEqual(p.read("releases/1/capability-pack.json")["provenance"]["ledger_head"], head["hash"])
        # the head the pack carries vouches for the history up to it ...
        records = p.ledger().records()
        anchor = {"seq": head["seq"], "hash": prov["ledger_head"]}
        self.assertTrue(verify(records, head=anchor).intact)
        # ... so a history rewritten from its start, consistent with itself, no longer holds that head
        forged = rechain(records, 0, lambda e: e["payload"].update(title="Another product"))
        self.assertTrue(verify(forged).intact)
        self.assertFalse(verify(forged, head=anchor).intact)
        self.assertNotIn(prov["ledger_head"], [r["hash"] for r in forged])
        # a later record moves the head a rebuilt pack names, never the pack's version or content
        p.log("note", {"text": "after the release"})
        again = build_pack(p)
        self.assertEqual((again["version"], again["content_sha256"]), (pack["version"], pack["content_sha256"]))
        self.assertEqual(again["provenance"]["ledger_head"], p.ledger().head()["hash"])
        self.assertNotEqual(again["provenance"]["ledger_head"], prov["ledger_head"])


# -- FR-N1: a factory API with read models; its writes are signed ------------------------------------------

# Write routes that record no state: a second sign-in link (kept in memory), the assistant (it proposes,
# kernel/assistant.py), the profile proposal (a rule over text), a folder's material map (kernel/material.py,
# read and shown, never kept) a settings change's preview (FR-CHG1), a posture's preview (kernel/posture.py)
# and a model's Test (kernel/models_setup.py). Adopting records its request,
# signed, before its job runs, so it is a signed write here.
RECORD_NOTHING = {"post_link", "post_assistant", "post_profile_propose", "post_source_preview",
                  "post_settings_preview", "post_model_test", "post_posture_preview", "post_automation_preview",
                  "post_automation_dry_run", "post_people_test_token",   # a token's test (FR-PPL1)
                  "post_source_scan", "post_source_scan_cancel",    # FR-RPJ1: a scan in the background reads only
                  "post_assessment_cancel",       # with nothing running it only says so; a real cancel is tested in test_progress
                  "post_pick_native", "post_pick_cancel"}  # FR-PICK1: the computer's own dialog and its cancellation
RECORD_NOTHING |= {"post_automation_compose"}   # Describe it: a draft, its summary and a dry run (FR-SET1)
RECORD_NOTHING |= {"post_enforcement_preview"}   # what a change of enforcement levels would do (FR-ENF1)
# An automation the write routes set (kernel/automations.py): a change proposal when a release is done.
AUTOMATION = {"name": "When a release is done", "trigger": {"kind": "event", "types": ["release_done"]},
              "action": {"kind": "change", "text": "{project} released: check the docs"}}
NOTES = {"name": "notes.md", "text": "The tool store is open on weekdays."}
MODEL = {"base_url": "http://127.0.0.1:9/v1", "model": "qwen3:32b"}   # set, never called
# The one write route that takes no person: it starts the pipeline as a job. Recorded as not built in
# contract/deferred/ln.json (FR-N1), so it is not exercised here.
UNSIGNED = {"post_advance"}
# The one read route that writes: the first build of a release's capability pack records its version.
# Recorded in contract/deferred/ln.json (FR-N1).
READ_THAT_WRITES = {"get_pack"}
LAYOUT = {"v": 1, "lens": "delivery",
          "widgets": [{"id": "gt", "type": "gate_trend", "size": "M", "view": "table", "filter": {}}]}


def alignment_writes(case) -> list:
    """The Alignment tab's writes (FR-ALN1), on a repository of the team's own attached for them: a scan, then a
    decision on the first item it proposed. Nothing is written to the repository."""
    from alignment_fixture import make_repo

    from kernel.attach import attach

    repo = case.tmp / "aligned-repo"
    if not (repo / ".git").exists():
        make_repo(repo)
    found = [p for p in case.factory.projects() if p.meta.get("title") == "Loans of the tool store"]
    pid = (found[0] if found else attach(case.factory, "Loans of the tool store", repo=repo, person="Aino Example",
                                         persona="developer")).pid
    return [
        ("post_repo_alignment_scan", "POST", f"/api/projects/{pid}/repo-alignment/scan",
         lambda who, got: {"person": who, "persona": "developer"}),
        ("post_repo_alignment_decide", "POST", f"/api/projects/{pid}/repo-alignment/decide",
         lambda who, got: {"items": [got["post_repo_alignment_scan"]["groups"][0]["items"][0]["id"]],
                           "verdict": "accept", "person": who, "persona": "product_owner"}),
    ]


class FactoryApiTest(CockpitTestCase):
    def world(self) -> dict:
        """A factory with something behind every route: a built project with a release, a project whose
        questions are all open, one whose plan waits on approval, a signal triaged into a concept."""
        built = self.built_project()                                        # assume mode: assumptions open
        write_json(built.path("releases", "1.json"), {"release": 1, "maturity": "demo", "state": "done",
                                                        "revision": "abc123", "steps": []})
        asking = self.intake_project(mode="socratic")                       # every question an open card
        planning = self.new(mode="assume", title="Room bookings")
        intake(planning, IDEA, model=model(), requested_by="Aino")
        make_spec(planning, model=model())                                  # a plan, not compiled
        change = Canon(built).card("change", "Show overdue loans first", refs={"requirements": ["R-1"]})
        s = receive(self.factory, "Warehouse staff need a way to report damaged pallets from a phone",
                    channel="meeting", source="ops weekly", person="Sanna")
        concept = triage(self.factory, s["id"])["routed_to"]["card"]
        # a coding agent's proposed answer in the asking project's channel, for a person to confirm (FR-BRG1)
        from kernel import agent_channel
        from kernel.agent_writes import propose_answer
        proposal = propose_answer(asking, agent_channel.agent("claude-code", "Aino", "developer"), "Q-003",
                                  "the team lead approves loans")["id"]
        return {"built": built, "asking": asking, "planning": planning, "change": change["id"], "concept": concept,
                "assumption": Canon(built).assumptions("open")[0]["id"], "proposal": proposal}

    def writes(self, w: dict) -> list:
        """Every signed write route, in an order where each one's target exists: (route name, method, path,
        body for a person). Paths may name what an earlier write made, through ``got``."""
        b, a, pl = w["built"].pid, w["asking"].pid, w["planning"].pid
        isolated_routing(self, self.tmp)                                     # Models setup writes a temp overlay

        def sid(got: dict) -> str:                                           # the conversation post_shape opened
            return got["post_shape"]["shape"]["id"]

        def aid(got: dict) -> str:                                           # the automation post_automation set
            return got["post_automation"]["automation"]["id"]
        repo = self.tmp / "adopt-source"                                     # an existing project to adopt
        if not (repo / ".git").exists():
            repo.mkdir(parents=True, exist_ok=True)
            (repo / "README.md").write_text("# Order tracker\n", encoding="utf-8")
            for cmd in (["init", "-q"], ["add", "-A"],
                        ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "x"]):
                subprocess.run(["git", *cmd], cwd=repo, check=True, capture_output=True)
        # the cockpit reads local folders only under home or an operator's root: the test's folder is one
        from unittest import mock

        from kernel.source_guard import ROOTS_ENV
        patcher = mock.patch.dict(os.environ, {ROOTS_ENV: str(self.tmp)})
        patcher.start()
        self.addCleanup(patcher.stop)
        # FR-HMD1: a fake Claude Code (tests/harness_fakes.py) for `post_models_use`; the real one never runs here
        from harness_fakes import fake_agent
        from runner_fakes import use as use_agent

        use_agent(self, "claude-code", fake_agent(self.tmp / "agents", "claude-code"))
        return [
            *console_writes(self, w),       # the console and the checks (tests/console_fakes.py; FR-CON1, FR-CHK1)
            *destination_writes(self, w),   # destinations and publishing (tests/destinations_fixture.py; FR-DST1)
            *itdata_writes(self, w),        # check, rotation reminder, turn off (tests/itdata_fixture.py; FR-ITD1)
            ("post_signal", "POST", "/api/signals",
             lambda who, got: {"text": "The loans page should show overdue loans first", "channel": "chat",
                               "person": who, "persona": "stakeholder"}),
            ("post_signal_triage", "POST", lambda got: f"/api/signals/{got['post_signal']['signal']['id']}/triage",
             lambda who, got: {"person": who, "persona": "stakeholder"}),
            ("post_concept_edit", "POST", f"/api/concepts/{w['concept']}/edit",
             lambda who, got: {"title": "Damaged pallet reports", "person": who, "persona": "business_owner"}),
            ("post_project", "POST", "/api/projects",
             lambda who, got: {"title": "Parking permits", "source": "We hand out parking permits by email.",
                               "requested_by": who, "persona": "business_owner"}),
            ("post_adopt", "POST", "/api/adopt",                       # an existing project, adopted as a job
             lambda who, got: {"title": "Order tracker", "source": str(repo), "intent": "maintain",
                               "person": who, "persona": "developer"}),
            ("post_decide", "POST", f"/api/projects/{b}/cards/{w['change']}/decide",
             lambda who, got: {"verdict": "accept", "reason": "worth it", "person": who, "persona": "product_owner"}),
            ("post_answer", "POST", f"/api/projects/{a}/questions/Q-001/answer",
             lambda who, got: {"text": "the team lead approves", "person": who, "persona": "business_owner"}),
            ("post_assume", "POST", f"/api/projects/{a}/questions/Q-002/assume",
             lambda who, got: {"person": who, "persona": "business_owner"}),
            ("post_settle", "POST", f"/api/projects/{b}/assumptions/{w['assumption']}/settle",
             lambda who, got: {"confirmed": True, "person": who, "persona": "product_owner"}),
            ("post_change", "POST", f"/api/projects/{b}/changes",
             lambda who, got: {"text": "Loans should have a due date", "person": who, "persona": "end_user"}),
            ("post_plan_requirement", "POST", f"/api/projects/{pl}/plan/requirements/R-1",
             lambda who, got: {"statement": "A team member can add an item with a name and a tag.",
                               "person": who, "persona": "product_owner"}),
            ("post_pause", "POST", f"/api/projects/{b}/pause",
             lambda who, got: {"reason": "audit week", "person": who, "persona": "developer"}),
            ("post_resume", "POST", f"/api/projects/{b}/resume",
             lambda who, got: {"person": who, "persona": "developer"}),
            # change anything set at creation, add material, go back a step (FR-CHG1)
            ("put_settings", "PUT", f"/api/projects/{pl}/settings",
             lambda who, got: {"title": "Room and desk bookings", "reason": "the desks too", "person": who,
                               "persona": "product_owner"}),
            ("post_material", "POST", f"/api/projects/{pl}/material",
             lambda who, got: {"text": "Desks are booked by the half day.", "note": "desks", "person": who,
                               "persona": "product_owner"}),
            ("post_rewind", "POST", f"/api/projects/{pl}/rewind",
             lambda who, got: {"to": "spec", "reason": "write it again with the desks", "person": who,
                               "persona": "product_owner"}),
            ("post_comment", "POST", f"/api/projects/{b}/comments",
             lambda who, got: {"target": {"kind": "requirement", "id": "R-1"}, "text": "keep the form short",
                               "person": who, "persona": "stakeholder"}),
            ("post_comment_promote", "POST",
             lambda got: f"/api/projects/{b}/comments/{got['post_comment']['comment']['id']}/promote",
             lambda who, got: {"person": who, "persona": "product_owner"}),
            ("put_autonomy", "PUT", "/api/autonomy",
             lambda who, got: {"level": 3, "reason": "trials only until the audit", "person": who,
                               "persona": "business_owner"}),
            ("put_project_autonomy", "PUT", f"/api/projects/{b}/autonomy",
             lambda who, got: {"level": 2, "reason": "answers and proposals", "person": who, "persona": "compliance"}),
            ("put_posture", "PUT", f"/api/projects/{b}/posture",
             lambda who, got: {"posture": "balanced", "reason": "a person says go", "person": who,
                               "persona": "business_owner"}),
            ("post_evidence_export", "POST", f"/api/projects/{b}/evidence",
             lambda who, got: {"person": who, "persona": "compliance"}),
            ("post_pack_build", "POST", f"/api/projects/{b}/pack/build",
             lambda who, got: {"person": who, "persona": "compliance"}),
            ("put_outputs", "PUT", f"/api/projects/{b}/outputs",     # outputs per audience (kernel/outputs.py)
             lambda who, got: {"targets": ["report"], "reason": "for the owner", "person": who,
                               "persona": "business_owner"}),
            ("post_outputs_build", "POST", f"/api/projects/{b}/outputs/build",
             lambda who, got: {"targets": ["report"], "person": who, "persona": "compliance"}),
            ("post_assessment", "POST", f"/api/projects/{b}/assessment",
             lambda who, got: {"person": who, "persona": "developer"}),
            ("post_assessment_changes", "POST", f"/api/projects/{b}/assessment/changes",
             lambda who, got: {"findings": ["F-1"], "person": who, "persona": "developer"}),
            ("post_embed", "POST", "/api/embeds",
             lambda who, got: {"kind": "feedback", "origins": ["https://shop.example"], "project": b,
                               "label": "Shop feedback", "person": who, "persona": "it"}),
            ("post_embed_revoke", "POST", lambda got: f"/api/embeds/{got['post_embed']['embed']['id']}/revoke",
             lambda who, got: {"person": who, "persona": "it"}),
            # autopilot, delegation and tracking (FR-AP2, FR-AP3)
            ("post_autopilot_start", "POST", f"/api/projects/{a}/autopilot",
             lambda who, got: {"kinds": ["question"], "until": "8h", "person": who, "persona": "developer"}),
            ("post_delegation_revoke", "POST", f"/api/projects/{a}/delegations/DL-001/revoke",
             lambda who, got: {"person": who, "persona": "business_owner"}),
            ("post_autopilot_stop", "POST", f"/api/projects/{a}/autopilot/stop",
             lambda who, got: {"person": who, "persona": "developer"}),
            ("put_tracking", "PUT", f"/api/projects/{a}/tracking",
             lambda who, got: {"checkpoints": [2], "person": who, "persona": "product_owner"}),
            ("post_checkpoint_look", "POST", f"/api/projects/{a}/checkpoints/2/look",
             lambda who, got: {"note": "seen", "person": who, "persona": "product_owner"}),
            ("put_modules", "PUT", "/api/modules",                      # every module stays on (kernel/modules.py)
             lambda who, got: {"preset": "full", "reason": "the whole factory", "person": who, "persona": "it"}),
            ("put_project_modules", "PUT", f"/api/projects/{b}/modules",     # every module on, the opt-in ones too
             lambda who, got: {"modules": list(cockpit.kmodules.MODULES), "person": who, "persona": "developer"}),
            ("put_layout", "PUT", "/api/layout?persona=developer&lens=delivery",
             lambda who, got: {"person": who, "layout": LAYOUT}),
            ("put_view_layouts", "PUT", "/api/view-layouts",               # Customize on every view (FR-UXO1)
             lambda who, got: {"person": who, "persona": "developer", "views": {"p:overview": {"hidden": ["brief"]}},
                               "tabs": {"hidden": ["review"], "pinned": []}}),
            # Shape it in chat (kernel/shape.py) and Models setup (kernel/models_setup.py), in the factory's ledger
            ("post_shape", "POST", "/api/shape",
             lambda who, got: {"text": "We lose track of borrowed drills", "person": who, "persona": "business_owner"}),
            ("post_shape_say", "POST", lambda got: f"/api/shape/{sid(got)}/say",
             lambda who, got: {"text": "The team members borrow them", "person": who, "persona": "business_owner"}),
            ("post_shape_attach", "POST", lambda got: f"/api/shape/{sid(got)}/attach",
             lambda who, got: {"attach": NOTES, "person": who, "persona": "business_owner"}),
            ("put_shape_draft", "PUT", lambda got: f"/api/shape/{sid(got)}/draft",
             lambda who, got: {"draft": {"for_whom": "team members", "problem": "drills go missing"}, "person": who,
                               "persona": "business_owner"}),
            ("post_shape_create", "POST", lambda got: f"/api/shape/{sid(got)}/create",
             lambda who, got: {"mode": "mixed", "maturity": "demo", "person": who, "persona": "business_owner"}),
            ("put_model", "PUT", "/api/models/assistant", lambda who, got: {**MODEL, "person": who, "persona": "it"}),
            ("post_model_remove", "POST", "/api/models/assistant/remove", lambda who, got: {"person": who, "persona": "it"}),
            # The coding agent you already have answers a text role (kernel/harness_setup.py, FR-HMD1)
            ("post_models_use", "POST", "/api/models/use",
             lambda who, got: {"harness": "claude-code", "roles": ["assistant"], "person": who, "persona": "it"}),
            # Settings > Runners (kernel/runners, D-0019): back to Gnomon applies at once, in the factory's ledger
            ("put_runner", "PUT", "/api/runners/builder", lambda who, got: {"runner": "gnomon", "person": who, "persona": "it"}),
            # automations (kernel/automations.py, FR-AUT1), in the factory's ledger and the project's
            ("post_automation", "POST", "/api/automations",
             lambda who, got: {"automation": AUTOMATION | {"scope": {"kind": "project", "projects": [b]}},
                               "person": who, "persona": "product_owner"}),
            ("put_automation", "PUT", lambda got: f"/api/automations/{aid(got)}",
             lambda who, got: {"automation": {"name": "When a release is done, again"}, "person": who,
                               "persona": "it"}),                       # IT, or the owner, changes one
            ("post_automation_run", "POST", lambda got: f"/api/automations/{aid(got)}/run",
             lambda who, got: {"person": who, "persona": "product_owner"}),
            ("post_automation_pause", "POST", lambda got: f"/api/automations/{aid(got)}/pause",
             lambda who, got: {"reason": "audit week", "person": who, "persona": "product_owner"}),
            ("post_automation_resume", "POST", lambda got: f"/api/automations/{aid(got)}/resume",
             lambda who, got: {"person": who, "persona": "it"}),
            ("post_automation_remove", "POST", lambda got: f"/api/automations/{aid(got)}/remove",
             lambda who, got: {"person": who, "persona": "it"}),
            ("put_project_tags", "PUT", f"/api/projects/{b}/tags",
             lambda who, got: {"tags": ["ops"], "person": who, "persona": "product_owner"}),
            # -- walkthroughs in Ask Rihma (FR-WLK1, tests/walkthrough_fakes.py): each step in the factory's ledger,
            # signed; Confirm is carried out by post_adopt
            *walkthrough_fakes.write_rows(self, repo),
            # a guided journey's own record, signed on the factory like a walkthrough (FR-JRN1)
            ("post_journey_guide", "POST", "/api/journeys/guide",
             lambda who, got: {"action": "start", "journey": "brownfield", "project": b, "person": who,
                               "persona": "developer"}),
            *alignment_writes(self),
            # since you last looked (FR-REV1): a reviewed mark on the merged task, all reviewed, the digest turned off
            ("post_review_mark", "POST", "/api/review/mark",
             lambda who, got: {"items": [f"{b}/task/T-001"], "person": who, "persona": "developer"}),
            ("post_review_done", "POST", "/api/review/done", lambda who, got: {"person": who, "persona": "developer"}),
            ("put_review_digest", "PUT", "/api/review/digest",
             lambda who, got: {"off": True, "person": who, "persona": "developer"}),
            # the paved roads (kernel/road_settings.py, FR-GCP1): IT configures a Google Cloud road, then a project's
            ("put_road", "PUT", "/api/roads/company-gcp",
             lambda who, got: {"road": gcp_road(), "maturity": ["production"], "person": who, "persona": "it"}),
            ("put_project_road", "PUT", f"/api/projects/{b}/road",
             lambda who, got: {"road": "company-gcp", "workload": "job", "schedule": GCP_SCHEDULE, "person": who,
                               "persona": "it"}),
            *FactoryApiTest.real_project_writes(self),       # test_access calls these writes on its own case
            *FactoryApiTest.bridge_writes(w),
            # the data and context layer (tests/context_fakes.py, FR-CTX1): a clean-up proposed and applied, signed
            *context_writes(self, w),
            *FactoryApiTest.graph_writes(w),
            *FactoryApiTest.setup_writes(self.factory, w),
            # agent observability (kernel/agentobs, FR-OBS1): IT sets the hub (nothing listens there), a developer
            # maps the project and records what the hub shows (here: that it did not answer)
            ("put_agent_observability", "PUT", "/api/agent-observability",
             lambda who, got: {"url": "http://127.0.0.1:9", "person": who, "persona": "it"}),
            ("post_agent_sessions_map", "POST", f"/api/projects/{b}/agent-sessions/map",
             lambda who, got: {"hub_project": "acme/checkout", "person": who, "persona": "developer"}),
            ("post_agent_sessions_snapshot", "POST", f"/api/projects/{b}/agent-sessions/snapshot",
             lambda who, got: {"person": who, "persona": "developer"}),
            # a developer's look at the development briefing (kernel/devsessions.py, FR-DEV1)
            ("post_dev_seen", "POST", f"/api/projects/{b}/dev/seen",
             lambda who, got: {"person": who, "persona": "developer"}),
            # a persona given to an agent by delegation (kernel/agent_personas.py, FR-PPL1)
            ("post_agent_persona", "POST", f"/api/projects/{b}/agent-personas",
             lambda who, got: {"persona": "operations", "agent": "ops-agent", "kinds": ["incident"], "until": "3d",
                               "person": who}),
            *gnomon_fakes.write_rows(self, w),     # Gnomon's audits and the role evals (FR-EVL1), as jobs
            *heal_fakes.write_routes(self, w),   # self-healing (tests/heal_fakes.py, FR-HEAL1)
            *neverlost_fakes.write_routes(self, w),   # decision triage and enforcement (FR-NVL1)
            *agentops_fakes.write_rows(self, w),   # Agent operations: the audit recorded, a change filed (FR-AOP1)
            *enforcement_fakes.write_rows(self, w),   # enforcement levels (tests/enforcement_fakes.py, FR-ENF1)
            *hitl_fakes.write_routes(self, w),   # people in the loop (tests/hitl_fakes.py, FR-HITL1)
            *itops_fixture.write_routes(self, w),   # what IT checks (tests/itops_fixture.py, FR-ITO1)
        ]

    @staticmethod
    def graph_writes(w: dict) -> list:
        """The Knowledge graph's saved views (cockpit/graph_routes.py, FR-GRV1): a person's own, kept as a layout is,
        in the cockpit's folder and never in a ledger."""
        b = w["built"].pid
        return [
            ("put_graph_prefs", "PUT", "/api/graph/prefs",
             lambda who, got: {"scope": b, "mode": "table", "presets": [{"name": "Open requirements and their tests",
                                                                         "query": "kinds=requirement,criterion,test&states=open"}],
                               "person": who, "persona": "developer"}),
        ]

    @staticmethod
    def setup_writes(factory, w: dict) -> list:
        """Set up a project, its suggested automations, archive, restore and remove (cockpit/setup_routes.py,
        FR-SET1), each signed: the set-up's one click sets the first suggestion, then one more is set and one
        dismissed on the built project; a spare copy is archived and removed, and one archived before is restored."""
        from kernel.automation_suggest import scan

        b = w["built"].pid
        spare = factory.new_project("A spare copy").pid
        shelved = factory.new_project("A shelved copy")
        shelved.update_meta(archived={"by": "Aino Example", "persona": "product_owner", "at": "2026-11-22T12:00:00Z"})

        def offered(got: dict) -> str:
            return next(s["id"] for s in scan(factory, b)["suggestions"] if s["state"] == "offered")
        return [
            ("post_project_setup", "POST", f"/api/projects/{b}/setup/automations",
             lambda who, got: {"person": who, "persona": "developer"}),
            ("post_suggestion_accept", "POST",
             lambda got: f"/api/projects/{b}/automation-suggestions/{offered(got)}/accept",
             lambda who, got: {"person": who, "persona": "developer"}),
            ("post_suggestion_dismiss", "POST",
             lambda got: f"/api/projects/{b}/automation-suggestions/{offered(got)}/dismiss",
             lambda who, got: {"person": who, "persona": "developer"}),
            ("post_project_archive", "POST", f"/api/projects/{spare}/archive",
             lambda who, got: {"reason": "a copy", "person": who, "persona": "product_owner"}),
            ("post_project_restore", "POST", f"/api/projects/{shelved.pid}/restore",
             lambda who, got: {"person": who, "persona": "product_owner"}),
            ("post_project_remove", "POST", f"/api/projects/{spare}/remove",
             lambda who, got: {"confirm": spare, "person": who, "persona": "product_owner"}),
        ]

    @staticmethod
    def people_writes(w: dict) -> list:
        """Settings > People and access (cockpit/people_routes.py, FR-PPL1), each signed by IT, in the factory's
        ledger. They run last and in this order: the last one turns team mode on, after which the solo session
        of this test signs nothing. With IT's access file in force they are refused (tests/test_people.py)."""
        from access_fakes import Provider

        b = w["built"].pid
        idp = {"preset": "oauth2-proxy", "issuer": "https://login.example.org", "origin": "https://rihmasto.example.org",
               "audience": "rihmasto-cockpit", "groups_claim": "groups"}
        it = {"persona": "it"}
        return [
            ("post_people_solo", "POST", "/api/people/solo", lambda who, got: {"person": who, "persona": "it"}),
            ("post_people_user", "POST", "/api/people/users",
             lambda who, got: {"name": "Bea Example", "personas": ["developer"], "person": who, **it}),
            ("put_people_user", "PUT", lambda got: f"/api/people/users/{got['post_people_user']['user']['id']}",
             lambda who, got: {"personas": ["developer", "operations"], "person": who, **it}),
            ("post_people_link", "POST", lambda got: f"/api/people/users/{got['post_people_user']['user']['id']}/link",
             lambda who, got: {"kind": "invite", "person": who, **it}),
            ("post_people_group", "POST", "/api/people/groups",
             lambda who, got: {"group": "0b8e5c1a-ops", "to": "operations", "person": who, **it}),
            ("post_people_role", "POST", "/api/people/roles",
             lambda who, got: {"project": b, "user": got["post_people_user"]["user"]["id"], "personas": ["product_owner"],
                               "person": who, **it}),
            ("put_people_views", "PUT", "/api/people/views",
             lambda who, got: {"to": "stakeholder", "hidden": ["insights_all"], "person": who, **it}),
            ("put_people_idp", "PUT", "/api/people/idp", lambda who, got: {"idp": idp, "person": who, **it}),
            ("post_people_keys", "POST", "/api/people/keys",
             lambda who, got: {"jwks": json.dumps(Provider("https://login.example.org", "rihmasto-cockpit").jwks()),
                               "person": who, **it}),
            ("post_people_mode", "POST", "/api/people/mode", lambda who, got: {"mode": "team", "person": who, **it}),
        ]

    @staticmethod
    def bridge_writes(w: dict) -> list:
        """The agent bridge and the agent channel (cockpit/bridge_routes.py; FR-BRG1, FR-CHN1), each signed."""
        b, a = w["built"].pid, w["asking"].pid
        return [
            ("post_handoff", "POST", f"/api/projects/{b}/handoff",
             lambda who, got: {"to": "claude-code", "via": "copy", "person": who, "persona": "developer"}),
            ("post_channel", "POST", f"/api/projects/{b}/channel",
             lambda who, got: {"text": "@analyst what does R-1-AC-1 mean?", "person": who, "persona": "developer"}),
            ("post_channel_settle", "POST", f"/api/projects/{a}/channel/{w['proposal']}/settle",
             lambda who, got: {"verdict": "confirm", "person": who, "persona": "business_owner"}),
            ("post_channel_pause", "POST", f"/api/projects/{b}/channel/pause",
             lambda who, got: {"reason": "a review", "person": who, "persona": "developer"}),
            ("post_channel_resume", "POST", f"/api/projects/{b}/channel/resume",
             lambda who, got: {"person": who, "persona": "developer"}),
        ]

    def real_project_writes(self) -> list:
        """FR-RPJ1's signed writes: the folders the cockpit may read, a local model for a confidential project's
        roles, and an adopted project's areas, watch and stated baseline (a game-like repository, adopted here)."""
        import rpj_fixture as fx

        from kernel.adopt import adopt

        game = next((p.pid for p in self.factory.projects() if p.meta.get("title") == "Isles"), None) or adopt(
            self.factory, "Isles", source=str(fx.game(self.tmp / "isles")), intent="monitor", person="Ida Example",
            persona="developer", suite_timeout=1).pid
        allowed = self.tmp / "allowed"
        allowed.mkdir(exist_ok=True)
        dev = lambda who, got: {"person": who, "persona": "developer"}          # noqa: E731
        return [("post_source_root", "POST", "/api/source/roots",
                 lambda who, got: {"folder": str(allowed), "confirm": True, "person": who, "persona": "it"}),
                ("post_source_root_remove", "POST", "/api/source/roots/remove",
                 lambda who, got: {"folder": str(allowed), "person": who, "persona": "it"}),
                ("post_pick_recent", "POST", "/api/pick/recent",            # FR-PICK1: kept outside every ledger
                 lambda who, got: {"path": str(allowed), "person": who, "persona": "developer"}),
                ("post_models_use_local", "POST", "/api/models/use-local",
                 lambda who, got: {"person": who, "persona": "it"}),
                ("post_areas", "POST", f"/api/projects/{game}/areas", dev),
                ("post_watch", "POST", f"/api/projects/{game}/watch", dev),
                ("post_baseline_stated", "POST", f"/api/projects/{game}/baseline/stated",
                 lambda who, got: {"command": "python tools/pipeline/check.py test", "confirm": True,
                                   **dev(who, got)})]

    def ledgers(self) -> dict:
        return {p.pid: p.ledger().records() for p in self.factory.projects()}

    def test_FR_N1_AC_2_every_write_that_records_state_is_signed_by_a_named_person(self):
        w = self.world()
        home = self.factory.home
        routes = [*self.writes(w), *FactoryApiTest.people_writes(w)]     # People and access last (FR-PPL1)
        every_write = {name for method, _, name in cockpit.ROUTES if method in ("POST", "PUT")}
        # every write route is accounted for: signed, recording nothing, or the one recorded gap
        self.assertEqual({r[0] for r in routes} | RECORD_NOTHING | UNSIGNED, every_write)
        self.assertEqual(len(routes), len({r[0] for r in routes}))
        got = {}
        for name, method, path, body in routes:
            path = path(got) if callable(path) else path
            person = f"Ida {name}"
            # the same request from a non-person is refused and leaves the factory home as it was
            before = tree(home)
            status, out, _ = self.call(method, path, body(NON_PERSON, got))
            self.assertEqual(status, 403, (name, out))
            self.assertEqual(tree(home), before, name)
            # from a named person it is taken, and the record of it carries that person
            ledgers = self.ledgers()
            status, out, _ = self.call(method, path, body(person, got))
            self.assertIn(status, (200, 201), (name, out))
            got[name] = out
            if name in ("put_layout", "put_graph_prefs"):     # a layout and saved graph views: outside every ledger
                folder = "layouts" if name == "put_layout" else "graph_views"
                saved = [json.loads(f.read_text(encoding="utf-8"))
                         for f in (home / "_cockpit" / folder).rglob("*.json")]
                self.assertEqual([s["person"] for s in saved], [person])
                self.assertEqual({k: len(v) for k, v in self.ledgers().items()},
                                 {k: len(v) for k, v in ledgers.items()})
                continue
            if name == "post_pick_recent":                 # a person's recent folders, kept outside every ledger
                kept = json.loads((home / "_walkthroughs" / "recent.json").read_text(encoding="utf-8"))
                self.assertIn(person, kept)
                self.assertEqual({k: len(v) for k, v in self.ledgers().items()},
                                 {k: len(v) for k, v in ledgers.items()})
                continue
            if name == "put_view_layouts":                            # so are a person's view layouts
                saved = [json.loads(f.read_text(encoding="utf-8"))
                         for f in (home / "_cockpit" / "view-layouts").glob("*.json")]
                self.assertEqual([s["person"] for s in saved], [person])
                self.assertEqual(saved[0]["views"], {"p:overview": {"order": [], "hidden": ["brief"], "size": {}}})
                self.assertEqual({k: len(v) for k, v in self.ledgers().items()},
                                 {k: len(v) for k, v in ledgers.items()})
                continue
            added = [r["event"] for pid, recs in self.ledgers().items() for r in recs[len(ledgers.get(pid, [])):]]
            self.assertTrue(added, name)
            self.assertTrue(any(person in strings(e["payload"]) for e in added), (name, added))
        for p in self.factory.projects():
            self.assertTrue(p.ledger().verify().intact, p.pid)

    def test_FR_N1_AC_2_the_writes_that_record_nothing_change_no_file(self):
        self.world()
        home = self.factory.home
        before = tree(home)
        status, out, _ = self.call("POST", "/api/links", {})
        self.assertEqual(status, 201, out)
        status, out, _ = self.call("POST", "/api/assistant", {"question": "What waits on me?", "persona": "developer",
                                                               "person": "Dev"})
        self.assertEqual(status, 200, out)
        status, out, _ = self.call("POST", "/api/profiles/propose", {"text": "Sync orders from SAP to our CRM"})
        self.assertEqual(status, 200, out)
        pl = next(p for p in self.factory.projects() if p.meta.get("title") == "Room bookings")
        status, out, _ = self.call("POST", f"/api/projects/{pl.pid}/settings/preview",
                                   {"kind": "integration", "maturity": "pilot", "person": "Dev", "persona": "developer"})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["rewind"], "questions")
        isolated_routing(self, self.tmp)                                     # the analyst's key is not set: no call
        status, out, _ = self.call("POST", "/api/models/analyst/test", {"person": "Ilkka", "persona": "it"})
        self.assertEqual((status, out["test"]["ok"]), (200, False), out)
        draft = AUTOMATION | {"scope": {"kind": "project", "projects": [pl.pid]}}
        status, out, _ = self.call("POST", "/api/automations/preview", {"automation": draft, "person": "Dev",
                                                                         "persona": "developer"})
        self.assertEqual((status, out["ok"]), (200, True), out)
        self.assertTrue(out["summary"].startswith("When a release is done, for project"), out)
        from unittest import mock

        from kernel.pick_native import PICK_ENV            # FR-PICK1: a stand-in for the computer's own dialog
        with mock.patch.dict(os.environ, {PICK_ENV: json.dumps([sys.executable, "-c", "print('picked')"])}):
            status, out, _ = self.call("POST", "/api/pick/native", {"kind": "folder", "person": "Dev",
                                                                     "persona": "developer"})
        self.assertEqual((status, out["picked"]["path"].endswith("picked")), (200, True), out)
        status, out, _ = self.call("POST", "/api/pick/native/cancel", {"person": "Dev", "persona": "developer"})
        self.assertEqual((status, out), (200, {"cancelled": False}))
        self.assertEqual(tree(home), before)

    def test_FR_N1_AC_1_every_read_model_answers_from_the_records_and_writes_nothing(self):
        w = self.world()
        b = w["built"]
        # some of everything for the reads to show: a comment, an embed, an export to download, a kept head
        self.call("POST", f"/api/projects/{b.pid}/comments", {"target": {"kind": "requirement", "id": "R-1"},
                                                              "text": "keep it short", "person": "Sanna",
                                                              "persona": "stakeholder"})
        self.call("POST", "/api/embeds", {"kind": "feedback", "origins": ["https://shop.example"], "project": b.pid,
                                          "label": "Shop feedback", "person": "Pekka", "persona": "it"})
        export = self.call("POST", f"/api/projects/{b.pid}/evidence", {"person": "Kaisa", "persona": "compliance"})[1]
        shaped = self.call("POST", "/api/shape", {"text": "Drills go missing", "person": "Aino",
                                                  "persona": "business_owner"})[1]["shape"]["id"]
        isolated_routing(self, self.tmp)
        walked = self.call("POST", "/api/walkthroughs", {"name": "tour", "person": "Aino",       # FR-WLK1
                                                         "persona": "developer"})[1]["walkthrough"]["id"]
        for p in self.factory.projects():
            self.call("GET", f"/api/projects/{p.pid}")
        home = self.factory.home
        before = tree(home)
        pids = [p.pid for p in self.factory.projects()]
        self.assertIn(FACTORY_PID, pids)
        query = "?persona=developer&person=Dev&lens=delivery&requirements=R-1&kind=requirement&id=R-1"
        reads = [(name, pattern) for method, pattern, name in cockpit.ROUTES if method == "GET"]
        self.assertGreaterEqual(len(reads), 30)
        answered = set()
        for name, pattern in reads:
            if name in READ_THAT_WRITES:
                continue
            template = pattern.pattern.removesuffix(r"/?\Z")
            if name == "get_export":
                paths = [export["download"]]
            elif name == "get_shape":
                paths = [f"/api/shape/{shaped}"]
            elif name == "get_walkthrough":                                  # FR-WLK1
                paths = [f"/api/walkthroughs/{walked}"]
            elif name == "get_source_scan":                     # a scan in the background (FR-RPJ1), as it runs
                from kernel.material import Progress

                self.server._rpj_scans = {"S-000000000000": {"id": "S-000000000000", "state": "running",
                                                             "progress": Progress(), "folder": "x"}}
                self.server._rpj_lock = threading.Lock()
                paths = ["/api/source/scan/S-000000000000"]
            elif cockpit.PID in template:
                paths = [template.replace(cockpit.PID, pid) for pid in pids]
            else:
                paths = [template]
            for path in paths:
                self.assertNotIn("(?P<", path, name)
                self.assertEqual(self.call("GET", path + query, token=None)[0], 401, path)   # behind the token
                status, out, _ = self.call("GET", path + query, raw=name == "get_export")
                self.assertEqual(status, 200, (path, out))
                self.assertIsNotNone(out, path)
                answered.add(name)
        self.assertEqual(answered, {name for name, _ in reads} - READ_THAT_WRITES)
        # nothing under the factory home changed: no ledger, no state file, no layout, no export
        self.assertEqual(tree(home), before)
        # and what they answer is the kernel's own read of the records
        for route, read in (("cell", cell), ("evidence", evidence), ("now", now), ("health", health),
                            ("try", try_it)):
            self.assertEqual(self.call("GET", f"/api/projects/{b.pid}/{route}")[1], self.as_json(read(b)), route)


if __name__ == "__main__":
    unittest.main()
