"""Since you last looked (FR-REV1): review what agents and automations shipped, in the kernel, the cockpit's API,
the morning digest and the command line.

The home is ``review_fixture``'s night of work: merged and failed tasks, an escalation, an endpoint failure, a
release to the demo environment, a priced model run, an autopilot that assumed answers in Aino's name, the
factory's own assumptions and a commit gated from a developer's IDE. The digest goes to a receiver on
127.0.0.1; nothing else leaves the machine.
"""

import contextlib
import io
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import review_fixture  # noqa: E402
from integration_fakes import FakeSmtp, Receiver  # noqa: E402
from review_fixture import AINO, BEA  # noqa: E402
from test_brief_ln import tree  # noqa: E402
from test_cockpit import CockpitTestCase  # noqa: E402

from kernel import notices, relay, review, review_digest, review_marks  # noqa: E402
from kernel.canon import Canon, DecisionRefused  # noqa: E402
from kernel.cli import main  # noqa: E402
from kernel.learn import factory_project  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"#/p/(?P<pid>[^/]+)/(?P<view>[a-z_]+)(?:/(?P<focus>[^/]+))?\Z")


def page_views() -> set:
    """The project views the page routes (cockpit/static/core.js PAGE_ROUTES)."""
    js = (ROOT / "cockpit" / "static" / "core.js").read_text(encoding="utf-8")
    routes = json.loads(re.search(r"PAGE_ROUTES = (\{.*?\});", js, re.S).group(1))
    return {k for k, v in routes.items() if "{pid}" in v}


class ReviewCase(CockpitTestCase):
    def setUp(self):
        super().setUp()
        self.w = review_fixture.build(self.factory, self.tmp)
        self.loans, self.rooms, self.orders = self.w["loans"], self.w["rooms"], self.w["orders"]

    def group(self, out: dict, gid: str) -> list:
        return next(g for g in out["groups"] if g["id"] == gid)["items"]

    def item(self, out: dict, iid: str) -> dict:
        return next(i for g in out["groups"] for i in g["items"] if i["id"] == iid)

    def kinds(self, project) -> list:
        return [r["event"]["kind"] for r in project.ledger().records()]


