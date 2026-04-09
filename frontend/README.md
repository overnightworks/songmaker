# Songmaker frontend

SvelteKit web UI for the Songmaker backend. Runs as a static SPA build, served by the FastAPI app from `frontend/build/` in production. In development, the Vite dev server proxies API calls to the running backend.

## Layout

```
src/
├── lib/
│   ├── api/             Typed API client (generated types from backend Pydantic models)
│   ├── components/      Reusable UI components
│   ├── stores/          Svelte stores (auth, editor, player, jobs, filters, settings)
│   └── utils/           Diff, format, time helpers
├── routes/              SvelteKit pages
└── tests/               Vitest + jsdom unit tests
```

## Conventions

- **Types are generated, not handwritten.** `src/lib/api/types.ts` is regenerated from the backend Pydantic models by `python scripts/generate_types.py` (runs at the project root). CI fails if `types.ts` is out of sync. Never edit `types.ts` by hand.
- **API calls go through `lib/api/`** — never `fetch()` from a component or store directly. The client wraps error handling, CSRF, and the canonical base URL.
- **State lives in stores**, not in component-local state, when it crosses page or component boundaries.
- **Test stores and utils**, not components yet (component test scaffolding is planned in `plans/frontend-component-split.md`).

## Local development

The backend must already be running (via `docker compose up -d --build --wait` from the project root). The Vite dev server proxies `/api` and `/static` to `http://localhost:8080`.

```bash
# One-time
pnpm install

# Dev server with HMR (proxies /api to the Docker backend)
pnpm dev

# Build the production SPA bundle (FastAPI serves it from frontend/build/)
pnpm build

# Tests, lint, type-check
pnpm test
pnpm lint
pnpm check
```

## Regenerating types after a backend Pydantic change

```bash
# From the project root
python scripts/generate_types.py

# Verify
cd frontend && pnpm check
```

## Production deployment

The build output (`frontend/build/`) is copied into the songmaker-web Docker image during `docker compose up --build`. There is no separate frontend container — FastAPI mounts the SPA assets and serves the SPA fallback for unknown routes. See `src/songmaker_cli/server.py` for the static-file mounting and CSP setup.

## See also

- [`../CLAUDE.md`](../CLAUDE.md) — project conventions, code patterns, "Where Things Go" (frontend row)
- [`../docs/architecture.md`](../docs/architecture.md) — backend layout, API endpoints, generation flow
- [`../docs/security.md`](../docs/security.md) — auth, CSRF, security headers (the frontend must call CSRF-protected endpoints with the `X-CSRF-Token` header)
- [`../plans/frontend-component-split.md`](../plans/frontend-component-split.md) — proposed refactor for the god components and component test scaffolding
