# Songmaker

AI-powered song generation platform. Create albums and songs with lyrics + style prompts, generate music via [ACE-Step](https://github.com/ace-step/ACE-Step), auto-master to MP3, and score quality.

SvelteKit frontend + FastAPI backend + PostgreSQL + Redis + GPU worker.

## Run with Docker

Requires: Docker, NVIDIA Container Toolkit (for GPU generation).

```bash
# 1. First-time setup
cp .env.docker.example .env     # edit with your passwords + session secret
docker compose up -d            # starts web, worker, PostgreSQL, Redis

# 2. That's it — survives reboots automatically

# 3. Remote access (optional)
cloudflared tunnel --url http://localhost:8080

# 4. Update after code changes
git pull && docker compose up -d --build

# 5. View logs
docker compose logs -f songmaker-worker   # GPU worker + ACE-Step
docker compose logs -f songmaker-web      # API + frontend
```

First start downloads ~3.5GB of ACE-Step dependencies (one-time). All data (database, audio files, models) persists across restarts and rebuilds.

## Development Setup

For editing code, running tests, and fast iteration.

Requires: Python 3.12, Node 22, pnpm, ffmpeg, PostgreSQL, Redis.

```bash
# 1. System services
sudo apt install postgresql redis-server ffmpeg
sudo systemctl enable --now postgresql redis-server

# 2. PostgreSQL database (one-time)
sudo -u postgres psql -c "CREATE USER songmaker WITH PASSWORD 'songmaker';"
sudo -u postgres psql -c "CREATE DATABASE songmaker OWNER songmaker;"

# 3. Backend
uv sync --extra server --extra scoring --extra whisper --extra dev

# 4. Frontend (optional — only needed for UI changes)
cd frontend && pnpm install && pnpm build && cd ..

# 5. Start
uv run songmaker server                         # terminal 1 — web server
uv run arq songmaker_cli.worker.WorkerSettings   # terminal 2 — GPU worker
```

Configure `DATABASE_URL`, `REDIS_URL`, and optional `ADMIN_USERNAME`/`ADMIN_PASSWORD` in `.server.env`.

## Docs

- [Architecture](docs/architecture.md) — system design, data model, API endpoints
- [Security](docs/security.md) — auth, CSRF, rate limiting, headers
- [Testing](docs/testing.md) — test structure, fixtures, coverage
- [ACE-Step](docs/acestep.md) — generation server, models, parameters

## License

MIT
