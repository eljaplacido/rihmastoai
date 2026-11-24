import unittest

from app.stock import change, level


class StockTest(unittest.TestCase):
    def test_level_of_a_stocked_item(self):
        self.assertEqual(level({"A-1": 3}, "A-1"), 3)

    def test_an_item_not_stocked_is_zero(self):
        self.assertEqual(level({}, "B-2"), 0)

    def test_a_change_is_audited(self):
        stock, audit_log = {"A-1": 3}, []
        change(stock, audit_log, "A-1", 5, "worker@example.org")
        self.assertEqual(audit_log[0]["from"], 3)
        self.assertEqual(stock["A-1"], 5)


if __name__ == "__main__":
    unittest.main()
