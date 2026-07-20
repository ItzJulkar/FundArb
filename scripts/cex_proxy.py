#!/usr/bin/env python3
"""Tiny CEX funding proxy for geo-blocked collectors. Bind 0.0.0.0:8790"""
from __future__ import annotations

import json
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

UA = "FundArb-CEX-Proxy/1.3"


def http_get(url: str, timeout: float = 25.0):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def binance():
    data = http_get("https://fapi.binance.com/fapi/v1/premiumIndex")
    out = []
    for it in data:
        sym = it.get("symbol") or ""
        if not sym.endswith("USDT"):
            continue
        out.append(
            {
                "exchange": "binance",
                "symbol": sym,
                "lastFundingRate": it.get("lastFundingRate"),
                "markPrice": it.get("markPrice"),
                "indexPrice": it.get("indexPrice"),
                "nextFundingTime": it.get("nextFundingTime"),
                "interval_h": 8,
            }
        )
    return out


def bybit():
    data = http_get("https://api.bybit.com/v5/market/tickers?category=linear")
    items = (data.get("result") or {}).get("list") or []
    out = []
    for it in items:
        sym = it.get("symbol") or ""
        if not sym.endswith("USDT"):
            continue
        out.append(
            {
                "exchange": "bybit",
                "symbol": sym,
                "fundingRate": it.get("fundingRate"),
                "markPrice": it.get("markPrice"),
                "indexPrice": it.get("indexPrice"),
                "openInterestValue": it.get("openInterestValue"),
                "nextFundingTime": it.get("nextFundingTime"),
                "fundingIntervalHour": it.get("fundingIntervalHour"),
                "turnover24h": it.get("turnover24h"),
            }
        )
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter
        pass

    def _send(self, code: int, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/health", "/"):
            self._send(200, {"ok": True, "service": "cex-proxy"})
            return
        if u.path not in ("/cex", "/api/cex"):
            self._send(404, {"error": "not found"})
            return
        q = parse_qs(u.query)
        which = (q.get("exchange") or ["all"])[0].lower()
        try:
            out = {"ts": __import__("time").time().__int__(), "exchanges": {}}
            if which in ("binance", "all"):
                out["exchanges"]["binance"] = binance()
            if which in ("bybit", "all"):
                out["exchanges"]["bybit"] = bybit()
            self._send(200, out)
        except Exception as e:
            self._send(502, {"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    host, port = "0.0.0.0", 8790
    print(f"cex-proxy on {host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), H).serve_forever()
