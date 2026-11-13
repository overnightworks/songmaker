# Songmaker

AI-powered song generation platform. Create albums and songs with lyrics + style prompts, generate music via [ACE-Step](https://github.com/ace-step/ACE-Step), auto-master to MP3, and score quality.

SvelteKit frontend + FastAPI backend + PostgreSQL + Redis + arq job workers + GPU ACE-Step worker.

## Deployment and the test stack

The platform serves Songmaker: it runs the web app, both arq workers, the ACE-Step GPU worker, PostgreSQL and Redis from the images the Release workflow pushes. This repository ships no deploy file.

[`docker/docker-compose.test.yml`](docker/docker-compose.test.yml) is the test stack: CI's e2e boot, the GPU and Voices probes and local e2e runs boot it with throwaway secrets. Run every Compose call from the repository root, so the project name, the root `.env` and the relative paths keep resolving there:

```bash
docker compose --project-directory . -f docker/docker-compose.test.yml up -d --build --wait postgres redis
```

[frontend/e2e/README.md](frontend/e2e/README.md#running-it-locally) lists the secrets and the boot steps of a local run; the ACE-Step worker runs only in the `gpu` profile.

## Operations

- **Updates:** the platform deploys a release tag (`vYYYY.MM.DD.N` on `main`) through Flux; the operator dispatches the Release workflow, which gates `main`, pushes the images to GHCR and sets the tag, and a merge to `main` alone deploys nothing.
- **Backup:** PostgreSQL and the audio volume are backed up together and restored by the platform's k8up (platform `docs/app.md`, `docs/runbooks/restore-a-database.md`).
- **Container confinement:** [docs/security.md](docs/security.md#container-confinement).

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
