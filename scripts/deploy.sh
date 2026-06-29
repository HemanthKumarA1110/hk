#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example and configure secrets first."
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ "${ENV:-}" != "production" ]]; then
  echo "WARN: ENV is not 'production'. Set ENV=production in .env for hardened deployment."
fi

require_secret() {
  local name="$1"
  local value="$2"
  local min_len="${3:-32}"
  if [[ -z "${value}" || "${#value}" -lt "${min_len}" ]]; then
    echo "ERROR: ${name} must be set to at least ${min_len} characters for production."
    exit 1
  fi
}

require_secret "JWT_SECRET" "${JWT_SECRET:-}" 32
require_secret "ENCRYPTION_KEY" "${ENCRYPTION_KEY:-}" 32

echo "Building and starting production stack..."
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build --remove-orphans

echo "Waiting for gateway health..."
for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1/health >/dev/null 2>&1 || curl -sf http://127.0.0.1:80/health >/dev/null 2>&1; then
    echo "Deployment healthy — frontend available on port 80."
    exit 0
  fi
  sleep 2
done

echo "Stack started but health check did not pass within 60s. Inspect logs:"
echo "  docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api-gateway frontend"
exit 1
