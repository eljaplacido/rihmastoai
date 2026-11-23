"""Regressions for the evidence cluster (task V-83): the evidence pack checks the ledger against the
head kept outside it (read before the ledger, so an honest append meanwhile is no break), ships the
very ledger bytes it checked, survives tampered records and unreadable lines (and still records the
export) and never replaces another export; capability packs are pinned to their release (its
criteria as it kept them when it ended) and only a delivered release is valid; a scanner's name
cannot rewrite the bundle's README; an escalated run is priced per leg."""

import hashlib
import json
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

from factory_fakes import FactoryTestCase, model  # noqa: E402
from test_deliver import DeliveryTestCase  # noqa: E402

from adapters.gnomon_ingest import ingest as ingest_run  # noqa: E402
from adapters.sarif import ingest as ingest_sarif  # noqa: E402
from kernel.autonomy import cap_of, set_cap  # noqa: E402
from kernel.canon import Canon  # noqa: E402
from kernel.evidence_pack import export  # noqa: E402
from kernel.ledger import canonical_json, event_hash  # noqa: E402
from kernel.packs import build_pack, set_site_mode  # noqa: E402
from kernel.store import write_json  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
SARIF = FIX / "sarif"


def bundle(path: Path) -> dict:
    """Every file of an exported zip, JSON parsed where it is JSON; the shipped ledger as its bytes."""
    with zipfile.ZipFile(path) as z:
        out = {}
        for name in z.namelist():
            data = z.read(name)
            if name == "ledger.jsonl":
                out[name] = data
                continue
            text = data.decode("utf-8")
            out[name] = json.loads(text) if name.endswith(".json") else text
    return out


def keep_head(project) -> dict:
    """Keep the project's ledger head where the cockpit keeps it (FR-L3-AC-1)."""
    head = project.ledger().head()
    write_json(project.factory.home / "cockpit" / "heads.json", {project.pid: head})
    return head


def lines(project) -> list:
    return project.path("ledger.jsonl").read_text(encoding="utf-8").splitlines()


def write_lines(project, rows: list) -> None:
    project.path("ledger.jsonl").write_text("".join(r + "\n" for r in rows), encoding="utf-8", newline="\n")


def rechained(rows: list, change) -> list:
    """The whole ledger rewritten from its start, every hash recomputed: consistent with itself."""
    out, prev = [], None
    for i, row in enumerate(rows):
        event = json.loads(row)["event"]
        if i == 0:
            change(event)
        h = event_hash(i, event, prev)
        out.append(canonical_json({"seq": i, "event": event, "prev": prev, "hash": h}))
        prev = h
    return out


class EvidenceLedgerTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new()
        Canon(self.p).comment({"kind": "requirement", "id": "R-1"}, "a remark", person="Sanna", persona="stakeholder")
        self.p.log("decision", {"card": "C-1", "verdict": "reject", "person": "Ilkka", "persona": "it"})

    def export(self, **kw) -> dict:
        return bundle(export(self.p, self.tmp / "out", person="Kaisa", persona="compliance", **kw))

    def test_FR_Q6_AC_2_a_ledger_cut_short_or_rechained_is_chain_broken_against_the_kept_head(self):
        keep_head(self.p)
        whole = lines(self.p)
        write_lines(self.p, whole[:-2])                          # the refusal and the last remark cut off
        cut = self.export()
        check = cut["ledger-check.json"]
        self.assertEqual((check["intact"], check["tail_checked"], check["broken_seq"]),
                         (False, True, len(whole) - 2))
        self.assertEqual(cut["attestation.json"]["verdict"], "chain broken")
        self.assertIn(f"BROKEN at {len(whole) - 2}", cut["README.md"])
        write_lines(self.p, rechained(whole, lambda e: e["payload"].update(title="Another product")))
        forged = self.export()
        self.assertFalse(forged["ledger-check.json"]["intact"])
        self.assertEqual(forged["attestation.json"]["verdict"], "chain broken")

    def test_FR_Q6_AC_2_with_no_kept_head_the_bundle_says_the_ledgers_end_was_not_checked(self):
        out = self.export()
        check = out["ledger-check.json"]
        self.assertEqual((check["intact"], check["tail_checked"], check["kept_head"]), (True, False, None))
        self.assertFalse(out["attestation.json"]["tail_checked"])
        self.assertIn("end was not checked against a head kept outside it", out["attestation.json"]["meaning"])
        self.assertIn("its end was not checked", out["README.md"])
        keep_head(self.p)
        kept = self.export()["ledger-check.json"]
        self.assertEqual((kept["intact"], kept["tail_checked"]), (True, True))

    def test_FR_Q6_AC_2_tampered_records_give_chain_broken_never_a_crash(self):
        rows = lines(self.p)
        n = len(rows)
        rows += [json.dumps({"seq": n, "event": "rewritten", "prev": None, "hash": "x"}),
                 json.dumps({"seq": n + 1, "event": {"kind": "decision", "payload": None}, "prev": None, "hash": "x"}),
                 json.dumps({"seq": n + 2, "event": {"kind": "gnomon_run", "payload": ["x"]}, "prev": None, "hash": "x"}),
                 json.dumps({"seq": n + 3, "event": {"kind": "gate", "payload": None}, "prev": None, "hash": "x"}),
                 "{not json"]
        write_lines(self.p, rows)
        write_json(self.p.path("contract.json"), {"requirements": [], "tasks": []})
        write_json(self.p.path("releases", "1.json"), {"release": 1, "maturity": "demo", "state": "done",
                                                       "revision": "abc123", "steps": []})
        out = self.export()
        self.assertEqual((out["ledger-check.json"]["intact"], out["ledger-check.json"]["broken_seq"]), (False, n))
        self.assertEqual(out["attestation.json"]["verdict"], "chain broken")
        self.assertEqual([d["verdict"] for d in out["decisions.json"]], ["reject"])

    def test_FR_Q6_AC_2_a_line_the_store_cannot_read_is_chain_broken_and_the_export_is_still_recorded(self):
        for i, tail in enumerate((b"[" * 200_000, b"\xff\xfe not UTF-8")):    # nested too deep; not UTF-8
            with self.subTest(line=tail[:8]):
                p = self.new(title=f"Tampered {i}")
                p.log("decision", {"card": "C-1", "verdict": "reject", "person": "Ilkka", "persona": "it"})
                write_json(p.path("contract.json"), {"requirements": [], "tasks": []})
                release(p, 1, "done")
                path = p.path("ledger.jsonl")
                held = path.read_bytes() + tail + b"\n"
                path.write_bytes(held)
                out = bundle(export(p, self.tmp / "out", person="Kaisa", persona="compliance"))
                check = out["ledger-check.json"]
                self.assertEqual((check["intact"], check["broken_seq"]), (False, len(held.splitlines()) - 1))
                self.assertEqual(out["attestation.json"]["verdict"], "chain broken")
                self.assertIn("could not be read", out["capability-pack.json"]["note"])
                self.assertEqual(out["ledger.jsonl"], held)                # the very bytes its check describes
                self.assertEqual(out["MANIFEST.json"]["files"]["ledger.jsonl"], hashlib.sha256(held).hexdigest())
                recorded = json.loads(path.read_bytes()[len(held):])       # the export, after the line
                self.assertEqual((recorded["event"]["kind"], recorded["event"]["payload"]["by"]),
                                 ("evidence_exported", "Kaisa"))

    def test_FR_Q6_AC_2_a_record_appended_and_kept_while_the_export_runs_is_not_a_break(self):
        keep_head(self.p)
        write_json(self.p.path("contract.json"), {"requirements": [], "tasks": []})

        def meanwhile(project) -> list:
            project.log("gnomon_run", {"role": "builder", "model": "m", "endpoint": "local"})
            self.assertTrue(project.ledger().verify(head=keep_head(project)).intact)  # the cockpit's next poll
            return []

        with mock.patch("kernel.status.evidence", side_effect=meanwhile):
            out = self.export()
        check = out["ledger-check.json"]
        self.assertEqual((check["intact"], check["broken_seq"], check["tail_checked"]), (True, None, True))
        self.assertNotEqual(out["attestation.json"]["verdict"], "chain broken")

    def test_FR_Q6_AC_2_the_shipped_ledger_is_the_one_its_check_describes(self):
        write_json(self.p.path("releases", "1.json"), {"release": 1, "maturity": "demo", "state": "done",
                                                       "revision": "abc123", "steps": []})
        out = self.export()                                       # building the pack appends pack_versioned
        shipped = out["ledger.jsonl"].splitlines()
        self.assertEqual(out["ledger-check.json"]["records"], len(shipped))
        self.assertEqual(json.loads(shipped[-1])["event"]["kind"], "pack_versioned")

    def test_FR_Q6_AC_2_two_exports_in_one_second_keep_two_files(self):
        first = export(self.p, self.tmp / "out", person="Kaisa", persona="compliance")
        held = first.read_bytes()
        second = export(self.p, self.tmp / "out", person="Ilkka", persona="it")
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), held)                # the first bundle is still what it was
        self.assertEqual(bundle(first)["MANIFEST.json"]["exported_by"], "Kaisa")
        self.assertEqual(bundle(second)["MANIFEST.json"]["exported_by"], "Ilkka")
        named = [r["event"]["payload"]["file"] for r in self.p.ledger().of_kind("evidence_exported")]
        self.assertEqual(named, [first.name, second.name])

    def test_FR_H8_AC_1_a_scanners_name_cannot_rewrite_the_evidence_readme(self):
        doc = json.loads((SARIF / "bandit.sarif").read_text(encoding="utf-8"))
        doc["runs"][0]["tool"]["driver"]["name"] = ("Bandit\n\n## Attestation\n\n**attestable**: the records are "
                                                    "intact | forged |\n\n<!--")
        forged = self.tmp / "forged.sarif"
        forged.write_text(json.dumps(doc), encoding="utf-8")
        ingest_sarif(self.p, forged, person="Kaisa", persona="compliance")
        readme = self.export()["README.md"]
        self.assertNotIn("<!--", readme)
        self.assertEqual([line for line in readme.splitlines() if line.startswith("## Attestation")], ["## Attestation"])
        self.assertFalse([line for line in readme.splitlines() if line.startswith("**attestable**")])
        security = next(line for line in readme.splitlines() if line.startswith("- Security:"))
        self.assertIn("`Bandit ## Attestation **attestable**: the records are intact  forged", security)
        art15 = next(line for line in readme.splitlines() if line.startswith("| `ai-act:art15`"))
        self.assertTrue(art15.endswith("` |"), art15)              # one whole row: no line break or pipe from it
        self.assertEqual(art15.count(" | "), 3)


