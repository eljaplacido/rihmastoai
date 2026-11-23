"""What a capability pack declares (FR-Q6-AC-3): its workload classes, the site mode and the fallback
ladder the site mode allows. The declarations are behaviour: when they change, the version changes."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_deliver import DeliveryTestCase  # noqa: E402

from kernel.autonomy import set_cap  # noqa: E402
from kernel.canon import DecisionRefused  # noqa: E402
from kernel.deliver import deliver  # noqa: E402
from kernel.learn import factory_project  # noqa: E402
from kernel.packs import (build_pack, content_sha256, ladder, latest_pack, pack_problems, set_site_mode,  # noqa: E402
                          site_policy)


def levels(pack) -> list:
    return pack["declared"]["site_mode"]["levels"]


def step(pack, level) -> dict:
    return next(s for s in pack["declared"]["fallback_ladder"] if s["level"] == level)


class PackDeclarationTest(DeliveryTestCase):
    maturity = "explore"

    def test_FR_Q6_AC_3_a_pack_declares_its_workload_classes_site_mode_and_fallback_ladder(self):
        self.factory.paved_roads_path.unlink()
        self.assertIsNone(latest_pack(self.project))
        deliver(self.project)
        self.assertIsNone(latest_pack(self.project))                               # a release alone is no pack
        pack = build_pack(self.project)
        declared = pack["declared"]
        self.assertEqual(declared["workload_classes"]["by_role"], {"builder": "batch"})
        self.assertEqual(declared["workload_classes"]["used"], ["batch"])
        self.assertIn("not declared", declared["workload_classes"]["runtime"])    # the product's own: said
        self.assertEqual(declared["site_mode"]["mode"], "connected")               # the default
        self.assertTrue(declared["site_mode"]["source"].startswith("default"))
        self.assertEqual(levels(pack), ["L1", "L2", "L3", "L4"])
        self.assertEqual(step(pack, "L3")["data_classes"], ["public"])
        self.assertEqual([s["name"] for s in declared["fallback_ladder"]],
                         ["same pack elsewhere", "smaller model, degraded", "cloud, allowed data classes only",
                          "queue and defer"])
        self.assertNotIn("declared", pack["acceptance"])                           # apart from what was measured
        # the newest pack is read as it was written; reading builds, versions and logs nothing
        records, history = len(self.project.ledger().records()), self.project.read("packs.json")
        self.assertEqual(latest_pack(self.project), pack)
        self.assertEqual((len(self.project.ledger().records()), self.project.read("packs.json")), (records, history))
        self.assertEqual(pack_problems(self.project, latest_pack(self.project)), [])

    def test_FR_Q6_AC_3_the_site_mode_is_set_by_it_or_compliance_and_changes_the_ladder_and_the_version(self):
        self.factory.paved_roads_path.unlink()
        deliver(self.project)
        first = build_pack(self.project)
        for person, persona in (("Pekka", "developer"), ("Aino", "business_owner"), ("factory", "it")):
            with self.assertRaises(DecisionRefused):
                set_site_mode(self.factory, "air-gapped", person=person, persona=persona, reason="isolated plant")
        with self.assertRaises(ValueError):
            set_site_mode(self.factory, "offline", person="Ilkka", persona="it", reason="isolated plant")
        with self.assertRaises(ValueError):
            set_site_mode(self.factory, "air-gapped", person="Ilkka", persona="it", reason=" ")
        set_site_mode(self.factory, "air-gapped", person="Ilkka", persona="it", reason="the plant network is isolated")
        gapped = build_pack(self.project)
        self.assertEqual((first["version"], gapped["version"]), ("1.0.0", "1.1.0"))   # pack version = behaviour version
        self.assertEqual(levels(gapped), ["L1", "L2", "L4"])
        self.assertEqual((step(gapped, "L3")["applies"], step(gapped, "L3")["why"]),
                         (False, "nothing leaves an air-gapped site"))
        self.assertEqual(step(gapped, "L1")["scope"], "inside the site only")
        self.assertEqual(build_pack(self.project)["version"], "1.1.0")              # the same declarations
        # a person setting the default explicitly changes where the mode came from, not the behaviour
        set_site_mode(self.factory, "connected", person="Kaisa", persona="compliance", reason="the link is back")
        connected = build_pack(self.project)
        self.assertEqual(connected["declared"]["site_mode"]["source"], "factory policy")
        self.assertEqual(connected["content_sha256"], first["content_sha256"])
        # restricted: the cloud only for public data, whatever else the policy lists
        set_site_mode(self.factory, "restricted", person="Kaisa", persona="compliance", reason="audit season",
                      cloud_data_classes=["internal"])
        restricted = build_pack(self.project)
        self.assertEqual(levels(restricted), ["L1", "L2", "L4"])
        self.assertIn("no data class may go to the cloud from a restricted site", step(restricted, "L3")["why"])
        both = ladder({"mode": "restricted", "cloud_data_classes": ["internal", "public"]})
        self.assertEqual(both[2]["data_classes"], ["public"])
        self.assertEqual(ladder({"mode": "connected", "cloud_data_classes": ["internal", "public"]})[2]["data_classes"],
                         ["internal", "public"])
        # the autonomy cap shares the policy file and leaves the site mode as it was
        set_cap(self.factory, 3, person="Aino", persona="business_owner", reason="sandbox only this month")
        self.assertEqual(site_policy(self.factory)["mode"], "restricted")
        kinds = [r["event"]["payload"] for r in factory_project(self.factory).ledger().of_kind("site_mode_set")]
        self.assertEqual([(k["to"], k["by"], k["persona"]) for k in kinds],
                         [("air-gapped", "Ilkka", "it"), ("connected", "Kaisa", "compliance"),
                          ("restricted", "Kaisa", "compliance")])
        # a pack edited after it was written no longer matches its record
        path = self.project.path("releases", "1", "capability-pack.json")
        edited = json.loads(path.read_text(encoding="utf-8"))
        edited["declared"]["site_mode"]["levels"] = ["L1", "L2", "L3", "L4"]
        self.assertNotEqual(content_sha256(edited), edited["content_sha256"])
        self.assertIn("its content does not hash to its content_sha256", pack_problems(self.project, edited))


if __name__ == "__main__":
    unittest.main()
