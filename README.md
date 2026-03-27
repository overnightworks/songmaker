# Songmaker

AI-powered song generation platform. Create albums and songs with lyrics + style prompts, generate music via [ACE-Step](https://github.com/ace-step/ACE-Step), auto-master to MP3, and score quality.

SvelteKit frontend + FastAPI backend + PostgreSQL + Redis + GPU worker.

## Quick Setup

Requires: Python 3.12, Node 22, pnpm, ffmpeg, PostgreSQL, Redis.

```bash
# 1. System services
sudo apt install postgresql redis-server ffmpeg
sudo systemctl enable --now postgresql redis-server

# 2. PostgreSQL database (one-time)
sudo -u postgres psql -c "CREATE USER songmaker WITH PASSWORD 'songmaker';"
sudo -u postgres psql -c "CREATE DATABASE songmaker OWNER songmaker;"

# 3. Backend
uv sync --extra server --extra scoring --extra whisper --extra dev && source .venv/bin/activate

# 4. Frontend (optional — only needed for UI changes)
cd frontend && pnpm install && pnpm build && cd ..

# 5. Start (runs migrations automatically on first launch)
songmaker server                              # terminal 1 — web server
arq songmaker_cli.worker.WorkerSettings       # terminal 2 — GPU worker
```

Configure `DATABASE_URL`, `REDIS_URL`, and optional `ADMIN_USERNAME`/`ADMIN_PASSWORD` in `.server.env`. See [.server.env.example](.server.env.example) for all options.

## Docs

- [Architecture](docs/architecture.md) — system design, data model, API endpoints
- [Security](docs/security.md) — auth, CSRF, rate limiting, headers
- [Testing](docs/testing.md) — test structure, fixtures, coverage
- [ACE-Step](docs/acestep.md) — generation server, models, parameters

## License

MIT
