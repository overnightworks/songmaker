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
		fetchProviderStatus
	} from '$lib/api/client';
	import type { AvailableModel } from '$lib/api/client';
	import type {
		CowriterSettings,
		JudgeSettings,
		ProviderNotConfiguredDetail,
		ProviderRouteStatusResponse,
		ProviderStatus,
		ProviderSurfaceStatus
	} from '$lib/api/types';
	import type { VersionGenerationParams } from '$lib/api/types';
	import ParamControls from '$lib/components/ParamControls.svelte';
	import WorkerPoolPanel from '$lib/components/WorkerPoolPanel.svelte';
	import ModelRegistryPanel from '$lib/components/ModelRegistryPanel.svelte';
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
		PROVIDER_API_KEY_NEEDS_CLI_LOGIN_DETAIL,
		PROVIDER_CLI_LOGIN_LABELS,
		PROVIDER_CONFIGURED_LABEL,
		PROVIDER_COWRITER_SURFACE_PREFIX,
		PROVIDER_JUDGE_SURFACE_PREFIX,
		PROVIDER_KEY_ONLY_LABEL,
		PROVIDER_LOGIN_ONLY_LABEL,
		PROVIDER_MISSING_DEPENDENCY_LABEL,
		PROVIDER_NOT_CONFIGURED_LABEL,
		PROVIDER_UNVERIFIED_DETAIL,
		PROVIDER_UNVERIFIED_LABEL,
		PROVIDER_STATUS_DESCRIPTION,
		PROVIDER_STATUS_EMPTY_MESSAGE,
		PROVIDER_STATUS_REFRESHING_MESSAGE,
		PROVIDER_STATUS_UNAVAILABLE_DETAIL,
		providerCliLoginNeedsApiKeyDetail,
		providerConfiguredDetail,
		providerMissingDependencyDetail,
		providerMissingRequirementDetail,
		COWRITER_MODEL_CURRENT_NOT_IN_CATALOG,
		COWRITER_SAVE_CHANGED,
		COWRITER_SAVE_MODEL_REQUIRED,
		COWRITER_SAVE_NOTHING_CHANGED,
		PROVIDER_ROUTE_API_LABEL,
		PROVIDER_ROUTE_ACTIVE_LABEL,
		PROVIDER_ROUTE_BROKEN_LABEL,
		PROVIDER_ROUTE_CLI_LABEL,
		PROVIDER_ROUTE_CONFIGURATION_REQUIRED,
		PROVIDER_ROUTE_KEY_NOT_SET_LABEL,
		PROVIDER_ROUTE_KEY_SET_LABEL,
		PROVIDER_ROUTE_MODELS_LABEL,
		PROVIDER_ROUTE_NO_MODELS_LABEL,
		PROVIDER_ROUTE_NOT_SET_UP_LABEL,
		PROVIDER_ROUTE_READY_LABEL,
		PROVIDER_ROUTE_STATUS_UNAVAILABLE_LABEL,
		PROVIDER_ROUTE_STILL_ACTIVE_LABEL,
		PROVIDER_ROUTE_TURN_BLOCKED_LABEL,
		PROVIDER_ROUTE_UNAVAILABLE_DETAIL,
		PROVIDER_ROUTE_UNAVAILABLE_LABEL,
		providerRouteBlockedDetail,
		providerRouteModelLabel
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
	let loadingProviderStatuses = $state(false);
	let providerStatusError = $state('');

	let cowriterSettings = $state<CowriterSettings | null>(null);
	let cowriterProvider = $state('claude');
	let cowriterModel = $state('');
	let cowriterBudget = $state(0);
	let cowriterRoutes = $state<Record<string, 'cli' | 'api'>>({});
	let savingCowriter = $state(false);

	let judgeSettings = $state<JudgeSettings | null>(null);
	let judgeProvider = $state('claude');
	let judgeModel = $state('');
	let savingJudge = $state(false);

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

	function isProviderSurfaceStatus(detail: unknown): detail is ProviderSurfaceStatus {
		if (typeof detail !== 'object' || detail === null) return false;
		const status = detail as Partial<ProviderSurfaceStatus>;
		return (
			status.state === 'unverified' ||
			status.state === 'configured' ||
			status.state === 'cli_login_needs_api_key' ||
			status.state === 'api_key_needs_cli_login' ||
			status.state === 'missing_dependency' ||
			status.state === 'unconfigured'
		);
	}

	function isProviderNotConfiguredDetail(detail: unknown): detail is ProviderNotConfiguredDetail {
		if (typeof detail !== 'object' || detail === null) return false;
		const candidate = detail as Partial<ProviderNotConfiguredDetail>;
		return (
			isNonEmptyString(candidate.provider) &&
			(candidate.surface === 'cowriter' || candidate.surface === 'judge') &&
			isProviderSurfaceStatus(candidate.status)
		);
	}

	function providerNotConfiguredMessage(error: unknown): string | null {
		if (!(error instanceof ApiError) || !isProviderNotConfiguredDetail(error.responseDetail)) {
			return null;
		}
		const surfacePrefix =
			error.responseDetail.surface === 'cowriter'
				? PROVIDER_COWRITER_SURFACE_PREFIX
				: PROVIDER_JUDGE_SURFACE_PREFIX;
		return `${providerLabel(error.responseDetail.provider)} ${surfacePrefix} ${surfaceDetail(error.responseDetail.status)}`;
	}

	function providerDetail(status: ProviderStatus): string[] {
		const cowriter = surfaceDetail(status.cowriter);
		const judge = surfaceDetail(status.judge);
		return cowriter === judge
			? [cowriter]
			: [
					`${PROVIDER_COWRITER_SURFACE_PREFIX} ${cowriter}`,
					`${PROVIDER_JUDGE_SURFACE_PREFIX} ${judge}`
				];
	}

	function worstState(status: ProviderStatus): ProviderSurfaceStatus['state'] {
		const stateRank: Record<ProviderSurfaceStatus['state'], number> = {
			unconfigured: 0,
			missing_dependency: 1,
			cli_login_needs_api_key: 2,
			api_key_needs_cli_login: 2,
			unverified: 3,
			configured: 4
		};
		return stateRank[status.cowriter.state] <= stateRank[status.judge.state]
			? status.cowriter.state
			: status.judge.state;
	}

	function surfaceFor(provider: string, surface: 'cowriter' | 'judge') {
		return providerStatusFor(provider)?.[surface];
	}

	function answering(provider: string, surface: 'cowriter' | 'judge'): boolean {
		return surfaceFor(provider, surface)?.state === 'configured';
	}

	function pickerStatus(provider: string, surface: 'cowriter' | 'judge'): string {
		const status = surfaceFor(provider, surface);
		const state = status?.state;
		if (state === 'missing_dependency') return PROVIDER_MISSING_DEPENDENCY_LABEL;
		if (state === 'unverified') return PROVIDER_UNVERIFIED_LABEL;
		if (state === 'cli_login_needs_api_key') return PROVIDER_LOGIN_ONLY_LABEL;
		return state === 'api_key_needs_cli_login'
			? PROVIDER_KEY_ONLY_LABEL
			: PROVIDER_NOT_CONFIGURED_LABEL;
	}

	function pickerReason(provider: string, surface: 'cowriter' | 'judge'): string {
		const status = surfaceFor(provider, surface);
		return status ? surfaceDetail(status) : PROVIDER_STATUS_UNAVAILABLE_DETAIL;
	}

	async function loadModelsTab() {
		loadingProviderStatuses = true;
		providerStatusError = '';
		try {
			providerStatuses = await fetchProviderStatus();
		} catch (e) {
			providerStatuses = [];
			providerStatusError = e instanceof Error ? e.message : 'Failed to load provider status';
		} finally {
			loadingProviderStatuses = false;
		}
		try {
			cowriterSettings = await fetchCowriterSettings();
			cowriterProvider = cowriterSettings.provider;
			cowriterModel = cowriterSettings.model;
			cowriterBudget = cowriterSettings.tail_token_budget;
			cowriterRoutes = { ...(cowriterSettings.provider_routes ?? {}) };
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load co-writer settings';
		}
		try {
			judgeSettings = await fetchJudgeSettings();
			judgeProvider = judgeSettings.provider;
			judgeModel = judgeSettings.model;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load scoring settings';
		}
	}

	type ProviderRoute = 'cli' | 'api';

	function selectedCowriterRoute(provider: string): ProviderRoute | undefined {
		return cowriterRoutes[provider] ?? cowriterSettings?.provider_routes?.[provider];
	}

	function routeStatus(
		provider: string,
		route: ProviderRoute | undefined
	): ProviderRouteStatusResponse | undefined {
		return route ? cowriterSettings?.provider_routes_status?.[provider]?.[route] : undefined;
	}

	function routeStateLabel(status: ProviderRouteStatusResponse | undefined): string {
		if (!status) return PROVIDER_ROUTE_STATUS_UNAVAILABLE_LABEL;
		if (status?.readiness.state === 'ready') return PROVIDER_ROUTE_READY_LABEL;
		if (status?.readiness.state === 'disturbed') return PROVIDER_ROUTE_BROKEN_LABEL;
		return PROVIDER_ROUTE_NOT_SET_UP_LABEL;
	}

	function routeReason(
		status: ProviderRouteStatusResponse | undefined,
		route: ProviderRoute
	): string {
		if (!status) return PROVIDER_STATUS_UNAVAILABLE_DETAIL;
		if (route === 'api' && status.readiness.state === 'ready') return PROVIDER_ROUTE_KEY_SET_LABEL;
		if (route === 'api' && status.readiness.reason?.code === 'api_key_not_set') {
			return PROVIDER_ROUTE_KEY_NOT_SET_LABEL;
		}
		return (
			status.readiness.reason?.message ??
			status.catalogue_failure?.message ??
			status.readiness.setup_label
		);
	}

	function routeCatalogDetail(status: ProviderRouteStatusResponse | undefined): string | undefined {
		if (!status) return undefined;
		if (status.catalog_version) return `Version ${status.catalog_version}`;
		return status.catalog_source ?? undefined;
	}

	function routeIsReady(provider: string, route: ProviderRoute | undefined): boolean {
		const status = routeStatus(provider, route);
		return cowriterRouteStatusAvailable
			? status?.readiness.state === 'ready'
			: answering(provider, 'cowriter');
	}

	function routeModels(provider: string, route: ProviderRoute | undefined): string[] {
		const status = routeStatus(provider, route);
		if (!cowriterRouteStatusAvailable) {
			return cowriterSettings?.models_by_provider?.[provider] ?? [];
		}
		if (!status) return [];
		const retainedModel = status.retained_model_id;
		return retainedModel && !status.models.includes(retainedModel)
			? [...status.models, retainedModel]
			: status.models;
	}

	function completeCowriterRoutes(): Record<string, ProviderRoute> | undefined {
		if (!cowriterSettings || !cowriterRouteStatusAvailable) return undefined;
		const entries = cowriterSettings.allowed_providers.map(
			(provider) => [provider, selectedCowriterRoute(provider)] as const
		);
		if (entries.some(([, route]) => route === undefined)) return undefined;
		return Object.fromEntries(entries) as Record<string, ProviderRoute>;
	}

	const cowriterRouteStatusAvailable = $derived(
		cowriterSettings?.provider_routes_status !== undefined
	);
	const cowriterRoute = $derived(selectedCowriterRoute(cowriterProvider));
	const selectedCowriterRouteStatus = $derived(routeStatus(cowriterProvider, cowriterRoute));
	const cowriterModels = $derived(routeModels(cowriterProvider, cowriterRoute));
	const cowriterModelsError = $derived(
		selectedCowriterRouteStatus?.catalogue_failure?.message ??
			cowriterSettings?.models_errors?.[cowriterProvider]
	);
	const cowriterModelsSource = $derived(
		routeCatalogDetail(selectedCowriterRouteStatus) ??
			cowriterSettings?.models_sources?.[cowriterProvider]
	);
	const cowriterCurrentModelNotInCatalog = $derived(
		selectedCowriterRouteStatus?.retained_model_id ??
			cowriterSettings?.current_models_not_in_catalog?.[cowriterProvider]
	);
	const cowriterSelectedRouteReady = $derived(routeIsReady(cowriterProvider, cowriterRoute));
	const cowriterRoutesToSave = $derived(completeCowriterRoutes());
	const cowriterHasReadyRoute = $derived(
		cowriterSettings?.allowed_providers.some((provider) =>
			(['cli', 'api'] as const).some((route) => routeIsReady(provider, route))
		) ?? false
	);
	const cowriterDirty = $derived(
		cowriterSettings !== null &&
			(cowriterProvider !== cowriterSettings.provider ||
				cowriterModel !== cowriterSettings.model ||
				cowriterBudget !== cowriterSettings.tail_token_budget ||
				cowriterSettings.allowed_providers.some(
					(provider) => cowriterRoutes[provider] !== cowriterSettings?.provider_routes?.[provider]
				))
	);
	const cowriterCanSave = $derived(
		cowriterDirty &&
			cowriterModel !== '' &&
			cowriterSelectedRouteReady &&
			(!cowriterRouteStatusAvailable || cowriterRoutesToSave !== undefined) &&
			!savingCowriter
	);
	const cowriterSaveReason = $derived(
		savingCowriter
			? ''
			: !cowriterDirty
				? COWRITER_SAVE_NOTHING_CHANGED
				: cowriterRouteStatusAvailable && cowriterRoutesToSave === undefined
					? PROVIDER_ROUTE_CONFIGURATION_REQUIRED
					: cowriterModel === ''
						? COWRITER_SAVE_MODEL_REQUIRED
						: COWRITER_SAVE_CHANGED
	);

	const judgeModels = $derived(judgeSettings?.models_by_provider?.[judgeProvider] ?? []);
	const judgeModelsError = $derived(judgeSettings?.models_errors?.[judgeProvider]);
	const judgeDirty = $derived(
		judgeSettings !== null &&
			(judgeProvider !== judgeSettings.provider || judgeModel !== judgeSettings.model)
	);
	const judgeCanSave = $derived(judgeDirty && judgeModel !== '' && !savingJudge);

	function savedCowriterModel(provider: string, models: string[]): string | null {
		if (cowriterSettings?.provider !== provider) return null;
		return models.includes(cowriterSettings.model) ? cowriterSettings.model : null;
	}

	function cowriterCardModel(provider: string, models: string[]): string {
		if (provider === cowriterProvider) return cowriterModel;
		return savedCowriterModel(provider, models) ?? models[0] ?? '';
	}

	function selectCowriterProvider(provider: string): void {
		cowriterProvider = provider;
		const models = routeModels(provider, selectedCowriterRoute(provider));
		cowriterModel = savedCowriterModel(provider, models) ?? models[0] ?? '';
	}

	function selectCowriterRoute(provider: string, route: ProviderRoute): void {
		cowriterRoutes = { ...cowriterRoutes, [provider]: route };
		if (provider !== cowriterProvider) return;
		const models = routeModels(provider, route);
		if (models.includes(cowriterModel)) return;
		cowriterModel = models[0] ?? '';
	}

	function selectJudgeProvider(provider: string): void {
		judgeProvider = provider;
		if (judgeSettings && provider === judgeSettings.provider) {
			judgeModel = judgeSettings.model;
			return;
		}
		const models = judgeSettings?.models_by_provider?.[provider] ?? [];
		judgeModel = models[0] ?? '';
	}

	async function handleSaveCowriter() {
		savingCowriter = true;
		error = '';
		try {
			cowriterSettings = await updateCowriterSettings(
				cowriterProvider,
				cowriterModel,
				cowriterBudget,
				cowriterRoutesToSave
			);
			cowriterProvider = cowriterSettings.provider;
			cowriterModel = cowriterSettings.model;
			cowriterBudget = cowriterSettings.tail_token_budget;
			cowriterRoutes = { ...(cowriterSettings.provider_routes ?? {}) };
		} catch (e) {
			error =
				providerNotConfiguredMessage(e) ??
				(e instanceof Error ? e.message : 'Failed to save co-writer settings');
		} finally {
			savingCowriter = false;
		}
	}

	async function handleSaveJudge() {
		savingJudge = true;
		error = '';
		try {
			judgeSettings = await updateJudgeSettings(judgeProvider, judgeModel);
			judgeProvider = judgeSettings.provider;
			judgeModel = judgeSettings.model;
		} catch (e) {
			error =
				providerNotConfiguredMessage(e) ??
				(e instanceof Error ? e.message : 'Failed to save scoring settings');
		} finally {
			savingJudge = false;
		}
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
			<section>
				<h2>Providers</h2>
				<p class="hint">{PROVIDER_STATUS_DESCRIPTION}</p>
				{#if providerStatuses.length > 0}
					<div class="provider-status-list">
						{#each providerStatuses as status (status.provider)}
							{@const state = worstState(status)}
							<div
								class="provider-status-row"
								class:ok={state === 'configured'}
								class:unverified={state === 'unverified'}
								class:partial={state === 'unverified' ||
									state === 'cli_login_needs_api_key' ||
									state === 'api_key_needs_cli_login'}
								class:bad={state === 'missing_dependency' || state === 'unconfigured'}
							>
								<span class="dot"></span>
								<span>
									<span class="name">{providerLabel(status.provider)}</span>
									{#each providerDetail(status) as line (line)}
										<span class="detail">{line}</span>
									{/each}
								</span>
							</div>
						{/each}
					</div>
					{#if loadingProviderStatuses}
						<p>{PROVIDER_STATUS_REFRESHING_MESSAGE}</p>
					{/if}
				{:else if loadingProviderStatuses}
					<p>Loading...</p>
				{:else if providerStatusError}
					<p class="error">{providerStatusError}</p>
				{:else}
					<p>{PROVIDER_STATUS_EMPTY_MESSAGE}</p>
				{/if}
			</section>

			<section>
				<h2>Co-Writer</h2>
				<p class="hint">
					Provider and model that answer your next message. The model list is loaded live from that
					provider.
				</p>
				{#if cowriterSettings}
					<div class="claude-form">
						<div class="active-banner">
							<span class="dot"></span>
							<span>
								<b
									>{cowriterDirty
										? PROVIDER_ROUTE_STILL_ACTIVE_LABEL
										: PROVIDER_ROUTE_ACTIVE_LABEL}</b
								>
								<span class="model"
									>{providerLabel(cowriterSettings.provider)} · {cowriterSettings.provider_routes?.[
										cowriterSettings.provider
									]?.toUpperCase() ?? PROVIDER_ROUTE_API_LABEL} · {cowriterSettings.model}</span
								>
							</span>
						</div>
						{#if cowriterDirty}
							<div class="change-banner">
								<span
									>Saving switches the co-writer to <strong
										>{providerLabel(cowriterProvider)} · {cowriterModel || '…'}</strong
									>. Earlier messages stay as they are; only the next reply changes.</span
								>
							</div>
						{/if}
						{#if cowriterRouteStatusAvailable}
							{#if !cowriterHasReadyRoute}
								<div class="blocked-banner" role="alert">
									<span>●</span>
									<span
										><strong>{PROVIDER_ROUTE_UNAVAILABLE_LABEL}</strong><br
										/>{PROVIDER_ROUTE_UNAVAILABLE_DETAIL}</span
									>
								</div>
							{:else if !cowriterSelectedRouteReady && cowriterRoute}
								<div class="blocked-banner" role="alert">
									<span>●</span>
									<span
										><strong>{PROVIDER_ROUTE_TURN_BLOCKED_LABEL}</strong><br
										/>{providerRouteBlockedDetail(
											providerLabel(cowriterProvider),
											cowriterRoute,
											routeStateLabel(selectedCowriterRouteStatus),
											routeReason(selectedCowriterRouteStatus, cowriterRoute)
										)}</span
									>
								</div>
							{/if}
							<div class="claude-field">
								<span class="field-label">{PROVIDER_ROUTE_MODELS_LABEL}</span>
								<div class="route-grid">
									{#each cowriterSettings.allowed_providers as provider (provider)}
										{@const selectedRoute = selectedCowriterRoute(provider)}
										{@const cliStatus = routeStatus(provider, 'cli')}
										{@const apiStatus = routeStatus(provider, 'api')}
										{@const models = routeModels(provider, selectedRoute)}
										{@const selectedStatus = routeStatus(provider, selectedRoute)}
										{@const selectedRouteReady = routeIsReady(provider, selectedRoute)}
										<div
											class="route-card"
											class:selected={provider === cowriterProvider}
											class:unavailable={!selectedRouteReady}
										>
											<div class="route-card-head">
												<button
													type="button"
													class="route-provider"
													class:selected={provider === cowriterProvider}
													aria-pressed={provider === cowriterProvider}
													onclick={() => selectCowriterProvider(provider)}
													>{providerLabel(provider)}</button
												>
												<div class="route-switch" aria-label={`${providerLabel(provider)} route`}>
													<button
														type="button"
														class:selected={selectedRoute === 'cli'}
														aria-label={`Use ${providerLabel(provider)} ${PROVIDER_ROUTE_CLI_LABEL} route`}
														aria-pressed={selectedRoute === 'cli'}
														onclick={() => selectCowriterRoute(provider, 'cli')}
														>{PROVIDER_ROUTE_CLI_LABEL}</button
													>
													<button
														type="button"
														class:selected={selectedRoute === 'api'}
														aria-label={`Use ${providerLabel(provider)} ${PROVIDER_ROUTE_API_LABEL} route`}
														aria-pressed={selectedRoute === 'api'}
														onclick={() => selectCowriterRoute(provider, 'api')}
														>{PROVIDER_ROUTE_API_LABEL}</button
													>
												</div>
											</div>
											<div class="route-status-list">
												<div
													class="route-status"
													class:ready={routeStateLabel(cliStatus) === PROVIDER_ROUTE_READY_LABEL}
													class:broken={routeStateLabel(cliStatus) === PROVIDER_ROUTE_BROKEN_LABEL}
													class:not-set-up={routeStateLabel(cliStatus) ===
														PROVIDER_ROUTE_NOT_SET_UP_LABEL}
													class:unavailable={routeStateLabel(cliStatus) ===
														PROVIDER_ROUTE_STATUS_UNAVAILABLE_LABEL}
												>
													<span class="dot"></span><span
														><strong
															>{PROVIDER_ROUTE_CLI_LABEL} · {routeStateLabel(cliStatus)}</strong
														><small>{routeReason(cliStatus, 'cli')}</small></span
													>
												</div>
												<div
													class="route-status"
													class:ready={routeStateLabel(apiStatus) === PROVIDER_ROUTE_READY_LABEL}
													class:broken={routeStateLabel(apiStatus) === PROVIDER_ROUTE_BROKEN_LABEL}
													class:not-set-up={routeStateLabel(apiStatus) ===
														PROVIDER_ROUTE_NOT_SET_UP_LABEL}
													class:unavailable={routeStateLabel(apiStatus) ===
														PROVIDER_ROUTE_STATUS_UNAVAILABLE_LABEL}
												>
													<span class="dot"></span><span
														><strong
															>{PROVIDER_ROUTE_API_LABEL} · {routeStateLabel(apiStatus)}</strong
														><small>{routeReason(apiStatus, 'api')}</small></span
													>
												</div>
											</div>
											<div class="route-model">
												<label for={`cowriter-model-${provider}`}
													>{providerRouteModelLabel(selectedRoute)}</label
												>
												<select
													id={`cowriter-model-${provider}`}
													value={cowriterCardModel(provider, models)}
													disabled={provider !== cowriterProvider ||
														models.length === 0 ||
														!selectedRouteReady}
													onchange={(event) =>
														(cowriterModel = (event.currentTarget as HTMLSelectElement).value)}
												>
													{#if models.length === 0}
														<option value="">{PROVIDER_ROUTE_NO_MODELS_LABEL}</option>
													{:else}
														{#each models as model (model)}
															<option value={model}
																>{model}{selectedStatus?.retained_model_id === model
																	? ` (${COWRITER_MODEL_CURRENT_NOT_IN_CATALOG})`
																	: ''}</option
															>
														{/each}
													{/if}
												</select>
												{#if routeCatalogDetail(selectedStatus)}<p class="hint">
														{routeCatalogDetail(selectedStatus)}
													</p>{/if}
												{#if selectedStatus?.catalogue_failure?.message}<p class="hint">
														{selectedStatus.catalogue_failure.message}
													</p>{/if}
											</div>
										</div>
									{/each}
								</div>
							</div>
						{:else}
							<div class="claude-field">
								<span class="field-label" id="cowriter-provider-label">Provider</span>
								<div class="provider-picker" role="group" aria-labelledby="cowriter-provider-label">
									{#each cowriterSettings.allowed_providers as provider (provider)}
										{@const canAnswer = answering(provider, 'cowriter')}
										<button
											type="button"
											class="provider-pill"
											class:selected={cowriterProvider === provider}
											aria-pressed={cowriterProvider === provider}
											disabled={!canAnswer}
											onclick={() => selectCowriterProvider(provider)}
										>
											<span class="name">{providerLabel(provider)}</span>
											<span
												class="pill-status"
												class:status-ok={canAnswer}
												class:status-bad={!canAnswer}
											>
												{canAnswer ? PROVIDER_CONFIGURED_LABEL : pickerStatus(provider, 'cowriter')}
											</span>
											{#if !canAnswer}
												<span class="pill-reason">{pickerReason(provider, 'cowriter')}</span>
											{/if}
										</button>
									{/each}
								</div>
							</div>
							<div class="claude-field">
								<label for="cowriter-model"
									>{cowriterRouteStatusAvailable
										? providerRouteModelLabel(cowriterRoute)
										: 'Model'}</label
								>
								<select
									id="cowriter-model"
									bind:value={cowriterModel}
									disabled={cowriterModels.length === 0}
								>
									{#if cowriterModels.length === 0 && cowriterModel}
										<option value={cowriterModel}
											>{cowriterModel} (current — live list unavailable)</option
										>
									{/if}
									{#each cowriterModels as model (model)}
										<option value={model}
											>{model}{cowriterCurrentModelNotInCatalog === model
												? ` (${COWRITER_MODEL_CURRENT_NOT_IN_CATALOG})`
												: ''}</option
										>
									{/each}
								</select>
								{#if cowriterModelsSource}
									<p class="hint">{cowriterModelsSource}</p>
								{/if}
								{#if cowriterModelsError}
									<p class="hint">{cowriterModelsError}</p>
								{/if}
							</div>
						{/if}
						<div class="claude-field">
							<label for="cowriter-budget">History tail (tokens)</label>
							<input
								id="cowriter-budget"
								type="number"
								bind:value={cowriterBudget}
								min="2000"
								max="100000"
							/>
						</div>
						<div class="btn-row">
							<button class="save-btn" onclick={handleSaveCowriter} disabled={!cowriterCanSave}>
								{savingCowriter ? 'Saving...' : 'Save Co-Writer'}
							</button>
							<span class="save-reason">{cowriterSaveReason}</span>
						</div>
					</div>
				{:else}
					<p>Loading...</p>
				{/if}
			</section>

			<section>
				<h2>Scoring</h2>
				<p class="hint">
					Provider and model that judge how closely the sung lyrics match what you wrote. Its own
					choice, independent of the co-writer.
				</p>
				{#if judgeSettings}
					<div class="claude-form">
						<div class="active-banner">
							<span class="dot"></span>
							<span>
								<b>{judgeDirty ? 'Still active' : 'Active'}</b>
								<span class="model"
									>{providerLabel(judgeSettings.provider)} · {judgeSettings.model}</span
								>
							</span>
						</div>
						{#if judgeDirty}
							<div class="change-banner">
								<span
									>Saving switches the judge to <strong
										>{providerLabel(judgeProvider)} · {judgeModel || '…'}</strong
									>. Already-scored generations keep their scores; only the next scoring run
									changes.</span
								>
							</div>
						{/if}
						<div class="claude-field">
							<span class="field-label" id="judge-provider-label">Provider</span>
							<div class="provider-picker" role="group" aria-labelledby="judge-provider-label">
								{#each judgeSettings.allowed_providers as provider (provider)}
									{@const canAnswer = answering(provider, 'judge')}
									<button
										type="button"
										class="provider-pill"
										class:selected={judgeProvider === provider}
										aria-pressed={judgeProvider === provider}
										disabled={!canAnswer}
										onclick={() => selectJudgeProvider(provider)}
									>
										<span class="name">{providerLabel(provider)}</span>
										<span
											class="pill-status"
											class:status-ok={canAnswer}
											class:status-bad={!canAnswer}
										>
											{canAnswer ? PROVIDER_CONFIGURED_LABEL : pickerStatus(provider, 'judge')}
										</span>
										{#if !canAnswer}
											<span class="pill-reason">{pickerReason(provider, 'judge')}</span>
										{/if}
									</button>
								{/each}
							</div>
						</div>
						<div class="claude-field">
							<label for="judge-model">Model</label>
							<select id="judge-model" bind:value={judgeModel} disabled={judgeModels.length === 0}>
								{#if judgeModels.length === 0 && judgeModel}
									<option value={judgeModel}>{judgeModel} (current — live list unavailable)</option>
								{/if}
								{#each judgeModels as model (model)}
									<option value={model}>{model}</option>
								{/each}
							</select>
							{#if judgeModelsError}
								<p class="hint">{judgeModelsError}</p>
							{/if}
						</div>
						<div class="btn-row">
							<button class="save-btn" onclick={handleSaveJudge} disabled={!judgeCanSave}>
								{savingJudge ? 'Saving...' : 'Save Scoring'}
							</button>
							<span class="save-reason"
								>{judgeDirty ? 'Changed, not saved yet.' : 'Nothing changed.'}</span
							>
						</div>
					</div>
				{:else}
					<p>Loading...</p>
				{/if}
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

<style>
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

	.claude-form {
		display: flex;
		flex-direction: column;
		gap: 1rem;
		max-width: 400px;
	}

	.claude-field {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.claude-field label,
	.claude-field .field-label {
		font-size: 0.8rem;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		font-family: var(--font-display);
	}

	.claude-field select {
		padding: var(--input-padding);
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: var(--input-radius);
		color: var(--text);
		font-size: var(--input-font-size);
		font-family: var(--font-body);
	}

	.claude-field select:focus {
		border-color: var(--accent);
		outline: none;
		box-shadow: 0 0 8px rgba(160, 32, 240, 0.2);
	}

	.provider-status-list {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		max-width: 460px;
	}

	.provider-status-row {
		display: flex;
		align-items: flex-start;
		gap: 0.5rem;
		padding: 0.4rem 0.55rem;
		border-radius: var(--input-radius);
		background: var(--surface);
	}

	.provider-status-row .dot {
		flex-shrink: 0;
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 50%;
		margin-top: 0.35rem;
		background: var(--score-bad);
	}

	.provider-status-row.ok .dot {
		background: var(--score-good);
	}

	.provider-status-row.partial .dot {
		background: var(--score-ok);
	}

	.provider-status-row.unverified .dot {
		border-radius: 0;
		transform: rotate(45deg);
	}

	.provider-status-row .name {
		font-family: var(--font-display);
		font-weight: 600;
		letter-spacing: 0.02em;
		font-size: 0.86rem;
		color: var(--text);
		display: inline-block;
		min-width: 64px;
	}

	.provider-status-row .detail {
		font-size: 0.76rem;
		color: var(--text-muted);
		display: block;
	}

	.provider-status-row.bad .detail {
		color: var(--score-bad);
	}

	.provider-status-row.partial .detail {
		color: var(--score-ok);
	}

	.active-banner {
		display: flex;
		align-items: flex-start;
		gap: 0.55rem;
		padding: 0.6rem 0.75rem;
		border-radius: var(--input-radius);
		font-size: 0.86rem;
		line-height: 1.4;
		background: var(--surface);
		border: 1px solid var(--border);
	}

	.active-banner .dot {
		flex-shrink: 0;
		width: 0.55rem;
		height: 0.55rem;
		border-radius: 50%;
		margin-top: 0.3rem;
		background: var(--score-good);
	}

	.active-banner b {
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-size: 0.78rem;
		display: block;
		margin-bottom: 0.15rem;
		color: var(--text-muted);
	}

	.active-banner .model {
		font-family: ui-monospace, monospace;
		font-size: 0.82rem;
		color: var(--text);
	}

	.provider-picker {
		display: flex;
		gap: 0.5rem;
		flex-wrap: wrap;
	}

	.route-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 0.7rem;
	}

	.route-card {
		border: 1px solid var(--border);
		border-radius: var(--input-radius);
		padding: 0.65rem;
		background: var(--surface);
		min-width: 0;
	}

	.route-card.selected {
		border-color: var(--primary);
		box-shadow: 0 0 0 1px var(--primary) inset;
	}

	.route-card.unavailable {
		opacity: 0.72;
	}

	.route-card-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.4rem;
		margin-bottom: 0.5rem;
	}

	.route-provider {
		border: 0;
		padding: 0;
		background: transparent;
		font-family: var(--font-display);
		font-weight: 600;
		letter-spacing: 0.03em;
		color: var(--text);
		cursor: pointer;
		text-align: left;
	}

	.route-provider.selected {
		color: var(--primary);
	}

	.route-switch {
		display: inline-flex;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-pill);
		padding: 0.12rem;
		background: var(--bg);
		flex-shrink: 0;
	}

	.route-switch button {
		border: 0;
		border-radius: var(--btn-radius-pill);
		background: transparent;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 0.68rem;
		letter-spacing: var(--btn-letter-spacing);
		padding: 0.13rem 0.35rem;
		cursor: pointer;
	}

	.route-switch button.selected {
		background: var(--primary);
		color: white;
	}

	.route-status-list {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}

	.route-status {
		display: grid;
		grid-template-columns: 0.5rem minmax(0, 1fr);
		gap: 0.35rem;
		align-items: start;
		font-size: 0.72rem;
		line-height: 1.35;
	}

	.route-status .dot {
		width: 0.48rem;
		height: 0.48rem;
		margin-top: 0.28rem;
		border-radius: 50%;
		background: var(--text-muted);
	}

	.route-status.ready .dot {
		background: var(--score-good);
	}

	.route-status.broken .dot {
		background: var(--score-bad);
	}

	.route-status.not-set-up .dot {
		border: 1px solid var(--text-muted);
		background: transparent;
	}

	.route-status.unavailable .dot {
		background: var(--text-muted);
	}

	.route-status strong {
		font-weight: 600;
		color: var(--text);
	}

	.route-status small {
		display: block;
		color: var(--text-muted);
	}

	.route-status.broken small {
		color: var(--score-bad);
	}

	.route-model {
		margin-top: 0.55rem;
	}

	.route-model label {
		display: block;
		margin-bottom: 0.25rem;
		font-size: 0.72rem;
		color: var(--text-muted);
	}

	.route-model select {
		width: 100%;
	}

	.route-model .hint {
		margin: 0.3rem 0 0;
		font-size: 0.67rem;
	}

	.blocked-banner {
		display: flex;
		gap: 0.45rem;
		align-items: flex-start;
		padding: 0.55rem 0.65rem;
		background: var(--surface);
		border: 1px solid var(--score-bad);
		border-radius: var(--input-radius);
		font-size: 0.76rem;
		color: var(--score-bad);
	}

	.provider-pill {
		flex: 1 1 90px;
		border: 1px solid var(--border);
		border-radius: var(--input-radius);
		padding: 0.5rem 0.6rem;
		font-size: 0.82rem;
		background: var(--bg);
		color: var(--text-muted);
		cursor: pointer;
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		min-width: 0;
		text-align: left;
		font-family: var(--font-body);
	}

	.provider-pill .name {
		font-family: var(--font-display);
		font-weight: 600;
		letter-spacing: 0.03em;
		color: var(--text);
	}

	.provider-pill.selected {
		border-color: var(--primary);
		box-shadow: 0 0 0 1px var(--primary) inset;
	}

	.provider-pill.selected .name {
		color: var(--primary);
	}

	.provider-pill:disabled {
		opacity: 0.55;
		cursor: not-allowed;
		background: var(--surface);
	}

	.pill-status {
		font-size: 0.66rem;
		font-weight: 500;
	}

	.status-ok {
		color: var(--score-good);
	}

	.status-bad {
		color: var(--score-bad);
	}

	.pill-reason {
		font-size: 0.66rem;
		color: var(--text-subtle);
		line-height: 1.3;
	}

	.change-banner {
		display: flex;
		gap: 0.5rem;
		align-items: flex-start;
		padding: 0.6rem 0.7rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--input-radius);
		font-size: 0.78rem;
		color: var(--text-muted);
	}

	.btn-row {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex-wrap: wrap;
	}

	.save-reason {
		font-size: 0.74rem;
		color: var(--text-subtle);
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

	@media (max-width: 760px) {
		.route-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
