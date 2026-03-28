# Deployment Plan

> **Status: NOT STARTED** — running locally on bare metal with RTX 3090.

## Goal

Docker-based deployment that works both privately (friends only, no public access) and could go public later if wanted. The default is private.

## Architecture

```
Docker Compose:
  songmaker-web    FastAPI + SvelteKit build + arq worker (single container)
  postgres         PostgreSQL 16 (persistent volume)
  redis            Redis 7 (session cache, rate limiting, job queue)
  acestep          ACE-Step inference server (GPU, isolated container)
```

GPU generation runs in the `acestep` container with only the audio volume mounted. The `songmaker-web` container handles API, frontend, and background worker. PostgreSQL is the primary datastore; Redis is required for sessions, rate limiting, and the arq job queue.

## Steps

### Step 1: Dockerfile

- [ ] Multi-stage build: Node (frontend build) → Python (backend)
- [ ] Frontend: `pnpm build` → static files in `/app/frontend/build/`
- [ ] Backend: `uv sync --extra server --extra scoring --extra whisper`
- [ ] Entrypoint: runs both `songmaker server` and `arq songmaker_cli.worker.WorkerSettings` (supervisord or process manager)
- [ ] Health check: `GET /health/ready`

### Step 2: Docker Compose

- [ ] `docker-compose.yml` with services: songmaker-web, postgres, redis, acestep
- [ ] Named volumes: `pg-data`, `audio-files`
- [ ] `.env` file for `DATABASE_URL`, `REDIS_URL`, `SESSION_SECRET`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`
- [ ] `REDIS_URL` must be in the process environment (not just `.server.env`) — `WorkerSettings.redis_settings` resolves at import time
- [ ] PostgreSQL health check: `pg_isready`
- [ ] Redis health check: `redis-cli ping`
- [ ] `depends_on` with `condition: service_healthy` for startup ordering

### Step 3: ACE-Step Container (trust boundary isolation)

- [ ] Separate container for ACE-Step with GPU passthrough (`deploy.resources.reservations.devices`)
- [ ] Only the audio output volume mounted (read-write)
- [ ] No access to database, Redis, or session secrets
- [ ] Communicates with songmaker-web via HTTP (port 8001, internal network only)
- [ ] If ACE-Step is compromised, blast radius is limited to audio files

### Step 4: Data Persistence

- [ ] PostgreSQL data in named volume (`pg-data`)
- [ ] Audio files in named volume (`audio-files`), shared between songmaker-web and acestep
- [ ] Backup strategy: `pg_dump` via cron + audio directory rsync (both must be backed up together — orphaned records or files if one is missing)

### Step 5: Observability

- [ ] `/metrics` endpoint (already implemented) — Prometheus text format
- [ ] Prometheus scrape config targeting songmaker-web:8080/metrics
- [ ] Grafana dashboard with panels: HTTP request rate, error rate, job queue depth, job duration, GPU VRAM, active sessions
- [ ] Alerts: queue depth > 5, error rate > 10%, Redis down, worker not healthy
- [ ] Log aggregation: structlog JSON output → stdout → Docker log driver → Loki or file

### Step 6: HTTPS and Access

- [ ] Caddy reverse proxy with automatic Let's Encrypt
- [ ] Or: Cloudflare Tunnel (no port forwarding, no certs to manage)
- [ ] Or: Tailscale for private network access (simplest for friends-only)
- [ ] `ALLOWED_HOSTS` and `CORS_ORIGIN` configured for the chosen domain
- [ ] `TRUSTED_PROXIES` set for the reverse proxy IP

### Step 7: Graceful Deployment

- [ ] `docker compose up -d --build` rebuilds and restarts
- [ ] In-flight arq jobs: worker receives SIGTERM → `on_shutdown` marks running jobs as failed → new worker picks them up via `recover_stale_jobs` on startup
- [ ] No zero-downtime requirement for private use — a few seconds of downtime is acceptable
- [ ] For future: blue-green with health check gate before switching traffic

---

## Public Considerations (if ever needed)

### Legal (Germany)

- **Impressum**: Required for any public-facing site. Real name + address.
- **Datenschutzerklärung (GDPR)**: Required if collecting any user data (logs, cookies, accounts).
- **GEMA**: AI-generated music is a legal grey area. Add disclaimer.
- **Gewerbeanmeldung**: Required if monetizing. Kleinunternehmerregelung below 22k EUR/year.

### Hosting

| Provider | What | Price |
|---|---|---|
| Hetzner Cloud | VPS for web app | ~4-5 EUR/mo |
| vast.ai / runpod | On-demand GPU for generation | pay-per-use |

### Additional Steps for Public

- [ ] Object storage for audio (Cloudflare R2 / S3)
- [ ] CDN for MP3 streaming
- [ ] Abuse prevention (captcha on generation)
- [ ] SvelteKit SSR for SEO
- [ ] OG meta tags, shareable song URLs
- [ ] Naming: "Songmaker" clashes with Google's Chrome Music Lab
