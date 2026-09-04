# #532 Provider routes — implementation plan

**Reader / decision:** builders and reviewers; the admin's saved per-provider `CLI`/`API` choice is the only Co-Writer route selection for *new* turns.  Judge remains a separate API-only concern.

## Goal and fixed cut

Make the route explicit and durable for Claude, Grok, and Codex without silently changing existing installations.  A saved route is global, never user- or environment-scoped.  A selected route either runs or returns that route's named failure; it never falls through to the other route.

This issue is deliberately cut into three independently landable items.  Each slice is sized for well under an hour and owns only the listed files/contracts.

| Slice | Owns | Done when |
| --- | --- | --- |
| **R2a — backend provider routes** | Settings persistence/API, default resolver, route-aware catalog/readiness/dispatch, Python tests and edge proofs | A complete, explicit backend contract works without a UI and has no fallback or second route chooser. |
| **R2b — Models panel and picture** | `docs/design/admin-models.html`, then the Models panel, client types and Vitest/browser proof | The operator has blessed the frozen design picture before the panel is built; the panel faithfully exposes every route state. |
| **R2c — Claude API tool loop** | Anthropic Messages adapter, Co-Writer tool loop/schema, focused tests | Claude API can execute the existing Co-Writer tools through Anthropic's native loop. |

R2a is first.  R2b depends on R2a's returned JSON contract and the approved design picture.  R2c is a new item and does **not** block R2a: until it lands, Claude's API route reports `not_configured` with the safe, named reason **`Claude over API needs the tool loop — coming`**.  It must not call `call_claude()`, select CLI, or otherwise quietly fall back.  No Alembic migration belongs to any slice.

## R2a — backend provider routes

### 1. One persisted setting and one legacy-default owner

- Add `SETTING_PROVIDER_ROUTES = "provider_routes"` in `constants.py`.  `db/queries/settings.py` owns its compact JSON encoding, parsing, enum validation, atomic complete writes, and effective-map resolution.  Store exactly a complete object such as `{"claude":"cli","grok":"api","codex":"cli"}` in the global (`user_id IS NULL`) `rate_limit_settings.value_text` row, alongside the existing global Co-Writer provider/model settings.  It is neither a user setting nor an environment value.
- `get_effective_provider_routes` is the **only** legacy-default resolver and runs only when the row is absent or empty.  It reproduces present `dispatch.py` behaviour exactly, provider by provider: Claude defaults to `cli` unconditionally; Grok and Codex use the current dispatch login-token probe (`True → cli`, `False → api`).  An `AgentCliUnavailableError` from that probe remains a named unavailable condition, not an API default.  Catalog API-key preference must never participate in this resolver.
- A non-empty row that is malformed JSON, non-object, missing/extra provider, or has any value outside `cli|api` fails loudly on GET, PUT, and a turn; it is not repaired by a discriminator.  Empty `value_text` means absent for backward compatibility.  The compact encoding has a test asserting it fits the current `String(100)` column.
- The first successful admin save atomically creates the row with the Co-Writer provider, model, and budget update.  There is no migration because the keyed text store already owns this value and absence has the defined compatibility result.  No key, credential, or inferred route is written by a migration.

### 2. Exact public response and PUT contract

