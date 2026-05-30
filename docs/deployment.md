# Deployment Guide

## Prerequisites

- Docker >= 24.0 + Docker Compose v2
- 4 GB RAM minimum (Milvus alone needs ~2 GB)
- Ports: 80 (frontend), 8000 (backend), 19530 (Milvus), 5432 (PostgreSQL)
- API keys: DeepSeek (or OpenAI/Qwen), 火山引擎 Embedding

## 1. Environment Configuration

```bash
cp configs/.env.example configs/.env.prod
```

Edit `configs/.env.prod`:

| Variable | Required | Description |
|----------|----------|-------------|
| `ENV` | Yes | Set to `prod` |
| `JWT_SECRET` | Yes | 64-char hex (`python -c "import secrets; print(secrets.token_hex(32))"`) |
| `DEEPSEEK_API_KEY` | Yes | DeepSeek API key |
| `VOLCENGINE_API_KEY` | Yes | 火山引擎 Embedding API key |
| `LLM_PROVIDER` | No | `deepseek` / `openai` / `qwen` (default: `deepseek`) |
| `LLM_MODEL` | No | Model name (default: provider-specific) |

Production automatically disables: `DEBUG`, `LLM_CACHE`, retrieval dumps.

## 2. Start Services

```bash
cd docker
docker compose up -d
```

This starts 6 services: etcd, MinIO, Milvus, PostgreSQL, backend, frontend.

### Verify Health

```bash
# All services should show "healthy"
docker compose ps

# Backend health endpoint
curl http://localhost:8000/api/health

# Frontend
curl http://localhost:80/nginx-health
```

## 3. Database Migrations

Migrations run automatically on container startup via `entrypoint.sh`.

To run manually:

```bash
docker compose exec backend psql $POSTGRES_URL -f migrations/001_add_research_current_step.sql
docker compose exec backend psql $POSTGRES_URL -f migrations/002_add_research_memory_quality.sql
```

## 4. Seed Data (Optional)

```bash
# Import 10K articles from HuggingFace AG News
docker compose exec backend python scripts/seed_data.py
```

## 5. HTTPS / Reverse Proxy

For production with a domain, place an external Nginx or Caddy in front:

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    location / {
        proxy_pass http://localhost:80;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }

    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;

        # SSE support
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

Or use Caddy for automatic HTTPS:

```Caddyfile
your-domain.com {
    reverse_proxy /api/* localhost:8000
    reverse_proxy localhost:80
}
```

## 6. Backup

### PostgreSQL

```bash
# Dump
docker compose exec postgres pg_dump -U rag_user rag_news > backup_$(date +%Y%m%d).sql

# Restore
cat backup.sql | docker compose exec -T postgres psql -U rag_user rag_news
```

### Milvus

Milvus data is persisted in the `milvus_data` Docker volume. Back up the volume:

```bash
docker run --rm -v rag_milvus_data:/data -v $(pwd):/backup alpine \
  tar czf /backup/milvus_backup_$(date +%Y%m%d).tar.gz /data
```

## 7. Logs

```bash
# All services
docker compose logs -f

# Backend only
docker compose logs -f backend

# Last 100 lines
docker compose logs --tail 100 backend
```

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Backend unhealthy | Milvus not ready | Wait 90s for Milvus start_period |
| 401 on API calls | Missing/expired JWT | Re-login or check `JWT_SECRET` |
| Empty search results | No data seeded | Run `seed_data.py` |
| OOM killed | Insufficient RAM | Increase to 4GB+ or reduce Milvus cache |
| Migration errors | Duplicate run | Migrations use `IF NOT EXISTS`, safe to re-run |

## 9. Updating

```bash
cd docker
git pull
docker compose build
docker compose up -d
```

Migrations apply automatically on restart.
