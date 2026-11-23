import unittest

from kernel.metrics import pass_rate
from kernel.pricing import price_run, spend

PRICES = {"currency": "USD", "models": {
    "local-q": {"local": True},
    "cloud-a": {"input": 1.0, "output": 4.0, "cached": 0.1},
    "cloud-half": {"input": 1.0},
}}


class PricingTest(unittest.TestCase):
    def test_FR_L4_AC_1_cost_from_tokens_and_the_table_local_and_cloud_apart(self):
        cloud = price_run("cloud-a", {"in": 1_000_000, "out": 500_000, "cached": 200_000}, prices=PRICES)
        self.assertEqual(cloud["kind"], "cloud")
        self.assertAlmostEqual(cloud["amount"], 0.8 + 0.02 + 2.0)
        local = price_run("local-q", {"in": 3000, "out": 1000}, prices=PRICES)
        self.assertEqual((local["kind"], local["amount"], local["local_tokens"]), ("local", 0.0, 4000))
        total = spend([cloud, local])
        self.assertAlmostEqual(total["cloud"], 2.82)
        self.assertEqual(total["local_tokens"], 4000)
        self.assertEqual(total["unmeasured_runs"], 0)

    def test_FR_L4_AC_2_a_model_missing_from_the_table_is_not_measured_never_zero(self):
        for model in ("unknown-model", "cloud-half", None):
            c = price_run(model, {"in": 10, "out": 10}, prices=PRICES)
            self.assertFalse(c["measured"])
            self.assertIsNone(c["amount"])
        no_tokens = price_run("cloud-a", {"in": None, "out": None}, prices=PRICES)
        self.assertIsNone(no_tokens["amount"])
        total = spend([price_run("cloud-a", {"in": 10, "out": 10}, prices=PRICES),
                       price_run("unknown-model", {"in": 10, "out": 10}, prices=PRICES)])
        self.assertIsNone(total["cloud"])                    # the sum is not measured either
        self.assertEqual(total["unmeasured_runs"], 1)
        self.assertGreater(total["cloud_measured_part"], 0)


class MetricsTest(unittest.TestCase):
    def test_FR_C6_AC_1_pass_rate_leaves_out_apparatus_failures_and_counts_them_apart(self):
        runs = [{"verdict": "passed"}, {"verdict": "passed"}, {"verdict": "failed"},
                {"verdict": "not measured", "apparatus_failure": True},
                {"verdict": "not measured", "apparatus_failure": True}]
        r = pass_rate(runs)
        self.assertAlmostEqual(r["rate"], 2 / 3)
        self.assertEqual((r["measured"], r["apparatus_failures"]), (3, 2))
        self.assertIsNone(pass_rate([{"verdict": "not measured", "apparatus_failure": True}])["rate"])


if __name__ == "__main__":
    unittest.main()