- Extend `CowriterSettingsResponse`, `GET /api/settings/cowriter`, `PUT /api/settings/cowriter`, and the corresponding request/response construction with effective `provider_routes: {claude,grok,codex: cli|api}` plus route-keyed snapshots for **both** paths of every provider.  Pin the route identity as `provider_routes_status[provider][route]`, with `state`, safe `reason`, `probed_at`, `setup_label`, `catalog_source`, and `catalog_version` where available.  `state` is `ready`, `not_configured`, `disturbed`, or the honest pre-probe/loading state `unverified`.
- Preserve the existing provider-keyed Co-Writer fields as an additive compatibility projection of the effective **selected** route: `allowed_models`, `models_by_provider`, `models_errors`, `models_sources`, `current_models_not_in_catalog`, and `probed_at`.  This keeps existing callers working while giving the pending client both routes before Save.  The projection contains no independently selected route and is derived from the same route-keyed snapshot.
- `GET /api/settings/providers` exposes Co-Writer state for each provider and route from the same snapshots; it no longer collapses state through a hidden discriminator.  Its Judge representation stays API-only and unchanged.  Retain mixed states such as `cli_login_needs_api_key` or `api_key_needs_cli_login` only if Judge still genuinely needs them.
- `CowriterSettingsRequest`/PUT requires a complete `provider_routes` map and accepts only the three known providers and `cli|api`.  It writes provider, model, budget, and route map in one transaction; only existing administrators may write it.  Audit the route *names* and never a secret or secret-derived value.
- PUT returns 422 only when the **active** `(provider, requested route)` is not ready, or when the submitted model is foreign/unknown for that active pair.  The other providers' routes may be unready and still persist, so an administrator can preconfigure them.  A retained active model marked `not_in_catalog` remains valid for save.  The response is read fresh from the committed setting.
- A musician may read the effective map via `GET /settings/cowriter`; `CoWriterPanel` does not render route controls.  No API response, audit event, log, input, text, or DOM attribute contains an API-key value.  Key configuration is limited to `Settings.anthropic_api_key`, `xai_api_key`, and `openai_api_key` / `.env`.

### 3. One explicit route from a new turn to its adapter

- Define the shared `ProviderRoute` value with the Co-Writer catalog/route owner.  Route evaluation takes an explicit `(provider, route)` and never chooses or falls back.  Delete `_catalog_configuration` and the dispatch token-preference branches rather than retaining parallel selection logic.
- `conversation_api.py` reads the effective provider, model, and route **once before creating the SSE generator**, captures them immutably, and supplies `route` as a required argument to `stream_cowriter_turn`.  A later save can affect only new turns; an in-flight stream completes on its captured route.  No code inside the generator rereads settings.
- `stream_cowriter_turn(..., route: ProviderRoute)` switches only on that value.  CLI calls the existing provider CLI adapter.  API requires the matching `.env` key and calls that provider's API adapter.  Missing selected-route setup, a rejected/expired login, unavailable binary, malformed CLI output, tool failure, or HTTP failure becomes that provider's named `ProviderUnavailableError`; it does not trigger the other adapter or any second HTTP/CLI attempt.
- While R2c is open, the Claude API branch is an explicit unavailable route with the safe reason `Claude over API needs the tool loop — coming`; it cannot use the OpenAI-compatible code or `call_claude()`.  R2c replaces that temporary route outcome with Anthropic's native implementation.
- `call_provider_once` has no route argument and remains the Judge's API-only call.  Judge model catalogues likewise always use their API route; no CLI catalogue fallback is introduced.

### 4. Route-keyed readiness and catalogues

- Replace `ProviderSnapshot`'s one Co-Writer configuration with snapshots keyed by `(provider, route)`; refresh probes **both** routes for every provider.  The toggle selects dispatch and the active dropdown only—it must not determine which routes are refreshed.  A provider with no ready routes is unavailable, but the UI/API continues to name the route the setting selected.
- Each route carries a safe readiness result, probe time, setup label, catalogue source, and source version whenever the source provides one.  `unverified` is only the honest state before/background freshness work, not a disguised configuration result.
- CLI routes: Claude probes structured `claude auth status` and its real `/model` aliases; Grok uses strict `grok models` login/model parsing; Codex uses `codex login status` and #524's known list.  API routes use the matching `Settings` key presence and the provider's live models endpoint.  Report only `set`/`not set` and named probe failures across the boundary.
- A missing CLI login or API key is `not_configured`.  A missing binary, rejected/expired login, dependency failure, malformed `grok models` output, or failed live catalogue probe is `disturbed`.  Neither status permits routing to its sibling path.  Both paths unready means the provider is unavailable; the UI never replaces the chosen route.
- `list_provider_models(provider, route)` queries only that explicit route.  It returns API endpoint IDs, real Claude CLI aliases, strict Grok CLI output, or Codex's known-list source as appropriate, including a version label when obtainable.  `models_with_active_model` appends the currently stored model exactly once for the active route even if it has no provider prefix (for example Claude's `sonnet` alias); mark it `not_in_catalog` rather than dropping it.  Persisting that retained active pair remains allowed by PUT.