class ReviewKernelTest(ReviewCase):
    def test_FR_REV1_AC_1_the_review_groups_and_ranks_what_agents_did_and_each_item_links_its_record(self):
        home = self.factory.home
        before = tree(home)
        jobs = [{"id": "J-0001", "kind": "run", "project": self.loans.pid, "state": "failed",
                 "started": self.factory.clock.stamp(), "log_tail": ["", "ModelError: the endpoint timed out"],
                 "by": {"person": AINO, "persona": "developer"}}]
        out = review.review(self.factory, person=AINO, persona="developer", jobs=jobs)
        self.assertEqual(tree(home), before)                                     # reading records nothing
        self.assertEqual([g["id"] for g in out["groups"]], ["waiting", "wrong", "decided", "shipped", "ide", "agents"])
        self.assertEqual(out["basis"], "last 24 hours")
        self.assertEqual(out["headline"], "Since you last looked: 2 shipped, 1 waiting on you, 4 failed, "
                                          f"{out['counts']['decided']} decided for you, 1 from your IDE")
        # waiting on you: the escalation the developer may decide, with its age and verdicts in place
        (card,) = self.group(out, "waiting")
        self.assertEqual((card["card_kind"], card["new"], card["age_hours"]), ("escalation", True, 0.0))
        self.assertEqual([(a["do"], a.get("body", {}).get("verdict"), a.get("key")) for a in card["actions"]],
                         [("decide", "retry", "a"), ("decide", "stop", "d"), ("open", None, "o")])
        self.assertEqual(review.review(self.factory, person=AINO, persona="it")["counts"]["waiting"], 0)
        # went wrong: the escalation first, then the gate's failure, the failed job, the endpoint failure
        wrong = self.group(out, "wrong")
        self.assertEqual([i["kind"] for i in wrong], ["escalated", "gate", "job_failed", "apparatus_failure"])
        self.assertEqual(wrong[1]["by"], {"type": "kernel", "name": "the gate"})
        self.assertIn("timed out", wrong[2]["detail"])
        self.assertEqual(wrong[2]["by"], {"type": "person", "name": AINO, "persona": "developer"})
        # decided for you: the autopilot's assumptions in Aino's name, and the factory's own assumptions with due dates
        decided = self.group(out, "decided")
        by_autopilot = [i for i in decided if i["kind"] == "delegated_decision"]
        self.assertTrue(by_autopilot)
        for i in by_autopilot:
            self.assertEqual((i["by"]["type"], i["by"]["person"], i["by"]["delegation"]), ("autopilot", AINO, "DL-001"))
            self.assertEqual([a["label"] for a in i["actions"]][:2], ["Confirm", "Overturn"])
        assumed = [i for i in decided if i["kind"] == "assumption"]
        self.assertTrue(assumed and all(i["project"] == self.loans.pid and i["due"] for i in assumed))
        self.assertFalse({(i["project"], i["assumption"]) for i in by_autopilot}       # each assumption once
                         & {(i["project"], i["assumption"]) for i in assumed})
        # shipped: the release, then T-001 with its verdict, rounds and diff
        release, task = self.group(out, "shipped")
        self.assertEqual((release["id"], release["where"]), (f"{self.loans.pid}/release/1", "to test"))
        self.assertEqual((task["task"], task["verdict"], task["rounds"]), ("T-001", "passed", 1))
        self.assertTrue(task["diff"]["measured"] and task["diff"]["files"] >= 2 and task["diff"]["added"] > 0)
        self.assertEqual((task["by"]["role"], task["by"]["model"]), ("builder", "fake-builder"))
        self.assertEqual([link["label"] for link in task["links"]], ["Task", "Diff", "Evidence", "Ledger"])
        # from your IDE: the commit Aino asked about, its verdict, who asked and what it changed
        (commit,) = self.group(out, "ide")
        self.assertEqual((commit["verdict"], commit["by"]["name"], commit["by"]["via"]), ("failed", AINO, "gate my code"))
        self.assertEqual((commit["diff"]["files"], commit["diff"]["added"], commit["diff"]["deleted"]), (2, 6, 1))
        self.assertEqual(commit["head"], self.w["head"])
        # cost and usage: the priced run, by project and role
        self.assertEqual([(r["project"], r["role"], r["tokens_in"]) for r in out["cost"]["rows"]],
                         [(self.loans.pid, "builder", 12000)])
        self.assertEqual(out["cost"]["total"]["cloud"], 0.0421)
        # every link resolves to a view the page routes, and every record is in its project's ledger
        views = page_views()
        for g in out["groups"]:
            for it in g["items"]:
                self.assertTrue(it["by"].get("type"), it["id"])
                for link in it["links"]:
                    if "href" not in link:
                        continue
                    if link["href"] == "#/jobs":
                        continue
                    m = LINK.match(link["href"])
                    self.assertTrue(m and m["view"] in views and m["pid"] == it["project"], link)
                seq = it["record"].get("seq")
                if seq is not None:
                    rec = self.factory.project(it["project"]).ledger().records()[seq]
                    self.assertEqual(rec["event"]["kind"], it["record"]["kind"], it["id"])

    def test_FR_REV1_AC_2_the_marker_is_each_persons_own_and_moves_when_they_mark_a_review_done(self):
        first = review.review(self.factory, person=AINO, persona="developer")
        done = review_marks.done(self.factory, person=AINO, persona="developer")
        self.assertEqual((done["scope"], done["counts"]), ("all", first["counts"]))
        rec = factory_project(self.factory).ledger().of_kind("review_done")[-1]["event"]["payload"]
        self.assertEqual((rec["person"], rec["persona"], rec["until"]), (AINO, "developer", first["until"]))
        again = review.review(self.factory, person=AINO, persona="developer")
        self.assertEqual((again["basis"], again["since"], again["happened"]), ("last review", first["until"], False))
        self.assertEqual([again["counts"][g] for g in ("wrong", "decided", "shipped", "ide")], [0, 0, 0, 0])
        self.assertEqual(again["counts"]["waiting"], 1)                          # the card still waits, not new
        self.assertEqual(again["headline"], "Since you last looked: 1 waiting on you")
        bea = review.review(self.factory, person=BEA, persona="developer")      # another person's marker is theirs
        self.assertEqual((bea["basis"], bea["counts"]["shipped"]), ("last 24 hours", 2))
        self.clock.advance(hours=1)
        self.loans.log("release_failed", {"release": 2, "step": "deploy:demo", "reason": "the port is taken"})
        later = review.review(self.factory, person=AINO, persona="developer")
        self.assertEqual([i["kind"] for i in self.group(later, "wrong")], ["release_failed"])
        self.assertEqual(self.group(later, "wrong")[0]["detail"], "the port is taken")
        # one project's review done moves that project's marker only; --since overrides any marker
        review_marks.done(self.factory, person=BEA, persona="developer", project=self.loans.pid)
        self.assertEqual(review.review(self.factory, person=BEA, persona="developer", project=self.loans.pid)
                         ["counts"]["shipped"], 0)
        self.assertEqual(review.review(self.factory, person=BEA, persona="developer")["counts"]["shipped"], 2)
        self.assertEqual(review.review(self.factory, person=AINO, persona="developer", since="7d")["counts"]["shipped"], 2)
        with self.assertRaises(ValueError):
            review.review(self.factory, person=AINO, since="yesterday")

    def test_FR_REV1_AC_3_a_reviewed_mark_is_signed_per_item_and_refused_for_what_cannot_be_marked(self):
        pid = self.loans.pid
        before = len(self.loans.ledger().records())
        for bad, why in (([f"{pid}/card/C-0001"], "decided, not marked"), ([f"{pid}/task/T-004"], "was not merged"),
                         ([f"{pid}/release/9"], "no release 9"), (["nonsense"], "an item is")):
            with self.assertRaises(ValueError) as caught:
                review_marks.mark(self.factory, bad, person=AINO, persona="developer")
            self.assertIn(why, str(caught.exception))
        with self.assertRaises(DecisionRefused):
            review_marks.mark(self.factory, [f"{pid}/task/T-001"], person="factory", persona="developer")
        self.assertEqual(len(self.loans.ledger().records()), before)            # a refusal records nothing
        out = review_marks.mark(self.factory, [f"{pid}/task/T-001", f"{pid}/release/1"], person=AINO,
                                persona="developer", note="read the diff")
        self.assertEqual(len(out), 2)
        marks = [r["event"]["payload"] for r in self.loans.ledger().of_kind("review_marked")]
        self.assertEqual([(m["item"], m["person"], m["persona"]) for m in marks],
                         [(f"{pid}/task/T-001", AINO, "developer"), (f"{pid}/release/1", AINO, "developer")])
        self.assertEqual(marks[0]["revision"], self.w["revision"])
        seen = review.review(self.factory, person=BEA, persona="developer")
        self.assertEqual(self.item(seen, f"{pid}/task/T-001")["reviewed"]["person"], AINO)
        self.assertEqual(seen["counts"]["unreviewed"], 1)                        # the IDE commit is left


