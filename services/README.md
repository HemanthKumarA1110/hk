# Services Overview

| Service | Port | Phase 1 Status |
|---------|------|----------------|
| api-gateway | 8000 | Production routing |
| auth-service | 8001 | JWT, RBAC, Angel One sessions |
| market-data-service | 8002 | Live WebSocket stream, scanner, option chain, candles |
| strategy-engine | 8003 | Scalping, intraday, swing signal engines |
| ai-decision-engine | 8004 | AI scoring, decisions, adaptive learning, journal |
| risk-manager | 8005 | Production risk controls |
| order-execution-engine | 8006 | Risk-gated live order execution |
| backtesting-engine | 8007 | Bar replay backtesting with Celery |
| portfolio-manager | 8008 | Live Angel One portfolio sync |
| alert-engine | 8009 | Telegram + SMTP alerts, health probes |
| analytics-engine | 8010 | Skeleton |
| trade-journal-engine | 8011 | Skeleton |
| admin-dashboard | 8012 | Overview BFF aggregation |
| celery-worker | n/a | Background tasks |

Shared code lives in `services/shared/trading_shared/`.
