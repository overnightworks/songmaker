<script module lang="ts">
	import type { SafeRouteReason } from '$lib/api/types';

	export type ModelsRouteKey = 'cli' | 'api';

	export interface ModelsTaskRoute {
		ready: boolean;
		reason: SafeRouteReason | null;
		models: string[];
		modelsReason?: string | null;
	}

	export interface ModelsTaskProvider {
		provider: string;
		label: string;
		routes: Record<ModelsRouteKey, ModelsTaskRoute>;
	}

	export interface ModelsTaskSelection {
		provider: string;
		route: ModelsRouteKey;
		model: string;
	}

	export type ModelsSaveOutcome = { ok: true } | { ok: false; reason: string };

	export const MODELS_ROUTES: ModelsRouteKey[] = ['cli', 'api'];
</script>

<script lang="ts">
	import type { Snippet } from 'svelte';
	import {
		MODELS_ADVANCED_LABEL,
		MODELS_COLUMN_MODEL_LABEL,
		MODELS_COLUMN_PROVIDER_LABEL,
		MODELS_COLUMN_ROUTE_LABEL,
		MODELS_COLUMN_STATUS_LABEL,
		MODELS_LIST_NEEDS_CLI_HINT,
		MODELS_LIST_NEEDS_KEY_HINT,
		MODELS_NO_MODELS_LABEL,
		MODELS_OPTION_NEEDS_API_KEY_PHRASE,
		MODELS_OPTION_READY_LABEL,
		MODELS_RETRY_LABEL,
		MODELS_ROUTE_KEY_NOT_SET_PHRASE,
		MODELS_ROUTE_KEY_SET_PHRASE,
		MODELS_ROUTE_LOGGED_IN_PHRASE,
		MODELS_ROUTE_NOT_LOGGED_IN_PHRASE,
		MODELS_ROUTE_NO_IMAGE_TOOL_PHRASE,
		MODELS_SAVED_LABEL,
		MODELS_STATUS_CHECKING_LABEL,
		MODELS_STATUS_NEEDS_API_KEY_LABEL,
		MODELS_STATUS_NOT_SAVED_LABEL,
		MODELS_STATUS_READY_CLI_LABEL,
		MODELS_STATUS_READY_KEY_LABEL,
		PROVIDER_ROUTE_API_LABEL,
		PROVIDER_ROUTE_CLI_LABEL,
		modelsCannotDrawHint
	} from '$lib/constants';

	interface Props {
		task: string;
		providers: ModelsTaskProvider[];
		selection: ModelsTaskSelection;
		save: (selection: ModelsTaskSelection) => Promise<ModelsSaveOutcome>;
		routeSelectable?: boolean;
		advanced?: Snippet;
	}

	let { task, providers, selection, save, routeSelectable = true, advanced }: Props = $props();

	const taskId = $derived(task.toLowerCase().replace(/\s+/g, '-'));
	const routeReasonsId = $derived(`${taskId}-route-reasons`);
	const modelsHintId = $derived(`${taskId}-models-hint`);

	let pending = $state<ModelsTaskSelection | null>(null);
	let saved = $state(false);
	let failure = $state<string | null>(null);
	let saveToken = 0;

	const current = $derived(pending ?? selection);
	const providerView = $derived(providers.find((entry) => entry.provider === current.provider));
	const routeView = $derived(providerView?.routes[current.route]);
	const modelOptions = $derived(modelOptionsOf(routeView?.models ?? [], current.model));
	const status = $derived(statusOf());
	const routeReasons = $derived(reasonsOf());
	const modelsHint = $derived(modelsHintOf());

	function routeLabel(route: ModelsRouteKey): string {
		return route === 'cli' ? PROVIDER_ROUTE_CLI_LABEL : PROVIDER_ROUTE_API_LABEL;
	}

	function readyPhrase(route: ModelsRouteKey): string {
		return route === 'cli' ? MODELS_ROUTE_LOGGED_IN_PHRASE : MODELS_ROUTE_KEY_SET_PHRASE;
	}

	function failurePhrase(reason: SafeRouteReason, route: ModelsRouteKey): string {
		if (reason.code === 'api_key_not_set') return MODELS_ROUTE_KEY_NOT_SET_PHRASE;
		if (reason.code === 'no_image_tool') return MODELS_ROUTE_NO_IMAGE_TOOL_PHRASE;
		if (reason.code === 'cli_login_not_configured' && route === 'cli') {
			return MODELS_ROUTE_NOT_LOGGED_IN_PHRASE;
		}
		return reason.message;
	}

	function routeReason(route: ModelsRouteKey): string | null {
		const view = providerView?.routes[route];
		if (!view) return null;
		if (view.ready) return `${routeLabel(route)} · ${readyPhrase(route)}`;
		if (!view.reason) return null;
		return `${routeLabel(route)} · ${failurePhrase(view.reason, route)}`;
	}

	function reasonsOf(): { route: ModelsRouteKey; text: string; warn: boolean }[] {
		const others = MODELS_ROUTES.filter((route) => route !== current.route);
		const shown = routeView?.ready === false ? [current.route, ...others] : others;
		return shown.flatMap((route) => {
			const text = routeReason(route);
			if (text === null) return [];
			return [{ route, text, warn: route === current.route }];
		});
	}

	function modelsHintOf(): string | null {
		if (modelOptions.length > 0) return null;
		const reason = routeView?.reason;
		if (!reason) return routeView?.modelsReason ?? null;
		if (reason.code === 'api_key_not_set') return MODELS_LIST_NEEDS_KEY_HINT;
		if (reason.code === 'cli_login_not_configured') return MODELS_LIST_NEEDS_CLI_HINT;
		if (reason.code === 'no_image_tool') {
			return modelsCannotDrawHint(providerView?.label ?? current.provider);
		}
		return reason.message;
	}

	function statusOf(): { shape: 'ok' | 'warn' | 'off' | 'bad'; mark: string; text: string } {
		if (failure !== null) return { shape: 'bad', mark: '✕', text: MODELS_STATUS_NOT_SAVED_LABEL };
		if (!routeView || (!routeView.ready && !routeView.reason)) {
			return { shape: 'off', mark: '○', text: MODELS_STATUS_CHECKING_LABEL };
		}
		if (routeView.ready) {
			return {
				shape: 'ok',
				mark: '✓',
				text:
					current.route === 'cli' ? MODELS_STATUS_READY_CLI_LABEL : MODELS_STATUS_READY_KEY_LABEL
			};
		}
		const reason = routeView.reason as SafeRouteReason;
		if (reason.code === 'api_key_not_set') {
			return { shape: 'warn', mark: '!', text: MODELS_STATUS_NEEDS_API_KEY_LABEL };
		}
		const name = providerView?.label ?? current.provider;
		if (reason.code === 'no_image_tool') {
			return { shape: 'off', mark: '○', text: `${name} · ${MODELS_ROUTE_NO_IMAGE_TOOL_PHRASE}` };
		}
		if (reason.code === 'cli_login_not_configured') {
			return {
				shape: 'off',
				mark: '○',
				text: `${name} ${PROVIDER_ROUTE_CLI_LABEL} ${MODELS_ROUTE_NOT_LOGGED_IN_PHRASE}`
			};
		}
		return { shape: 'off', mark: '○', text: `${name} · ${reason.message}` };
	}

	function providerOptionLabel(entry: ModelsTaskProvider): string {
		if (MODELS_ROUTES.some((route) => entry.routes[route].ready)) {
			return `${entry.label} ${MODELS_OPTION_READY_LABEL}`;
		}
		const keyMissing = MODELS_ROUTES.some(
			(route) => entry.routes[route].reason?.code === 'api_key_not_set'
		);
		if (keyMissing) return `${entry.label} · ${MODELS_OPTION_NEEDS_API_KEY_PHRASE}`;
		for (const route of MODELS_ROUTES) {
			const reason = entry.routes[route].reason;
			if (reason) return `${entry.label} · ${failurePhrase(reason, route)}`;
		}
		return `${entry.label} · ${MODELS_STATUS_CHECKING_LABEL}`;
	}

	function modelOptionsOf(models: string[], model: string): string[] {
		if (model === '' || models.includes(model)) return models;
		return [...models, model];
	}

	function routeFor(entry: ModelsTaskProvider | undefined, preferred: ModelsRouteKey) {
		if (!entry || entry.routes[preferred].ready) return preferred;
		const ready = MODELS_ROUTES.filter((route) => entry.routes[route].ready);
		return ready.length === 1 ? ready[0] : preferred;
	}

	function modelFor(
		entry: ModelsTaskProvider | undefined,
		route: ModelsRouteKey,
		preferred: string
	): string {
		const models = entry?.routes[route].models ?? [];
		if (models.includes(preferred)) return preferred;
		return models[0] ?? '';
	}

	async function persist(next: ModelsTaskSelection): Promise<void> {
		const token = ++saveToken;
		pending = next;
		saved = false;
		failure = null;
		const outcome = await save(next);
		if (token !== saveToken) return;
		if (outcome.ok) {
			pending = null;
			saved = true;
			return;
		}
		failure = outcome.reason;
	}

	function chooseProvider(provider: string): void {
		const entry = providers.find((candidate) => candidate.provider === provider);
		const route = routeFor(entry, current.route);
		void persist({ provider, route, model: modelFor(entry, route, current.model) });
	}

	function chooseRoute(route: ModelsRouteKey): void {
		void persist({
			provider: current.provider,
			route,
			model: modelFor(providerView, route, current.model)
		});
	}

	function chooseModel(model: string): void {
		void persist({ ...current, model });
	}
