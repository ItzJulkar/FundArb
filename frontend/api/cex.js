// CEX proxy — Node serverless in iad1 (US) so EU VPS bypasses Binance/Bybit geo-block.
export const config = {
  runtime: "nodejs",
  regions: ["iad1"],
  maxDuration: 30,
};

const UA = "FundArb-CEX-Proxy/1.2";

async function binance() {
  const r = await fetch("https://fapi.binance.com/fapi/v1/premiumIndex", {
    headers: { "User-Agent": UA },
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`binance ${r.status} ${t.slice(0, 120)}`);
  }
  const data = await r.json();
  return data
    .filter((it) => String(it.symbol || "").endsWith("USDT"))
    .map((it) => ({
      exchange: "binance",
      symbol: it.symbol,
      lastFundingRate: it.lastFundingRate,
      markPrice: it.markPrice,
      indexPrice: it.indexPrice,
      nextFundingTime: it.nextFundingTime,
      interval_h: 8,
    }));
}

async function bybit() {
  const r = await fetch(
    "https://api.bybit.com/v5/market/tickers?category=linear",
    { headers: { "User-Agent": UA } }
  );
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`bybit ${r.status} ${t.slice(0, 120)}`);
  }
  const data = await r.json();
  const list = (data.result && data.result.list) || [];
  return list
    .filter((it) => String(it.symbol || "").endsWith("USDT"))
    .map((it) => ({
      exchange: "bybit",
      symbol: it.symbol,
      fundingRate: it.fundingRate,
      markPrice: it.markPrice,
      indexPrice: it.indexPrice,
      openInterestValue: it.openInterestValue,
      nextFundingTime: it.nextFundingTime,
      fundingIntervalHour: it.fundingIntervalHour,
      turnover24h: it.turnover24h,
    }));
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "s-maxage=15, stale-while-revalidate=30");
  if (req.method === "OPTIONS") {
    res.status(204).end();
    return;
  }

  const url = new URL(req.url, "http://x");
  const which = (url.searchParams.get("exchange") || "all").toLowerCase();
  const out = { ts: Math.floor(Date.now() / 1000), exchanges: {}, region: "iad1" };

  try {
    if (which === "binance" || which === "all") {
      out.exchanges.binance = await binance();
    }
    if (which === "bybit" || which === "all") {
      out.exchanges.bybit = await bybit();
    }
    res.status(200).json(out);
  } catch (e) {
    res.status(502).json({ error: String(e && e.message ? e.message : e) });
  }
}
