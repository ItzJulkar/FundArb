"""Live taker-fee and order-book impact estimates for fixed USD notionals."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .store import store

SIZES = (1_000.0, 10_000.0, 100_000.0)
UA = "TradeImpact/1.0 (+https://github.com/ItzJulkar/FundArb)"

# Public/base rates. Actual account fees can differ with VIP tier, token discounts,
# referrals, or promotions. Nado and SoDEX are read from live market metadata.
BASE_FEES = {
    "binance": (0.00050, "Base USD-M taker rate; account tier may differ"),
    "bybit": (0.00055, "Base derivatives taker rate; account tier may differ"),
    "hyperliquid": (0.00045, "Base perp taker rate; volume tier may differ"),
    "extended": (0.00025, "Published base taker rate"),
    "risex": (0.00050, "Base taker rate; account tier may differ"),
    "variational": (0.0, "Omni charges zero explicit trading fees; spread is embedded"),
}

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _f(value: Any) -> float:
    return float(value)


def simulate_book(levels: list[list[float]], side: str, notional: float) -> dict[str, Any]:
    """Walk asks by quote notional or bids by equivalent best-price base size."""
    if not levels:
        raise ValueError("empty order book")
    best = levels[0][0]
    remaining = notional
    base_qty = 0.0
    quote_qty = 0.0

    if side == "buy":
        for price, qty in levels:
            take_quote = min(remaining, price * qty)
            base_qty += take_quote / price
            quote_qty += take_quote
            remaining -= take_quote
            if remaining <= 1e-9:
                break
        filled_notional = quote_qty
        vwap = quote_qty / base_qty if base_qty else 0.0
        slippage = max(0.0, vwap / best - 1.0) if best and base_qty else 0.0
        slippage_usd = max(0.0, quote_qty - base_qty * best)
    else:
        target_base = notional / best
        remaining_base = target_base
        for price, qty in levels:
            take_base = min(remaining_base, qty)
            base_qty += take_base
            quote_qty += take_base * price
            remaining_base -= take_base
            if remaining_base <= 1e-12:
                break
        filled_notional = base_qty * best
        vwap = quote_qty / base_qty if base_qty else 0.0
        slippage = max(0.0, 1.0 - vwap / best) if best and base_qty else 0.0
        slippage_usd = max(0.0, base_qty * best - quote_qty)

    return {
        "notional": notional,
        "best_price": best,
        "vwap": vwap,
        "slippage": slippage,
        "slippage_usd": slippage_usd,
        "filled_ratio": min(1.0, filled_notional / notional) if notional else 1.0,
    }


def _with_fee(result: dict[str, Any], fee_rate: float) -> dict[str, Any]:
    fee_usd = result["notional"] * fee_rate
    return {
        **result,
        "fee_usd": fee_usd,
        "total_cost_usd": result["slippage_usd"] + fee_usd,
    }


def _market_symbols(base: str) -> dict[str, str]:
    rows = store.snapshot()["rows"]
    return {
        row["exchange"]: row["symbol"]
        for row in rows
        if row["base"] == base and row["exchange"] in {
            "binance", "bybit", "hyperliquid", "extended",
            "risex", "variational", "nado", "sodex",
        }
    }


def available_bases() -> list[dict[str, Any]]:
    coverage: dict[str, set[str]] = {}
    for row in store.snapshot()["rows"]:
        coverage.setdefault(row["base"], set()).add(row["exchange"])
    return [
        {"base": base, "venues": len(exchanges)}
        for base, exchanges in sorted(coverage.items(), key=lambda item: (-len(item[1]), item[0]))
    ]


async def _binance(client: httpx.AsyncClient, symbol: str) -> tuple[list, list, float, str]:
    response = await client.get("https://fapi.binance.com/fapi/v1/depth", params={"symbol": symbol, "limit": 1000})
    response.raise_for_status()
    data = response.json()
    fee, note = BASE_FEES["binance"]
    return data["bids"], data["asks"], fee, note


async def _bybit(client: httpx.AsyncClient, symbol: str) -> tuple[list, list, float, str]:
    response = await client.get(
        "https://api.bybit.com/v5/market/orderbook",
        params={"category": "linear", "symbol": symbol, "limit": 500},
    )
    response.raise_for_status()
    data = response.json()["result"]
    fee, note = BASE_FEES["bybit"]
    return data["b"], data["a"], fee, note


async def _hyperliquid(client: httpx.AsyncClient, symbol: str) -> tuple[list, list, float, str]:
    response = await client.post("https://api.hyperliquid.xyz/info", json={"type": "l2Book", "coin": symbol})
    response.raise_for_status()
    levels = response.json()["levels"]
    bids = [[level["px"], level["sz"]] for level in levels[0]]
    asks = [[level["px"], level["sz"]] for level in levels[1]]
    fee, note = BASE_FEES["hyperliquid"]
    return bids, asks, fee, note


async def _extended(client: httpx.AsyncClient, symbol: str) -> tuple[list, list, float, str]:
    response = await client.get(f"https://api.starknet.extended.exchange/api/v1/info/markets/{symbol}/orderbook")
    response.raise_for_status()
    data = response.json()["data"]
    bids = [[level["price"], level["qty"]] for level in data["bid"]]
    asks = [[level["price"], level["qty"]] for level in data["ask"]]
    fee, note = BASE_FEES["extended"]
    return bids, asks, fee, note


async def _risex(client: httpx.AsyncClient, symbol: str) -> tuple[list, list, float, str]:
    markets = (await client.get("https://api.rise.trade/v1/markets")).json()["data"]["markets"]
    market = next(item for item in markets if item.get("display_name") == symbol or item.get("underlying") == symbol)
    response = await client.get("https://api.rise.trade/v1/orderbook", params={"market_id": market["market_id"]})
    response.raise_for_status()
    data = response.json()["data"]
    bids = [[level["price"], level["quantity"]] for level in data["bids"]]
    asks = [[level["price"], level["quantity"]] for level in data["asks"]]
    fee, note = BASE_FEES["risex"]
    return bids, asks, fee, note


async def _nado(client: httpx.AsyncClient, symbol: str) -> tuple[list, list, float, str]:
    response = await client.get(
        "https://gateway.prod.nado.xyz/v1/query",
        params={"type": "symbols"},
        headers={"Accept-Encoding": "gzip, deflate"},
    )
    response.raise_for_status()
    market = response.json()["data"]["symbols"][symbol]
    book = await client.get(
        "https://gateway.prod.nado.xyz/v1/query",
        params={"type": "market_liquidity", "product_id": market["product_id"], "depth": 100},
        headers={"Accept-Encoding": "gzip, deflate"},
    )
    book.raise_for_status()
    data = book.json()["data"]
    scale = 1e18
    bids = [[_f(price) / scale, _f(qty) / scale] for price, qty in data["bids"]]
    asks = [[_f(price) / scale, _f(qty) / scale] for price, qty in data["asks"]]
    fee = _f(market["taker_fee_rate_x18"]) / scale
    return bids, asks, fee, "Live base market fee; account volume tier may reduce it"


async def _sodex(client: httpx.AsyncClient, symbol: str) -> tuple[list, list, float, str]:
    root = "https://gateway-mainnet.sodex.dev/futures/fapi/market/v1/public"
    symbols = (await client.get(f"{root}/symbol/list")).json()["data"]
    market = next(item for item in symbols if item["symbol"] == symbol)
    response = await client.get(f"{root}/q/depth", params={"symbol": symbol, "level": 1000})
    response.raise_for_status()
    data = response.json()["data"]
    return data["b"], data["a"], _f(market["takerFee"]), "Live market taker fee"


async def _variational(client: httpx.AsyncClient, symbol: str) -> dict[str, Any]:
    response = await client.get("https://omni-client-api.prod.ap-northeast-1.variational.io/metadata/stats")
    response.raise_for_status()
    listing = next(item for item in response.json()["listings"] if item["ticker"] == symbol)
    quotes = listing["quotes"]
    base_bid = _f(quotes["base"]["bid"])
    base_ask = _f(quotes["base"]["ask"])
    output = {"exchange": "variational", "symbol": symbol, "fee_rate": 0.0, "fee_note": BASE_FEES["variational"][1], "model": "rfq_quotes", "buy": [], "sell": []}
    for size in SIZES:
        if size == 1_000:
            quote = quotes["size_1k"]
            estimated = False
        elif size == 100_000:
            quote = quotes["size_100k"]
            estimated = False
        else:
            # Omni publishes 1K and 100K indicative RFQ points. 10K is the
            # midpoint on a log-notional scale and is explicitly marked estimated.
            quote = {
                "bid": (_f(quotes["size_1k"]["bid"]) + _f(quotes["size_100k"]["bid"])) / 2,
                "ask": (_f(quotes["size_1k"]["ask"]) + _f(quotes["size_100k"]["ask"])) / 2,
            }
            estimated = True
        ask, bid = _f(quote["ask"]), _f(quote["bid"])
        buy_slippage = max(0.0, ask / base_ask - 1.0)
        sell_slippage = max(0.0, 1.0 - bid / base_bid)
        output["buy"].append({"notional": size, "best_price": base_ask, "vwap": ask, "slippage": buy_slippage, "slippage_usd": size * buy_slippage, "filled_ratio": 1.0, "fee_usd": 0.0, "total_cost_usd": size * buy_slippage, "estimated": estimated})
        output["sell"].append({"notional": size, "best_price": base_bid, "vwap": bid, "slippage": sell_slippage, "slippage_usd": size * sell_slippage, "filled_ratio": 1.0, "fee_usd": 0.0, "total_cost_usd": size * sell_slippage, "estimated": estimated})
    return output


FETCHERS = {
    "binance": _binance,
    "bybit": _bybit,
    "hyperliquid": _hyperliquid,
    "extended": _extended,
    "risex": _risex,
    "nado": _nado,
    "sodex": _sodex,
}


async def impact(base: str) -> dict[str, Any]:
    base = base.strip().upper()
    cached = _cache.get(base)
    if cached and time.monotonic() - cached[0] < 10:
        return cached[1]

    symbols = _market_symbols(base)
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": UA, "Accept": "application/json"}, limits=limits) as client:
        async def one(exchange: str, symbol: str) -> dict[str, Any]:
            try:
                if exchange == "variational":
                    return await _variational(client, symbol)
                bids, asks, fee, note = await FETCHERS[exchange](client, symbol)
                bids_f = [[_f(price), _f(qty)] for price, qty in bids]
                asks_f = [[_f(price), _f(qty)] for price, qty in asks]
                return {
                    "exchange": exchange,
                    "symbol": symbol,
                    "fee_rate": fee,
                    "fee_note": note,
                    "model": "order_book",
                    "buy": [_with_fee(simulate_book(asks_f, "buy", size), fee) for size in SIZES],
                    "sell": [_with_fee(simulate_book(bids_f, "sell", size), fee) for size in SIZES],
                }
            except Exception as exc:
                return {"exchange": exchange, "symbol": symbol, "error": f"{type(exc).__name__}: {exc}"}

        tasks = [one(exchange, symbol) for exchange, symbol in symbols.items() if exchange in FETCHERS or exchange == "variational"]
        venues = await asyncio.gather(*tasks)

    order = {name: index for index, name in enumerate(("binance", "bybit", "hyperliquid", "extended", "risex", "variational", "nado", "sodex"))}
    venues.sort(key=lambda item: order.get(item["exchange"], 99))
    result = {"ok": True, "base": base, "sizes": list(SIZES), "updated_at": int(time.time()), "venues": venues}
    _cache[base] = (time.monotonic(), result)
    return result