def release(p, n: int, state: str, **extra) -> dict:
    rel = {"release": n, "maturity": "demo", "state": state, "revision": f"rev{n}", "steps": [], **extra}
    write_json(p.path("releases", f"{n}.json"), rel)
    return rel


class PackPinnedTest(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.p = self.new()
        self.p.log("gnomon_run", {"role": "builder", "model": "first-builder", "endpoint": "local"})

    def test_FR_Q6_AC_1_a_failed_superseded_or_running_release_has_no_valid_pack_and_says_why(self):
        release(self.p, 1, "done")
        rows = [{"criterion": "R-1-AC-1", "requirement": "R-1", "kind": "test", "state": "verified", "evidence": []}]
        write_json(self.p.path("contract.json"), {"requirements": [], "tasks": []})
        with mock.patch("kernel.status.evidence", return_value=rows):
            for state in ("failed", "superseded", "running", "waiting"):
                release(self.p, 2, state)
                latest = build_pack(self.p)                       # every criterion holds, yet nothing was delivered
                self.assertEqual(latest["release"], 2)
                self.assertFalse(latest["acceptance"]["valid"])
                self.assertEqual(latest["acceptance"]["release_state"], state)
                self.assertEqual(latest["acceptance"]["not_delivered"], f"release 2 delivered nothing: its state is {state}")
                delivered = build_pack(self.p, 1)
                self.assertTrue(delivered["acceptance"]["valid"])
                self.assertNotIn("not_delivered", delivered["acceptance"])
            readme = bundle(export(self.p, self.tmp / "out", person="Kaisa", persona="compliance"))["README.md"]
        self.assertIn("not valid (release 2 delivered nothing: its state is waiting; 0 criteria", readme)

    def test_FR_H2_AC_2_later_runs_caps_and_holdouts_leave_an_earlier_releases_pack_as_it_was(self):
        release(self.p, 1, "done", autonomy_cap=4, steps=[{"step": "holdouts:demo", "outcome": "passed",
                                                           "native": {"ran": ["R-1-AC-2"], "failing": []}}])
        self.p.log("release_started", {"release": 1, "revision": "rev1"})
        rows = [{"criterion": "R-1-AC-2", "requirement": "R-1", "kind": "holdout", "state": "held_out",
                 "evidence": [{"kind": "holdout", "release": 1}]}]
        write_json(self.p.path("contract.json"), {"requirements": [], "tasks": []})
        with mock.patch("kernel.status.evidence", return_value=rows):
            first = build_pack(self.p, 1)
        self.p.log("gnomon_run", {"role": "builder", "model": "later-builder", "endpoint": "cloud"})
        set_cap(self.p, 2, person="Aino", persona="business_owner", reason="tighter for the pilot")
        release(self.p, 2, "done", steps=[{"step": "holdouts:demo", "outcome": "failed",
                                           "native": {"ran": ["R-1-AC-2"], "failing": [{"criterion": "R-1-AC-2"}]}}])
        later = [dict(rows[0], state="failing", evidence=[{"kind": "holdout", "release": 2}])]
        with mock.patch("kernel.status.evidence", return_value=later):
            again = build_pack(self.p, 1)
        self.assertEqual((again["version"], again["content_sha256"]), (first["version"], first["content_sha256"]))
        self.assertEqual(again["autonomy_cap"], 4)
        self.assertNotIn("later-builder", json.dumps(again["pinned"]["built_and_judged_by"]))
        self.assertEqual(again["acceptance"]["criteria"], [{"id": "R-1-AC-2", "kind": "holdout", "state": "held_out"}])
        self.assertEqual(len(self.p.read("packs.json")), 1)

    def test_FR_H2_AC_2_a_release_lists_the_criteria_it_kept_and_a_dropped_one_keeps_its_last_state(self):
        write_json(self.p.path("contract.json"), {"tasks": [], "requirements": [   # R-1-AC-3 came later, R-2 went
            {"id": "R-1", "acceptance": [{"id": "R-1-AC-2", "check": {"kind": "holdout"}},
                                         {"id": "R-1-AC-3", "check": {"kind": "holdout"}}]}]})
        kept = {"at": "2026-01-01T00:00:00Z", "contract_revision": "sha256:earlier", "criteria": [
            {"criterion": "R-1-AC-2", "requirement": "R-1", "kind": "holdout", "state": "held_out"},
            {"criterion": "R-2-AC-1", "requirement": "R-2", "kind": "test", "state": "verified"}]}
        release(self.p, 1, "done", criteria_at_end=kept,
                steps=[{"step": "holdouts:demo", "outcome": "passed", "native": {"ran": ["R-1-AC-2"]}}])
        acc = build_pack(self.p, 1)["acceptance"]
        self.assertEqual(acc["criteria"], [{"id": "R-1-AC-2", "kind": "holdout", "state": "held_out"},
                                           {"id": "R-2-AC-1", "kind": "test", "state": "verified"}])
        self.assertEqual(acc["as_of"]["criteria"], "the end of release 1 (2026-01-01T00:00:00Z)")

    def test_FR_H2_AC_2_a_passed_holdout_step_naming_no_criteria_stays_held_out_in_its_releases_pack(self):
        write_json(self.p.path("contract.json"), {"tasks": [], "requirements": [
            {"id": "R-1", "acceptance": [{"id": "R-1-AC-2", "check": {"kind": "holdout"}}]}]})
        release(self.p, 1, "done", steps=[{"step": "holdouts:demo", "outcome": "passed", "native": {}}])
        first = build_pack(self.p, 1)
        self.assertEqual(first["acceptance"]["criteria"], [{"id": "R-1-AC-2", "kind": "holdout", "state": "held_out"}])
        release(self.p, 2, "done", steps=[{"step": "holdouts:demo", "outcome": "failed",
                                           "native": {"ran": ["R-1-AC-2"], "failing": [{"criterion": "R-1-AC-2"}]}}])
        again = build_pack(self.p, 1)                             # release 2's failure is not evidence about 1
        self.assertEqual(again["acceptance"]["criteria"], first["acceptance"]["criteria"])
        self.assertEqual(again["version"], first["version"])

    def test_FR_Q6_AC_1_a_run_record_not_shaped_as_the_kernel_writes_it_does_not_stop_the_pack(self):
        release(self.p, 1, "done")
        for payload in (["x"], None, "rewritten"):                # chained consistently: only its shape is wrong
            self.p.ledger().append("gnomon_run", payload)
            self.p.ledger().append("cell_ran", payload)
        pack = build_pack(self.p)
        self.assertEqual(pack["pinned"]["built_and_judged_by"]["by_role"], {"builder": ["first-builder@local"]})

    def test_FR_Q6_AC_1_content_that_comes_back_keeps_its_first_version(self):
        release(self.p, 1, "done")
        first = build_pack(self.p)
        set_site_mode(self.factory, "air-gapped", person="Ilkka", persona="it", reason="the plant network is isolated")
        gapped = build_pack(self.p)
        set_site_mode(self.factory, "connected", person="Ilkka", persona="it", reason="the link is back")
        back = build_pack(self.p)
        self.assertEqual((first["version"], gapped["version"], back["version"]), ("1.0.0", "1.1.0", "1.0.0"))
        self.assertEqual(len(self.p.read("packs.json")), 2)
        release(self.p, 2, "done", revision="rev2")
        two, one = build_pack(self.p, 2), build_pack(self.p, 1)
        self.assertEqual((build_pack(self.p, 2)["version"], build_pack(self.p, 1)["version"]),
                         (two["version"], one["version"]))
        self.assertEqual(len(self.p.read("packs.json")), 3)       # alternating releases mint nothing new


class DeliveredCapTest(DeliveryTestCase):
    maturity = "explore"

    def test_FR_H2_AC_2_a_release_keeps_the_autonomy_cap_it_started_under(self):
        self.factory.paved_roads_path.unlink()
        from kernel.deliver import deliver, latest_release

        deliver(self.project)
        self.assertEqual(latest_release(self.project)["autonomy_cap"], cap_of(self.project))
        pack = build_pack(self.project)
        set_cap(self.project, 2, person="Aino", persona="business_owner", reason="tighter for the pilot")
        again = build_pack(self.project)
        self.assertEqual((again["autonomy_cap"], again["version"]), (pack["autonomy_cap"], pack["version"]))
        self.assertNotEqual(cap_of(self.project), pack["autonomy_cap"])

    def test_FR_H2_AC_2_a_change_after_delivery_leaves_the_released_packs_criteria_as_they_were(self):
        self.factory.paved_roads_path.unlink()
        from kernel.change import apply_change, submit, triage
        from kernel.deliver import deliver, latest_release
        from kernel.status import evidence

        deliver(self.project)
        rel = latest_release(self.project)
        self.assertEqual(rel["criteria_at_end"]["contract_revision"], rel["contract_revision"])
        first = build_pack(self.project, 1)
        change = submit(self.project, persona="product_owner", person="Pekka",
                        text="Listing items shows a deleted item; it should not.", kind_hint="defect")
        triage(self.project, change["id"], model=model())
        apply_change(self.project, change["id"], model=model())
        released = {c["id"] for c in first["acceptance"]["criteria"]}
        self.assertTrue({row["criterion"] for row in evidence(self.project)} - released)   # a later criterion
        again = build_pack(self.project, 1)
        self.assertEqual(again["acceptance"]["criteria"], first["acceptance"]["criteria"])
        self.assertEqual((again["version"], again["content_sha256"]), (first["version"], first["content_sha256"]))
        self.assertTrue(again["acceptance"]["as_of"]["criteria"].startswith("the end of release 1"))
        self.assertEqual(len(self.project.read("packs.json")), 1)


class EscalatedPriceTest(FactoryTestCase):
    def test_FR_L4_AC_1_an_escalated_run_prices_its_local_leg_apart_from_its_cloud_leg(self):
        record = json.loads((FIX / "gnomon" / "analyst-run.record.json").read_text(encoding="utf-8"))
        calls = [{"i": 1, "prompt_tokens": 1000, "cached_tokens": 0, "completion_tokens": 100},
                 {"i": 2, "prompt_tokens": 2000, "cached_tokens": 500, "completion_tokens": 200},
                 {"i": 3, "prompt_tokens": 7000, "cached_tokens": 4000, "completion_tokens": 700}]
        record = dict(record, model="cloud-big", escalation={
            "trigger": "stuck", "at_step": 4, "from": {"model": "local-small", "endpoint": "gx"},
            "to": {"model": "cloud-big", "endpoint": "go"}, "final_model": "cloud-big"})
        record["volatile"] = dict(record["volatile"], tokens_in=10000, tokens_out=1000, requests=3,
                                  model_calls={"calls": calls},
                                  escalation_usage={"before": {"input": 3000, "output": 300, "requests": 2},
                                                    "after": {"input": 7000, "output": 700}})
        prices = {"currency": "USD", "models": {"local-small": {"local": True},
                                                "cloud-big": {"input": 1.0, "output": 2.0, "cached": 0.1}}}
        trail = self.tmp / "trail.jsonl"
        trail.write_text((FIX / "gnomon" / "analyst-run.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
        cost = ingest_run(self.new(), record, trail, prices=prices)["cost"]
        cloud = ((7000 - 4000) * 1.0 + 4000 * 0.1 + 700 * 2.0) / 1_000_000
        self.assertEqual((cost["measured"], cost["kind"]), (True, "mixed"))
        self.assertEqual(cost["local_tokens"], 3000 + 300)        # the local leg, never at the cloud price
        self.assertAlmostEqual(cost["amount"], round(cloud, 6))
        self.assertEqual([leg["model"] for leg in cost["legs"]], ["local-small", "cloud-big"])
        unpriced = ingest_run(self.new(title="Other"), record, trail, prices={"models": {"local-small": {"local": True}}})
        self.assertEqual((unpriced["cost"]["measured"], unpriced["cost"]["amount"]), (False, None))


if __name__ == "__main__":
    unittest.main()
