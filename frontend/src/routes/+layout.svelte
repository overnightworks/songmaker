<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import '../app.css';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { checkSetupRequired } from '$lib/api/client';
	import PlayerBar from '$lib/components/PlayerBar.svelte';
	import { checkAuth, currentUser, authLoading, isAdmin, logout } from '$lib/stores/auth';
	import { playback } from '$lib/stores/player';
	import { sidebarOpen, toggleSidebar, closeSidebar } from '$lib/stores/ui';

	let { children } = $props();

	const PUBLIC_ROUTES = ['/login', '/setup'];
	let isPublicRoute = $derived(PUBLIC_ROUTES.includes(page.url.pathname));
	const me = $derived($currentUser);
	const admin = $derived($isAdmin);
	const hasPlayback = $derived($playback !== null);
	const sbOpen = $derived($sidebarOpen);

	$effect(() => {
		initAuth();
	});

	async function initAuth() {
		const path = page.url.pathname;
		if (PUBLIC_ROUTES.includes(path)) {
			authLoading.set(false);
			return;
		}

		const user = await checkAuth();
		if (!user) {
			try {
				const { required } = await checkSetupRequired();
				if (required) {
					await goto('/setup');
				} else {
					await goto('/login');
				}
			} catch {
				await goto('/login');
			}
		}
	}

	async function handleLogout() {
		await logout();
		window.location.href = '/login';
	}
</script>

<svelte:head>
	<title>Songmaker</title>
</svelte:head>

{#if isPublicRoute}
	{@render children()}
{:else if $authLoading}
	<div class="loading">Loading...</div>
{:else if me}
	<header class="top-bar">
		<div class="top-left">
			<button class="hamburger" onclick={toggleSidebar} aria-label="Toggle sidebar">
				{sbOpen ? '✕' : '☰'}
			</button>
			<a href="/" class="brand">Songmaker</a>
		</div>
		<nav class="top-right">
			<span class="top-username">{me.username}</span>
			<a href="/settings/account">Account</a>
			{#if admin}
				<a href="/settings/users">Admin</a>
			{/if}
			<button class="top-logout" onclick={handleLogout}>Logout</button>
		</nav>
	</header>

	{#if sbOpen}
		<button class="sidebar-overlay" onclick={closeSidebar} aria-label="Close sidebar" tabindex="-1"
		></button>
	{/if}

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
		height: 100vh;
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

	.hamburger {
		display: none;
		background: none;
		border: none;
		color: var(--text);
		font-size: 20px;
		cursor: pointer;
		padding: 4px;
	}

	.brand {
		font-family: var(--font-display);
		font-size: 18px;
		color: var(--primary);
		letter-spacing: 4px;
		text-transform: uppercase;
		text-decoration: none;
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
		height: calc(100vh - var(--header-height));
		display: flex;
		overflow: hidden;
	}

	.app-body.has-player {
		height: calc(100vh - var(--header-height) - var(--player-height));
	}

	.sidebar-overlay {
		display: none;
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		z-index: 150;
		border: none;
		cursor: default;
	}

	@media (max-width: 768px) {
		.hamburger {
			display: block;
		}

		.top-username {
			display: none;
		}

		.sidebar-overlay {
			display: block;
		}
	}
</style>
