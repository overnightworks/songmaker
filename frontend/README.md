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
- **API calls go through `lib/api/`** — never `fetch()` from a component or store directly. The client wraps error handling and the canonical base URL.
- **State lives in stores**, not in component-local state, when it crosses page or component boundaries.
- **Test stores, utils and components** (for example `AlbumMetaEditor.test.ts`).

## Local development

The dev server needs a backend: boot a probe stack as [`e2e/README.md`](e2e/README.md#running-it-locally) describes (never the live stack on 8080) and name it in `SONGMAKER_API_TARGET`; without it `pnpm dev` refuses to start. It proxies `/api`, `/ws`, `/audio`, `/shared`, `/login/oidc` and `/auth/logout` there.

```bash
pnpm install

# Dev server with HMR, proxying to the probe stack
SONGMAKER_API_TARGET=http://localhost:18080 pnpm dev

# Build the production SPA bundle (FastAPI serves it from frontend/build/)
pnpm build

# Targeted tests (CI runs the full suite), lint, type-check
pnpm exec vitest run src/lib/stores/player.test.ts
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

- [`../AGENTS.md`](../AGENTS.md) — project conventions, code patterns
- [`../docs/architecture.md`](../docs/architecture.md) — backend layout, API endpoints, generation flow
- [`../docs/security.md`](../docs/security.md) — auth, CSRF, security headers (the origin check guards writes; the frontend sends no token)
