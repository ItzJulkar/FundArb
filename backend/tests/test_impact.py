import pytest

from app.impact import _with_fee, simulate_book


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


def test_fee_and_total_cost_are_explicit():
    result = _with_fee(simulate_book([[100.0, 20.0]], "buy", 1_000.0), 0.0005)
    assert result["fee_usd"] == pytest.approx(0.5)
    assert result["total_cost_usd"] == pytest.approx(0.5)