### 5. R2a verification and edge proof

- Add focused Python coverage in `tests/test_cowriter_catalog.py`, `test_cowriter_dispatch.py`, `test_cowriter_providers.py`, and settings/API tests as needed.  Prove compact global persistence; absent/empty/malformed setting behaviour; exact per-provider defaults (Claude always CLI; Grok/Codex token-present → CLI and token-absent → API); complete PUT validation; admin-only write; and the active-pair-only 422 rules.
- Prove each provider/route calls exactly its explicit adapter; a CLI error makes no HTTP request and an API error makes no CLI request; route choice is captured before SSE generation; and neither response, error, audit, nor logs leaks a key.  Keep `REQ-COWRITER-09` and `REQ-COWRITER-11` at their existing meanings (one selected provider/adapter and its named no-fallback error); do **not** relabel `REQ-COWRITER-10`, which proves the default **provider**, as a route-default proof.
- Cover both-route snapshot refresh, every readiness state, live API source selection, strict Grok parsing, Codex source/version, Claude CLI aliases, and retained non-prefixed alias/model once as `not_in_catalog`.  Prove selected unavailable route blocks the turn, both paths unready make the provider unavailable, and Judge catalogue/call remain API-only.
- Run the targeted Python suites, settings requirement-contract test, type/lint checks required by the repository, and a self-review confirming deletion of both hidden route selectors.

## R2b — picture first, then Models panel

1. Before any panel implementation, amend `docs/design/admin-models.html`, the picture owner, with a route toggle for every provider and a visible CLI/API state line for each route.  Show all three meaningful route outcomes—`ready`, `not configured`, and `disturbed`—along with safe source/version/reason and the retained-model presentation.  The provider list must not hide a collapsed discriminator.  Give this frozen repository picture to the head for operator blessing; stop until blessed.
2. After blessing and R2a, update `frontend/src/lib/api/types.ts`, `frontend/src/routes/settings/users/+page.svelte`, and the established client request helper.  The Models tab shows the active/pending banner and provider picker, a two-way route control for every provider, each route's state/source, and the selected provider+route catalogue.  Changing a pending route changes only the pending displayed models; Save's banner names provider, route, and model.
3. Show catalogue source/version, `not_in_catalog` retained model, and safe catalogue failure.  A selected disabled/failed route remains visibly selected and named—there is no UI substitution.  Move new English strings and route/state formatting to `constants.ts`; do not expose an API key in any UI representation.  `CoWriterPanel` remains read-only for routes.
4. Add Vitest coverage for toggles, route-specific catalogue/source/version, each displayed state, selected failure, retained model, save/pending state, no-key rendering, and administrator-only controls.  Drive the blessed panel in a real browser at desktop and compact widths and retain that as the visual proof.

## R2c — Claude API adapter with native tool loop

1. Create a dedicated Anthropic Messages Co-Writer adapter.  It uses the Anthropic API and its native tool-use/result loop, emits the existing `StreamEvent` contract, and delegates every requested tool to the established `execute_cowriter_tool` owner.
2. Put the Anthropic tool schema beside `openai_tool_schemas`; do not claim OpenAI compatibility or duplicate the tool executor.  Map API, tool, and protocol failures to Claude's named selected-route error without a CLI retry.
3. Replace R2a's temporary Claude-API `not_configured` outcome only after focused adapter/loop/error tests pass.  Re-run R2a's no-fallback and API contract tests, then use independent review before landing this public route.

## Simplification and landing gates

- Remove the obsolete `_catalog_configuration` and all dispatch/catalog branches that decide a Co-Writer path from token/key availability.  There must be one persisted route owner, one legacy-default resolver, and one route argument at dispatch.
- Land R2a, then update #532's projection with R2b and R2c as its only remaining work; neither is silently absorbed into a large backend change.  R2b may start only after the picture is blessed.  R2c is dispatched as its own item when its dependency is clear.
