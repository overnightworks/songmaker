# #532 Provider routes — implementation plan

**Reader / decision:** builder and reviewer; precise contract for making the admin's per-provider `CLI`/`API` choice the sole route selection for new Co-Writer turns.
## Scope and cut

The existing implicit discriminator is `CLI` when its login is usable, otherwise `API` (`dispatch.py`, `catalog.py`). This slice makes that choice explicit for Claude, Grok, and Codex. It does not change the independent Judge choice.

If the implementation estimate exceeds one hour, dispatch these disjoint slices:

1. **Backend:** persisted route setting, route-aware readiness/catalog/dispatch, API contract, and Python tests.
2. **Panel:** typed client, Models tab, Vitest, and the design-picture amendment (which the head presents for approval before this slice is built).
## 1. Persist and expose the route choice

- Add `SETTING_PROVIDER_ROUTES = "provider_routes"` in `constants.py`; store a
  validated JSON object `{ "claude": "cli", "grok": "api", "codex": "cli" }`
  in the global (`user_id IS NULL`) `rate_limit_settings.value_text` row.  This is
  the same table and text-setting owner as `cowriter_provider`/`cowriter_model`,
  not a user setting and never an environment value.
- `db/queries/settings.py` owns parsing, provider/route enum validation, complete
  writes, and the effective map.  Missing or malformed legacy row fails loudly;
  an absent row resolves each provider through the single legacy-default resolver:
  CLI when that provider's login discriminator says usable, otherwise API.
- No Alembic migration: `rate_limit_settings` is already the generic keyed text
  store and absence has a defined backwards-compatible effective default.  The
  first successful admin save creates the row atomically; no credential or route
  is inferred or written by a database migration.
- Extend `GET`/`PUT /api/settings/cowriter`, Pydantic models, frontend API types,
  and `updateCowriterSettings` to round-trip the complete effective `provider_routes`
  map.  `PUT` validates all three provider names and only `cli|api`, writes it with
  the provider/model/budget in one transaction, records route names (never keys)
  in the existing Co-Writer audit event, and returns the fresh effective state.
## 2. One route owner from setting to turn

- `cowriter/catalog.py` owns the shared `ProviderRoute` value and the function
  that evaluates one explicit `(provider, route)`; it receives a route, never
  chooses a fallback.  The settings query's legacy-default resolver is the only
  place allowed to reproduce today's discriminator for an unset setting.
- `conversation_api.py` reads provider, model, and its effective route once before
  constructing the SSE stream, then passes that immutable route to
  `stream_cowriter_turn`.  A later save therefore changes only new turns; the
  already-created stream ends on its captured route.
- `dispatch.py` switches solely on that route: CLI calls the provider's existing
  CLI adapter; API requires that provider's `.env` key and calls its API adapter.
  It must not inspect a login token to select API, and any selected-route error is
  re-raised as that provider's named `ProviderUnavailableError` without HTTP/CLI
  fallback.  Claude's API route uses an Anthropic Messages/tool-loop adapter that
  emits the existing `StreamEvent` contract and delegates tool execution to the
  existing Co-Writer tool owner; do not pretend the OpenAI-compatible adapter is
  Anthropic.
- The catalog refresh, status endpoint, save validation, and model lookup receive
  the same explicit route.  Remove the current `_catalog_configuration` and
  `dispatch` token-preference branches rather than retaining parallel selection
  logic.  Judge configuration remains its current API-only concern.
## 3. Per-route readiness and model catalog

- Replace the one Co-Writer configuration/catalog in `ProviderSnapshot` with
  route-keyed snapshots.  A route reports `ready`, `not_configured`, or `disturbed`
  plus a safe reason, probe time, setup label, and model-catalog source; `unverified`
  remains only the honest loading/freshness state before a background probe.
- Sources are route-specific: Claude CLI uses structured `claude auth status` and
  its `/model` list; Grok CLI uses strict `grok models` login/model parsing; Codex
  CLI uses `codex login status`.  API is `ANTHROPIC_API_KEY`, `XAI_API_KEY`, or
  `OPENAI_API_KEY` presence from `Settings` plus its matching provider models
  endpoint.  Only `set`/`not set` and named probe failures cross the API boundary;
  no secret value enters a response, log, audit entry, or UI.
- Missing key/login is `not_configured`; absent binary, rejected/expired login,
  dependency failure, malformed CLI output, or failed live catalog probe is
  `disturbed`.  A selected non-ready route blocks its provider's turn with that
  reason; no alternative route is attempted.  If neither route is ready, the
  provider is unavailable.
- `list_provider_models(provider, route)` lists from the selected route only:
  API lists live provider endpoint IDs; Claude CLI uses its real aliases; Grok CLI
  uses `grok models`; Codex CLI uses #524's known list.  Return a source/version
  label whenever supplied (including CLI version where obtainable); keep the
  current valid stored model appended once when the live list no longer contains
  it, so it remains selectable and honestly marked.
- Shape `CowriterSettingsResponse` around provider-and-route model/status data;
  derive the active provider's selected-route `allowed_models` from it so existing
  consumers have one authoritative view.  Keep error/source maps keyed by the
  same provider+route identity, not by a silently chosen provider route.
## 4. Models panel and design owner

- In `frontend/src/routes/settings/users/+page.svelte`, keep the active/pending
  banner and provider picker, add a two-way route control for every provider, and
  show `ready` / `not configured` / `disturbed` text and its safe source beside
  each route.  A disabled or failed selected route is visible and named, never
  replaced in the UI.  Moving the route changes the displayed model list before
  Save; Save's pending banner names provider, route, and model.
- Bind the model dropdown to the selected provider+route catalog; show its source
  and version label, catalog failure, and the retained stored model.  Move all
  new English labels, messages, and route/state formatting to `constants.ts`.
  No input, text, or DOM attribute represents an API-key value.
- Before building UI, amend `docs/design/admin-models.html` with route toggles and
  per-route status text for all three states, then give that frozen picture to the
  head for operator approval.  Build the approved picture; update the design
  README only if its existing owner description must change.
## 5. Verification

- Python (`tests/test_cowriter_catalog.py`, `test_cowriter_dispatch.py`,
  `test_cowriter_providers.py`): legacy default matches today's discriminator;
  complete route-map read/write validation and instance-wide scope; every
  provider's explicit CLI/API route uses only its adapter; selected missing,
  expired, unavailable, or malformed route emits the named error and never
  falls back; changing a route leaves an in-flight captured route unchanged.
- Catalog/status tests cover all three state classes per route, safe key exposure,
  API live endpoint selection, Grok CLI parsing, Codex known-list source/version,
  and retained valid stored model for an absent live entry.  API tests prove only
  admins may change routes and new route/model saves reject the chosen non-ready
  route or a foreign/unknown model.
- Mark and preserve the acceptance proof mapping: `REQ-COWRITER-09` proves exactly
  one explicit provider+route adapter is invoked; `REQ-COWRITER-10` proves the
  absent setting's Claude default; `REQ-COWRITER-11` proves named selected-route
  failure with no fallback.  Add/adjust acceptance entries only where the ritual
  can honestly execute the stated integration proof.
- Vitest (`frontend/src/routes/settings/users/page.test.ts`) covers route controls,
  pending/save state, every displayed route state, route-specific catalog/source,
  retained model, no-key presentation, and admin-only rendering.  Run targeted
  Python and frontend suites plus the requirement-contract test; the panel slice
  also needs the approved-picture browser proof at desktop and compact widths.