class ReviewCockpitTest(ReviewCase):
    def get(self, path: str) -> dict:
        status, out, _ = self.call("GET", path)
        self.assertEqual(status, 200, out)
        return out

    def act(self, action: dict, extra: dict | None = None, who: str = AINO, persona: str = "developer") -> tuple:
        body = {**action.get("body", {}), **(extra or {}), "person": who, "persona": persona}
        status, out, _ = self.call("POST", action["path"], body)
        return status, out

    def test_FR_REV1_AC_3_reviewing_in_place_goes_through_the_signed_routes_and_records_who_did_what(self):
        pid = self.loans.pid
        out = self.get(f"/api/review?person={AINO.replace(' ', '%20')}&persona=developer")
        task = self.item(out, f"{pid}/task/T-001")
        reviewed = next(a for a in task["actions"] if a["do"] == "reviewed")
        before = self.kinds(self.loans)
        self.assertEqual(self.act(reviewed, who="system")[0], 403)               # not a person: nothing recorded
        self.assertEqual(self.kinds(self.loans), before)
        status, got = self.act(reviewed)
        self.assertEqual(status, 201, got)
        self.assertEqual(self.kinds(self.loans)[len(before):], ["review_marked", "cockpit_write"])
        again = self.get(f"/api/projects/{pid}/review?person={AINO.replace(' ', '%20')}&persona=developer")
        self.assertEqual(self.item(again, f"{pid}/task/T-001")["reviewed"]["person"], AINO)
        # the drawer's preview: the diff, file by file, and the gate's signals
        detail = self.get(f"/api/projects/{pid}/review/detail?item=task/T-001")
        self.assertIn("diff --git", detail["diff"]["diff"])
        self.assertTrue(detail["diff"]["per_file"] and detail["signals"] is None or isinstance(detail["signals"], dict))
        self.assertEqual(self.get(f"/api/projects/{pid}/review/detail")["item"], None)
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/review/detail?item=task/T-009")[0], 404)
        # a card decided in place, through its own route: the escalation is retried, signed by Aino
        card = self.group(out, "waiting")[0]
        status, got = self.act(next(a for a in card["actions"] if a.get("key") == "a"))
        self.assertEqual(status, 200, got)
        self.assertEqual((got["decision"]["verdict"], got["decision"]["person"]), ("retry", AINO))
        # an assumption overturned: it is refuted with the correction, and a change card opens
        assumed = next(i for i in self.group(out, "decided") if i["kind"] == "assumption")
        overturn = next(a for a in assumed["actions"] if a["label"] == "Overturn")
        self.assertEqual(overturn["needs"], "correction")
        status, got = self.act(overturn, {"correction": "only the team lead approves"}, persona="product_owner")
        self.assertEqual((status, got["assumption"]["status"]), (200, "refuted"))
        self.assertTrue(any(c["refs"].get("assumption") == assumed["assumption"]
                            for c in Canon(self.loans).cards(kind="change")))
        # a decision the autopilot made in Aino's name: overturned through its assumption, and its delegation stopped
        delegated = next(i for i in self.group(out, "decided") if i["kind"] == "delegated_decision")
        status, got = self.act(next(a for a in delegated["actions"] if a["label"] == "Overturn"),
                               {"correction": "rooms are booked by the hour"})
        self.assertEqual((status, got["assumption"]["status"]), (200, "refuted"))
        status, got = self.act(next(a for a in delegated["actions"] if a["do"] == "revoke"))
        self.assertEqual((status, got["delegation"]["id"]), (200, "DL-001"))
        # Report a change, prefilled with the item
        change = next(a for a in task["actions"] if a["do"] == "change")
        self.assertTrue(change["prefill"].startswith("About T-001"))
        status, got = self.act(change, {"text": change["prefill"] + "the list should sort by name"}, persona="end_user")
        self.assertEqual(status, 201, got)
        self.assertIn("T-001", got["card"]["body"] + got["card"]["title"] + json.dumps(got["card"]["payload"]))
        self.assertEqual(self.call("POST", "/api/review/mark", {"items": [f"{pid}/card/C-0001"], "person": AINO,
                                                                "persona": "developer"})[0], 400)

    def test_FR_REV1_AC_4_mark_all_reviewed_records_review_done_with_the_counts_and_moves_the_marker(self):
        q = f"?person={AINO.replace(' ', '%20')}&persona=developer"
        first = self.get("/api/review" + q)
        status, out, _ = self.call("POST", "/api/review/done", {"person": AINO, "persona": "developer"})
        self.assertEqual(status, 201, out)
        self.assertEqual((out["done"]["counts"], out["done"]["ledger"]), (first["counts"], "_factory"))
        self.assertEqual(self.get("/api/review" + q)["basis"], "last review")
        self.assertIn("review_done", self.kinds(factory_project(self.factory)))
        status, out, _ = self.call("POST", "/api/review/done", {"project": self.orders.pid, "person": BEA,
                                                                "persona": "developer"})
        self.assertEqual((status, out["done"]["ledger"], out["done"]["counts"]["ide"]), (201, self.orders.pid, 1))
        self.assertEqual(self.call("POST", "/api/review/done", {"person": "", "persona": "developer"})[0], 403)
        self.assertEqual(self.call("POST", "/api/review/done", {"project": "no-such-1", "person": BEA,
                                                                "persona": "developer"})[0], 404)


