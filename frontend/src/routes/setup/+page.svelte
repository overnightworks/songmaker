<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { goto } from '$app/navigation';
	import { setupAdmin } from '$lib/api/client';
	import { APP_NAME } from '$lib/constants';
	import { currentUser } from '$lib/stores/auth';

	let username = $state('');
	let password = $state('');
	let confirmPassword = $state('');
	let showPassword = $state(false);
	let submitting = $state(false);
	let error = $state('');

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		error = '';

		if (password !== confirmPassword) {
			error = 'Passwords do not match.';
			return;
		}

		submitting = true;
		try {
			const user = await setupAdmin(username, password);
			currentUser.set({ id: user.id, username: user.username, role: user.role });
			await goto('/');
		} catch (err) {
			if (err instanceof Error && err.message.includes('403')) {
				error = 'Setup already completed. Please log in.';
			} else {
				error = err instanceof Error ? err.message : 'Setup failed';
			}
		} finally {
			submitting = false;
		}
	}
</script>

<div class="setup-page">
	<div class="setup-card">
		<h1>{APP_NAME}</h1>
		<p class="subtitle">Create your admin account</p>
		<form onsubmit={handleSubmit}>
			<label>
				Username
				<input
					type="text"
					bind:value={username}
					minlength={3}
					required
					autocomplete="username"
					disabled={submitting}
				/>
			</label>
			<label>
				Password
				<div class="pw-field">
					<input
						type={showPassword ? 'text' : 'password'}
						bind:value={password}
						minlength={8}
						required
						autocomplete="new-password"
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
				Confirm Password
				<input
					type={showPassword ? 'text' : 'password'}
					bind:value={confirmPassword}
					minlength={8}
					required
					autocomplete="new-password"
					disabled={submitting}
				/>
			</label>
			{#if error}
				<p class="error">{error}</p>
			{/if}
			<button type="submit" disabled={submitting}>
				{submitting ? 'Creating...' : 'Create Admin Account'}
			</button>
		</form>
	</div>
</div>

<style>
	.setup-page {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100vh;
		background: var(--bg);
	}

	.setup-card {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 2rem;
		width: 360px;
	}

	h1 {
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--primary);
		text-align: center;
		margin-bottom: 0.3rem;
		font-size: 1.8rem;
	}

	.subtitle {
		text-align: center;
		color: var(--text-muted);
		font-size: 0.9rem;
		margin-bottom: 1.5rem;
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
		padding: 0.5rem 0.7rem;
		font-size: 0.95rem;
		font-family: var(--font-body);
		width: 100%;
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
		border-radius: 16px;
		padding: 0.5rem 1.2rem;
		font-size: 0.85rem;
		font-weight: 600;
		cursor: pointer;
		margin-top: 0.5rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
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
		text-align: center;
	}
</style>
