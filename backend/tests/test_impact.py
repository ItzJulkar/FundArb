import pytest

from app.impact import BASE_FEES, _lighter_levels, _perpl_fee_rate, _with_fee, simulate_book


def test_buy_walks_asks_by_quote_notional():
    result = simulate_book([[100.0, 5.0], [110.0, 10.0]], "buy", 1_000.0)
    assert result["filled_ratio"] == 1.0
    assert result["best_price"] == 100.0
    assert result["vwap"] == pytest.approx(1_000 / (5 + 500 / 110))
    assert result["slippage_usd"] == pytest.approx(1_000 - (5 + 500 / 110) * 100)


def test_sell_walks_bids_by_best_price_notional():
    result = simulate_book([[100.0, 5.0], [90.0, 10.0]], "sell", 1_000.0)
    assert result["filled_ratio"] == 1.0
    assert result["vwap"] == 95.0
    assert result["slippage"] == pytest.approx(0.05)
    assert result["slippage_usd"] == pytest.approx(50.0)


def test_insufficient_depth_is_not_presented_as_full_fill():
    result = simulate_book([[100.0, 1.0]], "buy", 1_000.0)
    assert result["filled_ratio"] == pytest.approx(0.1)


def test_execution_impact_includes_half_spread_against_mid():
    buy = simulate_book([[101.0, 20.0]], "buy", 1_000.0, 100.0)
    sell = simulate_book([[99.0, 20.0]], "sell", 1_000.0, 100.0)
    assert buy["slippage"] == pytest.approx(0.01)
    assert sell["slippage"] == pytest.approx(0.01)
    assert buy["slippage_usd"] == pytest.approx(1_000 - (1_000 / 101) * 100)
    assert sell["slippage_usd"] == pytest.approx(10.0)


def test_fee_and_total_cost_are_explicit():
    result = _with_fee(simulate_book([[100.0, 20.0]], "buy", 1_000.0), 0.0005)
    assert result["fee_usd"] == pytest.approx(0.5)
    assert result["total_cost_usd"] == pytest.approx(0.5)


def test_risex_default_taker_fee_matches_published_tier_one_rate():
    assert BASE_FEES["risex"][0] == 0.00030


def test_grvt_default_taker_fee_matches_published_level_one_rate():
    assert BASE_FEES["grvt"][0] == 0.00045


def test_perpl_fee_uses_public_micros_scale():
    assert _perpl_fee_rate(690) == pytest.approx(0.00069)


def test_lighter_raw_orders_are_aggregated_and_sorted():
    orders = [
        {"price": "101", "remaining_base_amount": "2"},
        {"price": "100", "remaining_base_amount": "1"},
        {"price": "101", "remaining_base_amount": "3"},
    ]
    assert _lighter_levels(orders, reverse=True) == [[101.0, 5.0], [100.0, 1.0]]
