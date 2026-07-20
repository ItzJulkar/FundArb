"""Multi-exchange funding rate collectors. Rates stored as decimal fractions (0.0001 = 0.01%)."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from .normalize import base_symbol, to_apy, to_hourly, to_period

log = logging.getLogger("fundarb.collectors")

UA = "FundArb/1.0 (+https://github.com/ItzJulkar/fundarb)"


def _f(x: Any, default: float = 0.0) -> float:
    try:
        if x is None or x == "":
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


def _row(
    *,
    exchange: str,
    symbol_raw: str,
    rate: float,
    interval_h: float,
    mark: float | None = None,
    index: float | None = None,
    oi: float | None = None,
    next_funding_ms: int | None = None,
    volume_24h: float | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    base = base_symbol(symbol_raw)
    if not base:
        return {}
    # rate = funding for one interval (decimal fraction)
    rate_1h = to_hourly(rate, interval_h)
    return {
        "exchange": exchange,
        "base": base,
        "symbol": symbol_raw,
        "rate": rate,  # per interval
        "interval_h": interval_h,
        "rate_1h": rate_1h,
        "rate_8h": to_period(rate_1h, 8),
        "rate_apy": to_apy(rate_1h),
        "mark": mark,
        "index": index,
        "oi": oi,
        "volume_24h": volume_24h,
        "next_funding_ms": next_funding_ms,
        "ts": int(time.time()),
        **(extra or {}),
    }


# Optional Vercel/edge proxy when VPS IP is geo-blocked by CEX (Binance 451 / Bybit 403).
CEX_PROXY = (
    __import__("os").environ.get("CEX_PROXY_URL", "").rstrip("/")
    or "http://127.0.0.1:8790/cex"
)


async def _cex_proxy(client: httpx.AsyncClient, exchange: str) -> list[dict]:
    r = await client.get(CEX_PROXY, params={"exchange": exchange}, timeout=40.0)
    r.raise_for_status()
    data = r.json()
    return (data.get("exchanges") or {}).get(exchange) or []


async def collect_binance(client: httpx.AsyncClient) -> list[dict]:
    items: list[dict]
    try:
        r = await client.get("https://fapi.binance.com/fapi/v1/premiumIndex")
        r.raise_for_status()
        items = r.json()
    except Exception as e:
        log.warning("binance direct failed (%s) — trying CEX proxy", e)
        items = await _cex_proxy(client, "binance")

    out = []
    for it in items:
        sym = it.get("symbol") or ""
        if not sym.endswith("USDT"):
            continue
        rate_key = "lastFundingRate" if "lastFundingRate" in it else "fundingRate"
        row = _row(
            exchange="binance",
            symbol_raw=sym,
            rate=_f(it.get(rate_key)),
            interval_h=_f(it.get("interval_h"), 8.0) or 8.0,
            mark=_f(it.get("markPrice")) or None,
            index=_f(it.get("indexPrice")) or None,
            next_funding_ms=int(it["nextFundingTime"]) if it.get("nextFundingTime") else None,
        )
        if row:
            out.append(row)
    return out


async def collect_bybit(client: httpx.AsyncClient) -> list[dict]:
    items: list[dict]
    try:
        r = await client.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "linear"},
        )
        r.raise_for_status()
        data = r.json()
        items = (data.get("result") or {}).get("list") or []
    except Exception as e:
        log.warning("bybit direct failed (%s) — trying CEX proxy", e)
        items = await _cex_proxy(client, "bybit")

    out = []
    for it in items:
        sym = it.get("symbol") or ""
        if not sym.endswith("USDT"):
            continue
        interval_h = _f(it.get("fundingIntervalHour") or it.get("interval_h"), 8.0) or 8.0
        row = _row(
            exchange="bybit",
            symbol_raw=sym,
            rate=_f(it.get("fundingRate") or it.get("lastFundingRate")),
            interval_h=interval_h,
            mark=_f(it.get("markPrice")) or None,
            index=_f(it.get("indexPrice")) or None,
            oi=_f(it.get("openInterestValue")) or None,
            next_funding_ms=int(float(it["nextFundingTime"])) if it.get("nextFundingTime") else None,
            volume_24h=_f(it.get("turnover24h")) or None,
        )
        if row:
            out.append(row)
    return out

async def collect_hyperliquid(client: httpx.AsyncClient) -> list[dict]:
    r = await client.post(
        "https://api.hyperliquid.xyz/info",
        json={"type": "metaAndAssetCtxs"},
    )
    r.raise_for_status()
    meta, ctxs = r.json()
    universe = meta.get("universe") or []
    out = []
    for u, c in zip(universe, ctxs):
        if u.get("isDelisted"):
            continue
        name = u.get("name") or ""
        # HL funding is hourly decimal
        row = _row(
            exchange="hyperliquid",
            symbol_raw=name,
            rate=_f(c.get("funding")),
            interval_h=1.0,
            mark=_f(c.get("markPx")) or None,
            index=_f(c.get("oraclePx")) or None,
            oi=_f(c.get("openInterest")) or None,
            volume_24h=_f(c.get("dayNtlVlm")) or None,
        )
        if row:
            out.append(row)
    return out


async def collect_extended(client: httpx.AsyncClient) -> list[dict]:
    r = await client.get("https://api.starknet.extended.exchange/api/v1/info/markets")
    r.raise_for_status()
    data = r.json()
    markets = data.get("data") or []
    out = []
    for m in markets:
        if (m.get("status") or "").upper() not in ("ACTIVE", "OPEN", ""):
            if m.get("active") is False:
                continue
        stats = m.get("marketStats") or {}
        name = m.get("name") or m.get("uiName") or ""
        # fundingRate is 1h applied rate (decimal)
        nf = stats.get("nextFundingRate")
        row = _row(
            exchange="extended",
            symbol_raw=name,
            rate=_f(stats.get("fundingRate")),
            interval_h=1.0,
            mark=_f(stats.get("markPrice")) or None,
            index=_f(stats.get("indexPrice")) or None,
            oi=_f(stats.get("openInterest")) or None,
            next_funding_ms=int(nf) if nf else None,
            volume_24h=_f(stats.get("dailyVolume")) or None,
        )
        if row:
            out.append(row)
    return out


async def collect_risex(client: httpx.AsyncClient) -> list[dict]:
    r = await client.get("https://api.rise.trade/v1/markets")
    r.raise_for_status()
    data = r.json()
    markets = (data.get("data") or {}).get("markets") or []
    out = []
    for m in markets:
        if m.get("active") is False:
            continue
        # Prefer explicit 8h rate; else current (hourly-ish)
        rate_8h = _f(m.get("funding_rate_8h"))
        rate_cur = _f(m.get("current_funding_rate"))
        if rate_8h != 0.0:
            rate, interval_h = rate_8h, 8.0
        else:
            # funding_interval is nanoseconds
            fi_ns = _f(m.get("funding_interval"), 3_600_000_000_000)
            interval_h = max(fi_ns / 3_600_000_000_000, 0.25) or 1.0
            rate, interval_h = rate_cur, interval_h
        nf = m.get("next_funding_time")
        next_ms = None
        if nf is not None:
            # often nanoseconds
            n = int(float(nf))
            next_ms = n // 1_000_000 if n > 10_000_000_000_000 else n
        name = m.get("display_name") or m.get("config", {}).get("name") or m.get("underlying") or ""
        row = _row(
            exchange="risex",
            symbol_raw=name,
            rate=rate,
            interval_h=interval_h,
            mark=_f(m.get("mark_price")) or None,
            index=_f(m.get("index_price")) or None,
            oi=_f(m.get("open_interest")) or None,
            next_funding_ms=next_ms,
            volume_24h=_f(m.get("quote_volume_24h")) or None,
        )
        if row:
            out.append(row)
    return out


async def collect_variational(client: httpx.AsyncClient) -> list[dict]:
    """
    Variational Omni /metadata/stats.
    funding_rate field is a percent number for the funding interval
    (e.g. 0.066584 means 0.066584%), NOT a 0-1 decimal.
    """
    r = await client.get(
        "https://omni-client-api.prod.ap-northeast-1.variational.io/metadata/stats"
    )
    r.raise_for_status()
    data = r.json()
    listings = data.get("listings") or []
    out = []
    for L in listings:
        ticker = L.get("ticker") or ""
        interval_s = _f(L.get("funding_interval_s"), 3600) or 3600
        interval_h = interval_s / 3600.0
        # percent → decimal fraction
        rate_pct = _f(L.get("funding_rate"))
        rate = rate_pct / 100.0
        oi_obj = L.get("open_interest") or {}
        oi = None
        try:
            oi = abs(_f(oi_obj.get("long_open_interest"))) + abs(
                _f(oi_obj.get("short_open_interest"))
            )
        except Exception:
            pass
        row = _row(
            exchange="variational",
            symbol_raw=ticker,
            rate=rate,
            interval_h=interval_h,
            mark=_f(L.get("mark_price")) or None,
            oi=oi or None,
            volume_24h=_f(L.get("volume_24h")) or None,
            extra={"name": L.get("name")},
        )
        if row:
            out.append(row)
    return out


async def collect_nado(client: httpx.AsyncClient) -> list[dict]:
    """
    Nado: symbols from gateway, funding from archive (24h rate, x18 fixed-point).
    """
    headers = {"Accept-Encoding": "gzip, deflate"}
    r = await client.get(
        "https://gateway.prod.nado.xyz/v1/query",
        params={"type": "symbols"},
        headers=headers,
    )
    r.raise_for_status()
    syms = (r.json().get("data") or {}).get("symbols") or {}
    perps = [
        (k, v)
        for k, v in syms.items()
        if (v.get("type") or "").lower() == "perp" and (v.get("trading_status") or "live") == "live"
    ]
    if not perps:
        return []

    product_ids = [int(v["product_id"]) for _, v in perps]
    id_to_sym = {int(v["product_id"]): k for k, v in perps}

    # batch funding_rates
    rates: dict[int, float] = {}
    # chunk to avoid huge payloads
    chunk = 40
    for i in range(0, len(product_ids), chunk):
        part = product_ids[i : i + chunk]
        fr = await client.post(
            "https://archive.prod.nado.xyz/v1",
            json={"funding_rates": {"product_ids": part}},
            headers=headers,
        )
        if fr.status_code == 200:
            body = fr.json()
            # map product_id -> {funding_rate_x18}
            if isinstance(body, dict):
                # may be nested under keys as strings
                for pid_s, val in body.items():
                    try:
                        pid = int(pid_s) if not isinstance(pid_s, int) else pid_s
                    except Exception:
                        continue
                    if isinstance(val, dict):
                        x18 = val.get("funding_rate_x18")
                    else:
                        continue
                    rates[pid] = _f(x18) / 1e18
            continue
        # fallback single
        for pid in part:
            try:
                one = await client.post(
                    "https://archive.prod.nado.xyz/v1",
                    json={"funding_rate": {"product_id": pid}},
                    headers=headers,
                )
                if one.status_code == 200:
                    val = one.json()
                    rates[pid] = _f(val.get("funding_rate_x18")) / 1e18
            except Exception as e:
                log.debug("nado funding %s: %s", pid, e)

    # oracle prices optional
    out = []
    for pid, rate_24h in rates.items():
        sym = id_to_sym.get(pid)
        if not sym:
            continue
        # docs: 24hr funding rate
        row = _row(
            exchange="nado",
            symbol_raw=sym,
            rate=rate_24h,
            interval_h=24.0,
        )
        if row:
            out.append(row)
    return out


async def collect_sodex(client: httpx.AsyncClient) -> list[dict]:
    """SoDEX (ValueChain perp DEX) — gateway-mainnet.sodex.dev"""
    base = "https://gateway-mainnet.sodex.dev"
    # symbols
    sr = await client.get(f"{base}/futures/fapi/market/v1/public/symbol/list")
    sr.raise_for_status()
    sbody = sr.json()
    symbols = sbody.get("data") or []
    active = [
        s
        for s in symbols
        if (s.get("contractType") or "").upper() == "PERPETUAL"
        and s.get("tradeSwitch")
        and s.get("state") == 0
        and s.get("symbol")
    ]
    if not active:
        return []

    # mark / index from agg-tickers (optional)
    marks: dict[str, tuple[float | None, float | None, float | None]] = {}
    try:
        tr = await client.get(f"{base}/futures/fapi/market/v1/public/q/agg-tickers")
        if tr.status_code == 200:
            for it in (tr.json().get("data") or []):
                sym = it.get("s") or ""
                if not sym:
                    continue
                marks[sym] = (
                    _f(it.get("m")) or None,
                    _f(it.get("i")) or None,
                    _f(it.get("v")) or None,
                )
    except Exception as e:
        log.debug("sodex agg-tickers: %s", e)

    async def one(sym: str) -> dict | None:
        r = await client.get(
            f"{base}/futures/fapi/market/v1/public/q/funding-rate",
            params={"symbol": sym},
        )
        if r.status_code != 200:
            return None
        data = (r.json() or {}).get("data") or {}
        rate = _f(data.get("fundingRate"))
        # collectionInterval is seconds (3600 = 1h)
        iv_s = _f(data.get("collectionInterval"), 3600.0) or 3600.0
        interval_h = iv_s / 3600.0
        mk, idx, vol = marks.get(sym, (None, None, None))
        nxt = data.get("nextCollectionTime")
        return _row(
            exchange="sodex",
            symbol_raw=sym,
            rate=rate,
            interval_h=interval_h,
            mark=mk,
            index=idx,
            volume_24h=vol,
            next_funding_ms=int(nxt) if nxt else None,
        )

    # ~80 symbols; fan-out
    results = await asyncio.gather(*(one(s["symbol"]) for s in active), return_exceptions=True)
    out: list[dict] = []
    for item in results:
        if isinstance(item, Exception):
            log.debug("sodex one: %s", item)
            continue
        if item:
            out.append(item)
    return out


COLLECTORS = {
    "binance": collect_binance,
    "bybit": collect_bybit,
    "hyperliquid": collect_hyperliquid,
    "extended": collect_extended,
    "risex": collect_risex,
    "variational": collect_variational,
    "nado": collect_nado,
    "sodex": collect_sodex,
}


async def collect_all(timeout: float = 25.0) -> dict[str, Any]:
    limits = httpx.Limits(max_connections=80, max_keepalive_connections=20)
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": UA, "Accept": "application/json"},
        limits=limits,
        follow_redirects=True,
    ) as client:
        tasks = {name: asyncio.create_task(fn(client)) for name, fn in COLLECTORS.items()}
        results: dict[str, Any] = {}
        errors: dict[str, str] = {}
        rows: list[dict] = []
        for name, task in tasks.items():
            try:
                items = await task
                results[name] = len(items)
                rows.extend(items)
            except Exception as e:
                log.exception("collector %s failed", name)
                errors[name] = f"{type(e).__name__}: {e}"
                results[name] = 0
        return {
            "rows": rows,
            "counts": results,
            "errors": errors,
            "ts": int(time.time()),
        }
