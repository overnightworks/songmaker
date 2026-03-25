<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { changePassword } from '$lib/api/client';
	import { currentUser } from '$lib/stores/auth';

	let current = $state('');
	let newPass = $state('');
	let confirm = $state('');
	let showPassword = $state(false);
	let submitting = $state(false);
	let error = $state('');
	let success = $state('');

	const me = $derived($currentUser);

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		error = '';
		success = '';

		if (newPass !== confirm) {
			error = 'Passwords do not match.';
			return;
		}

		submitting = true;
		try {
			await changePassword(current, newPass);
			success = 'Password changed.';
			current = '';
			newPass = '';
			confirm = '';
		} catch (err) {
			if (err instanceof Error && err.message.includes('401')) {
				error = 'Current password is incorrect.';
			} else {
				error = err instanceof Error ? err.message : 'Failed';
			}
		} finally {
			submitting = false;
		}
	}
</script>

<div class="settings-page">
	<header>
		<h1>Account</h1>
		<nav>
			<a href="/">Back</a>
			{#if me?.role === 'admin'}
				<a href="/settings/users">Admin</a>
			{/if}
		</nav>
	</header>

	<section>
		<h2>Change Password</h2>
		<p class="info">Logged in as <strong>{me?.username}</strong> ({me?.role})</p>
		<form onsubmit={handleSubmit}>
			<label>
				Current Password
				<div class="pw-field">
					<input
						type={showPassword ? 'text' : 'password'}
						bind:value={current}
						required
						autocomplete="current-password"
						disabled={submitting}
					/>
					<button
						type="button"
						class="pw-toggle"
						onclick={() => (showPassword = !showPassword)}
						tabindex="-1"
					>
						{showPassword ? '🙈' : '👁'}
					</button>
				</div>
			</label>
			<label>
				New Password
				<input
					type={showPassword ? 'text' : 'password'}
					bind:value={newPass}
					minlength={8}
					required
					autocomplete="new-password"
					disabled={submitting}
				/>
			</label>
			<label>
				Confirm New Password
				<input
					type={showPassword ? 'text' : 'password'}
					bind:value={confirm}
					minlength={8}
					required
					autocomplete="new-password"
					disabled={submitting}
				/>
			</label>
			{#if error}
				<p class="error">{error}</p>
			{/if}
			{#if success}
				<p class="success">{success}</p>
			{/if}
			<button type="submit" disabled={submitting}>
				{submitting ? 'Changing...' : 'Change Password'}
			</button>
		</form>
	</section>
</div>

<style>
	.settings-page {
		flex: 1;
		padding: 2rem;
		max-width: 500px;
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

	h2 {
		font-size: 1rem;
		color: var(--text-muted);
		margin-bottom: 0.5rem;
	}

	.info {
		color: var(--text-muted);
		font-size: 0.85rem;
		margin-bottom: 1rem;
	}

	form {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	label {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		font-size: 0.85rem;
		color: var(--text-muted);
	}

	input {
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		padding: 0.6rem 0.8rem;
		font-size: 0.95rem;
		width: 100%;
		font-family: var(--font-body);
	}

	.pw-field {
		position: relative;
	}

	.pw-field input {
		padding-right: 2.5rem;
	}

	.pw-toggle {
		position: absolute;
		right: 6px;
		top: 50%;
		transform: translateY(-50%);
		background: none;
		border: none;
		cursor: pointer;
		font-size: 1rem;
		padding: 2px 4px;
		color: var(--text-muted);
	}

	input:focus {
		outline: none;
		border-color: var(--primary);
	}

	input:disabled {
		opacity: 0.5;
	}

	button {
		background: var(--primary);
		color: white;
		border: none;
		border-radius: 4px;
		padding: 0.7rem;
		font-size: 0.95rem;
		font-weight: 600;
		cursor: pointer;
		margin-top: 0.5rem;
		font-family: var(--font-body);
	}

	button:hover:not(:disabled) {
		filter: brightness(1.1);
	}

	button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.error {
		color: var(--score-bad);
		font-size: 0.85rem;
	}

	.success {
		color: var(--score-good);
		font-size: 0.85rem;
	}
</style>
