# ResilientPay: Fault-Tolerant Fund Transfer Service

Containerized banking transfer API (FastAPI + PostgreSQL + Nginx) with SLAs, chaos testing and TTR measurement on AWS.

## Run locally
```bash
docker compose up -d --build
open http://localhost            # dashboard
bash scripts/smoke_test.sh       # API test
```

## Endpoints
`POST /accounts` · `GET /accounts` · `GET /balance/{id}` · `POST /transfer` · `GET /health`

## SLA targets
Availability 99.9% · p95 latency < 300 ms · error rate < 1% · **TTR < 60 s** · 0 lost/duplicate transfers

## Chaos test (TTR)
```bash
python3 scripts/measure_ttr.py --container resilientpay-api --runs 3
python3 scripts/measure_ttr.py --container resilientpay-db --action stop --runs 3
# baseline: remove `restart: always` for api in docker-compose.yml, re-run with --label baseline
# push to CloudWatch (on EC2 with IAM role): add --cloudwatch
```

## Deploy on EC2 (Ubuntu 22.04, t3.micro, SG ports 22 + 80)
```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker
git clone <your-repo-url> && cd resilientpay
docker compose up -d --build
```
Live link: `http://<EC2-public-IP>`