class MorningDigestTest(ReviewCase):
    def setUp(self):
        super().setUp()
        self.rx = Receiver()
        self.addCleanup(self.rx.close)
        self.env = {"TEAMS_DEV": self.rx.base + "/teams"}
        relay.set_cockpit(self.factory, "https://rihmasto.example", person="Ilkka", persona="it")
        self.sub = relay.subscribe(self.factory, sink="teams", url_env="TEAMS_DEV", personas=["developer"],
                                   kinds=["question"], person="Ilkka", persona="it")

    def digests(self) -> list:
        bodies = [json.loads(r["body"]) for r in self.rx.at("/teams")]
        return [b["attachments"][0]["content"] for b in bodies
                if b["attachments"][0]["content"]["body"][0]["text"].startswith("Since you last looked")]

    def round(self) -> dict:
        return relay.run(self.factory, environ=self.env)

    def test_FR_REV1_AC_5_the_digest_goes_at_the_persons_time_with_a_link_and_is_held_back_when_nothing_happened(self):
        with self.assertRaises(ValueError):                                       # a receiver IT set for the persona
            review_digest.set_digest(self.factory, person=AINO, persona="it", subscription=self.sub["id"])
        with self.assertRaises(ValueError):
            review_digest.set_digest(self.factory, person=AINO, persona="developer", subscription=self.sub["id"],
                                     at="7:30")
        entry = review_digest.set_digest(self.factory, person=AINO, persona="developer", subscription=self.sub["id"],
                                         at="07:30", days="weekdays", tz="+02:00")
        self.assertEqual((entry["days"], entry["tz"]), (["mon", "tue", "wed", "thu", "fri"], "+02:00"))
        self.assertIn("review_digest_set", self.kinds(factory_project(self.factory)))
        self.clock.advance(hours=17)                                              # Monday 05:00 UTC, 07:00 local
        self.round()
        self.assertEqual(self.digests(), [])                                      # not yet
        self.clock.advance(minutes=31)                                            # 07:31 local
        out = self.round()
        self.assertEqual(out["results"][0]["review_digest"], ["delivered"])
        (card,) = self.digests()
        head, detail = card["body"][0]["text"], card["body"][1]["text"]
        self.assertTrue(head.startswith("Since you last looked: 2 shipped, 1 waiting on you"), head)
        self.assertIn("T-001 merged", detail)
        self.assertIn("1 more project is bound to an autopilot's sandbox", detail)   # Room bookings is held
        self.assertNotIn("Room bookings", detail)
        self.assertEqual(card["actions"], [{"type": "Action.OpenUrl", "title": "Open the Review",
                                            "url": "https://rihmasto.example/#/review"}])
        self.round()
        self.assertEqual(len(self.digests()), 1)                                  # once a local day
        self.clock.advance(days=1)                                                # Tuesday: nothing happened
        self.assertEqual(self.round()["results"][0]["review_digest"], ["held back"])
        self.assertEqual(len(self.digests()), 1)
        log = [d for d in relay.deliveries(self.factory, limit=0) if d["kind"] == "review_digest"]
        self.assertEqual([d["outcome"] for d in log], ["delivered", "held back"])
        self.clock.advance(days=1)                                                # Wednesday: something did
        self.loans.log("release_failed", {"release": 2, "step": "deploy:demo", "reason": "the port is taken"})
        self.round()
        self.assertEqual(self.digests()[-1]["body"][0]["text"], "Since you last looked: 1 waiting on you, 1 failed")
        self.clock.advance(days=3)                                                # Saturday: not a weekday
        self.loans.log("release_failed", {"release": 3, "step": "deploy:demo", "reason": "again"})
        self.round()
        self.assertEqual(len(self.digests()), 2)
        self.assertTrue(relay.log_intact(self.factory))
        # the same notice by mail names the Review link, and a person can turn the digest off
        n = review_digest.notice(self.factory, entry, cockpit="https://rihmasto.example", subscription=self.sub,
                                 day="2026-11-30", since="2026-11-01T00:00:00Z")
        mail = notices.render_email(n, sender="rihmasto@example.org", to=["aino@example.org"],
                                    now=self.factory.clock.now()).as_string()
        self.assertIn("Open the Review:\nhttps://rihmasto.example/#/review", mail)
        off = review_digest.set_digest(self.factory, person=AINO, persona="developer", subscription=None, off=True)
        self.assertTrue(off["off"])
        self.assertIsNone(review_digest.due_day(off, self.factory.clock.now(), {}))

    def test_FR_REV1_AC_5_a_mail_receiver_gets_the_digest_through_the_relay(self):
        smtp = FakeSmtp()
        self.addCleanup(smtp.close)
        sub = relay.subscribe(self.factory, sink="email", personas=["developer"], person="Ilkka", persona="it",
                              mail={"host": "127.0.0.1", "port": smtp.port, "from": "rihmasto@example.org",
                                    "to": ["dev-team@example.org"]})
        review_digest.set_digest(self.factory, person=BEA, persona="developer", subscription=sub["id"], at="06:00",
                                 days="daily", tz="UTC")
        self.round()                                                              # Sunday 12:00 UTC: daily, past 06:00
        mails = [m.decode() for m in smtp.messages if b"Since you last looked" in m]
        self.assertEqual(len(mails), 1)
        self.assertIn("https://rihmasto.example/#/review", mails[0])


