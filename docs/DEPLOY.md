# Production Deployment Runbook

Single-VPS deployment using Docker Compose. Internal microservices stay on the Docker network; only the frontend/nginx port is exposed publicly.

## Prerequisites

- Linux VPS (2+ vCPU, 4 GB RAM recommended)
- Docker Engine 24+ and Docker Compose v2
- Domain pointing to the VPS (optional, for HTTPS termination)
- Strong secrets in `.env` (see below)

## 1. Configure environment

```bash
cp .env.example .env
```

Required production values:

| Variable | Notes |
|----------|-------|
| `ENV` | Must be `production` |
| `JWT_SECRET` | 32+ random characters |
| `ENCRYPTION_KEY` | Fernet-compatible key, 32+ chars |
| `DATABASE_URL` | Use internal hostname `postgres` in Compose |
| `ALLOW_PUBLIC_REGISTRATION` | `false` |
| `EXPOSE_SERVICE_REGISTRY` | `false` |
| `ENABLE_OPENAPI_DOCS` | `false` |
| `CORS_ORIGINS` | Your public site origin(s), comma-separated |
| `VITE_API_BASE` | Leave empty for same-origin nginx proxy |
| Angel One vars | Required for live trading |
| `TELEGRAM_*` / `SMTP_*` | Optional alert channels |

Example production database URL inside Compose:

```env
DATABASE_URL=postgresql://trader:CHANGE_ME@postgres:5432/trading
```

Change the Postgres password in both `.env` and `docker-compose.yml` / `POSTGRES_PASSWORD` before going live.

## 2. Deploy

```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

Or manually:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

## 3. Verify

| Check | Command / URL |
|-------|----------------|
| Frontend | `http://YOUR_HOST/` |
| Nginx health | `http://YOUR_HOST/health` |
| Gateway (internal) | `docker compose exec api-gateway curl -s localhost:8000/health` |
| Readiness | `docker compose exec auth-service curl -s localhost:8001/health/ready` |
| Alerts test | `POST /api/v1/alerts/test` (admin JWT) |

## 4. HTTPS (recommended)

Terminate TLS at a reverse proxy (Caddy, Traefik, or nginx) in front of port 80, or bind the frontend to localhost and proxy from the host:

```text
Internet → Caddy :443 → trading-frontend :80
```

Update `CORS_ORIGINS` to include `https://your-domain`.

## 5. Operations

```bash
# Logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api-gateway order-execution-engine

# Restart one service
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart risk-manager

# Stop stack
docker compose -f docker-compose.yml -f docker-compose.prod.yml down

# Backup Postgres
docker compose exec postgres pg_dump -U trader trading > backup.sql
```

## 6. Security checklist

- [ ] Change default admin password after first login
- [ ] Disable public registration (`ALLOW_PUBLIC_REGISTRATION=false`)
- [ ] Hide OpenAPI docs and service registry
- [ ] Do not expose Postgres, Redis, or service ports publicly
- [ ] Configure Telegram or SMTP alerts for risk halts
- [ ] Restrict VPS firewall to 22, 80, 443

## 7. Local development vs production

| | Development | Production |
|---|-------------|------------|
| Compose files | `docker-compose.yml` only | `docker-compose.yml` + `docker-compose.prod.yml` |
| Frontend URL | http://localhost:3000 | http://YOUR_HOST (port 80) |
| API | http://localhost:8000 | Same origin via nginx `/api` proxy |
| OpenAPI | Enabled at `/docs` | Disabled |
| Registration | Allowed | Blocked (viewer role only) |
