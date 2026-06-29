# Indian AI Trading Bot

Production-grade, AI-powered algorithmic trading platform for the Indian stock market (NSE/BSE), focused on scalping, intraday, swing trading, and NIFTY/BANKNIFTY options.

## Architecture

Microservices-based system with FastAPI, PostgreSQL, Redis, Celery, React, and Docker.

```
trading-bot/
├── docker-compose.yml          # Local / dev deployment
├── docker-compose.prod.yml     # Production overrides (port 80 only)
├── docs/DEPLOY.md              # VPS deployment runbook
├── .env.example
├── scripts/
│   └── init-db.sql
├── services/
│   ├── shared/                 # trading_shared Python package
│   ├── api-gateway/            # :8000
│   ├── auth-service/           # :8001 JWT, RBAC, Angel One sessions
│   ├── market-data-service/    # :8002
│   ├── strategy-engine/        # :8003
│   ├── ai-decision-engine/     # :8004
│   ├── risk-manager/           # :8005
│   ├── order-execution-engine/ # :8006
│   ├── backtesting-engine/     # :8007
│   ├── portfolio-manager/      # :8008
│   ├── alert-engine/           # :8009
│   ├── analytics-engine/       # :8010
│   ├── trade-journal-engine/   # :8011
│   ├── admin-dashboard/        # :8012
│   └── celery-worker/
├── frontend/                   # React + Tailwind dashboard
└── backend/                    # Legacy monolith (Phase 1+ uses services/)
```

## Phase 8 (Current)

- **Production validation** — fail-fast checks for weak JWT/encryption when `ENV=production`
- **Auth lockdown** — disable public registration; force `viewer` role for new signups in prod
- **API gateway hardening** — security headers, request logging, Redis-backed rate limits on login/orders
- **Health probes** — `/health/live`, `/health/ready` (Postgres + Redis), aggregate gateway check
- **Alert engine** — Telegram + SMTP delivery with admin test endpoint
- **docker-compose.prod.yml** — single public port (80), restart policies, resource limits
- **CI pipeline** — GitHub Actions build for Python, frontend, and Docker images
- **Deploy runbook** — `docs/DEPLOY.md` and `scripts/deploy.sh`

## Phase 7

- **Order execution engine** — risk-gated live orders via Angel One SmartAPI
- **Pre-trade risk check** — every order evaluated by `RiskManager` before broker call
- **Order lifecycle** — place, modify, cancel, order book, trade book
- **Persisted orders** — `broker_orders` table with risk approval audit trail
- **Portfolio manager** — live holdings and positions sync from Angel One
- **Live Trading UI** — order form with risk preview, trade feed, recent orders

## Phase 6

- **Backtesting engine** — bar-by-bar replay of production scalping, intraday, and swing engines
- **Historical data loader** — Angel One candles, PostgreSQL cache, or demo synthetic OHLCV
- **Backtest simulator** — uses shared `RiskEngine` for position sizing and daily loss limits
- **Async execution** — Celery task `backtest.run` with DB persistence (`backtest_runs`, `backtest_trades`)
- **Metrics** — win rate, max drawdown, profit factor, equity curve, trade log
- **Dashboard** — run form, job polling, Recharts equity curve, trades table

## Phase 5

- **Institutional dashboard** — sidebar navigation with 10 sections (Overview, Scalping, Intraday, Swing, Portfolio, Strategy, Backtesting, Journal, Alerts, AI)
- **TradingView charts** — embedded NIFTY, BANKNIFTY, and stock charts with dark theme
- **Recharts equity curve** — cumulative P&L visualization from trade journal
- **Risk manager microservice** — daily max loss, drawdown halt, position sizing, capital allocation limits
- **Admin dashboard BFF** — aggregated overview, equity curve, journal feed
- **Risk meter UI** — live gauges for daily loss, drawdown, and allocation usage

## Phase 4

- **AI decision engine** — ENTER / AVOID / EXIT / SCALE IN / PARTIAL BOOK
- 0–100 scoring from trend, volume, volatility, OI, Greeks, sentiment, sector, price action, R:R, regime
- Configurable threshold (`AI_DECISION_THRESHOLD`, default **75**)
- Human-readable **Why this trade?** reasoning panel
- Adaptive learning — weights adjust from trade journal outcomes
- Trade journal analysis (win rate, engine breakdown, mistake patterns)
- `ai-decision-engine` microservice with 60s auto-evaluation loop
- Celery beat task `ai.evaluate_all`

## Phase 3

- **Scalping engine** — NIFTY/BANKNIFTY multi-confirmation (ORB, VWAP, EMA, volume, OI, PCR, gamma)
- **Intraday engine** — auto-universe from scanner, top 10 ranked stocks with entry/SL/target
- **Swing engine** — daily/weekly setups with 5–20% target logic
- Weighted confirmation scoring (scalping requires **score ≥ 80**)
- `strategy-engine` microservice with 60s auto-run loop
- Signals cached in Redis + persisted to PostgreSQL
- Celery beat task `strategies.run_all`
- Dashboard strategy panels (scalping / intraday / swing)

## Phase 2

- Angel One SmartWebSocketV2 live streaming (NSE CM + NFO)
- Tick cache in Redis with client WebSocket fan-out
- OHLC candle builder (1m / 3m / 5m) with VWAP
- Continuous market scanner (volume, gaps, momentum, breakouts, sector strength)
- Option chain snapshots with PCR, OI, and Black-Scholes Greeks
- Historical candle API via Angel One
- Celery beat scanner task every 60 seconds
- Live market panel in dashboard

## Phase 1

