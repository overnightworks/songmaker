<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import '../app.css';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { checkSetupRequired } from '$lib/api/client';
	import PlayerBar from '$lib/components/PlayerBar.svelte';
	import { checkAuth, currentUser, authLoading } from '$lib/stores/auth';

	let { children } = $props();

	const PUBLIC_ROUTES = ['/login', '/setup'];
	let isPublicRoute = $derived(PUBLIC_ROUTES.includes(page.url.pathname));

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
</script>

<svelte:head>
	<title>Songmaker</title>
</svelte:head>

{#if isPublicRoute}
	{@render children()}
{:else if $authLoading}
	<div class="loading">Loading...</div>
{:else if $currentUser}
	<div class="app-shell">
		{@render children()}
	</div>
	<PlayerBar />
{/if}

<style>
	.app-shell {
		display: flex;
		height: calc(100vh - var(--player-height));
		overflow: hidden;
	}

	.loading {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100vh;
		color: var(--text-muted);
		font-size: 1.1rem;
	}
</style>
