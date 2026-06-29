# trading-stack Helm Chart

This Helm chart deploys:
- FastAPI backend deployment + service
- Nginx frontend reverse proxy deployment + service
- Redis deployment + service
- PostgreSQL StatefulSet + service

Install:
```bash
helm install trading-stack ./infra/helm/trading-stack
```

Upgrade:
```bash
helm upgrade trading-stack ./infra/helm/trading-stack
```
