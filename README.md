# Songmaker

AI-powered song generation platform. Create albums and songs with lyrics + style prompts, generate music via [ACE-Step](https://github.com/ace-step/ACE-Step), auto-master to MP3, and score quality.

SvelteKit frontend + FastAPI backend + PostgreSQL + Redis + arq job workers + GPU ACE-Step worker.

## Run with Docker

Songmaker is Docker-only; there is no native local-dev path. The stack runs the web app, both arq workers, the ACE-Step GPU worker, PostgreSQL, Redis, Prometheus, and Grafana.

Requires: Docker (with Compose v2), NVIDIA Container Toolkit (for GPU generation), and a Hugging Face token (for downloading model weights).

Install and first start, in the deploy checkout `~/srv/songmaker` (a clone at a release tag; a work clone has no `.env` and cannot start the live stack):

```bash
sudo ./scripts/apparmor/install.sh                # songmaker-web does not start without its AppArmor profile
cp docker/.env.docker.example .env                # fill in the required secrets
docker compose up -d --build --wait               # never wrap in `timeout`
sudo ./scripts/install-cli-credentials-mirror.sh  # agent-CLI login mirror
sudo ./scripts/install-autostart.sh               # start the stack after every boot
```

- [`docker/.env.docker.example`](docker/.env.docker.example) lists every setting, which ones are required, and how to generate secrets.
- A cold-cache build takes 8-15 minutes; [AGENTS.md](AGENTS.md#setup-and-run) says why it must not be interrupted. The first start also downloads the ACE-Step model weights into a Docker volume.
- All persistent state (database, audio files, model cache, Grafana dashboards) lives in named Docker volumes and survives `docker compose down` and rebuilds.
- AppArmor rollout, proof and removal: [docs/security.md](docs/security.md). Why Docker's restart policy alone does not survive every reboot, and what the autostart unit adds: [docs/acestep.md](docs/acestep.md#restart-policy-limits-and-boot-autostart).

## Operations

- **Moving the deploy checkout:** `scripts/switch_deploy_checkout.sh <tag>` switches a host from the work clone `~/git/songmaker` to the release clone `~/srv/songmaker` (it prints each step, stops at the first failed check and asks before deleting the old `.env`); `scripts/switch_deploy_checkout.sh --backout` returns, until a release has deployed from `~/srv/songmaker`. Neither touches the running containers.
- **Updates:** a systemd timer (`scripts/install-autodeploy.sh` installs it) runs `scripts/auto-deploy.sh`, which redeploys a release tag (`vYYYY.MM.DD.N` on `main`) once its checks are green and no job is running; a merge to `main` alone deploys nothing, and the header owns the rules.
- **Logs and status:** `docker compose logs -f <service>` and `docker compose ps -a` (`-a` also shows a created-but-never-started container).
- **Stop and start:** `docker compose stop` / `docker compose start` keep the volumes.
- **Backup:** PostgreSQL and the audio volume must be backed up together with `scripts/backup.sh`; setup, cron and restore are in [`scripts/BACKUP.md`](scripts/BACKUP.md).

## Development

Local tests, lint, type checking and the Python and frontend toolchain are in [AGENTS.md](AGENTS.md#checks); test structure and coverage gates are in [docs/testing.md](docs/testing.md). The live app never runs from the local `.venv`.

## Docs

- [AGENTS.md](AGENTS.md): project conventions, code patterns, and known constraints. Read this first if you are contributing.
- [docs/VISION.md](docs/VISION.md): why Songmaker exists, desired outcomes, guardrails, non-goals
- [docs/requirements/](docs/requirements/): ruled product sentences
- [docs/architecture.md](docs/architecture.md): system design, data model, API endpoints, worker pool, monitoring
- [docs/security.md](docs/security.md): auth, sessions, CSRF, rate limiting, security headers, trust boundaries
- [docs/testing.md](docs/testing.md): test structure, fixtures, coverage targets
- [docs/acestep.md](docs/acestep.md): ACE-Step integration, model variants, worker pool, generation parameters
- [docs/design/](docs/design/README.md): UI mockups

## License

MIT
