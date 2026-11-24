"""Brief sections L (ledger and audit) and N (interfaces): FR-L2, FR-L3 and FR-N1, measured against what
the code does (task V-69).

Each test drives the real kernel, the real ledger files and the real cockpit server. What the brief
asks for and the code does not do is recorded in ``contract/deferred/ln.json`` and is never tested here:
signing a ledger head and anchoring it off this machine (FR-L3), state rebuilt from the ledger alone
(FR-L2), and a server-sent event stream (FR-N1).
"""

import hashlib
import json
import subprocess
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model  # noqa: E402
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
# kernel/assistant.py) and the profile proposal (a rule over text).
RECORD_NOTHING = {"post_link", "post_assistant", "post_profile_propose"}
# The one write route that takes no person: it starts the pipeline as a job. Recorded as not built in
# contract/deferred/ln.json (FR-N1), so it is not exercised here.
UNSIGNED = {"post_advance"}
# The one read route that writes: the first build of a release's capability pack records its version.
# Recorded in contract/deferred/ln.json (FR-N1).
READ_THAT_WRITES = {"get_pack"}
LAYOUT = {"v": 1, "lens": "delivery",
          "widgets": [{"id": "gt", "type": "gate_trend", "size": "M", "view": "table", "filter": {}}]}


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
        return {"built": built, "asking": asking, "planning": planning, "change": change["id"], "concept": concept,
                "assumption": Canon(built).assumptions("open")[0]["id"]}

    def writes(self, w: dict) -> list:
        """Every signed write route, in an order where each one's target exists: (route name, method, path,
        body for a person). Paths may name what an earlier write made, through ``got``."""
        b, a, pl = w["built"].pid, w["asking"].pid, w["planning"].pid
        repo = self.tmp / "adopt-source"                                     # an existing project to adopt
        if not (repo / ".git").exists():
            repo.mkdir(parents=True, exist_ok=True)
            (repo / "README.md").write_text("# Order tracker\n", encoding="utf-8")
            for cmd in (["init", "-q"], ["add", "-A"],
                        ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "x"]):
                subprocess.run(["git", *cmd], cwd=repo, check=True, capture_output=True)
        return [
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
            ("post_evidence_export", "POST", f"/api/projects/{b}/evidence",
             lambda who, got: {"person": who, "persona": "compliance"}),
            ("post_pack_build", "POST", f"/api/projects/{b}/pack/build",
             lambda who, got: {"person": who, "persona": "compliance"}),
            ("put_outputs", "PUT", f"/api/projects/{b}/outputs",     # outputs per audience (kernel/outputs.py)
             lambda who, got: {"targets": ["report"], "reason": "for the owner", "person": who,
                               "persona": "business_owner"}),
            ("post_outputs_build", "POST", f"/api/projects/{b}/outputs/build",
             lambda who, got: {"targets": ["report"], "person": who, "persona": "compliance"}),
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
            ("put_project_modules", "PUT", f"/api/projects/{b}/modules",
             lambda who, got: {"preset": "full", "person": who, "persona": "developer"}),
            ("put_layout", "PUT", "/api/layout?persona=developer&lens=delivery",
             lambda who, got: {"person": who, "layout": LAYOUT}),
        ]

    def ledgers(self) -> dict:
        return {p.pid: p.ledger().records() for p in self.factory.projects()}

    def test_FR_N1_AC_2_every_write_that_records_state_is_signed_by_a_named_person(self):
        w = self.world()
        home = self.factory.home
        routes = self.writes(w)
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
            if name == "put_layout":                                       # a layout is kept outside every ledger
                saved = [json.loads(f.read_text(encoding="utf-8"))
                         for f in (home / "_cockpit" / "layouts").rglob("*.json")]
                self.assertEqual([s["person"] for s in saved], [person])
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
