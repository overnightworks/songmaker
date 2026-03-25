# Deployment Plan

> **Status: NOT STARTED** — running locally on bare metal with RTX 3090.

## Goal

Docker-based deployment that works both privately (friends only, no public access) and could go public later if wanted. The default is private.

## Architecture

```
Docker Compose:
  songmaker-app    FastAPI + SvelteKit build (single container)
  songmaker-db     SQLite volume (persistent)
  songmaker-audio  Audio files volume (persistent)
```

GPU generation stays on the local machine (RTX 3090). The Docker deployment is for the web UI + API only. Generation jobs are submitted to the local GPU queue.

## Steps

### Step 1: Dockerfile

- [ ] Multi-stage build: Node (frontend build) → Python (backend)
- [ ] Frontend: `pnpm build` → static files in `/app/frontend/build/`
- [ ] Backend: `pip install .` with server + scoring extras
- [ ] Entrypoint: `songmaker server --port 8080`
- [ ] Health check: `GET /api/capabilities`

### Step 2: Docker Compose

- [ ] `docker-compose.yml` with volumes for DB + audio
- [ ] `.env` file for SESSION_SECRET, port config
- [ ] Optional: reverse proxy (Caddy/Traefik) for HTTPS

### Step 3: Data Persistence

- [ ] SQLite DB in named volume (`songmaker-data:/app/_output/`)
- [ ] Audio files in same volume (MP3s are in `_output/`)
- [ ] Backup strategy: `sqlite3 .backup` via cron or manual

### Step 4: HTTPS (optional, for remote access)

- [ ] Caddy reverse proxy with automatic Let's Encrypt
- [ ] Or: Cloudflare Tunnel (no port forwarding needed)
- [ ] Or: Tailscale for private network access

---

## Public Considerations (if ever needed)

### Legal (Germany)

- **Impressum**: Required for any public-facing site. Real name + address.
- **Datenschutzerklärung (GDPR)**: Required if collecting any user data (logs, cookies, accounts).
- **GEMA**: AI-generated music is a legal grey area. Add disclaimer.
- **Gewerbeanmeldung**: Required if monetizing. Kleinunternehmerregelung below 22k€/year.

### Hosting

| Provider | What | Price |
|---|---|---|
| Hetzner Cloud | VPS for web app | ~4-5€/mo |
| vast.ai / runpod | On-demand GPU for generation | pay-per-use |

### Additional Steps for Public

- [ ] Rate limiting (per-IP, not just per-user)
- [ ] Object storage for audio (Cloudflare R2 / S3)
- [ ] CDN for MP3 streaming
- [ ] Abuse prevention (captcha on generation)
- [ ] SvelteKit SSR for SEO
- [ ] OG meta tags, shareable song URLs
- [ ] Naming: "Songmaker" clashes with Google's Chrome Music Lab
