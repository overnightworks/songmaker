<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import '../app.css';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { checkSetupRequired, fetchCapabilities } from '$lib/api/client';
	import PlayerBar from '$lib/components/PlayerBar.svelte';
	import { checkAuth, currentUser, authLoading, logout } from '$lib/stores/auth';
	import { playback } from '$lib/stores/player';
	import { canGoBack, deselectSong } from '$lib/stores/navigation';

	let { children } = $props();

	let isPublicRoute = $derived(
		page.url.pathname === '/login' ||
			page.url.pathname === '/setup' ||
			page.url.pathname.startsWith('/share/') ||
			page.url.pathname.startsWith('/legal')
	);
	const isSettings = $derived(page.url.pathname.startsWith('/settings'));
	const hasBack = $derived(isSettings || $canGoBack);
	const me = $derived($currentUser);
	const hasPlayback = $derived($playback !== null);

	$effect(() => {
		initAuth();
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
	<title>Hallucinai</title>
	<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
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
			{:else if hasBack}
				<button class="back-btn" onclick={deselectSong} aria-label="Back to songs">←</button>
			{/if}
			<a href="/" class="brand" data-text="Hallucinai">Hallucinai</a>
		</div>
		<nav class="top-right">
			<span class="top-username">{me.username}</span>
			<a href="/settings">Settings</a>
			<button class="top-logout" onclick={handleLogout}>Logout</button>
		</nav>
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
		background: #0a0a0a;
		border-bottom: 2px solid var(--primary);
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 16px;
		z-index: 200;
	}

	.top-left {
		display: flex;
		align-items: center;
		gap: 12px;
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
	}

	.back-btn:hover {
		color: var(--primary);
	}

	.brand {
		font-family: var(--font-display);
		font-size: 18px;
		color: var(--primary);
		letter-spacing: 4px;
		text-transform: uppercase;
		text-decoration: none;
		position: relative;
	}

	.brand:hover::after {
		content: attr(data-text);
		position: absolute;
		top: 0;
		left: 0;
		color: #a020f0;
		clip-path: inset(0 0 50% 0);
		animation: brand-glitch 0.3s steps(2) infinite;
	}

	@keyframes brand-glitch {
		0% { transform: translate(0); }
		50% { transform: translate(2px, -1px); }
		100% { transform: translate(-1px, 1px); }
	}

	.top-right {
		display: flex;
		align-items: center;
		gap: 12px;
		font-size: 0.8rem;
	}

	.top-username {
		color: var(--text-dim);
		max-width: 150px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.top-right a {
		color: var(--text-muted);
		text-decoration: none;
	}

	.top-right a:hover {
		color: var(--text);
	}

	.top-logout {
		background: none;
		border: 1px solid var(--border);
		border-radius: 3px;
		color: var(--text-muted);
		padding: 3px 8px;
		cursor: pointer;
		font-size: 0.75rem;
		font-family: var(--font-body);
	}

	.top-logout:hover {
		color: var(--score-bad);
		border-color: var(--score-bad);
	}

	.app-body {
		margin-top: var(--header-height);
		height: calc(100dvh - var(--header-height));
		display: flex;
		overflow: hidden;
	}

	.app-body.has-player {
		height: calc(100dvh - var(--header-height) - var(--player-height));
	}

	@media (max-width: 768px) {
		.top-username {
			display: none;
		}
	}
</style>
