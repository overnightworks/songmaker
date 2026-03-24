<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { goto } from '$app/navigation';
	import { login, authError } from '$lib/stores/auth';

	let username = $state('');
	let password = $state('');
	let showPassword = $state(false);
	let submitting = $state(false);

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		submitting = true;
		try {
			await login(username, password);
			await goto('/');
		} catch {
			// error is set in the store
		} finally {
			submitting = false;
		}
	}
</script>

<div class="login-page">
	<div class="login-card">
		<h1>Songmaker</h1>
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
						autocomplete="current-password"
						disabled={submitting}
					/>
					<button type="button" class="pw-toggle" onclick={() => (showPassword = !showPassword)} tabindex="-1">
						{showPassword ? '🙈' : '👁'}
					</button>
				</div>
			</label>
			{#if $authError}
				<p class="error">{$authError}</p>
			{/if}
			<button type="submit" disabled={submitting}>
				{submitting ? 'Logging in...' : 'Log in'}
			</button>
		</form>
	</div>
</div>

<style>
	.login-page {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100vh;
		background: var(--bg);
	}

	.login-card {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 2rem;
		width: 360px;
	}

	h1 {
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--primary);
		text-align: center;
		margin-bottom: 1.5rem;
		font-size: 1.8rem;
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
		font-family: var(--font-body);
		width: 100%;
	}

	input:focus {
		outline: none;
		border-color: var(--primary);
	}

	input:disabled {
		opacity: 0.5;
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

	button[type='submit'] {
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

	button[type='submit']:hover:not(:disabled) {
		filter: brightness(1.1);
	}

	button[type='submit']:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.error {
		color: var(--score-bad);
		font-size: 0.85rem;
		text-align: center;
	}
</style>
