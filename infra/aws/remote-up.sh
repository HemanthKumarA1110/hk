#!/bin/bash
# Runs on the EC2 host via SSM. Expects:
#   PACKAGE_S3_URI  e.g. s3://bucket/trading-bot/package.tgz
#   PUBLIC_HOST     Elastic IP or DNS
#   ENV_PARAM       SSM SecureString name for .env contents

set -euo pipefail

ROOT=/opt/trading-bot
mkdir -p "$ROOT"
cd "$ROOT"

echo "Downloading package from ${PACKAGE_S3_URI}"
aws s3 cp "${PACKAGE_S3_URI}" /tmp/trading-bot-package.tgz
rm -rf "${ROOT}/app"
mkdir -p "${ROOT}/app"
tar -xzf /tmp/trading-bot-package.tgz -C "${ROOT}/app"
cd "${ROOT}/app"

if [[ -n "${ENV_PARAM:-}" ]]; then
  aws ssm get-parameter --name "${ENV_PARAM}" --with-decryption --query Parameter.Value --output text > .env
elif [[ -n "${ENV_FILE_B64:-}" ]]; then
  echo "${ENV_FILE_B64}" | base64 -d > .env
fi

if [[ ! -f .env ]]; then
  echo "ERROR: .env missing on host. Upload secrets before deploy."
  exit 1
fi

# Force AWS-facing values
export PUBLIC_HOST="${PUBLIC_HOST}"
grep -q '^PUBLIC_HOST=' .env && sed -i "s/^PUBLIC_HOST=.*/PUBLIC_HOST=${PUBLIC_HOST}/" .env || echo "PUBLIC_HOST=${PUBLIC_HOST}" >> .env
grep -q '^ENV=' .env && sed -i 's/^ENV=.*/ENV=production/' .env || echo "ENV=production" >> .env
grep -q '^CORS_ORIGINS=' .env && sed -i "s|^CORS_ORIGINS=.*|CORS_ORIGINS=http://${PUBLIC_HOST}|" .env || echo "CORS_ORIGINS=http://${PUBLIC_HOST}" >> .env
grep -q '^ANGEL_CLIENT_PUBLIC_IP=' .env && sed -i "s/^ANGEL_CLIENT_PUBLIC_IP=.*/ANGEL_CLIENT_PUBLIC_IP=${PUBLIC_HOST}/" .env || echo "ANGEL_CLIENT_PUBLIC_IP=${PUBLIC_HOST}" >> .env
grep -q '^REDIS_URL=' .env && sed -i 's|^REDIS_URL=.*|REDIS_URL=redis://redis:6379/0|' .env || echo "REDIS_URL=redis://redis:6379/0" >> .env
grep -q '^ALLOW_PUBLIC_REGISTRATION=' .env && sed -i 's/^ALLOW_PUBLIC_REGISTRATION=.*/ALLOW_PUBLIC_REGISTRATION=false/' .env || echo "ALLOW_PUBLIC_REGISTRATION=false" >> .env

# Production rejects default traderpass — generate a strong DB password once per host
DB_PASS_FILE=/opt/trading-bot/db_password
if [[ -f "$DB_PASS_FILE" ]]; then
  DB_PASS="$(cat "$DB_PASS_FILE")"
else
  DB_PASS="$(openssl rand -hex 24)"
  umask 077
  echo -n "$DB_PASS" > "$DB_PASS_FILE"
fi
DB_URL="postgresql://trader:${DB_PASS}@postgres:5432/trading"
grep -q '^POSTGRES_PASSWORD=' .env && sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${DB_PASS}/" .env || echo "POSTGRES_PASSWORD=${DB_PASS}" >> .env
grep -q '^DATABASE_URL=' .env && sed -i "s|^DATABASE_URL=.*|DATABASE_URL=${DB_URL}|" .env || echo "DATABASE_URL=${DB_URL}" >> .env

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.aws.yml)

echo "Starting Compose stack..."
# Keep Postgres/Redis volumes on code deploys so live orders and history survive.
# Set WIPE_VOLUMES=1 only for a first-time password reset.
if [[ "${WIPE_VOLUMES:-0}" == "1" ]]; then
  echo "WIPE_VOLUMES=1 - removing Compose volumes"
  "${COMPOSE[@]}" down -v --remove-orphans || true
else
  "${COMPOSE[@]}" down --remove-orphans || true
fi
"${COMPOSE[@]}" up -d --build --remove-orphans

echo "Waiting for frontend health..."
for i in $(seq 1 90); do
  if curl -sf http://127.0.0.1/health >/dev/null 2>&1; then
    echo "OK - trading bot is up on http://${PUBLIC_HOST}/"
    "${COMPOSE[@]}" ps
    exit 0
  fi
  # Also accept gateway healthy + frontend starting
  if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1 && curl -sf http://127.0.0.1/ >/dev/null 2>&1; then
    echo "OK - api and frontend responding on http://${PUBLIC_HOST}/"
    "${COMPOSE[@]}" ps
    exit 0
  fi
  sleep 5
done

echo "WARN: health check timed out. Recent logs:"
"${COMPOSE[@]}" logs --tail=80 api-gateway frontend auth-service || true
exit 1
