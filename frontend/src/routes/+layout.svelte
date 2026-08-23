<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import '../app.css';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { checkSetupRequired, fetchCapabilities } from '$lib/api/client';
	import Rail from '$lib/components/shell/Rail.svelte';
	import RailDrawer from '$lib/components/shell/RailDrawer.svelte';
	import PlayerBar from '$lib/components/PlayerBar.svelte';
	import { APP_NAME, RAIL_DRAWER_OPEN_LABEL, RAIL_LIBRARY_LABEL } from '$lib/constants';
	import { AUTH_CHECK_RETRY_LABEL } from '$lib/constants/auth';
	import { HITBOX_STYLE } from '$lib/styles/hitbox';
	import { checkAuth, currentUser, authLoading, authCheckError, logout } from '$lib/stores/auth';
	import { backToCollection, openLibraryWall } from '$lib/stores/navigation';
	import { openCollection } from '$lib/stores/collection';
	import { escapeNowPlaying, nowPlayingSurface, selectedSongId } from '$lib/stores/player';
	import { sidebarOpen, toggleSidebar, initTheme } from '$lib/stores/ui';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';
	import { escapeLevelUpTarget, shouldHandleGlobalEscape } from '$lib/utils/escape-level-up';
	import { dev, browser } from '$app/environment';
	import { get } from 'svelte/store';

	let { children } = $props();

	let isPublicRoute = $derived(
		page.url.pathname === '/login' ||
			page.url.pathname === '/setup' ||
			page.url.pathname.startsWith('/share/') ||
			page.url.pathname.startsWith('/legal')
	);
	const me = $derived($currentUser);
	const hasPrivatePlayer = $derived(me !== null);
	const authRetryable = $derived($authCheckError !== null && me === null);

	let compact = $state(false);

	$effect(() => {
		return subscribeCompactLayout((value) => {
			compact = value;
		});
	});

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
			return;
		}
		if (get(authCheckError)) {
			return;
		}
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

	async function handleLogout() {
		await logout();
		window.location.href = '/login';
	}

	function onWindowKeydown(event: KeyboardEvent): void {
		if (!shouldHandleGlobalEscape(event, document)) return;
		const target = escapeLevelUpTarget(
			$nowPlayingSurface === 'docked',
			$selectedSongId !== null,
			$openCollection !== null
		);
		if (target === 'now-playing') escapeNowPlaying();
		else if (target === 'collection') backToCollection();
		else if (target === 'wall') void openLibraryWall();
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

<svelte:head>
	<title>{APP_NAME}</title>
	<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
	<link rel="manifest" href="/manifest.webmanifest" />
</svelte:head>

{#if isPublicRoute}
	{@render children()}
{:else if $authLoading}
	<div class="loading">Loading...</div>
{:else if authRetryable}
	<div class="auth-retry">
		<p>{$authCheckError}</p>
		<button type="button" onclick={initAuth}>{AUTH_CHECK_RETRY_LABEL}</button>
	</div>
{:else if me}
	{#if compact}
		<header class="mobile-strip">
			<button
				class="drawer-trigger"
				data-hitbox="frequent"
				data-hitbox-face
				aria-haspopup="dialog"
				aria-expanded={$sidebarOpen}
				aria-label={RAIL_DRAWER_OPEN_LABEL}
				onclick={toggleSidebar}
			>
				<svg
					width="20"
					height="20"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"
				>
					<line x1="4" y1="7" x2="20" y2="7" />
					<line x1="4" y1="12" x2="20" y2="12" />
					<line x1="4" y1="17" x2="20" y2="17" />
				</svg>
			</button>
			<button
				type="button"
				class="brand"
				onclick={() => openLibraryWall()}
				aria-label={RAIL_LIBRARY_LABEL}
				data-text={APP_NAME}>{APP_NAME}</button
			>
		</header>
		<RailDrawer>
			<Rail username={me.username} onlogout={handleLogout} />
		</RailDrawer>
		<div class="app-shell mobile" class:has-player={hasPrivatePlayer}>
			{@render children()}
		</div>
	{:else}
		<div class="shell-row" class:has-player={hasPrivatePlayer}>
			<Rail username={me.username} onlogout={handleLogout} />
			<div class="app-shell desktop">
				{@render children()}
			</div>
		</div>
	{/if}

	{#if hasPrivatePlayer}
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

	.auth-retry {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 12px;
		height: 100dvh;
		color: var(--text-muted);
		font-size: 1.1rem;
		text-align: center;
		padding: 0 24px;
	}

	.auth-retry button {
		background: var(--accent);
		color: var(--bg);
		border: none;
		border-radius: 6px;
		padding: 8px 20px;
		font-size: 0.95rem;
		cursor: pointer;
	}

	.mobile-strip {
		position: fixed;
		top: 0;
		left: 0;
		right: 0;
		height: var(--header-height);
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 0 12px;
		background: var(--header-bg);
		border-bottom: 1px solid var(--border);
		z-index: 200;
	}

	.brand {
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		font-family: var(--font-display);
		font-size: 16px;
		font-weight: 700;
		color: var(--accent);
		letter-spacing: 3px;
		text-transform: uppercase;
		text-decoration: none;
	}

	.shell-row {
		display: flex;
		height: 100dvh;
		overflow: hidden;
	}

	.shell-row.has-player {
		height: calc(100dvh - var(--player-height));
	}

	.app-shell.desktop {
		flex: 1;
		min-width: 0;
		min-height: 0;
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}

	.app-shell.mobile {
		margin-top: var(--header-height);
		height: calc(100dvh - var(--header-height));
		overflow: hidden;
		display: flex;
		flex-direction: column;
	}

	.app-shell.mobile.has-player {
		height: calc(100dvh - var(--header-height) - var(--player-height));
	}
</style>
