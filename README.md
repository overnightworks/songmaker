# Songmaker

AI-powered song generation platform. Create albums and songs with lyrics + style prompts, generate music via [ACE-Step](https://github.com/ace-step/ACE-Step), auto-master to MP3, and score quality.

SvelteKit frontend + FastAPI backend + PostgreSQL + Redis + arq job workers + GPU ACE-Step worker.

## Run with Docker

Songmaker is Docker-only; there is no native local-dev path. The stack runs the web app, both arq workers, the ACE-Step GPU worker, PostgreSQL, Redis, Prometheus, and Grafana.

Requires: Docker (with Compose v2), NVIDIA Container Toolkit (for GPU generation), and a Hugging Face token (for downloading model weights).

A process started from a checkout reads the first `.env` it finds walking up from its working directory and stops at the first `pyproject.toml`.

Install and first start, in the deploy checkout `~/srv/songmaker` (a clone at a release tag; a work clone has no `.env` and cannot start the live stack):

```bash
cp docker/.env.docker.example .env                # fill in the required settings; the secrets are files, see docs/security.md ("Secrets")
docker compose up -d --build --wait               # never wrap in `timeout`
sudo ./scripts/install_cli_credentials_mirror.sh  # agent-CLI login mirror
sudo ./scripts/install_autostart.sh               # start the stack after every boot
```

- [`docker/.env.docker.example`](docker/.env.docker.example) lists every setting, which ones are required, and how to generate secrets.
- A cold-cache build takes 8-15 minutes; [AGENTS.md](AGENTS.md#rules) says why it must not be interrupted. The first start also downloads the ACE-Step model weights into a Docker volume.
- All persistent state (database, audio files, model cache, Grafana dashboards) lives in named Docker volumes and survives `docker compose down` and rebuilds.
- Container confinement: [docs/security.md](docs/security.md#container-confinement). Why Docker's restart policy alone does not survive every reboot, and what the autostart unit adds: [docs/acestep.md](docs/acestep.md#restart-policy-limits-and-boot-autostart).

## Operations

- **Updates:** a systemd timer (`scripts/install_autodeploy.sh` installs it) runs `scripts/run_autodeploy.sh`, which redeploys a release tag (`vYYYY.MM.DD.N` on `main`) once its checks are green and no job is running (the operator dispatches the Release workflow, which gates `main`, pushes the images to GHCR and sets the tag); a merge to `main` alone deploys nothing, and the header owns the rules.
- **Logs and status:** `docker compose logs -f <service>` (the containers log through journald, so `journalctl -t <container>` reads the same lines) and `docker compose ps -a` (`-a` also shows a created-but-never-started container).
- **Stop and start:** `docker compose stop` / `docker compose start` keep the volumes.
- **Backup:** PostgreSQL and the audio volume are backed up together by `hal backup`, hal's scheduled backup (hal's `docs/backup.md`); `scripts/create_backup.sh` makes a manual copy ([`scripts/BACKUP.md`](scripts/BACKUP.md)).

## Development

The commands for local tests and the static checks are in [AGENTS.md](AGENTS.md#commands); the lint and type checks CI runs, test structure and coverage gates are in [docs/testing.md](docs/testing.md). The live app never runs from the local `.venv`.

## Docs

- [AGENTS.md](AGENTS.md): commands, rules and owners. Read this first if you are contributing.
- [docs/VISION.md](docs/VISION.md): what Songmaker does, who uses it today, and what it deliberately is not
- Ruled product sentences, one page per surface: [catalog](docs/catalog.md), [library](docs/library.md), [generation](docs/generation.md), [co-writer](docs/co-writer.md), [sharing](docs/sharing.md)
- [docs/architecture.md](docs/architecture.md): system design, data model, API endpoints, worker pool, monitoring
- [docs/security.md](docs/security.md): auth, sessions, CSRF, rate limiting, security headers, trust boundaries
- [docs/testing.md](docs/testing.md): test structure, fixtures, coverage targets
- [docs/acestep.md](docs/acestep.md): ACE-Step integration, model variants, worker pool, generation parameters
- [docs/navigation.md](docs/navigation.md): the rules of navigation, each under the ID its test cites
- [docs/mockups/](docs/mockups): pictures of surfaces not built yet

## License

MIT
