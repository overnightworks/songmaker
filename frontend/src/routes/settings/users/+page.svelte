<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { afterNavigate } from '$app/navigation';
	import { derived } from 'svelte/store';
	import { fetchAdminVoices, ApiError, fetchRateLimits, updateRateLimits } from '$lib/api/client';
	import { describeFailure } from '$lib/api/fetch';
	import { reloadWhileUnreachable } from '$lib/stores/connectivity';
	import type { RateLimitItem, AdminUserLoraItem } from '$lib/api/types';
	import { isAdmin } from '$lib/stores/auth';
	import { loadBuiltins, builtinDefaults } from '$lib/stores/presets';
	import {
		fetchGenerationDefaults,
		updateGenerationDefaults,
		fetchAllModels,
		toggleModel as toggleModelApi,
		fetchCowriterSettings,
		updateCowriterSettings,
		fetchJudgeSettings,
		updateJudgeSettings,
		fetchCoverSettings,
		updateCoverSettings,
		fetchProviderStatus
	} from '$lib/api/client';
	import type { AvailableModel } from '$lib/api/client';
	import type {
		CoverSettingsResponse,
		CowriterSettings,
		JudgeSettings,
		ProviderRouteStatusResponse,
		ProviderStatus,
		SafeRouteReason
	} from '$lib/api/types';
	import type { VersionGenerationParams } from '$lib/api/types';
	import ParamControls from '$lib/components/ParamControls.svelte';
	import { ADMIN_TABS, parseAdminTab, type AdminTab } from '$lib/adminTabs';
	import WorkerPoolPanel from '$lib/components/WorkerPoolPanel.svelte';
	import ModelRegistryPanel from '$lib/components/ModelRegistryPanel.svelte';
	import TakeRetentionPanel from '$lib/components/TakeRetentionPanel.svelte';
	import ModelsTaskRow, {
		MODELS_ROUTE_NOT_AVAILABLE_CODE,
		routeReasonSentence
	} from '$lib/components/ModelsTaskRow.svelte';
	import ModelsCowriterRow from '$lib/components/ModelsCowriterRow.svelte';
	import type {
		ModelsRouteKey,
		ModelsRouteReason,
		ModelsSaveOutcome,
		ModelsTaskProvider,
		ModelsTaskRoute,
		ModelsTaskSelection
	} from '$lib/components/ModelsTaskRow.svelte';
	import {
		ADMIN_TABS_LABEL,
		ADMIN_VOICES_EMPTY,
		ADMIN_VOICES_HEADING,
		VOICES_LOAD_FAILED,
		ADMIN_VOICES_LOADING,
		ADMIN_VOICES_NAME_LABEL,
		ADMIN_VOICES_OWNER_LABEL,
		ADMIN_VOICES_STATUS_LABEL,
		MODELS_COLUMN_MODEL_LABEL,
		MODELS_COLUMN_PROVIDER_LABEL,
		MODELS_COLUMN_ROUTE_LABEL,
		MODELS_COLUMN_STATUS_LABEL,
		MODELS_COLUMN_TASK_LABEL,
		MODELS_HEADING,
		MODELS_HISTORY_TAIL_LABEL,
		MODELS_RETRY_LABEL,
		MODELS_LOADING_LABEL,
		MODELS_SAVED_LABEL,
		MODELS_SAVE_FAILED_FALLBACK,
		MODELS_TASK_COVER_LABEL,
		MODELS_TASK_COWRITER_LABEL,
		MODELS_TASK_SCORING_LABEL,
		modelsRouteNotAvailablePhrase,
		PROVIDER_STATUS_UNAVAILABLE_DETAIL
	} from '$lib/constants';
	import {
		COMPACT_SELECT_CLASS,
		COMPACT_STACK_CLASS,
		ensureCompactUiStyles
	} from '$lib/styles/compact-ui';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';
	import { providerDisplayName } from '$lib/utils/cowriter-ui';

	let voices = $state<AdminUserLoraItem[]>([]);
	let loadingVoices = $state(false);
	let voicesLoaded = $state(false);
	let error = $state('');
	let compact = $state(false);

	let tab = $state<AdminTab>('voices');
	let tabVisit = 0;

	function pageErrorReporter(): (message: string) => void {
		const origin = tab;
		const visit = tabVisit;
		return (message) => {
			if (tab === origin && tabVisit === visit) error = message;
		};
	}

	$effect(() => {
		ensureCompactUiStyles();
		return subscribeCompactLayout((value) => (compact = value));
	});

	function selectTab(next: AdminTab): void {
		if (tab !== next) tabVisit += 1;
		tab = next;
		error = '';
		if (next === 'ratelimits') {
			void loadGlobalLimits();
		} else if (next === 'voices') {
			void loadVoices();
		} else if (next === 'generation' || next === 'acestep') {
			void loadGenDefaults();
		} else if (next === 'models') {
			void loadModelsTab();
		}
	}

	function onTabChange(event: Event): void {
		const next = parseAdminTab((event.currentTarget as HTMLSelectElement).value);
		if (next === null) return;
		selectTab(next);
	}

	let globalLimits = $state<RateLimitItem[]>([]);
	let globalEdits = $state<Record<string, string>>({});
	let savingGlobal = $state(false);

	const SETTING_LABELS: Record<string, string> = {
		generation_rate_limit: 'Generations / hour',
		scoring_rate_limit: 'Scorings / hour',
		chat_rate_limit: 'Chat messages / hour',
		max_queue_depth: 'Max queue depth',
		max_user_active_jobs: 'Max active jobs'
	};

	let providerStatuses = $state<ProviderStatus[]>([]);

	// The co-writer runs through the agent service; its row offers no choice until the Models row replaces it.
	let cowriterSettings = $state<CowriterSettings | null>(null);
	let cowriterBudget = $state(0);
	let cowriterBudgetSaved = $state(false);
	let cowriterBudgetFailure = $state<string | null>(null);
	let coverSettings = $state<CoverSettingsResponse | null>(null);
	let judgeSettings = $state<JudgeSettings | null>(null);

	let registryModes = $state<string[]>([]);

	let allModels = $state<AvailableModel[]>([]);
	let genDefaults = $state<Record<string, VersionGenerationParams>>({});
	let genDefaultsLoaded = $state(false);
	let genEditModel = $state('');
	let genEditDefaults = $state<VersionGenerationParams>({});
	let genSaving = $state(false);
	const genModelModes = $derived(Object.keys($builtinDefaults));

	const admin = $derived($isAdmin);

	// Each read the page makes (#1107): a lost network shows no words of its
	// own while the offline strip says it or a reload is coming, and the read
	// runs again by itself; any other failure shows the server's reason.
	const ADMIN_LOADS = [
		'voices',
		'rateLimits',
		'providerStatus',
		'cowriter',
		'cover',
		'scoring',
		'genDefaults'
	] as const;
	type AdminLoad = (typeof ADMIN_LOADS)[number];

	const LOAD_FAILURE_FALLBACKS: Record<AdminLoad, string> = {
		voices: VOICES_LOAD_FAILED,
		rateLimits: 'Failed to load rate limits',
		providerStatus: PROVIDER_STATUS_UNAVAILABLE_DETAIL,
		cowriter: 'Failed to load co-writer settings',
		cover: 'Failed to load cover settings',
		scoring: 'Failed to load scoring settings',
		genDefaults: 'Failed to load generation defaults'
	};
	const PAGE_WIDE_LOADS = {
		rateLimits: ['ratelimits'],
		cowriter: ['models'],
		cover: ['models'],
		scoring: ['models']
	} satisfies Partial<Record<AdminLoad, AdminTab[]>>;

	const loadReloads: Record<AdminLoad, ReturnType<typeof reloadWhileUnreachable>> = {
		voices: reloadWhileUnreachable(() => void loadVoices()),
		rateLimits: reloadWhileUnreachable(() => void loadGlobalLimits()),
		providerStatus: reloadWhileUnreachable(() => void loadProviderStatuses()),
		cowriter: reloadWhileUnreachable(() => void loadCowriterSettings()),
		cover: reloadWhileUnreachable(() => void loadCoverSettings()),
		scoring: reloadWhileUnreachable(() => void loadJudgeSettings()),
		genDefaults: reloadWhileUnreachable(() => void loadGenDefaults())
	};
	const loadFailures = derived(
		ADMIN_LOADS.map((load) => loadReloads[load].loadFailure),
		(failures) =>
			Object.fromEntries(ADMIN_LOADS.map((load, index) => [load, failures[index]])) as Record<
				AdminLoad,
				string | null
			>
	);
	const pageLoadFailures = $derived([
		...new Set(
			(Object.keys(PAGE_WIDE_LOADS) as (keyof typeof PAGE_WIDE_LOADS)[]).flatMap((load) =>
				(PAGE_WIDE_LOADS[load] as readonly AdminTab[]).includes(tab)
					? ($loadFailures[load] ?? [])
					: []
			)
		)
	]);

	function settleLoad(load: AdminLoad): void {
		loadReloads[load].stop();
	}

	function failLoad(load: AdminLoad, e: unknown): void {
		loadReloads[load].nameLoadFailure(e, LOAD_FAILURE_FALLBACKS[load]);
	}

	function selectRequestedTab(url: URL): void {
		selectTab(parseAdminTab(url.searchParams.get('tab') ?? '') ?? 'voices');
	}

	onMount(() => {
		selectRequestedTab(new URL(window.location.href));
	});
	afterNavigate(({ from, to }) => {
		if (to && from?.url.pathname === to.url.pathname) selectRequestedTab(to.url);
	});
	onDestroy(() => {
		for (const reloads of Object.values(loadReloads)) reloads.stop();
	});

	async function loadVoices() {
		loadingVoices = true;
		try {
			voices = await fetchAdminVoices();
			voicesLoaded = true;
			settleLoad('voices');
		} catch (e) {
			failLoad('voices', e);
		} finally {
			loadingVoices = false;
		}
	}

	async function loadGlobalLimits() {
		try {
			const res = await fetchRateLimits();
			globalLimits = res.settings;
			globalEdits = Object.fromEntries(res.settings.map((s) => [s.setting_key, String(s.value)]));
			settleLoad('rateLimits');
		} catch (e) {
			failLoad('rateLimits', e);
		}
	}

	async function handleSaveGlobal() {
		const reportError = pageErrorReporter();
		savingGlobal = true;
		reportError('');
		try {
			const settings: Record<string, number> = {};
			for (const [key, val] of Object.entries(globalEdits)) {
				settings[key] = parseInt(val, 10);
			}
			const res = await updateRateLimits(settings);
			globalLimits = res.settings;
			globalEdits = Object.fromEntries(res.settings.map((s) => [s.setting_key, String(s.value)]));
		} catch (e) {
			reportError(describeFailure(e, 'Failed to save'));
		} finally {
			savingGlobal = false;
		}
	}

	function providerStatusFor(provider: string): ProviderStatus | undefined {
		return providerStatuses.find((status) => status.provider === provider);
	}

	function isNonEmptyString(value: unknown): value is string {
		return typeof value === 'string' && value.length > 0;
	}

	const FALLBACK_ROUTE: ModelsRouteKey = 'cli';

	function loadModelsTab(): void {
		void loadProviderStatuses();
		void loadCowriterSettings();
		void loadCoverSettings();
		void loadJudgeSettings();
	}

	async function loadProviderStatuses(): Promise<void> {
		try {
			providerStatuses = await fetchProviderStatus();
			settleLoad('providerStatus');
		} catch (e) {
			providerStatuses = [];
			failLoad('providerStatus', e);
		}
	}

	async function loadCowriterSettings(): Promise<void> {
		try {
			cowriterSettings = await fetchCowriterSettings();
			cowriterBudget = cowriterSettings.tail_token_budget;
			settleLoad('cowriter');
		} catch (e) {
			failLoad('cowriter', e);
		}
	}

	async function loadCoverSettings(): Promise<void> {
		try {
			coverSettings = await fetchCoverSettings();
			settleLoad('cover');
		} catch (e) {
			failLoad('cover', e);
		}
	}

	async function loadJudgeSettings(): Promise<void> {
		try {
			judgeSettings = await fetchJudgeSettings();
			settleLoad('scoring');
		} catch (e) {
			failLoad('scoring', e);
		}
	}

	const providerStatusError = $derived($loadFailures.providerStatus ?? '');
	const providerStatusFailure = $derived<SafeRouteReason | null>(
		providerStatusError === '' ? null : { code: 'route_failed', message: providerStatusError }
	);

	function catalogueOf(
		provider: string,
		route: ModelsRouteKey
	): ProviderRouteStatusResponse | undefined {
		return providerStatusFor(provider)?.cowriter_routes?.[route];
	}

	function taskRoute(
		provider: string,
		route: ModelsRouteKey,
		ready: boolean,
		reason: SafeRouteReason | null,
		models?: string[]
	): ModelsTaskRoute {
		if (providerStatusFailure) {
			return {
				ready: false,
				reason: providerStatusFailure,
				models: [],
				modelsReason: providerStatusError
			};
		}
		const catalogue = catalogueOf(provider, route);
		return {
			ready,
			reason,
			models: models ?? catalogue?.models ?? [],
			modelsReason: catalogue?.catalogue_failure?.message ?? null
		};
	}

	function transportRoute(provider: string, route: ModelsRouteKey): ModelsTaskRoute {
		const readiness = catalogueOf(provider, route)?.readiness;
		return taskRoute(
			provider,
			route,
			readiness?.state === 'ready',
			readiness && readiness.state !== 'unverified' ? (readiness.reason ?? null) : null
		);
	}

	function coverRoute(provider: string, route: ModelsRouteKey): ModelsTaskRoute {
		const readiness = providerStatusFor(provider)?.cover_routes?.[route];
		const canDraw = readiness?.state === 'ready';
		return taskRoute(
			provider,
			route,
			canDraw,
			readiness && readiness.state !== 'unverified' ? (readiness.reason ?? null) : null,
			canDraw ? undefined : []
		);
	}

	function scoringRoute(provider: string, route: ModelsRouteKey): ModelsTaskRoute {
		if (route !== scoringSavedRoute) {
			return {
				ready: false,
				reason: {
					code: MODELS_ROUTE_NOT_AVAILABLE_CODE,
					message: modelsRouteNotAvailablePhrase(MODELS_TASK_SCORING_LABEL)
				},
				models: []
			};
		}
		return transportRoute(provider, route);
	}

	function taskProviders(
		routeOf: (provider: string, route: ModelsRouteKey) => ModelsTaskRoute,
		names: string[]
	): ModelsTaskProvider[] {
		return names.map((provider) => ({
			provider,
			label: providerDisplayName(provider),
			routes: { cli: routeOf(provider, 'cli'), api: routeOf(provider, 'api') }
		}));
	}

	const coverProviders = $derived(
		taskProviders(coverRoute, judgeSettings?.allowed_providers ?? [])
	);
	const coverSelection = $derived<ModelsTaskSelection>({
		provider: coverSettings?.provider ?? '',
		route: coverSettings?.route ?? FALLBACK_ROUTE,
		model: coverSettings?.model ?? ''
	});
	const scoringSavedRoute = $derived(judgeSettings?.route ?? FALLBACK_ROUTE);
	const scoringProviders = $derived(
		taskProviders(scoringRoute, judgeSettings?.allowed_providers ?? [])
	);
	const scoringSelection = $derived<ModelsTaskSelection>({
		provider: judgeSettings?.provider ?? '',
		route: scoringSavedRoute,
		model: judgeSettings?.model ?? ''
	});

	function isRouteReason(detail: unknown): detail is ModelsRouteReason {
		if (typeof detail !== 'object' || detail === null) return false;
		const candidate = detail as Partial<ModelsRouteReason>;
		return isNonEmptyString(candidate.code) && isNonEmptyString(candidate.message);
	}

	/**
	 * Every rejected save reaches the row as a sentence: a route reason through
	 * the row's own phrasing, a plain string verbatim. The generic API message
	 * never stands in for a reason.
	 */
	function saveFailureReason(e: unknown, task: string, route: ModelsRouteKey): string {
		if (e instanceof ApiError) {
			if (isRouteReason(e.responseDetail)) {
				return routeReasonSentence(e.responseDetail, route, task);
			}
			return isNonEmptyString(e.responseDetail) ? e.responseDetail : MODELS_SAVE_FAILED_FALLBACK;
		}
		return describeFailure(e, MODELS_SAVE_FAILED_FALLBACK);
	}

	async function saveCover(selection: ModelsTaskSelection): Promise<ModelsSaveOutcome> {
		try {
			coverSettings = await updateCoverSettings(
				selection.provider,
				selection.route,
				selection.model
			);
			return { ok: true };
		} catch (e) {
			return { ok: false, reason: saveFailureReason(e, MODELS_TASK_COVER_LABEL, selection.route) };
		}
	}

	async function saveScoring(selection: ModelsTaskSelection): Promise<ModelsSaveOutcome> {
		try {
			judgeSettings = await updateJudgeSettings(
				selection.provider,
				selection.route,
				selection.model
			);
			return { ok: true };
		} catch (e) {
			return {
				ok: false,
				reason: saveFailureReason(e, MODELS_TASK_SCORING_LABEL, selection.route)
			};
		}
	}

	async function saveCowriterBudget(budget: number): Promise<void> {
		cowriterBudgetSaved = false;
		cowriterBudgetFailure = null;
		cowriterBudget = budget;
		try {
			cowriterSettings = await updateCowriterSettings(budget);
			cowriterBudget = cowriterSettings.tail_token_budget;
			cowriterBudgetSaved = true;
		} catch (e) {
			cowriterBudgetFailure = saveFailureReason(e, MODELS_TASK_COWRITER_LABEL, FALLBACK_ROUTE);
		}
	}

	async function loadGenDefaults() {
		await loadBuiltins();
		try {
			allModels = await fetchAllModels();
		} catch {
			allModels = [];
		}
		const wasLoaded = genDefaultsLoaded;
		try {
			genDefaults = await fetchGenerationDefaults();
			genDefaultsLoaded = true;
			settleLoad('genDefaults');
			const modes = Object.keys($builtinDefaults);
			if (!wasLoaded && modes.length > 0) {
				genEditModel ||= modes[0];
				genEditDefaults = { ...(genDefaults[genEditModel] ?? {}) };
			}
		} catch (e) {
			genDefaultsLoaded = false;
			failLoad('genDefaults', e);
		}
	}

	async function handleToggleModel(modelId: string, currentActive: boolean): Promise<void> {
		const reportError = pageErrorReporter();
		try {
			const updated = await toggleModelApi(modelId, !currentActive);
			allModels = allModels.map((m) => (m.id === updated.id ? updated : m));
		} catch {
			reportError('Failed to toggle model');
		}
	}

	function switchGenModel(model: string): void {
		if (!genDefaultsLoaded) return;
		genEditModel = model;
		genEditDefaults = { ...(genDefaults[model] ?? {}) };
	}

	async function handleSaveGenDefaults(): Promise<void> {
		if (!genDefaultsLoaded) return;
		const reportError = pageErrorReporter();
		genSaving = true;
		reportError('');
		try {
			const cleaned = Object.keys(genEditDefaults).length > 0 ? genEditDefaults : {};
			genDefaults = await updateGenerationDefaults({ ...genDefaults, [genEditModel]: cleaned });
			genDefaultsLoaded = true;
			settleLoad('genDefaults');
			genEditDefaults = { ...(genDefaults[genEditModel] ?? {}) };
		} catch {
			reportError('Failed to save generation defaults');
		} finally {
			genSaving = false;
		}
	}

	function handleResetGenDefaults(): void {
		genEditDefaults = { ...(genDefaults[genEditModel] ?? {}) };
	}