class ReviewCliTest(ReviewCase):
    def cli(self, *argv: str) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--home", str(self.factory.home), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_FR_REV1_AC_6_the_command_line_reviews_marks_and_marks_a_review_done(self):
        since = "2026-11-01T00:00Z"
        code, out, err = self.cli("review", "--since", since, "--person", AINO, "--persona", "developer")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("Since you last looked: 2 shipped"), out)
        self.assertIn(f"{self.loans.pid}/task/T-001  T-001 merged", out)
        code, out, err = self.cli("review", self.orders.pid, "--since", since, "--json")
        self.assertEqual((code, json.loads(out)["counts"]["ide"], json.loads(out)["project"]), (0, 1, self.orders.pid))
        item = f"{self.orders.pid}/gate/{self.group(json.loads(out), 'ide')[0]['record']['seq']}"
        code, out, err = self.cli("review", "mark", item, "--person", AINO, "--persona", "developer")
        self.assertEqual((code, json.loads(out)["marked"][0]["item"]), (0, item), err)
        code, out, err = self.cli("review", "done", "--person", AINO, "--persona", "developer", "--since", since)
        self.assertEqual((code, json.loads(out)["scope"]), (0, "all"), err)
        code, out, err = self.cli("review", "mark", f"{self.loans.pid}/card/C-0001", "--person", AINO,
                                  "--persona", "developer")
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("rihmasto review: a card is decided, not marked"), err)
        code, out, err = self.cli("review", "done")
        self.assertEqual(code, 2)
        self.assertIn("review done is signed", err)
        self.assertEqual(self.cli("review", "mark", item, "--person", "factory", "--persona", "developer")[0], 2)


if __name__ == "__main__":
    unittest.main()
