# AWS deployment (EC2 + Docker Compose)

Lift-and-shift of the existing Compose stack onto a single EC2 host in **eu-north-1** (your AWS CLI default) with a static **Elastic IP** for Angel One SmartAPI IP allowlisting.

For lower Angel One latency you can redeploy with `-Region ap-south-1` (Mumbai).

## Why EC2 Compose (not ECS/Lambda)

- The bot is already a multi-service Docker Compose app (Postgres, Redis, websockets, Celery, scalping stream).
- Angel One requires a **stable egress IP**.
- Mumbai region keeps broker API latency lower than `eu-north-1` if you pass `-Region ap-south-1`.

## Prerequisites

1. AWS CLI logged in (`aws sts get-caller-identity`)
2. Repo `.env` with production secrets:
   - `JWT_SECRET` / `ENCRYPTION_KEY` (32+ chars)
   - Angel One `ANGEL_*` values
3. PowerShell on Windows (or adapt the script)

## Deploy

From the repo root:

```powershell
.\scripts\aws-deploy.ps1
```

Optional:

```powershell
.\scripts\aws-deploy.ps1 -InstanceType t3.2xlarge -StackName trading-bot-prod
```

What it does:

1. Creates a private S3 deploy bucket
2. Uploads source tarball (without `.env`) + remote install script
3. Stores `.env` in SSM Parameter Store as a SecureString
4. Creates/updates CloudFormation (`infra/aws/cloudformation.yml`) — EC2, EIP, SG, SSM IAM
5. Runs `docker compose` on the instance via SSM
6. Prints the public URL and Elastic IP

Compose files on the host:

```text
docker-compose.yml + docker-compose.prod.yml + docker-compose.aws.yml
```

## After deploy

1. Open `http://<ElasticIP>/`
2. In Angel One SmartAPI, register the printed Elastic IP
3. Prefer SSM over SSH:

```powershell
aws ssm start-session --target <InstanceId> --region eu-north-1
```

## Costs (approx.)

| Resource | Notes |
|----------|--------|
| EC2 `m7i-flex.large` | ~8 GB RAM — Free Tier eligible default; use `t3.xlarge` when paid EC2 is enabled |
| 80 GB gp3 EBS | App + Docker images + DB volume |
| Elastic IP | Free while associated |
| S3 deploy bucket | Small |

Stop or delete the stack when unused:

```powershell
aws cloudformation delete-stack --stack-name trading-bot --region eu-north-1
```

## Security notes

- Only ports 80/443 are open publicly; Postgres/Redis stay on the Docker network.
- Prefer changing default DB password before long-term production use.
- Add HTTPS (Caddy/ALB + ACM) when you attach a domain.