</script>

<div
	class="tt-row"
	class:warn={status.shape === 'warn'}
	class:off={status.shape === 'off'}
	class:bad={status.shape === 'bad'}
>
	<div class="cell cell-task">{task}</div>

	<div class="cell">
		<span class="k" aria-hidden="true">{MODELS_COLUMN_PROVIDER_LABEL}</span>
		<select
			class="sel"
			aria-label={`${task} ${MODELS_COLUMN_PROVIDER_LABEL.toLowerCase()}`}
			value={current.provider}
			onchange={(event) => chooseProvider(event.currentTarget.value)}
		>
			{#each providers as entry (entry.provider)}
				<option value={entry.provider}>{providerOptionLabel(entry)}</option>
			{/each}
		</select>
	</div>

	<div class="cell">
		<span class="k" aria-hidden="true">{MODELS_COLUMN_ROUTE_LABEL}</span>
		<div
			class="rsw"
			role="group"
			aria-label={`${task} ${MODELS_COLUMN_ROUTE_LABEL.toLowerCase()}`}
			aria-describedby={routeReasons.length > 0 ? routeReasonsId : undefined}
		>
			{#each MODELS_ROUTES as route (route)}
				{@const view = providerView?.routes[route]}
				{@const chosen = current.route === route}
				<button
					type="button"
					class:on={chosen && view?.ready === true}
					class:picked-dead={chosen && view?.ready !== true}
					class:dead={!chosen && view?.ready !== true}
					aria-pressed={chosen}
					disabled={!routeSelectable}
					onclick={() => chooseRoute(route)}>{routeLabel(route)}</button
				>
			{/each}
		</div>
		<span id={routeReasonsId}>
			{#each routeReasons as reason (reason.route)}
				<small class="why" class:warn={reason.warn}>{reason.text}</small>
			{/each}
		</span>
	</div>

	<div class="cell">
		<span class="k" aria-hidden="true">{MODELS_COLUMN_MODEL_LABEL}</span>
		<select
			class="sel"
			class:off={modelOptions.length === 0}
			aria-label={`${task} ${MODELS_COLUMN_MODEL_LABEL.toLowerCase()}`}
			aria-describedby={modelsHint !== null ? modelsHintId : undefined}
			value={current.model}
			disabled={modelOptions.length === 0}
			onchange={(event) => chooseModel(event.currentTarget.value)}
		>
			{#if modelOptions.length === 0}
				<option value="">{MODELS_NO_MODELS_LABEL}</option>
			{:else}
				{#each modelOptions as model (model)}
					<option value={model}>{model}</option>
				{/each}
			{/if}
		</select>
		{#if modelsHint !== null}
			<small class="hint" id={modelsHintId}>{modelsHint}</small>
		{/if}
	</div>

	<div class="cell">
		<span class="k" aria-hidden="true">{MODELS_COLUMN_STATUS_LABEL}</span>
		<span class="st {status.shape}"><span class="mark">{status.mark}</span>{status.text}</span>
		<span class="saved" aria-live="polite">{saved ? `✓ ${MODELS_SAVED_LABEL}` : ''}</span>
	</div>
</div>

{#if advanced}
	<div class="tt-sub">
		<details class="adv">
			<summary>{MODELS_ADVANCED_LABEL}</summary>
			<div class="adv-body">{@render advanced()}</div>
		</details>
	</div>
{/if}

{#if failure !== null}
	<div class="tt-sub bad">
		<p class="row-error" role="alert">
			<span>{failure}</span>
			<button type="button" class="retry" onclick={() => persist(current)}
				>{MODELS_RETRY_LABEL}</button
			>
		</p>
	</div>
{/if}

<style>
	.tt-row {
		display: grid;
		grid-template-columns: 9rem 11rem 12.5rem 14rem minmax(0, 1fr);
		gap: 0.85rem;
		align-items: start;
		padding: 0.65rem 0.85rem;
		border-top: 1px solid var(--border);
		border-left: 3px solid transparent;
	}
	.tt-row.warn {
		border-left-color: var(--score-ok);
		background: color-mix(in srgb, var(--score-ok) 8%, transparent);
	}
	.tt-row.off {
		border-left-color: var(--border);
		background: color-mix(in srgb, var(--text-muted) 6%, transparent);
	}
	.tt-row.bad {
		border-left-color: var(--score-bad);
		background: color-mix(in srgb, var(--score-bad) 8%, transparent);
	}

	.cell {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 0.2rem;
		min-width: 0;
	}
	.cell-task {
		font-weight: 600;
		letter-spacing: 0.04em;
		padding-top: 0.3rem;
	}
	.k {
		display: none;
		font-size: 0.68rem;
		letter-spacing: 0.07em;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	.sel {
		width: 100%;
		padding: 0.34rem 0.45rem;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: var(--bg);
		color: var(--text);
		font-size: 0.8rem;
	}
	.sel.off {
		border-style: dashed;
		color: var(--text-muted);
	}

	.rsw {
		display: inline-flex;
		align-self: start;
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 0.13rem;
		background: var(--bg);
		font-size: 0.72rem;
		letter-spacing: 0.06em;
	}
	.rsw button {
		padding: 0.16rem 0.55rem;
		border: 1px solid transparent;
		border-radius: 999px;
		background: transparent;
		font-weight: 600;
		color: var(--text);
		cursor: pointer;
	}
	.rsw button:disabled {
		cursor: default;
	}
	.rsw button.on {
		background: var(--accent);
		color: var(--bg);
	}
	.rsw button.dead {
		color: var(--text-muted);
	}
	.rsw button.picked-dead {
		border: 1px dashed var(--score-ok);
		color: var(--score-ok);
	}

	.why,
	.hint {
		display: block;
		font-size: 0.68rem;
		line-height: 1.35;
		color: var(--text-muted);
	}
	.why.warn {
		color: var(--score-ok);
	}

	.st {
		display: flex;
		align-items: flex-start;
		gap: 0.42rem;
		font-size: 0.8rem;
		color: var(--text);
	}
	.st .mark {
		flex: 0 0 auto;
		width: 1.05rem;
		height: 1.05rem;
		border-radius: 50%;
		display: inline-grid;
		place-items: center;
		font-size: 0.66rem;
		font-weight: 700;
		line-height: 1;
		margin-top: 0.12rem;
	}
	.st.ok .mark {
		background: var(--score-good);
		color: var(--bg);
	}
	.st.ok {
		color: var(--score-good);
	}
	.st.warn .mark {
		background: var(--score-ok);
		color: var(--bg);
	}
	.st.off .mark {
		border: 1px solid var(--border);
		color: transparent;
	}
	.st.bad .mark {
		background: var(--score-bad);
		color: var(--bg);
	}
	.st.warn {
		color: var(--score-ok);
	}
	.st.off {
		color: var(--text-muted);
	}
	.st.bad {
		color: var(--score-bad);
	}

	.saved {
		display: inline-flex;
		gap: 0.3rem;
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--score-good);
	}

	.tt-sub {
		padding: 0 0.85rem 0.6rem 10.7rem;
		border-left: 3px solid transparent;
	}
	.tt-sub.bad {
		border-left-color: var(--score-bad);
		background: color-mix(in srgb, var(--score-bad) 8%, transparent);
	}

	.row-error {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex-wrap: wrap;
		margin: 0;
		font-size: 0.76rem;
		color: var(--score-bad);
	}
	.retry {
		text-transform: uppercase;
		letter-spacing: 0.07em;
		font-size: 0.72rem;
		font-weight: 600;
		padding: 0.18rem 0.7rem;
		border: 1px solid var(--score-bad);
		border-radius: 999px;
		background: transparent;
		color: var(--score-bad);
		cursor: pointer;
	}

	details.adv summary {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		cursor: pointer;
		list-style: none;
		text-transform: uppercase;
		letter-spacing: 0.09em;
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--accent);
	}
	details.adv summary::-webkit-details-marker {
		display: none;
	}
	details.adv summary::before {
		content: '›';
		font-size: 0.85rem;
	}
	details.adv[open] summary::before {
		content: '⌄';
	}
	.adv-body {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		margin-top: 0.45rem;
		flex-wrap: wrap;
	}

	@media (max-width: 768px) {
		.tt-row {
			grid-template-columns: minmax(0, 1fr);
			gap: 0.3rem;
			border: 1px solid var(--border);
			border-left-width: 3px;
			border-radius: 4px;
			margin-bottom: 0.6rem;
		}
		.cell {
			grid-template-columns: 4.4rem minmax(0, 1fr);
			align-items: start;
			gap: 0.55rem;
		}
		.cell .k {
			display: block;
			grid-row: 1;
			grid-column: 1;
			padding-top: 0.35rem;
		}
		.cell > :global(*:not(.k)) {
			grid-column: 2;
		}
		.cell-task {
			font-size: 0.95rem;
			text-transform: uppercase;
		}
		.tt-sub {
			padding-left: 0.85rem;
		}
	}
</style>
