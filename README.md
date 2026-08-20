# Songmaker

AI-powered song generation platform. Create albums and songs with lyrics + style prompts, generate music via [ACE-Step](https://github.com/ace-step/ACE-Step), auto-master to MP3, and score quality.

SvelteKit frontend + FastAPI backend + PostgreSQL + Redis + arq job workers + GPU ACE-Step worker.

## Run with Docker

Songmaker is Docker-only — there is no native local-dev path. The Docker stack runs the web app, both arq workers, the ACE-Step GPU worker, PostgreSQL, Redis, Prometheus, and Grafana.

Requires: Docker (with Compose v2), NVIDIA Container Toolkit (for GPU generation), and a Hugging Face token (for downloading ACE-Step model weights).

```bash
# 1. First-time setup
cp .env.docker.example .env     # edit with your secrets — see file for required fields
docker compose up -d --build --wait
# Cold-cache rebuild takes 8-15 min the first time. Never wrap in `timeout`
# (see CLAUDE.md "Docker" section for the full reasoning).

# 2. That's it — survives reboots automatically.
```

The first start downloads ~3.5 GB of ACE-Step model weights into the `songmaker_hfcache` Docker volume (one-time). All persistent state (PostgreSQL DB, audio files, model cache, Grafana dashboards) lives in named Docker volumes and survives `docker compose down` and `--build` rebuilds.

### Day-to-day operations

```bash
# Update after pulling new code
git pull && docker compose up -d --build --wait

# View logs (one service at a time)
docker compose logs -f songmaker-web                # API + frontend
docker compose logs -f songmaker-music-worker       # generation jobs (arq)
docker compose logs -f songmaker-scoring-worker     # scoring jobs (arq)
docker compose logs -f songmaker-acestep-worker-0   # GPU subprocess (ACE-Step)

# Container status
docker compose ps                                   # all services + health

# Stop / start the stack (preserves volumes)
docker compose stop
docker compose start

# Cloudflare tunnel (if you've set one up for remote access)
sudo systemctl start cloudflared
sudo systemctl stop cloudflared
sudo systemctl status cloudflared
```

### Required env vars (in `.env`)

These are the four secrets that must be set or `Settings` will raise `ValidationError` at startup:

| Var | Purpose |
|---|---|
| `SESSION_SECRET` | HMAC signing key for session cookies (min 32 chars) |
| `POSTGRES_PASSWORD` | PostgreSQL password (substituted into the postgres container env) |
| `SONGMAKER_INTERNAL_TOKEN` | Shared secret for worker → web internal API auth |
| `HF_TOKEN` | Hugging Face token for downloading ACE-Step + scoring model weights |

Generate secrets with `python3 -c "import secrets; print(secrets.token_hex(32))"`. See [`.env.docker.example`](.env.docker.example) for the full list including all optional overrides.

## Local toolchain (tests, lint, IDE)

The local Python `.venv` exists for **tests, type checking, and IDE autocomplete only** — not for running the live app. The live app always runs in Docker.

```bash
# One-time setup
uv sync --extra server --extra scoring --extra whisper --extra mcp --extra dev

# Run the test suite
pytest tests/ -n auto -q

# Run the linter
ruff check src/ tests/

# Frontend tests / lint / type-check
cd frontend && pnpm install && pnpm test:coverage && pnpm lint && pnpm check && pnpm build
```

Tests run against an in-memory SQLite database (no Postgres needed for unit tests) and `fakeredis`. The live Docker stack and the test suite are fully independent — you can run tests while the Docker stack is up.

## Backup

Both PostgreSQL and the audio files Docker volume must be backed up together. See [`scripts/BACKUP.md`](scripts/BACKUP.md) for the setup, cron, and restore instructions. The default `BACKUP_DIR` is `/mnt/backup/songmaker` but can be overridden via env var.

```bash
BACKUP_DIR=/path/to/backup ./scripts/backup.sh
```

## Docs

- [CLAUDE.md](CLAUDE.md) — project conventions, code patterns, and "Known Technical Debt." Read this first if you're contributing.
- [docs/VISION.md](docs/VISION.md) — non-normative product overview and pointer to approved intent
- [docs/requirements/](docs/requirements/) — normative requirement grammar and revision registry
- [docs/PRODUCT.md](docs/PRODUCT.md) — generated requirement/acceptance count view; no implementation claim yet
- [docs/architecture.md](docs/architecture.md) — system design, data model, API endpoints, worker pool, monitoring, backup
- [docs/security.md](docs/security.md) — auth, sessions, CSRF, rate limiting, security headers, trust boundaries
- [docs/testing.md](docs/testing.md) — test structure, fixtures, coverage targets
- [docs/acestep.md](docs/acestep.md) — ACE-Step integration, model variants, worker pool, generation parameters
- [plans/](plans/) — design plans for in-flight and proposed work. Each has a `**Status:**` header.

## License

MIT
