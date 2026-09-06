<script lang="ts">
	import { onMount } from 'svelte';
	import {
		fetchUsers,
		fetchAdminVoices,
		ApiError,
		createUser,
		updateUser,
		hardDeleteUser,
		fetchSessions,
		forceLogout,
		fetchLoginAttempts,
		fetchRateLimits,
		updateRateLimits,
		fetchUserRateLimits,
		updateUserRateLimits,
		deleteUserRateLimits
	} from '$lib/api/client';
	import type {
		UserItem,
		SessionItem,
		LoginAttemptItem,
		RateLimitItem,
		UserRateLimitsResponse,
		AdminUserLoraItem
	} from '$lib/api/types';
	import { currentUser, isAdmin } from '$lib/stores/auth';
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
		ProviderSurfaceStatus,
		SafeRouteReason
	} from '$lib/api/types';
	import type { VersionGenerationParams } from '$lib/api/types';
	import ParamControls from '$lib/components/ParamControls.svelte';
	import WorkerPoolPanel from '$lib/components/WorkerPoolPanel.svelte';
	import ModelRegistryPanel from '$lib/components/ModelRegistryPanel.svelte';
	import ModelsTaskRow, {
		MODELS_ROUTES,
		MODELS_ROUTE_NOT_AVAILABLE_CODE,
		routeReasonSentence
	} from '$lib/components/ModelsTaskRow.svelte';
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
		ADMIN_VOICES_LOAD_FAILED,
		ADMIN_VOICES_LOADING,
		ADMIN_VOICES_NAME_LABEL,
		ADMIN_VOICES_OWNER_LABEL,
		ADMIN_VOICES_STATUS_LABEL,
		ADMIN_VOICES_TAB_LABEL,
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
		PROVIDER_API_KEY_NEEDS_CLI_LOGIN_DETAIL,
		PROVIDER_CLI_LOGIN_LABELS,
		PROVIDER_STATUS_UNAVAILABLE_DETAIL,
		PROVIDER_UNVERIFIED_DETAIL,
		providerCliLoginNeedsApiKeyDetail,
		providerConfiguredDetail,
		providerMissingDependencyDetail,
		providerMissingRequirementDetail
	} from '$lib/constants';
	import {
		COMPACT_SELECT_CLASS,
		COMPACT_STACK_CLASS,
		ensureCompactUiStyles
	} from '$lib/styles/compact-ui';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';

	let users = $state<UserItem[]>([]);
	let sessions = $state<SessionItem[]>([]);
	let attempts = $state<LoginAttemptItem[]>([]);
	let voices = $state<AdminUserLoraItem[]>([]);
	let loadingVoices = $state(false);
	let voicesLoadError = $state('');
	let error = $state('');
	let compact = $state(false);

	const ADMIN_TABS = [
		{ id: 'users', label: 'Users' },
		{ id: 'voices', label: ADMIN_VOICES_TAB_LABEL },
		{ id: 'sessions', label: 'Sessions' },
		{ id: 'attempts', label: 'Login Attempts' },
		{ id: 'ratelimits', label: 'Rate Limits' },
		{ id: 'generation', label: 'Generation' },
		{ id: 'models', label: 'Models' },
		{ id: 'acestep', label: 'ACE-Step' }
	] as const;

	type AdminTab = (typeof ADMIN_TABS)[number]['id'];

	let tab = $state<AdminTab>('users');

	$effect(() => {
		ensureCompactUiStyles();
		return subscribeCompactLayout((value) => (compact = value));
	});

	function parseAdminTab(value: string): AdminTab | null {
		for (const item of ADMIN_TABS) {
			if (item.id === value) return item.id;
		}
		return null;
	}

	function selectTab(next: AdminTab): void {
		tab = next;
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

	let expandedUserId = $state<string | null>(null);
	let userLimitsData = $state<UserRateLimitsResponse | null>(null);
	let userEdits = $state<Record<string, string>>({});
	let savingUser = $state(false);

	const SETTING_LABELS: Record<string, string> = {
		generation_rate_limit: 'Generations / hour',
		scoring_rate_limit: 'Scorings / hour',
		chat_rate_limit: 'Chat messages / hour',
		max_queue_depth: 'Max queue depth',
		max_user_active_jobs: 'Max active jobs'
	};

	let newUsername = $state('');
	let newPassword = $state('');
	let newRole = $state('user');
	let creating = $state(false);

	let providerStatuses = $state<ProviderStatus[]>([]);
	let providerStatusError = $state('');

	let cowriterSettings = $state<CowriterSettings | null>(null);
	let cowriterBudget = $state(0);
	let cowriterBudgetSaved = $state(false);
	let cowriterBudgetFailure = $state<string | null>(null);
	let coverSettings = $state<CoverSettingsResponse | null>(null);
	let judgeSettings = $state<JudgeSettings | null>(null);

	let resetPasswordUserId = $state<string | null>(null);
	let resetPasswordValue = $state('');
	let resettingPassword = $state(false);

	let deleteUserId = $state<string | null>(null);
	let deleteConfirmInput = $state('');
	let deleting = $state(false);

	let registryModes = $state<string[]>([]);

	let allModels = $state<AvailableModel[]>([]);
	let genDefaults = $state<Record<string, VersionGenerationParams>>({});
	let genEditModel = $state('');
	let genEditDefaults = $state<VersionGenerationParams>({});
	let genSaving = $state(false);
	const genModelModes = $derived(Object.keys($builtinDefaults));

	const admin = $derived($isAdmin);
	const me = $derived($currentUser);

	onMount(loadAll);

	async function loadAll() {
		try {
			const [u, s, a] = await Promise.all([
				fetchUsers(),
				fetchSessions(),
				fetchLoginAttempts(0, 50)
			]);
			users = u;
			sessions = s.items;
			attempts = a.items;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load';
		}
	}

	async function loadVoices() {
		loadingVoices = true;
		voicesLoadError = '';
		try {
			voices = await fetchAdminVoices();
		} catch (e) {
			voicesLoadError = e instanceof Error ? e.message : ADMIN_VOICES_LOAD_FAILED;
		} finally {
			loadingVoices = false;
		}
	}

	async function loadGlobalLimits() {
		try {
			const res = await fetchRateLimits();
			globalLimits = res.settings;
			globalEdits = Object.fromEntries(res.settings.map((s) => [s.setting_key, String(s.value)]));
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load rate limits';
		}
	}

	async function handleSaveGlobal() {
		savingGlobal = true;
		error = '';
		try {
			const settings: Record<string, number> = {};
			for (const [key, val] of Object.entries(globalEdits)) {
				settings[key] = parseInt(val, 10);
			}
			const res = await updateRateLimits(settings);
			globalLimits = res.settings;
			globalEdits = Object.fromEntries(res.settings.map((s) => [s.setting_key, String(s.value)]));
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to save';
		} finally {
			savingGlobal = false;
		}
	}

	async function handleExpandUser(userId: string) {
		if (expandedUserId === userId) {
			expandedUserId = null;
			userLimitsData = null;
			return;
		}
		expandedUserId = userId;
		userEdits = {};
		try {
			userLimitsData = await fetchUserRateLimits(userId);
			const overrideMap = Object.fromEntries(
				userLimitsData.overrides.map((o) => [o.setting_key, o.value])
			);
			userEdits = Object.fromEntries(
				userLimitsData.effective.map((e) => [
					e.setting_key,
					e.is_override ? String(overrideMap[e.setting_key] ?? e.value) : ''
				])
			);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load user limits';
		}
	}

	async function handleSaveUserLimits() {
		if (!expandedUserId) return;
		savingUser = true;
		error = '';
		try {
			const settings: Record<string, number> = {};
			for (const [key, val] of Object.entries(userEdits)) {
				if (val !== '') settings[key] = parseInt(val, 10);
			}
			if (Object.keys(settings).length === 0) {
				await deleteUserRateLimits(expandedUserId);
				userLimitsData = await fetchUserRateLimits(expandedUserId);
			} else {
				userLimitsData = await updateUserRateLimits(expandedUserId, settings);
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to save user limits';
		} finally {
			savingUser = false;
		}
	}

	async function handleClearUserLimits() {
		if (!expandedUserId) return;
		savingUser = true;
		error = '';
		try {
			await deleteUserRateLimits(expandedUserId);
			userLimitsData = await fetchUserRateLimits(expandedUserId);
			userEdits = Object.fromEntries(userLimitsData.effective.map((e) => [e.setting_key, '']));
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to clear';
		} finally {
			savingUser = false;
		}
	}

	function providerLabel(provider: string): string {
		return provider.charAt(0).toUpperCase() + provider.slice(1);
	}

	function providerStatusFor(provider: string): ProviderStatus | undefined {
		return providerStatuses.find((status) => status.provider === provider);
	}

	function cliLoginLabel(surface: ProviderSurfaceStatus): string | undefined {
		return surface.setup_method ? PROVIDER_CLI_LOGIN_LABELS[surface.setup_method] : undefined;
	}

	function surfaceDetail(surface: ProviderSurfaceStatus): string {
		switch (surface.state) {
			case 'unverified':
				return PROVIDER_UNVERIFIED_DETAIL;
			case 'missing_dependency':
				return providerMissingDependencyDetail(surface.missing_dependency);
			case 'unconfigured':
				return surface.needs === 'cli_login'
					? providerMissingRequirementDetail(PROVIDER_CLI_LOGIN_LABELS.claude_cli)
					: providerMissingRequirementDetail(surface.environment_key);
			case 'cli_login_needs_api_key':
				return providerCliLoginNeedsApiKeyDetail(cliLoginLabel(surface));
			case 'api_key_needs_cli_login':
				return PROVIDER_API_KEY_NEEDS_CLI_LOGIN_DETAIL;
			case 'configured':
				return providerConfiguredDetail(cliLoginLabel(surface), surface.environment_key);
		}
	}

	function isNonEmptyString(value: unknown): value is string {
		return typeof value === 'string' && value.length > 0;
	}

	const JUDGE_ROUTE: ModelsRouteKey = 'api';
	const FALLBACK_ROUTE: ModelsRouteKey = 'cli';

	function loadModelsTab(): void {
		void loadProviderStatuses();
		void loadCowriterSettings();
		void loadCoverSettings();
		void loadJudgeSettings();
	}

	async function loadProviderStatuses(): Promise<void> {
		providerStatusError = '';
		try {
			providerStatuses = await fetchProviderStatus();
		} catch (e) {
			providerStatuses = [];
			providerStatusError = e instanceof Error ? e.message : PROVIDER_STATUS_UNAVAILABLE_DETAIL;
		}
	}

	async function loadCowriterSettings(): Promise<void> {
		try {
			cowriterSettings = await fetchCowriterSettings();
			cowriterBudget = cowriterSettings.tail_token_budget;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load co-writer settings';
		}
	}

	async function loadCoverSettings(): Promise<void> {
		try {
			coverSettings = await fetchCoverSettings();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load cover settings';
		}
	}

	async function loadJudgeSettings(): Promise<void> {
		try {
			judgeSettings = await fetchJudgeSettings();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load scoring settings';
		}
	}

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

	function judgeReason(surface: ProviderSurfaceStatus): SafeRouteReason | null {
		if (surface.state === 'configured' || surface.state === 'unverified') return null;
		if (surface.state === 'missing_dependency') {
			return { code: 'cli_binary_unavailable', message: surfaceDetail(surface) };
		}
		return surface.needs === 'cli_login'
			? { code: 'cli_login_not_configured', message: surfaceDetail(surface) }
			: { code: 'api_key_not_set', message: surfaceDetail(surface) };
	}

	function scoringRoute(provider: string, route: ModelsRouteKey): ModelsTaskRoute {
		if (route !== JUDGE_ROUTE) {
			return {
				ready: false,
				reason: {
					code: MODELS_ROUTE_NOT_AVAILABLE_CODE,
					message: modelsRouteNotAvailablePhrase(MODELS_TASK_SCORING_LABEL)
				},
				models: []
			};
		}
		const surface = providerStatusFor(provider)?.judge;
		if (!surface) return taskRoute(provider, route, false, null);
		return taskRoute(provider, route, surface.state === 'configured', judgeReason(surface));
	}

	function taskProviders(
		routeOf: (provider: string, route: ModelsRouteKey) => ModelsTaskRoute,
		names: string[]
	): ModelsTaskProvider[] {
		return names.map((provider) => ({
			provider,
			label: providerLabel(provider),
			routes: { cli: routeOf(provider, 'cli'), api: routeOf(provider, 'api') }
		}));
	}

	function storedRoute(provider: string): ModelsRouteKey {
		const stored = cowriterSettings?.provider_routes?.[provider];
		if (stored) return stored;
		return (
			MODELS_ROUTES.find((route) => catalogueOf(provider, route)?.readiness.state === 'ready') ??
			FALLBACK_ROUTE
		);
	}

	const cowriterProviderNames = $derived(cowriterSettings?.allowed_providers ?? []);
	const cowriterProviders = $derived(taskProviders(transportRoute, cowriterProviderNames));
	const cowriterSelection = $derived<ModelsTaskSelection>({
		provider: cowriterSettings?.provider ?? '',
		route: storedRoute(cowriterSettings?.provider ?? ''),
		model: cowriterSettings?.model ?? ''
	});
	const coverProviders = $derived(taskProviders(coverRoute, cowriterProviderNames));
	const coverSelection = $derived<ModelsTaskSelection>({
		provider: coverSettings?.provider ?? '',
		route: coverSettings?.route ?? FALLBACK_ROUTE,
		model: coverSettings?.model ?? ''
	});
	const scoringProviders = $derived(
		taskProviders(scoringRoute, judgeSettings?.allowed_providers ?? [])
	);
	const scoringSelection = $derived<ModelsTaskSelection>({
		provider: judgeSettings?.provider ?? '',
		route: JUDGE_ROUTE,
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
		return e instanceof Error ? e.message : MODELS_SAVE_FAILED_FALLBACK;
	}

	function routeMapWith(selection: ModelsTaskSelection): Record<string, ModelsRouteKey> {
		const routes = Object.fromEntries(
			cowriterProviders.map((entry) => [entry.provider, storedRoute(entry.provider)])
		);
		return { ...routes, [selection.provider]: selection.route };
	}

	async function saveCowriter(selection: ModelsTaskSelection): Promise<ModelsSaveOutcome> {
		try {
			cowriterSettings = await updateCowriterSettings(
				selection.provider,
				selection.model,
				cowriterBudget,
				routeMapWith(selection)
			);
			cowriterBudget = cowriterSettings.tail_token_budget;
			return { ok: true };
		} catch (e) {
			return {
				ok: false,
				reason: saveFailureReason(e, MODELS_TASK_COWRITER_LABEL, selection.route)
			};
		}
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
			judgeSettings = await updateJudgeSettings(selection.provider, selection.model);
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
		const outcome = await saveCowriter(cowriterSelection);
		if (outcome.ok) {
			cowriterBudgetSaved = true;
			return;
		}
		cowriterBudgetFailure = outcome.reason;
	}

	async function handleCreate() {
		error = '';
		creating = true;
		try {
			await createUser(newUsername, newPassword, newRole);
			newUsername = '';
			newPassword = '';
			newRole = 'user';
			users = await fetchUsers();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to create user';
		} finally {
			creating = false;
		}
	}

	async function handleToggleActive(user: UserItem) {
		try {
			await updateUser(user.id, { is_active: !user.is_active });
			users = await fetchUsers();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to update user';
		}
	}

	async function handleToggleRole(user: UserItem) {
		const newRoleValue = user.role === 'admin' ? 'user' : 'admin';
		try {
			await updateUser(user.id, { role: newRoleValue });
			users = await fetchUsers();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to update role';
		}
	}

	async function handleResetPassword(userId: string) {
		if (!resetPasswordValue || resetPasswordValue.length < 8) {
			error = 'Password must be at least 8 characters';
			return;
		}
		resettingPassword = true;
		error = '';
		try {
			await updateUser(userId, { password: resetPasswordValue });
			resetPasswordUserId = null;
			resetPasswordValue = '';
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to reset password';
		} finally {
			resettingPassword = false;
		}
	}

	async function handleHardDelete(userId: string) {
		deleting = true;
		error = '';
		try {
			await hardDeleteUser(userId);
			deleteUserId = null;
			deleteConfirmInput = '';
			users = await fetchUsers();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to delete user';
		} finally {
			deleting = false;
		}
	}

	async function handleForceLogout(sessionId: string) {
		try {
			await forceLogout(sessionId);
			sessions = (await fetchSessions()).items;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed';
		}
	}

	async function loadGenDefaults() {
		await loadBuiltins();
		try {
			allModels = await fetchAllModels();
		} catch {
			allModels = [];
		}
		try {
			genDefaults = await fetchGenerationDefaults();
		} catch {
			genDefaults = {};
		}
		const modes = Object.keys($builtinDefaults);
		if (modes.length > 0 && !genEditModel) {
			genEditModel = modes[0];
			genEditDefaults = { ...(genDefaults[modes[0]] ?? {}) };
		}
	}

	async function handleToggleModel(modelId: string, currentActive: boolean): Promise<void> {
		try {
			const updated = await toggleModelApi(modelId, !currentActive);
			allModels = allModels.map((m) => (m.id === updated.id ? updated : m));
		} catch {
			error = 'Failed to toggle model';
		}
	}

	function switchGenModel(model: string): void {
		genEditModel = model;
		genEditDefaults = { ...(genDefaults[model] ?? {}) };
	}

	async function handleSaveGenDefaults(): Promise<void> {
		genSaving = true;
		error = '';
		try {
			const cleaned = Object.keys(genEditDefaults).length > 0 ? genEditDefaults : {};
			genDefaults = await updateGenerationDefaults({ ...genDefaults, [genEditModel]: cleaned });
			genEditDefaults = { ...(genDefaults[genEditModel] ?? {}) };
		} catch {
			error = 'Failed to save generation defaults';
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

		{#if tab === 'users'}
			<section>
				<h2>Create User</h2>
				<form
					class="create-form"
					onsubmit={(e) => {
						e.preventDefault();
						handleCreate();
					}}
					autocomplete="off"
				>
					<input
						bind:value={newUsername}
						placeholder="Username"
						minlength={3}
						required
						autocomplete="off"
					/>
					<input
						type="password"
						bind:value={newPassword}
						placeholder="Password"
						minlength={8}
						required
						autocomplete="new-password"
					/>
					<select bind:value={newRole}>
						<option value="user">User</option>
						<option value="admin">Admin</option>
					</select>
					<button type="submit" disabled={creating}>
						{creating ? 'Creating...' : 'Create'}
					</button>
				</form>

				<h2>Users</h2>
				<table class="stack-table {compact ? COMPACT_STACK_CLASS : ''}">
					<thead>
						<tr>
							<th>Username</th>
							<th>Role</th>
							<th>Active</th>
							<th>Created</th>
							<th>Actions</th>
						</tr>
					</thead>
					<tbody>
						{#each users as user (user.id)}
							<tr class:inactive={!user.is_active}>
								<td data-label="Username">{user.username}</td>
								<td data-label="Role">
									<span class="badge" class:admin-badge={user.role === 'admin'}>
										{user.role}
									</span>
								</td>
								<td data-label="Active">{user.is_active ? 'Yes' : 'No'}</td>
								<td data-label="Created"
									>{user.created_at ? new Date(user.created_at).toLocaleDateString() : ''}</td
								>
								<td class="actions">
									{#if me && user.id !== me.id}
										<button class="small" onclick={() => handleToggleRole(user)}>
											{user.role === 'admin' ? 'Demote' : 'Promote'}
										</button>
										<button class="small" onclick={() => handleToggleActive(user)}>
											{user.is_active ? 'Disable' : 'Enable'}
										</button>
										<button
											class="small"
											onclick={() => {
												resetPasswordUserId = resetPasswordUserId === user.id ? null : user.id;
												resetPasswordValue = '';
											}}
										>
											Reset PW
										</button>
										<button
											class="small danger"
											onclick={() => {
												deleteUserId = deleteUserId === user.id ? null : user.id;
												deleteConfirmInput = '';
											}}
										>
											Delete
										</button>
									{:else}
										<span class="text-muted">You</span>
									{/if}
								</td>
							</tr>
							{#if resetPasswordUserId === user.id}
								<tr class="inline-form-row">
									<td colspan="5">
										<form
											class="inline-form"
											onsubmit={(e) => {
												e.preventDefault();
												handleResetPassword(user.id);
											}}
										>
											<input
												type="password"
												bind:value={resetPasswordValue}
												placeholder="New password (min 8 chars)"
												minlength={8}
												required
												autocomplete="new-password"
											/>
											<button type="submit" class="small" disabled={resettingPassword}>
												{resettingPassword ? 'Saving...' : 'Save'}
											</button>
											<button
												type="button"
												class="small"
												onclick={() => {
													resetPasswordUserId = null;
													resetPasswordValue = '';
												}}
											>
												Cancel
											</button>
										</form>
									</td>
								</tr>
							{/if}
							{#if deleteUserId === user.id}
								<tr class="inline-form-row">
									<td colspan="5">
										<div class="delete-confirm">
											<p class="delete-warning">
												Permanently delete <strong>{user.username}</strong> and all their albums, songs,
												and generations. This cannot be undone.
											</p>
											<form
												class="inline-form"
												onsubmit={(e) => {
													e.preventDefault();
													handleHardDelete(user.id);
												}}
											>
												<input
													type="text"
													bind:value={deleteConfirmInput}
													placeholder="Type username to confirm"
													autocomplete="off"
												/>
												<button
													type="submit"
													class="small danger"
													disabled={deleting || deleteConfirmInput !== user.username}
												>
													{deleting ? 'Deleting...' : 'Confirm Delete'}
												</button>
												<button
													type="button"
													class="small"
													onclick={() => {
														deleteUserId = null;
														deleteConfirmInput = '';
													}}
												>
													Cancel
												</button>
											</form>
										</div>
									</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
			</section>
		{/if}

		{#if tab === 'voices'}
			<section>
				<h2>{ADMIN_VOICES_HEADING}</h2>
				{#if loadingVoices}
					<p class="text-muted">{ADMIN_VOICES_LOADING}</p>
				{:else if voicesLoadError}
					<p class="error">{voicesLoadError}</p>
				{:else if voices.length === 0}
					<p class="text-muted">{ADMIN_VOICES_EMPTY}</p>
				{:else}
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

		{#if tab === 'sessions'}
			<section>
				<h2>Active Sessions</h2>
				<table class="stack-table {compact ? COMPACT_STACK_CLASS : ''}">
					<thead>
						<tr>
							<th>User</th>
							<th>IP</th>
							<th>Created</th>
							<th>Expires</th>
							<th>Actions</th>
						</tr>
					</thead>
					<tbody>
						{#each sessions as sess (sess.id)}
							<tr>
								<td data-label="User">{sess.username}</td>
								<td data-label="IP">{sess.ip_address}</td>
								<td data-label="Created"
									>{sess.created_at ? new Date(sess.created_at).toLocaleString() : ''}</td
								>
								<td data-label="Expires"
									>{sess.expires_at ? new Date(sess.expires_at).toLocaleString() : ''}</td
								>
								<td class="actions">
									<button class="small danger" onclick={() => handleForceLogout(sess.id)}>
										Revoke
									</button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</section>
		{/if}

		{#if tab === 'attempts'}
			<section>
				<h2>Recent Login Attempts</h2>
				<table class="stack-table {compact ? COMPACT_STACK_CLASS : ''}">
					<thead>
						<tr>
							<th>Time</th>
							<th>Username</th>
							<th>IP</th>
							<th>Result</th>
						</tr>
					</thead>
					<tbody>
						{#each attempts as att (att.id)}
							<tr>
								<td data-label="Time"
									>{att.attempted_at ? new Date(att.attempted_at).toLocaleString() : ''}</td
								>
								<td data-label="Username">{att.username}</td>
								<td data-label="IP">{att.ip_address}</td>
								<td data-label="Result">
									<span class:success={att.success} class:fail={!att.success}>
										{att.success ? 'OK' : 'Failed'}
									</span>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</section>
		{/if}

		{#if tab === 'ratelimits'}
			<section>
				<h2>Global Defaults</h2>
				<p class="hint">These apply to all users unless overridden per-user.</p>
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

				<h2>Per-User Overrides</h2>
				<p class="hint">Click a user to set individual limits. Empty = uses global default.</p>
				<table class="stack-table {compact ? COMPACT_STACK_CLASS : ''}">
					<thead>
						<tr>
							<th>Username</th>
							<th>Role</th>
							<th>Overrides</th>
						</tr>
					</thead>
					<tbody>
						{#each users as user (user.id)}
							<tr
								class="clickable"
								class:expanded={expandedUserId === user.id}
								onclick={() => handleExpandUser(user.id)}
							>
								<td data-label="Username">{user.username}</td>
								<td data-label="Role">
									<span class="badge" class:admin-badge={user.role === 'admin'}>
										{user.role}
									</span>
								</td>
								<td data-label="Overrides">
									{#if expandedUserId === user.id && userLimitsData}
										{userLimitsData.overrides.length} custom
									{:else}
										-
									{/if}
								</td>
							</tr>
							{#if expandedUserId === user.id && userLimitsData}
								<tr class="override-row">
									<td colspan="3">
										<div class="limits-grid">
											{#each userLimitsData.effective as eff (eff.setting_key)}
												<label class="limit-row">
													<span class="limit-label">
														{SETTING_LABELS[eff.setting_key] ?? eff.setting_key}
														<span class="effective-val">(effective: {eff.value})</span>
													</span>
													<input
														type="number"
														min="0"
														placeholder={String(eff.value)}
														bind:value={userEdits[eff.setting_key]}
														class="limit-input"
														onclick={(e) => e.stopPropagation()}
													/>
												</label>
											{/each}
										</div>
										<div class="override-actions">
											<!-- svelte-ignore a11y_click_events_have_key_events -->
											<!-- svelte-ignore a11y_no_static_element_interactions -->
											<span
												class="save-btn"
												onclick={(e) => {
													e.stopPropagation();
													handleSaveUserLimits();
												}}
												class:disabled={savingUser}
											>
												{savingUser ? 'Saving...' : 'Save Overrides'}
											</span>
											<!-- svelte-ignore a11y_click_events_have_key_events -->
											<!-- svelte-ignore a11y_no_static_element_interactions -->
											<span
												class="clear-btn"
												onclick={(e) => {
													e.stopPropagation();
													handleClearUserLimits();
												}}
											>
												Clear All
											</span>
										</div>
									</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
			</section>
		{/if}

		{#if tab === 'generation'}
			<section>
				<h2>Generation Defaults</h2>
				<p class="hint">
					Default generation parameters for all users. Per-song overrides take precedence.
				</p>

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
					<button class="save-btn" onclick={handleSaveGenDefaults} disabled={genSaving}>
						{genSaving ? 'Saving...' : 'Save Defaults'}
					</button>
					<button class="clear-btn" onclick={handleResetGenDefaults}>Reset</button>
				</div>
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
						<ModelsTaskRow
							task={MODELS_TASK_COWRITER_LABEL}
							providers={cowriterProviders}
							selection={cowriterSelection}
							save={saveCowriter}
							advanced={cowriterAdvanced}
						/>
					{:else}
						<p class="hint">{MODELS_LOADING_LABEL}</p>
					{/if}
					{#if coverSettings && cowriterSettings}
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

	.create-form {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 1rem;
		flex-wrap: wrap;
	}

	.create-form input,
	.create-form select {
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: var(--input-radius);
		color: var(--text);
		padding: var(--input-padding);
		font-size: var(--input-font-size);
		font-family: var(--font-body);
	}

	.create-form button {
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: white;
		border: none;
		border-radius: var(--btn-radius-pill);
		padding: 0.5rem 1rem;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: var(--btn-letter-spacing);
		transition: box-shadow 0.2s;
	}

	.create-form button:hover:not(:disabled) {
		box-shadow: 0 0 16px rgba(160, 32, 240, 0.3);
	}

	.create-form button:disabled {
		opacity: 0.5;
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

	tr.inactive td {
		opacity: 0.5;
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

	.admin-badge {
		background: var(--primary);
		color: white;
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.3rem;
	}

	button.small {
		background: var(--surface-hover);
		color: var(--text);
		border: 1px solid var(--border);
		border-radius: 3px;
		padding: 0.2rem 0.5rem;
		font-size: 0.75rem;
		cursor: pointer;
		font-family: var(--font-body);
	}

	button.small:hover {
		background: var(--border);
	}

	button.small.danger {
		color: var(--score-bad);
		border-color: var(--score-bad);
	}

	tr.inline-form-row td {
		padding: 0.5rem;
		background: var(--surface);
		border-bottom: 1px solid var(--border);
	}

	.inline-form {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		align-items: center;
	}

	.inline-form input {
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: var(--input-radius);
		color: var(--text);
		padding: var(--input-padding);
		font-size: var(--input-font-size);
		font-family: var(--font-body);
		min-width: 0;
		flex: 1 1 12rem;
	}

	.delete-confirm {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.delete-warning {
		color: var(--score-bad);
		font-size: 0.8rem;
		margin: 0;
	}

	.text-muted {
		color: var(--text-muted);
		font-size: 0.8rem;
	}

	.success {
		color: var(--score-good);
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

	.effective-val {
		color: var(--text-subtle);
		font-size: 0.75rem;
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
		color: white;
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
		box-shadow: 0 0 16px rgba(160, 32, 240, 0.3);
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

	.override-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		align-items: center;
		margin-top: 0.5rem;
	}

	tr.clickable {
		cursor: pointer;
	}

	tr.clickable:hover td {
		background: var(--surface-hover);
	}

	tr.expanded td {
		background: var(--surface);
		border-bottom: none;
	}

	tr.override-row td {
		padding: 0.75rem 0.5rem 1rem;
		background: var(--surface);
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
		color: #fff;
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
		color: #fff;
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
