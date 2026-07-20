"""Symbol + funding interval normalization helpers."""
from __future__ import annotations

import re

_STRIP_SUFFIXES = (
    "USDT",
    "USDC",
    "USD",
    "PERP",
    "-PERP",
    "_PERP",
)

_RE_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def base_symbol(raw: str) -> str:
    """Map exchange-native pair names to a shared base ticker (BTC, ETH, …)."""
    s = (raw or "").strip().upper()
    if not s:
        return ""
    # common separators
    for sep in ("/", "-", "_", ":"):
        if sep in s:
            left = s.split(sep)[0]
            # HL-style xyz:BTC → BTC
            if left in {"XYZ", "FLX", "HENA", "KINETIQ", "PARA", "TRADE"} and len(s.split(sep)) > 1:
                s = s.split(sep)[-1]
            else:
                s = left
            break
    # strip quote / perp suffixes repeatedly
    changed = True
    while changed:
        changed = False
        for suf in _STRIP_SUFFIXES:
            if s.endswith(suf) and len(s) > len(suf):
                s = s[: -len(suf)]
                changed = True
    s = _RE_NON_ALNUM.sub("", s)
    # leftovers like 1000PEPE → keep; WBTC stays WBTC
    return s


def to_hourly(rate: float, interval_hours: float) -> float:
    if not interval_hours or interval_hours <= 0:
        return rate
    return rate / interval_hours


def to_period(rate_hourly: float, hours: float) -> float:
    return rate_hourly * hours


def to_apy(rate_hourly: float) -> float:
    # simple non-compounded annualization
    return rate_hourly * 24 * 365
