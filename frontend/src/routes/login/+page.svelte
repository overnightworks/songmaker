<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { goto } from '$app/navigation';
	import { APP_NAME } from '$lib/constants';
	import { AUTH_ACCOUNT_DISABLED_MESSAGE, AUTH_SESSION_EXPIRED_MESSAGE } from '$lib/constants/auth';
	import { login, authError, authNotice } from '$lib/stores/auth';

	let username = $state('');
	let password = $state('');
	let showPassword = $state(false);
	let submitting = $state(false);

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		submitting = true;
		try {
			await login(username, password);
			await goto('/', { replaceState: true });
		} catch {
			// error is set in the store
		} finally {
			submitting = false;
		}
	}
</script>

<div class="login-page">
	<div class="bg-grid"></div>
	<div class="bg-glow glow-1"></div>
	<div class="bg-glow glow-2"></div>
	<div class="bg-glow glow-3"></div>

	<div class="login-card">
		<div class="logo-area">
			<h1 class="logo" data-text={APP_NAME}>{APP_NAME}</h1>
			<p class="tagline">it's hallucination time</p>
		</div>
		<div class="waveform">
			{#each Array(32) as _, i (i)}
				<div class="bar" style="--h: {20 + Math.sin(i * 0.4) * 15 + Math.random() * 10}"></div>
			{/each}
		</div>
		<form onsubmit={handleSubmit}>
			<label>
				<span class="label-text">Username</span>
				<input
					type="text"
					bind:value={username}
					minlength={3}
					required
					autocomplete="username"
					disabled={submitting}
					placeholder="enter the void..."
				/>
			</label>
			<label>
				<span class="label-text">Password</span>
				<div class="pw-field">
					<input
						type={showPassword ? 'text' : 'password'}
						bind:value={password}
						minlength={8}
						required
						autocomplete="current-password"
						disabled={submitting}
						placeholder="••••••••"
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
			{#if $authNotice === 'disabled'}
				<p class="error">{AUTH_ACCOUNT_DISABLED_MESSAGE}</p>
			{:else if $authNotice === 'unauthorized'}
				<p class="error">{AUTH_SESSION_EXPIRED_MESSAGE}</p>
			{:else if $authError}
				<p class="error">{$authError}</p>
			{/if}
			<button type="submit" class="submit-btn" disabled={submitting}>
				{submitting ? 'Entering...' : 'Enter'}
			</button>
		</form>
	</div>
	<p class="legal-links">
		<a href="/legal#impressum">Impressum</a> · <a href="/legal#datenschutz">Datenschutz</a>
	</p>
</div>

<style>
	.login-page {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100dvh;
		background: var(--bg-deep);
		position: relative;
		overflow: hidden;
	}

	/* Background grid */
	.bg-grid {
		position: absolute;
		inset: 0;
		background-image:
			linear-gradient(var(--glow-primary) 1px, transparent 1px),
			linear-gradient(90deg, var(--glow-primary) 1px, transparent 1px);
		background-size: 40px 40px;
	}

	/* Background glows */
	.bg-glow {
		position: absolute;
		border-radius: 50%;
		filter: blur(80px);
		opacity: 0.15;
		pointer-events: none;
	}

	.glow-1 {
		width: 400px;
		height: 400px;
		background: var(--primary);
		top: -100px;
		right: -100px;
	}

	.glow-2 {
		width: 300px;
		height: 300px;
		background: var(--accent);
		bottom: -50px;
		left: -50px;
	}

	.glow-3 {
		width: 250px;
		height: 250px;
		background: color-mix(in srgb, var(--primary) 70%, var(--accent));
		top: 40%;
		left: 60%;
	}

	/* Card */
	.login-card {
		background: var(--card-bg);
		border: 1px solid color-mix(in srgb, var(--primary) 15%, transparent);
		border-radius: 12px;
		padding: 2.5rem 2rem 2rem;
		width: 380px;
		backdrop-filter: blur(20px);
		position: relative;
		z-index: 1;
		box-shadow: 0 0 60px color-mix(in srgb, var(--primary) 5%, transparent);
	}

	/* Logo with static split-color effect */
	.logo-area {
		text-align: center;
		margin-bottom: 1.2rem;
	}

	.logo {
		font-family: var(--font-display);
		font-size: 2.4rem;
		text-transform: uppercase;
		letter-spacing: 0.15em;
		color: var(--text);
		position: relative;
		display: inline-block;
		text-shadow: 0 0 20px color-mix(in srgb, var(--primary) 30%, transparent);
	}

	.logo::before,
	.logo::after {
		content: attr(data-text);
		position: absolute;
		top: 0;
		left: 0;
		width: 100%;
		height: 100%;
		pointer-events: none;
	}

	.logo::before {
		color: var(--primary);
		clip-path: inset(0 0 65% 0);
		opacity: 0.8;
	}

	.logo::after {
		color: var(--accent);
		clip-path: inset(65% 0 0 0);
		opacity: 0.8;
	}

	.tagline {
		font-family: var(--font-body);
		font-size: 0.75rem;
		color: var(--text-subtle);
		letter-spacing: 0.3em;
		margin-top: 0.3rem;
		font-style: italic;
	}

	/* Static waveform motif */
	.waveform {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 2px;
		height: 32px;
		margin-bottom: 1.5rem;
		opacity: 0.4;
	}

	.bar {
		width: 3px;
		background: linear-gradient(to top, var(--primary), var(--accent));
		border-radius: 2px;
		height: calc(var(--h) * 1%);
	}

	/* Form */
	form {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	label {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}

	.label-text {
		font-size: 0.75rem;
		color: var(--text-subtle);
		text-transform: uppercase;
		letter-spacing: 0.1em;
		font-family: var(--font-display);
	}

	input {
		background: color-mix(in srgb, var(--bg) 80%, transparent);
		border: 1px solid var(--border);
		border-radius: var(--input-radius);
		color: var(--text);
		padding: var(--input-padding);
		font-size: 0.9rem;
		font-family: var(--font-body);
		width: 100%;
		transition:
			border-color 0.2s,
			box-shadow 0.2s;
	}

	input::placeholder {
		color: var(--text-subtle);
		font-style: italic;
	}

	input:focus {
		outline: none;
		border-color: color-mix(in srgb, var(--primary) 50%, transparent);
		box-shadow: 0 0 20px color-mix(in srgb, var(--primary) 10%, transparent);
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

	.submit-btn {
		background: linear-gradient(
			135deg,
			var(--primary),
			color-mix(in srgb, var(--primary) 80%, black)
		);
		color: white;
		border: none;
		border-radius: var(--btn-radius-pill);
		padding: var(--btn-padding-pill);
		font-size: var(--btn-font-size);
		font-weight: 600;
		cursor: pointer;
		margin-top: 0.5rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: var(--btn-letter-spacing);
		transition:
			transform 0.15s,
			box-shadow 0.15s;
	}

	.submit-btn:hover:not(:disabled) {
		transform: translateY(-1px);
		box-shadow: 0 4px 20px color-mix(in srgb, var(--primary) 30%, transparent);
	}

	.submit-btn:active:not(:disabled) {
		transform: translateY(0);
	}

	.submit-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.error {
		color: var(--score-bad);
		font-size: 0.8rem;
		text-align: center;
		padding: 0.4rem 0.8rem;
		background: color-mix(in srgb, var(--score-bad) 8%, transparent);
		border-radius: 4px;
		border: 1px solid color-mix(in srgb, var(--score-bad) 15%, transparent);
	}

	.legal-links {
		text-align: center;
		margin-top: 1.5rem;
		font-size: 0.7rem;
		position: relative;
		z-index: 1;
	}

	.legal-links a {
		color: var(--text-subtle);
		text-decoration: none;
		transition: color 0.2s;
	}

	.legal-links a:hover {
		color: var(--text-muted);
	}

	@media (prefers-reduced-motion: reduce) {
		.login-page,
		.login-page *,
		.login-page *::before,
		.login-page *::after {
			animation: none !important;
			transition: none !important;
			scroll-behavior: auto !important;
		}

		.submit-btn:hover:not(:disabled),
		.submit-btn:active:not(:disabled) {
			transform: none;
			box-shadow: none;
		}
	}

	@media (max-width: 480px) {
		.login-card {
			width: calc(100vw - 2rem);
			padding: 2rem 1.5rem 1.5rem;
		}

		.logo {
			font-size: 1.8rem;
		}
	}
</style>
