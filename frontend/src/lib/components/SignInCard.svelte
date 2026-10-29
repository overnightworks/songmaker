<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from '$lib/components/Icon.svelte';
	import LegalLinks from '$lib/components/LegalLinks.svelte';
	import { APP_NAME } from '$lib/constants';

	interface Props {
		heading: string;
		// A refusal the page tells in words beside its warning shape.
		failure?: string;
		// The way on: links and buttons styled with `.sign-in-action`.
		actions: Snippet;
	}

	let { heading, failure, actions }: Props = $props();
</script>

<svelte:head>
	<title>{APP_NAME}</title>
</svelte:head>

<div class="sign-in-page">
	<div class="bg-grid"></div>
	<div class="bg-glow glow-1"></div>
	<div class="bg-glow glow-2"></div>

	<main class="sign-in-card">
		<p class="logo" data-text={APP_NAME}>{APP_NAME}</p>
		<h1>{heading}</h1>
		{#if failure}
			<p class="failure" role="alert">
				<Icon name="triangle-alert" size={18} />
				<span>{failure}</span>
			</p>
		{/if}
		<div class="actions">{@render actions()}</div>
	</main>
	<div class="legal-links">
		<LegalLinks />
	</div>
</div>

<style>
	.sign-in-page {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 100dvh;
		background: var(--bg-deep);
		position: relative;
		overflow: hidden;
	}

	.bg-grid {
		position: absolute;
		inset: 0;
		--glow-primary: color-mix(in srgb, var(--primary) 4%, transparent);
		background-image:
			linear-gradient(var(--glow-primary) 1px, transparent 1px),
			linear-gradient(90deg, var(--glow-primary) 1px, transparent 1px);
		background-size: 40px 40px;
	}

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

	.sign-in-card {
		background: var(--card-bg);
		border: 1px solid color-mix(in srgb, var(--primary) 15%, transparent);
		border-radius: 12px;
		padding: 2.5rem 2rem 2rem;
		width: 380px;
		max-width: calc(100vw - 2rem);
		box-sizing: border-box;
		backdrop-filter: blur(20px);
		position: relative;
		z-index: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1.25rem;
		text-align: center;
		box-shadow: 0 0 60px color-mix(in srgb, var(--primary) 5%, transparent);
	}

	.logo {
		margin: 0;
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
		inset: 0;
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

	h1 {
		margin: 0;
		font-family: var(--font-display);
		font-size: 1.15rem;
		font-weight: 600;
		color: var(--text);
		overflow-wrap: anywhere;
	}

	.failure {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin: 0;
		padding: 0.5rem 0.8rem;
		font-size: 0.85rem;
		text-align: left;
		color: var(--score-bad);
		background: color-mix(in srgb, var(--score-bad) 8%, transparent);
		border: 1px solid color-mix(in srgb, var(--score-bad) 15%, transparent);
		border-radius: 4px;
	}

	.failure :global(svg) {
		flex-shrink: 0;
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		gap: 0.75rem;
		width: 100%;
	}

	.actions :global(.sign-in-action) {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 0.4rem;
		min-height: var(--hitbox-frequent);
		box-sizing: border-box;
		padding: var(--btn-padding-pill);
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-pill);
		background: none;
		color: var(--text);
		font-family: var(--font-display);
		font-size: var(--btn-font-size);
		font-weight: 600;
		letter-spacing: var(--btn-letter-spacing);
		text-transform: uppercase;
		text-decoration: none;
		cursor: pointer;
	}

	.actions :global(.sign-in-action.primary) {
		border: none;
		color: white;
		background: linear-gradient(
			135deg,
			var(--primary),
			color-mix(in srgb, var(--primary) 80%, black)
		);
	}

	.actions :global(.sign-in-action:hover),
	.actions :global(.sign-in-action:focus-visible) {
		box-shadow: 0 4px 20px color-mix(in srgb, var(--primary) 30%, transparent);
	}

	.legal-links {
		text-align: center;
		margin-top: 1.5rem;
		font-size: 0.7rem;
		position: relative;
		z-index: 1;
	}

	@media (max-width: 480px) {
		.sign-in-card {
			padding: 2rem 1.5rem 1.5rem;
		}

		.logo {
			font-size: 1.8rem;
		}
	}
</style>
