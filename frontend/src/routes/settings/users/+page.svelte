<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { onMount } from 'svelte';
	import {
		fetchUsers,
		createUser,
		updateUser,
		fetchSessions,
		forceLogout,
		fetchLoginAttempts,
		getAceStepStatus,
		reinitializeAceStep
	} from '$lib/api/client';
	import type { UserItem, SessionItem, LoginAttemptItem } from '$lib/api/types';
	import { currentUser, isAdmin } from '$lib/stores/auth';

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
	let tab = $state<'users' | 'sessions' | 'attempts' | 'acestep'>('users');
	let reinitializing = $state(false);

	let newUsername = $state('');
	let newPassword = $state('');
	let newRole = $state('user');
	let creating = $state(false);

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
</script>

{#if !admin}
	<div class="denied">Admin access required.</div>
{:else}
	<div class="settings-page">
		<header>
			<h1>Admin</h1>
			<nav>
				<a href="/">Back</a>
				<a href="/settings/account">Account</a>
			</nav>
		</header>

		<div class="tabs">
			<button class:active={tab === 'users'} onclick={() => (tab = 'users')}>Users</button>
			<button class:active={tab === 'sessions'} onclick={() => (tab = 'sessions')}>Sessions</button>
			<button class:active={tab === 'attempts'} onclick={() => (tab = 'attempts')}
				>Login Attempts</button
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

	header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 1.5rem;
	}

	header h1 {
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--primary);
		font-size: 1.5rem;
	}

	nav {
		display: flex;
		gap: 1rem;
	}

	nav a {
		color: var(--text-muted);
		text-decoration: none;
		font-size: 0.85rem;
	}

	nav a:hover {
		color: var(--text);
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
		font-family: var(--font-body);
		font-size: 0.9rem;
	}

	.tabs button.active {
		color: var(--text);
		border-bottom-color: var(--primary);
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
		background: var(--primary);
		color: white;
		border: none;
		border-radius: 4px;
		padding: 0.5rem 1rem;
		cursor: pointer;
		font-family: var(--font-body);
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
		background: var(--primary);
		color: white;
		border: none;
		border-radius: 4px;
		padding: 0.5rem 1rem;
		font-size: 0.85rem;
		cursor: pointer;
		font-family: var(--font-body);
	}

	.reinit-btn:hover:not(:disabled) {
		filter: brightness(1.1);
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
</style>
