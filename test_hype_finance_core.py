import unittest
from hype_finance_core import Entry, FinanceError, wallet_balance, split_breeder_payment, validate_transfer


class WalletTests(unittest.TestCase):
    def test_only_confirmed_entries(self):
        rows = [Entry("a", "player", 100, True), Entry("b", "player", -30, True),
                Entry("c", "player", 999, False), Entry("d", "other", 20, True)]
        self.assertEqual(wallet_balance(rows, "player"), 70)

    def test_rejects_duplicate_transaction(self):
        with self.assertRaises(FinanceError):
            wallet_balance([Entry("a", "p", 10, True), Entry("a", "p", 10, True)], "p")

    def test_breeder_fee(self):
        self.assertEqual(split_breeder_payment(600000, "25"), (150000, 450000))
        self.assertEqual(split_breeder_payment(101, "10"), (10, 91))

    def test_invalid_fee(self):
        for rate in ("-1", "101", "NaN"):
            with self.assertRaises(FinanceError):
                split_breeder_payment(100, rate)

    def test_transfer_validation(self):
        validate_transfer(100, 100, "a", "b")
        with self.assertRaises(FinanceError):
            validate_transfer(100, 101, "a", "b")
        with self.assertRaises(FinanceError):
            validate_transfer(100, 10, "a", "a")


if __name__ == "__main__":
    unittest.main()
