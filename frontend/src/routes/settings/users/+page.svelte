<script lang="ts">
	import { onMount } from 'svelte';
	import {
		fetchUsers,
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
		UserRateLimitsResponse
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
	import type { CowriterSettings, JudgeSettings, ProviderStatus } from '$lib/api/types';
	import type { VersionGenerationParams } from '$lib/api/types';
	import ParamControls from '$lib/components/ParamControls.svelte';
	import WorkerPoolPanel from '$lib/components/WorkerPoolPanel.svelte';
	import ModelRegistryPanel from '$lib/components/ModelRegistryPanel.svelte';
	import { ADMIN_TABS_LABEL } from '$lib/constants';
	import {
		COMPACT_SELECT_CLASS,
		COMPACT_STACK_CLASS,
		ensureCompactUiStyles
	} from '$lib/styles/compact-ui';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';

	let users = $state<UserItem[]>([]);
	let sessions = $state<SessionItem[]>([]);
	let attempts = $state<LoginAttemptItem[]>([]);
	let error = $state('');
	let compact = $state(false);

	const ADMIN_TABS = [
		{ id: 'users', label: 'Users' },
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

	let cowriterSettings = $state<CowriterSettings | null>(null);
	let cowriterProvider = $state('claude');
	let cowriterModel = $state('');
	let cowriterBudget = $state(0);
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

	function providerDetail(status: ProviderStatus): string {
		if (!status.configured) {
			return `not configured — missing ${status.environment_key}`;
		}
		if (status.setup_method === 'claude_cli') {
			return 'configured — Claude Code CLI login';
		}
		return `configured — ${status.environment_key} set`;
	}

	const configuredProviders = $derived(
		new Set(providerStatuses.filter((status) => status.configured).map((s) => s.provider))
	);

	async function loadModelsTab() {
		try {
			providerStatuses = await fetchProviderStatus();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load provider status';
		}
		try {
			cowriterSettings = await fetchCowriterSettings();
			cowriterProvider = cowriterSettings.provider;
			cowriterModel = cowriterSettings.model;
			cowriterBudget = cowriterSettings.tail_token_budget;
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

	const cowriterModels = $derived(cowriterSettings?.models_by_provider?.[cowriterProvider] ?? []);
	const cowriterModelsError = $derived(cowriterSettings?.models_errors?.[cowriterProvider]);
	const cowriterDirty = $derived(
		cowriterSettings !== null &&
			(cowriterProvider !== cowriterSettings.provider ||
				cowriterModel !== cowriterSettings.model ||
				cowriterBudget !== cowriterSettings.tail_token_budget)
	);
	const cowriterCanSave = $derived(cowriterDirty && cowriterModel !== '' && !savingCowriter);

	const judgeModels = $derived(judgeSettings?.models_by_provider?.[judgeProvider] ?? []);
	const judgeModelsError = $derived(judgeSettings?.models_errors?.[judgeProvider]);
	const judgeDirty = $derived(
		judgeSettings !== null &&
			(judgeProvider !== judgeSettings.provider || judgeModel !== judgeSettings.model)
	);
	const judgeCanSave = $derived(judgeDirty && judgeModel !== '' && !savingJudge);

	function selectCowriterProvider(provider: string): void {
		cowriterProvider = provider;
		if (cowriterSettings && provider === cowriterSettings.provider) {
			cowriterModel = cowriterSettings.model;
			return;
		}
		const models = cowriterSettings?.models_by_provider?.[provider] ?? [];
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
				cowriterBudget
			);
			cowriterProvider = cowriterSettings.provider;
			cowriterModel = cowriterSettings.model;
			cowriterBudget = cowriterSettings.tail_token_budget;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to save co-writer settings';
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
			error = e instanceof Error ? e.message : 'Failed to save scoring settings';
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
				<p class="hint">
					Each provider's real reachability — configured and by what means, or not configured and
					what's missing.
				</p>
				{#if providerStatuses.length > 0}
					<div class="provider-status-list">
						{#each providerStatuses as status (status.provider)}
							<div
								class="provider-status-row"
								class:ok={status.configured}
								class:bad={!status.configured}
							>
								<span class="dot"></span>
								<span>
									<span class="name">{providerLabel(status.provider)}</span>
									<span class="detail">{providerDetail(status)}</span>
								</span>
							</div>
						{/each}
					</div>
				{:else}
					<p>Loading...</p>
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
								<b>{cowriterDirty ? 'Still active' : 'Active'}</b>
								<span class="model"
									>{providerLabel(cowriterSettings.provider)} · {cowriterSettings.model}</span
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
						<div class="claude-field">
							<span class="field-label" id="cowriter-provider-label">Provider</span>
							<div class="provider-picker" role="group" aria-labelledby="cowriter-provider-label">
								{#each cowriterSettings.allowed_providers as provider (provider)}
									{@const configured = configuredProviders.has(provider)}
									<button
										type="button"
										class="provider-pill"
										class:selected={cowriterProvider === provider}
										aria-pressed={cowriterProvider === provider}
										disabled={!configured}
										onclick={() => selectCowriterProvider(provider)}
									>
										<span class="name">{providerLabel(provider)}</span>
										<span
											class="pill-status"
											class:status-ok={configured}
											class:status-bad={!configured}
										>
											{configured ? 'configured' : 'not configured'}
										</span>
										{#if !configured}
											<span class="pill-reason"
												>Missing {providerStatusFor(provider)?.environment_key}</span
											>
										{/if}
									</button>
								{/each}
							</div>
						</div>
						<div class="claude-field">
							<label for="cowriter-model">Model</label>
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
									<option value={model}>{model}</option>
								{/each}
							</select>
							{#if cowriterModelsError}
								<p class="hint">{cowriterModelsError}</p>
							{/if}
						</div>
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
							<span class="save-reason"
								>{cowriterDirty ? 'Changed, not saved yet.' : 'Nothing changed.'}</span
							>
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
									{@const configured = configuredProviders.has(provider)}
									<button
										type="button"
										class="provider-pill"
										class:selected={judgeProvider === provider}
										aria-pressed={judgeProvider === provider}
										disabled={!configured}
										onclick={() => selectJudgeProvider(provider)}
									>
										<span class="name">{providerLabel(provider)}</span>
										<span
											class="pill-status"
											class:status-ok={configured}
											class:status-bad={!configured}
										>
											{configured ? 'configured' : 'not configured'}
										</span>
										{#if !configured}
											<span class="pill-reason"
												>Missing {providerStatusFor(provider)?.environment_key}</span
											>
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
</style>