</script>

{#if !admin}
	<div class="denied">Admin access required.</div>
{:else}
	<div class="settings-page">
		<h1>Admin</h1>

		{#if compact}
			<select
				class="tab-select {COMPACT_SELECT_CLASS}"
				aria-label={ADMIN_TABS_LABEL}
				value={tab}
				onchange={onTabChange}
			>
				{#each ADMIN_TABS as item (item.id)}
					<option value={item.id}>{item.label}</option>
				{/each}
			</select>
		{:else}
			<div class="tabs">
				{#each ADMIN_TABS as item (item.id)}
					<button class:active={tab === item.id} onclick={() => selectTab(item.id)}>
						{item.label}
					</button>
				{/each}
			</div>
		{/if}

		{#if error}
			<p class="error">{error}</p>
		{/if}
		{#each pageLoadFailures as failure (failure)}
			<p class="error">{failure}</p>
		{/each}

		{#if tab === 'voices'}
			<section>
				<h2>{ADMIN_VOICES_HEADING}</h2>
				{#if loadingVoices}
					<p class="text-muted">{ADMIN_VOICES_LOADING}</p>
				{:else if $loadFailures.voices}
					<p class="error">{$loadFailures.voices}</p>
				{:else if voicesLoaded && voices.length === 0}
					<p class="text-muted">{ADMIN_VOICES_EMPTY}</p>
				{:else if voices.length > 0}
					<table class="stack-table {compact ? COMPACT_STACK_CLASS : ''}">
						<thead>
							<tr>
								<th>{ADMIN_VOICES_NAME_LABEL}</th>
								<th>{ADMIN_VOICES_OWNER_LABEL}</th>
								<th>{ADMIN_VOICES_STATUS_LABEL}</th>
							</tr>
						</thead>
						<tbody>
							{#each voices as voice (voice.id)}
								<tr>
									<td data-label={ADMIN_VOICES_NAME_LABEL}>{voice.name}</td>
									<td data-label={ADMIN_VOICES_OWNER_LABEL}>{voice.owner_username}</td>
									<td data-label={ADMIN_VOICES_STATUS_LABEL}>
										<span
											class="badge voice-status"
											class:voice-status-ready={voice.status === 'ready'}
											class:voice-status-active={[
												'queued',
												'preprocessing',
												'training',
												'exporting'
											].includes(voice.status)}
											class:voice-status-failed={voice.status === 'failed'}
										>
											{voice.status}
										</span>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</section>
		{/if}

		{#if tab === 'ratelimits'}
			<section>
				<h2>Global Defaults</h2>
				<p class="hint">These apply to all users.</p>
				<div class="limits-grid">
					{#each globalLimits as item (item.setting_key)}
						<label class="limit-row">
							<span class="limit-label">{SETTING_LABELS[item.setting_key] ?? item.setting_key}</span
							>
							<input
								type="number"
								min="0"
								bind:value={globalEdits[item.setting_key]}
								class="limit-input"
							/>
						</label>
					{/each}
				</div>
				{#if globalLimits.length > 0}
					<button class="save-btn" onclick={handleSaveGlobal} disabled={savingGlobal}>
						{savingGlobal ? 'Saving...' : 'Save Defaults'}
					</button>
				{/if}
			</section>
		{/if}

		{#if tab === 'generation'}
			<section>
				<h2>Generation Defaults</h2>
				<p class="hint">
					Default generation parameters for all users. Per-song overrides take precedence.
				</p>

				{#if $loadFailures.genDefaults}
					<p class="error">{$loadFailures.genDefaults}</p>
				{/if}

				{#if genDefaultsLoaded}
					<div class="gen-model-tabs">
						{#each genModelModes as mode (mode)}
							<button
								class="gen-model-tab"
								class:active={genEditModel === mode}
								onclick={() => switchGenModel(mode)}
							>
								{mode.toUpperCase()}
							</button>
						{/each}
					</div>

					<div class="gen-defaults-controls">
						<ParamControls
							values={genEditDefaults}
							placeholders={($builtinDefaults[genEditModel] ??
								{}) as Required<VersionGenerationParams>}
							onchange={(p) => (genEditDefaults = p)}
						/>
					</div>

					<div class="gen-actions-row">
						<button
							class="save-btn"
							onclick={handleSaveGenDefaults}
							disabled={genSaving || !genDefaultsLoaded}
						>
							{genSaving ? 'Saving...' : 'Save Defaults'}
						</button>
						<button class="clear-btn" onclick={handleResetGenDefaults}>Reset</button>
					</div>
				{/if}
			</section>
		{/if}

		{#if tab === 'models'}
			<section class="models-table-frame">
				<h2>{MODELS_HEADING}</h2>
				<div class="tt">
					<div class="tt-head">
						<span>{MODELS_COLUMN_TASK_LABEL}</span>
						<span>{MODELS_COLUMN_PROVIDER_LABEL}</span>
						<span>{MODELS_COLUMN_ROUTE_LABEL}</span>
						<span>{MODELS_COLUMN_MODEL_LABEL}</span>
						<span>{MODELS_COLUMN_STATUS_LABEL}</span>
					</div>
					{#if cowriterSettings}
						<ModelsCowriterRow advanced={cowriterAdvanced} />
					{:else}
						<p class="hint">{MODELS_LOADING_LABEL}</p>
					{/if}
					{#if coverSettings && judgeSettings}
						<ModelsTaskRow
							task={MODELS_TASK_COVER_LABEL}
							providers={coverProviders}
							selection={coverSelection}
							save={saveCover}
						/>
					{:else}
						<p class="hint">{MODELS_LOADING_LABEL}</p>
					{/if}
					{#if judgeSettings}
						<ModelsTaskRow
							task={MODELS_TASK_SCORING_LABEL}
							providers={scoringProviders}
							selection={scoringSelection}
							save={saveScoring}
						/>
					{:else}
						<p class="hint">{MODELS_LOADING_LABEL}</p>
					{/if}
				</div>
			</section>
		{/if}

		{#if tab === 'acestep'}
			<WorkerPoolPanel availableModes={registryModes} />
			<ModelRegistryPanel onModesChange={(modes) => (registryModes = modes)} />

			<section>
				<h2>Available Models</h2>
				<p class="hint">Toggle which models users can create presets for.</p>
				<div class="model-toggles">
					{#each allModels as model (model.id)}
						<button
							class="model-toggle"
							class:active={model.is_active}
							onclick={() => handleToggleModel(model.id, model.is_active)}
						>
							{model.id.toUpperCase()}
							<span class="model-status">{model.is_active ? 'ON' : 'OFF'}</span>
						</button>
					{/each}
				</div>
			</section>
		{/if}

		{#if tab === 'cleanup'}
			<TakeRetentionPanel />
		{/if}
	</div>
{/if}

{#snippet cowriterAdvanced()}
	<label class="field-label" for="cowriter-budget">{MODELS_HISTORY_TAIL_LABEL}</label>
	<input
		id="cowriter-budget"
		type="number"
		min="2000"
		max="100000"
		value={cowriterBudget}
		onchange={(event) => saveCowriterBudget(Number(event.currentTarget.value))}
	/>
	<span class="saved" aria-live="polite"
		>{cowriterBudgetSaved ? `✓ ${MODELS_SAVED_LABEL}` : ''}</span
	>
	{#if cowriterBudgetFailure !== null}
		<span class="budget-error" role="alert">{cowriterBudgetFailure}</span>
		<button type="button" class="retry" onclick={() => saveCowriterBudget(cowriterBudget)}
			>{MODELS_RETRY_LABEL}</button
		>
	{/if}
{/snippet}

<style>
	/* The head lives here and the rows live in ModelsTaskRow, so the column
	   geometry is published once as tokens rather than kept in step by hand.
	   Every track may shrink below its width: how much room the table has is
	   decided by the card it sits in, not by the viewport — a docked panel or
	   an open rail takes hundreds of pixels the viewport still counts (#846) —
	   so the widths below are what a column takes when the room is there. Only
	   Status keeps a floor, because a status nobody can read is the one thing
	   this table exists to show. */
	.models-table-frame {
		container-type: inline-size;
		container-name: models-table;
	}

	.tt {
		--models-columns: minmax(0, 9rem) minmax(0, 11rem) minmax(0, 12.5rem) minmax(0, 14rem)
			minmax(9rem, 1fr);
		--models-gap: 0.85rem;
		--models-sub-indent: 10.7rem;
		border: 1px solid var(--border);
		border-radius: 4px;
		overflow: hidden;
	}

	/* The picture steps the columns down at 1180px of its own full-bleed
	   canvas; here the same step belongs where the wide columns stop fitting
	   the card — 46.5rem of columns, four gaps, the padding and the Status
	   floor. */
	@container models-table (max-width: 960px) {
		.tt {
			--models-columns: minmax(0, 7.5rem) minmax(0, 9rem) minmax(0, 10.5rem) minmax(0, 11rem)
				minmax(8rem, 1fr);
			--models-gap: 0.6rem;
			--models-sub-indent: 8.6rem;
			font-size: 0.95em;
		}
	}

	.tt-head {
		display: grid;
		grid-template-columns: var(--models-columns);
		gap: var(--models-gap);
		padding: 0.45rem 0.85rem;
		border-left: 3px solid transparent;
		background: var(--surface);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.09em;
		font-size: 0.72rem;
		color: var(--text-muted);
	}

	.field-label {
		text-transform: uppercase;
		letter-spacing: 0.06em;
		font-size: 0.72rem;
		color: var(--text-muted);
	}

	.saved {
		font-size: 0.72rem;
		font-weight: 600;
		color: var(--score-good);
	}

	.budget-error {
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

	@media (max-width: 768px) {
		.tt {
			border: 0;
		}
		.tt-head {
			display: none;
		}
	}
	.denied {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--text-muted);
		font-size: 1.1rem;
	}

	h1 {
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.1em;
		background: linear-gradient(90deg, var(--primary), var(--accent));
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
		font-size: 1.5rem;
		margin-bottom: 1.5rem;
	}

	.tabs {
		display: flex;
		gap: 0;
		margin-bottom: 1.5rem;
		border-bottom: 1px solid var(--border);
	}

	.tabs button {
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		color: var(--text-muted);
		padding: 0.5rem 1rem;
		cursor: pointer;
		font-family: var(--font-display);
		font-size: 0.9rem;
		text-transform: uppercase;
		letter-spacing: var(--btn-letter-spacing);
	}

	.tabs button.active {
		color: var(--primary);
		border-bottom: 2px solid transparent;
		border-image: linear-gradient(90deg, var(--primary), var(--accent)) 1;
	}

	.tab-select {
		margin-bottom: 1.5rem;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: var(--input-radius);
		color: var(--text);
		padding: var(--input-padding);
		font-size: 0.9rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: var(--btn-letter-spacing);
	}

	.error {
		color: var(--score-bad);
		font-size: 0.85rem;
		margin-bottom: 1rem;
	}

	h2 {
		font-size: 1rem;
		color: var(--text-muted);
		margin-bottom: 0.8rem;
		margin-top: 1.5rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.85rem;
	}

	th {
		text-align: left;
		color: var(--text-muted);
		font-weight: 600;
		padding: 0.5rem;
		border-bottom: 1px solid var(--border);
	}

	td {
		padding: 0.5rem;
		border-bottom: 1px solid var(--border);
	}

	.badge {
		display: inline-block;
		padding: 0.1rem 0.4rem;
		border-radius: 3px;
		font-size: 0.75rem;
		background: var(--surface-hover);
	}

	.voice-status {
		font-weight: 600;
	}

	.voice-status-ready {
		background: var(--score-good);
		color: var(--bg);
	}

	.voice-status-active {
		background: var(--score-warn);
		color: var(--bg);
	}

	.voice-status-failed {
		background: var(--score-bad);
		color: white;
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.3rem;
	}

	.text-muted {
		color: var(--text-muted);
		font-size: 0.8rem;
	}

	.fail {
		color: var(--score-bad);
	}

	.hint {
		color: var(--text-subtle);
		font-size: 0.75rem;
		margin-top: 0.5rem;
	}

	.limits-grid {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		margin: 0.75rem 0;
	}

	.limit-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 1rem;
	}

	.limit-label {
		flex: 1;
		font-size: 0.85rem;
		color: var(--text);
	}

	.limit-input {
		width: 80px;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: var(--input-radius);
		color: var(--text);
		padding: 0.35rem 0.5rem;
		font-size: 0.85rem;
		font-family: var(--font-body);
		text-align: right;
	}

	.limit-input::placeholder {
		color: var(--text-subtle);
	}

	.save-btn {
		display: inline-block;
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: var(--on-accent);
		border: none;
		border-radius: var(--btn-radius-pill);
		padding: 0.4rem 1rem;
		font-size: 0.8rem;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: var(--btn-letter-spacing);
		margin-top: 0.5rem;
	}

	.save-btn:hover:not(.disabled):not(:disabled) {
		box-shadow: 0 0 16px color-mix(in srgb, var(--accent) 30%, transparent);
	}

	.save-btn.disabled,
	.save-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.clear-btn {
		background: transparent;
		color: var(--text-muted);
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-pill);
		padding: var(--btn-padding-pill);
		font-size: var(--btn-font-size);
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: var(--btn-letter-spacing);
	}

	.clear-btn:hover {
		border-color: var(--text-muted);
		color: var(--text);
	}

	.gen-model-tabs {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-bottom: 1rem;
	}

	.gen-model-tab {
		padding: 0.5rem 1.4rem;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: transparent;
		color: var(--text-muted);
		font-size: var(--btn-font-size);
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: var(--btn-letter-spacing);
	}

	.gen-model-tab:hover:not(.active) {
		border-color: var(--primary);
		color: var(--primary);
	}

	.gen-model-tab.active {
		border-color: transparent;
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: var(--on-accent);
	}

	.gen-defaults-controls {
		margin-bottom: 1rem;
	}

	.gen-actions-row {
		display: flex;
		flex-wrap: wrap;
		gap: 0.75rem;
		align-items: center;
	}

	.model-toggles {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}

	.model-toggle {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 0.5rem 1.4rem;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: transparent;
		color: var(--text-muted);
		font-size: var(--btn-font-size);
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: var(--btn-letter-spacing);
	}

	.model-toggle.active {
		border-color: transparent;
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: var(--on-accent);
	}

	.model-toggle:hover:not(.active) {
		border-color: var(--primary);
		color: var(--primary);
	}

	.model-status {
		font-size: 0.7rem;
		opacity: 0.7;
	}
</style>