- Enterprise folder structure for all 12 microservices
- Docker Compose stack (Postgres, Redis, Celery, Gateway, Frontend)
- Auth service with JWT access/refresh tokens and RBAC (`admin`, `trader`, `viewer`)
- Encrypted Angel One credential storage (Fernet)
- Production Angel One SmartAPI client (login, profile, funds, holdings, positions, LTP, orders)
- Redis-backed broker session cache
- API gateway routing to all services
- Frontend login + Angel One setup UI

## Quick Start

### 1. Configure environment

```bash
cp .env.example .env
```

Fill in:

- `JWT_SECRET` and `ENCRYPTION_KEY`
- Angel One credentials from [SmartAPI Developer Portal](https://smartapi.angelone.in)

### 2. Start the full stack

**Development:**

```bash
docker compose up --build
```

**Production (VPS):**

```bash
cp .env.example .env   # set ENV=production and strong secrets
./scripts/deploy.sh
```

See [docs/DEPLOY.md](docs/DEPLOY.md) for the full runbook.

### 3. Access services

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| API Gateway | http://localhost:8000/docs |
| Auth Service | http://localhost:8001/docs |
| Market Data | http://localhost:8002/docs |

### 4. Default admin login

- Username: `admin`
- Password: `Admin@12345`

Change this immediately in production.

## Angel One Setup Flow

1. Login to the dashboard
2. Open **Angel One Setup**
3. Save API key, client code, password, and TOTP secret (Base32 from authenticator QR)
4. Connect broker — session is stored in PostgreSQL and cached in Redis

Admin users can also call:

```http
POST /api/v1/broker/system/connect
```

to connect using environment-level credentials.

## API Endpoints (Phase 1)

### Auth

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/auth/me`

### Market Data

- `GET /api/v1/market/indices`
- `GET /api/v1/market/ltp`
- `GET /api/v1/market/tick/{exchange_type}/{token}`
- `GET /api/v1/market/candles/{token}?interval=1m`
- `GET /api/v1/market/historical`
- `GET /api/v1/market/scan/latest`
- `POST /api/v1/market/scan/run`
- `GET /api/v1/market/sector/strength`
- `GET /api/v1/market/option-chain/{underlying}`
- `GET /api/v1/market/stream/status`
- `POST /api/v1/market/stream/start`
- `WS /api/v1/market/ws`

### Broker (Angel One)

- `POST /api/v1/broker/credentials`
- `POST /api/v1/broker/connect`
- `POST /api/v1/broker/disconnect`
- `GET /api/v1/broker/status`
- `GET /api/v1/broker/profile`
- `GET /api/v1/broker/funds`
- `GET /api/v1/broker/holdings`
- `GET /api/v1/broker/positions`

### Strategies

- `POST /api/v1/strategies/run`
- `GET /api/v1/strategies/scalping`
- `GET /api/v1/strategies/intraday`
- `GET /api/v1/strategies/swing`
- `GET /api/v1/strategies/status`

### AI Decision Engine

- `POST /api/v1/ai/evaluate`
- `GET /api/v1/ai/decisions`
- `GET /api/v1/ai/decisions/{symbol}`
- `GET /api/v1/ai/journal/insights`
- `POST /api/v1/ai/journal/entries`
- `POST /api/v1/ai/learn`
- `GET /api/v1/ai/weights`

### Risk Manager

- `GET /api/v1/risk/status`
- `GET /api/v1/risk/limits`
- `PATCH /api/v1/risk/limits`
- `POST /api/v1/risk/equity`
- `POST /api/v1/risk/evaluate`
- `POST /api/v1/risk/register`
- `POST /api/v1/risk/reset-halt`
- `GET /api/v1/risk/can-trade`

### Admin Dashboard

- `GET /api/v1/admin/overview`
- `GET /api/v1/admin/equity-curve`
- `GET /api/v1/admin/journal`
- `GET /api/v1/admin/backtest/preview`

### Backtesting Engine

- `GET /api/v1/backtest/status`
- `POST /api/v1/backtest/run`
- `GET /api/v1/backtest/runs`
- `GET /api/v1/backtest/runs/{id}`

### Order Execution

- `GET /api/v1/orders/status`
- `POST /api/v1/orders`
- `GET /api/v1/orders`
- `GET /api/v1/orders/book`
- `GET /api/v1/orders/trades`
- `PATCH /api/v1/orders/{id}`
- `DELETE /api/v1/orders/{id}`

### Portfolio

- `GET /api/v1/portfolio/summary`
- `GET /api/v1/portfolio/positions`

## Development Roadmap

| Phase | Scope |
|-------|-------|
| 1 | Folder structure, Docker, Auth, Angel One |
| 2 | Market data engine (WebSocket streaming, scanners) |
| 3 | Scalping, intraday, swing strategies |
| 4 | AI decision engine |
| 5 | Full institutional dashboard |
| 6 | Backtesting engine |
| 7 | Order execution & live trading |
| 8 | Production deployment hardening | **Current** |
| — | Paper trading (pre–Angel One) | Simulated orders, default mode |

## Security

- `.env` for secrets (never commit)
- Production startup validation for JWT and encryption keys
- Disable OpenAPI docs and service registry in production
- Rate limiting on authentication and order endpoints
- Fernet encryption for broker credentials at rest
- JWT bearer authentication
- Role-based access control
- Audit logging for auth events

## Tech Stack

**Backend:** Python, FastAPI, SQLAlchemy, PostgreSQL, Redis, Celery, Angel One SmartAPI

**Frontend:** React, React Router, TailwindCSS, TradingView, Recharts

**Infra:** Docker, Docker Compose

## License

Private — for personal/educational trading automation. Trade at your own risk.
