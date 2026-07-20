# FundArb

Cross-exchange **perpetual funding rate** tracker + simple arbitrage scanner.

## Exchanges

| Id | Source |
|----|--------|
| binance | `fapi.binance.com/fapi/v1/premiumIndex` |
| bybit | `api.bybit.com/v5/market/tickers?category=linear` |
| hyperliquid | `api.hyperliquid.xyz/info` `metaAndAssetCtxs` |
| extended | `api.starknet.extended.exchange/api/v1/info/markets` |
| risex | `api.rise.trade/v1/markets` |
| variational | `omni-client-api.../metadata/stats` |
| nado | gateway symbols + archive `funding_rates` |
| sodex | `gateway-mainnet.sodex.dev` symbol list + per-symbol funding-rate |

## Architecture

- **Backend (VPS, 24/7):** FastAPI poller → `/api/rates`, `/api/matrix`, `/api/arb`, `/api/health`
- **Frontend (Vercel):** static UI, polls API every 15s
- Rates normalized to **1h / 8h / APY** (simple, non-compounded)

## Local backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8788 --app-dir .
```

## Frontend

Open `frontend/public/index.html` via any static server, or set:

```js
// frontend/public/config.js
window.FUNDARB_API = "http://127.0.0.1:8788";
```

## VPS systemd

See `scripts/fundarb.service` and `scripts/deploy_vps.sh`.

## Disclaimer

Display / research only. Funding arb has basis, fees, borrow, liquidation, and latency risk. Not financial advice.
