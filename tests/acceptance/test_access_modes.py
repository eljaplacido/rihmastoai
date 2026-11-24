"""The access columns: a single operator, and access enforced through the organisation's identity
(docs/acceptance.md; FR-AM7, D-0016).

Enforced here means the kernel's own check behind every surface (kernel.access.require): each
decision is signed by a verified identity granted the persona on that project, by a binding to the
person, to a group they belong to, or to one project. The identity provider and the proxy in
front of the cockpit are the live identity test's (docs/acceptance.md, "The live acid test").
"""

from kernel import access as kaccess
from kernel.canon import Canon
from kernel.people import Identity

from .scripts import IT, OWNER, PRODUCT, AcceptanceCase, payloads

ISSUER = "https://login.example.org"
AINO, JAANA, PEKKA, MALLORY = (f"{ISSUER}#{s}" for s in ("aino-sub", "jaana-sub", "pekka-sub", "mallory-sub"))
IDENTITIES = {"Aino": Identity(AINO, "Aino", ("owners",)), "Jaana": Identity(JAANA, "Jaana"),
              "Pekka": Identity(PEKKA, "Pekka"), "Mallory": Identity(MALLORY, "Mallory")}


class SingleOperatorTest(AcceptanceCase):
    roads = False

    def test_FR_AM7_AC_1_without_an_access_file_one_operator_decides_and_the_factory_says_so(self):
        self.assertEqual(kaccess.describe(kaccess.load(self.factory)), "single operator: personas are self-declared")
        p = self.need("rooms", mode="mixed", maturity="demo")
        q1, q5 = (c for c in Canon(p).cards(kind="question"))
        self.decide(p, q1["id"], "answer", OWNER, "anyone in the office; the first booking stands")
        self.decide(p, q5["id"], "answer", ("Visitor", "stakeholder"), "the office manager")   # self-declared
        decisions = payloads(p, "decision")
        self.assertEqual([(d["person"], d["persona"]) for d in decisions], [OWNER, ("Visitor", "stakeholder")])
        self.assertFalse(any("identity" in d for d in decisions))


class EnforcedAccessTest(AcceptanceCase):
    def signed(self, who: tuple):
        return kaccess.signing(IDENTITIES[who[0]])

    def test_FR_AM7_AC_2_with_access_enforced_every_decision_of_a_production_run_is_signed_by_a_granted_identity(self):
        p = self.need("rooms", mode="mixed", maturity="production")
        self.enforce([{"group": "owners", "persona": "business_owner", "scope": "*"},
                      {"subject": JAANA, "persona": "it", "scope": "*"},
                      {"subject": PEKKA, "persona": "product_owner", "scope": [p.pid]},
                      {"subject": MALLORY, "persona": "stakeholder", "scope": ["another-project"]}],
                     {AINO: "Aino", JAANA: "Jaana", PEKKA: "Pekka", MALLORY: "Mallory"})
        self.assertTrue(kaccess.load(self.factory).enforced)
        card = Canon(p).cards(kind="question")[0]
        refused = {
            "nobody signed in": (None, OWNER),
            "a typed name that is not the identity": (IDENTITIES["Aino"], ("Someone", "business_owner")),
            "a persona not granted": (IDENTITIES["Pekka"], ("Pekka", "business_owner")),
            "a project outside the scope": (IDENTITIES["Mallory"], ("Mallory", "stakeholder")),
        }
        for why, (ident, who) in refused.items():
            with self.subTest(why), kaccess.signing(ident), self.assertRaises(kaccess.AccessRefused):
                Canon(p).decide(card["id"], "answer", person=who[0], persona=who[1], reason="refused")
        self.assertEqual(payloads(p, "decision"), [])                       # nothing was recorded
        self.answer_blocking(p)                                             # Aino, through her group
        plan = self.run_chain(p)
        self.decide(p, plan["waiting_on"][0], "approve", PRODUCT, "The plan covers the office")   # Pekka, this project
        out, decided = self.ship(p)
        self.assertEqual(decided, [("validation", "business_owner"), ("deploy_gate", "it")])
        self.assertDelivered(p, out, "production")
        signed = {(d["person"], d["persona"], d.get("identity")) for d in payloads(p, "decision")}
        self.assertEqual(signed, {("Aino", "business_owner", AINO), ("Pekka", "product_owner", PEKKA),
                                  ("Jaana", "it", JAANA)})
        self.assertIn(IT, {(d["person"], d["persona"]) for d in payloads(p, "decision") if d["kind"] == "deploy_gate"})
