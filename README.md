# Songmaker

AI-powered song generation platform. Create albums and songs with lyrics + style prompts, generate music via [ACE-Step](https://github.com/ace-step/ACE-Step), auto-master to MP3, and score quality.

SvelteKit frontend + FastAPI backend + PostgreSQL + Redis + GPU worker.

## Quick Setup

Requires: Python 3.12, Node 22, pnpm, ffmpeg, PostgreSQL, Redis.

```bash
# 1. System services
sudo apt install postgresql redis-server ffmpeg
sudo systemctl enable --now postgresql redis-server

# 2. Python + frontend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[server,scoring,whisper,dev]"
cd frontend && pnpm install && pnpm build && cd ..

# 3. Database (one-time — creates PG user + database + migrations)
sudo -u postgres songmaker setup-db

# 4. Start
songmaker server
```

Configure `DATABASE_URL`, `REDIS_URL`, and optional `ADMIN_USERNAME`/`ADMIN_PASSWORD` in `.server.env`. See [.server.env.example](.server.env.example) for all options.

## Docs

- [Architecture](docs/architecture.md) — system design, data model, API endpoints
- [Security](docs/security.md) — auth, CSRF, rate limiting, headers
- [Testing](docs/testing.md) — test structure, fixtures, coverage
- [ACE-Step](docs/acestep.md) — generation server, models, parameters

## License

MIT
