<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import '../app.css';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { checkSetupRequired, fetchCapabilities } from '$lib/api/client';
	import HeaderMenu from '$lib/components/HeaderMenu.svelte';
	import PlayerBar from '$lib/components/PlayerBar.svelte';
	import { APP_NAME } from '$lib/constants';
	import { HITBOX_STYLE } from '$lib/styles/hitbox';
	import { checkAuth, currentUser, authLoading, logout } from '$lib/stores/auth';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import { canGoBack, goBack, isLibraryWorkspacePath } from '$lib/stores/navigation';
	import { initTheme } from '$lib/stores/ui';
	import { dev, browser } from '$app/environment';

	let { children } = $props();

	let isPublicRoute = $derived(
		page.url.pathname === '/login' ||
			page.url.pathname === '/setup' ||
			page.url.pathname.startsWith('/share/') ||
			page.url.pathname.startsWith('/legal')
	);
	const isSettings = $derived(page.url.pathname.startsWith('/settings'));
	const hasLibraryBack = $derived(isLibraryWorkspacePath(page.url.pathname) && $canGoBack);
	const me = $derived($currentUser);
	const hasPlayback = $derived(audioPlayer.current !== null);

	$effect(() => {
		initTheme();
		initAuth();
		if (!dev && browser && 'serviceWorker' in navigator) {
			navigator.serviceWorker.register('/service-worker.js').catch(() => {
				// SW registration failure is non-fatal — the app still works online.
			});
		}
		if (!browser) return;
		const sheet = document.createElement('style');
		sheet.dataset.hitboxStyles = 'true';
		sheet.textContent = HITBOX_STYLE;
		document.head.append(sheet);
		return () => sheet.remove();
	});

	async function initAuth() {
		if (isPublicRoute) {
			authLoading.set(false);
			return;
		}

		const user = await checkAuth();
		if (user) {
			fetchCapabilities().catch(() => {});
		}
		if (!user) {
			try {
				const { required } = await checkSetupRequired();
				if (required) {
					await goto('/setup', { replaceState: true });
				} else {
					await goto('/login', { replaceState: true });
				}
			} catch {
				await goto('/login', { replaceState: true });
			}
		}
	}

	async function handleLogout() {
		await logout();
		window.location.href = '/login';
	}
</script>

<svelte:head>
	<title>{APP_NAME}</title>
	<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
	<link rel="manifest" href="/manifest.webmanifest" />
</svelte:head>

{#if isPublicRoute}
	{@render children()}
{:else if $authLoading}
	<div class="loading">Loading...</div>
{:else if me}
	<header class="top-bar">
		<div class="top-left">
			{#if isSettings}
				<a href="/" class="back-btn" aria-label="Back to home">←</a>
			{:else if hasLibraryBack}
				<button class="back-btn" onclick={goBack} aria-label="Back">←</button>
			{/if}
			<a href="/" class="brand" data-text={APP_NAME}>{APP_NAME}</a>
		</div>
		<HeaderMenu username={me.username} onlogout={handleLogout} />
	</header>

	<div class="app-body" class:has-player={hasPlayback}>
		{@render children()}
	</div>

	{#if hasPlayback}
		<PlayerBar />
	{/if}
{/if}

<style>
	.loading {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100dvh;
		color: var(--text-muted);
		font-size: 1.1rem;
	}

	.top-bar {
		position: fixed;
		top: 0;
		left: 0;
		right: 0;
		height: var(--header-height);
		background: var(--header-bg);
		border-bottom: 2px solid transparent;
		border-image: linear-gradient(90deg, var(--primary), var(--accent), var(--primary)) 1;
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 16px;
		min-width: 0;
		z-index: 200;
	}

	.top-left {
		display: flex;
		align-items: center;
		gap: 12px;
		min-width: 0;
		flex-shrink: 1;
	}

	.back-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 20px;
		cursor: pointer;
		padding: 4px;
		flex-shrink: 0;
	}

	.back-btn:hover {
		color: var(--primary);
	}

	.brand {
		font-family: var(--font-display);
		font-size: 18px;
		font-weight: 700;
		background: linear-gradient(90deg, var(--primary), var(--accent), var(--primary));
		background-size: 200% 100%;
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
		letter-spacing: 4px;
		text-transform: uppercase;
		text-decoration: none;
		position: relative;
		text-shadow: none;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	@media (prefers-reduced-motion: no-preference) {
		.brand {
			animation: brand-shimmer 4s ease-in-out infinite;
		}
	}

	@keyframes brand-shimmer {
		0%,
		100% {
			background-position: 0% 50%;
		}
		50% {
			background-position: 100% 50%;
		}
	}

	.brand::before,
	.brand::after {
		content: attr(data-text);
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		background: inherit;
		background-size: inherit;
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
		pointer-events: none;
		opacity: 0;
	}

	@media (prefers-reduced-motion: no-preference) {
		.brand::before {
			color: var(--primary);
			clip-path: inset(0 0 65% 0);
			animation: brand-glitch-top 4s steps(2) infinite;
		}

		.brand::after {
			color: var(--accent);
			clip-path: inset(60% 0 0 0);
			animation: brand-glitch-bottom 4s steps(2) infinite;
		}

		.brand:hover::before,
		.brand:hover::after {
			opacity: 0.8;
			animation-duration: 0.2s;
		}
	}

	@keyframes brand-glitch-top {
		0%,
		92% {
			opacity: 0;
			transform: translate(0);
		}
		93% {
			opacity: 0.6;
			transform: translate(2px, -1px);
		}
		94% {
			opacity: 0;
			transform: translate(-1px, 1px);
		}
		95%,
		100% {
			opacity: 0;
			transform: translate(0);
		}
	}

	@keyframes brand-glitch-bottom {
		0%,
		94% {
			opacity: 0;
			transform: translate(0);
		}
		95% {
			opacity: 0.6;
			transform: translate(-2px, 1px);
		}
		96% {
			opacity: 0;
			transform: translate(1px, -1px);
		}
		97%,
		100% {
			opacity: 0;
			transform: translate(0);
		}
	}

	.app-body {
		margin-top: var(--header-height);
		height: calc(100dvh - var(--header-height));
		display: flex;
		overflow: hidden;
		position: relative;
	}

	@media (prefers-reduced-motion: no-preference) {
		.app-body::before {
			content: '';
			position: fixed;
			inset: 0;
			background:
				radial-gradient(ellipse at 20% 50%, var(--glow-accent), transparent 70%),
				radial-gradient(ellipse at 80% 50%, var(--glow-primary), transparent 70%);
			pointer-events: none;
			z-index: 0;
		}
	}

	.app-body.has-player {
		height: calc(100dvh - var(--header-height) - var(--player-height));
	}

	@media (max-width: 768px) {
		.top-bar {
			padding: 0 8px;
			gap: 8px;
		}

		.brand {
			font-size: 14px;
			letter-spacing: 1px;
		}
	}

	:global(html[data-pointer='coarse']) .top-bar {
		padding: 0 8px;
		gap: 8px;
	}

	:global(html[data-pointer='coarse']) .brand {
		font-size: 14px;
		letter-spacing: 1px;
	}
</style>
