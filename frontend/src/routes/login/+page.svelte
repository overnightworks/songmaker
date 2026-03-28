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
			<h1 class="logo" data-text="Hallucinai">Hallucinai</h1>
			<p class="tagline">it's hallucination time</p>
		</div>
		<div class="waveform">
			{#each Array(32) as _, i}
				<div class="bar" style="--i: {i}; --h: {20 + Math.sin(i * 0.4) * 15 + Math.random() * 10}"></div>
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
			{#if $authError}
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
		background: #050508;
		position: relative;
		overflow: hidden;
	}

	/* Animated background grid */
	.bg-grid {
		position: absolute;
		inset: 0;
		background-image:
			linear-gradient(rgba(255, 50, 32, 0.03) 1px, transparent 1px),
			linear-gradient(90deg, rgba(255, 50, 32, 0.03) 1px, transparent 1px);
		background-size: 40px 40px;
		animation: grid-drift 20s linear infinite;
	}

	@keyframes grid-drift {
		0% { transform: translate(0, 0); }
		100% { transform: translate(40px, 40px); }
	}

	/* Floating glows */
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
		background: #ff3220;
		top: -100px;
		right: -100px;
		animation: float-1 12s ease-in-out infinite;
	}

	.glow-2 {
		width: 300px;
		height: 300px;
		background: #a020f0;
		bottom: -50px;
		left: -50px;
		animation: float-2 15s ease-in-out infinite;
	}

	.glow-3 {
		width: 250px;
		height: 250px;
		background: #ff6040;
		top: 40%;
		left: 60%;
		animation: float-3 18s ease-in-out infinite;
	}

	@keyframes float-1 {
		0%, 100% { transform: translate(0, 0) scale(1); }
		33% { transform: translate(-60px, 40px) scale(1.1); }
		66% { transform: translate(30px, -20px) scale(0.9); }
	}

	@keyframes float-2 {
		0%, 100% { transform: translate(0, 0) scale(1); }
		33% { transform: translate(50px, -30px) scale(1.2); }
		66% { transform: translate(-20px, 50px) scale(0.95); }
	}

	@keyframes float-3 {
		0%, 100% { transform: translate(0, 0) scale(1); opacity: 0.15; }
		50% { transform: translate(-40px, 30px) scale(1.1); opacity: 0.08; }
	}

	/* Card */
	.login-card {
		background: rgba(13, 13, 13, 0.85);
		border: 1px solid rgba(255, 50, 32, 0.15);
		border-radius: 12px;
		padding: 2.5rem 2rem 2rem;
		width: 380px;
		backdrop-filter: blur(20px);
		position: relative;
		z-index: 1;
		box-shadow: 0 0 60px rgba(255, 50, 32, 0.05);
	}

	/* Logo with glitch effect */
	.logo-area {
		text-align: center;
		margin-bottom: 1.2rem;
	}

	.logo {
		font-family: var(--font-display);
		font-size: 2.4rem;
		text-transform: uppercase;
		letter-spacing: 0.15em;
		color: #fff;
		position: relative;
		display: inline-block;
		animation: glow-pulse 4s ease-in-out infinite;
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
		color: #ff3220;
		animation: glitch-1 3s infinite;
		clip-path: inset(0 0 65% 0);
		opacity: 0.8;
	}

	.logo::after {
		color: #a020f0;
		animation: glitch-2 3s infinite;
		clip-path: inset(65% 0 0 0);
		opacity: 0.8;
	}

	@keyframes glitch-1 {
		0%, 90%, 100% { transform: translate(0); }
		92% { transform: translate(2px, -1px); }
		94% { transform: translate(-2px, 1px); }
		96% { transform: translate(1px, 0); }
	}

	@keyframes glitch-2 {
		0%, 88%, 100% { transform: translate(0); }
		90% { transform: translate(-2px, 1px); }
		93% { transform: translate(2px, -1px); }
		95% { transform: translate(-1px, 0); }
	}

	@keyframes glow-pulse {
		0%, 100% { text-shadow: 0 0 20px rgba(255, 50, 32, 0.3); }
		50% { text-shadow: 0 0 40px rgba(255, 50, 32, 0.5), 0 0 80px rgba(160, 32, 240, 0.2); }
	}

	.tagline {
		font-family: var(--font-body);
		font-size: 0.75rem;
		color: var(--text-dim);
		letter-spacing: 0.3em;
		margin-top: 0.3rem;
		font-style: italic;
	}

	/* Waveform visualizer */
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
		background: linear-gradient(to top, #ff3220, #a020f0);
		border-radius: 2px;
		height: calc(var(--h) * 1%);
		animation: wave 1.5s ease-in-out infinite;
		animation-delay: calc(var(--i) * 0.05s);
	}

	@keyframes wave {
		0%, 100% { transform: scaleY(1); opacity: 0.4; }
		50% { transform: scaleY(0.3); opacity: 0.8; }
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
		color: var(--text-dim);
		text-transform: uppercase;
		letter-spacing: 0.1em;
		font-family: var(--font-display);
	}

	input {
		background: rgba(0, 0, 0, 0.5);
		border: 1px solid rgba(255, 255, 255, 0.08);
		border-radius: 6px;
		color: var(--text);
		padding: 0.7rem 0.9rem;
		font-size: 0.9rem;
		font-family: var(--font-body);
		width: 100%;
		transition: border-color 0.2s, box-shadow 0.2s;
	}

	input::placeholder {
		color: var(--text-dim);
		font-style: italic;
	}

	input:focus {
		outline: none;
		border-color: rgba(255, 50, 32, 0.5);
		box-shadow: 0 0 20px rgba(255, 50, 32, 0.1);
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
		background: linear-gradient(135deg, #ff3220, #cc2018);
		color: white;
		border: none;
		border-radius: 6px;
		padding: 0.75rem;
		font-size: 0.9rem;
		font-weight: 600;
		cursor: pointer;
		margin-top: 0.5rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.15em;
		transition: transform 0.15s, box-shadow 0.15s;
		position: relative;
		overflow: hidden;
	}

	.submit-btn::after {
		content: '';
		position: absolute;
		inset: 0;
		background: linear-gradient(135deg, transparent 40%, rgba(255, 255, 255, 0.1) 50%, transparent 60%);
		transform: translateX(-100%);
		animation: shimmer 3s ease-in-out infinite;
	}

	@keyframes shimmer {
		0%, 70%, 100% { transform: translateX(-100%); }
		80% { transform: translateX(100%); }
	}

	.submit-btn:hover:not(:disabled) {
		transform: translateY(-1px);
		box-shadow: 0 4px 20px rgba(255, 50, 32, 0.3);
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
		background: rgba(255, 68, 68, 0.08);
		border-radius: 4px;
		border: 1px solid rgba(255, 68, 68, 0.15);
	}

	.legal-links {
		text-align: center;
		margin-top: 1.5rem;
		font-size: 0.7rem;
		position: relative;
		z-index: 1;
	}

	.legal-links a {
		color: var(--text-dim);
		text-decoration: none;
		transition: color 0.2s;
	}

	.legal-links a:hover {
		color: var(--text-muted);
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
