# Infra / Dev setup

Prereqs: Docker, Docker Compose

To start development stack:

```bash
cd infra
docker-compose up --build
```

Services:
- `backend` — FastAPI app
- `db` — PostgreSQL
- `redis` — Redis for caching and Celery broker
- `worker` — Celery worker
- `frontend` — React dev server

Production proxy build:
- `frontend` now includes `Dockerfile.proxy` and `nginx.conf` to build a production static site served by Nginx with `/api` reverse proxy support.

Kubernetes/Helm:
- Apply raw manifests in `infra/k8s/` with `kubectl apply -f infra/k8s/`.
- Install the Helm chart from `infra/helm/trading-stack` with `helm install trading-stack ./infra/helm/trading-stack`.
