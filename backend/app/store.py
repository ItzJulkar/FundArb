"""Funding rate snapshot store + cross-exchange arb engine."""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any


class Store:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.rows: list[dict[str, Any]] = []
        self.counts: dict[str, int] = {}
        self.errors: dict[str, str] = {}
        self.updated_at: int = 0
        self.poll_ms: float = 0.0
        self.poll_n: int = 0

    def update(self, payload: dict[str, Any], poll_ms: float) -> None:
        with self._lock:
            self.rows = payload.get("rows") or []
            self.counts = payload.get("counts") or {}
            self.errors = payload.get("errors") or {}
            self.updated_at = int(payload.get("ts") or time.time())
            self.poll_ms = poll_ms
            self.poll_n += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "updated_at": self.updated_at,
                "age_s": max(0, int(time.time()) - self.updated_at) if self.updated_at else None,
                "poll_ms": round(self.poll_ms, 1),
                "poll_n": self.poll_n,
                "counts": dict(self.counts),
                "errors": dict(self.errors),
                "n_rows": len(self.rows),
                "rows": list(self.rows),
            }

    def arb(self, min_spread_8h: float = 0.00005, min_exchanges: int = 2) -> dict[str, Any]:
        """
        For each base asset, find max/min rate_8h across exchanges.
        Positive spread = long cheap venue, short expensive venue (receive funding).
        """
        with self._lock:
            rows = list(self.rows)
            updated_at = self.updated_at

        by_base: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_base[r["base"]].append(r)

        opps = []
        for base, items in by_base.items():
            # one row per exchange (keep highest |oi| / latest)
            best: dict[str, dict] = {}
            for it in items:
                ex = it["exchange"]
                prev = best.get(ex)
                if prev is None or abs(it.get("oi") or 0) >= abs(prev.get("oi") or 0):
                    best[ex] = it
            if len(best) < min_exchanges:
                continue
            ranked = sorted(best.values(), key=lambda x: x["rate_8h"])
            lo, hi = ranked[0], ranked[-1]
            spread = hi["rate_8h"] - lo["rate_8h"]
            if spread < min_spread_8h:
                continue
            opps.append(
                {
                    "base": base,
                    "spread_8h": spread,
                    "spread_1h": hi["rate_1h"] - lo["rate_1h"],
                    "spread_apy": hi["rate_apy"] - lo["rate_apy"],
                    "long_exchange": lo["exchange"],  # pay lower / receive if negative
                    "long_rate_8h": lo["rate_8h"],
                    "long_symbol": lo["symbol"],
                    "short_exchange": hi["exchange"],
                    "short_rate_8h": hi["rate_8h"],
                    "short_symbol": hi["symbol"],
                    "venues": [
                        {
                            "exchange": x["exchange"],
                            "symbol": x["symbol"],
                            "rate_8h": x["rate_8h"],
                            "rate_apy": x["rate_apy"],
                            "mark": x.get("mark"),
                        }
                        for x in ranked
                    ],
                    "n_venues": len(ranked),
                }
            )

        opps.sort(key=lambda x: x["spread_8h"], reverse=True)
        return {
            "updated_at": updated_at,
            "age_s": max(0, int(time.time()) - updated_at) if updated_at else None,
            "n": len(opps),
            "opportunities": opps,
        }


store = Store()
