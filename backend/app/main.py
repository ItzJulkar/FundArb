"""FundArb API — multi-exchange funding rates + arb."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .collectors import collect_all
from .impact import available_bases, impact
from .store import store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("fundarb")

POLL_SECONDS = float(os.getenv("POLL_SECONDS", "20"))
HOST_PUBLIC = os.getenv("PUBLIC_URL", "")


async def poll_loop(stop: asyncio.Event) -> None:
    # first fetch immediately
    while not stop.is_set():
        t0 = time.perf_counter()
        try:
            payload = await collect_all()
            ms = (time.perf_counter() - t0) * 1000
            store.update(payload, ms)
            log.info(
                "poll ok rows=%s counts=%s errors=%s ms=%.0f",
                len(payload.get("rows") or []),
                payload.get("counts"),
                payload.get("errors") or {},
                ms,
            )
        except Exception:
            log.exception("poll failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    task = asyncio.create_task(poll_loop(stop))
    log.info("FundArb started poll=%ss", POLL_SECONDS)
    yield
    stop.set()
    await task


app = FastAPI(
    title="FundArb",
    description="Cross-exchange perpetual funding rates & arbitrage scanner",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
@app.get("/api/health")
async def health() -> dict[str, Any]:
    snap = store.snapshot()
    return {
        "ok": True,
        "product": "FundArb",
        "updated_at": snap["updated_at"],
        "age_s": snap["age_s"],
        "poll_ms": snap["poll_ms"],
        "poll_n": snap["poll_n"],
        "counts": snap["counts"],
        "errors": snap["errors"],
        "n_rows": snap["n_rows"],
    }


@app.get("/api/rates")
async def rates(
    exchange: str | None = Query(None, description="Filter by exchange id"),
    base: str | None = Query(None, description="Filter by base symbol e.g. BTC"),
    q: str | None = Query(None, description="Search base/symbol"),
    limit: int = Query(5000, ge=1, le=20000),
) -> dict[str, Any]:
    snap = store.snapshot()
    rows = snap["rows"]
    if exchange:
        ex = exchange.strip().lower()
        rows = [r for r in rows if r["exchange"] == ex]
    if base:
        b = base.strip().upper()
        rows = [r for r in rows if r["base"] == b]
    if q:
        qq = q.strip().upper()
        rows = [
            r
            for r in rows
            if qq in r["base"] or qq in (r.get("symbol") or "").upper()
        ]
    # sort by |rate_8h| desc
    rows = sorted(rows, key=lambda r: abs(r.get("rate_8h") or 0), reverse=True)[:limit]
    return {
        "updated_at": snap["updated_at"],
        "age_s": snap["age_s"],
        "poll_ms": snap["poll_ms"],
        "counts": snap["counts"],
        "errors": snap["errors"],
        "n": len(rows),
        "rows": rows,
    }


@app.get("/api/matrix")
async def matrix(
    bases: str | None = Query(
        None, description="Comma bases; default top by venue coverage"
    ),
    limit_bases: int = Query(80, ge=5, le=300),
) -> dict[str, Any]:
    """Pivot: base → {exchange: rate_8h} for table UI."""
    snap = store.snapshot()
    rows = snap["rows"]
    by_base: dict[str, dict[str, dict]] = {}
    for r in rows:
        b = r["base"]
        by_base.setdefault(b, {})[r["exchange"]] = {
            "rate_8h": r["rate_8h"],
            "rate_apy": r["rate_apy"],
            "rate_1h": r["rate_1h"],
            "symbol": r["symbol"],
            "mark": r.get("mark"),
            "exchange": r["exchange"],
        }

    if bases:
        want = {x.strip().upper() for x in bases.split(",") if x.strip()}
        items = [(b, by_base[b]) for b in want if b in by_base]
    else:
        items = sorted(
            by_base.items(),
            key=lambda kv: (-len(kv[1]), kv[0]),
        )[:limit_bases]

    exchanges = sorted({ex for _, m in items for ex in m})
    return {
        "updated_at": snap["updated_at"],
        "age_s": snap["age_s"],
        "exchanges": exchanges,
        "bases": [
            {"base": b, "venues": m, "n_venues": len(m)} for b, m in items
        ],
    }


@app.get("/api/arb")
async def arb(
    min_spread_bps: float = Query(
        0.5, description="Min 8h spread in bps (0.5 = 0.005%)"
    ),
    min_exchanges: int = Query(2, ge=2, le=10),
    limit: int = Query(200, ge=1, le=2000),
) -> dict[str, Any]:
    min_spread_8h = (min_spread_bps / 10000.0)  # bps → decimal
    data = store.arb(min_spread_8h=min_spread_8h, min_exchanges=min_exchanges)
    data["opportunities"] = data["opportunities"][:limit]
    data["n"] = len(data["opportunities"])
    data["min_spread_bps"] = min_spread_bps
    return data


@app.get("/api/impact/bases")
async def impact_bases() -> dict[str, Any]:
    return {"bases": available_bases()}


@app.get("/api/impact")
async def trade_impact(
    base: str = Query("BTC", min_length=1, max_length=32),
) -> dict[str, Any]:
    return await impact(base)


@app.get("/")
async def root() -> JSONResponse:
    return JSONResponse(
        {
            "product": "FundArb API",
            "endpoints": [
                "/api/health",
                "/api/rates",
                "/api/matrix",
                "/api/arb",
                "/api/impact/bases",
                "/api/impact?base=BTC",
            ],
        }
    )
