# Deployment Plan

> **Status: DOCKER FILES CREATED** — Dockerfile, Dockerfile.worker, docker-compose.yml ready. Needs Docker + NVIDIA toolkit install to test.

## Goal

Docker-based deployment on the same PC, exposed via Cloudflare Tunnel with a custom domain. Friends-only, private access. GPU stays local.

## Architecture

```
Internet → Cloudflare Tunnel → localhost:8080
                                    ↓
Docker Compose:
  songmaker-web      FastAPI + SvelteKit build (no GPU, no scoring)
  songmaker-worker   arq worker + ACE-Step subprocess (GPU access)
  postgres           PostgreSQL 16 (persistent volume)
  redis              Redis 7 (session cache, rate limiting, job queue)
```

The worker manages ACE-Step as a subprocess (existing architecture). ACE-Step models are
bind-mounted from `_models/acestep/` on the host. Scoring uses CPU torch inside the worker
container (slower but works without CUDA in the base image — ACE-Step's own CUDA torch runs
via `uv run` in the mounted directory with GPU passthrough).

## Prerequisites

```bash
# Docker
sudo apt install docker.io docker-compose-v2
sudo usermod -aG docker $USER
# Re-login for group change to take effect

# NVIDIA Container Toolkit (for GPU passthrough)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt install nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Verify GPU is visible in Docker
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi

# Cloudflare Tunnel
# Install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
# Or: sudo apt install cloudflared (if available)
```

## Steps

### Step 1: Dockerfile (songmaker-web)

- [ ] Multi-stage build: Node (frontend build) → Python (backend)
- [ ] Stage 1: `node:22-slim` — `pnpm install && pnpm build`
- [ ] Stage 2: `python:3.12-slim` — `uv sync --extra server --extra scoring --extra whisper`
- [ ] Copy frontend build from stage 1
- [ ] Entrypoint script runs both processes:
  - `uv run songmaker server` (foreground)
  - `uv run arq songmaker_cli.worker.WorkerSettings` (background, same container)
  - Or use `supervisord` if process management gets complex
- [ ] Health check: `GET /health/ready`
- [ ] Non-root user inside container

### Step 2: Docker Compose

- [ ] `docker-compose.yml` with services: songmaker-web, postgres, redis, acestep
- [ ] Named volumes: `pg-data`, `audio-files`
- [ ] `.env` file for configuration (gitignored):
  ```
  DATABASE_URL=postgresql://songmaker:songmaker@postgres:5432/songmaker
  REDIS_URL=redis://redis:6379/0
  SESSION_SECRET=<generated-64-char-hex>
  ADMIN_USERNAME=felix
  ADMIN_PASSWORD=<strong-password>
  ALLOWED_HOSTS=yourdomain.com
  CORS_ORIGIN=https://yourdomain.com
  TRUSTED_PROXIES=172.16.0.0/12
  HOST=0.0.0.0
  ```
- [ ] `REDIS_URL` passed as environment variable (not just in .server.env) — WorkerSettings resolves at import time
- [ ] PostgreSQL health check: `pg_isready -U songmaker`
- [ ] Redis health check: `redis-cli ping`
- [ ] `depends_on` with `condition: service_healthy` for startup ordering
- [ ] Internal network only — no ports exposed to host except 8080 for Cloudflare

### Step 3: ACE-Step Container (trust boundary isolation)

- [ ] Separate container with GPU passthrough:
  ```yaml
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
  ```
- [ ] Only the `audio-files` volume mounted (read-write)
- [ ] No access to `pg-data`, Redis, session secrets, or host filesystem
- [ ] Internal network only — communicates with songmaker-web via HTTP (port 8001)
- [ ] If ACE-Step is compromised, blast radius = audio files only (no DB, no credentials, no host access)
- [ ] No `--privileged` flag, no host network mode

### Step 4: Cloudflare Tunnel (custom domain)

- [ ] Create tunnel: `cloudflared tunnel create songmaker`
- [ ] Configure DNS: add CNAME `yourdomain.com` → `<tunnel-id>.cfargotunnel.com` in Cloudflare dashboard
- [ ] Create config file `~/.cloudflared/config.yml`:
  ```yaml
  tunnel: <tunnel-id>
  credentials-file: ~/.cloudflared/<tunnel-id>.json
  ingress:
    - hostname: yourdomain.com
      service: http://localhost:8080
    - service: http_status:404
  ```
- [ ] Run as systemd service: `cloudflared service install`
- [ ] Cloudflare provides: TLS termination, DDoS protection, hides home IP
- [ ] Optional: enable Cloudflare Access for extra auth layer (email-based allowlist)

### Step 5: Data Persistence & Backup

- [ ] PostgreSQL data in named volume (`pg-data`)
- [ ] Audio files in named volume (`audio-files`), shared between songmaker-web and acestep
- [ ] Backup script (cron daily):
  ```bash
  docker compose exec postgres pg_dump -U songmaker songmaker > backup.sql
  rsync -a /var/lib/docker/volumes/songmaker_audio-files/_data/ ~/backups/audio/
  ```
- [ ] Both must be backed up together — orphaned records or unreachable files if one is missing

### Step 6: Observability

- [ ] `/metrics` endpoint (already implemented) — Prometheus text format
- [ ] Optional: Prometheus + Grafana in docker-compose (adds ~200MB RAM)
- [ ] Minimum viable monitoring: check `/health` endpoint from cron, alert on failure
- [ ] Logs: `docker compose logs -f songmaker-web` (structlog JSON to stdout)

### Step 7: Security Hardening

- [ ] No `--privileged` on any container
- [ ] No `network_mode: host` — use Docker internal networking
- [ ] ACE-Step container: `read_only: true` filesystem except audio volume
- [ ] Drop all Linux capabilities except what's needed: `cap_drop: [ALL]`
- [ ] Strong passwords enforced (app already checks on creation)
- [ ] Enable MFA on Cloudflare account
- [ ] Pin Docker image versions (no `latest` tags)
- [ ] Run `docker scout cves` or `trivy` on built images before deploying
- [ ] Keep host OS, Docker, and NVIDIA drivers updated

### Step 8: Startup & Updates

- [ ] Start: `docker compose up -d`
- [ ] Update: `git pull && docker compose up -d --build`
- [ ] In-flight jobs: worker receives SIGTERM → `on_shutdown` marks running jobs as failed → new worker picks them up via `recover_stale_jobs` on startup
- [ ] Downtime: a few seconds during rebuild (acceptable for private use)

---

## Estimated Effort

| Step | Time | Notes |
|------|------|-------|
| Prerequisites | 30 min | Docker + NVIDIA toolkit install |
| Dockerfile | 2 hours | Multi-stage build, test locally |
| Docker Compose | 1 hour | Services, volumes, health checks |
| ACE-Step container | 2 hours | GPU passthrough, isolation testing |
| Cloudflare Tunnel | 30 min | Tunnel + DNS setup |
| Backup script | 30 min | pg_dump + rsync cron |
| Security hardening | 1 hour | Cap drops, read-only, image scanning |
| **Total** | **~8 hours** | |

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

- [ ] Cloudflare Access (zero-trust auth layer — email allowlist before app auth)
- [ ] Object storage for audio (Cloudflare R2 / S3)
- [ ] CDN for MP3 streaming
- [ ] Abuse prevention (captcha on generation)
- [ ] SvelteKit SSR for SEO
- [ ] OG meta tags, shareable song URLs
