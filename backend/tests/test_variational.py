import unittest

from app.collectors import _row, _variational_interval_rate


class VariationalFundingConversionTests(unittest.TestCase):
    def test_btc_ui_example_converts_hourly_bps_to_8h_rate(self):
        interval_rate = _variational_interval_rate("0.08125", 8.0)
        row = _row(
            exchange="variational",
            symbol_raw="BTC",
            rate=interval_rate,
            interval_h=8.0,
        )

        self.assertAlmostEqual(interval_rate, 0.000065)
        self.assertAlmostEqual(row["rate_1h"], 0.000008125)
        self.assertAlmostEqual(row["rate_8h"], 0.000065)

    def test_one_hour_market_stays_on_same_hourly_basis(self):
        interval_rate = _variational_interval_rate("0.125", 1.0)
        row = _row(
            exchange="variational",
            symbol_raw="TEST",
            rate=interval_rate,
            interval_h=1.0,
        )

        self.assertAlmostEqual(interval_rate, 0.0000125)
        self.assertAlmostEqual(row["rate_8h"], 0.0001)


if __name__ == "__main__":
    unittest.main()