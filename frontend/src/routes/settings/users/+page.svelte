<script lang="ts">
	import { onMount } from 'svelte';
	import {
		fetchUsers,
		createUser,
		updateUser,
		fetchSessions,
		forceLogout,
		fetchLoginAttempts,
		getAceStepStatus,
		reinitializeAceStep,
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
		toggleModel as toggleModelApi
	} from '$lib/api/client';
	import type { AvailableModel } from '$lib/api/client';
	import type { VersionGenerationParams } from '$lib/api/types';
	import ParamControls from '$lib/components/ParamControls.svelte';

	let users = $state<UserItem[]>([]);
	let sessions = $state<SessionItem[]>([]);
	let attempts = $state<LoginAttemptItem[]>([]);
	let aceStatus = $state<{
		online: boolean;
		model: string | null;
		lm_model: string | null;
		jobs: Record<string, number>;
	} | null>(null);
	let error = $state('');
	let tab = $state<'users' | 'sessions' | 'attempts' | 'acestep' | 'ratelimits' | 'generation'>(
		'users'
	);
	let reinitializing = $state(false);

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
			const [u, s, a, ace] = await Promise.all([
				fetchUsers(),
				fetchSessions(),
				fetchLoginAttempts(0, 50),
				getAceStepStatus()
			]);
			users = u;
			sessions = s.items;
			attempts = a.items;
			aceStatus = ace;
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

	async function handleReinitialize() {
		reinitializing = true;
		error = '';
		try {
			await reinitializeAceStep();
			aceStatus = await getAceStepStatus();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Reinitialize failed';
		} finally {
			reinitializing = false;
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

		<div class="tabs">
			<button class:active={tab === 'users'} onclick={() => (tab = 'users')}>Users</button>
			<button class:active={tab === 'sessions'} onclick={() => (tab = 'sessions')}>Sessions</button>
			<button class:active={tab === 'attempts'} onclick={() => (tab = 'attempts')}
				>Login Attempts</button
			>
			<button
				class:active={tab === 'ratelimits'}
				onclick={() => {
					tab = 'ratelimits';
					loadGlobalLimits();
				}}>Rate Limits</button
			>
			<button
				class:active={tab === 'generation'}
				onclick={() => {
					tab = 'generation';
					loadGenDefaults();
				}}>Generation</button
			>
			<button class:active={tab === 'acestep'} onclick={() => (tab = 'acestep')}>ACE-Step</button>
		</div>

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
				<table>
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
								<td>{user.username}</td>
								<td>
									<span class="badge" class:admin-badge={user.role === 'admin'}>
										{user.role}
									</span>
								</td>
								<td>{user.is_active ? 'Yes' : 'No'}</td>
								<td>{user.created_at ? new Date(user.created_at).toLocaleDateString() : ''}</td>
								<td class="actions">
									{#if me && user.id !== me.id}
										<button class="small" onclick={() => handleToggleRole(user)}>
											{user.role === 'admin' ? 'Demote' : 'Promote'}
										</button>
										<button class="small" onclick={() => handleToggleActive(user)}>
											{user.is_active ? 'Disable' : 'Enable'}
										</button>
									{:else}
										<span class="text-muted">You</span>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</section>
		{/if}

		{#if tab === 'sessions'}
			<section>
				<h2>Active Sessions</h2>
				<table>
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
								<td>{sess.username}</td>
								<td>{sess.ip_address}</td>
								<td>{sess.created_at ? new Date(sess.created_at).toLocaleString() : ''}</td>
								<td>{sess.expires_at ? new Date(sess.expires_at).toLocaleString() : ''}</td>
								<td>
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
				<table>
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
								<td>{att.attempted_at ? new Date(att.attempted_at).toLocaleString() : ''}</td>
								<td>{att.username}</td>
								<td>{att.ip_address}</td>
								<td>
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
				<table>
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
								<td>{user.username}</td>
								<td>
									<span class="badge" class:admin-badge={user.role === 'admin'}>
										{user.role}
									</span>
								</td>
								<td>
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

		{#if tab === 'acestep'}
			<section>
				<h2>ACE-Step Server</h2>
				{#if aceStatus}
					<div class="ace-status">
						<div class="ace-row">
							<span class="ace-label">Status</span>
							<span class:online={aceStatus.online} class:offline={!aceStatus.online}>
								{aceStatus.online ? 'Online' : 'Offline'}
							</span>
						</div>
						{#if aceStatus.online}
							<div class="ace-row">
								<span class="ace-label">Model</span>
								<span>{aceStatus.model}</span>
							</div>
							<div class="ace-row">
								<span class="ace-label">LM Model</span>
								<span>{aceStatus.lm_model}</span>
							</div>
							<div class="ace-row">
								<span class="ace-label">Jobs Total</span>
								<span>{aceStatus.jobs.total ?? 0}</span>
							</div>
							<div class="ace-row">
								<span class="ace-label">Jobs Failed</span>
								<span>{aceStatus.jobs.failed ?? 0}</span>
							</div>
						{/if}
					</div>
					<button class="reinit-btn" onclick={handleReinitialize} disabled={reinitializing}>
						{reinitializing ? 'Reinitializing...' : 'Reinitialize ACE-Step'}
					</button>
					<p class="hint">
						Use this if generations fail. Resets the model without restarting the server.
					</p>
				{:else}
					<p>Loading...</p>
				{/if}
			</section>
		{/if}
	</div>
{/if}

<style>
	.settings-page {
		flex: 1;
		padding: 2rem;
		overflow-y: auto;
		max-width: 900px;
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
		letter-spacing: 0.5px;
	}

	.tabs button.active {
		color: var(--primary);
		border-bottom: 2px solid transparent;
		border-image: linear-gradient(90deg, var(--primary), var(--accent)) 1;
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
		border-radius: 4px;
		color: var(--text);
		padding: 0.5rem;
		font-size: 0.85rem;
		font-family: var(--font-body);
	}

	.create-form button {
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: white;
		border: none;
		border-radius: 16px;
		padding: 0.5rem 1rem;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
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

	.ace-status {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		margin-bottom: 1rem;
	}

	.ace-row {
		display: flex;
		gap: 1rem;
		font-size: 0.85rem;
	}

	.ace-label {
		color: var(--text-muted);
		min-width: 100px;
	}

	.online {
		color: var(--score-good);
		font-weight: 600;
	}

	.offline {
		color: var(--score-bad);
		font-weight: 600;
	}

	.reinit-btn {
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: white;
		border: none;
		border-radius: 16px;
		padding: 0.5rem 1rem;
		font-size: 0.85rem;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		transition: box-shadow 0.2s;
	}

	.reinit-btn:hover:not(:disabled) {
		box-shadow: 0 0 16px rgba(160, 32, 240, 0.3);
	}

	.reinit-btn:disabled {
		opacity: 0.5;
		cursor: wait;
	}

	.hint {
		color: var(--text-dim);
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
		align-items: center;
		gap: 1rem;
	}

	.limit-label {
		flex: 1;
		font-size: 0.85rem;
		color: var(--text);
	}

	.effective-val {
		color: var(--text-dim);
		font-size: 0.75rem;
	}

	.limit-input {
		width: 80px;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		padding: 0.35rem 0.5rem;
		font-size: 0.85rem;
		font-family: var(--font-body);
		text-align: right;
	}

	.limit-input::placeholder {
		color: var(--text-dim);
	}

	.save-btn {
		display: inline-block;
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: white;
		border: none;
		border-radius: 16px;
		padding: 0.4rem 1rem;
		font-size: 0.8rem;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		margin-top: 0.5rem;
	}

	.save-btn:hover:not(.disabled) {
		box-shadow: 0 0 16px rgba(160, 32, 240, 0.3);
	}

	.save-btn.disabled {
		opacity: 0.5;
		cursor: wait;
	}

	.clear-btn {
		background: transparent;
		color: var(--text-muted);
		border: 1px solid var(--border);
		border-radius: 16px;
		padding: 0.5rem 1.2rem;
		font-size: 0.85rem;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.clear-btn:hover {
		border-color: var(--text-muted);
		color: var(--text);
	}

	.override-actions {
		display: flex;
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
		gap: 6px;
		margin-bottom: 1rem;
	}

	.gen-model-tab {
		padding: 0.5rem 1.4rem;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: transparent;
		color: var(--text-muted);
		font-size: 0.85rem;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 1px;
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
		border-radius: 4px;
		background: transparent;
		color: var(--text-muted);
		font-size: 0.85rem;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 1px;
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
